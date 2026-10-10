"""
Environment for industrial facility compliance risk assessment task.

Hardened tool surface (M0 + M1 + M3 + M5):
  - M1: get_sensor_readings and get_violation_records take a single
    JSON-encoded string `filter` parameter with layered, one-at-a-time
    validation errors.
  - M3: list_facilities and get_facility_details return deep-nested
    Notion-style records; the facility list uses cursor pagination
    (has_more / next_cursor) instead of total/total_pages.
  - M5: export_compliance_snapshot returns the full joined sensor/permit
    dataset as ONE JSON string with no pagination — at larger scales this
    is far bigger than a model's context budget and is only safe to
    consume inside a programmatic sandbox that filters before printing.
  - Errors: tools never raise; every failure returns an error object that
    shares no keys with the tool's success shape.
Task semantics, data, deliverables, and scoring are unchanged from the
base environment (M0 moved route narration out of the prompt and into a
workspace methodology document).
"""

import ast
import csv
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Tuple

import yaml


# ── Decorator ───────────────────────────────────────────────────────────────

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ── Hardened tool-surface helpers ───────────────────────────────────────────

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


# ── Notion-style nested-record builders (M3) ────────────────────────────────

def _select(name):
    return {"type": "select", "select": {"name": name}}


def _number(value):
    return {"type": "number", "number": value}


def _title(text):
    return {"type": "title", "title": [
        {"type": "text", "text": {"content": text, "link": None}, "plain_text": text}]}


def _relation(*ids):
    return {"type": "relation", "relation": [{"id": i} for i in ids]}


# ── Task Environment ────────────────────────────────────────────────────────

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

    # ── Internal validation helpers ─────────────────────────────────────

    def _check_facility_id(self, facility_id):
        """Validate a facility_id argument and confirm the facility exists.
        Returns None on success, or an error dict."""
        if not isinstance(facility_id, str) or facility_id == "":
            return _error(
                400, "validation_error",
                f"body.facility_id should be a non-empty string, instead was "
                f"{_shape(facility_id)}.")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT 1 FROM facilities WHERE facility_id = ?",
                  (facility_id,))
        found = c.fetchone()
        conn.close()
        if found is None:
            return _error(
                404, "object_not_found",
                f"Could not find facility with ID: {facility_id}.")
        return None

    # ── Tool methods ────────────────────────────────────────────────────

    @tool(
        description=(
            "List all registered industrial facilities. Each result entry "
            "carries the facility name, sector, region, and operating status. "
            "Results are paginated with a cursor."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of facilities per page. Defaults to 10.",
                },
            },
            "required": [],
        },
    )
    def list_facilities(self, page: Any = 1, page_size: Any = 10) -> dict:
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            return _error(
                400, "validation_error",
                f"body.page should be a positive integer, instead was "
                f"{_shape(page)}.")
        if (not isinstance(page_size, int) or isinstance(page_size, bool)
                or page_size < 1):
            return _error(
                400, "validation_error",
                f"body.page_size should be a positive integer, instead was "
                f"{_shape(page_size)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM facilities")
        total = c.fetchone()[0]
        offset = (page - 1) * page_size
        c.execute(
            "SELECT facility_id, name, sector, region, operating_status "
            "FROM facilities ORDER BY facility_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        results = [
            {
                "object": "facility",
                "id": r["facility_id"],
                "properties": {
                    "Name": _title(r["name"]),
                    "Sector": _select(r["sector"]),
                    "Region": _select(r["region"]),
                    "Operating Status": _select(r["operating_status"]),
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
            "Get the full record for a specific facility, including "
            "coordinates, employee count, and established year."
        ),
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "The facility identifier, e.g. FAC-0001.",
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_facility_details(self, facility_id: Any = None) -> dict:
        err = self._check_facility_id(facility_id)
        if err is not None:
            return err
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM facilities WHERE facility_id = ?",
                  (facility_id,))
        row = c.fetchone()
        conn.close()
        return {
            "object": "facility",
            "id": row["facility_id"],
            "properties": {
                "Name": _title(row["name"]),
                "Sector": _select(row["sector"]),
                "Region": _select(row["region"]),
                "Operating Status": _select(row["operating_status"]),
                "Latitude": _number(row["latitude"]),
                "Longitude": _number(row["longitude"]),
                "Employee Count": _number(row["employee_count"]),
                "Established Year": _number(row["established_year"]),
            },
        }

    @tool(
        description=(
            "Get the effluent sensor readings recorded at a facility, ordered "
            "by timestamp descending (most recent first). Filtering is "
            "expressed as a JSON-encoded string, e.g. "
            "filter='{\"pollutant_code\": \"BOD\", \"sensor_status\": "
            "\"Normal\"}'. Supported filter properties: pollutant_code (e.g. "
            "BOD, COD, TSS, NH3, PH, TEMP, OG, TN, TP, HM_PB, HM_CD, HM_CR) "
            "and sensor_status (Normal | Calibration Due | Fault)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "The facility identifier.",
                },
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"pollutant_code\": \"NH3\"}'. Pass '{}' or omit "
                        "for no filtering."
                    ),
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_sensor_readings(self, facility_id: Any = None,
                            filter: Any = None) -> dict:
        err = self._check_facility_id(facility_id)
        if err is not None:
            return err
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"pollutant_code", "sensor_status"}
        for key in parsed:
            if key not in supported:
                return _error(
                    400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: pollutant_code, sensor_status.")

        clauses = ["facility_id = ?"]
        params: list = [facility_id]
        if "pollutant_code" in parsed:
            pc = parsed["pollutant_code"]
            if not isinstance(pc, str) or pc == "":
                return _error(
                    400, "validation_error",
                    f"body.filter.pollutant_code should be a non-empty "
                    f"string, instead was {_shape(pc)}.")
            clauses.append("pollutant_code = ?")
            params.append(pc)
        if "sensor_status" in parsed:
            ss = parsed["sensor_status"]
            if not isinstance(ss, str) or ss not in (
                    "Normal", "Calibration Due", "Fault"):
                return _error(
                    400, "validation_error",
                    f"body.filter.sensor_status should be one of \"Normal\", "
                    f"\"Calibration Due\", \"Fault\", instead was "
                    f"{_shape(ss)}.")
            clauses.append("sensor_status = ?")
            params.append(ss)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT reading_id, pollutant_code, value, unit, timestamp, "
            "sensor_status FROM sensor_readings "
            "WHERE " + " AND ".join(clauses) + " ORDER BY timestamp DESC",
            params,
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"facility_id": facility_id, "readings": rows}

    @tool(
        description=(
            "Get the discharge permit limits for a specific facility. "
            "Returns all active permits with daily maximum and monthly "
            "average maximum limits per pollutant."
        ),
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "The facility identifier.",
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_permit_limits(self, facility_id: Any = None) -> dict:
        err = self._check_facility_id(facility_id)
        if err is not None:
            return err
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT permit_id, pollutant_code, daily_max, monthly_avg_max, "
            "unit, effective_date, expiry_date FROM discharge_permits "
            "WHERE facility_id = ? ORDER BY pollutant_code",
            (facility_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"facility_id": facility_id, "permits": rows}

    @tool(
        description=(
            "Get historical inspection violation records for a facility. "
            "Each record includes violation type, severity (1-5), inspection "
            "date, resolution status, and resolution date if applicable. "
            "Filtering is expressed as a JSON-encoded string, e.g. "
            "filter='{\"resolved\": false, \"min_severity\": 3}'. Supported "
            "filter properties: resolved (boolean), min_severity (integer "
            "1-5), and violation_type (string)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "The facility identifier.",
                },
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"resolved\": false}'. Pass '{}' or omit for no "
                        "filtering."
                    ),
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_violation_records(self, facility_id: Any = None,
                              filter: Any = None) -> dict:
        err = self._check_facility_id(facility_id)
        if err is not None:
            return err
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"resolved", "min_severity", "violation_type"}
        for key in parsed:
            if key not in supported:
                return _error(
                    400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: resolved, min_severity, "
                    f"violation_type.")

        clauses = ["facility_id = ?"]
        params: list = [facility_id]
        if "resolved" in parsed:
            rv = parsed["resolved"]
            if not isinstance(rv, bool):
                return _error(
                    400, "validation_error",
                    f"body.filter.resolved should be a boolean, instead was "
                    f"{_shape(rv)}.")
            clauses.append("resolved = ?")
            params.append(int(rv))
        if "min_severity" in parsed:
            ms = parsed["min_severity"]
            if not isinstance(ms, int) or isinstance(ms, bool):
                return _error(
                    400, "validation_error",
                    f"body.filter.min_severity should be an integer, instead "
                    f"was {_shape(ms)}.")
            if not 1 <= ms <= 5:
                return _error(
                    400, "validation_error",
                    f"body.filter.min_severity should be between 1 and 5, "
                    f"instead was {_shape(ms)}.")
            clauses.append("severity >= ?")
            params.append(ms)
        if "violation_type" in parsed:
            vt = parsed["violation_type"]
            if not isinstance(vt, str) or vt == "":
                return _error(
                    400, "validation_error",
                    f"body.filter.violation_type should be a non-empty "
                    f"string, instead was {_shape(vt)}.")
            clauses.append("violation_type = ?")
            params.append(vt)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT violation_id, inspection_date, violation_type, severity, "
            "description, resolved, resolution_date FROM violations "
            "WHERE " + " AND ".join(clauses) + " ORDER BY inspection_date DESC",
            params,
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"facility_id": facility_id, "violations": rows}

    @tool(
        description=(
            "Get maintenance log entries for a specific facility. Returns "
            "equipment name, maintenance type, scheduled date, completion "
            "date, and current status (Completed / Scheduled / Overdue)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "The facility identifier.",
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_maintenance_status(self, facility_id: Any = None) -> dict:
        err = self._check_facility_id(facility_id)
        if err is not None:
            return err
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT log_id, equipment_name, maintenance_type, scheduled_date, "
            "completed_date, status FROM maintenance_logs "
            "WHERE facility_id = ? ORDER BY scheduled_date DESC",
            (facility_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"facility_id": facility_id, "maintenance_logs": rows}

    @tool(
        description=(
            "Export the complete effluent compliance snapshot in a single "
            "response: every sensor reading recorded at every facility, "
            "joined with the facility's name, region, and operating status "
            "and with the applicable permitted daily maximum for that "
            "pollutant. No pagination required."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def export_compliance_snapshot(self) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            """
            SELECT f.facility_id, f.name AS facility_name, f.region,
                   f.operating_status, s.pollutant_code, s.value,
                   s.timestamp, s.sensor_status,
                   (SELECT MIN(p.daily_max) FROM discharge_permits p
                    WHERE p.facility_id = s.facility_id
                      AND p.pollutant_code = s.pollutant_code)
                       AS permit_daily_max
            FROM sensor_readings s
            JOIN facilities f ON f.facility_id = s.facility_id
            ORDER BY s.facility_id, s.pollutant_code, s.timestamp DESC
            """
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps({"record_count": len(rows), "records": rows},
                          ensure_ascii=False)

    # ── Internal helpers (for step ground-truth computation) ────────────

    def _load_workspace_config(self):
        """Load the three fixed config files from workspace."""
        with open(os.path.join(self.workspace, "risk_scoring_config.yaml")) as f:
            risk_cfg = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "pollutant_hazard_tiers.csv")) as f:
            reader = csv.DictReader(f)
            hazard = {r["pollutant_code"]: float(r["tier_multiplier"])
                      for r in reader}
        with open(os.path.join(self.workspace, "dispatch_rules.json")) as f:
            dispatch = json.load(f)
        return risk_cfg, hazard, dispatch

    def _load_site_assessments(self):
        """Load sensitivity zone data from site_assessment*.json files."""
        zones = {}  # facility_id -> zone_multiplier
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("site_assessment") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                for rec in data:
                    zones[rec["facility_id"]] = rec["zone_multiplier"]
        return zones

    def _load_lab_analyses(self):
        """Load lab verification data from lab_analysis*.csv files.
        Returns {(facility_id, pollutant_code): lab_verified_value}."""
        lab = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("lab_analysis") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        key = (row["facility_id"], row["pollutant_code"])
                        lab[key] = float(row["lab_verified_value"])
        return lab

    def _load_corrective_actions(self):
        """Load corrective action statuses from corrective_actions* files.
        Returns {facility_id: count_of_overdue_actions}."""
        overdue = {}
        for fname in sorted(os.listdir(self.workspace)):
            if not fname.startswith("corrective_actions"):
                continue
            fpath = os.path.join(self.workspace, fname)

            if fname.endswith(".yaml"):
                with open(fpath) as f:
                    records = yaml.safe_load(f)
                if records:
                    for rec in records:
                        fid = rec["facility_id"]
                        if rec["corrective_action_status"] == "Overdue":
                            overdue[fid] = overdue.get(fid, 0) + 1

            elif fname.endswith(".md"):
                with open(fpath) as f:
                    text = f.read()
                # Parse markdown: look for Facility and Status lines
                current_fid = None
                for line in text.splitlines():
                    line = line.strip()
                    if line.startswith("- Facility:"):
                        current_fid = line.split(":", 1)[1].strip()
                    elif line.startswith("- Corrective Action Status:"):
                        status = line.split(":", 1)[1].strip()
                        if status == "Overdue" and current_fid:
                            overdue[current_fid] = overdue.get(current_fid, 0) + 1

            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    text = f.read()
                blocks = text.split("---")
                for block in blocks:
                    fid = None
                    status = None
                    for line in block.strip().splitlines():
                        line = line.strip()
                        if line.startswith("Facility:"):
                            fid = line.split(":", 1)[1].strip()
                        elif line.startswith("Corrective Action Status:"):
                            status = line.split(":", 1)[1].strip()
                    if fid and status == "Overdue":
                        overdue[fid] = overdue.get(fid, 0) + 1

        return overdue

    def _compute_ground_truth(self):
        """Compute the full ground-truth dispatch list."""
        risk_cfg, hazard_mult, dispatch_cfg = self._load_workspace_config()
        zone_mult = self._load_site_assessments()
        lab_data = self._load_lab_analyses()
        overdue_ca = self._load_corrective_actions()

        weights = risk_cfg["scoring_weights"]
        recency = risk_cfg["recency_weights"]
        unresolved_mult = risk_cfg["unresolved_multiplier"]
        ref_date = datetime.strptime(risk_cfg["reference_date"], "%Y-%m-%d")
        cat_thresholds = risk_cfg["risk_categories"]  # CRITICAL, HIGH, MODERATE
        disp_thresholds = risk_cfg["dispatch_thresholds"]  # IMMEDIATE, PRIORITY, ROUTINE

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Get active facilities
        c = conn.cursor()
        c.execute(
            "SELECT facility_id, name, region FROM facilities "
            "WHERE operating_status = 'Active' ORDER BY facility_id"
        )
        active_facs = [dict(r) for r in c.fetchall()]

        results = []
        for fac in active_facs:
            fid = fac["facility_id"]

            # 1. Exceedance score
            # Get latest sensor reading per pollutant
            c.execute(
                "SELECT pollutant_code, value, timestamp FROM sensor_readings "
                "WHERE facility_id = ? ORDER BY pollutant_code, timestamp DESC",
                (fid,),
            )
            sensor_latest = {}
            for row in c.fetchall():
                pc = row["pollutant_code"]
                if pc not in sensor_latest:
                    sensor_latest[pc] = row["value"]

            # Get permit limits (daily_max) per pollutant
            c.execute(
                "SELECT pollutant_code, daily_max FROM discharge_permits "
                "WHERE facility_id = ?",
                (fid,),
            )
            permits = {}
            for row in c.fetchall():
                pc = row["pollutant_code"]
                # If multiple permits for same pollutant, use the most
                # restrictive (lowest daily_max)
                if pc not in permits or row["daily_max"] < permits[pc]:
                    permits[pc] = row["daily_max"]

            exceedance_score = 0.0
            for pc in sensor_latest:
                if pc not in permits:
                    continue
                sensor_val = sensor_latest[pc]
                lab_val = lab_data.get((fid, pc))
                effective_val = sensor_val
                if lab_val is not None and lab_val > sensor_val:
                    effective_val = lab_val
                limit = permits[pc]
                if effective_val > limit:
                    excess = (effective_val - limit) / limit
                    tier_m = hazard_mult.get(pc, 1.0)
                    exceedance_score += excess * tier_m

            # 2. Violation history score
            c.execute(
                "SELECT severity, inspection_date, resolved FROM violations "
                "WHERE facility_id = ?",
                (fid,),
            )
            violation_score = 0.0
            for row in c.fetchall():
                sev = row["severity"]
                insp = datetime.strptime(row["inspection_date"], "%Y-%m-%d")
                days_ago = (ref_date - insp).days
                if days_ago <= 90:
                    rw = recency["last_90_days"]
                elif days_ago <= 180:
                    rw = recency["last_180_days"]
                elif days_ago <= 365:
                    rw = recency["last_365_days"]
                else:
                    rw = recency["older"]
                base = sev * rw
                if not row["resolved"]:
                    base *= unresolved_mult
                violation_score += base

            # 3. Maintenance risk score (count of overdue items)
            c.execute(
                "SELECT COUNT(*) FROM maintenance_logs "
                "WHERE facility_id = ? AND status = 'Overdue'",
                (fid,),
            )
            maintenance_score = float(c.fetchone()[0])

            # 4. Lab discrepancy score
            # Count pollutants where lab_verified > sensor by > 10%
            lab_disc_count = 0
            for pc, sv in sensor_latest.items():
                lv = lab_data.get((fid, pc))
                if lv is not None and sv > 0 and (lv - sv) / sv > 0.10:
                    lab_disc_count += 1
            lab_disc_score = float(lab_disc_count)

            # 5. Corrective action score (count of overdue actions)
            ca_score = float(overdue_ca.get(fid, 0))

            # Weighted raw score
            raw = (
                exceedance_score * weights["exceedance"]
                + violation_score * weights["violation_history"]
                + maintenance_score * weights["maintenance_risk"]
                + lab_disc_score * weights["lab_discrepancy"]
                + ca_score * weights["corrective_action"]
            )

            # Determine primary concern (highest weighted component)
            components = {
                "Exceedance": exceedance_score * weights["exceedance"],
                "Violations": violation_score * weights["violation_history"],
                "Maintenance": maintenance_score * weights["maintenance_risk"],
                "Lab Discrepancy": lab_disc_score * weights["lab_discrepancy"],
                "Corrective Actions": ca_score * weights["corrective_action"],
            }
            primary = max(components, key=components.get)

            # Apply zone multiplier
            zm = zone_mult.get(fid, 1.0)
            risk_score = round(raw * zm, 2)

            # Risk category
            if risk_score >= cat_thresholds["CRITICAL"]:
                risk_cat = "CRITICAL"
            elif risk_score >= cat_thresholds["HIGH"]:
                risk_cat = "HIGH"
            elif risk_score >= cat_thresholds["MODERATE"]:
                risk_cat = "MODERATE"
            else:
                risk_cat = "LOW"

            # Dispatch urgency
            if risk_score >= disp_thresholds["IMMEDIATE"]:
                urgency = "IMMEDIATE"
            elif risk_score >= disp_thresholds["PRIORITY"]:
                urgency = "PRIORITY"
            elif risk_score >= disp_thresholds["ROUTINE"]:
                urgency = "ROUTINE"
            else:
                urgency = "MONITOR"

            results.append({
                "facility_id": fid,
                "facility_name": fac["name"],
                "region": fac["region"],
                "risk_score": risk_score,
                "risk_category": risk_cat,
                "primary_concern": primary,
                "dispatch_urgency": urgency,
            })

        conn.close()

        # Sort: risk_score descending, facility_id ascending for ties
        results.sort(key=lambda r: (-r["risk_score"], r["facility_id"]))

        # Add rank
        for i, r in enumerate(results, 1):
            r["rank"] = i

        return results

    # ── Evaluation ──────────────────────────────────────────────────────

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
        ground_truth = self._compute_ground_truth()
        gt_map = {r["facility_id"]: r for r in ground_truth}

        criteria = {}

        # ── Criterion 1: dispatch_list.csv exists with correct columns (10 pts)
        csv_path = os.path.join(self.workspace, "dispatch_list.csv")
        expected_cols = [
            "rank", "facility_id", "facility_name", "region",
            "risk_score", "risk_category", "primary_concern",
            "dispatch_urgency",
        ]
        c1_pass = False
        agent_rows = []
        if os.path.isfile(csv_path):
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    if all(c in cols for c in expected_cols):
                        agent_rows = list(reader)
                        c1_pass = True
            except Exception:
                pass
        criteria["csv_structure"] = {
            "passed": c1_pass,
            "score": 10 if c1_pass else 0,
            "max_score": 10,
            "reason": "" if c1_pass else "dispatch_list.csv missing or wrong columns",
        }

        # ── Criterion 2: Correct set of facilities (15 pts)
        gt_ids = set(r["facility_id"] for r in ground_truth)
        agent_ids = set(r.get("facility_id", "") for r in agent_rows)
        c2_pass = gt_ids == agent_ids
        criteria["facility_set"] = {
            "passed": c2_pass,
            "score": 15 if c2_pass else 0,
            "max_score": 15,
            "reason": "" if c2_pass else (
                f"Expected {len(gt_ids)} facilities, got {len(agent_ids)}; "
                f"missing={gt_ids - agent_ids}, extra={agent_ids - gt_ids}"
            ),
        }

        # ── Criterion 3: Risk scores correct (25 pts) — partial credit
        c3_correct = 0
        c3_total = len(ground_truth)
        for row in agent_rows:
            fid = row.get("facility_id", "")
            try:
                agent_score = round(float(row.get("risk_score", -1)), 2)
            except (ValueError, TypeError):
                continue
            gt_rec = gt_map.get(fid)
            if gt_rec and abs(agent_score - gt_rec["risk_score"]) < 0.015:
                c3_correct += 1
        c3_ratio = c3_correct / c3_total if c3_total > 0 else 0
        c3_score = round(c3_ratio * 25, 2)
        criteria["risk_scores"] = {
            "passed": c3_ratio >= 0.99,
            "score": c3_score,
            "max_score": 25,
            "reason": "" if c3_ratio >= 0.99 else (
                f"{c3_correct}/{c3_total} risk scores correct"
            ),
        }

        # ── Criterion 4: Correct ranking / sort order (15 pts)
        c4_pass = False
        if len(agent_rows) == len(ground_truth):
            agent_order = [r.get("facility_id", "") for r in agent_rows]
            gt_order = [r["facility_id"] for r in ground_truth]
            c4_pass = agent_order == gt_order
            # Also check rank column
            if c4_pass:
                for i, row in enumerate(agent_rows):
                    try:
                        if int(row.get("rank", -1)) != i + 1:
                            c4_pass = False
                            break
                    except (ValueError, TypeError):
                        c4_pass = False
                        break
        criteria["ranking"] = {
            "passed": c4_pass,
            "score": 15 if c4_pass else 0,
            "max_score": 15,
            "reason": "" if c4_pass else "Incorrect sort order or rank values",
        }

        # ── Criterion 5: Risk categories correct (10 pts)
        c5_correct = 0
        for row in agent_rows:
            fid = row.get("facility_id", "")
            gt_rec = gt_map.get(fid)
            if gt_rec and row.get("risk_category") == gt_rec["risk_category"]:
                c5_correct += 1
        c5_ratio = c5_correct / c3_total if c3_total > 0 else 0
        c5_score = round(c5_ratio * 10, 2)
        criteria["risk_categories"] = {
            "passed": c5_ratio >= 0.99,
            "score": c5_score,
            "max_score": 10,
            "reason": "" if c5_ratio >= 0.99 else (
                f"{c5_correct}/{c3_total} categories correct"
            ),
        }

        # ── Criterion 6: Dispatch urgency correct (10 pts)
        c6_correct = 0
        for row in agent_rows:
            fid = row.get("facility_id", "")
            gt_rec = gt_map.get(fid)
            if gt_rec and row.get("dispatch_urgency") == gt_rec["dispatch_urgency"]:
                c6_correct += 1
        c6_ratio = c6_correct / c3_total if c3_total > 0 else 0
        c6_score = round(c6_ratio * 10, 2)
        criteria["dispatch_urgency"] = {
            "passed": c6_ratio >= 0.99,
            "score": c6_score,
            "max_score": 10,
            "reason": "" if c6_ratio >= 0.99 else (
                f"{c6_correct}/{c3_total} urgency values correct"
            ),
        }

        # ── Criterion 7: Primary concern correct (10 pts)
        c7_correct = 0
        for row in agent_rows:
            fid = row.get("facility_id", "")
            gt_rec = gt_map.get(fid)
            if gt_rec and row.get("primary_concern") == gt_rec["primary_concern"]:
                c7_correct += 1
        c7_ratio = c7_correct / c3_total if c3_total > 0 else 0
        c7_score = round(c7_ratio * 10, 2)
        criteria["primary_concern"] = {
            "passed": c7_ratio >= 0.99,
            "score": c7_score,
            "max_score": 10,
            "reason": "" if c7_ratio >= 0.99 else (
                f"{c7_correct}/{c3_total} primary concerns correct"
            ),
        }

        # ── Criterion 8: Response summary mentions top-5 (5 pts)
        top5 = ground_truth[:5]
        c8_count = 0
        action_upper = action.upper() if action else ""
        for rec in top5:
            if rec["facility_id"] in (action or ""):
                c8_count += 1
        c8_pass = c8_count >= 4  # at least 4 of 5
        criteria["response_summary"] = {
            "passed": c8_pass,
            "score": 5 if c8_pass else 0,
            "max_score": 5,
            "reason": "" if c8_pass else (
                f"Only {c8_count}/5 top facilities mentioned in response"
            ),
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ── Self-verification ───────────────────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.

        This method proves end-to-end solvability of the HARDENED surface:
          - Walks the M3 nested facility records and follows cursor pagination.
          - Consumes the M5 bulk export once, in memory.
          - Builds M1 JSON-encoded string filters for violation queries.
          - Uses self.tools[name](**params) only (no direct DB queries).
        """
        tool_calls = 0

        # ── Step 1: Read workspace config files ─────────────────────────
        with open(os.path.join(self.workspace, "risk_scoring_config.yaml")) as f:
            risk_cfg = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "pollutant_hazard_tiers.csv")) as f:
            reader = csv.DictReader(f)
            hazard_mult = {r["pollutant_code"]: float(r["tier_multiplier"])
                           for r in reader}

        with open(os.path.join(self.workspace, "dispatch_rules.json")) as f:
            dispatch_cfg = json.load(f)

        # ── Step 2: Read site assessments (zone multipliers) ────────────
        zone_mult = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("site_assessment") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                for rec in data:
                    zone_mult[rec["facility_id"]] = rec["zone_multiplier"]

        # ── Step 3: Read lab analysis files ─────────────────────────────
        lab_data = {}  # (facility_id, pollutant_code) -> lab_verified_value
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("lab_analysis") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        key = (row["facility_id"], row["pollutant_code"])
                        lab_data[key] = float(row["lab_verified_value"])

        # ── Step 4: Read corrective action files ────────────────────────
        overdue_ca = {}  # facility_id -> count
        for fname in sorted(os.listdir(self.workspace)):
            if not fname.startswith("corrective_actions"):
                continue
            fpath = os.path.join(self.workspace, fname)

            if fname.endswith(".yaml"):
                with open(fpath) as f:
                    records = yaml.safe_load(f)
                if records:
                    for rec in records:
                        if rec["corrective_action_status"] == "Overdue":
                            fid = rec["facility_id"]
                            overdue_ca[fid] = overdue_ca.get(fid, 0) + 1

            elif fname.endswith(".md"):
                with open(fpath) as f:
                    text = f.read()
                current_fid = None
                for line in text.splitlines():
                    line = line.strip()
                    if line.startswith("- Facility:"):
                        current_fid = line.split(":", 1)[1].strip()
                    elif line.startswith("- Corrective Action Status:"):
                        status = line.split(":", 1)[1].strip()
                        if status == "Overdue" and current_fid:
                            overdue_ca[current_fid] = overdue_ca.get(
                                current_fid, 0) + 1

            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    text = f.read()
                blocks = text.split("---")
                for block in blocks:
                    fid = None
                    status = None
                    for line in block.strip().splitlines():
                        line = line.strip()
                        if line.startswith("Facility:"):
                            fid = line.split(":", 1)[1].strip()
                        elif line.startswith("Corrective Action Status:"):
                            status = line.split(":", 1)[1].strip()
                    if fid and status == "Overdue":
                        overdue_ca[fid] = overdue_ca.get(fid, 0) + 1

        # ── Step 5: Gather all facility data via the hardened tools ─────
        weights = risk_cfg["scoring_weights"]
        recency_w = risk_cfg["recency_weights"]
        unresolved_mult_val = risk_cfg["unresolved_multiplier"]
        ref_date = datetime.strptime(risk_cfg["reference_date"], "%Y-%m-%d")
        cat_thresholds = risk_cfg["risk_categories"]
        disp_thresholds = risk_cfg["dispatch_thresholds"]

        # 5a. All facilities via M3 nested records + cursor pagination
        all_facilities = []
        page = 1
        while True:
            result = self.tools["list_facilities"](page=page, page_size=10)
            tool_calls += 1
            for rec in result["results"]:
                props = rec["properties"]
                all_facilities.append({
                    "facility_id": rec["id"],
                    "name": props["Name"]["title"][0]["plain_text"],
                    "region": props["Region"]["select"]["name"],
                    "operating_status":
                        props["Operating Status"]["select"]["name"],
                })
            if not result["has_more"]:
                break
            page = result["next_cursor"]

        # Filter to Active only
        active_facs = [f for f in all_facilities
                       if f["operating_status"] == "Active"]

        # 5b. M5 bulk export, consumed ONCE in memory (never echoed).
        # Records arrive ordered by facility_id, pollutant_code,
        # timestamp DESC — first record per (facility, pollutant) is the
        # latest reading. permit_daily_max is the most restrictive limit.
        raw_export = self.tools["export_compliance_snapshot"]()
        tool_calls += 1
        snapshot = json.loads(raw_export)
        sensor_latest_map = {}   # (fid, pc) -> latest value
        permit_limit_map = {}    # (fid, pc) -> most restrictive daily_max
        for rec in snapshot["records"]:
            key = (rec["facility_id"], rec["pollutant_code"])
            if key not in sensor_latest_map:
                sensor_latest_map[key] = rec["value"]
            if rec["permit_daily_max"] is not None:
                permit_limit_map[key] = rec["permit_daily_max"]

        results = []
        for fac in active_facs:
            fid = fac["facility_id"]

            # Latest reading + limits per pollutant, from the bulk export
            sensor_latest = {pc: v for (f_id, pc), v
                             in sensor_latest_map.items() if f_id == fid}
            permits = {pc: v for (f_id, pc), v
                       in permit_limit_map.items() if f_id == fid}

            # 1. Exceedance score
            exceedance_score = 0.0
            for pc in sensor_latest:
                if pc not in permits:
                    continue
                sensor_val = sensor_latest[pc]
                lab_val = lab_data.get((fid, pc))
                effective_val = sensor_val
                if lab_val is not None and lab_val > sensor_val:
                    effective_val = lab_val
                limit = permits[pc]
                if effective_val > limit:
                    excess = (effective_val - limit) / limit
                    tier_m = hazard_mult.get(pc, 1.0)
                    exceedance_score += excess * tier_m

            # Get violations via M1 JSON-string filters (unresolved
            # and resolved fetched separately to exercise the filter).
            unresolved_resp = self.tools["get_violation_records"](
                facility_id=fid, filter=json.dumps({"resolved": False}))
            tool_calls += 1
            resolved_resp = self.tools["get_violation_records"](
                facility_id=fid, filter=json.dumps({"resolved": True}))
            tool_calls += 1

            # 2. Violation score
            violation_score = 0.0
            for v_list, is_resolved in (
                    (unresolved_resp["violations"], False),
                    (resolved_resp["violations"], True)):
                for v in v_list:
                    sev = v["severity"]
                    insp = datetime.strptime(v["inspection_date"], "%Y-%m-%d")
                    days_ago = (ref_date - insp).days
                    if days_ago <= 90:
                        rw = recency_w["last_90_days"]
                    elif days_ago <= 180:
                        rw = recency_w["last_180_days"]
                    elif days_ago <= 365:
                        rw = recency_w["last_365_days"]
                    else:
                        rw = recency_w["older"]
                    base = sev * rw
                    if not is_resolved:
                        base *= unresolved_mult_val
                    violation_score += base

            # Get maintenance (native dict tool)
            ms = self.tools["get_maintenance_status"](facility_id=fid)
            tool_calls += 1

            # 3. Maintenance risk score
            maintenance_score = float(
                sum(1 for m in ms["maintenance_logs"]
                    if m["status"] == "Overdue")
            )

            # 4. Lab discrepancy score
            lab_disc_count = 0
            for pc, sv in sensor_latest.items():
                lv = lab_data.get((fid, pc))
                if lv is not None and sv > 0 and (lv - sv) / sv > 0.10:
                    lab_disc_count += 1
            lab_disc_score = float(lab_disc_count)

            # 5. Corrective action score
            ca_score = float(overdue_ca.get(fid, 0))

            # Weighted raw score
            raw = (
                exceedance_score * weights["exceedance"]
                + violation_score * weights["violation_history"]
                + maintenance_score * weights["maintenance_risk"]
                + lab_disc_score * weights["lab_discrepancy"]
                + ca_score * weights["corrective_action"]
            )

            # Primary concern
            components = {
                "Exceedance": exceedance_score * weights["exceedance"],
                "Violations": violation_score * weights["violation_history"],
                "Maintenance": maintenance_score * weights["maintenance_risk"],
                "Lab Discrepancy": lab_disc_score * weights["lab_discrepancy"],
                "Corrective Actions": ca_score * weights["corrective_action"],
            }
            primary = max(components, key=components.get)

            # Zone multiplier
            zm = zone_mult.get(fid, 1.0)
            risk_score = round(raw * zm, 2)

            # Risk category
            if risk_score >= cat_thresholds["CRITICAL"]:
                risk_cat = "CRITICAL"
            elif risk_score >= cat_thresholds["HIGH"]:
                risk_cat = "HIGH"
            elif risk_score >= cat_thresholds["MODERATE"]:
                risk_cat = "MODERATE"
            else:
                risk_cat = "LOW"

            # Dispatch urgency
            if risk_score >= disp_thresholds["IMMEDIATE"]:
                urgency = "IMMEDIATE"
            elif risk_score >= disp_thresholds["PRIORITY"]:
                urgency = "PRIORITY"
            elif risk_score >= disp_thresholds["ROUTINE"]:
                urgency = "ROUTINE"
            else:
                urgency = "MONITOR"

            results.append({
                "facility_id": fid,
                "facility_name": fac["name"],
                "region": fac["region"],
                "risk_score": risk_score,
                "risk_category": risk_cat,
                "primary_concern": primary,
                "dispatch_urgency": urgency,
            })

        # Sort
        results.sort(key=lambda r: (-r["risk_score"], r["facility_id"]))
        for i, r in enumerate(results, 1):
            r["rank"] = i

        # ── Step 6: Write dispatch_list.csv ─────────────────────────────
        csv_path = os.path.join(self.workspace, "dispatch_list.csv")
        columns = dispatch_cfg["output_format"]["columns"]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for r in results:
                row = {c: r[c] for c in columns}
                writer.writerow(row)

        # ── Step 7: Build action string ─────────────────────────────────
        # Count by risk category
        cat_counts = {}
        for r in results:
            cat_counts[r["risk_category"]] = cat_counts.get(
                r["risk_category"], 0) + 1

        top5 = results[:5]
        top5_lines = []
        for r in top5:
            top5_lines.append(
                f"  {r['rank']}. {r['facility_id']} ({r['facility_name']})"
                f" - Risk Score: {r['risk_score']}"
            )

        action = (
            f"Compliance risk assessment complete. "
            f"Total facilities assessed: {len(results)}.\n\n"
            f"Risk category breakdown:\n"
        )
        for cat in ["CRITICAL", "HIGH", "MODERATE", "LOW"]:
            action += f"  {cat}: {cat_counts.get(cat, 0)}\n"
        action += f"\nTop 5 highest-risk facilities:\n"
        action += "\n".join(top5_lines)
        action += (
            f"\n\nThe full prioritized dispatch list has been saved to "
            f"dispatch_list.csv with {len(results)} entries."
        )

        reward, info = self.step(action)
        info["verify_tool_calls"] = tool_calls
        return reward, info
