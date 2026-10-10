"""
Environment for the Dynamic Substitution Engine task.
Provides tools for querying product, order, customer, inventory, and nutritional data.
Evaluates the agent's ranked substitution list output.
"""

import csv
import json
import os
import re
import sqlite3
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

    # ── Tools ────────────────────────────────────────────────────────────

    @tool(
        description="List orders that contain at least one out-of-stock item. Returns a paginated list of order IDs.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)."
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of order IDs per page (max 20)."
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_oos_orders(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT DISTINCT order_id FROM order_items WHERE is_out_of_stock = 1 ORDER BY order_id"
        )
        all_ids = [r[0] for r in c.fetchall()]
        conn.close()
        total = len(all_ids)
        page_ids = all_ids[offset : offset + page_size]
        return {
            "order_ids": page_ids,
            "page": page,
            "page_size": page_size,
            "total_orders": total,
        }

    @tool(
        description="Get details of a specific order, including all items and their out-of-stock status.",
        parameters={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "integer",
                    "description": "The order ID to look up."
                },
            },
            "required": ["order_id"],
        },
    )
    def get_order_details(self, order_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        order = c.fetchone()
        if not order:
            conn.close()
            return {"error": f"Order {order_id} not found."}
        c.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,))
        items = [dict(r) for r in c.fetchall()]
        conn.close()
        return {
            "order_id": order["order_id"],
            "customer_id": order["customer_id"],
            "order_date": order["order_date"],
            "status": order["status"],
            "items": items,
        }

    @tool(
        description="Get a customer's profile including name, price sensitivity tier, and loyalty score.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "integer",
                    "description": "The customer ID."
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_customer_profile(self, customer_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return {"error": f"Customer {customer_id} not found."}
        return dict(row)

    @tool(
        description="Get product details by product ID.",
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "The product ID."
                },
            },
            "required": ["product_id"],
        },
    )
    def get_product(self, product_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM products WHERE product_id = ?", (product_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return {"error": f"Product {product_id} not found."}
        return dict(row)

    @tool(
        description="Search products by category and optionally subcategory. Returns a paginated list.",
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Product category to search."
                },
                "subcategory": {
                    "type": "string",
                    "description": "Optional subcategory filter."
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)."
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 20)."
                },
            },
            "required": ["category", "page", "page_size"],
        },
    )
    def search_products(self, category: str, page: int, page_size: int,
                        subcategory: str = None) -> dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if subcategory:
            c.execute(
                "SELECT * FROM products WHERE category = ? AND subcategory = ? ORDER BY product_id LIMIT ? OFFSET ?",
                (category, subcategory, page_size, offset),
            )
        else:
            c.execute(
                "SELECT * FROM products WHERE category = ? ORDER BY product_id LIMIT ? OFFSET ?",
                (category, page_size, offset),
            )
        rows = [dict(r) for r in c.fetchall()]
        # Get total count
        if subcategory:
            c.execute(
                "SELECT COUNT(*) FROM products WHERE category = ? AND subcategory = ?",
                (category, subcategory),
            )
        else:
            c.execute("SELECT COUNT(*) FROM products WHERE category = ?", (category,))
        total = c.fetchone()[0]
        conn.close()
        return {"products": rows, "page": page, "page_size": page_size, "total": total}

    @tool(
        description="Check current inventory level for a product.",
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "The product ID to check inventory for."
                },
            },
            "required": ["product_id"],
        },
    )
    def check_inventory(self, product_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM inventory WHERE product_id = ?", (product_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return {"error": f"No inventory record for product {product_id}."}
        return dict(row)

    @tool(
        description="Get nutritional profile for a product.",
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "The product ID."
                },
            },
            "required": ["product_id"],
        },
    )
    def get_nutritional_info(self, product_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM nutritional_profiles WHERE product_id = ?", (product_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return {"error": f"No nutritional data for product {product_id}."}
        return dict(row)

    @tool(
        description="Get the list of out-of-stock product IDs for a given order.",
        parameters={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "integer",
                    "description": "The order ID."
                },
            },
            "required": ["order_id"],
        },
    )
    def get_oos_items_for_order(self, order_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT product_id, quantity FROM order_items WHERE order_id = ? AND is_out_of_stock = 1",
            (order_id,),
        )
        rows = [{"product_id": r[0], "quantity": r[1]} for r in c.fetchall()]
        conn.close()
        return {"order_id": order_id, "oos_items": rows}

    # ── Evaluation ───────────────────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute the full ground-truth substitution list."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Load policy
        policy = self._load_substitution_policy()
        weights = policy["scoring_weights"]
        nutri_tol = policy["nutritional_tolerance_pct"]
        max_subs = policy["rules"]["max_substitutes_per_item"]
        same_subcat_bonus = policy["rules"]["same_subcategory_bonus"]

        # Load price tiers
        with open(os.path.join(self.workspace, "price_sensitivity_tiers.json")) as f:
            price_tiers = json.load(f)

        # Load brand affinity matrix
        brand_affinity = self._load_brand_affinity()

        # Load product specs (dietary tags, allergens, quality, sourcing)
        product_specs = self._load_all_product_specs()

        # Load customer brand preferences
        with open(os.path.join(self.workspace, "customer_brand_preferences.json")) as f:
            cust_brand_prefs = json.load(f)

        # Load order notes
        order_notes = self._load_all_order_notes()

        # Get all OOS orders
        c.execute("SELECT DISTINCT order_id FROM order_items WHERE is_out_of_stock = 1 ORDER BY order_id")
        oos_order_ids = [r[0] for r in c.fetchall()]

        results = []
        for oid in oos_order_ids:
            # Check if substitution is allowed
            note_info = order_notes.get(oid, {"allow_substitution": True, "substitution_note": ""})
            if not note_info.get("allow_substitution", True):
                continue

            c.execute("SELECT customer_id FROM orders WHERE order_id = ?", (oid,))
            cid = c.fetchone()[0]

            c.execute("SELECT * FROM customers WHERE customer_id = ?", (cid,))
            customer = dict(c.fetchone())

            cust_prefs = cust_brand_prefs.get(str(cid), {"preferred_brands": [], "avoid_allergens": []})

            c.execute(
                "SELECT product_id, quantity FROM order_items WHERE order_id = ? AND is_out_of_stock = 1",
                (oid,),
            )
            oos_items = c.fetchall()

            for oos_item in oos_items:
                oos_pid = oos_item[0]
                oos_qty = oos_item[1]

                c.execute("SELECT * FROM products WHERE product_id = ?", (oos_pid,))
                oos_product = dict(c.fetchone())

                c.execute("SELECT * FROM nutritional_profiles WHERE product_id = ?", (oos_pid,))
                oos_nutri = dict(c.fetchone())

                oos_spec = product_specs.get(oos_pid, {})

                # Find candidates: same category, in stock, not the same product
                c.execute(
                    "SELECT p.* FROM products p JOIN inventory i ON p.product_id = i.product_id "
                    "WHERE p.category = ? AND p.product_id != ? AND i.current_stock >= ?",
                    (oos_product["category"], oos_pid, oos_qty),
                )
                candidates = [dict(r) for r in c.fetchall()]

                tier = customer["price_sensitivity_tier"]
                max_increase_pct = price_tiers[tier]["max_price_increase_pct"]

                scored = []
                for cand in candidates:
                    cpid = cand["product_id"]

                    # Price check
                    price_increase_pct = ((cand["unit_price"] - oos_product["unit_price"]) / oos_product["unit_price"]) * 100
                    if price_increase_pct > max_increase_pct:
                        continue

                    # Allergen check
                    cand_spec = product_specs.get(cpid, {})
                    cand_allergens = set(cand_spec.get("allergens", []))
                    avoid = set(cust_prefs.get("avoid_allergens", []))
                    if cand_allergens & avoid:
                        continue

                    # Score: category_match
                    cat_score = weights["category_match"]  # same category guaranteed
                    if cand["subcategory"] == oos_product["subcategory"]:
                        cat_score += same_subcat_bonus

                    # Score: brand_affinity
                    brand_score = 0
                    orig_brand = oos_product["brand"]
                    cand_brand = cand["brand"]
                    if orig_brand in brand_affinity and cand_brand in brand_affinity[orig_brand]:
                        brand_score = brand_affinity[orig_brand][cand_brand] / 100.0 * weights["brand_affinity"]
                    # Bonus for preferred brand
                    if cand_brand in cust_prefs.get("preferred_brands", []):
                        brand_score = min(brand_score + 5, weights["brand_affinity"] + 5)

                    # Score: nutritional_similarity
                    c.execute("SELECT * FROM nutritional_profiles WHERE product_id = ?", (cpid,))
                    cand_nutri_row = c.fetchone()
                    if cand_nutri_row:
                        cand_nutri = dict(cand_nutri_row)
                        nutri_score = 0
                        nutri_fields = ["calories", "protein_g", "fat_g", "carbs_g", "fiber_g", "sugar_g", "sodium_mg"]
                        for field in nutri_fields:
                            orig_val = oos_nutri[field]
                            cand_val = cand_nutri[field]
                            if orig_val == 0:
                                dev_pct = 0 if cand_val == 0 else 100
                            else:
                                dev_pct = abs(cand_val - orig_val) / orig_val * 100
                            tol = nutri_tol.get(field, 30)
                            if dev_pct <= tol:
                                nutri_score += weights["nutritional_similarity"] / len(nutri_fields)
                        nutri_score = round(nutri_score, 4)
                    else:
                        nutri_score = 0

                    # Score: price_compatibility
                    if price_increase_pct <= 0:
                        price_score = weights["price_compatibility"]
                    else:
                        price_score = weights["price_compatibility"] * (1 - price_increase_pct / max_increase_pct)
                    price_score = max(0, round(price_score, 4))

                    # Score: inventory_availability
                    c.execute("SELECT current_stock FROM inventory WHERE product_id = ?", (cpid,))
                    stock = c.fetchone()[0]
                    # Normalize: more stock = higher score, cap at 100
                    inv_score = min(stock / 100.0, 1.0) * weights["inventory_availability"]
                    inv_score = round(inv_score, 4)

                    # Quality bonus from specs
                    quality = cand_spec.get("quality_score", 3.0)
                    quality_bonus = (quality - 3.0) / 2.0 * 5  # up to +5 for quality 5.0

                    total = round(cat_score + brand_score + nutri_score + price_score + inv_score + quality_bonus, 2)

                    scored.append({
                        "order_id": oid,
                        "original_product_id": oos_pid,
                        "substitute_product_id": cpid,
                        "substitute_name": cand["name"],
                        "score": total,
                    })

                # Sort by score desc, take top max_subs
                scored.sort(key=lambda x: (-x["score"], x["substitute_product_id"]))
                for rank, entry in enumerate(scored[:max_subs], 1):
                    entry["rank"] = rank
                    results.append(entry)

        conn.close()
        return results

    def _load_substitution_policy(self) -> dict:
        """Parse the substitution_policy.yaml file."""
        path = os.path.join(self.workspace, "substitution_policy.yaml")
        return self._parse_simple_yaml(path)

    def _parse_simple_yaml(self, path: str) -> dict:
        """Minimal YAML parser for our structured files."""
        result = {}
        stack = [(result, -1)]

        with open(path) as f:
            for line in f:
                stripped = line.rstrip()
                if not stripped or stripped.startswith("#"):
                    continue

                indent = len(line) - len(line.lstrip())
                level = indent // 2

                # Pop stack to current level
                while len(stack) > 1 and stack[-1][1] >= level:
                    stack.pop()

                current = stack[-1][0]

                if stripped.startswith("- "):
                    # List item
                    val = stripped[2:].strip()
                    if isinstance(current, dict):
                        # Find the last key that has a list
                        last_key = list(current.keys())[-1]
                        if not isinstance(current[last_key], list):
                            current[last_key] = []
                        current[last_key].append(self._parse_yaml_value(val))
                    elif isinstance(current, list):
                        current.append(self._parse_yaml_value(val))
                elif ":" in stripped:
                    key, _, val = stripped.partition(":")
                    key = key.strip()
                    val = val.strip()
                    if val:
                        current[key] = self._parse_yaml_value(val)
                    else:
                        current[key] = {}
                        stack.append((current[key], level))

        return result

    def _parse_yaml_value(self, val: str):
        """Parse a YAML scalar value."""
        if val.lower() == "true":
            return True
        if val.lower() == "false":
            return False
        try:
            return int(val)
        except ValueError:
            pass
        try:
            return float(val)
        except ValueError:
            pass
        return val

    def _load_brand_affinity(self) -> dict:
        """Load brand affinity matrix as nested dict."""
        path = os.path.join(self.workspace, "brand_affinity_matrix.csv")
        result = {}
        with open(path) as f:
            reader = csv.reader(f)
            header = next(reader)
            brands = header[1:]  # skip 'brand' column
            for row in reader:
                brand_name = row[0]
                result[brand_name] = {}
                for i, b in enumerate(brands):
                    result[brand_name][b] = int(row[i + 1])
        return result

    def _load_all_product_specs(self) -> dict:
        """Load all product spec files from workspace into a dict keyed by product_id."""
        specs = {}
        specs_dir = os.path.join(self.workspace, "product_specs")
        if not os.path.isdir(specs_dir):
            return specs

        for fname in sorted(os.listdir(specs_dir)):
            fpath = os.path.join(specs_dir, fname)
            if fname.endswith(".json"):
                with open(fpath) as f:
                    records = json.load(f)
                for rec in records:
                    specs[rec["product_id"]] = rec
            elif fname.endswith(".csv"):
                with open(fpath) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        pid = int(row["product_id"])
                        specs[pid] = {
                            "product_id": pid,
                            "dietary_tags": [t for t in row.get("dietary_tags", "").split("|") if t],
                            "allergens": [a for a in row.get("allergens", "").split("|") if a],
                            "quality_score": float(row.get("quality_score", 3.0)),
                            "sourcing": row.get("sourcing", ""),
                        }
            elif fname.endswith(".yaml"):
                records = self._parse_yaml_spec_list(fpath)
                for rec in records:
                    specs[rec["product_id"]] = rec
            elif fname.endswith(".txt"):
                records = self._parse_txt_specs(fpath)
                for rec in records:
                    specs[rec["product_id"]] = rec
        return specs

    def _parse_yaml_spec_list(self, path: str) -> list:
        """Parse YAML spec files in our specific list format."""
        records = []
        current = None
        with open(path) as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("- product_id:"):
                    if current:
                        records.append(current)
                    pid = int(stripped.split(":")[1].strip())
                    current = {"product_id": pid, "dietary_tags": [], "allergens": [],
                               "quality_score": 3.0, "sourcing": ""}
                elif current and stripped.startswith("dietary_tags:"):
                    val = stripped.split(":", 1)[1].strip()
                    val = val.strip("[]")
                    current["dietary_tags"] = [t.strip() for t in val.split(",") if t.strip()]
                elif current and stripped.startswith("allergens:"):
                    val = stripped.split(":", 1)[1].strip()
                    val = val.strip("[]")
                    current["allergens"] = [a.strip() for a in val.split(",") if a.strip()]
                elif current and stripped.startswith("quality_score:"):
                    current["quality_score"] = float(stripped.split(":")[1].strip())
                elif current and stripped.startswith("sourcing:"):
                    current["sourcing"] = stripped.split(":")[1].strip()
        if current:
            records.append(current)
        return records

    def _parse_txt_specs(self, path: str) -> list:
        """Parse TXT spec files."""
        records = []
        current = {}
        with open(path) as f:
            for line in f:
                stripped = line.strip()
                if stripped == "---":
                    if current:
                        records.append(current)
                    current = {}
                elif "=" in stripped:
                    key, val = stripped.split("=", 1)
                    if key == "PRODUCT_ID":
                        current["product_id"] = int(val)
                    elif key == "DIETARY_TAGS":
                        current["dietary_tags"] = [t for t in val.split(",") if t]
                    elif key == "ALLERGENS":
                        current["allergens"] = [a for a in val.split(",") if a]
                    elif key == "QUALITY_SCORE":
                        current["quality_score"] = float(val)
                    elif key == "SOURCING":
                        current["sourcing"] = val
        if current and "product_id" in current:
            records.append(current)
        return records

    def _load_all_order_notes(self) -> dict:
        """Load all order notes files from workspace into a dict keyed by order_id."""
        notes = {}
        notes_dir = os.path.join(self.workspace, "order_notes")
        if not os.path.isdir(notes_dir):
            return notes

        for fname in sorted(os.listdir(notes_dir)):
            fpath = os.path.join(notes_dir, fname)
            if fname.endswith(".json"):
                with open(fpath) as f:
                    records = json.load(f)
                for rec in records:
                    notes[rec["order_id"]] = rec
            elif fname.endswith(".csv"):
                with open(fpath) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        oid = int(row["order_id"])
                        allow = row.get("allow_substitution", "True")
                        if isinstance(allow, str):
                            allow = allow.lower() in ("true", "1", "yes")
                        notes[oid] = {
                            "order_id": oid,
                            "allow_substitution": allow,
                            "substitution_note": row.get("substitution_note", ""),
                        }
            elif fname.endswith(".md"):
                current_oid = None
                allow = True
                note = ""
                with open(fpath) as f:
                    for line in f:
                        stripped = line.strip()
                        m = re.match(r"## Order (\d+)", stripped)
                        if m:
                            if current_oid is not None:
                                notes[current_oid] = {
                                    "order_id": current_oid,
                                    "allow_substitution": allow,
                                    "substitution_note": note,
                                }
                            current_oid = int(m.group(1))
                            allow = True
                            note = ""
                        elif stripped.startswith("- Allow substitution:"):
                            val = stripped.split(":", 1)[1].strip()
                            allow = val.lower() == "yes"
                        elif stripped.startswith("- Note:"):
                            note = stripped.split(":", 1)[1].strip()
                    if current_oid is not None:
                        notes[current_oid] = {
                            "order_id": current_oid,
                            "allow_substitution": allow,
                            "substitution_note": note,
                        }
            elif fname.endswith(".txt"):
                current = {}
                with open(fpath) as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped == "---":
                            if current and "order_id" in current:
                                notes[current["order_id"]] = current
                            current = {}
                        elif "=" in stripped:
                            key, val = stripped.split("=", 1)
                            if key == "ORDER_ID":
                                current["order_id"] = int(val)
                            elif key == "ALLOW_SUBSTITUTION":
                                current["allow_substitution"] = val.lower() in ("true", "1", "yes")
                            elif key == "NOTE":
                                current["substitution_note"] = val
                if current and "order_id" in current:
                    notes[current["order_id"]] = current
        return notes

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
        max_total = 0
        earned_total = 0

        # ── Criterion 1: substitution_list.csv exists and is well-formed (15 pts) ──
        csv_path = os.path.join(self.workspace, "substitution_list.csv")
        csv_ok = False
        agent_rows = []
        required_cols = {"order_id", "original_product_id", "rank", "substitute_product_id", "score"}
        c1_score = 0
        c1_max = 15
        if os.path.isfile(csv_path):
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    cols = set(reader.fieldnames) if reader.fieldnames else set()
                    if required_cols.issubset(cols):
                        for row in reader:
                            agent_rows.append({
                                "order_id": int(row["order_id"]),
                                "original_product_id": int(row["original_product_id"]),
                                "rank": int(row["rank"]),
                                "substitute_product_id": int(row["substitute_product_id"]),
                                "score": float(row["score"]),
                            })
                        csv_ok = True
                        c1_score = 15
                    else:
                        c1_score = 5  # file exists but wrong columns
            except Exception:
                c1_score = 2  # file exists but malformed
        eval_criteria["csv_file_format"] = {
            "passed": csv_ok,
            "score": c1_score,
            "max_score": c1_max,
            "reason": "" if csv_ok else "substitution_list.csv missing or wrong columns",
        }
        max_total += c1_max
        earned_total += c1_score

        # ── Criterion 2: Correct set of (order_id, original_product_id) pairs (20 pts) ──
        gt_pairs = set()
        for r in ground_truth:
            gt_pairs.add((r["order_id"], r["original_product_id"]))
        agent_pairs = set()
        for r in agent_rows:
            agent_pairs.add((r["order_id"], r["original_product_id"]))

        c2_max = 20
        if len(gt_pairs) == 0:
            c2_score = c2_max if len(agent_pairs) == 0 else 0
        else:
            correct = len(gt_pairs & agent_pairs)
            extra = len(agent_pairs - gt_pairs)
            precision = correct / max(len(agent_pairs), 1)
            recall = correct / len(gt_pairs)
            if precision + recall > 0:
                f1 = 2 * precision * recall / (precision + recall)
            else:
                f1 = 0
            c2_score = round(f1 * c2_max, 2)

        eval_criteria["oos_pair_coverage"] = {
            "passed": c2_score >= c2_max * 0.95,
            "score": c2_score,
            "max_score": c2_max,
            "reason": "" if c2_score >= c2_max * 0.95 else f"Expected {len(gt_pairs)} OOS pairs, agent has {len(agent_pairs)}",
        }
        max_total += c2_max
        earned_total += c2_score

        # ── Criterion 3: Rank-1 substitute accuracy (20 pts) ──
        gt_rank1 = {}
        for r in ground_truth:
            if r["rank"] == 1:
                gt_rank1[(r["order_id"], r["original_product_id"])] = r["substitute_product_id"]
        agent_rank1 = {}
        for r in agent_rows:
            if r["rank"] == 1:
                agent_rank1[(r["order_id"], r["original_product_id"])] = r["substitute_product_id"]

        c3_max = 20
        if len(gt_rank1) == 0:
            c3_score = c3_max
        else:
            matches = sum(1 for k, v in gt_rank1.items() if agent_rank1.get(k) == v)
            c3_score = round(matches / len(gt_rank1) * c3_max, 2)

        eval_criteria["rank1_accuracy"] = {
            "passed": c3_score >= c3_max * 0.9,
            "score": c3_score,
            "max_score": c3_max,
            "reason": "" if c3_score >= c3_max * 0.9 else f"Rank-1 match: {c3_score}/{c3_max}",
        }
        max_total += c3_max
        earned_total += c3_score

        # ── Criterion 4: Score accuracy — agent scores within 10% of ground truth (15 pts) ──
        c4_max = 15
        gt_lookup = {}
        for r in ground_truth:
            gt_lookup[(r["order_id"], r["original_product_id"], r["substitute_product_id"])] = r["score"]

        close_count = 0
        total_compared = 0
        for r in agent_rows:
            key = (r["order_id"], r["original_product_id"], r["substitute_product_id"])
            if key in gt_lookup:
                total_compared += 1
                gt_score = gt_lookup[key]
                if gt_score == 0:
                    if r["score"] == 0:
                        close_count += 1
                elif abs(r["score"] - gt_score) / gt_score <= 0.10:
                    close_count += 1

        if total_compared == 0:
            c4_score = 0
        else:
            c4_score = round(close_count / total_compared * c4_max, 2)

        eval_criteria["score_accuracy"] = {
            "passed": c4_score >= c4_max * 0.8,
            "score": c4_score,
            "max_score": c4_max,
            "reason": "" if c4_score >= c4_max * 0.8 else f"Score accuracy: {close_count}/{total_compared}",
        }
        max_total += c4_max
        earned_total += c4_score

        # ── Criterion 5: Max 3 substitutes per (order, product) pair (10 pts) ──
        c5_max = 10
        from collections import Counter
        pair_counts = Counter()
        for r in agent_rows:
            pair_counts[(r["order_id"], r["original_product_id"])] += 1

        violations = sum(1 for cnt in pair_counts.values() if cnt > 3)
        if len(pair_counts) == 0:
            c5_score = 0
        else:
            c5_score = round(max(0, 1 - violations / len(pair_counts)) * c5_max, 2)

        eval_criteria["max_subs_per_item"] = {
            "passed": violations == 0,
            "score": c5_score,
            "max_score": c5_max,
            "reason": "" if violations == 0 else f"{violations} pairs exceed 3 substitutes",
        }
        max_total += c5_max
        earned_total += c5_score

        # ── Criterion 6: Substitution summary in response (10 pts) ──
        c6_max = 10
        c6_score = 0
        # Check that the action mentions key stats
        if action:
            # Should mention total orders processed and total substitutions
            total_subs = len(ground_truth)
            total_oos_orders = len(set(r["order_id"] for r in ground_truth))
            has_count = False
            has_order_ref = False
            # Check for any number close to total_subs or total_oos_orders
            numbers_in_action = [int(x) for x in re.findall(r'\d+', action)]
            for n in numbers_in_action:
                if abs(n - total_subs) <= 2:
                    has_count = True
                if abs(n - total_oos_orders) <= 2:
                    has_order_ref = True
            if has_count:
                c6_score += 5
            if has_order_ref:
                c6_score += 5

        eval_criteria["response_summary"] = {
            "passed": c6_score >= c6_max * 0.8,
            "score": c6_score,
            "max_score": c6_max,
            "reason": "" if c6_score >= c6_max * 0.8 else "Response missing substitution summary stats",
        }
        max_total += c6_max
        earned_total += c6_score

        # ── Criterion 7: Orders without substitution permission correctly excluded (10 pts) ──
        c7_max = 10
        order_notes = self._load_all_order_notes()
        excluded_orders = set()
        for oid, info in order_notes.items():
            if not info.get("allow_substitution", True):
                excluded_orders.add(oid)

        # Check agent didn't include excluded orders
        agent_order_ids = set(r["order_id"] for r in agent_rows)
        bad_inclusions = agent_order_ids & excluded_orders
        if len(excluded_orders) == 0:
            c7_score = c7_max
        else:
            c7_score = round(max(0, 1 - len(bad_inclusions) / max(len(excluded_orders), 1)) * c7_max, 2)

        eval_criteria["exclusion_compliance"] = {
            "passed": len(bad_inclusions) == 0,
            "score": c7_score,
            "max_score": c7_max,
            "reason": "" if len(bad_inclusions) == 0 else f"Included {len(bad_inclusions)} orders that disallow substitution",
        }
        max_total += c7_max
        earned_total += c7_score

        total_score = round(earned_total, 2)
        reward = round(total_score / max_total, 4) if max_total > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_total,
        }
        return reward, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import os as _os
        import json as _json
        import csv as _csv
        import re as _re

        tool_calls = 0

        def tc(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        # Step 1: Load workspace config files
        # substitution_policy.yaml
        policy_path = _os.path.join(self.workspace, "substitution_policy.yaml")
        policy = self._parse_simple_yaml(policy_path)
        weights = policy["scoring_weights"]
        nutri_tol = policy["nutritional_tolerance_pct"]
        max_subs = policy["rules"]["max_substitutes_per_item"]
        same_subcat_bonus = policy["rules"]["same_subcategory_bonus"]

        # price_sensitivity_tiers.json
        with open(_os.path.join(self.workspace, "price_sensitivity_tiers.json")) as f:
            price_tiers = _json.load(f)

        # brand_affinity_matrix.csv
        brand_affinity = self._load_brand_affinity()

        # customer_brand_preferences.json
        with open(_os.path.join(self.workspace, "customer_brand_preferences.json")) as f:
            cust_brand_prefs = _json.load(f)

        # Load all product specs from workspace files
        product_specs = self._load_all_product_specs()

        # Load all order notes
        order_notes = self._load_all_order_notes()

        # Step 2: List all OOS orders (paginated)
        all_oos_order_ids = []
        page = 1
        while True:
            resp = tc("list_oos_orders", page=page, page_size=20)
            all_oos_order_ids.extend(resp["order_ids"])
            if page * 20 >= resp["total_orders"]:
                break
            page += 1

        results = []

        for oid in all_oos_order_ids:
            # Check order notes for substitution permission
            note_info = order_notes.get(oid, {"allow_substitution": True, "substitution_note": ""})
            if not note_info.get("allow_substitution", True):
                continue

            # Get order details
            order_det = tc("get_order_details", order_id=oid)
            cid = order_det["customer_id"]

            # Get customer profile
            cust = tc("get_customer_profile", customer_id=cid)
            tier = cust["price_sensitivity_tier"]
            max_increase_pct = price_tiers[tier]["max_price_increase_pct"]

            cust_prefs = cust_brand_prefs.get(str(cid), {"preferred_brands": [], "avoid_allergens": []})

            # Get OOS items for this order
            oos_resp = tc("get_oos_items_for_order", order_id=oid)
            oos_items = oos_resp["oos_items"]

            for oos_item in oos_items:
                oos_pid = oos_item["product_id"]
                oos_qty = oos_item["quantity"]

                # Get OOS product details
                oos_prod = tc("get_product", product_id=oos_pid)
                oos_nutri = tc("get_nutritional_info", product_id=oos_pid)

                oos_spec = product_specs.get(oos_pid, {})

                # Search for candidates in same category (paginated)
                cat = oos_prod["category"]
                candidates = []
                sp = 1
                while True:
                    resp = tc("search_products", category=cat, page=sp, page_size=20)
                    for p in resp["products"]:
                        if p["product_id"] != oos_pid:
                            candidates.append(p)
                    if sp * 20 >= resp["total"]:
                        break
                    sp += 1

                scored = []
                for cand in candidates:
                    cpid = cand["product_id"]

                    # Check inventory
                    inv = tc("check_inventory", product_id=cpid)
                    stock = inv["current_stock"]
                    if stock < oos_qty:
                        continue

                    # Price check
                    price_increase_pct = ((cand["unit_price"] - oos_prod["unit_price"]) / oos_prod["unit_price"]) * 100
                    if price_increase_pct > max_increase_pct:
                        continue

                    # Allergen check
                    cand_spec = product_specs.get(cpid, {})
                    cand_allergens = set(cand_spec.get("allergens", []))
                    avoid = set(cust_prefs.get("avoid_allergens", []))
                    if cand_allergens & avoid:
                        continue

                    # Score: category_match
                    cat_score = weights["category_match"]
                    if cand["subcategory"] == oos_prod["subcategory"]:
                        cat_score += same_subcat_bonus

                    # Score: brand_affinity
                    brand_score = 0
                    orig_brand = oos_prod["brand"]
                    cand_brand = cand["brand"]
                    if orig_brand in brand_affinity and cand_brand in brand_affinity[orig_brand]:
                        brand_score = brand_affinity[orig_brand][cand_brand] / 100.0 * weights["brand_affinity"]
                    if cand_brand in cust_prefs.get("preferred_brands", []):
                        brand_score = min(brand_score + 5, weights["brand_affinity"] + 5)

                    # Score: nutritional_similarity
                    cand_nutri = tc("get_nutritional_info", product_id=cpid)
                    nutri_score = 0
                    nutri_fields = ["calories", "protein_g", "fat_g", "carbs_g", "fiber_g", "sugar_g", "sodium_mg"]
                    for field in nutri_fields:
                        orig_val = oos_nutri[field]
                        cand_val = cand_nutri[field]
                        if orig_val == 0:
                            dev_pct = 0 if cand_val == 0 else 100
                        else:
                            dev_pct = abs(cand_val - orig_val) / orig_val * 100
                        tol = nutri_tol.get(field, 30)
                        if dev_pct <= tol:
                            nutri_score += weights["nutritional_similarity"] / len(nutri_fields)
                    nutri_score = round(nutri_score, 4)

                    # Score: price_compatibility
                    if price_increase_pct <= 0:
                        price_sc = weights["price_compatibility"]
                    else:
                        price_sc = weights["price_compatibility"] * (1 - price_increase_pct / max_increase_pct)
                    price_sc = max(0, round(price_sc, 4))

                    # Score: inventory_availability
                    inv_score = min(stock / 100.0, 1.0) * weights["inventory_availability"]
                    inv_score = round(inv_score, 4)

                    # Quality bonus
                    quality = cand_spec.get("quality_score", 3.0)
                    quality_bonus = (quality - 3.0) / 2.0 * 5

                    total = round(cat_score + brand_score + nutri_score + price_sc + inv_score + quality_bonus, 2)

                    scored.append({
                        "order_id": oid,
                        "original_product_id": oos_pid,
                        "substitute_product_id": cpid,
                        "substitute_name": cand["name"],
                        "score": total,
                    })

                scored.sort(key=lambda x: (-x["score"], x["substitute_product_id"]))
                for rank, entry in enumerate(scored[:max_subs], 1):
                    entry["rank"] = rank
                    results.append(entry)

        # Write substitution_list.csv
        csv_path = _os.path.join(self.workspace, "substitution_list.csv")
        with open(csv_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=[
                "order_id", "original_product_id", "rank",
                "substitute_product_id", "substitute_name", "score"
            ])
            writer.writeheader()
            for r in results:
                writer.writerow(r)

        # Build action summary
        total_subs = len(results)
        total_orders = len(set(r["order_id"] for r in results))
        total_oos_items = len(set((r["order_id"], r["original_product_id"]) for r in results))
        action = (
            f"Substitution analysis complete. Processed {total_orders} orders with "
            f"{total_oos_items} out-of-stock items, generating {total_subs} ranked substitutions. "
            f"Results saved to substitution_list.csv with columns: order_id, original_product_id, "
            f"rank, substitute_product_id, substitute_name, score."
        )

        print(f"[verify] Tool calls made: {tool_calls}")
        return self.step(action)
