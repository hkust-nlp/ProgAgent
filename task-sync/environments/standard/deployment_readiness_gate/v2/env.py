"""
Deployment Readiness Gate - Task Environment
"""

import json
import os
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

    # -------------------------------------------------------------------
    # Tool methods
    # -------------------------------------------------------------------

    @tool(
        description="List services registered in the system. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip (default 0).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return (default 20, max 20).",
                },
            },
            "required": [],
        },
    )
    def list_services(self, offset: int = 0, limit: int = 20) -> dict:
        limit = min(limit, 20)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM services")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT id, name, team, criticality FROM services ORDER BY id LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "services": [
                {"id": r[0], "name": r[1], "team": r[2], "criticality": r[3]}
                for r in rows
            ],
        }

    @tool(
        description="Get recent commits for a specific service, optionally filtered by branch. Returns up to 10 most recent commits.",
        parameters={
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "integer",
                    "description": "The service ID.",
                },
                "branch": {
                    "type": "string",
                    "description": "Filter by branch name. If omitted, returns commits from all branches.",
                },
            },
            "required": ["service_id"],
        },
    )
    def get_recent_commits(self, service_id: int, branch: str = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if branch:
            cur.execute(
                "SELECT id, commit_hash, author, timestamp, test_coverage_pct, branch, message "
                "FROM commits WHERE service_id = ? AND branch = ? "
                "ORDER BY timestamp DESC LIMIT 10",
                (service_id, branch),
            )
        else:
            cur.execute(
                "SELECT id, commit_hash, author, timestamp, test_coverage_pct, branch, message "
                "FROM commits WHERE service_id = ? "
                "ORDER BY timestamp DESC LIMIT 10",
                (service_id,),
            )
        rows = cur.fetchall()
        conn.close()
        return {
            "service_id": service_id,
            "commits": [
                {
                    "id": r[0],
                    "commit_hash": r[1],
                    "author": r[2],
                    "timestamp": r[3],
                    "test_coverage_pct": r[4],
                    "branch": r[5],
                    "message": r[6],
                }
                for r in rows
            ],
        }

    @tool(
        description="Search Jira tickets for a specific service with optional filters on priority and status.",
        parameters={
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "integer",
                    "description": "The service ID.",
                },
                "priority": {
                    "type": "string",
                    "description": "Filter by priority (e.g. 'P0', 'P1'). Omit to return all.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status (e.g. 'Open', 'In Progress'). Omit to return all.",
                },
            },
            "required": ["service_id"],
        },
    )
    def search_jira_tickets(self, service_id: int, priority: str = None, status: str = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        query = "SELECT id, ticket_key, summary, priority, status, environment, created_date, updated_date FROM jira_tickets WHERE service_id = ?"
        params: list = [service_id]
        if priority:
            query += " AND priority = ?"
            params.append(priority)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_date DESC"
        cur.execute(query, params)
        rows = cur.fetchall()
        conn.close()
        return {
            "service_id": service_id,
            "total": len(rows),
            "tickets": [
                {
                    "id": r[0],
                    "ticket_key": r[1],
                    "summary": r[2],
                    "priority": r[3],
                    "status": r[4],
                    "environment": r[5],
                    "created_date": r[6],
                    "updated_date": r[7],
                }
                for r in rows
            ],
        }

    @tool(
        description="Get configuration drift entries for a specific environment. Optionally filter by service.",
        parameters={
            "type": "object",
            "properties": {
                "environment_id": {
                    "type": "integer",
                    "description": "The environment ID.",
                },
                "service_id": {
                    "type": "integer",
                    "description": "Optionally filter by a specific service ID.",
                },
            },
            "required": ["environment_id"],
        },
    )
    def get_config_drift(self, environment_id: int, service_id: int = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if service_id:
            cur.execute(
                "SELECT id, service_id, parameter_name, expected_value, actual_value, "
                "drift_severity, detected_date FROM config_drift_entries "
                "WHERE environment_id = ? AND service_id = ? ORDER BY detected_date DESC",
                (environment_id, service_id),
            )
        else:
            cur.execute(
                "SELECT id, service_id, parameter_name, expected_value, actual_value, "
                "drift_severity, detected_date FROM config_drift_entries "
                "WHERE environment_id = ? ORDER BY detected_date DESC",
                (environment_id,),
            )
        rows = cur.fetchall()
        conn.close()
        return {
            "environment_id": environment_id,
            "total": len(rows),
            "drift_entries": [
                {
                    "id": r[0],
                    "service_id": r[1],
                    "parameter_name": r[2],
                    "expected_value": r[3],
                    "actual_value": r[4],
                    "drift_severity": r[5],
                    "detected_date": r[6],
                }
                for r in rows
            ],
        }

    @tool(
        description="Get security scan history for a specific service. Returns all scan records.",
        parameters={
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "integer",
                    "description": "The service ID.",
                },
                "scan_type": {
                    "type": "string",
                    "description": "Filter by scan type (SAST, DAST, SCA, container). Omit for all.",
                },
            },
            "required": ["service_id"],
        },
    )
    def get_security_scans(self, service_id: int, scan_type: str = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if scan_type:
            cur.execute(
                "SELECT id, scan_type, status, scan_timestamp, "
                "vulnerabilities_critical, vulnerabilities_high, "
                "vulnerabilities_medium, vulnerabilities_low "
                "FROM security_scans WHERE service_id = ? AND scan_type = ? "
                "ORDER BY scan_timestamp DESC",
                (service_id, scan_type),
            )
        else:
            cur.execute(
                "SELECT id, scan_type, status, scan_timestamp, "
                "vulnerabilities_critical, vulnerabilities_high, "
                "vulnerabilities_medium, vulnerabilities_low "
                "FROM security_scans WHERE service_id = ? "
                "ORDER BY scan_timestamp DESC",
                (service_id,),
            )
        rows = cur.fetchall()
        conn.close()
        return {
            "service_id": service_id,
            "total": len(rows),
            "scans": [
                {
                    "id": r[0],
                    "scan_type": r[1],
                    "status": r[2],
                    "scan_timestamp": r[3],
                    "vulnerabilities_critical": r[4],
                    "vulnerabilities_high": r[5],
                    "vulnerabilities_medium": r[6],
                    "vulnerabilities_low": r[7],
                }
                for r in rows
            ],
        }

    @tool(
        description="Get detailed information about a specific environment.",
        parameters={
            "type": "object",
            "properties": {
                "environment_id": {
                    "type": "integer",
                    "description": "The environment ID.",
                },
            },
            "required": ["environment_id"],
        },
    )
    def get_environment_details(self, environment_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, region, stage, status, last_deploy_date "
            "FROM environments WHERE id = ?",
            (environment_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Environment {environment_id} not found."}
        return {
            "id": row[0],
            "name": row[1],
            "region": row[2],
            "stage": row[3],
            "status": row[4],
            "last_deploy_date": row[5],
        }

    @tool(
        description="List all environments. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip (default 0).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return (default 20, max 20).",
                },
            },
            "required": [],
        },
    )
    def list_environments(self, offset: int = 0, limit: int = 20) -> dict:
        limit = min(limit, 20)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM environments")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT id, name, region, stage, status FROM environments ORDER BY id LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "environments": [
                {"id": r[0], "name": r[1], "region": r[2], "stage": r[3], "status": r[4]}
                for r in rows
            ],
        }

    @tool(
        description="Get service details by service ID.",
        parameters={
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "integer",
                    "description": "The service ID.",
                },
            },
            "required": ["service_id"],
        },
    )
    def get_service_details(self, service_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, team, criticality, repo_url, created_date "
            "FROM services WHERE id = ?",
            (service_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Service {service_id} not found."}
        return {
            "id": row[0],
            "name": row[1],
            "team": row[2],
            "criticality": row[3],
            "repo_url": row[4],
            "created_date": row[5],
        }

    # -------------------------------------------------------------------
    # Evaluation
    # -------------------------------------------------------------------

    def _compute_ground_truth(self) -> dict:
        """Compute the ground truth dashboard using DB + workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load policy
        with open(os.path.join(self.workspace, "go_nogo_policy.yaml")) as f:
            policy = yaml.safe_load(f)["deployment_policy"]

        # Load release manifest
        with open(os.path.join(self.workspace, "release_manifest.json")) as f:
            manifest = json.load(f)

        # Load scan requirements
        with open(os.path.join(self.workspace, "scan_requirements.json")) as f:
            scan_req = json.load(f)

        release_date = datetime.strptime(manifest["release_date"], "%Y-%m-%d")
        release_svc_ids = [s["service_id"] for s in manifest["services"]]
        target_env_ids = [e["environment_id"] for e in manifest["target_environments"]]

        cov_policy = policy["test_coverage"]
        jira_policy = policy["jira_blocking"]
        drift_policy = policy["config_drift"]
        sec_policy = policy["security_scan"]

        cur = conn.cursor()

        # Build service info lookup
        svc_info = {}
        for sid in release_svc_ids:
            cur.execute("SELECT id, name, team, criticality FROM services WHERE id = ?", (sid,))
            row = cur.fetchone()
            if row:
                svc_info[sid] = dict(row)

        # Build environment info lookup
        env_info = {}
        for eid in target_env_ids:
            cur.execute("SELECT id, name, region, stage, status FROM environments WHERE id = ?", (eid,))
            row = cur.fetchone()
            if row:
                env_info[eid] = dict(row)

        severity_order = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        max_allowed_sev = severity_order.get(drift_policy["max_allowed_severity"], 1)

        dashboard_rows = []
        blocking_issues_list = []

        for sid in release_svc_ids:
            if sid not in svc_info:
                continue
            svc = svc_info[sid]
            criticality = svc["criticality"]

            # --- Test coverage check ---
            branch = cov_policy["branch"]
            lookback = cov_policy["lookback_commits"]
            min_cov = (
                cov_policy["critical_services_min_pct"]
                if criticality == "critical"
                else cov_policy["standard_services_min_pct"]
            )
            cur.execute(
                "SELECT test_coverage_pct FROM commits "
                "WHERE service_id = ? AND branch = ? ORDER BY timestamp DESC LIMIT ?",
                (sid, branch, lookback),
            )
            cov_rows = [r[0] for r in cur.fetchall()]
            if cov_rows:
                avg_cov = round(sum(cov_rows) / len(cov_rows), 2)
            else:
                avg_cov = 0.0
            cov_pass = avg_cov >= min_cov

            # --- Jira blocking check ---
            blocking_prios = jira_policy["blocking_priorities"]
            blocking_statuses = jira_policy["blocking_statuses"]
            placeholders_p = ",".join("?" for _ in blocking_prios)
            placeholders_s = ",".join("?" for _ in blocking_statuses)
            cur.execute(
                f"SELECT ticket_key, summary, priority, status FROM jira_tickets "
                f"WHERE service_id = ? AND priority IN ({placeholders_p}) "
                f"AND status IN ({placeholders_s})",
                [sid] + blocking_prios + blocking_statuses,
            )
            blocking_tickets = [dict(r) for r in cur.fetchall()]
            jira_pass = len(blocking_tickets) == 0

            # --- Security scan check (per-service, not per-env) ---
            required_types = sec_policy["required_scan_types"].get(criticality, [])
            max_age = sec_policy["max_scan_age_days"]
            max_crit_vuln = sec_policy["max_critical_vulnerabilities"]
            max_high_vuln = sec_policy["max_high_vulnerabilities"]
            scan_issues = []
            for st in required_types:
                cur.execute(
                    "SELECT scan_type, status, scan_timestamp, "
                    "vulnerabilities_critical, vulnerabilities_high "
                    "FROM security_scans WHERE service_id = ? AND scan_type = ? "
                    "AND status = 'passed' ORDER BY scan_timestamp DESC LIMIT 1",
                    (sid, st),
                )
                row = cur.fetchone()
                if row is None:
                    scan_issues.append(f"Missing passed {st} scan")
                else:
                    scan_ts = datetime.strptime(row["scan_timestamp"], "%Y-%m-%dT%H:%M:%S")
                    age = (release_date - scan_ts).days
                    if age > max_age:
                        scan_issues.append(f"{st} scan too old ({age} days)")
                    if row["vulnerabilities_critical"] > max_crit_vuln:
                        scan_issues.append(
                            f"{st} scan has {row['vulnerabilities_critical']} critical vulnerabilities"
                        )
                    if row["vulnerabilities_high"] > max_high_vuln:
                        scan_issues.append(
                            f"{st} scan has {row['vulnerabilities_high']} high vulnerabilities"
                        )
            sec_pass = len(scan_issues) == 0

            for eid in target_env_ids:
                if eid not in env_info:
                    continue
                env = env_info[eid]

                # --- Config drift check ---
                cur.execute(
                    "SELECT parameter_name, expected_value, actual_value, drift_severity "
                    "FROM config_drift_entries "
                    "WHERE environment_id = ? AND service_id = ?",
                    (eid, sid),
                )
                drift_rows = cur.fetchall()
                drift_blockers = []
                for dr in drift_rows:
                    sev_level = severity_order.get(dr["drift_severity"], 0)
                    if sev_level > max_allowed_sev:
                        drift_blockers.append({
                            "parameter": dr["parameter_name"],
                            "severity": dr["drift_severity"],
                            "expected": dr["expected_value"],
                            "actual": dr["actual_value"],
                        })
                drift_pass = len(drift_blockers) == 0

                # Overall for this service-env pair
                go = cov_pass and jira_pass and sec_pass and drift_pass

                issues = []
                if not cov_pass:
                    issues.append(f"Coverage {avg_cov:.2f}% < {min_cov:.2f}%")
                if not jira_pass:
                    for t in blocking_tickets:
                        issues.append(f"Jira {t['ticket_key']} ({t['priority']}/{t['status']})")
                if not sec_pass:
                    issues.extend(scan_issues)
                if not drift_pass:
                    for db_ in drift_blockers:
                        issues.append(
                            f"Drift {db_['parameter']} severity={db_['severity']}"
                        )

                row_data = {
                    "service_name": svc["name"],
                    "service_id": sid,
                    "environment_name": env["name"],
                    "environment_id": eid,
                    "go_nogo": "GO" if go else "NO-GO",
                    "test_coverage_avg": f"{avg_cov:.2f}",
                    "test_coverage_status": "PASS" if cov_pass else "FAIL",
                    "jira_blocker_count": len(blocking_tickets),
                    "jira_status": "PASS" if jira_pass else "FAIL",
                    "config_drift_blocker_count": len(drift_blockers),
                    "config_drift_status": "PASS" if drift_pass else "FAIL",
                    "security_scan_status": "PASS" if sec_pass else "FAIL",
                    "blocking_issues": "; ".join(issues) if issues else "",
                }
                dashboard_rows.append(row_data)

                if not go:
                    blocking_issues_list.append({
                        "service_name": svc["name"],
                        "service_id": sid,
                        "environment_name": env["name"],
                        "environment_id": eid,
                        "issues": issues,
                    })

        conn.close()

        # Compute summary
        total_pairs = len(dashboard_rows)
        go_count = sum(1 for r in dashboard_rows if r["go_nogo"] == "GO")
        nogo_count = total_pairs - go_count
        overall = "GO" if nogo_count == 0 else "NO-GO"

        return {
            "dashboard_rows": sorted(
                dashboard_rows, key=lambda r: (r["service_name"], r["environment_name"])
            ),
            "blocking_issues": blocking_issues_list,
            "summary": {
                "total_pairs": total_pairs,
                "go_count": go_count,
                "nogo_count": nogo_count,
                "overall_decision": overall,
            },
        }

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
        gt_rows = gt["dashboard_rows"]
        gt_summary = gt["summary"]
        gt_blocking = gt["blocking_issues"]

        eval_criteria = {}
        import csv

        # --- Criterion 1: Dashboard file exists (10 pts) ---
        dashboard_path = os.path.join(self.workspace, "deployment_dashboard.csv")
        file_exists = os.path.isfile(dashboard_path)
        eval_criteria["dashboard_file_exists"] = {
            "passed": file_exists,
            "score": 10 if file_exists else 0,
            "max_score": 10,
        }
        if not file_exists:
            eval_criteria["dashboard_file_exists"]["reason"] = "deployment_dashboard.csv not found"

        # --- Criterion 2: Correct columns (10 pts) ---
        required_cols = {
            "service_name", "environment_name", "go_nogo",
            "test_coverage_status", "jira_status",
            "config_drift_status", "security_scan_status", "blocking_issues",
        }
        parsed_rows = []
        cols_ok = False
        if file_exists:
            try:
                with open(dashboard_path, newline="") as f:
                    reader = csv.DictReader(f)
                    actual_cols = set(reader.fieldnames or [])
                    cols_ok = required_cols.issubset(actual_cols)
                    for row in reader:
                        parsed_rows.append(row)
            except Exception:
                cols_ok = False
        eval_criteria["correct_columns"] = {
            "passed": cols_ok,
            "score": 10 if cols_ok else 0,
            "max_score": 10,
        }
        if not cols_ok:
            eval_criteria["correct_columns"]["reason"] = (
                f"Missing columns. Required: {sorted(required_cols)}"
            )

        # --- Criterion 3: Correct service-environment pairs (15 pts) ---
        gt_pairs = {(r["service_name"], r["environment_name"]) for r in gt_rows}
        actual_pairs = set()
        for r in parsed_rows:
            sn = r.get("service_name", "").strip()
            en = r.get("environment_name", "").strip()
            if sn and en:
                actual_pairs.add((sn, en))
        if gt_pairs:
            pair_overlap = len(gt_pairs & actual_pairs)
            pair_score = round(15 * pair_overlap / len(gt_pairs))
        else:
            pair_score = 0
        pairs_ok = gt_pairs == actual_pairs
        eval_criteria["correct_pairs"] = {
            "passed": pairs_ok,
            "score": pair_score,
            "max_score": 15,
        }
        if not pairs_ok:
            missing = gt_pairs - actual_pairs
            extra = actual_pairs - gt_pairs
            reasons = []
            if missing:
                reasons.append(f"Missing {len(missing)} pairs")
            if extra:
                reasons.append(f"Extra {len(extra)} pairs")
            eval_criteria["correct_pairs"]["reason"] = "; ".join(reasons)

        # --- Criterion 4: Correct go/no-go decisions (25 pts) ---
        gt_decision_map = {
            (r["service_name"], r["environment_name"]): r["go_nogo"] for r in gt_rows
        }
        actual_decision_map = {}
        for r in parsed_rows:
            key = (r.get("service_name", "").strip(), r.get("environment_name", "").strip())
            actual_decision_map[key] = r.get("go_nogo", "").strip().upper()
        correct_decisions = 0
        total_decisions = len(gt_decision_map)
        for key, expected in gt_decision_map.items():
            actual = actual_decision_map.get(key, "")
            if actual == expected:
                correct_decisions += 1
        if total_decisions > 0:
            decision_score = round(25 * correct_decisions / total_decisions)
        else:
            decision_score = 0
        decisions_ok = correct_decisions == total_decisions
        eval_criteria["correct_go_nogo"] = {
            "passed": decisions_ok,
            "score": decision_score,
            "max_score": 25,
        }
        if not decisions_ok:
            eval_criteria["correct_go_nogo"]["reason"] = (
                f"{correct_decisions}/{total_decisions} decisions correct"
            )

        # --- Criterion 5: Correct status columns (15 pts) ---
        status_cols = [
            "test_coverage_status", "jira_status",
            "config_drift_status", "security_scan_status",
        ]
        gt_status_map = {}
        for r in gt_rows:
            key = (r["service_name"], r["environment_name"])
            gt_status_map[key] = {c: r[c] for c in status_cols}
        actual_status_map = {}
        for r in parsed_rows:
            key = (r.get("service_name", "").strip(), r.get("environment_name", "").strip())
            actual_status_map[key] = {
                c: r.get(c, "").strip().upper() for c in status_cols
            }
        total_checks = len(gt_status_map) * len(status_cols)
        correct_checks = 0
        for key, expected_statuses in gt_status_map.items():
            actual_statuses = actual_status_map.get(key, {})
            for col in status_cols:
                if actual_statuses.get(col, "") == expected_statuses[col]:
                    correct_checks += 1
        if total_checks > 0:
            status_score = round(15 * correct_checks / total_checks)
        else:
            status_score = 0
        status_ok = correct_checks == total_checks
        eval_criteria["correct_status_columns"] = {
            "passed": status_ok,
            "score": status_score,
            "max_score": 15,
        }
        if not status_ok:
            eval_criteria["correct_status_columns"]["reason"] = (
                f"{correct_checks}/{total_checks} status values correct"
            )

        # --- Criterion 6: Blocking issues JSON file (15 pts) ---
        bi_path = os.path.join(self.workspace, "blocking_issues.json")
        bi_exists = os.path.isfile(bi_path)
        bi_score = 0
        if bi_exists:
            try:
                with open(bi_path) as f:
                    bi_data = json.load(f)
                # Check it's a list with entries for each blocking pair
                gt_blocking_pairs = {
                    (b["service_name"], b["environment_name"]) for b in gt_blocking
                }
                actual_bi_pairs = set()
                if isinstance(bi_data, list):
                    for entry in bi_data:
                        sn = entry.get("service_name", "").strip()
                        en = entry.get("environment_name", "").strip()
                        if sn and en:
                            actual_bi_pairs.add((sn, en))
                if gt_blocking_pairs and gt_blocking_pairs == actual_bi_pairs:
                    bi_score = 15
                elif gt_blocking_pairs:
                    overlap = len(gt_blocking_pairs & actual_bi_pairs)
                    bi_score = round(10 * overlap / len(gt_blocking_pairs))
                elif not gt_blocking_pairs and not actual_bi_pairs:
                    bi_score = 15
                else:
                    bi_score = 5  # File exists, partial credit
            except Exception:
                bi_score = 3  # File exists but can't parse
        eval_criteria["blocking_issues_file"] = {
            "passed": bi_score == 15,
            "score": bi_score,
            "max_score": 15,
        }
        if bi_score < 15:
            eval_criteria["blocking_issues_file"]["reason"] = (
                "blocking_issues.json missing or incomplete"
                if not bi_exists else "blocking_issues.json content mismatch"
            )

        # --- Criterion 7: Summary in response (10 pts) ---
        response_score = 0
        action_upper = action.upper() if action else ""
        overall = gt_summary["overall_decision"]
        if overall in action_upper:
            response_score += 4
        go_str = str(gt_summary["go_count"])
        nogo_str = str(gt_summary["nogo_count"])
        if go_str in action and nogo_str in action:
            response_score += 3
        total_str = str(gt_summary["total_pairs"])
        if total_str in action:
            response_score += 3
        eval_criteria["summary_in_response"] = {
            "passed": response_score == 10,
            "score": response_score,
            "max_score": 10,
        }
        if response_score < 10:
            eval_criteria["summary_in_response"]["reason"] = (
                f"Response should contain overall decision ({overall}), "
                f"GO count ({go_str}), NO-GO count ({nogo_str}), "
                f"total pairs ({total_str})"
            )

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
        import csv as csv_mod

        # Step 1: Read workspace files
        with open(os.path.join(self.workspace, "release_manifest.json")) as f:
            manifest = json.load(f)

        with open(os.path.join(self.workspace, "go_nogo_policy.yaml")) as f:
            policy = yaml.safe_load(f)["deployment_policy"]

        with open(os.path.join(self.workspace, "scan_requirements.json")) as f:
            scan_req = json.load(f)

        release_date = datetime.strptime(manifest["release_date"], "%Y-%m-%d")
        release_svcs = manifest["services"]
        target_envs = manifest["target_environments"]

        cov_policy = policy["test_coverage"]
        jira_policy = policy["jira_blocking"]
        drift_policy = policy["config_drift"]
        sec_policy = policy["security_scan"]

        severity_order = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        max_allowed_sev = severity_order.get(drift_policy["max_allowed_severity"], 1)

        tool_call_count = 0

        # Step 2: Get service details for each release service
        svc_details = {}
        for s in release_svcs:
            sid = s["service_id"]
            result = self.tools["get_service_details"](service_id=sid)
            tool_call_count += 1
            svc_details[sid] = result

        # Step 3: Get recent commits on main branch for coverage
        svc_coverage = {}
        for s in release_svcs:
            sid = s["service_id"]
            result = self.tools["get_recent_commits"](
                service_id=sid, branch=cov_policy["branch"]
            )
            tool_call_count += 1
            commits = result["commits"]
            lookback = cov_policy["lookback_commits"]
            recent = commits[:lookback]
            if recent:
                avg = sum(c["test_coverage_pct"] for c in recent) / len(recent)
            else:
                avg = 0.0
            svc_coverage[sid] = round(avg, 2)

        # Step 4: Check Jira tickets for blocking issues
        svc_blocking_tickets = {}
        for s in release_svcs:
            sid = s["service_id"]
            all_blocking = []
            for prio in jira_policy["blocking_priorities"]:
                for status in jira_policy["blocking_statuses"]:
                    result = self.tools["search_jira_tickets"](
                        service_id=sid, priority=prio, status=status
                    )
                    tool_call_count += 1
                    all_blocking.extend(result["tickets"])
            # Deduplicate by ticket_key
            seen = set()
            unique = []
            for t in all_blocking:
                if t["ticket_key"] not in seen:
                    seen.add(t["ticket_key"])
                    unique.append(t)
            svc_blocking_tickets[sid] = unique

        # Step 5: Check security scans
        svc_scan_issues = {}
        for s in release_svcs:
            sid = s["service_id"]
            criticality = svc_details[sid]["criticality"]
            required_types = sec_policy["required_scan_types"].get(criticality, [])
            issues = []
            for st in required_types:
                result = self.tools["get_security_scans"](
                    service_id=sid, scan_type=st
                )
                tool_call_count += 1
                # Find latest passed scan
                passed_scans = [
                    sc for sc in result["scans"] if sc["status"] == "passed"
                ]
                if not passed_scans:
                    issues.append(f"Missing passed {st} scan")
                else:
                    latest = passed_scans[0]  # Already sorted desc
                    scan_ts = datetime.strptime(
                        latest["scan_timestamp"], "%Y-%m-%dT%H:%M:%S"
                    )
                    age = (release_date - scan_ts).days
                    if age > sec_policy["max_scan_age_days"]:
                        issues.append(f"{st} scan too old ({age} days)")
                    if latest["vulnerabilities_critical"] > sec_policy["max_critical_vulnerabilities"]:
                        issues.append(
                            f"{st} scan has {latest['vulnerabilities_critical']} critical vulnerabilities"
                        )
                    if latest["vulnerabilities_high"] > sec_policy["max_high_vulnerabilities"]:
                        issues.append(
                            f"{st} scan has {latest['vulnerabilities_high']} high vulnerabilities"
                        )
            svc_scan_issues[sid] = issues

        # Step 6: Check config drift per environment per service
        env_svc_drift = {}
        for env in target_envs:
            eid = env["environment_id"]
            result = self.tools["get_config_drift"](environment_id=eid)
            tool_call_count += 1
            for entry in result["drift_entries"]:
                sev = severity_order.get(entry["drift_severity"], 0)
                if sev > max_allowed_sev:
                    key = (eid, entry["service_id"])
                    if key not in env_svc_drift:
                        env_svc_drift[key] = []
                    env_svc_drift[key].append({
                        "parameter": entry["parameter_name"],
                        "severity": entry["drift_severity"],
                        "expected": entry["expected_value"],
                        "actual": entry["actual_value"],
                    })

        # Step 7: Get environment details
        env_details = {}
        for env in target_envs:
            eid = env["environment_id"]
            result = self.tools["get_environment_details"](environment_id=eid)
            tool_call_count += 1

        # Step 8: Build dashboard
        dashboard_rows = []
        blocking_issues_list = []
        release_svc_ids = {s["service_id"] for s in release_svcs}

        for s in release_svcs:
            sid = s["service_id"]
            svc = svc_details[sid]
            criticality = svc["criticality"]
            min_cov = (
                cov_policy["critical_services_min_pct"]
                if criticality == "critical"
                else cov_policy["standard_services_min_pct"]
            )
            avg_cov = svc_coverage[sid]
            cov_pass = avg_cov >= min_cov
            jira_pass = len(svc_blocking_tickets[sid]) == 0
            sec_pass = len(svc_scan_issues[sid]) == 0

            for env in target_envs:
                eid = env["environment_id"]
                drift_blockers = env_svc_drift.get((eid, sid), [])
                drift_pass = len(drift_blockers) == 0

                go = cov_pass and jira_pass and sec_pass and drift_pass
                issues = []
                if not cov_pass:
                    issues.append(f"Coverage {avg_cov:.2f}% < {min_cov:.2f}%")
                if not jira_pass:
                    for t in svc_blocking_tickets[sid]:
                        issues.append(f"Jira {t['ticket_key']} ({t['priority']}/{t['status']})")
                if not sec_pass:
                    issues.extend(svc_scan_issues[sid])
                if not drift_pass:
                    for db_ in drift_blockers:
                        issues.append(f"Drift {db_['parameter']} severity={db_['severity']}")

                dashboard_rows.append({
                    "service_name": svc["name"],
                    "environment_name": env["environment_name"],
                    "go_nogo": "GO" if go else "NO-GO",
                    "test_coverage_avg": f"{avg_cov:.2f}",
                    "test_coverage_status": "PASS" if cov_pass else "FAIL",
                    "jira_blocker_count": str(len(svc_blocking_tickets[sid])),
                    "jira_status": "PASS" if jira_pass else "FAIL",
                    "config_drift_blocker_count": str(len(drift_blockers)),
                    "config_drift_status": "PASS" if drift_pass else "FAIL",
                    "security_scan_status": "PASS" if sec_pass else "FAIL",
                    "blocking_issues": "; ".join(issues) if issues else "",
                })

                if not go:
                    blocking_issues_list.append({
                        "service_name": svc["name"],
                        "environment_name": env["environment_name"],
                        "issues": issues,
                    })

        # Sort
        dashboard_rows.sort(key=lambda r: (r["service_name"], r["environment_name"]))

        # Write dashboard CSV
        fieldnames = [
            "service_name", "environment_name", "go_nogo",
            "test_coverage_avg", "test_coverage_status",
            "jira_blocker_count", "jira_status",
            "config_drift_blocker_count", "config_drift_status",
            "security_scan_status", "blocking_issues",
        ]
        with open(os.path.join(self.workspace, "deployment_dashboard.csv"), "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(dashboard_rows)

        # Write blocking issues JSON
        with open(os.path.join(self.workspace, "blocking_issues.json"), "w") as f:
            json.dump(blocking_issues_list, f, indent=2)

        # Compute summary
        total_pairs = len(dashboard_rows)
        go_count = sum(1 for r in dashboard_rows if r["go_nogo"] == "GO")
        nogo_count = total_pairs - go_count
        overall = "GO" if nogo_count == 0 else "NO-GO"

        action = (
            f"Deployment readiness assessment complete. "
            f"Overall decision: {overall}. "
            f"Out of {total_pairs} service-environment pairs, "
            f"{go_count} are GO and {nogo_count} are NO-GO. "
            f"Dashboard saved to deployment_dashboard.csv and blocking issues to blocking_issues.json."
        )

        print(f"[verify] Tool calls made: {tool_call_count}")
        return self.step(action)
