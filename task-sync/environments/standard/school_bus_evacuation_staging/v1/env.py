"""
School Bus Evacuation Staging - Environment
"""
import json
import os
import csv
import glob
import math
import sqlite3
import yaml
import pandas as pd
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

    # ------------------------------------------------------------------
    #  TOOLS
    # ------------------------------------------------------------------

    @tool(
        description="List schools with pagination. Returns school_id, name, zone_id, lat, lon, and address for each school on the requested page.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                    "default": 1
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of schools per page (max 10)",
                    "default": 10
                }
            },
            "required": []
        }
    )
    def list_schools(self, page: int = 1, page_size: int = 10) -> dict:
        page_size = min(page_size, 10)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM schools ORDER BY school_id LIMIT ? OFFSET ?",
            (page_size, offset)).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM schools").fetchone()[0]
        conn.close()
        return {
            "schools": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size)
        }

    @tool(
        description="Get detailed information for a single school by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "school_id": {
                    "type": "integer",
                    "description": "The school ID to look up"
                }
            },
            "required": ["school_id"]
        }
    )
    def get_school_details(self, school_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM schools WHERE school_id=?",
                           (school_id,)).fetchone()
        student_count = conn.execute(
            "SELECT COUNT(*) FROM students WHERE school_id=?",
            (school_id,)).fetchone()[0]
        special_count = conn.execute(
            "SELECT COUNT(*) FROM students WHERE school_id=? AND special_needs=1",
            (school_id,)).fetchone()[0]
        conn.close()
        if not row:
            return {"error": f"School {school_id} not found"}
        d = dict(row)
        d["student_count"] = student_count
        d["special_needs_count"] = special_count
        return d

    @tool(
        description="List students enrolled at a given school, with pagination. Returns student_id, name, grade, home_lat, home_lon, special_needs for each student.",
        parameters={
            "type": "object",
            "properties": {
                "school_id": {
                    "type": "integer",
                    "description": "The school ID"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                    "default": 1
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 20)",
                    "default": 20
                }
            },
            "required": ["school_id"]
        }
    )
    def get_students_by_school(self, school_id: int, page: int = 1,
                               page_size: int = 20) -> dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM students WHERE school_id=? ORDER BY student_id "
            "LIMIT ? OFFSET ?", (school_id, page_size, offset)).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM students WHERE school_id=?",
            (school_id,)).fetchone()[0]
        conn.close()
        return {
            "students": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if total else 0
        }

    @tool(
        description="List all buses with pagination. Returns bus_id, plate_number, capacity, empty_weight_tons, depot_zone_id, and wheelchair_accessible.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                    "default": 1
                },
                "page_size": {
                    "type": "integer",
                    "description": "Buses per page (max 10)",
                    "default": 10
                }
            },
            "required": []
        }
    )
    def list_buses(self, page: int = 1, page_size: int = 10) -> dict:
        page_size = min(page_size, 10)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM buses ORDER BY bus_id LIMIT ? OFFSET ?",
            (page_size, offset)).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM buses").fetchone()[0]
        conn.close()
        return {
            "buses": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size)
        }

    @tool(
        description="Get specifications for a single bus by its ID. Returns plate_number, capacity, empty_weight_tons, depot_zone_id, wheelchair_accessible.",
        parameters={
            "type": "object",
            "properties": {
                "bus_id": {
                    "type": "integer",
                    "description": "The bus ID"
                }
            },
            "required": ["bus_id"]
        }
    )
    def get_bus_specs(self, bus_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM buses WHERE bus_id=?",
                           (bus_id,)).fetchone()
        conn.close()
        if not row:
            return {"error": f"Bus {bus_id} not found"}
        return dict(row)

    @tool(
        description="List shelters with pagination. Returns shelter_id, name, lat, lon, base_capacity, medical_facility, wheelchair_accessible, address.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                    "default": 1
                },
                "page_size": {
                    "type": "integer",
                    "description": "Shelters per page (max 10)",
                    "default": 10
                }
            },
            "required": []
        }
    )
    def list_shelters(self, page: int = 1, page_size: int = 10) -> dict:
        page_size = min(page_size, 10)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM shelters ORDER BY shelter_id LIMIT ? OFFSET ?",
            (page_size, offset)).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM shelters").fetchone()[0]
        conn.close()
        return {
            "shelters": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size)
        }

    @tool(
        description="Get detailed information about a single shelter by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "shelter_id": {
                    "type": "integer",
                    "description": "The shelter ID"
                }
            },
            "required": ["shelter_id"]
        }
    )
    def get_shelter_details(self, shelter_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM shelters WHERE shelter_id=?",
                           (shelter_id,)).fetchone()
        conn.close()
        if not row:
            return {"error": f"Shelter {shelter_id} not found"}
        return dict(row)

    @tool(
        description="Retrieve the pre-computed route from a school to a shelter. Returns route_id, segment_ids (JSON list), total_distance_km, estimated_travel_min. Returns an error if no route exists between the pair.",
        parameters={
            "type": "object",
            "properties": {
                "school_id": {
                    "type": "integer",
                    "description": "Origin school ID"
                },
                "shelter_id": {
                    "type": "integer",
                    "description": "Destination shelter ID"
                }
            },
            "required": ["school_id", "shelter_id"]
        }
    )
    def get_route(self, school_id: int, shelter_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM routes WHERE school_id=? AND shelter_id=?",
            (school_id, shelter_id)).fetchone()
        conn.close()
        if not row:
            return {"error": f"No route from school {school_id} to shelter {shelter_id}"}
        d = dict(row)
        d["segment_ids"] = json.loads(d["segment_ids"])
        return d

    @tool(
        description="List all available routes from a given school. Returns a list of route summaries with shelter_id, total_distance_km, estimated_travel_min.",
        parameters={
            "type": "object",
            "properties": {
                "school_id": {
                    "type": "integer",
                    "description": "The school ID"
                }
            },
            "required": ["school_id"]
        }
    )
    def list_routes_from_school(self, school_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT route_id, shelter_id, total_distance_km, estimated_travel_min "
            "FROM routes WHERE school_id=? ORDER BY total_distance_km",
            (school_id,)).fetchall()
        conn.close()
        return {"school_id": school_id, "routes": [dict(r) for r in rows]}

    @tool(
        description="Get details for a single road segment by its ID. Returns segment_id, road_name, distance_km, has_bridge, bridge_weight_limit_tons.",
        parameters={
            "type": "object",
            "properties": {
                "segment_id": {
                    "type": "integer",
                    "description": "The road segment ID"
                }
            },
            "required": ["segment_id"]
        }
    )
    def get_segment_info(self, segment_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM road_segments WHERE segment_id=?",
                           (segment_id,)).fetchone()
        conn.close()
        if not row:
            return {"error": f"Segment {segment_id} not found"}
        return dict(row)

    # ------------------------------------------------------------------
    #  STEP  — evaluation
    # ------------------------------------------------------------------

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        criteria = {}
        max_total = 0

        # ---- helpers ----
        def _add(name, passed, score, max_score, reason=""):
            criteria[name] = {
                "passed": passed, "score": score,
                "max_score": max_score, "reason": reason}

        # ---- ground truth computation ----
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # all schools
        all_schools = [dict(r) for r in conn.execute("SELECT * FROM schools ORDER BY school_id").fetchall()]
        # all students
        all_students = [dict(r) for r in conn.execute("SELECT * FROM students ORDER BY student_id").fetchall()]
        # all buses
        all_buses = [dict(r) for r in conn.execute("SELECT * FROM buses ORDER BY bus_id").fetchall()]
        # all shelters
        all_shelters = [dict(r) for r in conn.execute("SELECT * FROM shelters ORDER BY shelter_id").fetchall()]
        # all segments
        all_segments = {r["segment_id"]: dict(r) for r in conn.execute("SELECT * FROM road_segments").fetchall()}
        # all routes
        all_routes = []
        for r in conn.execute("SELECT * FROM routes").fetchall():
            d = dict(r)
            d["segment_ids"] = json.loads(d["segment_ids"])
            all_routes.append(d)
        conn.close()

        # maps
        school_map = {s["school_id"]: s for s in all_schools}
        shelter_map = {s["shelter_id"]: s for s in all_shelters}
        bus_map = {b["bus_id"]: b for b in all_buses}
        school_name_to_id = {s["name"]: s["school_id"] for s in all_schools}
        shelter_name_to_id = {s["name"]: s["shelter_id"] for s in all_shelters}

        students_by_school = {}
        for st in all_students:
            students_by_school.setdefault(st["school_id"], []).append(st)

        # read workspace config
        policy_path = os.path.join(self.workspace, "evacuation_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)

        shelter_status_path = os.path.join(self.workspace, "shelter_status.json")
        with open(shelter_status_path) as f:
            shelter_adj = json.load(f)

        bridge_updates_path = os.path.join(self.workspace, "bridge_weight_updates.json")
        with open(bridge_updates_path) as f:
            bridge_updates = json.load(f)

        # effective shelter capacities
        effective_cap = {}
        for sh in all_shelters:
            sid = str(sh["shelter_id"])
            if sid in shelter_adj:
                effective_cap[sh["shelter_id"]] = shelter_adj[sid]["effective_capacity"]
            else:
                effective_cap[sh["shelter_id"]] = sh["base_capacity"]

        # effective bridge limits
        effective_bridge = {}
        for seg_id, seg in all_segments.items():
            if seg["has_bridge"]:
                sid = str(seg_id)
                if sid in bridge_updates:
                    effective_bridge[seg_id] = bridge_updates[sid]["updated_limit_tons"]
                else:
                    effective_bridge[seg_id] = seg["bridge_weight_limit_tons"]

        # bus deployability from workspace
        bus_status = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "bus_status_*.csv"))):
            df = pd.read_csv(fp)
            for _, row in df.iterrows():
                bus_status[int(row["bus_id"])] = row.to_dict()

        passenger_weight = policy.get("passenger_weight_tons", 0.07)
        min_fuel = policy.get("min_fuel_threshold_pct", 40)
        max_travel = policy.get("max_travel_time_min", 60)

        # route lookup
        route_lookup = {}
        for rt in all_routes:
            route_lookup[(rt["school_id"], rt["shelter_id"])] = rt

        # ========================================================
        # CRITERION 1: loading_schedule.csv exists and has correct columns (10 pts)
        # ========================================================
        ls_path = os.path.join(self.workspace, "loading_schedule.csv")
        required_ls_cols = {"school_name", "bus_id", "student_ids", "shelter_name", "departure_order"}
        ls_rows = []
        if os.path.exists(ls_path):
            try:
                df_ls = pd.read_csv(ls_path, dtype=str)
                cols = set(df_ls.columns)
                if required_ls_cols.issubset(cols):
                    _add("loading_schedule_format", True, 10, 10)
                    ls_rows = df_ls.to_dict("records")
                else:
                    missing = required_ls_cols - cols
                    _add("loading_schedule_format", False, 0, 10,
                         f"Missing columns: {missing}")
            except Exception as e:
                _add("loading_schedule_format", False, 0, 10, str(e))
        else:
            _add("loading_schedule_format", False, 0, 10, "File not found")

        # ========================================================
        # CRITERION 2: dispatch_routes.csv exists and has correct columns (10 pts)
        # ========================================================
        dr_path = os.path.join(self.workspace, "dispatch_routes.csv")
        required_dr_cols = {"bus_id", "school_name", "shelter_name",
                            "route_segment_ids", "total_distance_km",
                            "bus_loaded_weight_tons"}
        dr_rows = []
        if os.path.exists(dr_path):
            try:
                df_dr = pd.read_csv(dr_path, dtype=str)
                cols = set(df_dr.columns)
                if required_dr_cols.issubset(cols):
                    _add("dispatch_routes_format", True, 10, 10)
                    dr_rows = df_dr.to_dict("records")
                else:
                    missing = required_dr_cols - cols
                    _add("dispatch_routes_format", False, 0, 10,
                         f"Missing columns: {missing}")
            except Exception as e:
                _add("dispatch_routes_format", False, 0, 10, str(e))
        else:
            _add("dispatch_routes_format", False, 0, 10, "File not found")

        # ========================================================
        # CRITERION 3: All students assigned exactly once (20 pts)
        # ========================================================
        all_student_ids = {st["student_id"] for st in all_students}
        assigned_ids = set()
        duplicate_ids = set()
        if ls_rows:
            for row in ls_rows:
                try:
                    ids_str = str(row.get("student_ids", ""))
                    if ids_str.strip():
                        ids = [int(x.strip()) for x in ids_str.split(";") if x.strip()]
                        for sid in ids:
                            if sid in assigned_ids:
                                duplicate_ids.add(sid)
                            assigned_ids.add(sid)
                except Exception:
                    pass
        missing_students = all_student_ids - assigned_ids
        extra_students = assigned_ids - all_student_ids
        if not missing_students and not extra_students and not duplicate_ids and ls_rows:
            _add("all_students_assigned", True, 20, 20)
        else:
            reasons = []
            if missing_students:
                reasons.append(f"{len(missing_students)} students not assigned")
            if extra_students:
                reasons.append(f"{len(extra_students)} invalid student IDs")
            if duplicate_ids:
                reasons.append(f"{len(duplicate_ids)} duplicated")
            if not ls_rows:
                reasons.append("No loading schedule data")
            # partial credit: fraction assigned correctly
            correct = len(all_student_ids & assigned_ids - duplicate_ids)
            frac = correct / len(all_student_ids) if all_student_ids else 0
            score = int(20 * frac)
            _add("all_students_assigned", False, score, 20, "; ".join(reasons))

        # ========================================================
        # CRITERION 4: No bus exceeds capacity (15 pts)
        # ========================================================
        capacity_violations = 0
        total_bus_entries = 0
        if ls_rows:
            for row in ls_rows:
                total_bus_entries += 1
                try:
                    bid = int(row["bus_id"])
                    ids_str = str(row.get("student_ids", ""))
                    n_students = len([x for x in ids_str.split(";") if x.strip()])
                    bus = bus_map.get(bid)
                    if bus and n_students > int(bus["capacity"] * policy.get("max_load_factor", 1.0)):
                        capacity_violations += 1
                except Exception:
                    pass
        if total_bus_entries > 0 and capacity_violations == 0:
            _add("no_capacity_violations", True, 15, 15)
        else:
            frac = max(0, 1 - capacity_violations / max(total_bus_entries, 1))
            _add("no_capacity_violations", False, int(15 * frac), 15,
                 f"{capacity_violations} buses exceed capacity")

        # ========================================================
        # CRITERION 5: Bridge weight restrictions respected (15 pts)
        # ========================================================
        bridge_violations = 0
        total_route_entries = 0
        if dr_rows:
            for row in dr_rows:
                total_route_entries += 1
                try:
                    loaded_w = float(row["bus_loaded_weight_tons"])
                    seg_str = str(row.get("route_segment_ids", ""))
                    seg_ids = [int(x.strip()) for x in seg_str.split(";") if x.strip()]
                    for seg_id in seg_ids:
                        if seg_id in effective_bridge:
                            if loaded_w > effective_bridge[seg_id]:
                                bridge_violations += 1
                                break
                except Exception:
                    pass
        if total_route_entries > 0 and bridge_violations == 0:
            _add("bridge_weight_respected", True, 15, 15)
        else:
            frac = max(0, 1 - bridge_violations / max(total_route_entries, 1))
            _add("bridge_weight_respected", False, int(15 * frac), 15,
                 f"{bridge_violations} routes violate bridge limits")

        # ========================================================
        # CRITERION 6: Shelter capacity respected (15 pts)
        # ========================================================
        shelter_load = {}
        if ls_rows:
            for row in ls_rows:
                try:
                    sname = str(row.get("shelter_name", ""))
                    ids_str = str(row.get("student_ids", ""))
                    n = len([x for x in ids_str.split(";") if x.strip()])
                    shelter_load[sname] = shelter_load.get(sname, 0) + n
                except Exception:
                    pass
        shelter_violations = 0
        for sname, load in shelter_load.items():
            sid = shelter_name_to_id.get(sname)
            if sid is not None:
                cap = effective_cap.get(sid, 0)
                if load > cap:
                    shelter_violations += 1
        # also check closed shelters used
        for sname in shelter_load:
            sid = shelter_name_to_id.get(sname)
            if sid is not None and effective_cap.get(sid, 0) == 0 and shelter_load[sname] > 0:
                shelter_violations += 1

        if shelter_load and shelter_violations == 0:
            _add("shelter_capacity_respected", True, 15, 15)
        else:
            n_shelters = max(len(shelter_load), 1)
            frac = max(0, 1 - shelter_violations / n_shelters)
            _add("shelter_capacity_respected", False, int(15 * frac), 15,
                 f"{shelter_violations} shelters over-capacity or closed")

        # ========================================================
        # CRITERION 7: Only deployable buses used (10 pts)
        # ========================================================
        non_deployable_used = 0
        buses_used_count = 0
        if ls_rows:
            used_bus_ids = set()
            for row in ls_rows:
                try:
                    bid = int(row["bus_id"])
                    used_bus_ids.add(bid)
                except Exception:
                    pass
            buses_used_count = len(used_bus_ids)
            for bid in used_bus_ids:
                status = bus_status.get(bid, {})
                if status.get("current_status") == "maintenance":
                    non_deployable_used += 1
                elif status.get("fuel_level_pct", 100) < min_fuel:
                    non_deployable_used += 1
        if buses_used_count > 0 and non_deployable_used == 0:
            _add("only_deployable_buses", True, 10, 10)
        else:
            frac = max(0, 1 - non_deployable_used / max(buses_used_count, 1))
            _add("only_deployable_buses", False, int(10 * frac), 10,
                 f"{non_deployable_used} non-deployable buses used")

        # ========================================================
        # CRITERION 8: evacuation_summary.txt correct (5 pts)
        # ========================================================
        summary_path = os.path.join(self.workspace, "evacuation_summary.txt")
        summary_ok = False
        if os.path.exists(summary_path):
            try:
                with open(summary_path) as f:
                    content = f.read()
                # check it has the three key lines
                has_students = "TOTAL_STUDENTS_EVACUATED:" in content
                has_buses = "TOTAL_BUSES_DISPATCHED:" in content
                has_shelters = "SHELTERS_USED:" in content
                if has_students and has_buses and has_shelters:
                    summary_ok = True
                    _add("evacuation_summary", True, 5, 5)
                else:
                    _add("evacuation_summary", False, 0, 5,
                         "Missing required summary lines")
            except Exception as e:
                _add("evacuation_summary", False, 0, 5, str(e))
        else:
            _add("evacuation_summary", False, 0, 5, "File not found")

        # ========================================================
        # CRITERION 9: Final response contains evacuation summary (10 pts)
        # The action string must contain "EVACUATION COMPLETE:" line
        # ========================================================
        if "EVACUATION COMPLETE:" in action:
            _add("response_summary", True, 10, 10)
        else:
            _add("response_summary", False, 0, 10,
                 "Response missing 'EVACUATION COMPLETE:' summary line")

        # ---- aggregate ----
        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score if max_score else 0.0, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ------------------------------------------------------------------
    #  VERIFY — self-test proving solvability
    # ------------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import glob as glob_mod

        # 1. Read workspace policy files
        with open(os.path.join(self.workspace, "evacuation_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "shelter_status.json")) as f:
            shelter_adj = json.load(f)
        with open(os.path.join(self.workspace, "bridge_weight_updates.json")) as f:
            bridge_updates = json.load(f)

        passenger_weight = policy["passenger_weight_tons"]
        min_fuel = policy["min_fuel_threshold_pct"]
        max_travel = policy["max_travel_time_min"]
        max_load_factor = policy.get("max_load_factor", 1.0)

        # 2. Read bus status files
        bus_status = {}
        for fp in sorted(glob_mod.glob(os.path.join(self.workspace, "bus_status_*.csv"))):
            df = pd.read_csv(fp)
            for _, row in df.iterrows():
                bus_status[int(row["bus_id"])] = row.to_dict()

        # 3. Read student medical files
        student_medical = {}
        for fp in sorted(glob_mod.glob(os.path.join(self.workspace, "student_medical_*.csv"))):
            df = pd.read_csv(fp)
            for _, row in df.iterrows():
                student_medical[int(row["student_id"])] = row.to_dict()

        # 4. Read road conditions
        road_conditions = {}
        for fp in sorted(glob_mod.glob(os.path.join(self.workspace, "road_conditions_*.json"))):
            with open(fp) as fh:
                data = json.load(fh)
            for item in data:
                road_conditions[item["segment_id"]] = item

        # 5. Get all schools via tools (paginated)
        all_schools = []
        page = 1
        while True:
            result = self.tools["list_schools"](page=page, page_size=10)
            all_schools.extend(result["schools"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 6. Get student details per school via tools
        school_students = {}
        for school in all_schools:
            sid = school["school_id"]
            school_students[sid] = []
            page = 1
            while True:
                result = self.tools["get_students_by_school"](
                    school_id=sid, page=page, page_size=20)
                school_students[sid].extend(result["students"])
                if page >= result["total_pages"]:
                    break
                page += 1

        # 7. Get all buses via tools
        all_buses = []
        page = 1
        while True:
            result = self.tools["list_buses"](page=page, page_size=10)
            all_buses.extend(result["buses"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 8. Get all shelters via tools
        all_shelters = []
        page = 1
        while True:
            result = self.tools["list_shelters"](page=page, page_size=10)
            all_shelters.extend(result["shelters"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 9. Filter deployable buses
        deployable = []
        for bus in all_buses:
            bs = bus_status.get(bus["bus_id"])
            if not bs:
                continue
            if bs.get("current_status") == "maintenance":
                continue
            if bs.get("fuel_level_pct", 0) < min_fuel:
                continue
            deployable.append(bus)

        # 10. Compute effective shelter capacities
        effective_cap = {}
        for sh in all_shelters:
            sid_str = str(sh["shelter_id"])
            if sid_str in shelter_adj:
                effective_cap[sh["shelter_id"]] = shelter_adj[sid_str]["effective_capacity"]
            else:
                effective_cap[sh["shelter_id"]] = sh["base_capacity"]

        # 11. Compute effective bridge limits
        # Build from segment lookups via tools (we'll query as needed)
        effective_bridge_limits = {}  # segment_id -> limit

        def get_effective_bridge_limit(seg_id):
            if seg_id in effective_bridge_limits:
                return effective_bridge_limits[seg_id]
            seg_info = self.tools["get_segment_info"](segment_id=seg_id)
            if seg_info.get("has_bridge"):
                base_limit = seg_info["bridge_weight_limit_tons"]
                sid_str = str(seg_id)
                if sid_str in bridge_updates:
                    limit = bridge_updates[sid_str]["updated_limit_tons"]
                else:
                    limit = base_limit
                effective_bridge_limits[seg_id] = limit
                return limit
            effective_bridge_limits[seg_id] = None
            return None

        # 12. Greedy assignment: for each school, split students across shelters
        remaining_cap = dict(effective_cap)
        used_bus_ids = set()
        loading_schedule = []
        dispatch_routes = []

        shelter_name_map = {sh["shelter_id"]: sh["name"] for sh in all_shelters}
        school_name_map = {s["school_id"]: s["name"] for s in all_schools}

        # Sort schools by student count descending (hardest first)
        schools_sorted = sorted(all_schools,
                                key=lambda s: len(school_students.get(s["school_id"], [])),
                                reverse=True)

        def find_bus_for_route(seg_ids, n_students, need_accessible, avail):
            """Find lightest feasible bus for a given route and student count."""
            # Sort by weight ascending to maximise bridge feasibility
            candidates = sorted(avail, key=lambda b: b["empty_weight_tons"])
            for idx, bus in enumerate(candidates):
                cap = int(bus["capacity"] * max_load_factor)
                if cap <= 0:
                    continue
                if need_accessible and not bus["wheelchair_accessible"]:
                    continue
                actual_n = min(cap, n_students)
                lw = bus["empty_weight_tons"] + actual_n * passenger_weight
                ok = True
                for seg_id in seg_ids:
                    limit = get_effective_bridge_limit(seg_id)
                    if limit is not None and lw > limit:
                        ok = False
                        break
                if ok:
                    return candidates.pop(idx), actual_n, lw
            # Retry without accessibility constraint
            if need_accessible:
                candidates2 = sorted(avail, key=lambda b: b["empty_weight_tons"])
                for idx, bus in enumerate(candidates2):
                    cap = int(bus["capacity"] * max_load_factor)
                    if cap <= 0:
                        continue
                    actual_n = min(cap, n_students)
                    lw = bus["empty_weight_tons"] + actual_n * passenger_weight
                    ok = True
                    for seg_id in seg_ids:
                        limit = get_effective_bridge_limit(seg_id)
                        if limit is not None and lw > limit:
                            ok = False
                            break
                    if ok:
                        return candidates2.pop(idx), actual_n, lw
            return None, 0, 0

        for school in schools_sorted:
            sid = school["school_id"]
            remaining_studs = list(school_students.get(sid, []))
            if not remaining_studs:
                continue

            routes_result = self.tools["list_routes_from_school"](school_id=sid)
            avail_routes = routes_result["routes"]
            departure_order = 1

            for route_summary in avail_routes:
                if not remaining_studs:
                    break
                shelter_id = route_summary["shelter_id"]
                cap = remaining_cap.get(shelter_id, 0)
                if cap <= 0:
                    continue

                route_detail = self.tools["get_route"](
                    school_id=sid, shelter_id=shelter_id)
                if "error" in route_detail:
                    continue
                seg_ids = route_detail["segment_ids"]

                # Take at most 'cap' students for this shelter
                batch = remaining_studs[:cap]

                while batch:
                    avail = [b for b in deployable if b["bus_id"] not in used_bus_ids]
                    has_special = any(s["special_needs"] for s in batch)
                    need_acc = has_special and policy.get("special_needs_require_accessible_bus", True)

                    bus, actual_n, lw = find_bus_for_route(
                        seg_ids, len(batch), need_acc, avail)
                    if bus is None:
                        break

                    # Order: special needs first, then grade ascending
                    spec = sorted([s for s in batch if s["special_needs"]],
                                  key=lambda s: s["grade"])
                    norm = sorted([s for s in batch if not s["special_needs"]],
                                  key=lambda s: s["grade"])
                    ordered = (spec + norm)[:actual_n]
                    on_bus_ids = sorted([s["student_id"] for s in ordered])
                    loaded_w = round(bus["empty_weight_tons"]
                                     + len(ordered) * passenger_weight, 2)

                    loading_schedule.append({
                        "school_name": school_name_map[sid],
                        "bus_id": bus["bus_id"],
                        "student_ids": ";".join(str(x) for x in on_bus_ids),
                        "shelter_name": shelter_name_map[shelter_id],
                        "departure_order": departure_order,
                    })
                    dispatch_routes.append({
                        "bus_id": bus["bus_id"],
                        "school_name": school_name_map[sid],
                        "shelter_name": shelter_name_map[shelter_id],
                        "route_segment_ids": ";".join(str(x) for x in seg_ids),
                        "total_distance_km": f"{route_detail['total_distance_km']:.2f}",
                        "bus_loaded_weight_tons": f"{loaded_w:.2f}",
                    })
                    used_bus_ids.add(bus["bus_id"])
                    departure_order += 1
                    remaining_cap[shelter_id] -= len(ordered)

                    assigned_set = {s["student_id"] for s in ordered}
                    batch = [s for s in batch if s["student_id"] not in assigned_set]
                    remaining_studs = [s for s in remaining_studs
                                       if s["student_id"] not in assigned_set]

        # 13. Write deliverables
        pd.DataFrame(loading_schedule).to_csv(
            os.path.join(self.workspace, "loading_schedule.csv"), index=False)
        pd.DataFrame(dispatch_routes).to_csv(
            os.path.join(self.workspace, "dispatch_routes.csv"), index=False)

        # evacuation summary
        total_evacuated = len(set(
            sid for row in loading_schedule
            for sid in (int(x) for x in row["student_ids"].split(";") if x)
        ))
        total_buses = len(set(row["bus_id"] for row in loading_schedule))
        shelters_used = len(set(row["shelter_name"] for row in loading_schedule))

        with open(os.path.join(self.workspace, "evacuation_summary.txt"), "w") as f:
            f.write(f"TOTAL_STUDENTS_EVACUATED: {total_evacuated}\n")
            f.write(f"TOTAL_BUSES_DISPATCHED: {total_buses}\n")
            f.write(f"SHELTERS_USED: {shelters_used}\n")

        action = (f"EVACUATION COMPLETE: {total_evacuated} students evacuated on "
                  f"{total_buses} buses to {shelters_used} shelters")

        return self.step(action)
