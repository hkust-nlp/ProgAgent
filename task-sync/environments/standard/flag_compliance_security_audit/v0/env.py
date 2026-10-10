import sqlite3
import json
import csv
import os
from datetime import datetime
from typing import Tuple, Dict, List, Any


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

    # ═══════════════════════════════════════════
    # Tool methods
    # ═══════════════════════════════════════════

    @tool(
        description="List feature flags with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "environment": {
                    "type": "string",
                    "description": "Filter by environment (dev, staging, production, production-critical)",
                },
                "service": {
                    "type": "string",
                    "description": "Filter by service name",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status (active, inactive, archived)",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 50). Default 20.",
                },
            },
            "required": [],
        },
    )
    def list_feature_flags(
        self,
        environment: str = None,
        service: str = None,
        status: str = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT flag_id, flag_name, service, environment, status, owner_id FROM feature_flags WHERE 1=1"
        params = []
        if environment:
            query += " AND environment = ?"
            params.append(environment)
        if service:
            query += " AND service = ?"
            params.append(service)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY flag_id"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = rows[start:end]
        return {
            "flags": [dict(r) for r in page_rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": end < total,
        }

    @tool(
        description="Get detailed information about a specific feature flag by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "flag_id": {
                    "type": "string",
                    "description": "The unique flag identifier (e.g. FLAG0001)",
                },
            },
            "required": ["flag_id"],
        },
    )
    def get_flag_details(self, flag_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM feature_flags WHERE flag_id = ?", (flag_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Flag {flag_id} not found"}
        return dict(row)

    @tool(
        description="Get employee information including their Active Directory group memberships.",
        parameters={
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "The employee identifier (e.g. EMP0001)",
                },
            },
            "required": ["employee_id"],
        },
    )
    def get_employee_info(self, employee_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        emp = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ?", (employee_id,)
        ).fetchone()
        if emp is None:
            conn.close()
            return {"error": f"Employee {employee_id} not found"}
        groups = conn.execute(
            "SELECT group_name FROM employee_ad_groups WHERE employee_id = ?",
            (employee_id,),
        ).fetchall()
        conn.close()
        result = dict(emp)
        result["ad_groups"] = sorted([g["group_name"] for g in groups])
        return result

    @tool(
        description="Search change management tickets with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "flag_id": {
                    "type": "string",
                    "description": "Filter by feature flag ID",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by ticket status (approved, rejected, pending)",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 50). Default 20.",
                },
            },
            "required": [],
        },
    )
    def search_change_tickets(
        self,
        flag_id: str = None,
        status: str = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM change_tickets WHERE 1=1"
        params = []
        if flag_id:
            query += " AND flag_id = ?"
            params.append(flag_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY ticket_id"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "tickets": [dict(r) for r in rows[start:end]],
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": end < total,
        }

    @tool(
        description="Retrieve audit log entries with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "flag_id": {
                    "type": "string",
                    "description": "Filter by feature flag ID",
                },
                "actor_id": {
                    "type": "string",
                    "description": "Filter by actor employee ID",
                },
                "action": {
                    "type": "string",
                    "description": "Filter by action type (created, modified, toggled, deleted, rollback)",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 50). Default 20.",
                },
            },
            "required": [],
        },
    )
    def get_audit_logs(
        self,
        flag_id: str = None,
        actor_id: str = None,
        action: str = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM audit_logs WHERE 1=1"
        params = []
        if flag_id:
            query += " AND flag_id = ?"
            params.append(flag_id)
        if actor_id:
            query += " AND actor_id = ?"
            params.append(actor_id)
        if action:
            query += " AND action = ?"
            params.append(action)
        query += " ORDER BY log_id"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "logs": [dict(r) for r in rows[start:end]],
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": end < total,
        }

    @tool(
        description="Get all employee IDs that belong to a given Active Directory group.",
        parameters={
            "type": "object",
            "properties": {
                "group_name": {
                    "type": "string",
                    "description": "The AD group name (e.g. Security, Engineering, PlatformAdmin)",
                },
            },
            "required": ["group_name"],
        },
    )
    def get_ad_group_members(self, group_name: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT employee_id FROM employee_ad_groups WHERE group_name = ? ORDER BY employee_id",
            (group_name,),
        ).fetchall()
        conn.close()
        return {
            "group_name": group_name,
            "member_ids": [r["employee_id"] for r in rows],
            "count": len(rows),
        }

    # ═══════════════════════════════════════════
    # Ground-truth computation (used by step)
    # ═══════════════════════════════════════════

    def _compute_ground_truth(self):
        """Compute all violations using direct DB access + workspace files."""
        import yaml

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load workspace config
        with open(os.path.join(self.workspace, "compliance_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        sensitive = set()
        with open(os.path.join(self.workspace, "sensitive_services.csv")) as f:
            for row in csv.DictReader(f):
                sensitive.add(row["service_name"])

        # Read remediation procedures
        remediation_map = {}
        with open(os.path.join(self.workspace, "remediation_procedures.md")) as f:
            current_type = None
            for line in f:
                line = line.strip()
                if line.startswith("## "):
                    current_type = line[3:].strip()
                elif current_type and line and not line.startswith("#"):
                    remediation_map[current_type] = line
                    current_type = None

        # Load targeting rules from workspace
        targeting = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("targeting_rules_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for rule in json.load(f):
                        targeting[rule["flag_id"]] = rule

        # DB data
        flags = {}
        for row in conn.execute("SELECT * FROM feature_flags"):
            flags[row["flag_id"]] = dict(row)

        employees = {}
        for row in conn.execute("SELECT * FROM employees"):
            employees[row["employee_id"]] = dict(row)

        emp_groups = {}
        for row in conn.execute("SELECT * FROM employee_ad_groups"):
            emp_groups.setdefault(row["employee_id"], set()).add(row["group_name"])

        approved_tickets_by_flag = {}
        for row in conn.execute("SELECT * FROM change_tickets WHERE status='approved'"):
            r = dict(row)
            approved_tickets_by_flag.setdefault(r["flag_id"], []).append(r)

        audit_by_flag = {}
        for row in conn.execute("SELECT * FROM audit_logs"):
            r = dict(row)
            audit_by_flag.setdefault(r["flag_id"], []).append(r)

        conn.close()

        # Policy parameters
        env_clearance = policy["environment_clearance_requirements"]
        ticketed_envs = set(policy["change_management"]["ticket_required_environments"])
        severity_map = policy["severity_mapping"]
        exempt_groups = set(policy["targeting_policy"]["exempt_groups"])

        mw = policy["maintenance_windows"]
        wd_start = int(mw["weekday"]["start"].split(":")[0])
        wd_end = int(mw["weekday"]["end"].split(":")[0])
        we_start = int(mw["weekend"]["start"].split(":")[0])
        we_end = int(mw["weekend"]["end"].split(":")[0])

        violations = []

        for fid, flag in sorted(flags.items()):
            owner_id = flag["owner_id"]
            owner = employees.get(owner_id, {})
            owner_grps = emp_groups.get(owner_id, set())
            env = flag["environment"]
            service = flag["service"]
            severity = severity_map.get(env, "low")

            base = {
                "flag_id": fid,
                "flag_name": flag["flag_name"],
                "service": service,
                "environment": env,
                "owner_name": owner.get("name", "Unknown"),
                "owner_id": owner_id,
                "severity": severity,
            }

            # 1. CLEARANCE_VIOLATION
            required = env_clearance.get(env, 1)
            if owner.get("clearance_level", 0) < required:
                violations.append({
                    **base,
                    "violation_type": "CLEARANCE_VIOLATION",
                    "remediation_action": remediation_map.get("CLEARANCE_VIOLATION", ""),
                })

            # 2. TARGETING_VIOLATION
            if fid in targeting:
                tgt = set(targeting[fid]["target_groups"])
                if not (owner_grps & tgt) and not (owner_grps & exempt_groups):
                    violations.append({
                        **base,
                        "violation_type": "TARGETING_VIOLATION",
                        "remediation_action": remediation_map.get("TARGETING_VIOLATION", ""),
                    })

            # 3. MISSING_TICKET
            if env in ticketed_envs:
                has_mod = any(
                    log["action"] in ("modified", "toggled")
                    for log in audit_by_flag.get(fid, [])
                )
                has_approved = fid in approved_tickets_by_flag
                if has_mod and not has_approved:
                    violations.append({
                        **base,
                        "violation_type": "MISSING_TICKET",
                        "remediation_action": remediation_map.get("MISSING_TICKET", ""),
                    })

            # 4. OUT_OF_WINDOW_CHANGE
            if env in ("production", "production-critical"):
                for log in audit_by_flag.get(fid, []):
                    if log["action"] in ("modified", "toggled"):
                        ts = datetime.strptime(log["timestamp"], "%Y-%m-%d %H:%M:%S")
                        dow = ts.weekday()
                        h = ts.hour
                        if dow < 5:
                            in_window = wd_start <= h < wd_end
                        else:
                            in_window = we_start <= h < we_end
                        if not in_window:
                            violations.append({
                                **base,
                                "violation_type": "OUT_OF_WINDOW_CHANGE",
                                "remediation_action": remediation_map.get("OUT_OF_WINDOW_CHANGE", ""),
                            })
                            break  # one per flag

            # 5. SENSITIVE_NO_SECURITY_APPROVAL
            if service in sensitive and fid in approved_tickets_by_flag:
                has_sec = False
                for ticket in approved_tickets_by_flag[fid]:
                    approver_grps = emp_groups.get(ticket["approver_id"], set())
                    if "Security" in approver_grps:
                        has_sec = True
                        break
                if not has_sec:
                    violations.append({
                        **base,
                        "violation_type": "SENSITIVE_NO_SECURITY_APPROVAL",
                        "remediation_action": remediation_map.get("SENSITIVE_NO_SECURITY_APPROVAL", ""),
                    })

        # Sort: severity (critical > high > medium > low), then flag_id asc
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        violations.sort(key=lambda v: (sev_order.get(v["severity"], 99), v["flag_id"]))
        return violations

    # ═══════════════════════════════════════════
    # Evaluation
    # ═══════════════════════════════════════════

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        expected = self._compute_ground_truth()

        # Build expected sets per violation type
        expected_by_type = {}
        for v in expected:
            expected_by_type.setdefault(v["violation_type"], set()).add(v["flag_id"])

        # ── Read agent's remediation_roster.csv ──
        roster_path = os.path.join(self.workspace, "remediation_roster.csv")
        actual_rows = []
        actual_by_type = {}
        file_ok = False
        columns_ok = False
        required_cols = {
            "flag_id", "flag_name", "service", "environment",
            "owner_name", "owner_id", "violation_type", "severity",
            "remediation_action",
        }

        if os.path.exists(roster_path):
            try:
                with open(roster_path, newline="") as f:
                    reader = csv.DictReader(f)
                    if reader.fieldnames and required_cols.issubset(set(reader.fieldnames)):
                        columns_ok = True
                    for row in reader:
                        actual_rows.append(row)
                        vt = row.get("violation_type", "")
                        fid = row.get("flag_id", "")
                        actual_by_type.setdefault(vt, set()).add(fid)
                file_ok = True
            except Exception:
                pass

        # ── Scoring helpers ──
        def score_violation_type(vtype, max_pts):
            exp = expected_by_type.get(vtype, set())
            act = actual_by_type.get(vtype, set())
            if not exp:
                return (max_pts, True, "") if not act else (0, False, f"Expected 0 but found {len(act)}")
            tp = len(exp & act)
            fp = len(act - exp)
            ratio = max(0.0, (tp - fp * 0.5) / len(exp))
            pts = round(ratio * max_pts, 2)
            passed = pts >= max_pts * 0.99
            reason = "" if passed else f"expected {len(exp)}, matched {tp}, false_pos {fp}"
            return (pts, passed, reason)

        eval_criteria = {}

        # C1: roster file format (10 pts)
        c1_score = 0
        c1_pass = False
        c1_reason = ""
        if not file_ok:
            c1_reason = "remediation_roster.csv not found or unreadable"
        elif not columns_ok:
            c1_reason = "Missing required columns"
        else:
            c1_score = 10
            c1_pass = True
        eval_criteria["roster_file_format"] = {
            "passed": c1_pass, "score": c1_score, "max_score": 10, "reason": c1_reason,
        }

        # C2-C6: violation types
        vtype_criteria = [
            ("clearance_violations", "CLEARANCE_VIOLATION", 20),
            ("targeting_violations", "TARGETING_VIOLATION", 20),
            ("missing_ticket_violations", "MISSING_TICKET", 15),
            ("out_of_window_violations", "OUT_OF_WINDOW_CHANGE", 15),
            ("sensitive_service_violations", "SENSITIVE_NO_SECURITY_APPROVAL", 10),
        ]
        for crit_name, vtype, max_pts in vtype_criteria:
            pts, passed, reason = score_violation_type(vtype, max_pts)
            eval_criteria[crit_name] = {
                "passed": passed, "score": pts, "max_score": max_pts, "reason": reason,
            }

        # C7: response summary (10 pts)
        c7_score = 0
        c7_reason = ""
        total_expected = len(expected)
        unique_flags_expected = len({v["flag_id"] for v in expected})
        try:
            # Check total count in response
            if str(total_expected) in action:
                c7_score += 5
            else:
                c7_reason += f"Expected total {total_expected} not found in response. "
            if str(unique_flags_expected) in action:
                c7_score += 5
            else:
                c7_reason += f"Expected unique flag count {unique_flags_expected} not found. "
        except Exception:
            c7_reason = "Could not parse response summary"
        eval_criteria["response_summary"] = {
            "passed": c7_score >= 10, "score": c7_score, "max_score": 10, "reason": c7_reason.strip(),
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ═══════════════════════════════════════════
    # Self-verification
    # ═══════════════════════════════════════════

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml

        # ── 1. Read workspace configuration files ──
        with open(os.path.join(self.workspace, "compliance_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        sensitive_services = set()
        with open(os.path.join(self.workspace, "sensitive_services.csv")) as f:
            for row in csv.DictReader(f):
                sensitive_services.add(row["service_name"])

        remediation_map = {}
        with open(os.path.join(self.workspace, "remediation_procedures.md")) as f:
            current_type = None
            for line in f:
                line = line.strip()
                if line.startswith("## "):
                    current_type = line[3:].strip()
                elif current_type and line and not line.startswith("#"):
                    remediation_map[current_type] = line
                    current_type = None

        # Read all targeting rules from batch files
        targeting = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("targeting_rules_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for rule in json.load(f):
                        targeting[rule["flag_id"]] = rule

        # ── 2. Gather all flags via tool (paginated) ──
        all_flags = []
        page = 1
        while True:
            result = self.tools["list_feature_flags"](page=page, page_size=50)
            all_flags.extend(result["flags"])
            if not result["has_more"]:
                break
            page += 1

        # ── 3. Gather employee info for each unique owner ──
        owner_ids = sorted(set(f["owner_id"] for f in all_flags))
        employees = {}
        for oid in owner_ids:
            employees[oid] = self.tools["get_employee_info"](employee_id=oid)

        # ── 4. Gather all approved change tickets (paginated) ──
        approved_tickets_by_flag = {}
        page = 1
        while True:
            result = self.tools["search_change_tickets"](status="approved", page=page, page_size=50)
            for t in result["tickets"]:
                approved_tickets_by_flag.setdefault(t["flag_id"], []).append(t)
            if not result["has_more"]:
                break
            page += 1

        # ── 5. Gather audit logs for modification actions (paginated) ──
        audit_modified = {}
        for act in ("modified", "toggled"):
            page = 1
            while True:
                result = self.tools["get_audit_logs"](action=act, page=page, page_size=50)
                for log in result["logs"]:
                    audit_modified.setdefault(log["flag_id"], []).append(log)
                if not result["has_more"]:
                    break
                page += 1

        # ── 6. Get Security group members for sensitive-service check ──
        sec_result = self.tools["get_ad_group_members"](group_name="Security")
        security_members = set(sec_result["member_ids"])

        # ── 7. Policy parameters ──
        env_clearance = policy["environment_clearance_requirements"]
        ticketed_envs = set(policy["change_management"]["ticket_required_environments"])
        severity_map = policy["severity_mapping"]
        exempt_groups = set(policy["targeting_policy"]["exempt_groups"])

        mw = policy["maintenance_windows"]
        wd_start = int(mw["weekday"]["start"].split(":")[0])
        wd_end = int(mw["weekday"]["end"].split(":")[0])
        we_start = int(mw["weekend"]["start"].split(":")[0])
        we_end = int(mw["weekend"]["end"].split(":")[0])

        # ── 8. Compute violations ──
        violations = []

        for flag in all_flags:
            fid = flag["flag_id"]
            env = flag["environment"]
            service = flag["service"]
            owner_id = flag["owner_id"]
            emp = employees.get(owner_id, {})
            owner_groups = set(emp.get("ad_groups", []))
            severity = severity_map.get(env, "low")

            base = {
                "flag_id": fid,
                "flag_name": flag["flag_name"],
                "service": service,
                "environment": env,
                "owner_name": emp.get("name", "Unknown"),
                "owner_id": owner_id,
                "severity": severity,
            }

            # CLEARANCE_VIOLATION
            required = env_clearance.get(env, 1)
            if emp.get("clearance_level", 0) < required:
                violations.append({
                    **base,
                    "violation_type": "CLEARANCE_VIOLATION",
                    "remediation_action": remediation_map.get("CLEARANCE_VIOLATION", ""),
                })

            # TARGETING_VIOLATION
            if fid in targeting:
                tgt = set(targeting[fid]["target_groups"])
                if not (owner_groups & tgt) and not (owner_groups & exempt_groups):
                    violations.append({
                        **base,
                        "violation_type": "TARGETING_VIOLATION",
                        "remediation_action": remediation_map.get("TARGETING_VIOLATION", ""),
                    })

            # MISSING_TICKET
            if env in ticketed_envs:
                has_mod = fid in audit_modified
                has_approved = fid in approved_tickets_by_flag
                if has_mod and not has_approved:
                    violations.append({
                        **base,
                        "violation_type": "MISSING_TICKET",
                        "remediation_action": remediation_map.get("MISSING_TICKET", ""),
                    })

            # OUT_OF_WINDOW_CHANGE
            if env in ("production", "production-critical"):
                for log in audit_modified.get(fid, []):
                    ts = datetime.strptime(log["timestamp"], "%Y-%m-%d %H:%M:%S")
                    dow = ts.weekday()
                    h = ts.hour
                    if dow < 5:
                        in_window = wd_start <= h < wd_end
                    else:
                        in_window = we_start <= h < we_end
                    if not in_window:
                        violations.append({
                            **base,
                            "violation_type": "OUT_OF_WINDOW_CHANGE",
                            "remediation_action": remediation_map.get("OUT_OF_WINDOW_CHANGE", ""),
                        })
                        break

            # SENSITIVE_NO_SECURITY_APPROVAL
            if service in sensitive_services and fid in approved_tickets_by_flag:
                has_sec = False
                for ticket in approved_tickets_by_flag[fid]:
                    if ticket["approver_id"] in security_members:
                        has_sec = True
                        break
                if not has_sec:
                    violations.append({
                        **base,
                        "violation_type": "SENSITIVE_NO_SECURITY_APPROVAL",
                        "remediation_action": remediation_map.get("SENSITIVE_NO_SECURITY_APPROVAL", ""),
                    })

        # Sort: severity order (critical > high > medium > low), then flag_id
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        violations.sort(key=lambda v: (sev_order.get(v["severity"], 99), v["flag_id"]))

        # ── 9. Write remediation_roster.csv ──
        fieldnames = [
            "flag_id", "flag_name", "service", "environment",
            "owner_name", "owner_id", "violation_type", "severity",
            "remediation_action",
        ]
        roster_path = os.path.join(self.workspace, "remediation_roster.csv")
        with open(roster_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(violations)

        # ── 10. Build response summary ──
        total_violations = len(violations)
        unique_flags = len({v["flag_id"] for v in violations})
        type_counts = {}
        for v in violations:
            type_counts[v["violation_type"]] = type_counts.get(v["violation_type"], 0) + 1

        summary_lines = [
            f"Feature flag compliance audit complete.",
            f"Total violations identified: {total_violations}",
            f"Unique flags affected: {unique_flags}",
            "Breakdown by violation type:",
        ]
        for vt in ["CLEARANCE_VIOLATION", "TARGETING_VIOLATION", "MISSING_TICKET",
                    "OUT_OF_WINDOW_CHANGE", "SENSITIVE_NO_SECURITY_APPROVAL"]:
            summary_lines.append(f"  {vt}: {type_counts.get(vt, 0)}")
        summary_lines.append(
            "The remediation roster has been saved to remediation_roster.csv "
            "sorted by severity (critical first) then flag ID."
        )

        action = "\n".join(summary_lines)
        return self.step(action)
