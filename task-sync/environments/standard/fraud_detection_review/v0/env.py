"""
Environment for fraudulent ticket purchase detection task.
Defines tools for querying transaction/device/customer/resale data
and evaluates the agent's fraud review queue output.
"""

import sqlite3
import os
import json
import csv
import yaml
import glob
from datetime import datetime, timedelta
from typing import Tuple, Dict, List, Any


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

    # -----------------------------------------------------------------------
    # Helper: DB query
    # -----------------------------------------------------------------------
    def _query(self, sql, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    # -----------------------------------------------------------------------
    # Tools
    # -----------------------------------------------------------------------

    @tool(
        description="Returns the most recent transaction date in the system that requires fraud review. Use this to determine which day's transactions to analyze.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    def get_review_date(self) -> dict:
        rows = self._query("SELECT MAX(purchase_date) as review_date FROM transactions")
        return {"review_date": rows[0]["review_date"] if rows else None}

    @tool(
        description="Lists transactions for a given date with pagination. Returns transaction IDs and basic metadata. Use page and page_size to iterate through results.",
        parameters={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (default 20, max 50)"
                }
            },
            "required": ["date", "page"]
        }
    )
    def list_transactions_by_date(self, date: str, page: int, page_size: int = 20) -> dict:
        page_size = min(int(page_size), 50)
        page = max(1, int(page))
        offset = (page - 1) * page_size

        total_rows = self._query(
            "SELECT COUNT(*) as cnt FROM transactions WHERE purchase_date = ?", (date,)
        )
        total = total_rows[0]["cnt"]
        total_pages = max(1, (total + page_size - 1) // page_size)

        rows = self._query(
            "SELECT transaction_id, customer_id, event_id, amount, purchase_timestamp "
            "FROM transactions WHERE purchase_date = ? ORDER BY transaction_id "
            "LIMIT ? OFFSET ?",
            (date, page_size, offset)
        )

        return {
            "date": date,
            "page": page,
            "page_size": page_size,
            "total_transactions": total,
            "total_pages": total_pages,
            "transactions": rows
        }

    @tool(
        description="Retrieves full details of a specific transaction by its ID, including amount, payment method, quantity, and associated event and customer IDs.",
        parameters={
            "type": "object",
            "properties": {
                "transaction_id": {
                    "type": "string",
                    "description": "Transaction ID (e.g. TXN-00001)"
                }
            },
            "required": ["transaction_id"]
        }
    )
    def get_transaction_details(self, transaction_id: str) -> dict:
        rows = self._query(
            "SELECT * FROM transactions WHERE transaction_id = ?",
            (transaction_id,)
        )
        if not rows:
            return {"error": f"Transaction {transaction_id} not found"}
        return rows[0]

    @tool(
        description="Retrieves the device and network session data for a transaction, including IP address, device type, browser, geolocation (city, country, coordinates), and VPN detection status.",
        parameters={
            "type": "object",
            "properties": {
                "transaction_id": {
                    "type": "string",
                    "description": "Transaction ID (e.g. TXN-00001)"
                }
            },
            "required": ["transaction_id"]
        }
    )
    def get_device_session(self, transaction_id: str) -> dict:
        rows = self._query(
            "SELECT * FROM devices WHERE transaction_id = ?",
            (transaction_id,)
        )
        if not rows:
            return {"error": f"No device session found for transaction {transaction_id}"}
        return rows[0]

    @tool(
        description="Retrieves the profile of a customer by ID. Returns name, email, phone, registration date, and account tier. Does NOT include address information.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Customer ID (e.g. CUST-00001)"
                }
            },
            "required": ["customer_id"]
        }
    )
    def get_customer_profile(self, customer_id: str) -> dict:
        rows = self._query(
            "SELECT customer_id, name, email, phone, registration_date, account_tier "
            "FROM customers WHERE customer_id = ?",
            (customer_id,)
        )
        if not rows:
            return {"error": f"Customer {customer_id} not found"}
        return rows[0]

    @tool(
        description="Retrieves the purchase history for a customer with pagination. Returns past transactions sorted by timestamp descending. Use this to assess purchase velocity.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Customer ID (e.g. CUST-00001)"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (default 20, max 50)"
                }
            },
            "required": ["customer_id", "page"]
        }
    )
    def get_purchase_history(self, customer_id: str, page: int, page_size: int = 20) -> dict:
        page_size = min(int(page_size), 50)
        page = max(1, int(page))
        offset = (page - 1) * page_size

        total_rows = self._query(
            "SELECT COUNT(*) as cnt FROM transactions WHERE customer_id = ?",
            (customer_id,)
        )
        total = total_rows[0]["cnt"]
        total_pages = max(1, (total + page_size - 1) // page_size)

        rows = self._query(
            "SELECT transaction_id, event_id, ticket_id, purchase_timestamp, purchase_date, "
            "amount, payment_method, quantity "
            "FROM transactions WHERE customer_id = ? "
            "ORDER BY purchase_timestamp DESC LIMIT ? OFFSET ?",
            (customer_id, page_size, offset)
        )

        return {
            "customer_id": customer_id,
            "page": page,
            "page_size": page_size,
            "total_transactions": total,
            "total_pages": total_pages,
            "transactions": rows
        }

    @tool(
        description="Checks whether a specific ticket has been listed on any resale platform. Returns listing details if found, including platform name, asking price, and listing date.",
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "Ticket ID (e.g. TKT-00001)"
                }
            },
            "required": ["ticket_id"]
        }
    )
    def check_resale_listings(self, ticket_id: str) -> dict:
        rows = self._query(
            "SELECT * FROM resale_listings WHERE ticket_id = ?",
            (ticket_id,)
        )
        return {
            "ticket_id": ticket_id,
            "found": len(rows) > 0,
            "listings": rows
        }

    # -----------------------------------------------------------------------
    # Ground-truth computation (used by step)
    # -----------------------------------------------------------------------

    def _load_workspace_data(self):
        """Load all workspace files needed for ground-truth scoring."""
        # Fraud scoring rules
        rules_path = os.path.join(self.workspace, "fraud_scoring_rules.yaml")
        with open(rules_path, "r") as f:
            rules = yaml.safe_load(f)

        # Velocity policy
        velocity = {}
        vel_path = os.path.join(self.workspace, "velocity_policy.csv")
        with open(vel_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                velocity[row["tier"]] = {
                    "max_purchases_today": int(row["max_purchases_today"]),
                    "max_purchases_7d": int(row["max_purchases_7d"]),
                }

        # Processor flags from batch CSVs
        processor_flags = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "batch_*.csv"))):
            with open(fp, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    processor_flags[row["transaction_id"]] = int(row["processor_risk_flag"])

        # Event pricing from JSON files
        event_max_prices = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "event_pricing_*.json"))):
            with open(fp, "r") as f:
                data = json.load(f)
                for item in data:
                    event_max_prices[item["event_id"]] = item["max_ticket_price"]

        # Verified countries from TXT files
        verified_countries = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "customer_verified_*.txt"))):
            with open(fp, "r") as f:
                header = f.readline()  # skip header
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 2:
                        verified_countries[parts[0]] = parts[1]

        return rules, velocity, processor_flags, event_max_prices, verified_countries

    def _compute_ground_truth(self):
        """Compute the ground-truth fraud review queue."""
        rules, velocity_policy, processor_flags, event_max_prices, verified_countries = \
            self._load_workspace_data()

        weights = {k: v["weight"] for k, v in rules["risk_factors"].items()}
        thresholds = rules["thresholds"]
        price_anomaly_pct = thresholds["price_anomaly_pct"]

        # Get review date
        review_rows = self._query("SELECT MAX(purchase_date) as rd FROM transactions")
        review_date = review_rows[0]["rd"]

        # Get review-date transactions
        txns = self._query(
            "SELECT * FROM transactions WHERE purchase_date = ? ORDER BY transaction_id",
            (review_date,)
        )

        # Velocity windows
        review_dt = datetime.strptime(review_date, "%Y-%m-%d")
        window_7d_start = (review_dt - timedelta(days=6)).strftime("%Y-%m-%d")

        results = []
        for txn in txns:
            tid = txn["transaction_id"]
            cid = txn["customer_id"]
            eid = txn["event_id"]
            ticket_id = txn["ticket_id"]
            amount = txn["amount"]
            risk_factors = []

            # 1. Geo mismatch: device country vs verified country
            device_rows = self._query(
                "SELECT country, vpn_detected FROM devices WHERE transaction_id = ?", (tid,)
            )
            dev_country = device_rows[0]["country"] if device_rows else None
            vpn = device_rows[0]["vpn_detected"] if device_rows else 0

            verified_country = verified_countries.get(cid)
            if dev_country and verified_country and dev_country != verified_country:
                risk_factors.append("geo_mismatch")

            # 2. Velocity violation
            cust_rows = self._query(
                "SELECT account_tier FROM customers WHERE customer_id = ?", (cid,)
            )
            tier = cust_rows[0]["account_tier"] if cust_rows else "standard"
            limits = velocity_policy.get(tier, velocity_policy["standard"])

            today_count_rows = self._query(
                "SELECT COUNT(*) as cnt FROM transactions WHERE customer_id = ? AND purchase_date = ?",
                (cid, review_date)
            )
            today_count = today_count_rows[0]["cnt"]

            week_count_rows = self._query(
                "SELECT COUNT(*) as cnt FROM transactions WHERE customer_id = ? AND purchase_date >= ? AND purchase_date <= ?",
                (cid, window_7d_start, review_date)
            )
            week_count = week_count_rows[0]["cnt"]

            if today_count > limits["max_purchases_today"] or week_count > limits["max_purchases_7d"]:
                risk_factors.append("velocity_violation")

            # 3. Resale detected
            resale_rows = self._query(
                "SELECT COUNT(*) as cnt FROM resale_listings WHERE ticket_id = ?", (ticket_id,)
            )
            if resale_rows[0]["cnt"] > 0:
                risk_factors.append("resale_detected")

            # 4. VPN detected
            if vpn:
                risk_factors.append("vpn_detected")

            # 5. Price anomaly
            max_price = event_max_prices.get(eid)
            if max_price and amount > max_price * (1 + price_anomaly_pct / 100):
                risk_factors.append("price_anomaly")

            # 6. Processor flag
            if processor_flags.get(tid, 0) == 1:
                risk_factors.append("processor_flag")

            # Compute score
            risk_score = sum(weights.get(f, 0) for f in risk_factors)

            if risk_score >= thresholds["high_risk"]:
                risk_level = "HIGH"
                action = "block_and_investigate"
            elif risk_score >= thresholds["medium_risk"]:
                risk_level = "MEDIUM"
                action = "manual_review"
            elif risk_score >= 10:
                risk_level = "LOW"
                action = "monitor"
            else:
                continue  # Not included in queue

            results.append({
                "transaction_id": tid,
                "customer_id": cid,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "risk_factors": ";".join(sorted(risk_factors)),
                "recommended_action": action,
            })

        # Sort by risk_score descending, then transaction_id ascending
        results.sort(key=lambda x: (-x["risk_score"], x["transaction_id"]))
        return results, review_date

    # -----------------------------------------------------------------------
    # step
    # -----------------------------------------------------------------------

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
        ground_truth, review_date = self._compute_ground_truth()
        gt_by_tid = {r["transaction_id"]: r for r in ground_truth}

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: File exists with correct columns (10 pts) ---
        c1_max = 10
        max_score += c1_max
        queue_path = os.path.join(self.workspace, "fraud_review_queue.csv")
        expected_columns = ["transaction_id", "customer_id", "risk_score", "risk_level",
                            "risk_factors", "recommended_action"]
        file_ok = False
        agent_rows = []
        if os.path.exists(queue_path):
            try:
                with open(queue_path, "r") as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    if all(c in cols for c in expected_columns):
                        agent_rows = list(reader)
                        file_ok = True
            except Exception:
                pass

        if file_ok:
            eval_criteria["file_structure"] = {
                "passed": True, "score": c1_max, "max_score": c1_max
            }
            total_score += c1_max
        else:
            eval_criteria["file_structure"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "fraud_review_queue.csv missing or has incorrect columns"
            }

        # --- Criterion 2: Correct transaction IDs (20 pts) ---
        c2_max = 20
        max_score += c2_max
        if file_ok:
            gt_tids = set(gt_by_tid.keys())
            agent_tids = set(r["transaction_id"] for r in agent_rows)
            correct_tids = gt_tids & agent_tids
            extra_tids = agent_tids - gt_tids
            missing_tids = gt_tids - agent_tids

            if len(gt_tids) > 0:
                # Partial credit: correct / total_expected, penalize extras
                precision = len(correct_tids) / max(len(agent_tids), 1)
                recall = len(correct_tids) / len(gt_tids)
                f1 = 2 * precision * recall / max(precision + recall, 1e-9)
                c2_score = round(c2_max * f1)
            else:
                c2_score = c2_max if len(agent_tids) == 0 else 0

            passed = c2_score == c2_max
            eval_criteria["transaction_ids"] = {
                "passed": passed, "score": c2_score, "max_score": c2_max,
                **({"reason": f"Missing {len(missing_tids)}, extra {len(extra_tids)}"} if not passed else {})
            }
            total_score += c2_score
        else:
            eval_criteria["transaction_ids"] = {
                "passed": False, "score": 0, "max_score": c2_max,
                "reason": "Cannot evaluate - file not loaded"
            }

        # --- Criterion 3: Correct risk scores (20 pts) ---
        c3_max = 20
        max_score += c3_max
        if file_ok and agent_rows:
            agent_by_tid = {r["transaction_id"]: r for r in agent_rows}
            correct_scores = 0
            total_comparable = 0
            for tid, gt in gt_by_tid.items():
                if tid in agent_by_tid:
                    total_comparable += 1
                    try:
                        agent_score = int(agent_by_tid[tid]["risk_score"])
                        if agent_score == gt["risk_score"]:
                            correct_scores += 1
                    except (ValueError, KeyError):
                        pass

            if total_comparable > 0:
                c3_score = round(c3_max * correct_scores / total_comparable)
            else:
                c3_score = 0
            passed = c3_score == c3_max
            eval_criteria["risk_scores"] = {
                "passed": passed, "score": c3_score, "max_score": c3_max,
                **({"reason": f"{correct_scores}/{total_comparable} scores correct"} if not passed else {})
            }
            total_score += c3_score
        else:
            eval_criteria["risk_scores"] = {
                "passed": False, "score": 0, "max_score": c3_max,
                "reason": "Cannot evaluate - no data"
            }

        # --- Criterion 4: Correct risk levels (15 pts) ---
        c4_max = 15
        max_score += c4_max
        if file_ok and agent_rows:
            agent_by_tid = {r["transaction_id"]: r for r in agent_rows}
            correct_levels = 0
            total_comparable = 0
            for tid, gt in gt_by_tid.items():
                if tid in agent_by_tid:
                    total_comparable += 1
                    if agent_by_tid[tid].get("risk_level", "").strip().upper() == gt["risk_level"]:
                        correct_levels += 1

            if total_comparable > 0:
                c4_score = round(c4_max * correct_levels / total_comparable)
            else:
                c4_score = 0
            passed = c4_score == c4_max
            eval_criteria["risk_levels"] = {
                "passed": passed, "score": c4_score, "max_score": c4_max,
                **({"reason": f"{correct_levels}/{total_comparable} levels correct"} if not passed else {})
            }
            total_score += c4_score
        else:
            eval_criteria["risk_levels"] = {
                "passed": False, "score": 0, "max_score": c4_max,
                "reason": "Cannot evaluate - no data"
            }

        # --- Criterion 5: Correct risk factors (15 pts) ---
        c5_max = 15
        max_score += c5_max
        if file_ok and agent_rows:
            agent_by_tid = {r["transaction_id"]: r for r in agent_rows}
            correct_factors = 0
            total_comparable = 0
            for tid, gt in gt_by_tid.items():
                if tid in agent_by_tid:
                    total_comparable += 1
                    agent_factors = ";".join(sorted(
                        f.strip() for f in agent_by_tid[tid].get("risk_factors", "").split(";") if f.strip()
                    ))
                    if agent_factors == gt["risk_factors"]:
                        correct_factors += 1

            if total_comparable > 0:
                c5_score = round(c5_max * correct_factors / total_comparable)
            else:
                c5_score = 0
            passed = c5_score == c5_max
            eval_criteria["risk_factors"] = {
                "passed": passed, "score": c5_score, "max_score": c5_max,
                **({"reason": f"{correct_factors}/{total_comparable} factor sets correct"} if not passed else {})
            }
            total_score += c5_score
        else:
            eval_criteria["risk_factors"] = {
                "passed": False, "score": 0, "max_score": c5_max,
                "reason": "Cannot evaluate - no data"
            }

        # --- Criterion 6: Correct sorting (10 pts) ---
        c6_max = 10
        max_score += c6_max
        if file_ok and agent_rows and ground_truth:
            gt_order = [r["transaction_id"] for r in ground_truth]
            agent_order = [r["transaction_id"] for r in agent_rows]
            if agent_order == gt_order:
                c6_score = c6_max
                passed = True
            else:
                # Partial credit if top items are in correct order
                min_len = min(len(gt_order), len(agent_order))
                matching_prefix = 0
                for i in range(min_len):
                    if gt_order[i] == agent_order[i]:
                        matching_prefix += 1
                    else:
                        break
                c6_score = round(c6_max * matching_prefix / max(len(gt_order), 1))
                passed = False
            eval_criteria["sorting"] = {
                "passed": passed, "score": c6_score, "max_score": c6_max,
                **({"reason": "Incorrect sort order"} if not passed else {})
            }
            total_score += c6_score
        else:
            eval_criteria["sorting"] = {
                "passed": False, "score": 0, "max_score": c6_max,
                "reason": "Cannot evaluate - no data"
            }

        # --- Criterion 7: Response summary (10 pts) ---
        c7_max = 10
        max_score += c7_max
        c7_score = 0
        action_lower = action.lower() if action else ""

        # Check for total transactions reviewed
        gt_review_txns = self._query(
            "SELECT COUNT(*) as cnt FROM transactions WHERE purchase_date = ?",
            (review_date,)
        )
        total_reviewed = gt_review_txns[0]["cnt"]

        gt_high = sum(1 for r in ground_truth if r["risk_level"] == "HIGH")
        gt_medium = sum(1 for r in ground_truth if r["risk_level"] == "MEDIUM")
        gt_low = sum(1 for r in ground_truth if r["risk_level"] == "LOW")

        # Check counts appear in response (3 sub-checks + top 3 TIDs)
        summary_checks = 0
        total_checks = 4

        if str(total_reviewed) in action:
            summary_checks += 1
        if str(gt_high) in action and "high" in action_lower:
            summary_checks += 1
        if str(gt_medium) in action and "medium" in action_lower:
            summary_checks += 1

        # Top 3 highest-risk transaction IDs
        top3_tids = [r["transaction_id"] for r in ground_truth[:3]]
        if all(tid in action for tid in top3_tids):
            summary_checks += 1

        c7_score = round(c7_max * summary_checks / total_checks)
        passed = c7_score == c7_max
        eval_criteria["response_summary"] = {
            "passed": passed, "score": c7_score, "max_score": c7_max,
            **({"reason": f"Only {summary_checks}/{total_checks} summary elements present"} if not passed else {})
        }
        total_score += c7_score

        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

        return reward, info

    # -----------------------------------------------------------------------
    # verify
    # -----------------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        tool_call_count = 0

        # 1. Get review date
        review_info = self.tools["get_review_date"]()
        tool_call_count += 1
        review_date = review_info["review_date"]

        # 2. Load workspace config files
        rules_path = os.path.join(self.workspace, "fraud_scoring_rules.yaml")
        with open(rules_path, "r") as f:
            rules = yaml.safe_load(f)

        weights = {k: v["weight"] for k, v in rules["risk_factors"].items()}
        thresholds = rules["thresholds"]
        price_anomaly_pct = thresholds["price_anomaly_pct"]

        vel_path = os.path.join(self.workspace, "velocity_policy.csv")
        velocity_policy = {}
        with open(vel_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                velocity_policy[row["tier"]] = {
                    "max_purchases_today": int(row["max_purchases_today"]),
                    "max_purchases_7d": int(row["max_purchases_7d"]),
                }

        # 3. Load processor flags from batch CSVs
        processor_flags = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "batch_*.csv"))):
            with open(fp, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    processor_flags[row["transaction_id"]] = int(row["processor_risk_flag"])

        # 4. Load event pricing from JSON files
        event_max_prices = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "event_pricing_*.json"))):
            with open(fp, "r") as f:
                data = json.load(f)
                for item in data:
                    event_max_prices[item["event_id"]] = item["max_ticket_price"]

        # 5. Load verified countries from TXT files
        verified_countries = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "customer_verified_*.txt"))):
            with open(fp, "r") as f:
                header = f.readline()
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 2:
                        verified_countries[parts[0]] = parts[1]

        # 6. Get all review-date transactions (paginated)
        all_review_txns = []
        page = 1
        while True:
            result = self.tools["list_transactions_by_date"](date=review_date, page=page)
            tool_call_count += 1
            all_review_txns.extend(result["transactions"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 7. For each transaction, gather data and compute risk
        customer_cache = {}  # customer_id -> profile + history
        review_queue = []

        review_dt = datetime.strptime(review_date, "%Y-%m-%d")
        window_7d_start = (review_dt - timedelta(days=6)).strftime("%Y-%m-%d")

        for txn_summary in all_review_txns:
            tid = txn_summary["transaction_id"]
            cid = txn_summary["customer_id"]
            eid = txn_summary["event_id"]

            # Get transaction details
            txn_detail = self.tools["get_transaction_details"](transaction_id=tid)
            tool_call_count += 1
            amount = txn_detail["amount"]
            ticket_id = txn_detail["ticket_id"]

            # Get device session
            device = self.tools["get_device_session"](transaction_id=tid)
            tool_call_count += 1
            dev_country = device.get("country")
            vpn = device.get("vpn_detected", 0)

            # Get customer profile (cached)
            if cid not in customer_cache:
                profile = self.tools["get_customer_profile"](customer_id=cid)
                tool_call_count += 1

                # Get purchase history (all pages)
                history = []
                hist_page = 1
                while True:
                    hist_result = self.tools["get_purchase_history"](
                        customer_id=cid, page=hist_page
                    )
                    tool_call_count += 1
                    history.extend(hist_result["transactions"])
                    if hist_page >= hist_result["total_pages"]:
                        break
                    hist_page += 1

                customer_cache[cid] = {
                    "profile": profile,
                    "history": history,
                }

            profile = customer_cache[cid]["profile"]
            history = customer_cache[cid]["history"]
            tier = profile.get("account_tier", "standard")

            risk_factors = []

            # 1. Geo mismatch
            verified_country = verified_countries.get(cid)
            if dev_country and verified_country and dev_country != verified_country:
                risk_factors.append("geo_mismatch")

            # 2. Velocity violation
            limits = velocity_policy.get(tier, velocity_policy.get("standard", {}))
            today_count = sum(
                1 for h in history if h.get("purchase_date") == review_date
            )
            week_count = sum(
                1 for h in history
                if h.get("purchase_date", "") >= window_7d_start
                and h.get("purchase_date", "") <= review_date
            )
            if (today_count > limits.get("max_purchases_today", 999) or
                    week_count > limits.get("max_purchases_7d", 999)):
                risk_factors.append("velocity_violation")

            # 3. Resale detected
            resale = self.tools["check_resale_listings"](ticket_id=ticket_id)
            tool_call_count += 1
            if resale.get("found"):
                risk_factors.append("resale_detected")

            # 4. VPN detected
            if vpn:
                risk_factors.append("vpn_detected")

            # 5. Price anomaly
            max_price = event_max_prices.get(eid)
            if max_price and amount > max_price * (1 + price_anomaly_pct / 100):
                risk_factors.append("price_anomaly")

            # 6. Processor flag
            if processor_flags.get(tid, 0) == 1:
                risk_factors.append("processor_flag")

            # Compute score
            risk_score = sum(weights.get(f, 0) for f in risk_factors)

            if risk_score >= thresholds["high_risk"]:
                risk_level = "HIGH"
                action = "block_and_investigate"
            elif risk_score >= thresholds["medium_risk"]:
                risk_level = "MEDIUM"
                action = "manual_review"
            elif risk_score >= 10:
                risk_level = "LOW"
                action = "monitor"
            else:
                continue

            review_queue.append({
                "transaction_id": tid,
                "customer_id": cid,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "risk_factors": ";".join(sorted(risk_factors)),
                "recommended_action": action,
            })

        # Sort: risk_score descending, transaction_id ascending
        review_queue.sort(key=lambda x: (-x["risk_score"], x["transaction_id"]))

        # Write fraud_review_queue.csv
        queue_path = os.path.join(self.workspace, "fraud_review_queue.csv")
        with open(queue_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "transaction_id", "customer_id", "risk_score", "risk_level",
                "risk_factors", "recommended_action"
            ])
            writer.writeheader()
            for row in review_queue:
                writer.writerow(row)

        # Build summary response
        total_reviewed = len(all_review_txns)
        count_high = sum(1 for r in review_queue if r["risk_level"] == "HIGH")
        count_medium = sum(1 for r in review_queue if r["risk_level"] == "MEDIUM")
        count_low = sum(1 for r in review_queue if r["risk_level"] == "LOW")
        top3 = review_queue[:3]

        action_text = (
            f"Fraud review queue generated for {review_date}. "
            f"Total transactions reviewed: {total_reviewed}. "
            f"Flagged transactions: {len(review_queue)} "
            f"(HIGH: {count_high}, MEDIUM: {count_medium}, LOW: {count_low}). "
            f"Top 3 highest-risk transactions: "
        )
        for i, t in enumerate(top3):
            action_text += (
                f"{t['transaction_id']} (score: {t['risk_score']}, "
                f"level: {t['risk_level']}, factors: {t['risk_factors']})"
            )
            if i < len(top3) - 1:
                action_text += ", "
        action_text += "."

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need >= 15"

        return self.step(action_text)
