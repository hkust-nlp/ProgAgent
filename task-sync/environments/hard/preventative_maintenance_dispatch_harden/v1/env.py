"""
Fleet Preventative Maintenance Task - Environment (hardened tool surface)

Hardened surface (M0 + M1 + M4):
  - M1: list_vehicles and list_technicians take a single JSON-encoded string
    `filter` parameter; malformed JSON, objects-instead-of-strings,
    unsupported keys, or wrongly-typed values produce recoverable
    API-style errors.
  - M4: a new create_dispatch write tool records work orders through a
    deeply nested request payload (parent + properties) validated layer by
    layer with Notion-style error messages. Success and error responses
    share no keys.
  - M0 lives in prompt.md/data.py: the prompt states goal + deliverable
    contract only; formulas/conventions live in the workspace policy,
    methodology, and constraints documents.
Task data, business logic, deliverables, and ground truth are unchanged
from the base environment; step() gains one DB-state criterion
(db_dispatches_recorded, 10 pts) for the M4 write tool, offset by
technician_validity 15 -> 5.
"""
import ast
import csv
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta
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

    # ── Tool Methods ────────────────────────────────────────────────────────

    @tool(
        description=(
            "List vehicles in the fleet. Returns a paginated list (20 vehicles "
            "per page); each entry contains vehicle_id, make, model, year, "
            "category, and depot_id. Filtering is expressed as a JSON-encoded "
            "string, e.g. filter='{\"depot_id\": \"North\", \"category\": "
            "\"truck\"}'. Supported filter properties: depot_id (string) and "
            "category (string: sedan | suv | truck | van | bus)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"depot_id\": \"Central\"}'. Pass '{}' or omit for "
                        "no filtering."
                    ),
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based, default 1).",
                },
            },
            "required": [],
        },
    )
    def list_vehicles(self, filter: Any = None, page: int = 1):
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"depot_id", "category"}
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: depot_id, category.")

        clauses = []
        params: list = []
        if "depot_id" in parsed:
            depot_id = parsed["depot_id"]
            if not isinstance(depot_id, str) or not depot_id:
                return _error(400, "validation_error",
                    f"body.filter.depot_id should be a non-empty string, "
                    f"instead was {_shape(depot_id)}.")
            clauses.append("depot_id = ?")
            params.append(depot_id)
        if "category" in parsed:
            category = parsed["category"]
            if not isinstance(category, str) or category not in (
                "sedan", "suv", "truck", "van", "bus"
            ):
                return _error(400, "validation_error",
                    f"body.filter.category should be one of \"sedan\", \"suv\", "
                    f"\"truck\", \"van\", \"bus\", instead was {_shape(category)}.")
            clauses.append("category = ?")
            params.append(category)

        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            return _error(400, "validation_error",
                f"body.page should be a positive integer, instead was {_shape(page)}.")

        page_size = 20
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        where = (" AND " + " AND ".join(clauses)) if clauses else ""
        q = ("SELECT vehicle_id, make, model, year, category, depot_id "
             "FROM vehicles WHERE 1=1" + where + " ORDER BY vehicle_id")
        rows = conn.execute(q, params).fetchall()
        conn.close()

        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start: start + page_size]
        return {
            "vehicles": [dict(r) for r in page_rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": start + page_size < total,
        }

    @tool(
        description="Get full details for a single vehicle by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "vehicle_id": {
                    "type": "string",
                    "description": "Vehicle identifier, e.g. 'V0001'.",
                },
            },
            "required": ["vehicle_id"],
        },
    )
    def get_vehicle_details(self, vehicle_id: str = None):
        if not isinstance(vehicle_id, str) or not vehicle_id:
            return _error(400, "validation_error",
                f"body.vehicle_id should be a non-empty string, instead was "
                f"{_shape(vehicle_id)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM vehicles WHERE vehicle_id = ?", (vehicle_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                f"Could not find vehicle with ID: {vehicle_id}.")
        return dict(row)

    @tool(
        description=(
            "Retrieve all maintenance rules applicable to a given vehicle category. "
            "Each rule includes mileage and engine-hours intervals, priority base, "
            "required certification level, and estimated duration."
        ),
        parameters={
            "type": "object",
            "properties": {
                "vehicle_category": {
                    "type": "string",
                    "description": "Vehicle category (sedan, suv, truck, van, bus).",
                },
            },
            "required": ["vehicle_category"],
        },
    )
    def get_maintenance_rules(self, vehicle_category: str = None):
        if not isinstance(vehicle_category, str) or not vehicle_category:
            return _error(400, "validation_error",
                f"body.vehicle_category should be a non-empty string, instead was "
                f"{_shape(vehicle_category)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM maintenance_rules WHERE vehicle_category = ? ORDER BY rule_id",
            (vehicle_category,),
        ).fetchall()
        conn.close()
        return {"rules": [dict(r) for r in rows]}

    @tool(
        description=(
            "Get the service history for a specific vehicle.  Returns all past "
            "maintenance records including maintenance type, service date, mileage "
            "and engine hours at service, and the technician who performed it."
        ),
        parameters={
            "type": "object",
            "properties": {
                "vehicle_id": {
                    "type": "string",
                    "description": "Vehicle identifier, e.g. 'V0001'.",
                },
            },
            "required": ["vehicle_id"],
        },
    )
    def get_service_history(self, vehicle_id: str = None):
        if not isinstance(vehicle_id, str) or not vehicle_id:
            return _error(400, "validation_error",
                f"body.vehicle_id should be a non-empty string, instead was "
                f"{_shape(vehicle_id)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        exists = conn.execute(
            "SELECT 1 FROM vehicles WHERE vehicle_id = ?", (vehicle_id,)
        ).fetchone()
        if exists is None:
            conn.close()
            return _error(404, "object_not_found",
                f"Could not find vehicle with ID: {vehicle_id}.")
        rows = conn.execute(
            "SELECT * FROM service_history WHERE vehicle_id = ? ORDER BY service_date DESC",
            (vehicle_id,),
        ).fetchall()
        conn.close()
        return {"vehicle_id": vehicle_id, "records": [dict(r) for r in rows]}

    @tool(
        description=(
            "Check parts availability for a given maintenance type.  Returns the "
            "overall status ('ready', 'low_stock', or 'backordered') and details "
            "for each required part."
        ),
        parameters={
            "type": "object",
            "properties": {
                "maintenance_type": {
                    "type": "string",
                    "description": "Maintenance type name (e.g. 'oil_change').",
                },
            },
            "required": ["maintenance_type"],
        },
    )
    def check_parts_availability(self, maintenance_type: str = None):
        if not isinstance(maintenance_type, str) or not maintenance_type:
            return _error(400, "validation_error",
                f"body.maintenance_type should be a non-empty string, instead was "
                f"{_shape(maintenance_type)}.")
        base_type = re.sub(r"_tier\d+$", "", maintenance_type)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT part_id, part_name, quantity_on_hand, reorder_point "
            "FROM parts_inventory WHERE compatible_types = ?",
            (base_type,),
        ).fetchall()
        conn.close()

        if not rows:
            return {"maintenance_type": maintenance_type, "status": "ready", "parts": []}

        any_backordered = False
        any_low = False
        parts_list = []
        for r in rows:
            r = dict(r)
            if r["quantity_on_hand"] == 0:
                any_backordered = True
                r["status"] = "backordered"
            elif r["quantity_on_hand"] <= r["reorder_point"]:
                any_low = True
                r["status"] = "low_stock"
            else:
                r["status"] = "available"
            parts_list.append(r)

        if any_backordered:
            overall = "backordered"
        elif any_low:
            overall = "low_stock"
        else:
            overall = "ready"

        return {"maintenance_type": maintenance_type, "status": overall, "parts": parts_list}

    @tool(
        description=(
            "List technicians. Returns a paginated list (20 per page); each "
            "entry contains tech_id, name, cert_level, max_weekly_hours, "
            "depot_id, and hourly_rate. Filtering is expressed as a "
            "JSON-encoded string, e.g. filter='{\"depot_id\": \"South\", "
            "\"min_cert_level\": 3}'. Supported filter properties: depot_id "
            "(string) and min_cert_level (integer 1-5, matches technicians at "
            "or above that certification level)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"min_cert_level\": 2}'. Pass '{}' or omit for no "
                        "filtering."
                    ),
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based, default 1).",
                },
            },
            "required": [],
        },
    )
    def list_technicians(self, filter: Any = None, page: int = 1):
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"depot_id", "min_cert_level"}
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: depot_id, min_cert_level.")

        clauses = []
        params: list = []
        if "depot_id" in parsed:
            depot_id = parsed["depot_id"]
            if not isinstance(depot_id, str) or not depot_id:
                return _error(400, "validation_error",
                    f"body.filter.depot_id should be a non-empty string, "
                    f"instead was {_shape(depot_id)}.")
            clauses.append("depot_id = ?")
            params.append(depot_id)
        if "min_cert_level" in parsed:
            min_cert = parsed["min_cert_level"]
            if not isinstance(min_cert, int) or isinstance(min_cert, bool) \
                    or not 1 <= min_cert <= 5:
                return _error(400, "validation_error",
                    f"body.filter.min_cert_level should be an integer between "
                    f"1 and 5, instead was {_shape(min_cert)}.")
            clauses.append("cert_level >= ?")
            params.append(min_cert)

        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            return _error(400, "validation_error",
                f"body.page should be a positive integer, instead was {_shape(page)}.")

        page_size = 20
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        where = (" AND " + " AND ".join(clauses)) if clauses else ""
        q = "SELECT * FROM technicians WHERE 1=1" + where + " ORDER BY tech_id"
        rows = conn.execute(q, params).fetchall()
        conn.close()

        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start: start + page_size]
        return {
            "technicians": [dict(r) for r in page_rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": start + page_size < total,
        }

    @tool(
        description="Get full details for a single technician by ID.",
        parameters={
            "type": "object",
            "properties": {
                "tech_id": {
                    "type": "string",
                    "description": "Technician identifier, e.g. 'T0001'.",
                },
            },
            "required": ["tech_id"],
        },
    )
    def get_technician_details(self, tech_id: str = None):
        if not isinstance(tech_id, str) or not tech_id:
            return _error(400, "validation_error",
                f"body.tech_id should be a non-empty string, instead was "
                f"{_shape(tech_id)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM technicians WHERE tech_id = ?", (tech_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                f"Could not find technician with ID: {tech_id}.")
        return dict(row)

    @tool(
        description=(
            "Records a preventative-maintenance work order in the fleet "
            "dispatch system, placing a job into a technician's dispatch "
            "queue. The request body must contain a `parent` object "
            "identifying the receiving technician queue and a `properties` "
            "object with `Vehicle` (reference), `Maintenance` (select), and "
            "`Day` (date) properties. Example body: "
            "{\"parent\": {\"type\": \"dispatch_queue\", \"tech_id\": "
            "\"T0007\"}, \"properties\": {\"Vehicle\": {\"type\": "
            "\"reference\", \"reference\": {\"vehicle_id\": \"V0003\"}}, "
            "\"Maintenance\": {\"type\": \"select\", \"select\": {\"name\": "
            "\"oil_change\"}}, \"Day\": {\"type\": \"date\", \"date\": "
            "{\"start\": \"2026-04-27\"}}}}. An optional `Note` rich_text "
            "property may be included in `properties`. On success the work "
            "order is stored and appears in the dispatch system."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "The work-order request body.",
                    "properties": {
                        "parent": {
                            "type": "object",
                            "description": (
                                "The technician dispatch queue that receives "
                                "the work order. Must contain "
                                "type='dispatch_queue' and a tech_id string."
                            ),
                            "properties": {
                                "type": {"type": "string"},
                                "tech_id": {"type": "string"},
                            },
                            "required": ["type", "tech_id"],
                            "additionalProperties": True,
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Work-order properties. Must include a "
                                "'Vehicle' reference property, a "
                                "'Maintenance' select property, and a 'Day' "
                                "date property. May include a 'Note' "
                                "rich_text property."
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
        if parent.get("type") != "dispatch_queue":
            return _error(400, "validation_error",
                f"body.parent.type should be \"dispatch_queue\", instead was "
                f"{_shape(parent.get('type'))}.")
        tech_id = parent.get("tech_id")
        if not isinstance(tech_id, str) or not tech_id:
            return _error(400, "validation_error",
                f"body.parent.tech_id should be a non-empty string, instead was "
                f"{_shape(tech_id)}.")

        props = payload.get("properties")
        if props is None:
            return _error(400, "validation_error",
                "body.properties should be defined, instead was 'undefined'.")
        if not isinstance(props, dict):
            return _error(400, "validation_error",
                f"body.properties should be an object, instead was {_shape(props)}.")

        vehicle_prop = props.get("Vehicle")
        if vehicle_prop is None:
            return _error(400, "validation_error",
                "body.properties.Vehicle should be defined, instead was 'undefined'.")
        if not isinstance(vehicle_prop, dict):
            return _error(400, "validation_error",
                f"body.properties.Vehicle should be an object, instead was "
                f"{_shape(vehicle_prop)}.")
        if vehicle_prop.get("type") != "reference":
            return _error(400, "validation_error",
                f"body.properties.Vehicle.type should be \"reference\", instead was "
                f"{_shape(vehicle_prop.get('type'))}.")
        reference = vehicle_prop.get("reference")
        if not isinstance(reference, dict):
            return _error(400, "validation_error",
                f"body.properties.Vehicle.reference should be an object, instead was "
                f"{_shape(reference)}.")
        vehicle_id = reference.get("vehicle_id")
        if not isinstance(vehicle_id, str) or not vehicle_id:
            return _error(400, "validation_error",
                f"body.properties.Vehicle.reference.vehicle_id should be a non-empty "
                f"string, instead was {_shape(vehicle_id)}.")

        maint_prop = props.get("Maintenance")
        if maint_prop is None:
            return _error(400, "validation_error",
                "body.properties.Maintenance should be defined, instead was 'undefined'.")
        if not isinstance(maint_prop, dict):
            return _error(400, "validation_error",
                f"body.properties.Maintenance should be an object, instead was "
                f"{_shape(maint_prop)}.")
        if maint_prop.get("type") != "select":
            return _error(400, "validation_error",
                f"body.properties.Maintenance.type should be \"select\", instead was "
                f"{_shape(maint_prop.get('type'))}.")
        select = maint_prop.get("select")
        if not isinstance(select, dict):
            return _error(400, "validation_error",
                f"body.properties.Maintenance.select should be an object, instead was "
                f"{_shape(select)}.")
        maintenance_type = select.get("name")
        if not isinstance(maintenance_type, str) or not maintenance_type:
            return _error(400, "validation_error",
                f"body.properties.Maintenance.select.name should be a non-empty "
                f"string, instead was {_shape(maintenance_type)}.")

        day_prop = props.get("Day")
        if day_prop is None:
            return _error(400, "validation_error",
                "body.properties.Day should be defined, instead was 'undefined'.")
        if not isinstance(day_prop, dict):
            return _error(400, "validation_error",
                f"body.properties.Day should be an object, instead was "
                f"{_shape(day_prop)}.")
        if day_prop.get("type") != "date":
            return _error(400, "validation_error",
                f"body.properties.Day.type should be \"date\", instead was "
                f"{_shape(day_prop.get('type'))}.")
        date_obj = day_prop.get("date")
        if not isinstance(date_obj, dict):
            return _error(400, "validation_error",
                f"body.properties.Day.date should be an object, instead was "
                f"{_shape(date_obj)}.")
        scheduled_day = date_obj.get("start")
        if not isinstance(scheduled_day, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", scheduled_day
        ):
            return _error(400, "validation_error",
                f"body.properties.Day.date.start should be an ISO date string "
                f"(YYYY-MM-DD), instead was {_shape(scheduled_day)}.")

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
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT 1 FROM technicians WHERE tech_id = ?", (tech_id,))
        if c.fetchone() is None:
            conn.close()
            return _error(404, "object_not_found",
                f"Could not find technician queue with ID: {tech_id}.")
        c.execute("SELECT 1 FROM vehicles WHERE vehicle_id = ?", (vehicle_id,))
        if c.fetchone() is None:
            conn.close()
            return _error(404, "object_not_found",
                f"Could not find vehicle with ID: {vehicle_id}.")
        c.execute(
            "CREATE TABLE IF NOT EXISTS dispatch_orders ("
            "order_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "vehicle_id TEXT, maintenance_type TEXT, "
            "tech_id TEXT, scheduled_day TEXT)"
        )
        c.execute(
            "SELECT 1 FROM dispatch_orders WHERE vehicle_id = ? AND maintenance_type = ?",
            (vehicle_id, maintenance_type),
        )
        if c.fetchone() is not None:
            conn.close()
            return _error(400, "validation_error",
                f"A work order for vehicle '{vehicle_id}' and maintenance type "
                f"'{maintenance_type}' has already been recorded.")

        # --- Record the work order ---
        c.execute(
            "INSERT INTO dispatch_orders "
            "(vehicle_id, maintenance_type, tech_id, scheduled_day) "
            "VALUES (?, ?, ?, ?)",
            (vehicle_id, maintenance_type, tech_id, scheduled_day),
        )
        conn.commit()
        conn.close()

        # Success response: deep echo, shape entirely different from errors.
        return {
            "object": "work_order",
            "id": "wo_" + hashlib.md5(
                f"{vehicle_id}:{maintenance_type}:{tech_id}:{scheduled_day}".encode()
            ).hexdigest()[:10],
            "parent": {"type": "dispatch_queue", "tech_id": tech_id},
            "properties": {
                "Vehicle": {"type": "reference", "reference": {"vehicle_id": vehicle_id}},
                "Maintenance": {"type": "select", "select": {"name": maintenance_type}},
                "Day": {"type": "date", "date": {"start": scheduled_day}},
                "Status": {"type": "select", "select": {"name": "scheduled"}},
            },
            "created": True,
        }

    # ── Ground-truth computation (shared by step & verify) ──────────────────

    def _read_workspace_telemetry(self) -> Dict[str, Dict]:
        """Read all telemetry CSVs from workspace → {vehicle_id: {odometer_miles, engine_hours}}."""
        telemetry = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("telemetry_batch_") and fname.endswith(".csv"):
                path = os.path.join(self.workspace, fname)
                with open(path, newline="") as f:
                    for row in csv.DictReader(f):
                        telemetry[row["vehicle_id"]] = {
                            "odometer_miles": int(row["odometer_miles"]),
                            "engine_hours": int(row["engine_hours"]),
                        }
        return telemetry

    def _read_workspace_reservations(self) -> Dict[str, set]:
        """Read all reservation JSONs → {vehicle_id: set of ISO date strings within sched week}."""
        # Load scheduling week dates
        sc_path = os.path.join(self.workspace, "scheduling_constraints.json")
        with open(sc_path) as f:
            sc = json.load(f)
        week_dates_set = set(sc["available_days"])

        reservations: Dict[str, set] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("reservations_") and fname.endswith(".json"):
                path = os.path.join(self.workspace, fname)
                with open(path) as f:
                    entries = json.load(f)
                for entry in entries:
                    vid = entry["vehicle_id"]
                    start = datetime.strptime(entry["start_date"], "%Y-%m-%d")
                    end = datetime.strptime(entry["end_date"], "%Y-%m-%d")
                    d = start
                    while d <= end:
                        ds = d.strftime("%Y-%m-%d")
                        if ds in week_dates_set:
                            reservations.setdefault(vid, set()).add(ds)
                        d += timedelta(days=1)
        return reservations

    def _read_workspace_policy(self):
        with open(os.path.join(self.workspace, "maintenance_policy.yaml")) as f:
            return yaml.safe_load(f)

    def _read_workspace_schedule_config(self):
        with open(os.path.join(self.workspace, "scheduling_constraints.json")) as f:
            return json.load(f)

    def _compute_ground_truth(self):
        """Compute expected dispatch list using direct DB access + workspace files."""
        telemetry = self._read_workspace_telemetry()
        reservations = self._read_workspace_reservations()
        policy = self._read_workspace_policy()
        sched = self._read_workspace_schedule_config()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # All vehicles
        vehicles = [dict(r) for r in conn.execute("SELECT * FROM vehicles ORDER BY vehicle_id").fetchall()]
        # Rules by category
        rules_by_cat: Dict[str, list] = {}
        for r in conn.execute("SELECT * FROM maintenance_rules ORDER BY rule_id").fetchall():
            r = dict(r)
            rules_by_cat.setdefault(r["vehicle_category"], []).append(r)
        # Service history → most recent per (vehicle, mtype)
        last_service: Dict[str, Dict[str, dict]] = {}
        for r in conn.execute("SELECT * FROM service_history ORDER BY service_date DESC").fetchall():
            r = dict(r)
            vid, mt = r["vehicle_id"], r["maintenance_type"]
            last_service.setdefault(vid, {})
            if mt not in last_service[vid]:
                last_service[vid][mt] = r
        # Technicians
        all_techs = [dict(r) for r in conn.execute("SELECT * FROM technicians ORDER BY tech_id").fetchall()]
        conn.close()

        due_threshold = float(policy["due_threshold"])
        critical_threshold = float(policy["critical_threshold"])
        std_mult = float(policy["standard_multiplier"])
        crit_mult = float(policy["critical_multiplier"])
        no_hist_ratio = float(policy["no_history_overdue_ratio"])

        # Collect all due items
        due_items = []
        for v in vehicles:
            vid = v["vehicle_id"]
            if vid not in telemetry:
                continue
            cur = telemetry[vid]
            cat = v["category"]
            for rule in rules_by_cat.get(cat, []):
                mt = rule["maintenance_type"]
                svc = last_service.get(vid, {}).get(mt)
                if svc:
                    mi_ratio = (cur["odometer_miles"] - svc["mileage_at_service"]) / rule["mileage_interval"]
                    eh_ratio = (cur["engine_hours"] - svc["engine_hours_at_service"]) / rule["engine_hours_interval"]
                    overdue_ratio = max(mi_ratio, eh_ratio)
                else:
                    overdue_ratio = no_hist_ratio

                if overdue_ratio >= due_threshold:
                    mult = crit_mult if overdue_ratio >= critical_threshold else std_mult
                    urgency_score = round(overdue_ratio * rule["priority_base"] * mult, 2)
                    due_items.append({
                        "vehicle_id": vid,
                        "maintenance_type": mt,
                        "urgency_score": urgency_score,
                        "overdue_ratio": overdue_ratio,
                        "required_cert_level": rule["required_cert_level"],
                        "estimated_duration_hours": rule["estimated_duration_hours"],
                        "depot_id": v["depot_id"],
                    })

        # Sort: urgency DESC, vehicle_id ASC, maintenance_type ASC
        due_items.sort(key=lambda x: (-x["urgency_score"], x["vehicle_id"], x["maintenance_type"]))

        # Parts cache
        parts_cache = {}
        conn2 = sqlite3.connect(self.db_path)
        conn2.row_factory = sqlite3.Row
        for item in due_items:
            mt = item["maintenance_type"]
            if mt not in parts_cache:
                base_type = re.sub(r"_tier\d+$", "", mt)
                rows = conn2.execute(
                    "SELECT part_id, part_name, quantity_on_hand, reorder_point "
                    "FROM parts_inventory WHERE compatible_types = ?",
                    (base_type,),
                ).fetchall()
                any_bo = any(r["quantity_on_hand"] == 0 for r in rows)
                any_low = any(0 < r["quantity_on_hand"] <= r["reorder_point"] for r in rows)
                if any_bo:
                    parts_cache[mt] = "backordered"
                elif any_low:
                    parts_cache[mt] = "low_stock"
                else:
                    parts_cache[mt] = "ready"
        conn2.close()

        # Schedule
        week_dates = sched["available_days"]
        max_per_day = int(sched["max_dispatches_per_day"])
        max_tech_h_day = float(sched["max_hours_per_technician_per_day"])

        day_count = {d: 0 for d in week_dates}
        tech_day_h = {t["tech_id"]: {d: 0.0 for d in week_dates} for t in all_techs}
        tech_week_h = {t["tech_id"]: 0.0 for t in all_techs}

        dispatch = []
        rank = 1
        for item in due_items:
            v_res = reservations.get(item["vehicle_id"], set())
            scheduled = False
            for day in week_dates:
                if day in v_res:
                    continue
                if day_count[day] >= max_per_day:
                    continue
                eligible = []
                for t in all_techs:
                    if t["depot_id"] != item["depot_id"]:
                        continue
                    if t["cert_level"] < item["required_cert_level"]:
                        continue
                    if tech_day_h[t["tech_id"]][day] + item["estimated_duration_hours"] > max_tech_h_day:
                        continue
                    if tech_week_h[t["tech_id"]] + item["estimated_duration_hours"] > t["max_weekly_hours"]:
                        continue
                    eligible.append(t)
                if not eligible:
                    continue
                eligible.sort(key=lambda t: (t["hourly_rate"], t["tech_id"]))
                chosen = eligible[0]

                dispatch.append({
                    "priority_rank": rank,
                    "vehicle_id": item["vehicle_id"],
                    "maintenance_type": item["maintenance_type"],
                    "urgency_score": f"{item['urgency_score']:.2f}",
                    "assigned_tech_id": chosen["tech_id"],
                    "scheduled_day": day,
                    "estimated_duration_hours": f"{item['estimated_duration_hours']:.1f}",
                    "parts_status": parts_cache.get(item["maintenance_type"], "ready"),
                })
                day_count[day] += 1
                tech_day_h[chosen["tech_id"]][day] += item["estimated_duration_hours"]
                tech_week_h[chosen["tech_id"]] += item["estimated_duration_hours"]
                rank += 1
                scheduled = True
                break

        return dispatch, policy

    # ── Evaluation ──────────────────────────────────────────────────────────

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
        expected_dispatch, policy = self._compute_ground_truth()
        criteria = {}

        EXPECTED_COLS = [
            "priority_rank", "vehicle_id", "maintenance_type", "urgency_score",
            "assigned_tech_id", "scheduled_day", "estimated_duration_hours", "parts_status",
        ]

        # ── 1. File format (10 pts) ───────────────────────────────────────
        csv_path = os.path.join(self.workspace, "dispatch_list.csv")
        agent_rows = []
        fmt_ok = False
        if os.path.isfile(csv_path):
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames or []
                if cols == EXPECTED_COLS:
                    fmt_ok = True
                    for row in reader:
                        agent_rows.append(row)
        criteria["dispatch_file_format"] = {
            "passed": fmt_ok,
            "score": 10 if fmt_ok else 0,
            "max_score": 10,
            "reason": None if fmt_ok else "dispatch_list.csv missing or wrong columns",
        }

        # ── 1b. Work orders recorded via dispatch system (10 pts) ─────────
        conn_db = sqlite3.connect(self.db_path)
        try:
            db_rows = conn_db.execute(
                "SELECT vehicle_id, maintenance_type, tech_id, scheduled_day "
                "FROM dispatch_orders"
            ).fetchall()
        except sqlite3.OperationalError:
            db_rows = []
        conn_db.close()
        db_map = {(r[0], r[1]): (r[2], r[3]) for r in db_rows}
        if len(expected_dispatch) == 0:
            db_frac = 1.0
        else:
            db_ok = sum(
                1 for er in expected_dispatch
                if db_map.get((er["vehicle_id"], er["maintenance_type"]))
                == (er["assigned_tech_id"], er["scheduled_day"])
            )
            db_frac = db_ok / len(expected_dispatch)
        db_pts = round(10 * db_frac)
        criteria["db_dispatches_recorded"] = {
            "passed": db_frac >= 0.95,
            "score": db_pts,
            "max_score": 10,
            "reason": None if db_frac >= 0.95 else f"recorded {db_frac:.2%}",
        }

        if not fmt_ok:
            # Can't evaluate further
            total = sum(c["score"] for c in criteria.values())
            max_total = 100
            return total / max_total, {
                "eval_criteria": criteria,
                "total_score": total,
                "max_score": max_total,
            }

        # Build lookup for expected dispatch
        exp_lookup = {}  # (vehicle_id, mtype) -> expected row
        for er in expected_dispatch:
            exp_lookup[(er["vehicle_id"], er["maintenance_type"])] = er

        agent_lookup = {}
        for ar in agent_rows:
            agent_lookup[(ar["vehicle_id"], ar["maintenance_type"])] = ar

        # ── 2. Vehicle coverage (15 pts) ──────────────────────────────────
        exp_keys = set(exp_lookup.keys())
        agent_keys = set(agent_lookup.keys())
        if len(exp_keys) == 0:
            cov_frac = 1.0
        else:
            cov_frac = len(exp_keys & agent_keys) / len(exp_keys)
        cov_score = round(15 * cov_frac)
        criteria["vehicle_coverage"] = {
            "passed": cov_frac >= 0.95,
            "score": cov_score,
            "max_score": 15,
            "reason": None if cov_frac >= 0.95 else f"coverage {cov_frac:.2%}",
        }

        # ── 3. Urgency scores (15 pts) ────────────────────────────────────
        matched = exp_keys & agent_keys
        score_correct = 0
        for key in matched:
            exp_s = exp_lookup[key]["urgency_score"]
            try:
                agt_s = f"{float(agent_lookup[key]['urgency_score']):.2f}"
            except (ValueError, KeyError):
                agt_s = ""
            if agt_s == exp_s:
                score_correct += 1
        if len(matched) == 0:
            urg_frac = 0.0
        else:
            urg_frac = score_correct / len(matched)
        urg_pts = round(15 * urg_frac)
        criteria["urgency_scores"] = {
            "passed": urg_frac >= 0.95,
            "score": urg_pts,
            "max_score": 15,
            "reason": None if urg_frac >= 0.95 else f"accuracy {urg_frac:.2%}",
        }

        # ── 4. Priority ranking (15 pts) ──────────────────────────────────
        exp_order = [(r["vehicle_id"], r["maintenance_type"]) for r in expected_dispatch]
        agt_order = [(r["vehicle_id"], r["maintenance_type"]) for r in agent_rows]
        rank_ok = exp_order == agt_order
        criteria["priority_ranking"] = {
            "passed": rank_ok,
            "score": 15 if rank_ok else 0,
            "max_score": 15,
            "reason": None if rank_ok else "dispatch order does not match expected ranking",
        }

        # ── 5. Technician validity (5 pts) ────────────────────────────────
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        tech_map = {}
        for r in conn.execute("SELECT * FROM technicians").fetchall():
            tech_map[r["tech_id"]] = dict(r)
        vehicle_map = {}
        for r in conn.execute("SELECT * FROM vehicles").fetchall():
            vehicle_map[r["vehicle_id"]] = dict(r)
        rules_all = {}
        for r in conn.execute("SELECT * FROM maintenance_rules").fetchall():
            r = dict(r)
            rules_all.setdefault(r["vehicle_category"], {})[r["maintenance_type"]] = r
        conn.close()

        tech_valid_count = 0
        tech_total = len(agent_rows)
        for ar in agent_rows:
            vid = ar["vehicle_id"]
            mt = ar["maintenance_type"]
            tid = ar["assigned_tech_id"]
            v_info = vehicle_map.get(vid, {})
            t_info = tech_map.get(tid)
            rule_info = rules_all.get(v_info.get("category", ""), {}).get(mt)
            if t_info and rule_info and v_info:
                if (t_info["cert_level"] >= rule_info["required_cert_level"]
                        and t_info["depot_id"] == v_info["depot_id"]):
                    tech_valid_count += 1
        tech_frac = tech_valid_count / max(1, tech_total)
        tech_pts = round(5 * tech_frac)
        criteria["technician_validity"] = {
            "passed": tech_frac >= 0.95,
            "score": tech_pts,
            "max_score": 5,
            "reason": None if tech_frac >= 0.95 else f"valid {tech_frac:.2%}",
        }

        # ── 6. Parts status (10 pts) ──────────────────────────────────────
        parts_correct = 0
        for key in matched:
            if agent_lookup[key].get("parts_status") == exp_lookup[key]["parts_status"]:
                parts_correct += 1
        parts_frac = parts_correct / max(1, len(matched))
        parts_pts = round(10 * parts_frac)
        criteria["parts_status"] = {
            "passed": parts_frac >= 0.95,
            "score": parts_pts,
            "max_score": 10,
            "reason": None if parts_frac >= 0.95 else f"accuracy {parts_frac:.2%}",
        }

        # ── 7. Scheduling validity (10 pts) ───────────────────────────────
        reservations = self._read_workspace_reservations()
        sched = self._read_workspace_schedule_config()
        week_dates = set(sched["available_days"])
        max_per_day = int(sched["max_dispatches_per_day"])

        day_counts: Dict[str, int] = {}
        sched_violations = 0
        for ar in agent_rows:
            sd = ar["scheduled_day"]
            vid = ar["vehicle_id"]
            if sd not in week_dates:
                sched_violations += 1
                continue
            if sd in reservations.get(vid, set()):
                sched_violations += 1
            day_counts[sd] = day_counts.get(sd, 0) + 1

        for d, cnt in day_counts.items():
            if cnt > max_per_day:
                sched_violations += cnt - max_per_day

        sched_ok = sched_violations == 0
        criteria["scheduling_validity"] = {
            "passed": sched_ok,
            "score": 10 if sched_ok else max(0, 10 - sched_violations * 2),
            "max_score": 10,
            "reason": None if sched_ok else f"{sched_violations} scheduling violations",
        }

        # ── 8. Response summary (10 pts) ──────────────────────────────────
        tier_crit_thresh = float(policy["urgency_tiers"]["critical"]["min_score"])
        tier_high_thresh = float(policy["urgency_tiers"]["high"]["min_score"])

        exp_total_dispatches = len(expected_dispatch)
        exp_total_hours = sum(float(r["estimated_duration_hours"]) for r in expected_dispatch)
        exp_critical = sum(1 for r in expected_dispatch if float(r["urgency_score"]) >= tier_crit_thresh)
        exp_high = sum(
            1 for r in expected_dispatch
            if tier_high_thresh <= float(r["urgency_score"]) < tier_crit_thresh
        )
        exp_routine = exp_total_dispatches - exp_critical - exp_high

        summary_pts = 0
        # Check total dispatches
        if re.search(rf"Total dispatches:\s*{exp_total_dispatches}\b", action):
            summary_pts += 3
        # Check total hours
        exp_hours_str = f"{exp_total_hours:.1f}"
        if re.search(rf"Total estimated hours:\s*{re.escape(exp_hours_str)}\b", action):
            summary_pts += 3
        # Check tier breakdown
        tier_pat = rf"Critical:\s*{exp_critical}\b.*High:\s*{exp_high}\b.*Routine:\s*{exp_routine}\b"
        if re.search(tier_pat, action):
            summary_pts += 4

        criteria["response_summary"] = {
            "passed": summary_pts == 10,
            "score": summary_pts,
            "max_score": 10,
            "reason": None if summary_pts == 10 else "summary values do not match expected",
        }

        total = sum(c["score"] for c in criteria.values())
        max_total = sum(c["max_score"] for c in criteria.values())
        return total / max_total, {
            "eval_criteria": criteria,
            "total_score": total,
            "max_score": max_total,
        }

    # ── Verification ────────────────────────────────────────────────────────

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

        Note: the hardened surface requires JSON-encoded string filters for
        the list tools and nested request payloads for create_dispatch.
        """
        tool_calls = 0

        def _call(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        # ── 1. Read workspace files ─────────────────────────────────────
        telemetry = self._read_workspace_telemetry()
        reservations = self._read_workspace_reservations()
        policy = self._read_workspace_policy()
        sched = self._read_workspace_schedule_config()

        due_threshold = float(policy["due_threshold"])
        critical_threshold = float(policy["critical_threshold"])
        std_mult = float(policy["standard_multiplier"])
        crit_mult = float(policy["critical_multiplier"])
        no_hist_ratio = float(policy["no_history_overdue_ratio"])

        # ── 2. Gather all vehicles via tool (paginated, no filter) ──────
        all_vehicles = []
        page = 1
        while True:
            result = _call("list_vehicles", page=page)
            all_vehicles.extend(result["vehicles"])
            if not result["has_more"]:
                break
            page += 1

        # ── 3. Get maintenance rules per category ───────────────────────
        categories_seen = sorted(set(v["category"] for v in all_vehicles))
        rules_by_cat = {}
        for cat in categories_seen:
            res = _call("get_maintenance_rules", vehicle_category=cat)
            rules_by_cat[cat] = res["rules"]

        # ── 4. For each vehicle, get service history & compute overdue ──
        due_items = []
        for v in all_vehicles:
            vid = v["vehicle_id"]
            if vid not in telemetry:
                continue
            cur = telemetry[vid]

            hist_res = _call("get_service_history", vehicle_id=vid)
            last_svc = {}
            for rec in hist_res.get("records", []):
                mt = rec["maintenance_type"]
                if mt not in last_svc or rec["service_date"] > last_svc[mt]["service_date"]:
                    last_svc[mt] = rec

            for rule in rules_by_cat.get(v["category"], []):
                mt = rule["maintenance_type"]
                if mt in last_svc:
                    mi_ratio = (cur["odometer_miles"] - last_svc[mt]["mileage_at_service"]) / rule["mileage_interval"]
                    eh_ratio = (cur["engine_hours"] - last_svc[mt]["engine_hours_at_service"]) / rule["engine_hours_interval"]
                    overdue_ratio = max(mi_ratio, eh_ratio)
                else:
                    overdue_ratio = no_hist_ratio

                if overdue_ratio >= due_threshold:
                    mult = crit_mult if overdue_ratio >= critical_threshold else std_mult
                    urgency_score = round(overdue_ratio * rule["priority_base"] * mult, 2)
                    due_items.append({
                        "vehicle_id": vid,
                        "maintenance_type": mt,
                        "urgency_score": urgency_score,
                        "overdue_ratio": overdue_ratio,
                        "required_cert_level": rule["required_cert_level"],
                        "estimated_duration_hours": rule["estimated_duration_hours"],
                        "depot_id": v["depot_id"],
                    })

        # ── 5. Sort ─────────────────────────────────────────────────────
        due_items.sort(key=lambda x: (-x["urgency_score"], x["vehicle_id"], x["maintenance_type"]))

        # ── 6. Check parts availability for each unique mtype ───────────
        parts_cache = {}
        for item in due_items:
            mt = item["maintenance_type"]
            if mt not in parts_cache:
                res = _call("check_parts_availability", maintenance_type=mt)
                parts_cache[mt] = res["status"]

        # ── 7. Get all technicians via tool (JSON-string filter per depot)
        depots_seen = sorted(set(v["depot_id"] for v in all_vehicles))
        all_techs = []
        for depot in depots_seen:
            filter_str = json.dumps({"depot_id": depot})
            page = 1
            while True:
                result = _call("list_technicians", filter=filter_str, page=page)
                all_techs.extend(result["technicians"])
                if not result["has_more"]:
                    break
                page += 1
        all_techs.sort(key=lambda t: t["tech_id"])

        # ── 8. Greedy scheduling ────────────────────────────────────────
        week_dates = sched["available_days"]
        max_per_day = int(sched["max_dispatches_per_day"])
        max_tech_h_day = float(sched["max_hours_per_technician_per_day"])

        day_count = {d: 0 for d in week_dates}
        tech_day_h = {t["tech_id"]: {d: 0.0 for d in week_dates} for t in all_techs}
        tech_week_h = {t["tech_id"]: 0.0 for t in all_techs}

        dispatch_list = []
        rank = 1
        for item in due_items:
            v_res = reservations.get(item["vehicle_id"], set())
            for day in week_dates:
                if day in v_res:
                    continue
                if day_count[day] >= max_per_day:
                    continue
                eligible = []
                for t in all_techs:
                    if t["depot_id"] != item["depot_id"]:
                        continue
                    if t["cert_level"] < item["required_cert_level"]:
                        continue
                    if tech_day_h[t["tech_id"]][day] + item["estimated_duration_hours"] > max_tech_h_day:
                        continue
                    if tech_week_h[t["tech_id"]] + item["estimated_duration_hours"] > t["max_weekly_hours"]:
                        continue
                    eligible.append(t)
                if not eligible:
                    continue
                eligible.sort(key=lambda t: (t["hourly_rate"], t["tech_id"]))
                chosen = eligible[0]

                dispatch_list.append({
                    "priority_rank": rank,
                    "vehicle_id": item["vehicle_id"],
                    "maintenance_type": item["maintenance_type"],
                    "urgency_score": f"{item['urgency_score']:.2f}",
                    "assigned_tech_id": chosen["tech_id"],
                    "scheduled_day": day,
                    "estimated_duration_hours": f"{item['estimated_duration_hours']:.1f}",
                    "parts_status": parts_cache.get(item["maintenance_type"], "ready"),
                })
                day_count[day] += 1
                tech_day_h[chosen["tech_id"]][day] += item["estimated_duration_hours"]
                tech_week_h[chosen["tech_id"]] += item["estimated_duration_hours"]
                rank += 1
                break

        # ── 9. Record work orders via nested create_dispatch payloads ───
        recorded = 0
        for row in dispatch_list:
            result = _call(
                "create_dispatch",
                payload={
                    "parent": {"type": "dispatch_queue", "tech_id": row["assigned_tech_id"]},
                    "properties": {
                        "Vehicle": {
                            "type": "reference",
                            "reference": {"vehicle_id": row["vehicle_id"]},
                        },
                        "Maintenance": {
                            "type": "select",
                            "select": {"name": row["maintenance_type"]},
                        },
                        "Day": {
                            "type": "date",
                            "date": {"start": row["scheduled_day"]},
                        },
                    },
                },
            )
            if result.get("object") == "work_order" and result.get("created"):
                recorded += 1

        # ── 10. Write dispatch_list.csv ─────────────────────────────────
        fieldnames = [
            "priority_rank", "vehicle_id", "maintenance_type", "urgency_score",
            "assigned_tech_id", "scheduled_day", "estimated_duration_hours", "parts_status",
        ]
        csv_path = os.path.join(self.workspace, "dispatch_list.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in dispatch_list:
                writer.writerow(row)

        # ── 11. Build summary ───────────────────────────────────────────
        tier_crit = float(policy["urgency_tiers"]["critical"]["min_score"])
        tier_high = float(policy["urgency_tiers"]["high"]["min_score"])

        total_dispatches = len(dispatch_list)
        total_hours = sum(float(r["estimated_duration_hours"]) for r in dispatch_list)
        n_critical = sum(1 for r in dispatch_list if float(r["urgency_score"]) >= tier_crit)
        n_high = sum(1 for r in dispatch_list if tier_high <= float(r["urgency_score"]) < tier_crit)
        n_routine = total_dispatches - n_critical - n_high

        action = (
            f"The weekly preventative maintenance dispatch list has been generated "
            f"and saved as dispatch_list.csv. All {recorded} work orders have been "
            f"recorded in the fleet dispatch system.\n"
            f"Total dispatches: {total_dispatches}\n"
            f"Total estimated hours: {total_hours:.1f}\n"
            f"Critical: {n_critical}, High: {n_high}, Routine: {n_routine}"
        )

        print(f"[verify] total tool calls: {tool_calls}")
        return self.step(action)
