"""
Menu Item Performance Audit - Environment
Tools and evaluation for menu engineering analysis task.
"""

import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import numpy as np
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

    # --- Tool Methods ---

    @tool(
        description="List all menu categories available in the restaurant.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    def list_categories(self) -> str:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM menu_items ORDER BY category")
        categories = [r[0] for r in cursor.fetchall()]
        conn.close()
        return json.dumps({"categories": categories})

    @tool(
        description="Get menu items in a specific category. Returns item_id, item_name, menu_price, is_seasonal, and date_added.",
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "The menu category to retrieve items from"
                }
            },
            "required": ["category"]
        }
    )
    def get_items_by_category(self, category: str) -> str:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT item_id, item_name, menu_price, is_seasonal, date_added FROM menu_items WHERE category = ? ORDER BY item_id",
            (category,)
        )
        items = [{"item_id": r[0], "item_name": r[1], "menu_price": r[2],
                  "is_seasonal": bool(r[3]), "date_added": r[4]} for r in cursor.fetchall()]
        conn.close()
        return json.dumps({"category": category, "items": items, "count": len(items)})

    @tool(
        description="Get point-of-sale sales mix data for a specific menu item across all recorded periods.",
        parameters={
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "integer",
                    "description": "The menu item ID"
                }
            },
            "required": ["item_id"]
        }
    )
    def get_sales_mix(self, item_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT period, units_sold, total_revenue, discount_applied FROM sales_mix WHERE item_id = ? ORDER BY period",
            (item_id,)
        )
        records = [{"period": r[0], "units_sold": r[1], "total_revenue": r[2],
                    "discount_applied": r[3]} for r in cursor.fetchall()]
        conn.close()
        return json.dumps({"item_id": item_id, "sales_data": records})

    @tool(
        description="Get the list of ingredients and their quantities for a specific menu item.",
        parameters={
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "integer",
                    "description": "The menu item ID"
                }
            },
            "required": ["item_id"]
        }
    )
    def get_item_ingredients(self, item_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ingredient_name, quantity_per_serving, unit FROM item_ingredients WHERE item_id = ? ORDER BY ingredient_name",
            (item_id,)
        )
        ingredients = [{"ingredient_name": r[0], "quantity_per_serving": r[1],
                        "unit": r[2]} for r in cursor.fetchall()]
        conn.close()
        return json.dumps({"item_id": item_id, "ingredients": ingredients})

    @tool(
        description="Get aggregated prep time statistics for a specific menu item (average prep minutes, average cook minutes, number of log entries).",
        parameters={
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "integer",
                    "description": "The menu item ID"
                }
            },
            "required": ["item_id"]
        }
    )
    def get_prep_time_stats(self, item_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT AVG(prep_minutes), AVG(cook_minutes), COUNT(*) FROM prep_time_logs WHERE item_id = ?",
            (item_id,)
        )
        r = cursor.fetchone()
        conn.close()
        if r[0] is None:
            return json.dumps({"item_id": item_id, "error": "No prep time data found"})
        return json.dumps({
            "item_id": item_id,
            "avg_prep_minutes": round(r[0], 2),
            "avg_cook_minutes": round(r[1], 2),
            "avg_total_minutes": round(r[0] + r[1], 2),
            "num_logs": r[2]
        })

    @tool(
        description="Get customer rating statistics for a specific menu item (average score, count, score distribution).",
        parameters={
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "integer",
                    "description": "The menu item ID"
                }
            },
            "required": ["item_id"]
        }
    )
    def get_customer_ratings(self, item_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT AVG(rating_score), COUNT(*), MIN(rating_score), MAX(rating_score) FROM customer_ratings WHERE item_id = ?",
            (item_id,)
        )
        r = cursor.fetchone()
        conn.close()
        if r[0] is None:
            return json.dumps({"item_id": item_id, "error": "No rating data found"})
        return json.dumps({
            "item_id": item_id,
            "avg_rating": round(r[0], 2),
            "num_ratings": r[1],
            "min_rating": r[2],
            "max_rating": r[3]
        })

    @tool(
        description="Get the menu price and portion size for a specific item.",
        parameters={
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "integer",
                    "description": "The menu item ID"
                }
            },
            "required": ["item_id"]
        }
    )
    def get_item_pricing(self, item_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT item_name, category, menu_price, portion_size_oz FROM menu_items WHERE item_id = ?",
            (item_id,)
        )
        r = cursor.fetchone()
        conn.close()
        if r is None:
            return json.dumps({"item_id": item_id, "error": "Item not found"})
        return json.dumps({
            "item_id": item_id,
            "item_name": r[0],
            "category": r[1],
            "menu_price": r[2],
            "portion_size_oz": r[3]
        })

    # --- Evaluation ---

    def _compute_ground_truth(self):
        """Compute the full ground truth analysis."""
        conn = sqlite3.connect(self.db_path)

        # Load config
        config_path = os.path.join(self.workspace, "analysis_config.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        weights = config["scoring_weights"]
        thresholds = config["underperformance_thresholds"]
        action_rules = config["action_rules"]

        # Get all items
        items_df = pd.read_sql_query("SELECT * FROM menu_items", conn)

        # Get sales data
        sales_df = pd.read_sql_query("SELECT item_id, period, units_sold, total_revenue FROM sales_mix", conn)
        sales_agg = sales_df.groupby("item_id").agg(
            total_units_sold=("units_sold", "sum"),
            total_revenue=("total_revenue", "sum"),
            num_periods=("period", "nunique")
        ).reset_index()

        # Get prep time stats
        prep_df = pd.read_sql_query("SELECT item_id, prep_minutes, cook_minutes FROM prep_time_logs", conn)
        prep_agg = prep_df.groupby("item_id").agg(
            avg_prep=("prep_minutes", "mean"),
            avg_cook=("cook_minutes", "mean")
        ).reset_index()
        prep_agg["avg_total_prep"] = prep_agg["avg_prep"] + prep_agg["avg_cook"]

        # Get customer ratings
        ratings_df = pd.read_sql_query("SELECT item_id, rating_score FROM customer_ratings", conn)
        ratings_agg = ratings_df.groupby("item_id").agg(
            avg_rating=("rating_score", "mean")
        ).reset_index()

        # Get ingredient costs from workspace files
        ingredient_costs = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("ingredient_costs_") and fname.endswith(".csv"):
                df = pd.read_csv(os.path.join(self.workspace, fname))
                for _, row in df.iterrows():
                    ingredient_costs[row["ingredient"]] = row["cost_per_unit"]

        # Get ingredients from DB
        ingredients_df = pd.read_sql_query("SELECT item_id, ingredient_name, quantity_per_serving FROM item_ingredients", conn)
        conn.close()

        # Compute food cost per item
        def calc_food_cost(group):
            total = 0
            for _, row in group.iterrows():
                cost = ingredient_costs.get(row["ingredient_name"], 0)
                total += cost * row["quantity_per_serving"]
            return total

        food_costs = ingredients_df.groupby("item_id").apply(calc_food_cost).reset_index()
        food_costs.columns = ["item_id", "food_cost"]

        # Merge all data
        merged = items_df[["item_id", "item_name", "category", "menu_price"]].copy()
        merged = merged.merge(sales_agg, on="item_id", how="left")
        merged = merged.merge(prep_agg[["item_id", "avg_total_prep"]], on="item_id", how="left")
        merged = merged.merge(ratings_agg, on="item_id", how="left")
        merged = merged.merge(food_costs, on="item_id", how="left")

        # Fill NaN
        merged["total_units_sold"] = merged["total_units_sold"].fillna(0)
        merged["total_revenue"] = merged["total_revenue"].fillna(0)
        merged["num_periods"] = merged["num_periods"].fillna(1)
        merged["avg_total_prep"] = merged["avg_total_prep"].fillna(0)
        merged["avg_rating"] = merged["avg_rating"].fillna(2.5)
        merged["food_cost"] = merged["food_cost"].fillna(0)

        # Compute food cost percentage
        merged["food_cost_pct"] = (merged["food_cost"] / merged["menu_price"]) * 100

        # Compute dimension scores
        max_food_cost_pct = thresholds["max_food_cost_pct"]
        max_prep_minutes = thresholds["max_avg_prep_total_minutes"]

        merged["food_cost_score"] = merged["food_cost_pct"].apply(
            lambda x: max(0, 100 - (x / max_food_cost_pct) * 100)
        )

        max_units = merged["total_units_sold"].max()
        merged["sales_score"] = (merged["total_units_sold"] / max_units) * 100 if max_units > 0 else 0

        merged["satisfaction_score"] = ((merged["avg_rating"] - 1.0) / 4.0) * 100

        merged["prep_score"] = merged["avg_total_prep"].apply(
            lambda x: max(0, 100 - (x / max_prep_minutes) * 100)
        )

        max_revenue = merged["total_revenue"].max()
        merged["revenue_score"] = (merged["total_revenue"] / max_revenue) * 100 if max_revenue > 0 else 0

        # Composite score
        merged["composite_score"] = (
            merged["food_cost_score"] * weights["food_cost_pct"] +
            merged["sales_score"] * weights["sales_volume"] +
            merged["satisfaction_score"] * weights["customer_satisfaction"] +
            merged["prep_score"] * weights["prep_time_efficiency"] +
            merged["revenue_score"] * weights["revenue_contribution"]
        ).round(2)

        # Determine threshold failures
        min_satisfaction = thresholds["min_satisfaction_score"]
        min_units_per_quarter = thresholds["min_units_sold_per_quarter"]

        merged["fails_food_cost"] = merged["food_cost_pct"] > max_food_cost_pct
        merged["fails_satisfaction"] = merged["avg_rating"] < min_satisfaction
        merged["fails_prep"] = merged["avg_total_prep"] > max_prep_minutes
        merged["fails_sales"] = merged.apply(
            lambda r: r["total_units_sold"] < min_units_per_quarter * r["num_periods"], axis=1
        )

        merged["num_failures"] = (
            merged["fails_food_cost"].astype(int) +
            merged["fails_satisfaction"].astype(int) +
            merged["fails_prep"].astype(int) +
            merged["fails_sales"].astype(int)
        )

        # Revenue threshold for high revenue contribution (top 25%)
        revenue_75th = merged["total_revenue"].quantile(0.75)
        merged["high_revenue"] = merged["total_revenue"] >= revenue_75th

        # Action assignment
        def assign_action(row):
            removal_min = action_rules["removal_candidates"]["min_criteria_failed"]
            removal_must = action_rules["removal_candidates"]["must_fail"]
            revision_min = action_rules["revision_candidates"]["min_criteria_failed"]

            # Check removal
            must_fail_map = {
                "food_cost_pct_exceeded": row["fails_food_cost"],
                "low_satisfaction": row["fails_satisfaction"],
                "slow_prep": row["fails_prep"],
                "low_sales": row["fails_sales"]
            }

            all_must_fail = all(must_fail_map.get(f, False) for f in removal_must)
            if row["num_failures"] >= removal_min and all_must_fail:
                return "REMOVAL"

            # Check revision
            if row["num_failures"] >= revision_min:
                if row["high_revenue"]:
                    return "MONITOR"
                return "REVISION"

            if row["num_failures"] == 1:
                return "MONITOR"

            return "OK"

        merged["action"] = merged.apply(assign_action, axis=1)

        # Sort: primary by composite_score ascending, tie-break by item_name alphabetical
        merged = merged.sort_values(
            by=["composite_score", "item_name"],
            ascending=[True, True]
        ).reset_index(drop=True)

        return merged

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
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # Criterion 1: Output file exists with correct name (10 pts)
        output_path = os.path.join(self.workspace, "menu_audit_results.csv")
        file_exists = os.path.exists(output_path)
        eval_criteria["output_file_exists"] = {
            "passed": file_exists,
            "score": 10 if file_exists else 0,
            "max_score": 10,
            "reason": "" if file_exists else "menu_audit_results.csv not found in workspace"
        }
        total_score += eval_criteria["output_file_exists"]["score"]
        max_score += 10

        # Criterion 2: CSV has correct columns (15 pts)
        correct_columns = False
        expected_cols = ["item_id", "item_name", "category", "composite_score", "action", "food_cost_pct", "avg_rating", "avg_prep_total_minutes", "total_units_sold"]
        if file_exists:
            try:
                result_df = pd.read_csv(output_path)
                actual_cols = list(result_df.columns)
                correct_columns = all(c in actual_cols for c in expected_cols)
            except Exception:
                pass
        eval_criteria["correct_columns"] = {
            "passed": correct_columns,
            "score": 15 if correct_columns else 0,
            "max_score": 15,
            "reason": "" if correct_columns else f"Expected columns: {expected_cols}"
        }
        total_score += eval_criteria["correct_columns"]["score"]
        max_score += 15

        # Criterion 3: All items present and correctly identified (20 pts)
        all_items_correct = False
        if file_exists and correct_columns:
            try:
                result_df = pd.read_csv(output_path)
                gt_ids = set(ground_truth["item_id"].tolist())
                result_ids = set(result_df["item_id"].tolist())
                all_items_correct = gt_ids == result_ids
            except Exception:
                pass
        eval_criteria["all_items_present"] = {
            "passed": all_items_correct,
            "score": 20 if all_items_correct else 0,
            "max_score": 20,
            "reason": "" if all_items_correct else "Not all menu items are present in output"
        }
        total_score += eval_criteria["all_items_present"]["score"]
        max_score += 20

        # Criterion 4: Action classification accuracy (25 pts)
        action_accuracy = 0
        action_score = 0
        if file_exists and correct_columns:
            try:
                result_df = pd.read_csv(output_path)
                merged_check = ground_truth[["item_id", "action"]].merge(
                    result_df[["item_id", "action"]], on="item_id", suffixes=("_gt", "_pred")
                )
                if len(merged_check) > 0:
                    correct_actions = (merged_check["action_gt"] == merged_check["action_pred"]).sum()
                    action_accuracy = correct_actions / len(merged_check)
                    action_score = round(action_accuracy * 25)
            except Exception:
                pass
        eval_criteria["action_classification"] = {
            "passed": action_accuracy >= 0.9,
            "score": action_score,
            "max_score": 25,
            "reason": "" if action_accuracy >= 0.9 else f"Action accuracy: {action_accuracy:.2%}"
        }
        total_score += action_score
        max_score += 25

        # Criterion 5: Composite score accuracy (20 pts)
        score_accuracy = 0
        score_pts = 0
        if file_exists and correct_columns:
            try:
                result_df = pd.read_csv(output_path)
                merged_scores = ground_truth[["item_id", "composite_score"]].merge(
                    result_df[["item_id", "composite_score"]], on="item_id", suffixes=("_gt", "_pred")
                )
                if len(merged_scores) > 0:
                    # Allow tolerance of 0.5 per item
                    within_tol = (abs(merged_scores["composite_score_gt"] - merged_scores["composite_score_pred"]) <= 0.5).sum()
                    score_accuracy = within_tol / len(merged_scores)
                    score_pts = round(score_accuracy * 20)
            except Exception:
                pass
        eval_criteria["composite_score_accuracy"] = {
            "passed": score_accuracy >= 0.9,
            "score": score_pts,
            "max_score": 20,
            "reason": "" if score_accuracy >= 0.9 else f"Score accuracy: {score_accuracy:.2%}"
        }
        total_score += score_pts
        max_score += 20

        # Criterion 6: Correct sort order (10 pts)
        sort_correct = False
        if file_exists and correct_columns:
            try:
                result_df = pd.read_csv(output_path)
                # Verify the result is sorted by composite_score ascending, tie-break item_name ascending
                expected_order = result_df.sort_values(
                    by=["composite_score", "item_name"], ascending=[True, True]
                ).reset_index(drop=True)
                sort_correct = list(result_df["item_id"]) == list(expected_order["item_id"])
            except Exception:
                pass
        eval_criteria["correct_sort_order"] = {
            "passed": sort_correct,
            "score": 10 if sort_correct else 0,
            "max_score": 10,
            "reason": "" if sort_correct else "Items not sorted by composite_score ascending with item_name tie-breaker"
        }
        total_score += eval_criteria["correct_sort_order"]["score"]
        max_score += 10

        # Criterion 7: Response contains summary of removal and revision candidates (10 pts)
        removal_items = ground_truth[ground_truth["action"] == "REMOVAL"]["item_name"].tolist()
        revision_items = ground_truth[ground_truth["action"] == "REVISION"]["item_name"].tolist()

        response_has_summary = False
        if action:
            action_lower = action.lower()
            # Check that response mentions at least half the removal candidates and at least some revision
            removal_mentioned = sum(1 for item in removal_items if item.lower() in action_lower)
            revision_mentioned = sum(1 for item in revision_items if item.lower() in action_lower)
            min_removal = max(1, len(removal_items) // 2)
            min_revision = max(1, len(revision_items) // 3)
            response_has_summary = (removal_mentioned >= min_removal or len(removal_items) == 0) and \
                                   (revision_mentioned >= min_revision or len(revision_items) == 0)
        eval_criteria["response_summary"] = {
            "passed": response_has_summary,
            "score": 10 if response_has_summary else 0,
            "max_score": 10,
            "reason": "" if response_has_summary else "Response should summarize key removal and revision candidates"
        }
        total_score += eval_criteria["response_summary"]["score"]
        max_score += 10

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
        import glob as glob_mod

        # Step 1: Read config files from workspace
        config_path = os.path.join(self.workspace, "analysis_config.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        weights = config["scoring_weights"]
        thresholds = config["underperformance_thresholds"]
        action_rules = config["action_rules"]

        # Step 2: Get all categories using tool
        categories_result = json.loads(self.tools["list_categories"]())
        categories = categories_result["categories"]

        # Step 3: Get all items by category using tools
        all_items = []
        for cat in categories:
            items_result = json.loads(self.tools["get_items_by_category"](category=cat))
            for item in items_result["items"]:
                item["category"] = cat
                all_items.append(item)

        # Step 4: For each item, gather sales, ingredients, prep time, ratings via tools
        item_data = []
        for item in all_items:
            item_id = item["item_id"]

            # Get sales mix
            sales_result = json.loads(self.tools["get_sales_mix"](item_id=item_id))
            total_units = sum(s["units_sold"] for s in sales_result["sales_data"])
            total_revenue = sum(s["total_revenue"] for s in sales_result["sales_data"])
            num_periods = len(sales_result["sales_data"])

            # Get ingredients
            ing_result = json.loads(self.tools["get_item_ingredients"](item_id=item_id))

            # Get prep time stats
            prep_result = json.loads(self.tools["get_prep_time_stats"](item_id=item_id))
            avg_total_prep = prep_result.get("avg_total_minutes", 0)

            # Get customer ratings
            rating_result = json.loads(self.tools["get_customer_ratings"](item_id=item_id))
            avg_rating = rating_result.get("avg_rating", 2.5)

            # Get pricing
            pricing_result = json.loads(self.tools["get_item_pricing"](item_id=item_id))
            menu_price = pricing_result["menu_price"]

            item_data.append({
                "item_id": item_id,
                "item_name": item["item_name"],
                "category": item["category"],
                "menu_price": menu_price,
                "total_units_sold": total_units,
                "total_revenue": total_revenue,
                "num_periods": num_periods,
                "avg_total_prep": avg_total_prep,
                "avg_rating": avg_rating,
                "ingredients": ing_result["ingredients"]
            })

        # Step 5: Read ingredient cost files from workspace
        ingredient_costs = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("ingredient_costs_") and fname.endswith(".csv"):
                df = pd.read_csv(os.path.join(self.workspace, fname))
                for _, row in df.iterrows():
                    ingredient_costs[row["ingredient"]] = row["cost_per_unit"]

        # Step 6: Compute food cost per item
        for item in item_data:
            food_cost = 0
            for ing in item["ingredients"]:
                unit_cost = ingredient_costs.get(ing["ingredient_name"], 0)
                food_cost += unit_cost * ing["quantity_per_serving"]
            item["food_cost"] = food_cost
            item["food_cost_pct"] = (food_cost / item["menu_price"]) * 100 if item["menu_price"] > 0 else 0

        # Step 7: Compute dimension scores
        max_food_cost_pct = thresholds["max_food_cost_pct"]
        max_prep_minutes = thresholds["max_avg_prep_total_minutes"]
        max_units = max(it["total_units_sold"] for it in item_data) if item_data else 1
        max_revenue = max(it["total_revenue"] for it in item_data) if item_data else 1

        for item in item_data:
            item["food_cost_score"] = max(0, 100 - (item["food_cost_pct"] / max_food_cost_pct) * 100)
            item["sales_score"] = (item["total_units_sold"] / max_units) * 100
            item["satisfaction_score"] = ((item["avg_rating"] - 1.0) / 4.0) * 100
            item["prep_score"] = max(0, 100 - (item["avg_total_prep"] / max_prep_minutes) * 100)
            item["revenue_score"] = (item["total_revenue"] / max_revenue) * 100

            item["composite_score"] = round(
                item["food_cost_score"] * weights["food_cost_pct"] +
                item["sales_score"] * weights["sales_volume"] +
                item["satisfaction_score"] * weights["customer_satisfaction"] +
                item["prep_score"] * weights["prep_time_efficiency"] +
                item["revenue_score"] * weights["revenue_contribution"],
                2
            )

        # Step 8: Determine threshold failures and actions
        min_satisfaction = thresholds["min_satisfaction_score"]
        min_units_per_quarter = thresholds["min_units_sold_per_quarter"]

        for item in item_data:
            item["fails_food_cost"] = item["food_cost_pct"] > max_food_cost_pct
            item["fails_satisfaction"] = item["avg_rating"] < min_satisfaction
            item["fails_prep"] = item["avg_total_prep"] > max_prep_minutes
            item["fails_sales"] = item["total_units_sold"] < min_units_per_quarter * item["num_periods"]
            item["num_failures"] = sum([
                item["fails_food_cost"], item["fails_satisfaction"],
                item["fails_prep"], item["fails_sales"]
            ])

        # Revenue threshold top 25% (using numpy percentile to match pandas quantile)
        all_revenues = sorted([it["total_revenue"] for it in item_data])
        revenue_75th = float(np.percentile(all_revenues, 75)) if all_revenues else 0

        for item in item_data:
            item["high_revenue"] = item["total_revenue"] >= revenue_75th

        # Assign actions
        removal_min = action_rules["removal_candidates"]["min_criteria_failed"]
        removal_must = action_rules["removal_candidates"]["must_fail"]
        revision_min = action_rules["revision_candidates"]["min_criteria_failed"]

        for item in item_data:
            must_fail_map = {
                "food_cost_pct_exceeded": item["fails_food_cost"],
                "low_satisfaction": item["fails_satisfaction"],
                "slow_prep": item["fails_prep"],
                "low_sales": item["fails_sales"]
            }
            all_must_fail = all(must_fail_map.get(f, False) for f in removal_must)

            if item["num_failures"] >= removal_min and all_must_fail:
                item["action"] = "REMOVAL"
            elif item["num_failures"] >= revision_min:
                if item["high_revenue"]:
                    item["action"] = "MONITOR"
                else:
                    item["action"] = "REVISION"
            elif item["num_failures"] == 1:
                item["action"] = "MONITOR"
            else:
                item["action"] = "OK"

        # Step 9: Sort by composite_score ascending, then item_name alphabetical
        item_data.sort(key=lambda x: (x["composite_score"], x["item_name"]))

        # Step 10: Write output CSV
        output_rows = []
        for item in item_data:
            output_rows.append({
                "item_id": item["item_id"],
                "item_name": item["item_name"],
                "category": item["category"],
                "composite_score": item["composite_score"],
                "action": item["action"],
                "food_cost_pct": round(item["food_cost_pct"], 2),
                "avg_rating": round(item["avg_rating"], 2),
                "avg_prep_total_minutes": round(item["avg_total_prep"], 2),
                "total_units_sold": item["total_units_sold"]
            })

        output_df = pd.DataFrame(output_rows)
        output_df.to_csv(os.path.join(self.workspace, "menu_audit_results.csv"), index=False)

        # Step 11: Construct response
        removal_items = [it for it in item_data if it["action"] == "REMOVAL"]
        revision_items = [it for it in item_data if it["action"] == "REVISION"]

        response_parts = ["Menu Engineering Audit Complete.\n"]
        response_parts.append(f"Total items analyzed: {len(item_data)}")
        response_parts.append(f"Removal candidates: {len(removal_items)}")
        response_parts.append(f"Revision candidates: {len(revision_items)}\n")

        if removal_items:
            response_parts.append("Items recommended for REMOVAL:")
            for it in removal_items:
                response_parts.append(f"- {it['item_name']} (score: {it['composite_score']}, food cost: {it['food_cost_pct']:.2f}%, rating: {it['avg_rating']:.2f})")

        if revision_items:
            response_parts.append("\nItems recommended for REVISION:")
            for it in revision_items:
                response_parts.append(f"- {it['item_name']} (score: {it['composite_score']}, food cost: {it['food_cost_pct']:.2f}%, rating: {it['avg_rating']:.2f})")

        action_str = "\n".join(response_parts)

        return self.step(action_str)
