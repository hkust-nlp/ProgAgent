"""
Classroom Assignment Optimization - Environment (hardened tool surface)

Hardened surface (M0 + M1 + M4):
  - M1: list_classes and list_rooms each take a single JSON-encoded string
    `filter` parameter; malformed JSON or unsupported/wrongly-typed keys
    produce recoverable API-style errors.
  - M4: a new create_booking write tool records each period assignment into
    the school's room-booking database via a deeply nested request payload
    (parent + properties) validated layer by layer with Notion-style error
    messages. step() gains one DB-state criterion checking that the booking
    table mirrors the delivered schedule file.
  - M0: prompt.md rewritten to goal + deliverable contract; derivation rules
    moved into the workspace document scheduling_methodology.md (additive
    data.py change only).
Task data, business logic, the schedule deliverable, and all original
scoring criteria are unchanged from the base environment.
"""

import sqlite3
import os
import ast
import hashlib
import json
import csv
import math
import yaml
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


def _parse_json_string_param(raw, param_name: str):
    if raw is None or raw == "":
        return {}, None
    if isinstance(raw, (dict, list)):
        return None, _error(400, "invalid_request",
            f"body.{param_name} should be a JSON-encoded string, instead was an object. "
            f"Serialize it to a JSON string before passing it.")
    if not isinstance(raw, str):
        return None, _error(400, "invalid_request",
            f"body.{param_name} should be a JSON-encoded string, instead was {type(raw).__name__}.")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, _error(400, "invalid_json",
            f"Failed to parse {param_name}: {e.msg}: line {e.lineno} column {e.colno} (char {e.pos})")
    if not isinstance(value, dict):
        return None, _error(400, "invalid_request",
            f"body.{param_name} should encode a JSON object, instead was {type(value).__name__}.")
    return value, None


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
    # Booking-table helper (used by create_booking and step)
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_bookings_table(conn) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schedule_bookings ("
            "booking_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "day TEXT NOT NULL, "
            "period INTEGER NOT NULL, "
            "room_id INTEGER NOT NULL, "
            "class_id INTEGER NOT NULL)"
        )

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description=(
            "List teachers with pagination. Returns a page of teacher records "
            "including teacher_id, name, department, max_periods_per_day, and "
            "max_periods_per_week."
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
                    "description": "Number of records per page (default 10).",
                },
            },
            "required": ["page"],
        },
    )
    def list_teachers(self, page: int, page_size: int = 10) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        total = cur.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]
        offset = (page - 1) * page_size
        rows = cur.execute(
            "SELECT * FROM teachers ORDER BY teacher_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        teachers = [dict(r) for r in rows]
        return {
            "teachers": teachers,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": offset + page_size < total,
        }

    @tool(
        description=(
            "Get all subject certifications for a specific teacher. "
            "Returns a list of certification records with subject and "
            "certification_level."
        ),
        parameters={
            "type": "object",
            "properties": {
                "teacher_id": {
                    "type": "integer",
                    "description": "The teacher's ID.",
                },
            },
            "required": ["teacher_id"],
        },
    )
    def get_teacher_certifications(self, teacher_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        exists = conn.execute(
            "SELECT 1 FROM teachers WHERE teacher_id = ?", (teacher_id,)
        ).fetchone()
        if exists is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find teacher with ID: {teacher_id}.",
            )
        rows = conn.execute(
            "SELECT cert_id, subject, certification_level "
            "FROM certifications WHERE teacher_id = ? ORDER BY cert_id",
            (teacher_id,),
        ).fetchall()
        conn.close()
        return {
            "teacher_id": teacher_id,
            "certifications": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "List classes with pagination. Returns class_id, class_name, "
            "subject, grade_level, teacher_id, and num_students. Filtering is "
            "expressed as a JSON-encoded string, e.g. "
            "filter='{\"subject\": \"Mathematics\", \"grade_level\": 9}'. "
            "Supported filter properties: subject (string) and grade_level "
            "(integer)."
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
                    "description": "Number of records per page (default 10).",
                },
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"subject\": \"Chemistry\", \"grade_level\": 10}'. "
                        "Pass '{}' or omit for no filtering."
                    ),
                },
            },
            "required": ["page"],
        },
    )
    def list_classes(self, page: int, page_size: int = 10,
                     filter: Any = None) -> dict:
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"subject", "grade_level"}
        for key in parsed:
            if key not in supported:
                return _error(
                    400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: subject, grade_level.",
                )

        clauses = []
        params: list = []
        if "subject" in parsed:
            subject = parsed["subject"]
            if not isinstance(subject, str) or not subject:
                return _error(
                    400, "validation_error",
                    f"body.filter.subject should be a non-empty string, "
                    f"instead was {_shape(subject)}.",
                )
            clauses.append("subject = ?")
            params.append(subject)
        if "grade_level" in parsed:
            grade_level = parsed["grade_level"]
            if isinstance(grade_level, bool) or not isinstance(grade_level, int):
                return _error(
                    400, "validation_error",
                    f"body.filter.grade_level should be an integer, "
                    f"instead was {_shape(grade_level)}.",
                )
            clauses.append("grade_level = ?")
            params.append(grade_level)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM classes{where}", params
        ).fetchone()[0]
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT * FROM classes{where} ORDER BY class_id "
            f"LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        conn.close()
        return {
            "classes": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": offset + page_size < total,
        }

    @tool(
        description=(
            "List rooms with pagination. Returns room_id, room_name, "
            "capacity, room_type, building, and floor. Filtering is expressed "
            "as a JSON-encoded string, e.g. "
            "filter='{\"room_type\": \"classroom\", \"min_capacity\": 25}'. "
            "Supported filter properties: room_type (string) and min_capacity "
            "(integer)."
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
                    "description": "Number of records per page (default 10).",
                },
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"room_type\": \"science_lab\", \"min_capacity\": 20}'. "
                        "Pass '{}' or omit for no filtering."
                    ),
                },
            },
            "required": ["page"],
        },
    )
    def list_rooms(self, page: int, page_size: int = 10,
                   filter: Any = None) -> dict:
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"room_type", "min_capacity"}
        for key in parsed:
            if key not in supported:
                return _error(
                    400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: room_type, min_capacity.",
                )

        clauses = []
        params: list = []
        if "room_type" in parsed:
            room_type = parsed["room_type"]
            if not isinstance(room_type, str) or not room_type:
                return _error(
                    400, "validation_error",
                    f"body.filter.room_type should be a non-empty string, "
                    f"instead was {_shape(room_type)}.",
                )
            clauses.append("room_type = ?")
            params.append(room_type)
        if "min_capacity" in parsed:
            min_capacity = parsed["min_capacity"]
            if isinstance(min_capacity, bool) or not isinstance(min_capacity, int):
                return _error(
                    400, "validation_error",
                    f"body.filter.min_capacity should be an integer, "
                    f"instead was {_shape(min_capacity)}.",
                )
            clauses.append("capacity >= ?")
            params.append(min_capacity)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM rooms{where}", params
        ).fetchone()[0]
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT * FROM rooms{where} ORDER BY room_id "
            f"LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        conn.close()
        return {
            "rooms": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": offset + page_size < total,
        }

    @tool(
        description=(
            "Get detailed information for a single room by room_id. "
            "Returns room_id, room_name, capacity, room_type, building, "
            "and floor."
        ),
        parameters={
            "type": "object",
            "properties": {
                "room_id": {
                    "type": "integer",
                    "description": "The room's ID.",
                },
            },
            "required": ["room_id"],
        },
    )
    def get_room_details(self, room_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM rooms WHERE room_id = ?", (room_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return _error(
                404, "object_not_found",
                f"Could not find room with ID: {room_id}.",
            )
        return dict(row)

    @tool(
        description=(
            "Get detailed information for a single class by class_id. "
            "Returns class_id, class_name, subject, grade_level, "
            "teacher_id, and num_students."
        ),
        parameters={
            "type": "object",
            "properties": {
                "class_id": {
                    "type": "integer",
                    "description": "The class's ID.",
                },
            },
            "required": ["class_id"],
        },
    )
    def get_class_details(self, class_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM classes WHERE class_id = ?", (class_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return _error(
                404, "object_not_found",
                f"Could not find class with ID: {class_id}.",
            )
        return dict(row)

    @tool(
        description=(
            "Creates a booking: records one period assignment (a class "
            "meeting in a room at a specific day and period) into the "
            "school's room-booking database. The request body must contain a "
            "`parent` object identifying the receiving room calendar and a "
            "`properties` object with a `Class` reference property and a "
            "`Slot` timeslot property. Example body: "
            "{\"parent\": {\"type\": \"room_calendar\", \"room_id\": \"5\"}, "
            "\"properties\": {\"Class\": {\"type\": \"reference\", "
            "\"reference\": {\"class_id\": \"12\"}}, \"Slot\": {\"type\": "
            "\"timeslot\", \"timeslot\": {\"day\": \"Monday\", \"period\": "
            "3}}}}. An optional `Note` rich_text property may be included in "
            "`properties`. A room can hold at most one booking per "
            "day-and-period slot."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "The booking request body.",
                    "properties": {
                        "parent": {
                            "type": "object",
                            "description": (
                                "The room calendar that receives the booking. "
                                "Must contain type='room_calendar' and a "
                                "room_id string."
                            ),
                            "properties": {
                                "type": {"type": "string"},
                                "room_id": {"type": "string"},
                            },
                            "required": ["type", "room_id"],
                            "additionalProperties": True,
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Booking properties. Must include a 'Class' "
                                "reference property and a 'Slot' timeslot "
                                "property. May include a 'Note' rich_text "
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
    def create_booking(self, payload: Any = None) -> dict:
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
        if parent.get("type") != "room_calendar":
            return _error(
                400, "validation_error",
                f"body.parent.type should be \"room_calendar\", instead was "
                f"{_shape(parent.get('type'))}.",
            )
        room_id_raw = parent.get("room_id")
        if not isinstance(room_id_raw, str) or not room_id_raw:
            return _error(
                400, "validation_error",
                f"body.parent.room_id should be a non-empty string, instead was "
                f"{_shape(room_id_raw)}.",
            )
        if not room_id_raw.isdigit():
            return _error(
                400, "validation_error",
                f"body.parent.room_id should be a numeric string, instead was "
                f"{_shape(room_id_raw)}.",
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

        class_prop = props.get("Class")
        if class_prop is None:
            return _error(
                400, "validation_error",
                "body.properties.Class should be defined, instead was 'undefined'.",
            )
        if not isinstance(class_prop, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Class should be an object, instead was "
                f"{_shape(class_prop)}.",
            )
        if class_prop.get("type") != "reference":
            return _error(
                400, "validation_error",
                f"body.properties.Class.type should be \"reference\", instead was "
                f"{_shape(class_prop.get('type'))}.",
            )
        reference = class_prop.get("reference")
        if not isinstance(reference, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Class.reference should be an object, instead was "
                f"{_shape(reference)}.",
            )
        class_id_raw = reference.get("class_id")
        if not isinstance(class_id_raw, str) or not class_id_raw:
            return _error(
                400, "validation_error",
                f"body.properties.Class.reference.class_id should be a non-empty "
                f"string, instead was {_shape(class_id_raw)}.",
            )
        if not class_id_raw.isdigit():
            return _error(
                400, "validation_error",
                f"body.properties.Class.reference.class_id should be a numeric "
                f"string, instead was {_shape(class_id_raw)}.",
            )

        slot_prop = props.get("Slot")
        if slot_prop is None:
            return _error(
                400, "validation_error",
                "body.properties.Slot should be defined, instead was 'undefined'.",
            )
        if not isinstance(slot_prop, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Slot should be an object, instead was "
                f"{_shape(slot_prop)}.",
            )
        if slot_prop.get("type") != "timeslot":
            return _error(
                400, "validation_error",
                f"body.properties.Slot.type should be \"timeslot\", instead was "
                f"{_shape(slot_prop.get('type'))}.",
            )
        timeslot = slot_prop.get("timeslot")
        if not isinstance(timeslot, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Slot.timeslot should be an object, instead was "
                f"{_shape(timeslot)}.",
            )
        day = timeslot.get("day")
        if not isinstance(day, str) or not day:
            return _error(
                400, "validation_error",
                f"body.properties.Slot.timeslot.day should be a non-empty string, "
                f"instead was {_shape(day)}.",
            )
        period = timeslot.get("period")
        if isinstance(period, bool) or not isinstance(period, int) or period < 1:
            return _error(
                400, "validation_error",
                f"body.properties.Slot.timeslot.period should be a positive "
                f"integer, instead was {_shape(period)}.",
            )

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

        room_id = int(room_id_raw)
        class_id = int(class_id_raw)

        # --- Business validation ---
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        self._ensure_bookings_table(conn)
        if c.execute(
            "SELECT 1 FROM rooms WHERE room_id = ?", (room_id,)
        ).fetchone() is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find room calendar with ID: {room_id}.",
            )
        if c.execute(
            "SELECT 1 FROM classes WHERE class_id = ?", (class_id,)
        ).fetchone() is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find class with ID: {class_id}.",
            )
        if c.execute(
            "SELECT 1 FROM schedule_bookings "
            "WHERE day = ? AND period = ? AND room_id = ?",
            (day, period, room_id),
        ).fetchone() is not None:
            conn.close()
            return _error(
                400, "validation_error",
                f"Room {room_id} is already booked for {day} period {period}.",
            )

        # --- Perform booking ---
        c.execute(
            "INSERT INTO schedule_bookings (day, period, room_id, class_id) "
            "VALUES (?, ?, ?, ?)",
            (day, period, room_id, class_id),
        )
        conn.commit()
        conn.close()

        # Success response: deep echo, shape entirely different from errors.
        return {
            "object": "booking",
            "id": "bkg_" + hashlib.md5(
                f"{room_id}:{class_id}:{day}:{period}".encode()
            ).hexdigest()[:10],
            "parent": {"type": "room_calendar", "room_id": str(room_id)},
            "properties": {
                "Class": {"type": "reference",
                          "reference": {"class_id": str(class_id)}},
                "Slot": {"type": "timeslot",
                         "timeslot": {"day": day, "period": period}},
                "Status": {"type": "select", "select": {"name": "booked"}},
            },
            "created": True,
        }

    # ------------------------------------------------------------------
    # Helpers used by step / verify
    # ------------------------------------------------------------------

    def _load_ground_truth(self):
        """Load all reference data needed for evaluation."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        teachers = {
            r["teacher_id"]: dict(r)
            for r in conn.execute("SELECT * FROM teachers").fetchall()
        }
        classes = {
            r["class_id"]: dict(r)
            for r in conn.execute("SELECT * FROM classes").fetchall()
        }
        rooms = {
            r["room_id"]: dict(r)
            for r in conn.execute("SELECT * FROM rooms").fetchall()
        }
        certs = {}
        for r in conn.execute("SELECT * FROM certifications").fetchall():
            certs.setdefault(r["teacher_id"], []).append(r["subject"])
        conn.close()

        # Policy
        with open(os.path.join(self.workspace,
                               "scheduling_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        period_dur = policy["period_duration_minutes"]

        # Instructional minutes
        instr = {}
        with open(os.path.join(self.workspace,
                               "instructional_minutes.csv")) as f:
            for row in csv.DictReader(f):
                instr[(row["subject"], int(row["grade_level"]))] = int(
                    row["min_weekly_minutes"]
                )

        # Subject equipment requirements
        with open(os.path.join(self.workspace,
                               "subject_equipment_requirements.json")) as f:
            subj_equip = json.load(f)

        # Room equipment from YAML files
        room_equip: Dict[int, List[str]] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("room_equipment_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                for entry in data["rooms"]:
                    room_equip[entry["room_id"]] = [
                        e["name"] for e in entry["equipment"]
                    ]

        # Teacher unavailability
        teacher_unavail: Dict[int, set] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if (fname.startswith("teacher_availability_")
                    and fname.endswith(".csv")):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        tid = int(row["teacher_id"])
                        teacher_unavail.setdefault(tid, set()).add(
                            (row["day"], int(row["period"]))
                        )

        # Compute required periods per class
        class_periods = {}
        for cid, c in classes.items():
            key = (c["subject"], c["grade_level"])
            mins = instr.get(key, 135)
            class_periods[cid] = math.ceil(mins / period_dur)

        return {
            "teachers": teachers,
            "classes": classes,
            "rooms": rooms,
            "certs": certs,
            "policy": policy,
            "subj_equip": subj_equip,
            "room_equip": room_equip,
            "teacher_unavail": teacher_unavail,
            "class_periods": class_periods,
        }

    # ------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------

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
        gt = self._load_ground_truth()
        classes = gt["classes"]
        rooms = gt["rooms"]
        teachers = gt["teachers"]
        subj_equip = gt["subj_equip"]
        room_equip = gt["room_equip"]
        teacher_unavail = gt["teacher_unavail"]
        class_periods = gt["class_periods"]
        policy = gt["policy"]

        criteria: Dict[str, Dict[str, Any]] = {}

        # ------ Criterion 1: schedule file valid (10 pts) ------
        schedule_path = os.path.join(self.workspace, "weekly_schedule.csv")
        required_cols = {"day", "period", "class_id", "class_name",
                         "room_id", "room_name", "teacher_id", "teacher_name"}
        sched_rows = []
        c1_pass = True
        c1_reason = ""
        try:
            with open(schedule_path) as f:
                reader = csv.DictReader(f)
                cols = set(reader.fieldnames or [])
                if not required_cols.issubset(cols):
                    c1_pass = False
                    c1_reason = (
                        f"Missing columns: {required_cols - cols}"
                    )
                else:
                    for row in reader:
                        sched_rows.append(row)
                    if len(sched_rows) == 0:
                        c1_pass = False
                        c1_reason = "Schedule file is empty."
        except FileNotFoundError:
            c1_pass = False
            c1_reason = "weekly_schedule.csv not found."
        except Exception as e:
            c1_pass = False
            c1_reason = f"Error reading schedule: {e}"

        criteria["schedule_file_valid"] = {
            "passed": c1_pass,
            "score": 10 if c1_pass else 0,
            "max_score": 10,
        }
        if not c1_pass:
            criteria["schedule_file_valid"]["reason"] = c1_reason

        # If file invalid, remaining checks score 0
        if not c1_pass:
            for name, mx in [("schedule_sorted", 5),
                             ("all_classes_covered", 20),
                             ("no_room_conflicts", 15),
                             ("no_teacher_conflicts", 15),
                             ("capacity_respected", 15),
                             ("equipment_satisfied", 15),
                             ("specialist_rooms_respected", 10),
                             ("schedule_recorded_in_db", 10),
                             ("summary_response", 10)]:
                criteria[name] = {
                    "passed": False, "score": 0, "max_score": mx,
                    "reason": "Schedule file invalid; cannot evaluate.",
                }
            total = sum(c["score"] for c in criteria.values())
            mx_total = sum(c["max_score"] for c in criteria.values())
            return total / mx_total, {
                "eval_criteria": criteria,
                "total_score": total,
                "max_score": mx_total,
            }

        # Parse rows into typed dicts
        parsed = []
        for row in sched_rows:
            parsed.append({
                "day": row["day"].strip(),
                "period": int(row["period"]),
                "class_id": int(row["class_id"]),
                "class_name": row["class_name"].strip(),
                "room_id": int(row["room_id"]),
                "room_name": row["room_name"].strip(),
                "teacher_id": int(row["teacher_id"]),
                "teacher_name": row["teacher_name"].strip(),
            })

        # ------ Criterion 1b: schedule sorted (5 pts) ------
        # prompt.md: "Sort the rows first by day of the week in calendar order
        # starting from Monday, then by period number in ascending order, then
        # by class identifier in ascending order."
        sched_days = policy.get("days", [])
        day_index = {d: i for i, d in enumerate(sched_days)}
        sort_ok = True
        sort_reason = ""
        prev_key = None
        for r in parsed:
            cur_key = (day_index.get(r["day"], 99), r["period"], r["class_id"])
            if prev_key is not None and cur_key < prev_key:
                sort_ok = False
                sort_reason = (
                    f"Row out of order: {r['day']} period {r['period']} "
                    f"class {r['class_id']} comes after "
                    f"day_index={prev_key[0]} period {prev_key[1]} "
                    f"class {prev_key[2]}."
                )
                break
            prev_key = cur_key
        criteria["schedule_sorted"] = {
            "passed": sort_ok,
            "score": 5 if sort_ok else 0,
            "max_score": 5,
        }
        if not sort_ok:
            criteria["schedule_sorted"]["reason"] = sort_reason

        # ------ Criterion 2: all classes covered (20 pts) ------
        class_counts: Dict[int, int] = {}
        for r in parsed:
            class_counts[r["class_id"]] = class_counts.get(
                r["class_id"], 0) + 1

        c2_errors = []
        for cid, expected in class_periods.items():
            actual = class_counts.get(cid, 0)
            if actual != expected:
                cname = classes[cid]["class_name"]
                c2_errors.append(
                    f"{cname}(id={cid}): expected {expected}, got {actual}"
                )
        # Also check for unknown class ids in schedule
        for cid in class_counts:
            if cid not in classes:
                c2_errors.append(f"Unknown class_id {cid} in schedule.")

        c2_pass = len(c2_errors) == 0
        c2_score = 20 if c2_pass else max(
            0, 20 - 2 * len(c2_errors))
        criteria["all_classes_covered"] = {
            "passed": c2_pass,
            "score": c2_score,
            "max_score": 20,
        }
        if not c2_pass:
            criteria["all_classes_covered"]["reason"] = (
                f"{len(c2_errors)} mismatches: " +
                "; ".join(c2_errors[:5])
            )

        # ------ Criterion 3: no room conflicts (15 pts) ------
        room_slots: Dict[tuple, list] = {}
        for r in parsed:
            key = (r["day"], r["period"], r["room_id"])
            room_slots.setdefault(key, []).append(r["class_id"])
        conflicts_room = {k: v for k, v in room_slots.items() if len(v) > 1}
        c3_pass = len(conflicts_room) == 0
        c3_score = 15 if c3_pass else max(0, 15 - 3 * len(conflicts_room))
        criteria["no_room_conflicts"] = {
            "passed": c3_pass,
            "score": c3_score,
            "max_score": 15,
        }
        if not c3_pass:
            criteria["no_room_conflicts"]["reason"] = (
                f"{len(conflicts_room)} room-slot conflicts found."
            )

        # ------ Criterion 4: no teacher conflicts (15 pts) ------
        teacher_slots: Dict[tuple, list] = {}
        for r in parsed:
            key = (r["day"], r["period"], r["teacher_id"])
            teacher_slots.setdefault(key, []).append(r["class_id"])
        conflicts_teacher = {
            k: v for k, v in teacher_slots.items() if len(v) > 1
        }
        c4_pass = len(conflicts_teacher) == 0
        c4_score = 15 if c4_pass else max(
            0, 15 - 3 * len(conflicts_teacher))
        criteria["no_teacher_conflicts"] = {
            "passed": c4_pass,
            "score": c4_score,
            "max_score": 15,
        }
        if not c4_pass:
            criteria["no_teacher_conflicts"]["reason"] = (
                f"{len(conflicts_teacher)} teacher-slot conflicts found."
            )

        # ------ Criterion 5: capacity respected (15 pts) ------
        cap_violations = 0
        for r in parsed:
            cid = r["class_id"]
            rid = r["room_id"]
            if cid in classes and rid in rooms:
                if rooms[rid]["capacity"] < classes[cid]["num_students"]:
                    cap_violations += 1
        c5_pass = cap_violations == 0
        c5_score = 15 if c5_pass else max(0, 15 - 2 * cap_violations)
        criteria["capacity_respected"] = {
            "passed": c5_pass,
            "score": c5_score,
            "max_score": 15,
        }
        if not c5_pass:
            criteria["capacity_respected"]["reason"] = (
                f"{cap_violations} capacity violations."
            )

        # ------ Criterion 6: equipment satisfied (15 pts) ------
        equip_violations = 0
        for r in parsed:
            cid = r["class_id"]
            rid = r["room_id"]
            if cid in classes and rid in room_equip:
                subj = classes[cid]["subject"]
                required = set(subj_equip.get(subj, []))
                available = set(room_equip.get(rid, []))
                if not required.issubset(available):
                    equip_violations += 1
        c6_pass = equip_violations == 0
        c6_score = 15 if c6_pass else max(0, 15 - 2 * equip_violations)
        criteria["equipment_satisfied"] = {
            "passed": c6_pass,
            "score": c6_score,
            "max_score": 15,
        }
        if not c6_pass:
            criteria["equipment_satisfied"]["reason"] = (
                f"{equip_violations} equipment violations."
            )

        # ------ Criterion 6b: specialist rooms respected (10 pts) ------
        # room_priority_rules.txt (referenced by prompt.md): "Specialist rooms
        # must be reserved exclusively for classes whose subject requires the
        # specialist equipment. Regular-subject classes may NOT be placed in
        # specialist rooms."
        specialist_room_types = {
            "science_lab", "art_studio", "music_room",
            "gymnasium", "computer_lab",
        }
        specialist_violations = 0
        for r in parsed:
            cid = r["class_id"]
            rid = r["room_id"]
            if cid in classes and rid in rooms:
                subj = classes[cid]["subject"]
                required = set(subj_equip.get(subj, []))
                if (not required
                        and rooms[rid].get("room_type") in specialist_room_types):
                    specialist_violations += 1
        c6b_pass = specialist_violations == 0
        c6b_score = 10 if c6b_pass else max(
            0, 10 - 2 * specialist_violations)
        criteria["specialist_rooms_respected"] = {
            "passed": c6b_pass,
            "score": c6b_score,
            "max_score": 10,
        }
        if not c6b_pass:
            criteria["specialist_rooms_respected"]["reason"] = (
                f"{specialist_violations} regular classes placed in "
                f"specialist rooms."
            )

        # ------ Criterion 6c: schedule recorded in DB (10 pts) ------
        # (Added by M4 hardening: every schedule row must have been recorded
        # via the booking API; the booking table must mirror the CSV.)
        conn = sqlite3.connect(self.db_path)
        self._ensure_bookings_table(conn)
        db_rows = set(
            (r[0], r[1], r[2], r[3])
            for r in conn.execute(
                "SELECT day, period, room_id, class_id FROM schedule_bookings"
            ).fetchall()
        )
        conn.close()
        csv_rows = set(
            (r["day"], r["period"], r["room_id"], r["class_id"])
            for r in parsed
        )
        matched = len(csv_rows & db_rows)
        union = len(csv_rows | db_rows)
        cdb_pass = csv_rows == db_rows and len(csv_rows) > 0
        cdb_score = 10 if cdb_pass else max(
            0, round(10 * matched / max(union, 1)))
        criteria["schedule_recorded_in_db"] = {
            "passed": cdb_pass,
            "score": cdb_score,
            "max_score": 10,
        }
        if not cdb_pass:
            criteria["schedule_recorded_in_db"]["reason"] = (
                f"Booking records match {matched}/{union} schedule entries."
            )

        # ------ Criterion 7: summary response (10 pts) ------
        # Expect: "Scheduling Summary: X classes across Y periods using Z rooms"
        import re
        total_classes_gt = len(classes)
        total_periods_gt = sum(class_periods.values())
        # Count rooms actually needed (any room that is compatible with at
        # least one class can be used; we check the agent's self-reported
        # value against their actual schedule).
        agent_rooms_used = len(set(r["room_id"] for r in parsed))
        agent_classes = len(set(r["class_id"] for r in parsed))
        agent_periods = len(parsed)

        pattern = (
            r"Scheduling Summary:\s*(\d+)\s*classes?\s+across\s+(\d+)\s*"
            r"periods?\s+using\s+(\d+)\s*rooms?"
        )
        match = re.search(pattern, action, re.IGNORECASE)
        c7_pass = False
        c7_reason = ""
        if match:
            rep_cls = int(match.group(1))
            rep_per = int(match.group(2))
            rep_rm = int(match.group(3))
            if (rep_cls == agent_classes
                    and rep_per == agent_periods
                    and rep_rm == agent_rooms_used):
                c7_pass = True
            else:
                c7_reason = (
                    f"Reported {rep_cls}/{rep_per}/{rep_rm} but schedule "
                    f"has {agent_classes}/{agent_periods}/{agent_rooms_used}."
                )
        else:
            c7_reason = "Summary line not found in response."

        criteria["summary_response"] = {
            "passed": c7_pass,
            "score": 10 if c7_pass else 0,
            "max_score": 10,
        }
        if not c7_pass:
            criteria["summary_response"]["reason"] = c7_reason

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ------------------------------------------------------------------
    # verify
    # ------------------------------------------------------------------

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

        Note: the hardened tool surface requires JSON-encoded string filters
        for list_classes / list_rooms and nested request payloads for
        create_booking.
        """
        import math as _math

        tool_calls = 0

        def _call(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        # ---- 1. Collect all teachers via paginated tool calls ----
        all_teachers = []
        page = 1
        while True:
            result = _call("list_teachers", page=page, page_size=10)
            all_teachers.extend(result["teachers"])
            if not result["has_more"]:
                break
            page += 1

        # ---- 2. Collect certifications per teacher ----
        teacher_certs: Dict[int, List[str]] = {}
        for t in all_teachers:
            res = _call("get_teacher_certifications",
                        teacher_id=t["teacher_id"])
            teacher_certs[t["teacher_id"]] = [
                c["subject"] for c in res["certifications"]
            ]

        # ---- 3. Collect all classes (M1: JSON-encoded string filter) ----
        all_classes = []
        page = 1
        while True:
            result = _call("list_classes", page=page, page_size=10,
                           filter=json.dumps({}))
            if result.get("object") == "error":
                raise RuntimeError(result["message"])
            all_classes.extend(result["classes"])
            if not result["has_more"]:
                break
            page += 1

        # ---- 4. Collect all rooms (M1: JSON-encoded string filter) ----
        all_rooms = []
        page = 1
        while True:
            result = _call("list_rooms", page=page, page_size=10,
                           filter=json.dumps({}))
            if result.get("object") == "error":
                raise RuntimeError(result["message"])
            all_rooms.extend(result["rooms"])
            if not result["has_more"]:
                break
            page += 1

        # Exercise a real filtered M1 query as well (result subset sanity)
        filtered = _call("list_rooms", page=1, page_size=10,
                         filter=json.dumps({"room_type": "classroom",
                                            "min_capacity": 30}))
        assert filtered.get("object") != "error"

        # ---- 5. Read workspace files ----
        # 5a. Scheduling policy
        with open(os.path.join(self.workspace,
                               "scheduling_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        period_dur = policy["period_duration_minutes"]
        days = policy["days"]
        periods_per_day = policy["periods_per_day"]

        # 5b. Instructional minutes
        instr_mins: Dict[tuple, int] = {}
        with open(os.path.join(self.workspace,
                               "instructional_minutes.csv")) as f:
            for row in csv.DictReader(f):
                instr_mins[(row["subject"], int(row["grade_level"]))] = int(
                    row["min_weekly_minutes"]
                )

        # 5c. Subject equipment requirements
        with open(os.path.join(self.workspace,
                               "subject_equipment_requirements.json")) as f:
            subj_equip = json.load(f)

        # 5d. Room equipment from YAML files
        room_equip: Dict[int, List[str]] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("room_equipment_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                for entry in data["rooms"]:
                    room_equip[entry["room_id"]] = [
                        e["name"] for e in entry["equipment"]
                    ]

        # 5e. Teacher unavailability
        teacher_unavail: Dict[int, set] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if (fname.startswith("teacher_availability_")
                    and fname.endswith(".csv")):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        tid = int(row["teacher_id"])
                        teacher_unavail.setdefault(tid, set()).add(
                            (row["day"], int(row["period"]))
                        )

        # 5f. Methodology + room priority rules (applied in logic below)
        with open(os.path.join(self.workspace,
                               "scheduling_methodology.md")) as _:
            pass
        with open(os.path.join(self.workspace,
                               "room_priority_rules.txt")) as _:
            pass

        # ---- 6. Compute required periods per class ----
        class_periods: Dict[int, int] = {}
        for c in all_classes:
            key = (c["subject"], c["grade_level"])
            mins = instr_mins.get(key, 135)
            class_periods[c["class_id"]] = _math.ceil(mins / period_dur)

        # ---- 7. Determine compatible rooms per class ----
        room_map = {r["room_id"]: r for r in all_rooms}
        teacher_map = {t["teacher_id"]: t for t in all_teachers}

        # Build set of specialist room types
        specialist_room_types = {
            "computer_lab", "science_lab", "art_studio",
            "music_room", "gymnasium",
        }

        # Map subject -> required room types (subjects needing specialist
        # equipment can only go in rooms that have that equipment)
        class_compat: Dict[int, List[int]] = {}
        for c in all_classes:
            required = set(subj_equip.get(c["subject"], []))
            compat = []
            for r in all_rooms:
                avail_eq = set(room_equip.get(r["room_id"], []))
                # Equipment check
                if not required.issubset(avail_eq):
                    continue
                # Specialist-room exclusivity: regular subjects may NOT
                # use specialist rooms.
                if (not required
                        and r["room_type"] in specialist_room_types):
                    continue
                # Capacity check
                if r["capacity"] < c["num_students"]:
                    continue
                compat.append(r["room_id"])

            # Sort compatible rooms by best-fit (smallest surplus), then
            # by room_id as tie-breaker (rules 2 & 4).
            compat.sort(key=lambda rid: (
                room_map[rid]["capacity"] - c["num_students"],
                rid,
            ))
            class_compat[c["class_id"]] = compat

        # ---- 8. Greedy scheduling ----
        # Sort classes: larger enrollment first (rule 3), then fewer
        # compatible rooms first (most constrained).
        sorted_classes = sorted(
            all_classes,
            key=lambda c: (-c["num_students"],
                           len(class_compat[c["class_id"]])),
        )

        PERIODS = list(range(1, periods_per_day + 1))

        room_schedule: set = set()        # (day, period, room_id)
        teacher_schedule: set = set()     # (day, period, teacher_id)
        teacher_daily: Dict[tuple, int] = {}   # (tid, day) -> count
        teacher_weekly: Dict[int, int] = {}    # tid -> count

        schedule_rows = []

        for c in sorted_classes:
            cid = c["class_id"]
            tid = c["teacher_id"]
            needed = class_periods[cid]
            compat = class_compat[cid]
            unavail = teacher_unavail.get(tid, set())
            t_info = teacher_map[tid]
            max_daily = t_info["max_periods_per_day"]
            max_weekly = t_info["max_periods_per_week"]

            assigned = 0
            for day in days:
                if assigned >= needed:
                    break
                for period in PERIODS:
                    if assigned >= needed:
                        break
                    if (day, period) in unavail:
                        continue
                    if (day, period, tid) in teacher_schedule:
                        continue
                    dk = (tid, day)
                    if teacher_daily.get(dk, 0) >= max_daily:
                        continue
                    if teacher_weekly.get(tid, 0) >= max_weekly:
                        continue

                    for rid in compat:
                        if (day, period, rid) not in room_schedule:
                            # Assign
                            room_schedule.add((day, period, rid))
                            teacher_schedule.add((day, period, tid))
                            teacher_daily[dk] = (
                                teacher_daily.get(dk, 0) + 1
                            )
                            teacher_weekly[tid] = (
                                teacher_weekly.get(tid, 0) + 1
                            )
                            schedule_rows.append({
                                "day": day,
                                "period": period,
                                "class_id": cid,
                                "class_name": c["class_name"],
                                "room_id": rid,
                                "room_name": room_map[rid]["room_name"],
                                "teacher_id": tid,
                                "teacher_name": t_info["name"],
                            })
                            assigned += 1
                            break

        # ---- 9. Sort output ----
        day_order = {d: i for i, d in enumerate(days)}
        schedule_rows.sort(
            key=lambda r: (day_order[r["day"]], r["period"], r["class_id"])
        )

        # ---- 10. Record every assignment via the booking API (M4) ----
        for r in schedule_rows:
            result = _call(
                "create_booking",
                payload={
                    "parent": {"type": "room_calendar",
                               "room_id": str(r["room_id"])},
                    "properties": {
                        "Class": {
                            "type": "reference",
                            "reference": {"class_id": str(r["class_id"])},
                        },
                        "Slot": {
                            "type": "timeslot",
                            "timeslot": {"day": r["day"],
                                         "period": r["period"]},
                        },
                    },
                },
            )
            if not (result.get("object") == "booking"
                    and result.get("created")):
                raise RuntimeError(
                    f"Booking failed: {result.get('message', result)}"
                )

        # ---- 11. Write weekly_schedule.csv ----
        out_path = os.path.join(self.workspace, "weekly_schedule.csv")
        fieldnames = [
            "day", "period", "class_id", "class_name",
            "room_id", "room_name", "teacher_id", "teacher_name",
        ]
        with open(out_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(schedule_rows)

        # ---- 12. Build action string ----
        total_classes = len(set(r["class_id"] for r in schedule_rows))
        total_periods = len(schedule_rows)
        rooms_used = len(set(r["room_id"] for r in schedule_rows))

        action = (
            f"Scheduling Summary: {total_classes} classes across "
            f"{total_periods} periods using {rooms_used} rooms"
        )

        print(f"[verify] total tool calls: {tool_calls}")
        return self.step(action)
