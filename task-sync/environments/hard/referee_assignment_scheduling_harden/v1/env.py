"""
Environment for weekly referee assignment roster task (hardened tool surface).

Hardened surface (M0 + M1 + M4):
  - M1: get_fixtures and get_conflicts take a single JSON-encoded string
    `filter` parameter; malformed JSON, wrong types, or unsupported keys
    produce recoverable API-style errors.
  - M4: a new create_assignment write tool records confirmed assignments
    into the roster_assignments table via a deeply nested request payload
    (parent + properties) validated layer by layer with Notion-style error
    messages. step() gains one DB-state criterion for these records.
  - Tools never raise; error responses share NO keys with success responses.
Task data, ground truth, and the original seven scoring criteria are
unchanged from the base environment.
"""

import ast
import csv
import hashlib
import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


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


def _coerce_int(value, name: str):
    """Coerce an id-like parameter to int without ever raising."""
    if isinstance(value, bool):
        return None, _error(400, "validation_error",
            f"body.{name} should be an integer, instead was {_shape(value)}.")
    if isinstance(value, int):
        return value, None
    if isinstance(value, str):
        try:
            return int(value), None
        except ValueError:
            pass
    return None, _error(400, "validation_error",
        f"body.{name} should be an integer, instead was {_shape(value)}.")


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

    # ────────────────────────── Tool methods ──────────────────────────

    @tool(
        description=(
            "Retrieve a paginated list of fixtures for the week. Returns up to "
            "page_size fixtures per page. Optional filtering is expressed as a "
            "JSON-encoded string, e.g. filter='{\"day_of_week\": \"Saturday\", "
            "\"time_slot\": \"evening\"}'. Supported filter properties: "
            "day_of_week (full day name), time_slot (morning | afternoon | "
            "evening), and match_type (string)."
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
                    "description": "Number of fixtures per page (max 10, default 5).",
                },
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"day_of_week\": \"Monday\", \"match_type\": \"cup\"}'. "
                        "Pass '{}' or omit for no filtering."
                    ),
                },
            },
            "required": ["page"],
        },
    )
    def get_fixtures(self, page: Any = None, page_size: Any = 5, filter: Any = None) -> dict:
        page, err = _coerce_int(page, "page")
        if err is not None:
            return err
        page_size, err = _coerce_int(page_size, "page_size")
        if err is not None:
            return err
        page_size = min(page_size, 10)
        if page_size < 1 or page < 1:
            return _error(400, "validation_error",
                "body.page and body.page_size should be positive integers.")

        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err
        supported = {"day_of_week", "time_slot", "match_type"}
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: day_of_week, time_slot, match_type.")
        clauses = []
        params: list = []
        if "day_of_week" in parsed:
            dow = parsed["day_of_week"]
            if not isinstance(dow, str):
                return _error(400, "validation_error",
                    f"body.filter.day_of_week should be a string, instead was {_shape(dow)}.")
            clauses.append("day_of_week = ?")
            params.append(dow)
        if "time_slot" in parsed:
            slot = parsed["time_slot"]
            if not isinstance(slot, str) or slot not in ("morning", "afternoon", "evening"):
                return _error(400, "validation_error",
                    f"body.filter.time_slot should be one of \"morning\", \"afternoon\", "
                    f"\"evening\", instead was {_shape(slot)}.")
            clauses.append("time_slot = ?")
            params.append(slot)
        if "match_type" in parsed:
            mt = parsed["match_type"]
            if not isinstance(mt, str):
                return _error(400, "validation_error",
                    f"body.filter.match_type should be a string, instead was {_shape(mt)}.")
            clauses.append("match_type = ?")
            params.append(mt)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(f"SELECT COUNT(*) FROM fixtures{where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM fixtures{where} ORDER BY fixture_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        conn.close()
        return {
            "fixtures": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total_fixtures": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get detailed information about a single referee by their ID.",
        parameters={
            "type": "object",
            "properties": {
                "referee_id": {
                    "type": "integer",
                    "description": "The referee's unique identifier.",
                },
            },
            "required": ["referee_id"],
        },
    )
    def get_referee_info(self, referee_id: Any = None) -> dict:
        referee_id, err = _coerce_int(referee_id, "referee_id")
        if err is not None:
            return err
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM referees WHERE referee_id = ?", (referee_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                f"Could not find referee with ID: {referee_id}.")
        return dict(row)

    @tool(
        description="Get all certifications held by a specific referee.",
        parameters={
            "type": "object",
            "properties": {
                "referee_id": {
                    "type": "integer",
                    "description": "The referee's unique identifier.",
                },
            },
            "required": ["referee_id"],
        },
    )
    def get_certifications(self, referee_id: Any = None) -> dict:
        referee_id, err = _coerce_int(referee_id, "referee_id")
        if err is not None:
            return err
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM certifications WHERE referee_id = ?", (referee_id,)
        ).fetchall()
        conn.close()
        return {"referee_id": referee_id, "certifications": [dict(r) for r in rows]}

    @tool(
        description=(
            "Get conflict records for a specific referee. Optional filtering is "
            "expressed as a JSON-encoded string, e.g. filter='{\"active\": true}'. "
            "Supported filter properties: active (boolean) and conflict_type "
            "(string). Without a filter, both active and inactive conflicts are "
            "returned."
        ),
        parameters={
            "type": "object",
            "properties": {
                "referee_id": {
                    "type": "integer",
                    "description": "The referee's unique identifier.",
                },
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"active\": true}'. Pass '{}' or omit for no filtering."
                    ),
                },
            },
            "required": ["referee_id"],
        },
    )
    def get_conflicts(self, referee_id: Any = None, filter: Any = None) -> dict:
        referee_id, err = _coerce_int(referee_id, "referee_id")
        if err is not None:
            return err
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err
        supported = {"active", "conflict_type"}
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: active, conflict_type.")
        clauses = ["referee_id = ?"]
        params: list = [referee_id]
        if "active" in parsed:
            active = parsed["active"]
            if not isinstance(active, bool):
                return _error(400, "validation_error",
                    f"body.filter.active should be a boolean, instead was {_shape(active)}.")
            clauses.append("active = ?")
            params.append(int(active))
        if "conflict_type" in parsed:
            ct = parsed["conflict_type"]
            if not isinstance(ct, str):
                return _error(400, "validation_error",
                    f"body.filter.conflict_type should be a string, instead was {_shape(ct)}.")
            clauses.append("conflict_type = ?")
            params.append(ct)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM conflicts WHERE " + " AND ".join(clauses), params
        ).fetchall()
        conn.close()
        return {"referee_id": referee_id, "conflicts": [dict(r) for r in rows]}

    @tool(
        description="Get information about a specific venue by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "venue_id": {
                    "type": "integer",
                    "description": "The venue's unique identifier.",
                },
            },
            "required": ["venue_id"],
        },
    )
    def get_venue_info(self, venue_id: Any = None) -> dict:
        venue_id, err = _coerce_int(venue_id, "venue_id")
        if err is not None:
            return err
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM venues WHERE venue_id = ?", (venue_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                f"Could not find venue with ID: {venue_id}.")
        return dict(row)

    @tool(
        description="Get information about a specific team by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "team_id": {
                    "type": "integer",
                    "description": "The team's unique identifier.",
                },
            },
            "required": ["team_id"],
        },
    )
    def get_team_info(self, team_id: Any = None) -> dict:
        team_id, err = _coerce_int(team_id, "team_id")
        if err is not None:
            return err
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM teams WHERE team_id = ?", (team_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                f"Could not find team with ID: {team_id}.")
        return dict(row)

    @tool(
        description="List all referee IDs registered in the system (not necessarily available this week). Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of referees per page (max 20, default 10).",
                },
            },
            "required": ["page"],
        },
    )
    def list_referees(self, page: Any = None, page_size: Any = 10) -> dict:
        page, err = _coerce_int(page, "page")
        if err is not None:
            return err
        page_size, err = _coerce_int(page_size, "page_size")
        if err is not None:
            return err
        page_size = min(page_size, 20)
        if page_size < 1 or page < 1:
            return _error(400, "validation_error",
                "body.page and body.page_size should be positive integers.")
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM referees").fetchone()[0]
        rows = conn.execute(
            "SELECT referee_id, name FROM referees ORDER BY referee_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "referees": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total_referees": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description=(
            "Records a confirmed referee assignment in the league's central "
            "assignment registry. The request body must contain a `parent` "
            "object identifying the fixture slot being staffed and a "
            "`properties` object with a `Referee` reference property. Example "
            "body: {\"parent\": {\"type\": \"fixture_slot\", \"fixture_id\": "
            "\"7\"}, \"properties\": {\"Referee\": {\"type\": \"reference\", "
            "\"reference\": {\"referee_id\": \"12\"}}}}. An optional `Note` "
            "rich_text property may be included in `properties`. Recording the "
            "same fixture again replaces its registry entry. Only fixtures that "
            "actually receive a referee should be registered."
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
                                "The fixture slot that receives the referee. "
                                "Must contain type='fixture_slot' and a "
                                "fixture_id string."
                            ),
                            "properties": {
                                "type": {"type": "string"},
                                "fixture_id": {"type": "string"},
                            },
                            "required": ["type", "fixture_id"],
                            "additionalProperties": True,
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Assignment properties. Must include a "
                                "'Referee' reference property. May include a "
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
        if parent.get("type") != "fixture_slot":
            return _error(400, "validation_error",
                f"body.parent.type should be \"fixture_slot\", instead was "
                f"{_shape(parent.get('type'))}.")
        fixture_id_raw = parent.get("fixture_id")
        if not isinstance(fixture_id_raw, str) or not fixture_id_raw:
            return _error(400, "validation_error",
                f"body.parent.fixture_id should be a non-empty string, instead was "
                f"{_shape(fixture_id_raw)}.")

        props = payload.get("properties")
        if props is None:
            return _error(400, "validation_error",
                "body.properties should be defined, instead was 'undefined'.")
        if not isinstance(props, dict):
            return _error(400, "validation_error",
                f"body.properties should be an object, instead was {_shape(props)}.")

        ref_prop = props.get("Referee")
        if ref_prop is None:
            return _error(400, "validation_error",
                "body.properties.Referee should be defined, instead was 'undefined'.")
        if not isinstance(ref_prop, dict):
            return _error(400, "validation_error",
                f"body.properties.Referee should be an object, instead was "
                f"{_shape(ref_prop)}.")
        if ref_prop.get("type") != "reference":
            return _error(400, "validation_error",
                f"body.properties.Referee.type should be \"reference\", instead was "
                f"{_shape(ref_prop.get('type'))}.")
        reference = ref_prop.get("reference")
        if not isinstance(reference, dict):
            return _error(400, "validation_error",
                f"body.properties.Referee.reference should be an object, instead was "
                f"{_shape(reference)}.")
        referee_id_raw = reference.get("referee_id")
        if not isinstance(referee_id_raw, str) or not referee_id_raw:
            return _error(400, "validation_error",
                f"body.properties.Referee.reference.referee_id should be a non-empty "
                f"string, instead was {_shape(referee_id_raw)}.")

        note_prop = props.get("Note")
        if note_prop is not None:
            if not isinstance(note_prop, dict) or note_prop.get("type") != "rich_text":
                return _error(400, "validation_error",
                    "body.properties.Note.type should be \"rich_text\".")
            rich = note_prop.get("rich_text")
            if not isinstance(rich, list):
                return _error(400, "validation_error",
                    f"body.properties.Note.rich_text should be an array, instead was "
                    f"{_shape(rich)}.")
            for i, item in enumerate(rich):
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("text"), dict)
                    or not isinstance(item["text"].get("content"), str)
                ):
                    return _error(400, "validation_error",
                        f"body.properties.Note.rich_text[{i}].text.content should be "
                        f"a string, instead was 'undefined'.")

        # --- Business validation ---
        try:
            fixture_id = int(fixture_id_raw)
        except ValueError:
            return _error(404, "object_not_found",
                f"Could not find fixture with ID: {fixture_id_raw}.")
        try:
            referee_id = int(referee_id_raw)
        except ValueError:
            return _error(404, "object_not_found",
                f"Could not find referee with ID: {referee_id_raw}.")

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        row = c.execute(
            "SELECT fixture_id FROM fixtures WHERE fixture_id = ?", (fixture_id,)
        ).fetchone()
        if row is None:
            conn.close()
            return _error(404, "object_not_found",
                f"Could not find fixture with ID: {fixture_id_raw}.")
        row = c.execute(
            "SELECT referee_id FROM referees WHERE referee_id = ?", (referee_id,)
        ).fetchone()
        if row is None:
            conn.close()
            return _error(404, "object_not_found",
                f"Could not find referee with ID: {referee_id_raw}.")

        # --- Record the assignment (upsert) ---
        c.execute(
            "CREATE TABLE IF NOT EXISTS roster_assignments ("
            "fixture_id INTEGER PRIMARY KEY, referee_id INTEGER NOT NULL)"
        )
        c.execute(
            "INSERT OR REPLACE INTO roster_assignments (fixture_id, referee_id) "
            "VALUES (?, ?)",
            (fixture_id, referee_id),
        )
        conn.commit()
        conn.close()

        # Success response: deep echo, shape entirely different from errors.
        return {
            "object": "assignment",
            "id": "asg_" + hashlib.md5(
                f"{fixture_id}:{referee_id}".encode()
            ).hexdigest()[:10],
            "parent": {"type": "fixture_slot", "fixture_id": str(fixture_id)},
            "properties": {
                "Referee": {
                    "type": "reference",
                    "reference": {"referee_id": str(referee_id)},
                },
                "Status": {"type": "select", "select": {"name": "confirmed"}},
            },
            "created": True,
        }

    # ────────────────────────── Evaluation ──────────────────────────

    def _compute_ground_truth(self) -> List[dict]:
        """Compute the correct roster assignment using the deterministic algorithm."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load all data
        fixtures = [dict(r) for r in conn.execute("SELECT * FROM fixtures").fetchall()]
        referees = {
            r["referee_id"]: dict(r)
            for r in conn.execute("SELECT * FROM referees").fetchall()
        }
        venues = {
            r["venue_id"]: dict(r)
            for r in conn.execute("SELECT * FROM venues").fetchall()
        }
        teams = {
            r["team_id"]: dict(r)
            for r in conn.execute("SELECT * FROM teams").fetchall()
        }
        certs_raw = [dict(r) for r in conn.execute("SELECT * FROM certifications").fetchall()]
        conflicts_raw = [dict(r) for r in conn.execute("SELECT * FROM conflicts").fetchall()]
        conn.close()

        # Build cert lookup: referee_id -> {match_type: cert_level_str}
        cert_map = {}
        for c in certs_raw:
            cert_map.setdefault(c["referee_id"], {})[c["match_type"]] = c["cert_level"]

        # Build active conflict lookup: referee_id -> set of team_ids
        conflict_map = {}
        for c in conflicts_raw:
            if c["active"] == 1:
                conflict_map.setdefault(c["referee_id"], set()).add(c["team_id"])

        # Load policy
        with open(os.path.join(self.workspace, "policy.yaml"), "r") as f:
            policy = yaml.safe_load(f)
        max_distance = policy["max_travel_distance_km"]

        # Load match requirements
        with open(os.path.join(self.workspace, "match_requirements.json"), "r") as f:
            match_reqs = json.load(f)

        # Load travel matrix
        import pandas as pd
        dist_df = pd.read_csv(os.path.join(self.workspace, "travel_matrix.csv"))
        dist_df = dist_df.set_index("city")
        distance_lookup = {}
        for c1 in dist_df.index:
            for c2 in dist_df.columns:
                distance_lookup[(c1, c2)] = int(dist_df.loc[c1, c2])

        # Load availability from workspace files
        avail_dir = os.path.join(self.workspace, "availability")
        availability = {}  # referee_id -> {day: [slots]}
        available_ref_ids = set()
        if os.path.isdir(avail_dir):
            for fname in os.listdir(avail_dir):
                if fname.endswith(".json"):
                    with open(os.path.join(avail_dir, fname), "r") as f:
                        data = json.load(f)
                    rid = data["referee_id"]
                    available_ref_ids.add(rid)
                    availability[rid] = data["availability"]

        cert_level_num = {"basic": 1, "advanced": 2, "elite": 3}
        slot_order = {"morning": 0, "afternoon": 1, "evening": 2}

        # Sort fixtures by: priority_level DESC, match_date ASC, time_slot ASC, fixture_id ASC
        fixtures.sort(
            key=lambda f: (-f["priority_level"], f["match_date"], slot_order.get(f["time_slot"], 0), f["fixture_id"])
        )

        # Track assignments
        ref_assignment_count = {rid: 0 for rid in available_ref_ids}
        ref_day_slot_used = {}  # (referee_id, day, slot) -> True

        roster = []
        for fix in fixtures:
            fid = fix["fixture_id"]
            match_type = fix["match_type"]
            day = fix["day_of_week"]
            slot = fix["time_slot"]
            venue = venues[fix["venue_id"]]
            venue_city = venue["city"]
            home_team_id = fix["home_team_id"]
            away_team_id = fix["away_team_id"]
            home_team_name = teams[home_team_id]["name"]
            away_team_name = teams[away_team_id]["name"]

            req_level_str = match_reqs.get(match_type, "basic")
            req_level_num = cert_level_num[req_level_str]

            # Find eligible referees
            candidates = []
            for rid in sorted(available_ref_ids):
                ref = referees[rid]
                # Check max weekly assignments
                if ref_assignment_count[rid] >= ref["max_weekly_assignments"]:
                    continue
                # Check time slot conflict
                if ref_day_slot_used.get((rid, day, slot)):
                    continue
                # Check availability
                ref_avail = availability.get(rid, {})
                if day not in ref_avail or slot not in ref_avail[day]:
                    continue
                # Check certification
                ref_certs = cert_map.get(rid, {})
                if match_type not in ref_certs:
                    continue
                ref_cert_level = cert_level_num.get(ref_certs[match_type], 0)
                if ref_cert_level < req_level_num:
                    continue
                # Check conflicts (active only)
                ref_conflicts = conflict_map.get(rid, set())
                if home_team_id in ref_conflicts or away_team_id in ref_conflicts:
                    continue
                # Check travel distance
                ref_city = ref["home_city"]
                dist = distance_lookup.get((ref_city, venue_city), distance_lookup.get((venue_city, ref_city), 9999))
                if dist > max_distance:
                    continue

                candidates.append((rid, ref_cert_level, ref["experience_years"]))

            if candidates:
                # Tiebreak: highest cert level, most experience, lowest id
                candidates.sort(key=lambda x: (-x[1], -x[2], x[0]))
                chosen_rid = candidates[0][0]
                ref_assignment_count[chosen_rid] += 1
                ref_day_slot_used[(chosen_rid, day, slot)] = True
                ref_name = referees[chosen_rid]["name"]
            else:
                chosen_rid = -1
                ref_name = "UNASSIGNED"

            roster.append({
                "fixture_id": fid,
                "match_date": fix["match_date"],
                "day_of_week": day,
                "time_slot": slot,
                "home_team": home_team_name,
                "away_team": away_team_name,
                "venue_name": venue["name"],
                "referee_id": chosen_rid,
                "referee_name": ref_name,
            })

        # Sort output by fixture_id
        roster.sort(key=lambda r: r["fixture_id"])
        return roster

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
        gt_by_id = {r["fixture_id"]: r for r in ground_truth}
        total_fixtures = len(ground_truth)

        eval_criteria = {}

        # ── Criterion 1: roster.csv exists and is readable (10 pts) ──
        roster_path = os.path.join(self.workspace, "roster.csv")
        roster_exists = os.path.isfile(roster_path)
        submitted_rows = []
        parse_error = None
        if roster_exists:
            try:
                with open(roster_path, "r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    submitted_rows = [row for row in reader]
            except Exception as e:
                parse_error = str(e)

        eval_criteria["roster_file_exists"] = {
            "passed": roster_exists and parse_error is None,
            "score": 10 if (roster_exists and parse_error is None) else 0,
            "max_score": 10,
            "reason": None if (roster_exists and parse_error is None) else (
                f"Parse error: {parse_error}" if parse_error else "roster.csv not found"
            ),
        }

        # ── Criterion 2: correct columns in correct order (10 pts) ──
        expected_cols = [
            "fixture_id", "match_date", "day_of_week", "time_slot",
            "home_team", "away_team", "venue_name", "referee_id", "referee_name",
        ]
        if submitted_rows:
            actual_cols = list(submitted_rows[0].keys())
            cols_correct = actual_cols == expected_cols
        else:
            actual_cols = []
            cols_correct = False
        eval_criteria["correct_columns"] = {
            "passed": cols_correct,
            "score": 10 if cols_correct else 0,
            "max_score": 10,
            "reason": None if cols_correct else f"Expected {expected_cols}, got {actual_cols}",
        }

        # ── Criterion 3: correct number of rows (all fixtures present) (10 pts) ──
        row_count_ok = len(submitted_rows) == total_fixtures
        eval_criteria["all_fixtures_present"] = {
            "passed": row_count_ok,
            "score": 10 if row_count_ok else 0,
            "max_score": 10,
            "reason": None if row_count_ok else f"Expected {total_fixtures} rows, got {len(submitted_rows)}",
        }

        # ── Criterion 4: fixture metadata correct (match_date, day_of_week, time_slot, teams, venue) (20 pts) ──
        metadata_correct = 0
        metadata_total = 0
        for row in submitted_rows:
            try:
                fid = int(row.get("fixture_id", -999))
            except (ValueError, TypeError):
                continue
            gt = gt_by_id.get(fid)
            if gt is None:
                continue
            metadata_total += 1
            if (
                row.get("match_date") == gt["match_date"]
                and row.get("day_of_week") == gt["day_of_week"]
                and row.get("time_slot") == gt["time_slot"]
                and row.get("home_team") == gt["home_team"]
                and row.get("away_team") == gt["away_team"]
                and row.get("venue_name") == gt["venue_name"]
            ):
                metadata_correct += 1

        if metadata_total > 0:
            meta_ratio = metadata_correct / metadata_total
        else:
            meta_ratio = 0.0
        meta_score = round(meta_ratio * 20, 2)
        eval_criteria["fixture_metadata_accuracy"] = {
            "passed": meta_ratio == 1.0,
            "score": meta_score,
            "max_score": 20,
            "reason": None if meta_ratio == 1.0 else f"{metadata_correct}/{metadata_total} fixtures have correct metadata",
        }

        # ── Criterion 5: referee assignments match ground truth (30 pts) ──
        assign_correct = 0
        assign_total = 0
        for row in submitted_rows:
            try:
                fid = int(row.get("fixture_id", -999))
                submitted_rid = int(row.get("referee_id", -999))
            except (ValueError, TypeError):
                continue
            gt = gt_by_id.get(fid)
            if gt is None:
                continue
            assign_total += 1
            if submitted_rid == gt["referee_id"]:
                assign_correct += 1

        if assign_total > 0:
            assign_ratio = assign_correct / assign_total
        else:
            assign_ratio = 0.0
        assign_score = round(assign_ratio * 30, 2)
        eval_criteria["referee_assignment_accuracy"] = {
            "passed": assign_ratio == 1.0,
            "score": assign_score,
            "max_score": 30,
            "reason": None if assign_ratio == 1.0 else f"{assign_correct}/{assign_total} correct assignments",
        }

        # ── Criterion 6: referee names match (10 pts) ──
        name_correct = 0
        name_total = 0
        for row in submitted_rows:
            try:
                fid = int(row.get("fixture_id", -999))
            except (ValueError, TypeError):
                continue
            gt = gt_by_id.get(fid)
            if gt is None:
                continue
            name_total += 1
            if row.get("referee_name", "").strip() == gt["referee_name"]:
                name_correct += 1

        if name_total > 0:
            name_ratio = name_correct / name_total
        else:
            name_ratio = 0.0
        name_score = round(name_ratio * 10, 2)
        eval_criteria["referee_name_accuracy"] = {
            "passed": name_ratio == 1.0,
            "score": name_score,
            "max_score": 10,
            "reason": None if name_ratio == 1.0 else f"{name_correct}/{name_total} correct names",
        }

        # ── Criterion 7: sort order (fixture_id ascending) (10 pts) ──
        sort_ok = False
        if submitted_rows:
            try:
                fids = [int(r["fixture_id"]) for r in submitted_rows]
                sort_ok = fids == sorted(fids)
            except (ValueError, KeyError):
                sort_ok = False
        eval_criteria["sort_order"] = {
            "passed": sort_ok,
            "score": 10 if sort_ok else 0,
            "max_score": 10,
            "reason": None if sort_ok else "Rows are not sorted by fixture_id ascending",
        }

        # ── Criterion 8 (M4): assignments recorded in the registry (10 pts) ──
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            db_assigned = dict(c.execute(
                "SELECT fixture_id, referee_id FROM roster_assignments"
            ).fetchall())
        except sqlite3.OperationalError:
            db_assigned = {}
        conn.close()

        gt_assigned = {r["fixture_id"]: r["referee_id"]
                       for r in ground_truth if r["referee_id"] != -1}
        db_ok = sum(1 for fid, rid in gt_assigned.items()
                    if db_assigned.get(fid) == rid)
        db_total = max(len(gt_assigned), 1)
        db_ratio = db_ok / db_total
        db_score = round(db_ratio * 10, 2)
        eval_criteria["db_assignments_recorded"] = {
            "passed": db_ok == len(gt_assigned),
            "score": db_score,
            "max_score": 10,
            "reason": None if db_ok == len(gt_assigned) else (
                f"{db_ok}/{len(gt_assigned)} assignments recorded in the registry"
            ),
        }

        # ── Compute totals ──
        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())
        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

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
        for get_fixtures / get_conflicts and nested request payloads for
        create_assignment.
        """
        import pandas as pd

        tool_call_count = 0

        def _call(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # ── Step 1: Load workspace config files ──
        with open(os.path.join(self.workspace, "policy.yaml"), "r") as f:
            policy = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "match_requirements.json"), "r") as f:
            match_reqs = json.load(f)

        dist_df = pd.read_csv(os.path.join(self.workspace, "travel_matrix.csv"))
        dist_df = dist_df.set_index("city")

        max_distance = policy["max_travel_distance_km"]

        # ── Step 2: Load availability files ──
        avail_dir = os.path.join(self.workspace, "availability")
        availability = {}  # referee_id -> {day: [slots]}
        available_ref_ids = set()
        for fname in sorted(os.listdir(avail_dir)):
            if fname.endswith(".json"):
                with open(os.path.join(avail_dir, fname), "r") as f:
                    data = json.load(f)
                rid = data["referee_id"]
                available_ref_ids.add(rid)
                availability[rid] = data["availability"]

        # ── Step 3: Get all fixtures via tool (paginated, empty JSON filter) ──
        all_fixtures = []
        page = 1
        while True:
            result = _call("get_fixtures", page=page, page_size=10, filter="{}")
            assert result.get("object") != "error", result
            all_fixtures.extend(result["fixtures"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ── Step 4: For each available referee, get info, certs, conflicts ──
        # Active conflicts are fetched with a JSON-encoded string filter (M1).
        ref_info = {}
        ref_certs = {}  # rid -> {match_type: cert_level_str}
        ref_conflicts = {}  # rid -> set of team_ids (active only)

        active_filter = json.dumps({"active": True})
        for rid in sorted(available_ref_ids):
            info = _call("get_referee_info", referee_id=rid)
            assert info.get("object") != "error", info
            ref_info[rid] = info

            certs_result = _call("get_certifications", referee_id=rid)
            cmap = {}
            for c in certs_result["certifications"]:
                cmap[c["match_type"]] = c["cert_level"]
            ref_certs[rid] = cmap

            conflicts_result = _call("get_conflicts", referee_id=rid, filter=active_filter)
            assert conflicts_result.get("object") != "error", conflicts_result
            ref_conflicts[rid] = {c["team_id"] for c in conflicts_result["conflicts"]}

        # ── Step 5: Get venue and team info for each fixture ──
        venue_cache = {}
        team_cache = {}

        for fix in all_fixtures:
            vid = fix["venue_id"]
            if vid not in venue_cache:
                venue_cache[vid] = _call("get_venue_info", venue_id=vid)

            for tid in [fix["home_team_id"], fix["away_team_id"]]:
                if tid not in team_cache:
                    team_cache[tid] = _call("get_team_info", team_id=tid)

        # ── Step 6: Build distance lookup from workspace file ──
        distance_lookup = {}
        for c1 in dist_df.index:
            for c2 in dist_df.columns:
                distance_lookup[(c1, c2)] = int(dist_df.loc[c1, c2])

        cert_level_num = {"basic": 1, "advanced": 2, "elite": 3}
        slot_order = {"morning": 0, "afternoon": 1, "evening": 2}

        # ── Step 7: Sort fixtures by assignment priority ──
        all_fixtures.sort(
            key=lambda f: (
                -f["priority_level"],
                f["match_date"],
                slot_order.get(f["time_slot"], 0),
                f["fixture_id"],
            )
        )

        # ── Step 8: Greedy assignment ──
        ref_assignment_count = {rid: 0 for rid in available_ref_ids}
        ref_day_slot_used = {}
        roster = []

        for fix in all_fixtures:
            fid = fix["fixture_id"]
            match_type = fix["match_type"]
            day = fix["day_of_week"]
            slot = fix["time_slot"]
            venue = venue_cache[fix["venue_id"]]
            venue_city = venue["city"]
            home_team_id = fix["home_team_id"]
            away_team_id = fix["away_team_id"]
            home_team_name = team_cache[home_team_id]["name"]
            away_team_name = team_cache[away_team_id]["name"]
            venue_name = venue["name"]

            req_level_str = match_reqs.get(match_type, "basic")
            req_level_num = cert_level_num[req_level_str]

            candidates = []
            for rid in sorted(available_ref_ids):
                ri = ref_info[rid]
                if ref_assignment_count[rid] >= ri["max_weekly_assignments"]:
                    continue
                if ref_day_slot_used.get((rid, day, slot)):
                    continue
                ref_avail = availability.get(rid, {})
                if day not in ref_avail or slot not in ref_avail[day]:
                    continue
                rc = ref_certs.get(rid, {})
                if match_type not in rc:
                    continue
                ref_cert_lv = cert_level_num.get(rc[match_type], 0)
                if ref_cert_lv < req_level_num:
                    continue
                if home_team_id in ref_conflicts.get(rid, set()) or away_team_id in ref_conflicts.get(rid, set()):
                    continue
                ref_city = ri["home_city"]
                dist = distance_lookup.get(
                    (ref_city, venue_city),
                    distance_lookup.get((venue_city, ref_city), 9999),
                )
                if dist > max_distance:
                    continue
                candidates.append((rid, ref_cert_lv, ri["experience_years"]))

            if candidates:
                candidates.sort(key=lambda x: (-x[1], -x[2], x[0]))
                chosen_rid = candidates[0][0]
                ref_assignment_count[chosen_rid] += 1
                ref_day_slot_used[(chosen_rid, day, slot)] = True
                chosen_name = ref_info[chosen_rid]["name"]

                # Record the confirmed assignment via the nested write API (M4).
                result = _call(
                    "create_assignment",
                    payload={
                        "parent": {"type": "fixture_slot", "fixture_id": str(fid)},
                        "properties": {
                            "Referee": {
                                "type": "reference",
                                "reference": {"referee_id": str(chosen_rid)},
                            },
                        },
                    },
                )
                assert result.get("object") == "assignment" and result.get("created"), result
            else:
                chosen_rid = -1
                chosen_name = "UNASSIGNED"

            roster.append({
                "fixture_id": fid,
                "match_date": fix["match_date"],
                "day_of_week": day,
                "time_slot": slot,
                "home_team": home_team_name,
                "away_team": away_team_name,
                "venue_name": venue_name,
                "referee_id": chosen_rid,
                "referee_name": chosen_name,
            })

        # Sort by fixture_id ascending
        roster.sort(key=lambda r: r["fixture_id"])

        # ── Step 9: Write roster.csv ──
        roster_path = os.path.join(self.workspace, "roster.csv")
        fieldnames = [
            "fixture_id", "match_date", "day_of_week", "time_slot",
            "home_team", "away_team", "venue_name", "referee_id", "referee_name",
        ]
        with open(roster_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(roster)

        # ── Step 10: Build action string ──
        assigned = [r for r in roster if r["referee_id"] != -1]
        unassigned = [r for r in roster if r["referee_id"] == -1]

        action = (
            f"Roster generation complete. "
            f"Total fixtures: {len(roster)}. "
            f"Assigned: {len(assigned)}. "
            f"Unassigned: {len(unassigned)}. "
            f"All confirmed assignments have been recorded in the registry "
            f"and the roster has been saved to roster.csv."
        )

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made; need >= 15"
        print(f"[verify] total tool calls: {tool_call_count}")

        return self.step(action)
