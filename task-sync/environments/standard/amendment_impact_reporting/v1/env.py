"""
Environment for the Contract Amendment Impact Report task.
Provides tools for querying MSA clauses, change orders, vendor certifications,
and milestone payments, plus evaluation logic.
"""

import csv
import io
import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Tuple


# ---------------------------------------------------------------------------
# Tool decorator
# ---------------------------------------------------------------------------
def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ---------------------------------------------------------------------------
# Task_Env
# ---------------------------------------------------------------------------
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

    # ===================================================================== #
    #  Helper: DB query                                                      #
    # ===================================================================== #
    def _query(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    # ===================================================================== #
    #  Tools                                                                 #
    # ===================================================================== #

    @tool(
        description=(
            "List all contract IDs in the system, paginated. "
            "Returns a page of contract IDs along with contract names and vendor IDs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page. Default 10.",
                },
            },
            "required": ["page"],
        },
    )
    def list_contracts(self, page: int, page_size: int = 10) -> dict:
        offset = (page - 1) * page_size
        total = self._query("SELECT COUNT(*) AS cnt FROM contracts")[0]["cnt"]
        rows = self._query(
            "SELECT contract_id, contract_name, vendor_id FROM contracts "
            "ORDER BY contract_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        return {"contracts": rows, "page": page, "page_size": page_size, "total": total}

    @tool(
        description=(
            "Retrieve MSA clauses for a given contract. Returns clause details "
            "including clause_number, clause_type, amendment_threshold, "
            "compliance_category, and requires_signatory_level. Paginated."
        ),
        parameters={
            "type": "object",
            "properties": {
                "contract_id": {
                    "type": "string",
                    "description": "The contract ID to look up clauses for.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page. Default 5.",
                },
            },
            "required": ["contract_id", "page"],
        },
    )
    def get_contract_clauses(self, contract_id: str, page: int, page_size: int = 5) -> dict:
        offset = (page - 1) * page_size
        total = self._query(
            "SELECT COUNT(*) AS cnt FROM msa_clauses WHERE contract_id = ?",
            (contract_id,),
        )[0]["cnt"]
        rows = self._query(
            "SELECT clause_id, contract_id, clause_number, clause_type, "
            "amendment_threshold, compliance_category, requires_signatory_level "
            "FROM msa_clauses WHERE contract_id = ? ORDER BY clause_id LIMIT ? OFFSET ?",
            (contract_id, page_size, offset),
        )
        return {"clauses": rows, "page": page, "page_size": page_size, "total": total}

    @tool(
        description=(
            "List change orders filtered by contract ID and/or status. "
            "Returns order_id, contract_id, clause_id, cost_impact, "
            "schedule_impact_days, priority, status, and submission_date. Paginated."
        ),
        parameters={
            "type": "object",
            "properties": {
                "contract_id": {
                    "type": "string",
                    "description": "Filter by contract ID. Optional.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status (active, pending_review, approved, rejected). Optional.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page. Default 5.",
                },
            },
            "required": ["page"],
        },
    )
    def list_change_orders(self, page: int, contract_id: str = None,
                           status: str = None, page_size: int = 5) -> dict:
        conditions = []
        params = []
        if contract_id:
            conditions.append("contract_id = ?")
            params.append(contract_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = " AND ".join(conditions) if conditions else "1=1"
        total = self._query(
            f"SELECT COUNT(*) AS cnt FROM change_orders WHERE {where}", tuple(params)
        )[0]["cnt"]
        params_q = params + [page_size, (page - 1) * page_size]
        rows = self._query(
            f"SELECT order_id, contract_id, clause_id, requested_by, "
            f"change_description, cost_impact, schedule_impact_days, priority, "
            f"status, submission_date "
            f"FROM change_orders WHERE {where} ORDER BY order_id "
            f"LIMIT ? OFFSET ?",
            tuple(params_q),
        )
        return {"change_orders": rows, "page": page, "page_size": page_size, "total": total}

    @tool(
        description=(
            "Get detailed information about a single change order by its ID."
        ),
        parameters={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The change order ID.",
                },
            },
            "required": ["order_id"],
        },
    )
    def get_change_order(self, order_id: str) -> dict:
        rows = self._query(
            "SELECT * FROM change_orders WHERE order_id = ?", (order_id,)
        )
        if not rows:
            return {"error": f"Change order {order_id} not found."}
        return rows[0]

    @tool(
        description=(
            "Retrieve vendor information by vendor ID, including signatory details."
        ),
        parameters={
            "type": "object",
            "properties": {
                "vendor_id": {
                    "type": "string",
                    "description": "The vendor ID.",
                },
            },
            "required": ["vendor_id"],
        },
    )
    def get_vendor_info(self, vendor_id: str) -> dict:
        rows = self._query(
            "SELECT * FROM vendors WHERE vendor_id = ?", (vendor_id,)
        )
        if not rows:
            return {"error": f"Vendor {vendor_id} not found."}
        return rows[0]

    @tool(
        description=(
            "Check a vendor's certification status for a specific compliance "
            "category. Returns the most recent certification record for that "
            "vendor and category, including expiry_date and certification_level."
        ),
        parameters={
            "type": "object",
            "properties": {
                "vendor_id": {
                    "type": "string",
                    "description": "The vendor ID.",
                },
                "compliance_category": {
                    "type": "string",
                    "description": "The compliance category (financial, operational, legal, safety).",
                },
            },
            "required": ["vendor_id", "compliance_category"],
        },
    )
    def check_vendor_certification(self, vendor_id: str, compliance_category: str) -> dict:
        rows = self._query(
            "SELECT * FROM vendor_certifications "
            "WHERE vendor_id = ? AND compliance_category = ? "
            "ORDER BY expiry_date DESC LIMIT 1",
            (vendor_id, compliance_category),
        )
        if not rows:
            return {
                "vendor_id": vendor_id,
                "compliance_category": compliance_category,
                "certified": False,
                "reason": "No certification found for this vendor and category.",
            }
        cert = rows[0]
        return cert

    @tool(
        description=(
            "Get milestone payments for a contract, optionally filtered by status. "
            "Returns payment details including linked_clause_id. Paginated."
        ),
        parameters={
            "type": "object",
            "properties": {
                "contract_id": {
                    "type": "string",
                    "description": "The contract ID.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by payment status (scheduled, paid, overdue, disputed). Optional.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page. Default 5.",
                },
            },
            "required": ["contract_id", "page"],
        },
    )
    def get_milestone_payments(self, contract_id: str, page: int,
                               status: str = None, page_size: int = 5) -> dict:
        conditions = ["contract_id = ?"]
        params = [contract_id]
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = " AND ".join(conditions)
        total = self._query(
            f"SELECT COUNT(*) AS cnt FROM milestone_payments WHERE {where}",
            tuple(params),
        )[0]["cnt"]
        params_q = params + [page_size, (page - 1) * page_size]
        rows = self._query(
            f"SELECT payment_id, contract_id, milestone_name, milestone_number, "
            f"due_date, amount, status, linked_clause_id "
            f"FROM milestone_payments WHERE {where} ORDER BY payment_id "
            f"LIMIT ? OFFSET ?",
            tuple(params_q),
        )
        return {"payments": rows, "page": page, "page_size": page_size, "total": total}

    @tool(
        description=(
            "Look up a specific MSA clause by its clause ID. Returns full clause "
            "details including clause_text."
        ),
        parameters={
            "type": "object",
            "properties": {
                "clause_id": {
                    "type": "string",
                    "description": "The clause ID.",
                },
            },
            "required": ["clause_id"],
        },
    )
    def get_clause_details(self, clause_id: str) -> dict:
        rows = self._query(
            "SELECT * FROM msa_clauses WHERE clause_id = ?", (clause_id,)
        )
        if not rows:
            return {"error": f"Clause {clause_id} not found."}
        return rows[0]

    # ===================================================================== #
    #  step – Evaluation                                                     #
    # ===================================================================== #

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        ground = self._compute_ground_truth()
        criteria = {}
        total = 0
        max_total = 0

        # --- Criterion 1: Report CSV exists with correct structure (10 pts) ---
        c1_max = 10
        c1_score = 0
        report_path = os.path.join(self.workspace, "amendment_impact_report.csv")
        report_rows = []
        expected_cols = [
            "order_id", "contract_id", "clause_number", "vendor_name",
            "change_description", "cost_impact", "non_compliance_types",
            "required_signatory_level", "vendor_signatory_name",
            "vendor_signatory_title",
        ]
        if os.path.exists(report_path):
            try:
                with open(report_path, "r") as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    report_rows = list(reader)
                if set(expected_cols).issubset(set(cols)):
                    c1_score = c1_max
                else:
                    missing = set(expected_cols) - set(cols)
                    c1_score = 5
                    criteria["report_structure"] = {
                        "passed": False, "score": c1_score, "max_score": c1_max,
                        "reason": f"Missing columns: {missing}",
                    }
            except Exception as e:
                criteria["report_structure"] = {
                    "passed": False, "score": 0, "max_score": c1_max,
                    "reason": f"Error reading CSV: {e}",
                }
        else:
            criteria["report_structure"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "amendment_impact_report.csv not found.",
            }
        if "report_structure" not in criteria:
            criteria["report_structure"] = {
                "passed": True, "score": c1_score, "max_score": c1_max,
            }
        total += c1_score
        max_total += c1_max

        # --- Criterion 2: All non-compliant orders identified (25 pts) ---
        c2_max = 25
        gt_ids = set(ground["non_compliant_order_ids"])
        report_ids = set(r["order_id"] for r in report_rows) if report_rows else set()
        if gt_ids and report_ids:
            precision = len(gt_ids & report_ids) / len(report_ids) if report_ids else 0
            recall = len(gt_ids & report_ids) / len(gt_ids) if gt_ids else 0
            f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0
            c2_score = round(c2_max * f1)
        elif not gt_ids and not report_ids:
            c2_score = c2_max
        else:
            c2_score = 0
        criteria["orders_identified"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": None if c2_score == c2_max else (
                f"Expected {len(gt_ids)} orders, got {len(report_ids)}. "
                f"Missing: {gt_ids - report_ids}, Extra: {report_ids - gt_ids}"
            ),
        }
        total += c2_score
        max_total += c2_max

        # --- Criterion 3: Non-compliance types correct (15 pts) ---
        c3_max = 15
        c3_correct = 0
        gt_types = ground["order_types"]  # {order_id: sorted list of types}
        if report_rows and gt_ids:
            for row in report_rows:
                oid = row.get("order_id", "")
                if oid in gt_types:
                    # Parse types from report: split by "; "
                    reported = sorted([t.strip() for t in row.get("non_compliance_types", "").split(";") if t.strip()])
                    expected = sorted(gt_types[oid])
                    if reported == expected:
                        c3_correct += 1
            c3_score = round(c3_max * c3_correct / len(gt_ids)) if gt_ids else c3_max
        elif not gt_ids:
            c3_score = c3_max
        else:
            c3_score = 0
        criteria["compliance_types"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": None if c3_score == c3_max else f"{c3_correct}/{len(gt_ids)} orders have correct types.",
        }
        total += c3_score
        max_total += c3_max

        # --- Criterion 4: Required signatory levels correct (15 pts) ---
        c4_max = 15
        c4_correct = 0
        gt_levels = ground["signatory_levels"]  # {order_id: int}
        if report_rows and gt_ids:
            for row in report_rows:
                oid = row.get("order_id", "")
                if oid in gt_levels:
                    try:
                        reported_level = int(row.get("required_signatory_level", -1))
                    except (ValueError, TypeError):
                        reported_level = -1
                    if reported_level == gt_levels[oid]:
                        c4_correct += 1
            c4_score = round(c4_max * c4_correct / len(gt_ids)) if gt_ids else c4_max
        elif not gt_ids:
            c4_score = c4_max
        else:
            c4_score = 0
        criteria["signatory_levels"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": None if c4_score == c4_max else f"{c4_correct}/{len(gt_ids)} orders have correct signatory level.",
        }
        total += c4_score
        max_total += c4_max

        # --- Criterion 5: Summary JSON correct (20 pts) ---
        c5_max = 20
        c5_score = 0
        summary_path = os.path.join(self.workspace, "non_compliance_summary.json")
        if os.path.exists(summary_path):
            try:
                with open(summary_path, "r") as f:
                    summary = json.load(f)
                gt_summary = ground["summary"]
                checks = 0
                total_checks = 4
                # total_non_compliant
                if summary.get("total_non_compliant") == gt_summary["total_non_compliant"]:
                    checks += 1
                # total_cost_impact (within 0.01)
                try:
                    if abs(float(summary.get("total_cost_impact", 0)) - gt_summary["total_cost_impact"]) < 0.02:
                        checks += 1
                except (ValueError, TypeError):
                    pass
                # highest_risk_order_id
                if summary.get("highest_risk_order_id") == gt_summary["highest_risk_order_id"]:
                    checks += 1
                # by_type
                gt_by_type = gt_summary["by_type"]
                s_by_type = summary.get("by_type", {})
                if s_by_type == gt_by_type:
                    checks += 1
                c5_score = round(c5_max * checks / total_checks)
            except Exception as e:
                criteria["summary_json"] = {
                    "passed": False, "score": 0, "max_score": c5_max,
                    "reason": f"Error reading summary: {e}",
                }
        else:
            criteria["summary_json"] = {
                "passed": False, "score": 0, "max_score": c5_max,
                "reason": "non_compliance_summary.json not found.",
            }
        if "summary_json" not in criteria:
            criteria["summary_json"] = {
                "passed": c5_score == c5_max,
                "score": c5_score,
                "max_score": c5_max,
                "reason": None if c5_score == c5_max else "Some summary fields are incorrect.",
            }
        total += c5_score
        max_total += c5_max

        # --- Criterion 6: Report sorted correctly (10 pts) ---
        c6_max = 10
        c6_score = 0
        if report_rows and len(report_rows) > 1:
            try:
                sorted_rows = sorted(
                    report_rows,
                    key=lambda r: (-float(r.get("cost_impact", 0)), r.get("order_id", "")),
                )
                if [r["order_id"] for r in report_rows] == [r["order_id"] for r in sorted_rows]:
                    c6_score = c6_max
            except (ValueError, TypeError):
                pass
        elif len(report_rows) <= 1:
            c6_score = c6_max
        criteria["report_sorting"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": None if c6_score == c6_max else "Report not sorted by cost_impact desc, order_id asc.",
        }
        total += c6_score
        max_total += c6_max

        # --- Criterion 7: Response contains key findings (10 pts) ---
        c7_max = 10
        c7_score = 0
        gt_summary = ground["summary"]
        if action:
            checks7 = 0
            # Check total count mentioned
            if str(gt_summary["total_non_compliant"]) in action:
                checks7 += 1
            # Check total cost impact (formatted)
            cost_str = f"{gt_summary['total_cost_impact']:.2f}"
            if cost_str in action:
                checks7 += 1
            # Check highest risk order mentioned
            if gt_summary["highest_risk_order_id"] in action:
                checks7 += 1
            c7_score = round(c7_max * checks7 / 3)
        criteria["response_findings"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": None if c7_score == c7_max else "Response missing some key findings.",
        }
        total += c7_score
        max_total += c7_max

        # Remove None reasons
        for k in criteria:
            if criteria[k].get("reason") is None:
                criteria[k].pop("reason", None)

        reward = total / max_total if max_total > 0 else 0.0
        info = {
            "eval_criteria": criteria,
            "total_score": total,
            "max_score": max_total,
        }
        return reward, info

    # ===================================================================== #
    #  Ground truth computation                                              #
    # ===================================================================== #

    def _load_yaml_simple(self, path: str) -> Any:
        """Minimal YAML-like parser for our simple config files."""
        # For compliance_rules.yaml we need nested dict parsing
        result = {}
        current_key = None
        current_dict = None
        with open(path, "r") as f:
            for line in f:
                stripped = line.rstrip()
                if not stripped or stripped.startswith("#"):
                    continue
                # Top-level key with value
                if not line.startswith(" ") and not line.startswith("\t"):
                    if ":" in stripped:
                        key, _, val = stripped.partition(":")
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if val == "":
                            result[key] = {}
                            current_key = key
                            current_dict = result[key]
                        elif val.startswith("["):
                            # List
                            items = val.strip("[]").split(",")
                            result[key] = [i.strip().strip('"').strip("'") for i in items if i.strip()]
                            current_key = None
                            current_dict = None
                        else:
                            try:
                                result[key] = int(val)
                            except ValueError:
                                try:
                                    result[key] = float(val)
                                except ValueError:
                                    result[key] = val
                            current_key = None
                            current_dict = None
                elif current_dict is not None:
                    # Nested key under current_key
                    # Handle list items
                    if stripped.strip().startswith("- "):
                        item = stripped.strip()[2:].strip().strip('"').strip("'")
                        if not isinstance(current_dict, list):
                            result[current_key] = []
                            current_dict = result[current_key]
                        current_dict.append(item)
                    elif ":" in stripped:
                        key, _, val = stripped.strip().partition(":")
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if isinstance(current_dict, dict):
                            try:
                                current_dict[key] = int(val)
                            except ValueError:
                                try:
                                    current_dict[key] = float(val)
                                except ValueError:
                                    current_dict[key] = val
        return result

    def _load_amendment_history(self) -> Dict[str, Dict]:
        """Load amendment history from all YAML files in workspace."""
        history = {}  # contract_id -> {prior_amendments, ...}
        import glob
        for path in sorted(glob.glob(os.path.join(self.workspace, "amendment_history_*.yaml"))):
            with open(path, "r") as f:
                content = f.read()
            # Parse simple YAML list
            current = {}
            for line in content.split("\n"):
                line = line.rstrip()
                if not line:
                    continue
                if line.startswith("- "):
                    if current and "contract_id" in current:
                        history[current["contract_id"]] = current
                    current = {}
                    key, _, val = line[2:].partition(":")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    try:
                        current[key] = int(val)
                    except ValueError:
                        try:
                            current[key] = float(val)
                        except ValueError:
                            current[key] = val
                elif ":" in line:
                    key, _, val = line.strip().partition(":")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    try:
                        current[key] = int(val)
                    except ValueError:
                        try:
                            current[key] = float(val)
                        except ValueError:
                            current[key] = val
            if current and "contract_id" in current:
                history[current["contract_id"]] = current
        return history

    def _load_change_order_notes(self) -> Dict[str, Dict]:
        """Load change order notes from all JSON files in workspace."""
        notes = {}  # order_id -> note dict
        import glob
        for path in sorted(glob.glob(os.path.join(self.workspace, "change_order_notes_*.json"))):
            with open(path, "r") as f:
                data = json.load(f)
            for note in data:
                notes[note["order_id"]] = note
        return notes

    def _load_vendor_audits(self) -> Dict[str, Dict]:
        """Load vendor audit info from all TXT files in workspace."""
        audits = {}  # vendor_id -> audit dict
        import glob
        for path in sorted(glob.glob(os.path.join(self.workspace, "vendor_audit_*.txt"))):
            with open(path, "r") as f:
                content = f.read()
            blocks = content.split("---")
            for block in blocks:
                block = block.strip()
                if not block:
                    continue
                audit = {}
                for line in block.split("\n"):
                    if ":" in line:
                        key, _, val = line.partition(":")
                        key = key.strip()
                        val = val.strip()
                        audit[key] = val
                if "Vendor ID" in audit:
                    vid = audit["Vendor ID"]
                    audits[vid] = {
                        "vendor_id": vid,
                        "vendor_name": audit.get("Vendor Name", ""),
                        "penalty_flag": audit.get("Penalty Flag", "No") == "Yes",
                        "audit_score": int(audit.get("Audit Score", "0").split("/")[0]) if "Audit Score" in audit else 0,
                    }
        return audits

    def _compute_ground_truth(self) -> Dict[str, Any]:
        """Compute the full ground truth for evaluation."""
        # Load config files
        rules_path = os.path.join(self.workspace, "compliance_rules.yaml")
        rules = self._load_yaml_simple(rules_path)
        matrix_path = os.path.join(self.workspace, "signatory_matrix.json")
        with open(matrix_path, "r") as f:
            sig_matrix = json.load(f)

        ref_date = datetime.strptime(str(rules.get("reference_date", "2026-04-22")), "%Y-%m-%d")
        max_schedule = rules.get("max_schedule_days", {})
        risk_threshold = int(rules.get("risk_threshold", 3))
        min_cert = rules.get("min_cert_level", {})
        escalation_threshold = int(rules.get("escalation_threshold", 3))

        # Load workspace data
        co_notes = self._load_change_order_notes()
        vendor_audits = self._load_vendor_audits()
        amendment_hist = self._load_amendment_history()

        # Load DB data
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        contracts = [dict(r) for r in conn.execute("SELECT * FROM contracts").fetchall()]
        contract_vendor = {c["contract_id"]: c["vendor_id"] for c in contracts}

        active_orders = [dict(r) for r in conn.execute(
            "SELECT * FROM change_orders WHERE status = 'active' ORDER BY order_id"
        ).fetchall()]

        clauses_all = [dict(r) for r in conn.execute("SELECT * FROM msa_clauses").fetchall()]
        clause_map = {cl["clause_id"]: cl for cl in clauses_all}

        vendors_all = [dict(r) for r in conn.execute("SELECT * FROM vendors").fetchall()]
        vendor_map = {v["vendor_id"]: v for v in vendors_all}

        # Build payment lookup: clause_id -> list of overdue payments
        overdue_payments = [dict(r) for r in conn.execute(
            "SELECT * FROM milestone_payments WHERE status = 'overdue'"
        ).fetchall()]
        clause_overdue = {}
        for p in overdue_payments:
            if p["linked_clause_id"]:
                clause_overdue.setdefault(p["linked_clause_id"], []).append(p)

        conn.close()

        # Evaluate each active change order
        non_compliant = []
        order_types = {}
        signatory_levels = {}

        for co in active_orders:
            oid = co["order_id"]
            cid = co["contract_id"]
            clause = clause_map.get(co["clause_id"], {})
            vid = contract_vendor.get(cid, "")
            vendor = vendor_map.get(vid, {})
            note = co_notes.get(oid, {})
            audit = vendor_audits.get(vid, {})
            hist = amendment_hist.get(cid, {})

            types = []

            # 1. Threshold breach
            if co["cost_impact"] > clause.get("amendment_threshold", float("inf")):
                cat = clause.get("compliance_category", "")
                # Check vendor certification
                cert_rows = self._query(
                    "SELECT * FROM vendor_certifications "
                    "WHERE vendor_id = ? AND compliance_category = ? "
                    "ORDER BY expiry_date DESC LIMIT 1",
                    (vid, cat),
                )
                if not cert_rows:
                    types.append("threshold_breach")
                else:
                    cert = cert_rows[0]
                    expiry = datetime.strptime(cert["expiry_date"], "%Y-%m-%d")
                    if expiry < ref_date:
                        types.append("threshold_breach")

            # 2. Schedule violation
            priority = co.get("priority", "")
            max_days = max_schedule.get(priority, 999)
            if isinstance(max_days, str):
                max_days = int(max_days)
            if co["schedule_impact_days"] > max_days:
                types.append("schedule_violation")

            # 3. Payment risk
            risk_rating = note.get("risk_rating", 0)
            if co["clause_id"] in clause_overdue and risk_rating >= risk_threshold:
                types.append("payment_risk")

            # 4. Certification gap
            if audit.get("penalty_flag", False):
                cat = clause.get("compliance_category", "")
                min_level = min_cert.get(cat, 0)
                if isinstance(min_level, str):
                    min_level = int(min_level)
                cert_rows = self._query(
                    "SELECT * FROM vendor_certifications "
                    "WHERE vendor_id = ? AND compliance_category = ? "
                    "ORDER BY expiry_date DESC LIMIT 1",
                    (vid, cat),
                )
                cert_level = 0
                if cert_rows:
                    cert_level = cert_rows[0]["certification_level"]
                if cert_level < min_level:
                    types.append("certification_gap")

            if types:
                non_compliant.append(co)
                order_types[oid] = sorted(types)

                # Determine signatory level
                cost = co["cost_impact"]
                base_level = 1
                for lvl in sig_matrix["levels"]:
                    mc = lvl["max_cost"]
                    if mc is None:
                        mc = float("inf")
                    if lvl["min_cost"] <= cost < mc:
                        base_level = lvl["required_level"]
                        break

                # Escalation
                prior = hist.get("prior_amendments", 0)
                if prior > escalation_threshold:
                    base_level = min(base_level + 1, 4)

                # Legal review
                if note.get("requires_legal_review", False):
                    base_level = max(base_level, 3)

                base_level = min(base_level, 4)
                signatory_levels[oid] = base_level

        # Sort by cost_impact desc, order_id asc
        non_compliant.sort(key=lambda x: (-x["cost_impact"], x["order_id"]))

        # Summary
        total_cost = sum(co["cost_impact"] for co in non_compliant)
        by_type = {}
        for types_list in order_types.values():
            for t in types_list:
                by_type[t] = by_type.get(t, 0) + 1

        highest_risk_oid = non_compliant[0]["order_id"] if non_compliant else ""

        return {
            "non_compliant_order_ids": [co["order_id"] for co in non_compliant],
            "order_types": order_types,
            "signatory_levels": signatory_levels,
            "non_compliant_orders": non_compliant,
            "summary": {
                "total_non_compliant": len(non_compliant),
                "total_cost_impact": round(total_cost, 2),
                "highest_risk_order_id": highest_risk_oid,
                "by_type": by_type,
            },
        }

    # ===================================================================== #
    #  verify – End-to-end solvability proof                                 #
    # ===================================================================== #

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import glob

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # --- Step 1: Read config files from workspace ---
        rules = self._load_yaml_simple(os.path.join(self.workspace, "compliance_rules.yaml"))
        with open(os.path.join(self.workspace, "signatory_matrix.json"), "r") as f:
            sig_matrix = json.load(f)

        ref_date = datetime.strptime(str(rules.get("reference_date", "2026-04-22")), "%Y-%m-%d")
        max_schedule = rules.get("max_schedule_days", {})
        risk_threshold = int(rules.get("risk_threshold", 3))
        min_cert = rules.get("min_cert_level", {})
        escalation_threshold = int(rules.get("escalation_threshold", 3))

        # Load workspace data files
        co_notes = self._load_change_order_notes()
        vendor_audits = self._load_vendor_audits()
        amendment_hist = self._load_amendment_history()

        # --- Step 2: Get all contracts via tool ---
        all_contracts = []
        page = 1
        while True:
            result = call_tool("list_contracts", page=page, page_size=10)
            all_contracts.extend(result["contracts"])
            if page * 10 >= result["total"]:
                break
            page += 1

        # --- Step 3: For each contract, get clauses and active change orders ---
        all_clauses = {}  # clause_id -> clause
        all_active_orders = []  # list of change orders
        contract_vendor_map = {c["contract_id"]: c["vendor_id"] for c in all_contracts}

        for contract in all_contracts:
            cid = contract["contract_id"]

            # Get clauses
            page = 1
            while True:
                result = call_tool("get_contract_clauses", contract_id=cid, page=page, page_size=5)
                for cl in result["clauses"]:
                    all_clauses[cl["clause_id"]] = cl
                if page * 5 >= result["total"]:
                    break
                page += 1

            # Get active change orders
            page = 1
            while True:
                result = call_tool("list_change_orders", contract_id=cid, status="active", page=page, page_size=5)
                all_active_orders.extend(result["change_orders"])
                if page * 5 >= result["total"]:
                    break
                page += 1

        # --- Step 4: Get milestone payments (overdue) for each contract ---
        clause_overdue = {}  # clause_id -> True
        for contract in all_contracts:
            cid = contract["contract_id"]
            page = 1
            while True:
                result = call_tool("get_milestone_payments", contract_id=cid, status="overdue", page=page, page_size=5)
                for p in result["payments"]:
                    if p["linked_clause_id"]:
                        clause_overdue[p["linked_clause_id"]] = True
                if page * 5 >= result["total"]:
                    break
                page += 1

        # --- Step 5: Evaluate each active change order for non-compliance ---
        non_compliant = []

        for co in all_active_orders:
            oid = co["order_id"]
            cid = co["contract_id"]
            clause_id = co["clause_id"]
            clause = all_clauses.get(clause_id)
            if not clause:
                # Fetch clause if missing
                clause = call_tool("get_clause_details", clause_id=clause_id)
                all_clauses[clause_id] = clause

            vid = contract_vendor_map.get(cid, "")
            note = co_notes.get(oid, {})
            audit = vendor_audits.get(vid, {})
            hist = amendment_hist.get(cid, {})

            types = []

            # 1. Threshold breach
            if co["cost_impact"] > clause.get("amendment_threshold", float("inf")):
                cat = clause.get("compliance_category", "")
                cert_result = call_tool("check_vendor_certification",
                                        vendor_id=vid, compliance_category=cat)
                if "certified" in cert_result and not cert_result["certified"]:
                    types.append("threshold_breach")
                elif "expiry_date" in cert_result:
                    expiry = datetime.strptime(cert_result["expiry_date"], "%Y-%m-%d")
                    if expiry < ref_date:
                        types.append("threshold_breach")

            # 2. Schedule violation
            priority = co.get("priority", "")
            max_days = max_schedule.get(priority, 999)
            if isinstance(max_days, str):
                max_days = int(max_days)
            if co["schedule_impact_days"] > max_days:
                types.append("schedule_violation")

            # 3. Payment risk
            risk_rating = note.get("risk_rating", 0)
            if clause_id in clause_overdue and risk_rating >= risk_threshold:
                types.append("payment_risk")

            # 4. Certification gap
            if audit.get("penalty_flag", False):
                cat = clause.get("compliance_category", "")
                min_level = min_cert.get(cat, 0)
                if isinstance(min_level, str):
                    min_level = int(min_level)
                cert_result = call_tool("check_vendor_certification",
                                        vendor_id=vid, compliance_category=cat)
                cert_level = 0
                if "certification_level" in cert_result:
                    cert_level = cert_result["certification_level"]
                if cert_level < min_level:
                    types.append("certification_gap")

            if types:
                # Get vendor info for signatory details
                vendor_info = call_tool("get_vendor_info", vendor_id=vid)

                # Determine signatory level
                cost = co["cost_impact"]
                base_level = 1
                for lvl in sig_matrix["levels"]:
                    mc = lvl["max_cost"]
                    if mc is None:
                        mc = float("inf")
                    if lvl["min_cost"] <= cost < mc:
                        base_level = lvl["required_level"]
                        break

                prior = hist.get("prior_amendments", 0)
                if prior > escalation_threshold:
                    base_level = min(base_level + 1, 4)

                if note.get("requires_legal_review", False):
                    base_level = max(base_level, 3)

                base_level = min(base_level, 4)

                non_compliant.append({
                    "order_id": oid,
                    "contract_id": cid,
                    "clause_number": clause.get("clause_number", ""),
                    "vendor_name": vendor_info.get("vendor_name", ""),
                    "change_description": co.get("change_description", ""),
                    "cost_impact": f"{co['cost_impact']:.2f}",
                    "non_compliance_types": "; ".join(sorted(types)),
                    "required_signatory_level": base_level,
                    "vendor_signatory_name": vendor_info.get("signatory_name", ""),
                    "vendor_signatory_title": vendor_info.get("signatory_title", ""),
                })

        # Sort by cost_impact desc, order_id asc
        non_compliant.sort(key=lambda x: (-float(x["cost_impact"]), x["order_id"]))

        # --- Step 6: Write deliverables ---
        # amendment_impact_report.csv
        report_path = os.path.join(self.workspace, "amendment_impact_report.csv")
        fieldnames = [
            "order_id", "contract_id", "clause_number", "vendor_name",
            "change_description", "cost_impact", "non_compliance_types",
            "required_signatory_level", "vendor_signatory_name",
            "vendor_signatory_title",
        ]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(non_compliant)

        # non_compliance_summary.json
        total_cost = sum(float(r["cost_impact"]) for r in non_compliant)
        by_type = {}
        for r in non_compliant:
            for t in r["non_compliance_types"].split("; "):
                t = t.strip()
                if t:
                    by_type[t] = by_type.get(t, 0) + 1

        highest_risk_oid = non_compliant[0]["order_id"] if non_compliant else ""
        summary = {
            "total_non_compliant": len(non_compliant),
            "total_cost_impact": round(total_cost, 2),
            "highest_risk_order_id": highest_risk_oid,
            "by_type": by_type,
        }
        summary_path = os.path.join(self.workspace, "non_compliance_summary.json")
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        # --- Step 7: Construct action string ---
        action = (
            f"The contract amendment impact analysis identified "
            f"{len(non_compliant)} non-compliant active change orders "
            f"with a total cost impact of {total_cost:.2f}. "
            f"The highest-risk change order is {highest_risk_oid}. "
            f"Non-compliance breakdown by type: "
            + ", ".join(f"{k}: {v}" for k, v in sorted(by_type.items()))
            + ". "
            f"The full report has been saved to amendment_impact_report.csv "
            f"and the summary to non_compliance_summary.json."
        )

        print(f"[verify] Tool calls made: {tool_call_count}")
        return self.step(action)
