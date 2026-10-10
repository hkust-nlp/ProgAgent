import sqlite3
import os
import json
import csv
import math
import re
import glob as glob_mod
from typing import Tuple, Dict, List, Any
from datetime import datetime, timedelta
import yaml


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

    # ── Tool methods ──────────────────────────────────────────────────

    @tool(
        description="List milestones with optional status filter. Returns up to page_size milestones per page.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["upcoming", "in_progress", "completed", "cancelled", "all"],
                    "description": "Filter milestones by status. Use 'all' for no filter.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 20, default 20).",
                },
            },
            "required": ["status", "page"],
        },
    )
    def list_milestones(self, status: str, page: int, page_size: int = 20) -> dict:
        page = int(page)
        page_size = min(int(page_size) if page_size else 20, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if status == "all":
            cur.execute("SELECT COUNT(*) FROM milestones")
        else:
            cur.execute("SELECT COUNT(*) FROM milestones WHERE status = ?", (status,))
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        if status == "all":
            cur.execute(
                "SELECT id, name, project, target_date, status, priority FROM milestones ORDER BY id LIMIT ? OFFSET ?",
                (page_size, offset))
        else:
            cur.execute(
                "SELECT id, name, project, target_date, status, priority FROM milestones WHERE status = ? ORDER BY id LIMIT ? OFFSET ?",
                (status, page_size, offset))
        rows = [{"id": r[0], "name": r[1], "project": r[2], "target_date": r[3],
                 "status": r[4], "priority": r[5]} for r in cur.fetchall()]
        conn.close()
        return {"milestones": rows, "page": page, "total_pages": total_pages, "total": total}

    @tool(
        description="Get detailed information about a specific milestone.",
        parameters={
            "type": "object",
            "properties": {
                "milestone_id": {
                    "type": "integer",
                    "description": "The milestone ID.",
                },
            },
            "required": ["milestone_id"],
        },
    )
    def get_milestone_info(self, milestone_id: int) -> dict:
        milestone_id = int(milestone_id)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, name, project, target_date, status, priority, description FROM milestones WHERE id = ?",
                    (milestone_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": "Milestone not found"}
        return {"id": row[0], "name": row[1], "project": row[2], "target_date": row[3],
                "status": row[4], "priority": row[5], "description": row[6]}

    @tool(
        description="Get sprint history for a specific milestone. Returns all sprints associated with the milestone.",
        parameters={
            "type": "object",
            "properties": {
                "milestone_id": {
                    "type": "integer",
                    "description": "The milestone ID.",
                },
            },
            "required": ["milestone_id"],
        },
    )
    def get_sprint_history(self, milestone_id: int) -> Any:
        milestone_id = int(milestone_id)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM milestones WHERE id = ?", (milestone_id,))
        if cur.fetchone() is None:
            conn.close()
            return {"error": "Milestone not found"}
        cur.execute(
            "SELECT id, name, start_date, end_date, planned_points, completed_points, status "
            "FROM sprints WHERE milestone_id = ? ORDER BY id",
            (milestone_id,))
        rows = [{"sprint_id": r[0], "name": r[1], "start_date": r[2], "end_date": r[3],
                 "planned_points": r[4], "completed_points": r[5], "status": r[6]}
                for r in cur.fetchall()]
        conn.close()
        return {"milestone_id": milestone_id, "sprints": rows}

    @tool(
        description="Get stories for a specific sprint with pagination.",
        parameters={
            "type": "object",
            "properties": {
                "sprint_id": {
                    "type": "integer",
                    "description": "The sprint ID.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 30, default 30).",
                },
            },
            "required": ["sprint_id", "page"],
        },
    )
    def get_stories_for_sprint(self, sprint_id: int, page: int, page_size: int = 30) -> dict:
        sprint_id = int(sprint_id)
        page = int(page)
        page_size = min(int(page_size) if page_size else 30, 30)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM stories WHERE sprint_id = ?", (sprint_id,))
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        cur.execute(
            "SELECT id, title, estimated_points, actual_points, assignee_id, status "
            "FROM stories WHERE sprint_id = ? ORDER BY id LIMIT ? OFFSET ?",
            (sprint_id, page_size, offset))
        rows = [{"story_id": r[0], "title": r[1], "estimated_points": r[2],
                 "actual_points": r[3], "assignee_id": r[4], "status": r[5]}
                for r in cur.fetchall()]
        conn.close()
        return {"sprint_id": sprint_id, "stories": rows, "page": page,
                "total_pages": total_pages, "total": total}

    @tool(
        description="Get bugs associated with a specific milestone. Returns paginated bug records.",
        parameters={
            "type": "object",
            "properties": {
                "milestone_id": {
                    "type": "integer",
                    "description": "The milestone ID.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 25, default 25).",
                },
            },
            "required": ["milestone_id", "page"],
        },
    )
    def get_bugs_for_milestone(self, milestone_id: int, page: int, page_size: int = 25) -> dict:
        milestone_id = int(milestone_id)
        page = int(page)
        page_size = min(int(page_size) if page_size else 25, 25)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM bugs WHERE milestone_id = ?", (milestone_id,))
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        cur.execute(
            "SELECT id, title, severity, found_phase, sprint_id, status, reported_date "
            "FROM bugs WHERE milestone_id = ? ORDER BY id LIMIT ? OFFSET ?",
            (milestone_id, page_size, offset))
        rows = [{"bug_id": r[0], "title": r[1], "severity": r[2], "found_phase": r[3],
                 "sprint_id": r[4], "status": r[5], "reported_date": r[6]}
                for r in cur.fetchall()]
        conn.close()
        return {"milestone_id": milestone_id, "bugs": rows, "page": page,
                "total_pages": total_pages, "total": total}

    @tool(
        description="Get team member assignments for a specific milestone.",
        parameters={
            "type": "object",
            "properties": {
                "milestone_id": {
                    "type": "integer",
                    "description": "The milestone ID.",
                },
            },
            "required": ["milestone_id"],
        },
    )
    def get_team_assignments(self, milestone_id: int) -> Any:
        milestone_id = int(milestone_id)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM milestones WHERE id = ?", (milestone_id,))
        if cur.fetchone() is None:
            conn.close()
            return {"error": "Milestone not found"}
        cur.execute(
            "SELECT team_member_id, role_in_milestone, allocation_pct "
            "FROM milestone_assignments WHERE milestone_id = ? ORDER BY team_member_id",
            (milestone_id,))
        rows = [{"team_member_id": r[0], "role_in_milestone": r[1], "allocation_pct": r[2]}
                for r in cur.fetchall()]
        conn.close()
        return {"milestone_id": milestone_id, "assignments": rows}

    @tool(
        description="Get information about a specific team member.",
        parameters={
            "type": "object",
            "properties": {
                "member_id": {
                    "type": "integer",
                    "description": "The team member ID.",
                },
            },
            "required": ["member_id"],
        },
    )
    def get_team_member(self, member_id: int) -> dict:
        member_id = int(member_id)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, role, department, hire_date, departure_date, status "
            "FROM team_members WHERE id = ?", (member_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": "Team member not found"}
        return {"id": row[0], "name": row[1], "role": row[2], "department": row[3],
                "hire_date": row[4], "departure_date": row[5], "status": row[6]}

    @tool(
        description="Get dependencies for a specific milestone (both incoming and outgoing).",
        parameters={
            "type": "object",
            "properties": {
                "milestone_id": {
                    "type": "integer",
                    "description": "The milestone ID.",
                },
            },
            "required": ["milestone_id"],
        },
    )
    def get_dependencies(self, milestone_id: int) -> Any:
        milestone_id = int(milestone_id)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM milestones WHERE id = ?", (milestone_id,))
        if cur.fetchone() is None:
            conn.close()
            return {"error": "Milestone not found"}
        cur.execute(
            "SELECT id, source_milestone_id, target_milestone_id, dependency_type, status, description "
            "FROM dependencies WHERE source_milestone_id = ? OR target_milestone_id = ? ORDER BY id",
            (milestone_id, milestone_id))
        rows = [{"dep_id": r[0], "source_milestone_id": r[1], "target_milestone_id": r[2],
                 "dependency_type": r[3], "status": r[4], "description": r[5]}
                for r in cur.fetchall()]
        conn.close()
        return {"milestone_id": milestone_id, "dependencies": rows}

    # ── Workspace loaders (used by step and verify) ──────────────────

    def _load_risk_config(self) -> dict:
        with open(os.path.join(self.workspace, "risk_config.yaml")) as f:
            return yaml.safe_load(f)

    def _load_scoring_weights(self) -> dict:
        with open(os.path.join(self.workspace, "scoring_weights.json")) as f:
            return json.load(f)

    def _load_confluence_deps(self) -> Dict[int, int]:
        """Return dep_id -> severity_weight from confluence markdown files."""
        weights = {}
        for fpath in sorted(glob_mod.glob(os.path.join(self.workspace, "confluence_dep_*.md"))):
            with open(fpath) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("|") and not line.startswith("| dep_id") and not line.startswith("|---"):
                        parts = [p.strip() for p in line.split("|")]
                        parts = [p for p in parts if p]
                        if len(parts) >= 4:
                            try:
                                did = int(parts[0])
                                sw = int(parts[3])
                                weights[did] = sw
                            except (ValueError, IndexError):
                                pass
        return weights

    def _load_qa_reports(self) -> Dict[int, float]:
        """Return sprint_id -> test_coverage_pct from QA CSV files."""
        coverage = {}
        for fpath in sorted(glob_mod.glob(os.path.join(self.workspace, "qa_report_*.csv"))):
            with open(fpath, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        sid = int(row["sprint_id"])
                        cov = float(row["test_coverage_pct"])
                        coverage[sid] = cov
                    except (ValueError, KeyError):
                        pass
        return coverage

    def _load_team_capacity(self) -> Dict[int, int]:
        """Return member_id -> effective_capacity_pct from team JSON files."""
        caps = {}
        for fpath in sorted(glob_mod.glob(os.path.join(self.workspace, "team_capacity_*.json"))):
            with open(fpath) as f:
                data = json.load(f)
            for m in data.get("members", []):
                caps[m["member_id"]] = m["effective_capacity_pct"]
        return caps

    # ── Ground truth computation ─────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute the full risk assessment ground truth from DB + workspace."""
        config = self._load_risk_config()
        weights = self._load_scoring_weights()
        dep_severity = self._load_confluence_deps()
        qa_coverage = self._load_qa_reports()
        team_caps = self._load_team_capacity()

        ref_date = datetime.strptime(config["reference_date"], "%Y-%m-%d")
        churn_days = config["churn_window_days"]
        est_norm = config["estimation_accuracy"]["normalization_factor"]
        dep_block_factor = config["dependency_risk"]["active_blocking_factor"]
        bug_norm = config["bug_escape"]["normalization_factor"]
        escaped_phases = set(config["bug_escape"]["escaped_phases"])
        churn_norm = config["team_churn"]["normalization_factor"]
        high_thresh = config["risk_levels"]["high_threshold"]
        med_thresh = config["risk_levels"]["medium_threshold"]
        action_thresh = config["mitigation_action_threshold"]

        w_est = weights["estimation_accuracy"]
        w_dep = weights["dependency_risk"]
        w_bug = weights["bug_escape"]
        w_churn = weights["team_churn"]

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # Get active milestones
        cur.execute(
            "SELECT id, name, project, target_date, status, priority "
            "FROM milestones WHERE status IN ('upcoming', 'in_progress') ORDER BY id")
        active_milestones = cur.fetchall()

        results = []
        for ms in active_milestones:
            ms_id, ms_name = ms[0], ms[1]

            # --- Estimation Accuracy ---
            cur.execute("SELECT id FROM sprints WHERE milestone_id = ?", (ms_id,))
            sprint_ids = [r[0] for r in cur.fetchall()]
            total_est = 0
            total_act = 0
            for sp_id in sprint_ids:
                cur.execute(
                    "SELECT estimated_points, actual_points FROM stories "
                    "WHERE sprint_id = ? AND status = 'done'", (sp_id,))
                for est, act in cur.fetchall():
                    total_est += est
                    total_act += act
            if total_est > 0:
                ratio = total_act / total_est
                deviation = abs(1.0 - ratio)
                est_score = min(deviation / est_norm, 1.0)
            else:
                ratio = 1.0
                est_score = 0.0

            # --- Dependency Risk ---
            cur.execute(
                "SELECT id, dependency_type, status FROM dependencies "
                "WHERE source_milestone_id = ? OR target_milestone_id = ?",
                (ms_id, ms_id))
            deps = cur.fetchall()
            dep_weighted_sum = 0.0
            total_dep_max = 0.0
            at_risk_dep_ids = []
            for did, dtype, dstatus in deps:
                sw = dep_severity.get(did, 3)
                total_dep_max += 5.0
                if dstatus == "at_risk":
                    dep_weighted_sum += sw
                    at_risk_dep_ids.append(did)
                elif dstatus == "active" and dtype == "blocks":
                    dep_weighted_sum += sw * dep_block_factor
            if total_dep_max > 0:
                dep_score = min(dep_weighted_sum / total_dep_max, 1.0)
            else:
                dep_score = 0.0

            # --- Bug Escape Rate ---
            cur.execute(
                "SELECT found_phase FROM bugs WHERE milestone_id = ?", (ms_id,))
            all_bugs = cur.fetchall()
            total_bugs = len(all_bugs)
            escaped_bugs = sum(1 for (ph,) in all_bugs if ph in escaped_phases)
            if total_bugs > 0:
                escape_rate = escaped_bugs / total_bugs
            else:
                escape_rate = 0.0

            # Get avg test coverage for this milestone's sprints
            cov_values = [qa_coverage[sid] for sid in sprint_ids if sid in qa_coverage]
            avg_coverage = sum(cov_values) / len(cov_values) if cov_values else 70.0
            coverage_factor = 2.0 - avg_coverage / 100.0
            adjusted_rate = escape_rate * coverage_factor
            bug_score = min(adjusted_rate / bug_norm, 1.0)

            # --- Team Churn ---
            cur.execute(
                "SELECT team_member_id FROM milestone_assignments WHERE milestone_id = ?",
                (ms_id,))
            assigned_ids = [r[0] for r in cur.fetchall()]
            churned_ids = []
            active_member_ids = []
            for mid in assigned_ids:
                cur.execute(
                    "SELECT hire_date, departure_date, status FROM team_members WHERE id = ?",
                    (mid,))
                row = cur.fetchone()
                if row is None:
                    continue
                hire_str, dep_str, mstatus = row
                hire_dt = datetime.strptime(hire_str, "%Y-%m-%d")
                is_churned = False
                if mstatus == "departed":
                    is_churned = True
                elif (ref_date - hire_dt).days <= churn_days:
                    is_churned = True
                if is_churned:
                    churned_ids.append(mid)
                if mstatus != "departed":
                    active_member_ids.append(mid)

            total_assigned = len(assigned_ids)
            if total_assigned > 0:
                raw_churn = len(churned_ids) / total_assigned
            else:
                raw_churn = 0.0

            cap_values = [team_caps.get(mid, 100) for mid in active_member_ids]
            avg_cap = (sum(cap_values) / len(cap_values) / 100.0) if cap_values else 1.0
            if avg_cap <= 0:
                avg_cap = 0.01
            churn_score = min(raw_churn / (avg_cap * churn_norm), 1.0)

            # --- Overall ---
            overall = round(w_est * est_score + w_dep * dep_score +
                          w_bug * bug_score + w_churn * churn_score, 4)
            if overall >= high_thresh:
                level = "HIGH"
            elif overall >= med_thresh:
                level = "MEDIUM"
            else:
                level = "LOW"

            results.append({
                "milestone_id": ms_id,
                "milestone_name": ms_name,
                "estimation_accuracy_score": round(est_score, 4),
                "dependency_risk_score": round(dep_score, 4),
                "bug_escape_score": round(bug_score, 4),
                "team_churn_score": round(churn_score, 4),
                "overall_risk_score": overall,
                "risk_level": level,
                "est_ratio": round(ratio, 4),
                "at_risk_dep_ids": sorted(at_risk_dep_ids),
                "escaped_bugs": escaped_bugs,
                "total_bugs": total_bugs,
                "churned_member_ids": sorted(set(churned_ids)),
                "action_threshold": action_thresh,
            })

        # Sort by overall desc, then milestone_id asc
        results.sort(key=lambda x: (-x["overall_risk_score"], x["milestone_id"]))
        conn.close()
        return results, config, weights

    # ── step ─────────────────────────────────────────────────────────

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        gt_results, config, weights = self._compute_ground_truth()
        eval_criteria = {}

        high_thresh = config["risk_levels"]["high_threshold"]
        gt_high = [r for r in gt_results if r["risk_level"] == "HIGH"]
        gt_ms_ids = set(r["milestone_id"] for r in gt_results)
        gt_by_id = {r["milestone_id"]: r for r in gt_results}

        # 1. risk_assessment.csv exists with correct columns (10 pts)
        csv_path = os.path.join(self.workspace, "risk_assessment.csv")
        expected_cols = ["milestone_id", "milestone_name", "estimation_accuracy_score",
                        "dependency_risk_score", "bug_escape_score", "team_churn_score",
                        "overall_risk_score", "risk_level"]
        csv_score = 0
        agent_rows = []
        if os.path.isfile(csv_path):
            try:
                with open(csv_path, newline="") as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    if all(c in cols for c in expected_cols):
                        agent_rows = list(reader)
                        csv_score = 10
                    else:
                        csv_score = 3
            except Exception:
                csv_score = 0
        eval_criteria["csv_format"] = {
            "passed": csv_score == 10, "score": csv_score, "max_score": 10,
            "reason": "" if csv_score == 10 else "CSV missing or wrong columns"
        }

        # 2. Correct milestone set (10 pts)
        agent_ids = set()
        for row in agent_rows:
            try:
                agent_ids.add(int(row["milestone_id"]))
            except (ValueError, KeyError):
                pass
        if agent_ids == gt_ms_ids and len(agent_rows) == len(gt_results):
            ms_set_score = 10
        elif gt_ms_ids.issubset(agent_ids):
            ms_set_score = 5
        elif len(agent_ids & gt_ms_ids) > 0:
            ms_set_score = int(10 * len(agent_ids & gt_ms_ids) / len(gt_ms_ids))
        else:
            ms_set_score = 0
        eval_criteria["milestone_set"] = {
            "passed": ms_set_score == 10, "score": ms_set_score, "max_score": 10,
            "reason": "" if ms_set_score == 10 else f"Expected {len(gt_ms_ids)} milestones, got {len(agent_ids)}"
        }

        # Build agent lookup
        agent_by_id = {}
        for row in agent_rows:
            try:
                mid = int(row["milestone_id"])
                agent_by_id[mid] = row
            except (ValueError, KeyError):
                pass

        # 3. Estimation accuracy scores (15 pts)
        est_correct = 0
        est_total = len(gt_results)
        for gt in gt_results:
            mid = gt["milestone_id"]
            if mid in agent_by_id:
                try:
                    agent_val = float(agent_by_id[mid]["estimation_accuracy_score"])
                    if abs(agent_val - gt["estimation_accuracy_score"]) <= 0.02:
                        est_correct += 1
                except (ValueError, KeyError):
                    pass
        est_score = round(15 * est_correct / max(1, est_total), 1)
        eval_criteria["estimation_accuracy_scores"] = {
            "passed": est_score >= 14, "score": est_score, "max_score": 15,
            "reason": "" if est_score >= 14 else f"{est_correct}/{est_total} correct"
        }

        # 4. Dependency risk scores (15 pts)
        dep_correct = 0
        for gt in gt_results:
            mid = gt["milestone_id"]
            if mid in agent_by_id:
                try:
                    agent_val = float(agent_by_id[mid]["dependency_risk_score"])
                    if abs(agent_val - gt["dependency_risk_score"]) <= 0.02:
                        dep_correct += 1
                except (ValueError, KeyError):
                    pass
        dep_score = round(15 * dep_correct / max(1, est_total), 1)
        eval_criteria["dependency_risk_scores"] = {
            "passed": dep_score >= 14, "score": dep_score, "max_score": 15,
            "reason": "" if dep_score >= 14 else f"{dep_correct}/{est_total} correct"
        }

        # 5. Bug escape scores (15 pts)
        bug_correct = 0
        for gt in gt_results:
            mid = gt["milestone_id"]
            if mid in agent_by_id:
                try:
                    agent_val = float(agent_by_id[mid]["bug_escape_score"])
                    if abs(agent_val - gt["bug_escape_score"]) <= 0.02:
                        bug_correct += 1
                except (ValueError, KeyError):
                    pass
        bug_score_val = round(15 * bug_correct / max(1, est_total), 1)
        eval_criteria["bug_escape_scores"] = {
            "passed": bug_score_val >= 14, "score": bug_score_val, "max_score": 15,
            "reason": "" if bug_score_val >= 14 else f"{bug_correct}/{est_total} correct"
        }

        # 6. Team churn scores (10 pts)
        churn_correct = 0
        for gt in gt_results:
            mid = gt["milestone_id"]
            if mid in agent_by_id:
                try:
                    agent_val = float(agent_by_id[mid]["team_churn_score"])
                    if abs(agent_val - gt["team_churn_score"]) <= 0.02:
                        churn_correct += 1
                except (ValueError, KeyError):
                    pass
        churn_score_val = round(10 * churn_correct / max(1, est_total), 1)
        eval_criteria["team_churn_scores"] = {
            "passed": churn_score_val >= 9, "score": churn_score_val, "max_score": 10,
            "reason": "" if churn_score_val >= 9 else f"{churn_correct}/{est_total} correct"
        }

        # 7. Overall scores and risk levels (15 pts)
        overall_correct = 0
        level_correct = 0
        for gt in gt_results:
            mid = gt["milestone_id"]
            if mid in agent_by_id:
                try:
                    agent_val = float(agent_by_id[mid]["overall_risk_score"])
                    if abs(agent_val - gt["overall_risk_score"]) <= 0.02:
                        overall_correct += 1
                except (ValueError, KeyError):
                    pass
                try:
                    if agent_by_id[mid]["risk_level"].strip().upper() == gt["risk_level"]:
                        level_correct += 1
                except (ValueError, KeyError):
                    pass
        overall_val = round(8 * overall_correct / max(1, est_total), 1)
        level_val = round(7 * level_correct / max(1, est_total), 1)
        combined = overall_val + level_val
        eval_criteria["overall_and_levels"] = {
            "passed": combined >= 14, "score": combined, "max_score": 15,
            "reason": "" if combined >= 14 else f"overall: {overall_correct}/{est_total}, levels: {level_correct}/{est_total}"
        }

        # 8. Mitigation checklist (10 pts)
        checklist_path = os.path.join(self.workspace, "mitigation_checklist.md")
        checklist_score = 0
        if os.path.isfile(checklist_path):
            with open(checklist_path) as f:
                content = f.read()
            # Check all HIGH risk milestones appear
            found_high = 0
            for gt in gt_high:
                ms_name = gt["milestone_name"]
                ms_id = gt["milestone_id"]
                if str(ms_id) in content and (ms_name in content or ms_name[:30] in content):
                    found_high += 1
            if len(gt_high) > 0:
                checklist_score = round(10 * found_high / len(gt_high))
            else:
                checklist_score = 10 if "no high" in content.lower() or len(content.strip()) > 0 else 5
        eval_criteria["mitigation_checklist"] = {
            "passed": checklist_score >= 8, "score": checklist_score, "max_score": 10,
            "reason": "" if checklist_score >= 8 else f"Found {found_high if os.path.isfile(checklist_path) else 0}/{len(gt_high)} HIGH milestones"
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())
        reward = total_score / max_score

        return reward, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ── verify ───────────────────────────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # Load config from workspace
        config = self._load_risk_config()
        weights = self._load_scoring_weights()
        dep_severity = self._load_confluence_deps()
        qa_coverage = self._load_qa_reports()
        team_caps = self._load_team_capacity()

        ref_date = datetime.strptime(config["reference_date"], "%Y-%m-%d")
        churn_days = config["churn_window_days"]
        est_norm = config["estimation_accuracy"]["normalization_factor"]
        dep_block_factor = config["dependency_risk"]["active_blocking_factor"]
        bug_norm = config["bug_escape"]["normalization_factor"]
        escaped_phases = set(config["bug_escape"]["escaped_phases"])
        churn_norm = config["team_churn"]["normalization_factor"]
        high_thresh = config["risk_levels"]["high_threshold"]
        med_thresh = config["risk_levels"]["medium_threshold"]
        action_thresh = config["mitigation_action_threshold"]

        w_est = weights["estimation_accuracy"]
        w_dep = weights["dependency_risk"]
        w_bug = weights["bug_escape"]
        w_churn = weights["team_churn"]

        # 1. Get all active milestones (upcoming + in_progress)
        active_milestones = []
        for status in ["upcoming", "in_progress"]:
            page = 1
            while True:
                res = call_tool("list_milestones", status=status, page=page)
                active_milestones.extend(res["milestones"])
                if page >= res["total_pages"]:
                    break
                page += 1

        results = []
        for ms in active_milestones:
            ms_id = ms["id"]
            ms_name = ms["name"]

            # --- Estimation Accuracy ---
            sprint_res = call_tool("get_sprint_history", milestone_id=ms_id)
            sprint_ids = [s["sprint_id"] for s in sprint_res["sprints"]]
            total_est = 0
            total_act = 0
            for sp_id in sprint_ids:
                page = 1
                while True:
                    story_res = call_tool("get_stories_for_sprint", sprint_id=sp_id, page=page)
                    for st in story_res["stories"]:
                        if st["status"] == "done":
                            total_est += st["estimated_points"]
                            total_act += st["actual_points"]
                    if page >= story_res["total_pages"]:
                        break
                    page += 1

            if total_est > 0:
                ratio = total_act / total_est
                deviation = abs(1.0 - ratio)
                est_score = min(deviation / est_norm, 1.0)
            else:
                ratio = 1.0
                est_score = 0.0

            # --- Dependency Risk ---
            dep_res = call_tool("get_dependencies", milestone_id=ms_id)
            dep_weighted_sum = 0.0
            total_dep_max = 0.0
            at_risk_dep_ids = []
            for d in dep_res["dependencies"]:
                did = d["dep_id"]
                sw = dep_severity.get(did, 3)
                total_dep_max += 5.0
                if d["status"] == "at_risk":
                    dep_weighted_sum += sw
                    at_risk_dep_ids.append(did)
                elif d["status"] == "active" and d["dependency_type"] == "blocks":
                    dep_weighted_sum += sw * dep_block_factor
            if total_dep_max > 0:
                dep_score = min(dep_weighted_sum / total_dep_max, 1.0)
            else:
                dep_score = 0.0

            # --- Bug Escape Rate ---
            all_bugs = []
            page = 1
            while True:
                bug_res = call_tool("get_bugs_for_milestone", milestone_id=ms_id, page=page)
                all_bugs.extend(bug_res["bugs"])
                if page >= bug_res["total_pages"]:
                    break
                page += 1

            total_bugs = len(all_bugs)
            escaped_bugs = sum(1 for b in all_bugs if b["found_phase"] in escaped_phases)
            if total_bugs > 0:
                escape_rate = escaped_bugs / total_bugs
            else:
                escape_rate = 0.0

            cov_values = [qa_coverage[sid] for sid in sprint_ids if sid in qa_coverage]
            avg_coverage = sum(cov_values) / len(cov_values) if cov_values else 70.0
            coverage_factor = 2.0 - avg_coverage / 100.0
            adjusted_rate = escape_rate * coverage_factor
            bug_score = min(adjusted_rate / bug_norm, 1.0)

            # --- Team Churn ---
            assign_res = call_tool("get_team_assignments", milestone_id=ms_id)
            assigned_ids = [a["team_member_id"] for a in assign_res["assignments"]]
            churned_ids = []
            active_member_ids = []
            for mid in assigned_ids:
                mem = call_tool("get_team_member", member_id=mid)
                if "error" in mem:
                    continue
                hire_dt = datetime.strptime(mem["hire_date"], "%Y-%m-%d")
                is_churned = False
                if mem["status"] == "departed":
                    is_churned = True
                elif (ref_date - hire_dt).days <= churn_days:
                    is_churned = True
                if is_churned:
                    churned_ids.append(mid)
                if mem["status"] != "departed":
                    active_member_ids.append(mid)

            total_assigned = len(assigned_ids)
            if total_assigned > 0:
                raw_churn = len(churned_ids) / total_assigned
            else:
                raw_churn = 0.0

            cap_values = [team_caps.get(mid, 100) for mid in active_member_ids]
            avg_cap = (sum(cap_values) / len(cap_values) / 100.0) if cap_values else 1.0
            if avg_cap <= 0:
                avg_cap = 0.01
            churn_score = min(raw_churn / (avg_cap * churn_norm), 1.0)

            # --- Overall ---
            overall = round(w_est * est_score + w_dep * dep_score +
                          w_bug * bug_score + w_churn * churn_score, 4)
            if overall >= high_thresh:
                level = "HIGH"
            elif overall >= med_thresh:
                level = "MEDIUM"
            else:
                level = "LOW"

            results.append({
                "milestone_id": ms_id,
                "milestone_name": ms_name,
                "estimation_accuracy_score": round(est_score, 4),
                "dependency_risk_score": round(dep_score, 4),
                "bug_escape_score": round(bug_score, 4),
                "team_churn_score": round(churn_score, 4),
                "overall_risk_score": overall,
                "risk_level": level,
                "est_ratio": round(ratio, 4),
                "at_risk_dep_ids": sorted(at_risk_dep_ids),
                "escaped_bugs": escaped_bugs,
                "total_bugs": total_bugs,
                "churned_member_ids": sorted(set(churned_ids)),
            })

        # Sort: overall desc, milestone_id asc
        results.sort(key=lambda x: (-x["overall_risk_score"], x["milestone_id"]))

        # Write risk_assessment.csv
        csv_path = os.path.join(self.workspace, "risk_assessment.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "milestone_id", "milestone_name", "estimation_accuracy_score",
                "dependency_risk_score", "bug_escape_score", "team_churn_score",
                "overall_risk_score", "risk_level"])
            writer.writeheader()
            for r in results:
                writer.writerow({
                    "milestone_id": r["milestone_id"],
                    "milestone_name": r["milestone_name"],
                    "estimation_accuracy_score": r["estimation_accuracy_score"],
                    "dependency_risk_score": r["dependency_risk_score"],
                    "bug_escape_score": r["bug_escape_score"],
                    "team_churn_score": r["team_churn_score"],
                    "overall_risk_score": r["overall_risk_score"],
                    "risk_level": r["risk_level"],
                })

        # Write mitigation_checklist.md
        high_results = [r for r in results if r["risk_level"] == "HIGH"]
        checklist_lines = ["# Sprint Planning Mitigation Checklist\n"]
        for r in high_results:
            checklist_lines.append(f"## {r['milestone_name']} (ID: {r['milestone_id']})")
            checklist_lines.append(f"Overall Risk Score: {r['overall_risk_score']}")
            checklist_lines.append(f"- Estimation Accuracy: {r['estimation_accuracy_score']}")
            checklist_lines.append(f"- Dependency Risk: {r['dependency_risk_score']}")
            checklist_lines.append(f"- Bug Escape Rate: {r['bug_escape_score']}")
            checklist_lines.append(f"- Team Churn: {r['team_churn_score']}")
            checklist_lines.append("")
            checklist_lines.append("Actions:")
            action_thresh = config["mitigation_action_threshold"]
            dims = [
                ("estimation_accuracy_score", "Conduct estimation review - historical ratio: {:.4f}".format(r["est_ratio"])),
                ("dependency_risk_score", "Escalate at-risk dependencies: {}".format(
                    ", ".join(str(d) for d in r["at_risk_dep_ids"]) if r["at_risk_dep_ids"] else "none")),
                ("bug_escape_score", "Strengthen QA process - escape rate: {}/{}".format(
                    r["escaped_bugs"], r["total_bugs"])),
                ("team_churn_score", "Knowledge transfer for members: {}".format(
                    ", ".join(str(m) for m in r["churned_member_ids"]) if r["churned_member_ids"] else "none")),
            ]
            dims.sort(key=lambda x: -r[x[0]])
            for dim_key, action_text in dims:
                if r[dim_key] > action_thresh:
                    checklist_lines.append(f"- {action_text}")
            checklist_lines.append("")
            checklist_lines.append("---\n")

        checklist_path = os.path.join(self.workspace, "mitigation_checklist.md")
        with open(checklist_path, "w") as f:
            f.write("\n".join(checklist_lines))

        # Build final response
        high_names = [r["milestone_name"] for r in high_results]
        action = "High-risk milestones: " + ", ".join(high_names) if high_names else "No high-risk milestones identified."

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need >= 15"

        return self.step(action)
