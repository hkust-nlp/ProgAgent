"""
Environment for credit-risk delinquency identification task.
Provides tools for querying customer, invoice, order, and payment data,
and evaluates the agent's at-risk account identification and contact list.
"""
import csv
import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

import yaml


# ── Tool decorator ──────────────────────────────────────────────────────────
def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


REFERENCE_DATE = datetime(2026, 3, 31)


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

    # ── Helper ──────────────────────────────────────────────────────────
    def _query(self, sql: str, params: tuple = ()) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    # ── Tools ───────────────────────────────────────────────────────────
    @tool(
        description=(
            "List customer accounts with optional filters. Returns a paginated "
            "list of customer IDs and company names. Use page and page_size to "
            "iterate through all customers."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 25). Default 20.",
                },
                "industry_filter": {
                    "type": "string",
                    "description": "Filter by industry code (e.g. 'TECH'). Optional.",
                },
                "status_filter": {
                    "type": "string",
                    "description": "Filter by account status (e.g. 'active'). Optional.",
                },
            },
            "required": [],
        },
    )
    def list_customers(
        self,
        page: int = 1,
        page_size: int = 20,
        industry_filter: str = None,
        status_filter: str = None,
    ) -> dict:
        page_size = min(page_size, 25)
        offset = (max(1, page) - 1) * page_size
        conditions = []
        params = []
        if industry_filter:
            conditions.append("industry_code = ?")
            params.append(industry_filter)
        if status_filter:
            conditions.append("account_status = ?")
            params.append(status_filter)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        count_sql = f"SELECT COUNT(*) as cnt FROM customers{where}"
        total = self._query(count_sql, tuple(params))[0]["cnt"]

        sql = (
            f"SELECT customer_id, company_name, industry_code, account_status "
            f"FROM customers{where} ORDER BY customer_id "
            f"LIMIT ? OFFSET ?"
        )
        params.extend([page_size, offset])
        rows = self._query(sql, tuple(params))
        return {
            "customers": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description=(
            "Get detailed information for a specific customer account including "
            "credit limit, payment terms, contact information, and account status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Customer ID (e.g. 'CUST-00001').",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_customer_details(self, customer_id: str) -> dict:
        rows = self._query(
            "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
        )
        if not rows:
            return {"error": f"Customer {customer_id} not found."}
        return rows[0]

    @tool(
        description=(
            "Get invoice aging summary for a customer. Returns outstanding amounts "
            "grouped by aging bucket (current, 31-60, 61-90, 91-120, 121+ days past due) "
            "and a list of individual unpaid/partial invoices."
        ),
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Customer ID.",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_invoice_aging(self, customer_id: str) -> dict:
        invoices = self._query(
            "SELECT * FROM invoices WHERE customer_id = ? ORDER BY due_date",
            (customer_id,),
        )
        buckets = {
            "current": 0.0,
            "bucket_31_60": 0.0,
            "bucket_61_90": 0.0,
            "bucket_91_120": 0.0,
            "bucket_121_plus": 0.0,
        }
        unpaid_invoices = []
        ref = REFERENCE_DATE
        for inv in invoices:
            outstanding = inv["amount"] - inv["paid_amount"]
            if outstanding <= 0:
                continue
            if inv["status"] not in ("overdue", "open", "partial"):
                continue
            due = datetime.strptime(inv["due_date"], "%Y-%m-%d")
            days_past = (ref - due).days
            if days_past <= 30:
                buckets["current"] += outstanding
            elif days_past <= 60:
                buckets["bucket_31_60"] += outstanding
            elif days_past <= 90:
                buckets["bucket_61_90"] += outstanding
            elif days_past <= 120:
                buckets["bucket_91_120"] += outstanding
            else:
                buckets["bucket_121_plus"] += outstanding
            unpaid_invoices.append({
                "invoice_id": inv["invoice_id"],
                "due_date": inv["due_date"],
                "amount": inv["amount"],
                "paid_amount": inv["paid_amount"],
                "outstanding": round(outstanding, 2),
                "days_past_due": max(0, days_past),
                "status": inv["status"],
            })

        buckets = {k: round(v, 2) for k, v in buckets.items()}
        total = round(sum(buckets.values()), 2)
        return {
            "customer_id": customer_id,
            "aging_buckets": buckets,
            "total_outstanding": total,
            "unpaid_invoices": unpaid_invoices,
        }

    @tool(
        description=(
            "Get payment history for a customer within a date range. "
            "Returns individual payment records with dates, amounts, and methods."
        ),
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Customer ID.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD). Default: 12 months before reference date.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD). Default: reference date.",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_payment_history(
        self, customer_id: str, start_date: str = None, end_date: str = None
    ) -> dict:
        if not start_date:
            start_date = (REFERENCE_DATE - timedelta(days=365)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = REFERENCE_DATE.strftime("%Y-%m-%d")
        rows = self._query(
            "SELECT * FROM payment_records WHERE customer_id = ? "
            "AND payment_date BETWEEN ? AND ? ORDER BY payment_date",
            (customer_id, start_date, end_date),
        )
        return {"customer_id": customer_id, "payments": rows, "count": len(rows)}

    @tool(
        description=(
            "Get recent orders for a customer. Returns order records from the "
            "last 6 months, including order date, amount, and status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Customer ID.",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_recent_orders(self, customer_id: str) -> dict:
        six_months_ago = (REFERENCE_DATE - timedelta(days=180)).strftime("%Y-%m-%d")
        rows = self._query(
            "SELECT * FROM orders WHERE customer_id = ? AND order_date >= ? "
            "ORDER BY order_date",
            (customer_id, six_months_ago),
        )
        return {"customer_id": customer_id, "orders": rows, "count": len(rows)}

    @tool(
        description=(
            "Retrieve average days-to-payment for all paid invoices of a customer "
            "within the lookback period. Returns the average delay (days between "
            "due date and actual payment date) and the count of paid invoices."
        ),
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Customer ID.",
                },
                "lookback_months": {
                    "type": "integer",
                    "description": "Number of months to look back from reference date. Default 12.",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_avg_payment_delay(
        self, customer_id: str, lookback_months: int = 12
    ) -> dict:
        cutoff = (REFERENCE_DATE - timedelta(days=lookback_months * 30)).strftime(
            "%Y-%m-%d"
        )
        rows = self._query(
            "SELECT due_date, paid_date FROM invoices "
            "WHERE customer_id = ? AND paid_date IS NOT NULL AND invoice_date >= ?",
            (customer_id, cutoff),
        )
        if not rows:
            return {
                "customer_id": customer_id,
                "avg_days_late": None,
                "paid_invoice_count": 0,
            }
        delays = []
        for r in rows:
            due = datetime.strptime(r["due_date"], "%Y-%m-%d")
            paid = datetime.strptime(r["paid_date"], "%Y-%m-%d")
            delays.append(max(0, (paid - due).days))
        return {
            "customer_id": customer_id,
            "avg_days_late": round(sum(delays) / len(delays), 2),
            "paid_invoice_count": len(delays),
        }

    @tool(
        description=(
            "Get a summary of total invoiced amount and total paid amount "
            "for a customer across all records. Useful for credit utilization calculations."
        ),
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Customer ID.",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_credit_summary(self, customer_id: str) -> dict:
        rows = self._query(
            "SELECT SUM(amount) as total_invoiced, SUM(paid_amount) as total_paid "
            "FROM invoices WHERE customer_id = ?",
            (customer_id,),
        )
        cust = self._query(
            "SELECT credit_limit FROM customers WHERE customer_id = ?",
            (customer_id,),
        )
        if not cust:
            return {"error": f"Customer {customer_id} not found."}
        total_invoiced = rows[0]["total_invoiced"] or 0
        total_paid = rows[0]["total_paid"] or 0
        return {
            "customer_id": customer_id,
            "credit_limit": cust[0]["credit_limit"],
            "total_invoiced": round(total_invoiced, 2),
            "total_paid": round(total_paid, 2),
            "total_outstanding": round(total_invoiced - total_paid, 2),
        }

    # ── Step (evaluation) ───────────────────────────────────────────────
    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        eval_criteria = {}
        max_score = 0
        total_score = 0

        # ── Compute ground truth ────────────────────────────────────────
        gt_high_risk = self._compute_ground_truth()
        gt_ids = set(gt_high_risk.keys())

        # ── 1. Check at_risk_accounts.csv exists with correct columns (15 pts)
        csv_path = os.path.join(self.workspace, "at_risk_accounts.csv")
        c1_max = 15
        max_score += c1_max
        if os.path.exists(csv_path):
            try:
                with open(csv_path, "r") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                    headers = reader.fieldnames
                required_cols = [
                    "customer_id", "company_name", "risk_score",
                    "risk_level", "total_outstanding",
                    "recommended_action", "priority_rank",
                    "contact_name", "contact_email", "contact_phone",
                ]
                missing = [c for c in required_cols if c not in (headers or [])]
                if not missing and len(rows) > 0:
                    eval_criteria["csv_structure"] = {
                        "passed": True, "score": c1_max, "max_score": c1_max,
                    }
                    total_score += c1_max
                else:
                    eval_criteria["csv_structure"] = {
                        "passed": False, "score": 0, "max_score": c1_max,
                        "reason": f"Missing columns: {missing}" if missing else "CSV is empty",
                    }
            except Exception as e:
                eval_criteria["csv_structure"] = {
                    "passed": False, "score": 0, "max_score": c1_max,
                    "reason": str(e),
                }
        else:
            eval_criteria["csv_structure"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "at_risk_accounts.csv not found in workspace.",
            }

        # ── 2. Correct identification of high-risk accounts (25 pts) ────
        c2_max = 25
        max_score += c2_max
        if os.path.exists(csv_path):
            try:
                with open(csv_path, "r") as f:
                    reader = csv.DictReader(f)
                    submitted_rows = list(reader)
                submitted_ids = set(r["customer_id"] for r in submitted_rows)
                # Compute precision and recall
                if submitted_ids:
                    true_pos = submitted_ids & gt_ids
                    precision = len(true_pos) / len(submitted_ids)
                    recall = len(true_pos) / len(gt_ids) if gt_ids else 1.0
                    f1 = (
                        2 * precision * recall / (precision + recall)
                        if (precision + recall) > 0
                        else 0
                    )
                    score = round(f1 * c2_max)
                    eval_criteria["account_identification"] = {
                        "passed": f1 >= 0.8,
                        "score": score,
                        "max_score": c2_max,
                        "reason": f"F1={f1:.3f}, precision={precision:.3f}, recall={recall:.3f}" if f1 < 0.8 else None,
                    }
                    total_score += score
                else:
                    eval_criteria["account_identification"] = {
                        "passed": False, "score": 0, "max_score": c2_max,
                        "reason": "No accounts in CSV.",
                    }
            except Exception as e:
                eval_criteria["account_identification"] = {
                    "passed": False, "score": 0, "max_score": c2_max,
                    "reason": str(e),
                }
        else:
            eval_criteria["account_identification"] = {
                "passed": False, "score": 0, "max_score": c2_max,
                "reason": "CSV not found.",
            }

        # ── 3. Risk score accuracy (20 pts) ─────────────────────────────
        c3_max = 20
        max_score += c3_max
        if os.path.exists(csv_path):
            try:
                with open(csv_path, "r") as f:
                    submitted_rows = list(csv.DictReader(f))
                submitted_scores = {}
                for r in submitted_rows:
                    try:
                        submitted_scores[r["customer_id"]] = float(r["risk_score"])
                    except (ValueError, KeyError):
                        pass
                if submitted_scores:
                    # Score based on how close submitted scores are to ground truth
                    matching = 0
                    total_compared = 0
                    for cid, gt_info in gt_high_risk.items():
                        if cid in submitted_scores:
                            total_compared += 1
                            diff = abs(submitted_scores[cid] - gt_info["risk_score"])
                            if diff <= 5.0:
                                matching += 1
                            elif diff <= 10.0:
                                matching += 0.5
                    accuracy = matching / len(gt_ids) if gt_ids else 0
                    score = round(accuracy * c3_max)
                    eval_criteria["risk_score_accuracy"] = {
                        "passed": accuracy >= 0.7,
                        "score": score,
                        "max_score": c3_max,
                        "reason": f"Accuracy={accuracy:.3f}" if accuracy < 0.7 else None,
                    }
                    total_score += score
                else:
                    eval_criteria["risk_score_accuracy"] = {
                        "passed": False, "score": 0, "max_score": c3_max,
                        "reason": "No valid risk_score values.",
                    }
            except Exception as e:
                eval_criteria["risk_score_accuracy"] = {
                    "passed": False, "score": 0, "max_score": c3_max,
                    "reason": str(e),
                }
        else:
            eval_criteria["risk_score_accuracy"] = {
                "passed": False, "score": 0, "max_score": c3_max,
                "reason": "CSV not found.",
            }

        # ── 4. Correct priority ranking (15 pts) ───────────────────────
        c4_max = 15
        max_score += c4_max
        if os.path.exists(csv_path):
            try:
                with open(csv_path, "r") as f:
                    submitted_rows = list(csv.DictReader(f))
                if len(submitted_rows) >= 2:
                    # Check that rows are sorted by risk_score desc, tiebreaker total_outstanding desc
                    correctly_ordered = True
                    for i in range(len(submitted_rows) - 1):
                        try:
                            s1 = float(submitted_rows[i]["risk_score"])
                            s2 = float(submitted_rows[i + 1]["risk_score"])
                            t1 = float(submitted_rows[i]["total_outstanding"])
                            t2 = float(submitted_rows[i + 1]["total_outstanding"])
                        except (ValueError, KeyError):
                            correctly_ordered = False
                            break
                        if s1 < s2:
                            correctly_ordered = False
                            break
                        if s1 == s2 and t1 < t2:
                            correctly_ordered = False
                            break
                    # Check priority_rank is sequential
                    ranks_ok = True
                    for i, r in enumerate(submitted_rows):
                        try:
                            if int(r["priority_rank"]) != i + 1:
                                ranks_ok = False
                                break
                        except (ValueError, KeyError):
                            ranks_ok = False
                            break
                    if correctly_ordered and ranks_ok:
                        score = c4_max
                        passed = True
                    elif correctly_ordered or ranks_ok:
                        score = c4_max // 2
                        passed = False
                    else:
                        score = 0
                        passed = False
                    eval_criteria["priority_ranking"] = {
                        "passed": passed, "score": score, "max_score": c4_max,
                        "reason": None if passed else f"Order correct: {correctly_ordered}, Ranks sequential: {ranks_ok}",
                    }
                    total_score += score
                else:
                    eval_criteria["priority_ranking"] = {
                        "passed": False, "score": 0, "max_score": c4_max,
                        "reason": "Fewer than 2 rows.",
                    }
            except Exception as e:
                eval_criteria["priority_ranking"] = {
                    "passed": False, "score": 0, "max_score": c4_max,
                    "reason": str(e),
                }
        else:
            eval_criteria["priority_ranking"] = {
                "passed": False, "score": 0, "max_score": c4_max,
                "reason": "CSV not found.",
            }

        # ── 5. Risk level and recommended action correctness (15 pts) ──
        c5_max = 15
        max_score += c5_max
        if os.path.exists(csv_path):
            try:
                with open(csv_path, "r") as f:
                    submitted_rows = list(csv.DictReader(f))
                risk_class = self._load_risk_classification()
                correct = 0
                total_checked = 0
                for r in submitted_rows:
                    cid = r.get("customer_id")
                    if cid in gt_high_risk:
                        total_checked += 1
                        expected_level = gt_high_risk[cid]["risk_level"]
                        expected_action = gt_high_risk[cid]["recommended_action"]
                        if (r.get("risk_level", "").strip() == expected_level and
                                r.get("recommended_action", "").strip() == expected_action):
                            correct += 1
                if total_checked > 0:
                    acc = correct / total_checked
                    score = round(acc * c5_max)
                    eval_criteria["risk_level_action"] = {
                        "passed": acc >= 0.8, "score": score, "max_score": c5_max,
                        "reason": f"Accuracy={acc:.3f}" if acc < 0.8 else None,
                    }
                    total_score += score
                else:
                    eval_criteria["risk_level_action"] = {
                        "passed": False, "score": 0, "max_score": c5_max,
                        "reason": "No matching accounts to check.",
                    }
            except Exception as e:
                eval_criteria["risk_level_action"] = {
                    "passed": False, "score": 0, "max_score": c5_max,
                    "reason": str(e),
                }
        else:
            eval_criteria["risk_level_action"] = {
                "passed": False, "score": 0, "max_score": c5_max,
                "reason": "CSV not found.",
            }

        # ── 6. Response summary check (10 pts) ─────────────────────────
        c6_max = 10
        max_score += c6_max
        action_lower = action.lower() if action else ""
        # Check that response mentions key summary elements
        checks = [
            any(cid.lower() in action_lower for cid in gt_ids),  # mentions an actual at-risk ID
            "high" in action_lower or "critical" in action_lower,  # mentions risk levels
            any(w in action_lower for w in ["risk", "delinquen", "overdue", "outstanding"]),
            len(action) >= 100,  # substantive response
        ]
        passed_checks = sum(checks)
        score = round((passed_checks / len(checks)) * c6_max)
        eval_criteria["response_summary"] = {
            "passed": passed_checks == len(checks),
            "score": score,
            "max_score": c6_max,
            "reason": None if passed_checks == len(checks) else f"Passed {passed_checks}/{len(checks)} checks.",
        }
        total_score += score

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ── Ground truth computation ────────────────────────────────────────
    def _load_risk_classification(self) -> list:
        rc_path = os.path.join(self.workspace, "risk_classification.json")
        with open(rc_path, "r") as f:
            return json.load(f)["risk_levels"]

    def _compute_ground_truth(self) -> Dict[str, dict]:
        """Compute which accounts are high-risk using the same logic verify uses."""
        # Load policy
        policy_path = os.path.join(self.workspace, "credit_policy.yaml")
        with open(policy_path, "r") as f:
            policy = yaml.safe_load(f)

        coeff_path = os.path.join(self.workspace, "scoring_coefficients.json")
        with open(coeff_path, "r") as f:
            coefficients = json.load(f)

        ind_path = os.path.join(self.workspace, "industry_economic_indicators.csv")
        ind_data = {}
        with open(ind_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ind_data[row["industry_code"]] = row

        risk_class = self._load_risk_classification()
        weights = policy["scoring_model"]["weights"]
        eligible_statuses = policy["eligible_account_statuses"]
        threshold = policy["risk_thresholds"]["high_risk_min"]
        lookback_months = policy["delinquency_definition"]["lookback_months"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Get all customers with eligible status
        cur.execute(
            "SELECT * FROM customers WHERE account_status IN ({})".format(
                ",".join("?" * len(eligible_statuses))
            ),
            eligible_statuses,
        )
        customers = [dict(r) for r in cur.fetchall()]

        high_risk = {}
        for cust in customers:
            cid = cust["customer_id"]
            score_components = self._calc_score_components(
                cid, cust, ind_data, coefficients, lookback_months, conn
            )

            composite = sum(
                score_components[comp] * weights[comp] for comp in weights
            )
            composite = round(min(100, max(0, composite)), 2)

            if composite >= threshold:
                # Determine risk level
                level_info = self._classify_risk(composite, risk_class)
                aging = self._get_aging_data(cid, conn)
                high_risk[cid] = {
                    "customer_id": cid,
                    "company_name": cust["company_name"],
                    "risk_score": composite,
                    "risk_level": level_info["level"],
                    "total_outstanding": aging["total_outstanding"],
                    "recommended_action": level_info["recommended_action"],
                    "contact_name": cust["contact_name"],
                    "contact_email": cust["contact_email"],
                    "contact_phone": cust["contact_phone"],
                }
        conn.close()
        return high_risk

    def _calc_score_components(
        self, cid, cust, ind_data, coefficients, lookback_months, conn
    ) -> dict:
        cur = conn.cursor()
        ref = REFERENCE_DATE
        cutoff = (ref - timedelta(days=lookback_months * 30)).strftime("%Y-%m-%d")

        # 1. Payment delay score
        cur.execute(
            "SELECT due_date, paid_date FROM invoices "
            "WHERE customer_id = ? AND paid_date IS NOT NULL AND invoice_date >= ?",
            (cid, cutoff),
        )
        paid_inv = [dict(r) for r in cur.fetchall()]
        if paid_inv:
            delays = []
            for r in paid_inv:
                due = datetime.strptime(r["due_date"], "%Y-%m-%d")
                paid = datetime.strptime(r["paid_date"], "%Y-%m-%d")
                delays.append(max(0, (paid - due).days))
            avg_days_late = sum(delays) / len(delays)
            pds = min(100, (avg_days_late / cust["payment_terms_days"]) * 120)
        else:
            pds = 0

        # 2. Aging concentration score
        aging = self._get_aging_data(cid, conn)
        total_out = aging["total_outstanding"]
        over_60 = aging["bucket_61_90"] + aging["bucket_91_120"] + aging["bucket_121_plus"]
        if total_out > 0:
            acs = (over_60 / total_out) * 100
        else:
            acs = 0

        # 3. Order trend score
        three_mo_ago = (ref - timedelta(days=90)).strftime("%Y-%m-%d")
        six_mo_ago = (ref - timedelta(days=180)).strftime("%Y-%m-%d")
        cur.execute(
            "SELECT COUNT(*) as cnt FROM orders WHERE customer_id = ? AND order_date >= ?",
            (cid, three_mo_ago),
        )
        recent_3mo = dict(cur.fetchone())["cnt"]
        cur.execute(
            "SELECT COUNT(*) as cnt FROM orders WHERE customer_id = ? "
            "AND order_date >= ? AND order_date < ?",
            (cid, six_mo_ago, three_mo_ago),
        )
        prior_3mo = dict(cur.fetchone())["cnt"]
        if prior_3mo > 0:
            ots = max(0, (1 - recent_3mo / prior_3mo) * 100)
        elif recent_3mo > 0:
            ots = 0
        else:
            ots = 50

        # 4. Industry risk score
        ind_code = cust["industry_code"]
        if ind_code in ind_data:
            ind = ind_data[ind_code]
            sdr = float(ind["sector_default_rate_pct"])
            gdp = float(ind["gdp_growth_pct"])
            bi = float(ind["bankruptcy_index"])
            irs = min(100, max(0, (sdr * 4) + (max(0, -gdp) * 8) + (bi * 0.3)))
        else:
            irs = 50

        # 5. Credit utilization score
        cur.execute(
            "SELECT SUM(amount) as ti, SUM(paid_amount) as tp "
            "FROM invoices WHERE customer_id = ?",
            (cid,),
        )
        sums = dict(cur.fetchone())
        ti = sums["ti"] or 0
        tp = sums["tp"] or 0
        outstanding = ti - tp
        cl = cust["credit_limit"]
        if cl > 0:
            cus = min(100, (outstanding / cl) * 100)
        else:
            cus = 50

        return {
            "payment_delay_score": round(min(100, max(0, pds)), 2),
            "aging_concentration_score": round(min(100, max(0, acs)), 2),
            "order_trend_score": round(min(100, max(0, ots)), 2),
            "industry_risk_score": round(min(100, max(0, irs)), 2),
            "credit_utilization_score": round(min(100, max(0, cus)), 2),
        }

    def _get_aging_data(self, cid, conn) -> dict:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM invoices WHERE customer_id = ?", (cid,)
        )
        invoices = [dict(r) for r in cur.fetchall()]
        ref = REFERENCE_DATE
        buckets = {
            "current": 0.0,
            "bucket_31_60": 0.0,
            "bucket_61_90": 0.0,
            "bucket_91_120": 0.0,
            "bucket_121_plus": 0.0,
        }
        for inv in invoices:
            outstanding = inv["amount"] - inv["paid_amount"]
            if outstanding <= 0:
                continue
            if inv["status"] not in ("overdue", "open", "partial"):
                continue
            due = datetime.strptime(inv["due_date"], "%Y-%m-%d")
            days_past = (ref - due).days
            if days_past <= 30:
                buckets["current"] += outstanding
            elif days_past <= 60:
                buckets["bucket_31_60"] += outstanding
            elif days_past <= 90:
                buckets["bucket_61_90"] += outstanding
            elif days_past <= 120:
                buckets["bucket_91_120"] += outstanding
            else:
                buckets["bucket_121_plus"] += outstanding
        return {
            **{k: round(v, 2) for k, v in buckets.items()},
            "total_outstanding": round(sum(buckets.values()), 2),
        }

    def _classify_risk(self, score: float, risk_levels: list) -> dict:
        for level in risk_levels:
            if level["score_min"] <= score <= level["score_max"]:
                return level
        return risk_levels[-1]  # default to lowest

    # ── Verify ──────────────────────────────────────────────────────────
    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as csv_mod

        # Step 1: Read configuration files from workspace
        policy_path = os.path.join(self.workspace, "credit_policy.yaml")
        with open(policy_path, "r") as f:
            policy = yaml.safe_load(f)

        coeff_path = os.path.join(self.workspace, "scoring_coefficients.json")
        with open(coeff_path, "r") as f:
            coefficients = json.load(f)

        rc_path = os.path.join(self.workspace, "risk_classification.json")
        with open(rc_path, "r") as f:
            risk_class = json.load(f)["risk_levels"]

        ind_path = os.path.join(self.workspace, "industry_economic_indicators.csv")
        ind_data = {}
        with open(ind_path, "r") as f:
            reader = csv_mod.DictReader(f)
            for row in reader:
                ind_data[row["industry_code"]] = row

        weights = policy["scoring_model"]["weights"]
        eligible_statuses = policy["eligible_account_statuses"]
        threshold = policy["risk_thresholds"]["high_risk_min"]
        lookback_months = policy["delinquency_definition"]["lookback_months"]

        tool_call_count = 0

        # Step 2: List all customers (paginated)
        all_customers = []
        page = 1
        while True:
            result = self.tools["list_customers"](page=page, page_size=25)
            tool_call_count += 1
            all_customers.extend(result["customers"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 3: Filter eligible customers and compute risk scores
        eligible = [
            c for c in all_customers
            if c["account_status"] in eligible_statuses
        ]

        scored_accounts = []
        for cust_summary in eligible:
            cid = cust_summary["customer_id"]

            # Get customer details
            details = self.tools["get_customer_details"](customer_id=cid)
            tool_call_count += 1

            # Get invoice aging
            aging = self.tools["get_invoice_aging"](customer_id=cid)
            tool_call_count += 1

            # Get avg payment delay
            delay_info = self.tools["get_avg_payment_delay"](
                customer_id=cid, lookback_months=lookback_months
            )
            tool_call_count += 1

            # Get recent orders
            orders = self.tools["get_recent_orders"](customer_id=cid)
            tool_call_count += 1

            # Get credit summary
            credit = self.tools["get_credit_summary"](customer_id=cid)
            tool_call_count += 1

            # Compute payment_delay_score
            avg_late = delay_info["avg_days_late"]
            terms = details["payment_terms_days"]
            if avg_late is not None and terms > 0:
                pds = min(100, (avg_late / terms) * 120)
            else:
                pds = 0

            # Compute aging_concentration_score
            total_out = aging["total_outstanding"]
            over_60 = (
                aging["aging_buckets"]["bucket_61_90"]
                + aging["aging_buckets"]["bucket_91_120"]
                + aging["aging_buckets"]["bucket_121_plus"]
            )
            if total_out > 0:
                acs = (over_60 / total_out) * 100
            else:
                acs = 0

            # Compute order_trend_score
            ref = REFERENCE_DATE
            three_mo_ago = ref - timedelta(days=90)
            recent_orders = orders["orders"]
            recent_3mo = sum(
                1 for o in recent_orders
                if datetime.strptime(o["order_date"], "%Y-%m-%d") >= three_mo_ago
            )
            prior_3mo = sum(
                1 for o in recent_orders
                if datetime.strptime(o["order_date"], "%Y-%m-%d") < three_mo_ago
            )
            if prior_3mo > 0:
                ots = max(0, (1 - recent_3mo / prior_3mo) * 100)
            elif recent_3mo > 0:
                ots = 0
            else:
                ots = 50

            # Compute industry_risk_score
            ind_code = details["industry_code"]
            if ind_code in ind_data:
                ind = ind_data[ind_code]
                sdr = float(ind["sector_default_rate_pct"])
                gdp = float(ind["gdp_growth_pct"])
                bi = float(ind["bankruptcy_index"])
                irs = min(100, max(0, (sdr * 4) + (max(0, -gdp) * 8) + (bi * 0.3)))
            else:
                irs = 50

            # Compute credit_utilization_score
            cl = details["credit_limit"]
            outstanding = credit["total_outstanding"]
            if cl > 0:
                cus = min(100, (outstanding / cl) * 100)
            else:
                cus = 50

            components = {
                "payment_delay_score": round(min(100, max(0, pds)), 2),
                "aging_concentration_score": round(min(100, max(0, acs)), 2),
                "order_trend_score": round(min(100, max(0, ots)), 2),
                "industry_risk_score": round(min(100, max(0, irs)), 2),
                "credit_utilization_score": round(min(100, max(0, cus)), 2),
            }

            composite = sum(
                components[comp] * weights[comp] for comp in weights
            )
            composite = round(min(100, max(0, composite)), 2)

            if composite >= threshold:
                # Classify risk level
                level_info = None
                for lv in risk_class:
                    if lv["score_min"] <= composite <= lv["score_max"]:
                        level_info = lv
                        break
                if not level_info:
                    level_info = risk_class[-1]

                scored_accounts.append({
                    "customer_id": cid,
                    "company_name": details["company_name"],
                    "risk_score": composite,
                    "risk_level": level_info["level"],
                    "total_outstanding": round(total_out, 2),
                    "recommended_action": level_info["recommended_action"],
                    "contact_name": details["contact_name"],
                    "contact_email": details["contact_email"],
                    "contact_phone": details["contact_phone"],
                })

        # Step 4: Sort by risk_score desc, tiebreaker total_outstanding desc
        scored_accounts.sort(
            key=lambda x: (-x["risk_score"], -x["total_outstanding"])
        )

        # Assign priority ranks
        for i, acc in enumerate(scored_accounts):
            acc["priority_rank"] = i + 1

        # Step 5: Write at_risk_accounts.csv
        csv_out = os.path.join(self.workspace, "at_risk_accounts.csv")
        fieldnames = [
            "customer_id", "company_name", "risk_score", "risk_level",
            "total_outstanding", "recommended_action", "priority_rank",
            "contact_name", "contact_email", "contact_phone",
        ]
        with open(csv_out, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(scored_accounts)

        # Step 6: Build action/response string
        summary_lines = [
            f"Credit Risk Assessment Complete - {len(scored_accounts)} at-risk accounts identified.",
            "",
        ]
        critical = [a for a in scored_accounts if a["risk_level"] == "CRITICAL"]
        high = [a for a in scored_accounts if a["risk_level"] == "HIGH"]
        summary_lines.append(
            f"CRITICAL risk accounts: {len(critical)}, HIGH risk accounts: {len(high)}"
        )
        summary_lines.append("")
        summary_lines.append("Top at-risk accounts requiring immediate attention:")
        for acc in scored_accounts[:10]:
            summary_lines.append(
                f"  {acc['customer_id']} ({acc['company_name']}): "
                f"risk_score={acc['risk_score']}, level={acc['risk_level']}, "
                f"outstanding=${acc['total_outstanding']:,.2f}, "
                f"action: {acc['recommended_action']}"
            )
        summary_lines.append("")
        summary_lines.append(
            f"All {len(scored_accounts)} at-risk accounts have been saved to at_risk_accounts.csv "
            f"with priority rankings, risk levels, and recommended actions. "
            f"Accounts with delinquency risk exceeding the threshold have been flagged "
            f"for proactive credit management outreach."
        )
        action = "\n".join(summary_lines)

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need >= 15"

        return self.step(action)
