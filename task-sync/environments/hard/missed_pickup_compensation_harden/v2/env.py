"""
Environment for the missed-pickup compensation task (hardened tool surface).

Hardened surface (M1 + M4):
  - search_service_requests takes a single JSON-encoded string `filter`
    parameter; malformed JSON or unsupported keys produce recoverable
    API-style errors.
  - A new write tool, create_credit_memo, records each approved credit as a
    deeply nested request payload (parent + properties) validated layer by
    layer with Notion-style error messages. step() gains one DB-state
    criterion checking the recorded memos against the ground truth.
Task data, business logic, ground truth, and all original scoring criteria
are unchanged from the base environment.
"""

import csv
import hashlib
import io
import json
import math
import os
import sqlite3
import yaml
from typing import Tuple, Dict, List, Any


# ---------------------------------------------------------------------------
# Tool decorator
# ---------------------------------------------------------------------------

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


def _parse_json_string_param(raw, param_name: str):
    """Parse a parameter documented as a JSON-encoded string.

    Returns (value, None) on success or (None, error_dict) on failure, with
    error messages mirroring real API serialization failures.
    """
    if raw is None or raw == "":
        return {}, None
    if isinstance(raw, (dict, list)):
        return None, _error(
            400,
            "invalid_request",
            f"body.{param_name} should be a JSON-encoded string, instead was an object. "
            f"Serialize it to a JSON string before passing it.",
        )
    if not isinstance(raw, str):
        return None, _error(
            400,
            "invalid_request",
            f"body.{param_name} should be a JSON-encoded string, instead was "
            f"{type(raw).__name__}.",
        )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, _error(
            400,
            "invalid_json",
            f"Failed to parse {param_name}: {e.msg}: line {e.lineno} column {e.colno} "
            f"(char {e.pos})",
        )
    if not isinstance(value, dict):
        return None, _error(
            400,
            "invalid_request",
            f"body.{param_name} should encode a JSON object, instead was "
            f"{type(value).__name__}.",
        )
    return value, None


def _shape(value) -> str:
    """Short rendering of a wrong-typed value for error text."""
    if value is None:
        return "'undefined'"
    r = repr(value)
    if len(r) > 60:
        r = r[:57] + "..."
    return f"'{r}'"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    p = math.pi / 180
    a = (0.5 - math.cos((lat2 - lat1) * p) / 2 +
         math.cos(lat1 * p) * math.cos(lat2 * p) *
         (1 - math.cos((lon2 - lon1) * p)) / 2)
    return 2 * R * math.asin(math.sqrt(a))


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
    # Internal: credit-memo ledger table (created lazily on first write)
    # ------------------------------------------------------------------

    def _ensure_memo_table(self, conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS credit_memos ("
            "memo_id TEXT PRIMARY KEY, "
            "request_id TEXT NOT NULL UNIQUE, "
            "resident_id TEXT NOT NULL, "
            "miss_type TEXT NOT NULL, "
            "credit_amount REAL NOT NULL)"
        )

    # ===================================================================
    # TOOL METHODS
    # ===================================================================

    @tool(
        description=(
            "Search service requests. Filtering is expressed as a JSON-encoded "
            "string, e.g. filter='{\"request_type\": \"missed_pickup\", "
            "\"status\": \"pending_review\"}'. Supported filter properties: "
            "request_type (string) and status (string). Returns a paginated "
            "list with basic fields: request_id, resident_id, request_type, "
            "scheduled_pickup_date, status. Page numbering starts at 1."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"request_type\": \"missed_pickup\", "
                        "\"status\": \"pending_review\"}'. "
                        "Pass '{}' or omit for no filtering."
                    ),
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (starting from 1). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 20). Default 20.",
                },
            },
            "required": [],
        },
    )
    def search_service_requests(
        self,
        filter: Any = None,
        page: Any = 1,
        page_size: Any = 20,
    ) -> dict:
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = ("request_type", "status")
        for key in parsed:
            if key not in supported:
                return _error(
                    400,
                    "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: request_type, status.",
                )

        clauses, params = [], []
        for key in supported:
            if key in parsed:
                value = parsed[key]
                if not isinstance(value, str) or not value:
                    return _error(
                        400,
                        "validation_error",
                        f"body.filter.{key} should be a non-empty string, "
                        f"instead was {_shape(value)}.",
                    )
                clauses.append(f"{key} = ?")
                params.append(value)

        try:
            page = int(page)
            page_size = int(page_size)
        except (TypeError, ValueError):
            return _error(
                400,
                "validation_error",
                f"body.page and body.page_size should be integers, instead "
                f"were {_shape(page)} and {_shape(page_size)}.",
            )
        page_size = min(page_size, 20)
        page = max(page, 1)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM service_requests{where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT request_id, resident_id, request_type, "
            f"scheduled_pickup_date, status "
            f"FROM service_requests{where} "
            f"ORDER BY request_id "
            f"LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
        conn.close()
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "results": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "Get full details for a single service request by its request_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "The service request ID, e.g. 'SR00001'.",
                },
            },
            "required": ["request_id"],
        },
    )
    def get_request_details(self, request_id: str = None) -> dict:
        if not isinstance(request_id, str) or not request_id:
            return _error(
                400, "validation_error",
                f"body.request_id should be a non-empty string, instead was "
                f"{_shape(request_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM service_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return _error(
                404, "object_not_found",
                f"Could not find service request with ID: {request_id}.",
            )
        return {"request": dict(row)}

    @tool(
        description=(
            "Get resident information by resident_id. Returns name, address, "
            "latitude, longitude, zone_id, service_tier, and bin_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "resident_id": {
                    "type": "string",
                    "description": "The resident ID, e.g. 'R00001'.",
                },
            },
            "required": ["resident_id"],
        },
    )
    def get_resident_info(self, resident_id: str = None) -> dict:
        if not isinstance(resident_id, str) or not resident_id:
            return _error(
                400, "validation_error",
                f"body.resident_id should be a non-empty string, instead was "
                f"{_shape(resident_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM residents WHERE resident_id = ?",
            (resident_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return _error(
                404, "object_not_found",
                f"Could not find resident with ID: {resident_id}.",
            )
        return dict(row)

    @tool(
        description=(
            "Query GPS truck stops for a given truck on a specific date. "
            "Returns a list of stops with stop_id, latitude, longitude, "
            "stop_time, and stop_duration_sec."
        ),
        parameters={
            "type": "object",
            "properties": {
                "truck_id": {
                    "type": "string",
                    "description": "The truck ID, e.g. 'T001'.",
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format.",
                },
            },
            "required": ["truck_id", "date"],
        },
    )
    def query_gps_stops(self, truck_id: str = None, date: str = None) -> dict:
        if not isinstance(truck_id, str) or not truck_id:
            return _error(
                400, "validation_error",
                f"body.truck_id should be a non-empty string, instead was "
                f"{_shape(truck_id)}.",
            )
        if not isinstance(date, str) or not date:
            return _error(
                400, "validation_error",
                f"body.date should be a YYYY-MM-DD string, instead was "
                f"{_shape(date)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        known = conn.execute(
            "SELECT 1 FROM gps_stops WHERE truck_id = ? LIMIT 1",
            (truck_id,),
        ).fetchone()
        if known is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find truck with ID: {truck_id}.",
            )
        rows = conn.execute(
            "SELECT stop_id, latitude, longitude, stop_time, stop_duration_sec "
            "FROM gps_stops "
            "WHERE truck_id = ? AND stop_time LIKE ?",
            (truck_id, date + "%"),
        ).fetchall()
        conn.close()
        return {"truck_id": truck_id, "date": date, "stops": [dict(r) for r in rows]}

    @tool(
        description=(
            "Query bin lift sensor records for a specific bin on a given date. "
            "Returns lift_id, truck_id, lift_time, lift_successful, weight_kg."
        ),
        parameters={
            "type": "object",
            "properties": {
                "bin_id": {
                    "type": "string",
                    "description": "The bin ID, e.g. 'BIN00001'.",
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format.",
                },
            },
            "required": ["bin_id", "date"],
        },
    )
    def query_bin_lifts(self, bin_id: str = None, date: str = None) -> dict:
        if not isinstance(bin_id, str) or not bin_id:
            return _error(
                400, "validation_error",
                f"body.bin_id should be a non-empty string, instead was "
                f"{_shape(bin_id)}.",
            )
        if not isinstance(date, str) or not date:
            return _error(
                400, "validation_error",
                f"body.date should be a YYYY-MM-DD string, instead was "
                f"{_shape(date)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        known = conn.execute(
            "SELECT 1 FROM residents WHERE bin_id = ? LIMIT 1",
            (bin_id,),
        ).fetchone()
        if known is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find bin with ID: {bin_id}.",
            )
        rows = conn.execute(
            "SELECT lift_id, truck_id, lift_time, lift_successful, weight_kg "
            "FROM bin_lifts "
            "WHERE bin_id = ? AND lift_time LIKE ?",
            (bin_id, date + "%"),
        ).fetchall()
        conn.close()
        return {"bin_id": bin_id, "date": date, "lifts": [dict(r) for r in rows]}

    @tool(
        description=(
            "Check how many resolved missed-pickup claims exist for a resident "
            "within a date window. Useful for determining repeat-miss status. "
            "Returns the count and the matching request IDs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "resident_id": {
                    "type": "string",
                    "description": "The resident ID.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start of window (inclusive) YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End of window (exclusive) YYYY-MM-DD.",
                },
            },
            "required": ["resident_id", "start_date", "end_date"],
        },
    )
    def check_prior_claims(
        self,
        resident_id: str = None,
        start_date: str = None,
        end_date: str = None,
    ) -> dict:
        for pname, pval in (("resident_id", resident_id),
                            ("start_date", start_date),
                            ("end_date", end_date)):
            if not isinstance(pval, str) or not pval:
                return _error(
                    400, "validation_error",
                    f"body.{pname} should be a non-empty string, instead was "
                    f"{_shape(pval)}.",
                )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT request_id, scheduled_pickup_date FROM service_requests "
            "WHERE resident_id = ? AND request_type = 'missed_pickup' "
            "AND status = 'resolved' "
            "AND scheduled_pickup_date >= ? AND scheduled_pickup_date < ?",
            (resident_id, start_date, end_date),
        ).fetchall()
        conn.close()
        return {
            "resident_id": resident_id,
            "window": f"{start_date} to {end_date}",
            "count": len(rows),
            "claims": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "Creates a credit memo: posts an approved missed-pickup credit to "
            "a resident's account in the compensation ledger. The request body "
            "must contain a `parent` object identifying the resident account "
            "and a `properties` object with a `Request` reference property, a "
            "`MissType` select property, and a `Credit` number property. "
            "Example body: {\"parent\": {\"type\": \"resident_account\", "
            "\"resident_id\": \"R00001\"}, \"properties\": {\"Request\": "
            "{\"type\": \"reference\", \"reference\": {\"request_id\": "
            "\"SR00001\"}}, \"MissType\": {\"type\": \"select\", \"select\": "
            "{\"name\": \"full_miss\"}}, \"Credit\": {\"type\": \"number\", "
            "\"number\": 12.75}}}. An optional `Note` rich_text property may "
            "be included in `properties`. Each service request can receive at "
            "most one credit memo."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "The credit-memo request body.",
                    "properties": {
                        "parent": {
                            "type": "object",
                            "description": (
                                "The resident account that receives the "
                                "credit. Must contain type='resident_account' "
                                "and a resident_id string."
                            ),
                            "properties": {
                                "type": {"type": "string"},
                                "resident_id": {"type": "string"},
                            },
                            "required": ["type", "resident_id"],
                            "additionalProperties": True,
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Credit-memo properties. Must include a "
                                "'Request' reference property, a 'MissType' "
                                "select property, and a 'Credit' number "
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
    def create_credit_memo(self, payload: Any = None) -> dict:
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
        if parent.get("type") != "resident_account":
            return _error(
                400, "validation_error",
                f"body.parent.type should be \"resident_account\", instead was "
                f"{_shape(parent.get('type'))}.",
            )
        resident_id = parent.get("resident_id")
        if not isinstance(resident_id, str) or not resident_id:
            return _error(
                400, "validation_error",
                f"body.parent.resident_id should be a non-empty string, instead "
                f"was {_shape(resident_id)}.",
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

        # -- Request reference property --
        req_prop = props.get("Request")
        if req_prop is None:
            return _error(
                400, "validation_error",
                "body.properties.Request should be defined, instead was 'undefined'.",
            )
        if not isinstance(req_prop, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Request should be an object, instead was "
                f"{_shape(req_prop)}.",
            )
        if req_prop.get("type") != "reference":
            return _error(
                400, "validation_error",
                f"body.properties.Request.type should be \"reference\", instead "
                f"was {_shape(req_prop.get('type'))}.",
            )
        reference = req_prop.get("reference")
        if not isinstance(reference, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Request.reference should be an object, instead "
                f"was {_shape(reference)}.",
            )
        request_id = reference.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return _error(
                400, "validation_error",
                f"body.properties.Request.reference.request_id should be a "
                f"non-empty string, instead was {_shape(request_id)}.",
            )

        # -- MissType select property --
        mt_prop = props.get("MissType")
        if mt_prop is None:
            return _error(
                400, "validation_error",
                "body.properties.MissType should be defined, instead was 'undefined'.",
            )
        if not isinstance(mt_prop, dict):
            return _error(
                400, "validation_error",
                f"body.properties.MissType should be an object, instead was "
                f"{_shape(mt_prop)}.",
            )
        if mt_prop.get("type") != "select":
            return _error(
                400, "validation_error",
                f"body.properties.MissType.type should be \"select\", instead "
                f"was {_shape(mt_prop.get('type'))}.",
            )
        select = mt_prop.get("select")
        if not isinstance(select, dict):
            return _error(
                400, "validation_error",
                f"body.properties.MissType.select should be an object, instead "
                f"was {_shape(select)}.",
            )
        miss_type = select.get("name")
        if miss_type not in ("full_miss", "partial_miss"):
            return _error(
                400, "validation_error",
                f"body.properties.MissType.select.name should be one of "
                f"\"full_miss\", \"partial_miss\", instead was {_shape(miss_type)}.",
            )

        # -- Credit number property --
        cr_prop = props.get("Credit")
        if cr_prop is None:
            return _error(
                400, "validation_error",
                "body.properties.Credit should be defined, instead was 'undefined'.",
            )
        if not isinstance(cr_prop, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Credit should be an object, instead was "
                f"{_shape(cr_prop)}.",
            )
        if cr_prop.get("type") != "number":
            return _error(
                400, "validation_error",
                f"body.properties.Credit.type should be \"number\", instead was "
                f"{_shape(cr_prop.get('type'))}.",
            )
        credit = cr_prop.get("number")
        if isinstance(credit, bool) or not isinstance(credit, (int, float)):
            return _error(
                400, "validation_error",
                f"body.properties.Credit.number should be a number, instead was "
                f"{_shape(credit)}.",
            )
        if credit <= 0:
            return _error(
                400, "validation_error",
                f"body.properties.Credit.number should be a positive number, "
                f"instead was {_shape(credit)}.",
            )

        # -- Optional Note rich_text property --
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
                    f"body.properties.Note.rich_text should be an array, instead "
                    f"was {_shape(rich)}.",
                )
            for i, item in enumerate(rich):
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("text"), dict)
                    or not isinstance(item["text"].get("content"), str)
                ):
                    return _error(
                        400, "validation_error",
                        f"body.properties.Note.rich_text[{i}].text.content should "
                        f"be a string, instead was 'undefined'.",
                    )

        # --- Business validation ---
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        req = conn.execute(
            "SELECT resident_id, request_type, status FROM service_requests "
            "WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if req is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find service request with ID: {request_id}.",
            )
        if req["request_type"] != "missed_pickup" or req["status"] != "pending_review":
            conn.close()
            return _error(
                400, "validation_error",
                f"Service request '{request_id}' is not a pending missed-pickup "
                f"complaint (type='{req['request_type']}', status='{req['status']}').",
            )
        if req["resident_id"] != resident_id:
            conn.close()
            return _error(
                400, "validation_error",
                f"Service request '{request_id}' does not belong to resident "
                f"account '{resident_id}'.",
            )
        self._ensure_memo_table(conn)
        dup = conn.execute(
            "SELECT 1 FROM credit_memos WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if dup is not None:
            conn.close()
            return _error(
                400, "validation_error",
                f"A credit memo has already been recorded for request '{request_id}'.",
            )

        # --- Perform write ---
        credit_amount = round(float(credit), 2)
        memo_id = "cm_" + hashlib.md5(
            f"{request_id}:{resident_id}".encode()
        ).hexdigest()[:10]
        conn.execute(
            "INSERT INTO credit_memos "
            "(memo_id, request_id, resident_id, miss_type, credit_amount) "
            "VALUES (?, ?, ?, ?, ?)",
            (memo_id, request_id, resident_id, miss_type, credit_amount),
        )
        conn.commit()
        conn.close()

        # Success response: deep echo, shape entirely different from errors.
        return {
            "object": "credit_memo",
            "id": memo_id,
            "parent": {"type": "resident_account", "resident_id": resident_id},
            "properties": {
                "Request": {"type": "reference",
                            "reference": {"request_id": request_id}},
                "MissType": {"type": "select", "select": {"name": miss_type}},
                "Credit": {"type": "number", "number": credit_amount},
            },
            "created": True,
        }

    # ===================================================================
    # STEP  –  evaluation
    # ===================================================================

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's
        final response.
        """
        info: Dict[str, Any] = {"eval_criteria": {}}
        total_score = 0
        max_score = 0

        # ---- compute ground truth -----------------------------------
        gt_refunds = self._compute_ground_truth()

        # Criterion 1: refund_list.csv exists (10 pts)
        max_score += 10
        csv_path = os.path.join(self.workspace, "refund_list.csv")
        csv_exists = os.path.isfile(csv_path)
        info["eval_criteria"]["csv_exists"] = {
            "passed": csv_exists,
            "score": 10 if csv_exists else 0,
            "max_score": 10,
        }
        total_score += 10 if csv_exists else 0

        # Criterion 2: correct columns in CSV (10 pts)
        expected_cols = [
            "request_id", "resident_id", "resident_name", "zone_id",
            "service_tier", "scheduled_pickup_date", "miss_type",
            "base_credit", "final_credit",
        ]
        parsed_rows = []
        cols_ok = False
        if csv_exists:
            try:
                with open(csv_path, "r") as f:
                    reader = csv.DictReader(f)
                    actual_cols = [c.strip() for c in reader.fieldnames] if reader.fieldnames else []
                    cols_ok = actual_cols == expected_cols
                    for row in reader:
                        parsed_rows.append({k.strip(): v.strip() for k, v in row.items()})
            except Exception:
                pass
        max_score += 10
        info["eval_criteria"]["csv_columns"] = {
            "passed": cols_ok,
            "score": 10 if cols_ok else 0,
            "max_score": 10,
        }
        total_score += 10 if cols_ok else 0

        # Criterion 3: correct set of request_ids (25 pts)
        gt_ids = set(r["request_id"] for r in gt_refunds)
        agent_ids = set(r.get("request_id", "") for r in parsed_rows)
        ids_match = gt_ids == agent_ids
        # Partial: Jaccard similarity
        if gt_ids or agent_ids:
            jaccard = len(gt_ids & agent_ids) / len(gt_ids | agent_ids)
        else:
            jaccard = 1.0 if not gt_ids else 0.0
        id_score = round(25 * jaccard)
        max_score += 25
        info["eval_criteria"]["correct_request_ids"] = {
            "passed": ids_match,
            "score": id_score,
            "max_score": 25,
            "reason": "" if ids_match else f"expected {len(gt_ids)} refunds, got {len(agent_ids)}; overlap={len(gt_ids & agent_ids)}",
        }
        total_score += id_score

        # Criterion 4: correct miss_type for each matching request (15 pts)
        gt_map = {r["request_id"]: r for r in gt_refunds}
        agent_map = {r.get("request_id", ""): r for r in parsed_rows}
        common_ids = gt_ids & agent_ids
        type_correct = 0
        for rid in common_ids:
            if agent_map[rid].get("miss_type", "") == gt_map[rid]["miss_type"]:
                type_correct += 1
        type_ratio = type_correct / len(common_ids) if common_ids else (1.0 if not gt_ids else 0.0)
        type_score = round(15 * type_ratio)
        max_score += 15
        info["eval_criteria"]["correct_miss_types"] = {
            "passed": type_ratio == 1.0,
            "score": type_score,
            "max_score": 15,
            "reason": "" if type_ratio == 1.0 else f"{type_correct}/{len(common_ids)} correct",
        }
        total_score += type_score

        # Criterion 5: correct final_credit values (20 pts)
        credit_correct = 0
        for rid in common_ids:
            try:
                agent_credit = float(agent_map[rid].get("final_credit", -1))
            except (ValueError, TypeError):
                agent_credit = -1
            gt_credit = float(gt_map[rid]["final_credit"])
            if abs(agent_credit - gt_credit) < 0.01:
                credit_correct += 1
        credit_ratio = credit_correct / len(common_ids) if common_ids else (1.0 if not gt_ids else 0.0)
        credit_score = round(20 * credit_ratio)
        max_score += 20
        info["eval_criteria"]["correct_credits"] = {
            "passed": credit_ratio == 1.0,
            "score": credit_score,
            "max_score": 20,
            "reason": "" if credit_ratio == 1.0 else f"{credit_correct}/{len(common_ids)} correct",
        }
        total_score += credit_score

        # Criterion 6: sort order (10 pts)
        sorted_ok = False
        if parsed_rows:
            agent_id_list = [r.get("request_id", "") for r in parsed_rows]
            sorted_ok = agent_id_list == sorted(agent_id_list)
        max_score += 10
        info["eval_criteria"]["sort_order"] = {
            "passed": sorted_ok,
            "score": 10 if sorted_ok else 0,
            "max_score": 10,
        }
        total_score += 10 if sorted_ok else 0

        # Criterion 7: action string contains total count and total credit (10 pts)
        gt_total_credit = sum(float(r["final_credit"]) for r in gt_refunds)
        gt_count = len(gt_refunds)
        count_in_action = str(gt_count) in action
        credit_str = f"{gt_total_credit:.2f}"
        credit_in_action = credit_str in action
        summary_ok = count_in_action and credit_in_action
        summary_score = 0
        if count_in_action:
            summary_score += 5
        if credit_in_action:
            summary_score += 5
        max_score += 10
        info["eval_criteria"]["action_summary"] = {
            "passed": summary_ok,
            "score": summary_score,
            "max_score": 10,
            "reason": "" if summary_ok else f"expected count={gt_count}, credit={credit_str}",
        }
        total_score += summary_score

        # Criterion 8: credit memos recorded in the DB via create_credit_memo (10 pts)
        db_memos: Dict[str, Dict[str, Any]] = {}
        try:
            conn = sqlite3.connect(self.db_path)
            for row in conn.execute(
                "SELECT request_id, resident_id, miss_type, credit_amount "
                "FROM credit_memos"
            ).fetchall():
                db_memos[row[0]] = {
                    "resident_id": row[1],
                    "miss_type": row[2],
                    "credit_amount": row[3],
                }
            conn.close()
        except sqlite3.OperationalError:
            pass  # table never created -> no memos recorded
        memo_ok = 0
        for r in gt_refunds:
            m = db_memos.get(r["request_id"])
            if (
                m is not None
                and m["resident_id"] == r["resident_id"]
                and m["miss_type"] == r["miss_type"]
                and abs(float(m["credit_amount"]) - float(r["final_credit"])) < 0.01
            ):
                memo_ok += 1
        memo_ratio = memo_ok / len(gt_refunds) if gt_refunds else 1.0
        memo_score = round(10 * memo_ratio)
        max_score += 10
        info["eval_criteria"]["db_credits_recorded"] = {
            "passed": memo_ratio == 1.0,
            "score": memo_score,
            "max_score": 10,
            "reason": "" if memo_ratio == 1.0 else f"{memo_ok}/{len(gt_refunds)} memos recorded correctly",
        }
        total_score += memo_score

        info["total_score"] = total_score
        info["max_score"] = max_score
        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, info

    # ===================================================================
    # Ground-truth computation (used by step and verify)
    # ===================================================================

    def _compute_ground_truth(self) -> List[Dict[str, Any]]:
        """Derive the correct refund list from DB + workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load workspace config files
        with open(os.path.join(self.workspace, "sla_terms.yaml"), "r") as f:
            sla = yaml.safe_load(f)

        comp_rates = {}
        with open(os.path.join(self.workspace, "compensation_rates.csv"), "r") as f:
            for row in csv.DictReader(f):
                comp_rates[row["service_tier"]] = {
                    "base_credit": float(row["base_credit"]),
                    "partial_miss_rate": float(row["partial_miss_rate"]),
                    "full_miss_rate": float(row["full_miss_rate"]),
                    "repeat_miss_multiplier": float(row["repeat_miss_multiplier"]),
                }

        with open(os.path.join(self.workspace, "zone_boundaries.json"), "r") as f:
            zones = json.load(f)

        # Load all route logs to find excused zone-dates
        excused = set()  # (zone_id, date_str)
        for fname in os.listdir(self.workspace):
            if fname.startswith("route_log_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    for row in csv.DictReader(f):
                        exc_code = row.get("exception_code", "none")
                        adv = row.get("advance_notice", "false").lower() == "true"
                        if exc_code in sla["general"]["excused_exception_codes"] and adv:
                            excused.add((row["zone_id"], row["date"]))

        # Get all pending missed_pickup requests
        pending = conn.execute(
            "SELECT * FROM service_requests "
            "WHERE request_type = 'missed_pickup' AND status = 'pending_review' "
            "ORDER BY request_id"
        ).fetchall()

        refunds = []
        for req in pending:
            req = dict(req)
            rid = req["resident_id"]
            sched_date = req["scheduled_pickup_date"]

            # Get resident info
            res = dict(conn.execute(
                "SELECT * FROM residents WHERE resident_id = ?", (rid,)
            ).fetchone())

            zone_id = res["zone_id"]
            tier = res["service_tier"]

            # Check if scheduled day matches zone pickup days
            from datetime import datetime as _dt
            sched_dt = _dt.strptime(sched_date, "%Y-%m-%d")
            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                         "Friday", "Saturday", "Sunday"]
            sched_day = day_names[sched_dt.weekday()]
            if sched_day not in zones[zone_id]["pickup_days"]:
                continue  # not a valid pickup day for this zone

            # Check excused
            if (zone_id, sched_date) in excused:
                continue

            # Get truck for this zone
            truck_id = zones[zone_id]["assigned_truck"]

            # Get SLA thresholds
            tier_sla = sla["service_tiers"][tier]
            prox_thresh = tier_sla["proximity_threshold_m"]
            min_dur = tier_sla["min_stop_duration_sec"]

            # Check GPS stops
            gps_rows = conn.execute(
                "SELECT latitude, longitude, stop_duration_sec "
                "FROM gps_stops WHERE truck_id = ? AND stop_time LIKE ?",
                (truck_id, sched_date + "%"),
            ).fetchall()

            has_valid_stop = False
            for g in gps_rows:
                dist = _haversine_m(res["latitude"], res["longitude"],
                                    g["latitude"], g["longitude"])
                if dist <= prox_thresh and g["stop_duration_sec"] >= min_dur:
                    has_valid_stop = True
                    break

            # Check bin lifts
            lifts = conn.execute(
                "SELECT lift_successful FROM bin_lifts "
                "WHERE bin_id = ? AND lift_time LIKE ?",
                (res["bin_id"], sched_date + "%"),
            ).fetchall()
            has_successful_lift = any(l["lift_successful"] for l in lifts)

            # Determine miss type
            if has_valid_stop and has_successful_lift:
                continue  # not a valid miss
            elif has_valid_stop and not has_successful_lift:
                miss_type = "partial_miss"
            else:
                # No valid GPS stop (or no stop at all)
                if has_successful_lift:
                    # Unusual: bin was lifted but no GPS stop recorded near address
                    # Treat as not a valid miss since service was provided
                    continue
                miss_type = "full_miss"

            # Credit calculation
            rates = comp_rates[tier]
            base_credit = rates["base_credit"]
            if miss_type == "full_miss":
                credit = base_credit * rates["full_miss_rate"]
            else:
                credit = base_credit * rates["partial_miss_rate"]

            # Check repeat miss
            from datetime import timedelta as _td
            window_start = (sched_dt - _td(days=30)).strftime("%Y-%m-%d")
            prior = conn.execute(
                "SELECT COUNT(*) FROM service_requests "
                "WHERE resident_id = ? AND request_type = 'missed_pickup' "
                "AND status = 'resolved' "
                "AND scheduled_pickup_date >= ? AND scheduled_pickup_date < ?",
                (rid, window_start, sched_date),
            ).fetchone()[0]
            if prior > 0:
                credit *= rates["repeat_miss_multiplier"]

            final_credit = round(credit, 2)

            refunds.append({
                "request_id": req["request_id"],
                "resident_id": rid,
                "resident_name": res["name"],
                "zone_id": zone_id,
                "service_tier": tier,
                "scheduled_pickup_date": sched_date,
                "miss_type": miss_type,
                "base_credit": f"{base_credit:.2f}",
                "final_credit": f"{final_credit:.2f}",
            })

        conn.close()
        refunds.sort(key=lambda r: r["request_id"])
        return refunds

    # ===================================================================
    # VERIFY
    # ===================================================================

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.

        Note: the hardened tool surface requires a JSON-encoded string filter
        for search_service_requests and nested request payloads for
        create_credit_memo.
        """
        import os as _os
        from datetime import datetime as _dt, timedelta as _td

        tool_call_count = 0

        def _call(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # 1. Read workspace config files
        with open(_os.path.join(self.workspace, "sla_terms.yaml"), "r") as f:
            sla = yaml.safe_load(f)

        comp_rates = {}
        with open(_os.path.join(self.workspace, "compensation_rates.csv"), "r") as f:
            for row in csv.DictReader(f):
                comp_rates[row["service_tier"]] = {
                    "base_credit": float(row["base_credit"]),
                    "partial_miss_rate": float(row["partial_miss_rate"]),
                    "full_miss_rate": float(row["full_miss_rate"]),
                    "repeat_miss_multiplier": float(row["repeat_miss_multiplier"]),
                }

        with open(_os.path.join(self.workspace, "zone_boundaries.json"), "r") as f:
            zones = json.load(f)

        # Read all route logs for excused dates
        excused = set()
        for fname in _os.listdir(self.workspace):
            if fname.startswith("route_log_") and fname.endswith(".csv"):
                with open(_os.path.join(self.workspace, fname), "r") as f:
                    for row in csv.DictReader(f):
                        exc_code = row.get("exception_code", "none")
                        adv = row.get("advance_notice", "false").lower() == "true"
                        if exc_code in sla["general"]["excused_exception_codes"] and adv:
                            excused.add((row["zone_id"], row["date"]))

        # Read compensation policy (the agent would need to read this)
        with open(_os.path.join(self.workspace, "compensation_policy.md"), "r") as f:
            _ = f.read()

        # 2. Search for pending missed_pickup requests
        #    (JSON-encoded string filter, paginated)
        filter_str = json.dumps(
            {"request_type": "missed_pickup", "status": "pending_review"}
        )
        all_pending = []
        page = 1
        while True:
            result = _call(
                "search_service_requests",
                filter=filter_str, page=page, page_size=20,
            )
            all_pending.extend(result["results"])
            if page * result["page_size"] >= result["total"]:
                break
            page += 1

        # 3. For each pending request, gather data and determine compensation
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                     "Friday", "Saturday", "Sunday"]

        refunds = []
        for req_summary in all_pending:
            req_id = req_summary["request_id"]
            resident_id = req_summary["resident_id"]
            sched_date = req_summary["scheduled_pickup_date"]

            # Get resident info
            res = _call("get_resident_info", resident_id=resident_id)

            zone_id = res["zone_id"]
            tier = res["service_tier"]

            # Check pickup day
            sched_dt = _dt.strptime(sched_date, "%Y-%m-%d")
            sched_day = day_names[sched_dt.weekday()]
            if sched_day not in zones[zone_id]["pickup_days"]:
                continue

            # Check excused
            if (zone_id, sched_date) in excused:
                continue

            # Get truck for this zone
            truck_id = zones[zone_id]["assigned_truck"]

            # SLA thresholds
            tier_sla = sla["service_tiers"][tier]
            prox_thresh = tier_sla["proximity_threshold_m"]
            min_dur = tier_sla["min_stop_duration_sec"]

            # Query GPS stops
            gps_result = _call(
                "query_gps_stops", truck_id=truck_id, date=sched_date,
            )

            has_valid_stop = False
            for stop in gps_result["stops"]:
                dist = _haversine_m(
                    res["latitude"], res["longitude"],
                    stop["latitude"], stop["longitude"],
                )
                if dist <= prox_thresh and stop["stop_duration_sec"] >= min_dur:
                    has_valid_stop = True
                    break

            # Query bin lifts
            lift_result = _call(
                "query_bin_lifts", bin_id=res["bin_id"], date=sched_date,
            )
            has_successful_lift = any(
                l["lift_successful"] for l in lift_result["lifts"]
            )

            # Determine miss type
            if has_valid_stop and has_successful_lift:
                continue  # not a miss
            elif has_valid_stop and not has_successful_lift:
                miss_type = "partial_miss"
            else:
                if has_successful_lift:
                    continue  # service was provided
                miss_type = "full_miss"

            # Credit calculation
            rates = comp_rates[tier]
            base_credit = rates["base_credit"]
            if miss_type == "full_miss":
                credit = base_credit * rates["full_miss_rate"]
            else:
                credit = base_credit * rates["partial_miss_rate"]

            # Check repeat miss
            window_start = (sched_dt - _td(days=30)).strftime("%Y-%m-%d")
            prior = _call(
                "check_prior_claims",
                resident_id=resident_id,
                start_date=window_start,
                end_date=sched_date,
            )
            if prior["count"] > 0:
                credit *= rates["repeat_miss_multiplier"]

            final_credit = round(credit, 2)

            refunds.append({
                "request_id": req_id,
                "resident_id": resident_id,
                "resident_name": res["name"],
                "zone_id": zone_id,
                "service_tier": tier,
                "scheduled_pickup_date": sched_date,
                "miss_type": miss_type,
                "base_credit": f"{base_credit:.2f}",
                "final_credit": f"{final_credit:.2f}",
            })

        refunds.sort(key=lambda r: r["request_id"])

        # 4. Record each approved credit via nested create_credit_memo payloads
        for r in refunds:
            result = _call(
                "create_credit_memo",
                payload={
                    "parent": {
                        "type": "resident_account",
                        "resident_id": r["resident_id"],
                    },
                    "properties": {
                        "Request": {
                            "type": "reference",
                            "reference": {"request_id": r["request_id"]},
                        },
                        "MissType": {
                            "type": "select",
                            "select": {"name": r["miss_type"]},
                        },
                        "Credit": {
                            "type": "number",
                            "number": float(r["final_credit"]),
                        },
                    },
                },
            )
            assert result.get("object") == "credit_memo" and result.get("created"), (
                f"create_credit_memo failed for {r['request_id']}: {result}"
            )

        # 5. Write refund_list.csv
        csv_path = _os.path.join(self.workspace, "refund_list.csv")
        fieldnames = [
            "request_id", "resident_id", "resident_name", "zone_id",
            "service_tier", "scheduled_pickup_date", "miss_type",
            "base_credit", "final_credit",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(refunds)

        # 6. Build action string
        total_credit = sum(float(r["final_credit"]) for r in refunds)
        action = (
            f"Validated {len(refunds)} missed pickup refund entries and "
            f"recorded a credit memo for each. "
            f"Total credit amount: {total_credit:.2f}. "
            f"Results saved to refund_list.csv."
        )

        assert tool_call_count >= 15, (
            f"Tool call count {tool_call_count} < 15 minimum"
        )
        print(f"[verify] total tool calls: {tool_call_count}")

        return self.step(action)
