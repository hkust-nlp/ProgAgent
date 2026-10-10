#!/usr/bin/env python3
"""Environment for audit scope-creep / unauthorized-work detection task."""

import csv
import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


# ── Decorator ───────────────────────────────────────────────────────────

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ── Environment ─────────────────────────────────────────────────────────

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

    # ── Tool methods ────────────────────────────────────────────────────

    @tool(
        description="List engagements with pagination. Returns a page of engagement records including engagement_id, client_name, engagement_type, start_date, end_date, status, and partner_id.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 25).",
                },
            },
            "required": ["page"],
        },
    )
    def list_engagements(self, page: int = 1, page_size: int = 25) -> dict:
        page_size = min(int(page_size), 25)
        page = max(int(page), 1)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM engagements").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM engagements ORDER BY engagement_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "records": [dict(r) for r in rows],
        }

    @tool(
        description="List staff members with pagination. Returns staff_id, name, role, certification_level, department, hire_date.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 50).",
                },
            },
            "required": ["page"],
        },
    )
    def list_staff(self, page: int = 1, page_size: int = 50) -> dict:
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM staff").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM staff ORDER BY staff_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "records": [dict(r) for r in rows],
        }

    @tool(
        description="Query engagement-staff assignments with optional filters. Returns assignment_id, engagement_id, staff_id, assigned_role, start_date, end_date, is_active.",
        parameters={
            "type": "object",
            "properties": {
                "engagement_id": {
                    "type": "string",
                    "description": "Filter by engagement ID.",
                },
                "staff_id": {
                    "type": "string",
                    "description": "Filter by staff ID.",
                },
                "active_only": {
                    "type": "boolean",
                    "description": "If true, return only active assignments.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (max 50).",
                },
            },
            "required": ["page"],
        },
    )
    def query_assignments(
        self,
        page: int = 1,
        page_size: int = 50,
        engagement_id: str = None,
        staff_id: str = None,
        active_only: bool = False,
    ) -> dict:
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        offset = (page - 1) * page_size
        clauses, params = [], []
        if engagement_id:
            clauses.append("engagement_id = ?")
            params.append(engagement_id)
        if staff_id:
            clauses.append("staff_id = ?")
            params.append(staff_id)
        if active_only:
            clauses.append("is_active = 1")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(f"SELECT COUNT(*) FROM assignments{where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM assignments{where} ORDER BY assignment_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "records": [dict(r) for r in rows],
        }

    @tool(
        description="Query time entries with optional filters. Returns entry_id, staff_id, engagement_id, entry_date, hours, task_code, description.",
        parameters={
            "type": "object",
            "properties": {
                "engagement_id": {
                    "type": "string",
                    "description": "Filter by engagement ID.",
                },
                "staff_id": {
                    "type": "string",
                    "description": "Filter by staff ID.",
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date filter (YYYY-MM-DD).",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date filter (YYYY-MM-DD).",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (max 50).",
                },
            },
            "required": ["page"],
        },
    )
    def query_time_entries(
        self,
        page: int = 1,
        page_size: int = 50,
        engagement_id: str = None,
        staff_id: str = None,
        date_from: str = None,
        date_to: str = None,
    ) -> dict:
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        offset = (page - 1) * page_size
        clauses, params = [], []
        if engagement_id:
            clauses.append("engagement_id = ?")
            params.append(engagement_id)
        if staff_id:
            clauses.append("staff_id = ?")
            params.append(staff_id)
        if date_from:
            clauses.append("entry_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("entry_date <= ?")
            params.append(date_to)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(f"SELECT COUNT(*) FROM time_entries{where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM time_entries{where} ORDER BY entry_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "records": [dict(r) for r in rows],
        }

    @tool(
        description="Query file access logs with optional filters. Returns log_id, staff_id, engagement_id, file_name, access_type, access_timestamp.",
        parameters={
            "type": "object",
            "properties": {
                "engagement_id": {
                    "type": "string",
                    "description": "Filter by engagement ID.",
                },
                "staff_id": {
                    "type": "string",
                    "description": "Filter by staff ID.",
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date filter (YYYY-MM-DD), compared to date portion of access_timestamp.",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date filter (YYYY-MM-DD).",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (max 50).",
                },
            },
            "required": ["page"],
        },
    )
    def query_file_access_logs(
        self,
        page: int = 1,
        page_size: int = 50,
        engagement_id: str = None,
        staff_id: str = None,
        date_from: str = None,
        date_to: str = None,
    ) -> dict:
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        offset = (page - 1) * page_size
        clauses, params = [], []
        if engagement_id:
            clauses.append("engagement_id = ?")
            params.append(engagement_id)
        if staff_id:
            clauses.append("staff_id = ?")
            params.append(staff_id)
        if date_from:
            clauses.append("SUBSTR(access_timestamp, 1, 10) >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("SUBSTR(access_timestamp, 1, 10) <= ?")
            params.append(date_to)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(f"SELECT COUNT(*) FROM file_access_logs{where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM file_access_logs{where} ORDER BY log_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "records": [dict(r) for r in rows],
        }

    @tool(
        description="Query client document requests with optional filters. Returns request_id, engagement_id, requester_staff_id, document_type, request_date, scope_area, status.",
        parameters={
            "type": "object",
            "properties": {
                "engagement_id": {
                    "type": "string",
                    "description": "Filter by engagement ID.",
                },
                "requester_staff_id": {
                    "type": "string",
                    "description": "Filter by requester staff ID.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (max 50).",
                },
            },
            "required": ["page"],
        },
    )
    def query_document_requests(
        self,
        page: int = 1,
        page_size: int = 50,
        engagement_id: str = None,
        requester_staff_id: str = None,
    ) -> dict:
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        offset = (page - 1) * page_size
        clauses, params = [], []
        if engagement_id:
            clauses.append("engagement_id = ?")
            params.append(engagement_id)
        if requester_staff_id:
            clauses.append("requester_staff_id = ?")
            params.append(requester_staff_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(f"SELECT COUNT(*) FROM document_requests{where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM document_requests{where} ORDER BY request_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "records": [dict(r) for r in rows],
        }

    @tool(
        description="Get detailed information for a single staff member by ID.",
        parameters={
            "type": "object",
            "properties": {
                "staff_id": {
                    "type": "string",
                    "description": "The staff member ID (e.g. S0001).",
                },
            },
            "required": ["staff_id"],
        },
    )
    def get_staff_details(self, staff_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM staff WHERE staff_id = ?", (staff_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Staff {staff_id} not found."}
        return dict(row)

    # ── Evaluation ──────────────────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute all flags using DB + workspace files (ground-truth)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load DB tables
        engagements = {r["engagement_id"]: dict(r) for r in conn.execute("SELECT * FROM engagements")}
        staff_map = {r["staff_id"]: dict(r) for r in conn.execute("SELECT * FROM staff")}
        assignments_rows = [dict(r) for r in conn.execute("SELECT * FROM assignments")]
        time_entries = [dict(r) for r in conn.execute("SELECT * FROM time_entries")]
        access_logs = [dict(r) for r in conn.execute("SELECT * FROM file_access_logs")]
        doc_requests = [dict(r) for r in conn.execute("SELECT * FROM document_requests")]
        conn.close()

        # Build assignment lookup: engagement_id -> set of staff_ids (active only)
        active_assignments = {}
        for a in assignments_rows:
            if a["is_active"] == 1:
                active_assignments.setdefault(a["engagement_id"], set()).add(a["staff_id"])

        # Load workspace scope files
        scope_map = {}  # engagement_id -> {budget_hours, authorized_scope_areas}
        for fn in sorted(os.listdir(self.workspace)):
            if fn.startswith("engagement_scope_batch_") and fn.endswith(".yaml"):
                with open(os.path.join(self.workspace, fn)) as f:
                    data = yaml.safe_load(f)
                if data:
                    for eid, info in data.items():
                        scope_map[eid] = info

        # Load certification requirements
        cert_req = {}  # engagement_type -> min_certification
        cert_path = os.path.join(self.workspace, "certification_requirements.csv")
        if os.path.exists(cert_path):
            import csv as _csv
            with open(cert_path) as f:
                for row in _csv.DictReader(f):
                    cert_req[row["engagement_type"]] = row["min_certification"]

        cert_rank = {"junior": 0, "senior": 1, "manager": 2, "partner": 3}

        # Load flagging policy
        policy_path = os.path.join(self.workspace, "flagging_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)
        overrun_medium = policy["flag_types"]["BUDGET_OVERRUN"]["severity_rules"]["overrun_pct_medium"]
        overrun_high = policy["flag_types"]["BUDGET_OVERRUN"]["severity_rules"]["overrun_pct_high"]

        flags = []

        # 1. UNAUTHORIZED_TIME
        for te in time_entries:
            eid = te["engagement_id"]
            sid = te["staff_id"]
            assigned = active_assignments.get(eid, set())
            if sid not in assigned:
                flags.append({
                    "flag_type": "UNAUTHORIZED_TIME",
                    "engagement_id": eid,
                    "staff_id": sid,
                    "staff_name": staff_map.get(sid, {}).get("name", "UNKNOWN"),
                    "detail": f"Time entry {te['entry_id']}: {te['hours']}h on {te['entry_date']}",
                    "severity": "HIGH",
                    "reference_date": te["entry_date"],
                    "sort_key": te["entry_id"],
                })

        # 2. BUDGET_OVERRUN
        # Aggregate hours per engagement
        hours_by_eng = {}
        for te in time_entries:
            hours_by_eng.setdefault(te["engagement_id"], 0.0)
            hours_by_eng[te["engagement_id"]] += te["hours"]
        for eid, total_h in hours_by_eng.items():
            info = scope_map.get(eid)
            if info is None:
                continue
            budget = info["budget_hours"]
            if budget <= 0:
                continue
            overrun_pct = ((total_h - budget) / budget) * 100
            if overrun_pct >= overrun_medium:
                sev = "HIGH" if overrun_pct >= overrun_high else "MEDIUM"
                flags.append({
                    "flag_type": "BUDGET_OVERRUN",
                    "engagement_id": eid,
                    "staff_id": "",
                    "staff_name": "",
                    "detail": f"Total hours {total_h:.1f} vs budget {budget:.1f} ({overrun_pct:.1f}% over)",
                    "severity": sev,
                    "reference_date": "",
                    "sort_key": eid,
                })

        # 3. UNAUTHORIZED_ACCESS
        for al in access_logs:
            eid = al["engagement_id"]
            sid = al["staff_id"]
            assigned = active_assignments.get(eid, set())
            if sid not in assigned:
                flags.append({
                    "flag_type": "UNAUTHORIZED_ACCESS",
                    "engagement_id": eid,
                    "staff_id": sid,
                    "staff_name": staff_map.get(sid, {}).get("name", "UNKNOWN"),
                    "detail": f"Access log {al['log_id']}: {al['access_type']} {al['file_name']} at {al['access_timestamp']}",
                    "severity": "HIGH",
                    "reference_date": al["access_timestamp"][:10],
                    "sort_key": al["log_id"],
                })

        # 4. OUT_OF_SCOPE_REQUEST
        for dr in doc_requests:
            eid = dr["engagement_id"]
            info = scope_map.get(eid)
            if info is None:
                continue
            authorized = info.get("authorized_scope_areas", [])
            if dr["scope_area"] not in authorized:
                sid = dr["requester_staff_id"]
                flags.append({
                    "flag_type": "OUT_OF_SCOPE_REQUEST",
                    "engagement_id": eid,
                    "staff_id": sid,
                    "staff_name": staff_map.get(sid, {}).get("name", "UNKNOWN"),
                    "detail": f"Request {dr['request_id']}: scope_area '{dr['scope_area']}' not in authorized {authorized}",
                    "severity": "MEDIUM",
                    "reference_date": dr["request_date"],
                    "sort_key": dr["request_id"],
                })

        # 5. CERTIFICATION_VIOLATION
        seen_cert_violations = set()
        for a in assignments_rows:
            if a["is_active"] != 1:
                continue
            eid = a["engagement_id"]
            sid = a["staff_id"]
            eng = engagements.get(eid)
            if eng is None:
                continue
            eng_type = eng["engagement_type"]
            min_cert = cert_req.get(eng_type)
            if min_cert is None:
                continue
            staff_cert = staff_map.get(sid, {}).get("certification_level", "junior")
            if cert_rank.get(staff_cert, 0) < cert_rank.get(min_cert, 0):
                key = (eid, sid)
                if key in seen_cert_violations:
                    continue
                seen_cert_violations.add(key)
                flags.append({
                    "flag_type": "CERTIFICATION_VIOLATION",
                    "engagement_id": eid,
                    "staff_id": sid,
                    "staff_name": staff_map.get(sid, {}).get("name", "UNKNOWN"),
                    "detail": f"Staff cert '{staff_cert}' below required '{min_cert}' for {eng_type}",
                    "severity": "HIGH",
                    "reference_date": a["start_date"],
                    "sort_key": f"{eid}_{sid}",
                })

        # Sort flags: by flag_type, then sort_key
        flags.sort(key=lambda f: (f["flag_type"], f["sort_key"]))

        # Assign flag_ids
        for i, flag in enumerate(flags, 1):
            flag["flag_id"] = i
            del flag["sort_key"]

        return flags

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
        criteria = {}

        # ── C1: flagged_activities.csv exists and has correct columns (15 pts) ──
        csv_path = os.path.join(self.workspace, "flagged_activities.csv")
        csv_ok = False
        agent_flags = []
        expected_cols = ["flag_id", "flag_type", "engagement_id", "staff_id",
                         "staff_name", "detail", "severity", "reference_date"]
        if os.path.exists(csv_path):
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    if all(c in cols for c in expected_cols):
                        csv_ok = True
                        for row in reader:
                            agent_flags.append(row)
            except Exception:
                pass
        criteria["csv_format"] = {
            "passed": csv_ok,
            "score": 15 if csv_ok else 0,
            "max_score": 15,
            "reason": "" if csv_ok else f"flagged_activities.csv missing or wrong columns; expected {expected_cols}",
        }

        # ── C2: Total flag count matches (10 pts) ──
        gt_count = len(ground_truth)
        agent_count = len(agent_flags)
        count_match = agent_count == gt_count
        criteria["flag_count"] = {
            "passed": count_match,
            "score": 10 if count_match else 0,
            "max_score": 10,
            "reason": "" if count_match else f"Expected {gt_count} flags, got {agent_count}",
        }

        # ── C3: Flag-type distribution matches (15 pts) ──
        gt_dist = {}
        for f in ground_truth:
            gt_dist[f["flag_type"]] = gt_dist.get(f["flag_type"], 0) + 1
        agent_dist = {}
        for f in agent_flags:
            agent_dist[f.get("flag_type", "")] = agent_dist.get(f.get("flag_type", ""), 0) + 1
        dist_match = gt_dist == agent_dist
        criteria["flag_type_distribution"] = {
            "passed": dist_match,
            "score": 15 if dist_match else 0,
            "max_score": 15,
            "reason": "" if dist_match else f"Expected distribution {gt_dist}, got {agent_dist}",
        }

        # ── C4: Per-flag accuracy — (engagement_id, staff_id, flag_type) tuples (25 pts) ──
        gt_set = set()
        for f in ground_truth:
            gt_set.add((f["flag_type"], f["engagement_id"], f["staff_id"]))
        agent_set = set()
        for f in agent_flags:
            agent_set.add((f.get("flag_type", ""), f.get("engagement_id", ""), f.get("staff_id", "")))
        if len(gt_set) > 0:
            overlap = len(gt_set & agent_set)
            accuracy = overlap / len(gt_set)
        else:
            accuracy = 1.0 if len(agent_set) == 0 else 0.0
        per_flag_score = round(accuracy * 25)
        criteria["per_flag_accuracy"] = {
            "passed": accuracy == 1.0,
            "score": per_flag_score,
            "max_score": 25,
            "reason": "" if accuracy == 1.0 else f"Matched {overlap}/{len(gt_set)} flag tuples",
        }

        # ── C5: Severity correctness (15 pts) ──
        # Build gt lookup by (flag_type, engagement_id, staff_id) -> severity
        gt_sev = {}
        for f in ground_truth:
            key = (f["flag_type"], f["engagement_id"], f["staff_id"])
            gt_sev[key] = f["severity"]
        sev_correct = 0
        sev_total = 0
        for f in agent_flags:
            key = (f.get("flag_type", ""), f.get("engagement_id", ""), f.get("staff_id", ""))
            if key in gt_sev:
                sev_total += 1
                if f.get("severity", "") == gt_sev[key]:
                    sev_correct += 1
        sev_accuracy = (sev_correct / sev_total) if sev_total > 0 else 0.0
        sev_score = round(sev_accuracy * 15)
        criteria["severity_accuracy"] = {
            "passed": sev_accuracy == 1.0,
            "score": sev_score,
            "max_score": 15,
            "reason": "" if sev_accuracy == 1.0 else f"Severity correct for {sev_correct}/{sev_total} matched flags",
        }

        # ── C6: summary.txt exists with required counts (20 pts) ──
        summary_path = os.path.join(self.workspace, "summary.txt")
        summary_ok = False
        summary_reason = "summary.txt not found"
        if os.path.exists(summary_path):
            with open(summary_path) as f:
                summary_text = f.read()
            # Check that summary mentions total count and per-type counts
            checks = []
            checks.append(str(gt_count) in summary_text)  # total count
            for ft, cnt in gt_dist.items():
                checks.append(str(cnt) in summary_text)
            # Count HIGH severity flags
            high_count = sum(1 for fl in ground_truth if fl["severity"] == "HIGH")
            medium_count = sum(1 for fl in ground_truth if fl["severity"] == "MEDIUM")
            checks.append(str(high_count) in summary_text)
            checks.append(str(medium_count) in summary_text)
            pass_rate = sum(checks) / len(checks) if checks else 0
            summary_ok = pass_rate == 1.0
            summary_score = round(pass_rate * 20)
            if not summary_ok:
                summary_reason = f"summary.txt missing some expected counts (pass rate {pass_rate:.0%})"
        else:
            summary_score = 0
        criteria["summary_file"] = {
            "passed": summary_ok,
            "score": summary_score,
            "max_score": 20,
            "reason": "" if summary_ok else summary_reason,
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
        reward = total_score / max_score if max_score > 0 else 0.0

        return reward, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as _csv

        tool_call_count = 0

        def _call(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # ── Step 1: Gather all engagements ──
        all_engagements = []
        page = 1
        while True:
            res = _call("list_engagements", page=page, page_size=25)
            all_engagements.extend(res["records"])
            if page >= res["total_pages"]:
                break
            page += 1

        # ── Step 2: Gather all staff (for name lookup) ──
        staff_map = {}
        page = 1
        while True:
            res = _call("list_staff", page=page, page_size=50)
            for s in res["records"]:
                staff_map[s["staff_id"]] = s
            if page >= res["total_pages"]:
                break
            page += 1

        # ── Step 3: Gather all assignments ──
        all_assignments = []
        page = 1
        while True:
            res = _call("query_assignments", page=page, page_size=50)
            all_assignments.extend(res["records"])
            if page >= res["total_pages"]:
                break
            page += 1

        # Build active assignment lookup
        active_assign = {}  # eid -> set(sid)
        for a in all_assignments:
            if a["is_active"] == 1:
                active_assign.setdefault(a["engagement_id"], set()).add(a["staff_id"])

        # ── Step 4: Gather all time entries ──
        all_time = []
        page = 1
        while True:
            res = _call("query_time_entries", page=page, page_size=50)
            all_time.extend(res["records"])
            if page >= res["total_pages"]:
                break
            page += 1

        # ── Step 5: Gather all file access logs ──
        all_access = []
        page = 1
        while True:
            res = _call("query_file_access_logs", page=page, page_size=50)
            all_access.extend(res["records"])
            if page >= res["total_pages"]:
                break
            page += 1

        # ── Step 6: Gather all document requests ──
        all_docreq = []
        page = 1
        while True:
            res = _call("query_document_requests", page=page, page_size=50)
            all_docreq.extend(res["records"])
            if page >= res["total_pages"]:
                break
            page += 1

        # ── Step 7: Read workspace files ──
        # Read scope files
        scope_map = {}
        for fn in sorted(os.listdir(self.workspace)):
            if fn.startswith("engagement_scope_batch_") and fn.endswith(".yaml"):
                with open(os.path.join(self.workspace, fn)) as f:
                    data = yaml.safe_load(f)
                if data:
                    for eid, info in data.items():
                        scope_map[eid] = info

        # Read certification requirements
        cert_req = {}
        cert_path = os.path.join(self.workspace, "certification_requirements.csv")
        with open(cert_path) as f:
            for row in _csv.DictReader(f):
                cert_req[row["engagement_type"]] = row["min_certification"]

        # Read flagging policy
        with open(os.path.join(self.workspace, "flagging_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        overrun_medium = policy["flag_types"]["BUDGET_OVERRUN"]["severity_rules"]["overrun_pct_medium"]
        overrun_high = policy["flag_types"]["BUDGET_OVERRUN"]["severity_rules"]["overrun_pct_high"]

        # Read task code mapping
        with open(os.path.join(self.workspace, "task_code_mapping.json")) as f:
            task_code_map = json.load(f)

        cert_rank = {"junior": 0, "senior": 1, "manager": 2, "partner": 3}

        # ── Step 8: Compute flags ──
        flags = []

        # Flag 1: UNAUTHORIZED_TIME
        for te in all_time:
            eid = te["engagement_id"]
            sid = te["staff_id"]
            assigned = active_assign.get(eid, set())
            if sid not in assigned:
                flags.append({
                    "flag_type": "UNAUTHORIZED_TIME",
                    "engagement_id": eid,
                    "staff_id": sid,
                    "staff_name": staff_map.get(sid, {}).get("name", "UNKNOWN"),
                    "detail": f"Time entry {te['entry_id']}: {te['hours']}h on {te['entry_date']}",
                    "severity": "HIGH",
                    "reference_date": te["entry_date"],
                    "sort_key": te["entry_id"],
                })

        # Flag 2: BUDGET_OVERRUN
        hours_by_eng = {}
        for te in all_time:
            hours_by_eng.setdefault(te["engagement_id"], 0.0)
            hours_by_eng[te["engagement_id"]] += te["hours"]
        for eid, total_h in hours_by_eng.items():
            info = scope_map.get(eid)
            if info is None:
                continue
            budget = info["budget_hours"]
            if budget <= 0:
                continue
            overrun_pct = ((total_h - budget) / budget) * 100
            if overrun_pct >= overrun_medium:
                sev = "HIGH" if overrun_pct >= overrun_high else "MEDIUM"
                flags.append({
                    "flag_type": "BUDGET_OVERRUN",
                    "engagement_id": eid,
                    "staff_id": "",
                    "staff_name": "",
                    "detail": f"Total hours {total_h:.1f} vs budget {budget:.1f} ({overrun_pct:.1f}% over)",
                    "severity": sev,
                    "reference_date": "",
                    "sort_key": eid,
                })

        # Flag 3: UNAUTHORIZED_ACCESS
        for al in all_access:
            eid = al["engagement_id"]
            sid = al["staff_id"]
            assigned = active_assign.get(eid, set())
            if sid not in assigned:
                flags.append({
                    "flag_type": "UNAUTHORIZED_ACCESS",
                    "engagement_id": eid,
                    "staff_id": sid,
                    "staff_name": staff_map.get(sid, {}).get("name", "UNKNOWN"),
                    "detail": f"Access log {al['log_id']}: {al['access_type']} {al['file_name']} at {al['access_timestamp']}",
                    "severity": "HIGH",
                    "reference_date": al["access_timestamp"][:10],
                    "sort_key": al["log_id"],
                })

        # Flag 4: OUT_OF_SCOPE_REQUEST
        for dr in all_docreq:
            eid = dr["engagement_id"]
            info = scope_map.get(eid)
            if info is None:
                continue
            authorized = info.get("authorized_scope_areas", [])
            if dr["scope_area"] not in authorized:
                sid = dr["requester_staff_id"]
                flags.append({
                    "flag_type": "OUT_OF_SCOPE_REQUEST",
                    "engagement_id": eid,
                    "staff_id": sid,
                    "staff_name": staff_map.get(sid, {}).get("name", "UNKNOWN"),
                    "detail": f"Request {dr['request_id']}: scope_area '{dr['scope_area']}' not in authorized {authorized}",
                    "severity": "MEDIUM",
                    "reference_date": dr["request_date"],
                    "sort_key": dr["request_id"],
                })

        # Flag 5: CERTIFICATION_VIOLATION
        seen_cert = set()
        eng_type_map = {e["engagement_id"]: e["engagement_type"] for e in all_engagements}
        for a in all_assignments:
            if a["is_active"] != 1:
                continue
            eid = a["engagement_id"]
            sid = a["staff_id"]
            eng_type = eng_type_map.get(eid, "")
            min_cert = cert_req.get(eng_type)
            if min_cert is None:
                continue
            staff_info = staff_map.get(sid, {})
            staff_cert = staff_info.get("certification_level", "junior")
            if cert_rank.get(staff_cert, 0) < cert_rank.get(min_cert, 0):
                key = (eid, sid)
                if key in seen_cert:
                    continue
                seen_cert.add(key)
                flags.append({
                    "flag_type": "CERTIFICATION_VIOLATION",
                    "engagement_id": eid,
                    "staff_id": sid,
                    "staff_name": staff_info.get("name", "UNKNOWN"),
                    "detail": f"Staff cert '{staff_cert}' below required '{min_cert}' for {eng_type}",
                    "severity": "HIGH",
                    "reference_date": a["start_date"],
                    "sort_key": f"{eid}_{sid}",
                })

        # Sort by flag_type, then sort_key
        flags.sort(key=lambda fl: (fl["flag_type"], fl["sort_key"]))
        for i, fl in enumerate(flags, 1):
            fl["flag_id"] = i
            del fl["sort_key"]

        # ── Step 9: Write deliverables ──
        # flagged_activities.csv
        csv_path = os.path.join(self.workspace, "flagged_activities.csv")
        fieldnames = ["flag_id", "flag_type", "engagement_id", "staff_id",
                       "staff_name", "detail", "severity", "reference_date"]
        with open(csv_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for fl in flags:
                writer.writerow({k: fl[k] for k in fieldnames})

        # summary.txt
        type_dist = {}
        sev_dist = {}
        for fl in flags:
            type_dist[fl["flag_type"]] = type_dist.get(fl["flag_type"], 0) + 1
            sev_dist[fl["severity"]] = sev_dist.get(fl["severity"], 0) + 1

        summary_lines = [
            f"Total flags: {len(flags)}",
            "",
            "Flags by type:",
        ]
        for ft in sorted(type_dist.keys()):
            summary_lines.append(f"  {ft}: {type_dist[ft]}")
        summary_lines.append("")
        summary_lines.append("Flags by severity:")
        for sev in ["HIGH", "MEDIUM", "LOW"]:
            if sev in sev_dist:
                summary_lines.append(f"  {sev}: {sev_dist[sev]}")
        summary_lines.append("")
        summary_lines.append("High-severity items requiring immediate partner attention:")
        for fl in flags:
            if fl["severity"] == "HIGH":
                summary_lines.append(
                    f"  Flag {fl['flag_id']}: [{fl['flag_type']}] Engagement {fl['engagement_id']}"
                    f" Staff {fl['staff_id']} {fl['staff_name']} - {fl['detail']}"
                )

        summary_text = "\n".join(summary_lines)
        with open(os.path.join(self.workspace, "summary.txt"), "w") as f:
            f.write(summary_text)

        # ── Step 10: Construct action string ──
        action = (
            f"Audit scope-creep analysis complete. "
            f"Total flagged activities: {len(flags)}. "
            f"Distribution by type: {', '.join(f'{k}={v}' for k, v in sorted(type_dist.items()))}. "
            f"Distribution by severity: {', '.join(f'{k}={v}' for k, v in sorted(sev_dist.items()))}. "
            f"Results saved to flagged_activities.csv and summary.txt."
        )

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need >= 15"

        return self.step(action)
