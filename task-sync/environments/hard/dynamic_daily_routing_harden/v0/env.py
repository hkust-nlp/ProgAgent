"""
env.py - Task environment for technician schedule optimization.

Hardened tool surface (M1 + M4):
  - list_jobs takes a single JSON-encoded string `filter` parameter;
  - create_dispatch_record takes a deeply nested Notion-style request body
    with layered, one-error-at-a-time validation;
  - tools never raise: every failure returns an API-style error dict that
    shares no keys with success responses.
"""
from typing import Tuple, Dict, List, Any
import sqlite3
import os
import json
import csv
import re
import math
import yaml
import ast
import hashlib


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


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

        # Dispatch-record table used by create_dispatch_record (write API).
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS dispatch_assignments ("
            "job_id TEXT PRIMARY KEY, "
            "technician_id TEXT NOT NULL, "
            "note TEXT)"
        )
        conn.commit()
        conn.close()

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

    # ======================== TOOLS ========================

    @tool(
        description="List all service zones in the dispatch area.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_zones(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT DISTINCT from_zone FROM traffic_conditions ORDER BY from_zone"
        ).fetchall()
        conn.close()
        zones = sorted(set(r[0] for r in rows))
        return {"zones": zones, "count": len(zones)}

    @tool(
        description=(
            "List technicians with optional status filter. "
            "Returns paginated results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status, e.g. 'available'.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting at 1 (default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 10, max 50).",
                },
            },
            "required": [],
        },
    )
    def list_technicians(self, status=None, page=1, page_size=10):
        try:
            page = max(1, int(page))
            page_size = max(1, min(50, int(page_size)))
        except (TypeError, ValueError):
            return _error(400, "validation_error",
                          f"body.page and body.page_size should be integers, "
                          f"instead were {_shape(page)}, {_shape(page_size)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM technicians"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        total = conn.execute(
            query.replace("SELECT *", "SELECT COUNT(*)"), params
        ).fetchone()[0]
        query += " ORDER BY tech_id LIMIT ? OFFSET ?"
        params.extend([page_size, (page - 1) * page_size])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        technicians = [
            {
                "tech_id": r["tech_id"],
                "name": r["name"],
                "skill_level": r["skill_level"],
                "van_id": r["van_id"],
                "shift_start": r["shift_start"],
                "shift_end": r["shift_end"],
                "home_zone": r["home_zone"],
                "status": r["status"],
            }
            for r in rows
        ]
        return {"technicians": technicians, "page": page,
                "page_size": page_size, "total": total}

    @tool(
        description=(
            "List service jobs. Filtering is expressed as a JSON-encoded "
            "string, e.g. filter='{\"status\": \"pending\", \"priority_tier\": "
            "\"P1\"}'. Supported filter properties: status (e.g. 'pending'), "
            "priority_tier (e.g. 'P1'), and zone (zone name). Returns "
            "paginated results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"status\": \"pending\", \"zone\": \"Downtown\"}'. "
                        "Pass '{}' or omit for no filtering."
                    ),
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting at 1 (default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 10, max 50).",
                },
            },
            "required": [],
        },
    )
    def list_jobs(self, filter: Any = None, page=1, page_size=10):
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = ("status", "priority_tier", "zone")
        for key in parsed:
            if key not in supported:
                return _error(
                    400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: status, priority_tier, zone.",
                )

        clauses, params = [], []
        for key in supported:
            if key in parsed:
                val = parsed[key]
                if not isinstance(val, str) or not val:
                    return _error(
                        400, "validation_error",
                        f"body.filter.{key} should be a non-empty string, "
                        f"instead was {_shape(val)}.",
                    )
                clauses.append(f"{key} = ?")
                params.append(val)

        try:
            page = max(1, int(page))
            page_size = max(1, min(50, int(page_size)))
        except (TypeError, ValueError):
            return _error(400, "validation_error",
                          f"body.page and body.page_size should be integers, "
                          f"instead were {_shape(page)}, {_shape(page_size)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM jobs{where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM jobs{where} ORDER BY job_id LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
        conn.close()
        jobs = [
            {
                "job_id": r["job_id"],
                "customer_name": r["customer_name"],
                "address": r["address"],
                "zone": r["zone"],
                "job_type": r["job_type"],
                "priority_tier": r["priority_tier"],
                "estimated_duration_min": r["estimated_duration_min"],
                "window_start": r["window_start"],
                "window_end": r["window_end"],
                "required_skill_level": r["required_skill_level"],
                "status": r["status"],
            }
            for r in rows
        ]
        return {"jobs": jobs, "page": page, "page_size": page_size,
                "total": total}

    @tool(
        description="Get full details of a single technician by ID.",
        parameters={
            "type": "object",
            "properties": {
                "tech_id": {
                    "type": "string",
                    "description": "Technician identifier, e.g. 'TECH_001'.",
                },
            },
            "required": ["tech_id"],
        },
    )
    def get_technician(self, tech_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM technicians WHERE tech_id = ?", (tech_id,)
        ).fetchone()
        conn.close()
        if not row:
            return _error(404, "object_not_found",
                          f"Could not find technician with ID: {tech_id}.")
        return {"technician": dict(row)}

    @tool(
        description="Get full details of a single job by ID.",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Job identifier, e.g. 'JOB_001'.",
                },
            },
            "required": ["job_id"],
        },
    )
    def get_job_details(self, job_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        conn.close()
        if not row:
            return _error(404, "object_not_found",
                          f"Could not find job with ID: {job_id}.")
        return {"job": dict(row)}

    @tool(
        description=(
            "List all parts currently carried in a specific service van, "
            "with quantities."
        ),
        parameters={
            "type": "object",
            "properties": {
                "van_id": {
                    "type": "string",
                    "description": "Van identifier, e.g. 'VAN_001'.",
                },
            },
            "required": ["van_id"],
        },
    )
    def get_van_inventory(self, van_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT pi.part_id, pc.part_name, pi.quantity "
            "FROM parts_inventory pi "
            "JOIN parts_catalog pc ON pi.part_id = pc.part_id "
            "WHERE pi.van_id = ? ORDER BY pi.part_id",
            (van_id,),
        ).fetchall()
        conn.close()
        parts = [{"part_id": r["part_id"], "part_name": r["part_name"],
                   "quantity": r["quantity"]} for r in rows]
        return {"van_id": van_id, "parts": parts}

    @tool(
        description="Get the list of parts required to complete a specific job.",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Job identifier, e.g. 'JOB_001'.",
                },
            },
            "required": ["job_id"],
        },
    )
    def get_job_required_parts(self, job_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT jp.part_id, pc.part_name, jp.quantity_needed "
            "FROM job_parts jp "
            "JOIN parts_catalog pc ON jp.part_id = pc.part_id "
            "WHERE jp.job_id = ? ORDER BY jp.part_id",
            (job_id,),
        ).fetchall()
        conn.close()
        parts = [{"part_id": r["part_id"], "part_name": r["part_name"],
                   "quantity_needed": r["quantity_needed"]} for r in rows]
        return {"job_id": job_id, "parts": parts}

    @tool(
        description=(
            "Get real-time traffic information for traveling between two zones, "
            "including base travel time, congestion factor, and road condition."
        ),
        parameters={
            "type": "object",
            "properties": {
                "from_zone": {
                    "type": "string",
                    "description": "Origin zone name.",
                },
                "to_zone": {
                    "type": "string",
                    "description": "Destination zone name.",
                },
            },
            "required": ["from_zone", "to_zone"],
        },
    )
    def get_travel_info(self, from_zone: str, to_zone: str):
        if from_zone == to_zone:
            return {
                "from_zone": from_zone,
                "to_zone": to_zone,
                "base_travel_min": 5.0,
                "congestion_factor": 1.0,
                "road_condition": "good",
                "note": "Intra-zone travel estimate",
            }
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM traffic_conditions "
            "WHERE from_zone = ? AND to_zone = ?",
            (from_zone, to_zone),
        ).fetchone()
        conn.close()
        if not row:
            return _error(404, "object_not_found",
                          f"Could not find traffic segment with ID: "
                          f"{from_zone}->{to_zone}.")
        return {
            "from_zone": row["from_zone"],
            "to_zone": row["to_zone"],
            "base_travel_min": row["base_travel_min"],
            "congestion_factor": row["congestion_factor"],
            "road_condition": row["road_condition"],
            "last_updated": row["last_updated"],
        }

    @tool(
        description=(
            "Creates a dispatch record: commits a pending job onto a "
            "technician's route in the dispatch system. The request body must "
            "contain a `parent` object identifying the receiving technician "
            "route and a `properties` object with a `Job` reference property. "
            "Example body: {\"parent\": {\"type\": \"technician_route\", "
            "\"technician_id\": \"TECH_001\"}, \"properties\": {\"Job\": "
            "{\"type\": \"reference\", \"reference\": {\"job_id\": "
            "\"JOB_001\"}}}}. An optional `Note` rich_text property may be "
            "included in `properties`. Each job can be committed only once."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "The dispatch record request body.",
                    "properties": {
                        "parent": {
                            "type": "object",
                            "description": (
                                "The technician route that receives the job. "
                                "Must contain type='technician_route' and a "
                                "technician_id string."
                            ),
                            "properties": {
                                "type": {"type": "string"},
                                "technician_id": {"type": "string"},
                            },
                            "required": ["type", "technician_id"],
                            "additionalProperties": True,
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Dispatch record properties. Must include a "
                                "'Job' reference property. May include a "
                                "'Note' rich_text property."
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
    def create_dispatch_record(self, payload: Any = None) -> dict:
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
        if parent.get("type") != "technician_route":
            return _error(
                400, "validation_error",
                f"body.parent.type should be \"technician_route\", instead was "
                f"{_shape(parent.get('type'))}.",
            )
        technician_id = parent.get("technician_id")
        if not isinstance(technician_id, str) or not technician_id:
            return _error(
                400, "validation_error",
                f"body.parent.technician_id should be a non-empty string, "
                f"instead was {_shape(technician_id)}.",
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

        job_prop = props.get("Job")
        if job_prop is None:
            return _error(
                400, "validation_error",
                "body.properties.Job should be defined, instead was 'undefined'.",
            )
        if not isinstance(job_prop, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Job should be an object, instead was "
                f"{_shape(job_prop)}.",
            )
        if job_prop.get("type") != "reference":
            return _error(
                400, "validation_error",
                f"body.properties.Job.type should be \"reference\", instead was "
                f"{_shape(job_prop.get('type'))}.",
            )
        reference = job_prop.get("reference")
        if not isinstance(reference, dict):
            return _error(
                400, "validation_error",
                f"body.properties.Job.reference should be an object, instead was "
                f"{_shape(reference)}.",
            )
        job_id = reference.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            return _error(
                400, "validation_error",
                f"body.properties.Job.reference.job_id should be a non-empty "
                f"string, instead was {_shape(job_id)}.",
            )

        note_text = None
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
                    f"body.properties.Note.rich_text should be an array, instead "
                    f"was {_shape(rich)}.",
                )
            for i, item in enumerate(rich):
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("text"), dict)
                    or not isinstance(item["text"].get("content"), str)
                ):
                    return _error(
                        400, "validation_error",
                        f"body.properties.Note.rich_text[{i}].text.content should "
                        f"be a string, instead was 'undefined'.",
                    )
            note_text = "".join(item["text"]["content"] for item in rich)

        # --- Business validation ---
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT tech_id FROM technicians WHERE tech_id=?",
                  (technician_id,))
        if c.fetchone() is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find technician route with ID: {technician_id}.",
            )
        c.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,))
        row = c.fetchone()
        if row is None:
            conn.close()
            return _error(
                404, "object_not_found",
                f"Could not find job with ID: {job_id}.",
            )
        if row[0] != "pending":
            conn.close()
            return _error(
                400, "validation_error",
                f"Job '{job_id}' is not pending (status='{row[0]}').",
            )
        c.execute("SELECT technician_id FROM dispatch_assignments WHERE job_id=?",
                  (job_id,))
        existing = c.fetchone()
        if existing is not None:
            conn.close()
            return _error(
                400, "validation_error",
                f"Job '{job_id}' already has a dispatch record "
                f"(technician '{existing[0]}').",
            )

        # --- Perform the write ---
        c.execute(
            "INSERT INTO dispatch_assignments (job_id, technician_id, note) "
            "VALUES (?,?,?)",
            (job_id, technician_id, note_text),
        )
        conn.commit()
        conn.close()

        # Success response: deep echo, shape entirely different from errors.
        return {
            "object": "dispatch_record",
            "id": "dsp_" + hashlib.md5(
                f"{job_id}:{technician_id}".encode()).hexdigest()[:10],
            "parent": {"type": "technician_route",
                       "technician_id": technician_id},
            "properties": {
                "Job": {"type": "reference", "reference": {"job_id": job_id}},
                "Status": {"type": "select", "select": {"name": "committed"}},
            },
            "created": True,
        }

    # ======================== HELPERS ========================

    @staticmethod
    def _time_to_min(t: str) -> int:
        h, m = map(int, t.split(":"))
        return h * 60 + m

    @staticmethod
    def _min_to_time(m: int) -> str:
        return f"{m // 60:02d}:{m % 60:02d}"

    def _load_reference_data(self):
        """Load all reference data needed for evaluation."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        techs = {r["tech_id"]: dict(r)
                 for r in conn.execute("SELECT * FROM technicians").fetchall()}
        jobs = {r["job_id"]: dict(r)
                for r in conn.execute(
                    "SELECT * FROM jobs WHERE status='pending'"
                ).fetchall()}

        van_parts = {}
        for r in conn.execute("SELECT * FROM parts_inventory").fetchall():
            van_parts.setdefault(r["van_id"], {})[r["part_id"]] = r["quantity"]

        job_reqs = {}
        for r in conn.execute("SELECT * FROM job_parts").fetchall():
            job_reqs.setdefault(r["job_id"], {})[r["part_id"]] = r["quantity_needed"]

        traffic = {}
        for r in conn.execute("SELECT * FROM traffic_conditions").fetchall():
            traffic[(r["from_zone"], r["to_zone"])] = dict(r)

        conn.close()

        with open(os.path.join(self.workspace, "scheduling_rules.json")) as f:
            sched_rules = json.load(f)
        with open(os.path.join(self.workspace, "part_substitutions.json")) as f:
            substitutions = json.load(f)

        zone_adj = {}
        adj_path = os.path.join(self.workspace, "travel_adjustments.csv")
        with open(adj_path) as f:
            for row in csv.DictReader(f):
                zone_adj[row["zone"]] = float(row["multiplier"])

        site_access = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("site_details_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for rec in json.load(f):
                        site_access[rec["job_id"]] = rec

        tech_zones = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("gps_tracking_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        tech_zones[row["tech_id"]] = row["current_zone"]

        return {
            "techs": techs, "jobs": jobs, "van_parts": van_parts,
            "job_reqs": job_reqs, "traffic": traffic, "sched_rules": sched_rules,
            "substitutions": substitutions, "zone_adj": zone_adj,
            "site_access": site_access, "tech_zones": tech_zones,
        }

    def _compute_travel(self, fz, tz, traffic, sched_rules, zone_adj):
        if fz == tz:
            return float(sched_rules.get("same_zone_travel_minutes", 5))
        key = (fz, tz)
        if key not in traffic:
            return 999.0
        seg = traffic[key]
        road_mult = sched_rules["road_condition_multipliers"].get(
            seg["road_condition"], 1.0
        )
        za = zone_adj.get(tz, 1.0)
        return round(
            seg["base_travel_min"] * seg["congestion_factor"] * road_mult * za, 1
        )

    @staticmethod
    def _has_parts(available, required, substitutions):
        for pid, qty in required.items():
            if available.get(pid, 0) >= qty:
                continue
            found = False
            for sub in substitutions.get(pid, []):
                if available.get(sub, 0) >= qty:
                    found = True
                    break
            if not found:
                return False
        return True

    @staticmethod
    def _deduct_parts(available, required, substitutions):
        used = dict(available)
        for pid, qty in required.items():
            if used.get(pid, 0) >= qty:
                used[pid] -= qty
            else:
                for sub in substitutions.get(pid, []):
                    if used.get(sub, 0) >= qty:
                        used[sub] -= qty
                        break
        return used

    # ======================== STEP ========================

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
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
        ref = self._load_reference_data()
        techs = ref["techs"]
        jobs = ref["jobs"]
        van_parts = ref["van_parts"]
        job_reqs = ref["job_reqs"]
        traffic = ref["traffic"]
        sched_rules = ref["sched_rules"]
        substitutions = ref["substitutions"]
        zone_adj = ref["zone_adj"]
        site_access = ref["site_access"]
        tech_zones = ref["tech_zones"]

        results = {}

        # ---------- Criterion 1: route_file_format (10 pts) ----------
        route_path = os.path.join(self.workspace, "route_plan.csv")
        required_cols = {
            "technician_id", "stop_number", "job_id",
            "estimated_arrival", "estimated_completion", "travel_minutes",
        }
        route_data = []
        file_ok = False
        if os.path.exists(route_path):
            with open(route_path) as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and required_cols.issubset(set(reader.fieldnames)):
                    file_ok = True
                    for row in reader:
                        route_data.append(row)

        results["route_file_format"] = {
            "passed": file_ok, "score": 10 if file_ok else 0, "max_score": 10,
        }
        if not file_ok:
            results["route_file_format"]["reason"] = (
                "File missing or required columns not found"
            )
            # Cannot evaluate further
            for name, ms in [
                ("job_coverage", 20), ("unique_assignment", 10),
                ("skill_compliance", 15), ("parts_compliance", 15),
                ("time_compliance", 15), ("priority_ordering", 15),
                ("db_assignments_recorded", 10), ("summary_text", 10),
            ]:
                results[name] = {
                    "passed": False, "score": 0, "max_score": ms,
                    "reason": "Route file not valid",
                }
            ts = sum(r["score"] for r in results.values())
            ms = sum(r["max_score"] for r in results.values())
            return ts / ms, {"eval_criteria": results,
                             "total_score": ts, "max_score": ms}

        # Parse assignments
        assignments = []
        for row in route_data:
            try:
                assignments.append({
                    "technician_id": row["technician_id"].strip(),
                    "stop_number": int(row["stop_number"]),
                    "job_id": row["job_id"].strip(),
                    "estimated_arrival": row["estimated_arrival"].strip(),
                    "estimated_completion": row["estimated_completion"].strip(),
                    "travel_minutes": float(row["travel_minutes"]),
                })
            except (ValueError, KeyError):
                continue

        assigned_jobs = set(a["job_id"] for a in assignments)

        # ---------- Criterion 2: job_coverage (20 pts) ----------
        total_w, assigned_w = 0, 0
        tier_w = {"P1": 4, "P2": 3, "P3": 2, "P4": 1}
        for jid, j in jobs.items():
            w = tier_w.get(j["priority_tier"], 1)
            total_w += w
            if jid in assigned_jobs:
                assigned_w += w
        cov_frac = assigned_w / total_w if total_w else 0
        c2 = round(cov_frac * 20)
        results["job_coverage"] = {
            "passed": cov_frac >= 0.95, "score": c2, "max_score": 20,
        }
        if cov_frac < 0.95:
            results["job_coverage"]["reason"] = (
                f"Weighted coverage {cov_frac:.1%}"
            )

        # ---------- Criterion 3: unique_assignment (10 pts) ----------
        jcounts = {}
        for a in assignments:
            jcounts[a["job_id"]] = jcounts.get(a["job_id"], 0) + 1
        dups = [j for j, c in jcounts.items() if c > 1]
        c3_ok = len(dups) == 0
        results["unique_assignment"] = {
            "passed": c3_ok, "score": 10 if c3_ok else 0, "max_score": 10,
        }
        if not c3_ok:
            results["unique_assignment"]["reason"] = (
                f"{len(dups)} job(s) assigned multiple times"
            )

        # ---------- Criterion 4: skill_compliance (15 pts) ----------
        sk_ok = sk_tot = 0
        for a in assignments:
            jid, tid = a["job_id"], a["technician_id"]
            if jid in jobs and tid in techs:
                sk_tot += 1
                if techs[tid]["skill_level"] >= jobs[jid]["required_skill_level"]:
                    sk_ok += 1
        sk_frac = sk_ok / sk_tot if sk_tot else 1
        c4 = round(sk_frac * 15)
        results["skill_compliance"] = {
            "passed": sk_frac >= 0.95, "score": c4, "max_score": 15,
        }
        if sk_frac < 0.95:
            results["skill_compliance"]["reason"] = (
                f"{sk_tot - sk_ok} assignment(s) violate skill requirement"
            )

        # ---------- Criterion 5: parts_compliance (15 pts) ----------
        # Sequential check within each tech's route
        tech_routes = {}
        for a in assignments:
            tech_routes.setdefault(a["technician_id"], []).append(a)

        pt_ok = pt_tot = 0
        for tid, route in tech_routes.items():
            if tid not in techs:
                continue
            van_id = techs[tid]["van_id"]
            remaining = dict(van_parts.get(van_id, {}))
            route.sort(key=lambda x: x["stop_number"])
            for a in route:
                jid = a["job_id"]
                if jid not in jobs:
                    continue
                reqs = job_reqs.get(jid, {})
                pt_tot += 1
                if self._has_parts(remaining, reqs, substitutions):
                    pt_ok += 1
                    remaining = self._deduct_parts(remaining, reqs, substitutions)
        pt_frac = pt_ok / pt_tot if pt_tot else 1
        c5 = round(pt_frac * 15)
        results["parts_compliance"] = {
            "passed": pt_frac >= 0.95, "score": c5, "max_score": 15,
        }
        if pt_frac < 0.95:
            results["parts_compliance"]["reason"] = (
                f"{pt_tot - pt_ok} assignment(s) lack required parts"
            )

        # ---------- Criterion 6: time_compliance (15 pts) ----------
        tm_ok = tm_tot = 0
        for a in assignments:
            jid = a["job_id"]
            if jid not in jobs:
                continue
            j = jobs[jid]
            try:
                arr = self._time_to_min(a["estimated_arrival"])
            except Exception:
                continue
            ws = self._time_to_min(j["window_start"])
            we = self._time_to_min(j["window_end"])
            sa = site_access.get(jid)
            if sa:
                acc_s = self._time_to_min(sa["access_start"])
                acc_e = self._time_to_min(sa["access_end"])
            else:
                acc_s, acc_e = 0, 24 * 60
            eff_s = max(ws, acc_s)
            eff_e = min(we, acc_e)
            tm_tot += 1
            if eff_s <= arr <= eff_e:
                tm_ok += 1
        tm_frac = tm_ok / tm_tot if tm_tot else 1
        c6 = round(tm_frac * 15)
        results["time_compliance"] = {
            "passed": tm_frac >= 0.95, "score": c6, "max_score": 15,
        }
        if tm_frac < 0.95:
            results["time_compliance"]["reason"] = (
                f"{tm_tot - tm_ok} arrival(s) outside effective window"
            )

        # ---------- Criterion 7: priority_ordering (15 pts) ----------
        tier_ord = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
        ord_ok = ord_tot = 0
        for tid, route in tech_routes.items():
            route.sort(key=lambda x: x["stop_number"])
            for i in range(len(route) - 1):
                j1, j2 = route[i]["job_id"], route[i + 1]["job_id"]
                if j1 in jobs and j2 in jobs:
                    ord_tot += 1
                    t1 = tier_ord.get(jobs[j1]["priority_tier"], 5)
                    t2 = tier_ord.get(jobs[j2]["priority_tier"], 5)
                    if t1 < t2:
                        ord_ok += 1
                    elif t1 == t2:
                        we1 = self._time_to_min(jobs[j1]["window_end"])
                        we2 = self._time_to_min(jobs[j2]["window_end"])
                        if we1 <= we2:
                            ord_ok += 1
        ord_frac = ord_ok / ord_tot if ord_tot else 1.0
        c7 = round(ord_frac * 15)
        results["priority_ordering"] = {
            "passed": ord_frac >= 0.95, "score": c7, "max_score": 15,
        }
        if ord_frac < 0.95:
            results["priority_ordering"]["reason"] = (
                f"{ord_tot - ord_ok} priority ordering violation(s)"
            )

        # ---------- Criterion 8: db_assignments_recorded (10 pts) ----------
        # Each assignment in route_plan.csv must also be committed via the
        # dispatch-record write API (dispatch_assignments table).
        conn = sqlite3.connect(self.db_path)
        try:
            db_recs = {
                r[0]: r[1] for r in conn.execute(
                    "SELECT job_id, technician_id FROM dispatch_assignments"
                ).fetchall()
            }
        except sqlite3.OperationalError:
            db_recs = {}
        conn.close()

        rec_tot = rec_ok = 0
        for a in assignments:
            if a["job_id"] not in jobs:
                continue
            rec_tot += 1
            if db_recs.get(a["job_id"]) == a["technician_id"]:
                rec_ok += 1
        rec_frac = rec_ok / rec_tot if rec_tot else 0.0
        c8 = round(rec_frac * 10)
        results["db_assignments_recorded"] = {
            "passed": rec_frac >= 0.95, "score": c8, "max_score": 10,
        }
        if rec_frac < 0.95:
            results["db_assignments_recorded"]["reason"] = (
                f"{rec_tot - rec_ok} assignment(s) missing a matching "
                f"dispatch record"
            )

        # ---------- Criterion 9: summary_text (10 pts) ----------
        # The agent's response must contain the two exact summary lines described
        # in the task specification.
        plan_total_travel = round(sum(a["travel_minutes"] for a in assignments), 1)
        plan_assigned_count = len(assigned_jobs & set(jobs.keys()))
        plan_total_pending = len(jobs)

        travel_pat = re.compile(
            r"Total Travel Time:\s+([\d.]+)\s+minutes"
        )
        sched_pat = re.compile(
            r"Jobs Scheduled:\s+(\d+)\s+out of\s+(\d+)"
        )
        tm = travel_pat.search(action)
        sm = sched_pat.search(action)

        travel_line_ok = (
            tm is not None
            and round(float(tm.group(1)), 1) == plan_total_travel
        )
        sched_line_ok = (
            sm is not None
            and int(sm.group(1)) == plan_assigned_count
            and int(sm.group(2)) == plan_total_pending
        )
        st_ok = travel_line_ok and sched_line_ok
        results["summary_text"] = {
            "passed": st_ok,
            "score": 10 if st_ok else 0,
            "max_score": 10,
        }
        if not st_ok:
            if not travel_line_ok:
                results["summary_text"]["reason"] = (
                    "Missing or incorrect 'Total Travel Time' summary line"
                )
            else:
                results["summary_text"]["reason"] = (
                    "Missing or incorrect 'Jobs Scheduled' summary line"
                )

        total_score = sum(r["score"] for r in results.values())
        max_score = sum(r["max_score"] for r in results.values())
        return total_score / max_score, {
            "eval_criteria": results,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ======================== VERIFY ========================

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

        # ---- 1. Read workspace files ----
        tech_gps = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("gps_tracking_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        tech_gps[row["tech_id"]] = {
                            "latitude": float(row["latitude"]),
                            "longitude": float(row["longitude"]),
                            "current_zone": row["current_zone"],
                        }

        site_access = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("site_details_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for rec in json.load(f):
                        site_access[rec["job_id"]] = rec

        with open(os.path.join(self.workspace, "priority_config.yaml")) as f:
            _priority_config = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "scheduling_rules.json")) as f:
            sched_rules = json.load(f)

        with open(os.path.join(self.workspace, "part_substitutions.json")) as f:
            substitutions = json.load(f)

        zone_adj = {}
        with open(os.path.join(self.workspace, "travel_adjustments.csv")) as f:
            for row in csv.DictReader(f):
                zone_adj[row["zone"]] = float(row["multiplier"])

        # ---- 2. Gather data via tools ----
        all_techs = []
        page = 1
        while True:
            res = self.tools["list_technicians"](page=page, page_size=10)
            all_techs.extend(res["technicians"])
            if len(res["technicians"]) < 10 or page * 10 >= res["total"]:
                break
            page += 1

        all_jobs = []
        page = 1
        while True:
            res = self.tools["list_jobs"](
                filter=json.dumps({"status": "pending"}),
                page=page, page_size=10,
            )
            all_jobs.extend(res["jobs"])
            if len(res["jobs"]) < 10 or page * 10 >= res["total"]:
                break
            page += 1

        # Van inventories
        tech_parts = {}
        for t in all_techs:
            inv = self.tools["get_van_inventory"](van_id=t["van_id"])
            tech_parts[t["tech_id"]] = {
                p["part_id"]: p["quantity"] for p in inv["parts"]
            }

        # Job required parts
        j_reqs = {}
        for j in all_jobs:
            rp = self.tools["get_job_required_parts"](job_id=j["job_id"])
            j_reqs[j["job_id"]] = {
                p["part_id"]: p["quantity_needed"] for p in rp["parts"]
            }

        # Also call list_zones to add tool calls
        _zones_result = self.tools["list_zones"]()

        # ---- 3. Travel time helper (via tools, cached) ----
        travel_cache = {}

        def get_travel(fz, tz):
            key = (fz, tz)
            if key not in travel_cache:
                res = self.tools["get_travel_info"](from_zone=fz, to_zone=tz)
                if res.get("object") == "error":
                    travel_cache[key] = 999.0
                else:
                    road_mult = sched_rules["road_condition_multipliers"].get(
                        res["road_condition"], 1.0
                    )
                    za = zone_adj.get(tz, 1.0)
                    travel_cache[key] = round(
                        res["base_travel_min"] * res["congestion_factor"]
                        * road_mult * za,
                        1,
                    )
            return travel_cache[key]

        max_jobs = sched_rules.get("max_jobs_per_technician", 6)

        # ---- 4. Greedy scheduling ----
        tier_ord = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
        sorted_jobs = sorted(
            all_jobs,
            key=lambda j: (tier_ord.get(j["priority_tier"], 5), j["window_end"]),
        )

        # Initialize technician state
        tech_state = {}
        for t in all_techs:
            tid = t["tech_id"]
            gps = tech_gps.get(tid)
            czone = gps["current_zone"] if gps else t["home_zone"]
            tech_state[tid] = {
                "current_zone": czone,
                "current_time": self._time_to_min(t["shift_start"]),
                "shift_end": self._time_to_min(t["shift_end"]),
                "skill_level": t["skill_level"],
                "van_id": t["van_id"],
                "available_parts": dict(tech_parts.get(tid, {})),
                "route": [],
            }

        assigned_set = set()
        for job in sorted_jobs:
            jid = job["job_id"]
            j_zone = job["zone"]
            j_dur = job["estimated_duration_min"]
            j_skill = job["required_skill_level"]
            j_ws = self._time_to_min(job["window_start"])
            j_we = self._time_to_min(job["window_end"])

            sa = site_access.get(jid)
            if sa:
                acc_s = self._time_to_min(sa["access_start"])
                acc_e = self._time_to_min(sa["access_end"])
            else:
                acc_s, acc_e = 0, 24 * 60

            eff_s = max(j_ws, acc_s)
            eff_e = min(j_we, acc_e)
            if eff_e - eff_s < j_dur:
                continue  # infeasible

            best_tech = None
            best_travel = float("inf")
            best_arrival = 0

            for tid, st in tech_state.items():
                if st["skill_level"] < j_skill:
                    continue
                if len(st["route"]) >= max_jobs:
                    continue
                if not self._has_parts(
                    st["available_parts"], j_reqs.get(jid, {}), substitutions
                ):
                    continue

                travel = get_travel(st["current_zone"], j_zone)
                raw_arr = st["current_time"] + travel
                arrival = max(raw_arr, eff_s)
                completion = arrival + j_dur

                if arrival > eff_e:
                    continue
                if completion > st["shift_end"]:
                    continue

                if travel < best_travel or (
                    travel == best_travel and
                    (best_tech is None or tid < best_tech)
                ):
                    best_travel = travel
                    best_tech = tid
                    best_arrival = arrival

            if best_tech is not None:
                st = tech_state[best_tech]
                completion = best_arrival + j_dur
                st["route"].append({
                    "job_id": jid,
                    "stop_number": len(st["route"]) + 1,
                    "estimated_arrival": self._min_to_time(int(best_arrival)),
                    "estimated_completion": self._min_to_time(int(completion)),
                    "travel_minutes": round(best_travel, 1),
                })
                st["current_zone"] = j_zone
                st["current_time"] = completion
                st["available_parts"] = self._deduct_parts(
                    st["available_parts"], j_reqs.get(jid, {}), substitutions
                )
                assigned_set.add(jid)

        # ---- 5. Write route_plan.csv ----
        route_rows = []
        for tid, st in sorted(tech_state.items()):
            for stop in st["route"]:
                route_rows.append({
                    "technician_id": tid,
                    "stop_number": stop["stop_number"],
                    "job_id": stop["job_id"],
                    "estimated_arrival": stop["estimated_arrival"],
                    "estimated_completion": stop["estimated_completion"],
                    "travel_minutes": stop["travel_minutes"],
                })

        route_path = os.path.join(self.workspace, "route_plan.csv")
        with open(route_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "technician_id", "stop_number", "job_id",
                "estimated_arrival", "estimated_completion", "travel_minutes",
            ])
            writer.writeheader()
            writer.writerows(route_rows)

        # ---- 5b. Commit each assignment via the dispatch-record write API ----
        for row in route_rows:
            resp = self.tools["create_dispatch_record"](payload={
                "parent": {
                    "type": "technician_route",
                    "technician_id": row["technician_id"],
                },
                "properties": {
                    "Job": {
                        "type": "reference",
                        "reference": {"job_id": row["job_id"]},
                    },
                    "Note": {
                        "type": "rich_text",
                        "rich_text": [{
                            "type": "text",
                            "text": {"content": f"Stop {row['stop_number']}, "
                                                f"ETA {row['estimated_arrival']}"},
                        }],
                    },
                },
            })
            assert resp.get("created") is True, f"dispatch commit failed: {resp}"

        # ---- 6. Build action string ----
        total_travel = round(sum(r["travel_minutes"] for r in route_rows), 1)
        num_scheduled = len(assigned_set)
        num_total = len(all_jobs)

        action_lines = [
            f"Total Travel Time: {total_travel} minutes",
            f"Jobs Scheduled: {num_scheduled} out of {num_total}",
        ]
        unassigned = sorted(
            j["job_id"] for j in all_jobs if j["job_id"] not in assigned_set
        )
        if unassigned:
            action_lines.append(f"Unassigned Jobs: {', '.join(unassigned)}")
        action = "\n".join(action_lines)

        return self.step(action)
