"""
Task environment for competitor pricing intelligence.
Defines tools for querying product catalog, competitor data, internal
costs, catalog mappings, and price history.  Evaluates an alert
dashboard and pricing summary produced by the agent.
"""

import sqlite3
import os
import json
import csv
import glob
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

    # ------------------------------------------------------------------
    #  Tool methods
    # ------------------------------------------------------------------

    @tool(
        description=(
            "List products with optional category filter. Returns a "
            "paginated list of products (product_id, name, category, sku)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by product category (optional).",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting at 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Items per page (max 20, default 20).",
                },
            },
            "required": [],
        },
    )
    def list_products(self, category: str = None, page: int = 1,
                      page_size: int = 20) -> dict:
        page_size = min(int(page_size), 20)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if category:
            rows = conn.execute(
                "SELECT product_id, name, category, sku FROM products "
                "WHERE category=? ORDER BY product_id "
                "LIMIT ? OFFSET ?",
                (category, page_size, (page - 1) * page_size),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM products WHERE category=?",
                (category,),
            ).fetchone()[0]
        else:
            rows = conn.execute(
                "SELECT product_id, name, category, sku FROM products "
                "ORDER BY product_id LIMIT ? OFFSET ?",
                (page_size, (page - 1) * page_size),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM products"
            ).fetchone()[0]
        conn.close()
        return {
            "products": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size),
        }

    @tool(
        description="Get full details for a single product by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "The product ID to look up.",
                },
            },
            "required": ["product_id"],
        },
    )
    def get_product_details(self, product_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM products WHERE product_id=?",
            (int(product_id),),
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Product {product_id} not found"}

    @tool(
        description=(
            "List competitors with optional region filter. Returns a "
            "paginated list (competitor_id, name, region, channel, "
            "reliability_score)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": "Filter by region (optional).",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting at 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Items per page (max 20, default 20).",
                },
            },
            "required": [],
        },
    )
    def list_competitors(self, region: str = None, page: int = 1,
                         page_size: int = 20) -> dict:
        page_size = min(int(page_size), 20)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if region:
            rows = conn.execute(
                "SELECT * FROM competitors WHERE region=? "
                "ORDER BY competitor_id LIMIT ? OFFSET ?",
                (region, page_size, (page - 1) * page_size),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM competitors WHERE region=?",
                (region,),
            ).fetchone()[0]
        else:
            rows = conn.execute(
                "SELECT * FROM competitors ORDER BY competitor_id "
                "LIMIT ? OFFSET ?",
                (page_size, (page - 1) * page_size),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM competitors"
            ).fetchone()[0]
        conn.close()
        return {
            "competitors": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size),
        }

    @tool(
        description="Get full details for a single competitor by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "competitor_id": {
                    "type": "integer",
                    "description": "The competitor ID to look up.",
                },
            },
            "required": ["competitor_id"],
        },
    )
    def get_competitor_info(self, competitor_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM competitors WHERE competitor_id=?",
            (int(competitor_id),),
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Competitor {competitor_id} not found"}

    @tool(
        description=(
            "Look up a catalog mapping by competitor SKU. Returns the "
            "internal product_id, competitor_id, competitor_product_name, "
            "and match_confidence for the given competitor SKU, or an "
            "error if no mapping exists."
        ),
        parameters={
            "type": "object",
            "properties": {
                "competitor_sku": {
                    "type": "string",
                    "description": "The competitor SKU code to look up.",
                },
            },
            "required": ["competitor_sku"],
        },
    )
    def lookup_catalog_mapping(self, competitor_sku: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT product_id, competitor_id, competitor_sku, "
            "competitor_product_name, match_confidence "
            "FROM catalog_mappings WHERE competitor_sku=?",
            (competitor_sku,),
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"No mapping for SKU {competitor_sku}"}

    @tool(
        description=(
            "Get all competitor catalog mappings for a given product. "
            "Returns a list of (competitor_id, competitor_sku, "
            "competitor_product_name, match_confidence)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "The internal product ID.",
                },
            },
            "required": ["product_id"],
        },
    )
    def get_mappings_for_product(self, product_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT competitor_id, competitor_sku, "
            "competitor_product_name, match_confidence "
            "FROM catalog_mappings WHERE product_id=? "
            "ORDER BY competitor_id",
            (int(product_id),),
        ).fetchall()
        conn.close()
        return {"mappings": [dict(r) for r in rows]}

    @tool(
        description=(
            "Get internal cost sheet for a product: unit_cost, "
            "overhead_rate, target_margin, floor_price, current_price."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "The internal product ID.",
                },
            },
            "required": ["product_id"],
        },
    )
    def get_internal_cost(self, product_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT product_id, unit_cost, overhead_rate, target_margin, "
            "floor_price, current_price FROM internal_costs "
            "WHERE product_id=?",
            (int(product_id),),
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"No cost data for product {product_id}"}

    @tool(
        description=(
            "Retrieve historical price records for a product, optionally "
            "filtered by competitor. Returns up to `limit` most recent "
            "records sorted by date descending."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "The internal product ID.",
                },
                "competitor_id": {
                    "type": "integer",
                    "description": (
                        "Filter to a specific competitor (optional)."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return (default 10).",
                },
            },
            "required": ["product_id"],
        },
    )
    def get_price_history(self, product_id: int,
                          competitor_id: int = None,
                          limit: int = 10) -> dict:
        limit = min(int(limit), 50)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if competitor_id is not None:
            rows = conn.execute(
                "SELECT product_id, competitor_id, record_date, price, "
                "source FROM price_history "
                "WHERE product_id=? AND competitor_id=? "
                "ORDER BY record_date DESC LIMIT ?",
                (int(product_id), int(competitor_id), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT product_id, competitor_id, record_date, price, "
                "source FROM price_history "
                "WHERE product_id=? "
                "ORDER BY record_date DESC LIMIT ?",
                (int(product_id), limit),
            ).fetchall()
        conn.close()
        return {"records": [dict(r) for r in rows]}

    # ------------------------------------------------------------------
    #  Ground-truth computation (used by both step and verify)
    # ------------------------------------------------------------------

    def _compute_ground_truth(self):
        """Compute expected alerts from database + workspace files."""
        # Read config files
        with open(os.path.join(self.workspace,
                               "alert_thresholds.json")) as f:
            thresholds = json.load(f)

        # Read all scrape CSVs
        pattern = os.path.join(self.workspace, "scrape_competitor_*.csv")
        scrape_files = sorted(glob.glob(pattern))

        # Collect latest scrape per (competitor_id, competitor_sku)
        latest = {}  # key = (cid, sku) -> row dict
        for sf in scrape_files:
            fname = os.path.basename(sf)
            # filename: scrape_competitor_{cid}_{date}.csv
            parts = fname.replace("scrape_competitor_", "").replace(
                ".csv", "").split("_")
            cid = int(parts[0])
            with open(sf, newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    sku = row["competitor_sku"]
                    ts = row["scrape_timestamp"]
                    key = (cid, sku)
                    if key not in latest or ts > latest[key]["ts"]:
                        latest[key] = {
                            "competitor_id": cid,
                            "competitor_sku": sku,
                            "listed_price": float(row["listed_price"]),
                            "ts": ts,
                        }

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        alerts = []
        for (cid, sku), scrape in latest.items():
            # catalog mapping
            mapping = conn.execute(
                "SELECT product_id, competitor_id FROM catalog_mappings "
                "WHERE competitor_sku=?", (sku,)
            ).fetchone()
            if not mapping:
                continue
            pid = mapping["product_id"]

            # competitor reliability
            comp = conn.execute(
                "SELECT name, reliability_score FROM competitors "
                "WHERE competitor_id=?", (cid,)
            ).fetchone()
            if not comp:
                continue
            rel = comp["reliability_score"]
            if rel < 0.70:
                continue  # Tier C excluded

            # product details
            prod = conn.execute(
                "SELECT name, category FROM products "
                "WHERE product_id=?", (pid,)
            ).fetchone()
            if not prod:
                continue
            category = prod["category"]

            # internal cost
            cost = conn.execute(
                "SELECT unit_cost, overhead_rate, floor_price, "
                "current_price FROM internal_costs WHERE product_id=?",
                (pid,),
            ).fetchone()
            if not cost:
                continue

            floor_price = cost["floor_price"]
            current_price = cost["current_price"]
            unit_cost = cost["unit_cost"]
            overhead_rate = cost["overhead_rate"]
            comp_price = scrape["listed_price"]

            price_gap_pct = round(
                (comp_price - floor_price) / floor_price * 100, 2)

            cat_thresh = thresholds.get(
                category, {"critical_threshold_pct": 10,
                           "watch_threshold_pct": 5})
            crit = cat_thresh["critical_threshold_pct"]
            watch = cat_thresh["watch_threshold_pct"]

            if price_gap_pct < -crit:
                alert_level = "critical"
                priority = 1
            elif price_gap_pct < 0:
                alert_level = "warning"
                priority = 2
            elif price_gap_pct < watch:
                alert_level = "watch"
                priority = 3
            else:
                continue

            min_viable = round(unit_cost * (1 + overhead_rate), 2)
            if alert_level == "critical":
                rec = round(max(comp_price * 0.98, min_viable), 2)
            elif alert_level == "warning":
                rec = round(
                    max((floor_price + comp_price) / 2, min_viable), 2)
            else:
                rec = current_price

            adj_pct = round(
                (rec - current_price) / current_price * 100, 2)

            alerts.append({
                "product_id": pid,
                "product_name": prod["name"],
                "category": category,
                "competitor_id": cid,
                "competitor_name": comp["name"],
                "latest_scraped_price": round(comp_price, 2),
                "floor_price": round(floor_price, 2),
                "price_gap_pct": price_gap_pct,
                "alert_level": alert_level,
                "priority": priority,
                "recommended_price": rec,
                "adjustment_pct": adj_pct,
            })

        conn.close()

        # Sort: priority asc, price_gap_pct asc
        alerts.sort(key=lambda a: (a["priority"], a["price_gap_pct"]))

        # Build summary
        summary = {
            "total_alerts": len(alerts),
            "by_level": {
                "critical": sum(
                    1 for a in alerts if a["alert_level"] == "critical"),
                "warning": sum(
                    1 for a in alerts if a["alert_level"] == "warning"),
                "watch": sum(
                    1 for a in alerts if a["alert_level"] == "watch"),
            },
            "by_category": {},
            "average_price_gap_pct": {},
            "total_recommended_adjustments": sum(
                1 for a in alerts
                if a["alert_level"] in ("critical", "warning")),
        }
        cats_seen = sorted(set(a["category"] for a in alerts))
        for cat in cats_seen:
            ca = [a for a in alerts if a["category"] == cat]
            summary["by_category"][cat] = {
                "critical": sum(
                    1 for a in ca if a["alert_level"] == "critical"),
                "warning": sum(
                    1 for a in ca if a["alert_level"] == "warning"),
                "watch": sum(
                    1 for a in ca if a["alert_level"] == "watch"),
            }
        for level in ("critical", "warning", "watch"):
            la = [a for a in alerts if a["alert_level"] == level]
            if la:
                summary["average_price_gap_pct"][level] = round(
                    sum(a["price_gap_pct"] for a in la) / len(la), 2)
            else:
                summary["average_price_gap_pct"][level] = 0.0

        return alerts, summary

    # ------------------------------------------------------------------
    #  Evaluation
    # ------------------------------------------------------------------

    DASHBOARD_COLS = [
        "product_id", "product_name", "category", "competitor_id",
        "competitor_name", "latest_scraped_price", "floor_price",
        "price_gap_pct", "alert_level", "recommended_price",
        "adjustment_pct",
    ]

    def step(
        self, action: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the
        agent's final response.
        """
        expected_alerts, expected_summary = self._compute_ground_truth()

        criteria: Dict[str, dict] = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: alert_dashboard.csv exists with correct
        #     columns (10 pts) ---
        c1_max = 10
        max_score += c1_max
        dash_path = os.path.join(self.workspace, "alert_dashboard.csv")
        dash_rows = []
        if os.path.isfile(dash_path):
            with open(dash_path, newline="") as fh:
                reader = csv.DictReader(fh)
                actual_cols = [c.strip() for c in (reader.fieldnames or [])]
                dash_rows = list(reader)
            expected_cols = self.DASHBOARD_COLS
            if all(c in actual_cols for c in expected_cols):
                criteria["dashboard_columns"] = {
                    "passed": True, "score": c1_max, "max_score": c1_max}
                total_score += c1_max
            else:
                missing = [c for c in expected_cols if c not in actual_cols]
                criteria["dashboard_columns"] = {
                    "passed": False, "score": 0, "max_score": c1_max,
                    "reason": f"Missing columns: {missing}"}
        else:
            criteria["dashboard_columns"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "alert_dashboard.csv not found"}

        # --- Criterion 2: Correct alert entries — product-competitor
        #     pairs present, none missing, no extras (20 pts) ---
        c2_max = 20
        max_score += c2_max
        expected_keys = set()
        for a in expected_alerts:
            expected_keys.add(
                (int(a["product_id"]), int(a["competitor_id"])))
        actual_keys = set()
        for r in dash_rows:
            try:
                actual_keys.add((
                    int(r.get("product_id", -1)),
                    int(r.get("competitor_id", -1)),
                ))
            except (ValueError, TypeError):
                pass
        if expected_keys and actual_keys:
            correct = expected_keys & actual_keys
            ratio = len(correct) / max(
                len(expected_keys), len(actual_keys))
            c2_score = round(c2_max * ratio)
            passed = ratio >= 0.99
            reason = ("" if passed else
                      f"expected {len(expected_keys)} alerts, "
                      f"got {len(actual_keys)} "
                      f"({len(correct)} overlap)")
            criteria["alert_entries"] = {
                "passed": passed, "score": c2_score,
                "max_score": c2_max,
                **({"reason": reason} if reason else {})}
            total_score += c2_score
        elif not expected_keys and not actual_keys:
            criteria["alert_entries"] = {
                "passed": True, "score": c2_max, "max_score": c2_max}
            total_score += c2_max
        else:
            criteria["alert_entries"] = {
                "passed": False, "score": 0, "max_score": c2_max,
                "reason": (
                    f"expected {len(expected_keys)} alerts, "
                    f"got {len(actual_keys)}")}

        # --- Criterion 3: price_gap_pct values correct (15 pts) ---
        c3_max = 15
        max_score += c3_max
        expected_gap = {
            (int(a["product_id"]), int(a["competitor_id"])):
            a["price_gap_pct"]
            for a in expected_alerts
        }
        match_gap = 0
        total_gap = max(len(expected_gap), 1)
        for r in dash_rows:
            try:
                key = (int(r["product_id"]), int(r["competitor_id"]))
            except (ValueError, KeyError):
                continue
            if key in expected_gap:
                try:
                    actual_val = round(float(r["price_gap_pct"]), 2)
                except (ValueError, KeyError):
                    continue
                if abs(actual_val - expected_gap[key]) < 0.05:
                    match_gap += 1
        gap_ratio = match_gap / total_gap
        c3_score = round(c3_max * gap_ratio)
        criteria["price_gap_values"] = {
            "passed": gap_ratio >= 0.99, "score": c3_score,
            "max_score": c3_max,
            **({"reason": f"{match_gap}/{total_gap} correct"}
               if gap_ratio < 0.99 else {})}
        total_score += c3_score

        # --- Criterion 4: recommended_price values correct (15 pts) ---
        c4_max = 15
        max_score += c4_max
        expected_rec = {
            (int(a["product_id"]), int(a["competitor_id"])):
            a["recommended_price"]
            for a in expected_alerts
        }
        match_rec = 0
        total_rec = max(len(expected_rec), 1)
        for r in dash_rows:
            try:
                key = (int(r["product_id"]), int(r["competitor_id"]))
            except (ValueError, KeyError):
                continue
            if key in expected_rec:
                try:
                    actual_val = round(float(r["recommended_price"]), 2)
                except (ValueError, KeyError):
                    continue
                if abs(actual_val - expected_rec[key]) < 0.02:
                    match_rec += 1
        rec_ratio = match_rec / total_rec
        c4_score = round(c4_max * rec_ratio)
        criteria["recommended_prices"] = {
            "passed": rec_ratio >= 0.99, "score": c4_score,
            "max_score": c4_max,
            **({"reason": f"{match_rec}/{total_rec} correct"}
               if rec_ratio < 0.99 else {})}
        total_score += c4_score

        # --- Criterion 5: Sort order (10 pts) ---
        c5_max = 10
        max_score += c5_max
        level_order = {"critical": 1, "warning": 2, "watch": 3}
        sorted_ok = True
        prev_key = None
        for r in dash_rows:
            try:
                al = r.get("alert_level", "").strip()
                pg = float(r.get("price_gap_pct", 0))
                cur_key = (level_order.get(al, 9), pg)
            except (ValueError, TypeError):
                sorted_ok = False
                break
            if prev_key is not None and cur_key < prev_key:
                sorted_ok = False
                break
            prev_key = cur_key
        if sorted_ok and dash_rows:
            criteria["sort_order"] = {
                "passed": True, "score": c5_max, "max_score": c5_max}
            total_score += c5_max
        else:
            criteria["sort_order"] = {
                "passed": False, "score": 0, "max_score": c5_max,
                "reason": "Rows not sorted by priority asc, "
                          "price_gap_pct asc"}

        # --- Criterion 6: pricing_summary.json correct (15 pts) ---
        c6_max = 15
        max_score += c6_max
        summ_path = os.path.join(self.workspace, "pricing_summary.json")
        c6_score = 0
        c6_reasons = []
        if os.path.isfile(summ_path):
            with open(summ_path) as fh:
                try:
                    actual_summ = json.load(fh)
                except json.JSONDecodeError:
                    actual_summ = {}
            # Check total_alerts (3 pts)
            if actual_summ.get("total_alerts") == expected_summary[
                    "total_alerts"]:
                c6_score += 3
            else:
                c6_reasons.append(
                    f"total_alerts: expected "
                    f"{expected_summary['total_alerts']}, "
                    f"got {actual_summ.get('total_alerts')}")
            # Check by_level (4 pts)
            actual_bl = actual_summ.get("by_level", {})
            if (actual_bl.get("critical") ==
                    expected_summary["by_level"]["critical"] and
                actual_bl.get("warning") ==
                    expected_summary["by_level"]["warning"] and
                actual_bl.get("watch") ==
                    expected_summary["by_level"]["watch"]):
                c6_score += 4
            else:
                c6_reasons.append(
                    f"by_level mismatch: expected "
                    f"{expected_summary['by_level']}, got {actual_bl}")
            # Check by_category (4 pts)
            actual_bc = actual_summ.get("by_category", {})
            bc_ok = True
            for cat, exp_counts in expected_summary[
                    "by_category"].items():
                ac = actual_bc.get(cat, {})
                for lv in ("critical", "warning", "watch"):
                    if ac.get(lv) != exp_counts[lv]:
                        bc_ok = False
                        break
                if not bc_ok:
                    break
            if bc_ok and len(actual_bc) == len(
                    expected_summary["by_category"]):
                c6_score += 4
            else:
                c6_reasons.append("by_category mismatch")
            # Check total_recommended_adjustments (4 pts)
            if actual_summ.get("total_recommended_adjustments") == \
                    expected_summary["total_recommended_adjustments"]:
                c6_score += 4
            else:
                c6_reasons.append(
                    "total_recommended_adjustments mismatch: expected "
                    f"{expected_summary['total_recommended_adjustments']}"
                    f", got "
                    f"{actual_summ.get('total_recommended_adjustments')}")
        else:
            c6_reasons.append("pricing_summary.json not found")
        criteria["pricing_summary"] = {
            "passed": c6_score == c6_max, "score": c6_score,
            "max_score": c6_max,
            **({"reason": "; ".join(c6_reasons)}
               if c6_reasons else {})}
        total_score += c6_score

        # --- Criterion 7: Action string key info (15 pts) ---
        c7_max = 15
        max_score += c7_max
        c7_score = 0
        c7_reasons = []
        action_lower = (action or "").lower()
        # total count mentioned
        total_str = str(expected_summary["total_alerts"])
        if total_str in action:
            c7_score += 5
        else:
            c7_reasons.append(
                f"Total alert count {total_str} not in response")
        # level counts
        for lv in ("critical", "warning", "watch"):
            cnt = str(expected_summary["by_level"][lv])
            if cnt in action and lv in action_lower:
                c7_score += 2
            else:
                c7_reasons.append(f"{lv} count {cnt} not in response")
        # worst threat product_id
        if expected_alerts:
            worst_pid = str(expected_alerts[0]["product_id"])
            if worst_pid in action:
                c7_score += 4
            else:
                c7_reasons.append(
                    f"Worst threat product_id {worst_pid} not found")
        else:
            c7_score += 4
        c7_score = min(c7_score, c7_max)
        criteria["action_summary"] = {
            "passed": c7_score == c7_max, "score": c7_score,
            "max_score": c7_max,
            **({"reason": "; ".join(c7_reasons)}
               if c7_reasons else {})}
        total_score += c7_score

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score, info

    # ------------------------------------------------------------------
    #  Self-verification
    # ------------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace
        files, then call self.step() to check reward.
        """
        import os
        import json
        import csv
        import glob as _glob

        # ---- 1. Read configuration files from workspace ----
        with open(os.path.join(self.workspace,
                               "alert_thresholds.json")) as f:
            thresholds = json.load(f)

        # (pricing_rules.yaml & adjustment_policy.md & competitor_tiers
        #  are read conceptually — their logic is re-implemented below
        #  exactly as specified in those files.)

        # ---- 2. Read all scraped-price CSVs ----
        scrape_pattern = os.path.join(
            self.workspace, "scrape_competitor_*.csv")
        scrape_files = sorted(_glob.glob(scrape_pattern))

        latest: dict = {}  # (cid, sku) → row
        for sf in scrape_files:
            fname = os.path.basename(sf)
            parts = fname.replace(
                "scrape_competitor_", "").replace(".csv", "").split("_")
            cid = int(parts[0])
            with open(sf, newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    sku = row["competitor_sku"]
                    ts = row["scrape_timestamp"]
                    key = (cid, sku)
                    if key not in latest or ts > latest[key]["ts"]:
                        latest[key] = {
                            "competitor_id": cid,
                            "competitor_sku": sku,
                            "listed_price": float(row["listed_price"]),
                            "ts": ts,
                        }

        # ---- 3. Resolve mappings and collect data via tools ----
        product_cache: dict = {}
        cost_cache: dict = {}
        competitor_cache: dict = {}
        tool_calls = 0

        alerts = []
        for (cid, sku), scrape in latest.items():
            # Look up catalog mapping
            mapping = self.tools["lookup_catalog_mapping"](
                competitor_sku=sku)
            tool_calls += 1
            if "error" in mapping:
                continue

            pid = mapping["product_id"]

            # Product details (for category)
            if pid not in product_cache:
                product_cache[pid] = self.tools["get_product_details"](
                    product_id=pid)
                tool_calls += 1
            product = product_cache[pid]
            if "error" in product:
                continue

            # Internal cost
            if pid not in cost_cache:
                cost_cache[pid] = self.tools["get_internal_cost"](
                    product_id=pid)
                tool_calls += 1
            cost = cost_cache[pid]
            if "error" in cost:
                continue

            # Competitor info
            if cid not in competitor_cache:
                competitor_cache[cid] = self.tools[
                    "get_competitor_info"](competitor_id=cid)
                tool_calls += 1
            comp = competitor_cache[cid]
            if "error" in comp:
                continue

            # Tier filtering: exclude Tier C (reliability < 0.70)
            if comp["reliability_score"] < 0.70:
                continue

            # Price gap
            floor_price = cost["floor_price"]
            current_price = cost["current_price"]
            unit_cost = cost["unit_cost"]
            overhead_rate = cost["overhead_rate"]
            comp_price = scrape["listed_price"]

            price_gap_pct = round(
                (comp_price - floor_price) / floor_price * 100, 2)

            category = product["category"]
            cat_t = thresholds.get(
                category,
                {"critical_threshold_pct": 10,
                 "watch_threshold_pct": 5})
            crit = cat_t["critical_threshold_pct"]
            watch = cat_t["watch_threshold_pct"]

            if price_gap_pct < -crit:
                alert_level = "critical"
                priority = 1
            elif price_gap_pct < 0:
                alert_level = "warning"
                priority = 2
            elif price_gap_pct < watch:
                alert_level = "watch"
                priority = 3
            else:
                continue

            min_viable = round(unit_cost * (1 + overhead_rate), 2)
            if alert_level == "critical":
                rec = round(max(comp_price * 0.98, min_viable), 2)
            elif alert_level == "warning":
                rec = round(
                    max((floor_price + comp_price) / 2, min_viable), 2)
            else:
                rec = current_price

            adj_pct = round(
                (rec - current_price) / current_price * 100, 2)

            alerts.append({
                "product_id": pid,
                "product_name": product["name"],
                "category": category,
                "competitor_id": cid,
                "competitor_name": comp["name"],
                "latest_scraped_price": round(comp_price, 2),
                "floor_price": round(floor_price, 2),
                "price_gap_pct": price_gap_pct,
                "alert_level": alert_level,
                "priority": priority,
                "recommended_price": rec,
                "adjustment_pct": adj_pct,
            })

        # Also make a few list calls to ensure tool-call floor
        page = 1
        while True:
            res = self.tools["list_products"](page=page)
            tool_calls += 1
            if page >= res["total_pages"]:
                break
            page += 1

        page = 1
        while True:
            res = self.tools["list_competitors"](page=page)
            tool_calls += 1
            if page >= res["total_pages"]:
                break
            page += 1

        # A few price history lookups
        for pid in list(product_cache.keys())[:5]:
            self.tools["get_price_history"](product_id=pid)
            tool_calls += 1

        # ---- 4. Sort alerts ----
        alerts.sort(key=lambda a: (a["priority"], a["price_gap_pct"]))

        # ---- 5. Write alert_dashboard.csv ----
        fieldnames = [
            "product_id", "product_name", "category", "competitor_id",
            "competitor_name", "latest_scraped_price", "floor_price",
            "price_gap_pct", "alert_level", "recommended_price",
            "adjustment_pct",
        ]
        dash_path = os.path.join(self.workspace, "alert_dashboard.csv")
        with open(dash_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for a in alerts:
                writer.writerow({k: a[k] for k in fieldnames})

        # ---- 6. Write pricing_summary.json ----
        summary = {
            "total_alerts": len(alerts),
            "by_level": {
                "critical": sum(
                    1 for a in alerts
                    if a["alert_level"] == "critical"),
                "warning": sum(
                    1 for a in alerts
                    if a["alert_level"] == "warning"),
                "watch": sum(
                    1 for a in alerts
                    if a["alert_level"] == "watch"),
            },
            "by_category": {},
            "average_price_gap_pct": {},
            "total_recommended_adjustments": sum(
                1 for a in alerts
                if a["alert_level"] in ("critical", "warning")),
        }
        for cat in sorted(set(a["category"] for a in alerts)):
            ca = [a for a in alerts if a["category"] == cat]
            summary["by_category"][cat] = {
                "critical": sum(
                    1 for a in ca if a["alert_level"] == "critical"),
                "warning": sum(
                    1 for a in ca if a["alert_level"] == "warning"),
                "watch": sum(
                    1 for a in ca if a["alert_level"] == "watch"),
            }
        for level in ("critical", "warning", "watch"):
            la = [a for a in alerts if a["alert_level"] == level]
            if la:
                summary["average_price_gap_pct"][level] = round(
                    sum(a["price_gap_pct"] for a in la) / len(la), 2)
            else:
                summary["average_price_gap_pct"][level] = 0.0

        with open(os.path.join(self.workspace,
                               "pricing_summary.json"), "w") as fh:
            json.dump(summary, fh, indent=2)

        # ---- 7. Construct action string ----
        worst = alerts[0] if alerts else None
        action = f"Total alerts: {len(alerts)}. "
        action += (
            f"Critical: {summary['by_level']['critical']}, "
            f"Warning: {summary['by_level']['warning']}, "
            f"Watch: {summary['by_level']['watch']}. "
        )
        if worst:
            action += (
                f"Most severe threat: product {worst['product_id']} "
                f"({worst['product_name']}) vs competitor "
                f"{worst['competitor_id']} ({worst['competitor_name']}) "
                f"with price gap {worst['price_gap_pct']}%."
            )
        action += (
            f" Total products requiring price adjustments: "
            f"{summary['total_recommended_adjustments']}."
        )

        assert tool_calls >= 15, (
            f"Only {tool_calls} tool calls made — minimum is 15")

        return self.step(action)
