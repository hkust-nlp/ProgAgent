"""
Environment for Inter-Library Loan Overdue Reconciliation task.
"""

import csv
import json
import os
import sqlite3
import glob as globmod
import yaml
from datetime import datetime
from typing import Tuple, Dict, List, Any


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
        description="List loans filtered by status. Returns paginated results (up to 20 per page). Each record includes loan_id, book_id, patron_id, partner_institution_id, loan_date, due_date, return_date, and status.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "returned", "overdue", "lost", "all"],
                    "description": "Filter by loan status. Use 'all' to list every loan.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Each page contains up to 20 records.",
                },
            },
            "required": ["status", "page"],
        },
    )
    def list_loans(self, status: str, page: int) -> dict:
        page_size = 20
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if status == "all":
            rows = conn.execute(
                "SELECT * FROM loans ORDER BY loan_id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM loans WHERE status = ? ORDER BY loan_id", (status,)
            ).fetchall()
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = [dict(r) for r in rows[start:end]]
        return {
            "loans": page_rows,
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get detailed information for a single loan by its loan_id.",
        parameters={
            "type": "object",
            "properties": {
                "loan_id": {
                    "type": "string",
                    "description": "The loan identifier, e.g. 'ILL-0001'.",
                },
            },
            "required": ["loan_id"],
        },
    )
    def get_loan_details(self, loan_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM loans WHERE loan_id = ?", (loan_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Loan {loan_id} not found."}
        return dict(row)

    @tool(
        description="Get information about a patron by patron_id, including name, email, phone, department, and patron type.",
        parameters={
            "type": "object",
            "properties": {
                "patron_id": {
                    "type": "string",
                    "description": "The patron identifier, e.g. 'PAT-0001'.",
                },
            },
            "required": ["patron_id"],
        },
    )
    def get_patron_info(self, patron_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM patrons WHERE patron_id = ?", (patron_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Patron {patron_id} not found."}
        return dict(row)

    @tool(
        description="Get book details including title, author, ISBN, category, and base replacement cost.",
        parameters={
            "type": "object",
            "properties": {
                "book_id": {
                    "type": "string",
                    "description": "The book identifier, e.g. 'BK-0001'.",
                },
            },
            "required": ["book_id"],
        },
    )
    def get_book_info(self, book_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM books WHERE book_id = ?", (book_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Book {book_id} not found."}
        return dict(row)

    @tool(
        description="Get partner institution details by institution_id, including name, location, default loan period, and default fine rate.",
        parameters={
            "type": "object",
            "properties": {
                "institution_id": {
                    "type": "string",
                    "description": "The institution identifier, e.g. 'INST-0001'.",
                },
            },
            "required": ["institution_id"],
        },
    )
    def get_partner_info(self, institution_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM partner_institutions WHERE institution_id = ?",
            (institution_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Institution {institution_id} not found."}
        return dict(row)

    @tool(
        description="Get all shipment tracking records for a given loan_id. Returns a list of shipments with direction, carrier, tracking number, dates, and status.",
        parameters={
            "type": "object",
            "properties": {
                "loan_id": {
                    "type": "string",
                    "description": "The loan identifier to look up shipments for.",
                },
            },
            "required": ["loan_id"],
        },
    )
    def get_shipment_info(self, loan_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM shipment_tracking WHERE loan_id = ? ORDER BY ship_date",
            (loan_id,),
        ).fetchall()
        conn.close()
        return {"shipments": [dict(r) for r in rows]}

    @tool(
        description="Get the contact history for a specific loan, showing all patron contact attempts including dates, methods, outcomes, and notes.",
        parameters={
            "type": "object",
            "properties": {
                "loan_id": {
                    "type": "string",
                    "description": "The loan identifier to look up contact history for.",
                },
            },
            "required": ["loan_id"],
        },
    )
    def get_contact_history(self, loan_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM patron_contacts WHERE loan_id = ? ORDER BY contact_date",
            (loan_id,),
        ).fetchall()
        conn.close()
        return {"contacts": [dict(r) for r in rows]}

    # ── Ground truth computation (shared by step and verify) ─────────────

    def _compute_ground_truth(self):
        """Compute the full ground truth reconciliation from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load fine policy
        policy_path = os.path.join(self.workspace, "fine_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)

        ref_date = datetime.strptime(policy["report_as_of_date"], "%Y-%m-%d")
        default_grace = policy["default_grace_period_days"]
        fine_tiers = sorted(policy["fine_tiers"], key=lambda t: t["min_days"])
        default_max_cap = policy["default_max_fine_cap"]
        replacement_threshold = policy["replacement_threshold_days"]
        condition_mults = policy["condition_multipliers"]

        # Load institution agreements
        agreements_path = os.path.join(self.workspace, "institution_agreements.json")
        with open(agreements_path) as f:
            agreements = json.load(f)

        # Load condition reports
        condition_map = {}
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "condition_report_batch_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    condition_map[row["book_id"]] = row["condition_grade"]

        # Load insurance records
        insurance_map = {}
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "insurance_record_*.json"))):
            with open(fpath) as f:
                records = json.load(f)
                for rec in records:
                    insurance_map[rec["loan_id"]] = rec

        # Load patron communication preferences
        patron_prefs = {}
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "patron_comm_prefs_*.txt"))):
            with open(fpath) as f:
                current_patron = None
                for line in f:
                    line = line.rstrip("\n")
                    if line.startswith("Patron ID:"):
                        current_patron = line.split(":", 1)[1].strip()
                        patron_prefs[current_patron] = {}
                    elif current_patron and line.strip().startswith("Preferred Method:"):
                        patron_prefs[current_patron]["preferred_method"] = line.split(":", 1)[1].strip()
                    elif current_patron and line.strip().startswith("Do Not Contact:"):
                        patron_prefs[current_patron]["do_not_contact"] = line.split(":", 1)[1].strip()
                    elif current_patron and line.strip().startswith("Max Contacts/Month:"):
                        patron_prefs[current_patron]["max_contacts_month"] = int(line.split(":", 1)[1].strip())

        # Load recovery procedures to validate action categories
        # (The recovery actions are deterministic from days_overdue + status)

        # Get overdue and lost loans
        loans = conn.execute(
            "SELECT * FROM loans WHERE status IN ('overdue', 'lost') ORDER BY loan_id"
        ).fetchall()

        results = []
        for loan in loans:
            loan = dict(loan)
            loan_id = loan["loan_id"]
            book_id = loan["book_id"]
            patron_id = loan["patron_id"]
            inst_id = loan["partner_institution_id"]
            due_date = datetime.strptime(loan["due_date"], "%Y-%m-%d")
            status = loan["status"]

            # Get book info
            book = dict(conn.execute(
                "SELECT * FROM books WHERE book_id = ?", (book_id,)
            ).fetchone())

            # Get patron info
            patron = dict(conn.execute(
                "SELECT * FROM patrons WHERE patron_id = ?", (patron_id,)
            ).fetchone())

            # Get institution info
            inst = dict(conn.execute(
                "SELECT * FROM partner_institutions WHERE institution_id = ?",
                (inst_id,),
            ).fetchone())

            # Determine grace period
            inst_agreement = agreements.get(inst_id, {})
            grace_period = inst_agreement.get("grace_period_days", default_grace)

            # Calculate raw days overdue
            raw_days_overdue = (ref_date - due_date).days
            adjusted_days_overdue = max(0, raw_days_overdue - grace_period)

            # Calculate fine using tiers
            fine_rate_multiplier = inst_agreement.get("fine_rate_multiplier", 1.0)
            max_fine_cap = inst_agreement.get("max_fine_cap", default_max_cap)

            fine = 0.0
            remaining_days = adjusted_days_overdue
            for tier in fine_tiers:
                if remaining_days <= 0:
                    break
                tier_min = tier["min_days"]
                tier_max = tier["max_days"]
                tier_span = tier_max - tier_min + 1
                days_in_tier = min(remaining_days, tier_span)
                fine += days_in_tier * tier["rate_per_day"] * fine_rate_multiplier
                remaining_days -= days_in_tier

            fine = min(fine, max_fine_cap)
            fine = round(fine, 2)

            # Determine replacement liability
            replacement_liable = adjusted_days_overdue > replacement_threshold or status == "lost"

            gross_replacement = 0.0
            insurance_coverage = 0.0
            net_replacement = 0.0

            if replacement_liable:
                condition_grade = condition_map.get(book_id, "B")  # default B
                multiplier = condition_mults.get(condition_grade, 1.1)
                gross_replacement = round(book["base_replacement_cost"] * multiplier, 2)

                # Check insurance
                ins_rec = insurance_map.get(loan_id, {})
                if ins_rec.get("policy_status") == "active" and ins_rec.get("coverage_amount", 0) > 0:
                    insurance_coverage = round(
                        max(0, ins_rec["coverage_amount"] - ins_rec.get("deductible", 0)), 2
                    )

                net_replacement = round(max(0, gross_replacement - insurance_coverage), 2)

            # Determine recovery action
            if adjusted_days_overdue > 90 or status == "lost":
                recovery_action = "replacement_invoice"
            elif adjusted_days_overdue >= 61:
                recovery_action = "collection_referral"
            elif adjusted_days_overdue >= 31:
                recovery_action = "final_warning"
            elif adjusted_days_overdue >= 15:
                recovery_action = "formal_notice"
            elif adjusted_days_overdue >= 1:
                recovery_action = "courtesy_reminder"
            else:
                recovery_action = "no_action"

            # Priority
            total_liability = fine + net_replacement
            priority = "high_priority" if total_liability > 100.0 else "normal_priority"

            # Contact hold
            prefs = patron_prefs.get(patron_id, {})
            contact_hold = prefs.get("do_not_contact", "no") == "yes"

            results.append({
                "loan_id": loan_id,
                "book_title": book["title"],
                "patron_name": patron["name"],
                "patron_email": patron["email"],
                "partner_institution": inst["name"],
                "days_overdue": adjusted_days_overdue,
                "fine_amount": fine,
                "replacement_liable": "yes" if replacement_liable else "no",
                "gross_replacement_cost": gross_replacement,
                "insurance_coverage": insurance_coverage,
                "net_replacement_cost": net_replacement,
                "total_liability": round(total_liability, 2),
                "recovery_action": recovery_action,
                "priority": priority,
                "contact_hold": contact_hold,
                "patron_id": patron_id,
            })

        conn.close()

        # Sort by days_overdue descending, then loan_id ascending
        results.sort(key=lambda r: (-r["days_overdue"], r["loan_id"]))

        return results

    # ── step ─────────────────────────────────────────────────────────────

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion.
        """
        gt = self._compute_ground_truth()
        # Filter to only items with action needed
        gt_actionable = [r for r in gt if r["recovery_action"] != "no_action"]

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: reconciliation_report.csv exists and has correct columns (10 pts) ──
        c1_max = 10
        max_score += c1_max
        report_path = os.path.join(self.workspace, "reconciliation_report.csv")
        expected_columns = [
            "loan_id", "book_title", "patron_name", "partner_institution",
            "days_overdue", "fine_amount", "replacement_liable",
            "gross_replacement_cost", "insurance_coverage", "net_replacement_cost",
            "total_liability", "recovery_action", "priority", "contact_hold",
        ]
        report_rows = []
        if os.path.exists(report_path):
            with open(report_path) as f:
                reader = csv.DictReader(f)
                actual_cols = reader.fieldnames or []
                report_rows = list(reader)
            cols_match = all(c in actual_cols for c in expected_columns)
            if cols_match:
                eval_criteria["report_structure"] = {
                    "passed": True, "score": c1_max, "max_score": c1_max,
                }
                total_score += c1_max
            else:
                missing = [c for c in expected_columns if c not in actual_cols]
                eval_criteria["report_structure"] = {
                    "passed": False, "score": 0, "max_score": c1_max,
                    "reason": f"Missing columns: {missing}",
                }
        else:
            eval_criteria["report_structure"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "reconciliation_report.csv not found.",
            }

        # ── Criterion 2: Correct identification of overdue/lost items (20 pts) ──
        c2_max = 20
        max_score += c2_max
        gt_loan_ids = set(r["loan_id"] for r in gt_actionable)
        report_loan_ids = set(r.get("loan_id", "") for r in report_rows)
        if gt_loan_ids and report_loan_ids:
            correct = gt_loan_ids & report_loan_ids
            extra = report_loan_ids - gt_loan_ids
            missing = gt_loan_ids - report_loan_ids
            id_score = round(c2_max * len(correct) / len(gt_loan_ids) * (1 - 0.5 * len(extra) / max(len(report_loan_ids), 1)), 1)
            id_score = max(0, min(c2_max, id_score))
            passed = len(missing) == 0 and len(extra) == 0
            eval_criteria["item_identification"] = {
                "passed": passed,
                "score": id_score,
                "max_score": c2_max,
                "reason": "" if passed else f"Missing: {len(missing)}, Extra: {len(extra)} out of {len(gt_loan_ids)} expected.",
            }
            total_score += id_score
        else:
            eval_criteria["item_identification"] = {
                "passed": False, "score": 0, "max_score": c2_max,
                "reason": "No loan IDs found in report or ground truth is empty.",
            }

        # ── Criterion 3: Correct fine calculations (25 pts) ──
        c3_max = 25
        max_score += c3_max
        gt_fines = {r["loan_id"]: r["fine_amount"] for r in gt_actionable}
        report_fines = {}
        for r in report_rows:
            try:
                report_fines[r["loan_id"]] = round(float(r.get("fine_amount", 0)), 2)
            except (ValueError, TypeError):
                pass
        fine_correct = 0
        fine_total = len(gt_fines)
        for lid, expected_fine in gt_fines.items():
            if lid in report_fines and abs(report_fines[lid] - expected_fine) < 0.02:
                fine_correct += 1
        if fine_total > 0:
            fine_score = round(c3_max * fine_correct / fine_total, 1)
        else:
            fine_score = c3_max
        eval_criteria["fine_calculations"] = {
            "passed": fine_correct == fine_total,
            "score": fine_score,
            "max_score": c3_max,
            "reason": "" if fine_correct == fine_total else f"{fine_correct}/{fine_total} fines correct.",
        }
        total_score += fine_score

        # ── Criterion 4: Correct replacement cost calculations (20 pts) ──
        c4_max = 20
        max_score += c4_max
        gt_replacement = {r["loan_id"]: r for r in gt_actionable if r["replacement_liable"] == "yes"}
        repl_correct = 0
        repl_total = len(gt_replacement)
        for lid, gt_r in gt_replacement.items():
            for rr in report_rows:
                if rr.get("loan_id") == lid:
                    try:
                        rr_net = round(float(rr.get("net_replacement_cost", 0)), 2)
                        rr_gross = round(float(rr.get("gross_replacement_cost", 0)), 2)
                        rr_liable = rr.get("replacement_liable", "").strip().lower()
                        if (rr_liable == "yes"
                                and abs(rr_net - gt_r["net_replacement_cost"]) < 0.02
                                and abs(rr_gross - gt_r["gross_replacement_cost"]) < 0.02):
                            repl_correct += 1
                    except (ValueError, TypeError):
                        pass
                    break
        # Also check that non-liable items are correctly marked
        gt_non_replacement = {r["loan_id"] for r in gt_actionable if r["replacement_liable"] == "no"}
        non_repl_correct = 0
        for rr in report_rows:
            lid = rr.get("loan_id", "")
            if lid in gt_non_replacement:
                if rr.get("replacement_liable", "").strip().lower() == "no":
                    non_repl_correct += 1
        total_repl_checks = repl_total + len(gt_non_replacement)
        all_repl_correct = repl_correct + non_repl_correct
        if total_repl_checks > 0:
            repl_score = round(c4_max * all_repl_correct / total_repl_checks, 1)
        else:
            repl_score = c4_max
        eval_criteria["replacement_costs"] = {
            "passed": all_repl_correct == total_repl_checks,
            "score": repl_score,
            "max_score": c4_max,
            "reason": "" if all_repl_correct == total_repl_checks else f"{all_repl_correct}/{total_repl_checks} replacement assessments correct.",
        }
        total_score += repl_score

        # ── Criterion 5: recovery_actions.json correctness (15 pts) ──
        c5_max = 15
        max_score += c5_max
        ra_path = os.path.join(self.workspace, "recovery_actions.json")
        if os.path.exists(ra_path):
            try:
                with open(ra_path) as f:
                    recovery_data = json.load(f)

                # Build expected recovery actions grouped by type
                expected_ra = {}
                for r in gt_actionable:
                    action_type = r["recovery_action"]
                    if action_type not in expected_ra:
                        expected_ra[action_type] = set()
                    expected_ra[action_type].add(r["loan_id"])

                # Check structure: should be dict of action_type -> list of entries
                ra_correct = 0
                ra_total = len(gt_actionable)
                if isinstance(recovery_data, dict):
                    for action_type, expected_ids in expected_ra.items():
                        actual_entries = recovery_data.get(action_type, [])
                        actual_ids = set()
                        for entry in actual_entries:
                            if isinstance(entry, dict):
                                actual_ids.add(entry.get("loan_id", ""))
                        ra_correct += len(expected_ids & actual_ids)

                ra_score = round(c5_max * ra_correct / ra_total, 1) if ra_total > 0 else c5_max
                eval_criteria["recovery_actions"] = {
                    "passed": ra_correct == ra_total,
                    "score": ra_score,
                    "max_score": c5_max,
                    "reason": "" if ra_correct == ra_total else f"{ra_correct}/{ra_total} recovery action entries correct.",
                }
                total_score += ra_score
            except (json.JSONDecodeError, Exception) as e:
                eval_criteria["recovery_actions"] = {
                    "passed": False, "score": 0, "max_score": c5_max,
                    "reason": f"Error reading recovery_actions.json: {e}",
                }
        else:
            eval_criteria["recovery_actions"] = {
                "passed": False, "score": 0, "max_score": c5_max,
                "reason": "recovery_actions.json not found.",
            }

        # ── Criterion 6: Correct sort order in report (10 pts) ──
        c6_max = 10
        max_score += c6_max
        if len(report_rows) >= 2:
            sorted_correctly = True
            for i in range(len(report_rows) - 1):
                try:
                    d1 = int(report_rows[i].get("days_overdue", 0))
                    d2 = int(report_rows[i + 1].get("days_overdue", 0))
                    l1 = report_rows[i].get("loan_id", "")
                    l2 = report_rows[i + 1].get("loan_id", "")
                    if d1 < d2 or (d1 == d2 and l1 > l2):
                        sorted_correctly = False
                        break
                except (ValueError, TypeError):
                    sorted_correctly = False
                    break
            eval_criteria["sort_order"] = {
                "passed": sorted_correctly,
                "score": c6_max if sorted_correctly else 0,
                "max_score": c6_max,
                "reason": "" if sorted_correctly else "Report rows not sorted by days_overdue desc, loan_id asc.",
            }
            total_score += c6_max if sorted_correctly else 0
        elif len(report_rows) == 1:
            eval_criteria["sort_order"] = {
                "passed": True, "score": c6_max, "max_score": c6_max,
            }
            total_score += c6_max
        else:
            eval_criteria["sort_order"] = {
                "passed": False, "score": 0, "max_score": c6_max,
                "reason": "Report is empty.",
            }

        # ── Criterion 7: Response summary accuracy (10 pts) ──
        c7_max = 10
        max_score += c7_max
        # Check that the action string contains key summary numbers
        total_overdue = len(gt_actionable)
        total_fines_sum = round(sum(r["fine_amount"] for r in gt_actionable), 2)
        total_repl_sum = round(sum(r["net_replacement_cost"] for r in gt_actionable), 2)

        summary_checks = 0
        summary_total = 3
        if str(total_overdue) in action:
            summary_checks += 1
        # Check fines total - allow formatting variations
        fines_str = f"{total_fines_sum:.2f}"
        if fines_str in action or f"${fines_str}" in action:
            summary_checks += 1
        repl_str = f"{total_repl_sum:.2f}"
        if repl_str in action or f"${repl_str}" in action:
            summary_checks += 1

        summary_score = round(c7_max * summary_checks / summary_total, 1)
        eval_criteria["response_summary"] = {
            "passed": summary_checks == summary_total,
            "score": summary_score,
            "max_score": c7_max,
            "reason": "" if summary_checks == summary_total else f"{summary_checks}/{summary_total} summary values found in response.",
        }
        total_score += summary_score

        total_score = round(total_score, 1)
        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0

        return reward, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ── verify ───────────────────────────────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml as _yaml

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # Step 1: Read workspace files
        # Read fine policy
        policy_path = os.path.join(self.workspace, "fine_policy.yaml")
        with open(policy_path) as f:
            policy = _yaml.safe_load(f)

        ref_date = datetime.strptime(policy["report_as_of_date"], "%Y-%m-%d")
        default_grace = policy["default_grace_period_days"]
        fine_tiers = sorted(policy["fine_tiers"], key=lambda t: t["min_days"])
        default_max_cap = policy["default_max_fine_cap"]
        replacement_threshold = policy["replacement_threshold_days"]
        condition_mults = policy["condition_multipliers"]

        # Read institution agreements
        agreements_path = os.path.join(self.workspace, "institution_agreements.json")
        with open(agreements_path) as f:
            agreements = json.load(f)

        # Read condition reports
        condition_map = {}
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "condition_report_batch_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    condition_map[row["book_id"]] = row["condition_grade"]

        # Read insurance records
        insurance_map = {}
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "insurance_record_*.json"))):
            with open(fpath) as f:
                records = json.load(f)
                for rec in records:
                    insurance_map[rec["loan_id"]] = rec

        # Read patron comm prefs
        patron_prefs = {}
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "patron_comm_prefs_*.txt"))):
            with open(fpath) as f:
                current_patron = None
                for line in f:
                    line = line.rstrip("\n")
                    if line.startswith("Patron ID:"):
                        current_patron = line.split(":", 1)[1].strip()
                        patron_prefs[current_patron] = {}
                    elif current_patron and line.strip().startswith("Preferred Method:"):
                        patron_prefs[current_patron]["preferred_method"] = line.split(":", 1)[1].strip()
                    elif current_patron and line.strip().startswith("Do Not Contact:"):
                        patron_prefs[current_patron]["do_not_contact"] = line.split(":", 1)[1].strip()

        # Read recovery procedures
        recovery_path = os.path.join(self.workspace, "recovery_procedures.md")
        with open(recovery_path) as f:
            _ = f.read()  # Read for reference

        # Step 2: Get all overdue and lost loans via tools
        all_overdue = []
        page = 1
        while True:
            result = call_tool("list_loans", status="overdue", page=page)
            all_overdue.extend(result["loans"])
            if page >= result["total_pages"]:
                break
            page += 1

        all_lost = []
        page = 1
        while True:
            result = call_tool("list_loans", status="lost", page=page)
            all_lost.extend(result["loans"])
            if page >= result["total_pages"]:
                break
            page += 1

        all_items = all_overdue + all_lost

        # Step 3: For each item, gather details via tools
        results = []
        seen_books = {}
        seen_patrons = {}
        seen_institutions = {}

        for item in all_items:
            loan_id = item["loan_id"]
            book_id = item["book_id"]
            patron_id = item["patron_id"]
            inst_id = item["partner_institution_id"]
            due_date = datetime.strptime(item["due_date"], "%Y-%m-%d")
            status = item["status"]

            # Get book info (cache)
            if book_id not in seen_books:
                seen_books[book_id] = call_tool("get_book_info", book_id=book_id)
            book = seen_books[book_id]

            # Get patron info (cache)
            if patron_id not in seen_patrons:
                seen_patrons[patron_id] = call_tool("get_patron_info", patron_id=patron_id)
            patron = seen_patrons[patron_id]

            # Get institution info (cache)
            if inst_id not in seen_institutions:
                seen_institutions[inst_id] = call_tool("get_partner_info", institution_id=inst_id)
            inst = seen_institutions[inst_id]

            # Get shipment info
            shipment_info = call_tool("get_shipment_info", loan_id=loan_id)

            # Get contact history
            contact_info = call_tool("get_contact_history", loan_id=loan_id)

            # Calculate
            inst_agreement = agreements.get(inst_id, {})
            grace_period = inst_agreement.get("grace_period_days", default_grace)
            raw_days = (ref_date - due_date).days
            adjusted_days = max(0, raw_days - grace_period)

            fine_rate_multiplier = inst_agreement.get("fine_rate_multiplier", 1.0)
            max_fine_cap = inst_agreement.get("max_fine_cap", default_max_cap)

            fine = 0.0
            remaining = adjusted_days
            for tier in fine_tiers:
                if remaining <= 0:
                    break
                tier_span = tier["max_days"] - tier["min_days"] + 1
                days_in = min(remaining, tier_span)
                fine += days_in * tier["rate_per_day"] * fine_rate_multiplier
                remaining -= days_in
            fine = min(fine, max_fine_cap)
            fine = round(fine, 2)

            replacement_liable = adjusted_days > replacement_threshold or status == "lost"
            gross_repl = 0.0
            ins_cov = 0.0
            net_repl = 0.0

            if replacement_liable:
                cond_grade = condition_map.get(book_id, "B")
                mult = condition_mults.get(cond_grade, 1.1)
                gross_repl = round(book["base_replacement_cost"] * mult, 2)

                ins_rec = insurance_map.get(loan_id, {})
                if ins_rec.get("policy_status") == "active" and ins_rec.get("coverage_amount", 0) > 0:
                    ins_cov = round(max(0, ins_rec["coverage_amount"] - ins_rec.get("deductible", 0)), 2)
                net_repl = round(max(0, gross_repl - ins_cov), 2)

            if adjusted_days > 90 or status == "lost":
                recovery_action = "replacement_invoice"
            elif adjusted_days >= 61:
                recovery_action = "collection_referral"
            elif adjusted_days >= 31:
                recovery_action = "final_warning"
            elif adjusted_days >= 15:
                recovery_action = "formal_notice"
            elif adjusted_days >= 1:
                recovery_action = "courtesy_reminder"
            else:
                recovery_action = "no_action"

            if recovery_action == "no_action":
                continue

            total_liability = round(fine + net_repl, 2)
            priority = "high_priority" if total_liability > 100.0 else "normal_priority"

            prefs = patron_prefs.get(patron_id, {})
            contact_hold = prefs.get("do_not_contact", "no") == "yes"

            results.append({
                "loan_id": loan_id,
                "book_title": book["title"],
                "patron_name": patron["name"],
                "patron_email": patron["email"],
                "partner_institution": inst["name"],
                "days_overdue": adjusted_days,
                "fine_amount": fine,
                "replacement_liable": "yes" if replacement_liable else "no",
                "gross_replacement_cost": gross_repl,
                "insurance_coverage": ins_cov,
                "net_replacement_cost": net_repl,
                "total_liability": total_liability,
                "recovery_action": recovery_action,
                "priority": priority,
                "contact_hold": contact_hold,
            })

        # Sort by days_overdue desc, loan_id asc
        results.sort(key=lambda r: (-r["days_overdue"], r["loan_id"]))

        # Write reconciliation_report.csv
        report_path = os.path.join(self.workspace, "reconciliation_report.csv")
        fieldnames = [
            "loan_id", "book_title", "patron_name", "partner_institution",
            "days_overdue", "fine_amount", "replacement_liable",
            "gross_replacement_cost", "insurance_coverage", "net_replacement_cost",
            "total_liability", "recovery_action", "priority", "contact_hold",
        ]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                row = {k: r[k] for k in fieldnames}
                row["fine_amount"] = f"{r['fine_amount']:.2f}"
                row["gross_replacement_cost"] = f"{r['gross_replacement_cost']:.2f}"
                row["insurance_coverage"] = f"{r['insurance_coverage']:.2f}"
                row["net_replacement_cost"] = f"{r['net_replacement_cost']:.2f}"
                row["total_liability"] = f"{r['total_liability']:.2f}"
                row["contact_hold"] = str(r["contact_hold"]).lower()
                writer.writerow(row)

        # Write recovery_actions.json
        recovery_actions = {}
        for r in results:
            at = r["recovery_action"]
            if at not in recovery_actions:
                recovery_actions[at] = []
            recovery_actions[at].append({
                "loan_id": r["loan_id"],
                "patron_name": r["patron_name"],
                "patron_email": r["patron_email"],
                "fine_amount": r["fine_amount"],
                "net_replacement_cost": r["net_replacement_cost"],
                "total_liability": r["total_liability"],
                "priority": r["priority"],
                "contact_hold": r["contact_hold"],
            })

        ra_path = os.path.join(self.workspace, "recovery_actions.json")
        with open(ra_path, "w") as f:
            json.dump(recovery_actions, f, indent=2)

        # Build action string (summary)
        total_items = len(results)
        total_fines = round(sum(r["fine_amount"] for r in results), 2)
        total_repl = round(sum(r["net_replacement_cost"] for r in results), 2)
        total_liability = round(sum(r["total_liability"] for r in results), 2)

        action_counts = {}
        for r in results:
            at = r["recovery_action"]
            action_counts[at] = action_counts.get(at, 0) + 1

        action = (
            f"Reconciliation complete. {total_items} overdue/lost items identified. "
            f"Total fines: ${total_fines:.2f}. "
            f"Total net replacement liabilities: ${total_repl:.2f}. "
            f"Total liability: ${total_liability:.2f}. "
            f"Recovery action breakdown: "
            + ", ".join(f"{k}: {v}" for k, v in sorted(action_counts.items()))
            + ". "
            f"Files saved: reconciliation_report.csv and recovery_actions.json."
        )

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need >= 15"

        return self.step(action)
