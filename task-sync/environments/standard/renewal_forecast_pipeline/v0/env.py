#!/usr/bin/env python3
"""Environment for quarterly contract renewal forecast task."""

import sqlite3
import os
import json
import csv
import math
import re
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

    # ---- Tool methods ----

    @tool(
        description="List contracts expiring within a given date range. Returns paginated results (10 per page). Each result contains contract_id, client_id, platform_name, end_date, and annual_value.",
        parameters={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start of date range in YYYY-MM-DD format (inclusive).",
                },
                "end_date": {
                    "type": "string",
                    "description": "End of date range in YYYY-MM-DD format (inclusive).",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
            },
            "required": ["start_date", "end_date"],
        },
    )
    def list_expiring_contracts(self, start_date: str, end_date: str, page: int = 1) -> dict:
        page_size = 10
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT contract_id, client_id, platform_name, end_date, annual_value "
            "FROM contracts WHERE end_date >= ? AND end_date <= ? ORDER BY end_date, contract_id",
            (start_date, end_date),
        )
        all_rows = cur.fetchall()
        conn.close()

        total = len(all_rows)
        total_pages = max(1, math.ceil(total / page_size))
        start_idx = (page - 1) * page_size
        page_rows = all_rows[start_idx : start_idx + page_size]

        return {
            "contracts": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "total_pages": total_pages,
        }

    @tool(
        description="Get full details of a single contract by its ID. Returns contract_id, client_id, platform_name, start_date, end_date, annual_value, status, auto_renew, and payment_terms.",
        parameters={
            "type": "object",
            "properties": {
                "contract_id": {
                    "type": "string",
                    "description": "The contract identifier (e.g. CNT-0001).",
                },
            },
            "required": ["contract_id"],
        },
    )
    def get_contract_details(self, contract_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM contracts WHERE contract_id = ?", (contract_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Contract {contract_id} not found."}
        return dict(row)

    @tool(
        description="Get client information by client ID. Returns client_id, company_name, industry, region, tier, and account_manager.",
        parameters={
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "string",
                    "description": "The client identifier (e.g. CLI-0001).",
                },
            },
            "required": ["client_id"],
        },
    )
    def get_client_info(self, client_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Client {client_id} not found."}
        return dict(row)

    @tool(
        description="Get monthly usage metrics for a specific contract. Returns a list of records each containing month, active_users, api_calls, storage_used_gb, and feature_adoption_pct. Records are ordered by month ascending.",
        parameters={
            "type": "object",
            "properties": {
                "contract_id": {
                    "type": "string",
                    "description": "The contract identifier (e.g. CNT-0001).",
                },
            },
            "required": ["contract_id"],
        },
    )
    def get_usage_metrics(self, contract_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT month, active_users, api_calls, storage_used_gb, feature_adoption_pct "
            "FROM usage_metrics WHERE contract_id = ? ORDER BY month",
            (contract_id,),
        )
        rows = cur.fetchall()
        conn.close()
        return {"contract_id": contract_id, "metrics": [dict(r) for r in rows]}

    @tool(
        description="Get stakeholder feedback entries for a client. Returns paginated results (5 per page). Each entry contains contact_name, contact_role, sentiment, feedback_text, feedback_date, and channel.",
        parameters={
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "string",
                    "description": "The client identifier (e.g. CLI-0001).",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
            },
            "required": ["client_id"],
        },
    )
    def get_stakeholder_feedback(self, client_id: str, page: int = 1) -> dict:
        page_size = 5
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT contact_name, contact_role, sentiment, feedback_text, feedback_date, channel "
            "FROM stakeholder_feedback WHERE client_id = ? ORDER BY feedback_date DESC",
            (client_id,),
        )
        all_rows = cur.fetchall()
        conn.close()

        total = len(all_rows)
        total_pages = max(1, math.ceil(total / page_size))
        start_idx = (page - 1) * page_size
        page_rows = all_rows[start_idx : start_idx + page_size]

        return {
            "client_id": client_id,
            "feedback": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "total_pages": total_pages,
        }

    @tool(
        description="Get negotiation history for a specific contract. Returns a list of negotiation records each containing negotiation_date, negotiator, outcome, discount_offered_pct, final_discount_pct, duration_days, and notes.",
        parameters={
            "type": "object",
            "properties": {
                "contract_id": {
                    "type": "string",
                    "description": "The contract identifier (e.g. CNT-0001).",
                },
            },
            "required": ["contract_id"],
        },
    )
    def get_negotiation_history(self, contract_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT negotiation_date, negotiator, outcome, discount_offered_pct, "
            "final_discount_pct, duration_days, notes "
            "FROM negotiation_history WHERE contract_id = ? ORDER BY negotiation_date DESC",
            (contract_id,),
        )
        rows = cur.fetchall()
        conn.close()
        return {"contract_id": contract_id, "history": [dict(r) for r in rows]}

    # ---- Evaluation ----

    def _compute_ground_truth(self) -> List[dict]:
        """Compute the ground truth renewal forecast using DB + workspace files."""
        import yaml

        # 1. Load config files
        config_dir = os.path.join(self.workspace, "config")
        with open(os.path.join(config_dir, "scoring_config.yaml"), "r") as f:
            scoring_config = yaml.safe_load(f)
        with open(os.path.join(config_dir, "renewal_policy.json"), "r") as f:
            renewal_policy = json.load(f)
        discount_schedule = []
        with open(os.path.join(config_dir, "discount_schedule.csv"), "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                discount_schedule.append(row)

        weights = scoring_config["scoring_weights"]
        target = scoring_config["target_quarter"]

        # 2. Get expiring contracts from DB
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM contracts WHERE end_date >= ? AND end_date <= ? ORDER BY end_date, contract_id",
            (target["start_date"], target["end_date"]),
        )
        expiring = [dict(r) for r in cur.fetchall()]

        # 3. Load all workspace data files
        # Client dossiers
        strategic_map = {}  # client_id -> strategic_importance
        dossier_dir = os.path.join(self.workspace, "client_dossiers")
        if os.path.isdir(dossier_dir):
            for fname in sorted(os.listdir(dossier_dir)):
                if fname.endswith(".json"):
                    with open(os.path.join(dossier_dir, fname), "r") as f:
                        entries = json.load(f)
                    for entry in entries:
                        strategic_map[entry["client_id"]] = entry["strategic_importance"]

        # Competitive analysis
        threat_map = {}  # contract_id -> competitor_threat_level
        analysis_dir = os.path.join(self.workspace, "competitive_analysis")
        if os.path.isdir(analysis_dir):
            for fname in sorted(os.listdir(analysis_dir)):
                if fname.endswith(".csv"):
                    with open(os.path.join(analysis_dir, fname), "r") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            threat_map[row["contract_id"]] = int(row["competitor_threat_level"])

        # Negotiation briefs
        difficulty_map = {}  # contract_id -> negotiation_difficulty
        brief_dir = os.path.join(self.workspace, "negotiation_briefs")
        if os.path.isdir(brief_dir):
            for fname in sorted(os.listdir(brief_dir)):
                if fname.endswith(".md"):
                    with open(os.path.join(brief_dir, fname), "r") as f:
                        content = f.read()
                    # Parse markdown for contract entries
                    blocks = re.split(r"^## ", content, flags=re.MULTILINE)
                    for block in blocks:
                        block = block.strip()
                        if not block:
                            continue
                        lines = block.split("\n")
                        cid = lines[0].strip()
                        diff_match = re.search(r"\*\*Negotiation Difficulty:\*\*\s*(\d+)", block)
                        if diff_match and cid.startswith("CNT-"):
                            difficulty_map[cid] = int(diff_match.group(1))

        # 4. Compute scores for each expiring contract
        results = []
        for contract in expiring:
            cid = contract["contract_id"]
            client_id = contract["client_id"]

            # Usage decline: compare first 3 months avg active_users vs last 3 months
            cur.execute(
                "SELECT month, active_users FROM usage_metrics WHERE contract_id = ? ORDER BY month",
                (cid,),
            )
            metrics = cur.fetchall()
            if len(metrics) >= 6:
                first_3 = sum(m["active_users"] for m in metrics[:3]) / 3.0
                last_3 = sum(m["active_users"] for m in metrics[-3:]) / 3.0
                if first_3 > 0:
                    decline_pct = max(0, (first_3 - last_3) / first_3 * 100.0)
                else:
                    decline_pct = 0
            else:
                decline_pct = 0
            usage_decline_score = min(100.0, max(0.0, decline_pct * 2))

            # Sentiment risk
            cur.execute(
                "SELECT sentiment FROM stakeholder_feedback WHERE client_id = ?",
                (client_id,),
            )
            fb_rows = cur.fetchall()
            if fb_rows:
                neg_count = sum(1 for r in fb_rows if r["sentiment"] == "negative")
                sentiment_risk_score = (neg_count / len(fb_rows)) * 100.0
            else:
                sentiment_risk_score = 50.0

            # Strategic importance
            si = strategic_map.get(client_id, 5)
            strategic_score = si * 10.0

            # Competitive threat
            ct = threat_map.get(cid, 5)
            competitive_score = ct * 10.0

            # Negotiation difficulty
            nd = difficulty_map.get(cid, 5)
            difficulty_score = nd * 10.0

            # Weighted risk score
            risk_score = (
                weights["usage_decline"] * usage_decline_score
                + weights["sentiment_risk"] * sentiment_risk_score
                + weights["strategic_importance"] * strategic_score
                + weights["competitive_threat"] * competitive_score
                + weights["negotiation_difficulty"] * difficulty_score
            )
            risk_score = round(risk_score, 2)

            # Client info
            cur.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,))
            client_info = dict(cur.fetchone())
            tier = client_info["tier"]

            # Recommended action based on tier thresholds
            thresholds = renewal_policy["action_thresholds"][tier]
            if risk_score < thresholds["auto_renew_below"]:
                action = "auto_renew"
            elif risk_score < thresholds["standard_renewal_below"]:
                action = "standard_renewal"
            elif risk_score < thresholds["manager_review_below"]:
                action = "manager_review"
            else:
                action = "executive_escalation"

            # Projected discount
            annual_val = contract["annual_value"]
            max_disc = 0
            for dr in discount_schedule:
                if (
                    dr["tier"] == tier
                    and float(dr["min_value"]) <= annual_val <= float(dr["max_value"])
                ):
                    max_disc = float(dr["max_discount_pct"])
                    break
            projected_discount = round(max_disc * (risk_score / 100.0), 2)

            # Usage trend label
            if len(metrics) >= 6:
                first_3_avg = sum(m["active_users"] for m in metrics[:3]) / 3.0
                last_3_avg = sum(m["active_users"] for m in metrics[-3:]) / 3.0
                if first_3_avg > 0:
                    usage_trend_pct = round(((last_3_avg - first_3_avg) / first_3_avg) * 100.0, 2)
                else:
                    usage_trend_pct = 0.0
            else:
                usage_trend_pct = 0.0

            results.append(
                {
                    "contract_id": cid,
                    "client_name": client_info["company_name"],
                    "platform": contract["platform_name"],
                    "expiry_date": contract["end_date"],
                    "annual_value": round(annual_val, 2),
                    "usage_trend_pct": usage_trend_pct,
                    "sentiment_score": round(sentiment_risk_score, 2),
                    "risk_score": risk_score,
                    "priority_rank": 0,  # filled after sort
                    "recommended_action": action,
                    "projected_discount_pct": projected_discount,
                    "tier": tier,
                }
            )

        conn.close()

        # Sort by risk_score descending, then contract_id ascending for tie-breaking
        results.sort(key=lambda x: (-x["risk_score"], x["contract_id"]))
        for i, r in enumerate(results):
            r["priority_rank"] = i + 1

        return results

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
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: renewal_forecast.csv exists with correct columns (15 pts) ---
        max_score += 15
        csv_path = os.path.join(self.workspace, "renewal_forecast.csv")
        expected_cols = [
            "contract_id", "client_name", "platform", "expiry_date",
            "annual_value", "usage_trend_pct", "sentiment_score",
            "risk_score", "priority_rank", "recommended_action", "projected_discount_pct",
        ]
        csv_rows = []
        if os.path.exists(csv_path):
            with open(csv_path, "r") as f:
                reader = csv.DictReader(f)
                actual_cols = reader.fieldnames or []
                csv_rows = list(reader)
            if set(expected_cols).issubset(set(actual_cols)):
                eval_criteria["csv_structure"] = {
                    "passed": True, "score": 15, "max_score": 15,
                }
                total_score += 15
            else:
                missing = set(expected_cols) - set(actual_cols)
                eval_criteria["csv_structure"] = {
                    "passed": False, "score": 0, "max_score": 15,
                    "reason": f"Missing columns: {sorted(missing)}",
                }
        else:
            eval_criteria["csv_structure"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "renewal_forecast.csv not found in workspace.",
            }

        # --- Criterion 2: Correct number of expiring contracts (15 pts) ---
        max_score += 15
        if len(csv_rows) == len(ground_truth):
            eval_criteria["contract_count"] = {
                "passed": True, "score": 15, "max_score": 15,
            }
            total_score += 15
        else:
            eval_criteria["contract_count"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": f"Expected {len(ground_truth)} contracts, got {len(csv_rows)}.",
            }

        # --- Criterion 3: Correct risk_score values (20 pts) ---
        max_score += 20
        gt_map = {r["contract_id"]: r for r in ground_truth}
        csv_map = {}
        for row in csv_rows:
            csv_map[row.get("contract_id", "")] = row

        correct_scores = 0
        total_contracts = len(ground_truth)
        for cid, gt in gt_map.items():
            if cid in csv_map:
                try:
                    agent_score = float(csv_map[cid]["risk_score"])
                    if abs(agent_score - gt["risk_score"]) < 0.5:
                        correct_scores += 1
                except (ValueError, KeyError):
                    pass
        if total_contracts > 0:
            score_pct = correct_scores / total_contracts
            earned = round(20 * score_pct)
        else:
            earned = 0
        eval_criteria["risk_scores"] = {
            "passed": earned == 20,
            "score": earned,
            "max_score": 20,
            "reason": f"{correct_scores}/{total_contracts} risk scores within tolerance." if earned < 20 else "",
        }
        total_score += earned

        # --- Criterion 4: Correct priority ranking (15 pts) ---
        max_score += 15
        correct_ranks = 0
        for cid, gt in gt_map.items():
            if cid in csv_map:
                try:
                    agent_rank = int(csv_map[cid]["priority_rank"])
                    if agent_rank == gt["priority_rank"]:
                        correct_ranks += 1
                except (ValueError, KeyError):
                    pass
        if total_contracts > 0:
            rank_pct = correct_ranks / total_contracts
            earned = round(15 * rank_pct)
        else:
            earned = 0
        eval_criteria["priority_ranking"] = {
            "passed": earned == 15,
            "score": earned,
            "max_score": 15,
            "reason": f"{correct_ranks}/{total_contracts} ranks correct." if earned < 15 else "",
        }
        total_score += earned

        # --- Criterion 5: Correct recommended_action (15 pts) ---
        max_score += 15
        correct_actions = 0
        for cid, gt in gt_map.items():
            if cid in csv_map:
                agent_action = csv_map[cid].get("recommended_action", "").strip()
                if agent_action == gt["recommended_action"]:
                    correct_actions += 1
        if total_contracts > 0:
            action_pct = correct_actions / total_contracts
            earned = round(15 * action_pct)
        else:
            earned = 0
        eval_criteria["recommended_actions"] = {
            "passed": earned == 15,
            "score": earned,
            "max_score": 15,
            "reason": f"{correct_actions}/{total_contracts} actions correct." if earned < 15 else "",
        }
        total_score += earned

        # --- Criterion 6: Correct projected_discount_pct (10 pts) ---
        max_score += 10
        correct_discounts = 0
        for cid, gt in gt_map.items():
            if cid in csv_map:
                try:
                    agent_disc = float(csv_map[cid]["projected_discount_pct"])
                    if abs(agent_disc - gt["projected_discount_pct"]) < 0.1:
                        correct_discounts += 1
                except (ValueError, KeyError):
                    pass
        if total_contracts > 0:
            disc_pct = correct_discounts / total_contracts
            earned = round(10 * disc_pct)
        else:
            earned = 0
        eval_criteria["projected_discounts"] = {
            "passed": earned == 10,
            "score": earned,
            "max_score": 10,
            "reason": f"{correct_discounts}/{total_contracts} discounts correct." if earned < 10 else "",
        }
        total_score += earned

        # --- Criterion 7: Top 5 summary in final response (10 pts) ---
        max_score += 10
        top5 = ground_truth[:5]
        top5_found = 0
        for entry in top5:
            # Check that contract_id and client_name appear in action
            if entry["contract_id"] in action and entry["client_name"] in action:
                top5_found += 1
        if len(top5) > 0:
            earned = round(10 * (top5_found / len(top5)))
        else:
            earned = 0
        eval_criteria["top5_summary"] = {
            "passed": earned == 10,
            "score": earned,
            "max_score": 10,
            "reason": f"{top5_found}/{len(top5)} top-5 entries found in response." if earned < 10 else "",
        }
        total_score += earned

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
        import yaml

        tool_call_count = 0

        # 1. Read config files from workspace
        config_dir = os.path.join(self.workspace, "config")
        with open(os.path.join(config_dir, "scoring_config.yaml"), "r") as f:
            scoring_config = yaml.safe_load(f)
        with open(os.path.join(config_dir, "renewal_policy.json"), "r") as f:
            renewal_policy = json.load(f)
        discount_schedule = []
        with open(os.path.join(config_dir, "discount_schedule.csv"), "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                discount_schedule.append(row)

        weights = scoring_config["scoring_weights"]
        target = scoring_config["target_quarter"]

        # 2. Load workspace data files
        # Client dossiers -> strategic_importance
        strategic_map = {}
        dossier_dir = os.path.join(self.workspace, "client_dossiers")
        if os.path.isdir(dossier_dir):
            for fname in sorted(os.listdir(dossier_dir)):
                if fname.endswith(".json"):
                    with open(os.path.join(dossier_dir, fname), "r") as f:
                        entries = json.load(f)
                    for entry in entries:
                        strategic_map[entry["client_id"]] = entry["strategic_importance"]

        # Competitive analysis -> competitor_threat_level
        threat_map = {}
        analysis_dir = os.path.join(self.workspace, "competitive_analysis")
        if os.path.isdir(analysis_dir):
            for fname in sorted(os.listdir(analysis_dir)):
                if fname.endswith(".csv"):
                    with open(os.path.join(analysis_dir, fname), "r") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            threat_map[row["contract_id"]] = int(row["competitor_threat_level"])

        # Negotiation briefs -> negotiation_difficulty
        difficulty_map = {}
        brief_dir = os.path.join(self.workspace, "negotiation_briefs")
        if os.path.isdir(brief_dir):
            for fname in sorted(os.listdir(brief_dir)):
                if fname.endswith(".md"):
                    with open(os.path.join(brief_dir, fname), "r") as f:
                        content = f.read()
                    blocks = re.split(r"^## ", content, flags=re.MULTILINE)
                    for block in blocks:
                        block = block.strip()
                        if not block:
                            continue
                        lines = block.split("\n")
                        cid = lines[0].strip()
                        diff_match = re.search(r"\*\*Negotiation Difficulty:\*\*\s*(\d+)", block)
                        if diff_match and cid.startswith("CNT-"):
                            difficulty_map[cid] = int(diff_match.group(1))

        # 3. List all expiring contracts via tool
        all_expiring = []
        page = 1
        while True:
            result = self.tools["list_expiring_contracts"](
                start_date=target["start_date"],
                end_date=target["end_date"],
                page=page,
            )
            tool_call_count += 1
            all_expiring.extend(result["contracts"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 4. For each expiring contract, gather data via tools
        forecast_rows = []
        seen_clients = {}

        for contract_summary in all_expiring:
            cid = contract_summary["contract_id"]
            client_id = contract_summary["client_id"]

            # Get full contract details
            details = self.tools["get_contract_details"](contract_id=cid)
            tool_call_count += 1

            # Get client info (cache for same client)
            if client_id not in seen_clients:
                seen_clients[client_id] = self.tools["get_client_info"](client_id=client_id)
                tool_call_count += 1
            client_info = seen_clients[client_id]

            # Get usage metrics
            usage_result = self.tools["get_usage_metrics"](contract_id=cid)
            tool_call_count += 1
            metrics = usage_result["metrics"]

            # Compute usage decline
            if len(metrics) >= 6:
                first_3 = sum(m["active_users"] for m in metrics[:3]) / 3.0
                last_3 = sum(m["active_users"] for m in metrics[-3:]) / 3.0
                if first_3 > 0:
                    decline_pct = max(0, (first_3 - last_3) / first_3 * 100.0)
                else:
                    decline_pct = 0
            else:
                decline_pct = 0
            usage_decline_score = min(100.0, max(0.0, decline_pct * 2))

            # Usage trend percentage
            if len(metrics) >= 6:
                first_3_avg = sum(m["active_users"] for m in metrics[:3]) / 3.0
                last_3_avg = sum(m["active_users"] for m in metrics[-3:]) / 3.0
                if first_3_avg > 0:
                    usage_trend_pct = round(((last_3_avg - first_3_avg) / first_3_avg) * 100.0, 2)
                else:
                    usage_trend_pct = 0.0
            else:
                usage_trend_pct = 0.0

            # Sentiment risk: collect all feedback for this client
            all_feedback = []
            fb_page = 1
            while True:
                fb_result = self.tools["get_stakeholder_feedback"](client_id=client_id, page=fb_page)
                tool_call_count += 1
                all_feedback.extend(fb_result["feedback"])
                if fb_page >= fb_result["total_pages"]:
                    break
                fb_page += 1

            if all_feedback:
                neg_count = sum(1 for fb in all_feedback if fb["sentiment"] == "negative")
                sentiment_risk_score = (neg_count / len(all_feedback)) * 100.0
            else:
                sentiment_risk_score = 50.0

            # Get negotiation history via tool (to demonstrate usage, not needed for score)
            neg_result = self.tools["get_negotiation_history"](contract_id=cid)
            tool_call_count += 1

            # Workspace-derived scores
            si = strategic_map.get(client_id, 5)
            strategic_score = si * 10.0

            ct = threat_map.get(cid, 5)
            competitive_score = ct * 10.0

            nd = difficulty_map.get(cid, 5)
            difficulty_score = nd * 10.0

            # Weighted risk score
            risk_score = (
                weights["usage_decline"] * usage_decline_score
                + weights["sentiment_risk"] * sentiment_risk_score
                + weights["strategic_importance"] * strategic_score
                + weights["competitive_threat"] * competitive_score
                + weights["negotiation_difficulty"] * difficulty_score
            )
            risk_score = round(risk_score, 2)

            # Recommended action
            tier = client_info["tier"]
            thresholds = renewal_policy["action_thresholds"][tier]
            if risk_score < thresholds["auto_renew_below"]:
                action = "auto_renew"
            elif risk_score < thresholds["standard_renewal_below"]:
                action = "standard_renewal"
            elif risk_score < thresholds["manager_review_below"]:
                action = "manager_review"
            else:
                action = "executive_escalation"

            # Projected discount
            annual_val = details["annual_value"]
            max_disc = 0
            for dr in discount_schedule:
                if (
                    dr["tier"] == tier
                    and float(dr["min_value"]) <= annual_val <= float(dr["max_value"])
                ):
                    max_disc = float(dr["max_discount_pct"])
                    break
            projected_discount = round(max_disc * (risk_score / 100.0), 2)

            forecast_rows.append(
                {
                    "contract_id": cid,
                    "client_name": client_info["company_name"],
                    "platform": details["platform_name"],
                    "expiry_date": details["end_date"],
                    "annual_value": round(annual_val, 2),
                    "usage_trend_pct": usage_trend_pct,
                    "sentiment_score": round(sentiment_risk_score, 2),
                    "risk_score": risk_score,
                    "priority_rank": 0,
                    "recommended_action": action,
                    "projected_discount_pct": projected_discount,
                }
            )

        # Sort by risk_score descending, contract_id ascending for tie-breaking
        forecast_rows.sort(key=lambda x: (-x["risk_score"], x["contract_id"]))
        for i, row in enumerate(forecast_rows):
            row["priority_rank"] = i + 1

        # 5. Write renewal_forecast.csv
        csv_path = os.path.join(self.workspace, "renewal_forecast.csv")
        fieldnames = [
            "contract_id", "client_name", "platform", "expiry_date",
            "annual_value", "usage_trend_pct", "sentiment_score",
            "risk_score", "priority_rank", "recommended_action", "projected_discount_pct",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in forecast_rows:
                writer.writerow(row)

        # 6. Build action string with top 5 summary
        top5 = forecast_rows[:5]
        summary_lines = ["Quarterly Contract Renewal Forecast - Top 5 Priority Renewals:\n"]
        for entry in top5:
            summary_lines.append(
                f"Rank {entry['priority_rank']}: {entry['client_name']} - {entry['platform']} "
                f"(Contract {entry['contract_id']}), Risk Score: {entry['risk_score']}, "
                f"Action: {entry['recommended_action']}"
            )
        summary_lines.append(
            f"\nTotal contracts expiring in {target['label']}: {len(forecast_rows)}"
        )
        summary_lines.append("Full forecast saved to renewal_forecast.csv.")
        action_text = "\n".join(summary_lines)

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need at least 15."

        return self.step(action_text)
