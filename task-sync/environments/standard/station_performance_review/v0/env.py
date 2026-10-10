import sqlite3
import os
import csv
import json
import yaml
from typing import Tuple, Dict, List, Any


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


def _envelope(payload):
    """MCP-style tool result: payload JSON-encoded in a text content block."""
    return {"content": [{"type": "text",
                          "text": json.dumps(payload, ensure_ascii=False, default=str)}],
            "isError": False}


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

    # ── Tools ──────────────────────────────────────────────────────

    @tool(
        description=(
            "Retrieves a paginated list of stations. Each entry includes the "
            "station's identifier, name, district, type, capacity, installation "
            "date, and current status. Use the page and page_size parameters to "
            "iterate through all stations."
        ),
        parameters={
            "type": "object",
            "properties": {
                "district": {
                    "type": "string",
                    "description": "Optional district name to filter stations.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of stations per page. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def list_stations(self, district: str = None, page: int = 1, page_size: int = 20):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        if district:
            cur.execute(
                "SELECT COUNT(*) FROM stations WHERE district = ?", (district,)
            )
        else:
            cur.execute("SELECT COUNT(*) FROM stations")
        total = cur.fetchone()[0]

        offset = (page - 1) * page_size
        if district:
            cur.execute(
                "SELECT station_id, name, district, station_type, capacity, "
                "install_date, status FROM stations WHERE district = ? "
                "ORDER BY station_id LIMIT ? OFFSET ?",
                (district, page_size, offset),
            )
        else:
            cur.execute(
                "SELECT station_id, name, district, station_type, capacity, "
                "install_date, status FROM stations "
                "ORDER BY station_id LIMIT ? OFFSET ?",
                (page_size, offset),
            )

        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return json.dumps({
            "stations": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Returns the financial cost breakdown of maintenance activities for "
            "a single station, including total expenditure, number of incidents, "
            "average cost per incident, and a per-issue-type cost summary."
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
    def get_maintenance_cost_report(self, station_id: int):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute(
            "SELECT COALESCE(SUM(cost), 0), COUNT(*) "
            "FROM maintenance_logs WHERE station_id = ?",
            (station_id,),
        )
        total_cost, incident_count = cur.fetchone()

        cur.execute(
            "SELECT issue_type, SUM(cost) FROM maintenance_logs "
            "WHERE station_id = ? GROUP BY issue_type",
            (station_id,),
        )
        cost_by_type = {r[0]: round(r[1], 2) for r in cur.fetchall()}

        conn.close()
        return _envelope({
            "station_id": station_id,
            "total_cost": round(total_cost, 2),
            "incident_count": incident_count,
            "avg_cost_per_incident": round(total_cost / max(incident_count, 1), 2),
            "cost_by_issue_type": cost_by_type,
        })

    @tool(
        description=(
            "Returns complaint severity statistics for a single station, "
            "including total complaint count, the distribution of severity "
            "ratings (1-5), and a weighted severity score (sum of all individual "
            "severity values)."
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
    def get_complaint_severity_report(self, station_id: int):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute(
            "SELECT severity, COUNT(*) FROM complaints "
            "WHERE station_id = ? GROUP BY severity",
            (station_id,),
        )
        dist = {str(r[0]): r[1] for r in cur.fetchall()}

        cur.execute(
            "SELECT COALESCE(SUM(severity), 0), COUNT(*) "
            "FROM complaints WHERE station_id = ?",
            (station_id,),
        )
        weighted, total = cur.fetchone()

        conn.close()
        return json.dumps({
            "station_id": station_id,
            "total_complaints": total,
            "severity_distribution": dist,
            "weighted_severity_score": weighted,
        }, ensure_ascii=False, default=str)

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
                rec = row["recommendation"].strip().upper()
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
        # Check top candidate mentioned
        if gt_candidates:
            top_name = gt_candidates[0]["station_name"]
            top_id = str(gt_candidates[0]["station_id"])
            if top_name in action or top_id in action:
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
        # ── Read workspace config files ────────────────────────────
        with open(os.path.join(self.workspace, "scoring_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "relocation_criteria.json")) as f:
            criteria = json.load(f)

        weights = config["weights"]
        norm = config["normalization"]
        thresh = config["thresholds"]
        max_install = criteria["eligibility"]["max_install_date"]

        # ── Read usage trend CSVs ──────────────────────────────────
        usage_data: Dict[int, list] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("usage_trends_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname), newline="") as f:
                    for row in csv.DictReader(f):
                        sid = int(row["station_id"])
                        usage_data.setdefault(sid, []).append(row)

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

        # ── List all stations via tool (paginated) ─────────────────
        all_stations = []
        page = 1
        while True:
            result = json.loads(self.tools["list_stations"](page=page, page_size=20))
            all_stations.extend(result["stations"])
            if not result["has_more"]:
                break
            page += 1

        # ── Filter eligible stations ───────────────────────────────
        eligible = [s for s in all_stations if s["install_date"] <= max_install]

        # ── Compute scores ─────────────────────────────────────────
        scored = []
        for station in eligible:
            sid = station["station_id"]

            # Usage decline
            records = sorted(usage_data.get(sid, []), key=lambda r: r["year_month"])
            if len(records) >= 6:
                first_3 = sum(int(r["total_rides"]) for r in records[:3]) / 3.0
                last_3 = sum(int(r["total_rides"]) for r in records[-3:]) / 3.0
                decline_pct = max(0.0, (first_3 - last_3) / first_3 * 100) if first_3 > 0 else 0.0
            else:
                decline_pct = 0.0
            decline_pct = min(decline_pct, norm["max_usage_decline_pct"])
            usage_score = (decline_pct / norm["max_usage_decline_pct"]) * 100

            # Maintenance burden (cost from tool, downtime from workspace)
            maint_report = json.loads(self.tools["get_maintenance_cost_report"](station_id=sid)["content"][0]["text"])
            total_cost = maint_report["total_cost"]
            total_dt = maint_downtime.get(sid, 0.0)
            burden = total_cost + total_dt * norm["downtime_cost_per_hour"]
            maint_score = min(burden / norm["maintenance_cost_cap"], 1.0) * 100

            # Complaint index (severity from tool, unresolved from workspace)
            comp_report = json.loads(self.tools["get_complaint_severity_report"](station_id=sid))
            w_sev = comp_report["weighted_severity_score"]
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
