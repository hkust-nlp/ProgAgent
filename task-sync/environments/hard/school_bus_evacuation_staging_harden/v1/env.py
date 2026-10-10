"""
School Bus Evacuation Staging - Environment (hardened tool surface)

Hardened surface (M0 + M1 + M4):
  - list_buses and list_shelters take a single JSON-encoded string `filter`
    parameter; malformed JSON, wrong-typed values, or unsupported keys
    produce recoverable API-style errors.
  - The dispatch-routes deliverable is recorded through create_dispatch, a
    write tool taking a deeply nested request payload (parent + properties)
    validated layer by layer with Notion-style error messages. Success and
    error responses use completely different object shapes.
  - prompt.md is de-proceduralized (M0); the operational rules live in
    workspace/evacuation_procedures.md.
Task data, business logic, ground truth, and scoring semantics are unchanged
from the base environment (the dispatch-routes criteria now read the ledger
table instead of a CSV, with identical checks and weights).
"""
import ast
import hashlib
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
            return _error(404, "object_not_found",
                          f"Could not find school with ID: {school_id}.")
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
        description=(
            "List buses with pagination. Filtering is expressed as a JSON-encoded "
            "string, e.g. filter='{\"wheelchair_accessible\": true, \"min_capacity\": 30}'. "
            "Supported filter properties: wheelchair_accessible (boolean), "
            "depot_zone_id (integer), and min_capacity (integer, minimum seating "
            "capacity). Each result entry contains bus_id, plate_number, capacity, "
            "empty_weight_tons, depot_zone_id, and wheelchair_accessible."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"wheelchair_accessible\": true, \"depot_zone_id\": 2}'. "
                        "Pass '{}' or omit for no filtering."
                    )
                },
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
    def list_buses(self, filter: Any = None, page: int = 1,
                   page_size: int = 10) -> dict:
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"wheelchair_accessible", "depot_zone_id", "min_capacity"}
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: wheelchair_accessible, depot_zone_id, min_capacity.")

        clauses = []
        params: list = []
        if "wheelchair_accessible" in parsed:
            v = parsed["wheelchair_accessible"]
            if not isinstance(v, bool):
                return _error(400, "validation_error",
                    f"body.filter.wheelchair_accessible should be a boolean, "
                    f"instead was {_shape(v)}.")
            clauses.append("wheelchair_accessible=?")
            params.append(int(v))
        if "depot_zone_id" in parsed:
            v = parsed["depot_zone_id"]
            if not isinstance(v, int) or isinstance(v, bool):
                return _error(400, "validation_error",
                    f"body.filter.depot_zone_id should be an integer, "
                    f"instead was {_shape(v)}.")
            clauses.append("depot_zone_id=?")
            params.append(v)
        if "min_capacity" in parsed:
            v = parsed["min_capacity"]
            if not isinstance(v, int) or isinstance(v, bool):
                return _error(400, "validation_error",
                    f"body.filter.min_capacity should be an integer, "
                    f"instead was {_shape(v)}.")
            clauses.append("capacity>=?")
            params.append(v)

        page_size = min(page_size, 10)
        offset = (page - 1) * page_size
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM buses{where} ORDER BY bus_id LIMIT ? OFFSET ?",
            params + [page_size, offset]).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM buses{where}", params).fetchone()[0]
        conn.close()
        return {
            "buses": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if total else 0
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
            return _error(404, "object_not_found",
                          f"Could not find bus with ID: {bus_id}.")
        return dict(row)

    @tool(
        description=(
            "List shelters with pagination. Filtering is expressed as a JSON-encoded "
            "string, e.g. filter='{\"medical_facility\": true}'. Supported filter "
            "properties: medical_facility (boolean) and wheelchair_accessible "
            "(boolean). Each result entry contains shelter_id, name, lat, lon, "
            "base_capacity, medical_facility, wheelchair_accessible, address."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"wheelchair_accessible\": true}'. "
                        "Pass '{}' or omit for no filtering."
                    )
                },
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
    def list_shelters(self, filter: Any = None, page: int = 1,
                      page_size: int = 10) -> dict:
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"medical_facility", "wheelchair_accessible"}
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: medical_facility, wheelchair_accessible.")

        clauses = []
        params: list = []
        for key in ("medical_facility", "wheelchair_accessible"):
            if key in parsed:
                v = parsed[key]
                if not isinstance(v, bool):
                    return _error(400, "validation_error",
                        f"body.filter.{key} should be a boolean, "
                        f"instead was {_shape(v)}.")
                clauses.append(f"{key}=?")
                params.append(int(v))

        page_size = min(page_size, 10)
        offset = (page - 1) * page_size
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM shelters{where} ORDER BY shelter_id LIMIT ? OFFSET ?",
            params + [page_size, offset]).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM shelters{where}", params).fetchone()[0]
        conn.close()
        return {
            "shelters": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if total else 0
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
            return _error(404, "object_not_found",
                          f"Could not find shelter with ID: {shelter_id}.")
        return dict(row)

    @tool(
        description="Retrieve the pre-computed route from a school to a shelter. Returns route_id, segment_ids (JSON list), total_distance_km, estimated_travel_min. Not every school-shelter pair has a route.",
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
            return _error(404, "object_not_found",
                          f"Could not find route with ID: {school_id}->{shelter_id}.")
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
            return _error(404, "object_not_found",
                          f"Could not find road segment with ID: {segment_id}.")
        return dict(row)

    @tool(
        description=(
            "Records one bus dispatch in the district dispatch ledger. The request "
            "body must contain a `parent` object identifying the bus being "
            "dispatched and a `properties` object with `School` and `Shelter` "
            "reference properties, a `Segments` rich_text property carrying the "
            "semicolon-separated road-segment IDs in route order, and `Distance` "
            "and `LoadedWeight` number properties (kilometres and tonnes). "
            "Example body: {\"parent\": {\"type\": \"bus_roster\", \"bus_id\": "
            "\"12\"}, \"properties\": {\"School\": {\"type\": \"reference\", "
            "\"reference\": {\"school_id\": \"3\"}}, \"Shelter\": {\"type\": "
            "\"reference\", \"reference\": {\"shelter_id\": \"7\"}}, "
            "\"Segments\": {\"type\": \"rich_text\", \"rich_text\": [{\"type\": "
            "\"text\", \"text\": {\"content\": \"5;12;30\"}}]}, \"Distance\": "
            "{\"type\": \"number\", \"number\": 12.34}, \"LoadedWeight\": "
            "{\"type\": \"number\", \"number\": 10.05}}}. On success the dispatch "
            "is appended to the ledger."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "The dispatch request body.",
                    "properties": {
                        "parent": {
                            "type": "object",
                            "description": (
                                "The bus roster entry being dispatched. Must "
                                "contain type='bus_roster' and a bus_id string."
                            ),
                            "properties": {
                                "type": {"type": "string"},
                                "bus_id": {"type": "string"},
                            },
                            "required": ["type", "bus_id"],
                            "additionalProperties": True,
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Dispatch properties. Must include 'School' and "
                                "'Shelter' reference properties, a 'Segments' "
                                "rich_text property, and 'Distance' and "
                                "'LoadedWeight' number properties."
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
    def create_dispatch(self, payload: Any = None) -> dict:
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
        if parent.get("type") != "bus_roster":
            return _error(400, "validation_error",
                          f"body.parent.type should be \"bus_roster\", instead was "
                          f"{_shape(parent.get('type'))}.")
        bus_id_str = parent.get("bus_id")
        if not isinstance(bus_id_str, str) or not bus_id_str:
            return _error(400, "validation_error",
                          f"body.parent.bus_id should be a non-empty string, instead was "
                          f"{_shape(bus_id_str)}.")

        props = payload.get("properties")
        if props is None:
            return _error(400, "validation_error",
                          "body.properties should be defined, instead was 'undefined'.")
        if not isinstance(props, dict):
            return _error(400, "validation_error",
                          f"body.properties should be an object, instead was {_shape(props)}.")

        # --- reference properties: School, Shelter ---
        ref_ids = {}
        for prop_name, id_field in (("School", "school_id"), ("Shelter", "shelter_id")):
            prop = props.get(prop_name)
            if prop is None:
                return _error(400, "validation_error",
                              f"body.properties.{prop_name} should be defined, "
                              f"instead was 'undefined'.")
            if not isinstance(prop, dict):
                return _error(400, "validation_error",
                              f"body.properties.{prop_name} should be an object, "
                              f"instead was {_shape(prop)}.")
            if prop.get("type") != "reference":
                return _error(400, "validation_error",
                              f"body.properties.{prop_name}.type should be \"reference\", "
                              f"instead was {_shape(prop.get('type'))}.")
            reference = prop.get("reference")
            if not isinstance(reference, dict):
                return _error(400, "validation_error",
                              f"body.properties.{prop_name}.reference should be an object, "
                              f"instead was {_shape(reference)}.")
            ref_id = reference.get(id_field)
            if not isinstance(ref_id, str) or not ref_id:
                return _error(400, "validation_error",
                              f"body.properties.{prop_name}.reference.{id_field} should be "
                              f"a non-empty string, instead was {_shape(ref_id)}.")
            ref_ids[id_field] = ref_id

        # --- Segments rich_text property ---
        seg_prop = props.get("Segments")
        if seg_prop is None:
            return _error(400, "validation_error",
                          "body.properties.Segments should be defined, instead was 'undefined'.")
        if not isinstance(seg_prop, dict) or seg_prop.get("type") != "rich_text":
            return _error(400, "validation_error",
                          "body.properties.Segments.type should be \"rich_text\".")
        rich = seg_prop.get("rich_text")
        if not isinstance(rich, list) or not rich:
            return _error(400, "validation_error",
                          f"body.properties.Segments.rich_text should be a non-empty array, "
                          f"instead was {_shape(rich)}.")
        first = rich[0]
        if (not isinstance(first, dict)
                or not isinstance(first.get("text"), dict)
                or not isinstance(first["text"].get("content"), str)):
            return _error(400, "validation_error",
                          "body.properties.Segments.rich_text[0].text.content should be "
                          "a string, instead was 'undefined'.")
        seg_content = "".join(
            item["text"]["content"] for item in rich
            if isinstance(item, dict) and isinstance(item.get("text"), dict)
            and isinstance(item["text"].get("content"), str))
        try:
            seg_ids = [int(x.strip()) for x in seg_content.split(";") if x.strip()]
        except ValueError:
            return _error(400, "validation_error",
                          f"body.properties.Segments.rich_text[0].text.content should be a "
                          f"semicolon-separated list of integer segment IDs, instead was "
                          f"{_shape(seg_content)}.")
        if not seg_ids:
            return _error(400, "validation_error",
                          "body.properties.Segments.rich_text[0].text.content should contain "
                          "at least one segment ID, instead was 'undefined'.")

        # --- number properties: Distance, LoadedWeight ---
        numbers = {}
        for prop_name in ("Distance", "LoadedWeight"):
            prop = props.get(prop_name)
            if prop is None:
                return _error(400, "validation_error",
                              f"body.properties.{prop_name} should be defined, "
                              f"instead was 'undefined'.")
            if not isinstance(prop, dict) or prop.get("type") != "number":
                return _error(400, "validation_error",
                              f"body.properties.{prop_name}.type should be \"number\".")
            num = prop.get("number")
            if isinstance(num, bool) or not isinstance(num, (int, float)):
                return _error(400, "validation_error",
                              f"body.properties.{prop_name}.number should be a number, "
                              f"instead was {_shape(num)}.")
            numbers[prop_name] = float(num)

        # --- Business validation (referenced entities must exist) ---
        try:
            bus_id = int(bus_id_str)
        except ValueError:
            bus_id = None
        try:
            school_id = int(ref_ids["school_id"])
        except ValueError:
            school_id = None
        try:
            shelter_id = int(ref_ids["shelter_id"])
        except ValueError:
            shelter_id = None

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        if bus_id is None or c.execute(
                "SELECT 1 FROM buses WHERE bus_id=?", (bus_id,)).fetchone() is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find bus with ID: {bus_id_str}.")
        if school_id is None or c.execute(
                "SELECT 1 FROM schools WHERE school_id=?", (school_id,)).fetchone() is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find school with ID: {ref_ids['school_id']}.")
        if shelter_id is None or c.execute(
                "SELECT 1 FROM shelters WHERE shelter_id=?", (shelter_id,)).fetchone() is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find shelter with ID: {ref_ids['shelter_id']}.")

        # --- Perform the ledger write ---
        c.execute("""CREATE TABLE IF NOT EXISTS dispatch_records (
            record_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bus_id             INTEGER NOT NULL,
            school_id          INTEGER NOT NULL,
            shelter_id         INTEGER NOT NULL,
            segment_ids        TEXT NOT NULL,
            total_distance_km  REAL NOT NULL,
            loaded_weight_tons REAL NOT NULL
        )""")
        c.execute(
            "INSERT INTO dispatch_records "
            "(bus_id, school_id, shelter_id, segment_ids, total_distance_km, "
            "loaded_weight_tons) VALUES (?,?,?,?,?,?)",
            (bus_id, school_id, shelter_id,
             ";".join(str(x) for x in seg_ids),
             numbers["Distance"], numbers["LoadedWeight"]))
        record_id = c.lastrowid
        conn.commit()
        conn.close()

        # Success response: deep echo, shape entirely different from errors.
        return {
            "object": "dispatch",
            "id": "dsp_" + hashlib.md5(
                f"{record_id}:{bus_id}:{school_id}:{shelter_id}".encode()
            ).hexdigest()[:10],
            "parent": {"type": "bus_roster", "bus_id": str(bus_id)},
            "properties": {
                "School": {"type": "reference", "reference": {"school_id": str(school_id)}},
                "Shelter": {"type": "reference", "reference": {"shelter_id": str(shelter_id)}},
                "Segments": {"type": "rich_text", "rich_text": [
                    {"type": "text",
                     "text": {"content": ";".join(str(x) for x in seg_ids), "link": None},
                     "plain_text": ";".join(str(x) for x in seg_ids)}]},
                "Distance": {"type": "number", "number": numbers["Distance"]},
                "LoadedWeight": {"type": "number", "number": numbers["LoadedWeight"]},
            },
            "created": True,
        }

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
        # dispatch ledger records (written via the create_dispatch tool)
        try:
            dr_rows = [dict(r) for r in conn.execute(
                "SELECT * FROM dispatch_records ORDER BY record_id").fetchall()]
        except sqlite3.OperationalError:
            dr_rows = []
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
        # CRITERION 2: dispatch ledger populated via the dispatch API (10 pts)
        # (formerly dispatch_routes.csv; identical fields, recorded in DB)
        # ========================================================
        if dr_rows:
            _add("dispatch_routes_format", True, 10, 10)
        else:
            _add("dispatch_routes_format", False, 0, 10,
                 "No dispatch records found in the ledger")

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
                    loaded_w = float(row["loaded_weight_tons"])
                    seg_str = str(row.get("segment_ids", ""))
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
        # Values must match the loading_schedule counts.
        # ========================================================
        # Expected counts derived from the loading schedule
        ls_student_ids = set()
        ls_bus_ids = set()
        ls_shelter_names = set()
        for row in ls_rows:
            try:
                ids_str = str(row.get("student_ids", ""))
                for x in ids_str.split(";"):
                    x = x.strip()
                    if x:
                        ls_student_ids.add(int(x))
                bid_str = str(row.get("bus_id", "")).strip()
                if bid_str:
                    ls_bus_ids.add(int(bid_str))
                sn = str(row.get("shelter_name", "")).strip()
                if sn:
                    ls_shelter_names.add(sn)
            except Exception:
                pass
        exp_students = len(ls_student_ids)
        exp_buses = len(ls_bus_ids)
        exp_shelters = len(ls_shelter_names)

        summary_path = os.path.join(self.workspace, "evacuation_summary.txt")
        if os.path.exists(summary_path):
            try:
                import re as _re
                with open(summary_path) as f:
                    content = f.read()
                m_s = _re.search(r'TOTAL_STUDENTS_EVACUATED:\s*(\d+)', content)
                m_b = _re.search(r'TOTAL_BUSES_DISPATCHED:\s*(\d+)', content)
                m_sh = _re.search(r'SHELTERS_USED:\s*(\d+)', content)
                if m_s and m_b and m_sh:
                    got_s = int(m_s.group(1))
                    got_b = int(m_b.group(1))
                    got_sh = int(m_sh.group(1))
                    if got_s == exp_students and got_b == exp_buses and got_sh == exp_shelters:
                        _add("evacuation_summary", True, 5, 5)
                    else:
                        reasons_sum = []
                        if got_s != exp_students:
                            reasons_sum.append(
                                f"TOTAL_STUDENTS_EVACUATED is {got_s}, expected {exp_students}")
                        if got_b != exp_buses:
                            reasons_sum.append(
                                f"TOTAL_BUSES_DISPATCHED is {got_b}, expected {exp_buses}")
                        if got_sh != exp_shelters:
                            reasons_sum.append(
                                f"SHELTERS_USED is {got_sh}, expected {exp_shelters}")
                        _add("evacuation_summary", False, 0, 5,
                             "; ".join(reasons_sum))
                else:
                    _add("evacuation_summary", False, 0, 5,
                         "Missing required summary lines")
            except Exception as e:
                _add("evacuation_summary", False, 0, 5, str(e))
        else:
            _add("evacuation_summary", False, 0, 5, "File not found")

        # ========================================================
        # CRITERION 9: Final response contains correct evacuation summary (10 pts)
        # Must match "EVACUATION COMPLETE: N students evacuated on M buses to K shelters"
        # with N, M, K matching the loading schedule counts.
        # ========================================================
        import re as _re2
        m_resp = _re2.search(
            r'EVACUATION COMPLETE:\s*(\d+)\s+students\s+evacuated\s+on\s+(\d+)\s+buses\s+to\s+(\d+)\s+shelters',
            action)
        if m_resp:
            resp_n = int(m_resp.group(1))
            resp_m = int(m_resp.group(2))
            resp_k = int(m_resp.group(3))
            if resp_n == exp_students and resp_m == exp_buses and resp_k == exp_shelters:
                _add("response_summary", True, 10, 10)
            else:
                reasons_resp = []
                if resp_n != exp_students:
                    reasons_resp.append(f"N={resp_n} expected {exp_students}")
                if resp_m != exp_buses:
                    reasons_resp.append(f"M={resp_m} expected {exp_buses}")
                if resp_k != exp_shelters:
                    reasons_resp.append(f"K={resp_k} expected {exp_shelters}")
                _add("response_summary", False, 0, 10,
                     "Counts mismatch: " + "; ".join(reasons_resp))
        else:
            _add("response_summary", False, 0, 10,
                 "Response missing or malformed 'EVACUATION COMPLETE: N students evacuated "
                 "on M buses to K shelters' summary line")

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

        Note: the hardened tool surface requires JSON-encoded string filters
        for list_buses/list_shelters and nested request payloads for
        create_dispatch.
        """
        import glob as glob_mod

        tool_calls = 0

        def _call(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

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
            result = _call("list_schools", page=page, page_size=10)
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
                result = _call("get_students_by_school",
                               school_id=sid, page=page, page_size=20)
                school_students[sid].extend(result["students"])
                if page >= result["total_pages"]:
                    break
                page += 1

        # 7. Get all buses via tools, exercising the JSON-string filter:
        #    accessible fleet and non-accessible fleet fetched separately.
        all_buses = []
        for accessible in (True, False):
            filter_str = json.dumps({"wheelchair_accessible": accessible})
            page = 1
            while True:
                result = _call("list_buses", filter=filter_str,
                               page=page, page_size=10)
                all_buses.extend(result["buses"])
                if page >= result["total_pages"]:
                    break
                page += 1
        all_buses.sort(key=lambda b: b["bus_id"])

        # 8. Get all shelters via tools (empty JSON-string filter)
        all_shelters = []
        page = 1
        while True:
            result = _call("list_shelters", filter=json.dumps({}),
                           page=page, page_size=10)
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
            seg_info = _call("get_segment_info", segment_id=seg_id)
            if seg_info.get("object") == "error":
                effective_bridge_limits[seg_id] = None
                return None
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
        dispatch_count = 0

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

            routes_result = _call("list_routes_from_school", school_id=sid)
            avail_routes = routes_result["routes"]
            departure_order = 1

            for route_summary in avail_routes:
                if not remaining_studs:
                    break
                shelter_id = route_summary["shelter_id"]
                cap = remaining_cap.get(shelter_id, 0)
                if cap <= 0:
                    continue

                route_detail = _call("get_route",
                                     school_id=sid, shelter_id=shelter_id)
                if route_detail.get("object") == "error":
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
                    # Record the dispatch through the nested write API
                    dispatch_result = _call("create_dispatch", payload={
                        "parent": {"type": "bus_roster",
                                   "bus_id": str(bus["bus_id"])},
                        "properties": {
                            "School": {"type": "reference",
                                       "reference": {"school_id": str(sid)}},
                            "Shelter": {"type": "reference",
                                        "reference": {"shelter_id": str(shelter_id)}},
                            "Segments": {"type": "rich_text", "rich_text": [
                                {"type": "text",
                                 "text": {"content": ";".join(str(x) for x in seg_ids)}}]},
                            "Distance": {"type": "number",
                                         "number": round(route_detail["total_distance_km"], 2)},
                            "LoadedWeight": {"type": "number",
                                             "number": loaded_w},
                        },
                    })
                    if dispatch_result.get("object") == "dispatch" and dispatch_result.get("created"):
                        dispatch_count += 1
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

        print(f"[verify] total tool calls: {tool_calls} "
              f"(dispatch records: {dispatch_count})")
        return self.step(action)
