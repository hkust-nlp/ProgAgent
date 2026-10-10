import sqlite3
import json
import os
import csv
from typing import Tuple, Dict, List, Any
from datetime import datetime, timedelta

import yaml


# ---------------------------------------------------------------------------
# Tool decorator  (keep unchanged)
# ---------------------------------------------------------------------------
def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ---------------------------------------------------------------------------
# Canonical failure-reason phrases (used by verify and step)
# ---------------------------------------------------------------------------
FAILURE_PESTICIDE = "banned pesticide in lookback period"
FAILURE_SOIL = "soil quality threshold exceeded"
FAILURE_LAB = "testing lab not accredited"
FAILURE_AUDIT = "audit certificate invalid or expired"
FAILURE_TEMP = "storage temperature exceeded limit"
FAILURE_WEIGHT = "weight discrepancy beyond tolerance"
FAILURE_DEFECT = "defect rate exceeded limit"


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

    # ==================================================================
    # TOOLS
    # ==================================================================

    @tool(
        description="Look up processor lot details by lot code. Returns lot_id, lot_code, processor_name, farm_id, harvest_date, weight_kg, grade, processing_date, and storage_facility.",
        parameters={
            "type": "object",
            "properties": {
                "lot_code": {
                    "type": "string",
                    "description": "The processor lot code to look up (e.g. 'LOT-ABC123').",
                },
            },
            "required": ["lot_code"],
        },
    )
    def lookup_lot(self, lot_code: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM processor_lots WHERE lot_code = ?", (lot_code,)
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Lot code '{lot_code}' not found"}

    @tool(
        description="Retrieve detailed information about a specific farm by its farm_id. Returns farm_id, farm_name, region, acreage, organic_registered_date, and contact_email.",
        parameters={
            "type": "object",
            "properties": {
                "farm_id": {
                    "type": "string",
                    "description": "The farm identifier (e.g. 'FARM-0001').",
                },
            },
            "required": ["farm_id"],
        },
    )
    def query_farm(self, farm_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM farms WHERE farm_id = ?", (farm_id,)
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Farm '{farm_id}' not found"}

    @tool(
        description="Retrieve pesticide application records for a specific farm in a given calendar year. Returns a list of records each containing app_id, farm_id, application_date, chemical_name, chemical_category, dosage_kg_per_hectare, field_section, and applicator_name.",
        parameters={
            "type": "object",
            "properties": {
                "farm_id": {
                    "type": "string",
                    "description": "The farm identifier.",
                },
                "year": {
                    "type": "integer",
                    "description": "The calendar year to query (e.g. 2025).",
                },
            },
            "required": ["farm_id", "year"],
        },
    )
    def get_pesticide_applications(self, farm_id: str, year: int) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM pesticide_applications "
            "WHERE farm_id = ? AND application_date >= ? AND application_date < ? "
            "ORDER BY application_date",
            (farm_id, f"{year}-01-01", f"{year + 1}-01-01"),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @tool(
        description="Retrieve all soil test results for a specific farm, ordered by sample date descending (most recent first). Each record contains test_id, farm_id, sample_date, ph_level, organic_matter_pct, lead_ppm, cadmium_ppm, nitrogen_ppm, lab_name, and lab_certificate_number.",
        parameters={
            "type": "object",
            "properties": {
                "farm_id": {
                    "type": "string",
                    "description": "The farm identifier.",
                },
            },
            "required": ["farm_id"],
        },
    )
    def get_soil_tests(self, farm_id: str) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM soil_tests WHERE farm_id = ? "
            "ORDER BY sample_date DESC, test_id DESC",
            (farm_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @tool(
        description="Retrieve all audit certificates for a specific farm, ordered by audit date descending (most recent first). Each record contains cert_id, farm_id, auditor_org, audit_date, expiry_date, status, certificate_number, and scope.",
        parameters={
            "type": "object",
            "properties": {
                "farm_id": {
                    "type": "string",
                    "description": "The farm identifier.",
                },
            },
            "required": ["farm_id"],
        },
    )
    def get_audit_certificates(self, farm_id: str) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_certificates WHERE farm_id = ? "
            "ORDER BY audit_date DESC, cert_id DESC",
            (farm_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ==================================================================
    # HELPERS  (internal, not exposed as tools)
    # ==================================================================

    def _parse_inspection_file(self, filepath: str) -> dict:
        """Parse an inspection report file (JSON or TXT) and return a dict."""
        if filepath.endswith(".json"):
            with open(filepath) as f:
                return json.load(f)
        elif filepath.endswith(".txt"):
            data: Dict[str, Any] = {}
            with open(filepath) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("Lot Code:"):
                        data["lot_code"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Measured Weight (kg):"):
                        data["measured_weight_kg"] = float(
                            line.split(":", 1)[1].strip()
                        )
                    elif line.startswith("Temperature (C):"):
                        data["temperature_c"] = float(
                            line.split(":", 1)[1].strip()
                        )
                    elif line.startswith("Defect Rate (%):"):
                        data["defect_rate_pct"] = float(
                            line.split(":", 1)[1].strip()
                        )
                    elif line.startswith("Inspection Date:"):
                        data["inspection_date"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Inspector:"):
                        data["inspector_name"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Visual Quality:"):
                        data["visual_quality"] = line.split(":", 1)[1].strip()
            return data
        return {}

    def _find_inspection_file(self, lot_code: str) -> str | None:
        """Locate the inspection report file for a lot code."""
        for ext in (".json", ".txt"):
            fpath = os.path.join(self.workspace, f"inspection_{lot_code}{ext}")
            if os.path.exists(fpath):
                return fpath
        return None

    def _compute_ground_truth(self) -> Tuple[list, dict]:
        """Compute the expected compliance results directly from DB + workspace."""

        # -- workspace files ------------------------------------------------
        with open(os.path.join(self.workspace, "batch_manifest.json")) as f:
            manifest = json.load(f)

        with open(os.path.join(self.workspace, "organic_standards.yaml")) as f:
            standards = yaml.safe_load(f)

        approved_labs: set = set()
        with open(os.path.join(self.workspace, "approved_labs.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                approved_labs.add(row["lab_name"])

        delivery_date = datetime.strptime(manifest["delivery_date"], "%Y-%m-%d")
        lookback_months = standards["pesticide_compliance"]["lookback_months"]
        lookback_date = delivery_date - timedelta(days=lookback_months * 30)
        lookback_str = lookback_date.strftime("%Y-%m-%d")
        banned_substances = set(
            standards["pesticide_compliance"]["banned_substances"]
        )
        banned_categories = set(
            standards["pesticide_compliance"]["banned_categories"]
        )
        soil_thresh = standards["soil_quality_thresholds"]
        insp_thresh = standards["lot_inspection_thresholds"]
        valid_statuses = set(standards["audit_requirements"]["valid_statuses"])

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        results = []
        for lot_code in manifest["lot_codes"]:
            lot = dict(
                conn.execute(
                    "SELECT * FROM processor_lots WHERE lot_code = ?",
                    (lot_code,),
                ).fetchone()
            )
            farm_id = lot["farm_id"]
            farm = dict(
                conn.execute(
                    "SELECT * FROM farms WHERE farm_id = ?", (farm_id,)
                ).fetchone()
            )

            # -- pesticide --------------------------------------------------
            pest_rows = conn.execute(
                "SELECT * FROM pesticide_applications "
                "WHERE farm_id = ? AND application_date >= ?",
                (farm_id, lookback_str),
            ).fetchall()
            pesticide_ok = True
            for p in pest_rows:
                if (
                    p["chemical_name"] in banned_substances
                    or p["chemical_category"] in banned_categories
                ):
                    pesticide_ok = False
                    break

            # -- soil -------------------------------------------------------
            soil_row = conn.execute(
                "SELECT * FROM soil_tests WHERE farm_id = ? "
                "ORDER BY sample_date DESC, test_id DESC LIMIT 1",
                (farm_id,),
            ).fetchone()
            soil_ok = True
            lab_ok = True
            if soil_row:
                if (
                    soil_row["ph_level"] < soil_thresh["ph_min"]
                    or soil_row["ph_level"] > soil_thresh["ph_max"]
                    or soil_row["lead_ppm"] > soil_thresh["lead_max_ppm"]
                    or soil_row["cadmium_ppm"] > soil_thresh["cadmium_max_ppm"]
                    or soil_row["organic_matter_pct"]
                    < soil_thresh["organic_matter_min_pct"]
                ):
                    soil_ok = False
                if soil_row["lab_name"] not in approved_labs:
                    lab_ok = False
            else:
                soil_ok = False
                lab_ok = False

            # -- audit ------------------------------------------------------
            cert_row = conn.execute(
                "SELECT * FROM audit_certificates WHERE farm_id = ? "
                "ORDER BY audit_date DESC, cert_id DESC LIMIT 1",
                (farm_id,),
            ).fetchone()
            audit_ok = True
            if cert_row:
                if cert_row["status"] not in valid_statuses:
                    audit_ok = False
                cert_expiry = datetime.strptime(
                    cert_row["expiry_date"], "%Y-%m-%d"
                )
                if cert_expiry < delivery_date:
                    audit_ok = False
            else:
                audit_ok = False

            # -- inspection -------------------------------------------------
            inspection_ok = True
            failures_insp: list = []
            insp_path = self._find_inspection_file(lot_code)
            if insp_path:
                insp = self._parse_inspection_file(insp_path)
                if insp.get("temperature_c", 0) > insp_thresh["max_temperature_c"]:
                    inspection_ok = False
                    failures_insp.append(FAILURE_TEMP)
                weight_diff = (
                    abs(insp.get("measured_weight_kg", 0) - lot["weight_kg"])
                    / lot["weight_kg"]
                    * 100
                )
                if weight_diff > insp_thresh["weight_tolerance_pct"]:
                    inspection_ok = False
                    failures_insp.append(FAILURE_WEIGHT)
                if insp.get("defect_rate_pct", 0) > insp_thresh["max_defect_rate_pct"]:
                    inspection_ok = False
                    failures_insp.append(FAILURE_DEFECT)
            else:
                inspection_ok = False
                failures_insp.append("inspection report missing")

            # -- compile ----------------------------------------------------
            failures: list = []
            if not pesticide_ok:
                failures.append(FAILURE_PESTICIDE)
            if not soil_ok:
                failures.append(FAILURE_SOIL)
            if not lab_ok:
                failures.append(FAILURE_LAB)
            if not audit_ok:
                failures.append(FAILURE_AUDIT)
            if not inspection_ok:
                failures.extend(failures_insp)

            overall = "COMPLIANT" if not failures else "NON_COMPLIANT"

            results.append(
                {
                    "lot_code": lot_code,
                    "farm_id": farm_id,
                    "farm_name": farm["farm_name"],
                    "pesticide_status": "PASS" if pesticide_ok else "FAIL",
                    "soil_status": "PASS" if soil_ok else "FAIL",
                    "lab_accredited": "PASS" if lab_ok else "FAIL",
                    "audit_status": "PASS" if audit_ok else "FAIL",
                    "inspection_status": "PASS" if inspection_ok else "FAIL",
                    "overall_status": overall,
                    "failure_reasons": "; ".join(failures) if failures else "None",
                }
            )

        conn.close()

        results.sort(key=lambda x: x["lot_code"])

        compliant = sum(
            1 for r in results if r["overall_status"] == "COMPLIANT"
        )
        non_compliant = len(results) - compliant
        batch_status = "APPROVED" if non_compliant == 0 else "REJECTED"
        nc_codes = [
            r["lot_code"]
            for r in results
            if r["overall_status"] == "NON_COMPLIANT"
        ]

        summary = {
            "batch_id": manifest["batch_id"],
            "delivery_date": manifest["delivery_date"],
            "total_lots": len(results),
            "compliant_lots": compliant,
            "non_compliant_lots": non_compliant,
            "batch_status": batch_status,
            "non_compliant_lot_codes": sorted(nc_codes),
        }

        return results, summary

    # ==================================================================
    # STEP  – evaluate task completion
    # ==================================================================

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
        ground_rows, ground_summary = self._compute_ground_truth()
        eval_criteria: Dict[str, Any] = {}

        # ---------------------------------------------------------------
        # 1. compliance_report.csv  – existence & columns  (10 pts)
        # ---------------------------------------------------------------
        expected_cols = [
            "lot_code", "farm_id", "farm_name", "pesticide_status",
            "soil_status", "lab_accredited", "audit_status",
            "inspection_status", "overall_status", "failure_reasons",
        ]
        report_path = os.path.join(self.workspace, "compliance_report.csv")
        agent_rows: list = []
        cols_ok = False
        if os.path.exists(report_path):
            with open(report_path, newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and list(reader.fieldnames) == expected_cols:
                    cols_ok = True
                for row in reader:
                    agent_rows.append(row)

        if cols_ok:
            eval_criteria["report_format"] = {
                "passed": True, "score": 10, "max_score": 10,
            }
        else:
            reason = "compliance_report.csv not found or columns mismatch"
            eval_criteria["report_format"] = {
                "passed": False, "score": 0, "max_score": 10, "reason": reason,
            }

        # ---------------------------------------------------------------
        # 2. Correct row count  (10 pts)
        # ---------------------------------------------------------------
        expected_count = len(ground_rows)
        actual_count = len(agent_rows)
        if actual_count == expected_count:
            eval_criteria["row_count"] = {
                "passed": True, "score": 10, "max_score": 10,
            }
        else:
            eval_criteria["row_count"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": f"Expected {expected_count} rows, got {actual_count}",
            }

        # Build agent lookup by lot_code
        agent_lookup = {r.get("lot_code"): r for r in agent_rows}

        # ---------------------------------------------------------------
        # 3. overall_status accuracy  (20 pts, proportional)
        # ---------------------------------------------------------------
        correct_overall = 0
        for gr in ground_rows:
            ar = agent_lookup.get(gr["lot_code"])
            if ar and ar.get("overall_status") == gr["overall_status"]:
                correct_overall += 1
        n = max(len(ground_rows), 1)
        os_score = round(20 * correct_overall / n, 2)
        eval_criteria["overall_status_accuracy"] = {
            "passed": correct_overall == len(ground_rows),
            "score": os_score,
            "max_score": 20,
        }
        if correct_overall < len(ground_rows):
            eval_criteria["overall_status_accuracy"]["reason"] = (
                f"{correct_overall}/{len(ground_rows)} lots correct"
            )

        # ---------------------------------------------------------------
        # 4. Individual check columns accuracy  (20 pts, proportional)
        # ---------------------------------------------------------------
        status_cols = [
            "pesticide_status", "soil_status", "lab_accredited",
            "audit_status", "inspection_status",
        ]
        total_checks = len(ground_rows) * len(status_cols)
        correct_checks = 0
        for gr in ground_rows:
            ar = agent_lookup.get(gr["lot_code"])
            if ar:
                for col in status_cols:
                    if ar.get(col) == gr[col]:
                        correct_checks += 1
        ic_score = round(20 * correct_checks / max(total_checks, 1), 2)
        eval_criteria["individual_checks_accuracy"] = {
            "passed": correct_checks == total_checks,
            "score": ic_score,
            "max_score": 20,
        }
        if correct_checks < total_checks:
            eval_criteria["individual_checks_accuracy"]["reason"] = (
                f"{correct_checks}/{total_checks} individual checks correct"
            )

        # ---------------------------------------------------------------
        # 5. failure_reasons accuracy  (15 pts, proportional)
        # ---------------------------------------------------------------
        correct_reasons = 0
        for gr in ground_rows:
            ar = agent_lookup.get(gr["lot_code"])
            if ar:
                gt_set = (
                    set(r.strip() for r in gr["failure_reasons"].split(";"))
                    if gr["failure_reasons"] != "None"
                    else set()
                )
                ag_val = ar.get("failure_reasons", "")
                ag_set = (
                    set(r.strip() for r in ag_val.split(";"))
                    if ag_val and ag_val != "None"
                    else set()
                )
                if gt_set == ag_set:
                    correct_reasons += 1
        fr_score = round(15 * correct_reasons / n, 2)
        eval_criteria["failure_reasons_accuracy"] = {
            "passed": correct_reasons == len(ground_rows),
            "score": fr_score,
            "max_score": 15,
        }
        if correct_reasons < len(ground_rows):
            eval_criteria["failure_reasons_accuracy"]["reason"] = (
                f"{correct_reasons}/{len(ground_rows)} lots with correct reasons"
            )

        # ---------------------------------------------------------------
        # 6. compliance_summary.json  (15 pts, proportional sub-checks)
        # ---------------------------------------------------------------
        summary_path = os.path.join(self.workspace, "compliance_summary.json")
        if os.path.exists(summary_path):
            with open(summary_path) as f:
                agent_summary = json.load(f)
            sub_ok = 0
            sub_total = 5
            if agent_summary.get("batch_status") == ground_summary["batch_status"]:
                sub_ok += 1
            if agent_summary.get("total_lots") == ground_summary["total_lots"]:
                sub_ok += 1
            if agent_summary.get("compliant_lots") == ground_summary["compliant_lots"]:
                sub_ok += 1
            if agent_summary.get("non_compliant_lots") == ground_summary["non_compliant_lots"]:
                sub_ok += 1
            if sorted(agent_summary.get("non_compliant_lot_codes", [])) == sorted(
                ground_summary["non_compliant_lot_codes"]
            ):
                sub_ok += 1
            sm_score = round(15 * sub_ok / sub_total, 2)
            eval_criteria["summary_file"] = {
                "passed": sub_ok == sub_total,
                "score": sm_score,
                "max_score": 15,
            }
            if sub_ok < sub_total:
                eval_criteria["summary_file"]["reason"] = (
                    f"{sub_ok}/{sub_total} summary fields correct"
                )
        else:
            eval_criteria["summary_file"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "compliance_summary.json not found",
            }

        # ---------------------------------------------------------------
        # 7. Response contains correct batch status  (10 pts)
        # ---------------------------------------------------------------
        expected_status = ground_summary["batch_status"]
        if expected_status in action:
            eval_criteria["response_batch_status"] = {
                "passed": True, "score": 10, "max_score": 10,
            }
        else:
            eval_criteria["response_batch_status"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": f"Expected '{expected_status}' in response text",
            }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ==================================================================
    # VERIFY  – self-test using only tools + workspace files
    # ==================================================================

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
        tool_call_count = 0

        # -- Read workspace reference files ---------------------------------
        with open(os.path.join(self.workspace, "batch_manifest.json")) as f:
            manifest = json.load(f)

        with open(os.path.join(self.workspace, "organic_standards.yaml")) as f:
            standards = yaml.safe_load(f)

        approved_labs: set = set()
        with open(os.path.join(self.workspace, "approved_labs.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                approved_labs.add(row["lab_name"])

        delivery_date = datetime.strptime(manifest["delivery_date"], "%Y-%m-%d")
        lookback_months = standards["pesticide_compliance"]["lookback_months"]
        lookback_date = delivery_date - timedelta(days=lookback_months * 30)
        lookback_str = lookback_date.strftime("%Y-%m-%d")
        banned_substances = set(
            standards["pesticide_compliance"]["banned_substances"]
        )
        banned_categories = set(
            standards["pesticide_compliance"]["banned_categories"]
        )
        soil_thresh = standards["soil_quality_thresholds"]
        insp_thresh = standards["lot_inspection_thresholds"]
        valid_statuses = set(standards["audit_requirements"]["valid_statuses"])

        years_to_check = list(range(lookback_date.year, delivery_date.year + 1))

        # -- Lookup every lot in the batch ----------------------------------
        lot_data: Dict[str, dict] = {}
        for lot_code in manifest["lot_codes"]:
            result = self.tools["lookup_lot"](lot_code=lot_code)
            tool_call_count += 1
            lot_data[lot_code] = result

        # -- Unique farms ---------------------------------------------------
        farm_ids = set(
            v["farm_id"] for v in lot_data.values() if "farm_id" in v
        )

        farm_info: Dict[str, dict] = {}
        for fid in farm_ids:
            result = self.tools["query_farm"](farm_id=fid)
            tool_call_count += 1
            farm_info[fid] = result

        # -- Pesticide applications per farm --------------------------------
        farm_pest: Dict[str, list] = {}
        for fid in farm_ids:
            records: list = []
            for yr in years_to_check:
                result = self.tools["get_pesticide_applications"](
                    farm_id=fid, year=yr
                )
                tool_call_count += 1
                if isinstance(result, list):
                    records.extend(result)
            farm_pest[fid] = records

        # -- Soil tests per farm --------------------------------------------
        farm_soil: Dict[str, list] = {}
        for fid in farm_ids:
            result = self.tools["get_soil_tests"](farm_id=fid)
            tool_call_count += 1
            farm_soil[fid] = result if isinstance(result, list) else []

        # -- Audit certificates per farm ------------------------------------
        farm_audit: Dict[str, list] = {}
        for fid in farm_ids:
            result = self.tools["get_audit_certificates"](farm_id=fid)
            tool_call_count += 1
            farm_audit[fid] = result if isinstance(result, list) else []

        # -- Evaluate each lot ----------------------------------------------
        results: list = []
        for lot_code in manifest["lot_codes"]:
            lot = lot_data[lot_code]
            farm_id = lot["farm_id"]
            farm = farm_info.get(farm_id, {})

            # Pesticide check
            pesticide_ok = True
            for p in farm_pest.get(farm_id, []):
                if p["application_date"] >= lookback_str:
                    if (
                        p["chemical_name"] in banned_substances
                        or p["chemical_category"] in banned_categories
                    ):
                        pesticide_ok = False
                        break

            # Soil check
            soil_ok = True
            lab_ok = True
            soil_records = farm_soil.get(farm_id, [])
            if soil_records:
                latest = soil_records[0]  # sorted desc by tool
                if (
                    latest["ph_level"] < soil_thresh["ph_min"]
                    or latest["ph_level"] > soil_thresh["ph_max"]
                    or latest["lead_ppm"] > soil_thresh["lead_max_ppm"]
                    or latest["cadmium_ppm"] > soil_thresh["cadmium_max_ppm"]
                    or latest["organic_matter_pct"]
                    < soil_thresh["organic_matter_min_pct"]
                ):
                    soil_ok = False
                if latest["lab_name"] not in approved_labs:
                    lab_ok = False
            else:
                soil_ok = False
                lab_ok = False

            # Audit check
            audit_ok = True
            audit_records = farm_audit.get(farm_id, [])
            if audit_records:
                latest_cert = audit_records[0]
                if latest_cert["status"] not in valid_statuses:
                    audit_ok = False
                cert_expiry = datetime.strptime(
                    latest_cert["expiry_date"], "%Y-%m-%d"
                )
                if cert_expiry < delivery_date:
                    audit_ok = False
            else:
                audit_ok = False

            # Inspection check
            inspection_ok = True
            failures_insp: list = []
            insp_path = self._find_inspection_file(lot_code)
            if insp_path:
                insp = self._parse_inspection_file(insp_path)
                if insp.get("temperature_c", 0) > insp_thresh["max_temperature_c"]:
                    inspection_ok = False
                    failures_insp.append(FAILURE_TEMP)
                weight_diff = (
                    abs(insp.get("measured_weight_kg", 0) - lot["weight_kg"])
                    / lot["weight_kg"]
                    * 100
                )
                if weight_diff > insp_thresh["weight_tolerance_pct"]:
                    inspection_ok = False
                    failures_insp.append(FAILURE_WEIGHT)
                if insp.get("defect_rate_pct", 0) > insp_thresh["max_defect_rate_pct"]:
                    inspection_ok = False
                    failures_insp.append(FAILURE_DEFECT)
            else:
                inspection_ok = False
                failures_insp.append("inspection report missing")

            # Compile
            failures: list = []
            if not pesticide_ok:
                failures.append(FAILURE_PESTICIDE)
            if not soil_ok:
                failures.append(FAILURE_SOIL)
            if not lab_ok:
                failures.append(FAILURE_LAB)
            if not audit_ok:
                failures.append(FAILURE_AUDIT)
            if not inspection_ok:
                failures.extend(failures_insp)

            overall = "COMPLIANT" if not failures else "NON_COMPLIANT"

            results.append(
                {
                    "lot_code": lot_code,
                    "farm_id": farm_id,
                    "farm_name": farm.get("farm_name", ""),
                    "pesticide_status": "PASS" if pesticide_ok else "FAIL",
                    "soil_status": "PASS" if soil_ok else "FAIL",
                    "lab_accredited": "PASS" if lab_ok else "FAIL",
                    "audit_status": "PASS" if audit_ok else "FAIL",
                    "inspection_status": "PASS" if inspection_ok else "FAIL",
                    "overall_status": overall,
                    "failure_reasons": "; ".join(failures) if failures else "None",
                }
            )

        results.sort(key=lambda x: x["lot_code"])

        # -- Write compliance_report.csv ------------------------------------
        report_path = os.path.join(self.workspace, "compliance_report.csv")
        fieldnames = [
            "lot_code", "farm_id", "farm_name", "pesticide_status",
            "soil_status", "lab_accredited", "audit_status",
            "inspection_status", "overall_status", "failure_reasons",
        ]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        # -- Write compliance_summary.json ----------------------------------
        compliant = sum(
            1 for r in results if r["overall_status"] == "COMPLIANT"
        )
        non_compliant = len(results) - compliant
        batch_status = "APPROVED" if non_compliant == 0 else "REJECTED"
        nc_codes = sorted(
            r["lot_code"]
            for r in results
            if r["overall_status"] == "NON_COMPLIANT"
        )

        summary = {
            "batch_id": manifest["batch_id"],
            "delivery_date": manifest["delivery_date"],
            "total_lots": len(results),
            "compliant_lots": compliant,
            "non_compliant_lots": non_compliant,
            "batch_status": batch_status,
            "non_compliant_lot_codes": nc_codes,
        }
        summary_path = os.path.join(self.workspace, "compliance_summary.json")
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        # -- Construct action -----------------------------------------------
        action_lines = [
            f"Batch {manifest['batch_id']} Compliance Verification Result: {batch_status}",
            f"Total lots evaluated: {len(results)}",
            f"Compliant: {compliant}, Non-compliant: {non_compliant}",
        ]
        if nc_codes:
            action_lines.append("Non-compliant lots:")
            for r in results:
                if r["overall_status"] == "NON_COMPLIANT":
                    action_lines.append(
                        f"  {r['lot_code']} ({r['farm_name']}): {r['failure_reasons']}"
                    )
        action = "\n".join(action_lines)

        assert tool_call_count >= 15, (
            f"Only {tool_call_count} tool calls; need >= 15"
        )

        return self.step(action)
