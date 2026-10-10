import sqlite3
import json
import csv
import os
import re
from typing import Tuple, Dict, List, Any
from datetime import datetime, timedelta


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


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

    # ----------------------------------------------------------------
    # Tool methods
    # ----------------------------------------------------------------

    @tool(
        description="List train services with optional filtering and pagination.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Default 20.",
                },
                "operator": {
                    "type": "string",
                    "description": "Filter by operator name (exact match).",
                },
                "train_type": {
                    "type": "string",
                    "description": "Filter by train type (intercity, express, regional, commuter, freight).",
                },
            },
            "required": [],
        },
    )
    def list_trains(
        self,
        page: int = 1,
        page_size: int = 20,
        operator: str = None,
        train_type: str = None,
    ):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        q = "SELECT * FROM trains WHERE 1=1"
        params = []
        if operator:
            q += " AND operator = ?"
            params.append(operator)
        if train_type:
            q += " AND train_type = ?"
            params.append(train_type)
        q += " ORDER BY train_id"
        total = conn.execute(
            q.replace("SELECT *", "SELECT COUNT(*)"), params
        ).fetchone()[0]
        q += " LIMIT ? OFFSET ?"
        params.extend([page_size, (page - 1) * page_size])
        rows = conn.execute(q, params).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "results": [dict(r) for r in rows],
        }

    @tool(
        description="Get details for a single train service by its service code.",
        parameters={
            "type": "object",
            "properties": {
                "service_code": {
                    "type": "string",
                    "description": "The unique service code of the train (e.g. '3A42').",
                },
            },
            "required": ["service_code"],
        },
    )
    def get_train_by_code(self, service_code: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM trains WHERE service_code = ?", (service_code,)
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"No train found with service_code '{service_code}'."}

    @tool(
        description="List route sections with pagination.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Default 20.",
                },
            },
            "required": [],
        },
    )
    def list_route_sections(self, page: int = 1, page_size: int = 20):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM route_sections").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM route_sections ORDER BY section_id LIMIT ? OFFSET ?",
            (page_size, (page - 1) * page_size),
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "results": [dict(r) for r in rows],
        }

    @tool(
        description="Get full details for a single route section by section_id.",
        parameters={
            "type": "object",
            "properties": {
                "section_id": {
                    "type": "integer",
                    "description": "The numeric ID of the route section.",
                },
            },
            "required": ["section_id"],
        },
    )
    def get_route_section(self, section_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM route_sections WHERE section_id = ?", (section_id,)
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"No section found with section_id {section_id}."}

    @tool(
        description=(
            "Get maintenance possession blocks for a given route section, "
            "optionally filtered by date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "section_id": {
                    "type": "integer",
                    "description": "The route section ID.",
                },
                "date": {
                    "type": "string",
                    "description": (
                        "Optional date (YYYY-MM-DD) to filter blocks "
                        "that overlap this date."
                    ),
                },
            },
            "required": ["section_id"],
        },
    )
    def get_maintenance_blocks(self, section_id: int, date: str = None):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if date:
            day_start = f"{date} 00:00"
            day_end = f"{date} 23:59"
            rows = conn.execute(
                "SELECT * FROM maintenance_possessions "
                "WHERE section_id = ? AND start_datetime <= ? AND end_datetime >= ? "
                "ORDER BY start_datetime",
                (section_id, day_end, day_start),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM maintenance_possessions "
                "WHERE section_id = ? ORDER BY start_datetime",
                (section_id,),
            ).fetchall()
        conn.close()
        return {"section_id": section_id, "blocks": [dict(r) for r in rows]}

    @tool(
        description="Get details and capacity for a junction by junction_id.",
        parameters={
            "type": "object",
            "properties": {
                "junction_id": {
                    "type": "integer",
                    "description": "The numeric ID of the junction.",
                },
            },
            "required": ["junction_id"],
        },
    )
    def get_junction_details(self, junction_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM junctions WHERE junction_id = ?", (junction_id,)
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"No junction found with junction_id {junction_id}."}

    @tool(
        description=(
            "Get historical punctuality records for a route section. "
            "Returns all recorded periods."
        ),
        parameters={
            "type": "object",
            "properties": {
                "section_id": {
                    "type": "integer",
                    "description": "The route section ID.",
                },
            },
            "required": ["section_id"],
        },
    )
    def get_punctuality_history(self, section_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM punctuality_history WHERE section_id = ? ORDER BY period",
            (section_id,),
        ).fetchall()
        conn.close()
        return {"section_id": section_id, "records": [dict(r) for r in rows]}

    # ----------------------------------------------------------------
    # Ground-truth computation (used by both step and verify)
    # ----------------------------------------------------------------

    def _load_proposals(self):
        """Read all schedule_batch CSV files from workspace."""
        proposals = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("schedule_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname), newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        row["section_id"] = int(row["section_id"])
                        proposals.append(row)
        return proposals

    def _parse_yaml(self, path):
        """Minimal YAML parser for flat / one-level-nested dicts."""
        result = {}
        current_key = None
        with open(path) as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.lstrip().startswith("#"):
                    continue
                if not line.startswith(" "):
                    key, _, val = line.partition(":")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if val:
                        # try numeric conversion
                        try:
                            val = int(val)
                        except ValueError:
                            try:
                                val = float(val)
                            except ValueError:
                                pass
                        result[key] = val
                    else:
                        result[key] = {}
                        current_key = key
                elif current_key is not None:
                    key, _, val = line.partition(":")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    try:
                        val = int(val)
                    except ValueError:
                        try:
                            val = float(val)
                        except ValueError:
                            pass
                    result[current_key][key] = val
        return result

    def _parse_risk_thresholds(self, path):
        """Parse risk_thresholds.txt."""
        thresholds = {}
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) == 3:
                    level, max_pct, flag = parts
                    thresholds[level] = {
                        "max_on_time_pct": float(max_pct),
                        "flag": flag.lower() == "yes",
                    }
        return thresholds

    def _compute_ground_truth(self):
        """Compute the full ground-truth conflict set and recommendations."""
        proposals = self._load_proposals()

        # Load configs
        rules = self._parse_yaml(
            os.path.join(self.workspace, "conflict_rules.yaml")
        )
        with open(os.path.join(self.workspace, "priority_matrix.json")) as f:
            matrix = json.load(f)
        risk_th = self._parse_risk_thresholds(
            os.path.join(self.workspace, "risk_thresholds.txt")
        )

        buffer_min = int(rules["maintenance_buffer_minutes"])
        jct_ratio = float(rules["junction_capacity_threshold_ratio"])
        sev_map = rules["conflict_severity"]

        # Punctuality risk threshold
        punct_threshold = None
        for lvl, info in risk_th.items():
            if info["flag"]:
                punct_threshold = info["max_on_time_pct"]
                break
        if punct_threshold is None:
            punct_threshold = 75.0

        # Direct DB access for ground truth
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        sections = {
            r["section_id"]: dict(r)
            for r in conn.execute("SELECT * FROM route_sections").fetchall()
        }
        maint_rows = conn.execute(
            "SELECT * FROM maintenance_possessions ORDER BY section_id, start_datetime"
        ).fetchall()
        maint_by_sec = {}
        for m in maint_rows:
            maint_by_sec.setdefault(m["section_id"], []).append(dict(m))

        junctions = {
            r["junction_id"]: dict(r)
            for r in conn.execute("SELECT * FROM junctions").fetchall()
        }

        punct_rows = conn.execute(
            "SELECT * FROM punctuality_history"
        ).fetchall()
        # avg on_time_pct per section
        sect_otp = {}
        sect_delay = {}
        for pr in punct_rows:
            sid = pr["section_id"]
            sect_otp.setdefault(sid, []).append(pr["on_time_percentage"])
            sect_delay.setdefault(sid, []).append(pr["avg_delay_minutes"])
        for sid in sect_otp:
            sect_otp[sid] = sum(sect_otp[sid]) / len(sect_otp[sid])
        for sid in sect_delay:
            sect_delay[sid] = sum(sect_delay[sid]) / len(sect_delay[sid])

        poor_sections = {
            sid for sid, avg in sect_otp.items() if avg <= punct_threshold
        }

        trains_by_code = {
            r["service_code"]: dict(r)
            for r in conn.execute("SELECT * FROM trains").fetchall()
        }
        conn.close()

        # ----- Detect conflicts -----
        conflicts = []

        # 1. Maintenance
        for p in proposals:
            pid = p["proposal_id"]
            sid = p["section_id"]
            dep_dt = datetime.strptime(
                f"{p['date']} {p['departure_time']}", "%Y-%m-%d %H:%M"
            )
            arr_dt = datetime.strptime(
                f"{p['date']} {p['arrival_time']}", "%Y-%m-%d %H:%M"
            )
            if arr_dt <= dep_dt:
                arr_dt += timedelta(days=1)

            if sid not in maint_by_sec:
                continue
            overlap_found = False
            buffer_found = False
            overlap_detail = ""
            buffer_detail = ""
            for mb in maint_by_sec[sid]:
                ms = datetime.strptime(mb["start_datetime"], "%Y-%m-%d %H:%M")
                me = datetime.strptime(mb["end_datetime"], "%Y-%m-%d %H:%M")
                if dep_dt < me and arr_dt > ms:
                    overlap_found = True
                    overlap_detail = (
                        f"Overlaps {mb['possession_type']} block "
                        f"{mb['start_datetime']}-{mb['end_datetime']}"
                    )
                    break
                elif dep_dt < me + timedelta(minutes=buffer_min) and \
                        arr_dt > ms - timedelta(minutes=buffer_min):
                    buffer_found = True
                    buffer_detail = (
                        f"Within {buffer_min}min buffer of "
                        f"{mb['possession_type']} block "
                        f"{mb['start_datetime']}-{mb['end_datetime']}"
                    )
            if overlap_found:
                sec_name = sections[sid]["section_name"] if sid in sections else f"SEC-{sid:03d}"
                conflicts.append({
                    "proposal_id": pid,
                    "train_service_code": p["train_service_code"],
                    "section_id": sid,
                    "section_name": sec_name,
                    "conflict_type": "maintenance_overlap",
                    "severity": sev_map["maintenance_overlap"],
                    "details": overlap_detail,
                })
            elif buffer_found:
                sec_name = sections[sid]["section_name"] if sid in sections else f"SEC-{sid:03d}"
                conflicts.append({
                    "proposal_id": pid,
                    "train_service_code": p["train_service_code"],
                    "section_id": sid,
                    "section_name": sec_name,
                    "conflict_type": "maintenance_buffer",
                    "severity": sev_map["maintenance_buffer"],
                    "details": buffer_detail,
                })

        # 2. Junction overload
        jct_hour_map = {}  # (junction_id, hour_str) -> [proposal]
        for p in proposals:
            sid = p["section_id"]
            sec = sections.get(sid)
            if not sec or sec["junction_id"] is None:
                continue
            jid = sec["junction_id"]
            dep_dt = datetime.strptime(
                f"{p['date']} {p['departure_time']}", "%Y-%m-%d %H:%M"
            )
            arr_dt = datetime.strptime(
                f"{p['date']} {p['arrival_time']}", "%Y-%m-%d %H:%M"
            )
            if arr_dt <= dep_dt:
                arr_dt += timedelta(days=1)
            hour = dep_dt.replace(minute=0, second=0, microsecond=0)
            while hour < arr_dt:
                key = (jid, hour.strftime("%Y-%m-%d %H:%M"))
                jct_hour_map.setdefault(key, []).append(p)
                hour += timedelta(hours=1)

        overloaded_proposals = set()
        overload_details = {}
        for (jid, hstr), props in jct_hour_map.items():
            jct = junctions.get(jid)
            if not jct:
                continue
            cap = jct["capacity_per_hour"]
            if len(props) > cap * jct_ratio:
                for p in props:
                    pid = p["proposal_id"]
                    if pid not in overloaded_proposals:
                        overloaded_proposals.add(pid)
                        overload_details[pid] = (
                            f"Junction {jct['junction_name']} overloaded: "
                            f"{len(props)}/{cap} trains at {hstr}"
                        )

        for p in proposals:
            pid = p["proposal_id"]
            if pid in overloaded_proposals:
                sid = p["section_id"]
                sec_name = sections[sid]["section_name"] if sid in sections else f"SEC-{sid:03d}"
                conflicts.append({
                    "proposal_id": pid,
                    "train_service_code": p["train_service_code"],
                    "section_id": sid,
                    "section_name": sec_name,
                    "conflict_type": "junction_overload",
                    "severity": sev_map["junction_overload"],
                    "details": overload_details[pid],
                })

        # 3. Punctuality risk
        for p in proposals:
            pid = p["proposal_id"]
            sid = p["section_id"]
            if sid in poor_sections:
                sec_name = sections[sid]["section_name"] if sid in sections else f"SEC-{sid:03d}"
                avg_otp = sect_otp.get(sid, 0)
                conflicts.append({
                    "proposal_id": pid,
                    "train_service_code": p["train_service_code"],
                    "section_id": sid,
                    "section_name": sec_name,
                    "conflict_type": "punctuality_risk",
                    "severity": sev_map["punctuality_risk"],
                    "details": (
                        f"Section avg on-time {avg_otp:.1f}% "
                        f"<= threshold {punct_threshold}%"
                    ),
                })

        # Sort: severity order then proposal_id
        sev_order = {"critical": 0, "major": 1, "moderate": 2, "minor": 3}
        conflicts.sort(
            key=lambda c: (sev_order.get(c["severity"], 9), c["proposal_id"])
        )
        for i, c in enumerate(conflicts):
            c["conflict_id"] = f"C{i + 1:04d}"

        # Priority scores
        sev_w = matrix["severity_weights"]
        base_m = matrix["base_multiplier"]
        tpw = matrix["train_priority_weight"]
        prw = matrix["punctuality_risk_weight"]

        recommendations = []
        for c in conflicts:
            sw = sev_w.get(c["severity"], 1)
            train = trains_by_code.get(c["train_service_code"])
            tpc = train["priority_class"] if train else 3
            avg_del = sect_delay.get(c["section_id"], 0)
            score = round(sw * base_m + tpc * tpw + avg_del * prw, 2)
            recommendations.append({
                "rank": None,
                "proposal_id": c["proposal_id"],
                "train_service_code": c["train_service_code"],
                "conflict_type": c["conflict_type"],
                "severity": c["severity"],
                "priority_score": score,
            })

        recommendations.sort(
            key=lambda r: (-r["priority_score"], r["proposal_id"])
        )
        for i, r in enumerate(recommendations):
            r["rank"] = i + 1

        # Type breakdown
        breakdown = {}
        for c in conflicts:
            breakdown[c["conflict_type"]] = breakdown.get(c["conflict_type"], 0) + 1

        return conflicts, recommendations, breakdown

    # ----------------------------------------------------------------
    # step
    # ----------------------------------------------------------------

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
        gt_conflicts, gt_recs, gt_breakdown = self._compute_ground_truth()

        criteria = {}
        total_score = 0
        max_score = 0

        # ------ Criterion 1: conflict_report.csv exists + correct columns (10 pts) ------
        cr_path = os.path.join(self.workspace, "conflict_report.csv")
        c1_max = 10
        c1_score = 0
        c1_reason = ""
        required_cols = {
            "conflict_id", "proposal_id", "train_service_code",
            "section_name", "conflict_type", "severity", "details",
        }
        agent_conflicts = []
        if os.path.exists(cr_path):
            with open(cr_path, newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and required_cols.issubset(set(reader.fieldnames)):
                    c1_score = c1_max
                    for row in reader:
                        agent_conflicts.append(row)
                else:
                    c1_score = 3
                    c1_reason = f"Missing columns: {required_cols - set(reader.fieldnames or [])}"
                    for row in reader:
                        agent_conflicts.append(row)
        else:
            c1_reason = "conflict_report.csv not found"
        criteria["conflict_report_format"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": c1_reason,
        }
        total_score += c1_score
        max_score += c1_max

        # Helper: compute F1-based score
        def _f1_score(gt_set, agent_set, max_pts):
            if not gt_set and not agent_set:
                return max_pts, ""
            if not gt_set:
                return max_pts if not agent_set else 0, "No ground truth but agent produced entries"
            correct = len(gt_set & agent_set)
            if correct == 0:
                return 0, f"0/{len(gt_set)} found"
            prec = correct / len(agent_set) if agent_set else 0
            rec = correct / len(gt_set)
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
            pts = round(f1 * max_pts, 2)
            reason = "" if pts == max_pts else f"{correct}/{len(gt_set)} found, P={prec:.2f} R={rec:.2f}"
            return pts, reason

        # Build agent conflict sets by type
        agent_by_type = {}
        for ac in agent_conflicts:
            ctype = ac.get("conflict_type", "")
            pid = ac.get("proposal_id", "")
            agent_by_type.setdefault(ctype, set()).add(pid)

        gt_by_type = {}
        for gc in gt_conflicts:
            gt_by_type.setdefault(gc["conflict_type"], set()).add(gc["proposal_id"])

        # ------ Criterion 2: maintenance conflicts (20 pts) ------
        c2_max = 20
        gt_maint = gt_by_type.get("maintenance_overlap", set()) | gt_by_type.get("maintenance_buffer", set())
        ag_maint = agent_by_type.get("maintenance_overlap", set()) | agent_by_type.get("maintenance_buffer", set())
        c2_score, c2_reason = _f1_score(gt_maint, ag_maint, c2_max)
        criteria["maintenance_conflicts"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": c2_reason,
        }
        total_score += c2_score
        max_score += c2_max

        # ------ Criterion 3: junction overload conflicts (20 pts) ------
        c3_max = 20
        gt_jct = gt_by_type.get("junction_overload", set())
        ag_jct = agent_by_type.get("junction_overload", set())
        c3_score, c3_reason = _f1_score(gt_jct, ag_jct, c3_max)
        criteria["junction_overload_conflicts"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": c3_reason,
        }
        total_score += c3_score
        max_score += c3_max

        # ------ Criterion 4: punctuality risk conflicts (15 pts) ------
        c4_max = 15
        gt_pun = gt_by_type.get("punctuality_risk", set())
        ag_pun = agent_by_type.get("punctuality_risk", set())
        c4_score, c4_reason = _f1_score(gt_pun, ag_pun, c4_max)
        criteria["punctuality_risk_conflicts"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": c4_reason,
        }
        total_score += c4_score
        max_score += c4_max

        # ------ Criterion 5: rescheduling_recommendations.json format (10 pts) ------
        rr_path = os.path.join(self.workspace, "rescheduling_recommendations.json")
        c5_max = 10
        c5_score = 0
        c5_reason = ""
        agent_recs = []
        req_fields = {"rank", "proposal_id", "train_service_code",
                       "conflict_type", "severity", "priority_score"}
        if os.path.exists(rr_path):
            try:
                with open(rr_path) as f:
                    agent_recs = json.load(f)
                if isinstance(agent_recs, list) and len(agent_recs) > 0:
                    sample = agent_recs[0]
                    if req_fields.issubset(set(sample.keys())):
                        c5_score = c5_max
                    else:
                        c5_score = 3
                        c5_reason = f"Missing fields: {req_fields - set(sample.keys())}"
                else:
                    c5_score = 2
                    c5_reason = "JSON is not a non-empty list"
            except Exception as e:
                c5_reason = f"JSON parse error: {e}"
        else:
            c5_reason = "rescheduling_recommendations.json not found"
        criteria["recommendations_format"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": c5_reason,
        }
        total_score += c5_score
        max_score += c5_max

        # ------ Criterion 6: priority scores & ordering (15 pts) ------
        c6_max = 15
        c6_score = 0
        c6_reason = ""
        if agent_recs and gt_recs:
            # Check top-10 ordering by (proposal_id, conflict_type) match
            gt_top = [(r["proposal_id"], r["conflict_type"]) for r in gt_recs[:10]]
            ag_top = [(r.get("proposal_id"), r.get("conflict_type")) for r in agent_recs[:10]]
            order_matches = sum(
                1 for i in range(min(len(gt_top), len(ag_top)))
                if gt_top[i] == ag_top[i]
            )
            order_pts = round(order_matches / max(len(gt_top), 1) * 8, 2)

            # Check priority_score accuracy (within 0.5 tolerance)
            # Key by (proposal_id, conflict_type) to handle multi-conflict proposals
            gt_scores = {
                (r["proposal_id"], r["conflict_type"]): r["priority_score"]
                for r in gt_recs
            }
            score_correct = 0
            score_total = 0
            for ar in agent_recs:
                key = (ar.get("proposal_id"), ar.get("conflict_type"))
                if key in gt_scores:
                    score_total += 1
                    try:
                        if abs(float(ar["priority_score"]) - gt_scores[key]) < 0.5:
                            score_correct += 1
                    except (ValueError, TypeError):
                        pass
            score_pts = round(
                (score_correct / max(score_total, 1)) * 7, 2
            )
            c6_score = round(order_pts + score_pts, 2)
            if c6_score < c6_max:
                c6_reason = (
                    f"Order: {order_matches}/{len(gt_top)} top matches; "
                    f"Scores: {score_correct}/{score_total} within tolerance"
                )
        else:
            c6_reason = "Missing recommendations data"
        criteria["priority_ordering"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": c6_reason,
        }
        total_score += c6_score
        max_score += c6_max

        # ------ Criterion 7: response summary (10 pts) ------
        c7_max = 10
        c7_score = 0
        c7_reason = ""
        if action:
            # Check total conflict count
            gt_total = len(gt_conflicts)
            total_match = False
            nums = re.findall(r"\b(\d+)\b", action)
            if str(gt_total) in nums:
                total_match = True
                c7_score += 5

            # Check breakdown counts
            breakdown_match = True
            for ctype in ["maintenance_overlap", "maintenance_buffer",
                          "junction_overload", "punctuality_risk"]:
                expected = gt_breakdown.get(ctype, 0)
                pattern = rf"{ctype}\s*:\s*{expected}\b"
                if not re.search(pattern, action):
                    # Also try without underscore for looser matching
                    breakdown_match = False

            if breakdown_match:
                c7_score += 5
            else:
                if c7_score < c7_max:
                    c7_reason = "Breakdown counts missing or incorrect"

            if not total_match and not breakdown_match:
                c7_reason = "Total count and breakdown not found in response"
        else:
            c7_reason = "Empty response"
        criteria["response_summary"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": c7_reason,
        }
        total_score += c7_score
        max_score += c7_max

        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0
        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ----------------------------------------------------------------
    # verify
    # ----------------------------------------------------------------

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
        # --- Step 1: Read all schedule proposal files ---
        proposals = self._load_proposals()

        # --- Step 2: Read configuration files ---
        rules = self._parse_yaml(
            os.path.join(self.workspace, "conflict_rules.yaml")
        )
        with open(os.path.join(self.workspace, "priority_matrix.json")) as f:
            matrix = json.load(f)
        risk_th = self._parse_risk_thresholds(
            os.path.join(self.workspace, "risk_thresholds.txt")
        )

        buffer_min = int(rules["maintenance_buffer_minutes"])
        jct_ratio = float(rules["junction_capacity_threshold_ratio"])
        sev_map = rules["conflict_severity"]

        punct_threshold = None
        for lvl, info in risk_th.items():
            if info["flag"]:
                punct_threshold = info["max_on_time_pct"]
                break
        if punct_threshold is None:
            punct_threshold = 75.0

        sev_weights = matrix["severity_weights"]
        base_mult = matrix["base_multiplier"]
        train_pw = matrix["train_priority_weight"]
        punct_rw = matrix["punctuality_risk_weight"]

        # --- Step 3: Use tools to gather data ---
        # 3a. Build section cache
        section_cache = {}
        page = 1
        while True:
            res = self.tools["list_route_sections"](page=page, page_size=50)
            for s in res["results"]:
                section_cache[s["section_id"]] = s
            if page * 50 >= res["total"]:
                break
            page += 1

        # 3b. Build train cache
        train_cache = {}
        page = 1
        while True:
            res = self.tools["list_trains"](page=page, page_size=50)
            for t in res["results"]:
                train_cache[t["service_code"]] = t
            if page * 50 >= res["total"]:
                break
            page += 1

        # 3c. Get unique section IDs from proposals
        unique_sids = set(p["section_id"] for p in proposals)

        # 3d. Get maintenance blocks for each section (tool calls)
        maint_by_sec = {}
        for sid in sorted(unique_sids):
            res = self.tools["get_maintenance_blocks"](section_id=sid)
            if res["blocks"]:
                maint_by_sec[sid] = res["blocks"]

        # 3e. Get punctuality history for each section (tool calls)
        punct_by_sec = {}
        for sid in sorted(unique_sids):
            res = self.tools["get_punctuality_history"](section_id=sid)
            if res["records"]:
                punct_by_sec[sid] = res["records"]

        # 3f. Compute avg on-time pct and avg delay per section
        sect_avg_otp = {}
        sect_avg_delay = {}
        for sid, records in punct_by_sec.items():
            otps = [r["on_time_percentage"] for r in records]
            delays = [r["avg_delay_minutes"] for r in records]
            sect_avg_otp[sid] = sum(otps) / len(otps)
            sect_avg_delay[sid] = sum(delays) / len(delays)

        poor_sections = {
            sid for sid, avg in sect_avg_otp.items() if avg <= punct_threshold
        }

        # 3g. Get junction details for each unique junction
        unique_jids = set()
        for sid in unique_sids:
            sec = section_cache.get(sid)
            if sec and sec["junction_id"] is not None:
                unique_jids.add(sec["junction_id"])

        junction_cache = {}
        for jid in sorted(unique_jids):
            res = self.tools["get_junction_details"](junction_id=jid)
            if "error" not in res:
                junction_cache[jid] = res

        # --- Step 4: Detect conflicts ---
        conflicts = []

        # 4a. Maintenance conflicts
        for p in proposals:
            pid = p["proposal_id"]
            sid = p["section_id"]
            dep_dt = datetime.strptime(
                f"{p['date']} {p['departure_time']}", "%Y-%m-%d %H:%M"
            )
            arr_dt = datetime.strptime(
                f"{p['date']} {p['arrival_time']}", "%Y-%m-%d %H:%M"
            )
            if arr_dt <= dep_dt:
                arr_dt += timedelta(days=1)

            if sid not in maint_by_sec:
                continue
            overlap_found = False
            buffer_found = False
            overlap_detail = ""
            buffer_detail = ""
            for mb in maint_by_sec[sid]:
                ms = datetime.strptime(mb["start_datetime"], "%Y-%m-%d %H:%M")
                me = datetime.strptime(mb["end_datetime"], "%Y-%m-%d %H:%M")
                if dep_dt < me and arr_dt > ms:
                    overlap_found = True
                    overlap_detail = (
                        f"Overlaps {mb['possession_type']} block "
                        f"{mb['start_datetime']}-{mb['end_datetime']}"
                    )
                    break
                elif dep_dt < me + timedelta(minutes=buffer_min) and \
                        arr_dt > ms - timedelta(minutes=buffer_min):
                    buffer_found = True
                    buffer_detail = (
                        f"Within {buffer_min}min buffer of "
                        f"{mb['possession_type']} block "
                        f"{mb['start_datetime']}-{mb['end_datetime']}"
                    )

            sec_name = section_cache.get(sid, {}).get("section_name", f"SEC-{sid:03d}")
            if overlap_found:
                conflicts.append({
                    "proposal_id": pid,
                    "train_service_code": p["train_service_code"],
                    "section_id": sid,
                    "section_name": sec_name,
                    "conflict_type": "maintenance_overlap",
                    "severity": sev_map["maintenance_overlap"],
                    "details": overlap_detail,
                })
            elif buffer_found:
                conflicts.append({
                    "proposal_id": pid,
                    "train_service_code": p["train_service_code"],
                    "section_id": sid,
                    "section_name": sec_name,
                    "conflict_type": "maintenance_buffer",
                    "severity": sev_map["maintenance_buffer"],
                    "details": buffer_detail,
                })

        # 4b. Junction overload
        jct_hour_map = {}
        for p in proposals:
            sid = p["section_id"]
            sec = section_cache.get(sid)
            if not sec or sec["junction_id"] is None:
                continue
            jid = sec["junction_id"]
            dep_dt = datetime.strptime(
                f"{p['date']} {p['departure_time']}", "%Y-%m-%d %H:%M"
            )
            arr_dt = datetime.strptime(
                f"{p['date']} {p['arrival_time']}", "%Y-%m-%d %H:%M"
            )
            if arr_dt <= dep_dt:
                arr_dt += timedelta(days=1)
            hour = dep_dt.replace(minute=0, second=0, microsecond=0)
            while hour < arr_dt:
                key = (jid, hour.strftime("%Y-%m-%d %H:%M"))
                jct_hour_map.setdefault(key, []).append(p)
                hour += timedelta(hours=1)

        overloaded = set()
        overload_details = {}
        for (jid, hstr), props in jct_hour_map.items():
            jct = junction_cache.get(jid)
            if not jct:
                continue
            cap = jct["capacity_per_hour"]
            if len(props) > cap * jct_ratio:
                for p in props:
                    pid = p["proposal_id"]
                    if pid not in overloaded:
                        overloaded.add(pid)
                        overload_details[pid] = (
                            f"Junction {jct['junction_name']} overloaded: "
                            f"{len(props)}/{cap} trains at {hstr}"
                        )

        for p in proposals:
            pid = p["proposal_id"]
            if pid in overloaded:
                sid = p["section_id"]
                sec_name = section_cache.get(sid, {}).get("section_name", f"SEC-{sid:03d}")
                conflicts.append({
                    "proposal_id": pid,
                    "train_service_code": p["train_service_code"],
                    "section_id": sid,
                    "section_name": sec_name,
                    "conflict_type": "junction_overload",
                    "severity": sev_map["junction_overload"],
                    "details": overload_details[pid],
                })

        # 4c. Punctuality risk
        for p in proposals:
            pid = p["proposal_id"]
            sid = p["section_id"]
            if sid in poor_sections:
                sec_name = section_cache.get(sid, {}).get("section_name", f"SEC-{sid:03d}")
                avg_otp = sect_avg_otp.get(sid, 0)
                conflicts.append({
                    "proposal_id": pid,
                    "train_service_code": p["train_service_code"],
                    "section_id": sid,
                    "section_name": sec_name,
                    "conflict_type": "punctuality_risk",
                    "severity": sev_map["punctuality_risk"],
                    "details": (
                        f"Section avg on-time {avg_otp:.1f}% "
                        f"<= threshold {punct_threshold}%"
                    ),
                })

        # --- Step 5: Sort and assign IDs ---
        sev_order = {"critical": 0, "major": 1, "moderate": 2, "minor": 3}
        conflicts.sort(
            key=lambda c: (sev_order.get(c["severity"], 9), c["proposal_id"])
        )
        for i, c in enumerate(conflicts):
            c["conflict_id"] = f"C{i + 1:04d}"

        # --- Step 6: Compute priority scores ---
        recommendations = []
        for c in conflicts:
            sw = sev_weights.get(c["severity"], 1)
            train = train_cache.get(c["train_service_code"])
            tpc = train["priority_class"] if train else 3
            avg_del = sect_avg_delay.get(c["section_id"], 0)
            score = round(sw * base_mult + tpc * train_pw + avg_del * punct_rw, 2)
            recommendations.append({
                "rank": None,
                "proposal_id": c["proposal_id"],
                "train_service_code": c["train_service_code"],
                "conflict_type": c["conflict_type"],
                "severity": c["severity"],
                "priority_score": score,
                "recommendation": f"Reschedule {c['train_service_code']} on {c['section_name']} to resolve {c['conflict_type']}",
            })

        recommendations.sort(
            key=lambda r: (-r["priority_score"], r["proposal_id"])
        )
        for i, r in enumerate(recommendations):
            r["rank"] = i + 1

        # --- Step 7: Write deliverables ---
        # conflict_report.csv
        cr_path = os.path.join(self.workspace, "conflict_report.csv")
        with open(cr_path, "w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "conflict_id", "proposal_id", "train_service_code",
                    "section_name", "conflict_type", "severity", "details",
                ],
            )
            w.writeheader()
            for c in conflicts:
                w.writerow({
                    "conflict_id": c["conflict_id"],
                    "proposal_id": c["proposal_id"],
                    "train_service_code": c["train_service_code"],
                    "section_name": c["section_name"],
                    "conflict_type": c["conflict_type"],
                    "severity": c["severity"],
                    "details": c["details"],
                })

        # rescheduling_recommendations.json
        rr_path = os.path.join(self.workspace, "rescheduling_recommendations.json")
        with open(rr_path, "w") as f:
            json.dump(recommendations, f, indent=2)

        # --- Step 8: Build response ---
        total_conflicts = len(conflicts)
        breakdown = {}
        for c in conflicts:
            breakdown[c["conflict_type"]] = breakdown.get(c["conflict_type"], 0) + 1

        type_order = [
            "maintenance_overlap", "maintenance_buffer",
            "junction_overload", "punctuality_risk",
        ]
        bd_parts = []
        for t in type_order:
            bd_parts.append(f"{t}: {breakdown.get(t, 0)}")

        top3 = recommendations[:3]
        top3_lines = []
        for r in top3:
            top3_lines.append(
                f"Rank {r['rank']}: {r['proposal_id']} (score {r['priority_score']})"
            )

        action = (
            f"Total conflicts identified: {total_conflicts}\n"
            f"Breakdown: {', '.join(bd_parts)}\n"
            f"Top 3 rescheduling recommendations:\n"
            + "\n".join(top3_lines)
        )

        return self.step(action)
