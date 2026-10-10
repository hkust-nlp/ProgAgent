"""
Environment for Perishable Ingredient Ordering Optimization task.
"""

import csv
import glob
import json
import math
import os
import sqlite3
from datetime import datetime, timedelta
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

    # ── Helper ───────────────────────────────────────────────────────────

    def _query(self, sql, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── Tools ────────────────────────────────────────────────────────────

    @tool(
        description="List stores with pagination. Returns store id, name, city, and state.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of stores per page (max 20).",
                },
            },
            "required": ["page"],
        },
    )
    def list_stores(self, page: int, page_size: int = 10):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        total = self._query("SELECT COUNT(*) as cnt FROM stores")[0]["cnt"]
        rows = self._query(
            "SELECT store_id, name, city, state FROM stores ORDER BY store_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        return {
            "stores": rows,
            "page": page,
            "page_size": page_size,
            "total_stores": total,
            "total_pages": math.ceil(total / page_size),
        }

    @tool(
        description="List ingredients with optional category filter and pagination.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number per page (max 20).",
                },
                "category": {
                    "type": "string",
                    "description": "Optional filter by category (dairy, produce, meat, seafood, bakery, deli).",
                },
            },
            "required": ["page"],
        },
    )
    def list_ingredients(self, page: int, page_size: int = 10, category: str = None):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        if category:
            total = self._query(
                "SELECT COUNT(*) as cnt FROM ingredients WHERE category = ?", (category,)
            )[0]["cnt"]
            rows = self._query(
                "SELECT ingredient_id, name, category, unit, base_price FROM ingredients WHERE category = ? ORDER BY ingredient_id LIMIT ? OFFSET ?",
                (category, page_size, offset),
            )
        else:
            total = self._query("SELECT COUNT(*) as cnt FROM ingredients")[0]["cnt"]
            rows = self._query(
                "SELECT ingredient_id, name, category, unit, base_price FROM ingredients ORDER BY ingredient_id LIMIT ? OFFSET ?",
                (page_size, offset),
            )
        return {
            "ingredients": rows,
            "page": page,
            "page_size": page_size,
            "total_ingredients": total,
            "total_pages": math.ceil(total / page_size),
        }

    @tool(
        description="Get aggregated daily sales for a specific store within a date range. Returns per-ingredient totals and daily average.",
        parameters={
            "type": "object",
            "properties": {
                "store_id": {
                    "type": "integer",
                    "description": "The store ID to query.",
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date inclusive (YYYY-MM-DD).",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date inclusive (YYYY-MM-DD).",
                },
            },
            "required": ["store_id", "date_from", "date_to"],
        },
    )
    def get_sales_summary(self, store_id: int, date_from: str, date_to: str):
        rows = self._query(
            """
            SELECT ingredient_id,
                   SUM(qty_sold) as total_sold,
                   COUNT(DISTINCT sale_date) as days_with_sales,
                   ROUND(SUM(qty_sold) / COUNT(DISTINCT sale_date), 2) as avg_daily_qty
            FROM daily_sales
            WHERE store_id = ? AND sale_date >= ? AND sale_date <= ?
            GROUP BY ingredient_id
            ORDER BY ingredient_id
            """,
            (store_id, date_from, date_to),
        )
        return {
            "store_id": store_id,
            "date_from": date_from,
            "date_to": date_to,
            "sales": rows,
        }

    @tool(
        description="Get current inventory levels for a specific store. Returns all ingredients stocked at that location.",
        parameters={
            "type": "object",
            "properties": {
                "store_id": {
                    "type": "integer",
                    "description": "The store ID to query.",
                },
            },
            "required": ["store_id"],
        },
    )
    def get_current_inventory(self, store_id: int):
        rows = self._query(
            "SELECT ingredient_id, current_qty, last_restock_date FROM inventory WHERE store_id = ? ORDER BY ingredient_id",
            (store_id,),
        )
        return {"store_id": store_id, "inventory": rows}

    @tool(
        description="Get supplier options for a specific ingredient. Returns all suppliers that carry this ingredient with pricing and pack size.",
        parameters={
            "type": "object",
            "properties": {
                "ingredient_id": {
                    "type": "integer",
                    "description": "The ingredient ID to query.",
                },
            },
            "required": ["ingredient_id"],
        },
    )
    def get_supplier_options(self, ingredient_id: int):
        rows = self._query(
            """
            SELECT sc.supplier_id, s.name as supplier_name, sc.unit_cost, sc.pack_size, sc.is_available
            FROM supplier_catalog sc
            JOIN suppliers s ON sc.supplier_id = s.supplier_id
            WHERE sc.ingredient_id = ? AND sc.is_available = 1
            ORDER BY sc.unit_cost ASC
            """,
            (ingredient_id,),
        )
        return {"ingredient_id": ingredient_id, "suppliers": rows}

    @tool(
        description="Get waste log data for a specific store. Returns weekly waste quantities per ingredient.",
        parameters={
            "type": "object",
            "properties": {
                "store_id": {
                    "type": "integer",
                    "description": "The store ID to query.",
                },
            },
            "required": ["store_id"],
        },
    )
    def get_waste_data(self, store_id: int):
        rows = self._query(
            """
            SELECT ingredient_id,
                   SUM(qty_wasted) as total_wasted,
                   COUNT(DISTINCT week_start) as weeks_recorded,
                   ROUND(AVG(qty_wasted), 2) as avg_weekly_waste
            FROM waste_logs
            WHERE store_id = ?
            GROUP BY ingredient_id
            ORDER BY ingredient_id
            """,
            (store_id,),
        )
        return {"store_id": store_id, "waste": rows}

    @tool(
        description="Get details for a specific supplier including lead time and minimum order value.",
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "integer",
                    "description": "The supplier ID to query.",
                },
            },
            "required": ["supplier_id"],
        },
    )
    def get_supplier_details(self, supplier_id: int):
        rows = self._query(
            "SELECT * FROM suppliers WHERE supplier_id = ?", (supplier_id,)
        )
        if rows:
            return rows[0]
        return {"error": f"Supplier {supplier_id} not found"}

    # ── Evaluation ───────────────────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute the expected purchase orders using the same logic the agent should follow."""
        # Load ordering policy
        policy_path = os.path.join(self.workspace, "ordering_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)

        safety_stock_days = policy["safety_stock_days"]
        waste_reduction_factor = policy["waste_reduction_factor"]
        priority_thresholds = policy["priority_thresholds"]

        # Load all store configs from workspace
        store_configs = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "store_config_zone_*.json"))):
            with open(fpath) as f:
                for sc in json.load(f):
                    store_configs[sc["store_id"]] = sc

        # Load all ingredient specs from workspace
        ingredient_specs = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "ingredient_specs_batch_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ingredient_specs[int(row["ingredient_id"])] = {
                        "shelf_life_days": int(row["shelf_life_days"]),
                        "storage_temp_c": float(row["storage_temp_c"]),
                        "waste_threshold_pct": float(row["waste_threshold_pct"]),
                        "reorder_multiplier": float(row["reorder_multiplier"]),
                    }

        # Load supplier ratings from workspace
        supplier_ratings = {}
        ratings_path = os.path.join(self.workspace, "supplier_ratings.csv")
        with open(ratings_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                supplier_ratings[int(row["supplier_id"])] = float(row["reliability_score"])

        # Get reference date (max sale_date + 1)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT MAX(sale_date) FROM daily_sales")
        max_date_str = c.fetchone()[0]
        reference_date = datetime.strptime(max_date_str, "%Y-%m-%d") + timedelta(days=1)

        # Get all stores
        c.execute("SELECT store_id, name FROM stores ORDER BY store_id")
        stores = c.fetchall()

        # Get ingredient names
        c.execute("SELECT ingredient_id, name, category FROM ingredients")
        ing_info = {row[0]: {"name": row[1], "category": row[2]} for row in c.fetchall()}

        WEEKDAY_MAP = {
            "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
            "Friday": 4, "Saturday": 5, "Sunday": 6,
        }

        orders = []
        waste_report = []

        for store_id, store_name in stores:
            if store_id not in store_configs:
                continue

            sc = store_configs[store_id]
            delivery_days = sc["delivery_days"]
            delivery_day_nums = sorted([WEEKDAY_MAP[d] for d in delivery_days])

            # Compute days until next delivery
            ref_weekday = reference_date.weekday()
            days_until = None
            for dd in delivery_day_nums:
                diff = (dd - ref_weekday) % 7
                if diff == 0:
                    diff = 7  # same day means next week
                if days_until is None or diff < days_until:
                    days_until = diff
            if days_until is None:
                days_until = 7

            # Get sales data (last 14 days)
            date_from = (reference_date - timedelta(days=14)).strftime("%Y-%m-%d")
            date_to = (reference_date - timedelta(days=1)).strftime("%Y-%m-%d")
            c.execute(
                """
                SELECT ingredient_id,
                       SUM(qty_sold) as total_sold,
                       COUNT(DISTINCT sale_date) as days_with_sales
                FROM daily_sales
                WHERE store_id = ? AND sale_date >= ? AND sale_date <= ?
                GROUP BY ingredient_id
                """,
                (store_id, date_from, date_to),
            )
            sales_data = {row[0]: {"total_sold": row[1], "days_with_sales": row[2]} for row in c.fetchall()}

            # Get inventory
            c.execute(
                "SELECT ingredient_id, current_qty FROM inventory WHERE store_id = ?",
                (store_id,),
            )
            inventory = {row[0]: row[1] for row in c.fetchall()}

            # Get waste data
            c.execute(
                """
                SELECT ingredient_id, SUM(qty_wasted) as total_wasted
                FROM waste_logs WHERE store_id = ?
                GROUP BY ingredient_id
                """,
                (store_id,),
            )
            waste_data = {row[0]: row[1] for row in c.fetchall()}

            # Get all ingredient IDs this store has in inventory or sales
            all_ings = set(sales_data.keys()) | set(inventory.keys())

            for iid in sorted(all_ings):
                if iid not in ingredient_specs:
                    continue

                specs = ingredient_specs[iid]
                reorder_mult = specs["reorder_multiplier"]
                waste_threshold = specs["waste_threshold_pct"]

                # Avg daily demand
                if iid in sales_data:
                    sd = sales_data[iid]
                    avg_daily = round(sd["total_sold"] / sd["days_with_sales"], 2)
                else:
                    avg_daily = 0.0

                if avg_daily <= 0:
                    continue

                current_qty = inventory.get(iid, 0.0)

                # Calculate order qty
                forecast = avg_daily * days_until
                safety = safety_stock_days * avg_daily
                base_qty = forecast - current_qty + safety
                base_qty = base_qty * reorder_mult

                # Waste adjustment
                total_sold_all = sales_data.get(iid, {}).get("total_sold", 0)
                total_wasted = waste_data.get(iid, 0)
                if total_sold_all + total_wasted > 0:
                    waste_pct = total_wasted / (total_sold_all + total_wasted)
                else:
                    waste_pct = 0.0

                waste_adjusted = False
                original_qty = base_qty
                if waste_pct > waste_threshold:
                    base_qty = base_qty * (1 - waste_reduction_factor)
                    waste_adjusted = True

                if base_qty <= 0:
                    if waste_adjusted:
                        waste_report.append({
                            "store_id": store_id,
                            "store_name": store_name,
                            "ingredient_id": iid,
                            "ingredient_name": ing_info[iid]["name"],
                            "waste_pct": round(waste_pct, 4),
                            "waste_threshold_pct": waste_threshold,
                            "adjustment_applied": True,
                            "original_qty": round(original_qty, 2),
                            "adjusted_qty": round(base_qty, 2),
                            "order_eliminated": True,
                        })
                    continue

                # Find best supplier
                c.execute(
                    """
                    SELECT sc.supplier_id, s.name, sc.unit_cost, sc.pack_size
                    FROM supplier_catalog sc
                    JOIN suppliers s ON sc.supplier_id = s.supplier_id
                    WHERE sc.ingredient_id = ? AND sc.is_available = 1
                    ORDER BY sc.unit_cost ASC
                    """,
                    (iid,),
                )
                supplier_options = c.fetchall()
                if not supplier_options:
                    continue

                # Pick cheapest; tie-break by reliability
                best_cost = supplier_options[0][2]
                candidates = [s for s in supplier_options if s[2] == best_cost]
                if len(candidates) > 1:
                    best = max(candidates, key=lambda s: supplier_ratings.get(s[0], 0.0))
                else:
                    best = candidates[0]

                sup_id, sup_name, unit_cost, pack_size = best

                # Round up to pack size
                order_qty = math.ceil(base_qty / pack_size) * pack_size
                total_cost = round(order_qty * unit_cost, 2)

                # Priority
                if avg_daily > 0:
                    days_supply = current_qty / avg_daily
                else:
                    days_supply = float("inf")

                if days_supply < priority_thresholds["critical"]:
                    priority = "critical"
                elif days_supply < priority_thresholds["high"]:
                    priority = "high"
                elif days_supply < priority_thresholds["medium"]:
                    priority = "medium"
                else:
                    priority = "low"

                orders.append({
                    "store_id": store_id,
                    "store_name": store_name,
                    "ingredient_id": iid,
                    "ingredient_name": ing_info[iid]["name"],
                    "supplier_id": sup_id,
                    "supplier_name": sup_name,
                    "recommended_qty": order_qty,
                    "unit_cost": unit_cost,
                    "total_cost": total_cost,
                    "priority": priority,
                })

                if waste_adjusted:
                    waste_report.append({
                        "store_id": store_id,
                        "store_name": store_name,
                        "ingredient_id": iid,
                        "ingredient_name": ing_info[iid]["name"],
                        "waste_pct": round(waste_pct, 4),
                        "waste_threshold_pct": waste_threshold,
                        "adjustment_applied": True,
                        "original_qty": round(original_qty, 2),
                        "adjusted_qty": round(base_qty, 2),
                        "order_eliminated": False,
                    })

        conn.close()

        # Sort orders: by store_id, then priority rank, then ingredient_id
        priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        orders.sort(key=lambda o: (o["store_id"], priority_rank[o["priority"]], o["ingredient_id"]))
        waste_report.sort(key=lambda w: (w["store_id"], w["ingredient_id"]))

        return orders, waste_report

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
        gt_orders, gt_waste = self._compute_ground_truth()
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: purchase_orders.csv exists with correct columns (10 pts)
        c1_max = 10
        max_score += c1_max
        po_path = os.path.join(self.workspace, "purchase_orders.csv")
        required_cols = [
            "store_id", "store_name", "ingredient_id", "ingredient_name",
            "supplier_id", "supplier_name", "recommended_qty", "unit_cost",
            "total_cost", "priority",
        ]
        if os.path.exists(po_path):
            try:
                import pandas as pd
                po_df = pd.read_csv(po_path)
                po_cols = [c.strip().lower() for c in po_df.columns]
                missing_cols = [c for c in required_cols if c not in po_cols]
                if not missing_cols:
                    eval_criteria["file_structure"] = {
                        "passed": True, "score": c1_max, "max_score": c1_max,
                    }
                    total_score += c1_max
                else:
                    eval_criteria["file_structure"] = {
                        "passed": False, "score": 0, "max_score": c1_max,
                        "reason": f"Missing columns: {missing_cols}",
                    }
            except Exception as e:
                eval_criteria["file_structure"] = {
                    "passed": False, "score": 0, "max_score": c1_max,
                    "reason": f"Error reading CSV: {str(e)}",
                }
                po_df = None
        else:
            eval_criteria["file_structure"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "purchase_orders.csv not found",
            }
            po_df = None

        # ── Criterion 2: Store coverage (15 pts)
        c2_max = 15
        max_score += c2_max
        if po_df is not None and not po_df.empty:
            gt_store_ids = set(o["store_id"] for o in gt_orders)
            sub_store_ids = set(int(x) for x in po_df["store_id"].unique())
            if gt_store_ids:
                coverage = len(gt_store_ids & sub_store_ids) / len(gt_store_ids)
            else:
                coverage = 1.0
            c2_score = round(c2_max * coverage)
            eval_criteria["store_coverage"] = {
                "passed": coverage >= 0.95,
                "score": c2_score,
                "max_score": c2_max,
                "reason": None if coverage >= 0.95 else f"Coverage {coverage:.1%}, expected >=95%",
            }
            total_score += c2_score
        else:
            eval_criteria["store_coverage"] = {
                "passed": False, "score": 0, "max_score": c2_max,
                "reason": "No purchase orders data available",
            }

        # ── Criterion 3: Order quantity accuracy (25 pts)
        c3_max = 25
        max_score += c3_max
        if po_df is not None and not po_df.empty and gt_orders:
            # Build ground truth lookup
            gt_lookup = {}
            for o in gt_orders:
                key = (int(o["store_id"]), int(o["ingredient_id"]))
                gt_lookup[key] = o

            matches = 0
            total_checked = 0
            for _, row in po_df.iterrows():
                key = (int(row["store_id"]), int(row["ingredient_id"]))
                if key in gt_lookup:
                    total_checked += 1
                    gt_qty = gt_lookup[key]["recommended_qty"]
                    sub_qty = float(row["recommended_qty"])
                    # Allow 10% tolerance or exact pack-size match
                    if gt_qty > 0:
                        rel_err = abs(sub_qty - gt_qty) / gt_qty
                        if rel_err <= 0.10:
                            matches += 1

            if total_checked > 0:
                accuracy = matches / len(gt_lookup)
            else:
                accuracy = 0.0
            c3_score = round(c3_max * min(1.0, accuracy))
            eval_criteria["order_quantity_accuracy"] = {
                "passed": accuracy >= 0.85,
                "score": c3_score,
                "max_score": c3_max,
                "reason": None if accuracy >= 0.85 else f"Accuracy {accuracy:.1%}, need >=85%",
            }
            total_score += c3_score
        else:
            eval_criteria["order_quantity_accuracy"] = {
                "passed": False, "score": 0, "max_score": c3_max,
                "reason": "No data to evaluate",
            }

        # ── Criterion 4: Supplier assignment validity (15 pts)
        c4_max = 15
        max_score += c4_max
        if po_df is not None and not po_df.empty and gt_orders:
            gt_supplier_lookup = {
                (int(o["store_id"]), int(o["ingredient_id"])): int(o["supplier_id"])
                for o in gt_orders
            }
            valid_suppliers = 0
            checked = 0
            for _, row in po_df.iterrows():
                key = (int(row["store_id"]), int(row["ingredient_id"]))
                if key in gt_supplier_lookup:
                    checked += 1
                    # Check if supplier is valid (carries the ingredient and is available)
                    conn = sqlite3.connect(self.db_path)
                    c = conn.cursor()
                    c.execute(
                        "SELECT 1 FROM supplier_catalog WHERE supplier_id = ? AND ingredient_id = ? AND is_available = 1",
                        (int(row["supplier_id"]), int(row["ingredient_id"])),
                    )
                    if c.fetchone():
                        valid_suppliers += 1
                    conn.close()
            if checked > 0:
                validity = valid_suppliers / checked
            else:
                validity = 0.0
            c4_score = round(c4_max * validity)
            eval_criteria["supplier_validity"] = {
                "passed": validity >= 0.90,
                "score": c4_score,
                "max_score": c4_max,
                "reason": None if validity >= 0.90 else f"Valid {validity:.1%}, need >=90%",
            }
            total_score += c4_score
        else:
            eval_criteria["supplier_validity"] = {
                "passed": False, "score": 0, "max_score": c4_max,
                "reason": "No data to evaluate",
            }

        # ── Criterion 5: Priority assignment accuracy (10 pts)
        c5_max = 10
        max_score += c5_max
        if po_df is not None and not po_df.empty and gt_orders:
            gt_priority = {
                (int(o["store_id"]), int(o["ingredient_id"])): o["priority"]
                for o in gt_orders
            }
            correct_priority = 0
            checked = 0
            for _, row in po_df.iterrows():
                key = (int(row["store_id"]), int(row["ingredient_id"]))
                if key in gt_priority:
                    checked += 1
                    if str(row["priority"]).strip().lower() == gt_priority[key]:
                        correct_priority += 1
            if checked > 0:
                p_accuracy = correct_priority / checked
            else:
                p_accuracy = 0.0
            c5_score = round(c5_max * p_accuracy)
            eval_criteria["priority_accuracy"] = {
                "passed": p_accuracy >= 0.85,
                "score": c5_score,
                "max_score": c5_max,
                "reason": None if p_accuracy >= 0.85 else f"Accuracy {p_accuracy:.1%}",
            }
            total_score += c5_score
        else:
            eval_criteria["priority_accuracy"] = {
                "passed": False, "score": 0, "max_score": c5_max,
                "reason": "No data to evaluate",
            }

        # ── Criterion 6: Waste reduction report (15 pts)
        c6_max = 15
        max_score += c6_max
        wr_path = os.path.join(self.workspace, "waste_reduction_report.csv")
        wr_required_cols = [
            "store_id", "ingredient_id", "waste_pct",
            "adjustment_applied", "original_qty", "adjusted_qty",
        ]
        if os.path.exists(wr_path):
            try:
                import pandas as pd
                wr_df = pd.read_csv(wr_path)
                wr_cols = [c.strip().lower() for c in wr_df.columns]
                missing = [c for c in wr_required_cols if c not in wr_cols]
                if not missing:
                    # Check coverage of waste-adjusted items
                    gt_waste_keys = set(
                        (w["store_id"], w["ingredient_id"])
                        for w in gt_waste
                        if w["adjustment_applied"]
                    )
                    if gt_waste_keys:
                        sub_keys = set()
                        for _, row in wr_df.iterrows():
                            sub_keys.add((int(row["store_id"]), int(row["ingredient_id"])))
                        wr_coverage = len(gt_waste_keys & sub_keys) / len(gt_waste_keys)
                    else:
                        wr_coverage = 1.0
                    c6_score = round(c6_max * min(1.0, wr_coverage))
                    eval_criteria["waste_report"] = {
                        "passed": wr_coverage >= 0.80,
                        "score": c6_score,
                        "max_score": c6_max,
                        "reason": None if wr_coverage >= 0.80 else f"Coverage {wr_coverage:.1%}",
                    }
                    total_score += c6_score
                else:
                    eval_criteria["waste_report"] = {
                        "passed": False, "score": 0, "max_score": c6_max,
                        "reason": f"Missing columns: {missing}",
                    }
            except Exception as e:
                eval_criteria["waste_report"] = {
                    "passed": False, "score": 0, "max_score": c6_max,
                    "reason": str(e),
                }
        else:
            eval_criteria["waste_report"] = {
                "passed": False, "score": 0, "max_score": c6_max,
                "reason": "waste_reduction_report.csv not found",
            }

        # ── Criterion 7: Action string summary (10 pts)
        c7_max = 10
        max_score += c7_max
        action_lower = action.lower() if action else ""
        has_total_orders = any(
            kw in action_lower for kw in ["total order", "order lines", "total lines", "purchase order"]
        )
        has_cost = any(kw in action_lower for kw in ["total cost", "overall cost", "total spend"])
        has_critical = "critical" in action_lower
        has_stores_mentioned = any(
            kw in action_lower for kw in ["store", "location"]
        )
        checks_passed = sum([has_total_orders, has_cost, has_critical, has_stores_mentioned])
        c7_score = round(c7_max * checks_passed / 4)
        eval_criteria["action_summary"] = {
            "passed": checks_passed >= 3,
            "score": c7_score,
            "max_score": c7_max,
            "reason": None if checks_passed >= 3 else f"Only {checks_passed}/4 summary elements found",
        }
        total_score += c7_score

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
        import csv as csv_mod
        import math as math_mod

        tool_calls = 0

        # ── Step 1: Load workspace files ─────────────────────────────────
        # Load ordering policy
        policy_path = os.path.join(self.workspace, "ordering_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)

        safety_stock_days = policy["safety_stock_days"]
        waste_reduction_factor = policy["waste_reduction_factor"]
        priority_thresholds = policy["priority_thresholds"]

        # Load store configs
        store_configs = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "store_config_zone_*.json"))):
            with open(fpath) as f:
                for sc in json.load(f):
                    store_configs[sc["store_id"]] = sc

        # Load ingredient specs
        ingredient_specs = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "ingredient_specs_batch_*.csv"))):
            with open(fpath) as f:
                reader = csv_mod.DictReader(f)
                for row in reader:
                    ingredient_specs[int(row["ingredient_id"])] = {
                        "shelf_life_days": int(row["shelf_life_days"]),
                        "waste_threshold_pct": float(row["waste_threshold_pct"]),
                        "reorder_multiplier": float(row["reorder_multiplier"]),
                    }

        # Load supplier ratings
        supplier_ratings = {}
        ratings_path = os.path.join(self.workspace, "supplier_ratings.csv")
        with open(ratings_path) as f:
            reader = csv_mod.DictReader(f)
            for row in reader:
                supplier_ratings[int(row["supplier_id"])] = float(row["reliability_score"])

        # ── Step 2: Discover stores and ingredients via tools ────────────
        all_stores = []
        page = 1
        while True:
            result = self.tools["list_stores"](page=page, page_size=20)
            tool_calls += 1
            all_stores.extend(result["stores"])
            if page >= result["total_pages"]:
                break
            page += 1

        all_ingredients = []
        page = 1
        while True:
            result = self.tools["list_ingredients"](page=page, page_size=20)
            tool_calls += 1
            all_ingredients.extend(result["ingredients"])
            if page >= result["total_pages"]:
                break
            page += 1

        ing_name_map = {ing["ingredient_id"]: ing["name"] for ing in all_ingredients}
        ing_cat_map = {ing["ingredient_id"]: ing["category"] for ing in all_ingredients}

        # ── Step 3: Determine reference date from sales data ─────────────
        # Use the first store to find date range
        first_store = all_stores[0]
        probe = self.tools["get_sales_summary"](
            store_id=first_store["store_id"],
            date_from="2020-01-01",
            date_to="2030-12-31",
        )
        tool_calls += 1
        # We need the actual dates; get from raw sales using a broader query
        # Since tools don't expose raw dates directly, we use the known generation logic:
        # data.py always generates 14 days ending at 2025-06-15
        # Reference date = 2025-06-16
        # But we should discover this from tools. Let's use a scanning approach.

        # Actually, get_sales_summary gives date_from/date_to but we need the max date.
        # We'll try multiple date ranges. Since data covers ~14 days, try recent dates.
        # Use a wide range to get all data.
        reference_date = None
        # We know the data is around 2025, scan for the latest date
        test_result = self.tools["get_sales_summary"](
            store_id=first_store["store_id"],
            date_from="2025-06-01",
            date_to="2025-06-30",
        )
        tool_calls += 1

        # The date_to in our query was 2025-06-30 but sales may end earlier.
        # Since the tool doesn't return individual dates, we need to figure this out.
        # Use an iterative approach: try specific dates
        from datetime import date as dt_date

        # Binary search for max date
        last_date_with_sales = None
        for d in range(30, 0, -1):
            test_date = f"2025-06-{d:02d}"
            res = self.tools["get_sales_summary"](
                store_id=first_store["store_id"],
                date_from=test_date,
                date_to=test_date,
            )
            tool_calls += 1
            if res["sales"]:
                last_date_with_sales = test_date
                break

        if last_date_with_sales:
            reference_date = datetime.strptime(last_date_with_sales, "%Y-%m-%d") + timedelta(days=1)
        else:
            # Fallback: just use 2025-06-16
            reference_date = datetime(2025, 6, 16)

        date_from_str = (reference_date - timedelta(days=14)).strftime("%Y-%m-%d")
        date_to_str = (reference_date - timedelta(days=1)).strftime("%Y-%m-%d")

        WEEKDAY_MAP = {
            "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
            "Friday": 4, "Saturday": 5, "Sunday": 6,
        }

        # ── Step 4: For each store, compute purchase orders ──────────────
        orders = []
        waste_report = []
        supplier_cache = {}  # ingredient_id -> supplier options

        for store in all_stores:
            sid = store["store_id"]
            sname = store["name"]

            if sid not in store_configs:
                continue

            sc = store_configs[sid]
            delivery_days = sc["delivery_days"]
            delivery_day_nums = sorted([WEEKDAY_MAP[d] for d in delivery_days])

            ref_weekday = reference_date.weekday()
            days_until = None
            for dd in delivery_day_nums:
                diff = (dd - ref_weekday) % 7
                if diff == 0:
                    diff = 7
                if days_until is None or diff < days_until:
                    days_until = diff
            if days_until is None:
                days_until = 7

            # Get sales
            sales_result = self.tools["get_sales_summary"](
                store_id=sid, date_from=date_from_str, date_to=date_to_str,
            )
            tool_calls += 1

            # Get inventory
            inv_result = self.tools["get_current_inventory"](store_id=sid)
            tool_calls += 1

            # Get waste
            waste_result = self.tools["get_waste_data"](store_id=sid)
            tool_calls += 1

            sales_map = {}
            for s in sales_result["sales"]:
                sales_map[s["ingredient_id"]] = {
                    "total_sold": s["total_sold"],
                    "days_with_sales": s["days_with_sales"],
                    "avg_daily": s["avg_daily_qty"],
                }

            inv_map = {i["ingredient_id"]: i["current_qty"] for i in inv_result["inventory"]}
            waste_map = {w["ingredient_id"]: w["total_wasted"] for w in waste_result["waste"]}

            all_ings = set(sales_map.keys()) | set(inv_map.keys())

            for iid in sorted(all_ings):
                if iid not in ingredient_specs:
                    continue

                specs = ingredient_specs[iid]
                reorder_mult = specs["reorder_multiplier"]
                waste_threshold = specs["waste_threshold_pct"]

                if iid in sales_map:
                    avg_daily = sales_map[iid]["avg_daily"]
                    total_sold = sales_map[iid]["total_sold"]
                else:
                    avg_daily = 0.0
                    total_sold = 0.0

                if avg_daily <= 0:
                    continue

                current_qty = inv_map.get(iid, 0.0)
                forecast = avg_daily * days_until
                safety = safety_stock_days * avg_daily
                base_qty = forecast - current_qty + safety
                base_qty = base_qty * reorder_mult

                total_wasted = waste_map.get(iid, 0)
                if total_sold + total_wasted > 0:
                    waste_pct = total_wasted / (total_sold + total_wasted)
                else:
                    waste_pct = 0.0

                waste_adjusted = False
                original_qty = base_qty
                if waste_pct > waste_threshold:
                    base_qty = base_qty * (1 - waste_reduction_factor)
                    waste_adjusted = True

                if base_qty <= 0:
                    if waste_adjusted:
                        waste_report.append({
                            "store_id": sid,
                            "store_name": sname,
                            "ingredient_id": iid,
                            "ingredient_name": ing_name_map.get(iid, ""),
                            "waste_pct": round(waste_pct, 4),
                            "waste_threshold_pct": waste_threshold,
                            "adjustment_applied": True,
                            "original_qty": round(original_qty, 2),
                            "adjusted_qty": round(base_qty, 2),
                            "order_eliminated": True,
                        })
                    continue

                # Get supplier options (cached)
                if iid not in supplier_cache:
                    sup_result = self.tools["get_supplier_options"](ingredient_id=iid)
                    tool_calls += 1
                    supplier_cache[iid] = sup_result["suppliers"]

                sup_options = supplier_cache[iid]
                if not sup_options:
                    continue

                best_cost = sup_options[0]["unit_cost"]
                candidates = [s for s in sup_options if s["unit_cost"] == best_cost]
                if len(candidates) > 1:
                    best = max(candidates, key=lambda s: supplier_ratings.get(s["supplier_id"], 0.0))
                else:
                    best = candidates[0]

                order_qty = math_mod.ceil(base_qty / best["pack_size"]) * best["pack_size"]
                total_cost = round(order_qty * best["unit_cost"], 2)

                if avg_daily > 0:
                    days_supply = current_qty / avg_daily
                else:
                    days_supply = float("inf")

                if days_supply < priority_thresholds["critical"]:
                    priority = "critical"
                elif days_supply < priority_thresholds["high"]:
                    priority = "high"
                elif days_supply < priority_thresholds["medium"]:
                    priority = "medium"
                else:
                    priority = "low"

                orders.append({
                    "store_id": sid,
                    "store_name": sname,
                    "ingredient_id": iid,
                    "ingredient_name": ing_name_map.get(iid, ""),
                    "supplier_id": best["supplier_id"],
                    "supplier_name": best["supplier_name"],
                    "recommended_qty": order_qty,
                    "unit_cost": best["unit_cost"],
                    "total_cost": total_cost,
                    "priority": priority,
                })

                if waste_adjusted:
                    waste_report.append({
                        "store_id": sid,
                        "store_name": sname,
                        "ingredient_id": iid,
                        "ingredient_name": ing_name_map.get(iid, ""),
                        "waste_pct": round(waste_pct, 4),
                        "waste_threshold_pct": waste_threshold,
                        "adjustment_applied": True,
                        "original_qty": round(original_qty, 2),
                        "adjusted_qty": round(base_qty, 2),
                        "order_eliminated": False,
                    })

        # ── Step 5: Sort and write deliverables ──────────────────────────
        priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        orders.sort(key=lambda o: (o["store_id"], priority_rank[o["priority"]], o["ingredient_id"]))
        waste_report.sort(key=lambda w: (w["store_id"], w["ingredient_id"]))

        # Write purchase_orders.csv
        po_path = os.path.join(self.workspace, "purchase_orders.csv")
        with open(po_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=[
                "store_id", "store_name", "ingredient_id", "ingredient_name",
                "supplier_id", "supplier_name", "recommended_qty", "unit_cost",
                "total_cost", "priority",
            ])
            writer.writeheader()
            writer.writerows(orders)

        # Write waste_reduction_report.csv
        wr_path = os.path.join(self.workspace, "waste_reduction_report.csv")
        with open(wr_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=[
                "store_id", "store_name", "ingredient_id", "ingredient_name",
                "waste_pct", "waste_threshold_pct", "adjustment_applied",
                "original_qty", "adjusted_qty", "order_eliminated",
            ])
            writer.writeheader()
            writer.writerows(waste_report)

        # ── Step 6: Build action summary ─────────────────────────────────
        total_order_cost = sum(o["total_cost"] for o in orders)
        n_critical = sum(1 for o in orders if o["priority"] == "critical")
        n_high = sum(1 for o in orders if o["priority"] == "high")
        stores_covered = len(set(o["store_id"] for o in orders))
        waste_adjustments = len([w for w in waste_report if w["adjustment_applied"]])

        action = (
            f"Purchase order generation complete. Generated {len(orders)} total order lines "
            f"covering {stores_covered} store locations. "
            f"Total cost across all orders: ${total_order_cost:,.2f}. "
            f"Priority breakdown: {n_critical} critical items requiring immediate attention, "
            f"{n_high} high-priority items. "
            f"Waste reduction analysis identified {waste_adjustments} ingredient-store combinations "
            f"where order quantities were adjusted downward due to exceeding waste thresholds. "
            f"All purchase orders saved to purchase_orders.csv and waste analysis saved to "
            f"waste_reduction_report.csv."
        )

        print(f"[verify] Tool calls made: {tool_calls}")
        return self.step(action)
