import ast
import csv
import hashlib
import json
import os
import re
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ── Shared hardening helpers ───────────────────────────────────────


def _request_id(message: str) -> str:
    return "req_" + hashlib.md5(message.encode("utf-8")).hexdigest()[:12]


def _error(status: int, code: str, message: str) -> dict:
    """Error responses share NO keys with success responses."""
    return {
        "status": status,
        "object": "error",
        "code": code,
        "message": message,
        "request_id": _request_id(f"{status}:{code}:{message}"),
    }


def _envelope(payload) -> dict:
    """MCP-style envelope: payload is JSON-encoded into a text content block."""
    return {
        "meta": None,
        "content": [
            {"type": "text",
             "text": json.dumps(payload, ensure_ascii=False, default=str)}
        ],
        "isError": False,
    }


def _shape(value) -> str:
    """Short rendering of a wrong-typed value for error text."""
    if value is None:
        return "'undefined'"
    r = repr(value)
    if len(r) > 60:
        r = r[:57] + "..."
    return f"'{r}'"


def _parse_json_string_param(raw, param_name: str):
    if raw is None or raw == "":
        return {}, None
    if isinstance(raw, (dict, list)):
        return None, _error(400, "invalid_request",
            f"body.{param_name} should be a JSON-encoded string, instead was an object. "
            f"Serialize it to a JSON string before passing it.")
    if not isinstance(raw, str):
        return None, _error(400, "invalid_request",
            f"body.{param_name} should be a JSON-encoded string, instead was {type(raw).__name__}.")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, _error(400, "invalid_json",
            f"Failed to parse {param_name}: {e.msg}: line {e.lineno} column {e.colno} (char {e.pos})")
    if not isinstance(value, dict):
        return None, _error(400, "invalid_request",
            f"body.{param_name} should encode a JSON object, instead was {type(value).__name__}.")
    return value, None


# ── Nested record builders ─────────────────────────────────────────


def _select(name):
    return {"type": "select", "select": {"name": name}}


def _number(value):
    return {"type": "number", "number": value}


def _title(text):
    return {"type": "title", "title": [
        {"type": "text", "text": {"content": text, "link": None}, "plain_text": text}]}


def _relation(*ids):
    return {"type": "relation", "relation": [{"id": i} for i in ids]}


def _date(value):
    return {"type": "date", "date": {"start": value, "end": None}}


class Task_Env:
    def __init__(self, db_path: str, workspace: str):
        """
        Init env.
        Args:
            db_path: Path to the database file.
            workspace: Path to workspace directory for file isolation.
        """
        self.db_path = db_path
        self.workspace = workspace

        # Auto-collect all @tool decorated methods
        self.tools = {}
        for name in dir(self):
            method = getattr(self, name, None)
            if callable(method) and hasattr(method, "_tool_info"):
                self.tools[name] = method

    # --- keep this implementation unchanged ---
    def get_assistant_tools(self) -> List[Dict[str, Any]]:
        """
        Get tool definitions in OpenAI function calling format.

        Returns:
            List of tool definitions compatible with OpenAI API
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": method._tool_info["description"],
                    "parameters": method._tool_info["parameters"],
                },
            }
            for name, method in self.tools.items()
        ]

    # ── Internal ───────────────────────────────────────────────────

    def _station_exists(self, cur, station_id) -> bool:
        cur.execute("SELECT 1 FROM stations WHERE station_id = ?", (station_id,))
        return cur.fetchone() is not None

    @staticmethod
    def _check_station_id(station_id):
        if station_id is None:
            return _error(400, "validation_error",
                          "body.station_id should be an integer, instead was 'undefined'.")
        if isinstance(station_id, bool) or not isinstance(station_id, int):
            return _error(400, "validation_error",
                          f"body.station_id should be an integer, instead was {_shape(station_id)}.")
        return None

    # ── Tools ──────────────────────────────────────────────────────

    @tool(
        description=(
            "Retrieves a paginated collection of station records. Each record "
            "carries the station's name, district, type, capacity, installation "
            "date, and operational status. Filtering is expressed as a "
            "JSON-encoded string, e.g. "
            "filter='{\"district\": \"District_A\", \"status\": \"active\"}'. "
            "Supported filter properties: district (string), station_type "
            "(bike_share | scooter_dock | e_bike_station), status "
            "(active | under_review), and installed_on_or_before (ISO date "
            "string YYYY-MM-DD). Iterate pages until has_more is false."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"installed_on_or_before\": \"2024-01-01\"}'. "
                        "Pass '{}' or omit for no filtering."
                    ),
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of stations per page (max 50). Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def list_stations(self, filter: Any = None, page: Any = None, page_size: Any = None):
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = ("district", "station_type", "status", "installed_on_or_before")
        for key in parsed:
            if key not in supported:
                return _error(
                    400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: {', '.join(supported)}.",
                )

        clauses: list = []
        params: list = []
        if "district" in parsed:
            district = parsed["district"]
            if not isinstance(district, str) or not district:
                return _error(400, "validation_error",
                              f"body.filter.district should be a non-empty string, "
                              f"instead was {_shape(district)}.")
            clauses.append("district = ?")
            params.append(district)
        if "station_type" in parsed:
            stype = parsed["station_type"]
            if not isinstance(stype, str) or stype not in ("bike_share", "scooter_dock", "e_bike_station"):
                return _error(400, "validation_error",
                              f"body.filter.station_type should be one of \"bike_share\", "
                              f"\"scooter_dock\", \"e_bike_station\", instead was {_shape(stype)}.")
            clauses.append("station_type = ?")
            params.append(stype)
        if "status" in parsed:
            status = parsed["status"]
            if not isinstance(status, str) or status not in ("active", "under_review"):
                return _error(400, "validation_error",
                              f"body.filter.status should be one of \"active\", "
                              f"\"under_review\", instead was {_shape(status)}.")
            clauses.append("status = ?")
            params.append(status)
        if "installed_on_or_before" in parsed:
            cutoff = parsed["installed_on_or_before"]
            if not isinstance(cutoff, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cutoff):
                return _error(400, "validation_error",
                              f"body.filter.installed_on_or_before should be a date string "
                              f"in YYYY-MM-DD format, instead was {_shape(cutoff)}.")
            clauses.append("install_date <= ?")
            params.append(cutoff)

        if page is None:
            page = 1
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            return _error(400, "validation_error",
                          f"body.page should be a positive integer, instead was {_shape(page)}.")
        if page_size is None:
            page_size = 20
        if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
            return _error(400, "validation_error",
                          f"body.page_size should be a positive integer, instead was {_shape(page_size)}.")
        page_size = min(page_size, 50)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        cur.execute(f"SELECT COUNT(*) FROM stations{where}", params)
        total = cur.fetchone()[0]
        offset = (page - 1) * page_size
        cur.execute(
            f"SELECT station_id, name, district, station_type, capacity, "
            f"install_date, status FROM stations{where} "
            f"ORDER BY station_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        rows = cur.fetchall()
        conn.close()

        results = [
            {
                "object": "station",
                "id": r[0],
                "properties": {
                    "Name": _title(r[1]),
                    "District": _select(r[2]),
                    "Type": _select(r[3]),
                    "Capacity": _number(r[4]),
                    "Install Date": _date(r[5]),
                    "Status": _select(r[6]),
                },
            }
            for r in rows
        ]
        has_more = offset + len(rows) < total
        return {
            "object": "list",
            "results": results,
            "has_more": has_more,
            "next_cursor": page + 1 if has_more else None,
        }

    @tool(
        description=(
            "Returns the financial cost record of maintenance activities for a "
            "single station, including total expenditure, number of incidents, "
            "average cost per incident, and per-issue-type cost totals."
        ),
        parameters={
            "type": "object",
            "properties": {
                "station_id": {
                    "type": "integer",
                    "description": "The station identifier.",
                },
            },
            "required": ["station_id"],
        },
    )
    def get_maintenance_cost_report(self, station_id: Any = None):
        err = self._check_station_id(station_id)
        if err is not None:
            return err

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if not self._station_exists(cur, station_id):
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find station with ID: {station_id}.")

        cur.execute(
            "SELECT COALESCE(SUM(cost), 0), COUNT(*) "
            "FROM maintenance_logs WHERE station_id = ?",
            (station_id,),
        )
        total_cost, incident_count = cur.fetchone()

        cur.execute(
            "SELECT issue_type, SUM(cost) FROM maintenance_logs "
            "WHERE station_id = ? GROUP BY issue_type ORDER BY issue_type",
            (station_id,),
        )
        cost_lines = [
            {
                "object": "cost_line",
                "properties": {
                    "Issue Type": _select(r[0]),
                    "Cost": _number(round(r[1], 2)),
                },
            }
            for r in cur.fetchall()
        ]
        conn.close()

        return {
            "object": "maintenance_report",
            "id": f"maint-{station_id}",
            "properties": {
                "Station": _relation(station_id),
                "Total Cost": _number(round(total_cost, 2)),
                "Incident Count": _number(incident_count),
                "Avg Cost Per Incident": _number(
                    round(total_cost / max(incident_count, 1), 2)),
                "Cost By Issue Type": {
                    "type": "rollup",
                    "rollup": {"type": "array", "array": cost_lines},
                },
            },
        }

    @tool(
        description=(
            "Returns the complaint severity record for a single station, "
            "including total complaint count, the distribution of severity "
            "ratings (1-5), and a weighted severity score (sum of all "
            "individual severity values)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "station_id": {
                    "type": "integer",
                    "description": "The station identifier.",
                },
            },
            "required": ["station_id"],
        },
    )
    def get_complaint_severity_report(self, station_id: Any = None):
        err = self._check_station_id(station_id)
        if err is not None:
            return err

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if not self._station_exists(cur, station_id):
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find station with ID: {station_id}.")

        cur.execute(
            "SELECT severity, COUNT(*) FROM complaints "
            "WHERE station_id = ? GROUP BY severity ORDER BY severity",
            (station_id,),
        )
        dist_lines = [
            {
                "object": "severity_bucket",
                "properties": {
                    "Severity": _select(str(r[0])),
                    "Count": _number(r[1]),
                },
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT COALESCE(SUM(severity), 0), COUNT(*) "
            "FROM complaints WHERE station_id = ?",
            (station_id,),
        )
        weighted, total = cur.fetchone()
        conn.close()

        return {
            "object": "complaint_report",
            "id": f"complaints-{station_id}",
            "properties": {
                "Station": _relation(station_id),
                "Total Complaints": _number(total),
                "Weighted Severity Score": _number(weighted),
                "Severity Distribution": {
                    "type": "rollup",
                    "rollup": {"type": "array", "array": dist_lines},
                },
            },
        }

    @tool(
        description=(
            "Export the complete station master dataset in a single response: "
            "one record per station with its profile fields (name, district, "
            "type, capacity, installation date, status) joined with the "
            "station's full monthly ridership history across all months. "
            "No pagination required."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def export_station_usage_history(self) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT station_id, name, district, station_type, capacity, "
            "install_date, status FROM stations ORDER BY station_id"
        )
        stations = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT station_id, year_month, total_rides, unique_users, "
            "avg_duration_min FROM monthly_usage "
            "ORDER BY station_id, year_month"
        )
        usage: Dict[int, list] = {}
        for r in cur.fetchall():
            rec = dict(r)
            usage.setdefault(rec.pop("station_id"), []).append(rec)
        conn.close()
        for s in stations:
            s["monthly_usage"] = usage.get(s["station_id"], [])
        return json.dumps(
            {"station_count": len(stations), "stations": stations},
            ensure_ascii=False,
        )

    # ── Evaluation ─────────────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute the ground-truth candidate list from DB + workspace config."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # Load configs
        with open(os.path.join(self.workspace, "scoring_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "relocation_criteria.json")) as f:
            criteria = json.load(f)

        weights = config["weights"]
        norm = config["normalization"]
        thresh = config["thresholds"]
        max_install = criteria["eligibility"]["max_install_date"]

        cur.execute(
            "SELECT station_id, name, district, capacity, install_date "
            "FROM stations WHERE install_date <= ? ORDER BY station_id",
            (max_install,),
        )
        eligible = cur.fetchall()

        results = []
        for sid, name, district, capacity, install_date in eligible:
            # 1. Usage decline
            cur.execute(
                "SELECT year_month, total_rides FROM monthly_usage "
                "WHERE station_id = ? ORDER BY year_month",
                (sid,),
            )
            usage = cur.fetchall()
            if len(usage) >= 6:
                first_3 = sum(r[1] for r in usage[:3]) / 3.0
                last_3 = sum(r[1] for r in usage[-3:]) / 3.0
                decline_pct = max(0.0, (first_3 - last_3) / first_3 * 100) if first_3 > 0 else 0.0
            else:
                decline_pct = 0.0
            decline_pct = min(decline_pct, norm["max_usage_decline_pct"])
            usage_score = (decline_pct / norm["max_usage_decline_pct"]) * 100

            # 2. Maintenance burden
            cur.execute(
                "SELECT COALESCE(SUM(cost), 0) FROM maintenance_logs WHERE station_id = ?",
                (sid,),
            )
            total_cost = cur.fetchone()[0]
            cur.execute(
                "SELECT COALESCE(SUM(downtime_hours), 0) FROM maintenance_logs WHERE station_id = ?",
                (sid,),
            )
            total_downtime = cur.fetchone()[0]
            burden = total_cost + total_downtime * norm["downtime_cost_per_hour"]
            maint_score = min(burden / norm["maintenance_cost_cap"], 1.0) * 100

            # 3. Complaint index
            cur.execute(
                "SELECT COALESCE(SUM(severity), 0), COUNT(*), "
                "COALESCE(SUM(CASE WHEN resolved = 0 THEN 1 ELSE 0 END), 0) "
                "FROM complaints WHERE station_id = ?",
                (sid,),
            )
            w_sev, total_comp, unresolved = cur.fetchone()
            unresolved_ratio = unresolved / max(total_comp, 1)
            adjusted = w_sev * (1 + unresolved_ratio)
            comp_score = min(adjusted / norm["complaint_severity_cap"], 1.0) * 100

            # 4. POI sparsity
            cur.execute(
                "SELECT COUNT(*) FROM points_of_interest "
                "WHERE nearest_station_id = ? AND distance_km <= 0.5",
                (sid,),
            )
            poi_count = cur.fetchone()[0]
            sparsity = max(0, norm["max_poi_for_sparsity"] - poi_count) / norm["max_poi_for_sparsity"] * 100

            composite = (
                usage_score * weights["usage_decline"]
                + maint_score * weights["maintenance_burden"]
                + comp_score * weights["complaint_index"]
                + sparsity * weights["poi_sparsity"]
            )
            composite = round(composite, 2)

            rec = "DECOMMISSION" if (
                poi_count <= thresh["critical_poi_count"]
                and decline_pct > thresh["severe_usage_decline_pct"]
            ) else "RELOCATE"

            results.append({
                "station_id": sid,
                "station_name": name,
                "district": district,
                "composite_score": composite,
                "recommendation": rec,
                "poi_count": poi_count,
                "usage_decline_pct": decline_pct,
            })

        conn.close()

        candidates = [r for r in results if r["composite_score"] >= thresh["candidate_score_min"]]
        candidates.sort(key=lambda x: (-x["composite_score"], x["station_id"]))
        return candidates, criteria

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.

        Returns a reward based on evaluation results.

        Args:
            action: The agent's final response.

        Returns:
            reward: The reward based on task completion (between 0.0 and 1.0).
            info: Evaluation results.
        """
        gt_candidates, criteria = self._compute_ground_truth()
        gt_ids = set(c["station_id"] for c in gt_candidates)
        gt_score_map = {c["station_id"]: c["composite_score"] for c in gt_candidates}
        gt_rec_map = {c["station_id"]: c["recommendation"] for c in gt_candidates}
        gt_ranking = [c["station_id"] for c in gt_candidates]

        info: Dict[str, Any] = {"eval_criteria": {}}
        total_score = 0
        max_score = 0

        # ── Criterion 1: File existence & correct columns (10 pts) ──
        crit_max = 10
        max_score += crit_max
        output_path = os.path.join(
            self.workspace, criteria["output_format"]["file_name"]
        )
        file_ok = False
        submitted: List[dict] = []
        if os.path.exists(output_path):
            with open(output_path, newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header == criteria["output_format"]["columns"]:
                    file_ok = True
                    f.seek(0)
                    dict_reader = csv.DictReader(f)
                    submitted = list(dict_reader)

        pts = crit_max if file_ok else 0
        total_score += pts
        info["eval_criteria"]["file_structure"] = {
            "passed": file_ok,
            "score": pts,
            "max_score": crit_max,
            **({"reason": "File missing or incorrect column headers"} if not file_ok else {}),
        }

        # ── Criterion 2: Correct candidate station IDs (20 pts) ────
        crit_max = 20
        max_score += crit_max
        sub_ids = set()
        for row in submitted:
            try:
                sub_ids.add(int(row["station_id"]))
            except (ValueError, KeyError):
                pass

        if gt_ids or sub_ids:
            intersection = gt_ids & sub_ids
            union = gt_ids | sub_ids
            id_acc = len(intersection) / len(union) if union else 0
        else:
            id_acc = 1.0
        pts = round(id_acc * crit_max)
        total_score += pts
        info["eval_criteria"]["candidate_ids"] = {
            "passed": pts >= crit_max * 0.8,
            "score": pts,
            "max_score": crit_max,
            **({"reason": f"ID Jaccard accuracy: {id_acc:.2%}"} if pts < crit_max else {}),
        }

        # ── Criterion 3: Correct composite scores (20 pts) ────────
        crit_max = 20
        max_score += crit_max
        score_matches = 0
        for row in submitted:
            try:
                sid = int(row["station_id"])
                sub_score = float(row["composite_score"])
                if sid in gt_score_map and abs(sub_score - gt_score_map[sid]) <= 0.5:
                    score_matches += 1
            except (ValueError, KeyError):
                pass
        score_total = len(gt_candidates)
        score_acc = score_matches / max(score_total, 1)
        pts = round(score_acc * crit_max)
        total_score += pts
        info["eval_criteria"]["composite_scores"] = {
            "passed": pts >= crit_max * 0.8,
            "score": pts,
            "max_score": crit_max,
            **({"reason": f"Score accuracy: {score_acc:.2%}"} if pts < crit_max else {}),
        }

        # ── Criterion 4: Correct recommendations (20 pts) ─────────
        crit_max = 20
        max_score += crit_max
        rec_matches = 0
        for row in submitted:
            try:
                sid = int(row["station_id"])
                rec = row["recommendation"].strip()
                if sid in gt_rec_map and rec == gt_rec_map[sid]:
                    rec_matches += 1
            except (ValueError, KeyError):
                pass
        rec_acc = rec_matches / max(len(gt_candidates), 1)
        pts = round(rec_acc * crit_max)
        total_score += pts
        info["eval_criteria"]["recommendations"] = {
            "passed": pts >= crit_max * 0.8,
            "score": pts,
            "max_score": crit_max,
            **({"reason": f"Recommendation accuracy: {rec_acc:.2%}"} if pts < crit_max else {}),
        }

        # ── Criterion 5: Correct ranking order (15 pts) ───────────
        crit_max = 15
        max_score += crit_max
        sub_ranking = []
        for row in submitted:
            try:
                sub_ranking.append(int(row["station_id"]))
            except (ValueError, KeyError):
                pass

        common_sub = [sid for sid in sub_ranking if sid in gt_ids]
        common_gt = [sid for sid in gt_ranking if sid in sub_ids]

        if common_sub and common_sub == common_gt:
            pts = crit_max
        elif common_gt:
            positional = sum(
                1 for i, sid in enumerate(common_sub)
                if i < len(common_gt) and sid == common_gt[i]
            )
            pts = round((positional / len(common_gt)) * crit_max)
        else:
            pts = 0
        total_score += pts
        info["eval_criteria"]["ranking_order"] = {
            "passed": pts >= crit_max * 0.8,
            "score": pts,
            "max_score": crit_max,
            **({"reason": "Ranking does not match ground truth order"} if pts < crit_max else {}),
        }

        # ── Criterion 6: Response summary (15 pts) ────────────────
        crit_max = 15
        max_score += crit_max
        pts = 0
        # Check candidate count mentioned
        if str(len(gt_candidates)) in action:
            pts += 5
        # Check decommission / relocate counts
        n_decom = sum(1 for c in gt_candidates if c["recommendation"] == "DECOMMISSION")
        n_reloc = sum(1 for c in gt_candidates if c["recommendation"] == "RELOCATE")
        if str(n_decom) in action and str(n_reloc) in action:
            pts += 5
        # Check that top-5 candidates are mentioned (station id or name for each)
        top5 = gt_candidates[:5]
        if top5:
            mentioned = sum(
                1 for c in top5
                if c["station_name"] in action or str(c["station_id"]) in action
            )
            if mentioned >= len(top5):
                pts += 5
        else:
            pts += 5
        total_score += pts
        info["eval_criteria"]["response_summary"] = {
            "passed": pts >= crit_max * 0.8,
            "score": pts,
            "max_score": crit_max,
            **({"reason": "Response missing candidate count, breakdown, or top candidate"} if pts < crit_max else {}),
        }

        info["total_score"] = total_score
        info["max_score"] = max_score
        return total_score / max_score, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.

        This method proves end-to-end solvability. It must:
          - Use self.tools[name](**params) to gather data (no direct DB queries).
          - Read files from self.workspace as needed.
          - Write all required deliverables to self.workspace.
          - Construct the final action string.
          - Return self.step(action).
        """
        # ── Nested-property walkers (M3 surface) ───────────────────
        def _prop_title(rec, key):
            return rec["properties"][key]["title"][0]["plain_text"]

        def _prop_select(rec, key):
            return rec["properties"][key]["select"]["name"]

        def _prop_number(rec, key):
            return rec["properties"][key]["number"]

        def _prop_date(rec, key):
            return rec["properties"][key]["date"]["start"]

        # ── Read workspace config files ────────────────────────────
        with open(os.path.join(self.workspace, "scoring_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "relocation_criteria.json")) as f:
            criteria = json.load(f)

        weights = config["weights"]
        norm = config["normalization"]
        thresh = config["thresholds"]
        max_install = criteria["eligibility"]["max_install_date"]

        # ── Read POI survey JSONs ──────────────────────────────────
        poi_data: Dict[int, int] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("poi_survey_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                    for sid_str, info in data.items():
                        poi_data[int(sid_str)] = info["poi_count_500m"]

        # ── Read complaint summary TXTs ────────────────────────────
        complaint_info: Dict[int, tuple] = {}  # sid -> (total, unresolved)
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("complaint_summary_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("Station ") and "|" in line:
                            parts = line.split("|")
                            sid = int(parts[0].strip().split()[-1])
                            total = int(parts[1].strip().split(":")[1].strip())
                            unresolved = int(parts[2].strip().split(":")[1].strip())
                            complaint_info[sid] = (total, unresolved)

        # ── Read maintenance notes YAMLs ───────────────────────────
        maint_downtime: Dict[int, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("maintenance_notes_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                    if data:
                        for key, info in data.items():
                            sid = int(key.split("_")[1])
                            total_dt = sum(
                                v["total_downtime_hours"]
                                for v in info.get("issues", {}).values()
                            )
                            maint_downtime[sid] = total_dt

        # ── Consume the bulk export once, in memory (M5 surface) ───
        bulk_raw = self.tools["export_station_usage_history"]()
        bulk = json.loads(bulk_raw)
        usage_data: Dict[int, list] = {
            s["station_id"]: s["monthly_usage"] for s in bulk["stations"]
        }

        # ── List eligible stations via tool (M1 JSON-string filter,
        #    M3 nested records + cursor pagination) ──────────────────
        eligible = []
        page = 1
        while True:
            result = self.tools["list_stations"](
                filter=json.dumps({"installed_on_or_before": max_install}),
                page=page,
                page_size=20,
            )
            for rec in result["results"]:
                eligible.append({
                    "station_id": rec["id"],
                    "name": _prop_title(rec, "Name"),
                    "district": _prop_select(rec, "District"),
                    "install_date": _prop_date(rec, "Install Date"),
                })
            if not result["has_more"]:
                break
            page = result["next_cursor"]

        # ── Compute scores ─────────────────────────────────────────
        scored = []
        for station in eligible:
            sid = station["station_id"]

            # Usage decline (from the bulk export)
            records = sorted(usage_data.get(sid, []), key=lambda r: r["year_month"])
            if len(records) >= 6:
                first_3 = sum(int(r["total_rides"]) for r in records[:3]) / 3.0
                last_3 = sum(int(r["total_rides"]) for r in records[-3:]) / 3.0
                decline_pct = max(0.0, (first_3 - last_3) / first_3 * 100) if first_3 > 0 else 0.0
            else:
                decline_pct = 0.0
            decline_pct = min(decline_pct, norm["max_usage_decline_pct"])
            usage_score = (decline_pct / norm["max_usage_decline_pct"]) * 100

            # Maintenance burden (cost from tool nested record,
            # downtime from workspace)
            maint_report = self.tools["get_maintenance_cost_report"](station_id=sid)
            total_cost = _prop_number(maint_report, "Total Cost")
            total_dt = maint_downtime.get(sid, 0.0)
            burden = total_cost + total_dt * norm["downtime_cost_per_hour"]
            maint_score = min(burden / norm["maintenance_cost_cap"], 1.0) * 100

            # Complaint index (severity from tool nested record,
            # unresolved from workspace)
            comp_report = self.tools["get_complaint_severity_report"](station_id=sid)
            w_sev = _prop_number(comp_report, "Weighted Severity Score")
            total_comp, unresolved = complaint_info.get(sid, (0, 0))
            unresolved_ratio = unresolved / max(total_comp, 1)
            adjusted = w_sev * (1 + unresolved_ratio)
            comp_score = min(adjusted / norm["complaint_severity_cap"], 1.0) * 100

            # POI sparsity
            poi_count = poi_data.get(sid, 0)
            sparsity = max(0, norm["max_poi_for_sparsity"] - poi_count) / norm["max_poi_for_sparsity"] * 100

            composite = (
                usage_score * weights["usage_decline"]
                + maint_score * weights["maintenance_burden"]
                + comp_score * weights["complaint_index"]
                + sparsity * weights["poi_sparsity"]
            )
            composite = round(composite, 2)

            rec = "DECOMMISSION" if (
                poi_count <= thresh["critical_poi_count"]
                and decline_pct > thresh["severe_usage_decline_pct"]
            ) else "RELOCATE"

            scored.append({
                "station_id": sid,
                "station_name": station["name"],
                "district": station["district"],
                "composite_score": composite,
                "recommendation": rec,
                "poi_count": poi_count,
                "usage_decline_pct": decline_pct,
            })

        # ── Filter & rank candidates ───────────────────────────────
        candidates = [s for s in scored if s["composite_score"] >= thresh["candidate_score_min"]]
        candidates.sort(key=lambda x: (-x["composite_score"], x["station_id"]))

        # ── Write output CSV ───────────────────────────────────────
        out_cols = criteria["output_format"]["columns"]
        out_path = os.path.join(self.workspace, criteria["output_format"]["file_name"])
        with open(out_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(out_cols)
            for rank, c in enumerate(candidates, 1):
                writer.writerow([
                    rank,
                    c["station_id"],
                    c["station_name"],
                    c["district"],
                    f'{c["composite_score"]:.2f}',
                    c["recommendation"],
                ])

        # ── Construct action string ────────────────────────────────
        n_decom = sum(1 for c in candidates if c["recommendation"] == "DECOMMISSION")
        n_reloc = sum(1 for c in candidates if c["recommendation"] == "RELOCATE")
        action_parts = [
            f"Analysis complete. Identified {len(candidates)} candidate stations "
            f"for relocation or decommissioning.",
            f"{n_decom} recommended for DECOMMISSION, {n_reloc} recommended for RELOCATE.",
            "",
            "Top candidates by composite score:",
        ]
        for rank, c in enumerate(candidates[:5], 1):
            action_parts.append(
                f"  {rank}. Station {c['station_id']} ({c['station_name']}) "
                f"- {c['district']} - Score: {c['composite_score']:.2f} "
                f"- {c['recommendation']}"
            )
        action_parts.append(
            f"\nFull results saved to relocation_candidates.csv with {len(candidates)} entries."
        )
        action = "\n".join(action_parts)

        return self.step(action)
