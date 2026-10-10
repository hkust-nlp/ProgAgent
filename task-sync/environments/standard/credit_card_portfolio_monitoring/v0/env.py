from typing import Tuple, Dict, List, Any
import sqlite3
import json
import os
import csv
import glob
import re
from datetime import datetime, timedelta


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

    # ===================== TOOL METHODS =====================

    @tool(
        description="List credit card accounts with pagination. Returns account details including ID, name, region, tier, credit limit, and status. Results are ordered by account_id.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of accounts per page. Maximum allowed is 20. Defaults to 20 if omitted.",
                },
            },
            "required": ["page"],
        },
    )
    def list_accounts(self, page: int, page_size: int = 20) -> dict:
        page_size = min(int(page_size) if page_size else 20, 20)
        page = max(1, int(page))
        offset = (page - 1) * page_size

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM accounts")
        total = cur.fetchone()[0]

        cur.execute(
            "SELECT * FROM accounts ORDER BY account_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        total_pages = (total + page_size - 1) // page_size
        return {
            "accounts": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    @tool(
        description="Retrieve all transactions for a specific credit card account, ordered by transaction date.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "The account identifier, e.g. ACC_00001.",
                }
            },
            "required": ["account_id"],
        },
    )
    def get_account_transactions(self, account_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM transactions WHERE account_id = ? ORDER BY tx_date",
            (account_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        if not rows:
            return {"error": f"No transactions found for account {account_id}"}
        return {"transactions": rows}

    @tool(
        description="Retrieve credit bureau score history for a specific account, sorted chronologically by report date.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "The account identifier.",
                }
            },
            "required": ["account_id"],
        },
    )
    def get_credit_bureau_records(self, account_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM credit_bureau WHERE account_id = ? ORDER BY report_date",
            (account_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        if not rows:
            return {"error": f"No credit bureau records found for account {account_id}"}
        return {"records": rows}

    @tool(
        description="Retrieve monthly payment history for a specific account, sorted by billing period ascending.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "The account identifier.",
                }
            },
            "required": ["account_id"],
        },
    )
    def get_payment_history(self, account_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM payment_history WHERE account_id = ? ORDER BY billing_period",
            (account_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        if not rows:
            return {"error": f"No payment history found for account {account_id}"}
        return {"records": rows}

    @tool(
        description="Retrieve macroeconomic delinquency data for a specific region. Returns all available periods sorted by period descending (most recent first).",
        parameters={
            "type": "object",
            "properties": {
                "region_code": {
                    "type": "string",
                    "description": "The region code, e.g. NE, SE, MW, SW, WE, NW, SC, NC, AT, PA.",
                }
            },
            "required": ["region_code"],
        },
    )
    def get_regional_delinquency(self, region_code: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM macro_delinquency WHERE region_code = ? ORDER BY period DESC",
            (region_code,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        if not rows:
            return {"error": f"No delinquency data found for region {region_code}"}
        return {"records": rows}

    # ===================== HELPERS =====================

    def _read_workspace_configs(self):
        """Read all workspace configuration files and supplement data."""
        import yaml

        with open(os.path.join(self.workspace, "risk_thresholds.yaml")) as f:
            risk_config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "tier_config.json")) as f:
            tier_config = json.load(f)
        with open(os.path.join(self.workspace, "regional_adjustments.json")) as f:
            regional_adj = json.load(f)

        supplement = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "account_supplement_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    supplement[row["account_id"]] = row

        return risk_config, tier_config, regional_adj, supplement

    def _compute_ground_truth(self):
        """Compute expected high-risk accounts using direct DB access."""
        risk_config, tier_config, regional_adj, supplement = self._read_workspace_configs()

        weights = risk_config["scoring_weights"]
        thresholds = risk_config["thresholds"]
        dti_config = risk_config["dti_bonus"]
        cutoff = risk_config["high_risk_cutoff"]
        levels = risk_config["risk_levels"]
        factor_priority = risk_config["factor_priority"]
        eval_months = risk_config["evaluation_period_months"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # All active accounts
        cur.execute("SELECT * FROM accounts WHERE status = 'active' ORDER BY account_id")
        active_accounts = [dict(r) for r in cur.fetchall()]

        # Latest delinquency rate per region
        cur.execute(
            "SELECT m.region_code, m.delinquency_rate FROM macro_delinquency m "
            "INNER JOIN (SELECT region_code, MAX(period) AS max_period FROM macro_delinquency GROUP BY region_code) sub "
            "ON m.region_code = sub.region_code AND m.period = sub.max_period"
        )
        region_delinq = {row["region_code"]: row["delinquency_rate"] for row in cur.fetchall()}

        high_risk = []
        for acc in active_accounts:
            acc_id = acc["account_id"]

            supp = supplement.get(acc_id, {})
            if supp.get("hardship_program") == "yes":
                continue

            # Factor 1: Cash advance ratio
            cur.execute("SELECT amount, tx_type FROM transactions WHERE account_id = ?", (acc_id,))
            txns = cur.fetchall()
            total_amount = sum(r["amount"] for r in txns)
            ca_amount = sum(r["amount"] for r in txns if r["tx_type"] == "cash_advance")
            ca_ratio = ca_amount / total_amount if total_amount > 0 else 0
            ca_triggered = ca_ratio > thresholds["cash_advance_ratio"]

            # Factor 2: Credit score decline
            cur.execute(
                "SELECT report_date, credit_score FROM credit_bureau WHERE account_id = ? ORDER BY report_date",
                (acc_id,),
            )
            scores = [dict(r) for r in cur.fetchall()]
            cs_triggered = False
            if len(scores) >= 2:
                latest_date = scores[-1]["report_date"]
                latest_score = scores[-1]["credit_score"]
                latest_dt = datetime.strptime(latest_date, "%Y-%m-%d")
                baseline_target = latest_dt - timedelta(days=eval_months * 30)
                baseline_record = min(
                    scores,
                    key=lambda r: abs(
                        (datetime.strptime(r["report_date"], "%Y-%m-%d") - baseline_target).days
                    ),
                )
                baseline_score = baseline_record["credit_score"]
                decline = baseline_score - latest_score
                cs_triggered = decline > thresholds["credit_score_decline_points"]

            # Factor 3: Minimum payment streak
            cur.execute(
                "SELECT min_payment_due, amount_paid FROM payment_history WHERE account_id = ? ORDER BY billing_period",
                (acc_id,),
            )
            payments = cur.fetchall()
            max_streak = 0
            cur_streak = 0
            for pay in payments:
                if abs(pay["amount_paid"] - pay["min_payment_due"]) < 0.01:
                    cur_streak += 1
                    max_streak = max(max_streak, cur_streak)
                else:
                    cur_streak = 0
            mp_triggered = max_streak >= thresholds["minimum_payment_consecutive_months"]

            # Factor 4: Regional delinquency
            region = acc["region_code"]
            raw_rate = region_delinq.get(region, 0)
            adj_val = regional_adj.get(region, {}).get("unemployment_adjustment", 0)
            adjusted_rate = raw_rate * (1 + adj_val)
            rd_triggered = adjusted_rate > thresholds["regional_delinquency_rate"]

            # Compute risk score
            triggered = {}
            if ca_triggered:
                triggered["cash_advance_ratio"] = weights["cash_advance_ratio"]
            if cs_triggered:
                triggered["credit_score_decline"] = weights["credit_score_decline"]
            if mp_triggered:
                triggered["minimum_payment_streak"] = weights["minimum_payment_streak"]
            if rd_triggered:
                triggered["regional_delinquency"] = weights["regional_delinquency"]

            raw_score = sum(triggered.values())

            dti = float(supp.get("debt_to_income_ratio", 0))
            if dti > dti_config["high_threshold"]:
                raw_score += dti_config["high_bonus"]
            elif dti > dti_config["moderate_threshold"]:
                raw_score += dti_config["moderate_bonus"]

            tier = acc["account_tier"]
            tier_mult = tier_config[tier]["risk_multiplier"]
            adjusted_score = round(raw_score * tier_mult, 2)

            if adjusted_score >= cutoff and triggered:
                if adjusted_score >= levels["critical"]:
                    risk_level = "critical"
                elif adjusted_score >= levels["high"]:
                    risk_level = "high"
                else:
                    risk_level = "moderate"

                primary = None
                max_w = -1
                for factor in factor_priority:
                    if factor in triggered and triggered[factor] > max_w:
                        max_w = triggered[factor]
                        primary = factor

                reduction_rate = tier_config[tier]["reduction_rates"][risk_level]
                new_limit = acc["credit_limit"] * (1 - reduction_rate)
                new_limit = max(500, new_limit)
                new_limit = int(new_limit // 100) * 100

                high_risk.append({
                    "account_id": acc_id,
                    "customer_name": acc["customer_name"],
                    "current_limit": int(acc["credit_limit"]),
                    "risk_score": adjusted_score,
                    "risk_level": risk_level,
                    "recommended_limit": new_limit,
                    "primary_risk_factor": primary,
                })

        conn.close()

        high_risk.sort(key=lambda x: (-x["risk_score"], x["account_id"]))
        return high_risk, len(active_accounts)

    # ===================== EVALUATION =====================

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
        expected, total_active = self._compute_ground_truth()

        level_counts = {}
        for acc in expected:
            level_counts[acc["risk_level"]] = level_counts.get(acc["risk_level"], 0) + 1

        eval_results = {}

        # --- Criterion 1: File exists (10 pts) ---
        csv_path = os.path.join(self.workspace, "high_risk_accounts.csv")
        file_exists = os.path.exists(csv_path)
        eval_results["file_exists"] = {
            "passed": file_exists,
            "score": 10 if file_exists else 0,
            "max_score": 10,
        }
        if not file_exists:
            eval_results["file_exists"]["reason"] = "high_risk_accounts.csv not found in workspace"

        # Try to read CSV
        predicted = []
        pred_columns = []
        if file_exists:
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    pred_columns = list(reader.fieldnames or [])
                    for row in reader:
                        predicted.append(row)
            except Exception:
                pred_columns = []

        # --- Criterion 2: Correct columns (10 pts) ---
        expected_cols = [
            "account_id", "customer_name", "current_limit",
            "risk_score", "risk_level", "recommended_limit", "primary_risk_factor",
        ]
        cols_match = pred_columns == expected_cols
        eval_results["correct_columns"] = {
            "passed": cols_match,
            "score": 10 if cols_match else 0,
            "max_score": 10,
        }
        if not cols_match:
            eval_results["correct_columns"]["reason"] = (
                f"Expected columns {expected_cols}, got {pred_columns}"
            )

        # --- Criterion 3: Correct account set (15 pts) ---
        expected_ids = set(a["account_id"] for a in expected)
        predicted_ids = set(r.get("account_id", "") for r in predicted)

        if len(expected_ids) == 0 and len(predicted_ids) == 0:
            f1 = 1.0
        elif len(expected_ids) == 0 or len(predicted_ids) == 0:
            f1 = 0.0
        else:
            tp = len(expected_ids & predicted_ids)
            precision = tp / len(predicted_ids)
            recall = tp / len(expected_ids)
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        score3 = round(15 * f1)
        eval_results["correct_account_set"] = {
            "passed": f1 == 1.0,
            "score": score3,
            "max_score": 15,
        }
        if f1 < 1.0:
            eval_results["correct_account_set"]["reason"] = (
                f"F1={f1:.3f}, expected {len(expected_ids)} accounts, "
                f"got {len(predicted_ids)}, overlap {len(expected_ids & predicted_ids)}"
            )

        # Build lookup maps for common accounts
        expected_map = {a["account_id"]: a for a in expected}
        predicted_map = {r["account_id"]: r for r in predicted if "account_id" in r}
        common_ids = expected_ids & predicted_ids

        # --- Criterion 4: Correct risk scores (15 pts) ---
        if common_ids:
            score_matches = 0
            for aid in common_ids:
                try:
                    pred_score = float(predicted_map[aid]["risk_score"])
                    exp_score = expected_map[aid]["risk_score"]
                    if abs(pred_score - exp_score) < 0.015:
                        score_matches += 1
                except (ValueError, KeyError):
                    pass
            ratio4 = score_matches / len(common_ids)
        else:
            ratio4 = 0.0 if expected_ids else 1.0

        score4 = round(15 * ratio4)
        eval_results["correct_risk_scores"] = {
            "passed": ratio4 == 1.0,
            "score": score4,
            "max_score": 15,
        }
        if ratio4 < 1.0:
            eval_results["correct_risk_scores"]["reason"] = (
                f"{score_matches if common_ids else 0}/{len(common_ids) if common_ids else 0} scores match"
            )

        # --- Criterion 5: Correct risk levels (10 pts) ---
        if common_ids:
            level_matches = sum(
                1 for aid in common_ids
                if predicted_map[aid].get("risk_level") == expected_map[aid]["risk_level"]
            )
            ratio5 = level_matches / len(common_ids)
        else:
            ratio5 = 0.0 if expected_ids else 1.0

        score5 = round(10 * ratio5)
        eval_results["correct_risk_levels"] = {
            "passed": ratio5 == 1.0,
            "score": score5,
            "max_score": 10,
        }
        if ratio5 < 1.0:
            eval_results["correct_risk_levels"]["reason"] = (
                f"{level_matches if common_ids else 0}/{len(common_ids) if common_ids else 0} levels match"
            )

        # --- Criterion 6: Correct recommended limits (10 pts) ---
        if common_ids:
            limit_matches = 0
            for aid in common_ids:
                try:
                    pred_limit = int(float(predicted_map[aid]["recommended_limit"]))
                    exp_limit = expected_map[aid]["recommended_limit"]
                    if pred_limit == exp_limit:
                        limit_matches += 1
                except (ValueError, KeyError):
                    pass
            ratio6 = limit_matches / len(common_ids)
        else:
            ratio6 = 0.0 if expected_ids else 1.0

        score6 = round(10 * ratio6)
        eval_results["correct_recommended_limits"] = {
            "passed": ratio6 == 1.0,
            "score": score6,
            "max_score": 10,
        }
        if ratio6 < 1.0:
            eval_results["correct_recommended_limits"]["reason"] = (
                f"{limit_matches if common_ids else 0}/{len(common_ids) if common_ids else 0} limits match"
            )

        # --- Criterion 7: Correct primary risk factors (10 pts) ---
        if common_ids:
            factor_matches = sum(
                1 for aid in common_ids
                if predicted_map[aid].get("primary_risk_factor") == expected_map[aid]["primary_risk_factor"]
            )
            ratio7 = factor_matches / len(common_ids)
        else:
            ratio7 = 0.0 if expected_ids else 1.0

        score7 = round(10 * ratio7)
        eval_results["correct_primary_factors"] = {
            "passed": ratio7 == 1.0,
            "score": score7,
            "max_score": 10,
        }
        if ratio7 < 1.0:
            eval_results["correct_primary_factors"]["reason"] = (
                f"{factor_matches if common_ids else 0}/{len(common_ids) if common_ids else 0} factors match"
            )

        # --- Criterion 8: Correct sorting (10 pts) ---
        correct_order = True
        if len(predicted) >= 2:
            for i in range(len(predicted) - 1):
                try:
                    s1 = float(predicted[i]["risk_score"])
                    s2 = float(predicted[i + 1]["risk_score"])
                    if s1 < s2:
                        correct_order = False
                        break
                    if abs(s1 - s2) < 0.001 and predicted[i]["account_id"] > predicted[i + 1]["account_id"]:
                        correct_order = False
                        break
                except (ValueError, KeyError):
                    correct_order = False
                    break

        eval_results["correct_sorting"] = {
            "passed": correct_order,
            "score": 10 if correct_order else 0,
            "max_score": 10,
        }
        if not correct_order:
            eval_results["correct_sorting"]["reason"] = (
                "Rows not sorted by risk_score descending, account_id ascending"
            )

        # --- Criterion 9: Response summary (10 pts) ---
        summary_correct = False
        try:
            nums = [int(n) for n in re.findall(r"\b(\d+)\b", action)]
            has_total = total_active in nums
            has_flagged = len(expected) in nums
            has_levels = all(
                count in nums for count in level_counts.values() if count > 0
            )
            summary_correct = has_total and has_flagged and has_levels
        except Exception:
            summary_correct = False

        eval_results["response_summary"] = {
            "passed": summary_correct,
            "score": 10 if summary_correct else 0,
            "max_score": 10,
        }
        if not summary_correct:
            eval_results["response_summary"]["reason"] = (
                f"Expected: {total_active} active, {len(expected)} flagged, levels: {level_counts}"
            )

        total_score = sum(c["score"] for c in eval_results.values())
        max_score = sum(c["max_score"] for c in eval_results.values())

        return total_score / max_score if max_score > 0 else 0.0, {
            "eval_criteria": eval_results,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ===================== VERIFICATION =====================

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
        import yaml

        # --- Read workspace configuration files ---
        with open(os.path.join(self.workspace, "risk_thresholds.yaml")) as f:
            risk_config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "tier_config.json")) as f:
            tier_config = json.load(f)
        with open(os.path.join(self.workspace, "regional_adjustments.json")) as f:
            regional_adj = json.load(f)
        with open(os.path.join(self.workspace, "limit_adjustment_policy.md")) as f:
            _ = f.read()  # Read policy for awareness

        # Read supplement data from all CSV files
        supplement = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "account_supplement_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    supplement[row["account_id"]] = row

        weights = risk_config["scoring_weights"]
        thresholds = risk_config["thresholds"]
        dti_config = risk_config["dti_bonus"]
        cutoff = risk_config["high_risk_cutoff"]
        levels = risk_config["risk_levels"]
        factor_priority = risk_config["factor_priority"]
        eval_months = risk_config["evaluation_period_months"]

        # --- List all accounts via paginated tool calls ---
        all_accounts = []
        page = 1
        while True:
            result = self.tools["list_accounts"](page=page, page_size=20)
            all_accounts.extend(result["accounts"])
            if page >= result["total_pages"]:
                break
            page += 1

        active_accounts = [a for a in all_accounts if a["status"] == "active"]

        # --- Get regional delinquency rates (one call per region) ---
        regions = set(a["region_code"] for a in active_accounts)
        region_delinq = {}
        for region in sorted(regions):
            result = self.tools["get_regional_delinquency"](region_code=region)
            if "records" in result and result["records"]:
                region_delinq[region] = result["records"][0]["delinquency_rate"]

        # --- Process each active account ---
        high_risk = []
        for acc in active_accounts:
            acc_id = acc["account_id"]

            # Check hardship exclusion
            supp = supplement.get(acc_id, {})
            if supp.get("hardship_program") == "yes":
                continue

            # Factor 1: Cash advance ratio
            tx_result = self.tools["get_account_transactions"](account_id=acc_id)
            txns = tx_result.get("transactions", [])
            total_amount = sum(t["amount"] for t in txns)
            ca_amount = sum(t["amount"] for t in txns if t["tx_type"] == "cash_advance")
            ca_ratio = ca_amount / total_amount if total_amount > 0 else 0
            ca_triggered = ca_ratio > thresholds["cash_advance_ratio"]

            # Factor 2: Credit score decline
            cb_result = self.tools["get_credit_bureau_records"](account_id=acc_id)
            scores = cb_result.get("records", [])
            cs_triggered = False
            if len(scores) >= 2:
                latest_score = scores[-1]["credit_score"]
                latest_dt = datetime.strptime(scores[-1]["report_date"], "%Y-%m-%d")
                baseline_target = latest_dt - timedelta(days=eval_months * 30)
                baseline_record = min(
                    scores,
                    key=lambda r: abs(
                        (datetime.strptime(r["report_date"], "%Y-%m-%d") - baseline_target).days
                    ),
                )
                baseline_score = baseline_record["credit_score"]
                decline = baseline_score - latest_score
                cs_triggered = decline > thresholds["credit_score_decline_points"]

            # Factor 3: Minimum payment streak
            ph_result = self.tools["get_payment_history"](account_id=acc_id)
            payments = ph_result.get("records", [])
            max_streak = 0
            cur_streak = 0
            for pay in payments:
                if abs(pay["amount_paid"] - pay["min_payment_due"]) < 0.01:
                    cur_streak += 1
                    max_streak = max(max_streak, cur_streak)
                else:
                    cur_streak = 0
            mp_triggered = max_streak >= thresholds["minimum_payment_consecutive_months"]

            # Factor 4: Regional delinquency (with adjustment)
            region = acc["region_code"]
            raw_rate = region_delinq.get(region, 0)
            adj_val = regional_adj.get(region, {}).get("unemployment_adjustment", 0)
            adjusted_rate = raw_rate * (1 + adj_val)
            rd_triggered = adjusted_rate > thresholds["regional_delinquency_rate"]

            # Build triggered factors
            triggered = {}
            if ca_triggered:
                triggered["cash_advance_ratio"] = weights["cash_advance_ratio"]
            if cs_triggered:
                triggered["credit_score_decline"] = weights["credit_score_decline"]
            if mp_triggered:
                triggered["minimum_payment_streak"] = weights["minimum_payment_streak"]
            if rd_triggered:
                triggered["regional_delinquency"] = weights["regional_delinquency"]

            raw_score = sum(triggered.values())

            # DTI bonus
            dti = float(supp.get("debt_to_income_ratio", 0))
            if dti > dti_config["high_threshold"]:
                raw_score += dti_config["high_bonus"]
            elif dti > dti_config["moderate_threshold"]:
                raw_score += dti_config["moderate_bonus"]

            # Tier multiplier
            tier = acc["account_tier"]
            tier_mult = tier_config[tier]["risk_multiplier"]
            adjusted_score = round(raw_score * tier_mult, 2)

            # Check cutoff
            if adjusted_score >= cutoff and triggered:
                if adjusted_score >= levels["critical"]:
                    risk_level = "critical"
                elif adjusted_score >= levels["high"]:
                    risk_level = "high"
                else:
                    risk_level = "moderate"

                # Primary risk factor
                primary = None
                max_w = -1
                for factor in factor_priority:
                    if factor in triggered and triggered[factor] > max_w:
                        max_w = triggered[factor]
                        primary = factor

                # Recommended limit
                reduction_rate = tier_config[tier]["reduction_rates"][risk_level]
                new_limit = acc["credit_limit"] * (1 - reduction_rate)
                new_limit = max(500, new_limit)
                new_limit = int(new_limit // 100) * 100

                high_risk.append({
                    "account_id": acc_id,
                    "customer_name": acc["customer_name"],
                    "current_limit": int(acc["credit_limit"]),
                    "risk_score": adjusted_score,
                    "risk_level": risk_level,
                    "recommended_limit": new_limit,
                    "primary_risk_factor": primary,
                })

        # Sort by risk_score descending, account_id ascending
        high_risk.sort(key=lambda x: (-x["risk_score"], x["account_id"]))

        # Write output CSV
        csv_path = os.path.join(self.workspace, "high_risk_accounts.csv")
        fieldnames = [
            "account_id", "customer_name", "current_limit",
            "risk_score", "risk_level", "recommended_limit", "primary_risk_factor",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for acc in high_risk:
                writer.writerow({
                    "account_id": acc["account_id"],
                    "customer_name": acc["customer_name"],
                    "current_limit": acc["current_limit"],
                    "risk_score": f"{acc['risk_score']:.2f}",
                    "risk_level": acc["risk_level"],
                    "recommended_limit": acc["recommended_limit"],
                    "primary_risk_factor": acc["primary_risk_factor"],
                })

        # Build summary action
        level_summary_parts = {}
        for acc in high_risk:
            level_summary_parts[acc["risk_level"]] = level_summary_parts.get(acc["risk_level"], 0) + 1

        level_str = ", ".join(
            f"{count} {level}" for level, count in sorted(level_summary_parts.items())
        )
        action = (
            f"Evaluated {len(active_accounts)} active accounts. "
            f"{len(high_risk)} accounts flagged as high risk: {level_str}."
        )

        return self.step(action)
