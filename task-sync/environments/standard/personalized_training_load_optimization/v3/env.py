import os
import json
import csv
import sqlite3
import yaml
import glob as glob_mod
from typing import Tuple, Dict, List, Any
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
        }
        return func
    return decorator


# ---------------------------------------------------------------------------
# Constants shared across methods
# ---------------------------------------------------------------------------
TARGET_WEEK_START = "2025-03-10"
ALL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TRAINING_WINDOWS = [
    ("06:00", "08:00"), ("10:00", "12:00"),
    ("14:00", "16:00"), ("18:00", "20:00"),
]
INTENSITY_ORDER = ["recovery", "low", "moderate", "high", "maximal"]


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

    # -----------------------------------------------------------------------
    # Tool methods
    # -----------------------------------------------------------------------

    @tool(
        description="List athletes with basic profile information. Returns a paginated list.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)."
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of athletes per page (max 20)."
                }
            },
            "required": ["page", "page_size"]
        }
    )
    def list_athletes(self, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM athletes")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT athlete_id, name, age, sport, position, team, academic_year "
            "FROM athletes ORDER BY athlete_id LIMIT ? OFFSET ?",
            (page_size, offset)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "athletes": rows,
            "page": page,
            "page_size": page_size,
            "total_athletes": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get detailed GPS training session data for a specific athlete within a date range.",
        parameters={
            "type": "object",
            "properties": {
                "athlete_id": {
                    "type": "integer",
                    "description": "The athlete's unique ID."
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (inclusive) in YYYY-MM-DD format."
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (inclusive) in YYYY-MM-DD format."
                }
            },
            "required": ["athlete_id", "start_date", "end_date"]
        }
    )
    def get_gps_data(self, athlete_id: int, start_date: str, end_date: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT session_date, session_type, total_distance_m, "
            "high_speed_running_m, sprint_count, accelerations, decelerations, "
            "max_speed_kmh, duration_min, player_load "
            "FROM gps_sessions WHERE athlete_id = ? AND session_date >= ? AND session_date <= ? "
            "ORDER BY session_date",
            (athlete_id, start_date, end_date)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"athlete_id": athlete_id, "sessions": rows, "count": len(rows)}

    @tool(
        description="Get the most recent wellness survey for a specific athlete.",
        parameters={
            "type": "object",
            "properties": {
                "athlete_id": {
                    "type": "integer",
                    "description": "The athlete's unique ID."
                }
            },
            "required": ["athlete_id"]
        }
    )
    def get_wellness_data(self, athlete_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT survey_date, sleep_hours, sleep_quality, fatigue, soreness, stress, mood "
            "FROM wellness_surveys WHERE athlete_id = ? ORDER BY survey_date DESC LIMIT 1",
            (athlete_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return {"athlete_id": athlete_id, "survey": dict(row)}
        return {"athlete_id": athlete_id, "survey": None}

    @tool(
        description="Get all musculoskeletal screening results for a specific athlete.",
        parameters={
            "type": "object",
            "properties": {
                "athlete_id": {
                    "type": "integer",
                    "description": "The athlete's unique ID."
                }
            },
            "required": ["athlete_id"]
        }
    )
    def get_msk_results(self, athlete_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT screening_date, body_region, rom_score, strength_score, "
            "asymmetry_pct, pain_level, risk_category "
            "FROM msk_screenings WHERE athlete_id = ? ORDER BY screening_date DESC",
            (athlete_id,)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"athlete_id": athlete_id, "screenings": rows, "count": len(rows)}

    @tool(
        description="Get an athlete's academic timetable for a specific day of the week.",
        parameters={
            "type": "object",
            "properties": {
                "athlete_id": {
                    "type": "integer",
                    "description": "The athlete's unique ID."
                },
                "day_of_week": {
                    "type": "string",
                    "description": "Day of the week (e.g. 'Monday', 'Tuesday', etc.)."
                }
            },
            "required": ["athlete_id", "day_of_week"]
        }
    )
    def get_academic_schedule(self, athlete_id: int, day_of_week: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT day_of_week, start_time, end_time, course_name, is_mandatory "
            "FROM academic_timetable WHERE athlete_id = ? AND day_of_week = ? "
            "ORDER BY start_time",
            (athlete_id, day_of_week)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"athlete_id": athlete_id, "day": day_of_week, "classes": rows}

    @tool(
        description="Get an athlete's full weekly academic timetable (all days).",
        parameters={
            "type": "object",
            "properties": {
                "athlete_id": {
                    "type": "integer",
                    "description": "The athlete's unique ID."
                }
            },
            "required": ["athlete_id"]
        }
    )
    def get_full_academic_schedule(self, athlete_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT day_of_week, start_time, end_time, course_name, is_mandatory "
            "FROM academic_timetable WHERE athlete_id = ? "
            "ORDER BY CASE day_of_week "
            "WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3 "
            "WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 "
            "WHEN 'Saturday' THEN 6 WHEN 'Sunday' THEN 7 END, start_time",
            (athlete_id,)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"athlete_id": athlete_id, "timetable": rows}

    # -----------------------------------------------------------------------
    # Helpers for step / verify
    # -----------------------------------------------------------------------

    def _load_config(self, filename):
        path = os.path.join(self.workspace, filename)
        with open(path, "r") as f:
            if filename.endswith(".yaml"):
                return yaml.safe_load(f)
            elif filename.endswith(".json"):
                return json.load(f)
            else:
                return f.read()

    def _compute_acwr(self, athlete_id: int):
        """Compute ACWR from GPS data: acute (last 7 days) vs chronic (last 28 days)."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        target = datetime.strptime(TARGET_WEEK_START, "%Y-%m-%d")
        acute_start = (target - timedelta(days=7)).strftime("%Y-%m-%d")
        chronic_start = (target - timedelta(days=28)).strftime("%Y-%m-%d")
        chronic_end = (target - timedelta(days=1)).strftime("%Y-%m-%d")

        cur.execute(
            "SELECT SUM(player_load) FROM gps_sessions "
            "WHERE athlete_id = ? AND session_date >= ? AND session_date <= ?",
            (athlete_id, acute_start, chronic_end)
        )
        acute_load = cur.fetchone()[0] or 0.0

        cur.execute(
            "SELECT SUM(player_load) FROM gps_sessions "
            "WHERE athlete_id = ? AND session_date >= ? AND session_date <= ?",
            (athlete_id, chronic_start, chronic_end)
        )
        chronic_load = cur.fetchone()[0] or 0.0
        conn.close()

        # Chronic = average weekly load over 4 weeks
        chronic_weekly = chronic_load / 4.0 if chronic_load > 0 else 0.0
        if chronic_weekly < 0.01:
            return None  # undefined
        return round(acute_load / chronic_weekly, 2)

    def _compute_ground_truth(self):
        """Compute ground-truth risk assessment and constraints for every athlete."""
        thresholds = self._load_config("risk_thresholds.json")
        policy = self._load_config("load_management_policy.yaml")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM athletes ORDER BY athlete_id")
        athletes = [dict(r) for r in cur.fetchall()]

        gt = {}
        for ath in athletes:
            aid = ath["athlete_id"]

            # --- ACWR risk ---
            acwr = self._compute_acwr(aid)
            acwr_low = thresholds["acwr"]["low_risk"]
            if acwr is None or acwr < thresholds["acwr"]["high_risk_low"][1] or acwr >= thresholds["acwr"]["high_risk_high"][0]:
                if acwr is not None and acwr_low[0] <= acwr <= acwr_low[1]:
                    acwr_risk = "low"
                elif acwr is None:
                    acwr_risk = "high"
                else:
                    acwr_risk = "high"
            else:
                acwr_risk = "low"

            # Re-derive cleanly
            if acwr is None:
                acwr_risk = "high"
            elif acwr_low[0] <= acwr <= acwr_low[1]:
                acwr_risk = "low"
            elif (thresholds["acwr"]["moderate_risk_low"][0] <= acwr < thresholds["acwr"]["moderate_risk_low"][1]) or \
                 (thresholds["acwr"]["moderate_risk_high"][0] < acwr <= thresholds["acwr"]["moderate_risk_high"][1]):
                acwr_risk = "moderate"
            else:
                acwr_risk = "high"

            # --- Wellness risk ---
            cur.execute(
                "SELECT fatigue, soreness, stress, sleep_quality FROM wellness_surveys "
                "WHERE athlete_id = ? ORDER BY survey_date DESC LIMIT 1", (aid,)
            )
            wrow = cur.fetchone()
            wellness_risk = "low"
            wellness_composite = 0
            if wrow:
                fatigue, soreness, stress, sleep_q = wrow["fatigue"], wrow["soreness"], wrow["stress"], wrow["sleep_quality"]
                wellness_composite = fatigue + soreness + stress
                if wellness_composite >= thresholds["wellness"]["composite_risk_threshold"]:
                    wellness_risk = "high"
                elif fatigue >= thresholds["wellness"]["fatigue_threshold"] or \
                     soreness >= thresholds["wellness"]["soreness_threshold"] or \
                     sleep_q <= thresholds["wellness"]["sleep_quality_threshold"]:
                    wellness_risk = "moderate"

            # --- MSK risk ---
            cur.execute(
                "SELECT body_region, pain_level, asymmetry_pct FROM msk_screenings "
                "WHERE athlete_id = ?", (aid,)
            )
            msk_rows = cur.fetchall()
            msk_risk = "low"
            critical = thresholds["msk"]["critical_regions"]
            for mr in msk_rows:
                region = mr["body_region"]
                pain = mr["pain_level"]
                asym = mr["asymmetry_pct"]
                if region in critical and (pain >= thresholds["msk"]["high_risk_pain_level"] or asym >= thresholds["msk"]["asymmetry_threshold"]):
                    msk_risk = "high"
                    break
                if pain >= 4 or asym >= 10:
                    msk_risk = "moderate"

            # --- RPE risk (from workspace files) ---
            rpe_risk = "low"
            rpe_avg = None
            report_path = os.path.join(self.workspace, f"athlete_report_{aid}.json")
            if os.path.exists(report_path):
                with open(report_path) as f:
                    report = json.load(f)
                rpe_avg = report.get("rpe_7day_avg")
                if rpe_avg is not None:
                    if rpe_avg >= thresholds["rpe"]["high_threshold"]:
                        rpe_risk = "high"
                    elif rpe_avg >= thresholds["rpe"]["moderate_threshold"]:
                        rpe_risk = "moderate"

            # --- Overall risk ---
            risk_levels = {"low": 0, "moderate": 1, "high": 2}
            overall_val = max(risk_levels[acwr_risk], risk_levels[wellness_risk],
                              risk_levels[msk_risk], risk_levels[rpe_risk])
            overall_risk = ["low", "moderate", "high"][overall_val]

            # --- Constraints from policy ---
            adj = policy["risk_adjustments"][overall_risk]

            # --- Academic conflicts ---
            cur.execute(
                "SELECT day_of_week, start_time, end_time, is_mandatory "
                "FROM academic_timetable WHERE athlete_id = ?", (aid,)
            )
            acad_rows = cur.fetchall()
            blocked_windows = {}  # day -> set of blocked window indices
            for ar in acad_rows:
                if not ar["is_mandatory"]:
                    continue
                day = ar["day_of_week"]
                cs = ar["start_time"]
                ce = ar["end_time"]
                if day not in blocked_windows:
                    blocked_windows[day] = set()
                for wi, (ws, we) in enumerate(TRAINING_WINDOWS):
                    if cs < we and ce > ws:
                        blocked_windows[day].add(wi)

            gt[aid] = {
                "name": ath["name"],
                "sport": ath["sport"],
                "position": ath["position"],
                "acwr": acwr,
                "acwr_risk": acwr_risk,
                "wellness_composite": wellness_composite,
                "wellness_risk": wellness_risk,
                "msk_risk": msk_risk,
                "rpe_avg": rpe_avg,
                "rpe_risk": rpe_risk,
                "overall_risk": overall_risk,
                "max_sessions": adj["max_sessions"],
                "max_intensity": adj["max_intensity"],
                "mandatory_rest_days": adj["mandatory_rest_days"],
                "exclude_session_types": adj["exclude_session_types"],
                "blocked_windows": blocked_windows,  # day -> set of window indices
            }

        conn.close()
        return gt

    # -----------------------------------------------------------------------
    # step
    # -----------------------------------------------------------------------

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        gt = self._compute_ground_truth()
        all_ids = sorted(gt.keys())
        n_athletes = len(all_ids)

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ---- Criterion 1: weekly_training_plan.csv format (10 pts) ----
        c1_max = 10
        c1_score = 0
        plan_path = os.path.join(self.workspace, "weekly_training_plan.csv")
        plan_rows = []
        required_cols = {"athlete_id", "athlete_name", "day", "session_start",
                         "session_end", "session_type", "intensity", "duration_min"}
        if os.path.exists(plan_path):
            with open(plan_path, "r") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and required_cols.issubset(set(reader.fieldnames)):
                    c1_score = c1_max
                    plan_rows = list(reader)
                else:
                    c1_score = 3  # file exists but wrong columns
        eval_criteria["plan_file_format"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": "" if c1_score == c1_max else "Missing or incorrect columns in weekly_training_plan.csv"
        }

        # ---- Criterion 2: athlete_risk_report.csv format and accuracy (20 pts) ----
        c2_max = 20
        c2_score = 0
        risk_path = os.path.join(self.workspace, "athlete_risk_report.csv")
        risk_rows = []
        risk_required = {"athlete_id", "athlete_name", "acwr_value", "acwr_risk",
                         "wellness_risk", "msk_risk", "overall_risk"}
        if os.path.exists(risk_path):
            with open(risk_path, "r") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and risk_required.issubset(set(reader.fieldnames)):
                    risk_rows = list(reader)
                    # Check accuracy
                    risk_by_id = {}
                    for rr in risk_rows:
                        try:
                            risk_by_id[int(rr["athlete_id"])] = rr
                        except (ValueError, KeyError):
                            continue
                    correct = 0
                    for aid in all_ids:
                        if aid in risk_by_id:
                            rr = risk_by_id[aid]
                            # Check overall risk
                            if rr.get("overall_risk", "").strip().lower() == gt[aid]["overall_risk"]:
                                correct += 1
                    if n_athletes > 0:
                        accuracy = correct / n_athletes
                        c2_score = round(5 + 15 * accuracy)  # 5 pts for format, up to 15 for accuracy
                    else:
                        c2_score = 5
                else:
                    c2_score = 2  # file exists but wrong cols
        eval_criteria["risk_report_accuracy"] = {
            "passed": c2_score >= 18,
            "score": c2_score,
            "max_score": c2_max,
            "reason": "" if c2_score >= 18 else f"Risk report accuracy: {c2_score}/{c2_max}"
        }

        # ---- Criterion 3: Complete athlete coverage (15 pts) ----
        c3_max = 15
        c3_score = 0
        plan_by_athlete = {}
        for row in plan_rows:
            try:
                aid = int(row["athlete_id"])
                plan_by_athlete.setdefault(aid, []).append(row)
            except (ValueError, KeyError):
                continue
        covered = sum(1 for aid in all_ids if aid in plan_by_athlete and len(plan_by_athlete[aid]) > 0)
        if n_athletes > 0:
            coverage = covered / n_athletes
            c3_score = round(c3_max * coverage)
        eval_criteria["athlete_coverage"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": "" if c3_score == c3_max else f"Only {covered}/{n_athletes} athletes covered"
        }

        # ---- Criterion 4: Academic conflict avoidance (20 pts) ----
        c4_max = 20
        conflicts = 0
        total_sessions = 0
        for aid in all_ids:
            sessions = plan_by_athlete.get(aid, [])
            blocked = gt[aid]["blocked_windows"]
            for sess in sessions:
                total_sessions += 1
                day = sess.get("day", "")
                s_start = sess.get("session_start", "")
                if day in blocked:
                    for wi, (ws, we) in enumerate(TRAINING_WINDOWS):
                        if ws == s_start and wi in blocked[day]:
                            conflicts += 1
                            break
        if total_sessions > 0:
            conflict_rate = conflicts / total_sessions
            c4_score = round(c4_max * max(0, 1 - conflict_rate * 5))  # penalize heavily
        else:
            c4_score = 0
        eval_criteria["academic_conflict_avoidance"] = {
            "passed": conflicts == 0,
            "score": c4_score,
            "max_score": c4_max,
            "reason": "" if conflicts == 0 else f"{conflicts} sessions conflict with mandatory classes"
        }

        # ---- Criterion 5: Load management compliance (20 pts) ----
        c5_max = 20
        violations = 0
        checks = 0
        for aid in all_ids:
            sessions = plan_by_athlete.get(aid, [])
            info = gt[aid]
            n_sess = len(sessions)
            checks += 1

            # Max sessions check
            if n_sess > info["max_sessions"]:
                violations += 1

            # Rest days check
            days_with_sessions = set(s.get("day", "") for s in sessions)
            rest_days = 7 - len(days_with_sessions)
            if rest_days < info["mandatory_rest_days"]:
                violations += 1
            checks += 1

            # Max intensity check
            max_int_idx = INTENSITY_ORDER.index(info["max_intensity"])
            for s in sessions:
                intensity = s.get("intensity", "").strip().lower()
                if intensity in INTENSITY_ORDER:
                    if INTENSITY_ORDER.index(intensity) > max_int_idx:
                        violations += 1
                        break
            checks += 1

            # Excluded session types
            for s in sessions:
                st = s.get("session_type", "").strip().lower()
                if st in [x.lower() for x in info["exclude_session_types"]]:
                    violations += 1
                    break
            checks += 1

        if checks > 0:
            compliance = max(0, 1 - violations / checks)
            c5_score = round(c5_max * compliance)
        else:
            c5_score = 0
        eval_criteria["load_management_compliance"] = {
            "passed": violations == 0,
            "score": c5_score,
            "max_score": c5_max,
            "reason": "" if violations == 0 else f"{violations} load management violations"
        }

        # ---- Criterion 6: Response summary accuracy (15 pts) ----
        c6_max = 15
        c6_score = 0
        gt_counts = {"high": 0, "moderate": 0, "low": 0}
        gt_high_names = set()
        for aid in all_ids:
            r = gt[aid]["overall_risk"]
            gt_counts[r] += 1
            if r == "high":
                gt_high_names.add(gt[aid]["name"])

        action_lower = action.lower() if action else ""
        # Check if counts are mentioned
        count_matches = 0
        for level in ["high", "moderate", "low"]:
            if str(gt_counts[level]) in action:
                count_matches += 1
        if count_matches >= 2:
            c6_score += 7

        # Check if high-risk names are mentioned
        if gt_high_names:
            names_found = sum(1 for n in gt_high_names if n.lower() in action_lower)
            name_ratio = names_found / len(gt_high_names)
            c6_score += round(8 * name_ratio)
        else:
            # No high-risk athletes; give full credit if "no high-risk" or "0 high" mentioned
            if "0" in action and "high" in action_lower:
                c6_score += 8
            else:
                c6_score += 4  # partial

        eval_criteria["response_summary"] = {
            "passed": c6_score >= 13,
            "score": c6_score,
            "max_score": c6_max,
            "reason": "" if c6_score >= 13 else "Response missing risk category counts or high-risk names"
        }

        # ---- Aggregate ----
        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score if max_score > 0 else 0.0, info

    # -----------------------------------------------------------------------
    # verify
    # -----------------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as csv_mod

        # --- Load config files from workspace ---
        with open(os.path.join(self.workspace, "risk_thresholds.json")) as f:
            thresholds = json.load(f)
        with open(os.path.join(self.workspace, "load_management_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "session_templates.json")) as f:
            templates = json.load(f)
        with open(os.path.join(self.workspace, "scheduling_rules.txt")) as f:
            rules_text = f.read()

        # --- Discover all athletes via tool ---
        page = 1
        all_athletes = []
        while True:
            result = self.tools["list_athletes"](page=page, page_size=20)
            all_athletes.extend(result["athletes"])
            if page >= result["total_pages"]:
                break
            page += 1

        target = datetime.strptime(TARGET_WEEK_START, "%Y-%m-%d")
        acute_start = (target - timedelta(days=7)).strftime("%Y-%m-%d")
        chronic_start = (target - timedelta(days=28)).strftime("%Y-%m-%d")
        chronic_end = (target - timedelta(days=1)).strftime("%Y-%m-%d")

        risk_rows = []
        schedule_rows = []

        for ath in all_athletes:
            aid = ath["athlete_id"]
            aname = ath["name"]
            sport = ath["sport"]
            position = ath["position"]

            # --- GPS data via tool ---
            gps_result = self.tools["get_gps_data"](
                athlete_id=aid, start_date=chronic_start, end_date=chronic_end
            )
            sessions = gps_result["sessions"]

            # ACWR calculation
            acute_load = sum(
                s["player_load"] for s in sessions if s["session_date"] >= acute_start
            )
            chronic_load = sum(s["player_load"] for s in sessions)
            chronic_weekly = chronic_load / 4.0 if chronic_load > 0 else 0.0
            if chronic_weekly < 0.01:
                acwr = None
                acwr_risk = "high"
            else:
                acwr = round(acute_load / chronic_weekly, 2)
                lo = thresholds["acwr"]["low_risk"]
                if lo[0] <= acwr <= lo[1]:
                    acwr_risk = "low"
                elif (thresholds["acwr"]["moderate_risk_low"][0] <= acwr < thresholds["acwr"]["moderate_risk_low"][1]) or \
                     (thresholds["acwr"]["moderate_risk_high"][0] < acwr <= thresholds["acwr"]["moderate_risk_high"][1]):
                    acwr_risk = "moderate"
                else:
                    acwr_risk = "high"

            # --- Wellness via tool ---
            well_result = self.tools["get_wellness_data"](athlete_id=aid)
            survey = well_result["survey"]
            wellness_risk = "low"
            wellness_composite = 0
            if survey:
                fatigue = survey["fatigue"]
                soreness = survey["soreness"]
                stress = survey["stress"]
                sleep_q = survey["sleep_quality"]
                wellness_composite = fatigue + soreness + stress
                if wellness_composite >= thresholds["wellness"]["composite_risk_threshold"]:
                    wellness_risk = "high"
                elif fatigue >= thresholds["wellness"]["fatigue_threshold"] or \
                     soreness >= thresholds["wellness"]["soreness_threshold"] or \
                     sleep_q <= thresholds["wellness"]["sleep_quality_threshold"]:
                    wellness_risk = "moderate"

            # --- MSK via tool ---
            msk_result = self.tools["get_msk_results"](athlete_id=aid)
            msk_risk = "low"
            critical = thresholds["msk"]["critical_regions"]
            for scr in msk_result["screenings"]:
                region = scr["body_region"]
                pain = scr["pain_level"]
                asym = scr["asymmetry_pct"]
                if region in critical and (pain >= thresholds["msk"]["high_risk_pain_level"] or asym >= thresholds["msk"]["asymmetry_threshold"]):
                    msk_risk = "high"
                    break
                if pain >= 4 or asym >= 10:
                    msk_risk = "moderate"

            # --- RPE from workspace file ---
            rpe_risk = "low"
            rpe_avg = None
            report_path = os.path.join(self.workspace, f"athlete_report_{aid}.json")
            if os.path.exists(report_path):
                with open(report_path) as f:
                    report = json.load(f)
                rpe_avg = report.get("rpe_7day_avg")
                if rpe_avg is not None:
                    if rpe_avg >= thresholds["rpe"]["high_threshold"]:
                        rpe_risk = "high"
                    elif rpe_avg >= thresholds["rpe"]["moderate_threshold"]:
                        rpe_risk = "moderate"

            # --- Overall risk ---
            risk_map = {"low": 0, "moderate": 1, "high": 2}
            overall_val = max(risk_map[acwr_risk], risk_map[wellness_risk],
                              risk_map[msk_risk], risk_map[rpe_risk])
            overall_risk = ["low", "moderate", "high"][overall_val]

            # Risk adjustment from policy
            adj = policy["risk_adjustments"][overall_risk]
            max_sess = adj["max_sessions"]
            mandatory_rest = adj["mandatory_rest_days"]
            max_int = adj["max_intensity"]
            exclude_types = [x.lower() for x in adj["exclude_session_types"]]

            risk_rows.append({
                "athlete_id": aid,
                "athlete_name": aname,
                "acwr_value": acwr if acwr is not None else "N/A",
                "acwr_risk": acwr_risk,
                "wellness_composite": wellness_composite,
                "wellness_risk": wellness_risk,
                "msk_risk": msk_risk,
                "rpe_risk": rpe_risk,
                "overall_risk": overall_risk,
                "max_sessions": max_sess,
                "max_intensity": max_int,
                "mandatory_rest_days": mandatory_rest,
            })

            # --- Academic schedule via tool (all days) ---
            acad_result = self.tools["get_full_academic_schedule"](athlete_id=aid)
            timetable = acad_result["timetable"]
            blocked = {}  # day -> set of window indices
            for entry in timetable:
                if not entry["is_mandatory"]:
                    continue
                day = entry["day_of_week"]
                cs, ce = entry["start_time"], entry["end_time"]
                if day not in blocked:
                    blocked[day] = set()
                for wi, (ws, we) in enumerate(TRAINING_WINDOWS):
                    if cs < we and ce > ws:
                        blocked[day].add(wi)

            # --- Preferred windows from report ---
            pref_windows = None
            if os.path.exists(report_path):
                with open(report_path) as f:
                    report = json.load(f)
                pw = report.get("preferred_training_windows", [])
                if pw:
                    pref_indices = []
                    for p in pw:
                        ps, pe = p.split("-")
                        for wi, (ws, we) in enumerate(TRAINING_WINDOWS):
                            if ws == ps and we == pe:
                                pref_indices.append(wi)
                    if pref_indices:
                        pref_windows = pref_indices

            # --- Build schedule for this athlete ---
            # Determine available windows per day
            avail = {}
            for di, day in enumerate(ALL_DAYS):
                day_blocked = blocked.get(day, set())
                day_avail = [wi for wi in range(len(TRAINING_WINDOWS)) if wi not in day_blocked]
                # Sort by preference
                if pref_windows:
                    day_avail.sort(key=lambda wi: (0 if wi in pref_windows else 1, wi))
                avail[day] = day_avail

            # Select session types based on risk level
            int_order = ["recovery", "low", "moderate", "high", "maximal"]
            max_int_idx = int_order.index(max_int)
            eligible_templates = [
                t for t in templates
                if t["session_type"].lower() not in exclude_types
                and int_order.index(t["intensity"]) <= max_int_idx
            ]
            # Sort by priority (recovery first, then low, etc.)
            priority = {"recovery": 0, "low": 1, "moderate": 2, "high": 3, "maximal": 4}
            eligible_templates.sort(key=lambda t: priority.get(t["intensity"], 5))

            # Determine training days: up to max_sess, with mandatory_rest rest days
            max_training_days = min(max_sess, 7 - mandatory_rest)
            # Pick days with available windows, prefer days with more options
            day_scores = []
            for di, day in enumerate(ALL_DAYS):
                if avail[day]:
                    day_scores.append((day, len(avail[day]), di))
            day_scores.sort(key=lambda x: (-x[1], x[2]))
            training_days = [d[0] for d in day_scores[:max_training_days]]
            training_days.sort(key=lambda d: ALL_DAYS.index(d))

            # Enforce max_consecutive_training_days (3)
            max_consec = policy["weekly_constraints"]["max_consecutive_training_days"]
            final_days = []
            consec = 0
            for di, day in enumerate(ALL_DAYS):
                if day in training_days:
                    if consec >= max_consec:
                        continue  # skip to break consecutive streak
                    final_days.append(day)
                    consec += 1
                else:
                    consec = 0
            training_days = final_days[:max_training_days]

            # Enforce no consecutive high-intensity days
            # Assign templates to days
            max_high = policy["weekly_constraints"]["max_high_intensity_sessions"]
            high_used = 0
            prev_high = False
            for day in training_days:
                windows = avail[day]
                if not windows:
                    continue
                win_idx = windows[0]
                ws, we = TRAINING_WINDOWS[win_idx]

                # Pick template
                chosen = None
                for tmpl in eligible_templates:
                    is_high = tmpl["intensity"] in ("high", "maximal")
                    if is_high and prev_high:
                        continue  # no consecutive high days
                    if is_high and high_used >= max_high:
                        continue
                    chosen = tmpl
                    break
                if chosen is None:
                    # Fallback to first eligible
                    chosen = eligible_templates[0] if eligible_templates else {
                        "session_type": "recovery_session",
                        "default_duration": 30,
                        "intensity": "recovery",
                        "focus": "regeneration"
                    }

                is_high = chosen["intensity"] in ("high", "maximal")
                if is_high:
                    high_used += 1
                prev_high = is_high

                schedule_rows.append({
                    "athlete_id": aid,
                    "athlete_name": aname,
                    "day": day,
                    "session_start": ws,
                    "session_end": we,
                    "session_type": chosen["session_type"],
                    "intensity": chosen["intensity"],
                    "duration_min": chosen["default_duration"],
                    "focus_area": chosen["focus"],
                })

        # --- Write deliverables ---
        plan_path = os.path.join(self.workspace, "weekly_training_plan.csv")
        with open(plan_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=[
                "athlete_id", "athlete_name", "day", "session_start", "session_end",
                "session_type", "intensity", "duration_min", "focus_area"
            ])
            writer.writeheader()
            writer.writerows(schedule_rows)

        risk_path = os.path.join(self.workspace, "athlete_risk_report.csv")
        with open(risk_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=[
                "athlete_id", "athlete_name", "acwr_value", "acwr_risk",
                "wellness_composite", "wellness_risk", "msk_risk", "rpe_risk",
                "overall_risk", "max_sessions", "max_intensity", "mandatory_rest_days"
            ])
            writer.writeheader()
            writer.writerows(risk_rows)

        # --- Build action string ---
        counts = {"high": 0, "moderate": 0, "low": 0}
        high_names = []
        for rr in risk_rows:
            counts[rr["overall_risk"]] += 1
            if rr["overall_risk"] == "high":
                high_names.append(rr["athlete_name"])

        action_lines = [
            "Weekly Training Schedule Generation Complete.",
            "",
            f"Total athletes processed: {len(all_athletes)}",
            f"Risk distribution: {counts['high']} high-risk, {counts['moderate']} moderate-risk, {counts['low']} low-risk.",
            "",
        ]
        if high_names:
            action_lines.append("High-risk athletes requiring special attention: " + ", ".join(high_names) + ".")
        else:
            action_lines.append("No high-risk athletes identified. 0 high-risk athletes.")
        action_lines.extend([
            "",
            "All schedules have been saved to weekly_training_plan.csv.",
            "Risk assessments have been saved to athlete_risk_report.csv.",
        ])
        action = "\n".join(action_lines)

        return self.step(action)
