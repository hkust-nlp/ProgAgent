#!/usr/bin/env python3
"""Environment for cash reserves forecasting task."""
import sqlite3
import json
import os
import csv
import glob
import re
from datetime import datetime, timedelta
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

    # ================================================================
    # Tool methods
    # ================================================================

    @tool(
        description="Returns the list of all department names in the company.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_departments(self) -> str:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT DISTINCT department FROM employees ORDER BY department"
        ).fetchall()
        conn.close()
        return json.dumps([r[0] for r in rows])

    @tool(
        description=(
            "Returns payroll details for every employee in the given department. "
            "Each record includes employee_id, name, base_salary (per pay period), "
            "pay_frequency (weekly / biweekly / monthly), pay_day_of_week "
            "(0=Mon .. 6=Sun, null for monthly), pay_day_of_month (null for "
            "weekly/biweekly), and pay_anchor_date (used for biweekly cycle "
            "calculation, null otherwise)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": "Exact department name (case-sensitive).",
                }
            },
            "required": ["department"],
        },
    )
    def get_payroll_by_department(self, department: str) -> str:
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "SELECT employee_id, name, base_salary, pay_frequency, "
            "pay_day_of_week, pay_day_of_month, pay_anchor_date "
            "FROM employees WHERE department = ? ORDER BY employee_id",
            (department,),
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return json.dumps(rows)

    @tool(
        description="Returns the list of all vendor category names.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_vendor_categories(self) -> str:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT DISTINCT category FROM vendors ORDER BY category"
        ).fetchall()
        conn.close()
        return json.dumps([r[0] for r in rows])

    @tool(
        description=(
            "Returns all vendors in the given category. Each record includes "
            "vendor_id, vendor_name, payment_amount, payment_frequency "
            "(weekly / monthly / quarterly), payment_day_of_week (0=Mon .. 6=Sun, "
            "null for monthly/quarterly), payment_day_of_month (null for weekly), "
            "and is_active (1 = active, 0 = inactive)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Exact vendor category name (case-sensitive).",
                }
            },
            "required": ["category"],
        },
    )
    def get_vendors_by_category(self, category: str) -> str:
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "SELECT vendor_id, vendor_name, payment_amount, payment_frequency, "
            "payment_day_of_week, payment_day_of_month, is_active "
            "FROM vendors WHERE category = ? ORDER BY vendor_id",
            (category,),
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return json.dumps(rows)

    @tool(
        description=(
            "Returns tax liabilities filtered by status and date range. "
            "Each record includes tax_id, tax_type, jurisdiction, amount, "
            "due_date, status, and penalty_rate_daily."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: 'pending', 'paid', or 'deferred'.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start of date range (inclusive), YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End of date range (inclusive), YYYY-MM-DD.",
                },
            },
            "required": ["status", "start_date", "end_date"],
        },
    )
    def get_tax_liabilities(self, status: str, start_date: str, end_date: str) -> str:
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "SELECT tax_id, tax_type, jurisdiction, amount, due_date, "
            "status, penalty_rate_daily "
            "FROM tax_liabilities "
            "WHERE status = ? AND due_date >= ? AND due_date <= ? "
            "ORDER BY due_date, tax_id",
            (status, start_date, end_date),
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return json.dumps(rows)

    @tool(
        description=(
            "Returns historical expense records for a department within a date "
            "range. Each record includes record_id, record_date, category, "
            "budgeted_amount, and actual_amount."
        ),
        parameters={
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": "Exact department name (case-sensitive).",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start of date range (inclusive), YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End of date range (inclusive), YYYY-MM-DD.",
                },
            },
            "required": ["department", "start_date", "end_date"],
        },
    )
    def get_expense_history(self, department: str, start_date: str, end_date: str) -> str:
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "SELECT record_id, record_date, category, budgeted_amount, actual_amount "
            "FROM expense_history "
            "WHERE department = ? AND record_date >= ? AND record_date <= ? "
            "ORDER BY record_date, record_id",
            (department, start_date, end_date),
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return json.dumps(rows)

    @tool(
        description=(
            "Returns the current operating-account balance and the date it was "
            "recorded."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def get_account_balance(self) -> str:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT account_name, current_balance, balance_date FROM account_info "
            "WHERE account_id = 1"
        ).fetchone()
        conn.close()
        return json.dumps({
            "account_name": row[0],
            "current_balance": row[1],
            "balance_date": row[2],
        })

    # ================================================================
    # Ground-truth computation helpers (used by step and verify)
    # ================================================================

    def _compute_ground_truth(self) -> dict:
        """Compute the full ground-truth forecast from DB + workspace."""
        conn = sqlite3.connect(self.db_path)

        # ---------- reference date & forecast window ----------
        ref = datetime.strptime("2025-01-13", "%Y-%m-%d")
        forecast_dates = [ref + timedelta(days=d) for d in range(7)]

        # ---------- cash policy ----------
        policy = self._parse_cash_policy()

        # ---------- variance adjustments ----------
        va_path = os.path.join(self.workspace, "variance_adjustments.json")
        with open(va_path) as f:
            var_adj = json.load(f)

        # ---------- day-of-week weights ----------
        dow_weights = self._parse_day_weights()

        # ---------- current balance ----------
        balance_row = conn.execute(
            "SELECT current_balance FROM account_info WHERE account_id = 1"
        ).fetchone()
        current_balance = balance_row[0]

        # ---------- payroll per day ----------
        employees = conn.execute(
            "SELECT base_salary, pay_frequency, pay_day_of_week, "
            "pay_day_of_month, pay_anchor_date FROM employees"
        ).fetchall()

        payroll_by_day = {}
        for d in forecast_dates:
            ds = d.strftime("%Y-%m-%d")
            total = 0.0
            for sal, freq, dow, dom, anchor in employees:
                if self._employee_paid_on(d, freq, dow, dom, anchor):
                    total += sal
            payroll_by_day[ds] = round(total, 2)

        # ---------- vendor payments per day ----------
        vendors = conn.execute(
            "SELECT payment_amount, payment_frequency, payment_day_of_week, "
            "payment_day_of_month, is_active FROM vendors"
        ).fetchall()

        vendor_by_day = {}
        for d in forecast_dates:
            ds = d.strftime("%Y-%m-%d")
            total = 0.0
            for amt, freq, dow, dom, active in vendors:
                if active and self._vendor_pays_on(d, freq, dow, dom):
                    total += amt
            vendor_by_day[ds] = round(total, 2)

        # ---------- tax liabilities per day ----------
        tax_by_day = {}
        for d in forecast_dates:
            ds = d.strftime("%Y-%m-%d")
            row = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM tax_liabilities "
                "WHERE status = 'pending' AND due_date = ?",
                (ds,),
            ).fetchone()
            tax_by_day[ds] = round(row[0], 2)

        # ---------- operating expense per day ----------
        # average daily actual by category over all history
        hist_rows = conn.execute(
            "SELECT category, actual_amount FROM expense_history"
        ).fetchall()
        distinct_dates = conn.execute(
            "SELECT COUNT(DISTINCT record_date) FROM expense_history"
        ).fetchone()[0]

        cat_totals: Dict[str, float] = {}
        for cat, amt in hist_rows:
            cat_totals[cat] = cat_totals.get(cat, 0.0) + amt

        base_daily = 0.0
        for cat, total in cat_totals.items():
            avg = total / distinct_dates
            factor = var_adj.get(cat, {}).get("adjustment_factor", 1.0)
            base_daily += avg * factor

        opex_by_day = {}
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                      "Friday", "Saturday", "Sunday"]
        for d in forecast_dates:
            ds = d.strftime("%Y-%m-%d")
            wt = dow_weights.get(day_names[d.weekday()], 1.0)
            opex_by_day[ds] = round(base_daily * wt, 2)

        # ---------- projected inflows per day-of-week ----------
        inflow_by_dow = self._compute_avg_inflows()
        inflow_by_day = {}
        for d in forecast_dates:
            ds = d.strftime("%Y-%m-%d")
            inflow_by_day[ds] = round(inflow_by_dow.get(d.weekday(), 0.0), 2)

        conn.close()

        # ---------- build daily projection rows ----------
        projections = []
        running_balance = current_balance
        for d in forecast_dates:
            ds = d.strftime("%Y-%m-%d")
            opening = round(running_balance, 2)
            inflows = inflow_by_day[ds]
            payroll = payroll_by_day[ds]
            vendor = vendor_by_day[ds]
            tax = tax_by_day[ds]
            opex = opex_by_day[ds]
            total_outflow = round(payroll + vendor + tax + opex, 2)
            closing = round(opening + inflows - total_outflow, 2)
            projections.append({
                "date": ds,
                "opening_balance": opening,
                "projected_inflows": inflows,
                "payroll_outflow": payroll,
                "vendor_outflow": vendor,
                "tax_outflow": tax,
                "operating_expense": opex,
                "total_outflow": total_outflow,
                "closing_balance": closing,
            })
            running_balance = closing

        # ---------- funding recommendation ----------
        min_closing = min(p["closing_balance"] for p in projections)
        min_balance = policy["minimum_balance"]
        target_balance = min_balance * (1 + policy["target_buffer_pct"])

        if min_closing < min_balance:
            funding_amount = round(target_balance - min_closing, 2)
            # Find the first day closing < min_balance
            first_shortfall_idx = next(
                i for i, p in enumerate(projections)
                if p["closing_balance"] < min_balance
            )
            # Fund the day before, or the first day itself
            fund_idx = max(0, first_shortfall_idx - 1)
            funding_date = projections[fund_idx]["date"]
            # Determine tier
            funding_method = "asset_liquidation"
            for tier in policy["funding_tiers"]:
                if funding_amount <= tier["max_amount"]:
                    funding_method = tier["method"]
                    break
        else:
            funding_amount = 0.0
            funding_date = "N/A"
            funding_method = "none"

        funding_rec = {
            "recommended_amount": funding_amount,
            "funding_date": funding_date,
            "funding_method": funding_method,
            "min_projected_balance": min_closing,
        }

        return {
            "projections": projections,
            "funding_recommendation": funding_rec,
            "current_balance": current_balance,
        }

    @staticmethod
    def _employee_paid_on(d: datetime, freq: str, dow, dom, anchor) -> bool:
        if freq == "weekly":
            return dow is not None and d.weekday() == dow
        elif freq == "biweekly":
            if dow is None or anchor is None:
                return False
            if d.weekday() != dow:
                return False
            anchor_dt = datetime.strptime(anchor, "%Y-%m-%d")
            return (d - anchor_dt).days % 14 == 0
        elif freq == "monthly":
            return dom is not None and d.day == dom
        return False

    @staticmethod
    def _vendor_pays_on(d: datetime, freq: str, dow, dom) -> bool:
        if freq == "weekly":
            return dow is not None and d.weekday() == dow
        elif freq == "monthly":
            return dom is not None and d.day == dom
        elif freq == "quarterly":
            return dom is not None and d.day == dom and d.month in (1, 4, 7, 10)
        return False

    def _parse_cash_policy(self) -> dict:
        path = os.path.join(self.workspace, "cash_policy.yaml")
        with open(path) as f:
            text = f.read()
        policy = {}
        m = re.search(r"minimum_balance:\s*([\d.]+)", text)
        policy["minimum_balance"] = float(m.group(1)) if m else 250000.0
        m = re.search(r"target_buffer_pct:\s*([\d.]+)", text)
        policy["target_buffer_pct"] = float(m.group(1)) if m else 0.15
        m = re.search(r"emergency_reserve_pct:\s*([\d.]+)", text)
        policy["emergency_reserve_pct"] = float(m.group(1)) if m else 0.05
        # parse funding tiers
        tiers = []
        tier_blocks = re.findall(
            r"-\s*max_amount:\s*([\d.]+)\s*\n\s*method:\s*\"?([^\"]+?)\"?\s*\n\s*lead_time_days:\s*(\d+)",
            text,
        )
        for ma, method, lt in tier_blocks:
            tiers.append({
                "max_amount": float(ma),
                "method": method.strip(),
                "lead_time_days": int(lt),
            })
        policy["funding_tiers"] = tiers
        return policy

    def _parse_day_weights(self) -> dict:
        path = os.path.join(self.workspace, "forecast_parameters.txt")
        with open(path) as f:
            text = f.read()
        weights = {}
        for m in re.finditer(r"(\w+day):\s*([\d.]+)", text):
            weights[m.group(1)] = float(m.group(2))
        return weights

    def _compute_avg_inflows(self) -> Dict[int, float]:
        """Compute average daily inflow by weekday from workspace CSV files."""
        pattern = os.path.join(self.workspace, "weekly_inflows_w*.csv")
        files = sorted(glob.glob(pattern))
        dow_totals: Dict[int, float] = {}
        dow_counts: Dict[int, int] = {}
        dates_seen: Dict[int, set] = {i: set() for i in range(7)}

        for fpath in files:
            with open(fpath, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    d = datetime.strptime(row["date"], "%Y-%m-%d")
                    wd = d.weekday()
                    amt = float(row["amount"])
                    dow_totals[wd] = dow_totals.get(wd, 0.0) + amt
                    dates_seen[wd].add(row["date"])

        result = {}
        for wd in range(7):
            n_days = len(dates_seen[wd])
            if n_days > 0:
                result[wd] = dow_totals.get(wd, 0.0) / n_days
            else:
                result[wd] = 0.0
        return result

    # ================================================================
    # Evaluation
    # ================================================================

    def step(
        self, action: str
    ) -> Tuple[float, Dict[str, Any]]:
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
        gt_proj = gt["projections"]
        gt_fund = gt["funding_recommendation"]

        criteria = {}

        # ---------- 1. projections structure (10 pts) ----------
        proj_path = os.path.join(self.workspace, "daily_projections.csv")
        required_cols = [
            "date", "opening_balance", "projected_inflows",
            "payroll_outflow", "vendor_outflow", "tax_outflow",
            "operating_expense", "total_outflow", "closing_balance",
        ]
        if os.path.exists(proj_path):
            with open(proj_path, newline="") as f:
                reader = csv.DictReader(f)
                agent_rows = list(reader)
            cols_ok = all(c in (reader.fieldnames or []) for c in required_cols)
            rows_ok = len(agent_rows) == 7
            struct_pass = cols_ok and rows_ok
        else:
            agent_rows = []
            struct_pass = False

        criteria["projections_structure"] = {
            "passed": struct_pass,
            "score": 10 if struct_pass else 0,
            "max_score": 10,
            "reason": "" if struct_pass else "daily_projections.csv missing, wrong columns, or wrong row count",
        }

        # Helper to compare a column
        def _col_accuracy(col_name: str, max_pts: int, tolerance: float = 0.02) -> dict:
            if not struct_pass:
                return {"passed": False, "score": 0, "max_score": max_pts,
                        "reason": "projections file not valid"}
            matched = 0
            for gt_row, ag_row in zip(gt_proj, agent_rows):
                try:
                    gt_val = gt_row[col_name]
                    ag_val = float(ag_row[col_name])
                    if abs(gt_val - ag_val) <= tolerance:
                        matched += 1
                except (KeyError, ValueError, TypeError):
                    pass
            score = round(max_pts * matched / 7, 1)
            return {
                "passed": matched == 7,
                "score": score,
                "max_score": max_pts,
                "reason": "" if matched == 7 else f"{7-matched}/7 days mismatch",
            }

        # ---------- 2. payroll accuracy (20 pts) ----------
        criteria["payroll_accuracy"] = _col_accuracy("payroll_outflow", 20)

        # ---------- 3. vendor accuracy (15 pts) ----------
        criteria["vendor_accuracy"] = _col_accuracy("vendor_outflow", 15)

        # ---------- 4. tax accuracy (15 pts) ----------
        criteria["tax_accuracy"] = _col_accuracy("tax_outflow", 15)

        # ---------- 5. operating expense accuracy (15 pts) ----------
        criteria["operating_expense_accuracy"] = _col_accuracy("operating_expense", 15)

        # ---------- 6. closing balance accuracy (10 pts) ----------
        criteria["closing_balance_accuracy"] = _col_accuracy("closing_balance", 10, tolerance=0.10)

        # ---------- 7. funding recommendation (15 pts) ----------
        fund_path = os.path.join(self.workspace, "funding_recommendation.json")
        fund_score = 0
        fund_reason = ""
        if os.path.exists(fund_path):
            try:
                with open(fund_path) as f:
                    agent_fund = json.load(f)
                # Amount check (5 pts) — tolerance ±1000
                ag_amt = float(agent_fund.get("recommended_amount", -1))
                if abs(ag_amt - gt_fund["recommended_amount"]) <= 1000:
                    fund_score += 5
                else:
                    fund_reason += f"amount off (expected ~{gt_fund['recommended_amount']:.2f}); "
                # Date check (5 pts)
                if agent_fund.get("funding_date") == gt_fund["funding_date"]:
                    fund_score += 5
                else:
                    fund_reason += f"date mismatch (expected {gt_fund['funding_date']}); "
                # Method check (5 pts)
                if agent_fund.get("funding_method") == gt_fund["funding_method"]:
                    fund_score += 5
                else:
                    fund_reason += f"method mismatch (expected {gt_fund['funding_method']}); "
            except Exception as e:
                fund_reason = f"error reading funding_recommendation.json: {e}"
        else:
            fund_reason = "funding_recommendation.json not found"

        criteria["funding_recommendation"] = {
            "passed": fund_score == 15,
            "score": fund_score,
            "max_score": 15,
            "reason": fund_reason.strip().rstrip(";"),
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ================================================================
    # Verification
    # ================================================================

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
        from datetime import datetime, timedelta
        import json, csv, os, glob, re

        # ---- 1. Read workspace config files ----
        # forecast_parameters.txt
        with open(os.path.join(self.workspace, "forecast_parameters.txt")) as f:
            fp_text = f.read()
        ref_match = re.search(r"Reference Date:\s*(\S+)", fp_text)
        ref_date_str = ref_match.group(1)
        ref_date = datetime.strptime(ref_date_str, "%Y-%m-%d")
        period_match = re.search(r"Forecast Period:\s*(\d+)", fp_text)
        forecast_days = int(period_match.group(1))
        day_weights = {}
        for m in re.finditer(r"(\w+day):\s*([\d.]+)", fp_text):
            day_weights[m.group(1)] = float(m.group(2))

        forecast_dates = [ref_date + timedelta(days=i) for i in range(forecast_days)]
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                      "Friday", "Saturday", "Sunday"]

        # cash_policy.yaml
        with open(os.path.join(self.workspace, "cash_policy.yaml")) as f:
            cp_text = f.read()
        min_balance = float(re.search(r"minimum_balance:\s*([\d.]+)", cp_text).group(1))
        target_buffer_pct = float(re.search(r"target_buffer_pct:\s*([\d.]+)", cp_text).group(1))
        tiers = []
        for tm in re.finditer(
            r"-\s*max_amount:\s*([\d.]+)\s*\n\s*method:\s*\"?([^\"]+?)\"?\s*\n\s*lead_time_days:\s*(\d+)",
            cp_text,
        ):
            tiers.append({
                "max_amount": float(tm.group(1)),
                "method": tm.group(2).strip(),
                "lead_time_days": int(tm.group(3)),
            })

        # variance_adjustments.json
        with open(os.path.join(self.workspace, "variance_adjustments.json")) as f:
            var_adj = json.load(f)

        # ---- 2. Get account balance (tool call 1) ----
        balance_data = json.loads(self.tools["get_account_balance"]())
        current_balance = balance_data["current_balance"]

        # ---- 3. Get departments and payroll (tool calls 2..10) ----
        departments = json.loads(self.tools["list_departments"]())
        all_employees = []
        for dept in departments:
            emps = json.loads(self.tools["get_payroll_by_department"](department=dept))
            all_employees.extend(emps)

        # ---- 4. Get vendor categories and vendors (tool calls 11..17) ----
        categories = json.loads(self.tools["list_vendor_categories"]())
        all_vendors = []
        for cat in categories:
            vends = json.loads(self.tools["get_vendors_by_category"](category=cat))
            all_vendors.extend(vends)

        # ---- 5. Get pending tax liabilities (tool call 18) ----
        start_str = forecast_dates[0].strftime("%Y-%m-%d")
        end_str = forecast_dates[-1].strftime("%Y-%m-%d")
        taxes = json.loads(self.tools["get_tax_liabilities"](
            status="pending", start_date=start_str, end_date=end_str
        ))

        # ---- 6. Get expense history per department (tool calls 19..26) ----
        hist_start = (ref_date - timedelta(days=30)).strftime("%Y-%m-%d")
        hist_end = (ref_date - timedelta(days=1)).strftime("%Y-%m-%d")
        all_expenses = []
        for dept in departments:
            exps = json.loads(self.tools["get_expense_history"](
                department=dept, start_date=hist_start, end_date=hist_end
            ))
            all_expenses.extend(exps)

        # ---- 7. Compute payroll per day ----
        payroll_by_day = {}
        for d in forecast_dates:
            ds = d.strftime("%Y-%m-%d")
            total = 0.0
            for emp in all_employees:
                freq = emp["pay_frequency"]
                if freq == "weekly":
                    if emp["pay_day_of_week"] is not None and d.weekday() == emp["pay_day_of_week"]:
                        total += emp["base_salary"]
                elif freq == "biweekly":
                    if (emp["pay_day_of_week"] is not None
                            and emp["pay_anchor_date"] is not None
                            and d.weekday() == emp["pay_day_of_week"]):
                        anchor = datetime.strptime(emp["pay_anchor_date"], "%Y-%m-%d")
                        if (d - anchor).days % 14 == 0:
                            total += emp["base_salary"]
                elif freq == "monthly":
                    if emp["pay_day_of_month"] is not None and d.day == emp["pay_day_of_month"]:
                        total += emp["base_salary"]
            payroll_by_day[ds] = round(total, 2)

        # ---- 8. Compute vendor payments per day ----
        vendor_by_day = {}
        for d in forecast_dates:
            ds = d.strftime("%Y-%m-%d")
            total = 0.0
            for v in all_vendors:
                if not v["is_active"]:
                    continue
                freq = v["payment_frequency"]
                if freq == "weekly":
                    if v["payment_day_of_week"] is not None and d.weekday() == v["payment_day_of_week"]:
                        total += v["payment_amount"]
                elif freq == "monthly":
                    if v["payment_day_of_month"] is not None and d.day == v["payment_day_of_month"]:
                        total += v["payment_amount"]
                elif freq == "quarterly":
                    if (v["payment_day_of_month"] is not None
                            and d.day == v["payment_day_of_month"]
                            and d.month in (1, 4, 7, 10)):
                        total += v["payment_amount"]
            vendor_by_day[ds] = round(total, 2)

        # ---- 9. Compute tax per day ----
        tax_by_day = {}
        for d in forecast_dates:
            ds = d.strftime("%Y-%m-%d")
            total = sum(t["amount"] for t in taxes if t["due_date"] == ds)
            tax_by_day[ds] = round(total, 2)

        # ---- 10. Compute operating expense per day ----
        distinct_dates = set(e["record_date"] for e in all_expenses)
        num_days = len(distinct_dates)
        cat_totals = {}
        for e in all_expenses:
            cat_totals[e["category"]] = cat_totals.get(e["category"], 0.0) + e["actual_amount"]

        base_daily = 0.0
        for cat, total in cat_totals.items():
            avg = total / num_days
            factor = var_adj.get(cat, {}).get("adjustment_factor", 1.0)
            base_daily += avg * factor

        opex_by_day = {}
        for d in forecast_dates:
            ds = d.strftime("%Y-%m-%d")
            wt = day_weights.get(day_names[d.weekday()], 1.0)
            opex_by_day[ds] = round(base_daily * wt, 2)

        # ---- 11. Compute projected inflows by weekday ----
        inflow_files = sorted(glob.glob(os.path.join(self.workspace, "weekly_inflows_w*.csv")))
        dow_totals = {}
        dates_seen = {i: set() for i in range(7)}
        for fpath in inflow_files:
            with open(fpath, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    d = datetime.strptime(row["date"], "%Y-%m-%d")
                    wd = d.weekday()
                    dow_totals[wd] = dow_totals.get(wd, 0.0) + float(row["amount"])
                    dates_seen[wd].add(row["date"])

        avg_inflow_by_dow = {}
        for wd in range(7):
            n = len(dates_seen[wd])
            avg_inflow_by_dow[wd] = dow_totals.get(wd, 0.0) / n if n > 0 else 0.0

        inflow_by_day = {}
        for d in forecast_dates:
            ds = d.strftime("%Y-%m-%d")
            inflow_by_day[ds] = round(avg_inflow_by_dow[d.weekday()], 2)

        # ---- 12. Build daily projections ----
        projections = []
        running = current_balance
        for d in forecast_dates:
            ds = d.strftime("%Y-%m-%d")
            opening = round(running, 2)
            inflows = inflow_by_day[ds]
            payroll = payroll_by_day[ds]
            vendor = vendor_by_day[ds]
            tax = tax_by_day[ds]
            opex = opex_by_day[ds]
            total_outflow = round(payroll + vendor + tax + opex, 2)
            closing = round(opening + inflows - total_outflow, 2)
            projections.append({
                "date": ds,
                "opening_balance": opening,
                "projected_inflows": inflows,
                "payroll_outflow": payroll,
                "vendor_outflow": vendor,
                "tax_outflow": tax,
                "operating_expense": opex,
                "total_outflow": total_outflow,
                "closing_balance": closing,
            })
            running = closing

        # ---- 13. Write daily_projections.csv ----
        proj_path = os.path.join(self.workspace, "daily_projections.csv")
        fieldnames = [
            "date", "opening_balance", "projected_inflows",
            "payroll_outflow", "vendor_outflow", "tax_outflow",
            "operating_expense", "total_outflow", "closing_balance",
        ]
        with open(proj_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in projections:
                writer.writerow({k: f"{v:.2f}" if isinstance(v, float) else v
                                 for k, v in row.items()})

        # ---- 14. Compute and write funding recommendation ----
        min_closing = min(p["closing_balance"] for p in projections)
        target_balance = min_balance * (1 + target_buffer_pct)

        if min_closing < min_balance:
            funding_amount = round(target_balance - min_closing, 2)
            first_shortfall_idx = next(
                i for i, p in enumerate(projections)
                if p["closing_balance"] < min_balance
            )
            fund_idx = max(0, first_shortfall_idx - 1)
            funding_date = projections[fund_idx]["date"]
            funding_method = "asset_liquidation"
            for tier in tiers:
                if funding_amount <= tier["max_amount"]:
                    funding_method = tier["method"]
                    break
        else:
            funding_amount = 0.0
            funding_date = "N/A"
            funding_method = "none"

        fund_rec = {
            "recommended_amount": funding_amount,
            "funding_date": funding_date,
            "funding_method": funding_method,
            "min_projected_balance": min_closing,
        }
        with open(os.path.join(self.workspace, "funding_recommendation.json"), "w") as f:
            json.dump(fund_rec, f, indent=2)

        # ---- 15. Build action string ----
        total_weekly_outflow = round(sum(p["total_outflow"] for p in projections), 2)
        action = (
            f"Weekly Cash Forecast Summary:\n"
            f"Forecast period: {start_str} to {end_str}\n"
            f"Starting balance: ${current_balance:,.2f}\n"
            f"Total weekly outflow: ${total_weekly_outflow:,.2f}\n"
            f"Lowest projected closing balance: ${min_closing:,.2f}\n"
        )
        if funding_amount > 0:
            action += (
                f"Funding required: ${funding_amount:,.2f} via {funding_method} "
                f"by {funding_date}\n"
            )
        else:
            action += "No additional funding required for this period.\n"

        return self.step(action)
