import sqlite3
import os
import json
import csv
import math
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

    # ================================================================== #
    #  TOOL METHODS                                                       #
    # ================================================================== #

    @tool(
        description=(
            "Returns a paginated list of fall alerts that have status 'pending'. "
            "Each entry includes alert_id, resident_id, timestamp, and raw_severity_score. "
            "Page numbering starts at 1. Maximum page_size is 10."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of alerts per page (max 10).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_pending_alerts(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 10)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT alert_id, resident_id, timestamp, raw_severity_score "
            "FROM fall_alerts WHERE status = 'pending' "
            "ORDER BY alert_id "
            "LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        # total count
        total = cur.execute(
            "SELECT COUNT(*) FROM fall_alerts WHERE status = 'pending'"
        ).fetchone()[0]
        conn.close()
        return _envelope({
            "alerts": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_next": offset + page_size < total,
        })

    @tool(
        description=(
            "Returns full details of a single fall alert by its alert_id, "
            "including resident_id, device_id, timestamp, raw_severity_score, and status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "alert_id": {
                    "type": "integer",
                    "description": "The unique alert identifier.",
                },
            },
            "required": ["alert_id"],
        },
    )
    def get_alert_detail(self, alert_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM fall_alerts WHERE alert_id = ?", (alert_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"Alert {alert_id} not found."}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description=(
            "Returns all motion-sensor readings associated with a given alert_id. "
            "Each reading includes timestamp, accel_x, accel_y, accel_z, and gyro_magnitude."
        ),
        parameters={
            "type": "object",
            "properties": {
                "alert_id": {
                    "type": "integer",
                    "description": "The alert identifier whose readings to retrieve.",
                },
            },
            "required": ["alert_id"],
        },
    )
    def get_motion_readings(self, alert_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT reading_id, timestamp, accel_x, accel_y, accel_z, gyro_magnitude "
            "FROM motion_readings WHERE alert_id = ? ORDER BY timestamp",
            (alert_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return _envelope({"alert_id": alert_id, "readings": rows})

    @tool(
        description=(
            "Returns resident profile information for a given resident_id, "
            "including name, age, room_number, mobility_level, and admission_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "resident_id": {
                    "type": "integer",
                    "description": "The resident identifier.",
                },
            },
            "required": ["resident_id"],
        },
    )
    def get_resident_info(self, resident_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM residents WHERE resident_id = ?", (resident_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"Resident {resident_id} not found."}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description=(
            "Returns all caregiver visits for a given resident on a specific date. "
            "Each visit includes visit_type, scheduled_start/end, actual_arrival/departure."
        ),
        parameters={
            "type": "object",
            "properties": {
                "resident_id": {
                    "type": "integer",
                    "description": "The resident identifier.",
                },
                "date": {
                    "type": "string",
                    "description": "Date string in YYYY-MM-DD format.",
                },
            },
            "required": ["resident_id", "date"],
        },
    )
    def get_caregiver_visits(self, resident_id: int, date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM caregiver_visits "
            "WHERE resident_id = ? "
            "AND date(actual_arrival) <= ? "
            "AND date(actual_departure) >= ? "
            "ORDER BY actual_arrival",
            (resident_id, date, date),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return json.dumps({"resident_id": resident_id, "date": date, "visits": rows}, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Returns audio events detected in a specific room within a time window. "
            "Each event includes event_type, confidence_score, and duration_ms."
        ),
        parameters={
            "type": "object",
            "properties": {
                "room_number": {
                    "type": "string",
                    "description": "The room number string.",
                },
                "start_time": {
                    "type": "string",
                    "description": "Window start in YYYY-MM-DD HH:MM:SS format.",
                },
                "end_time": {
                    "type": "string",
                    "description": "Window end in YYYY-MM-DD HH:MM:SS format.",
                },
            },
            "required": ["room_number", "start_time", "end_time"],
        },
    )
    def get_audio_events(
        self, room_number: str, start_time: str, end_time: str
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM audio_events "
            "WHERE room_number = ? AND timestamp >= ? AND timestamp <= ? "
            "ORDER BY timestamp",
            (room_number, start_time, end_time),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return _envelope({
            "room_number": room_number,
            "start_time": start_time,
            "end_time": end_time,
            "events": rows,
        })

    # ================================================================== #
    #  GROUND-TRUTH COMPUTATION  (used by step)                           #
    # ================================================================== #

    def _compute_ground_truth(self) -> List[dict]:
        """Compute the expected report rows for all pending alerts."""
        # Read workspace config files
        with open(os.path.join(self.workspace, "validation_rules.json")) as f:
            rules = json.load(f)

        exempt_types = []
        with open(os.path.join(self.workspace, "caregiver_exemptions.txt")) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    exempt_types.append(line)

        severity_levels = []
        with open(os.path.join(self.workspace, "severity_thresholds.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                severity_levels.append(
                    {
                        "severity_level": row["severity_level"],
                        "min_acceleration": float(row["min_acceleration"]),
                        "requires_audio": row["requires_audio_confirmation"] == "yes",
                        "severity_rank": int(row["severity_rank"]),
                    }
                )
        severity_levels.sort(key=lambda x: x["severity_rank"])

        # Read all baselines
        baselines = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("baseline_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                    for room, bl in data["rooms"].items():
                        baselines[room] = bl

        # Read device registry
        device_map = {}
        with open(os.path.join(self.workspace, "device_registry.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                device_map[row["device_id"]] = row

        # Read emergency contacts
        with open(os.path.join(self.workspace, "emergency_contacts.json")) as f:
            contacts = json.load(f)

        dev_factor = rules["acceleration"]["deviation_factor"]
        min_mag = rules["acceleration"]["minimum_magnitude"]
        cg_window = rules["caregiver"]["presence_window_seconds"]
        audio_window = rules["audio"]["confirmation_window_seconds"]
        audio_min_conf = rules["audio"]["minimum_confidence"]
        audio_types = rules["audio"]["confirming_types"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # All pending alerts
        alerts = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM fall_alerts WHERE status = 'pending' ORDER BY alert_id"
            ).fetchall()
        ]

        report = []
        for alert in alerts:
            aid = alert["alert_id"]
            rid = alert["resident_id"]
            device_id = alert["device_id"]
            alert_ts = alert["timestamp"]
            alert_dt = datetime.strptime(alert_ts, "%Y-%m-%d %H:%M:%S")

            # Resident name
            res = dict(
                conn.execute(
                    "SELECT * FROM residents WHERE resident_id = ?", (rid,)
                ).fetchone()
            )

            # Room from device registry
            dev_info = device_map.get(device_id, {})
            room_number = dev_info.get("room_number", res["room_number"])

            # Baseline
            bl = baselines.get(room_number, {})
            baseline_max = bl.get("typical_accel_max", 1.0)

            # Peak acceleration
            readings = conn.execute(
                "SELECT accel_x, accel_y, accel_z FROM motion_readings WHERE alert_id = ?",
                (aid,),
            ).fetchall()
            peak_accel = 0.0
            for rd in readings:
                mag = math.sqrt(rd[0] ** 2 + rd[1] ** 2 + rd[2] ** 2)
                peak_accel = max(peak_accel, mag)

            threshold = max(baseline_max * dev_factor, min_mag)
            motion_exceeds = peak_accel > threshold

            # Caregiver check
            alert_date = alert_dt.strftime("%Y-%m-%d")
            visits = conn.execute(
                "SELECT * FROM caregiver_visits "
                "WHERE resident_id = ? AND date(actual_arrival) <= ? AND date(actual_departure) >= ?",
                (rid, alert_date, alert_date),
            ).fetchall()
            caregiver_present = False
            for v in visits:
                vtype = v[3]  # visit_type
                if vtype not in exempt_types:
                    continue
                arr = datetime.strptime(v[6], "%Y-%m-%d %H:%M:%S")  # actual_arrival
                dep = datetime.strptime(v[7], "%Y-%m-%d %H:%M:%S")  # actual_departure
                if (
                    arr <= alert_dt + timedelta(seconds=cg_window)
                    and dep >= alert_dt - timedelta(seconds=cg_window)
                ):
                    caregiver_present = True
                    break

            # Audio check
            start_t = (alert_dt - timedelta(seconds=audio_window)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            end_t = (alert_dt + timedelta(seconds=audio_window)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            audio_rows = conn.execute(
                "SELECT * FROM audio_events "
                "WHERE room_number = ? AND timestamp >= ? AND timestamp <= ?",
                (room_number, start_t, end_t),
            ).fetchall()
            audio_confirmed = False
            for ae in audio_rows:
                if ae[3] in audio_types and ae[4] >= audio_min_conf:
                    audio_confirmed = True
                    break

            # Verification
            verified = motion_exceeds and (not caregiver_present or audio_confirmed)

            # Severity
            severity = "n/a"
            sev_rank = 5
            if verified:
                for sl in severity_levels:
                    if peak_accel >= sl["min_acceleration"]:
                        if sl["requires_audio"] and not audio_confirmed:
                            continue
                        severity = sl["severity_level"]
                        sev_rank = sl["severity_rank"]
                        break

            # Contributing factors
            motion_f = "motion_exceeded" if motion_exceeds else "motion_within_baseline"
            cg_f = (
                "caregiver_exempt_present"
                if caregiver_present
                else "no_caregiver_overlap"
            )
            audio_f = "audio_confirmed" if audio_confirmed else "no_audio_confirmation"
            factors = f"{motion_f}; {cg_f}; {audio_f}"

            # Emergency contact
            ct = contacts.get(str(rid), {})

            report.append(
                {
                    "alert_id": aid,
                    "resident_name": res["name"],
                    "room_number": room_number,
                    "alert_timestamp": alert_ts,
                    "peak_acceleration": round(peak_accel, 4),
                    "baseline_max": baseline_max,
                    "severity_level": severity,
                    "verification_status": "verified" if verified else "false_positive",
                    "contributing_factors": factors,
                    "emergency_contact_name": ct.get("primary_contact_name", ""),
                    "emergency_contact_phone": ct.get("primary_contact_phone", ""),
                    "_severity_rank": sev_rank,
                }
            )

        conn.close()

        # Sort: severity_rank asc, then timestamp asc
        report.sort(key=lambda r: (r["_severity_rank"], r["alert_timestamp"]))
        return report

    # ================================================================== #
    #  STEP — evaluate agent output                                       #
    # ================================================================== #

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
        ground_truth = self._compute_ground_truth()
        gt_by_id = {r["alert_id"]: r for r in ground_truth}
        total_pending = len(ground_truth)
        gt_verified = sum(
            1 for r in ground_truth if r["verification_status"] == "verified"
        )
        gt_false_pos = total_pending - gt_verified

        criteria = {}

        # ---- C1: File exists with correct columns (10 pts) ----
        report_path = os.path.join(self.workspace, "incident_report.csv")
        expected_cols = [
            "alert_id",
            "resident_name",
            "room_number",
            "alert_timestamp",
            "peak_acceleration",
            "baseline_max",
            "severity_level",
            "verification_status",
            "contributing_factors",
            "emergency_contact_name",
            "emergency_contact_phone",
        ]
        agent_rows = []
        c1_pass = False
        if os.path.isfile(report_path):
            try:
                with open(report_path, newline="") as f:
                    reader = csv.DictReader(f)
                    actual_cols = [c.strip() for c in (reader.fieldnames or [])]
                    if actual_cols == expected_cols:
                        c1_pass = True
                    for row in reader:
                        cleaned = {k.strip(): v.strip() for k, v in row.items()}
                        agent_rows.append(cleaned)
            except Exception:
                pass
        criteria["file_format"] = {
            "passed": c1_pass,
            "score": 10 if c1_pass else 0,
            "max_score": 10,
            "reason": "" if c1_pass else "incident_report.csv missing or has wrong columns",
        }

        # ---- C2: All pending alerts present (15 pts) ----
        agent_ids = set()
        for ar in agent_rows:
            try:
                agent_ids.add(int(ar.get("alert_id", -1)))
            except (ValueError, TypeError):
                pass
        gt_ids = set(gt_by_id.keys())
        found = len(agent_ids & gt_ids)
        c2_score = round(15 * found / max(total_pending, 1), 2)
        criteria["alerts_coverage"] = {
            "passed": found == total_pending,
            "score": c2_score,
            "max_score": 15,
            "reason": (
                ""
                if found == total_pending
                else f"Found {found}/{total_pending} pending alerts"
            ),
        }

        # ---- C3: Verification status correct (25 pts) ----
        correct_status = 0
        for ar in agent_rows:
            try:
                aid = int(ar.get("alert_id", -1))
            except (ValueError, TypeError):
                continue
            gt = gt_by_id.get(aid)
            if gt and ar.get("verification_status") == gt["verification_status"]:
                correct_status += 1
        c3_score = round(25 * correct_status / max(total_pending, 1), 2)
        criteria["verification_accuracy"] = {
            "passed": correct_status == total_pending,
            "score": c3_score,
            "max_score": 25,
            "reason": (
                ""
                if correct_status == total_pending
                else f"{correct_status}/{total_pending} correct"
            ),
        }

        # ---- C4: Severity levels correct (15 pts) ----
        sev_total = 0
        sev_correct = 0
        for ar in agent_rows:
            try:
                aid = int(ar.get("alert_id", -1))
            except (ValueError, TypeError):
                continue
            gt = gt_by_id.get(aid)
            if gt is None:
                continue
            sev_total += 1
            if ar.get("severity_level") == gt["severity_level"]:
                sev_correct += 1
        c4_score = round(15 * sev_correct / max(sev_total, 1), 2)
        criteria["severity_accuracy"] = {
            "passed": sev_correct == sev_total and sev_total > 0,
            "score": c4_score,
            "max_score": 15,
            "reason": (
                ""
                if sev_correct == sev_total and sev_total > 0
                else f"{sev_correct}/{sev_total} correct"
            ),
        }

        # ---- C5: Sort order correct (10 pts) ----
        rank_map = {"critical": 1, "high": 2, "medium": 3, "low": 4, "n/a": 5}
        c5_pass = True
        if len(agent_rows) < total_pending:
            c5_pass = False
        else:
            prev_key = (0, "")
            for ar in agent_rows:
                sev = ar.get("severity_level", "n/a")
                ts = ar.get("alert_timestamp", "")
                cur_key = (rank_map.get(sev, 5), ts)
                if cur_key < prev_key:
                    c5_pass = False
                    break
                prev_key = cur_key
        criteria["sort_order"] = {
            "passed": c5_pass,
            "score": 10 if c5_pass else 0,
            "max_score": 10,
            "reason": "" if c5_pass else "Rows not sorted by severity_rank asc, then timestamp asc",
        }

        # ---- C6: Contributing factors correct (10 pts) ----
        cf_total = 0
        cf_correct = 0
        for ar in agent_rows:
            try:
                aid = int(ar.get("alert_id", -1))
            except (ValueError, TypeError):
                continue
            gt = gt_by_id.get(aid)
            if gt is None:
                continue
            cf_total += 1
            if ar.get("contributing_factors") == gt["contributing_factors"]:
                cf_correct += 1
        c6_score = round(10 * cf_correct / max(cf_total, 1), 2)
        criteria["contributing_factors"] = {
            "passed": cf_correct == cf_total and cf_total > 0,
            "score": c6_score,
            "max_score": 10,
            "reason": (
                ""
                if cf_correct == cf_total and cf_total > 0
                else f"{cf_correct}/{cf_total} correct"
            ),
        }

        # ---- C7: Response summary counts (15 pts) ----
        action_lower = action.lower()
        c7_score = 0
        found_verified = False
        found_false = False
        found_total = False
        # Look for numbers near keywords
        import re

        nums = re.findall(r"(\d+)", action)
        nums_int = [int(n) for n in nums]
        if gt_verified in nums_int:
            found_verified = True
        if gt_false_pos in nums_int:
            found_false = True
        if total_pending in nums_int:
            found_total = True
        if found_verified:
            c7_score += 5
        if found_false:
            c7_score += 5
        if found_total:
            c7_score += 5
        criteria["response_summary"] = {
            "passed": c7_score == 15,
            "score": c7_score,
            "max_score": 15,
            "reason": (
                ""
                if c7_score == 15
                else f"verified={found_verified} false_pos={found_false} total={found_total}"
            ),
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
        reward = round(total_score / max_score, 4)

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ================================================================== #
    #  VERIFY — solve using only tools + workspace files                  #
    # ================================================================== #

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
        # ---- Read workspace config ----
        with open(os.path.join(self.workspace, "validation_rules.json")) as f:
            rules = json.load(f)

        exempt_types = []
        with open(os.path.join(self.workspace, "caregiver_exemptions.txt")) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    exempt_types.append(line)

        severity_levels = []
        with open(os.path.join(self.workspace, "severity_thresholds.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                severity_levels.append(
                    {
                        "severity_level": row["severity_level"],
                        "min_acceleration": float(row["min_acceleration"]),
                        "requires_audio": row["requires_audio_confirmation"] == "yes",
                        "severity_rank": int(row["severity_rank"]),
                    }
                )
        severity_levels.sort(key=lambda x: x["severity_rank"])

        # Read device registry
        device_map = {}
        with open(os.path.join(self.workspace, "device_registry.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                device_map[row["device_id"]] = row

        # Read all baselines
        baselines = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("baseline_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                    for room, bl in data["rooms"].items():
                        baselines[room] = bl

        # Read emergency contacts
        with open(os.path.join(self.workspace, "emergency_contacts.json")) as f:
            contacts = json.load(f)

        dev_factor = rules["acceleration"]["deviation_factor"]
        min_mag = rules["acceleration"]["minimum_magnitude"]
        cg_window = rules["caregiver"]["presence_window_seconds"]
        audio_window = rules["audio"]["confirmation_window_seconds"]
        audio_min_conf = rules["audio"]["minimum_confidence"]
        audio_confirm_types = rules["audio"]["confirming_types"]

        # ---- Collect all pending alerts via paginated tool ----
        all_alerts = []
        page = 1
        tool_call_count = 0
        while True:
            result = json.loads(self.tools["list_pending_alerts"](page=page, page_size=10)["content"][0]["text"])
            tool_call_count += 1
            if not result["alerts"]:
                break
            all_alerts.extend(result["alerts"])
            if not result["has_next"]:
                break
            page += 1

        # ---- Process each alert ----
        report_rows = []
        for alert_summary in all_alerts:
            aid = alert_summary["alert_id"]

            # Get full alert detail
            detail = json.loads(self.tools["get_alert_detail"](alert_id=aid))
            tool_call_count += 1

            device_id = detail["device_id"]
            alert_ts = detail["timestamp"]
            alert_dt = datetime.strptime(alert_ts, "%Y-%m-%d %H:%M:%S")
            rid = detail["resident_id"]

            # Room from device registry
            dev_info = device_map.get(device_id, {})
            room_number = dev_info.get("room_number", "")

            # Baseline
            bl = baselines.get(room_number, {})
            baseline_max = bl.get("typical_accel_max", 1.0)
            threshold = max(baseline_max * dev_factor, min_mag)

            # Motion readings
            readings_resp = json.loads(self.tools["get_motion_readings"](alert_id=aid)["content"][0]["text"])
            tool_call_count += 1
            peak_accel = 0.0
            for rd in readings_resp["readings"]:
                mag = math.sqrt(
                    rd["accel_x"] ** 2 + rd["accel_y"] ** 2 + rd["accel_z"] ** 2
                )
                peak_accel = max(peak_accel, mag)

            motion_exceeds = peak_accel > threshold

            # Resident info
            res = json.loads(self.tools["get_resident_info"](resident_id=rid))
            tool_call_count += 1

            # Caregiver visits
            alert_date = alert_dt.strftime("%Y-%m-%d")
            visits_resp = json.loads(self.tools["get_caregiver_visits"](
                resident_id=rid, date=alert_date
            ))
            tool_call_count += 1
            caregiver_present = False
            for v in visits_resp["visits"]:
                if v["visit_type"] not in exempt_types:
                    continue
                arr = datetime.strptime(v["actual_arrival"], "%Y-%m-%d %H:%M:%S")
                dep = datetime.strptime(v["actual_departure"], "%Y-%m-%d %H:%M:%S")
                if (
                    arr <= alert_dt + timedelta(seconds=cg_window)
                    and dep >= alert_dt - timedelta(seconds=cg_window)
                ):
                    caregiver_present = True
                    break

            # Audio events
            start_t = (alert_dt - timedelta(seconds=audio_window)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            end_t = (alert_dt + timedelta(seconds=audio_window)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            audio_resp = json.loads(self.tools["get_audio_events"](
                room_number=room_number, start_time=start_t, end_time=end_t
            )["content"][0]["text"])
            tool_call_count += 1
            audio_confirmed = False
            for ae in audio_resp["events"]:
                if (
                    ae["event_type"] in audio_confirm_types
                    and ae["confidence_score"] >= audio_min_conf
                ):
                    audio_confirmed = True
                    break

            # Verification decision
            verified = motion_exceeds and (not caregiver_present or audio_confirmed)

            # Severity
            severity = "n/a"
            sev_rank = 5
            if verified:
                for sl in severity_levels:
                    if peak_accel >= sl["min_acceleration"]:
                        if sl["requires_audio"] and not audio_confirmed:
                            continue
                        severity = sl["severity_level"]
                        sev_rank = sl["severity_rank"]
                        break

            # Contributing factors
            motion_f = (
                "motion_exceeded" if motion_exceeds else "motion_within_baseline"
            )
            cg_f = (
                "caregiver_exempt_present"
                if caregiver_present
                else "no_caregiver_overlap"
            )
            audio_f = (
                "audio_confirmed" if audio_confirmed else "no_audio_confirmation"
            )
            factors = f"{motion_f}; {cg_f}; {audio_f}"

            ct = contacts.get(str(rid), {})

            report_rows.append(
                {
                    "alert_id": aid,
                    "resident_name": res["name"],
                    "room_number": room_number,
                    "alert_timestamp": alert_ts,
                    "peak_acceleration": f"{peak_accel:.4f}",
                    "baseline_max": baseline_max,
                    "severity_level": severity,
                    "verification_status": "verified" if verified else "false_positive",
                    "contributing_factors": factors,
                    "emergency_contact_name": ct.get("primary_contact_name", ""),
                    "emergency_contact_phone": ct.get("primary_contact_phone", ""),
                    "_severity_rank": sev_rank,
                }
            )

        # Sort by severity_rank asc, then alert_timestamp asc
        report_rows.sort(
            key=lambda r: (r["_severity_rank"], r["alert_timestamp"])
        )

        # Write incident_report.csv
        csv_path = os.path.join(self.workspace, "incident_report.csv")
        fieldnames = [
            "alert_id",
            "resident_name",
            "room_number",
            "alert_timestamp",
            "peak_acceleration",
            "baseline_max",
            "severity_level",
            "verification_status",
            "contributing_factors",
            "emergency_contact_name",
            "emergency_contact_phone",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in report_rows:
                out = {k: row[k] for k in fieldnames}
                writer.writerow(out)

        # Build response summary
        verified_count = sum(
            1 for r in report_rows if r["verification_status"] == "verified"
        )
        false_pos_count = len(report_rows) - verified_count
        total_count = len(report_rows)

        action = (
            f"Fall alert validation complete. "
            f"Total alerts reviewed: {total_count}. "
            f"Verified true incidents: {verified_count}. "
            f"False positives identified: {false_pos_count}. "
            f"The incident report has been saved as incident_report.csv."
        )

        assert tool_call_count >= 15, (
            f"Tool call count too low: {tool_call_count}"
        )

        return self.step(action)
