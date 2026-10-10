"""
Environment for visa application triage task.
Defines tools for querying applicant data and evaluating the agent's
intervention list output.
"""

import csv
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

    # ── Tool Methods ──────────────────────────────────────────────────────

    @tool(
        description="Search for visa applicants with optional filters. Returns paginated results (max 20 per page). Returns applicant_id, full_name, visa_category, priority_level, embassy_id, submission_date, current_status.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by current_status (e.g. 'pending', 'in_review', 'on_hold', 'awaiting_documents', 'approved', 'denied')",
                },
                "visa_category": {
                    "type": "string",
                    "description": "Filter by visa category (e.g. 'diplomatic', 'employment', 'business', 'student', 'family_reunion', 'tourist')",
                },
                "embassy_id": {
                    "type": "string",
                    "description": "Filter by embassy ID (e.g. 'EMB_001')",
                },
                "priority_level": {
                    "type": "string",
                    "description": "Filter by priority level ('critical', 'high', 'medium', 'low')",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20). Default 20.",
                },
            },
            "required": [],
        },
    )
    def search_applicants(
        self,
        status: str = None,
        visa_category: str = None,
        embassy_id: str = None,
        priority_level: str = None,
        page: int = 1,
        page_size: int = 20,
    ):
        page_size = min(page_size, 20)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        query = "SELECT * FROM applicants WHERE 1=1"
        params = []
        if status:
            query += " AND current_status = ?"
            params.append(status)
        if visa_category:
            query += " AND visa_category = ?"
            params.append(visa_category)
        if embassy_id:
            query += " AND embassy_id = ?"
            params.append(embassy_id)
        if priority_level:
            query += " AND priority_level = ?"
            params.append(priority_level)

        # Get total count
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        c.execute(count_query, params)
        total = c.fetchone()[0]

        query += " ORDER BY applicant_id ASC LIMIT ? OFFSET ?"
        params.extend([page_size, (page - 1) * page_size])
        c.execute(query, params)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()

        return {
            "results": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get detailed information for a specific applicant by their ID.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The applicant ID (e.g. 'APP_00001')",
                },
            },
            "required": ["applicant_id"],
        },
    )
    def get_applicant_details(self, applicant_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM applicants WHERE applicant_id = ?", (applicant_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Applicant {applicant_id} not found"}

    @tool(
        description="Retrieve all biometric submissions for a given applicant. Returns bio_id, bio_type, capture_date, quality_score, status, expiry_date.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The applicant ID",
                },
            },
            "required": ["applicant_id"],
        },
    )
    def get_biometric_status(self, applicant_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM biometric_submissions WHERE applicant_id = ? ORDER BY capture_date DESC",
            (applicant_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"applicant_id": applicant_id, "biometrics": rows}

    @tool(
        description="Retrieve all document verification records for a given applicant, including any flags.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The applicant ID",
                },
            },
            "required": ["applicant_id"],
        },
    )
    def get_document_flags(self, applicant_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM document_verifications WHERE applicant_id = ? ORDER BY doc_id",
            (applicant_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"applicant_id": applicant_id, "documents": rows}

    @tool(
        description="Retrieve all embassy appointment records for a given applicant.",
        parameters={
            "type": "object",
            "properties": {
                "applicant_id": {
                    "type": "string",
                    "description": "The applicant ID",
                },
            },
            "required": ["applicant_id"],
        },
    )
    def get_appointment_history(self, applicant_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM embassy_appointments WHERE applicant_id = ? ORDER BY scheduled_date DESC",
            (applicant_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"applicant_id": applicant_id, "appointments": rows}

    @tool(
        description="Get visa quota utilization for a specific visa category and embassy in a given quarter.",
        parameters={
            "type": "object",
            "properties": {
                "visa_category": {
                    "type": "string",
                    "description": "Visa category (e.g. 'employment')",
                },
                "embassy_id": {
                    "type": "string",
                    "description": "Embassy ID (e.g. 'EMB_001')",
                },
                "quarter": {
                    "type": "string",
                    "description": "Fiscal quarter (e.g. 'Q2'). Default is 'Q2'.",
                },
            },
            "required": ["visa_category", "embassy_id"],
        },
    )
    def get_visa_quota(self, visa_category: str, embassy_id: str, quarter: str = "Q2"):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM visa_quotas WHERE visa_category = ? AND embassy_id = ? AND quarter = ?",
            (visa_category, embassy_id, quarter),
        )
        row = c.fetchone()
        conn.close()
        if row:
            d = dict(row)
            d["utilization_pct"] = round(d["used_count"] / d["allocated_quota"] * 100, 2) if d["allocated_quota"] > 0 else 0
            return d
        return {"error": f"No quota record found for {visa_category} at {embassy_id} in {quarter}"}

    @tool(
        description="List all embassy IDs in the system.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_embassies(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT DISTINCT embassy_id FROM applicants ORDER BY embassy_id")
        embassies = [r[0] for r in c.fetchall()]
        conn.close()
        return {"embassies": embassies}

    @tool(
        description="List all visa categories in the system.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_visa_categories(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT DISTINCT visa_category FROM applicants ORDER BY visa_category")
        cats = [r[0] for r in c.fetchall()]
        conn.close()
        return {"visa_categories": cats}

    # ── Evaluation ────────────────────────────────────────────────────────

    def _load_config(self):
        """Load workspace config files for evaluation."""
        with open(os.path.join(self.workspace, "stall_criteria.json")) as f:
            stall_criteria = json.load(f)
        with open(os.path.join(self.workspace, "priority_scoring_rules.yaml")) as f:
            priority_rules = yaml.safe_load(f)
        standards = {}
        with open(os.path.join(self.workspace, "visa_processing_standards.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                standards[row["visa_category"]] = {
                    "standard_sla_days": int(row["standard_sla_days"]),
                    "requires_interview": row["requires_interview"],
                    "max_renewals": int(row["max_renewals"]),
                }
        return stall_criteria, priority_rules, standards

    def _load_case_dossiers(self):
        """Load all case dossier data from workspace files."""
        dossiers = {}  # applicant_id -> {escalation_level, sponsor_tier, ...}
        for fname in os.listdir(self.workspace):
            if not fname.startswith("case_dossier_batch_"):
                continue
            fpath = os.path.join(self.workspace, fname)
            if fname.endswith(".json"):
                with open(fpath) as f:
                    records = json.load(f)
                for rec in records:
                    dossiers[rec["applicant_id"]] = rec
            elif fname.endswith(".csv"):
                with open(fpath) as f:
                    reader = csv.DictReader(f)
                    for rec in reader:
                        rec["escalation_level"] = int(rec["escalation_level"])
                        if rec.get("special_circumstances") == "":
                            rec["special_circumstances"] = None
                        dossiers[rec["applicant_id"]] = rec
            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    content = f.read()
                current = {}
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("--- Applicant:"):
                        if current.get("applicant_id"):
                            dossiers[current["applicant_id"]] = current
                        app_id = line.split("--- Applicant:")[1].strip().rstrip(" ---")
                        current = {"applicant_id": app_id}
                    elif line.startswith("Escalation Level:"):
                        current["escalation_level"] = int(line.split(":")[1].strip())
                    elif line.startswith("Sponsor Tier:"):
                        current["sponsor_tier"] = line.split(":")[1].strip()
                    elif line.startswith("Special Circumstances:"):
                        val = line.split(":", 1)[1].strip()
                        current["special_circumstances"] = None if val == "None" else val
                    elif line.startswith("Last Officer Contact:"):
                        current["last_officer_contact"] = line.split(":")[1].strip()
                if current.get("applicant_id"):
                    dossiers[current["applicant_id"]] = current
            elif fname.endswith(".yaml"):
                with open(fpath) as f:
                    records = yaml.safe_load(f)
                if records:
                    for rec in records:
                        dossiers[rec["applicant_id"]] = rec
            elif fname.endswith(".md"):
                with open(fpath) as f:
                    content = f.read()
                current = {}
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("## APP_"):
                        if current.get("applicant_id"):
                            dossiers[current["applicant_id"]] = current
                        current = {"applicant_id": line[3:].strip()}
                    elif line.startswith("| Escalation Level |"):
                        val = line.split("|")[2].strip()
                        current["escalation_level"] = int(val)
                    elif line.startswith("| Sponsor Tier |"):
                        current["sponsor_tier"] = line.split("|")[2].strip()
                    elif line.startswith("| Special Circumstances |"):
                        val = line.split("|")[2].strip()
                        current["special_circumstances"] = None if val == "None" else val
                    elif line.startswith("| Last Officer Contact |"):
                        current["last_officer_contact"] = line.split("|")[2].strip()
                if current.get("applicant_id"):
                    dossiers[current["applicant_id"]] = current
        return dossiers

    def _compute_ground_truth(self):
        """Compute the expected intervention list from scratch."""
        stall_criteria, priority_rules, standards = self._load_config()
        dossiers = self._load_case_dossiers()
        ref_date = datetime.strptime(stall_criteria["reference_date"], "%Y-%m-%d")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Get all active applicants
        c = conn.cursor()
        active_statuses = ("pending", "in_review", "on_hold", "awaiting_documents")
        placeholders = ",".join("?" for _ in active_statuses)
        c.execute(f"SELECT * FROM applicants WHERE current_status IN ({placeholders})", active_statuses)
        applicants = [dict(r) for r in c.fetchall()]

        intervention_list = []

        for app in applicants:
            app_id = app["applicant_id"]
            sub_date = datetime.strptime(app["submission_date"], "%Y-%m-%d")
            days_since = (ref_date - sub_date).days
            visa_cat = app["visa_category"]
            embassy = app["embassy_id"]

            sla_days = standards.get(visa_cat, {}).get("standard_sla_days", 90)
            threshold_mult = stall_criteria["processing_time_threshold_multiplier"]
            bio_warning = stall_criteria["biometric_expiry_warning_days"]
            min_flags = stall_criteria["min_unresolved_document_flags"]
            appt_threshold = stall_criteria["appointment_wait_threshold_days"]
            quota_crit_pct = stall_criteria["quota_utilization_critical_pct"]

            stall_reasons = []

            # Check biometrics
            c.execute("SELECT * FROM biometric_submissions WHERE applicant_id = ?", (app_id,))
            bios = [dict(r) for r in c.fetchall()]
            has_bio_issue = False
            for bio in bios:
                if bio["status"] == "expired":
                    has_bio_issue = True
                    break
                expiry = datetime.strptime(bio["expiry_date"], "%Y-%m-%d")
                if (expiry - ref_date).days <= bio_warning:
                    has_bio_issue = True
                    break
            if has_bio_issue:
                stall_reasons.append("biometric_expired")

            # Check document flags
            c.execute(
                "SELECT COUNT(*) FROM document_verifications WHERE applicant_id = ? AND verification_status = 'flagged'",
                (app_id,),
            )
            num_flags = c.fetchone()[0]
            if num_flags >= min_flags:
                stall_reasons.append("document_flags_unresolved")

            # Check SLA
            if days_since > sla_days * threshold_mult:
                stall_reasons.append("sla_exceeded")

            # Check appointment backlog
            c.execute("SELECT * FROM embassy_appointments WHERE applicant_id = ?", (app_id,))
            appts = [dict(r) for r in c.fetchall()]
            has_appt_issue = False
            for appt in appts:
                if appt["status"] in ("pending", "scheduled") and appt["wait_days"] > appt_threshold:
                    has_appt_issue = True
                    break
            if has_appt_issue:
                stall_reasons.append("appointment_backlogged")

            # Check quota
            c.execute(
                "SELECT * FROM visa_quotas WHERE visa_category = ? AND embassy_id = ? AND quarter = 'Q2'",
                (visa_cat, embassy),
            )
            quota_row = c.fetchone()
            if quota_row:
                quota = dict(quota_row)
                util_pct = (quota["used_count"] / quota["allocated_quota"] * 100) if quota["allocated_quota"] > 0 else 0
                if util_pct >= quota_crit_pct:
                    stall_reasons.append("quota_critical")

            if not stall_reasons:
                continue  # Not stalled

            # Check high-priority
            dossier = dossiers.get(app_id, {})
            escalation_level = int(dossier.get("escalation_level", 0))
            sponsor_tier = dossier.get("sponsor_tier", "none")

            hp_conditions = priority_rules["high_priority_conditions"]
            is_high_priority = (
                app["priority_level"] in hp_conditions["priority_levels"]
                or escalation_level >= hp_conditions["min_escalation_level"]
                or sponsor_tier in hp_conditions["sponsor_tiers"]
            )

            if not is_high_priority:
                continue

            # Compute priority score
            base_score = priority_rules["base_scores"].get(visa_cat, 50)
            pl_mult = priority_rules["priority_level_multiplier"].get(app["priority_level"], 1.0)
            mods = priority_rules["modifiers"]

            score = base_score * pl_mult
            score += base_score * mods["escalation_multiplier"] * escalation_level
            score += days_since * mods["days_stalled_factor"]
            if "quota_critical" in stall_reasons:
                score += mods["quota_pressure_bonus"]
            if "biometric_expired" in stall_reasons:
                score += mods["biometric_expiry_bonus"]
            score += mods["document_flag_penalty"] * num_flags
            score += mods["sponsor_tier_bonus"].get(sponsor_tier, 0)

            score = round(score, 2)

            # Determine recommended action based on priority order
            action_map = priority_rules["stall_reason_action_mapping"]
            reason_order = priority_rules["stall_reason_priority_order"]
            recommended_action = "Review case"
            for reason in reason_order:
                if reason in stall_reasons:
                    recommended_action = action_map[reason]
                    break

            stall_reasons_str = "; ".join(stall_reasons)

            intervention_list.append({
                "applicant_id": app_id,
                "full_name": app["full_name"],
                "visa_category": visa_cat,
                "embassy_id": embassy,
                "priority_score": score,
                "stall_reasons": stall_reasons_str,
                "recommended_action": recommended_action,
                "days_stalled": days_since,
            })

        conn.close()

        # Sort: priority_score DESC, days_stalled DESC, applicant_id ASC
        intervention_list.sort(
            key=lambda x: (-x["priority_score"], -x["days_stalled"], x["applicant_id"])
        )

        return intervention_list

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
        ground_truth = self._compute_ground_truth()
        gt_ids = set(r["applicant_id"] for r in ground_truth)
        gt_map = {r["applicant_id"]: r for r in ground_truth}

        criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: Output file exists and has correct columns (15 pts) ──
        c1_max = 15
        max_score += c1_max
        csv_path = os.path.join(self.workspace, "intervention_list.csv")
        expected_columns = [
            "applicant_id", "full_name", "visa_category", "embassy_id",
            "priority_score", "stall_reasons", "recommended_action", "days_stalled",
        ]
        submitted_rows = []
        c1_passed = False
        c1_reason = ""
        if os.path.exists(csv_path):
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    if set(expected_columns).issubset(set(cols)):
                        submitted_rows = list(reader)
                        c1_passed = True
                    else:
                        missing = set(expected_columns) - set(cols)
                        c1_reason = f"Missing columns: {missing}"
            except Exception as e:
                c1_reason = f"Failed to parse CSV: {e}"
        else:
            c1_reason = "intervention_list.csv not found in workspace"

        c1_score = c1_max if c1_passed else 0
        total_score += c1_score
        criteria["output_file_format"] = {
            "passed": c1_passed,
            "score": c1_score,
            "max_score": c1_max,
        }
        if not c1_passed:
            criteria["output_file_format"]["reason"] = c1_reason

        # ── Criterion 2: Correct identification of stalled high-priority applicants (25 pts) ──
        c2_max = 25
        max_score += c2_max
        submitted_ids = set(r["applicant_id"] for r in submitted_rows)
        if gt_ids:
            correct_ids = submitted_ids & gt_ids
            false_positives = submitted_ids - gt_ids
            false_negatives = gt_ids - submitted_ids
            precision = len(correct_ids) / len(submitted_ids) if submitted_ids else 0
            recall = len(correct_ids) / len(gt_ids) if gt_ids else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            c2_score = round(c2_max * f1)
        else:
            c2_score = c2_max if not submitted_ids else 0
        c2_passed = c2_score == c2_max
        total_score += c2_score
        criteria["stalled_identification"] = {
            "passed": c2_passed,
            "score": c2_score,
            "max_score": c2_max,
        }
        if not c2_passed:
            reasons = []
            if 'false_positives' in dir() and false_positives:
                reasons.append(f"False positives: {len(false_positives)}")
            if 'false_negatives' in dir() and false_negatives:
                reasons.append(f"False negatives: {len(false_negatives)}")
            criteria["stalled_identification"]["reason"] = "; ".join(reasons) if reasons else "Mismatch in identified applicants"

        # ── Criterion 3: Priority score accuracy (20 pts) ──
        c3_max = 20
        max_score += c3_max
        if submitted_rows and gt_ids:
            score_matches = 0
            score_total = 0
            for row in submitted_rows:
                aid = row.get("applicant_id", "")
                if aid in gt_map:
                    score_total += 1
                    try:
                        submitted_score = float(row.get("priority_score", 0))
                        expected_score = gt_map[aid]["priority_score"]
                        if abs(submitted_score - expected_score) <= 0.5:
                            score_matches += 1
                    except (ValueError, TypeError):
                        pass
            accuracy = score_matches / score_total if score_total > 0 else 0
            c3_score = round(c3_max * accuracy)
        else:
            c3_score = 0
        c3_passed = c3_score == c3_max
        total_score += c3_score
        criteria["priority_score_accuracy"] = {
            "passed": c3_passed,
            "score": c3_score,
            "max_score": c3_max,
        }
        if not c3_passed:
            criteria["priority_score_accuracy"]["reason"] = f"Score accuracy: {score_matches}/{score_total}" if submitted_rows else "No rows to evaluate"

        # ── Criterion 4: Stall reasons correctness (15 pts) ──
        c4_max = 15
        max_score += c4_max
        if submitted_rows and gt_ids:
            reason_matches = 0
            reason_total = 0
            for row in submitted_rows:
                aid = row.get("applicant_id", "")
                if aid in gt_map:
                    reason_total += 1
                    submitted_reasons = set(r.strip() for r in row.get("stall_reasons", "").split(";") if r.strip())
                    expected_reasons = set(r.strip() for r in gt_map[aid]["stall_reasons"].split(";") if r.strip())
                    if submitted_reasons == expected_reasons:
                        reason_matches += 1
            accuracy = reason_matches / reason_total if reason_total > 0 else 0
            c4_score = round(c4_max * accuracy)
        else:
            c4_score = 0
        c4_passed = c4_score == c4_max
        total_score += c4_score
        criteria["stall_reasons_accuracy"] = {
            "passed": c4_passed,
            "score": c4_score,
            "max_score": c4_max,
        }
        if not c4_passed:
            criteria["stall_reasons_accuracy"]["reason"] = f"Reason matches: {reason_matches}/{reason_total}" if submitted_rows else "No rows"

        # ── Criterion 5: Sorting order (10 pts) ──
        c5_max = 10
        max_score += c5_max
        c5_passed = False
        c5_reason = ""
        if len(submitted_rows) >= 2:
            try:
                correctly_sorted = True
                for i in range(len(submitted_rows) - 1):
                    s1 = float(submitted_rows[i].get("priority_score", 0))
                    s2 = float(submitted_rows[i + 1].get("priority_score", 0))
                    d1 = int(submitted_rows[i].get("days_stalled", 0))
                    d2 = int(submitted_rows[i + 1].get("days_stalled", 0))
                    id1 = submitted_rows[i].get("applicant_id", "")
                    id2 = submitted_rows[i + 1].get("applicant_id", "")
                    if s1 < s2:
                        correctly_sorted = False
                        break
                    elif s1 == s2:
                        if d1 < d2:
                            correctly_sorted = False
                            break
                        elif d1 == d2:
                            if id1 > id2:
                                correctly_sorted = False
                                break
                c5_passed = correctly_sorted
                if not c5_passed:
                    c5_reason = "Rows not sorted by priority_score DESC, days_stalled DESC, applicant_id ASC"
            except (ValueError, TypeError) as e:
                c5_reason = f"Could not parse sort fields: {e}"
        elif len(submitted_rows) == 1:
            c5_passed = True
        else:
            c5_reason = "No rows to check sorting"

        c5_score = c5_max if c5_passed else 0
        total_score += c5_score
        criteria["sorting_order"] = {
            "passed": c5_passed,
            "score": c5_score,
            "max_score": c5_max,
        }
        if not c5_passed:
            criteria["sorting_order"]["reason"] = c5_reason

        # ── Criterion 6: Recommended actions accuracy (15 pts) ──
        c6_max = 15
        max_score += c6_max
        if submitted_rows and gt_ids:
            action_matches = 0
            action_total = 0
            for row in submitted_rows:
                aid = row.get("applicant_id", "")
                if aid in gt_map:
                    action_total += 1
                    if row.get("recommended_action", "").strip() == gt_map[aid]["recommended_action"]:
                        action_matches += 1
            accuracy = action_matches / action_total if action_total > 0 else 0
            c6_score = round(c6_max * accuracy)
        else:
            c6_score = 0
        c6_passed = c6_score == c6_max
        total_score += c6_score
        criteria["recommended_actions"] = {
            "passed": c6_passed,
            "score": c6_score,
            "max_score": c6_max,
        }
        if not c6_passed:
            criteria["recommended_actions"]["reason"] = f"Action matches: {action_matches}/{action_total}" if submitted_rows else "No rows"

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

        This method proves end-to-end solvability. It must:
          - Use self.tools[name](**params) to gather data (no direct DB queries).
          - Read files from self.workspace as needed.
          - Write all required deliverables to self.workspace.
          - Construct the final action string.
          - Return self.step(action).
        """
        import csv as csv_mod

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # Step 1: Load config files from workspace
        with open(os.path.join(self.workspace, "stall_criteria.json")) as f:
            stall_criteria = json.load(f)
        with open(os.path.join(self.workspace, "priority_scoring_rules.yaml")) as f:
            priority_rules = yaml.safe_load(f)
        sla_map = {}
        with open(os.path.join(self.workspace, "visa_processing_standards.csv")) as f:
            reader = csv_mod.DictReader(f)
            for row in reader:
                sla_map[row["visa_category"]] = int(row["standard_sla_days"])

        ref_date = datetime.strptime(stall_criteria["reference_date"], "%Y-%m-%d")

        # Step 2: Load case dossiers from workspace
        dossiers = {}
        for fname in sorted(os.listdir(self.workspace)):
            if not fname.startswith("case_dossier_batch_"):
                continue
            fpath = os.path.join(self.workspace, fname)
            if fname.endswith(".json"):
                with open(fpath) as f:
                    for rec in json.load(f):
                        dossiers[rec["applicant_id"]] = rec
            elif fname.endswith(".csv"):
                with open(fpath) as f:
                    for rec in csv_mod.DictReader(f):
                        rec["escalation_level"] = int(rec["escalation_level"])
                        if rec.get("special_circumstances") == "":
                            rec["special_circumstances"] = None
                        dossiers[rec["applicant_id"]] = rec
            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    content = f.read()
                current = {}
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("--- Applicant:"):
                        if current.get("applicant_id"):
                            dossiers[current["applicant_id"]] = current
                        app_id = line.split("--- Applicant:")[1].strip().rstrip(" ---")
                        current = {"applicant_id": app_id}
                    elif line.startswith("Escalation Level:"):
                        current["escalation_level"] = int(line.split(":")[1].strip())
                    elif line.startswith("Sponsor Tier:"):
                        current["sponsor_tier"] = line.split(":")[1].strip()
                    elif line.startswith("Special Circumstances:"):
                        val = line.split(":", 1)[1].strip()
                        current["special_circumstances"] = None if val == "None" else val
                    elif line.startswith("Last Officer Contact:"):
                        current["last_officer_contact"] = line.split(":")[1].strip()
                if current.get("applicant_id"):
                    dossiers[current["applicant_id"]] = current
            elif fname.endswith(".yaml"):
                with open(fpath) as f:
                    records = yaml.safe_load(f)
                if records:
                    for rec in records:
                        dossiers[rec["applicant_id"]] = rec
            elif fname.endswith(".md"):
                with open(fpath) as f:
                    content = f.read()
                current = {}
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("## APP_"):
                        if current.get("applicant_id"):
                            dossiers[current["applicant_id"]] = current
                        current = {"applicant_id": line[3:].strip()}
                    elif line.startswith("| Escalation Level |"):
                        current["escalation_level"] = int(line.split("|")[2].strip())
                    elif line.startswith("| Sponsor Tier |"):
                        current["sponsor_tier"] = line.split("|")[2].strip()
                    elif line.startswith("| Special Circumstances |"):
                        val = line.split("|")[2].strip()
                        current["special_circumstances"] = None if val == "None" else val
                    elif line.startswith("| Last Officer Contact |"):
                        current["last_officer_contact"] = line.split("|")[2].strip()
                if current.get("applicant_id"):
                    dossiers[current["applicant_id"]] = current

        # Step 3: Gather all active applicants via tool calls (paginated)
        active_statuses = ["pending", "in_review", "on_hold", "awaiting_documents"]
        all_active = []
        for status in active_statuses:
            page = 1
            while True:
                result = call_tool("search_applicants", status=status, page=page, page_size=20)
                all_active.extend(result["results"])
                if page >= result["total_pages"]:
                    break
                page += 1

        # Step 4: For each active applicant, check stall conditions and priority
        intervention_list = []
        threshold_mult = stall_criteria["processing_time_threshold_multiplier"]
        bio_warning = stall_criteria["biometric_expiry_warning_days"]
        min_flags = stall_criteria["min_unresolved_document_flags"]
        appt_threshold = stall_criteria["appointment_wait_threshold_days"]
        quota_crit_pct = stall_criteria["quota_utilization_critical_pct"]

        # Cache quota lookups to avoid redundant calls
        quota_cache = {}

        for app in all_active:
            app_id = app["applicant_id"]
            visa_cat = app["visa_category"]
            embassy = app["embassy_id"]
            sub_date = datetime.strptime(app["submission_date"], "%Y-%m-%d")
            days_since = (ref_date - sub_date).days

            sla_days = sla_map.get(visa_cat, 90)
            stall_reasons = []

            # Check biometrics
            bio_result = call_tool("get_biometric_status", applicant_id=app_id)
            has_bio_issue = False
            for bio in bio_result["biometrics"]:
                if bio["status"] == "expired":
                    has_bio_issue = True
                    break
                expiry = datetime.strptime(bio["expiry_date"], "%Y-%m-%d")
                if (expiry - ref_date).days <= bio_warning:
                    has_bio_issue = True
                    break
            if has_bio_issue:
                stall_reasons.append("biometric_expired")

            # Check document flags
            doc_result = call_tool("get_document_flags", applicant_id=app_id)
            num_flags = sum(1 for d in doc_result["documents"] if d["verification_status"] == "flagged")
            if num_flags >= min_flags:
                stall_reasons.append("document_flags_unresolved")

            # Check SLA
            if days_since > sla_days * threshold_mult:
                stall_reasons.append("sla_exceeded")

            # Check appointments
            appt_result = call_tool("get_appointment_history", applicant_id=app_id)
            has_appt_issue = False
            for appt in appt_result["appointments"]:
                if appt["status"] in ("pending", "scheduled") and appt["wait_days"] > appt_threshold:
                    has_appt_issue = True
                    break
            if has_appt_issue:
                stall_reasons.append("appointment_backlogged")

            # Check quota
            quota_key = (visa_cat, embassy)
            if quota_key not in quota_cache:
                quota_cache[quota_key] = call_tool("get_visa_quota", visa_category=visa_cat, embassy_id=embassy, quarter="Q2")
            quota_info = quota_cache[quota_key]
            if "utilization_pct" in quota_info and quota_info["utilization_pct"] >= quota_crit_pct:
                stall_reasons.append("quota_critical")

            if not stall_reasons:
                continue

            # Check high-priority
            dossier = dossiers.get(app_id, {})
            escalation_level = int(dossier.get("escalation_level", 0))
            sponsor_tier = dossier.get("sponsor_tier", "none")

            hp_conditions = priority_rules["high_priority_conditions"]
            is_high_priority = (
                app["priority_level"] in hp_conditions["priority_levels"]
                or escalation_level >= hp_conditions["min_escalation_level"]
                or sponsor_tier in hp_conditions["sponsor_tiers"]
            )

            if not is_high_priority:
                continue

            # Compute priority score
            base_score = priority_rules["base_scores"].get(visa_cat, 50)
            pl_mult = priority_rules["priority_level_multiplier"].get(app["priority_level"], 1.0)
            mods = priority_rules["modifiers"]

            score = base_score * pl_mult
            score += base_score * mods["escalation_multiplier"] * escalation_level
            score += days_since * mods["days_stalled_factor"]
            if "quota_critical" in stall_reasons:
                score += mods["quota_pressure_bonus"]
            if "biometric_expired" in stall_reasons:
                score += mods["biometric_expiry_bonus"]
            score += mods["document_flag_penalty"] * num_flags
            score += mods["sponsor_tier_bonus"].get(sponsor_tier, 0)

            score = round(score, 2)

            # Determine recommended action
            action_map = priority_rules["stall_reason_action_mapping"]
            reason_order = priority_rules["stall_reason_priority_order"]
            recommended_action = "Review case"
            for reason in reason_order:
                if reason in stall_reasons:
                    recommended_action = action_map[reason]
                    break

            intervention_list.append({
                "applicant_id": app_id,
                "full_name": app["full_name"],
                "visa_category": visa_cat,
                "embassy_id": embassy,
                "priority_score": score,
                "stall_reasons": "; ".join(stall_reasons),
                "recommended_action": recommended_action,
                "days_stalled": days_since,
            })

        # Sort
        intervention_list.sort(
            key=lambda x: (-x["priority_score"], -x["days_stalled"], x["applicant_id"])
        )

        # Write output CSV
        csv_path = os.path.join(self.workspace, "intervention_list.csv")
        fieldnames = [
            "applicant_id", "full_name", "visa_category", "embassy_id",
            "priority_score", "stall_reasons", "recommended_action", "days_stalled",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(intervention_list)

        # Build action string (summary)
        action_lines = [
            f"Intervention list generated with {len(intervention_list)} stalled high-priority applications.",
            "The list has been saved to intervention_list.csv, sorted by priority_score descending, "
            "then days_stalled descending, then applicant_id ascending.",
            "",
            "Top entries:",
        ]
        for entry in intervention_list[:5]:
            action_lines.append(
                f"  {entry['applicant_id']} ({entry['full_name']}): "
                f"score={entry['priority_score']}, stall_reasons={entry['stall_reasons']}, "
                f"action={entry['recommended_action']}"
            )
        if len(intervention_list) > 5:
            action_lines.append(f"  ... and {len(intervention_list) - 5} more entries.")

        action = "\n".join(action_lines)

        print(f"[verify] Tool calls made: {tool_call_count}")
        return self.step(action)
