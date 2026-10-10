"""
Environment for franchisee marketing promotion compliance monitoring task.
Provides tools for querying franchisee data, promotion details, POS transactions,
and coupon redemptions. Evaluates corrective action list completeness and accuracy.
"""

import csv
import json
import os
import sqlite3
import yaml
from typing import Tuple, Dict, List, Any

import pandas as pd


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
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

    # ==================== Tool Methods ====================

    @tool(
        description="List franchisees with pagination. Returns a page of franchisee records including id, name, region, tier, and active status.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based)",
                    "default": 1
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 20)",
                    "default": 20
                }
            },
            "required": []
        }
    )
    def list_franchisees(self, page: int = 1, page_size: int = 20):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM franchisees")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT franchisee_id, name, region, tier, is_active FROM franchisees ORDER BY franchisee_id LIMIT ? OFFSET ?",
            (page_size, offset)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "franchisees": rows
        }

    @tool(
        description="Get detailed information about a specific franchisee by ID.",
        parameters={
            "type": "object",
            "properties": {
                "franchisee_id": {
                    "type": "string",
                    "description": "The franchisee ID (e.g. FR-0001)"
                }
            },
            "required": ["franchisee_id"]
        }
    )
    def get_franchisee_details(self, franchisee_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM franchisees WHERE franchisee_id = ?", (franchisee_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Franchisee {franchisee_id} not found"}
        return dict(row)

    @tool(
        description="List all national marketing promotions with their basic information including ID, name, type, and status.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    def list_promotions(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT promotion_id, name, type, status FROM promotions ORDER BY promotion_id")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"promotions": rows}

    @tool(
        description="Get detailed information about a specific promotion including required discount percentage, minimum local ad spend, mandatory status, and date range.",
        parameters={
            "type": "object",
            "properties": {
                "promotion_id": {
                    "type": "string",
                    "description": "The promotion ID (e.g. PROMO-001)"
                }
            },
            "required": ["promotion_id"]
        }
    )
    def get_promotion_details(self, promotion_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM promotions WHERE promotion_id = ?", (promotion_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Promotion {promotion_id} not found"}
        return dict(row)

    @tool(
        description="Get discount analysis for a specific franchisee. Returns per-promotion statistics including average applied discount, transaction count, and min/max discounts observed.",
        parameters={
            "type": "object",
            "properties": {
                "franchisee_id": {
                    "type": "string",
                    "description": "The franchisee ID (e.g. FR-0001)"
                }
            },
            "required": ["franchisee_id"]
        }
    )
    def get_discount_analysis(self, franchisee_id: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT promotion_id,
                   COUNT(*) as transaction_count,
                   ROUND(AVG(applied_discount_pct), 2) as avg_discount_pct,
                   ROUND(MIN(applied_discount_pct), 2) as min_discount_pct,
                   ROUND(MAX(applied_discount_pct), 2) as max_discount_pct,
                   ROUND(SUM(original_price * quantity), 2) as total_gross_sales
            FROM pos_transactions
            WHERE franchisee_id = ?
            GROUP BY promotion_id
            ORDER BY promotion_id
        """, (franchisee_id,))
        columns = [desc[0] for desc in cur.description]
        rows = [dict(zip(columns, r)) for r in cur.fetchall()]
        conn.close()
        return {
            "franchisee_id": franchisee_id,
            "promotion_stats": rows
        }

    @tool(
        description="Get coupon redemption statistics for a specific franchisee. Returns per-promotion counts of valid, invalid, and expired coupon redemptions.",
        parameters={
            "type": "object",
            "properties": {
                "franchisee_id": {
                    "type": "string",
                    "description": "The franchisee ID (e.g. FR-0001)"
                }
            },
            "required": ["franchisee_id"]
        }
    )
    def get_coupon_analysis(self, franchisee_id: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT promotion_id,
                   COUNT(*) as total_redemptions,
                   SUM(CASE WHEN status = 'valid' THEN 1 ELSE 0 END) as valid_count,
                   SUM(CASE WHEN status = 'invalid' THEN 1 ELSE 0 END) as invalid_count,
                   SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END) as expired_count,
                   ROUND(SUM(discount_amount), 2) as total_discount_amount
            FROM coupon_redemptions
            WHERE franchisee_id = ?
            GROUP BY promotion_id
            ORDER BY promotion_id
        """, (franchisee_id,))
        columns = [desc[0] for desc in cur.description]
        rows = [dict(zip(columns, r)) for r in cur.fetchall()]
        conn.close()
        return {
            "franchisee_id": franchisee_id,
            "coupon_stats": rows
        }

    # ==================== Ground Truth Computation ====================

    def _compute_ground_truth(self) -> List[Dict]:
        """Compute the expected corrective actions from DB + workspace files."""
        # Load compliance thresholds
        config_path = os.path.join(self.workspace, "compliance_thresholds.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        discount_tolerance = config["discount_tolerance_pct"]
        max_coupon_invalid_rate = config["max_coupon_invalid_rate_pct"]
        severity_rules = config["severity_rules"]
        recommended_actions = config["recommended_actions"]

        # Load promotion calendar for mandatory flags
        cal_path = os.path.join(self.workspace, "promotion_calendar.json")
        with open(cal_path, "r") as f:
            promo_calendar = json.load(f)
        mandatory_promos = {p["promotion_id"] for p in promo_calendar if p["participation"] == "mandatory"}

        # Load DB data
        conn = sqlite3.connect(self.db_path)
        franchisees = pd.read_sql("SELECT * FROM franchisees", conn)
        promotions = pd.read_sql("SELECT * FROM promotions", conn)
        pos_txns = pd.read_sql("SELECT * FROM pos_transactions", conn)
        coupons = pd.read_sql("SELECT * FROM coupon_redemptions", conn)
        conn.close()

        promo_details = {row["promotion_id"]: row for _, row in promotions.iterrows()}
        franchisee_names = dict(zip(franchisees["franchisee_id"], franchisees["name"]))

        # Load ad spend from workspace
        ad_reports_dir = os.path.join(self.workspace, "ad_reports")
        ad_spend_by_franchisee = {}
        if os.path.isdir(ad_reports_dir):
            for fname in os.listdir(ad_reports_dir):
                if fname.endswith("_ad_spend.csv"):
                    fid = fname.replace("_ad_spend.csv", "")
                    fpath = os.path.join(ad_reports_dir, fname)
                    df = pd.read_csv(fpath)
                    # Sum actual_spend per promotion
                    spend_by_promo = df.groupby("promotion_id")["actual_spend"].sum().to_dict()
                    ad_spend_by_franchisee[fid] = spend_by_promo

        violations = []

        for _, fr in franchisees.iterrows():
            fid = fr["franchisee_id"]
            fname = fr["name"]

            # 1. Discount violations
            fr_txns = pos_txns[pos_txns["franchisee_id"] == fid]
            participated_promos = set(fr_txns["promotion_id"].unique())

            for pid in participated_promos:
                promo = promo_details[pid]
                required = promo["required_discount_pct"]
                promo_txns = fr_txns[fr_txns["promotion_id"] == pid]
                avg_discount = promo_txns["applied_discount_pct"].mean()
                deviation = abs(avg_discount - required)

                if deviation > discount_tolerance:
                    severity = self._classify_severity(
                        deviation, severity_rules["discount_violation"], "min_deviation_pct"
                    )
                    action = recommended_actions["discount_violation"][severity]
                    violations.append({
                        "franchisee_id": fid,
                        "franchisee_name": fname,
                        "promotion_id": pid,
                        "promotion_name": promo["name"],
                        "violation_type": "discount_violation",
                        "severity": severity,
                        "details": f"Average applied discount {avg_discount:.1f}% vs required {required:.1f}% (deviation: {deviation:.1f}%)",
                        "recommended_action": action,
                    })

            # 2. Underfunded campaign violations
            if fid in ad_spend_by_franchisee:
                for pid, actual_total in ad_spend_by_franchisee[fid].items():
                    if pid in promo_details:
                        min_spend = promo_details[pid]["min_local_ad_spend"]
                        if actual_total < min_spend:
                            funding_ratio = (actual_total / min_spend) * 100
                            severity = self._classify_severity_underfunded(
                                funding_ratio, severity_rules["underfunded_campaign"]
                            )
                            action = recommended_actions["underfunded_campaign"][severity]
                            shortfall = min_spend - actual_total
                            violations.append({
                                "franchisee_id": fid,
                                "franchisee_name": fname,
                                "promotion_id": pid,
                                "promotion_name": promo_details[pid]["name"],
                                "violation_type": "underfunded_campaign",
                                "severity": severity,
                                "details": f"Actual spend ${actual_total:.2f} vs minimum ${min_spend:.2f} (shortfall: ${shortfall:.2f}, funded {funding_ratio:.1f}%)",
                                "recommended_action": action,
                            })

            # 3. Coupon violations
            fr_coupons = coupons[coupons["franchisee_id"] == fid]
            if len(fr_coupons) > 0:
                total_coupons = len(fr_coupons)
                invalid_expired = len(fr_coupons[fr_coupons["status"].isin(["invalid", "expired"])])
                invalid_rate = (invalid_expired / total_coupons) * 100

                if invalid_rate > max_coupon_invalid_rate:
                    severity = self._classify_severity(
                        invalid_rate, severity_rules["coupon_violation"], "min_invalid_rate_pct"
                    )
                    action = recommended_actions["coupon_violation"][severity]
                    violations.append({
                        "franchisee_id": fid,
                        "franchisee_name": fname,
                        "promotion_id": "ALL",
                        "promotion_name": "All Promotions",
                        "violation_type": "coupon_violation",
                        "severity": severity,
                        "details": f"Invalid/expired coupon rate {invalid_rate:.1f}% exceeds maximum {max_coupon_invalid_rate:.1f}% ({invalid_expired} of {total_coupons} redemptions)",
                        "recommended_action": action,
                    })

            # 4. Non-participation violations
            for pid in mandatory_promos:
                if pid not in participated_promos:
                    promo = promo_details[pid]
                    severity = "HIGH"
                    action = recommended_actions["non_participation"][severity]
                    violations.append({
                        "franchisee_id": fid,
                        "franchisee_name": fname,
                        "promotion_id": pid,
                        "promotion_name": promo["name"],
                        "violation_type": "non_participation",
                        "severity": severity,
                        "details": f"No transactions recorded for mandatory promotion '{promo['name']}'",
                        "recommended_action": action,
                    })

        # Sort: severity order (CRITICAL > HIGH > MEDIUM), then franchisee_id, then promotion_id
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        violations.sort(key=lambda v: (severity_order.get(v["severity"], 9), v["franchisee_id"], v["promotion_id"]))

        return violations

    def _classify_severity(self, value, rules, key):
        """Classify severity based on threshold rules (higher value = more severe)."""
        for sev in ["CRITICAL", "HIGH", "MEDIUM"]:
            if sev in rules and value >= rules[sev][key]:
                return sev
        return "MEDIUM"

    def _classify_severity_underfunded(self, funding_ratio, rules):
        """Classify underfunded severity (lower ratio = more severe)."""
        for sev in ["CRITICAL", "HIGH", "MEDIUM"]:
            if sev in rules and funding_ratio <= rules[sev]["max_funding_ratio_pct"]:
                return sev
        return "MEDIUM"

    # ==================== Evaluation ====================

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

        # Criterion 1: corrective_actions.csv exists and is valid CSV (10 pts)
        csv_path = os.path.join(self.workspace, "corrective_actions.csv")
        c1_score = 0
        c1_max = 10
        csv_rows = []
        if os.path.isfile(csv_path):
            try:
                with open(csv_path, "r") as f:
                    reader = csv.DictReader(f)
                    csv_rows = list(reader)
                if len(csv_rows) > 0:
                    c1_score = 10
            except Exception:
                pass
        eval_criteria["csv_file_valid"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": "" if c1_score == c1_max else "corrective_actions.csv missing or invalid"
        }
        total_score += c1_score
        max_score += c1_max

        # Criterion 2: CSV has correct columns (10 pts)
        expected_columns = {"franchisee_id", "franchisee_name", "promotion_id", "promotion_name",
                            "violation_type", "severity", "details", "recommended_action"}
        c2_score = 0
        c2_max = 10
        if csv_rows:
            actual_columns = set(csv_rows[0].keys())
            if expected_columns.issubset(actual_columns):
                c2_score = 10
        eval_criteria["csv_correct_columns"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": "" if c2_score == c2_max else f"Missing columns: {expected_columns - set(csv_rows[0].keys()) if csv_rows else expected_columns}"
        }
        total_score += c2_score
        max_score += c2_max

        # Criterion 3: Correct number of violations identified (15 pts)
        c3_max = 15
        gt_count = len(ground_truth)
        agent_count = len(csv_rows)
        if gt_count > 0 and agent_count == gt_count:
            c3_score = 15
        elif gt_count > 0:
            ratio = 1.0 - abs(agent_count - gt_count) / gt_count
            c3_score = max(0, round(ratio * 15))
        else:
            c3_score = 15 if agent_count == 0 else 0
        eval_criteria["violation_count_accuracy"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": "" if c3_score == c3_max else f"Expected {gt_count} violations, found {agent_count}"
        }
        total_score += c3_score
        max_score += c3_max

        # Criterion 4: Correct violation identification (25 pts)
        # Match by (franchisee_id, promotion_id, violation_type)
        c4_max = 25
        gt_keys = {(v["franchisee_id"], v["promotion_id"], v["violation_type"]) for v in ground_truth}
        agent_keys = set()
        for row in csv_rows:
            key = (row.get("franchisee_id", ""), row.get("promotion_id", ""), row.get("violation_type", ""))
            agent_keys.add(key)

        if len(gt_keys) > 0:
            correct = len(gt_keys & agent_keys)
            c4_score = round((correct / len(gt_keys)) * c4_max)
        else:
            c4_score = c4_max if len(agent_keys) == 0 else 0
        eval_criteria["violation_identification"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": "" if c4_score == c4_max else f"Matched {correct if gt_keys else 0}/{len(gt_keys)} violations"
        }
        total_score += c4_score
        max_score += c4_max

        # Criterion 5: Correct severity classification (15 pts)
        c5_max = 15
        gt_severity = {(v["franchisee_id"], v["promotion_id"], v["violation_type"]): v["severity"] for v in ground_truth}
        severity_correct = 0
        severity_total = len(gt_severity)
        for row in csv_rows:
            key = (row.get("franchisee_id", ""), row.get("promotion_id", ""), row.get("violation_type", ""))
            if key in gt_severity and row.get("severity", "") == gt_severity[key]:
                severity_correct += 1
        if severity_total > 0:
            c5_score = round((severity_correct / severity_total) * c5_max)
        else:
            c5_score = c5_max
        eval_criteria["severity_classification"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": "" if c5_score == c5_max else f"Correct severity for {severity_correct}/{severity_total} violations"
        }
        total_score += c5_score
        max_score += c5_max

        # Criterion 6: Correct sort order (10 pts)
        c6_max = 10
        c6_score = 0
        if csv_rows and len(csv_rows) > 1:
            severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
            is_sorted = True
            for i in range(len(csv_rows) - 1):
                curr = csv_rows[i]
                nxt = csv_rows[i + 1]
                curr_key = (severity_order.get(curr.get("severity", ""), 9), curr.get("franchisee_id", ""), curr.get("promotion_id", ""))
                nxt_key = (severity_order.get(nxt.get("severity", ""), 9), nxt.get("franchisee_id", ""), nxt.get("promotion_id", ""))
                if curr_key > nxt_key:
                    is_sorted = False
                    break
            if is_sorted:
                c6_score = 10
        elif len(csv_rows) <= 1:
            c6_score = 10
        eval_criteria["correct_sort_order"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": "" if c6_score == c6_max else "Rows not sorted by severity (desc), then franchisee_id (asc), then promotion_id (asc)"
        }
        total_score += c6_score
        max_score += c6_max

        # Criterion 7: Response contains summary statistics (15 pts)
        c7_max = 15
        c7_score = 0
        action_lower = action.lower()
        # Check for key summary elements in the response
        checks = {
            "total_violations": any(str(len(ground_truth)) in action for _ in [1]),
            "violation_types_mentioned": sum(1 for vt in ["discount_violation", "underfunded_campaign", "coupon_violation", "non_participation"]
                                             if vt.replace("_", " ") in action_lower or vt in action_lower) >= 3,
            "severity_breakdown": any(s in action_lower for s in ["critical", "high", "medium"]),
        }
        points_per_check = c7_max / len(checks)
        for check_name, passed in checks.items():
            if passed:
                c7_score += points_per_check
        c7_score = round(c7_score)
        eval_criteria["response_summary"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": "" if c7_score == c7_max else f"Missing summary elements: {[k for k, v in checks.items() if not v]}"
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

    # ==================== Verification ====================

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
        import yaml as _yaml

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # Step 1: Read compliance configuration from workspace
        with open(os.path.join(self.workspace, "compliance_thresholds.yaml"), "r") as f:
            config = _yaml.safe_load(f)

        discount_tolerance = config["discount_tolerance_pct"]
        max_coupon_invalid_rate = config["max_coupon_invalid_rate_pct"]
        severity_rules = config["severity_rules"]
        rec_actions = config["recommended_actions"]

        # Step 2: Read promotion calendar for mandatory flags
        with open(os.path.join(self.workspace, "promotion_calendar.json"), "r") as f:
            promo_calendar = json.load(f)
        mandatory_promos = {p["promotion_id"] for p in promo_calendar if p["participation"] == "mandatory"}

        # Step 3: List all franchisees via tool
        all_franchisees = []
        page = 1
        while True:
            result = call_tool("list_franchisees", page=page, page_size=20)
            all_franchisees.extend(result["franchisees"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 4: List all promotions and get details via tools
        promo_list = call_tool("list_promotions")
        promo_details = {}
        for p in promo_list["promotions"]:
            details = call_tool("get_promotion_details", promotion_id=p["promotion_id"])
            promo_details[p["promotion_id"]] = details

        # Step 5: Read ad spend reports from workspace
        ad_reports_dir = os.path.join(self.workspace, "ad_reports")
        ad_spend_by_franchisee = {}
        if os.path.isdir(ad_reports_dir):
            for fname in os.listdir(ad_reports_dir):
                if fname.endswith("_ad_spend.csv"):
                    fid = fname.replace("_ad_spend.csv", "")
                    fpath = os.path.join(ad_reports_dir, fname)
                    df = pd.read_csv(fpath)
                    spend_by_promo = df.groupby("promotion_id")["actual_spend"].sum().to_dict()
                    ad_spend_by_franchisee[fid] = spend_by_promo

        # Step 6: Analyze each franchisee for violations
        violations = []

        for fr in all_franchisees:
            fid = fr["franchisee_id"]
            fname = fr["name"]

            # Get discount analysis via tool
            discount_result = call_tool("get_discount_analysis", franchisee_id=fid)
            participated_promos = set()

            for stat in discount_result["promotion_stats"]:
                pid = stat["promotion_id"]
                participated_promos.add(pid)
                if pid in promo_details:
                    required = promo_details[pid]["required_discount_pct"]
                    avg_discount = stat["avg_discount_pct"]
                    deviation = abs(avg_discount - required)

                    if deviation > discount_tolerance:
                        severity = self._classify_severity_verify(
                            deviation, severity_rules["discount_violation"], "min_deviation_pct"
                        )
                        action = rec_actions["discount_violation"][severity]
                        violations.append({
                            "franchisee_id": fid,
                            "franchisee_name": fname,
                            "promotion_id": pid,
                            "promotion_name": promo_details[pid]["name"],
                            "violation_type": "discount_violation",
                            "severity": severity,
                            "details": f"Average applied discount {avg_discount:.1f}% vs required {required:.1f}% (deviation: {deviation:.1f}%)",
                            "recommended_action": action,
                        })

            # Get coupon analysis via tool
            coupon_result = call_tool("get_coupon_analysis", franchisee_id=fid)
            total_coupons = sum(s["total_redemptions"] for s in coupon_result["coupon_stats"])
            total_invalid = sum(s["invalid_count"] + s["expired_count"] for s in coupon_result["coupon_stats"])

            if total_coupons > 0:
                invalid_rate = (total_invalid / total_coupons) * 100
                if invalid_rate > max_coupon_invalid_rate:
                    severity = self._classify_severity_verify(
                        invalid_rate, severity_rules["coupon_violation"], "min_invalid_rate_pct"
                    )
                    action = rec_actions["coupon_violation"][severity]
                    violations.append({
                        "franchisee_id": fid,
                        "franchisee_name": fname,
                        "promotion_id": "ALL",
                        "promotion_name": "All Promotions",
                        "violation_type": "coupon_violation",
                        "severity": severity,
                        "details": f"Invalid/expired coupon rate {invalid_rate:.1f}% exceeds maximum {max_coupon_invalid_rate:.1f}% ({total_invalid} of {total_coupons} redemptions)",
                        "recommended_action": action,
                    })

            # Check underfunded campaigns from workspace files
            if fid in ad_spend_by_franchisee:
                for pid, actual_total in ad_spend_by_franchisee[fid].items():
                    if pid in promo_details:
                        min_spend = promo_details[pid]["min_local_ad_spend"]
                        if actual_total < min_spend:
                            funding_ratio = (actual_total / min_spend) * 100
                            severity = self._classify_severity_underfunded_verify(
                                funding_ratio, severity_rules["underfunded_campaign"]
                            )
                            action = rec_actions["underfunded_campaign"][severity]
                            shortfall = min_spend - actual_total
                            violations.append({
                                "franchisee_id": fid,
                                "franchisee_name": fname,
                                "promotion_id": pid,
                                "promotion_name": promo_details[pid]["name"],
                                "violation_type": "underfunded_campaign",
                                "severity": severity,
                                "details": f"Actual spend ${actual_total:.2f} vs minimum ${min_spend:.2f} (shortfall: ${shortfall:.2f}, funded {funding_ratio:.1f}%)",
                                "recommended_action": action,
                            })

            # Check non-participation in mandatory promotions
            for pid in mandatory_promos:
                if pid not in participated_promos:
                    promo = promo_details[pid]
                    severity = "HIGH"
                    action = rec_actions["non_participation"][severity]
                    violations.append({
                        "franchisee_id": fid,
                        "franchisee_name": fname,
                        "promotion_id": pid,
                        "promotion_name": promo["name"],
                        "violation_type": "non_participation",
                        "severity": severity,
                        "details": f"No transactions recorded for mandatory promotion '{promo['name']}'",
                        "recommended_action": action,
                    })

        # Sort violations
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        violations.sort(key=lambda v: (severity_order.get(v["severity"], 9), v["franchisee_id"], v["promotion_id"]))

        # Write corrective_actions.csv
        csv_path = os.path.join(self.workspace, "corrective_actions.csv")
        fieldnames = ["franchisee_id", "franchisee_name", "promotion_id", "promotion_name",
                      "violation_type", "severity", "details", "recommended_action"]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for v in violations:
                writer.writerow(v)

        # Build summary response
        type_counts = {}
        severity_counts = {}
        for v in violations:
            type_counts[v["violation_type"]] = type_counts.get(v["violation_type"], 0) + 1
            severity_counts[v["severity"]] = severity_counts.get(v["severity"], 0) + 1

        summary_lines = [
            f"Franchise Marketing Compliance Audit Complete.",
            f"",
            f"Total violations identified: {len(violations)}",
            f"",
            f"Violations by type:",
        ]
        for vt, count in sorted(type_counts.items()):
            summary_lines.append(f"  - {vt}: {count}")
        summary_lines.append("")
        summary_lines.append("Violations by severity:")
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            if sev in severity_counts:
                summary_lines.append(f"  - {sev}: {severity_counts[sev]}")
        summary_lines.append("")
        summary_lines.append(f"Corrective actions have been saved to corrective_actions.csv with {len(violations)} entries.")
        summary_lines.append(f"The file contains columns: {', '.join(fieldnames)}.")
        summary_lines.append(f"Results are sorted by severity (CRITICAL first), then by franchisee_id, then by promotion_id.")

        action_str = "\n".join(summary_lines)

        print(f"Verify used {tool_call_count} tool calls")
        return self.step(action_str)

    def _classify_severity_verify(self, value, rules, key):
        """Classify severity (used in verify to mirror step logic without DB access)."""
        for sev in ["CRITICAL", "HIGH", "MEDIUM"]:
            if sev in rules and value >= rules[sev][key]:
                return sev
        return "MEDIUM"

    def _classify_severity_underfunded_verify(self, funding_ratio, rules):
        """Classify underfunded severity in verify."""
        for sev in ["CRITICAL", "HIGH", "MEDIUM"]:
            if sev in rules and funding_ratio <= rules[sev]["max_funding_ratio_pct"]:
                return sev
        return "MEDIUM"
