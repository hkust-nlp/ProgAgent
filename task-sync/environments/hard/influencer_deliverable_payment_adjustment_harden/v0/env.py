"""
Influencer Deliverable Payment Adjustment - Environment (hardened tool surface)

Hardened surface (M0 + M1 + M4):
  - M0: prompt.md rewritten to specify the goal and deliverable contract only;
    business rules live in the workspace policy documents (payment_terms.md,
    compliance_rules.yaml, audit_methodology.md).
  - M1: list_contracts takes a single JSON-encoded string `filter` parameter;
    malformed JSON or unsupported/wrongly-typed keys produce recoverable
    API-style errors.
  - M4: the payment_adjustments.csv deliverable is converted into a write API:
    create_payment_adjustment takes a deeply nested request payload
    (parent + properties) validated layer by layer with Notion-style error
    messages, and records the adjustment in the database. step() criteria 3-5
    check DB state with the same ground truth comparisons and weights.
Task semantics, data generation, ground truth, and criterion weights are
otherwise unchanged from the base environment.
"""

import ast
import sqlite3
import os
import json
import csv
import hashlib
import yaml
from datetime import datetime
from typing import Tuple, Dict, List, Any


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


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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

    # ====================== TOOL METHODS ======================

    @tool(
        description=(
            "Returns a paginated list of contract summaries (contract_id, "
            "campaign_name, influencer_id, status). Filtering is expressed as a "
            "JSON-encoded string, e.g. filter='{\"status\": \"pending_review\"}'. "
            "Supported filter properties: status (pending_review | completed | "
            "cancelled) and influencer_id (integer). Pass '{}' or omit the filter "
            "for no filtering. Page size is 10."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"status\": \"pending_review\"}'. Supported properties: "
                        "status, influencer_id."
                    ),
                },
                "page": {
                    "type": "integer",
                    "description": "1-based page number. Defaults to 1.",
                },
            },
            "required": [],
        },
    )
    def list_contracts(self, filter: Any = None, page: Any = 1) -> dict:
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"status", "influencer_id"}
        for key in parsed:
            if key not in supported:
                return _error(
                    400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: status, influencer_id.",
                )

        clauses = []
        params: list = []
        if "status" in parsed:
            status = parsed["status"]
            if not isinstance(status, str) or status not in (
                "pending_review", "completed", "cancelled"
            ):
                return _error(
                    400, "validation_error",
                    f"body.filter.status should be one of \"pending_review\", "
                    f"\"completed\", \"cancelled\", instead was {_shape(status)}.",
                )
            clauses.append("status = ?")
            params.append(status)
        if "influencer_id" in parsed:
            inf_id = parsed["influencer_id"]
            if not _is_number(inf_id) or int(inf_id) != inf_id:
                return _error(
                    400, "validation_error",
                    f"body.filter.influencer_id should be an integer, instead was "
                    f"{_shape(inf_id)}.",
                )
            clauses.append("influencer_id = ?")
            params.append(int(inf_id))

        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            return _error(
                400, "validation_error",
                f"body.page should be a positive integer, instead was {_shape(page)}.",
            )

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        page_size = 10
        offset = (page - 1) * page_size
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        cur.execute(
            f"SELECT contract_id, campaign_name, influencer_id, status "
            f"FROM contracts{where} ORDER BY contract_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute(f"SELECT COUNT(*) FROM contracts{where}", params)
        total = cur.fetchone()[0]
        conn.close()
        return {
            "contracts": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description=(
            "Get full details for a single contract by its ID. Returns all "
            "contract fields including dates, engagement thresholds, payment, "
            "target region, and posting hour window."
        ),
        parameters={
            "type": "object",
            "properties": {
                "contract_id": {
                    "type": "integer",
                    "description": "The contract ID to look up.",
                },
            },
            "required": ["contract_id"],
        },
    )
    def get_contract_details(self, contract_id: Any = None) -> dict:
        if not _is_number(contract_id) or int(contract_id) != contract_id:
            return _error(
                400, "validation_error",
                f"body.contract_id should be an integer, instead was "
                f"{_shape(contract_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM contracts WHERE contract_id = ?", (int(contract_id),))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _error(
                404, "object_not_found",
                f"Could not find contract with ID: {contract_id}.",
            )
        return {"contract": dict(row)}

    @tool(
        description=(
            "List all posts associated with a specific contract. Returns post_id, "
            "posted_at, content_type, likes, comments, shares, and impressions "
            "for each post."
        ),
        parameters={
            "type": "object",
            "properties": {
                "contract_id": {
                    "type": "integer",
                    "description": "The contract ID whose posts to list.",
                },
            },
            "required": ["contract_id"],
        },
    )
    def list_contract_posts(self, contract_id: Any = None) -> dict:
        if not _is_number(contract_id) or int(contract_id) != contract_id:
            return _error(
                400, "validation_error",
                f"body.contract_id should be an integer, instead was "
                f"{_shape(contract_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT contract_id FROM contracts WHERE contract_id = ?",
            (int(contract_id),),
        )
        if cur.fetchone() is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find contract with ID: {contract_id}.",
            )
        cur.execute(
            "SELECT post_id, posted_at, content_type, likes, comments, shares, impressions "
            "FROM posts WHERE contract_id = ? ORDER BY post_id",
            (int(contract_id),),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"contract_id": int(contract_id), "posts": rows, "count": len(rows)}

    @tool(
        description=(
            "Get all bot detection scan records for a given post. Each record "
            "contains bot_score, flagged_accounts, scan_confidence, scan_method, "
            "and scan_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "post_id": {
                    "type": "integer",
                    "description": "The post ID to retrieve bot detection records for.",
                },
            },
            "required": ["post_id"],
        },
    )
    def get_bot_report(self, post_id: Any = None) -> dict:
        if not _is_number(post_id) or int(post_id) != post_id:
            return _error(
                400, "validation_error",
                f"body.post_id should be an integer, instead was {_shape(post_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT post_id FROM posts WHERE post_id = ?", (int(post_id),))
        if cur.fetchone() is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find post with ID: {post_id}.",
            )
        cur.execute(
            "SELECT detection_id, bot_score, flagged_accounts, scan_confidence, "
            "scan_method, scan_date FROM bot_detection WHERE post_id = ? "
            "ORDER BY scan_confidence DESC",
            (int(post_id),),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"post_id": int(post_id), "scans": rows, "count": len(rows)}

    @tool(
        description="Get influencer profile details by influencer ID.",
        parameters={
            "type": "object",
            "properties": {
                "influencer_id": {
                    "type": "integer",
                    "description": "The influencer ID.",
                },
            },
            "required": ["influencer_id"],
        },
    )
    def get_influencer(self, influencer_id: Any = None) -> dict:
        if not _is_number(influencer_id) or int(influencer_id) != influencer_id:
            return _error(
                400, "validation_error",
                f"body.influencer_id should be an integer, instead was "
                f"{_shape(influencer_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM influencers WHERE influencer_id = ?", (int(influencer_id),)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _error(
                404, "object_not_found",
                f"Could not find influencer with ID: {influencer_id}.",
            )
        return {"influencer": dict(row)}

    @tool(
        description=(
            "Records a payment adjustment for a reviewed contract in the "
            "adjustment ledger. The request body must contain a `parent` object "
            "identifying the ledger entry's contract and a `properties` object "
            "with `Penalty` and `AdjustedPayment` number properties. Example "
            "body: {\"parent\": {\"type\": \"adjustment_ledger\", "
            "\"contract_id\": \"17\"}, \"properties\": {\"Penalty\": {\"type\": "
            "\"number\", \"number\": 35}, \"AdjustedPayment\": {\"type\": "
            "\"number\", \"number\": 8125.50}}}. An optional `Note` rich_text "
            "property may be included in `properties`. Recording the same "
            "contract again overwrites its previous ledger entry. Only contracts "
            "that are pending review can be recorded."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "The adjustment request body.",
                    "properties": {
                        "parent": {
                            "type": "object",
                            "description": (
                                "The ledger entry target. Must contain "
                                "type='adjustment_ledger' and a contract_id "
                                "string."
                            ),
                            "properties": {
                                "type": {"type": "string"},
                                "contract_id": {"type": "string"},
                            },
                            "required": ["type", "contract_id"],
                            "additionalProperties": True,
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Adjustment properties. Must include 'Penalty' "
                                "and 'AdjustedPayment' number properties. May "
                                "include a 'Note' rich_text property."
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
    def create_payment_adjustment(self, payload: Any = None) -> dict:
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
        if parent.get("type") != "adjustment_ledger":
            return _error(
                400, "validation_error",
                f"body.parent.type should be \"adjustment_ledger\", instead was "
                f"{_shape(parent.get('type'))}.",
            )
        contract_id = parent.get("contract_id")
        if not isinstance(contract_id, str) or not contract_id:
            return _error(
                400, "validation_error",
                f"body.parent.contract_id should be a non-empty string, instead was "
                f"{_shape(contract_id)}.",
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

        numbers = {}
        for prop_name in ("Penalty", "AdjustedPayment"):
            prop = props.get(prop_name)
            if prop is None:
                return _error(
                    400, "validation_error",
                    f"body.properties.{prop_name} should be defined, instead was "
                    f"'undefined'.",
                )
            if not isinstance(prop, dict):
                return _error(
                    400, "validation_error",
                    f"body.properties.{prop_name} should be an object, instead was "
                    f"{_shape(prop)}.",
                )
            if prop.get("type") != "number":
                return _error(
                    400, "validation_error",
                    f"body.properties.{prop_name}.type should be \"number\", "
                    f"instead was {_shape(prop.get('type'))}.",
                )
            num = prop.get("number")
            if not _is_number(num):
                return _error(
                    400, "validation_error",
                    f"body.properties.{prop_name}.number should be a number, "
                    f"instead was {_shape(num)}.",
                )
            numbers[prop_name] = num

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
        try:
            cid_int = int(contract_id.strip())
        except ValueError:
            cid_int = None
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        row = None
        if cid_int is not None:
            cur.execute(
                "SELECT status FROM contracts WHERE contract_id = ?", (cid_int,)
            )
            row = cur.fetchone()
        if row is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find contract with ID: {contract_id}.",
            )
        if row[0] != "pending_review":
            conn.close()
            return _error(
                400, "validation_error",
                f"Contract '{contract_id}' is not pending review "
                f"(status='{row[0]}').",
            )

        # --- Record the adjustment (idempotent per contract) ---
        cur.execute(
            "CREATE TABLE IF NOT EXISTS payment_adjustments ("
            "contract_id INTEGER PRIMARY KEY, "
            "total_penalty_pct REAL, "
            "adjusted_payment REAL)"
        )
        cur.execute(
            "INSERT OR REPLACE INTO payment_adjustments "
            "(contract_id, total_penalty_pct, adjusted_payment) VALUES (?, ?, ?)",
            (cid_int, float(numbers["Penalty"]), float(numbers["AdjustedPayment"])),
        )
        conn.commit()
        conn.close()

        # Success response: deep echo, shape entirely different from errors.
        return {
            "object": "adjustment",
            "id": "adj_" + hashlib.md5(
                f"{cid_int}:{numbers['Penalty']}:{numbers['AdjustedPayment']}".encode()
            ).hexdigest()[:10],
            "parent": {"type": "adjustment_ledger", "contract_id": contract_id},
            "properties": {
                "Penalty": {"type": "number", "number": numbers["Penalty"]},
                "AdjustedPayment": {"type": "number", "number": numbers["AdjustedPayment"]},
                "Status": {"type": "select", "select": {"name": "recorded"}},
            },
            "created": True,
        }

    # ====================== GROUND TRUTH COMPUTATION ======================

    def _compute_ground_truth(self):
        """Compute the full ground truth using direct DB access and workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load compliance rules
        with open(os.path.join(self.workspace, "compliance_rules.yaml")) as f:
            rules = yaml.safe_load(f)

        # Load all audience data
        audience = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("audience_geo_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                    audience.update(data)

        region_map = rules["region_country_mapping"]
        max_bot = rules["bot_detection"]["max_bot_score"]
        min_conf = rules["bot_detection"]["min_scan_confidence"]

        cur = conn.cursor()

        # Get pending_review contracts
        cur.execute("SELECT * FROM contracts WHERE status = 'pending_review' ORDER BY contract_id")
        contracts = [dict(r) for r in cur.fetchall()]

        all_violations = []  # list of dicts
        payment_adjustments = []  # list of dicts

        for c in contracts:
            cid = c["contract_id"]
            cur.execute("SELECT * FROM posts WHERE contract_id = ? ORDER BY post_id", (cid,))
            contract_posts = [dict(r) for r in cur.fetchall()]

            violation_types_seen = set()

            for p in contract_posts:
                pid = p["post_id"]
                posted = datetime.strptime(p["posted_at"], "%Y-%m-%d %H:%M:%S")
                start_d = datetime.strptime(c["start_date"], "%Y-%m-%d")
                end_d = datetime.strptime(c["end_date"], "%Y-%m-%d")

                # Date violation
                if posted.date() < start_d.date() or posted.date() > end_d.date():
                    all_violations.append({
                        "post_id": pid, "contract_id": cid,
                        "violation_type": "date_violation",
                        "detail": f"Posted {posted.date()}, window {c['start_date']} to {c['end_date']}",
                    })
                    violation_types_seen.add("date_violation")

                # Hour violation
                if posted.hour < c["posting_hour_start"] or posted.hour > c["posting_hour_end"]:
                    all_violations.append({
                        "post_id": pid, "contract_id": cid,
                        "violation_type": "hour_violation",
                        "detail": f"Hour {posted.hour}, allowed {c['posting_hour_start']}-{c['posting_hour_end']}",
                    })
                    violation_types_seen.add("hour_violation")

                # Engagement
                eng_rate = (p["likes"] + p["comments"] + p["shares"]) / max(p["impressions"], 1)
                if eng_rate < c["min_engagement_rate"]:
                    all_violations.append({
                        "post_id": pid, "contract_id": cid,
                        "violation_type": "low_engagement",
                        "detail": f"Rate {eng_rate:.6f} < min {c['min_engagement_rate']}",
                    })
                    violation_types_seen.add("low_engagement")

                # Bot score
                cur.execute(
                    "SELECT bot_score, scan_confidence FROM bot_detection "
                    "WHERE post_id = ? AND scan_confidence >= ? "
                    "ORDER BY scan_confidence DESC LIMIT 1",
                    (pid, min_conf),
                )
                bot_row = cur.fetchone()
                if bot_row and bot_row["bot_score"] > max_bot:
                    all_violations.append({
                        "post_id": pid, "contract_id": cid,
                        "violation_type": "high_bot_score",
                        "detail": f"Bot score {bot_row['bot_score']} > max {max_bot}",
                    })
                    violation_types_seen.add("high_bot_score")

                # Audience location
                pid_str = str(pid)
                if pid_str in audience:
                    breakdown = audience[pid_str]["audience_breakdown"]
                    target_countries = region_map.get(c["target_region"], [])
                    region_pct = sum(breakdown.get(cc, 0.0) for cc in target_countries) / 100.0
                    if region_pct < c["min_region_pct"]:
                        all_violations.append({
                            "post_id": pid, "contract_id": cid,
                            "violation_type": "audience_location",
                            "detail": f"Region pct {region_pct:.4f} < min {c['min_region_pct']}",
                        })
                        violation_types_seen.add("audience_location")

            # Compute penalty
            penalty = 0
            if "date_violation" in violation_types_seen:
                penalty += rules["timing"]["date_violation_penalty_pct"]
            if "hour_violation" in violation_types_seen:
                penalty += rules["timing"]["hour_violation_penalty_pct"]
            if "low_engagement" in violation_types_seen:
                penalty += rules["engagement"]["penalty_pct"]
            if "high_bot_score" in violation_types_seen:
                penalty += rules["bot_detection"]["penalty_pct"]
            if "audience_location" in violation_types_seen:
                penalty += rules["audience_location"]["penalty_pct"]

            shortfall = max(c["required_posts"] - len(contract_posts), 0)
            penalty += shortfall * rules["post_count"]["penalty_per_missing_post_pct"]

            penalty = min(penalty, rules["max_total_penalty_pct"])
            adjusted = round(c["base_payment"] * (1 - penalty / 100), 2)

            payment_adjustments.append({
                "contract_id": cid,
                "campaign_name": c["campaign_name"],
                "base_payment": c["base_payment"],
                "total_penalty_pct": penalty,
                "adjusted_payment": adjusted,
            })

        conn.close()

        # Sort violations
        all_violations.sort(key=lambda v: (v["contract_id"], v["post_id"], v["violation_type"]))
        payment_adjustments.sort(key=lambda p: p["contract_id"])

        return all_violations, payment_adjustments

    # ====================== STEP ======================

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace, the database
        adjustment ledger, and the agent's final response.
        """
        gt_violations, gt_payments = self._compute_ground_truth()

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ---------- Criterion 1: flagged_posts.csv exists with correct columns (10 pts) ----------
        c1_max = 10
        max_score += c1_max
        fp_path = os.path.join(self.workspace, "flagged_posts.csv")
        fp_ok = False
        fp_rows = []
        expected_cols = {"post_id", "contract_id", "violation_type", "detail"}
        if os.path.exists(fp_path):
            try:
                with open(fp_path, newline="") as f:
                    reader = csv.DictReader(f)
                    cols = set(reader.fieldnames) if reader.fieldnames else set()
                    if expected_cols.issubset(cols):
                        fp_rows = list(reader)
                        fp_ok = True
            except Exception:
                pass

        if fp_ok:
            eval_criteria["flagged_posts_structure"] = {
                "passed": True, "score": c1_max, "max_score": c1_max,
            }
            total_score += c1_max
        else:
            eval_criteria["flagged_posts_structure"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "flagged_posts.csv missing or wrong columns",
            }

        # ---------- Criterion 2: flagged_posts content accuracy (25 pts) ----------
        c2_max = 25
        max_score += c2_max
        if fp_ok and gt_violations:
            # Build sets of (post_id, contract_id, violation_type)
            gt_set = set()
            for v in gt_violations:
                gt_set.add((str(v["post_id"]), str(v["contract_id"]), v["violation_type"]))

            pred_set = set()
            for r in fp_rows:
                pred_set.add((
                    str(r.get("post_id", "")).strip(),
                    str(r.get("contract_id", "")).strip(),
                    str(r.get("violation_type", "")).strip(),
                ))

            if gt_set or pred_set:
                tp = len(gt_set & pred_set)
                precision = tp / len(pred_set) if pred_set else 0
                recall = tp / len(gt_set) if gt_set else 0
                f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0
                c2_score = round(f1 * c2_max)
            else:
                c2_score = c2_max

            eval_criteria["flagged_posts_accuracy"] = {
                "passed": c2_score == c2_max,
                "score": c2_score,
                "max_score": c2_max,
                "reason": "" if c2_score == c2_max else f"F1={f1:.3f}, precision={precision:.3f}, recall={recall:.3f}",
            }
            total_score += c2_score
        elif not gt_violations:
            # No violations expected
            c2_score = c2_max if len(fp_rows) == 0 else 0
            eval_criteria["flagged_posts_accuracy"] = {
                "passed": c2_score == c2_max,
                "score": c2_score,
                "max_score": c2_max,
                "reason": "" if c2_score == c2_max else "Expected no violations",
            }
            total_score += c2_score
        else:
            eval_criteria["flagged_posts_accuracy"] = {
                "passed": False, "score": 0, "max_score": c2_max,
                "reason": "flagged_posts.csv not readable",
            }

        # ---------- Read recorded adjustments from the DB ledger ----------
        # (M4: replaces the payment_adjustments.csv deliverable; same ground
        #  truth comparisons and weights as the base environment.)
        adj_records: Dict[str, Dict[str, float]] = {}
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT contract_id, total_penalty_pct, adjusted_payment "
                "FROM payment_adjustments"
            )
            for cid, pen, adj in cur.fetchall():
                adj_records[str(cid)] = {
                    "total_penalty_pct": pen,
                    "adjusted_payment": adj,
                }
            conn.close()
        except sqlite3.OperationalError:
            # Table never created: no adjustments were recorded.
            pass

        total_contracts = len(gt_payments)

        # ---------- Criterion 3: adjustments recorded for all pending contracts (10 pts) ----------
        c3_max = 10
        max_score += c3_max
        recorded = sum(
            1 for p in gt_payments if str(p["contract_id"]) in adj_records
        )
        ratio = recorded / total_contracts if total_contracts else 1
        c3_score = round(ratio * c3_max)
        eval_criteria["payment_adjustments_recorded"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": "" if c3_score == c3_max else f"{recorded}/{total_contracts} contracts recorded in ledger",
        }
        total_score += c3_score

        # ---------- Criterion 4: penalty percentages correct (20 pts) ----------
        c4_max = 20
        max_score += c4_max
        if adj_records and gt_payments:
            gt_map = {str(p["contract_id"]): p for p in gt_payments}
            correct = 0
            for cid, rec in adj_records.items():
                if cid in gt_map:
                    try:
                        pred_pen = int(float(rec["total_penalty_pct"]))
                        if pred_pen == gt_map[cid]["total_penalty_pct"]:
                            correct += 1
                    except (ValueError, TypeError):
                        pass
            ratio = correct / total_contracts if total_contracts else 1
            c4_score = round(ratio * c4_max)
            eval_criteria["penalty_pct_accuracy"] = {
                "passed": c4_score == c4_max,
                "score": c4_score,
                "max_score": c4_max,
                "reason": "" if c4_score == c4_max else f"{correct}/{total_contracts} correct",
            }
            total_score += c4_score
        else:
            eval_criteria["penalty_pct_accuracy"] = {
                "passed": False, "score": 0, "max_score": c4_max,
                "reason": "no recorded adjustments or no contracts",
            }

        # ---------- Criterion 5: adjusted payments correct (20 pts) ----------
        c5_max = 20
        max_score += c5_max
        if adj_records and gt_payments:
            gt_map = {str(p["contract_id"]): p for p in gt_payments}
            correct = 0
            for cid, rec in adj_records.items():
                if cid in gt_map:
                    try:
                        pred_adj = round(float(rec["adjusted_payment"]), 2)
                        if abs(pred_adj - gt_map[cid]["adjusted_payment"]) < 0.015:
                            correct += 1
                    except (ValueError, TypeError):
                        pass
            ratio = correct / total_contracts if total_contracts else 1
            c5_score = round(ratio * c5_max)
            eval_criteria["adjusted_payment_accuracy"] = {
                "passed": c5_score == c5_max,
                "score": c5_score,
                "max_score": c5_max,
                "reason": "" if c5_score == c5_max else f"{correct}/{total_contracts} correct",
            }
            total_score += c5_score
        else:
            eval_criteria["adjusted_payment_accuracy"] = {
                "passed": False, "score": 0, "max_score": c5_max,
                "reason": "no recorded adjustments or no contracts",
            }

        # ---------- Criterion 6: action summary (15 pts) ----------
        c6_max = 15
        max_score += c6_max
        c6_score = 0

        gt_total_violations = len(gt_violations)
        gt_penalized = sum(1 for p in gt_payments if p["total_penalty_pct"] > 0)
        gt_total_deduction = round(
            sum(p["base_payment"] - p["adjusted_payment"] for p in gt_payments), 2
        )

        # Parse action string
        import re
        try:
            m_viol = re.search(r"Total violations:\s*(\d+)", action)
            m_pen = re.search(r"Contracts penalized:\s*(\d+)", action)
            m_ded = re.search(r"Total deductions:\s*\$?([\d,]+\.?\d*)", action)

            if m_viol and int(m_viol.group(1)) == gt_total_violations:
                c6_score += 5
            if m_pen and int(m_pen.group(1)) == gt_penalized:
                c6_score += 5
            if m_ded:
                pred_ded = float(m_ded.group(1).replace(",", ""))
                if abs(pred_ded - gt_total_deduction) < 0.015:
                    c6_score += 5
        except Exception:
            pass

        eval_criteria["action_summary"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": "" if c6_score == c6_max else f"Expected: violations={gt_total_violations}, penalized={gt_penalized}, deductions=${gt_total_deduction:.2f}",
        }
        total_score += c6_score

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, info

    # ====================== VERIFY ======================

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.

        Note: the hardened tool surface requires a JSON-encoded string filter
        for list_contracts and nested request payloads for
        create_payment_adjustment.
        """
        import yaml as _yaml

        tool_calls = 0

        def _call(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        # Step 1: Read compliance rules from workspace
        with open(os.path.join(self.workspace, "compliance_rules.yaml")) as f:
            rules = _yaml.safe_load(f)

        region_map = rules["region_country_mapping"]
        max_bot = rules["bot_detection"]["max_bot_score"]
        min_conf = rules["bot_detection"]["min_scan_confidence"]

        # Step 2: Read all audience geo files from workspace
        audience = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("audience_geo_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                    audience.update(data)

        # Step 3: List all pending_review contracts via tools
        # (M1: JSON-encoded string filter, paginated)
        pending_contracts = []
        page = 1
        filter_str = json.dumps({"status": "pending_review"})
        while True:
            result = _call("list_contracts", filter=filter_str, page=page)
            pending_contracts.extend(result["contracts"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 4: For each contract, get details, get posts, check violations
        all_violations = []
        payment_adjustments = []

        for c_summary in pending_contracts:
            cid = c_summary["contract_id"]

            # Get full contract details (success payload is nested under "contract")
            c = _call("get_contract_details", contract_id=cid)["contract"]

            # Get posts
            posts_result = _call("list_contract_posts", contract_id=cid)
            contract_posts = posts_result["posts"]

            violation_types_seen = set()

            for p in contract_posts:
                pid = p["post_id"]
                posted = datetime.strptime(p["posted_at"], "%Y-%m-%d %H:%M:%S")
                start_d = datetime.strptime(c["start_date"], "%Y-%m-%d")
                end_d = datetime.strptime(c["end_date"], "%Y-%m-%d")

                # Date violation
                if posted.date() < start_d.date() or posted.date() > end_d.date():
                    all_violations.append({
                        "post_id": pid, "contract_id": cid,
                        "violation_type": "date_violation",
                        "detail": f"Posted {posted.date()}, window {c['start_date']} to {c['end_date']}",
                    })
                    violation_types_seen.add("date_violation")

                # Hour violation
                if posted.hour < c["posting_hour_start"] or posted.hour > c["posting_hour_end"]:
                    all_violations.append({
                        "post_id": pid, "contract_id": cid,
                        "violation_type": "hour_violation",
                        "detail": f"Hour {posted.hour}, allowed {c['posting_hour_start']}-{c['posting_hour_end']}",
                    })
                    violation_types_seen.add("hour_violation")

                # Engagement
                eng_rate = (p["likes"] + p["comments"] + p["shares"]) / max(p["impressions"], 1)
                if eng_rate < c["min_engagement_rate"]:
                    all_violations.append({
                        "post_id": pid, "contract_id": cid,
                        "violation_type": "low_engagement",
                        "detail": f"Rate {eng_rate:.6f} < min {c['min_engagement_rate']}",
                    })
                    violation_types_seen.add("low_engagement")

                # Bot score via tool
                bot_result = _call("get_bot_report", post_id=pid)
                # Find highest-confidence scan with confidence >= min_conf
                valid_scans = [s for s in bot_result["scans"] if s["scan_confidence"] >= min_conf]
                if valid_scans:
                    best = max(valid_scans, key=lambda s: s["scan_confidence"])
                    if best["bot_score"] > max_bot:
                        all_violations.append({
                            "post_id": pid, "contract_id": cid,
                            "violation_type": "high_bot_score",
                            "detail": f"Bot score {best['bot_score']} > max {max_bot}",
                        })
                        violation_types_seen.add("high_bot_score")

                # Audience location from workspace files
                pid_str = str(pid)
                if pid_str in audience:
                    breakdown = audience[pid_str]["audience_breakdown"]
                    target_countries = region_map.get(c["target_region"], [])
                    region_pct = sum(breakdown.get(cc, 0.0) for cc in target_countries) / 100.0
                    if region_pct < c["min_region_pct"]:
                        all_violations.append({
                            "post_id": pid, "contract_id": cid,
                            "violation_type": "audience_location",
                            "detail": f"Region pct {region_pct:.4f} < min {c['min_region_pct']}",
                        })
                        violation_types_seen.add("audience_location")

            # Compute penalty
            penalty = 0
            if "date_violation" in violation_types_seen:
                penalty += rules["timing"]["date_violation_penalty_pct"]
            if "hour_violation" in violation_types_seen:
                penalty += rules["timing"]["hour_violation_penalty_pct"]
            if "low_engagement" in violation_types_seen:
                penalty += rules["engagement"]["penalty_pct"]
            if "high_bot_score" in violation_types_seen:
                penalty += rules["bot_detection"]["penalty_pct"]
            if "audience_location" in violation_types_seen:
                penalty += rules["audience_location"]["penalty_pct"]

            shortfall = max(c["required_posts"] - len(contract_posts), 0)
            penalty += shortfall * rules["post_count"]["penalty_per_missing_post_pct"]

            penalty = min(penalty, rules["max_total_penalty_pct"])
            adjusted = round(c["base_payment"] * (1 - penalty / 100), 2)

            payment_adjustments.append({
                "contract_id": cid,
                "campaign_name": c["campaign_name"],
                "base_payment": c["base_payment"],
                "total_penalty_pct": penalty,
                "adjusted_payment": adjusted,
            })

        # Sort violations
        all_violations.sort(key=lambda v: (v["contract_id"], v["post_id"], v["violation_type"]))
        payment_adjustments.sort(key=lambda pa: pa["contract_id"])

        # Write flagged_posts.csv
        fp_path = os.path.join(self.workspace, "flagged_posts.csv")
        with open(fp_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["post_id", "contract_id", "violation_type", "detail"])
            writer.writeheader()
            for v in all_violations:
                writer.writerow(v)

        # Record adjustments through the write API
        # (M4: nested payload with layered validation)
        for pa in payment_adjustments:
            result = _call(
                "create_payment_adjustment",
                payload={
                    "parent": {
                        "type": "adjustment_ledger",
                        "contract_id": str(pa["contract_id"]),
                    },
                    "properties": {
                        "Penalty": {
                            "type": "number",
                            "number": pa["total_penalty_pct"],
                        },
                        "AdjustedPayment": {
                            "type": "number",
                            "number": pa["adjusted_payment"],
                        },
                    },
                },
            )
            assert result.get("object") == "adjustment" and result.get("created"), result

        # Build action summary
        total_violations = len(all_violations)
        contracts_penalized = sum(1 for pa in payment_adjustments if pa["total_penalty_pct"] > 0)
        total_deduction = round(
            sum(pa["base_payment"] - pa["adjusted_payment"] for pa in payment_adjustments), 2
        )

        action = (
            f"Total violations: {total_violations}\n"
            f"Contracts penalized: {contracts_penalized}\n"
            f"Total deductions: ${total_deduction:.2f}"
        )

        print(f"[verify] total tool calls: {tool_calls}")
        return self.step(action)
