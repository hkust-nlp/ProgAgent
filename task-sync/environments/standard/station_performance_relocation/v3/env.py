"""
Environment for EV Charging Station Relocation Analysis task.
Provides tools for querying station data and evaluates the agent's output.
"""

import csv
import json
import math
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


# ---------------------------------------------------------------------------
# Tool decorator
# ---------------------------------------------------------------------------

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ---------------------------------------------------------------------------
# Haversine helper
# ---------------------------------------------------------------------------

def _haversine(lat1, lon1, lat2, lon2):
    """Return distance in km between two (lat, lon) points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Task_Env
# ---------------------------------------------------------------------------

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

    # ====================================================================
    # TOOL METHODS
    # ====================================================================

    @tool(
        description=(
            "List charging stations with pagination. Returns station id, "
            "name, and status for each entry."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of stations per page (max 50).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_stations(self, page: int, page_size: int):
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        total = cur.execute("SELECT COUNT(*) FROM charging_stations").fetchone()[0]
        rows = cur.execute(
            "SELECT station_id, name, status FROM charging_stations "
            "ORDER BY station_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "stations": [
                {"station_id": r[0], "name": r[1], "status": r[2]} for r in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @tool(
        description=(
            "Get detailed information for a single charging station, "
            "including region name, coordinates, charger count, and type."
        ),
        parameters={
            "type": "object",
            "properties": {
                "station_id": {
                    "type": "integer",
                    "description": "The station identifier.",
                },
            },
            "required": ["station_id"],
        },
    )
    def get_station_details(self, station_id: int):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        row = cur.execute(
            "SELECT s.station_id, s.name, s.region_id, r.name, "
            "       s.latitude, s.longitude, s.num_chargers, "
            "       s.charger_type, s.install_date, s.status "
            "FROM charging_stations s "
            "JOIN regions r ON s.region_id = r.region_id "
            "WHERE s.station_id = ?",
            (station_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Station {station_id} not found."}
        return {
            "station_id": row[0],
            "name": row[1],
            "region_id": row[2],
            "region_name": row[3],
            "latitude": row[4],
            "longitude": row[5],
            "num_chargers": row[6],
            "charger_type": row[7],
            "install_date": row[8],
            "status": row[9],
        }

    @tool(
        description=(
            "Get aggregated session statistics for a station in a given year. "
            "Returns total sessions, completed/failed counts, total charge "
            "hours, energy delivered, and revenue."
        ),
        parameters={
            "type": "object",
            "properties": {
                "station_id": {
                    "type": "integer",
                    "description": "The station identifier.",
                },
                "year": {
                    "type": "integer",
                    "description": "Calendar year to aggregate (e.g. 2024).",
                },
            },
            "required": ["station_id", "year"],
        },
    )
    def get_session_stats(self, station_id: int, year: int):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        row = cur.execute(
            "SELECT SUM(total_sessions), SUM(completed_sessions), "
            "       SUM(failed_sessions), SUM(total_charge_hours), "
            "       SUM(energy_kwh), SUM(revenue) "
            "FROM monthly_station_stats "
            "WHERE station_id = ? AND year = ?",
            (station_id, year),
        ).fetchone()
        conn.close()
        if row is None or row[0] is None:
            return {
                "station_id": station_id,
                "year": year,
                "total_sessions": 0,
                "completed_sessions": 0,
                "failed_sessions": 0,
                "total_charge_hours": 0.0,
                "total_energy_kwh": 0.0,
                "total_revenue": 0.0,
            }
        return {
            "station_id": station_id,
            "year": year,
            "total_sessions": int(row[0]),
            "completed_sessions": int(row[1]),
            "failed_sessions": int(row[2]),
            "total_charge_hours": round(float(row[3]), 2),
            "total_energy_kwh": round(float(row[4]), 2),
            "total_revenue": round(float(row[5]), 2),
        }

    @tool(
        description=(
            "Get paginated failure records for a station. Each record "
            "includes failure type, severity, resolution hours, and a "
            "short description."
        ),
        parameters={
            "type": "object",
            "properties": {
                "station_id": {
                    "type": "integer",
                    "description": "The station identifier.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (max 100).",
                },
            },
            "required": ["station_id", "page", "page_size"],
        },
    )
    def get_failure_records(self, station_id: int, page: int, page_size: int):
        page_size = min(page_size, 100)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        total = cur.execute(
            "SELECT COUNT(*) FROM session_failures WHERE station_id = ?",
            (station_id,),
        ).fetchone()[0]
        rows = cur.execute(
            "SELECT failure_id, failure_date, failure_type, severity, "
            "       resolution_hours, description "
            "FROM session_failures WHERE station_id = ? "
            "ORDER BY failure_id LIMIT ? OFFSET ?",
            (station_id, page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "station_id": station_id,
            "records": [
                {
                    "failure_id": r[0],
                    "failure_date": r[1],
                    "failure_type": r[2],
                    "severity": r[3],
                    "resolution_hours": r[4],
                    "description": r[5],
                }
                for r in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @tool(
        description=(
            "Find competitor charging stations within a given radius of a "
            "station. Returns each competitor's distance, charger count, "
            "and network."
        ),
        parameters={
            "type": "object",
            "properties": {
                "station_id": {
                    "type": "integer",
                    "description": "The reference station identifier.",
                },
                "radius_km": {
                    "type": "number",
                    "description": "Search radius in kilometres.",
                },
            },
            "required": ["station_id", "radius_km"],
        },
    )
    def get_nearby_competitors(self, station_id: int, radius_km: float):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        srow = cur.execute(
            "SELECT latitude, longitude FROM charging_stations "
            "WHERE station_id = ?",
            (station_id,),
        ).fetchone()
        if srow is None:
            conn.close()
            return {"error": f"Station {station_id} not found."}
        slat, slon = srow
        comps = cur.execute(
            "SELECT competitor_id, name, latitude, longitude, "
            "       num_chargers, network "
            "FROM competitors",
        ).fetchall()
        conn.close()
        nearby = []
        for c in comps:
            d = _haversine(slat, slon, c[2], c[3])
            if d <= radius_km:
                nearby.append({
                    "competitor_id": c[0],
                    "name": c[1],
                    "distance_km": round(d, 2),
                    "num_chargers": c[4],
                    "network": c[5],
                })
        nearby.sort(key=lambda x: x["distance_km"])
        return {
            "station_id": station_id,
            "competitors": nearby,
            "count": len(nearby),
        }

    @tool(
        description=(
            "Get quarterly EV registration records for a specific region. "
            "Returns counts broken down by year, quarter, and vehicle type."
        ),
        parameters={
            "type": "object",
            "properties": {
                "region_id": {
                    "type": "integer",
                    "description": "The region identifier.",
                },
            },
            "required": ["region_id"],
        },
    )
    def get_regional_ev_data(self, region_id: int):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT year, quarter, vehicle_count, vehicle_type "
            "FROM ev_registrations WHERE region_id = ? "
            "ORDER BY year, quarter, vehicle_type",
            (region_id,),
        ).fetchall()
        conn.close()
        return {
            "region_id": region_id,
            "records": [
                {
                    "year": r[0],
                    "quarter": r[1],
                    "vehicle_count": r[2],
                    "vehicle_type": r[3],
                }
                for r in rows
            ],
        }

    # ====================================================================
    # GROUND-TRUTH COMPUTATION (used by step)
    # ====================================================================

    def _compute_ground_truth(self):
        """Compute the expected relocation list from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # --- configs ---
        with open(os.path.join(self.workspace, "scoring_config.yaml")) as f:
            cfg = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "revenue_model_params.json")) as f:
            rp = json.load(f)

        util_thresh = cfg["underperformance_thresholds"]["adjusted_utilization_below"]
        fail_thresh = cfg["underperformance_thresholds"]["failure_rate_above"]
        weights = cfg["scoring_weights"]
        comp_radius = cfg["competitor_radius_km"]
        comp_cap = cfg["competitor_cap"]
        min_score = cfg["min_composite_score"]
        benchmark = rp["benchmark_utilization"]
        rev_per_hour = rp["revenue_per_charger_hour"]
        annual_hours = rp["annual_operating_hours"]

        # --- stations ---
        stations = {}
        for row in cur.execute(
            "SELECT s.station_id, s.name, s.region_id, r.name, "
            "       s.latitude, s.longitude, s.num_chargers "
            "FROM charging_stations s "
            "JOIN regions r ON s.region_id = r.region_id"
        ):
            stations[row[0]] = {
                "station_id": row[0], "name": row[1],
                "region_id": row[2], "region_name": row[3],
                "lat": row[4], "lon": row[5], "num_chargers": row[6],
            }

        # --- annual stats ---
        for row in cur.execute(
            "SELECT station_id, SUM(total_sessions), SUM(failed_sessions), "
            "       SUM(total_charge_hours) "
            "FROM monthly_station_stats WHERE year = 2024 "
            "GROUP BY station_id"
        ):
            if row[0] in stations:
                stations[row[0]].update({
                    "total_sessions": int(row[1]),
                    "failed_sessions": int(row[2]),
                    "charge_hours": float(row[3]),
                })

        # --- maintenance downtime ---
        downtime: Dict[int, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("maintenance_log_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                for block in content.strip().split("---"):
                    block = block.strip()
                    if not block:
                        continue
                    rec: Dict[str, str] = {}
                    for line in block.split("\n"):
                        if ":" in line:
                            k, v = line.split(":", 1)
                            rec[k.strip()] = v.strip()
                    if "Station ID" in rec:
                        sid = int(rec["Station ID"])
                        dh = float(rec["Downtime Hours"])
                        ca = int(rec["Chargers Affected"])
                        downtime[sid] = downtime.get(sid, 0) + dh * ca

        # --- utilization & failure rate ---
        for sid, s in stations.items():
            nc = s["num_chargers"]
            ch = s.get("charge_hours", 0.0)
            ts = s.get("total_sessions", 0)
            fs = s.get("failed_sessions", 0)
            avail = nc * annual_hours - downtime.get(sid, 0)
            s["adjusted_util"] = ch / avail if avail > 0 else 0.0
            s["fail_rate"] = fs / ts if ts > 0 else 0.0

        # --- EV growth rates (forecast files + historical fallback) ---
        forecasts: Dict[int, float] = {}
        forecast_file_values: List[float] = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("ev_market_forecast_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                for entry in data:
                    val = entry["projected_ev_growth_rate"]
                    forecasts[entry["region_id"]] = val
                    forecast_file_values.append(val)

        # historical fallback for missing regions
        all_rids = {s["region_id"] for s in stations.values()}
        for rid in all_rids:
            if rid not in forecasts:
                t23 = cur.execute(
                    "SELECT SUM(vehicle_count) FROM ev_registrations "
                    "WHERE region_id = ? AND year = 2023", (rid,)
                ).fetchone()[0] or 0
                t24 = cur.execute(
                    "SELECT SUM(vehicle_count) FROM ev_registrations "
                    "WHERE region_id = ? AND year = 2024", (rid,)
                ).fetchone()[0] or 0
                forecasts[rid] = (t24 - t23) / t23 if t23 > 0 else 0.0

        # median from forecast-file values only
        forecast_file_values.sort()
        n = len(forecast_file_values)
        if n == 0:
            median_growth = 0.0
        elif n % 2 == 0:
            median_growth = (forecast_file_values[n // 2 - 1]
                             + forecast_file_values[n // 2]) / 2
        else:
            median_growth = forecast_file_values[n // 2]

        # --- competitors ---
        all_comps = cur.execute(
            "SELECT latitude, longitude FROM competitors"
        ).fetchall()

        # --- candidates & composite scores ---
        candidates = [
            sid for sid, s in stations.items()
            if s["adjusted_util"] < util_thresh or s["fail_rate"] > fail_thresh
        ]

        flagged = []
        for sid in candidates:
            s = stations[sid]
            comp_count = sum(
                1 for c in all_comps
                if _haversine(s["lat"], s["lon"], c[0], c[1]) <= comp_radius
            )
            ev_growth = forecasts.get(s["region_id"], 0.0)

            ud = max(0.0, (util_thresh - s["adjusted_util"]) / util_thresh)
            fsev = max(0.0, (s["fail_rate"] - fail_thresh) / (1 - fail_thresh))
            cp = min(1.0, comp_count / comp_cap)
            egd = (max(0.0, (median_growth - ev_growth) / median_growth)
                   if median_growth > 0 else 0.0)

            composite = (weights["utilization_deficit"] * ud
                         + weights["failure_severity"] * fsev
                         + weights["competitor_pressure"] * cp
                         + weights["ev_growth_deficit"] * egd)

            if composite >= min_score:
                s["competitor_count"] = comp_count
                s["ev_growth_rate"] = ev_growth
                s["composite_score"] = composite
                s["revenue_loss"] = (
                    (benchmark - s["adjusted_util"])
                    * s["num_chargers"] * annual_hours * rev_per_hour
                )
                flagged.append(s)

        # --- costs ---
        costs: Dict[int, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("station_costs_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        sid = int(row["station_id"])
                        monthly = (float(row["monthly_lease"])
                                   + float(row["electricity_cost"])
                                   + float(row["maintenance_cost"])
                                   + float(row["staff_cost"]))
                        costs[sid] = round(monthly * 12, 2)
        for s in flagged:
            s["annual_operating_cost"] = costs.get(s["station_id"], 0.0)

        flagged.sort(key=lambda x: (-x["composite_score"], x["station_id"]))
        conn.close()
        return flagged

    # ====================================================================
    # STEP — evaluation
    # ====================================================================

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
        expected = self._compute_ground_truth()
        expected_ids = [s["station_id"] for s in expected]
        expected_map = {s["station_id"]: s for s in expected}

        criteria: Dict[str, Dict[str, Any]] = {}

        # ---- 1. File structure (10 pts) ----
        csv_path = os.path.join(self.workspace, "relocation_list.csv")
        required_cols = [
            "station_id", "station_name", "region_name",
            "adjusted_utilization", "failure_rate", "competitor_count",
            "ev_growth_rate", "composite_score",
            "projected_annual_revenue_loss", "annual_operating_cost",
        ]
        submitted_rows = []
        file_ok = False
        if os.path.isfile(csv_path):
            try:
                with open(csv_path, newline="") as f:
                    reader = csv.DictReader(f)
                    if reader.fieldnames and set(required_cols).issubset(
                        set(reader.fieldnames)
                    ):
                        for row in reader:
                            submitted_rows.append(row)
                        file_ok = True
            except Exception:
                pass
        criteria["file_structure"] = {
            "passed": file_ok,
            "score": 10 if file_ok else 0,
            "max_score": 10,
            "reason": "" if file_ok else "relocation_list.csv missing or bad columns",
        }

        # ---- 2. Station identification (20 pts) ----
        submitted_ids = []
        for row in submitted_rows:
            try:
                submitted_ids.append(int(row["station_id"]))
            except (ValueError, KeyError):
                pass
        exp_set = set(expected_ids)
        sub_set = set(submitted_ids)
        union = exp_set | sub_set
        inter = exp_set & sub_set
        id_score = (len(inter) / len(union) * 20) if union else 20.0
        id_score = round(id_score, 2)
        criteria["station_identification"] = {
            "passed": exp_set == sub_set,
            "score": id_score,
            "max_score": 20,
            "reason": "" if exp_set == sub_set else (
                f"expected {sorted(exp_set)}, got {sorted(sub_set)}"
            ),
        }

        # ---- 3. Utilization accuracy (15 pts) ----
        util_matches = 0
        util_total = 0
        for row in submitted_rows:
            sid = int(row.get("station_id", -1))
            if sid in expected_map:
                util_total += 1
                try:
                    val = float(row["adjusted_utilization"])
                    if abs(val - expected_map[sid]["adjusted_util"]) < 0.02:
                        util_matches += 1
                except (ValueError, KeyError):
                    pass
        util_ratio = util_matches / util_total if util_total else 0.0
        util_pts = round(util_ratio * 15, 2)
        criteria["utilization_accuracy"] = {
            "passed": util_ratio == 1.0,
            "score": util_pts,
            "max_score": 15,
            "reason": "" if util_ratio == 1.0 else (
                f"{util_matches}/{util_total} within tolerance"
            ),
        }

        # ---- 4. Composite score accuracy (20 pts) ----
        comp_matches = 0
        comp_total = 0
        for row in submitted_rows:
            sid = int(row.get("station_id", -1))
            if sid in expected_map:
                comp_total += 1
                try:
                    val = float(row["composite_score"])
                    if abs(val - expected_map[sid]["composite_score"]) < 0.02:
                        comp_matches += 1
                except (ValueError, KeyError):
                    pass
        comp_ratio = comp_matches / comp_total if comp_total else 0.0
        comp_pts = round(comp_ratio * 20, 2)
        criteria["composite_score_accuracy"] = {
            "passed": comp_ratio == 1.0,
            "score": comp_pts,
            "max_score": 20,
            "reason": "" if comp_ratio == 1.0 else (
                f"{comp_matches}/{comp_total} within tolerance"
            ),
        }

        # ---- 5. Sort order (15 pts) ----
        order_ok = submitted_ids == expected_ids
        criteria["sort_order"] = {
            "passed": order_ok,
            "score": 15 if order_ok else 0,
            "max_score": 15,
            "reason": "" if order_ok else "Rows not in expected order",
        }

        # ---- 6. Revenue projections (10 pts) ----
        rev_matches = 0
        rev_total = 0
        for row in submitted_rows:
            sid = int(row.get("station_id", -1))
            if sid in expected_map:
                rev_total += 1
                try:
                    val = float(row["projected_annual_revenue_loss"])
                    exp_val = expected_map[sid]["revenue_loss"]
                    tol = max(abs(exp_val) * 0.05, 1.0)
                    if abs(val - exp_val) < tol:
                        rev_matches += 1
                except (ValueError, KeyError):
                    pass
        rev_ratio = rev_matches / rev_total if rev_total else 0.0
        rev_pts = round(rev_ratio * 10, 2)
        criteria["revenue_projections"] = {
            "passed": rev_ratio == 1.0,
            "score": rev_pts,
            "max_score": 10,
            "reason": "" if rev_ratio == 1.0 else (
                f"{rev_matches}/{rev_total} within tolerance"
            ),
        }

        # ---- 7. Response summary (10 pts) ----
        resp_pts = 0
        n_expected = len(expected)
        total_loss = sum(s["revenue_loss"] for s in expected)
        import re
        # Check that the count of flagged stations appears as a standalone number.
        if re.search(rf"(?<!\d){n_expected}(?!\d)", action):
            resp_pts += 4
        # Check that the aggregate revenue loss value appears (within 5%).
        for m in re.finditer(r"([\d][\d,]*\.\d+|[\d][\d,]*)", action):
            try:
                reported = float(m.group(1).replace(",", ""))
                if reported > 0 and abs(reported - total_loss) < max(abs(total_loss) * 0.05, 1.0):
                    resp_pts += 3
                    break
            except ValueError:
                pass
        # Check top-3 station IDs present
        top3_ids = [s["station_id"] for s in expected[:3]]
        if all(str(sid) in action for sid in top3_ids):
            resp_pts += 3

        criteria["response_summary"] = {
            "passed": resp_pts == 10,
            "score": resp_pts,
            "max_score": 10,
            "reason": "" if resp_pts == 10 else "Missing or incorrect summary items",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ====================================================================
    # VERIFY — self-test
    # ====================================================================

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
        # --- Read configuration files ---
        with open(os.path.join(self.workspace, "scoring_config.yaml")) as f:
            cfg = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "revenue_model_params.json")) as f:
            rp = json.load(f)

        util_thresh = cfg["underperformance_thresholds"]["adjusted_utilization_below"]
        fail_thresh = cfg["underperformance_thresholds"]["failure_rate_above"]
        weights = cfg["scoring_weights"]
        comp_radius = cfg["competitor_radius_km"]
        comp_cap = cfg["competitor_cap"]
        min_score = cfg["min_composite_score"]
        benchmark = rp["benchmark_utilization"]
        rev_per_hour = rp["revenue_per_charger_hour"]
        annual_hours = rp["annual_operating_hours"]

        # --- List all stations (paginated) ---
        all_station_ids = []
        page = 1
        while True:
            res = self.tools["list_stations"](page=page, page_size=10)
            for s in res["stations"]:
                all_station_ids.append(s["station_id"])
            if page * 10 >= res["total"]:
                break
            page += 1

        # --- Get details and session stats for every station ---
        station_data: Dict[int, dict] = {}
        for sid in all_station_ids:
            det = self.tools["get_station_details"](station_id=sid)
            stats = self.tools["get_session_stats"](station_id=sid, year=2024)
            station_data[sid] = {**det, **stats}

        # --- Read maintenance downtime from workspace ---
        downtime: Dict[int, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("maintenance_log_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                for block in content.strip().split("---"):
                    block = block.strip()
                    if not block:
                        continue
                    rec: Dict[str, str] = {}
                    for line in block.split("\n"):
                        if ":" in line:
                            k, v = line.split(":", 1)
                            rec[k.strip()] = v.strip()
                    if "Station ID" in rec:
                        sid = int(rec["Station ID"])
                        dh = float(rec["Downtime Hours"])
                        ca = int(rec["Chargers Affected"])
                        downtime[sid] = downtime.get(sid, 0) + dh * ca

        # --- Compute adjusted utilization and failure rate ---
        for sid, d in station_data.items():
            nc = d["num_chargers"]
            ch = d["total_charge_hours"]
            ts = d["total_sessions"]
            fs = d["failed_sessions"]
            avail = nc * annual_hours - downtime.get(sid, 0)
            d["adjusted_util"] = ch / avail if avail > 0 else 0.0
            d["fail_rate"] = fs / ts if ts > 0 else 0.0

        # --- Read EV forecast files ---
        forecasts: Dict[int, float] = {}
        forecast_file_values: List[float] = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("ev_market_forecast_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                for entry in data:
                    val = entry["projected_ev_growth_rate"]
                    forecasts[entry["region_id"]] = val
                    forecast_file_values.append(val)

        # Historical fallback for regions not in forecast files
        for sid, d in station_data.items():
            rid = d["region_id"]
            if rid not in forecasts:
                ev = self.tools["get_regional_ev_data"](region_id=rid)
                t23 = sum(r["vehicle_count"] for r in ev["records"]
                          if r["year"] == 2023)
                t24 = sum(r["vehicle_count"] for r in ev["records"]
                          if r["year"] == 2024)
                forecasts[rid] = (t24 - t23) / t23 if t23 > 0 else 0.0

        # Median from forecast-file values only
        forecast_file_values.sort()
        n = len(forecast_file_values)
        if n == 0:
            median_growth = 0.0
        elif n % 2 == 0:
            median_growth = (forecast_file_values[n // 2 - 1]
                             + forecast_file_values[n // 2]) / 2
        else:
            median_growth = forecast_file_values[n // 2]

        # --- Identify candidates ---
        candidates = [
            sid for sid, d in station_data.items()
            if d["adjusted_util"] < util_thresh or d["fail_rate"] > fail_thresh
        ]

        # --- Composite scores ---
        flagged = []
        for sid in candidates:
            d = station_data[sid]
            comp_res = self.tools["get_nearby_competitors"](
                station_id=sid, radius_km=comp_radius)
            comp_count = comp_res["count"]

            ev_growth = forecasts.get(d["region_id"], 0.0)

            ud = max(0.0, (util_thresh - d["adjusted_util"]) / util_thresh)
            fsev = max(0.0, (d["fail_rate"] - fail_thresh) / (1 - fail_thresh))
            cp = min(1.0, comp_count / comp_cap)
            egd = (max(0.0, (median_growth - ev_growth) / median_growth)
                   if median_growth > 0 else 0.0)

            composite = (weights["utilization_deficit"] * ud
                         + weights["failure_severity"] * fsev
                         + weights["competitor_pressure"] * cp
                         + weights["ev_growth_deficit"] * egd)

            if composite >= min_score:
                d["competitor_count"] = comp_count
                d["ev_growth_rate"] = ev_growth
                d["composite_score"] = composite
                d["revenue_loss"] = (
                    (benchmark - d["adjusted_util"])
                    * d["num_chargers"] * annual_hours * rev_per_hour
                )
                flagged.append(d)

        # --- Read cost data ---
        costs: Dict[int, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("station_costs_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        sid = int(row["station_id"])
                        monthly = (float(row["monthly_lease"])
                                   + float(row["electricity_cost"])
                                   + float(row["maintenance_cost"])
                                   + float(row["staff_cost"]))
                        costs[sid] = round(monthly * 12, 2)

        for d in flagged:
            d["annual_operating_cost"] = costs.get(d["station_id"], 0.0)

        # --- Sort ---
        flagged.sort(key=lambda x: (-x["composite_score"], x["station_id"]))

        # --- Write relocation_list.csv ---
        csv_path = os.path.join(self.workspace, "relocation_list.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "station_id", "station_name", "region_name",
                "adjusted_utilization", "failure_rate", "competitor_count",
                "ev_growth_rate", "composite_score",
                "projected_annual_revenue_loss", "annual_operating_cost",
            ])
            for d in flagged:
                writer.writerow([
                    d["station_id"],
                    d["name"],
                    d["region_name"],
                    f"{d['adjusted_util']:.4f}",
                    f"{d['fail_rate']:.4f}",
                    d["competitor_count"],
                    f"{d['ev_growth_rate']:.4f}",
                    f"{d['composite_score']:.4f}",
                    f"{d['revenue_loss']:.2f}",
                    f"{d['annual_operating_cost']:.2f}",
                ])

        # --- Build action string ---
        total_loss = sum(d["revenue_loss"] for d in flagged)
        top3 = flagged[:3]
        top3_text = "; ".join(
            f"Station {d['station_id']} ({d['name']}): {d['composite_score']:.4f}"
            for d in top3
        )
        action = (
            f"Total stations flagged: {len(flagged)}\n"
            f"Total projected annual revenue loss: ${total_loss:.2f}\n"
            f"Top 3 stations by composite score: {top3_text}"
        )

        return self.step(action)
