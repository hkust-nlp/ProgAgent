import sqlite3
import os
import json
import csv
import glob
import math
from typing import Tuple, Dict, List, Any

import yaml


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

    # ---- Tool Methods ----

    @tool(
        description="List subcontractors with pagination. Returns a page of subcontractor records including id, name, trade, and contract_value.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 20)"
                }
            },
            "required": ["page", "page_size"]
        }
    )
    def list_subcontractors(self, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM subcontractors")
        total = cur.fetchone()["cnt"]
        cur.execute("SELECT id, name, trade, contract_value, status FROM subcontractors ORDER BY id LIMIT ? OFFSET ?",
                     (page_size, offset))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"subcontractors": rows, "total": total, "page": page, "page_size": page_size}

    @tool(
        description="Get detailed information for a specific subcontractor by ID, including contact info, contract value, bond amount, and start date.",
        parameters={
            "type": "object",
            "properties": {
                "subcontractor_id": {
                    "type": "integer",
                    "description": "The subcontractor ID"
                }
            },
            "required": ["subcontractor_id"]
        }
    )
    def get_subcontractor(self, subcontractor_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM subcontractors WHERE id = ?", (subcontractor_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Subcontractor {subcontractor_id} not found"}

    @tool(
        description="List schedule items for a given subcontractor with pagination. Returns item_code, description, planned dates, and budgeted_amount.",
        parameters={
            "type": "object",
            "properties": {
                "subcontractor_id": {
                    "type": "integer",
                    "description": "The subcontractor ID"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (max 20)"
                }
            },
            "required": ["subcontractor_id", "page", "page_size"]
        }
    )
    def list_schedule_items(self, subcontractor_id: int, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM schedule_items WHERE subcontractor_id = ?", (subcontractor_id,))
        total = cur.fetchone()["cnt"]
        cur.execute("SELECT * FROM schedule_items WHERE subcontractor_id = ? ORDER BY id LIMIT ? OFFSET ?",
                     (subcontractor_id, page_size, offset))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"items": rows, "total": total, "page": page, "page_size": page_size}

    @tool(
        description="Get details of a single schedule item by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "integer",
                    "description": "The schedule item ID"
                }
            },
            "required": ["item_id"]
        }
    )
    def get_schedule_item(self, item_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM schedule_items WHERE id = ?", (item_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Schedule item {item_id} not found"}

    @tool(
        description="List payment applications filtered by status with pagination. Status can be 'pending', 'approved', 'paid', or 'rejected'.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by application status",
                    "enum": ["pending", "approved", "paid", "rejected"]
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (max 10)"
                }
            },
            "required": ["status", "page", "page_size"]
        }
    )
    def list_payment_applications(self, status: str, page: int, page_size: int):
        page_size = min(page_size, 10)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM payment_applications WHERE status = ?", (status,))
        total = cur.fetchone()["cnt"]
        cur.execute(
            "SELECT id, subcontractor_id, schedule_item_id, application_number, period_start, period_end, "
            "claimed_completion_pct, claimed_amount, submission_date, status "
            "FROM payment_applications WHERE status = ? ORDER BY id LIMIT ? OFFSET ?",
            (status, page_size, offset)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"applications": rows, "total": total, "page": page, "page_size": page_size}

    @tool(
        description="Get detailed information for a specific payment application by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "application_id": {
                    "type": "integer",
                    "description": "The payment application ID"
                }
            },
            "required": ["application_id"]
        }
    )
    def get_payment_application(self, application_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM payment_applications WHERE id = ?", (application_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Payment application {application_id} not found"}

    @tool(
        description="Get material delivery records for a specific schedule item. Returns all deliveries including PO number, material description, quantities, amounts, and delivery date.",
        parameters={
            "type": "object",
            "properties": {
                "schedule_item_id": {
                    "type": "integer",
                    "description": "The schedule item ID"
                }
            },
            "required": ["schedule_item_id"]
        }
    )
    def get_material_deliveries(self, schedule_item_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM material_deliveries WHERE schedule_item_id = ? ORDER BY id", (schedule_item_id,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"deliveries": rows, "schedule_item_id": schedule_item_id}

    @tool(
        description="Get the architect inspection report for a specific schedule item. Returns the most recent inspection including verified completion percentage, deficiency status, and sign-off.",
        parameters={
            "type": "object",
            "properties": {
                "schedule_item_id": {
                    "type": "integer",
                    "description": "The schedule item ID"
                }
            },
            "required": ["schedule_item_id"]
        }
    )
    def get_inspection_report(self, schedule_item_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM inspection_reports WHERE schedule_item_id = ? ORDER BY inspection_date DESC LIMIT 1",
            (schedule_item_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"No inspection report found for schedule item {schedule_item_id}"}

    # ---- Step (Evaluation) ----

    def _compute_ground_truth(self):
        """Compute the ground truth certified payment schedule."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Load policy
        policy_path = os.path.join(self.workspace, "payment_policy.yaml")
        with open(policy_path, "r") as f:
            policy = yaml.safe_load(f)

        retention_rate = policy["retention_rate"]
        deficiency_deduction_rate = policy["deficiency_deduction_rate"]
        material_discrepancy_tolerance = policy["material_discrepancy_tolerance"]
        material_discrepancy_penalty_rate = policy["material_discrepancy_penalty_rate"]
        max_allowed_stoppage = policy["max_allowed_stoppage_days"]
        delay_penalty_rate = policy["delay_penalty_rate"]
        minimum_approved_pct = policy["minimum_approved_pct"]

        # Get pending applications
        cur.execute("SELECT * FROM payment_applications WHERE status = 'pending' ORDER BY id")
        pending_apps = [dict(r) for r in cur.fetchall()]

        # Load supervisor logs and parse stoppages
        logs_dir = os.path.join(self.workspace, "logs")
        item_stoppage_days = {}
        if os.path.isdir(logs_dir):
            for log_file in sorted(glob.glob(os.path.join(logs_dir, "log_*.md"))):
                with open(log_file, "r") as f:
                    content = f.read()
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("- SI-") and "No activity" in line:
                        item_code = line.split(":")[0].replace("- ", "").strip()
                        item_stoppage_days[item_code] = item_stoppage_days.get(item_code, 0) + 1

        results = []
        for app in pending_apps:
            app_id = app["id"]
            sub_id = app["subcontractor_id"]
            item_id = app["schedule_item_id"]
            claimed_pct = app["claimed_completion_pct"]
            claimed_amount = app["claimed_amount"]

            # Get subcontractor name
            cur.execute("SELECT name FROM subcontractors WHERE id = ?", (sub_id,))
            sub_row = cur.fetchone()
            sub_name = sub_row["name"] if sub_row else "Unknown"

            # Get schedule item
            cur.execute("SELECT * FROM schedule_items WHERE id = ?", (item_id,))
            item_row = cur.fetchone()
            if not item_row:
                continue
            item = dict(item_row)
            item_code = item["item_code"]
            item_desc = item["description"]
            budgeted_amount = item["budgeted_amount"]

            # Get inspection report
            cur.execute(
                "SELECT * FROM inspection_reports WHERE schedule_item_id = ? ORDER BY inspection_date DESC LIMIT 1",
                (item_id,)
            )
            insp_row = cur.fetchone()
            verified_pct = 0.0
            deficiency_flag = 0
            if insp_row:
                insp = dict(insp_row)
                verified_pct = insp["verified_completion_pct"]
                deficiency_flag = insp["deficiency_flag"]

            # Read completion certificate
            cert_path = os.path.join(self.workspace, "certificates", f"cert_{app_id:04d}.json")
            certified_pct = 0.0
            supervisor_signed = False
            if os.path.exists(cert_path):
                with open(cert_path, "r") as f:
                    cert = json.load(f)
                certified_pct = cert.get("certified_completion_pct", 0.0)
                supervisor_signed = cert.get("supervisor_signed_off", False)

            # Determine approved percentage
            approved_pct = min(claimed_pct, verified_pct, certified_pct)

            # Check rejection conditions
            status = "approved"
            if not supervisor_signed:
                status = "rejected"
            elif approved_pct < minimum_approved_pct:
                status = "rejected"

            if status == "rejected":
                results.append({
                    "application_id": app_id,
                    "subcontractor_name": sub_name,
                    "schedule_item_id": item_id,
                    "item_description": item_desc,
                    "claimed_amount": round(claimed_amount, 2),
                    "approved_pct": round(approved_pct, 2),
                    "gross_approved": 0.0,
                    "total_deductions": 0.0,
                    "retention": 0.0,
                    "net_payable": 0.0,
                    "status": "rejected",
                })
                continue

            gross_approved = round(budgeted_amount * approved_pct / 100.0, 2)

            # Calculate deductions
            total_deductions = 0.0

            # 1. Deficiency deduction
            if deficiency_flag:
                total_deductions += round(gross_approved * deficiency_deduction_rate, 2)

            # 2. Material discrepancy check
            cur.execute("SELECT SUM(total_amount) as db_total FROM material_deliveries WHERE schedule_item_id = ?",
                         (item_id,))
            db_mat_row = cur.fetchone()
            db_material_total = db_mat_row["db_total"] if db_mat_row and db_mat_row["db_total"] else 0.0

            invoice_path = os.path.join(self.workspace, "invoices", f"invoice_{item_code}.csv")
            invoice_total = 0.0
            if os.path.exists(invoice_path):
                with open(invoice_path, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        invoice_total += float(row["line_total"])

                if db_material_total > 0 and abs(invoice_total - db_material_total) > material_discrepancy_tolerance * db_material_total:
                    total_deductions += round(gross_approved * material_discrepancy_penalty_rate, 2)

            # 3. Delay penalty (stoppage days)
            stoppage_days = item_stoppage_days.get(item_code, 0)
            if stoppage_days > max_allowed_stoppage:
                total_deductions += round(gross_approved * delay_penalty_rate, 2)

            total_deductions = round(total_deductions, 2)
            adjusted = round(gross_approved - total_deductions, 2)
            retention = round(adjusted * retention_rate, 2)
            net_payable = round(adjusted - retention, 2)

            results.append({
                "application_id": app_id,
                "subcontractor_name": sub_name,
                "schedule_item_id": item_id,
                "item_description": item_desc,
                "claimed_amount": round(claimed_amount, 2),
                "approved_pct": round(approved_pct, 2),
                "gross_approved": gross_approved,
                "total_deductions": total_deductions,
                "retention": retention,
                "net_payable": net_payable,
                "status": status,
            })

        conn.close()

        # Sort by application_id
        results.sort(key=lambda x: x["application_id"])

        # Compute totals
        total_gross = round(sum(r["gross_approved"] for r in results), 2)
        total_deductions = round(sum(r["total_deductions"] for r in results), 2)
        total_retention = round(sum(r["retention"] for r in results), 2)
        total_net = round(sum(r["net_payable"] for r in results), 2)

        return results, {
            "total_gross_approved": total_gross,
            "total_deductions": total_deductions,
            "total_retention": total_retention,
            "total_net_payable": total_net,
        }

    def step(
        self, action: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.

        Returns a reward based on evaluation results.

        Args:
            action: The agent's final response.

        Returns:
            reward: The reward based on task completion (between 0.0 and 1.0).
            info: Evaluation results.
        """
        gt_results, gt_totals = self._compute_ground_truth()
        eval_criteria = {}

        # --- Criterion 1: Output file exists with correct columns (10 pts) ---
        output_path = os.path.join(self.workspace, "certified_payment_schedule.csv")
        file_ok = False
        output_rows = []
        expected_cols = ["application_id", "subcontractor_name", "schedule_item_id", "item_description",
                         "claimed_amount", "approved_pct", "gross_approved", "total_deductions",
                         "retention", "net_payable", "status"]
        if os.path.exists(output_path):
            with open(output_path, "r") as f:
                reader = csv.DictReader(f)
                actual_cols = reader.fieldnames or []
                if all(c in actual_cols for c in expected_cols):
                    file_ok = True
                    output_rows = list(reader)

        eval_criteria["output_file_structure"] = {
            "passed": file_ok,
            "score": 10 if file_ok else 0,
            "max_score": 10,
            "reason": "" if file_ok else f"Missing file or columns. Expected columns: {expected_cols}"
        }

        # --- Criterion 2: Correct number of entries (15 pts) ---
        count_ok = len(output_rows) == len(gt_results)
        eval_criteria["entry_count"] = {
            "passed": count_ok,
            "score": 15 if count_ok else 0,
            "max_score": 15,
            "reason": "" if count_ok else f"Expected {len(gt_results)} entries, got {len(output_rows)}"
        }

        # Build lookup from output
        output_by_id = {}
        for r in output_rows:
            try:
                aid = int(r.get("application_id", -1))
                output_by_id[aid] = r
            except (ValueError, TypeError):
                pass

        # --- Criterion 3: Approved percentages correct (20 pts) ---
        pct_correct = 0
        pct_total = len(gt_results)
        for gt in gt_results:
            out = output_by_id.get(gt["application_id"])
            if out:
                try:
                    if abs(float(out["approved_pct"]) - gt["approved_pct"]) < 0.15:
                        pct_correct += 1
                except (ValueError, KeyError):
                    pass
        pct_score = round(20 * pct_correct / max(1, pct_total), 1)
        eval_criteria["approved_pct_accuracy"] = {
            "passed": pct_correct == pct_total,
            "score": pct_score,
            "max_score": 20,
            "reason": "" if pct_correct == pct_total else f"{pct_correct}/{pct_total} approved percentages correct"
        }

        # --- Criterion 4: Gross approved amounts correct (15 pts) ---
        gross_correct = 0
        for gt in gt_results:
            out = output_by_id.get(gt["application_id"])
            if out:
                try:
                    if abs(float(out["gross_approved"]) - gt["gross_approved"]) < 0.02:
                        gross_correct += 1
                except (ValueError, KeyError):
                    pass
        gross_score = round(15 * gross_correct / max(1, pct_total), 1)
        eval_criteria["gross_approved_accuracy"] = {
            "passed": gross_correct == pct_total,
            "score": gross_score,
            "max_score": 15,
            "reason": "" if gross_correct == pct_total else f"{gross_correct}/{pct_total} gross amounts correct"
        }

        # --- Criterion 5: Deductions correct (15 pts) ---
        ded_correct = 0
        for gt in gt_results:
            out = output_by_id.get(gt["application_id"])
            if out:
                try:
                    if abs(float(out["total_deductions"]) - gt["total_deductions"]) < 0.02:
                        ded_correct += 1
                except (ValueError, KeyError):
                    pass
        ded_score = round(15 * ded_correct / max(1, pct_total), 1)
        eval_criteria["deductions_accuracy"] = {
            "passed": ded_correct == pct_total,
            "score": ded_score,
            "max_score": 15,
            "reason": "" if ded_correct == pct_total else f"{ded_correct}/{pct_total} deduction amounts correct"
        }

        # --- Criterion 6: Retention and net payable correct (15 pts) ---
        net_correct = 0
        for gt in gt_results:
            out = output_by_id.get(gt["application_id"])
            if out:
                try:
                    ret_ok = abs(float(out["retention"]) - gt["retention"]) < 0.02
                    net_ok = abs(float(out["net_payable"]) - gt["net_payable"]) < 0.02
                    if ret_ok and net_ok:
                        net_correct += 1
                except (ValueError, KeyError):
                    pass
        net_score = round(15 * net_correct / max(1, pct_total), 1)
        eval_criteria["retention_net_payable_accuracy"] = {
            "passed": net_correct == pct_total,
            "score": net_score,
            "max_score": 15,
            "reason": "" if net_correct == pct_total else f"{net_correct}/{pct_total} retention/net correct"
        }

        # --- Criterion 7: Response contains summary totals (10 pts) ---
        totals_found = 0
        action_lower = action.lower().replace(",", "").replace("$", "")
        for key, val in gt_totals.items():
            val_str = f"{val:.2f}"
            if val_str in action_lower or val_str in action:
                totals_found += 1
        totals_score = round(10 * totals_found / 4, 1)
        eval_criteria["response_totals"] = {
            "passed": totals_found == 4,
            "score": totals_score,
            "max_score": 10,
            "reason": "" if totals_found == 4 else f"Found {totals_found}/4 summary totals in response"
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

        return total_score / max_score, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml as _yaml

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # Step 1: Read payment policy from workspace
        policy_path = os.path.join(self.workspace, "payment_policy.yaml")
        with open(policy_path, "r") as f:
            policy = _yaml.safe_load(f)

        retention_rate = policy["retention_rate"]
        deficiency_deduction_rate = policy["deficiency_deduction_rate"]
        material_discrepancy_tolerance = policy["material_discrepancy_tolerance"]
        material_discrepancy_penalty_rate = policy["material_discrepancy_penalty_rate"]
        max_allowed_stoppage = policy["max_allowed_stoppage_days"]
        delay_penalty_rate = policy["delay_penalty_rate"]
        minimum_approved_pct = policy["minimum_approved_pct"]

        # Step 2: Read supervisor logs to count stoppages per item code
        logs_dir = os.path.join(self.workspace, "logs")
        item_stoppage_days = {}
        if os.path.isdir(logs_dir):
            for log_file in sorted(glob.glob(os.path.join(logs_dir, "log_*.md"))):
                with open(log_file, "r") as f:
                    content = f.read()
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("- SI-") and "No activity" in line:
                        item_code = line.split(":")[0].replace("- ", "").strip()
                        item_stoppage_days[item_code] = item_stoppage_days.get(item_code, 0) + 1

        # Step 3: Get all pending payment applications via tool
        pending_apps = []
        page = 1
        while True:
            result = call_tool("list_payment_applications", status="pending", page=page, page_size=10)
            pending_apps.extend(result["applications"])
            if page * 10 >= result["total"]:
                break
            page += 1

        # Step 4: Process each pending application
        schedule_results = []
        for app in pending_apps:
            app_id = app["id"]
            sub_id = app["subcontractor_id"]
            item_id = app["schedule_item_id"]
            claimed_pct = app["claimed_completion_pct"]
            claimed_amount = app["claimed_amount"]

            # Get subcontractor name
            sub_info = call_tool("get_subcontractor", subcontractor_id=sub_id)
            sub_name = sub_info.get("name", "Unknown")

            # Get schedule item details
            item_info = call_tool("get_schedule_item", item_id=item_id)
            item_code = item_info["item_code"]
            item_desc = item_info["description"]
            budgeted_amount = item_info["budgeted_amount"]

            # Get inspection report
            insp = call_tool("get_inspection_report", schedule_item_id=item_id)
            verified_pct = insp.get("verified_completion_pct", 0.0)
            deficiency_flag = insp.get("deficiency_flag", 0)

            # Get material deliveries from tool
            del_result = call_tool("get_material_deliveries", schedule_item_id=item_id)
            db_material_total = sum(d["total_amount"] for d in del_result["deliveries"])

            # Read completion certificate from workspace
            cert_path = os.path.join(self.workspace, "certificates", f"cert_{app_id:04d}.json")
            certified_pct = 0.0
            supervisor_signed = False
            if os.path.exists(cert_path):
                with open(cert_path, "r") as f:
                    cert = json.load(f)
                certified_pct = cert.get("certified_completion_pct", 0.0)
                supervisor_signed = cert.get("supervisor_signed_off", False)

            # Determine approved percentage
            approved_pct = min(claimed_pct, verified_pct, certified_pct)

            # Check rejection
            status = "approved"
            if not supervisor_signed:
                status = "rejected"
            elif approved_pct < minimum_approved_pct:
                status = "rejected"

            if status == "rejected":
                schedule_results.append({
                    "application_id": app_id,
                    "subcontractor_name": sub_name,
                    "schedule_item_id": item_id,
                    "item_description": item_desc,
                    "claimed_amount": round(claimed_amount, 2),
                    "approved_pct": round(approved_pct, 2),
                    "gross_approved": 0.0,
                    "total_deductions": 0.0,
                    "retention": 0.0,
                    "net_payable": 0.0,
                    "status": "rejected",
                })
                continue

            gross_approved = round(budgeted_amount * approved_pct / 100.0, 2)

            total_deductions = 0.0

            # Deficiency deduction
            if deficiency_flag:
                total_deductions += round(gross_approved * deficiency_deduction_rate, 2)

            # Material discrepancy check
            invoice_path = os.path.join(self.workspace, "invoices", f"invoice_{item_code}.csv")
            if os.path.exists(invoice_path):
                invoice_total = 0.0
                with open(invoice_path, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        invoice_total += float(row["line_total"])
                if db_material_total > 0 and abs(invoice_total - db_material_total) > material_discrepancy_tolerance * db_material_total:
                    total_deductions += round(gross_approved * material_discrepancy_penalty_rate, 2)

            # Delay penalty
            stoppage_days = item_stoppage_days.get(item_code, 0)
            if stoppage_days > max_allowed_stoppage:
                total_deductions += round(gross_approved * delay_penalty_rate, 2)

            total_deductions = round(total_deductions, 2)
            adjusted = round(gross_approved - total_deductions, 2)
            retention = round(adjusted * retention_rate, 2)
            net_payable = round(adjusted - retention, 2)

            schedule_results.append({
                "application_id": app_id,
                "subcontractor_name": sub_name,
                "schedule_item_id": item_id,
                "item_description": item_desc,
                "claimed_amount": round(claimed_amount, 2),
                "approved_pct": round(approved_pct, 2),
                "gross_approved": gross_approved,
                "total_deductions": total_deductions,
                "retention": retention,
                "net_payable": net_payable,
                "status": status,
            })

        # Sort by application_id
        schedule_results.sort(key=lambda x: x["application_id"])

        # Step 5: Write certified_payment_schedule.csv
        output_path = os.path.join(self.workspace, "certified_payment_schedule.csv")
        fieldnames = ["application_id", "subcontractor_name", "schedule_item_id", "item_description",
                       "claimed_amount", "approved_pct", "gross_approved", "total_deductions",
                       "retention", "net_payable", "status"]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(schedule_results)

        # Step 6: Construct action string with summary totals
        total_gross = round(sum(r["gross_approved"] for r in schedule_results), 2)
        total_deductions = round(sum(r["total_deductions"] for r in schedule_results), 2)
        total_retention = round(sum(r["retention"] for r in schedule_results), 2)
        total_net = round(sum(r["net_payable"] for r in schedule_results), 2)

        action = (
            f"Certified payment schedule has been generated and saved. "
            f"Summary of all pending payment applications:\n"
            f"Total Gross Approved: ${total_gross:.2f}\n"
            f"Total Deductions: ${total_deductions:.2f}\n"
            f"Total Retention: ${total_retention:.2f}\n"
            f"Total Net Payable: ${total_net:.2f}\n"
            f"Applications processed: {len(schedule_results)} "
            f"(approved: {sum(1 for r in schedule_results if r['status'] == 'approved')}, "
            f"rejected: {sum(1 for r in schedule_results if r['status'] == 'rejected')})"
        )

        print(f"verify: {tool_call_count} tool calls made")
        return self.step(action)
