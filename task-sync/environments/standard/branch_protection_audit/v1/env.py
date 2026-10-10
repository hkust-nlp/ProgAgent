"""
Branch Protection Rule Compliance Audit - Environment
"""

import sqlite3
import os
import json
import csv
import glob
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


def _envelope(payload):
    """MCP-style tool result: payload JSON-encoded in a text content block."""
    return {"content": [{"type": "text",
                         "text": json.dumps(payload, ensure_ascii=False, default=str)}],
            "isError": False}


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

    # ─── Tool Methods ───

    @tool(
        description="List repositories with pagination. Returns repository id, name, org, visibility, default_branch, created_at, and whether branch protection rules exist for the repo.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 25)",
                },
            },
            "required": ["page"],
        },
    )
    def list_repositories(self, page: int, page_size: int = 20):
        page_size = min(page_size, 25)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        total = cursor.execute("SELECT COUNT(*) FROM repositories").fetchone()[0]

        rows = cursor.execute(
            """
            SELECT r.id, r.name, r.org, r.visibility, r.default_branch, r.created_at,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM branch_protection_rules WHERE repo_id = r.id
                   ) THEN 1 ELSE 0 END AS has_protection
            FROM repositories r
            ORDER BY r.id
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        ).fetchall()
        conn.close()

        return json.dumps({
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "repositories": [dict(r) for r in rows],
        }, ensure_ascii=False, default=str)

    @tool(
        description="Get all branch protection rules for a specific repository.",
        parameters={
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "integer",
                    "description": "Repository ID",
                },
            },
            "required": ["repo_id"],
        },
    )
    def get_branch_protection_rules(self, repo_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM branch_protection_rules WHERE repo_id = ? ORDER BY id",
            (repo_id,),
        ).fetchall()
        conn.close()
        return json.dumps({"repo_id": repo_id, "rules": [dict(r) for r in rows]}, ensure_ascii=False, default=str)

    @tool(
        description="Query push events for a repository with optional filters. Returns push event details including whether the push was forced.",
        parameters={
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "integer",
                    "description": "Repository ID",
                },
                "branch": {
                    "type": "string",
                    "description": "Filter by branch name (optional)",
                },
                "forced_only": {
                    "type": "boolean",
                    "description": "If true, return only forced push events (default false)",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed, default 1)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 25, default 20)",
                },
            },
            "required": ["repo_id"],
        },
    )
    def get_push_events(self, repo_id: int, branch: str = None,
                        forced_only: bool = False, page: int = 1, page_size: int = 20):
        page_size = min(page_size, 25)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        conditions = ["repo_id = ?"]
        params: list = [repo_id]
        if branch:
            conditions.append("branch = ?")
            params.append(branch)
        if forced_only:
            conditions.append("forced = 1")

        where = " AND ".join(conditions)

        total = conn.execute(
            f"SELECT COUNT(*) FROM push_events WHERE {where}", params
        ).fetchone()[0]

        params_paged = params + [page_size, offset]
        rows = conn.execute(
            f"SELECT * FROM push_events WHERE {where} ORDER BY timestamp LIMIT ? OFFSET ?",
            params_paged,
        ).fetchall()
        conn.close()

        return json.dumps({
            "repo_id": repo_id,
            "page": page,
            "page_size": page_size,
            "total": total,
            "events": [dict(r) for r in rows],
        }, ensure_ascii=False, default=str)

    @tool(
        description="Get code review decisions for a specific pull request in a repository. Returns reviewer names, decisions (approved/changes_requested/commented), and timestamps.",
        parameters={
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "integer",
                    "description": "Repository ID",
                },
                "pr_number": {
                    "type": "integer",
                    "description": "Pull request number",
                },
            },
            "required": ["repo_id", "pr_number"],
        },
    )
    def get_pull_request_reviews(self, repo_id: int, pr_number: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM code_reviews WHERE repo_id = ? AND pr_number = ? ORDER BY submitted_at",
            (repo_id, pr_number),
        ).fetchall()
        conn.close()
        return _envelope({
            "repo_id": repo_id,
            "pr_number": pr_number,
            "reviews": [dict(r) for r in rows],
        })

    @tool(
        description="Get status check results for a specific commit SHA in a repository. Returns check names, statuses (success/failure/pending), and completion timestamps.",
        parameters={
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "integer",
                    "description": "Repository ID",
                },
                "commit_sha": {
                    "type": "string",
                    "description": "The commit SHA to look up status checks for",
                },
            },
            "required": ["repo_id", "commit_sha"],
        },
    )
    def get_status_check_results(self, repo_id: int, commit_sha: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM status_checks WHERE repo_id = ? AND commit_sha = ? ORDER BY check_name",
            (repo_id, commit_sha),
        ).fetchall()
        conn.close()
        return _envelope({
            "repo_id": repo_id,
            "commit_sha": commit_sha,
            "checks": [dict(r) for r in rows],
        })

    @tool(
        description="Look up a repository's ID by its name. Returns the repository ID and basic info if found.",
        parameters={
            "type": "object",
            "properties": {
                "repo_name": {
                    "type": "string",
                    "description": "The repository name to look up",
                },
            },
            "required": ["repo_name"],
        },
    )
    def lookup_repo_by_name(self, repo_name: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM repositories WHERE name = ?", (repo_name,)
        ).fetchone()
        conn.close()
        if row:
            return _envelope({"found": True, "repository": dict(row)})
        return _envelope({"found": False, "repository": None})

    # ─── Evaluation ───

    def _compute_ground_truth(self):
        """Compute all violations using the database and workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load compliance policy
        with open(os.path.join(self.workspace, "compliance_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        # Load exemptions
        with open(os.path.join(self.workspace, "exemptions.json")) as f:
            exemptions = json.load(f)

        exempt_repos = set(exemptions.get("exempt_repos", []))
        exempt_users = exemptions.get("exempt_users", {})

        severity_weights = policy["severity_weights"]
        violation_severities = {
            vtype: info["severity"]
            for vtype, info in policy["violation_types"].items()
        }

        # Load team ownership
        team_map = {}
        with open(os.path.join(self.workspace, "team_ownership.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                team_map[row["repo_name"]] = row["team"]

        # Load all merge records from workspace batch files
        merge_records = []
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "merge_records_batch_*"))):
            if fpath.endswith(".csv"):
                with open(fpath) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        row["pr_number"] = int(row["pr_number"])
                        row["admin_override"] = row["admin_override"] in ("True", "true", "1", True)
                        merge_records.append(row)
            elif fpath.endswith(".json"):
                with open(fpath) as f:
                    data = json.load(f)
                    for row in data:
                        row["pr_number"] = int(row["pr_number"])
                        if isinstance(row["admin_override"], str):
                            row["admin_override"] = row["admin_override"] in ("True", "true", "1")
                        merge_records.append(row)

        # Build repo name -> id mapping
        repos = conn.execute("SELECT id, name FROM repositories").fetchall()
        repo_name_to_id = {r["name"]: r["id"] for r in repos}
        repo_id_to_name = {r["id"]: r["name"] for r in repos}

        # Build repo_id -> rules mapping
        rules = conn.execute("SELECT * FROM branch_protection_rules").fetchall()
        repo_rules = {}
        for rule in rules:
            repo_rules.setdefault(rule["repo_id"], []).append(dict(rule))

        violations = []

        # 1. Force push violations
        forced_pushes = conn.execute(
            "SELECT * FROM push_events WHERE forced = 1"
        ).fetchall()

        for fp in forced_pushes:
            repo_id = fp["repo_id"]
            repo_name = repo_id_to_name.get(repo_id, "")
            branch = fp["branch"]

            if repo_name in exempt_repos:
                continue
            if fp["user"] in exempt_users and "force_push" in exempt_users[fp["user"]]:
                continue

            # Check if there's a protection rule for this branch disallowing force push
            if repo_id in repo_rules:
                for rule in repo_rules[repo_id]:
                    pattern = rule["branch_pattern"]
                    if self._branch_matches_pattern(branch, pattern) and rule["allow_force_push"] == 0:
                        violations.append({
                            "repo_name": repo_name,
                            "branch": branch,
                            "violation_type": "force_push",
                            "severity": violation_severities["force_push"],
                            "offending_user": fp["user"],
                            "event_timestamp": fp["timestamp"],
                            "description": f"Forced push to protected branch {branch}",
                            "owning_team": team_map.get(repo_name, "Unknown"),
                        })
                        break

        # 2. Review violations, status check violations, admin override violations
        for mr in merge_records:
            repo_name = mr["repo_name"]
            repo_id = repo_name_to_id.get(repo_name)
            if repo_id is None:
                continue

            if repo_name in exempt_repos:
                continue

            branch = mr["branch"]
            pr_number = mr["pr_number"]
            commit_sha = mr["merge_commit_sha"]
            merged_by = mr["merged_by"]
            merged_at = mr["merged_at"]
            is_admin_override = mr["admin_override"]

            if repo_id not in repo_rules:
                continue

            matching_rule = None
            for rule in repo_rules[repo_id]:
                if self._branch_matches_pattern(branch, rule["branch_pattern"]):
                    matching_rule = rule
                    break
            if matching_rule is None:
                continue

            # Check insufficient reviews
            if matching_rule["require_pull_request_reviews"]:
                min_approvals = matching_rule["min_approvals"]
                reviews = conn.execute(
                    "SELECT * FROM code_reviews WHERE repo_id = ? AND pr_number = ? AND decision = 'approved'",
                    (repo_id, pr_number),
                ).fetchall()
                actual_approvals = len(reviews)
                if actual_approvals < min_approvals:
                    if not (merged_by in exempt_users and "insufficient_reviews" in exempt_users.get(merged_by, [])):
                        violations.append({
                            "repo_name": repo_name,
                            "branch": branch,
                            "violation_type": "insufficient_reviews",
                            "severity": violation_severities["insufficient_reviews"],
                            "offending_user": merged_by,
                            "event_timestamp": merged_at,
                            "description": f"PR #{pr_number} merged with {actual_approvals} approvals (required {min_approvals})",
                            "owning_team": team_map.get(repo_name, "Unknown"),
                        })

            # Check failed status checks
            if matching_rule["require_status_checks"]:
                required_checks = [
                    c.strip()
                    for c in (matching_rule["required_status_checks"] or "").split(",")
                    if c.strip()
                ]
                if required_checks:
                    status_checks = conn.execute(
                        "SELECT check_name, status FROM status_checks WHERE repo_id = ? AND commit_sha = ?",
                        (repo_id, commit_sha),
                    ).fetchall()
                    check_statuses = {sc["check_name"]: sc["status"] for sc in status_checks}
                    failed_checks = [
                        c for c in required_checks
                        if check_statuses.get(c) == "failure"
                    ]
                    if failed_checks:
                        if not (merged_by in exempt_users and "failed_status_checks" in exempt_users.get(merged_by, [])):
                            violations.append({
                                "repo_name": repo_name,
                                "branch": branch,
                                "violation_type": "failed_status_checks",
                                "severity": violation_severities["failed_status_checks"],
                                "offending_user": merged_by,
                                "event_timestamp": merged_at,
                                "description": f"PR #{pr_number} merged with failing checks: {', '.join(failed_checks)}",
                                "owning_team": team_map.get(repo_name, "Unknown"),
                            })

            # Check admin override
            if is_admin_override and matching_rule["enforce_admins"]:
                if not (merged_by in exempt_users and "admin_override" in exempt_users.get(merged_by, [])):
                    violations.append({
                        "repo_name": repo_name,
                        "branch": branch,
                        "violation_type": "admin_override",
                        "severity": violation_severities["admin_override"],
                        "offending_user": merged_by,
                        "event_timestamp": merged_at,
                        "description": f"Admin {merged_by} bypassed enforce-admins on {branch}",
                        "owning_team": team_map.get(repo_name, "Unknown"),
                    })

        conn.close()

        # Sort: severity weight descending, then timestamp ascending
        violations.sort(
            key=lambda v: (-severity_weights[v["severity"]], v["event_timestamp"])
        )

        # Compute escalation repos
        repo_scores = {}
        for v in violations:
            w = severity_weights[v["severity"]]
            repo_scores[v["repo_name"]] = repo_scores.get(v["repo_name"], 0) + w
        escalation_threshold = policy["escalation_threshold"]
        escalation_repos = sorted([
            r for r, s in repo_scores.items() if s >= escalation_threshold
        ])

        # Build summary
        by_severity = {}
        by_type = {}
        for v in violations:
            by_severity[v["severity"]] = by_severity.get(v["severity"], 0) + 1
            by_type[v["violation_type"]] = by_type.get(v["violation_type"], 0) + 1

        # Top offending repos by violation count
        repo_counts = {}
        for v in violations:
            repo_counts[v["repo_name"]] = repo_counts.get(v["repo_name"], 0) + 1
        top_repos = sorted(repo_counts.items(), key=lambda x: (-x[1], x[0]))[:5]

        summary = {
            "total_violations": len(violations),
            "by_severity": {s: by_severity.get(s, 0) for s in ["critical", "high", "medium", "low"]},
            "by_type": {t: by_type.get(t, 0) for t in ["force_push", "insufficient_reviews", "failed_status_checks", "admin_override"]},
            "top_offending_repos": [{"repo_name": r, "violation_count": c} for r, c in top_repos],
            "escalation_repos": escalation_repos,
        }

        return violations, summary

    def _branch_matches_pattern(self, branch: str, pattern: str) -> bool:
        """Check if a branch name matches a protection rule pattern."""
        if pattern == branch:
            return True
        if pattern.endswith("/*"):
            prefix = pattern[:-2]
            return branch.startswith(prefix + "/")
        return False

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
        gt_violations, gt_summary = self._compute_ground_truth()

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: violation_report.csv exists and has correct columns (10 pts) ──
        report_path = os.path.join(self.workspace, "violation_report.csv")
        c1_score = 0
        c1_max = 10
        c1_reason = ""
        expected_cols = {"repo_name", "branch", "violation_type", "severity",
                         "offending_user", "event_timestamp", "description", "owning_team"}
        if os.path.exists(report_path):
            try:
                with open(report_path) as f:
                    reader = csv.DictReader(f)
                    actual_cols = set(reader.fieldnames or [])
                    if expected_cols.issubset(actual_cols):
                        c1_score = 10
                    else:
                        missing = expected_cols - actual_cols
                        c1_score = 5
                        c1_reason = f"Missing columns: {missing}"
            except Exception as e:
                c1_reason = f"Error reading CSV: {e}"
        else:
            c1_reason = "violation_report.csv not found"

        eval_criteria["report_file_structure"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": c1_reason if c1_score < c1_max else "",
        }

        # ── Criterion 2: Correct total violation count (15 pts) ──
        c2_score = 0
        c2_max = 15
        c2_reason = ""
        agent_violations = []
        if os.path.exists(report_path):
            try:
                with open(report_path) as f:
                    reader = csv.DictReader(f)
                    agent_violations = list(reader)
            except Exception:
                pass

        expected_count = len(gt_violations)
        actual_count = len(agent_violations)
        if actual_count == expected_count:
            c2_score = 15
        elif abs(actual_count - expected_count) <= 2:
            c2_score = 10
            c2_reason = f"Expected {expected_count} violations, got {actual_count}"
        elif abs(actual_count - expected_count) <= 5:
            c2_score = 5
            c2_reason = f"Expected {expected_count} violations, got {actual_count}"
        else:
            c2_reason = f"Expected {expected_count} violations, got {actual_count}"

        eval_criteria["violation_count"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": c2_reason if c2_score < c2_max else "",
        }

        # ── Criterion 3: Violation content accuracy (25 pts) ──
        c3_score = 0
        c3_max = 25
        c3_reason = ""

        # Build set of ground truth violation keys
        gt_keys = set()
        for v in gt_violations:
            gt_keys.add((v["repo_name"], v["violation_type"], v["offending_user"], v["event_timestamp"]))

        agent_keys = set()
        for v in agent_violations:
            agent_keys.add((
                v.get("repo_name", ""),
                v.get("violation_type", ""),
                v.get("offending_user", ""),
                v.get("event_timestamp", ""),
            ))

        if gt_keys:
            matched = len(gt_keys & agent_keys)
            precision = len(gt_keys & agent_keys) / len(agent_keys) if agent_keys else 0
            recall = matched / len(gt_keys)
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            c3_score = round(f1 * c3_max)
            if c3_score < c3_max:
                missing = gt_keys - agent_keys
                extra = agent_keys - gt_keys
                parts = []
                if missing:
                    parts.append(f"{len(missing)} missing violations")
                if extra:
                    parts.append(f"{len(extra)} extra violations")
                c3_reason = "; ".join(parts)
        else:
            c3_score = c3_max  # No violations expected, and none found

        eval_criteria["violation_accuracy"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": c3_reason if c3_score < c3_max else "",
        }

        # ── Criterion 4: Sort order correctness (10 pts) ──
        c4_score = 0
        c4_max = 10
        c4_reason = ""

        severity_weights = {"critical": 10, "high": 7, "medium": 4, "low": 1}
        if agent_violations and len(agent_violations) > 1:
            correctly_sorted = True
            for i in range(len(agent_violations) - 1):
                w_curr = severity_weights.get(agent_violations[i].get("severity", ""), 0)
                w_next = severity_weights.get(agent_violations[i + 1].get("severity", ""), 0)
                t_curr = agent_violations[i].get("event_timestamp", "")
                t_next = agent_violations[i + 1].get("event_timestamp", "")
                if w_curr < w_next:
                    correctly_sorted = False
                    break
                if w_curr == w_next and t_curr > t_next:
                    correctly_sorted = False
                    break
            if correctly_sorted:
                c4_score = 10
            else:
                c4_reason = "Violations not sorted by severity weight desc, then timestamp asc"
        elif len(agent_violations) <= 1:
            c4_score = 10  # Trivially sorted

        eval_criteria["sort_order"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": c4_reason if c4_score < c4_max else "",
        }

        # ── Criterion 5: executive_summary.json exists and correct (20 pts) ──
        c5_score = 0
        c5_max = 20
        c5_reason = ""
        summary_path = os.path.join(self.workspace, "executive_summary.json")
        if os.path.exists(summary_path):
            try:
                with open(summary_path) as f:
                    agent_summary = json.load(f)

                sub_scores = 0

                # total_violations
                if agent_summary.get("total_violations") == gt_summary["total_violations"]:
                    sub_scores += 5
                else:
                    c5_reason += f"total_violations: expected {gt_summary['total_violations']}, got {agent_summary.get('total_violations')}; "

                # by_severity
                agent_by_sev = agent_summary.get("by_severity", {})
                if all(agent_by_sev.get(s, 0) == gt_summary["by_severity"].get(s, 0) for s in ["critical", "high", "medium", "low"]):
                    sub_scores += 5
                else:
                    c5_reason += f"by_severity mismatch; "

                # by_type
                agent_by_type = agent_summary.get("by_type", {})
                if all(agent_by_type.get(t, 0) == gt_summary["by_type"].get(t, 0) for t in ["force_push", "insufficient_reviews", "failed_status_checks", "admin_override"]):
                    sub_scores += 5
                else:
                    c5_reason += f"by_type mismatch; "

                # escalation_repos
                agent_esc = sorted(agent_summary.get("escalation_repos", []))
                if agent_esc == gt_summary["escalation_repos"]:
                    sub_scores += 5
                else:
                    c5_reason += f"escalation_repos mismatch: expected {gt_summary['escalation_repos']}, got {agent_esc}; "

                c5_score = sub_scores
            except Exception as e:
                c5_reason = f"Error reading summary: {e}"
        else:
            c5_reason = "executive_summary.json not found"

        eval_criteria["executive_summary"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": c5_reason.strip().rstrip(";") if c5_score < c5_max else "",
        }

        # ── Criterion 6: Exemptions correctly applied (10 pts) ──
        c6_score = 0
        c6_max = 10
        c6_reason = ""

        # Check that no exempt repos appear in agent violations
        with open(os.path.join(self.workspace, "exemptions.json")) as f:
            exemptions = json.load(f)
        exempt_repos = set(exemptions.get("exempt_repos", []))
        exempt_users = exemptions.get("exempt_users", {})

        has_exempt_repo = any(v.get("repo_name") in exempt_repos for v in agent_violations)
        has_exempt_user = False
        for v in agent_violations:
            user = v.get("offending_user", "")
            vtype = v.get("violation_type", "")
            if user in exempt_users and vtype in exempt_users[user]:
                has_exempt_user = True
                break

        if not has_exempt_repo and not has_exempt_user:
            c6_score = 10
        else:
            parts = []
            if has_exempt_repo:
                parts.append("Exempt repo violations included")
            if has_exempt_user:
                parts.append("Exempt user/type violations included")
            c6_reason = "; ".join(parts)

        eval_criteria["exemptions_applied"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": c6_reason if c6_score < c6_max else "",
        }

        # ── Criterion 7: Response contains summary text (10 pts) ──
        c7_score = 0
        c7_max = 10
        c7_reason = ""
        action_lower = action.lower()

        checks_passed = 0
        if str(gt_summary["total_violations"]) in action:
            checks_passed += 1
        if any(s in action_lower for s in ["violation", "compliance", "audit"]):
            checks_passed += 1
        if any(s in action_lower for s in ["force push", "force_push"]):
            checks_passed += 1
        if any(s in action_lower for s in ["review", "approval"]):
            checks_passed += 1
        if any(s in action_lower for s in ["status check", "status_check"]):
            checks_passed += 1

        c7_score = min(c7_max, checks_passed * 2)

        eval_criteria["response_summary"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": c7_reason if c7_score < c7_max else "",
        }

        # ── Aggregate ──
        for c in eval_criteria.values():
            total_score += c["score"]
            max_score += c["max_score"]

        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

        return reward, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import glob as glob_mod

        tool_calls = 0

        # 1. Read compliance policy
        with open(os.path.join(self.workspace, "compliance_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        severity_weights = policy["severity_weights"]
        violation_severities = {
            vtype: info["severity"]
            for vtype, info in policy["violation_types"].items()
        }
        escalation_threshold = policy["escalation_threshold"]

        # 2. Read exemptions
        with open(os.path.join(self.workspace, "exemptions.json")) as f:
            exemptions = json.load(f)
        exempt_repos = set(exemptions.get("exempt_repos", []))
        exempt_users = exemptions.get("exempt_users", {})

        # 3. Read team ownership
        team_map = {}
        with open(os.path.join(self.workspace, "team_ownership.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                team_map[row["repo_name"]] = row["team"]

        # 4. Read reporting template
        with open(os.path.join(self.workspace, "reporting_template.md")) as f:
            _ = f.read()

        # 5. Read all merge records from workspace batch files
        merge_records = []
        for fpath in sorted(glob_mod.glob(os.path.join(self.workspace, "merge_records_batch_*"))):
            if fpath.endswith(".csv"):
                with open(fpath) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        row["pr_number"] = int(row["pr_number"])
                        row["admin_override"] = row["admin_override"] in ("True", "true", "1", True)
                        merge_records.append(row)
            elif fpath.endswith(".json"):
                with open(fpath) as f:
                    data = json.load(f)
                    for row in data:
                        row["pr_number"] = int(row["pr_number"])
                        if isinstance(row["admin_override"], str):
                            row["admin_override"] = row["admin_override"] in ("True", "true", "1")
                        merge_records.append(row)

        # 6. List all repositories via tool
        all_repos = []
        page = 1
        while True:
            result = json.loads(self.tools["list_repositories"](page=page, page_size=25))
            tool_calls += 1
            all_repos.extend(result["repositories"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Build name->id mapping
        repo_name_to_id = {r["name"]: r["id"] for r in all_repos}
        repo_id_to_name = {r["id"]: r["name"] for r in all_repos}

        # 7. Get protection rules for all protected repos
        protected_repos = [r for r in all_repos if r["has_protection"]]
        repo_rules = {}
        for r in protected_repos:
            result = json.loads(self.tools["get_branch_protection_rules"](repo_id=r["id"]))
            tool_calls += 1
            if result["rules"]:
                repo_rules[r["id"]] = result["rules"]

        violations = []

        # 8. Check force push violations
        for repo_id, rules_list in repo_rules.items():
            repo_name = repo_id_to_name[repo_id]
            if repo_name in exempt_repos:
                continue

            no_force_branches = [
                r for r in rules_list if r["allow_force_push"] == 0
            ]
            if not no_force_branches:
                continue

            result = json.loads(self.tools["get_push_events"](repo_id=repo_id, forced_only=True, page=1, page_size=25))
            tool_calls += 1
            events = result["events"]
            # Handle pagination
            total_pages = (result["total"] + 24) // 25
            for p in range(2, total_pages + 1):
                r2 = json.loads(self.tools["get_push_events"](repo_id=repo_id, forced_only=True, page=p, page_size=25))
                tool_calls += 1
                events.extend(r2["events"])

            for event in events:
                branch = event["branch"]
                user = event["user"]

                if user in exempt_users and "force_push" in exempt_users[user]:
                    continue

                for rule in no_force_branches:
                    pattern = rule["branch_pattern"]
                    if self._branch_matches_pattern(branch, pattern):
                        violations.append({
                            "repo_name": repo_name,
                            "branch": branch,
                            "violation_type": "force_push",
                            "severity": violation_severities["force_push"],
                            "offending_user": user,
                            "event_timestamp": event["timestamp"],
                            "description": f"Forced push to protected branch {branch}",
                            "owning_team": team_map.get(repo_name, "Unknown"),
                        })
                        break

        # 9. Check merge-related violations
        for mr in merge_records:
            repo_name = mr["repo_name"]
            if repo_name in exempt_repos:
                continue

            repo_id = repo_name_to_id.get(repo_name)
            if repo_id is None or repo_id not in repo_rules:
                continue

            branch = mr["branch"]
            pr_number = mr["pr_number"]
            commit_sha = mr["merge_commit_sha"]
            merged_by = mr["merged_by"]
            merged_at = mr["merged_at"]
            is_admin_override = mr["admin_override"]

            # Find matching rule
            matching_rule = None
            for rule in repo_rules[repo_id]:
                if self._branch_matches_pattern(branch, rule["branch_pattern"]):
                    matching_rule = rule
                    break
            if matching_rule is None:
                continue

            # Check insufficient reviews
            if matching_rule["require_pull_request_reviews"]:
                min_approvals = matching_rule["min_approvals"]
                result = json.loads(self.tools["get_pull_request_reviews"](repo_id=repo_id, pr_number=pr_number)["content"][0]["text"])
                tool_calls += 1
                approvals = [r for r in result["reviews"] if r["decision"] == "approved"]
                if len(approvals) < min_approvals:
                    if not (merged_by in exempt_users and "insufficient_reviews" in exempt_users.get(merged_by, [])):
                        violations.append({
                            "repo_name": repo_name,
                            "branch": branch,
                            "violation_type": "insufficient_reviews",
                            "severity": violation_severities["insufficient_reviews"],
                            "offending_user": merged_by,
                            "event_timestamp": merged_at,
                            "description": f"PR #{pr_number} merged with {len(approvals)} approvals (required {min_approvals})",
                            "owning_team": team_map.get(repo_name, "Unknown"),
                        })

            # Check failed status checks
            if matching_rule["require_status_checks"]:
                required_checks = [
                    c.strip()
                    for c in (matching_rule["required_status_checks"] or "").split(",")
                    if c.strip()
                ]
                if required_checks:
                    result = json.loads(self.tools["get_status_check_results"](repo_id=repo_id, commit_sha=commit_sha)["content"][0]["text"])
                    tool_calls += 1
                    check_statuses = {c["check_name"]: c["status"] for c in result["checks"]}
                    failed_checks = [c for c in required_checks if check_statuses.get(c) == "failure"]
                    if failed_checks:
                        if not (merged_by in exempt_users and "failed_status_checks" in exempt_users.get(merged_by, [])):
                            violations.append({
                                "repo_name": repo_name,
                                "branch": branch,
                                "violation_type": "failed_status_checks",
                                "severity": violation_severities["failed_status_checks"],
                                "offending_user": merged_by,
                                "event_timestamp": merged_at,
                                "description": f"PR #{pr_number} merged with failing checks: {', '.join(failed_checks)}",
                                "owning_team": team_map.get(repo_name, "Unknown"),
                            })

            # Check admin override
            if is_admin_override and matching_rule["enforce_admins"]:
                if not (merged_by in exempt_users and "admin_override" in exempt_users.get(merged_by, [])):
                    violations.append({
                        "repo_name": repo_name,
                        "branch": branch,
                        "violation_type": "admin_override",
                        "severity": violation_severities["admin_override"],
                        "offending_user": merged_by,
                        "event_timestamp": merged_at,
                        "description": f"Admin {merged_by} bypassed enforce-admins on {branch}",
                        "owning_team": team_map.get(repo_name, "Unknown"),
                    })

        # 10. Sort violations
        violations.sort(
            key=lambda v: (-severity_weights[v["severity"]], v["event_timestamp"])
        )

        # 11. Write violation_report.csv
        report_path = os.path.join(self.workspace, "violation_report.csv")
        fieldnames = ["repo_name", "branch", "violation_type", "severity",
                       "offending_user", "event_timestamp", "description", "owning_team"]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for v in violations:
                writer.writerow(v)

        # 12. Compute summary
        by_severity = {}
        by_type = {}
        for v in violations:
            by_severity[v["severity"]] = by_severity.get(v["severity"], 0) + 1
            by_type[v["violation_type"]] = by_type.get(v["violation_type"], 0) + 1

        repo_counts = {}
        repo_scores = {}
        for v in violations:
            repo_counts[v["repo_name"]] = repo_counts.get(v["repo_name"], 0) + 1
            w = severity_weights[v["severity"]]
            repo_scores[v["repo_name"]] = repo_scores.get(v["repo_name"], 0) + w

        top_repos = sorted(repo_counts.items(), key=lambda x: (-x[1], x[0]))[:5]
        escalation_repos = sorted([r for r, s in repo_scores.items() if s >= escalation_threshold])

        summary = {
            "total_violations": len(violations),
            "by_severity": {s: by_severity.get(s, 0) for s in ["critical", "high", "medium", "low"]},
            "by_type": {t: by_type.get(t, 0) for t in ["force_push", "insufficient_reviews", "failed_status_checks", "admin_override"]},
            "top_offending_repos": [{"repo_name": r, "violation_count": c} for r, c in top_repos],
            "escalation_repos": escalation_repos,
        }

        summary_path = os.path.join(self.workspace, "executive_summary.json")
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        # 13. Build response text
        action = (
            f"Branch protection compliance audit complete. "
            f"Found {len(violations)} total violations across all repositories. "
            f"Force push violations: {by_type.get('force_push', 0)}. "
            f"Insufficient review violations: {by_type.get('insufficient_reviews', 0)}. "
            f"Failed status check violations: {by_type.get('failed_status_checks', 0)}. "
            f"Admin override violations: {by_type.get('admin_override', 0)}. "
            f"By severity: critical={by_severity.get('critical', 0)}, "
            f"high={by_severity.get('high', 0)}, medium={by_severity.get('medium', 0)}, "
            f"low={by_severity.get('low', 0)}. "
            f"Repositories flagged for escalation: {', '.join(escalation_repos) if escalation_repos else 'none'}. "
            f"Results saved to violation_report.csv and executive_summary.json."
        )

        assert tool_calls >= 15, f"Only {tool_calls} tool calls made, need at least 15"

        return self.step(action)
