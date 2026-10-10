#!/usr/bin/env python3
"""Environment for chronic requisition bottleneck analysis task."""

import csv
import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

import pandas as pd
import yaml


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


REFERENCE_DATE = datetime(2026, 4, 15)


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

    # ---------- Tool methods ----------

    @tool(
        description="List all departments with their IDs, names, and divisions.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_departments(self) -> str:
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute("SELECT id, name, division FROM departments ORDER BY id")
        rows = cur.fetchall()
        conn.close()
        result = [{"id": r[0], "name": r[1], "division": r[2]} for r in rows]
        return json.dumps(result)

    @tool(
        description=(
            "Query requisitions with optional filters. Returns paginated results "
            "(20 per page). Each result includes requisition id, title, department_id, "
            "status, open_date, close_date, priority_level, target_headcount, and location."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: open, closed, on_hold, cancelled",
                },
                "department_id": {
                    "type": "integer",
                    "description": "Filter by department ID",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default is 1.",
                },
            },
            "required": [],
        },
    )
    def query_requisitions(
        self, status: str = None, department_id: int = None, page: int = 1
    ) -> str:
        page_size = 20
        conn = sqlite3.connect(self.db_path)
        query = "SELECT id, title, department_id, status, open_date, close_date, priority_level, target_headcount, location FROM requisitions WHERE 1=1"
        params: list = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if department_id is not None:
            query += " AND department_id = ?"
            params.append(department_id)
        query += " ORDER BY id"

        cur = conn.execute(query, params)
        all_rows = cur.fetchall()
        conn.close()
        total = len(all_rows)
        start = (page - 1) * page_size
        page_rows = all_rows[start : start + page_size]
        cols = [
            "id", "title", "department_id", "status", "open_date",
            "close_date", "priority_level", "target_headcount", "location",
        ]
        results = [dict(zip(cols, r)) for r in page_rows]
        return json.dumps({
            "results": results,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        })

    @tool(
        description="Get full details for a single requisition by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "requisition_id": {
                    "type": "integer",
                    "description": "The requisition ID",
                },
            },
            "required": ["requisition_id"],
        },
    )
    def get_requisition_details(self, requisition_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "SELECT r.id, r.title, r.department_id, d.name as department_name, "
            "r.status, r.open_date, r.close_date, r.priority_level, "
            "r.target_headcount, r.location "
            "FROM requisitions r JOIN departments d ON r.department_id = d.id "
            "WHERE r.id = ?",
            (requisition_id,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return json.dumps({"error": "Requisition not found"})
        cols = [
            "id", "title", "department_id", "department_name", "status",
            "open_date", "close_date", "priority_level", "target_headcount", "location",
        ]
        return json.dumps(dict(zip(cols, row)))

    @tool(
        description=(
            "Get candidate applications for a requisition. Returns paginated results "
            "(25 per page) with candidate id, name, application_date, current_stage, and source."
        ),
        parameters={
            "type": "object",
            "properties": {
                "requisition_id": {
                    "type": "integer",
                    "description": "The requisition ID",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default is 1.",
                },
            },
            "required": ["requisition_id"],
        },
    )
    def get_candidate_applications(
        self, requisition_id: int, page: int = 1
    ) -> str:
        page_size = 25
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "SELECT id, name, application_date, current_stage, source "
            "FROM candidates WHERE requisition_id = ? ORDER BY application_date",
            (requisition_id,),
        )
        all_rows = cur.fetchall()
        conn.close()
        total = len(all_rows)
        start = (page - 1) * page_size
        page_rows = all_rows[start : start + page_size]
        cols = ["id", "name", "application_date", "current_stage", "source"]
        results = [dict(zip(cols, r)) for r in page_rows]
        return json.dumps({
            "results": results,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        })

    @tool(
        description=(
            "Get all recruiter assignment records for a requisition, including "
            "recruiter_id, recruiter_name, assigned_date, unassigned_date, and reason."
        ),
        parameters={
            "type": "object",
            "properties": {
                "requisition_id": {
                    "type": "integer",
                    "description": "The requisition ID",
                },
            },
            "required": ["requisition_id"],
        },
    )
    def get_recruiter_assignments(self, requisition_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "SELECT id, recruiter_id, recruiter_name, assigned_date, "
            "unassigned_date, reason "
            "FROM recruiter_assignments WHERE requisition_id = ? ORDER BY assigned_date",
            (requisition_id,),
        )
        rows = cur.fetchall()
        conn.close()
        cols = [
            "id", "recruiter_id", "recruiter_name", "assigned_date",
            "unassigned_date", "reason",
        ]
        return json.dumps([dict(zip(cols, r)) for r in rows])

    @tool(
        description=(
            "Get hiring manager feedback entries for a requisition. Returns "
            "feedback_id, candidate_id, feedback_date, score, category, and comments."
        ),
        parameters={
            "type": "object",
            "properties": {
                "requisition_id": {
                    "type": "integer",
                    "description": "The requisition ID",
                },
            },
            "required": ["requisition_id"],
        },
    )
    def get_hiring_manager_feedback(self, requisition_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "SELECT id, candidate_id, feedback_date, score, category, comments "
            "FROM hiring_manager_feedback WHERE requisition_id = ? ORDER BY feedback_date",
            (requisition_id,),
        )
        rows = cur.fetchall()
        conn.close()
        cols = ["id", "candidate_id", "feedback_date", "score", "category", "comments"]
        return json.dumps([dict(zip(cols, r)) for r in rows])

    @tool(
        description=(
            "Get a summary count of candidates in each pipeline stage for a requisition."
        ),
        parameters={
            "type": "object",
            "properties": {
                "requisition_id": {
                    "type": "integer",
                    "description": "The requisition ID",
                },
            },
            "required": ["requisition_id"],
        },
    )
    def get_pipeline_stage_summary(self, requisition_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "SELECT current_stage, COUNT(*) FROM candidates "
            "WHERE requisition_id = ? GROUP BY current_stage ORDER BY current_stage",
            (requisition_id,),
        )
        rows = cur.fetchall()
        conn.close()
        return json.dumps({r[0]: r[1] for r in rows})

    # ---------- Evaluation ----------

    def _compute_ground_truth(self):
        """Compute the full ground truth solution using database + workspace."""
        conn = sqlite3.connect(self.db_path)

        # Load workspace configs
        with open(os.path.join(self.workspace, "department_thresholds.yaml")) as f:
            dept_thresholds = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "bottleneck_classification.json")) as f:
            bottleneck_defs = json.load(f)

        pipeline_stages = pd.read_csv(os.path.join(self.workspace, "pipeline_stages.csv"))
        expected_days = dict(zip(pipeline_stages["stage"], pipeline_stages["expected_days"]))

        # Read priority scoring rules (parse severity weights from bottleneck_defs)
        # The rules reference severity_weight from bottleneck_classification.json

        # Get all departments
        depts = {}
        for row in conn.execute("SELECT id, name FROM departments"):
            depts[row[0]] = row[1]

        # Get all open requisitions
        reqs = []
        for row in conn.execute(
            "SELECT id, title, department_id, status, open_date, close_date, "
            "priority_level, target_headcount, location FROM requisitions "
            "WHERE status = 'open'"
        ):
            req = {
                "id": row[0], "title": row[1], "department_id": row[2],
                "status": row[3], "open_date": row[4], "close_date": row[5],
                "priority_level": row[6], "target_headcount": row[7],
                "location": row[8],
                "department_name": depts[row[2]],
            }
            open_date = datetime.strptime(req["open_date"], "%Y-%m-%d")
            req["days_open"] = (REFERENCE_DATE - open_date).days
            reqs.append(req)

        # Filter: only open > 60 days
        flagged = [r for r in reqs if r["days_open"] > 60]

        # Load weekly pipeline data for flow rate computation
        weekly_files = sorted([
            f for f in os.listdir(self.workspace)
            if f.startswith("weekly_pipeline_week_") and f.endswith(".csv")
        ])
        weekly_data = []
        for wf in weekly_files:
            df = pd.read_csv(os.path.join(self.workspace, wf))
            weekly_data.append(df)

        # For each flagged requisition, compute bottlenecks
        results = []
        for req in flagged:
            rid = req["id"]
            dept_name = req["department_name"]
            thresholds = dept_thresholds.get(dept_name, {})
            days_open_flag = thresholds.get("days_open_flag", 60)

            if req["days_open"] <= days_open_flag:
                continue

            bottlenecks = []

            # 1. low_application_flow
            min_rate = thresholds.get("min_weekly_application_rate", 2.0)
            weekly_apps = []
            for wdf in weekly_data:
                row = wdf[wdf["requisition_id"] == rid]
                if not row.empty:
                    weekly_apps.append(row["new_applications"].values[0])
            avg_app_rate = sum(weekly_apps) / len(weekly_apps) if weekly_apps else 0
            if avg_app_rate < min_rate:
                bottlenecks.append("low_application_flow")

            # 2. high_stage_stagnation
            # Get candidates and check if >40% are beyond expected duration
            candidates = conn.execute(
                "SELECT id, application_date, current_stage FROM candidates "
                "WHERE requisition_id = ?", (rid,)
            ).fetchall()
            active_stages = {"applied", "phone_screen", "technical_interview",
                             "onsite_interview", "offer_extended"}
            active_cands = [c for c in candidates if c[2] in active_stages]
            if active_cands:
                stagnant_count = 0
                for cand in active_cands:
                    stage = cand[2]
                    app_date = datetime.strptime(cand[1], "%Y-%m-%d")
                    days_in_pipeline = (REFERENCE_DATE - app_date).days
                    exp = expected_days.get(stage, 7)
                    if days_in_pipeline > exp:
                        stagnant_count += 1
                stagnation_pct = stagnant_count / len(active_cands)
                if stagnation_pct > 0.4:
                    bottlenecks.append("high_stage_stagnation")

            # 3. low_feedback_scores
            min_fb_score = thresholds.get("min_acceptable_feedback_score", 3.0)
            feedback = conn.execute(
                "SELECT score FROM hiring_manager_feedback WHERE requisition_id = ?",
                (rid,)
            ).fetchall()
            if feedback:
                avg_fb = sum(f[0] for f in feedback) / len(feedback)
                if avg_fb < min_fb_score:
                    bottlenecks.append("low_feedback_scores")

            # 4. recruiter_instability
            max_changes = thresholds.get("max_recruiter_changes", 2)
            assignments = conn.execute(
                "SELECT id FROM recruiter_assignments WHERE requisition_id = ? "
                "AND unassigned_date IS NOT NULL", (rid,)
            ).fetchall()
            n_changes = len(assignments)
            if n_changes > max_changes:
                bottlenecks.append("recruiter_instability")

            # 5. feedback_delay
            onsite_cands = [c for c in candidates
                            if c[2] in {"onsite_interview", "offer_extended", "hired"}]
            if onsite_cands:
                onsite_ids = {c[0] for c in onsite_cands}
                fb_cand_ids = set()
                for fb in conn.execute(
                    "SELECT candidate_id FROM hiring_manager_feedback "
                    "WHERE requisition_id = ?", (rid,)
                ).fetchall():
                    if fb[0] in onsite_ids:
                        fb_cand_ids.add(fb[0])
                coverage = len(fb_cand_ids) / len(onsite_cands)
                if coverage < 0.5:
                    bottlenecks.append("feedback_delay")

            # Priority score
            base_score = min(req["days_open"] // 10, 10)
            modifier = sum(
                bottleneck_defs[b]["severity_weight"]
                for b in bottlenecks if b in bottleneck_defs
            )
            priority_score = base_score + modifier

            primary = bottlenecks[0] if bottlenecks else "none"
            secondary = bottlenecks[1] if len(bottlenecks) > 1 else "none"

            results.append({
                "requisition_id": rid,
                "title": req["title"],
                "department": dept_name,
                "days_open": req["days_open"],
                "priority_score": priority_score,
                "primary_bottleneck": primary,
                "secondary_bottleneck": secondary,
                "all_bottlenecks": bottlenecks,
            })

        conn.close()

        # Sort by priority_score desc, then requisition_id asc
        results.sort(key=lambda x: (-x["priority_score"], x["requisition_id"]))
        return results

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
        ground_truth = self._compute_ground_truth()
        gt_ids = [r["requisition_id"] for r in ground_truth]
        gt_map = {r["requisition_id"]: r for r in ground_truth}

        eval_criteria = {}

        # --- Criterion 1: intervention_list_file_exists (10 pts) ---
        csv_path = os.path.join(self.workspace, "priority_intervention_list.csv")
        file_exists = os.path.exists(csv_path)
        eval_criteria["intervention_list_file_exists"] = {
            "passed": file_exists,
            "score": 10 if file_exists else 0,
            "max_score": 10,
        }
        if not file_exists:
            eval_criteria["intervention_list_file_exists"]["reason"] = \
                "priority_intervention_list.csv not found in workspace"

        # --- Criterion 2: correct_columns (10 pts) ---
        expected_cols = [
            "requisition_id", "title", "department", "days_open",
            "priority_score", "primary_bottleneck", "secondary_bottleneck",
        ]
        cols_correct = False
        agent_rows = []
        if file_exists:
            try:
                df = pd.read_csv(csv_path)
                actual_cols = [c.strip().lower() for c in df.columns]
                cols_correct = all(c in actual_cols for c in expected_cols)
                if cols_correct:
                    df.columns = [c.strip().lower() for c in df.columns]
                    agent_rows = df.to_dict("records")
            except Exception:
                pass
        eval_criteria["correct_columns"] = {
            "passed": cols_correct,
            "score": 10 if cols_correct else 0,
            "max_score": 10,
        }
        if not cols_correct:
            eval_criteria["correct_columns"]["reason"] = \
                f"Expected columns: {expected_cols}"

        # --- Criterion 3: correct_flagged_requisitions (20 pts) ---
        agent_ids = []
        if agent_rows:
            try:
                agent_ids = [int(r["requisition_id"]) for r in agent_rows]
            except (ValueError, KeyError):
                pass
        id_match = set(agent_ids) == set(gt_ids)
        # Partial credit: fraction of correct IDs
        if gt_ids:
            correct_ids = set(agent_ids) & set(gt_ids)
            extra_ids = set(agent_ids) - set(gt_ids)
            precision = len(correct_ids) / len(agent_ids) if agent_ids else 0
            recall = len(correct_ids) / len(gt_ids)
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            id_score = round(f1 * 20)
        else:
            id_score = 20 if not agent_ids else 0
        eval_criteria["correct_flagged_requisitions"] = {
            "passed": id_match,
            "score": id_score,
            "max_score": 20,
        }
        if not id_match:
            eval_criteria["correct_flagged_requisitions"]["reason"] = \
                f"Expected {len(gt_ids)} requisitions, got {len(agent_ids)}. " \
                f"Missing: {sorted(set(gt_ids) - set(agent_ids))[:5]}, " \
                f"Extra: {sorted(set(agent_ids) - set(gt_ids))[:5]}"

        # --- Criterion 4: correct_priority_scores (20 pts) ---
        score_matches = 0
        score_total = len(gt_ids)
        if agent_rows and gt_ids:
            agent_map = {}
            for r in agent_rows:
                try:
                    agent_map[int(r["requisition_id"])] = int(float(r.get("priority_score", -1)))
                except (ValueError, TypeError):
                    pass
            for rid in gt_ids:
                if rid in agent_map and agent_map[rid] == gt_map[rid]["priority_score"]:
                    score_matches += 1
        score_pct = score_matches / score_total if score_total > 0 else 0
        ps_score = round(score_pct * 20)
        eval_criteria["correct_priority_scores"] = {
            "passed": score_pct == 1.0,
            "score": ps_score,
            "max_score": 20,
        }
        if score_pct < 1.0:
            eval_criteria["correct_priority_scores"]["reason"] = \
                f"{score_matches}/{score_total} priority scores correct"

        # --- Criterion 5: correct_bottleneck_classification (20 pts) ---
        bn_matches = 0
        bn_total = len(gt_ids)
        if agent_rows and gt_ids:
            agent_bn_map = {}
            for r in agent_rows:
                try:
                    rid = int(r["requisition_id"])
                    agent_bn_map[rid] = {
                        "primary": str(r.get("primary_bottleneck", "")).strip().lower(),
                        "secondary": str(r.get("secondary_bottleneck", "")).strip().lower(),
                    }
                except (ValueError, TypeError):
                    pass
            for rid in gt_ids:
                gt_entry = gt_map[rid]
                if rid in agent_bn_map:
                    agent_entry = agent_bn_map[rid]
                    if (agent_entry["primary"] == gt_entry["primary_bottleneck"]
                            and agent_entry["secondary"] == gt_entry["secondary_bottleneck"]):
                        bn_matches += 1
        bn_pct = bn_matches / bn_total if bn_total > 0 else 0
        bn_score = round(bn_pct * 20)
        eval_criteria["correct_bottleneck_classification"] = {
            "passed": bn_pct == 1.0,
            "score": bn_score,
            "max_score": 20,
        }
        if bn_pct < 1.0:
            eval_criteria["correct_bottleneck_classification"]["reason"] = \
                f"{bn_matches}/{bn_total} bottleneck classifications correct"

        # --- Criterion 6: correct_sort_order (10 pts) ---
        sort_correct = False
        if agent_ids and gt_ids:
            sort_correct = agent_ids == gt_ids
        eval_criteria["correct_sort_order"] = {
            "passed": sort_correct,
            "score": 10 if sort_correct else 0,
            "max_score": 10,
        }
        if not sort_correct:
            eval_criteria["correct_sort_order"]["reason"] = \
                "Rows not sorted by priority_score desc, requisition_id asc"

        # --- Criterion 7: response_summary (10 pts) ---
        # The action should mention the total count and top priority requisition
        summary_ok = False
        if ground_truth and action:
            top_req_id = str(ground_truth[0]["requisition_id"])
            total_count = str(len(ground_truth))
            summary_ok = top_req_id in action and total_count in action
        elif not ground_truth:
            summary_ok = True
        eval_criteria["response_summary"] = {
            "passed": summary_ok,
            "score": 10 if summary_ok else 0,
            "max_score": 10,
        }
        if not summary_ok:
            eval_criteria["response_summary"]["reason"] = \
                "Response should mention total flagged count and top priority requisition ID"

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import os

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # Step 1: List departments
        depts_raw = json.loads(call_tool("list_departments"))
        dept_map = {d["id"]: d["name"] for d in depts_raw}

        # Step 2: Load workspace config files
        with open(os.path.join(self.workspace, "department_thresholds.yaml")) as f:
            dept_thresholds = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "bottleneck_classification.json")) as f:
            bottleneck_defs = json.load(f)
        pipeline_stages = pd.read_csv(os.path.join(self.workspace, "pipeline_stages.csv"))
        expected_days_map = dict(zip(pipeline_stages["stage"], pipeline_stages["expected_days"]))
        with open(os.path.join(self.workspace, "priority_scoring_rules.txt")) as f:
            _ = f.read()  # Read for reference

        # Step 3: Gather all open requisitions via paginated queries
        all_open_reqs = []
        page = 1
        while True:
            resp = json.loads(call_tool("query_requisitions", status="open", page=page))
            all_open_reqs.extend(resp["results"])
            if page >= resp["total_pages"]:
                break
            page += 1

        # Step 4: Identify requisitions open > 60 days
        ref_date = datetime(2026, 4, 15)
        flagged_reqs = []
        for req in all_open_reqs:
            open_date = datetime.strptime(req["open_date"], "%Y-%m-%d")
            days_open = (ref_date - open_date).days
            dept_name = dept_map[req["department_id"]]
            thresholds = dept_thresholds.get(dept_name, {})
            days_threshold = thresholds.get("days_open_flag", 60)
            if days_open > days_threshold:
                req["days_open"] = days_open
                req["department_name"] = dept_name
                flagged_reqs.append(req)

        # Step 5: Load weekly pipeline data for flow rates
        weekly_files = sorted([
            f for f in os.listdir(self.workspace)
            if f.startswith("weekly_pipeline_week_") and f.endswith(".csv")
        ])
        weekly_data = []
        for wf in weekly_files:
            df = pd.read_csv(os.path.join(self.workspace, wf))
            weekly_data.append(df)

        # Step 6: For each flagged requisition, gather data and compute bottlenecks
        results = []
        for req in flagged_reqs:
            rid = req["id"]
            dept_name = req["department_name"]
            thresholds = dept_thresholds.get(dept_name, {})

            # Get candidate applications (paginated)
            all_candidates = []
            cpage = 1
            while True:
                cresp = json.loads(call_tool("get_candidate_applications",
                                             requisition_id=rid, page=cpage))
                all_candidates.extend(cresp["results"])
                if cpage >= cresp["total_pages"]:
                    break
                cpage += 1

            # Get recruiter assignments
            assignments = json.loads(call_tool("get_recruiter_assignments",
                                               requisition_id=rid))

            # Get hiring manager feedback
            feedback = json.loads(call_tool("get_hiring_manager_feedback",
                                            requisition_id=rid))

            # Get pipeline stage summary
            stage_summary = json.loads(call_tool("get_pipeline_stage_summary",
                                                  requisition_id=rid))

            bottlenecks = []

            # 1. low_application_flow
            min_rate = thresholds.get("min_weekly_application_rate", 2.0)
            weekly_apps = []
            for wdf in weekly_data:
                row = wdf[wdf["requisition_id"] == rid]
                if not row.empty:
                    weekly_apps.append(row["new_applications"].values[0])
            avg_app_rate = sum(weekly_apps) / len(weekly_apps) if weekly_apps else 0
            if avg_app_rate < min_rate:
                bottlenecks.append("low_application_flow")

            # 2. high_stage_stagnation
            active_stages = {"applied", "phone_screen", "technical_interview",
                             "onsite_interview", "offer_extended"}
            active_cands = [c for c in all_candidates if c["current_stage"] in active_stages]
            if active_cands:
                stagnant = 0
                for cand in active_cands:
                    stage = cand["current_stage"]
                    app_date = datetime.strptime(cand["application_date"], "%Y-%m-%d")
                    days_in = (ref_date - app_date).days
                    exp = expected_days_map.get(stage, 7)
                    if days_in > exp:
                        stagnant += 1
                if stagnant / len(active_cands) > 0.4:
                    bottlenecks.append("high_stage_stagnation")

            # 3. low_feedback_scores
            min_fb = thresholds.get("min_acceptable_feedback_score", 3.0)
            if feedback:
                avg_fb = sum(f["score"] for f in feedback) / len(feedback)
                if avg_fb < min_fb:
                    bottlenecks.append("low_feedback_scores")

            # 4. recruiter_instability
            max_changes = thresholds.get("max_recruiter_changes", 2)
            n_changes = sum(1 for a in assignments if a["unassigned_date"] is not None)
            if n_changes > max_changes:
                bottlenecks.append("recruiter_instability")

            # 5. feedback_delay
            onsite_cands = [c for c in all_candidates
                            if c["current_stage"] in {"onsite_interview", "offer_extended", "hired"}]
            if onsite_cands:
                onsite_ids = {c["id"] for c in onsite_cands}
                fb_cand_ids = {f["candidate_id"] for f in feedback if f["candidate_id"] in onsite_ids}
                coverage = len(fb_cand_ids) / len(onsite_cands)
                if coverage < 0.5:
                    bottlenecks.append("feedback_delay")

            # Priority score
            base_score = min(req["days_open"] // 10, 10)
            modifier = sum(
                bottleneck_defs[b]["severity_weight"]
                for b in bottlenecks if b in bottleneck_defs
            )
            priority_score = base_score + modifier

            primary = bottlenecks[0] if bottlenecks else "none"
            secondary = bottlenecks[1] if len(bottlenecks) > 1 else "none"

            results.append({
                "requisition_id": rid,
                "title": req["title"],
                "department": dept_name,
                "days_open": req["days_open"],
                "priority_score": priority_score,
                "primary_bottleneck": primary,
                "secondary_bottleneck": secondary,
            })

        # Sort by priority_score desc, requisition_id asc
        results.sort(key=lambda x: (-x["priority_score"], x["requisition_id"]))

        # Write deliverable
        df_out = pd.DataFrame(results)
        csv_path = os.path.join(self.workspace, "priority_intervention_list.csv")
        df_out.to_csv(csv_path, index=False)

        # Construct action summary
        top_id = results[0]["requisition_id"] if results else "N/A"
        action = (
            f"Analysis complete. Identified {len(results)} requisitions with chronic "
            f"hiring delays requiring intervention. The highest priority requisition is "
            f"ID {top_id}. Full results written to priority_intervention_list.csv."
        )

        assert tool_call_count >= 15, \
            f"Tool call count too low: {tool_call_count} (need >= 15)"

        return self.step(action)
