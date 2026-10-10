"""Environment for component stockout prevention task."""
import os
import json
import csv
import math
import sqlite3
import glob as glob_mod
from datetime import date
from typing import Tuple, Dict, List, Any

import yaml

REFERENCE_DATE = date(2026, 4, 20)
PAGE_SIZE = 20


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

    # ──────────────────────────────────────────
    #  TOOLS
    # ──────────────────────────────────────────

    @tool(
        description=(
            "List components with optional category filter. "
            "Returns up to 20 results per page."
        ),
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["electronic", "mechanical", "raw_material",
                             "chemical", "fastener"],
                    "description": "Filter by component category",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number starting from 1 (default 1)",
                },
            },
            "required": [],
        },
    )
    def list_components(self, category=None, page=1):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        q = "SELECT component_id, name, category, unit FROM components"
        params = []
        if category:
            q += " WHERE category = ?"
            params.append(category)
        q += " ORDER BY component_id"
        rows = conn.execute(q, params).fetchall()
        conn.close()
        start = (page - 1) * PAGE_SIZE
        page_rows = rows[start : start + PAGE_SIZE]
        return {
            "page": page,
            "total": len(rows),
            "results": [dict(r) for r in page_rows],
        }

    @tool(
        description="Get detailed information about a single component by ID.",
        parameters={
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "integer",
                    "description": "The component ID",
                },
            },
            "required": ["component_id"],
        },
    )
    def lookup_component(self, component_id):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM components WHERE component_id = ?",
            (component_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else {"error": "Component not found"}

    @tool(
        description=(
            "List assembly lines with optional status filter. "
            "Returns up to 20 results per page."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "maintenance", "idle"],
                    "description": "Filter by line status",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number starting from 1 (default 1)",
                },
            },
            "required": [],
        },
    )
    def list_assembly_lines(self, status=None, page=1):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        q = "SELECT line_id, name, product, status FROM assembly_lines"
        params = []
        if status:
            q += " WHERE status = ?"
            params.append(status)
        q += " ORDER BY line_id"
        rows = conn.execute(q, params).fetchall()
        conn.close()
        start = (page - 1) * PAGE_SIZE
        page_rows = rows[start : start + PAGE_SIZE]
        return {
            "page": page,
            "total": len(rows),
            "results": [dict(r) for r in page_rows],
        }

    @tool(
        description=(
            "Get production schedules, optionally filtered by line ID "
            "and/or status. Returns up to 20 results per page."
        ),
        parameters={
            "type": "object",
            "properties": {
                "line_id": {
                    "type": "integer",
                    "description": "Filter by assembly line ID",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "planned", "completed"],
                    "description": "Filter by schedule status",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number starting from 1 (default 1)",
                },
            },
            "required": [],
        },
    )
    def get_production_schedules(self, line_id=None, status=None, page=1):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        q = "SELECT * FROM production_schedules WHERE 1=1"
        params = []
        if line_id is not None:
            q += " AND line_id = ?"
            params.append(line_id)
        if status:
            q += " AND status = ?"
            params.append(status)
        q += " ORDER BY schedule_id"
        rows = conn.execute(q, params).fetchall()
        conn.close()
        start = (page - 1) * PAGE_SIZE
        page_rows = rows[start : start + PAGE_SIZE]
        return {
            "page": page,
            "total": len(rows),
            "results": [dict(r) for r in page_rows],
        }

    @tool(
        description=(
            "Get the bill of materials for a specific assembly line: "
            "lists every component used and its units-per-product rate."
        ),
        parameters={
            "type": "object",
            "properties": {
                "line_id": {
                    "type": "integer",
                    "description": "The assembly line ID",
                },
            },
            "required": ["line_id"],
        },
    )
    def get_line_bill_of_materials(self, line_id):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT component_id, units_per_product FROM line_components "
            "WHERE line_id = ? ORDER BY component_id",
            (line_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @tool(
        description=(
            "Get current inventory for a specific component, including "
            "component name and category."
        ),
        parameters={
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "integer",
                    "description": "The component ID",
                },
            },
            "required": ["component_id"],
        },
    )
    def get_inventory(self, component_id):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT i.component_id, c.name, c.category, "
            "i.quantity_on_hand, i.reserved_quantity, i.last_updated "
            "FROM inventory i JOIN components c "
            "ON i.component_id = c.component_id "
            "WHERE i.component_id = ?",
            (component_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else {"error": "Component not found"}

    @tool(
        description=(
            "Get all supplier offers for a specific component, including "
            "supplier name, unit price, lead time, and minimum order quantity."
        ),
        parameters={
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "integer",
                    "description": "The component ID",
                },
            },
            "required": ["component_id"],
        },
    )
    def get_supplier_offers(self, component_id):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT sc.supplier_id, s.name AS supplier_name, "
            "sc.unit_price, sc.lead_time_days, sc.min_order_qty "
            "FROM supplier_components sc "
            "JOIN suppliers s ON sc.supplier_id = s.supplier_id "
            "WHERE sc.component_id = ? "
            "ORDER BY sc.supplier_id",
            (component_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ──────────────────────────────────────────
    #  GROUND-TRUTH COMPUTATION (used by step)
    # ──────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute expected purchase orders from DB + workspace files."""
        today = REFERENCE_DATE
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # ── Config files ──
        with open(os.path.join(self.workspace, "risk_config.yaml")) as f:
            risk_config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "priority_weights.json")) as f:
            pw = json.load(f)

        criticality = {}
        with open(os.path.join(self.workspace,
                               "component_criticality.csv")) as f:
            for row in csv.DictReader(f):
                criticality[int(row["component_id"])] = int(
                    row["criticality_tier"]
                )

        # ── Consumption logs → avg daily consumption ──
        cons_raw: Dict[tuple, list] = {}
        for fp in sorted(
            glob_mod.glob(
                os.path.join(self.workspace, "consumption_log_week_*.csv")
            )
        ):
            with open(fp) as f:
                for row in csv.DictReader(f):
                    key = (int(row["line_id"]), int(row["component_id"]))
                    cons_raw.setdefault(key, []).append(
                        float(row["units_consumed"])
                    )
        avg_cons = {k: sum(v) / len(v) for k, v in cons_raw.items()}

        # ── Supplier delivery reports → on-time rates ──
        supp_del: Dict[int, list] = {}
        for fp in sorted(
            glob_mod.glob(
                os.path.join(self.workspace,
                             "supplier_delivery_batch_*.json")
            )
        ):
            with open(fp) as f:
                for rec in json.load(f):
                    sid = rec["supplier_id"]
                    supp_del.setdefault(sid, [0, 0])
                    supp_del[sid][1] += 1
                    if rec["actual_lead_days"] <= rec["promised_lead_days"]:
                        supp_del[sid][0] += 1
        on_time = {
            sid: d[0] / d[1] for sid, d in supp_del.items() if d[1] > 0
        }

        # ── Active schedules ──
        schedules = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM production_schedules WHERE status='active'"
            ).fetchall()
        ]

        # ── BOMs ──
        bom_all = {}
        for r in conn.execute(
            "SELECT line_id, component_id, units_per_product "
            "FROM line_components"
        ):
            bom_all.setdefault(r[0], []).append((r[1], r[2]))

        # ── Demand projection ──
        comp_demand: Dict[int, float] = {}
        comp_max_pri: Dict[int, str] = {}
        # Also collect (line_id, daily_target) per component for fallback
        comp_line_info: Dict[int, list] = {}

        pri_rank = {"high": 3, "medium": 2, "low": 1}

        for sched in schedules:
            lid = sched["line_id"]
            end_d = date.fromisoformat(sched["end_date"])
            remaining_days = max(0, (end_d - today).days)
            daily_target = sched["daily_target"]
            priority = sched["priority"]

            for cid, upr in bom_all.get(lid, []):
                key = (lid, cid)
                if key in avg_cons:
                    projected = avg_cons[key] * remaining_days
                else:
                    projected = remaining_days * daily_target * upr

                comp_demand[cid] = comp_demand.get(cid, 0) + projected

                if (
                    cid not in comp_max_pri
                    or pri_rank.get(priority, 0)
                    > pri_rank.get(comp_max_pri[cid], 0)
                ):
                    comp_max_pri[cid] = priority

                comp_line_info.setdefault(cid, []).append(
                    (lid, daily_target, upr)
                )

        # ── Inventory + safety stock → net need ──
        safety_days = risk_config["safety_stock_days"]
        risk_levels_cfg = risk_config["risk_levels"]
        weights = pw["weights"]
        crit_scores = pw["criticality_scores"]
        prod_pri_scores = pw["production_priority_scores"]

        at_risk = {}
        for cid, proj_demand in comp_demand.items():
            if proj_demand <= 0:
                continue
            inv_row = conn.execute(
                "SELECT i.quantity_on_hand, i.reserved_quantity, c.category, "
                "c.name FROM inventory i JOIN components c "
                "ON i.component_id = c.component_id "
                "WHERE i.component_id = ?",
                (cid,),
            ).fetchone()
            if not inv_row:
                continue

            qty_oh = inv_row[0]
            qty_res = inv_row[1]
            cat = inv_row[2]
            comp_name = inv_row[3]
            available = qty_oh - qty_res

            # Total daily consumption across active lines
            total_daily = 0.0
            for lid, dt, upr in comp_line_info.get(cid, []):
                key = (lid, cid)
                if key in avg_cons:
                    total_daily += avg_cons[key]
                else:
                    total_daily += dt * upr

            ss_days = safety_days.get(cat, 5)
            safety_qty = total_daily * ss_days

            net_need = proj_demand - available + safety_qty

            if net_need > 0:
                shortage_sev = min(1.0, net_need / max(1.0, proj_demand))
                days_stockout = (
                    available / total_daily if total_daily > 0 else 9999.0
                )

                at_risk[cid] = {
                    "component_id": cid,
                    "component_name": comp_name,
                    "category": cat,
                    "net_need": net_need,
                    "projected_demand": proj_demand,
                    "available": available,
                    "safety_qty": safety_qty,
                    "shortage_severity": shortage_sev,
                    "days_until_stockout": days_stockout,
                    "max_priority": comp_max_pri.get(cid, "low"),
                    "criticality_tier": criticality.get(cid, 3),
                    "total_daily": total_daily,
                }

        # ── Supplier selection & purchase orders ──
        orders = []
        for cid, info in at_risk.items():
            offers = [
                dict(r)
                for r in conn.execute(
                    "SELECT sc.supplier_id, s.name AS supplier_name, "
                    "sc.unit_price, sc.lead_time_days, sc.min_order_qty "
                    "FROM supplier_components sc "
                    "JOIN suppliers s ON sc.supplier_id = s.supplier_id "
                    "WHERE sc.component_id = ? ORDER BY sc.supplier_id",
                    (cid,),
                ).fetchall()
            ]
            if not offers:
                continue

            # Compute adjusted cost per offer
            enriched = []
            for o in offers:
                otr = on_time.get(o["supplier_id"], 0)
                if otr >= 0.90:
                    factor = 1.00
                elif otr >= 0.80:
                    factor = 1.15
                elif otr >= 0.70:
                    factor = 1.30
                else:
                    factor = 1.50
                enriched.append({
                    **o,
                    "on_time_rate": otr,
                    "factor": factor,
                    "adj_cost": o["unit_price"] * factor,
                })

            qualifying = [e for e in enriched if e["on_time_rate"] >= 0.80]
            if qualifying:
                best = min(qualifying, key=lambda x: x["adj_cost"])
            else:
                best = max(enriched, key=lambda x: x["on_time_rate"])

            # Order quantity
            moq = best["min_order_qty"]
            base_qty = math.ceil(info["net_need"])
            if base_qty <= moq:
                order_qty = moq
            else:
                order_qty = math.ceil(base_qty / moq) * moq

            # Estimated lead time
            otr = best["on_time_rate"]
            est_lead = math.ceil(best["lead_time_days"] / max(0.01, otr))

            # Priority score
            sev = info["shortage_severity"]
            tier = info["criticality_tier"]
            crit_s = crit_scores.get(f"tier_{tier}", 0.3)
            prod_s = prod_pri_scores.get(info["max_priority"], 0.3)
            lead_urg = min(
                1.0, est_lead / max(1.0, info["days_until_stockout"])
            )

            priority_score = round(
                weights["shortage_severity"] * sev
                + weights["criticality"] * crit_s
                + weights["production_priority"] * prod_s
                + weights["lead_time_urgency"] * lead_urg,
                2,
            )

            # Risk level
            risk_level = "low"
            for level in ["critical", "high", "medium", "low"]:
                if sev >= risk_levels_cfg[level]:
                    risk_level = level
                    break

            total_cost = round(order_qty * best["unit_price"], 2)

            orders.append({
                "component_id": cid,
                "component_name": info["component_name"],
                "supplier_id": best["supplier_id"],
                "supplier_name": best["supplier_name"],
                "order_quantity": order_qty,
                "unit_price": best["unit_price"],
                "total_cost": total_cost,
                "priority_score": priority_score,
                "risk_level": risk_level,
                "estimated_lead_days": est_lead,
            })

        conn.close()

        # Sort: priority_score desc, component_id asc
        orders.sort(key=lambda x: (-x["priority_score"], x["component_id"]))
        return orders

    # ──────────────────────────────────────────
    #  STEP (evaluation)
    # ──────────────────────────────────────────

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's
        final response.
        """
        truth = self._compute_ground_truth()
        truth_ids = {o["component_id"] for o in truth}
        truth_map = {o["component_id"]: o for o in truth}
        grand_total = sum(o["total_cost"] for o in truth)

        criteria = {}
        max_total = 0

        # ── C1: File exists with correct columns (10 pts) ──
        po_path = os.path.join(self.workspace, "purchase_orders.csv")
        expected_cols = [
            "component_id", "component_name", "supplier_id", "supplier_name",
            "order_quantity", "unit_price", "total_cost", "priority_score",
            "risk_level", "estimated_lead_days",
        ]
        c1_score = 0
        c1_max = 10
        agent_orders = []
        if os.path.isfile(po_path):
            with open(po_path) as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames or []
                if cols == expected_cols:
                    c1_score = 10
                    agent_orders = list(reader)
                else:
                    c1_score = 3  # file exists but wrong columns
        criteria["file_format"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": "" if c1_score == c1_max else "Missing file or wrong columns",
        }
        max_total += c1_max

        # Parse agent orders
        agent_map = {}
        for row in agent_orders:
            try:
                cid = int(row["component_id"])
                agent_map[cid] = row
            except (ValueError, KeyError):
                pass
        agent_ids = set(agent_map.keys())

        # ── C2: At-risk component identification (20 pts) ──
        c2_max = 20
        if len(truth_ids) == 0:
            c2_score = 20 if len(agent_ids) == 0 else 0
        else:
            correct = truth_ids & agent_ids
            extra = agent_ids - truth_ids
            missing = truth_ids - agent_ids
            precision = len(correct) / max(1, len(agent_ids))
            recall = len(correct) / len(truth_ids)
            f1 = (
                2 * precision * recall / max(0.001, precision + recall)
            )
            c2_score = round(c2_max * f1)
        criteria["component_identification"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": (
                ""
                if c2_score == c2_max
                else f"missing={len(truth_ids - agent_ids)}, extra={len(agent_ids - truth_ids)}"
            ),
        }
        max_total += c2_max

        # ── C3: Order quantities (20 pts) ──
        c3_max = 20
        correct_qty = 0
        common = truth_ids & agent_ids
        for cid in common:
            try:
                agent_qty = int(agent_map[cid]["order_quantity"])
                truth_qty = truth_map[cid]["order_quantity"]
                if truth_qty > 0 and abs(agent_qty - truth_qty) / truth_qty <= 0.05:
                    correct_qty += 1
            except (ValueError, KeyError):
                pass
        c3_score = round(c3_max * correct_qty / max(1, len(truth_ids)))
        criteria["order_quantities"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": (
                ""
                if c3_score == c3_max
                else f"correct={correct_qty}/{len(truth_ids)}"
            ),
        }
        max_total += c3_max

        # ── C4: Priority scores (15 pts) ──
        c4_max = 15
        correct_pri = 0
        for cid in common:
            try:
                agent_ps = float(agent_map[cid]["priority_score"])
                truth_ps = truth_map[cid]["priority_score"]
                if abs(agent_ps - truth_ps) <= 0.05:
                    correct_pri += 1
            except (ValueError, KeyError):
                pass
        c4_score = round(c4_max * correct_pri / max(1, len(truth_ids)))
        criteria["priority_scores"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": (
                ""
                if c4_score == c4_max
                else f"correct={correct_pri}/{len(truth_ids)}"
            ),
        }
        max_total += c4_max

        # ── C5: Supplier selection (15 pts) ──
        c5_max = 15
        correct_supp = 0
        for cid in common:
            try:
                agent_sid = int(agent_map[cid]["supplier_id"])
                if agent_sid == truth_map[cid]["supplier_id"]:
                    correct_supp += 1
            except (ValueError, KeyError):
                pass
        c5_score = round(c5_max * correct_supp / max(1, len(truth_ids)))
        criteria["supplier_selection"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": (
                ""
                if c5_score == c5_max
                else f"correct={correct_supp}/{len(truth_ids)}"
            ),
        }
        max_total += c5_max

        # ── C6: Risk levels (10 pts) ──
        c6_max = 10
        correct_risk = 0
        for cid in common:
            try:
                if agent_map[cid]["risk_level"] == truth_map[cid]["risk_level"]:
                    correct_risk += 1
            except KeyError:
                pass
        c6_score = round(c6_max * correct_risk / max(1, len(truth_ids)))
        criteria["risk_levels"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": (
                ""
                if c6_score == c6_max
                else f"correct={correct_risk}/{len(truth_ids)}"
            ),
        }
        max_total += c6_max

        # ── C7: Response summary (10 pts) ──
        c7_max = 10
        c7_score = 0
        # Check total count
        n_truth = len(truth)
        if str(n_truth) in action:
            c7_score += 4
        # Check grand total cost (formatted as $X,XXX.XX or $X.XX)
        gt_str = f"${grand_total:,.2f}"
        gt_str_plain = f"${grand_total:.2f}"
        if gt_str in action or gt_str_plain in action:
            c7_score += 6
        criteria["response_summary"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": (
                ""
                if c7_score == c7_max
                else f"Expected count={n_truth}, total={gt_str}"
            ),
        }
        max_total += c7_max

        total_score = sum(c["score"] for c in criteria.values())
        return total_score / max_total, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_total,
        }

    # ──────────────────────────────────────────
    #  VERIFY (self-test via tools + workspace)
    # ──────────────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        today = REFERENCE_DATE

        # ── Read workspace config files ──
        with open(os.path.join(self.workspace, "risk_config.yaml")) as f:
            risk_config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "priority_weights.json")) as f:
            pw = json.load(f)

        criticality = {}
        with open(os.path.join(self.workspace,
                               "component_criticality.csv")) as f:
            for row in csv.DictReader(f):
                criticality[int(row["component_id"])] = int(
                    row["criticality_tier"]
                )

        # ── Read consumption logs ──
        cons_raw: Dict[tuple, list] = {}
        for fp in sorted(
            glob_mod.glob(
                os.path.join(self.workspace, "consumption_log_week_*.csv")
            )
        ):
            with open(fp) as f:
                for row in csv.DictReader(f):
                    key = (int(row["line_id"]), int(row["component_id"]))
                    cons_raw.setdefault(key, []).append(
                        float(row["units_consumed"])
                    )
        avg_cons = {k: sum(v) / len(v) for k, v in cons_raw.items()}

        # ── Read supplier delivery reports ──
        supp_del: Dict[int, list] = {}
        for fp in sorted(
            glob_mod.glob(
                os.path.join(self.workspace,
                             "supplier_delivery_batch_*.json")
            )
        ):
            with open(fp) as f:
                for rec in json.load(f):
                    sid = rec["supplier_id"]
                    supp_del.setdefault(sid, [0, 0])
                    supp_del[sid][1] += 1
                    if rec["actual_lead_days"] <= rec["promised_lead_days"]:
                        supp_del[sid][0] += 1
        on_time = {
            sid: d[0] / d[1] for sid, d in supp_del.items() if d[1] > 0
        }

        # ── Get active schedules via tools (paginated) ──
        all_schedules = []
        page = 1
        while True:
            result = self.tools["get_production_schedules"](
                status="active", page=page
            )
            all_schedules.extend(result["results"])
            if page * PAGE_SIZE >= result["total"]:
                break
            page += 1

        # ── Get BOMs for each unique active line ──
        active_line_ids = sorted(set(s["line_id"] for s in all_schedules))
        bom_all = {}
        for lid in active_line_ids:
            bom_all[lid] = self.tools["get_line_bill_of_materials"](
                line_id=lid
            )

        # ── Demand projection ──
        comp_demand: Dict[int, float] = {}
        comp_max_pri: Dict[int, str] = {}
        comp_line_info: Dict[int, list] = {}
        pri_rank = {"high": 3, "medium": 2, "low": 1}

        for sched in all_schedules:
            lid = sched["line_id"]
            end_d = date.fromisoformat(sched["end_date"])
            remaining_days = max(0, (end_d - today).days)
            daily_target = sched["daily_target"]
            priority = sched["priority"]

            for entry in bom_all.get(lid, []):
                cid = entry["component_id"]
                upr = entry["units_per_product"]
                key = (lid, cid)

                if key in avg_cons:
                    projected = avg_cons[key] * remaining_days
                else:
                    projected = remaining_days * daily_target * upr

                comp_demand[cid] = comp_demand.get(cid, 0) + projected

                if (
                    cid not in comp_max_pri
                    or pri_rank.get(priority, 0)
                    > pri_rank.get(comp_max_pri[cid], 0)
                ):
                    comp_max_pri[cid] = priority

                comp_line_info.setdefault(cid, []).append(
                    (lid, daily_target, upr)
                )

        # ── Inventory check + safety stock ──
        safety_days = risk_config["safety_stock_days"]
        risk_levels_cfg = risk_config["risk_levels"]
        weights = pw["weights"]
        crit_scores = pw["criticality_scores"]
        prod_pri_scores = pw["production_priority_scores"]

        at_risk = {}
        for cid in sorted(comp_demand.keys()):
            proj_demand = comp_demand[cid]
            if proj_demand <= 0:
                continue

            inv = self.tools["get_inventory"](component_id=cid)
            if "error" in inv:
                continue

            available = inv["quantity_on_hand"] - inv["reserved_quantity"]
            cat = inv["category"]
            comp_name = inv["name"]

            total_daily = 0.0
            for lid, dt, upr in comp_line_info.get(cid, []):
                key = (lid, cid)
                if key in avg_cons:
                    total_daily += avg_cons[key]
                else:
                    total_daily += dt * upr

            ss_d = safety_days.get(cat, 5)
            safety_qty = total_daily * ss_d
            net_need = proj_demand - available + safety_qty

            if net_need > 0:
                shortage_sev = min(1.0, net_need / max(1.0, proj_demand))
                days_stockout = (
                    available / total_daily if total_daily > 0 else 9999.0
                )
                at_risk[cid] = {
                    "component_id": cid,
                    "component_name": comp_name,
                    "category": cat,
                    "net_need": net_need,
                    "projected_demand": proj_demand,
                    "available": available,
                    "safety_qty": safety_qty,
                    "shortage_severity": shortage_sev,
                    "days_until_stockout": days_stockout,
                    "max_priority": comp_max_pri.get(cid, "low"),
                    "criticality_tier": criticality.get(cid, 3),
                    "total_daily": total_daily,
                }

        # ── Supplier selection & purchase orders ──
        orders = []
        for cid in sorted(at_risk.keys()):
            info = at_risk[cid]
            offers = self.tools["get_supplier_offers"](component_id=cid)
            if not offers:
                continue

            enriched = []
            for o in offers:
                otr = on_time.get(o["supplier_id"], 0)
                if otr >= 0.90:
                    factor = 1.00
                elif otr >= 0.80:
                    factor = 1.15
                elif otr >= 0.70:
                    factor = 1.30
                else:
                    factor = 1.50
                enriched.append({
                    **o,
                    "on_time_rate": otr,
                    "factor": factor,
                    "adj_cost": o["unit_price"] * factor,
                })

            qualifying = [e for e in enriched if e["on_time_rate"] >= 0.80]
            if qualifying:
                best = min(qualifying, key=lambda x: x["adj_cost"])
            else:
                best = max(enriched, key=lambda x: x["on_time_rate"])

            moq = best["min_order_qty"]
            base_qty = math.ceil(info["net_need"])
            if base_qty <= moq:
                order_qty = moq
            else:
                order_qty = math.ceil(base_qty / moq) * moq

            otr = best["on_time_rate"]
            est_lead = math.ceil(best["lead_time_days"] / max(0.01, otr))

            sev = info["shortage_severity"]
            tier = info["criticality_tier"]
            crit_s = crit_scores.get(f"tier_{tier}", 0.3)
            prod_s = prod_pri_scores.get(info["max_priority"], 0.3)
            lead_urg = min(
                1.0, est_lead / max(1.0, info["days_until_stockout"])
            )

            priority_score = round(
                weights["shortage_severity"] * sev
                + weights["criticality"] * crit_s
                + weights["production_priority"] * prod_s
                + weights["lead_time_urgency"] * lead_urg,
                2,
            )

            risk_level = "low"
            for level in ["critical", "high", "medium", "low"]:
                if sev >= risk_levels_cfg[level]:
                    risk_level = level
                    break

            total_cost = round(order_qty * best["unit_price"], 2)

            orders.append({
                "component_id": cid,
                "component_name": info["component_name"],
                "supplier_id": best["supplier_id"],
                "supplier_name": best["supplier_name"],
                "order_quantity": order_qty,
                "unit_price": best["unit_price"],
                "total_cost": total_cost,
                "priority_score": priority_score,
                "risk_level": risk_level,
                "estimated_lead_days": est_lead,
            })

        # Sort
        orders.sort(key=lambda x: (-x["priority_score"], x["component_id"]))

        # ── Write purchase_orders.csv ──
        fieldnames = [
            "component_id", "component_name", "supplier_id", "supplier_name",
            "order_quantity", "unit_price", "total_cost", "priority_score",
            "risk_level", "estimated_lead_days",
        ]
        with open(
            os.path.join(self.workspace, "purchase_orders.csv"), "w",
            newline="",
        ) as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(orders)

        # ── Build action string ──
        grand_total = sum(o["total_cost"] for o in orders)
        n_risk = len(orders)

        action = (
            f"Analysis complete. Identified {n_risk} components at risk of "
            f"stockout. Total purchase order cost: ${grand_total:,.2f}. "
            f"Generated purchase_orders.csv with {n_risk} prioritized orders."
        )
        if orders:
            action += " Top 3 highest priority components: "
            top3 = orders[:3]
            parts = []
            for o in top3:
                parts.append(
                    f"{o['component_name']} (priority: {o['priority_score']}, "
                    f"risk: {o['risk_level']})"
                )
            action += ", ".join(parts) + "."

        return self.step(action)
