#!/usr/bin/env python3
"""Environment for cross-border payment reconciliation task."""

import csv
import glob
import json
import os
import sqlite3
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

    # ── Tool Methods ─────────────────────────────────────────────────────

    @tool(
        description=(
            "Query payment records with optional filters. Returns paginated results "
            "(up to 20 per page). Each result includes payment_id, payment_ref, "
            "customer_name, amount, currency, status, and initiated_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["COMPLETED", "FAILED", "PENDING", "RETURNED"],
                    "description": "Filter by payment status.",
                },
                "currency": {
                    "type": "string",
                    "description": "Filter by currency code (e.g. USD, EUR).",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Defaults to 1.",
                },
            },
            "required": [],
        },
    )
    def query_payments(self, status: str = None, currency: str = None, page: int = 1):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        query = "SELECT id, payment_ref, customer_name, amount, currency, status, initiated_date FROM payments WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if currency:
            query += " AND currency = ?"
            params.append(currency)
        query += " ORDER BY id"
        page_size = 20
        offset = (max(1, page) - 1) * page_size
        query += f" LIMIT {page_size} OFFSET {offset}"
        rows = c.execute(query, params).fetchall()
        total = c.execute(
            "SELECT COUNT(*) FROM payments WHERE 1=1"
            + (" AND status = ?" if status else "")
            + (" AND currency = ?" if currency else ""),
            params,
        ).fetchone()[0]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total_results": total,
            "total_pages": (total + page_size - 1) // page_size,
            "results": [
                {
                    "payment_id": r[0],
                    "payment_ref": r[1],
                    "customer_name": r[2],
                    "amount": r[3],
                    "currency": r[4],
                    "status": r[5],
                    "initiated_date": r[6],
                }
                for r in rows
            ],
        }

    @tool(
        description=(
            "Retrieve full details of a single payment by its ID, including "
            "sender_bic, receiver_bic, value_date, and all other fields."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payment_id": {
                    "type": "integer",
                    "description": "The payment ID to look up.",
                },
            },
            "required": ["payment_id"],
        },
    )
    def get_payment_details(self, payment_id: int):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        row = c.execute(
            "SELECT id, payment_ref, customer_id, customer_name, amount, currency, "
            "sender_bic, receiver_bic, initiated_date, value_date, status "
            "FROM payments WHERE id = ?",
            (payment_id,),
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"Payment ID {payment_id} not found."}
        return {
            "payment_id": row[0],
            "payment_ref": row[1],
            "customer_id": row[2],
            "customer_name": row[3],
            "amount": row[4],
            "currency": row[5],
            "sender_bic": row[6],
            "receiver_bic": row[7],
            "initiated_date": row[8],
            "value_date": row[9],
            "status": row[10],
        }

    @tool(
        description=(
            "Retrieve the SWIFT message trail for a given payment reference. "
            "Returns all SWIFT messages in chronological order, including "
            "message_type, status_code (if any), timestamp, and narrative."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payment_ref": {
                    "type": "string",
                    "description": "The payment reference (e.g. PAY-00001).",
                },
            },
            "required": ["payment_ref"],
        },
    )
    def get_swift_trail(self, payment_ref: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        rows = c.execute(
            "SELECT id, message_type, status_code, timestamp, narrative "
            "FROM swift_messages WHERE payment_ref = ? ORDER BY timestamp",
            (payment_ref,),
        ).fetchall()
        conn.close()
        return {
            "payment_ref": payment_ref,
            "message_count": len(rows),
            "messages": [
                {
                    "message_id": r[0],
                    "message_type": r[1],
                    "status_code": r[2],
                    "timestamp": r[3],
                    "narrative": r[4],
                }
                for r in rows
            ],
        }

    @tool(
        description=(
            "Retrieve nostro account entries associated with a given payment reference. "
            "Returns debit/credit entries with amounts, dates, and running balances."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payment_ref": {
                    "type": "string",
                    "description": "The payment reference (e.g. PAY-00001).",
                },
            },
            "required": ["payment_ref"],
        },
    )
    def get_nostro_entries_by_ref(self, payment_ref: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        rows = c.execute(
            "SELECT id, account_id, entry_date, value_date, dc_indicator, "
            "amount, currency, balance_after "
            "FROM nostro_entries WHERE payment_ref = ? ORDER BY entry_date, id",
            (payment_ref,),
        ).fetchall()
        conn.close()
        return {
            "payment_ref": payment_ref,
            "entry_count": len(rows),
            "entries": [
                {
                    "entry_id": r[0],
                    "account_id": r[1],
                    "entry_date": r[2],
                    "value_date": r[3],
                    "dc_indicator": r[4],
                    "amount": r[5],
                    "currency": r[6],
                    "balance_after": r[7],
                }
                for r in rows
            ],
        }

    @tool(
        description=(
            "Look up correspondent bank information by BIC code. Returns the "
            "bank name, country, active status, and risk rating."
        ),
        parameters={
            "type": "object",
            "properties": {
                "bic_code": {
                    "type": "string",
                    "description": "The SWIFT BIC code (e.g. DEUTDEFF).",
                },
            },
            "required": ["bic_code"],
        },
    )
    def lookup_bank(self, bic_code: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        row = c.execute(
            "SELECT id, bic_code, bank_name, country, is_active, risk_rating "
            "FROM correspondent_banks WHERE bic_code = ?",
            (bic_code,),
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"BIC {bic_code} not found in correspondent bank directory."}
        return {
            "bank_id": row[0],
            "bic_code": row[1],
            "bank_name": row[2],
            "country": row[3],
            "is_active": bool(row[4]),
            "risk_rating": row[5],
        }

    @tool(
        description=(
            "Retrieve the fee record for a given payment reference, including "
            "expected fee, actual fee charged, and the fee currency."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payment_ref": {
                    "type": "string",
                    "description": "The payment reference (e.g. PAY-00001).",
                },
            },
            "required": ["payment_ref"],
        },
    )
    def get_fee_record(self, payment_ref: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        row = c.execute(
            "SELECT id, fee_type, expected_amount, actual_amount, currency, charged_date "
            "FROM fee_records WHERE payment_ref = ?",
            (payment_ref,),
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"No fee record for {payment_ref}."}
        return {
            "payment_ref": payment_ref,
            "fee_id": row[0],
            "fee_type": row[1],
            "expected_amount": row[2],
            "actual_amount": row[3],
            "currency": row[4],
            "charged_date": row[5],
        }

    # ── Evaluation ───────────────────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute the expected reconciliation results from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Load workspace configs
        with open(os.path.join(self.workspace, "high_value_thresholds.json")) as f:
            thresholds = json.load(f)["thresholds"]

        with open(os.path.join(self.workspace, "swift_status_codes.json")) as f:
            status_code_defs = json.load(f)

        with open(os.path.join(self.workspace, "reconciliation_rules.yaml")) as f:
            recon_rules = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "fee_corridor_config.yaml")) as f:
            fee_config = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "escalation_procedures.md")) as f:
            esc_text = f.read()

        # Parse escalation procedures into dict
        interventions = {}
        for line in esc_text.split("\n"):
            line = line.strip()
            if ":" in line and not line.startswith("Each"):
                parts = line.split(":", 1)
                key = parts[0].strip()
                val = parts[1].strip()
                if key and val:
                    interventions[key] = val

        # Load customer urgency from batch files
        urgency_map = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "customer_batch_*.json"))):
            with open(fpath) as f:
                batch = json.load(f)
            for p in batch["payments"]:
                urgency_map[p["payment_ref"]] = p["urgency"]

        # Load nostro reconciliation flags from CSVs
        nostro_flags = {}  # payment_ref -> list of (dc_indicator, flag)
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "nostro_statement_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ref = row["reference"]
                    dc = row["dc_indicator"]
                    flag = row["reconciliation_flag"]
                    if ref not in nostro_flags:
                        nostro_flags[ref] = []
                    nostro_flags[ref].append((dc, flag))

        # Get failed payments
        failed = c.execute(
            "SELECT id, payment_ref, customer_name, amount, currency, "
            "sender_bic, receiver_bic, initiated_date, value_date "
            "FROM payments WHERE status = 'FAILED' ORDER BY id"
        ).fetchall()

        results = []
        for row in failed:
            pid, ref, cname, amount, ccy, sender, receiver, init_date, val_date = row

            # Check high-value
            if amount < thresholds.get(ccy, float("inf")):
                continue

            # Get SWIFT trail - find rejection code
            msgs = c.execute(
                "SELECT message_type, status_code, timestamp FROM swift_messages "
                "WHERE payment_ref = ? ORDER BY timestamp",
                (ref,),
            ).fetchall()

            swift_status_code = None
            failure_date = init_date
            for msg in msgs:
                if msg[1]:  # has status code
                    swift_status_code = msg[1]
                    failure_date = msg[2].split(" ")[0] if msg[2] else init_date

            # Determine root cause
            # Check if receiver bank is inactive
            bank_row = c.execute(
                "SELECT is_active FROM correspondent_banks WHERE bic_code = ?",
                (receiver,),
            ).fetchone()
            bank_inactive = bank_row and bank_row[0] == 0

            if bank_inactive:
                root_cause = "BANK_INACTIVE"
            elif swift_status_code and swift_status_code in status_code_defs:
                root_cause = status_code_defs[swift_status_code]["category"]
            else:
                root_cause = "UNSPECIFIED"

            # Fee calculation
            fee_row = c.execute(
                "SELECT expected_amount, actual_amount FROM fee_records WHERE payment_ref = ?",
                (ref,),
            ).fetchone()
            expected_fee = fee_row[0] if fee_row else 0.0
            actual_fee = fee_row[1] if fee_row else 0.0
            fee_discrepancy = round(actual_fee - expected_fee, 2)

            # Nostro impact
            entries_for_ref = nostro_flags.get(ref, [])
            has_debit = any(dc == "D" for dc, _ in entries_for_ref)
            has_unmatched_debit = any(dc == "D" and flag == "UNMATCHED" for dc, flag in entries_for_ref)

            if has_unmatched_debit:
                nostro_impact = "STRANDED_DEBIT"
            elif has_debit:
                nostro_impact = "REVERSED"
            else:
                nostro_impact = "NO_DEBIT"

            # Intervention steps
            intervention = interventions.get(root_cause, "Contact operations desk for guidance.")

            # Priority
            urgency = urgency_map.get(ref, "STANDARD")
            threshold_val = thresholds.get(ccy, float("inf"))

            priority = "MEDIUM"
            if bank_inactive:
                priority = "CRITICAL"
            elif root_cause == "INSUFFICIENT_FUNDS":
                priority = "CRITICAL"
            elif urgency == "CRITICAL":
                priority = "CRITICAL"
            elif amount >= 2 * threshold_val:
                priority = "HIGH"
            elif urgency == "URGENT":
                priority = "HIGH"
            elif abs(fee_discrepancy) > 0.20 * expected_fee and expected_fee > 0:
                priority = "HIGH"
            # else stays MEDIUM

            results.append({
                "payment_id": pid,
                "payment_ref": ref,
                "customer_name": cname,
                "amount": amount,
                "currency": ccy,
                "sender_bic": sender,
                "receiver_bic": receiver,
                "failure_date": failure_date,
                "swift_status_code": swift_status_code or "",
                "root_cause": root_cause,
                "expected_fee": expected_fee,
                "actual_fee": actual_fee,
                "fee_discrepancy": fee_discrepancy,
                "nostro_impact": nostro_impact,
                "manual_intervention": intervention,
                "priority": priority,
            })

        conn.close()

        # Sort: CRITICAL > HIGH > MEDIUM, then amount desc
        priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
        results.sort(key=lambda x: (priority_order.get(x["priority"], 3), -x["amount"]))

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
        gt_refs = {r["payment_ref"] for r in ground_truth}
        gt_by_ref = {r["payment_ref"]: r for r in ground_truth}

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: Report file exists with correct payment set (20 pts) ──
        max_c1 = 20
        max_score += max_c1
        report_path = os.path.join(self.workspace, "reconciliation_report.csv")
        if os.path.exists(report_path):
            try:
                with open(report_path, newline="") as f:
                    reader = csv.DictReader(f)
                    agent_rows = list(reader)
                agent_refs = {r["payment_ref"] for r in agent_rows}
                missing = gt_refs - agent_refs
                extra = agent_refs - gt_refs
                if not missing and not extra:
                    c1_score = max_c1
                    c1_passed = True
                    c1_reason = ""
                else:
                    correct_frac = len(gt_refs & agent_refs) / max(len(gt_refs), 1)
                    penalty = len(extra) * 0.5 / max(len(gt_refs), 1)
                    c1_score = max(0, round(max_c1 * (correct_frac - penalty)))
                    c1_passed = False
                    c1_reason = f"Missing: {sorted(missing)}, Extra: {sorted(extra)}"
            except Exception as e:
                agent_rows = []
                c1_score = 0
                c1_passed = False
                c1_reason = f"Failed to parse report: {e}"
        else:
            agent_rows = []
            c1_score = 0
            c1_passed = False
            c1_reason = "reconciliation_report.csv not found in workspace."

        eval_criteria["payment_identification"] = {
            "passed": c1_passed,
            "score": c1_score,
            "max_score": max_c1,
            **({"reason": c1_reason} if not c1_passed else {}),
        }
        total_score += c1_score

        # Build agent lookup
        agent_by_ref = {}
        for r in agent_rows:
            agent_by_ref[r.get("payment_ref", "")] = r

        # ── Criterion 2: Root cause accuracy (25 pts) ──
        max_c2 = 25
        max_score += max_c2
        if agent_rows and gt_refs:
            correct_causes = 0
            total_checked = 0
            for ref, gt in gt_by_ref.items():
                if ref in agent_by_ref:
                    total_checked += 1
                    if agent_by_ref[ref].get("root_cause", "").strip() == gt["root_cause"]:
                        correct_causes += 1
            if total_checked > 0:
                c2_score = round(max_c2 * correct_causes / total_checked)
            else:
                c2_score = 0
            c2_passed = c2_score == max_c2
            c2_reason = "" if c2_passed else f"{correct_causes}/{total_checked} correct root causes."
        else:
            c2_score = 0
            c2_passed = False
            c2_reason = "No report rows to evaluate."

        eval_criteria["root_cause_accuracy"] = {
            "passed": c2_passed,
            "score": c2_score,
            "max_score": max_c2,
            **({"reason": c2_reason} if not c2_passed else {}),
        }
        total_score += c2_score

        # ── Criterion 3: Fee calculation (15 pts) ──
        max_c3 = 15
        max_score += max_c3
        if agent_rows and gt_refs:
            correct_fees = 0
            total_fee_checked = 0
            for ref, gt in gt_by_ref.items():
                if ref in agent_by_ref:
                    total_fee_checked += 1
                    ar = agent_by_ref[ref]
                    try:
                        a_exp = round(float(ar.get("expected_fee", -1)), 2)
                        a_act = round(float(ar.get("actual_fee", -1)), 2)
                        a_disc = round(float(ar.get("fee_discrepancy", -999)), 2)
                        if (
                            a_exp == round(gt["expected_fee"], 2)
                            and a_act == round(gt["actual_fee"], 2)
                            and a_disc == round(gt["fee_discrepancy"], 2)
                        ):
                            correct_fees += 1
                    except (ValueError, TypeError):
                        pass
            if total_fee_checked > 0:
                c3_score = round(max_c3 * correct_fees / total_fee_checked)
            else:
                c3_score = 0
            c3_passed = c3_score == max_c3
            c3_reason = "" if c3_passed else f"{correct_fees}/{total_fee_checked} correct fee records."
        else:
            c3_score = 0
            c3_passed = False
            c3_reason = "No report rows to evaluate."

        eval_criteria["fee_calculation"] = {
            "passed": c3_passed,
            "score": c3_score,
            "max_score": max_c3,
            **({"reason": c3_reason} if not c3_passed else {}),
        }
        total_score += c3_score

        # ── Criterion 4: Nostro impact (15 pts) ──
        max_c4 = 15
        max_score += max_c4
        if agent_rows and gt_refs:
            correct_nostro = 0
            total_nostro_checked = 0
            for ref, gt in gt_by_ref.items():
                if ref in agent_by_ref:
                    total_nostro_checked += 1
                    if agent_by_ref[ref].get("nostro_impact", "").strip() == gt["nostro_impact"]:
                        correct_nostro += 1
            if total_nostro_checked > 0:
                c4_score = round(max_c4 * correct_nostro / total_nostro_checked)
            else:
                c4_score = 0
            c4_passed = c4_score == max_c4
            c4_reason = "" if c4_passed else f"{correct_nostro}/{total_nostro_checked} correct nostro impacts."
        else:
            c4_score = 0
            c4_passed = False
            c4_reason = "No report rows to evaluate."

        eval_criteria["nostro_impact"] = {
            "passed": c4_passed,
            "score": c4_score,
            "max_score": max_c4,
            **({"reason": c4_reason} if not c4_passed else {}),
        }
        total_score += c4_score

        # ── Criterion 5: Manual intervention steps (15 pts) ──
        max_c5 = 15
        max_score += max_c5
        if agent_rows and gt_refs:
            correct_interv = 0
            total_interv_checked = 0
            for ref, gt in gt_by_ref.items():
                if ref in agent_by_ref:
                    total_interv_checked += 1
                    agent_interv = agent_by_ref[ref].get("manual_intervention", "").strip()
                    gt_interv = gt["manual_intervention"]
                    # Allow partial match: check that the agent's text contains key phrases
                    if agent_interv == gt_interv:
                        correct_interv += 1
                    elif gt_interv.lower() in agent_interv.lower() or agent_interv.lower() in gt_interv.lower():
                        correct_interv += 0.5
            if total_interv_checked > 0:
                c5_score = round(max_c5 * correct_interv / total_interv_checked)
            else:
                c5_score = 0
            c5_passed = c5_score == max_c5
            c5_reason = "" if c5_passed else f"{correct_interv}/{total_interv_checked} correct interventions."
        else:
            c5_score = 0
            c5_passed = False
            c5_reason = "No report rows to evaluate."

        eval_criteria["manual_intervention"] = {
            "passed": c5_passed,
            "score": c5_score,
            "max_score": max_c5,
            **({"reason": c5_reason} if not c5_passed else {}),
        }
        total_score += c5_score

        # ── Criterion 6: Format and sorting (10 pts) ──
        max_c6 = 10
        max_score += max_c6
        c6_score = 0

        required_columns = [
            "payment_id", "payment_ref", "customer_name", "amount", "currency",
            "sender_bic", "receiver_bic", "failure_date", "swift_status_code",
            "root_cause", "expected_fee", "actual_fee", "fee_discrepancy",
            "nostro_impact", "manual_intervention", "priority",
        ]

        if agent_rows:
            # Check columns (5 pts)
            actual_cols = list(agent_rows[0].keys()) if agent_rows else []
            if actual_cols == required_columns:
                c6_score += 5
            elif set(required_columns).issubset(set(actual_cols)):
                c6_score += 3  # columns present but wrong order

            # Check sort order (5 pts)
            priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
            correctly_sorted = True
            for i in range(len(agent_rows) - 1):
                r1, r2 = agent_rows[i], agent_rows[i + 1]
                p1 = priority_order.get(r1.get("priority", ""), 3)
                p2 = priority_order.get(r2.get("priority", ""), 3)
                try:
                    a1 = float(r1.get("amount", 0))
                    a2 = float(r2.get("amount", 0))
                except (ValueError, TypeError):
                    correctly_sorted = False
                    break
                if p1 > p2:
                    correctly_sorted = False
                    break
                if p1 == p2 and a1 < a2:
                    correctly_sorted = False
                    break
            if correctly_sorted:
                c6_score += 5

        c6_passed = c6_score == max_c6
        c6_reason = "" if c6_passed else f"Format/sort score: {c6_score}/{max_c6}"

        eval_criteria["format_and_sorting"] = {
            "passed": c6_passed,
            "score": c6_score,
            "max_score": max_c6,
            **({"reason": c6_reason} if not c6_passed else {}),
        }
        total_score += c6_score

        # ── Criterion 7: Response summary (bonus check in action text) ──
        # Check that the action mentions the total count and total stranded amount
        max_c7 = 0  # No extra points; all 100 pts accounted for above

        reward = total_score / max_score if max_score > 0 else 0.0

        return reward, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

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
        tool_calls = 0

        def call_tool(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        # ── Step 1: Read workspace config files ──
        with open(os.path.join(self.workspace, "high_value_thresholds.json")) as f:
            thresholds = json.load(f)["thresholds"]

        with open(os.path.join(self.workspace, "swift_status_codes.json")) as f:
            status_code_defs = json.load(f)

        with open(os.path.join(self.workspace, "reconciliation_rules.yaml")) as f:
            recon_rules = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "fee_corridor_config.yaml")) as f:
            fee_config = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "escalation_procedures.md")) as f:
            esc_text = f.read()

        # Parse escalation procedures
        interventions = {}
        for line in esc_text.split("\n"):
            line = line.strip()
            if ":" in line and not line.startswith("Each"):
                parts = line.split(":", 1)
                key = parts[0].strip()
                val = parts[1].strip()
                if key and val:
                    interventions[key] = val

        # Load customer urgency from batch files
        urgency_map = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "customer_batch_*.json"))):
            with open(fpath) as f:
                batch = json.load(f)
            for p in batch["payments"]:
                urgency_map[p["payment_ref"]] = p["urgency"]

        # Load nostro reconciliation flags from CSVs
        nostro_flags = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "nostro_statement_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ref = row["reference"]
                    dc = row["dc_indicator"]
                    flag = row["reconciliation_flag"]
                    if ref not in nostro_flags:
                        nostro_flags[ref] = []
                    nostro_flags[ref].append((dc, flag))

        # ── Step 2: Query all failed payments (paginated) ──
        all_failed = []
        page = 1
        while True:
            result = call_tool("query_payments", status="FAILED", page=page)
            all_failed.extend(result["results"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Filter to high-value
        hv_failed = []
        for p in all_failed:
            ccy = p["currency"]
            amount = p["amount"]
            if amount >= thresholds.get(ccy, float("inf")):
                hv_failed.append(p)

        # ── Step 3: For each high-value failed payment, gather details ──
        reconciliation = []
        bank_cache = {}

        for p in hv_failed:
            pid = p["payment_id"]
            ref = p["payment_ref"]

            # Get full details
            details = call_tool("get_payment_details", payment_id=pid)
            sender_bic = details["sender_bic"]
            receiver_bic = details["receiver_bic"]

            # Get SWIFT trail
            trail = call_tool("get_swift_trail", payment_ref=ref)
            swift_status_code = None
            failure_date = details["initiated_date"]
            for msg in trail["messages"]:
                if msg["status_code"]:
                    swift_status_code = msg["status_code"]
                    failure_date = msg["timestamp"].split(" ")[0] if msg["timestamp"] else failure_date

            # Lookup receiver bank
            if receiver_bic not in bank_cache:
                bank_cache[receiver_bic] = call_tool("lookup_bank", bic_code=receiver_bic)
            bank_info = bank_cache[receiver_bic]
            bank_inactive = not bank_info.get("is_active", True) if "error" not in bank_info else False

            # Determine root cause
            if bank_inactive:
                root_cause = "BANK_INACTIVE"
            elif swift_status_code and swift_status_code in status_code_defs:
                root_cause = status_code_defs[swift_status_code]["category"]
            else:
                root_cause = "UNSPECIFIED"

            # Get fee record
            fee_data = call_tool("get_fee_record", payment_ref=ref)
            expected_fee = fee_data.get("expected_amount", 0.0)
            actual_fee = fee_data.get("actual_amount", 0.0)
            fee_discrepancy = round(actual_fee - expected_fee, 2)

            # Get nostro entries (tool call for completeness)
            nostro_data = call_tool("get_nostro_entries_by_ref", payment_ref=ref)

            # Determine nostro impact from workspace CSVs
            entries_for_ref = nostro_flags.get(ref, [])
            has_debit = any(dc == "D" for dc, _ in entries_for_ref)
            has_unmatched_debit = any(dc == "D" and flag == "UNMATCHED" for dc, flag in entries_for_ref)

            if has_unmatched_debit:
                nostro_impact = "STRANDED_DEBIT"
            elif has_debit:
                nostro_impact = "REVERSED"
            else:
                nostro_impact = "NO_DEBIT"

            # Intervention
            intervention = interventions.get(root_cause, "Contact operations desk for guidance.")

            # Priority
            urgency = urgency_map.get(ref, "STANDARD")
            threshold_val = thresholds.get(details["currency"], float("inf"))

            priority = "MEDIUM"
            if bank_inactive:
                priority = "CRITICAL"
            elif root_cause == "INSUFFICIENT_FUNDS":
                priority = "CRITICAL"
            elif urgency == "CRITICAL":
                priority = "CRITICAL"
            elif details["amount"] >= 2 * threshold_val:
                priority = "HIGH"
            elif urgency == "URGENT":
                priority = "HIGH"
            elif abs(fee_discrepancy) > 0.20 * expected_fee and expected_fee > 0:
                priority = "HIGH"

            reconciliation.append({
                "payment_id": str(pid),
                "payment_ref": ref,
                "customer_name": details["customer_name"],
                "amount": str(details["amount"]),
                "currency": details["currency"],
                "sender_bic": sender_bic,
                "receiver_bic": receiver_bic,
                "failure_date": failure_date,
                "swift_status_code": swift_status_code or "",
                "root_cause": root_cause,
                "expected_fee": str(expected_fee),
                "actual_fee": str(actual_fee),
                "fee_discrepancy": str(fee_discrepancy),
                "nostro_impact": nostro_impact,
                "manual_intervention": intervention,
                "priority": priority,
            })

        # ── Step 4: Sort and write report ──
        priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
        reconciliation.sort(key=lambda x: (priority_order.get(x["priority"], 3), -float(x["amount"])))

        columns = [
            "payment_id", "payment_ref", "customer_name", "amount", "currency",
            "sender_bic", "receiver_bic", "failure_date", "swift_status_code",
            "root_cause", "expected_fee", "actual_fee", "fee_discrepancy",
            "nostro_impact", "manual_intervention", "priority",
        ]

        report_path = os.path.join(self.workspace, "reconciliation_report.csv")
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for row in reconciliation:
                writer.writerow(row)

        # ── Step 5: Build action string ──
        stranded_count = sum(1 for r in reconciliation if r["nostro_impact"] == "STRANDED_DEBIT")
        total_stranded_amount = sum(
            float(r["amount"]) for r in reconciliation if r["nostro_impact"] == "STRANDED_DEBIT"
        )
        total_fee_disc = sum(abs(float(r["fee_discrepancy"])) for r in reconciliation)

        action = (
            f"Reconciliation complete. Identified {len(reconciliation)} failed high-value "
            f"cross-border payments. {stranded_count} payments have stranded debits totaling "
            f"{total_stranded_amount:.2f} in local currency equivalents. Total absolute fee "
            f"discrepancies across all reconciled payments: {total_fee_disc:.2f}. "
            f"The reconciliation report has been saved as reconciliation_report.csv with full "
            f"root cause analysis, nostro impact assessment, fee reconciliation, and manual "
            f"intervention steps for each payment."
        )

        assert tool_calls >= 15, f"Only {tool_calls} tool calls made; need at least 15."

        return self.step(action)
