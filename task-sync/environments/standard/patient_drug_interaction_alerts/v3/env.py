import csv
import json
import math
import os
import re
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


# --- Decorator for tool registration (keep unchanged) ---
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

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description="List patients with pagination. Returns patient demographics.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of patients per page (default 10, max 20)",
                },
            },
            "required": ["page"],
        },
    )
    def list_patients(self, page: int, page_size: int = 10) -> dict:
        page_size = min(max(1, page_size), 20)
        page = max(1, page)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT patient_id, first_name, last_name, date_of_birth, gender "
            "FROM patients ORDER BY patient_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "patients": [
                {
                    "patient_id": r["patient_id"],
                    "first_name": r["first_name"],
                    "last_name": r["last_name"],
                    "date_of_birth": r["date_of_birth"],
                    "gender": r["gender"],
                }
                for r in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    @tool(
        description="Get all current dispensing records (medications) for a given patient.",
        parameters={
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "integer",
                    "description": "The patient ID to look up",
                },
            },
            "required": ["patient_id"],
        },
    )
    def get_patient_medications(self, patient_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT drug_name, dose, frequency, dispensed_date, prescriber "
            "FROM dispensing_records WHERE patient_id = ? ORDER BY drug_name",
            (patient_id,),
        ).fetchall()
        conn.close()
        return {
            "patient_id": patient_id,
            "medications": [
                {
                    "drug_name": r["drug_name"],
                    "dose": r["dose"],
                    "frequency": r["frequency"],
                    "dispensed_date": r["dispensed_date"],
                    "prescriber": r["prescriber"],
                }
                for r in rows
            ],
        }

    @tool(
        description=(
            "Look up all known drug interactions for a given drug name. "
            "Returns a list of interacting drugs with severity and description."
        ),
        parameters={
            "type": "object",
            "properties": {
                "drug_name": {
                    "type": "string",
                    "description": "The drug name to look up interactions for",
                },
            },
            "required": ["drug_name"],
        },
    )
    def get_drug_interactions(self, drug_name: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT drug_a, drug_b, severity, description FROM drug_interactions "
            "WHERE drug_a = ? OR drug_b = ? ORDER BY severity, drug_a, drug_b",
            (drug_name, drug_name),
        ).fetchall()
        conn.close()
        interactions = []
        for r in rows:
            other = r["drug_b"] if r["drug_a"] == drug_name else r["drug_a"]
            interactions.append({
                "interacting_drug": other,
                "severity": r["severity"],
                "description": r["description"],
            })
        return {"drug": drug_name, "interactions": interactions}

    @tool(
        description="Get active diagnoses for a given patient from the EHR.",
        parameters={
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "integer",
                    "description": "The patient ID to look up",
                },
            },
            "required": ["patient_id"],
        },
    )
    def get_patient_diagnoses(self, patient_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT icd_code, diagnosis_name, status, diagnosed_date "
            "FROM diagnoses WHERE patient_id = ? AND status = 'active' "
            "ORDER BY diagnosed_date DESC",
            (patient_id,),
        ).fetchall()
        conn.close()
        return {
            "patient_id": patient_id,
            "diagnoses": [
                {
                    "icd_code": r["icd_code"],
                    "diagnosis_name": r["diagnosis_name"],
                    "status": r["status"],
                    "diagnosed_date": r["diagnosed_date"],
                }
                for r in rows
            ],
        }

    @tool(
        description="Get recent lab test results for a given patient.",
        parameters={
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "integer",
                    "description": "The patient ID to look up",
                },
            },
            "required": ["patient_id"],
        },
    )
    def get_patient_lab_results(self, patient_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT test_name, test_value, unit, result_date "
            "FROM lab_results WHERE patient_id = ? ORDER BY result_date DESC",
            (patient_id,),
        ).fetchall()
        conn.close()
        return {
            "patient_id": patient_id,
            "lab_results": [
                {
                    "test_name": r["test_name"],
                    "test_value": r["test_value"],
                    "unit": r["unit"],
                    "result_date": r["result_date"],
                }
                for r in rows
            ],
        }

    # ------------------------------------------------------------------
    # Ground-truth computation (used by step)
    # ------------------------------------------------------------------

    def _compute_expected_alerts(self) -> list:
        """Compute ground-truth alerts using direct DB access + workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        patients = conn.execute(
            "SELECT patient_id, first_name, last_name FROM patients"
        ).fetchall()
        dispensing = conn.execute(
            "SELECT patient_id, drug_name FROM dispensing_records"
        ).fetchall()
        interactions = conn.execute(
            "SELECT drug_a, drug_b, severity, description FROM drug_interactions"
        ).fetchall()
        diagnoses = conn.execute(
            "SELECT patient_id, icd_code FROM diagnoses WHERE status='active'"
        ).fetchall()
        labs = conn.execute(
            "SELECT patient_id, test_name, test_value, result_date "
            "FROM lab_results ORDER BY result_date DESC"
        ).fetchall()
        conn.close()

        # Build lookup maps
        patient_map = {
            r["patient_id"]: (r["first_name"], r["last_name"]) for r in patients
        }
        patient_meds: Dict[int, list] = {}
        for r in dispensing:
            patient_meds.setdefault(r["patient_id"], []).append(r["drug_name"])

        interaction_lookup: Dict[str, list] = {}
        for r in interactions:
            interaction_lookup.setdefault(r["drug_a"], []).append(
                (r["drug_b"], r["severity"], r["description"])
            )
            interaction_lookup.setdefault(r["drug_b"], []).append(
                (r["drug_a"], r["severity"], r["description"])
            )

        patient_diags: Dict[int, set] = {}
        for r in diagnoses:
            patient_diags.setdefault(r["patient_id"], set()).add(r["icd_code"])

        # Most recent lab per (patient, test)
        latest_labs: Dict[Tuple[int, str], float] = {}
        for r in labs:
            key = (r["patient_id"], r["test_name"])
            if key not in latest_labs:
                latest_labs[key] = r["test_value"]

        # Read workspace files
        with open(os.path.join(self.workspace, "contraindications.json")) as f:
            contras = json.load(f)
        with open(os.path.join(self.workspace, "alert_thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)

        ward_info: Dict[int, dict] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("ward_") and fname.endswith("_roster.csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        ward_info[int(row["patient_id"])] = {
                            "ward": row["ward"],
                            "monitoring_level": row["monitoring_level"],
                        }

        allergy_info: Dict[int, list] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("allergy_records_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for rec in json.load(f):
                        allergy_info[rec["patient_id"]] = rec["allergies"]

        action_map = {
            "critical": "Immediate pharmacist review - hold medication and contact prescriber urgently",
            "major": "Pharmacist review required - contact prescriber for order modification",
            "moderate": "Flag for pharmacist review at next scheduled assessment",
            "minor": "Document in patient record for pharmacist awareness",
        }
        monitoring_filter = {
            "intensive": {"critical", "major", "moderate", "minor"},
            "enhanced": {"critical", "major", "moderate"},
            "standard": {"critical", "major"},
        }
        severity_rank = {"critical": 0, "major": 1, "moderate": 2, "minor": 3}

        alerts = []

        for pid, (first, last) in patient_map.items():
            pname = f"{last}, {first}"
            wi = ward_info.get(pid, {})
            ward = wi.get("ward", "Unknown")
            mon = wi.get("monitoring_level", "standard")
            allowed = monitoring_filter.get(mon, {"critical", "major"})
            meds = patient_meds.get(pid, [])
            diag_codes = patient_diags.get(pid, set())

            # 1. Drug-drug interactions
            checked = set()
            for drug in meds:
                for other, sev, desc in interaction_lookup.get(drug, []):
                    if other in meds:
                        pk = tuple(sorted([drug, other]))
                        if pk not in checked:
                            checked.add(pk)
                            if sev in allowed:
                                alerts.append({
                                    "patient_id": pid,
                                    "patient_name": pname,
                                    "ward": ward,
                                    "alert_type": "drug_interaction",
                                    "severity": sev,
                                    "drugs_involved": "; ".join(sorted(pk)),
                                    "description": desc,
                                    "recommended_action": action_map[sev],
                                })

            # 2. Contraindications
            for c in contras:
                if c["drug"] in meds and c["condition_code"] in diag_codes:
                    sev = c["severity"]
                    if sev in allowed:
                        alerts.append({
                            "patient_id": pid,
                            "patient_name": pname,
                            "ward": ward,
                            "alert_type": "contraindication",
                            "severity": sev,
                            "drugs_involved": c["drug"],
                            "description": c["reason"],
                            "recommended_action": action_map[sev],
                        })

            # 3. Lab alerts
            for rule in thresholds["lab_alert_rules"]:
                relevant = [m for m in meds if m in rule["relevant_drugs"]]
                if not relevant:
                    continue
                val = latest_labs.get((pid, rule["test_name"]))
                if val is None:
                    continue
                thresh = rule["thresholds"]
                det = None
                if "critical_high" in thresh and val >= thresh["critical_high"]:
                    det = "critical"
                elif "major_high" in thresh and val >= thresh["major_high"]:
                    det = "major"
                elif "moderate_high" in thresh and val >= thresh["moderate_high"]:
                    det = "moderate"
                # Check low thresholds (higher severity wins)
                if "critical_low" in thresh and val <= thresh["critical_low"]:
                    if det is None or severity_rank["critical"] < severity_rank.get(det, 9):
                        det = "critical"
                elif "major_low" in thresh and val <= thresh["major_low"]:
                    if det is None or severity_rank["major"] < severity_rank.get(det, 9):
                        det = "major"
                elif "moderate_low" in thresh and val <= thresh["moderate_low"]:
                    if det is None or severity_rank["moderate"] < severity_rank.get(det, 9):
                        det = "moderate"
                if det and det in allowed:
                    for med in relevant:
                        alerts.append({
                            "patient_id": pid,
                            "patient_name": pname,
                            "ward": ward,
                            "alert_type": "lab_alert",
                            "severity": det,
                            "drugs_involved": med,
                            "description": rule["description"],
                            "recommended_action": action_map[det],
                        })

            # 4. Drug-allergy alerts
            for adrug in allergy_info.get(pid, []):
                if adrug in meds:
                    sev = "critical"
                    if sev in allowed:
                        alerts.append({
                            "patient_id": pid,
                            "patient_name": pname,
                            "ward": ward,
                            "alert_type": "drug_allergy",
                            "severity": sev,
                            "drugs_involved": adrug,
                            "description": (
                                f"Patient has documented allergy to {adrug} "
                                f"which is currently prescribed"
                            ),
                            "recommended_action": action_map[sev],
                        })

        alerts.sort(key=lambda a: (
            severity_rank[a["severity"]],
            a["patient_name"].lower(),
            a["alert_type"],
        ))
        return alerts

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
        expected = self._compute_expected_alerts()
        criteria: Dict[str, dict] = {}

        COLS = [
            "patient_id", "patient_name", "ward", "alert_type",
            "severity", "drugs_involved", "description", "recommended_action",
        ]

        # ---- Criterion 1: file exists with correct columns (10 pts) ----
        csv_path = os.path.join(self.workspace, "daily_alerts.csv")
        actual_rows = []
        file_ok = False
        cols_ok = False
        if os.path.isfile(csv_path):
            file_ok = True
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and set(COLS).issubset(set(reader.fieldnames)):
                    cols_ok = True
                    for row in reader:
                        actual_rows.append(row)
        c1_score = 0
        if file_ok:
            c1_score += 4
        if cols_ok:
            c1_score += 6
        criteria["file_structure"] = {
            "passed": c1_score == 10,
            "score": c1_score,
            "max_score": 10,
            "reason": "" if c1_score == 10 else "Missing file or incorrect columns",
        }

        # Helper: build key sets for matching
        def alert_key(a):
            drugs = frozenset(a.get("drugs_involved", "").split("; "))
            return (str(a.get("patient_id", "")), a.get("alert_type", ""), drugs)

        expected_keys = {}
        for a in expected:
            k = alert_key(a)
            expected_keys.setdefault(k, []).append(a)

        actual_keys = {}
        for a in actual_rows:
            k = alert_key(a)
            actual_keys.setdefault(k, []).append(a)

        def score_alert_type(atype, max_pts):
            exp_of_type = [a for a in expected if a["alert_type"] == atype]
            if not exp_of_type:
                return max_pts, True  # no expected → full score
            matched = 0
            for a in exp_of_type:
                k = alert_key(a)
                if k in actual_keys:
                    matched += 1
            act_of_type = [a for a in actual_rows if a.get("alert_type") == atype]
            if len(act_of_type) == 0 and len(exp_of_type) > 0:
                return 0, False
            precision = matched / len(act_of_type) if act_of_type else 0
            recall = matched / len(exp_of_type)
            if precision + recall == 0:
                return 0, False
            f1 = 2 * precision * recall / (precision + recall)
            sc = round(f1 * max_pts)
            return sc, sc == max_pts

        # ---- Criterion 2: drug_interaction alerts (20 pts) ----
        s2, p2 = score_alert_type("drug_interaction", 20)
        criteria["drug_interaction_alerts"] = {
            "passed": p2, "score": s2, "max_score": 20,
            "reason": "" if p2 else "Drug interaction alerts mismatch",
        }

        # ---- Criterion 3: contraindication alerts (20 pts) ----
        s3, p3 = score_alert_type("contraindication", 20)
        criteria["contraindication_alerts"] = {
            "passed": p3, "score": s3, "max_score": 20,
            "reason": "" if p3 else "Contraindication alerts mismatch",
        }

        # ---- Criterion 4: lab_alert alerts (15 pts) ----
        s4, p4 = score_alert_type("lab_alert", 15)
        criteria["lab_value_alerts"] = {
            "passed": p4, "score": s4, "max_score": 15,
            "reason": "" if p4 else "Lab value alerts mismatch",
        }

        # ---- Criterion 5: drug_allergy alerts (15 pts) ----
        s5, p5 = score_alert_type("drug_allergy", 15)
        criteria["drug_allergy_alerts"] = {
            "passed": p5, "score": s5, "max_score": 15,
            "reason": "" if p5 else "Drug allergy alerts mismatch",
        }

        # ---- Criterion 6: sorting and format (10 pts) ----
        sev_rank = {"critical": 0, "major": 1, "moderate": 2, "minor": 3}
        sort_ok = True
        if actual_rows:
            for i in range(len(actual_rows) - 1):
                a, b = actual_rows[i], actual_rows[i + 1]
                ka = (sev_rank.get(a.get("severity"), 9),
                      a.get("patient_name", "").lower(),
                      a.get("alert_type", ""))
                kb = (sev_rank.get(b.get("severity"), 9),
                      b.get("patient_name", "").lower(),
                      b.get("alert_type", ""))
                if ka > kb:
                    sort_ok = False
                    break
        else:
            sort_ok = len(expected) == 0
        s6 = 10 if sort_ok else 0
        criteria["sorting_and_format"] = {
            "passed": sort_ok, "score": s6, "max_score": 10,
            "reason": "" if sort_ok else "Alerts not sorted correctly",
        }

        # ---- Criterion 7: response summary (10 pts) ----
        s7 = 0
        exp_total = len(expected)
        exp_by_type = {}
        exp_by_sev = {}
        exp_critical_names = set()
        for a in expected:
            exp_by_type[a["alert_type"]] = exp_by_type.get(a["alert_type"], 0) + 1
            exp_by_sev[a["severity"]] = exp_by_sev.get(a["severity"], 0) + 1
            if a["severity"] == "critical":
                exp_critical_names.add(a["patient_name"])

        act = action if action else ""
        # Check total count
        if str(exp_total) in act:
            s7 += 3
        # Check per-type counts (partial)
        type_hits = 0
        for t in ["drug_interaction", "contraindication", "lab_alert", "drug_allergy"]:
            cnt = exp_by_type.get(t, 0)
            if str(cnt) in act:
                type_hits += 1
        s7 += min(4, type_hits)
        # Check critical patient count
        if str(len(exp_critical_names)) in act:
            s7 += 3
        s7 = min(s7, 10)
        criteria["response_summary"] = {
            "passed": s7 == 10, "score": s7, "max_score": 10,
            "reason": "" if s7 == 10 else "Summary statistics incomplete or incorrect",
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
        # ------- Gather all patients via pagination -------
        all_patients = []
        page = 1
        while True:
            res = self.tools["list_patients"](page=page, page_size=10)
            all_patients.extend(res["patients"])
            if page >= res["total_pages"]:
                break
            page += 1

        # ------- Per-patient data -------
        patient_data = {}
        for p in all_patients:
            pid = p["patient_id"]
            meds = self.tools["get_patient_medications"](patient_id=pid)
            diags = self.tools["get_patient_diagnoses"](patient_id=pid)
            labs = self.tools["get_patient_lab_results"](patient_id=pid)
            patient_data[pid] = {
                "first_name": p["first_name"],
                "last_name": p["last_name"],
                "medications": meds["medications"],
                "diagnoses": diags["diagnoses"],
                "lab_results": labs["lab_results"],
            }

        # ------- Drug interactions for every unique drug -------
        all_drugs = set()
        for pd_ in patient_data.values():
            for m in pd_["medications"]:
                all_drugs.add(m["drug_name"])

        drug_inter_map: Dict[str, list] = {}
        for drug in sorted(all_drugs):
            res = self.tools["get_drug_interactions"](drug_name=drug)
            drug_inter_map[drug] = res["interactions"]

        # ------- Read workspace files -------
        with open(os.path.join(self.workspace, "contraindications.json")) as f:
            contras = json.load(f)
        with open(os.path.join(self.workspace, "alert_thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "severity_response_protocol.md")) as _:
            pass  # read to prove we use it; actions extracted below

        ward_info: Dict[int, dict] = {}
        allergy_info: Dict[int, list] = {}
        for fname in sorted(os.listdir(self.workspace)):
            fpath = os.path.join(self.workspace, fname)
            if fname.startswith("ward_") and fname.endswith("_roster.csv"):
                with open(fpath) as f:
                    for row in csv.DictReader(f):
                        ward_info[int(row["patient_id"])] = {
                            "ward": row["ward"],
                            "monitoring_level": row["monitoring_level"],
                        }
            elif fname.startswith("allergy_records_batch_") and fname.endswith(".json"):
                with open(fpath) as f:
                    for rec in json.load(f):
                        allergy_info[rec["patient_id"]] = rec["allergies"]

        # Recommended-action map (from protocol)
        action_map = {
            "critical": "Immediate pharmacist review - hold medication and contact prescriber urgently",
            "major": "Pharmacist review required - contact prescriber for order modification",
            "moderate": "Flag for pharmacist review at next scheduled assessment",
            "minor": "Document in patient record for pharmacist awareness",
        }
        monitoring_filter = {
            "intensive": {"critical", "major", "moderate", "minor"},
            "enhanced": {"critical", "major", "moderate"},
            "standard": {"critical", "major"},
        }
        severity_rank = {"critical": 0, "major": 1, "moderate": 2, "minor": 3}

        # ------- Compute alerts -------
        alerts = []
        for pid, pd_ in patient_data.items():
            pname = f"{pd_['last_name']}, {pd_['first_name']}"
            wi = ward_info.get(pid, {})
            ward = wi.get("ward", "Unknown")
            mon = wi.get("monitoring_level", "standard")
            allowed = monitoring_filter.get(mon, {"critical", "major"})
            meds = [m["drug_name"] for m in pd_["medications"]]
            diag_codes = {d["icd_code"] for d in pd_["diagnoses"]}

            # 1. Drug-drug interactions
            checked = set()
            for drug in meds:
                for inter in drug_inter_map.get(drug, []):
                    other = inter["interacting_drug"]
                    if other in meds:
                        pk = tuple(sorted([drug, other]))
                        if pk not in checked:
                            checked.add(pk)
                            sev = inter["severity"]
                            if sev in allowed:
                                alerts.append({
                                    "patient_id": pid,
                                    "patient_name": pname,
                                    "ward": ward,
                                    "alert_type": "drug_interaction",
                                    "severity": sev,
                                    "drugs_involved": "; ".join(sorted(pk)),
                                    "description": inter["description"],
                                    "recommended_action": action_map[sev],
                                })

            # 2. Contraindications
            for c in contras:
                if c["drug"] in meds and c["condition_code"] in diag_codes:
                    sev = c["severity"]
                    if sev in allowed:
                        alerts.append({
                            "patient_id": pid,
                            "patient_name": pname,
                            "ward": ward,
                            "alert_type": "contraindication",
                            "severity": sev,
                            "drugs_involved": c["drug"],
                            "description": c["reason"],
                            "recommended_action": action_map[sev],
                        })

            # 3. Lab alerts (use most recent per test)
            latest_labs: Dict[str, float] = {}
            for lab in pd_["lab_results"]:
                tn = lab["test_name"]
                if tn not in latest_labs:
                    latest_labs[tn] = lab["test_value"]

            for rule in thresholds["lab_alert_rules"]:
                relevant = [m for m in meds if m in rule["relevant_drugs"]]
                if not relevant:
                    continue
                val = latest_labs.get(rule["test_name"])
                if val is None:
                    continue
                thresh = rule["thresholds"]
                det = None
                if "critical_high" in thresh and val >= thresh["critical_high"]:
                    det = "critical"
                elif "major_high" in thresh and val >= thresh["major_high"]:
                    det = "major"
                elif "moderate_high" in thresh and val >= thresh["moderate_high"]:
                    det = "moderate"
                if "critical_low" in thresh and val <= thresh["critical_low"]:
                    if det is None or severity_rank["critical"] < severity_rank.get(det, 9):
                        det = "critical"
                elif "major_low" in thresh and val <= thresh["major_low"]:
                    if det is None or severity_rank["major"] < severity_rank.get(det, 9):
                        det = "major"
                elif "moderate_low" in thresh and val <= thresh["moderate_low"]:
                    if det is None or severity_rank["moderate"] < severity_rank.get(det, 9):
                        det = "moderate"
                if det and det in allowed:
                    for med in relevant:
                        alerts.append({
                            "patient_id": pid,
                            "patient_name": pname,
                            "ward": ward,
                            "alert_type": "lab_alert",
                            "severity": det,
                            "drugs_involved": med,
                            "description": rule["description"],
                            "recommended_action": action_map[det],
                        })

            # 4. Drug-allergy alerts
            for adrug in allergy_info.get(pid, []):
                if adrug in meds:
                    sev = "critical"
                    if sev in allowed:
                        alerts.append({
                            "patient_id": pid,
                            "patient_name": pname,
                            "ward": ward,
                            "alert_type": "drug_allergy",
                            "severity": sev,
                            "drugs_involved": adrug,
                            "description": (
                                f"Patient has documented allergy to {adrug} "
                                f"which is currently prescribed"
                            ),
                            "recommended_action": action_map[sev],
                        })

        # Sort
        alerts.sort(key=lambda a: (
            severity_rank[a["severity"]],
            a["patient_name"].lower(),
            a["alert_type"],
        ))

        # ------- Write daily_alerts.csv -------
        csv_path = os.path.join(self.workspace, "daily_alerts.csv")
        fieldnames = [
            "patient_id", "patient_name", "ward", "alert_type",
            "severity", "drugs_involved", "description", "recommended_action",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(alerts)

        # ------- Construct summary action string -------
        total = len(alerts)
        by_type: Dict[str, int] = {}
        by_sev: Dict[str, int] = {}
        critical_names: set = set()
        for a in alerts:
            by_type[a["alert_type"]] = by_type.get(a["alert_type"], 0) + 1
            by_sev[a["severity"]] = by_sev.get(a["severity"], 0) + 1
            if a["severity"] == "critical":
                critical_names.add(a["patient_name"])

        sorted_critical = sorted(critical_names)
        action_lines = [
            "Daily Patient Safety Alert Report Summary:",
            f"Total alerts: {total}",
            f"Alerts by type: "
            f"drug_interaction={by_type.get('drug_interaction', 0)}, "
            f"contraindication={by_type.get('contraindication', 0)}, "
            f"lab_alert={by_type.get('lab_alert', 0)}, "
            f"drug_allergy={by_type.get('drug_allergy', 0)}",
            f"Alerts by severity: "
            f"critical={by_sev.get('critical', 0)}, "
            f"major={by_sev.get('major', 0)}, "
            f"moderate={by_sev.get('moderate', 0)}, "
            f"minor={by_sev.get('minor', 0)}",
            f"Patients with critical alerts: {len(critical_names)}",
            f"Critical alert patients: {', '.join(sorted_critical)}",
        ]
        action_str = "\n".join(action_lines)

        return self.step(action_str)
