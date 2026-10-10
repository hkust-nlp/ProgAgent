"""Task environment for code-review coverage audit."""

import csv
import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import pandas as pd

try:
    import yaml
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml", "-q"])
    import yaml


# --- Decorator (keep unchanged) ---
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

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _query(self, sql: str, params: tuple = ()) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def _load_repo_profiles(self) -> Dict[str, Dict]:
        """Read every repo_profiles_batch_* file and return
        {repo_name: {criticality_tier: int, required_min_reviewers: int}}.
        """
        profiles: Dict[str, Dict] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if not fname.startswith("repo_profiles_batch_"):
                continue
            fpath = os.path.join(self.workspace, fname)
            records: list = []

            if fname.endswith(".csv"):
                with open(fpath) as f:
                    for row in csv.DictReader(f):
                        records.append(row)

            elif fname.endswith(".json"):
                with open(fpath) as f:
                    records = json.load(f)

            elif fname.endswith(".yaml"):
                with open(fpath) as f:
                    records = yaml.safe_load(f) or []

            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    lines = f.readlines()
                if len(lines) > 2:
                    keys = [k.strip() for k in lines[0].split("|")]
                    for line in lines[2:]:
                        vals = [v.strip() for v in line.split("|")]
                        if len(vals) == len(keys):
                            records.append(dict(zip(keys, vals)))

            elif fname.endswith(".md"):
                with open(fpath) as f:
                    lines = f.readlines()
                if len(lines) > 2:
                    keys = [k.strip() for k in lines[0].split("|") if k.strip()]
                    for line in lines[2:]:
                        vals = [v.strip() for v in line.split("|") if v.strip()]
                        if len(vals) == len(keys):
                            records.append(dict(zip(keys, vals)))

            for rec in records:
                profiles[str(rec["repo_name"])] = {
                    "criticality_tier": int(rec["criticality_tier"]),
                    "required_min_reviewers": int(rec["required_min_reviewers"]),
                }
        return profiles

    # ------------------------------------------------------------------ #
    #  Tool methods                                                        #
    # ------------------------------------------------------------------ #

    @tool(
        description="List repositories with pagination. Returns repo_id, name, language, and team for each repository.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed. Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def list_repositories(self, page: int = 1, page_size: int = 20) -> Dict:
        offset = (page - 1) * page_size
        total = self._query("SELECT COUNT(*) AS cnt FROM repositories")[0]["cnt"]
        rows = self._query(
            "SELECT repo_id, name, language, team "
            "FROM repositories ORDER BY repo_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        return {
            "repositories": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }

    @tool(
        description="List all releases currently in pending-review status, with pagination.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed. Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def get_pending_releases(self, page: int = 1, page_size: int = 20) -> Dict:
        offset = (page - 1) * page_size
        total = self._query(
            "SELECT COUNT(*) AS cnt FROM releases WHERE status='pending_review'"
        )[0]["cnt"]
        rows = self._query(
            "SELECT release_id, repo_id, version, planned_date, status "
            "FROM releases WHERE status='pending_review' "
            "ORDER BY release_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        return {
            "releases": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }

    @tool(
        description="Get all pull requests that belong to a specific release.",
        parameters={
            "type": "object",
            "properties": {
                "release_id": {
                    "type": "integer",
                    "description": "The release ID to query pull requests for.",
                },
            },
            "required": ["release_id"],
        },
    )
    def get_pull_requests_for_release(self, release_id: int) -> Dict:
        rows = self._query(
            "SELECT pr_id, repo_id, release_id, title, author, "
            "lines_added, lines_deleted, files_changed, merged_at "
            "FROM pull_requests WHERE release_id=? ORDER BY pr_id",
            (int(release_id),),
        )
        return {"pull_requests": rows}

    @tool(
        description="Get all review comments for a specific pull request.",
        parameters={
            "type": "object",
            "properties": {
                "pr_id": {
                    "type": "integer",
                    "description": "The pull request ID.",
                },
            },
            "required": ["pr_id"],
        },
    )
    def get_review_comments_for_pr(self, pr_id: int) -> Dict:
        rows = self._query(
            "SELECT comment_id, pr_id, reviewer, comment_type, "
            "body_length, created_at "
            "FROM review_comments WHERE pr_id=? ORDER BY comment_id",
            (int(pr_id),),
        )
        return {"comments": rows}

    @tool(
        description="Get all static-analysis violations for a specific pull request.",
        parameters={
            "type": "object",
            "properties": {
                "pr_id": {
                    "type": "integer",
                    "description": "The pull request ID.",
                },
            },
            "required": ["pr_id"],
        },
    )
    def get_violations_for_pr(self, pr_id: int) -> Dict:
        rows = self._query(
            "SELECT violation_id, pr_id, rule_id, severity, "
            "file_path, resolved "
            "FROM static_analysis_violations WHERE pr_id=? "
            "ORDER BY violation_id",
            (int(pr_id),),
        )
        for r in rows:
            r["resolved"] = bool(r["resolved"])
        return {"violations": rows}

    @tool(
        description=(
            "Get per-release statistics for a repository. For every release "
            "of the given repo, returns release_id, version, status, "
            "total_prs (number of pull requests), and total_defects "
            "(number of defect escapes)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "integer",
                    "description": "The repository ID.",
                },
            },
            "required": ["repo_id"],
        },
    )
    def get_repo_release_stats(self, repo_id: int) -> Dict:
        releases = self._query(
            "SELECT release_id, version, status "
            "FROM releases WHERE repo_id=? ORDER BY release_id",
            (int(repo_id),),
        )
        stats = []
        for rel in releases:
            rid = rel["release_id"]
            pr_count = self._query(
                "SELECT COUNT(*) AS cnt FROM pull_requests WHERE release_id=?",
                (rid,),
            )[0]["cnt"]
            defect_count = self._query(
                "SELECT COUNT(*) AS cnt FROM defect_escapes WHERE release_id=?",
                (rid,),
            )[0]["cnt"]
            stats.append({
                "release_id": rid,
                "version": rel["version"],
                "status": rel["status"],
                "total_prs": pr_count,
                "total_defects": defect_count,
            })
        return {"release_stats": stats}

    # ------------------------------------------------------------------ #
    #  Ground-truth computation (shared by step & verify)                   #
    # ------------------------------------------------------------------ #

    def _compute_ground_truth(self):
        """Return {release_id: {…row dict…}} for every pending release."""
        conn = sqlite3.connect(self.db_path)
        repos_df = pd.read_sql("SELECT * FROM repositories", conn)
        releases_df = pd.read_sql("SELECT * FROM releases", conn)
        prs_df = pd.read_sql("SELECT * FROM pull_requests", conn)
        comments_df = pd.read_sql("SELECT * FROM review_comments", conn)
        violations_df = pd.read_sql("SELECT * FROM static_analysis_violations", conn)
        defects_df = pd.read_sql("SELECT * FROM defect_escapes", conn)
        conn.close()

        profiles = self._load_repo_profiles()

        with open(os.path.join(self.workspace, "review_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "severity_weights.json")) as f:
            sev_weights = json.load(f)

        repo_name_map = dict(zip(repos_df["repo_id"], repos_df["name"]))
        pending = releases_df[releases_df["status"] == "pending_review"].sort_values("release_id")

        gt: Dict[int, Dict] = {}
        for _, rel in pending.iterrows():
            rid = int(rel["release_id"])
            repo_id = int(rel["repo_id"])
            repo_name = repo_name_map[repo_id]
            version = rel["version"]

            prof = profiles.get(repo_name,
                                {"criticality_tier": 4, "required_min_reviewers": 1})
            tier = prof["criticality_tier"]
            min_rev = prof["required_min_reviewers"]
            tp = policy["tiers"][tier]

            rel_prs = prs_df[prs_df["release_id"] == rid]
            if len(rel_prs) == 0:
                rc, cd, wv = 1.0, 0.0, 0
            else:
                reviewed = 0
                total_lines = 0
                total_comments_count = 0
                total_wv = 0
                for _, pr in rel_prs.iterrows():
                    pid = int(pr["pr_id"])
                    author = pr["author"]
                    lines = int(pr["lines_added"]) + int(pr["lines_deleted"])
                    total_lines += lines

                    pc = comments_df[comments_df["pr_id"] == pid]
                    total_comments_count += len(pc)
                    unique_rev = set(
                        pc[pc["reviewer"] != author]["reviewer"]
                    )
                    if len(unique_rev) >= min_rev:
                        reviewed += 1

                    pv = violations_df[
                        (violations_df["pr_id"] == pid)
                        & (violations_df["resolved"] == 0)
                    ]
                    for _, v in pv.iterrows():
                        total_wv += sev_weights.get(v["severity"], 0)

                rc = reviewed / len(rel_prs)
                cd = (total_comments_count / total_lines
                      if total_lines > 0 else 0.0)
                wv = total_wv

            # defect escape rate
            repo_released = releases_df[
                (releases_df["repo_id"] == repo_id)
                & (releases_df["status"] == "released")
            ]
            rel_ids = repo_released["release_id"].tolist()
            hist_prs = len(prs_df[prs_df["release_id"].isin(rel_ids)])
            hist_def = len(defects_df[defects_df["release_id"].isin(rel_ids)])
            der = hist_def / hist_prs if hist_prs > 0 else 0.0

            failed = []
            if rc < tp["min_review_coverage"]:
                failed.append("review_coverage")
            if cd < tp["min_comment_density"]:
                failed.append("comment_density")
            if wv > tp["max_weighted_violations"]:
                failed.append("weighted_violations")
            if der > tp["max_defect_escape_rate"]:
                failed.append("defect_escape_rate")

            gt[rid] = {
                "release_id": rid,
                "repo_name": repo_name,
                "version": version,
                "criticality_tier": tier,
                "review_coverage": round(rc, 4),
                "comment_density": round(cd, 4),
                "weighted_violations": int(wv),
                "defect_escape_rate": round(der, 4),
                "decision": "GO" if not failed else "NO-GO",
                "failed_criteria": ";".join(failed) if failed else "none",
            }

        return gt

    # ------------------------------------------------------------------ #
    #  step                                                                #
    # ------------------------------------------------------------------ #

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
        eval_criteria: Dict[str, Dict] = {}

        # ---- C1: report file exists with correct headers (10 pts) ----
        report_path = os.path.join(self.workspace, "audit_report.csv")
        expected_cols = [
            "release_id", "repo_name", "version", "criticality_tier",
            "review_coverage", "comment_density", "weighted_violations",
            "defect_escape_rate", "decision", "failed_criteria",
        ]
        agent_rows: Dict[int, Dict] = {}
        c1 = False
        if os.path.exists(report_path):
            try:
                with open(report_path) as f:
                    reader = csv.DictReader(f)
                    if (reader.fieldnames
                            and set(expected_cols).issubset(set(reader.fieldnames))):
                        c1 = True
                        for row in reader:
                            agent_rows[int(row["release_id"])] = row
            except Exception:
                pass
        eval_criteria["report_format"] = {
            "passed": c1,
            "score": 10 if c1 else 0,
            "max_score": 10,
            "reason": "" if c1 else "audit_report.csv missing or wrong headers",
        }

        # ---- C2: correct row count (10 pts) ----
        c2 = len(agent_rows) == len(gt)
        eval_criteria["row_count"] = {
            "passed": c2,
            "score": 10 if c2 else 0,
            "max_score": 10,
            "reason": ("" if c2
                       else f"Expected {len(gt)} rows, got {len(agent_rows)}"),
        }

        # helper
        n_gt = len(gt) if gt else 1  # avoid /0

        def _num_check(field: str, max_pts: int, tol: float = 0.0011):
            correct = 0
            for rid, g in gt.items():
                if rid in agent_rows:
                    try:
                        if abs(float(agent_rows[rid][field]) - float(g[field])) < tol:
                            correct += 1
                    except Exception:
                        pass
            score = int(max_pts * correct / n_gt)
            return correct == len(gt), score, correct

        # ---- C3: review_coverage accuracy (20 pts) ----
        c3p, c3s, c3c = _num_check("review_coverage", 20)
        eval_criteria["review_coverage_accuracy"] = {
            "passed": c3p,
            "score": c3s,
            "max_score": 20,
            "reason": ("" if c3p
                       else f"{c3c}/{len(gt)} review_coverage values correct"),
        }

        # ---- C4: comment_density (10) + weighted_violations (10) = 20 pts ----
        c4a_p, c4a_s, _ = _num_check("comment_density", 10)
        c4b_correct = 0
        for rid, g in gt.items():
            if rid in agent_rows:
                try:
                    if int(float(agent_rows[rid]["weighted_violations"])) == g["weighted_violations"]:
                        c4b_correct += 1
                except Exception:
                    pass
        c4b_s = int(10 * c4b_correct / n_gt)
        c4p = c4a_p and (c4b_correct == len(gt))
        eval_criteria["density_violations_accuracy"] = {
            "passed": c4p,
            "score": c4a_s + c4b_s,
            "max_score": 20,
            "reason": ("" if c4p
                       else "Some comment_density or weighted_violations values incorrect"),
        }

        # ---- C5: defect_escape_rate accuracy (15 pts) ----
        c5p, c5s, c5c = _num_check("defect_escape_rate", 15)
        eval_criteria["defect_escape_rate_accuracy"] = {
            "passed": c5p,
            "score": c5s,
            "max_score": 15,
            "reason": ("" if c5p
                       else f"{c5c}/{len(gt)} defect_escape_rate values correct"),
        }

        # ---- C6: GO / NO-GO decisions (15 pts) ----
        c6_correct = 0
        for rid, g in gt.items():
            if rid in agent_rows:
                if agent_rows[rid].get("decision", "").strip().upper() == g["decision"]:
                    c6_correct += 1
        c6s = int(15 * c6_correct / n_gt)
        c6p = c6_correct == len(gt)
        eval_criteria["decisions_accuracy"] = {
            "passed": c6p,
            "score": c6s,
            "max_score": 15,
            "reason": ("" if c6p
                       else f"{c6_correct}/{len(gt)} decisions correct"),
        }

        # ---- C7: response summary (10 pts) ----
        go_ct = sum(1 for g in gt.values() if g["decision"] == "GO")
        nogo_ct = sum(1 for g in gt.values() if g["decision"] == "NO-GO")
        exp_summary = f"SUMMARY: {go_ct} GO, {nogo_ct} NO-GO"
        c7_sum = exp_summary in action
        c7_lines = all(
            f"Release {rid}: {g['decision']}" in action
            for rid, g in sorted(gt.items())
        )
        c7p = c7_sum and c7_lines
        eval_criteria["response_summary"] = {
            "passed": c7p,
            "score": 10 if c7p else 0,
            "max_score": 10,
            "reason": "" if c7p else "Response summary incomplete or incorrect",
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())
        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ------------------------------------------------------------------ #
    #  verify                                                              #
    # ------------------------------------------------------------------ #

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
        # 1. Read workspace config files
        profiles = self._load_repo_profiles()

        with open(os.path.join(self.workspace, "review_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "severity_weights.json")) as f:
            sev_weights = json.load(f)

        # 2. Get all repositories via tool
        repos: Dict[int, str] = {}
        page = 1
        while True:
            res = self.tools["list_repositories"](page=page, page_size=20)
            for r in res["repositories"]:
                repos[r["repo_id"]] = r["name"]
            if not res["has_more"]:
                break
            page += 1

        # 3. Get pending releases via tool
        pending: list = []
        page = 1
        while True:
            res = self.tools["get_pending_releases"](page=page, page_size=20)
            pending.extend(res["releases"])
            if not res["has_more"]:
                break
            page += 1

        # 4. Process each pending release
        report_rows: list = []
        for rel in sorted(pending, key=lambda x: x["release_id"]):
            release_id = rel["release_id"]
            repo_id = rel["repo_id"]
            version = rel["version"]
            repo_name = repos[repo_id]

            prof = profiles.get(
                repo_name,
                {"criticality_tier": 4, "required_min_reviewers": 1},
            )
            tier = prof["criticality_tier"]
            min_rev = prof["required_min_reviewers"]
            tp = policy["tiers"][tier]

            # Pull requests
            prs_res = self.tools["get_pull_requests_for_release"](
                release_id=release_id
            )
            prs = prs_res["pull_requests"]

            if not prs:
                rc, cd, wv = 1.0, 0.0, 0
            else:
                reviewed = 0
                total_lines = 0
                total_comments = 0
                total_wv = 0

                for pr in prs:
                    pr_id = pr["pr_id"]
                    author = pr["author"]
                    lines = pr["lines_added"] + pr["lines_deleted"]
                    total_lines += lines

                    # Review comments
                    c_res = self.tools["get_review_comments_for_pr"](pr_id=pr_id)
                    cmts = c_res["comments"]
                    total_comments += len(cmts)
                    unique_rev = set(
                        c["reviewer"] for c in cmts if c["reviewer"] != author
                    )
                    if len(unique_rev) >= min_rev:
                        reviewed += 1

                    # Violations
                    v_res = self.tools["get_violations_for_pr"](pr_id=pr_id)
                    for v in v_res["violations"]:
                        if not v["resolved"]:
                            total_wv += sev_weights.get(v["severity"], 0)

                rc = reviewed / len(prs)
                cd = total_comments / total_lines if total_lines > 0 else 0.0
                wv = total_wv

            # Defect escape rate
            stats_res = self.tools["get_repo_release_stats"](repo_id=repo_id)
            released = [
                s for s in stats_res["release_stats"] if s["status"] == "released"
            ]
            hist_prs = sum(s["total_prs"] for s in released)
            hist_def = sum(s["total_defects"] for s in released)
            der = hist_def / hist_prs if hist_prs > 0 else 0.0

            # Threshold comparison
            failed = []
            if rc < tp["min_review_coverage"]:
                failed.append("review_coverage")
            if cd < tp["min_comment_density"]:
                failed.append("comment_density")
            if wv > tp["max_weighted_violations"]:
                failed.append("weighted_violations")
            if der > tp["max_defect_escape_rate"]:
                failed.append("defect_escape_rate")

            decision = "GO" if not failed else "NO-GO"
            report_rows.append({
                "release_id": release_id,
                "repo_name": repo_name,
                "version": version,
                "criticality_tier": tier,
                "review_coverage": round(rc, 4),
                "comment_density": round(cd, 4),
                "weighted_violations": int(wv),
                "defect_escape_rate": round(der, 4),
                "decision": decision,
                "failed_criteria": ";".join(failed) if failed else "none",
            })

        # 5. Write audit_report.csv
        fields = [
            "release_id", "repo_name", "version", "criticality_tier",
            "review_coverage", "comment_density", "weighted_violations",
            "defect_escape_rate", "decision", "failed_criteria",
        ]
        report_path = os.path.join(self.workspace, "audit_report.csv")
        with open(report_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for row in report_rows:
                w.writerow(row)

        # 6. Build action string
        lines = [
            f"Release {r['release_id']}: {r['decision']}" for r in report_rows
        ]
        go = sum(1 for r in report_rows if r["decision"] == "GO")
        nogo = sum(1 for r in report_rows if r["decision"] == "NO-GO")
        lines.append(f"SUMMARY: {go} GO, {nogo} NO-GO")
        action = "\n".join(lines)

        return self.step(action)
