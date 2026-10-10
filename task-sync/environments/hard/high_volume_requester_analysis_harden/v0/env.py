"""
High Volume Requester Analysis - Environment (hardened tool surface)

Hardened surface (M5 + M2):
  - export_request_activity returns the entire joined request-activity
    dataset in one JSON-string response with NO pagination. At larger data
    scales this single response is far bigger than a model's context budget;
    it is only safe to consume inside a programmatic sandbox that filters
    before printing. Paginated / per-entity tools remain available.
  - The remaining tools return a mix of shapes: native dicts, JSON-encoded
    strings, MCP-style envelopes, plain key:value text, and Python-repr
    strings. Error responses use a different object shape than successes,
    and tools never raise.
Task semantics, data, and scoring are unchanged from the base environment.
"""

import ast
import hashlib
import sqlite3
import os
import json
import csv
import yaml
import math
from typing import Tuple, Dict, List, Any


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
        }
        return func
    return decorator


# --- Hardened tool-surface helpers ---

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


def _check_int(value, name):
    """Return an _error dict if value is not a plain integer, else None."""
    if value is None or isinstance(value, bool) or not isinstance(value, int):
        return _error(400, "validation_error",
                      f"body.{name} should be an integer, instead was {_shape(value)}.")
    return None


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

    def _requestor_exists(self, requestor_id: int) -> bool:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT 1 FROM requestors WHERE id = ?", (requestor_id,))
        found = c.fetchone() is not None
        conn.close()
        return found

    # ── tool methods ────────────────────────────────────────────────────────

    @tool(
        description=(
            "Search requestors with optional filters. Returns paginated results "
            "with basic info (id, name, email, organization, requestor_type). "
            "Maximum page_size is 25."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                    "default": 1
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 25)",
                    "default": 25
                },
                "name_query": {
                    "type": "string",
                    "description": "Substring filter on requestor name (case-insensitive)",
                    "default": ""
                },
                "requestor_type": {
                    "type": "string",
                    "description": "Filter by type: individual, organization, government, media",
                    "default": ""
                },
                "organization_query": {
                    "type": "string",
                    "description": "Substring filter on organization name (case-insensitive)",
                    "default": ""
                }
            },
            "required": []
        }
    )
    def search_requestors(self, page: Any = 1, page_size: Any = 25,
                          name_query: str = "", requestor_type: str = "",
                          organization_query: str = ""):
        # M2: native dict return
        err = _check_int(page, "page") or _check_int(page_size, "page_size")
        if err:
            return err
        page_size = min(page_size, 25)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        query = "SELECT id, name, email, organization, requestor_type FROM requestors WHERE 1=1"
        params = []
        if name_query:
            query += " AND LOWER(name) LIKE ?"
            params.append(f"%{str(name_query).lower()}%")
        if requestor_type:
            query += " AND requestor_type = ?"
            params.append(requestor_type)
        if organization_query:
            query += " AND LOWER(organization) LIKE ?"
            params.append(f"%{str(organization_query).lower()}%")
        query += " ORDER BY id"

        c.execute(query, params)
        all_rows = c.fetchall()
        total = len(all_rows)
        total_pages = max(1, math.ceil(total / page_size))
        start = (page - 1) * page_size
        page_rows = all_rows[start:start + page_size]
        conn.close()

        return {
            "page": page,
            "page_size": page_size,
            "total_results": total,
            "total_pages": total_pages,
            "results": [dict(r) for r in page_rows]
        }

    @tool(
        description=(
            "Get full details of a single requestor by ID, including address, "
            "phone, city, state, and all other fields."
        ),
        parameters={
            "type": "object",
            "properties": {
                "requestor_id": {
                    "type": "integer",
                    "description": "The requestor's unique ID"
                }
            },
            "required": ["requestor_id"]
        }
    )
    def get_requestor_details(self, requestor_id: Any = None):
        # M2: plain "key: value" text return (single flat record)
        err = _check_int(requestor_id, "requestor_id")
        if err:
            return err
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM requestors WHERE id = ?", (requestor_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find requestor with ID: {requestor_id}.")
        fields = dict(row)
        return "\n".join(f"{k}: {v}" for k, v in fields.items())

    @tool(
        description=(
            "Search public-records requests with optional filters. Returns "
            "paginated results including requestor_id, date_filed, subject, "
            "status, category_id, department_id. Maximum page_size is 50."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                    "default": 1
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 50)",
                    "default": 50
                },
                "requestor_id": {
                    "type": "integer",
                    "description": "Filter by requestor ID"
                },
                "department_id": {
                    "type": "integer",
                    "description": "Filter by department ID"
                },
                "category_id": {
                    "type": "integer",
                    "description": "Filter by category ID"
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: open, closed, pending, fulfilled"
                }
            },
            "required": []
        }
    )
    def search_requests(self, page: Any = 1, page_size: Any = 50,
                        requestor_id: Any = None, department_id: Any = None,
                        category_id: Any = None, status: str = None):
        # M2: native dict return
        err = _check_int(page, "page") or _check_int(page_size, "page_size")
        if err:
            return err
        for pname, pval in (("requestor_id", requestor_id),
                            ("department_id", department_id),
                            ("category_id", category_id)):
            if pval is not None:
                err = _check_int(pval, pname)
                if err:
                    return err
        page_size = min(page_size, 50)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        query = "SELECT * FROM requests WHERE 1=1"
        params = []
        if requestor_id is not None:
            query += " AND requestor_id = ?"
            params.append(requestor_id)
        if department_id is not None:
            query += " AND department_id = ?"
            params.append(department_id)
        if category_id is not None:
            query += " AND category_id = ?"
            params.append(category_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY id"

        c.execute(query, params)
        all_rows = c.fetchall()
        total = len(all_rows)
        total_pages = max(1, math.ceil(total / page_size))
        start = (page - 1) * page_size
        page_rows = all_rows[start:start + page_size]
        conn.close()

        return {
            "page": page,
            "page_size": page_size,
            "total_results": total,
            "total_pages": total_pages,
            "results": [dict(r) for r in page_rows]
        }

    @tool(
        description=(
            "Get full details of a single public-records request by its ID."
        ),
        parameters={
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "integer",
                    "description": "The request's unique ID"
                }
            },
            "required": ["request_id"]
        }
    )
    def get_request_details(self, request_id: Any = None):
        # M2: MCP-style envelope return
        err = _check_int(request_id, "request_id")
        if err:
            return err
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM requests WHERE id = ?", (request_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find request with ID: {request_id}.")
        return _envelope(dict(row))

    @tool(
        description=(
            "Get aggregate production statistics for a given requestor: "
            "total pages produced, total cost, total staff hours, and "
            "number of production records across all their requests."
        ),
        parameters={
            "type": "object",
            "properties": {
                "requestor_id": {
                    "type": "integer",
                    "description": "The requestor's unique ID"
                }
            },
            "required": ["requestor_id"]
        }
    )
    def get_requestor_production_summary(self, requestor_id: Any = None):
        # M2: Python-repr string return
        err = _check_int(requestor_id, "requestor_id")
        if err:
            return err
        if not self._requestor_exists(requestor_id):
            return _error(404, "object_not_found",
                          f"Could not find requestor with ID: {requestor_id}.")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            SELECT
                COUNT(dp.id) as production_count,
                COALESCE(SUM(dp.pages_produced), 0) as total_pages,
                COALESCE(SUM(dp.cost), 0) as total_cost,
                COALESCE(SUM(dp.staff_hours), 0) as total_staff_hours
            FROM document_productions dp
            JOIN requests r ON dp.request_id = r.id
            WHERE r.requestor_id = ?
        """, (requestor_id,))
        row = c.fetchone()
        conn.close()
        return repr({
            "requestor_id": requestor_id,
            "production_count": row[0],
            "total_pages": row[1],
            "total_cost": round(row[2], 2),
            "total_staff_hours": round(row[3], 1),
        })

    @tool(
        description=(
            "Get all fee waiver records for a given requestor. Returns each "
            "waiver's type, amounts, reason, approval status, and approver."
        ),
        parameters={
            "type": "object",
            "properties": {
                "requestor_id": {
                    "type": "integer",
                    "description": "The requestor's unique ID"
                }
            },
            "required": ["requestor_id"]
        }
    )
    def get_fee_waivers_by_requestor(self, requestor_id: Any = None):
        # M2: MCP-style envelope return
        err = _check_int(requestor_id, "requestor_id")
        if err:
            return err
        if not self._requestor_exists(requestor_id):
            return _error(404, "object_not_found",
                          f"Could not find requestor with ID: {requestor_id}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""
            SELECT * FROM fee_waivers
            WHERE requestor_id = ?
            ORDER BY id
        """, (requestor_id,))
        rows = c.fetchall()
        conn.close()
        return _envelope({
            "requestor_id": requestor_id,
            "total_waivers": len(rows),
            "waivers": [dict(r) for r in rows]
        })

    @tool(
        description="List all departments with their IDs and names.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    def get_departments(self):
        # M2: native list return
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM departments ORDER BY id")
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @tool(
        description="List all request categories with their IDs and names.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    def get_categories(self):
        # M2: JSON-encoded string return
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM categories ORDER BY id")
        rows = c.fetchall()
        conn.close()
        return json.dumps({"categories": [dict(r) for r in rows]},
                          ensure_ascii=False)

    @tool(
        description=(
            "Export the complete request-activity dataset in a single "
            "response: one record per filed public-records request, joined "
            "with the requesting party's name, email, organization, and "
            "requestor type. Covers every requestor and every request on "
            "file, including filing date, status, category, and department. "
            "No pagination required."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    def export_request_activity(self) -> str:
        # M5: unbounded bulk export, one JSON string, no pagination
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""
            SELECT r.id AS request_id, r.requestor_id,
                   q.name AS requestor_name, q.email, q.organization,
                   q.requestor_type,
                   r.date_filed, r.status,
                   r.category_id, r.department_id
            FROM requests r
            JOIN requestors q ON r.requestor_id = q.id
            ORDER BY r.id
        """)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps({"record_count": len(rows), "records": rows},
                          ensure_ascii=False)

    # ── step (evaluation) ───────────────────────────────────────────────────

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
        gt = self._compute_ground_truth()
        criteria = {}

        # ── C1: Report file exists and has correct columns (10 pts) ─────
        report_path = os.path.join(self.workspace, "flagged_requestors_report.csv")
        c1_pass = False
        c1_score = 0
        report_rows = []
        expected_cols = [
            "requestor_id", "requestor_name", "email", "organization",
            "num_requests", "risk_score", "flag_reasons",
            "total_pages_produced", "approved_fee_waivers",
            "departments_targeted"
        ]
        if os.path.isfile(report_path):
            try:
                with open(report_path, "r") as f:
                    reader = csv.DictReader(f)
                    report_rows = list(reader)
                    actual_cols = list(reader.fieldnames) if reader.fieldnames else []
                if actual_cols == expected_cols:
                    c1_pass = True
                    c1_score = 10
                else:
                    c1_score = 3  # file exists but wrong columns
            except Exception:
                c1_score = 0
        criteria["report_file_format"] = {
            "passed": c1_pass,
            "score": c1_score,
            "max_score": 10,
            "reason": "" if c1_pass else "Report missing or wrong column names/order"
        }

        # ── C2: Correct set of flagged requestor IDs (25 pts) ───────────
        gt_ids = set(gt["flagged_ids"])
        report_ids = set()
        for row in report_rows:
            try:
                report_ids.add(int(row.get("requestor_id", -1)))
            except (ValueError, TypeError):
                pass
        if gt_ids and report_ids:
            precision = len(gt_ids & report_ids) / len(report_ids) if report_ids else 0
            recall = len(gt_ids & report_ids) / len(gt_ids) if gt_ids else 0
            f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0
            c2_score = round(25 * f1)
        elif not gt_ids and not report_ids:
            c2_score = 25
            f1 = 1.0
        else:
            c2_score = 0
            f1 = 0
        c2_pass = (gt_ids == report_ids)
        criteria["flagged_requestor_ids"] = {
            "passed": c2_pass,
            "score": c2_score,
            "max_score": 25,
            "reason": "" if c2_pass else f"Expected IDs {sorted(gt_ids)}, got {sorted(report_ids)}"
        }

        # ── C3: Risk scores within tolerance (20 pts) ──────────────────
        c3_score = 0
        if report_rows and gt_ids:
            gt_scores = gt["risk_scores"]  # {id: score}
            matched = 0
            total_compared = 0
            for row in report_rows:
                try:
                    rid = int(row["requestor_id"])
                    reported_score = float(row["risk_score"])
                except (ValueError, KeyError, TypeError):
                    continue
                if rid in gt_scores:
                    total_compared += 1
                    if abs(reported_score - gt_scores[rid]) < 0.02:
                        matched += 1
            if total_compared > 0:
                c3_score = round(20 * matched / total_compared)
        c3_pass = (c3_score == 20)
        criteria["risk_scores_accuracy"] = {
            "passed": c3_pass,
            "score": c3_score,
            "max_score": 20,
            "reason": "" if c3_pass else "Some risk scores differ from ground truth"
        }

        # ── C4: Report sorted by risk_score descending (10 pts) ────────
        c4_pass = False
        c4_score = 0
        if len(report_rows) >= 2:
            try:
                scores_in_order = [float(r["risk_score"]) for r in report_rows]
                if scores_in_order == sorted(scores_in_order, reverse=True):
                    c4_pass = True
                    c4_score = 10
            except (ValueError, KeyError):
                pass
        elif len(report_rows) == 1:
            c4_pass = True
            c4_score = 10
        elif not gt_ids:
            c4_pass = True
            c4_score = 10
        criteria["report_sort_order"] = {
            "passed": c4_pass,
            "score": c4_score,
            "max_score": 10,
            "reason": "" if c4_pass else "Report not sorted by risk_score descending"
        }

        # ── C5: Commercial waiver language flags (15 pts) ──────────────
        gt_cwl = gt["commercial_waiver_language_ids"]
        report_cwl = set()
        for row in report_rows:
            reasons_str = row.get("flag_reasons", "")
            try:
                rid = int(row["requestor_id"])
            except (ValueError, KeyError, TypeError):
                continue
            if "commercial_waiver_language" in reasons_str:
                report_cwl.add(rid)
        if gt_cwl or report_cwl:
            if gt_cwl == report_cwl:
                c5_score = 15
                c5_pass = True
            else:
                overlap = len(gt_cwl & report_cwl)
                total_ref = max(len(gt_cwl), len(report_cwl))
                c5_score = round(15 * overlap / total_ref) if total_ref else 0
                c5_pass = False
        else:
            c5_score = 15
            c5_pass = True
        criteria["commercial_waiver_language"] = {
            "passed": c5_pass,
            "score": c5_score,
            "max_score": 15,
            "reason": "" if c5_pass else f"Expected CWL IDs {sorted(gt_cwl)}, got {sorted(report_cwl)}"
        }

        # ── C6: Action string summary (20 pts) ────────────────────────
        c6_score = 0
        # check that total flagged count is in the action
        expected_count_str = str(len(gt_ids))
        if expected_count_str in action and ("flagged" in action.lower() or "identified" in action.lower()):
            c6_score += 10
        # check that all flagged IDs are mentioned in action
        ids_found = 0
        for rid in gt_ids:
            if str(rid) in action:
                ids_found += 1
        if gt_ids:
            c6_score += round(10 * ids_found / len(gt_ids))
        else:
            c6_score += 10
        c6_pass = (c6_score == 20)
        criteria["action_summary"] = {
            "passed": c6_pass,
            "score": c6_score,
            "max_score": 20,
            "reason": "" if c6_pass else "Action missing flagged count or requestor IDs"
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score, info

    def _compute_ground_truth(self) -> dict:
        """Compute the full ground truth from DB + workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # load config
        with open(os.path.join(self.workspace, "thresholds.yaml"), "r") as f:
            thresholds = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "commercial_domains.json"), "r") as f:
            commercial_domains = set(json.load(f)["known_commercial_domains"])

        # department sensitivity
        dept_sens = {}
        with open(os.path.join(self.workspace, "department_sensitivity.csv"), "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dept_sens[int(row["department_id"])] = int(row["sensitivity_level"])

        # category risk scores
        cat_risk = {}
        with open(os.path.join(self.workspace, "category_risk_scores.json"), "r") as f:
            for entry in json.load(f):
                cat_risk[entry["category_id"]] = entry["risk_score"]

        # requestor profiles from workspace
        profiles = {}  # requestor_id -> {alternate_email, cross_agency_request_count, ...}
        for fname in os.listdir(self.workspace):
            if fname.startswith("requestor_profile_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        rid = int(row["requestor_id"])
                        profiles[rid] = {
                            "alternate_email": row["alternate_email"],
                            "affiliated_organization": row["affiliated_organization"],
                            "cross_agency_request_count": int(row["cross_agency_request_count"]),
                        }

        # production manifests from workspace
        prod_manifest = {}  # request_id -> avg_document_sensitivity
        for fname in os.listdir(self.workspace):
            if fname.startswith("production_manifest_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    for entry in json.load(f):
                        prod_manifest[entry["request_id"]] = entry["avg_document_sensitivity"]

        # get all requestors
        c.execute("SELECT * FROM requestors")
        requestors = {r["id"]: dict(r) for r in c.fetchall()}

        # get all requests grouped by requestor
        c.execute("SELECT * FROM requests")
        all_requests = [dict(r) for r in c.fetchall()]
        requests_by_requestor = {}
        for req in all_requests:
            requests_by_requestor.setdefault(req["requestor_id"], []).append(req)

        # get fee waivers by requestor
        c.execute("SELECT * FROM fee_waivers")
        all_waivers = [dict(r) for r in c.fetchall()]
        waivers_by_requestor = {}
        for w in all_waivers:
            waivers_by_requestor.setdefault(w["requestor_id"], []).append(w)

        # get productions by request
        c.execute("SELECT dp.*, r.requestor_id FROM document_productions dp JOIN requests r ON dp.request_id = r.id")
        all_prods = [dict(r) for r in c.fetchall()]
        prods_by_requestor = {}
        for p in all_prods:
            prods_by_requestor.setdefault(p["requestor_id"], []).append(p)

        conn.close()

        vol_threshold = thresholds["volume_threshold"]
        risk_threshold = thresholds["risk_score_threshold"]
        weights = thresholds["scoring_weights"]
        norms = thresholds["normalization"]

        commercial_keywords = ["commercial", "market analysis", "bulk data", "aggregation"]

        flagged = {}
        risk_scores = {}
        cwl_ids = set()  # commercial waiver language IDs

        for rid, requestor in requestors.items():
            reqs = requests_by_requestor.get(rid, [])
            num_requests = len(reqs)
            if num_requests < vol_threshold:
                continue

            # component 1: request volume
            vol_norm = min(num_requests / norms["volume_cap"], 1.0)

            # component 2: commercial domain match
            primary_email = requestor["email"]
            primary_domain = primary_email.split("@")[-1] if "@" in primary_email else ""
            alt_email = profiles.get(rid, {}).get("alternate_email", "")
            alt_domain = alt_email.split("@")[-1] if "@" in alt_email else ""
            comm_match = 1.0 if (primary_domain in commercial_domains or
                                  alt_domain in commercial_domains) else 0.0

            # component 3: fee waiver ratio
            waivers = waivers_by_requestor.get(rid, [])
            approved_waivers = [w for w in waivers if w["status"] == "approved"]
            fee_waiver_ratio = len(approved_waivers) / num_requests

            # component 4: department spread
            dept_ids = set(r["department_id"] for r in reqs)
            dept_spread = min(len(dept_ids) / norms["department_spread_cap"], 1.0)

            # component 5: document sensitivity (from workspace manifests)
            req_ids = set(r["id"] for r in reqs)
            sensitivities = [prod_manifest[reqid] for reqid in req_ids
                             if reqid in prod_manifest]
            if sensitivities:
                doc_sens_norm = (sum(sensitivities) / len(sensitivities)) / 5.0
            else:
                doc_sens_norm = 0.0

            # component 6: cross-agency history (from workspace profiles)
            cross_agency = profiles.get(rid, {}).get("cross_agency_request_count", 0)
            cross_agency_norm = min(cross_agency / norms["cross_agency_cap"], 1.0)

            # composite risk score
            risk_score = (
                weights["request_volume"] * vol_norm +
                weights["commercial_domain_match"] * comm_match +
                weights["fee_waiver_ratio"] * fee_waiver_ratio +
                weights["department_spread"] * dept_spread +
                weights["document_sensitivity"] * doc_sens_norm +
                weights["cross_agency_history"] * cross_agency_norm
            )
            risk_score = round(risk_score, 4)

            if risk_score >= risk_threshold:
                # build flag reasons
                reasons = []
                if comm_match > 0:
                    reasons.append("commercial_domain_match")
                if fee_waiver_ratio > 0.5:
                    reasons.append("high_fee_waiver_ratio")
                if len(dept_ids) >= norms["department_spread_cap"]:
                    reasons.append("wide_department_spread")
                if cross_agency >= norms["cross_agency_cap"]:
                    reasons.append("high_cross_agency_activity")

                # check commercial waiver language
                has_cwl = False
                for w in approved_waivers:
                    reason_text = (w.get("reason") or "").lower()
                    if any(kw in reason_text for kw in commercial_keywords):
                        has_cwl = True
                        break
                if has_cwl:
                    reasons.append("commercial_waiver_language")
                    cwl_ids.add(rid)

                total_pages = sum(p["pages_produced"]
                                  for p in prods_by_requestor.get(rid, []))

                flagged[rid] = {
                    "requestor_id": rid,
                    "requestor_name": requestor["name"],
                    "email": requestor["email"],
                    "organization": requestor["organization"],
                    "num_requests": num_requests,
                    "risk_score": risk_score,
                    "flag_reasons": "; ".join(sorted(reasons)),
                    "total_pages_produced": total_pages,
                    "approved_fee_waivers": len(approved_waivers),
                    "departments_targeted": len(dept_ids),
                }
                risk_scores[rid] = risk_score

        return {
            "flagged": flagged,
            "flagged_ids": set(flagged.keys()),
            "risk_scores": risk_scores,
            "commercial_waiver_language_ids": cwl_ids,
        }

    # ── verify ──────────────────────────────────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.

        Note: the hardened tool surface returns mixed shapes; this solver
        consumes the bulk export programmatically (filtering in memory rather
        than echoing it), and parses key:value text, MCP envelopes, and
        Python-repr strings from the per-entity tools.
        """
        # ── Step 1: Load workspace config files ────────────────────────────
        with open(os.path.join(self.workspace, "thresholds.yaml"), "r") as f:
            thresholds = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "commercial_domains.json"), "r") as f:
            commercial_domains = set(json.load(f)["known_commercial_domains"])

        dept_sens = {}
        with open(os.path.join(self.workspace, "department_sensitivity.csv"), "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dept_sens[int(row["department_id"])] = int(row["sensitivity_level"])

        cat_risk = {}
        with open(os.path.join(self.workspace, "category_risk_scores.json"), "r") as f:
            for entry in json.load(f):
                cat_risk[entry["category_id"]] = entry["risk_score"]

        # read fee waiver policy for commercial language keywords
        # (policy says: "commercial", "market analysis", "bulk data", "aggregation")
        commercial_keywords = ["commercial", "market analysis", "bulk data", "aggregation"]

        # load requestor profiles from workspace
        profiles = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("requestor_profile_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        rid = int(row["requestor_id"])
                        profiles[rid] = {
                            "alternate_email": row["alternate_email"],
                            "affiliated_organization": row["affiliated_organization"],
                            "cross_agency_request_count": int(row["cross_agency_request_count"]),
                        }

        # load production manifests from workspace
        prod_manifest = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("production_manifest_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    for entry in json.load(f):
                        prod_manifest[entry["request_id"]] = entry["avg_document_sensitivity"]

        vol_threshold = thresholds["volume_threshold"]
        risk_threshold = thresholds["risk_score_threshold"]
        weights = thresholds["scoring_weights"]
        norms = thresholds["normalization"]

        tool_calls = 0

        def _kv_parse(text):
            out = {}
            for line in text.splitlines():
                k, _, v = line.partition(": ")
                out[k] = v
            return out

        # ── Step 2: Pull the bulk request-activity export ONCE and group
        # in memory (this response is far too large to echo into context;
        # consume it programmatically) ──────────────────────────────────────
        raw = self.tools["export_request_activity"]()
        tool_calls += 1
        export = json.loads(raw)

        # group by requestor
        requests_by_requestor = {}
        for rec in export["records"]:
            requests_by_requestor.setdefault(rec["requestor_id"], []).append(rec)

        # reference lookups (native list / JSON-string returns)
        _ = self.tools["get_departments"]()
        tool_calls += 1
        _ = json.loads(self.tools["get_categories"]())
        tool_calls += 1

        # ── Step 3: Identify high-volume requestors ────────────────────────
        high_volume_ids = [rid for rid, reqs in requests_by_requestor.items()
                           if len(reqs) >= vol_threshold]

        # ── Step 4: Get details + fee waivers + production for each ────────
        flagged_records = []
        for rid in high_volume_ids:
            reqs = requests_by_requestor[rid]
            num_requests = len(reqs)

            # get requestor details (plain key:value text return)
            details_raw = self.tools["get_requestor_details"](requestor_id=rid)
            tool_calls += 1
            details = _kv_parse(details_raw)

            # get production summary (Python-repr string return)
            prod_raw = self.tools["get_requestor_production_summary"](requestor_id=rid)
            tool_calls += 1
            prod_summary = ast.literal_eval(prod_raw)

            # get fee waivers (MCP envelope return)
            waiver_env = self.tools["get_fee_waivers_by_requestor"](requestor_id=rid)
            tool_calls += 1
            waiver_data = json.loads(waiver_env["content"][0]["text"])

            # component 1: request volume
            vol_norm = min(num_requests / norms["volume_cap"], 1.0)

            # component 2: commercial domain match
            primary_email = details.get("email", "")
            primary_domain = primary_email.split("@")[-1] if "@" in primary_email else ""
            alt_email = profiles.get(rid, {}).get("alternate_email", "")
            alt_domain = alt_email.split("@")[-1] if "@" in alt_email else ""
            comm_match = 1.0 if (primary_domain in commercial_domains or
                                  alt_domain in commercial_domains) else 0.0

            # component 3: fee waiver ratio
            waivers = waiver_data.get("waivers", [])
            approved_waivers = [w for w in waivers if w["status"] == "approved"]
            fee_waiver_ratio = len(approved_waivers) / num_requests

            # component 4: department spread
            dept_ids = set(r["department_id"] for r in reqs)
            dept_spread = min(len(dept_ids) / norms["department_spread_cap"], 1.0)

            # component 5: document sensitivity from workspace manifests
            req_ids = set(r["request_id"] for r in reqs)
            sensitivities = [prod_manifest[reqid] for reqid in req_ids
                             if reqid in prod_manifest]
            if sensitivities:
                doc_sens_norm = (sum(sensitivities) / len(sensitivities)) / 5.0
            else:
                doc_sens_norm = 0.0

            # component 6: cross-agency history from workspace profiles
            cross_agency = profiles.get(rid, {}).get("cross_agency_request_count", 0)
            cross_agency_norm = min(cross_agency / norms["cross_agency_cap"], 1.0)

            # composite risk score
            risk_score = (
                weights["request_volume"] * vol_norm +
                weights["commercial_domain_match"] * comm_match +
                weights["fee_waiver_ratio"] * fee_waiver_ratio +
                weights["department_spread"] * dept_spread +
                weights["document_sensitivity"] * doc_sens_norm +
                weights["cross_agency_history"] * cross_agency_norm
            )
            risk_score = round(risk_score, 4)

            if risk_score >= risk_threshold:
                # build flag reasons
                reasons = []
                if comm_match > 0:
                    reasons.append("commercial_domain_match")
                if fee_waiver_ratio > 0.5:
                    reasons.append("high_fee_waiver_ratio")
                if len(dept_ids) >= norms["department_spread_cap"]:
                    reasons.append("wide_department_spread")
                if cross_agency >= norms["cross_agency_cap"]:
                    reasons.append("high_cross_agency_activity")

                # check commercial waiver language
                has_cwl = False
                for w in approved_waivers:
                    reason_text = (w.get("reason") or "").lower()
                    if any(kw in reason_text for kw in commercial_keywords):
                        has_cwl = True
                        break
                if has_cwl:
                    reasons.append("commercial_waiver_language")

                flagged_records.append({
                    "requestor_id": rid,
                    "requestor_name": details.get("name", ""),
                    "email": details.get("email", ""),
                    "organization": details.get("organization", ""),
                    "num_requests": num_requests,
                    "risk_score": risk_score,
                    "flag_reasons": "; ".join(sorted(reasons)),
                    "total_pages_produced": prod_summary["total_pages"],
                    "approved_fee_waivers": len(approved_waivers),
                    "departments_targeted": len(dept_ids),
                })

        # ── Step 5: Sort by risk_score descending and write report ─────────
        flagged_records.sort(key=lambda x: -x["risk_score"])

        report_path = os.path.join(self.workspace, "flagged_requestors_report.csv")
        fieldnames = [
            "requestor_id", "requestor_name", "email", "organization",
            "num_requests", "risk_score", "flag_reasons",
            "total_pages_produced", "approved_fee_waivers",
            "departments_targeted"
        ]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rec in flagged_records:
                writer.writerow(rec)

        # ── Step 6: Construct action string ────────────────────────────────
        id_list = ", ".join(str(r["requestor_id"]) for r in flagged_records)
        action = (
            f"Identified {len(flagged_records)} flagged requestors for potential "
            f"commercial data mining. Flagged requestor IDs (sorted by risk score "
            f"descending): {id_list}. The full report has been saved as "
            f"flagged_requestors_report.csv with columns: requestor_id, "
            f"requestor_name, email, organization, num_requests, risk_score, "
            f"flag_reasons, total_pages_produced, approved_fee_waivers, "
            f"departments_targeted."
        )

        print(f"verify() used {tool_calls} tool calls")
        return self.step(action)
