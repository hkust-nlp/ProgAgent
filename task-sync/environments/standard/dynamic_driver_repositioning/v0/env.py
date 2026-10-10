#!/usr/bin/env python3
"""Environment for driver dispatch optimization task."""

import sqlite3
import os
import re
import json
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

    # ═══════════════════════════════════════════════
    # Tool methods
    # ═══════════════════════════════════════════════

    @tool(
        description="Retrieves pending ride requests, paginated. Returns a page of ride requests that are currently waiting for driver assignment.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Defaults to 10.",
                },
            },
            "required": ["page"],
        },
    )
    def get_pending_requests(self, page: int, page_size: int = 10) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM ride_requests WHERE status='pending' ORDER BY request_id"
        )
        all_rows = [dict(r) for r in c.fetchall()]
        conn.close()

        total = len(all_rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = all_rows[start:end]
        return {
            "requests": page_rows,
            "page": page,
            "page_size": page_size,
            "total_pending": total,
            "has_more": end < total,
        }

    @tool(
        description="Retrieves full details for a single driver by their ID.",
        parameters={
            "type": "object",
            "properties": {
                "driver_id": {
                    "type": "string",
                    "description": "The driver identifier (e.g. D0001).",
                },
            },
            "required": ["driver_id"],
        },
    )
    def get_driver_info(self, driver_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM drivers WHERE driver_id=?", (driver_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Driver {driver_id} not found."}

    @tool(
        description="Searches for drivers matching optional filters. Returns a list of matching drivers with their basic dispatch-relevant attributes.",
        parameters={
            "type": "object",
            "properties": {
                "zone": {
                    "type": "string",
                    "description": "Filter by current zone (e.g. Z01). Optional.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status (available, en_route, busy, offline). Optional.",
                },
            },
            "required": [],
        },
    )
    def search_drivers(self, zone: str = None, status: str = None) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        query = "SELECT driver_id, current_zone, status, vehicle_type, driver_rating FROM drivers WHERE 1=1"
        params = []
        if zone:
            query += " AND current_zone=?"
            params.append(zone)
        if status:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY driver_id"
        c.execute(query, params)
        results = [dict(r) for r in c.fetchall()]
        conn.close()
        return results

    @tool(
        description="Retrieves historical demand data for a specific zone at a given hour of day.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "string",
                    "description": "Zone identifier (e.g. Z01).",
                },
                "hour": {
                    "type": "integer",
                    "description": "Hour of day (0-23).",
                },
            },
            "required": ["zone_id", "hour"],
        },
    )
    def get_zone_demand(self, zone_id: str, hour: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM demand_heatmap WHERE zone_id=? AND hour=?",
            (zone_id, hour),
        )
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {
            "zone_id": zone_id,
            "hour": hour,
            "avg_requests": 0,
            "peak_requests": 0,
            "avg_wait_time_min": 0,
            "note": "No historical data for this zone/hour.",
        }

    @tool(
        description="Retrieves current traffic information between two zones. Returns estimated travel time in minutes and congestion data.",
        parameters={
            "type": "object",
            "properties": {
                "from_zone": {
                    "type": "string",
                    "description": "Origin zone identifier.",
                },
                "to_zone": {
                    "type": "string",
                    "description": "Destination zone identifier.",
                },
            },
            "required": ["from_zone", "to_zone"],
        },
    )
    def get_traffic_info(self, from_zone: str, to_zone: str) -> dict:
        if from_zone == to_zone:
            return {
                "error": "Same-zone queries not supported. Refer to dispatch policy for same-zone pickup estimates.",
            }
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM traffic_flow WHERE from_zone=? AND to_zone=?",
            (from_zone, to_zone),
        )
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {
            "from_zone": from_zone,
            "to_zone": to_zone,
            "current_travel_min": 20.0,
            "normal_travel_min": 15.0,
            "congestion_factor": 1.33,
            "note": "No direct data available - default estimate used.",
        }

    @tool(
        description="Returns the list of all zone identifiers in the system.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def get_all_zones(self) -> list:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT DISTINCT zone_id FROM demand_heatmap ORDER BY zone_id")
        zones = [row[0] for row in c.fetchall()]
        conn.close()
        return zones

    # ═══════════════════════════════════════════════
    # Internal helpers
    # ═══════════════════════════════════════════════

    def _parse_workspace(self):
        """Parse all workspace files and return structured data."""
        import yaml
        import pandas as pd

        ws = self.workspace

        # Policy
        with open(os.path.join(ws, "dispatch_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        # Zone categories
        with open(os.path.join(ws, "zone_categories.json")) as f:
            zone_cats = json.load(f)

        # Vehicle rules
        with open(os.path.join(ws, "vehicle_rules.yaml")) as f:
            vehicle_rules = yaml.safe_load(f)

        # Surge factors from MD reports
        surge_factors = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("zone_demand_report_") and fname.endswith(".md"):
                content = open(os.path.join(ws, fname)).read()
                in_table = False
                for line in content.split("\n"):
                    line = line.strip()
                    if "| Zone |" in line:
                        in_table = True
                        continue
                    if in_table and "---" in line:
                        continue
                    if in_table and line.startswith("|"):
                        parts = [p.strip() for p in line.split("|") if p.strip()]
                        if len(parts) >= 3:
                            zone_id = parts[0]
                            sf = float(parts[2])
                            surge_factors[zone_id] = sf
                    elif in_table and not line.startswith("|"):
                        in_table = False

        # Closures from traffic bulletins
        closures = set()
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("traffic_bulletin_") and fname.endswith(".txt"):
                content = open(os.path.join(ws, fname)).read()
                for m in re.finditer(
                    r"from Zone (Z\d+) to Zone (Z\d+) is currently CLOSED", content
                ):
                    closures.add((m.group(1), m.group(2)))

        # Overtime from driver shift CSVs
        overtime_drivers = set()
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("driver_shift_") and fname.endswith(".csv"):
                df = pd.read_csv(os.path.join(ws, fname))
                for _, row in df.iterrows():
                    if int(row["overtime_flag"]) == 1:
                        overtime_drivers.add(str(row["driver_id"]))

        # Forecasts from JSONs
        forecasts = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("demand_forecast_") and fname.endswith(".json"):
                with open(os.path.join(ws, fname)) as f:
                    data = json.load(f)
                for zone_id, info in data["zones"].items():
                    forecasts[zone_id] = info["predicted_requests"]

        return {
            "policy": policy,
            "zone_cats": zone_cats,
            "vehicle_rules": vehicle_rules,
            "surge_factors": surge_factors,
            "closures": closures,
            "overtime_drivers": overtime_drivers,
            "forecasts": forecasts,
        }

    def _get_db_data(self):
        """Read all needed data directly from the database."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT * FROM ride_requests WHERE status='pending' ORDER BY request_id")
        pending = [dict(r) for r in c.fetchall()]

        c.execute("SELECT * FROM drivers WHERE status='available' ORDER BY driver_id")
        available = [dict(r) for r in c.fetchall()]

        c.execute("SELECT DISTINCT zone_id FROM demand_heatmap ORDER BY zone_id")
        all_zones = [r[0] for r in c.fetchall()]

        conn.close()
        return pending, available, all_zones

    def _get_zone_demand_db(self, zone_id, hour):
        """Get demand data directly from DB."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT avg_requests FROM demand_heatmap WHERE zone_id=? AND hour=?",
            (zone_id, hour),
        )
        row = c.fetchone()
        conn.close()
        if row:
            return row["avg_requests"]
        return 0

    def _get_traffic_db(self, from_zone, to_zone, default_travel):
        """Get traffic time directly from DB."""
        if from_zone == to_zone:
            return None  # caller should use same_zone_pickup_min
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT current_travel_min FROM traffic_flow WHERE from_zone=? AND to_zone=?",
            (from_zone, to_zone),
        )
        row = c.fetchone()
        conn.close()
        if row:
            return row["current_travel_min"]
        return default_travel

    def _solve(self, pending, available, all_zones, zone_base_demand, traffic_func,
               policy, zone_cats, vehicle_rules, surge_factors, closures,
               overtime_drivers, forecasts):
        """
        Pure dispatch algorithm. Given all data, computes dispatch list and
        repositioning plan. Returns (dispatch_list, reposition_list).
        """
        weights = policy["weights"]
        max_tol_cap = policy["normalization"]["max_wait_tolerance_cap"]
        same_zone_time = policy["thresholds"]["same_zone_pickup_min"]
        default_travel = policy["thresholds"]["default_travel_min"]
        closure_penalty = policy["thresholds"]["closure_penalty_factor"]
        p_dp = policy["output"]["priority_decimal_places"]
        t_dp = policy["output"]["time_decimal_places"]
        vehicle_matching = vehicle_rules["vehicle_matching"]
        min_ratings = vehicle_rules["minimum_driver_rating"]
        oversupply_ratio = policy["thresholds"]["oversupply_ratio"]

        # Compute adjusted demand per zone
        adjusted_demand = {}
        for z in all_zones:
            base = zone_base_demand.get(z, 0)
            sf = surge_factors.get(z, 1.0)
            adjusted_demand[z] = round(base * sf, 1)

        # Normalisation denominators
        pickup_zones_demand = [
            adjusted_demand.get(r["pickup_zone"], 0) for r in pending
        ]
        max_adj = max(pickup_zones_demand) if pickup_zones_demand else 1
        if max_adj == 0:
            max_adj = 1

        max_priority_mult = max(
            (zone_cats[z]["priority_multiplier"] for z in zone_cats), default=1
        )
        if max_priority_mult == 0:
            max_priority_mult = 1

        # Priority scores
        for req in pending:
            z = req["pickup_zone"]
            demand_norm = adjusted_demand.get(z, 0) / max_adj
            urgency_norm = max(0.0, min(1.0, (max_tol_cap - req["wait_tolerance_min"]) / max_tol_cap))
            zone_mult = zone_cats.get(z, {}).get("priority_multiplier", 1.0)
            zone_norm = zone_mult / max_priority_mult
            pr_norm = req["passenger_rating"] / 5.0

            score = (
                weights["demand"] * demand_norm
                + weights["urgency"] * urgency_norm
                + weights["zone_priority"] * zone_norm
                + weights["passenger_rating"] * pr_norm
            )
            req["priority_score"] = round(score, p_dp)

        # Sort: priority desc, request_id asc
        pending.sort(key=lambda r: (-r["priority_score"], r["request_id"]))

        # Greedy assignment
        assigned_ids = set()
        dispatch_list = []

        for req in pending:
            ride_type = req["ride_type"]
            allowed_vehicles = vehicle_matching.get(ride_type, ["sedan", "suv", "van"])
            min_rating = min_ratings.get(ride_type, 3.5)

            candidates = []
            for d in available:
                did = d["driver_id"]
                if did in assigned_ids:
                    continue
                if did in overtime_drivers:
                    continue
                if d["vehicle_type"] not in allowed_vehicles:
                    continue
                if d["driver_rating"] < min_rating:
                    continue

                from_z = d["current_zone"]
                to_z = req["pickup_zone"]
                if from_z == to_z:
                    travel = float(same_zone_time)
                else:
                    travel = traffic_func(from_z, to_z)
                    if travel is None:
                        travel = float(default_travel)
                    if (from_z, to_z) in closures:
                        travel = travel * closure_penalty
                travel = round(travel, t_dp)
                candidates.append((d, travel))

            if not candidates:
                continue

            # Best: min travel, higher rating, lower driver_id
            candidates.sort(
                key=lambda x: (x[1], -x[0]["driver_rating"], x[0]["driver_id"])
            )
            best_driver, best_time = candidates[0]

            dispatch_list.append({
                "request_id": req["request_id"],
                "assigned_driver_id": best_driver["driver_id"],
                "priority_score": req["priority_score"],
                "estimated_pickup_min": best_time,
            })
            assigned_ids.add(best_driver["driver_id"])

        # Number dispatch orders
        for i, item in enumerate(dispatch_list):
            item["dispatch_order"] = i + 1

        # ── Repositioning ──
        remaining = [
            d for d in available
            if d["driver_id"] not in assigned_ids
            and d["driver_id"] not in overtime_drivers
        ]
        remaining.sort(key=lambda d: d["driver_id"])

        zone_supply = {}
        for d in remaining:
            zone_supply[d["current_zone"]] = zone_supply.get(d["current_zone"], 0) + 1

        reposition_list = []
        for d in remaining:
            z = d["current_zone"]
            supply = zone_supply.get(z, 0)
            demand = max(forecasts.get(z, 1), 1)
            ratio = supply / demand

            if ratio > oversupply_ratio:
                # Find target: highest deficit, tiebreak zone_id asc
                best_target = None
                best_deficit = -1

                for tz in sorted(all_zones):
                    if tz == z:
                        continue
                    tz_supply = zone_supply.get(tz, 0)
                    tz_demand = forecasts.get(tz, 1)
                    deficit = tz_demand - tz_supply
                    if deficit > 0 and deficit > best_deficit:
                        best_deficit = deficit
                        best_target = tz

                if best_target:
                    travel = traffic_func(z, best_target)
                    if travel is None:
                        travel = float(default_travel)
                    if (z, best_target) in closures:
                        travel = travel * closure_penalty
                    travel = round(travel, t_dp)

                    reposition_list.append({
                        "driver_id": d["driver_id"],
                        "current_zone": z,
                        "target_zone": best_target,
                        "reason": f"Oversupplied zone {z} (ratio {ratio:.1f}) to high-demand zone {best_target}",
                        "estimated_travel_min": travel,
                    })
                    zone_supply[z] = zone_supply.get(z, 0) - 1
                    zone_supply[best_target] = zone_supply.get(best_target, 0) + 1

        return dispatch_list, reposition_list

    def _compute_ground_truth(self):
        """Compute the full ground-truth solution using DB + workspace."""
        ws_data = self._parse_workspace()
        pending, available, all_zones = self._get_db_data()
        policy = ws_data["policy"]
        current_hour = policy["normalization"]["current_hour"]
        default_travel = policy["thresholds"]["default_travel_min"]

        # Build zone base demand map
        zone_base_demand = {}
        for z in all_zones:
            zone_base_demand[z] = self._get_zone_demand_db(z, current_hour)

        # Traffic lookup function (direct DB)
        def traffic_func(fz, tz):
            return self._get_traffic_db(fz, tz, default_travel)

        dispatch_list, reposition_list = self._solve(
            pending, available, all_zones, zone_base_demand, traffic_func,
            policy, ws_data["zone_cats"], ws_data["vehicle_rules"],
            ws_data["surge_factors"], ws_data["closures"],
            ws_data["overtime_drivers"], ws_data["forecasts"],
        )
        return dispatch_list, reposition_list, pending

    # ═══════════════════════════════════════════════
    # step
    # ═══════════════════════════════════════════════

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        import pandas as pd

        gt_dispatch, gt_reposition, gt_pending = self._compute_ground_truth()

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── 1. dispatch_priority.csv format (10 pts) ──
        dispatch_path = os.path.join(self.workspace, "dispatch_priority.csv")
        expected_cols = ["request_id", "assigned_driver_id", "priority_score",
                         "estimated_pickup_min", "dispatch_order"]
        crit1 = {"max_score": 10, "score": 0, "passed": False}
        agent_dispatch = None
        if os.path.exists(dispatch_path):
            try:
                agent_dispatch = pd.read_csv(dispatch_path)
                if list(agent_dispatch.columns) == expected_cols:
                    crit1["passed"] = True
                    crit1["score"] = 10
                else:
                    crit1["reason"] = f"Expected columns {expected_cols}, got {list(agent_dispatch.columns)}"
            except Exception as e:
                crit1["reason"] = f"Could not parse CSV: {e}"
        else:
            crit1["reason"] = "dispatch_priority.csv not found in workspace."
        eval_criteria["dispatch_file_format"] = crit1

        # ── 2. dispatch coverage (15 pts) ──
        crit2 = {"max_score": 15, "score": 0, "passed": False}
        if agent_dispatch is not None and crit1["passed"]:
            gt_req_ids = set(d["request_id"] for d in gt_dispatch)
            agent_req_ids = set(agent_dispatch["request_id"].astype(str))
            if gt_req_ids == agent_req_ids:
                crit2["passed"] = True
                crit2["score"] = 15
            else:
                missing = gt_req_ids - agent_req_ids
                extra = agent_req_ids - gt_req_ids
                crit2["reason"] = f"Missing {len(missing)} requests, {len(extra)} extra."
        else:
            crit2["reason"] = "dispatch_priority.csv not available or malformed."
        eval_criteria["dispatch_coverage"] = crit2

        # ── 3. priority scores (20 pts) ──
        crit3 = {"max_score": 20, "score": 0, "passed": False}
        if agent_dispatch is not None and crit1["passed"]:
            gt_scores = {d["request_id"]: d["priority_score"] for d in gt_dispatch}
            correct = 0
            total = len(gt_scores)
            for _, row in agent_dispatch.iterrows():
                rid = str(row["request_id"])
                if rid in gt_scores:
                    try:
                        agent_score = float(row["priority_score"])
                        if abs(agent_score - gt_scores[rid]) <= 0.01:
                            correct += 1
                    except (ValueError, TypeError):
                        pass
            if total > 0:
                ratio = correct / total
                crit3["score"] = round(20 * ratio)
                crit3["passed"] = ratio >= 0.95
                if not crit3["passed"]:
                    crit3["reason"] = f"{correct}/{total} scores matched."
            else:
                crit3["passed"] = True
                crit3["score"] = 20
        else:
            crit3["reason"] = "dispatch_priority.csv not available or malformed."
        eval_criteria["priority_scores"] = crit3

        # ── 4. driver eligibility (15 pts) ──
        crit4 = {"max_score": 15, "score": 0, "passed": False}
        if agent_dispatch is not None and crit1["passed"]:
            gt_assignments = {
                d["request_id"]: d["assigned_driver_id"] for d in gt_dispatch
            }
            correct = 0
            total = len(gt_assignments)
            for _, row in agent_dispatch.iterrows():
                rid = str(row["request_id"])
                if rid in gt_assignments:
                    if str(row["assigned_driver_id"]) == gt_assignments[rid]:
                        correct += 1
            if total > 0:
                ratio = correct / total
                crit4["score"] = round(15 * ratio)
                crit4["passed"] = ratio >= 0.90
                if not crit4["passed"]:
                    crit4["reason"] = f"{correct}/{total} driver assignments matched."
            else:
                crit4["passed"] = True
                crit4["score"] = 15
        else:
            crit4["reason"] = "dispatch_priority.csv not available or malformed."
        eval_criteria["driver_eligibility"] = crit4

        # ── 5. estimated pickup times (15 pts) ──
        crit5 = {"max_score": 15, "score": 0, "passed": False}
        if agent_dispatch is not None and crit1["passed"]:
            gt_times = {
                d["request_id"]: d["estimated_pickup_min"] for d in gt_dispatch
            }
            correct = 0
            total = len(gt_times)
            for _, row in agent_dispatch.iterrows():
                rid = str(row["request_id"])
                if rid in gt_times:
                    try:
                        agent_time = float(row["estimated_pickup_min"])
                        if abs(agent_time - gt_times[rid]) <= 0.5:
                            correct += 1
                    except (ValueError, TypeError):
                        pass
            if total > 0:
                ratio = correct / total
                crit5["score"] = round(15 * ratio)
                crit5["passed"] = ratio >= 0.90
                if not crit5["passed"]:
                    crit5["reason"] = f"{correct}/{total} pickup times matched."
            else:
                crit5["passed"] = True
                crit5["score"] = 15
        else:
            crit5["reason"] = "dispatch_priority.csv not available or malformed."
        eval_criteria["pickup_times"] = crit5

        # ── 6. repositioning plan (15 pts) ──
        repo_path = os.path.join(self.workspace, "repositioning_plan.csv")
        expected_repo_cols = ["driver_id", "current_zone", "target_zone",
                              "reason", "estimated_travel_min"]
        crit6 = {"max_score": 15, "score": 0, "passed": False}
        if os.path.exists(repo_path):
            try:
                agent_repo = pd.read_csv(repo_path)
                if list(agent_repo.columns) == expected_repo_cols:
                    gt_repo_drivers = {d["driver_id"]: d for d in gt_reposition}
                    agent_repo_drivers = set(agent_repo["driver_id"].astype(str))
                    gt_repo_ids = set(gt_repo_drivers.keys())

                    # Both empty → perfect
                    if len(gt_repo_ids) == 0 and len(agent_repo_drivers) == 0:
                        crit6["score"] = 15
                        crit6["passed"] = True
                    elif len(gt_repo_ids) == 0:
                        crit6["score"] = 8  # file exists with right cols but has extra rows
                        crit6["passed"] = False
                        crit6["reason"] = "Expected empty repositioning plan."
                    else:
                        total_gt = len(gt_repo_ids)
                        id_match = len(gt_repo_ids & agent_repo_drivers)
                        target_match = 0
                        for _, row in agent_repo.iterrows():
                            did = str(row["driver_id"])
                            if did in gt_repo_drivers:
                                if str(row["target_zone"]) == gt_repo_drivers[did]["target_zone"]:
                                    target_match += 1
                        id_ratio = id_match / total_gt
                        target_ratio = target_match / total_gt
                        combined = (id_ratio + target_ratio) / 2
                        crit6["score"] = round(15 * combined)
                        crit6["passed"] = combined >= 0.80
                        if not crit6["passed"]:
                            crit6["reason"] = f"Driver match: {id_match}/{total_gt}, target match: {target_match}/{total_gt}"
                else:
                    crit6["reason"] = f"Expected columns {expected_repo_cols}, got {list(agent_repo.columns)}"
            except Exception as e:
                crit6["reason"] = f"Could not parse CSV: {e}"
        else:
            crit6["reason"] = "repositioning_plan.csv not found in workspace."
        eval_criteria["repositioning_plan"] = crit6

        # ── 7. response summary (10 pts) ──
        crit7 = {"max_score": 10, "score": 0, "passed": False}
        match = re.search(
            r"SUMMARY:\s*(\d+)\s*pending,\s*(\d+)\s*dispatched,\s*([\d.]+)\s*avg pickup min,\s*(\d+)\s*repositioned",
            action,
        )
        if match:
            gt_pending_count = len(gt_pending)
            gt_dispatched = len(gt_dispatch)
            if gt_dispatched > 0:
                gt_avg = round(
                    sum(d["estimated_pickup_min"] for d in gt_dispatch) / gt_dispatched, 1
                )
            else:
                gt_avg = 0.0
            gt_repositioned = len(gt_reposition)

            checks = 0
            if int(match.group(1)) == gt_pending_count:
                checks += 1
            if int(match.group(2)) == gt_dispatched:
                checks += 1
            if abs(float(match.group(3)) - gt_avg) <= 0.2:
                checks += 1
            if int(match.group(4)) == gt_repositioned:
                checks += 1

            crit7["score"] = round(10 * checks / 4)
            crit7["passed"] = checks == 4
            if not crit7["passed"]:
                crit7["reason"] = (
                    f"Expected {gt_pending_count} pending, {gt_dispatched} dispatched, "
                    f"{gt_avg} avg, {gt_repositioned} repositioned. "
                    f"Got {match.group(1)}, {match.group(2)}, {match.group(3)}, {match.group(4)}."
                )
        else:
            crit7["reason"] = "SUMMARY line not found or malformed in response."
        eval_criteria["response_summary"] = crit7

        # ── Aggregate ──
        for c_name, c_val in eval_criteria.items():
            total_score += c_val["score"]
            max_score += c_val["max_score"]

        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ═══════════════════════════════════════════════
    # verify
    # ═══════════════════════════════════════════════

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml
        import pandas as pd

        ws = self.workspace

        # ── 1. Read workspace files ──
        with open(os.path.join(ws, "dispatch_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(ws, "zone_categories.json")) as f:
            zone_cats = json.load(f)
        with open(os.path.join(ws, "vehicle_rules.yaml")) as f:
            vehicle_rules = yaml.safe_load(f)

        # Surge factors
        surge_factors = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("zone_demand_report_") and fname.endswith(".md"):
                content = open(os.path.join(ws, fname)).read()
                in_table = False
                for line in content.split("\n"):
                    line = line.strip()
                    if "| Zone |" in line:
                        in_table = True
                        continue
                    if in_table and "---" in line:
                        continue
                    if in_table and line.startswith("|"):
                        parts = [p.strip() for p in line.split("|") if p.strip()]
                        if len(parts) >= 3:
                            surge_factors[parts[0]] = float(parts[2])
                    elif in_table and not line.startswith("|"):
                        in_table = False

        # Closures
        closures = set()
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("traffic_bulletin_") and fname.endswith(".txt"):
                content = open(os.path.join(ws, fname)).read()
                for m in re.finditer(
                    r"from Zone (Z\d+) to Zone (Z\d+) is currently CLOSED", content
                ):
                    closures.add((m.group(1), m.group(2)))

        # Overtime
        overtime_drivers = set()
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("driver_shift_") and fname.endswith(".csv"):
                df = pd.read_csv(os.path.join(ws, fname))
                for _, row in df.iterrows():
                    if int(row["overtime_flag"]) == 1:
                        overtime_drivers.add(str(row["driver_id"]))

        # Forecasts
        forecasts = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("demand_forecast_") and fname.endswith(".json"):
                with open(os.path.join(ws, fname)) as f:
                    data = json.load(f)
                for zone_id, info in data["zones"].items():
                    forecasts[zone_id] = info["predicted_requests"]

        # ── 2. Use tools to gather data ──
        tool_calls = 0

        # Get all zones
        all_zones = self.tools["get_all_zones"]()
        tool_calls += 1

        # Get pending requests (paginated)
        pending = []
        page = 1
        while True:
            result = self.tools["get_pending_requests"](page=page, page_size=10)
            tool_calls += 1
            pending.extend(result["requests"])
            if not result["has_more"]:
                break
            page += 1

        # Get available drivers
        available = self.tools["search_drivers"](status="available")
        tool_calls += 1

        # Get zone demand for all zones at current hour
        current_hour = policy["normalization"]["current_hour"]
        default_travel = policy["thresholds"]["default_travel_min"]
        zone_base_demand = {}
        for z in all_zones:
            result = self.tools["get_zone_demand"](zone_id=z, hour=current_hour)
            tool_calls += 1
            zone_base_demand[z] = result.get("avg_requests", 0)

        # Traffic cache
        traffic_cache = {}

        def traffic_func(fz, tz):
            nonlocal tool_calls
            if fz == tz:
                return None
            if (fz, tz) not in traffic_cache:
                result = self.tools["get_traffic_info"](from_zone=fz, to_zone=tz)
                tool_calls += 1
                traffic_cache[(fz, tz)] = result.get("current_travel_min", default_travel)
            return traffic_cache[(fz, tz)]

        # ── 3. Solve ──
        dispatch_list, reposition_list = self._solve(
            pending, available, all_zones, zone_base_demand, traffic_func,
            policy, zone_cats, vehicle_rules, surge_factors, closures,
            overtime_drivers, forecasts,
        )

        # ── 4. Write deliverables ──
        dispatch_df = pd.DataFrame(dispatch_list)[
            ["request_id", "assigned_driver_id", "priority_score",
             "estimated_pickup_min", "dispatch_order"]
        ] if dispatch_list else pd.DataFrame(
            columns=["request_id", "assigned_driver_id", "priority_score",
                      "estimated_pickup_min", "dispatch_order"]
        )
        dispatch_df.to_csv(os.path.join(ws, "dispatch_priority.csv"), index=False)

        repo_df = pd.DataFrame(reposition_list)[
            ["driver_id", "current_zone", "target_zone", "reason",
             "estimated_travel_min"]
        ] if reposition_list else pd.DataFrame(
            columns=["driver_id", "current_zone", "target_zone", "reason",
                      "estimated_travel_min"]
        )
        repo_df.to_csv(os.path.join(ws, "repositioning_plan.csv"), index=False)

        # ── 5. Construct action ──
        n_pending = len(pending)
        n_dispatched = len(dispatch_list)
        if n_dispatched > 0:
            avg_pickup = round(
                sum(d["estimated_pickup_min"] for d in dispatch_list) / n_dispatched, 1
            )
        else:
            avg_pickup = 0.0
        n_repositioned = len(reposition_list)

        action = (
            f"Dispatch optimization complete. "
            f"Processed all pending ride requests and generated assignment and "
            f"repositioning plans.\n\n"
            f"SUMMARY: {n_pending} pending, {n_dispatched} dispatched, "
            f"{avg_pickup} avg pickup min, {n_repositioned} repositioned"
        )

        return self.step(action)
