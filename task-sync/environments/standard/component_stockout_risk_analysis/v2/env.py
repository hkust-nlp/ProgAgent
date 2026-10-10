import os
import re
import csv
import json
import glob
import math
import sqlite3
from typing import Tuple, Dict, List, Any
from collections import defaultdict


# ── Decorator ────────────────────────────────────────────────────────────
def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ═════════════════════════════════════════════════════════════════════════
#  Task_Env
# ═════════════════════════════════════════════════════════════════════════

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

    # ── keep this implementation unchanged ──
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

    # ─────────────────────────────────────────────────────────────────────
    #  TOOL METHODS
    # ─────────────────────────────────────────────────────────────────────

    @tool(
        description=(
            "Returns a paginated list of production orders filtered by status. "
            "Each page contains up to page_size orders."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by order status, e.g. 'Active', 'Completed', 'On Hold'.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of orders per page (max 20, default 10).",
                },
            },
            "required": ["status", "page"],
        },
    )
    def list_production_orders(self, status: str, page: int, page_size: int = 10):
        page_size = min(page_size, 20)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM production_orders WHERE status = ?", (status,)
        )
        total = c.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        c.execute(
            "SELECT * FROM production_orders WHERE status = ? "
            "ORDER BY order_id LIMIT ? OFFSET ?",
            (status, page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {
            "orders": rows,
            "page": page,
            "page_size": page_size,
            "total_count": total,
            "total_pages": total_pages,
        }

    @tool(
        description=(
            "Returns the top-level bill of materials entries for a given product. "
            "These are direct children of the product (parent_component_id is null)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_code": {
                    "type": "string",
                    "description": "The product code, e.g. 'PROD-001'.",
                },
            },
            "required": ["product_code"],
        },
    )
    def get_product_bom(self, product_code: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM bill_of_materials "
            "WHERE product_code = ? AND parent_component_id IS NULL "
            "ORDER BY child_component_id",
            (product_code,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"product_code": product_code, "entries": rows}

    @tool(
        description=(
            "Returns the child components of a sub-assembly. "
            "These are BOM entries where the given component is the parent."
        ),
        parameters={
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "The parent component (sub-assembly) ID, e.g. 'CMP-0001'.",
                },
            },
            "required": ["component_id"],
        },
    )
    def get_subassembly_components(self, component_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM bill_of_materials "
            "WHERE parent_component_id = ? "
            "ORDER BY child_component_id",
            (component_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"parent_component_id": component_id, "entries": rows}

    @tool(
        description=(
            "Returns inventory records for a specific component across all warehouses."
        ),
        parameters={
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "The component ID, e.g. 'CMP-0009'.",
                },
            },
            "required": ["component_id"],
        },
    )
    def get_inventory_levels(self, component_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM inventory WHERE component_id = ? "
            "ORDER BY warehouse_id",
            (component_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"component_id": component_id, "records": rows}

    @tool(
        description=(
            "Returns the suppliers linked to a specific component, including "
            "lead times, pricing, and whether each supplier is the preferred one."
        ),
        parameters={
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "The component ID, e.g. 'CMP-0009'.",
                },
            },
            "required": ["component_id"],
        },
    )
    def get_component_suppliers(self, component_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT cs.*, s.name as supplier_name, s.country, "
            "s.reliability_rating "
            "FROM component_suppliers cs "
            "JOIN suppliers s ON cs.supplier_id = s.supplier_id "
            "WHERE cs.component_id = ? "
            "ORDER BY cs.is_preferred DESC, cs.supply_lead_time_days ASC",
            (component_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"component_id": component_id, "suppliers": rows}

    @tool(
        description=(
            "Returns detailed information about a single component."
        ),
        parameters={
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "The component ID, e.g. 'CMP-0009'.",
                },
            },
            "required": ["component_id"],
        },
    )
    def get_component_info(self, component_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM components WHERE component_id = ?",
            (component_id,),
        )
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Component {component_id} not found"}

    # ─────────────────────────────────────────────────────────────────────
    #  GROUND-TRUTH COMPUTATION (used by step)
    # ─────────────────────────────────────────────────────────────────────

    def _read_policy(self):
        """Read stockout_policy.yaml from workspace."""
        path = os.path.join(self.workspace, "stockout_policy.yaml")
        policy = {}
        with open(path) as f:
            text = f.read()
        # Simple YAML parsing (flat + one-level nested)
        current_section = None
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip()
                if val == "":
                    # section header
                    current_section = key
                    policy[current_section] = {}
                elif current_section and line.startswith("  "):
                    policy[current_section][key] = (
                        float(val) if "." in val else int(val)
                    )
                else:
                    current_section = None
                    try:
                        policy[key] = float(val) if "." in val else int(val)
                    except ValueError:
                        policy[key] = val
        return policy

    def _read_demand_adjustments(self):
        """Read all demand_forecast_*.csv files -> {product_code: factor}."""
        adj = {}
        for fpath in sorted(
            glob.glob(os.path.join(self.workspace, "demand_forecast_*.csv"))
        ):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    adj[row["product_code"]] = float(
                        row["demand_adjustment_factor"]
                    )
        return adj

    def _read_supplier_lt_adjustments(self):
        """Read all supplier_performance_*.json -> {supplier_id: adj_days}."""
        adj = {}
        for fpath in sorted(
            glob.glob(
                os.path.join(self.workspace, "supplier_performance_*.json")
            )
        ):
            with open(fpath) as f:
                data = json.load(f)
            for a in data["assessments"]:
                adj[a["supplier_id"]] = a["lead_time_adjustment_days"]
        return adj

    def _read_reserved_quantities(self):
        """Read all warehouse_status_*.md -> {component_id: total_reserved}."""
        reserved = defaultdict(float)
        for fpath in sorted(
            glob.glob(os.path.join(self.workspace, "warehouse_status_*.md"))
        ):
            with open(fpath) as f:
                content = f.read()
            # Parse markdown tables
            in_table = False
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped.startswith("| Component ID"):
                    in_table = True
                    continue
                if in_table and stripped.startswith("|---"):
                    continue
                if in_table and stripped.startswith("|"):
                    parts = [p.strip() for p in stripped.split("|")]
                    # parts: ['', 'CMP-XXXX', '123.4', 'reason', '']
                    parts = [p for p in parts if p]
                    if len(parts) >= 2:
                        cid = parts[0]
                        qty = float(parts[1])
                        reserved[cid] += qty
                elif in_table and not stripped.startswith("|"):
                    in_table = False
        return dict(reserved)

    def _compute_ground_truth(self):
        """Compute expected procurement alerts from DB + workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # ── Read workspace data ──
        policy = self._read_policy()
        demand_adj = self._read_demand_adjustments()
        sup_lt_adj = self._read_supplier_lt_adjustments()
        reserved = self._read_reserved_quantities()

        weights = policy["priority_weights"]
        tiers = policy["priority_tiers"]
        max_lt_bench = policy["max_lead_time_benchmark_days"]
        crit_bonus = policy["criticality_tier_bonus"]

        # ── Active orders ──
        c.execute("SELECT * FROM production_orders WHERE status = 'Active'")
        active_orders = [dict(r) for r in c.fetchall()]

        # ── BOM: product-level (parent IS NULL) ──
        c.execute(
            "SELECT * FROM bill_of_materials WHERE parent_component_id IS NULL"
        )
        product_bom = [dict(r) for r in c.fetchall()]

        # ── BOM: sub-assembly-level (parent IS NOT NULL) ──
        c.execute(
            "SELECT * FROM bill_of_materials "
            "WHERE parent_component_id IS NOT NULL"
        )
        sub_bom_rows = [dict(r) for r in c.fetchall()]
        # sub_bom: parent_id -> [(child_id, qty)]
        sub_bom = defaultdict(list)
        for row in sub_bom_rows:
            sub_bom[row["parent_component_id"]].append(
                (row["child_component_id"], row["quantity_per_unit"])
            )

        # ── Demand calculation ──
        component_demand = defaultdict(float)
        # Also track which orders affect which components (for urgency)
        component_orders = defaultdict(set)  # cid -> set of order_ids

        # product_bom grouped by product_code
        prod_bom_map = defaultdict(list)
        for entry in product_bom:
            prod_bom_map[entry["product_code"]].append(entry)

        for order in active_orders:
            pc = order["product_code"]
            qty = order["quantity"]
            adj_factor = demand_adj.get(pc, 1.0)

            for entry in prod_bom_map.get(pc, []):
                child_id = entry["child_component_id"]
                child_qty = entry["quantity_per_unit"]

                # Check if this child is a sub-assembly (has children in sub_bom)
                if child_id in sub_bom:
                    # Sub-assembly: demand flows to its children
                    for leaf_id, leaf_qty in sub_bom[child_id]:
                        demand = qty * child_qty * leaf_qty * adj_factor
                        component_demand[leaf_id] += demand
                        component_orders[leaf_id].add(order["order_id"])
                else:
                    # Direct leaf component
                    demand = qty * child_qty * adj_factor
                    component_demand[child_id] += demand
                    component_orders[child_id].add(order["order_id"])

                # Sub-assembly itself also gets demand (it's consumed)
                if child_id in sub_bom:
                    sa_demand = qty * child_qty * adj_factor
                    component_demand[child_id] += sa_demand
                    component_orders[child_id].add(order["order_id"])

        # ── Inventory ──
        c.execute("SELECT component_id, SUM(quantity_on_hand) as total "
                  "FROM inventory GROUP BY component_id")
        inv_totals = {r["component_id"]: r["total"] for r in c.fetchall()}

        # ── Components info ──
        c.execute("SELECT * FROM components")
        comp_info = {r["component_id"]: dict(r) for r in c.fetchall()}

        # ── Component suppliers ──
        c.execute(
            "SELECT cs.*, s.name as supplier_name "
            "FROM component_suppliers cs "
            "JOIN suppliers s ON cs.supplier_id = s.supplier_id"
        )
        cs_rows = [dict(r) for r in c.fetchall()]
        comp_sup_map = defaultdict(list)
        for row in cs_rows:
            comp_sup_map[row["component_id"]].append(row)

        # ── Order priorities lookup ──
        order_priority = {o["order_id"]: o["priority"] for o in active_orders}
        priority_map = {"High": 100.0, "Medium": 60.0, "Low": 30.0}

        conn.close()

        # ── Build alerts ──
        alerts = []
        for cid, total_demand in component_demand.items():
            if total_demand <= 0:
                continue
            raw_inv = inv_totals.get(cid, 0)
            res = reserved.get(cid, 0)
            available = max(0, raw_inv - res)
            shortage = total_demand - available
            if shortage <= 0:
                continue

            info = comp_info.get(cid, {})
            is_critical = info.get("is_critical", 0)

            # ── Supplier selection ──
            sups = comp_sup_map.get(cid, [])
            preferred = [s for s in sups if s["is_preferred"] == 1]
            if preferred:
                chosen_sup = preferred[0]
            elif sups:
                # shortest effective lead time
                def eff_lt(s):
                    return s["supply_lead_time_days"] + sup_lt_adj.get(
                        s["supplier_id"], 0
                    )
                chosen_sup = min(sups, key=eff_lt)
            else:
                chosen_sup = None

            if chosen_sup:
                sup_id = chosen_sup["supplier_id"]
                eff_lead_time = (
                    chosen_sup["supply_lead_time_days"]
                    + sup_lt_adj.get(sup_id, 0)
                )
            else:
                sup_id = "N/A"
                eff_lead_time = 0

            # ── Priority score ──
            shortage_pct = min(100.0, (shortage / total_demand) * 100.0)
            crit_pct = 100.0 if is_critical else 0.0
            lt_pct = min(100.0, (eff_lead_time / max_lt_bench) * 100.0)

            # Urgency: max priority among affecting orders
            affecting_oids = component_orders.get(cid, set())
            urgency_vals = [
                priority_map.get(order_priority.get(oid, "Low"), 30.0)
                for oid in affecting_oids
            ]
            urgency_pct = max(urgency_vals) if urgency_vals else 30.0

            score = (
                weights["shortage_ratio"] * shortage_pct
                + weights["criticality"] * crit_pct
                + weights["lead_time_pressure"] * lt_pct
                + weights["order_urgency"] * urgency_pct
            )
            score = round(score, 2)

            # Tier
            tier_score = score + (crit_bonus if is_critical else 0)
            if tier_score >= tiers["Critical"]:
                tier = "Critical"
            elif tier_score >= tiers["High"]:
                tier = "High"
            elif tier_score >= tiers["Medium"]:
                tier = "Medium"
            else:
                tier = "Low"

            alerts.append({
                "component_id": cid,
                "component_name": info.get("name", ""),
                "total_demand": round(total_demand, 2),
                "available_inventory": round(available, 2),
                "shortage_quantity": round(shortage, 2),
                "preferred_supplier_id": sup_id,
                "effective_lead_time_days": int(eff_lead_time),
                "priority_score": score,
                "priority_tier": tier,
            })

        # Sort: priority_score desc, then component_id asc
        alerts.sort(key=lambda a: (-a["priority_score"], a["component_id"]))
        return alerts

    # ─────────────────────────────────────────────────────────────────────
    #  STEP  (evaluation)
    # ─────────────────────────────────────────────────────────────────────

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's
        final response.

        Returns a reward based on evaluation results.

        Args:
            action: The agent's final response.

        Returns:
            reward: The reward based on task completion (between 0.0 and 1.0).
            info: Evaluation results.
        """
        expected = self._compute_ground_truth()
        criteria = {}

        # ── 1. File structure (10 pts) ──
        csv_path = os.path.join(self.workspace, "procurement_alerts.csv")
        expected_cols = [
            "component_id", "component_name", "total_demand",
            "available_inventory", "shortage_quantity",
            "preferred_supplier_id", "effective_lead_time_days",
            "priority_score", "priority_tier",
        ]
        if os.path.exists(csv_path):
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                actual_cols = list(reader.fieldnames or [])
                submitted_rows = list(reader)
            cols_match = actual_cols == expected_cols
            criteria["file_structure"] = {
                "passed": cols_match,
                "score": 10 if cols_match else 3,
                "max_score": 10,
                "reason": None if cols_match else (
                    f"Expected columns {expected_cols}, got {actual_cols}"
                ),
            }
        else:
            submitted_rows = []
            criteria["file_structure"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": "procurement_alerts.csv not found",
            }

        # ── 2. Component identification (25 pts) ──
        expected_ids = set(a["component_id"] for a in expected)
        submitted_ids = set(r.get("component_id", "") for r in submitted_rows)

        if expected_ids:
            tp = len(expected_ids & submitted_ids)
            precision = tp / len(submitted_ids) if submitted_ids else 0
            recall = tp / len(expected_ids)
            f1 = (
                2 * precision * recall / (precision + recall)
                if (precision + recall) > 0
                else 0
            )
            id_score = round(f1 * 25)
        else:
            id_score = 25 if not submitted_ids else 0
            f1 = 1.0 if not submitted_ids else 0

        criteria["component_identification"] = {
            "passed": id_score == 25,
            "score": id_score,
            "max_score": 25,
            "reason": None if id_score == 25 else (
                f"F1={f1:.2f}, expected {len(expected_ids)} components, "
                f"got {len(submitted_ids)}"
            ),
        }

        # ── Helper: build expected lookup ──
        exp_lookup = {a["component_id"]: a for a in expected}

        # ── 3. Numerical accuracy (25 pts) ──
        #    Check total_demand, available_inventory, shortage_quantity
        num_correct = 0
        num_checked = 0
        for row in submitted_rows:
            cid = row.get("component_id", "")
            if cid not in exp_lookup:
                continue
            exp = exp_lookup[cid]
            all_ok = True
            for field in ["total_demand", "available_inventory",
                          "shortage_quantity"]:
                try:
                    actual_val = float(row.get(field, 0))
                except (ValueError, TypeError):
                    all_ok = False
                    break
                exp_val = exp[field]
                tol = max(0.01, abs(exp_val) * 0.01)
                if abs(actual_val - exp_val) > tol:
                    all_ok = False
                    break
            if all_ok:
                num_correct += 1
            num_checked += 1

        if len(expected) > 0 and num_checked > 0:
            num_score = round((num_correct / len(expected)) * 25)
        else:
            num_score = 0

        criteria["numerical_accuracy"] = {
            "passed": num_score == 25,
            "score": num_score,
            "max_score": 25,
            "reason": None if num_score == 25 else (
                f"{num_correct}/{len(expected)} components with correct "
                f"demand/inventory/shortage values"
            ),
        }

        # ── 4. Priority scoring (20 pts) ──
        ps_correct = 0
        for row in submitted_rows:
            cid = row.get("component_id", "")
            if cid not in exp_lookup:
                continue
            try:
                actual_ps = float(row.get("priority_score", -1))
            except (ValueError, TypeError):
                continue
            exp_ps = exp_lookup[cid]["priority_score"]
            if abs(actual_ps - exp_ps) <= max(0.05, abs(exp_ps) * 0.01):
                ps_correct += 1

        if len(expected) > 0:
            ps_score = round((ps_correct / len(expected)) * 20)
        else:
            ps_score = 0

        criteria["priority_scoring"] = {
            "passed": ps_score == 20,
            "score": ps_score,
            "max_score": 20,
            "reason": None if ps_score == 20 else (
                f"{ps_correct}/{len(expected)} components with correct "
                f"priority scores"
            ),
        }

        # ── 5. Sort order and tiers (10 pts) ──
        sort_ok = False
        tier_ok = False

        if submitted_rows and expected:
            # Check sort order
            sub_scores = []
            for row in submitted_rows:
                try:
                    sub_scores.append(float(row.get("priority_score", 0)))
                except (ValueError, TypeError):
                    sub_scores.append(0)
            sort_ok = all(
                sub_scores[i] >= sub_scores[i + 1]
                for i in range(len(sub_scores) - 1)
            )

            # Check tier assignment
            tier_correct = 0
            tier_total = 0
            for row in submitted_rows:
                cid = row.get("component_id", "")
                if cid in exp_lookup:
                    tier_total += 1
                    if row.get("priority_tier") == exp_lookup[cid]["priority_tier"]:
                        tier_correct += 1
            tier_ok = tier_total > 0 and tier_correct == tier_total

        st_score = (5 if sort_ok else 0) + (5 if tier_ok else 0)
        criteria["sort_and_tiers"] = {
            "passed": st_score == 10,
            "score": st_score,
            "max_score": 10,
            "reason": None if st_score == 10 else (
                f"sort_ok={sort_ok}, tier_ok={tier_ok}"
            ),
        }

        # ── 6. Response summary (10 pts) ──
        summary_score = 0
        if action:
            # Check total count mentioned
            total_str = str(len(expected))
            if total_str in action:
                summary_score += 4

            # Check top-3 component IDs mentioned
            top3 = expected[:3]
            top3_found = sum(
                1 for a in top3 if a["component_id"] in action
            )
            if top3_found >= 3:
                summary_score += 3
            elif top3_found >= 1:
                summary_score += 1

            # Check tier counts mentioned
            tier_counts = defaultdict(int)
            for a in expected:
                tier_counts[a["priority_tier"]] += 1
            tiers_found = sum(
                1 for t, cnt in tier_counts.items()
                if str(cnt) in action and t in action
            )
            if tiers_found == len(tier_counts):
                summary_score += 3
            elif tiers_found >= 1:
                summary_score += 1

        criteria["response_summary"] = {
            "passed": summary_score == 10,
            "score": summary_score,
            "max_score": 10,
            "reason": None if summary_score == 10 else (
                f"Scored {summary_score}/10 on summary checks"
            ),
        }

        total_score = sum(v["score"] for v in criteria.values())
        max_score = sum(v["max_score"] for v in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ─────────────────────────────────────────────────────────────────────
    #  VERIFY
    # ─────────────────────────────────────────────────────────────────────

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
        import yaml as _yaml_mod  # optional; we parse manually below

        # ── Read workspace config files ──
        policy = self._read_policy()
        demand_adj = self._read_demand_adjustments()
        sup_lt_adj = self._read_supplier_lt_adjustments()
        reserved = self._read_reserved_quantities()

        weights = policy["priority_weights"]
        tiers_thresholds = policy["priority_tiers"]
        max_lt_bench = policy["max_lead_time_benchmark_days"]
        crit_bonus = policy["criticality_tier_bonus"]

        priority_map = {"High": 100.0, "Medium": 60.0, "Low": 30.0}

        # ── Step 1: Get all active orders (paginated) ──
        all_orders = []
        page = 1
        while True:
            result = self.tools["list_production_orders"](
                status="Active", page=page, page_size=10
            )
            all_orders.extend(result["orders"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ── Step 2: Get top-level BOM for each unique product ──
        product_codes = sorted(set(o["product_code"] for o in all_orders))
        product_bom = {}
        for pc in product_codes:
            result = self.tools["get_product_bom"](product_code=pc)
            product_bom[pc] = result["entries"]

        # ── Step 3: Identify sub-assemblies and get their children ──
        # Collect all unique child component IDs from product BOMs
        all_top_children = set()
        for entries in product_bom.values():
            for e in entries:
                all_top_children.add(e["child_component_id"])

        sub_bom = {}  # component_id -> list of (child_id, qty)
        for cid in sorted(all_top_children):
            result = self.tools["get_subassembly_components"](
                component_id=cid
            )
            if result["entries"]:
                sub_bom[cid] = [
                    (e["child_component_id"], e["quantity_per_unit"])
                    for e in result["entries"]
                ]

        # ── Step 4: Calculate demand per component ──
        component_demand = defaultdict(float)
        component_order_ids = defaultdict(set)

        for order in all_orders:
            pc = order["product_code"]
            qty = order["quantity"]
            adj_factor = demand_adj.get(pc, 1.0)

            for entry in product_bom.get(pc, []):
                child_id = entry["child_component_id"]
                child_qty = entry["quantity_per_unit"]

                if child_id in sub_bom:
                    # Sub-assembly: demand flows to its children
                    for leaf_id, leaf_qty in sub_bom[child_id]:
                        d = qty * child_qty * leaf_qty * adj_factor
                        component_demand[leaf_id] += d
                        component_order_ids[leaf_id].add(order["order_id"])
                    # Sub-assembly itself is also consumed
                    sa_d = qty * child_qty * adj_factor
                    component_demand[child_id] += sa_d
                    component_order_ids[child_id].add(order["order_id"])
                else:
                    d = qty * child_qty * adj_factor
                    component_demand[child_id] += d
                    component_order_ids[child_id].add(order["order_id"])

        # ── Step 5: Get inventory for all demanded components ──
        inv_totals = {}
        for cid in sorted(component_demand.keys()):
            result = self.tools["get_inventory_levels"](component_id=cid)
            total = sum(r["quantity_on_hand"] for r in result["records"])
            inv_totals[cid] = total

        # ── Step 6: Compute shortage ──
        at_risk = []
        for cid in sorted(component_demand.keys()):
            total_demand = component_demand[cid]
            if total_demand <= 0:
                continue
            raw_inv = inv_totals.get(cid, 0)
            res = reserved.get(cid, 0)
            available = max(0, raw_inv - res)
            shortage = total_demand - available
            if shortage > 0:
                at_risk.append((cid, total_demand, available, shortage))

        # ── Step 7: For at-risk, get component info + suppliers ──
        comp_details = {}
        comp_suppliers_data = {}
        for cid, _, _, _ in at_risk:
            comp_details[cid] = self.tools["get_component_info"](
                component_id=cid
            )
            comp_suppliers_data[cid] = self.tools["get_component_suppliers"](
                component_id=cid
            )

        # ── Step 8: Build order priority lookup ──
        order_priority = {o["order_id"]: o["priority"] for o in all_orders}

        # ── Step 9: Compute priority scores and build alerts ──
        alerts = []
        for cid, total_demand, available, shortage in at_risk:
            info = comp_details[cid]
            is_critical = info.get("is_critical", 0)

            # Supplier selection
            sups = comp_suppliers_data[cid].get("suppliers", [])
            preferred = [s for s in sups if s["is_preferred"] == 1]
            if preferred:
                chosen = preferred[0]
            elif sups:
                def eff_lt(s):
                    return (
                        s["supply_lead_time_days"]
                        + sup_lt_adj.get(s["supplier_id"], 0)
                    )
                chosen = min(sups, key=eff_lt)
            else:
                chosen = None

            if chosen:
                sup_id = chosen["supplier_id"]
                eff_lead_time = (
                    chosen["supply_lead_time_days"]
                    + sup_lt_adj.get(sup_id, 0)
                )
            else:
                sup_id = "N/A"
                eff_lead_time = 0

            # Priority score factors
            shortage_pct = min(100.0, (shortage / total_demand) * 100.0)
            crit_pct = 100.0 if is_critical else 0.0
            lt_pct = min(
                100.0, (eff_lead_time / max_lt_bench) * 100.0
            )

            affecting_oids = component_order_ids.get(cid, set())
            urgency_vals = [
                priority_map.get(order_priority.get(oid, "Low"), 30.0)
                for oid in affecting_oids
            ]
            urgency_pct = max(urgency_vals) if urgency_vals else 30.0

            score = (
                weights["shortage_ratio"] * shortage_pct
                + weights["criticality"] * crit_pct
                + weights["lead_time_pressure"] * lt_pct
                + weights["order_urgency"] * urgency_pct
            )
            score = round(score, 2)

            # Tier
            tier_score = score + (crit_bonus if is_critical else 0)
            if tier_score >= tiers_thresholds["Critical"]:
                tier = "Critical"
            elif tier_score >= tiers_thresholds["High"]:
                tier = "High"
            elif tier_score >= tiers_thresholds["Medium"]:
                tier = "Medium"
            else:
                tier = "Low"

            alerts.append({
                "component_id": cid,
                "component_name": info.get("name", ""),
                "total_demand": round(total_demand, 2),
                "available_inventory": round(available, 2),
                "shortage_quantity": round(shortage, 2),
                "preferred_supplier_id": sup_id,
                "effective_lead_time_days": int(eff_lead_time),
                "priority_score": score,
                "priority_tier": tier,
            })

        # Sort: priority_score desc, component_id asc
        alerts.sort(key=lambda a: (-a["priority_score"], a["component_id"]))

        # ── Step 10: Write procurement_alerts.csv ──
        csv_path = os.path.join(self.workspace, "procurement_alerts.csv")
        fieldnames = [
            "component_id", "component_name", "total_demand",
            "available_inventory", "shortage_quantity",
            "preferred_supplier_id", "effective_lead_time_days",
            "priority_score", "priority_tier",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for a in alerts:
                writer.writerow({
                    "component_id": a["component_id"],
                    "component_name": a["component_name"],
                    "total_demand": f"{a['total_demand']:.2f}",
                    "available_inventory": f"{a['available_inventory']:.2f}",
                    "shortage_quantity": f"{a['shortage_quantity']:.2f}",
                    "preferred_supplier_id": a["preferred_supplier_id"],
                    "effective_lead_time_days": a["effective_lead_time_days"],
                    "priority_score": f"{a['priority_score']:.2f}",
                    "priority_tier": a["priority_tier"],
                })

        # ── Step 11: Build response summary ──
        tier_counts = defaultdict(int)
        for a in alerts:
            tier_counts[a["priority_tier"]] += 1

        top3 = alerts[:3]
        top3_lines = []
        for a in top3:
            top3_lines.append(
                f"  {a['component_id']} ({a['component_name']}): "
                f"shortage={a['shortage_quantity']:.2f}, "
                f"priority_score={a['priority_score']:.2f}, "
                f"tier={a['priority_tier']}"
            )

        tier_summary = ", ".join(
            f"{t}: {c}" for t, c in sorted(tier_counts.items())
        )

        action = (
            f"Total components at risk of stockout: {len(alerts)}\n\n"
            f"Top 3 by priority score:\n"
            + "\n".join(top3_lines)
            + f"\n\nPriority tier breakdown: {tier_summary}"
        )

        return self.step(action)
