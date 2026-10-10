"""
Environment for data exfiltration forensic analysis task.
Provides tools for querying firewall logs, file access audits,
authentication events, and asset metadata; evaluates the agent's
containment report and affected-asset deliverables.
"""

import sqlite3
import os
import json
import csv
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


# ---------- helpers ----------
CLASSIFICATION_ORDER = {
    "PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2,
    "RESTRICTED": 3, "TOP_SECRET": 4,
}
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _is_off_hours(hour: int, start: int, end: int) -> bool:
    if start > end:
        return hour >= start or hour < end
    return start <= hour < end


def _parse_hour(ts: str) -> int:
    return int(ts.split(" ")[1].split(":")[0])


def _paginate(rows: list, page: int, page_size: int) -> dict:
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "results": rows[start:end],
        "page": page,
        "page_size": page_size,
        "total_results": total,
        "total_pages": total_pages,
    }


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

    # ================================================================
    # TOOL METHODS
    # ================================================================

    @tool(
        description="Query firewall egress log entries with optional filters. Returns paginated results. All filter parameters are optional; omit a parameter to skip that filter.",
        parameters={
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "Filter by user ID (exact match).",
                },
                "dst_ip": {
                    "type": "string",
                    "description": "Filter by destination IP address (exact match).",
                },
                "min_bytes": {
                    "type": "integer",
                    "description": "Only return entries where bytes_transferred > this value.",
                },
                "action": {
                    "type": "string",
                    "enum": ["ALLOW", "DENY"],
                    "description": "Filter by firewall action.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed, default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 20, max 50).",
                },
            },
            "required": [],
        },
    )
    def query_firewall_logs(self, user_id=None, dst_ip=None, min_bytes=None,
                            action=None, page=1, page_size=20):
        page_size = max(1, min(int(page_size) if page_size else 20, 50))
        page = max(1, int(page) if page else 1)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM firewall_logs WHERE 1=1"
        params: list = []
        if user_id:
            sql += " AND user_id = ?"
            params.append(user_id)
        if dst_ip:
            sql += " AND dst_ip = ?"
            params.append(dst_ip)
        if min_bytes is not None:
            sql += " AND bytes_transferred > ?"
            params.append(int(min_bytes))
        if action:
            sql += " AND action = ?"
            params.append(action)
        sql += " ORDER BY timestamp"
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        conn.close()
        return _paginate(rows, page, page_size)

    @tool(
        description="Query file access audit log entries with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "Filter by user ID.",
                },
                "file_id": {
                    "type": "string",
                    "description": "Filter by file ID.",
                },
                "action": {
                    "type": "string",
                    "enum": ["READ", "WRITE", "COPY", "DOWNLOAD", "DELETE"],
                    "description": "Filter by access action type.",
                },
                "endpoint_id": {
                    "type": "string",
                    "description": "Filter by endpoint ID.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed, default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 20, max 50).",
                },
            },
            "required": [],
        },
    )
    def query_file_access(self, user_id=None, file_id=None, action=None,
                          endpoint_id=None, page=1, page_size=20):
        page_size = max(1, min(int(page_size) if page_size else 20, 50))
        page = max(1, int(page) if page else 1)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM file_access_logs WHERE 1=1"
        params: list = []
        if user_id:
            sql += " AND user_id = ?"
            params.append(user_id)
        if file_id:
            sql += " AND file_id = ?"
            params.append(file_id)
        if action:
            sql += " AND action = ?"
            params.append(action)
        if endpoint_id:
            sql += " AND endpoint_id = ?"
            params.append(endpoint_id)
        sql += " ORDER BY timestamp"
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        conn.close()
        return _paginate(rows, page, page_size)

    @tool(
        description="Query authentication event records with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "Filter by user ID.",
                },
                "status": {
                    "type": "string",
                    "enum": ["SUCCESS", "FAILURE"],
                    "description": "Filter by authentication outcome.",
                },
                "auth_type": {
                    "type": "string",
                    "enum": ["PASSWORD", "MFA", "SSO", "CERTIFICATE"],
                    "description": "Filter by authentication method.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed, default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 20, max 50).",
                },
            },
            "required": [],
        },
    )
    def query_auth_events(self, user_id=None, status=None, auth_type=None,
                          page=1, page_size=20):
        page_size = max(1, min(int(page_size) if page_size else 20, 50))
        page = max(1, int(page) if page else 1)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM auth_events WHERE 1=1"
        params: list = []
        if user_id:
            sql += " AND user_id = ?"
            params.append(user_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        if auth_type:
            sql += " AND auth_type = ?"
            params.append(auth_type)
        sql += " ORDER BY timestamp"
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        conn.close()
        return _paginate(rows, page, page_size)

    @tool(
        description="Retrieve metadata for a single file by its file ID.",
        parameters={
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "The file ID to look up (e.g. FILE-0001).",
                },
            },
            "required": ["file_id"],
        },
    )
    def get_file_info(self, file_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM files WHERE file_id = ?", (file_id,)).fetchone()
        conn.close()
        if row is None:
            return {"error": f"File {file_id} not found."}
        return dict(row)

    @tool(
        description="Retrieve detailed information for a single user by their user ID.",
        parameters={
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "The user ID to look up (e.g. USR-0001).",
                },
            },
            "required": ["user_id"],
        },
    )
    def get_user_info(self, user_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        conn.close()
        if row is None:
            return {"error": f"User {user_id} not found."}
        return dict(row)

    @tool(
        description="Retrieve detailed information for a single endpoint by its endpoint ID.",
        parameters={
            "type": "object",
            "properties": {
                "endpoint_id": {
                    "type": "string",
                    "description": "The endpoint ID to look up (e.g. EP-0001).",
                },
            },
            "required": ["endpoint_id"],
        },
    )
    def get_endpoint_info(self, endpoint_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM endpoints WHERE endpoint_id = ?", (endpoint_id,)).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Endpoint {endpoint_id} not found."}
        return dict(row)

    # ================================================================
    # GROUND TRUTH COMPUTATION (used by both step and verify)
    # ================================================================

    def _compute_ground_truth(self):
        """Compute the expected answer from DB + workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # --- read workspace config ---
        with open(os.path.join(self.workspace, "incident_response_policy.yaml")) as f:
            policy = yaml.safe_load(f)["incident_response"]

        with open(os.path.join(self.workspace, "clearance_matrix.json")) as f:
            clearance_matrix = json.load(f)

        dept_risk: Dict[str, int] = {}
        with open(os.path.join(self.workspace, "department_risk_scores.csv")) as f:
            for row in csv.DictReader(f):
                dept_risk[row["department"]] = int(row["risk_score"])

        safe_ips: set = set()
        with open(os.path.join(self.workspace, "known_safe_destinations.txt")) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    safe_ips.add(line)

        # --- collect malicious IPs from threat intel ---
        malicious_ips: set = set()
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("threat_intel_feed_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    report = json.load(f)
                for ind in report["indicators"]:
                    if (ind["type"] == "ipv4"
                            and ind["status"] == "active"
                            and ind["confidence"] in ("high", "medium")
                            and ind["threat_category"] in ("C2", "exfiltration")):
                        malicious_ips.add(ind["value"])
        malicious_ips -= safe_ips

        # --- policy thresholds ---
        off_start = policy["off_hours"]["start"]
        off_end = policy["off_hours"]["end"]
        bytes_thresh = policy["bytes_threshold"]
        max_failed = policy["max_failed_auth_before_flag"]
        suspicious_actions = set(policy["suspicious_actions"])

        severity_map: Dict[str, str] = {}
        for sev_name, sev_info in policy["severity_levels"].items():
            severity_map[sev_info["min_classification"]] = sev_name

        # --- find candidate users from firewall logs ---
        candidate_users: set = set()
        for row in conn.execute("SELECT * FROM firewall_logs").fetchall():
            hour = _parse_hour(row["timestamp"])
            if (row["dst_ip"] in malicious_ips
                    and row["bytes_transferred"] > bytes_thresh
                    and _is_off_hours(hour, off_start, off_end)):
                candidate_users.add(row["user_id"])

        # --- filter by auth failure threshold ---
        compromised_users: set = set()
        for uid in candidate_users:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM auth_events WHERE user_id=? AND status='FAILURE'",
                (uid,),
            ).fetchone()[0]
            if cnt >= max_failed:
                compromised_users.add(uid)

        # --- user info map ---
        user_map: Dict[str, dict] = {}
        for uid in compromised_users:
            r = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
            user_map[uid] = dict(r)

        # --- find exfiltrated file accesses ---
        expected_rows: list = []
        unique_files: set = set()
        unique_endpoints: set = set()

        for uid in compromised_users:
            for acc in conn.execute("SELECT * FROM file_access_logs WHERE user_id=?", (uid,)).fetchall():
                hour = _parse_hour(acc["timestamp"])
                if acc["action"] not in suspicious_actions:
                    continue
                if not _is_off_hours(hour, off_start, off_end):
                    continue

                finfo = dict(conn.execute("SELECT * FROM files WHERE file_id=?", (acc["file_id"],)).fetchone())
                classification = finfo["classification"]
                if classification not in severity_map:
                    continue  # PUBLIC excluded

                severity = severity_map[classification]
                uinfo = user_map[uid]
                max_clear = clearance_matrix.get(uinfo["role"], "PUBLIC")
                unauthorized = CLASSIFICATION_ORDER[classification] > CLASSIFICATION_ORDER[max_clear]

                expected_rows.append({
                    "user_id": uid,
                    "username": uinfo["username"],
                    "department": uinfo["department"],
                    "role": uinfo["role"],
                    "clearance_level": uinfo["clearance_level"],
                    "file_id": acc["file_id"],
                    "filename": finfo["filename"],
                    "classification": classification,
                    "access_action": acc["action"],
                    "access_timestamp": acc["timestamp"],
                    "endpoint_id": acc["endpoint_id"],
                    "severity": severity,
                    "unauthorized": "TRUE" if unauthorized else "FALSE",
                })
                unique_files.add(acc["file_id"])
                unique_endpoints.add(acc["endpoint_id"])

        conn.close()

        # --- sort ---
        expected_rows.sort(key=lambda r: (
            SEVERITY_ORDER[r["severity"]],
            -dept_risk.get(r["department"], 0),
            r["user_id"],
            r["file_id"],
            r["access_timestamp"],
        ))

        severity_breakdown = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for r in expected_rows:
            severity_breakdown[r["severity"]] += 1

        return {
            "expected_rows": expected_rows,
            "compromised_users": sorted(compromised_users),
            "exfiltrated_files": sorted(unique_files),
            "affected_endpoints": sorted(unique_endpoints),
            "severity_breakdown": severity_breakdown,
            "dept_risk": dept_risk,
        }

    # ================================================================
    # STEP — evaluate agent deliverables
    # ================================================================

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
        gt = self._compute_ground_truth()
        expected_rows = gt["expected_rows"]
        expected_compromised = gt["compromised_users"]
        expected_files = gt["exfiltrated_files"]
        expected_endpoints = gt["affected_endpoints"]
        sev_breakdown = gt["severity_breakdown"]
        dept_risk = gt["dept_risk"]

        eval_criteria: Dict[str, dict] = {}

        # ---- 1. containment_report.csv format (10 pts) ----
        csv_path = os.path.join(self.workspace, "containment_report.csv")
        EXPECTED_HEADERS = [
            "user_id", "username", "department", "role", "clearance_level",
            "file_id", "filename", "classification", "access_action",
            "access_timestamp", "endpoint_id", "severity", "unauthorized",
        ]
        actual_rows: list = []
        headers_ok = False
        try:
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is not None and list(reader.fieldnames) == EXPECTED_HEADERS:
                    headers_ok = True
                actual_rows = list(reader)
        except Exception:
            pass

        eval_criteria["report_format"] = {
            "passed": headers_ok,
            "score": 10 if headers_ok else 0,
            "max_score": 10,
            "reason": "" if headers_ok else "containment_report.csv missing or has incorrect column headers",
        }

        # ---- 2. containment_report.csv rows (15 pts) ----
        def _row_key(r):
            return (r.get("user_id", ""), r.get("file_id", ""), r.get("access_timestamp", ""))

        expected_keys = sorted(_row_key(r) for r in expected_rows)
        actual_keys = sorted(_row_key(r) for r in actual_rows)
        rows_match = expected_keys == actual_keys

        eval_criteria["report_rows"] = {
            "passed": rows_match,
            "score": 15 if rows_match else 0,
            "max_score": 15,
            "reason": "" if rows_match else f"Row mismatch: expected {len(expected_rows)} rows, got {len(actual_rows)}",
        }

        # ---- 3. containment_report.csv sort order (10 pts) ----
        sort_ok = False
        if rows_match and len(actual_rows) > 0:
            actual_sort_keys = [
                (
                    SEVERITY_ORDER.get(r.get("severity", ""), 99),
                    -dept_risk.get(r.get("department", ""), 0),
                    r.get("user_id", ""),
                    r.get("file_id", ""),
                    r.get("access_timestamp", ""),
                )
                for r in actual_rows
            ]
            sort_ok = actual_sort_keys == sorted(actual_sort_keys)

        eval_criteria["report_sort"] = {
            "passed": sort_ok,
            "score": 10 if sort_ok else 0,
            "max_score": 10,
            "reason": "" if sort_ok else "Containment report rows not sorted correctly",
        }

        # ---- 4-6. affected_assets.json checks ----
        assets_path = os.path.join(self.workspace, "affected_assets.json")
        actual_assets: dict = {}
        try:
            with open(assets_path) as f:
                actual_assets = json.load(f)
        except Exception:
            pass

        users_ok = actual_assets.get("compromised_users") == expected_compromised
        eval_criteria["assets_users"] = {
            "passed": users_ok,
            "score": 15 if users_ok else 0,
            "max_score": 15,
            "reason": "" if users_ok else "compromised_users list in affected_assets.json does not match expected",
        }

        files_ok = actual_assets.get("exfiltrated_files") == expected_files
        eval_criteria["assets_files"] = {
            "passed": files_ok,
            "score": 10 if files_ok else 0,
            "max_score": 10,
            "reason": "" if files_ok else "exfiltrated_files list in affected_assets.json does not match expected",
        }

        endpoints_ok = actual_assets.get("affected_endpoints") == expected_endpoints
        eval_criteria["assets_endpoints"] = {
            "passed": endpoints_ok,
            "score": 10 if endpoints_ok else 0,
            "max_score": 10,
            "reason": "" if endpoints_ok else "affected_endpoints list in affected_assets.json does not match expected",
        }

        # ---- 7. response COMPROMISED_USERS (10 pts) ----
        expected_users_str = ", ".join(expected_compromised)
        resp_users_ok = f"COMPROMISED_USERS: {expected_users_str}" in action
        eval_criteria["response_users"] = {
            "passed": resp_users_ok,
            "score": 10 if resp_users_ok else 0,
            "max_score": 10,
            "reason": "" if resp_users_ok else "COMPROMISED_USERS line missing or incorrect in response",
        }

        # ---- 8. response TOTAL_EXFILTRATED_FILES (10 pts) ----
        expected_total = len(expected_files)
        resp_total_ok = f"TOTAL_EXFILTRATED_FILES: {expected_total}" in action
        eval_criteria["response_total_files"] = {
            "passed": resp_total_ok,
            "score": 10 if resp_total_ok else 0,
            "max_score": 10,
            "reason": "" if resp_total_ok else "TOTAL_EXFILTRATED_FILES line missing or incorrect in response",
        }

        # ---- 9. response SEVERITY_BREAKDOWN (10 pts) ----
        expected_sev_str = (
            f"CRITICAL:{sev_breakdown['CRITICAL']}, "
            f"HIGH:{sev_breakdown['HIGH']}, "
            f"MEDIUM:{sev_breakdown['MEDIUM']}, "
            f"LOW:{sev_breakdown['LOW']}"
        )
        resp_sev_ok = f"SEVERITY_BREAKDOWN: {expected_sev_str}" in action
        eval_criteria["response_severity"] = {
            "passed": resp_sev_ok,
            "score": 10 if resp_sev_ok else 0,
            "max_score": 10,
            "reason": "" if resp_sev_ok else "SEVERITY_BREAKDOWN line missing or incorrect in response",
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

        return total_score / max_score, info

    # ================================================================
    # VERIFY — solve the task end-to-end using only tools + workspace
    # ================================================================

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
        tool_call_count = 0

        def _call(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # ----------------------------------------------------------
        # 1. Read workspace configuration files
        # ----------------------------------------------------------
        with open(os.path.join(self.workspace, "incident_response_policy.yaml")) as f:
            policy = yaml.safe_load(f)["incident_response"]

        with open(os.path.join(self.workspace, "clearance_matrix.json")) as f:
            clearance_matrix = json.load(f)

        dept_risk: Dict[str, int] = {}
        with open(os.path.join(self.workspace, "department_risk_scores.csv")) as f:
            for row in csv.DictReader(f):
                dept_risk[row["department"]] = int(row["risk_score"])

        safe_ips: set = set()
        with open(os.path.join(self.workspace, "known_safe_destinations.txt")) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    safe_ips.add(line)

        # Read data classification guide (informational)
        with open(os.path.join(self.workspace, "data_classification_guide.md")) as f:
            _ = f.read()

        # ----------------------------------------------------------
        # 2. Collect malicious IPs from ALL threat intel feeds
        # ----------------------------------------------------------
        malicious_ips: set = set()
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("threat_intel_feed_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    report = json.load(f)
                for ind in report["indicators"]:
                    if (ind["type"] == "ipv4"
                            and ind["status"] == "active"
                            and ind["confidence"] in ("high", "medium")
                            and ind["threat_category"] in ("C2", "exfiltration")):
                        malicious_ips.add(ind["value"])

        # Remove safe destinations
        malicious_ips -= safe_ips

        # ----------------------------------------------------------
        # 3. Extract policy thresholds
        # ----------------------------------------------------------
        off_start = policy["off_hours"]["start"]
        off_end = policy["off_hours"]["end"]
        bytes_thresh = policy["bytes_threshold"]
        max_failed = policy["max_failed_auth_before_flag"]
        suspicious_actions = set(policy["suspicious_actions"])

        severity_map: Dict[str, str] = {}
        for sev_name, sev_info in policy["severity_levels"].items():
            severity_map[sev_info["min_classification"]] = sev_name

        # ----------------------------------------------------------
        # 4. Query firewall logs to find candidate compromised users
        # ----------------------------------------------------------
        candidate_user_ids: set = set()
        page = 1
        while True:
            result = _call("query_firewall_logs", min_bytes=bytes_thresh, page=page, page_size=50)
            for entry in result["results"]:
                dst_ip = entry["dst_ip"]
                hour = _parse_hour(entry["timestamp"])
                if dst_ip in malicious_ips and _is_off_hours(hour, off_start, off_end):
                    candidate_user_ids.add(entry["user_id"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ----------------------------------------------------------
        # 5. Verify auth failure threshold for each candidate
        # ----------------------------------------------------------
        compromised_user_ids: set = set()
        for uid in sorted(candidate_user_ids):
            result = _call("query_auth_events", user_id=uid, status="FAILURE", page=1, page_size=50)
            total_failures = result["total_results"]
            if total_failures >= max_failed:
                compromised_user_ids.add(uid)

        # ----------------------------------------------------------
        # 6. Get user details for compromised users
        # ----------------------------------------------------------
        user_info: Dict[str, dict] = {}
        for uid in sorted(compromised_user_ids):
            user_info[uid] = _call("get_user_info", user_id=uid)

        # ----------------------------------------------------------
        # 7. Find exfiltrated files via file access logs
        # ----------------------------------------------------------
        exfil_records: list = []
        for uid in sorted(compromised_user_ids):
            page = 1
            while True:
                result = _call("query_file_access", user_id=uid, page=page, page_size=50)
                for entry in result["results"]:
                    hour = _parse_hour(entry["timestamp"])
                    if (entry["action"] in suspicious_actions
                            and _is_off_hours(hour, off_start, off_end)):
                        exfil_records.append(entry)
                if page >= result["total_pages"]:
                    break
                page += 1

        # ----------------------------------------------------------
        # 8. Get file metadata for each unique file
        # ----------------------------------------------------------
        file_info: Dict[str, dict] = {}
        for rec in exfil_records:
            fid = rec["file_id"]
            if fid not in file_info:
                file_info[fid] = _call("get_file_info", file_id=fid)

        # ----------------------------------------------------------
        # 9. Get endpoint details for each unique endpoint
        # ----------------------------------------------------------
        endpoint_info: Dict[str, dict] = {}
        for rec in exfil_records:
            eid = rec["endpoint_id"]
            if eid not in endpoint_info:
                endpoint_info[eid] = _call("get_endpoint_info", endpoint_id=eid)

        # ----------------------------------------------------------
        # 10. Build containment report rows
        # ----------------------------------------------------------
        report_rows: list = []
        for rec in exfil_records:
            uid = rec["user_id"]
            fid = rec["file_id"]
            uinfo = user_info[uid]
            finfo = file_info[fid]

            classification = finfo["classification"]
            if classification not in severity_map:
                continue  # PUBLIC excluded

            severity = severity_map[classification]
            max_clear = clearance_matrix.get(uinfo["role"], "PUBLIC")
            unauthorized = CLASSIFICATION_ORDER[classification] > CLASSIFICATION_ORDER[max_clear]

            report_rows.append({
                "user_id": uid,
                "username": uinfo["username"],
                "department": uinfo["department"],
                "role": uinfo["role"],
                "clearance_level": uinfo["clearance_level"],
                "file_id": fid,
                "filename": finfo["filename"],
                "classification": classification,
                "access_action": rec["action"],
                "access_timestamp": rec["timestamp"],
                "endpoint_id": rec["endpoint_id"],
                "severity": severity,
                "unauthorized": "TRUE" if unauthorized else "FALSE",
            })

        # Sort by severity, dept risk desc, user_id, file_id, timestamp
        report_rows.sort(key=lambda r: (
            SEVERITY_ORDER[r["severity"]],
            -dept_risk.get(r["department"], 0),
            r["user_id"],
            r["file_id"],
            r["access_timestamp"],
        ))

        # ----------------------------------------------------------
        # 11. Write containment_report.csv
        # ----------------------------------------------------------
        csv_path = os.path.join(self.workspace, "containment_report.csv")
        fieldnames = [
            "user_id", "username", "department", "role", "clearance_level",
            "file_id", "filename", "classification", "access_action",
            "access_timestamp", "endpoint_id", "severity", "unauthorized",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in report_rows:
                writer.writerow(row)

        # ----------------------------------------------------------
        # 12. Build affected_assets.json
        # ----------------------------------------------------------
        severity_breakdown = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for row in report_rows:
            severity_breakdown[row["severity"]] += 1

        unique_files = sorted(set(r["file_id"] for r in report_rows))
        unique_endpoints = sorted(set(r["endpoint_id"] for r in report_rows))

        affected_assets = {
            "compromised_users": sorted(compromised_user_ids),
            "exfiltrated_files": unique_files,
            "affected_endpoints": unique_endpoints,
            "severity_breakdown": severity_breakdown,
        }

        with open(os.path.join(self.workspace, "affected_assets.json"), "w") as f:
            json.dump(affected_assets, f, indent=2)

        # ----------------------------------------------------------
        # 13. Build action string
        # ----------------------------------------------------------
        users_str = ", ".join(sorted(compromised_user_ids))
        total_files = len(unique_files)
        sev_str = (
            f"CRITICAL:{severity_breakdown['CRITICAL']}, "
            f"HIGH:{severity_breakdown['HIGH']}, "
            f"MEDIUM:{severity_breakdown['MEDIUM']}, "
            f"LOW:{severity_breakdown['LOW']}"
        )

        action = (
            f"COMPROMISED_USERS: {users_str}\n"
            f"TOTAL_EXFILTRATED_FILES: {total_files}\n"
            f"SEVERITY_BREAKDOWN: {sev_str}"
        )

        assert tool_call_count >= 15, (
            f"verify used only {tool_call_count} tool calls; minimum is 15"
        )

        return self.step(action)
