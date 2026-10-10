"""
Environment for hotel reservation fraud detection task.
Provides tools for querying reservation data and evaluates fraud review output.
"""

import sqlite3
import os
import json
import csv
import re
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

    # ----------------------------------------------------------------
    # Tool methods
    # ----------------------------------------------------------------

    @tool(
        description="Search reservations by check-in date. Returns a paginated list of reservations. Each page contains up to 20 results.",
        parameters={
            "type": "object",
            "properties": {
                "check_in_date": {
                    "type": "string",
                    "description": "Check-in date in YYYY-MM-DD format"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number starting from 1 (default: 1)"
                }
            },
            "required": ["check_in_date"]
        }
    )
    def search_reservations(self, check_in_date: str, page: int = 1) -> dict:
        page_size = 20
        offset = (max(1, page) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM reservations WHERE check_in_date = ?",
            (check_in_date,)
        )
        total = cursor.fetchone()[0]
        cursor.execute(
            "SELECT reservation_id, guest_id, payment_method_id, room_type, "
            "check_in_date, check_out_date, booking_date, amount, status "
            "FROM reservations WHERE check_in_date = ? "
            "ORDER BY reservation_id LIMIT ? OFFSET ?",
            (check_in_date, page_size, offset)
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
            "results": rows
        }

    @tool(
        description="Get detailed information about a specific guest by their guest ID.",
        parameters={
            "type": "object",
            "properties": {
                "guest_id": {
                    "type": "string",
                    "description": "The guest ID (e.g., G00001)"
                }
            },
            "required": ["guest_id"]
        }
    )
    def get_guest_info(self, guest_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM guests WHERE guest_id = ?", (guest_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Guest {guest_id} not found"}

    @tool(
        description="Check if a document number appears in the fraud blacklist database. Returns match details if found.",
        parameters={
            "type": "object",
            "properties": {
                "document_number": {
                    "type": "string",
                    "description": "The identity document number to check"
                }
            },
            "required": ["document_number"]
        }
    )
    def check_blacklist(self, document_number: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM blacklist WHERE id_document_number = ?",
            (document_number,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"match": True, **dict(row)}
        return {"match": False, "document_number": document_number}

    @tool(
        description="Get details of a specific payment method by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "payment_method_id": {
                    "type": "string",
                    "description": "The payment method ID (e.g., PM00001)"
                }
            },
            "required": ["payment_method_id"]
        }
    )
    def get_payment_method_details(self, payment_method_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM payment_methods WHERE payment_method_id = ?",
            (payment_method_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Payment method {payment_method_id} not found"}

    @tool(
        description="Get the total number of no-show records for a specific guest.",
        parameters={
            "type": "object",
            "properties": {
                "guest_id": {
                    "type": "string",
                    "description": "The guest ID (e.g., G00001)"
                }
            },
            "required": ["guest_id"]
        }
    )
    def get_no_show_count(self, guest_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM no_show_records WHERE guest_id = ?",
            (guest_id,)
        )
        count = cursor.fetchone()[0]
        conn.close()
        return {"guest_id": guest_id, "no_show_count": count}

    @tool(
        description="Get a specific reservation by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "reservation_id": {
                    "type": "string",
                    "description": "The reservation ID (e.g., R00001)"
                }
            },
            "required": ["reservation_id"]
        }
    )
    def get_reservation(self, reservation_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM reservations WHERE reservation_id = ?",
            (reservation_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Reservation {reservation_id} not found"}

    # ----------------------------------------------------------------
    # Helper: compute ground truth
    # ----------------------------------------------------------------

    def _load_yaml_config(self):
        """Parse the YAML config file (simple key-value YAML, no pyyaml needed)."""
        config_path = os.path.join(self.workspace, "fraud_scoring_rules.yaml")
        config = {"scoring_weights": {}, "thresholds": {}, "review_date": ""}
        current_section = None
        with open(config_path, "r") as f:
            for line in f:
                line = line.rstrip()
                if not line:
                    continue
                if line.startswith("scoring_weights:"):
                    current_section = "scoring_weights"
                elif line.startswith("thresholds:"):
                    current_section = "thresholds"
                elif line.startswith("review_date:"):
                    val = line.split(":", 1)[1].strip().strip('"')
                    config["review_date"] = val
                    current_section = None
                elif current_section and line.startswith("  "):
                    parts = line.strip().split(":")
                    key = parts[0].strip()
                    val = parts[1].strip()
                    try:
                        val = int(val)
                    except ValueError:
                        try:
                            val = float(val)
                        except ValueError:
                            pass
                    config[current_section][key] = val
        return config

    def _load_scan_data(self):
        """Load all identity scan batch files and index by guest_id."""
        scan_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("identity_scan_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    data = json.load(f)
                for entry in data:
                    scan_map[entry["guest_id"]] = entry["scan_confidence"]
        return scan_map

    def _load_chargeback_ratios(self):
        """Load all transaction log CSV files and compute chargeback ratio per payment method."""
        pm_stats = {}  # pm_id -> {"total": int, "chargebacks": int}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("transaction_log_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        pm_id = row["payment_method_id"]
                        if pm_id not in pm_stats:
                            pm_stats[pm_id] = {"total": 0, "chargebacks": 0}
                        pm_stats[pm_id]["total"] += 1
                        pm_stats[pm_id]["chargebacks"] += int(row["is_chargeback"])
        ratios = {}
        for pm_id, stats in pm_stats.items():
            if stats["total"] > 0:
                ratios[pm_id] = stats["chargebacks"] / stats["total"]
            else:
                ratios[pm_id] = 0.0
        return ratios

    def _load_booking_patterns(self):
        """Load all booking pattern TXT files and index by guest_id."""
        patterns = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("booking_pattern_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    current = {}
                    for line in f:
                        line = line.strip()
                        if line == "---":
                            if "guest_id" in current:
                                patterns[current["guest_id"]] = current.get("flagged_rapid", "no")
                            current = {}
                        elif line.startswith("GUEST_ID:"):
                            current["guest_id"] = line.split(":", 1)[1].strip()
                        elif line.startswith("FLAGGED_RAPID:"):
                            current["flagged_rapid"] = line.split(":", 1)[1].strip()
                    if "guest_id" in current:
                        patterns[current["guest_id"]] = current.get("flagged_rapid", "no")
        return patterns

    def _compute_ground_truth(self):
        """Compute the expected fraud review list."""
        config = self._load_yaml_config()
        weights = config["scoring_weights"]
        thresholds = config["thresholds"]
        review_date = config["review_date"]

        scan_map = self._load_scan_data()
        cb_ratios = self._load_chargeback_ratios()
        booking_patterns = self._load_booking_patterns()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get all reservations for review date
        cursor.execute(
            "SELECT * FROM reservations WHERE check_in_date = ? ORDER BY reservation_id",
            (review_date,)
        )
        review_reservations = [dict(r) for r in cursor.fetchall()]

        results = []
        for res in review_reservations:
            rid = res["reservation_id"]
            gid = res["guest_id"]
            pmid = res["payment_method_id"]

            # Get guest info
            cursor.execute("SELECT * FROM guests WHERE guest_id = ?", (gid,))
            guest = dict(cursor.fetchone())
            guest_name = f"{guest['first_name']} {guest['last_name']}"
            doc_num = guest["id_document_number"]

            # Check blacklist
            cursor.execute(
                "SELECT COUNT(*) FROM blacklist WHERE id_document_number = ?",
                (doc_num,)
            )
            is_blacklisted = cursor.fetchone()[0] > 0

            # Get payment method
            cursor.execute(
                "SELECT * FROM payment_methods WHERE payment_method_id = ?",
                (pmid,)
            )
            pm = dict(cursor.fetchone())

            # No-show count
            cursor.execute(
                "SELECT COUNT(*) FROM no_show_records WHERE guest_id = ?",
                (gid,)
            )
            no_show_count = cursor.fetchone()[0]

            # Compute risk score
            score = 0
            factors = []

            if is_blacklisted:
                score += weights["blacklist_match"]
                factors.append("blacklist_match")

            if pm["is_prepaid"]:
                score += weights["prepaid_card"]
                factors.append("prepaid_card")

            if pm["fraud_flag_count"] >= thresholds["fraud_flag_count_min"]:
                score += weights["high_fraud_flags"]
                factors.append("high_fraud_flags")

            if no_show_count >= thresholds["no_show_count_min"]:
                score += weights["no_show_history"]
                factors.append("no_show_history")

            scan_conf = scan_map.get(gid, 1.0)
            if scan_conf < thresholds["scan_confidence_min"]:
                score += weights["low_scan_confidence"]
                factors.append("low_scan_confidence")

            cb_ratio = cb_ratios.get(pmid, 0.0)
            if cb_ratio >= thresholds["chargeback_ratio_min"]:
                score += weights["high_chargeback_ratio"]
                factors.append("high_chargeback_ratio")

            rapid = booking_patterns.get(gid, "no")
            if rapid == "yes":
                score += weights["rapid_booking"]
                factors.append("rapid_booking")

            factors.sort()

            if score >= thresholds["risk_score_cutoff"]:
                priority = "critical" if score >= 60 else "high"
                results.append({
                    "reservation_id": rid,
                    "guest_name": guest_name,
                    "document_number": doc_num,
                    "risk_score": score,
                    "risk_factors": ";".join(factors),
                    "priority": priority,
                })

        conn.close()

        # Sort: risk_score desc, reservation_id asc
        results.sort(key=lambda x: (-x["risk_score"], x["reservation_id"]))
        return results

    # ----------------------------------------------------------------
    # Evaluation
    # ----------------------------------------------------------------

    def step(
        self, action: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        ground_truth = self._compute_ground_truth()
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: Output file exists (10 pts) ---
        c1_max = 10
        max_score += c1_max
        output_path = os.path.join(self.workspace, "daily_fraud_review.csv")
        file_exists = os.path.exists(output_path)
        if file_exists:
            total_score += c1_max
        eval_criteria["output_file_exists"] = {
            "passed": file_exists,
            "score": c1_max if file_exists else 0,
            "max_score": c1_max,
            "reason": "" if file_exists else "daily_fraud_review.csv not found in workspace"
        }

        if not file_exists:
            # Can't evaluate further
            for name, mx in [("correct_columns", 10), ("correct_reservations", 25),
                             ("correct_risk_scores", 20), ("correct_risk_factors", 15),
                             ("correct_sorting", 10), ("response_summary", 10)]:
                max_score += mx
                eval_criteria[name] = {
                    "passed": False, "score": 0, "max_score": mx,
                    "reason": "Output file missing"
                }
            return total_score / max_score, {
                "eval_criteria": eval_criteria,
                "total_score": total_score,
                "max_score": max_score,
            }

        # Parse output CSV
        try:
            with open(output_path, "r") as f:
                reader = csv.DictReader(f)
                output_rows = list(reader)
                output_columns = reader.fieldnames or []
        except Exception as e:
            output_rows = []
            output_columns = []

        expected_columns = ["reservation_id", "guest_name", "document_number",
                           "risk_score", "risk_factors", "priority"]

        # --- Criterion 2: Correct columns (10 pts) ---
        c2_max = 10
        max_score += c2_max
        cols_match = output_columns == expected_columns
        if cols_match:
            total_score += c2_max
        eval_criteria["correct_columns"] = {
            "passed": cols_match,
            "score": c2_max if cols_match else 0,
            "max_score": c2_max,
            "reason": "" if cols_match else f"Expected columns {expected_columns}, got {output_columns}"
        }

        # --- Criterion 3: Correct reservations identified (25 pts) ---
        c3_max = 25
        max_score += c3_max
        expected_ids = {r["reservation_id"] for r in ground_truth}
        actual_ids = {r.get("reservation_id", "") for r in output_rows}
        correct_ids = expected_ids == actual_ids
        if correct_ids:
            c3_score = c3_max
        else:
            # Partial credit: proportion of correct
            if len(expected_ids) == 0:
                c3_score = c3_max if len(actual_ids) == 0 else 0
            else:
                tp = len(expected_ids & actual_ids)
                fp = len(actual_ids - expected_ids)
                fn = len(expected_ids - actual_ids)
                precision = tp / (tp + fp) if (tp + fp) > 0 else 0
                recall = tp / (tp + fn) if (tp + fn) > 0 else 0
                f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
                c3_score = round(c3_max * f1)
        total_score += c3_score
        eval_criteria["correct_reservations"] = {
            "passed": correct_ids,
            "score": c3_score,
            "max_score": c3_max,
            "reason": "" if correct_ids else f"Missing: {expected_ids - actual_ids}, Extra: {actual_ids - expected_ids}"
        }

        # Build lookup from output
        output_map = {}
        for row in output_rows:
            rid = row.get("reservation_id", "")
            output_map[rid] = row

        # --- Criterion 4: Correct risk scores (20 pts) ---
        c4_max = 20
        max_score += c4_max
        if len(ground_truth) == 0:
            c4_score = c4_max if len(output_rows) == 0 else 0
        else:
            correct_scores = 0
            for gt_row in ground_truth:
                rid = gt_row["reservation_id"]
                if rid in output_map:
                    try:
                        actual_score = int(output_map[rid].get("risk_score", -1))
                    except (ValueError, TypeError):
                        actual_score = -1
                    if actual_score == gt_row["risk_score"]:
                        correct_scores += 1
            c4_score = round(c4_max * correct_scores / len(ground_truth))
        total_score += c4_score
        eval_criteria["correct_risk_scores"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": "" if c4_score == c4_max else f"Matched {correct_scores}/{len(ground_truth)} risk scores"
        }

        # --- Criterion 5: Correct risk factors (15 pts) ---
        c5_max = 15
        max_score += c5_max
        if len(ground_truth) == 0:
            c5_score = c5_max if len(output_rows) == 0 else 0
        else:
            correct_factors = 0
            for gt_row in ground_truth:
                rid = gt_row["reservation_id"]
                if rid in output_map:
                    actual_factors = output_map[rid].get("risk_factors", "")
                    if actual_factors == gt_row["risk_factors"]:
                        correct_factors += 1
            c5_score = round(c5_max * correct_factors / len(ground_truth))
        total_score += c5_score
        eval_criteria["correct_risk_factors"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": "" if c5_score == c5_max else f"Matched {correct_factors}/{len(ground_truth)} factor lists"
        }

        # --- Criterion 6: Correct sorting (10 pts) ---
        c6_max = 10
        max_score += c6_max
        if len(output_rows) <= 1:
            sort_correct = True
        else:
            sort_correct = True
            for i in range(len(output_rows) - 1):
                try:
                    s1 = int(output_rows[i].get("risk_score", 0))
                    s2 = int(output_rows[i + 1].get("risk_score", 0))
                except (ValueError, TypeError):
                    sort_correct = False
                    break
                r1 = output_rows[i].get("reservation_id", "")
                r2 = output_rows[i + 1].get("reservation_id", "")
                if s1 < s2:
                    sort_correct = False
                    break
                if s1 == s2 and r1 > r2:
                    sort_correct = False
                    break
        if sort_correct:
            total_score += c6_max
        eval_criteria["correct_sorting"] = {
            "passed": sort_correct,
            "score": c6_max if sort_correct else 0,
            "max_score": c6_max,
            "reason": "" if sort_correct else "Rows not sorted by risk_score desc / reservation_id asc"
        }

        # --- Criterion 7: Response summary (10 pts) ---
        c7_max = 10
        max_score += c7_max
        n_flagged = len(ground_truth)
        critical_ids = sorted([r["reservation_id"] for r in ground_truth if r["priority"] == "critical"])

        # Expected format: "Flagged: N reservations. Critical: R00001, R00002" or "Critical: none"
        expected_flagged_str = f"Flagged: {n_flagged} reservations."
        if critical_ids:
            expected_critical_str = f"Critical: {', '.join(critical_ids)}"
        else:
            expected_critical_str = "Critical: none"

        action_lower = action.lower() if action else ""
        flagged_match = f"flagged: {n_flagged} reservations" in action_lower
        if critical_ids:
            critical_match = all(cid in action for cid in critical_ids)
        else:
            critical_match = "critical: none" in action_lower

        c7_score = 0
        if flagged_match:
            c7_score += 5
        if critical_match:
            c7_score += 5
        total_score += c7_score
        eval_criteria["response_summary"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": "" if c7_score == c7_max else f"Expected '{expected_flagged_str} {expected_critical_str}'"
        }

        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ----------------------------------------------------------------
    # Verify
    # ----------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import os as _os

        # Step 1: Read scoring config from workspace
        config_path = _os.path.join(self.workspace, "fraud_scoring_rules.yaml")
        config = {"scoring_weights": {}, "thresholds": {}}
        current_section = None
        review_date = ""
        with open(config_path, "r") as f:
            for line in f:
                line = line.rstrip()
                if not line:
                    continue
                if line.startswith("scoring_weights:"):
                    current_section = "scoring_weights"
                elif line.startswith("thresholds:"):
                    current_section = "thresholds"
                elif line.startswith("review_date:"):
                    review_date = line.split(":", 1)[1].strip().strip('"')
                    current_section = None
                elif current_section and line.startswith("  "):
                    parts = line.strip().split(":")
                    key = parts[0].strip()
                    val = parts[1].strip()
                    try:
                        val = int(val)
                    except ValueError:
                        try:
                            val = float(val)
                        except ValueError:
                            pass
                    config[current_section][key] = val

        weights = config["scoring_weights"]
        thresholds = config["thresholds"]

        # Step 2: Load identity scan data from workspace JSON files
        scan_map = {}
        for fname in sorted(_os.listdir(self.workspace)):
            if fname.startswith("identity_scan_batch_") and fname.endswith(".json"):
                with open(_os.path.join(self.workspace, fname), "r") as f:
                    data = json.load(f)
                for entry in data:
                    scan_map[entry["guest_id"]] = entry["scan_confidence"]

        # Step 3: Load transaction data from workspace CSV files
        pm_txn_stats = {}
        for fname in sorted(_os.listdir(self.workspace)):
            if fname.startswith("transaction_log_") and fname.endswith(".csv"):
                with open(_os.path.join(self.workspace, fname), "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        pmid = row["payment_method_id"]
                        if pmid not in pm_txn_stats:
                            pm_txn_stats[pmid] = {"total": 0, "chargebacks": 0}
                        pm_txn_stats[pmid]["total"] += 1
                        pm_txn_stats[pmid]["chargebacks"] += int(row["is_chargeback"])
        cb_ratios = {}
        for pmid, stats in pm_txn_stats.items():
            cb_ratios[pmid] = stats["chargebacks"] / stats["total"] if stats["total"] > 0 else 0.0

        # Step 4: Load booking pattern data from workspace TXT files
        booking_patterns = {}
        for fname in sorted(_os.listdir(self.workspace)):
            if fname.startswith("booking_pattern_") and fname.endswith(".txt"):
                with open(_os.path.join(self.workspace, fname), "r") as f:
                    current = {}
                    for line in f:
                        line = line.strip()
                        if line == "---":
                            if "guest_id" in current:
                                booking_patterns[current["guest_id"]] = current.get("flagged_rapid", "no")
                            current = {}
                        elif line.startswith("GUEST_ID:"):
                            current["guest_id"] = line.split(":", 1)[1].strip()
                        elif line.startswith("FLAGGED_RAPID:"):
                            current["flagged_rapid"] = line.split(":", 1)[1].strip()
                    if "guest_id" in current:
                        booking_patterns[current["guest_id"]] = current.get("flagged_rapid", "no")

        # Step 5: Search reservations via tools (paginated)
        tool_call_count = 0
        all_reservations = []
        page = 1
        while True:
            result = self.tools["search_reservations"](check_in_date=review_date, page=page)
            tool_call_count += 1
            all_reservations.extend(result["results"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 6: For each reservation, gather data via tools
        review_list = []
        for res in all_reservations:
            rid = res["reservation_id"]
            gid = res["guest_id"]
            pmid = res["payment_method_id"]

            # Get guest info
            guest_info = self.tools["get_guest_info"](guest_id=gid)
            tool_call_count += 1
            guest_name = f"{guest_info['first_name']} {guest_info['last_name']}"
            doc_num = guest_info["id_document_number"]

            # Check blacklist
            bl_result = self.tools["check_blacklist"](document_number=doc_num)
            tool_call_count += 1

            # Get payment method
            pm_info = self.tools["get_payment_method_details"](payment_method_id=pmid)
            tool_call_count += 1

            # Get no-show count
            ns_result = self.tools["get_no_show_count"](guest_id=gid)
            tool_call_count += 1

            # Compute risk score
            score = 0
            factors = []

            if bl_result.get("match", False):
                score += weights.get("blacklist_match", 0)
                factors.append("blacklist_match")

            if pm_info.get("is_prepaid", 0):
                score += weights.get("prepaid_card", 0)
                factors.append("prepaid_card")

            if pm_info.get("fraud_flag_count", 0) >= thresholds.get("fraud_flag_count_min", 999):
                score += weights.get("high_fraud_flags", 0)
                factors.append("high_fraud_flags")

            if ns_result.get("no_show_count", 0) >= thresholds.get("no_show_count_min", 999):
                score += weights.get("no_show_history", 0)
                factors.append("no_show_history")

            scan_conf = scan_map.get(gid, 1.0)
            if scan_conf < thresholds.get("scan_confidence_min", 0.0):
                score += weights.get("low_scan_confidence", 0)
                factors.append("low_scan_confidence")

            cb_ratio = cb_ratios.get(pmid, 0.0)
            if cb_ratio >= thresholds.get("chargeback_ratio_min", 1.0):
                score += weights.get("high_chargeback_ratio", 0)
                factors.append("high_chargeback_ratio")

            rapid = booking_patterns.get(gid, "no")
            if rapid == "yes":
                score += weights.get("rapid_booking", 0)
                factors.append("rapid_booking")

            factors.sort()
            cutoff = thresholds.get("risk_score_cutoff", 30)
            if score >= cutoff:
                priority = "critical" if score >= 60 else "high"
                review_list.append({
                    "reservation_id": rid,
                    "guest_name": guest_name,
                    "document_number": doc_num,
                    "risk_score": score,
                    "risk_factors": ";".join(factors),
                    "priority": priority,
                })

        # Sort: risk_score desc, reservation_id asc
        review_list.sort(key=lambda x: (-x["risk_score"], x["reservation_id"]))

        # Step 7: Write output CSV
        output_path = _os.path.join(self.workspace, "daily_fraud_review.csv")
        fieldnames = ["reservation_id", "guest_name", "document_number",
                      "risk_score", "risk_factors", "priority"]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(review_list)

        # Step 8: Construct response
        n_flagged = len(review_list)
        critical_ids = sorted([r["reservation_id"] for r in review_list if r["priority"] == "critical"])
        if critical_ids:
            critical_str = ", ".join(critical_ids)
        else:
            critical_str = "none"

        action = f"Flagged: {n_flagged} reservations. Critical: {critical_str}"

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need >= 15"

        return self.step(action)
