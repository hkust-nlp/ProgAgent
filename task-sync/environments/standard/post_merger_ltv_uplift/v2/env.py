import sqlite3
import os
import json
import csv
import math
import yaml
from typing import Tuple, Dict, List, Any


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

    # ======================= TOOL METHODS =======================

    @tool(
        description="List all customer segments with the number of customers in each segment.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    def list_segments(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT segment, COUNT(*) as customer_count FROM customers GROUP BY segment ORDER BY segment")
        rows = cur.fetchall()
        conn.close()
        return _envelope([{"segment": r[0], "customer_count": r[1]} for r in rows])

    @tool(
        description="Query customers with optional filters. Returns paginated results with customer basic info.",
        parameters={
            "type": "object",
            "properties": {
                "segment": {
                    "type": "string",
                    "description": "Filter by customer segment (e.g. 'enterprise', 'mid_market', 'small_business', 'consumer')"
                },
                "company": {
                    "type": "string",
                    "description": "Filter by company origin ('acquirer' or 'target')"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed, default 1)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (default 20, max 50)"
                }
            },
            "required": []
        }
    )
    def query_customers(self, segment: str = None, company: str = None,
                        page: int = 1, page_size: int = 20):
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        where_clauses = []
        params = []
        if segment:
            where_clauses.append("segment = ?")
            params.append(segment)
        if company:
            where_clauses.append("company = ?")
            params.append(company)

        where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        cur.execute(f"SELECT COUNT(*) FROM customers{where_sql}", params)
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))

        offset = (page - 1) * page_size
        cur.execute(
            f"SELECT customer_id, name, segment, company, region, tenure_years "
            f"FROM customers{where_sql} ORDER BY customer_id LIMIT ? OFFSET ?",
            params + [page_size, offset]
        )
        rows = cur.fetchall()
        conn.close()

        customers = []
        for r in rows:
            customers.append({
                "customer_id": r[0],
                "name": r[1],
                "segment": r[2],
                "company": r[3],
                "region": r[4],
                "tenure_years": r[5],
            })

        return json.dumps({
            "customers": customers,
            "page": page,
            "page_size": page_size,
            "total_customers": total,
            "total_pages": total_pages,
        }, ensure_ascii=False, default=str)

    @tool(
        description="Get aggregated purchase data for a batch of customers. Returns total purchases, average annual revenue, and per-product breakdown for each customer. Maximum 10 customer IDs per call.",
        parameters={
            "type": "object",
            "properties": {
                "customer_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of customer IDs (max 10)"
                }
            },
            "required": ["customer_ids"]
        }
    )
    def get_purchase_aggregates(self, customer_ids: list):
        if len(customer_ids) > 10:
            return json.dumps({"error": "Maximum 10 customer IDs per call"}, ensure_ascii=False, default=str)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        placeholders = ",".join(["?"] * len(customer_ids))

        # Per-customer totals
        cur.execute(
            f"SELECT customer_id, COUNT(*) as n_purchases, SUM(amount) as total_amount "
            f"FROM purchase_history WHERE customer_id IN ({placeholders}) "
            f"GROUP BY customer_id",
            customer_ids
        )
        totals = {r[0]: {"total_purchases": r[1], "total_amount": round(r[2], 2)} for r in cur.fetchall()}

        # Per-customer per-product breakdown
        cur.execute(
            f"SELECT customer_id, product_id, SUM(quantity) as total_qty, SUM(amount) as total_amount "
            f"FROM purchase_history WHERE customer_id IN ({placeholders}) "
            f"GROUP BY customer_id, product_id",
            customer_ids
        )
        breakdowns = {}
        for r in cur.fetchall():
            cid = r[0]
            if cid not in breakdowns:
                breakdowns[cid] = []
            breakdowns[cid].append({
                "product_id": r[1],
                "total_quantity": r[2],
                "total_amount": round(r[3], 2),
            })

        conn.close()

        results = []
        for cid in customer_ids:
            t = totals.get(cid, {"total_purchases": 0, "total_amount": 0.0})
            results.append({
                "customer_id": cid,
                "total_purchases": t["total_purchases"],
                "total_amount": t["total_amount"],
                "avg_annual_revenue": round(t["total_amount"] / 3.0, 2),
                "product_breakdown": breakdowns.get(cid, []),
            })
        return json.dumps(results, ensure_ascii=False, default=str)

    @tool(
        description="Get detailed information for a single product by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product ID (e.g. 'PROD-0001')"
                }
            },
            "required": ["product_id"]
        }
    )
    def get_product_details(self, product_id: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT product_id, name, category, base_cost, retail_price "
            "FROM products WHERE product_id = ?",
            (product_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _envelope({"error": f"Product {product_id} not found"})
        return _envelope({
            "product_id": row[0],
            "name": row[1],
            "category": row[2],
            "base_cost": row[3],
            "retail_price": row[4],
        })

    @tool(
        description="Query products with optional category filter. Returns paginated product list with cost and pricing details.",
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by product category (e.g. 'software', 'hardware', 'services', 'support', 'consulting')"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed, default 1)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (default 20, max 50)"
                }
            },
            "required": []
        }
    )
    def query_products(self, category: str = None, page: int = 1, page_size: int = 20):
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        where_sql = ""
        params = []
        if category:
            where_sql = " WHERE category = ?"
            params.append(category)

        cur.execute(f"SELECT COUNT(*) FROM products{where_sql}", params)
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))

        offset = (page - 1) * page_size
        cur.execute(
            f"SELECT product_id, name, category, base_cost, retail_price "
            f"FROM products{where_sql} ORDER BY product_id LIMIT ? OFFSET ?",
            params + [page_size, offset]
        )
        rows = cur.fetchall()
        conn.close()

        products = []
        for r in rows:
            products.append({
                "product_id": r[0],
                "name": r[1],
                "category": r[2],
                "base_cost": r[3],
                "retail_price": r[4],
            })

        return _envelope({
            "products": products,
            "page": page,
            "page_size": page_size,
            "total_products": total,
            "total_pages": total_pages,
        })

    @tool(
        description="Get churn probability and risk tier data for all customers in a given segment.",
        parameters={
            "type": "object",
            "properties": {
                "segment": {
                    "type": "string",
                    "description": "Customer segment name (e.g. 'enterprise', 'mid_market', 'small_business', 'consumer')"
                }
            },
            "required": ["segment"]
        }
    )
    def get_churn_data(self, segment: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT c.customer_id, cr.annual_churn_probability, cr.risk_tier "
            "FROM churn_records cr "
            "JOIN customers c ON cr.customer_id = c.customer_id "
            "WHERE c.segment = ? ORDER BY c.customer_id",
            (segment,)
        )
        rows = cur.fetchall()
        conn.close()
        return json.dumps([
            {
                "customer_id": r[0],
                "annual_churn_probability": r[1],
                "risk_tier": r[2],
            }
            for r in rows
        ], ensure_ascii=False, default=str)

    # ======================= HELPER: GROUND TRUTH =======================

    def _compute_ground_truth(self):
        """Compute the ground-truth LTV for every customer using DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        customers = {}
        cur = conn.cursor()
        cur.execute("SELECT customer_id, name, segment, company, region, tenure_years FROM customers")
        for r in cur.fetchall():
            customers[r[0]] = {
                "customer_id": r[0], "name": r[1], "segment": r[2],
                "company": r[3], "region": r[4], "tenure_years": r[5],
            }

        # Products
        products = {}
        cur.execute("SELECT product_id, name, category, base_cost, retail_price FROM products")
        for r in cur.fetchall():
            products[r[0]] = {"base_cost": r[2 + 1], "retail_price": r[3 + 1], "category": r[2]}

        # Purchases aggregated per customer per product
        cur.execute(
            "SELECT customer_id, product_id, SUM(amount) as total_amount "
            "FROM purchase_history GROUP BY customer_id, product_id"
        )
        purchase_breakdown = {}
        for r in cur.fetchall():
            cid, pid, amt = r
            if cid not in purchase_breakdown:
                purchase_breakdown[cid] = {}
            purchase_breakdown[cid][pid] = amt

        # Total per customer
        cur.execute(
            "SELECT customer_id, SUM(amount) as total_amount FROM purchase_history GROUP BY customer_id"
        )
        customer_totals = {r[0]: r[1] for r in cur.fetchall()}

        # Churn
        churn_map = {}
        cur.execute("SELECT customer_id, annual_churn_probability FROM churn_records")
        for r in cur.fetchall():
            churn_map[r[0]] = r[1]

        conn.close()

        # Workspace: customer profiles
        loyalty_map = {}
        propensity_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("customer_profiles_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        cid = row["customer_id"]
                        loyalty_map[cid] = float(row["loyalty_score"])
                        propensity_map[cid] = float(row["cross_sell_propensity"])

        # Workspace: product synergy
        synergy_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("product_analysis_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for rec in json.load(f):
                        synergy_map[rec["product_id"]] = rec["synergy_factor"]

        # Workspace: LTV config
        with open(os.path.join(self.workspace, "ltv_config.yaml")) as f:
            ltv_cfg = yaml.safe_load(f)
        discount_rate = ltv_cfg["discount_rate"]
        growth_rate = ltv_cfg["revenue_growth_rate"]

        # Workspace: segment tier rules
        with open(os.path.join(self.workspace, "segment_tier_rules.json")) as f:
            tier_rules = json.load(f)

        # Workspace: cross-sell conversion matrix
        conversion_matrix = {}
        with open(os.path.join(self.workspace, "cross_sell_conversion_matrix.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                seg = row["segment"]
                if seg not in conversion_matrix:
                    conversion_matrix[seg] = {}
                conversion_matrix[seg][row["product_category"]] = float(row["conversion_rate"])

        # Workspace: integration params
        integration_costs = {}
        applies_to = None
        amortization_years = None
        with open(os.path.join(self.workspace, "merger_integration_params.txt")) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, val = line.split("=", 1)
                key, val = key.strip(), val.strip()
                if key == "applies_to":
                    applies_to = val
                elif key == "amortization_years":
                    amortization_years = int(val)
                else:
                    integration_costs[key] = float(val)

        # Compute LTV
        results = []
        for cid in sorted(customers.keys()):
            cust = customers[cid]
            total_amount = customer_totals.get(cid, 0.0)
            avg_annual_revenue = total_amount / 3.0

            # Weighted cost ratio and synergy
            pb = purchase_breakdown.get(cid, {})
            weighted_cost_sum = 0.0
            weighted_synergy_sum = 0.0
            for pid, amt in pb.items():
                prod = products.get(pid, {})
                cost_ratio = prod.get("base_cost", 0) / prod.get("retail_price", 1)
                weighted_cost_sum += amt * cost_ratio
                weighted_synergy_sum += amt * synergy_map.get(pid, 1.0)

            if total_amount > 0:
                weighted_cost_ratio = weighted_cost_sum / total_amount
                weighted_synergy = weighted_synergy_sum / total_amount
            else:
                weighted_cost_ratio = 0.0
                weighted_synergy = 1.0

            gross_profit = avg_annual_revenue * (1 - weighted_cost_ratio)
            synergy_adjusted_profit = gross_profit * weighted_synergy

            loyalty_score = loyalty_map.get(cid, 50.0)
            churn_rate = churn_map.get(cid, 0.1)
            effective_churn = churn_rate * (1 - loyalty_score / 100.0)

            cross_sell_prop = propensity_map.get(cid, 0.0)
            seg = cust["segment"]
            seg_conv = conversion_matrix.get(seg, {})
            avg_conversion = sum(seg_conv.values()) / len(seg_conv) if seg_conv else 0.0
            seg_multiplier = tier_rules.get(seg, {}).get("value_multiplier", 1.0)
            cross_sell_value = cross_sell_prop * avg_conversion * seg_multiplier * 0.15 * avg_annual_revenue

            if cust["company"] == applies_to:
                integ_cost = integration_costs.get(seg, 0.0) / amortization_years
            else:
                integ_cost = 0.0

            net_annual_value = synergy_adjusted_profit + cross_sell_value - integ_cost

            ltv_years = []
            for y in range(1, 4):
                survival = (1 - effective_churn) ** y
                grown = net_annual_value * (1 + growth_rate) ** y
                pv = grown * survival / (1 + discount_rate) ** y
                ltv_years.append(round(pv, 2))

            total_3yr = round(ltv_years[0] + ltv_years[1] + ltv_years[2], 2)

            results.append({
                "customer_id": cid,
                "customer_name": cust["name"],
                "segment": seg,
                "company": cust["company"],
                "region": cust["region"],
                "avg_annual_revenue": round(avg_annual_revenue, 2),
                "gross_profit": round(gross_profit, 2),
                "synergy_adjusted_profit": round(synergy_adjusted_profit, 2),
                "effective_churn_rate": round(effective_churn, 2),
                "cross_sell_value": round(cross_sell_value, 2),
                "year_1_ltv": ltv_years[0],
                "year_2_ltv": ltv_years[1],
                "year_3_ltv": ltv_years[2],
                "total_3yr_ltv": total_3yr,
            })

        results.sort(key=lambda x: (-x["total_3yr_ltv"], x["customer_id"]))
        return results

    # ======================= STEP =======================

    def step(
        self, action: str
    ) -> Tuple[float, Dict[str, Any]]:
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
        gt_map = {r["customer_id"]: r for r in ground_truth}
        n_customers = len(ground_truth)

        eval_criteria = {}
        total_score = 0
        max_score = 0

        COLUMNS = [
            "customer_id", "customer_name", "segment", "company", "region",
            "avg_annual_revenue", "gross_profit", "synergy_adjusted_profit",
            "effective_churn_rate", "cross_sell_value",
            "year_1_ltv", "year_2_ltv", "year_3_ltv", "total_3yr_ltv",
        ]

        # --- Criterion 1: file exists (10 pts) ---
        report_path = os.path.join(self.workspace, "ltv_report.csv")
        file_exists = os.path.exists(report_path)
        sc = 10 if file_exists else 0
        eval_criteria["file_exists"] = {"passed": file_exists, "score": sc, "max_score": 10}
        total_score += sc
        max_score += 10

        if not file_exists:
            # remaining criteria all fail
            for cname, mx in [("columns_correct", 10), ("row_count", 10),
                              ("ltv_accuracy", 30), ("sort_order", 10),
                              ("segment_summary", 15), ("top_customers", 15)]:
                eval_criteria[cname] = {"passed": False, "score": 0, "max_score": mx,
                                        "reason": "ltv_report.csv not found"}
                max_score += mx
            return total_score / max_score, {
                "eval_criteria": eval_criteria,
                "total_score": total_score,
                "max_score": max_score,
            }

        # Read agent report
        try:
            agent_rows = []
            with open(report_path, newline="") as f:
                reader = csv.DictReader(f)
                agent_cols = list(reader.fieldnames) if reader.fieldnames else []
                for row in reader:
                    agent_rows.append(row)
        except Exception as e:
            agent_rows = []
            agent_cols = []

        # --- Criterion 2: columns correct (10 pts) ---
        cols_ok = agent_cols == COLUMNS
        sc = 10 if cols_ok else 0
        reason = "" if cols_ok else f"Expected {COLUMNS}, got {agent_cols}"
        eval_criteria["columns_correct"] = {"passed": cols_ok, "score": sc, "max_score": 10}
        if not cols_ok:
            eval_criteria["columns_correct"]["reason"] = reason
        total_score += sc
        max_score += 10

        # --- Criterion 3: row count (10 pts) ---
        rows_ok = len(agent_rows) == n_customers
        sc = 10 if rows_ok else 0
        eval_criteria["row_count"] = {"passed": rows_ok, "score": sc, "max_score": 10}
        if not rows_ok:
            eval_criteria["row_count"]["reason"] = f"Expected {n_customers} rows, got {len(agent_rows)}"
        total_score += sc
        max_score += 10

        # --- Criterion 4: LTV accuracy (30 pts) ---
        # Check each customer's total_3yr_ltv within tolerance
        correct_count = 0
        checked = 0
        for arow in agent_rows:
            cid = arow.get("customer_id", "")
            gt = gt_map.get(cid)
            if gt is None:
                continue
            checked += 1
            try:
                agent_ltv = float(arow.get("total_3yr_ltv", 0))
                gt_ltv = gt["total_3yr_ltv"]
                # tolerance: within $1 or 1% relative, whichever is larger
                abs_tol = max(1.0, abs(gt_ltv) * 0.01)
                if abs(agent_ltv - gt_ltv) <= abs_tol:
                    correct_count += 1
            except (ValueError, TypeError):
                pass

        if checked > 0:
            accuracy = correct_count / n_customers
        else:
            accuracy = 0.0
        sc = round(30 * accuracy)
        eval_criteria["ltv_accuracy"] = {
            "passed": accuracy >= 0.9,
            "score": sc,
            "max_score": 30,
        }
        if accuracy < 0.9:
            eval_criteria["ltv_accuracy"]["reason"] = (
                f"{correct_count}/{n_customers} customers within tolerance"
            )
        total_score += sc
        max_score += 30

        # --- Criterion 5: sort order (10 pts) ---
        sort_ok = True
        for i in range(len(agent_rows) - 1):
            try:
                v1 = float(agent_rows[i].get("total_3yr_ltv", 0))
                v2 = float(agent_rows[i + 1].get("total_3yr_ltv", 0))
                if v1 < v2 - 0.005:
                    sort_ok = False
                    break
            except (ValueError, TypeError):
                sort_ok = False
                break
        sc = 10 if sort_ok else 0
        eval_criteria["sort_order"] = {"passed": sort_ok, "score": sc, "max_score": 10}
        if not sort_ok:
            eval_criteria["sort_order"]["reason"] = "Rows not sorted by total_3yr_ltv descending"
        total_score += sc
        max_score += 10

        # --- Criterion 6: segment summary in response (15 pts) ---
        # Compute ground truth segment totals
        seg_totals_gt = {}
        for r in ground_truth:
            seg = r["segment"]
            seg_totals_gt[seg] = seg_totals_gt.get(seg, 0) + r["total_3yr_ltv"]
        for seg in seg_totals_gt:
            seg_totals_gt[seg] = round(seg_totals_gt[seg], 2)

        seg_matches = 0
        for seg, gt_val in seg_totals_gt.items():
            # Look for "segment_name: VALUE" in action
            import re
            pattern = re.escape(seg) + r"\s*:\s*([\d,]+\.?\d*)"
            match = re.search(pattern, action)
            if match:
                try:
                    agent_val = float(match.group(1).replace(",", ""))
                    tol = max(1.0, abs(gt_val) * 0.01)
                    if abs(agent_val - gt_val) <= tol:
                        seg_matches += 1
                except (ValueError, TypeError):
                    pass

        n_segs = len(seg_totals_gt)
        seg_score = round(15 * seg_matches / n_segs) if n_segs > 0 else 0
        eval_criteria["segment_summary"] = {
            "passed": seg_matches == n_segs,
            "score": seg_score,
            "max_score": 15,
        }
        if seg_matches < n_segs:
            eval_criteria["segment_summary"]["reason"] = (
                f"Matched {seg_matches}/{n_segs} segment totals. Expected: {seg_totals_gt}"
            )
        total_score += seg_score
        max_score += 15

        # --- Criterion 7: top 5 customers (15 pts) ---
        top5_gt = ground_truth[:5]
        top5_gt_ids = [r["customer_id"] for r in top5_gt]
        import re
        top5_matches = 0
        for gt_r in top5_gt:
            cid = gt_r["customer_id"]
            gt_val = gt_r["total_3yr_ltv"]
            pattern = re.escape(cid) + r"\s*:\s*([\d,]+\.?\d*)"
            match = re.search(pattern, action)
            if match:
                try:
                    agent_val = float(match.group(1).replace(",", ""))
                    tol = max(1.0, abs(gt_val) * 0.01)
                    if abs(agent_val - gt_val) <= tol:
                        top5_matches += 1
                except (ValueError, TypeError):
                    pass

        sc = round(15 * top5_matches / 5)
        eval_criteria["top_customers"] = {
            "passed": top5_matches == 5,
            "score": sc,
            "max_score": 15,
        }
        if top5_matches < 5:
            eval_criteria["top_customers"]["reason"] = (
                f"Matched {top5_matches}/5 top customers. Expected top 5: "
                + ", ".join(f"{r['customer_id']}={r['total_3yr_ltv']}" for r in top5_gt)
            )
        total_score += sc
        max_score += 15

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ======================= VERIFY =======================

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
        import re as _re

        tool_calls = 0

        # 1. Get segments
        segments_info = json.loads(self.tools["list_segments"]()["content"][0]["text"])
        tool_calls += 1

        # 2. Get all customers (paginated)
        all_customers = []
        page = 1
        while True:
            result = json.loads(self.tools["query_customers"](page=page, page_size=20))
            tool_calls += 1
            all_customers.extend(result["customers"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 3. Get purchase aggregates in batches of 10
        customer_ids = [c["customer_id"] for c in all_customers]
        purchase_data = {}
        for i in range(0, len(customer_ids), 10):
            batch = customer_ids[i:i + 10]
            results = json.loads(self.tools["get_purchase_aggregates"](customer_ids=batch))
            tool_calls += 1
            for r in results:
                purchase_data[r["customer_id"]] = r

        # 4. Get all products (paginated)
        all_products = {}
        page = 1
        while True:
            result = json.loads(self.tools["query_products"](page=page, page_size=20)["content"][0]["text"])
            tool_calls += 1
            for p in result["products"]:
                all_products[p["product_id"]] = p
            if page >= result["total_pages"]:
                break
            page += 1

        # 5. Get churn data by segment
        churn_data = {}
        for seg_info in segments_info:
            seg = seg_info["segment"]
            result = json.loads(self.tools["get_churn_data"](segment=seg))
            tool_calls += 1
            for r in result:
                churn_data[r["customer_id"]] = r

        assert tool_calls >= 15, f"Only {tool_calls} tool calls made, need at least 15"

        # 6. Read workspace files
        # Customer profiles
        loyalty_map = {}
        propensity_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("customer_profiles_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        cid = row["customer_id"]
                        loyalty_map[cid] = float(row["loyalty_score"])
                        propensity_map[cid] = float(row["cross_sell_propensity"])

        # Product synergy
        synergy_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("product_analysis_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for rec in json.load(f):
                        synergy_map[rec["product_id"]] = rec["synergy_factor"]

        # LTV config
        with open(os.path.join(self.workspace, "ltv_config.yaml")) as f:
            ltv_cfg = yaml.safe_load(f)
        discount_rate = ltv_cfg["discount_rate"]
        growth_rate = ltv_cfg["revenue_growth_rate"]

        # Segment tier rules
        with open(os.path.join(self.workspace, "segment_tier_rules.json")) as f:
            tier_rules = json.load(f)

        # Cross-sell conversion matrix
        conversion_matrix = {}
        with open(os.path.join(self.workspace, "cross_sell_conversion_matrix.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                seg = row["segment"]
                if seg not in conversion_matrix:
                    conversion_matrix[seg] = {}
                conversion_matrix[seg][row["product_category"]] = float(row["conversion_rate"])

        # Integration params
        integration_costs = {}
        applies_to = None
        amortization_years = None
        with open(os.path.join(self.workspace, "merger_integration_params.txt")) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, val = line.split("=", 1)
                key, val = key.strip(), val.strip()
                if key == "applies_to":
                    applies_to = val
                elif key == "amortization_years":
                    amortization_years = int(val)
                else:
                    integration_costs[key] = float(val)

        # 7. Compute LTV for each customer
        results = []
        for cust in all_customers:
            cid = cust["customer_id"]
            purch = purchase_data.get(cid, {"total_amount": 0, "product_breakdown": []})

            total_amount = purch.get("total_amount", 0)
            avg_annual_revenue = total_amount / 3.0

            # Weighted cost ratio and synergy
            weighted_cost_sum = 0.0
            weighted_synergy_sum = 0.0
            for pb in purch.get("product_breakdown", []):
                pid = pb["product_id"]
                amt = pb["total_amount"]
                prod = all_products.get(pid, {})
                rp = prod.get("retail_price", 1)
                bc = prod.get("base_cost", 0)
                cost_ratio = bc / rp if rp != 0 else 0
                weighted_cost_sum += amt * cost_ratio
                weighted_synergy_sum += amt * synergy_map.get(pid, 1.0)

            if total_amount > 0:
                weighted_cost_ratio = weighted_cost_sum / total_amount
                weighted_synergy = weighted_synergy_sum / total_amount
            else:
                weighted_cost_ratio = 0.0
                weighted_synergy = 1.0

            gross_profit = avg_annual_revenue * (1 - weighted_cost_ratio)
            synergy_adjusted_profit = gross_profit * weighted_synergy

            loyalty_score = loyalty_map.get(cid, 50.0)
            churn_rate = churn_data.get(cid, {}).get("annual_churn_probability", 0.1)
            effective_churn = churn_rate * (1 - loyalty_score / 100.0)

            cross_sell_prop = propensity_map.get(cid, 0.0)
            seg = cust["segment"]
            seg_conv = conversion_matrix.get(seg, {})
            avg_conversion = sum(seg_conv.values()) / len(seg_conv) if seg_conv else 0.0
            seg_multiplier = tier_rules.get(seg, {}).get("value_multiplier", 1.0)
            cross_sell_value = cross_sell_prop * avg_conversion * seg_multiplier * 0.15 * avg_annual_revenue

            if cust["company"] == applies_to:
                integ_cost = integration_costs.get(seg, 0.0) / amortization_years
            else:
                integ_cost = 0.0

            net_annual_value = synergy_adjusted_profit + cross_sell_value - integ_cost

            ltv_years = []
            for y in range(1, 4):
                survival = (1 - effective_churn) ** y
                grown = net_annual_value * (1 + growth_rate) ** y
                pv = grown * survival / (1 + discount_rate) ** y
                ltv_years.append(round(pv, 2))

            total_3yr = round(ltv_years[0] + ltv_years[1] + ltv_years[2], 2)

            results.append({
                "customer_id": cid,
                "customer_name": cust["name"],
                "segment": seg,
                "company": cust["company"],
                "region": cust["region"],
                "avg_annual_revenue": round(avg_annual_revenue, 2),
                "gross_profit": round(gross_profit, 2),
                "synergy_adjusted_profit": round(synergy_adjusted_profit, 2),
                "effective_churn_rate": round(effective_churn, 2),
                "cross_sell_value": round(cross_sell_value, 2),
                "year_1_ltv": ltv_years[0],
                "year_2_ltv": ltv_years[1],
                "year_3_ltv": ltv_years[2],
                "total_3yr_ltv": total_3yr,
            })

        # Sort descending by total_3yr_ltv
        results.sort(key=lambda x: (-x["total_3yr_ltv"], x["customer_id"]))

        # Write ltv_report.csv
        columns = [
            "customer_id", "customer_name", "segment", "company", "region",
            "avg_annual_revenue", "gross_profit", "synergy_adjusted_profit",
            "effective_churn_rate", "cross_sell_value",
            "year_1_ltv", "year_2_ltv", "year_3_ltv", "total_3yr_ltv",
        ]
        with open(os.path.join(self.workspace, "ltv_report.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for r in results:
                writer.writerow(r)

        # Build action string
        total_combined = round(sum(r["total_3yr_ltv"] for r in results), 2)

        seg_totals = {}
        for r in results:
            seg = r["segment"]
            seg_totals[seg] = seg_totals.get(seg, 0) + r["total_3yr_ltv"]
        for seg in seg_totals:
            seg_totals[seg] = round(seg_totals[seg], 2)
        sorted_segs = sorted(seg_totals.items(), key=lambda x: -x[1])

        top5 = results[:5]

        lines = [f"Total combined three-year LTV: {total_combined:.2f}"]
        for seg, val in sorted_segs:
            lines.append(f"{seg}: {val:.2f}")
        for r in top5:
            lines.append(f"{r['customer_id']}: {r['total_3yr_ltv']:.2f}")

        action = "\n".join(lines)

        return self.step(action)
