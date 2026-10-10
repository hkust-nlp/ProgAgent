import os
import re
import csv
import json
import math
import sqlite3
from typing import Tuple, Dict, List, Any

import yaml
import numpy as np
import pandas as pd


# -------------------------------------------------------------------- #
# Decorator                                                             #
# -------------------------------------------------------------------- #

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# -------------------------------------------------------------------- #
# Helper utilities                                                      #
# -------------------------------------------------------------------- #

def _euclidean(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2)


def _parse_maintenance(workspace: str) -> Dict[str, set]:
    """Return {truck_id: {day_of_week, ...}}."""
    maint: Dict[str, set] = {}
    path = os.path.join(workspace, "truck_maintenance.txt")
    if not os.path.exists(path):
        return maint
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            tid = parts[0].strip()
            dow = int(parts[1].strip())
            maint.setdefault(tid, set()).add(dow)
    return maint


def _load_traffic(workspace: str) -> Dict[int, Dict[tuple, tuple]]:
    """Return {day: {(from_id, to_id): (distance_km, travel_time_min)}}."""
    traffic: Dict[int, Dict[tuple, tuple]] = {}
    traffic_dir = os.path.join(workspace, "traffic")
    if not os.path.isdir(traffic_dir):
        return traffic
    for fname in sorted(os.listdir(traffic_dir)):
        if not fname.endswith(".csv"):
            continue
        m = re.match(r"day_(\d+)_part_\d+\.csv", fname)
        if not m:
            continue
        day = int(m.group(1))
        traffic.setdefault(day, {})
        with open(os.path.join(traffic_dir, fname)) as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row["from_id"], row["to_id"])
                traffic[day][key] = (
                    float(row["distance_km"]),
                    float(row["travel_time_minutes"]),
                )
    return traffic


def _load_tiers(workspace: str) -> dict:
    path = os.path.join(workspace, "subscription_tiers.yaml")
    with open(path) as f:
        return yaml.safe_load(f)


def _load_fuel_prices(workspace: str) -> dict:
    with open(os.path.join(workspace, "fuel_prices.json")) as f:
        return json.load(f)


def _load_district_schedule(workspace: str) -> dict:
    with open(os.path.join(workspace, "district_schedule.json")) as f:
        return json.load(f)


def _parse_threshold(workspace: str) -> float:
    path = os.path.join(workspace, "collection_policy.md")
    with open(path) as f:
        text = f.read()
    m = re.search(r"equals or exceeds\s+([\d.]+)\s*\n?kilograms", text)
    if m:
        return float(m.group(1))
    return 120.0


# -------------------------------------------------------------------- #
# Shared solver – identical logic for verify (tools) and step (DB)      #
# -------------------------------------------------------------------- #

def _solve(
    areas: List[dict],
    area_day_weights: Dict[str, Dict[int, float]],
    area_has_premium: Dict[str, bool],
    trucks: List[dict],
    truck_efficiency: Dict[str, float],
    maintenance: Dict[str, set],
    district_schedule: dict,
    fuel_prices: dict,
    traffic: Dict[int, Dict[tuple, tuple]],
    threshold: float,
):
    """
    Deterministic solver.  Returns (schedule_rows, cost_report).

    schedule_rows: list of dicts with keys
        day_of_week, truck_id, stop_order, area_id, area_name, expected_weight_kg
    cost_report: dict with total_fuel_cost, total_drive_time_minutes, daily_breakdown
    """

    area_map = {a["area_id"]: a for a in areas}

    # --- 1. Classify areas ------------------------------------------------
    area_avg_weight: Dict[str, float] = {}
    for aid, day_w in area_day_weights.items():
        area_avg_weight[aid] = sum(day_w.values()) / 5.0

    high_demand = set()
    for aid in area_avg_weight:
        if area_avg_weight[aid] >= threshold:
            high_demand.add(aid)
        if area_has_premium.get(aid, False):
            high_demand.add(aid)

    # --- 2. Assign collection days ----------------------------------------
    # day -> list of area_ids
    day_areas: Dict[int, list] = {d: [] for d in range(1, 6)}
    for a in areas:
        aid = a["area_id"]
        dist = a["district"]
        sched = district_schedule.get(dist, {"primary_day": 1, "secondary_day": 4})
        day_areas[sched["primary_day"]].append(aid)
        if aid in high_demand:
            day_areas[sched["secondary_day"]].append(aid)

    # --- 3. Truck ranking (global, reused each day) -----------------------
    # Only trucks with fuel logs
    eligible_trucks = [t for t in trucks if t["truck_id"] in truck_efficiency]
    eligible_trucks.sort(
        key=lambda t: (-truck_efficiency[t["truck_id"]], t["truck_id"])
    )

    schedule_rows: list = []
    daily_breakdown: list = []

    total_fuel_cost = 0.0
    total_drive_time = 0.0

    for day in range(1, 6):
        areas_today = day_areas[day]
        if not areas_today:
            daily_breakdown.append({
                "day": day, "num_routes": 0,
                "fuel_cost": 0.0, "drive_time_minutes": 0.0,
            })
            continue

        # Available trucks (not in maintenance, have logs)
        avail = [
            t for t in eligible_trucks
            if day not in maintenance.get(t["truck_id"], set())
        ]
        if not avail:
            # Fallback – cannot schedule
            daily_breakdown.append({
                "day": day, "num_routes": 0,
                "fuel_cost": 0.0, "drive_time_minutes": 0.0,
            })
            continue

        # Area weights for today
        area_weights_today: Dict[str, float] = {}
        for aid in areas_today:
            area_weights_today[aid] = area_day_weights.get(aid, {}).get(day, 0.0)

        # Sort areas by weight desc, then area_id asc
        sorted_areas = sorted(
            areas_today, key=lambda a: (-area_weights_today[a], a)
        )

        # Greedy assignment
        remaining_cap: Dict[str, float] = {
            t["truck_id"]: float(t["capacity_kg"]) for t in avail
        }
        truck_areas: Dict[str, list] = {t["truck_id"]: [] for t in avail}
        # Build efficiency rank mapping (lower = better)
        eff_rank = {t["truck_id"]: idx for idx, t in enumerate(avail)}

        for aid in sorted_areas:
            w = area_weights_today[aid]
            # Find highest-ranked truck with enough capacity
            assigned = False
            for t in avail:
                tid = t["truck_id"]
                if remaining_cap[tid] >= w:
                    truck_areas[tid].append(aid)
                    remaining_cap[tid] -= w
                    assigned = True
                    break
            if not assigned:
                # Assign to truck with greatest remaining capacity
                best = max(
                    avail,
                    key=lambda t: (remaining_cap[t["truck_id"]],
                                   -eff_rank[t["truck_id"]]),
                )
                truck_areas[best["truck_id"]].append(aid)
                remaining_cap[best["truck_id"]] -= w

        # --- Route ordering (nearest-neighbour from depot) ----------------
        day_fuel = 0.0
        day_time = 0.0
        day_routes = 0

        for t in avail:
            tid = t["truck_id"]
            assigned = truck_areas[tid]
            if not assigned:
                continue
            day_routes += 1
            eff = truck_efficiency[tid]
            price = fuel_prices.get(t["fuel_type"], 1.0)

            # Nearest-neighbour ordering
            remaining = list(assigned)
            route_order: list = []
            cur_lat, cur_lon = 0.0, 0.0  # depot

            while remaining:
                dists = []
                for aid in remaining:
                    a = area_map[aid]
                    d = _euclidean(cur_lat, cur_lon, a["latitude"], a["longitude"])
                    dists.append((d, aid))
                dists.sort(key=lambda x: (x[0], x[1]))
                nearest_aid = dists[0][1]
                route_order.append(nearest_aid)
                a = area_map[nearest_aid]
                cur_lat, cur_lon = a["latitude"], a["longitude"]
                remaining.remove(nearest_aid)

            # Build schedule rows + compute costs
            prev_id = "DEPOT"
            prev_lat, prev_lon = 0.0, 0.0
            for stop_idx, aid in enumerate(route_order):
                a = area_map[aid]
                ew = round(area_weights_today[aid], 1)
                schedule_rows.append({
                    "day_of_week": day,
                    "truck_id": tid,
                    "stop_order": stop_idx + 1,
                    "area_id": aid,
                    "area_name": a["area_name"],
                    "expected_weight_kg": ew,
                })

                # Segment cost
                seg = traffic.get(day, {}).get((prev_id, aid))
                if seg:
                    seg_dist, seg_time = seg
                else:
                    eucl = _euclidean(prev_lat, prev_lon,
                                     a["latitude"], a["longitude"])
                    seg_dist = eucl
                    seg_time = eucl / 30.0 * 60.0

                day_fuel += seg_dist / eff * price
                day_time += seg_time

                prev_id = aid
                prev_lat, prev_lon = a["latitude"], a["longitude"]

            # Return to depot segment
            seg = traffic.get(day, {}).get((prev_id, "DEPOT"))
            if seg:
                seg_dist, seg_time = seg
            else:
                eucl = _euclidean(prev_lat, prev_lon, 0.0, 0.0)
                seg_dist = eucl
                seg_time = eucl / 30.0 * 60.0
            day_fuel += seg_dist / eff * price
            day_time += seg_time

        total_fuel_cost += day_fuel
        total_drive_time += day_time
        daily_breakdown.append({
            "day": day,
            "num_routes": day_routes,
            "fuel_cost": round(day_fuel, 2),
            "drive_time_minutes": round(day_time, 2),
        })

    cost_report = {
        "total_fuel_cost": round(total_fuel_cost, 2),
        "total_drive_time_minutes": round(total_drive_time, 2),
        "daily_breakdown": daily_breakdown,
    }
    return schedule_rows, cost_report


# -------------------------------------------------------------------- #
# Task_Env                                                              #
# -------------------------------------------------------------------- #

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

    # ================================================================ #
    # TOOLS                                                             #
    # ================================================================ #

    @tool(
        description=(
            "Lists all service areas with their identifier, name, district, "
            "latitude, and longitude."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_service_areas(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT area_id, area_name, district, latitude, longitude "
            "FROM service_areas ORDER BY area_id"
        )
        rows = cur.fetchall()
        conn.close()
        return _envelope([
            {
                "area_id": r[0],
                "area_name": r[1],
                "district": r[2],
                "latitude": r[3],
                "longitude": r[4],
            }
            for r in rows
        ])

    @tool(
        description=(
            "Returns the total expected bin weight for a given service area "
            "on each weekday (1-5) plus the average across all five days."
        ),
        parameters={
            "type": "object",
            "properties": {
                "area_id": {
                    "type": "string",
                    "description": "Service area identifier, e.g. SA001",
                },
            },
            "required": ["area_id"],
        },
    )
    def get_area_weight_summary(self, area_id: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT w.day_of_week, SUM(w.weight_kg)
            FROM weight_readings w
            JOIN bins b ON b.bin_id = w.bin_id
            WHERE b.area_id = ?
            GROUP BY w.day_of_week
            ORDER BY w.day_of_week
            """,
            (area_id,),
        )
        rows = cur.fetchall()
        conn.close()
        daily = {int(r[0]): round(r[1], 1) for r in rows}
        avg = round(sum(daily.values()) / max(len(daily), 1), 1)
        return _envelope({"area_id": area_id, "daily_weights": daily, "avg_daily_weight_kg": avg})

    @tool(
        description=(
            "Returns the list of residents in a given service area, "
            "including each resident's identifier, name, and subscription tier."
        ),
        parameters={
            "type": "object",
            "properties": {
                "area_id": {
                    "type": "string",
                    "description": "Service area identifier, e.g. SA001",
                },
            },
            "required": ["area_id"],
        },
    )
    def get_area_residents(self, area_id: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT resident_id, name, subscription_tier "
            "FROM residents WHERE area_id = ? ORDER BY resident_id",
            (area_id,),
        )
        rows = cur.fetchall()
        conn.close()
        return json.dumps([
            {"resident_id": r[0], "name": r[1], "subscription_tier": r[2]}
            for r in rows
        ], ensure_ascii=False, default=str)

    @tool(
        description=(
            "Lists all trucks with their identifier, plate number, model, "
            "weight capacity in kg, fuel type, and manufacturer-specified "
            "fuel efficiency."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_trucks(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT truck_id, plate_number, model, capacity_kg, "
            "fuel_type, fuel_efficiency_spec FROM trucks ORDER BY truck_id"
        )
        rows = cur.fetchall()
        conn.close()
        return json.dumps([
            {
                "truck_id": r[0],
                "plate_number": r[1],
                "model": r[2],
                "capacity_kg": r[3],
                "fuel_type": r[4],
                "fuel_efficiency_spec": r[5],
            }
            for r in rows
        ], ensure_ascii=False, default=str)

    @tool(
        description=(
            "Returns all fuel-log entries for a given truck, including "
            "date, distance in km, and fuel consumed in litres."
        ),
        parameters={
            "type": "object",
            "properties": {
                "truck_id": {
                    "type": "string",
                    "description": "Truck identifier, e.g. T001",
                },
            },
            "required": ["truck_id"],
        },
    )
    def get_truck_fuel_logs(self, truck_id: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT log_id, date, distance_km, fuel_consumed_liters "
            "FROM fuel_logs WHERE truck_id = ? ORDER BY date",
            (truck_id,),
        )
        rows = cur.fetchall()
        conn.close()
        return json.dumps([
            {
                "log_id": r[0],
                "date": r[1],
                "distance_km": r[2],
                "fuel_consumed_liters": r[3],
            }
            for r in rows
        ], ensure_ascii=False, default=str)

    # ================================================================ #
    # STEP – evaluation                                                 #
    # ================================================================ #

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's
        final response.
        """
        gt_schedule, gt_cost = self._ground_truth()

        criteria: Dict[str, dict] = {}
        total_score = 0
        max_score = 0

        # ---- 1. Schedule file format (10 pts) ----------------------------
        ms = 10
        max_score += ms
        sched_path = os.path.join(self.workspace, "route_schedule.csv")
        sched_ok = False
        agent_df = None
        expected_cols = [
            "day_of_week", "truck_id", "stop_order",
            "area_id", "area_name", "expected_weight_kg",
        ]
        if os.path.exists(sched_path):
            try:
                agent_df = pd.read_csv(sched_path)
                if list(agent_df.columns) == expected_cols and len(agent_df) > 0:
                    sched_ok = True
            except Exception:
                pass
        if sched_ok:
            criteria["schedule_format"] = {"passed": True, "score": ms, "max_score": ms}
            total_score += ms
        else:
            criteria["schedule_format"] = {
                "passed": False, "score": 0, "max_score": ms,
                "reason": "route_schedule.csv missing or has wrong columns",
            }

        # Build ground-truth lookup structures
        gt_df = pd.DataFrame(gt_schedule)

        # ---- 2. Complete area coverage (20 pts) --------------------------
        ms = 20
        max_score += ms
        if sched_ok and agent_df is not None:
            gt_area_days = set()
            for _, r in gt_df.iterrows():
                gt_area_days.add((r["area_id"], int(r["day_of_week"])))
            agent_area_days = set()
            for _, r in agent_df.iterrows():
                agent_area_days.add((str(r["area_id"]), int(r["day_of_week"])))
            correct = len(gt_area_days & agent_area_days)
            total_gt = len(gt_area_days)
            frac = correct / total_gt if total_gt else 0
            sc = round(ms * frac)
            criteria["area_coverage"] = {
                "passed": frac == 1.0,
                "score": sc,
                "max_score": ms,
                "reason": (
                    f"{correct}/{total_gt} area-day pairs correct"
                    if frac < 1.0 else ""
                ),
            }
            total_score += sc
        else:
            criteria["area_coverage"] = {
                "passed": False, "score": 0, "max_score": ms,
                "reason": "schedule file not loaded",
            }

        # ---- 3. Day assignments correct (15 pts) -------------------------
        ms = 15
        max_score += ms
        if sched_ok and agent_df is not None:
            # Per-area: set of days in gt vs agent
            gt_ad: Dict[str, set] = {}
            for _, r in gt_df.iterrows():
                gt_ad.setdefault(r["area_id"], set()).add(int(r["day_of_week"]))
            agent_ad: Dict[str, set] = {}
            for _, r in agent_df.iterrows():
                agent_ad.setdefault(str(r["area_id"]), set()).add(
                    int(r["day_of_week"])
                )
            correct = sum(1 for a in gt_ad if gt_ad[a] == agent_ad.get(a, set()))
            total_a = len(gt_ad)
            frac = correct / total_a if total_a else 0
            sc = round(ms * frac)
            criteria["day_assignments"] = {
                "passed": frac == 1.0,
                "score": sc,
                "max_score": ms,
                "reason": (
                    f"{correct}/{total_a} areas with correct day sets"
                    if frac < 1.0 else ""
                ),
            }
            total_score += sc
        else:
            criteria["day_assignments"] = {
                "passed": False, "score": 0, "max_score": ms,
                "reason": "schedule file not loaded",
            }

        # ---- 4. Truck constraints (15 pts) -------------------------------
        ms = 15
        max_score += ms
        if sched_ok and agent_df is not None:
            conn = sqlite3.connect(self.db_path)
            truck_cap = dict(
                conn.execute("SELECT truck_id, capacity_kg FROM trucks").fetchall()
            )
            conn.close()
            maint = _parse_maintenance(self.workspace)

            violations = 0
            total_checks = 0
            for (day, tid), grp in agent_df.groupby(["day_of_week", "truck_id"]):
                total_checks += 1
                # Capacity check
                tot_w = grp["expected_weight_kg"].sum()
                cap = truck_cap.get(str(tid), 0)
                if tot_w > cap * 1.01:  # 1% tolerance
                    violations += 1
                    continue
                # Maintenance check
                if int(day) in maint.get(str(tid), set()):
                    violations += 1
            frac = 1.0 - (violations / max(total_checks, 1))
            sc = round(ms * max(frac, 0))
            criteria["truck_constraints"] = {
                "passed": violations == 0,
                "score": sc,
                "max_score": ms,
                "reason": (
                    f"{violations} constraint violations" if violations else ""
                ),
            }
            total_score += sc
        else:
            criteria["truck_constraints"] = {
                "passed": False, "score": 0, "max_score": ms,
                "reason": "schedule file not loaded",
            }

        # ---- 5. Route ordering (10 pts) ----------------------------------
        ms = 10
        max_score += ms
        if sched_ok and agent_df is not None:
            correct_routes = 0
            total_routes = 0
            for (day, tid), grp in gt_df.groupby(["day_of_week", "truck_id"]):
                total_routes += 1
                gt_order = list(grp.sort_values("stop_order")["area_id"])
                agent_grp = agent_df[
                    (agent_df["day_of_week"] == day) &
                    (agent_df["truck_id"] == tid)
                ]
                if agent_grp.empty:
                    continue
                agent_order = list(
                    agent_grp.sort_values("stop_order")["area_id"].astype(str)
                )
                if gt_order == agent_order:
                    correct_routes += 1
            frac = correct_routes / max(total_routes, 1)
            sc = round(ms * frac)
            criteria["route_ordering"] = {
                "passed": frac == 1.0,
                "score": sc,
                "max_score": ms,
                "reason": (
                    f"{correct_routes}/{total_routes} routes in correct order"
                    if frac < 1.0 else ""
                ),
            }
            total_score += sc
        else:
            criteria["route_ordering"] = {
                "passed": False, "score": 0, "max_score": ms,
                "reason": "schedule file not loaded",
            }

        # ---- 6. Cost report accuracy (15 pts) ----------------------------
        ms = 15
        max_score += ms
        cost_path = os.path.join(self.workspace, "cost_report.json")
        if os.path.exists(cost_path):
            try:
                with open(cost_path) as f:
                    agent_cost = json.load(f)
                fc_ok = (
                    abs(agent_cost["total_fuel_cost"] - gt_cost["total_fuel_cost"])
                    <= max(0.01 * gt_cost["total_fuel_cost"], 0.01)
                )
                dt_ok = (
                    abs(agent_cost["total_drive_time_minutes"]
                        - gt_cost["total_drive_time_minutes"])
                    <= max(0.01 * gt_cost["total_drive_time_minutes"], 0.01)
                )
                bd_ok = "daily_breakdown" in agent_cost and len(
                    agent_cost["daily_breakdown"]
                ) == 5
                parts = int(fc_ok) + int(dt_ok) + int(bd_ok)
                sc = round(ms * parts / 3)
                criteria["cost_report"] = {
                    "passed": parts == 3,
                    "score": sc,
                    "max_score": ms,
                    "reason": (
                        f"fuel_cost_ok={fc_ok}, drive_time_ok={dt_ok}, "
                        f"breakdown_ok={bd_ok}"
                        if parts < 3 else ""
                    ),
                }
                total_score += sc
            except Exception as e:
                criteria["cost_report"] = {
                    "passed": False, "score": 0, "max_score": ms,
                    "reason": f"Error reading cost_report.json: {e}",
                }
        else:
            criteria["cost_report"] = {
                "passed": False, "score": 0, "max_score": ms,
                "reason": "cost_report.json not found",
            }

        # ---- 7. Response summary (15 pts) --------------------------------
        ms = 15
        max_score += ms
        fc_match = False
        dt_match = False
        if action:
            # Look for total fuel cost
            fc_pattern = re.findall(
                r"\$?([\d,]+\.\d{2})", action.replace(",", "")
            )
            for val in fc_pattern:
                try:
                    v = float(val)
                    if abs(v - gt_cost["total_fuel_cost"]) <= max(
                        0.01 * gt_cost["total_fuel_cost"], 0.01
                    ):
                        fc_match = True
                        break
                except ValueError:
                    pass
            # Look for drive time
            dt_pattern = re.findall(r"([\d]+\.?\d*)\s*minutes", action)
            for val in dt_pattern:
                try:
                    v = float(val)
                    if abs(v - gt_cost["total_drive_time_minutes"]) <= max(
                        0.01 * gt_cost["total_drive_time_minutes"], 0.01
                    ):
                        dt_match = True
                        break
                except ValueError:
                    pass
        parts = int(fc_match) + int(dt_match)
        sc = round(ms * parts / 2)
        criteria["response_summary"] = {
            "passed": parts == 2,
            "score": sc,
            "max_score": ms,
            "reason": (
                f"fuel_cost_found={fc_match}, drive_time_found={dt_match}"
                if parts < 2 else ""
            ),
        }
        total_score += sc

        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ================================================================ #
    # Ground truth computation (uses DB directly)                       #
    # ================================================================ #

    def _ground_truth(self):
        conn = sqlite3.connect(self.db_path)

        areas_raw = conn.execute(
            "SELECT area_id, area_name, district, latitude, longitude "
            "FROM service_areas ORDER BY area_id"
        ).fetchall()
        areas = [
            {
                "area_id": r[0], "area_name": r[1], "district": r[2],
                "latitude": r[3], "longitude": r[4],
            }
            for r in areas_raw
        ]

        # area_day_weights
        rows = conn.execute(
            """
            SELECT b.area_id, w.day_of_week, SUM(w.weight_kg)
            FROM weight_readings w
            JOIN bins b ON b.bin_id = w.bin_id
            GROUP BY b.area_id, w.day_of_week
            """
        ).fetchall()
        area_day_weights: Dict[str, Dict[int, float]] = {}
        for aid, dow, s in rows:
            area_day_weights.setdefault(aid, {})[int(dow)] = round(s, 1)

        # premium residents
        res_rows = conn.execute(
            "SELECT area_id, subscription_tier FROM residents"
        ).fetchall()
        area_has_premium: Dict[str, bool] = {}
        for aid, tier in res_rows:
            if tier == "premium":
                area_has_premium[aid] = True
            else:
                area_has_premium.setdefault(aid, False)

        # trucks
        truck_rows = conn.execute(
            "SELECT truck_id, plate_number, model, capacity_kg, "
            "fuel_type, fuel_efficiency_spec FROM trucks ORDER BY truck_id"
        ).fetchall()
        trucks = [
            {
                "truck_id": r[0], "plate_number": r[1], "model": r[2],
                "capacity_kg": r[3], "fuel_type": r[4],
                "fuel_efficiency_spec": r[5],
            }
            for r in truck_rows
        ]

        # truck efficiency from logs
        fl_rows = conn.execute(
            "SELECT truck_id, SUM(distance_km), SUM(fuel_consumed_liters) "
            "FROM fuel_logs GROUP BY truck_id"
        ).fetchall()
        truck_efficiency: Dict[str, float] = {}
        for tid, dist, fuel in fl_rows:
            if fuel > 0:
                truck_efficiency[tid] = dist / fuel

        conn.close()

        maintenance = _parse_maintenance(self.workspace)
        district_schedule = _load_district_schedule(self.workspace)
        fuel_prices = _load_fuel_prices(self.workspace)
        traffic = _load_traffic(self.workspace)
        threshold = _parse_threshold(self.workspace)

        return _solve(
            areas, area_day_weights, area_has_premium,
            trucks, truck_efficiency, maintenance,
            district_schedule, fuel_prices, traffic, threshold,
        )

    # ================================================================ #
    # VERIFY – prove solvability using only tools + workspace           #
    # ================================================================ #

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        # --- Gather data via tools ---
        areas = json.loads(self.tools["list_service_areas"]()["content"][0]["text"])

        area_day_weights: Dict[str, Dict[int, float]] = {}
        area_has_premium: Dict[str, bool] = {}

        for a in areas:
            aid = a["area_id"]
            ws = json.loads(self.tools["get_area_weight_summary"](area_id=aid)["content"][0]["text"])
            area_day_weights[aid] = {
                int(k): v for k, v in ws["daily_weights"].items()
            }
            residents = json.loads(self.tools["get_area_residents"](area_id=aid))
            area_has_premium[aid] = any(
                r["subscription_tier"] == "premium" for r in residents
            )

        trucks = json.loads(self.tools["list_trucks"]())
        truck_efficiency: Dict[str, float] = {}
        for t in trucks:
            logs = json.loads(self.tools["get_truck_fuel_logs"](truck_id=t["truck_id"]))
            total_dist = sum(l["distance_km"] for l in logs)
            total_fuel = sum(l["fuel_consumed_liters"] for l in logs)
            if total_fuel > 0:
                truck_efficiency[t["truck_id"]] = total_dist / total_fuel

        # --- Read workspace files ---
        maintenance = _parse_maintenance(self.workspace)
        district_schedule = _load_district_schedule(self.workspace)
        fuel_prices = _load_fuel_prices(self.workspace)
        traffic = _load_traffic(self.workspace)
        threshold = _parse_threshold(self.workspace)
        # Also read tiers config to confirm premium forces high-demand
        _load_tiers(self.workspace)

        # --- Solve ---
        schedule_rows, cost_report = _solve(
            areas, area_day_weights, area_has_premium,
            trucks, truck_efficiency, maintenance,
            district_schedule, fuel_prices, traffic, threshold,
        )

        # --- Write deliverables ---
        sched_path = os.path.join(self.workspace, "route_schedule.csv")
        cols = [
            "day_of_week", "truck_id", "stop_order",
            "area_id", "area_name", "expected_weight_kg",
        ]
        with open(sched_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(schedule_rows)

        cost_path = os.path.join(self.workspace, "cost_report.json")
        with open(cost_path, "w") as f:
            json.dump(cost_report, f, indent=2)

        # --- Construct action string ---
        action = (
            f"Total weekly fuel cost: ${cost_report['total_fuel_cost']:.2f}\n"
            f"Total weekly drive time: "
            f"{cost_report['total_drive_time_minutes']:.2f} minutes"
        )

        return self.step(action)
