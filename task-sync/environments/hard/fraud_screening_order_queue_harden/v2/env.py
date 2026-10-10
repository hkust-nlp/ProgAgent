"""
Fraud Screening Order Queue - Environment (hardened tool surface)

Hardened surface (M0 + M1 + M4):
  - M0: prompt.md de-proceduralized; scoring formulas live in the workspace
    scoring_methodology.md document, case recording in fraud_review_policy.txt.
  - M1: list_orders takes a single JSON-encoded string `filter` parameter
    (status / shipping_country / currency); malformed JSON or unsupported
    keys produce recoverable API-style errors.
  - M4: create_review_case takes a deeply nested request payload
    (parent + properties) validated layer by layer with Notion-style error
    messages, and records each queued order in the review_cases table.
    Success and error responses use completely different object shapes.
Task data, ground truth, deliverables, and original scoring criteria are
unchanged from the base environment; step() gains one DB-state criterion
for the recorded review cases (M4 write-tool conversion).
"""

import ast
import csv
import glob
import hashlib
import json
import math
import os
import sqlite3
from typing import Tuple, Dict, List, Any
from datetime import datetime, date

REFERENCE_DATE = date(2026, 4, 20)


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


REVIEW_QUEUE_ID = "fraud-review"


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

    # ------------------------------------------------------------------ #
    #  TOOLS                                                              #
    # ------------------------------------------------------------------ #

    @tool(
        description=(
            "Returns a paginated list of orders. Each entry contains order_id, "
            "customer_id, order_date, total_amount, currency, status, and "
            "shipping_country. Filtering is expressed as a JSON-encoded string, "
            "e.g. filter='{\"status\": \"pending_review\"}'. Supported filter "
            "properties: status (completed | pending_review | processing | "
            "cancelled | refunded), shipping_country (two-letter code), and "
            "currency."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"status\": \"pending_review\"}'. Pass '{}' or omit "
                        "for no filtering."
                    ),
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def list_orders(self, filter: Any = None, page: int = 1, page_size: int = 20):
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"status", "shipping_country", "currency"}
        for key in parsed:
            if key not in supported:
                return _error(
                    400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: status, shipping_country, currency.",
                )

        clauses = []
        params: list = []
        if "status" in parsed:
            status = parsed["status"]
            valid = ("completed", "pending_review", "processing", "cancelled", "refunded")
            if not isinstance(status, str) or status not in valid:
                return _error(
                    400, "validation_error",
                    f"body.filter.status should be one of \"completed\", "
                    f"\"pending_review\", \"processing\", \"cancelled\", "
                    f"\"refunded\", instead was {_shape(status)}.",
                )
            clauses.append("status = ?")
            params.append(status)
        if "shipping_country" in parsed:
            country = parsed["shipping_country"]
            if not isinstance(country, str) or not country:
                return _error(
                    400, "validation_error",
                    f"body.filter.shipping_country should be a non-empty string, "
                    f"instead was {_shape(country)}.",
                )
            clauses.append("shipping_country = ?")
            params.append(country)
        if "currency" in parsed:
            currency = parsed["currency"]
            if not isinstance(currency, str) or not currency:
                return _error(
                    400, "validation_error",
                    f"body.filter.currency should be a non-empty string, "
                    f"instead was {_shape(currency)}.",
                )
            clauses.append("currency = ?")
            params.append(currency)

        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            return _error(400, "validation_error",
                          f"body.page should be a positive integer, instead was {_shape(page)}.")
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
            return _error(400, "validation_error",
                          f"body.page_size should be a positive integer, instead was {_shape(page_size)}.")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        cur.execute(f"SELECT COUNT(*) FROM orders{where}", params)
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        cur.execute(
            f"SELECT order_id, customer_id, order_date, total_amount, currency, "
            f"status, shipping_country FROM orders{where} "
            f"ORDER BY order_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "orders": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    @tool(
        description=(
            "Get full details for a single order by its order_id, including "
            "the IP address used to place the order."
        ),
        parameters={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The order identifier, e.g. 'ORD-00012'.",
                },
            },
            "required": ["order_id"],
        },
    )
    def get_order_details(self, order_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find order with ID: {order_id}.")
        return dict(row)

    @tool(
        description=(
            "Retrieve the IP geolocation check result for a given order. "
            "Returns IP country, customer country, mismatch flag, proxy/VPN "
            "detection indicators, and confidence score."
        ),
        parameters={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The order identifier.",
                },
            },
            "required": ["order_id"],
        },
    )
    def get_ip_geolocation_check(self, order_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM ip_geolocation_checks WHERE order_id = ?", (order_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find IP geolocation check with order ID: {order_id}.")
        return dict(row)

    @tool(
        description=(
            "Retrieve the card transaction record for a given order. Returns "
            "card last four digits, issuer bank, decline code, response "
            "message, retry count, and authorized amount."
        ),
        parameters={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The order identifier.",
                },
            },
            "required": ["order_id"],
        },
    )
    def get_card_transaction(self, order_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM card_transactions WHERE order_id = ?", (order_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find card transaction with order ID: {order_id}.")
        return dict(row)

    @tool(
        description=(
            "Retrieve the address verification result for a given order. "
            "Returns AVS response code, AVS score (0-100), component match "
            "flags, and overall verification status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The order identifier.",
                },
            },
            "required": ["order_id"],
        },
    )
    def get_address_verification(self, order_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM address_verifications WHERE order_id = ?", (order_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find address verification with order ID: {order_id}.")
        return dict(row)

    @tool(
        description=(
            "Retrieve basic profile information for a customer. Returns name, "
            "email, phone, registration date, country, and account tier."
        ),
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "integer",
                    "description": "The customer identifier.",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_customer_profile(self, customer_id: Any = None):
        if not isinstance(customer_id, int) or isinstance(customer_id, bool):
            return _error(400, "validation_error",
                          f"body.customer_id should be an integer, instead was {_shape(customer_id)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find customer with ID: {customer_id}.")
        return dict(row)

    @tool(
        description=(
            "Records an order as a review case in a manual review queue. The "
            "request body must contain a `parent` object identifying the "
            "receiving review queue and a `properties` object with an `Order` "
            "reference property and a `RiskLevel` select property. Example "
            "body: {\"parent\": {\"type\": \"review_queue\", \"queue_id\": "
            "\"fraud-review\"}, \"properties\": {\"Order\": {\"type\": "
            "\"reference\", \"reference\": {\"order_id\": \"ORD-00012\"}}, "
            "\"RiskLevel\": {\"type\": \"select\", \"select\": {\"name\": "
            "\"HIGH\"}}}}. An optional `Note` rich_text property may be "
            "included in `properties`. On success the order is registered as "
            "a case in the queue's ledger."
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
                                "The review queue that receives the case. Must "
                                "contain type='review_queue' and a queue_id "
                                "string."
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
                                "Case properties. Must include an 'Order' "
                                "reference property and a 'RiskLevel' select "
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
    def create_review_case(self, payload: Any = None):
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
        if parent.get("type") != "review_queue":
            return _error(
                400, "validation_error",
                f"body.parent.type should be \"review_queue\", instead was "
                f"{_shape(parent.get('type'))}.",
            )
        queue_id = parent.get("queue_id")
        if not isinstance(queue_id, str) or not queue_id:
            return _error(
                400, "validation_error",
                f"body.parent.queue_id should be a non-empty string, instead was "
                f"{_shape(queue_id)}.",
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

        order_prop = props.get("Order")
        if order_prop is None:
            return _error(
                400, "validation_error",
                "body.properties.Order should be defined, instead was 'undefined'.",
            )
        if not isinstance(order_prop, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Order should be an object, instead was "
                f"{_shape(order_prop)}.",
            )
        if order_prop.get("type") != "reference":
            return _error(
                400, "validation_error",
                f"body.properties.Order.type should be \"reference\", instead was "
                f"{_shape(order_prop.get('type'))}.",
            )
        reference = order_prop.get("reference")
        if not isinstance(reference, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Order.reference should be an object, instead was "
                f"{_shape(reference)}.",
            )
        order_id = reference.get("order_id")
        if not isinstance(order_id, str) or not order_id:
            return _error(
                400, "validation_error",
                f"body.properties.Order.reference.order_id should be a non-empty "
                f"string, instead was {_shape(order_id)}.",
            )

        level_prop = props.get("RiskLevel")
        if level_prop is None:
            return _error(
                400, "validation_error",
                "body.properties.RiskLevel should be defined, instead was 'undefined'.",
            )
        if not isinstance(level_prop, dict):
            return _error(
                400, "validation_error",
                f"body.properties.RiskLevel should be an object, instead was "
                f"{_shape(level_prop)}.",
            )
        if level_prop.get("type") != "select":
            return _error(
                400, "validation_error",
                f"body.properties.RiskLevel.type should be \"select\", instead was "
                f"{_shape(level_prop.get('type'))}.",
            )
        select = level_prop.get("select")
        if not isinstance(select, dict):
            return _error(
                400, "validation_error",
                f"body.properties.RiskLevel.select should be an object, instead was "
                f"{_shape(select)}.",
            )
        level_name = select.get("name")
        if not isinstance(level_name, str) or not level_name:
            return _error(
                400, "validation_error",
                f"body.properties.RiskLevel.select.name should be a non-empty "
                f"string, instead was {_shape(level_name)}.",
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
        if queue_id != REVIEW_QUEUE_ID:
            return _error(
                404, "object_not_found",
                f"Could not find review queue with ID: {queue_id}.",
            )
        if level_name not in ("HIGH", "MEDIUM"):
            return _error(
                400, "validation_error",
                f"body.properties.RiskLevel.select.name should be \"HIGH\" or "
                f"\"MEDIUM\", instead was {_shape(level_name)}.",
            )

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT status FROM orders WHERE order_id = ?", (order_id,))
        row = cur.fetchone()
        if row is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find order with ID: {order_id}.",
            )
        if row[0] != "pending_review":
            conn.close()
            return _error(
                400, "validation_error",
                f"Order '{order_id}' is not pending review (status='{row[0]}').",
            )

        # --- Record the case ---
        cur.execute(
            "CREATE TABLE IF NOT EXISTS review_cases ("
            "order_id TEXT PRIMARY KEY, queue_id TEXT, risk_level TEXT)"
        )
        cur.execute(
            "INSERT OR REPLACE INTO review_cases (order_id, queue_id, risk_level) "
            "VALUES (?, ?, ?)",
            (order_id, queue_id, level_name),
        )
        conn.commit()
        conn.close()

        # Success response: deep echo, shape entirely different from errors.
        return {
            "object": "review_case",
            "id": "case_" + hashlib.md5(f"{order_id}:{queue_id}".encode()).hexdigest()[:10],
            "parent": {"type": "review_queue", "queue_id": queue_id},
            "properties": {
                "Order": {"type": "reference", "reference": {"order_id": order_id}},
                "RiskLevel": {"type": "select", "select": {"name": level_name}},
            },
            "created": True,
        }

    # ------------------------------------------------------------------ #
    #  GROUND TRUTH COMPUTATION (used by step)                            #
    # ------------------------------------------------------------------ #

    def _compute_ground_truth(self):
        """Compute the expected fraud review queue from DB + workspace."""

        # --- load workspace config ---
        import yaml

        with open(os.path.join(self.workspace, "risk_scoring_config.yaml")) as f:
            cfg = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "issuer_response_codes.json")) as f:
            irc = json.load(f)

        avs_tiers = []
        with open(os.path.join(self.workspace, "avs_score_tiers.csv"), newline="") as f:
            for row in csv.DictReader(f):
                avs_tiers.append({
                    "min": int(row["min_score"]),
                    "max": int(row["max_score"]),
                    "risk_points": int(row["risk_points"]),
                })

        # customer risk profiles from workspace
        cust_risk = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "customer_risk_profile_batch_*.csv"))):
            with open(fp, newline="") as f:
                for row in csv.DictReader(f):
                    cust_risk[int(row["customer_id"])] = {
                        "previous_fraud_count": int(row["previous_fraud_count"]),
                        "chargeback_count": int(row["chargeback_count"]),
                        "account_age_days": int(row["account_age_days"]),
                    }

        # transaction patterns from workspace
        txn_pat = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "transaction_pattern_batch_*.json"))):
            with open(fp) as f:
                for rec in json.load(f):
                    txn_pat[rec["order_id"]] = {
                        "rapid_order_flag": int(rec["rapid_order_flag"]),
                        "unusual_amount_flag": int(rec["unusual_amount_flag"]),
                        "multiple_address_flag": int(rec["multiple_address_flag"]),
                    }

        # --- load DB data ---
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT * FROM orders WHERE status = 'pending_review' ORDER BY order_id")
        pending = [dict(r) for r in cur.fetchall()]

        results = []
        for order in pending:
            oid = order["order_id"]
            cid = order["customer_id"]

            # IP check
            cur.execute("SELECT * FROM ip_geolocation_checks WHERE order_id = ?", (oid,))
            ip = dict(cur.fetchone())

            # card transaction
            cur.execute("SELECT * FROM card_transactions WHERE order_id = ?", (oid,))
            card = dict(cur.fetchone())

            # address verification
            cur.execute("SELECT * FROM address_verifications WHERE order_id = ?", (oid,))
            addr = dict(cur.fetchone())

            # risk factor config
            rf = cfg["risk_factors"]

            # IP risk
            ip_risk = 0
            if ip["mismatch_flag"]:
                ip_risk += rf["ip_geolocation"]["mismatch_points"]
            if ip["proxy_detected"] or ip["vpn_detected"]:
                ip_risk += rf["ip_geolocation"]["proxy_vpn_points"]

            # card risk
            decline_code = card["decline_code"]
            card_sev = irc.get(decline_code, {}).get("severity", 0)
            card_risk = min(card_sev, rf["card_issuer"]["max_points"])

            # avs risk
            avs_score = addr["avs_score"]
            avs_risk = 0
            for tier in avs_tiers:
                if tier["min"] <= avs_score <= tier["max"]:
                    avs_risk = tier["risk_points"]
                    break
            avs_risk = min(avs_risk, rf["address_verification"]["max_points"])

            # history risk
            cr = cust_risk.get(cid, {"previous_fraud_count": 0, "chargeback_count": 0, "account_age_days": 999})
            history_risk = (
                cr["previous_fraud_count"] * rf["customer_history"]["fraud_count_multiplier"]
                + cr["chargeback_count"] * rf["customer_history"]["chargeback_multiplier"]
            )
            if cr["account_age_days"] < rf["customer_history"]["new_account_threshold_days"]:
                history_risk += rf["customer_history"]["new_account_bonus"]

            # transaction pattern risk
            tp = txn_pat.get(oid, {"rapid_order_flag": 0, "unusual_amount_flag": 0, "multiple_address_flag": 0})
            pattern_risk = (
                tp["rapid_order_flag"] * rf["transaction_patterns"]["rapid_order_points"]
                + tp["unusual_amount_flag"] * rf["transaction_patterns"]["unusual_amount_points"]
                + tp["multiple_address_flag"] * rf["transaction_patterns"]["multiple_address_points"]
            )

            total = ip_risk + card_risk + avs_risk + history_risk + pattern_risk
            cap = cfg["output_requirements"]["score_cap"]
            total = min(total, cap)

            high_t = cfg["thresholds"]["high_risk"]
            med_t = cfg["thresholds"]["medium_risk"]
            if total >= high_t:
                level = "HIGH"
            elif total >= med_t:
                level = "MEDIUM"
            else:
                level = "LOW"

            # recommended actions
            actions = self._get_recommended_actions(
                ip["mismatch_flag"],
                ip["proxy_detected"] or ip["vpn_detected"],
                card_sev, avs_risk,
                cr["previous_fraud_count"], cr["chargeback_count"],
                tp["rapid_order_flag"], tp["unusual_amount_flag"],
                tp["multiple_address_flag"],
            )

            results.append({
                "order_id": oid,
                "risk_score": total,
                "risk_level": level,
                "ip_risk": ip_risk,
                "card_risk": card_risk,
                "avs_risk": avs_risk,
                "history_risk": history_risk,
                "pattern_risk": pattern_risk,
                "recommended_actions": "; ".join(actions),
            })

        conn.close()

        # filter to HIGH/MEDIUM, sort
        queue = [r for r in results if r["risk_level"] in ("HIGH", "MEDIUM")]
        queue.sort(key=lambda x: (-x["risk_score"], x["order_id"]))

        return {
            "total_pending": len(pending),
            "queue": queue,
            "high_count": sum(1 for r in queue if r["risk_level"] == "HIGH"),
            "medium_count": sum(1 for r in queue if r["risk_level"] == "MEDIUM"),
        }

    @staticmethod
    def _get_recommended_actions(
        mismatch_flag, proxy_or_vpn, card_severity, avs_risk,
        prev_fraud, chargebacks, rapid, unusual, multi_addr
    ):
        actions = []
        if mismatch_flag:
            actions.append(
                "Verify customer identity via phone call and confirm shipping destination"
            )
        if proxy_or_vpn:
            actions.append(
                "Request customer to disable VPN and retry transaction, escalate to senior analyst if refused"
            )
        if card_severity >= 10:
            actions.append(
                "Contact card issuer for manual verification and request 3D Secure re-authentication"
            )
        elif card_severity >= 5:
            actions.append(
                "Request additional cardholder identity verification"
            )
        if avs_risk >= 12:
            actions.append(
                "Place shipment on hold and confirm shipping address via registered email"
            )
        elif avs_risk >= 5:
            actions.append(
                "Send address confirmation request before dispatching"
            )
        if prev_fraud > 0:
            actions.append(
                "Escalate to senior fraud analyst for full manual review"
            )
        if chargebacks > 2:
            actions.append(
                "Require alternative payment method or prepayment before processing"
            )
        if rapid:
            actions.append(
                "Verify order intent with customer and check for bot activity"
            )
        if unusual:
            actions.append(
                "Confirm order amount directly with customer before processing"
            )
        if multi_addr:
            actions.append(
                "Verify all shipping addresses on file with customer"
            )
        return actions

    # ------------------------------------------------------------------ #
    #  STEP                                                               #
    # ------------------------------------------------------------------ #

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
        gt = self._compute_ground_truth()
        criteria = {}

        # ---- 1. File exists & correct columns (10 pts) ----
        csv_path = os.path.join(self.workspace, "fraud_review_queue.csv")
        expected_cols = [
            "order_id", "risk_score", "risk_level", "ip_risk",
            "card_risk", "avs_risk", "history_risk", "pattern_risk",
            "recommended_actions",
        ]
        if os.path.isfile(csv_path):
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                actual_cols = list(reader.fieldnames or [])
                submitted_rows = list(reader)
            cols_ok = actual_cols == expected_cols
            criteria["file_structure"] = {
                "passed": cols_ok,
                "score": 10 if cols_ok else 3,
                "max_score": 10,
                "reason": None if cols_ok else f"Expected columns {expected_cols}, got {actual_cols}",
            }
        else:
            submitted_rows = []
            criteria["file_structure"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": "fraud_review_queue.csv not found in workspace.",
            }

        # ---- 2. Correct order IDs in queue (20 pts) ----
        expected_ids = {r["order_id"] for r in gt["queue"]}
        submitted_ids = {r["order_id"] for r in submitted_rows}
        ids_match = expected_ids == submitted_ids
        if expected_ids:
            id_overlap = len(expected_ids & submitted_ids) / len(expected_ids | submitted_ids)
        else:
            id_overlap = 1.0 if not submitted_ids else 0.0
        id_score = round(20 * id_overlap)
        criteria["order_ids"] = {
            "passed": ids_match,
            "score": id_score,
            "max_score": 20,
            "reason": None if ids_match else (
                f"Missing: {expected_ids - submitted_ids}, Extra: {submitted_ids - expected_ids}"
            ),
        }

        # Build lookup for submitted data
        sub_by_id = {r["order_id"]: r for r in submitted_rows}
        gt_by_id = {r["order_id"]: r for r in gt["queue"]}

        # ---- 3. Risk level classification (15 pts) ----
        common = expected_ids & submitted_ids
        if common:
            correct_levels = sum(
                1 for oid in common
                if sub_by_id[oid].get("risk_level", "").strip().upper() == gt_by_id[oid]["risk_level"]
            )
            level_ratio = correct_levels / len(common)
        else:
            level_ratio = 0.0
        level_score = round(15 * level_ratio)
        criteria["risk_levels"] = {
            "passed": level_ratio == 1.0,
            "score": level_score,
            "max_score": 15,
            "reason": None if level_ratio == 1.0 else f"{round(level_ratio*100,1)}% correct levels.",
        }

        # ---- 4. Risk score accuracy (20 pts, within +/- 2) ----
        if common:
            correct_scores = 0
            for oid in common:
                try:
                    sub_score = int(float(sub_by_id[oid].get("risk_score", -999)))
                except (ValueError, TypeError):
                    sub_score = -999
                if abs(sub_score - gt_by_id[oid]["risk_score"]) <= 2:
                    correct_scores += 1
            score_ratio = correct_scores / len(common)
        else:
            score_ratio = 0.0
        score_pts = round(20 * score_ratio)
        criteria["risk_scores"] = {
            "passed": score_ratio == 1.0,
            "score": score_pts,
            "max_score": 20,
            "reason": None if score_ratio == 1.0 else f"{round(score_ratio*100,1)}% scores within tolerance.",
        }

        # ---- 5. Sort order (10 pts) ----
        if len(submitted_rows) >= 2:
            sorted_ok = True
            for i in range(len(submitted_rows) - 1):
                try:
                    s1 = int(float(submitted_rows[i].get("risk_score", 0)))
                    s2 = int(float(submitted_rows[i + 1].get("risk_score", 0)))
                except (ValueError, TypeError):
                    sorted_ok = False
                    break
                if s1 < s2:
                    sorted_ok = False
                    break
                if s1 == s2 and submitted_rows[i]["order_id"] > submitted_rows[i + 1]["order_id"]:
                    sorted_ok = False
                    break
        else:
            sorted_ok = len(submitted_rows) == len(gt["queue"])
        sort_score = 10 if sorted_ok else 0
        criteria["sort_order"] = {
            "passed": sorted_ok,
            "score": sort_score,
            "max_score": 10,
            "reason": None if sorted_ok else "Rows not sorted by risk_score desc / order_id asc.",
        }

        # ---- 6. Recommended actions (15 pts) ----
        if common:
            action_matches = 0
            for oid in common:
                expected_actions = gt_by_id[oid]["recommended_actions"]
                submitted_actions = sub_by_id[oid].get("recommended_actions", "").strip()
                if submitted_actions == expected_actions:
                    action_matches += 1
            action_ratio = action_matches / len(common)
        else:
            action_ratio = 0.0
        action_score = round(15 * action_ratio)
        criteria["recommended_actions"] = {
            "passed": action_ratio == 1.0,
            "score": action_score,
            "max_score": 15,
            "reason": None if action_ratio == 1.0 else f"{round(action_ratio*100,1)}% actions correct.",
        }

        # ---- 7. Response summary (10 pts) ----
        resp = action or ""
        summary_score = 0
        # Check total pending count
        if str(gt["total_pending"]) in resp:
            summary_score += 3
        # Check high count
        if str(gt["high_count"]) in resp:
            summary_score += 2
        # Check medium count
        if str(gt["medium_count"]) in resp:
            summary_score += 2
        # Check top 3 order IDs
        top3 = gt["queue"][:3]
        top3_found = 0
        for entry in top3:
            pattern = f"{entry['order_id']}: {entry['risk_score']}"
            if pattern in resp:
                top3_found += 1
            else:
                # also accept without space
                pattern2 = f"{entry['order_id']}:{entry['risk_score']}"
                if pattern2 in resp:
                    top3_found += 1
        if top3:
            summary_score += round(3 * top3_found / len(top3))
        else:
            summary_score += 3
        summary_ok = summary_score == 10
        criteria["response_summary"] = {
            "passed": summary_ok,
            "score": summary_score,
            "max_score": 10,
            "reason": None if summary_ok else "Some summary elements missing from response.",
        }

        # ---- 8. Review cases recorded in DB (10 pts, M4 write-tool criterion) ----
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='review_cases'"
        )
        if cur.fetchone() is not None:
            cur.execute(
                "SELECT order_id, risk_level FROM review_cases WHERE queue_id = ?",
                (REVIEW_QUEUE_ID,),
            )
            db_cases = {r[0]: r[1] for r in cur.fetchall()}
        else:
            db_cases = {}
        conn.close()
        if gt["queue"]:
            recorded = sum(
                1 for r in gt["queue"] if db_cases.get(r["order_id"]) == r["risk_level"]
            )
            case_ratio = recorded / len(gt["queue"])
        else:
            case_ratio = 1.0 if not db_cases else 0.0
        case_score = round(10 * case_ratio)
        criteria["review_cases_recorded"] = {
            "passed": case_ratio == 1.0,
            "score": case_score,
            "max_score": 10,
            "reason": None if case_ratio == 1.0 else (
                f"{round(case_ratio*100,1)}% of queued orders recorded as review cases."
            ),
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ------------------------------------------------------------------ #
    #  VERIFY                                                             #
    # ------------------------------------------------------------------ #

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.

        Note: the hardened tool surface requires a JSON-encoded string filter
        for list_orders and nested request payloads for create_review_case.
        """
        import yaml

        tool_calls = 0

        def _call(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        # --- Read workspace config files ---
        with open(os.path.join(self.workspace, "risk_scoring_config.yaml")) as f:
            cfg = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "issuer_response_codes.json")) as f:
            irc = json.load(f)

        avs_tiers = []
        with open(os.path.join(self.workspace, "avs_score_tiers.csv"), newline="") as f:
            for row in csv.DictReader(f):
                avs_tiers.append({
                    "min": int(row["min_score"]),
                    "max": int(row["max_score"]),
                    "risk_points": int(row["risk_points"]),
                })

        # Read all customer risk profiles
        cust_risk = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "customer_risk_profile_batch_*.csv"))):
            with open(fp, newline="") as f:
                for row in csv.DictReader(f):
                    cust_risk[int(row["customer_id"])] = {
                        "previous_fraud_count": int(row["previous_fraud_count"]),
                        "chargeback_count": int(row["chargeback_count"]),
                        "account_age_days": int(row["account_age_days"]),
                    }

        # Read all transaction patterns
        txn_pat = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "transaction_pattern_batch_*.json"))):
            with open(fp) as f:
                for rec in json.load(f):
                    txn_pat[rec["order_id"]] = {
                        "rapid_order_flag": int(rec["rapid_order_flag"]),
                        "unusual_amount_flag": int(rec["unusual_amount_flag"]),
                        "multiple_address_flag": int(rec["multiple_address_flag"]),
                    }

        rf = cfg["risk_factors"]

        # --- Retrieve all pending_review orders via the JSON-string filter ---
        all_pending = []
        page = 1
        filter_str = json.dumps({"status": "pending_review"})
        while True:
            result = _call("list_orders", filter=filter_str, page=page, page_size=20)
            all_pending.extend(result["orders"])
            if page >= result["total_pages"]:
                break
            page += 1

        # --- For each pending order, gather risk signals via tools ---
        queue_data = []
        for order in all_pending:
            oid = order["order_id"]
            cid = order["customer_id"]

            ip_result = _call("get_ip_geolocation_check", order_id=oid)
            card_result = _call("get_card_transaction", order_id=oid)
            addr_result = _call("get_address_verification", order_id=oid)

            # IP risk
            ip_risk = 0
            mismatch_flag = ip_result["mismatch_flag"]
            proxy_or_vpn = ip_result["proxy_detected"] or ip_result["vpn_detected"]
            if mismatch_flag:
                ip_risk += rf["ip_geolocation"]["mismatch_points"]
            if proxy_or_vpn:
                ip_risk += rf["ip_geolocation"]["proxy_vpn_points"]

            # Card risk
            decline_code = card_result["decline_code"]
            card_sev = irc.get(decline_code, {}).get("severity", 0)
            card_risk = min(card_sev, rf["card_issuer"]["max_points"])

            # AVS risk
            avs_score = addr_result["avs_score"]
            avs_risk = 0
            for tier in avs_tiers:
                if tier["min"] <= avs_score <= tier["max"]:
                    avs_risk = tier["risk_points"]
                    break
            avs_risk = min(avs_risk, rf["address_verification"]["max_points"])

            # History risk
            cr = cust_risk.get(cid, {"previous_fraud_count": 0, "chargeback_count": 0, "account_age_days": 999})
            history_risk = (
                cr["previous_fraud_count"] * rf["customer_history"]["fraud_count_multiplier"]
                + cr["chargeback_count"] * rf["customer_history"]["chargeback_multiplier"]
            )
            if cr["account_age_days"] < rf["customer_history"]["new_account_threshold_days"]:
                history_risk += rf["customer_history"]["new_account_bonus"]

            # Pattern risk
            tp = txn_pat.get(oid, {"rapid_order_flag": 0, "unusual_amount_flag": 0, "multiple_address_flag": 0})
            pattern_risk = (
                tp["rapid_order_flag"] * rf["transaction_patterns"]["rapid_order_points"]
                + tp["unusual_amount_flag"] * rf["transaction_patterns"]["unusual_amount_points"]
                + tp["multiple_address_flag"] * rf["transaction_patterns"]["multiple_address_points"]
            )

            total = ip_risk + card_risk + avs_risk + history_risk + pattern_risk
            cap = cfg["output_requirements"]["score_cap"]
            total = min(total, cap)

            high_t = cfg["thresholds"]["high_risk"]
            med_t = cfg["thresholds"]["medium_risk"]
            if total >= high_t:
                level = "HIGH"
            elif total >= med_t:
                level = "MEDIUM"
            else:
                level = "LOW"

            # Recommended actions
            actions = self._get_recommended_actions(
                mismatch_flag, proxy_or_vpn,
                card_sev, avs_risk,
                cr["previous_fraud_count"], cr["chargeback_count"],
                tp["rapid_order_flag"], tp["unusual_amount_flag"],
                tp["multiple_address_flag"],
            )

            queue_data.append({
                "order_id": oid,
                "risk_score": total,
                "risk_level": level,
                "ip_risk": ip_risk,
                "card_risk": card_risk,
                "avs_risk": avs_risk,
                "history_risk": history_risk,
                "pattern_risk": pattern_risk,
                "recommended_actions": "; ".join(actions),
            })

        # Filter and sort
        queue = [r for r in queue_data if r["risk_level"] in ("HIGH", "MEDIUM")]
        queue.sort(key=lambda x: (-x["risk_score"], x["order_id"]))

        # Record each queued order as a review case (nested M4 payload)
        for entry in queue:
            result = _call(
                "create_review_case",
                payload={
                    "parent": {"type": "review_queue", "queue_id": "fraud-review"},
                    "properties": {
                        "Order": {
                            "type": "reference",
                            "reference": {"order_id": entry["order_id"]},
                        },
                        "RiskLevel": {
                            "type": "select",
                            "select": {"name": entry["risk_level"]},
                        },
                    },
                },
            )
            assert result.get("object") == "review_case" and result.get("created"), (
                f"create_review_case failed for {entry['order_id']}: {result}"
            )

        # Write fraud_review_queue.csv
        csv_path = os.path.join(self.workspace, "fraud_review_queue.csv")
        fieldnames = [
            "order_id", "risk_score", "risk_level", "ip_risk",
            "card_risk", "avs_risk", "history_risk", "pattern_risk",
            "recommended_actions",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in queue:
                writer.writerow(row)

        # Build response summary
        high_count = sum(1 for r in queue if r["risk_level"] == "HIGH")
        medium_count = sum(1 for r in queue if r["risk_level"] == "MEDIUM")
        top3 = queue[:3]
        top3_str = ", ".join(f"{r['order_id']}: {r['risk_score']}" for r in top3)

        response = (
            f"Fraud review analysis complete. "
            f"Total pending orders reviewed: {len(all_pending)}. "
            f"HIGH risk orders: {high_count}. "
            f"MEDIUM risk orders: {medium_count}. "
            f"Top 3 highest-risk orders: {top3_str}."
        )

        assert tool_calls >= 15, f"Only {tool_calls} tool calls made; need at least 15."
        print(f"[verify] total tool calls: {tool_calls}")

        return self.step(response)
