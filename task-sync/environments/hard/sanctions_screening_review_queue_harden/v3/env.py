#!/usr/bin/env python3
"""Environment for sanctions screening task (hardened tool surface).

Hardened surface (M0 + M1 + M4):
  - M0: prompt.md specifies goal and deliverable contract only; the screening
    methodology lives in the workspace compliance policy / configuration files.
  - M1: search_sanctions takes a single JSON-encoded string `request`
    parameter; list_pending_customers takes a JSON-encoded string `filter`
    parameter. Malformed JSON or unsupported keys produce recoverable
    API-style errors.
  - M4: create_review_case takes a deeply nested request payload
    (parent + properties) validated layer by layer with Notion-style error
    messages, and records the per-customer review priority in the database.
Task data, business logic, ground truth, and the CSV deliverable are
unchanged from the base environment; step() gains one DB-state criterion
for the review cases recorded through the write API.
"""

import ast
import hashlib
import sqlite3
import os
import json
import csv
import re
import glob
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

    # -----------------------------------------------------------------------
    # Helper: name similarity (word-level Jaccard)
    # -----------------------------------------------------------------------
    @staticmethod
    def _name_similarity(name1: str, name2: str) -> float:
        w1 = set(re.sub(r"[^a-z\s]", "", name1.lower()).split())
        w2 = set(re.sub(r"[^a-z\s]", "", name2.lower()).split())
        if not w1 or not w2:
            return 0.0
        return len(w1 & w2) / len(w1 | w2)

    # -----------------------------------------------------------------------
    # Tools
    # -----------------------------------------------------------------------
    @tool(
        description="List customers with pending screening status. Returns a paginated list of customers awaiting sanctions screening. Each entry includes the customer ID, full name, customer type, nationality, and registration date. Filtering is expressed as a JSON-encoded string, e.g. filter='{\"customer_type\": \"corporate\"}'. Supported filter properties: customer_type (individual | corporate) and nationality (country name).",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20, default 10)"
                },
                "filter": {
                    "type": "string",
                    "description": "Optional JSON-encoded filter object as a string. Example: '{\"customer_type\": \"individual\", \"nationality\": \"Germany\"}'. Pass '{}' or omit for no filtering."
                }
            },
            "required": ["page"]
        }
    )
    def list_pending_customers(self, page: Any = None, page_size: Any = 10, filter: Any = None) -> dict:
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            return _error(400, "validation_error",
                          f"body.page should be a positive integer, instead was {_shape(page)}.")
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
            return _error(400, "validation_error",
                          f"body.page_size should be a positive integer, instead was {_shape(page_size)}.")
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err
        supported = {"customer_type", "nationality"}
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                              f"body.filter.{key} is not a supported filter property. "
                              f"Supported properties: customer_type, nationality.")
        clauses = ["screening_status='pending'"]
        params: list = []
        if "customer_type" in parsed:
            ctype = parsed["customer_type"]
            if not isinstance(ctype, str) or ctype not in ("individual", "corporate"):
                return _error(400, "validation_error",
                              f"body.filter.customer_type should be one of \"individual\", "
                              f"\"corporate\", instead was {_shape(ctype)}.")
            clauses.append("customer_type=?")
            params.append(ctype)
        if "nationality" in parsed:
            nat = parsed["nationality"]
            if not isinstance(nat, str) or not nat:
                return _error(400, "validation_error",
                              f"body.filter.nationality should be a non-empty string, "
                              f"instead was {_shape(nat)}.")
            clauses.append("nationality=?")
            params.append(nat)

        page_size = min(page_size, 20)
        where = " AND ".join(clauses)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        total = c.execute(f"SELECT COUNT(*) FROM customers WHERE {where}", params).fetchone()[0]
        offset = (page - 1) * page_size
        rows = c.execute(
            f"SELECT customer_id, full_name, customer_type, nationality, registration_date "
            f"FROM customers WHERE {where} "
            f"ORDER BY customer_id LIMIT ? OFFSET ?",
            params + [page_size, offset]
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total_customers": total,
            "total_pages": (total + page_size - 1) // page_size,
            "customers": [dict(r) for r in rows],
        }

    @tool(
        description="Get detailed information for a specific customer by their ID. Returns the full customer record including date of birth, nationality, country of residence, customer type, and screening status.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The customer identifier, e.g. CUST-0001"
                }
            },
            "required": ["customer_id"]
        }
    )
    def get_customer_details(self, customer_id: Any = None) -> dict:
        if not isinstance(customer_id, str) or not customer_id:
            return _error(400, "validation_error",
                          f"body.customer_id should be a non-empty string, instead was {_shape(customer_id)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find customer with ID: {customer_id}.")
        return dict(row)

    @tool(
        description="Search sanctions lists by name. Computes word-level similarity between the queried name and all sanctions entry names and their known aliases. Returns entries whose similarity score meets a minimum internal threshold of 0.3, along with the computed similarity score. The search request is expressed as a JSON-encoded string, e.g. request='{\"query\": \"John Smith\"}'. Supported request properties: query (required, the name to search) and list_source (optional, one of OFAC | EU | UN to restrict results to a single sanctions list).",
        parameters={
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "JSON-encoded search request object as a string. Example: '{\"query\": \"Viktor Petrov\", \"list_source\": \"OFAC\"}'. The query property is required."
                }
            },
            "required": ["request"]
        }
    )
    def search_sanctions(self, request: Any = None) -> dict:
        parsed, err = _parse_json_string_param(request, "request")
        if err is not None:
            return err
        supported = {"query", "list_source"}
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                              f"body.request.{key} is not a supported request property. "
                              f"Supported properties: query, list_source.")
        if "query" not in parsed:
            return _error(400, "validation_error",
                          "body.request.query should be defined, instead was 'undefined'.")
        query = parsed["query"]
        if not isinstance(query, str) or not query:
            return _error(400, "validation_error",
                          f"body.request.query should be a non-empty string, instead was {_shape(query)}.")
        list_source = parsed.get("list_source")
        if list_source is not None and (
                not isinstance(list_source, str) or list_source not in ("OFAC", "EU", "UN")):
            return _error(400, "validation_error",
                          f"body.request.list_source should be one of \"OFAC\", \"EU\", \"UN\", "
                          f"instead was {_shape(list_source)}.")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        if list_source:
            entries = c.execute(
                "SELECT * FROM sanctions_entries WHERE list_source = ?", (list_source,)
            ).fetchall()
        else:
            entries = c.execute("SELECT * FROM sanctions_entries").fetchall()

        # Also load aliases
        aliases = {}
        for row in c.execute("SELECT entry_id, alias_name FROM sanctions_aliases").fetchall():
            aliases.setdefault(row["entry_id"], []).append(row["alias_name"])

        conn.close()
        results = []
        for entry in entries:
            eid = entry["entry_id"]
            # Check main name
            sim = self._name_similarity(query, entry["entity_name"])
            # Check aliases
            for alias in aliases.get(eid, []):
                alias_sim = self._name_similarity(query, alias)
                sim = max(sim, alias_sim)

            if sim >= 0.3:
                results.append({
                    "entry_id": eid,
                    "entity_name": entry["entity_name"],
                    "list_source": entry["list_source"],
                    "entity_type": entry["entity_type"],
                    "similarity_score": round(sim, 4),
                })

        results.sort(key=lambda x: -x["similarity_score"])
        return {"query": query, "matches": results[:20]}

    @tool(
        description="Get full details of a sanctions entry by its ID. Returns the complete record including entity name, list source, date of birth, nationalities, country, program, remarks, and known aliases.",
        parameters={
            "type": "object",
            "properties": {
                "entry_id": {
                    "type": "string",
                    "description": "The sanctions entry identifier, e.g. SAN-0001"
                }
            },
            "required": ["entry_id"]
        }
    )
    def get_sanctions_entry(self, entry_id: Any = None) -> dict:
        if not isinstance(entry_id, str) or not entry_id:
            return _error(400, "validation_error",
                          f"body.entry_id should be a non-empty string, instead was {_shape(entry_id)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM sanctions_entries WHERE entry_id = ?", (entry_id,)
        ).fetchone()
        aliases = [r["alias_name"] for r in conn.execute(
            "SELECT alias_name FROM sanctions_aliases WHERE entry_id = ?", (entry_id,)
        ).fetchall()]
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find sanctions entry with ID: {entry_id}.")
        result = dict(row)
        result["aliases"] = aliases
        return result

    @tool(
        description="Get all payment intermediaries associated with a customer. Returns the list of intermediaries including name, country, type, transaction amount, currency, and date.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The customer identifier"
                }
            },
            "required": ["customer_id"]
        }
    )
    def get_payment_intermediaries(self, customer_id: Any = None) -> dict:
        if not isinstance(customer_id, str) or not customer_id:
            return _error(400, "validation_error",
                          f"body.customer_id should be a non-empty string, instead was {_shape(customer_id)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM payment_intermediaries WHERE customer_id = ? ORDER BY intermediary_id",
            (customer_id,)
        ).fetchall()
        conn.close()
        return {
            "customer_id": customer_id,
            "intermediaries": [dict(r) for r in rows],
        }

    @tool(
        description="Get the ultimate beneficial ownership structure for a customer. Returns all UBO records including entity name, ownership percentage, beneficial owner name, nationality, date of birth, and control type.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The customer identifier"
                }
            },
            "required": ["customer_id"]
        }
    )
    def get_ubo_structure(self, customer_id: Any = None) -> dict:
        if not isinstance(customer_id, str) or not customer_id:
            return _error(400, "validation_error",
                          f"body.customer_id should be a non-empty string, instead was {_shape(customer_id)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM ubo_structures WHERE customer_id = ? ORDER BY ubo_record_id",
            (customer_id,)
        ).fetchall()
        conn.close()
        return {
            "customer_id": customer_id,
            "ubo_records": [dict(r) for r in rows],
        }

    @tool(
        description="Get the risk tier for a specific country from the country risk matrix stored in the workspace. Returns the country name, risk tier (1-5), and whether an active sanctions regime applies.",
        parameters={
            "type": "object",
            "properties": {
                "country": {
                    "type": "string",
                    "description": "Country name to look up"
                }
            },
            "required": ["country"]
        }
    )
    def get_country_risk(self, country: Any = None) -> dict:
        if not isinstance(country, str) or not country:
            return _error(400, "validation_error",
                          f"body.country should be a non-empty string, instead was {_shape(country)}.")
        filepath = os.path.join(self.workspace, "country_risk_matrix.csv")
        if not os.path.exists(filepath):
            return _error(404, "object_not_found", "Country risk matrix not found.")
        with open(filepath, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["country"].strip().lower() == country.strip().lower():
                    return {
                        "country": row["country"],
                        "risk_tier": int(row["risk_tier"]),
                        "sanctions_regime": row["sanctions_regime"],
                    }
        return {"country": country, "risk_tier": 2, "sanctions_regime": "no",
                "note": "Country not found in matrix, default tier 2 assigned"}

    @tool(
        description=(
            "Files a screening review case for a customer in the compliance case-management "
            "system, recording the review priority resulting from the screening. The request "
            "body must contain a `parent` object identifying the customer whose case is being "
            "filed and a `properties` object with a `Priority` select property. Example body: "
            "{\"parent\": {\"type\": \"review_queue\", \"customer_id\": \"CUST-0001\"}, "
            "\"properties\": {\"Priority\": {\"type\": \"select\", \"select\": "
            "{\"name\": \"HIGH\"}}}}. Valid priority names are CRITICAL, HIGH, MEDIUM, LOW, "
            "and CLEAR. An optional `RiskScore` number property "
            "({\"type\": \"number\", \"number\": 55}) and an optional `Note` rich_text "
            "property may be included in `properties`. Filing a case again for the same "
            "customer replaces the previously recorded case."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "The review case request body.",
                    "properties": {
                        "parent": {
                            "type": "object",
                            "description": (
                                "The review queue entry for the customer. Must contain "
                                "type='review_queue' and a customer_id string."
                            ),
                            "properties": {
                                "type": {"type": "string"},
                                "customer_id": {"type": "string"},
                            },
                            "required": ["type", "customer_id"],
                            "additionalProperties": True,
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Case properties. Must include a 'Priority' select property. "
                                "May include a 'RiskScore' number property and a 'Note' "
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
    def create_review_case(self, payload: Any = None) -> dict:
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
        if parent.get("type") != "review_queue":
            return _error(400, "validation_error",
                          f"body.parent.type should be \"review_queue\", instead was "
                          f"{_shape(parent.get('type'))}.")
        customer_id = parent.get("customer_id")
        if not isinstance(customer_id, str) or not customer_id:
            return _error(400, "validation_error",
                          f"body.parent.customer_id should be a non-empty string, instead was "
                          f"{_shape(customer_id)}.")

        props = payload.get("properties")
        if props is None:
            return _error(400, "validation_error",
                          "body.properties should be defined, instead was 'undefined'.")
        if not isinstance(props, dict):
            return _error(400, "validation_error",
                          f"body.properties should be an object, instead was {_shape(props)}.")

        priority_prop = props.get("Priority")
        if priority_prop is None:
            return _error(400, "validation_error",
                          "body.properties.Priority should be defined, instead was 'undefined'.")
        if not isinstance(priority_prop, dict):
            return _error(400, "validation_error",
                          f"body.properties.Priority should be an object, instead was "
                          f"{_shape(priority_prop)}.")
        if priority_prop.get("type") != "select":
            return _error(400, "validation_error",
                          f"body.properties.Priority.type should be \"select\", instead was "
                          f"{_shape(priority_prop.get('type'))}.")
        select = priority_prop.get("select")
        if not isinstance(select, dict):
            return _error(400, "validation_error",
                          f"body.properties.Priority.select should be an object, instead was "
                          f"{_shape(select)}.")
        pri_name = select.get("name")
        if not isinstance(pri_name, str) or not pri_name:
            return _error(400, "validation_error",
                          f"body.properties.Priority.select.name should be a non-empty string, "
                          f"instead was {_shape(pri_name)}.")
        if pri_name not in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "CLEAR"):
            return _error(400, "validation_error",
                          f"body.properties.Priority.select.name should be one of \"CRITICAL\", "
                          f"\"HIGH\", \"MEDIUM\", \"LOW\", \"CLEAR\", instead was {_shape(pri_name)}.")

        risk_score = None
        score_prop = props.get("RiskScore")
        if score_prop is not None:
            if not isinstance(score_prop, dict) or score_prop.get("type") != "number":
                return _error(400, "validation_error",
                              "body.properties.RiskScore.type should be \"number\".")
            num = score_prop.get("number")
            if isinstance(num, bool) or not isinstance(num, (int, float)):
                return _error(400, "validation_error",
                              f"body.properties.RiskScore.number should be a number, instead was "
                              f"{_shape(num)}.")
            risk_score = float(num)

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
                if (not isinstance(item, dict)
                        or not isinstance(item.get("text"), dict)
                        or not isinstance(item["text"].get("content"), str)):
                    return _error(400, "validation_error",
                                  f"body.properties.Note.rich_text[{i}].text.content should be "
                                  f"a string, instead was 'undefined'.")

        # --- Business validation ---
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        row = c.execute("SELECT screening_status FROM customers WHERE customer_id=?",
                        (customer_id,)).fetchone()
        if row is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find customer with ID: {customer_id}.")

        # --- Record the review case ---
        c.execute("""CREATE TABLE IF NOT EXISTS screening_review_cases (
            customer_id TEXT PRIMARY KEY,
            review_priority TEXT NOT NULL,
            risk_score REAL
        )""")
        c.execute("INSERT OR REPLACE INTO screening_review_cases "
                  "(customer_id, review_priority, risk_score) VALUES (?, ?, ?)",
                  (customer_id, pri_name, risk_score))
        conn.commit()
        conn.close()

        # Success response: deep echo, shape entirely different from errors.
        echo_props: Dict[str, Any] = {
            "Priority": {"type": "select", "select": {"name": pri_name}},
        }
        if risk_score is not None:
            echo_props["RiskScore"] = {"type": "number", "number": risk_score}
        return {
            "object": "review_case",
            "id": "case_" + hashlib.md5(f"{customer_id}:{pri_name}".encode()).hexdigest()[:10],
            "parent": {"type": "review_queue", "customer_id": customer_id},
            "properties": echo_props,
            "created": True,
        }

    # -----------------------------------------------------------------------
    # Ground-truth computation (used by step and verify)
    # -----------------------------------------------------------------------
    def _load_config(self) -> dict:
        """Load screening config from workspace."""
        import yaml
        filepath = os.path.join(self.workspace, "screening_config.yaml")
        with open(filepath) as f:
            return yaml.safe_load(f)

    def _load_country_risk(self) -> dict:
        """Load country risk matrix from workspace."""
        filepath = os.path.join(self.workspace, "country_risk_matrix.csv")
        risk = {}
        with open(filepath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                risk[row["country"].strip()] = int(row["risk_tier"])
        return risk

    def _load_customer_aliases(self) -> dict:
        """Load customer aliases from workspace JSON files."""
        aliases = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "customer_batch_*.json"))):
            with open(fp) as f:
                for rec in json.load(f):
                    aliases[rec["customer_id"]] = rec.get("aliases", [])
        return aliases

    def _load_pep_info(self) -> dict:
        """Load PEP info from workspace YAML files. Returns {customer_id: [{owner, pep_country}]}."""
        import yaml
        pep_info = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "ubo_batch_*.yaml"))):
            with open(fp) as f:
                declarations = yaml.safe_load(f)
            if not declarations:
                continue
            for decl in declarations:
                cid = decl["customer_id"]
                pep_owners = []
                for bo in decl.get("beneficial_owners", []):
                    if bo.get("pep_status"):
                        pep_owners.append({
                            "beneficial_owner": bo["beneficial_owner"],
                            "pep_country": bo.get("pep_country"),
                        })
                if pep_owners:
                    pep_info[cid] = pep_owners
        return pep_info

    def _compute_ground_truth(self) -> List[dict]:
        """Compute the expected screening results for all customers."""
        config = self._load_config()
        country_risk = self._load_country_risk()
        customer_aliases = self._load_customer_aliases()
        pep_info = self._load_pep_info()

        threshold = config["name_match_threshold"]
        ubo_own_threshold = config["ubo_ownership_screening_threshold"]
        country_tier_threshold = config["country_risk_tier_flag_threshold"]
        weights = config["risk_score_weights"]
        priority_thresholds = config["priority_thresholds"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        customers = conn.execute(
            "SELECT * FROM customers WHERE screening_status='pending' ORDER BY customer_id"
        ).fetchall()

        sanctions = conn.execute("SELECT * FROM sanctions_entries").fetchall()
        alias_rows = conn.execute("SELECT entry_id, alias_name FROM sanctions_aliases").fetchall()
        san_aliases = {}
        for r in alias_rows:
            san_aliases.setdefault(r["entry_id"], []).append(r["alias_name"])

        intermediaries = {}
        for r in conn.execute("SELECT * FROM payment_intermediaries").fetchall():
            intermediaries.setdefault(r["customer_id"], []).append(dict(r))

        ubos = {}
        for r in conn.execute("SELECT * FROM ubo_structures").fetchall():
            ubos.setdefault(r["customer_id"], []).append(dict(r))

        conn.close()

        def find_matches(query_name):
            """Find sanctions entries matching a name above threshold."""
            matched = []
            for san in sanctions:
                sim = self._name_similarity(query_name, san["entity_name"])
                for alias in san_aliases.get(san["entry_id"], []):
                    alias_sim = self._name_similarity(query_name, alias)
                    sim = max(sim, alias_sim)
                if sim >= threshold:
                    matched.append(san["entry_id"])
            return matched

        results = []
        for cust in customers:
            cid = cust["customer_id"]
            flags = set()
            matched_san_ids = set()

            # 1. Direct name match
            name_matches = find_matches(cust["full_name"])
            if name_matches:
                flags.add("direct_name_match")
                matched_san_ids.update(name_matches)

            # 2. Alias matches
            for alias in customer_aliases.get(cid, []):
                alias_matches = find_matches(alias)
                if alias_matches:
                    flags.add("alias_match")
                    matched_san_ids.update(alias_matches)

            # 3. Intermediary screening
            for intm in intermediaries.get(cid, []):
                # Check intermediary name against sanctions
                intm_matches = find_matches(intm["intermediary_name"])
                if intm_matches:
                    flags.add("intermediary_sanctions_match")
                    matched_san_ids.update(intm_matches)

                # Check intermediary country
                tier = country_risk.get(intm["intermediary_country"], 2)
                if tier >= country_tier_threshold:
                    flags.add("high_risk_country_intermediary")

            # 4. UBO screening
            for ubo in ubos.get(cid, []):
                if ubo["ownership_percentage"] >= ubo_own_threshold:
                    ubo_matches = find_matches(ubo["beneficial_owner_name"])
                    if ubo_matches:
                        flags.add("ubo_sanctions_match")
                        matched_san_ids.update(ubo_matches)

            # 5. PEP in high-risk country
            for pep_rec in pep_info.get(cid, []):
                pep_country = pep_rec.get("pep_country")
                if pep_country:
                    tier = country_risk.get(pep_country, 2)
                    if tier >= country_tier_threshold:
                        flags.add("pep_high_risk_country")

            # Compute risk score
            risk_score = sum(weights.get(f, 0) for f in flags)

            # Priority
            if risk_score >= priority_thresholds["critical"]:
                priority = "CRITICAL"
            elif risk_score >= priority_thresholds["high"]:
                priority = "HIGH"
            elif risk_score >= priority_thresholds["medium"]:
                priority = "MEDIUM"
            elif risk_score > 0:
                priority = "LOW"
            else:
                priority = "CLEAR"

            results.append({
                "customer_id": cid,
                "customer_name": cust["full_name"],
                "risk_score": risk_score,
                "flagged": risk_score > 0,
                "flag_reasons": sorted(flags),
                "matched_sanctions_ids": sorted(matched_san_ids),
                "review_priority": priority,
            })

        # Sort by risk_score desc, then customer_id asc
        results.sort(key=lambda x: (-x["risk_score"], x["customer_id"]))
        return results

    # -----------------------------------------------------------------------
    # Step: evaluate
    # -----------------------------------------------------------------------
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
        gt_by_id = {r["customer_id"]: r for r in ground_truth}

        criteria = {}

        # --- Criterion 1: File existence and format (10 pts) ---
        csv_path = os.path.join(self.workspace, "screening_results.csv")
        expected_cols = {"customer_id", "customer_name", "risk_score", "flagged",
                         "flag_reasons", "matched_sanctions_ids", "review_priority"}
        file_ok = False
        agent_rows = []
        if os.path.exists(csv_path):
            with open(csv_path, "r") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and expected_cols.issubset(set(reader.fieldnames)):
                    file_ok = True
                    for row in reader:
                        agent_rows.append(row)
        criteria["file_format"] = {
            "passed": file_ok,
            "score": 10 if file_ok else 0,
            "max_score": 10,
            "reason": "" if file_ok else "screening_results.csv missing or has wrong columns",
        }

        # --- Criterion 2: Customer completeness (15 pts) ---
        agent_ids = {r["customer_id"] for r in agent_rows}
        gt_ids = {r["customer_id"] for r in ground_truth}
        coverage = len(agent_ids & gt_ids) / len(gt_ids) if gt_ids else 0
        comp_score = round(coverage * 15)
        criteria["customer_completeness"] = {
            "passed": coverage == 1.0,
            "score": comp_score,
            "max_score": 15,
            "reason": "" if coverage == 1.0 else f"Coverage {coverage:.2%}, missing {len(gt_ids - agent_ids)} customers",
        }

        # --- Criterion 3: Flagged customer accuracy (25 pts) ---
        gt_flagged = {r["customer_id"] for r in ground_truth if r["flagged"]}
        agent_flagged = set()
        for r in agent_rows:
            val = r.get("flagged", "").strip().lower()
            if val in ("true", "yes", "1"):
                agent_flagged.add(r["customer_id"])

        tp = len(gt_flagged & agent_flagged)
        fp = len(agent_flagged - gt_flagged)
        fn = len(gt_flagged - agent_flagged)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        flag_score = round(f1 * 25)
        criteria["flagged_accuracy"] = {
            "passed": f1 >= 0.95,
            "score": flag_score,
            "max_score": 25,
            "reason": "" if f1 >= 0.95 else f"F1={f1:.3f} (P={precision:.3f}, R={recall:.3f}), TP={tp}, FP={fp}, FN={fn}",
        }

        # --- Criterion 4: Risk score accuracy (15 pts) ---
        score_correct = 0
        score_total = 0
        for r in agent_rows:
            cid = r.get("customer_id", "")
            if cid in gt_by_id:
                score_total += 1
                try:
                    agent_score = int(float(r.get("risk_score", "0")))
                    if agent_score == gt_by_id[cid]["risk_score"]:
                        score_correct += 1
                except (ValueError, TypeError):
                    pass
        score_acc = score_correct / score_total if score_total > 0 else 0
        risk_pts = round(score_acc * 15)
        criteria["risk_score_accuracy"] = {
            "passed": score_acc >= 0.95,
            "score": risk_pts,
            "max_score": 15,
            "reason": "" if score_acc >= 0.95 else f"Accuracy {score_acc:.2%} ({score_correct}/{score_total})",
        }

        # --- Criterion 5: Flag reasons correctness (15 pts) ---
        reason_correct = 0
        reason_total = 0
        for r in agent_rows:
            cid = r.get("customer_id", "")
            if cid in gt_by_id:
                reason_total += 1
                gt_reasons = gt_by_id[cid]["flag_reasons"]
                agent_reasons_raw = r.get("flag_reasons", "").strip()
                if agent_reasons_raw:
                    agent_reasons = sorted([x.strip() for x in agent_reasons_raw.split(";")])
                else:
                    agent_reasons = []
                if agent_reasons == gt_reasons:
                    reason_correct += 1
        reason_acc = reason_correct / reason_total if reason_total > 0 else 0
        reason_pts = round(reason_acc * 15)
        criteria["flag_reasons"] = {
            "passed": reason_acc >= 0.95,
            "score": reason_pts,
            "max_score": 15,
            "reason": "" if reason_acc >= 0.95 else f"Accuracy {reason_acc:.2%} ({reason_correct}/{reason_total})",
        }

        # --- Criterion 6: Matched sanctions IDs (10 pts) ---
        san_correct = 0
        san_total = 0
        for r in agent_rows:
            cid = r.get("customer_id", "")
            if cid in gt_by_id:
                san_total += 1
                gt_sids = gt_by_id[cid]["matched_sanctions_ids"]
                agent_sids_raw = r.get("matched_sanctions_ids", "").strip()
                if agent_sids_raw:
                    agent_sids = sorted([x.strip() for x in agent_sids_raw.split(";")])
                else:
                    agent_sids = []
                if agent_sids == gt_sids:
                    san_correct += 1
        san_acc = san_correct / san_total if san_total > 0 else 0
        san_pts = round(san_acc * 10)
        criteria["sanctions_ids"] = {
            "passed": san_acc >= 0.95,
            "score": san_pts,
            "max_score": 10,
            "reason": "" if san_acc >= 0.95 else f"Accuracy {san_acc:.2%} ({san_correct}/{san_total})",
        }

        # --- Criterion 7: Review priority (10 pts) ---
        pri_correct = 0
        pri_total = 0
        for r in agent_rows:
            cid = r.get("customer_id", "")
            if cid in gt_by_id:
                pri_total += 1
                if r.get("review_priority", "").strip().upper() == gt_by_id[cid]["review_priority"]:
                    pri_correct += 1
        pri_acc = pri_correct / pri_total if pri_total > 0 else 0
        pri_pts = round(pri_acc * 10)
        criteria["review_priority"] = {
            "passed": pri_acc >= 0.95,
            "score": pri_pts,
            "max_score": 10,
            "reason": "" if pri_acc >= 0.95 else f"Accuracy {pri_acc:.2%} ({pri_correct}/{pri_total})",
        }

        # --- Criterion 8: Review cases recorded via write API (10 pts) ---
        case_map = {}
        conn = sqlite3.connect(self.db_path)
        try:
            for cid, pri in conn.execute(
                    "SELECT customer_id, review_priority FROM screening_review_cases"):
                case_map[cid] = pri
        except sqlite3.OperationalError:
            pass
        conn.close()
        case_correct = sum(
            1 for r in ground_truth if case_map.get(r["customer_id"]) == r["review_priority"]
        )
        case_acc = case_correct / len(ground_truth) if ground_truth else 0
        case_pts = round(case_acc * 10)
        criteria["review_cases_recorded"] = {
            "passed": case_acc >= 0.95,
            "score": case_pts,
            "max_score": 10,
            "reason": "" if case_acc >= 0.95 else f"Accuracy {case_acc:.2%} ({case_correct}/{len(ground_truth)})",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # -----------------------------------------------------------------------
    # Verify: self-solve using only tools and workspace
    # -----------------------------------------------------------------------
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

        Note: the hardened tool surface requires JSON-encoded string request
        parameters for search_sanctions / list_pending_customers and nested
        request payloads for create_review_case.
        """
        import yaml

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # 1. Load config from workspace
        with open(os.path.join(self.workspace, "screening_config.yaml")) as f:
            config = yaml.safe_load(f)
        threshold = config["name_match_threshold"]
        ubo_own_threshold = config["ubo_ownership_screening_threshold"]
        country_tier_threshold = config["country_risk_tier_flag_threshold"]
        weights = config["risk_score_weights"]
        priority_thresholds = config["priority_thresholds"]

        # 2. Load country risk from workspace
        country_risk = {}
        with open(os.path.join(self.workspace, "country_risk_matrix.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                country_risk[row["country"].strip()] = int(row["risk_tier"])

        # 3. Load customer aliases from workspace JSON
        customer_aliases = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "customer_batch_*.json"))):
            with open(fp) as f:
                for rec in json.load(f):
                    customer_aliases[rec["customer_id"]] = rec.get("aliases", [])

        # 4. Load PEP info from workspace YAML
        pep_info = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "ubo_batch_*.yaml"))):
            with open(fp) as f:
                declarations = yaml.safe_load(f)
            if not declarations:
                continue
            for decl in declarations:
                cid = decl["customer_id"]
                for bo in decl.get("beneficial_owners", []):
                    if bo.get("pep_status"):
                        pep_info.setdefault(cid, []).append({
                            "beneficial_owner": bo["beneficial_owner"],
                            "pep_country": bo.get("pep_country"),
                        })

        # 5. List all pending customers via tool (paginated, empty JSON filter)
        all_customers = []
        page = 1
        while True:
            result = call_tool("list_pending_customers", page=page, page_size=10,
                               filter="{}")
            all_customers.extend(result["customers"])
            if page >= result["total_pages"]:
                break
            page += 1

        def search_matches(name):
            """Search sanctions via JSON-encoded string request; return matches."""
            resp = call_tool("search_sanctions", request=json.dumps({"query": name}))
            if resp.get("object") == "error":
                return []
            return resp["matches"]

        # 6. Screen each customer
        screening_results = []
        for cust in all_customers:
            cid = cust["customer_id"]
            cname = cust["full_name"]
            flags = set()
            matched_san_ids = set()

            # 6a. Search customer name against sanctions
            for m in search_matches(cname):
                if m["similarity_score"] >= threshold:
                    flags.add("direct_name_match")
                    matched_san_ids.add(m["entry_id"])

            # 6b. Search aliases
            for alias in customer_aliases.get(cid, []):
                for m in search_matches(alias):
                    if m["similarity_score"] >= threshold:
                        flags.add("alias_match")
                        matched_san_ids.add(m["entry_id"])

            # 6c. Check payment intermediaries
            intm_result = call_tool("get_payment_intermediaries", customer_id=cid)
            for intm in intm_result["intermediaries"]:
                # Check intermediary name against sanctions
                for m in search_matches(intm["intermediary_name"]):
                    if m["similarity_score"] >= threshold:
                        flags.add("intermediary_sanctions_match")
                        matched_san_ids.add(m["entry_id"])

                # Check intermediary country risk
                tier = country_risk.get(intm["intermediary_country"], 2)
                if tier >= country_tier_threshold:
                    flags.add("high_risk_country_intermediary")

            # 6d. Check UBO structure
            ubo_result = call_tool("get_ubo_structure", customer_id=cid)
            for ubo in ubo_result["ubo_records"]:
                if ubo["ownership_percentage"] >= ubo_own_threshold:
                    for m in search_matches(ubo["beneficial_owner_name"]):
                        if m["similarity_score"] >= threshold:
                            flags.add("ubo_sanctions_match")
                            matched_san_ids.add(m["entry_id"])

            # 6e. Check PEP in high-risk country
            for pep_rec in pep_info.get(cid, []):
                pep_country = pep_rec.get("pep_country")
                if pep_country:
                    tier = country_risk.get(pep_country, 2)
                    if tier >= country_tier_threshold:
                        flags.add("pep_high_risk_country")

            # Compute risk score
            risk_score = sum(weights.get(f, 0) for f in flags)

            # Priority
            if risk_score >= priority_thresholds["critical"]:
                priority = "CRITICAL"
            elif risk_score >= priority_thresholds["high"]:
                priority = "HIGH"
            elif risk_score >= priority_thresholds["medium"]:
                priority = "MEDIUM"
            elif risk_score > 0:
                priority = "LOW"
            else:
                priority = "CLEAR"

            screening_results.append({
                "customer_id": cid,
                "customer_name": cname,
                "risk_score": risk_score,
                "flagged": risk_score > 0,
                "flag_reasons": ";".join(sorted(flags)),
                "matched_sanctions_ids": ";".join(sorted(matched_san_ids)),
                "review_priority": priority,
            })

        # Sort by risk_score desc, customer_id asc
        screening_results.sort(key=lambda x: (-x["risk_score"], x["customer_id"]))

        # 7. File a review case for every customer via the nested write payload
        for r in screening_results:
            resp = call_tool("create_review_case", payload={
                "parent": {"type": "review_queue", "customer_id": r["customer_id"]},
                "properties": {
                    "Priority": {"type": "select", "select": {"name": r["review_priority"]}},
                    "RiskScore": {"type": "number", "number": r["risk_score"]},
                },
            })
            assert resp.get("object") == "review_case" and resp.get("created"), resp

        # 8. Write screening_results.csv
        csv_path = os.path.join(self.workspace, "screening_results.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "customer_id", "customer_name", "risk_score", "flagged",
                "flag_reasons", "matched_sanctions_ids", "review_priority"
            ])
            writer.writeheader()
            for r in screening_results:
                writer.writerow(r)

        # 9. Build action string with summary
        total = len(screening_results)
        flagged = sum(1 for r in screening_results if r["flagged"])
        critical = sum(1 for r in screening_results if r["review_priority"] == "CRITICAL")
        high = sum(1 for r in screening_results if r["review_priority"] == "HIGH")
        medium = sum(1 for r in screening_results if r["review_priority"] == "MEDIUM")
        low = sum(1 for r in screening_results if r["review_priority"] == "LOW")
        clear = sum(1 for r in screening_results if r["review_priority"] == "CLEAR")

        critical_list = [r for r in screening_results if r["review_priority"] == "CRITICAL"]

        action = (
            f"Screening complete. Total customers screened: {total}. "
            f"Flagged: {flagged}. Clear: {clear}. "
            f"Priority breakdown - CRITICAL: {critical}, HIGH: {high}, MEDIUM: {medium}, LOW: {low}. "
        )
        if critical_list:
            action += "CRITICAL priority customers: "
            action += ", ".join(
                f"{r['customer_id']} ({r['customer_name']}, score={r['risk_score']})"
                for r in critical_list
            )
            action += ". "
        action += "Results saved to screening_results.csv and all review cases filed."

        print(f"[verify] Tool calls made: {tool_call_count}")
        return self.step(action)
