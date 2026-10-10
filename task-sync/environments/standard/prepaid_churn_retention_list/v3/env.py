#!/usr/bin/env python3
"""Environment for prepaid subscriber retention task."""

import csv
import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

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
    #  Helper: DB access                                                   #
    # ------------------------------------------------------------------ #

    def _query_db(self, query, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(query, params).fetchall()]
        conn.close()
        return rows

    # ------------------------------------------------------------------ #
    #  Tools                                                               #
    # ------------------------------------------------------------------ #

    @tool(
        description=(
            "List subscribers with pagination. Returns up to 20 subscribers per page "
            "with basic profile information including subscriber_id, name, phone, "
            "region, plan_type, account_status, registration_date, and monthly_arpu."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed.",
                },
            },
            "required": ["page"],
        },
    )
    def list_subscribers(self, page: int):
        page_size = 20
        offset = (page - 1) * page_size
        rows = self._query_db(
            "SELECT subscriber_id, name, phone, region, plan_type, "
            "account_status, registration_date, monthly_arpu "
            "FROM subscribers ORDER BY subscriber_id LIMIT ? OFFSET ?",
            (page_size + 1, offset),
        )
        has_more = len(rows) > page_size
        if has_more:
            rows = rows[:page_size]
        total = self._query_db("SELECT COUNT(*) AS cnt FROM subscribers")[0]["cnt"]
        return {
            "subscribers": rows,
            "page": page,
            "page_size": page_size,
            "total_count": total,
            "has_more": has_more,
        }

    @tool(
        description=(
            "Get monthly usage metrics for a subscriber over the last 6 months. "
            "Returns voice call counts, voice minutes, and SMS counts aggregated "
            "by calendar month."
        ),
        parameters={
            "type": "object",
            "properties": {
                "subscriber_id": {
                    "type": "string",
                    "description": "Subscriber identifier, e.g. 'SUB_0001'.",
                },
            },
            "required": ["subscriber_id"],
        },
    )
    def get_usage_metrics(self, subscriber_id: str):
        rows = self._query_db(
            "SELECT strftime('%Y-%m', call_date) AS month, "
            "SUM(CASE WHEN call_type IN ('voice_outgoing','voice_incoming') "
            "    THEN 1 ELSE 0 END) AS voice_calls, "
            "SUM(CASE WHEN call_type IN ('voice_outgoing','voice_incoming') "
            "    THEN duration_seconds ELSE 0 END) AS voice_seconds, "
            "SUM(CASE WHEN call_type IN ('sms_outgoing','sms_incoming') "
            "    THEN 1 ELSE 0 END) AS sms_count "
            "FROM call_detail_records WHERE subscriber_id = ? "
            "GROUP BY strftime('%Y-%m', call_date) ORDER BY month",
            (subscriber_id,),
        )
        return {
            "subscriber_id": subscriber_id,
            "monthly_metrics": [
                {
                    "month": r["month"],
                    "voice_calls": r["voice_calls"],
                    "voice_minutes": round(r["voice_seconds"] / 60.0, 2),
                    "sms_count": r["sms_count"],
                }
                for r in rows
            ],
        }

    @tool(
        description=(
            "Get top-up transaction history for a subscriber. Returns all "
            "top-up records with date, amount, channel, and resulting balance."
        ),
        parameters={
            "type": "object",
            "properties": {
                "subscriber_id": {
                    "type": "string",
                    "description": "Subscriber identifier.",
                },
            },
            "required": ["subscriber_id"],
        },
    )
    def get_topup_history(self, subscriber_id: str):
        rows = self._query_db(
            "SELECT topup_date, amount, channel, balance_after "
            "FROM topup_transactions WHERE subscriber_id = ? ORDER BY topup_date",
            (subscriber_id,),
        )
        return {"subscriber_id": subscriber_id, "transactions": rows}

    @tool(
        description=(
            "Get service interaction records for a subscriber. Returns interaction "
            "metadata: date, channel, category, sentiment score, resolution status, "
            "and agent ID. Does not include verbatim notes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "subscriber_id": {
                    "type": "string",
                    "description": "Subscriber identifier.",
                },
            },
            "required": ["subscriber_id"],
        },
    )
    def get_service_interactions(self, subscriber_id: str):
        rows = self._query_db(
            "SELECT interaction_id, interaction_date, channel, category, "
            "sentiment_score, resolution, agent_id "
            "FROM service_interactions WHERE subscriber_id = ? "
            "ORDER BY interaction_date",
            (subscriber_id,),
        )
        return {"subscriber_id": subscriber_id, "interactions": rows}

    # ------------------------------------------------------------------ #
    #  Scoring helpers (shared by step & verify)                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _period_months(analysis_date: datetime, recent_n: int, historical_n: int):
        """Return (set_of_recent_month_strings, set_of_historical_month_strings)."""
        recent, historical = set(), set()
        for i in range(1, recent_n + 1):
            m, y = analysis_date.month - i, analysis_date.year
            while m <= 0:
                m += 12; y -= 1
            recent.add(f"{y:04d}-{m:02d}")
        for i in range(recent_n + 1, recent_n + historical_n + 1):
            m, y = analysis_date.month - i, analysis_date.year
            while m <= 0:
                m += 12; y -= 1
            historical.add(f"{y:04d}-{m:02d}")
        return recent, historical

    @staticmethod
    def _bracket_score(value, thresholds_dict):
        """Map decline-pct to 0/0.4/0.7/1.0 using severe/moderate/mild keys."""
        if value <= thresholds_dict["severe"]:
            return 1.0
        if value <= thresholds_dict["moderate"]:
            return 0.7
        if value <= thresholds_dict["mild"]:
            return 0.4
        return 0.0

    @staticmethod
    def _sentiment_bracket(value, thresholds_dict):
        if value <= thresholds_dict["very_negative"]:
            return 1.0
        if value <= thresholds_dict["negative"]:
            return 0.7
        if value <= thresholds_dict["neutral"]:
            return 0.4
        return 0.0

    def _load_workspace_context(self):
        """Load all workspace config/data files. Returns a dict of parsed objects."""
        ctx = {}
        with open(os.path.join(self.workspace, "retention_scoring_config.yaml")) as f:
            ctx["config"] = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "risk_classification_rules.json")) as f:
            ctx["rules"] = json.load(f)

        ctx["offer_matrix"] = {}
        with open(os.path.join(self.workspace, "offer_matrix.csv")) as f:
            for row in csv.DictReader(f):
                ctx["offer_matrix"][(row["primary_risk_factor"], row["plan_type"])] = row["recommended_offer"]

        ctx["survey_data"] = {}
        ctx["competitor_campaigns"] = []
        for fname in sorted(os.listdir(self.workspace)):
            fpath = os.path.join(self.workspace, fname)
            if fname.startswith("feedback_survey_batch_") and fname.endswith(".json"):
                with open(fpath) as f:
                    for resp in json.load(f).get("survey_responses", []):
                        ctx["survey_data"].setdefault(resp["subscriber_id"], []).append(resp)
            elif fname.startswith("competitor_campaign_") and fname.endswith(".yaml"):
                with open(fpath) as f:
                    data = yaml.safe_load(f)
                    ctx["competitor_campaigns"].extend(data.get("campaigns", []))
        return ctx

    def _score_subscriber(self, sub, usage_data, topup_data, interaction_data, ctx):
        """Score a single subscriber. Returns dict with all fields or None if ineligible."""
        config = ctx["config"]
        rules = ctx["rules"]
        analysis_date = datetime.strptime(config["analysis_date"], "%Y-%m-%d")

        # Eligibility
        if sub["account_status"] not in rules["eligible_statuses"]:
            return None
        reg_date = datetime.strptime(sub["registration_date"], "%Y-%m-%d")
        if (analysis_date - reg_date).days < rules["min_tenure_days"]:
            return None

        recent_m, hist_m = self._period_months(
            analysis_date, config["periods"]["recent_months"], config["periods"]["historical_months"]
        )

        # --- usage decline ---
        recent_calls = sum(
            m["voice_calls"] for m in usage_data["monthly_metrics"] if m["month"] in recent_m
        )
        hist_calls = sum(
            m["voice_calls"] for m in usage_data["monthly_metrics"] if m["month"] in hist_m
        )
        usage_decline_pct = (
            (recent_calls - hist_calls) / hist_calls * 100 if hist_calls > 0 else 0.0
        )
        usage_score = self._bracket_score(usage_decline_pct, config["usage_decline_thresholds"])

        # --- topup decline ---
        recent_topup = sum(
            t["amount"] for t in topup_data["transactions"] if t["topup_date"][:7] in recent_m
        )
        hist_topup = sum(
            t["amount"] for t in topup_data["transactions"] if t["topup_date"][:7] in hist_m
        )
        topup_decline_pct = (
            (recent_topup - hist_topup) / hist_topup * 100 if hist_topup > 0 else 0.0
        )
        topup_score = self._bracket_score(topup_decline_pct, config["topup_decline_thresholds"])

        # --- sentiment ---
        ints = interaction_data["interactions"]
        if ints:
            avg_sentiment = sum(i["sentiment_score"] for i in ints) / len(ints)
            sentiment_score = self._sentiment_bracket(avg_sentiment, config["sentiment_thresholds"])
            if any(i["resolution"] == "escalated" for i in ints):
                sentiment_score = min(1.0, sentiment_score + config["escalation_penalty"])
        else:
            avg_sentiment = 0.0
            sentiment_score = 0.0

        # --- churn intent ---
        has_port_out = any(i["category"] == "port_out_request" for i in ints)
        surveys = ctx["survey_data"].get(sub["subscriber_id"], [])
        if surveys:
            avg_lik = sum(s["likelihood_to_switch"] for s in surveys) / len(surveys)
            churn_score = avg_lik / 10.0
            if any(s.get("competitor_mentioned") for s in surveys):
                churn_score += config["competitor_mention_bonus"]
        else:
            churn_score = 0.0
        if has_port_out:
            churn_score += config["port_out_bonus"]
        # campaign match
        for camp in ctx["competitor_campaigns"]:
            if camp["target_region"] == sub["region"] and sub["plan_type"] in camp.get("target_plans", []):
                churn_score += config["campaign_match_bonus"]
                break
        churn_score = min(1.0, churn_score)

        # --- combined ---
        w = config["weights"]
        risk_score = round(
            w["usage_decline"] * usage_score
            + w["topup_decline"] * topup_score
            + w["sentiment"] * sentiment_score
            + w["churn_intent"] * churn_score,
            4,
        )

        # primary risk factor (tiebreak order)
        components = [
            ("usage_decline", usage_score),
            ("churn_intent", churn_score),
            ("negative_sentiment", sentiment_score),
            ("topup_decline", topup_score),
        ]
        max_c = max(c[1] for c in components)
        primary_factor = next(name for name, sc in components if sc == max_c)

        # risk tier
        risk_tier = "low"
        for tier in ["critical", "high", "medium", "low"]:
            if risk_score >= rules["risk_tiers"][tier]["min_score"]:
                risk_tier = tier
                break

        recommended_offer = ctx["offer_matrix"].get(
            (primary_factor, sub["plan_type"]), "standard_retention_offer"
        )

        return {
            "subscriber_id": sub["subscriber_id"],
            "name": sub["name"],
            "phone": sub["phone"],
            "region": sub["region"],
            "plan_type": sub["plan_type"],
            "risk_score": risk_score,
            "risk_tier": risk_tier,
            "usage_decline_pct": round(usage_decline_pct, 2),
            "topup_decline_pct": round(topup_decline_pct, 2),
            "avg_sentiment": round(avg_sentiment, 2),
            "churn_intent_score": round(churn_score, 4),
            "primary_risk_factor": primary_factor,
            "recommended_offer": recommended_offer,
            "monthly_arpu": sub["monthly_arpu"],
        }

    # ------------------------------------------------------------------ #
    #  Ground truth via direct DB access (used by step)                    #
    # ------------------------------------------------------------------ #

    def _compute_ground_truth(self):
        ctx = self._load_workspace_context()
        config = ctx["config"]
        analysis_date = datetime.strptime(config["analysis_date"], "%Y-%m-%d")
        recent_m, hist_m = self._period_months(
            analysis_date, config["periods"]["recent_months"], config["periods"]["historical_months"]
        )

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        subscribers = [dict(r) for r in conn.execute(
            "SELECT * FROM subscribers ORDER BY subscriber_id"
        ).fetchall()]

        all_scored = []
        for sub in subscribers:
            # Build usage data dict (same shape as tool output)
            cdr_rows = conn.execute(
                "SELECT strftime('%Y-%m', call_date) AS month, "
                "SUM(CASE WHEN call_type IN ('voice_outgoing','voice_incoming') THEN 1 ELSE 0 END) AS voice_calls, "
                "SUM(CASE WHEN call_type IN ('voice_outgoing','voice_incoming') THEN duration_seconds ELSE 0 END) AS voice_seconds, "
                "SUM(CASE WHEN call_type IN ('sms_outgoing','sms_incoming') THEN 1 ELSE 0 END) AS sms_count "
                "FROM call_detail_records WHERE subscriber_id=? "
                "GROUP BY strftime('%Y-%m', call_date) ORDER BY month",
                (sub["subscriber_id"],),
            ).fetchall()
            usage_data = {
                "monthly_metrics": [
                    {"month": r["month"], "voice_calls": r["voice_calls"],
                     "voice_minutes": round(r["voice_seconds"] / 60.0, 2),
                     "sms_count": r["sms_count"]}
                    for r in cdr_rows
                ]
            }

            topup_rows = conn.execute(
                "SELECT topup_date, amount, channel, balance_after "
                "FROM topup_transactions WHERE subscriber_id=? ORDER BY topup_date",
                (sub["subscriber_id"],),
            ).fetchall()
            topup_data = {"transactions": [dict(r) for r in topup_rows]}

            int_rows = conn.execute(
                "SELECT interaction_id, interaction_date, channel, category, "
                "sentiment_score, resolution, agent_id "
                "FROM service_interactions WHERE subscriber_id=? ORDER BY interaction_date",
                (sub["subscriber_id"],),
            ).fetchall()
            interaction_data = {"interactions": [dict(r) for r in int_rows]}

            scored = self._score_subscriber(sub, usage_data, topup_data, interaction_data, ctx)
            if scored is not None:
                all_scored.append(scored)

        conn.close()

        call_list_tiers = ctx["rules"]["call_list_tiers"]
        call_list = [s for s in all_scored if s["risk_tier"] in call_list_tiers]
        call_list.sort(key=lambda x: (-x["risk_score"], -x["monthly_arpu"]))
        return call_list, all_scored

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
        call_list_gt, _ = self._compute_ground_truth()

        eval_criteria = {}
        total_score = 0
        max_score = 0

        CSV_COLUMNS = [
            "subscriber_id", "name", "phone", "region", "plan_type",
            "risk_score", "risk_tier", "usage_decline_pct", "topup_decline_pct",
            "avg_sentiment", "churn_intent_score", "primary_risk_factor", "recommended_offer",
        ]

        # ---- Criterion 1: File format (15 pts) ----
        crit = {"max_score": 15, "score": 0, "passed": False}
        csv_path = os.path.join(self.workspace, "retention_call_list.csv")
        agent_rows = []
        if os.path.exists(csv_path):
            try:
                with open(csv_path, newline="") as f:
                    reader = csv.DictReader(f)
                    agent_rows = list(reader)
                    if reader.fieldnames and set(CSV_COLUMNS) <= set(reader.fieldnames):
                        crit["score"] = 15
                        crit["passed"] = True
                    else:
                        crit["score"] = 5
                        crit["reason"] = f"Missing columns. Expected {CSV_COLUMNS}, got {reader.fieldnames}"
            except Exception as e:
                crit["reason"] = f"CSV read error: {e}"
        else:
            crit["reason"] = "retention_call_list.csv not found"
        eval_criteria["file_format"] = crit
        total_score += crit["score"]; max_score += crit["max_score"]

        # ---- Criterion 2: Subscriber identification (25 pts) ----
        crit = {"max_score": 25, "score": 0, "passed": False}
        gt_ids = {r["subscriber_id"] for r in call_list_gt}
        ag_ids = {r.get("subscriber_id", "") for r in agent_rows}
        if gt_ids or ag_ids:
            correct = gt_ids & ag_ids
            prec = len(correct) / len(ag_ids) if ag_ids else 0
            rec = len(correct) / len(gt_ids) if gt_ids else 0
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
            crit["score"] = round(25 * f1)
            crit["passed"] = f1 >= 0.95
            if not crit["passed"]:
                crit["reason"] = f"F1={f1:.3f} (expected {len(gt_ids)}, got {len(ag_ids)}, correct {len(correct)})"
        else:
            crit["score"] = 25; crit["passed"] = True
        eval_criteria["subscriber_identification"] = crit
        total_score += crit["score"]; max_score += crit["max_score"]

        # ---- Criterion 3: Risk score accuracy (20 pts) ----
        crit = {"max_score": 20, "score": 0, "passed": False}
        if agent_rows:
            gt_scores = {r["subscriber_id"]: r["risk_score"] for r in call_list_gt}
            ok = total_cmp = 0
            for row in agent_rows:
                sid = row.get("subscriber_id", "")
                if sid in gt_scores:
                    total_cmp += 1
                    try:
                        if abs(float(row.get("risk_score", -1)) - gt_scores[sid]) <= 0.05:
                            ok += 1
                    except (ValueError, TypeError):
                        pass
            if total_cmp:
                acc = ok / total_cmp
                crit["score"] = round(20 * acc)
                crit["passed"] = acc >= 0.9
                if not crit["passed"]:
                    crit["reason"] = f"Accuracy {acc:.3f} ({ok}/{total_cmp})"
        else:
            crit["reason"] = "No rows"
        eval_criteria["risk_score_accuracy"] = crit
        total_score += crit["score"]; max_score += crit["max_score"]

        # ---- Criterion 4: Ranking correctness (15 pts) ----
        crit = {"max_score": 15, "score": 0, "passed": False}
        if len(agent_rows) >= 2:
            gt_order = [r["subscriber_id"] for r in call_list_gt]
            ag_order = [r.get("subscriber_id", "") for r in agent_rows]
            common_gt = [s for s in gt_order if s in ag_ids]
            common_ag = [s for s in ag_order if s in gt_ids]
            if len(common_ag) >= 2:
                ok_pairs = total_pairs = 0
                for i in range(len(common_ag)):
                    for j in range(i + 1, len(common_ag)):
                        total_pairs += 1
                        gi = common_gt.index(common_ag[i]) if common_ag[i] in common_gt else len(common_gt)
                        gj = common_gt.index(common_ag[j]) if common_ag[j] in common_gt else len(common_gt)
                        if gi < gj:
                            ok_pairs += 1
                if total_pairs:
                    acc = ok_pairs / total_pairs
                    crit["score"] = round(15 * acc)
                    crit["passed"] = acc >= 0.9
                    if not crit["passed"]:
                        crit["reason"] = f"Pair accuracy {acc:.3f}"
        else:
            crit["reason"] = "Fewer than 2 rows"
        eval_criteria["ranking_correctness"] = crit
        total_score += crit["score"]; max_score += crit["max_score"]

        # ---- Criterion 5: Tier & offer correctness (15 pts) ----
        crit = {"max_score": 15, "score": 0, "passed": False}
        if agent_rows:
            gt_tiers = {r["subscriber_id"]: r["risk_tier"] for r in call_list_gt}
            gt_offers = {r["subscriber_id"]: r["recommended_offer"] for r in call_list_gt}
            t_ok = o_ok = cmp = 0
            for row in agent_rows:
                sid = row.get("subscriber_id", "")
                if sid in gt_tiers:
                    cmp += 1
                    if row.get("risk_tier") == gt_tiers[sid]:
                        t_ok += 1
                    if row.get("recommended_offer") == gt_offers[sid]:
                        o_ok += 1
            if cmp:
                combined = 0.5 * (t_ok / cmp) + 0.5 * (o_ok / cmp)
                crit["score"] = round(15 * combined)
                crit["passed"] = combined >= 0.9
                if not crit["passed"]:
                    crit["reason"] = f"Tier {t_ok}/{cmp}, Offer {o_ok}/{cmp}"
        else:
            crit["reason"] = "No rows"
        eval_criteria["tier_and_offer"] = crit
        total_score += crit["score"]; max_score += crit["max_score"]

        # ---- Criterion 6: Response summary (10 pts) ----
        crit = {"max_score": 10, "score": 0, "passed": False}
        if action:
            pts = 0
            if str(len(call_list_gt)) in action:
                pts += 3
            crit_cnt = sum(1 for r in call_list_gt if r["risk_tier"] == "critical")
            high_cnt = sum(1 for r in call_list_gt if r["risk_tier"] == "high")
            if str(crit_cnt) in action and str(high_cnt) in action:
                pts += 3
            top5 = call_list_gt[:5]
            mentioned = sum(1 for r in top5 if r["subscriber_id"] in action)
            if mentioned >= 3:
                pts += 4
            elif mentioned >= 1:
                pts += 2
            crit["score"] = pts
            crit["passed"] = pts >= 8
            if not crit["passed"]:
                crit["reason"] = f"Summary scored {pts}/10"
        else:
            crit["reason"] = "Empty response"
        eval_criteria["response_summary"] = crit
        total_score += crit["score"]; max_score += crit["max_score"]

        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, {
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
        # 1. Load workspace files
        ctx = self._load_workspace_context()
        config = ctx["config"]
        rules = ctx["rules"]
        analysis_date = datetime.strptime(config["analysis_date"], "%Y-%m-%d")

        # 2. List all subscribers via tools
        all_subs = []
        page = 1
        while True:
            result = self.tools["list_subscribers"](page=page)
            all_subs.extend(result["subscribers"])
            if not result["has_more"]:
                break
            page += 1

        # 3. Score each subscriber
        scored = []
        for sub in all_subs:
            usage_data = self.tools["get_usage_metrics"](subscriber_id=sub["subscriber_id"])
            topup_data = self.tools["get_topup_history"](subscriber_id=sub["subscriber_id"])
            int_data = self.tools["get_service_interactions"](subscriber_id=sub["subscriber_id"])
            result = self._score_subscriber(sub, usage_data, topup_data, int_data, ctx)
            if result is not None:
                scored.append(result)

        # 4. Filter to call-list tiers and sort
        call_list_tiers = rules["call_list_tiers"]
        final = [s for s in scored if s["risk_tier"] in call_list_tiers]
        final.sort(key=lambda x: (-x["risk_score"], -x["monthly_arpu"]))

        # 5. Write retention_call_list.csv
        fieldnames = [
            "subscriber_id", "name", "phone", "region", "plan_type",
            "risk_score", "risk_tier", "usage_decline_pct", "topup_decline_pct",
            "avg_sentiment", "churn_intent_score", "primary_risk_factor", "recommended_offer",
        ]
        csv_path = os.path.join(self.workspace, "retention_call_list.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(final)

        # 6. Build action string
        total_at_risk = len(final)
        crit_cnt = sum(1 for r in final if r["risk_tier"] == "critical")
        high_cnt = sum(1 for r in final if r["risk_tier"] == "high")
        region_counts = {}
        for r in final:
            region_counts[r["region"]] = region_counts.get(r["region"], 0) + 1

        top5 = final[:5]

        lines = [
            f"Total subscribers on call list: {total_at_risk}",
            f"Risk tier breakdown: critical={crit_cnt}, high={high_cnt}",
            "Per-region at-risk counts:",
        ]
        for reg in sorted(region_counts):
            lines.append(f"  {reg}: {region_counts[reg]}")
        lines.append("")
        lines.append("Top 5 highest-risk subscribers:")
        for r in top5:
            lines.append(
                f"  {r['subscriber_id']} — Risk Score: {r['risk_score']}, Tier: {r['risk_tier']}"
            )
        action = "\n".join(lines)

        return self.step(action)
