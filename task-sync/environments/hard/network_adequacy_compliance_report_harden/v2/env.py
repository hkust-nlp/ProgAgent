#!/usr/bin/env python3
"""Environment for network adequacy compliance task (hardened tool surface).

Hardened surface (M1 + M3 + M5):
  - M1: query_members and search_providers take a single JSON-encoded string
    `filter` parameter; malformed JSON, wrong-typed values, or unsupported
    keys produce recoverable API-style errors, one at a time.
  - M3: list_service_areas, query_members, and search_providers return
    Notion-style deeply nested records with cursor pagination
    (has_more / next_cursor instead of total/total_pages).
  - M5: export_network_directory returns the entire joined provider network
    directory as one JSON string, no pagination (context-pressure trap).
Task semantics, data, prompt deliverables, and scoring are unchanged from
the base environment.
"""

import ast
import sqlite3
import json
import os
import csv
import math
import hashlib
import glob as globmod
from typing import Tuple, Dict, List, Any
from datetime import date


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


def haversine_miles(lat1, lon1, lat2, lon2):
    """Compute great-circle distance in miles between two lat/lon points."""
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


PAGE_SIZE = 20


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


# ---------------------------------------------------------------------------
# Notion-style nested record builders (M3)
# ---------------------------------------------------------------------------

def _select(name):
    return {"type": "select", "select": {"name": name}}


def _number(value):
    return {"type": "number", "number": value}


def _title(text):
    return {"type": "title", "title": [
        {"type": "text", "text": {"content": text, "link": None}, "plain_text": text}]}


def _relation(*ids):
    return {"type": "relation", "relation": [{"id": i} for i in ids]}


def _rich_text(text):
    return {"type": "rich_text", "rich_text": [
        {"type": "text", "text": {"content": text, "link": None}, "plain_text": text}]}


def _checkbox(value):
    return {"type": "checkbox", "checkbox": bool(value)}


def _multi_select(names):
    return {"type": "multi_select", "multi_select": [{"name": n} for n in names]}


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

    # ── Tool methods ─────────────────────────────────────────────────────

    @tool(
        description=(
            "List all health-plan service areas. Each record contains the "
            "service area's ID, name, urban/suburban/rural classification, "
            "and state."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_service_areas(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT area_id, area_name, area_type, state FROM service_areas ORDER BY area_id")
        rows = cur.fetchall()
        conn.close()
        results = [
            {
                "object": "service_area",
                "id": r[0],
                "properties": {
                    "Name": _title(r[1]),
                    "Classification": _select(r[2]),
                    "State": _select(r[3]),
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
        description="List all covered medical specialties with their ID, name, and category.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_specialties(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT specialty_id, specialty_name, category FROM specialties ORDER BY specialty_id")
        rows = cur.fetchall()
        conn.close()
        return [
            {"specialty_id": r[0], "specialty_name": r[1], "category": r[2]}
            for r in rows
        ]

    @tool(
        description=(
            "Query enrolled members. Filtering is expressed as a JSON-encoded "
            "string, e.g. filter='{\"service_area_id\": 3}'. Supported filter "
            "properties: service_area_id (integer) and gender (\"M\" | \"F\"). "
            "Each record contains the member's ID, full name, and assigned "
            "service area. Results are paginated (20 per page, 1-based)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"service_area_id\": 2}'. Pass '{}' or omit for no "
                        "filtering."
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
    def query_members(self, filter: Any = None, page: int = 1):
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"service_area_id", "gender"}
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: service_area_id, gender.")

        clauses = []
        params: list = []
        if "service_area_id" in parsed:
            said = parsed["service_area_id"]
            if not isinstance(said, int) or isinstance(said, bool):
                return _error(400, "validation_error",
                    f"body.filter.service_area_id should be an integer, "
                    f"instead was {_shape(said)}.")
            clauses.append("service_area_id = ?")
            params.append(said)
        if "gender" in parsed:
            gender = parsed["gender"]
            if not isinstance(gender, str) or gender not in ("M", "F"):
                return _error(400, "validation_error",
                    f"body.filter.gender should be one of \"M\", \"F\", "
                    f"instead was {_shape(gender)}.")
            clauses.append("gender = ?")
            params.append(gender)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        if "service_area_id" in parsed:
            cur.execute("SELECT area_id FROM service_areas WHERE area_id = ?",
                        (parsed["service_area_id"],))
            if cur.fetchone() is None:
                conn.close()
                return _error(404, "object_not_found",
                    f"Could not find service area with ID: {parsed['service_area_id']}.")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        cur.execute(f"SELECT COUNT(*) FROM members{where}", params)
        total = cur.fetchone()[0]
        page = max(1, page)
        offset = (page - 1) * PAGE_SIZE
        cur.execute(
            f"SELECT member_id, first_name, last_name, service_area_id "
            f"FROM members{where} ORDER BY member_id LIMIT ? OFFSET ?",
            params + [PAGE_SIZE, offset],
        )
        rows = cur.fetchall()
        conn.close()

        results = [
            {
                "object": "member",
                "id": r[0],
                "properties": {
                    "Name": _title(f"{r[1]} {r[2]}"),
                    "Service Area": _relation(r[3]),
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
            "Geocode a batch of members by their IDs. Returns latitude and "
            "longitude for each member. Accepts up to 20 member IDs per call."
        ),
        parameters={
            "type": "object",
            "properties": {
                "member_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of member IDs (max 20).",
                },
            },
            "required": ["member_ids"],
        },
    )
    def geocode_members(self, member_ids: Any = None):
        if member_ids is None:
            return _error(400, "validation_error",
                "body.member_ids should be defined, instead was 'undefined'.")
        if not isinstance(member_ids, list) or not all(
            isinstance(i, int) and not isinstance(i, bool) for i in member_ids
        ):
            return _error(400, "validation_error",
                f"body.member_ids should be an array of integers, instead was "
                f"{_shape(member_ids)}.")
        ids = member_ids[:20]
        placeholders = ",".join("?" for _ in ids)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            f"SELECT member_id, latitude, longitude FROM members "
            f"WHERE member_id IN ({placeholders})",
            ids,
        )
        rows = cur.fetchall()
        conn.close()
        return [
            {"member_id": r[0], "latitude": r[1], "longitude": r[2]}
            for r in rows
        ]

    @tool(
        description=(
            "Search for provider office locations. Filtering is expressed as a "
            "JSON-encoded string, e.g. filter='{\"specialty_id\": 4}'. Supported "
            "filter properties: specialty_id (integer, required) and "
            "accepting_new_patients (boolean). Each record contains the office "
            "name, the provider reference and display name, the office "
            "coordinates, whether the provider accepts new patients, and the "
            "plan types for which the provider holds an active network "
            "contract. Results are paginated (20 per page, 1-based)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"specialty_id\": 1, \"accepting_new_patients\": true}'. "
                        "specialty_id is required."
                    ),
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Defaults to 1.",
                },
            },
            "required": ["filter"],
        },
    )
    def search_providers(self, filter: Any = None, page: int = 1):
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"specialty_id", "accepting_new_patients"}
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: specialty_id, accepting_new_patients.")

        specialty_id = parsed.get("specialty_id")
        if specialty_id is None:
            return _error(400, "validation_error",
                "body.filter.specialty_id should be defined, instead was 'undefined'.")
        if not isinstance(specialty_id, int) or isinstance(specialty_id, bool):
            return _error(400, "validation_error",
                f"body.filter.specialty_id should be an integer, instead was "
                f"{_shape(specialty_id)}.")

        clauses = ["pl.specialty_id = ?"]
        params: list = [specialty_id]
        if "accepting_new_patients" in parsed:
            anp = parsed["accepting_new_patients"]
            if not isinstance(anp, bool):
                return _error(400, "validation_error",
                    f"body.filter.accepting_new_patients should be a boolean, "
                    f"instead was {_shape(anp)}.")
            clauses.append("p.accepting_new_patients = ?")
            params.append(int(anp))

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute("SELECT specialty_id FROM specialties WHERE specialty_id = ?",
                    (specialty_id,))
        if cur.fetchone() is None:
            conn.close()
            return _error(404, "object_not_found",
                f"Could not find specialty with ID: {specialty_id}.")

        where = " AND ".join(clauses)
        cur.execute(
            f"SELECT COUNT(*) FROM provider_locations pl "
            f"JOIN providers p ON pl.provider_id = p.provider_id WHERE {where}",
            params,
        )
        total = cur.fetchone()[0]
        page = max(1, page)
        offset = (page - 1) * PAGE_SIZE

        cur.execute(
            f"""
            SELECT pl.location_id, pl.provider_id,
                   p.first_name, p.last_name,
                   pl.latitude, pl.longitude,
                   p.accepting_new_patients, pl.office_name
            FROM provider_locations pl
            JOIN providers p ON pl.provider_id = p.provider_id
            WHERE {where}
            ORDER BY pl.location_id
            LIMIT ? OFFSET ?
            """,
            params + [PAGE_SIZE, offset],
        )
        loc_rows = cur.fetchall()

        results = []
        for lr in loc_rows:
            pid = lr[1]
            cur.execute(
                "SELECT DISTINCT plan_type FROM network_contracts "
                "WHERE provider_id = ? AND status = 'active'",
                (pid,),
            )
            plans = [r[0] for r in cur.fetchall()]

            results.append({
                "object": "provider_location",
                "id": lr[0],
                "properties": {
                    "Office": _title(lr[7]),
                    "Provider": _relation(pid),
                    "Provider Name": _rich_text(f"Dr. {lr[2]} {lr[3]}"),
                    "Latitude": _number(lr[4]),
                    "Longitude": _number(lr[5]),
                    "Accepting New Patients": _checkbox(lr[6]),
                    "Contracted Plans": _multi_select(plans),
                },
            })

        conn.close()
        has_more = offset + len(loc_rows) < total
        return {
            "object": "list",
            "results": results,
            "has_more": has_more,
            "next_cursor": page + 1 if has_more else None,
        }

    @tool(
        description=(
            "Export the complete provider network directory in a single "
            "response: one record per provider office location across all "
            "specialties and service areas, joined with the provider's "
            "identity, credential type, patient acceptance status, and "
            "full network contract history (plan type, status, effective and "
            "termination dates). No pagination required."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def export_network_directory(self) -> str:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT pl.location_id, pl.provider_id,
                   p.first_name, p.last_name, p.credential_type,
                   pl.specialty_id, s.specialty_name, pl.office_name,
                   pl.latitude, pl.longitude, p.accepting_new_patients
            FROM provider_locations pl
            JOIN providers p ON pl.provider_id = p.provider_id
            JOIN specialties s ON pl.specialty_id = s.specialty_id
            ORDER BY pl.location_id
            """
        )
        loc_rows = cur.fetchall()

        cur.execute(
            "SELECT provider_id, plan_type, status, effective_date, termination_date "
            "FROM network_contracts ORDER BY contract_id"
        )
        contracts_by_pid: Dict[int, list] = {}
        for r in cur.fetchall():
            contracts_by_pid.setdefault(r[0], []).append({
                "plan_type": r[1],
                "status": r[2],
                "effective_date": r[3],
                "termination_date": r[4],
            })
        conn.close()

        records = []
        for lr in loc_rows:
            records.append({
                "location_id": lr[0],
                "provider_id": lr[1],
                "provider_name": f"Dr. {lr[2]} {lr[3]}",
                "credential_type": lr[4],
                "specialty_id": lr[5],
                "specialty_name": lr[6],
                "office_name": lr[7],
                "latitude": lr[8],
                "longitude": lr[9],
                "accepting_new_patients": bool(lr[10]),
                "contracts": contracts_by_pid.get(lr[1], []),
            })
        return json.dumps(
            {"record_count": len(records), "records": records},
            ensure_ascii=False,
        )

    # ── Evaluation ───────────────────────────────────────────────────────

    def _load_workspace_config(self):
        """Load config files from workspace."""
        # Distance thresholds (hand-parse simple YAML)
        thresholds = {}
        yaml_path = os.path.join(self.workspace, "distance_thresholds.yaml")
        with open(yaml_path) as f:
            current_spec = None
            for line in f:
                line = line.rstrip()
                if not line:
                    continue
                if not line.startswith(" "):
                    current_spec = line.rstrip(":")
                    thresholds[current_spec] = {}
                else:
                    parts = line.strip().split(": ")
                    thresholds[current_spec][parts[0]] = int(parts[1])

        # Compliance standards
        std_path = os.path.join(self.workspace, "compliance_standards.json")
        with open(std_path) as f:
            standards = json.load(f)

        return thresholds, standards

    def _load_workspace_credentials(self):
        """Load provider credentials from all workspace JSON files."""
        cred_map = {}  # provider_id -> {board_certified, certification_expiry}
        pattern = os.path.join(self.workspace, "provider_cred_*.json")
        for fpath in sorted(globmod.glob(pattern)):
            with open(fpath) as f:
                records = json.load(f)
            for rec in records:
                cred_map[rec["provider_id"]] = {
                    "board_certified": rec["board_certified"],
                    "certification_expiry": rec["certification_expiry"],
                }
        return cred_map

    def _compute_ground_truth(self):
        """Compute the correct deficiency report using direct DB + workspace access."""
        thresholds, standards = self._load_workspace_config()
        cred_map = self._load_workspace_credentials()
        ref_date = date.fromisoformat(standards["reference_date"])
        required_pct = standards["required_coverage_pct"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Load service areas and specialties
        cur.execute("SELECT * FROM service_areas ORDER BY area_id")
        areas = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM specialties ORDER BY specialty_id")
        specs = [dict(r) for r in cur.fetchall()]

        # Load members
        cur.execute("SELECT member_id, plan_type, service_area_id, latitude, longitude FROM members")
        members = [dict(r) for r in cur.fetchall()]

        # Load provider locations with provider info
        cur.execute("""
            SELECT pl.location_id, pl.provider_id, pl.specialty_id,
                   pl.latitude, pl.longitude, p.accepting_new_patients
            FROM provider_locations pl
            JOIN providers p ON pl.provider_id = p.provider_id
        """)
        all_locations = [dict(r) for r in cur.fetchall()]

        # Load active contracts: provider_id -> set of plan_types
        cur.execute(
            "SELECT provider_id, plan_type FROM network_contracts WHERE status = 'active'"
        )
        active_contracts = {}
        for r in cur.fetchall():
            active_contracts.setdefault(r[0], set()).add(r[1])
        conn.close()

        # Pre-filter eligible provider locations
        # Eligible = board_certified + not expired + accepting_new + has active contract
        def is_provider_eligible(pid, plan_type):
            cred = cred_map.get(pid)
            if not cred or not cred["board_certified"]:
                return False
            if cred["certification_expiry"] is None:
                return False
            if date.fromisoformat(cred["certification_expiry"]) < ref_date:
                return False
            contracts = active_contracts.get(pid, set())
            if plan_type not in contracts:
                return False
            return True

        # Group members by service area
        area_members = {}
        for m in members:
            area_members.setdefault(m["service_area_id"], []).append(m)

        # Group locations by specialty
        spec_locations = {}
        for loc in all_locations:
            spec_locations.setdefault(loc["specialty_id"], []).append(loc)

        # Build report
        report_rows = []
        for area in areas:
            aid = area["area_id"]
            atype = area["area_type"]
            mems = area_members.get(aid, [])
            total_members = len(mems)

            for spec in specs:
                sid = spec["specialty_id"]
                sname = spec["specialty_name"]
                threshold = thresholds.get(sname, {}).get(atype, 9999)
                req_pct = required_pct.get(sname, 0)

                locs = spec_locations.get(sid, [])

                # For each member, check if at least one eligible provider
                # is within threshold
                covered = 0
                for m in mems:
                    mlat, mlon = m["latitude"], m["longitude"]
                    mplan = m["plan_type"]
                    found = False
                    # Group locs by provider_id to find closest per provider
                    provider_locs = {}
                    for loc in locs:
                        pid = loc["provider_id"]
                        if not loc["accepting_new_patients"]:
                            continue
                        provider_locs.setdefault(pid, []).append(loc)

                    for pid, plocs in provider_locs.items():
                        if not is_provider_eligible(pid, mplan):
                            continue
                        # Find closest location for this provider
                        min_dist = min(
                            haversine_miles(mlat, mlon, pl["latitude"], pl["longitude"])
                            for pl in plocs
                        )
                        if min_dist <= threshold:
                            found = True
                            break
                    if found:
                        covered += 1

                cov_pct = round(covered / total_members * 100, 2) if total_members > 0 else 0.0
                compliant = "YES" if cov_pct >= req_pct else "NO"

                report_rows.append({
                    "service_area_id": aid,
                    "service_area_name": area["area_name"],
                    "area_type": atype,
                    "specialty_id": sid,
                    "specialty_name": sname,
                    "distance_threshold_miles": threshold,
                    "total_members": total_members,
                    "members_with_access": covered,
                    "members_without_access": total_members - covered,
                    "coverage_pct": cov_pct,
                    "required_coverage_pct": req_pct,
                    "compliant": compliant,
                })

        return report_rows

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
        gt_rows = self._compute_ground_truth()
        criteria = {}

        # ── Criterion 1: deficiency_report.csv exists (10 pts) ───────────
        report_path = os.path.join(self.workspace, "deficiency_report.csv")
        file_exists = os.path.isfile(report_path)
        criteria["file_exists"] = {
            "passed": file_exists,
            "score": 10 if file_exists else 0,
            "max_score": 10,
        }
        if not file_exists:
            criteria["file_exists"]["reason"] = "deficiency_report.csv not found in workspace"

        # Try to parse submitted report
        submitted = []
        if file_exists:
            try:
                with open(report_path, newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        submitted.append(row)
            except Exception as e:
                criteria["file_exists"]["reason"] = f"Error parsing CSV: {e}"

        # ── Criterion 2: correct columns (10 pts) ────────────────────────
        expected_cols = [
            "service_area_id", "service_area_name", "area_type",
            "specialty_id", "specialty_name", "distance_threshold_miles",
            "total_members", "members_with_access", "members_without_access",
            "coverage_pct", "required_coverage_pct", "compliant",
        ]
        if submitted:
            actual_cols = list(submitted[0].keys())
            cols_match = actual_cols == expected_cols
        else:
            actual_cols = []
            cols_match = False
        criteria["correct_columns"] = {
            "passed": cols_match,
            "score": 10 if cols_match else 0,
            "max_score": 10,
        }
        if not cols_match:
            criteria["correct_columns"]["reason"] = (
                f"Expected columns {expected_cols}, got {actual_cols}"
            )

        # ── Criterion 3: correct row count (10 pts) ─────────────────────
        expected_rows = len(gt_rows)
        row_count_ok = len(submitted) == expected_rows
        criteria["correct_row_count"] = {
            "passed": row_count_ok,
            "score": 10 if row_count_ok else 0,
            "max_score": 10,
        }
        if not row_count_ok:
            criteria["correct_row_count"]["reason"] = (
                f"Expected {expected_rows} rows, got {len(submitted)}"
            )

        # ── Criterion 4: coverage_pct accuracy (30 pts) ──────────────────
        # Build ground-truth lookup: (area_id, spec_id) -> gt row
        gt_lookup = {}
        for r in gt_rows:
            gt_lookup[(r["service_area_id"], r["specialty_id"])] = r

        cov_correct = 0
        cov_total = len(gt_rows)
        for row in submitted:
            try:
                key = (int(row["service_area_id"]), int(row["specialty_id"]))
                gt = gt_lookup.get(key)
                if gt and abs(float(row["coverage_pct"]) - gt["coverage_pct"]) < 1.01:
                    cov_correct += 1
            except (ValueError, KeyError):
                pass

        cov_score = round(30 * cov_correct / cov_total, 1) if cov_total else 0
        criteria["coverage_accuracy"] = {
            "passed": cov_correct == cov_total,
            "score": cov_score,
            "max_score": 30,
        }
        if cov_correct < cov_total:
            criteria["coverage_accuracy"]["reason"] = (
                f"{cov_correct}/{cov_total} rows have correct coverage_pct (within 1%)"
            )

        # ── Criterion 5: compliant determination (25 pts) ────────────────
        comp_correct = 0
        for row in submitted:
            try:
                key = (int(row["service_area_id"]), int(row["specialty_id"]))
                gt = gt_lookup.get(key)
                if gt and row.get("compliant", "").strip().upper() == gt["compliant"]:
                    comp_correct += 1
            except (ValueError, KeyError):
                pass

        comp_score = round(25 * comp_correct / cov_total, 1) if cov_total else 0
        criteria["compliance_determination"] = {
            "passed": comp_correct == cov_total,
            "score": comp_score,
            "max_score": 25,
        }
        if comp_correct < cov_total:
            criteria["compliance_determination"]["reason"] = (
                f"{comp_correct}/{cov_total} rows have correct compliant flag"
            )

        # ── Criterion 6: response summary of non-compliant combos (15 pts) ─
        non_compliant = [
            r for r in gt_rows if r["compliant"] == "NO"
        ]
        mentioned = 0
        action_upper = action.upper() if action else ""
        for nc in non_compliant:
            # Check area name and specialty name both appear near each other
            aname = nc["service_area_name"].upper()
            sname = nc["specialty_name"].upper()
            if aname in action_upper and sname in action_upper:
                mentioned += 1

        if len(non_compliant) > 0:
            summary_score = round(15 * mentioned / len(non_compliant), 1)
            summary_ok = mentioned == len(non_compliant)
        else:
            summary_score = 15
            summary_ok = True

        criteria["response_summary"] = {
            "passed": summary_ok,
            "score": summary_score,
            "max_score": 15,
        }
        if not summary_ok:
            criteria["response_summary"]["reason"] = (
                f"Response mentions {mentioned}/{len(non_compliant)} non-compliant pairs"
            )

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score, info

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
        (M1), walking Notion-style nested records with cursor pagination (M3),
        and consuming the bulk network-directory export as one JSON string,
        in memory (M5).
        """
        tool_calls = 0

        def _call(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        # ── 1. Read workspace config files ───────────────────────────────
        # Distance thresholds (hand-parse the simple two-level YAML)
        thresholds = {}
        with open(os.path.join(self.workspace, "distance_thresholds.yaml")) as f:
            current_spec = None
            for line in f:
                line = line.rstrip()
                if not line:
                    continue
                if not line.startswith(" "):
                    current_spec = line.rstrip(":")
                    thresholds[current_spec] = {}
                else:
                    parts = line.strip().split(": ")
                    thresholds[current_spec][parts[0]] = int(parts[1])

        # Compliance standards
        with open(os.path.join(self.workspace, "compliance_standards.json")) as f:
            standards = json.load(f)
        ref_date = date.fromisoformat(standards["reference_date"])
        required_pct = standards["required_coverage_pct"]

        # ── 2. Read workspace member roster files (for plan_type) ────────
        member_plan = {}  # member_id -> plan_type
        pattern = os.path.join(self.workspace, "member_roster_*.csv")
        for fpath in sorted(globmod.glob(pattern)):
            with open(fpath, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    member_plan[int(row["member_id"])] = row["plan_type"]

        # ── 3. Read workspace provider credential files ──────────────────
        cred_map = {}  # provider_id -> {board_certified, certification_expiry}
        cred_pattern = os.path.join(self.workspace, "provider_cred_*.json")
        for fpath in sorted(globmod.glob(cred_pattern)):
            with open(fpath) as f:
                records = json.load(f)
            for rec in records:
                cred_map[rec["provider_id"]] = {
                    "board_certified": rec["board_certified"],
                    "certification_expiry": rec["certification_expiry"],
                }

        # ── 4. Call tools to gather data ─────────────────────────────────
        # List service areas (M3 nested records)
        area_resp = _call("list_service_areas")
        areas = []
        for rec in area_resp["results"]:
            areas.append({
                "area_id": rec["id"],
                "area_name": rec["properties"]["Name"]["title"][0]["plain_text"],
                "area_type": rec["properties"]["Classification"]["select"]["name"],
            })

        # List specialties (native)
        specs = _call("list_specialties")

        # Get members per service area (M1 JSON-string filter + cursor pagination)
        area_member_ids = {}  # area_id -> [member_id, ...]
        for area in areas:
            aid = area["area_id"]
            area_member_ids[aid] = []
            page = 1
            while True:
                result = _call(
                    "query_members",
                    filter=json.dumps({"service_area_id": aid}),
                    page=page,
                )
                for rec in result["results"]:
                    area_member_ids[aid].append(rec["id"])
                if not result["has_more"]:
                    break
                page = result["next_cursor"]

        # Geocode all members (batches of 20)
        all_member_ids = []
        for ids in area_member_ids.values():
            all_member_ids.extend(ids)
        member_coords = {}  # member_id -> (lat, lon)
        for i in range(0, len(all_member_ids), 20):
            batch = all_member_ids[i : i + 20]
            results = _call("geocode_members", member_ids=batch)
            for r in results:
                member_coords[r["member_id"]] = (r["latitude"], r["longitude"])

        # ── 5. Consume the bulk export ONCE, in memory (M5) ──────────────
        # Use it to derive each provider's active contracted plan set from
        # the raw contract history.
        raw = _call("export_network_directory")
        directory = json.loads(raw)
        provider_active_plans = {}  # provider_id -> set of plan_types
        for rec in directory["records"]:
            pid = rec["provider_id"]
            if pid not in provider_active_plans:
                provider_active_plans[pid] = {
                    c["plan_type"] for c in rec["contracts"]
                    if c["status"] == "active"
                }

        # Search providers by specialty (M1 filter + M3 records + cursor pages)
        spec_providers = {}  # specialty_id -> list of provider-location dicts
        for spec in specs:
            sid = spec["specialty_id"]
            spec_providers[sid] = []
            page = 1
            while True:
                result = _call(
                    "search_providers",
                    filter=json.dumps({"specialty_id": sid}),
                    page=page,
                )
                for rec in result["results"]:
                    props = rec["properties"]
                    spec_providers[sid].append({
                        "location_id": rec["id"],
                        "provider_id": props["Provider"]["relation"][0]["id"],
                        "latitude": props["Latitude"]["number"],
                        "longitude": props["Longitude"]["number"],
                        "accepting_new_patients": props["Accepting New Patients"]["checkbox"],
                    })
                if not result["has_more"]:
                    break
                page = result["next_cursor"]

        # ── 6. Determine eligibility and coverage ────────────────────────
        def provider_eligible(pid, plan_type):
            """Check credential + contract eligibility for a provider."""
            if plan_type not in provider_active_plans.get(pid, set()):
                return False
            cred = cred_map.get(pid)
            if not cred or not cred["board_certified"]:
                return False
            if cred["certification_expiry"] is None:
                return False
            if date.fromisoformat(cred["certification_expiry"]) < ref_date:
                return False
            return True

        report_rows = []
        for area in areas:
            aid = area["area_id"]
            atype = area["area_type"]
            mids = area_member_ids.get(aid, [])
            total_members = len(mids)

            for spec in specs:
                sid = spec["specialty_id"]
                sname = spec["specialty_name"]
                threshold = thresholds.get(sname, {}).get(atype, 9999)
                req = required_pct.get(sname, 0)

                provs = spec_providers.get(sid, [])

                # Group locations by provider_id (accepting locations only)
                pid_locs = {}
                for p in provs:
                    if not p["accepting_new_patients"]:
                        continue
                    pid_locs.setdefault(p["provider_id"], []).append(p)

                covered = 0
                for mid in mids:
                    mlat, mlon = member_coords[mid]
                    mplan = member_plan[mid]
                    found = False
                    for pid, plocs in pid_locs.items():
                        if not provider_eligible(pid, mplan):
                            continue
                        min_dist = min(
                            haversine_miles(mlat, mlon, pl["latitude"], pl["longitude"])
                            for pl in plocs
                        )
                        if min_dist <= threshold:
                            found = True
                            break
                    if found:
                        covered += 1

                cov_pct = round(covered / total_members * 100, 2) if total_members > 0 else 0.0
                compliant = "YES" if cov_pct >= req else "NO"

                report_rows.append({
                    "service_area_id": aid,
                    "service_area_name": area["area_name"],
                    "area_type": atype,
                    "specialty_id": sid,
                    "specialty_name": sname,
                    "distance_threshold_miles": threshold,
                    "total_members": total_members,
                    "members_with_access": covered,
                    "members_without_access": total_members - covered,
                    "coverage_pct": cov_pct,
                    "required_coverage_pct": req,
                    "compliant": compliant,
                })

        # ── 7. Write deficiency_report.csv ───────────────────────────────
        report_path = os.path.join(self.workspace, "deficiency_report.csv")
        fieldnames = [
            "service_area_id", "service_area_name", "area_type",
            "specialty_id", "specialty_name", "distance_threshold_miles",
            "total_members", "members_with_access", "members_without_access",
            "coverage_pct", "required_coverage_pct", "compliant",
        ]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in report_rows:
                writer.writerow(row)

        # ── 8. Build action string (summary of non-compliant) ────────────
        non_compliant = [r for r in report_rows if r["compliant"] == "NO"]
        lines = ["Network Adequacy Compliance Analysis Complete.", ""]
        lines.append(f"Total service-area/specialty pairs evaluated: {len(report_rows)}")
        lines.append(f"Non-compliant pairs: {len(non_compliant)}")
        lines.append("")
        if non_compliant:
            lines.append("Non-compliant service area and specialty combinations:")
            lines.append("")
            for nc in non_compliant:
                lines.append(
                    f"- {nc['service_area_name']} / {nc['specialty_name']}: "
                    f"coverage {nc['coverage_pct']:.2f}% "
                    f"(required {nc['required_coverage_pct']:.2f}%)"
                )
        else:
            lines.append("All service area and specialty combinations are compliant.")

        action = "\n".join(lines)

        print(f"[verify] Total tool calls: {tool_calls}")
        return self.step(action)
