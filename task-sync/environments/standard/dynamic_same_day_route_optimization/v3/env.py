import sqlite3
import os
import json
import csv
import re
import glob
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

    # ── Helper ──────────────────────────────────────────────────────────────

    def _query(self, sql, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    # ── Tools ───────────────────────────────────────────────────────────────

    @tool(
        description=(
            "Returns a high-level summary of each delivery zone: the zone id, "
            "zone name, count of pending orders whose delivery zone matches, "
            "and count of available couriers currently in that zone."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    def get_zone_summary(self):
        zones_raw = self._query(
            "SELECT DISTINCT zone_id FROM couriers "
            "UNION SELECT DISTINCT delivery_zone_id FROM orders"
        )
        zone_ids = sorted(set(r["zone_id"] for r in zones_raw))
        # zone names from the workspace config
        znames = {}
        zfile = os.path.join(self.workspace, "zone_definitions.json")
        if os.path.exists(zfile):
            with open(zfile) as f:
                zdata = json.load(f)
            for z in zdata.get("zones", []):
                znames[z["zone_id"]] = z["name"]
        result = []
        for zid in zone_ids:
            pending = self._query(
                "SELECT COUNT(*) AS cnt FROM orders "
                "WHERE delivery_zone_id=? AND status='pending'", (zid,)
            )[0]["cnt"]
            avail = self._query(
                "SELECT COUNT(*) AS cnt FROM couriers "
                "WHERE zone_id=? AND status='available'", (zid,)
            )[0]["cnt"]
            result.append({
                "zone_id": zid,
                "zone_name": znames.get(zid, f"Zone {zid}"),
                "pending_orders": pending,
                "available_couriers": avail,
            })
        return result

    @tool(
        description=(
            "Returns all couriers with status 'available' in the given zone. "
            "Each record includes courier_id, name, vehicle_type, capacity_kg, "
            "max_parcels, current_lat, current_lng, zone_id, current_load_kg, "
            "current_parcels, and shift_end."
        ),
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "integer",
                    "description": "The zone to query for available couriers."
                }
            },
            "required": ["zone_id"]
        }
    )
    def get_available_couriers(self, zone_id: int):
        return self._query(
            "SELECT courier_id, name, vehicle_type, capacity_kg, max_parcels, "
            "current_lat, current_lng, zone_id, current_load_kg, current_parcels, "
            "shift_end FROM couriers WHERE zone_id=? AND status='available'",
            (zone_id,)
        )

    @tool(
        description=(
            "Returns paginated pending orders whose delivery zone matches the "
            "given zone_id. Each record includes order_id, customer_id, "
            "pickup_zone_id, delivery_zone_id, weight_kg, parcel_count, "
            "order_placed, window_start, window_end, priority, and status. "
            "The response also contains page, page_size, total_orders, and "
            "total_pages for pagination."
        ),
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "integer",
                    "description": "Delivery zone to filter pending orders."
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1."
                },
                "page_size": {
                    "type": "integer",
                    "description": "Orders per page. Default 20."
                }
            },
            "required": ["zone_id"]
        }
    )
    def get_pending_orders(self, zone_id: int, page: int = 1, page_size: int = 20):
        total = self._query(
            "SELECT COUNT(*) AS cnt FROM orders "
            "WHERE delivery_zone_id=? AND status='pending'", (zone_id,)
        )[0]["cnt"]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        orders = self._query(
            "SELECT order_id, customer_id, pickup_zone_id, delivery_zone_id, "
            "weight_kg, parcel_count, order_placed, window_start, window_end, "
            "priority, status FROM orders "
            "WHERE delivery_zone_id=? AND status='pending' "
            "ORDER BY order_id LIMIT ? OFFSET ?",
            (zone_id, page_size, offset)
        )
        return {
            "orders": orders,
            "page": page,
            "page_size": page_size,
            "total_orders": total,
            "total_pages": total_pages,
        }

    @tool(
        description=(
            "Returns full details for a single order by order_id, including "
            "order_id, customer_id, pickup_zone_id, delivery_zone_id, weight_kg, "
            "parcel_count, order_placed, window_start, window_end, priority, status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "integer",
                    "description": "The order identifier."
                }
            },
            "required": ["order_id"]
        }
    )
    def get_order_details(self, order_id: int):
        rows = self._query("SELECT * FROM orders WHERE order_id=?", (order_id,))
        return rows[0] if rows else {"error": f"Order {order_id} not found"}

    @tool(
        description=(
            "Returns customer information for the given customer_id: "
            "customer_id, name, tier, zone_id, phone, address."
        ),
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "integer",
                    "description": "The customer identifier."
                }
            },
            "required": ["customer_id"]
        }
    )
    def get_customer_info(self, customer_id: int):
        rows = self._query("SELECT * FROM customers WHERE customer_id=?", (customer_id,))
        return rows[0] if rows else {"error": f"Customer {customer_id} not found"}

    @tool(
        description=(
            "Returns the best (fastest) traffic estimate between two zones. "
            "The response includes from_zone_id, to_zone_id, route_name, "
            "distance_km, base_time_min, congestion_factor, and "
            "estimated_time_min (base_time_min * congestion_factor for the "
            "fastest available route)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "from_zone_id": {
                    "type": "integer",
                    "description": "Origin zone identifier."
                },
                "to_zone_id": {
                    "type": "integer",
                    "description": "Destination zone identifier."
                }
            },
            "required": ["from_zone_id", "to_zone_id"]
        }
    )
    def get_traffic_estimate(self, from_zone_id: int, to_zone_id: int):
        rows = self._query(
            "SELECT *, ROUND(base_time_min * congestion_factor, 2) AS estimated_time_min "
            "FROM traffic_segments "
            "WHERE from_zone_id=? AND to_zone_id=? "
            "ORDER BY base_time_min * congestion_factor ASC LIMIT 1",
            (from_zone_id, to_zone_id)
        )
        if not rows:
            return {"error": f"No traffic data for {from_zone_id}->{to_zone_id}"}
        r = rows[0]
        return {
            "from_zone_id": r["from_zone_id"],
            "to_zone_id": r["to_zone_id"],
            "route_name": r["route_name"],
            "distance_km": r["distance_km"],
            "base_time_min": r["base_time_min"],
            "congestion_factor": r["congestion_factor"],
            "estimated_time_min": r["estimated_time_min"],
        }

    @tool(
        description=(
            "Returns the current load and remaining capacity for a courier: "
            "courier_id, vehicle_type, capacity_kg, max_parcels, "
            "current_load_kg, current_parcels, remaining_capacity_kg, "
            "remaining_parcels."
        ),
        parameters={
            "type": "object",
            "properties": {
                "courier_id": {
                    "type": "integer",
                    "description": "The courier identifier."
                }
            },
            "required": ["courier_id"]
        }
    )
    def check_courier_capacity(self, courier_id: int):
        rows = self._query(
            "SELECT courier_id, vehicle_type, capacity_kg, max_parcels, "
            "current_load_kg, current_parcels FROM couriers WHERE courier_id=?",
            (courier_id,)
        )
        if not rows:
            return {"error": f"Courier {courier_id} not found"}
        r = rows[0]
        return {
            "courier_id": r["courier_id"],
            "vehicle_type": r["vehicle_type"],
            "capacity_kg": r["capacity_kg"],
            "max_parcels": r["max_parcels"],
            "current_load_kg": r["current_load_kg"],
            "current_parcels": r["current_parcels"],
            "remaining_capacity_kg": round(r["capacity_kg"] - r["current_load_kg"], 1),
            "remaining_parcels": r["max_parcels"] - r["current_parcels"],
        }

    # ── Evaluation ──────────────────────────────────────────────────────────

    def _load_handling_map(self):
        """Read all order_handling_batch CSVs → {order_id: handling_code}."""
        hmap = {}
        for path in sorted(glob.glob(os.path.join(self.workspace, "order_handling_batch_*.csv"))):
            with open(path, newline="") as f:
                for row in csv.DictReader(f):
                    hmap[int(row["order_id"])] = row["handling_code"]
        return hmap

    def _load_vehicle_compat(self):
        with open(os.path.join(self.workspace, "vehicle_compatibility.yaml")) as f:
            data = yaml.safe_load(f)
        return data["vehicle_compatibility"], data["vehicle_specs"]

    def _load_sla_matrix(self):
        sla = {}
        with open(os.path.join(self.workspace, "sla_thresholds.csv"), newline="") as f:
            for row in csv.DictReader(f):
                sla[(row["tier"], row["priority"])] = int(row["max_delivery_minutes"])
        return sla

    def _load_zone_config(self):
        with open(os.path.join(self.workspace, "zone_definitions.json")) as f:
            return json.load(f)

    def _best_traffic_time(self, from_zone, to_zone):
        """Return fastest estimated_time_min between two zones (direct DB)."""
        rows = self._query(
            "SELECT MIN(base_time_min * congestion_factor) AS best "
            "FROM traffic_segments WHERE from_zone_id=? AND to_zone_id=?",
            (from_zone, to_zone)
        )
        if rows and rows[0]["best"] is not None:
            return round(rows[0]["best"], 2)
        return None

    def _compute_delivery_time(self, courier_zone, delivery_zone, speed_factor, penalty):
        traffic_time = self._best_traffic_time(courier_zone, delivery_zone)
        if traffic_time is None:
            return None
        p = penalty if courier_zone != delivery_zone else 0
        return round(traffic_time / speed_factor + p, 1)

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
        criteria = {}

        # ── Load ground truth data ──────────────────────────────────────────
        handling_map = self._load_handling_map()
        compat, vspecs = self._load_vehicle_compat()
        sla_matrix = self._load_sla_matrix()
        zone_config = self._load_zone_config()
        penalty = zone_config.get("cross_zone_penalty_minutes", 5)

        # Pending orders from DB
        pending = self._query("SELECT * FROM orders WHERE status='pending'")
        pending_ids = {o["order_id"] for o in pending}

        # Available couriers from DB (keyed by id)
        avail = self._query("SELECT * FROM couriers WHERE status='available'")
        courier_map = {c["courier_id"]: c for c in avail}

        # Customer tiers
        cust_rows = self._query("SELECT customer_id, tier FROM customers")
        cust_tier = {r["customer_id"]: r["tier"] for r in cust_rows}

        # ── 1. Manifest format ──────────────────────────────────────────────
        manifest_path = os.path.join(self.workspace, "assignment_manifest.csv")
        expected_cols = [
            "courier_id", "courier_name", "order_id", "delivery_zone_id",
            "estimated_delivery_min", "priority", "handling_code", "sla_deadline_min",
        ]
        manifest_rows = []
        fmt_ok = False
        try:
            with open(manifest_path, newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and list(reader.fieldnames) == expected_cols:
                    fmt_ok = True
                for row in reader:
                    manifest_rows.append(row)
        except Exception:
            pass

        criteria["manifest_format"] = {
            "passed": fmt_ok and len(manifest_rows) > 0,
            "score": 10 if (fmt_ok and len(manifest_rows) > 0) else 0,
            "max_score": 10,
        }
        if not criteria["manifest_format"]["passed"]:
            criteria["manifest_format"]["reason"] = (
                "Manifest missing, empty, or has wrong columns. "
                f"Expected columns: {expected_cols}"
            )

        # ── Parse manifest rows ─────────────────────────────────────────────
        parsed = []
        for row in manifest_rows:
            try:
                parsed.append({
                    "courier_id": int(row["courier_id"]),
                    "courier_name": row["courier_name"],
                    "order_id": int(row["order_id"]),
                    "delivery_zone_id": int(row["delivery_zone_id"]),
                    "estimated_delivery_min": float(row["estimated_delivery_min"]),
                    "priority": row["priority"],
                    "handling_code": row["handling_code"],
                    "sla_deadline_min": float(row["sla_deadline_min"]),
                })
            except (ValueError, KeyError):
                continue

        # ── 2. Order completeness ───────────────────────────────────────────
        manifest_order_ids = {r["order_id"] for r in parsed}
        present = manifest_order_ids & pending_ids
        dup_count = len(parsed) - len(manifest_order_ids)
        completeness = len(present) / len(pending_ids) if pending_ids else 1.0
        no_dups = dup_count == 0
        comp_score = round(20 * completeness) if no_dups else round(20 * completeness * 0.5)

        criteria["order_completeness"] = {
            "passed": completeness == 1.0 and no_dups,
            "score": comp_score,
            "max_score": 20,
        }
        if not criteria["order_completeness"]["passed"]:
            missing = pending_ids - manifest_order_ids
            criteria["order_completeness"]["reason"] = (
                f"Missing {len(missing)} pending orders; {dup_count} duplicate(s)."
            )

        # ── 3. Vehicle compatibility ────────────────────────────────────────
        compat_ok = 0
        compat_total = 0
        for r in parsed:
            if r["courier_id"] == -1:
                continue
            compat_total += 1
            cid = r["courier_id"]
            hcode = r["handling_code"]
            if cid in courier_map:
                vtype = courier_map[cid]["vehicle_type"]
                if hcode in compat.get(vtype, []):
                    compat_ok += 1

        compat_frac = compat_ok / compat_total if compat_total else 1.0
        criteria["vehicle_compatibility"] = {
            "passed": compat_frac == 1.0,
            "score": round(20 * compat_frac),
            "max_score": 20,
        }
        if not criteria["vehicle_compatibility"]["passed"]:
            criteria["vehicle_compatibility"]["reason"] = (
                f"{compat_total - compat_ok} of {compat_total} assignment(s) violate vehicle-handling compatibility."
            )

        # ── 4. Capacity constraints ─────────────────────────────────────────
        # Sum assigned weight/parcels per courier
        assigned_weight = {}
        assigned_parcels = {}
        for r in parsed:
            cid = r["courier_id"]
            if cid == -1:
                continue
            oid = r["order_id"]
            order_row = self._query("SELECT weight_kg, parcel_count FROM orders WHERE order_id=?", (oid,))
            if order_row:
                assigned_weight[cid] = assigned_weight.get(cid, 0) + order_row[0]["weight_kg"]
                assigned_parcels[cid] = assigned_parcels.get(cid, 0) + order_row[0]["parcel_count"]

        cap_violations = 0
        for cid, w in assigned_weight.items():
            if cid not in courier_map:
                cap_violations += 1
                continue
            c = courier_map[cid]
            if w + c["current_load_kg"] > c["capacity_kg"] + 0.01:
                cap_violations += 1
            if assigned_parcels.get(cid, 0) + c["current_parcels"] > c["max_parcels"]:
                cap_violations += 1

        criteria["capacity_constraints"] = {
            "passed": cap_violations == 0,
            "score": 15 if cap_violations == 0 else max(0, 15 - cap_violations * 3),
            "max_score": 15,
        }
        if not criteria["capacity_constraints"]["passed"]:
            criteria["capacity_constraints"]["reason"] = (
                f"{cap_violations} capacity violation(s) detected."
            )

        # ── 5. SLA compliance ───────────────────────────────────────────────
        sla_ok = 0
        sla_total = 0
        sla_deadline_correct = 0
        for r in parsed:
            oid = r["order_id"]
            if r["courier_id"] == -1:
                # check that sla_deadline is correct even for unassigned
                order_row = self._query("SELECT customer_id, priority FROM orders WHERE order_id=?", (oid,))
                if order_row:
                    tier = cust_tier.get(order_row[0]["customer_id"], "bronze")
                    expected_sla = sla_matrix.get((tier, order_row[0]["priority"]), 240)
                    if abs(r["sla_deadline_min"] - expected_sla) < 0.01:
                        sla_deadline_correct += 1
                sla_total += 1
                sla_ok += 1  # unassigned orders don't count as SLA failures
                continue

            sla_total += 1
            order_row = self._query("SELECT customer_id, priority FROM orders WHERE order_id=?", (oid,))
            if not order_row:
                continue
            tier = cust_tier.get(order_row[0]["customer_id"], "bronze")
            expected_sla = sla_matrix.get((tier, order_row[0]["priority"]), 240)
            if abs(r["sla_deadline_min"] - expected_sla) < 0.01:
                sla_deadline_correct += 1
            if r["estimated_delivery_min"] <= expected_sla + 0.01:
                sla_ok += 1

        sla_frac = sla_ok / sla_total if sla_total else 1.0
        deadline_frac = sla_deadline_correct / len(parsed) if parsed else 1.0
        sla_score = round(15 * (0.5 * sla_frac + 0.5 * deadline_frac))

        criteria["sla_compliance"] = {
            "passed": sla_frac == 1.0 and deadline_frac == 1.0,
            "score": sla_score,
            "max_score": 15,
        }
        if not criteria["sla_compliance"]["passed"]:
            criteria["sla_compliance"]["reason"] = (
                f"SLA time compliance: {sla_ok}/{sla_total}; "
                f"SLA deadline values correct: {sla_deadline_correct}/{len(parsed)}."
            )

        # ── 6. Summary statistics ───────────────────────────────────────────
        # Ground truth from manifest
        assigned_rows = [r for r in parsed if r["courier_id"] != -1]
        gt_assigned = len(assigned_rows)
        gt_couriers = len(set(r["courier_id"] for r in assigned_rows))
        gt_unassigned = len(parsed) - gt_assigned
        gt_avg_time = (
            round(sum(r["estimated_delivery_min"] for r in assigned_rows) / gt_assigned, 1)
            if gt_assigned else 0.0
        )

        stat_score = 0
        stat_max = 20

        def _find_number(pattern, text):
            m = re.search(pattern, text, re.IGNORECASE)
            return float(m.group(1)) if m else None

        v_assigned = _find_number(r"(?:total\s+)?orders?\s+(?:that\s+were\s+)?(?:successfully\s+)?assigned[^\d\n]*?(\d+)", action)
        if v_assigned is None:
            v_assigned = _find_number(r"assigned[^\d\n]*?(\d+)", action)
        v_couriers = _find_number(r"(?:distinct\s+)?couriers?\s+utilized[^\d\n]*?(\d+)", action)
        if v_couriers is None:
            v_couriers = _find_number(r"utilized[^\d\n]*?(\d+)", action)
        v_unassigned = _find_number(r"unassigned[^\d\n]*?(\d+)", action)
        v_avg = _find_number(r"average\s+(?:estimated\s+)?delivery\s+time[^\d\n]*?([\d.]+)", action)

        checks = {
            "total_assigned": (v_assigned, gt_assigned),
            "couriers_utilized": (v_couriers, gt_couriers),
            "unassigned_orders": (v_unassigned, gt_unassigned),
            "avg_delivery_time": (v_avg, gt_avg_time),
        }
        detail_parts = []
        for k, (got, expected) in checks.items():
            if got is not None and abs(got - expected) < 0.15:
                stat_score += 5
                detail_parts.append(f"{k}: correct")
            else:
                detail_parts.append(f"{k}: expected {expected}, got {got}")

        criteria["summary_statistics"] = {
            "passed": stat_score == stat_max,
            "score": stat_score,
            "max_score": stat_max,
        }
        if not criteria["summary_statistics"]["passed"]:
            criteria["summary_statistics"]["reason"] = "; ".join(detail_parts)

        # ── Aggregate ───────────────────────────────────────────────────────
        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score if max_score else 0.0, info

    # ── Verify ──────────────────────────────────────────────────────────────

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
        # 1. Read workspace config files
        with open(os.path.join(self.workspace, "zone_definitions.json")) as f:
            zone_config = json.load(f)
        zones = zone_config["zones"]
        adjacency = {int(k): v for k, v in zone_config["adjacency"].items()}
        cross_zone_penalty = zone_config["cross_zone_penalty_minutes"]

        with open(os.path.join(self.workspace, "vehicle_compatibility.yaml")) as f:
            vc = yaml.safe_load(f)
        vehicle_compat = vc["vehicle_compatibility"]
        vehicle_specs = vc["vehicle_specs"]

        sla = {}
        with open(os.path.join(self.workspace, "sla_thresholds.csv"), newline="") as f:
            for row in csv.DictReader(f):
                sla[(row["tier"], row["priority"])] = int(row["max_delivery_minutes"])

        # Read dispatch policy (acknowledge it)
        with open(os.path.join(self.workspace, "dispatch_policy.md")) as f:
            _ = f.read()

        # Read handling code batch files
        handling_map = {}
        for path in sorted(glob.glob(os.path.join(self.workspace, "order_handling_batch_*.csv"))):
            with open(path, newline="") as f:
                for row in csv.DictReader(f):
                    handling_map[int(row["order_id"])] = row["handling_code"]

        # 2. Tool calls – zone summary
        zone_summary = self.tools["get_zone_summary"]()

        # 3. Get available couriers per zone
        all_couriers = []
        for z in zones:
            couriers = self.tools["get_available_couriers"](zone_id=z["zone_id"])
            all_couriers.extend(couriers)

        # Build courier lookup and remaining capacity tracker
        courier_lookup = {c["courier_id"]: dict(c) for c in all_couriers}
        remaining_kg = {
            c["courier_id"]: c["capacity_kg"] - c["current_load_kg"]
            for c in all_couriers
        }
        remaining_p = {
            c["courier_id"]: c["max_parcels"] - c["current_parcels"]
            for c in all_couriers
        }

        # 4. Get all pending orders per zone (with pagination)
        all_pending = []
        for z in zones:
            page = 1
            while True:
                result = self.tools["get_pending_orders"](
                    zone_id=z["zone_id"], page=page, page_size=20
                )
                all_pending.extend(result["orders"])
                if page >= result["total_pages"]:
                    break
                page += 1

        # 5. Get customer tier for each unique customer
        customer_ids = set(o["customer_id"] for o in all_pending)
        cust_info = {}
        for cid in sorted(customer_ids):
            cust_info[cid] = self.tools["get_customer_info"](customer_id=cid)

        # 6. Get traffic estimates for relevant zone pairs
        zone_ids_set = set(z["zone_id"] for z in zones)
        traffic_cache = {}
        courier_zones = set(c["zone_id"] for c in all_couriers)
        delivery_zones = set(o["delivery_zone_id"] for o in all_pending)
        for fz in courier_zones:
            for tz in delivery_zones:
                if (fz, tz) not in traffic_cache:
                    traffic_cache[(fz, tz)] = self.tools["get_traffic_estimate"](
                        from_zone_id=fz, to_zone_id=tz
                    )

        # 7. Sort orders by priority (urgent > high > standard > low), then window_start, then order_id
        priority_rank = {"urgent": 0, "high": 1, "standard": 2, "low": 3}
        all_pending.sort(key=lambda o: (
            priority_rank.get(o["priority"], 9),
            o["window_start"],
            o["order_id"],
        ))

        # 8. Greedy assignment
        assignments = []

        for order in all_pending:
            oid = order["order_id"]
            dzone = order["delivery_zone_id"]
            hcode = handling_map.get(oid, "STANDARD")
            cid_customer = order["customer_id"]
            tier = cust_info[cid_customer]["tier"]
            prio = order["priority"]
            sla_deadline = sla.get((tier, prio), 240)

            # Find compatible couriers
            candidates = []
            for cid, c in courier_lookup.items():
                vtype = c["vehicle_type"]
                if hcode not in vehicle_compat.get(vtype, []):
                    continue
                if remaining_kg.get(cid, 0) < order["weight_kg"] - 0.01:
                    continue
                if remaining_p.get(cid, 0) < order["parcel_count"]:
                    continue
                candidates.append(cid)

            if not candidates:
                assignments.append({
                    "courier_id": -1,
                    "courier_name": "UNASSIGNED",
                    "order_id": oid,
                    "delivery_zone_id": dzone,
                    "estimated_delivery_min": -1.0,
                    "priority": prio,
                    "handling_code": hcode,
                    "sla_deadline_min": float(sla_deadline),
                })
                continue

            # Preference: same zone > adjacent zone > other
            def zone_pref(cid):
                cz = courier_lookup[cid]["zone_id"]
                if cz == dzone:
                    return 0
                if dzone in adjacency.get(cz, []):
                    return 1
                return 2

            # Among same preference tier, pick courier with most remaining weight
            candidates.sort(key=lambda cid: (zone_pref(cid), -remaining_kg.get(cid, 0)))
            best_cid = candidates[0]
            best_c = courier_lookup[best_cid]

            # Compute estimated delivery time
            tdata = traffic_cache.get((best_c["zone_id"], dzone))
            if tdata and "estimated_time_min" in tdata:
                speed = vehicle_specs[best_c["vehicle_type"]]["speed_factor"]
                p = cross_zone_penalty if best_c["zone_id"] != dzone else 0
                est_min = round(tdata["estimated_time_min"] / speed + p, 1)
            else:
                est_min = -1.0

            assignments.append({
                "courier_id": best_cid,
                "courier_name": best_c["name"],
                "order_id": oid,
                "delivery_zone_id": dzone,
                "estimated_delivery_min": est_min,
                "priority": prio,
                "handling_code": hcode,
                "sla_deadline_min": float(sla_deadline),
            })

            # Update remaining capacity
            remaining_kg[best_cid] -= order["weight_kg"]
            remaining_p[best_cid] -= order["parcel_count"]

        # 9. Sort manifest by priority rank then order_id (output format)
        assignments.sort(key=lambda a: (priority_rank.get(a["priority"], 9), a["order_id"]))

        # 10. Write manifest CSV
        manifest_path = os.path.join(self.workspace, "assignment_manifest.csv")
        fieldnames = [
            "courier_id", "courier_name", "order_id", "delivery_zone_id",
            "estimated_delivery_min", "priority", "handling_code", "sla_deadline_min",
        ]
        with open(manifest_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for a in assignments:
                writer.writerow(a)

        # 11. Compute summary statistics
        assigned_rows = [a for a in assignments if a["courier_id"] != -1]
        total_assigned = len(assigned_rows)
        couriers_used = len(set(a["courier_id"] for a in assigned_rows))
        unassigned_count = len(assignments) - total_assigned
        avg_time = (
            round(sum(a["estimated_delivery_min"] for a in assigned_rows) / total_assigned, 1)
            if total_assigned else 0.0
        )

        action = (
            f"Total orders assigned: {total_assigned}\n"
            f"Couriers utilized: {couriers_used}\n"
            f"Unassigned orders: {unassigned_count}\n"
            f"Average estimated delivery time: {avg_time} minutes"
        )

        return self.step(action)
