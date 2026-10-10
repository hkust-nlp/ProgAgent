"""
Aircraft De-Icing Invoice Reconciliation - Task Environment

Provides tools for querying de-icing service data and evaluates
the agent's reconciliation of invoices against actual operations.
"""

import csv
import glob
import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Tuple

import yaml


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


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

    # ----------------------------------------------------------------
    # Tool methods
    # ----------------------------------------------------------------

    @tool(
        description="List invoices with pagination. Returns a page of invoice summaries sorted by invoice_id. Each entry includes invoice_id, service_id, provider_id, fluid_type, charged_quantity, charged_rate, total_charge, invoice_date, and status.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of invoices per page (max 25)",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_invoices(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 25)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM invoices")
        total = cur.fetchone()["cnt"]
        cur.execute(
            "SELECT * FROM invoices ORDER BY invoice_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total_invoices": total,
            "total_pages": (total + page_size - 1) // page_size,
            "invoices": rows,
        }

    @tool(
        description="Get detailed information for a specific invoice by its invoice_id.",
        parameters={
            "type": "object",
            "properties": {
                "invoice_id": {
                    "type": "string",
                    "description": "The invoice identifier, e.g. INV00001",
                },
            },
            "required": ["invoice_id"],
        },
    )
    def get_invoice(self, invoice_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Invoice {invoice_id} not found"}

    @tool(
        description="Get the de-icing service record for a given service_id. Returns flight_id, truck_id, fluid_type, fluid_quantity_liters, service_start, service_end, temperature_c, provider_id, and date.",
        parameters={
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "string",
                    "description": "The service identifier, e.g. SVC00001",
                },
            },
            "required": ["service_id"],
        },
    )
    def get_service_record(self, service_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM deicing_services WHERE service_id = ?", (service_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Service {service_id} not found"}

    @tool(
        description="Get flight information including scheduled departure and actual pushback time for a given flight_id.",
        parameters={
            "type": "object",
            "properties": {
                "flight_id": {
                    "type": "string",
                    "description": "The flight identifier, e.g. FL00001",
                },
            },
            "required": ["flight_id"],
        },
    )
    def get_flight_info(self, flight_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM flights WHERE flight_id = ?", (flight_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Flight {flight_id} not found"}

    @tool(
        description="Get provider details by provider_id, including provider name and contract ID.",
        parameters={
            "type": "object",
            "properties": {
                "provider_id": {
                    "type": "string",
                    "description": "The provider identifier, e.g. P001",
                },
            },
            "required": ["provider_id"],
        },
    )
    def get_provider_info(self, provider_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM providers WHERE provider_id = ?", (provider_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Provider {provider_id} not found"}

    @tool(
        description="Get truck details by truck_id, including provider_id, fluid_type capability, capacity, and maintenance date.",
        parameters={
            "type": "object",
            "properties": {
                "truck_id": {
                    "type": "string",
                    "description": "The truck identifier, e.g. T0001",
                },
            },
            "required": ["truck_id"],
        },
    )
    def get_truck_info(self, truck_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM deicing_trucks WHERE truck_id = ?", (truck_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Truck {truck_id} not found"}

    @tool(
        description="List all services for a given date. Returns a list of service summaries with service_id, flight_id, truck_id, provider_id, fluid_type, and fluid_quantity_liters.",
        parameters={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format",
                },
            },
            "required": ["date"],
        },
    )
    def list_services_by_date(self, date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT service_id, flight_id, truck_id, provider_id, fluid_type, fluid_quantity_liters "
            "FROM deicing_services WHERE date = ? ORDER BY service_id",
            (date,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"date": date, "count": len(rows), "services": rows}

    @tool(
        description="Search invoices by provider_id with pagination. Returns invoices for the specified provider.",
        parameters={
            "type": "object",
            "properties": {
                "provider_id": {
                    "type": "string",
                    "description": "The provider identifier to filter by",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of invoices per page (max 25)",
                },
            },
            "required": ["provider_id", "page", "page_size"],
        },
    )
    def search_invoices_by_provider(self, provider_id: str, page: int, page_size: int) -> dict:
        page_size = min(page_size, 25)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) as cnt FROM invoices WHERE provider_id = ?",
            (provider_id,),
        )
        total = cur.fetchone()["cnt"]
        cur.execute(
            "SELECT * FROM invoices WHERE provider_id = ? ORDER BY invoice_id LIMIT ? OFFSET ?",
            (provider_id, page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "provider_id": provider_id,
            "page": page,
            "page_size": page_size,
            "total_invoices": total,
            "total_pages": (total + page_size - 1) // page_size,
            "invoices": rows,
        }

    # ----------------------------------------------------------------
    # Evaluation
    # ----------------------------------------------------------------

    def _compute_ground_truth(self):
        """Compute all discrepancies and approved amounts from the database and workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Load contract rates from workspace
        rates_path = os.path.join(self.workspace, "contract_rates.json")
        with open(rates_path) as f:
            contract_rates_data = json.load(f)
        contract_rates = {}
        for pid, info in contract_rates_data.items():
            contract_rates[pid] = {}
            for ft, rate_info in info["rates"].items():
                contract_rates[pid][ft] = rate_info["rate_per_liter"]

        # Load validation policy from workspace
        policy_path = os.path.join(self.workspace, "validation_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)
        qty_tol = policy["validation_rules"]["quantity_tolerance_pct"]
        rate_tol = policy["validation_rules"]["rate_tolerance_pct"]

        # Load truck logs from workspace to get actual dispensed quantities
        truck_logs = {}
        for fpath in glob.glob(os.path.join(self.workspace, "truck_fluid_log_*.csv")):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    truck_logs[row["service_id"]] = {
                        "dispensed_liters": float(row["dispensed_liters"]),
                        "truck_id": row["truck_id"],
                        "fluid_type": row["fluid_type"],
                        "start_time": row["start_time"],
                        "end_time": row["end_time"],
                    }

        # Get all invoices
        cur.execute("SELECT * FROM invoices ORDER BY invoice_id")
        all_invoices = [dict(r) for r in cur.fetchall()]

        # Get all services
        cur.execute("SELECT * FROM deicing_services")
        all_services = {r["service_id"]: dict(r) for r in cur.fetchall()}

        # Get all flights
        cur.execute("SELECT * FROM flights")
        all_flights = {r["flight_id"]: dict(r) for r in cur.fetchall()}

        # Load temperature brackets
        temp_brackets = [
            {"min_temp_c": -40, "max_temp_c": -20, "required_fluid": "Type IV"},
            {"min_temp_c": -20, "max_temp_c": -5, "required_fluid": "Type II"},
            {"min_temp_c": -5, "max_temp_c": 5, "required_fluid": "Type I"},
        ]

        conn.close()

        # Detect discrepancies
        discrepancies = []
        approved_payments = []
        seen_services = {}  # service_id -> first invoice_id (for duplicate detection)

        for inv in all_invoices:
            inv_id = inv["invoice_id"]
            svc_id = inv["service_id"]
            pid = inv["provider_id"]
            fluid_type = inv["fluid_type"]
            charged_qty = inv["charged_quantity"]
            charged_rate = inv["charged_rate"]
            total_charge = inv["total_charge"]

            flags = []

            # Check for duplicate billing
            if svc_id in seen_services:
                flags.append({
                    "type": "duplicate_billing",
                    "detail": f"Duplicate of {seen_services[svc_id]} for service {svc_id}",
                    "charged_value": str(total_charge),
                    "expected_value": "0.00",
                    "difference": str(total_charge),
                })
            else:
                seen_services[svc_id] = inv_id

            # Get actual dispensed quantity from truck logs
            actual_qty = None
            if svc_id in truck_logs:
                actual_qty = truck_logs[svc_id]["dispensed_liters"]

                # Quantity overcharge check
                if actual_qty > 0:
                    pct_diff = ((charged_qty - actual_qty) / actual_qty) * 100
                    if pct_diff > qty_tol:
                        flags.append({
                            "type": "quantity_overcharge",
                            "detail": f"Charged {charged_qty}L vs actual {actual_qty}L ({pct_diff:.1f}% over)",
                            "charged_value": str(charged_qty),
                            "expected_value": str(actual_qty),
                            "difference": str(round(charged_qty - actual_qty, 2)),
                        })

            # Rate mismatch check
            if pid in contract_rates and fluid_type in contract_rates[pid]:
                correct_rate = contract_rates[pid][fluid_type]
                if rate_tol == 0:
                    rate_mismatch = abs(charged_rate - correct_rate) > 0.001
                else:
                    rate_mismatch = abs(charged_rate - correct_rate) / correct_rate * 100 > rate_tol
                if rate_mismatch:
                    flags.append({
                        "type": "rate_mismatch",
                        "detail": f"Charged rate ${charged_rate}/L vs contracted ${correct_rate}/L",
                        "charged_value": str(charged_rate),
                        "expected_value": str(correct_rate),
                        "difference": str(round(charged_rate - correct_rate, 2)),
                    })

            # Time anomaly check: service end after pushback
            if svc_id in all_services:
                svc = all_services[svc_id]
                fid = svc["flight_id"]
                if fid in all_flights:
                    flight = all_flights[fid]
                    svc_end = datetime.fromisoformat(svc["service_end"])
                    pushback = datetime.fromisoformat(flight["actual_pushback"])
                    if svc_end > pushback:
                        flags.append({
                            "type": "time_anomaly",
                            "detail": f"Service ended {svc_end.isoformat()} after pushback {pushback.isoformat()}",
                            "charged_value": svc["service_end"],
                            "expected_value": flight["actual_pushback"],
                            "difference": str(int((svc_end - pushback).total_seconds() // 60)) + " minutes",
                        })

            # Determine status and approved amount
            if flags:
                status = "flagged"
                # For approved amount: use correct values
                if any(f["type"] == "duplicate_billing" for f in flags):
                    approved_qty = 0.0
                    approved_rate = 0.0
                    approved_amount = 0.0
                else:
                    approved_qty = actual_qty if actual_qty is not None else charged_qty
                    if pid in contract_rates and fluid_type in contract_rates[pid]:
                        approved_rate = contract_rates[pid][fluid_type]
                    else:
                        approved_rate = charged_rate
                    approved_amount = round(approved_qty * approved_rate, 2)
            else:
                status = "approved"
                approved_qty = charged_qty
                approved_rate = charged_rate
                approved_amount = total_charge

            # Get provider name
            pname = ""
            for pid_key, info in contract_rates_data.items():
                if pid_key == pid:
                    pname = info["provider_name"]
                    break

            approved_payments.append({
                "invoice_id": inv_id,
                "service_id": svc_id,
                "provider_name": pname,
                "flight_id": all_services[svc_id]["flight_id"] if svc_id in all_services else "",
                "fluid_type": fluid_type,
                "approved_quantity": round(approved_qty, 2),
                "approved_rate": round(approved_rate, 2),
                "approved_amount": round(approved_amount, 2),
                "status": status,
                "discrepancy_flag": "|".join(f["type"] for f in flags) if flags else "none",
            })

            for flag in flags:
                discrepancies.append({
                    "invoice_id": inv_id,
                    "discrepancy_type": flag["type"],
                    "charged_value": flag["charged_value"],
                    "expected_value": flag["expected_value"],
                    "difference": flag["difference"],
                })

        return approved_payments, discrepancies

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
        gt_payments, gt_discrepancies = self._compute_ground_truth()
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: approved_payments.csv exists and has correct columns (10 pts) ---
        c1_max = 10
        max_score += c1_max
        payments_path = os.path.join(self.workspace, "approved_payments.csv")
        payments_ok = False
        agent_payments = []
        expected_cols = {"invoice_id", "service_id", "provider_name", "flight_id",
                         "fluid_type", "approved_quantity", "approved_rate",
                         "approved_amount", "status", "discrepancy_flag"}
        if os.path.exists(payments_path):
            try:
                with open(payments_path) as f:
                    reader = csv.DictReader(f)
                    agent_payments = list(reader)
                actual_cols = set(reader.fieldnames) if reader.fieldnames else set()
                if expected_cols.issubset(actual_cols) and len(agent_payments) > 0:
                    payments_ok = True
            except Exception:
                pass

        if payments_ok:
            eval_criteria["payments_file_format"] = {
                "passed": True, "score": c1_max, "max_score": c1_max,
            }
            total_score += c1_max
        else:
            eval_criteria["payments_file_format"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "approved_payments.csv missing, unreadable, or has wrong columns",
            }

        # --- Criterion 2: Correct row count in approved_payments.csv (10 pts) ---
        c2_max = 10
        max_score += c2_max
        if payments_ok and len(agent_payments) == len(gt_payments):
            eval_criteria["payments_row_count"] = {
                "passed": True, "score": c2_max, "max_score": c2_max,
            }
            total_score += c2_max
        else:
            eval_criteria["payments_row_count"] = {
                "passed": False, "score": 0, "max_score": c2_max,
                "reason": f"Expected {len(gt_payments)} rows, got {len(agent_payments)}",
            }

        # --- Criterion 3: Approved amounts accuracy (25 pts, partial) ---
        c3_max = 25
        max_score += c3_max
        if payments_ok and len(agent_payments) > 0:
            gt_amounts = {p["invoice_id"]: p["approved_amount"] for p in gt_payments}
            agent_amounts = {}
            for p in agent_payments:
                try:
                    agent_amounts[p["invoice_id"]] = round(float(p["approved_amount"]), 2)
                except (ValueError, KeyError):
                    pass
            correct = 0
            total_checked = len(gt_amounts)
            for inv_id, gt_amt in gt_amounts.items():
                if inv_id in agent_amounts and abs(agent_amounts[inv_id] - gt_amt) < 0.02:
                    correct += 1
            pct = correct / total_checked if total_checked > 0 else 0
            score = round(c3_max * pct)
            eval_criteria["approved_amounts_accuracy"] = {
                "passed": pct >= 0.95,
                "score": score,
                "max_score": c3_max,
                "reason": f"{correct}/{total_checked} amounts correct ({pct*100:.1f}%)" if pct < 0.95 else None,
            }
            total_score += score
        else:
            eval_criteria["approved_amounts_accuracy"] = {
                "passed": False, "score": 0, "max_score": c3_max,
                "reason": "No valid payment data to check",
            }

        # --- Criterion 4: Status flags accuracy (20 pts, partial) ---
        c4_max = 20
        max_score += c4_max
        if payments_ok and len(agent_payments) > 0:
            gt_status = {p["invoice_id"]: p["status"] for p in gt_payments}
            agent_status = {p.get("invoice_id", ""): p.get("status", "").strip().lower() for p in agent_payments}
            correct = 0
            total_checked = len(gt_status)
            for inv_id, gt_s in gt_status.items():
                if inv_id in agent_status and agent_status[inv_id] == gt_s:
                    correct += 1
            pct = correct / total_checked if total_checked > 0 else 0
            score = round(c4_max * pct)
            eval_criteria["status_accuracy"] = {
                "passed": pct >= 0.95,
                "score": score,
                "max_score": c4_max,
                "reason": f"{correct}/{total_checked} statuses correct ({pct*100:.1f}%)" if pct < 0.95 else None,
            }
            total_score += score
        else:
            eval_criteria["status_accuracy"] = {
                "passed": False, "score": 0, "max_score": c4_max,
                "reason": "No valid payment data to check",
            }

        # --- Criterion 5: discrepancy_report.csv exists and content (15 pts) ---
        c5_max = 15
        max_score += c5_max
        disc_path = os.path.join(self.workspace, "discrepancy_report.csv")
        disc_ok = False
        agent_discs = []
        disc_expected_cols = {"invoice_id", "discrepancy_type", "charged_value", "expected_value", "difference"}
        if os.path.exists(disc_path):
            try:
                with open(disc_path) as f:
                    reader = csv.DictReader(f)
                    agent_discs = list(reader)
                actual_cols = set(reader.fieldnames) if reader.fieldnames else set()
                if disc_expected_cols.issubset(actual_cols):
                    disc_ok = True
            except Exception:
                pass

        if disc_ok:
            # Check that the discrepancy types and invoice IDs are mostly correct
            gt_disc_set = set()
            for d in gt_discrepancies:
                gt_disc_set.add((d["invoice_id"], d["discrepancy_type"]))
            agent_disc_set = set()
            for d in agent_discs:
                agent_disc_set.add((d.get("invoice_id", ""), d.get("discrepancy_type", "").strip()))

            if len(gt_disc_set) > 0:
                tp = len(gt_disc_set & agent_disc_set)
                precision = tp / len(agent_disc_set) if agent_disc_set else 0
                recall = tp / len(gt_disc_set)
                f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
                score = round(c5_max * f1)
            else:
                score = c5_max if len(agent_disc_set) == 0 else 0

            eval_criteria["discrepancy_report"] = {
                "passed": score >= c5_max * 0.9,
                "score": score,
                "max_score": c5_max,
                "reason": f"F1={f1:.3f} (P={precision:.3f}, R={recall:.3f})" if score < c5_max * 0.9 else None,
            }
            total_score += score
        else:
            eval_criteria["discrepancy_report"] = {
                "passed": False, "score": 0, "max_score": c5_max,
                "reason": "discrepancy_report.csv missing or has wrong columns",
            }

        # --- Criterion 6: Discrepancy flags in payments match (10 pts) ---
        c6_max = 10
        max_score += c6_max
        if payments_ok and len(agent_payments) > 0:
            gt_flags = {p["invoice_id"]: p["discrepancy_flag"] for p in gt_payments}
            agent_flags = {}
            for p in agent_payments:
                agent_flags[p.get("invoice_id", "")] = p.get("discrepancy_flag", "").strip()

            correct = 0
            total_checked = len(gt_flags)
            for inv_id, gt_f in gt_flags.items():
                if inv_id in agent_flags:
                    # Compare sets of flags (order doesn't matter)
                    gt_set = set(gt_f.split("|")) if gt_f != "none" else {"none"}
                    agent_set = set(agent_flags[inv_id].split("|")) if agent_flags[inv_id] and agent_flags[inv_id] != "none" else {"none"}
                    if gt_set == agent_set:
                        correct += 1
            pct = correct / total_checked if total_checked > 0 else 0
            score = round(c6_max * pct)
            eval_criteria["discrepancy_flags_accuracy"] = {
                "passed": pct >= 0.90,
                "score": score,
                "max_score": c6_max,
                "reason": f"{correct}/{total_checked} flags correct ({pct*100:.1f}%)" if pct < 0.90 else None,
            }
            total_score += score
        else:
            eval_criteria["discrepancy_flags_accuracy"] = {
                "passed": False, "score": 0, "max_score": c6_max,
                "reason": "No valid payment data to check",
            }

        # --- Criterion 7: Response summary (10 pts) ---
        c7_max = 10
        max_score += c7_max
        action_lower = action.lower()
        summary_checks = 0
        # Check that response mentions total invoices processed
        if str(len(gt_payments)) in action:
            summary_checks += 1
        # Check that response mentions number of flagged invoices
        n_flagged = sum(1 for p in gt_payments if p["status"] == "flagged")
        if str(n_flagged) in action:
            summary_checks += 1
        # Check that response mentions total approved amount
        total_approved = round(sum(p["approved_amount"] for p in gt_payments), 2)
        # Allow some formatting flexibility
        total_str = f"{total_approved:.2f}"
        if total_str in action or f"{total_approved:,.2f}" in action:
            summary_checks += 1
        # Check mention of discrepancy types
        disc_types_found = 0
        for dt in ["quantity_overcharge", "rate_mismatch", "time_anomaly", "duplicate_billing"]:
            if dt in action_lower or dt.replace("_", " ") in action_lower:
                disc_types_found += 1
        if disc_types_found >= 3:
            summary_checks += 1

        score = round(c7_max * min(summary_checks / 4, 1.0))
        eval_criteria["response_summary"] = {
            "passed": summary_checks >= 3,
            "score": score,
            "max_score": c7_max,
            "reason": f"Only {summary_checks}/4 summary elements found" if summary_checks < 3 else None,
        }
        total_score += score

        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as csv_mod

        # Step 1: Read workspace files to get contract rates, validation policy, truck logs
        # Read contract rates
        rates_path = os.path.join(self.workspace, "contract_rates.json")
        with open(rates_path) as f:
            contract_rates_data = json.load(f)
        contract_rates = {}
        provider_names = {}
        for pid, info in contract_rates_data.items():
            provider_names[pid] = info["provider_name"]
            contract_rates[pid] = {}
            for ft, rate_info in info["rates"].items():
                contract_rates[pid][ft] = rate_info["rate_per_liter"]

        # Read validation policy
        policy_path = os.path.join(self.workspace, "validation_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)
        qty_tol = policy["validation_rules"]["quantity_tolerance_pct"]

        # Read truck logs
        truck_logs = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "truck_fluid_log_*.csv"))):
            with open(fpath) as f:
                reader = csv_mod.DictReader(f)
                for row in reader:
                    truck_logs[row["service_id"]] = {
                        "dispensed_liters": float(row["dispensed_liters"]),
                        "truck_id": row["truck_id"],
                        "fluid_type": row["fluid_type"],
                        "end_time": row["end_time"],
                    }

        # Step 2: Get all invoices via tools (paginated)
        all_invoices = []
        tool_call_count = 0

        result = self.tools["list_invoices"](page=1, page_size=25)
        tool_call_count += 1
        total_pages = result["total_pages"]
        all_invoices.extend(result["invoices"])

        for pg in range(2, total_pages + 1):
            result = self.tools["list_invoices"](page=pg, page_size=25)
            tool_call_count += 1
            all_invoices.extend(result["invoices"])

        # Step 3: For each invoice, get service record and flight info
        seen_services = {}
        approved_payments = []
        discrepancies = []

        for inv in all_invoices:
            inv_id = inv["invoice_id"]
            svc_id = inv["service_id"]
            pid = inv["provider_id"]
            fluid_type = inv["fluid_type"]
            charged_qty = float(inv["charged_quantity"])
            charged_rate = float(inv["charged_rate"])
            total_charge = float(inv["total_charge"])

            flags = []

            # Check for duplicate billing
            if svc_id in seen_services:
                flags.append({
                    "type": "duplicate_billing",
                    "detail": f"Duplicate of {seen_services[svc_id]}",
                    "charged_value": f"{total_charge}",
                    "expected_value": "0.00",
                    "difference": f"{total_charge}",
                })
            else:
                seen_services[svc_id] = inv_id

            # Get service record
            svc = self.tools["get_service_record"](service_id=svc_id)
            tool_call_count += 1

            # Get flight info
            flight = self.tools["get_flight_info"](flight_id=svc["flight_id"])
            tool_call_count += 1

            # Quantity overcharge check using truck logs
            actual_qty = None
            if svc_id in truck_logs:
                actual_qty = truck_logs[svc_id]["dispensed_liters"]
                if actual_qty > 0:
                    pct_diff = ((charged_qty - actual_qty) / actual_qty) * 100
                    if pct_diff > qty_tol:
                        flags.append({
                            "type": "quantity_overcharge",
                            "charged_value": str(charged_qty),
                            "expected_value": str(actual_qty),
                            "difference": str(round(charged_qty - actual_qty, 2)),
                        })

            # Rate mismatch check
            if pid in contract_rates and fluid_type in contract_rates[pid]:
                correct_rate = contract_rates[pid][fluid_type]
                if abs(charged_rate - correct_rate) > 0.001:
                    flags.append({
                        "type": "rate_mismatch",
                        "charged_value": str(charged_rate),
                        "expected_value": str(correct_rate),
                        "difference": str(round(charged_rate - correct_rate, 2)),
                    })

            # Time anomaly check
            svc_end = datetime.fromisoformat(svc["service_end"])
            pushback = datetime.fromisoformat(flight["actual_pushback"])
            if svc_end > pushback:
                flags.append({
                    "type": "time_anomaly",
                    "charged_value": svc["service_end"],
                    "expected_value": flight["actual_pushback"],
                    "difference": str(int((svc_end - pushback).total_seconds() // 60)) + " minutes",
                })

            # Determine approved values
            if flags:
                status = "flagged"
                if any(f["type"] == "duplicate_billing" for f in flags):
                    approved_qty = 0.0
                    approved_rate = 0.0
                    approved_amount = 0.0
                else:
                    approved_qty = actual_qty if actual_qty is not None else charged_qty
                    approved_rate = contract_rates.get(pid, {}).get(fluid_type, charged_rate)
                    approved_amount = round(approved_qty * approved_rate, 2)
            else:
                status = "approved"
                approved_qty = charged_qty
                approved_rate = charged_rate
                approved_amount = total_charge

            # Get provider name (use cached data from workspace file)
            pname = provider_names.get(pid, pid)

            approved_payments.append({
                "invoice_id": inv_id,
                "service_id": svc_id,
                "provider_name": pname,
                "flight_id": svc["flight_id"],
                "fluid_type": fluid_type,
                "approved_quantity": round(approved_qty, 2),
                "approved_rate": round(approved_rate, 2),
                "approved_amount": round(approved_amount, 2),
                "status": status,
                "discrepancy_flag": "|".join(f["type"] for f in flags) if flags else "none",
            })

            for flag in flags:
                discrepancies.append({
                    "invoice_id": inv_id,
                    "discrepancy_type": flag["type"],
                    "charged_value": flag["charged_value"],
                    "expected_value": flag["expected_value"],
                    "difference": flag["difference"],
                })

        # Step 4: Write output files
        # approved_payments.csv
        payments_path = os.path.join(self.workspace, "approved_payments.csv")
        fieldnames = ["invoice_id", "service_id", "provider_name", "flight_id",
                       "fluid_type", "approved_quantity", "approved_rate",
                       "approved_amount", "status", "discrepancy_flag"]
        with open(payments_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for p in approved_payments:
                writer.writerow(p)

        # discrepancy_report.csv
        disc_path = os.path.join(self.workspace, "discrepancy_report.csv")
        disc_fieldnames = ["invoice_id", "discrepancy_type", "charged_value",
                           "expected_value", "difference"]
        with open(disc_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=disc_fieldnames)
            writer.writeheader()
            for d in discrepancies:
                writer.writerow(d)

        # Step 5: Construct action string with summary
        n_flagged = sum(1 for p in approved_payments if p["status"] == "flagged")
        total_approved = round(sum(p["approved_amount"] for p in approved_payments), 2)

        disc_type_counts = {}
        for d in discrepancies:
            dt = d["discrepancy_type"]
            disc_type_counts[dt] = disc_type_counts.get(dt, 0) + 1

        action = (
            f"Reconciliation complete. Processed {len(approved_payments)} invoices total. "
            f"{n_flagged} invoices were flagged with discrepancies. "
            f"Total approved amount: {total_approved:.2f}. "
            f"Discrepancy breakdown: "
        )
        parts = []
        for dt in ["quantity_overcharge", "rate_mismatch", "time_anomaly", "duplicate_billing"]:
            if dt in disc_type_counts:
                parts.append(f"{dt}: {disc_type_counts[dt]}")
        action += ", ".join(parts) + ". "
        action += (
            f"Output files: approved_payments.csv ({len(approved_payments)} rows) and "
            f"discrepancy_report.csv ({len(discrepancies)} entries)."
        )

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need >= 15"

        return self.step(action)
