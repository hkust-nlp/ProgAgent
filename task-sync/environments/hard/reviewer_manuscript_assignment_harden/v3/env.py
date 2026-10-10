"""
Environment for the manuscript-reviewer assignment task (hardened tool surface).

Hardened surface (M1 + M4):
  - list_manuscripts and list_reviewers take a single JSON-encoded string
    `filter` parameter; malformed JSON, wrong-typed values, or unsupported
    keys produce recoverable API-style errors.
  - A new create_review_assignment write tool records each manuscript-reviewer
    pairing in the database through a deeply nested request payload
    (parent + properties) validated layer by layer with Notion-style error
    messages. Success and error responses use completely different shapes.
Task semantics, data generation, ground truth, and the original scoring
criteria are unchanged; step() gains one DB-state criterion for the write API.
"""

import ast
import csv
import hashlib
import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


# ── Decorator for tool registration ─────────────────────────────────────────
def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ── Hardened tool-surface helpers ────────────────────────────────────────────

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
    """Parse a parameter documented as a JSON-encoded string.

    Returns (value, None) on success or (None, error_dict) on failure.
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


def _as_page_int(value, name: str, default: int):
    """Coerce a pagination parameter to a non-negative int, or return an error."""
    if value is None:
        return default, None
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            value = int(str(value))
        except (ValueError, TypeError):
            return None, _error(
                400,
                "validation_error",
                f"body.{name} should be an integer, instead was {_shape(value)}.",
            )
    if value < 0:
        return None, _error(
            400,
            "validation_error",
            f"body.{name} should be a non-negative integer, instead was {_shape(value)}.",
        )
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

    # ── Internal DB helper for the write tool ────────────────────────────

    def _ensure_assignment_table(self, conn) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS review_assignments ("
            "manuscript_id TEXT NOT NULL, "
            "reviewer_id TEXT NOT NULL, "
            "PRIMARY KEY (manuscript_id, reviewer_id))"
        )

    # ── Tool methods ─────────────────────────────────────────────────────

    @tool(
        description=(
            "List pending manuscripts with pagination. Returns a list of "
            "manuscript stubs (manuscript_id, title). Filtering is expressed "
            "as a JSON-encoded string, e.g. "
            "filter='{\"field\": \"Physics\", \"min_pages\": 10}'. Supported "
            "filter properties: field (string), min_pages (integer), and "
            "max_pages (integer). Use get_manuscript_details for full "
            "information on a specific manuscript."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"field\": \"Biology\", \"max_pages\": 20}'. "
                        "Pass '{}' or omit for no filtering."
                    ),
                },
                "offset": {
                    "type": "integer",
                    "description": "Starting index (0-based). Default 0.",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Maximum number of manuscripts to return (max 10). "
                        "Default 10."
                    ),
                },
            },
            "required": [],
        },
    )
    def list_manuscripts(
        self, filter: Any = None, offset: Any = 0, limit: Any = 10
    ) -> dict:
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err
        offset, err = _as_page_int(offset, "offset", 0)
        if err is not None:
            return err
        limit, err = _as_page_int(limit, "limit", 10)
        if err is not None:
            return err
        limit = min(limit, 10)

        supported = {"field", "min_pages", "max_pages"}
        for key in parsed:
            if key not in supported:
                return _error(
                    400,
                    "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: field, min_pages, max_pages.",
                )

        clauses = ["status='pending'"]
        params: list = []
        if "field" in parsed:
            field = parsed["field"]
            if not isinstance(field, str) or not field:
                return _error(
                    400,
                    "validation_error",
                    f"body.filter.field should be a non-empty string, "
                    f"instead was {_shape(field)}.",
                )
            clauses.append("field=?")
            params.append(field)
        if "min_pages" in parsed:
            mn = parsed["min_pages"]
            if isinstance(mn, bool) or not isinstance(mn, int):
                return _error(
                    400,
                    "validation_error",
                    f"body.filter.min_pages should be an integer, "
                    f"instead was {_shape(mn)}.",
                )
            clauses.append("num_pages>=?")
            params.append(mn)
        if "max_pages" in parsed:
            mx = parsed["max_pages"]
            if isinstance(mx, bool) or not isinstance(mx, int):
                return _error(
                    400,
                    "validation_error",
                    f"body.filter.max_pages should be an integer, "
                    f"instead was {_shape(mx)}.",
                )
            clauses.append("num_pages<=?")
            params.append(mx)

        where = " AND ".join(clauses)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM manuscripts WHERE {where}", params)
        total = cur.fetchone()[0]
        cur.execute(
            f"SELECT manuscript_id, title FROM manuscripts "
            f"WHERE {where} ORDER BY manuscript_id "
            f"LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        rows = [
            {"manuscript_id": r[0], "title": r[1]} for r in cur.fetchall()
        ]
        conn.close()
        return {"total": total, "offset": offset, "limit": limit, "manuscripts": rows}

    @tool(
        description=(
            "Get full details for a single manuscript by its ID. "
            "Returns manuscript_id, title, field, submission_date, "
            "status, and num_pages."
        ),
        parameters={
            "type": "object",
            "properties": {
                "manuscript_id": {
                    "type": "string",
                    "description": "The manuscript identifier, e.g. M0001.",
                },
            },
            "required": ["manuscript_id"],
        },
    )
    def get_manuscript_details(self, manuscript_id: Any = None) -> dict:
        if not isinstance(manuscript_id, str) or not manuscript_id:
            return _error(
                400,
                "validation_error",
                f"body.manuscript_id should be a non-empty string, "
                f"instead was {_shape(manuscript_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT manuscript_id, title, field, submission_date, status, "
            "num_pages FROM manuscripts WHERE manuscript_id=?",
            (manuscript_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _error(
                404,
                "object_not_found",
                f"Could not find manuscript with ID: {manuscript_id}.",
            )
        return {
            "manuscript_id": row[0],
            "title": row[1],
            "field": row[2],
            "submission_date": row[3],
            "status": row[4],
            "num_pages": row[5],
        }

    @tool(
        description=(
            "List reviewers with pagination. Returns reviewer stubs "
            "(reviewer_id, name). Filtering is expressed as a JSON-encoded "
            "string, e.g. filter='{\"institution\": \"MIT\", "
            "\"min_capacity\": 3}'. Supported filter properties: institution "
            "(string) and min_capacity (integer, minimum max_reviews_per_round). "
            "Use get_reviewer_details for full info."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"institution\": \"ETH Zurich\", \"min_capacity\": 4}'. "
                        "Pass '{}' or omit for no filtering."
                    ),
                },
                "offset": {
                    "type": "integer",
                    "description": "Starting index (0-based). Default 0.",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Maximum number of reviewers to return (max 10). "
                        "Default 10."
                    ),
                },
            },
            "required": [],
        },
    )
    def list_reviewers(
        self, filter: Any = None, offset: Any = 0, limit: Any = 10
    ) -> dict:
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err
        offset, err = _as_page_int(offset, "offset", 0)
        if err is not None:
            return err
        limit, err = _as_page_int(limit, "limit", 10)
        if err is not None:
            return err
        limit = min(limit, 10)

        supported = {"institution", "min_capacity"}
        for key in parsed:
            if key not in supported:
                return _error(
                    400,
                    "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: institution, min_capacity.",
                )

        clauses = []
        params: list = []
        if "institution" in parsed:
            inst = parsed["institution"]
            if not isinstance(inst, str) or not inst:
                return _error(
                    400,
                    "validation_error",
                    f"body.filter.institution should be a non-empty string, "
                    f"instead was {_shape(inst)}.",
                )
            clauses.append("institution=?")
            params.append(inst)
        if "min_capacity" in parsed:
            mc = parsed["min_capacity"]
            if isinstance(mc, bool) or not isinstance(mc, int):
                return _error(
                    400,
                    "validation_error",
                    f"body.filter.min_capacity should be an integer, "
                    f"instead was {_shape(mc)}.",
                )
            clauses.append("max_reviews_per_round>=?")
            params.append(mc)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM reviewers{where}", params)
        total = cur.fetchone()[0]
        cur.execute(
            f"SELECT reviewer_id, name FROM reviewers{where} "
            f"ORDER BY reviewer_id LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        rows = [
            {"reviewer_id": r[0], "name": r[1]} for r in cur.fetchall()
        ]
        conn.close()
        return {"total": total, "offset": offset, "limit": limit, "reviewers": rows}

    @tool(
        description=(
            "Get full details for a single reviewer. Returns reviewer_id, "
            "name, institution, email, and max_reviews_per_round."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reviewer_id": {
                    "type": "string",
                    "description": "The reviewer identifier, e.g. R0001.",
                },
            },
            "required": ["reviewer_id"],
        },
    )
    def get_reviewer_details(self, reviewer_id: Any = None) -> dict:
        if not isinstance(reviewer_id, str) or not reviewer_id:
            return _error(
                400,
                "validation_error",
                f"body.reviewer_id should be a non-empty string, "
                f"instead was {_shape(reviewer_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT reviewer_id, name, institution, email, "
            "max_reviews_per_round FROM reviewers WHERE reviewer_id=?",
            (reviewer_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _error(
                404,
                "object_not_found",
                f"Could not find reviewer with ID: {reviewer_id}.",
            )
        return {
            "reviewer_id": row[0],
            "name": row[1],
            "institution": row[2],
            "email": row[3],
            "max_reviews_per_round": row[4],
        }

    @tool(
        description=(
            "Get all declared conflicts of interest for a specific "
            "manuscript. Returns a list of conflicted reviewer IDs "
            "with conflict type and reason."
        ),
        parameters={
            "type": "object",
            "properties": {
                "manuscript_id": {
                    "type": "string",
                    "description": "The manuscript identifier.",
                },
            },
            "required": ["manuscript_id"],
        },
    )
    def get_conflicts_for_manuscript(self, manuscript_id: Any = None) -> dict:
        if not isinstance(manuscript_id, str) or not manuscript_id:
            return _error(
                400,
                "validation_error",
                f"body.manuscript_id should be a non-empty string, "
                f"instead was {_shape(manuscript_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM manuscripts WHERE manuscript_id=?",
            (manuscript_id,),
        )
        if cur.fetchone()[0] == 0:
            conn.close()
            return _error(
                404,
                "object_not_found",
                f"Could not find manuscript with ID: {manuscript_id}.",
            )
        cur.execute(
            "SELECT reviewer_id, conflict_type, reason "
            "FROM conflicts_of_interest WHERE manuscript_id=?",
            (manuscript_id,),
        )
        rows = [
            {
                "reviewer_id": r[0],
                "conflict_type": r[1],
                "reason": r[2],
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return {"manuscript_id": manuscript_id, "conflicts": rows}

    @tool(
        description=(
            "Get the historical review quality and timeliness scores "
            "for a specific reviewer. Returns a list of past review "
            "records with quality_score, timeliness_score, and review_year."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reviewer_id": {
                    "type": "string",
                    "description": "The reviewer identifier.",
                },
            },
            "required": ["reviewer_id"],
        },
    )
    def get_reviewer_quality_scores(self, reviewer_id: Any = None) -> dict:
        if not isinstance(reviewer_id, str) or not reviewer_id:
            return _error(
                400,
                "validation_error",
                f"body.reviewer_id should be a non-empty string, "
                f"instead was {_shape(reviewer_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM reviewers WHERE reviewer_id=?",
            (reviewer_id,),
        )
        if cur.fetchone()[0] == 0:
            conn.close()
            return _error(
                404,
                "object_not_found",
                f"Could not find reviewer with ID: {reviewer_id}.",
            )
        cur.execute(
            "SELECT quality_score, timeliness_score, review_year "
            "FROM review_history WHERE reviewer_id=? "
            "ORDER BY review_year",
            (reviewer_id,),
        )
        rows = [
            {
                "quality_score": r[0],
                "timeliness_score": r[1],
                "review_year": r[2],
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return {"reviewer_id": reviewer_id, "history": rows}

    @tool(
        description=(
            "Records one reviewer assignment: registers a reviewer onto a "
            "pending manuscript's review panel in the editorial system. The "
            "request body must contain a `parent` object identifying the "
            "manuscript review panel and a `properties` object with a "
            "`Reviewer` reference property. Example body: "
            "{\"parent\": {\"type\": \"review_panel\", \"manuscript_id\": "
            "\"M0001\"}, \"properties\": {\"Reviewer\": {\"type\": "
            "\"reference\", \"reference\": {\"reviewer_id\": \"R0001\"}}}}. "
            "An optional `Note` rich_text property may be included in "
            "`properties`. Call once per reviewer-manuscript pairing; the "
            "same reviewer cannot be registered twice on one manuscript."
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
                                "The manuscript review panel that receives "
                                "the reviewer. Must contain "
                                "type='review_panel' and a manuscript_id "
                                "string."
                            ),
                            "properties": {
                                "type": {"type": "string"},
                                "manuscript_id": {"type": "string"},
                            },
                            "required": ["type", "manuscript_id"],
                            "additionalProperties": True,
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Assignment properties. Must include a "
                                "'Reviewer' reference property. May include "
                                "a 'Note' rich_text property."
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
    def create_review_assignment(self, payload: Any = None) -> dict:
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
        if parent.get("type") != "review_panel":
            return _error(
                400, "validation_error",
                f"body.parent.type should be \"review_panel\", instead was "
                f"{_shape(parent.get('type'))}.",
            )
        manuscript_id = parent.get("manuscript_id")
        if not isinstance(manuscript_id, str) or not manuscript_id:
            return _error(
                400, "validation_error",
                f"body.parent.manuscript_id should be a non-empty string, "
                f"instead was {_shape(manuscript_id)}.",
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

        reviewer_prop = props.get("Reviewer")
        if reviewer_prop is None:
            return _error(
                400, "validation_error",
                "body.properties.Reviewer should be defined, instead was 'undefined'.",
            )
        if not isinstance(reviewer_prop, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Reviewer should be an object, instead was "
                f"{_shape(reviewer_prop)}.",
            )
        if reviewer_prop.get("type") != "reference":
            return _error(
                400, "validation_error",
                f"body.properties.Reviewer.type should be \"reference\", "
                f"instead was {_shape(reviewer_prop.get('type'))}.",
            )
        reference = reviewer_prop.get("reference")
        if not isinstance(reference, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Reviewer.reference should be an object, "
                f"instead was {_shape(reference)}.",
            )
        reviewer_id = reference.get("reviewer_id")
        if not isinstance(reviewer_id, str) or not reviewer_id:
            return _error(
                400, "validation_error",
                f"body.properties.Reviewer.reference.reviewer_id should be a "
                f"non-empty string, instead was {_shape(reviewer_id)}.",
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
                    f"body.properties.Note.rich_text should be an array, "
                    f"instead was {_shape(rich)}.",
                )
            for i, item in enumerate(rich):
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("text"), dict)
                    or not isinstance(item["text"].get("content"), str)
                ):
                    return _error(
                        400, "validation_error",
                        f"body.properties.Note.rich_text[{i}].text.content "
                        f"should be a string, instead was 'undefined'.",
                    )

        # --- Business validation ---
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT status FROM manuscripts WHERE manuscript_id=?",
            (manuscript_id,),
        )
        row = cur.fetchone()
        if row is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find manuscript with ID: {manuscript_id}.",
            )
        if row[0] != "pending":
            conn.close()
            return _error(
                400, "validation_error",
                f"Manuscript '{manuscript_id}' is not pending "
                f"(status='{row[0]}').",
            )
        cur.execute(
            "SELECT reviewer_id FROM reviewers WHERE reviewer_id=?",
            (reviewer_id,),
        )
        if cur.fetchone() is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find reviewer with ID: {reviewer_id}.",
            )

        self._ensure_assignment_table(conn)
        cur.execute(
            "SELECT COUNT(*) FROM review_assignments "
            "WHERE manuscript_id=? AND reviewer_id=?",
            (manuscript_id, reviewer_id),
        )
        if cur.fetchone()[0] > 0:
            conn.close()
            return _error(
                400, "validation_error",
                f"Reviewer '{reviewer_id}' is already registered on the "
                f"review panel of manuscript '{manuscript_id}'.",
            )

        # --- Perform the write ---
        cur.execute(
            "INSERT INTO review_assignments (manuscript_id, reviewer_id) "
            "VALUES (?, ?)",
            (manuscript_id, reviewer_id),
        )
        conn.commit()
        conn.close()

        # Success response: deep echo, shape entirely different from errors.
        return {
            "object": "review_assignment",
            "id": "asg_" + hashlib.md5(
                f"{manuscript_id}:{reviewer_id}".encode()
            ).hexdigest()[:10],
            "parent": {"type": "review_panel", "manuscript_id": manuscript_id},
            "properties": {
                "Reviewer": {
                    "type": "reference",
                    "reference": {"reviewer_id": reviewer_id},
                },
                "Status": {"type": "select", "select": {"name": "assigned"}},
            },
            "created": True,
        }

    # ── Internal helpers (used by step / verify) ─────────────────────────

    def _load_manuscript_keywords_from_workspace(self) -> Dict[str, List[str]]:
        """Read all manuscript keyword CSV files from workspace."""
        kw_map: Dict[str, List[str]] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("manuscript_keywords_batch_") and fname.endswith(".csv"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath, newline="") as fh:
                    reader = csv.DictReader(fh)
                    for row in reader:
                        mid = row["manuscript_id"]
                        kw_map.setdefault(mid, []).append(row["keyword"])
        return kw_map

    def _load_reviewer_expertise_from_workspace(self) -> Dict[str, Dict]:
        """Read all reviewer expertise JSON files from workspace."""
        exp_map: Dict[str, Dict] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("reviewer_expertise_") and fname.endswith(".json"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath) as fh:
                    data = json.load(fh)
                    exp_map.update(data)
        return exp_map

    def _load_policy(self) -> dict:
        """Load assignment policy from workspace."""
        with open(os.path.join(self.workspace, "assignment_policy.json")) as fh:
            return json.load(fh)

    def _load_scoring_rubric(self) -> dict:
        """Load scoring rubric from workspace."""
        with open(os.path.join(self.workspace, "scoring_rubric.yaml")) as fh:
            return yaml.safe_load(fh)

    @staticmethod
    def _jaccard(set_a, set_b):
        """Jaccard similarity between two sets."""
        a, b = set(set_a), set(set_b)
        if not a and not b:
            return 0.0
        return len(a & b) / len(a | b)

    def _compute_ground_truth(self):
        """
        Compute the optimal greedy assignment matrix.
        Returns (assignment_dict, all_manuscripts_sorted, reviewer_capacities).
        assignment_dict: {manuscript_id: [(reviewer_id, pair_score), ...]}
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # All pending manuscripts sorted by submission_date, then manuscript_id
        cur.execute(
            "SELECT manuscript_id, field, submission_date "
            "FROM manuscripts WHERE status='pending' "
            "ORDER BY submission_date, manuscript_id"
        )
        manuscripts = cur.fetchall()

        # All reviewers
        cur.execute(
            "SELECT reviewer_id, max_reviews_per_round FROM reviewers"
        )
        reviewer_caps = {r[0]: r[1] for r in cur.fetchall()}

        # All conflicts
        cur.execute(
            "SELECT reviewer_id, manuscript_id FROM conflicts_of_interest"
        )
        conflicts = set()
        for r in cur.fetchall():
            conflicts.add((r[0], r[1]))

        # All review history → avg scores
        cur.execute(
            "SELECT reviewer_id, quality_score, timeliness_score "
            "FROM review_history"
        )
        history_data: Dict[str, List] = {}
        for r in cur.fetchall():
            history_data.setdefault(r[0], []).append((r[1], r[2]))
        conn.close()

        reviewer_avg = {}
        for rid, scores in history_data.items():
            avg_q = sum(s[0] for s in scores) / len(scores)
            avg_t = sum(s[1] for s in scores) / len(scores)
            reviewer_avg[rid] = (avg_q, avg_t)

        # Workspace data
        m_keywords = self._load_manuscript_keywords_from_workspace()
        r_expertise = self._load_reviewer_expertise_from_workspace()
        policy = self._load_policy()
        rubric = self._load_scoring_rubric()

        rev_per_ms = policy["reviewers_per_manuscript"]
        min_qual = policy["min_quality_threshold"]
        kw_weight = rubric["scoring_formula"]["keyword_match"]["weight"]
        kw_scale = rubric["scoring_formula"]["keyword_match"]["scale_factor"]
        q_weight = rubric["scoring_formula"]["quality"]["weight"]
        q_scale = rubric["scoring_formula"]["quality"]["scale_factor"]
        t_weight = rubric["scoring_formula"]["timeliness"]["weight"]
        t_scale = rubric["scoring_formula"]["timeliness"]["scale_factor"]

        # Track remaining capacity
        remaining_cap = dict(reviewer_caps)
        current_load = {rid: 0 for rid in reviewer_caps}

        assignments: Dict[str, list] = {}

        for mid, field, sub_date in manuscripts:
            m_kws = set(m_keywords.get(mid, []))
            eligible = []
            for rid in reviewer_caps:
                # Conflict check
                if (rid, mid) in conflicts:
                    continue
                # Capacity check
                if remaining_cap[rid] <= 0:
                    continue
                # Quality check
                if rid not in reviewer_avg:
                    continue
                avg_q, avg_t = reviewer_avg[rid]
                if avg_q < min_qual:
                    continue
                # Compute score
                r_kws = set(r_expertise.get(rid, {}).get("expertise_keywords", []))
                jsim = self._jaccard(m_kws, r_kws)
                pair_score = (
                    kw_weight * jsim * kw_scale
                    + q_weight * avg_q * q_scale
                    + t_weight * avg_t * t_scale
                )
                eligible.append((rid, pair_score, current_load[rid]))

            # Sort: highest score first, then fewest assignments, then reviewer_id
            eligible.sort(key=lambda x: (-x[1], x[2], x[0]))

            chosen = []
            for rid, ps, _ in eligible[:rev_per_ms]:
                chosen.append((rid, round(ps, 4)))
                remaining_cap[rid] -= 1
                current_load[rid] += 1

            assignments[mid] = chosen

        return assignments, manuscripts

    # ── Evaluation ───────────────────────────────────────────────────────

    def step(
        self, action: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's
        final response.

        Returns a reward based on evaluation results.

        Args:
            action: The agent's final response.

        Returns:
            reward: The reward based on task completion (between 0.0 and 1.0).
            info: Evaluation results.
        """
        criteria = {}
        gt_assignments, gt_manuscripts = self._compute_ground_truth()
        policy = self._load_policy()
        rubric = self._load_scoring_rubric()
        rev_per_ms = policy["reviewers_per_manuscript"]
        min_qual = policy["min_quality_threshold"]

        # Load conflicts from DB
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT reviewer_id, manuscript_id FROM conflicts_of_interest"
        )
        conflict_set = set((r[0], r[1]) for r in cur.fetchall())
        cur.execute(
            "SELECT reviewer_id, max_reviews_per_round FROM reviewers"
        )
        reviewer_caps = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute(
            "SELECT reviewer_id, quality_score FROM review_history"
        )
        hist: Dict[str, List[float]] = {}
        for r in cur.fetchall():
            hist.setdefault(r[0], []).append(r[1])
        conn.close()

        reviewer_avg_q = {
            rid: sum(s) / len(s) for rid, s in hist.items()
        }

        # ── Criterion 1: File exists and correct format (10 pts) ────────
        matrix_path = os.path.join(self.workspace, "assignment_matrix.csv")
        c1_pass = False
        agent_assignments: Dict[str, List[str]] = {}
        agent_scores: Dict[str, float] = {}
        if os.path.isfile(matrix_path):
            try:
                with open(matrix_path, newline="") as fh:
                    reader = csv.DictReader(fh)
                    cols = reader.fieldnames or []
                    expected_cols = [
                        "manuscript_id", "reviewer_1", "reviewer_2",
                        "reviewer_3", "assignment_score",
                    ]
                    if all(c in cols for c in expected_cols):
                        c1_pass = True
                        for row in reader:
                            mid = row["manuscript_id"]
                            revs = [
                                row["reviewer_1"],
                                row["reviewer_2"],
                                row["reviewer_3"],
                            ]
                            agent_assignments[mid] = revs
                            try:
                                agent_scores[mid] = float(
                                    row["assignment_score"]
                                )
                            except (ValueError, TypeError):
                                agent_scores[mid] = 0.0
            except Exception:
                c1_pass = False

        criteria["file_format"] = {
            "passed": c1_pass,
            "score": 10 if c1_pass else 0,
            "max_score": 10,
            "reason": "" if c1_pass else (
                "assignment_matrix.csv missing or has wrong columns"
            ),
        }

        if not c1_pass:
            # Can't evaluate further
            for cname, maxs in [
                ("all_manuscripts_assigned", 15),
                ("no_conflict_violations", 20),
                ("capacity_respected", 15),
                ("quality_threshold", 15),
                ("assignment_quality", 25),
                ("db_assignments_recorded", 10),
            ]:
                criteria[cname] = {
                    "passed": False, "score": 0, "max_score": maxs,
                    "reason": "Cannot evaluate: file format check failed",
                }
            total = sum(c["score"] for c in criteria.values())
            mx = sum(c["max_score"] for c in criteria.values())
            return total / mx, {
                "eval_criteria": criteria,
                "total_score": total,
                "max_score": mx,
            }

        all_pending = [m[0] for m in gt_manuscripts]

        # ── Criterion 2: All manuscripts assigned (15 pts) ──────────────
        assigned_count = 0
        correct_count_manuscripts = 0
        for mid in all_pending:
            if mid in agent_assignments:
                revs = [r for r in agent_assignments[mid] if r.strip()]
                if len(revs) == rev_per_ms:
                    correct_count_manuscripts += 1
                assigned_count += 1

        frac = correct_count_manuscripts / len(all_pending) if all_pending else 0
        c2_score = round(15 * frac)
        criteria["all_manuscripts_assigned"] = {
            "passed": frac == 1.0,
            "score": c2_score,
            "max_score": 15,
            "reason": "" if frac == 1.0 else (
                f"{correct_count_manuscripts}/{len(all_pending)} manuscripts "
                f"correctly assigned with {rev_per_ms} reviewers"
            ),
        }

        # ── Criterion 3: No conflict violations (20 pts) ────────────────
        conflict_violations = 0
        total_pairs = 0
        for mid, revs in agent_assignments.items():
            for rid in revs:
                if rid.strip():
                    total_pairs += 1
                    if (rid, mid) in conflict_set:
                        conflict_violations += 1

        c3_pass = conflict_violations == 0
        if total_pairs > 0:
            c3_frac = max(0, 1 - conflict_violations / total_pairs)
        else:
            c3_frac = 0
        c3_score = round(20 * c3_frac)
        criteria["no_conflict_violations"] = {
            "passed": c3_pass,
            "score": c3_score,
            "max_score": 20,
            "reason": "" if c3_pass else (
                f"{conflict_violations} conflict-of-interest violations found"
            ),
        }

        # ── Criterion 4: Capacity respected (15 pts) ────────────────────
        load_count: Dict[str, int] = {}
        for mid, revs in agent_assignments.items():
            for rid in revs:
                if rid.strip():
                    load_count[rid] = load_count.get(rid, 0) + 1

        over_cap = 0
        for rid, cnt in load_count.items():
            cap = reviewer_caps.get(rid, 0)
            if cnt > cap:
                over_cap += 1

        c4_pass = over_cap == 0
        c4_score = 15 if c4_pass else max(0, round(15 * (1 - over_cap / max(len(load_count), 1))))
        criteria["capacity_respected"] = {
            "passed": c4_pass,
            "score": c4_score,
            "max_score": 15,
            "reason": "" if c4_pass else (
                f"{over_cap} reviewers exceeded their max capacity"
            ),
        }

        # ── Criterion 5: Quality threshold (15 pts) ─────────────────────
        qual_violations = 0
        qual_total = 0
        for mid, revs in agent_assignments.items():
            for rid in revs:
                if rid.strip():
                    qual_total += 1
                    avg = reviewer_avg_q.get(rid, 0)
                    if avg < min_qual:
                        qual_violations += 1

        c5_pass = qual_violations == 0
        if qual_total > 0:
            c5_frac = max(0, 1 - qual_violations / qual_total)
        else:
            c5_frac = 0
        c5_score = round(15 * c5_frac)
        criteria["quality_threshold"] = {
            "passed": c5_pass,
            "score": c5_score,
            "max_score": 15,
            "reason": "" if c5_pass else (
                f"{qual_violations} assignments below min quality threshold"
            ),
        }

        # ── Criterion 6: Assignment quality (25 pts) ────────────────────
        # Compare agent's total assignment score vs ground truth
        m_keywords = self._load_manuscript_keywords_from_workspace()
        r_expertise = self._load_reviewer_expertise_from_workspace()

        kw_weight = rubric["scoring_formula"]["keyword_match"]["weight"]
        kw_scale = rubric["scoring_formula"]["keyword_match"]["scale_factor"]
        q_weight = rubric["scoring_formula"]["quality"]["weight"]
        q_scale = rubric["scoring_formula"]["quality"]["scale_factor"]
        t_weight = rubric["scoring_formula"]["timeliness"]["weight"]
        t_scale = rubric["scoring_formula"]["timeliness"]["scale_factor"]

        # Recompute avg timeliness too
        conn2 = sqlite3.connect(self.db_path)
        cur2 = conn2.cursor()
        cur2.execute(
            "SELECT reviewer_id, quality_score, timeliness_score "
            "FROM review_history"
        )
        hist_full: Dict[str, list] = {}
        for r in cur2.fetchall():
            hist_full.setdefault(r[0], []).append((r[1], r[2]))
        conn2.close()

        reviewer_avgs = {}
        for rid, recs in hist_full.items():
            reviewer_avgs[rid] = (
                sum(x[0] for x in recs) / len(recs),
                sum(x[1] for x in recs) / len(recs),
            )

        def calc_pair_score(mid, rid):
            m_kws = set(m_keywords.get(mid, []))
            r_kws = set(r_expertise.get(rid, {}).get("expertise_keywords", []))
            jsim = self._jaccard(m_kws, r_kws)
            avg_q, avg_t = reviewer_avgs.get(rid, (0, 0))
            return (
                kw_weight * jsim * kw_scale
                + q_weight * avg_q * q_scale
                + t_weight * avg_t * t_scale
            )

        # Ground truth total
        gt_total = 0.0
        for mid, chosen in gt_assignments.items():
            for rid, ps in chosen:
                gt_total += ps

        # Agent total
        agent_total = 0.0
        for mid, revs in agent_assignments.items():
            for rid in revs:
                if rid.strip() and rid in reviewer_avgs:
                    agent_total += calc_pair_score(mid, rid)

        if gt_total > 0:
            ratio = agent_total / gt_total
        else:
            ratio = 1.0 if agent_total == 0 else 0.0

        # Score: 100% if ratio >= 0.95, linear down to 0 at ratio < 0.5
        if ratio >= 0.95:
            c6_score = 25
        elif ratio >= 0.5:
            c6_score = round(25 * (ratio - 0.5) / 0.45)
        else:
            c6_score = 0

        c6_pass = c6_score == 25
        criteria["assignment_quality"] = {
            "passed": c6_pass,
            "score": c6_score,
            "max_score": 25,
            "reason": "" if c6_pass else (
                f"Agent total score {agent_total:.2f} vs optimal "
                f"{gt_total:.2f} (ratio={ratio:.3f})"
            ),
        }

        # ── Criterion 7: Assignments recorded via write API (10 pts) ────
        # (added with the M4 hardened surface; checks DB state written by
        #  create_review_assignment against the ground-truth pairs)
        conn3 = sqlite3.connect(self.db_path)
        cur3 = conn3.cursor()
        db_pairs = set()
        try:
            cur3.execute(
                "SELECT manuscript_id, reviewer_id FROM review_assignments"
            )
            db_pairs = set((r[0], r[1]) for r in cur3.fetchall())
        except sqlite3.OperationalError:
            db_pairs = set()
        conn3.close()

        gt_pairs = set()
        for mid, chosen in gt_assignments.items():
            for rid, ps in chosen:
                gt_pairs.add((mid, rid))

        db_ok = len(gt_pairs & db_pairs)
        c7_frac = db_ok / len(gt_pairs) if gt_pairs else 0.0
        c7_score = round(10 * c7_frac)
        criteria["db_assignments_recorded"] = {
            "passed": c7_frac == 1.0,
            "score": c7_score,
            "max_score": 10,
            "reason": "" if c7_frac == 1.0 else (
                f"{db_ok}/{len(gt_pairs)} ground-truth assignments recorded "
                f"in the editorial system"
            ),
        }

        total = sum(c["score"] for c in criteria.values())
        mx = sum(c["max_score"] for c in criteria.values())
        return total / mx, {
            "eval_criteria": criteria,
            "total_score": total,
            "max_score": mx,
        }

    # ── Self-verification ────────────────────────────────────────────────

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
        the list tools and nested request payloads for
        create_review_assignment.
        """
        tool_calls = 0

        def _call(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        # ── Step 1: Discover all pending manuscripts (JSON-string filter) ─
        all_manuscripts = []
        offset = 0
        while True:
            res = _call(
                "list_manuscripts",
                filter=json.dumps({}),
                offset=offset,
                limit=10,
            )
            all_manuscripts.extend(res["manuscripts"])
            if offset + 10 >= res["total"]:
                break
            offset += 10

        # ── Step 2: Get details for each manuscript ──────────────────────
        manuscript_details = {}
        for m in all_manuscripts:
            mid = m["manuscript_id"]
            det = _call("get_manuscript_details", manuscript_id=mid)
            manuscript_details[mid] = det

        # ── Step 3: Discover all reviewers (JSON-string filter) ──────────
        all_reviewers = []
        offset = 0
        filter_str = json.dumps({"min_capacity": 1})
        while True:
            res = _call(
                "list_reviewers", filter=filter_str, offset=offset, limit=10
            )
            all_reviewers.extend(res["reviewers"])
            if offset + 10 >= res["total"]:
                break
            offset += 10

        # ── Step 4: Get details & quality scores for each reviewer ───────
        reviewer_details = {}
        reviewer_avg = {}
        for r in all_reviewers:
            rid = r["reviewer_id"]
            det = _call("get_reviewer_details", reviewer_id=rid)
            reviewer_details[rid] = det

            hist = _call("get_reviewer_quality_scores", reviewer_id=rid)
            records = hist["history"]
            if records:
                avg_q = sum(x["quality_score"] for x in records) / len(records)
                avg_t = sum(x["timeliness_score"] for x in records) / len(records)
            else:
                avg_q, avg_t = 0.0, 0.0
            reviewer_avg[rid] = (avg_q, avg_t)

        # ── Step 5: Get conflicts for each manuscript ────────────────────
        manuscript_conflicts: Dict[str, set] = {}
        for m in all_manuscripts:
            mid = m["manuscript_id"]
            res = _call("get_conflicts_for_manuscript", manuscript_id=mid)
            manuscript_conflicts[mid] = set(
                c["reviewer_id"] for c in res["conflicts"]
            )

        # ── Step 6: Read workspace files ─────────────────────────────────
        m_keywords = self._load_manuscript_keywords_from_workspace()
        r_expertise = self._load_reviewer_expertise_from_workspace()
        policy = self._load_policy()
        rubric = self._load_scoring_rubric()

        rev_per_ms = policy["reviewers_per_manuscript"]
        min_qual = policy["min_quality_threshold"]
        kw_weight = rubric["scoring_formula"]["keyword_match"]["weight"]
        kw_scale = rubric["scoring_formula"]["keyword_match"]["scale_factor"]
        q_weight = rubric["scoring_formula"]["quality"]["weight"]
        q_scale = rubric["scoring_formula"]["quality"]["scale_factor"]
        t_weight = rubric["scoring_formula"]["timeliness"]["weight"]
        t_scale = rubric["scoring_formula"]["timeliness"]["scale_factor"]

        # ── Step 7: Greedy assignment ────────────────────────────────────
        # Sort manuscripts by submission_date, then manuscript_id
        sorted_mids = sorted(
            manuscript_details.keys(),
            key=lambda mid: (
                manuscript_details[mid]["submission_date"],
                mid,
            ),
        )

        remaining_cap = {
            rid: reviewer_details[rid]["max_reviews_per_round"]
            for rid in reviewer_details
        }
        current_load = {rid: 0 for rid in reviewer_details}

        assignments: Dict[str, list] = {}  # mid -> [(rid, pair_score)]

        for mid in sorted_mids:
            m_kws = set(m_keywords.get(mid, []))
            conflicts_for_m = manuscript_conflicts.get(mid, set())

            eligible = []
            for rid in reviewer_details:
                if rid in conflicts_for_m:
                    continue
                if remaining_cap[rid] <= 0:
                    continue
                avg_q, avg_t = reviewer_avg.get(rid, (0, 0))
                if avg_q < min_qual:
                    continue
                r_kws = set(
                    r_expertise.get(rid, {}).get("expertise_keywords", [])
                )
                jsim = self._jaccard(m_kws, r_kws)
                pair_score = (
                    kw_weight * jsim * kw_scale
                    + q_weight * avg_q * q_scale
                    + t_weight * avg_t * t_scale
                )
                eligible.append((rid, pair_score, current_load[rid]))

            eligible.sort(key=lambda x: (-x[1], x[2], x[0]))

            chosen = []
            for rid, ps, _ in eligible[:rev_per_ms]:
                chosen.append((rid, round(ps, 4)))
                remaining_cap[rid] -= 1
                current_load[rid] += 1

            assignments[mid] = chosen

        # ── Step 8: Record each assignment via the nested write API ──────
        for mid in sorted_mids:
            for rid, ps in assignments.get(mid, []):
                result = _call(
                    "create_review_assignment",
                    payload={
                        "parent": {
                            "type": "review_panel",
                            "manuscript_id": mid,
                        },
                        "properties": {
                            "Reviewer": {
                                "type": "reference",
                                "reference": {"reviewer_id": rid},
                            },
                        },
                    },
                )
                assert result.get("object") == "review_assignment" and \
                    result.get("created"), f"write failed: {result}"

        # ── Step 9: Write assignment_matrix.csv ──────────────────────────
        matrix_path = os.path.join(self.workspace, "assignment_matrix.csv")
        with open(matrix_path, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow([
                "manuscript_id", "reviewer_1", "reviewer_2",
                "reviewer_3", "assignment_score",
            ])
            for mid in sorted_mids:
                chosen = assignments.get(mid, [])
                revs = [c[0] for c in chosen]
                while len(revs) < rev_per_ms:
                    revs.append("")
                total_score = sum(c[1] for c in chosen)
                writer.writerow([
                    mid, revs[0], revs[1], revs[2],
                    f"{total_score:.2f}",
                ])

        # ── Step 10: Build response ──────────────────────────────────────
        total_pairs = sum(len(v) for v in assignments.values())
        all_scores = [
            sum(c[1] for c in assignments[mid]) for mid in sorted_mids
        ]
        avg_score = sum(all_scores) / len(all_scores) if all_scores else 0
        unassigned = [
            mid for mid in sorted_mids
            if len(assignments.get(mid, [])) < rev_per_ms
        ]

        action_parts = [
            f"Total assignments made: {total_pairs}",
            f"Average assignment score per manuscript: {avg_score:.2f}",
        ]
        if unassigned:
            action_parts.append(
                f"Manuscripts not fully assigned: {', '.join(unassigned)}"
            )
        else:
            action_parts.append("All manuscripts were fully assigned.")
        action_parts.append(
            "Every assignment has been recorded in the editorial system."
        )
        action = "\n".join(action_parts)

        print(f"[verify] Tool calls made: {tool_calls}")
        return self.step(action)
