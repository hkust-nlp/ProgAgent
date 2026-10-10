"""
Task environment for warranty claim fraud detection.
"""

import sqlite3
import os
import re
import json
import csv
from typing import Tuple, Dict, List, Any
from datetime import datetime


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

    # =========================================================================
    # Tool Methods
    # =========================================================================

    @tool(
        description=(
            "List warranty claims currently in pending_review status."
            " Returns a paginated list with 20 claims per page."
            " Each entry contains only claim_id and status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed.",
                },
            },
            "required": ["page"],
        },
    )
    def list_pending_claims(self, page: int) -> dict:
        PAGE_SIZE = 20
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT claim_id, status FROM claims "
            "WHERE status='pending_review' ORDER BY claim_id"
        )
        all_rows = cursor.fetchall()
        conn.close()

        all_claims = [{"claim_id": r[0], "status": r[1]} for r in all_rows]
        start = (page - 1) * PAGE_SIZE
        end = start + PAGE_SIZE
        page_claims = all_claims[start:end]

        return {
            "claims": page_claims,
            "page": page,
            "page_size": PAGE_SIZE,
            "total_count": len(all_claims),
            "has_next_page": end < len(all_claims),
        }

    @tool(
        description=(
            "Get full details for a single warranty claim by its claim ID."
            " Returns claim_id, customer_id, serial_number, claim_date,"
            " claim_type, failure_description, status, and purchase_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "claim_id": {
                    "type": "string",
                    "description": "The claim identifier, e.g. CLM-0001.",
                },
            },
            "required": ["claim_id"],
        },
    )
    def get_claim_details(self, claim_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM claims WHERE claim_id=?", (claim_id,))
        row = cursor.fetchone()
        if row is None:
            conn.close()
            return {"error": f"Claim {claim_id} not found"}
        cols = [d[0] for d in cursor.description]
        conn.close()
        return dict(zip(cols, row))

    @tool(
        description=(
            "Get product information by serial number."
            " Returns serial_number, model_name, production_date,"
            " production_line, batch_id, and msrp."
        ),
        parameters={
            "type": "object",
            "properties": {
                "serial_number": {
                    "type": "string",
                    "description": "Product serial number, e.g. SN-00001.",
                },
            },
            "required": ["serial_number"],
        },
    )
    def get_product_info(self, serial_number: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM products WHERE serial_number=?", (serial_number,)
        )
        row = cursor.fetchone()
        if row is None:
            conn.close()
            return {"error": f"Product {serial_number} not found"}
        cols = [d[0] for d in cursor.description]
        conn.close()
        return dict(zip(cols, row))

    @tool(
        description=(
            "Get quality control test records for a product by serial number."
            " Returns a list of QC records each containing qc_id,"
            " serial_number, test_station, test_type, test_date, result,"
            " defect_code, and inspector_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "serial_number": {
                    "type": "string",
                    "description": "Product serial number, e.g. SN-00001.",
                },
            },
            "required": ["serial_number"],
        },
    )
    def get_qc_records(self, serial_number: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM qc_records WHERE serial_number=? ORDER BY test_date",
            (serial_number,),
        )
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        conn.close()
        records = [dict(zip(cols, r)) for r in rows]
        return {"records": records, "count": len(records)}

    @tool(
        description=(
            "Get service history for a product by serial number."
            " Returns service records containing service_id, serial_number,"
            " repair_center_id, service_date, repair_type, and technician_id."
            " Note: detailed repair cost information is maintained separately"
            " by each repair center and is not available through this endpoint."
        ),
        parameters={
            "type": "object",
            "properties": {
                "serial_number": {
                    "type": "string",
                    "description": "Product serial number, e.g. SN-00001.",
                },
            },
            "required": ["serial_number"],
        },
    )
    def get_service_history(self, serial_number: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT service_id, serial_number, repair_center_id,"
            " service_date, repair_type, technician_id"
            " FROM service_history WHERE serial_number=?"
            " ORDER BY service_date",
            (serial_number,),
        )
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        conn.close()
        records = [dict(zip(cols, r)) for r in rows]
        return {"records": records, "total_count": len(records)}

    @tool(
        description=(
            "Get customer information by customer ID."
            " Returns customer_id, name, email, phone, address,"
            " and registration_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Customer identifier, e.g. CUST-0001.",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_customer_info(self, customer_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM customers WHERE customer_id=?", (customer_id,)
        )
        row = cursor.fetchone()
        if row is None:
            conn.close()
            return {"error": f"Customer {customer_id} not found"}
        cols = [d[0] for d in cursor.description]
        conn.close()
        return dict(zip(cols, row))

    # =========================================================================
    # Ground Truth Computation
    # =========================================================================

    def _compute_ground_truth(self) -> dict:
        """Compute the correct set of flagged claims from DB + workspace."""
        import yaml

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Load workspace config files
        rules_path = os.path.join(self.workspace, "fraud_detection_rules.yaml")
        policy_path = os.path.join(self.workspace, "warranty_policy.yaml")
        with open(rules_path) as f:
            rules = yaml.safe_load(f)
        with open(policy_path) as f:
            policy = yaml.safe_load(f)

        # Load photo dates from workspace
        photo_dates: Dict[str, str] = {}
        photo_dir = os.path.join(self.workspace, "photo_analysis")
        if os.path.isdir(photo_dir):
            for fname in sorted(os.listdir(photo_dir)):
                if fname.endswith(".json"):
                    with open(os.path.join(photo_dir, fname)) as f:
                        for entry in json.load(f):
                            photo_dates[entry["claim_id"]] = entry[
                                "photo_taken_date"
                            ]

        # Load repair costs from workspace
        repair_costs: Dict[str, float] = {}
        repair_dir = os.path.join(self.workspace, "repair_logs")
        if os.path.isdir(repair_dir):
            for fname in sorted(os.listdir(repair_dir)):
                if fname.endswith(".csv"):
                    with open(os.path.join(repair_dir, fname)) as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            sn = row["serial_number"]
                            cost = float(row["repair_cost"])
                            repair_costs[sn] = repair_costs.get(sn, 0) + cost

        # Get all pending claims
        cursor.execute(
            "SELECT * FROM claims WHERE status='pending_review' ORDER BY claim_id"
        )
        claim_cols = [d[0] for d in cursor.description]
        pending_claims = [dict(zip(claim_cols, r)) for r in cursor.fetchall()]

        flagged: Dict[str, dict] = {}

        for claim in pending_claims:
            cid = claim["claim_id"]
            sn = claim["serial_number"]
            flags: list = []

            # Product info
            cursor.execute(
                "SELECT * FROM products WHERE serial_number=?", (sn,)
            )
            pcols = [d[0] for d in cursor.description]
            prod = dict(zip(pcols, cursor.fetchone()))

            claim_date = datetime.fromisoformat(claim["claim_date"]).date()
            purchase_date = datetime.fromisoformat(claim["purchase_date"]).date()
            prod_date = datetime.fromisoformat(prod["production_date"]).date()
            model = prod["model_name"]
            msrp = prod["msrp"]

            # Rule 1: PHOTO_TIMESTAMP_ANOMALY
            if cid in photo_dates:
                photo_date = datetime.fromisoformat(photo_dates[cid]).date()
                diff = (claim_date - photo_date).days
                max_before = rules["rules"]["PHOTO_TIMESTAMP_ANOMALY"][
                    "max_days_before_claim"
                ]
                max_after = rules["rules"]["PHOTO_TIMESTAMP_ANOMALY"][
                    "max_days_after_claim"
                ]
                if diff > max_before or diff < -max_after:
                    flags.append("PHOTO_TIMESTAMP_ANOMALY")

            # Rule 2: WARRANTY_EXPIRED
            warranty_days = policy["warranty_durations_days"][model]
            if (claim_date - purchase_date).days > warranty_days:
                flags.append("WARRANTY_EXPIRED")

            # Rule 3: QC_PASS_CONTRADICTION
            cursor.execute(
                "SELECT result FROM qc_records WHERE serial_number=?", (sn,)
            )
            qc_results = [r[0] for r in cursor.fetchall()]
            if (
                claim["claim_type"] == "manufacturing_defect"
                and qc_results
                and all(r == "pass" for r in qc_results)
            ):
                flags.append("QC_PASS_CONTRADICTION")

            # Rule 4: PRODUCTION_DATE_ANOMALY
            if prod_date > purchase_date:
                flags.append("PRODUCTION_DATE_ANOMALY")

            # Rule 5: REPEAT_SERVICE
            cursor.execute(
                "SELECT COUNT(*) FROM service_history WHERE serial_number=?",
                (sn,),
            )
            svc_count = cursor.fetchone()[0]
            max_svcs = rules["rules"]["REPEAT_SERVICE"]["max_prior_services"]
            if svc_count > max_svcs:
                flags.append("REPEAT_SERVICE")

            # Rule 6: EXCESSIVE_REPAIR_COST
            total_cost = repair_costs.get(sn, 0)
            threshold_pct = rules["rules"]["EXCESSIVE_REPAIR_COST"][
                "cost_threshold_pct"
            ]
            if total_cost > msrp * threshold_pct / 100:
                flags.append("EXCESSIVE_REPAIR_COST")

            if flags:
                flags.sort()
                risk_score = min(
                    sum(rules["rules"][f]["risk_points"] for f in flags),
                    rules["risk_score_cap"],
                )
                flagged[cid] = {
                    "serial_number": sn,
                    "customer_id": claim["customer_id"],
                    "flags": "|".join(flags),
                    "flag_count": len(flags),
                    "risk_score": risk_score,
                }

        conn.close()
        return flagged

    # =========================================================================
    # step
    # =========================================================================

    def step(
        self, action: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.

        Returns a reward based on evaluation results.

        Args:
            action: The agent's final response.

        Returns:
            reward: The reward based on task completion (between 0.0 and 1.0).
            info: Evaluation results.
        """
        gt = self._compute_ground_truth()
        criteria: Dict[str, dict] = {}
        total_score = 0
        max_score = 0

        # ----- Criterion 1: report file exists with correct columns (10 pts) -----
        report_path = os.path.join(self.workspace, "flagged_claims_report.csv")
        expected_cols = [
            "claim_id", "serial_number", "customer_id",
            "flags", "flag_count", "risk_score",
        ]
        report_ok = False
        report_data: list = []

        if os.path.isfile(report_path):
            try:
                with open(report_path, newline="") as f:
                    reader = csv.DictReader(f)
                    actual_cols = list(reader.fieldnames or [])
                    if set(expected_cols) <= set(actual_cols):
                        report_ok = True
                        report_data = list(reader)
                        criteria["report_format"] = {
                            "passed": True, "score": 10, "max_score": 10,
                        }
                    else:
                        missing = set(expected_cols) - set(actual_cols)
                        criteria["report_format"] = {
                            "passed": False, "score": 0, "max_score": 10,
                            "reason": f"Missing columns: {missing}",
                        }
            except Exception as e:
                criteria["report_format"] = {
                    "passed": False, "score": 0, "max_score": 10,
                    "reason": f"Error reading report: {e}",
                }
        else:
            criteria["report_format"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "flagged_claims_report.csv not found",
            }

        max_score += 10
        total_score += criteria["report_format"]["score"]

        if not report_ok:
            for cname, mx in [
                ("flagged_completeness", 20),
                ("no_false_positives", 15),
                ("correct_flags", 20),
                ("correct_risk_scores", 15),
                ("sort_order", 10),
            ]:
                criteria[cname] = {
                    "passed": False, "score": 0, "max_score": mx,
                    "reason": "Report file not available",
                }
                max_score += mx
        else:
            report_claims: Dict[str, dict] = {}
            for row in report_data:
                report_claims[row["claim_id"]] = row

            gt_ids = set(gt.keys())
            report_ids = set(report_claims.keys())
            found = gt_ids & report_ids

            # ----- Criterion 2: flagged completeness (20 pts) -----
            if gt_ids:
                completeness = len(found) / len(gt_ids)
            else:
                completeness = 1.0 if not report_ids else 0.0
            score2 = round(20 * completeness)
            criteria["flagged_completeness"] = {
                "passed": completeness == 1.0,
                "score": score2,
                "max_score": 20,
            }
            if completeness < 1.0:
                criteria["flagged_completeness"]["reason"] = (
                    f"Found {len(found)}/{len(gt_ids)} expected claims"
                )
            max_score += 20
            total_score += score2

            # ----- Criterion 3: no false positives (15 pts) -----
            false_positives = report_ids - gt_ids
            if report_ids:
                fp_ratio = len(false_positives) / len(report_ids)
                score3 = round(15 * (1 - fp_ratio))
            else:
                score3 = 15
            criteria["no_false_positives"] = {
                "passed": len(false_positives) == 0,
                "score": score3,
                "max_score": 15,
            }
            if false_positives:
                criteria["no_false_positives"]["reason"] = (
                    f"{len(false_positives)} false positive(s)"
                )
            max_score += 15
            total_score += score3

            # ----- Criterion 4: correct flags per claim (20 pts) -----
            correct_flags_n = 0
            for cid in found:
                if report_claims[cid]["flags"] == gt[cid]["flags"]:
                    correct_flags_n += 1
            n_comp = len(gt_ids) if gt_ids else 1
            score4 = round(20 * correct_flags_n / n_comp)
            criteria["correct_flags"] = {
                "passed": correct_flags_n == len(gt_ids),
                "score": score4,
                "max_score": 20,
            }
            if score4 < 20:
                criteria["correct_flags"]["reason"] = (
                    f"{correct_flags_n}/{len(gt_ids)} claims with correct flags"
                )
            max_score += 20
            total_score += score4

            # ----- Criterion 5: correct risk scores (15 pts) -----
            correct_scores_n = 0
            for cid in found:
                try:
                    reported = int(float(report_claims[cid]["risk_score"]))
                    if reported == gt[cid]["risk_score"]:
                        correct_scores_n += 1
                except (ValueError, KeyError):
                    pass
            score5 = round(15 * correct_scores_n / n_comp)
            criteria["correct_risk_scores"] = {
                "passed": correct_scores_n == len(gt_ids),
                "score": score5,
                "max_score": 15,
            }
            if score5 < 15:
                criteria["correct_risk_scores"]["reason"] = (
                    f"{correct_scores_n}/{len(gt_ids)} claims with correct scores"
                )
            max_score += 15
            total_score += score5

            # ----- Criterion 6: sort order (10 pts) -----
            gt_sorted = sorted(
                gt.keys(), key=lambda c: (-gt[c]["risk_score"], c)
            )
            report_order = [row["claim_id"] for row in report_data]
            # Only check order of entries that are in gt
            report_gt_order = [c for c in report_order if c in gt_ids]
            if report_gt_order == gt_sorted:
                score6 = 10
            else:
                score6 = 0
            criteria["sort_order"] = {
                "passed": score6 == 10,
                "score": score6,
                "max_score": 10,
            }
            if score6 == 0:
                criteria["sort_order"]["reason"] = "Incorrect sort order"
            max_score += 10
            total_score += score6

        # ----- Criterion 7: summary count in response (10 pts) -----
        expected_count = len(gt)
        pattern = r"\b" + str(expected_count) + r"\b"
        if re.search(pattern, action):
            score7 = 10
        else:
            score7 = 0
        criteria["summary_count"] = {
            "passed": score7 == 10,
            "score": score7,
            "max_score": 10,
        }
        if score7 == 0:
            criteria["summary_count"]["reason"] = (
                f"Expected count {expected_count} not found in response"
            )
        max_score += 10
        total_score += score7

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # =========================================================================
    # verify
    # =========================================================================

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
        import yaml

        # ------------------------------------------------------------------
        # 1. Read workspace configuration files
        # ------------------------------------------------------------------
        with open(
            os.path.join(self.workspace, "fraud_detection_rules.yaml")
        ) as f:
            rules = yaml.safe_load(f)
        with open(
            os.path.join(self.workspace, "warranty_policy.yaml")
        ) as f:
            policy = yaml.safe_load(f)

        # ------------------------------------------------------------------
        # 2. Read all photo dates from workspace
        # ------------------------------------------------------------------
        photo_dates: Dict[str, str] = {}
        photo_dir = os.path.join(self.workspace, "photo_analysis")
        if os.path.isdir(photo_dir):
            for fname in sorted(os.listdir(photo_dir)):
                if fname.endswith(".json"):
                    with open(os.path.join(photo_dir, fname)) as fh:
                        for entry in json.load(fh):
                            photo_dates[entry["claim_id"]] = entry[
                                "photo_taken_date"
                            ]

        # ------------------------------------------------------------------
        # 3. Read all repair costs from workspace
        # ------------------------------------------------------------------
        repair_costs: Dict[str, float] = {}
        repair_dir = os.path.join(self.workspace, "repair_logs")
        if os.path.isdir(repair_dir):
            for fname in sorted(os.listdir(repair_dir)):
                if fname.endswith(".csv"):
                    with open(os.path.join(repair_dir, fname)) as fh:
                        reader = csv.DictReader(fh)
                        for row in reader:
                            sn = row["serial_number"]
                            cost = float(row["repair_cost"])
                            repair_costs[sn] = (
                                repair_costs.get(sn, 0) + cost
                            )

        # ------------------------------------------------------------------
        # 4. List all pending claims via tool (paginated)
        # ------------------------------------------------------------------
        all_pending: list = []
        page = 1
        while True:
            result = self.tools["list_pending_claims"](page=page)
            all_pending.extend(result["claims"])
            if not result["has_next_page"]:
                break
            page += 1

        # ------------------------------------------------------------------
        # 5. For each pending claim, gather data via tools & apply rules
        # ------------------------------------------------------------------
        flagged_claims: list = []

        for pending in all_pending:
            claim_id = pending["claim_id"]

            # Tool calls
            claim = self.tools["get_claim_details"](claim_id=claim_id)
            sn = claim["serial_number"]
            customer_id = claim["customer_id"]

            product = self.tools["get_product_info"](serial_number=sn)
            qc_result = self.tools["get_qc_records"](serial_number=sn)
            svc_result = self.tools["get_service_history"](serial_number=sn)

            claim_date = datetime.fromisoformat(claim["claim_date"]).date()
            purchase_date = datetime.fromisoformat(
                claim["purchase_date"]
            ).date()
            prod_date = datetime.fromisoformat(
                product["production_date"]
            ).date()
            model_name = product["model_name"]
            msrp = product["msrp"]

            flags: list = []

            # Rule 1: PHOTO_TIMESTAMP_ANOMALY
            if claim_id in photo_dates:
                photo_date = datetime.fromisoformat(
                    photo_dates[claim_id]
                ).date()
                diff = (claim_date - photo_date).days
                max_before = rules["rules"]["PHOTO_TIMESTAMP_ANOMALY"][
                    "max_days_before_claim"
                ]
                max_after = rules["rules"]["PHOTO_TIMESTAMP_ANOMALY"][
                    "max_days_after_claim"
                ]
                if diff > max_before or diff < -max_after:
                    flags.append("PHOTO_TIMESTAMP_ANOMALY")

            # Rule 2: WARRANTY_EXPIRED
            warranty_days = policy["warranty_durations_days"][model_name]
            if (claim_date - purchase_date).days > warranty_days:
                flags.append("WARRANTY_EXPIRED")

            # Rule 3: QC_PASS_CONTRADICTION
            qc_records = qc_result["records"]
            if (
                claim["claim_type"] == "manufacturing_defect"
                and qc_records
                and all(r["result"] == "pass" for r in qc_records)
            ):
                flags.append("QC_PASS_CONTRADICTION")

            # Rule 4: PRODUCTION_DATE_ANOMALY
            if prod_date > purchase_date:
                flags.append("PRODUCTION_DATE_ANOMALY")

            # Rule 5: REPEAT_SERVICE
            max_svcs = rules["rules"]["REPEAT_SERVICE"]["max_prior_services"]
            if svc_result["total_count"] > max_svcs:
                flags.append("REPEAT_SERVICE")

            # Rule 6: EXCESSIVE_REPAIR_COST
            total_cost = repair_costs.get(sn, 0)
            threshold_pct = rules["rules"]["EXCESSIVE_REPAIR_COST"][
                "cost_threshold_pct"
            ]
            if total_cost > msrp * threshold_pct / 100:
                flags.append("EXCESSIVE_REPAIR_COST")

            if flags:
                flags.sort()
                risk_score = min(
                    sum(rules["rules"][f]["risk_points"] for f in flags),
                    rules["risk_score_cap"],
                )
                flagged_claims.append({
                    "claim_id": claim_id,
                    "serial_number": sn,
                    "customer_id": customer_id,
                    "flags": "|".join(flags),
                    "flag_count": len(flags),
                    "risk_score": risk_score,
                })

        # ------------------------------------------------------------------
        # 6. Sort by risk_score descending, claim_id ascending
        # ------------------------------------------------------------------
        flagged_claims.sort(key=lambda x: (-x["risk_score"], x["claim_id"]))

        # ------------------------------------------------------------------
        # 7. Write flagged_claims_report.csv
        # ------------------------------------------------------------------
        report_path = os.path.join(self.workspace, "flagged_claims_report.csv")
        fieldnames = [
            "claim_id", "serial_number", "customer_id",
            "flags", "flag_count", "risk_score",
        ]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flagged_claims)

        # ------------------------------------------------------------------
        # 8. Construct action string
        # ------------------------------------------------------------------
        action = (
            f"Fraud investigation complete. {len(flagged_claims)} claims"
            f" flagged out of {len(all_pending)} pending claims reviewed."
        )

        return self.step(action)
