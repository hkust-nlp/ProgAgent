"""
Environment for ingredient spoilage reduction task.
Provides tools for querying kitchen inventory data and evaluates
the agent's prioritized use-it-first list.
"""

import csv
import glob
import json
import math
import os
import re
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


# --- Decorator (keep unchanged) ---
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

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description=(
            "List all ingredients in the system with pagination. "
            "Returns id, name, and category for each ingredient."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20).",
                },
            },
            "required": ["page"],
        },
    )
    def list_ingredients(self, page: int, page_size: int = 20) -> dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM ingredients")
        total = cur.fetchone()["cnt"]
        cur.execute(
            "SELECT id, name, category FROM ingredients ORDER BY id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        items = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size),
        }

    @tool(
        description=(
            "Get full details for a single ingredient by its ID. "
            "Returns name, category, unit, shelf_life_days, "
            "min_storage_temp, and max_storage_temp."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ingredient_id": {
                    "type": "integer",
                    "description": "The ingredient ID.",
                },
            },
            "required": ["ingredient_id"],
        },
    )
    def get_ingredient_details(self, ingredient_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Ingredient {ingredient_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Query supplier delivery records for a specific ingredient. "
            "Returns delivery_date, batch_code, quantity, supplier_name, and unit_cost."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ingredient_id": {
                    "type": "integer",
                    "description": "The ingredient ID to query deliveries for.",
                },
            },
            "required": ["ingredient_id"],
        },
    )
    def get_deliveries_for_ingredient(self, ingredient_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, ingredient_id, supplier_name, delivery_date, batch_code, "
            "quantity, unit_cost FROM supplier_deliveries "
            "WHERE ingredient_id = ? ORDER BY delivery_date DESC",
            (ingredient_id,),
        )
        items = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"deliveries": items, "count": len(items)}

    @tool(
        description=(
            "Get temperature log readings for a specific fridge on a specific date. "
            "Returns all recorded temperatures with timestamps."
        ),
        parameters={
            "type": "object",
            "properties": {
                "fridge_id": {
                    "type": "string",
                    "description": "Fridge identifier (e.g., 'FRIDGE-A').",
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format.",
                },
            },
            "required": ["fridge_id", "date"],
        },
    )
    def get_fridge_temperatures(self, fridge_id: str, date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, fridge_id, recorded_at, temperature_c "
            "FROM fridge_temp_logs "
            "WHERE fridge_id = ? AND DATE(recorded_at) = ? "
            "ORDER BY recorded_at",
            (fridge_id, date),
        )
        items = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"readings": items, "count": len(items)}

    @tool(
        description=(
            "Get waste log entries for a specific ingredient over the past 30 days "
            "from the reference date. Returns date, quantity wasted, and reason."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ingredient_id": {
                    "type": "integer",
                    "description": "The ingredient ID.",
                },
            },
            "required": ["ingredient_id"],
        },
    )
    def get_waste_history(self, ingredient_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, ingredient_id, waste_date, quantity_wasted, reason "
            "FROM waste_logs WHERE ingredient_id = ? "
            "ORDER BY waste_date DESC",
            (ingredient_id,),
        )
        items = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"waste_entries": items, "count": len(items)}

    @tool(
        description=(
            "Get all recipes that use a specific ingredient, with the "
            "quantity required per serving for each recipe."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ingredient_id": {
                    "type": "integer",
                    "description": "The ingredient ID.",
                },
            },
            "required": ["ingredient_id"],
        },
    )
    def get_recipe_usage(self, ingredient_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, recipe_name, ingredient_id, quantity_per_serving "
            "FROM recipe_ingredients WHERE ingredient_id = ? "
            "ORDER BY recipe_name",
            (ingredient_id,),
        )
        items = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"recipes": items, "count": len(items)}

    @tool(
        description=(
            "Look up the delivery record for a specific batch code. "
            "Returns ingredient_id, supplier_name, delivery_date, quantity, and unit_cost."
        ),
        parameters={
            "type": "object",
            "properties": {
                "batch_code": {
                    "type": "string",
                    "description": "The batch code (e.g., 'BCH-00001').",
                },
            },
            "required": ["batch_code"],
        },
    )
    def lookup_batch(self, batch_code: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM supplier_deliveries WHERE batch_code = ?",
            (batch_code,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Batch {batch_code} not found."}
        return dict(row)

    # ------------------------------------------------------------------
    # Ground-truth computation (used by step and verify)
    # ------------------------------------------------------------------

    def _compute_ground_truth(self):
        """Compute the ground-truth priority list from DB + workspace."""
        # Load config
        config_path = os.path.join(self.workspace, "spoilage_config.yaml")
        with open(config_path) as f:
            config = yaml.safe_load(f)

        ref_date = config["reference_date"]
        ref_ts = __import__("datetime").datetime.strptime(ref_date, "%Y-%m-%d")

        scoring = config["scoring"]
        temp_coeff = scoring["temp_penalty_coefficient"]
        cond_penalty = scoring["condition_flag_penalty_days"]
        waste_mult = scoring["waste_rate_multiplier"]
        thresholds = config["action_thresholds"]

        # Load current stock from all stock files
        stock_items = []
        for fp in sorted(glob.glob(os.path.join(self.workspace, "current_stock_*.json"))):
            with open(fp) as f:
                stock_items.extend(json.load(f))

        # Load flagged batches from delivery notes
        flagged_batches = set()
        for fp in sorted(glob.glob(os.path.join(self.workspace, "delivery_notes_*.txt"))):
            with open(fp) as f:
                content = f.read()
            # Find lines with batch codes followed by CONDITION FLAG
            current_batch = None
            for line in content.split("\n"):
                if line.startswith("Batch: "):
                    current_batch = line.replace("Batch: ", "").strip()
                if "CONDITION FLAG" in line and current_batch:
                    flagged_batches.add(current_batch)

        # Load DB data
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Ingredient details
        ing_map = {}
        for row in conn.execute("SELECT * FROM ingredients"):
            ing_map[row["id"]] = dict(row)

        # Delivery details by batch_code
        del_map = {}
        for row in conn.execute("SELECT * FROM supplier_deliveries"):
            del_map[row["batch_code"]] = dict(row)

        # Compute avg fridge temps over past 3 days
        fridge_avg_temps = {}
        for fid in ["FRIDGE-A", "FRIDGE-B", "FREEZER-C", "PANTRY-D"]:
            rows = conn.execute(
                "SELECT temperature_c FROM fridge_temp_logs "
                "WHERE fridge_id = ? AND DATE(recorded_at) >= DATE(?, '-3 days') "
                "AND DATE(recorded_at) <= ?",
                (fid, ref_date, ref_date),
            ).fetchall()
            if rows:
                fridge_avg_temps[fid] = sum(r["temperature_c"] for r in rows) / len(rows)
            else:
                fridge_avg_temps[fid] = 0.0

        # Waste totals per ingredient (30-day window)
        waste_totals = {}
        for row in conn.execute(
            "SELECT ingredient_id, SUM(quantity_wasted) as total "
            "FROM waste_logs WHERE waste_date >= DATE(?, '-30 days') "
            "AND waste_date <= ? GROUP BY ingredient_id",
            (ref_date, ref_date),
        ):
            waste_totals[row["ingredient_id"]] = row["total"]

        # Delivery totals per ingredient (30-day window)
        delivery_totals = {}
        for row in conn.execute(
            "SELECT ingredient_id, SUM(quantity) as total "
            "FROM supplier_deliveries WHERE delivery_date >= DATE(?, '-30 days') "
            "AND delivery_date <= ? GROUP BY ingredient_id",
            (ref_date, ref_date),
        ):
            delivery_totals[row["ingredient_id"]] = row["total"]

        conn.close()

        # Compute priority list
        results = []
        for stock in stock_items:
            batch_code = stock["batch_code"]
            ing_id = stock["ingredient_id"]
            fridge_id = stock["fridge_id"]

            ing = ing_map.get(ing_id)
            delivery = del_map.get(batch_code)
            if ing is None or delivery is None:
                continue

            # Days since delivery
            del_date = __import__("datetime").datetime.strptime(
                delivery["delivery_date"], "%Y-%m-%d"
            )
            days_since = (ref_ts - del_date).days

            # Base remaining
            base_remaining = ing["shelf_life_days"] - days_since

            # Temp penalty
            avg_temp = fridge_avg_temps.get(fridge_id, 0.0)
            temp_excess = max(0, avg_temp - ing["max_storage_temp"])
            temp_pen = temp_excess * temp_coeff

            # Condition penalty
            cond_pen = cond_penalty if batch_code in flagged_batches else 0

            # Effective remaining
            effective_remaining = base_remaining - temp_pen - cond_pen

            # Waste rate
            total_wasted = waste_totals.get(ing_id, 0.0)
            total_delivered = delivery_totals.get(ing_id, 0.0)
            waste_rate = total_wasted / total_delivered if total_delivered > 0 else 0.0

            # Spoilage risk score
            eff_for_score = max(effective_remaining, 0.1)
            spoilage_score = (1.0 / eff_for_score) * (1.0 + waste_rate * waste_mult)

            # Recommended action
            action = "MONITOR"
            # Check thresholds in order: DISCARD, USE_IMMEDIATELY, USE_SOON
            if effective_remaining <= thresholds["DISCARD"]["max_effective_remaining"]:
                action = "DISCARD"
            elif effective_remaining <= thresholds["USE_IMMEDIATELY"]["max_effective_remaining"]:
                action = "USE_IMMEDIATELY"
            elif effective_remaining <= thresholds["USE_SOON"]["max_effective_remaining"]:
                action = "USE_SOON"

            results.append({
                "ingredient_name": ing["name"],
                "batch_code": batch_code,
                "category": ing["category"],
                "delivery_date": delivery["delivery_date"],
                "effective_remaining_days": round(effective_remaining, 1),
                "spoilage_risk_score": round(spoilage_score, 4),
                "recommended_action": action,
            })

        # Sort by spoilage_risk_score desc, then ingredient_name asc for ties
        results.sort(key=lambda x: (-x["spoilage_risk_score"], x["ingredient_name"]))

        # Add rank
        for i, r in enumerate(results):
            r["rank"] = i + 1

        return results, flagged_batches

    # ------------------------------------------------------------------
    # Step: evaluate the agent's output
    # ------------------------------------------------------------------

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
        gt_results, gt_flagged = self._compute_ground_truth()
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: priority_list.csv exists with correct columns (10 pts) ---
        csv_path = os.path.join(self.workspace, "priority_list.csv")
        expected_cols = [
            "rank", "ingredient_name", "batch_code", "category",
            "delivery_date", "effective_remaining_days",
            "spoilage_risk_score", "recommended_action",
        ]
        c1_score = 0
        c1_max = 10
        c1_reason = ""
        agent_rows = []
        if os.path.exists(csv_path):
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                agent_cols = [c.strip() for c in (reader.fieldnames or [])]
                if set(expected_cols) <= set(agent_cols):
                    c1_score = 10
                    for row in reader:
                        agent_rows.append({k.strip(): v.strip() for k, v in row.items()})
                else:
                    missing = set(expected_cols) - set(agent_cols)
                    c1_reason = f"Missing columns: {missing}"
        else:
            c1_reason = "priority_list.csv not found"

        eval_criteria["csv_structure"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": c1_reason if c1_score < c1_max else "",
        }
        total_score += c1_score
        max_score += c1_max

        # --- Criterion 2: Correct set of batches (15 pts) ---
        c2_max = 15
        gt_batches = set(r["batch_code"] for r in gt_results)
        agent_batches = set(r.get("batch_code", "") for r in agent_rows)
        if gt_batches and agent_batches:
            intersection = gt_batches & agent_batches
            union = gt_batches | agent_batches
            jaccard = len(intersection) / len(union) if union else 0
            c2_score = round(c2_max * jaccard)
            c2_reason = "" if jaccard == 1.0 else (
                f"Expected {len(gt_batches)} batches, got {len(agent_batches)}. "
                f"Missing: {gt_batches - agent_batches}, Extra: {agent_batches - gt_batches}"
            )
        else:
            c2_score = 0
            c2_reason = "No batches to compare"

        eval_criteria["batch_coverage"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": c2_reason if c2_score < c2_max else "",
        }
        total_score += c2_score
        max_score += c2_max

        # --- Criterion 3: Correct effective_remaining_days (20 pts) ---
        c3_max = 20
        gt_by_batch = {r["batch_code"]: r for r in gt_results}
        agent_by_batch = {r.get("batch_code", ""): r for r in agent_rows}
        common = gt_batches & agent_batches
        correct_erd = 0
        for bc in common:
            gt_erd = gt_by_batch[bc]["effective_remaining_days"]
            try:
                agent_erd = float(agent_by_batch[bc].get("effective_remaining_days", "nan"))
            except (ValueError, TypeError):
                continue
            if abs(gt_erd - agent_erd) <= 0.15:
                correct_erd += 1
        if common:
            c3_score = round(c3_max * correct_erd / len(common))
        else:
            c3_score = 0
        c3_reason = "" if c3_score == c3_max else f"{correct_erd}/{len(common)} batches correct"

        eval_criteria["effective_remaining_days"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": c3_reason if c3_score < c3_max else "",
        }
        total_score += c3_score
        max_score += c3_max

        # --- Criterion 4: Correct spoilage_risk_score (20 pts) ---
        c4_max = 20
        correct_srs = 0
        for bc in common:
            gt_srs = gt_by_batch[bc]["spoilage_risk_score"]
            try:
                agent_srs = float(agent_by_batch[bc].get("spoilage_risk_score", "nan"))
            except (ValueError, TypeError):
                continue
            if abs(gt_srs - agent_srs) <= 0.005:
                correct_srs += 1
        if common:
            c4_score = round(c4_max * correct_srs / len(common))
        else:
            c4_score = 0
        c4_reason = "" if c4_score == c4_max else f"{correct_srs}/{len(common)} batches correct"

        eval_criteria["spoilage_risk_score"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": c4_reason if c4_score < c4_max else "",
        }
        total_score += c4_score
        max_score += c4_max

        # --- Criterion 5: Correct recommended actions (15 pts) ---
        c5_max = 15
        correct_act = 0
        for bc in common:
            gt_act = gt_by_batch[bc]["recommended_action"]
            agent_act = agent_by_batch[bc].get("recommended_action", "").strip()
            if gt_act == agent_act:
                correct_act += 1
        if common:
            c5_score = round(c5_max * correct_act / len(common))
        else:
            c5_score = 0
        c5_reason = "" if c5_score == c5_max else f"{correct_act}/{len(common)} actions correct"

        eval_criteria["recommended_actions"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": c5_reason if c5_score < c5_max else "",
        }
        total_score += c5_score
        max_score += c5_max

        # --- Criterion 6: Correct ranking order (10 pts) ---
        c6_max = 10
        if len(agent_rows) == len(gt_results) and len(agent_rows) > 0:
            agent_order = [r.get("batch_code", "") for r in agent_rows]
            gt_order = [r["batch_code"] for r in gt_results]
            if agent_order == gt_order:
                c6_score = 10
                c6_reason = ""
            else:
                # Partial credit using Kendall tau-like metric
                correct_pairs = 0
                total_pairs = 0
                gt_rank = {bc: i for i, bc in enumerate(gt_order)}
                for i in range(len(agent_order)):
                    for j in range(i + 1, len(agent_order)):
                        if agent_order[i] in gt_rank and agent_order[j] in gt_rank:
                            total_pairs += 1
                            if gt_rank[agent_order[i]] < gt_rank[agent_order[j]]:
                                correct_pairs += 1
                ratio = correct_pairs / total_pairs if total_pairs > 0 else 0
                c6_score = round(c6_max * ratio)
                c6_reason = f"Order match ratio: {ratio:.2f}"
        else:
            c6_score = 0
            c6_reason = f"Row count mismatch: expected {len(gt_results)}, got {len(agent_rows)}"

        eval_criteria["ranking_order"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": c6_reason if c6_score < c6_max else "",
        }
        total_score += c6_score
        max_score += c6_max

        # --- Criterion 7: Response summary (10 pts) ---
        c7_max = 10
        c7_score = 0
        # Check that response mentions top 5 items and action counts
        if gt_results:
            top5 = gt_results[:5]
            top5_mentioned = sum(
                1 for r in top5 if r["ingredient_name"] in action or r["batch_code"] in action
            )
            # Count actions in ground truth
            action_counts = {}
            for r in gt_results:
                a = r["recommended_action"]
                action_counts[a] = action_counts.get(a, 0) + 1

            # Check if counts mentioned
            counts_mentioned = 0
            for act_name, count in action_counts.items():
                if str(count) in action and act_name in action:
                    counts_mentioned += 1

            # Score: 5 pts for top-5 mention, 5 pts for action counts
            top5_pts = round(5 * top5_mentioned / 5) if top5_mentioned <= 5 else 5
            count_pts = round(5 * counts_mentioned / max(len(action_counts), 1))
            c7_score = top5_pts + count_pts

        c7_reason = "" if c7_score == c7_max else "Missing top-5 items or action count summary"

        eval_criteria["response_summary"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": c7_reason if c7_score < c7_max else "",
        }
        total_score += c7_score
        max_score += c7_max

        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ------------------------------------------------------------------
    # Verify: prove end-to-end solvability
    # ------------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import datetime

        # ---- Step 1: Read workspace config files ----
        config_path = os.path.join(self.workspace, "spoilage_config.yaml")
        with open(config_path) as f:
            config = yaml.safe_load(f)

        ref_date_str = config["reference_date"]
        ref_date = datetime.datetime.strptime(ref_date_str, "%Y-%m-%d")
        scoring = config["scoring"]
        temp_coeff = scoring["temp_penalty_coefficient"]
        cond_penalty_days = scoring["condition_flag_penalty_days"]
        waste_mult = scoring["waste_rate_multiplier"]
        thresholds = config["action_thresholds"]

        # Read fridge layout
        fridge_layout_path = os.path.join(self.workspace, "fridge_layout.json")
        with open(fridge_layout_path) as f:
            fridge_layout = json.load(f)

        # ---- Step 2: Read current stock files ----
        stock_items = []
        for fp in sorted(glob.glob(os.path.join(self.workspace, "current_stock_*.json"))):
            with open(fp) as f:
                stock_items.extend(json.load(f))

        # ---- Step 3: Read delivery notes for condition flags ----
        flagged_batches = set()
        for fp in sorted(glob.glob(os.path.join(self.workspace, "delivery_notes_*.txt"))):
            with open(fp) as f:
                content = f.read()
            current_batch = None
            for line in content.split("\n"):
                if line.startswith("Batch: "):
                    current_batch = line.replace("Batch: ", "").strip()
                if "CONDITION FLAG" in line and current_batch:
                    flagged_batches.add(current_batch)

        # ---- Step 4: Read menu plans (for summary context) ----
        menu_recipes = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "menu_plan_day*.csv"))):
            with open(fp, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rn = row["recipe_name"]
                    servings = int(row["planned_servings"])
                    menu_recipes[rn] = menu_recipes.get(rn, 0) + servings

        # ---- Step 5: Use tools to gather ingredient data ----
        # Get all ingredient IDs from stock
        stock_ingredient_ids = set(s["ingredient_id"] for s in stock_items)
        stock_batch_codes = set(s["batch_code"] for s in stock_items)

        # Get ingredient details via tool calls
        ingredient_details = {}
        for ing_id in sorted(stock_ingredient_ids):
            result = self.tools["get_ingredient_details"](ingredient_id=ing_id)
            if "error" not in result:
                ingredient_details[ing_id] = result

        # Get delivery info for each batch via tool calls
        batch_delivery_info = {}
        for stock in stock_items:
            result = self.tools["lookup_batch"](batch_code=stock["batch_code"])
            if "error" not in result:
                batch_delivery_info[stock["batch_code"]] = result

        # Get fridge temperatures for past 3 days
        fridge_temps = {}
        for fid in fridge_layout.keys():
            all_readings = []
            for d_offset in range(4):  # 0, 1, 2, 3 days ago
                d = ref_date - datetime.timedelta(days=d_offset)
                date_str = d.strftime("%Y-%m-%d")
                result = self.tools["get_fridge_temperatures"](
                    fridge_id=fid, date=date_str
                )
                all_readings.extend(result.get("readings", []))
            if all_readings:
                avg = sum(r["temperature_c"] for r in all_readings) / len(all_readings)
                fridge_temps[fid] = avg
            else:
                fridge_temps[fid] = 0.0

        # Get waste history per ingredient
        waste_totals = {}
        delivery_totals = {}
        for ing_id in sorted(stock_ingredient_ids):
            # Waste
            w_result = self.tools["get_waste_history"](ingredient_id=ing_id)
            total_w = sum(e["quantity_wasted"] for e in w_result.get("waste_entries", []))
            waste_totals[ing_id] = total_w

            # Delivery totals
            d_result = self.tools["get_deliveries_for_ingredient"](ingredient_id=ing_id)
            total_d = sum(d["quantity"] for d in d_result.get("deliveries", []))
            delivery_totals[ing_id] = total_d

        # Get recipe usage for context (for summary)
        planned_usage = {}
        for ing_id in sorted(stock_ingredient_ids):
            r_result = self.tools["get_recipe_usage"](ingredient_id=ing_id)
            total_planned = 0
            for rec in r_result.get("recipes", []):
                rn = rec["recipe_name"]
                if rn in menu_recipes:
                    total_planned += rec["quantity_per_serving"] * menu_recipes[rn]
            planned_usage[ing_id] = round(total_planned, 2)

        # ---- Step 6: Compute priority scores ----
        results = []
        for stock in stock_items:
            batch_code = stock["batch_code"]
            ing_id = stock["ingredient_id"]
            fridge_id = stock["fridge_id"]

            ing = ingredient_details.get(ing_id)
            delivery = batch_delivery_info.get(batch_code)
            if ing is None or delivery is None:
                continue

            del_date = datetime.datetime.strptime(delivery["delivery_date"], "%Y-%m-%d")
            days_since = (ref_date - del_date).days

            base_remaining = ing["shelf_life_days"] - days_since

            avg_temp = fridge_temps.get(fridge_id, 0.0)
            temp_excess = max(0, avg_temp - ing["max_storage_temp"])
            temp_pen = temp_excess * temp_coeff

            cond_pen = cond_penalty_days if batch_code in flagged_batches else 0

            effective_remaining = base_remaining - temp_pen - cond_pen

            total_w = waste_totals.get(ing_id, 0.0)
            total_d = delivery_totals.get(ing_id, 0.0)
            waste_rate = total_w / total_d if total_d > 0 else 0.0

            eff_for_score = max(effective_remaining, 0.1)
            spoilage_score = (1.0 / eff_for_score) * (1.0 + waste_rate * waste_mult)

            action_label = "MONITOR"
            if effective_remaining <= thresholds["DISCARD"]["max_effective_remaining"]:
                action_label = "DISCARD"
            elif effective_remaining <= thresholds["USE_IMMEDIATELY"]["max_effective_remaining"]:
                action_label = "USE_IMMEDIATELY"
            elif effective_remaining <= thresholds["USE_SOON"]["max_effective_remaining"]:
                action_label = "USE_SOON"

            results.append({
                "ingredient_name": ing["name"],
                "batch_code": batch_code,
                "category": ing["category"],
                "delivery_date": delivery["delivery_date"],
                "effective_remaining_days": round(effective_remaining, 1),
                "spoilage_risk_score": round(spoilage_score, 4),
                "recommended_action": action_label,
            })

        results.sort(key=lambda x: (-x["spoilage_risk_score"], x["ingredient_name"]))
        for i, r in enumerate(results):
            r["rank"] = i + 1

        # ---- Step 7: Write priority_list.csv ----
        csv_path = os.path.join(self.workspace, "priority_list.csv")
        fieldnames = [
            "rank", "ingredient_name", "batch_code", "category",
            "delivery_date", "effective_remaining_days",
            "spoilage_risk_score", "recommended_action",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow({k: r[k] for k in fieldnames})

        # ---- Step 8: Build action summary string ----
        action_counts = {}
        for r in results:
            a = r["recommended_action"]
            action_counts[a] = action_counts.get(a, 0) + 1

        top5 = results[:5]
        top5_lines = []
        for r in top5:
            top5_lines.append(
                f"  {r['rank']}. {r['ingredient_name']} (batch {r['batch_code']}): "
                f"effective remaining {r['effective_remaining_days']} days, "
                f"risk score {r['spoilage_risk_score']}, action: {r['recommended_action']}"
            )

        action_summary_parts = []
        for act_name in ["DISCARD", "USE_IMMEDIATELY", "USE_SOON", "MONITOR"]:
            cnt = action_counts.get(act_name, 0)
            if cnt > 0:
                action_summary_parts.append(f"{act_name}: {cnt}")

        action_string = (
            f"Priority list has been saved to priority_list.csv with {len(results)} batches.\n\n"
            f"Top 5 highest-risk items:\n"
            + "\n".join(top5_lines) + "\n\n"
            f"Action summary: " + ", ".join(action_summary_parts)
        )

        return self.step(action_string)
