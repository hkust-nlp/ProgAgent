"""
Environment for Financial Regulation Reporting Threshold Task.
"""

import sqlite3
import os
import json
import csv
import glob
from typing import Tuple, Dict, List, Any
from datetime import datetime


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
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

    def _query_db(self, query, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    # ==================== TOOLS ====================

    @tool(
        description=(
            "List clients with pagination. Returns a page of client records "
            "including client_id, name, jurisdiction_code, client_type, "
            "registration_date, and status. Use status_filter to limit to "
            "active/inactive/suspended clients."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)."
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page. Default 20, max 50."
                },
                "status_filter": {
                    "type": "string",
                    "enum": ["active", "inactive", "suspended"],
                    "description": "Optional filter by client status."
                }
            },
            "required": ["page"]
        }
    )
    def list_clients(self, page: int, page_size: int = 20, status_filter: str = None):
        page_size = min(max(1, page_size), 50)
        offset = (max(1, page) - 1) * page_size

        if status_filter:
            total = self._query_db(
                "SELECT COUNT(*) as cnt FROM clients WHERE status = ?",
                (status_filter,)
            )[0]["cnt"]
            rows = self._query_db(
                "SELECT * FROM clients WHERE status = ? ORDER BY client_id LIMIT ? OFFSET ?",
                (status_filter, page_size, offset)
            )
        else:
            total = self._query_db("SELECT COUNT(*) as cnt FROM clients")[0]["cnt"]
            rows = self._query_db(
                "SELECT * FROM clients ORDER BY client_id LIMIT ? OFFSET ?",
                (page_size, offset)
            )

        return {
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": (total + page_size - 1) // page_size,
            "clients": rows
        }

    @tool(
        description=(
            "Get detailed information for a single client by their ID."
        ),
        parameters={
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's unique identifier."
                }
            },
            "required": ["client_id"]
        }
    )
    def get_client_details(self, client_id: int):
        rows = self._query_db(
            "SELECT * FROM clients WHERE client_id = ?", (client_id,)
        )
        if not rows:
            return {"error": f"Client {client_id} not found"}
        return rows[0]

    @tool(
        description=(
            "Retrieve transactions for a specific client. Can filter by "
            "transaction type and/or date range. Returns transaction records "
            "including txn_id, account_id, amount, txn_type, txn_date, "
            "currency, and counterparty. Results are paginated."
        ),
        parameters={
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's unique identifier."
                },
                "txn_type": {
                    "type": "string",
                    "description": "Optional filter: transaction type (e.g. wire_transfer, securities_trade)."
                },
                "start_date": {
                    "type": "string",
                    "description": "Optional filter: start date (YYYY-MM-DD inclusive)."
                },
                "end_date": {
                    "type": "string",
                    "description": "Optional filter: end date (YYYY-MM-DD inclusive)."
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1."
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page. Default 50, max 100."
                }
            },
            "required": ["client_id"]
        }
    )
    def get_client_transactions(self, client_id: int, txn_type: str = None,
                                 start_date: str = None, end_date: str = None,
                                 page: int = 1, page_size: int = 50):
        page_size = min(max(1, page_size), 100)
        offset = (max(1, page) - 1) * page_size

        conditions = ["client_id = ?"]
        params = [client_id]

        if txn_type:
            conditions.append("txn_type = ?")
            params.append(txn_type)
        if start_date:
            conditions.append("txn_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("txn_date <= ?")
            params.append(end_date)

        where = " AND ".join(conditions)

        total = self._query_db(
            f"SELECT COUNT(*) as cnt FROM transactions WHERE {where}", params
        )[0]["cnt"]

        rows = self._query_db(
            f"SELECT * FROM transactions WHERE {where} ORDER BY txn_date, txn_id LIMIT ? OFFSET ?",
            params + [page_size, offset]
        )

        return {
            "client_id": client_id,
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "transactions": rows
        }

    @tool(
        description=(
            "Retrieve previous report filings for a specific client. "
            "Returns report_id, report_type, filing_date, period_start, "
            "period_end, threshold_applied, total_reported_amount, "
            "jurisdiction_code, txn_type, and filing_status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's unique identifier."
                },
                "txn_type": {
                    "type": "string",
                    "description": "Optional filter by transaction type."
                }
            },
            "required": ["client_id"]
        }
    )
    def get_previous_reports(self, client_id: int, txn_type: str = None):
        if txn_type:
            rows = self._query_db(
                "SELECT * FROM previous_reports WHERE client_id = ? AND txn_type = ? ORDER BY filing_date DESC",
                (client_id, txn_type)
            )
        else:
            rows = self._query_db(
                "SELECT * FROM previous_reports WHERE client_id = ? ORDER BY filing_date DESC",
                (client_id,)
            )
        return {
            "client_id": client_id,
            "total_reports": len(rows),
            "reports": rows
        }

    @tool(
        description=(
            "Get account summary for a client, including account_id, "
            "account_number, account_type, balance, currency, and opened_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's unique identifier."
                }
            },
            "required": ["client_id"]
        }
    )
    def get_account_summary(self, client_id: int):
        rows = self._query_db(
            "SELECT * FROM accounts WHERE client_id = ? ORDER BY account_id",
            (client_id,)
        )
        return {
            "client_id": client_id,
            "total_accounts": len(rows),
            "accounts": rows
        }

    @tool(
        description=(
            "Look up the regulation clause that applies for a given "
            "transaction type, jurisdiction code, and client type. Returns "
            "the clause details including old_threshold and new_threshold."
        ),
        parameters={
            "type": "object",
            "properties": {
                "txn_type": {
                    "type": "string",
                    "description": "Transaction type (e.g. wire_transfer, securities_trade, foreign_exchange, derivative, cash_deposit, loan_disbursement)."
                },
                "jurisdiction_code": {
                    "type": "string",
                    "description": "Jurisdiction code (e.g. US-NY, UK-LON, EU-DE)."
                },
                "client_type": {
                    "type": "string",
                    "description": "Client type: individual, corporate, or institutional."
                }
            },
            "required": ["txn_type", "jurisdiction_code", "client_type"]
        }
    )
    def lookup_regulation_clause(self, txn_type: str, jurisdiction_code: str, client_type: str):
        rows = self._query_db(
            "SELECT * FROM regulation_clauses WHERE txn_type = ? AND jurisdiction_code = ? AND client_type = ?",
            (txn_type, jurisdiction_code, client_type)
        )
        if not rows:
            return {"error": f"No clause found for {txn_type}/{jurisdiction_code}/{client_type}"}
        return rows[0]

    @tool(
        description=(
            "List all distinct transaction types that appear in the "
            "transactions table."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    def list_transaction_types(self):
        rows = self._query_db(
            "SELECT DISTINCT txn_type FROM transactions ORDER BY txn_type"
        )
        return {"transaction_types": [r["txn_type"] for r in rows]}

    # ==================== STEP (Evaluation) ====================

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # Compute ground truth
        gt_rows = self._compute_ground_truth()

        # --- Criterion 1: impacted_clients.csv exists (10 pts) ---
        csv_path = os.path.join(self.workspace, "impacted_clients.csv")
        csv_exists = os.path.isfile(csv_path)
        c1_score = 10 if csv_exists else 0
        eval_criteria["csv_file_exists"] = {
            "passed": csv_exists,
            "score": c1_score,
            "max_score": 10,
            "reason": "" if csv_exists else "impacted_clients.csv not found in workspace"
        }
        total_score += c1_score
        max_score += 10

        if not csv_exists:
            # Can't check further
            for name, ms in [("correct_columns", 10), ("correct_client_count", 15),
                             ("correct_client_ids", 20), ("correct_amounts", 15),
                             ("correct_priorities", 15), ("correct_sorting", 15)]:
                eval_criteria[name] = {
                    "passed": False, "score": 0, "max_score": ms,
                    "reason": "CSV file missing"
                }
                max_score += ms

            # Response check
            resp_score, resp_criteria = self._check_response(action, gt_rows)
            eval_criteria.update(resp_criteria)
            total_score += resp_score
            max_score += sum(c["max_score"] for c in resp_criteria.values())

            return total_score / max_score, {
                "eval_criteria": eval_criteria,
                "total_score": total_score,
                "max_score": max_score,
            }

        # Parse submitted CSV
        submitted_rows = []
        try:
            with open(csv_path, "r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    submitted_rows.append(row)
        except Exception as e:
            eval_criteria["csv_parse"] = {
                "passed": False, "score": 0, "max_score": 0,
                "reason": f"Failed to parse CSV: {e}"
            }

        # --- Criterion 2: Correct columns (10 pts) ---
        expected_cols = [
            "client_id", "client_name", "jurisdiction_code", "transaction_type",
            "total_amount", "old_threshold", "new_threshold", "gap_amount",
            "previous_report_id", "disclosure_priority"
        ]
        if submitted_rows:
            actual_cols = list(submitted_rows[0].keys())
            cols_match = actual_cols == expected_cols
        else:
            actual_cols = []
            cols_match = False
        c2_score = 10 if cols_match else 0
        eval_criteria["correct_columns"] = {
            "passed": cols_match,
            "score": c2_score,
            "max_score": 10,
            "reason": "" if cols_match else f"Expected columns {expected_cols}, got {actual_cols}"
        }
        total_score += c2_score
        max_score += 10

        # --- Criterion 3: Correct number of impacted client rows (15 pts) ---
        count_match = len(submitted_rows) == len(gt_rows)
        c3_score = 15 if count_match else (7 if abs(len(submitted_rows) - len(gt_rows)) <= 3 else 0)
        eval_criteria["correct_client_count"] = {
            "passed": count_match,
            "score": c3_score,
            "max_score": 15,
            "reason": "" if count_match else f"Expected {len(gt_rows)} rows, got {len(submitted_rows)}"
        }
        total_score += c3_score
        max_score += 15

        # --- Criterion 4: Correct client_id + transaction_type pairs (20 pts) ---
        gt_pairs = set()
        for r in gt_rows:
            gt_pairs.add((str(r["client_id"]), r["transaction_type"]))
        sub_pairs = set()
        for r in submitted_rows:
            cid = r.get("client_id", "").strip()
            tt = r.get("transaction_type", "").strip()
            sub_pairs.add((cid, tt))
        if gt_pairs:
            overlap = len(gt_pairs & sub_pairs)
            pair_ratio = overlap / len(gt_pairs)
        else:
            pair_ratio = 1.0 if not sub_pairs else 0.0
        c4_score = round(20 * pair_ratio)
        eval_criteria["correct_client_ids"] = {
            "passed": pair_ratio == 1.0,
            "score": c4_score,
            "max_score": 20,
            "reason": "" if pair_ratio == 1.0 else f"Matched {overlap}/{len(gt_pairs)} client-txntype pairs"
        }
        total_score += c4_score
        max_score += 20

        # --- Criterion 5: Correct amounts (total_amount, gap_amount, thresholds) (15 pts) ---
        gt_lookup = {}
        for r in gt_rows:
            gt_lookup[(str(r["client_id"]), r["transaction_type"])] = r

        amount_correct = 0
        amount_total = 0
        for r in submitted_rows:
            key = (r.get("client_id", "").strip(), r.get("transaction_type", "").strip())
            if key in gt_lookup:
                gt_r = gt_lookup[key]
                amount_total += 4
                try:
                    if abs(float(r.get("total_amount", 0)) - gt_r["total_amount"]) < 0.01:
                        amount_correct += 1
                    if abs(float(r.get("old_threshold", 0)) - gt_r["old_threshold"]) < 0.01:
                        amount_correct += 1
                    if abs(float(r.get("new_threshold", 0)) - gt_r["new_threshold"]) < 0.01:
                        amount_correct += 1
                    if abs(float(r.get("gap_amount", 0)) - gt_r["gap_amount"]) < 0.01:
                        amount_correct += 1
                except (ValueError, TypeError):
                    pass

        amt_ratio = amount_correct / amount_total if amount_total > 0 else 0.0
        c5_score = round(15 * amt_ratio)
        eval_criteria["correct_amounts"] = {
            "passed": amt_ratio >= 0.99,
            "score": c5_score,
            "max_score": 15,
            "reason": "" if amt_ratio >= 0.99 else f"Amount accuracy: {amount_correct}/{amount_total}"
        }
        total_score += c5_score
        max_score += 15

        # --- Criterion 6: Correct disclosure_priority (15 pts) ---
        pri_correct = 0
        pri_total = 0
        for r in submitted_rows:
            key = (r.get("client_id", "").strip(), r.get("transaction_type", "").strip())
            if key in gt_lookup:
                pri_total += 1
                if r.get("disclosure_priority", "").strip() == gt_lookup[key]["disclosure_priority"]:
                    pri_correct += 1

        pri_ratio = pri_correct / pri_total if pri_total > 0 else 0.0
        c6_score = round(15 * pri_ratio)
        eval_criteria["correct_priorities"] = {
            "passed": pri_ratio >= 0.99,
            "score": c6_score,
            "max_score": 15,
            "reason": "" if pri_ratio >= 0.99 else f"Priority accuracy: {pri_correct}/{pri_total}"
        }
        total_score += c6_score
        max_score += 15

        # --- Criterion 7: Correct sorting (15 pts) ---
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        is_sorted = True
        for i in range(1, len(submitted_rows)):
            prev = submitted_rows[i - 1]
            curr = submitted_rows[i]
            prev_pri = priority_order.get(prev.get("disclosure_priority", "").strip(), 99)
            curr_pri = priority_order.get(curr.get("disclosure_priority", "").strip(), 99)
            if prev_pri < curr_pri:
                continue
            elif prev_pri > curr_pri:
                is_sorted = False
                break
            else:
                # Same priority, check gap_amount descending
                try:
                    prev_gap = float(prev.get("gap_amount", 0))
                    curr_gap = float(curr.get("gap_amount", 0))
                except (ValueError, TypeError):
                    is_sorted = False
                    break
                if prev_gap > curr_gap:
                    continue
                elif prev_gap < curr_gap:
                    is_sorted = False
                    break
                else:
                    # Tiebreaker: client_id ascending
                    try:
                        prev_cid = int(prev.get("client_id", 0))
                        curr_cid = int(curr.get("client_id", 0))
                    except (ValueError, TypeError):
                        is_sorted = False
                        break
                    if prev_cid > curr_cid:
                        is_sorted = False
                        break

        c7_score = 15 if is_sorted else 0
        eval_criteria["correct_sorting"] = {
            "passed": is_sorted,
            "score": c7_score,
            "max_score": 15,
            "reason": "" if is_sorted else "Rows not sorted by priority desc, gap_amount desc, client_id asc"
        }
        total_score += c7_score
        max_score += 15

        # --- Response checks ---
        resp_score, resp_criteria = self._check_response(action, gt_rows)
        eval_criteria.update(resp_criteria)
        total_score += resp_score
        max_score += sum(c["max_score"] for c in resp_criteria.values())

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    def _check_response(self, action: str, gt_rows: list) -> Tuple[int, dict]:
        """Check the agent's final text response for required summary info."""
        criteria = {}
        score = 0

        # Criterion: response mentions count of impacted clients
        n_impacted = len(gt_rows)
        # Count unique client_ids
        unique_clients = len(set(r["client_id"] for r in gt_rows))
        has_count = str(unique_clients) in action or str(n_impacted) in action
        c_score = 10 if has_count else 0
        criteria["response_impacted_count"] = {
            "passed": has_count,
            "score": c_score,
            "max_score": 10,
            "reason": "" if has_count else f"Response should mention {unique_clients} unique impacted clients or {n_impacted} impacted rows"
        }
        score += c_score

        return score, criteria

    def _compute_ground_truth(self) -> list:
        """Compute the ground truth list of impacted client rows."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load exemption data from workspace
        portfolio_data = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("client_portfolio_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    entries = json.load(f)
                    for e in entries:
                        portfolio_data[e["client_id"]] = e

        # Load priority matrix
        priority_matrix = []
        pm_path = os.path.join(self.workspace, "priority_matrix.csv")
        if os.path.isfile(pm_path):
            with open(pm_path, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    priority_matrix.append(row)

        # Get active clients
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clients WHERE status = 'active'")
        active_clients = [dict(r) for r in cursor.fetchall()]

        # Regulation effective date for exemption check
        reg_effective = datetime(2024, 7, 1)
        exemption_cutoff = datetime(2024, 4, 2)  # 90 days before effective date

        impacted_rows = []

        for client in active_clients:
            cid = client["client_id"]
            jur = client["jurisdiction_code"]
            ctype = client["client_type"]

            # Check exemption: registration date
            reg_date = datetime.strptime(client["registration_date"], "%Y-%m-%d")
            if reg_date >= exemption_cutoff:
                continue  # Exempt - newly registered

            # Check portfolio exemption
            portfolio = portfolio_data.get(cid, {})
            risk_rating = portfolio.get("risk_rating", "medium")
            compliance_tier = portfolio.get("compliance_tier", "standard")
            aml_flag = portfolio.get("aml_flag", False)

            if risk_rating == "low" and compliance_tier == "premium" and not aml_flag:
                continue  # Exempt

            # Get in-period transactions grouped by type
            cursor.execute(
                """SELECT txn_type, SUM(amount) as total_amount
                   FROM transactions
                   WHERE client_id = ? AND txn_date >= '2024-01-01' AND txn_date <= '2024-06-30'
                   GROUP BY txn_type""",
                (cid,)
            )
            txn_totals = {r["txn_type"]: r["total_amount"] for r in cursor.fetchall()}

            for txn_type, total_amount in txn_totals.items():
                # Look up regulation clause
                cursor.execute(
                    """SELECT * FROM regulation_clauses
                       WHERE txn_type = ? AND jurisdiction_code = ? AND client_type = ?""",
                    (txn_type, jur, ctype)
                )
                clause_row = cursor.fetchone()
                if not clause_row:
                    continue
                clause = dict(clause_row)

                old_threshold = clause["old_threshold"]
                new_threshold = clause["new_threshold"]

                # Impact condition: total >= new_threshold AND has previous report with old threshold
                if total_amount < new_threshold:
                    continue

                # Check for previous report with this txn_type using old threshold
                cursor.execute(
                    """SELECT * FROM previous_reports
                       WHERE client_id = ? AND txn_type = ?
                       ORDER BY filing_date DESC""",
                    (cid, txn_type)
                )
                prev_reports = [dict(r) for r in cursor.fetchall()]
                if not prev_reports:
                    continue

                # Find the most recent report
                most_recent = prev_reports[0]
                if abs(most_recent["threshold_applied"] - old_threshold) > 0.01:
                    continue  # Previous report didn't use the old threshold

                total_amount_rounded = round(total_amount, 2)
                gap_amount = round(total_amount_rounded - new_threshold, 2)

                # Determine priority
                gap_ratio = gap_amount / new_threshold if new_threshold > 0 else 999
                priority = self._get_priority(risk_rating, gap_ratio, priority_matrix)

                impacted_rows.append({
                    "client_id": cid,
                    "client_name": client["name"],
                    "jurisdiction_code": jur,
                    "transaction_type": txn_type,
                    "total_amount": total_amount_rounded,
                    "old_threshold": old_threshold,
                    "new_threshold": new_threshold,
                    "gap_amount": gap_amount,
                    "previous_report_id": most_recent["report_id"],
                    "disclosure_priority": priority,
                })

        conn.close()

        # Sort: priority (critical > high > medium > low), gap_amount desc, client_id asc
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        impacted_rows.sort(key=lambda r: (
            priority_order.get(r["disclosure_priority"], 99),
            -r["gap_amount"],
            r["client_id"]
        ))

        return impacted_rows

    def _get_priority(self, risk_rating: str, gap_ratio: float, priority_matrix: list) -> str:
        for row in priority_matrix:
            if row["risk_rating"] == risk_rating:
                if float(row["gap_ratio_min"]) <= gap_ratio < float(row["gap_ratio_max"]):
                    return row["disclosure_priority"]
        # Fallback
        if gap_ratio >= 1.0:
            return "critical"
        elif gap_ratio >= 0.5:
            return "high"
        elif gap_ratio >= 0.0:
            return "medium"
        return "low"

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
        # Read regulation update
        with open(os.path.join(self.workspace, "regulation_update.yaml")) as f:
            reg_data = _yaml.safe_load(f)
        regulation = reg_data["regulation"]
        period_start = regulation["reporting_period"]["start"]
        period_end = regulation["reporting_period"]["end"]

        # Read exemption policy
        with open(os.path.join(self.workspace, "exemption_policy.txt")) as f:
            exemption_text = f.read()

        # Read priority matrix
        priority_matrix = []
        with open(os.path.join(self.workspace, "priority_matrix.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                priority_matrix.append(row)

        # Read disclosure format spec
        with open(os.path.join(self.workspace, "disclosure_format_spec.md")) as f:
            format_spec = f.read()

        # Read all client portfolio files
        portfolio_data = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("client_portfolio_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    entries = json.load(f)
                    for e in entries:
                        portfolio_data[e["client_id"]] = e

        # Step 2: Get all active clients via tool
        all_active_clients = []
        page = 1
        while True:
            result = call_tool("list_clients", page=page, page_size=20, status_filter="active")
            all_active_clients.extend(result["clients"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 3: Get transaction types
        txn_types_result = call_tool("list_transaction_types")
        txn_types = txn_types_result["transaction_types"]

        # Exemption cutoff: 90 days before 2024-07-01 = 2024-04-02
        from datetime import datetime as dt
        exemption_cutoff = "2024-04-02"

        impacted_rows = []

        # Step 4: For each active client, check impact
        for client in all_active_clients:
            cid = client["client_id"]
            jur = client["jurisdiction_code"]
            ctype = client["client_type"]
            reg_date = client["registration_date"]

            # Check exemption: newly registered
            if reg_date >= exemption_cutoff:
                continue

            # Check portfolio exemption
            portfolio = portfolio_data.get(cid, {})
            risk_rating = portfolio.get("risk_rating", "medium")
            compliance_tier = portfolio.get("compliance_tier", "standard")
            aml_flag = portfolio.get("aml_flag", False)

            if risk_rating == "low" and compliance_tier == "premium" and not aml_flag:
                continue

            # Get in-period transactions
            txn_result = call_tool(
                "get_client_transactions",
                client_id=cid,
                start_date=period_start,
                end_date=period_end
            )
            transactions = txn_result["transactions"]
            # Handle pagination
            while txn_result["page"] < txn_result["total_pages"]:
                txn_result = call_tool(
                    "get_client_transactions",
                    client_id=cid,
                    start_date=period_start,
                    end_date=period_end,
                    page=txn_result["page"] + 1
                )
                transactions.extend(txn_result["transactions"])

            if not transactions:
                continue

            # Group by txn_type
            txn_totals = {}
            for txn in transactions:
                tt = txn["txn_type"]
                txn_totals[tt] = txn_totals.get(tt, 0) + txn["amount"]

            for txn_type, total_amount in txn_totals.items():
                # Look up regulation clause
                clause = call_tool(
                    "lookup_regulation_clause",
                    txn_type=txn_type,
                    jurisdiction_code=jur,
                    client_type=ctype
                )
                if "error" in clause:
                    continue

                old_threshold = clause["old_threshold"]
                new_threshold = clause["new_threshold"]

                if total_amount < new_threshold:
                    continue

                # Get previous reports
                reports_result = call_tool(
                    "get_previous_reports",
                    client_id=cid,
                    txn_type=txn_type
                )
                prev_reports = reports_result["reports"]
                if not prev_reports:
                    continue

                most_recent = prev_reports[0]  # Already sorted by filing_date DESC
                if abs(most_recent["threshold_applied"] - old_threshold) > 0.01:
                    continue

                total_amount_rounded = round(total_amount, 2)
                gap_amount = round(total_amount_rounded - new_threshold, 2)

                # Determine priority
                gap_ratio = gap_amount / new_threshold if new_threshold > 0 else 999
                priority = self._get_priority_from_matrix(risk_rating, gap_ratio, priority_matrix)

                impacted_rows.append({
                    "client_id": cid,
                    "client_name": client["name"],
                    "jurisdiction_code": jur,
                    "transaction_type": txn_type,
                    "total_amount": total_amount_rounded,
                    "old_threshold": old_threshold,
                    "new_threshold": new_threshold,
                    "gap_amount": gap_amount,
                    "previous_report_id": most_recent["report_id"],
                    "disclosure_priority": priority,
                })

        # Sort
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        impacted_rows.sort(key=lambda r: (
            priority_order.get(r["disclosure_priority"], 99),
            -r["gap_amount"],
            r["client_id"]
        ))

        # Write impacted_clients.csv
        csv_path = os.path.join(self.workspace, "impacted_clients.csv")
        fieldnames = [
            "client_id", "client_name", "jurisdiction_code", "transaction_type",
            "total_amount", "old_threshold", "new_threshold", "gap_amount",
            "previous_report_id", "disclosure_priority"
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in impacted_rows:
                writer.writerow({
                    "client_id": row["client_id"],
                    "client_name": row["client_name"],
                    "jurisdiction_code": row["jurisdiction_code"],
                    "transaction_type": row["transaction_type"],
                    "total_amount": f"{row['total_amount']:.2f}",
                    "old_threshold": f"{row['old_threshold']:.2f}",
                    "new_threshold": f"{row['new_threshold']:.2f}",
                    "gap_amount": f"{row['gap_amount']:.2f}",
                    "previous_report_id": row["previous_report_id"],
                    "disclosure_priority": row["disclosure_priority"],
                })

        # Build response
        unique_clients = len(set(r["client_id"] for r in impacted_rows))
        total_rows = len(impacted_rows)
        total_gap = sum(r["gap_amount"] for r in impacted_rows)

        priority_counts = {}
        for r in impacted_rows:
            p = r["disclosure_priority"]
            priority_counts[p] = priority_counts.get(p, 0) + 1

        action = (
            f"Impact assessment complete under Regulation FRT-2024. "
            f"Identified {unique_clients} unique impacted clients across {total_rows} "
            f"client-transaction type combinations requiring updated disclosures. "
            f"Total gap exposure: ${total_gap:,.2f}. "
            f"Priority breakdown: "
            + ", ".join(f"{p}: {c}" for p, c in sorted(priority_counts.items(),
                        key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x[0], 99)))
            + ". "
            f"Results saved to impacted_clients.csv."
        )

        print(f"verify: {tool_call_count} tool calls made")
        return self.step(action)

    def _get_priority_from_matrix(self, risk_rating: str, gap_ratio: float, priority_matrix: list) -> str:
        for row in priority_matrix:
            if row["risk_rating"] == risk_rating:
                if float(row["gap_ratio_min"]) <= gap_ratio < float(row["gap_ratio_max"]):
                    return row["disclosure_priority"]
        if gap_ratio >= 1.0:
            return "critical"
        elif gap_ratio >= 0.5:
            return "high"
        elif gap_ratio >= 0.0:
            return "medium"
        return "low"
