"""Environment for fundraising reconciliation task."""

import csv
import json
import os
import re
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

    # ================================================================
    # Tool methods
    # ================================================================

    @tool(
        description="List campaigns filtered by status. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "completed", "paused"],
                    "description": "Campaign status to filter by.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed. Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page, max 20. Defaults to 20.",
                },
            },
            "required": ["status"],
        },
    )
    def list_campaigns(self, status: str, page: int = 1, page_size: int = 20) -> dict:
        page_size = min(page_size, 20)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) as cnt FROM campaigns WHERE status = ?", (status,)
        )
        total = cur.fetchone()["cnt"]
        offset = (page - 1) * page_size
        cur.execute(
            "SELECT id, name, status, tier FROM campaigns WHERE status = ? ORDER BY id LIMIT ? OFFSET ?",
            (status, page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "campaigns": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get full details for a single campaign by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "integer",
                    "description": "The campaign ID.",
                },
            },
            "required": ["campaign_id"],
        },
    )
    def get_campaign_details(self, campaign_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Campaign {campaign_id} not found."}
        return dict(row)

    @tool(
        description="Retrieve gateway deposit records for a specific campaign. Optionally filter by deposit status.",
        parameters={
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "integer",
                    "description": "The campaign ID.",
                },
                "status_filter": {
                    "type": "string",
                    "enum": ["cleared", "pending", "reversed"],
                    "description": "If provided, return only deposits with this status.",
                },
            },
            "required": ["campaign_id"],
        },
    )
    def query_gateway_deposits(self, campaign_id: int, status_filter: str = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if status_filter:
            cur.execute(
                "SELECT * FROM gateway_deposits WHERE campaign_id = ? AND status = ? ORDER BY id",
                (campaign_id, status_filter),
            )
        else:
            cur.execute(
                "SELECT * FROM gateway_deposits WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"campaign_id": campaign_id, "deposits": rows, "count": len(rows)}

    @tool(
        description="Retrieve all in-kind donation records for a specific campaign.",
        parameters={
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "integer",
                    "description": "The campaign ID.",
                },
            },
            "required": ["campaign_id"],
        },
    )
    def get_in_kind_donations(self, campaign_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM in_kind_donations WHERE campaign_id = ? ORDER BY id",
            (campaign_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"campaign_id": campaign_id, "donations": rows, "count": len(rows)}

    @tool(
        description="Retrieve expense records for a specific campaign. Optionally filter by approval status.",
        parameters={
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "integer",
                    "description": "The campaign ID.",
                },
                "status_filter": {
                    "type": "string",
                    "enum": ["approved", "pending", "rejected"],
                    "description": "If provided, return only expenses with this status.",
                },
            },
            "required": ["campaign_id"],
        },
    )
    def get_campaign_expenses(self, campaign_id: int, status_filter: str = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if status_filter:
            cur.execute(
                "SELECT * FROM expenses WHERE campaign_id = ? AND status = ? ORDER BY id",
                (campaign_id, status_filter),
            )
        else:
            cur.execute(
                "SELECT * FROM expenses WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"campaign_id": campaign_id, "expenses": rows, "count": len(rows)}

    @tool(
        description="Retrieve all fee waiver/credit records for a specific campaign.",
        parameters={
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "integer",
                    "description": "The campaign ID.",
                },
            },
            "required": ["campaign_id"],
        },
    )
    def get_fee_waivers(self, campaign_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM fee_waivers WHERE campaign_id = ? ORDER BY id",
            (campaign_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"campaign_id": campaign_id, "waivers": rows, "count": len(rows)}

    # ================================================================
    # Helpers for ground-truth computation (used by step)
    # ================================================================

    def _load_workspace_config(self):
        """Load reconciliation rules and fee schedule from workspace."""
        with open(os.path.join(self.workspace, "reconciliation_rules.json")) as f:
            rules = json.load(f)
        with open(os.path.join(self.workspace, "fee_schedule.yaml")) as f:
            schedule = yaml.safe_load(f)
        return rules, schedule

    def _load_manual_deposits(self):
        """Load all manual deposit records from CSV batch files."""
        records = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("deposit_batch") and fname.endswith(".csv"):
                path = os.path.join(self.workspace, fname)
                with open(path, newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        row["campaign_id"] = int(row["campaign_id"])
                        row["amount"] = float(row["amount"])
                        records.append(row)
        return records

    def _load_appraisal_certs(self):
        """Load all appraisal certificates from JSON files. Returns dict keyed by donation_id."""
        certs = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("appraisal_cert") and fname.endswith(".json"):
                path = os.path.join(self.workspace, fname)
                with open(path) as f:
                    data = json.load(f)
                for entry in data:
                    certs[entry["donation_id"]] = entry["certified_value"]
        return certs

    def _load_fee_statements(self):
        """Load all fee statement records from YAML files."""
        records = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("fee_statement") and fname.endswith(".yaml"):
                path = os.path.join(self.workspace, fname)
                with open(path) as f:
                    data = yaml.safe_load(f)
                if data and "fee_records" in data:
                    records.extend(data["fee_records"])
        return records

    def _load_expense_supplements(self):
        """Load all expense supplement records from pipe-delimited TXT files."""
        records = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("expense_supplement") and fname.endswith(".txt"):
                path = os.path.join(self.workspace, fname)
                with open(path) as f:
                    header = f.readline().strip().split("|")
                    for line in f:
                        vals = line.strip().split("|")
                        if len(vals) == len(header):
                            rec = dict(zip(header, vals))
                            rec["campaign_id"] = int(rec["campaign_id"])
                            rec["amount"] = float(rec["amount"])
                            records.append(rec)
        return records

    def _compute_ground_truth(self):
        """Compute ground truth for all active campaigns using DB + workspace."""
        rules, schedule = self._load_workspace_config()
        cond_mult = rules["condition_multipliers"]
        cat_weight = rules["category_weights"]
        tier_rates = schedule["tier_rates"]
        tolerance = rules["fee_discrepancy_tolerance_pct"]
        precision = rules["rounding_precision"]

        # Load workspace data
        manual_deps = self._load_manual_deposits()
        certs = self._load_appraisal_certs()
        fee_stmts = self._load_fee_statements()
        expense_supps = self._load_expense_supplements()

        # Aggregate workspace data by campaign_id
        manual_by_cid = {}
        for r in manual_deps:
            manual_by_cid[r["campaign_id"]] = manual_by_cid.get(r["campaign_id"], 0) + r["amount"]

        fee_by_cid = {}
        for r in fee_stmts:
            cid = r["campaign_id"]
            fee_by_cid[cid] = fee_by_cid.get(cid, 0) + r["charged_amount"]

        supp_by_cid = {}
        for r in expense_supps:
            supp_by_cid[r["campaign_id"]] = supp_by_cid.get(r["campaign_id"], 0) + r["amount"]

        # Query DB
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT * FROM campaigns WHERE status = 'active' ORDER BY id")
        active_campaigns = [dict(r) for r in cur.fetchall()]

        results = {}
        discrepancies = []

        for camp in active_campaigns:
            cid = camp["id"]

            # Gateway deposits (cleared only)
            cur.execute(
                "SELECT COALESCE(SUM(amount), 0) as total FROM gateway_deposits WHERE campaign_id = ? AND status = 'cleared'",
                (cid,),
            )
            gw_dep = cur.fetchone()["total"]

            # Manual deposits
            man_dep = manual_by_cid.get(cid, 0)

            total_dep = gw_dep + man_dep

            # In-kind donations adjusted
            cur.execute(
                "SELECT * FROM in_kind_donations WHERE campaign_id = ?", (cid,)
            )
            donations = [dict(r) for r in cur.fetchall()]
            adjusted_ink = 0.0
            for d in donations:
                base_val = certs.get(d["id"], d["base_appraised_value"])
                mult = cond_mult.get(d["condition_grade"], 1.0)
                wt = cat_weight.get(d["category"], 1.0)
                adjusted_ink += base_val * mult * wt

            gross_rev = total_dep + adjusted_ink

            # Platform fees (from workspace)
            plat_fees = fee_by_cid.get(cid, 0)

            # Fee waivers (from DB)
            cur.execute(
                "SELECT COALESCE(SUM(waiver_amount), 0) as total FROM fee_waivers WHERE campaign_id = ?",
                (cid,),
            )
            waiver_total = cur.fetchone()["total"]

            net_fees = plat_fees - waiver_total

            # Approved expenses (from DB)
            cur.execute(
                "SELECT COALESCE(SUM(amount), 0) as total FROM expenses WHERE campaign_id = ? AND status = 'approved'",
                (cid,),
            )
            approved_exp = cur.fetchone()["total"]

            # Supplementary expenses
            supp_exp = supp_by_cid.get(cid, 0)

            total_exp = approved_exp + supp_exp

            net_bal = gross_rev - net_fees - total_exp

            results[cid] = {
                "campaign_id": cid,
                "campaign_name": camp["name"],
                "tier": camp["tier"],
                "gateway_deposits": round(gw_dep, precision),
                "manual_deposits": round(man_dep, precision),
                "total_deposits": round(total_dep, precision),
                "adjusted_in_kind": round(adjusted_ink, precision),
                "gross_revenue": round(gross_rev, precision),
                "platform_fees": round(plat_fees, precision),
                "fee_waivers": round(waiver_total, precision),
                "net_fees": round(net_fees, precision),
                "approved_expenses": round(approved_exp, precision),
                "supplementary_expenses": round(supp_exp, precision),
                "total_expenses": round(total_exp, precision),
                "net_balance": round(net_bal, precision),
            }

            # Discrepancy check
            expected_fees = tier_rates[camp["tier"]] * total_dep
            if expected_fees > 0:
                disc_pct = abs(plat_fees - expected_fees) / expected_fees * 100
                if disc_pct > tolerance:
                    discrepancies.append({
                        "campaign_id": cid,
                        "campaign_name": camp["name"],
                        "expected_fees": round(expected_fees, precision),
                        "actual_fees": round(plat_fees, precision),
                        "discrepancy_pct": round(disc_pct, 1),
                    })

        conn.close()

        discrepancies.sort(key=lambda x: x["campaign_id"])
        grand_total = round(sum(r["net_balance"] for r in results.values()), precision)

        return results, discrepancies, grand_total

    # ================================================================
    # step
    # ================================================================

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        gt_results, gt_disc, gt_grand_total = self._compute_ground_truth()
        gt_cids = sorted(gt_results.keys())

        criteria = {}
        tol = 0.015  # tolerance for floating-point comparison

        # --- Criterion 1: Active campaigns in financial_statements.csv (10 pts) ---
        fs_path = os.path.join(self.workspace, "financial_statements.csv")
        submitted = {}
        fs_exists = os.path.exists(fs_path)
        if fs_exists:
            with open(fs_path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        cid = int(row.get("campaign_id", -1))
                        submitted[cid] = row
                    except (ValueError, TypeError):
                        pass

        submitted_cids = sorted(submitted.keys())
        if submitted_cids == gt_cids:
            criteria["active_campaigns"] = {"passed": True, "score": 10, "max_score": 10}
        else:
            missing = set(gt_cids) - set(submitted_cids)
            extra = set(submitted_cids) - set(gt_cids)
            reason = ""
            if missing:
                reason += f"Missing campaign IDs: {sorted(missing)}. "
            if extra:
                reason += f"Extra campaign IDs: {sorted(extra)}. "
            if not fs_exists:
                reason = "financial_statements.csv not found."
            # partial credit: proportion correct
            if gt_cids:
                correct = len(set(gt_cids) & set(submitted_cids))
                partial = round(10 * correct / len(gt_cids))
            else:
                partial = 0
            criteria["active_campaigns"] = {"passed": False, "score": partial, "max_score": 10, "reason": reason.strip()}

        # Helper to compare a numeric column across all campaigns
        def _check_column(col_name, max_pts, crit_name):
            if not fs_exists:
                criteria[crit_name] = {"passed": False, "score": 0, "max_score": max_pts, "reason": "financial_statements.csv not found."}
                return
            correct = 0
            total = len(gt_cids)
            errors = []
            for cid in gt_cids:
                gt_val = gt_results[cid][col_name]
                if cid in submitted:
                    try:
                        sub_val = float(submitted[cid].get(col_name, ""))
                    except (ValueError, TypeError):
                        sub_val = None
                    if sub_val is not None and abs(sub_val - gt_val) <= tol:
                        correct += 1
                    else:
                        errors.append(f"campaign {cid}: expected {gt_val}, got {sub_val}")
                else:
                    errors.append(f"campaign {cid}: row missing")
            score = round(max_pts * correct / total) if total > 0 else 0
            if correct == total:
                criteria[crit_name] = {"passed": True, "score": max_pts, "max_score": max_pts}
            else:
                reason = f"{total - correct}/{total} campaigns wrong. " + "; ".join(errors[:3])
                criteria[crit_name] = {"passed": False, "score": score, "max_score": max_pts, "reason": reason}

        # --- Criterion 2: gateway_deposits (15 pts) ---
        _check_column("gateway_deposits", 15, "gateway_deposits")

        # --- Criterion 3: manual_deposits (15 pts) ---
        _check_column("manual_deposits", 15, "manual_deposits")

        # --- Criterion 4: adjusted_in_kind (20 pts) ---
        _check_column("adjusted_in_kind", 20, "adjusted_in_kind")

        # --- Criterion 5: net_fees (15 pts) ---
        _check_column("net_fees", 15, "net_fees")

        # --- Criterion 6: total_expenses (10 pts) ---
        _check_column("total_expenses", 10, "total_expenses")

        # --- Criterion 7: discrepancy_report.txt (15 pts) ---
        dr_path = os.path.join(self.workspace, "discrepancy_report.txt")
        if os.path.exists(dr_path):
            with open(dr_path) as f:
                dr_lines = [l.strip() for l in f if l.strip()]
            # Extract campaign IDs from report lines
            reported_ids = set()
            for line in dr_lines:
                m = re.match(r"Campaign\s+(\d+)", line)
                if m:
                    reported_ids.add(int(m.group(1)))
            gt_disc_ids = set(d["campaign_id"] for d in gt_disc)
            if reported_ids == gt_disc_ids:
                criteria["discrepancy_report"] = {"passed": True, "score": 15, "max_score": 15}
            else:
                missing_d = gt_disc_ids - reported_ids
                extra_d = reported_ids - gt_disc_ids
                reason = ""
                if missing_d:
                    reason += f"Missing flagged campaigns: {sorted(missing_d)}. "
                if extra_d:
                    reason += f"Extra flagged campaigns: {sorted(extra_d)}. "
                if gt_disc_ids:
                    correct_d = len(gt_disc_ids & reported_ids)
                    partial = round(15 * correct_d / len(gt_disc_ids))
                else:
                    # No discrepancies expected but agent reported some
                    partial = 0 if reported_ids else 15
                criteria["discrepancy_report"] = {"passed": False, "score": partial, "max_score": 15, "reason": reason.strip()}
        else:
            criteria["discrepancy_report"] = {"passed": False, "score": 0, "max_score": 15, "reason": "discrepancy_report.txt not found."}

        # --- Criterion 8: Grand total in response (10 pts) ---
        gt_str = f"{gt_grand_total:.2f}"
        if gt_str in action:
            criteria["summary_response"] = {"passed": True, "score": 10, "max_score": 10}
        else:
            # Try to find any number close to grand total in the action
            numbers = re.findall(r"[\-]?\d+\.\d{2}", action)
            found_close = any(abs(float(n) - gt_grand_total) <= tol for n in numbers)
            if found_close:
                criteria["summary_response"] = {"passed": True, "score": 10, "max_score": 10}
            else:
                criteria["summary_response"] = {
                    "passed": False, "score": 0, "max_score": 10,
                    "reason": f"Expected grand total {gt_str} not found in response."
                }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ================================================================
    # verify
    # ================================================================

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as _csv

        # Step 1: List all active campaigns via tool
        all_active = []
        page = 1
        while True:
            result = self.tools["list_campaigns"](status="active", page=page, page_size=20)
            all_active.extend(result["campaigns"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 2: Get details for each active campaign
        campaign_details = {}
        for camp in all_active:
            details = self.tools["get_campaign_details"](campaign_id=camp["id"])
            campaign_details[camp["id"]] = details

        # Step 3: Load workspace config files
        rules_path = os.path.join(self.workspace, "reconciliation_rules.json")
        with open(rules_path) as f:
            rules = json.load(f)
        cond_mult = rules["condition_multipliers"]
        cat_weight = rules["category_weights"]
        tolerance = rules["fee_discrepancy_tolerance_pct"]
        precision = rules["rounding_precision"]

        schedule_path = os.path.join(self.workspace, "fee_schedule.yaml")
        with open(schedule_path) as f:
            schedule = yaml.safe_load(f)
        tier_rates = schedule["tier_rates"]

        # Step 4: Load workspace data files
        # Manual deposits from CSV
        manual_deps = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("deposit_batch") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname), newline="") as f:
                    reader = _csv.DictReader(f)
                    for row in reader:
                        cid = int(row["campaign_id"])
                        amt = float(row["amount"])
                        manual_deps[cid] = manual_deps.get(cid, 0) + amt

        # Appraisal certs from JSON
        certs = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("appraisal_cert") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                for entry in data:
                    certs[entry["donation_id"]] = entry["certified_value"]

        # Fee statements from YAML
        fee_records = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("fee_statement") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                if data and "fee_records" in data:
                    for rec in data["fee_records"]:
                        cid = rec["campaign_id"]
                        fee_records[cid] = fee_records.get(cid, 0) + rec["charged_amount"]

        # Expense supplements from TXT
        supp_exps = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("expense_supplement") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    header = f.readline().strip().split("|")
                    for line in f:
                        vals = line.strip().split("|")
                        if len(vals) == len(header):
                            rec = dict(zip(header, vals))
                            cid = int(rec["campaign_id"])
                            amt = float(rec["amount"])
                            supp_exps[cid] = supp_exps.get(cid, 0) + amt

        # Step 5: For each active campaign, gather tool data and compute
        statements = []
        discrepancies = []

        for cid in sorted(campaign_details.keys()):
            camp = campaign_details[cid]

            # Gateway deposits (cleared)
            gw_result = self.tools["query_gateway_deposits"](
                campaign_id=cid, status_filter="cleared"
            )
            gw_total = sum(d["amount"] for d in gw_result["deposits"])

            # Manual deposits
            man_total = manual_deps.get(cid, 0)

            total_dep = gw_total + man_total

            # In-kind donations
            ink_result = self.tools["get_in_kind_donations"](campaign_id=cid)
            adjusted_ink = 0.0
            for d in ink_result["donations"]:
                base_val = certs.get(d["id"], d["base_appraised_value"])
                mult = cond_mult.get(d["condition_grade"], 1.0)
                wt = cat_weight.get(d["category"], 1.0)
                adjusted_ink += base_val * mult * wt

            gross_rev = total_dep + adjusted_ink

            # Platform fees from workspace
            plat_fees = fee_records.get(cid, 0)

            # Fee waivers from tool
            waiver_result = self.tools["get_fee_waivers"](campaign_id=cid)
            waiver_total = sum(w["waiver_amount"] for w in waiver_result["waivers"])

            net_fees = plat_fees - waiver_total

            # Approved expenses from tool
            exp_result = self.tools["get_campaign_expenses"](
                campaign_id=cid, status_filter="approved"
            )
            approved_exp = sum(e["amount"] for e in exp_result["expenses"])

            # Supplementary expenses from workspace
            supp_exp = supp_exps.get(cid, 0)

            total_exp = approved_exp + supp_exp
            net_bal = gross_rev - net_fees - total_exp

            statements.append({
                "campaign_id": cid,
                "campaign_name": camp["name"],
                "tier": camp["tier"],
                "gateway_deposits": f"{round(gw_total, precision):.2f}",
                "manual_deposits": f"{round(man_total, precision):.2f}",
                "total_deposits": f"{round(total_dep, precision):.2f}",
                "adjusted_in_kind": f"{round(adjusted_ink, precision):.2f}",
                "gross_revenue": f"{round(gross_rev, precision):.2f}",
                "platform_fees": f"{round(plat_fees, precision):.2f}",
                "fee_waivers": f"{round(waiver_total, precision):.2f}",
                "net_fees": f"{round(net_fees, precision):.2f}",
                "approved_expenses": f"{round(approved_exp, precision):.2f}",
                "supplementary_expenses": f"{round(supp_exp, precision):.2f}",
                "total_expenses": f"{round(total_exp, precision):.2f}",
                "net_balance": f"{round(net_bal, precision):.2f}",
            })

            # Discrepancy check
            expected_fees = tier_rates[camp["tier"]] * total_dep
            if expected_fees > 0:
                disc_pct = abs(plat_fees - expected_fees) / expected_fees * 100
                if disc_pct > tolerance:
                    discrepancies.append({
                        "campaign_id": cid,
                        "campaign_name": camp["name"],
                        "expected_fees": round(expected_fees, precision),
                        "actual_fees": round(plat_fees, precision),
                        "discrepancy_pct": round(disc_pct, 1),
                    })

        # Step 6: Write deliverables
        fieldnames = [
            "campaign_id", "campaign_name", "tier",
            "gateway_deposits", "manual_deposits", "total_deposits",
            "adjusted_in_kind", "gross_revenue",
            "platform_fees", "fee_waivers", "net_fees",
            "approved_expenses", "supplementary_expenses", "total_expenses",
            "net_balance",
        ]
        fs_path = os.path.join(self.workspace, "financial_statements.csv")
        with open(fs_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(statements)

        dr_path = os.path.join(self.workspace, "discrepancy_report.txt")
        with open(dr_path, "w") as f:
            for d in discrepancies:
                f.write(
                    f"Campaign {d['campaign_id']} ({d['campaign_name']}): "
                    f"expected_fees={d['expected_fees']:.2f}, "
                    f"actual_fees={d['actual_fees']:.2f}, "
                    f"discrepancy={d['discrepancy_pct']:.1f}%\n"
                )

        # Step 7: Build action string
        grand_total = sum(float(s["net_balance"]) for s in statements)
        action = f"Grand Total Net Balance: {grand_total:.2f}"

        return self.step(action)
