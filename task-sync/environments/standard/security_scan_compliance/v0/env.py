import csv
import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Tuple

import yaml


# --- Define this decorator at the top of env.py, keep unchanged ---
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

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description=(
            "List pull requests with optional filters. Returns a paginated list "
            "of pull requests. Each entry contains pr_number, title, author, "
            "source_branch, target_branch, status, created_at, and merged_at."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["merged", "open", "closed", "all"],
                    "description": "Filter by PR status. Use 'all' for no filter.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20).",
                },
            },
            "required": ["status", "page", "page_size"],
        },
    )
    def list_pull_requests(self, status: str, page: int, page_size: int):
        page_size = min(page_size, 20)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if status == "all":
            rows = conn.execute(
                "SELECT pr_number,title,author,source_branch,target_branch,"
                "status,created_at,merged_at FROM pull_requests "
                "ORDER BY pr_number LIMIT ? OFFSET ?",
                (page_size, (page - 1) * page_size),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM pull_requests"
            ).fetchone()[0]
        else:
            rows = conn.execute(
                "SELECT pr_number,title,author,source_branch,target_branch,"
                "status,created_at,merged_at FROM pull_requests "
                "WHERE status=? ORDER BY pr_number LIMIT ? OFFSET ?",
                (status, page_size, (page - 1) * page_size),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM pull_requests WHERE status=?",
                (status,),
            ).fetchone()[0]
        conn.close()
        return {
            "pull_requests": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @tool(
        description=(
            "Get all commits associated with a specific pull request number."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pr_number": {
                    "type": "integer",
                    "description": "The pull request number.",
                },
            },
            "required": ["pr_number"],
        },
    )
    def get_pr_commits(self, pr_number: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT c.commit_sha, c.author, c.message, c.committed_at "
            "FROM commits c JOIN pull_requests p ON c.pr_id=p.id "
            "WHERE p.pr_number=? ORDER BY c.committed_at",
            (pr_number,),
        ).fetchall()
        conn.close()
        return {"pr_number": pr_number, "commits": [dict(r) for r in rows]}

    @tool(
        description=(
            "Get CI pipeline execution records for a specific commit SHA."
        ),
        parameters={
            "type": "object",
            "properties": {
                "commit_sha": {
                    "type": "string",
                    "description": "The commit SHA (12-character hex).",
                },
            },
            "required": ["commit_sha"],
        },
    )
    def get_pipeline_runs(self, commit_sha: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, pipeline_name, status, started_at, finished_at "
            "FROM ci_pipelines WHERE commit_sha=? ORDER BY started_at",
            (commit_sha,),
        ).fetchall()
        conn.close()
        return {
            "commit_sha": commit_sha,
            "pipelines": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "Get security findings for a specific CI pipeline run. "
            "Returns vulnerability details including severity, status, "
            "and review information."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pipeline_id": {
                    "type": "integer",
                    "description": "The CI pipeline run ID.",
                },
            },
            "required": ["pipeline_id"],
        },
    )
    def get_findings_by_pipeline(self, pipeline_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, tool_name, vulnerability_id, severity, file_path, "
            "line_number, description, status, reviewed_by, reviewed_at "
            "FROM security_findings WHERE pipeline_id=? ORDER BY id",
            (pipeline_id,),
        ).fetchall()
        conn.close()
        return {
            "pipeline_id": pipeline_id,
            "findings": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "Get merge approval records for a specific pull request number."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pr_number": {
                    "type": "integer",
                    "description": "The pull request number.",
                },
            },
            "required": ["pr_number"],
        },
    )
    def get_merge_approvals(self, pr_number: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ma.approver, ma.approved_at "
            "FROM merge_approvals ma JOIN pull_requests p ON ma.pr_id=p.id "
            "WHERE p.pr_number=? ORDER BY ma.approved_at",
            (pr_number,),
        ).fetchall()
        conn.close()
        return {"pr_number": pr_number, "approvals": [dict(r) for r in rows]}

    @tool(
        description=(
            "Search security findings across all pipelines with optional "
            "filters. Returns paginated results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low", "all"],
                    "description": "Filter by severity level.",
                },
                "status": {
                    "type": "string",
                    "enum": ["open", "reviewed", "dismissed", "all"],
                    "description": "Filter by review status.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 20).",
                },
            },
            "required": ["severity", "status", "page", "page_size"],
        },
    )
    def search_findings(self, severity: str, status: str, page: int,
                        page_size: int):
        page_size = min(page_size, 20)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conditions = []
        params: list = []
        if severity != "all":
            conditions.append("sf.severity=?")
            params.append(severity)
        if status != "all":
            conditions.append("sf.status=?")
            params.append(status)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM security_findings sf {where}", params
        ).fetchone()[0]
        params.extend([page_size, (page - 1) * page_size])
        rows = conn.execute(
            f"SELECT sf.id, sf.pipeline_id, sf.tool_name, sf.vulnerability_id, "
            f"sf.severity, sf.file_path, sf.line_number, sf.description, "
            f"sf.status, sf.reviewed_by, sf.reviewed_at "
            f"FROM security_findings sf {where} ORDER BY sf.id "
            f"LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        conn.close()
        return {
            "findings": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @tool(
        description=(
            "Look up which pull request a given pipeline belongs to, by "
            "tracing pipeline -> commit -> pull request."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pipeline_id": {
                    "type": "integer",
                    "description": "The CI pipeline run ID.",
                },
            },
            "required": ["pipeline_id"],
        },
    )
    def get_pr_for_pipeline(self, pipeline_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT p.pr_number, p.title, p.status, p.merged_at "
            "FROM ci_pipelines cp "
            "JOIN commits c ON cp.commit_sha=c.commit_sha "
            "JOIN pull_requests p ON c.pr_id=p.id "
            "WHERE cp.id=?",
            (pipeline_id,),
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"No pull request found for pipeline {pipeline_id}"}

    # ------------------------------------------------------------------
    # Step (evaluation)
    # ------------------------------------------------------------------

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's
        final response.
        """
        ground = self._compute_ground_truth()
        eval_criteria: Dict[str, Dict] = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: remediation_backlog.csv exists with correct columns (10 pts) ---
        c1_max = 10
        backlog_path = os.path.join(self.workspace, "remediation_backlog.csv")
        expected_cols = [
            "pr_number", "violation_type", "finding_id", "vulnerability_id",
            "severity", "details", "priority",
        ]
        c1_ok = False
        agent_rows = []
        if os.path.isfile(backlog_path):
            with open(backlog_path, "r") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and set(expected_cols).issubset(
                    set(reader.fieldnames)
                ):
                    agent_rows = list(reader)
                    c1_ok = True
        c1_score = c1_max if c1_ok else 0
        eval_criteria["backlog_file_structure"] = {
            "passed": c1_ok,
            "score": c1_score,
            "max_score": c1_max,
            "reason": "" if c1_ok else "remediation_backlog.csv missing or wrong columns",
        }
        total_score += c1_score
        max_score += c1_max

        # --- Criterion 2: correct non-compliant PR identification (20 pts) ---
        c2_max = 20
        gt_prs = set(ground["non_compliant_prs"])
        agent_prs = set()
        for row in agent_rows:
            try:
                agent_prs.add(int(row["pr_number"]))
            except (ValueError, KeyError):
                pass
        if gt_prs:
            precision = (len(agent_prs & gt_prs) / len(agent_prs)
                         if agent_prs else 0)
            recall = len(agent_prs & gt_prs) / len(gt_prs)
            f1 = (2 * precision * recall / (precision + recall)
                  if (precision + recall) > 0 else 0)
        else:
            f1 = 1.0 if not agent_prs else 0.0
        c2_score = round(c2_max * f1)
        c2_ok = c2_score == c2_max
        eval_criteria["non_compliant_pr_identification"] = {
            "passed": c2_ok,
            "score": c2_score,
            "max_score": c2_max,
            "reason": ("" if c2_ok
                       else f"F1={f1:.2f} (precision={precision:.2f}, "
                            f"recall={recall:.2f})"),
        }
        total_score += c2_score
        max_score += c2_max

        # --- Criterion 3: violation type accuracy (20 pts) ---
        c3_max = 20
        gt_violations = ground["violations"]  # list of (pr, type, finding_id)
        gt_set = set()
        for v in gt_violations:
            gt_set.add((v["pr_number"], v["violation_type"],
                        str(v.get("finding_id", ""))))
        agent_set = set()
        for row in agent_rows:
            agent_set.add((
                int(row.get("pr_number", 0)),
                row.get("violation_type", ""),
                str(row.get("finding_id", "")),
            ))
        if gt_set:
            matched = len(gt_set & agent_set)
            prec = matched / len(agent_set) if agent_set else 0
            rec = matched / len(gt_set)
            f1v = (2 * prec * rec / (prec + rec)
                   if (prec + rec) > 0 else 0)
        else:
            f1v = 1.0 if not agent_set else 0.0
        c3_score = round(c3_max * f1v)
        c3_ok = c3_score == c3_max
        eval_criteria["violation_type_accuracy"] = {
            "passed": c3_ok,
            "score": c3_score,
            "max_score": c3_max,
            "reason": "" if c3_ok else f"Violation F1={f1v:.2f}",
        }
        total_score += c3_score
        max_score += c3_max

        # --- Criterion 4: priority assignment correctness (15 pts) ---
        c4_max = 15
        gt_priority_map = {}
        for v in gt_violations:
            key = (v["pr_number"], v["violation_type"],
                   str(v.get("finding_id", "")))
            gt_priority_map[key] = v["priority"]
        correct_priorities = 0
        total_matchable = 0
        for row in agent_rows:
            key = (int(row.get("pr_number", 0)),
                   row.get("violation_type", ""),
                   str(row.get("finding_id", "")))
            if key in gt_priority_map:
                total_matchable += 1
                if row.get("priority", "") == gt_priority_map[key]:
                    correct_priorities += 1
        c4_ratio = (correct_priorities / total_matchable
                    if total_matchable > 0 else 0)
        c4_score = round(c4_max * c4_ratio)
        c4_ok = c4_score == c4_max
        eval_criteria["priority_assignment"] = {
            "passed": c4_ok,
            "score": c4_score,
            "max_score": c4_max,
            "reason": ("" if c4_ok
                       else f"{correct_priorities}/{total_matchable} correct"),
        }
        total_score += c4_score
        max_score += c4_max

        # --- Criterion 5: backlog sorted correctly (10 pts) ---
        c5_max = 10
        priority_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
        sorted_ok = True
        for i in range(1, len(agent_rows)):
            prev_p = priority_order.get(agent_rows[i - 1].get("priority", ""), 99)
            curr_p = priority_order.get(agent_rows[i].get("priority", ""), 99)
            prev_pr = int(agent_rows[i - 1].get("pr_number", 0))
            curr_pr = int(agent_rows[i].get("pr_number", 0))
            if (prev_p, prev_pr) > (curr_p, curr_pr):
                sorted_ok = False
                break
        if not agent_rows:
            sorted_ok = False
        c5_score = c5_max if sorted_ok else 0
        eval_criteria["backlog_sort_order"] = {
            "passed": sorted_ok,
            "score": c5_score,
            "max_score": c5_max,
            "reason": "" if sorted_ok else "Rows not sorted by priority then pr_number",
        }
        total_score += c5_score
        max_score += c5_max

        # --- Criterion 6: summary statistics in response (15 pts) ---
        c6_max = 15
        gt_summary = ground["summary"]
        checks = {
            "total_merged_prs": str(gt_summary["total_merged_prs"]),
            "compliant_prs": str(gt_summary["compliant_prs"]),
            "non_compliant_prs": str(gt_summary["non_compliant_prs"]),
            "total_violations": str(gt_summary["total_violations"]),
        }
        c6_matched = 0
        for key, expected_val in checks.items():
            # look for key: value pattern in action
            if f"{key}: {expected_val}" in action or f"{key}:{expected_val}" in action:
                c6_matched += 1
            elif expected_val in action and key.replace("_", " ") in action.lower():
                c6_matched += 1
        c6_ratio = c6_matched / len(checks)
        c6_score = round(c6_max * c6_ratio)
        c6_ok = c6_score == c6_max
        eval_criteria["summary_statistics"] = {
            "passed": c6_ok,
            "score": c6_score,
            "max_score": c6_max,
            "reason": ("" if c6_ok
                       else f"Matched {c6_matched}/{len(checks)} summary stats"),
        }
        total_score += c6_score
        max_score += c6_max

        # --- Criterion 7: violation count accuracy (10 pts) ---
        c7_max = 10
        gt_total_v = len(gt_violations)
        agent_total_v = len(agent_rows)
        if gt_total_v > 0:
            count_accuracy = 1 - abs(agent_total_v - gt_total_v) / gt_total_v
            count_accuracy = max(0, count_accuracy)
        else:
            count_accuracy = 1.0 if agent_total_v == 0 else 0.0
        c7_score = round(c7_max * count_accuracy)
        c7_ok = c7_score == c7_max
        eval_criteria["violation_count_accuracy"] = {
            "passed": c7_ok,
            "score": c7_score,
            "max_score": c7_max,
            "reason": ("" if c7_ok
                       else f"Expected {gt_total_v}, got {agent_total_v}"),
        }
        total_score += c7_score
        max_score += c7_max

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ------------------------------------------------------------------
    # Ground-truth computation (used by step and verify)
    # ------------------------------------------------------------------

    def _compute_ground_truth(self) -> dict:
        """Compute full ground truth from DB + workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load policy
        policy_path = os.path.join(self.workspace, "scan_policy.yaml")
        with open(policy_path, "r") as f:
            policy = yaml.safe_load(f)

        # Load authorized reviewers
        reviewers_path = os.path.join(self.workspace, "authorized_reviewers.csv")
        authorized = {}  # name -> max_severity
        sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        with open(reviewers_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                authorized[row["reviewer_name"]] = row["max_authorized_severity"]

        # Load PR metadata (compliance tiers)
        pr_tier = {}  # pr_number -> tier
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("pr_metadata_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    entries = json.load(f)
                    for entry in entries:
                        pr_tier[entry["pr_number"]] = entry["compliance_tier"]

        # Get merged PRs
        merged_prs = conn.execute(
            "SELECT id, pr_number, merged_at FROM pull_requests "
            "WHERE status='merged' ORDER BY pr_number"
        ).fetchall()

        violations = []
        non_compliant = set()

        priority_matrix = policy["violation_priority_matrix"]
        tiers = policy["compliance_tiers"]

        for pr in merged_prs:
            pr_id = pr["id"]
            pr_number = pr["pr_number"]
            merged_at_str = pr["merged_at"]
            merged_at = datetime.strptime(merged_at_str, "%Y-%m-%dT%H:%M:%SZ")

            tier = pr_tier.get(pr_number, "tier3")
            required_scans = set(tiers[tier]["required_scans"])
            review_required_sevs = set(
                tiers[tier]["pre_merge_review_required_severities"])

            # Collect all commits for this PR
            commits = conn.execute(
                "SELECT commit_sha FROM commits WHERE pr_id=?", (pr_id,)
            ).fetchall()

            # Collect all pipeline runs across all commits
            all_scans_run = set()
            all_findings = []
            for commit in commits:
                sha = commit["commit_sha"]
                pipelines = conn.execute(
                    "SELECT id, pipeline_name, status FROM ci_pipelines "
                    "WHERE commit_sha=?", (sha,)
                ).fetchall()
                for pipe in pipelines:
                    if pipe["status"] != "skipped":
                        all_scans_run.add(pipe["pipeline_name"])
                    # Get findings for security scan pipelines
                    if pipe["pipeline_name"] in ("sast", "dast",
                                                  "dependency_check"):
                        findings = conn.execute(
                            "SELECT id, severity, status, reviewed_by, "
                            "reviewed_at FROM security_findings "
                            "WHERE pipeline_id=?", (pipe["id"],)
                        ).fetchall()
                        for f in findings:
                            all_findings.append(dict(f))

            # Check 1: missing required scans
            missing = required_scans - all_scans_run
            for scan in sorted(missing):
                p = priority_matrix["missing_required_scan"].get(tier, "P4")
                violations.append({
                    "pr_number": pr_number,
                    "violation_type": "missing_required_scan",
                    "finding_id": "",
                    "vulnerability_id": "",
                    "severity": "",
                    "details": f"Missing required scan: {scan}",
                    "priority": p,
                })
                non_compliant.add(pr_number)

            # Check 2 & 3 & 4: finding-level violations
            for finding in all_findings:
                sev = finding["severity"]
                if sev not in review_required_sevs:
                    continue

                fid = finding["id"]

                # Check 2: unreviewed finding
                if finding["status"] == "open":
                    p = priority_matrix["unreviewed_finding"].get(sev, "P4")
                    # look up vulnerability_id
                    vuln_row = conn.execute(
                        "SELECT vulnerability_id FROM security_findings "
                        "WHERE id=?", (fid,)
                    ).fetchone()
                    vuln_id = vuln_row["vulnerability_id"] if vuln_row else ""
                    violations.append({
                        "pr_number": pr_number,
                        "violation_type": "unreviewed_finding",
                        "finding_id": str(fid),
                        "vulnerability_id": vuln_id,
                        "severity": sev,
                        "details": f"Unreviewed {sev} finding",
                        "priority": p,
                    })
                    non_compliant.add(pr_number)
                    continue

                # Finding is reviewed or dismissed
                reviewer = finding["reviewed_by"]
                reviewed_at_str = finding["reviewed_at"]

                # Check 3: unauthorized reviewer
                if reviewer:
                    auth_sev = authorized.get(reviewer)
                    if auth_sev is None or sev_rank.get(sev, 3) < sev_rank.get(
                        auth_sev, 3
                    ):
                        vuln_row = conn.execute(
                            "SELECT vulnerability_id FROM security_findings "
                            "WHERE id=?", (fid,)
                        ).fetchone()
                        vuln_id = (vuln_row["vulnerability_id"]
                                   if vuln_row else "")
                        p = priority_matrix["unauthorized_review"].get(
                            sev, "P4")
                        violations.append({
                            "pr_number": pr_number,
                            "violation_type": "unauthorized_review",
                            "finding_id": str(fid),
                            "vulnerability_id": vuln_id,
                            "severity": sev,
                            "details": (
                                f"Reviewer {reviewer} not authorized for "
                                f"{sev} severity"),
                            "priority": p,
                        })
                        non_compliant.add(pr_number)

                # Check 4: premature merge (reviewed after merge)
                if reviewed_at_str:
                    reviewed_at = datetime.strptime(
                        reviewed_at_str, "%Y-%m-%dT%H:%M:%SZ")
                    if reviewed_at > merged_at:
                        vuln_row = conn.execute(
                            "SELECT vulnerability_id FROM security_findings "
                            "WHERE id=?", (fid,)
                        ).fetchone()
                        vuln_id = (vuln_row["vulnerability_id"]
                                   if vuln_row else "")
                        p = priority_matrix["premature_merge"].get(sev, "P4")
                        violations.append({
                            "pr_number": pr_number,
                            "violation_type": "premature_merge",
                            "finding_id": str(fid),
                            "vulnerability_id": vuln_id,
                            "severity": sev,
                            "details": (
                                f"Finding reviewed at {reviewed_at_str} "
                                f"after merge at {merged_at_str}"),
                            "priority": p,
                        })
                        non_compliant.add(pr_number)

        conn.close()

        # Sort violations: priority asc, then pr_number asc
        priority_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
        violations.sort(key=lambda v: (
            priority_order.get(v["priority"], 99), v["pr_number"]))

        total_merged = len(merged_prs)
        summary = {
            "total_merged_prs": total_merged,
            "compliant_prs": total_merged - len(non_compliant),
            "non_compliant_prs": len(non_compliant),
            "total_violations": len(violations),
        }

        return {
            "violations": violations,
            "non_compliant_prs": sorted(non_compliant),
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        # Step 1: Read policy files from workspace
        with open(os.path.join(self.workspace, "scan_policy.yaml"), "r") as f:
            policy = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "authorized_reviewers.csv"),
                  "r") as f:
            reader = csv.DictReader(f)
            authorized = {}
            sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            for row in reader:
                authorized[row["reviewer_name"]] = row[
                    "max_authorized_severity"]

        with open(os.path.join(self.workspace, "sla_config.json"), "r") as f:
            sla_config = json.load(f)

        # Read PR metadata files to get compliance tiers
        pr_tier = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("pr_metadata_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    entries = json.load(f)
                    for entry in entries:
                        pr_tier[entry["pr_number"]] = entry["compliance_tier"]

        tiers_config = policy["compliance_tiers"]
        priority_matrix = policy["violation_priority_matrix"]

        # Step 2: List all merged PRs via tools (paginated)
        merged_prs = []
        page = 1
        while True:
            result = self.tools["list_pull_requests"](
                status="merged", page=page, page_size=20)
            merged_prs.extend(result["pull_requests"])
            if page * 20 >= result["total"]:
                break
            page += 1

        # Step 3: For each merged PR, gather data via tools
        violations = []
        non_compliant = set()

        for pr in merged_prs:
            pr_number = pr["pr_number"]
            merged_at_str = pr["merged_at"]
            merged_at = datetime.strptime(merged_at_str, "%Y-%m-%dT%H:%M:%SZ")

            tier = pr_tier.get(pr_number, "tier3")
            required_scans = set(tiers_config[tier]["required_scans"])
            review_required_sevs = set(
                tiers_config[tier]["pre_merge_review_required_severities"])

            # Get commits
            commits_result = self.tools["get_pr_commits"](pr_number=pr_number)
            commits = commits_result["commits"]

            # Get pipelines for each commit
            all_scans_run = set()
            security_pipeline_ids = []

            for commit in commits:
                sha = commit["commit_sha"]
                pipe_result = self.tools["get_pipeline_runs"](commit_sha=sha)
                for pipe in pipe_result["pipelines"]:
                    if pipe["status"] != "skipped":
                        all_scans_run.add(pipe["pipeline_name"])
                    if pipe["pipeline_name"] in (
                        "sast", "dast", "dependency_check"
                    ):
                        security_pipeline_ids.append(pipe["id"])

            # Check missing scans
            missing = required_scans - all_scans_run
            for scan in sorted(missing):
                p = priority_matrix["missing_required_scan"].get(tier, "P4")
                violations.append({
                    "pr_number": pr_number,
                    "violation_type": "missing_required_scan",
                    "finding_id": "",
                    "vulnerability_id": "",
                    "severity": "",
                    "details": f"Missing required scan: {scan}",
                    "priority": p,
                })
                non_compliant.add(pr_number)

            # Get findings for security pipelines
            for pid in security_pipeline_ids:
                findings_result = self.tools["get_findings_by_pipeline"](
                    pipeline_id=pid)
                for finding in findings_result["findings"]:
                    sev = finding["severity"]
                    if sev not in review_required_sevs:
                        continue

                    fid = finding["id"]

                    # Unreviewed
                    if finding["status"] == "open":
                        p = priority_matrix["unreviewed_finding"].get(
                            sev, "P4")
                        violations.append({
                            "pr_number": pr_number,
                            "violation_type": "unreviewed_finding",
                            "finding_id": str(fid),
                            "vulnerability_id": finding["vulnerability_id"],
                            "severity": sev,
                            "details": f"Unreviewed {sev} finding",
                            "priority": p,
                        })
                        non_compliant.add(pr_number)
                        continue

                    # Unauthorized reviewer
                    reviewer = finding["reviewed_by"]
                    if reviewer:
                        auth_sev = authorized.get(reviewer)
                        if auth_sev is None or sev_rank.get(
                            sev, 3
                        ) < sev_rank.get(auth_sev, 3):
                            p = priority_matrix["unauthorized_review"].get(
                                sev, "P4")
                            violations.append({
                                "pr_number": pr_number,
                                "violation_type": "unauthorized_review",
                                "finding_id": str(fid),
                                "vulnerability_id": finding[
                                    "vulnerability_id"],
                                "severity": sev,
                                "details": (
                                    f"Reviewer {reviewer} not authorized for "
                                    f"{sev} severity"),
                                "priority": p,
                            })
                            non_compliant.add(pr_number)

                    # Premature merge
                    reviewed_at_str = finding["reviewed_at"]
                    if reviewed_at_str:
                        reviewed_at = datetime.strptime(
                            reviewed_at_str, "%Y-%m-%dT%H:%M:%SZ")
                        if reviewed_at > merged_at:
                            p = priority_matrix["premature_merge"].get(
                                sev, "P4")
                            violations.append({
                                "pr_number": pr_number,
                                "violation_type": "premature_merge",
                                "finding_id": str(fid),
                                "vulnerability_id": finding[
                                    "vulnerability_id"],
                                "severity": sev,
                                "details": (
                                    f"Finding reviewed at {reviewed_at_str} "
                                    f"after merge at {merged_at_str}"),
                                "priority": p,
                            })
                            non_compliant.add(pr_number)

        # Sort violations
        priority_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
        violations.sort(key=lambda v: (
            priority_order.get(v["priority"], 99), v["pr_number"]))

        # Write remediation_backlog.csv
        backlog_path = os.path.join(self.workspace, "remediation_backlog.csv")
        fieldnames = ["pr_number", "violation_type", "finding_id",
                      "vulnerability_id", "severity", "details", "priority"]
        with open(backlog_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(violations)

        # Build summary
        total_merged = len(merged_prs)
        summary = {
            "total_merged_prs": total_merged,
            "compliant_prs": total_merged - len(non_compliant),
            "non_compliant_prs": len(non_compliant),
            "total_violations": len(violations),
        }

        action = (
            f"Compliance analysis complete.\n\n"
            f"total_merged_prs: {summary['total_merged_prs']}\n"
            f"compliant_prs: {summary['compliant_prs']}\n"
            f"non_compliant_prs: {summary['non_compliant_prs']}\n"
            f"total_violations: {summary['total_violations']}\n\n"
            f"The remediation backlog has been saved to remediation_backlog.csv "
            f"with {len(violations)} entries sorted by priority (P1 first) "
            f"then by PR number ascending."
        )

        return self.step(action)
