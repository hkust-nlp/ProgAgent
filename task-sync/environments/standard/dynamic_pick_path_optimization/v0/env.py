"""Warehouse pick-path optimization – environment & evaluation."""

from typing import Tuple, Dict, List, Any
import csv
import json
import os
import re
import sqlite3
import glob as glob_module


# ── decorator ─────────────────────────────────────────────────────────
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

    # ── Tool methods ──────────────────────────────────────────────────

    @tool(
        description=(
            "List pending orders with pagination. Returns order_id, customer_id, "
            "order_date, and priority for orders whose status is 'pending'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 20, default 10).",
                },
            },
            "required": ["page"],
        },
    )
    def list_pending_orders(self, page: int, page_size: int = 10):
        page_size = max(1, min(int(page_size), 20))
        page = max(1, int(page))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM orders WHERE status='pending'")
        total = cur.fetchone()["cnt"]
        offset = (page - 1) * page_size
        cur.execute(
            "SELECT order_id, customer_id, order_date, priority "
            "FROM orders WHERE status='pending' ORDER BY order_id "
            "LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        total_pages = max(1, (total + page_size - 1) // page_size)
        return {
            "orders": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        }

    @tool(
        description=(
            "Retrieve all line-items for a given order. "
            "Returns item_id, sku_id, and quantity for each item."
        ),
        parameters={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "Order identifier, e.g. ORD0001.",
                },
            },
            "required": ["order_id"],
        },
    )
    def get_order_items(self, order_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT item_id, sku_id, quantity FROM order_items "
            "WHERE order_id=? ORDER BY item_id",
            (order_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"order_id": order_id, "items": rows}

    @tool(
        description=(
            "Get full details for a single SKU: sku_id, sku_name, category, "
            "weight_kg, volume_liters, zone_id, shelf_position, is_fragile."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sku_id": {
                    "type": "string",
                    "description": "SKU identifier, e.g. SKU0001.",
                },
            },
            "required": ["sku_id"],
        },
    )
    def get_sku_details(self, sku_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM skus WHERE sku_id=?", (sku_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"SKU {sku_id} not found"}

    @tool(
        description="List all currently active (on-duty) pickers. Returns picker_id and name.",
        parameters={"type": "object", "properties": {}, "required": []},
    )
    def list_active_pickers(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT picker_id, name FROM pickers WHERE is_active=1 ORDER BY picker_id"
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"pickers": rows}

    @tool(
        description=(
            "Get detailed information for one picker: picker_id, name, shift, "
            "max_weight_kg, max_volume_liters, current_zone_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "picker_id": {
                    "type": "string",
                    "description": "Picker identifier, e.g. P001.",
                },
            },
            "required": ["picker_id"],
        },
    )
    def get_picker_info(self, picker_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT picker_id, name, shift, max_weight_kg, "
            "max_volume_liters, current_zone_id "
            "FROM pickers WHERE picker_id=?",
            (picker_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Picker {picker_id} not found"}

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _manhattan(z1: str, z2: str, zone_map: dict) -> float:
        a = zone_map.get(z1)
        b = zone_map.get(z2)
        if a is None or b is None:
            return float("inf")
        return abs(a["x_coord"] - b["x_coord"]) + abs(a["y_coord"] - b["y_coord"])

    def _nearest_neighbor_route(self, start_zone: str, zones_to_visit: set,
                                zone_map: dict) -> list:
        """Nearest-neighbor traversal from *start_zone* over *zones_to_visit*."""
        remaining = set(zones_to_visit)
        current = start_zone
        route: list = []
        while remaining:
            best, best_d = None, float("inf")
            for z in sorted(remaining):          # sorted → tie-break by zone_id
                d = self._manhattan(current, z, zone_map)
                if d < best_d or (d == best_d and (best is None or z < best)):
                    best_d = d
                    best = z
            if best is None:
                break
            route.append(best)
            remaining.remove(best)
            current = best
        return route

    # ── shared workspace / DB loaders ─────────────────────────────────

    def _load_workspace(self):
        import yaml as _yaml

        with open(os.path.join(self.workspace, "zone_map.json")) as f:
            zone_map = json.load(f)
        with open(os.path.join(self.workspace, "picking_policy.yaml")) as f:
            policy = _yaml.safe_load(f)

        certs: dict = {}
        with open(os.path.join(self.workspace, "picker_certifications.csv")) as f:
            for row in csv.DictReader(f):
                certs[row["picker_id"]] = {
                    "cold_chain": int(row["cold_chain_certified"]),
                    "hazmat": int(row["hazmat_certified"]),
                }

        special: dict = {}
        for bf in sorted(glob_module.glob(
                os.path.join(self.workspace, "order_batch_*.csv"))):
            with open(bf) as f:
                for row in csv.DictReader(f):
                    special[row["order_id"]] = row["special_handling"]

        return zone_map, policy, certs, special

    def _load_db_ground_truth(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT * FROM orders WHERE status='pending' ORDER BY order_id")
        pending = [dict(r) for r in cur.fetchall()]

        oi_map: dict = {}
        for o in pending:
            cur.execute(
                "SELECT item_id, sku_id, quantity FROM order_items WHERE order_id=?",
                (o["order_id"],),
            )
            oi_map[o["order_id"]] = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM skus")
        skus = {r["sku_id"]: dict(r) for r in cur.fetchall()}

        cur.execute("SELECT * FROM pickers WHERE is_active=1 ORDER BY picker_id")
        pickers = [dict(r) for r in cur.fetchall()]

        conn.close()
        return pending, oi_map, skus, pickers

    # ── deterministic assignment ──────────────────────────────────────

    @staticmethod
    def _compute_assignment(pending_orders, oi_map, skus, active_pickers,
                            certs, special, policy):
        """Return {picker_id: [order_dicts]} following the deterministic rules."""
        prio = {"urgent": 0, "express": 1, "standard": 2}
        sorted_orders = sorted(
            pending_orders,
            key=lambda o: (prio.get(o["priority"], 9), o["order_id"]),
        )

        remaining = {}
        for p in active_pickers:
            remaining[p["picker_id"]] = {
                "w": min(p["max_weight_kg"], policy["max_batch_weight_kg"]),
                "v": min(p["max_volume_liters"], policy["max_batch_volume_liters"]),
                "n": policy["max_items_per_batch"],
            }

        assign: dict = {p["picker_id"]: [] for p in active_pickers}

        for order in sorted_orders:
            oid = order["order_id"]
            items = oi_map.get(oid, [])
            tw = sum(skus[it["sku_id"]]["weight_kg"] * it["quantity"] for it in items)
            tv = sum(skus[it["sku_id"]]["volume_liters"] * it["quantity"] for it in items)
            tn = sum(it["quantity"] for it in items)
            sh = special.get(oid, "none")

            eligible = []
            for p in active_pickers:
                pid = p["picker_id"]
                r = remaining[pid]
                if r["w"] < tw - 0.01 or r["v"] < tv - 0.01 or r["n"] < tn:
                    continue
                if sh == "cold_chain" and not certs.get(pid, {}).get("cold_chain", 0):
                    continue
                if sh == "hazmat" and not certs.get(pid, {}).get("hazmat", 0):
                    continue
                eligible.append(pid)

            if not eligible:
                continue

            # Most remaining weight; tie-break picker_id ascending
            best_pid, best_rem = None, -1.0
            for pid in sorted(eligible):
                rw = remaining[pid]["w"]
                if rw > best_rem + 0.001:
                    best_rem = rw
                    best_pid = pid

            if best_pid is None:
                continue

            assign[best_pid].append(order)
            remaining[best_pid]["w"] -= tw
            remaining[best_pid]["v"] -= tv
            remaining[best_pid]["n"] -= tn

        return {pid: ords for pid, ords in assign.items() if ords}

    # ── step ──────────────────────────────────────────────────────────

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
        zone_map, policy, certs, special = self._load_workspace()
        pending, oi_map, skus, pickers = self._load_db_ground_truth()
        gt = self._compute_assignment(pending, oi_map, skus, pickers,
                                      certs, special, policy)

        criteria: dict = {}

        # ── 1. Pick-list files & column format (15 pts) ──────────────
        expected_pids = set(gt.keys())
        found_pids: set = set()
        agent_lists: Dict[str, list] = {}
        fmt_ok = True
        REQ_COLS = {
            "sequence", "zone_id", "zone_name", "sku_id", "sku_name",
            "order_id", "quantity", "item_weight_kg", "item_volume_liters",
            "shelf_position",
        }

        for pid in expected_pids:
            fp = os.path.join(self.workspace, f"pick_list_{pid}.csv")
            if os.path.exists(fp):
                found_pids.add(pid)
                with open(fp) as fh:
                    rdr = csv.DictReader(fh)
                    rows = list(rdr)
                    if not REQ_COLS.issubset(set(rdr.fieldnames or [])):
                        fmt_ok = False
                    agent_lists[pid] = rows
            else:
                fmt_ok = False

        file_pts = (len(found_pids) / max(len(expected_pids), 1)) * 10
        if fmt_ok and found_pids == expected_pids:
            file_pts += 5
        file_pts = round(min(file_pts, 15), 2)

        criteria["pick_list_files_format"] = {
            "passed": file_pts == 15,
            "score": file_pts,
            "max_score": 15,
        }
        if file_pts < 15:
            criteria["pick_list_files_format"]["reason"] = (
                f"Expected {len(expected_pids)} lists, found {len(found_pids)}, "
                f"format_ok={fmt_ok}"
            )

        # ── 2. Order coverage (15 pts) ───────────────────────────────
        agent_oids: set = set()
        for rows in agent_lists.values():
            for r in rows:
                agent_oids.add(r.get("order_id", ""))
        gt_oids = {o["order_id"] for ords in gt.values() for o in ords}
        cov = len(agent_oids & gt_oids) / max(len(gt_oids), 1)
        cov_pts = round(cov * 15, 2)
        criteria["order_coverage"] = {
            "passed": cov_pts == 15,
            "score": cov_pts,
            "max_score": 15,
        }
        if cov_pts < 15:
            criteria["order_coverage"]["reason"] = (
                f"{len(agent_oids & gt_oids)}/{len(gt_oids)} orders covered"
            )

        # ── 3. Assignment correctness (20 pts) ───────────────────────
        match_count = 0
        total_gt = sum(len(v) for v in gt.values())
        for pid, ords in gt.items():
            agent_oids_pid = {r["order_id"] for r in agent_lists.get(pid, [])}
            for o in ords:
                if o["order_id"] in agent_oids_pid:
                    match_count += 1
        assign_pts = round((match_count / max(total_gt, 1)) * 20, 2)
        criteria["assignment_correctness"] = {
            "passed": assign_pts == 20,
            "score": assign_pts,
            "max_score": 20,
        }
        if assign_pts < 20:
            criteria["assignment_correctness"]["reason"] = (
                f"{match_count}/{total_gt} orders matched ground-truth assignment"
            )

        # ── 4. Weight & volume constraints (15 pts) ──────────────────
        cap_ok = 0
        cap_total = max(len(agent_lists), 1)
        for pid, rows in agent_lists.items():
            try:
                tw = sum(float(r.get("item_weight_kg", 0)) for r in rows)
                tv = sum(float(r.get("item_volume_liters", 0)) for r in rows)
            except (ValueError, TypeError):
                continue
            p_info = next((p for p in pickers if p["picker_id"] == pid), None)
            if p_info is None:
                continue
            ew = min(p_info["max_weight_kg"], policy["max_batch_weight_kg"])
            ev = min(p_info["max_volume_liters"], policy["max_batch_volume_liters"])
            if tw <= ew + 0.05 and tv <= ev + 0.05:
                cap_ok += 1
        cap_pts = round((cap_ok / cap_total) * 15, 2)
        criteria["capacity_constraints"] = {
            "passed": cap_pts == 15,
            "score": cap_pts,
            "max_score": 15,
        }
        if cap_pts < 15:
            criteria["capacity_constraints"]["reason"] = (
                f"{cap_ok}/{cap_total} pickers within weight/volume limits"
            )

        # ── 5. Certification constraints (15 pts) ────────────────────
        cert_ok = cert_total = 0
        for pid, rows in agent_lists.items():
            seen_oids = {r["order_id"] for r in rows}
            for oid in seen_oids:
                sh = special.get(oid, "none")
                if sh in ("cold_chain", "hazmat"):
                    cert_total += 1
                    pc = certs.get(pid, {"cold_chain": 0, "hazmat": 0})
                    if (sh == "cold_chain" and pc["cold_chain"]) or \
                       (sh == "hazmat" and pc["hazmat"]):
                        cert_ok += 1
        cert_pts = 15.0 if cert_total == 0 else round((cert_ok / cert_total) * 15, 2)
        criteria["certification_constraints"] = {
            "passed": cert_pts == 15,
            "score": cert_pts,
            "max_score": 15,
        }
        if cert_pts < 15:
            criteria["certification_constraints"]["reason"] = (
                f"{cert_ok}/{cert_total} special-handling orders correctly certified"
            )

        # ── 6. Route optimization (10 pts) ───────────────────────────
        route_ok = route_total = 0
        for pid, rows in agent_lists.items():
            if not rows:
                continue
            route_total += 1
            seen: list = []
            seen_set: set = set()
            for r in sorted(rows, key=lambda x: (
                    int(x["sequence"]), x["shelf_position"], x["sku_id"])):
                z = r["zone_id"]
                if z not in seen_set:
                    seen.append(z)
                    seen_set.add(z)
            p_info = next((p for p in pickers if p["picker_id"] == pid), None)
            if p_info is None:
                continue
            needed = {r["zone_id"] for r in rows}
            expected = self._nearest_neighbor_route(
                p_info["current_zone_id"], needed, zone_map)
            if seen == expected:
                route_ok += 1
        route_pts = 10.0 if route_total == 0 else round(
            (route_ok / route_total) * 10, 2)
        criteria["route_optimization"] = {
            "passed": route_pts == 10,
            "score": route_pts,
            "max_score": 10,
        }
        if route_pts < 10:
            criteria["route_optimization"]["reason"] = (
                f"{route_ok}/{route_total} pickers have correct NN routes"
            )

        # ── 7. Batch summary & response (10 pts) ─────────────────────
        summ_pts = 0.0
        sp = os.path.join(self.workspace, "batch_summary.csv")
        if os.path.exists(sp):
            with open(sp) as fh:
                rdr = csv.DictReader(fh)
                s_rows = list(rdr)
                req = {
                    "picker_id", "picker_name", "num_orders", "num_items",
                    "total_weight_kg", "total_volume_liters", "num_zones",
                    "route_zones",
                }
                if req.issubset(set(rdr.fieldnames or [])):
                    summ_pts += 3
                    if {r["picker_id"] for r in s_rows} == expected_pids:
                        summ_pts += 2

        m = re.search(r"Total orders assigned:\s*(\d+)", action)
        if m and int(m.group(1)) == total_gt:
            summ_pts += 5
        summ_pts = min(round(summ_pts, 2), 10)

        criteria["batch_summary_response"] = {
            "passed": summ_pts == 10,
            "score": summ_pts,
            "max_score": 10,
        }
        if summ_pts < 10:
            criteria["batch_summary_response"]["reason"] = (
                "batch_summary.csv or response-format issue"
            )

        # ── aggregate ─────────────────────────────────────────────────
        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
        return round(total_score / max_score, 4), {
            "eval_criteria": criteria,
            "total_score": round(total_score, 2),
            "max_score": max_score,
        }

    # ── verify ────────────────────────────────────────────────────────

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
        import yaml as _yaml

        # ── 1. Read workspace reference files ─────────────────────────
        with open(os.path.join(self.workspace, "zone_map.json")) as f:
            zone_map = json.load(f)
        with open(os.path.join(self.workspace, "picking_policy.yaml")) as f:
            policy = _yaml.safe_load(f)

        certs: dict = {}
        with open(os.path.join(self.workspace, "picker_certifications.csv")) as f:
            for row in csv.DictReader(f):
                certs[row["picker_id"]] = {
                    "cold_chain": int(row["cold_chain_certified"]),
                    "hazmat": int(row["hazmat_certified"]),
                }

        special: dict = {}
        for bf in sorted(glob_module.glob(
                os.path.join(self.workspace, "order_batch_*.csv"))):
            with open(bf) as f:
                for row in csv.DictReader(f):
                    special[row["order_id"]] = row["special_handling"]

        # ── 2. Gather data via tools ──────────────────────────────────
        all_pending: list = []
        page = 1
        while True:
            res = self.tools["list_pending_orders"](page=page, page_size=20)
            all_pending.extend(res["orders"])
            if page >= res["total_pages"]:
                break
            page += 1

        oi_map: dict = {}
        for o in all_pending:
            res = self.tools["get_order_items"](order_id=o["order_id"])
            oi_map[o["order_id"]] = res["items"]

        sku_ids = {it["sku_id"] for items in oi_map.values() for it in items}
        skus: dict = {}
        for sid in sorted(sku_ids):
            skus[sid] = self.tools["get_sku_details"](sku_id=sid)

        active = self.tools["list_active_pickers"]()["pickers"]
        picker_info: dict = {}
        for p in active:
            picker_info[p["picker_id"]] = self.tools["get_picker_info"](
                picker_id=p["picker_id"])

        active_list = [picker_info[pid] for pid in sorted(picker_info)]

        # ── 3. Compute assignment ─────────────────────────────────────
        assign = self._compute_assignment(
            all_pending, oi_map, skus, active_list, certs, special, policy)

        # ── 4. Write pick-list files ──────────────────────────────────
        for pid, orders in assign.items():
            items_rows: list = []
            for order in orders:
                for it in oi_map[order["order_id"]]:
                    sku = skus[it["sku_id"]]
                    items_rows.append({
                        "order_id": order["order_id"],
                        "sku_id": it["sku_id"],
                        "sku_name": sku["sku_name"],
                        "quantity": it["quantity"],
                        "weight": round(sku["weight_kg"] * it["quantity"], 2),
                        "volume": round(sku["volume_liters"] * it["quantity"], 2),
                        "zone_id": sku["zone_id"],
                        "shelf_position": sku["shelf_position"],
                    })

            zones_needed = {r["zone_id"] for r in items_rows}
            start = picker_info[pid]["current_zone_id"]
            route = self._nearest_neighbor_route(start, zones_needed, zone_map)
            zseq = {z: i + 1 for i, z in enumerate(route)}

            csv_rows: list = []
            for r in items_rows:
                csv_rows.append({
                    "sequence": zseq.get(r["zone_id"], 999),
                    "zone_id": r["zone_id"],
                    "zone_name": zone_map[r["zone_id"]]["zone_name"],
                    "sku_id": r["sku_id"],
                    "sku_name": r["sku_name"],
                    "order_id": r["order_id"],
                    "quantity": r["quantity"],
                    "item_weight_kg": f"{r['weight']:.2f}",
                    "item_volume_liters": f"{r['volume']:.2f}",
                    "shelf_position": r["shelf_position"],
                })
            csv_rows.sort(key=lambda x: (
                x["sequence"], x["shelf_position"], x["sku_id"]))

            fpath = os.path.join(self.workspace, f"pick_list_{pid}.csv")
            with open(fpath, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=[
                    "sequence", "zone_id", "zone_name", "sku_id", "sku_name",
                    "order_id", "quantity", "item_weight_kg",
                    "item_volume_liters", "shelf_position",
                ])
                w.writeheader()
                w.writerows(csv_rows)

        # ── 5. Write batch summary ────────────────────────────────────
        summary: list = []
        for pid in sorted(assign):
            ords = assign[pid]
            items = [it for o in ords for it in oi_map[o["order_id"]]]
            tw = sum(skus[it["sku_id"]]["weight_kg"] * it["quantity"]
                     for it in items)
            tv = sum(skus[it["sku_id"]]["volume_liters"] * it["quantity"]
                     for it in items)
            tn = sum(it["quantity"] for it in items)
            zones_needed = {skus[it["sku_id"]]["zone_id"] for it in items}
            route = self._nearest_neighbor_route(
                picker_info[pid]["current_zone_id"], zones_needed, zone_map)
            summary.append({
                "picker_id": pid,
                "picker_name": picker_info[pid]["name"],
                "num_orders": len(ords),
                "num_items": tn,
                "total_weight_kg": f"{tw:.2f}",
                "total_volume_liters": f"{tv:.2f}",
                "num_zones": len(zones_needed),
                "route_zones": ";".join(route),
            })

        with open(os.path.join(self.workspace, "batch_summary.csv"),
                  "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=[
                "picker_id", "picker_name", "num_orders", "num_items",
                "total_weight_kg", "total_volume_liters", "num_zones",
                "route_zones",
            ])
            w.writeheader()
            w.writerows(summary)

        # ── 6. Final action string ────────────────────────────────────
        total_assigned = sum(len(v) for v in assign.values())
        action = (
            f"Total orders assigned: {total_assigned}. "
            "All constraints satisfied."
        )
        return self.step(action)
