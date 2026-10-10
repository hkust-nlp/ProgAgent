"""
Environment for Certified Seed Lot Purity Compliance Validation task.
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

    # ---- Tool Methods ----

    @tool(
        description="List seed lots with optional filters. Returns paginated results with lot_id, crop_type, variety, status, and harvest_date. Use page parameter for pagination (20 results per page).",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending_review", "certified", "rejected"],
                    "description": "Filter by lot status",
                },
                "crop_type": {
                    "type": "string",
                    "description": "Filter by crop type (e.g., corn, wheat, soybean)",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based), 20 results per page",
                    "default": 1,
                },
            },
            "required": [],
        },
    )
    def list_seed_lots(self, status: str = None, crop_type: str = None, page: int = 1):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT lot_id, crop_type, variety, status, harvest_date FROM seed_lots WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if crop_type:
            query += " AND crop_type = ?"
            params.append(crop_type)
        query += " ORDER BY lot_id"
        rows = conn.execute(query, params).fetchall()
        conn.close()

        total = len(rows)
        page_size = 20
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = rows[start:end]
        return {
            "lots": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get detailed information for a specific seed lot by lot_id. Returns crop_type, variety, parent_lot_id, field_id, harvest_date, weight_kg, and status.",
        parameters={
            "type": "object",
            "properties": {
                "lot_id": {
                    "type": "string",
                    "description": "The lot identifier (e.g., LOT-0001)",
                },
            },
            "required": ["lot_id"],
        },
    )
    def get_lot_details(self, lot_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM seed_lots WHERE lot_id = ?", (lot_id,)).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Lot {lot_id} not found"}

    @tool(
        description="Get the harvest log for a specific field. Returns field_id, crop_type, harvest_date, yield_kg, equipment_id, operator_name, and notes.",
        parameters={
            "type": "object",
            "properties": {
                "field_id": {
                    "type": "string",
                    "description": "The field identifier (e.g., FIELD-0001)",
                },
            },
            "required": ["field_id"],
        },
    )
    def get_harvest_log(self, field_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM harvest_logs WHERE field_id = ?", (field_id,)
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"No harvest log for field {field_id}"}

    @tool(
        description="Get germination test results for a specific seed lot. Returns all tests for the lot, including test_date, germination_rate, purity_pct, moisture_pct, weed_seed_count, other_crop_seed_count, inert_matter_pct, lab_name, and technician_name.",
        parameters={
            "type": "object",
            "properties": {
                "lot_id": {
                    "type": "string",
                    "description": "The lot identifier (e.g., LOT-0001)",
                },
            },
            "required": ["lot_id"],
        },
    )
    def get_germination_results(self, lot_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM germination_tests WHERE lot_id = ? ORDER BY test_date DESC",
            (lot_id,),
        ).fetchall()
        conn.close()
        if rows:
            return {"tests": [dict(r) for r in rows]}
        return {"error": f"No germination tests for lot {lot_id}"}

    @tool(
        description="Get the parent seed stock certificate for a given parent lot ID. Returns certification_body, issue_date, expiry_date, generation, crop_type, variety, and cert_status.",
        parameters={
            "type": "object",
            "properties": {
                "parent_lot_id": {
                    "type": "string",
                    "description": "The parent lot identifier (e.g., PARENT-0001)",
                },
            },
            "required": ["parent_lot_id"],
        },
    )
    def get_parent_certificate(self, parent_lot_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM parent_certificates WHERE parent_lot_id = ?",
            (parent_lot_id,),
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"No certificate for parent lot {parent_lot_id}"}

    @tool(
        description="Get government inspection records for a specific seed lot. Returns all inspection records including inspector_name, inspection_date, field_inspection_passed, lab_inspection_passed, documentation_complete, overall_result, and notes.",
        parameters={
            "type": "object",
            "properties": {
                "lot_id": {
                    "type": "string",
                    "description": "The lot identifier (e.g., LOT-0001)",
                },
            },
            "required": ["lot_id"],
        },
    )
    def get_inspection_records(self, lot_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM inspection_records WHERE lot_id = ? ORDER BY inspection_date DESC",
            (lot_id,),
        ).fetchall()
        conn.close()
        if rows:
            return {"records": [dict(r) for r in rows]}
        return {"error": f"No inspection records for lot {lot_id}"}

    # ---- Evaluation ----

    def _compute_ground_truth(self):
        """Compute expected compliance results using DB and workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load thresholds
        with open(os.path.join(self.workspace, "compliance_thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)["crop_thresholds"]

        # Load vigor scores from lab analysis JSONs
        vigor_map = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "lab_analysis_report_*.json"))):
            with open(fpath) as f:
                entries = json.load(f)
            for entry in entries:
                vigor_map[entry["lot_id"]] = entry["vigor_score"]

        # Load field conditions from CSVs
        field_conditions = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "field_condition_report_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    field_conditions[row["field_id"]] = {
                        "temperature_c": float(row["temperature_c"]),
                        "rainfall_mm": float(row["rainfall_mm"]),
                    }

        # Get all pending_review lots
        pending_lots = conn.execute(
            "SELECT * FROM seed_lots WHERE status = 'pending_review' ORDER BY lot_id"
        ).fetchall()
        pending_lots = [dict(r) for r in pending_lots]

        accepted = []
        rejected = []
        cert_date = "2025-12-01"

        for lot in pending_lots:
            lot_id = lot["lot_id"]
            crop = lot["crop_type"]
            variety = lot["variety"]
            parent_lot_id = lot["parent_lot_id"]
            field_id = lot["field_id"]
            harvest_date = lot["harvest_date"]
            crop_thresh = thresholds.get(crop, {})
            reasons = []

            # 1. Parent certificate check
            parent_cert = conn.execute(
                "SELECT * FROM parent_certificates WHERE parent_lot_id = ?",
                (parent_lot_id,),
            ).fetchone()
            if parent_cert:
                parent_cert = dict(parent_cert)
                if parent_cert["cert_status"] != "valid":
                    reasons.append(f"parent_cert_status_{parent_cert['cert_status']}")
                if parent_cert["expiry_date"] < harvest_date:
                    reasons.append("parent_cert_expired_before_harvest")
                if parent_cert["crop_type"] != crop:
                    reasons.append("parent_crop_mismatch")
                if parent_cert["variety"] != variety:
                    reasons.append("parent_variety_mismatch")
                valid_gens = crop_thresh.get("valid_parent_generations", [])
                if parent_cert["generation"] not in valid_gens:
                    reasons.append("invalid_parent_generation")
            else:
                reasons.append("no_parent_certificate")

            # 2. Germination test check (most recent)
            germ_tests = conn.execute(
                "SELECT * FROM germination_tests WHERE lot_id = ? ORDER BY test_date DESC",
                (lot_id,),
            ).fetchall()
            if germ_tests:
                gt = dict(germ_tests[0])
                if gt["germination_rate"] < crop_thresh.get("min_germination_rate", 0):
                    reasons.append("low_germination_rate")
                if gt["purity_pct"] < crop_thresh.get("min_purity_pct", 0):
                    reasons.append("low_purity")
                if gt["moisture_pct"] > crop_thresh.get("max_moisture_pct", 100):
                    reasons.append("high_moisture")
                if gt["weed_seed_count"] > crop_thresh.get("max_weed_seed_count", 999):
                    reasons.append("excess_weed_seeds")
                if gt["other_crop_seed_count"] > crop_thresh.get("max_other_crop_seed_count", 999):
                    reasons.append("excess_other_crop_seeds")
                if gt["inert_matter_pct"] > crop_thresh.get("max_inert_matter_pct", 100):
                    reasons.append("excess_inert_matter")
            else:
                reasons.append("no_germination_test")

            # 3. Vigor check
            vigor = vigor_map.get(lot_id)
            if vigor is not None:
                if vigor < crop_thresh.get("min_vigor_score", 0):
                    reasons.append("low_vigor_score")
            else:
                reasons.append("no_vigor_score")

            # 4. Field condition check
            fc = field_conditions.get(field_id)
            if fc:
                if fc["temperature_c"] > crop_thresh.get("max_harvest_temperature_c", 999):
                    reasons.append("harvest_temperature_exceeded")
                if fc["rainfall_mm"] > crop_thresh.get("max_harvest_rainfall_mm", 999):
                    reasons.append("harvest_rainfall_exceeded")
            else:
                reasons.append("no_field_condition_data")

            # 5. Inspection check (most recent)
            inspections = conn.execute(
                "SELECT * FROM inspection_records WHERE lot_id = ? ORDER BY inspection_date DESC",
                (lot_id,),
            ).fetchall()
            if inspections:
                insp = dict(inspections[0])
                if insp["overall_result"] != "passed":
                    reasons.append(f"inspection_{insp['overall_result']}")
            else:
                reasons.append("no_inspection_record")

            if len(reasons) == 0:
                lot_num = lot_id.split("-")[1]
                cert_number = f"CERT-{lot_num}-{cert_date.replace('-', '')}"
                accepted.append({
                    "lot_id": lot_id,
                    "crop_type": crop,
                    "variety": variety,
                    "certificate_number": cert_number,
                    "certification_date": cert_date,
                    "status": "certified",
                })
            else:
                rejected.append({
                    "lot_id": lot_id,
                    "crop_type": crop,
                    "variety": variety,
                    "rejection_reasons": "; ".join(sorted(reasons)),
                    "status": "rejected",
                })

        conn.close()
        return accepted, rejected, pending_lots

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
        accepted, rejected, pending_lots = self._compute_ground_truth()
        total_pending = len(pending_lots)
        expected_accepted_ids = sorted([a["lot_id"] for a in accepted])
        expected_rejected_ids = sorted([r["lot_id"] for r in rejected])

        criteria = {}
        max_score = 0
        total_score = 0

        # Criterion 1: compliance_certificates.csv exists and has correct accepted lots (25 pts)
        c1_max = 25
        max_score += c1_max
        cert_path = os.path.join(self.workspace, "compliance_certificates.csv")
        if os.path.exists(cert_path):
            with open(cert_path) as f:
                reader = csv.DictReader(f)
                cert_rows = list(reader)
            cert_lot_ids = sorted([r.get("lot_id", "") for r in cert_rows])
            if cert_lot_ids == expected_accepted_ids:
                c1_score = c1_max
                c1_passed = True
                c1_reason = ""
            else:
                missing = set(expected_accepted_ids) - set(cert_lot_ids)
                extra = set(cert_lot_ids) - set(expected_accepted_ids)
                c1_score = max(0, c1_max - len(missing) * 3 - len(extra) * 3)
                c1_passed = False
                c1_reason = f"Missing: {sorted(missing)}, Extra: {sorted(extra)}"
        else:
            c1_score = 0
            c1_passed = False
            c1_reason = "compliance_certificates.csv not found"
        criteria["accepted_lots_correct"] = {
            "passed": c1_passed,
            "score": c1_score,
            "max_score": c1_max,
            "reason": c1_reason if not c1_passed else "",
        }
        total_score += c1_score

        # Criterion 2: Certificate numbers are correctly formatted (15 pts)
        c2_max = 15
        max_score += c2_max
        if os.path.exists(cert_path) and cert_rows:
            expected_certs = {a["lot_id"]: a["certificate_number"] for a in accepted}
            correct_certs = 0
            total_certs = len(cert_rows)
            for row in cert_rows:
                lid = row.get("lot_id", "")
                cn = row.get("certificate_number", "")
                if lid in expected_certs and expected_certs[lid] == cn:
                    correct_certs += 1
            if total_certs > 0 and correct_certs == total_certs and total_certs == len(expected_accepted_ids):
                c2_score = c2_max
                c2_passed = True
                c2_reason = ""
            else:
                c2_score = int(c2_max * correct_certs / max(1, len(expected_accepted_ids)))
                c2_passed = False
                c2_reason = f"{correct_certs}/{len(expected_accepted_ids)} certificate numbers correct"
        else:
            c2_score = 0
            c2_passed = False
            c2_reason = "No certificates to check"
        criteria["certificate_numbers_correct"] = {
            "passed": c2_passed,
            "score": c2_score,
            "max_score": c2_max,
            "reason": c2_reason if not c2_passed else "",
        }
        total_score += c2_score

        # Criterion 3: rejection_report.csv exists and has correct rejected lots (20 pts)
        c3_max = 20
        max_score += c3_max
        rej_path = os.path.join(self.workspace, "rejection_report.csv")
        if os.path.exists(rej_path):
            with open(rej_path) as f:
                reader = csv.DictReader(f)
                rej_rows = list(reader)
            rej_lot_ids = sorted([r.get("lot_id", "") for r in rej_rows])
            if rej_lot_ids == expected_rejected_ids:
                c3_score = c3_max
                c3_passed = True
                c3_reason = ""
            else:
                missing = set(expected_rejected_ids) - set(rej_lot_ids)
                extra = set(rej_lot_ids) - set(expected_rejected_ids)
                c3_score = max(0, c3_max - len(missing) * 2 - len(extra) * 2)
                c3_passed = False
                c3_reason = f"Missing: {sorted(missing)}, Extra: {sorted(extra)}"
        else:
            c3_score = 0
            c3_passed = False
            c3_reason = "rejection_report.csv not found"
        criteria["rejected_lots_correct"] = {
            "passed": c3_passed,
            "score": c3_score,
            "max_score": c3_max,
            "reason": c3_reason if not c3_passed else "",
        }
        total_score += c3_score

        # Criterion 4: Rejection reasons are accurate (15 pts)
        c4_max = 15
        max_score += c4_max
        if os.path.exists(rej_path) and rej_rows:
            expected_reasons = {r["lot_id"]: set(r["rejection_reasons"].split("; ")) for r in rejected}
            correct_reasons = 0
            total_rej = len(expected_rejected_ids)
            for row in rej_rows:
                lid = row.get("lot_id", "")
                if lid in expected_reasons:
                    actual_reasons = set(r.strip() for r in row.get("rejection_reasons", "").split(";"))
                    # Check if the agent captured at least the key reasons
                    if actual_reasons == expected_reasons[lid]:
                        correct_reasons += 1
                    elif actual_reasons & expected_reasons[lid]:
                        correct_reasons += 0.5
            if total_rej > 0:
                ratio = correct_reasons / total_rej
                c4_score = int(c4_max * ratio)
                c4_passed = ratio == 1.0
                c4_reason = "" if c4_passed else f"{correct_reasons}/{total_rej} lots with exact rejection reasons"
            else:
                c4_score = c4_max
                c4_passed = True
                c4_reason = ""
        else:
            c4_score = 0 if expected_rejected_ids else c4_max
            c4_passed = not bool(expected_rejected_ids)
            c4_reason = "No rejection report to check" if expected_rejected_ids else ""
        criteria["rejection_reasons_accurate"] = {
            "passed": c4_passed,
            "score": c4_score,
            "max_score": c4_max,
            "reason": c4_reason if not c4_passed else "",
        }
        total_score += c4_score

        # Criterion 5: compliance_certificates.csv has required columns (10 pts)
        c5_max = 10
        max_score += c5_max
        required_cert_cols = {"lot_id", "crop_type", "variety", "certificate_number", "certification_date", "status"}
        if os.path.exists(cert_path) and cert_rows:
            actual_cols = set(cert_rows[0].keys())
            if required_cert_cols.issubset(actual_cols):
                c5_score = c5_max
                c5_passed = True
                c5_reason = ""
            else:
                missing_cols = required_cert_cols - actual_cols
                c5_score = max(0, c5_max - len(missing_cols) * 2)
                c5_passed = False
                c5_reason = f"Missing columns: {sorted(missing_cols)}"
        elif os.path.exists(cert_path):
            c5_score = 0
            c5_passed = False
            c5_reason = "Certificate file is empty"
        else:
            c5_score = 0
            c5_passed = False
            c5_reason = "compliance_certificates.csv not found"
        criteria["certificate_columns_correct"] = {
            "passed": c5_passed,
            "score": c5_score,
            "max_score": c5_max,
            "reason": c5_reason if not c5_passed else "",
        }
        total_score += c5_score

        # Criterion 6: Response contains summary counts (15 pts)
        c6_max = 15
        max_score += c6_max
        n_accepted = len(expected_accepted_ids)
        n_rejected = len(expected_rejected_ids)
        action_lower = action.lower() if action else ""
        has_accepted_count = str(n_accepted) in action
        has_rejected_count = str(n_rejected) in action
        has_total_count = str(total_pending) in action
        count_matches = sum([has_accepted_count, has_rejected_count, has_total_count])
        if count_matches == 3:
            c6_score = c6_max
            c6_passed = True
            c6_reason = ""
        else:
            c6_score = int(c6_max * count_matches / 3)
            c6_passed = False
            missing_items = []
            if not has_accepted_count:
                missing_items.append(f"accepted count ({n_accepted})")
            if not has_rejected_count:
                missing_items.append(f"rejected count ({n_rejected})")
            if not has_total_count:
                missing_items.append(f"total pending count ({total_pending})")
            c6_reason = f"Missing in response: {', '.join(missing_items)}"
        criteria["response_summary_counts"] = {
            "passed": c6_passed,
            "score": c6_score,
            "max_score": c6_max,
            "reason": c6_reason if not c6_passed else "",
        }
        total_score += c6_score

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": criteria,
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

        # Step 1: Load compliance thresholds from workspace
        thresh_path = os.path.join(self.workspace, "compliance_thresholds.yaml")
        with open(thresh_path) as f:
            thresholds = yaml.safe_load(f)["crop_thresholds"]

        # Step 2: Load traceability rules
        rules_path = os.path.join(self.workspace, "traceability_rules.md")
        with open(rules_path) as f:
            _rules = f.read()

        # Step 3: Load vigor scores from lab analysis JSON files
        vigor_map = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "lab_analysis_report_*.json"))):
            with open(fpath) as f:
                entries = json.load(f)
            for entry in entries:
                vigor_map[entry["lot_id"]] = entry["vigor_score"]

        # Step 4: Load field conditions from CSV files
        field_conditions = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "field_condition_report_*.csv"))):
            with open(fpath) as f:
                reader = csv_mod.DictReader(f)
                for row in reader:
                    field_conditions[row["field_id"]] = {
                        "temperature_c": float(row["temperature_c"]),
                        "rainfall_mm": float(row["rainfall_mm"]),
                    }

        # Step 5: Get all pending_review lots via tool calls
        all_pending = []
        page = 1
        while True:
            result = self.tools["list_seed_lots"](status="pending_review", page=page)
            all_pending.extend(result["lots"])
            if page >= result["total_pages"]:
                break
            page += 1

        total_pending = len(all_pending)
        tool_call_count = page  # list_seed_lots calls

        # Step 6: For each pending lot, gather all data and evaluate compliance
        accepted = []
        rejected = []

        for lot_summary in all_pending:
            lot_id = lot_summary["lot_id"]

            # Get lot details
            lot_details = self.tools["get_lot_details"](lot_id=lot_id)
            tool_call_count += 1

            crop = lot_details["crop_type"]
            variety = lot_details["variety"]
            parent_lot_id = lot_details["parent_lot_id"]
            field_id = lot_details["field_id"]
            harvest_date = lot_details["harvest_date"]
            crop_thresh = thresholds.get(crop, {})
            reasons = []

            # Get parent certificate
            parent_cert = self.tools["get_parent_certificate"](parent_lot_id=parent_lot_id)
            tool_call_count += 1

            if "error" not in parent_cert:
                if parent_cert["cert_status"] != "valid":
                    reasons.append(f"parent_cert_status_{parent_cert['cert_status']}")
                if parent_cert["expiry_date"] < harvest_date:
                    reasons.append("parent_cert_expired_before_harvest")
                if parent_cert["crop_type"] != crop:
                    reasons.append("parent_crop_mismatch")
                if parent_cert["variety"] != variety:
                    reasons.append("parent_variety_mismatch")
                valid_gens = crop_thresh.get("valid_parent_generations", [])
                if parent_cert["generation"] not in valid_gens:
                    reasons.append("invalid_parent_generation")
            else:
                reasons.append("no_parent_certificate")

            # Get germination results
            germ_result = self.tools["get_germination_results"](lot_id=lot_id)
            tool_call_count += 1

            if "error" not in germ_result:
                gt = germ_result["tests"][0]  # Most recent (sorted DESC)
                if gt["germination_rate"] < crop_thresh.get("min_germination_rate", 0):
                    reasons.append("low_germination_rate")
                if gt["purity_pct"] < crop_thresh.get("min_purity_pct", 0):
                    reasons.append("low_purity")
                if gt["moisture_pct"] > crop_thresh.get("max_moisture_pct", 100):
                    reasons.append("high_moisture")
                if gt["weed_seed_count"] > crop_thresh.get("max_weed_seed_count", 999):
                    reasons.append("excess_weed_seeds")
                if gt["other_crop_seed_count"] > crop_thresh.get("max_other_crop_seed_count", 999):
                    reasons.append("excess_other_crop_seeds")
                if gt["inert_matter_pct"] > crop_thresh.get("max_inert_matter_pct", 100):
                    reasons.append("excess_inert_matter")
            else:
                reasons.append("no_germination_test")

            # Vigor check from workspace
            vigor = vigor_map.get(lot_id)
            if vigor is not None:
                if vigor < crop_thresh.get("min_vigor_score", 0):
                    reasons.append("low_vigor_score")
            else:
                reasons.append("no_vigor_score")

            # Field condition check from workspace
            fc = field_conditions.get(field_id)
            if fc:
                if fc["temperature_c"] > crop_thresh.get("max_harvest_temperature_c", 999):
                    reasons.append("harvest_temperature_exceeded")
                if fc["rainfall_mm"] > crop_thresh.get("max_harvest_rainfall_mm", 999):
                    reasons.append("harvest_rainfall_exceeded")
            else:
                reasons.append("no_field_condition_data")

            # Get inspection records
            insp_result = self.tools["get_inspection_records"](lot_id=lot_id)
            tool_call_count += 1

            if "error" not in insp_result:
                insp = insp_result["records"][0]  # Most recent
                if insp["overall_result"] != "passed":
                    reasons.append(f"inspection_{insp['overall_result']}")
            else:
                reasons.append("no_inspection_record")

            # Get harvest log (for traceability verification)
            _harvest_log = self.tools["get_harvest_log"](field_id=field_id)
            tool_call_count += 1

            if len(reasons) == 0:
                lot_num = lot_id.split("-")[1]
                cert_number = f"CERT-{lot_num}-20251201"
                accepted.append({
                    "lot_id": lot_id,
                    "crop_type": crop,
                    "variety": variety,
                    "certificate_number": cert_number,
                    "certification_date": "2025-12-01",
                    "status": "certified",
                })
            else:
                rejected.append({
                    "lot_id": lot_id,
                    "crop_type": crop,
                    "variety": variety,
                    "rejection_reasons": "; ".join(sorted(reasons)),
                    "status": "rejected",
                })

        # Step 7: Write compliance_certificates.csv
        cert_path = os.path.join(self.workspace, "compliance_certificates.csv")
        with open(cert_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(
                f,
                fieldnames=["lot_id", "crop_type", "variety", "certificate_number",
                             "certification_date", "status"],
            )
            writer.writeheader()
            for row in sorted(accepted, key=lambda x: x["lot_id"]):
                writer.writerow(row)

        # Step 8: Write rejection_report.csv
        rej_path = os.path.join(self.workspace, "rejection_report.csv")
        with open(rej_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(
                f,
                fieldnames=["lot_id", "crop_type", "variety", "rejection_reasons", "status"],
            )
            writer.writeheader()
            for row in sorted(rejected, key=lambda x: x["lot_id"]):
                writer.writerow(row)

        # Step 9: Construct action string with summary
        n_accepted = len(accepted)
        n_rejected = len(rejected)
        action = (
            f"Compliance review complete. "
            f"Out of {total_pending} seed lots pending review, "
            f"{n_accepted} lots have been certified and {n_rejected} lots have been rejected. "
            f"Compliance certificates have been saved to compliance_certificates.csv "
            f"and rejection details have been saved to rejection_report.csv."
        )

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need at least 15"

        return self.step(action)
