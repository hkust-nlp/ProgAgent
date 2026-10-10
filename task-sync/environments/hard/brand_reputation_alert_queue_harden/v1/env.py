"""
Brand reputation monitoring – task environment (hardened tool surface).

Hardened surface (M0 + M1 + M4):
  - M0: prompt.md is de-proceduralized; the signal formulas and combination
    procedure now live in the workspace document alert_methodology.md.
  - M1: search_headlines and get_support_tickets take a single JSON-encoded
    string `filter` parameter; malformed JSON, wrong-typed values, and
    unsupported keys produce recoverable API-style errors.
  - M4: the brand_risk_summary.json deliverable is converted into a write
    API: file_alert(payload) takes a deeply nested request body
    (parent + properties) validated layer by layer with Notion-style error
    messages, and records each alert in the reputation_alerts DB table.
Task semantics, data generation, ground truth, and criterion weights are
unchanged from the base environment (criterion 6 now checks DB state
instead of brand_risk_summary.json, same 10 points).
"""

from typing import Tuple, Dict, List, Any
import sqlite3
import os
import ast
import hashlib
import json
import csv
import yaml
import re


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


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


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
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description="Lists brands under monitoring, paginated. Returns brand_id, brand_name, industry, and region for each brand.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (default 20, max 50)",
                },
            },
            "required": ["page"],
        },
    )
    def list_brands(self, page: int = 1, page_size: int = 20):
        if not _is_int(page) or page < 1:
            return _error(400, "validation_error",
                          f"body.page should be a positive integer, instead was {_shape(page)}.")
        if not _is_int(page_size) or page_size < 1:
            return _error(400, "validation_error",
                          f"body.page_size should be a positive integer, instead was {_shape(page_size)}.")
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        total = c.execute("SELECT COUNT(*) FROM brands").fetchone()[0]
        rows = c.execute(
            "SELECT id, name, industry, region FROM brands ORDER BY id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        brands = [
            {"brand_id": r[0], "brand_name": r[1], "industry": r[2], "region": r[3]}
            for r in rows
        ]
        return {"brands": brands, "page": page, "page_size": page_size,
                "total": total, "has_more": offset + page_size < total}

    @tool(
        description="Retrieves full details for a single brand by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "brand_id": {"type": "integer", "description": "The brand identifier"},
            },
            "required": ["brand_id"],
        },
    )
    def get_brand_details(self, brand_id: Any = None):
        if not _is_int(brand_id):
            return _error(400, "validation_error",
                          f"body.brand_id should be an integer, instead was {_shape(brand_id)}.")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        row = c.execute(
            "SELECT id, name, industry, region, stock_ticker, employee_count FROM brands WHERE id=?",
            (brand_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find brand with ID: {brand_id}.")
        return {"brand_id": row[0], "brand_name": row[1], "industry": row[2],
                "region": row[3], "stock_ticker": row[4], "employee_count": row[5]}

    @tool(
        description="Returns daily social-media metrics (mention_count, engagement_score) for a brand across all tracked platforms and dates.",
        parameters={
            "type": "object",
            "properties": {
                "brand_id": {"type": "integer", "description": "The brand identifier"},
            },
            "required": ["brand_id"],
        },
    )
    def get_social_media_metrics(self, brand_id: Any = None):
        if not _is_int(brand_id):
            return _error(400, "validation_error",
                          f"body.brand_id should be an integer, instead was {_shape(brand_id)}.")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        exists = c.execute("SELECT 1 FROM brands WHERE id=?", (brand_id,)).fetchone()
        if exists is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find brand with ID: {brand_id}.")
        rows = c.execute(
            "SELECT date, platform, mention_count, engagement_score "
            "FROM social_media_metrics WHERE brand_id=? ORDER BY date, platform",
            (brand_id,),
        ).fetchall()
        conn.close()
        metrics = [
            {"date": r[0], "platform": r[1], "mention_count": r[2], "engagement_score": r[3]}
            for r in rows
        ]
        return {"brand_id": brand_id, "metrics": metrics}

    @tool(
        description=(
            "Searches news headlines from the monitoring period, paginated. "
            "Filtering is expressed as a JSON-encoded string, e.g. "
            "filter='{\"brand_id\": 7, \"category\": \"legal\"}'. Supported filter "
            "properties: brand_id (integer, required), category (one of product | "
            "legal | financial | executive | regulatory | partnership), and source "
            "(string). Each result entry contains headline_id, headline, source, "
            "published_date, and category."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"brand_id\": 7, \"source\": \"Reuters\"}'. The brand_id "
                        "property is required; category and source are optional."
                    ),
                },
                "page": {"type": "integer", "description": "Page number (1-indexed, default 1)"},
                "page_size": {"type": "integer", "description": "Results per page (default 20, max 50)"},
            },
            "required": ["filter"],
        },
    )
    def search_headlines(self, filter: Any = None, page: int = 1, page_size: int = 20):
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"brand_id", "category", "source"}
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: brand_id, category, source.")

        brand_id = parsed.get("brand_id")
        if brand_id is None:
            return _error(400, "validation_error",
                "body.filter.brand_id should be defined, instead was 'undefined'.")
        if not _is_int(brand_id):
            return _error(400, "validation_error",
                f"body.filter.brand_id should be an integer, instead was {_shape(brand_id)}.")

        clauses = ["brand_id=?"]
        params: list = [brand_id]
        if "category" in parsed:
            category = parsed["category"]
            valid_cats = ("product", "legal", "financial", "executive", "regulatory", "partnership")
            if not isinstance(category, str) or category not in valid_cats:
                return _error(400, "validation_error",
                    f"body.filter.category should be one of \"product\", \"legal\", "
                    f"\"financial\", \"executive\", \"regulatory\", \"partnership\", "
                    f"instead was {_shape(category)}.")
            clauses.append("category=?")
            params.append(category)
        if "source" in parsed:
            source = parsed["source"]
            if not isinstance(source, str) or not source:
                return _error(400, "validation_error",
                    f"body.filter.source should be a non-empty string, instead was {_shape(source)}.")
            clauses.append("source=?")
            params.append(source)

        if not _is_int(page) or page < 1:
            return _error(400, "validation_error",
                          f"body.page should be a positive integer, instead was {_shape(page)}.")
        if not _is_int(page_size) or page_size < 1:
            return _error(400, "validation_error",
                          f"body.page_size should be a positive integer, instead was {_shape(page_size)}.")
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        where = " AND ".join(clauses)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        total = c.execute(f"SELECT COUNT(*) FROM news_headlines WHERE {where}", params).fetchone()[0]
        rows = c.execute(
            f"SELECT id, headline, source, published_date, category "
            f"FROM news_headlines WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        conn.close()
        headlines = [
            {"headline_id": r[0], "headline": r[1], "source": r[2],
             "published_date": r[3], "category": r[4]}
            for r in rows
        ]
        return {"brand_id": brand_id, "headlines": headlines,
                "page": page, "total": total, "has_more": offset + page_size < total}

    @tool(
        description=(
            "Lists support tickets, paginated. Filtering is expressed as a "
            "JSON-encoded string, e.g. filter='{\"brand_id\": 3, \"status\": "
            "\"open\"}'. Supported filter properties: brand_id (integer, "
            "required), status (one of open | in_progress | resolved | "
            "escalated), and customer_tier (one of enterprise | business | "
            "individual). Each result entry contains ticket_id, subject, "
            "category, created_date, status, and customer_tier (body text is "
            "not included; use get_ticket_content for full text)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"brand_id\": 3, \"customer_tier\": \"enterprise\"}'. The "
                        "brand_id property is required; status and customer_tier are optional."
                    ),
                },
                "page": {"type": "integer", "description": "Page number (1-indexed, default 1)"},
                "page_size": {"type": "integer", "description": "Results per page (default 20, max 50)"},
            },
            "required": ["filter"],
        },
    )
    def get_support_tickets(self, filter: Any = None, page: int = 1, page_size: int = 20):
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"brand_id", "status", "customer_tier"}
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: brand_id, status, customer_tier.")

        brand_id = parsed.get("brand_id")
        if brand_id is None:
            return _error(400, "validation_error",
                "body.filter.brand_id should be defined, instead was 'undefined'.")
        if not _is_int(brand_id):
            return _error(400, "validation_error",
                f"body.filter.brand_id should be an integer, instead was {_shape(brand_id)}.")

        clauses = ["brand_id=?"]
        params: list = [brand_id]
        if "status" in parsed:
            status = parsed["status"]
            valid_statuses = ("open", "in_progress", "resolved", "escalated")
            if not isinstance(status, str) or status not in valid_statuses:
                return _error(400, "validation_error",
                    f"body.filter.status should be one of \"open\", \"in_progress\", "
                    f"\"resolved\", \"escalated\", instead was {_shape(status)}.")
            clauses.append("status=?")
            params.append(status)
        if "customer_tier" in parsed:
            tier = parsed["customer_tier"]
            valid_tiers = ("enterprise", "business", "individual")
            if not isinstance(tier, str) or tier not in valid_tiers:
                return _error(400, "validation_error",
                    f"body.filter.customer_tier should be one of \"enterprise\", "
                    f"\"business\", \"individual\", instead was {_shape(tier)}.")
            clauses.append("customer_tier=?")
            params.append(tier)

        if not _is_int(page) or page < 1:
            return _error(400, "validation_error",
                          f"body.page should be a positive integer, instead was {_shape(page)}.")
        if not _is_int(page_size) or page_size < 1:
            return _error(400, "validation_error",
                          f"body.page_size should be a positive integer, instead was {_shape(page_size)}.")
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        where = " AND ".join(clauses)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        total = c.execute(f"SELECT COUNT(*) FROM support_tickets WHERE {where}", params).fetchone()[0]
        rows = c.execute(
            f"SELECT id, subject, category, created_date, status, customer_tier "
            f"FROM support_tickets WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        conn.close()
        tickets = [
            {"ticket_id": r[0], "subject": r[1], "category": r[2],
             "created_date": r[3], "status": r[4], "customer_tier": r[5]}
            for r in rows
        ]
        return {"brand_id": brand_id, "tickets": tickets,
                "page": page, "total": total, "has_more": offset + page_size < total}

    @tool(
        description="Retrieves the full content of a single support ticket, including the body text.",
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {"type": "integer", "description": "The ticket identifier"},
            },
            "required": ["ticket_id"],
        },
    )
    def get_ticket_content(self, ticket_id: Any = None):
        if not _is_int(ticket_id):
            return _error(400, "validation_error",
                          f"body.ticket_id should be an integer, instead was {_shape(ticket_id)}.")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        row = c.execute(
            "SELECT id, brand_id, subject, body, category, created_date, status, customer_tier "
            "FROM support_tickets WHERE id=?",
            (ticket_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find ticket with ID: {ticket_id}.")
        return {"ticket_id": row[0], "brand_id": row[1], "subject": row[2],
                "body": row[3], "category": row[4], "created_date": row[5],
                "status": row[6], "customer_tier": row[7]}

    @tool(
        description="Lists executive communications for a brand, paginated. Returns comm_id, comm_type, title, date, and spokesperson (summary text is not included; use get_comm_content for details).",
        parameters={
            "type": "object",
            "properties": {
                "brand_id": {"type": "integer", "description": "The brand identifier"},
                "page": {"type": "integer", "description": "Page number (1-indexed, default 1)"},
                "page_size": {"type": "integer", "description": "Results per page (default 20, max 50)"},
            },
            "required": ["brand_id"],
        },
    )
    def get_executive_comms(self, brand_id: Any = None, page: int = 1, page_size: int = 20):
        if not _is_int(brand_id):
            return _error(400, "validation_error",
                          f"body.brand_id should be an integer, instead was {_shape(brand_id)}.")
        if not _is_int(page) or page < 1:
            return _error(400, "validation_error",
                          f"body.page should be a positive integer, instead was {_shape(page)}.")
        if not _is_int(page_size) or page_size < 1:
            return _error(400, "validation_error",
                          f"body.page_size should be a positive integer, instead was {_shape(page_size)}.")
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        total = c.execute(
            "SELECT COUNT(*) FROM executive_communications WHERE brand_id=?", (brand_id,),
        ).fetchone()[0]
        rows = c.execute(
            "SELECT id, comm_type, title, date, spokesperson "
            "FROM executive_communications WHERE brand_id=? ORDER BY id LIMIT ? OFFSET ?",
            (brand_id, page_size, offset),
        ).fetchall()
        conn.close()
        comms = [
            {"comm_id": r[0], "comm_type": r[1], "title": r[2],
             "date": r[3], "spokesperson": r[4]}
            for r in rows
        ]
        return {"brand_id": brand_id, "communications": comms,
                "page": page, "total": total, "has_more": offset + page_size < total}

    @tool(
        description="Retrieves the full content of a single executive communication, including the summary text.",
        parameters={
            "type": "object",
            "properties": {
                "comm_id": {"type": "integer", "description": "The communication identifier"},
            },
            "required": ["comm_id"],
        },
    )
    def get_comm_content(self, comm_id: Any = None):
        if not _is_int(comm_id):
            return _error(400, "validation_error",
                          f"body.comm_id should be an integer, instead was {_shape(comm_id)}.")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        row = c.execute(
            "SELECT id, brand_id, comm_type, title, summary, date, spokesperson "
            "FROM executive_communications WHERE id=?",
            (comm_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find communication with ID: {comm_id}.")
        return {"comm_id": row[0], "brand_id": row[1], "comm_type": row[2],
                "title": row[3], "summary": row[4], "date": row[5],
                "spokesperson": row[6]}

    @tool(
        description=(
            "Files a reputation alert into the central alert queue of the "
            "monitoring platform. The request body must contain a `parent` "
            "object identifying the receiving alert queue and a `properties` "
            "object with a `Brand` reference property and a `Severity` number "
            "property. Example body: "
            "{\"parent\": {\"type\": \"alert_queue\", \"queue_id\": "
            "\"reputation-alerts\"}, \"properties\": {\"Brand\": {\"type\": "
            "\"reference\", \"reference\": {\"brand_id\": 7}}, \"Severity\": "
            "{\"type\": \"number\", \"number\": 23.5}}}. An optional `Note` "
            "rich_text property may be included in `properties`. Filing again "
            "for the same brand replaces the previously filed severity."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "The alert filing request body.",
                    "properties": {
                        "parent": {
                            "type": "object",
                            "description": (
                                "The alert queue that receives the alert. Must "
                                "contain type='alert_queue' and a queue_id string."
                            ),
                            "properties": {
                                "type": {"type": "string"},
                                "queue_id": {"type": "string"},
                            },
                            "required": ["type", "queue_id"],
                            "additionalProperties": True,
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Alert properties. Must include a 'Brand' "
                                "reference property and a 'Severity' number "
                                "property. May include a 'Note' rich_text property."
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
    def file_alert(self, payload: Any = None) -> dict:
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
        if parent.get("type") != "alert_queue":
            return _error(400, "validation_error",
                          f"body.parent.type should be \"alert_queue\", instead was "
                          f"{_shape(parent.get('type'))}.")
        queue_id = parent.get("queue_id")
        if not isinstance(queue_id, str) or not queue_id:
            return _error(400, "validation_error",
                          f"body.parent.queue_id should be a non-empty string, instead was "
                          f"{_shape(queue_id)}.")

        props = payload.get("properties")
        if props is None:
            return _error(400, "validation_error",
                          "body.properties should be defined, instead was 'undefined'.")
        if not isinstance(props, dict):
            return _error(400, "validation_error",
                          f"body.properties should be an object, instead was {_shape(props)}.")

        brand_prop = props.get("Brand")
        if brand_prop is None:
            return _error(400, "validation_error",
                          "body.properties.Brand should be defined, instead was 'undefined'.")
        if not isinstance(brand_prop, dict):
            return _error(400, "validation_error",
                          f"body.properties.Brand should be an object, instead was "
                          f"{_shape(brand_prop)}.")
        if brand_prop.get("type") != "reference":
            return _error(400, "validation_error",
                          f"body.properties.Brand.type should be \"reference\", instead was "
                          f"{_shape(brand_prop.get('type'))}.")
        reference = brand_prop.get("reference")
        if not isinstance(reference, dict):
            return _error(400, "validation_error",
                          f"body.properties.Brand.reference should be an object, instead was "
                          f"{_shape(reference)}.")
        brand_id = reference.get("brand_id")
        if not _is_int(brand_id):
            return _error(400, "validation_error",
                          f"body.properties.Brand.reference.brand_id should be an integer, "
                          f"instead was {_shape(brand_id)}.")

        severity_prop = props.get("Severity")
        if severity_prop is None:
            return _error(400, "validation_error",
                          "body.properties.Severity should be defined, instead was 'undefined'.")
        if not isinstance(severity_prop, dict):
            return _error(400, "validation_error",
                          f"body.properties.Severity should be an object, instead was "
                          f"{_shape(severity_prop)}.")
        if severity_prop.get("type") != "number":
            return _error(400, "validation_error",
                          f"body.properties.Severity.type should be \"number\", instead was "
                          f"{_shape(severity_prop.get('type'))}.")
        severity = severity_prop.get("number")
        if isinstance(severity, bool) or not isinstance(severity, (int, float)):
            return _error(400, "validation_error",
                          f"body.properties.Severity.number should be a number, instead was "
                          f"{_shape(severity)}.")

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
        if queue_id != "reputation-alerts":
            return _error(404, "object_not_found",
                          f"Could not find alert queue with ID: {queue_id}.")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        exists = c.execute("SELECT 1 FROM brands WHERE id=?", (brand_id,)).fetchone()
        if exists is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find brand with ID: {brand_id}.")

        # --- Record the alert (upsert keyed by brand) ---
        c.execute(
            "CREATE TABLE IF NOT EXISTS reputation_alerts ("
            "brand_id INTEGER PRIMARY KEY, severity_score REAL NOT NULL)"
        )
        c.execute(
            "INSERT INTO reputation_alerts (brand_id, severity_score) VALUES (?, ?) "
            "ON CONFLICT(brand_id) DO UPDATE SET severity_score=excluded.severity_score",
            (brand_id, float(severity)),
        )
        conn.commit()
        conn.close()

        # Success response: deep echo, shape entirely different from errors.
        return {
            "object": "alert",
            "id": "alr_" + hashlib.md5(f"{brand_id}:{severity}".encode()).hexdigest()[:10],
            "parent": {"type": "alert_queue", "queue_id": "reputation-alerts"},
            "properties": {
                "Brand": {"type": "reference", "reference": {"brand_id": brand_id}},
                "Severity": {"type": "number", "number": float(severity)},
                "Status": {"type": "select", "select": {"name": "filed"}},
            },
            "created": True,
        }

    # ------------------------------------------------------------------
    # Internal helpers for ground-truth computation
    # ------------------------------------------------------------------

    def _read_workspace_configs(self):
        """Read all workspace configuration and data files, return structured dicts."""
        ws = self.workspace

        with open(os.path.join(ws, "anomaly_config.yaml")) as f:
            anomaly_config = yaml.safe_load(f)
        with open(os.path.join(ws, "sentiment_rules.json")) as f:
            sentiment_rules = json.load(f)
        with open(os.path.join(ws, "priority_matrix.json")) as f:
            priority_matrix = json.load(f)

        # Brand tiers
        brand_tiers = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("brand_tier_") and fname.endswith(".csv"):
                with open(os.path.join(ws, fname), newline="") as f:
                    for row in csv.DictReader(f):
                        brand_tiers[int(row["brand_id"])] = row["monitoring_tier"]

        # Social baselines
        baselines = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("social_baseline_") and fname.endswith(".json"):
                with open(os.path.join(ws, fname)) as f:
                    data = json.load(f)
                    for bid_str, stats in data.items():
                        baselines[int(bid_str)] = stats

        # Ticket severity overrides
        ticket_overrides = {}
        block_pattern = re.compile(
            r"=== Brand:[^=]*?\(ID:\s*(\d+)\s*\)\s*===\s*(.*?)(?=(?:\n=== Brand:)|\Z)",
            re.DOTALL,
        )
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("ticket_notes_") and fname.endswith(".txt"):
                with open(os.path.join(ws, fname)) as f:
                    content = f.read()
                for m in block_pattern.finditer(content):
                    bid = int(m.group(1))
                    sev_match = re.search(r"Overall ticket severity:\s*(\w+)", m.group(2))
                    if sev_match:
                        ticket_overrides[bid] = sev_match.group(1)

        # Exec watchlists
        exec_watchlists = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("exec_watchlist_") and fname.endswith(".yaml"):
                with open(os.path.join(ws, fname)) as f:
                    data = yaml.safe_load(f)
                    if data:
                        for entry in data:
                            exec_watchlists[entry["brand_id"]] = entry

        return {
            "anomaly_config": anomaly_config,
            "sentiment_rules": sentiment_rules,
            "priority_matrix": priority_matrix,
            "brand_tiers": brand_tiers,
            "baselines": baselines,
            "ticket_overrides": ticket_overrides,
            "exec_watchlists": exec_watchlists,
        }

    def _compute_ground_truth(self):
        """Compute the expected alert queue from DB + workspace files."""
        cfg = self._read_workspace_configs()
        pm = cfg["priority_matrix"]
        sr = cfg["sentiment_rules"]
        z_threshold = cfg["anomaly_config"]["z_score_threshold"]

        neg_kw = [k.lower() for k in sr["negative_keywords"]]
        crit_kw = [k.lower() for k in sr["critical_keywords"]]
        crisis_kw = [k.lower() for k in sr["crisis_keywords"]]
        weights = pm["weights"]
        scaling = pm["signal_scaling"]
        tier_mults = pm["tier_multipliers"]
        sev_mults = pm["severity_override_multipliers"]
        risk_mults = pm["risk_assessment_multipliers"]

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        brands = c.execute("SELECT id, name FROM brands ORDER BY id").fetchall()

        alerts = []
        for brand_id, brand_name in brands:
            # --- Social anomaly ---
            rows = c.execute(
                "SELECT date, SUM(mention_count) FROM social_media_metrics "
                "WHERE brand_id=? GROUP BY date", (brand_id,),
            ).fetchall()
            daily_vals = [r[1] for r in rows]
            current_avg = sum(daily_vals) / len(daily_vals) if daily_vals else 0
            bl = cfg["baselines"].get(brand_id, {"mean": current_avg, "std": 1.0})
            z_score = (current_avg - bl["mean"]) / bl["std"] if bl["std"] > 0 else 0.0
            anomaly_raw = max(0.0, z_score)

            # --- Headline sentiment ---
            hrows = c.execute(
                "SELECT headline FROM news_headlines WHERE brand_id=?", (brand_id,),
            ).fetchall()
            neg_h, crit_h = 0, 0
            for (h,) in hrows:
                hl = h.lower()
                if any(kw in hl for kw in crit_kw):
                    crit_h += 1
                elif any(kw in hl for kw in neg_kw):
                    neg_h += 1
            headline_raw = (neg_h + 2 * crit_h) / max(1, len(hrows))

            # --- Ticket sentiment ---
            trows = c.execute(
                "SELECT subject, body FROM support_tickets WHERE brand_id=?", (brand_id,),
            ).fetchall()
            neg_t = 0
            for subj, body in trows:
                text = (subj + " " + body).lower()
                if any(kw in text for kw in neg_kw):
                    neg_t += 1
            ticket_base = neg_t / max(1, len(trows))
            override = cfg["ticket_overrides"].get(brand_id, "normal")
            ticket_raw = ticket_base * sev_mults.get(override, 1.0)

            # --- Exec comms risk ---
            erows = c.execute(
                "SELECT spokesperson, summary FROM executive_communications WHERE brand_id=?",
                (brand_id,),
            ).fetchall()
            wl = cfg["exec_watchlists"].get(brand_id, {})
            watched = wl.get("watched_executives", [])
            exec_flag = 0
            for spk, summ in erows:
                if spk in watched and any(kw in summ.lower() for kw in crisis_kw):
                    exec_flag = 1
                    break
            risk_level = wl.get("risk_assessment", "medium")
            exec_raw = exec_flag * risk_mults.get(risk_level, 1.0)

            # --- Combined severity ---
            raw_severity = (
                weights["social_anomaly"] * anomaly_raw * scaling["social_anomaly"]
                + weights["headline_sentiment"] * headline_raw * scaling["headline_sentiment"]
                + weights["ticket_sentiment"] * ticket_raw * scaling["ticket_sentiment"]
                + weights["executive_comms"] * exec_raw * scaling["executive_comms"]
            )
            tier = cfg["brand_tiers"].get(brand_id, "silver")
            severity = round(raw_severity * tier_mults.get(tier, 1.0), 2)

            if severity >= pm["alert_threshold"]:
                alerts.append({
                    "rank": 0,
                    "brand_id": brand_id,
                    "brand_name": brand_name,
                    "monitoring_tier": tier,
                    "severity_score": severity,
                    "social_zscore": round(z_score, 2),
                    "headline_risk": round(headline_raw, 4),
                    "ticket_negativity": round(ticket_raw, 4),
                    "exec_risk_flag": exec_flag,
                })

        conn.close()

        alerts.sort(key=lambda a: (-a["severity_score"], a["brand_id"]))
        for i, a in enumerate(alerts):
            a["rank"] = i + 1

        return alerts

    # ------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------

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
        expected = self._compute_ground_truth()
        expected_ids = {a["brand_id"] for a in expected}
        expected_map = {a["brand_id"]: a for a in expected}

        eval_criteria: Dict[str, Any] = {}

        # --- 1. alert_queue.csv exists with correct columns (10 pts) ---
        csv_path = os.path.join(self.workspace, "alert_queue.csv")
        required_cols = ["rank", "brand_id", "brand_name", "monitoring_tier",
                         "severity_score", "social_zscore", "headline_risk",
                         "ticket_negativity", "exec_risk_flag"]
        actual_alerts = []
        csv_ok = False
        if os.path.isfile(csv_path):
            try:
                with open(csv_path, newline="") as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    if all(c in cols for c in required_cols):
                        csv_ok = True
                        for row in reader:
                            actual_alerts.append(row)
            except Exception:
                pass
        eval_criteria["alert_queue_format"] = {
            "passed": csv_ok,
            "score": 10 if csv_ok else 0,
            "max_score": 10,
            "reason": "" if csv_ok else "alert_queue.csv missing or has wrong columns",
        }

        # Parse actual alerts
        actual_parsed = []
        for row in actual_alerts:
            try:
                actual_parsed.append({
                    "brand_id": int(row["brand_id"]),
                    "brand_name": row["brand_name"].strip(),
                    "severity_score": float(row["severity_score"]),
                    "social_zscore": float(row["social_zscore"]),
                    "headline_risk": float(row["headline_risk"]),
                    "ticket_negativity": float(row["ticket_negativity"]),
                    "exec_risk_flag": int(row["exec_risk_flag"]),
                    "monitoring_tier": row["monitoring_tier"].strip(),
                })
            except (KeyError, ValueError):
                continue
        actual_ids = {a["brand_id"] for a in actual_parsed}
        actual_map = {a["brand_id"]: a for a in actual_parsed}

        # --- 2. Correct brands identified (20 pts) ---
        if expected_ids or actual_ids:
            jaccard = len(expected_ids & actual_ids) / len(expected_ids | actual_ids)
        else:
            jaccard = 1.0
        brand_score = round(jaccard * 20)
        eval_criteria["correct_brands"] = {
            "passed": expected_ids == actual_ids,
            "score": brand_score,
            "max_score": 20,
            "reason": "" if expected_ids == actual_ids else f"Expected {len(expected_ids)} brands, got {len(actual_ids)}; overlap {len(expected_ids & actual_ids)}",
        }

        # --- 3. Correct severity scores (20 pts) ---
        common = expected_ids & actual_ids
        sev_correct = 0
        for bid in common:
            if abs(expected_map[bid]["severity_score"] - actual_map[bid]["severity_score"]) <= 1.0:
                sev_correct += 1
        sev_score = round(sev_correct / max(1, len(expected_ids)) * 20)
        eval_criteria["correct_severity_scores"] = {
            "passed": sev_correct == len(expected_ids),
            "score": sev_score,
            "max_score": 20,
            "reason": "" if sev_correct == len(expected_ids) else f"{sev_correct}/{len(expected_ids)} scores within tolerance",
        }

        # --- 4. Correct ranking order (15 pts) ---
        actual_order = [a["brand_id"] for a in actual_parsed]
        expected_order = [a["brand_id"] for a in expected]
        if actual_order == expected_order:
            rank_pts = 15
        elif len(actual_order) > 0 and len(expected_order) > 0:
            # Count pairwise correct orderings among common brands
            common_expected = [b for b in expected_order if b in actual_ids]
            common_actual = [b for b in actual_order if b in expected_ids]
            if len(common_expected) > 1:
                pairs_total = 0
                pairs_correct = 0
                for i in range(len(common_expected)):
                    for j in range(i + 1, len(common_expected)):
                        pairs_total += 1
                        bi, bj = common_expected[i], common_expected[j]
                        if bi in common_actual and bj in common_actual:
                            if common_actual.index(bi) < common_actual.index(bj):
                                pairs_correct += 1
                rank_pts = round(pairs_correct / max(1, pairs_total) * 15)
            else:
                rank_pts = 15 if set(common_expected) == set(common_actual) else 0
        else:
            rank_pts = 0
        eval_criteria["correct_ranking"] = {
            "passed": actual_order == expected_order,
            "score": rank_pts,
            "max_score": 15,
        }

        # --- 5. Correct signal values (social_zscore, headline_risk, ticket_negativity, exec_risk_flag) (15 pts) ---
        signal_correct = 0
        signal_total = 0
        for bid in common:
            ea = expected_map[bid]
            aa = actual_map[bid]
            for key, tol in [("social_zscore", 0.5), ("headline_risk", 0.05),
                             ("ticket_negativity", 0.05), ("exec_risk_flag", 0.01)]:
                signal_total += 1
                if abs(ea[key] - aa[key]) <= tol:
                    signal_correct += 1
        sig_pts = round(signal_correct / max(1, signal_total) * 15)
        eval_criteria["correct_signal_values"] = {
            "passed": signal_correct == signal_total,
            "score": sig_pts,
            "max_score": 15,
            "reason": "" if signal_correct == signal_total else f"{signal_correct}/{signal_total} signal values correct",
        }

        # --- 6. Alerts filed in the reputation_alerts register (10 pts) ---
        #     (M4 conversion of the former brand_risk_summary.json criterion;
        #      same weight, DB state written via the file_alert tool.)
        db_alerts: Dict[int, float] = {}
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            has_table = c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='reputation_alerts'"
            ).fetchone()
            if has_table:
                for bid, sev in c.execute(
                    "SELECT brand_id, severity_score FROM reputation_alerts"
                ).fetchall():
                    db_alerts[int(bid)] = float(sev)
            conn.close()
        except Exception:
            pass
        db_ids = set(db_alerts)
        filed_correct = sum(
            1 for bid in expected_ids & db_ids
            if abs(expected_map[bid]["severity_score"] - db_alerts[bid]) <= 1.0
        )
        if not expected_ids and not db_ids:
            register_ok = True
            register_score = 10
        else:
            register_ok = db_ids == expected_ids and filed_correct == len(expected_ids)
            register_score = round(filed_correct / max(1, len(expected_ids | db_ids)) * 10)
        eval_criteria["alert_register_db"] = {
            "passed": register_ok,
            "score": register_score,
            "max_score": 10,
            "reason": "" if register_ok else (
                f"{filed_correct}/{len(expected_ids)} expected alerts filed correctly; "
                f"{len(db_ids - expected_ids)} unexpected filings"
            ),
        }

        # --- 7. Action string contains correct count and priority list (10 pts) ---
        action_pts = 0
        # Check "Total alerts: N"
        count_match = re.search(r"Total alerts:\s*(\d+)", action)
        if count_match and int(count_match.group(1)) == len(expected):
            action_pts += 5
        # Check "Priority order: brand1, brand2, ..."
        order_match = re.search(r"Priority order:\s*(.+)", action)
        if order_match and expected:
            listed_names = [n.strip() for n in order_match.group(1).split(",")]
            expected_names = [a["brand_name"] for a in expected]
            if listed_names == expected_names:
                action_pts += 5
            elif set(listed_names) == set(expected_names):
                action_pts += 2
        elif not expected:
            action_pts += 5  # no alerts expected
        eval_criteria["action_string"] = {
            "passed": action_pts == 10,
            "score": action_pts,
            "max_score": 10,
        }

        total_score = sum(v["score"] for v in eval_criteria.values())
        max_score = sum(v["max_score"] for v in eval_criteria.values())

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
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
        for search_headlines / get_support_tickets and nested request payloads
        for file_alert.
        """
        ws = self.workspace
        tool_calls = 0

        def _call(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        # ------ 1. Read workspace config files ------
        with open(os.path.join(ws, "anomaly_config.yaml")) as f:
            anomaly_config = yaml.safe_load(f)
        with open(os.path.join(ws, "sentiment_rules.json")) as f:
            sentiment_rules = json.load(f)
        with open(os.path.join(ws, "priority_matrix.json")) as f:
            priority_matrix = json.load(f)

        neg_kw = [k.lower() for k in sentiment_rules["negative_keywords"]]
        crit_kw = [k.lower() for k in sentiment_rules["critical_keywords"]]
        crisis_kw = [k.lower() for k in sentiment_rules["crisis_keywords"]]
        weights = priority_matrix["weights"]
        scaling = priority_matrix["signal_scaling"]
        tier_mults = priority_matrix["tier_multipliers"]
        sev_mults = priority_matrix["severity_override_multipliers"]
        risk_mults = priority_matrix["risk_assessment_multipliers"]

        # ------ 2. Read brand tiers from workspace CSVs ------
        brand_tiers = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("brand_tier_") and fname.endswith(".csv"):
                with open(os.path.join(ws, fname), newline="") as f:
                    for row in csv.DictReader(f):
                        brand_tiers[int(row["brand_id"])] = row["monitoring_tier"]

        # ------ 3. Read social baselines from workspace JSONs ------
        baselines = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("social_baseline_") and fname.endswith(".json"):
                with open(os.path.join(ws, fname)) as f:
                    data = json.load(f)
                    for bid_str, stats in data.items():
                        baselines[int(bid_str)] = stats

        # ------ 4. Read ticket severity overrides from workspace TXTs ------
        ticket_overrides = {}
        block_pattern = re.compile(
            r"=== Brand:[^=]*?\(ID:\s*(\d+)\s*\)\s*===\s*(.*?)(?=(?:\n=== Brand:)|\Z)",
            re.DOTALL,
        )
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("ticket_notes_") and fname.endswith(".txt"):
                with open(os.path.join(ws, fname)) as f:
                    content = f.read()
                for m in block_pattern.finditer(content):
                    bid = int(m.group(1))
                    sev_match = re.search(r"Overall ticket severity:\s*(\w+)", m.group(2))
                    if sev_match:
                        ticket_overrides[bid] = sev_match.group(1)

        # ------ 5. Read exec watchlists from workspace YAMLs ------
        exec_watchlists = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("exec_watchlist_") and fname.endswith(".yaml"):
                with open(os.path.join(ws, fname)) as f:
                    data = yaml.safe_load(f)
                    if data:
                        for entry in data:
                            exec_watchlists[entry["brand_id"]] = entry

        # ------ 6. Retrieve all brands via tool ------
        all_brands = []
        page = 1
        while True:
            result = _call("list_brands", page=page, page_size=50)
            all_brands.extend(result["brands"])
            if not result["has_more"]:
                break
            page += 1

        # ------ 7. For each brand compute signals ------
        alerts = []
        for brand in all_brands:
            bid = brand["brand_id"]

            # --- Social anomaly ---
            sm = _call("get_social_media_metrics", brand_id=bid)
            daily_totals: Dict[str, int] = {}
            for m in sm["metrics"]:
                daily_totals[m["date"]] = daily_totals.get(m["date"], 0) + m["mention_count"]
            daily_vals = list(daily_totals.values())
            current_avg = sum(daily_vals) / len(daily_vals) if daily_vals else 0.0
            bl = baselines.get(bid, {"mean": current_avg, "std": 1.0})
            z_score = (current_avg - bl["mean"]) / bl["std"] if bl["std"] > 0 else 0.0
            anomaly_raw = max(0.0, z_score)

            # --- Headline sentiment (JSON-string filter, paginated) ---
            all_headlines = []
            hpage = 1
            hfilter = json.dumps({"brand_id": bid})
            while True:
                hr = _call("search_headlines", filter=hfilter, page=hpage, page_size=50)
                all_headlines.extend(hr["headlines"])
                if not hr["has_more"]:
                    break
                hpage += 1
            neg_h, crit_h = 0, 0
            for h in all_headlines:
                hl = h["headline"].lower()
                if any(kw in hl for kw in crit_kw):
                    crit_h += 1
                elif any(kw in hl for kw in neg_kw):
                    neg_h += 1
            headline_raw = (neg_h + 2 * crit_h) / max(1, len(all_headlines))

            # --- Ticket sentiment (JSON-string filter, paginated) ---
            all_tickets = []
            tpage = 1
            tfilter = json.dumps({"brand_id": bid})
            while True:
                tr = _call("get_support_tickets", filter=tfilter, page=tpage, page_size=50)
                all_tickets.extend(tr["tickets"])
                if not tr["has_more"]:
                    break
                tpage += 1
            neg_t = 0
            for t in all_tickets:
                tc = _call("get_ticket_content", ticket_id=t["ticket_id"])
                text = (tc["subject"] + " " + tc["body"]).lower()
                if any(kw in text for kw in neg_kw):
                    neg_t += 1
            ticket_base = neg_t / max(1, len(all_tickets))
            override = ticket_overrides.get(bid, "normal")
            ticket_raw = ticket_base * sev_mults.get(override, 1.0)

            # --- Exec comms risk ---
            all_comms = []
            epage = 1
            while True:
                er = _call("get_executive_comms", brand_id=bid, page=epage, page_size=50)
                all_comms.extend(er["communications"])
                if not er["has_more"]:
                    break
                epage += 1
            wl = exec_watchlists.get(bid, {})
            watched = wl.get("watched_executives", [])
            exec_flag = 0
            for cm in all_comms:
                if cm["spokesperson"] in watched:
                    detail = _call("get_comm_content", comm_id=cm["comm_id"])
                    if any(kw in detail["summary"].lower() for kw in crisis_kw):
                        exec_flag = 1
                        break
            risk_level = wl.get("risk_assessment", "medium")
            exec_raw = exec_flag * risk_mults.get(risk_level, 1.0)

            # --- Combined severity ---
            raw_severity = (
                weights["social_anomaly"] * anomaly_raw * scaling["social_anomaly"]
                + weights["headline_sentiment"] * headline_raw * scaling["headline_sentiment"]
                + weights["ticket_sentiment"] * ticket_raw * scaling["ticket_sentiment"]
                + weights["executive_comms"] * exec_raw * scaling["executive_comms"]
            )
            tier = brand_tiers.get(bid, "silver")
            severity = round(raw_severity * tier_mults.get(tier, 1.0), 2)

            if severity >= priority_matrix["alert_threshold"]:
                alerts.append({
                    "brand_id": bid,
                    "brand_name": brand["brand_name"],
                    "monitoring_tier": tier,
                    "severity_score": severity,
                    "social_zscore": round(z_score, 2),
                    "headline_risk": round(headline_raw, 4),
                    "ticket_negativity": round(ticket_raw, 4),
                    "exec_risk_flag": exec_flag,
                })

        # ------ 8. Sort and rank ------
        alerts.sort(key=lambda a: (-a["severity_score"], a["brand_id"]))
        for i, a in enumerate(alerts):
            a["rank"] = i + 1

        # ------ 9. Write alert_queue.csv ------
        csv_path = os.path.join(ws, "alert_queue.csv")
        fieldnames = ["rank", "brand_id", "brand_name", "monitoring_tier",
                       "severity_score", "social_zscore", "headline_risk",
                       "ticket_negativity", "exec_risk_flag"]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for a in alerts:
                writer.writerow(a)

        # ------ 10. File each alert via the nested write API ------
        for a in alerts:
            result = _call(
                "file_alert",
                payload={
                    "parent": {"type": "alert_queue", "queue_id": "reputation-alerts"},
                    "properties": {
                        "Brand": {
                            "type": "reference",
                            "reference": {"brand_id": a["brand_id"]},
                        },
                        "Severity": {"type": "number", "number": a["severity_score"]},
                    },
                },
            )
            assert result.get("object") == "alert" and result.get("created"), result

        # ------ 11. Construct action string ------
        brand_list = ", ".join(a["brand_name"] for a in alerts)
        action = f"Total alerts: {len(alerts)}\nPriority order: {brand_list}"

        print(f"[verify] total tool calls: {tool_calls}")
        return self.step(action)
