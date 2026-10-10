#!/usr/bin/env python3
"""Environment for volunteer shift scheduling task."""

import csv
import io
import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


# ── Decorator ──────────────────────────────────────────────────────────────

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ── Helpers ────────────────────────────────────────────────────────────────

def _time_to_minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _windows_cover(windows, start, end):
    """Return True if any availability window fully covers [start, end]."""
    s = _time_to_minutes(start)
    e = _time_to_minutes(end)
    for w in windows:
        if _time_to_minutes(w[0]) <= s and _time_to_minutes(w[1]) >= e:
            return True
    return False


def _shifts_overlap(s1_start, s1_end, s2_start, s2_end):
    """Return True if two time ranges overlap."""
    a0, a1 = _time_to_minutes(s1_start), _time_to_minutes(s1_end)
    b0, b1 = _time_to_minutes(s2_start), _time_to_minutes(s2_end)
    return a0 < b1 and b0 < a1


# ── Task Environment ──────────────────────────────────────────────────────

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

    # ── Tool methods ───────────────────────────────────────────────────

    @tool(
        description="List volunteers with pagination. Returns a JSON object with 'volunteers' (list of volunteer records with id, name, certifications, max_shifts_per_week, experience_years) and 'has_more' (boolean indicating more pages).",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page. Maximum 20.",
                },
            },
            "required": ["page"],
        },
    )
    def list_volunteers(self, page: int, page_size: int = 20) -> str:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, certifications, max_shifts_per_week, experience_years "
            "FROM volunteers ORDER BY id LIMIT ? OFFSET ?",
            (page_size + 1, offset),
        ).fetchall()
        conn.close()

        has_more = len(rows) > page_size
        volunteers = [dict(r) for r in rows[:page_size]]
        return json.dumps({"volunteers": volunteers, "has_more": has_more})

    @tool(
        description="List shifts for a specific day of the week with pagination. Returns a JSON object with 'shifts' (list of shift records with shift_id, event_id, event_name, day_of_week, start_time, end_time, role, location, is_outdoor) and 'has_more'.",
        parameters={
            "type": "object",
            "properties": {
                "day_of_week": {
                    "type": "string",
                    "description": "Day name, e.g. 'Monday', 'Tuesday', etc.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page. Maximum 20.",
                },
            },
            "required": ["day_of_week", "page"],
        },
    )
    def list_shifts(self, day_of_week: str, page: int, page_size: int = 20) -> str:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id AS shift_id, event_id, event_name, day_of_week, "
            "start_time, end_time, role, location, is_outdoor "
            "FROM shifts WHERE day_of_week = ? ORDER BY id LIMIT ? OFFSET ?",
            (day_of_week, page_size + 1, offset),
        ).fetchall()
        conn.close()

        has_more = len(rows) > page_size
        shifts = [dict(r) for r in rows[:page_size]]
        for s in shifts:
            s["is_outdoor"] = bool(s["is_outdoor"])
        return json.dumps({"shifts": shifts, "has_more": has_more})

    @tool(
        description="Get a volunteer's availability windows for the entire week. Returns a JSON object with 'volunteer_id' and 'windows' (list of {day_of_week, available_from, available_until}).",
        parameters={
            "type": "object",
            "properties": {
                "volunteer_id": {
                    "type": "integer",
                    "description": "The volunteer's ID.",
                },
            },
            "required": ["volunteer_id"],
        },
    )
    def get_volunteer_availability(self, volunteer_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT day_of_week, available_from, available_until "
            "FROM availability WHERE volunteer_id = ? ORDER BY id",
            (volunteer_id,),
        ).fetchall()
        conn.close()
        return json.dumps({
            "volunteer_id": volunteer_id,
            "windows": [dict(r) for r in rows],
        })

    @tool(
        description="Get attendance summary for a single volunteer. Returns a JSON object with 'volunteer_id', 'total_records', 'attended', 'no_shows', and 'no_show_rate' (float, 0.0-1.0).",
        parameters={
            "type": "object",
            "properties": {
                "volunteer_id": {
                    "type": "integer",
                    "description": "The volunteer's ID.",
                },
            },
            "required": ["volunteer_id"],
        },
    )
    def get_attendance_summary(self, volunteer_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT status FROM attendance_history WHERE volunteer_id = ?",
            (volunteer_id,),
        ).fetchall()
        conn.close()

        total = len(rows)
        no_shows = sum(1 for r in rows if r[0] == "no_show")
        attended = total - no_shows
        rate = round(no_shows / total, 4) if total > 0 else 0.0
        return json.dumps({
            "volunteer_id": volunteer_id,
            "total_records": total,
            "attended": attended,
            "no_shows": no_shows,
            "no_show_rate": rate,
        })

    # ── step ───────────────────────────────────────────────────────────

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
        criteria = {}
        # ── Load ground-truth data ──
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        volunteers = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM volunteers ORDER BY id").fetchall()}
        shifts = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM shifts ORDER BY id").fetchall()}
        avail_rows = conn.execute("SELECT * FROM availability ORDER BY id").fetchall()
        attendance_rows = conn.execute("SELECT * FROM attendance_history ORDER BY id").fetchall()
        conn.close()

        # Build availability lookup: vol_id -> {day -> [(from, until)]}
        avail_map = {}
        for r in avail_rows:
            avail_map.setdefault(r["volunteer_id"], {}).setdefault(r["day_of_week"], []).append(
                (r["available_from"], r["available_until"])
            )

        # Build no-show rates
        att_counts = {}
        for r in attendance_rows:
            vid = r["volunteer_id"]
            att_counts.setdefault(vid, {"total": 0, "no_show": 0})
            att_counts[vid]["total"] += 1
            if r["status"] == "no_show":
                att_counts[vid]["no_show"] += 1
        no_show_rates = {}
        for vid, c in att_counts.items():
            no_show_rates[vid] = round(c["no_show"] / c["total"], 4) if c["total"] > 0 else 0.0

        # Load workspace policy & event briefs
        policy_path = os.path.join(self.workspace, "scheduling_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)

        weather_path = os.path.join(self.workspace, "weather_forecast.json")
        with open(weather_path) as f:
            weather = json.load(f)

        role_cert_path = os.path.join(self.workspace, "role_certification_matrix.csv")
        role_cert_map = {}
        with open(role_cert_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                role_cert_map[row["role"]] = {
                    "required_certifications": row["required_certifications"].split(";") if row["required_certifications"] else [],
                    "min_experience_years": int(row["min_experience_years"]),
                }

        event_briefs = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("event_brief_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    eb = json.load(f)
                    event_briefs[eb["event_id"]] = eb

        no_show_threshold = policy["no_show_threshold"]
        rain_threshold = policy["rain_threshold"]
        normal_backup = policy["normal_backup_count"]
        outdoor_rain_backup = policy["outdoor_rain_backup_count"]

        # ── Criterion 1: weekly_schedule.csv exists and has correct columns (10 pts) ──
        schedule_path = os.path.join(self.workspace, "weekly_schedule.csv")
        expected_cols = ["shift_id", "day", "start_time", "end_time", "event_name",
                         "role", "assigned_volunteer_id", "assigned_volunteer_name"]
        schedule_rows = []
        c1_pass = False
        c1_reason = ""
        if os.path.exists(schedule_path):
            with open(schedule_path) as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames or []
                if all(c in cols for c in expected_cols):
                    schedule_rows = list(reader)
                    c1_pass = True
                else:
                    c1_reason = f"Missing columns. Expected {expected_cols}, got {cols}"
        else:
            c1_reason = "weekly_schedule.csv not found"
        criteria["schedule_format"] = {
            "passed": c1_pass, "score": 10 if c1_pass else 0, "max_score": 10,
            "reason": c1_reason if not c1_pass else "",
        }

        # ── Criterion 2: All shifts covered (10 pts) ──
        assigned_shift_ids = set()
        schedule_by_shift = {}
        for row in schedule_rows:
            try:
                sid = int(row["shift_id"])
                assigned_shift_ids.add(sid)
                schedule_by_shift[sid] = row
            except (ValueError, KeyError):
                pass
        total_shifts = len(shifts)
        covered = len(assigned_shift_ids & set(shifts.keys()))
        c2_pass = covered == total_shifts
        c2_score = round(10 * covered / total_shifts) if total_shifts > 0 else 0
        criteria["all_shifts_covered"] = {
            "passed": c2_pass, "score": c2_score, "max_score": 10,
            "reason": "" if c2_pass else f"Covered {covered}/{total_shifts} shifts",
        }

        # ── Criterion 3: Certification & experience compliance (20 pts) ──
        cert_ok = 0
        cert_total = 0
        for sid, row in schedule_by_shift.items():
            if sid not in shifts:
                continue
            cert_total += 1
            shift = shifts[sid]
            try:
                vid = int(row["assigned_volunteer_id"])
            except (ValueError, KeyError):
                continue
            if vid not in volunteers:
                continue
            vol = volunteers[vid]
            role = shift["role"]
            if role not in role_cert_map:
                continue
            req_certs = set(role_cert_map[role]["required_certifications"])
            min_exp = role_cert_map[role]["min_experience_years"]
            # Additional event cert
            event_id = shift["event_id"]
            eb = event_briefs.get(event_id, {})
            if eb.get("additional_certification"):
                req_certs.add(eb["additional_certification"])
            v_certs = set(vol["certifications"].split(","))
            if req_certs.issubset(v_certs) and vol["experience_years"] >= min_exp:
                cert_ok += 1

        c3_score = round(20 * cert_ok / cert_total) if cert_total > 0 else 0
        c3_pass = cert_ok == cert_total and cert_total > 0
        criteria["certification_compliance"] = {
            "passed": c3_pass, "score": c3_score, "max_score": 20,
            "reason": "" if c3_pass else f"{cert_ok}/{cert_total} assignments meet cert/exp requirements",
        }

        # ── Criterion 4: Availability compliance (15 pts) ──
        avail_ok = 0
        avail_total = 0
        for sid, row in schedule_by_shift.items():
            if sid not in shifts:
                continue
            avail_total += 1
            shift = shifts[sid]
            try:
                vid = int(row["assigned_volunteer_id"])
            except (ValueError, KeyError):
                continue
            day_windows = avail_map.get(vid, {}).get(shift["day_of_week"], [])
            if _windows_cover(day_windows, shift["start_time"], shift["end_time"]):
                avail_ok += 1

        c4_score = round(15 * avail_ok / avail_total) if avail_total > 0 else 0
        c4_pass = avail_ok == avail_total and avail_total > 0
        criteria["availability_compliance"] = {
            "passed": c4_pass, "score": c4_score, "max_score": 15,
            "reason": "" if c4_pass else f"{avail_ok}/{avail_total} assignments respect availability",
        }

        # ── Criterion 5: Max shifts per week not exceeded (10 pts) ──
        vol_shift_count = {}
        for sid, row in schedule_by_shift.items():
            try:
                vid = int(row["assigned_volunteer_id"])
                vol_shift_count[vid] = vol_shift_count.get(vid, 0) + 1
            except (ValueError, KeyError):
                pass
        violations_5 = 0
        for vid, count in vol_shift_count.items():
            if vid in volunteers and count > volunteers[vid]["max_shifts_per_week"]:
                violations_5 += 1
        c5_pass = violations_5 == 0
        c5_score = 10 if c5_pass else max(0, 10 - violations_5 * 2)
        criteria["max_shifts_compliance"] = {
            "passed": c5_pass, "score": c5_score, "max_score": 10,
            "reason": "" if c5_pass else f"{violations_5} volunteers exceed max_shifts_per_week",
        }

        # ── Criterion 6: No time conflicts (10 pts) ──
        # Group primary assignments by volunteer and day
        vol_day_shifts = {}
        for sid, row in schedule_by_shift.items():
            if sid not in shifts:
                continue
            try:
                vid = int(row["assigned_volunteer_id"])
            except (ValueError, KeyError):
                continue
            shift = shifts[sid]
            key = (vid, shift["day_of_week"])
            vol_day_shifts.setdefault(key, []).append(shift)

        conflict_count = 0
        for key, slist in vol_day_shifts.items():
            for i in range(len(slist)):
                for j in range(i + 1, len(slist)):
                    if _shifts_overlap(slist[i]["start_time"], slist[i]["end_time"],
                                       slist[j]["start_time"], slist[j]["end_time"]):
                        conflict_count += 1
        c6_pass = conflict_count == 0
        c6_score = 10 if c6_pass else max(0, 10 - conflict_count * 2)
        criteria["no_time_conflicts"] = {
            "passed": c6_pass, "score": c6_score, "max_score": 10,
            "reason": "" if c6_pass else f"{conflict_count} time conflicts detected",
        }

        # ── Criterion 7: No-show threshold for primaries (10 pts) ──
        threshold_ok = 0
        threshold_total = 0
        for sid, row in schedule_by_shift.items():
            if sid not in shifts:
                continue
            threshold_total += 1
            try:
                vid = int(row["assigned_volunteer_id"])
            except (ValueError, KeyError):
                continue
            rate = no_show_rates.get(vid, 0.0)
            if rate <= no_show_threshold:
                threshold_ok += 1

        c7_score = round(10 * threshold_ok / threshold_total) if threshold_total > 0 else 0
        c7_pass = threshold_ok == threshold_total and threshold_total > 0
        criteria["noshow_threshold_compliance"] = {
            "passed": c7_pass, "score": c7_score, "max_score": 10,
            "reason": "" if c7_pass else f"{threshold_ok}/{threshold_total} primaries meet no-show threshold",
        }

        # ── Criterion 8: backup_assignments.csv format and correct backup counts (15 pts) ──
        backup_path = os.path.join(self.workspace, "backup_assignments.csv")
        backup_expected_cols = ["shift_id", "backup_rank", "volunteer_id", "volunteer_name", "reliability_score"]
        backup_rows = []
        c8_pass = False
        c8_reason = ""
        c8_score = 0

        if os.path.exists(backup_path):
            with open(backup_path) as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames or []
                if all(c in cols for c in backup_expected_cols):
                    backup_rows = list(reader)
                    # Check backup counts per shift
                    backup_counts = {}
                    for br in backup_rows:
                        try:
                            bsid = int(br["shift_id"])
                            backup_counts[bsid] = backup_counts.get(bsid, 0) + 1
                        except (ValueError, KeyError):
                            pass

                    count_ok = 0
                    count_total = 0
                    for sid, shift in shifts.items():
                        count_total += 1
                        day = shift["day_of_week"]
                        is_outdoor = bool(shift["is_outdoor"])
                        rain_prob = weather.get(day, {}).get("rain_probability", 0)
                        if is_outdoor and rain_prob > rain_threshold:
                            expected_backups = outdoor_rain_backup
                        else:
                            expected_backups = normal_backup
                        actual = backup_counts.get(sid, 0)
                        if actual >= expected_backups:
                            count_ok += 1

                    c8_score = round(15 * count_ok / count_total) if count_total > 0 else 0
                    c8_pass = count_ok == count_total and count_total > 0
                    if not c8_pass:
                        c8_reason = f"{count_ok}/{count_total} shifts have correct backup count"
                else:
                    c8_reason = f"Missing columns. Expected {backup_expected_cols}, got {cols}"
        else:
            c8_reason = "backup_assignments.csv not found"

        criteria["backup_assignments"] = {
            "passed": c8_pass, "score": c8_score, "max_score": 15,
            "reason": c8_reason if not c8_pass else "",
        }

        # ── Criterion 9: Summary statistics in response (10 pts) ──
        # Expected: total_shifts_scheduled, coverage_percentage, average_primary_reliability
        c9_score = 0
        c9_parts = []
        # total_shifts_scheduled = number of rows in schedule
        total_scheduled = len(schedule_by_shift)
        # coverage_percentage = (total_scheduled / total_shifts) * 100, 1 decimal
        coverage_pct = round(100.0 * total_scheduled / total_shifts, 1) if total_shifts > 0 else 0.0
        # average_primary_reliability = mean of (1 - no_show_rate) of primaries, 2 decimals
        reliabilities = []
        for sid, row in schedule_by_shift.items():
            try:
                vid = int(row["assigned_volunteer_id"])
                reliabilities.append(1.0 - no_show_rates.get(vid, 0.0))
            except (ValueError, KeyError):
                pass
        avg_reliability = round(sum(reliabilities) / len(reliabilities), 2) if reliabilities else 0.0

        # Check if action contains these values
        action_lower = action.lower().replace(" ", "") if action else ""
        if str(total_scheduled) in action:
            c9_score += 3
            c9_parts.append("total_shifts_scheduled")
        if f"{coverage_pct}" in action:
            c9_score += 3
            c9_parts.append("coverage_percentage")
        if f"{avg_reliability:.2f}" in action:
            c9_score += 4
            c9_parts.append("average_primary_reliability")
        c9_pass = c9_score == 10
        criteria["summary_statistics"] = {
            "passed": c9_pass, "score": c9_score, "max_score": 10,
            "reason": "" if c9_pass else f"Found: {c9_parts}; missing others. Expected total={total_scheduled}, coverage={coverage_pct}%, avg_reliability={avg_reliability:.2f}",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score if max_score > 0 else 0.0, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ── verify ─────────────────────────────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        # ── 1. Read workspace files ──
        with open(os.path.join(self.workspace, "scheduling_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "weather_forecast.json")) as f:
            weather = json.load(f)

        role_cert_map = {}
        with open(os.path.join(self.workspace, "role_certification_matrix.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                role_cert_map[row["role"]] = {
                    "required_certifications": row["required_certifications"].split(";") if row["required_certifications"] else [],
                    "min_experience_years": int(row["min_experience_years"]),
                }

        event_briefs = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("event_brief_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    eb = json.load(f)
                    event_briefs[eb["event_id"]] = eb

        # Read backup rules (for completeness, rules are encoded in logic below)
        with open(os.path.join(self.workspace, "backup_priority_rules.md")) as f:
            _ = f.read()

        no_show_threshold = policy["no_show_threshold"]
        rain_threshold = policy["rain_threshold"]
        normal_backup_count = policy["normal_backup_count"]
        outdoor_rain_backup_count = policy["outdoor_rain_backup_count"]

        # ── 2. Get all volunteers via tool (paginated) ──
        all_volunteers = []
        page = 1
        while True:
            result = json.loads(self.tools["list_volunteers"](page=page, page_size=20))
            all_volunteers.extend(result["volunteers"])
            if not result["has_more"]:
                break
            page += 1

        # ── 3. Get all shifts by day via tool ──
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        all_shifts = []
        for day in days:
            page = 1
            while True:
                result = json.loads(self.tools["list_shifts"](day_of_week=day, page=page, page_size=20))
                all_shifts.extend(result["shifts"])
                if not result["has_more"]:
                    break
                page += 1

        # ── 4. Get attendance summaries and availability for all volunteers ──
        attendance = {}
        vol_availability = {}
        for v in all_volunteers:
            att = json.loads(self.tools["get_attendance_summary"](volunteer_id=v["id"]))
            attendance[v["id"]] = att

            avail = json.loads(self.tools["get_volunteer_availability"](volunteer_id=v["id"]))
            # Index by day
            by_day = {}
            for w in avail["windows"]:
                by_day.setdefault(w["day_of_week"], []).append(
                    (w["available_from"], w["available_until"])
                )
            vol_availability[v["id"]] = by_day

        # ── 5. Sort shifts by shift_id (deterministic) ──
        all_shifts.sort(key=lambda s: s["shift_id"])

        # ── 6. Greedy assignment ──
        vol_shift_count = {v["id"]: 0 for v in all_volunteers}
        # Track primary assignments per (vol_id, day) -> list of (start, end)
        vol_day_primaries = {}

        schedule_rows = []
        backup_rows = []

        for shift in all_shifts:
            sid = shift["shift_id"]
            role = shift["role"]
            day = shift["day_of_week"]
            s_start = shift["start_time"]
            s_end = shift["end_time"]
            event_id = shift["event_id"]
            is_outdoor = shift["is_outdoor"]

            # Determine cert requirements
            base_req = role_cert_map.get(role, {"required_certifications": [], "min_experience_years": 0})
            req_certs = set(base_req["required_certifications"])
            min_exp = base_req["min_experience_years"]
            eb = event_briefs.get(event_id, {})
            if eb.get("additional_certification"):
                req_certs.add(eb["additional_certification"])

            # Weather-based backup count
            rain_prob = weather.get(day, {}).get("rain_probability", 0)
            if is_outdoor and rain_prob > rain_threshold:
                num_backups = outdoor_rain_backup_count
            else:
                num_backups = normal_backup_count

            # Find eligible volunteers
            eligible = []
            for v in all_volunteers:
                vid = v["id"]
                v_certs = set(v["certifications"].split(","))
                if not req_certs.issubset(v_certs):
                    continue
                if v["experience_years"] < min_exp:
                    continue

                # Check availability
                day_windows = vol_availability.get(vid, {}).get(day, [])
                if not _windows_cover(day_windows, s_start, s_end):
                    continue

                # Check max shifts (only for primary candidacy consideration, not eligibility for backup)
                at_max = vol_shift_count[vid] >= v["max_shifts_per_week"]

                # Check time conflict with existing primary assignments
                existing = vol_day_primaries.get((vid, day), [])
                has_conflict = any(
                    _shifts_overlap(s_start, s_end, ex_s, ex_e)
                    for ex_s, ex_e in existing
                )

                no_show_rate = attendance[vid]["no_show_rate"]
                reliability = round(1.0 - no_show_rate, 4)
                eligible.append({
                    "id": vid,
                    "name": v["name"],
                    "reliability": reliability,
                    "no_show_rate": no_show_rate,
                    "at_max": at_max,
                    "has_conflict": has_conflict,
                })

            # Sort by reliability DESC, then id ASC
            eligible.sort(key=lambda x: (-x["reliability"], x["id"]))

            # Select primary: must not be at_max, must not have conflict, must be below no-show threshold
            primary = None
            for e in eligible:
                if not e["at_max"] and not e["has_conflict"] and e["no_show_rate"] <= no_show_threshold:
                    primary = e
                    break

            if primary is None:
                # Fallback: relax no-show threshold (pick best available)
                for e in eligible:
                    if not e["at_max"] and not e["has_conflict"]:
                        primary = e
                        break

            if primary is not None:
                vol_shift_count[primary["id"]] += 1
                vol_day_primaries.setdefault((primary["id"], day), []).append((s_start, s_end))

                schedule_rows.append({
                    "shift_id": sid,
                    "day": day,
                    "start_time": s_start,
                    "end_time": s_end,
                    "event_name": shift["event_name"],
                    "role": role,
                    "assigned_volunteer_id": primary["id"],
                    "assigned_volunteer_name": primary["name"],
                })

                # Select backups: eligible (including high no-show), exclude primary,
                # exclude those with time conflicts on primary assignments
                backup_candidates = []
                for e in eligible:
                    if e["id"] == primary["id"]:
                        continue
                    if e["has_conflict"]:
                        continue
                    backup_candidates.append(e)

                for rank, bc in enumerate(backup_candidates[:num_backups], 1):
                    backup_rows.append({
                        "shift_id": sid,
                        "backup_rank": rank,
                        "volunteer_id": bc["id"],
                        "volunteer_name": bc["name"],
                        "reliability_score": f"{bc['reliability']:.2f}",
                    })

        # ── 7. Write deliverables ──
        schedule_path = os.path.join(self.workspace, "weekly_schedule.csv")
        with open(schedule_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "shift_id", "day", "start_time", "end_time", "event_name",
                "role", "assigned_volunteer_id", "assigned_volunteer_name",
            ])
            writer.writeheader()
            writer.writerows(schedule_rows)

        backup_path = os.path.join(self.workspace, "backup_assignments.csv")
        with open(backup_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "shift_id", "backup_rank", "volunteer_id", "volunteer_name", "reliability_score",
            ])
            writer.writeheader()
            writer.writerows(backup_rows)

        # ── 8. Construct action string ──
        total_scheduled = len(schedule_rows)
        total_shifts = len(all_shifts)
        coverage_pct = round(100.0 * total_scheduled / total_shifts, 1) if total_shifts > 0 else 0.0
        reliabilities = []
        for sr in schedule_rows:
            vid = sr["assigned_volunteer_id"]
            reliabilities.append(1.0 - attendance[vid]["no_show_rate"])
        avg_rel = round(sum(reliabilities) / len(reliabilities), 2) if reliabilities else 0.0

        action = (
            f"Weekly volunteer schedule complete.\n"
            f"Total shifts scheduled: {total_scheduled}\n"
            f"Coverage percentage: {coverage_pct}%\n"
            f"Average primary reliability: {avg_rel:.2f}\n"
            f"The weekly_schedule.csv and backup_assignments.csv have been saved."
        )

        return self.step(action)
