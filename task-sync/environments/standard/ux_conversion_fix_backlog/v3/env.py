#!/usr/bin/env python3
"""Task environment for UX conversion bottleneck analysis."""
import sqlite3
import os
import json
import csv
import glob
from typing import Tuple, Dict, List, Any

import yaml
import pandas as pd


# ── Decorator ──────────────────────────────────────────────────
def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ── Constants (must match data.py) ─────────────────────────────
PAGES = [
    "homepage", "search_results", "product_listing", "product_detail",
    "size_guide", "reviews", "cart", "checkout_shipping",
    "checkout_payment", "order_confirmation", "account_settings", "help_center",
]


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

    # ── Tool definitions (OpenAI format) ───────────────────────
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

    # ── Tools ──────────────────────────────────────────────────

    @tool(
        description="Returns the list of all page names tracked by the analytics platform.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_pages(self) -> dict:
        return {"pages": list(PAGES)}

    @tool(
        description=(
            "Retrieves error log entries for a specific page. "
            "Supports pagination via offset and limit. "
            "Returns errors with their id, session_id, error_type, severity, message, and timestamp."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page_name": {
                    "type": "string",
                    "description": "The page to retrieve errors for.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip (default 0).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return per call (default 50, max 100).",
                },
            },
            "required": ["page_name"],
        },
    )
    def get_page_errors(self, page_name: str, offset: int = 0, limit: int = 50) -> dict:
        limit = min(int(limit) if limit else 50, 100)
        offset = int(offset) if offset else 0
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(
            "SELECT COUNT(*) FROM error_logs WHERE page = ?", (page_name,)
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT error_id, session_id, error_type, severity, message, timestamp "
            "FROM error_logs WHERE page = ? ORDER BY error_id LIMIT ? OFFSET ?",
            (page_name, limit, offset),
        ).fetchall()
        conn.close()
        return {
            "page": page_name,
            "errors": [dict(r) for r in rows],
            "total_count": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total,
        }

    @tool(
        description=(
            "Retrieves rage-click events for a specific page. "
            "Supports pagination via offset and limit. "
            "Returns click_id, session_id, element, x_coord, y_coord, click_count, and timestamp."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page_name": {
                    "type": "string",
                    "description": "The page to retrieve rage-click data for.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip (default 0).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return per call (default 50, max 100).",
                },
            },
            "required": ["page_name"],
        },
    )
    def get_page_rage_clicks(self, page_name: str, offset: int = 0, limit: int = 50) -> dict:
        limit = min(int(limit) if limit else 50, 100)
        offset = int(offset) if offset else 0
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(
            "SELECT COUNT(*) FROM rage_clicks WHERE page = ?", (page_name,)
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT click_id, session_id, element, x_coord, y_coord, click_count, timestamp "
            "FROM rage_clicks WHERE page = ? ORDER BY click_id LIMIT ? OFFSET ?",
            (page_name, limit, offset),
        ).fetchall()
        conn.close()
        return {
            "page": page_name,
            "rage_clicks": [dict(r) for r in rows],
            "total_count": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total,
        }

    @tool(
        description="Returns the ordered list of funnel steps with their step_name and associated page.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_funnel_steps(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT DISTINCT step_name, page FROM funnel_events"
        ).fetchall()
        conn.close()
        # Read canonical order from the definition stored during data generation
        funnel_csv = os.path.join(self.workspace, "funnel_definition.csv")
        ordered = []
        if os.path.exists(funnel_csv):
            with open(funnel_csv, newline="") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    ordered.append({
                        "step_order": int(r["step_order"]),
                        "step_name": r["step_name"],
                        "page": r["page"],
                    })
        else:
            for r in rows:
                ordered.append({"step_name": r["step_name"], "page": r["page"]})
        return {"steps": ordered}

    @tool(
        description=(
            "Returns aggregate funnel metrics for a single step: "
            "total sessions entered, total completed, and the associated page."
        ),
        parameters={
            "type": "object",
            "properties": {
                "step_name": {
                    "type": "string",
                    "description": "Name of the funnel step to query.",
                },
            },
            "required": ["step_name"],
        },
    )
    def get_funnel_step_data(self, step_name: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT page, SUM(entered) AS total_entered, SUM(completed) AS total_completed "
            "FROM funnel_events WHERE step_name = ? GROUP BY page",
            (step_name,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"No data for step '{step_name}'."}
        return {
            "step_name": step_name,
            "page": row[0],
            "total_entered": int(row[1]),
            "total_completed": int(row[2]),
        }

    @tool(
        description="Returns the list of A/B test names available in the system.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_ab_tests(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT DISTINCT test_name FROM ab_assignments ORDER BY test_name"
        ).fetchall()
        conn.close()
        return {"tests": [r[0] for r in rows]}

    @tool(
        description=(
            "Returns per-variant aggregate metrics for a single A/B test on its target page: "
            "session count, error count, and rage-click count for variant A and variant B."
        ),
        parameters={
            "type": "object",
            "properties": {
                "test_name": {
                    "type": "string",
                    "description": "The A/B test name to query.",
                },
            },
            "required": ["test_name"],
        },
    )
    def get_ab_test_metrics(self, test_name: str) -> dict:
        # Read target page from workspace config
        ab_hyp_path = os.path.join(self.workspace, "ab_test_hypotheses.yaml")
        with open(ab_hyp_path) as f:
            ab_cfg = yaml.safe_load(f)
        test_info = ab_cfg["tests"].get(test_name)
        if test_info is None:
            return {"error": f"Unknown test '{test_name}'."}
        target_page = test_info["target_page"]

        conn = sqlite3.connect(self.db_path)
        result = {"test_name": test_name, "target_page": target_page}

        for variant in ["A", "B"]:
            # Users assigned to this variant
            user_rows = conn.execute(
                "SELECT user_id FROM ab_assignments WHERE test_name = ? AND variant = ?",
                (test_name, variant),
            ).fetchall()
            user_ids = [r[0] for r in user_rows]
            if not user_ids:
                result[f"variant_{variant.lower()}"] = {
                    "session_count": 0, "error_count": 0, "rage_click_count": 0,
                }
                continue

            placeholders = ",".join("?" * len(user_ids))

            # Sessions for those users
            sess_rows = conn.execute(
                f"SELECT session_id FROM sessions WHERE user_id IN ({placeholders})",
                user_ids,
            ).fetchall()
            sess_ids = [r[0] for r in sess_rows]
            sess_count = len(sess_ids)

            if not sess_ids:
                result[f"variant_{variant.lower()}"] = {
                    "session_count": 0, "error_count": 0, "rage_click_count": 0,
                }
                continue

            sp = ",".join("?" * len(sess_ids))
            err_count = conn.execute(
                f"SELECT COUNT(*) FROM error_logs WHERE session_id IN ({sp}) AND page = ?",
                sess_ids + [target_page],
            ).fetchone()[0]

            rage_count = conn.execute(
                f"SELECT COUNT(*) FROM rage_clicks WHERE session_id IN ({sp}) AND page = ?",
                sess_ids + [target_page],
            ).fetchone()[0]

            result[f"variant_{variant.lower()}"] = {
                "session_count": sess_count,
                "error_count": err_count,
                "rage_click_count": rage_count,
            }

        conn.close()
        return result

    # ── Ground-truth computation (shared by step & verify) ─────

    def _compute_ground_truth(self) -> dict:
        conn = sqlite3.connect(self.db_path)

        # Read workspace configs
        with open(os.path.join(self.workspace, "severity_weights.json")) as f:
            sev_weights = json.load(f)
        with open(os.path.join(self.workspace, "priority_config.yaml")) as f:
            config = yaml.safe_load(f)
        zones_df = pd.read_csv(os.path.join(self.workspace, "heatmap_zones.csv"))
        funnel_def = pd.read_csv(os.path.join(self.workspace, "funnel_definition.csv"))
        with open(os.path.join(self.workspace, "ab_test_hypotheses.yaml")) as f:
            ab_config = yaml.safe_load(f)

        weights = config["weights"]
        norm = config["normalization"]
        zone_wts = config["zone_weights"]
        bonus = config["confirmed_issue_bonus"]
        cap_confirmed = norm["confirmed_issue_cap"]

        # 1. Error scores per page
        errors_df = pd.read_sql("SELECT page, severity FROM error_logs", conn)
        error_scores: Dict[str, float] = {}
        for page in PAGES:
            pe = errors_df[errors_df["page"] == page]
            score = sum(sev_weights.get(str(row["severity"]), 0) for _, row in pe.iterrows())
            error_scores[page] = float(score)

        # 2. Rage-click scores per page
        rage_df = pd.read_sql(
            "SELECT page, x_coord, y_coord, click_count FROM rage_clicks", conn
        )
        rage_scores: Dict[str, float] = {}
        for page in PAGES:
            pc = rage_df[rage_df["page"] == page]
            pz = zones_df[zones_df["page"] == page]
            total = 0.0
            for _, click in pc.iterrows():
                matched = False
                for _, zone in pz.iterrows():
                    if (zone["x_min"] <= click["x_coord"] <= zone["x_max"]
                            and zone["y_min"] <= click["y_coord"] <= zone["y_max"]):
                        total += click["click_count"] * zone_wts.get(zone["zone_type"], 1.0)
                        matched = True
                        break
                if not matched:
                    total += click["click_count"] * 1.0
            rage_scores[page] = total

        # 3. Abandonment rates per funnel page
        funnel_events = pd.read_sql(
            "SELECT step_name, entered, completed FROM funnel_events", conn
        )
        abandonment_rates: Dict[str, float] = {}
        funnel_data: Dict[str, dict] = {}
        for _, row in funnel_def.iterrows():
            step = row["step_name"]
            page = row["page"]
            se = funnel_events[funnel_events["step_name"] == step]
            total_entered = int(se["entered"].sum())
            total_completed = int(se["completed"].sum())
            rate = 1.0 - (total_completed / total_entered) if total_entered > 0 else 0.0
            abandonment_rates[page] = rate
            funnel_data[step] = {
                "step_name": step,
                "page": page,
                "total_entered": total_entered,
                "total_completed": total_completed,
                "abandonment_rate": round(rate, 4),
                "target_conversion_rate": float(row["target_conversion_rate"]),
                "conversion_rate": round(1.0 - rate, 4),
            }

        # 4. A/B impact per target page
        sessions_db = pd.read_sql("SELECT session_id, user_id FROM sessions", conn)
        ab_assign_db = pd.read_sql(
            "SELECT user_id, test_name, variant FROM ab_assignments", conn
        )
        error_full = pd.read_sql("SELECT session_id, page FROM error_logs", conn)
        rage_full = pd.read_sql("SELECT session_id, page FROM rage_clicks", conn)

        ab_impacts: Dict[str, float] = {}
        ab_metrics: Dict[str, dict] = {}
        for test_name, test_info in ab_config["tests"].items():
            target_page = test_info["target_page"]
            ab_metrics[test_name] = {"target_page": target_page}
            for variant in ["A", "B"]:
                vusers = ab_assign_db[
                    (ab_assign_db["test_name"] == test_name)
                    & (ab_assign_db["variant"] == variant)
                ]["user_id"].tolist()
                vsess = sessions_db[sessions_db["user_id"].isin(vusers)][
                    "session_id"
                ].tolist()
                err_c = len(
                    error_full[
                        (error_full["session_id"].isin(vsess))
                        & (error_full["page"] == target_page)
                    ]
                )
                rage_c = len(
                    rage_full[
                        (rage_full["session_id"].isin(vsess))
                        & (rage_full["page"] == target_page)
                    ]
                )
                ab_metrics[test_name][f"variant_{variant.lower()}"] = {
                    "session_count": len(vsess),
                    "error_count": err_c,
                    "rage_click_count": rage_c,
                }
            va = ab_metrics[test_name]["variant_a"]
            vb = ab_metrics[test_name]["variant_b"]
            rate_a = (va["error_count"] + va["rage_click_count"]) / max(va["session_count"], 1)
            rate_b = (vb["error_count"] + vb["rage_click_count"]) / max(vb["session_count"], 1)
            ab_impacts[target_page] = abs(rate_a - rate_b)

        # 5. Confirmed issues from replay files
        confirmed_issues: Dict[str, int] = {p: 0 for p in PAGES}
        replay_files = sorted(
            glob.glob(os.path.join(self.workspace, "session_replay_batch_*.json"))
        )
        for fpath in replay_files:
            with open(fpath) as f:
                batch = json.load(f)
            for ann in batch["annotations"]:
                for issue in ann.get("issues_found", []):
                    if issue.get("confirmed_ux_issue", False):
                        p = issue["page"]
                        confirmed_issues[p] = confirmed_issues.get(p, 0) + 1

        # 6. Priority scores
        priority_scores: Dict[str, float] = {}
        for page in PAGES:
            es = error_scores.get(page, 0)
            rs = rage_scores.get(page, 0)
            ar = abandonment_rates.get(page, 0.0)
            ai = ab_impacts.get(page, 0.0)
            ci = confirmed_issues.get(page, 0)

            ne = min(es / norm["error_score_cap"], 1.0)
            nr = min(rs / norm["rage_click_score_cap"], 1.0)
            nab = min(ai, 1.0)
            nc = min(ci * bonus / cap_confirmed, 1.0)

            priority = (
                weights["error_score"] * ne
                + weights["rage_click_score"] * nr
                + weights["abandonment_rate"] * ar
                + weights["ab_impact"] * nab
                + weights["confirmed_issues"] * nc
            ) * 100
            priority_scores[page] = round(priority, 2)

        conn.close()

        # Overall funnel conversion
        step_order = list(funnel_def["step_name"])
        first_step = step_order[0]
        last_step = step_order[-1]
        overall_conv = 0.0
        if funnel_data[first_step]["total_entered"] > 0:
            overall_conv = (
                funnel_data[last_step]["total_completed"]
                / funnel_data[first_step]["total_entered"]
            )

        return {
            "error_scores": error_scores,
            "rage_scores": rage_scores,
            "abandonment_rates": abandonment_rates,
            "ab_impacts": ab_impacts,
            "confirmed_issues": confirmed_issues,
            "priority_scores": priority_scores,
            "funnel_data": funnel_data,
            "funnel_step_order": step_order,
            "overall_conversion_rate": round(overall_conv, 4),
        }

    # ── Evaluation ─────────────────────────────────────────────

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
        criteria: Dict[str, dict] = {}

        # ── 1. ux_backlog.csv exists & has correct columns (10 pts) ──
        backlog_path = os.path.join(self.workspace, "ux_backlog.csv")
        expected_cols = [
            "page_name", "error_score", "rage_click_score",
            "abandonment_rate", "ab_impact_score", "confirmed_issues",
            "priority_score", "recommended_action",
        ]
        backlog_df = None
        if os.path.exists(backlog_path):
            try:
                backlog_df = pd.read_csv(backlog_path)
                cols_ok = all(c in backlog_df.columns for c in expected_cols)
            except Exception:
                cols_ok = False
        else:
            cols_ok = False
        criteria["backlog_file_format"] = {
            "passed": cols_ok,
            "score": 10 if cols_ok else 0,
            "max_score": 10,
            "reason": "" if cols_ok else "ux_backlog.csv missing or wrong columns",
        }

        # ── 2. All pages present in backlog (10 pts) ──
        pages_ok = False
        if backlog_df is not None and cols_ok:
            present = set(backlog_df["page_name"].tolist())
            pages_ok = set(PAGES).issubset(present)
        criteria["backlog_pages_complete"] = {
            "passed": pages_ok,
            "score": 10 if pages_ok else 0,
            "max_score": 10,
            "reason": "" if pages_ok else "Not all pages present in backlog",
        }

        # ── 3. Priority scores accuracy (25 pts) ──
        ps_correct = 0
        if backlog_df is not None and cols_ok:
            agent_ps = dict(
                zip(backlog_df["page_name"], backlog_df["priority_score"])
            )
            for page in PAGES:
                expected = gt["priority_scores"][page]
                actual = agent_ps.get(page)
                if actual is not None:
                    tol = max(abs(expected) * 0.05, 2.0)
                    if abs(float(actual) - expected) <= tol:
                        ps_correct += 1
        ps_score = round(25 * ps_correct / len(PAGES), 2)
        criteria["priority_scores_accuracy"] = {
            "passed": ps_correct == len(PAGES),
            "score": ps_score,
            "max_score": 25,
            "reason": f"{ps_correct}/{len(PAGES)} pages within tolerance",
        }

        # ── 4. Backlog ranking top-5 (15 pts) ──
        rank_score = 0
        if backlog_df is not None and cols_ok:
            gt_ranking = sorted(
                gt["priority_scores"].items(), key=lambda x: -x[1]
            )
            gt_top5 = [p for p, _ in gt_ranking[:5]]
            agent_ranking = backlog_df.sort_values(
                "priority_score", ascending=False
            )["page_name"].tolist()[:5]
            for i in range(min(5, len(agent_ranking))):
                if i < len(gt_top5) and agent_ranking[i] == gt_top5[i]:
                    rank_score += 3
        criteria["backlog_ranking_top5"] = {
            "passed": rank_score == 15,
            "score": rank_score,
            "max_score": 15,
            "reason": f"{rank_score}/15 ranking points",
        }

        # ── 5. funnel_report.json structure (10 pts) ──
        funnel_path = os.path.join(self.workspace, "funnel_report.json")
        funnel_ok = False
        funnel_json = None
        if os.path.exists(funnel_path):
            try:
                with open(funnel_path) as f:
                    funnel_json = json.load(f)
                if (
                    "steps" in funnel_json
                    and isinstance(funnel_json["steps"], list)
                    and len(funnel_json["steps"]) == len(gt["funnel_step_order"])
                    and "overall_conversion_rate" in funnel_json
                ):
                    required_keys = {
                        "step_name", "page", "total_entered",
                        "total_completed", "abandonment_rate",
                        "target_conversion_rate", "conversion_rate",
                    }
                    funnel_ok = all(
                        required_keys.issubset(set(s.keys()))
                        for s in funnel_json["steps"]
                    )
            except Exception:
                pass
        criteria["funnel_report_structure"] = {
            "passed": funnel_ok,
            "score": 10 if funnel_ok else 0,
            "max_score": 10,
            "reason": "" if funnel_ok else "funnel_report.json missing or malformed",
        }

        # ── 6. Abandonment rates accuracy (15 pts) ──
        ar_correct = 0
        n_steps = len(gt["funnel_step_order"])
        if funnel_json and funnel_ok:
            agent_steps = {s["step_name"]: s for s in funnel_json["steps"]}
            for step_name in gt["funnel_step_order"]:
                gt_rate = gt["funnel_data"][step_name]["abandonment_rate"]
                a_step = agent_steps.get(step_name)
                if a_step:
                    try:
                        a_rate = float(a_step["abandonment_rate"])
                        if abs(a_rate - gt_rate) <= 0.02:
                            ar_correct += 1
                    except (TypeError, ValueError):
                        pass
        ar_score = round(15 * ar_correct / max(n_steps, 1), 2)
        criteria["abandonment_rates_accuracy"] = {
            "passed": ar_correct == n_steps,
            "score": ar_score,
            "max_score": 15,
            "reason": f"{ar_correct}/{n_steps} steps within tolerance",
        }

        # ── 7. Top-3 pages in response (15 pts) ──
        gt_ranking_all = sorted(
            gt["priority_scores"].items(), key=lambda x: -x[1]
        )
        gt_top3 = [p for p, _ in gt_ranking_all[:3]]
        top3_score = 0
        if action:
            for p in gt_top3:
                if p in action:
                    top3_score += 5
        criteria["top3_in_response"] = {
            "passed": top3_score == 15,
            "score": top3_score,
            "max_score": 15,
            "reason": f"Found {top3_score // 5}/3 top pages in response",
        }

        total = sum(c["score"] for c in criteria.values())
        max_total = sum(c["max_score"] for c in criteria.values())
        return total / max_total, {
            "eval_criteria": criteria,
            "total_score": total,
            "max_score": max_total,
        }

    # ── Self-verification ──────────────────────────────────────

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
        tool_calls = 0

        # ---- 1. Read workspace config files ----
        with open(os.path.join(self.workspace, "priority_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "severity_weights.json")) as f:
            sev_weights = json.load(f)
        zones_df = pd.read_csv(os.path.join(self.workspace, "heatmap_zones.csv"))
        funnel_def_df = pd.read_csv(os.path.join(self.workspace, "funnel_definition.csv"))
        with open(os.path.join(self.workspace, "ab_test_hypotheses.yaml")) as f:
            ab_config = yaml.safe_load(f)
        # scoring_methodology.md is informational — already encoded in logic below

        weights = config["weights"]
        norm_cfg = config["normalization"]
        zone_wts = config["zone_weights"]
        bonus = config["confirmed_issue_bonus"]
        cap_confirmed = norm_cfg["confirmed_issue_cap"]

        # ---- 2. Read session replay annotations (confirmed issues) ----
        confirmed_issues: Dict[str, int] = {}
        replay_files = sorted(
            glob.glob(os.path.join(self.workspace, "session_replay_batch_*.json"))
        )
        for fpath in replay_files:
            with open(fpath) as f:
                batch = json.load(f)
            for ann in batch["annotations"]:
                for issue in ann.get("issues_found", []):
                    if issue.get("confirmed_ux_issue", False):
                        p = issue["page"]
                        confirmed_issues[p] = confirmed_issues.get(p, 0) + 1

        # ---- 3. List pages via tool ----
        pages_result = self.tools["list_pages"]()
        tool_calls += 1
        pages = pages_result["pages"]

        # ---- 4. Error scores per page ----
        error_scores: Dict[str, float] = {}
        for page in pages:
            all_errors = []
            offset = 0
            while True:
                result = self.tools["get_page_errors"](
                    page_name=page, offset=offset, limit=50
                )
                tool_calls += 1
                all_errors.extend(result["errors"])
                if not result["has_more"]:
                    break
                offset += 50
            score = sum(sev_weights.get(e["severity"], 0) for e in all_errors)
            error_scores[page] = float(score)

        # ---- 5. Rage-click scores per page ----
        rage_scores: Dict[str, float] = {}
        for page in pages:
            all_clicks = []
            offset = 0
            while True:
                result = self.tools["get_page_rage_clicks"](
                    page_name=page, offset=offset, limit=50
                )
                tool_calls += 1
                all_clicks.extend(result["rage_clicks"])
                if not result["has_more"]:
                    break
                offset += 50
            page_zones = zones_df[zones_df["page"] == page]
            total = 0.0
            for click in all_clicks:
                matched = False
                for _, zone in page_zones.iterrows():
                    if (zone["x_min"] <= click["x_coord"] <= zone["x_max"]
                            and zone["y_min"] <= click["y_coord"] <= zone["y_max"]):
                        total += click["click_count"] * zone_wts.get(
                            zone["zone_type"], 1.0
                        )
                        matched = True
                        break
                if not matched:
                    total += click["click_count"] * 1.0
            rage_scores[page] = total

        # ---- 6. Funnel step data ----
        steps_result = self.tools["list_funnel_steps"]()
        tool_calls += 1
        funnel_steps = steps_result["steps"]

        abandonment_rates: Dict[str, float] = {}
        funnel_report_steps = []

        # Build target conversion rate lookup
        target_rates = {}
        for _, r in funnel_def_df.iterrows():
            target_rates[r["step_name"]] = float(r["target_conversion_rate"])

        for step_info in funnel_steps:
            sname = step_info["step_name"]
            sdata = self.tools["get_funnel_step_data"](step_name=sname)
            tool_calls += 1
            t_entered = sdata["total_entered"]
            t_completed = sdata["total_completed"]
            a_rate = 1.0 - (t_completed / t_entered) if t_entered > 0 else 0.0
            abandonment_rates[sdata["page"]] = a_rate
            funnel_report_steps.append({
                "step_name": sname,
                "page": sdata["page"],
                "total_entered": t_entered,
                "total_completed": t_completed,
                "abandonment_rate": round(a_rate, 4),
                "target_conversion_rate": target_rates.get(sname, 0.0),
                "conversion_rate": round(1.0 - a_rate, 4),
            })

        # Overall conversion
        if funnel_report_steps:
            overall_conv = round(
                funnel_report_steps[-1]["total_completed"]
                / funnel_report_steps[0]["total_entered"],
                4,
            ) if funnel_report_steps[0]["total_entered"] > 0 else 0.0
        else:
            overall_conv = 0.0

        # ---- 7. A/B impact ----
        ab_tests_result = self.tools["list_ab_tests"]()
        tool_calls += 1

        # Map: target_page -> ab_impact
        ab_impacts: Dict[str, float] = {}
        for tname in ab_tests_result["tests"]:
            metrics = self.tools["get_ab_test_metrics"](test_name=tname)
            tool_calls += 1
            va = metrics["variant_a"]
            vb = metrics["variant_b"]
            rate_a = (va["error_count"] + va["rage_click_count"]) / max(
                va["session_count"], 1
            )
            rate_b = (vb["error_count"] + vb["rage_click_count"]) / max(
                vb["session_count"], 1
            )
            ab_impacts[metrics["target_page"]] = abs(rate_a - rate_b)

        # ---- 8. Compute priority scores ----
        backlog_rows = []
        for page in pages:
            es = error_scores.get(page, 0)
            rs = rage_scores.get(page, 0)
            ar = abandonment_rates.get(page, 0.0)
            ai = ab_impacts.get(page, 0.0)
            ci = confirmed_issues.get(page, 0)

            ne = min(es / norm_cfg["error_score_cap"], 1.0)
            nr = min(rs / norm_cfg["rage_click_score_cap"], 1.0)
            nab = min(ai, 1.0)
            nc = min(ci * bonus / cap_confirmed, 1.0)

            priority = (
                weights["error_score"] * ne
                + weights["rage_click_score"] * nr
                + weights["abandonment_rate"] * ar
                + weights["ab_impact"] * nab
                + weights["confirmed_issues"] * nc
            ) * 100
            priority = round(priority, 2)

            # Determine dominant component for recommended action
            components = {
                "error": weights["error_score"] * ne,
                "rage_click": weights["rage_click_score"] * nr,
                "abandonment": weights["abandonment_rate"] * ar,
                "ab_variant": weights["ab_impact"] * nab,
                "confirmed_ux": weights["confirmed_issues"] * nc,
            }
            dominant = max(components, key=components.get)
            action_map = {
                "error": "Resolve high-severity errors on this page",
                "rage_click": "Redesign interactive elements causing rage clicks",
                "abandonment": "Simplify flow to reduce funnel abandonment",
                "ab_variant": "Adopt better-performing A/B variant",
                "confirmed_ux": "Address confirmed UX issues from session replays",
            }
            rec = action_map[dominant]

            backlog_rows.append({
                "page_name": page,
                "error_score": round(es, 2),
                "rage_click_score": round(rs, 2),
                "abandonment_rate": round(ar, 4),
                "ab_impact_score": round(ai, 4),
                "confirmed_issues": ci,
                "priority_score": priority,
                "recommended_action": rec,
            })

        # Sort by priority_score descending
        backlog_rows.sort(key=lambda r: -r["priority_score"])

        # ---- 9. Write deliverables ----
        backlog_path = os.path.join(self.workspace, "ux_backlog.csv")
        with open(backlog_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "page_name", "error_score", "rage_click_score",
                "abandonment_rate", "ab_impact_score", "confirmed_issues",
                "priority_score", "recommended_action",
            ])
            writer.writeheader()
            writer.writerows(backlog_rows)

        funnel_report = {
            "steps": funnel_report_steps,
            "overall_conversion_rate": overall_conv,
        }
        funnel_path = os.path.join(self.workspace, "funnel_report.json")
        with open(funnel_path, "w") as f:
            json.dump(funnel_report, f, indent=2)

        # ---- 10. Build action string ----
        top3 = backlog_rows[:3]
        action_lines = ["Top 3 priority pages for UX fixes:\n"]
        for row in top3:
            # Identify dominant component
            action_lines.append(
                f"- {row['page_name']}: priority_score = {row['priority_score']:.2f}. "
                f"{row['recommended_action']}."
            )
        action_str = "\n".join(action_lines)

        assert tool_calls >= 15, f"Only {tool_calls} tool calls made"
        return self.step(action_str)
