"""Environment for rental applicant risk screening task (hardened tool surface).

Hardened surface (M2 + M3): tools return a mix of shapes — deeply nested
record objects, JSON-encoded strings, MCP-style envelopes, plain key:value
text, and Python-repr strings. Error responses use a different object shape
than success responses. Task semantics, data, and scoring are unchanged
from the base environment.
"""

import ast
import hashlib
import json
import os
import csv
import sqlite3
import glob
import re
from datetime import datetime
from typing import Tuple, Dict, List, Any

import yaml
import pandas as pd


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
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

    # ── Tool methods ──────────────────────────────────────────────────

    @tool(
        description="List rental applicant records with cursor-based pagination. Each record includes the applicant's name, application date, the property they applied for, and application status.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)."
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of applicants per page. Maximum 20."
                }
            },
            "required": ["page"]
        }
    )
    def list_applicants(self, page: Any = None, page_size: Any = 10):
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            return _error(400, "validation_error",
                          f"body.page should be a positive integer, instead was {_shape(page)}.")
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
            return _error(400, "validation_error",
                          f"body.page_size should be a positive integer, instead was {_shape(page_size)}.")
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM applicants")
        total = cursor.fetchone()[0]
        cursor.execute(
            "SELECT applicant_id, first_name, last_name, application_date, property_id, status "
            "FROM applicants ORDER BY applicant_id LIMIT ? OFFSET ?",
            (page_size, offset)
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        results = [
            {
                "object": "applicant",
                "id": r["applicant_id"],
                "properties": {
                    "Name": _title(f"{r['first_name']} {r['last_name']}"),
                    "Application Date": _date(r["application_date"]),
                    "Property": _relation(r["property_id"]),
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
        description="Retrieve the full record for a single rental applicant, including name, contact details, application date, the property applied for, and application status.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "integer",
                    "description": "The applicant's unique ID."
                }
            },
            "required": ["applicant_id"]
        }
    )
    def get_applicant_details(self, applicant_id: Any = None):
        if not isinstance(applicant_id, int) or isinstance(applicant_id, bool):
            return _error(400, "validation_error",
                          f"body.applicant_id should be an integer, instead was {_shape(applicant_id)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT applicant_id, first_name, last_name, email, phone, application_date, property_id, status "
            "FROM applicants WHERE applicant_id = ?",
            (applicant_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find applicant with ID: {applicant_id}.")
        return {
            "object": "applicant",
            "id": row["applicant_id"],
            "properties": {
                "Name": _title(f"{row['first_name']} {row['last_name']}"),
                "Email": _rich_text(row["email"]),
                "Phone": _rich_text(row["phone"]),
                "Application Date": _date(row["application_date"]),
                "Property": _relation(row["property_id"]),
                "Status": _select(row["status"]),
            },
        }

    @tool(
        description="Retrieve the credit report on file for a specific applicant. The report covers the credit score, number of delinquent accounts, bankruptcy status, credit utilization, total outstanding debt, and the report date.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "integer",
                    "description": "The applicant's unique ID."
                }
            },
            "required": ["applicant_id"]
        }
    )
    def get_credit_report(self, applicant_id: Any = None):
        if not isinstance(applicant_id, int) or isinstance(applicant_id, bool):
            return json.dumps(_error(400, "validation_error",
                              f"body.applicant_id should be an integer, instead was {_shape(applicant_id)}."))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT credit_score, num_delinquencies, bankruptcy_flag, credit_utilization, total_debt, report_date "
            "FROM credit_reports WHERE applicant_id = ?",
            (applicant_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return json.dumps(_error(404, "object_not_found",
                              f"Could not find credit report with ID: {applicant_id}."))
        payload = {
            "object": "credit_report",
            "id": applicant_id,
            "properties": {
                "Applicant": _relation(applicant_id),
                "Credit Score": _number(row["credit_score"]),
                "Delinquent Accounts": _number(row["num_delinquencies"]),
                "Bankruptcy On File": _select("yes" if row["bankruptcy_flag"] else "no"),
                "Credit Utilization": _number(row["credit_utilization"]),
                "Total Debt": _number(row["total_debt"]),
                "Report Date": _date(row["report_date"]),
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    @tool(
        description="Check the national eviction database for records associated with a specific applicant. Returns all eviction entries on file, each with its date, court, case number, judgment amount, and reason category.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "integer",
                    "description": "The applicant's unique ID."
                }
            },
            "required": ["applicant_id"]
        }
    )
    def check_eviction_history(self, applicant_id: Any = None):
        if not isinstance(applicant_id, int) or isinstance(applicant_id, bool):
            return _error(400, "validation_error",
                          f"body.applicant_id should be an integer, instead was {_shape(applicant_id)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT eviction_date, court_name, case_number, judgment_amount, reason "
            "FROM eviction_records WHERE applicant_id = ? ORDER BY eviction_date DESC",
            (applicant_id,)
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        results = [
            {
                "object": "eviction_record",
                "id": r["case_number"],
                "properties": {
                    "Applicant": _relation(applicant_id),
                    "Eviction Date": _date(r["eviction_date"]),
                    "Court": _rich_text(r["court_name"]),
                    "Judgment Amount": _number(r["judgment_amount"]),
                    "Reason": _select(r["reason"]),
                },
            }
            for r in rows
        ]
        payload = {
            "object": "list",
            "results": results,
            "has_more": False,
            "next_cursor": None,
        }
        return _envelope(payload)

    @tool(
        description="Retrieve the landlord references on file for a specific applicant. Each reference carries the landlord's name, the reference date, ratings for payment timeliness, property care, and lease compliance, the landlord's rent-again recommendation, and free-form comments.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "integer",
                    "description": "The applicant's unique ID."
                }
            },
            "required": ["applicant_id"]
        }
    )
    def get_landlord_references(self, applicant_id: Any = None):
        if not isinstance(applicant_id, int) or isinstance(applicant_id, bool):
            return _error(400, "validation_error",
                          f"body.applicant_id should be an integer, instead was {_shape(applicant_id)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT reference_id, landlord_name, reference_date, payment_timeliness, property_care, "
            "lease_compliance, would_rent_again, comments "
            "FROM landlord_references WHERE applicant_id = ? ORDER BY reference_date DESC",
            (applicant_id,)
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        results = [
            {
                "object": "landlord_reference",
                "id": r["reference_id"],
                "properties": {
                    "Landlord": _title(r["landlord_name"]),
                    "Applicant": _relation(applicant_id),
                    "Reference Date": _date(r["reference_date"]),
                    "Payment Timeliness": _number(r["payment_timeliness"]),
                    "Property Care": _number(r["property_care"]),
                    "Lease Compliance": _number(r["lease_compliance"]),
                    "Would Rent Again": _select(r["would_rent_again"]),
                    "Comments": _rich_text(r["comments"]),
                },
            }
            for r in rows
        ]
        payload = {
            "object": "list",
            "results": results,
            "has_more": False,
            "next_cursor": None,
        }
        return repr(payload)

    @tool(
        description="Get details about a rental property: its address, property type, number of bedrooms, and neighborhood.",
        parameters={
            "type": "object",
            "properties": {
                "property_id": {
                    "type": "integer",
                    "description": "The property's unique ID."
                }
            },
            "required": ["property_id"]
        }
    )
    def get_property_details(self, property_id: Any = None):
        if not isinstance(property_id, int) or isinstance(property_id, bool):
            return _error(400, "validation_error",
                          f"body.property_id should be an integer, instead was {_shape(property_id)}.")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT property_id, address, property_type, bedrooms, neighborhood "
            "FROM properties WHERE property_id = ?",
            (property_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return _error(404, "object_not_found",
                          f"Could not find property with ID: {property_id}.")
        fields = {
            "property_id": row["property_id"],
            "address": row["address"],
            "property_type": row["property_type"],
            "bedrooms": row["bedrooms"],
            "neighborhood": row["neighborhood"],
        }
        return "\n".join(f"{k}: {v}" for k, v in fields.items())

    # ── Helper methods for ground-truth computation ───────────────────

    def _load_risk_config(self):
        with open(os.path.join(self.workspace, "risk_config.yaml"), 'r') as f:
            return yaml.safe_load(f)

    def _load_eviction_severity(self):
        df = pd.read_csv(os.path.join(self.workspace, "eviction_severity.csv"))
        return dict(zip(df['reason'], df['severity_weight']))

    def _load_income_data(self):
        """Load all applicant income data from workspace JSON files."""
        income = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "applicant_income_*.json"))):
            with open(fp, 'r') as f:
                for rec in json.load(f):
                    income[rec["applicant_id"]] = rec
        return income

    def _load_rent_data(self):
        """Load all rental listings from workspace CSV files."""
        rents = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "rental_listings_*.csv"))):
            df = pd.read_csv(fp)
            for _, row in df.iterrows():
                rents[int(row["property_id"])] = float(row["monthly_rent"])
        return rents

    def _load_reference_verifications(self):
        """Load reference verification statuses from workspace TXT files."""
        verifications = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "reference_verification_*.txt"))):
            with open(fp, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # Format: Reference ID: X | Applicant ID: Y | Verification: STATUS
                    parts = line.split("|")
                    ref_id = int(parts[0].split(":")[1].strip())
                    status = parts[2].split(":")[1].strip()
                    verifications[ref_id] = status
        return verifications

    def _compute_ground_truth(self):
        """Compute ground truth risk scores for all applicants."""
        config = self._load_risk_config()
        severity_map = self._load_eviction_severity()
        income_data = self._load_income_data()
        rent_data = self._load_rent_data()
        ref_verifications = self._load_reference_verifications()

        weights = config["weights"]
        cs = config["credit_scoring"]
        ir = config["income_ratio"]
        es = config["eviction_scoring"]
        rs = config["reference_scoring"]
        ref_date = datetime.strptime(config["reference_date"], "%Y-%m-%d")
        tiers = config["risk_tiers"]
        threshold = config["review_threshold"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get all applicants
        cursor.execute("SELECT * FROM applicants ORDER BY applicant_id")
        applicants = [dict(r) for r in cursor.fetchall()]

        results = []
        for app in applicants:
            aid = app["applicant_id"]
            pid = app["property_id"]

            # --- Credit sub-score ---
            cursor.execute("SELECT * FROM credit_reports WHERE applicant_id = ?", (aid,))
            cr = dict(cursor.fetchone())
            credit_base = max(0, (cs["base_threshold"] - cr["credit_score"])) / cs["score_range"] * 100
            credit_sub = credit_base
            if cr["bankruptcy_flag"]:
                credit_sub += cs["bankruptcy_penalty"]
            credit_sub += min(cr["num_delinquencies"] * cs["delinquency_penalty_per_item"],
                              cs["max_delinquency_penalty"])
            if cr["credit_utilization"] > cs["high_utilization_threshold"]:
                credit_sub += cs["high_utilization_penalty"]
            credit_sub = min(credit_sub, 100)

            # --- Income ratio sub-score ---
            inc = income_data.get(aid, {})
            monthly_income = inc.get("monthly_income", 0) + inc.get("additional_income", 0)
            monthly_rent = rent_data.get(pid, 0)
            if monthly_rent > 0:
                ratio = monthly_income / monthly_rent
            else:
                ratio = 999
            if ratio >= ir["minimum_ratio"]:
                income_sub = 0
            else:
                income_sub = (ir["minimum_ratio"] - ratio) / ir["minimum_ratio"] * 100
            income_sub = min(income_sub, 100)

            # --- Eviction sub-score ---
            cursor.execute("SELECT * FROM eviction_records WHERE applicant_id = ?", (aid,))
            evictions = [dict(r) for r in cursor.fetchall()]
            eviction_total = 0
            for ev in evictions:
                sev = severity_map.get(ev["reason"], 0.5)
                ev_date = datetime.strptime(ev["eviction_date"], "%Y-%m-%d")
                years_ago = (ref_date - ev_date).days / 365.25
                if years_ago <= es["recency_years"]:
                    mult = es["recency_multiplier"]
                else:
                    mult = 1.0
                eviction_total += sev * mult
            eviction_sub = min(eviction_total * es["base_scale_factor"], 100)

            # --- Reference sub-score ---
            cursor.execute("SELECT * FROM landlord_references WHERE applicant_id = ?", (aid,))
            all_refs = [dict(r) for r in cursor.fetchall()]
            verified_refs = [r for r in all_refs if ref_verifications.get(r["reference_id"]) == "VERIFIED"]

            if not verified_refs:
                reference_sub = rs["no_references_score"]
                avg_ref_rating = None
            else:
                ref_means = []
                penalty = 0
                for r in verified_refs:
                    mean_r = (r["payment_timeliness"] + r["property_care"] + r["lease_compliance"]) / 3
                    ref_means.append(mean_r)
                    if r["would_rent_again"] == "no":
                        penalty += rs["would_not_rent_again_penalty"]
                    elif r["would_rent_again"] == "maybe":
                        penalty += rs["uncertain_recommendation_penalty"]
                avg_ref_rating = sum(ref_means) / len(ref_means)
                reference_sub = (5 - avg_ref_rating) / 5 * 60 + penalty
                reference_sub = min(reference_sub, 100)

            # --- Final risk score ---
            risk_score = (
                weights["credit"] * credit_sub +
                weights["income_ratio"] * income_sub +
                weights["eviction"] * eviction_sub +
                weights["references"] * reference_sub
            )
            risk_score = round(risk_score, 2)

            # --- Risk tier ---
            risk_tier = "Low"
            for tier_name in ["Critical", "High", "Moderate", "Low"]:
                if risk_score >= tiers[tier_name]:
                    risk_tier = tier_name
                    break

            # --- Primary flag ---
            components = {
                "credit": credit_sub,
                "eviction": eviction_sub,
                "income_ratio": income_sub,
                "references": reference_sub,
            }
            max_val = max(components.values())
            primary_flags = sorted([k for k, v in components.items() if v == max_val])
            primary_flag = primary_flags[0]

            results.append({
                "applicant_id": aid,
                "full_name": f"{app['first_name']} {app['last_name']}",
                "risk_score": risk_score,
                "risk_tier": risk_tier,
                "primary_flag": primary_flag,
                "credit_score": cr["credit_score"],
                "income_to_rent_ratio": round(ratio, 2),
                "eviction_count": len(evictions),
                "avg_reference_rating": round(avg_ref_rating, 2) if avg_ref_rating is not None else "N/A",
            })

        conn.close()

        # Sort: risk_score DESC, applicant_id ASC
        results.sort(key=lambda x: (-x["risk_score"], x["applicant_id"]))

        # Review queue = those at or above threshold
        queue = [r for r in results if r["risk_score"] >= threshold]

        return results, queue, config

    # ── Evaluation ────────────────────────────────────────────────────

    def step(
        self, action: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        all_results, expected_queue, config = self._compute_ground_truth()
        threshold = config["review_threshold"]
        tiers = config["risk_tiers"]

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: File existence and column structure (10 pts) ---
        c1_max = 10
        c1_score = 0
        queue_path = os.path.join(self.workspace, "review_queue.csv")
        expected_cols = [
            "applicant_id", "full_name", "risk_score", "risk_tier", "primary_flag",
            "credit_score", "income_to_rent_ratio", "eviction_count", "avg_reference_rating"
        ]
        file_ok = False
        submitted_rows = []
        if os.path.isfile(queue_path):
            try:
                df = pd.read_csv(queue_path)
                actual_cols = list(df.columns)
                if actual_cols == expected_cols:
                    c1_score = c1_max
                    file_ok = True
                    submitted_rows = df.to_dict(orient='records')
                else:
                    c1_score = 4  # file exists but wrong columns
                    # try to work with it anyway
                    if all(c in actual_cols for c in expected_cols):
                        file_ok = True
                        submitted_rows = df[expected_cols].to_dict(orient='records')
            except Exception:
                c1_score = 2  # file exists but not parseable
        eval_criteria["file_format"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
        }
        if c1_score < c1_max:
            eval_criteria["file_format"]["reason"] = f"Expected columns: {expected_cols}"

        # --- Criterion 2: Correct applicant set in queue (20 pts) ---
        c2_max = 20
        c2_score = 0
        if file_ok and submitted_rows:
            expected_ids = set(r["applicant_id"] for r in expected_queue)
            submitted_ids = set()
            for r in submitted_rows:
                try:
                    submitted_ids.add(int(float(r["applicant_id"])))
                except (ValueError, KeyError):
                    pass
            if expected_ids == submitted_ids:
                c2_score = c2_max
            else:
                correct = len(expected_ids & submitted_ids)
                total_expected = len(expected_ids)
                if total_expected > 0:
                    c2_score = int(c2_max * correct / total_expected * 0.8)  # partial credit
        eval_criteria["applicant_set"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
        }
        if c2_score < c2_max:
            eval_criteria["applicant_set"]["reason"] = (
                f"Expected {len(expected_queue)} applicants in queue"
            )

        # --- Criterion 3: Risk score accuracy (25 pts) ---
        c3_max = 25
        c3_score = 0
        if file_ok and submitted_rows:
            expected_scores = {r["applicant_id"]: r["risk_score"] for r in expected_queue}
            correct_scores = 0
            for r in submitted_rows:
                try:
                    aid = int(float(r["applicant_id"]))
                    sub_score = float(r["risk_score"])
                    if aid in expected_scores:
                        if abs(sub_score - expected_scores[aid]) <= 0.5:
                            correct_scores += 1
                except (ValueError, KeyError):
                    pass
            if len(expected_queue) > 0:
                c3_score = int(c3_max * correct_scores / len(expected_queue))
        eval_criteria["risk_scores"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
        }
        if c3_score < c3_max:
            eval_criteria["risk_scores"]["reason"] = "Some risk scores deviate from ground truth"

        # --- Criterion 4: Correct sorting (15 pts) ---
        c4_max = 15
        c4_score = 0
        if file_ok and submitted_rows:
            expected_order = [(r["applicant_id"],) for r in expected_queue]
            submitted_order = []
            for r in submitted_rows:
                try:
                    submitted_order.append((int(float(r["applicant_id"])),))
                except (ValueError, KeyError):
                    pass
            if submitted_order == expected_order:
                c4_score = c4_max
            else:
                # Partial: check if at least sorted by risk_score desc
                try:
                    scores = [float(r["risk_score"]) for r in submitted_rows]
                    if scores == sorted(scores, reverse=True):
                        c4_score = c4_max // 2
                except (ValueError, KeyError):
                    pass
        eval_criteria["sorting"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
        }
        if c4_score < c4_max:
            eval_criteria["sorting"]["reason"] = "Sorting should be risk_score DESC, applicant_id ASC"

        # --- Criterion 5: Risk tier accuracy (15 pts) ---
        c5_max = 15
        c5_score = 0
        if file_ok and submitted_rows:
            expected_tiers = {r["applicant_id"]: r["risk_tier"] for r in expected_queue}
            correct_tiers = 0
            for r in submitted_rows:
                try:
                    aid = int(float(r["applicant_id"]))
                    tier = str(r["risk_tier"]).strip()
                    if aid in expected_tiers and tier == expected_tiers[aid]:
                        correct_tiers += 1
                except (ValueError, KeyError):
                    pass
            if len(expected_queue) > 0:
                c5_score = int(c5_max * correct_tiers / len(expected_queue))
        eval_criteria["risk_tiers"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
        }
        if c5_score < c5_max:
            eval_criteria["risk_tiers"]["reason"] = "Some risk tier assignments are incorrect"

        # --- Criterion 6: Summary in response (15 pts) ---
        c6_max = 15
        c6_score = 0
        if action:
            action_lower = action.lower()
            # Check total applicants screened
            total_applicants = len(all_results)
            if str(total_applicants) in action:
                c6_score += 3

            # Check number in review queue
            queue_count = len(expected_queue)
            if str(queue_count) in action:
                c6_score += 3

            # Check per-tier counts
            tier_counts = {}
            for r in all_results:
                tier_counts[r["risk_tier"]] = tier_counts.get(r["risk_tier"], 0) + 1
            tiers_found = 0
            for tier_name, count in tier_counts.items():
                if tier_name.lower() in action_lower and str(count) in action:
                    tiers_found += 1
            if tiers_found >= len(tier_counts):
                c6_score += 5
            elif tiers_found > 0:
                c6_score += 2

            # Check highest risk applicant
            if expected_queue:
                highest = expected_queue[0]
                if highest["full_name"].lower() in action_lower:
                    c6_score += 2
                if str(highest["risk_score"]) in action:
                    c6_score += 2

        eval_criteria["summary_response"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
        }
        if c6_score < c6_max:
            eval_criteria["summary_response"]["reason"] = (
                "Response should include: total screened, queue count, per-tier counts, highest-risk applicant"
            )

        # --- Aggregate ---
        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

        return total_score / max_score if max_score > 0 else 0.0, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.

        Consumes the hardened tool surface: unwraps MCP envelopes, parses
        JSON-encoded strings and Python-repr strings, walks Notion-style
        nested properties, parses key:value text, and follows
        has_more/next_cursor pagination.
        """
        import glob as globmod

        # Step 1: Read workspace config files
        with open(os.path.join(self.workspace, "risk_config.yaml"), 'r') as f:
            config = yaml.safe_load(f)

        severity_map = {}
        sev_path = os.path.join(self.workspace, "eviction_severity.csv")
        with open(sev_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                severity_map[row["reason"]] = float(row["severity_weight"])

        # Read income data from workspace
        income_data = {}
        for fp in sorted(globmod.glob(os.path.join(self.workspace, "applicant_income_*.json"))):
            with open(fp, 'r') as f:
                for rec in json.load(f):
                    income_data[rec["applicant_id"]] = rec

        # Read rent data from workspace
        rent_data = {}
        for fp in sorted(globmod.glob(os.path.join(self.workspace, "rental_listings_*.csv"))):
            with open(fp, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rent_data[int(row["property_id"])] = float(row["monthly_rent"])

        # Read reference verifications from workspace
        ref_verifications = {}
        for fp in sorted(globmod.glob(os.path.join(self.workspace, "reference_verification_*.txt"))):
            with open(fp, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("|")
                    ref_id = int(parts[0].split(":")[1].strip())
                    status = parts[2].split(":")[1].strip()
                    ref_verifications[ref_id] = status

        weights = config["weights"]
        cs = config["credit_scoring"]
        ir = config["income_ratio"]
        es = config["eviction_scoring"]
        rs = config["reference_scoring"]
        ref_date = datetime.strptime(config["reference_date"], "%Y-%m-%d")
        tiers_config = config["risk_tiers"]
        threshold = config["review_threshold"]

        # Step 2: List all applicants via tool (nested list, cursor pagination)
        all_applicants = []
        page = 1
        while True:
            result = self.tools["list_applicants"](page=page, page_size=20)
            for rec in result["results"]:
                props = rec["properties"]
                all_applicants.append({
                    "applicant_id": rec["id"],
                    "full_name": props["Name"]["title"][0]["plain_text"],
                    "property_id": props["Property"]["relation"][0]["id"],
                })
            if not result["has_more"]:
                break
            page = result["next_cursor"]

        # Step 3: For each applicant, gather data via tools
        results = []
        property_cache = {}

        for app in all_applicants:
            aid = app["applicant_id"]
            pid = app["property_id"]

            # Full applicant record (native nested dict)
            detail = self.tools["get_applicant_details"](applicant_id=aid)
            assert detail["object"] == "applicant"
            full_name = detail["properties"]["Name"]["title"][0]["plain_text"]

            # Get credit report via tool (JSON-encoded string of a nested record)
            cr_raw = self.tools["get_credit_report"](applicant_id=aid)
            cr_rec = json.loads(cr_raw)
            cr_props = cr_rec["properties"]
            credit_score = cr_props["Credit Score"]["number"]
            num_delinquencies = cr_props["Delinquent Accounts"]["number"]
            bankruptcy = cr_props["Bankruptcy On File"]["select"]["name"] == "yes"
            credit_utilization = cr_props["Credit Utilization"]["number"]

            # Credit sub-score
            credit_base = max(0, (cs["base_threshold"] - credit_score)) / cs["score_range"] * 100
            credit_sub = credit_base
            if bankruptcy:
                credit_sub += cs["bankruptcy_penalty"]
            credit_sub += min(num_delinquencies * cs["delinquency_penalty_per_item"],
                              cs["max_delinquency_penalty"])
            if credit_utilization > cs["high_utilization_threshold"]:
                credit_sub += cs["high_utilization_penalty"]
            credit_sub = min(credit_sub, 100)

            # Income ratio sub-score
            inc = income_data.get(aid, {})
            monthly_income = inc.get("monthly_income", 0) + inc.get("additional_income", 0)
            monthly_rent = rent_data.get(pid, 0)
            if monthly_rent > 0:
                ratio = monthly_income / monthly_rent
            else:
                ratio = 999
            if ratio >= ir["minimum_ratio"]:
                income_sub = 0
            else:
                income_sub = (ir["minimum_ratio"] - ratio) / ir["minimum_ratio"] * 100
            income_sub = min(income_sub, 100)

            # Check eviction history via tool (MCP envelope around a nested list)
            ev_env = self.tools["check_eviction_history"](applicant_id=aid)
            ev_payload = json.loads(ev_env["content"][0]["text"])
            evictions = ev_payload["results"]
            eviction_total = 0
            for ev in evictions:
                ev_props = ev["properties"]
                reason = ev_props["Reason"]["select"]["name"]
                ev_date_str = ev_props["Eviction Date"]["date"]["start"]
                sev = severity_map.get(reason, 0.5)
                ev_date = datetime.strptime(ev_date_str, "%Y-%m-%d")
                years_ago = (ref_date - ev_date).days / 365.25
                if years_ago <= es["recency_years"]:
                    mult = es["recency_multiplier"]
                else:
                    mult = 1.0
                eviction_total += sev * mult
            eviction_sub = min(eviction_total * es["base_scale_factor"], 100)

            # Get landlord references via tool (Python-repr string of a nested list)
            ref_raw = self.tools["get_landlord_references"](applicant_id=aid)
            ref_payload = ast.literal_eval(ref_raw)
            all_refs = []
            for rec in ref_payload["results"]:
                r_props = rec["properties"]
                all_refs.append({
                    "reference_id": rec["id"],
                    "payment_timeliness": r_props["Payment Timeliness"]["number"],
                    "property_care": r_props["Property Care"]["number"],
                    "lease_compliance": r_props["Lease Compliance"]["number"],
                    "would_rent_again": r_props["Would Rent Again"]["select"]["name"],
                })
            verified_refs = [r for r in all_refs if ref_verifications.get(r["reference_id"]) == "VERIFIED"]

            if not verified_refs:
                reference_sub = rs["no_references_score"]
                avg_ref_rating = None
            else:
                ref_means = []
                penalty = 0
                for r in verified_refs:
                    mean_r = (r["payment_timeliness"] + r["property_care"] + r["lease_compliance"]) / 3
                    ref_means.append(mean_r)
                    if r["would_rent_again"] == "no":
                        penalty += rs["would_not_rent_again_penalty"]
                    elif r["would_rent_again"] == "maybe":
                        penalty += rs["uncertain_recommendation_penalty"]
                avg_ref_rating = sum(ref_means) / len(ref_means)
                reference_sub = (5 - avg_ref_rating) / 5 * 60 + penalty
                reference_sub = min(reference_sub, 100)

            # Get property details via tool (plain key:value text)
            if pid not in property_cache:
                prop_raw = self.tools["get_property_details"](property_id=pid)
                prop = {}
                for line in prop_raw.split("\n"):
                    k, v = line.split(": ", 1)
                    prop[k] = v
                property_cache[pid] = prop

            # Final risk score
            risk_score = (
                weights["credit"] * credit_sub +
                weights["income_ratio"] * income_sub +
                weights["eviction"] * eviction_sub +
                weights["references"] * reference_sub
            )
            risk_score = round(risk_score, 2)

            # Risk tier
            risk_tier = "Low"
            for tier_name in ["Critical", "High", "Moderate", "Low"]:
                if risk_score >= tiers_config[tier_name]:
                    risk_tier = tier_name
                    break

            # Primary flag
            components = {
                "credit": credit_sub,
                "eviction": eviction_sub,
                "income_ratio": income_sub,
                "references": reference_sub,
            }
            max_val = max(components.values())
            primary_flags = sorted([k for k, v in components.items() if v == max_val])
            primary_flag = primary_flags[0]

            results.append({
                "applicant_id": aid,
                "full_name": full_name,
                "risk_score": risk_score,
                "risk_tier": risk_tier,
                "primary_flag": primary_flag,
                "credit_score": credit_score,
                "income_to_rent_ratio": round(ratio, 2),
                "eviction_count": len(evictions),
                "avg_reference_rating": round(avg_ref_rating, 2) if avg_ref_rating is not None else "N/A",
            })

        # Sort: risk_score DESC, applicant_id ASC
        results.sort(key=lambda x: (-x["risk_score"], x["applicant_id"]))

        # Filter to review queue
        queue = [r for r in results if r["risk_score"] >= threshold]

        # Write review_queue.csv
        queue_path = os.path.join(self.workspace, "review_queue.csv")
        cols = [
            "applicant_id", "full_name", "risk_score", "risk_tier", "primary_flag",
            "credit_score", "income_to_rent_ratio", "eviction_count", "avg_reference_rating"
        ]
        with open(queue_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for r in queue:
                writer.writerow(r)

        # Build summary response
        total_applicants = len(results)
        queue_count = len(queue)
        tier_counts = {}
        for r in results:
            tier_counts[r["risk_tier"]] = tier_counts.get(r["risk_tier"], 0) + 1

        highest = queue[0] if queue else None
        tier_summary = ", ".join(f"{t}: {c}" for t, c in sorted(tier_counts.items()))

        action = (
            f"Screening complete. Total applicants screened: {total_applicants}. "
            f"Applicants placed in review queue: {queue_count}. "
            f"Risk tier distribution across all applicants - {tier_summary}. "
        )
        if highest:
            action += (
                f"The highest-risk applicant is {highest['full_name']} "
                f"with a risk score of {highest['risk_score']}."
            )

        return self.step(action)
