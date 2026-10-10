"""
Environment for competitor price monitoring and alert generation task.
"""

import os
import csv
import json
import sqlite3
import math
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

    # -----------------------------------------------------------------------
    # Tool methods
    # -----------------------------------------------------------------------

    @tool(
        description="List all product categories available in the catalog.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_categories(self) -> List[str]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT DISTINCT category FROM products ORDER BY category")
        cats = [row[0] for row in c.fetchall()]
        conn.close()
        return cats

    @tool(
        description="List products in a given category with pagination. Returns a list of product summaries (id, sku, name, current_price, status) and total count.",
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Product category name",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of products per page (max 20)",
                },
            },
            "required": ["category", "page", "page_size"],
        },
    )
    def list_products(self, category: str, page: int, page_size: int) -> Dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM products WHERE category = ?", (category,))
        total = c.fetchone()[0]
        c.execute(
            "SELECT id, sku, name, current_price, status FROM products "
            "WHERE category = ? ORDER BY id LIMIT ? OFFSET ?",
            (category, page_size, offset),
        )
        items = [
            {"id": r[0], "sku": r[1], "name": r[2], "current_price": r[3], "status": r[4]}
            for r in c.fetchall()
        ]
        conn.close()
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    @tool(
        description="Get detailed information about a single product by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "Product ID",
                },
            },
            "required": ["product_id"],
        },
    )
    def get_product_info(self, product_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT id, sku, name, category, current_price, list_price, status "
            "FROM products WHERE id = ?",
            (product_id,),
        )
        row = c.fetchone()
        conn.close()
        if not row:
            return {"error": "Product not found"}
        return {
            "id": row[0], "sku": row[1], "name": row[2], "category": row[3],
            "current_price": row[4], "list_price": row[5], "status": row[6],
        }

    @tool(
        description="Get the most recent competitor prices for a given product. Returns the latest scraped price from each competitor that has data for this product.",
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "Product ID",
                },
            },
            "required": ["product_id"],
        },
    )
    def get_competitor_prices(self, product_id: int) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """
            SELECT cp.competitor_name, cp.price, cp.in_stock, cp.scrape_date
            FROM competitor_prices cp
            INNER JOIN (
                SELECT competitor_name, MAX(scrape_date) as max_date
                FROM competitor_prices
                WHERE product_id = ?
                GROUP BY competitor_name
            ) latest ON cp.competitor_name = latest.competitor_name
                     AND cp.scrape_date = latest.max_date
            WHERE cp.product_id = ?
            ORDER BY cp.competitor_name
            """,
            (product_id, product_id),
        )
        results = [
            {
                "competitor_name": r[0],
                "price": r[1],
                "in_stock": bool(r[2]),
                "scrape_date": r[3],
            }
            for r in c.fetchall()
        ]
        conn.close()
        return results

    @tool(
        description="Get supplier cost information for a given product. Returns all supplier quotes.",
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "Product ID",
                },
            },
            "required": ["product_id"],
        },
    )
    def get_supplier_costs(self, product_id: int) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT supplier_name, unit_cost, moq, lead_time_days, valid_until "
            "FROM supplier_costs WHERE product_id = ? ORDER BY unit_cost",
            (product_id,),
        )
        results = [
            {
                "supplier_name": r[0],
                "unit_cost": r[1],
                "moq": r[2],
                "lead_time_days": r[3],
                "valid_until": r[4],
            }
            for r in c.fetchall()
        ]
        conn.close()
        return results

    @tool(
        description="Get conversion history for a product over a specified number of recent days. Returns daily page views, add-to-cart counts, purchases, and revenue.",
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "Product ID",
                },
                "days": {
                    "type": "integer",
                    "description": "Number of recent days to retrieve (max 60)",
                },
            },
            "required": ["product_id", "days"],
        },
    )
    def get_conversion_history(self, product_id: int, days: int) -> List[Dict]:
        days = min(days, 60)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT date, page_views, add_to_cart, purchases, revenue "
            "FROM conversion_history WHERE product_id = ? "
            "ORDER BY date DESC LIMIT ?",
            (product_id, days),
        )
        results = [
            {
                "date": r[0],
                "page_views": r[1],
                "add_to_cart": r[2],
                "purchases": r[3],
                "revenue": r[4],
            }
            for r in c.fetchall()
        ]
        conn.close()
        return results

    @tool(
        description="Search products by name keyword. Returns matching products (max 15 results).",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keyword to match against product names",
                },
            },
            "required": ["query"],
        },
    )
    def search_products(self, query: str) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT id, sku, name, category, current_price, status "
            "FROM products WHERE name LIKE ? ORDER BY id LIMIT 15",
            (f"%{query}%",),
        )
        results = [
            {
                "id": r[0], "sku": r[1], "name": r[2],
                "category": r[3], "current_price": r[4], "status": r[5],
            }
            for r in c.fetchall()
        ]
        conn.close()
        return results

    # -----------------------------------------------------------------------
    # Ground-truth computation (used by step and verify)
    # -----------------------------------------------------------------------

    def _load_config(self):
        """Load workspace config files."""
        # competitor tiers
        with open(os.path.join(self.workspace, "competitor_tiers.json")) as f:
            competitor_tiers = json.load(f)

        # category config
        category_config = {}
        with open(os.path.join(self.workspace, "category_config.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                category_config[row["category"]] = {
                    "min_margin_pct": float(row["min_margin_pct"]),
                    "allow_promotion": row["allow_promotion"].strip().lower() == "yes",
                    "priority": int(row["priority"]),
                }

        # pricing policy
        pricing_policy = {}
        with open(os.path.join(self.workspace, "pricing_policy.yaml")) as f:
            for line in f:
                line = line.strip()
                if ":" in line and not line.startswith("#"):
                    key, val = line.split(":", 1)
                    val = val.strip()
                    try:
                        val = float(val)
                        if val == int(val):
                            val = int(val)
                    except ValueError:
                        pass
                    pricing_policy[key.strip()] = val

        return competitor_tiers, category_config, pricing_policy

    def _load_price_flags(self):
        """Load price flags from daily scrape CSV files in workspace.
        Returns dict: (product_sku, competitor_name) -> most recent flag."""
        flags = {}  # (sku, comp) -> (date_str, flag)
        for fname in sorted(os.listdir(self.workspace)):
            if not fname.startswith("daily_scrape_") or not fname.endswith(".csv"):
                continue
            # Extract date from filename daily_scrape_YYYYMMDD.csv
            date_str = fname.replace("daily_scrape_", "").replace(".csv", "")
            with open(os.path.join(self.workspace, fname)) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (row["product_sku"], row["competitor_name"])
                    existing = flags.get(key)
                    if existing is None or date_str > existing[0]:
                        flags[key] = (date_str, row["price_flag"])
        # Return just the flag
        return {k: v[1] for k, v in flags.items()}

    def _compute_conversion_trend(self, product_id, pricing_policy):
        """Compute conversion trend for a product."""
        lookback = pricing_policy.get("conversion_lookback_days", 14)
        split_day = pricing_policy.get("comparison_split_day", 7)
        decline_threshold = pricing_policy.get("conversion_decline_threshold", 0.10)

        history = self.tools["get_conversion_history"](product_id=product_id, days=lookback)
        if len(history) < 4:
            return "stable"

        # history is sorted desc by date
        # recent = last split_day days (first split_day entries)
        # earlier = previous split_day days (next split_day entries)
        recent = history[:split_day]
        earlier = history[split_day:2 * split_day]

        if not recent or not earlier:
            return "stable"

        recent_avg = sum(r["purchases"] for r in recent) / len(recent)
        earlier_avg = sum(r["purchases"] for r in earlier) / len(earlier)

        if earlier_avg == 0:
            return "stable"

        ratio = recent_avg / earlier_avg
        if ratio < (1.0 - decline_threshold):
            return "declining"
        elif ratio > (1.0 + decline_threshold):
            return "improving"
        else:
            return "stable"

    def _compute_ground_truth(self):
        """Compute the full ground truth alert list."""
        competitor_tiers, category_config, pricing_policy = self._load_config()
        price_flags = self._load_price_flags()

        # Get all active products
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT id, sku, name, category, current_price FROM products "
            "WHERE status = 'active' ORDER BY id"
        )
        active_products = [
            {"id": r[0], "sku": r[1], "name": r[2], "category": r[3], "current_price": r[4]}
            for r in c.fetchall()
        ]
        conn.close()

        alerts = []
        for product in active_products:
            pid = product["id"]
            sku = product["sku"]
            our_price = product["current_price"]
            category = product["category"]

            # Get competitor prices
            comp_prices = self.tools["get_competitor_prices"](product_id=pid)

            # Get supplier costs
            supplier_costs = self.tools["get_supplier_costs"](product_id=pid)
            best_cost = min((s["unit_cost"] for s in supplier_costs), default=our_price)

            # Filter competitor prices
            qualifying = []
            for cp in comp_prices:
                comp_name = cp["competitor_name"]
                tier = competitor_tiers.get(comp_name, "C")
                if tier == "C":
                    continue
                if not cp["in_stock"]:
                    continue
                # Check price flag from workspace
                flag = price_flags.get((sku, comp_name), "normal")
                if flag in ("clearance", "bundle"):
                    continue
                qualifying.append(cp)

            # Conversion trend
            conv_trend = self._compute_conversion_trend(pid, pricing_policy)

            # Current margin
            current_margin = round((our_price - best_cost) / our_price * 100, 2) if our_price > 0 else 0.0

            cat_config = category_config.get(category, {"min_margin_pct": 20.0, "allow_promotion": False})
            min_margin = cat_config["min_margin_pct"]
            allow_promo = cat_config["allow_promotion"]

            if not qualifying:
                alerts.append({
                    "product_sku": sku,
                    "product_name": product["name"],
                    "category": category,
                    "our_price": our_price,
                    "best_competitor_price": "N/A",
                    "best_competitor_name": "N/A",
                    "supplier_cost": best_cost,
                    "current_margin_pct": current_margin,
                    "adjusted_margin_pct": "N/A",
                    "conversion_trend": conv_trend,
                    "action": "hold",
                    "reason": "no qualifying competitor prices",
                })
                continue

            # Find lowest qualifying price
            best_comp = min(qualifying, key=lambda x: x["price"])
            best_price = best_comp["price"]
            best_name = best_comp["competitor_name"]

            if best_price >= our_price:
                alerts.append({
                    "product_sku": sku,
                    "product_name": product["name"],
                    "category": category,
                    "our_price": our_price,
                    "best_competitor_price": best_price,
                    "best_competitor_name": best_name,
                    "supplier_cost": best_cost,
                    "current_margin_pct": current_margin,
                    "adjusted_margin_pct": round((best_price - best_cost) / best_price * 100, 2) if best_price > 0 else 0.0,
                    "conversion_trend": conv_trend,
                    "action": "hold",
                    "reason": "price competitive",
                })
                continue

            # Competitor is cheaper
            adjusted_margin = round((best_price - best_cost) / best_price * 100, 2) if best_price > 0 else 0.0

            if adjusted_margin >= min_margin:
                action = "match"
                reason = "margin preserved after matching"
            elif conv_trend == "declining" and allow_promo:
                action = "promote"
                reason = "margin squeeze with declining conversion"
            else:
                action = "hold"
                reason = "insufficient margin to match"

            alerts.append({
                "product_sku": sku,
                "product_name": product["name"],
                "category": category,
                "our_price": our_price,
                "best_competitor_price": best_price,
                "best_competitor_name": best_name,
                "supplier_cost": best_cost,
                "current_margin_pct": current_margin,
                "adjusted_margin_pct": adjusted_margin,
                "conversion_trend": conv_trend,
                "action": action,
                "reason": reason,
            })

        # Sort by category ASC, then price gap DESC
        def sort_key(a):
            if a["best_competitor_price"] == "N/A":
                gap = 0.0
            else:
                gap = a["our_price"] - a["best_competitor_price"]
            return (a["category"], -gap)

        alerts.sort(key=sort_key)
        return alerts

    # -----------------------------------------------------------------------
    # step
    # -----------------------------------------------------------------------

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
        gt_by_sku = {a["product_sku"]: a for a in ground_truth}

        criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: price_alerts.csv exists with correct columns (10 pts) ---
        c1_max = 10
        max_score += c1_max
        alerts_path = os.path.join(self.workspace, "price_alerts.csv")
        expected_cols = [
            "product_sku", "product_name", "category", "our_price",
            "best_competitor_price", "best_competitor_name", "supplier_cost",
            "current_margin_pct", "adjusted_margin_pct", "conversion_trend",
            "action", "reason",
        ]
        if os.path.exists(alerts_path):
            with open(alerts_path) as f:
                reader = csv.DictReader(f)
                actual_cols = reader.fieldnames or []
                submitted_rows = list(reader)
            if all(c in actual_cols for c in expected_cols):
                criteria["file_format"] = {"passed": True, "score": c1_max, "max_score": c1_max}
                total_score += c1_max
            else:
                missing = [c for c in expected_cols if c not in actual_cols]
                criteria["file_format"] = {
                    "passed": False, "score": 0, "max_score": c1_max,
                    "reason": f"Missing columns: {missing}",
                }
        else:
            submitted_rows = []
            criteria["file_format"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "price_alerts.csv not found",
            }

        # --- Criterion 2: All active products included (15 pts) ---
        c2_max = 15
        max_score += c2_max
        submitted_skus = set()
        submitted_by_sku = {}
        for row in submitted_rows:
            sku = row.get("product_sku", "").strip()
            if sku:
                submitted_skus.add(sku)
                submitted_by_sku[sku] = row
        gt_skus = set(gt_by_sku.keys())
        if submitted_skus == gt_skus:
            criteria["product_coverage"] = {"passed": True, "score": c2_max, "max_score": c2_max}
            total_score += c2_max
        else:
            missing_count = len(gt_skus - submitted_skus)
            extra_count = len(submitted_skus - gt_skus)
            coverage = len(gt_skus & submitted_skus) / len(gt_skus) if gt_skus else 0
            earned = round(c2_max * coverage)
            criteria["product_coverage"] = {
                "passed": False, "score": earned, "max_score": c2_max,
                "reason": f"Missing {missing_count} products, {extra_count} extra",
            }
            total_score += earned

        # --- Criterion 3: Correct actions (25 pts) ---
        c3_max = 25
        max_score += c3_max
        correct_actions = 0
        total_compared = 0
        for sku, gt in gt_by_sku.items():
            if sku in submitted_by_sku:
                total_compared += 1
                if submitted_by_sku[sku].get("action", "").strip().lower() == gt["action"]:
                    correct_actions += 1
        if total_compared > 0:
            action_accuracy = correct_actions / total_compared
        else:
            action_accuracy = 0
        earned3 = round(c3_max * action_accuracy)
        criteria["action_accuracy"] = {
            "passed": action_accuracy >= 0.99,
            "score": earned3,
            "max_score": c3_max,
            "reason": f"{correct_actions}/{total_compared} correct" if action_accuracy < 0.99 else "",
        }
        total_score += earned3

        # --- Criterion 4: Correct competitor price and name (20 pts) ---
        c4_max = 20
        max_score += c4_max
        correct_comp = 0
        comp_compared = 0
        for sku, gt in gt_by_sku.items():
            if sku not in submitted_by_sku:
                continue
            sub = submitted_by_sku[sku]
            gt_price = gt["best_competitor_price"]
            sub_price = sub.get("best_competitor_price", "").strip()
            gt_name = gt["best_competitor_name"]
            sub_name = sub.get("best_competitor_name", "").strip()
            comp_compared += 1
            if gt_price == "N/A":
                if sub_price == "N/A":
                    correct_comp += 1
            else:
                try:
                    if abs(float(sub_price) - float(gt_price)) < 0.015 and sub_name == gt_name:
                        correct_comp += 1
                except (ValueError, TypeError):
                    pass
        if comp_compared > 0:
            comp_accuracy = correct_comp / comp_compared
        else:
            comp_accuracy = 0
        earned4 = round(c4_max * comp_accuracy)
        criteria["competitor_prices"] = {
            "passed": comp_accuracy >= 0.99,
            "score": earned4,
            "max_score": c4_max,
            "reason": f"{correct_comp}/{comp_compared} correct" if comp_accuracy < 0.99 else "",
        }
        total_score += earned4

        # --- Criterion 5: Correct margin calculations (15 pts) ---
        c5_max = 15
        max_score += c5_max
        correct_margins = 0
        margin_compared = 0
        for sku, gt in gt_by_sku.items():
            if sku not in submitted_by_sku:
                continue
            sub = submitted_by_sku[sku]
            margin_compared += 1
            try:
                sub_cur = float(sub.get("current_margin_pct", ""))
                gt_cur = float(gt["current_margin_pct"])
                cur_ok = abs(sub_cur - gt_cur) < 0.5
            except (ValueError, TypeError):
                cur_ok = False

            gt_adj = gt["adjusted_margin_pct"]
            sub_adj = sub.get("adjusted_margin_pct", "").strip()
            if gt_adj == "N/A":
                adj_ok = sub_adj == "N/A"
            else:
                try:
                    adj_ok = abs(float(sub_adj) - float(gt_adj)) < 0.5
                except (ValueError, TypeError):
                    adj_ok = False

            if cur_ok and adj_ok:
                correct_margins += 1

        if margin_compared > 0:
            margin_accuracy = correct_margins / margin_compared
        else:
            margin_accuracy = 0
        earned5 = round(c5_max * margin_accuracy)
        criteria["margin_calculations"] = {
            "passed": margin_accuracy >= 0.99,
            "score": earned5,
            "max_score": c5_max,
            "reason": f"{correct_margins}/{margin_compared} correct" if margin_accuracy < 0.99 else "",
        }
        total_score += earned5

        # --- Criterion 6: Response summary statistics (15 pts) ---
        c6_max = 15
        max_score += c6_max
        gt_total = len(ground_truth)
        gt_match = sum(1 for a in ground_truth if a["action"] == "match")
        gt_hold = sum(1 for a in ground_truth if a["action"] == "hold")
        gt_promote = sum(1 for a in ground_truth if a["action"] == "promote")

        action_lower = action.lower() if action else ""
        summary_checks = 0
        summary_total = 4

        if str(gt_total) in action_lower:
            summary_checks += 1
        if f"match" in action_lower and str(gt_match) in action_lower:
            summary_checks += 1
        if f"hold" in action_lower and str(gt_hold) in action_lower:
            summary_checks += 1
        if f"promote" in action_lower and str(gt_promote) in action_lower:
            summary_checks += 1

        earned6 = round(c6_max * summary_checks / summary_total)
        criteria["response_summary"] = {
            "passed": summary_checks == summary_total,
            "score": earned6,
            "max_score": c6_max,
            "reason": f"{summary_checks}/{summary_total} summary items found" if summary_checks < summary_total else "",
        }
        total_score += earned6

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, info

    # -----------------------------------------------------------------------
    # verify
    # -----------------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import os, csv, json

        # --- Step 1: Read workspace config files ---
        with open(os.path.join(self.workspace, "competitor_tiers.json")) as f:
            competitor_tiers = json.load(f)

        category_config = {}
        with open(os.path.join(self.workspace, "category_config.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                category_config[row["category"]] = {
                    "min_margin_pct": float(row["min_margin_pct"]),
                    "allow_promotion": row["allow_promotion"].strip().lower() == "yes",
                }

        pricing_policy = {}
        with open(os.path.join(self.workspace, "pricing_policy.yaml")) as f:
            for line in f:
                line = line.strip()
                if ":" in line and not line.startswith("#"):
                    key, val = line.split(":", 1)
                    val = val.strip()
                    try:
                        val = float(val)
                        if val == int(val):
                            val = int(val)
                    except ValueError:
                        pass
                    pricing_policy[key.strip()] = val

        lookback = pricing_policy.get("conversion_lookback_days", 14)
        split_day = pricing_policy.get("comparison_split_day", 7)
        decline_threshold = pricing_policy.get("conversion_decline_threshold", 0.10)

        # --- Step 2: Read price flags from workspace scrape files ---
        price_flags = {}
        for fname in sorted(os.listdir(self.workspace)):
            if not fname.startswith("daily_scrape_") or not fname.endswith(".csv"):
                continue
            date_str = fname.replace("daily_scrape_", "").replace(".csv", "")
            with open(os.path.join(self.workspace, fname)) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (row["product_sku"], row["competitor_name"])
                    existing = price_flags.get(key)
                    if existing is None or date_str > existing[0]:
                        price_flags[key] = (date_str, row["price_flag"])
        price_flags_final = {k: v[1] for k, v in price_flags.items()}

        # --- Step 3: Use tools to gather product data ---
        tool_call_count = 0

        categories = self.tools["list_categories"]()
        tool_call_count += 1

        all_products = []
        for cat in categories:
            page = 1
            while True:
                result = self.tools["list_products"](category=cat, page=page, page_size=20)
                tool_call_count += 1
                all_products.extend(result["items"])
                if page * 20 >= result["total"]:
                    break
                page += 1

        # Filter active products
        active_products = [p for p in all_products if p["status"] == "active"]

        alerts = []
        for product in active_products:
            pid = product["id"]
            sku = product["sku"]
            our_price = product["current_price"]

            # Get full product info for category
            pinfo = self.tools["get_product_info"](product_id=pid)
            tool_call_count += 1
            category = pinfo["category"]
            name = pinfo["name"]

            # Get competitor prices
            comp_prices = self.tools["get_competitor_prices"](product_id=pid)
            tool_call_count += 1

            # Get supplier costs
            supp_costs = self.tools["get_supplier_costs"](product_id=pid)
            tool_call_count += 1
            best_cost = min((s["unit_cost"] for s in supp_costs), default=our_price)

            # Get conversion history
            conv_history = self.tools["get_conversion_history"](product_id=pid, days=lookback)
            tool_call_count += 1

            # Compute conversion trend
            recent = conv_history[:split_day]
            earlier = conv_history[split_day:2 * split_day]
            if recent and earlier:
                recent_avg = sum(r["purchases"] for r in recent) / len(recent)
                earlier_avg = sum(r["purchases"] for r in earlier) / len(earlier)
                if earlier_avg > 0:
                    ratio = recent_avg / earlier_avg
                    if ratio < (1.0 - decline_threshold):
                        conv_trend = "declining"
                    elif ratio > (1.0 + decline_threshold):
                        conv_trend = "improving"
                    else:
                        conv_trend = "stable"
                else:
                    conv_trend = "stable"
            else:
                conv_trend = "stable"

            # Filter competitors
            qualifying = []
            for cp in comp_prices:
                comp_name = cp["competitor_name"]
                tier = competitor_tiers.get(comp_name, "C")
                if tier == "C":
                    continue
                if not cp["in_stock"]:
                    continue
                flag = price_flags_final.get((sku, comp_name), "normal")
                if flag in ("clearance", "bundle"):
                    continue
                qualifying.append(cp)

            current_margin = round((our_price - best_cost) / our_price * 100, 2) if our_price > 0 else 0.0

            cat_cfg = category_config.get(category, {"min_margin_pct": 20.0, "allow_promotion": False})
            min_margin = cat_cfg["min_margin_pct"]
            allow_promo = cat_cfg["allow_promotion"]

            if not qualifying:
                alerts.append({
                    "product_sku": sku,
                    "product_name": name,
                    "category": category,
                    "our_price": our_price,
                    "best_competitor_price": "N/A",
                    "best_competitor_name": "N/A",
                    "supplier_cost": best_cost,
                    "current_margin_pct": current_margin,
                    "adjusted_margin_pct": "N/A",
                    "conversion_trend": conv_trend,
                    "action": "hold",
                    "reason": "no qualifying competitor prices",
                })
                continue

            best_comp = min(qualifying, key=lambda x: x["price"])
            best_price = best_comp["price"]
            best_name = best_comp["competitor_name"]

            if best_price >= our_price:
                adjusted_margin = round((best_price - best_cost) / best_price * 100, 2) if best_price > 0 else 0.0
                alerts.append({
                    "product_sku": sku,
                    "product_name": name,
                    "category": category,
                    "our_price": our_price,
                    "best_competitor_price": best_price,
                    "best_competitor_name": best_name,
                    "supplier_cost": best_cost,
                    "current_margin_pct": current_margin,
                    "adjusted_margin_pct": adjusted_margin,
                    "conversion_trend": conv_trend,
                    "action": "hold",
                    "reason": "price competitive",
                })
                continue

            adjusted_margin = round((best_price - best_cost) / best_price * 100, 2) if best_price > 0 else 0.0

            if adjusted_margin >= min_margin:
                action_val = "match"
                reason_val = "margin preserved after matching"
            elif conv_trend == "declining" and allow_promo:
                action_val = "promote"
                reason_val = "margin squeeze with declining conversion"
            else:
                action_val = "hold"
                reason_val = "insufficient margin to match"

            alerts.append({
                "product_sku": sku,
                "product_name": name,
                "category": category,
                "our_price": our_price,
                "best_competitor_price": best_price,
                "best_competitor_name": best_name,
                "supplier_cost": best_cost,
                "current_margin_pct": current_margin,
                "adjusted_margin_pct": adjusted_margin,
                "conversion_trend": conv_trend,
                "action": action_val,
                "reason": reason_val,
            })

        # Sort by category ASC, then price gap DESC
        def sort_key(a):
            if a["best_competitor_price"] == "N/A":
                gap = 0.0
            else:
                gap = a["our_price"] - float(a["best_competitor_price"])
            return (a["category"], -gap)

        alerts.sort(key=sort_key)

        # --- Step 4: Write price_alerts.csv ---
        fieldnames = [
            "product_sku", "product_name", "category", "our_price",
            "best_competitor_price", "best_competitor_name", "supplier_cost",
            "current_margin_pct", "adjusted_margin_pct", "conversion_trend",
            "action", "reason",
        ]
        alerts_path = os.path.join(self.workspace, "price_alerts.csv")
        with open(alerts_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in alerts:
                writer.writerow(row)

        # --- Step 5: Build action summary ---
        total_products = len(alerts)
        match_count = sum(1 for a in alerts if a["action"] == "match")
        hold_count = sum(1 for a in alerts if a["action"] == "hold")
        promote_count = sum(1 for a in alerts if a["action"] == "promote")

        # Top 5 by price gap
        with_gap = []
        for a in alerts:
            if a["best_competitor_price"] != "N/A":
                gap = a["our_price"] - float(a["best_competitor_price"])
                if gap > 0:
                    with_gap.append((a, gap))
        with_gap.sort(key=lambda x: -x[1])
        top5 = with_gap[:5]

        action_text = (
            f"Price adjustment alert analysis complete. "
            f"Analyzed {total_products} active products across all categories. "
            f"Results: {match_count} match, {hold_count} hold, {promote_count} promote. "
            f"The alert list has been saved to price_alerts.csv.\n\n"
            f"Top 5 products by price gap:\n"
        )
        for a, gap in top5:
            action_text += (
                f"- {a['product_sku']} ({a['product_name']}): "
                f"our price {a['our_price']}, competitor {a['best_competitor_price']}, "
                f"gap {round(gap, 2)}, action: {a['action']}\n"
            )

        assert tool_call_count >= 15, f"Tool call count too low: {tool_call_count}"

        return self.step(action_text)
