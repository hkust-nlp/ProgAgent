import sqlite3
import os
import json
import csv
import math
from typing import Tuple, Dict, List, Any
from datetime import datetime, timedelta


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
        }
        return func
    return decorator


BASE_TIME = datetime(2026, 4, 25, 6, 0, 0)


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
    # TOOLS
    # ====================================================================

    @tool(
        description="List deliveries with optional status filter. Returns a paginated list.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status (e.g. 'pending', 'completed', 'cancelled'). Omit to list all."
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1."
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Default 20."
                }
            },
            "required": []
        }
    )
    def list_deliveries(self, status: str = None, page: int = 1, page_size: int = 20) -> dict:
        conn = sqlite3.connect(self.db_path)
        base = "FROM deliveries"
        params: list = []
        if status:
            base += " WHERE status = ?"
            params.append(status)
        total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT delivery_id, truck_id, driver_id, priority, status {base} "
            f"ORDER BY delivery_id LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size]
        ).fetchall()
        conn.close()
        return {
            "deliveries": [
                {"delivery_id": r[0], "truck_id": r[1], "driver_id": r[2],
                 "priority": r[3], "status": r[4]}
                for r in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    @tool(
        description="Get full details for a single delivery including origin/destination location names and deadline.",
        parameters={
            "type": "object",
            "properties": {
                "delivery_id": {"type": "string", "description": "The delivery identifier, e.g. DEL_0001"}
            },
            "required": ["delivery_id"]
        }
    )
    def get_delivery(self, delivery_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT d.delivery_id, d.truck_id, d.driver_id, "
            "d.origin_location_id, lo.name, d.destination_location_id, ld.name, "
            "d.deadline, d.priority, d.status, d.cargo_description "
            "FROM deliveries d "
            "JOIN locations lo ON d.origin_location_id = lo.location_id "
            "JOIN locations ld ON d.destination_location_id = ld.location_id "
            "WHERE d.delivery_id = ?", (delivery_id,)
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"Delivery {delivery_id} not found"}
        return {
            "delivery_id": row[0], "truck_id": row[1], "driver_id": row[2],
            "origin_location_id": row[3], "origin_name": row[4],
            "destination_location_id": row[5], "destination_name": row[6],
            "deadline": row[7], "priority": row[8], "status": row[9],
            "cargo_description": row[10],
        }

    @tool(
        description="Get specifications of a truck (battery capacity, base efficiency, model, status).",
        parameters={
            "type": "object",
            "properties": {
                "truck_id": {"type": "string", "description": "Truck identifier, e.g. TRK_0001"}
            },
            "required": ["truck_id"]
        }
    )
    def get_truck(self, truck_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT truck_id, model, battery_capacity_kwh, base_efficiency_kwh_per_mile, status "
            "FROM trucks WHERE truck_id = ?", (truck_id,)
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"Truck {truck_id} not found"}
        return {
            "truck_id": row[0], "model": row[1],
            "battery_capacity_kwh": row[2],
            "base_efficiency_kwh_per_mile": row[3],
            "status": row[4],
        }

    @tool(
        description="Get driver information (name, license class, status).",
        parameters={
            "type": "object",
            "properties": {
                "driver_id": {"type": "string", "description": "Driver identifier, e.g. DRV_0001"}
            },
            "required": ["driver_id"]
        }
    )
    def get_driver(self, driver_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT driver_id, name, license_class, hire_date, status "
            "FROM drivers WHERE driver_id = ?", (driver_id,)
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"Driver {driver_id} not found"}
        return {
            "driver_id": row[0], "name": row[1],
            "license_class": row[2], "hire_date": row[3],
            "status": row[4],
        }

    @tool(
        description="Get ordered route segments for a delivery (paginated). Each segment includes from/to location IDs and names, distance, and terrain type.",
        parameters={
            "type": "object",
            "properties": {
                "delivery_id": {"type": "string", "description": "Delivery identifier"},
                "page": {"type": "integer", "description": "Page number (1-indexed). Default 1."},
                "page_size": {"type": "integer", "description": "Results per page. Default 50."}
            },
            "required": ["delivery_id"]
        }
    )
    def get_route_segments(self, delivery_id: str, page: int = 1, page_size: int = 50) -> dict:
        conn = sqlite3.connect(self.db_path)
        total = conn.execute(
            "SELECT COUNT(*) FROM route_segments WHERE delivery_id = ?", (delivery_id,)
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT rs.segment_id, rs.segment_order, "
            "rs.from_location_id, lf.name, rs.to_location_id, lt.name, "
            "rs.distance_miles, rs.terrain_type "
            "FROM route_segments rs "
            "JOIN locations lf ON rs.from_location_id = lf.location_id "
            "JOIN locations lt ON rs.to_location_id = lt.location_id "
            "WHERE rs.delivery_id = ? ORDER BY rs.segment_order "
            "LIMIT ? OFFSET ?",
            (delivery_id, page_size, (page - 1) * page_size)
        ).fetchall()
        conn.close()
        return {
            "segments": [
                {
                    "segment_id": r[0], "segment_order": r[1],
                    "from_location_id": r[2], "from_location_name": r[3],
                    "to_location_id": r[4], "to_location_name": r[5],
                    "distance_miles": r[6], "terrain_type": r[7],
                }
                for r in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    @tool(
        description="Find all charging stations at a given location. Returns station details including charge rate and current wait time.",
        parameters={
            "type": "object",
            "properties": {
                "location_id": {"type": "string", "description": "Location identifier, e.g. L0005"}
            },
            "required": ["location_id"]
        }
    )
    def find_stations_at_location(self, location_id: str) -> list:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT station_id, name, charger_type, charge_rate_kw, "
            "num_ports, occupied_ports, estimated_wait_min "
            "FROM charging_stations WHERE location_id = ? ORDER BY station_id",
            (location_id,)
        ).fetchall()
        conn.close()
        return [
            {
                "station_id": r[0], "name": r[1], "charger_type": r[2],
                "charge_rate_kw": r[3], "num_ports": r[4],
                "occupied_ports": r[5], "estimated_wait_min": r[6],
            }
            for r in rows
        ]

    @tool(
        description="Get full details of a single charging station.",
        parameters={
            "type": "object",
            "properties": {
                "station_id": {"type": "string", "description": "Station identifier, e.g. STN_0001"}
            },
            "required": ["station_id"]
        }
    )
    def get_station(self, station_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT s.station_id, s.location_id, l.name, s.name, s.charger_type, "
            "s.charge_rate_kw, s.num_ports, s.occupied_ports, s.estimated_wait_min "
            "FROM charging_stations s JOIN locations l ON s.location_id = l.location_id "
            "WHERE s.station_id = ?", (station_id,)
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"Station {station_id} not found"}
        return {
            "station_id": row[0], "location_id": row[1],
            "location_name": row[2], "station_name": row[3],
            "charger_type": row[4], "charge_rate_kw": row[5],
            "num_ports": row[6], "occupied_ports": row[7],
            "estimated_wait_min": row[8],
        }

    @tool(
        description="Get details of a location (name, coordinates).",
        parameters={
            "type": "object",
            "properties": {
                "location_id": {"type": "string", "description": "Location identifier, e.g. L0001"}
            },
            "required": ["location_id"]
        }
    )
    def get_location(self, location_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT location_id, name, latitude, longitude FROM locations WHERE location_id = ?",
            (location_id,)
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"Location {location_id} not found"}
        return {
            "location_id": row[0], "name": row[1],
            "latitude": row[2], "longitude": row[3],
        }

    # ====================================================================
    # HELPERS
    # ====================================================================

    def _read_configs(self):
        """Read all workspace config files and return a unified config dict."""
        # charging policy
        with open(os.path.join(self.workspace, "charging_policy.json")) as f:
            cpol = json.load(f)

        # efficiency factors
        terrain_factors = {}
        terrain_speeds = {}
        with open(os.path.join(self.workspace, "efficiency_factors.csv")) as f:
            for row in csv.DictReader(f):
                terrain_factors[row["terrain_type"]] = float(row["energy_factor"])
                terrain_speeds[row["terrain_type"]] = float(row["avg_speed_mph"])

        # HOS regulations
        hos = {}
        with open(os.path.join(self.workspace, "hos_regulations.yaml")) as f:
            for line in f:
                line = line.strip()
                if ":" in line and not line.startswith("notes") and not line.startswith("#"):
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if val.lower() == "true":
                        hos[key] = True
                    elif val.lower() == "false":
                        hos[key] = False
                    elif val == ">":
                        continue
                    else:
                        try:
                            hos[key] = float(val)
                        except ValueError:
                            hos[key] = val

        # weight factors
        weight_brackets = []
        with open(os.path.join(self.workspace, "weight_factors.md")) as f:
            for line in f:
                line = line.strip()
                if line.startswith("|") and not line.startswith("| Max") and not line.startswith("|--"):
                    parts = [p.strip() for p in line.split("|") if p.strip()]
                    if len(parts) >= 2:
                        try:
                            weight_brackets.append((int(parts[0]), float(parts[1])))
                        except ValueError:
                            pass

        return {
            "min_soc_pct": cpol["min_soc_pct"],
            "target_charge_soc_pct": cpol["target_charge_soc_pct"],
            "station_selection_rule": cpol.get("station_selection_rule", ""),
            "terrain_factors": terrain_factors,
            "terrain_speeds": terrain_speeds,
            "max_continuous_driving_hours": hos.get("max_continuous_driving_hours", 8.0),
            "mandatory_rest_minutes": int(hos.get("mandatory_rest_minutes", 30)),
            "rest_during_charging": hos.get("rest_during_charging", True),
            "weight_brackets": weight_brackets,
        }

    @staticmethod
    def _get_weight_factor(weight_lbs, brackets):
        for mw, fac in brackets:
            if weight_lbs <= mw:
                return fac
        return 1.50

    def _read_telemetry(self, truck_id):
        """Read latest telemetry for a truck: returns (soc_pct, cargo_weight_lbs)."""
        fp = os.path.join(self.workspace, f"telemetry_{truck_id}.csv")
        with open(fp) as f:
            rows = list(csv.DictReader(f))
        last = rows[-1]
        return float(last["soc_pct"]), int(last["cargo_weight_lbs"])

    def _read_hos_log(self, driver_id):
        """Read HOS log for a driver: returns continuous_driving_hours."""
        fp = os.path.join(self.workspace, f"hos_log_{driver_id}.txt")
        cont_h = 0.0
        with open(fp) as f:
            for line in f:
                if "continuous_driving_hours:" in line:
                    cont_h = float(line.split(":")[1].strip())
                    break
        return cont_h

    def _compute_schedule(self):
        """Compute the expected charge-stop schedule using direct DB + workspace access."""
        cfg = self._read_configs()
        conn = sqlite3.connect(self.db_path)

        pending = conn.execute(
            "SELECT delivery_id, truck_id, driver_id, deadline "
            "FROM deliveries WHERE status = 'pending' ORDER BY delivery_id"
        ).fetchall()

        all_stops = []
        delivery_summaries = {}

        for del_id, truck_id, driver_id, deadline_str in pending:
            # Truck specs
            truck = conn.execute(
                "SELECT battery_capacity_kwh, base_efficiency_kwh_per_mile FROM trucks WHERE truck_id = ?",
                (truck_id,)
            ).fetchone()
            capacity = truck[0]
            base_eff = truck[1]

            # Telemetry
            soc, cargo_weight = self._read_telemetry(truck_id)

            # Driver HOS
            cont_h = self._read_hos_log(driver_id)

            # Segments
            segs = conn.execute(
                "SELECT rs.from_location_id, lf.name, rs.to_location_id, lt.name, "
                "rs.distance_miles, rs.terrain_type "
                "FROM route_segments rs "
                "JOIN locations lf ON rs.from_location_id = lf.location_id "
                "JOIN locations lt ON rs.to_location_id = lt.location_id "
                "WHERE rs.delivery_id = ? ORDER BY rs.segment_order",
                (del_id,)
            ).fetchall()

            wf = self._get_weight_factor(cargo_weight, cfg["weight_brackets"])
            current_soc = soc
            continuous = cont_h
            current_time = BASE_TIME
            cum_dist = 0.0
            stop_num = 0
            stops = []

            for seg in segs:
                from_loc_id, from_name, to_loc_id, to_name, dist, terrain = seg
                tf = cfg["terrain_factors"][terrain]
                speed = cfg["terrain_speeds"][terrain]
                eff = base_eff * tf * wf
                energy = dist * eff
                soc_drop = energy / capacity * 100.0
                soc_after = current_soc - soc_drop
                drive_h = dist / speed

                need_charge = soc_after < cfg["min_soc_pct"]
                need_rest = continuous + drive_h > cfg["max_continuous_driving_hours"]

                if need_charge or need_rest:
                    stop_num += 1
                    arrival_soc = current_soc
                    departure_soc = current_soc
                    charge_dur = 0
                    rest_dur = 0
                    station_id = ""

                    if need_charge:
                        # find station at from_loc_id
                        st_rows = conn.execute(
                            "SELECT station_id, charge_rate_kw, estimated_wait_min "
                            "FROM charging_stations WHERE location_id = ? "
                            "ORDER BY estimated_wait_min ASC, station_id ASC",
                            (from_loc_id,)
                        ).fetchall()
                        if st_rows:
                            best = st_rows[0]
                            station_id = best[0]
                            rate = best[1]
                            wait = best[2]
                            charge_kwh = (cfg["target_charge_soc_pct"] - current_soc) / 100.0 * capacity
                            charge_time = charge_kwh / rate * 60.0
                            charge_dur = round(charge_time + wait)
                            departure_soc = cfg["target_charge_soc_pct"]

                    if need_rest:
                        rest_dur = cfg["mandatory_rest_minutes"]

                    if need_charge and need_rest:
                        stype = "charge_and_rest"
                    elif need_charge:
                        stype = "charge"
                    else:
                        stype = "rest"

                    if need_charge and need_rest and cfg["rest_during_charging"]:
                        total_stop = max(charge_dur, rest_dur)
                    elif need_charge and need_rest:
                        total_stop = charge_dur + rest_dur
                    elif need_charge:
                        total_stop = charge_dur
                    else:
                        total_stop = rest_dur

                    stops.append({
                        "delivery_id": del_id,
                        "truck_id": truck_id,
                        "driver_id": driver_id,
                        "stop_number": stop_num,
                        "stop_type": stype,
                        "location_id": from_loc_id,
                        "location_name": from_name,
                        "station_id": station_id,
                        "arrival_soc_pct": round(arrival_soc, 1),
                        "departure_soc_pct": round(departure_soc, 1),
                        "charge_duration_min": charge_dur,
                        "rest_duration_min": rest_dur,
                        "cumulative_distance_miles": round(cum_dist, 1),
                        "estimated_arrival_iso": current_time.strftime("%Y-%m-%dT%H:%M:%S"),
                    })

                    current_soc = departure_soc
                    current_time += timedelta(minutes=total_stop)
                    if need_rest:
                        continuous = 0.0

                # Drive the segment
                current_soc -= soc_drop
                continuous += drive_h
                current_time += timedelta(hours=drive_h)
                cum_dist += dist

            deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%dT%H:%M:%S")
            meets = "yes" if current_time <= deadline_dt else "no"
            total_charge = sum(s["charge_duration_min"] for s in stops)
            total_rest = sum(s["rest_duration_min"] for s in stops)

            delivery_summaries[del_id] = {
                "truck_id": truck_id,
                "total_stops": len(stops),
                "total_charge_min": total_charge,
                "total_rest_min": total_rest,
                "arrival_time": current_time.strftime("%Y-%m-%dT%H:%M:%S"),
                "meets_deadline": meets,
            }
            all_stops.extend(stops)

        conn.close()
        return all_stops, delivery_summaries

    # ====================================================================
    # STEP
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
        expected_stops, expected_summaries = self._compute_schedule()

        criteria = {}

        # ---- 1. File format (10 pts) ----
        csv_path = os.path.join(self.workspace, "charge_stop_schedule.csv")
        required_cols = [
            "delivery_id", "truck_id", "driver_id", "stop_number", "stop_type",
            "location_id", "location_name", "station_id",
            "arrival_soc_pct", "departure_soc_pct",
            "charge_duration_min", "rest_duration_min",
            "cumulative_distance_miles", "estimated_arrival_iso",
        ]
        agent_rows = []
        if os.path.exists(csv_path):
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                agent_rows = list(reader)
            missing = [c for c in required_cols if c not in headers]
            if not missing:
                criteria["file_format"] = {"passed": True, "score": 10, "max_score": 10}
            else:
                criteria["file_format"] = {"passed": False, "score": 0, "max_score": 10,
                                           "reason": f"Missing columns: {missing}"}
        else:
            criteria["file_format"] = {"passed": False, "score": 0, "max_score": 10,
                                       "reason": "charge_stop_schedule.csv not found"}

        # ---- 2. Delivery coverage (15 pts) ----
        expected_del_ids = sorted(expected_summaries.keys())
        agent_del_ids = sorted(set(r.get("delivery_id", "") for r in agent_rows))
        covered = [d for d in expected_del_ids if d in agent_del_ids]
        if len(expected_del_ids) > 0:
            cov_ratio = len(covered) / len(expected_del_ids)
        else:
            cov_ratio = 1.0
        cov_score = round(15 * cov_ratio)
        criteria["delivery_coverage"] = {
            "passed": cov_ratio == 1.0,
            "score": cov_score,
            "max_score": 15,
            "reason": "" if cov_ratio == 1.0 else f"Missing deliveries: {set(expected_del_ids) - set(agent_del_ids)}"
        }

        # ---- 3. Stop correctness (25 pts) ----
        # For each delivery: correct number of stops and correct stop locations
        exp_by_del = {}
        for s in expected_stops:
            exp_by_del.setdefault(s["delivery_id"], []).append(s)
        agent_by_del = {}
        for r in agent_rows:
            agent_by_del.setdefault(r.get("delivery_id", ""), []).append(r)

        stop_correct = 0
        stop_total = max(len(expected_del_ids), 1)
        for del_id in expected_del_ids:
            exp_list = exp_by_del.get(del_id, [])
            agt_list = agent_by_del.get(del_id, [])
            if len(exp_list) == len(agt_list):
                # Check locations match in order
                match = True
                for e, a in zip(exp_list, agt_list):
                    if a.get("location_id", "") != e["location_id"]:
                        match = False
                        break
                    if a.get("stop_type", "") != e["stop_type"]:
                        match = False
                        break
                if match:
                    stop_correct += 1
        stop_score = round(25 * stop_correct / stop_total)
        criteria["stop_correctness"] = {
            "passed": stop_correct == stop_total,
            "score": stop_score,
            "max_score": 25,
            "reason": "" if stop_correct == stop_total else f"{stop_correct}/{stop_total} deliveries with correct stops"
        }

        # ---- 4. SoC accuracy (20 pts) ----
        soc_ok = 0
        soc_total = max(len(expected_stops), 1)
        for exp in expected_stops:
            del_id = exp["delivery_id"]
            stop_n = exp["stop_number"]
            agt_list = agent_by_del.get(del_id, [])
            agt = None
            for a in agt_list:
                try:
                    if int(a.get("stop_number", -1)) == stop_n:
                        agt = a
                        break
                except (ValueError, TypeError):
                    pass
            if agt:
                try:
                    a_soc = float(agt.get("arrival_soc_pct", -999))
                    d_soc = float(agt.get("departure_soc_pct", -999))
                    if (abs(a_soc - exp["arrival_soc_pct"]) <= 1.0 and
                            abs(d_soc - exp["departure_soc_pct"]) <= 1.0):
                        soc_ok += 1
                except (ValueError, TypeError):
                    pass
        soc_score = round(20 * soc_ok / soc_total)
        criteria["soc_accuracy"] = {
            "passed": soc_ok == soc_total,
            "score": soc_score,
            "max_score": 20,
            "reason": "" if soc_ok == soc_total else f"{soc_ok}/{soc_total} stops with correct SoC"
        }

        # ---- 5. Charge duration accuracy (15 pts) ----
        dur_ok = 0
        dur_total = max(len(expected_stops), 1)
        for exp in expected_stops:
            del_id = exp["delivery_id"]
            stop_n = exp["stop_number"]
            agt_list = agent_by_del.get(del_id, [])
            agt = None
            for a in agt_list:
                try:
                    if int(a.get("stop_number", -1)) == stop_n:
                        agt = a
                        break
                except (ValueError, TypeError):
                    pass
            if agt:
                try:
                    a_cd = int(round(float(agt.get("charge_duration_min", -999))))
                    a_rd = int(round(float(agt.get("rest_duration_min", -999))))
                    if abs(a_cd - exp["charge_duration_min"]) <= 2 and abs(a_rd - exp["rest_duration_min"]) <= 1:
                        dur_ok += 1
                except (ValueError, TypeError):
                    pass
        dur_score = round(15 * dur_ok / dur_total)
        criteria["duration_accuracy"] = {
            "passed": dur_ok == dur_total,
            "score": dur_score,
            "max_score": 15,
            "reason": "" if dur_ok == dur_total else f"{dur_ok}/{dur_total} stops with correct durations"
        }

        # ---- 6. Summary response (15 pts) ----
        summary_ok = 0
        summary_total = max(len(expected_del_ids), 1)
        for del_id in expected_del_ids:
            exp_s = expected_summaries[del_id]
            # Look for line in action containing del_id and pipe-separated fields
            found = False
            for line in action.split("\n"):
                if del_id in line and "|" in line:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 7:
                        try:
                            a_del = parts[0]
                            a_trk = parts[1]
                            a_stops = int(parts[2])
                            a_charge = int(parts[3])
                            a_rest = int(parts[4])
                            a_arrival = parts[5]
                            a_meets = parts[6].lower().strip()
                            if (a_del == del_id and
                                    a_trk == exp_s["truck_id"] and
                                    a_stops == exp_s["total_stops"] and
                                    abs(a_charge - exp_s["total_charge_min"]) <= 2 and
                                    abs(a_rest - exp_s["total_rest_min"]) <= 1 and
                                    a_meets == exp_s["meets_deadline"]):
                                found = True
                        except (ValueError, IndexError):
                            pass
                    break
            if found:
                summary_ok += 1
        sum_score = round(15 * summary_ok / summary_total)
        criteria["summary_response"] = {
            "passed": summary_ok == summary_total,
            "score": sum_score,
            "max_score": 15,
            "reason": "" if summary_ok == summary_total else f"{summary_ok}/{summary_total} correct summaries"
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ====================================================================
    # VERIFY
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
        # --- Read config files ---
        cfg = self._read_configs()

        # --- Get pending deliveries via tools ---
        result = self.tools["list_deliveries"](status="pending", page=1, page_size=200)
        deliveries = result["deliveries"]

        all_stops = []
        summaries = []

        for del_info in deliveries:
            del_id = del_info["delivery_id"]
            truck_id = del_info["truck_id"]
            driver_id = del_info["driver_id"]

            # Tool calls: get_delivery, get_truck, get_driver
            delivery = self.tools["get_delivery"](delivery_id=del_id)
            truck = self.tools["get_truck"](truck_id=truck_id)
            driver = self.tools["get_driver"](driver_id=driver_id)

            capacity = truck["battery_capacity_kwh"]
            base_eff = truck["base_efficiency_kwh_per_mile"]
            deadline_str = delivery["deadline"]

            # Read telemetry file
            soc, cargo_weight = self._read_telemetry(truck_id)

            # Read HOS log
            cont_h = self._read_hos_log(driver_id)

            # Get route segments via tool
            seg_result = self.tools["get_route_segments"](delivery_id=del_id, page=1, page_size=200)
            segments = seg_result["segments"]

            wf = self._get_weight_factor(cargo_weight, cfg["weight_brackets"])
            current_soc = soc
            continuous = cont_h
            current_time = BASE_TIME
            cum_dist = 0.0
            stop_num = 0
            stops = []

            for seg in segments:
                from_loc_id = seg["from_location_id"]
                from_name = seg["from_location_name"]
                dist = seg["distance_miles"]
                terrain = seg["terrain_type"]

                tf = cfg["terrain_factors"][terrain]
                speed = cfg["terrain_speeds"][terrain]
                eff = base_eff * tf * wf
                energy = dist * eff
                soc_drop = energy / capacity * 100.0
                soc_after = current_soc - soc_drop
                drive_h = dist / speed

                need_charge = soc_after < cfg["min_soc_pct"]
                need_rest = continuous + drive_h > cfg["max_continuous_driving_hours"]

                if need_charge or need_rest:
                    stop_num += 1
                    arrival_soc = current_soc
                    departure_soc = current_soc
                    charge_dur = 0
                    rest_dur = 0
                    station_id = ""

                    if need_charge:
                        # Use tool to find stations at this location
                        station_list = self.tools["find_stations_at_location"](location_id=from_loc_id)
                        # Sort by wait time then station_id
                        station_list.sort(key=lambda x: (x["estimated_wait_min"], x["station_id"]))
                        if station_list:
                            best = station_list[0]
                            station_id = best["station_id"]
                            rate = best["charge_rate_kw"]
                            wait = best["estimated_wait_min"]
                            charge_kwh = (cfg["target_charge_soc_pct"] - current_soc) / 100.0 * capacity
                            charge_time = charge_kwh / rate * 60.0
                            charge_dur = round(charge_time + wait)
                            departure_soc = cfg["target_charge_soc_pct"]

                    if need_rest:
                        rest_dur = cfg["mandatory_rest_minutes"]

                    if need_charge and need_rest:
                        stype = "charge_and_rest"
                    elif need_charge:
                        stype = "charge"
                    else:
                        stype = "rest"

                    if need_charge and need_rest and cfg["rest_during_charging"]:
                        total_stop = max(charge_dur, rest_dur)
                    elif need_charge and need_rest:
                        total_stop = charge_dur + rest_dur
                    elif need_charge:
                        total_stop = charge_dur
                    else:
                        total_stop = rest_dur

                    stops.append({
                        "delivery_id": del_id,
                        "truck_id": truck_id,
                        "driver_id": driver_id,
                        "stop_number": stop_num,
                        "stop_type": stype,
                        "location_id": from_loc_id,
                        "location_name": from_name,
                        "station_id": station_id,
                        "arrival_soc_pct": round(arrival_soc, 1),
                        "departure_soc_pct": round(departure_soc, 1),
                        "charge_duration_min": charge_dur,
                        "rest_duration_min": rest_dur,
                        "cumulative_distance_miles": round(cum_dist, 1),
                        "estimated_arrival_iso": current_time.strftime("%Y-%m-%dT%H:%M:%S"),
                    })

                    current_soc = departure_soc
                    current_time += timedelta(minutes=total_stop)
                    if need_rest:
                        continuous = 0.0

                # Drive the segment
                current_soc -= soc_drop
                continuous += drive_h
                current_time += timedelta(hours=drive_h)
                cum_dist += dist

            all_stops.extend(stops)

            deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%dT%H:%M:%S")
            meets = "yes" if current_time <= deadline_dt else "no"
            total_charge = sum(s["charge_duration_min"] for s in stops)
            total_rest = sum(s["rest_duration_min"] for s in stops)

            summaries.append(
                f"{del_id} | {truck_id} | {len(stops)} | {total_charge} | "
                f"{total_rest} | {current_time.strftime('%Y-%m-%dT%H:%M:%S')} | {meets}"
            )

        # --- Write CSV ---
        csv_path = os.path.join(self.workspace, "charge_stop_schedule.csv")
        fieldnames = [
            "delivery_id", "truck_id", "driver_id", "stop_number", "stop_type",
            "location_id", "location_name", "station_id",
            "arrival_soc_pct", "departure_soc_pct",
            "charge_duration_min", "rest_duration_min",
            "cumulative_distance_miles", "estimated_arrival_iso",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_stops)

        # --- Build action string ---
        action = "DELIVERY SCHEDULE SUMMARY\n"
        action += "delivery_id | truck_id | total_stops | total_charge_min | total_rest_min | arrival_time | meets_deadline\n"
        for s in summaries:
            action += s + "\n"

        return self.step(action)
