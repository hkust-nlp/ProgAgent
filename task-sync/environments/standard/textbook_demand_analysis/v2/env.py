"""
Environment for textbook availability monitoring task.
Cross-references course enrollments, library inventory, circulation data,
and reservation queues to identify shortage risks and generate procurement priorities.
"""

import json
import math
import os
import csv
import sqlite3
import glob as globmod
from typing import Tuple, Dict, List, Any

import yaml
import pandas as pd


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

    # ---- Tool Methods ----

    @tool(
        description="Lists all academic departments that have courses in the system.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_departments(self) -> List[str]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT department FROM courses ORDER BY department")
        depts = [row[0] for row in cursor.fetchall()]
        conn.close()
        return depts

    @tool(
        description="Retrieves all courses for a given department, including course ID, code, name, semester, and section.",
        parameters={
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": "Name of the department, e.g. 'Computer Science'",
                },
            },
            "required": ["department"],
        },
    )
    def get_department_courses(self, department: str) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT course_id, course_code, course_name, semester, section, instructor "
            "FROM courses WHERE department = ? ORDER BY course_id",
            (department,),
        )
        cols = ["course_id", "course_code", "course_name", "semester", "section", "instructor"]
        rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
        conn.close()
        return rows

    @tool(
        description="Retrieves the textbooks assigned to a specific course, including the requirement type (required or recommended).",
        parameters={
            "type": "object",
            "properties": {
                "course_id": {
                    "type": "integer",
                    "description": "The course ID to look up textbooks for.",
                },
            },
            "required": ["course_id"],
        },
    )
    def get_course_textbooks(self, course_id: int) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ct.textbook_id, t.title, t.isbn, ct.requirement_type "
            "FROM course_textbooks ct "
            "JOIN textbooks t ON ct.textbook_id = t.textbook_id "
            "WHERE ct.course_id = ? ORDER BY ct.textbook_id",
            (course_id,),
        )
        cols = ["textbook_id", "title", "isbn", "requirement_type"]
        rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
        conn.close()
        return rows

    @tool(
        description="Retrieves detailed information about a textbook by its ID, including title, author, ISBN, edition, publisher, retail price, and year published.",
        parameters={
            "type": "object",
            "properties": {
                "textbook_id": {
                    "type": "integer",
                    "description": "The textbook ID.",
                },
            },
            "required": ["textbook_id"],
        },
    )
    def get_textbook_info(self, textbook_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT textbook_id, title, author, isbn, edition, publisher, retail_price, year_published "
            "FROM textbooks WHERE textbook_id = ?",
            (textbook_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Textbook {textbook_id} not found"}
        cols = ["textbook_id", "title", "author", "isbn", "edition", "publisher", "retail_price", "year_published"]
        return dict(zip(cols, row))

    @tool(
        description="Retrieves the current inventory status for a textbook across all library branches. Returns total_copies and available_copies per branch.",
        parameters={
            "type": "object",
            "properties": {
                "textbook_id": {
                    "type": "integer",
                    "description": "The textbook ID to check inventory for.",
                },
            },
            "required": ["textbook_id"],
        },
    )
    def get_inventory_status(self, textbook_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT branch, total_copies, available_copies, condition, last_audit_date "
            "FROM inventory WHERE textbook_id = ? ORDER BY branch",
            (textbook_id,),
        )
        cols = ["branch", "total_copies", "available_copies", "condition", "last_audit_date"]
        branches = [dict(zip(cols, r)) for r in cursor.fetchall()]
        total = sum(b["total_copies"] for b in branches)
        available = sum(b["available_copies"] for b in branches)
        conn.close()
        return {
            "textbook_id": textbook_id,
            "total_copies": total,
            "available_copies": available,
            "branches": branches,
        }

    @tool(
        description="Retrieves circulation statistics for a textbook: total checkouts, currently checked out count, overdue count, and average loan duration in days.",
        parameters={
            "type": "object",
            "properties": {
                "textbook_id": {
                    "type": "integer",
                    "description": "The textbook ID.",
                },
            },
            "required": ["textbook_id"],
        },
    )
    def get_circulation_stats(self, textbook_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Total checkouts
        cursor.execute(
            "SELECT COUNT(*) FROM circulation WHERE textbook_id = ?",
            (textbook_id,),
        )
        total_checkouts = cursor.fetchone()[0]

        # Currently checked out (no return_date)
        cursor.execute(
            "SELECT COUNT(*) FROM circulation WHERE textbook_id = ? AND return_date IS NULL",
            (textbook_id,),
        )
        currently_out = cursor.fetchone()[0]

        # Overdue (return_date IS NULL AND due_date < today, or returned late)
        cursor.execute(
            "SELECT COUNT(*) FROM circulation WHERE textbook_id = ? "
            "AND return_date IS NULL AND due_date < date('now')",
            (textbook_id,),
        )
        overdue = cursor.fetchone()[0]

        # Average loan duration for returned books
        cursor.execute(
            "SELECT AVG(julianday(return_date) - julianday(checkout_date)) "
            "FROM circulation WHERE textbook_id = ? AND return_date IS NOT NULL",
            (textbook_id,),
        )
        avg_days = cursor.fetchone()[0]
        avg_loan_days = round(avg_days, 1) if avg_days else 0.0

        # Renewal count
        cursor.execute(
            "SELECT SUM(renewals) FROM circulation WHERE textbook_id = ?",
            (textbook_id,),
        )
        total_renewals = cursor.fetchone()[0] or 0

        conn.close()
        return {
            "textbook_id": textbook_id,
            "total_checkouts": total_checkouts,
            "currently_checked_out": currently_out,
            "overdue_count": overdue,
            "avg_loan_days": avg_loan_days,
            "total_renewals": total_renewals,
        }

    @tool(
        description="Retrieves pending reservations for a textbook, including the count of pending reservations and the queue details.",
        parameters={
            "type": "object",
            "properties": {
                "textbook_id": {
                    "type": "integer",
                    "description": "The textbook ID.",
                },
            },
            "required": ["textbook_id"],
        },
    )
    def get_pending_reservations(self, textbook_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM reservations WHERE textbook_id = ? AND status = 'pending'",
            (textbook_id,),
        )
        pending_count = cursor.fetchone()[0]

        cursor.execute(
            "SELECT reservation_id, student_id, request_date, position_in_queue, course_id "
            "FROM reservations WHERE textbook_id = ? AND status = 'pending' "
            "ORDER BY position_in_queue",
            (textbook_id,),
        )
        cols = ["reservation_id", "student_id", "request_date", "position_in_queue", "course_id"]
        queue = [dict(zip(cols, r)) for r in cursor.fetchall()]

        # Total reservations (all statuses) for context
        cursor.execute(
            "SELECT COUNT(*) FROM reservations WHERE textbook_id = ?",
            (textbook_id,),
        )
        total_reservations = cursor.fetchone()[0]

        conn.close()
        return {
            "textbook_id": textbook_id,
            "pending_count": pending_count,
            "total_reservations": total_reservations,
            "queue": queue,
        }

    @tool(
        description="Lists all textbook IDs in the system, optionally filtered by publisher.",
        parameters={
            "type": "object",
            "properties": {
                "publisher": {
                    "type": "string",
                    "description": "Optional publisher name to filter by.",
                },
            },
            "required": [],
        },
    )
    def list_textbook_ids(self, publisher: str = None) -> List[int]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if publisher:
            cursor.execute(
                "SELECT textbook_id FROM textbooks WHERE publisher = ? ORDER BY textbook_id",
                (publisher,),
            )
        else:
            cursor.execute("SELECT textbook_id FROM textbooks ORDER BY textbook_id")
        ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        return ids

    # ---- Evaluation ----

    def _compute_ground_truth(self):
        """Compute the complete ground truth procurement priority list."""
        conn = sqlite3.connect(self.db_path)

        # Load policy from workspace
        with open(os.path.join(self.workspace, "procurement_policy.yaml"), "r") as f:
            policy = yaml.safe_load(f)

        # Load budget
        with open(os.path.join(self.workspace, "budget_allocation.json"), "r") as f:
            budget_data = json.load(f)

        # Load supplier discounts
        discounts = pd.read_csv(os.path.join(self.workspace, "supplier_discounts.csv"))

        # Load enrollment data from all enrollment batch files
        enrollment_files = sorted(globmod.glob(os.path.join(self.workspace, "enrollment_batch_*.csv")))
        enrollment_records = []
        for ef in enrollment_files:
            edf = pd.read_csv(ef)
            enrollment_records.append(edf)
        if enrollment_records:
            enrollment_df = pd.concat(enrollment_records, ignore_index=True)
        else:
            enrollment_df = pd.DataFrame()

        # Build course enrollment lookup: course_id -> (enrolled + waitlisted, department)
        course_demand = {}
        course_dept = {}
        for _, row in enrollment_df.iterrows():
            cid = int(row["course_id"])
            course_demand[cid] = int(row["enrolled_students"]) + int(row["waitlisted_students"])
            course_dept[cid] = row["department"]

        # Get course-textbook mappings (required only)
        ct_df = pd.read_sql(
            "SELECT course_id, textbook_id, requirement_type FROM course_textbooks",
            conn,
        )
        required_ct = ct_df[ct_df["requirement_type"] == "required"]

        # Calculate total demand per textbook
        textbook_demand = {}
        textbook_departments = {}
        for _, row in required_ct.iterrows():
            tid = int(row["textbook_id"])
            cid = int(row["course_id"])
            if cid in course_demand:
                textbook_demand[tid] = textbook_demand.get(tid, 0) + course_demand[cid]
                if tid not in textbook_departments:
                    textbook_departments[tid] = set()
                if cid in course_dept:
                    textbook_departments[tid].add(course_dept[cid])

        # Get inventory per textbook
        inv_df = pd.read_sql(
            "SELECT textbook_id, SUM(total_copies) as total_copies, "
            "SUM(available_copies) as available_copies "
            "FROM inventory GROUP BY textbook_id",
            conn,
        )
        inventory_lookup = {}
        for _, row in inv_df.iterrows():
            inventory_lookup[int(row["textbook_id"])] = {
                "total_copies": int(row["total_copies"]),
                "available_copies": int(row["available_copies"]),
            }

        # Get circulation stats per textbook
        circ_df = pd.read_sql(
            "SELECT textbook_id, COUNT(*) as total_checkouts, "
            "SUM(CASE WHEN return_date IS NULL THEN 1 ELSE 0 END) as currently_out "
            "FROM circulation GROUP BY textbook_id",
            conn,
        )
        circ_lookup = {}
        for _, row in circ_df.iterrows():
            circ_lookup[int(row["textbook_id"])] = {
                "total_checkouts": int(row["total_checkouts"]),
                "currently_out": int(row["currently_out"]),
            }

        # Get pending reservation counts per textbook
        res_df = pd.read_sql(
            "SELECT textbook_id, COUNT(*) as pending_count "
            "FROM reservations WHERE status = 'pending' GROUP BY textbook_id",
            conn,
        )
        res_lookup = {}
        for _, row in res_df.iterrows():
            res_lookup[int(row["textbook_id"])] = int(row["pending_count"])

        # Get textbook details
        tb_df = pd.read_sql("SELECT * FROM textbooks", conn)
        tb_lookup = {}
        for _, row in tb_df.iterrows():
            tb_lookup[int(row["textbook_id"])] = row.to_dict()

        conn.close()

        # Load circulation summary files for additional overdue data
        circ_summary_files = sorted(globmod.glob(os.path.join(self.workspace, "circulation_summary_*.csv")))
        overdue_totals = {}
        for csf in circ_summary_files:
            csdf = pd.read_csv(csf)
            for _, row in csdf.iterrows():
                tid = int(row["textbook_id"])
                overdue_totals[tid] = overdue_totals.get(tid, 0) + int(row["overdue_count"])

        # Scoring weights
        weights = policy["shortage_risk_scoring"]["weights"]
        thresholds = policy["shortage_risk_scoring"]["risk_thresholds"]
        target_ratio = policy["purchase_quantity_formula"]["target_ratio"]
        min_order = policy["purchase_quantity_formula"]["minimum_order"]
        tier_scores = policy["priority_tier_scores"]

        # Compute risk scores for textbooks with demand
        results = []
        for tid, demand in textbook_demand.items():
            if demand == 0:
                continue
            inv = inventory_lookup.get(tid, {"total_copies": 0, "available_copies": 0})
            circ = circ_lookup.get(tid, {"total_checkouts": 0, "currently_out": 0})
            pending = res_lookup.get(tid, 0)
            total_copies = inv["total_copies"]

            # Demand-supply ratio component: demand / max(total_copies, 1)
            dsr = demand / max(total_copies, 1)
            dsr_norm = min(dsr / 10.0, 1.0)  # Normalize: ratio of 10 or more = 1.0

            # Reservation pressure: pending / max(total_copies, 1)
            rp = pending / max(total_copies, 1)
            rp_norm = min(rp / 5.0, 1.0)  # Normalize: 5 pending per copy = 1.0

            # Circulation intensity: currently_out / max(total_copies, 1)
            ci = circ["currently_out"] / max(total_copies, 1)
            ci_norm = min(ci, 1.0)

            # Waitlist factor: use enrollment data waitlist proportion
            # Sum waitlisted for courses requiring this textbook
            waitlist_total = 0
            enrolled_total = 0
            for _, row in required_ct[required_ct["textbook_id"] == tid].iterrows():
                cid = int(row["course_id"])
                for _, er in enrollment_df[enrollment_df["course_id"] == cid].iterrows():
                    waitlist_total += int(er["waitlisted_students"])
                    enrolled_total += int(er["enrolled_students"])
            wf = waitlist_total / max(enrolled_total, 1)
            wf_norm = min(wf, 1.0)

            # Weighted risk score
            risk_score = (
                weights["demand_supply_ratio"] * dsr_norm
                + weights["reservation_pressure"] * rp_norm
                + weights["circulation_intensity"] * ci_norm
                + weights["waitlist_factor"] * wf_norm
            )
            risk_score = round(risk_score, 4)

            # Risk classification
            if risk_score >= thresholds["critical"]:
                risk_level = "critical"
            elif risk_score >= thresholds["high"]:
                risk_level = "high"
            elif risk_score >= thresholds["medium"]:
                risk_level = "medium"
            else:
                risk_level = "low"

            # Purchase quantity
            recommended_qty = math.ceil(demand * target_ratio) - total_copies
            if recommended_qty > 0 and recommended_qty < min_order:
                recommended_qty = min_order
            elif recommended_qty <= 0:
                recommended_qty = 0

            # Cost calculation
            tb_info = tb_lookup.get(tid, {})
            retail_price = tb_info.get("retail_price", 0)

            # Apply discount
            discount_pct = 0.0
            for _, dr in discounts.iterrows():
                if dr["quantity_min"] <= recommended_qty <= dr["quantity_max"]:
                    discount_pct = dr["discount_pct"]
                    break

            unit_cost = retail_price * (1 - discount_pct / 100.0)
            total_cost = round(unit_cost * recommended_qty, 2)

            # Primary department (most courses requiring this textbook)
            depts = textbook_departments.get(tid, set())
            primary_dept = sorted(depts)[0] if depts else "Unknown"

            results.append({
                "textbook_id": tid,
                "title": tb_info.get("title", ""),
                "isbn": tb_info.get("isbn", ""),
                "department": primary_dept,
                "total_demand": demand,
                "total_copies": total_copies,
                "available_copies": inv["available_copies"],
                "pending_reservations": pending,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "priority_tier": tier_scores.get(risk_level, 1),
                "recommended_quantity": recommended_qty,
                "unit_cost": round(unit_cost, 2),
                "total_cost": total_cost,
            })

        # Sort by priority_tier desc, risk_score desc, textbook_id asc
        results.sort(key=lambda x: (-x["priority_tier"], -x["risk_score"], x["textbook_id"]))

        return results

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        ground_truth = self._compute_ground_truth()
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ---- Criterion 1: Output file exists with correct name (10 pts) ----
        output_path = os.path.join(self.workspace, "procurement_priority_list.csv")
        file_exists = os.path.isfile(output_path)
        eval_criteria["output_file_exists"] = {
            "passed": file_exists,
            "score": 10 if file_exists else 0,
            "max_score": 10,
        }
        if not file_exists:
            eval_criteria["output_file_exists"]["reason"] = "procurement_priority_list.csv not found in workspace"

        # ---- Criterion 2: Correct columns in output file (10 pts) ----
        expected_columns = [
            "textbook_id", "title", "isbn", "department", "total_demand",
            "total_copies", "available_copies", "pending_reservations",
            "risk_score", "risk_level", "priority_tier",
            "recommended_quantity", "unit_cost", "total_cost",
        ]
        columns_correct = False
        agent_df = None
        if file_exists:
            try:
                agent_df = pd.read_csv(output_path)
                agent_cols = list(agent_df.columns)
                columns_correct = agent_cols == expected_columns
            except Exception:
                pass

        eval_criteria["correct_columns"] = {
            "passed": columns_correct,
            "score": 10 if columns_correct else 0,
            "max_score": 10,
        }
        if not columns_correct:
            eval_criteria["correct_columns"]["reason"] = f"Expected columns: {expected_columns}"

        # ---- Criterion 3: Correct textbooks identified (only required, 15 pts) ----
        textbooks_with_demand = [r for r in ground_truth if r["total_demand"] > 0]
        gt_tids = set(r["textbook_id"] for r in textbooks_with_demand)
        agent_tids = set()
        if agent_df is not None and "textbook_id" in agent_df.columns:
            agent_tids = set(agent_df["textbook_id"].astype(int).tolist())

        if gt_tids:
            tid_precision = len(agent_tids & gt_tids) / max(len(agent_tids), 1)
            tid_recall = len(agent_tids & gt_tids) / len(gt_tids)
            tid_f1 = (2 * tid_precision * tid_recall / max(tid_precision + tid_recall, 1e-9))
        else:
            tid_f1 = 1.0 if len(agent_tids) == 0 else 0.0
        tid_score = round(tid_f1 * 15, 1)

        eval_criteria["correct_textbooks"] = {
            "passed": tid_f1 >= 0.99,
            "score": tid_score,
            "max_score": 15,
        }
        if tid_f1 < 0.99:
            missing = gt_tids - agent_tids
            extra = agent_tids - gt_tids
            eval_criteria["correct_textbooks"]["reason"] = (
                f"F1={tid_f1:.3f}. Missing: {sorted(missing)[:5]}, Extra: {sorted(extra)[:5]}"
            )

        # ---- Criterion 4: Correct demand values (15 pts) ----
        demand_correct_count = 0
        demand_total = 0
        if agent_df is not None and "textbook_id" in agent_df.columns and "total_demand" in agent_df.columns:
            gt_demand = {r["textbook_id"]: r["total_demand"] for r in ground_truth}
            for _, row in agent_df.iterrows():
                tid = int(row["textbook_id"])
                if tid in gt_demand:
                    demand_total += 1
                    if int(row["total_demand"]) == gt_demand[tid]:
                        demand_correct_count += 1
        demand_ratio = demand_correct_count / max(demand_total, 1)
        demand_score = round(demand_ratio * 15, 1)

        eval_criteria["correct_demand"] = {
            "passed": demand_ratio >= 0.99,
            "score": demand_score,
            "max_score": 15,
        }
        if demand_ratio < 0.99:
            eval_criteria["correct_demand"]["reason"] = f"Accuracy: {demand_correct_count}/{demand_total}"

        # ---- Criterion 5: Correct risk scores (15 pts) ----
        risk_correct_count = 0
        risk_total = 0
        if agent_df is not None and "textbook_id" in agent_df.columns and "risk_score" in agent_df.columns:
            gt_risk = {r["textbook_id"]: r["risk_score"] for r in ground_truth}
            for _, row in agent_df.iterrows():
                tid = int(row["textbook_id"])
                if tid in gt_risk:
                    risk_total += 1
                    try:
                        if abs(float(row["risk_score"]) - gt_risk[tid]) < 0.01:
                            risk_correct_count += 1
                    except (ValueError, TypeError):
                        pass
        risk_ratio = risk_correct_count / max(risk_total, 1)
        risk_score_pts = round(risk_ratio * 15, 1)

        eval_criteria["correct_risk_scores"] = {
            "passed": risk_ratio >= 0.95,
            "score": risk_score_pts,
            "max_score": 15,
        }
        if risk_ratio < 0.95:
            eval_criteria["correct_risk_scores"]["reason"] = f"Accuracy: {risk_correct_count}/{risk_total}"

        # ---- Criterion 6: Correct risk levels (10 pts) ----
        level_correct = 0
        level_total = 0
        if agent_df is not None and "textbook_id" in agent_df.columns and "risk_level" in agent_df.columns:
            gt_level = {r["textbook_id"]: r["risk_level"] for r in ground_truth}
            for _, row in agent_df.iterrows():
                tid = int(row["textbook_id"])
                if tid in gt_level:
                    level_total += 1
                    if str(row["risk_level"]).strip().lower() == gt_level[tid]:
                        level_correct += 1
        level_ratio = level_correct / max(level_total, 1)
        level_pts = round(level_ratio * 10, 1)

        eval_criteria["correct_risk_levels"] = {
            "passed": level_ratio >= 0.95,
            "score": level_pts,
            "max_score": 10,
        }
        if level_ratio < 0.95:
            eval_criteria["correct_risk_levels"]["reason"] = f"Accuracy: {level_correct}/{level_total}"

        # ---- Criterion 7: Correct recommended quantities (15 pts) ----
        qty_correct = 0
        qty_total = 0
        if agent_df is not None and "textbook_id" in agent_df.columns and "recommended_quantity" in agent_df.columns:
            gt_qty = {r["textbook_id"]: r["recommended_quantity"] for r in ground_truth}
            for _, row in agent_df.iterrows():
                tid = int(row["textbook_id"])
                if tid in gt_qty:
                    qty_total += 1
                    try:
                        if int(row["recommended_quantity"]) == gt_qty[tid]:
                            qty_correct += 1
                    except (ValueError, TypeError):
                        pass
        qty_ratio = qty_correct / max(qty_total, 1)
        qty_pts = round(qty_ratio * 15, 1)

        eval_criteria["correct_quantities"] = {
            "passed": qty_ratio >= 0.95,
            "score": qty_pts,
            "max_score": 15,
        }
        if qty_ratio < 0.95:
            eval_criteria["correct_quantities"]["reason"] = f"Accuracy: {qty_correct}/{qty_total}"

        # ---- Criterion 8: Correct sort order (10 pts) ----
        order_correct = False
        if agent_df is not None and len(agent_df) > 0 and "priority_tier" in agent_df.columns and "risk_score" in agent_df.columns:
            try:
                agent_order = list(agent_df["textbook_id"].astype(int))
                gt_order = [r["textbook_id"] for r in ground_truth if r["textbook_id"] in set(agent_order)]
                # Also check that it's sorted by priority_tier desc, risk_score desc, textbook_id asc
                is_sorted = True
                for i in range(len(agent_df) - 1):
                    t1 = agent_df.iloc[i]
                    t2 = agent_df.iloc[i + 1]
                    tier1, tier2 = int(t1["priority_tier"]), int(t2["priority_tier"])
                    rs1, rs2 = float(t1["risk_score"]), float(t2["risk_score"])
                    tid1, tid2 = int(t1["textbook_id"]), int(t2["textbook_id"])
                    if tier1 > tier2:
                        continue
                    elif tier1 == tier2:
                        if rs1 > rs2:
                            continue
                        elif abs(rs1 - rs2) < 0.001:
                            if tid1 <= tid2:
                                continue
                        is_sorted = False
                        break
                    else:
                        is_sorted = False
                        break
                order_correct = is_sorted
            except Exception:
                pass

        eval_criteria["correct_sort_order"] = {
            "passed": order_correct,
            "score": 10 if order_correct else 0,
            "max_score": 10,
        }
        if not order_correct:
            eval_criteria["correct_sort_order"]["reason"] = "Expected sort: priority_tier DESC, risk_score DESC, textbook_id ASC"

        # Sum scores
        for c in eval_criteria.values():
            total_score += c["score"]
            max_score += c["max_score"]

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
        import math as _math

        # Step 1: Read policy config from workspace
        with open(os.path.join(self.workspace, "procurement_policy.yaml"), "r") as f:
            policy = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "budget_allocation.json"), "r") as f:
            budget_data = json.load(f)

        discounts = pd.read_csv(os.path.join(self.workspace, "supplier_discounts.csv"))

        # Step 2: Read enrollment data from workspace files
        enrollment_files = sorted(globmod.glob(os.path.join(self.workspace, "enrollment_batch_*.csv")))
        enrollment_records = []
        for ef in enrollment_files:
            edf = pd.read_csv(ef)
            enrollment_records.append(edf)
        enrollment_df = pd.concat(enrollment_records, ignore_index=True)

        # Build course demand lookup
        course_demand = {}
        course_dept = {}
        for _, row in enrollment_df.iterrows():
            cid = int(row["course_id"])
            course_demand[cid] = int(row["enrolled_students"]) + int(row["waitlisted_students"])
            course_dept[cid] = row["department"]

        # Step 3: Use tools to discover departments and courses
        tool_call_count = 0

        departments = self.tools["list_departments"]()
        tool_call_count += 1

        all_course_ids = set()
        for dept in departments:
            courses = self.tools["get_department_courses"](department=dept)
            tool_call_count += 1
            for c in courses:
                all_course_ids.add(c["course_id"])

        # Step 4: For each course, get required textbooks via tools
        textbook_demand = {}
        textbook_departments = {}
        for cid in sorted(all_course_ids):
            tbooks = self.tools["get_course_textbooks"](course_id=cid)
            tool_call_count += 1
            for tb in tbooks:
                if tb["requirement_type"] == "required":
                    tid = tb["textbook_id"]
                    if cid in course_demand:
                        textbook_demand[tid] = textbook_demand.get(tid, 0) + course_demand[cid]
                        if tid not in textbook_departments:
                            textbook_departments[tid] = set()
                        if cid in course_dept:
                            textbook_departments[tid].add(course_dept[cid])

        # Step 5: For each textbook with demand, get inventory, circulation, reservations
        weights = policy["shortage_risk_scoring"]["weights"]
        thresholds = policy["shortage_risk_scoring"]["risk_thresholds"]
        target_ratio = policy["purchase_quantity_formula"]["target_ratio"]
        min_order = policy["purchase_quantity_formula"]["minimum_order"]
        tier_scores = policy["priority_tier_scores"]

        # Collect waitlist data per textbook from enrollment
        textbook_waitlist = {}
        textbook_enrolled = {}
        for cid in sorted(all_course_ids):
            for tid, demand in list(textbook_demand.items()):
                pass
        # Recompute properly using course-textbook mapping
        # Need to track which courses map to which textbooks
        course_textbook_map = {}
        for cid in sorted(all_course_ids):
            tbooks = self.tools["get_course_textbooks"](course_id=cid)
            tool_call_count += 1
            for tb in tbooks:
                if tb["requirement_type"] == "required":
                    tid = tb["textbook_id"]
                    if tid not in course_textbook_map:
                        course_textbook_map[tid] = []
                    course_textbook_map[tid].append(cid)

        # Actually, we already have the textbook_demand. Let me compute waitlist/enrolled per textbook.
        for tid in textbook_demand:
            wl_total = 0
            en_total = 0
            if tid in course_textbook_map:
                for cid in course_textbook_map[tid]:
                    subset = enrollment_df[enrollment_df["course_id"] == cid]
                    for _, er in subset.iterrows():
                        wl_total += int(er["waitlisted_students"])
                        en_total += int(er["enrolled_students"])
            textbook_waitlist[tid] = wl_total
            textbook_enrolled[tid] = en_total

        results = []
        for tid in sorted(textbook_demand.keys()):
            demand = textbook_demand[tid]
            if demand == 0:
                continue

            # Get inventory via tool
            inv = self.tools["get_inventory_status"](textbook_id=tid)
            tool_call_count += 1
            total_copies = inv["total_copies"]
            available_copies = inv["available_copies"]

            # Get circulation stats via tool
            circ = self.tools["get_circulation_stats"](textbook_id=tid)
            tool_call_count += 1

            # Get reservations via tool
            res = self.tools["get_pending_reservations"](textbook_id=tid)
            tool_call_count += 1
            pending = res["pending_count"]

            # Get textbook info for pricing
            tb_info = self.tools["get_textbook_info"](textbook_id=tid)
            tool_call_count += 1

            # Compute risk score components
            dsr = demand / max(total_copies, 1)
            dsr_norm = min(dsr / 10.0, 1.0)

            rp = pending / max(total_copies, 1)
            rp_norm = min(rp / 5.0, 1.0)

            ci = circ["currently_checked_out"] / max(total_copies, 1)
            ci_norm = min(ci, 1.0)

            wf = textbook_waitlist.get(tid, 0) / max(textbook_enrolled.get(tid, 0), 1)
            wf_norm = min(wf, 1.0)

            risk_score = (
                weights["demand_supply_ratio"] * dsr_norm
                + weights["reservation_pressure"] * rp_norm
                + weights["circulation_intensity"] * ci_norm
                + weights["waitlist_factor"] * wf_norm
            )
            risk_score = round(risk_score, 4)

            if risk_score >= thresholds["critical"]:
                risk_level = "critical"
            elif risk_score >= thresholds["high"]:
                risk_level = "high"
            elif risk_score >= thresholds["medium"]:
                risk_level = "medium"
            else:
                risk_level = "low"

            recommended_qty = _math.ceil(demand * target_ratio) - total_copies
            if recommended_qty > 0 and recommended_qty < min_order:
                recommended_qty = min_order
            elif recommended_qty <= 0:
                recommended_qty = 0

            retail_price = tb_info.get("retail_price", 0)
            discount_pct = 0.0
            for _, dr in discounts.iterrows():
                if dr["quantity_min"] <= recommended_qty <= dr["quantity_max"]:
                    discount_pct = dr["discount_pct"]
                    break

            unit_cost = retail_price * (1 - discount_pct / 100.0)
            total_cost = round(unit_cost * recommended_qty, 2)

            depts = textbook_departments.get(tid, set())
            primary_dept = sorted(depts)[0] if depts else "Unknown"

            results.append({
                "textbook_id": tid,
                "title": tb_info.get("title", ""),
                "isbn": tb_info.get("isbn", ""),
                "department": primary_dept,
                "total_demand": demand,
                "total_copies": total_copies,
                "available_copies": available_copies,
                "pending_reservations": pending,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "priority_tier": tier_scores.get(risk_level, 1),
                "recommended_quantity": recommended_qty,
                "unit_cost": round(unit_cost, 2),
                "total_cost": total_cost,
            })

        # Sort: priority_tier DESC, risk_score DESC, textbook_id ASC
        results.sort(key=lambda x: (-x["priority_tier"], -x["risk_score"], x["textbook_id"]))

        # Write output file
        output_path = os.path.join(self.workspace, "procurement_priority_list.csv")
        out_df = pd.DataFrame(results)
        columns = [
            "textbook_id", "title", "isbn", "department", "total_demand",
            "total_copies", "available_copies", "pending_reservations",
            "risk_score", "risk_level", "priority_tier",
            "recommended_quantity", "unit_cost", "total_cost",
        ]
        out_df = out_df[columns]
        out_df.to_csv(output_path, index=False)

        # Build action string summarizing findings
        action_parts = [
            f"Procurement priority analysis complete. Analyzed {len(results)} textbooks with demand from required courses.",
            f"Risk distribution: "
            f"critical={sum(1 for r in results if r['risk_level']=='critical')}, "
            f"high={sum(1 for r in results if r['risk_level']=='high')}, "
            f"medium={sum(1 for r in results if r['risk_level']=='medium')}, "
            f"low={sum(1 for r in results if r['risk_level']=='low')}.",
            f"Total recommended purchases: {sum(r['recommended_quantity'] for r in results)} copies.",
            f"Total estimated cost: ${sum(r['total_cost'] for r in results):,.2f}.",
            f"Results saved to procurement_priority_list.csv sorted by priority tier (descending), risk score (descending), and textbook ID (ascending).",
        ]
        action = " ".join(action_parts)

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need at least 15"

        return self.step(action)
