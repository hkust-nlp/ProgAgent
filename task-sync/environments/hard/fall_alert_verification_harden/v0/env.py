"""
Fall Alert Verification - Environment (hardened tool surface)

Hardened surface (M0 + M4 + M5):
  - M0: prompt.md rewritten to state goal + deliverable contract only; the
    verification rules live in workspace documents (verification_methodology.md
    plus the original configuration files).
  - M4: new write tool create_alert_resolution takes a deeply nested request
    payload (parent + properties) validated layer by layer with Notion-style
    error messages. It records each pending alert's disposition into an
    alert_resolutions table; step() gains one DB-state criterion for this
    (sanctioned M4 exception - SOURCE had no write tool).
  - M5: new parameterless bulk tool export_alert_evidence returns the complete
    joined dataset as ONE JSON string with no pagination (context-pressure
    trap; ~13k tokens at v0, >100k tokens at v3).
Task data, business logic, ground truth, and deliverables are otherwise
unchanged from the base environment. Success and error responses share no
keys, and tools never raise.
"""

import ast
import sqlite3
import os
import json
import csv
import math
import hashlib
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


# ---------------------------------------------------------------------------
# Hardened tool-surface helpers
# ---------------------------------------------------------------------------

def _request_id(message: str) -> str:
    return "req_" + hashlib.md5(message.encode("utf-8")).hexdigest()[:12]


def _error(status: int, code: str, message: str) -> dict:
    """Error responses share NO keys with success responses."""
    return {
        "status": status,
        "object": "error",
        "code": code,
        "message": message,
        "request_id": _request_id(f"{status}:{code}:{message}"),
    }


def _envelope(payload) -> dict:
    """MCP-style envelope: payload is JSON-encoded into a text content block."""
    return {
        "meta": None,
        "content": [
            {"type": "text",
             "text": json.dumps(payload, ensure_ascii=False, default=str)}
        ],
        "isError": False,
    }


def _shape(value) -> str:
    """Short rendering of a wrong-typed value for error text."""
    if value is None:
        return "'undefined'"
    r = repr(value)
    if len(r) > 60:
        r = r[:57] + "..."
    return f"'{r}'"


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
    def list_pending_alerts(self, page: Any = None, page_size: Any = None) -> dict:
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            return _error(
                400, "validation_error",
                f"body.page should be an integer >= 1, instead was {_shape(page)}.",
            )
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
            return _error(
                400, "validation_error",
                f"body.page_size should be an integer >= 1, instead was {_shape(page_size)}.",
            )
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
        return {
            "alerts": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_next": offset + page_size < total,
        }

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
    def get_alert_detail(self, alert_id: Any = None) -> dict:
        if not isinstance(alert_id, int) or isinstance(alert_id, bool):
            return _error(
                400, "validation_error",
                f"body.alert_id should be an integer, instead was {_shape(alert_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM fall_alerts WHERE alert_id = ?", (alert_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _error(
                404, "object_not_found",
                f"Could not find alert with ID: {alert_id}.",
            )
        return {"alert": dict(row)}

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
    def get_motion_readings(self, alert_id: Any = None) -> dict:
        if not isinstance(alert_id, int) or isinstance(alert_id, bool):
            return _error(
                400, "validation_error",
                f"body.alert_id should be an integer, instead was {_shape(alert_id)}.",
            )
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
        return {"alert_id": alert_id, "readings": rows}

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
    def get_resident_info(self, resident_id: Any = None) -> dict:
        if not isinstance(resident_id, int) or isinstance(resident_id, bool):
            return _error(
                400, "validation_error",
                f"body.resident_id should be an integer, instead was {_shape(resident_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM residents WHERE resident_id = ?", (resident_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _error(
                404, "object_not_found",
                f"Could not find resident with ID: {resident_id}.",
            )
        return {"resident": dict(row)}

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
    def get_caregiver_visits(self, resident_id: Any = None, date: Any = None) -> dict:
        if not isinstance(resident_id, int) or isinstance(resident_id, bool):
            return _error(
                400, "validation_error",
                f"body.resident_id should be an integer, instead was {_shape(resident_id)}.",
            )
        if not isinstance(date, str) or not date:
            return _error(
                400, "validation_error",
                f"body.date should be a YYYY-MM-DD string, instead was {_shape(date)}.",
            )
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
        return {"resident_id": resident_id, "date": date, "visits": rows}

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
        self, room_number: Any = None, start_time: Any = None, end_time: Any = None
    ) -> dict:
        if not isinstance(room_number, str) or not room_number:
            return _error(
                400, "validation_error",
                f"body.room_number should be a non-empty string, instead was "
                f"{_shape(room_number)}.",
            )
        if not isinstance(start_time, str) or not start_time:
            return _error(
                400, "validation_error",
                f"body.start_time should be a YYYY-MM-DD HH:MM:SS string, instead was "
                f"{_shape(start_time)}.",
            )
        if not isinstance(end_time, str) or not end_time:
            return _error(
                400, "validation_error",
                f"body.end_time should be a YYYY-MM-DD HH:MM:SS string, instead was "
                f"{_shape(end_time)}.",
            )
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
        return {
            "room_number": room_number,
            "start_time": start_time,
            "end_time": end_time,
            "events": rows,
        }

    # ------------------------------------------------------------------ #
    #  M5: unbounded bulk export                                          #
    # ------------------------------------------------------------------ #

    @tool(
        description=(
            "Returns the complete fall-alert evidence dataset in a single "
            "response: every alert (all statuses) joined with the resident's "
            "profile, plus every motion-sensor reading, every caregiver visit, "
            "and every audio event on record. Everything needed to review the "
            "alert queue in one call. No pagination required."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def export_alert_evidence(self) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute(
            """
            SELECT a.alert_id, a.status AS alert_status, a.timestamp AS alert_timestamp,
                   a.raw_severity_score, a.device_id AS triggering_device_id,
                   a.resident_id, r.name AS resident_name, r.age AS resident_age,
                   r.room_number AS resident_room_number,
                   r.mobility_level AS resident_mobility_level
            FROM fall_alerts a
            JOIN residents r ON r.resident_id = a.resident_id
            ORDER BY a.alert_id
            """
        )
        alerts = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT reading_id, alert_id, timestamp AS recorded_at,
                   accel_x AS acceleration_x_g, accel_y AS acceleration_y_g,
                   accel_z AS acceleration_z_g,
                   gyro_magnitude AS gyroscope_magnitude
            FROM motion_readings ORDER BY alert_id, timestamp
            """
        )
        readings = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT visit_id, resident_id, caregiver_name, visit_type,
                   scheduled_start, scheduled_end, actual_arrival, actual_departure
            FROM caregiver_visits ORDER BY visit_id
            """
        )
        visits = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT event_id, room_number, timestamp AS detected_at, event_type,
                   confidence_score, duration_ms
            FROM audio_events ORDER BY event_id
            """
        )
        audio = [dict(r) for r in cur.fetchall()]
        conn.close()

        payload = {
            "dataset": "fall_alert_evidence",
            "alert_count": len(alerts),
            "alerts": alerts,
            "motion_readings": readings,
            "caregiver_visits": visits,
            "audio_events": audio,
        }
        return json.dumps(payload, ensure_ascii=False)

    # ------------------------------------------------------------------ #
    #  M4: nested write payload with layered validation                   #
    # ------------------------------------------------------------------ #

    @tool(
        description=(
            "Records the final disposition of a pending fall alert in the "
            "facility's incident management register. The request body must "
            "contain a `parent` object identifying the alert record and a "
            "`properties` object with required `Disposition` and `Severity` "
            "select properties. Example body: "
            "{\"parent\": {\"type\": \"alert_record\", \"alert_id\": \"17\"}, "
            "\"properties\": {\"Disposition\": {\"type\": \"select\", "
            "\"select\": {\"name\": \"verified\"}}, \"Severity\": {\"type\": "
            "\"select\", \"select\": {\"name\": \"high\"}}}}. Disposition must "
            "be 'verified' or 'false_positive'; Severity must be 'critical', "
            "'high', 'medium', 'low', or 'n/a'. An optional `Note` rich_text "
            "property may be included in `properties`. Re-submitting for the "
            "same alert overwrites the previous disposition."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "The disposition request body.",
                    "properties": {
                        "parent": {
                            "type": "object",
                            "description": (
                                "The alert record being resolved. Must contain "
                                "type='alert_record' and an alert_id string."
                            ),
                            "properties": {
                                "type": {"type": "string"},
                                "alert_id": {"type": "string"},
                            },
                            "required": ["type", "alert_id"],
                            "additionalProperties": True,
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Disposition properties. Must include "
                                "'Disposition' and 'Severity' select "
                                "properties. May include a 'Note' rich_text "
                                "property."
                            ),
                            "additionalProperties": True,
                        },
                    },
                    "required": ["parent", "properties"],
                    "additionalProperties": True,
                },
            },
            "required": ["payload"],
        },
    )
    def create_alert_resolution(self, payload: Any = None) -> dict:
        # --- Layered request-body validation, one error at a time ---
        if payload is None:
            return _error(
                400, "validation_error",
                "body should be defined, instead was 'undefined'.",
            )
        if isinstance(payload, str):
            return _error(
                400, "validation_error",
                f"body should be an object, instead was {_shape(payload)}. "
                f"Pass a JSON object, not a string.",
            )
        if not isinstance(payload, dict):
            return _error(
                400, "validation_error",
                f"body should be an object, instead was {_shape(payload)}.",
            )

        parent = payload.get("parent")
        if parent is None:
            return _error(
                400, "validation_error",
                "body.parent should be defined, instead was 'undefined'.",
            )
        if not isinstance(parent, dict):
            return _error(
                400, "validation_error",
                f"body.parent should be an object, instead was {_shape(parent)}.",
            )
        if parent.get("type") != "alert_record":
            return _error(
                400, "validation_error",
                f"body.parent.type should be \"alert_record\", instead was "
                f"{_shape(parent.get('type'))}.",
            )
        alert_id_raw = parent.get("alert_id")
        if not isinstance(alert_id_raw, str) or not alert_id_raw:
            return _error(
                400, "validation_error",
                f"body.parent.alert_id should be a non-empty string, instead was "
                f"{_shape(alert_id_raw)}.",
            )

        props = payload.get("properties")
        if props is None:
            return _error(
                400, "validation_error",
                "body.properties should be defined, instead was 'undefined'.",
            )
        if not isinstance(props, dict):
            return _error(
                400, "validation_error",
                f"body.properties should be an object, instead was {_shape(props)}.",
            )

        def _validate_select(prop_name: str, allowed: List[str]):
            prop = props.get(prop_name)
            if prop is None:
                return None, _error(
                    400, "validation_error",
                    f"body.properties.{prop_name} should be defined, instead was "
                    f"'undefined'.",
                )
            if not isinstance(prop, dict):
                return None, _error(
                    400, "validation_error",
                    f"body.properties.{prop_name} should be an object, instead was "
                    f"{_shape(prop)}.",
                )
            if prop.get("type") != "select":
                return None, _error(
                    400, "validation_error",
                    f"body.properties.{prop_name}.type should be \"select\", "
                    f"instead was {_shape(prop.get('type'))}.",
                )
            select = prop.get("select")
            if not isinstance(select, dict):
                return None, _error(
                    400, "validation_error",
                    f"body.properties.{prop_name}.select should be an object, "
                    f"instead was {_shape(select)}.",
                )
            name = select.get("name")
            allowed_str = ", ".join(f'"{a}"' for a in allowed)
            if not isinstance(name, str) or name not in allowed:
                return None, _error(
                    400, "validation_error",
                    f"body.properties.{prop_name}.select.name should be one of "
                    f"{allowed_str}, instead was {_shape(name)}.",
                )
            return name, None

        disposition, err = _validate_select(
            "Disposition", ["verified", "false_positive"]
        )
        if err is not None:
            return err
        severity, err = _validate_select(
            "Severity", ["critical", "high", "medium", "low", "n/a"]
        )
        if err is not None:
            return err

        note_prop = props.get("Note")
        if note_prop is not None:
            if not isinstance(note_prop, dict) or note_prop.get("type") != "rich_text":
                return _error(
                    400, "validation_error",
                    "body.properties.Note.type should be \"rich_text\".",
                )
            rich = note_prop.get("rich_text")
            if not isinstance(rich, list):
                return _error(
                    400, "validation_error",
                    f"body.properties.Note.rich_text should be an array, instead was "
                    f"{_shape(rich)}.",
                )
            for i, item in enumerate(rich):
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("text"), dict)
                    or not isinstance(item["text"].get("content"), str)
                ):
                    return _error(
                        400, "validation_error",
                        f"body.properties.Note.rich_text[{i}].text.content should be "
                        f"a string, instead was 'undefined'.",
                    )

        # --- Business validation ---
        try:
            alert_id = int(alert_id_raw)
        except ValueError:
            return _error(
                404, "object_not_found",
                f"Could not find alert with ID: {alert_id_raw}.",
            )

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT status FROM fall_alerts WHERE alert_id = ?", (alert_id,))
        row = c.fetchone()
        if row is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find alert with ID: {alert_id_raw}.",
            )
        if row[0] != "pending":
            conn.close()
            return _error(
                400, "validation_error",
                f"Alert '{alert_id_raw}' is not pending (status='{row[0]}'). "
                f"Only pending alerts accept dispositions.",
            )

        # --- Perform write (INSERT OR REPLACE into resolutions register) ---
        c.execute(
            "CREATE TABLE IF NOT EXISTS alert_resolutions ("
            "alert_id INTEGER PRIMARY KEY, "
            "verification_status TEXT NOT NULL, "
            "severity_level TEXT NOT NULL)"
        )
        c.execute(
            "INSERT OR REPLACE INTO alert_resolutions VALUES (?, ?, ?)",
            (alert_id, disposition, severity),
        )
        conn.commit()
        conn.close()

        # Success response: deep echo, shape entirely different from errors.
        return {
            "object": "resolution",
            "id": "res_" + hashlib.md5(
                f"{alert_id}:{disposition}:{severity}".encode()
            ).hexdigest()[:10],
            "parent": {"type": "alert_record", "alert_id": alert_id_raw},
            "properties": {
                "Disposition": {"type": "select", "select": {"name": disposition}},
                "Severity": {"type": "select", "select": {"name": severity}},
            },
            "created": True,
        }

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

        # ---- C2: All pending alerts present (10 pts) ----
        agent_ids = set()
        for ar in agent_rows:
            try:
                agent_ids.add(int(ar.get("alert_id", -1)))
            except (ValueError, TypeError):
                pass
        gt_ids = set(gt_by_id.keys())
        found = len(agent_ids & gt_ids)
        c2_score = round(10 * found / max(total_pending, 1), 2)
        criteria["alerts_coverage"] = {
            "passed": found == total_pending,
            "score": c2_score,
            "max_score": 10,
            "reason": (
                ""
                if found == total_pending
                else f"Found {found}/{total_pending} pending alerts"
            ),
        }

        # ---- C3: Verification status correct (20 pts) ----
        correct_status = 0
        for ar in agent_rows:
            try:
                aid = int(ar.get("alert_id", -1))
            except (ValueError, TypeError):
                continue
            gt = gt_by_id.get(aid)
            if gt and ar.get("verification_status") == gt["verification_status"]:
                correct_status += 1
        c3_score = round(20 * correct_status / max(total_pending, 1), 2)
        criteria["verification_accuracy"] = {
            "passed": correct_status == total_pending,
            "score": c3_score,
            "max_score": 20,
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

        # ---- C8: Dispositions recorded via write API (10 pts) ----
        # (M4 DB-state criterion: SOURCE had no write tool; recording each
        # pending alert's disposition is the converted deliverable.)
        resolutions = {}
        try:
            conn = sqlite3.connect(self.db_path)
            for aid, vs, sev in conn.execute(
                "SELECT alert_id, verification_status, severity_level "
                "FROM alert_resolutions"
            ):
                resolutions[aid] = (vs, sev)
            conn.close()
        except sqlite3.OperationalError:
            pass
        res_ok = sum(
            1
            for r in ground_truth
            if resolutions.get(r["alert_id"])
            == (r["verification_status"], r["severity_level"])
        )
        c8_score = round(10 * res_ok / max(total_pending, 1), 2)
        criteria["db_dispositions_recorded"] = {
            "passed": res_ok == total_pending,
            "score": c8_score,
            "max_score": 10,
            "reason": (
                ""
                if res_ok == total_pending
                else f"{res_ok}/{total_pending} dispositions recorded correctly"
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

        Note: the hardened surface requires unwrapping {"alert": ...} /
        {"resident": ...} detail responses, consuming the M5 bulk export once
        in memory, and constructing nested M4 write payloads.
        """
        tool_calls = 0

        def _call(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

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

        # ---- M5: consume the bulk export ONCE, in memory ----
        raw_export = _call("export_alert_evidence")
        export = json.loads(raw_export)
        readings_by_alert: Dict[int, list] = {}
        for rd in export["motion_readings"]:
            readings_by_alert.setdefault(rd["alert_id"], []).append(rd)

        # ---- Collect all pending alerts via paginated tool ----
        all_alerts = []
        page = 1
        while True:
            result = _call("list_pending_alerts", page=page, page_size=10)
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

            # Get full alert detail (wrapped response)
            detail_resp = _call("get_alert_detail", alert_id=aid)
            detail = detail_resp["alert"]

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

            # Peak acceleration from the bulk export (consumed once above)
            peak_accel = 0.0
            for rd in readings_by_alert.get(aid, []):
                mag = math.sqrt(
                    rd["acceleration_x_g"] ** 2
                    + rd["acceleration_y_g"] ** 2
                    + rd["acceleration_z_g"] ** 2
                )
                peak_accel = max(peak_accel, mag)

            motion_exceeds = peak_accel > threshold

            # Resident info (wrapped response)
            res_resp = _call("get_resident_info", resident_id=rid)
            res = res_resp["resident"]

            # Caregiver visits
            alert_date = alert_dt.strftime("%Y-%m-%d")
            visits_resp = _call(
                "get_caregiver_visits", resident_id=rid, date=alert_date
            )
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
            audio_resp = _call(
                "get_audio_events",
                room_number=room_number,
                start_time=start_t,
                end_time=end_t,
            )
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

            # ---- M4: record the disposition via nested write payload ----
            resolution = _call(
                "create_alert_resolution",
                payload={
                    "parent": {"type": "alert_record", "alert_id": str(aid)},
                    "properties": {
                        "Disposition": {
                            "type": "select",
                            "select": {
                                "name": "verified" if verified else "false_positive"
                            },
                        },
                        "Severity": {
                            "type": "select",
                            "select": {"name": severity},
                        },
                    },
                },
            )
            assert resolution.get("object") == "resolution" and resolution.get(
                "created"
            ), f"create_alert_resolution failed for alert {aid}: {resolution}"

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
            f"All dispositions have been recorded in the incident register and "
            f"the incident report has been saved as incident_report.csv."
        )

        assert tool_calls >= 15, (
            f"Tool call count too low: {tool_calls}"
        )
        print(f"[verify] total tool calls: {tool_calls}, "
              f"export tokens ~{len(raw_export) // 4}")

        return self.step(action)
