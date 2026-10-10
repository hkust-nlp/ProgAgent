"""
Environment for grant application budget risk assessment task.

Hardened tool surface (M2 + M3): tools return a mix of shapes — deeply
nested record objects with cursor pagination, JSON-encoded strings,
MCP-style envelopes, plain key:value text, and Python-repr strings.
Error responses use a different object shape than success responses and
tools never raise. Task semantics, data, ground truth, and scoring are
unchanged from the base environment.
"""

import ast
import csv
import hashlib
import json
import os
import sqlite3
import glob as glob_module
from typing import Tuple, Dict, List, Any

import yaml


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


def _date(start):
    return {"type": "date", "date": {"start": start, "end": None}}


VALID_STATUSES = ("pending_review", "approved", "rejected", "under_revision")


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

    # ---- Tool Methods ----

    @tool(
        description="List grant application records filtered by status. Each record includes the application title, PI reference, institution reference, program area, submission date, total requested amount, and status. Paginated.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by application status. One of: pending_review, approved, rejected, under_revision.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 10). Default 10.",
                },
            },
            "required": ["status"],
        },
    )
    def list_applications(self, status: Any = None, page: Any = 1, page_size: Any = 10) -> Any:
        if not isinstance(status, str) or status == "":
            return _error(400, "validation_error",
                          f"body.status should be a non-empty string, instead was {_shape(status)}.")
        if status not in VALID_STATUSES:
            return _error(400, "validation_error",
                          f"body.status is not a supported status value. Supported values: {', '.join(VALID_STATUSES)}.")
        try:
            page = int(page)
            page_size = int(page_size)
        except (TypeError, ValueError):
            return _error(400, "validation_error",
                          f"body.page and body.page_size should be integers, instead were {_shape(page)}, {_shape(page_size)}.")
        page_size = min(page_size, 10)
        page = max(page, 1)
        offset = (page - 1) * page_size

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) as cnt FROM grant_applications WHERE status = ?",
            (status,),
        )
        total = cursor.fetchone()["cnt"]

        cursor.execute(
            "SELECT app_id, pi_id, institution_id, title, program_area, submission_date, total_requested, status "
            "FROM grant_applications WHERE status = ? ORDER BY app_id LIMIT ? OFFSET ?",
            (status, page_size, offset),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        results = [
            {
                "object": "application",
                "id": r["app_id"],
                "properties": {
                    "Title": _title(r["title"]),
                    "PI": _relation(r["pi_id"]),
                    "Institution": _relation(r["institution_id"]),
                    "Program Area": _select(r["program_area"]),
                    "Submission Date": _date(r["submission_date"]),
                    "Total Requested": _number(r["total_requested"]),
                    "Status": _select(r["status"]),
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
        description="Get the itemized budget for a specific grant application: every budget line item with its category, subcategory, amount, and description, plus the application's total requested amount.",
        parameters={
            "type": "object",
            "properties": {
                "app_id": {
                    "type": "integer",
                    "description": "The application ID to retrieve budget items for.",
                },
            },
            "required": ["app_id"],
        },
    )
    def get_application_budget(self, app_id: Any = None) -> str:
        try:
            app_id = int(app_id)
        except (TypeError, ValueError):
            return json.dumps(_error(400, "validation_error",
                                     f"body.app_id should be an integer, instead was {_shape(app_id)}."))

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT total_requested FROM grant_applications WHERE app_id = ?",
            (app_id,),
        )
        row = cursor.fetchone()
        if row is None:
            conn.close()
            return json.dumps(_error(404, "object_not_found",
                                     f"Could not find application with ID: {app_id}."))
        total_requested = row["total_requested"]

        cursor.execute(
            "SELECT item_id, app_id, category, subcategory, amount, description "
            "FROM expense_line_items WHERE app_id = ? ORDER BY item_id",
            (app_id,),
        )
        items = [dict(r) for r in cursor.fetchall()]
        conn.close()

        results = [
            {
                "object": "line_item",
                "id": it["item_id"],
                "properties": {
                    "Application": _relation(it["app_id"]),
                    "Category": _select(it["category"]),
                    "Subcategory": _select(it["subcategory"]),
                    "Amount": _number(it["amount"]),
                    "Description": _rich_text(it["description"]),
                },
            }
            for it in items
        ]
        payload = {
            "object": "list",
            "results": results,
            "has_more": False,
            "next_cursor": None,
            "application": {
                "object": "application",
                "id": app_id,
                "properties": {
                    "Total Requested": _number(total_requested),
                },
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    @tool(
        description="Get the profile of a Principal Investigator (PI) by their ID: name, email, department, institution, career stage, h-index, and years active.",
        parameters={
            "type": "object",
            "properties": {
                "pi_id": {
                    "type": "integer",
                    "description": "The PI ID to look up.",
                },
            },
            "required": ["pi_id"],
        },
    )
    def get_pi_profile(self, pi_id: Any = None) -> Any:
        try:
            pi_id = int(pi_id)
        except (TypeError, ValueError):
            return _error(400, "validation_error",
                          f"body.pi_id should be an integer, instead was {_shape(pi_id)}.")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT pi_id, name, email, department, institution_id, career_stage, h_index, years_active "
            "FROM pi_profiles WHERE pi_id = ?",
            (pi_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find PI with ID: {pi_id}.")
        fields = dict(row)
        return "\n".join(f"{k}: {v}" for k, v in fields.items())

    @tool(
        description="Get historical financial reports for a PI: all past grant financial records with grant year, category, budgeted amount, and actual spending.",
        parameters={
            "type": "object",
            "properties": {
                "pi_id": {
                    "type": "integer",
                    "description": "The PI ID to retrieve historical reports for.",
                },
            },
            "required": ["pi_id"],
        },
    )
    def get_pi_historical_reports(self, pi_id: Any = None) -> Any:
        try:
            pi_id = int(pi_id)
        except (TypeError, ValueError):
            return _error(400, "validation_error",
                          f"body.pi_id should be an integer, instead was {_shape(pi_id)}.")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT pi_id FROM pi_profiles WHERE pi_id = ?", (pi_id,))
        if cursor.fetchone() is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find PI with ID: {pi_id}.")

        cursor.execute(
            "SELECT report_id, pi_id, grant_year, category, budgeted_amount, actual_spent "
            "FROM historical_financial_reports WHERE pi_id = ? ORDER BY grant_year, category",
            (pi_id,),
        )
        reports = [dict(r) for r in cursor.fetchall()]
        conn.close()

        payload = {
            "pi_id": pi_id,
            "num_reports": len(reports),
            "reports": reports,
        }
        return repr(payload)

    @tool(
        description="Get institution details by institution ID: name, type, state, base overhead rate, negotiation date, and NIH approval status.",
        parameters={
            "type": "object",
            "properties": {
                "institution_id": {
                    "type": "integer",
                    "description": "The institution ID to look up.",
                },
            },
            "required": ["institution_id"],
        },
    )
    def get_institution_info(self, institution_id: Any = None) -> Any:
        try:
            institution_id = int(institution_id)
        except (TypeError, ValueError):
            return _error(400, "validation_error",
                          f"body.institution_id should be an integer, instead was {_shape(institution_id)}.")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT institution_id, name, type, state, base_overhead_rate, negotiated_date, nih_approved "
            "FROM institutions WHERE institution_id = ?",
            (institution_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find institution with ID: {institution_id}.")
        return _envelope(dict(row))

    @tool(
        description="List all distinct expense categories used across all applications, with the count of line items per category.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_expense_categories(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT category, COUNT(*) as item_count FROM expense_line_items GROUP BY category ORDER BY category"
        )
        cats = [dict(r) for r in cursor.fetchall()]
        conn.close()

        return {"categories": cats, "total_categories": len(cats)}

    # ---- Evaluation ----

    def _compute_ground_truth(self):
        """Compute the full ground truth risk assessment for all pending applications."""
        # Load config files
        with open(os.path.join(self.workspace, "category_benchmarks.yaml"), "r") as f:
            benchmarks_data = yaml.safe_load(f)
        benchmarks = benchmarks_data["category_benchmarks"]

        with open(os.path.join(self.workspace, "risk_scoring_config.json"), "r") as f:
            risk_config = json.load(f)

        # Load overhead tiers
        overhead_tiers = {}
        with open(os.path.join(self.workspace, "overhead_rate_tiers.csv"), "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                overhead_tiers[row["institution_type"]] = float(row["approved_max_rate"])

        # Load all PI funding records
        pi_funding = {}
        funding_dir = os.path.join(self.workspace, "pi_funding_records")
        for fpath in sorted(glob_module.glob(os.path.join(funding_dir, "batch_*.json"))):
            with open(fpath, "r") as f:
                records = json.load(f)
            for rec in records:
                pi_funding[rec["pi_id"]] = rec

        # Get all pending applications from DB
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM grant_applications WHERE status = 'pending_review' ORDER BY app_id"
        )
        pending_apps = [dict(r) for r in cursor.fetchall()]

        results = []
        for app in pending_apps:
            app_id = app["app_id"]
            pi_id = app["pi_id"]
            institution_id = app["institution_id"]
            total_requested = app["total_requested"]

            # Get expense items
            cursor.execute(
                "SELECT category, amount FROM expense_line_items WHERE app_id = ?",
                (app_id,),
            )
            items = cursor.fetchall()

            # Aggregate by category
            cat_totals = {}
            for item in items:
                cat = item["category"]
                cat_totals[cat] = cat_totals.get(cat, 0) + item["amount"]

            # Check category benchmarks
            num_category_flags = 0
            categories_over = []
            total_cats_in_budget = len(cat_totals)
            for cat, amt in cat_totals.items():
                pct = (amt / total_requested) * 100 if total_requested > 0 else 0
                if cat in benchmarks and pct > benchmarks[cat]["max_pct"]:
                    num_category_flags += 1
                    categories_over.append(cat)

            # Category benchmark score component
            if total_cats_in_budget > 0:
                cat_score = min(30.0, num_category_flags * (30.0 / total_cats_in_budget))
            else:
                cat_score = 0.0

            # Get PI info
            cursor.execute(
                "SELECT * FROM pi_profiles WHERE pi_id = ?", (pi_id,)
            )
            pi = dict(cursor.fetchone())

            # Get institution info
            cursor.execute(
                "SELECT * FROM institutions WHERE institution_id = ?",
                (institution_id,),
            )
            inst = dict(cursor.fetchone())

            # Pub-to-funding ratio
            pi_fund = pi_funding.get(pi_id, {})
            total_pubs = pi_fund.get("total_publications", 0)
            total_funding_received = pi_fund.get("total_funding_received", 0)

            if total_funding_received > 0:
                pub_funding_ratio = round(total_pubs / (total_funding_received / 100000), 2)
            else:
                pub_funding_ratio = 0.0

            pub_funding_flag = False
            pub_score = 0.0
            critical_threshold = risk_config["pub_funding_ratio"]["critical_threshold"]
            low_threshold = risk_config["pub_funding_ratio"]["low_threshold"]
            if pub_funding_ratio < critical_threshold:
                pub_score = 25.0
                pub_funding_flag = True
            elif pub_funding_ratio < low_threshold:
                pub_score = 12.5
                pub_funding_flag = True

            # Historical variance
            cursor.execute(
                "SELECT budgeted_amount, actual_spent FROM historical_financial_reports WHERE pi_id = ?",
                (pi_id,),
            )
            hist_reports = cursor.fetchall()

            if hist_reports:
                variances = []
                for hr in hist_reports:
                    budgeted = hr["budgeted_amount"]
                    actual = hr["actual_spent"]
                    if budgeted > 0:
                        var_pct = abs(actual - budgeted) / budgeted * 100
                        variances.append(var_pct)
                historical_variance_pct = round(sum(variances) / len(variances), 2) if variances else 0.0
            else:
                historical_variance_pct = 0.0

            historical_flag = False
            hist_score = 0.0
            warning_pct = risk_config["historical_variance"]["warning_pct"]
            critical_pct = risk_config["historical_variance"]["critical_pct"]
            if historical_variance_pct > critical_pct:
                hist_score = 25.0
                historical_flag = True
            elif historical_variance_pct > warning_pct:
                hist_score = 12.5
                historical_flag = True

            # Overhead compliance
            inst_type = inst["type"]
            inst_overhead = inst["base_overhead_rate"]
            approved_max = overhead_tiers.get(inst_type, 100.0)

            overhead_flag = inst_overhead > approved_max
            overhead_score = 20.0 if overhead_flag else 0.0

            # Total risk score
            risk_score = round(cat_score + pub_score + hist_score + overhead_score, 2)

            # Risk tier
            tiers = risk_config["risk_tiers"]
            risk_tier = "Low"
            for tier_name, tier_range in tiers.items():
                if tier_range["min_score"] <= risk_score < tier_range["max_score"]:
                    risk_tier = tier_name
                    break
            # Handle score == 100
            if risk_score >= tiers["Critical"]["min_score"]:
                risk_tier = "Critical"

            results.append({
                "app_id": app_id,
                "pi_name": pi["name"],
                "institution_name": inst["name"],
                "total_requested": total_requested,
                "categories_over_benchmark": ", ".join(sorted(categories_over)) if categories_over else "none",
                "num_category_flags": num_category_flags,
                "pub_funding_ratio": pub_funding_ratio,
                "pub_funding_flag": pub_funding_flag,
                "historical_variance_pct": historical_variance_pct,
                "historical_flag": historical_flag,
                "overhead_rate": inst_overhead,
                "approved_max_rate": approved_max,
                "overhead_flag": overhead_flag,
                "risk_score": risk_score,
                "risk_tier": risk_tier,
            })

        conn.close()

        # Sort by risk_score descending, then app_id ascending
        results.sort(key=lambda x: (-x["risk_score"], x["app_id"]))
        return results

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
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # Criterion 1: Report file exists and has correct columns (15 pts)
        c1_max = 15
        max_score += c1_max
        report_path = os.path.join(self.workspace, "risk_assessment_report.csv")
        report_exists = os.path.exists(report_path)
        report_rows = []
        expected_columns = [
            "app_id", "pi_name", "institution_name", "total_requested",
            "categories_over_benchmark", "num_category_flags", "pub_funding_ratio",
            "pub_funding_flag", "historical_variance_pct", "historical_flag",
            "overhead_rate", "approved_max_rate", "overhead_flag", "risk_score", "risk_tier",
        ]

        if report_exists:
            try:
                with open(report_path, "r") as f:
                    reader = csv.DictReader(f)
                    report_rows = list(reader)
                    actual_columns = reader.fieldnames or []
                if set(expected_columns).issubset(set(actual_columns)):
                    c1_score = c1_max
                    c1_passed = True
                    c1_reason = ""
                else:
                    missing = set(expected_columns) - set(actual_columns)
                    c1_score = 5
                    c1_passed = False
                    c1_reason = f"Missing columns: {missing}"
            except Exception as e:
                c1_score = 0
                c1_passed = False
                c1_reason = f"Error reading report: {e}"
        else:
            c1_score = 0
            c1_passed = False
            c1_reason = "risk_assessment_report.csv not found in workspace"

        total_score += c1_score
        eval_criteria["report_file_structure"] = {
            "passed": c1_passed,
            "score": c1_score,
            "max_score": c1_max,
            "reason": c1_reason if not c1_passed else "",
        }

        # Criterion 2: Correct number of applications assessed (10 pts)
        c2_max = 10
        max_score += c2_max
        expected_count = len(ground_truth)
        actual_count = len(report_rows)
        if actual_count == expected_count:
            c2_score = c2_max
            c2_passed = True
            c2_reason = ""
        else:
            c2_score = max(0, c2_max - abs(actual_count - expected_count) * 2)
            c2_passed = False
            c2_reason = f"Expected {expected_count} rows, got {actual_count}"

        total_score += c2_score
        eval_criteria["application_count"] = {
            "passed": c2_passed,
            "score": c2_score,
            "max_score": c2_max,
            "reason": c2_reason if not c2_passed else "",
        }

        # Criterion 3: Correct risk tier assignments (20 pts)
        c3_max = 20
        max_score += c3_max
        gt_tiers = {str(r["app_id"]): r["risk_tier"] for r in ground_truth}
        correct_tiers = 0
        total_compared = 0
        for row in report_rows:
            aid = str(row.get("app_id", "")).strip()
            tier = row.get("risk_tier", "").strip()
            if aid in gt_tiers:
                total_compared += 1
                if tier == gt_tiers[aid]:
                    correct_tiers += 1

        if total_compared > 0:
            tier_accuracy = correct_tiers / total_compared
            c3_score = round(c3_max * tier_accuracy, 2)
            c3_passed = tier_accuracy == 1.0
            c3_reason = "" if c3_passed else f"{correct_tiers}/{total_compared} tiers correct"
        else:
            c3_score = 0
            c3_passed = False
            c3_reason = "No matching application IDs found"

        total_score += c3_score
        eval_criteria["risk_tier_accuracy"] = {
            "passed": c3_passed,
            "score": c3_score,
            "max_score": c3_max,
            "reason": c3_reason if not c3_passed else "",
        }

        # Criterion 4: Correct risk scores (within tolerance) (20 pts)
        c4_max = 20
        max_score += c4_max
        gt_scores = {str(r["app_id"]): r["risk_score"] for r in ground_truth}
        correct_scores = 0
        score_compared = 0
        for row in report_rows:
            aid = str(row.get("app_id", "")).strip()
            try:
                reported_score = float(row.get("risk_score", -1))
            except (ValueError, TypeError):
                continue
            if aid in gt_scores:
                score_compared += 1
                if abs(reported_score - gt_scores[aid]) < 0.1:
                    correct_scores += 1

        if score_compared > 0:
            score_accuracy = correct_scores / score_compared
            c4_score = round(c4_max * score_accuracy, 2)
            c4_passed = score_accuracy == 1.0
            c4_reason = "" if c4_passed else f"{correct_scores}/{score_compared} scores correct"
        else:
            c4_score = 0
            c4_passed = False
            c4_reason = "No matching application IDs found for score comparison"

        total_score += c4_score
        eval_criteria["risk_score_accuracy"] = {
            "passed": c4_passed,
            "score": c4_score,
            "max_score": c4_max,
            "reason": c4_reason if not c4_passed else "",
        }

        # Criterion 5: Correct category flags (15 pts)
        c5_max = 15
        max_score += c5_max
        gt_cat_flags = {str(r["app_id"]): r["categories_over_benchmark"] for r in ground_truth}
        correct_flags = 0
        flag_compared = 0
        for row in report_rows:
            aid = str(row.get("app_id", "")).strip()
            reported_cats = row.get("categories_over_benchmark", "").strip()
            if aid in gt_cat_flags:
                flag_compared += 1
                expected_cats = gt_cat_flags[aid]
                if reported_cats == expected_cats:
                    correct_flags += 1

        if flag_compared > 0:
            flag_accuracy = correct_flags / flag_compared
            c5_score = round(c5_max * flag_accuracy, 2)
            c5_passed = flag_accuracy == 1.0
            c5_reason = "" if c5_passed else f"{correct_flags}/{flag_compared} category flag sets correct"
        else:
            c5_score = 0
            c5_passed = False
            c5_reason = "No matching application IDs for category flag comparison"

        total_score += c5_score
        eval_criteria["category_flag_accuracy"] = {
            "passed": c5_passed,
            "score": c5_score,
            "max_score": c5_max,
            "reason": c5_reason if not c5_passed else "",
        }

        # Criterion 6: Sort order (10 pts)
        c6_max = 10
        max_score += c6_max
        if len(report_rows) >= 2:
            correctly_sorted = True
            for i in range(len(report_rows) - 1):
                try:
                    s1 = float(report_rows[i].get("risk_score", 0))
                    s2 = float(report_rows[i + 1].get("risk_score", 0))
                    a1 = int(report_rows[i].get("app_id", 0))
                    a2 = int(report_rows[i + 1].get("app_id", 0))
                except (ValueError, TypeError):
                    correctly_sorted = False
                    break
                if s1 < s2 or (s1 == s2 and a1 > a2):
                    correctly_sorted = False
                    break
            c6_score = c6_max if correctly_sorted else 0
            c6_passed = correctly_sorted
            c6_reason = "" if c6_passed else "Report not sorted by risk_score desc, app_id asc"
        elif len(report_rows) == 1:
            c6_score = c6_max
            c6_passed = True
            c6_reason = ""
        else:
            c6_score = 0
            c6_passed = False
            c6_reason = "No rows to check sort order"

        total_score += c6_score
        eval_criteria["sort_order"] = {
            "passed": c6_passed,
            "score": c6_score,
            "max_score": c6_max,
            "reason": c6_reason if not c6_passed else "",
        }

        # Criterion 7: Response summary lists High and Critical applications (10 pts)
        c7_max = 10
        max_score += c7_max
        high_critical = [r for r in ground_truth if r["risk_tier"] in ("High", "Critical")]
        action_lower = action.lower() if action else ""
        found_in_response = 0
        for r in high_critical:
            # Check if app_id is mentioned in the response
            if str(r["app_id"]) in (action or ""):
                found_in_response += 1

        if high_critical:
            response_accuracy = found_in_response / len(high_critical)
            c7_score = round(c7_max * response_accuracy, 2)
            c7_passed = response_accuracy == 1.0
            c7_reason = "" if c7_passed else f"Only {found_in_response}/{len(high_critical)} High/Critical apps mentioned in response"
        else:
            # No high/critical apps - check response acknowledges this
            no_hc_phrases = ["no applications", "none were flagged", "no high", "no critical",
                             "all low", "all medium", "0 total", "zero"]
            found_phrase = any(p in action_lower for p in no_hc_phrases)
            c7_score = c7_max if found_phrase else 0
            c7_passed = c7_score > 0
            c7_reason = "" if c7_passed else "Response should indicate no High/Critical applications found"

        total_score += c7_score
        eval_criteria["response_summary"] = {
            "passed": c7_passed,
            "score": c7_score,
            "max_score": c7_max,
            "reason": c7_reason if not c7_passed else "",
        }

        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": round(total_score, 2),
            "max_score": max_score,
        }

        return reward, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.

        Note: the hardened tool surface returns mixed shapes, so this solver
        unwraps MCP envelopes, parses JSON strings / repr strings / key:value
        text, walks the nested property objects, and follows has_more /
        next_cursor pagination.
        """
        import glob as g

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        def unwrap_envelope(resp):
            return json.loads(resp["content"][0]["text"])

        def parse_kv_text(text):
            out = {}
            for line in text.splitlines():
                k, _, v = line.partition(": ")
                out[k] = v
            return out

        # Step 1: Read config files from workspace
        with open(os.path.join(self.workspace, "category_benchmarks.yaml"), "r") as f:
            benchmarks_data = yaml.safe_load(f)
        benchmarks = benchmarks_data["category_benchmarks"]

        with open(os.path.join(self.workspace, "risk_scoring_config.json"), "r") as f:
            risk_config = json.load(f)

        overhead_tiers = {}
        with open(os.path.join(self.workspace, "overhead_rate_tiers.csv"), "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                overhead_tiers[row["institution_type"]] = float(row["approved_max_rate"])

        with open(os.path.join(self.workspace, "review_guidelines.md"), "r") as f:
            guidelines = f.read()

        # Step 2: Load all PI funding records from workspace
        pi_funding = {}
        funding_dir = os.path.join(self.workspace, "pi_funding_records")
        for fpath in sorted(g.glob(os.path.join(funding_dir, "batch_*.json"))):
            with open(fpath, "r") as f:
                records = json.load(f)
            for rec in records:
                pi_funding[rec["pi_id"]] = rec

        # Probe the category listing tool (native dict)
        _ = call_tool("list_expense_categories")

        # Step 3: List all pending applications (nested records, cursor pagination)
        pending_apps = []
        page = 1
        while True:
            result = call_tool("list_applications", status="pending_review", page=page, page_size=10)
            for rec in result["results"]:
                props = rec["properties"]
                pending_apps.append({
                    "app_id": rec["id"],
                    "pi_id": props["PI"]["relation"][0]["id"],
                    "institution_id": props["Institution"]["relation"][0]["id"],
                    "total_requested": props["Total Requested"]["number"],
                })
            if not result["has_more"]:
                break
            page = result["next_cursor"]

        # Step 4: For each pending application, gather all data via tools
        assessment_results = []
        seen_pis = {}
        seen_institutions = {}
        seen_hist = {}

        for app in pending_apps:
            app_id = app["app_id"]
            pi_id = app["pi_id"]
            institution_id = app["institution_id"]
            total_requested = app["total_requested"]

            # Get expense items (JSON-encoded string with nested line_item records)
            budget_raw = call_tool("get_application_budget", app_id=app_id)
            budget_obj = json.loads(budget_raw)
            line_items = [
                {
                    "category": li["properties"]["Category"]["select"]["name"],
                    "amount": li["properties"]["Amount"]["number"],
                }
                for li in budget_obj["results"]
            ]

            # Get PI profile (plain key: value text)
            if pi_id not in seen_pis:
                pi_text = call_tool("get_pi_profile", pi_id=pi_id)
                seen_pis[pi_id] = parse_kv_text(pi_text)
            pi_profile = seen_pis[pi_id]

            # Get historical reports (Python-repr string)
            if pi_id not in seen_hist:
                hist_raw = call_tool("get_pi_historical_reports", pi_id=pi_id)
                seen_hist[pi_id] = ast.literal_eval(hist_raw)
            hist_result = seen_hist[pi_id]

            # Get institution info (MCP envelope)
            if institution_id not in seen_institutions:
                inst_resp = call_tool("get_institution_info", institution_id=institution_id)
                seen_institutions[institution_id] = unwrap_envelope(inst_resp)
            inst_info = seen_institutions[institution_id]

            # Aggregate expense categories
            cat_totals = {}
            for item in line_items:
                cat = item["category"]
                cat_totals[cat] = cat_totals.get(cat, 0) + item["amount"]

            # Check category benchmarks
            num_category_flags = 0
            categories_over = []
            total_cats_in_budget = len(cat_totals)
            for cat, amt in cat_totals.items():
                pct = (amt / total_requested) * 100 if total_requested > 0 else 0
                if cat in benchmarks and pct > benchmarks[cat]["max_pct"]:
                    num_category_flags += 1
                    categories_over.append(cat)

            # Category score
            if total_cats_in_budget > 0:
                cat_score = min(30.0, num_category_flags * (30.0 / total_cats_in_budget))
            else:
                cat_score = 0.0

            # Pub-to-funding ratio
            pi_fund = pi_funding.get(pi_id, {})
            total_pubs = pi_fund.get("total_publications", 0)
            total_funding_received = pi_fund.get("total_funding_received", 0)

            if total_funding_received > 0:
                pub_funding_ratio = round(total_pubs / (total_funding_received / 100000), 2)
            else:
                pub_funding_ratio = 0.0

            pub_funding_flag = False
            pub_score = 0.0
            critical_threshold = risk_config["pub_funding_ratio"]["critical_threshold"]
            low_threshold = risk_config["pub_funding_ratio"]["low_threshold"]
            if pub_funding_ratio < critical_threshold:
                pub_score = 25.0
                pub_funding_flag = True
            elif pub_funding_ratio < low_threshold:
                pub_score = 12.5
                pub_funding_flag = True

            # Historical variance
            hist_reports = hist_result["reports"]
            if hist_reports:
                variances = []
                for hr in hist_reports:
                    budgeted = hr["budgeted_amount"]
                    actual = hr["actual_spent"]
                    if budgeted > 0:
                        var_pct = abs(actual - budgeted) / budgeted * 100
                        variances.append(var_pct)
                historical_variance_pct = round(sum(variances) / len(variances), 2) if variances else 0.0
            else:
                historical_variance_pct = 0.0

            historical_flag = False
            hist_score = 0.0
            warning_pct = risk_config["historical_variance"]["warning_pct"]
            critical_pct = risk_config["historical_variance"]["critical_pct"]
            if historical_variance_pct > critical_pct:
                hist_score = 25.0
                historical_flag = True
            elif historical_variance_pct > warning_pct:
                hist_score = 12.5
                historical_flag = True

            # Overhead compliance
            inst_type = inst_info["type"]
            inst_overhead = inst_info["base_overhead_rate"]
            approved_max = overhead_tiers.get(inst_type, 100.0)
            overhead_flag = inst_overhead > approved_max
            overhead_score = 20.0 if overhead_flag else 0.0

            # Total risk score
            risk_score = round(cat_score + pub_score + hist_score + overhead_score, 2)

            # Risk tier
            tiers = risk_config["risk_tiers"]
            risk_tier = "Low"
            for tier_name, tier_range in tiers.items():
                if tier_range["min_score"] <= risk_score < tier_range["max_score"]:
                    risk_tier = tier_name
                    break
            if risk_score >= tiers["Critical"]["min_score"]:
                risk_tier = "Critical"

            assessment_results.append({
                "app_id": app_id,
                "pi_name": pi_profile["name"],
                "institution_name": inst_info["name"],
                "total_requested": total_requested,
                "categories_over_benchmark": ", ".join(sorted(categories_over)) if categories_over else "none",
                "num_category_flags": num_category_flags,
                "pub_funding_ratio": pub_funding_ratio,
                "pub_funding_flag": pub_funding_flag,
                "historical_variance_pct": historical_variance_pct,
                "historical_flag": historical_flag,
                "overhead_rate": inst_overhead,
                "approved_max_rate": approved_max,
                "overhead_flag": overhead_flag,
                "risk_score": risk_score,
                "risk_tier": risk_tier,
            })

        # Sort by risk_score descending, app_id ascending
        assessment_results.sort(key=lambda x: (-x["risk_score"], x["app_id"]))

        # Write the report CSV
        report_path = os.path.join(self.workspace, "risk_assessment_report.csv")
        fieldnames = [
            "app_id", "pi_name", "institution_name", "total_requested",
            "categories_over_benchmark", "num_category_flags", "pub_funding_ratio",
            "pub_funding_flag", "historical_variance_pct", "historical_flag",
            "overhead_rate", "approved_max_rate", "overhead_flag", "risk_score", "risk_tier",
        ]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in assessment_results:
                writer.writerow(r)

        # Build action string with summary
        high_critical = [r for r in assessment_results if r["risk_tier"] in ("High", "Critical")]
        summary_lines = [
            f"Risk assessment completed for {len(assessment_results)} pending grant applications.",
            f"Results saved to risk_assessment_report.csv.",
            "",
        ]
        if high_critical:
            summary_lines.append(f"Applications flagged as High or Critical risk ({len(high_critical)} total):")
            for r in high_critical:
                summary_lines.append(
                    f"  - App {r['app_id']}: {r['pi_name']} ({r['institution_name']}), "
                    f"risk_score={r['risk_score']}, tier={r['risk_tier']}"
                )
        else:
            summary_lines.append("No applications were flagged as High or Critical risk.")

        action = "\n".join(summary_lines)

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need at least 15"
        print(f"verify: {tool_call_count} tool calls made")

        return self.step(action)
