"""
env.py - Shift Assignment Optimization Task Environment (hardened tool surface)

Hardened surface (M0 + M1 + M4):
  - M1: query_maintenance_logs and list_operators take a single JSON-encoded
    string `filter` parameter; malformed JSON, wrong-typed values, or
    unsupported keys produce recoverable API-style errors.
  - M4: create_shift_assignment takes a deeply nested request payload
    (parent + properties) validated layer by layer with Notion-style error
    messages. The write records each assignment in a shift_assignments
    roster table; step() gained one DB-state criterion for it.
  - Errors never raise; error responses share NO keys with success
    responses.
Task data, ground truth, and all original scoring criteria are unchanged
from the base environment.
"""

import ast
import os
import csv
import json
import glob
import hashlib
import sqlite3
from typing import Tuple, Dict, List, Any


# ── Decorator ─────────────────────────────────────────────────────────────────

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ── Hardened tool-surface helpers ─────────────────────────────────────────────

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


# ── Task Environment ──────────────────────────────────────────────────────────

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

    # ── Helper ────────────────────────────────────────────────────────────

    def _query(self, sql: str, params: tuple = ()) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def _line_exists(self, line_id) -> bool:
        rows = self._query(
            "SELECT 1 FROM machines WHERE production_line = ? LIMIT 1",
            (line_id,))
        return bool(rows)

    def _ensure_roster_table(self, conn) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS shift_assignments ("
            "shift TEXT NOT NULL, "
            "machine_id TEXT NOT NULL, "
            "operator_id TEXT NOT NULL, "
            "PRIMARY KEY (shift, machine_id))"
        )

    # ── Tools ─────────────────────────────────────────────────────────────

    @tool(
        description=(
            "Returns a list of all distinct production line identifiers and "
            "the count of machines on each line."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_production_lines(self) -> List[Dict]:
        return self._query(
            "SELECT production_line, COUNT(*) AS machine_count "
            "FROM machines GROUP BY production_line ORDER BY production_line"
        )

    @tool(
        description=(
            "Returns all machines on a given production line, including "
            "machine_id, machine_name, machine_type, and nominal_throughput."
        ),
        parameters={
            "type": "object",
            "properties": {
                "line_id": {
                    "type": "string",
                    "description": "Production line identifier, e.g. 'L01'.",
                },
            },
            "required": ["line_id"],
        },
    )
    def get_line_machines(self, line_id: Any = None) -> Any:
        if not isinstance(line_id, str) or not line_id:
            return _error(400, "validation_error",
                f"body.line_id should be a non-empty string, instead was "
                f"{_shape(line_id)}.")
        if not self._line_exists(line_id):
            return _error(404, "object_not_found",
                f"Could not find production line with ID: {line_id}.")
        return self._query(
            "SELECT machine_id, machine_name, machine_type, nominal_throughput "
            "FROM machines WHERE production_line = ? ORDER BY machine_id",
            (line_id,),
        )

    @tool(
        description=(
            "Searches maintenance log entries, ordered by log_date "
            "descending. Filtering is expressed as a JSON-encoded string, "
            "e.g. filter='{\"line_id\": \"L01\", \"resolved\": false}'. "
            "Supported filter properties: line_id (production line "
            "identifier string), resolved (boolean), and min_severity "
            "(integer; only entries with severity >= this value are "
            "returned). Each entry includes machine_id, log_date, "
            "event_type, severity, estimated_downtime_hours, and whether "
            "it is resolved."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"line_id\": \"L01\", \"resolved\": false, "
                        "\"min_severity\": 3}'. Pass '{}' or omit for no "
                        "filtering."
                    ),
                },
            },
            "required": [],
        },
    )
    def query_maintenance_logs(self, filter: Any = None) -> Any:
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = ["line_id", "resolved", "min_severity"]
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: line_id, resolved, min_severity.")

        clauses = []
        params: list = []
        if "line_id" in parsed:
            line_id = parsed["line_id"]
            if not isinstance(line_id, str) or not line_id:
                return _error(400, "validation_error",
                    f"body.filter.line_id should be a non-empty string, "
                    f"instead was {_shape(line_id)}.")
            if not self._line_exists(line_id):
                return _error(404, "object_not_found",
                    f"Could not find production line with ID: {line_id}.")
            clauses.append("m.production_line = ?")
            params.append(line_id)
        if "resolved" in parsed:
            resolved = parsed["resolved"]
            if not isinstance(resolved, bool):
                return _error(400, "validation_error",
                    f"body.filter.resolved should be a boolean, instead was "
                    f"{_shape(resolved)}.")
            clauses.append("ml.resolved = ?")
            params.append(int(resolved))
        if "min_severity" in parsed:
            min_sev = parsed["min_severity"]
            if isinstance(min_sev, bool) or not isinstance(min_sev, int):
                return _error(400, "validation_error",
                    f"body.filter.min_severity should be an integer, "
                    f"instead was {_shape(min_sev)}.")
            clauses.append("ml.severity >= ?")
            params.append(min_sev)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return self._query(
            "SELECT ml.machine_id, ml.log_date, ml.event_type, ml.severity, "
            "ml.estimated_downtime_hours, ml.resolved "
            "FROM maintenance_logs ml "
            "JOIN machines m ON ml.machine_id = m.machine_id"
            f"{where} "
            "ORDER BY ml.log_date DESC",
            tuple(params),
        )

    @tool(
        description=(
            "Returns all current (non-expired as of the planning date) "
            "certifications for machines on a given production line. Each "
            "record includes operator_id, machine_id, cert_level, and "
            "expiry_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "line_id": {
                    "type": "string",
                    "description": "Production line identifier, e.g. 'L01'.",
                },
            },
            "required": ["line_id"],
        },
    )
    def get_line_certifications(self, line_id: Any = None) -> Any:
        if not isinstance(line_id, str) or not line_id:
            return _error(400, "validation_error",
                f"body.line_id should be a non-empty string, instead was "
                f"{_shape(line_id)}.")
        if not self._line_exists(line_id):
            return _error(404, "object_not_found",
                f"Could not find production line with ID: {line_id}.")
        # Read planning date from shift_config.json
        cfg_path = os.path.join(self.workspace, "shift_config.json")
        with open(cfg_path) as f:
            planning_date = json.load(f)["planning_date"]
        return self._query(
            "SELECT c.operator_id, c.machine_id, c.cert_level, c.expiry_date "
            "FROM certifications c "
            "JOIN machines m ON c.machine_id = m.machine_id "
            "WHERE m.production_line = ? AND c.expiry_date >= ? "
            "ORDER BY c.machine_id, c.cert_level DESC",
            (line_id, planning_date),
        )

    @tool(
        description=(
            "Returns absence statistics for a batch of operators. For each "
            "operator the response includes operator_id, total_absences "
            "(count of all historical absence records), and "
            "absence_rate (total_absences / 90, rounded to 4 decimal "
            "places). Accepts up to 10 operator IDs per call."
        ),
        parameters={
            "type": "object",
            "properties": {
                "operator_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of operator IDs (max 10), e.g. "
                        "['O001', 'O002']."
                    ),
                },
            },
            "required": ["operator_ids"],
        },
    )
    def get_operator_absence_rates(self, operator_ids: Any = None) -> Any:
        if not isinstance(operator_ids, list) or not operator_ids:
            return _error(400, "validation_error",
                f"body.operator_ids should be a non-empty array of strings, "
                f"instead was {_shape(operator_ids)}.")
        for i, oid in enumerate(operator_ids):
            if not isinstance(oid, str) or not oid:
                return _error(400, "validation_error",
                    f"body.operator_ids[{i}] should be a non-empty string, "
                    f"instead was {_shape(oid)}.")
        if len(operator_ids) > 10:
            return _error(400, "validation_error",
                f"body.operator_ids accepts at most 10 operator IDs per "
                f"call, instead received {len(operator_ids)}.")
        placeholders = ",".join("?" for _ in operator_ids)
        rows = self._query(
            f"SELECT operator_id, COUNT(*) AS total_absences "
            f"FROM absenteeism_records "
            f"WHERE operator_id IN ({placeholders}) AND was_absent = 1 "
            f"GROUP BY operator_id",
            tuple(operator_ids),
        )
        result_map = {r["operator_id"]: r["total_absences"] for r in rows}
        results = []
        for oid in operator_ids:
            total = result_map.get(oid, 0)
            results.append({
                "operator_id": oid,
                "total_absences": total,
                "absence_rate": round(total / 90, 4),
            })
        return results

    @tool(
        description=(
            "Returns basic information for a single operator: operator_id, "
            "name, skill_tier, department, hire_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "operator_id": {
                    "type": "string",
                    "description": "Operator identifier, e.g. 'O001'.",
                },
            },
            "required": ["operator_id"],
        },
    )
    def get_operator_info(self, operator_id: Any = None) -> Dict:
        if not isinstance(operator_id, str) or not operator_id:
            return _error(400, "validation_error",
                f"body.operator_id should be a non-empty string, instead "
                f"was {_shape(operator_id)}.")
        rows = self._query(
            "SELECT operator_id, name, skill_tier, department, hire_date "
            "FROM operators WHERE operator_id = ?",
            (operator_id,),
        )
        if not rows:
            return _error(404, "object_not_found",
                f"Could not find operator with ID: {operator_id}.")
        return rows[0]

    @tool(
        description=(
            "Returns a paginated list of operators. Each page contains up "
            "to 20 operators with operator_id, name, skill_tier, and "
            "department. Filtering is expressed as a JSON-encoded string, "
            "e.g. filter='{\"skill_tier\": \"senior\"}'. Supported filter "
            "properties: skill_tier (junior | mid | senior) and department "
            "(department identifier string)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"skill_tier\": \"senior\", \"department\": "
                        "\"Dept-1\"}'. Pass '{}' or omit for no filtering."
                    ),
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Defaults to 1.",
                },
            },
            "required": [],
        },
    )
    def list_operators(self, filter: Any = None, page: int = 1) -> Dict:
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = ["skill_tier", "department"]
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: skill_tier, department.")

        clauses = []
        params: list = []
        if "skill_tier" in parsed:
            tier = parsed["skill_tier"]
            if not isinstance(tier, str) or tier not in (
                    "junior", "mid", "senior"):
                return _error(400, "validation_error",
                    f"body.filter.skill_tier should be one of \"junior\", "
                    f"\"mid\", \"senior\", instead was {_shape(tier)}.")
            clauses.append("skill_tier = ?")
            params.append(tier)
        if "department" in parsed:
            dept = parsed["department"]
            if not isinstance(dept, str) or not dept:
                return _error(400, "validation_error",
                    f"body.filter.department should be a non-empty string, "
                    f"instead was {_shape(dept)}.")
            clauses.append("department = ?")
            params.append(dept)

        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            return _error(400, "validation_error",
                f"body.page should be a positive integer, instead was "
                f"{_shape(page)}.")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        page_size = 20
        offset = (page - 1) * page_size
        rows = self._query(
            "SELECT operator_id, name, skill_tier, department "
            f"FROM operators{where} ORDER BY operator_id "
            f"LIMIT {page_size} OFFSET {offset}",
            tuple(params),
        )
        total = self._query(
            f"SELECT COUNT(*) AS cnt FROM operators{where}",
            tuple(params))[0]["cnt"]
        return {
            "operators": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description=(
            "Registers one staffing assignment in the plant's central shift "
            "roster system. The request body must contain a `parent` object "
            "identifying the receiving shift roster and a `properties` "
            "object with `Machine` and `Operator` reference properties. "
            "Example body: {\"parent\": {\"type\": \"shift_roster\", "
            "\"shift_id\": \"Morning\"}, \"properties\": {\"Machine\": "
            "{\"type\": \"reference\", \"reference\": {\"machine_id\": "
            "\"M003\"}}, \"Operator\": {\"type\": \"reference\", "
            "\"reference\": {\"operator_id\": \"O012\"}}}}. An optional "
            "`Note` rich_text property may be included in `properties`. On "
            "success the assignment is recorded on the roster for that "
            "shift."
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
                                "The shift roster that receives the "
                                "assignment. Must contain "
                                "type='shift_roster' and a shift_id string."
                            ),
                            "properties": {
                                "type": {"type": "string"},
                                "shift_id": {"type": "string"},
                            },
                            "required": ["type", "shift_id"],
                            "additionalProperties": True,
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Assignment properties. Must include "
                                "'Machine' and 'Operator' reference "
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
    def create_shift_assignment(self, payload: Any = None) -> dict:
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
                f"body.parent should be an object, instead was "
                f"{_shape(parent)}.")
        if parent.get("type") != "shift_roster":
            return _error(400, "validation_error",
                f"body.parent.type should be \"shift_roster\", instead was "
                f"{_shape(parent.get('type'))}.")
        shift_id = parent.get("shift_id")
        if not isinstance(shift_id, str) or not shift_id:
            return _error(400, "validation_error",
                f"body.parent.shift_id should be a non-empty string, "
                f"instead was {_shape(shift_id)}.")

        props = payload.get("properties")
        if props is None:
            return _error(400, "validation_error",
                "body.properties should be defined, instead was "
                "'undefined'.")
        if not isinstance(props, dict):
            return _error(400, "validation_error",
                f"body.properties should be an object, instead was "
                f"{_shape(props)}.")

        refs = {}
        for prop_name, id_field in (("Machine", "machine_id"),
                                    ("Operator", "operator_id")):
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
                    f"body.properties.{prop_name}.type should be "
                    f"\"reference\", instead was "
                    f"{_shape(prop.get('type'))}.")
            reference = prop.get("reference")
            if not isinstance(reference, dict):
                return _error(400, "validation_error",
                    f"body.properties.{prop_name}.reference should be an "
                    f"object, instead was {_shape(reference)}.")
            ref_id = reference.get(id_field)
            if not isinstance(ref_id, str) or not ref_id:
                return _error(400, "validation_error",
                    f"body.properties.{prop_name}.reference.{id_field} "
                    f"should be a non-empty string, instead was "
                    f"{_shape(ref_id)}.")
            refs[id_field] = ref_id

        note_prop = props.get("Note")
        if note_prop is not None:
            if (not isinstance(note_prop, dict)
                    or note_prop.get("type") != "rich_text"):
                return _error(400, "validation_error",
                    "body.properties.Note.type should be \"rich_text\".")
            rich = note_prop.get("rich_text")
            if not isinstance(rich, list):
                return _error(400, "validation_error",
                    f"body.properties.Note.rich_text should be an array, "
                    f"instead was {_shape(rich)}.")
            for i, item in enumerate(rich):
                if (not isinstance(item, dict)
                        or not isinstance(item.get("text"), dict)
                        or not isinstance(item["text"].get("content"), str)):
                    return _error(400, "validation_error",
                        f"body.properties.Note.rich_text[{i}].text.content "
                        f"should be a string, instead was 'undefined'.")

        machine_id = refs["machine_id"]
        operator_id = refs["operator_id"]

        # --- Business validation ---
        cfg_path = os.path.join(self.workspace, "shift_config.json")
        with open(cfg_path) as f:
            shift_order = json.load(f)["shift_order"]
        if shift_id not in shift_order:
            return _error(404, "object_not_found",
                f"Could not find shift roster with ID: {shift_id}.")

        conn = sqlite3.connect(self.db_path)
        try:
            c = conn.cursor()
            c.execute("SELECT 1 FROM machines WHERE machine_id = ?",
                      (machine_id,))
            if c.fetchone() is None:
                return _error(404, "object_not_found",
                    f"Could not find machine with ID: {machine_id}.")
            c.execute("SELECT 1 FROM operators WHERE operator_id = ?",
                      (operator_id,))
            if c.fetchone() is None:
                return _error(404, "object_not_found",
                    f"Could not find operator with ID: {operator_id}.")

            self._ensure_roster_table(conn)
            c.execute(
                "SELECT operator_id FROM shift_assignments "
                "WHERE shift = ? AND machine_id = ?",
                (shift_id, machine_id))
            existing = c.fetchone()
            if existing is not None:
                return _error(400, "validation_error",
                    f"Machine '{machine_id}' already has an assignment "
                    f"recorded on the '{shift_id}' roster "
                    f"(operator '{existing[0]}').")

            # --- Perform the write ---
            c.execute(
                "INSERT INTO shift_assignments (shift, machine_id, "
                "operator_id) VALUES (?, ?, ?)",
                (shift_id, machine_id, operator_id))
            conn.commit()
        finally:
            conn.close()

        # Success response: deep echo, shape entirely different from errors.
        return {
            "object": "assignment",
            "id": "asg_" + hashlib.md5(
                f"{shift_id}:{machine_id}:{operator_id}".encode()
            ).hexdigest()[:10],
            "parent": {"type": "shift_roster", "shift_id": shift_id},
            "properties": {
                "Machine": {"type": "reference",
                            "reference": {"machine_id": machine_id}},
                "Operator": {"type": "reference",
                             "reference": {"operator_id": operator_id}},
                "Status": {"type": "select",
                           "select": {"name": "recorded"}},
            },
            "created": True,
        }

    # ── Ground-truth computation (shared by step & verify) ────────────────

    def _compute_ground_truth(self) -> Dict:
        """Compute the deterministic optimal staffing plan.

        Algorithm:
        1. Read staffing rules and shift config from workspace.
        2. Read production targets and operator availability from workspace.
        3. Query DB for machines, maintenance, certifications, absences.
        4. For each shift (in shift_order), for each line sorted by priority
           (critical > high > medium > low, ties broken by line_id asc):
             a. Identify operational machines (exclude machines with any
                unresolved maintenance event of severity >= threshold).
             b. For each operational machine (sorted by machine_id asc):
                  - Find certified operators (cert_level >= min_cert;
                    for critical/high priority lines, cert_level >=
                    high_priority_min_cert).
                  - Filter to those available this shift.
                  - Exclude those with absence_rate > max_absence_rate.
                  - Sort by cert_level DESC, absence_rate ASC,
                    operator_id ASC.
                  - Assign the first operator not already assigned this shift.
        5. Return assignments and summary.
        """
        import yaml as _yaml

        # --- Read workspace config ---
        with open(os.path.join(self.workspace, "staffing_rules.yaml")) as f:
            rules = _yaml.safe_load(f)
        with open(os.path.join(self.workspace, "shift_config.json")) as f:
            shift_cfg = json.load(f)

        planning_date = shift_cfg["planning_date"]
        shift_order = shift_cfg["shift_order"]
        priority_order = rules["priority_order"]
        min_cert = rules["min_cert_level"]
        high_cert = rules["high_priority_min_cert"]
        max_abs = rules["max_absence_rate"]
        sev_thresh = rules["maintenance_severity_threshold"]

        # --- Read production targets ---
        targets = {}  # (line_id, shift) -> {target_units, priority}
        for fp in sorted(glob.glob(os.path.join(
                self.workspace, "production_targets", "*.csv"))):
            with open(fp) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (row["production_line"], row["shift"])
                    targets[key] = {
                        "target_units": int(row["target_units"]),
                        "priority": row["priority"],
                    }

        # --- Read operator availability ---
        availability = {}  # operator_id -> set of shifts
        for fp in sorted(glob.glob(os.path.join(
                self.workspace, "operator_availability", "*.json"))):
            with open(fp) as f:
                data = json.load(f)
            for entry in data["operators"]:
                availability[entry["operator_id"]] = set(
                    entry["available_shifts"])

        # --- Query DB ---
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Machines by line
        machines_by_line = {}
        for row in c.execute(
                "SELECT machine_id, production_line, machine_type, "
                "nominal_throughput FROM machines ORDER BY machine_id"):
            r = dict(row)
            machines_by_line.setdefault(r["production_line"], []).append(r)

        # Down machines: any unresolved event with severity >= threshold
        down_machines = set()
        for row in c.execute(
                "SELECT DISTINCT machine_id FROM maintenance_logs "
                "WHERE resolved = 0 AND severity >= ?",
                (sev_thresh,)):
            down_machines.add(row[0])

        # Certifications (non-expired)
        certs = {}  # machine_id -> [(operator_id, cert_level)]
        for row in c.execute(
                "SELECT operator_id, machine_id, cert_level FROM certifications "
                "WHERE expiry_date >= ? ORDER BY machine_id",
                (planning_date,)):
            r = dict(row)
            certs.setdefault(r["machine_id"], []).append(
                (r["operator_id"], r["cert_level"]))

        # Absence rates
        absence_counts = {}
        for row in c.execute(
                "SELECT operator_id, COUNT(*) AS cnt FROM absenteeism_records "
                "WHERE was_absent = 1 GROUP BY operator_id"):
            absence_counts[dict(row)["operator_id"]] = dict(row)["cnt"]

        # Operator names
        op_names = {}
        for row in c.execute("SELECT operator_id, name FROM operators"):
            op_names[dict(row)["operator_id"]] = dict(row)["name"]

        conn.close()

        # --- Compute absence rates ---
        absence_rates = {}
        for oid in availability:
            absence_rates[oid] = round(absence_counts.get(oid, 0) / 90, 4)

        # --- Determine all unique lines ---
        all_lines = sorted(machines_by_line.keys())

        # --- Build line priority map (from targets for any shift) ---
        line_priority = {}
        for (lid, _), info in targets.items():
            line_priority[lid] = info["priority"]

        # --- Assignment algorithm ---
        assignments = []  # list of dicts
        uncovered = []    # (shift, line, machine_id, reason)

        for shift in shift_order:
            assigned_this_shift = set()

            # Sort lines by priority then line_id
            def line_sort_key(lid):
                p = line_priority.get(lid, "low")
                return (priority_order.index(p), lid)

            sorted_lines = sorted(all_lines, key=line_sort_key)

            for lid in sorted_lines:
                prio = line_priority.get(lid, "low")
                req_cert = (high_cert
                            if prio in ("critical", "high") else min_cert)

                operational = [
                    m for m in machines_by_line.get(lid, [])
                    if m["machine_id"] not in down_machines
                ]
                operational.sort(key=lambda m: m["machine_id"])

                for mach in operational:
                    mid = mach["machine_id"]
                    # Skip if no target for this line/shift
                    if (lid, shift) not in targets:
                        continue

                    # Get certified operators
                    candidates = []
                    for oid, clevel in certs.get(mid, []):
                        if clevel < req_cert:
                            continue
                        if oid not in availability:
                            continue
                        if shift not in availability[oid]:
                            continue
                        if absence_rates.get(oid, 0) > max_abs:
                            continue
                        if oid in assigned_this_shift:
                            continue
                        candidates.append((oid, clevel,
                                           absence_rates.get(oid, 0)))

                    # Sort: cert_level DESC, absence_rate ASC, op_id ASC
                    candidates.sort(key=lambda x: (-x[1], x[2], x[0]))

                    if candidates:
                        best_oid, best_cert, best_abs = candidates[0]
                        assignments.append({
                            "shift": shift,
                            "production_line": lid,
                            "machine_id": mid,
                            "operator_id": best_oid,
                            "operator_name": op_names.get(best_oid, ""),
                            "cert_level": best_cert,
                            "absence_rate": f"{best_abs:.2f}",
                        })
                        assigned_this_shift.add(best_oid)
                    else:
                        uncovered.append((shift, lid, mid,
                                          "no eligible operator"))

        # --- Coverage summary ---
        total_slots = 0
        covered_slots = 0
        coverage_by_shift_line = {}
        for shift in shift_order:
            for lid in sorted(all_lines):
                operational = [
                    m for m in machines_by_line.get(lid, [])
                    if m["machine_id"] not in down_machines
                    and (lid, shift) in targets
                ]
                n_op = len(operational)
                n_cov = len([a for a in assignments
                             if a["shift"] == shift
                             and a["production_line"] == lid])
                total_slots += n_op
                covered_slots += n_cov
                coverage_by_shift_line[(shift, lid)] = (n_cov, n_op)

        down_list = sorted(down_machines)
        coverage_pct = (round(covered_slots / total_slots * 100, 1)
                        if total_slots > 0 else 0.0)

        return {
            "assignments": assignments,
            "uncovered": uncovered,
            "down_machines": down_list,
            "total_assignments": len(assignments),
            "total_slots": total_slots,
            "covered_slots": covered_slots,
            "coverage_pct": coverage_pct,
            "coverage_by_shift_line": coverage_by_shift_line,
            "shift_order": shift_order,
            "all_lines": all_lines,
            "priority_order": priority_order,
            "line_priority": line_priority,
        }

    # ── Evaluation ────────────────────────────────────────────────────────

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
        gt = self._compute_ground_truth()
        criteria = {}

        # ── C1: staffing_plan.csv exists with correct columns (15 pts) ──
        plan_path = os.path.join(self.workspace, "staffing_plan.csv")
        c1_score = 0
        c1_max = 15
        c1_reason = ""
        expected_cols = ["shift", "production_line", "machine_id",
                         "operator_id", "operator_name", "cert_level",
                         "absence_rate"]
        if os.path.isfile(plan_path):
            with open(plan_path) as f:
                reader = csv.DictReader(f)
                plan_rows = list(reader)
                actual_cols = reader.fieldnames or []
            if set(expected_cols).issubset(set(actual_cols)):
                c1_score = c1_max
            else:
                missing = set(expected_cols) - set(actual_cols)
                c1_reason = f"Missing columns: {missing}"
                c1_score = 5
        else:
            c1_reason = "staffing_plan.csv not found"
            plan_rows = []

        criteria["staffing_plan_format"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
        }
        if c1_reason:
            criteria["staffing_plan_format"]["reason"] = c1_reason

        # ── C2: Correct assignments (25 pts) ──
        c2_max = 25
        gt_set = set()
        for a in gt["assignments"]:
            gt_set.add((a["shift"], a["production_line"],
                        a["machine_id"], a["operator_id"]))

        agent_set = set()
        for r in plan_rows:
            agent_set.add((r.get("shift", ""), r.get("production_line", ""),
                           r.get("machine_id", ""), r.get("operator_id", "")))

        if gt_set:
            correct = len(gt_set & agent_set)
            c2_score = round(c2_max * correct / len(gt_set))
        else:
            c2_score = c2_max if not agent_set else 0

        c2_reason = ""
        if c2_score < c2_max:
            c2_reason = (f"{correct}/{len(gt_set)} assignments match "
                         f"ground truth")

        criteria["correct_assignments"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
        }
        if c2_reason:
            criteria["correct_assignments"]["reason"] = c2_reason

        # ── C3: No certification violations (15 pts) ──
        import yaml as _yaml
        c3_max = 15
        with open(os.path.join(self.workspace, "staffing_rules.yaml")) as f:
            rules = _yaml.safe_load(f)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        with open(os.path.join(self.workspace, "shift_config.json")) as f:
            planning_date = json.load(f)["planning_date"]

        cert_map = {}
        for row in conn.execute(
                "SELECT operator_id, machine_id, cert_level "
                "FROM certifications WHERE expiry_date >= ?",
                (planning_date,)):
            cert_map[(row[0], row[1])] = row[2]

        line_map = {}
        for row in conn.execute(
                "SELECT machine_id, production_line FROM machines"):
            line_map[row[0]] = row[1]

        conn.close()

        violations = 0
        for r in plan_rows:
            oid = r.get("operator_id", "")
            mid = r.get("machine_id", "")
            clevel = cert_map.get((oid, mid), 0)
            lid = line_map.get(mid, "")
            prio = gt["line_priority"].get(lid, "low")
            req = (rules["high_priority_min_cert"]
                   if prio in ("critical", "high")
                   else rules["min_cert_level"])
            if clevel < req:
                violations += 1

        if plan_rows:
            c3_score = c3_max if violations == 0 else max(
                0, c3_max - violations * 3)
        else:
            c3_score = 0
        c3_reason = ""
        if violations:
            c3_reason = f"{violations} certification violation(s)"

        criteria["no_cert_violations"] = {
            "passed": violations == 0 and len(plan_rows) > 0,
            "score": c3_score,
            "max_score": c3_max,
        }
        if c3_reason:
            criteria["no_cert_violations"]["reason"] = c3_reason

        # ── C4: No maintenance-down machines assigned (15 pts) ──
        c4_max = 15
        down_assigned = 0
        for r in plan_rows:
            if r.get("machine_id", "") in gt["down_machines"]:
                down_assigned += 1

        c4_score = c4_max if down_assigned == 0 and len(plan_rows) > 0 else (
            max(0, c4_max - down_assigned * 5) if plan_rows else 0)
        c4_reason = ""
        if down_assigned:
            c4_reason = f"{down_assigned} assignment(s) to down machines"

        criteria["no_down_machine_assignments"] = {
            "passed": down_assigned == 0 and len(plan_rows) > 0,
            "score": c4_score,
            "max_score": c4_max,
        }
        if c4_reason:
            criteria["no_down_machine_assignments"]["reason"] = c4_reason

        # ── C5: coverage_summary.txt exists and accurate (15 pts) ──
        c5_max = 15
        summary_path = os.path.join(self.workspace, "coverage_summary.txt")
        c5_score = 0
        c5_reason = ""
        if os.path.isfile(summary_path):
            with open(summary_path) as f:
                summary_text = f.read()
            # Check that coverage percentage appears
            pct_str = f"{gt['coverage_pct']}"
            if pct_str in summary_text:
                c5_score += 8
            else:
                c5_reason = f"Coverage percentage {pct_str}% not found"
            # Check total assignments count
            total_str = str(gt["total_assignments"])
            if total_str in summary_text:
                c5_score += 7
            elif not c5_reason:
                c5_reason = f"Total assignments {total_str} not found"
        else:
            c5_reason = "coverage_summary.txt not found"

        criteria["coverage_summary"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
        }
        if c5_reason:
            criteria["coverage_summary"]["reason"] = c5_reason

        # ── C6: Response text contains correct stats (15 pts) ──
        c6_max = 15
        c6_score = 0
        c6_reason = ""
        action_lower = action.lower() if action else ""

        # Check total assignments mentioned
        if str(gt["total_assignments"]) in action:
            c6_score += 5
        else:
            c6_reason = (f"Total assignments ({gt['total_assignments']}) "
                         f"not in response")

        # Check coverage percentage mentioned
        if f"{gt['coverage_pct']}" in action:
            c6_score += 5
        elif not c6_reason:
            c6_reason = f"Coverage pct ({gt['coverage_pct']}%) not in response"

        # Check down machine count or listing mentioned
        if str(len(gt["down_machines"])) in action:
            c6_score += 5
        elif any(m in action for m in gt["down_machines"]):
            c6_score += 3
        elif not c6_reason:
            c6_reason = "Down machine info not in response"

        criteria["response_statistics"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
        }
        if c6_reason:
            criteria["response_statistics"]["reason"] = c6_reason

        # ── C7: Assignments recorded in the roster system (15 pts) ──
        # (M4 DB-state criterion: added with the create_shift_assignment
        # write tool; all other criteria are unchanged from SOURCE.)
        c7_max = 15
        conn = sqlite3.connect(self.db_path)
        self._ensure_roster_table(conn)
        db_set = set()
        for row in conn.execute(
                "SELECT shift, machine_id, operator_id "
                "FROM shift_assignments"):
            db_set.add((row[0], row[1], row[2]))
        conn.close()

        gt_triples = set()
        for a in gt["assignments"]:
            gt_triples.add((a["shift"], a["machine_id"], a["operator_id"]))

        if gt_triples:
            db_ok = len(gt_triples & db_set)
            c7_score = round(c7_max * db_ok / len(gt_triples))
            c7_reason = ("" if db_ok == len(gt_triples)
                         else f"{db_ok}/{len(gt_triples)} assignments "
                              f"recorded in roster system")
        else:
            c7_score = c7_max if not db_set else 0
            c7_reason = ""

        criteria["db_assignments_recorded"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
        }
        if c7_reason:
            criteria["db_assignments_recorded"]["reason"] = c7_reason

        # ── Aggregate ─────────────────────────────────────────────────────
        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score, info

    # ── Verification ──────────────────────────────────────────────────────

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
        for query_maintenance_logs / list_operators and nested request
        payloads for create_shift_assignment.
        """
        import yaml as _yaml

        tool_calls = 0

        def call_tool(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        def is_err(resp) -> bool:
            return isinstance(resp, dict) and resp.get("object") == "error"

        # 1. Read workspace config files
        with open(os.path.join(self.workspace, "staffing_rules.yaml")) as f:
            rules = _yaml.safe_load(f)
        with open(os.path.join(self.workspace, "shift_config.json")) as f:
            shift_cfg = json.load(f)

        planning_date = shift_cfg["planning_date"]
        shift_order = shift_cfg["shift_order"]
        priority_order = rules["priority_order"]
        min_cert = rules["min_cert_level"]
        high_cert = rules["high_priority_min_cert"]
        max_abs = rules["max_absence_rate"]
        sev_thresh = rules["maintenance_severity_threshold"]

        # 2. Read production targets from workspace
        targets = {}
        for fp in sorted(glob.glob(os.path.join(
                self.workspace, "production_targets", "*.csv"))):
            with open(fp) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (row["production_line"], row["shift"])
                    targets[key] = {
                        "target_units": int(row["target_units"]),
                        "priority": row["priority"],
                    }

        # 3. Read operator availability from workspace
        availability = {}
        for fp in sorted(glob.glob(os.path.join(
                self.workspace, "operator_availability", "*.json"))):
            with open(fp) as f:
                data = json.load(f)
            for entry in data["operators"]:
                availability[entry["operator_id"]] = set(
                    entry["available_shifts"])

        # 4. Get production lines via tool
        lines_info = call_tool("list_production_lines")
        all_lines = [r["production_line"] for r in lines_info]

        # 5. For each line, get machines, maintenance, certifications via tools
        line_machines = {}
        down_machines = set()
        line_certs = {}

        for lid in all_lines:
            machines = call_tool("get_line_machines", line_id=lid)
            assert not is_err(machines), machines
            line_machines[lid] = machines

            # Maintenance search: JSON-encoded string filter (M1 surface).
            maint = call_tool(
                "query_maintenance_logs",
                filter=json.dumps({"line_id": lid, "resolved": False}))
            assert not is_err(maint), maint
            for entry in maint:
                if entry["severity"] >= sev_thresh:
                    down_machines.add(entry["machine_id"])

            certs = call_tool("get_line_certifications", line_id=lid)
            assert not is_err(certs), certs
            line_certs[lid] = certs

        # 6. Get operator names via paginated list (JSON-string filter)
        op_names = {}
        page = 1
        while True:
            result = call_tool("list_operators",
                               filter=json.dumps({}), page=page)
            assert not is_err(result), result
            for op in result["operators"]:
                op_names[op["operator_id"]] = op["name"]
            if page >= result["total_pages"]:
                break
            page += 1

        # 7. Get absence rates for all relevant operators
        relevant_ops = set()
        for lid in all_lines:
            for cert in line_certs.get(lid, []):
                relevant_ops.add(cert["operator_id"])

        absence_rates = {}
        relevant_list = sorted(relevant_ops)
        for i in range(0, len(relevant_list), 10):
            batch = relevant_list[i:i + 10]
            rates = call_tool("get_operator_absence_rates",
                              operator_ids=batch)
            assert not is_err(rates), rates
            for r in rates:
                absence_rates[r["operator_id"]] = r["absence_rate"]

        # 8. Build certification lookup: machine_id -> [(op_id, cert_level)]
        cert_lookup = {}
        for lid in all_lines:
            for cert in line_certs.get(lid, []):
                cert_lookup.setdefault(cert["machine_id"], []).append(
                    (cert["operator_id"], cert["cert_level"]))

        # 9. Line priority map
        line_priority = {}
        for (lid, _), info in targets.items():
            line_priority[lid] = info["priority"]

        # 10. Run deterministic assignment
        assignments = []
        uncovered = []

        for shift in shift_order:
            assigned_this_shift = set()

            def line_sort_key(lid):
                p = line_priority.get(lid, "low")
                return (priority_order.index(p)
                        if p in priority_order else 999, lid)

            sorted_lines = sorted(all_lines, key=line_sort_key)

            for lid in sorted_lines:
                prio = line_priority.get(lid, "low")
                req_cert = high_cert if prio in ("critical", "high") else min_cert

                operational = [
                    m for m in line_machines.get(lid, [])
                    if m["machine_id"] not in down_machines
                ]
                operational.sort(key=lambda m: m["machine_id"])

                for mach in operational:
                    mid = mach["machine_id"]
                    if (lid, shift) not in targets:
                        continue

                    candidates = []
                    for oid, clevel in cert_lookup.get(mid, []):
                        if clevel < req_cert:
                            continue
                        if oid not in availability:
                            continue
                        if shift not in availability[oid]:
                            continue
                        if absence_rates.get(oid, 0) > max_abs:
                            continue
                        if oid in assigned_this_shift:
                            continue
                        candidates.append(
                            (oid, clevel, absence_rates.get(oid, 0)))

                    candidates.sort(key=lambda x: (-x[1], x[2], x[0]))

                    if candidates:
                        best_oid, best_cert, best_abs = candidates[0]
                        assignments.append({
                            "shift": shift,
                            "production_line": lid,
                            "machine_id": mid,
                            "operator_id": best_oid,
                            "operator_name": op_names.get(best_oid, ""),
                            "cert_level": best_cert,
                            "absence_rate": f"{best_abs:.2f}",
                        })
                        assigned_this_shift.add(best_oid)
                    else:
                        uncovered.append((shift, lid, mid,
                                          "no eligible operator"))

        # 11. Record each assignment in the roster system via nested payloads
        for a in assignments:
            resp = call_tool(
                "create_shift_assignment",
                payload={
                    "parent": {"type": "shift_roster",
                               "shift_id": a["shift"]},
                    "properties": {
                        "Machine": {
                            "type": "reference",
                            "reference": {"machine_id": a["machine_id"]},
                        },
                        "Operator": {
                            "type": "reference",
                            "reference": {"operator_id": a["operator_id"]},
                        },
                    },
                },
            )
            assert (isinstance(resp, dict)
                    and resp.get("object") == "assignment"
                    and resp.get("created")), resp

        # 12. Write staffing_plan.csv
        plan_path = os.path.join(self.workspace, "staffing_plan.csv")
        with open(plan_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "shift", "production_line", "machine_id",
                "operator_id", "operator_name", "cert_level",
                "absence_rate",
            ])
            writer.writeheader()
            writer.writerows(assignments)

        # 13. Compute coverage
        total_slots = 0
        covered_slots = len(assignments)
        for shift in shift_order:
            for lid in sorted(all_lines):
                operational = [
                    m for m in line_machines.get(lid, [])
                    if m["machine_id"] not in down_machines
                    and (lid, shift) in targets
                ]
                total_slots += len(operational)

        coverage_pct = (round(covered_slots / total_slots * 100, 1)
                        if total_slots > 0 else 0.0)

        # 14. Write coverage_summary.txt
        summary_path = os.path.join(self.workspace, "coverage_summary.txt")
        with open(summary_path, "w") as f:
            f.write("Shift Staffing Coverage Summary\n")
            f.write(f"Planning Date: {planning_date}\n")
            f.write(f"Total Assignments: {len(assignments)}\n\n")
            for shift in shift_order:
                f.write(f"Shift: {shift}\n")
                for lid in sorted(all_lines):
                    operational = [
                        m for m in line_machines.get(lid, [])
                        if m["machine_id"] not in down_machines
                        and (lid, shift) in targets
                    ]
                    n_op = len(operational)
                    n_cov = len([a for a in assignments
                                 if a["shift"] == shift
                                 and a["production_line"] == lid])
                    prio = line_priority.get(lid, "low")
                    f.write(f"  Line {lid} ({prio}): "
                            f"{n_cov}/{n_op} machines covered\n")
                f.write("\n")

            f.write(f"Machines under maintenance: "
                    f"{', '.join(sorted(down_machines))}\n")
            if uncovered:
                f.write("\nUncovered machine-shift slots:\n")
                for shift, lid, mid, reason in uncovered:
                    f.write(f"  {shift} / {lid} / {mid}: {reason}\n")

            f.write(f"\nOverall coverage: {covered_slots}/{total_slots} "
                    f"({coverage_pct}%)\n")

        # 15. Construct action string
        action_parts = [
            f"Staffing plan generated for {planning_date}.",
            f"Total assignments: {len(assignments)}.",
            f"Overall coverage: {covered_slots}/{total_slots} "
            f"({coverage_pct}%).",
            f"Machines under maintenance ({len(sorted(down_machines))}): "
            f"{', '.join(sorted(down_machines))}.",
            "All assignments have been recorded in the shift roster system.",
        ]
        if uncovered:
            action_parts.append("Uncovered slots:")
            for shift, lid, mid, reason in uncovered:
                action_parts.append(f"  {shift} / {lid} / {mid}: {reason}")

        action = "\n".join(action_parts)

        assert tool_calls >= 15, (
            f"verify used only {tool_calls} tool calls, need >= 15")
        print(f"[verify] total tool calls: {tool_calls}")

        return self.step(action)
