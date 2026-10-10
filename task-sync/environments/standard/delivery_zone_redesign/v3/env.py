import sqlite3
import os
import json
import csv
import math
import yaml
import glob as glob_mod
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

    # ---------- Helper ----------
    def _query(self, sql, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    # ---------- Tools ----------

    @tool(
        description="List all delivery zones with their IDs and names.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_zones(self):
        return self._query("SELECT zone_id, zone_name FROM zones ORDER BY zone_id")

    @tool(
        description="Get detailed information about a specific delivery zone including boundaries and current rider quota.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {"type": "integer", "description": "The zone ID to look up."},
            },
            "required": ["zone_id"],
        },
    )
    def get_zone_details(self, zone_id: int):
        rows = self._query("SELECT * FROM zones WHERE zone_id = ?", (zone_id,))
        return rows[0] if rows else {"error": "Zone not found"}

    @tool(
        description="Get the total number of orders and average delivery time for a zone.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {"type": "integer", "description": "The zone ID."},
            },
            "required": ["zone_id"],
        },
    )
    def get_zone_order_summary(self, zone_id: int):
        rows = self._query(
            "SELECT COUNT(*) as total_orders, "
            "AVG(delivery_time_min) as avg_delivery_time, "
            "SUM(order_value) as total_order_value "
            "FROM orders WHERE zone_id = ?",
            (zone_id,),
        )
        return rows[0] if rows else {"error": "No data"}

    @tool(
        description="Get the list of riders assigned to a zone, including their tier, speed, and active status.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {"type": "integer", "description": "The zone ID."},
            },
            "required": ["zone_id"],
        },
    )
    def get_zone_riders(self, zone_id: int):
        return self._query(
            "SELECT rider_id, rider_name, avg_speed_kmh, total_deliveries, "
            "is_active, rider_tier FROM riders WHERE zone_id = ?",
            (zone_id,),
        )

    @tool(
        description="Get aggregate transit time metrics for all logged rider transits within a zone.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {"type": "integer", "description": "The zone ID."},
            },
            "required": ["zone_id"],
        },
    )
    def get_zone_transit_metrics(self, zone_id: int):
        rows = self._query(
            "SELECT COUNT(*) as total_logs, "
            "AVG(transit_time_min) as avg_transit_time, "
            "MAX(transit_time_min) as max_transit_time, "
            "MIN(transit_time_min) as min_transit_time, "
            "AVG(distance_km) as avg_distance_km "
            "FROM transit_logs WHERE zone_id = ?",
            (zone_id,),
        )
        return rows[0] if rows else {"error": "No data"}

    @tool(
        description="Get aggregate restaurant preparation time metrics for a zone.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {"type": "integer", "description": "The zone ID."},
            },
            "required": ["zone_id"],
        },
    )
    def get_zone_prep_metrics(self, zone_id: int):
        rows = self._query(
            "SELECT COUNT(*) as total_logs, "
            "AVG(prep_duration_min) as avg_prep_time, "
            "MAX(prep_duration_min) as max_prep_time, "
            "MIN(prep_duration_min) as min_prep_time "
            "FROM prep_logs WHERE zone_id = ?",
            (zone_id,),
        )
        return rows[0] if rows else {"error": "No data"}

    @tool(
        description="Get the count of active riders in a zone.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {"type": "integer", "description": "The zone ID."},
            },
            "required": ["zone_id"],
        },
    )
    def get_active_rider_count(self, zone_id: int):
        rows = self._query(
            "SELECT COUNT(*) as active_riders FROM riders "
            "WHERE zone_id = ? AND is_active = 1",
            (zone_id,),
        )
        return rows[0] if rows else {"error": "No data"}

    @tool(
        description="Get details of a specific rider by ID, including transit summary.",
        parameters={
            "type": "object",
            "properties": {
                "rider_id": {"type": "integer", "description": "The rider ID."},
            },
            "required": ["rider_id"],
        },
    )
    def get_rider_detail(self, rider_id: int):
        rider = self._query("SELECT * FROM riders WHERE rider_id = ?", (rider_id,))
        if not rider:
            return {"error": "Rider not found"}
        transit = self._query(
            "SELECT COUNT(*) as trips, AVG(transit_time_min) as avg_transit, "
            "AVG(distance_km) as avg_distance FROM transit_logs WHERE rider_id = ?",
            (rider_id,),
        )
        result = rider[0]
        result["transit_summary"] = transit[0] if transit else {}
        return result

    @tool(
        description="Get details of a specific restaurant by ID, including prep time summary.",
        parameters={
            "type": "object",
            "properties": {
                "restaurant_id": {"type": "integer", "description": "The restaurant ID."},
            },
            "required": ["restaurant_id"],
        },
    )
    def get_restaurant_detail(self, restaurant_id: int):
        rest = self._query("SELECT * FROM restaurants WHERE restaurant_id = ?", (restaurant_id,))
        if not rest:
            return {"error": "Restaurant not found"}
        prep = self._query(
            "SELECT COUNT(*) as total_preps, AVG(prep_duration_min) as avg_prep "
            "FROM prep_logs WHERE restaurant_id = ?",
            (restaurant_id,),
        )
        result = rest[0]
        result["prep_summary"] = prep[0] if prep else {}
        return result

    @tool(
        description="Get the list of restaurants in a zone.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {"type": "integer", "description": "The zone ID."},
            },
            "required": ["zone_id"],
        },
    )
    def get_zone_restaurants(self, zone_id: int):
        return self._query(
            "SELECT restaurant_id, restaurant_name, cuisine_type, avg_rating "
            "FROM restaurants WHERE zone_id = ?",
            (zone_id,),
        )

    # ---------- step ----------
    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Compute ground truth ---
        gt = self._compute_ground_truth()

        # Criterion 1: rezoning_proposal.csv exists and has correct columns (10 pts)
        c1_max = 10
        max_score += c1_max
        proposal_path = os.path.join(self.workspace, "rezoning_proposal.csv")
        expected_cols = [
            "zone_id", "zone_name", "efficiency_score", "status",
            "current_rider_quota", "new_rider_quota",
            "current_radius_km", "new_radius_km",
        ]
        if os.path.exists(proposal_path):
            try:
                with open(proposal_path, "r") as f:
                    reader = csv.DictReader(f)
                    proposal_rows = list(reader)
                    actual_cols = reader.fieldnames or []
                cols_ok = all(c in actual_cols for c in expected_cols)
                rows_ok = len(proposal_rows) == len(gt)
                if cols_ok and rows_ok:
                    eval_criteria["output_format"] = {"passed": True, "score": c1_max, "max_score": c1_max}
                    total_score += c1_max
                else:
                    reasons = []
                    if not cols_ok:
                        reasons.append(f"Missing columns: {set(expected_cols) - set(actual_cols)}")
                    if not rows_ok:
                        reasons.append(f"Expected {len(gt)} rows, got {len(proposal_rows)}")
                    eval_criteria["output_format"] = {
                        "passed": False, "score": 0, "max_score": c1_max,
                        "reason": "; ".join(reasons),
                    }
            except Exception as e:
                eval_criteria["output_format"] = {
                    "passed": False, "score": 0, "max_score": c1_max,
                    "reason": f"CSV parse error: {e}",
                }
                proposal_rows = []
        else:
            eval_criteria["output_format"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "rezoning_proposal.csv not found",
            }
            proposal_rows = []

        # Build lookup from proposal
        proposal_map = {}
        for r in proposal_rows:
            try:
                proposal_map[int(r["zone_id"])] = r
            except (KeyError, ValueError):
                pass

        # Criterion 2: Efficiency scores accurate (25 pts) — per zone, partial credit
        c2_max = 25
        max_score += c2_max
        c2_score = 0
        per_zone_pts = c2_max / len(gt)
        wrong_scores = []
        for zid, truth in gt.items():
            pr = proposal_map.get(zid)
            if pr:
                try:
                    submitted = float(pr["efficiency_score"])
                    if abs(submitted - truth["efficiency_score"]) <= 0.5:
                        c2_score += per_zone_pts
                    else:
                        wrong_scores.append(f"zone {zid}: expected {truth['efficiency_score']:.2f}, got {submitted:.2f}")
                except (ValueError, KeyError):
                    wrong_scores.append(f"zone {zid}: missing/invalid score")
        c2_score = round(c2_score, 2)
        total_score += c2_score
        eval_criteria["efficiency_scores"] = {
            "passed": c2_score >= c2_max - 0.01,
            "score": c2_score,
            "max_score": c2_max,
        }
        if wrong_scores:
            eval_criteria["efficiency_scores"]["reason"] = "; ".join(wrong_scores[:5])

        # Criterion 3: Inefficient zones correctly identified (20 pts)
        c3_max = 20
        max_score += c3_max
        gt_inefficient = {zid for zid, v in gt.items() if v["status"] == "INEFFICIENT"}
        submitted_inefficient = set()
        for zid, pr in proposal_map.items():
            if pr.get("status", "").strip().upper() == "INEFFICIENT":
                submitted_inefficient.add(zid)
        if submitted_inefficient == gt_inefficient:
            eval_criteria["inefficient_identification"] = {"passed": True, "score": c3_max, "max_score": c3_max}
            total_score += c3_max
        else:
            missed = gt_inefficient - submitted_inefficient
            extra = submitted_inefficient - gt_inefficient
            # Partial credit: per correct zone
            correct = gt_inefficient & submitted_inefficient
            efficient_correct = (set(gt.keys()) - gt_inefficient) - submitted_inefficient
            all_correct = len(correct) + len(efficient_correct)
            partial = round(c3_max * all_correct / len(gt), 2)
            total_score += partial
            eval_criteria["inefficient_identification"] = {
                "passed": False, "score": partial, "max_score": c3_max,
                "reason": f"Missed: {missed}, Extra: {extra}",
            }

        # Criterion 4: New rider quotas correct (20 pts)
        c4_max = 20
        max_score += c4_max
        c4_score = 0
        per_zone_pts4 = c4_max / len(gt)
        wrong_quotas = []
        for zid, truth in gt.items():
            pr = proposal_map.get(zid)
            if pr:
                try:
                    submitted_q = int(float(pr["new_rider_quota"]))
                    if submitted_q == truth["new_rider_quota"]:
                        c4_score += per_zone_pts4
                    else:
                        wrong_quotas.append(f"zone {zid}: expected {truth['new_rider_quota']}, got {submitted_q}")
                except (ValueError, KeyError):
                    wrong_quotas.append(f"zone {zid}: missing/invalid quota")
        c4_score = round(c4_score, 2)
        total_score += c4_score
        eval_criteria["rider_quotas"] = {
            "passed": c4_score >= c4_max - 0.01,
            "score": c4_score,
            "max_score": c4_max,
        }
        if wrong_quotas:
            eval_criteria["rider_quotas"]["reason"] = "; ".join(wrong_quotas[:5])

        # Criterion 5: New radius values correct (15 pts)
        c5_max = 15
        max_score += c5_max
        c5_score = 0
        per_zone_pts5 = c5_max / len(gt)
        wrong_radii = []
        for zid, truth in gt.items():
            pr = proposal_map.get(zid)
            if pr:
                try:
                    submitted_r = float(pr["new_radius_km"])
                    if abs(submitted_r - truth["new_radius_km"]) <= 0.01:
                        c5_score += per_zone_pts5
                    else:
                        wrong_radii.append(f"zone {zid}: expected {truth['new_radius_km']:.2f}, got {submitted_r:.2f}")
                except (ValueError, KeyError):
                    wrong_radii.append(f"zone {zid}: missing/invalid radius")
        c5_score = round(c5_score, 2)
        total_score += c5_score
        eval_criteria["zone_boundaries"] = {
            "passed": c5_score >= c5_max - 0.01,
            "score": c5_score,
            "max_score": c5_max,
        }
        if wrong_radii:
            eval_criteria["zone_boundaries"]["reason"] = "; ".join(wrong_radii[:5])

        # Criterion 6: Response contains summary stats (10 pts)
        c6_max = 10
        max_score += c6_max
        c6_score = 0
        action_upper = action.upper() if action else ""
        num_inefficient = len(gt_inefficient)
        if str(num_inefficient) in action and str(len(gt)) in action:
            c6_score += 5
        # Check that the action mentions the total rider quota change
        gt_old_total = sum(v["current_rider_quota"] for v in gt.values())
        gt_new_total = sum(v["new_rider_quota"] for v in gt.values())
        if str(gt_new_total) in action:
            c6_score += 5
        total_score += c6_score
        eval_criteria["response_summary"] = {
            "passed": c6_score >= c6_max,
            "score": c6_score,
            "max_score": c6_max,
        }
        if c6_score < c6_max:
            eval_criteria["response_summary"]["reason"] = (
                f"Expected mention of {num_inefficient} inefficient zones out of {len(gt)}, "
                f"and new total quota {gt_new_total}"
            )

        total_score = round(total_score, 2)
        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ---------- Ground-truth computation ----------
    def _haversine_km(self, lat1, lng1, lat2, lng2):
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlng / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _load_density_sectors(self):
        """Load all sector density CSV files from workspace."""
        sectors = []
        for fpath in sorted(glob_mod.glob(os.path.join(self.workspace, "sector_density_*.csv"))):
            with open(fpath, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sectors.append({
                        "lat_min": float(row["lat_min"]),
                        "lat_max": float(row["lat_max"]),
                        "lng_min": float(row["lng_min"]),
                        "lng_max": float(row["lng_max"]),
                        "residential_addresses": int(row["residential_addresses"]),
                        "commercial_addresses": int(row["commercial_addresses"]),
                        "density_per_sq_km": float(row["density_per_sq_km"]),
                    })
        return sectors

    def _compute_zone_density(self, zone, sectors):
        """Compute weighted density for a zone from overlapping sectors."""
        total_addr = 0
        weighted_density = 0.0
        for s in sectors:
            s_center_lat = (s["lat_min"] + s["lat_max"]) / 2
            s_center_lng = (s["lng_min"] + s["lng_max"]) / 2
            dist = self._haversine_km(
                s_center_lat, s_center_lng,
                zone["center_lat"], zone["center_lng"],
            )
            if dist <= zone["radius_km"]:
                addr = s["residential_addresses"] + s["commercial_addresses"]
                total_addr += addr
                weighted_density += s["density_per_sq_km"] * addr
        if total_addr == 0:
            return 0.0
        return weighted_density / total_addr

    def _load_policy(self):
        with open(os.path.join(self.workspace, "rezoning_policy.yaml"), "r") as f:
            return yaml.safe_load(f)

    def _compute_ground_truth(self):
        """Compute full ground truth for all zones."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        policy = self._load_policy()
        weights = policy["efficiency_weights"]
        rules = policy["scoring_rules"]
        cutoff = policy["efficiency_cutoff"]
        adj = policy["adjustment_rules"]

        sectors = self._load_density_sectors()

        # Get zone info
        cur.execute("SELECT * FROM zones ORDER BY zone_id")
        zones = [dict(r) for r in cur.fetchall()]

        # Compute per-zone density
        zone_densities = {}
        for z in zones:
            zone_densities[z["zone_id"]] = self._compute_zone_density(z, sectors)

        city_avg_density = sum(zone_densities.values()) / len(zone_densities) if zone_densities else 1.0
        if city_avg_density == 0:
            city_avg_density = 1.0

        gt = {}
        for z in zones:
            zid = z["zone_id"]

            # Order stats
            cur.execute("SELECT COUNT(*) as cnt FROM orders WHERE zone_id = ?", (zid,))
            order_count = cur.fetchone()["cnt"]

            # Active rider count
            cur.execute("SELECT COUNT(*) as cnt FROM riders WHERE zone_id = ? AND is_active = 1", (zid,))
            active_riders = cur.fetchone()["cnt"]

            # Transit metrics
            cur.execute("SELECT AVG(transit_time_min) as avg_tt FROM transit_logs WHERE zone_id = ?", (zid,))
            row = cur.fetchone()
            avg_transit = row["avg_tt"] if row["avg_tt"] is not None else 0.0

            # Prep metrics
            cur.execute("SELECT AVG(prep_duration_min) as avg_pt FROM prep_logs WHERE zone_id = ?", (zid,))
            row = cur.fetchone()
            avg_prep = row["avg_pt"] if row["avg_pt"] is not None else 0.0

            # Orders per active rider
            orders_per_rider = order_count / active_riders if active_riders > 0 else 0

            # Component scores (each 0-100)
            transit_baseline = rules["transit_baseline_min"]
            prep_baseline = rules["prep_baseline_min"]
            target_ratio = rules["target_orders_per_rider"]
            transit_penalty_rate = rules["transit_penalty_per_min"]
            prep_penalty_rate = rules["prep_penalty_per_min"]
            ratio_penalty_rate = rules["ratio_penalty_per_unit"]

            transit_score = max(0, 100 - max(0, avg_transit - transit_baseline) * transit_penalty_rate)
            prep_score = max(0, 100 - max(0, avg_prep - prep_baseline) * prep_penalty_rate)
            ratio_score = max(0, 100 - abs(orders_per_rider - target_ratio) * ratio_penalty_rate)

            zone_density = zone_densities[zid]
            density_score = min(100, (zone_density / city_avg_density) * 100) if city_avg_density > 0 else 50

            efficiency_score = round(
                weights["transit_time"] * transit_score +
                weights["prep_time"] * prep_score +
                weights["order_rider_ratio"] * ratio_score +
                weights["density_utilization"] * density_score,
                2,
            )

            status = "INEFFICIENT" if efficiency_score < cutoff else "EFFICIENT"

            # New rider quota
            density_factor = zone_density / city_avg_density if city_avg_density > 0 else 1.0
            if status == "INEFFICIENT":
                raw_quota = order_count * density_factor / target_ratio
                new_quota = max(1, math.ceil(raw_quota))
                new_radius = round(
                    max(adj["min_radius_km"],
                        min(adj["max_radius_km"],
                            z["radius_km"] * adj["radius_shrink_factor"])),
                    2,
                )
            else:
                new_quota = z["current_rider_quota"]
                new_radius = z["radius_km"]

            gt[zid] = {
                "zone_id": zid,
                "zone_name": z["zone_name"],
                "efficiency_score": efficiency_score,
                "status": status,
                "current_rider_quota": z["current_rider_quota"],
                "new_rider_quota": new_quota,
                "current_radius_km": z["radius_km"],
                "new_radius_km": new_radius,
            }

        conn.close()
        return gt

    # ---------- verify ----------
    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as csv_mod
        import json as json_mod
        import yaml as yaml_mod
        import math as math_mod
        import glob as g

        # 1. Read policy
        with open(os.path.join(self.workspace, "rezoning_policy.yaml"), "r") as f:
            policy = yaml_mod.safe_load(f)
        weights = policy["efficiency_weights"]
        rules = policy["scoring_rules"]
        cutoff = policy["efficiency_cutoff"]
        adj = policy["adjustment_rules"]

        # 2. Read zone boundaries
        with open(os.path.join(self.workspace, "zone_boundaries.json"), "r") as f:
            zone_boundaries = json_mod.load(f)

        # 3. Read all sector density files
        sector_files = sorted(g.glob(os.path.join(self.workspace, "sector_density_*.csv")))
        all_sectors = []
        for sf in sector_files:
            with open(sf, "r") as f:
                reader = csv_mod.DictReader(f)
                for row in reader:
                    all_sectors.append(row)

        # Helper: haversine
        def hav(lat1, lng1, lat2, lng2):
            R = 6371.0
            dlat = math_mod.radians(lat2 - lat1)
            dlng = math_mod.radians(lng2 - lng1)
            a = (math_mod.sin(dlat / 2) ** 2 +
                 math_mod.cos(math_mod.radians(lat1)) * math_mod.cos(math_mod.radians(lat2)) *
                 math_mod.sin(dlng / 2) ** 2)
            return R * 2 * math_mod.atan2(math_mod.sqrt(a), math_mod.sqrt(1 - a))

        # 4. Compute zone densities from sector files
        def compute_density(center_lat, center_lng, radius_km):
            total_addr = 0
            weighted_d = 0.0
            for s in all_sectors:
                slat = (float(s["lat_min"]) + float(s["lat_max"])) / 2
                slng = (float(s["lng_min"]) + float(s["lng_max"])) / 2
                dist = hav(slat, slng, center_lat, center_lng)
                if dist <= radius_km:
                    addr = int(s["residential_addresses"]) + int(s["commercial_addresses"])
                    total_addr += addr
                    weighted_d += float(s["density_per_sq_km"]) * addr
            return weighted_d / total_addr if total_addr > 0 else 0.0

        # 5. Use tools to gather zone data
        zones_list = self.tools["list_zones"]()  # call 1

        zone_data = {}
        for z in zones_list:
            zid = z["zone_id"]
            details = self.tools["get_zone_details"](zone_id=zid)  # calls 2-11
            order_summary = self.tools["get_zone_order_summary"](zone_id=zid)  # calls 12-21
            riders = self.tools["get_zone_riders"](zone_id=zid)  # calls 22-31
            transit = self.tools["get_zone_transit_metrics"](zone_id=zid)  # calls 32-41
            prep = self.tools["get_zone_prep_metrics"](zone_id=zid)  # calls 42-51
            active_count = self.tools["get_active_rider_count"](zone_id=zid)  # calls 52-61

            zone_data[zid] = {
                "details": details,
                "order_summary": order_summary,
                "riders": riders,
                "transit": transit,
                "prep": prep,
                "active_riders": active_count["active_riders"],
            }

        # 6. Compute zone densities from workspace files and zone boundaries
        zone_densities = {}
        for zid_str, zb in zone_boundaries.items():
            zid = int(zid_str)
            zone_densities[zid] = compute_density(
                zb["center_lat"], zb["center_lng"], zb["radius_km"]
            )

        city_avg_density = sum(zone_densities.values()) / len(zone_densities) if zone_densities else 1.0
        if city_avg_density == 0:
            city_avg_density = 1.0

        # 7. Compute efficiency scores
        results = {}
        for z in zones_list:
            zid = z["zone_id"]
            zd = zone_data[zid]
            zb_info = zone_boundaries[str(zid)]

            order_count = zd["order_summary"]["total_orders"]
            active_riders = zd["active_riders"]
            avg_transit = zd["transit"]["avg_transit_time"] or 0.0
            avg_prep = zd["prep"]["avg_prep_time"] or 0.0
            orders_per_rider = order_count / active_riders if active_riders > 0 else 0

            transit_baseline = rules["transit_baseline_min"]
            prep_baseline = rules["prep_baseline_min"]
            target_ratio = rules["target_orders_per_rider"]
            transit_penalty_rate = rules["transit_penalty_per_min"]
            prep_penalty_rate = rules["prep_penalty_per_min"]
            ratio_penalty_rate = rules["ratio_penalty_per_unit"]

            transit_score = max(0, 100 - max(0, avg_transit - transit_baseline) * transit_penalty_rate)
            prep_score = max(0, 100 - max(0, avg_prep - prep_baseline) * prep_penalty_rate)
            ratio_score = max(0, 100 - abs(orders_per_rider - target_ratio) * ratio_penalty_rate)
            zone_density = zone_densities.get(zid, 0)
            density_score = min(100, (zone_density / city_avg_density) * 100) if city_avg_density > 0 else 50

            efficiency_score = round(
                weights["transit_time"] * transit_score +
                weights["prep_time"] * prep_score +
                weights["order_rider_ratio"] * ratio_score +
                weights["density_utilization"] * density_score,
                2,
            )

            status = "INEFFICIENT" if efficiency_score < cutoff else "EFFICIENT"

            density_factor = zone_density / city_avg_density if city_avg_density > 0 else 1.0
            if status == "INEFFICIENT":
                raw_quota = order_count * density_factor / target_ratio
                new_quota = max(1, math_mod.ceil(raw_quota))
                new_radius = round(
                    max(adj["min_radius_km"],
                        min(adj["max_radius_km"],
                            zb_info["radius_km"] * adj["radius_shrink_factor"])),
                    2,
                )
            else:
                new_quota = zb_info["current_rider_quota"]
                new_radius = zb_info["radius_km"]

            results[zid] = {
                "zone_id": zid,
                "zone_name": z["zone_name"],
                "efficiency_score": efficiency_score,
                "status": status,
                "current_rider_quota": zb_info["current_rider_quota"],
                "new_rider_quota": new_quota,
                "current_radius_km": zb_info["radius_km"],
                "new_radius_km": new_radius,
            }

        # 8. Write rezoning_proposal.csv
        fieldnames = [
            "zone_id", "zone_name", "efficiency_score", "status",
            "current_rider_quota", "new_rider_quota",
            "current_radius_km", "new_radius_km",
        ]
        proposal_path = os.path.join(self.workspace, "rezoning_proposal.csv")
        with open(proposal_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for zid in sorted(results.keys()):
                writer.writerow(results[zid])

        # 9. Build action summary
        num_zones = len(results)
        inefficient = [r for r in results.values() if r["status"] == "INEFFICIENT"]
        num_inefficient = len(inefficient)
        old_total_quota = sum(r["current_rider_quota"] for r in results.values())
        new_total_quota = sum(r["new_rider_quota"] for r in results.values())

        action = (
            f"Re-zoning analysis complete. Analyzed {num_zones} delivery zones. "
            f"Identified {num_inefficient} inefficient zones: "
            + ", ".join(f"{r['zone_name']} (zone {r['zone_id']}, score {r['efficiency_score']})"
                        for r in sorted(inefficient, key=lambda x: x["zone_id"]))
            + f". Total rider quota adjusted from {old_total_quota} to {new_total_quota}. "
            f"Detailed proposal saved to rezoning_proposal.csv."
        )

        return self.step(action)
