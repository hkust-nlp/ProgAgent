"""
Delivery Zone Optimization - Task Environment

Provides tools for querying the delivery logistics database, evaluation
logic (step), and a self-verification routine (verify).
"""
import os
import re
import sqlite3
import json
import csv
import math
from typing import Tuple, Dict, List, Any

import yaml
import pandas as pd


# ─── Decorator ────────────────────────────────────────────────────────────────

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ─── Helper constants ─────────────────────────────────────────────────────────
SHIFT_ORDER = {"morning": 0, "afternoon": 1, "evening": 2}
CERT_RANK = {"basic": 0, "advanced": 1, "expert": 2}


# ─── Task Environment ────────────────────────────────────────────────────────

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

    # ── Tool methods ──────────────────────────────────────────────────────

    @tool(
        description="List delivery zones with their names and regions. Returns a paginated result.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed. Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def list_zones(self, page: int = 1, page_size: int = 20) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM zones")
        total = cur.fetchone()[0]
        pages = math.ceil(total / page_size)
        offset = (max(1, page) - 1) * page_size
        cur.execute(
            "SELECT zone_id, zone_name, region FROM zones ORDER BY zone_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "zones": [
                {"zone_id": r[0], "zone_name": r[1], "region": r[2]} for r in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": pages,
        }

    @tool(
        description=(
            "Get a summary of package demand for a specific zone on a given date. "
            "Returns total count, total weight, and breakdowns by priority and delivery window."
        ),
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "string",
                    "description": "The zone identifier, e.g. 'Z001'.",
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format, e.g. '2026-04-21'.",
                },
            },
            "required": ["zone_id", "date"],
        },
    )
    def get_zone_package_summary(self, zone_id: str, date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT weight_kg, priority, delivery_window FROM packages "
            "WHERE zone_id = ? AND created_date = ?",
            (zone_id, date),
        )
        rows = cur.fetchall()
        conn.close()

        by_priority: Dict[str, Dict[str, Any]] = {}
        by_window: Dict[str, Dict[str, Any]] = {}
        total_weight = 0.0

        for weight, priority, window in rows:
            total_weight += weight
            bp = by_priority.setdefault(priority, {"count": 0, "weight_kg": 0.0})
            bp["count"] += 1
            bp["weight_kg"] = round(bp["weight_kg"] + weight, 4)
            bw = by_window.setdefault(window, {"count": 0, "weight_kg": 0.0})
            bw["count"] += 1
            bw["weight_kg"] = round(bw["weight_kg"] + weight, 4)

        return {
            "zone_id": zone_id,
            "date": date,
            "total_packages": len(rows),
            "total_weight_kg": round(total_weight, 2),
            "by_priority": by_priority,
            "by_window": by_window,
        }

    @tool(
        description=(
            "Retrieve the traffic congestion index and average speed for a zone, "
            "shift period, and day of week."
        ),
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "string",
                    "description": "Zone identifier, e.g. 'Z001'.",
                },
                "shift": {
                    "type": "string",
                    "enum": ["morning", "afternoon", "evening"],
                    "description": "Shift period.",
                },
                "day_of_week": {
                    "type": "string",
                    "description": "Day name, e.g. 'Tuesday'.",
                },
            },
            "required": ["zone_id", "shift", "day_of_week"],
        },
    )
    def get_traffic_data(self, zone_id: str, shift: str, day_of_week: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT congestion_index, avg_speed_kmh FROM traffic_patterns "
            "WHERE zone_id = ? AND shift = ? AND day_of_week = ?",
            (zone_id, shift, day_of_week),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {
                "zone_id": zone_id,
                "shift": shift,
                "day_of_week": day_of_week,
                "found": False,
            }
        return {
            "zone_id": zone_id,
            "shift": shift,
            "day_of_week": day_of_week,
            "congestion_index": row[0],
            "avg_speed_kmh": row[1],
            "found": True,
        }

    @tool(
        description=(
            "Search for drivers assigned to a given shift type. "
            "Returns paginated driver records."
        ),
        parameters={
            "type": "object",
            "properties": {
                "shift_type": {
                    "type": "string",
                    "enum": ["morning", "afternoon", "evening"],
                    "description": "The shift to filter by.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed. Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Defaults to 20.",
                },
            },
            "required": ["shift_type"],
        },
    )
    def search_drivers(
        self, shift_type: str, page: int = 1, page_size: int = 20
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM drivers WHERE shift_type = ?", (shift_type,)
        )
        total = cur.fetchone()[0]
        pages = math.ceil(total / page_size) if total else 0
        offset = (max(1, page) - 1) * page_size
        cur.execute(
            "SELECT driver_id, name, certification_level, experience_years, "
            "max_daily_deliveries FROM drivers "
            "WHERE shift_type = ? ORDER BY driver_id LIMIT ? OFFSET ?",
            (shift_type, page_size, offset),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "shift_type": shift_type,
            "drivers": [
                {
                    "driver_id": r[0],
                    "name": r[1],
                    "certification_level": r[2],
                    "experience_years": r[3],
                    "max_daily_deliveries": r[4],
                }
                for r in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": pages,
        }

    @tool(
        description="Retrieve the full profile for a single driver by ID.",
        parameters={
            "type": "object",
            "properties": {
                "driver_id": {
                    "type": "string",
                    "description": "Driver identifier, e.g. 'D001'.",
                },
            },
            "required": ["driver_id"],
        },
    )
    def get_driver_profile(self, driver_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT driver_id, name, license_type, shift_type, experience_years, "
            "certification_level, max_daily_deliveries FROM drivers WHERE driver_id = ?",
            (driver_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"driver_id": driver_id, "found": False}
        return {
            "driver_id": row[0],
            "name": row[1],
            "license_type": row[2],
            "shift_type": row[3],
            "experience_years": row[4],
            "certification_level": row[5],
            "max_daily_deliveries": row[6],
            "found": True,
        }

    @tool(
        description="List vehicles in the fleet with basic specs. Paginated.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed. Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def list_vehicles(self, page: int = 1, page_size: int = 20) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM vehicles")
        total = cur.fetchone()[0]
        pages = math.ceil(total / page_size) if total else 0
        offset = (max(1, page) - 1) * page_size
        cur.execute(
            "SELECT vehicle_id, vehicle_type, max_load_kg FROM vehicles "
            "ORDER BY vehicle_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "vehicles": [
                {"vehicle_id": r[0], "vehicle_type": r[1], "max_load_kg": r[2]}
                for r in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": pages,
        }

    @tool(
        description="Get full specifications for a single vehicle by ID.",
        parameters={
            "type": "object",
            "properties": {
                "vehicle_id": {
                    "type": "string",
                    "description": "Vehicle identifier, e.g. 'V001'.",
                },
            },
            "required": ["vehicle_id"],
        },
    )
    def get_vehicle_specs(self, vehicle_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT vehicle_id, vehicle_type, max_load_kg, max_volume_m3, "
            "fuel_type, operational_range_km FROM vehicles WHERE vehicle_id = ?",
            (vehicle_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"vehicle_id": vehicle_id, "found": False}
        return {
            "vehicle_id": row[0],
            "vehicle_type": row[1],
            "max_load_kg": row[2],
            "max_volume_m3": row[3],
            "fuel_type": row[4],
            "operational_range_km": row[5],
            "found": True,
        }

    # ── Ground-truth computation (used by step) ──────────────────────────

    def _compute_ground_truth(self):
        """Return (clusters, zone_metrics) for the current DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # Load workspace config ------------------------------------------------
        with open(os.path.join(self.workspace, "clustering_config.yaml")) as f:
            config = yaml.safe_load(f)

        target_date = config["target_date"]
        max_zpc = config["max_zones_per_cluster"]
        load_buffer_pct = config["load_buffer_pct"]
        priority_mult = config["priority_multiplier"]
        cert_thresh = config["certification_thresholds"]

        # Vehicle availability
        veh_avail = {}
        with open(os.path.join(self.workspace, "vehicle_availability.csv")) as f:
            for row in csv.DictReader(f):
                veh_avail[row["vehicle_id"]] = row["available"] == "True"

        # Driver performance scores
        perf_scores: Dict[str, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("driver_performance_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        perf_scores[row["driver_id"]] = float(
                            row["performance_score"]
                        )

        # Zone forecasts
        forecasts: Dict[str, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("zone_forecast_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for entry in json.load(f):
                        forecasts[entry["zone_id"]] = float(
                            entry["forecast_factor"]
                        )

        # Traffic bulletin adjustments
        traffic_adj: Dict[tuple, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("traffic_bulletin_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("Zone ") and "Adjustment:" in line:
                            parts = line.split("|")
                            zid = parts[0].strip().split()[-1]
                            shift = parts[1].strip().split()[-1]
                            adj_str = parts[2].strip().split()[-1]
                            traffic_adj[(zid, shift)] = float(adj_str)

        # All zones
        cur.execute(
            "SELECT zone_id, zone_name, region FROM zones ORDER BY zone_id"
        )
        zones = {r[0]: {"zone_name": r[1], "region": r[2]} for r in cur.fetchall()}

        # Today's packages per zone
        cur.execute(
            "SELECT zone_id, weight_kg, priority, delivery_window "
            "FROM packages WHERE created_date = ?",
            (target_date,),
        )
        zone_pkgs: Dict[str, list] = {}
        for zid, w, pri, win in cur.fetchall():
            zone_pkgs.setdefault(zid, []).append(
                {"weight_kg": w, "priority": pri, "delivery_window": win}
            )

        # ── Phase 1: per-zone metrics ────────────────────────────────────
        zone_metrics: Dict[str, dict] = {}
        for zid, pkgs in zone_pkgs.items():
            if not pkgs:
                continue

            by_window: Dict[str, int] = {}
            by_priority: Dict[str, Dict[str, Any]] = {}
            total_weight = 0.0

            for p in pkgs:
                win = p["delivery_window"]
                by_window[win] = by_window.get(win, 0) + 1
                bp = by_priority.setdefault(
                    p["priority"], {"count": 0, "weight": 0.0}
                )
                bp["count"] += 1
                bp["weight"] += p["weight_kg"]
                total_weight += p["weight_kg"]

            # Primary shift (tie-break: morning < afternoon < evening)
            primary_shift = min(
                by_window, key=lambda s: (-by_window[s], SHIFT_ORDER[s])
            )

            # Weighted load
            weighted_load = sum(
                by_priority.get(pr, {"weight": 0.0})["weight"] * mult
                for pr, mult in priority_mult.items()
            )

            # Forecast factor
            ff = forecasts.get(zid, 1.0)

            # Base congestion (derive day-of-week from target_date)
            import datetime as _dt
            _dow = _dt.datetime.strptime(target_date, "%Y-%m-%d").strftime("%A")
            cur.execute(
                "SELECT congestion_index FROM traffic_patterns "
                "WHERE zone_id = ? AND shift = ? AND day_of_week = ?",
                (zid, primary_shift, _dow),
            )
            row = cur.fetchone()
            base_cong = row[0] if row else 0.0
            adj = traffic_adj.get((zid, primary_shift), 0.0)
            eff_cong = min(max(base_cong + adj, 0.0), 1.0)

            adjusted_demand = weighted_load * ff * (1 + eff_cong)

            total_count = len(pkgs)
            urgent_ct = by_priority.get("urgent", {"count": 0})["count"]
            express_ct = by_priority.get("express", {"count": 0})["count"]
            urgent_pct = urgent_ct / total_count * 100
            express_urgent_pct = (express_ct + urgent_ct) / total_count * 100

            zone_metrics[zid] = {
                "region": zones[zid]["region"],
                "zone_name": zones[zid]["zone_name"],
                "primary_shift": primary_shift,
                "total_packages": total_count,
                "total_weight": round(total_weight, 2),
                "weighted_load": weighted_load,
                "adjusted_demand": adjusted_demand,
                "urgent_pct": urgent_pct,
                "express_urgent_pct": express_urgent_pct,
            }

        # ── Phase 2: cluster formation ───────────────────────────────────
        groups: Dict[tuple, list] = {}
        for zid, m in zone_metrics.items():
            key = (m["region"], m["primary_shift"])
            groups.setdefault(key, []).append(zid)

        sorted_keys = sorted(
            groups, key=lambda k: (k[0], SHIFT_ORDER[k[1]])
        )

        clusters: list = []
        cid_counter = 0
        for key in sorted_keys:
            zlist = groups[key]
            zlist.sort(key=lambda z: (-zone_metrics[z]["adjusted_demand"], z))
            for i in range(0, len(zlist), max_zpc):
                cid_counter += 1
                cid = f"C{cid_counter:03d}"
                c_zones = zlist[i : i + max_zpc]
                total_load = round(
                    sum(zone_metrics[z]["total_weight"] for z in c_zones), 2
                )
                req_cap = round(total_load * (1 + load_buffer_pct / 100), 2)

                # Min certification
                min_cert = "basic"
                for z in c_zones:
                    if zone_metrics[z]["urgent_pct"] > cert_thresh["urgent_pct_expert"]:
                        min_cert = "expert"
                        break
                    if (
                        zone_metrics[z]["express_urgent_pct"]
                        > cert_thresh["express_urgent_pct_advanced"]
                    ):
                        if CERT_RANK.get(min_cert, 0) < CERT_RANK["advanced"]:
                            min_cert = "advanced"

                total_packages = sum(
                    zone_metrics[z]["total_packages"] for z in c_zones
                )
                clusters.append(
                    {
                        "cluster_id": cid,
                        "region": key[0],
                        "shift": key[1],
                        "zone_ids": sorted(c_zones),
                        "total_load": total_load,
                        "required_capacity": req_cap,
                        "min_cert": min_cert,
                        "total_packages": total_packages,
                    }
                )

        # ── Phase 3: resource assignment ─────────────────────────────────
        cur.execute(
            "SELECT driver_id, name, shift_type, certification_level FROM drivers"
        )
        all_drivers = {
            r[0]: {"name": r[1], "shift_type": r[2], "certification_level": r[3]}
            for r in cur.fetchall()
        }
        cur.execute("SELECT vehicle_id, vehicle_type, max_load_kg FROM vehicles")
        all_vehicles = {
            r[0]: {"vehicle_type": r[1], "max_load_kg": r[2]}
            for r in cur.fetchall()
        }
        conn.close()

        assigned_drivers: set = set()
        assigned_vehicles: set = set()

        for cluster in clusters:
            shift = cluster["shift"]
            min_cert_level = CERT_RANK[cluster["min_cert"]]
            req_cap = cluster["required_capacity"]

            # Eligible drivers
            eligible_d = []
            for did, d in all_drivers.items():
                if did in assigned_drivers:
                    continue
                if d["shift_type"] != shift:
                    continue
                if CERT_RANK.get(d["certification_level"], 0) < min_cert_level:
                    continue
                eligible_d.append((did, perf_scores.get(did, 0.0)))
            eligible_d.sort(key=lambda x: (-x[1], x[0]))

            chosen_driver = eligible_d[0][0] if eligible_d else None
            if chosen_driver:
                assigned_drivers.add(chosen_driver)

            # Eligible vehicles
            eligible_v = []
            for vid, v in all_vehicles.items():
                if vid in assigned_vehicles:
                    continue
                if not veh_avail.get(vid, False):
                    continue
                if v["max_load_kg"] < req_cap:
                    continue
                eligible_v.append((vid, v["max_load_kg"]))
            eligible_v.sort(key=lambda x: (x[1], x[0]))

            chosen_vehicle = eligible_v[0][0] if eligible_v else None
            if chosen_vehicle:
                assigned_vehicles.add(chosen_vehicle)

            cluster["driver_id"] = chosen_driver
            cluster["driver_name"] = (
                all_drivers[chosen_driver]["name"] if chosen_driver else ""
            )
            cluster["vehicle_id"] = chosen_vehicle
            cluster["vehicle_type"] = (
                all_vehicles[chosen_vehicle]["vehicle_type"]
                if chosen_vehicle
                else ""
            )
            cluster["vehicle_capacity"] = (
                all_vehicles[chosen_vehicle]["max_load_kg"]
                if chosen_vehicle
                else 0.0
            )
            if chosen_vehicle and cluster["vehicle_capacity"] > 0:
                cluster["utilization_pct"] = round(
                    cluster["total_load"] / cluster["vehicle_capacity"] * 100, 1
                )
            else:
                cluster["utilization_pct"] = 0.0

        return clusters, zone_metrics

    # ── Evaluation ────────────────────────────────────────────────────────

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
        clusters, zone_metrics = self._compute_ground_truth()
        expected_zone_set = set(zone_metrics.keys())
        total_score = 0
        max_score = 0
        eval_criteria: Dict[str, dict] = {}

        # Build quick-lookup structures
        cluster_by_zone: Dict[str, dict] = {}
        for cl in clusters:
            for z in cl["zone_ids"]:
                cluster_by_zone[z] = cl
        expected_cluster_ids = {cl["cluster_id"] for cl in clusters}

        # ── Criterion 1: CSV structure (10 pts) ──────────────────────────
        c1_max = 10
        max_score += c1_max
        csv_path = os.path.join(self.workspace, "zone_assignment_map.csv")
        expected_cols = [
            "zone_id", "zone_name", "cluster_id", "shift", "driver_id",
            "driver_name", "vehicle_id", "estimated_packages",
            "estimated_load_kg", "utilization_pct",
        ]
        df = None
        try:
            df = pd.read_csv(csv_path, dtype=str)
            if list(df.columns) == expected_cols:
                c1_score = c1_max
                c1_pass = True
                c1_reason = ""
            else:
                c1_score = 5  # partial: file exists but wrong cols
                c1_pass = False
                c1_reason = f"Expected columns {expected_cols}, got {list(df.columns)}"
        except Exception as e:
            c1_score = 0
            c1_pass = False
            c1_reason = f"Cannot read CSV: {e}"
        eval_criteria["csv_structure"] = {
            "passed": c1_pass, "score": c1_score, "max_score": c1_max,
            **({"reason": c1_reason} if not c1_pass else {}),
        }
        total_score += c1_score

        # ── Criterion 2: Zone coverage (15 pts) ─────────────────────────
        c2_max = 15
        max_score += c2_max
        if df is not None and "zone_id" in df.columns:
            actual_zones = set(df["zone_id"].tolist())
            missing = expected_zone_set - actual_zones
            extra = actual_zones - expected_zone_set
            if not missing and not extra:
                c2_score = c2_max
                c2_pass = True
                c2_reason = ""
            else:
                frac = max(
                    0.0,
                    1.0
                    - len(missing) / max(len(expected_zone_set), 1)
                    - len(extra) / max(len(expected_zone_set), 1) * 0.5,
                )
                c2_score = round(c2_max * frac)
                c2_pass = False
                c2_reason = f"Missing {len(missing)}, extra {len(extra)} zones"
        else:
            c2_score = 0
            c2_pass = False
            c2_reason = "No valid zone_id column"
        eval_criteria["zone_coverage"] = {
            "passed": c2_pass, "score": c2_score, "max_score": c2_max,
            **({"reason": c2_reason} if not c2_pass else {}),
        }
        total_score += c2_score

        # ── Criterion 3: Cluster formation (15 pts) ─────────────────────
        c3_max = 15
        max_score += c3_max
        if df is not None and "cluster_id" in df.columns and "zone_id" in df.columns:
            # Check cluster membership matches ground truth
            actual_cluster_map: Dict[str, list] = {}
            for _, row in df.iterrows():
                actual_cluster_map.setdefault(row["cluster_id"], []).append(
                    row["zone_id"]
                )
            expected_cluster_map: Dict[str, list] = {}
            for cl in clusters:
                expected_cluster_map[cl["cluster_id"]] = sorted(cl["zone_ids"])

            match_count = 0
            total_clusters_expected = len(expected_cluster_map)
            for cid, exp_zones in expected_cluster_map.items():
                act_zones = sorted(actual_cluster_map.get(cid, []))
                if act_zones == exp_zones:
                    match_count += 1
            if total_clusters_expected > 0:
                frac = match_count / total_clusters_expected
            else:
                frac = 1.0
            c3_score = round(c3_max * frac)
            c3_pass = frac == 1.0
            c3_reason = (
                ""
                if c3_pass
                else f"{match_count}/{total_clusters_expected} clusters match"
            )
        else:
            c3_score = 0
            c3_pass = False
            c3_reason = "Missing cluster_id or zone_id column"
        eval_criteria["cluster_formation"] = {
            "passed": c3_pass, "score": c3_score, "max_score": c3_max,
            **({"reason": c3_reason} if not c3_pass else {}),
        }
        total_score += c3_score

        # ── Criterion 4: Driver validity (15 pts) ───────────────────────
        c4_max = 15
        max_score += c4_max
        if df is not None and "cluster_id" in df.columns and "driver_id" in df.columns:
            # One driver_id per cluster — check against ground truth
            actual_driver_map: Dict[str, str] = {}
            for _, row in df.iterrows():
                actual_driver_map[row["cluster_id"]] = row["driver_id"]
            expected_driver_map = {
                cl["cluster_id"]: (cl["driver_id"] or "") for cl in clusters
            }
            d_match = 0
            for cid, exp_did in expected_driver_map.items():
                actual_did = actual_driver_map.get(cid, "")
                # Normalize: treat NaN/None/empty as ""
                if pd.isna(actual_did):
                    actual_did = ""
                if actual_did == exp_did:
                    d_match += 1
            n_cl = len(expected_driver_map)
            frac = d_match / n_cl if n_cl else 1.0
            c4_score = round(c4_max * frac)
            c4_pass = frac == 1.0
            c4_reason = (
                "" if c4_pass else f"{d_match}/{n_cl} driver assignments match"
            )
        else:
            c4_score = 0
            c4_pass = False
            c4_reason = "Missing columns"
        eval_criteria["driver_validity"] = {
            "passed": c4_pass, "score": c4_score, "max_score": c4_max,
            **({"reason": c4_reason} if not c4_pass else {}),
        }
        total_score += c4_score

        # ── Criterion 5: Vehicle validity (15 pts) ──────────────────────
        c5_max = 15
        max_score += c5_max
        if df is not None and "cluster_id" in df.columns and "vehicle_id" in df.columns:
            actual_veh_map: Dict[str, str] = {}
            for _, row in df.iterrows():
                actual_veh_map[row["cluster_id"]] = row["vehicle_id"]
            expected_veh_map = {
                cl["cluster_id"]: (cl["vehicle_id"] or "") for cl in clusters
            }
            v_match = 0
            for cid, exp_vid in expected_veh_map.items():
                actual_vid = actual_veh_map.get(cid, "")
                if pd.isna(actual_vid):
                    actual_vid = ""
                if actual_vid == exp_vid:
                    v_match += 1
            n_cl = len(expected_veh_map)
            frac = v_match / n_cl if n_cl else 1.0
            c5_score = round(c5_max * frac)
            c5_pass = frac == 1.0
            c5_reason = (
                "" if c5_pass else f"{v_match}/{n_cl} vehicle assignments match"
            )
        else:
            c5_score = 0
            c5_pass = False
            c5_reason = "Missing columns"
        eval_criteria["vehicle_validity"] = {
            "passed": c5_pass, "score": c5_score, "max_score": c5_max,
            **({"reason": c5_reason} if not c5_pass else {}),
        }
        total_score += c5_score

        # ── Criterion 6: dispatch_summary.json (15 pts) ─────────────────
        c6_max = 15
        max_score += c6_max
        json_path = os.path.join(self.workspace, "dispatch_summary.json")
        try:
            with open(json_path) as f:
                summary = json.load(f)

            checks_passed = 0
            total_checks = 5

            # 6a: total_clusters
            expected_total_clusters = len(clusters)
            if summary.get("total_clusters") == expected_total_clusters:
                checks_passed += 1

            # 6b: total_zones_assigned
            if summary.get("total_zones_assigned") == len(zone_metrics):
                checks_passed += 1

            # 6c: total_packages_scheduled
            exp_total_pkgs = sum(cl["total_packages"] for cl in clusters)
            if summary.get("total_packages_scheduled") == exp_total_pkgs:
                checks_passed += 1

            # 6d: cluster count in array
            if isinstance(summary.get("clusters"), list) and len(
                summary["clusters"]
            ) == expected_total_clusters:
                checks_passed += 1

            # 6e: average_utilization_pct
            if clusters:
                exp_avg_util = round(
                    sum(cl["utilization_pct"] for cl in clusters) / len(clusters),
                    1,
                )
            else:
                exp_avg_util = 0.0
            if (
                isinstance(summary.get("average_utilization_pct"), (int, float))
                and round(float(summary["average_utilization_pct"]), 1)
                == exp_avg_util
            ):
                checks_passed += 1

            frac = checks_passed / total_checks
            c6_score = round(c6_max * frac)
            c6_pass = checks_passed == total_checks
            c6_reason = (
                ""
                if c6_pass
                else f"{checks_passed}/{total_checks} summary checks pass"
            )
        except Exception as e:
            c6_score = 0
            c6_pass = False
            c6_reason = f"Cannot read JSON: {e}"
        eval_criteria["dispatch_summary"] = {
            "passed": c6_pass, "score": c6_score, "max_score": c6_max,
            **({"reason": c6_reason} if not c6_pass else {}),
        }
        total_score += c6_score

        # ── Criterion 7: Response metrics (15 pts) ──────────────────────
        c7_max = 15
        max_score += c7_max
        action_str = str(action) if action else ""
        resp_checks = 0
        resp_total = 3

        # 7a: total clusters
        exp_tc = len(clusters)
        if str(exp_tc) in action_str:
            resp_checks += 1

        # 7b: average utilization
        if clusters:
            exp_au = round(
                sum(cl["utilization_pct"] for cl in clusters) / len(clusters), 1
            )
        else:
            exp_au = 0.0
        # Accept e.g. "45.3" in the response
        if f"{exp_au}" in action_str:
            resp_checks += 1

        # 7c: total packages
        exp_tp = sum(cl["total_packages"] for cl in clusters)
        if str(exp_tp) in action_str:
            resp_checks += 1

        c7_score = round(c7_max * resp_checks / resp_total)
        c7_pass = resp_checks == resp_total
        c7_reason = (
            ""
            if c7_pass
            else f"{resp_checks}/{resp_total} response metrics found"
        )
        eval_criteria["response_metrics"] = {
            "passed": c7_pass, "score": c7_score, "max_score": c7_max,
            **({"reason": c7_reason} if not c7_pass else {}),
        }
        total_score += c7_score

        # ── Final ────────────────────────────────────────────────────────
        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ── Self-verification ────────────────────────────────────────────────

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
        import datetime

        # ── Read workspace config files ──────────────────────────────────
        with open(os.path.join(self.workspace, "clustering_config.yaml")) as f:
            config = yaml.safe_load(f)

        target_date = config["target_date"]
        max_zpc = config["max_zones_per_cluster"]
        load_buffer_pct = config["load_buffer_pct"]
        priority_mult = config["priority_multiplier"]
        cert_thresh = config["certification_thresholds"]

        # Determine day of week from target_date
        dt = datetime.datetime.strptime(target_date, "%Y-%m-%d")
        day_of_week = dt.strftime("%A")  # e.g. "Tuesday"

        # Vehicle availability
        veh_avail: Dict[str, bool] = {}
        with open(os.path.join(self.workspace, "vehicle_availability.csv")) as f:
            for row in csv.DictReader(f):
                veh_avail[row["vehicle_id"]] = row["available"] == "True"

        # Driver performance scores
        perf_scores: Dict[str, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("driver_performance_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        perf_scores[row["driver_id"]] = float(
                            row["performance_score"]
                        )

        # Zone forecasts
        forecasts: Dict[str, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("zone_forecast_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for entry in json.load(f):
                        forecasts[entry["zone_id"]] = float(
                            entry["forecast_factor"]
                        )

        # Traffic bulletin adjustments
        traffic_adj: Dict[tuple, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("traffic_bulletin_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("Zone ") and "Adjustment:" in line:
                            parts = line.split("|")
                            zid = parts[0].strip().split()[-1]
                            shift = parts[1].strip().split()[-1]
                            adj_str = parts[2].strip().split()[-1]
                            traffic_adj[(zid, shift)] = float(adj_str)

        # Priority rules (already encoded in config thresholds)
        # Read the file to mirror what an agent would do
        with open(os.path.join(self.workspace, "priority_rules.md")) as f:
            _ = f.read()

        # ── Gather data via tools ────────────────────────────────────────
        # 1. List all zones
        all_zones: list = []
        page = 1
        while True:
            res = self.tools["list_zones"](page=page, page_size=20)
            all_zones.extend(res["zones"])
            if page >= res["pages"]:
                break
            page += 1

        # 2. Get package summary for each zone on target_date
        zone_pkg_summaries: Dict[str, dict] = {}
        for z in all_zones:
            zid = z["zone_id"]
            summary = self.tools["get_zone_package_summary"](
                zone_id=zid, date=target_date
            )
            if summary["total_packages"] > 0:
                zone_pkg_summaries[zid] = summary

        # 3. Get traffic data for each active zone's primary shift
        # First determine primary shift per zone
        zone_primary_shift: Dict[str, str] = {}
        for zid, s in zone_pkg_summaries.items():
            bw = s["by_window"]
            primary = min(
                bw, key=lambda sh: (-bw[sh]["count"], SHIFT_ORDER[sh])
            )
            zone_primary_shift[zid] = primary

        # Now fetch traffic
        zone_traffic: Dict[str, dict] = {}
        for zid, pshift in zone_primary_shift.items():
            res = self.tools["get_traffic_data"](
                zone_id=zid, shift=pshift, day_of_week=day_of_week
            )
            zone_traffic[zid] = res

        # 4. Get drivers by shift
        drivers_by_shift: Dict[str, list] = {}
        for shift in ["morning", "afternoon", "evening"]:
            drivers_by_shift[shift] = []
            page = 1
            while True:
                res = self.tools["search_drivers"](
                    shift_type=shift, page=page, page_size=20
                )
                drivers_by_shift[shift].extend(res["drivers"])
                if page >= res["pages"]:
                    break
                page += 1

        # 5. List all vehicles
        all_vehicles_list: list = []
        page = 1
        while True:
            res = self.tools["list_vehicles"](page=page, page_size=20)
            all_vehicles_list.extend(res["vehicles"])
            if page >= res["pages"]:
                break
            page += 1

        # Build zone info map from list_zones results
        zone_info = {z["zone_id"]: z for z in all_zones}

        # ── Phase 1: per-zone metrics ────────────────────────────────────
        zone_metrics: Dict[str, dict] = {}
        for zid, s in zone_pkg_summaries.items():
            pshift = zone_primary_shift[zid]

            # Weighted load
            weighted_load = 0.0
            for pr, mult in priority_mult.items():
                if pr in s["by_priority"]:
                    weighted_load += s["by_priority"][pr]["weight_kg"] * mult

            ff = forecasts.get(zid, 1.0)
            base_cong = (
                zone_traffic[zid]["congestion_index"]
                if zone_traffic[zid].get("found")
                else 0.0
            )
            adj = traffic_adj.get((zid, pshift), 0.0)
            eff_cong = min(max(base_cong + adj, 0.0), 1.0)
            adjusted_demand = weighted_load * ff * (1 + eff_cong)

            total_count = s["total_packages"]
            urgent_ct = s["by_priority"].get("urgent", {}).get("count", 0)
            express_ct = s["by_priority"].get("express", {}).get("count", 0)
            urgent_pct = urgent_ct / total_count * 100
            express_urgent_pct = (express_ct + urgent_ct) / total_count * 100

            zone_metrics[zid] = {
                "region": zone_info[zid]["region"],
                "zone_name": zone_info[zid]["zone_name"],
                "primary_shift": pshift,
                "total_packages": total_count,
                "total_weight": s["total_weight_kg"],
                "adjusted_demand": adjusted_demand,
                "urgent_pct": urgent_pct,
                "express_urgent_pct": express_urgent_pct,
            }

        # ── Phase 2: cluster formation ───────────────────────────────────
        groups: Dict[tuple, list] = {}
        for zid, m in zone_metrics.items():
            key = (m["region"], m["primary_shift"])
            groups.setdefault(key, []).append(zid)

        sorted_keys = sorted(
            groups, key=lambda k: (k[0], SHIFT_ORDER[k[1]])
        )

        clusters: list = []
        cid_counter = 0
        for key in sorted_keys:
            zlist = groups[key]
            zlist.sort(key=lambda z: (-zone_metrics[z]["adjusted_demand"], z))
            for i in range(0, len(zlist), max_zpc):
                cid_counter += 1
                cid = f"C{cid_counter:03d}"
                c_zones = zlist[i : i + max_zpc]
                total_load = round(
                    sum(zone_metrics[z]["total_weight"] for z in c_zones), 2
                )
                req_cap = round(total_load * (1 + load_buffer_pct / 100), 2)

                min_cert = "basic"
                for z in c_zones:
                    if zone_metrics[z]["urgent_pct"] > cert_thresh["urgent_pct_expert"]:
                        min_cert = "expert"
                        break
                    if (
                        zone_metrics[z]["express_urgent_pct"]
                        > cert_thresh["express_urgent_pct_advanced"]
                    ):
                        if CERT_RANK.get(min_cert, 0) < CERT_RANK["advanced"]:
                            min_cert = "advanced"

                total_packages = sum(
                    zone_metrics[z]["total_packages"] for z in c_zones
                )
                clusters.append(
                    {
                        "cluster_id": cid,
                        "region": key[0],
                        "shift": key[1],
                        "zone_ids": sorted(c_zones),
                        "total_load": total_load,
                        "required_capacity": req_cap,
                        "min_cert": min_cert,
                        "total_packages": total_packages,
                    }
                )

        # ── Phase 3: resource assignment ─────────────────────────────────
        # Build driver lookup: {driver_id: {name, certification_level, shift_type}}
        all_drivers_map: Dict[str, dict] = {}
        for shift, dlist in drivers_by_shift.items():
            for d in dlist:
                all_drivers_map[d["driver_id"]] = {
                    "name": d["name"],
                    "certification_level": d["certification_level"],
                    "shift_type": shift,
                }

        # Build vehicle lookup
        all_vehicles_map: Dict[str, dict] = {}
        for v in all_vehicles_list:
            all_vehicles_map[v["vehicle_id"]] = {
                "vehicle_type": v["vehicle_type"],
                "max_load_kg": v["max_load_kg"],
            }

        assigned_drivers: set = set()
        assigned_vehicles: set = set()

        for cluster in clusters:
            shift = cluster["shift"]
            min_cert_level = CERT_RANK[cluster["min_cert"]]
            req_cap = cluster["required_capacity"]

            eligible_d = []
            for did, d in all_drivers_map.items():
                if did in assigned_drivers:
                    continue
                if d["shift_type"] != shift:
                    continue
                if CERT_RANK.get(d["certification_level"], 0) < min_cert_level:
                    continue
                eligible_d.append((did, perf_scores.get(did, 0.0)))
            eligible_d.sort(key=lambda x: (-x[1], x[0]))
            chosen_driver = eligible_d[0][0] if eligible_d else None
            if chosen_driver:
                assigned_drivers.add(chosen_driver)

            eligible_v = []
            for vid, v in all_vehicles_map.items():
                if vid in assigned_vehicles:
                    continue
                if not veh_avail.get(vid, False):
                    continue
                if v["max_load_kg"] < req_cap:
                    continue
                eligible_v.append((vid, v["max_load_kg"]))
            eligible_v.sort(key=lambda x: (x[1], x[0]))
            chosen_vehicle = eligible_v[0][0] if eligible_v else None
            if chosen_vehicle:
                assigned_vehicles.add(chosen_vehicle)

            cluster["driver_id"] = chosen_driver
            cluster["driver_name"] = (
                all_drivers_map[chosen_driver]["name"] if chosen_driver else ""
            )
            cluster["vehicle_id"] = chosen_vehicle
            cluster["vehicle_type"] = (
                all_vehicles_map[chosen_vehicle]["vehicle_type"]
                if chosen_vehicle
                else ""
            )
            cluster["vehicle_capacity"] = (
                all_vehicles_map[chosen_vehicle]["max_load_kg"]
                if chosen_vehicle
                else 0.0
            )
            if chosen_vehicle and cluster["vehicle_capacity"] > 0:
                cluster["utilization_pct"] = round(
                    cluster["total_load"] / cluster["vehicle_capacity"] * 100, 1
                )
            else:
                cluster["utilization_pct"] = 0.0

        # ── Write deliverables ───────────────────────────────────────────
        # 1. zone_assignment_map.csv
        csv_rows = []
        for cl in clusters:
            for zid in cl["zone_ids"]:
                csv_rows.append(
                    {
                        "zone_id": zid,
                        "zone_name": zone_metrics[zid]["zone_name"],
                        "cluster_id": cl["cluster_id"],
                        "shift": cl["shift"],
                        "driver_id": cl["driver_id"] or "",
                        "driver_name": cl["driver_name"],
                        "vehicle_id": cl["vehicle_id"] or "",
                        "estimated_packages": zone_metrics[zid]["total_packages"],
                        "estimated_load_kg": zone_metrics[zid]["total_weight"],
                        "utilization_pct": cl["utilization_pct"],
                    }
                )
        csv_rows.sort(key=lambda r: (r["cluster_id"], r["zone_id"]))
        csv_path = os.path.join(self.workspace, "zone_assignment_map.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "zone_id", "zone_name", "cluster_id", "shift", "driver_id",
                    "driver_name", "vehicle_id", "estimated_packages",
                    "estimated_load_kg", "utilization_pct",
                ],
            )
            writer.writeheader()
            writer.writerows(csv_rows)

        # 2. dispatch_summary.json
        total_clusters = len(clusters)
        total_zones = len(zone_metrics)
        total_packages = sum(cl["total_packages"] for cl in clusters)
        avg_util = (
            round(
                sum(cl["utilization_pct"] for cl in clusters) / total_clusters, 1
            )
            if total_clusters
            else 0.0
        )

        summary = {
            "date": target_date,
            "total_clusters": total_clusters,
            "total_zones_assigned": total_zones,
            "total_packages_scheduled": total_packages,
            "clusters": [
                {
                    "cluster_id": cl["cluster_id"],
                    "region": cl["region"],
                    "shift": cl["shift"],
                    "zone_ids": cl["zone_ids"],
                    "driver_id": cl["driver_id"] or "",
                    "vehicle_id": cl["vehicle_id"] or "",
                    "total_packages": cl["total_packages"],
                    "total_load_kg": cl["total_load"],
                    "vehicle_capacity_kg": cl["vehicle_capacity"],
                    "utilization_pct": cl["utilization_pct"],
                }
                for cl in clusters
            ],
            "average_utilization_pct": avg_util,
        }
        json_path = os.path.join(self.workspace, "dispatch_summary.json")
        with open(json_path, "w") as f:
            json.dump(summary, f, indent=2)

        # 3. Final response
        action = (
            f"Zone assignment complete for {target_date}. "
            f"Total clusters formed: {total_clusters}. "
            f"Average utilization: {avg_util}%. "
            f"Total packages scheduled for delivery: {total_packages}."
        )

        return self.step(action)
