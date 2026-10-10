"""
Ad Inventory Pricing Optimization - Task Environment
Provides tools for querying ad campaign/impression data and evaluates
the agent's pricing schedule output.
"""

import csv
import json
import os
import sqlite3
import yaml
from typing import Any, Dict, List, Tuple


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

    # ─── Tool Methods ───

    @tool(
        description="List shows with pagination. Returns show_id, name, genre, and weekly_listeners for each show.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20)",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_shows(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM shows")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT show_id, name, genre, weekly_listeners FROM shows ORDER BY show_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "shows": [
                {"show_id": r[0], "name": r[1], "genre": r[2], "weekly_listeners": r[3]}
                for r in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @tool(
        description="Get detailed information for a specific show including host and launch year.",
        parameters={
            "type": "object",
            "properties": {
                "show_id": {
                    "type": "integer",
                    "description": "The show ID to look up",
                },
            },
            "required": ["show_id"],
        },
    )
    def get_show_details(self, show_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM shows WHERE show_id = ?", (show_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": f"Show {show_id} not found"}
        return {
            "show_id": row[0],
            "name": row[1],
            "genre": row[2],
            "host": row[3],
            "weekly_listeners": row[4],
            "launch_year": row[5],
        }

    @tool(
        description="List regions with pagination. Returns region_id, region_name, country, and market_tier.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20)",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_regions(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM regions")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT region_id, region_name, country, market_tier FROM regions ORDER BY region_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "regions": [
                {"region_id": r[0], "region_name": r[1], "country": r[2], "market_tier": r[3]}
                for r in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @tool(
        description="Get region details by region_id including population.",
        parameters={
            "type": "object",
            "properties": {
                "region_id": {
                    "type": "integer",
                    "description": "The region ID to look up",
                },
            },
            "required": ["region_id"],
        },
    )
    def get_region_details(self, region_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM regions WHERE region_id = ?", (region_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": f"Region {region_id} not found"}
        return {
            "region_id": row[0],
            "region_name": row[1],
            "country": row[2],
            "market_tier": row[3],
            "population": row[4],
        }

    @tool(
        description="List active campaigns, optionally filtered by show_id and/or region_id. Returns campaign details including advertiser_id and base_cpm. Paginated.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20)",
                },
                "show_id": {
                    "type": "integer",
                    "description": "Optional: filter by show_id",
                },
                "region_id": {
                    "type": "integer",
                    "description": "Optional: filter by region_id",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_active_campaigns(
        self, page: int, page_size: int, show_id: int = None, region_id: int = None
    ) -> dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        where = "WHERE status = 'active'"
        params: list = []
        if show_id is not None:
            where += " AND show_id = ?"
            params.append(show_id)
        if region_id is not None:
            where += " AND region_id = ?"
            params.append(region_id)

        cur.execute(f"SELECT COUNT(*) FROM campaigns {where}", params)
        total = cur.fetchone()[0]

        cur.execute(
            f"SELECT campaign_id, advertiser_id, show_id, region_id, quarter, base_cpm "
            f"FROM campaigns {where} ORDER BY campaign_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "campaigns": [
                {
                    "campaign_id": r[0],
                    "advertiser_id": r[1],
                    "show_id": r[2],
                    "region_id": r[3],
                    "quarter": r[4],
                    "base_cpm": r[5],
                }
                for r in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @tool(
        description="Get advertiser information by advertiser_id, including company name, ad category, and budget tier.",
        parameters={
            "type": "object",
            "properties": {
                "advertiser_id": {
                    "type": "integer",
                    "description": "The advertiser ID to look up",
                },
            },
            "required": ["advertiser_id"],
        },
    )
    def get_advertiser_info(self, advertiser_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM advertisers WHERE advertiser_id = ?", (advertiser_id,)
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": f"Advertiser {advertiser_id} not found"}
        return {
            "advertiser_id": row[0],
            "company_name": row[1],
            "category": row[2],
            "budget_tier": row[3],
            "annual_budget": row[4],
        }

    @tool(
        description="Get aggregated impression statistics for a specific show-region pair. Returns total available slots, total filled slots, overall fill rate, total revenue, and number of log entries.",
        parameters={
            "type": "object",
            "properties": {
                "show_id": {
                    "type": "integer",
                    "description": "The show ID",
                },
                "region_id": {
                    "type": "integer",
                    "description": "The region ID",
                },
            },
            "required": ["show_id", "region_id"],
        },
    )
    def get_impression_stats(self, show_id: int, region_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT SUM(available_slots), SUM(filled_slots), SUM(revenue), COUNT(*) "
            "FROM impression_logs WHERE show_id = ? AND region_id = ?",
            (show_id, region_id),
        )
        row = cur.fetchone()
        conn.close()
        total_avail = row[0] or 0
        total_filled = row[1] or 0
        total_rev = row[2] or 0.0
        count = row[3] or 0
        fill_rate = round(total_filled / total_avail, 4) if total_avail > 0 else 0.0
        return {
            "show_id": show_id,
            "region_id": region_id,
            "total_available_slots": total_avail,
            "total_filled_slots": total_filled,
            "fill_rate": fill_rate,
            "total_revenue": round(total_rev, 2),
            "log_entries": count,
        }

    @tool(
        description="Get revenue breakdown by advertiser category for a specific show-region pair from impression logs. Returns each category's total revenue contribution.",
        parameters={
            "type": "object",
            "properties": {
                "show_id": {
                    "type": "integer",
                    "description": "The show ID",
                },
                "region_id": {
                    "type": "integer",
                    "description": "The region ID",
                },
            },
            "required": ["show_id", "region_id"],
        },
    )
    def get_revenue_by_category(self, show_id: int, region_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.category, SUM(il.revenue) as total_revenue
            FROM impression_logs il
            JOIN campaigns c ON il.campaign_id = c.campaign_id
            JOIN advertisers a ON c.advertiser_id = a.advertiser_id
            WHERE il.show_id = ? AND il.region_id = ?
            GROUP BY a.category
            ORDER BY total_revenue DESC
            """,
            (show_id, region_id),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "show_id": show_id,
            "region_id": region_id,
            "category_revenue": [
                {"category": r[0], "total_revenue": round(r[1], 2)} for r in rows
            ],
        }

    # ─── Evaluation ───

    def _compute_ground_truth(self) -> list:
        """Compute the expected pricing schedule from DB and workspace files."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # 1. Find show-region pairs with active campaigns AND impression logs
        cur.execute(
            """
            SELECT DISTINCT c.show_id, c.region_id
            FROM campaigns c
            INNER JOIN (SELECT DISTINCT show_id, region_id FROM impression_logs) il
                ON c.show_id = il.show_id AND c.region_id = il.region_id
            WHERE c.status = 'active'
            ORDER BY c.show_id, c.region_id
            """
        )
        pairs = cur.fetchall()

        # 2. Load workspace config files
        with open(os.path.join(self.workspace, "pricing_rules.yaml")) as f:
            pricing_rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "seasonal_factors.json")) as f:
            seasonal_config = json.load(f)
        target_quarter = seasonal_config["target_quarter"]
        seasonal_factor = seasonal_config["factors"][target_quarter]

        fill_rate_adj = pricing_rules["fill_rate_adjustments"]
        geo_adj = pricing_rules["geo_concentration_adjustments"]

        # Load geo profiles from all batch files
        geo_profiles = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("show_geo_profile_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                    geo_profiles.update(data)

        # Load category demand benchmarks from all benchmark files
        category_benchmarks = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("category_demand_benchmark_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                    category_benchmarks.update(data.get("category_benchmarks", {}))

        schedule = []
        for show_id, region_id in pairs:
            # Current CPM: average base_cpm of active campaigns for this pair
            cur.execute(
                "SELECT AVG(base_cpm) FROM campaigns WHERE show_id = ? AND region_id = ? AND status = 'active'",
                (show_id, region_id),
            )
            current_cpm = round(cur.fetchone()[0], 2)

            # Fill rate
            cur.execute(
                "SELECT SUM(available_slots), SUM(filled_slots) FROM impression_logs WHERE show_id = ? AND region_id = ?",
                (show_id, region_id),
            )
            row = cur.fetchone()
            total_avail = row[0] or 0
            total_filled = row[1] or 0
            fill_rate = round(total_filled / total_avail, 4) if total_avail > 0 else 0.0

            # Fill rate multiplier
            fill_mult = 1.0
            for tier_info in fill_rate_adj.values():
                if tier_info["min_rate"] <= fill_rate < tier_info["max_rate"]:
                    fill_mult = tier_info["multiplier"]
                    break
                if fill_rate == 1.0 and tier_info["max_rate"] == 1.0 and tier_info["min_rate"] <= fill_rate:
                    fill_mult = tier_info["multiplier"]
                    break

            # Geo concentration
            show_geo = geo_profiles.get(str(show_id), {})
            listener_dist = show_geo.get("listener_distribution", {})
            geo_share = listener_dist.get(str(region_id), {}).get("listener_share", 0.0)

            geo_mult = 0.90  # default: minimal
            for tier_info in geo_adj.values():
                if tier_info["min_share"] <= geo_share < tier_info["max_share"]:
                    geo_mult = tier_info["multiplier"]
                    break
                if geo_share == 1.0 and tier_info["max_share"] == 1.0 and tier_info["min_share"] <= geo_share:
                    geo_mult = tier_info["multiplier"]
                    break

            # Dominant category by revenue for this pair
            cur.execute(
                """
                SELECT a.category, SUM(il.revenue) as total_rev
                FROM impression_logs il
                JOIN campaigns c ON il.campaign_id = c.campaign_id
                JOIN advertisers a ON c.advertiser_id = a.advertiser_id
                WHERE il.show_id = ? AND il.region_id = ?
                GROUP BY a.category
                ORDER BY total_rev DESC
                LIMIT 1
                """,
                (show_id, region_id),
            )
            cat_row = cur.fetchone()
            dominant_category = cat_row[0] if cat_row else "Unknown"

            # Category factor (demand_index from benchmarks)
            cat_factor = category_benchmarks.get(dominant_category, {}).get("demand_index", 1.0)

            # Show name
            cur.execute("SELECT name FROM shows WHERE show_id = ?", (show_id,))
            show_name = cur.fetchone()[0]

            # Region name
            cur.execute("SELECT region_name FROM regions WHERE region_id = ?", (region_id,))
            region_name = cur.fetchone()[0]

            recommended_cpm = round(
                current_cpm * fill_mult * geo_mult * cat_factor * seasonal_factor, 2
            )
            adjustment_pct = round((recommended_cpm / current_cpm - 1) * 100, 2)

            schedule.append(
                {
                    "show_id": show_id,
                    "show_name": show_name,
                    "region_id": region_id,
                    "region_name": region_name,
                    "current_cpm": current_cpm,
                    "fill_rate": fill_rate,
                    "fill_rate_multiplier": fill_mult,
                    "geo_concentration": geo_share,
                    "geo_multiplier": geo_mult,
                    "category": dominant_category,
                    "category_factor": cat_factor,
                    "seasonal_factor": seasonal_factor,
                    "recommended_cpm": recommended_cpm,
                    "adjustment_pct": adjustment_pct,
                }
            )

        conn.close()
        # Sort by show_id, then region_id
        schedule.sort(key=lambda x: (x["show_id"], x["region_id"]))
        return schedule

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
        gt_count = len(ground_truth)

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: pricing_schedule.csv exists (10 pts) ---
        csv_path = os.path.join(self.workspace, "pricing_schedule.csv")
        csv_exists = os.path.exists(csv_path)
        eval_criteria["file_exists"] = {
            "passed": csv_exists,
            "score": 10 if csv_exists else 0,
            "max_score": 10,
            "reason": "" if csv_exists else "pricing_schedule.csv not found in workspace",
        }
        total_score += eval_criteria["file_exists"]["score"]
        max_score += 10

        if not csv_exists:
            # Can't evaluate further
            for name, pts in [
                ("correct_columns", 10),
                ("correct_row_count", 15),
                ("correct_show_region_pairs", 15),
                ("correct_fill_rates", 15),
                ("correct_multipliers", 15),
                ("correct_recommended_cpm", 20),
            ]:
                eval_criteria[name] = {
                    "passed": False,
                    "score": 0,
                    "max_score": pts,
                    "reason": "Cannot evaluate: file missing",
                }
                max_score += pts

            return total_score / max_score, {
                "eval_criteria": eval_criteria,
                "total_score": total_score,
                "max_score": max_score,
            }

        # Read the CSV
        try:
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                submitted_rows = list(reader)
                submitted_cols = reader.fieldnames or []
        except Exception as e:
            for name, pts in [
                ("correct_columns", 10),
                ("correct_row_count", 15),
                ("correct_show_region_pairs", 15),
                ("correct_fill_rates", 15),
                ("correct_multipliers", 15),
                ("correct_recommended_cpm", 20),
            ]:
                eval_criteria[name] = {
                    "passed": False,
                    "score": 0,
                    "max_score": pts,
                    "reason": f"Cannot parse CSV: {e}",
                }
                max_score += pts
            return total_score / max_score, {
                "eval_criteria": eval_criteria,
                "total_score": total_score,
                "max_score": max_score,
            }

        # --- Criterion 2: Correct columns (10 pts) ---
        expected_cols = [
            "show_id", "show_name", "region_id", "region_name",
            "current_cpm", "fill_rate", "fill_rate_multiplier",
            "geo_concentration", "geo_multiplier",
            "category", "category_factor",
            "seasonal_factor", "recommended_cpm", "adjustment_pct",
        ]
        cols_match = submitted_cols == expected_cols
        eval_criteria["correct_columns"] = {
            "passed": cols_match,
            "score": 10 if cols_match else 0,
            "max_score": 10,
            "reason": "" if cols_match else f"Expected columns {expected_cols}, got {submitted_cols}",
        }
        total_score += eval_criteria["correct_columns"]["score"]
        max_score += 10

        # --- Criterion 3: Correct row count (15 pts) ---
        count_match = len(submitted_rows) == gt_count
        eval_criteria["correct_row_count"] = {
            "passed": count_match,
            "score": 15 if count_match else 0,
            "max_score": 15,
            "reason": "" if count_match else f"Expected {gt_count} rows, got {len(submitted_rows)}",
        }
        total_score += eval_criteria["correct_row_count"]["score"]
        max_score += 15

        # Build lookup from submitted rows
        submitted_lookup = {}
        for row in submitted_rows:
            try:
                key = (int(row["show_id"]), int(row["region_id"]))
                submitted_lookup[key] = row
            except (KeyError, ValueError):
                pass

        gt_lookup = {(r["show_id"], r["region_id"]): r for r in ground_truth}

        # --- Criterion 4: Correct show-region pairs (15 pts) ---
        gt_keys = set(gt_lookup.keys())
        sub_keys = set(submitted_lookup.keys())
        pairs_match = gt_keys == sub_keys
        eval_criteria["correct_show_region_pairs"] = {
            "passed": pairs_match,
            "score": 15 if pairs_match else 0,
            "max_score": 15,
            "reason": "" if pairs_match else f"Missing pairs: {gt_keys - sub_keys}, extra pairs: {sub_keys - gt_keys}",
        }
        total_score += eval_criteria["correct_show_region_pairs"]["score"]
        max_score += 15

        # --- Criterion 5: Correct fill rates (15 pts) ---
        common_keys = gt_keys & sub_keys
        fill_correct = 0
        fill_total = len(common_keys)
        for key in common_keys:
            try:
                sub_fr = float(submitted_lookup[key]["fill_rate"])
                gt_fr = gt_lookup[key]["fill_rate"]
                if abs(sub_fr - gt_fr) < 0.005:
                    fill_correct += 1
            except (KeyError, ValueError):
                pass

        fill_pct = fill_correct / fill_total if fill_total > 0 else 0.0
        fill_score = round(15 * fill_pct)
        eval_criteria["correct_fill_rates"] = {
            "passed": fill_pct >= 0.95,
            "score": fill_score,
            "max_score": 15,
            "reason": "" if fill_pct >= 0.95 else f"{fill_correct}/{fill_total} fill rates correct",
        }
        total_score += fill_score
        max_score += 15

        # --- Criterion 6: Correct multipliers and factors (15 pts) ---
        mult_correct = 0
        mult_total = len(common_keys) * 4  # 4 factors per row
        for key in common_keys:
            gt_row = gt_lookup[key]
            sub_row = submitted_lookup[key]
            for field in ["fill_rate_multiplier", "geo_multiplier", "category_factor", "seasonal_factor"]:
                try:
                    if abs(float(sub_row[field]) - float(gt_row[field])) < 0.005:
                        mult_correct += 1
                except (KeyError, ValueError):
                    pass

        mult_pct = mult_correct / mult_total if mult_total > 0 else 0.0
        mult_score = round(15 * mult_pct)
        eval_criteria["correct_multipliers"] = {
            "passed": mult_pct >= 0.95,
            "score": mult_score,
            "max_score": 15,
            "reason": "" if mult_pct >= 0.95 else f"{mult_correct}/{mult_total} factor values correct",
        }
        total_score += mult_score
        max_score += 15

        # --- Criterion 7: Correct recommended CPM (20 pts) ---
        cpm_correct = 0
        cpm_total = len(common_keys)
        for key in common_keys:
            try:
                sub_cpm = float(submitted_lookup[key]["recommended_cpm"])
                gt_cpm = gt_lookup[key]["recommended_cpm"]
                if abs(sub_cpm - gt_cpm) < 0.015:
                    cpm_correct += 1
            except (KeyError, ValueError):
                pass

        cpm_pct = cpm_correct / cpm_total if cpm_total > 0 else 0.0
        cpm_score = round(20 * cpm_pct)
        eval_criteria["correct_recommended_cpm"] = {
            "passed": cpm_pct >= 0.95,
            "score": cpm_score,
            "max_score": 20,
            "reason": "" if cpm_pct >= 0.95 else f"{cpm_correct}/{cpm_total} recommended CPMs correct",
        }
        total_score += cpm_score
        max_score += 20

        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

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
        import csv as _csv

        tool_calls = 0

        def call_tool(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        # Step 1: Load workspace config files
        with open(os.path.join(self.workspace, "pricing_rules.yaml")) as f:
            pricing_rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "seasonal_factors.json")) as f:
            seasonal_config = json.load(f)
        with open(os.path.join(self.workspace, "policy_overview.md")) as f:
            policy = f.read()

        target_quarter = seasonal_config["target_quarter"]
        seasonal_factor = seasonal_config["factors"][target_quarter]
        fill_rate_adj = pricing_rules["fill_rate_adjustments"]
        geo_adj = pricing_rules["geo_concentration_adjustments"]
        output_cols = pricing_rules["output_format"]["columns"]

        # Load geo profiles from workspace
        geo_profiles = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("show_geo_profile_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                    geo_profiles.update(data)

        # Load category benchmarks from workspace
        category_benchmarks = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("category_demand_benchmark_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                    category_benchmarks.update(data.get("category_benchmarks", {}))

        # Step 2: Get all active campaigns via tool calls (paginated)
        all_campaigns = []
        page = 1
        while True:
            result = call_tool("list_active_campaigns", page=page, page_size=20)
            all_campaigns.extend(result["campaigns"])
            if page * 20 >= result["total"]:
                break
            page += 1

        # Identify unique show-region pairs from active campaigns
        show_region_pairs = set()
        pair_campaigns = {}  # (show_id, region_id) -> list of campaigns
        advertiser_ids = set()
        for camp in all_campaigns:
            key = (camp["show_id"], camp["region_id"])
            show_region_pairs.add(key)
            pair_campaigns.setdefault(key, []).append(camp)
            advertiser_ids.add(camp["advertiser_id"])

        # Step 3: Get show details for all relevant shows
        show_ids = set(k[0] for k in show_region_pairs)
        show_details = {}
        for sid in sorted(show_ids):
            show_details[sid] = call_tool("get_show_details", show_id=sid)

        # Step 4: Get region details for all relevant regions
        region_ids = set(k[1] for k in show_region_pairs)
        region_details = {}
        for rid in sorted(region_ids):
            region_details[rid] = call_tool("get_region_details", region_id=rid)

        # Step 5: Get impression stats for each show-region pair
        impression_stats = {}
        for show_id, region_id in sorted(show_region_pairs):
            stats = call_tool("get_impression_stats", show_id=show_id, region_id=region_id)
            impression_stats[(show_id, region_id)] = stats

        # Filter pairs that have impression logs
        valid_pairs = set()
        for key, stats in impression_stats.items():
            if stats["log_entries"] > 0:
                valid_pairs.add(key)

        # Step 6: Get revenue by category for dominant category determination
        pair_dominant_category = {}
        for show_id, region_id in sorted(valid_pairs):
            rev_data = call_tool(
                "get_revenue_by_category", show_id=show_id, region_id=region_id
            )
            cat_rev = rev_data["category_revenue"]
            if cat_rev:
                pair_dominant_category[(show_id, region_id)] = cat_rev[0]["category"]
            else:
                pair_dominant_category[(show_id, region_id)] = "Unknown"

        # Step 7: Compute pricing schedule
        schedule = []
        for show_id, region_id in sorted(valid_pairs):
            camps = pair_campaigns.get((show_id, region_id), [])
            if not camps:
                continue

            current_cpm = round(
                sum(c["base_cpm"] for c in camps) / len(camps), 2
            )

            stats = impression_stats[(show_id, region_id)]
            fill_rate = stats["fill_rate"]

            # Fill rate multiplier
            fill_mult = 1.0
            for tier_info in fill_rate_adj.values():
                if tier_info["min_rate"] <= fill_rate < tier_info["max_rate"]:
                    fill_mult = tier_info["multiplier"]
                    break
                if fill_rate == 1.0 and tier_info["max_rate"] == 1.0 and tier_info["min_rate"] <= fill_rate:
                    fill_mult = tier_info["multiplier"]
                    break

            # Geo concentration
            show_geo = geo_profiles.get(str(show_id), {})
            listener_dist = show_geo.get("listener_distribution", {})
            geo_share = listener_dist.get(str(region_id), {}).get("listener_share", 0.0)

            geo_mult = 0.90  # default minimal
            for tier_info in geo_adj.values():
                if tier_info["min_share"] <= geo_share < tier_info["max_share"]:
                    geo_mult = tier_info["multiplier"]
                    break
                if geo_share == 1.0 and tier_info["max_share"] == 1.0 and tier_info["min_share"] <= geo_share:
                    geo_mult = tier_info["multiplier"]
                    break

            # Category factor
            dominant_cat = pair_dominant_category.get((show_id, region_id), "Unknown")
            cat_factor = category_benchmarks.get(dominant_cat, {}).get("demand_index", 1.0)

            recommended_cpm = round(
                current_cpm * fill_mult * geo_mult * cat_factor * seasonal_factor, 2
            )
            adjustment_pct = round((recommended_cpm / current_cpm - 1) * 100, 2)

            show_name = show_details[show_id]["name"]
            region_name = region_details[region_id]["region_name"]

            schedule.append(
                {
                    "show_id": show_id,
                    "show_name": show_name,
                    "region_id": region_id,
                    "region_name": region_name,
                    "current_cpm": current_cpm,
                    "fill_rate": fill_rate,
                    "fill_rate_multiplier": fill_mult,
                    "geo_concentration": geo_share,
                    "geo_multiplier": geo_mult,
                    "category": dominant_cat,
                    "category_factor": cat_factor,
                    "seasonal_factor": seasonal_factor,
                    "recommended_cpm": recommended_cpm,
                    "adjustment_pct": adjustment_pct,
                }
            )

        # Sort by show_id, then region_id
        schedule.sort(key=lambda x: (x["show_id"], x["region_id"]))

        # Step 8: Write pricing_schedule.csv
        csv_path = os.path.join(self.workspace, "pricing_schedule.csv")
        with open(csv_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=output_cols)
            writer.writeheader()
            writer.writerows(schedule)

        # Step 9: Build action string
        action = (
            f"Completed pricing schedule with {len(schedule)} show-region pairs. "
            f"Applied fill rate adjustments, geographic concentration multipliers, "
            f"category demand factors, and seasonal factor ({seasonal_factor}) for {target_quarter}. "
            f"Output saved to pricing_schedule.csv."
        )

        print(f"verify: {tool_calls} tool calls made")
        return self.step(action)
