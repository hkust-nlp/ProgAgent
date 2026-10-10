import sqlite3
import os
import json
import csv
import glob
from typing import Tuple, Dict, List, Any

import yaml
import pandas as pd


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

    # ===================== TOOL METHODS =====================

    @tool(
        description="List volunteers with pagination. Returns volunteer_id, first_name, last_name, department, status, and join_date for each volunteer.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 20).",
                },
            },
            "required": ["page"],
        },
    )
    def list_volunteers(self, page: int, page_size: int = 20) -> dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        total = cur.execute("SELECT COUNT(*) FROM volunteers").fetchone()[0]
        rows = cur.execute(
            "SELECT volunteer_id, first_name, last_name, department, status, join_date "
            "FROM volunteers ORDER BY volunteer_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": (total + page_size - 1) // page_size,
            "volunteers": [dict(r) for r in rows],
        }

    @tool(
        description="Get all certifications for a specific volunteer. Returns cert_name, cert_category, completion_date, and is_active status.",
        parameters={
            "type": "object",
            "properties": {
                "volunteer_id": {
                    "type": "string",
                    "description": "The volunteer ID, e.g. 'V0001'.",
                },
            },
            "required": ["volunteer_id"],
        },
    )
    def get_certifications(self, volunteer_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT cert_name, cert_category, completion_date, is_active "
            "FROM certifications WHERE volunteer_id = ? ORDER BY completion_date",
            (volunteer_id,),
        ).fetchall()
        conn.close()
        return {
            "volunteer_id": volunteer_id,
            "certifications": [dict(r) for r in rows],
        }

    @tool(
        description="Get peer feedback entries for a specific volunteer, optionally filtered by quarter. Returns reviewer_id, score, quarter, and category for each entry.",
        parameters={
            "type": "object",
            "properties": {
                "volunteer_id": {
                    "type": "string",
                    "description": "The volunteer ID, e.g. 'V0001'.",
                },
                "quarter": {
                    "type": "string",
                    "description": "Optional quarter filter, e.g. 'Q1_2026'. If omitted, returns all quarters.",
                },
            },
            "required": ["volunteer_id"],
        },
    )
    def get_peer_feedback(self, volunteer_id: str, quarter: str = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if quarter:
            rows = conn.execute(
                "SELECT reviewer_id, score, quarter, category "
                "FROM peer_feedback WHERE volunteer_id = ? AND quarter = ? ORDER BY feedback_id",
                (volunteer_id, quarter),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT reviewer_id, score, quarter, category "
                "FROM peer_feedback WHERE volunteer_id = ? ORDER BY feedback_id",
                (volunteer_id,),
            ).fetchall()
        conn.close()
        return {
            "volunteer_id": volunteer_id,
            "feedback_entries": [dict(r) for r in rows],
        }

    @tool(
        description="Get event leadership roles for a specific volunteer, optionally filtered by quarter. Returns event_name, role_type, event_date, and quarter.",
        parameters={
            "type": "object",
            "properties": {
                "volunteer_id": {
                    "type": "string",
                    "description": "The volunteer ID, e.g. 'V0001'.",
                },
                "quarter": {
                    "type": "string",
                    "description": "Optional quarter filter, e.g. 'Q1_2026'. If omitted, returns all quarters.",
                },
            },
            "required": ["volunteer_id"],
        },
    )
    def get_leadership_roles(self, volunteer_id: str, quarter: str = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if quarter:
            rows = conn.execute(
                "SELECT event_name, role_type, event_date, quarter "
                "FROM event_leadership WHERE volunteer_id = ? AND quarter = ? ORDER BY event_date",
                (volunteer_id, quarter),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT event_name, role_type, event_date, quarter "
                "FROM event_leadership WHERE volunteer_id = ? ORDER BY event_date",
                (volunteer_id,),
            ).fetchall()
        conn.close()
        return {
            "volunteer_id": volunteer_id,
            "leadership_roles": [dict(r) for r in rows],
        }

    @tool(
        description="Look up a single volunteer's full details by volunteer_id. Returns first_name, last_name, email, department, join_date, and status.",
        parameters={
            "type": "object",
            "properties": {
                "volunteer_id": {
                    "type": "string",
                    "description": "The volunteer ID, e.g. 'V0001'.",
                },
            },
            "required": ["volunteer_id"],
        },
    )
    def get_volunteer_details(self, volunteer_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT volunteer_id, first_name, last_name, email, department, join_date, status "
            "FROM volunteers WHERE volunteer_id = ?",
            (volunteer_id,),
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Volunteer {volunteer_id} not found."}

    # ===================== GROUND-TRUTH COMPUTATION =====================

    def _compute_ground_truth(self):
        """Compute the expected commendation list from DB + workspace (for step & verify)."""
        # Load config
        with open(os.path.join(self.workspace, "award_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "specialized_certs.json")) as f:
            spec_info = json.load(f)
        spec_cats = set(spec_info["specialized_categories"])
        quarter = policy["evaluation_quarter"]
        q_start = policy["quarter_start"]
        q_end = policy["quarter_end"]
        join_cutoff = policy["eligibility"]["joined_on_or_before"]

        conn = sqlite3.connect(self.db_path)

        # Eligible volunteers: active + joined on or before cutoff
        vols = pd.read_sql_query(
            "SELECT volunteer_id, first_name, last_name, department, join_date, status "
            "FROM volunteers WHERE status = 'active' AND join_date <= ?",
            conn,
            params=(join_cutoff,),
        )
        eligible_ids = set(vols["volunteer_id"])

        # Hours from workspace CSVs
        hours_files = sorted(glob.glob(os.path.join(self.workspace, "hours_log_part_*.csv")))
        hours_dfs = [pd.read_csv(f) for f in hours_files]
        all_hours = pd.concat(hours_dfs, ignore_index=True)
        q1_hours = all_hours[
            (all_hours["log_date"] >= q_start) & (all_hours["log_date"] <= q_end)
        ]
        hours_agg = q1_hours.groupby("volunteer_id")["hours"].sum()

        # Certifications (active, in specialized categories) — count distinct categories
        certs = pd.read_sql_query(
            "SELECT volunteer_id, cert_category FROM certifications WHERE is_active = 1",
            conn,
        )
        spec_certs = certs[certs["cert_category"].isin(spec_cats)]
        cert_agg = spec_certs.groupby("volunteer_id")["cert_category"].nunique()

        # Peer feedback for the quarter — average score
        fb = pd.read_sql_query(
            "SELECT volunteer_id, score FROM peer_feedback WHERE quarter = ?",
            conn,
            params=(quarter,),
        )
        fb_agg = fb.groupby("volunteer_id")["score"].mean()

        # Leadership roles for the quarter — count
        lead = pd.read_sql_query(
            "SELECT volunteer_id FROM event_leadership WHERE quarter = ?",
            conn,
            params=(quarter,),
        )
        lead_agg = lead.groupby("volunteer_id").size()

        conn.close()

        # Determine tiers
        tier_defs = policy["tiers"]
        tier_order = policy["tier_priority"]

        results = []
        for _, vol in vols.iterrows():
            vid = vol["volunteer_id"]
            if vid not in eligible_ids:
                continue
            total_hours = round(float(hours_agg.get(vid, 0.0)), 1)
            spec_count = int(cert_agg.get(vid, 0))
            avg_fb = round(float(fb_agg.get(vid, 0.0)), 2)
            lead_count = int(lead_agg.get(vid, 0))

            assigned_tier = None
            for tier_name in tier_order:
                td = tier_defs[tier_name]
                if (
                    total_hours >= td["min_total_hours"]
                    and spec_count >= td["min_specialized_cert_categories"]
                    and avg_fb >= td["min_avg_feedback"]
                    and lead_count >= td["min_leadership_roles"]
                ):
                    assigned_tier = tier_name
                    break

            if assigned_tier:
                full_name = f"{vol['first_name']} {vol['last_name']}"
                results.append({
                    "volunteer_id": vid,
                    "full_name": full_name,
                    "department": vol["department"],
                    "total_hours": total_hours,
                    "specialized_cert_categories": spec_count,
                    "avg_feedback_score": avg_fb,
                    "leadership_count": lead_count,
                    "award_tier": assigned_tier,
                })

        # Sort: tier priority, then total_hours desc, then volunteer_id asc
        tier_rank = {t: i for i, t in enumerate(tier_order)}
        results.sort(key=lambda r: (tier_rank[r["award_tier"]], -r["total_hours"], r["volunteer_id"]))

        # Counts per tier
        tier_counts = {}
        for t in tier_order:
            cnt = sum(1 for r in results if r["award_tier"] == t)
            if cnt > 0:
                tier_counts[t] = cnt

        return results, tier_counts

    # ===================== STEP =====================

    def step(
        self, action: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.

        Returns a reward based on evaluation results.

        Args:
            action: The agent's final response.

        Returns:
            reward: The reward based on task completion (between 0.0 and 1.0).
            info: Evaluation results.
        """
        gt_results, gt_tier_counts = self._compute_ground_truth()
        gt_total = len(gt_results)

        eval_criteria = {}

        # ---- Criterion 1: commendation_list.csv exists (10 pts) ----
        csv_path = os.path.join(self.workspace, "commendation_list.csv")
        csv_exists = os.path.isfile(csv_path)
        eval_criteria["file_exists"] = {
            "passed": csv_exists,
            "score": 10 if csv_exists else 0,
            "max_score": 10,
        }
        if not csv_exists:
            eval_criteria["file_exists"]["reason"] = "commendation_list.csv not found in workspace"

        # Try to parse the CSV
        submitted_rows = []
        if csv_exists:
            try:
                with open(csv_path, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        submitted_rows.append(row)
            except Exception as e:
                eval_criteria["file_exists"]["reason"] = f"CSV parse error: {e}"

        # ---- Criterion 2: Correct columns (10 pts) ----
        expected_cols = [
            "volunteer_id", "full_name", "department", "total_hours",
            "specialized_cert_categories", "avg_feedback_score",
            "leadership_count", "award_tier",
        ]
        if submitted_rows:
            actual_cols = list(submitted_rows[0].keys())
            cols_match = actual_cols == expected_cols
        else:
            actual_cols = []
            cols_match = False
        eval_criteria["correct_columns"] = {
            "passed": cols_match,
            "score": 10 if cols_match else 0,
            "max_score": 10,
        }
        if not cols_match:
            eval_criteria["correct_columns"]["reason"] = (
                f"Expected columns {expected_cols}, got {actual_cols}"
            )

        # ---- Criterion 3: Correct volunteer IDs (20 pts) ----
        gt_ids = set(r["volunteer_id"] for r in gt_results)
        submitted_ids = set()
        for row in submitted_rows:
            vid = row.get("volunteer_id", "").strip()
            if vid:
                submitted_ids.add(vid)
        ids_match = gt_ids == submitted_ids
        # Partial credit: proportion of correct IDs
        if gt_ids:
            correct_ids = gt_ids & submitted_ids
            extra_ids = submitted_ids - gt_ids
            id_score = max(0, (len(correct_ids) - len(extra_ids)) / len(gt_ids))
            id_score = round(id_score * 20)
        else:
            id_score = 20 if len(submitted_ids) == 0 else 0
        eval_criteria["correct_volunteer_ids"] = {
            "passed": ids_match,
            "score": id_score,
            "max_score": 20,
        }
        if not ids_match:
            missing = gt_ids - submitted_ids
            extra = submitted_ids - gt_ids
            eval_criteria["correct_volunteer_ids"]["reason"] = (
                f"Missing {len(missing)} IDs, {len(extra)} extra IDs"
            )

        # ---- Criterion 4: Correct tier assignments (20 pts) ----
        gt_tier_map = {r["volunteer_id"]: r["award_tier"] for r in gt_results}
        submitted_tier_map = {}
        for row in submitted_rows:
            vid = row.get("volunteer_id", "").strip()
            tier = row.get("award_tier", "").strip()
            if vid:
                submitted_tier_map[vid] = tier
        tier_correct = 0
        tier_total = len(gt_tier_map)
        for vid, expected_tier in gt_tier_map.items():
            if submitted_tier_map.get(vid) == expected_tier:
                tier_correct += 1
        if tier_total > 0:
            tier_score = round((tier_correct / tier_total) * 20)
        else:
            tier_score = 20
        eval_criteria["correct_tiers"] = {
            "passed": tier_correct == tier_total,
            "score": tier_score,
            "max_score": 20,
        }
        if tier_correct != tier_total:
            eval_criteria["correct_tiers"]["reason"] = (
                f"{tier_correct}/{tier_total} tiers correct"
            )

        # ---- Criterion 5: Correct numeric values (15 pts) ----
        gt_val_map = {r["volunteer_id"]: r for r in gt_results}
        val_correct = 0
        val_total = len(gt_val_map)
        for vid, gt in gt_val_map.items():
            if vid not in submitted_tier_map:
                continue
            row_match = True
            for srow in submitted_rows:
                if srow.get("volunteer_id", "").strip() == vid:
                    try:
                        if (
                            abs(float(srow.get("total_hours", 0)) - gt["total_hours"]) > 0.15
                            or int(srow.get("specialized_cert_categories", -1)) != gt["specialized_cert_categories"]
                            or abs(float(srow.get("avg_feedback_score", 0)) - gt["avg_feedback_score"]) > 0.015
                            or int(srow.get("leadership_count", -1)) != gt["leadership_count"]
                        ):
                            row_match = False
                    except (ValueError, TypeError):
                        row_match = False
                    break
            else:
                row_match = False
            if row_match:
                val_correct += 1
        if val_total > 0:
            val_score = round((val_correct / val_total) * 15)
        else:
            val_score = 15
        eval_criteria["correct_values"] = {
            "passed": val_correct == val_total,
            "score": val_score,
            "max_score": 15,
        }
        if val_correct != val_total:
            eval_criteria["correct_values"]["reason"] = (
                f"{val_correct}/{val_total} rows have correct numeric values"
            )

        # ---- Criterion 6: Correct sort order (10 pts) ----
        gt_id_order = [r["volunteer_id"] for r in gt_results]
        submitted_id_order = [
            row.get("volunteer_id", "").strip() for row in submitted_rows
        ]
        order_match = gt_id_order == submitted_id_order
        eval_criteria["correct_sort_order"] = {
            "passed": order_match,
            "score": 10 if order_match else 0,
            "max_score": 10,
        }
        if not order_match:
            eval_criteria["correct_sort_order"]["reason"] = (
                "Rows not sorted by tier priority, then total_hours descending, then volunteer_id ascending"
            )

        # ---- Criterion 7: Response summary (15 pts) ----
        # Check that response mentions total awardee count and per-tier counts
        response_score = 0
        action_lower = action.lower() if action else ""
        # Check total count
        if str(gt_total) in (action or ""):
            response_score += 5

        # Check per-tier counts
        tier_count_correct = 0
        for tier_name, cnt in gt_tier_counts.items():
            if str(cnt) in (action or ""):
                tier_count_correct += 1
        if gt_tier_counts and tier_count_correct == len(gt_tier_counts):
            response_score += 10
        elif gt_tier_counts:
            response_score += round(10 * tier_count_correct / len(gt_tier_counts))

        eval_criteria["response_summary"] = {
            "passed": response_score == 15,
            "score": response_score,
            "max_score": 15,
        }
        if response_score < 15:
            eval_criteria["response_summary"]["reason"] = (
                f"Response should mention total awardee count ({gt_total}) and "
                f"per-tier counts: {dict(gt_tier_counts)}"
            )

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score, info

    # ===================== VERIFY =====================

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
        # ---- Step 1: Read config files from workspace ----
        with open(os.path.join(self.workspace, "award_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "specialized_certs.json")) as f:
            spec_info = json.load(f)

        spec_cats = set(spec_info["specialized_categories"])
        quarter = policy["evaluation_quarter"]
        q_start = policy["quarter_start"]
        q_end = policy["quarter_end"]
        join_cutoff = policy["eligibility"]["joined_on_or_before"]
        tier_defs = policy["tiers"]
        tier_order = policy["tier_priority"]

        # ---- Step 2: Read hours log CSVs from workspace ----
        hours_files = sorted(glob.glob(os.path.join(self.workspace, "hours_log_part_*.csv")))
        all_hours = pd.concat([pd.read_csv(f) for f in hours_files], ignore_index=True)
        q1_hours = all_hours[
            (all_hours["log_date"] >= q_start) & (all_hours["log_date"] <= q_end)
        ]
        hours_per_vol = q1_hours.groupby("volunteer_id")["hours"].sum().to_dict()

        # ---- Step 3: List all volunteers via tool (paginated) ----
        tool_call_count = 0
        all_volunteers = []
        page = 1
        while True:
            result = self.tools["list_volunteers"](page=page, page_size=20)
            tool_call_count += 1
            all_volunteers.extend(result["volunteers"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Filter eligible volunteers
        eligible = []
        for v in all_volunteers:
            if v["status"] == "active" and v["join_date"] <= join_cutoff:
                eligible.append(v)

        # ---- Step 4: For each eligible volunteer, get certs, feedback, leadership ----
        results = []
        for v in eligible:
            vid = v["volunteer_id"]
            total_hours = round(hours_per_vol.get(vid, 0.0), 1)

            # Get certifications
            cert_result = self.tools["get_certifications"](volunteer_id=vid)
            tool_call_count += 1
            active_spec_cats = set()
            for c in cert_result["certifications"]:
                if c["is_active"] and c["cert_category"] in spec_cats:
                    active_spec_cats.add(c["cert_category"])
            spec_count = len(active_spec_cats)

            # Get peer feedback for the quarter
            fb_result = self.tools["get_peer_feedback"](volunteer_id=vid, quarter=quarter)
            tool_call_count += 1
            fb_entries = fb_result["feedback_entries"]
            if fb_entries:
                avg_fb = round(sum(e["score"] for e in fb_entries) / len(fb_entries), 2)
            else:
                avg_fb = 0.0

            # Get leadership roles for the quarter
            lead_result = self.tools["get_leadership_roles"](volunteer_id=vid, quarter=quarter)
            tool_call_count += 1
            lead_count = len(lead_result["leadership_roles"])

            # Determine tier
            assigned_tier = None
            for tier_name in tier_order:
                td = tier_defs[tier_name]
                if (
                    total_hours >= td["min_total_hours"]
                    and spec_count >= td["min_specialized_cert_categories"]
                    and avg_fb >= td["min_avg_feedback"]
                    and lead_count >= td["min_leadership_roles"]
                ):
                    assigned_tier = tier_name
                    break

            if assigned_tier:
                full_name = f"{v['first_name']} {v['last_name']}"
                results.append({
                    "volunteer_id": vid,
                    "full_name": full_name,
                    "department": v["department"],
                    "total_hours": total_hours,
                    "specialized_cert_categories": spec_count,
                    "avg_feedback_score": avg_fb,
                    "leadership_count": lead_count,
                    "award_tier": assigned_tier,
                })

        # ---- Step 5: Sort results ----
        tier_rank = {t: i for i, t in enumerate(tier_order)}
        results.sort(key=lambda r: (tier_rank[r["award_tier"]], -r["total_hours"], r["volunteer_id"]))

        # ---- Step 6: Write commendation_list.csv ----
        csv_path = os.path.join(self.workspace, "commendation_list.csv")
        fieldnames = [
            "volunteer_id", "full_name", "department", "total_hours",
            "specialized_cert_categories", "avg_feedback_score",
            "leadership_count", "award_tier",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow(r)

        # ---- Step 7: Build action string ----
        tier_counts = {}
        for t in tier_order:
            cnt = sum(1 for r in results if r["award_tier"] == t)
            if cnt > 0:
                tier_counts[t] = cnt

        summary_parts = [
            f"Quarterly Commendation List for {quarter} has been compiled.",
            f"Total awardees: {len(results)}.",
        ]
        for t in tier_order:
            if t in tier_counts:
                summary_parts.append(f"{t}: {tier_counts[t]} volunteers.")
        summary_parts.append(
            "The commendation_list.csv has been saved with columns: "
            "volunteer_id, full_name, department, total_hours, "
            "specialized_cert_categories, avg_feedback_score, leadership_count, award_tier."
        )
        action = " ".join(summary_parts)

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need at least 15"

        return self.step(action)
