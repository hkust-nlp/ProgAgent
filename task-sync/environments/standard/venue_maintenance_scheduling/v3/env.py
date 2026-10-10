import sqlite3
import json
import os
import csv
import re
from datetime import datetime, timedelta
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

    # ----------------------------------------------------------------
    # Tool methods
    # ----------------------------------------------------------------

    @tool(
        description="List venues with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["A", "B", "C"],
                    "description": "Filter by venue category.",
                },
                "district": {
                    "type": "string",
                    "description": "Filter by district name.",
                },
                "surface_type": {
                    "type": "string",
                    "enum": ["natural_grass", "hybrid_grass", "artificial_turf"],
                    "description": "Filter by surface type.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 15).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of results to skip (default 0).",
                },
            },
            "required": [],
        },
    )
    def list_venues(
        self,
        category: str = None,
        district: str = None,
        surface_type: str = None,
        limit: int = 15,
        offset: int = 0,
    ) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM venues WHERE 1=1"
        params = []
        if category:
            query += " AND category = ?"
            params.append(category)
        if district:
            query += " AND district = ?"
            params.append(district)
        if surface_type:
            query += " AND surface_type = ?"
            params.append(surface_type)
        query += " ORDER BY venue_id LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return json.dumps([dict(r) for r in rows])

    @tool(
        description="Get details for a single venue by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "venue_id": {
                    "type": "integer",
                    "description": "The venue ID to look up.",
                },
            },
            "required": ["venue_id"],
        },
    )
    def get_venue_details(self, venue_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM venues WHERE venue_id = ?", (venue_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": "Venue not found"})
        return json.dumps(dict(row))

    @tool(
        description="Query fixtures (scheduled matches) with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "venue_id": {
                    "type": "integer",
                    "description": "Filter by venue ID.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date filter (YYYY-MM-DD), inclusive.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date filter (YYYY-MM-DD), inclusive.",
                },
                "match_type": {
                    "type": "string",
                    "enum": ["league", "cup", "friendly", "training"],
                    "description": "Filter by match type.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 15).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of results to skip (default 0).",
                },
            },
            "required": [],
        },
    )
    def get_fixtures(
        self,
        venue_id: int = None,
        start_date: str = None,
        end_date: str = None,
        match_type: str = None,
        limit: int = 15,
        offset: int = 0,
    ) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM fixtures WHERE 1=1"
        params = []
        if venue_id is not None:
            query += " AND venue_id = ?"
            params.append(venue_id)
        if start_date:
            query += " AND fixture_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND fixture_date <= ?"
            params.append(end_date)
        if match_type:
            query += " AND match_type = ?"
            params.append(match_type)
        query += " ORDER BY fixture_date, fixture_id LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return json.dumps([dict(r) for r in rows])

    @tool(
        description="Query pitch wear inspection records with optional filters. Returns paginated results sorted by inspection_date descending.",
        parameters={
            "type": "object",
            "properties": {
                "venue_id": {
                    "type": "integer",
                    "description": "Filter by venue ID.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date filter for inspection_date (YYYY-MM-DD), inclusive.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date filter for inspection_date (YYYY-MM-DD), inclusive.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 15).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of results to skip (default 0).",
                },
            },
            "required": [],
        },
    )
    def get_pitch_wear_records(
        self,
        venue_id: int = None,
        start_date: str = None,
        end_date: str = None,
        limit: int = 15,
        offset: int = 0,
    ) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM pitch_wear_records WHERE 1=1"
        params = []
        if venue_id is not None:
            query += " AND venue_id = ?"
            params.append(venue_id)
        if start_date:
            query += " AND inspection_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND inspection_date <= ?"
            params.append(end_date)
        query += " ORDER BY inspection_date DESC, record_id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return json.dumps([dict(r) for r in rows])

    @tool(
        description="Query contracted third-party events with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "venue_id": {
                    "type": "integer",
                    "description": "Filter by venue ID.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date filter for event_date (YYYY-MM-DD), inclusive.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date filter for event_date (YYYY-MM-DD), inclusive.",
                },
                "status": {
                    "type": "string",
                    "enum": ["confirmed", "tentative"],
                    "description": "Filter by contract status.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 15).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of results to skip (default 0).",
                },
            },
            "required": [],
        },
    )
    def get_third_party_events(
        self,
        venue_id: int = None,
        start_date: str = None,
        end_date: str = None,
        status: str = None,
        limit: int = 15,
        offset: int = 0,
    ) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM third_party_events WHERE 1=1"
        params = []
        if venue_id is not None:
            query += " AND venue_id = ?"
            params.append(venue_id)
        if start_date:
            query += " AND event_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND event_date <= ?"
            params.append(end_date)
        if status:
            query += " AND contract_status = ?"
            params.append(status)
        query += " ORDER BY event_date, event_id LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return json.dumps([dict(r) for r in rows])

    @tool(
        description="Get available ground staff on a specific date, with optional skill level filter. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "The date to check availability (YYYY-MM-DD).",
                },
                "min_skill_level": {
                    "type": "integer",
                    "description": "Minimum skill level required (1-5).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 15).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of results to skip (default 0).",
                },
            },
            "required": ["date"],
        },
    )
    def get_staff_availability(
        self,
        date: str,
        min_skill_level: int = None,
        limit: int = 15,
        offset: int = 0,
    ) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = """
            SELECT g.staff_id, g.name, g.role, g.skill_level, s.shift_type
            FROM staff_shifts s
            JOIN ground_staff g ON s.staff_id = g.staff_id
            WHERE s.shift_date = ? AND s.status = 'available'
        """
        params = [date]
        if min_skill_level is not None:
            query += " AND g.skill_level >= ?"
            params.append(min_skill_level)
        query += " ORDER BY g.staff_id LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return json.dumps([dict(r) for r in rows])

    # ----------------------------------------------------------------
    # Ground-truth computation (used by step)
    # ----------------------------------------------------------------

    def _compute_ground_truth(self):
        """Compute the expected maintenance schedule and utilization report."""
        import yaml

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load all DB data
        venues = [dict(r) for r in conn.execute("SELECT * FROM venues ORDER BY venue_id").fetchall()]
        fixtures = [dict(r) for r in conn.execute("SELECT * FROM fixtures").fetchall()]
        wear_recs = [dict(r) for r in conn.execute("SELECT * FROM pitch_wear_records").fetchall()]
        events = [dict(r) for r in conn.execute("SELECT * FROM third_party_events").fetchall()]
        staff_all = [dict(r) for r in conn.execute("SELECT * FROM ground_staff ORDER BY staff_id").fetchall()]
        shifts_all = [dict(r) for r in conn.execute("SELECT * FROM staff_shifts").fetchall()]
        conn.close()

        # Load policy
        with open(os.path.join(self.workspace, "maintenance_policy.yaml"), "r") as f:
            policy = yaml.safe_load(f)

        # Load priority rules
        with open(os.path.join(self.workspace, "priority_rules.json"), "r") as f:
            priority_rules = json.load(f)

        # Load certifications from all cert files
        cert_map = {}  # staff_id -> set of certs
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("staff_certifications_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    for entry in json.load(f):
                        cert_map[entry["staff_id"]] = set(entry["certifications"])

        # Load weather forecasts
        weather = {}  # (date, district) -> precipitation_mm
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("weather_forecast_") and fname.endswith(".csv"):
                import pandas as pd
                df = pd.read_csv(os.path.join(self.workspace, fname))
                for _, row in df.iterrows():
                    weather[(row["date"], row["district"])] = row["precipitation_mm"]

        # Load maintenance logs -> find venues with recent maintenance
        recent_maintenance = {}  # venue_id -> most recent date
        planning_start = datetime.strptime(policy["scheduling_rules"]["planning_start"], "%Y-%m-%d")
        lookback = policy["recent_maintenance_adjustment"]["lookback_days"]
        cutoff = (planning_start - timedelta(days=lookback)).strftime("%Y-%m-%d")

        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("maintenance_log_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    content = f.read()
                blocks = content.split("=== Maintenance Record ===")
                for block in blocks:
                    block = block.strip()
                    if not block:
                        continue
                    vid_match = re.search(r"Venue ID:\s*(\d+)", block)
                    date_match = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", block)
                    if vid_match and date_match:
                        vid = int(vid_match.group(1))
                        mdate = date_match.group(1)
                        if mdate >= cutoff and mdate < planning_start.strftime("%Y-%m-%d"):
                            if vid not in recent_maintenance or mdate > recent_maintenance[vid]:
                                recent_maintenance[vid] = mdate

        # Build lookup structures
        venue_map = {v["venue_id"]: v for v in venues}
        excluded_surfaces = set(policy["excluded_surface_types"])

        # Fixtures by venue in planning window
        ps = policy["scheduling_rules"]["planning_start"]
        pe = policy["scheduling_rules"]["planning_end"]
        fixture_dates_by_venue = {}
        for f in fixtures:
            if ps <= f["fixture_date"] <= pe:
                fixture_dates_by_venue.setdefault(f["venue_id"], set()).add(f["fixture_date"])

        # Events by venue (confirmed only) - blocked date ranges
        event_blocked_by_venue = {}
        for e in events:
            if e["contract_status"] != "confirmed":
                continue
            edate = datetime.strptime(e["event_date"], "%Y-%m-%d")
            blocked = set()
            for d in range(-e["setup_days"], e["teardown_days"] + 1):
                bd = (edate + timedelta(days=d)).strftime("%Y-%m-%d")
                if ps <= bd <= pe:
                    blocked.add(bd)
            event_blocked_by_venue.setdefault(e["venue_id"], set()).update(blocked)

        # Get latest wear record per venue
        latest_wear = {}
        for r in wear_recs:
            vid = r["venue_id"]
            if vid not in latest_wear or r["inspection_date"] > latest_wear[vid]["inspection_date"]:
                latest_wear[vid] = r
            elif r["inspection_date"] == latest_wear[vid]["inspection_date"] and r["record_id"] > latest_wear[vid]["record_id"]:
                latest_wear[vid] = r

        # Determine maintenance needs
        maint_types = policy["maintenance_types"]
        wear_reduction = policy["recent_maintenance_adjustment"]["wear_reduction"]
        cat_mult = policy["category_multipliers"]
        urgency_cfg = policy["urgency_factors"]
        max_precip = policy["weather_constraints"]["max_precipitation_mm"]

        tasks = []
        for v in venues:
            vid = v["venue_id"]
            if v["surface_type"] in excluded_surfaces:
                continue
            if vid not in latest_wear:
                continue
            raw_wear = latest_wear[vid]["wear_index"]
            adjusted_wear = raw_wear
            if vid in recent_maintenance:
                adjusted_wear = max(0, raw_wear - wear_reduction)

            # Determine maintenance type (highest applicable)
            mtype = None
            for mt_name in ["deep_restoration", "surface_treatment", "light_maintenance"]:
                if adjusted_wear >= maint_types[mt_name]["min_wear_index"]:
                    mtype = mt_name
                    break
            if mtype is None:
                continue

            # Urgency factor: days from planning_start to earliest fixture
            venue_fixtures = fixture_dates_by_venue.get(vid, set())
            if venue_fixtures:
                earliest = min(venue_fixtures)
                days_to = (datetime.strptime(earliest, "%Y-%m-%d") - datetime.strptime(ps, "%Y-%m-%d")).days
            else:
                days_to = 999

            if days_to <= 3:
                uf = urgency_cfg["days_0_to_3"]
            elif days_to <= 7:
                uf = urgency_cfg["days_4_to_7"]
            elif days_to <= 14:
                uf = urgency_cfg["days_8_to_14"]
            else:
                uf = urgency_cfg["days_15_plus"]

            cm = cat_mult[v["category"]]
            priority_score = round(adjusted_wear * cm * uf, int(priority_rules["rounding"]))

            tasks.append({
                "venue_id": vid,
                "venue_name": v["name"],
                "district": v["district"],
                "category": v["category"],
                "maintenance_type": mtype,
                "adjusted_wear": adjusted_wear,
                "priority_score": priority_score,
                "hours_required": maint_types[mtype]["hours_required"],
                "min_skill": maint_types[mtype]["min_skill_level"],
                "required_cert": maint_types[mtype]["required_certification"],
            })

        # Sort by priority_score desc, venue_id asc (for scheduling order)
        tasks.sort(key=lambda t: (-t["priority_score"], t["venue_id"]))

        # Staff availability by date
        avail_by_date = {}
        for s in shifts_all:
            if s["status"] == "available" and ps <= s["shift_date"] <= pe:
                avail_by_date.setdefault(s["shift_date"], set()).add(s["staff_id"])

        staff_map = {s["staff_id"]: s for s in staff_all}

        # Schedule maintenance
        schedule = []
        staff_booked = {}  # date -> set of staff_ids already assigned

        planning_dates = []
        d = datetime.strptime(ps, "%Y-%m-%d")
        end_d = datetime.strptime(pe, "%Y-%m-%d")
        while d <= end_d:
            planning_dates.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)

        for task in tasks:
            vid = task["venue_id"]
            district = task["district"]
            fixture_blocked = fixture_dates_by_venue.get(vid, set())
            event_blocked = event_blocked_by_venue.get(vid, set())
            min_skill = task["min_skill"]
            req_cert = task["required_cert"]

            scheduled = False
            for date_str in planning_dates:
                # Check fixture conflict
                if date_str in fixture_blocked:
                    continue
                # Check event conflict
                if date_str in event_blocked:
                    continue
                # Check weather
                precip = weather.get((date_str, district), 0)
                if precip > max_precip:
                    continue
                # Find eligible staff
                available_ids = avail_by_date.get(date_str, set())
                booked = staff_booked.get(date_str, set())
                candidates = []
                for sid in sorted(available_ids):
                    if sid in booked:
                        continue
                    s = staff_map[sid]
                    if s["skill_level"] < min_skill:
                        continue
                    if req_cert and req_cert not in cert_map.get(sid, set()):
                        continue
                    candidates.append(sid)
                if not candidates:
                    continue
                # Assign lowest staff_id
                assigned_sid = candidates[0]
                staff_booked.setdefault(date_str, set()).add(assigned_sid)
                schedule.append({
                    "date": date_str,
                    "venue_id": vid,
                    "venue_name": task["venue_name"],
                    "maintenance_type": task["maintenance_type"],
                    "priority_score": task["priority_score"],
                    "assigned_staff_id": assigned_sid,
                    "assigned_staff_name": staff_map[assigned_sid]["name"],
                    "estimated_hours": task["hours_required"],
                    "reason": f"adjusted_wear={task['adjusted_wear']:.1f}, category={task['category']}",
                })
                scheduled = True
                break

        # Sort schedule by date asc, priority_score desc
        schedule.sort(key=lambda s: (s["date"], -s["priority_score"]))

        # Utilization report for ALL venues
        maintenance_dates_by_venue = {}
        for s in schedule:
            maintenance_dates_by_venue.setdefault(s["venue_id"], set()).add(s["date"])

        utilization = []
        for v in venues:
            vid = v["venue_id"]
            fdays = len(fixture_dates_by_venue.get(vid, set()))
            edays = len(event_blocked_by_venue.get(vid, set()))
            mdays = len(maintenance_dates_by_venue.get(vid, set()))
            total_days = PLANNING_DAYS if hasattr(self, '_planning_days') else 30
            available = total_days - fdays - edays - mdays
            if available < 0:
                available = 0
            util_pct = round((fdays + edays + mdays) / total_days * 100, 1)
            utilization.append({
                "venue_id": vid,
                "venue_name": v["name"],
                "category": v["category"],
                "fixture_days": fdays,
                "event_days": edays,
                "maintenance_days": mdays,
                "available_days": available,
                "utilization_pct": util_pct,
            })

        # Summary stats
        n_tasks = len(schedule)
        n_deep = sum(1 for s in schedule if s["maintenance_type"] == "deep_restoration")
        total_hours = sum(s["estimated_hours"] for s in schedule)
        if schedule:
            highest = max(schedule, key=lambda s: s["priority_score"])
            highest_venue = highest["venue_name"]
            highest_score = highest["priority_score"]
        else:
            highest_venue = "N/A"
            highest_score = 0.0

        summary = {
            "total_maintenance_tasks": n_tasks,
            "deep_restoration_count": n_deep,
            "highest_priority_venue": highest_venue,
            "highest_priority_score": highest_score,
            "total_staff_hours": total_hours,
        }

        return schedule, utilization, summary

    # ----------------------------------------------------------------
    # Evaluation
    # ----------------------------------------------------------------

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
        expected_schedule, expected_util, expected_summary = self._compute_ground_truth()

        criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: maintenance_schedule.csv exists with correct columns (10 pts) ---
        max_c1 = 10
        max_score += max_c1
        sched_path = os.path.join(self.workspace, "maintenance_schedule.csv")
        expected_cols = ["date", "venue_id", "venue_name", "maintenance_type",
                         "priority_score", "assigned_staff_id", "assigned_staff_name",
                         "estimated_hours", "reason"]
        if os.path.exists(sched_path):
            try:
                with open(sched_path, "r") as f:
                    reader = csv.DictReader(f)
                    agent_sched_rows = list(reader)
                    agent_cols = list(reader.fieldnames) if reader.fieldnames else []
                if set(expected_cols).issubset(set(agent_cols)):
                    criteria["schedule_file_format"] = {
                        "passed": True, "score": max_c1, "max_score": max_c1,
                    }
                    total_score += max_c1
                else:
                    missing = set(expected_cols) - set(agent_cols)
                    criteria["schedule_file_format"] = {
                        "passed": False, "score": 5, "max_score": max_c1,
                        "reason": f"Missing columns: {missing}",
                    }
                    total_score += 5
            except Exception as e:
                agent_sched_rows = []
                criteria["schedule_file_format"] = {
                    "passed": False, "score": 0, "max_score": max_c1,
                    "reason": f"Error reading CSV: {e}",
                }
        else:
            agent_sched_rows = []
            criteria["schedule_file_format"] = {
                "passed": False, "score": 0, "max_score": max_c1,
                "reason": "maintenance_schedule.csv not found",
            }

        # --- Criterion 2: Correct venues and maintenance types (20 pts) ---
        max_c2 = 20
        max_score += max_c2
        expected_set = {(s["venue_id"], s["maintenance_type"]) for s in expected_schedule}
        agent_set = set()
        for r in agent_sched_rows:
            try:
                agent_set.add((int(r["venue_id"]), r["maintenance_type"]))
            except (KeyError, ValueError):
                pass
        if expected_set:
            correct = len(expected_set & agent_set)
            extra = len(agent_set - expected_set)
            ratio = max(0, correct - extra * 0.5) / len(expected_set)
            c2_score = round(ratio * max_c2)
        else:
            c2_score = max_c2 if not agent_set else 0
        criteria["venue_maintenance_identification"] = {
            "passed": c2_score == max_c2,
            "score": c2_score,
            "max_score": max_c2,
            "reason": f"Matched {len(expected_set & agent_set)}/{len(expected_set)}, extra={len(agent_set - expected_set)}" if c2_score < max_c2 else "",
        }
        total_score += c2_score

        # --- Criterion 3: No scheduling conflicts (15 pts) ---
        max_c3 = 15
        max_score += max_c3
        import yaml
        with open(os.path.join(self.workspace, "maintenance_policy.yaml"), "r") as f:
            policy = yaml.safe_load(f)
        ps = policy["scheduling_rules"]["planning_start"]
        pe = policy["scheduling_rules"]["planning_end"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        fixtures_db = [dict(r) for r in conn.execute("SELECT * FROM fixtures").fetchall()]
        events_db = [dict(r) for r in conn.execute("SELECT * FROM third_party_events").fetchall()]
        conn.close()

        fixture_dates_by_venue = {}
        for f in fixtures_db:
            if ps <= f["fixture_date"] <= pe:
                fixture_dates_by_venue.setdefault(f["venue_id"], set()).add(f["fixture_date"])
        event_blocked_by_venue = {}
        for e in events_db:
            if e["contract_status"] != "confirmed":
                continue
            edate = datetime.strptime(e["event_date"], "%Y-%m-%d")
            for d in range(-e["setup_days"], e["teardown_days"] + 1):
                bd = (edate + timedelta(days=d)).strftime("%Y-%m-%d")
                if ps <= bd <= pe:
                    event_blocked_by_venue.setdefault(e["venue_id"], set()).add(bd)

        weather = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("weather_forecast_") and fname.endswith(".csv"):
                import pandas as pd
                df = pd.read_csv(os.path.join(self.workspace, fname))
                for _, row in df.iterrows():
                    weather[(row["date"], row["district"])] = row["precipitation_mm"]

        venue_district = {}
        conn2 = sqlite3.connect(self.db_path)
        conn2.row_factory = sqlite3.Row
        for r in conn2.execute("SELECT venue_id, district FROM venues").fetchall():
            venue_district[r["venue_id"]] = r["district"]
        conn2.close()

        conflicts = 0
        total_checked = 0
        for r in agent_sched_rows:
            try:
                vid = int(r["venue_id"])
                date_str = r["date"]
                total_checked += 1
                if date_str in fixture_dates_by_venue.get(vid, set()):
                    conflicts += 1
                elif date_str in event_blocked_by_venue.get(vid, set()):
                    conflicts += 1
                elif weather.get((date_str, venue_district.get(vid, "")), 0) > policy["weather_constraints"]["max_precipitation_mm"]:
                    conflicts += 1
            except (KeyError, ValueError):
                conflicts += 1

        if total_checked > 0:
            conflict_ratio = conflicts / total_checked
            c3_score = round((1 - conflict_ratio) * max_c3)
        else:
            c3_score = 0
        criteria["no_scheduling_conflicts"] = {
            "passed": c3_score == max_c3,
            "score": c3_score,
            "max_score": max_c3,
            "reason": f"{conflicts}/{total_checked} tasks have conflicts" if conflicts > 0 else "",
        }
        total_score += c3_score

        # --- Criterion 4: Staff assignments valid (15 pts) ---
        max_c4 = 15
        max_score += max_c4
        maint_types = policy["maintenance_types"]
        cert_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("staff_certifications_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    for entry in json.load(f):
                        cert_map[entry["staff_id"]] = set(entry["certifications"])

        conn3 = sqlite3.connect(self.db_path)
        conn3.row_factory = sqlite3.Row
        staff_db = {r["staff_id"]: dict(r) for r in conn3.execute("SELECT * FROM ground_staff").fetchall()}
        shifts_db = conn3.execute("SELECT * FROM staff_shifts").fetchall()
        conn3.close()
        avail_lookup = {}
        for s in shifts_db:
            if s["status"] == "available":
                avail_lookup.setdefault(s["shift_date"], set()).add(s["staff_id"])

        staff_errors = 0
        staff_checked = 0
        date_staff_assignments = {}
        for r in agent_sched_rows:
            try:
                sid = int(r["assigned_staff_id"])
                date_str = r["date"]
                mtype = r["maintenance_type"]
                staff_checked += 1

                # Check skill level
                if sid not in staff_db:
                    staff_errors += 1
                    continue
                mt_cfg = maint_types.get(mtype, {})
                if staff_db[sid]["skill_level"] < mt_cfg.get("min_skill_level", 0):
                    staff_errors += 1
                    continue
                # Check cert
                req_cert = mt_cfg.get("required_certification")
                if req_cert and req_cert not in cert_map.get(sid, set()):
                    staff_errors += 1
                    continue
                # Check availability
                if sid not in avail_lookup.get(date_str, set()):
                    staff_errors += 1
                    continue
                # Check double-booking
                key = (date_str, sid)
                if key in date_staff_assignments:
                    staff_errors += 1
                    continue
                date_staff_assignments[key] = True
            except (KeyError, ValueError):
                staff_errors += 1

        if staff_checked > 0:
            err_ratio = staff_errors / staff_checked
            c4_score = round((1 - err_ratio) * max_c4)
        else:
            c4_score = 0
        criteria["valid_staff_assignments"] = {
            "passed": c4_score == max_c4,
            "score": c4_score,
            "max_score": max_c4,
            "reason": f"{staff_errors}/{staff_checked} assignments invalid" if staff_errors > 0 else "",
        }
        total_score += c4_score

        # --- Criterion 5: Priority scores correct (15 pts) ---
        max_c5 = 15
        max_score += max_c5
        expected_scores = {s["venue_id"]: s["priority_score"] for s in expected_schedule}
        score_matches = 0
        score_total = 0
        for r in agent_sched_rows:
            try:
                vid = int(r["venue_id"])
                agent_ps = float(r["priority_score"])
                if vid in expected_scores:
                    score_total += 1
                    if abs(agent_ps - expected_scores[vid]) < 0.02:
                        score_matches += 1
            except (KeyError, ValueError):
                pass
        if expected_scores:
            c5_score = round((score_matches / len(expected_scores)) * max_c5)
        else:
            c5_score = max_c5
        criteria["priority_scores_correct"] = {
            "passed": c5_score == max_c5,
            "score": c5_score,
            "max_score": max_c5,
            "reason": f"Matched {score_matches}/{len(expected_scores)} scores" if c5_score < max_c5 else "",
        }
        total_score += c5_score

        # --- Criterion 6: utilization_report.csv correct (15 pts) ---
        max_c6 = 15
        max_score += max_c6
        util_path = os.path.join(self.workspace, "utilization_report.csv")
        expected_util_map = {u["venue_id"]: u for u in expected_util}
        if os.path.exists(util_path):
            try:
                with open(util_path, "r") as f:
                    reader = csv.DictReader(f)
                    agent_util_rows = list(reader)
                if not agent_util_rows:
                    raise ValueError("Empty file")
                # Check each venue
                util_matches = 0
                for r in agent_util_rows:
                    try:
                        vid = int(r["venue_id"])
                        if vid in expected_util_map:
                            exp = expected_util_map[vid]
                            fd_ok = int(r.get("fixture_days", -1)) == exp["fixture_days"]
                            ed_ok = int(r.get("event_days", -1)) == exp["event_days"]
                            md_ok = int(r.get("maintenance_days", -1)) == exp["maintenance_days"]
                            up_ok = abs(float(r.get("utilization_pct", -1)) - exp["utilization_pct"]) < 0.15
                            if fd_ok and ed_ok and md_ok and up_ok:
                                util_matches += 1
                    except (KeyError, ValueError):
                        pass
                c6_score = round((util_matches / len(expected_util_map)) * max_c6)
            except Exception as e:
                c6_score = 0
                criteria["utilization_report_correct"] = {
                    "passed": False, "score": 0, "max_score": max_c6,
                    "reason": f"Error reading utilization_report.csv: {e}",
                }
                total_score += c6_score
                # skip the normal assignment below
                max_score += 0  # no-op
        else:
            c6_score = 0
        if "utilization_report_correct" not in criteria:
            criteria["utilization_report_correct"] = {
                "passed": c6_score == max_c6,
                "score": c6_score,
                "max_score": max_c6,
                "reason": "" if c6_score == max_c6 else f"Matched {c6_score}/{max_c6} proportionally",
            }
        total_score += c6_score

        # --- Criterion 7: Response summary correct (10 pts) ---
        max_c7 = 10
        max_score += max_c7
        c7_score = 0
        action_lower = action.lower() if action else ""
        # Check total tasks
        if str(expected_summary["total_maintenance_tasks"]) in action:
            c7_score += 3
        # Check deep restoration count
        if str(expected_summary["deep_restoration_count"]) in action:
            c7_score += 2
        # Check highest priority venue
        if expected_summary["highest_priority_venue"].lower() in action_lower:
            c7_score += 2
        # Check highest priority score
        if str(expected_summary["highest_priority_score"]) in action:
            c7_score += 1
        # Check total hours
        if str(expected_summary["total_staff_hours"]) in action:
            c7_score += 2
        criteria["response_summary"] = {
            "passed": c7_score == max_c7,
            "score": c7_score,
            "max_score": max_c7,
            "reason": "" if c7_score == max_c7 else f"Some summary values missing from response",
        }
        total_score += c7_score

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
            "expected_summary": expected_summary,
        }
        return reward, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml

        # ---- Step 1: Read policy and config files ----
        with open(os.path.join(self.workspace, "maintenance_policy.yaml"), "r") as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "priority_rules.json"), "r") as f:
            priority_rules = json.load(f)

        # Read staff assignment guidelines (for reference, rules are clear)
        with open(os.path.join(self.workspace, "staff_assignment_guidelines.md"), "r") as f:
            _ = f.read()

        ps = policy["scheduling_rules"]["planning_start"]
        pe = policy["scheduling_rules"]["planning_end"]
        excluded_surfaces = set(policy["excluded_surface_types"])
        maint_types = policy["maintenance_types"]
        cat_mult = policy["category_multipliers"]
        urgency_cfg = policy["urgency_factors"]
        max_precip = policy["weather_constraints"]["max_precipitation_mm"]
        lookback = policy["recent_maintenance_adjustment"]["lookback_days"]
        wear_reduction = policy["recent_maintenance_adjustment"]["wear_reduction"]
        rounding = int(priority_rules["rounding"])

        # ---- Step 2: Read weather files ----
        weather = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("weather_forecast_") and fname.endswith(".csv"):
                import pandas as pd
                df = pd.read_csv(os.path.join(self.workspace, fname))
                for _, row in df.iterrows():
                    weather[(row["date"], row["district"])] = row["precipitation_mm"]

        # ---- Step 3: Read certification files ----
        cert_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("staff_certifications_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    for entry in json.load(f):
                        cert_map[entry["staff_id"]] = set(entry["certifications"])

        # ---- Step 4: Read maintenance logs ----
        planning_start_dt = datetime.strptime(ps, "%Y-%m-%d")
        cutoff = (planning_start_dt - timedelta(days=lookback)).strftime("%Y-%m-%d")
        recent_maintenance = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("maintenance_log_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    content = f.read()
                blocks = content.split("=== Maintenance Record ===")
                for block in blocks:
                    block = block.strip()
                    if not block:
                        continue
                    vid_m = re.search(r"Venue ID:\s*(\d+)", block)
                    date_m = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", block)
                    if vid_m and date_m:
                        vid = int(vid_m.group(1))
                        mdate = date_m.group(1)
                        if mdate >= cutoff and mdate < ps:
                            if vid not in recent_maintenance or mdate > recent_maintenance[vid]:
                                recent_maintenance[vid] = mdate

        # ---- Step 5: Get all venues via tools ----
        tool_call_count = 0
        venues = []
        offset = 0
        while True:
            result = json.loads(self.tools["list_venues"](limit=15, offset=offset))
            tool_call_count += 1
            if not result:
                break
            venues.extend(result)
            if len(result) < 15:
                break
            offset += 15

        venue_map = {v["venue_id"]: v for v in venues}

        # ---- Step 6: Get all fixtures via tools ----
        all_fixtures = []
        offset = 0
        while True:
            result = json.loads(self.tools["get_fixtures"](
                start_date=ps, end_date=pe, limit=15, offset=offset
            ))
            tool_call_count += 1
            if not result:
                break
            all_fixtures.extend(result)
            if len(result) < 15:
                break
            offset += 15

        fixture_dates_by_venue = {}
        for f in all_fixtures:
            fixture_dates_by_venue.setdefault(f["venue_id"], set()).add(f["fixture_date"])

        # ---- Step 7: Get all pitch wear records via tools ----
        all_wear = []
        offset = 0
        while True:
            result = json.loads(self.tools["get_pitch_wear_records"](limit=15, offset=offset))
            tool_call_count += 1
            if not result:
                break
            all_wear.extend(result)
            if len(result) < 15:
                break
            offset += 15

        latest_wear = {}
        for r in all_wear:
            vid = r["venue_id"]
            if vid not in latest_wear or r["inspection_date"] > latest_wear[vid]["inspection_date"]:
                latest_wear[vid] = r
            elif r["inspection_date"] == latest_wear[vid]["inspection_date"] and r["record_id"] > latest_wear[vid]["record_id"]:
                latest_wear[vid] = r

        # ---- Step 8: Get all third-party events via tools ----
        all_events = []
        offset = 0
        while True:
            result = json.loads(self.tools["get_third_party_events"](
                start_date=ps, end_date=pe, limit=15, offset=offset
            ))
            tool_call_count += 1
            if not result:
                break
            all_events.extend(result)
            if len(result) < 15:
                break
            offset += 15

        event_blocked_by_venue = {}
        for e in all_events:
            if e["contract_status"] != "confirmed":
                continue
            edate = datetime.strptime(e["event_date"], "%Y-%m-%d")
            for d in range(-e["setup_days"], e["teardown_days"] + 1):
                bd = (edate + timedelta(days=d)).strftime("%Y-%m-%d")
                if ps <= bd <= pe:
                    event_blocked_by_venue.setdefault(e["venue_id"], set()).update([bd])

        # ---- Step 9: Determine maintenance needs ----
        tasks = []
        for v in venues:
            vid = v["venue_id"]
            if v["surface_type"] in excluded_surfaces:
                continue
            if vid not in latest_wear:
                continue
            raw_wear = latest_wear[vid]["wear_index"]
            adjusted_wear = raw_wear
            if vid in recent_maintenance:
                adjusted_wear = max(0, raw_wear - wear_reduction)

            mtype = None
            for mt_name in ["deep_restoration", "surface_treatment", "light_maintenance"]:
                if adjusted_wear >= maint_types[mt_name]["min_wear_index"]:
                    mtype = mt_name
                    break
            if mtype is None:
                continue

            venue_fixtures = fixture_dates_by_venue.get(vid, set())
            if venue_fixtures:
                earliest = min(venue_fixtures)
                days_to = (datetime.strptime(earliest, "%Y-%m-%d") - datetime.strptime(ps, "%Y-%m-%d")).days
            else:
                days_to = 999

            if days_to <= 3:
                uf = urgency_cfg["days_0_to_3"]
            elif days_to <= 7:
                uf = urgency_cfg["days_4_to_7"]
            elif days_to <= 14:
                uf = urgency_cfg["days_8_to_14"]
            else:
                uf = urgency_cfg["days_15_plus"]

            cm = cat_mult[v["category"]]
            priority_score = round(adjusted_wear * cm * uf, rounding)

            tasks.append({
                "venue_id": vid,
                "venue_name": v["name"],
                "district": v["district"],
                "category": v["category"],
                "maintenance_type": mtype,
                "adjusted_wear": adjusted_wear,
                "priority_score": priority_score,
                "hours_required": maint_types[mtype]["hours_required"],
                "min_skill": maint_types[mtype]["min_skill_level"],
                "required_cert": maint_types[mtype]["required_certification"],
            })

        tasks.sort(key=lambda t: (-t["priority_score"], t["venue_id"]))

        # ---- Step 10: Build planning dates ----
        planning_dates = []
        d = datetime.strptime(ps, "%Y-%m-%d")
        end_d = datetime.strptime(pe, "%Y-%m-%d")
        while d <= end_d:
            planning_dates.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)

        # ---- Step 11: Schedule with staff assignment via tools ----
        schedule = []
        staff_booked = {}
        # Cache staff availability per date to minimize repeated calls
        staff_avail_cache = {}

        for task in tasks:
            vid = task["venue_id"]
            district = task["district"]
            fixture_blocked = fixture_dates_by_venue.get(vid, set())
            event_blocked = event_blocked_by_venue.get(vid, set())
            min_skill = task["min_skill"]
            req_cert = task["required_cert"]

            scheduled = False
            for date_str in planning_dates:
                if date_str in fixture_blocked:
                    continue
                if date_str in event_blocked:
                    continue
                precip = weather.get((date_str, district), 0)
                if precip > max_precip:
                    continue

                # Get available staff for this date (use cache)
                if date_str not in staff_avail_cache:
                    avail_staff = []
                    off2 = 0
                    while True:
                        res = json.loads(self.tools["get_staff_availability"](
                            date=date_str, limit=15, offset=off2
                        ))
                        tool_call_count += 1
                        if not res:
                            break
                        avail_staff.extend(res)
                        if len(res) < 15:
                            break
                        off2 += 15
                    staff_avail_cache[date_str] = avail_staff

                booked = staff_booked.get(date_str, set())
                candidates = []
                for s in staff_avail_cache[date_str]:
                    sid = s["staff_id"]
                    if sid in booked:
                        continue
                    if s["skill_level"] < min_skill:
                        continue
                    if req_cert and req_cert not in cert_map.get(sid, set()):
                        continue
                    candidates.append(s)

                if not candidates:
                    continue

                candidates.sort(key=lambda x: x["staff_id"])
                assigned = candidates[0]
                staff_booked.setdefault(date_str, set()).add(assigned["staff_id"])
                schedule.append({
                    "date": date_str,
                    "venue_id": vid,
                    "venue_name": task["venue_name"],
                    "maintenance_type": task["maintenance_type"],
                    "priority_score": task["priority_score"],
                    "assigned_staff_id": assigned["staff_id"],
                    "assigned_staff_name": assigned["name"],
                    "estimated_hours": task["hours_required"],
                    "reason": f"adjusted_wear={task['adjusted_wear']:.1f}, category={task['category']}",
                })
                scheduled = True
                break

        schedule.sort(key=lambda s: (s["date"], -s["priority_score"]))

        # ---- Step 12: Build utilization report ----
        maintenance_dates_by_venue = {}
        for s in schedule:
            maintenance_dates_by_venue.setdefault(s["venue_id"], set()).add(s["date"])

        utilization = []
        for v in venues:
            vid = v["venue_id"]
            fdays = len(fixture_dates_by_venue.get(vid, set()))
            edays = len(event_blocked_by_venue.get(vid, set()))
            mdays = len(maintenance_dates_by_venue.get(vid, set()))
            total_days = 30
            available = max(0, total_days - fdays - edays - mdays)
            util_pct = round((fdays + edays + mdays) / total_days * 100, 1)
            utilization.append({
                "venue_id": vid,
                "venue_name": v["name"],
                "category": v["category"],
                "fixture_days": fdays,
                "event_days": edays,
                "maintenance_days": mdays,
                "available_days": available,
                "utilization_pct": util_pct,
            })

        # ---- Step 13: Write deliverables ----
        with open(os.path.join(self.workspace, "maintenance_schedule.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "date", "venue_id", "venue_name", "maintenance_type",
                "priority_score", "assigned_staff_id", "assigned_staff_name",
                "estimated_hours", "reason",
            ])
            writer.writeheader()
            writer.writerows(schedule)

        with open(os.path.join(self.workspace, "utilization_report.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "venue_id", "venue_name", "category", "fixture_days",
                "event_days", "maintenance_days", "available_days", "utilization_pct",
            ])
            writer.writeheader()
            writer.writerows(utilization)

        # ---- Step 14: Build action summary ----
        n_tasks = len(schedule)
        n_deep = sum(1 for s in schedule if s["maintenance_type"] == "deep_restoration")
        total_hours = sum(s["estimated_hours"] for s in schedule)
        if schedule:
            highest = max(schedule, key=lambda s: s["priority_score"])
            highest_venue = highest["venue_name"]
            highest_score = highest["priority_score"]
        else:
            highest_venue = "N/A"
            highest_score = 0.0

        action = (
            f"Maintenance scheduling complete.\n"
            f"Total maintenance tasks scheduled: {n_tasks}\n"
            f"Venues requiring deep restoration: {n_deep}\n"
            f"Highest priority venue: {highest_venue} with score {highest_score}\n"
            f"Total staff hours allocated: {total_hours}\n"
            f"The maintenance_schedule.csv and utilization_report.csv have been saved."
        )

        print(f"[verify] Tool calls made: {tool_call_count}")
        return self.step(action)
