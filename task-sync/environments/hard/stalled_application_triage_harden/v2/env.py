"""
Environment for visa application triage task (hardened tool surface).

Hardened surface (M0 + M1 + M4):
  - M0: prompt.md specifies goal + deliverable contract only; the triage
    procedure lives in workspace policy documents (triage_methodology.md,
    stall_criteria.json, priority_scoring_rules.yaml,
    visa_processing_standards.csv).
  - M1: search_applicants collapses its filters into a single JSON-encoded
    string `filter` parameter; malformed JSON or unsupported/wrong-typed
    keys produce recoverable API-style errors.
  - M4: create_intervention takes a deeply nested request payload
    (parent + properties) validated layer by layer with Notion-style error
    messages, and records the intervention in the database. step() gained
    one DB-state criterion for these recordings; all original criteria and
    the ground truth are unchanged.
Tools never raise; failures return error objects whose shape shares no
data keys with success responses.
"""

import ast
import csv
import hashlib
import json
import os
import sqlite3
from datetime import datetime
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

    # ── Tool Methods ──────────────────────────────────────────────────────

    @tool(
        description=(
            "Search for visa applicants. Returns paginated results (max 20 per "
            "page) with applicant_id, full_name, visa_category, priority_level, "
            "embassy_id, submission_date, current_status. Filtering is expressed "
            "as a JSON-encoded string, e.g. "
            "filter='{\"status\": \"pending\", \"embassy_id\": \"EMB_001\"}'. "
            "Supported filter properties: status (pending | in_review | on_hold "
            "| awaiting_documents | approved | denied), visa_category "
            "(diplomatic | employment | business | student | family_reunion | "
            "tourist), embassy_id (e.g. 'EMB_001'), priority_level (critical | "
            "high | medium | low)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"status\": \"on_hold\", \"priority_level\": \"high\"}'. "
                        "Pass '{}' or omit for no filtering."
                    ),
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20). Default 20.",
                },
            },
            "required": [],
        },
    )
    def search_applicants(
        self,
        filter: Any = None,
        page: int = 1,
        page_size: int = 20,
    ):
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = ("status", "visa_category", "embassy_id", "priority_level")
        for key in parsed:
            if key not in supported:
                return _error(
                    400,
                    "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: {', '.join(supported)}.",
                )

        allowed_values = {
            "status": ("pending", "in_review", "on_hold", "awaiting_documents",
                       "approved", "denied"),
            "visa_category": ("diplomatic", "employment", "business", "student",
                              "family_reunion", "tourist"),
            "priority_level": ("critical", "high", "medium", "low"),
        }

        clauses = {"status": "current_status", "visa_category": "visa_category",
                   "embassy_id": "embassy_id", "priority_level": "priority_level"}
        conditions = []
        params = []
        for key in supported:
            if key not in parsed:
                continue
            value = parsed[key]
            if key in allowed_values:
                if not isinstance(value, str) or value not in allowed_values[key]:
                    choices = ", ".join(f'"{v}"' for v in allowed_values[key])
                    return _error(
                        400,
                        "validation_error",
                        f"body.filter.{key} should be one of {choices}, "
                        f"instead was {_shape(value)}.",
                    )
            else:
                if not isinstance(value, str) or not value:
                    return _error(
                        400,
                        "validation_error",
                        f"body.filter.{key} should be a non-empty string, "
                        f"instead was {_shape(value)}.",
                    )
            conditions.append(f"{clauses[key]} = ?")
            params.append(value)

        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            return _error(
                400,
                "validation_error",
                f"body.page should be a positive integer, instead was {_shape(page)}.",
            )
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
            return _error(
                400,
                "validation_error",
                f"body.page_size should be a positive integer, instead was "
                f"{_shape(page_size)}.",
            )

        page_size = min(page_size, 20)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        query = "SELECT * FROM applicants WHERE 1=1"
        for cond in conditions:
            query += f" AND {cond}"

        # Get total count
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        c.execute(count_query, params)
        total = c.fetchone()[0]

        query += " ORDER BY applicant_id ASC LIMIT ? OFFSET ?"
        params.extend([page_size, (page - 1) * page_size])
        c.execute(query, params)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()

        return {
            "results": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get detailed information for a specific applicant by their ID.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The applicant ID (e.g. 'APP_00001')",
                },
            },
            "required": ["applicant_id"],
        },
    )
    def get_applicant_details(self, applicant_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM applicants WHERE applicant_id = ?", (applicant_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
        return _error(404, "object_not_found",
                      f"Could not find applicant with ID: {applicant_id}.")

    @tool(
        description="Retrieve all biometric submissions for a given applicant. Returns bio_id, bio_type, capture_date, quality_score, status, expiry_date.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The applicant ID",
                },
            },
            "required": ["applicant_id"],
        },
    )
    def get_biometric_status(self, applicant_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM biometric_submissions WHERE applicant_id = ? ORDER BY capture_date DESC",
            (applicant_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"applicant_id": applicant_id, "biometrics": rows}

    @tool(
        description="Retrieve all document verification records for a given applicant, including any flags.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The applicant ID",
                },
            },
            "required": ["applicant_id"],
        },
    )
    def get_document_flags(self, applicant_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM document_verifications WHERE applicant_id = ? ORDER BY doc_id",
            (applicant_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"applicant_id": applicant_id, "documents": rows}

    @tool(
        description="Retrieve all embassy appointment records for a given applicant.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The applicant ID",
                },
            },
            "required": ["applicant_id"],
        },
    )
    def get_appointment_history(self, applicant_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM embassy_appointments WHERE applicant_id = ? ORDER BY scheduled_date DESC",
            (applicant_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"applicant_id": applicant_id, "appointments": rows}

    @tool(
        description="Get visa quota utilization for a specific visa category and embassy in a given quarter.",
        parameters={
            "type": "object",
            "properties": {
                "visa_category": {
                    "type": "string",
                    "description": "Visa category (e.g. 'employment')",
                },
                "embassy_id": {
                    "type": "string",
                    "description": "Embassy ID (e.g. 'EMB_001')",
                },
                "quarter": {
                    "type": "string",
                    "description": "Fiscal quarter (e.g. 'Q2'). Default is 'Q2'.",
                },
            },
            "required": ["visa_category", "embassy_id"],
        },
    )
    def get_visa_quota(self, visa_category: str, embassy_id: str, quarter: str = "Q2"):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM visa_quotas WHERE visa_category = ? AND embassy_id = ? AND quarter = ?",
            (visa_category, embassy_id, quarter),
        )
        row = c.fetchone()
        conn.close()
        if row:
            d = dict(row)
            d["utilization_pct"] = round(d["used_count"] / d["allocated_quota"] * 100, 2) if d["allocated_quota"] > 0 else 0
            return d
        return _error(
            404, "object_not_found",
            f"Could not find quota record with ID: {visa_category}/{embassy_id}/{quarter}.")

    @tool(
        description="List all embassy IDs in the system.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_embassies(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT DISTINCT embassy_id FROM applicants ORDER BY embassy_id")
        embassies = [r[0] for r in c.fetchall()]
        conn.close()
        return {"embassies": embassies}

    @tool(
        description="List all visa categories in the system.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_visa_categories(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT DISTINCT visa_category FROM applicants ORDER BY visa_category")
        cats = [r[0] for r in c.fetchall()]
        conn.close()
        return {"visa_categories": cats}

    @tool(
        description=(
            "Files an intervention request in the case management system: "
            "records that a stalled application needs urgent case-officer "
            "attention. The request body must contain a `parent` object "
            "identifying the receiving embassy queue and a `properties` object "
            "with an `Applicant` reference property and an `Action` select "
            "property carrying the recommended action. Example body: "
            "{\"parent\": {\"type\": \"embassy_queue\", \"embassy_id\": "
            "\"EMB_003\"}, \"properties\": {\"Applicant\": {\"type\": "
            "\"reference\", \"reference\": {\"applicant_id\": \"APP_00042\"}}, "
            "\"Action\": {\"type\": \"select\", \"select\": {\"name\": "
            "\"Expedite document review\"}}}}. An optional `Note` rich_text "
            "property may be included in `properties`. The request must be "
            "filed to the queue of the embassy that owns the application. "
            "Filing again for the same applicant replaces the earlier request."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "The intervention request body.",
                    "properties": {
                        "parent": {
                            "type": "object",
                            "description": (
                                "The embassy queue that receives the request. "
                                "Must contain type='embassy_queue' and an "
                                "embassy_id string."
                            ),
                            "properties": {
                                "type": {"type": "string"},
                                "embassy_id": {"type": "string"},
                            },
                            "required": ["type", "embassy_id"],
                            "additionalProperties": True,
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Request properties. Must include an 'Applicant' "
                                "reference property and an 'Action' select "
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
    def create_intervention(self, payload: Any = None):
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
        if parent.get("type") != "embassy_queue":
            return _error(
                400, "validation_error",
                f"body.parent.type should be \"embassy_queue\", instead was "
                f"{_shape(parent.get('type'))}.",
            )
        embassy_id = parent.get("embassy_id")
        if not isinstance(embassy_id, str) or not embassy_id:
            return _error(
                400, "validation_error",
                f"body.parent.embassy_id should be a non-empty string, instead was "
                f"{_shape(embassy_id)}.",
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

        applicant_prop = props.get("Applicant")
        if applicant_prop is None:
            return _error(
                400, "validation_error",
                "body.properties.Applicant should be defined, instead was 'undefined'.",
            )
        if not isinstance(applicant_prop, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Applicant should be an object, instead was "
                f"{_shape(applicant_prop)}.",
            )
        if applicant_prop.get("type") != "reference":
            return _error(
                400, "validation_error",
                f"body.properties.Applicant.type should be \"reference\", instead was "
                f"{_shape(applicant_prop.get('type'))}.",
            )
        reference = applicant_prop.get("reference")
        if not isinstance(reference, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Applicant.reference should be an object, instead was "
                f"{_shape(reference)}.",
            )
        applicant_id = reference.get("applicant_id")
        if not isinstance(applicant_id, str) or not applicant_id:
            return _error(
                400, "validation_error",
                f"body.properties.Applicant.reference.applicant_id should be a "
                f"non-empty string, instead was {_shape(applicant_id)}.",
            )

        action_prop = props.get("Action")
        if action_prop is None:
            return _error(
                400, "validation_error",
                "body.properties.Action should be defined, instead was 'undefined'.",
            )
        if not isinstance(action_prop, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Action should be an object, instead was "
                f"{_shape(action_prop)}.",
            )
        if action_prop.get("type") != "select":
            return _error(
                400, "validation_error",
                f"body.properties.Action.type should be \"select\", instead was "
                f"{_shape(action_prop.get('type'))}.",
            )
        select = action_prop.get("select")
        if not isinstance(select, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Action.select should be an object, instead was "
                f"{_shape(select)}.",
            )
        action_name = select.get("name")
        if not isinstance(action_name, str) or not action_name:
            return _error(
                400, "validation_error",
                f"body.properties.Action.select.name should be a non-empty string, "
                f"instead was {_shape(action_name)}.",
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

        # --- Business validation ---
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT embassy_id FROM applicants WHERE applicant_id = ?",
            (applicant_id,),
        )
        row = c.fetchone()
        if row is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find applicant with ID: {applicant_id}.",
            )
        if row[0] != embassy_id:
            conn.close()
            return _error(
                400, "validation_error",
                f"Applicant '{applicant_id}' belongs to embassy queue '{row[0]}', "
                f"not '{embassy_id}'. File the request to the applicant's own "
                f"embassy queue.",
            )

        # --- Perform recording ---
        c.execute(
            "CREATE TABLE IF NOT EXISTS intervention_requests ("
            "applicant_id TEXT PRIMARY KEY, "
            "embassy_id TEXT NOT NULL, "
            "recommended_action TEXT NOT NULL)"
        )
        c.execute(
            "INSERT OR REPLACE INTO intervention_requests "
            "(applicant_id, embassy_id, recommended_action) VALUES (?,?,?)",
            (applicant_id, embassy_id, action_name),
        )
        conn.commit()
        conn.close()

        # Success response: deep echo, shape distinct from error responses.
        return {
            "object": "intervention_request",
            "id": "ivr_" + hashlib.md5(
                f"{applicant_id}:{embassy_id}".encode()).hexdigest()[:10],
            "parent": {"type": "embassy_queue", "embassy_id": embassy_id},
            "properties": {
                "Applicant": {"type": "reference",
                              "reference": {"applicant_id": applicant_id}},
                "Action": {"type": "select", "select": {"name": action_name}},
            },
            "created": True,
        }

    # ── Evaluation ────────────────────────────────────────────────────────

    def _load_config(self):
        """Load workspace config files for evaluation."""
        with open(os.path.join(self.workspace, "stall_criteria.json")) as f:
            stall_criteria = json.load(f)
        with open(os.path.join(self.workspace, "priority_scoring_rules.yaml")) as f:
            priority_rules = yaml.safe_load(f)
        standards = {}
        with open(os.path.join(self.workspace, "visa_processing_standards.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                standards[row["visa_category"]] = {
                    "standard_sla_days": int(row["standard_sla_days"]),
                    "requires_interview": row["requires_interview"],
                    "max_renewals": int(row["max_renewals"]),
                }
        return stall_criteria, priority_rules, standards

    def _load_case_dossiers(self):
        """Load all case dossier data from workspace files."""
        dossiers = {}  # applicant_id -> {escalation_level, sponsor_tier, ...}
        for fname in os.listdir(self.workspace):
            if not fname.startswith("case_dossier_batch_"):
                continue
            fpath = os.path.join(self.workspace, fname)
            if fname.endswith(".json"):
                with open(fpath) as f:
                    records = json.load(f)
                for rec in records:
                    dossiers[rec["applicant_id"]] = rec
            elif fname.endswith(".csv"):
                with open(fpath) as f:
                    reader = csv.DictReader(f)
                    for rec in reader:
                        rec["escalation_level"] = int(rec["escalation_level"])
                        if rec.get("special_circumstances") == "":
                            rec["special_circumstances"] = None
                        dossiers[rec["applicant_id"]] = rec
            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    content = f.read()
                current = {}
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("--- Applicant:"):
                        if current.get("applicant_id"):
                            dossiers[current["applicant_id"]] = current
                        app_id = line.split("--- Applicant:")[1].strip().rstrip(" ---")
                        current = {"applicant_id": app_id}
                    elif line.startswith("Escalation Level:"):
                        current["escalation_level"] = int(line.split(":")[1].strip())
                    elif line.startswith("Sponsor Tier:"):
                        current["sponsor_tier"] = line.split(":")[1].strip()
                    elif line.startswith("Special Circumstances:"):
                        val = line.split(":", 1)[1].strip()
                        current["special_circumstances"] = None if val == "None" else val
                    elif line.startswith("Last Officer Contact:"):
                        current["last_officer_contact"] = line.split(":")[1].strip()
                if current.get("applicant_id"):
                    dossiers[current["applicant_id"]] = current
            elif fname.endswith(".yaml"):
                with open(fpath) as f:
                    records = yaml.safe_load(f)
                if records:
                    for rec in records:
                        dossiers[rec["applicant_id"]] = rec
            elif fname.endswith(".md"):
                with open(fpath) as f:
                    content = f.read()
                current = {}
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("## APP_"):
                        if current.get("applicant_id"):
                            dossiers[current["applicant_id"]] = current
                        current = {"applicant_id": line[3:].strip()}
                    elif line.startswith("| Escalation Level |"):
                        val = line.split("|")[2].strip()
                        current["escalation_level"] = int(val)
                    elif line.startswith("| Sponsor Tier |"):
                        current["sponsor_tier"] = line.split("|")[2].strip()
                    elif line.startswith("| Special Circumstances |"):
                        val = line.split("|")[2].strip()
                        current["special_circumstances"] = None if val == "None" else val
                    elif line.startswith("| Last Officer Contact |"):
                        current["last_officer_contact"] = line.split("|")[2].strip()
                if current.get("applicant_id"):
                    dossiers[current["applicant_id"]] = current
        return dossiers

    def _compute_ground_truth(self):
        """Compute the expected intervention list from scratch."""
        stall_criteria, priority_rules, standards = self._load_config()
        dossiers = self._load_case_dossiers()
        ref_date = datetime.strptime(stall_criteria["reference_date"], "%Y-%m-%d")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Get all active applicants
        c = conn.cursor()
        active_statuses = ("pending", "in_review", "on_hold", "awaiting_documents")
        placeholders = ",".join("?" for _ in active_statuses)
        c.execute(f"SELECT * FROM applicants WHERE current_status IN ({placeholders})", active_statuses)
        applicants = [dict(r) for r in c.fetchall()]

        intervention_list = []

        for app in applicants:
            app_id = app["applicant_id"]
            sub_date = datetime.strptime(app["submission_date"], "%Y-%m-%d")
            days_since = (ref_date - sub_date).days
            visa_cat = app["visa_category"]
            embassy = app["embassy_id"]

            sla_days = standards.get(visa_cat, {}).get("standard_sla_days", 90)
            threshold_mult = stall_criteria["processing_time_threshold_multiplier"]
            bio_warning = stall_criteria["biometric_expiry_warning_days"]
            min_flags = stall_criteria["min_unresolved_document_flags"]
            appt_threshold = stall_criteria["appointment_wait_threshold_days"]
            quota_crit_pct = stall_criteria["quota_utilization_critical_pct"]

            stall_reasons = []

            # Check biometrics
            c.execute("SELECT * FROM biometric_submissions WHERE applicant_id = ?", (app_id,))
            bios = [dict(r) for r in c.fetchall()]
            has_bio_issue = False
            for bio in bios:
                if bio["status"] == "expired":
                    has_bio_issue = True
                    break
                expiry = datetime.strptime(bio["expiry_date"], "%Y-%m-%d")
                if (expiry - ref_date).days <= bio_warning:
                    has_bio_issue = True
                    break
            if has_bio_issue:
                stall_reasons.append("biometric_expired")

            # Check document flags
            c.execute(
                "SELECT COUNT(*) FROM document_verifications WHERE applicant_id = ? AND verification_status = 'flagged'",
                (app_id,),
            )
            num_flags = c.fetchone()[0]
            if num_flags >= min_flags:
                stall_reasons.append("document_flags_unresolved")

            # Check SLA
            if days_since > sla_days * threshold_mult:
                stall_reasons.append("sla_exceeded")

            # Check appointment backlog
            c.execute("SELECT * FROM embassy_appointments WHERE applicant_id = ?", (app_id,))
            appts = [dict(r) for r in c.fetchall()]
            has_appt_issue = False
            for appt in appts:
                if appt["status"] in ("pending", "scheduled") and appt["wait_days"] > appt_threshold:
                    has_appt_issue = True
                    break
            if has_appt_issue:
                stall_reasons.append("appointment_backlogged")

            # Check quota
            c.execute(
                "SELECT * FROM visa_quotas WHERE visa_category = ? AND embassy_id = ? AND quarter = 'Q2'",
                (visa_cat, embassy),
            )
            quota_row = c.fetchone()
            if quota_row:
                quota = dict(quota_row)
                util_pct = (quota["used_count"] / quota["allocated_quota"] * 100) if quota["allocated_quota"] > 0 else 0
                if util_pct >= quota_crit_pct:
                    stall_reasons.append("quota_critical")

            if not stall_reasons:
                continue  # Not stalled

            # Check high-priority
            dossier = dossiers.get(app_id, {})
            escalation_level = int(dossier.get("escalation_level", 0))
            sponsor_tier = dossier.get("sponsor_tier", "none")

            hp_conditions = priority_rules["high_priority_conditions"]
            is_high_priority = (
                app["priority_level"] in hp_conditions["priority_levels"]
                or escalation_level >= hp_conditions["min_escalation_level"]
                or sponsor_tier in hp_conditions["sponsor_tiers"]
            )

            if not is_high_priority:
                continue

            # Compute priority score
            base_score = priority_rules["base_scores"].get(visa_cat, 50)
            pl_mult = priority_rules["priority_level_multiplier"].get(app["priority_level"], 1.0)
            mods = priority_rules["modifiers"]

            score = base_score * pl_mult
            score += base_score * mods["escalation_multiplier"] * escalation_level
            score += days_since * mods["days_stalled_factor"]
            if "quota_critical" in stall_reasons:
                score += mods["quota_pressure_bonus"]
            if "biometric_expired" in stall_reasons:
                score += mods["biometric_expiry_bonus"]
            score += mods["document_flag_penalty"] * num_flags
            score += mods["sponsor_tier_bonus"].get(sponsor_tier, 0)

            score = round(score, 2)

            # Determine recommended action based on priority order
            action_map = priority_rules["stall_reason_action_mapping"]
            reason_order = priority_rules["stall_reason_priority_order"]
            recommended_action = "Review case"
            for reason in reason_order:
                if reason in stall_reasons:
                    recommended_action = action_map[reason]
                    break

            stall_reasons_str = "; ".join(stall_reasons)

            intervention_list.append({
                "applicant_id": app_id,
                "full_name": app["full_name"],
                "visa_category": visa_cat,
                "embassy_id": embassy,
                "priority_score": score,
                "stall_reasons": stall_reasons_str,
                "recommended_action": recommended_action,
                "days_stalled": days_since,
            })

        conn.close()

        # Sort: priority_score DESC, days_stalled DESC, applicant_id ASC
        intervention_list.sort(
            key=lambda x: (-x["priority_score"], -x["days_stalled"], x["applicant_id"])
        )

        return intervention_list

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
        gt_ids = set(r["applicant_id"] for r in ground_truth)
        gt_map = {r["applicant_id"]: r for r in ground_truth}

        criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: Output file exists and has correct columns (15 pts) ──
        c1_max = 15
        max_score += c1_max
        csv_path = os.path.join(self.workspace, "intervention_list.csv")
        expected_columns = [
            "applicant_id", "full_name", "visa_category", "embassy_id",
            "priority_score", "stall_reasons", "recommended_action", "days_stalled",
        ]
        submitted_rows = []
        c1_passed = False
        c1_reason = ""
        if os.path.exists(csv_path):
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    if set(expected_columns).issubset(set(cols)):
                        submitted_rows = list(reader)
                        c1_passed = True
                    else:
                        missing = set(expected_columns) - set(cols)
                        c1_reason = f"Missing columns: {missing}"
            except Exception as e:
                c1_reason = f"Failed to parse CSV: {e}"
        else:
            c1_reason = "intervention_list.csv not found in workspace"

        c1_score = c1_max if c1_passed else 0
        total_score += c1_score
        criteria["output_file_format"] = {
            "passed": c1_passed,
            "score": c1_score,
            "max_score": c1_max,
        }
        if not c1_passed:
            criteria["output_file_format"]["reason"] = c1_reason

        # ── Criterion 2: Correct identification of stalled high-priority applicants (25 pts) ──
        c2_max = 25
        max_score += c2_max
        submitted_ids = set(r["applicant_id"] for r in submitted_rows)
        if gt_ids:
            correct_ids = submitted_ids & gt_ids
            false_positives = submitted_ids - gt_ids
            false_negatives = gt_ids - submitted_ids
            precision = len(correct_ids) / len(submitted_ids) if submitted_ids else 0
            recall = len(correct_ids) / len(gt_ids) if gt_ids else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            c2_score = round(c2_max * f1)
        else:
            c2_score = c2_max if not submitted_ids else 0
        c2_passed = c2_score == c2_max
        total_score += c2_score
        criteria["stalled_identification"] = {
            "passed": c2_passed,
            "score": c2_score,
            "max_score": c2_max,
        }
        if not c2_passed:
            reasons = []
            if 'false_positives' in dir() and false_positives:
                reasons.append(f"False positives: {len(false_positives)}")
            if 'false_negatives' in dir() and false_negatives:
                reasons.append(f"False negatives: {len(false_negatives)}")
            criteria["stalled_identification"]["reason"] = "; ".join(reasons) if reasons else "Mismatch in identified applicants"

        # ── Criterion 3: Priority score accuracy (20 pts) ──
        c3_max = 20
        max_score += c3_max
        if submitted_rows and gt_ids:
            score_matches = 0
            score_total = 0
            for row in submitted_rows:
                aid = row.get("applicant_id", "")
                if aid in gt_map:
                    score_total += 1
                    try:
                        submitted_score = float(row.get("priority_score", 0))
                        expected_score = gt_map[aid]["priority_score"]
                        if abs(submitted_score - expected_score) <= 0.5:
                            score_matches += 1
                    except (ValueError, TypeError):
                        pass
            accuracy = score_matches / score_total if score_total > 0 else 0
            c3_score = round(c3_max * accuracy)
        else:
            c3_score = 0
        c3_passed = c3_score == c3_max
        total_score += c3_score
        criteria["priority_score_accuracy"] = {
            "passed": c3_passed,
            "score": c3_score,
            "max_score": c3_max,
        }
        if not c3_passed:
            criteria["priority_score_accuracy"]["reason"] = f"Score accuracy: {score_matches}/{score_total}" if submitted_rows else "No rows to evaluate"

        # ── Criterion 4: Stall reasons correctness (15 pts) ──
        c4_max = 15
        max_score += c4_max
        if submitted_rows and gt_ids:
            reason_matches = 0
            reason_total = 0
            for row in submitted_rows:
                aid = row.get("applicant_id", "")
                if aid in gt_map:
                    reason_total += 1
                    submitted_reasons = set(r.strip() for r in row.get("stall_reasons", "").split(";") if r.strip())
                    expected_reasons = set(r.strip() for r in gt_map[aid]["stall_reasons"].split(";") if r.strip())
                    if submitted_reasons == expected_reasons:
                        reason_matches += 1
            accuracy = reason_matches / reason_total if reason_total > 0 else 0
            c4_score = round(c4_max * accuracy)
        else:
            c4_score = 0
        c4_passed = c4_score == c4_max
        total_score += c4_score
        criteria["stall_reasons_accuracy"] = {
            "passed": c4_passed,
            "score": c4_score,
            "max_score": c4_max,
        }
        if not c4_passed:
            criteria["stall_reasons_accuracy"]["reason"] = f"Reason matches: {reason_matches}/{reason_total}" if submitted_rows else "No rows"

        # ── Criterion 5: Sorting order (10 pts) ──
        c5_max = 10
        max_score += c5_max
        c5_passed = False
        c5_reason = ""
        if len(submitted_rows) >= 2:
            try:
                correctly_sorted = True
                for i in range(len(submitted_rows) - 1):
                    s1 = float(submitted_rows[i].get("priority_score", 0))
                    s2 = float(submitted_rows[i + 1].get("priority_score", 0))
                    d1 = int(submitted_rows[i].get("days_stalled", 0))
                    d2 = int(submitted_rows[i + 1].get("days_stalled", 0))
                    id1 = submitted_rows[i].get("applicant_id", "")
                    id2 = submitted_rows[i + 1].get("applicant_id", "")
                    if s1 < s2:
                        correctly_sorted = False
                        break
                    elif s1 == s2:
                        if d1 < d2:
                            correctly_sorted = False
                            break
                        elif d1 == d2:
                            if id1 > id2:
                                correctly_sorted = False
                                break
                c5_passed = correctly_sorted
                if not c5_passed:
                    c5_reason = "Rows not sorted by priority_score DESC, days_stalled DESC, applicant_id ASC"
            except (ValueError, TypeError) as e:
                c5_reason = f"Could not parse sort fields: {e}"
        elif len(submitted_rows) == 1:
            c5_passed = True
        else:
            c5_reason = "No rows to check sorting"

        c5_score = c5_max if c5_passed else 0
        total_score += c5_score
        criteria["sorting_order"] = {
            "passed": c5_passed,
            "score": c5_score,
            "max_score": c5_max,
        }
        if not c5_passed:
            criteria["sorting_order"]["reason"] = c5_reason

        # ── Criterion 6: Recommended actions accuracy (15 pts) ──
        c6_max = 15
        max_score += c6_max
        if submitted_rows and gt_ids:
            action_matches = 0
            action_total = 0
            for row in submitted_rows:
                aid = row.get("applicant_id", "")
                if aid in gt_map:
                    action_total += 1
                    if row.get("recommended_action", "").strip() == gt_map[aid]["recommended_action"]:
                        action_matches += 1
            accuracy = action_matches / action_total if action_total > 0 else 0
            c6_score = round(c6_max * accuracy)
        else:
            c6_score = 0
        c6_passed = c6_score == c6_max
        total_score += c6_score
        criteria["recommended_actions"] = {
            "passed": c6_passed,
            "score": c6_score,
            "max_score": c6_max,
        }
        if not c6_passed:
            criteria["recommended_actions"]["reason"] = f"Action matches: {action_matches}/{action_total}" if submitted_rows else "No rows"

        # ── Criterion 7: Interventions recorded in the system (15 pts) ──
        c7_max = 15
        max_score += c7_max
        recorded_ids = set()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute("SELECT applicant_id FROM intervention_requests")
            recorded_ids = set(r[0] for r in c.fetchall())
        except sqlite3.OperationalError:
            recorded_ids = set()
        conn.close()
        if gt_ids:
            rec_correct = recorded_ids & gt_ids
            rec_precision = len(rec_correct) / len(recorded_ids) if recorded_ids else 0
            rec_recall = len(rec_correct) / len(gt_ids)
            rec_f1 = (
                2 * rec_precision * rec_recall / (rec_precision + rec_recall)
                if (rec_precision + rec_recall) > 0 else 0
            )
            c7_score = round(c7_max * rec_f1)
        else:
            c7_score = c7_max if not recorded_ids else 0
        c7_passed = c7_score == c7_max
        total_score += c7_score
        criteria["db_interventions_recorded"] = {
            "passed": c7_passed,
            "score": c7_score,
            "max_score": c7_max,
        }
        if not c7_passed:
            criteria["db_interventions_recorded"]["reason"] = (
                f"Recorded: {len(recorded_ids)}, expected: {len(gt_ids)}, "
                f"correct: {len(recorded_ids & gt_ids)}"
            )

        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": criteria,
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
        """
        import csv as csv_mod

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # Step 1: Load config files from workspace
        with open(os.path.join(self.workspace, "stall_criteria.json")) as f:
            stall_criteria = json.load(f)
        with open(os.path.join(self.workspace, "priority_scoring_rules.yaml")) as f:
            priority_rules = yaml.safe_load(f)
        sla_map = {}
        with open(os.path.join(self.workspace, "visa_processing_standards.csv")) as f:
            reader = csv_mod.DictReader(f)
            for row in reader:
                sla_map[row["visa_category"]] = int(row["standard_sla_days"])

        ref_date = datetime.strptime(stall_criteria["reference_date"], "%Y-%m-%d")

        # Step 2: Load case dossiers from workspace
        dossiers = {}
        for fname in sorted(os.listdir(self.workspace)):
            if not fname.startswith("case_dossier_batch_"):
                continue
            fpath = os.path.join(self.workspace, fname)
            if fname.endswith(".json"):
                with open(fpath) as f:
                    for rec in json.load(f):
                        dossiers[rec["applicant_id"]] = rec
            elif fname.endswith(".csv"):
                with open(fpath) as f:
                    for rec in csv_mod.DictReader(f):
                        rec["escalation_level"] = int(rec["escalation_level"])
                        if rec.get("special_circumstances") == "":
                            rec["special_circumstances"] = None
                        dossiers[rec["applicant_id"]] = rec
            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    content = f.read()
                current = {}
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("--- Applicant:"):
                        if current.get("applicant_id"):
                            dossiers[current["applicant_id"]] = current
                        app_id = line.split("--- Applicant:")[1].strip().rstrip(" ---")
                        current = {"applicant_id": app_id}
                    elif line.startswith("Escalation Level:"):
                        current["escalation_level"] = int(line.split(":")[1].strip())
                    elif line.startswith("Sponsor Tier:"):
                        current["sponsor_tier"] = line.split(":")[1].strip()
                    elif line.startswith("Special Circumstances:"):
                        val = line.split(":", 1)[1].strip()
                        current["special_circumstances"] = None if val == "None" else val
                    elif line.startswith("Last Officer Contact:"):
                        current["last_officer_contact"] = line.split(":")[1].strip()
                if current.get("applicant_id"):
                    dossiers[current["applicant_id"]] = current
            elif fname.endswith(".yaml"):
                with open(fpath) as f:
                    records = yaml.safe_load(f)
                if records:
                    for rec in records:
                        dossiers[rec["applicant_id"]] = rec
            elif fname.endswith(".md"):
                with open(fpath) as f:
                    content = f.read()
                current = {}
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("## APP_"):
                        if current.get("applicant_id"):
                            dossiers[current["applicant_id"]] = current
                        current = {"applicant_id": line[3:].strip()}
                    elif line.startswith("| Escalation Level |"):
                        current["escalation_level"] = int(line.split("|")[2].strip())
                    elif line.startswith("| Sponsor Tier |"):
                        current["sponsor_tier"] = line.split("|")[2].strip()
                    elif line.startswith("| Special Circumstances |"):
                        val = line.split("|")[2].strip()
                        current["special_circumstances"] = None if val == "None" else val
                    elif line.startswith("| Last Officer Contact |"):
                        current["last_officer_contact"] = line.split("|")[2].strip()
                if current.get("applicant_id"):
                    dossiers[current["applicant_id"]] = current

        # Step 3: Gather all active applicants via tool calls (paginated).
        # M1 surface: filters are passed as a JSON-encoded string.
        active_statuses = ["pending", "in_review", "on_hold", "awaiting_documents"]
        all_active = []
        for status in active_statuses:
            page = 1
            while True:
                result = call_tool(
                    "search_applicants",
                    filter=json.dumps({"status": status}),
                    page=page,
                    page_size=20,
                )
                assert result.get("object") != "error", f"search failed: {result}"
                all_active.extend(result["results"])
                if page >= result["total_pages"]:
                    break
                page += 1

        # Step 4: For each active applicant, check stall conditions and priority
        intervention_list = []
        threshold_mult = stall_criteria["processing_time_threshold_multiplier"]
        bio_warning = stall_criteria["biometric_expiry_warning_days"]
        min_flags = stall_criteria["min_unresolved_document_flags"]
        appt_threshold = stall_criteria["appointment_wait_threshold_days"]
        quota_crit_pct = stall_criteria["quota_utilization_critical_pct"]

        # Cache quota lookups to avoid redundant calls
        quota_cache = {}

        for app in all_active:
            app_id = app["applicant_id"]
            visa_cat = app["visa_category"]
            embassy = app["embassy_id"]
            sub_date = datetime.strptime(app["submission_date"], "%Y-%m-%d")
            days_since = (ref_date - sub_date).days

            sla_days = sla_map.get(visa_cat, 90)
            stall_reasons = []

            # Check biometrics
            bio_result = call_tool("get_biometric_status", applicant_id=app_id)
            has_bio_issue = False
            for bio in bio_result["biometrics"]:
                if bio["status"] == "expired":
                    has_bio_issue = True
                    break
                expiry = datetime.strptime(bio["expiry_date"], "%Y-%m-%d")
                if (expiry - ref_date).days <= bio_warning:
                    has_bio_issue = True
                    break
            if has_bio_issue:
                stall_reasons.append("biometric_expired")

            # Check document flags
            doc_result = call_tool("get_document_flags", applicant_id=app_id)
            num_flags = sum(1 for d in doc_result["documents"] if d["verification_status"] == "flagged")
            if num_flags >= min_flags:
                stall_reasons.append("document_flags_unresolved")

            # Check SLA
            if days_since > sla_days * threshold_mult:
                stall_reasons.append("sla_exceeded")

            # Check appointments
            appt_result = call_tool("get_appointment_history", applicant_id=app_id)
            has_appt_issue = False
            for appt in appt_result["appointments"]:
                if appt["status"] in ("pending", "scheduled") and appt["wait_days"] > appt_threshold:
                    has_appt_issue = True
                    break
            if has_appt_issue:
                stall_reasons.append("appointment_backlogged")

            # Check quota
            quota_key = (visa_cat, embassy)
            if quota_key not in quota_cache:
                quota_cache[quota_key] = call_tool("get_visa_quota", visa_category=visa_cat, embassy_id=embassy, quarter="Q2")
            quota_info = quota_cache[quota_key]
            if "utilization_pct" in quota_info and quota_info["utilization_pct"] >= quota_crit_pct:
                stall_reasons.append("quota_critical")

            if not stall_reasons:
                continue

            # Check high-priority
            dossier = dossiers.get(app_id, {})
            escalation_level = int(dossier.get("escalation_level", 0))
            sponsor_tier = dossier.get("sponsor_tier", "none")

            hp_conditions = priority_rules["high_priority_conditions"]
            is_high_priority = (
                app["priority_level"] in hp_conditions["priority_levels"]
                or escalation_level >= hp_conditions["min_escalation_level"]
                or sponsor_tier in hp_conditions["sponsor_tiers"]
            )

            if not is_high_priority:
                continue

            # Compute priority score
            base_score = priority_rules["base_scores"].get(visa_cat, 50)
            pl_mult = priority_rules["priority_level_multiplier"].get(app["priority_level"], 1.0)
            mods = priority_rules["modifiers"]

            score = base_score * pl_mult
            score += base_score * mods["escalation_multiplier"] * escalation_level
            score += days_since * mods["days_stalled_factor"]
            if "quota_critical" in stall_reasons:
                score += mods["quota_pressure_bonus"]
            if "biometric_expired" in stall_reasons:
                score += mods["biometric_expiry_bonus"]
            score += mods["document_flag_penalty"] * num_flags
            score += mods["sponsor_tier_bonus"].get(sponsor_tier, 0)

            score = round(score, 2)

            # Determine recommended action
            action_map = priority_rules["stall_reason_action_mapping"]
            reason_order = priority_rules["stall_reason_priority_order"]
            recommended_action = "Review case"
            for reason in reason_order:
                if reason in stall_reasons:
                    recommended_action = action_map[reason]
                    break

            intervention_list.append({
                "applicant_id": app_id,
                "full_name": app["full_name"],
                "visa_category": visa_cat,
                "embassy_id": embassy,
                "priority_score": score,
                "stall_reasons": "; ".join(stall_reasons),
                "recommended_action": recommended_action,
                "days_stalled": days_since,
            })

        # Sort
        intervention_list.sort(
            key=lambda x: (-x["priority_score"], -x["days_stalled"], x["applicant_id"])
        )

        # Record every intervention in the case management system.
        # M4 surface: nested request payload (parent + properties).
        for entry in intervention_list:
            resp = call_tool(
                "create_intervention",
                payload={
                    "parent": {
                        "type": "embassy_queue",
                        "embassy_id": entry["embassy_id"],
                    },
                    "properties": {
                        "Applicant": {
                            "type": "reference",
                            "reference": {"applicant_id": entry["applicant_id"]},
                        },
                        "Action": {
                            "type": "select",
                            "select": {"name": entry["recommended_action"]},
                        },
                        "Note": {
                            "type": "rich_text",
                            "rich_text": [
                                {"text": {"content": entry["stall_reasons"]}}
                            ],
                        },
                    },
                },
            )
            assert resp.get("created") is True, f"create_intervention failed: {resp}"

        # Write output CSV
        csv_path = os.path.join(self.workspace, "intervention_list.csv")
        fieldnames = [
            "applicant_id", "full_name", "visa_category", "embassy_id",
            "priority_score", "stall_reasons", "recommended_action", "days_stalled",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(intervention_list)

        # Build action string (summary)
        action_lines = [
            f"Intervention list generated with {len(intervention_list)} stalled high-priority applications.",
            "The list has been saved to intervention_list.csv, sorted by priority_score descending, "
            "then days_stalled descending, then applicant_id ascending.",
            "",
            "Top entries:",
        ]
        for entry in intervention_list[:5]:
            action_lines.append(
                f"  {entry['applicant_id']} ({entry['full_name']}): "
                f"score={entry['priority_score']}, stall_reasons={entry['stall_reasons']}, "
                f"action={entry['recommended_action']}"
            )
        if len(intervention_list) > 5:
            action_lines.append(f"  ... and {len(intervention_list) - 5} more entries.")
        action_lines.append(
            f"All {len(intervention_list)} intervention requests have been recorded "
            f"in the case management system."
        )

        action = "\n".join(action_lines)

        print(f"[verify] Tool calls made: {tool_call_count}")
        return self.step(action)
