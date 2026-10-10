import sqlite3
import os
import json
import math
import glob
import re
from datetime import datetime, timedelta
from typing import Tuple, Dict, List, Any

import pandas as pd
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

    def get_assistant_tools(self) -> List[Dict[str, Any]]:
        """Get tool definitions in OpenAI function calling format."""
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

    def _get_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ==================== TOOLS ====================

    @tool(
        description="Get active subscriber counts by region for a given plan type.",
        parameters={
            "type": "object",
            "properties": {
                "plan_type": {
                    "type": "string",
                    "description": "The subscription plan type (e.g. 'basic', 'standard', 'premium', 'deluxe', 'enterprise')"
                }
            },
            "required": ["plan_type"]
        }
    )
    def get_subscriber_count(self, plan_type: str) -> dict:
        conn = self._get_db()
        rows = conn.execute(
            "SELECT region, COUNT(*) as count FROM subscribers WHERE plan_type=? AND status='active' GROUP BY region",
            (plan_type,)
        ).fetchall()
        conn.close()
        result = {r["region"]: r["count"] for r in rows}
        return {"plan_type": plan_type, "counts_by_region": result, "total_active": sum(result.values())}

    @tool(
        description="List packaging materials with pagination. Returns material ID, name, category, unit, and cost.",
        parameters={
            "type": "object",
            "properties": {
                "page": {"type": "integer", "description": "Page number (1-based)", "default": 1},
                "page_size": {"type": "integer", "description": "Items per page (max 50)", "default": 10}
            },
            "required": []
        }
    )
    def list_materials(self, page: int = 1, page_size: int = 10) -> dict:
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = self._get_db()
        total = conn.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM materials ORDER BY material_id LIMIT ? OFFSET ?",
            (page_size, offset)
        ).fetchall()
        conn.close()
        return {
            "materials": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size)
        }

    @tool(
        description="Get detailed information about a specific packaging material by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "material_id": {"type": "integer", "description": "The material ID"}
            },
            "required": ["material_id"]
        }
    )
    def get_material_info(self, material_id: int) -> dict:
        conn = self._get_db()
        row = conn.execute("SELECT * FROM materials WHERE material_id=?", (material_id,)).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Material {material_id} not found"}
        return dict(row)

    @tool(
        description="List box types with pagination. Returns box type ID, name, associated plan type, and size category.",
        parameters={
            "type": "object",
            "properties": {
                "page": {"type": "integer", "description": "Page number (1-based)", "default": 1},
                "page_size": {"type": "integer", "description": "Items per page (max 50)", "default": 10}
            },
            "required": []
        }
    )
    def list_box_types(self, page: int = 1, page_size: int = 10) -> dict:
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = self._get_db()
        total = conn.execute("SELECT COUNT(*) FROM box_types").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM box_types ORDER BY box_type_id LIMIT ? OFFSET ?",
            (page_size, offset)
        ).fetchall()
        conn.close()
        return {
            "box_types": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size)
        }

    @tool(
        description="Get the bill of materials (BOM) for a specific box type. Returns the list of materials and quantities needed to assemble one box of this type.",
        parameters={
            "type": "object",
            "properties": {
                "box_type_id": {"type": "integer", "description": "The box type ID"}
            },
            "required": ["box_type_id"]
        }
    )
    def get_box_type_bom(self, box_type_id: int) -> dict:
        conn = self._get_db()
        rows = conn.execute(
            "SELECT b.material_id, m.name as material_name, m.category, b.quantity_per_box "
            "FROM assembly_bom b JOIN materials m ON b.material_id = m.material_id "
            "WHERE b.box_type_id=?",
            (box_type_id,)
        ).fetchall()
        conn.close()
        return {"box_type_id": box_type_id, "materials": [dict(r) for r in rows]}

    @tool(
        description="Get the assembly schedule for a specific box type within a date range. Returns scheduled dates, planned quantities, and status.",
        parameters={
            "type": "object",
            "properties": {
                "box_type_id": {"type": "integer", "description": "The box type ID"},
                "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"}
            },
            "required": ["box_type_id", "start_date", "end_date"]
        }
    )
    def get_assembly_schedule(self, box_type_id: int, start_date: str, end_date: str) -> dict:
        conn = self._get_db()
        rows = conn.execute(
            "SELECT * FROM assembly_schedule WHERE box_type_id=? AND scheduled_date>=? AND scheduled_date<=? ORDER BY scheduled_date",
            (box_type_id, start_date, end_date)
        ).fetchall()
        conn.close()
        return {"box_type_id": box_type_id, "schedules": [dict(r) for r in rows]}

    @tool(
        description="Check current inventory levels for a specific material. Returns warehouse location, quantity on hand, and reserved quantity.",
        parameters={
            "type": "object",
            "properties": {
                "material_id": {"type": "integer", "description": "The material ID"}
            },
            "required": ["material_id"]
        }
    )
    def check_inventory(self, material_id: int) -> dict:
        conn = self._get_db()
        rows = conn.execute(
            "SELECT * FROM inventory WHERE material_id=?", (material_id,)
        ).fetchall()
        conn.close()
        if not rows:
            return {"material_id": material_id, "records": [], "total_on_hand": 0, "total_reserved": 0}
        records = [dict(r) for r in rows]
        return {
            "material_id": material_id,
            "records": records,
            "total_on_hand": sum(r["quantity_on_hand"] for r in records),
            "total_reserved": sum(r["reserved_quantity"] for r in records)
        }

    @tool(
        description="Find all suppliers that can provide a specific material. Returns supplier details including lead time, minimum order quantity, and price.",
        parameters={
            "type": "object",
            "properties": {
                "material_id": {"type": "integer", "description": "The material ID"}
            },
            "required": ["material_id"]
        }
    )
    def find_suppliers_for_material(self, material_id: int) -> dict:
        conn = self._get_db()
        rows = conn.execute(
            "SELECT sm.*, s.company_name, s.reliability_score, s.is_active "
            "FROM supplier_materials sm "
            "JOIN suppliers s ON sm.supplier_id = s.supplier_id "
            "WHERE sm.material_id=?",
            (material_id,)
        ).fetchall()
        conn.close()
        return {"material_id": material_id, "suppliers": [dict(r) for r in rows]}

    @tool(
        description="Get detailed information about a specific supplier by ID.",
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {"type": "integer", "description": "The supplier ID"}
            },
            "required": ["supplier_id"]
        }
    )
    def get_supplier_details(self, supplier_id: int) -> dict:
        conn = self._get_db()
        row = conn.execute("SELECT * FROM suppliers WHERE supplier_id=?", (supplier_id,)).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Supplier {supplier_id} not found"}
        return dict(row)

    # ==================== GROUND TRUTH COMPUTATION ====================

    def _compute_ground_truth(self):
        """Compute the expected purchase requisition using direct DB access and workspace files."""
        conn = self._get_db()

        # 1. Read workspace files
        # Growth forecasts
        growth_rates = {}  # (region, plan_type) -> rate
        for f in sorted(glob.glob(os.path.join(self.workspace, "growth_forecast_*.csv"))):
            df = pd.read_csv(f)
            for _, row in df.iterrows():
                growth_rates[(row["region"], row["plan_type"])] = row["growth_rate_pct"]

        # Supplier discounts
        supplier_discounts = {}  # supplier_id -> discount_pct
        for f in sorted(glob.glob(os.path.join(self.workspace, "supplier_terms_*.json"))):
            with open(f) as fh:
                data = json.load(fh)
            for entry in data:
                supplier_discounts[entry["supplier_id"]] = entry["discount_pct"]

        # Inventory adjustments
        inv_adjustments = {}  # material_id -> (damaged, expired)
        for f in sorted(glob.glob(os.path.join(self.workspace, "inventory_adjustment_*.yaml"))):
            with open(f) as fh:
                data = yaml.safe_load(fh)
            for adj in data["adjustments"]:
                inv_adjustments[adj["material_id"]] = (adj["damaged_qty"], adj["expired_qty"])

        # Procurement policy
        with open(os.path.join(self.workspace, "procurement_policy.yaml")) as fh:
            policy = yaml.safe_load(fh)

        # Quarter config
        with open(os.path.join(self.workspace, "quarter_config.json")) as fh:
            qconfig = json.load(fh)
        q_start = qconfig["next_quarter"]["start"]
        q_end = qconfig["next_quarter"]["end"]

        # Priority categories
        priority_categories = ["corrugated", "cushioning"]

        # 2. Subscriber counts and weighted growth rates
        plan_growth = {}
        for plan_type in ["basic", "standard", "premium", "deluxe", "enterprise"]:
            rows = conn.execute(
                "SELECT region, COUNT(*) as cnt FROM subscribers WHERE plan_type=? AND status='active' GROUP BY region",
                (plan_type,)
            ).fetchall()
            counts = {r["region"]: r["cnt"] for r in rows}
            total_count = sum(counts.values())
            if total_count == 0:
                plan_growth[plan_type] = 0.0
                continue
            weighted = sum(growth_rates.get((region, plan_type), 0.0) * cnt for region, cnt in counts.items())
            plan_growth[plan_type] = weighted / total_count

        # 3. Get box types
        box_types = {}
        for row in conn.execute("SELECT * FROM box_types").fetchall():
            box_types[row["box_type_id"]] = dict(row)

        # 4. Get confirmed assembly schedule for Q3
        schedules = conn.execute(
            "SELECT * FROM assembly_schedule WHERE status='confirmed' AND scheduled_date>=? AND scheduled_date<=?",
            (q_start, q_end)
        ).fetchall()

        # 5. Get all BOMs
        bom_data = {}  # box_type_id -> [(material_id, qty_per_box)]
        for row in conn.execute("SELECT * FROM assembly_bom").fetchall():
            bom_data.setdefault(row["box_type_id"], []).append((row["material_id"], row["quantity_per_box"]))

        # 6. Compute material needs
        material_need = {}  # material_id -> total_need
        material_earliest_date = {}  # material_id -> earliest need date

        for sched in schedules:
            bt_id = sched["box_type_id"]
            bt = box_types.get(bt_id)
            if not bt:
                continue
            plan = bt["plan_type"]
            growth = plan_growth.get(plan, 0.0)
            adjusted_qty = math.ceil(sched["planned_quantity"] * (1 + growth / 100))

            bom = bom_data.get(bt_id, [])
            for mid, qty_per in bom:
                material_need[mid] = material_need.get(mid, 0) + adjusted_qty * qty_per
                sched_date = sched["scheduled_date"]
                if mid not in material_earliest_date or sched_date < material_earliest_date[mid]:
                    material_earliest_date[mid] = sched_date

        # 7. Gross need with safety stock
        safety_pct = policy["safety_stock_percentage"]
        gross_need = {}
        for mid, need in material_need.items():
            gross_need[mid] = math.ceil(need * (1 + safety_pct / 100))

        # 8. Effective inventory
        materials_info = {}
        for row in conn.execute("SELECT * FROM materials").fetchall():
            materials_info[row["material_id"]] = dict(row)

        effective_inv = {}
        for mid in gross_need:
            inv_rows = conn.execute("SELECT * FROM inventory WHERE material_id=?", (mid,)).fetchall()
            on_hand = sum(r["quantity_on_hand"] for r in inv_rows)
            reserved = sum(r["reserved_quantity"] for r in inv_rows)
            damaged, expired = inv_adjustments.get(mid, (0, 0))
            effective_inv[mid] = max(0, on_hand - reserved - damaged - expired)

        # 9. Net need and purchase decisions
        requisition = []
        min_reliability = policy["supplier_selection"]["min_reliability_score"]

        for mid in sorted(gross_need.keys()):
            net = gross_need[mid] - effective_inv.get(mid, 0)
            if net <= 0:
                continue

            mat = materials_info[mid]

            # Find best supplier
            sup_rows = conn.execute(
                "SELECT sm.*, s.company_name, s.reliability_score, s.is_active "
                "FROM supplier_materials sm JOIN suppliers s ON sm.supplier_id=s.supplier_id "
                "WHERE sm.material_id=?", (mid,)
            ).fetchall()

            candidates = []
            for sr in sup_rows:
                if sr["is_active"] != 1 or sr["reliability_score"] < min_reliability:
                    continue
                disc = supplier_discounts.get(sr["supplier_id"], 0.0)
                eff_cost = round(sr["price_per_unit"] * (1 - disc / 100), 2)
                candidates.append({
                    "supplier_id": sr["supplier_id"],
                    "company_name": sr["company_name"],
                    "lead_time_days": sr["lead_time_days"],
                    "min_order_qty": sr["min_order_qty"],
                    "price_per_unit": sr["price_per_unit"],
                    "discount_pct": disc,
                    "effective_cost": eff_cost,
                })

            if not candidates:
                continue

            # Sort: lowest effective_cost, then shortest lead_time, then lowest supplier_id
            candidates.sort(key=lambda x: (x["effective_cost"], x["lead_time_days"], x["supplier_id"]))
            best = candidates[0]

            # Order quantity (round up to MOQ)
            moq = best["min_order_qty"]
            order_qty = math.ceil(net / moq) * moq

            # Priority and buffer
            is_priority = mat["category"] in priority_categories
            buffer = policy["priority_buffer_days"] if is_priority else policy["standard_buffer_days"]

            # Dates
            earliest_date = datetime.strptime(material_earliest_date[mid], "%Y-%m-%d")
            lead_time = best["lead_time_days"]
            order_date = earliest_date - timedelta(days=lead_time + buffer)
            delivery_date = order_date + timedelta(days=lead_time)

            unit_cost = best["effective_cost"]
            total_cost = round(order_qty * unit_cost, 2)

            requisition.append({
                "material_id": mid,
                "material_name": mat["name"],
                "supplier_id": best["supplier_id"],
                "supplier_name": best["company_name"],
                "order_quantity": order_qty,
                "unit_cost": unit_cost,
                "total_cost": total_cost,
                "order_date": order_date.strftime("%Y-%m-%d"),
                "expected_delivery_date": delivery_date.strftime("%Y-%m-%d"),
            })

        # Sort by order_date, then material_id
        requisition.sort(key=lambda x: (x["order_date"], x["material_id"]))

        conn.close()

        # Summary stats
        grand_total = round(sum(r["total_cost"] for r in requisition), 2)
        dates = [r["order_date"] for r in requisition]
        summary = {
            "total_materials": len(requisition),
            "grand_total_cost": grand_total,
            "earliest_order_date": min(dates) if dates else "",
            "latest_order_date": max(dates) if dates else "",
        }

        return requisition, summary

    # ==================== STEP ====================

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        expected_req, expected_summary = self._compute_ground_truth()

        eval_criteria = {}
        max_scores = {
            "file_exists": 10,
            "correct_columns": 10,
            "correct_materials": 20,
            "correct_quantities": 20,
            "correct_suppliers": 15,
            "correct_dates": 15,
            "summary_accuracy": 10,
        }

        # 1. File existence (10 pts)
        csv_path = os.path.join(self.workspace, "purchase_requisition.csv")
        file_exists = os.path.exists(csv_path)
        eval_criteria["file_exists"] = {
            "passed": file_exists, "score": 10 if file_exists else 0, "max_score": 10,
            "reason": "" if file_exists else "purchase_requisition.csv not found"
        }

        if not file_exists:
            for c in ["correct_columns", "correct_materials", "correct_quantities", "correct_suppliers", "correct_dates", "summary_accuracy"]:
                eval_criteria[c] = {"passed": False, "score": 0, "max_score": max_scores[c], "reason": "CSV not found"}
            total = sum(c["score"] for c in eval_criteria.values())
            max_total = sum(c["max_score"] for c in eval_criteria.values())
            return total / max_total, {"eval_criteria": eval_criteria, "total_score": total, "max_score": max_total}

        # Read agent's CSV
        try:
            agent_df = pd.read_csv(csv_path)
        except Exception as e:
            eval_criteria["correct_columns"] = {"passed": False, "score": 0, "max_score": 10, "reason": f"CSV read error: {e}"}
            for c in ["correct_materials", "correct_quantities", "correct_suppliers", "correct_dates", "summary_accuracy"]:
                eval_criteria[c] = {"passed": False, "score": 0, "max_score": max_scores[c], "reason": f"CSV read error: {e}"}
            total = sum(c["score"] for c in eval_criteria.values())
            max_total = sum(c["max_score"] for c in eval_criteria.values())
            return total / max_total, {"eval_criteria": eval_criteria, "total_score": total, "max_score": max_total}

        # 2. Correct columns (10 pts)
        expected_cols = ["material_id", "material_name", "supplier_id", "supplier_name",
                         "order_quantity", "unit_cost", "total_cost", "order_date", "expected_delivery_date"]
        has_cols = all(c in agent_df.columns for c in expected_cols)
        eval_criteria["correct_columns"] = {
            "passed": has_cols, "score": 10 if has_cols else 0, "max_score": 10,
            "reason": "" if has_cols else f"Missing columns: {set(expected_cols) - set(agent_df.columns)}"
        }

        # 3. Correct materials (20 pts)
        expected_mids = set(r["material_id"] for r in expected_req)
        agent_mids = set()
        if "material_id" in agent_df.columns:
            agent_mids = set(agent_df["material_id"].astype(int).tolist())

        correct_mids = expected_mids & agent_mids
        if expected_mids:
            precision = len(correct_mids) / len(agent_mids) if agent_mids else 0
            recall = len(correct_mids) / len(expected_mids)
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            mat_score = round(20 * f1)
        else:
            mat_score = 20 if len(agent_mids) == 0 else 0
        eval_criteria["correct_materials"] = {
            "passed": mat_score == 20, "score": mat_score, "max_score": 20,
            "reason": "" if mat_score == 20 else f"Expected {len(expected_mids)} materials, got {len(agent_mids)}, overlap {len(correct_mids)}"
        }

        # Build lookups for remaining checks
        expected_by_mid = {r["material_id"]: r for r in expected_req}
        agent_by_mid = {}
        if "material_id" in agent_df.columns:
            for _, row in agent_df.iterrows():
                agent_by_mid[int(row["material_id"])] = row

        common = expected_mids & agent_mids

        # 4. Correct quantities (20 pts)
        qty_correct = 0
        for mid in common:
            if "order_quantity" in agent_df.columns:
                try:
                    if int(agent_by_mid[mid]["order_quantity"]) == expected_by_mid[mid]["order_quantity"]:
                        qty_correct += 1
                except Exception:
                    pass
        qty_score = round(20 * qty_correct / len(expected_mids)) if expected_mids else 20
        eval_criteria["correct_quantities"] = {
            "passed": qty_score == 20, "score": qty_score, "max_score": 20,
            "reason": "" if qty_score == 20 else f"{qty_correct}/{len(expected_mids)} quantities correct"
        }

        # 5. Correct suppliers (15 pts)
        sup_correct = 0
        for mid in common:
            if "supplier_id" in agent_df.columns:
                try:
                    if int(agent_by_mid[mid]["supplier_id"]) == expected_by_mid[mid]["supplier_id"]:
                        sup_correct += 1
                except Exception:
                    pass
        sup_score = round(15 * sup_correct / len(expected_mids)) if expected_mids else 15
        eval_criteria["correct_suppliers"] = {
            "passed": sup_score == 15, "score": sup_score, "max_score": 15,
            "reason": "" if sup_score == 15 else f"{sup_correct}/{len(expected_mids)} suppliers correct"
        }

        # 6. Correct dates (15 pts)
        date_correct = 0
        for mid in common:
            if "order_date" in agent_df.columns:
                try:
                    if str(agent_by_mid[mid]["order_date"]).strip() == expected_by_mid[mid]["order_date"]:
                        date_correct += 1
                except Exception:
                    pass
        date_score = round(15 * date_correct / len(expected_mids)) if expected_mids else 15
        eval_criteria["correct_dates"] = {
            "passed": date_score == 15, "score": date_score, "max_score": 15,
            "reason": "" if date_score == 15 else f"{date_correct}/{len(expected_mids)} dates correct"
        }

        # 7. Summary accuracy (10 pts)
        summary_score = 0
        if f"Total materials to order: {expected_summary['total_materials']}" in action:
            summary_score += 3
        expected_cost_str = f"${expected_summary['grand_total_cost']:.2f}"
        if expected_cost_str in action:
            summary_score += 3
        if expected_summary["earliest_order_date"] in action:
            summary_score += 2
        if expected_summary["latest_order_date"] in action:
            summary_score += 2
        eval_criteria["summary_accuracy"] = {
            "passed": summary_score == 10, "score": summary_score, "max_score": 10,
            "reason": "" if summary_score == 10 else "Some summary fields missing or incorrect"
        }

        total = sum(c["score"] for c in eval_criteria.values())
        max_total = sum(c["max_score"] for c in eval_criteria.values())
        return total / max_total, {"eval_criteria": eval_criteria, "total_score": total, "max_score": max_total}

    # ==================== VERIFY ====================

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """Solve the task using only tools and workspace files (no direct DB queries)."""
        tool_call_count = 0

        # 1. Read workspace files
        # Growth forecasts
        growth_rates = {}  # (region, plan_type) -> rate
        for f in sorted(glob.glob(os.path.join(self.workspace, "growth_forecast_*.csv"))):
            df = pd.read_csv(f)
            for _, row in df.iterrows():
                growth_rates[(row["region"], row["plan_type"])] = row["growth_rate_pct"]

        # Supplier discounts
        supplier_discounts = {}  # supplier_id -> discount_pct
        for f in sorted(glob.glob(os.path.join(self.workspace, "supplier_terms_*.json"))):
            with open(f) as fh:
                data = json.load(fh)
            for entry in data:
                supplier_discounts[entry["supplier_id"]] = entry["discount_pct"]

        # Inventory adjustments
        inv_adjustments = {}  # material_id -> (damaged, expired)
        for f in sorted(glob.glob(os.path.join(self.workspace, "inventory_adjustment_*.yaml"))):
            with open(f) as fh:
                data = yaml.safe_load(fh)
            for adj in data["adjustments"]:
                inv_adjustments[adj["material_id"]] = (adj["damaged_qty"], adj["expired_qty"])

        # Procurement policy
        with open(os.path.join(self.workspace, "procurement_policy.yaml")) as fh:
            policy = yaml.safe_load(fh)

        # Quarter config
        with open(os.path.join(self.workspace, "quarter_config.json")) as fh:
            qconfig = json.load(fh)
        q_start = qconfig["next_quarter"]["start"]
        q_end = qconfig["next_quarter"]["end"]

        # Priority categories (parse from material_priority_rules.md)
        priority_categories = ["corrugated", "cushioning"]

        safety_pct = policy["safety_stock_percentage"]
        min_reliability = policy["supplier_selection"]["min_reliability_score"]

        # 2. Get subscriber counts per plan type
        plan_types = ["basic", "standard", "premium", "deluxe", "enterprise"]
        plan_counts = {}  # plan_type -> {region: count}
        for pt in plan_types:
            result = self.tools["get_subscriber_count"](plan_type=pt)
            tool_call_count += 1
            plan_counts[pt] = result["counts_by_region"]

        # 3. Compute weighted growth rates
        plan_growth = {}
        for pt in plan_types:
            counts = plan_counts[pt]
            total_count = sum(counts.values())
            if total_count == 0:
                plan_growth[pt] = 0.0
                continue
            weighted = sum(growth_rates.get((region, pt), 0.0) * cnt for region, cnt in counts.items())
            plan_growth[pt] = weighted / total_count

        # 4. Get all box types (paginate)
        all_box_types = []
        page = 1
        while True:
            result = self.tools["list_box_types"](page=page, page_size=50)
            tool_call_count += 1
            all_box_types.extend(result["box_types"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 5. Get assembly schedules for each box type
        box_schedules = {}  # box_type_id -> list of confirmed schedules
        for bt in all_box_types:
            bt_id = bt["box_type_id"]
            result = self.tools["get_assembly_schedule"](box_type_id=bt_id, start_date=q_start, end_date=q_end)
            tool_call_count += 1
            confirmed = [s for s in result["schedules"] if s["status"] == "confirmed"]
            if confirmed:
                box_schedules[bt_id] = confirmed

        # 6. Get BOM for box types with confirmed assemblies
        box_bom = {}  # box_type_id -> list of {material_id, qty_per_box, ...}
        for bt_id in box_schedules:
            result = self.tools["get_box_type_bom"](box_type_id=bt_id)
            tool_call_count += 1
            box_bom[bt_id] = result["materials"]

        # Build box_type lookup for plan_type
        bt_lookup = {bt["box_type_id"]: bt for bt in all_box_types}

        # 7. Compute adjusted quantities and aggregate material needs
        material_need = {}  # material_id -> total_need
        material_earliest_date = {}  # material_id -> earliest scheduled_date
        material_names = {}  # material_id -> name (from BOM)
        material_categories = {}  # material_id -> category (from BOM)

        for bt_id, confirmed_scheds in box_schedules.items():
            bt = bt_lookup[bt_id]
            plan = bt["plan_type"]
            growth = plan_growth.get(plan, 0.0)
            bom = box_bom.get(bt_id, [])

            for sched in confirmed_scheds:
                adjusted_qty = math.ceil(sched["planned_quantity"] * (1 + growth / 100))
                for mat in bom:
                    mid = mat["material_id"]
                    qty_per = mat["quantity_per_box"]
                    material_need[mid] = material_need.get(mid, 0) + adjusted_qty * qty_per
                    material_names[mid] = mat["material_name"]
                    material_categories[mid] = mat["category"]
                    sched_date = sched["scheduled_date"]
                    if mid not in material_earliest_date or sched_date < material_earliest_date[mid]:
                        material_earliest_date[mid] = sched_date

        # 8. Compute gross need with safety stock
        gross_need = {}
        for mid, need in material_need.items():
            gross_need[mid] = math.ceil(need * (1 + safety_pct / 100))

        # 9. For each material, check inventory via tool
        effective_inv = {}
        for mid in sorted(gross_need.keys()):
            result = self.tools["check_inventory"](material_id=mid)
            tool_call_count += 1
            on_hand = result["total_on_hand"]
            reserved = result["total_reserved"]
            damaged, expired = inv_adjustments.get(mid, (0, 0))
            effective_inv[mid] = max(0, on_hand - reserved - damaged - expired)

        # 10. Compute net need
        requisition = []
        for mid in sorted(gross_need.keys()):
            net = gross_need[mid] - effective_inv.get(mid, 0)
            if net <= 0:
                continue

            # 11. Find suppliers via tool
            result = self.tools["find_suppliers_for_material"](material_id=mid)
            tool_call_count += 1

            candidates = []
            for sr in result["suppliers"]:
                if sr["is_active"] != 1 or sr["reliability_score"] < min_reliability:
                    continue
                disc = supplier_discounts.get(sr["supplier_id"], 0.0)
                eff_cost = round(sr["price_per_unit"] * (1 - disc / 100), 2)
                candidates.append({
                    "supplier_id": sr["supplier_id"],
                    "company_name": sr["company_name"],
                    "lead_time_days": sr["lead_time_days"],
                    "min_order_qty": sr["min_order_qty"],
                    "price_per_unit": sr["price_per_unit"],
                    "discount_pct": disc,
                    "effective_cost": eff_cost,
                })

            if not candidates:
                continue

            # Sort: lowest effective_cost, then shortest lead_time, then lowest supplier_id
            candidates.sort(key=lambda x: (x["effective_cost"], x["lead_time_days"], x["supplier_id"]))
            best = candidates[0]

            # 12. Order quantity (round up to MOQ)
            moq = best["min_order_qty"]
            order_qty = math.ceil(net / moq) * moq

            # 13. Priority and buffer
            mat_cat = material_categories[mid]
            is_priority = mat_cat in priority_categories
            buffer = policy["priority_buffer_days"] if is_priority else policy["standard_buffer_days"]

            # 14. Dates
            earliest_date = datetime.strptime(material_earliest_date[mid], "%Y-%m-%d")
            lead_time = best["lead_time_days"]
            order_date = earliest_date - timedelta(days=lead_time + buffer)
            delivery_date = order_date + timedelta(days=lead_time)

            unit_cost = best["effective_cost"]
            total_cost = round(order_qty * unit_cost, 2)

            requisition.append({
                "material_id": mid,
                "material_name": material_names[mid],
                "supplier_id": best["supplier_id"],
                "supplier_name": best["company_name"],
                "order_quantity": order_qty,
                "unit_cost": unit_cost,
                "total_cost": total_cost,
                "order_date": order_date.strftime("%Y-%m-%d"),
                "expected_delivery_date": delivery_date.strftime("%Y-%m-%d"),
            })

        # 15. Sort and write CSV
        requisition.sort(key=lambda x: (x["order_date"], x["material_id"]))

        req_df = pd.DataFrame(requisition)
        csv_path = os.path.join(self.workspace, "purchase_requisition.csv")
        if len(requisition) > 0:
            req_df.to_csv(csv_path, index=False)
        else:
            # Write empty CSV with headers
            pd.DataFrame(columns=["material_id", "material_name", "supplier_id", "supplier_name",
                                   "order_quantity", "unit_cost", "total_cost", "order_date",
                                   "expected_delivery_date"]).to_csv(csv_path, index=False)

        # 16. Build action string
        grand_total = round(sum(r["total_cost"] for r in requisition), 2)
        dates = [r["order_date"] for r in requisition]
        earliest_order = min(dates) if dates else "N/A"
        latest_order = max(dates) if dates else "N/A"

        action = (
            f"Total materials to order: {len(requisition)}\n"
            f"Grand total cost: ${grand_total:.2f}\n"
            f"Earliest order date: {earliest_order}\n"
            f"Latest order date: {latest_order}"
        )

        # Sanity check: verify enough tool calls were made
        assert tool_call_count >= 15, f"Expected at least 15 tool calls, got {tool_call_count}"

        # 17. Call step
        return self.step(action)
