"""
Task environment for e-commerce flash sale pricing optimization.
"""

import sqlite3
import os
import json
import csv
import math
import glob
import yaml
import pandas as pd
import numpy as np
from typing import Tuple, Dict, List, Any


# --- Decorator for tool registration ---
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

    # ----------------------------------------------------------------
    # Tool methods
    # ----------------------------------------------------------------

    @tool(
        description=(
            "List products in the catalog. Returns product_id, product_name, "
            "and category for each product. Results are paginated."
        ),
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Optional category filter. If omitted, returns all categories.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def list_products(self, category: str = None, page: int = 1, page_size: int = 20):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if category:
            cursor.execute(
                "SELECT product_id, product_name, category FROM products "
                "WHERE category = ? ORDER BY product_id",
                (category,),
            )
        else:
            cursor.execute(
                "SELECT product_id, product_name, category FROM products ORDER BY product_id"
            )
        all_rows = cursor.fetchall()
        conn.close()
        total = len(all_rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = all_rows[start:end]
        return {
            "products": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": end < total,
        }

    @tool(
        description=(
            "Get full details for a single product by its product_id. "
            "Returns product_id, product_name, category, base_price, "
            "cost_price, brand, and supplier."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product identifier, e.g. 'P0001'.",
                },
            },
            "required": ["product_id"],
        },
    )
    def get_product_details(self, product_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products WHERE product_id = ?", (product_id,))
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Product '{product_id}' not found."}
        return dict(row)

    @tool(
        description=(
            "Retrieve all competitor price entries for a given product. "
            "Each entry includes competitor_name, competitor_price, "
            "price_timestamp, and in_stock (1 = in stock, 0 = out of stock)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product identifier.",
                },
            },
            "required": ["product_id"],
        },
    )
    def get_competitor_prices(self, product_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT competitor_name, competitor_price, price_timestamp, in_stock "
            "FROM competitor_prices WHERE product_id = ? ORDER BY competitor_name",
            (product_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return {"product_id": product_id, "competitors": [dict(r) for r in rows]}

    @tool(
        description=(
            "Get inventory status for a product across all warehouses. "
            "Each entry includes warehouse_id, current_stock, "
            "monthly_units_sold, and last_restock_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product identifier.",
                },
            },
            "required": ["product_id"],
        },
    )
    def get_inventory_status(self, product_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT warehouse_id, current_stock, monthly_units_sold, last_restock_date "
            "FROM inventory WHERE product_id = ? ORDER BY warehouse_id",
            (product_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return {"product_id": product_id, "warehouses": [dict(r) for r in rows]}

    @tool(
        description=(
            "List customer segments with basic information. "
            "Returns segment_id, segment_name, and avg_ltv_score. "
            "Results are paginated."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def list_customer_segments(self, page: int = 1, page_size: int = 20):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT segment_id, segment_name, avg_ltv_score "
            "FROM customer_segments ORDER BY segment_id"
        )
        all_rows = cursor.fetchall()
        conn.close()
        total = len(all_rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = all_rows[start:end]
        return {
            "segments": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": end < total,
        }

    @tool(
        description=(
            "Get full details for a single customer segment by its segment_id. "
            "Returns segment_id, segment_name, member_count, avg_ltv_score, "
            "avg_order_value, and churn_risk."
        ),
        parameters={
            "type": "object",
            "properties": {
                "segment_id": {
                    "type": "string",
                    "description": "The segment identifier, e.g. 'SEG001'.",
                },
            },
            "required": ["segment_id"],
        },
    )
    def get_segment_details(self, segment_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM customer_segments WHERE segment_id = ?", (segment_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Segment '{segment_id}' not found."}
        return dict(row)

    # ----------------------------------------------------------------
    # Ground-truth computation (used by step)
    # ----------------------------------------------------------------

    def _compute_ground_truth(self):
        """Compute the expected pricing schedule from DB + workspace files."""
        conn = sqlite3.connect(self.db_path)

        # --- Read workspace configs ---
        with open(os.path.join(self.workspace, "campaign_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "discount_tiers.json")) as f:
            tiers_data = json.load(f)

        comp_rep = {}
        with open(os.path.join(self.workspace, "competitor_reputation.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                comp_rep[row["competitor_name"]] = float(row["reputation_weight"])

        with open(os.path.join(self.workspace, "warehouse_config.yaml")) as f:
            wh_config = yaml.safe_load(f)
        wh_priority = {
            k: v["priority_weight"] for k, v in wh_config["warehouses"].items()
        }

        eligible_cats = set(config["eligible_categories"])
        min_margin_pct = config["min_margin_pct"]
        max_discount_pct = config["max_discount_pct"]
        weights = config["scoring_weights"]
        tier_list = tiers_data["tiers"]

        # --- Load DB tables ---
        products_df = pd.read_sql("SELECT * FROM products", conn)
        comp_prices_df = pd.read_sql("SELECT * FROM competitor_prices", conn)
        inv_df = pd.read_sql("SELECT * FROM inventory", conn)
        segments_df = pd.read_sql("SELECT segment_id, avg_ltv_score FROM customer_segments", conn)
        conn.close()

        seg_ltv = dict(zip(segments_df["segment_id"], segments_df["avg_ltv_score"]))

        # --- Load clickstream ---
        cs_files = sorted(glob.glob(os.path.join(self.workspace, "clickstream_day_*.csv")))
        if cs_files:
            all_clicks = pd.concat([pd.read_csv(f) for f in cs_files], ignore_index=True)
        else:
            all_clicks = pd.DataFrame(
                columns=["session_id", "product_id", "customer_segment_id", "event_type", "timestamp"]
            )

        # --- Eligible products ---
        eligible = products_df[products_df["category"].isin(eligible_cats)].copy()
        eligible = eligible.set_index("product_id")

        # --- Raw engagement ---
        event_weights_map = {"page_view": 1, "click": 2, "add_to_cart": 3, "purchase": 5}
        if not all_clicks.empty:
            all_clicks["event_weight"] = all_clicks["event_type"].map(event_weights_map).fillna(0)
            engagement_raw = all_clicks.groupby("product_id")["event_weight"].sum()
        else:
            engagement_raw = pd.Series(dtype=float)
        eligible["raw_engagement"] = engagement_raw.reindex(eligible.index, fill_value=0.0)

        # --- Raw price competitiveness ---
        in_stock_comp = comp_prices_df[comp_prices_df["in_stock"] == 1].copy()
        in_stock_comp["rep_weight"] = in_stock_comp["competitor_name"].map(comp_rep).fillna(0)

        def _weighted_avg_price(group):
            w = group["rep_weight"]
            p = group["competitor_price"]
            total_w = w.sum()
            if total_w == 0:
                return 0.0
            return (p * w).sum() / total_w

        if not in_stock_comp.empty:
            weighted_comp = in_stock_comp.groupby("product_id").apply(_weighted_avg_price)
        else:
            weighted_comp = pd.Series(dtype=float)

        raw_comp = []
        for pid in eligible.index:
            bp = eligible.loc[pid, "base_price"]
            if pid in weighted_comp.index and weighted_comp[pid] > 0:
                val = (bp - weighted_comp[pid]) / bp * 100
            else:
                val = 0.0
            raw_comp.append(val)
        eligible["raw_competitiveness"] = raw_comp

        # --- Raw inventory urgency ---
        inv_df_copy = inv_df.copy()
        inv_df_copy["priority"] = inv_df_copy["warehouse_id"].map(wh_priority).fillna(0)
        inv_df_copy["days_of_supply"] = inv_df_copy["current_stock"] / (
            inv_df_copy["monthly_units_sold"] / 30.0
        )

        def _weighted_avg_dos(group):
            w = group["priority"]
            d = group["days_of_supply"]
            total_w = w.sum()
            if total_w == 0:
                return 0.0
            return (d * w).sum() / total_w

        if not inv_df_copy.empty:
            inv_urgency = inv_df_copy.groupby("product_id").apply(_weighted_avg_dos)
        else:
            inv_urgency = pd.Series(dtype=float)
        eligible["raw_urgency"] = inv_urgency.reindex(eligible.index, fill_value=0.0)

        # --- Raw segment value ---
        if not all_clicks.empty:
            all_clicks["ltv"] = all_clicks["customer_segment_id"].map(seg_ltv).fillna(0)
            seg_val_raw = all_clicks.groupby("product_id")["ltv"].mean()
        else:
            seg_val_raw = pd.Series(dtype=float)
        eligible["raw_segment_value"] = seg_val_raw.reindex(eligible.index, fill_value=0.0)

        # --- Min-max normalization ---
        def _minmax(series):
            mn, mx = series.min(), series.max()
            if mn == mx:
                return pd.Series(50.0, index=series.index)
            return (series - mn) / (mx - mn) * 100.0

        eligible["norm_engagement"] = _minmax(eligible["raw_engagement"])
        eligible["norm_competitiveness"] = _minmax(eligible["raw_competitiveness"])
        eligible["norm_urgency"] = _minmax(eligible["raw_urgency"])
        eligible["norm_segment_value"] = _minmax(eligible["raw_segment_value"])

        # --- Composite score ---
        eligible["composite_score"] = (
            weights["engagement"] * eligible["norm_engagement"]
            + weights["price_competitiveness"] * eligible["norm_competitiveness"]
            + weights["inventory_urgency"] * eligible["norm_urgency"]
            + weights["segment_value"] * eligible["norm_segment_value"]
        )

        # --- Tier assignment ---
        def _assign_tier(score):
            for t in tier_list:
                if score >= t["min_score"]:
                    return t["tier_name"], t["base_discount_pct"]
            return "NoDiscount", 0

        tier_info = eligible["composite_score"].apply(lambda s: _assign_tier(s))
        eligible["discount_tier"] = [t[0] for t in tier_info]
        eligible["tier_discount"] = [t[1] for t in tier_info]

        # --- Margin enforcement ---
        min_margin_factor = 1.0 - min_margin_pct / 100.0  # e.g. 0.85

        def _cap_discount(row):
            discount = min(row["tier_discount"], max_discount_pct)
            sale_price = round(row["base_price"] * (1 - discount / 100.0), 2)
            min_sp = row["cost_price"] / min_margin_factor
            if sale_price >= min_sp:
                return int(discount)
            # Find largest whole-number discount that satisfies margin
            max_d = math.floor(
                (1.0 - row["cost_price"] / (row["base_price"] * min_margin_factor)) * 100.0
            )
            if max_d < 1:
                return -1  # exclude
            return max_d

        eligible["discount_pct"] = eligible.apply(_cap_discount, axis=1)

        # Remove products that cannot sustain any discount
        eligible = eligible[eligible["discount_pct"] >= 0].copy()

        # Compute final sale price
        eligible["sale_price"] = (
            eligible["base_price"] * (1 - eligible["discount_pct"] / 100.0)
        ).round(2)
        eligible["composite_score"] = eligible["composite_score"].round(2)
        eligible["discount_pct"] = eligible["discount_pct"].astype(int)

        # Sort by composite_score desc, then product_id asc
        eligible = eligible.sort_values(
            ["composite_score", "product_id_sort"],
            ascending=[False, True],
            key=lambda col: col if col.name != "product_id_sort" else col,
        ) if "product_id_sort" in eligible.columns else eligible.reset_index().sort_values(
            ["composite_score", "product_id"], ascending=[False, True]
        )

        # Select final columns
        if "product_id" not in eligible.columns:
            eligible = eligible.reset_index()

        result = eligible[
            [
                "product_id", "product_name", "category", "base_price",
                "cost_price", "composite_score", "discount_tier",
                "discount_pct", "sale_price",
            ]
        ].copy()

        return result

    # ----------------------------------------------------------------
    # step – evaluation
    # ----------------------------------------------------------------

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
        criteria = {}
        gt = self._compute_ground_truth()

        # ---- Criterion 1: Output file exists and has correct columns (10 pts) ----
        schedule_path = os.path.join(self.workspace, "pricing_schedule.csv")
        expected_cols = [
            "product_id", "product_name", "category", "base_price",
            "cost_price", "composite_score", "discount_tier",
            "discount_pct", "sale_price",
        ]
        c1_score = 0
        c1_max = 10
        agent_df = None
        if os.path.exists(schedule_path):
            try:
                agent_df = pd.read_csv(schedule_path)
                agent_cols = list(agent_df.columns)
                if agent_cols == expected_cols:
                    c1_score = 10
                else:
                    # Partial credit: columns present but wrong order
                    if set(agent_cols) == set(expected_cols):
                        c1_score = 5
            except Exception:
                pass
        criteria["output_file_format"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": "" if c1_score == c1_max else "pricing_schedule.csv missing, unreadable, or has incorrect columns/order.",
        }

        if agent_df is None or agent_df.empty:
            # Cannot evaluate further
            for name, mx in [
                ("eligible_products", 15),
                ("composite_scores", 20),
                ("discount_tiers", 15),
                ("margin_enforcement", 15),
                ("sort_order", 10),
                ("response_summary", 15),
            ]:
                criteria[name] = {
                    "passed": False,
                    "score": 0,
                    "max_score": mx,
                    "reason": "No valid output file to evaluate.",
                }
            total = c1_score
            max_score = c1_max + 15 + 20 + 15 + 15 + 10 + 15
            return total / max_score, {
                "eval_criteria": criteria,
                "total_score": total,
                "max_score": max_score,
            }

        # Normalize types for comparison
        try:
            agent_df["product_id"] = agent_df["product_id"].astype(str)
            agent_df["composite_score"] = pd.to_numeric(agent_df["composite_score"], errors="coerce")
            agent_df["discount_pct"] = pd.to_numeric(agent_df["discount_pct"], errors="coerce").astype("Int64")
            agent_df["sale_price"] = pd.to_numeric(agent_df["sale_price"], errors="coerce")
            agent_df["base_price"] = pd.to_numeric(agent_df["base_price"], errors="coerce")
            agent_df["cost_price"] = pd.to_numeric(agent_df["cost_price"], errors="coerce")
        except Exception:
            pass

        gt_ids = set(gt["product_id"].tolist())
        agent_ids = set(agent_df["product_id"].tolist())

        # ---- Criterion 2: Eligible products correctly identified (15 pts) ----
        c2_max = 15
        if gt_ids == agent_ids:
            c2_score = 15
            c2_reason = ""
        else:
            overlap = len(gt_ids & agent_ids)
            total_expected = len(gt_ids)
            if total_expected > 0:
                c2_score = max(0, round(15 * overlap / total_expected) - (len(agent_ids - gt_ids)))
                c2_score = max(0, min(15, c2_score))
            else:
                c2_score = 0
            missing = gt_ids - agent_ids
            extra = agent_ids - gt_ids
            c2_reason = f"Missing {len(missing)}, extra {len(extra)} products."
        criteria["eligible_products"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": c2_reason,
        }

        # ---- Criterion 3: Composite scores correct (20 pts) ----
        c3_max = 20
        # Merge on product_id
        merged = pd.merge(
            gt[["product_id", "composite_score"]],
            agent_df[["product_id", "composite_score"]],
            on="product_id",
            suffixes=("_gt", "_agent"),
            how="inner",
        )
        if len(merged) == 0:
            c3_score = 0
            c3_reason = "No matching products to compare scores."
        else:
            diff = (merged["composite_score_gt"] - merged["composite_score_agent"]).abs()
            exact = (diff <= 0.01).sum()
            close = (diff <= 1.0).sum()
            ratio_exact = exact / len(gt)
            ratio_close = close / len(gt)
            c3_score = round(10 * ratio_exact + 10 * ratio_close)
            c3_score = min(c3_max, c3_score)
            c3_reason = "" if c3_score == c3_max else f"{exact}/{len(gt)} exact, {close}/{len(gt)} within 1.0."
        criteria["composite_scores"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": c3_reason,
        }

        # ---- Criterion 4: Discount tiers correct (15 pts) ----
        c4_max = 15
        merged_tiers = pd.merge(
            gt[["product_id", "discount_tier"]],
            agent_df[["product_id", "discount_tier"]],
            on="product_id",
            suffixes=("_gt", "_agent"),
            how="inner",
        )
        if len(merged_tiers) == 0:
            c4_score = 0
            c4_reason = "No matching products."
        else:
            correct_tiers = (merged_tiers["discount_tier_gt"] == merged_tiers["discount_tier_agent"]).sum()
            ratio = correct_tiers / len(gt)
            c4_score = round(c4_max * ratio)
            c4_score = min(c4_max, c4_score)
            c4_reason = "" if c4_score == c4_max else f"{correct_tiers}/{len(gt)} tiers correct."
        criteria["discount_tiers"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": c4_reason,
        }

        # ---- Criterion 5: Margin enforcement (15 pts) ----
        c5_max = 15
        with open(os.path.join(self.workspace, "campaign_config.yaml")) as f:
            config = yaml.safe_load(f)
        min_margin_pct = config["min_margin_pct"]
        min_margin_factor = 1.0 - min_margin_pct / 100.0

        # Check that all agent products satisfy margin
        violations = 0
        for _, row in agent_df.iterrows():
            try:
                sp = float(row["sale_price"])
                cp = float(row["cost_price"])
                min_sp = cp / min_margin_factor
                if sp < min_sp - 0.01:  # small tolerance
                    violations += 1
            except (ValueError, TypeError):
                violations += 1

        # Also check discount_pct matches ground truth
        merged_disc = pd.merge(
            gt[["product_id", "discount_pct"]],
            agent_df[["product_id", "discount_pct"]],
            on="product_id",
            suffixes=("_gt", "_agent"),
            how="inner",
        )
        if len(merged_disc) > 0:
            correct_disc = (merged_disc["discount_pct_gt"] == merged_disc["discount_pct_agent"]).sum()
            disc_ratio = correct_disc / len(gt)
        else:
            disc_ratio = 0.0

        c5_score = 0
        if violations == 0:
            c5_score += 7
        else:
            c5_score += max(0, 7 - violations)
        c5_score += round(8 * disc_ratio)
        c5_score = min(c5_max, max(0, c5_score))
        c5_reason = ""
        if violations > 0:
            c5_reason += f"{violations} margin violations. "
        if disc_ratio < 1.0 and len(merged_disc) > 0:
            c5_reason += f"{int(correct_disc)}/{len(gt)} discount_pct correct."
        criteria["margin_enforcement"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": c5_reason,
        }

        # ---- Criterion 6: Sort order (10 pts) ----
        c6_max = 10
        c6_score = 0
        agent_sorted = agent_df[["product_id", "composite_score"]].copy()
        # Check descending composite_score, ties broken by product_id ascending
        is_sorted = True
        for i in range(len(agent_sorted) - 1):
            s_curr = agent_sorted.iloc[i]["composite_score"]
            s_next = agent_sorted.iloc[i + 1]["composite_score"]
            if s_curr < s_next:
                is_sorted = False
                break
            if s_curr == s_next:
                if str(agent_sorted.iloc[i]["product_id"]) > str(agent_sorted.iloc[i + 1]["product_id"]):
                    is_sorted = False
                    break
        if is_sorted:
            c6_score = 10
        criteria["sort_order"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": "" if c6_score == c6_max else "Rows not sorted by composite_score desc / product_id asc.",
        }

        # ---- Criterion 7: Response summary (15 pts) ----
        c7_max = 15
        c7_score = 0
        action_lower = action.lower() if action else ""

        # Expected summary stats
        total_products = len(gt)
        tier_counts = gt["discount_tier"].value_counts().to_dict()
        avg_discount = round(gt["discount_pct"].mean(), 2)

        # Check total count
        if str(total_products) in action:
            c7_score += 5

        # Check tier counts
        tier_found = 0
        for tier_name, cnt in tier_counts.items():
            # Look for the tier name and count close together in the response
            if tier_name.lower() in action_lower and str(cnt) in action:
                tier_found += 1
        if len(tier_counts) > 0:
            c7_score += round(5 * tier_found / len(tier_counts))

        # Check average discount
        avg_str = f"{avg_discount:.2f}"
        if avg_str in action:
            c7_score += 5
        else:
            # Try integer form if it's a round number
            if avg_discount == int(avg_discount) and str(int(avg_discount)) in action:
                c7_score += 3

        c7_score = min(c7_max, c7_score)
        c7_reason = "" if c7_score == c7_max else "Summary stats incomplete or incorrect in response."
        criteria["response_summary"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": c7_reason,
        }

        # ---- Aggregate ----
        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ----------------------------------------------------------------
    # verify – self-test
    # ----------------------------------------------------------------

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
        import math as _math

        # ---- Read workspace configuration files ----
        with open(os.path.join(self.workspace, "campaign_config.yaml")) as f:
            config = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "discount_tiers.json")) as f:
            tiers_data = json.load(f)

        comp_rep = {}
        with open(os.path.join(self.workspace, "competitor_reputation.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                comp_rep[row["competitor_name"]] = float(row["reputation_weight"])

        with open(os.path.join(self.workspace, "warehouse_config.yaml")) as f:
            wh_config = yaml.safe_load(f)
        wh_priority = {
            k: v["priority_weight"] for k, v in wh_config["warehouses"].items()
        }

        # Read pricing_policy.md (agent would read this for edge-case rules)
        with open(os.path.join(self.workspace, "pricing_policy.md")) as f:
            _ = f.read()  # acknowledged

        eligible_cats = set(config["eligible_categories"])
        min_margin_pct = config["min_margin_pct"]
        max_discount_pct = config["max_discount_pct"]
        weights = config["scoring_weights"]
        tier_list = tiers_data["tiers"]

        # ---- Retrieve all products via tools (paginated) ----
        all_products = []
        page = 1
        while True:
            result = self.tools["list_products"](page=page, page_size=20)
            all_products.extend(result["products"])
            if not result["has_more"]:
                break
            page += 1

        # Filter eligible
        eligible_ids = [
            p["product_id"] for p in all_products if p["category"] in eligible_cats
        ]

        # ---- Get product details via tools ----
        products = {}
        for pid in eligible_ids:
            details = self.tools["get_product_details"](product_id=pid)
            products[pid] = details

        # ---- Get competitor prices via tools ----
        comp_data = {}
        for pid in eligible_ids:
            result = self.tools["get_competitor_prices"](product_id=pid)
            comp_data[pid] = result["competitors"]

        # ---- Get inventory via tools ----
        inv_data = {}
        for pid in eligible_ids:
            result = self.tools["get_inventory_status"](product_id=pid)
            inv_data[pid] = result["warehouses"]

        # ---- Get segment LTV scores via tools ----
        seg_ltv = {}
        page = 1
        while True:
            result = self.tools["list_customer_segments"](page=page, page_size=20)
            for s in result["segments"]:
                seg_ltv[s["segment_id"]] = s["avg_ltv_score"]
            if not result["has_more"]:
                break
            page += 1

        # ---- Read clickstream files from workspace ----
        cs_files = sorted(glob.glob(os.path.join(self.workspace, "clickstream_day_*.csv")))
        if cs_files:
            all_clicks = pd.concat([pd.read_csv(f) for f in cs_files], ignore_index=True)
        else:
            all_clicks = pd.DataFrame(
                columns=["session_id", "product_id", "customer_segment_id", "event_type", "timestamp"]
            )

        # ---- Compute raw engagement ----
        event_weights_map = {"page_view": 1, "click": 2, "add_to_cart": 3, "purchase": 5}
        raw_engagement = {}
        if not all_clicks.empty:
            all_clicks["event_weight"] = all_clicks["event_type"].map(event_weights_map).fillna(0)
            eng_series = all_clicks.groupby("product_id")["event_weight"].sum()
            for pid in eligible_ids:
                raw_engagement[pid] = eng_series.get(pid, 0.0)
        else:
            for pid in eligible_ids:
                raw_engagement[pid] = 0.0

        # ---- Compute raw price competitiveness ----
        raw_competitiveness = {}
        for pid in eligible_ids:
            bp = products[pid]["base_price"]
            in_stock_entries = [c for c in comp_data[pid] if c["in_stock"] == 1]
            if not in_stock_entries:
                raw_competitiveness[pid] = 0.0
                continue
            weighted_sum = sum(
                c["competitor_price"] * comp_rep.get(c["competitor_name"], 0)
                for c in in_stock_entries
            )
            weight_sum = sum(
                comp_rep.get(c["competitor_name"], 0) for c in in_stock_entries
            )
            if weight_sum == 0:
                raw_competitiveness[pid] = 0.0
            else:
                wavg = weighted_sum / weight_sum
                raw_competitiveness[pid] = (bp - wavg) / bp * 100

        # ---- Compute raw inventory urgency ----
        raw_urgency = {}
        for pid in eligible_ids:
            wh_entries = inv_data[pid]
            if not wh_entries:
                raw_urgency[pid] = 0.0
                continue
            num = 0.0
            den = 0.0
            for wh in wh_entries:
                prio = wh_priority.get(wh["warehouse_id"], 0)
                dos = wh["current_stock"] / (wh["monthly_units_sold"] / 30.0)
                num += dos * prio
                den += prio
            raw_urgency[pid] = num / den if den > 0 else 0.0

        # ---- Compute raw segment value ----
        raw_segment_value = {}
        if not all_clicks.empty:
            all_clicks["ltv"] = all_clicks["customer_segment_id"].map(seg_ltv).fillna(0)
            sv_series = all_clicks.groupby("product_id")["ltv"].mean()
            for pid in eligible_ids:
                raw_segment_value[pid] = sv_series.get(pid, 0.0)
        else:
            for pid in eligible_ids:
                raw_segment_value[pid] = 0.0

        # ---- Min-max normalization ----
        def _minmax_dict(d):
            vals = list(d.values())
            mn = min(vals)
            mx = max(vals)
            if mn == mx:
                return {k: 50.0 for k in d}
            return {k: (v - mn) / (mx - mn) * 100.0 for k, v in d.items()}

        norm_engagement = _minmax_dict(raw_engagement)
        norm_competitiveness = _minmax_dict(raw_competitiveness)
        norm_urgency = _minmax_dict(raw_urgency)
        norm_segment_value = _minmax_dict(raw_segment_value)

        # ---- Composite score ----
        composite = {}
        for pid in eligible_ids:
            composite[pid] = (
                weights["engagement"] * norm_engagement[pid]
                + weights["price_competitiveness"] * norm_competitiveness[pid]
                + weights["inventory_urgency"] * norm_urgency[pid]
                + weights["segment_value"] * norm_segment_value[pid]
            )

        # ---- Tier assignment ----
        def _assign_tier(score):
            for t in tier_list:
                if score >= t["min_score"]:
                    return t["tier_name"], t["base_discount_pct"]
            return "NoDiscount", 0

        tiers = {}
        for pid in eligible_ids:
            tiers[pid] = _assign_tier(composite[pid])

        # ---- Margin enforcement ----
        min_margin_factor = 1.0 - min_margin_pct / 100.0
        final_products = []
        for pid in eligible_ids:
            bp = products[pid]["base_price"]
            cp = products[pid]["cost_price"]
            tier_name, tier_disc = tiers[pid]
            discount = min(tier_disc, max_discount_pct)
            sale_price = round(bp * (1 - discount / 100.0), 2)
            min_sp = cp / min_margin_factor
            if sale_price < min_sp:
                max_d = _math.floor(
                    (1.0 - cp / (bp * min_margin_factor)) * 100.0
                )
                if max_d < 1:
                    continue  # exclude
                discount = max_d
                sale_price = round(bp * (1 - discount / 100.0), 2)
            final_products.append({
                "product_id": pid,
                "product_name": products[pid]["product_name"],
                "category": products[pid]["category"],
                "base_price": bp,
                "cost_price": cp,
                "composite_score": round(composite[pid], 2),
                "discount_tier": tier_name,
                "discount_pct": int(discount),
                "sale_price": sale_price,
            })

        # Sort by composite_score desc, product_id asc
        final_products.sort(key=lambda x: (-x["composite_score"], x["product_id"]))

        # ---- Write pricing_schedule.csv ----
        output_path = os.path.join(self.workspace, "pricing_schedule.csv")
        fieldnames = [
            "product_id", "product_name", "category", "base_price",
            "cost_price", "composite_score", "discount_tier",
            "discount_pct", "sale_price",
        ]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in final_products:
                writer.writerow({
                    "product_id": row["product_id"],
                    "product_name": row["product_name"],
                    "category": row["category"],
                    "base_price": f"{row['base_price']:.2f}",
                    "cost_price": f"{row['cost_price']:.2f}",
                    "composite_score": f"{row['composite_score']:.2f}",
                    "discount_tier": row["discount_tier"],
                    "discount_pct": row["discount_pct"],
                    "sale_price": f"{row['sale_price']:.2f}",
                })

        # ---- Construct summary for action string ----
        total_count = len(final_products)
        tier_counts = {}
        for p in final_products:
            t = p["discount_tier"]
            tier_counts[t] = tier_counts.get(t, 0) + 1
        avg_disc = round(
            sum(p["discount_pct"] for p in final_products) / total_count, 2
        ) if total_count > 0 else 0.0

        tier_summary = ", ".join(
            f"{t}: {c}" for t, c in sorted(tier_counts.items())
        )

        action = (
            f"The pricing schedule has been saved to pricing_schedule.csv. "
            f"Total products included: {total_count}. "
            f"Products per discount tier: {tier_summary}. "
            f"Average discount percentage: {avg_disc:.2f}."
        )

        return self.step(action)
