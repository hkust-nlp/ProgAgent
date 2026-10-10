"""Budget Variance Analysis - Task Environment."""
import sqlite3
import os
import json
import csv
import math
import glob as globmod
from typing import Tuple, Dict, List, Any

import yaml


# ---------------------------------------------------------------------------
# Tool decorator
# ---------------------------------------------------------------------------

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ---------------------------------------------------------------------------
# Task_Env
# ---------------------------------------------------------------------------

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

    # ===================================================================
    # Tools
    # ===================================================================

    PAGE_SIZE = 20

    @tool(
        description="List all department names in the organisation.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_departments(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT department FROM budget_allocations ORDER BY department")
        depts = [r[0] for r in cur.fetchall()]
        conn.close()
        return {"departments": depts}

    @tool(
        description="Get base budget allocations for a given department and fiscal year. Returns category-level annual budget amounts.",
        parameters={
            "type": "object",
            "properties": {
                "department": {"type": "string", "description": "Department name"},
                "fiscal_year": {"type": "integer", "description": "Fiscal year (e.g. 2025)"},
            },
            "required": ["department", "fiscal_year"],
        },
    )
    def get_budget_allocations(self, department: str, fiscal_year: int = 2025) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT category, annual_budget FROM budget_allocations WHERE department=? AND fiscal_year=? ORDER BY category",
            (department, fiscal_year),
        )
        rows = [{"category": r[0], "annual_budget": r[1]} for r in cur.fetchall()]
        conn.close()
        return {"department": department, "fiscal_year": fiscal_year, "allocations": rows}

    @tool(
        description="Query general-ledger entries for a department, optionally filtered by category. Returns paginated results (page_size=20).",
        parameters={
            "type": "object",
            "properties": {
                "department": {"type": "string", "description": "Department name"},
                "category": {"type": "string", "description": "Spending category (optional)"},
                "page": {"type": "integer", "description": "Page number, starting at 1 (default 1)"},
            },
            "required": ["department"],
        },
    )
    def query_gl_entries(self, department: str, category: str = None, page: int = 1) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        params: list = [department]
        sql = "SELECT id, department, category, entry_date, amount, vendor, description, reference_no FROM gl_entries WHERE department=?"
        if category:
            sql += " AND category=?"
            params.append(category)
        # Count
        cnt = cur.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]
        sql += " ORDER BY entry_date, id"
        sql += f" LIMIT {self.PAGE_SIZE} OFFSET {(page - 1) * self.PAGE_SIZE}"
        cur.execute(sql, params)
        cols = ["id", "department", "category", "entry_date", "amount", "vendor", "description", "reference_no"]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        total_pages = math.ceil(cnt / self.PAGE_SIZE) if cnt else 1
        return {"entries": rows, "page": page, "total_pages": total_pages, "total_count": cnt}

    @tool(
        description="Query purchase orders for a department, optionally filtered by status. Returns paginated results (page_size=20).",
        parameters={
            "type": "object",
            "properties": {
                "department": {"type": "string", "description": "Department name"},
                "status": {"type": "string", "description": "PO status filter: Open, Closed, or Cancelled (optional)"},
                "page": {"type": "integer", "description": "Page number, starting at 1 (default 1)"},
            },
            "required": ["department"],
        },
    )
    def get_purchase_orders(self, department: str, status: str = None, page: int = 1) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        params: list = [department]
        sql = "SELECT id, department, category, vendor, po_number, po_date, amount, status, project_name FROM purchase_orders WHERE department=?"
        if status:
            sql += " AND status=?"
            params.append(status)
        cnt = cur.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]
        sql += " ORDER BY po_date, id"
        sql += f" LIMIT {self.PAGE_SIZE} OFFSET {(page - 1) * self.PAGE_SIZE}"
        cur.execute(sql, params)
        cols = ["id", "department", "category", "vendor", "po_number", "po_date", "amount", "status", "project_name"]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        total_pages = math.ceil(cnt / self.PAGE_SIZE) if cnt else 1
        return {"purchase_orders": rows, "page": page, "total_pages": total_pages, "total_count": cnt}

    @tool(
        description="Query vendor invoice line items, optionally filtered by department, category, or vendor. Returns paginated results (page_size=20).",
        parameters={
            "type": "object",
            "properties": {
                "department": {"type": "string", "description": "Department name (optional)"},
                "category": {"type": "string", "description": "Spending category (optional)"},
                "vendor": {"type": "string", "description": "Vendor name (optional)"},
                "page": {"type": "integer", "description": "Page number, starting at 1 (default 1)"},
            },
            "required": [],
        },
    )
    def query_invoice_lines(self, department: str = None, category: str = None, vendor: str = None, page: int = 1) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        params: list = []
        clauses: list = []
        if department:
            clauses.append("department=?")
            params.append(department)
        if category:
            clauses.append("category=?")
            params.append(category)
        if vendor:
            clauses.append("vendor=?")
            params.append(vendor)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        base = f"SELECT id, invoice_number, vendor, department, category, line_description, amount, invoice_date, po_number FROM invoice_line_items{where}"
        cnt = cur.execute(f"SELECT COUNT(*) FROM ({base})", params).fetchone()[0]
        base += " ORDER BY invoice_date, id"
        base += f" LIMIT {self.PAGE_SIZE} OFFSET {(page - 1) * self.PAGE_SIZE}"
        cur.execute(base, params)
        cols = ["id", "invoice_number", "vendor", "department", "category", "line_description", "amount", "invoice_date", "po_number"]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        total_pages = math.ceil(cnt / self.PAGE_SIZE) if cnt else 1
        return {"invoice_lines": rows, "page": page, "total_pages": total_pages, "total_count": cnt}

    @tool(
        description="List projects, optionally filtered by department.",
        parameters={
            "type": "object",
            "properties": {
                "department": {"type": "string", "description": "Department name (optional)"},
            },
            "required": [],
        },
    )
    def list_projects(self, department: str = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if department:
            cur.execute("SELECT DISTINCT project_name, department FROM project_milestones WHERE department=? ORDER BY project_name", (department,))
        else:
            cur.execute("SELECT DISTINCT project_name, department FROM project_milestones ORDER BY project_name")
        rows = [{"project_name": r[0], "department": r[1]} for r in cur.fetchall()]
        conn.close()
        return {"projects": rows}

    @tool(
        description="Get all milestones for a given project.",
        parameters={
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
            },
            "required": ["project_name"],
        },
    )
    def get_project_milestones(self, project_name: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, project_name, department, category, milestone_name, planned_date, forecast_amount, status "
            "FROM project_milestones WHERE project_name=? ORDER BY planned_date, id",
            (project_name,),
        )
        cols = ["id", "project_name", "department", "category", "milestone_name", "planned_date", "forecast_amount", "status"]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return {"milestones": rows}

    # ===================================================================
    # Ground-truth computation (shared by step & verify)
    # ===================================================================

    def _compute_ground_truth(self):
        """Return the full expected variance table as a list of dicts,
        computed from DB + workspace files. Used by both step() and verify()."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # 1. Base budgets
        base_budgets = {}
        for r in conn.execute("SELECT department, category, annual_budget FROM budget_allocations WHERE fiscal_year=2025"):
            key = (r["department"], r["category"])
            base_budgets[key] = base_budgets.get(key, 0.0) + r["annual_budget"]

        # 2. Budget amendments from workspace
        amendments = {}
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "budget_amendment_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (row["department"], row["category"])
                    amendments[key] = amendments.get(key, 0.0) + float(row["amendment_amount"])

        # 3. Vendor discount map from workspace
        vendor_discounts = {}
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "vendor_contract_*.json"))):
            with open(fpath) as f:
                contracts = json.load(f)
            for c in contracts:
                vendor_discounts[c["vendor_name"]] = c["committed_discount_pct"]

        # 4. Project risk adjustment factors from workspace
        project_factors = {}
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "project_forecast_*.yaml"))):
            with open(fpath) as f:
                data = yaml.safe_load(f) or {}
            for pname, info in data.items():
                project_factors[pname] = info["risk_adjustment_factor"]

        # 5. GL actuals
        gl_actuals = {}
        for r in conn.execute("SELECT department, category, SUM(amount) as total FROM gl_entries GROUP BY department, category"):
            gl_actuals[(r["department"], r["category"])] = r["total"]

        # 6. Open PO committed amounts (with vendor discount applied)
        po_committed = {}
        for r in conn.execute("SELECT department, category, vendor, amount FROM purchase_orders WHERE status='Open'"):
            key = (r["department"], r["category"])
            discount = vendor_discounts.get(r["vendor"], 0.0)
            effective = r["amount"] * (1.0 - discount)
            po_committed[key] = po_committed.get(key, 0.0) + effective

        # 7. Pending milestone forecasts (with risk adjustment)
        milestone_forecast = {}
        for r in conn.execute("SELECT project_name, department, category, forecast_amount FROM project_milestones WHERE status='Pending'"):
            key = (r["department"], r["category"])
            factor = project_factors.get(r["project_name"], 1.0)
            milestone_forecast[key] = milestone_forecast.get(key, 0.0) + r["forecast_amount"] * factor

        # 8. Invoice line items by (dept, cat, vendor) for top-vendor lookup
        vendor_spend = {}
        for r in conn.execute("SELECT department, category, vendor, SUM(amount) as total FROM invoice_line_items GROUP BY department, category, vendor"):
            key = (r["department"], r["category"])
            if key not in vendor_spend:
                vendor_spend[key] = {}
            vendor_spend[key][r["vendor"]] = r["total"]

        conn.close()

        # 9. Variance policy
        policy_path = os.path.join(self.workspace, "variance_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)
        threshold = policy["variance_threshold_pct"]

        # 10. Build result table
        results = []
        for key in sorted(base_budgets.keys()):
            dept, cat = key
            base = base_budgets[key]
            amend = amendments.get(key, 0.0)
            adj_budget = base + amend
            gl = gl_actuals.get(key, 0.0)
            po = po_committed.get(key, 0.0)
            ms = milestone_forecast.get(key, 0.0)
            total_exp = gl + po + ms
            variance_amt = total_exp - adj_budget
            variance_pct = round(variance_amt / adj_budget * 100, 2) if adj_budget != 0 else 0.0
            flagged = "Yes" if abs(variance_pct) > threshold else "No"

            # Top vendor for this (dept, cat) from invoice lines
            vs = vendor_spend.get(key, {})
            top_vendor = max(vs, key=vs.get) if vs else "N/A"

            results.append({
                "department": dept,
                "category": cat,
                "adjusted_budget": round(adj_budget, 2),
                "gl_actual": round(gl, 2),
                "po_committed": round(po, 2),
                "milestone_forecast": round(ms, 2),
                "total_exposure": round(total_exp, 2),
                "variance_amount": round(variance_amt, 2),
                "variance_pct": variance_pct,
                "flagged": flagged,
                "top_vendor": top_vendor,
            })

        return results, threshold

    # ===================================================================
    # step
    # ===================================================================

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
        gt_results, threshold = self._compute_ground_truth()
        gt_by_key = {(r["department"], r["category"]): r for r in gt_results}
        flagged_gt = [r for r in gt_results if r["flagged"] == "Yes"]

        criteria: Dict[str, Dict] = {}

        # --- Criterion 1: Report file exists with correct columns (15 pts) ---
        report_path = os.path.join(self.workspace, "variance_report.csv")
        c1_score = 0
        c1_max = 15
        report_rows = []
        expected_cols = [
            "department", "category", "adjusted_budget", "gl_actual",
            "po_committed", "milestone_forecast", "total_exposure",
            "variance_amount", "variance_pct", "flagged",
        ]
        if os.path.exists(report_path):
            with open(report_path) as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    header = [h.strip() for h in reader.fieldnames]
                    if all(c in header for c in expected_cols):
                        c1_score = 15
                        for row in reader:
                            report_rows.append({k.strip(): v.strip() for k, v in row.items()})
                    else:
                        missing = [c for c in expected_cols if c not in header]
                        criteria["report_file_format"] = {
                            "passed": False, "score": 5, "max_score": c1_max,
                            "reason": f"Missing columns: {missing}",
                        }
        if "report_file_format" not in criteria:
            criteria["report_file_format"] = {
                "passed": c1_score == c1_max,
                "score": c1_score,
                "max_score": c1_max,
                "reason": "" if c1_score == c1_max else "variance_report.csv not found or unreadable",
            }

        # --- Criterion 2: Correct row coverage (10 pts) ---
        c2_max = 10
        report_keys = set()
        for r in report_rows:
            report_keys.add((r.get("department", ""), r.get("category", "")))
        gt_keys = set(gt_by_key.keys())
        coverage = len(report_keys & gt_keys) / len(gt_keys) if gt_keys else 0
        c2_score = round(c2_max * coverage, 1)
        criteria["row_coverage"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": "" if c2_score == c2_max else f"Found {len(report_keys & gt_keys)}/{len(gt_keys)} expected rows",
        }

        # --- Criterion 3: Adjusted budget accuracy (20 pts) ---
        c3_max = 20
        correct_budget = 0
        total_checked = 0
        for r in report_rows:
            key = (r.get("department", ""), r.get("category", ""))
            if key in gt_by_key:
                total_checked += 1
                try:
                    val = float(r["adjusted_budget"])
                    if abs(val - gt_by_key[key]["adjusted_budget"]) < 1.0:
                        correct_budget += 1
                except (ValueError, KeyError):
                    pass
        budget_acc = correct_budget / total_checked if total_checked else 0
        c3_score = round(c3_max * budget_acc, 1)
        criteria["adjusted_budget_accuracy"] = {
            "passed": c3_score >= c3_max * 0.95,
            "score": c3_score,
            "max_score": c3_max,
            "reason": "" if c3_score >= c3_max * 0.95 else f"{correct_budget}/{total_checked} correct",
        }

        # --- Criterion 4: GL actual accuracy (15 pts) ---
        c4_max = 15
        correct_gl = 0
        total_checked_gl = 0
        for r in report_rows:
            key = (r.get("department", ""), r.get("category", ""))
            if key in gt_by_key:
                total_checked_gl += 1
                try:
                    val = float(r["gl_actual"])
                    if abs(val - gt_by_key[key]["gl_actual"]) < 1.0:
                        correct_gl += 1
                except (ValueError, KeyError):
                    pass
        gl_acc = correct_gl / total_checked_gl if total_checked_gl else 0
        c4_score = round(c4_max * gl_acc, 1)
        criteria["gl_actual_accuracy"] = {
            "passed": c4_score >= c4_max * 0.95,
            "score": c4_score,
            "max_score": c4_max,
            "reason": "" if c4_score >= c4_max * 0.95 else f"{correct_gl}/{total_checked_gl} correct",
        }

        # --- Criterion 5: Total exposure accuracy (15 pts) ---
        c5_max = 15
        correct_exp = 0
        total_checked_exp = 0
        for r in report_rows:
            key = (r.get("department", ""), r.get("category", ""))
            if key in gt_by_key:
                total_checked_exp += 1
                try:
                    val = float(r["total_exposure"])
                    if abs(val - gt_by_key[key]["total_exposure"]) < 5.0:
                        correct_exp += 1
                except (ValueError, KeyError):
                    pass
        exp_acc = correct_exp / total_checked_exp if total_checked_exp else 0
        c5_score = round(c5_max * exp_acc, 1)
        criteria["total_exposure_accuracy"] = {
            "passed": c5_score >= c5_max * 0.95,
            "score": c5_score,
            "max_score": c5_max,
            "reason": "" if c5_score >= c5_max * 0.95 else f"{correct_exp}/{total_checked_exp} correct",
        }

        # --- Criterion 6: Variance percentage accuracy (10 pts) ---
        c6_max = 10
        correct_pct = 0
        total_checked_pct = 0
        for r in report_rows:
            key = (r.get("department", ""), r.get("category", ""))
            if key in gt_by_key:
                total_checked_pct += 1
                try:
                    val = float(r["variance_pct"])
                    if abs(val - gt_by_key[key]["variance_pct"]) < 0.5:
                        correct_pct += 1
                except (ValueError, KeyError):
                    pass
        pct_acc = correct_pct / total_checked_pct if total_checked_pct else 0
        c6_score = round(c6_max * pct_acc, 1)
        criteria["variance_pct_accuracy"] = {
            "passed": c6_score >= c6_max * 0.95,
            "score": c6_score,
            "max_score": c6_max,
            "reason": "" if c6_score >= c6_max * 0.95 else f"{correct_pct}/{total_checked_pct} correct",
        }

        # --- Criterion 7: Flagged items in action string (15 pts) ---
        c7_max = 15
        flagged_mentioned = 0
        action_upper = action.upper() if action else ""
        for item in flagged_gt:
            dept_in = item["department"].upper() in action_upper
            cat_in = item["category"].upper() in action_upper
            if dept_in and cat_in:
                flagged_mentioned += 1
        flag_ratio = flagged_mentioned / len(flagged_gt) if flagged_gt else 1.0
        c7_score = round(c7_max * flag_ratio, 1)
        criteria["flagged_items_in_response"] = {
            "passed": c7_score >= c7_max * 0.9,
            "score": c7_score,
            "max_score": c7_max,
            "reason": "" if c7_score >= c7_max * 0.9 else f"{flagged_mentioned}/{len(flagged_gt)} flagged items mentioned",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
        reward = round(total_score / max_score, 4) if max_score else 0.0

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ===================================================================
    # verify
    # ===================================================================

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        tool_calls = 0

        # 1. List departments
        dept_result = self.tools["list_departments"]()
        tool_calls += 1
        departments = dept_result["departments"]

        # 2. For each department, get budget allocations
        base_budgets = {}  # (dept, cat) -> amount
        for dept in departments:
            res = self.tools["get_budget_allocations"](department=dept, fiscal_year=2025)
            tool_calls += 1
            for alloc in res["allocations"]:
                key = (dept, alloc["category"])
                base_budgets[key] = base_budgets.get(key, 0.0) + alloc["annual_budget"]

        # 3. Read budget amendments from workspace
        amendments = {}
        import glob as _glob
        for fpath in sorted(_glob.glob(os.path.join(self.workspace, "budget_amendment_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (row["department"], row["category"])
                    amendments[key] = amendments.get(key, 0.0) + float(row["amendment_amount"])

        # 4. Read vendor contracts from workspace
        vendor_discounts = {}
        for fpath in sorted(_glob.glob(os.path.join(self.workspace, "vendor_contract_*.json"))):
            with open(fpath) as f:
                contracts = json.load(f)
            for c in contracts:
                vendor_discounts[c["vendor_name"]] = c["committed_discount_pct"]

        # 5. Read project forecast adjustments from workspace
        project_factors = {}
        for fpath in sorted(_glob.glob(os.path.join(self.workspace, "project_forecast_*.yaml"))):
            with open(fpath) as f:
                data = yaml.safe_load(f) or {}
            for pname, info in data.items():
                project_factors[pname] = info["risk_adjustment_factor"]

        # 6. Read variance policy
        with open(os.path.join(self.workspace, "variance_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        threshold = policy["variance_threshold_pct"]

        # 7. Query GL entries for each department (paginated)
        gl_actuals = {}
        for dept in departments:
            page = 1
            while True:
                res = self.tools["query_gl_entries"](department=dept, page=page)
                tool_calls += 1
                for entry in res["entries"]:
                    key = (entry["department"], entry["category"])
                    gl_actuals[key] = gl_actuals.get(key, 0.0) + entry["amount"]
                if page >= res["total_pages"]:
                    break
                page += 1

        # 8. Query open POs for each department (paginated)
        po_committed = {}
        for dept in departments:
            page = 1
            while True:
                res = self.tools["get_purchase_orders"](department=dept, status="Open", page=page)
                tool_calls += 1
                for po in res["purchase_orders"]:
                    key = (po["department"], po["category"])
                    discount = vendor_discounts.get(po["vendor"], 0.0)
                    effective = po["amount"] * (1.0 - discount)
                    po_committed[key] = po_committed.get(key, 0.0) + effective
                if page >= res["total_pages"]:
                    break
                page += 1

        # 9. Query project milestones
        proj_res = self.tools["list_projects"]()
        tool_calls += 1
        milestone_forecast = {}
        for proj in proj_res["projects"]:
            ms_res = self.tools["get_project_milestones"](project_name=proj["project_name"])
            tool_calls += 1
            for ms in ms_res["milestones"]:
                if ms["status"] == "Pending":
                    key = (ms["department"], ms["category"])
                    factor = project_factors.get(ms["project_name"], 1.0)
                    milestone_forecast[key] = milestone_forecast.get(key, 0.0) + ms["forecast_amount"] * factor

        # 10. Query invoice lines per department for top-vendor analysis
        vendor_spend = {}  # (dept, cat) -> {vendor: total}
        for dept in departments:
            page = 1
            while True:
                res = self.tools["query_invoice_lines"](department=dept, page=page)
                tool_calls += 1
                for line in res["invoice_lines"]:
                    key = (line["department"], line["category"])
                    if key not in vendor_spend:
                        vendor_spend[key] = {}
                    vendor_spend[key][line["vendor"]] = vendor_spend[key].get(line["vendor"], 0.0) + line["amount"]
                if page >= res["total_pages"]:
                    break
                page += 1

        # 11. Compute variance table
        results = []
        for key in sorted(base_budgets.keys()):
            dept, cat = key
            base = base_budgets[key]
            amend = amendments.get(key, 0.0)
            adj_budget = base + amend
            gl = gl_actuals.get(key, 0.0)
            po = po_committed.get(key, 0.0)
            ms = milestone_forecast.get(key, 0.0)
            total_exp = gl + po + ms
            variance_amt = total_exp - adj_budget
            variance_pct = round(variance_amt / adj_budget * 100, 2) if adj_budget != 0 else 0.0
            flagged = "Yes" if abs(variance_pct) > threshold else "No"
            vs = vendor_spend.get(key, {})
            top_vendor = max(vs, key=vs.get) if vs else "N/A"
            results.append({
                "department": dept,
                "category": cat,
                "adjusted_budget": round(adj_budget, 2),
                "gl_actual": round(gl, 2),
                "po_committed": round(po, 2),
                "milestone_forecast": round(ms, 2),
                "total_exposure": round(total_exp, 2),
                "variance_amount": round(variance_amt, 2),
                "variance_pct": variance_pct,
                "flagged": flagged,
                "top_vendor": top_vendor,
            })

        # 12. Write variance_report.csv
        report_path = os.path.join(self.workspace, "variance_report.csv")
        fieldnames = [
            "department", "category", "adjusted_budget", "gl_actual",
            "po_committed", "milestone_forecast", "total_exposure",
            "variance_amount", "variance_pct", "flagged", "top_vendor",
        ]
        with open(report_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(results)

        # 13. Construct action string with flagged items summary
        flagged_items = [r for r in results if r["flagged"] == "Yes"]
        action_lines = ["Departmental Budget Variance Analysis Complete.\n"]
        action_lines.append(f"Total line items analysed: {len(results)}")
        action_lines.append(f"Items flagged (>{threshold}% variance): {len(flagged_items)}\n")
        action_lines.append("Flagged Items Summary:")
        for item in flagged_items:
            action_lines.append(
                f"- {item['department']} / {item['category']}: "
                f"Adjusted Budget={item['adjusted_budget']:.2f}, "
                f"Total Exposure={item['total_exposure']:.2f}, "
                f"Variance={item['variance_pct']:.2f}%, "
                f"Top Vendor={item['top_vendor']}"
            )
        action_lines.append(f"\nVariance report saved as variance_report.csv.")
        action = "\n".join(action_lines)

        print(f"verify: {tool_calls} tool calls made")
        return self.step(action)
