"""
Environment for billing discrepancy reconciliation task.
Defines tools for querying customer data and evaluating the agent's
adjustment report.
"""

import csv
import json
import math
import os
import sqlite3
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
    # Helper
    # ------------------------------------------------------------------
    def _query(self, sql, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @tool(
        description="List customers with pagination. Returns a page of customer records including customer_id, full_name, email, account_status, and signup_date.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 20).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_customers(self, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        total = self._query("SELECT COUNT(*) as cnt FROM customers")[0]["cnt"]
        rows = self._query(
            "SELECT customer_id, full_name, email, account_status, signup_date "
            "FROM customers ORDER BY customer_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        return {
            "page": page,
            "page_size": page_size,
            "total_customers": total,
            "total_pages": math.ceil(total / page_size),
            "customers": rows,
        }

    @tool(
        description="Get subscription plan details for a specific customer, including plan tier, bundle type, and contract dates.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The customer ID, e.g. CUST-00001.",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_customer_subscription(self, customer_id: str):
        rows = self._query(
            "SELECT * FROM subscription_plans WHERE customer_id = ?",
            (customer_id,),
        )
        if not rows:
            return {"error": f"No subscription found for {customer_id}"}
        return rows[0]

    @tool(
        description="Get discount eligibility records for a customer, showing which promotional codes they are eligible for, the eligibility window, and current status (active/expired).",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The customer ID.",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_discount_eligibility(self, customer_id: str):
        rows = self._query(
            "SELECT * FROM discount_eligibility WHERE customer_id = ? ORDER BY eligible_from",
            (customer_id,),
        )
        return {"customer_id": customer_id, "discount_records": rows}

    @tool(
        description="Get network usage records for a customer in a specific billing period. Returns each service type and its usage in GB.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The customer ID.",
                },
                "billing_period": {
                    "type": "string",
                    "description": "Billing period in YYYY-MM format, e.g. 2025-01.",
                },
            },
            "required": ["customer_id", "billing_period"],
        },
    )
    def get_usage_records(self, customer_id: str, billing_period: str):
        rows = self._query(
            "SELECT record_id, service_type, usage_gb FROM usage_records "
            "WHERE customer_id = ? AND billing_period = ?",
            (customer_id, billing_period),
        )
        return {
            "customer_id": customer_id,
            "billing_period": billing_period,
            "usage_records": rows,
        }

    @tool(
        description="Get the invoice amount from a third-party content provider for a specific customer and billing period.",
        parameters={
            "type": "object",
            "properties": {
                "provider_name": {
                    "type": "string",
                    "description": "Name of the content provider.",
                },
                "customer_id": {
                    "type": "string",
                    "description": "The customer ID.",
                },
                "billing_period": {
                    "type": "string",
                    "description": "Billing period in YYYY-MM format.",
                },
            },
            "required": ["provider_name", "customer_id", "billing_period"],
        },
    )
    def get_provider_invoice(self, provider_name: str, customer_id: str, billing_period: str):
        rows = self._query(
            "SELECT invoice_id, provider_name, service_description, invoice_amount "
            "FROM provider_invoices "
            "WHERE provider_name = ? AND customer_id = ? AND billing_period = ?",
            (provider_name, customer_id, billing_period),
        )
        if not rows:
            return {"found": False, "message": f"No invoice from {provider_name} for {customer_id} in {billing_period}"}
        return {"found": True, "invoices": rows}

    @tool(
        description="List all third-party content providers available in the system.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_providers(self):
        rows = self._query("SELECT DISTINCT provider_name FROM provider_invoices ORDER BY provider_name")
        return {"providers": [r["provider_name"] for r in rows]}

    @tool(
        description="List all billing periods available in the system.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_billing_periods(self):
        rows = self._query("SELECT DISTINCT billing_period FROM usage_records ORDER BY billing_period")
        return {"billing_periods": [r["billing_period"] for r in rows]}

    @tool(
        description="Get all provider invoices for a specific customer across all billing periods. Returns a list of invoices with provider name, amount, and period.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The customer ID.",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_customer_provider_invoices(self, customer_id: str):
        rows = self._query(
            "SELECT invoice_id, provider_name, service_description, invoice_amount, billing_period "
            "FROM provider_invoices WHERE customer_id = ? ORDER BY billing_period, provider_name",
            (customer_id,),
        )
        return {"customer_id": customer_id, "invoices": rows}

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _load_billing_from_workspace(self):
        """Load all billing records from workspace files (CSV, JSON, TXT, YAML)."""
        records = []
        for fname in sorted(os.listdir(self.workspace)):
            fpath = os.path.join(self.workspace, fname)
            if not os.path.isfile(fpath):
                continue
            if fname.startswith("billing_batch_"):
                if fname.endswith(".csv"):
                    import pandas as pd
                    df = pd.read_csv(fpath)
                    for _, row in df.iterrows():
                        records.append(dict(row))
                elif fname.endswith(".json"):
                    with open(fpath) as f:
                        data = json.load(f)
                    records.extend(data.get("billing_records", []))
                elif fname.endswith(".txt"):
                    with open(fpath) as f:
                        lines = f.read().strip().split("\n")
                    if len(lines) > 1:
                        headers = lines[0].split("\t")
                        for line in lines[1:]:
                            vals = line.split("\t")
                            rec = {}
                            for h, v in zip(headers, vals):
                                try:
                                    rec[h] = float(v)
                                except ValueError:
                                    rec[h] = v
                            records.append(rec)
                elif fname.endswith(".yaml"):
                    with open(fpath) as f:
                        data = yaml.safe_load(f)
                    records.extend(data.get("billing_records", []))
        return records

    def _compute_ground_truth(self):
        """Compute ground truth: what each customer should have been billed,
        and identify discrepancies by comparing with workspace billing records."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load reference data
        customers = [dict(r) for r in conn.execute("SELECT * FROM customers ORDER BY customer_id").fetchall()]
        plans = [dict(r) for r in conn.execute("SELECT * FROM subscription_plans").fetchall()]
        discounts = [dict(r) for r in conn.execute("SELECT * FROM discount_eligibility").fetchall()]
        usage = [dict(r) for r in conn.execute("SELECT * FROM usage_records").fetchall()]
        invoices = [dict(r) for r in conn.execute("SELECT * FROM provider_invoices").fetchall()]
        conn.close()

        # Load pricing and bundle rules from workspace
        with open(os.path.join(self.workspace, "pricing_tiers.yaml")) as f:
            pricing_config = yaml.safe_load(f)["pricing_tiers"]
        with open(os.path.join(self.workspace, "bundle_discount_rules.json")) as f:
            bundle_rules = json.load(f)["bundle_discount_rules"]
        with open(os.path.join(self.workspace, "promo_catalog.md")) as f:
            promo_text = f.read()

        # Parse promo catalog
        promo_details = {}
        import re
        for block in promo_text.split("## ")[1:]:
            lines = block.strip().split("\n")
            code = lines[0].strip()
            disc_pct = None
            applies_to = None
            for line in lines[1:]:
                m = re.search(r"Discount:\s*(\d+)%\s*off\s*(\w+)", line)
                if m:
                    disc_pct = int(m.group(1)) / 100.0
                    applies_to = m.group(2)
                m2 = re.search(r"Applies to:\s*(\w+)", line)
                if m2:
                    applies_to = m2.group(1)
            if disc_pct is not None:
                promo_details[code] = {"discount_pct": disc_pct, "applies_to": applies_to}

        # Build lookup structures
        plan_by_cust = {p["customer_id"]: p for p in plans}
        disc_by_cust = {}
        for d in discounts:
            disc_by_cust.setdefault(d["customer_id"], []).append(d)
        usage_by_cust_period = {}
        for u in usage:
            key = (u["customer_id"], u["billing_period"])
            usage_by_cust_period.setdefault(key, []).append(u)
        inv_by_cust_period = {}
        for inv in invoices:
            key = (inv["customer_id"], inv["billing_period"])
            inv_by_cust_period.setdefault(key, []).append(inv)

        # Get billing periods
        periods = sorted(set(u["billing_period"] for u in usage))

        # Compute expected billing for each customer-period
        expected = {}
        for c in customers:
            cid = c["customer_id"]
            plan = plan_by_cust.get(cid)
            if not plan:
                continue
            tier = plan["tier"]
            bundle = plan["bundle_type"]
            pricing = pricing_config[tier]

            for period in periods:
                base_charge = pricing["monthly_rate"]

                # Bundle discount
                bundle_disc_pct = bundle_rules[bundle]["discount_percentage"] / 100.0
                bundle_discount = round(base_charge * bundle_disc_pct, 2)

                # Promo discount
                promo_discount = 0.0
                cust_discs = disc_by_cust.get(cid, [])
                for d in cust_discs:
                    if d["eligible_from"] <= f"{period}-28" and d["eligible_to"] >= f"{period}-01" and d["status"] == "active":
                        pcode = d["promo_code"]
                        if pcode in promo_details:
                            pd_info = promo_details[pcode]
                            if pd_info["applies_to"] == "base_charge":
                                disc = round(base_charge * pd_info["discount_pct"], 2)
                                promo_discount = max(promo_discount, disc)

                # Usage charge
                ukey = (cid, period)
                usage_recs = usage_by_cust_period.get(ukey, [])
                total_usage = sum(u["usage_gb"] for u in usage_recs)
                overage = max(0, total_usage - pricing["included_data_gb"])
                usage_charge = round(overage * pricing["overage_rate_per_gb"], 2)

                # Content charge
                ikey = (cid, period)
                invs = inv_by_cust_period.get(ikey, [])
                content_charge = round(sum(inv["invoice_amount"] for inv in invs), 2)

                # Check for total-level promo
                subtotal = round(base_charge - bundle_discount - promo_discount + usage_charge + content_charge, 2)
                total_promo = 0.0
                for d in cust_discs:
                    if d["eligible_from"] <= f"{period}-28" and d["eligible_to"] >= f"{period}-01" and d["status"] == "active":
                        pcode = d["promo_code"]
                        if pcode in promo_details:
                            pd_info = promo_details[pcode]
                            if pd_info["applies_to"] == "total":
                                disc = round(subtotal * pd_info["discount_pct"], 2)
                                total_promo = max(total_promo, disc)

                if total_promo > 0:
                    promo_discount = total_promo

                total_expected = round(base_charge - bundle_discount - promo_discount + usage_charge + content_charge, 2)

                expected[(cid, period)] = {
                    "customer_id": cid,
                    "billing_period": period,
                    "base_charge": base_charge,
                    "bundle_discount": bundle_discount,
                    "promo_discount": promo_discount,
                    "usage_charge": usage_charge,
                    "content_charge": content_charge,
                    "total_expected": total_expected,
                }

        # Load actual billing from workspace
        actual_records = self._load_billing_from_workspace()
        actual_by_key = {}
        for r in actual_records:
            key = (r["customer_id"], r["billing_period"])
            actual_by_key[key] = r

        # Find discrepancies
        discrepancies = []
        for key in sorted(expected.keys()):
            exp = expected[key]
            act = actual_by_key.get(key)
            if act is None:
                continue

            cid, period = key
            plan = plan_by_cust[cid]

            # Compare each component
            root_cause = None
            exp_total = exp["total_expected"]
            act_total = round(float(act.get("total_billed", 0)), 2)

            if abs(exp_total - act_total) < 0.01:
                continue  # no discrepancy

            # Determine root cause by comparing components
            act_base = round(float(act.get("base_charge", 0)), 2)
            act_bundle = round(float(act.get("bundle_discount", 0)), 2)
            act_promo = round(float(act.get("promo_discount", 0)), 2)
            act_usage = round(float(act.get("usage_charge", 0)), 2)
            act_content = round(float(act.get("content_charge", 0)), 2)

            if abs(act_base - exp["base_charge"]) > 0.01:
                root_cause = "PLAN_RATE_ERROR"
            elif abs(act_bundle - exp["bundle_discount"]) > 0.01:
                root_cause = "MISSING_BUNDLE_DISCOUNT"
            elif abs(act_promo - exp["promo_discount"]) > 0.01:
                root_cause = "EXPIRED_PROMO"
            elif abs(act_usage - exp["usage_charge"]) > 0.01:
                root_cause = "USAGE_OVERCHARGE"
            elif abs(act_content - exp["content_charge"]) > 0.01:
                root_cause = "PROVIDER_MISMATCH"
            else:
                root_cause = "UNKNOWN"

            adjustment = round(exp_total - act_total, 2)

            discrepancies.append({
                "customer_id": cid,
                "billing_period": period,
                "root_cause": root_cause,
                "expected_amount": exp_total,
                "billed_amount": act_total,
                "adjustment_amount": adjustment,
            })

        return discrepancies, expected, actual_by_key

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        gt_discrepancies, expected, actual = self._compute_ground_truth()

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: adjustment_report.csv exists and has correct columns (15 pts) ---
        max_score += 15
        report_path = os.path.join(self.workspace, "adjustment_report.csv")
        report_exists = os.path.isfile(report_path)
        report_records = []
        required_cols = {"customer_id", "billing_period", "root_cause", "expected_amount",
                         "billed_amount", "adjustment_amount"}

        if report_exists:
            try:
                with open(report_path, newline="") as f:
                    reader = csv.DictReader(f)
                    report_records = list(reader)
                actual_cols = set(reader.fieldnames) if reader.fieldnames else set()
                cols_ok = required_cols.issubset(actual_cols)
            except Exception:
                cols_ok = False
        else:
            cols_ok = False

        if report_exists and cols_ok and len(report_records) > 0:
            score = 15
            eval_criteria["report_format"] = {"passed": True, "score": 15, "max_score": 15}
        elif report_exists and cols_ok:
            score = 10
            eval_criteria["report_format"] = {"passed": False, "score": 10, "max_score": 15,
                                               "reason": "Report exists with correct columns but is empty"}
        elif report_exists:
            score = 5
            eval_criteria["report_format"] = {"passed": False, "score": 5, "max_score": 15,
                                               "reason": f"Report exists but missing columns: {required_cols - actual_cols if report_exists else required_cols}"}
        else:
            score = 0
            eval_criteria["report_format"] = {"passed": False, "score": 0, "max_score": 15,
                                               "reason": "adjustment_report.csv not found"}
        total_score += score

        # --- Criterion 2: Discrepancy detection completeness (25 pts) ---
        max_score += 25
        gt_keys = {(d["customer_id"], d["billing_period"]) for d in gt_discrepancies}
        report_keys = set()
        for r in report_records:
            report_keys.add((r.get("customer_id", ""), r.get("billing_period", "")))

        if len(gt_keys) > 0:
            detected = gt_keys & report_keys
            recall = len(detected) / len(gt_keys)
        else:
            recall = 1.0

        score_2 = round(25 * recall)
        passed_2 = recall >= 0.9
        eval_criteria["discrepancy_detection"] = {
            "passed": passed_2,
            "score": score_2,
            "max_score": 25,
            "reason": f"Detected {len(detected) if gt_keys else 0}/{len(gt_keys)} discrepancies (recall={recall:.2%})" if not passed_2 else None,
        }
        if passed_2:
            eval_criteria["discrepancy_detection"].pop("reason", None)
        total_score += score_2

        # --- Criterion 3: Root cause accuracy (25 pts) ---
        max_score += 25
        gt_by_key = {(d["customer_id"], d["billing_period"]): d for d in gt_discrepancies}
        correct_rc = 0
        total_rc = 0
        for r in report_records:
            key = (r.get("customer_id", ""), r.get("billing_period", ""))
            if key in gt_by_key:
                total_rc += 1
                if r.get("root_cause", "").strip() == gt_by_key[key]["root_cause"]:
                    correct_rc += 1

        rc_accuracy = correct_rc / total_rc if total_rc > 0 else 0.0
        score_3 = round(25 * rc_accuracy)
        passed_3 = rc_accuracy >= 0.9
        eval_criteria["root_cause_accuracy"] = {
            "passed": passed_3,
            "score": score_3,
            "max_score": 25,
        }
        if not passed_3:
            eval_criteria["root_cause_accuracy"]["reason"] = f"Root cause correct for {correct_rc}/{total_rc} entries ({rc_accuracy:.2%})"
        total_score += score_3

        # --- Criterion 4: Adjustment amounts accuracy (20 pts) ---
        max_score += 20
        correct_adj = 0
        total_adj = 0
        for r in report_records:
            key = (r.get("customer_id", ""), r.get("billing_period", ""))
            if key in gt_by_key:
                total_adj += 1
                try:
                    reported_adj = round(float(r.get("adjustment_amount", 0)), 2)
                    expected_adj = gt_by_key[key]["adjustment_amount"]
                    if abs(reported_adj - expected_adj) < 0.02:
                        correct_adj += 1
                except (ValueError, TypeError):
                    pass

        adj_accuracy = correct_adj / total_adj if total_adj > 0 else 0.0
        score_4 = round(20 * adj_accuracy)
        passed_4 = adj_accuracy >= 0.9
        eval_criteria["adjustment_amounts"] = {
            "passed": passed_4,
            "score": score_4,
            "max_score": 20,
        }
        if not passed_4:
            eval_criteria["adjustment_amounts"]["reason"] = f"Adjustment amounts correct for {correct_adj}/{total_adj} entries ({adj_accuracy:.2%})"
        total_score += score_4

        # --- Criterion 5: False positive rate (15 pts) ---
        max_score += 15
        false_positives = report_keys - gt_keys
        fp_rate = len(false_positives) / len(report_keys) if len(report_keys) > 0 else 0.0
        if fp_rate <= 0.05:
            score_5 = 15
            passed_5 = True
        elif fp_rate <= 0.15:
            score_5 = 10
            passed_5 = False
        elif fp_rate <= 0.30:
            score_5 = 5
            passed_5 = False
        else:
            score_5 = 0
            passed_5 = False

        eval_criteria["false_positive_rate"] = {
            "passed": passed_5,
            "score": score_5,
            "max_score": 15,
        }
        if not passed_5:
            eval_criteria["false_positive_rate"]["reason"] = f"{len(false_positives)} false positives out of {len(report_keys)} reported ({fp_rate:.2%})"
        total_score += score_5

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import re as _re

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # Step 1: Read workspace config files
        with open(os.path.join(self.workspace, "pricing_tiers.yaml")) as f:
            pricing_config = yaml.safe_load(f)["pricing_tiers"]

        with open(os.path.join(self.workspace, "bundle_discount_rules.json")) as f:
            bundle_rules = json.load(f)["bundle_discount_rules"]

        with open(os.path.join(self.workspace, "promo_catalog.md")) as f:
            promo_text = f.read()

        # Parse promo catalog
        promo_details = {}
        for block in promo_text.split("## ")[1:]:
            lines = block.strip().split("\n")
            code = lines[0].strip()
            disc_pct = None
            applies_to = None
            for line in lines[1:]:
                m = _re.search(r"Discount:\s*(\d+)%\s*off\s*(\w+)", line)
                if m:
                    disc_pct = int(m.group(1)) / 100.0
                    applies_to = m.group(2)
                m2 = _re.search(r"Applies to:\s*(\w+)", line)
                if m2:
                    applies_to = m2.group(1)
            if disc_pct is not None:
                promo_details[code] = {"discount_pct": disc_pct, "applies_to": applies_to}

        # Step 2: Load all billing records from workspace
        billing_records = self._load_billing_from_workspace()
        actual_by_key = {}
        for r in billing_records:
            key = (r["customer_id"], r["billing_period"])
            actual_by_key[key] = r

        # Step 3: Get list of billing periods and providers
        periods_result = call_tool("list_billing_periods")
        periods = periods_result["billing_periods"]

        providers_result = call_tool("list_providers")
        providers = providers_result["providers"]

        # Step 4: List all customers (paginated)
        all_customers = []
        page = 1
        while True:
            result = call_tool("list_customers", page=page, page_size=20)
            all_customers.extend(result["customers"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 5: For each customer, get subscription and check for discrepancies
        discrepancies = []

        for cust in all_customers:
            cid = cust["customer_id"]

            # Get subscription details
            sub = call_tool("get_customer_subscription", customer_id=cid)
            tier = sub["tier"]
            bundle = sub["bundle_type"]
            pricing = pricing_config[tier]

            # Get discount eligibility
            disc_result = call_tool("get_discount_eligibility", customer_id=cid)
            cust_discounts = disc_result["discount_records"]

            # Get all provider invoices for this customer
            inv_result = call_tool("get_customer_provider_invoices", customer_id=cid)
            cust_invoices = inv_result["invoices"]

            for period in periods:
                key = (cid, period)
                act = actual_by_key.get(key)
                if act is None:
                    continue

                # Get usage records
                usage_result = call_tool("get_usage_records", customer_id=cid, billing_period=period)
                usage_recs = usage_result["usage_records"]

                # Compute expected billing
                base_charge = pricing["monthly_rate"]

                # Bundle discount
                bundle_disc_pct = bundle_rules[bundle]["discount_percentage"] / 100.0
                bundle_discount = round(base_charge * bundle_disc_pct, 2)

                # Promo discount
                promo_discount = 0.0
                for d in cust_discounts:
                    if (d["eligible_from"] <= f"{period}-28" and
                            d["eligible_to"] >= f"{period}-01" and
                            d["status"] == "active"):
                        pcode = d["promo_code"]
                        if pcode in promo_details:
                            pd_info = promo_details[pcode]
                            if pd_info["applies_to"] == "base_charge":
                                disc = round(base_charge * pd_info["discount_pct"], 2)
                                promo_discount = max(promo_discount, disc)

                # Usage charge
                total_usage = sum(u["usage_gb"] for u in usage_recs)
                overage = max(0, total_usage - pricing["included_data_gb"])
                usage_charge = round(overage * pricing["overage_rate_per_gb"], 2)

                # Content charge
                period_invs = [inv for inv in cust_invoices if inv["billing_period"] == period]
                content_charge = round(sum(inv["invoice_amount"] for inv in period_invs), 2)

                # Check for total-level promo
                subtotal = round(base_charge - bundle_discount - promo_discount + usage_charge + content_charge, 2)
                total_promo = 0.0
                for d in cust_discounts:
                    if (d["eligible_from"] <= f"{period}-28" and
                            d["eligible_to"] >= f"{period}-01" and
                            d["status"] == "active"):
                        pcode = d["promo_code"]
                        if pcode in promo_details:
                            pd_info = promo_details[pcode]
                            if pd_info["applies_to"] == "total":
                                disc = round(subtotal * pd_info["discount_pct"], 2)
                                total_promo = max(total_promo, disc)

                if total_promo > 0:
                    promo_discount = total_promo

                expected_total = round(base_charge - bundle_discount - promo_discount + usage_charge + content_charge, 2)

                # Compare with actual
                act_total = round(float(act.get("total_billed", 0)), 2)

                if abs(expected_total - act_total) >= 0.01:
                    # Determine root cause
                    act_base = round(float(act.get("base_charge", 0)), 2)
                    act_bundle = round(float(act.get("bundle_discount", 0)), 2)
                    act_promo = round(float(act.get("promo_discount", 0)), 2)
                    act_usage = round(float(act.get("usage_charge", 0)), 2)
                    act_content = round(float(act.get("content_charge", 0)), 2)

                    if abs(act_base - base_charge) > 0.01:
                        root_cause = "PLAN_RATE_ERROR"
                    elif abs(act_bundle - bundle_discount) > 0.01:
                        root_cause = "MISSING_BUNDLE_DISCOUNT"
                    elif abs(act_promo - promo_discount) > 0.01:
                        root_cause = "EXPIRED_PROMO"
                    elif abs(act_usage - usage_charge) > 0.01:
                        root_cause = "USAGE_OVERCHARGE"
                    elif abs(act_content - content_charge) > 0.01:
                        root_cause = "PROVIDER_MISMATCH"
                    else:
                        root_cause = "UNKNOWN"

                    adjustment = round(expected_total - act_total, 2)

                    discrepancies.append({
                        "customer_id": cid,
                        "billing_period": period,
                        "root_cause": root_cause,
                        "expected_amount": f"{expected_total:.2f}",
                        "billed_amount": f"{act_total:.2f}",
                        "adjustment_amount": f"{adjustment:.2f}",
                    })

        # Step 6: Write adjustment report
        report_path = os.path.join(self.workspace, "adjustment_report.csv")
        fieldnames = ["customer_id", "billing_period", "root_cause",
                      "expected_amount", "billed_amount", "adjustment_amount"]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for d in sorted(discrepancies, key=lambda x: (x["customer_id"], x["billing_period"])):
                writer.writerow(d)

        # Step 7: Construct action summary
        rc_counts = {}
        total_adj = 0.0
        for d in discrepancies:
            rc = d["root_cause"]
            rc_counts[rc] = rc_counts.get(rc, 0) + 1
            total_adj += float(d["adjustment_amount"])

        action_lines = [
            f"Billing Discrepancy Reconciliation Complete.",
            f"Total discrepancies found: {len(discrepancies)}",
            f"Total adjustment amount: ${total_adj:.2f}",
            f"Root cause breakdown:",
        ]
        for rc, count in sorted(rc_counts.items()):
            action_lines.append(f"  - {rc}: {count}")
        action_lines.append(f"Adjustment report saved as adjustment_report.csv")

        action = "\n".join(action_lines)

        print(f"Verify: {tool_call_count} tool calls made")
        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need >= 15"

        return self.step(action)
