"""
Milestone Risk Assessment - Task Environment (hardened tool surface)

Provides tools for querying milestone/sprint/bug/team data and evaluates
the agent's risk assessment deliverables.

Hardened surface (M2 + M3): tools return a mix of shapes — deeply nested
record objects with cursor pagination, JSON-encoded strings, MCP-style
envelopes, plain key:value text, and Python-repr strings. Error responses
use a different object shape than success responses and share no keys with
success payloads. Task semantics, data, ground truth, and scoring are
unchanged from the base environment.
"""

import ast
import csv
import glob as glob_mod
import hashlib
import json
import math
import os
import re
import sqlite3
from datetime import datetime, timedelta
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


# ─── Hardened tool-surface helpers ───

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


def _select(name):
    return {"type": "select", "select": {"name": name}}


def _number(value):
    return {"type": "number", "number": value}


def _title(text):
    return {"type": "title", "title": [
        {"type": "text", "text": {"content": text, "link": None}, "plain_text": text}]}


def _relation(*ids):
    return {"type": "relation", "relation": [{"id": i} for i in ids]}


def _date(start):
    return {"type": "date", "date": {"start": start, "end": None}}


def _rich_text(text):
    if text is None:
        return {"type": "rich_text", "rich_text": []}
    return {"type": "rich_text", "rich_text": [
        {"type": "text", "text": {"content": text, "link": None}, "plain_text": text}]}


def _coerce_int(value, name):
    """Best-effort integer coercion; returns (value, error)."""
    if isinstance(value, bool) or value is None:
        return None, _error(400, "validation_error",
                            f"body.{name} should be an integer, instead was {_shape(value)}.")
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, _error(400, "validation_error",
                            f"body.{name} should be an integer, instead was {_shape(value)}.")


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
        description="List milestone records with optional status filter. Paginated.",
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
    def list_milestones(self, status: Any = None, page: Any = None, page_size: Any = None) -> dict:
        valid_statuses = ["upcoming", "in_progress", "completed", "cancelled", "all"]
        if status not in valid_statuses:
            return _error(400, "validation_error",
                          f"body.status should be one of {valid_statuses}, instead was {_shape(status)}.")
        page, err = _coerce_int(page, "page")
        if err:
            return err
        if page_size is None:
            page_size = 20
        page_size, err = _coerce_int(page_size, "page_size")
        if err:
            return err
        page_size = max(1, min(page_size, 20))
        page = max(1, page)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if status == "all":
            cur.execute("SELECT COUNT(*) FROM milestones")
        else:
            cur.execute("SELECT COUNT(*) FROM milestones WHERE status = ?", (status,))
        total = cur.fetchone()[0]
        if status == "all":
            cur.execute(
                "SELECT id, name, project, target_date, status, priority FROM milestones ORDER BY id LIMIT ? OFFSET ?",
                (page_size, offset))
        else:
            cur.execute(
                "SELECT id, name, project, target_date, status, priority FROM milestones WHERE status = ? ORDER BY id LIMIT ? OFFSET ?",
                (status, page_size, offset))
        rows = cur.fetchall()
        conn.close()
        results = [
            {
                "object": "milestone",
                "id": r[0],
                "properties": {
                    "Name": _title(r[1]),
                    "Project": _select(r[2]),
                    "Target Date": _date(r[3]),
                    "Status": _select(r[4]),
                    "Priority": _select(r[5]),
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
        description="Get the full record for a specific milestone, including its description.",
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
    def get_milestone_info(self, milestone_id: Any = None) -> str:
        milestone_id, err = _coerce_int(milestone_id, "milestone_id")
        if err:
            return json.dumps(err)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, name, project, target_date, status, priority, description FROM milestones WHERE id = ?",
                    (milestone_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return json.dumps(_error(
                404, "object_not_found", f"Could not find milestone with ID: {milestone_id}."))
        payload = {
            "object": "milestone",
            "id": row[0],
            "properties": {
                "Name": _title(row[1]),
                "Project": _select(row[2]),
                "Target Date": _date(row[3]),
                "Status": _select(row[4]),
                "Priority": _select(row[5]),
                "Description": _rich_text(row[6]),
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    @tool(
        description="Get sprint history for a specific milestone: every sprint associated with it, with dates, points, and status.",
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
    def get_sprint_history(self, milestone_id: Any = None) -> Any:
        milestone_id, err = _coerce_int(milestone_id, "milestone_id")
        if err:
            return err
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM milestones WHERE id = ?", (milestone_id,))
        if cur.fetchone() is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find milestone with ID: {milestone_id}.")
        cur.execute(
            "SELECT id, name, start_date, end_date, planned_points, completed_points, status "
            "FROM sprints WHERE milestone_id = ? ORDER BY id",
            (milestone_id,))
        rows = [{"sprint_id": r[0], "name": r[1], "start_date": r[2], "end_date": r[3],
                 "planned_points": r[4], "completed_points": r[5], "status": r[6]}
                for r in cur.fetchall()]
        conn.close()
        return _envelope({"milestone_id": milestone_id, "sprints": rows})

    @tool(
        description="Get story records for a specific sprint, with point estimates, assignee, and status. Paginated.",
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
    def get_stories_for_sprint(self, sprint_id: Any = None, page: Any = None, page_size: Any = None) -> dict:
        sprint_id, err = _coerce_int(sprint_id, "sprint_id")
        if err:
            return err
        page, err = _coerce_int(page, "page")
        if err:
            return err
        if page_size is None:
            page_size = 30
        page_size, err = _coerce_int(page_size, "page_size")
        if err:
            return err
        page_size = max(1, min(page_size, 30))
        page = max(1, page)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM sprints WHERE id = ?", (sprint_id,))
        if cur.fetchone() is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find sprint with ID: {sprint_id}.")
        cur.execute("SELECT COUNT(*) FROM stories WHERE sprint_id = ?", (sprint_id,))
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT id, title, estimated_points, actual_points, assignee_id, status "
            "FROM stories WHERE sprint_id = ? ORDER BY id LIMIT ? OFFSET ?",
            (sprint_id, page_size, offset))
        rows = cur.fetchall()
        conn.close()
        results = [
            {
                "object": "story",
                "id": r[0],
                "properties": {
                    "Title": _title(r[1]),
                    "Estimated Points": _number(r[2]),
                    "Actual Points": _number(r[3]),
                    "Assignee": _relation(r[4]),
                    "Status": _select(r[5]),
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
        description="Get bug records associated with a specific milestone, with severity, found phase, and status. Paginated.",
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
    def get_bugs_for_milestone(self, milestone_id: Any = None, page: Any = None, page_size: Any = None) -> dict:
        milestone_id, err = _coerce_int(milestone_id, "milestone_id")
        if err:
            return err
        page, err = _coerce_int(page, "page")
        if err:
            return err
        if page_size is None:
            page_size = 25
        page_size, err = _coerce_int(page_size, "page_size")
        if err:
            return err
        page_size = max(1, min(page_size, 25))
        page = max(1, page)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM milestones WHERE id = ?", (milestone_id,))
        if cur.fetchone() is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find milestone with ID: {milestone_id}.")
        cur.execute("SELECT COUNT(*) FROM bugs WHERE milestone_id = ?", (milestone_id,))
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT id, title, severity, found_phase, sprint_id, status, reported_date "
            "FROM bugs WHERE milestone_id = ? ORDER BY id LIMIT ? OFFSET ?",
            (milestone_id, page_size, offset))
        rows = cur.fetchall()
        conn.close()
        results = [
            {
                "object": "bug",
                "id": r[0],
                "properties": {
                    "Title": _title(r[1]),
                    "Severity": _select(r[2]),
                    "Found Phase": _select(r[3]),
                    "Sprint": _relation(*([r[4]] if r[4] is not None else [])),
                    "Status": _select(r[5]),
                    "Reported Date": _date(r[6]),
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
        description="Get team member assignments for a specific milestone: member, role in the milestone, and allocation percentage.",
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
    def get_team_assignments(self, milestone_id: Any = None) -> Any:
        milestone_id, err = _coerce_int(milestone_id, "milestone_id")
        if err:
            return err
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM milestones WHERE id = ?", (milestone_id,))
        if cur.fetchone() is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find milestone with ID: {milestone_id}.")
        cur.execute(
            "SELECT team_member_id, role_in_milestone, allocation_pct "
            "FROM milestone_assignments WHERE milestone_id = ? ORDER BY team_member_id",
            (milestone_id,))
        rows = [{"team_member_id": r[0], "role_in_milestone": r[1], "allocation_pct": r[2]}
                for r in cur.fetchall()]
        conn.close()
        return repr({"milestone_id": milestone_id, "assignments": rows})

    @tool(
        description="Get the profile of a specific team member: name, role, department, hire/departure dates, and status.",
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
    def get_team_member(self, member_id: Any = None) -> Any:
        member_id, err = _coerce_int(member_id, "member_id")
        if err:
            return err
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, role, department, hire_date, departure_date, status "
            "FROM team_members WHERE id = ?", (member_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find team member with ID: {member_id}.")
        fields = {
            "id": row[0],
            "name": row[1],
            "role": row[2],
            "department": row[3],
            "hire_date": row[4],
            "departure_date": row[5],
            "status": row[6],
        }
        return "\n".join(f"{k}: {v}" for k, v in fields.items())

    @tool(
        description="Get dependencies linked to a specific milestone, both incoming and outgoing, with type and status.",
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
    def get_dependencies(self, milestone_id: Any = None) -> str:
        milestone_id, err = _coerce_int(milestone_id, "milestone_id")
        if err:
            return json.dumps(err)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM milestones WHERE id = ?", (milestone_id,))
        if cur.fetchone() is None:
            conn.close()
            return json.dumps(_error(
                404, "object_not_found", f"Could not find milestone with ID: {milestone_id}."))
        cur.execute(
            "SELECT id, source_milestone_id, target_milestone_id, dependency_type, status, description "
            "FROM dependencies WHERE source_milestone_id = ? OR target_milestone_id = ? ORDER BY id",
            (milestone_id, milestone_id))
        rows = cur.fetchall()
        conn.close()
        results = [
            {
                "object": "dependency",
                "id": r[0],
                "properties": {
                    "Source Milestone": _relation(r[1]),
                    "Target Milestone": _relation(r[2]),
                    "Type": _select(r[3]),
                    "Status": _select(r[4]),
                    "Description": _rich_text(r[5]),
                },
            }
            for r in rows
        ]
        payload = {
            "object": "list",
            "results": results,
            "has_more": False,
            "next_cursor": None,
        }
        return json.dumps(payload, ensure_ascii=False)

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

        # 9. Final response text (10 pts)
        # prompt.md requires: "High-risk milestones: <name1>, <name2>, ..." in descending
        # overall_risk_score order (ties: milestone_id ascending). If none, state so.
        gt_high_names = [r["milestone_name"] for r in gt_results if r["risk_level"] == "HIGH"]
        prefix = "High-risk milestones: "
        action_stripped = action.strip()
        resp_score = 0
        if gt_high_names:
            if action_stripped.startswith(prefix):
                listed_names = [n.strip() for n in action_stripped[len(prefix):].split(",")]
                if listed_names == gt_high_names:
                    resp_score = 10
                elif set(listed_names) == set(gt_high_names):
                    resp_score = 7  # correct names, wrong order
                else:
                    overlap = len([n for n in listed_names if n in set(gt_high_names)])
                    resp_score = round(5 * overlap / max(1, len(gt_high_names)))
            elif prefix.lower() in action_stripped.lower():
                resp_score = 3
            resp_reason = ("" if resp_score >= 8
                           else f"Expected '{prefix}' followed by {len(gt_high_names)} names in descending risk order")
        else:
            if any(kw in action_stripped.lower() for kw in ["none", "no high", "no milestone"]):
                resp_score = 10
            resp_reason = ("" if resp_score == 10
                           else "Expected statement that no milestones are high risk")
        eval_criteria["final_response"] = {
            "passed": resp_score >= 8, "score": resp_score, "max_score": 10,
            "reason": resp_reason,
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

        Note: the hardened tool surface returns mixed shapes, so this solver
        unwraps MCP envelopes, parses JSON strings / repr strings / key:value
        text, walks the deep-nested property objects, and follows
        has_more/next_cursor pagination.
        """
        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        def unwrap_envelope(resp):
            return json.loads(resp["content"][0]["text"])

        def parse_kv_text(text):
            fields = {}
            for line in text.splitlines():
                if ": " in line:
                    k, v = line.split(": ", 1)
                    fields[k] = v
                elif line.endswith(":"):
                    fields[line[:-1]] = ""
            return fields

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

        # 1. Get all active milestones (upcoming + in_progress).
        # list_milestones returns deep-nested records with cursor pagination.
        active_milestones = []
        for status in ["upcoming", "in_progress"]:
            page = 1
            while True:
                res = call_tool("list_milestones", status=status, page=page)
                for rec in res["results"]:
                    props = rec["properties"]
                    active_milestones.append({
                        "id": rec["id"],
                        "name": props["Name"]["title"][0]["plain_text"],
                    })
                if not res["has_more"]:
                    break
                page = res["next_cursor"]

        results = []
        for ms in active_milestones:
            ms_id = ms["id"]
            ms_name = ms["name"]

            # --- Estimation Accuracy ---
            # get_sprint_history returns an MCP envelope.
            sprint_res = unwrap_envelope(call_tool("get_sprint_history", milestone_id=ms_id))
            sprint_ids = [s["sprint_id"] for s in sprint_res["sprints"]]
            total_est = 0
            total_act = 0
            for sp_id in sprint_ids:
                # get_stories_for_sprint returns deep-nested records with
                # cursor pagination.
                page = 1
                while True:
                    story_res = call_tool("get_stories_for_sprint", sprint_id=sp_id, page=page)
                    for rec in story_res["results"]:
                        props = rec["properties"]
                        if props["Status"]["select"]["name"] == "done":
                            total_est += props["Estimated Points"]["number"]
                            total_act += props["Actual Points"]["number"]
                    if not story_res["has_more"]:
                        break
                    page = story_res["next_cursor"]

            if total_est > 0:
                ratio = total_act / total_est
                deviation = abs(1.0 - ratio)
                est_score = min(deviation / est_norm, 1.0)
            else:
                ratio = 1.0
                est_score = 0.0

            # --- Dependency Risk ---
            # get_dependencies returns a JSON-encoded string of nested records.
            dep_res = json.loads(call_tool("get_dependencies", milestone_id=ms_id))
            dep_weighted_sum = 0.0
            total_dep_max = 0.0
            at_risk_dep_ids = []
            for rec in dep_res["results"]:
                props = rec["properties"]
                did = rec["id"]
                dstatus = props["Status"]["select"]["name"]
                dtype = props["Type"]["select"]["name"]
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
            # get_bugs_for_milestone returns deep-nested records with cursor
            # pagination.
            all_bug_phases = []
            page = 1
            while True:
                bug_res = call_tool("get_bugs_for_milestone", milestone_id=ms_id, page=page)
                for rec in bug_res["results"]:
                    all_bug_phases.append(
                        rec["properties"]["Found Phase"]["select"]["name"])
                if not bug_res["has_more"]:
                    break
                page = bug_res["next_cursor"]

            total_bugs = len(all_bug_phases)
            escaped_bugs = sum(1 for ph in all_bug_phases if ph in escaped_phases)
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
            # get_team_assignments returns a Python-repr string.
            assign_res = ast.literal_eval(call_tool("get_team_assignments", milestone_id=ms_id))
            assigned_ids = [a["team_member_id"] for a in assign_res["assignments"]]
            churned_ids = []
            active_member_ids = []
            for mid in assigned_ids:
                # get_team_member returns plain key: value text (dict on error).
                mem_raw = call_tool("get_team_member", member_id=mid)
                if isinstance(mem_raw, dict):
                    continue  # error response
                mem = parse_kv_text(mem_raw)
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
        print(f"verify: {tool_call_count} tool calls made")

        return self.step(action)
