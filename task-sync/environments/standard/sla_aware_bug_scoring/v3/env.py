"""
Environment for SLA-Aware Bug Triage Scoring task.
Defines tools for querying bug history, developer profiles, customer contracts,
and feature telemetry, plus evaluation logic.
"""

import csv
import json
import os
import sqlite3
import glob
import re
from typing import Any, Dict, List, Tuple

import yaml


# ── Tool decorator ───────────────────────────────────────────────────────────
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

    # ── OpenAI-format tool definitions ───────────────────────────────────
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

    # ═══════════════════════════════════════════════════════════════════════
    # Tool methods
    # ═══════════════════════════════════════════════════════════════════════

    @tool(
        description=(
            "Retrieve historical bug fix records for a given feature ID. "
            "Returns a list of past bugs including severity, fix time in hours, "
            "and the developer who resolved them. Limited to 20 records per call; "
            "use the offset parameter for pagination."
        ),
        parameters={
            "type": "object",
            "properties": {
                "feature_id": {
                    "type": "integer",
                    "description": "The feature ID to look up historical bugs for.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Pagination offset (default 0).",
                },
            },
            "required": ["feature_id"],
        },
    )
    def get_bug_fix_history(self, feature_id: int, offset: int = 0) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT bug_id, title, severity, component, fix_time_hours, "
            "developer_id, reported_date, resolved_date "
            "FROM bugs_history WHERE feature_id = ? "
            "ORDER BY bug_id LIMIT 20 OFFSET ?",
            (feature_id, offset),
        ).fetchall()
        conn.close()
        return {
            "feature_id": feature_id,
            "offset": offset,
            "records": [dict(r) for r in rows],
            "count": len(rows),
        }

    @tool(
        description=(
            "Get the profile of a single developer by their ID, including "
            "team, skills, experience years, and current workload."
        ),
        parameters={
            "type": "object",
            "properties": {
                "dev_id": {
                    "type": "integer",
                    "description": "Developer ID.",
                },
            },
            "required": ["dev_id"],
        },
    )
    def get_developer_profile(self, dev_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM developers WHERE dev_id = ?", (dev_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Developer {dev_id} not found."}
        return dict(row)

    @tool(
        description=(
            "List developers belonging to a specific team. Returns dev_id, "
            "name, skills, experience_years, max_concurrent_bugs, and "
            "active_bugs for each member."
        ),
        parameters={
            "type": "object",
            "properties": {
                "team": {
                    "type": "string",
                    "description": "Team name (e.g. 'security', 'billing').",
                },
            },
            "required": ["team"],
        },
    )
    def list_developers_by_team(self, team: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT dev_id, name, skills, experience_years, "
            "max_concurrent_bugs, active_bugs "
            "FROM developers WHERE team = ? ORDER BY dev_id",
            (team,),
        ).fetchall()
        conn.close()
        return {
            "team": team,
            "members": [dict(r) for r in rows],
            "count": len(rows),
        }

    @tool(
        description=(
            "Get contract and account details for a customer by their ID, "
            "including contract tier, annual revenue, industry, and support "
            "contact count."
        ),
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "integer",
                    "description": "Customer ID.",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_customer_contract(self, customer_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Customer {customer_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Get telemetry data for a feature by its ID: daily/monthly active "
            "users, error rate, revenue contribution, and module."
        ),
        parameters={
            "type": "object",
            "properties": {
                "feature_id": {
                    "type": "integer",
                    "description": "Feature ID.",
                },
            },
            "required": ["feature_id"],
        },
    )
    def get_feature_telemetry(self, feature_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM features WHERE feature_id = ?", (feature_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Feature {feature_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Search for developers whose skills contain a given keyword. "
            "Returns matching developer summaries."
        ),
        parameters={
            "type": "object",
            "properties": {
                "skill_keyword": {
                    "type": "string",
                    "description": "Skill keyword to search for (case-insensitive).",
                },
            },
            "required": ["skill_keyword"],
        },
    )
    def search_developers_by_skill(self, skill_keyword: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT dev_id, name, team, skills, experience_years, "
            "max_concurrent_bugs, active_bugs "
            "FROM developers WHERE LOWER(skills) LIKE ? ORDER BY dev_id",
            (f"%{skill_keyword.lower()}%",),
        ).fetchall()
        conn.close()
        return {
            "skill_keyword": skill_keyword,
            "matches": [dict(r) for r in rows],
            "count": len(rows),
        }

    @tool(
        description=(
            "Get summary statistics of historical bug fixes for a specific "
            "module: average fix time by severity, total bugs resolved, and "
            "most frequent developer."
        ),
        parameters={
            "type": "object",
            "properties": {
                "module_name": {
                    "type": "string",
                    "description": "Module/component name.",
                },
            },
            "required": ["module_name"],
        },
    )
    def get_module_bug_stats(self, module_name: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        # Average fix time by severity
        rows = conn.execute(
            "SELECT severity, AVG(fix_time_hours) as avg_fix, "
            "COUNT(*) as cnt FROM bugs_history WHERE component = ? "
            "GROUP BY severity",
            (module_name,),
        ).fetchall()
        stats_by_severity = {
            r[0]: {"avg_fix_hours": round(r[1], 2), "count": r[2]}
            for r in rows
        }
        # Most frequent developer
        top_dev = conn.execute(
            "SELECT developer_id, COUNT(*) as cnt FROM bugs_history "
            "WHERE component = ? GROUP BY developer_id "
            "ORDER BY cnt DESC LIMIT 1",
            (module_name,),
        ).fetchone()
        total = conn.execute(
            "SELECT COUNT(*) FROM bugs_history WHERE component = ?",
            (module_name,),
        ).fetchone()[0]
        conn.close()
        return {
            "module": module_name,
            "total_resolved": total,
            "stats_by_severity": stats_by_severity,
            "top_developer_id": top_dev[0] if top_dev else None,
            "top_developer_fixes": top_dev[1] if top_dev else 0,
        }

    @tool(
        description=(
            "List all features in the system with their IDs and daily active "
            "user counts. Returns paginated results; use offset to page through."
        ),
        parameters={
            "type": "object",
            "properties": {
                "offset": {
                    "type": "integer",
                    "description": "Pagination offset (default 0).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return (default 25).",
                },
            },
            "required": [],
        },
    )
    def list_features(self, offset: int = 0, limit: int = 25) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total_count = conn.execute(
            "SELECT COUNT(*) FROM features"
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT feature_id, feature_name, module, daily_active_users "
            "FROM features ORDER BY feature_id LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        conn.close()
        return {
            "offset": offset,
            "limit": limit,
            "total_count": total_count,
            "features": [dict(r) for r in rows],
            "returned": len(rows),
        }

    # ═══════════════════════════════════════════════════════════════════════
    # Evaluation
    # ═══════════════════════════════════════════════════════════════════════

    def _load_new_bugs(self) -> List[dict]:
        """Load all new bug reports from workspace (any format)."""
        bugs = []
        patterns = [
            os.path.join(self.workspace, "bug_report_*.json"),
            os.path.join(self.workspace, "bug_report_*.md"),
            os.path.join(self.workspace, "bug_report_*.yaml"),
            os.path.join(self.workspace, "bug_report_*.txt"),
        ]
        for pattern in patterns:
            for fpath in sorted(glob.glob(pattern)):
                ext = os.path.splitext(fpath)[1]
                with open(fpath) as f:
                    if ext == ".json":
                        data = json.load(f)
                    elif ext == ".yaml":
                        data = yaml.safe_load(f)
                    elif ext == ".md":
                        data = self._parse_md_bug(f.read())
                    elif ext == ".txt":
                        data = self._parse_txt_bug(f.read())
                    else:
                        continue
                bugs.append(data)
        return bugs

    @staticmethod
    def _parse_md_bug(text: str) -> dict:
        d = {}
        m = re.search(r"# Bug Report (NEW-\d+)", text)
        if m:
            d["bug_id"] = m.group(1)
        for key, field in [
            ("Title", "title"),
            ("Severity", "severity"),
            ("Module", "module"),
            ("Environment", "environment"),
            ("Reported Date", "reported_date"),
        ]:
            m = re.search(rf"\*\*{key}:\*\*\s*(.+)", text)
            if m:
                d[field] = m.group(1).strip()
        m = re.search(
            r"\*\*Affected Feature:\*\*\s*(.+?)\s*\(ID:\s*(\d+)\)", text
        )
        if m:
            d["affected_feature"] = m.group(1).strip()
            d["feature_id"] = int(m.group(2))
        m = re.search(
            r"\*\*Reported By:\*\*\s*(.+?)\s*\(Customer ID:\s*(\d+)\)", text
        )
        if m:
            d["reported_by_company"] = m.group(1).strip()
            d["reported_by_customer_id"] = int(m.group(2))
        return d

    @staticmethod
    def _parse_txt_bug(text: str) -> dict:
        d = {}
        m = re.search(r"BUG ID:\s*(NEW-\d+)", text)
        if m:
            d["bug_id"] = m.group(1)
        m = re.search(r"TITLE:\s*(.+)", text)
        if m:
            d["title"] = m.group(1).strip()
        m = re.search(r"SEVERITY:\s*(\w+)", text)
        if m:
            d["severity"] = m.group(1).strip()
        m = re.search(r"FEATURE:\s*(.+?)\s*\(ID:\s*(\d+)\)", text)
        if m:
            d["affected_feature"] = m.group(1).strip()
            d["feature_id"] = int(m.group(2))
        m = re.search(r"MODULE:\s*(\w+)", text)
        if m:
            d["module"] = m.group(1).strip()
        m = re.search(r"CUSTOMER:\s*(.+?)\s*\(ID:\s*(\d+)\)", text)
        if m:
            d["reported_by_company"] = m.group(1).strip()
            d["reported_by_customer_id"] = int(m.group(2))
        m = re.search(r"DATE:\s*(.+)", text)
        if m:
            d["reported_date"] = m.group(1).strip()
        return d

    def _load_dev_schedules(self) -> Dict[int, dict]:
        """Load developer schedule CSV files into a dict keyed by dev_id."""
        schedules = {}
        for fpath in sorted(
            glob.glob(os.path.join(self.workspace, "dev_schedule_week_*.csv"))
        ):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    did = int(row["dev_id"])
                    schedules[did] = {
                        "available_hours": int(row["available_hours_this_week"]),
                        "on_call": row["on_call"].strip().lower() == "yes",
                        "pto_days": int(row["pto_days"]),
                        "sprint_load_pct": int(row["current_sprint_load_pct"]),
                    }
        return schedules

    def _load_scoring_config(self) -> dict:
        with open(os.path.join(self.workspace, "priority_weights.json")) as f:
            return json.load(f)

    def _load_sla_config(self) -> dict:
        with open(os.path.join(self.workspace, "sla_config.yaml")) as f:
            return yaml.safe_load(f)

    def _load_team_mapping(self) -> dict:
        with open(
            os.path.join(self.workspace, "team_module_mapping.yaml")
        ) as f:
            return yaml.safe_load(f)

    def _compute_ground_truth(self):
        """Compute the full ground-truth triage queue."""
        bugs = self._load_new_bugs()
        scoring = self._load_scoring_config()
        sla_cfg = self._load_sla_config()
        team_map = self._load_team_mapping()
        dev_schedules = self._load_dev_schedules()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Preload all features for normalization
        all_features = conn.execute("SELECT * FROM features").fetchall()
        all_features = [dict(r) for r in all_features]
        max_dau = max(f["daily_active_users"] for f in all_features) if all_features else 1

        # Preload avg fix times per feature
        fix_stats = {}
        for row in conn.execute(
            "SELECT feature_id, AVG(fix_time_hours) as avg_fix "
            "FROM bugs_history GROUP BY feature_id"
        ).fetchall():
            fix_stats[row[0]] = row[1]
        all_fix_times = list(fix_stats.values())
        max_fix_time = max(all_fix_times) if all_fix_times else 1

        # Preload developers
        all_devs = conn.execute("SELECT * FROM developers").fetchall()
        all_devs = [dict(r) for r in all_devs]
        dev_by_id = {d["dev_id"]: d for d in all_devs}
        dev_by_team = {}
        for d in all_devs:
            dev_by_team.setdefault(d["team"], []).append(d)

        # Preload customers
        all_customers = conn.execute("SELECT * FROM customers").fetchall()
        cust_by_id = {r["customer_id"]: dict(r) for r in all_customers}

        feature_by_id = {f["feature_id"]: f for f in all_features}

        conn.close()

        sev_scores = scoring["severity_scores"]
        sla_scores = scoring["sla_urgency_scores"]
        w_sev = scoring["severity_weight"]
        w_sla = scoring["sla_urgency_weight"]
        w_feat = scoring["feature_impact_weight"]
        w_hist = scoring["historical_complexity_weight"]

        module_team = team_map["module_team_mapping"]
        assign_rules = team_map["assignment_rules"]

        results = []
        for bug in bugs:
            bug_id = bug.get("bug_id", "UNKNOWN")
            severity = bug.get("severity", "low").lower()
            feature_id = int(bug.get("feature_id", 0))
            customer_id = int(bug.get("reported_by_customer_id", 0))
            module = bug.get("module", "")

            # 1. Severity score
            sev_score = sev_scores.get(severity, 1.0)

            # 2. SLA urgency score
            cust = cust_by_id.get(customer_id, {})
            tier = cust.get("contract_tier", "bronze").lower()
            sla_score = sla_scores.get(tier, 2.0)

            # 3. Feature impact score
            feat = feature_by_id.get(feature_id, {})
            dau = feat.get("daily_active_users", 0)
            error_rate = feat.get("error_rate", 0)
            norm_dau = (dau / max_dau) * 10 if max_dau > 0 else 0
            feature_impact = norm_dau * (1 + error_rate * 10)

            # 4. Historical complexity score
            avg_fix = fix_stats.get(feature_id, max_fix_time)
            norm_fix = (avg_fix / max_fix_time) * 10 if max_fix_time > 0 else 0
            complexity_score = 10 - norm_fix  # higher = simpler = more urgent

            # Priority score
            priority = round(
                w_sev * sev_score
                + w_sla * sla_score
                + w_feat * feature_impact
                + w_hist * complexity_score,
                2,
            )

            # Assignee selection
            target_team = module_team.get(module, "backend")
            candidates = dev_by_team.get(target_team, [])

            best_dev = None
            best_score = -1
            for dev in candidates:
                did = dev["dev_id"]
                sched = dev_schedules.get(did, {})
                avail_hours = sched.get("available_hours", 0)
                pto = sched.get("pto_days", 5)
                sprint_load = sched.get("sprint_load_pct", 100)

                # Filter: must not exceed max_active_bugs_pct
                if dev["max_concurrent_bugs"] > 0:
                    load_ratio = dev["active_bugs"] / dev["max_concurrent_bugs"]
                else:
                    load_ratio = 1.0
                if load_ratio >= assign_rules["max_active_bugs_pct"]:
                    continue

                # Filter: for critical bugs, need min experience
                if severity == "critical" and assign_rules["prefer_experienced_for_critical"]:
                    if dev["experience_years"] < assign_rules["min_experience_years_for_critical"]:
                        continue

                # Filter: skip devs with 0 available hours or high PTO
                if avail_hours <= 0 or pto >= 4:
                    continue

                # Candidate score: lower active bugs better, higher experience better
                cand_score = (
                    (1 - load_ratio) * 50
                    + dev["experience_years"] * 3
                    + (40 - sprint_load) * 0.5
                    + avail_hours * 0.2
                )
                if cand_score > best_score:
                    best_score = cand_score
                    best_dev = dev

            # Fallback: if no candidate in target team, pick globally
            if best_dev is None:
                for dev in all_devs:
                    did = dev["dev_id"]
                    sched = dev_schedules.get(did, {})
                    avail_hours = sched.get("available_hours", 0)
                    pto = sched.get("pto_days", 5)
                    if dev["max_concurrent_bugs"] > 0:
                        load_ratio = dev["active_bugs"] / dev["max_concurrent_bugs"]
                    else:
                        load_ratio = 1.0
                    if load_ratio >= assign_rules["max_active_bugs_pct"]:
                        continue
                    if avail_hours <= 0 or pto >= 4:
                        continue
                    cand_score = (
                        (1 - load_ratio) * 50
                        + dev["experience_years"] * 3
                        + avail_hours * 0.2
                    )
                    if cand_score > best_score:
                        best_score = cand_score
                        best_dev = dev

            assignee_name = best_dev["name"] if best_dev else "UNASSIGNED"
            assignee_id = best_dev["dev_id"] if best_dev else -1

            # Estimated fix hours
            est_fix = round(avg_fix, 1) if feature_id in fix_stats else round(max_fix_time, 1)

            results.append({
                "bug_id": bug_id,
                "severity": severity,
                "sla_tier": tier,
                "priority_score": priority,
                "recommended_assignee": assignee_name,
                "recommended_assignee_id": assignee_id,
                "estimated_fix_hours": est_fix,
                "module": module,
            })

        # Sort by priority_score descending, then by bug_id ascending as tiebreaker
        results.sort(key=lambda x: (-x["priority_score"], x["bug_id"]))

        # Assign rank
        for i, r in enumerate(results, 1):
            r["priority_rank"] = i

        return results

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's
        final response.

        Returns a reward based on evaluation results.

        Args:
            action: The agent's final response.

        Returns:
            reward: The reward based on task completion (between 0.0 and 1.0).
            info: Evaluation results.
        """
        gt = self._compute_ground_truth()
        gt_by_id = {r["bug_id"]: r for r in gt}
        n_bugs = len(gt)

        criteria = {}
        total = 0
        max_total = 0

        # ── Criterion 1: triage_queue.csv exists and has correct columns (15 pts)
        c1_max = 15
        max_total += c1_max
        csv_path = os.path.join(self.workspace, "triage_queue.csv")
        expected_cols = [
            "bug_id", "priority_score", "priority_rank",
            "recommended_assignee", "sla_tier", "estimated_fix_hours",
        ]
        csv_rows = []
        if os.path.exists(csv_path):
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                csv_cols = [c.strip() for c in (reader.fieldnames or [])]
                csv_rows = list(reader)
            cols_ok = all(c in csv_cols for c in expected_cols)
            if cols_ok and len(csv_rows) == n_bugs:
                criteria["triage_csv_structure"] = {
                    "passed": True, "score": c1_max, "max_score": c1_max,
                }
                total += c1_max
            else:
                reason = ""
                if not cols_ok:
                    missing = [c for c in expected_cols if c not in csv_cols]
                    reason = f"Missing columns: {missing}. "
                if len(csv_rows) != n_bugs:
                    reason += f"Expected {n_bugs} rows, got {len(csv_rows)}."
                criteria["triage_csv_structure"] = {
                    "passed": False, "score": 0, "max_score": c1_max,
                    "reason": reason.strip(),
                }
        else:
            criteria["triage_csv_structure"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "triage_queue.csv not found.",
            }

        # ── Criterion 2: Priority scores within tolerance (20 pts)
        c2_max = 20
        max_total += c2_max
        if csv_rows:
            correct_scores = 0
            for row in csv_rows:
                bid = row.get("bug_id", "").strip()
                try:
                    ps = float(row.get("priority_score", -1))
                except (ValueError, TypeError):
                    continue
                gt_entry = gt_by_id.get(bid)
                if gt_entry and abs(ps - gt_entry["priority_score"]) < 0.15:
                    correct_scores += 1
            score_pct = correct_scores / n_bugs if n_bugs > 0 else 0
            earned = round(c2_max * score_pct)
            criteria["priority_scores_accuracy"] = {
                "passed": earned == c2_max,
                "score": earned,
                "max_score": c2_max,
                "reason": (
                    f"{correct_scores}/{n_bugs} scores within tolerance."
                    if earned < c2_max else ""
                ),
            }
            total += earned
        else:
            criteria["priority_scores_accuracy"] = {
                "passed": False, "score": 0, "max_score": c2_max,
                "reason": "No CSV rows to evaluate.",
            }

        # ── Criterion 3: Correct ranking order (15 pts)
        c3_max = 15
        max_total += c3_max
        if csv_rows:
            csv_order = [r.get("bug_id", "").strip() for r in csv_rows]
            gt_order = [r["bug_id"] for r in gt]
            if csv_order == gt_order:
                criteria["ranking_order"] = {
                    "passed": True, "score": c3_max, "max_score": c3_max,
                }
                total += c3_max
            else:
                # Partial credit: Kendall tau-like measure
                correct_pairs = 0
                total_pairs = 0
                gt_pos = {bid: i for i, bid in enumerate(gt_order)}
                for i in range(len(csv_order)):
                    for j in range(i + 1, len(csv_order)):
                        bi, bj = csv_order[i], csv_order[j]
                        if bi in gt_pos and bj in gt_pos:
                            total_pairs += 1
                            if gt_pos[bi] < gt_pos[bj]:
                                correct_pairs += 1
                pair_acc = correct_pairs / total_pairs if total_pairs > 0 else 0
                earned = round(c3_max * pair_acc)
                criteria["ranking_order"] = {
                    "passed": False, "score": earned, "max_score": c3_max,
                    "reason": f"Pairwise ordering accuracy: {pair_acc:.2%}",
                }
                total += earned
        else:
            criteria["ranking_order"] = {
                "passed": False, "score": 0, "max_score": c3_max,
                "reason": "No CSV rows.",
            }

        # ── Criterion 4: Recommended assignees correct (20 pts)
        c4_max = 20
        max_total += c4_max
        if csv_rows:
            correct_assignees = 0
            for row in csv_rows:
                bid = row.get("bug_id", "").strip()
                assignee = row.get("recommended_assignee", "").strip()
                gt_entry = gt_by_id.get(bid)
                if gt_entry and assignee == gt_entry["recommended_assignee"]:
                    correct_assignees += 1
            asgn_pct = correct_assignees / n_bugs if n_bugs > 0 else 0
            earned = round(c4_max * asgn_pct)
            criteria["assignee_accuracy"] = {
                "passed": earned == c4_max,
                "score": earned,
                "max_score": c4_max,
                "reason": (
                    f"{correct_assignees}/{n_bugs} assignees correct."
                    if earned < c4_max else ""
                ),
            }
            total += earned
        else:
            criteria["assignee_accuracy"] = {
                "passed": False, "score": 0, "max_score": c4_max,
                "reason": "No CSV rows.",
            }

        # ── Criterion 5: SLA tiers correct (10 pts)
        c5_max = 10
        max_total += c5_max
        if csv_rows:
            correct_sla = 0
            for row in csv_rows:
                bid = row.get("bug_id", "").strip()
                sla = row.get("sla_tier", "").strip().lower()
                gt_entry = gt_by_id.get(bid)
                if gt_entry and sla == gt_entry["sla_tier"]:
                    correct_sla += 1
            sla_pct = correct_sla / n_bugs if n_bugs > 0 else 0
            earned = round(c5_max * sla_pct)
            criteria["sla_tier_accuracy"] = {
                "passed": earned == c5_max,
                "score": earned,
                "max_score": c5_max,
                "reason": (
                    f"{correct_sla}/{n_bugs} SLA tiers correct."
                    if earned < c5_max else ""
                ),
            }
            total += earned
        else:
            criteria["sla_tier_accuracy"] = {
                "passed": False, "score": 0, "max_score": c5_max,
                "reason": "No CSV rows.",
            }

        # ── Criterion 6: Response contains top-3 bug summary (10 pts)
        c6_max = 10
        max_total += c6_max
        top3_ids = [r["bug_id"] for r in gt[:3]]
        found_top3 = sum(1 for bid in top3_ids if bid in action)
        if found_top3 == len(top3_ids):
            criteria["response_top3_summary"] = {
                "passed": True, "score": c6_max, "max_score": c6_max,
            }
            total += c6_max
        else:
            earned = round(c6_max * found_top3 / len(top3_ids)) if top3_ids else 0
            criteria["response_top3_summary"] = {
                "passed": False, "score": earned, "max_score": c6_max,
                "reason": f"Found {found_top3}/{len(top3_ids)} top bugs in response.",
            }
            total += earned

        # ── Criterion 7: estimated_fix_hours correct (10 pts)
        c7_max = 10
        max_total += c7_max
        if csv_rows:
            correct_est = 0
            for row in csv_rows:
                bid = row.get("bug_id", "").strip()
                try:
                    est = float(row.get("estimated_fix_hours", -1))
                except (ValueError, TypeError):
                    continue
                gt_entry = gt_by_id.get(bid)
                if gt_entry and abs(est - gt_entry["estimated_fix_hours"]) < 0.5:
                    correct_est += 1
            est_pct = correct_est / n_bugs if n_bugs > 0 else 0
            earned = round(c7_max * est_pct)
            criteria["estimated_fix_hours_accuracy"] = {
                "passed": earned == c7_max,
                "score": earned,
                "max_score": c7_max,
                "reason": (
                    f"{correct_est}/{n_bugs} fix hour estimates within tolerance."
                    if earned < c7_max else ""
                ),
            }
            total += earned
        else:
            criteria["estimated_fix_hours_accuracy"] = {
                "passed": False, "score": 0, "max_score": c7_max,
                "reason": "No CSV rows.",
            }

        reward = total / max_total if max_total > 0 else 0.0
        return reward, {
            "eval_criteria": criteria,
            "total_score": total,
            "max_score": max_total,
        }

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml as _yaml

        # ── Step 1: Read config files from workspace ─────────────────────
        with open(os.path.join(self.workspace, "priority_weights.json")) as f:
            scoring = json.load(f)
        with open(os.path.join(self.workspace, "sla_config.yaml")) as f:
            sla_cfg = _yaml.safe_load(f)
        with open(os.path.join(self.workspace, "team_module_mapping.yaml")) as f:
            team_cfg = _yaml.safe_load(f)

        module_team = team_cfg["module_team_mapping"]
        assign_rules = team_cfg["assignment_rules"]
        sev_scores = scoring["severity_scores"]
        sla_scores = scoring["sla_urgency_scores"]
        w_sev = scoring["severity_weight"]
        w_sla = scoring["sla_urgency_weight"]
        w_feat = scoring["feature_impact_weight"]
        w_hist = scoring["historical_complexity_weight"]

        # ── Step 2: Load new bug reports from workspace ──────────────────
        bugs = self._load_new_bugs()

        # ── Step 3: Load developer schedules from workspace ──────────────
        dev_schedules = self._load_dev_schedules()

        # ── Step 4: Gather data via tools ────────────────────────────────
        tool_call_count = 0

        # Collect all unique feature_ids and customer_ids from bugs
        bug_feature_ids = set()
        customer_ids = set()
        modules_needed = set()
        for bug in bugs:
            bug_feature_ids.add(int(bug.get("feature_id", 0)))
            customer_ids.add(int(bug.get("reported_by_customer_id", 0)))
            modules_needed.add(bug.get("module", ""))

        # ── Discover ALL features via list_features (for normalization) ──
        all_feature_summaries = []
        offset = 0
        while True:
            result = self.tools["list_features"](offset=offset, limit=25)
            tool_call_count += 1
            batch = result.get("features", [])
            all_feature_summaries.extend(batch)
            if len(batch) < 25 or offset + len(batch) >= result.get("total_count", 0):
                break
            offset += 25

        # Get detailed telemetry for bug-related features
        feature_data = {}
        for fid in bug_feature_ids:
            result = self.tools["get_feature_telemetry"](feature_id=fid)
            tool_call_count += 1
            if "error" not in result:
                feature_data[fid] = result

        # Max DAU from list_features (covers all features)
        all_dau_values = [f["daily_active_users"] for f in all_feature_summaries]
        max_dau = max(all_dau_values) if all_dau_values else 1

        # ── Get bug fix history per feature for avg fix time ─────────────
        all_feature_ids = [f["feature_id"] for f in all_feature_summaries]
        fix_times = {}
        for fid in all_feature_ids:
            result = self.tools["get_bug_fix_history"](feature_id=fid)
            tool_call_count += 1
            records = result.get("records", [])
            if records:
                avg_ft = sum(r["fix_time_hours"] for r in records) / len(records)
                fix_times[fid] = avg_ft

        all_fix_values = list(fix_times.values())
        max_fix_time = max(all_fix_values) if all_fix_values else 1

        # ── Get customer contracts ───────────────────────────────────────
        customer_data = {}
        for cid in customer_ids:
            result = self.tools["get_customer_contract"](customer_id=cid)
            tool_call_count += 1
            if "error" not in result:
                customer_data[cid] = result

        # ── Get developers by team ───────────────────────────────────────
        all_teams = set(module_team.values())
        team_devs = {}
        for team in all_teams:
            result = self.tools["list_developers_by_team"](team=team)
            tool_call_count += 1
            team_devs[team] = result.get("members", [])

        # ── Step 5: Compute priority scores ──────────────────────────────
        results = []
        for bug in bugs:
            bug_id = bug.get("bug_id", "UNKNOWN")
            severity = bug.get("severity", "low").lower()
            feature_id = int(bug.get("feature_id", 0))
            customer_id = int(bug.get("reported_by_customer_id", 0))
            module = bug.get("module", "")

            sev_score = sev_scores.get(severity, 1.0)

            cust = customer_data.get(customer_id, {})
            tier = cust.get("contract_tier", "bronze").lower()
            sla_score = sla_scores.get(tier, 2.0)

            feat = feature_data.get(feature_id, {})
            dau = feat.get("daily_active_users", 0)
            error_rate = feat.get("error_rate", 0)
            norm_dau = (dau / max_dau) * 10 if max_dau > 0 else 0
            feature_impact = norm_dau * (1 + error_rate * 10)

            avg_fix = fix_times.get(feature_id, max_fix_time)
            norm_fix = (avg_fix / max_fix_time) * 10 if max_fix_time > 0 else 0
            complexity_score = 10 - norm_fix

            priority = round(
                w_sev * sev_score
                + w_sla * sla_score
                + w_feat * feature_impact
                + w_hist * complexity_score,
                2,
            )

            # Assignee selection
            target_team = module_team.get(module, "backend")
            candidates = team_devs.get(target_team, [])

            best_dev = None
            best_score = -1
            for dev in candidates:
                did = dev["dev_id"]
                sched = dev_schedules.get(did, {})
                avail_hours = sched.get("available_hours", 0)
                pto = sched.get("pto_days", 5)
                sprint_load = sched.get("sprint_load_pct", 100)

                if dev["max_concurrent_bugs"] > 0:
                    load_ratio = dev["active_bugs"] / dev["max_concurrent_bugs"]
                else:
                    load_ratio = 1.0
                if load_ratio >= assign_rules["max_active_bugs_pct"]:
                    continue
                if severity == "critical" and assign_rules["prefer_experienced_for_critical"]:
                    if dev["experience_years"] < assign_rules["min_experience_years_for_critical"]:
                        continue
                if avail_hours <= 0 or pto >= 4:
                    continue

                cand_score = (
                    (1 - load_ratio) * 50
                    + dev["experience_years"] * 3
                    + (40 - sprint_load) * 0.5
                    + avail_hours * 0.2
                )
                if cand_score > best_score:
                    best_score = cand_score
                    best_dev = dev

            if best_dev is None:
                for team_name, devs in team_devs.items():
                    for dev in devs:
                        did = dev["dev_id"]
                        sched = dev_schedules.get(did, {})
                        avail_hours = sched.get("available_hours", 0)
                        pto = sched.get("pto_days", 5)
                        if dev["max_concurrent_bugs"] > 0:
                            load_ratio = dev["active_bugs"] / dev["max_concurrent_bugs"]
                        else:
                            load_ratio = 1.0
                        if load_ratio >= assign_rules["max_active_bugs_pct"]:
                            continue
                        if avail_hours <= 0 or pto >= 4:
                            continue
                        cand_score = (
                            (1 - load_ratio) * 50
                            + dev["experience_years"] * 3
                            + avail_hours * 0.2
                        )
                        if cand_score > best_score:
                            best_score = cand_score
                            best_dev = dev

            assignee_name = best_dev["name"] if best_dev else "UNASSIGNED"
            est_fix = round(avg_fix, 1) if feature_id in fix_times else round(max_fix_time, 1)

            results.append({
                "bug_id": bug_id,
                "severity": severity,
                "sla_tier": tier,
                "priority_score": priority,
                "recommended_assignee": assignee_name,
                "estimated_fix_hours": est_fix,
                "module": module,
            })

        results.sort(key=lambda x: (-x["priority_score"], x["bug_id"]))
        for i, r in enumerate(results, 1):
            r["priority_rank"] = i

        # ── Step 6: Write deliverables ───────────────────────────────────
        csv_path = os.path.join(self.workspace, "triage_queue.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "bug_id", "priority_score", "priority_rank",
                "recommended_assignee", "sla_tier", "estimated_fix_hours",
            ])
            writer.writeheader()
            for r in results:
                writer.writerow({
                    "bug_id": r["bug_id"],
                    "priority_score": r["priority_score"],
                    "priority_rank": r["priority_rank"],
                    "recommended_assignee": r["recommended_assignee"],
                    "sla_tier": r["sla_tier"],
                    "estimated_fix_hours": r["estimated_fix_hours"],
                })

        # ── Step 7: Build action string with top-3 summary ──────────────
        top3 = results[:3]
        action_lines = [
            "Weekly Bug Triage Queue Summary",
            f"Total new bugs triaged: {len(results)}",
            "",
            "Top 3 highest-priority bugs:",
        ]
        for r in top3:
            action_lines.append(
                f"  {r['bug_id']}: priority={r['priority_score']}, "
                f"assignee={r['recommended_assignee']}, "
                f"SLA={r['sla_tier']}, est_fix={r['estimated_fix_hours']}h"
            )
        action_lines.append("")
        action_lines.append(
            "Full ranked queue has been saved to triage_queue.csv."
        )
        action = "\n".join(action_lines)

        print(f"[verify] Tool calls made: {tool_call_count}")
        return self.step(action)
