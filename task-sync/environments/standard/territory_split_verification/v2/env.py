"""
Environment for royalty overpayment detection task.
Defines tools for querying payment/contract data and evaluates agent's recovery claims.
"""

import csv
import glob as glob_module
import io
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

    PAGE_SIZE = 20

    # ------------------------------------------------------------------ tools

    @tool(
        description="List artists with basic information. Returns a paginated list.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-based.",
                }
            },
            "required": ["page"],
        },
    )
    def list_artists(self, page: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM artists")
        total = cur.fetchone()["cnt"]
        offset = (page - 1) * self.PAGE_SIZE
        cur.execute(
            "SELECT artist_id, name, label, genre, country "
            "FROM artists ORDER BY artist_id LIMIT ? OFFSET ?",
            (self.PAGE_SIZE, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "page": page,
            "total": total,
            "total_pages": (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE,
            "artists": rows,
        }

    @tool(
        description=(
            "Retrieve all active contracts for a given artist. "
            "Each contract specifies the territory and negotiated revenue share percentage."
        ),
        parameters={
            "type": "object",
            "properties": {
                "artist_id": {
                    "type": "integer",
                    "description": "The artist's unique identifier.",
                }
            },
            "required": ["artist_id"],
        },
    )
    def get_artist_contracts(self, artist_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT contract_id, artist_id, territory_code, revenue_share_pct, "
            "start_date, end_date, status "
            "FROM contracts WHERE artist_id = ? ORDER BY territory_code",
            (artist_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"artist_id": artist_id, "contracts": rows}

    @tool(
        description=(
            "List payment records with pagination. Each record shows the sale reference, "
            "the actual territory of the sale, the territory whose rates were applied "
            "during payment processing, and the amount paid."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-based.",
                }
            },
            "required": ["page"],
        },
    )
    def list_payments(self, page: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM payments")
        total = cur.fetchone()["cnt"]
        offset = (page - 1) * self.PAGE_SIZE
        cur.execute(
            "SELECT payment_id, sale_ref, artist_id, territory_code, "
            "applied_territory_code, amount_paid, payment_date, status "
            "FROM payments ORDER BY payment_id LIMIT ? OFFSET ?",
            (self.PAGE_SIZE, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "page": page,
            "total": total,
            "total_pages": (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE,
            "payments": rows,
        }

    @tool(
        description="Get full details of a single payment by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "payment_id": {
                    "type": "integer",
                    "description": "The payment's unique identifier.",
                }
            },
            "required": ["payment_id"],
        },
    )
    def get_payment_detail(self, payment_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM payments WHERE payment_id = ?", (payment_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Payment {payment_id} not found"}

    @tool(
        description="Look up territory information by its two-letter code.",
        parameters={
            "type": "object",
            "properties": {
                "territory_code": {
                    "type": "string",
                    "description": "Two-letter territory code, e.g. 'US', 'GB'.",
                }
            },
            "required": ["territory_code"],
        },
    )
    def get_territory_info(self, territory_code: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT territory_id, code, name, region, is_domestic "
            "FROM territories WHERE code = ?",
            (territory_code,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Territory '{territory_code}' not found"}

    # -------------------------------------------------------------- helpers

    def _compute_ground_truth(self):
        """Compute the authoritative set of overpayment claims from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # All payments where territory mismatch
        cur.execute(
            "SELECT * FROM payments WHERE territory_code != applied_territory_code"
        )
        mismatched = [dict(r) for r in cur.fetchall()]

        # Contracts lookup
        cur.execute("SELECT artist_id, territory_code, revenue_share_pct FROM contracts")
        contract_map = {}
        for r in cur.fetchall():
            contract_map[(r["artist_id"], r["territory_code"])] = r["revenue_share_pct"]

        # Artist names
        cur.execute("SELECT artist_id, name FROM artists")
        artist_names = {r["artist_id"]: r["name"] for r in cur.fetchall()}

        conn.close()

        # Tax treaties from workspace
        with open(os.path.join(self.workspace, "tax_treaties.yaml")) as f:
            tax_data = yaml.safe_load(f)["tax_treaties"]

        # Policy config
        with open(os.path.join(self.workspace, "policy_config.yaml")) as f:
            policy = yaml.safe_load(f)["overpayment_policy"]
        threshold = policy["minimum_threshold"]
        priority_rules = policy["recovery_priority_rules"]

        # Sales from CSVs
        sales_map = {}
        reports_dir = os.path.join(self.workspace, "reports")
        for csv_file in sorted(glob_module.glob(os.path.join(reports_dir, "*.csv"))):
            with open(csv_file, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sales_map[row["sale_ref"]] = row

        # Compute claims
        claims = []
        for p in mismatched:
            sale = sales_map.get(p["sale_ref"])
            if not sale:
                continue
            gross_revenue = float(sale["gross_revenue"])
            actual_tc = p["territory_code"]
            correct_rate = contract_map.get((p["artist_id"], actual_tc))
            if correct_rate is None:
                continue
            wh_rate = tax_data[actual_tc]["withholding_rate"]
            correct_amount = round(gross_revenue * correct_rate * (1 - wh_rate), 2)
            overpayment = round(p["amount_paid"] - correct_amount, 2)

            if overpayment > threshold:
                if overpayment >= priority_rules["high"]["min_overpayment"]:
                    priority = "high"
                elif overpayment >= priority_rules["medium"]["min_overpayment"]:
                    priority = "medium"
                else:
                    priority = "low"

                claims.append({
                    "payment_id": p["payment_id"],
                    "artist_name": artist_names[p["artist_id"]],
                    "territory_code": actual_tc,
                    "applied_territory_code": p["applied_territory_code"],
                    "gross_revenue": gross_revenue,
                    "correct_amount": correct_amount,
                    "paid_amount": p["amount_paid"],
                    "overpayment_amount": overpayment,
                    "recovery_priority": priority,
                })

        # Sort by overpayment desc, payment_id asc
        claims.sort(key=lambda x: (-x["overpayment_amount"], x["payment_id"]))

        # Assign claim IDs
        for i, c in enumerate(claims):
            c["claim_id"] = f"RC-{i + 1:04d}"

        return claims

    # --------------------------------------------------------------- step

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
        gt_claims = self._compute_ground_truth()
        gt_payment_ids = {c["payment_id"] for c in gt_claims}
        gt_amount_map = {c["payment_id"]: c for c in gt_claims}
        gt_total_claims = len(gt_claims)
        gt_total_recovery = round(sum(c["overpayment_amount"] for c in gt_claims), 2)

        eval_criteria = {}
        total_score = 0.0
        max_score = 0.0

        # ---- Criterion 1: file exists (10 pts) ----
        claims_path = os.path.join(self.workspace, "recovery_claims.csv")
        file_exists = os.path.exists(claims_path)
        c1_score = 10.0 if file_exists else 0.0
        eval_criteria["file_exists"] = {
            "passed": file_exists,
            "score": c1_score,
            "max_score": 10.0,
        }
        if not file_exists:
            eval_criteria["file_exists"]["reason"] = "recovery_claims.csv not found"
        total_score += c1_score
        max_score += 10.0

        # If file missing, remaining file-based criteria score 0
        submitted_rows = []
        submitted_columns = []

        if file_exists:
            with open(claims_path, newline="") as f:
                content = f.read()
            if content.strip():
                reader = csv.DictReader(io.StringIO(content))
                submitted_rows = list(reader)
                submitted_columns = list(reader.fieldnames) if reader.fieldnames else []

        expected_columns = [
            "claim_id", "payment_id", "artist_name", "territory_code",
            "applied_territory_code", "gross_revenue", "correct_amount",
            "paid_amount", "overpayment_amount", "recovery_priority",
        ]

        # ---- Criterion 2: correct columns (10 pts) ----
        cols_match = submitted_columns == expected_columns
        c2_score = 10.0 if cols_match else 0.0
        eval_criteria["correct_columns"] = {
            "passed": cols_match,
            "score": c2_score,
            "max_score": 10.0,
        }
        if not cols_match:
            eval_criteria["correct_columns"]["reason"] = (
                f"Expected {expected_columns}, got {submitted_columns}"
            )
        total_score += c2_score
        max_score += 10.0

        # ---- Criterion 3: correct identification of overpayments (25 pts) ----
        sub_pids = set()
        for row in submitted_rows:
            try:
                sub_pids.add(int(row.get("payment_id", -1)))
            except (ValueError, TypeError):
                pass

        correct_ids = gt_payment_ids & sub_pids
        false_pos = sub_pids - gt_payment_ids
        missed = gt_payment_ids - sub_pids

        if gt_total_claims > 0:
            recall = len(correct_ids) / gt_total_claims
            fp_penalty = len(false_pos) / gt_total_claims
            c3_score = round(max(0, 25.0 * recall - 5.0 * fp_penalty), 2)
            c3_score = min(25.0, c3_score)
        else:
            c3_score = 25.0 if len(sub_pids) == 0 else 0.0

        eval_criteria["correct_identification"] = {
            "passed": c3_score == 25.0,
            "score": c3_score,
            "max_score": 25.0,
        }
        if c3_score < 25.0:
            eval_criteria["correct_identification"]["reason"] = (
                f"Correct={len(correct_ids)}/{gt_total_claims}, "
                f"FP={len(false_pos)}, Missed={len(missed)}"
            )
        total_score += c3_score
        max_score += 25.0

        # ---- Criterion 4: correct overpayment amounts (25 pts) ----
        amount_correct = 0
        for row in submitted_rows:
            try:
                pid = int(row["payment_id"])
                if pid in gt_amount_map:
                    expected = gt_amount_map[pid]["overpayment_amount"]
                    submitted = float(row["overpayment_amount"])
                    if abs(submitted - expected) < 0.02:
                        amount_correct += 1
            except (ValueError, KeyError, TypeError):
                pass

        if gt_total_claims > 0:
            c4_score = round(25.0 * amount_correct / gt_total_claims, 2)
        else:
            c4_score = 25.0
        eval_criteria["correct_amounts"] = {
            "passed": c4_score == 25.0,
            "score": c4_score,
            "max_score": 25.0,
        }
        if c4_score < 25.0:
            eval_criteria["correct_amounts"]["reason"] = (
                f"Correct amounts: {amount_correct}/{gt_total_claims}"
            )
        total_score += c4_score
        max_score += 25.0

        # ---- Criterion 5: correct priority assignment (10 pts) ----
        priority_correct = 0
        for row in submitted_rows:
            try:
                pid = int(row["payment_id"])
                if pid in gt_amount_map:
                    if row.get("recovery_priority", "").strip() == gt_amount_map[pid]["recovery_priority"]:
                        priority_correct += 1
            except (ValueError, KeyError):
                pass

        if gt_total_claims > 0:
            c5_score = round(10.0 * priority_correct / gt_total_claims, 2)
        else:
            c5_score = 10.0
        eval_criteria["correct_priority"] = {
            "passed": c5_score == 10.0,
            "score": c5_score,
            "max_score": 10.0,
        }
        if c5_score < 10.0:
            eval_criteria["correct_priority"]["reason"] = (
                f"Correct priorities: {priority_correct}/{gt_total_claims}"
            )
        total_score += c5_score
        max_score += 10.0

        # ---- Criterion 6: correct sorting (10 pts) ----
        sorting_correct = False
        if len(submitted_rows) == len(gt_claims) and len(gt_claims) > 0:
            sorting_correct = True
            for sub_row, gt_row in zip(submitted_rows, gt_claims):
                try:
                    if int(sub_row["payment_id"]) != gt_row["payment_id"]:
                        sorting_correct = False
                        break
                except (ValueError, KeyError):
                    sorting_correct = False
                    break

        c6_score = 10.0 if sorting_correct else 0.0
        eval_criteria["correct_sorting"] = {
            "passed": sorting_correct,
            "score": c6_score,
            "max_score": 10.0,
        }
        if not sorting_correct:
            eval_criteria["correct_sorting"]["reason"] = (
                "Rows not sorted by overpayment_amount descending then payment_id ascending, "
                "or row count mismatch"
            )
        total_score += c6_score
        max_score += 10.0

        # ---- Criterion 7: response summary (10 pts) ----
        summary_score = 0.0
        if str(gt_total_claims) in action:
            summary_score += 5.0
        recovery_plain = f"{gt_total_recovery:.2f}"
        recovery_comma = f"{gt_total_recovery:,.2f}"
        if recovery_plain in action or recovery_comma in action:
            summary_score += 5.0

        eval_criteria["response_summary"] = {
            "passed": summary_score == 10.0,
            "score": summary_score,
            "max_score": 10.0,
        }
        if summary_score < 10.0:
            eval_criteria["response_summary"]["reason"] = (
                f"Expected total claims={gt_total_claims}, "
                f"total recovery={recovery_plain} in response"
            )
        total_score += summary_score
        max_score += 10.0

        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ------------------------------------------------------------- verify

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
        # --- Step 1: Read workspace files ---
        # Read all sales report CSVs
        reports_dir = os.path.join(self.workspace, "reports")
        sales_map = {}
        for csv_file in sorted(glob_module.glob(os.path.join(reports_dir, "*.csv"))):
            with open(csv_file, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sales_map[row["sale_ref"]] = row

        # Read tax treaties
        with open(os.path.join(self.workspace, "tax_treaties.yaml")) as f:
            tax_data = yaml.safe_load(f)["tax_treaties"]

        # Read policy config
        with open(os.path.join(self.workspace, "policy_config.yaml")) as f:
            policy = yaml.safe_load(f)["overpayment_policy"]
        threshold = policy["minimum_threshold"]
        priority_rules = policy["recovery_priority_rules"]

        # --- Step 2: Get all artists via tools ---
        artist_names = {}
        page = 1
        while True:
            result = self.tools["list_artists"](page=page)
            for a in result["artists"]:
                artist_names[a["artist_id"]] = a["name"]
            if page >= result["total_pages"]:
                break
            page += 1

        # --- Step 3: Get all payments via tools ---
        all_payments = []
        page = 1
        while True:
            result = self.tools["list_payments"](page=page)
            all_payments.extend(result["payments"])
            if page >= result["total_pages"]:
                break
            page += 1

        # --- Step 4: Identify mismatched territory payments ---
        mismatched = [
            p for p in all_payments
            if p["territory_code"] != p["applied_territory_code"]
        ]

        # --- Step 5: Get contracts for relevant artists ---
        contract_cache = {}  # artist_id -> {territory_code: rate}
        for p in mismatched:
            aid = p["artist_id"]
            if aid not in contract_cache:
                result = self.tools["get_artist_contracts"](artist_id=aid)
                contract_cache[aid] = {
                    c["territory_code"]: c["revenue_share_pct"]
                    for c in result["contracts"]
                }

        # --- Step 6: Also look up territory info for a few territories ---
        # (This demonstrates use of get_territory_info; in practice,
        #  territory_reference.json gives the same data.)
        territory_info_cache = {}
        unique_territories = set()
        for p in mismatched:
            unique_territories.add(p["territory_code"])
            unique_territories.add(p["applied_territory_code"])
        for tc in sorted(unique_territories):
            territory_info_cache[tc] = self.tools["get_territory_info"](
                territory_code=tc
            )

        # --- Step 7: Compute overpayments ---
        claims = []
        for p in mismatched:
            sale = sales_map.get(p["sale_ref"])
            if not sale:
                continue
            gross_revenue = float(sale["gross_revenue"])
            actual_tc = p["territory_code"]

            rates = contract_cache.get(p["artist_id"], {})
            correct_rate = rates.get(actual_tc)
            if correct_rate is None:
                continue

            wh_rate = tax_data[actual_tc]["withholding_rate"]
            correct_amount = round(gross_revenue * correct_rate * (1 - wh_rate), 2)
            overpayment = round(p["amount_paid"] - correct_amount, 2)

            if overpayment > threshold:
                if overpayment >= priority_rules["high"]["min_overpayment"]:
                    priority = "high"
                elif overpayment >= priority_rules["medium"]["min_overpayment"]:
                    priority = "medium"
                else:
                    priority = "low"

                claims.append({
                    "payment_id": p["payment_id"],
                    "artist_name": artist_names[p["artist_id"]],
                    "territory_code": actual_tc,
                    "applied_territory_code": p["applied_territory_code"],
                    "gross_revenue": gross_revenue,
                    "correct_amount": correct_amount,
                    "paid_amount": p["amount_paid"],
                    "overpayment_amount": overpayment,
                    "recovery_priority": priority,
                })

        # Sort by overpayment_amount descending, payment_id ascending
        claims.sort(key=lambda x: (-x["overpayment_amount"], x["payment_id"]))

        # Assign claim IDs
        for i, c in enumerate(claims):
            c["claim_id"] = f"RC-{i + 1:04d}"

        # --- Step 8: Write recovery_claims.csv ---
        fieldnames = [
            "claim_id", "payment_id", "artist_name", "territory_code",
            "applied_territory_code", "gross_revenue", "correct_amount",
            "paid_amount", "overpayment_amount", "recovery_priority",
        ]
        output_path = os.path.join(self.workspace, "recovery_claims.csv")
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for c in claims:
                writer.writerow({
                    "claim_id": c["claim_id"],
                    "payment_id": c["payment_id"],
                    "artist_name": c["artist_name"],
                    "territory_code": c["territory_code"],
                    "applied_territory_code": c["applied_territory_code"],
                    "gross_revenue": f"{c['gross_revenue']:.2f}",
                    "correct_amount": f"{c['correct_amount']:.2f}",
                    "paid_amount": f"{c['paid_amount']:.2f}",
                    "overpayment_amount": f"{c['overpayment_amount']:.2f}",
                    "recovery_priority": c["recovery_priority"],
                })

        # --- Step 9: Build response ---
        total_claims = len(claims)
        total_recovery = round(sum(c["overpayment_amount"] for c in claims), 2)

        territory_breakdown = {}
        for c in claims:
            tc = c["territory_code"]
            if tc not in territory_breakdown:
                territory_breakdown[tc] = {"count": 0, "total": 0.0}
            territory_breakdown[tc]["count"] += 1
            territory_breakdown[tc]["total"] = round(
                territory_breakdown[tc]["total"] + c["overpayment_amount"], 2
            )

        action = (
            f"Total overpayment claims: {total_claims}\n"
            f"Total recovery amount: {total_recovery:.2f}\n\n"
            f"Breakdown by territory:\n"
        )
        for tc in sorted(territory_breakdown.keys()):
            info = territory_breakdown[tc]
            action += f"  {tc}: {info['count']} claims, ${info['total']:.2f}\n"

        return self.step(action)
