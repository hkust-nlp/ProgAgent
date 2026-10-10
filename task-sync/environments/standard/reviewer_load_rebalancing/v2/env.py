"""
Environment for code review bottleneck analysis task.
Defines tools for querying PR/reviewer data and evaluates
the agent's overload analysis and rebalancing proposal.
"""
from typing import Tuple, Dict, List, Any
import sqlite3
import os
import json
import csv

try:
    import yaml
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml", "-q"])
    import yaml


PAGE_SIZE = 20


def tool(description: str, parameters: dict):
    """Decorator that attaches tool metadata to a method."""
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

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _db_conn(self):
        return sqlite3.connect(self.db_path)

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description=(
            "List team members with optional filters. Returns paginated results "
            "including id, name, email, team, role, specializations, hire_date, "
            "and timezone for each member."
        ),
        parameters={
            "type": "object",
            "properties": {
                "team": {
                    "type": "string",
                    "description": "Filter by team name (e.g. 'backend', 'frontend', 'platform', 'data', 'mobile')",
                },
                "role": {
                    "type": "string",
                    "description": "Filter by role (e.g. 'junior', 'mid', 'senior', 'lead')",
                },
                "offset": {
                    "type": "integer",
                    "description": "Pagination offset, default 0",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results per page (default and max 20)",
                },
            },
            "required": [],
        },
    )
    def list_team_members(
        self,
        team: str = None,
        role: str = None,
        offset: int = 0,
        limit: int = PAGE_SIZE,
    ):
        limit = min(int(limit), PAGE_SIZE)
        offset = int(offset)
        conn = self._db_conn()
        cur = conn.cursor()
        query = "SELECT * FROM team_members WHERE 1=1"
        params: list = []
        if team:
            query += " AND team = ?"
            params.append(team)
        if role:
            query += " AND role = ?"
            params.append(role)
        cur.execute(query.replace("SELECT *", "SELECT COUNT(*)"), params)
        total = cur.fetchone()[0]
        cur.execute(query + " ORDER BY id LIMIT ? OFFSET ?", params + [limit, offset])
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return {
            "members": rows,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total,
        }

    @tool(
        description="Get detailed information for a single team member by ID.",
        parameters={
            "type": "object",
            "properties": {
                "member_id": {
                    "type": "integer",
                    "description": "The team member's unique ID",
                },
            },
            "required": ["member_id"],
        },
    )
    def get_team_member(self, member_id: int):
        member_id = int(member_id)
        conn = self._db_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM team_members WHERE id = ?", (member_id,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": f"No team member with id {member_id}"}
        return dict(zip(cols, row))

    @tool(
        description=(
            "Query pull requests with optional filters. Returns paginated results "
            "including id, title, repo, author_id, created_at, priority, "
            "complexity_score, lines_changed, language, and status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by PR status: 'open', 'merged', or 'closed'",
                },
                "priority": {
                    "type": "string",
                    "description": "Filter by priority level: 'P0', 'P1', 'P2', or 'P3'",
                },
                "repo": {
                    "type": "string",
                    "description": "Filter by repository name",
                },
                "author_id": {
                    "type": "integer",
                    "description": "Filter by author's team member ID",
                },
                "offset": {
                    "type": "integer",
                    "description": "Pagination offset, default 0",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results per page (default and max 20)",
                },
            },
            "required": [],
        },
    )
    def query_pull_requests(
        self,
        status: str = None,
        priority: str = None,
        repo: str = None,
        author_id: int = None,
        offset: int = 0,
        limit: int = PAGE_SIZE,
    ):
        limit = min(int(limit), PAGE_SIZE)
        offset = int(offset)
        conn = self._db_conn()
        cur = conn.cursor()
        query = "SELECT * FROM pull_requests WHERE 1=1"
        params: list = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if priority:
            query += " AND priority = ?"
            params.append(priority)
        if repo:
            query += " AND repo = ?"
            params.append(repo)
        if author_id is not None:
            query += " AND author_id = ?"
            params.append(int(author_id))
        cur.execute(query.replace("SELECT *", "SELECT COUNT(*)"), params)
        total = cur.fetchone()[0]
        cur.execute(query + " ORDER BY id LIMIT ? OFFSET ?", params + [limit, offset])
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return {
            "pull_requests": rows,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total,
        }

    @tool(
        description="Get full details of a single pull request by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "pr_id": {
                    "type": "integer",
                    "description": "The pull request's unique ID",
                },
            },
            "required": ["pr_id"],
        },
    )
    def get_pr_details(self, pr_id: int):
        pr_id = int(pr_id)
        conn = self._db_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM pull_requests WHERE id = ?", (pr_id,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": f"No pull request with id {pr_id}"}
        return dict(zip(cols, row))

    @tool(
        description=(
            "Query review assignments with optional filters. Returns paginated "
            "results including id, pr_id, reviewer_id, assigned_at, completed_at, "
            "status, and round_number."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reviewer_id": {
                    "type": "integer",
                    "description": "Filter by reviewer's team member ID",
                },
                "pr_id": {
                    "type": "integer",
                    "description": "Filter by pull request ID",
                },
                "status": {
                    "type": "string",
                    "description": (
                        "Filter by assignment status: 'pending', 'in_progress', "
                        "'completed', or 'declined'"
                    ),
                },
                "offset": {
                    "type": "integer",
                    "description": "Pagination offset, default 0",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results per page (default and max 20)",
                },
            },
            "required": [],
        },
    )
    def get_reviewer_assignments(
        self,
        reviewer_id: int = None,
        pr_id: int = None,
        status: str = None,
        offset: int = 0,
        limit: int = PAGE_SIZE,
    ):
        limit = min(int(limit), PAGE_SIZE)
        offset = int(offset)
        conn = self._db_conn()
        cur = conn.cursor()
        query = "SELECT * FROM review_assignments WHERE 1=1"
        params: list = []
        if reviewer_id is not None:
            query += " AND reviewer_id = ?"
            params.append(int(reviewer_id))
        if pr_id is not None:
            query += " AND pr_id = ?"
            params.append(int(pr_id))
        if status:
            query += " AND status = ?"
            params.append(status)
        cur.execute(query.replace("SELECT *", "SELECT COUNT(*)"), params)
        total = cur.fetchone()[0]
        cur.execute(query + " ORDER BY id LIMIT ? OFFSET ?", params + [limit, offset])
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return {
            "assignments": rows,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total,
        }

    @tool(
        description=(
            "Get aggregated review-completion statistics for a specific reviewer. "
            "Returns the number of completed reviews, average duration in hours, "
            "average quality score (1-5 scale), and total comments written."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reviewer_id": {
                    "type": "integer",
                    "description": "The reviewer's team member ID",
                },
            },
            "required": ["reviewer_id"],
        },
    )
    def get_review_completion_stats(self, reviewer_id: int):
        reviewer_id = int(reviewer_id)
        conn = self._db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*)              AS total_completed,
                COALESCE(AVG(rc.duration_hours), 0)  AS avg_duration_hours,
                COALESCE(AVG(rc.quality_score),  0)  AS avg_quality_score,
                COALESCE(SUM(rc.comments_count), 0)  AS total_comments
            FROM review_completions rc
            JOIN review_assignments ra ON rc.assignment_id = ra.id
            WHERE ra.reviewer_id = ?
            """,
            (reviewer_id,),
        )
        row = cur.fetchone()
        conn.close()
        return {
            "reviewer_id": reviewer_id,
            "total_completed": row[0],
            "avg_duration_hours": round(row[1], 2),
            # Eligibility compares the mean against an exact policy threshold;
            # rounding here can promote an ineligible reviewer across it.
            "avg_quality_score": row[2],
            "total_comments": int(row[3]),
        }

    # ------------------------------------------------------------------
    # Ground-truth computation (used by step)
    # ------------------------------------------------------------------

    def _compute_ground_truth(self):
        """Recompute the correct answer directly from DB + workspace configs."""
        import pandas as pd

        conn = self._db_conn()
        members_df = pd.read_sql("SELECT * FROM team_members", conn)
        prs_df = pd.read_sql("SELECT * FROM pull_requests", conn)
        assigns_df = pd.read_sql("SELECT * FROM review_assignments", conn)
        completions_df = pd.read_sql("SELECT * FROM review_completions", conn)
        conn.close()

        # Configs
        with open(os.path.join(self.workspace, "review_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "priority_weights.json")) as f:
            priority_weights = json.load(f)
        with open(os.path.join(self.workspace, "role_capacity.json")) as f:
            role_capacity = json.load(f)

        overload_threshold = policy["overload_threshold"]
        lookback = policy["availability_lookback_weeks"]
        min_quality = policy["min_quality_score_for_reassignment_target"]

        # Availability (recent weeks)
        avail_files = sorted(
            f
            for f in os.listdir(self.workspace)
            if f.startswith("availability_schedule_week_") and f.endswith(".csv")
        )
        recent = avail_files[-lookback:] if len(avail_files) >= lookback else avail_files
        member_hours: Dict[int, list] = {}
        for af in recent:
            df = pd.read_csv(os.path.join(self.workspace, af))
            for _, row in df.iterrows():
                mid = int(row["member_id"])
                wh = sum(
                    row[f"{d}_hours"]
                    for d in ["monday", "tuesday", "wednesday", "thursday", "friday"]
                )
                member_hours.setdefault(mid, []).append(wh)
        avg_hours = {mid: sum(h) / len(h) for mid, h in member_hours.items()}

        member_map = {int(r["id"]): r.to_dict() for _, r in members_df.iterrows()}
        open_prs = prs_df[prs_df["status"] == "open"]
        pr_map = {int(r["id"]): r.to_dict() for _, r in open_prs.iterrows()}
        open_pr_ids = set(pr_map.keys())

        # Active assignments for open PRs
        active = assigns_df[
            assigns_df["status"].isin(["pending", "in_progress"])
            & assigns_df["pr_id"].isin(open_pr_ids)
        ]

        reviewer_loads: Dict[int, float] = {}
        reviewer_assign_map: Dict[int, list] = {}
        for _, a in active.iterrows():
            rid = int(a["reviewer_id"])
            pr = pr_map.get(int(a["pr_id"]))
            if pr:
                load = priority_weights[pr["priority"]] * pr["complexity_score"]
                reviewer_loads[rid] = reviewer_loads.get(rid, 0) + load
                reviewer_assign_map.setdefault(rid, []).append(a.to_dict())

        overloaded = []
        overloaded_ids: set = set()
        for rid, load in reviewer_loads.items():
            m = member_map.get(rid)
            if not m:
                continue
            cap = avg_hours.get(rid, 0) * role_capacity.get(m["role"], 0.5)
            ratio = load / cap if cap > 0 else float("inf")
            if ratio > overload_threshold:
                overloaded.append(
                    {
                        "reviewer_id": rid,
                        "reviewer_name": m["name"],
                        "team": m["team"],
                        "role": m["role"],
                        "weighted_load": round(load, 2),
                        "capacity": round(cap, 2),
                        "overload_ratio": round(ratio, 2),
                        "pending_review_count": len(reviewer_assign_map.get(rid, [])),
                    }
                )
                overloaded_ids.add(rid)
        overloaded.sort(key=lambda x: x["overload_ratio"], reverse=True)

        # Per-reviewer average quality (for reassignment-target validation)
        reviewer_quality: Dict[int, list] = {}
        for _, rc in completions_df.iterrows():
            aid = int(rc["assignment_id"])
            match = assigns_df[assigns_df["id"] == aid]
            if len(match):
                rid = int(match.iloc[0]["reviewer_id"])
                reviewer_quality.setdefault(rid, []).append(rc["quality_score"])
        avg_quality = {
            rid: sum(qs) / len(qs) for rid, qs in reviewer_quality.items()
        }

        return {
            "overloaded": overloaded,
            "overloaded_ids": overloaded_ids,
            "member_map": member_map,
            "pr_map": pr_map,
            "avg_quality": avg_quality,
            "overload_threshold": overload_threshold,
            "min_quality": min_quality,
            "priority_weights": priority_weights,
            "role_capacity": role_capacity,
            "avg_hours": avg_hours,
            "reviewer_assign_map": reviewer_assign_map,
        }

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

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
        gt = self._compute_ground_truth()
        eval_criteria: Dict[str, dict] = {}

        # ---- Criterion 1: overloaded_file_structure (10 pts) ----
        OVL_COLS = [
            "reviewer_id", "reviewer_name", "team", "role",
            "weighted_load", "capacity", "overload_ratio", "pending_review_count",
        ]
        ovl_path = os.path.join(self.workspace, "overloaded_reviewers.csv")
        c1_max = 10
        c1_score = 0
        agent_ovl: list = []
        ovl_fieldnames: list = []
        if os.path.exists(ovl_path):
            try:
                with open(ovl_path, "r", newline="") as f:
                    reader = csv.DictReader(f)
                    ovl_fieldnames = list(reader.fieldnames or [])
                    agent_ovl = list(reader)
                if all(c in ovl_fieldnames for c in OVL_COLS):
                    c1_score = c1_max
                else:
                    c1_score = 5
            except Exception:
                pass
        eval_criteria["overloaded_file_structure"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": "" if c1_score == c1_max else "File missing or incorrect columns",
        }

        # ---- Criterion 2: overloaded_reviewer_ids (25 pts) ----
        c2_max = 25
        gt_ids = gt["overloaded_ids"]
        try:
            agent_ids = {int(r["reviewer_id"]) for r in agent_ovl}
        except (KeyError, ValueError):
            agent_ids = set()

        if gt_ids:
            correct = len(gt_ids & agent_ids)
            prec = correct / len(agent_ids) if agent_ids else 0
            rec = correct / len(gt_ids)
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
            c2_score = round(c2_max * f1)
        else:
            c2_score = c2_max if not agent_ids else 0
        eval_criteria["overloaded_reviewer_ids"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": (
                ""
                if c2_score == c2_max
                else f"Expected IDs {sorted(gt_ids)}, got {sorted(agent_ids)}"
            ),
        }

        # ---- Criterion 3: overload_metrics_accuracy (20 pts) ----
        c3_max = 20
        gt_metrics = {r["reviewer_id"]: r for r in gt["overloaded"]}
        correct_metrics = 0
        total_checks = 0
        TOLERANCE = 0.15
        for row in agent_ovl:
            try:
                rid = int(row["reviewer_id"])
                if rid not in gt_metrics:
                    continue
                gt_r = gt_metrics[rid]
                for field in ["weighted_load", "capacity", "overload_ratio"]:
                    total_checks += 1
                    if abs(float(row[field]) - gt_r[field]) <= TOLERANCE:
                        correct_metrics += 1
            except (KeyError, ValueError):
                pass
        c3_score = round(c3_max * correct_metrics / total_checks) if total_checks else 0
        eval_criteria["overload_metrics_accuracy"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": (
                ""
                if c3_score == c3_max
                else f"{correct_metrics}/{total_checks} metric values within tolerance"
            ),
        }

        # ---- Criterion 4: rebalancing_proposals_valid (25 pts) ----
        REB_COLS = [
            "pr_id", "pr_title", "current_reviewer_id", "current_reviewer_name",
            "proposed_reviewer_id", "proposed_reviewer_name", "reason",
        ]
        reb_path = os.path.join(self.workspace, "rebalancing_proposal.csv")
        c4_max = 25
        c4_score = 0
        agent_proposals: list = []
        if os.path.exists(reb_path):
            try:
                with open(reb_path, "r", newline="") as f:
                    reader = csv.DictReader(f)
                    reb_fields = list(reader.fieldnames or [])
                    agent_proposals = list(reader)
                has_cols = all(c in reb_fields for c in REB_COLS)
            except Exception:
                has_cols = False

            if has_cols and agent_proposals:
                valid = 0
                for prop in agent_proposals:
                    try:
                        pr_id = int(prop["pr_id"])
                        cur_rid = int(prop["current_reviewer_id"])
                        new_rid = int(prop["proposed_reviewer_id"])
                        pr = gt["pr_map"].get(pr_id)
                        new_m = gt["member_map"].get(new_rid)
                        if not pr or not new_m:
                            continue
                        if cur_rid not in gt["overloaded_ids"]:
                            continue
                        if pr["language"] not in new_m["specializations"].split(","):
                            continue
                        if new_rid in gt["overloaded_ids"]:
                            continue
                        if new_rid == int(pr["author_id"]):
                            continue
                        avg_q = gt["avg_quality"].get(new_rid, 0)
                        if avg_q < gt["min_quality"]:
                            continue
                        valid += 1
                    except (KeyError, ValueError):
                        pass
                c4_score = round(c4_max * valid / len(agent_proposals))
            elif has_cols:
                c4_score = 3  # correct structure but empty
        eval_criteria["rebalancing_proposals_valid"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": "" if c4_score == c4_max else f"Score {c4_score}/{c4_max}",
        }

        # ---- Criterion 5: response_summary (20 pts) ----
        c5_max = 20
        c5_score = 0
        gt_ovl_count = len(gt["overloaded"])
        # Check overloaded count in response
        if str(gt_ovl_count) in str(action):
            c5_score += 10
        # Check proposal count consistency (agent's file vs agent's text)
        if str(len(agent_proposals)) in str(action):
            c5_score += 10
        eval_criteria["response_summary"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": (
                ""
                if c5_score == c5_max
                else f"Expected overloaded count {gt_ovl_count} and proposal count in response"
            ),
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())
        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ------------------------------------------------------------------
    # Self-verification
    # ------------------------------------------------------------------

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
        import pandas as pd

        tool_call_count = 0

        def _call(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # ---- 1. Read workspace configuration files ----
        with open(os.path.join(self.workspace, "review_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "priority_weights.json")) as f:
            priority_weights = json.load(f)
        with open(os.path.join(self.workspace, "role_capacity.json")) as f:
            role_capacity = json.load(f)

        overload_threshold = policy["overload_threshold"]
        lookback = policy["availability_lookback_weeks"]
        min_quality = policy["min_quality_score_for_reassignment_target"]

        # ---- 2. Read availability schedules ----
        avail_files = sorted(
            f
            for f in os.listdir(self.workspace)
            if f.startswith("availability_schedule_week_") and f.endswith(".csv")
        )
        recent = avail_files[-lookback:] if len(avail_files) >= lookback else avail_files

        member_hours: Dict[int, list] = {}
        for af in recent:
            df = pd.read_csv(os.path.join(self.workspace, af))
            for _, row in df.iterrows():
                mid = int(row["member_id"])
                wh = sum(
                    row[f"{d}_hours"]
                    for d in ["monday", "tuesday", "wednesday", "thursday", "friday"]
                )
                member_hours.setdefault(mid, []).append(wh)
        avg_hours = {mid: sum(h) / len(h) for mid, h in member_hours.items()}

        # ---- 3. List all team members (paginated) ----
        all_members: list = []
        offset = 0
        while True:
            res = _call("list_team_members", offset=offset, limit=PAGE_SIZE)
            all_members.extend(res["members"])
            if not res["has_more"]:
                break
            offset += PAGE_SIZE
        member_map = {m["id"]: m for m in all_members}

        # ---- 4. Get all open pull requests (paginated) ----
        open_prs: list = []
        offset = 0
        while True:
            res = _call("query_pull_requests", status="open", offset=offset, limit=PAGE_SIZE)
            open_prs.extend(res["pull_requests"])
            if not res["has_more"]:
                break
            offset += PAGE_SIZE
        pr_map = {p["id"]: p for p in open_prs}

        # ---- 5. Get all pending + in_progress assignments ----
        active_assignments: list = []
        for st in ("pending", "in_progress"):
            offset = 0
            while True:
                res = _call("get_reviewer_assignments", status=st, offset=offset, limit=PAGE_SIZE)
                active_assignments.extend(res["assignments"])
                if not res["has_more"]:
                    break
                offset += PAGE_SIZE

        # Keep only those linked to open PRs
        active_assignments = [a for a in active_assignments if a["pr_id"] in pr_map]

        # Group by reviewer
        reviewer_assigns: Dict[int, list] = {}
        for a in active_assignments:
            reviewer_assigns.setdefault(a["reviewer_id"], []).append(a)

        # ---- 6. Compute weighted load, capacity, overload ratio ----
        overloaded: list = []
        overloaded_ids: set = set()
        all_stats: Dict[int, dict] = {}

        for rid, assigns in reviewer_assigns.items():
            m = member_map.get(rid)
            if not m:
                continue
            load = sum(
                priority_weights[pr_map[a["pr_id"]]["priority"]]
                * pr_map[a["pr_id"]]["complexity_score"]
                for a in assigns
                if a["pr_id"] in pr_map
            )
            cap = avg_hours.get(rid, 0) * role_capacity.get(m["role"], 0.5)
            ratio = load / cap if cap > 0 else float("inf")
            stats = {
                "reviewer_id": rid,
                "reviewer_name": m["name"],
                "team": m["team"],
                "role": m["role"],
                "weighted_load": round(load, 2),
                "capacity": round(cap, 2),
                "overload_ratio": round(ratio, 2),
                "pending_review_count": len(assigns),
            }
            all_stats[rid] = stats
            if ratio > overload_threshold:
                overloaded.append(stats)
                overloaded_ids.add(rid)

        overloaded.sort(key=lambda x: x["overload_ratio"], reverse=True)

        # ---- 7. Fetch quality stats for non-overloaded members ----
        quality_cache: Dict[int, dict] = {}
        for m in all_members:
            if m["id"] not in overloaded_ids:
                qs = _call("get_review_completion_stats", reviewer_id=m["id"])
                quality_cache[m["id"]] = qs

        # ---- 8. Generate rebalancing proposals ----
        proposals: list = []
        running_loads: Dict[int, float] = {
            rid: s["weighted_load"] for rid, s in all_stats.items()
        }

        for ov in overloaded:
            rid = ov["reviewer_id"]
            assigns = reviewer_assigns[rid]
            # Pair each assignment with its PR, sort by priority weight ascending
            a_pr = [
                (a, pr_map[a["pr_id"]])
                for a in assigns
                if a["pr_id"] in pr_map
            ]
            a_pr.sort(key=lambda x: priority_weights[x[1]["priority"]])

            for a, pr in a_pr:
                cur_load = running_loads.get(rid, ov["weighted_load"])
                cur_cap = ov["capacity"]
                if cur_cap > 0 and cur_load / cur_cap <= overload_threshold:
                    break  # no longer overloaded after previous reassignments

                item_load = priority_weights[pr["priority"]] * pr["complexity_score"]
                pr_lang = pr["language"]

                best_target = None
                best_ratio = float("inf")

                for mid, mm in member_map.items():
                    if mid == rid or mid == pr["author_id"]:
                        continue
                    if mid in overloaded_ids:
                        continue
                    if pr_lang not in mm["specializations"].split(","):
                        continue
                    qs = quality_cache.get(mid)
                    if (
                        not qs
                        or qs["total_completed"] == 0
                        or qs["avg_quality_score"] < min_quality
                    ):
                        continue
                    t_load = running_loads.get(mid, 0)
                    t_cap = avg_hours.get(mid, 0) * role_capacity.get(mm["role"], 0.5)
                    new_ratio = (t_load + item_load) / t_cap if t_cap > 0 else float("inf")
                    if new_ratio > overload_threshold:
                        continue
                    if new_ratio < best_ratio:
                        best_ratio = new_ratio
                        best_target = mm

                if best_target:
                    tid = best_target["id"]
                    running_loads[rid] = running_loads.get(rid, ov["weighted_load"]) - item_load
                    running_loads[tid] = running_loads.get(tid, 0) + item_load
                    proposals.append(
                        {
                            "pr_id": pr["id"],
                            "pr_title": pr["title"],
                            "current_reviewer_id": rid,
                            "current_reviewer_name": ov["reviewer_name"],
                            "proposed_reviewer_id": tid,
                            "proposed_reviewer_name": best_target["name"],
                            "reason": (
                                f"Reviewer {ov['reviewer_name']} overloaded "
                                f"(ratio: {ov['overload_ratio']}). "
                                f"{best_target['name']} has matching expertise "
                                f"and available capacity."
                            ),
                        }
                    )

        proposals.sort(key=lambda x: x["pr_id"])

        # ---- 9. Write deliverables ----
        with open(
            os.path.join(self.workspace, "overloaded_reviewers.csv"), "w", newline=""
        ) as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "reviewer_id", "reviewer_name", "team", "role",
                    "weighted_load", "capacity", "overload_ratio",
                    "pending_review_count",
                ],
            )
            w.writeheader()
            w.writerows(overloaded)

        with open(
            os.path.join(self.workspace, "rebalancing_proposal.csv"), "w", newline=""
        ) as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "pr_id", "pr_title", "current_reviewer_id",
                    "current_reviewer_name", "proposed_reviewer_id",
                    "proposed_reviewer_name", "reason",
                ],
            )
            w.writeheader()
            w.writerows(proposals)

        # ---- 10. Build response ----
        avg_ratio = (
            sum(o["overload_ratio"] for o in overloaded) / len(overloaded)
            if overloaded
            else 0
        )
        action = (
            f"Analysis complete. Found {len(overloaded)} overloaded reviewers "
            f"with an average overload ratio of {avg_ratio:.2f}. "
            f"Proposed {len(proposals)} PR reassignments to rebalance the "
            f"review workload. Results saved to overloaded_reviewers.csv "
            f"and rebalancing_proposal.csv."
        )

        assert tool_call_count >= 15, (
            f"verify used only {tool_call_count} tool calls (minimum 15 required)"
        )

        return self.step(action)
