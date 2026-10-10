"""
Environment for Perishable Goods Spoilage Risk Alert task.
"""

import sqlite3
import os
import json
import yaml
import csv
import math
import re
from typing import Tuple, Dict, List, Any
from datetime import datetime, timedelta


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
        }
        return func
    return decorator


def _envelope(payload):
    """MCP-style tool result: payload JSON-encoded in a text content block."""
    return {"content": [{"type": "text",
                         "text": json.dumps(payload, ensure_ascii=False, default=str)}],
            "isError": False}


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
        description="List all warehouse facilities with their IDs, names, locations, and zones.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        }
    )
    def list_warehouses(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT warehouse_id, name, location, zone, capacity FROM warehouses")
        rows = c.fetchall()
        conn.close()
        return _envelope([
            {"warehouse_id": r[0], "name": r[1], "location": r[2], "zone": r[3], "capacity": r[4]}
            for r in rows
        ])

    @tool(
        description="List products with pagination. Returns up to 20 products per page.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)."
                },
                "category": {
                    "type": "string",
                    "description": "Optional filter by category name (e.g. 'Dairy', 'Meat')."
                }
            },
            "required": ["page"],
        }
    )
    def list_products(self, page: int, category: str = None):
        page_size = 20
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        if category:
            c.execute(
                "SELECT product_id, name, category, subcategory FROM products WHERE category = ? ORDER BY product_id LIMIT ? OFFSET ?",
                (category, page_size, offset),
            )
            c2 = conn.cursor()
            c2.execute("SELECT COUNT(*) FROM products WHERE category = ?", (category,))
        else:
            c.execute(
                "SELECT product_id, name, category, subcategory FROM products ORDER BY product_id LIMIT ? OFFSET ?",
                (page_size, offset),
            )
            c2 = conn.cursor()
            c2.execute("SELECT COUNT(*) FROM products")

        rows = c.fetchall()
        total = c2.fetchone()[0]
        conn.close()

        return json.dumps({
            "page": page,
            "page_size": page_size,
            "total_products": total,
            "total_pages": math.ceil(total / page_size),
            "products": [
                {"product_id": r[0], "name": r[1], "category": r[2], "subcategory": r[3]}
                for r in rows
            ],
        }, ensure_ascii=False, default=str)

    @tool(
        description="Get detailed information about a specific product by its product ID.",
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product ID (e.g. 'PRD-0001')."
                }
            },
            "required": ["product_id"],
        }
    )
    def get_product_details(self, product_id: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT product_id, name, category, subcategory, unit_price, shelf_life_days, storage_temp_min, storage_temp_max FROM products WHERE product_id = ?",
            (product_id,),
        )
        row = c.fetchone()
        conn.close()
        if not row:
            return _envelope({"error": f"Product {product_id} not found."})
        return _envelope({
            "product_id": row[0],
            "name": row[1],
            "category": row[2],
            "subcategory": row[3],
            "unit_price": row[4],
            "shelf_life_days": row[5],
            "storage_temp_min": row[6],
            "storage_temp_max": row[7],
        })

    @tool(
        description="Get inventory batches at a specific warehouse. Returns up to 25 records per page, including batch IDs, product IDs, quantities, received dates, and expiry dates.",
        parameters={
            "type": "object",
            "properties": {
                "warehouse_id": {
                    "type": "string",
                    "description": "The warehouse ID (e.g. 'WH001')."
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1."
                }
            },
            "required": ["warehouse_id"],
        }
    )
    def get_inventory(self, warehouse_id: str, page: int = 1):
        page_size = 25
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT batch_id, product_id, quantity, received_date, expiry_date FROM inventory_batches WHERE warehouse_id = ? ORDER BY expiry_date ASC LIMIT ? OFFSET ?",
            (warehouse_id, page_size, offset),
        )
        rows = c.fetchall()
        c2 = conn.cursor()
        c2.execute("SELECT COUNT(*) FROM inventory_batches WHERE warehouse_id = ?", (warehouse_id,))
        total = c2.fetchone()[0]
        conn.close()

        return json.dumps({
            "warehouse_id": warehouse_id,
            "page": page,
            "page_size": page_size,
            "total_batches": total,
            "total_pages": math.ceil(total / page_size),
            "batches": [
                {
                    "batch_id": r[0],
                    "product_id": r[1],
                    "quantity": r[2],
                    "received_date": r[3],
                    "expiry_date": r[4],
                }
                for r in rows
            ],
        }, ensure_ascii=False, default=str)

    @tool(
        description="Get the last 7 days of sales history for a specific product at a specific warehouse. Returns daily quantities sold.",
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product ID."
                },
                "warehouse_id": {
                    "type": "string",
                    "description": "The warehouse ID."
                }
            },
            "required": ["product_id", "warehouse_id"],
        }
    )
    def get_sales_history(self, product_id: str, warehouse_id: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT sale_date, quantity_sold FROM daily_sales WHERE product_id = ? AND warehouse_id = ? ORDER BY sale_date DESC",
            (product_id, warehouse_id),
        )
        rows = c.fetchall()
        conn.close()

        total_sold = sum(r[1] for r in rows)
        days = len(rows) if rows else 1
        avg_daily = round(total_sold / days, 2) if rows else 0.0

        return _envelope({
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "records": [{"date": r[0], "quantity_sold": r[1]} for r in rows],
            "total_sold_7d": total_sold,
            "avg_daily_sales": avg_daily,
        })

    @tool(
        description="Get promotions scheduled within a date range. Returns promotion details including product ID, dates, discount percentage, and expected sales lift.",
        parameters={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format."
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format."
                }
            },
            "required": ["start_date", "end_date"],
        }
    )
    def get_promotions_in_range(self, start_date: str, end_date: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT promo_id, product_id, promo_name, start_date, end_date, discount_pct, expected_sales_lift FROM promotions WHERE start_date <= ? AND end_date >= ? ORDER BY start_date",
            (end_date, start_date),
        )
        rows = c.fetchall()
        conn.close()

        return json.dumps({
            "start_date": start_date,
            "end_date": end_date,
            "total_promotions": len(rows),
            "promotions": [
                {
                    "promo_id": r[0],
                    "product_id": r[1],
                    "promo_name": r[2],
                    "start_date": r[3],
                    "end_date": r[4],
                    "discount_pct": r[5],
                    "expected_sales_lift": r[6],
                }
                for r in rows
            ],
        }, ensure_ascii=False, default=str)

    # ---- Evaluation ----

    def _compute_ground_truth(self):
        """Compute the expected priority list from database and workspace files."""
        # Load config
        config_path = os.path.join(self.workspace, "config.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        ref_dt = datetime.strptime(config["reference_datetime"], "%Y-%m-%dT%H:%M:%S")
        weights = config["priority_weights"]
        tiers = config["markdown_tiers"]
        overstock_threshold = config["overstock_threshold_days"]

        # Load category risk factors
        risk_path = os.path.join(self.workspace, "category_risk_factors.json")
        with open(risk_path, "r") as f:
            cat_risk = json.load(f)

        # Load all supplement data from workspace
        supplier_data = {}  # product_id -> {supplier_reliability, unit_weight_kg}
        for fname in sorted(os.listdir(self.workspace)):
            fpath = os.path.join(self.workspace, fname)
            if not fname.startswith("product_supplement_"):
                continue
            if fname.endswith(".csv"):
                with open(fpath, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        supplier_data[row["product_id"]] = {
                            "supplier_reliability": float(row["supplier_reliability"]),
                            "unit_weight_kg": float(row["unit_weight_kg"]),
                        }
            elif fname.endswith(".json"):
                with open(fpath, "r") as f:
                    records = json.load(f)
                    for row in records:
                        supplier_data[row["product_id"]] = {
                            "supplier_reliability": float(row["supplier_reliability"]),
                            "unit_weight_kg": float(row["unit_weight_kg"]),
                        }
            elif fname.endswith(".yaml"):
                with open(fpath, "r") as f:
                    data = yaml.safe_load(f)
                    for row in data.get("product_supplements", []):
                        supplier_data[row["product_id"]] = {
                            "supplier_reliability": float(row["supplier_reliability"]),
                            "unit_weight_kg": float(row["unit_weight_kg"]),
                        }
            elif fname.endswith(".txt"):
                with open(fpath, "r") as f:
                    lines = f.readlines()
                    for line in lines[1:]:  # skip header
                        parts = line.strip().split("\t")
                        if len(parts) >= 4:
                            supplier_data[parts[0]] = {
                                "supplier_reliability": float(parts[2]),
                                "unit_weight_kg": float(parts[3]),
                            }

        # Query database for all needed data
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Get all inventory batches expiring within 48 hours
        deadline = ref_dt + timedelta(hours=48)
        c.execute(
            "SELECT batch_id, product_id, warehouse_id, quantity, expiry_date FROM inventory_batches WHERE expiry_date > ? AND expiry_date <= ? ORDER BY expiry_date",
            (ref_dt.strftime("%Y-%m-%d %H:%M:%S"), deadline.strftime("%Y-%m-%d %H:%M:%S")),
        )
        at_risk_batches = c.fetchall()

        # Build priority list
        priority_list = []
        for batch in at_risk_batches:
            batch_id, product_id, warehouse_id, quantity, expiry_str = batch
            expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")
            hours_to_expiry = (expiry_dt - ref_dt).total_seconds() / 3600.0

            # Get product details
            c.execute("SELECT name, category, unit_price FROM products WHERE product_id = ?", (product_id,))
            prod = c.fetchone()
            if not prod:
                continue
            prod_name, category, unit_price = prod

            # Get avg daily sales
            c.execute(
                "SELECT AVG(quantity_sold) FROM daily_sales WHERE product_id = ? AND warehouse_id = ?",
                (product_id, warehouse_id),
            )
            avg_row = c.fetchone()
            avg_daily_sales = avg_row[0] if avg_row and avg_row[0] else 0.0

            # Days of stock
            if avg_daily_sales > 0:
                days_of_stock = quantity / avg_daily_sales
            else:
                days_of_stock = overstock_threshold * 2  # treat no sales as highly overstocked

            # Check promotions overlapping with the at-risk window
            c.execute(
                "SELECT COUNT(*) FROM promotions WHERE product_id = ? AND start_date <= ? AND end_date >= ?",
                (product_id, deadline.strftime("%Y-%m-%d"), ref_dt.strftime("%Y-%m-%d")),
            )
            has_promo = c.fetchone()[0] > 0

            # Supplier reliability
            supp_info = supplier_data.get(product_id, {"supplier_reliability": 0.75, "unit_weight_kg": 1.0})
            supplier_reliability = supp_info["supplier_reliability"]

            # Category risk
            category_risk = cat_risk.get(category, 0.5)

            # Compute priority score components
            urgency = (48.0 - hours_to_expiry) / 48.0
            overstock = min(days_of_stock / overstock_threshold, 1.0)
            supplier_risk = 1.0 - supplier_reliability
            promo_conflict = 1.0 if has_promo else 0.0

            priority_score = (
                urgency * weights["urgency"]
                + overstock * weights["overstock"]
                + category_risk * weights["category_risk"]
                + supplier_risk * weights["supplier_risk"]
                + promo_conflict * weights["promo_conflict"]
            )
            priority_score = round(priority_score, 4)

            # Markdown tier
            markdown_pct = 0
            for tier in sorted(tiers, key=lambda t: t["max_hours"]):
                if hours_to_expiry <= tier["max_hours"]:
                    markdown_pct = tier["markdown_pct"]
                    break

            estimated_loss = round(quantity * unit_price * (markdown_pct / 100.0), 2)

            priority_list.append({
                "product_id": product_id,
                "product_name": prod_name,
                "category": category,
                "warehouse_id": warehouse_id,
                "batch_id": batch_id,
                "quantity": quantity,
                "hours_to_expiry": round(hours_to_expiry, 1),
                "avg_daily_sales": round(avg_daily_sales, 2),
                "days_of_stock": round(days_of_stock, 1),
                "has_promotion": has_promo,
                "markdown_pct": markdown_pct,
                "priority_score": priority_score,
                "estimated_loss": estimated_loss,
            })

        conn.close()

        # Sort by priority score descending, then hours_to_expiry ascending for ties
        priority_list.sort(key=lambda x: (-x["priority_score"], x["hours_to_expiry"]))

        # Add rank
        for i, item in enumerate(priority_list):
            item["rank"] = i + 1

        total_loss = round(sum(item["estimated_loss"] for item in priority_list), 2)

        return {
            "priority_list": priority_list,
            "total_items": len(priority_list),
            "total_estimated_loss": total_loss,
        }

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
        gt_list = ground_truth["priority_list"]
        gt_total_items = ground_truth["total_items"]
        gt_total_loss = ground_truth["total_estimated_loss"]

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # Criterion 1: File existence (10 pts)
        max_score += 10
        output_path = os.path.join(self.workspace, "priority_list.md")
        file_exists = os.path.isfile(output_path)
        if file_exists:
            with open(output_path, "r") as f:
                file_content = f.read()
            eval_criteria["file_exists"] = {"passed": True, "score": 10, "max_score": 10}
            total_score += 10
        else:
            file_content = ""
            eval_criteria["file_exists"] = {"passed": False, "score": 0, "max_score": 10, "reason": "priority_list.md not found in workspace"}

        # Criterion 2: Correct at-risk items identified (25 pts)
        max_score += 25
        if file_content:
            # Extract batch IDs from the file
            found_batches = set(re.findall(r"BAT-\d{5}", file_content))
            expected_batches = set(item["batch_id"] for item in gt_list)

            if expected_batches:
                precision = len(found_batches & expected_batches) / len(found_batches) if found_batches else 0
                recall = len(found_batches & expected_batches) / len(expected_batches)
                f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
                item_score = round(f1 * 25)
            else:
                item_score = 0

            passed = item_score >= 20
            eval_criteria["correct_items"] = {
                "passed": passed,
                "score": item_score,
                "max_score": 25,
                "reason": None if passed else f"F1={f1:.2f}, found={len(found_batches)}, expected={len(expected_batches)}"
            }
            total_score += item_score
        else:
            eval_criteria["correct_items"] = {"passed": False, "score": 0, "max_score": 25, "reason": "No output file"}

        # Criterion 3: Priority scores accuracy (20 pts)
        max_score += 20
        if file_content and gt_list:
            # Parse the markdown table to extract batch_id -> priority_score mapping
            parsed_scores = {}
            for line in file_content.split("\n"):
                if "BAT-" not in line or "|" not in line:
                    continue
                cells = [c.strip() for c in line.split("|")]
                # Table row: empty | Rank | Product_ID | ... | Batch_ID(6) | ... | Priority_Score(13) | Estimated_Loss(14) | empty
                # After split by |, index 0 is empty, columns are 1-indexed
                if len(cells) >= 15:
                    batch_id_cell = cells[6]  # Batch_ID column
                    priority_score_cell = cells[13]  # Priority_Score column
                    batch_match = re.search(r"BAT-\d{5}", batch_id_cell)
                    if batch_match:
                        try:
                            parsed_scores[batch_match.group()] = float(priority_score_cell)
                        except (ValueError, IndexError):
                            pass

            score_matches = 0
            score_total = 0
            for item in gt_list:
                batch_id = item["batch_id"]
                expected_score = item["priority_score"]
                score_total += 1
                if batch_id in parsed_scores:
                    if abs(parsed_scores[batch_id] - expected_score) <= 0.05:
                        score_matches += 1

            if score_total > 0:
                accuracy = score_matches / score_total
                pts = round(accuracy * 20)
            else:
                pts = 0

            passed = pts >= 15
            eval_criteria["priority_scores"] = {
                "passed": passed,
                "score": pts,
                "max_score": 20,
                "reason": None if passed else f"Accuracy={accuracy:.2f} ({score_matches}/{score_total})"
            }
            total_score += pts
        else:
            eval_criteria["priority_scores"] = {"passed": False, "score": 0, "max_score": 20, "reason": "No output file or no expected items"}

        # Criterion 4: Markdown percentages (15 pts)
        max_score += 15
        if file_content and gt_list:
            # Parse markdown table for batch_id -> markdown_pct
            parsed_md = {}
            for line in file_content.split("\n"):
                if "BAT-" not in line or "|" not in line:
                    continue
                cells = [c.strip() for c in line.split("|")]
                if len(cells) >= 15:
                    batch_id_cell = cells[6]  # Batch_ID
                    md_pct_cell = cells[12]  # Markdown_Pct
                    batch_match = re.search(r"BAT-\d{5}", batch_id_cell)
                    if batch_match:
                        try:
                            parsed_md[batch_match.group()] = int(md_pct_cell)
                        except (ValueError, IndexError):
                            pass

            md_matches = 0
            md_total = 0
            for item in gt_list:
                batch_id = item["batch_id"]
                expected_md = item["markdown_pct"]
                md_total += 1
                if batch_id in parsed_md and parsed_md[batch_id] == expected_md:
                    md_matches += 1

            if md_total > 0:
                accuracy = md_matches / md_total
                pts = round(accuracy * 15)
            else:
                pts = 0

            passed = pts >= 12
            eval_criteria["markdown_percentages"] = {
                "passed": passed,
                "score": pts,
                "max_score": 15,
                "reason": None if passed else f"Accuracy={accuracy:.2f} ({md_matches}/{md_total})"
            }
            total_score += pts
        else:
            eval_criteria["markdown_percentages"] = {"passed": False, "score": 0, "max_score": 15, "reason": "No output file or no expected items"}

        # Criterion 5: Sort order (10 pts)
        max_score += 10
        if file_content and gt_list:
            # Extract batch IDs in order from file
            file_batch_order = re.findall(r"BAT-\d{5}", file_content)
            expected_order = [item["batch_id"] for item in gt_list]

            # Check if the order matches (for batches that appear in both)
            common = [b for b in file_batch_order if b in set(expected_order)]
            expected_common = [b for b in expected_order if b in set(file_batch_order)]

            if common and expected_common:
                # Check if ordering is consistent (Kendall tau or simple sequential check)
                correct_pairs = 0
                total_pairs = 0
                for i in range(len(common)):
                    for j in range(i + 1, len(common)):
                        total_pairs += 1
                        # Check if same relative order
                        idx_i_expected = expected_common.index(common[i]) if common[i] in expected_common else -1
                        idx_j_expected = expected_common.index(common[j]) if common[j] in expected_common else -1
                        if idx_i_expected >= 0 and idx_j_expected >= 0:
                            if idx_i_expected < idx_j_expected:
                                correct_pairs += 1

                if total_pairs > 0:
                    order_accuracy = correct_pairs / total_pairs
                    pts = round(order_accuracy * 10)
                else:
                    pts = 0
            else:
                pts = 0

            passed = pts >= 8
            eval_criteria["sort_order"] = {
                "passed": passed,
                "score": pts,
                "max_score": 10,
                "reason": None if passed else f"Order accuracy={order_accuracy:.2f}" if 'order_accuracy' in dir() else "No common items"
            }
            total_score += pts
        else:
            eval_criteria["sort_order"] = {"passed": False, "score": 0, "max_score": 10, "reason": "No output file"}

        # Criterion 6: Column completeness (10 pts)
        max_score += 10
        required_columns = [
            "Rank", "Product_ID", "Product_Name", "Category", "Warehouse_ID",
            "Batch_ID", "Quantity", "Hours_to_Expiry", "Avg_Daily_Sales",
            "Days_of_Stock", "Has_Promotion", "Markdown_Pct", "Priority_Score",
            "Estimated_Loss"
        ]
        if file_content:
            # Check header row of markdown table
            found_cols = 0
            for col in required_columns:
                if col in file_content:
                    found_cols += 1
            col_accuracy = found_cols / len(required_columns)
            pts = round(col_accuracy * 10)
            passed = pts >= 8
            eval_criteria["column_completeness"] = {
                "passed": passed,
                "score": pts,
                "max_score": 10,
                "reason": None if passed else f"Found {found_cols}/{len(required_columns)} columns"
            }
            total_score += pts
        else:
            eval_criteria["column_completeness"] = {"passed": False, "score": 0, "max_score": 10, "reason": "No output file"}

        # Criterion 7: Summary accuracy (10 pts)
        max_score += 10
        if file_content and action:
            pts = 0
            # Check total count in action or file
            count_mentioned = False
            loss_mentioned = False

            # Check for total items count
            count_patterns = [str(gt_total_items), f"{gt_total_items} "]
            for pat in count_patterns:
                if pat in action or pat in file_content:
                    count_mentioned = True
                    break

            # Check for total loss (within 5% tolerance)
            loss_pattern = re.findall(r"\$?([\d,]+\.?\d*)", action + " " + file_content)
            for val_str in loss_pattern:
                try:
                    val = float(val_str.replace(",", ""))
                    if abs(val - gt_total_loss) / max(gt_total_loss, 1) <= 0.05:
                        loss_mentioned = True
                        break
                except ValueError:
                    pass

            if count_mentioned:
                pts += 5
            if loss_mentioned:
                pts += 5

            passed = pts >= 8
            eval_criteria["summary_accuracy"] = {
                "passed": passed,
                "score": pts,
                "max_score": 10,
                "reason": None if passed else f"count_ok={count_mentioned}, loss_ok={loss_mentioned}"
            }
            total_score += pts
        else:
            eval_criteria["summary_accuracy"] = {"passed": False, "score": 0, "max_score": 10, "reason": "No output or action"}

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
        import os

        # Step 1: Read config.yaml from workspace
        config_path = os.path.join(self.workspace, "config.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        ref_dt = datetime.strptime(config["reference_datetime"], "%Y-%m-%dT%H:%M:%S")
        weights = config["priority_weights"]
        tiers = config["markdown_tiers"]
        overstock_threshold = config["overstock_threshold_days"]

        # Step 2: Read category_risk_factors.json
        risk_path = os.path.join(self.workspace, "category_risk_factors.json")
        with open(risk_path, "r") as f:
            cat_risk = json.load(f)

        # Step 3: Read all supplement files to get supplier reliability
        supplier_data = {}
        for fname in sorted(os.listdir(self.workspace)):
            fpath = os.path.join(self.workspace, fname)
            if not fname.startswith("product_supplement_"):
                continue
            if fname.endswith(".csv"):
                with open(fpath, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        supplier_data[row["product_id"]] = {
                            "supplier_reliability": float(row["supplier_reliability"]),
                            "unit_weight_kg": float(row["unit_weight_kg"]),
                        }
            elif fname.endswith(".json"):
                with open(fpath, "r") as f:
                    records = json.load(f)
                    for row in records:
                        supplier_data[row["product_id"]] = {
                            "supplier_reliability": float(row["supplier_reliability"]),
                            "unit_weight_kg": float(row["unit_weight_kg"]),
                        }
            elif fname.endswith(".yaml"):
                with open(fpath, "r") as f:
                    data = yaml.safe_load(f)
                    for row in data.get("product_supplements", []):
                        supplier_data[row["product_id"]] = {
                            "supplier_reliability": float(row["supplier_reliability"]),
                            "unit_weight_kg": float(row["unit_weight_kg"]),
                        }
            elif fname.endswith(".txt"):
                with open(fpath, "r") as f:
                    lines = f.readlines()
                    for line in lines[1:]:
                        parts = line.strip().split("\t")
                        if len(parts) >= 4:
                            supplier_data[parts[0]] = {
                                "supplier_reliability": float(parts[2]),
                                "unit_weight_kg": float(parts[3]),
                            }

        # Step 4: Call list_warehouses tool
        tool_call_count = 0

        warehouses = json.loads(self.tools["list_warehouses"]()["content"][0]["text"])
        tool_call_count += 1

        # Step 5: For each warehouse, get all inventory batches (paginated)
        all_batches = []
        for wh in warehouses:
            wh_id = wh["warehouse_id"]
            page = 1
            while True:
                result = json.loads(self.tools["get_inventory"](warehouse_id=wh_id, page=page))
                tool_call_count += 1
                all_batches.extend([(b, wh_id) for b in result["batches"]])
                if page >= result["total_pages"]:
                    break
                page += 1

        # Step 6: Filter batches within 48 hours of expiry
        deadline = ref_dt + timedelta(hours=48)
        at_risk = []
        for batch, wh_id in all_batches:
            expiry_dt = datetime.strptime(batch["expiry_date"], "%Y-%m-%d %H:%M:%S")
            if ref_dt < expiry_dt <= deadline:
                at_risk.append((batch, wh_id))

        # Step 7: For each at-risk batch, get product details and sales history
        product_cache = {}
        sales_cache = {}
        priority_list = []

        for batch, wh_id in at_risk:
            product_id = batch["product_id"]
            batch_id = batch["batch_id"]
            quantity = batch["quantity"]
            expiry_dt = datetime.strptime(batch["expiry_date"], "%Y-%m-%d %H:%M:%S")
            hours_to_expiry = (expiry_dt - ref_dt).total_seconds() / 3600.0

            # Get product details (cache to avoid redundant calls)
            if product_id not in product_cache:
                product_cache[product_id] = json.loads(self.tools["get_product_details"](product_id=product_id)["content"][0]["text"])
                tool_call_count += 1
            prod_info = product_cache[product_id]

            # Get sales history
            cache_key = (product_id, wh_id)
            if cache_key not in sales_cache:
                sales_cache[cache_key] = json.loads(self.tools["get_sales_history"](product_id=product_id, warehouse_id=wh_id)["content"][0]["text"])
                tool_call_count += 1
            sales_info = sales_cache[cache_key]

            avg_daily_sales = sales_info["avg_daily_sales"]

            # Days of stock
            if avg_daily_sales > 0:
                days_of_stock = quantity / avg_daily_sales
            else:
                days_of_stock = overstock_threshold * 2

            # Category risk
            category = prod_info["category"]
            category_risk_val = cat_risk.get(category, 0.5)

            # Supplier risk
            supp_info = supplier_data.get(product_id, {"supplier_reliability": 0.75, "unit_weight_kg": 1.0})
            supplier_reliability = supp_info["supplier_reliability"]
            supplier_risk_val = 1.0 - supplier_reliability

            priority_list.append({
                "product_id": product_id,
                "product_name": prod_info["name"],
                "category": category,
                "warehouse_id": wh_id,
                "batch_id": batch_id,
                "quantity": quantity,
                "hours_to_expiry": round(hours_to_expiry, 1),
                "avg_daily_sales": round(avg_daily_sales, 2),
                "days_of_stock": round(days_of_stock, 1),
                "unit_price": prod_info["unit_price"],
                "category_risk": category_risk_val,
                "supplier_reliability": supplier_reliability,
                "supplier_risk": supplier_risk_val,
            })

        # Step 8: Get promotions in the at-risk window
        promo_start = ref_dt.strftime("%Y-%m-%d")
        promo_end = deadline.strftime("%Y-%m-%d")
        promo_result = json.loads(self.tools["get_promotions_in_range"](start_date=promo_start, end_date=promo_end))
        tool_call_count += 1

        promo_products = set(p["product_id"] for p in promo_result["promotions"])

        # Step 9: Calculate priority scores and markdown percentages
        for item in priority_list:
            has_promo = item["product_id"] in promo_products
            item["has_promotion"] = has_promo

            urgency = (48.0 - item["hours_to_expiry"]) / 48.0
            overstock = min(item["days_of_stock"] / overstock_threshold, 1.0)
            promo_conflict = 1.0 if has_promo else 0.0

            priority_score = (
                urgency * weights["urgency"]
                + overstock * weights["overstock"]
                + item["category_risk"] * weights["category_risk"]
                + item["supplier_risk"] * weights["supplier_risk"]
                + promo_conflict * weights["promo_conflict"]
            )
            item["priority_score"] = round(priority_score, 4)

            # Markdown tier
            markdown_pct = 0
            for tier in sorted(tiers, key=lambda t: t["max_hours"]):
                if item["hours_to_expiry"] <= tier["max_hours"]:
                    markdown_pct = tier["markdown_pct"]
                    break
            item["markdown_pct"] = markdown_pct
            item["estimated_loss"] = round(item["quantity"] * item["unit_price"] * (markdown_pct / 100.0), 2)

        # Step 10: Sort by priority score desc, then hours_to_expiry asc
        priority_list.sort(key=lambda x: (-x["priority_score"], x["hours_to_expiry"]))

        # Add rank
        for i, item in enumerate(priority_list):
            item["rank"] = i + 1

        # Step 11: Write priority_list.md
        total_loss = round(sum(item["estimated_loss"] for item in priority_list), 2)
        total_items = len(priority_list)

        lines = []
        lines.append("# Priority Markdown List - Perishable Goods at Risk of Spoilage")
        lines.append("")
        lines.append("| Rank | Product_ID | Product_Name | Category | Warehouse_ID | Batch_ID | Quantity | Hours_to_Expiry | Avg_Daily_Sales | Days_of_Stock | Has_Promotion | Markdown_Pct | Priority_Score | Estimated_Loss |")
        lines.append("|------|-----------|-------------|----------|-------------|---------|---------|----------------|----------------|--------------|--------------|-------------|---------------|---------------|")

        for item in priority_list:
            lines.append(
                f"| {item['rank']} | {item['product_id']} | {item['product_name']} | {item['category']} | "
                f"{item['warehouse_id']} | {item['batch_id']} | {item['quantity']} | "
                f"{item['hours_to_expiry']:.1f} | {item['avg_daily_sales']:.2f} | "
                f"{item['days_of_stock']:.1f} | {'Yes' if item['has_promotion'] else 'No'} | "
                f"{item['markdown_pct']} | {item['priority_score']:.4f} | {item['estimated_loss']:.2f} |"
            )

        lines.append("")
        lines.append(f"**Total at-risk items: {total_items}**")
        lines.append(f"**Total estimated markdown loss: ${total_loss:.2f}**")

        output_path = os.path.join(self.workspace, "priority_list.md")
        with open(output_path, "w") as f:
            f.write("\n".join(lines))

        # Step 12: Construct action string
        top3 = priority_list[:3]
        top3_desc = "; ".join(
            f"#{item['rank']} {item['product_name']} (Batch {item['batch_id']}, Score: {item['priority_score']:.4f})"
            for item in top3
        )

        action = (
            f"I have completed the perishable goods risk analysis. "
            f"Total at-risk items within 48 hours of expiry: {total_items}. "
            f"Total estimated markdown loss: ${total_loss:.2f}. "
            f"Top 3 highest-priority items: {top3_desc}. "
            f"The full priority markdown list has been saved to priority_list.md."
        )

        assert tool_call_count >= 15, f"Tool call count too low: {tool_call_count}"

        return self.step(action)
