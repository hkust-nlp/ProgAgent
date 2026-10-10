#!/usr/bin/env python3
"""Environment for volunteer shift scheduling task (hardened tool surface).

Hardened surface (M1 + M4):
  - list_volunteers and list_shifts each take a single JSON-encoded string
    `filter` parameter; malformed JSON, objects passed where strings are
    required, and unsupported/wrongly-typed filter keys produce recoverable
    API-style errors.
  - create_assignment records a primary assignment into the scheduling
    database via a deeply nested request payload (parent + properties)
    validated layer by layer with Notion-style error messages. Success and
    error responses share no keys.
Task semantics, data generation, prompt deliverables, and the original
scoring criteria are unchanged from the base environment (step() gains one
DB-state criterion for the recorded assignments, per the M4 conversion rule).
"""

import ast
import csv
import hashlib
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


# ── Hardened tool-surface helpers ──────────────────────────────────────────

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


_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday",
              "Friday", "Saturday", "Sunday")


def _check_page(page, page_size):
    """Validate pagination inputs; returns an error dict or None."""
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        return _error(400, "validation_error",
                      f"body.page should be a positive integer, instead was {_shape(page)}.")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
        return _error(400, "validation_error",
                      f"body.page_size should be a positive integer, instead was {_shape(page_size)}.")
    return None


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
        description=(
            "List volunteers with pagination. Filtering is expressed as a "
            "JSON-encoded string, e.g. filter='{\"certification\": \"first_aid\", "
            "\"min_experience_years\": 2}'. Supported filter properties: "
            "certification (string; only volunteers holding that certification) "
            "and min_experience_years (integer; only volunteers with at least "
            "that many years of experience). Returns 'volunteers' (records with "
            "id, name, certifications, max_shifts_per_week, experience_years) "
            "and 'has_more' (whether more pages exist)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"certification\": \"food_safety\"}'. "
                        "Pass '{}' or omit for no filtering."
                    ),
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
            "required": ["page"],
        },
    )
    def list_volunteers(self, page: int = 1, page_size: int = 20,
                        filter: Any = None) -> str:
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return json.dumps(err)
        supported = ("certification", "min_experience_years")
        for key in parsed:
            if key not in supported:
                return json.dumps(_error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: certification, min_experience_years."))
        certification = parsed.get("certification")
        if "certification" in parsed and (
                not isinstance(certification, str) or not certification):
            return json.dumps(_error(400, "validation_error",
                f"body.filter.certification should be a non-empty string, "
                f"instead was {_shape(certification)}."))
        min_exp = parsed.get("min_experience_years")
        if "min_experience_years" in parsed and (
                not isinstance(min_exp, int) or isinstance(min_exp, bool)):
            return json.dumps(_error(400, "validation_error",
                f"body.filter.min_experience_years should be an integer, "
                f"instead was {_shape(min_exp)}."))

        perr = _check_page(page, page_size)
        if perr is not None:
            return json.dumps(perr)
        page_size = min(page_size, 20)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, certifications, max_shifts_per_week, experience_years "
            "FROM volunteers ORDER BY id",
        ).fetchall()
        conn.close()

        records = [dict(r) for r in rows]
        if certification is not None:
            records = [r for r in records
                       if certification in r["certifications"].split(",")]
        if min_exp is not None:
            records = [r for r in records if r["experience_years"] >= min_exp]

        offset = (page - 1) * page_size
        window = records[offset:offset + page_size + 1]
        has_more = len(window) > page_size
        volunteers = window[:page_size]
        return json.dumps({"volunteers": volunteers, "has_more": has_more})

    @tool(
        description=(
            "List shifts with pagination. Filtering is expressed as a "
            "JSON-encoded string, e.g. filter='{\"day_of_week\": \"Monday\", "
            "\"is_outdoor\": true}'. Supported filter properties: day_of_week "
            "(day name, e.g. 'Monday'), is_outdoor (boolean), and role "
            "(string). Returns 'shifts' (records with shift_id, event_id, "
            "event_name, day_of_week, start_time, end_time, role, location, "
            "is_outdoor) and 'has_more' (whether more pages exist)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"day_of_week\": \"Friday\"}'. "
                        "Pass '{}' or omit for no filtering."
                    ),
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
            "required": ["page"],
        },
    )
    def list_shifts(self, page: int = 1, page_size: int = 20,
                    filter: Any = None) -> str:
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return json.dumps(err)
        supported = ("day_of_week", "is_outdoor", "role")
        for key in parsed:
            if key not in supported:
                return json.dumps(_error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: day_of_week, is_outdoor, role."))

        clauses = []
        params: list = []
        if "day_of_week" in parsed:
            day = parsed["day_of_week"]
            if not isinstance(day, str) or day not in _DAY_NAMES:
                return json.dumps(_error(400, "validation_error",
                    f"body.filter.day_of_week should be one of \"Monday\" ... "
                    f"\"Sunday\", instead was {_shape(day)}."))
            clauses.append("day_of_week = ?")
            params.append(day)
        if "is_outdoor" in parsed:
            is_outdoor = parsed["is_outdoor"]
            if not isinstance(is_outdoor, bool):
                return json.dumps(_error(400, "validation_error",
                    f"body.filter.is_outdoor should be a boolean, instead was "
                    f"{_shape(is_outdoor)}."))
            clauses.append("is_outdoor = ?")
            params.append(int(is_outdoor))
        if "role" in parsed:
            role = parsed["role"]
            if not isinstance(role, str) or not role:
                return json.dumps(_error(400, "validation_error",
                    f"body.filter.role should be a non-empty string, instead was "
                    f"{_shape(role)}."))
            clauses.append("role = ?")
            params.append(role)

        perr = _check_page(page, page_size)
        if perr is not None:
            return json.dumps(perr)
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id AS shift_id, event_id, event_name, day_of_week, "
            "start_time, end_time, role, location, is_outdoor "
            f"FROM shifts{where} ORDER BY id LIMIT ? OFFSET ?",
            params + [page_size + 1, offset],
        ).fetchall()
        conn.close()

        has_more = len(rows) > page_size
        shifts = [dict(r) for r in rows[:page_size]]
        for s in shifts:
            s["is_outdoor"] = bool(s["is_outdoor"])
        return json.dumps({"shifts": shifts, "has_more": has_more})

    @tool(
        description="Get a volunteer's availability windows for the entire week. Returns 'volunteer_id' and 'windows' (list of {day_of_week, available_from, available_until}).",
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
    def get_volunteer_availability(self, volunteer_id: Any = None) -> str:
        if not isinstance(volunteer_id, int) or isinstance(volunteer_id, bool):
            return json.dumps(_error(400, "validation_error",
                f"body.volunteer_id should be an integer, instead was "
                f"{_shape(volunteer_id)}."))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        exists = conn.execute(
            "SELECT 1 FROM volunteers WHERE id = ?", (volunteer_id,)
        ).fetchone()
        if exists is None:
            conn.close()
            return json.dumps(_error(404, "object_not_found",
                f"Could not find volunteer with ID: {volunteer_id}."))
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
        description="Get attendance summary for a single volunteer. Returns 'volunteer_id', 'total_records', 'attended', 'no_shows', and 'no_show_rate' (float, 0.0-1.0).",
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
    def get_attendance_summary(self, volunteer_id: Any = None) -> str:
        if not isinstance(volunteer_id, int) or isinstance(volunteer_id, bool):
            return json.dumps(_error(400, "validation_error",
                f"body.volunteer_id should be an integer, instead was "
                f"{_shape(volunteer_id)}."))
        conn = sqlite3.connect(self.db_path)
        exists = conn.execute(
            "SELECT 1 FROM volunteers WHERE id = ?", (volunteer_id,)
        ).fetchone()
        if exists is None:
            conn.close()
            return json.dumps(_error(404, "object_not_found",
                f"Could not find volunteer with ID: {volunteer_id}."))
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

    @tool(
        description=(
            "Records a primary assignment: places a volunteer onto a shift's "
            "roster in the scheduling system. The request body must contain a "
            "`parent` object identifying the receiving shift roster and a "
            "`properties` object with a `Volunteer` reference property. "
            "Example body: {\"parent\": {\"type\": \"shift_roster\", "
            "\"shift_id\": 12}, \"properties\": {\"Volunteer\": {\"type\": "
            "\"reference\", \"reference\": {\"volunteer_id\": 7}}}}. An "
            "optional `Note` rich_text property may be included in "
            "`properties`. Recording an assignment for a shift that already "
            "has one replaces the previous assignment."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "The assignment request body.",
                    "properties": {
                        "parent": {
                            "type": "object",
                            "description": (
                                "The shift roster that receives the volunteer. "
                                "Must contain type='shift_roster' and an "
                                "integer shift_id."
                            ),
                            "properties": {
                                "type": {"type": "string"},
                                "shift_id": {"type": "integer"},
                            },
                            "required": ["type", "shift_id"],
                            "additionalProperties": True,
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Assignment properties. Must include a "
                                "'Volunteer' reference property. May include a "
                                "'Note' rich_text property."
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
    def create_assignment(self, payload: Any = None) -> dict:
        # --- Layered request-body validation, one error at a time ---
        if payload is None:
            return _error(400, "validation_error",
                          "body should be defined, instead was 'undefined'.")
        if isinstance(payload, str):
            return _error(400, "validation_error",
                          f"body should be an object, instead was {_shape(payload)}. "
                          f"Pass a JSON object, not a string.")
        if not isinstance(payload, dict):
            return _error(400, "validation_error",
                          f"body should be an object, instead was {_shape(payload)}.")

        parent = payload.get("parent")
        if parent is None:
            return _error(400, "validation_error",
                          "body.parent should be defined, instead was 'undefined'.")
        if not isinstance(parent, dict):
            return _error(400, "validation_error",
                          f"body.parent should be an object, instead was {_shape(parent)}.")
        if parent.get("type") != "shift_roster":
            return _error(400, "validation_error",
                          f"body.parent.type should be \"shift_roster\", instead was "
                          f"{_shape(parent.get('type'))}.")
        shift_id = parent.get("shift_id")
        if not isinstance(shift_id, int) or isinstance(shift_id, bool):
            return _error(400, "validation_error",
                          f"body.parent.shift_id should be an integer, instead was "
                          f"{_shape(shift_id)}.")

        props = payload.get("properties")
        if props is None:
            return _error(400, "validation_error",
                          "body.properties should be defined, instead was 'undefined'.")
        if not isinstance(props, dict):
            return _error(400, "validation_error",
                          f"body.properties should be an object, instead was {_shape(props)}.")

        vol_prop = props.get("Volunteer")
        if vol_prop is None:
            return _error(400, "validation_error",
                          "body.properties.Volunteer should be defined, instead was 'undefined'.")
        if not isinstance(vol_prop, dict):
            return _error(400, "validation_error",
                          f"body.properties.Volunteer should be an object, instead was "
                          f"{_shape(vol_prop)}.")
        if vol_prop.get("type") != "reference":
            return _error(400, "validation_error",
                          f"body.properties.Volunteer.type should be \"reference\", "
                          f"instead was {_shape(vol_prop.get('type'))}.")
        reference = vol_prop.get("reference")
        if not isinstance(reference, dict):
            return _error(400, "validation_error",
                          f"body.properties.Volunteer.reference should be an object, "
                          f"instead was {_shape(reference)}.")
        volunteer_id = reference.get("volunteer_id")
        if not isinstance(volunteer_id, int) or isinstance(volunteer_id, bool):
            return _error(400, "validation_error",
                          f"body.properties.Volunteer.reference.volunteer_id should be "
                          f"an integer, instead was {_shape(volunteer_id)}.")

        note_prop = props.get("Note")
        if note_prop is not None:
            if not isinstance(note_prop, dict) or note_prop.get("type") != "rich_text":
                return _error(400, "validation_error",
                              "body.properties.Note.type should be \"rich_text\".")
            rich = note_prop.get("rich_text")
            if not isinstance(rich, list):
                return _error(400, "validation_error",
                              f"body.properties.Note.rich_text should be an array, "
                              f"instead was {_shape(rich)}.")
            for i, item in enumerate(rich):
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("text"), dict)
                    or not isinstance(item["text"].get("content"), str)
                ):
                    return _error(400, "validation_error",
                                  f"body.properties.Note.rich_text[{i}].text.content "
                                  f"should be a string, instead was 'undefined'.")

        # --- Business validation ---
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        if c.execute("SELECT 1 FROM shifts WHERE id = ?", (shift_id,)).fetchone() is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find shift with ID: {shift_id}.")
        if c.execute("SELECT 1 FROM volunteers WHERE id = ?", (volunteer_id,)).fetchone() is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find volunteer with ID: {volunteer_id}.")

        # --- Perform the write ---
        c.execute(
            "CREATE TABLE IF NOT EXISTS shift_assignments ("
            "shift_id INTEGER PRIMARY KEY, volunteer_id INTEGER NOT NULL)"
        )
        c.execute(
            "INSERT OR REPLACE INTO shift_assignments (shift_id, volunteer_id) "
            "VALUES (?, ?)",
            (shift_id, volunteer_id),
        )
        conn.commit()
        conn.close()

        # Success response: deep echo, shape entirely different from errors.
        return {
            "object": "assignment",
            "id": "asg_" + hashlib.md5(f"{shift_id}:{volunteer_id}".encode()).hexdigest()[:10],
            "parent": {"type": "shift_roster", "shift_id": shift_id},
            "properties": {
                "Volunteer": {"type": "reference",
                              "reference": {"volunteer_id": volunteer_id}},
                "Status": {"type": "select", "select": {"name": "assigned"}},
            },
            "created": True,
        }

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
        has_assignments_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='shift_assignments'"
        ).fetchone() is not None
        db_assignments = {}
        if has_assignments_table:
            db_assignments = {
                r["shift_id"]: r["volunteer_id"]
                for r in conn.execute("SELECT shift_id, volunteer_id FROM shift_assignments").fetchall()
            }
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
                    # Check reliability_score format: prompt requires exactly 2 decimal places
                    bad_format = []
                    for br in backup_rows:
                        rel_str = br.get("reliability_score", "")
                        parts = rel_str.split(".")
                        if not (len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 2):
                            bad_format.append(rel_str)
                    if bad_format:
                        c8_reason = (
                            f"reliability_score must be formatted to exactly two decimal places; "
                            f"found malformatted values: {bad_format[:5]}"
                        )
                    else:
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

        # ── Criterion 10: Assignments recorded in the scheduling system (10 pts) ──
        # (M4 DB-state criterion: every scheduled shift must have a matching
        # record created via the assignment API.)
        rec_ok = 0
        for sid, row in schedule_by_shift.items():
            if sid not in shifts:
                continue
            try:
                vid = int(row["assigned_volunteer_id"])
            except (ValueError, KeyError):
                continue
            if db_assignments.get(sid) == vid:
                rec_ok += 1
        c10_score = round(10 * rec_ok / total_shifts) if total_shifts > 0 else 0
        c10_pass = rec_ok == total_shifts and total_shifts > 0
        criteria["assignments_recorded"] = {
            "passed": c10_pass, "score": c10_score, "max_score": 10,
            "reason": "" if c10_pass else f"{rec_ok}/{total_shifts} shifts recorded in the scheduling system",
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

        Note: the hardened tool surface requires JSON-encoded string filters
        for list_volunteers/list_shifts and nested request payloads for
        create_assignment.
        """
        tool_calls = 0

        def _call(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

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

        # Read rule documents (for completeness, rules are encoded in logic below)
        with open(os.path.join(self.workspace, "backup_priority_rules.md")) as f:
            _ = f.read()
        with open(os.path.join(self.workspace, "primary_assignment_rules.md")) as f:
            _ = f.read()

        no_show_threshold = policy["no_show_threshold"]
        rain_threshold = policy["rain_threshold"]
        normal_backup_count = policy["normal_backup_count"]
        outdoor_rain_backup_count = policy["outdoor_rain_backup_count"]

        # ── 2. Get all volunteers via tool (paginated, empty JSON-string filter) ──
        all_volunteers = []
        page = 1
        while True:
            result = json.loads(_call("list_volunteers", filter="{}", page=page, page_size=20))
            assert result.get("object") != "error", result
            all_volunteers.extend(result["volunteers"])
            if not result["has_more"]:
                break
            page += 1

        # ── 3. Get all shifts by day via tool (JSON-string day filter) ──
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        all_shifts = []
        for day in days:
            page = 1
            filter_str = json.dumps({"day_of_week": day})
            while True:
                result = json.loads(_call("list_shifts", filter=filter_str, page=page, page_size=20))
                assert result.get("object") != "error", result
                all_shifts.extend(result["shifts"])
                if not result["has_more"]:
                    break
                page += 1

        # ── 4. Get attendance summaries and availability for all volunteers ──
        attendance = {}
        vol_availability = {}
        for v in all_volunteers:
            att = json.loads(_call("get_attendance_summary", volunteer_id=v["id"]))
            assert att.get("object") != "error", att
            attendance[v["id"]] = att

            avail = json.loads(_call("get_volunteer_availability", volunteer_id=v["id"]))
            assert avail.get("object") != "error", avail
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

                # Record the assignment via the nested write API
                result = _call(
                    "create_assignment",
                    payload={
                        "parent": {"type": "shift_roster", "shift_id": sid},
                        "properties": {
                            "Volunteer": {
                                "type": "reference",
                                "reference": {"volunteer_id": primary["id"]},
                            },
                        },
                    },
                )
                assert result.get("object") == "assignment" and result.get("created"), result

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
            f"All primary assignments have been recorded in the scheduling system, and "
            f"the weekly_schedule.csv and backup_assignments.csv have been saved."
        )

        print(f"[verify] total tool calls: {tool_calls}")
        return self.step(action)
