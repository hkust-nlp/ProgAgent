"""
Delivery Fleet Geofence Adherence - Task Environment (hardened tool surface)

Hardened surface (M0 + M1 + M3 + M5):
  - M0: prompt.md states the goal and the deliverable contract only; the
    scoring methodology lives in workspace documents
    (compliance_methodology.md + the configuration files).
  - M1: get_depot_drivers and query_violations take a single JSON-encoded
    string `filter` parameter instead of individual filter arguments.
  - M3: list/detail tools return deeply nested Notion-style records
    (title / select / number / relation / checkbox / date properties) with
    cursor-style pagination (has_more / next_cursor).
  - M5: export_fleet_activity returns the entire joined reporting-week
    dataset as ONE JSON string with no pagination (context-pressure trap).

Task semantics, data generation (beyond the additive methodology document),
ground truth, and scoring are unchanged from the base environment.
"""

import ast
import glob
import hashlib
import json
import os
import sqlite3
import yaml
import pandas as pd
from typing import Any, Dict, List, Tuple
from collections import defaultdict


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ─── Hardened tool-surface helpers ───

def _request_id(message: str) -> str:
    return "req_" + hashlib.md5(message.encode("utf-8")).hexdigest()[:12]


def _error(status: int, code: str, message: str) -> dict:
    """Error responses share NO keys with success responses (except the
    discriminating `object` key, which is "error" here and an entity kind
    on success)."""
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


# ─── Notion-style property builders (M3) ───

def _select(name):
    return {"type": "select", "select": {"name": name}}


def _number(value):
    return {"type": "number", "number": value}


def _title(text):
    return {"type": "title", "title": [
        {"type": "text", "text": {"content": text, "link": None}, "plain_text": text}]}


def _relation(*ids):
    return {"type": "relation", "relation": [{"id": i} for i in ids]}


def _checkbox(value):
    return {"type": "checkbox", "checkbox": bool(value)}


def _date(start, end=None):
    return {"type": "date", "date": {"start": start, "end": end}}


def _rich_text(text):
    return {"type": "rich_text", "rich_text": [
        {"type": "text", "text": {"content": text, "link": None}, "plain_text": text}]}


def _coerce_id(value, name):
    """Validate an integer-id parameter. Returns (id, None) or (None, error)."""
    if value is None:
        return None, _error(
            400, "validation_error",
            f"body.{name} should be defined, instead was 'undefined'.")
    if isinstance(value, bool):
        return None, _error(
            400, "validation_error",
            f"body.{name} should be an integer, instead was {_shape(value)}.")
    if isinstance(value, int):
        return value, None
    if isinstance(value, str):
        try:
            return int(value.strip()), None
        except ValueError:
            pass
    return None, _error(
        400, "validation_error",
        f"body.{name} should be an integer, instead was {_shape(value)}.")


def _coerce_page(value, name, default):
    """Lenient page/page_size coercion. Returns (int, None) or (None, error)."""
    if value is None:
        return default, None
    if isinstance(value, bool):
        return None, _error(
            400, "validation_error",
            f"body.{name} should be an integer, instead was {_shape(value)}.")
    if isinstance(value, int):
        return value, None
    if isinstance(value, str):
        try:
            return int(value.strip()), None
        except ValueError:
            pass
    return None, _error(
        400, "validation_error",
        f"body.{name} should be an integer, instead was {_shape(value)}.")


DRIVER_FILTER_ENUMS = {
    "status": ["active", "inactive", "on_leave"],
    "certification_level": ["standard", "advanced", "senior"],
    "license_class": ["A", "B", "C", "CDL"],
}

VIOLATION_FILTER_STRING_ENUMS = {
    "severity": ["low", "medium", "high", "critical"],
    "violation_type": [
        "unauthorized_entry", "overstay", "speeding_in_zone",
        "wrong_entry_point", "after_hours_access",
    ],
}
VIOLATION_FILTER_BOOL_KEYS = ["acknowledged", "resolved"]


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
    # Internal DB helpers
    # ------------------------------------------------------------------

    def _exists(self, table: str, id_col: str, id_val: int) -> bool:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            f"SELECT 1 FROM {table} WHERE {id_col} = ? LIMIT 1", (id_val,)
        ).fetchone()
        conn.close()
        return row is not None

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @tool(
        description=(
            "List the depots in the network, including each depot's name, "
            "region, manager, and location. Results are returned as pages "
            "of records; use the cursor to fetch subsequent pages."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (max 100). Default 20.",
                },
            },
            "required": [],
        },
    )
    def list_depots(self, page: Any = None, page_size: Any = None) -> dict:
        page, err = _coerce_page(page, "page", 1)
        if err:
            return err
        page_size, err = _coerce_page(page_size, "page_size", 20)
        if err:
            return err
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        offset = (page - 1) * page_size

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM depots").fetchone()[0]
        rows = conn.execute(
            "SELECT depot_id, name, region, manager_name, city, state "
            "FROM depots ORDER BY depot_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()

        results = [
            {
                "object": "depot",
                "id": r["depot_id"],
                "properties": {
                    "Name": _title(r["name"]),
                    "Region": _select(r["region"]),
                    "Manager": _rich_text(r["manager_name"]),
                    "City": _rich_text(r["city"]),
                    "State": _select(r["state"]),
                },
            }
            for r in rows
        ]
        has_more = offset + len(rows) < total
        return {
            "object": "list",
            "results": results,
            "has_more": has_more,
            "next_cursor": page + 1 if has_more else None,
        }

    @tool(
        description=(
            "Returns the drivers assigned to a given depot, including each "
            "driver's name, license class, certification level, hire date, "
            "and status. An optional filter narrows the result; it must be "
            "passed as a JSON-encoded string, e.g. "
            "filter='{\"status\": \"active\"}'. Supported filter properties: "
            "status (\"active\", \"inactive\", \"on_leave\"), "
            "certification_level (\"standard\", \"advanced\", \"senior\"), "
            "license_class (\"A\", \"B\", \"C\", \"CDL\")."
        ),
        parameters={
            "type": "object",
            "properties": {
                "depot_id": {
                    "type": "integer",
                    "description": "The depot ID to look up drivers for.",
                },
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"status\": \"active\", \"license_class\": \"CDL\"}'. "
                        "Pass '{}' or omit for no filtering."
                    ),
                },
            },
            "required": ["depot_id"],
        },
    )
    def get_depot_drivers(self, depot_id: Any = None, filter: Any = None) -> dict:
        depot_id, err = _coerce_id(depot_id, "depot_id")
        if err:
            return err
        parsed, err = _parse_json_string_param(filter, "filter")
        if err:
            return err
        for key, value in parsed.items():
            if key not in DRIVER_FILTER_ENUMS:
                return _error(
                    400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: status, certification_level, "
                    f"license_class.")
            if not isinstance(value, str):
                return _error(
                    400, "validation_error",
                    f"body.filter.{key} should be a string, instead was "
                    f"{_shape(value)}.")
            allowed = DRIVER_FILTER_ENUMS[key]
            if value not in allowed:
                return _error(
                    400, "validation_error",
                    f"body.filter.{key} should be one of "
                    + ", ".join(f'"{a}"' for a in allowed)
                    + f", instead was {_shape(value)}.")
        if not self._exists("depots", "depot_id", depot_id):
            return _error(
                404, "object_not_found",
                f"Could not find depot with ID: {depot_id}.")

        where = "WHERE depot_id = ?"
        params: list = [depot_id]
        for key, value in parsed.items():
            where += f" AND {key} = ?"
            params.append(value)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT driver_id, first_name, last_name, depot_id, "
            "license_class, certification_level, hire_date, status "
            f"FROM drivers {where} ORDER BY driver_id",
            params,
        ).fetchall()
        conn.close()

        results = [
            {
                "object": "driver",
                "id": r["driver_id"],
                "properties": {
                    "Name": _title(f"{r['first_name']} {r['last_name']}"),
                    "Depot": _relation(r["depot_id"]),
                    "License Class": _select(r["license_class"]),
                    "Certification": _select(r["certification_level"]),
                    "Hire Date": _date(r["hire_date"]),
                    "Status": _select(r["status"]),
                },
            }
            for r in rows
        ]
        return {
            "object": "list",
            "results": results,
            "has_more": False,
            "next_cursor": None,
        }

    @tool(
        description=(
            "Returns geofence violation records committed by drivers "
            "belonging to a depot during the reporting week (2025-01-06 to "
            "2025-01-12). Results are returned as pages of records; use the "
            "cursor to fetch subsequent pages. An optional filter narrows "
            "the result; it must be passed as a JSON-encoded string, e.g. "
            "filter='{\"severity\": \"critical\", \"resolved\": false}'. "
            "Supported filter properties: severity (\"low\", \"medium\", "
            "\"high\", \"critical\"), violation_type "
            "(\"unauthorized_entry\", \"overstay\", \"speeding_in_zone\", "
            "\"wrong_entry_point\", \"after_hours_access\"), acknowledged "
            "(boolean), resolved (boolean)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "depot_id": {
                    "type": "integer",
                    "description": "Depot ID whose drivers' violations to query.",
                },
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"severity\": \"critical\", \"acknowledged\": true}'. "
                        "Pass '{}' or omit for no filtering."
                    ),
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (max 100). Default 20.",
                },
            },
            "required": ["depot_id"],
        },
    )
    def query_violations(
        self,
        depot_id: Any = None,
        filter: Any = None,
        page: Any = None,
        page_size: Any = None,
    ) -> dict:
        depot_id, err = _coerce_id(depot_id, "depot_id")
        if err:
            return err
        parsed, err = _parse_json_string_param(filter, "filter")
        if err:
            return err
        for key, value in parsed.items():
            if key in VIOLATION_FILTER_STRING_ENUMS:
                if not isinstance(value, str):
                    return _error(
                        400, "validation_error",
                        f"body.filter.{key} should be a string, instead was "
                        f"{_shape(value)}.")
                allowed = VIOLATION_FILTER_STRING_ENUMS[key]
                if value not in allowed:
                    return _error(
                        400, "validation_error",
                        f"body.filter.{key} should be one of "
                        + ", ".join(f'"{a}"' for a in allowed)
                        + f", instead was {_shape(value)}.")
            elif key in VIOLATION_FILTER_BOOL_KEYS:
                if not isinstance(value, bool):
                    return _error(
                        400, "validation_error",
                        f"body.filter.{key} should be a boolean, instead was "
                        f"{_shape(value)}.")
            else:
                return _error(
                    400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: severity, violation_type, "
                    f"acknowledged, resolved.")
        page, err = _coerce_page(page, "page", 1)
        if err:
            return err
        page_size, err = _coerce_page(page_size, "page_size", 20)
        if err:
            return err
        if not self._exists("depots", "depot_id", depot_id):
            return _error(
                404, "object_not_found",
                f"Could not find depot with ID: {depot_id}.")

        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        offset = (page - 1) * page_size

        where = (
            "WHERE d.depot_id = ? "
            "AND v.timestamp >= '2025-01-06' AND v.timestamp < '2025-01-13'"
        )
        params: list = [depot_id]
        for key, value in parsed.items():
            if key in VIOLATION_FILTER_BOOL_KEYS:
                where += f" AND v.{key} = ?"
                params.append(1 if value else 0)
            else:
                where += f" AND v.{key} = ?"
                params.append(value)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(
            "SELECT COUNT(*) FROM violations v "
            "JOIN drivers d ON v.driver_id = d.driver_id " + where,
            params,
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT v.violation_id, v.driver_id, v.customer_id, "
            "v.timestamp, v.violation_type, v.distance_exceeded_m, "
            "v.dwell_time_s, v.severity, v.acknowledged, v.resolved "
            "FROM violations v "
            "JOIN drivers d ON v.driver_id = d.driver_id "
            + where +
            " ORDER BY v.violation_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        conn.close()

        results = [
            {
                "object": "violation",
                "id": r["violation_id"],
                "properties": {
                    "Driver": _relation(r["driver_id"]),
                    "Customer": _relation(r["customer_id"]),
                    "Occurred At": _date(r["timestamp"]),
                    "Type": _select(r["violation_type"]),
                    "Severity": _select(r["severity"]),
                    "Distance Exceeded (m)": _number(r["distance_exceeded_m"]),
                    "Dwell Time (s)": _number(r["dwell_time_s"]),
                    "Acknowledged": _checkbox(r["acknowledged"]),
                    "Resolved": _checkbox(r["resolved"]),
                },
            }
            for r in rows
        ]
        has_more = offset + len(rows) < total
        return {
            "object": "list",
            "results": results,
            "has_more": has_more,
            "next_cursor": page + 1 if has_more else None,
        }

    @tool(
        description=(
            "Returns the active contract record for a customer, including "
            "the service tier, the maximum weekly violations permitted, the "
            "penalty per violation, and the contract term."
        ),
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "integer",
                    "description": "Customer ID to look up.",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_customer_contract(self, customer_id: Any = None) -> dict:
        customer_id, err = _coerce_id(customer_id, "customer_id")
        if err:
            return err
        if not self._exists("customers", "customer_id", customer_id):
            return _error(
                404, "object_not_found",
                f"Could not find customer with ID: {customer_id}.")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT contract_id, customer_id, sla_tier, "
            "max_weekly_violations, penalty_per_violation, "
            "contract_start, contract_end, active "
            "FROM contracts WHERE customer_id = ? AND active = 1 "
            "ORDER BY contract_id LIMIT 1",
            (customer_id,),
        ).fetchone()
        conn.close()
        if not row:
            return _error(
                404, "object_not_found",
                f"Could not find an active contract for customer with ID: "
                f"{customer_id}.")

        return {
            "object": "contract",
            "id": row["contract_id"],
            "properties": {
                "Customer": _relation(row["customer_id"]),
                "SLA Tier": _select(row["sla_tier"]),
                "Max Weekly Violations": _number(row["max_weekly_violations"]),
                "Penalty Per Violation": _number(row["penalty_per_violation"]),
                "Term": _date(row["contract_start"], row["contract_end"]),
                "Active": _checkbox(row["active"]),
            },
        }

    @tool(
        description=(
            "Returns the shift log entries recorded for a driver during the "
            "reporting week (2025-01-06 to 2025-01-12), including shift "
            "date, clock-in/clock-out times, vehicle, route, and shift "
            "status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "driver_id": {
                    "type": "integer",
                    "description": "Driver ID to look up.",
                },
            },
            "required": ["driver_id"],
        },
    )
    def get_driver_shift_log(self, driver_id: Any = None) -> dict:
        driver_id, err = _coerce_id(driver_id, "driver_id")
        if err:
            return err
        if not self._exists("drivers", "driver_id", driver_id):
            return _error(
                404, "object_not_found",
                f"Could not find driver with ID: {driver_id}.")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT shift_id, driver_id, shift_date, clock_in, clock_out, "
            "vehicle_id, route_id, status "
            "FROM shift_logs "
            "WHERE driver_id = ? "
            "AND shift_date >= '2025-01-06' AND shift_date <= '2025-01-12' "
            "ORDER BY shift_date, clock_in",
            (driver_id,),
        ).fetchall()
        conn.close()

        results = [
            {
                "object": "shift",
                "id": r["shift_id"],
                "properties": {
                    "Driver": _relation(r["driver_id"]),
                    "Date": _date(r["shift_date"]),
                    "Clock In": _rich_text(r["clock_in"]),
                    "Clock Out": _rich_text(r["clock_out"]),
                    "Vehicle": _rich_text(r["vehicle_id"]),
                    "Route": _rich_text(r["route_id"]),
                    "Status": _select(r["status"]),
                },
            }
            for r in rows
        ]
        return {
            "object": "list",
            "results": results,
            "has_more": False,
            "next_cursor": None,
        }

    @tool(
        description=(
            "Returns the complete reporting-week fleet activity dataset in "
            "a single response: the full depot directory, the full driver "
            "roster, every geofence violation joined with its driver, depot, "
            "and active contract terms, and the week's complete GPS ping "
            "trace. No pagination required."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def export_fleet_activity(self) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        depots = [
            dict(r) for r in conn.execute(
                "SELECT depot_id, name AS depot_name, region "
                "FROM depots ORDER BY depot_id"
            ).fetchall()
        ]
        drivers = [
            dict(r) for r in conn.execute(
                "SELECT driver_id, "
                "(first_name || ' ' || last_name) AS driver_name, "
                "depot_id, status "
                "FROM drivers ORDER BY driver_id"
            ).fetchall()
        ]
        ledger = [
            dict(r) for r in conn.execute(
                "SELECT v.violation_id, v.driver_id, "
                "(d.first_name || ' ' || d.last_name) AS driver_name, "
                "d.status AS driver_status, d.depot_id, "
                "dep.name AS depot_name, dep.region, "
                "v.customer_id, c.sla_tier, c.max_weekly_violations, "
                "v.timestamp, v.violation_type, v.severity "
                "FROM violations v "
                "JOIN drivers d ON v.driver_id = d.driver_id "
                "JOIN depots dep ON d.depot_id = dep.depot_id "
                "LEFT JOIN contracts c "
                "ON c.customer_id = v.customer_id AND c.active = 1 "
                "WHERE v.timestamp >= '2025-01-06' "
                "AND v.timestamp < '2025-01-13' "
                "ORDER BY v.violation_id"
            ).fetchall()
        ]
        pings = [
            dict(r) for r in conn.execute(
                "SELECT ping_id, driver_id, timestamp, latitude, longitude, "
                "speed_kmh, heading_deg "
                "FROM gps_pings ORDER BY ping_id"
            ).fetchall()
        ]
        conn.close()

        payload = {
            "reporting_week": {"start": "2025-01-06", "end": "2025-01-12"},
            "depots": depots,
            "drivers": drivers,
            "violation_ledger": ledger,
            "gps_pings": pings,
        }
        return json.dumps(payload, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Ground-truth computation (used by step and verify)
    # ------------------------------------------------------------------

    def _load_workspace_configs(self):
        with open(os.path.join(self.workspace, "scoring_weights.json")) as f:
            scoring = json.load(f)
        with open(os.path.join(self.workspace, "retraining_policy.json")) as f:
            retraining = json.load(f)
        with open(os.path.join(self.workspace, "sla_tiers.yaml")) as f:
            sla = yaml.safe_load(f)
        return scoring, retraining, sla

    def _load_incident_map(self):
        """Return {violation_id: {adjustment_factor, disputed}}."""
        inc_map = {}
        for fp in sorted(glob.glob(
            os.path.join(self.workspace, "incident_context_*.csv")
        )):
            df = pd.read_csv(fp)
            for _, row in df.iterrows():
                inc_map[int(row["violation_id"])] = {
                    "adjustment_factor": float(row["adjustment_factor"]),
                    "disputed": bool(int(row["disputed"])),
                }
        return inc_map

    def _compute_ground_truth(self):
        scoring, retraining, sla = self._load_workspace_configs()
        inc_map = self._load_incident_map()

        sev_w = scoring["severity_weights"]
        default_adj = scoring["default_adjustment_factor"]
        breach_mult = scoring["sla_breach_multiplier"]
        risk_thr = scoring["risk_thresholds"]
        tier_mults = {
            t: d["violation_weight_multiplier"]
            for t, d in sla["tiers"].items()
        }
        flag_cond = retraining["flag_conditions"]
        rec_actions = retraining["recommended_actions"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        depots = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM depots ORDER BY depot_id"
            ).fetchall()
        ]
        drivers_all = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM drivers ORDER BY driver_id"
            ).fetchall()
        ]
        violations_all = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM violations "
                "WHERE timestamp >= '2025-01-06' AND timestamp < '2025-01-13' "
                "ORDER BY violation_id"
            ).fetchall()
        ]

        # cache contracts
        contract_cache = {}
        for r in conn.execute(
            "SELECT * FROM contracts WHERE active = 1"
        ).fetchall():
            contract_cache[r["customer_id"]] = dict(r)

        conn.close()

        # group drivers by depot
        drivers_by_depot = defaultdict(list)
        for d in drivers_all:
            drivers_by_depot[d["depot_id"]].append(d)

        # group violations by driver
        viols_by_driver = defaultdict(list)
        for v in violations_all:
            viols_by_driver[v["driver_id"]].append(v)

        # ---- Per-depot scorecard ----
        scorecard = []
        for depot in depots:
            did = depot["depot_id"]
            dep_drivers = drivers_by_depot.get(did, [])
            total_drivers = len(dep_drivers)
            active_drivers = sum(
                1 for d in dep_drivers if d["status"] == "active"
            )

            # violations for this depot's drivers
            dep_viols = []
            for drv in dep_drivers:
                dep_viols.extend(viols_by_driver.get(drv["driver_id"], []))

            # filter non-disputed
            nd_viols = []
            for v in dep_viols:
                inc = inc_map.get(v["violation_id"])
                if inc and inc["disputed"]:
                    continue
                nd_viols.append(v)

            total_violations = len(nd_viols)
            critical_violations = sum(
                1 for v in nd_viols if v["severity"] == "critical"
            )

            # group by customer for SLA breach check
            viols_by_cust = defaultdict(list)
            for v in nd_viols:
                viols_by_cust[v["customer_id"]].append(v)

            breached_customers = set()
            for cid, cvs in viols_by_cust.items():
                contract = contract_cache.get(cid, {})
                max_wv = contract.get("max_weekly_violations", 999)
                if len(cvs) > max_wv:
                    breached_customers.add(cid)

            sla_breach_count = len(breached_customers)

            # compute penalty
            total_penalty = 0.0
            for v in nd_viols:
                sw = sev_w.get(v["severity"], 0)
                contract = contract_cache.get(v["customer_id"], {})
                tier = contract.get("sla_tier", "bronze")
                tm = tier_mults.get(tier, 1.0)
                inc = inc_map.get(v["violation_id"])
                adj = inc["adjustment_factor"] if inc else default_adj
                pen = sw * tm * adj
                if v["customer_id"] in breached_customers:
                    pen *= breach_mult
                total_penalty += pen

            denom = max(active_drivers, 1)
            raw_score = 100.0 - total_penalty / denom
            compliance_score = round(max(0.0, raw_score), 2)

            # risk rating
            if compliance_score >= risk_thr["low"]["min_score"]:
                risk_rating = "low"
            elif compliance_score >= risk_thr["medium"]["min_score"]:
                risk_rating = "medium"
            elif compliance_score >= risk_thr["high"]["min_score"]:
                risk_rating = "high"
            else:
                risk_rating = "critical"

            scorecard.append({
                "depot_id": did,
                "depot_name": depot["name"],
                "region": depot["region"],
                "total_drivers": total_drivers,
                "active_drivers": active_drivers,
                "total_violations": total_violations,
                "critical_violations": critical_violations,
                "sla_breach_count": sla_breach_count,
                "compliance_score": compliance_score,
                "risk_rating": risk_rating,
            })

        scorecard.sort(key=lambda x: x["depot_id"])

        # ---- Flagged drivers ----
        depot_name_map = {d["depot_id"]: d["name"] for d in depots}
        flagged = []
        for drv in drivers_all:
            dvs = viols_by_driver.get(drv["driver_id"], [])
            # filter non-disputed
            nd = []
            for v in dvs:
                inc = inc_map.get(v["violation_id"])
                if inc and inc["disputed"]:
                    continue
                nd.append(v)

            violation_count = len(nd)
            ws = 0.0
            has_critical = False
            for v in nd:
                sw = sev_w.get(v["severity"], 0)
                inc = inc_map.get(v["violation_id"])
                adj = inc["adjustment_factor"] if inc else default_adj
                ws += sw * adj
                if v["severity"] == "critical":
                    has_critical = True
            ws = round(ws, 2)

            should_flag = False
            if violation_count >= flag_cond["min_violations"]:
                should_flag = True
            if ws >= flag_cond["min_weighted_severity_score"]:
                should_flag = True
            if has_critical and flag_cond["critical_violation_auto_flag"]:
                should_flag = True

            if not should_flag:
                continue

            if has_critical:
                reason = "critical_violation"
            elif ws >= flag_cond["min_weighted_severity_score"]:
                reason = "high_severity_score"
            else:
                reason = "excessive_violations"

            if ws > 30:
                action = rec_actions["weighted_score_above_30"]
            elif ws > 15:
                action = rec_actions["weighted_score_above_15"]
            else:
                action = rec_actions["default"]

            flagged.append({
                "driver_id": drv["driver_id"],
                "driver_name": f"{drv['first_name']} {drv['last_name']}",
                "depot_id": drv["depot_id"],
                "depot_name": depot_name_map.get(drv["depot_id"], ""),
                "violation_count": violation_count,
                "weighted_severity_score": ws,
                "primary_flag_reason": reason,
                "recommended_action": action,
            })

        flagged.sort(key=lambda x: (-x["weighted_severity_score"], x["driver_id"]))

        return scorecard, flagged

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

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
        gt_scorecard, gt_flagged = self._compute_ground_truth()
        criteria = {}
        total_score = 0.0
        max_score = 0.0

        # ---- 1. Scorecard file structure (15 pts) ----
        sc_path = os.path.join(self.workspace, "compliance_scorecard.csv")
        sc_cols = [
            "depot_id", "depot_name", "region", "total_drivers",
            "active_drivers", "total_violations", "critical_violations",
            "sla_breach_count", "compliance_score", "risk_rating",
        ]
        crit1_max = 15
        max_score += crit1_max
        crit1_score = 0
        crit1_reason = ""
        try:
            sc_df = pd.read_csv(sc_path)
            if list(sc_df.columns) == sc_cols:
                crit1_score = crit1_max
            else:
                missing = set(sc_cols) - set(sc_df.columns)
                extra = set(sc_df.columns) - set(sc_cols)
                if not missing:
                    crit1_score = crit1_max * 0.7
                    crit1_reason = f"Column order mismatch or extra columns: {extra}"
                else:
                    crit1_score = crit1_max * 0.3
                    crit1_reason = f"Missing columns: {missing}"
        except Exception as e:
            crit1_reason = f"Cannot read file: {e}"
        total_score += crit1_score
        criteria["scorecard_structure"] = {
            "passed": crit1_score == crit1_max,
            "score": round(crit1_score, 2),
            "max_score": crit1_max,
            "reason": crit1_reason or None,
        }

        # ---- 2. Scorecard depot completeness (15 pts) ----
        crit2_max = 15
        max_score += crit2_max
        crit2_score = 0
        crit2_reason = ""
        try:
            sc_df = pd.read_csv(sc_path)
            gt_ids = set(r["depot_id"] for r in gt_scorecard)
            pred_ids = set(int(x) for x in sc_df["depot_id"].tolist())
            if gt_ids == pred_ids:
                crit2_score = crit2_max
            else:
                overlap = len(gt_ids & pred_ids)
                crit2_score = crit2_max * overlap / max(len(gt_ids), 1)
                crit2_reason = (
                    f"Expected {len(gt_ids)} depots, got {len(pred_ids)}; "
                    f"overlap {overlap}"
                )
        except Exception as e:
            crit2_reason = f"Cannot read file: {e}"
        total_score += crit2_score
        criteria["scorecard_completeness"] = {
            "passed": crit2_score == crit2_max,
            "score": round(crit2_score, 2),
            "max_score": crit2_max,
            "reason": crit2_reason or None,
        }

        # ---- 3. Scorecard values accuracy (25 pts) ----
        crit3_max = 25
        max_score += crit3_max
        crit3_score = 0
        crit3_reason = ""
        try:
            sc_df = pd.read_csv(sc_path)
            gt_map = {r["depot_id"]: r for r in gt_scorecard}
            per_depot = crit3_max / max(len(gt_map), 1)
            details = []
            for _, row in sc_df.iterrows():
                did = int(row["depot_id"])
                gt = gt_map.get(did)
                if not gt:
                    continue
                ok = True
                # check numeric fields
                for field in [
                    "total_violations", "critical_violations",
                    "sla_breach_count", "active_drivers", "total_drivers",
                ]:
                    if int(row[field]) != gt[field]:
                        ok = False
                        details.append(
                            f"depot {did} {field}: "
                            f"expected {gt[field]}, got {int(row[field])}"
                        )
                # compliance score tolerance 0.05
                if abs(float(row["compliance_score"]) - gt["compliance_score"]) > 0.05:
                    ok = False
                    details.append(
                        f"depot {did} compliance_score: "
                        f"expected {gt['compliance_score']}, "
                        f"got {float(row['compliance_score'])}"
                    )
                # risk rating exact
                if str(row["risk_rating"]).strip().lower() != gt["risk_rating"]:
                    ok = False
                    details.append(
                        f"depot {did} risk_rating: "
                        f"expected {gt['risk_rating']}, got {row['risk_rating']}"
                    )
                if ok:
                    crit3_score += per_depot
            if details:
                crit3_reason = "; ".join(details[:10])
        except Exception as e:
            crit3_reason = f"Cannot evaluate: {e}"
        total_score += crit3_score
        criteria["scorecard_accuracy"] = {
            "passed": abs(crit3_score - crit3_max) < 0.01,
            "score": round(crit3_score, 2),
            "max_score": crit3_max,
            "reason": crit3_reason or None,
        }

        # ---- 4. Flagged drivers file structure (10 pts) ----
        fl_path = os.path.join(self.workspace, "flagged_drivers_report.csv")
        fl_cols = [
            "driver_id", "driver_name", "depot_id", "depot_name",
            "violation_count", "weighted_severity_score",
            "primary_flag_reason", "recommended_action",
        ]
        crit4_max = 10
        max_score += crit4_max
        crit4_score = 0
        crit4_reason = ""
        try:
            fl_df = pd.read_csv(fl_path)
            if list(fl_df.columns) == fl_cols:
                crit4_score = crit4_max
            else:
                missing = set(fl_cols) - set(fl_df.columns)
                if not missing:
                    crit4_score = crit4_max * 0.7
                    crit4_reason = "Column order mismatch"
                else:
                    crit4_score = crit4_max * 0.3
                    crit4_reason = f"Missing columns: {missing}"
        except Exception as e:
            crit4_reason = f"Cannot read file: {e}"
        total_score += crit4_score
        criteria["flagged_structure"] = {
            "passed": crit4_score == crit4_max,
            "score": round(crit4_score, 2),
            "max_score": crit4_max,
            "reason": crit4_reason or None,
        }

        # ---- 5. Flagged drivers accuracy (25 pts) ----
        crit5_max = 25
        max_score += crit5_max
        crit5_score = 0
        crit5_reason = ""
        try:
            fl_df = pd.read_csv(fl_path)
            gt_ids = set(r["driver_id"] for r in gt_flagged)
            pred_ids = set(int(x) for x in fl_df["driver_id"].tolist())

            # 15 pts for correct set
            if gt_ids == pred_ids:
                set_score = 15.0
            else:
                correct = len(gt_ids & pred_ids)
                total_relevant = max(len(gt_ids | pred_ids), 1)
                set_score = 15.0 * correct / total_relevant
                crit5_reason = (
                    f"Expected {len(gt_ids)} flagged drivers, "
                    f"got {len(pred_ids)}; correct {correct}"
                )
            crit5_score += set_score

            # 10 pts for detail accuracy of correctly identified drivers
            gt_map = {r["driver_id"]: r for r in gt_flagged}
            correct_ids = gt_ids & pred_ids
            if correct_ids:
                per_d = 10.0 / len(correct_ids)
                detail_errs = []
                for _, row in fl_df.iterrows():
                    did = int(row["driver_id"])
                    if did not in correct_ids:
                        continue
                    gt = gt_map[did]
                    ok = True
                    if abs(
                        float(row["weighted_severity_score"])
                        - gt["weighted_severity_score"]
                    ) > 0.05:
                        ok = False
                        detail_errs.append(
                            f"driver {did} ws: "
                            f"expected {gt['weighted_severity_score']}, "
                            f"got {float(row['weighted_severity_score'])}"
                        )
                    if (
                        str(row["primary_flag_reason"]).strip()
                        != gt["primary_flag_reason"]
                    ):
                        ok = False
                        detail_errs.append(
                            f"driver {did} reason mismatch"
                        )
                    if (
                        str(row["recommended_action"]).strip()
                        != gt["recommended_action"]
                    ):
                        ok = False
                        detail_errs.append(
                            f"driver {did} action mismatch"
                        )
                    if ok:
                        crit5_score += per_d
                if detail_errs:
                    crit5_reason = (
                        (crit5_reason + "; " if crit5_reason else "")
                        + "; ".join(detail_errs[:10])
                    )
        except Exception as e:
            crit5_reason = f"Cannot evaluate: {e}"
        total_score += crit5_score
        criteria["flagged_accuracy"] = {
            "passed": abs(crit5_score - crit5_max) < 0.01,
            "score": round(crit5_score, 2),
            "max_score": crit5_max,
            "reason": crit5_reason or None,
        }

        # ---- 6. Response summary accuracy (10 pts) ----
        crit6_max = 10
        max_score += crit6_max
        crit6_score = 0
        crit6_reason = ""
        try:
            action_lower = action.lower() if action else ""

            # overall fleet compliance score
            fleet_avg = round(
                sum(s["compliance_score"] for s in gt_scorecard)
                / max(len(gt_scorecard), 1),
                2,
            )
            # check if the number appears
            fleet_str = f"{fleet_avg:.2f}"
            # also accept one-decimal variant
            fleet_str1 = f"{fleet_avg:.1f}"
            if fleet_str in action or fleet_str1 in action:
                crit6_score += 4
            else:
                crit6_reason += f"Fleet avg {fleet_str} not found in response. "

            # risk distribution
            risk_dist = defaultdict(int)
            for s in gt_scorecard:
                risk_dist[s["risk_rating"]] += 1
            risk_ok = True
            for rating, count in risk_dist.items():
                if str(count) not in action:
                    risk_ok = False
            if risk_ok:
                crit6_score += 3
            else:
                crit6_reason += (
                    f"Risk distribution {dict(risk_dist)} not fully in response. "
                )

            # total flagged
            total_flagged = len(gt_flagged)
            if str(total_flagged) in action:
                crit6_score += 3
            else:
                crit6_reason += (
                    f"Total flagged count {total_flagged} not in response. "
                )
        except Exception as e:
            crit6_reason = f"Cannot evaluate response: {e}"
        total_score += crit6_score
        criteria["response_summary"] = {
            "passed": crit6_score == crit6_max,
            "score": round(crit6_score, 2),
            "max_score": crit6_max,
            "reason": crit6_reason.strip() or None,
        }

        # ---- Aggregate ----
        info = {
            "eval_criteria": criteria,
            "total_score": round(total_score, 2),
            "max_score": round(max_score, 2),
        }
        reward = round(total_score / max(max_score, 1), 4)
        return reward, info

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.

        This method proves the hardened tool surface is fully parseable:
          - walks nested Notion-style records (M3), following
            has_more/next_cursor pagination;
          - builds JSON-encoded string filters (M1);
          - consumes the unbounded bulk export once, in memory (M5).
        """
        import csv as csv_mod

        tool_calls = 0

        # ---- Consumer-side parsers for the nested record surface ----
        def prop_plain(props, key):
            p = props[key]
            return p[p["type"]][0]["plain_text"]

        def prop_select(props, key):
            return props[key]["select"]["name"]

        def prop_number(props, key):
            return props[key]["number"]

        def prop_relation(props, key):
            return props[key]["relation"][0]["id"]

        def is_error(resp):
            return isinstance(resp, dict) and resp.get("object") == "error"

        # ---- Load workspace configs ----
        with open(os.path.join(self.workspace, "scoring_weights.json")) as f:
            scoring = json.load(f)
        with open(os.path.join(self.workspace, "retraining_policy.json")) as f:
            retraining = json.load(f)
        with open(os.path.join(self.workspace, "sla_tiers.yaml")) as f:
            sla = yaml.safe_load(f)

        sev_w = scoring["severity_weights"]
        default_adj = scoring["default_adjustment_factor"]
        breach_mult = scoring["sla_breach_multiplier"]
        risk_thr = scoring["risk_thresholds"]
        tier_mults = {
            t: d["violation_weight_multiplier"]
            for t, d in sla["tiers"].items()
        }
        flag_cond = retraining["flag_conditions"]
        rec_actions = retraining["recommended_actions"]

        # ---- Load incident context ----
        inc_map = {}
        for fp in sorted(glob.glob(
            os.path.join(self.workspace, "incident_context_*.csv")
        )):
            df = pd.read_csv(fp)
            for _, row in df.iterrows():
                inc_map[int(row["violation_id"])] = {
                    "adjustment_factor": float(row["adjustment_factor"]),
                    "disputed": bool(int(row["disputed"])),
                }

        # ---- Tool calls: gather depots (M3 cursor pagination) ----
        depots = []
        page = 1
        while True:
            resp = self.tools["list_depots"](page=page, page_size=20)
            tool_calls += 1
            assert not is_error(resp), resp
            for rec in resp["results"]:
                depots.append({
                    "depot_id": rec["id"],
                    "name": prop_plain(rec["properties"], "Name"),
                    "region": prop_select(rec["properties"], "Region"),
                })
            if not resp["has_more"]:
                break
            page = resp["next_cursor"]

        all_drivers = {}          # driver_id -> {name, depot_id, status}
        depot_drivers = {}        # depot_id -> [driver dicts]
        depot_violations = {}     # depot_id -> [violation dicts]
        contract_cache = {}       # customer_id -> {sla_tier, max_weekly_violations}

        for depot in depots:
            did = depot["depot_id"]

            resp = self.tools["get_depot_drivers"](depot_id=did)
            tool_calls += 1
            assert not is_error(resp), resp
            drivers = []
            for rec in resp["results"]:
                props = rec["properties"]
                drivers.append({
                    "driver_id": rec["id"],
                    "name": prop_plain(props, "Name"),
                    "depot_id": prop_relation(props, "Depot"),
                    "status": prop_select(props, "Status"),
                })
            depot_drivers[did] = drivers
            for d in drivers:
                all_drivers[d["driver_id"]] = d

            # paginated violations (M3 cursor)
            all_viols = []
            page = 1
            while True:
                resp = self.tools["query_violations"](
                    depot_id=did, page=page, page_size=20,
                )
                tool_calls += 1
                assert not is_error(resp), resp
                for rec in resp["results"]:
                    props = rec["properties"]
                    all_viols.append({
                        "violation_id": rec["id"],
                        "driver_id": prop_relation(props, "Driver"),
                        "customer_id": prop_relation(props, "Customer"),
                        "severity": prop_select(props, "Severity"),
                    })
                if not resp["has_more"]:
                    break
                page = resp["next_cursor"]
            depot_violations[did] = all_viols

            # fetch contracts for unique customers (M3 nested detail record)
            cust_ids = set(v["customer_id"] for v in all_viols)
            for cid in cust_ids:
                if cid not in contract_cache:
                    resp = self.tools["get_customer_contract"](
                        customer_id=cid
                    )
                    tool_calls += 1
                    if is_error(resp):
                        contract_cache[cid] = {}
                        continue
                    props = resp["properties"]
                    contract_cache[cid] = {
                        "sla_tier": prop_select(props, "SLA Tier"),
                        "max_weekly_violations": prop_number(
                            props, "Max Weekly Violations"),
                    }

        # ---- Exercise the M1 JSON-string filters and cross-check ----
        if depots:
            did0 = depots[0]["depot_id"]
            filt = json.dumps({"status": "active"})
            resp = self.tools["get_depot_drivers"](depot_id=did0, filter=filt)
            tool_calls += 1
            assert not is_error(resp), resp
            n_active = len(resp["results"])
            assert n_active == sum(
                1 for d in depot_drivers[did0] if d["status"] == "active"
            ), "M1 status filter mismatch"

            filt = json.dumps({"severity": "critical", "resolved": False})
            crit_unres = []
            page = 1
            while True:
                resp = self.tools["query_violations"](
                    depot_id=did0, filter=filt, page=page, page_size=20,
                )
                tool_calls += 1
                assert not is_error(resp), resp
                crit_unres.extend(resp["results"])
                if not resp["has_more"]:
                    break
                page = resp["next_cursor"]
            assert len(crit_unres) <= sum(
                1 for v in depot_violations[did0]
                if v["severity"] == "critical"
            ), "M1 severity filter mismatch"

        # ---- Exercise the shift log surface (M3 nested list) ----
        if all_drivers:
            first_drv = min(all_drivers)
            resp = self.tools["get_driver_shift_log"](driver_id=first_drv)
            tool_calls += 1
            assert not is_error(resp), resp
            for rec in resp["results"]:
                _ = prop_select(rec["properties"], "Status")

        # ---- Consume the bulk export once, in memory (M5) ----
        raw = self.tools["export_fleet_activity"]()
        tool_calls += 1
        export = json.loads(raw)
        n_viols_export = len(export["violation_ledger"])
        n_viols_tools = sum(len(v) for v in depot_violations.values())
        assert n_viols_export == n_viols_tools, (
            f"export/tool violation count mismatch: "
            f"{n_viols_export} vs {n_viols_tools}"
        )
        assert len(export["depots"]) == len(depots)
        assert len(export["drivers"]) == len(all_drivers)

        # ---- Compute scorecard ----
        scorecard_rows = []
        for depot in depots:
            did = depot["depot_id"]
            drivers = depot_drivers.get(did, [])
            total_drivers = len(drivers)
            active_drivers = sum(
                1 for d in drivers if d["status"] == "active"
            )

            viols = depot_violations.get(did, [])
            # filter non-disputed
            nd_viols = []
            for v in viols:
                inc = inc_map.get(v["violation_id"])
                if inc and inc["disputed"]:
                    continue
                nd_viols.append(v)

            total_violations = len(nd_viols)
            critical_violations = sum(
                1 for v in nd_viols if v["severity"] == "critical"
            )

            # SLA breach
            viols_by_cust = defaultdict(list)
            for v in nd_viols:
                viols_by_cust[v["customer_id"]].append(v)

            breached = set()
            for cid, cvs in viols_by_cust.items():
                contract = contract_cache.get(cid, {})
                max_wv = contract.get("max_weekly_violations", 999)
                if len(cvs) > max_wv:
                    breached.add(cid)

            sla_breach_count = len(breached)

            # penalty
            total_penalty = 0.0
            for v in nd_viols:
                sw = sev_w.get(v["severity"], 0)
                contract = contract_cache.get(v["customer_id"], {})
                tier = contract.get("sla_tier", "bronze")
                tm = tier_mults.get(tier, 1.0)
                inc = inc_map.get(v["violation_id"])
                adj = inc["adjustment_factor"] if inc else default_adj
                pen = sw * tm * adj
                if v["customer_id"] in breached:
                    pen *= breach_mult
                total_penalty += pen

            denom = max(active_drivers, 1)
            compliance_score = round(max(0.0, 100.0 - total_penalty / denom), 2)

            if compliance_score >= risk_thr["low"]["min_score"]:
                risk_rating = "low"
            elif compliance_score >= risk_thr["medium"]["min_score"]:
                risk_rating = "medium"
            elif compliance_score >= risk_thr["high"]["min_score"]:
                risk_rating = "high"
            else:
                risk_rating = "critical"

            scorecard_rows.append({
                "depot_id": did,
                "depot_name": depot["name"],
                "region": depot["region"],
                "total_drivers": total_drivers,
                "active_drivers": active_drivers,
                "total_violations": total_violations,
                "critical_violations": critical_violations,
                "sla_breach_count": sla_breach_count,
                "compliance_score": compliance_score,
                "risk_rating": risk_rating,
            })

        scorecard_rows.sort(key=lambda x: x["depot_id"])

        # ---- Compute flagged drivers ----
        depot_name_map = {d["depot_id"]: d["name"] for d in depots}

        # group violations by driver across all depots
        viols_by_driver = defaultdict(list)
        for did, vs in depot_violations.items():
            for v in vs:
                viols_by_driver[v["driver_id"]].append(v)

        flagged_rows = []
        for drv_id, drv in all_drivers.items():
            dvs = viols_by_driver.get(drv_id, [])
            nd = []
            for v in dvs:
                inc = inc_map.get(v["violation_id"])
                if inc and inc["disputed"]:
                    continue
                nd.append(v)

            violation_count = len(nd)
            ws = 0.0
            has_critical = False
            for v in nd:
                sw = sev_w.get(v["severity"], 0)
                inc = inc_map.get(v["violation_id"])
                adj = inc["adjustment_factor"] if inc else default_adj
                ws += sw * adj
                if v["severity"] == "critical":
                    has_critical = True
            ws = round(ws, 2)

            should_flag = False
            if violation_count >= flag_cond["min_violations"]:
                should_flag = True
            if ws >= flag_cond["min_weighted_severity_score"]:
                should_flag = True
            if has_critical and flag_cond["critical_violation_auto_flag"]:
                should_flag = True

            if not should_flag:
                continue

            if has_critical:
                reason = "critical_violation"
            elif ws >= flag_cond["min_weighted_severity_score"]:
                reason = "high_severity_score"
            else:
                reason = "excessive_violations"

            if ws > 30:
                act = rec_actions["weighted_score_above_30"]
            elif ws > 15:
                act = rec_actions["weighted_score_above_15"]
            else:
                act = rec_actions["default"]

            flagged_rows.append({
                "driver_id": drv_id,
                "driver_name": drv["name"],
                "depot_id": drv["depot_id"],
                "depot_name": depot_name_map.get(drv["depot_id"], ""),
                "violation_count": violation_count,
                "weighted_severity_score": ws,
                "primary_flag_reason": reason,
                "recommended_action": act,
            })

        flagged_rows.sort(
            key=lambda x: (-x["weighted_severity_score"], x["driver_id"])
        )

        # ---- Write deliverables ----
        sc_path = os.path.join(self.workspace, "compliance_scorecard.csv")
        sc_cols = [
            "depot_id", "depot_name", "region", "total_drivers",
            "active_drivers", "total_violations", "critical_violations",
            "sla_breach_count", "compliance_score", "risk_rating",
        ]
        with open(sc_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=sc_cols)
            writer.writeheader()
            writer.writerows(scorecard_rows)

        fl_path = os.path.join(self.workspace, "flagged_drivers_report.csv")
        fl_cols = [
            "driver_id", "driver_name", "depot_id", "depot_name",
            "violation_count", "weighted_severity_score",
            "primary_flag_reason", "recommended_action",
        ]
        with open(fl_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=fl_cols)
            writer.writeheader()
            writer.writerows(flagged_rows)

        # ---- Build response ----
        fleet_avg = round(
            sum(r["compliance_score"] for r in scorecard_rows)
            / max(len(scorecard_rows), 1),
            2,
        )
        risk_dist = defaultdict(int)
        for r in scorecard_rows:
            risk_dist[r["risk_rating"]] += 1

        total_flagged = len(flagged_rows)

        action = (
            f"Overall fleet compliance score: {fleet_avg:.2f}. "
            f"Depot risk distribution: "
            + ", ".join(
                f"{rating} = {count}"
                for rating, count in sorted(risk_dist.items())
            )
            + f". Total drivers flagged for retraining: {total_flagged}."
        )

        print(f"verify: {tool_calls} tool calls made")
        return self.step(action)
