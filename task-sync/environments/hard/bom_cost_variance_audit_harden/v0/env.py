"""
Environment for BOM cost variance audit task.

Hardened tool surface (M0 + M1 + M3 + M5):
  - M1: get_approved_vendors and get_labor_routing take a single
    JSON-encoded string `filter` parameter with layered, one-at-a-time
    validation errors.
  - M3: list_products, get_bom, and get_material_info return deep-nested
    Notion-style records; the product list uses cursor pagination
    (has_more / next_cursor) instead of total/total_pages.
  - M5: export_bom_sourcing_matrix returns the full joined
    BOM/product/material/vendor dataset as ONE JSON string with no
    pagination — at larger scales this is far bigger than a model's
    context budget and is only safe to consume inside a programmatic
    sandbox that filters before printing.
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

    def _check_product_id(self, product_id):
        """Validate a product_id argument and confirm the product exists.
        Returns None on success, or an error dict."""
        if not isinstance(product_id, str) or product_id == "":
            return _error(
                400, "validation_error",
                f"body.product_id should be a non-empty string, instead was "
                f"{_shape(product_id)}.")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT 1 FROM finished_goods WHERE product_id = ?",
                  (product_id,))
        found = c.fetchone()
        conn.close()
        if found is None:
            return _error(
                404, "object_not_found",
                f"Could not find product with ID: {product_id}.")
        return None

    def _check_material_id(self, material_id):
        """Validate a material_id argument and confirm the material exists.
        Returns None on success, or an error dict."""
        if not isinstance(material_id, str) or material_id == "":
            return _error(
                400, "validation_error",
                f"body.material_id should be a non-empty string, instead was "
                f"{_shape(material_id)}.")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT 1 FROM raw_materials WHERE material_id = ?",
                  (material_id,))
        found = c.fetchone()
        conn.close()
        if found is None:
            return _error(
                404, "object_not_found",
                f"Could not find material with ID: {material_id}.")
        return None

    # ── Tool methods ────────────────────────────────────────────────────

    @tool(
        description=(
            "List all finished goods maintained in the standard cost system. "
            "Each result entry carries the product name and category. "
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
                    "description": "Number of products per page. Defaults to 10.",
                },
            },
            "required": [],
        },
    )
    def list_products(self, page: Any = 1, page_size: Any = 10) -> dict:
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
        c.execute("SELECT COUNT(*) FROM finished_goods")
        total = c.fetchone()[0]
        offset = (page - 1) * page_size
        c.execute(
            "SELECT product_id, product_name, category FROM finished_goods "
            "ORDER BY product_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        results = [
            {
                "object": "product",
                "id": r["product_id"],
                "properties": {
                    "Name": _title(r["product_name"]),
                    "Category": _select(r["category"]),
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
            "Get the bill of materials for a finished good. Each BOM line "
            "references the product it belongs to and the raw material it "
            "consumes, and carries the standard quantity and the standard "
            "unit price for that line."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product identifier, e.g. 'FG-0001'.",
                },
            },
            "required": ["product_id"],
        },
    )
    def get_bom(self, product_id: Any = None) -> dict:
        err = self._check_product_id(product_id)
        if err is not None:
            return err
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT bom_id, material_id, standard_qty, standard_unit_price "
            "FROM bom_items WHERE product_id = ? ORDER BY material_id",
            (product_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        results = [
            {
                "object": "bom_line",
                "id": f"BOMLINE-{r['bom_id']:05d}",
                "properties": {
                    "Product": _relation(product_id),
                    "Material": _relation(r["material_id"]),
                    "Standard Qty": _number(r["standard_qty"]),
                    "Standard Unit Price": _number(r["standard_unit_price"]),
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
            "Get the full record for a specific raw material, including its "
            "name, unit of measure, and standard price."
        ),
        parameters={
            "type": "object",
            "properties": {
                "material_id": {
                    "type": "string",
                    "description": "The material identifier, e.g. 'MAT-0001'.",
                },
            },
            "required": ["material_id"],
        },
    )
    def get_material_info(self, material_id: Any = None) -> dict:
        err = self._check_material_id(material_id)
        if err is not None:
            return err
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT material_id, material_name, unit, standard_price "
            "FROM raw_materials WHERE material_id = ?",
            (material_id,),
        )
        row = c.fetchone()
        conn.close()
        return {
            "object": "material",
            "id": row["material_id"],
            "properties": {
                "Name": _title(row["material_name"]),
                "Unit": _select(row["unit"]),
                "Standard Price": _number(row["standard_price"]),
            },
        }

    @tool(
        description=(
            "Returns the list of approved vendors for a given material. Each "
            "entry includes vendor_id, vendor_name, is_preferred (0 or 1), "
            "and status ('active' or 'inactive'). Filtering is expressed as "
            "a JSON-encoded string, e.g. filter='{\"status\": \"active\"}'. "
            "Supported filter properties: status ('active' | 'inactive') "
            "and preferred_only (boolean)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "material_id": {
                    "type": "string",
                    "description": "The material identifier, e.g. 'MAT-0001'.",
                },
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"status\": \"active\"}'. Pass '{}' or omit for "
                        "no filtering."
                    ),
                },
            },
            "required": ["material_id"],
        },
    )
    def get_approved_vendors(self, material_id: Any = None,
                             filter: Any = None) -> dict:
        err = self._check_material_id(material_id)
        if err is not None:
            return err
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"status", "preferred_only"}
        for key in parsed:
            if key not in supported:
                return _error(
                    400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: status, preferred_only.")

        clauses = ["material_id = ?"]
        params: list = [material_id]
        if "status" in parsed:
            st = parsed["status"]
            if not isinstance(st, str) or st not in ("active", "inactive"):
                return _error(
                    400, "validation_error",
                    f"body.filter.status should be one of \"active\", "
                    f"\"inactive\", instead was {_shape(st)}.")
            clauses.append("status = ?")
            params.append(st)
        if "preferred_only" in parsed:
            po = parsed["preferred_only"]
            if not isinstance(po, bool):
                return _error(
                    400, "validation_error",
                    f"body.filter.preferred_only should be a boolean, "
                    f"instead was {_shape(po)}.")
            if po:
                clauses.append("is_preferred = 1")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT vendor_id, vendor_name, is_preferred, status "
            "FROM approved_vendors "
            "WHERE " + " AND ".join(clauses) + " ORDER BY vendor_id",
            params,
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"material_id": material_id, "vendors": rows}

    @tool(
        description=(
            "Returns the labor routing for a finished good. Each routing "
            "line includes operation_name, standard_hours, and "
            "standard_labor_rate. Filtering is expressed as a JSON-encoded "
            "string, e.g. filter='{\"operation_name\": \"Welding\"}'. "
            "Supported filter properties: operation_name (string) and "
            "min_standard_hours (number)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product identifier, e.g. 'FG-0001'.",
                },
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"operation_name\": \"Assembly\"}'. Pass '{}' or "
                        "omit for no filtering."
                    ),
                },
            },
            "required": ["product_id"],
        },
    )
    def get_labor_routing(self, product_id: Any = None,
                          filter: Any = None) -> dict:
        err = self._check_product_id(product_id)
        if err is not None:
            return err
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"operation_name", "min_standard_hours"}
        for key in parsed:
            if key not in supported:
                return _error(
                    400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: operation_name, "
                    f"min_standard_hours.")

        clauses = ["product_id = ?"]
        params: list = [product_id]
        if "operation_name" in parsed:
            op = parsed["operation_name"]
            if not isinstance(op, str) or op == "":
                return _error(
                    400, "validation_error",
                    f"body.filter.operation_name should be a non-empty "
                    f"string, instead was {_shape(op)}.")
            clauses.append("operation_name = ?")
            params.append(op)
        if "min_standard_hours" in parsed:
            mh = parsed["min_standard_hours"]
            if not isinstance(mh, (int, float)) or isinstance(mh, bool):
                return _error(
                    400, "validation_error",
                    f"body.filter.min_standard_hours should be a number, "
                    f"instead was {_shape(mh)}.")
            clauses.append("standard_hours >= ?")
            params.append(mh)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT operation_name, standard_hours, standard_labor_rate "
            "FROM labor_routings "
            "WHERE " + " AND ".join(clauses) + " ORDER BY operation_name",
            params,
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"product_id": product_id, "routings": rows}

    @tool(
        description=(
            "Export the complete bill-of-materials sourcing matrix in a "
            "single response: every BOM line of every finished good, joined "
            "with the product it belongs to, the raw material it consumes "
            "(with standard quantity and standard unit price), and each "
            "approved vendor of that material together with its preferred "
            "flag and status. No pagination required."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def export_bom_sourcing_matrix(self) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            """
            SELECT b.product_id, f.product_name, b.material_id,
                   m.material_name, b.standard_qty, b.standard_unit_price,
                   v.vendor_id, v.vendor_name, v.is_preferred,
                   v.status AS vendor_status
            FROM bom_items b
            JOIN finished_goods f ON f.product_id = b.product_id
            JOIN raw_materials m ON m.material_id = b.material_id
            JOIN approved_vendors v ON v.material_id = b.material_id
            ORDER BY b.product_id, b.material_id, v.vendor_id
            """
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps({"record_count": len(rows), "records": rows},
                          ensure_ascii=False)

    # -------------------------------------------------------------- step
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
        criteria = {}

        # Load ground truth
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT product_id, product_name, standard_material_cost, actual_material_cost, "
            "material_variance, material_variance_pct, standard_labor_cost, actual_labor_cost, "
            "labor_variance, labor_variance_pct, yield_rate, yield_adjusted_total, "
            "total_standard_cost, total_variance, total_variance_pct, flag, revision_recommended "
            "FROM ground_truth ORDER BY product_id"
        )
        gt_rows = cur.fetchall()
        conn.close()

        gt = {}
        for r in gt_rows:
            gt[r[0]] = {
                "product_id": r[0],
                "product_name": r[1],
                "standard_material_cost": r[2],
                "actual_material_cost": r[3],
                "material_variance": r[4],
                "material_variance_pct": r[5],
                "standard_labor_cost": r[6],
                "actual_labor_cost": r[7],
                "labor_variance": r[8],
                "labor_variance_pct": r[9],
                "yield_rate": r[10],
                "yield_adjusted_total": r[11],
                "total_standard_cost": r[12],
                "total_variance": r[13],
                "total_variance_pct": r[14],
                "flag": r[15],
                "revision_recommended": r[16],
            }

        total_products = len(gt)

        # ---- Criterion 1: file exists, correct columns, correct sort order (15 pts) ----
        report_path = os.path.join(self.workspace, "variance_report.csv")
        expected_cols = [
            "product_id", "product_name",
            "standard_material_cost", "actual_material_cost",
            "material_variance", "material_variance_pct",
            "standard_labor_cost", "actual_labor_cost",
            "labor_variance", "labor_variance_pct",
            "yield_rate", "yield_adjusted_total",
            "total_standard_cost", "total_variance", "total_variance_pct",
            "flag", "revision_recommended",
        ]
        agent_data = {}
        ordered_abs_pcts = []
        file_ok = False
        cols_ok = False
        sort_ok = False
        if os.path.exists(report_path):
            try:
                with open(report_path, "r") as f:
                    reader = csv.DictReader(f)
                    actual_cols = [c.strip() for c in reader.fieldnames] if reader.fieldnames else []
                    cols_ok = all(c in actual_cols for c in expected_cols)
                    for row in reader:
                        row = {k.strip(): v.strip() for k, v in row.items()}
                        pid = row.get("product_id", "")
                        agent_data[pid] = row
                        try:
                            ordered_abs_pcts.append(abs(float(row.get("total_variance_pct", "0"))))
                        except (ValueError, TypeError):
                            pass
                file_ok = True
            except Exception:
                pass
        # Sort order: abs(total_variance_pct) must be non-increasing
        if len(ordered_abs_pcts) >= 2:
            sort_ok = all(
                ordered_abs_pcts[i] >= ordered_abs_pcts[i + 1]
                for i in range(len(ordered_abs_pcts) - 1)
            )
        elif len(ordered_abs_pcts) <= 1:
            sort_ok = True

        c1_score = 0
        if file_ok:
            c1_score += 5
        if cols_ok:
            c1_score += 5
        if sort_ok:
            c1_score += 5
        criteria["file_structure"] = {
            "passed": c1_score == 15,
            "score": c1_score,
            "max_score": 15,
            "reason": "" if c1_score == 15 else "File missing, columns incorrect, or rows not sorted by descending abs(total_variance_pct)",
        }

        # ---- Criterion 2: all products present (10 pts) ----
        present = sum(1 for pid in gt if pid in agent_data)
        c2_score = round(present / total_products * 10) if total_products else 0
        criteria["all_products_present"] = {
            "passed": c2_score == 10,
            "score": c2_score,
            "max_score": 10,
            "reason": "" if c2_score == 10 else f"{total_products - present} products missing",
        }

        # Helper for numeric comparison
        def _close(a, b, rel=0.01, abs_tol=1.0):
            try:
                a, b = float(a), float(b)
            except (ValueError, TypeError):
                return False
            if abs(b) < 1e-9:
                return abs(a) < abs_tol
            return abs(a - b) <= max(rel * abs(b), abs_tol)

        # ---- Criterion 3: material cost variances (20 pts) ----
        mat_ok = 0
        for pid, g in gt.items():
            if pid not in agent_data:
                continue
            a = agent_data[pid]
            if (
                _close(a.get("standard_material_cost", ""), g["standard_material_cost"])
                and _close(a.get("actual_material_cost", ""), g["actual_material_cost"])
                and _close(a.get("material_variance", ""), g["material_variance"])
                and _close(a.get("material_variance_pct", ""), g["material_variance_pct"], rel=0.02, abs_tol=0.5)
            ):
                mat_ok += 1
        c3_score = round(mat_ok / total_products * 20) if total_products else 0
        criteria["material_cost_accuracy"] = {
            "passed": c3_score == 20,
            "score": c3_score,
            "max_score": 20,
            "reason": "" if c3_score == 20 else f"{total_products - mat_ok} products have material cost errors",
        }

        # ---- Criterion 4: labor cost variances (20 pts) ----
        lab_ok = 0
        for pid, g in gt.items():
            if pid not in agent_data:
                continue
            a = agent_data[pid]
            if (
                _close(a.get("standard_labor_cost", ""), g["standard_labor_cost"])
                and _close(a.get("actual_labor_cost", ""), g["actual_labor_cost"])
                and _close(a.get("labor_variance", ""), g["labor_variance"])
                and _close(a.get("labor_variance_pct", ""), g["labor_variance_pct"], rel=0.02, abs_tol=0.5)
            ):
                lab_ok += 1
        c4_score = round(lab_ok / total_products * 20) if total_products else 0
        criteria["labor_cost_accuracy"] = {
            "passed": c4_score == 20,
            "score": c4_score,
            "max_score": 20,
            "reason": "" if c4_score == 20 else f"{total_products - lab_ok} products have labor cost errors",
        }

        # ---- Criterion 5: yield rates and adjusted totals (15 pts) ----
        yld_ok = 0
        for pid, g in gt.items():
            if pid not in agent_data:
                continue
            a = agent_data[pid]
            if (
                _close(a.get("yield_rate", ""), g["yield_rate"], rel=0.005, abs_tol=0.005)
                and _close(a.get("yield_adjusted_total", ""), g["yield_adjusted_total"])
                and _close(a.get("total_standard_cost", ""), g["total_standard_cost"])
                and _close(a.get("total_variance", ""), g["total_variance"])
                and _close(a.get("total_variance_pct", ""), g["total_variance_pct"], rel=0.02, abs_tol=0.5)
            ):
                yld_ok += 1
        c5_score = round(yld_ok / total_products * 15) if total_products else 0
        criteria["yield_and_totals"] = {
            "passed": c5_score == 15,
            "score": c5_score,
            "max_score": 15,
            "reason": "" if c5_score == 15 else f"{total_products - yld_ok} products have yield/total errors",
        }

        # ---- Criterion 6: flags and revision recommendations (10 pts) ----
        flag_ok = 0
        for pid, g in gt.items():
            if pid not in agent_data:
                continue
            a = agent_data[pid]
            if (
                a.get("flag", "").strip().upper() == g["flag"]
                and a.get("revision_recommended", "").strip().upper() == g["revision_recommended"]
            ):
                flag_ok += 1
        c6_score = round(flag_ok / total_products * 10) if total_products else 0
        criteria["flags_and_revision"] = {
            "passed": c6_score == 10,
            "score": c6_score,
            "max_score": 10,
            "reason": "" if c6_score == 10 else f"{total_products - flag_ok} products have flag/revision errors",
        }

        # ---- Criterion 7: action string lists revision products (10 pts) ----
        revision_pids = [pid for pid, g in gt.items() if g["revision_recommended"] == "YES"]
        mentioned = 0
        for pid in revision_pids:
            if pid in action:
                mentioned += 1
        if revision_pids:
            c7_score = round(mentioned / len(revision_pids) * 10)
        else:
            c7_score = 10  # no revisions needed, auto-pass
        criteria["action_revision_summary"] = {
            "passed": c7_score == 10,
            "score": c7_score,
            "max_score": 10,
            "reason": "" if c7_score == 10 else f"{len(revision_pids) - mentioned} revision products not mentioned in response",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score if max_score else 0.0, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # -------------------------------------------------------------- verify
    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.

        This method proves end-to-end solvability of the HARDENED surface:
          - Walks the M3 nested product/BOM/material records and follows
            cursor pagination.
          - Consumes the M5 bulk export once, in memory.
          - Builds M1 JSON-encoded string filters for vendor queries.
          - Uses self.tools[name](**params) only (no direct DB queries).
        """
        import glob as globmod

        tool_calls = 0

        # 1. List all products via M3 nested records + cursor pagination
        all_products = []
        page = 1
        while True:
            res = self.tools["list_products"](page=page, page_size=10)
            tool_calls += 1
            for rec in res["results"]:
                props = rec["properties"]
                all_products.append({
                    "product_id": rec["id"],
                    "product_name": props["Name"]["title"][0]["plain_text"],
                })
            if not res["has_more"]:
                break
            page = res["next_cursor"]

        # 2. Read cost thresholds
        with open(os.path.join(self.workspace, "cost_thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)

        # 3. Read costing methodology + revision policy (to confirm rules)
        with open(os.path.join(self.workspace, "costing_methodology.md")) as f:
            _ = f.read()
        with open(os.path.join(self.workspace, "revision_policy.txt")) as f:
            _ = f.read()

        # 4. Read all vendor quote JSON files
        vendor_price_map = {}  # vendor_id -> {material_id, quoted_price}
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "vendor_quotes_*.json"))):
            with open(fpath) as f:
                data = json.load(f)
            for q in data["quotes"]:
                vendor_price_map[q["vendor_id"]] = {
                    "material_id": q["material_id"],
                    "quoted_price": q["quoted_price"],
                }

        # 5. Read all material handling TXT files
        handling_map = {}  # material_id -> surcharge
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "material_specs_*.txt"))):
            with open(fpath) as f:
                content = f.read()
            # Parse material blocks
            blocks = content.split("---")
            for block in blocks:
                mid_m = re.search(r"Material ID:\s*(\S+)", block)
                hs_m = re.search(r"Handling Surcharge:\s*([\d.]+)", block)
                if mid_m and hs_m:
                    handling_map[mid_m.group(1)] = float(hs_m.group(1))

        # 6. Read all yield report CSV files
        yield_map = {}  # product_id -> [(planned, actual)]
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "yield_report_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pid = row["product_id"]
                    yield_map.setdefault(pid, []).append(
                        (int(row["planned_qty"]), int(row["actual_qty"]))
                    )

        # 7. Read all production summary MD files for actual hours
        actual_hours_map = {}  # (product_id, operation) -> actual_hours
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "production_summary_*.md"))):
            with open(fpath) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("|") and not line.startswith("|-") and "Product ID" not in line:
                        parts = [p.strip() for p in line.split("|")]
                        parts = [p for p in parts if p]
                        if len(parts) >= 4:
                            pid = parts[0]
                            op = parts[1]
                            try:
                                ah = float(parts[3])
                                actual_hours_map[(pid, op)] = ah
                            except ValueError:
                                pass

        # 7b. M5 bulk export, consumed ONCE in memory (never echoed).
        # Provides the full BOM/vendor join; used here to cross-check the
        # per-product BOM lines and each material's vendor roster.
        raw_export = self.tools["export_bom_sourcing_matrix"]()
        tool_calls += 1
        export_data = json.loads(raw_export)
        export_bom = {}      # (product_id, material_id) -> (qty, unit_price)
        export_vendors = {}  # material_id -> {vendor_id: (is_preferred, status)}
        for rec in export_data["records"]:
            export_bom[(rec["product_id"], rec["material_id"])] = (
                rec["standard_qty"], rec["standard_unit_price"])
            export_vendors.setdefault(rec["material_id"], {})[
                rec["vendor_id"]] = (rec["is_preferred"], rec["vendor_status"])
        assert export_data["record_count"] == len(export_data["records"])

        # 8. For each product, compute variances using tools + workspace
        active_vendor_cache = {}   # material_id -> list of active vendor dicts
        material_probe_done = False
        results = []
        for prod in all_products:
            pid = prod["product_id"]
            pname = prod["product_name"]

            # Get BOM (M3 nested list; material id sits at relation[0].id)
            bom_res = self.tools["get_bom"](product_id=pid)
            tool_calls += 1
            bom = [
                {
                    "material_id": line["properties"]["Material"]["relation"][0]["id"],
                    "standard_qty": line["properties"]["Standard Qty"]["number"],
                    "standard_unit_price":
                        line["properties"]["Standard Unit Price"]["number"],
                }
                for line in bom_res["results"]
            ]

            # Cross-check against the bulk export
            for b in bom:
                assert export_bom[(pid, b["material_id"])] == (
                    b["standard_qty"], b["standard_unit_price"])

            # Probe M3 material records once (first product's materials)
            if not material_probe_done:
                for b in bom:
                    mrec = self.tools["get_material_info"](
                        material_id=b["material_id"])
                    tool_calls += 1
                    assert mrec["properties"]["Name"]["title"][0]["plain_text"]
                    assert mrec["properties"]["Unit"]["select"]["name"]
                material_probe_done = True

            # Standard material cost
            std_mat = sum(b["standard_qty"] * b["standard_unit_price"] for b in bom)

            # Actual material cost
            act_mat = 0.0
            has_non_preferred = False
            for b in bom:
                mid = b["material_id"]
                # Get active approved vendors via M1 JSON-string filter
                if mid not in active_vendor_cache:
                    vres = self.tools["get_approved_vendors"](
                        material_id=mid,
                        filter=json.dumps({"status": "active"}))
                    tool_calls += 1
                    active_vendor_cache[mid] = vres["vendors"]
                    # Cross-check against the bulk export roster
                    for v in vres["vendors"]:
                        assert export_vendors[mid][v["vendor_id"]] == (
                            v["is_preferred"], "active")
                active = active_vendor_cache[mid]
                preferred = [v for v in active if v["is_preferred"] == 1]

                if preferred and preferred[0]["vendor_id"] in vendor_price_map:
                    act_price = vendor_price_map[preferred[0]["vendor_id"]]["quoted_price"]
                else:
                    has_non_preferred = True
                    prices = [
                        vendor_price_map[v["vendor_id"]]["quoted_price"]
                        for v in active
                        if v["vendor_id"] in vendor_price_map
                    ]
                    act_price = min(prices) if prices else 0.0

                handling = handling_map.get(mid, 0.0)
                act_mat += b["standard_qty"] * (act_price + handling)

            mat_var = act_mat - std_mat
            mat_var_pct = (mat_var / std_mat * 100) if std_mat else 0.0

            # Labor (M1 tool; omitting the filter returns all routing lines)
            lr_res = self.tools["get_labor_routing"](product_id=pid)
            tool_calls += 1
            routings = lr_res["routings"]
            std_lab = sum(r["standard_hours"] * r["standard_labor_rate"] for r in routings)

            act_lab = 0.0
            for r in routings:
                ah = actual_hours_map.get((pid, r["operation_name"]), r["standard_hours"])
                act_lab += ah * r["standard_labor_rate"]
            lab_var = act_lab - std_lab
            lab_var_pct = (lab_var / std_lab * 100) if std_lab else 0.0

            # Yield
            ylds = yield_map.get(pid, [])
            total_planned = sum(p for p, _ in ylds)
            total_actual = sum(a for _, a in ylds)
            yield_rate = total_actual / total_planned if total_planned > 0 else 1.0

            yield_adj = (act_mat + act_lab) / yield_rate if yield_rate > 0 else (act_mat + act_lab)
            total_std = std_mat + std_lab
            total_var = yield_adj - total_std
            total_var_pct = (total_var / total_std * 100) if total_std else 0.0

            flag = "YES" if abs(total_var_pct) > thresholds["total_variance_threshold"] else "NO"

            revision = "NO"
            if abs(total_var_pct) > thresholds["total_critical_threshold"]:
                revision = "YES"
            elif abs(mat_var_pct) > thresholds["material_critical_threshold"] and has_non_preferred:
                revision = "YES"
            elif yield_rate < thresholds["yield_loss_threshold"]:
                revision = "YES"

            results.append({
                "product_id": pid,
                "product_name": pname,
                "standard_material_cost": round(std_mat, 2),
                "actual_material_cost": round(act_mat, 2),
                "material_variance": round(mat_var, 2),
                "material_variance_pct": round(mat_var_pct, 2),
                "standard_labor_cost": round(std_lab, 2),
                "actual_labor_cost": round(act_lab, 2),
                "labor_variance": round(lab_var, 2),
                "labor_variance_pct": round(lab_var_pct, 2),
                "yield_rate": round(yield_rate, 4),
                "yield_adjusted_total": round(yield_adj, 2),
                "total_standard_cost": round(total_std, 2),
                "total_variance": round(total_var, 2),
                "total_variance_pct": round(total_var_pct, 2),
                "flag": flag,
                "revision_recommended": revision,
            })

        # Sort by absolute total_variance_pct descending
        results.sort(key=lambda x: abs(x["total_variance_pct"]), reverse=True)

        # 9. Write variance_report.csv
        cols = [
            "product_id", "product_name",
            "standard_material_cost", "actual_material_cost",
            "material_variance", "material_variance_pct",
            "standard_labor_cost", "actual_labor_cost",
            "labor_variance", "labor_variance_pct",
            "yield_rate", "yield_adjusted_total",
            "total_standard_cost", "total_variance", "total_variance_pct",
            "flag", "revision_recommended",
        ]
        report_path = os.path.join(self.workspace, "variance_report.csv")
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            writer.writerows(results)

        # 10. Build action string
        revision_items = [r for r in results if r["revision_recommended"] == "YES"]
        lines = ["Cost Variance Analysis Complete.", ""]
        lines.append(f"Total products analysed: {len(results)}")
        lines.append(f"Products flagged: {sum(1 for r in results if r['flag'] == 'YES')}")
        lines.append(f"Products recommended for revision: {len(revision_items)}")
        lines.append("")
        lines.append("Products recommended for cost revision:")
        for r in revision_items:
            reasons = []
            if abs(r["total_variance_pct"]) > thresholds["total_critical_threshold"]:
                reasons.append(f"total variance {r['total_variance_pct']:.2f}% exceeds critical threshold")
            if abs(r["material_variance_pct"]) > thresholds["material_critical_threshold"]:
                reasons.append(f"material variance {r['material_variance_pct']:.2f}% exceeds material critical threshold (non-preferred vendor used)")
            if r["yield_rate"] < thresholds["yield_loss_threshold"]:
                reasons.append(f"yield rate {r['yield_rate']:.4f} below minimum threshold")
            lines.append(
                f"  {r['product_id']} ({r['product_name']}): total variance = {r['total_variance_pct']:.2f}% "
                f"— reasons: {'; '.join(reasons)}"
            )

        action = "\n".join(lines)
        reward, info = self.step(action)
        info["verify_tool_calls"] = tool_calls
        return reward, info
