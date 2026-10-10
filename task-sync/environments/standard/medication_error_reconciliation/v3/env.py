"""Medication dispensing error reconciliation environment."""

from typing import Tuple, Dict, List, Any
import sqlite3
import json
import csv
import os
import yaml


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


PAGE_SIZE = 20


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

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description=(
            "Retrieves electronic medication administration records (eMAR) "
            "for a given date with pagination. Returns up to 20 records per "
            "page along with pagination metadata."
        ),
        parameters={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
            },
            "required": ["date", "page"],
        },
    )
    def get_emar_records(self, date: str, page: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT emar_id, patient_id, medication_id, nurse_id, "
            "scheduled_time, administered_time, dose_mg, status "
            "FROM emar_records WHERE scheduled_time LIKE ? "
            "ORDER BY emar_id",
            (f"{date}%",),
        )
        all_rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        total = len(all_rows)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        start = (page - 1) * PAGE_SIZE
        end = start + PAGE_SIZE
        page_rows = all_rows[start:end]
        return {
            "records": page_rows,
            "page": page,
            "total_pages": total_pages,
            "total_records": total,
            "has_more": page < total_pages,
        }

    @tool(
        description=(
            "Retrieves pharmacy dispensation records for a given date with "
            "pagination. Returns up to 20 records per page."
        ),
        parameters={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
            },
            "required": ["date", "page"],
        },
    )
    def get_dispensation_records(self, date: str, page: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT dispensation_id, patient_id, medication_id, "
            "dispensed_dose_mg, dispensed_time, pharmacist_id "
            "FROM pharmacy_dispensations WHERE dispensed_time LIKE ? "
            "ORDER BY dispensation_id",
            (f"{date}%",),
        )
        all_rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        total = len(all_rows)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        start = (page - 1) * PAGE_SIZE
        end = start + PAGE_SIZE
        page_rows = all_rows[start:end]
        return {
            "records": page_rows,
            "page": page,
            "total_pages": total_pages,
            "total_records": total,
            "has_more": page < total_pages,
        }

    @tool(
        description=(
            "Retrieves all documented allergies for a specific patient."
        ),
        parameters={
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "Patient identifier (e.g. P0001)",
                },
            },
            "required": ["patient_id"],
        },
    )
    def get_patient_allergies(self, patient_id: str) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT allergen_class, severity, reaction_type "
            "FROM patient_allergies WHERE patient_id = ?",
            (patient_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @tool(
        description=(
            "Retrieves demographic information for a specific patient, "
            "including name, date of birth, ward, and bed number."
        ),
        parameters={
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "Patient identifier (e.g. P0001)",
                },
            },
            "required": ["patient_id"],
        },
    )
    def get_patient_info(self, patient_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT patient_id, name, dob, ward, bed_number "
            "FROM patients WHERE patient_id = ?",
            (patient_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Patient {patient_id} not found"}

    @tool(
        description=(
            "Retrieves medication details including generic name, brand name, "
            "standard dose, and route of administration. Does NOT include "
            "drug class information."
        ),
        parameters={
            "type": "object",
            "properties": {
                "medication_id": {
                    "type": "string",
                    "description": "Medication identifier (e.g. M0001)",
                },
            },
            "required": ["medication_id"],
        },
    )
    def get_medication_info(self, medication_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT medication_id, generic_name, brand_name, "
            "standard_dose_mg, route "
            "FROM medications WHERE medication_id = ?",
            (medication_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Medication {medication_id} not found"}

    @tool(
        description=(
            "Retrieves all shift assignments for a specific nurse on a "
            "given date, including ward assignment and shift times."
        ),
        parameters={
            "type": "object",
            "properties": {
                "nurse_id": {
                    "type": "string",
                    "description": "Nurse identifier (e.g. N0001)",
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format",
                },
            },
            "required": ["nurse_id", "date"],
        },
    )
    def get_nurse_shift(self, nurse_id: str, date: str) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT shift_id, nurse_id, shift_date, start_time, end_time, "
            "assigned_ward FROM nurse_shifts "
            "WHERE nurse_id = ? AND shift_date = ?",
            (nurse_id, date),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    # ------------------------------------------------------------------
    # Helper: compute ground-truth errors from DB + workspace
    # ------------------------------------------------------------------

    def _compute_ground_truth(self):
        """Return ground-truth error sets and supporting data."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Read reconciliation date from policy file
        policy_path = os.path.join(self.workspace, "reconciliation_policy.txt")
        recon_date = None
        with open(policy_path) as f:
            for line in f:
                if "Reconciliation Date:" in line:
                    recon_date = line.split(":", 1)[1].strip()
                    break
        assert recon_date is not None, "Cannot find reconciliation date"

        # Load workspace configs
        with open(os.path.join(self.workspace, "formulary.json")) as f:
            formulary = json.load(f)
        with open(os.path.join(self.workspace, "dosage_tolerance.yaml")) as f:
            tol_config = yaml.safe_load(f)
        default_tol = tol_config["default_tolerance_percent"]
        class_tols = tol_config["drug_class_tolerances"]

        # Load prescribed orders from workspace batch CSVs
        prescribed = {}  # (patient_id, medication_id) -> prescribed_dose_mg
        for fn in sorted(os.listdir(self.workspace)):
            if fn.startswith("medication_orders_batch_") and fn.endswith(".csv"):
                with open(os.path.join(self.workspace, fn)) as f:
                    for row in csv.DictReader(f):
                        prescribed[(row["patient_id"], row["medication_id"])] = float(
                            row["prescribed_dose_mg"]
                        )

        # DB: eMAR
        cur.execute(
            "SELECT * FROM emar_records WHERE scheduled_time LIKE ?",
            (f"{recon_date}%",),
        )
        emar_rows = [dict(r) for r in cur.fetchall()]

        # DB: dispensations
        cur.execute(
            "SELECT * FROM pharmacy_dispensations WHERE dispensed_time LIKE ?",
            (f"{recon_date}%",),
        )
        disp_map = {}
        for r in cur.fetchall():
            r = dict(r)
            disp_map[(r["patient_id"], r["medication_id"])] = r

        # DB: patients
        cur.execute("SELECT * FROM patients")
        patients = {r["patient_id"]: dict(r) for r in cur.fetchall()}

        # DB: allergies
        cur.execute("SELECT * FROM patient_allergies")
        allergies_by_patient: Dict[str, list] = {}
        for r in cur.fetchall():
            r = dict(r)
            allergies_by_patient.setdefault(r["patient_id"], []).append(r)

        # DB: nurse shifts on recon date
        cur.execute(
            "SELECT * FROM nurse_shifts WHERE shift_date = ?", (recon_date,)
        )
        shifts_by_nurse: Dict[str, list] = {}
        for r in cur.fetchall():
            r = dict(r)
            shifts_by_nurse.setdefault(r["nurse_id"], []).append(r)

        conn.close()

        # Compute error sets
        gt_allergy: Dict[str, dict] = {}
        gt_dosage_mm: Dict[str, dict] = {}
        gt_unauth: Dict[str, dict] = {}
        gt_missing: Dict[str, dict] = {}
        gt_dosedev: Dict[str, dict] = {}

        for rec in emar_rows:
            eid = rec["emar_id"]
            pid = rec["patient_id"]
            mid = rec["medication_id"]
            nid = rec["nurse_id"]
            admin_dose = rec["dose_mg"]
            admin_time = rec["administered_time"]
            admin_time_t = admin_time.split(" ")[1] if " " in admin_time else admin_time

            patient = patients[pid]
            fentry = formulary.get(mid, {})
            drug_class = fentry.get("drug_class", "")
            med_name = fentry.get("generic_name", mid)
            tol_pct = class_tols.get(drug_class, default_tol)
            presc = prescribed.get((pid, mid))

            # 1. ALLERGY_CONFLICT
            p_allerg = allergies_by_patient.get(pid, [])
            for a in p_allerg:
                if a["allergen_class"] == drug_class:
                    sev_map = {"severe": "CRITICAL", "moderate": "HIGH", "mild": "MEDIUM"}
                    gt_allergy[eid] = {
                        "error_severity": sev_map.get(a["severity"], "MEDIUM"),
                        "details": (
                            f"Patient allergic to {drug_class} "
                            f"(severity: {a['severity']})"
                        ),
                    }
                    break

            # 2. MISSING_DISPENSATION
            dkey = (pid, mid)
            if dkey not in disp_map:
                gt_missing[eid] = {
                    "error_severity": "HIGH",
                    "details": "No matching pharmacy dispensation found",
                }
            else:
                # 3. DOSAGE_MISMATCH
                disp_dose = disp_map[dkey]["dispensed_dose_mg"]
                if presc and presc > 0:
                    dev = abs(admin_dose - disp_dose) / presc * 100
                    if dev > tol_pct:
                        if dev > 50:
                            sev = "CRITICAL"
                        elif dev > 30:
                            sev = "HIGH"
                        else:
                            sev = "MEDIUM"
                        gt_dosage_mm[eid] = {
                            "error_severity": sev,
                            "details": (
                                f"Dispensed {disp_dose}mg vs administered "
                                f"{admin_dose}mg ({dev:.1f}% deviation)"
                            ),
                        }

            # 4. UNAUTHORIZED_ADMIN
            nurse_shifts = shifts_by_nurse.get(nid, [])
            authorized = False
            for s in nurse_shifts:
                if (
                    s["assigned_ward"] == patient["ward"]
                    and s["start_time"] <= admin_time_t < s["end_time"]
                ):
                    authorized = True
                    break
            if not authorized:
                gt_unauth[eid] = {
                    "error_severity": "HIGH",
                    "details": (
                        f"Nurse {nid} not authorized for ward "
                        f"{patient['ward']} at {admin_time_t}"
                    ),
                }

            # 5. DOSE_DEVIATION
            if presc and presc > 0:
                dev = abs(admin_dose - presc) / presc * 100
                if dev > tol_pct:
                    if dev > 50:
                        sev = "CRITICAL"
                    elif dev > 30:
                        sev = "HIGH"
                    else:
                        sev = "MEDIUM"
                    gt_dosedev[eid] = {
                        "error_severity": sev,
                        "details": (
                            f"Administered {admin_dose}mg vs prescribed "
                            f"{presc}mg ({dev:.1f}% deviation)"
                        ),
                    }

        return {
            "recon_date": recon_date,
            "n_emar": len(emar_rows),
            "gt_allergy": gt_allergy,
            "gt_dosage_mm": gt_dosage_mm,
            "gt_unauth": gt_unauth,
            "gt_missing": gt_missing,
            "gt_dosedev": gt_dosedev,
            "patients": patients,
            "formulary": formulary,
        }

    # ------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------

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
        gt = self._compute_ground_truth()

        # --- Parse agent outputs ---
        report_path = os.path.join(self.workspace, "reconciliation_report.csv")
        summary_path = os.path.join(self.workspace, "error_summary.json")

        agent_by_type: Dict[str, set] = {
            "ALLERGY_CONFLICT": set(),
            "DOSAGE_MISMATCH": set(),
            "UNAUTHORIZED_ADMIN": set(),
            "MISSING_DISPENSATION": set(),
            "DOSE_DEVIATION": set(),
        }
        report_exists = os.path.exists(report_path)
        report_columns_ok = False
        report_sorting_ok = False
        report_rows = []

        expected_cols = {
            "emar_id", "patient_id", "patient_name", "medication_id",
            "medication_name", "error_type", "error_severity", "details",
        }

        if report_exists:
            with open(report_path, newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and expected_cols.issubset(set(reader.fieldnames)):
                    report_columns_ok = True
                report_rows = list(reader)
            for row in report_rows:
                etype = row.get("error_type", "")
                eid = row.get("emar_id", "")
                if etype in agent_by_type:
                    agent_by_type[etype].add(eid)

            # Check sorting
            sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
            report_sorting_ok = True
            prev = (-1, "")
            for row in report_rows:
                key = (sev_order.get(row.get("error_severity", ""), 99),
                       row.get("emar_id", ""))
                if key < prev:
                    report_sorting_ok = False
                    break
                prev = key

        # Summary check
        total_gt = (len(gt["gt_allergy"]) + len(gt["gt_dosage_mm"])
                    + len(gt["gt_unauth"]) + len(gt["gt_missing"])
                    + len(gt["gt_dosedev"]))
        summary_ok = False
        if os.path.exists(summary_path):
            try:
                with open(summary_path) as f:
                    summary = json.load(f)
                if (summary.get("total_records_reviewed") == gt["n_emar"]
                        and summary.get("total_errors_found") == total_gt):
                    summary_ok = True
            except (json.JSONDecodeError, TypeError):
                pass

        # --- Scoring helper ---
        def _score(gt_dict, agent_set, max_pts):
            gt_set = set(gt_dict.keys())
            if not gt_set:
                return max_pts if not agent_set else max(0, max_pts - len(agent_set) * 2)
            tp = len(gt_set & agent_set)
            fp = len(agent_set - gt_set)
            recall = tp / len(gt_set)
            prec_pen = max(0.0, 1.0 - fp / max(1, 2 * len(gt_set)))
            return round(max_pts * recall * prec_pen, 2)

        criteria = {}

        s1 = _score(gt["gt_allergy"], agent_by_type["ALLERGY_CONFLICT"], 20)
        criteria["allergy_conflict"] = {
            "passed": s1 >= 20,
            "score": s1,
            "max_score": 20,
            **({"reason": f"expected {set(gt['gt_allergy'].keys())}, "
                          f"got {agent_by_type['ALLERGY_CONFLICT']}"}
               if s1 < 20 else {}),
        }

        s2 = _score(gt["gt_dosage_mm"], agent_by_type["DOSAGE_MISMATCH"], 20)
        criteria["dosage_mismatch"] = {
            "passed": s2 >= 20,
            "score": s2,
            "max_score": 20,
            **({"reason": f"expected {set(gt['gt_dosage_mm'].keys())}, "
                          f"got {agent_by_type['DOSAGE_MISMATCH']}"}
               if s2 < 20 else {}),
        }

        s3 = _score(gt["gt_unauth"], agent_by_type["UNAUTHORIZED_ADMIN"], 15)
        criteria["unauthorized_admin"] = {
            "passed": s3 >= 15,
            "score": s3,
            "max_score": 15,
            **({"reason": f"expected {set(gt['gt_unauth'].keys())}, "
                          f"got {agent_by_type['UNAUTHORIZED_ADMIN']}"}
               if s3 < 15 else {}),
        }

        s4 = _score(gt["gt_missing"], agent_by_type["MISSING_DISPENSATION"], 15)
        criteria["missing_dispensation"] = {
            "passed": s4 >= 15,
            "score": s4,
            "max_score": 15,
            **({"reason": f"expected {set(gt['gt_missing'].keys())}, "
                          f"got {agent_by_type['MISSING_DISPENSATION']}"}
               if s4 < 15 else {}),
        }

        s5 = _score(gt["gt_dosedev"], agent_by_type["DOSE_DEVIATION"], 15)
        criteria["dose_deviation"] = {
            "passed": s5 >= 15,
            "score": s5,
            "max_score": 15,
            **({"reason": f"expected {set(gt['gt_dosedev'].keys())}, "
                          f"got {agent_by_type['DOSE_DEVIATION']}"}
               if s5 < 15 else {}),
        }

        fmt_score = 0
        fmt_reasons = []
        if report_exists:
            fmt_score += 4
        else:
            fmt_reasons.append("reconciliation_report.csv missing")
        if report_columns_ok:
            fmt_score += 4
        else:
            fmt_reasons.append("report columns incorrect")
        if report_sorting_ok:
            fmt_score += 3
        else:
            fmt_reasons.append("report sorting incorrect")
        if summary_ok:
            fmt_score += 4
        else:
            fmt_reasons.append("error_summary.json missing or incorrect")

        criteria["report_format"] = {
            "passed": fmt_score >= 15,
            "score": fmt_score,
            "max_score": 15,
            **({"reason": "; ".join(fmt_reasons)} if fmt_score < 15 else {}),
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ------------------------------------------------------------------
    # verify
    # ------------------------------------------------------------------

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
        # --- Read workspace config files ---
        with open(os.path.join(self.workspace, "formulary.json")) as f:
            formulary = json.load(f)
        with open(os.path.join(self.workspace, "dosage_tolerance.yaml")) as f:
            tol_config = yaml.safe_load(f)
        default_tol = tol_config["default_tolerance_percent"]
        class_tols = tol_config["drug_class_tolerances"]

        # Read reconciliation date from policy
        recon_date = None
        with open(os.path.join(self.workspace, "reconciliation_policy.txt")) as f:
            for line in f:
                if "Reconciliation Date:" in line:
                    recon_date = line.split(":", 1)[1].strip()
                    break
        assert recon_date

        # Read prescribed orders from batch CSVs
        prescribed = {}  # (pid, mid) -> prescribed_dose_mg
        for fn in sorted(os.listdir(self.workspace)):
            if fn.startswith("medication_orders_batch_") and fn.endswith(".csv"):
                with open(os.path.join(self.workspace, fn)) as f:
                    for row in csv.DictReader(f):
                        prescribed[(row["patient_id"], row["medication_id"])] = float(
                            row["prescribed_dose_mg"]
                        )

        # --- Gather eMAR records via tools ---
        all_emar = []
        page = 1
        while True:
            result = self.tools["get_emar_records"](date=recon_date, page=page)
            all_emar.extend(result["records"])
            if not result["has_more"]:
                break
            page += 1

        # --- Gather dispensation records via tools ---
        all_disp = []
        page = 1
        while True:
            result = self.tools["get_dispensation_records"](date=recon_date, page=page)
            all_disp.extend(result["records"])
            if not result["has_more"]:
                break
            page += 1

        disp_lookup = {}
        for d in all_disp:
            disp_lookup[(d["patient_id"], d["medication_id"])] = d

        # --- Process each eMAR record ---
        errors = []
        patient_cache = {}
        allergy_cache = {}
        nurse_cache = {}

        for rec in all_emar:
            eid = rec["emar_id"]
            pid = rec["patient_id"]
            mid = rec["medication_id"]
            nid = rec["nurse_id"]
            admin_dose = rec["dose_mg"]
            admin_time = rec["administered_time"]
            admin_time_t = (
                admin_time.split(" ")[1] if " " in admin_time else admin_time
            )

            # Patient info (cached)
            if pid not in patient_cache:
                patient_cache[pid] = self.tools["get_patient_info"](
                    patient_id=pid
                )
            pinfo = patient_cache[pid]
            pname = pinfo["name"]
            pward = pinfo["ward"]

            # Formulary lookup (workspace)
            fentry = formulary.get(mid, {})
            drug_class = fentry.get("drug_class", "")
            med_name = fentry.get("generic_name", mid)

            tol_pct = class_tols.get(drug_class, default_tol)

            # Prescribed dose
            presc = prescribed.get((pid, mid))

            # 1. ALLERGY_CONFLICT
            if pid not in allergy_cache:
                allergy_cache[pid] = self.tools["get_patient_allergies"](
                    patient_id=pid
                )
            p_allergies = allergy_cache[pid]
            for a in p_allergies:
                if a["allergen_class"] == drug_class:
                    sev_map = {
                        "severe": "CRITICAL",
                        "moderate": "HIGH",
                        "mild": "MEDIUM",
                    }
                    errors.append({
                        "emar_id": eid,
                        "patient_id": pid,
                        "patient_name": pname,
                        "medication_id": mid,
                        "medication_name": med_name,
                        "error_type": "ALLERGY_CONFLICT",
                        "error_severity": sev_map.get(a["severity"], "MEDIUM"),
                        "details": (
                            f"Patient allergic to {drug_class} "
                            f"(severity: {a['severity']})"
                        ),
                    })
                    break

            # 2. MISSING_DISPENSATION / DOSAGE_MISMATCH
            dkey = (pid, mid)
            if dkey not in disp_lookup:
                errors.append({
                    "emar_id": eid,
                    "patient_id": pid,
                    "patient_name": pname,
                    "medication_id": mid,
                    "medication_name": med_name,
                    "error_type": "MISSING_DISPENSATION",
                    "error_severity": "HIGH",
                    "details": "No matching pharmacy dispensation found",
                })
            else:
                disp_dose = disp_lookup[dkey]["dispensed_dose_mg"]
                if presc and presc > 0:
                    dev = abs(admin_dose - disp_dose) / presc * 100
                    if dev > tol_pct:
                        if dev > 50:
                            sev = "CRITICAL"
                        elif dev > 30:
                            sev = "HIGH"
                        else:
                            sev = "MEDIUM"
                        errors.append({
                            "emar_id": eid,
                            "patient_id": pid,
                            "patient_name": pname,
                            "medication_id": mid,
                            "medication_name": med_name,
                            "error_type": "DOSAGE_MISMATCH",
                            "error_severity": sev,
                            "details": (
                                f"Dispensed {disp_dose}mg vs administered "
                                f"{admin_dose}mg ({dev:.1f}% deviation)"
                            ),
                        })

            # 3. UNAUTHORIZED_ADMIN
            nkey = (nid, recon_date)
            if nkey not in nurse_cache:
                nurse_cache[nkey] = self.tools["get_nurse_shift"](
                    nurse_id=nid, date=recon_date
                )
            shifts = nurse_cache[nkey]
            authorized = False
            for s in shifts:
                if (
                    s["assigned_ward"] == pward
                    and s["start_time"] <= admin_time_t < s["end_time"]
                ):
                    authorized = True
                    break
            if not authorized:
                errors.append({
                    "emar_id": eid,
                    "patient_id": pid,
                    "patient_name": pname,
                    "medication_id": mid,
                    "medication_name": med_name,
                    "error_type": "UNAUTHORIZED_ADMIN",
                    "error_severity": "HIGH",
                    "details": (
                        f"Nurse {nid} not authorized for ward "
                        f"{pward} at {admin_time_t}"
                    ),
                })

            # 4. DOSE_DEVIATION
            if presc and presc > 0:
                dev = abs(admin_dose - presc) / presc * 100
                if dev > tol_pct:
                    if dev > 50:
                        sev = "CRITICAL"
                    elif dev > 30:
                        sev = "HIGH"
                    else:
                        sev = "MEDIUM"
                    errors.append({
                        "emar_id": eid,
                        "patient_id": pid,
                        "patient_name": pname,
                        "medication_id": mid,
                        "medication_name": med_name,
                        "error_type": "DOSE_DEVIATION",
                        "error_severity": sev,
                        "details": (
                            f"Administered {admin_dose}mg vs prescribed "
                            f"{presc}mg ({dev:.1f}% deviation)"
                        ),
                    })

        # --- Sort errors ---
        sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        errors.sort(key=lambda e: (sev_order.get(e["error_severity"], 99),
                                   e["emar_id"]))

        # --- Write reconciliation_report.csv ---
        rpt_path = os.path.join(self.workspace, "reconciliation_report.csv")
        with open(rpt_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "emar_id", "patient_id", "patient_name", "medication_id",
                "medication_name", "error_type", "error_severity", "details",
            ])
            writer.writeheader()
            writer.writerows(errors)

        # --- Write error_summary.json ---
        errors_by_type: Dict[str, int] = {}
        errors_by_sev: Dict[str, int] = {}
        for e in errors:
            errors_by_type[e["error_type"]] = errors_by_type.get(
                e["error_type"], 0) + 1
            errors_by_sev[e["error_severity"]] = errors_by_sev.get(
                e["error_severity"], 0) + 1

        summary = {
            "reconciliation_date": recon_date,
            "total_records_reviewed": len(all_emar),
            "total_errors_found": len(errors),
            "errors_by_type": errors_by_type,
            "errors_by_severity": errors_by_sev,
        }
        with open(os.path.join(self.workspace, "error_summary.json"), "w") as f:
            json.dump(summary, f, indent=2)

        # --- Build action string ---
        parts = [
            f"Reconciliation completed for {recon_date}.",
            f"Reviewed {len(all_emar)} eMAR records.",
            f"Found {len(errors)} total errors.",
            "Breakdown by type:",
        ]
        for etype in ["ALLERGY_CONFLICT", "DOSAGE_MISMATCH",
                       "UNAUTHORIZED_ADMIN", "MISSING_DISPENSATION",
                       "DOSE_DEVIATION"]:
            parts.append(f"  {etype}: {errors_by_type.get(etype, 0)}")
        parts.append("Breakdown by severity:")
        for sev in ["CRITICAL", "HIGH", "MEDIUM"]:
            parts.append(f"  {sev}: {errors_by_sev.get(sev, 0)}")

        action = "\n".join(parts)
        return self.step(action)
