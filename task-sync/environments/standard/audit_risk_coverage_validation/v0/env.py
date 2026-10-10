"""
Environment for audit coverage gap analysis task.
Provides tools to query audit areas, checklist items, prior findings, and GL entries.
Agent must cross-reference tool results with workspace files to identify coverage gaps.
"""

import sqlite3
import os
import json
import csv
import glob
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
    # Tool methods
    # -----------------------------------------------------------------------

    @tool(
        description="List audit areas with pagination. Returns area_id, area_name, department, and inherent_risk for each area.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20)"
                }
            },
            "required": ["page", "page_size"]
        }
    )
    def list_audit_areas(self, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM audit_areas")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT area_id, area_name, department, inherent_risk FROM audit_areas "
            "ORDER BY area_id LIMIT ? OFFSET ?",
            (page_size, offset)
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "total_count": total,
            "page": page,
            "page_size": page_size,
            "areas": [
                {"area_id": r[0], "area_name": r[1], "department": r[2], "inherent_risk": r[3]}
                for r in rows
            ]
        }

    @tool(
        description="Get checklist items for a specific audit area. Returns procedure types, completion status, and assignments.",
        parameters={
            "type": "object",
            "properties": {
                "area_id": {
                    "type": "string",
                    "description": "The audit area ID (e.g. AREA_0001)"
                }
            },
            "required": ["area_id"]
        }
    )
    def get_checklist_items(self, area_id: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT item_id, procedure_type, procedure_description, completion_status, assigned_to, due_date "
            "FROM checklist_items WHERE area_id = ? ORDER BY item_id",
            (area_id,)
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "area_id": area_id,
            "item_count": len(rows),
            "items": [
                {
                    "item_id": r[0],
                    "procedure_type": r[1],
                    "procedure_description": r[2],
                    "completion_status": r[3],
                    "assigned_to": r[4],
                    "due_date": r[5],
                }
                for r in rows
            ]
        }

    @tool(
        description="Get prior year audit findings for a specific area. Returns finding severity, remediation status, and management response.",
        parameters={
            "type": "object",
            "properties": {
                "area_id": {
                    "type": "string",
                    "description": "The audit area ID (e.g. AREA_0001)"
                }
            },
            "required": ["area_id"]
        }
    )
    def get_prior_findings(self, area_id: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT finding_id, finding_year, severity, finding_description, remediation_status, management_response "
            "FROM prior_year_findings WHERE area_id = ? ORDER BY finding_id",
            (area_id,)
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "area_id": area_id,
            "finding_count": len(rows),
            "findings": [
                {
                    "finding_id": r[0],
                    "finding_year": r[1],
                    "severity": r[2],
                    "finding_description": r[3],
                    "remediation_status": r[4],
                    "management_response": r[5],
                }
                for r in rows
            ]
        }

    @tool(
        description="Query GL entry summary for a specific audit area. Returns total amount, entry count, and individual entries.",
        parameters={
            "type": "object",
            "properties": {
                "area_id": {
                    "type": "string",
                    "description": "The audit area ID (e.g. AREA_0001)"
                }
            },
            "required": ["area_id"]
        }
    )
    def query_gl_summary(self, area_id: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT entry_id, account_code, account_name, amount, entry_date, memo "
            "FROM gl_entries WHERE area_id = ? ORDER BY entry_date",
            (area_id,)
        )
        rows = cur.fetchall()
        conn.close()
        total_amount = sum(r[3] for r in rows)
        return {
            "area_id": area_id,
            "entry_count": len(rows),
            "total_amount": round(total_amount, 2),
            "entries": [
                {
                    "entry_id": r[0],
                    "account_code": r[1],
                    "account_name": r[2],
                    "amount": r[3],
                    "entry_date": r[4],
                    "memo": r[5],
                }
                for r in rows
            ]
        }

    @tool(
        description="Get area details including full description for a specific audit area.",
        parameters={
            "type": "object",
            "properties": {
                "area_id": {
                    "type": "string",
                    "description": "The audit area ID (e.g. AREA_0001)"
                }
            },
            "required": ["area_id"]
        }
    )
    def get_area_details(self, area_id: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT area_id, area_name, department, inherent_risk, description "
            "FROM audit_areas WHERE area_id = ?",
            (area_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Area {area_id} not found"}
        return {
            "area_id": row[0],
            "area_name": row[1],
            "department": row[2],
            "inherent_risk": row[3],
            "description": row[4],
        }

    @tool(
        description="Search for audit areas by department. Returns areas belonging to the specified department.",
        parameters={
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": "Department name to filter by"
                }
            },
            "required": ["department"]
        }
    )
    def search_areas_by_department(self, department: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT area_id, area_name, inherent_risk FROM audit_areas WHERE department = ? ORDER BY area_id",
            (department,)
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "department": department,
            "count": len(rows),
            "areas": [
                {"area_id": r[0], "area_name": r[1], "inherent_risk": r[2]}
                for r in rows
            ]
        }

    # -----------------------------------------------------------------------
    # Ground truth computation (used by step and verify)
    # -----------------------------------------------------------------------

    def _load_workspace_config(self):
        """Load risk scoring policy, materiality thresholds, and required procedures from workspace."""
        import yaml

        with open(os.path.join(self.workspace, "risk_scoring_policy.yaml")) as f:
            risk_policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "materiality_thresholds.json")) as f:
            materiality = json.load(f)
        with open(os.path.join(self.workspace, "required_procedures.yaml")) as f:
            req_procs = yaml.safe_load(f)

        return risk_policy, materiality, req_procs

    def _parse_support_docs(self):
        """Parse all client support document files to determine coverage per area."""
        coverage = {}  # area_id -> list of {quality, filename}

        support_files = []
        for ext in ["*.txt", "*.csv", "*.json", "*.md"]:
            support_files.extend(glob.glob(os.path.join(self.workspace, f"client_support_*{ext}")))

        for fpath in support_files:
            fname = os.path.basename(fpath)
            if fpath.endswith(".txt"):
                self._parse_txt_support(fpath, fname, coverage)
            elif fpath.endswith(".csv"):
                self._parse_csv_support(fpath, fname, coverage)
            elif fpath.endswith(".json"):
                self._parse_json_support(fpath, fname, coverage)
            elif fpath.endswith(".md"):
                self._parse_md_support(fpath, fname, coverage)

        return coverage

    def _parse_txt_support(self, fpath, fname, coverage):
        with open(fpath) as f:
            content = f.read()
        current_area = None
        current_quality = None
        for line in content.split("\n"):
            if line.startswith("Audit Area: "):
                parts = line.replace("Audit Area: ", "").split(" (")
                current_area = parts[0].strip()
            elif line.startswith("Coverage Quality: "):
                current_quality = line.replace("Coverage Quality: ", "").strip()
                if current_area:
                    coverage.setdefault(current_area, []).append(
                        {"quality": current_quality, "filename": fname}
                    )

    def _parse_csv_support(self, fpath, fname, coverage):
        with open(fpath, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                aid = row.get("area_id", "").strip()
                quality = row.get("coverage_quality", "").strip()
                if aid:
                    coverage.setdefault(aid, []).append(
                        {"quality": quality, "filename": fname}
                    )

    def _parse_json_support(self, fpath, fname, coverage):
        with open(fpath) as f:
            data = json.load(f)
        for rec in data.get("support_evidence", []):
            aid = rec.get("area_id", "").strip()
            quality = rec.get("coverage_quality", "").strip()
            if aid:
                coverage.setdefault(aid, []).append(
                    {"quality": quality, "filename": fname}
                )

    def _parse_md_support(self, fpath, fname, coverage):
        with open(fpath) as f:
            content = f.read()
        current_area = None
        for line in content.split("\n"):
            if line.startswith("## "):
                # Format: ## AREA_XXXX - Name
                parts = line[3:].strip().split(" - ", 1)
                current_area = parts[0].strip()
            elif "Coverage Quality" in line and current_area:
                quality = line.split(":")[-1].strip().strip("*")
                coverage.setdefault(current_area, []).append(
                    {"quality": quality, "filename": fname}
                )

    def _compute_ground_truth(self):
        """
        Compute the complete ground truth gap analysis.
        Returns:
            high_risk_areas: set of area_ids that are composite high-risk
            all_gaps: list of gap dicts
            area_risk_scores: dict of area_id -> {score, composite_risk}
        """
        risk_policy, materiality, req_procs = self._load_workspace_config()
        support_coverage = self._parse_support_docs()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Load all areas
        cur.execute("SELECT * FROM audit_areas ORDER BY area_id")
        areas = [dict(r) for r in cur.fetchall()]

        # Load all checklist items grouped by area
        cur.execute("SELECT * FROM checklist_items ORDER BY area_id, item_id")
        all_checklists = {}
        for row in cur.fetchall():
            row = dict(row)
            all_checklists.setdefault(row["area_id"], []).append(row)

        # Load all prior findings grouped by area
        cur.execute("SELECT * FROM prior_year_findings ORDER BY area_id")
        all_findings = {}
        for row in cur.fetchall():
            row = dict(row)
            all_findings.setdefault(row["area_id"], []).append(row)

        # Load GL totals per area
        cur.execute("SELECT area_id, SUM(amount) as total_amount FROM gl_entries GROUP BY area_id")
        gl_totals = {row["area_id"]: row["total_amount"] for row in cur.fetchall()}

        conn.close()

        # Compute composite risk scores
        inherent_points = risk_policy["inherent_risk_points"]
        finding_adjustments = risk_policy["prior_finding_adjustments"]
        mat_points = risk_policy["materiality_exceeded_points"]
        no_support_points = risk_policy["no_support_docs_points"]
        thresholds = risk_policy["composite_risk_thresholds"]

        area_risk_scores = {}
        high_risk_areas = set()

        for area in areas:
            aid = area["area_id"]
            dept = area["department"]
            score = inherent_points.get(area["inherent_risk"], 0)

            # Prior finding adjustments
            findings = all_findings.get(aid, [])
            for adj in finding_adjustments:
                for f in findings:
                    if (f["severity"] == adj["severity"]
                            and f["remediation_status"] not in adj["remediation_not_in"]):
                        score += adj["points"]
                        break  # only count once per severity level

            # Materiality check
            mat_threshold = materiality.get(dept, 500000)
            gl_total = gl_totals.get(aid, 0)
            if gl_total > mat_threshold:
                score += mat_points

            # Support doc check
            if aid not in support_coverage:
                score += no_support_points

            # Determine composite risk
            if score >= thresholds["High"]:
                composite = "High"
                high_risk_areas.add(aid)
            elif score >= thresholds["Medium"]:
                composite = "Medium"
            else:
                composite = "Low"

            area_risk_scores[aid] = {
                "score": score,
                "composite_risk": composite,
                "area_name": area["area_name"],
                "department": dept,
                "inherent_risk": area["inherent_risk"],
                "gl_total": gl_total,
                "materiality_threshold": mat_threshold,
            }

        # Identify gaps for high-risk areas
        all_gaps = []

        for aid in sorted(high_risk_areas):
            area_info = area_risk_scores[aid]
            composite = area_info["composite_risk"]

            # 1. Procedure gaps
            required = set(req_procs.get(composite, []))
            existing_procs = set()
            if aid in all_checklists:
                for item in all_checklists[aid]:
                    existing_procs.add(item["procedure_type"])
            missing_procs = required - existing_procs
            for proc in sorted(missing_procs):
                all_gaps.append({
                    "area_id": aid,
                    "area_name": area_info["area_name"],
                    "composite_risk_level": composite,
                    "gap_type": "PROCEDURE_GAP",
                    "gap_description": f"Missing required procedure: {proc}",
                    "severity": "High",
                    "recommendation": f"Add {proc} procedure to audit program for {aid}",
                })

            # 2. Unremediated finding gaps
            findings = all_findings.get(aid, [])
            for f in findings:
                if f["severity"] in ("Critical", "High") and f["remediation_status"] not in ("Remediated", "Not Applicable"):
                    all_gaps.append({
                        "area_id": aid,
                        "area_name": area_info["area_name"],
                        "composite_risk_level": composite,
                        "gap_type": "UNREMEDIATED_FINDING",
                        "gap_description": f"Finding {f['finding_id']} ({f['severity']}) status: {f['remediation_status']}",
                        "severity": "Critical" if f["severity"] == "Critical" else "High",
                        "recommendation": f"Perform follow-up procedures for finding {f['finding_id']}",
                    })

            # 3. Support deficiency gaps
            area_support = support_coverage.get(aid, [])
            if not area_support:
                all_gaps.append({
                    "area_id": aid,
                    "area_name": area_info["area_name"],
                    "composite_risk_level": composite,
                    "gap_type": "SUPPORT_DEFICIENCY",
                    "gap_description": "No client support documents on file",
                    "severity": "High",
                    "recommendation": f"Request client support documentation for {aid}",
                })
            else:
                # Check if all support is Limited or Partial
                qualities = [s["quality"] for s in area_support]
                if all(q in ("Limited", "Partial") for q in qualities):
                    all_gaps.append({
                        "area_id": aid,
                        "area_name": area_info["area_name"],
                        "composite_risk_level": composite,
                        "gap_type": "SUPPORT_DEFICIENCY",
                        "gap_description": f"Support documentation quality insufficient: {', '.join(qualities)}",
                        "severity": "Medium",
                        "recommendation": f"Request additional or higher-quality documentation for {aid}",
                    })

            # 4. Materiality untested gaps
            gl_total = area_info["gl_total"]
            mat_threshold = area_info["materiality_threshold"]
            if gl_total > mat_threshold:
                if "detail_testing" not in existing_procs:
                    all_gaps.append({
                        "area_id": aid,
                        "area_name": area_info["area_name"],
                        "composite_risk_level": composite,
                        "gap_type": "MATERIALITY_UNTESTED",
                        "gap_description": f"GL total {gl_total:.2f} exceeds materiality {mat_threshold:.2f} but no detail testing",
                        "severity": "High",
                        "recommendation": f"Add detail_testing procedure for {aid} given material GL activity",
                    })

        # Sort gaps: by area_id, then gap_type
        all_gaps.sort(key=lambda g: (g["area_id"], g["gap_type"]))

        return high_risk_areas, all_gaps, area_risk_scores

    # -----------------------------------------------------------------------
    # Step: evaluate
    # -----------------------------------------------------------------------

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        high_risk_areas, ground_truth_gaps, area_risk_scores = self._compute_ground_truth()

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ---- Criterion 1: Output file exists with correct columns (10 pts) ----
        max_score += 10
        report_path = os.path.join(self.workspace, "coverage_gap_report.csv")
        required_cols = {"area_id", "area_name", "composite_risk_level", "gap_type",
                         "gap_description", "severity", "recommendation"}
        file_ok = False
        report_rows = []
        if os.path.exists(report_path):
            try:
                with open(report_path, newline="") as f:
                    reader = csv.DictReader(f)
                    headers = set(reader.fieldnames) if reader.fieldnames else set()
                    if required_cols.issubset(headers):
                        report_rows = list(reader)
                        file_ok = True
            except Exception:
                pass

        if file_ok:
            eval_criteria["output_format"] = {
                "passed": True, "score": 10, "max_score": 10
            }
            total_score += 10
        else:
            eval_criteria["output_format"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": f"coverage_gap_report.csv missing or wrong columns. Expected: {sorted(required_cols)}"
            }

        # ---- Criterion 2: High-risk area identification (20 pts) ----
        max_score += 20
        reported_hr_areas = set()
        for row in report_rows:
            reported_hr_areas.add(row.get("area_id", "").strip())

        # Also check action string for mentions of high-risk areas
        if high_risk_areas:
            correct_hr = reported_hr_areas & high_risk_areas
            precision = len(correct_hr) / len(reported_hr_areas) if reported_hr_areas else 0
            recall = len(correct_hr) / len(high_risk_areas)
            # Weight recall more heavily
            hr_score = round(20 * (0.3 * precision + 0.7 * recall))
        else:
            hr_score = 20 if not reported_hr_areas else 0

        eval_criteria["high_risk_identification"] = {
            "passed": hr_score >= 16,
            "score": hr_score,
            "max_score": 20,
            "reason": f"Expected {len(high_risk_areas)} high-risk areas, report covers {len(reported_hr_areas & high_risk_areas)} correctly" if hr_score < 20 else ""
        }
        total_score += hr_score

        # ---- Criterion 3: Procedure gap detection (20 pts) ----
        max_score += 20
        gt_proc_gaps = {(g["area_id"], g["gap_description"])
                        for g in ground_truth_gaps if g["gap_type"] == "PROCEDURE_GAP"}
        reported_proc_gaps = set()
        for row in report_rows:
            if row.get("gap_type", "").strip() == "PROCEDURE_GAP":
                reported_proc_gaps.add((row.get("area_id", "").strip(),
                                        row.get("gap_description", "").strip()))

        if gt_proc_gaps:
            # Fuzzy matching: check if the reported gap mentions the same procedure
            matched = 0
            for gt_aid, gt_desc in gt_proc_gaps:
                proc_name = gt_desc.replace("Missing required procedure: ", "")
                for r_aid, r_desc in reported_proc_gaps:
                    if r_aid == gt_aid and proc_name in r_desc:
                        matched += 1
                        break
            proc_score = round(20 * matched / len(gt_proc_gaps))
        else:
            proc_score = 20 if not reported_proc_gaps else 15

        eval_criteria["procedure_gap_detection"] = {
            "passed": proc_score >= 16,
            "score": proc_score,
            "max_score": 20,
            "reason": f"Matched {matched if gt_proc_gaps else 0}/{len(gt_proc_gaps)} procedure gaps" if proc_score < 20 else ""
        }
        total_score += proc_score

        # ---- Criterion 4: Unremediated finding gaps (15 pts) ----
        max_score += 15
        gt_finding_gaps = {(g["area_id"], g["gap_description"].split("(")[0].strip().split()[-1] if "(" in g["gap_description"] else "")
                           for g in ground_truth_gaps if g["gap_type"] == "UNREMEDIATED_FINDING"}
        # Extract finding IDs from ground truth
        gt_finding_gap_ids = set()
        for g in ground_truth_gaps:
            if g["gap_type"] == "UNREMEDIATED_FINDING":
                # Extract finding_id from description
                desc = g["gap_description"]
                fid = desc.split(" ")[1] if len(desc.split(" ")) > 1 else ""
                gt_finding_gap_ids.add((g["area_id"], fid))

        reported_finding_gaps = set()
        for row in report_rows:
            if row.get("gap_type", "").strip() == "UNREMEDIATED_FINDING":
                reported_finding_gaps.add(row.get("area_id", "").strip())

        gt_finding_areas = {g[0] for g in gt_finding_gap_ids}
        if gt_finding_areas:
            matched_finding = len(reported_finding_gaps & gt_finding_areas)
            finding_score = round(15 * matched_finding / len(gt_finding_areas))
        else:
            finding_score = 15 if not reported_finding_gaps else 12

        eval_criteria["unremediated_finding_gaps"] = {
            "passed": finding_score >= 12,
            "score": finding_score,
            "max_score": 15,
            "reason": f"Matched {matched_finding if gt_finding_areas else 0}/{len(gt_finding_areas)} areas with finding gaps" if finding_score < 15 else ""
        }
        total_score += finding_score

        # ---- Criterion 5: Support deficiency gaps (15 pts) ----
        max_score += 15
        gt_support_gaps = {g["area_id"] for g in ground_truth_gaps
                          if g["gap_type"] == "SUPPORT_DEFICIENCY"}
        reported_support_gaps = set()
        for row in report_rows:
            if row.get("gap_type", "").strip() == "SUPPORT_DEFICIENCY":
                reported_support_gaps.add(row.get("area_id", "").strip())

        if gt_support_gaps:
            matched_support = len(reported_support_gaps & gt_support_gaps)
            support_score = round(15 * matched_support / len(gt_support_gaps))
        else:
            support_score = 15 if not reported_support_gaps else 12

        eval_criteria["support_deficiency_detection"] = {
            "passed": support_score >= 12,
            "score": support_score,
            "max_score": 15,
            "reason": f"Matched {matched_support if gt_support_gaps else 0}/{len(gt_support_gaps)} support deficiency gaps" if support_score < 15 else ""
        }
        total_score += support_score

        # ---- Criterion 6: Materiality untested gaps (10 pts) ----
        max_score += 10
        gt_mat_gaps = {g["area_id"] for g in ground_truth_gaps
                       if g["gap_type"] == "MATERIALITY_UNTESTED"}
        reported_mat_gaps = set()
        for row in report_rows:
            if row.get("gap_type", "").strip() == "MATERIALITY_UNTESTED":
                reported_mat_gaps.add(row.get("area_id", "").strip())

        if gt_mat_gaps:
            matched_mat = len(reported_mat_gaps & gt_mat_gaps)
            mat_score = round(10 * matched_mat / len(gt_mat_gaps))
        else:
            mat_score = 10 if not reported_mat_gaps else 8

        eval_criteria["materiality_gap_detection"] = {
            "passed": mat_score >= 8,
            "score": mat_score,
            "max_score": 10,
            "reason": f"Matched {matched_mat if gt_mat_gaps else 0}/{len(gt_mat_gaps)} materiality gaps" if mat_score < 10 else ""
        }
        total_score += mat_score

        # ---- Criterion 7: Executive summary in response (10 pts) ----
        max_score += 10
        summary_score = 0
        action_lower = action.lower()
        # Check for key summary elements
        has_total_gaps = str(len(ground_truth_gaps)) in action
        has_hr_count = str(len(high_risk_areas)) in action

        # Check gap type counts in action
        proc_gap_count = sum(1 for g in ground_truth_gaps if g["gap_type"] == "PROCEDURE_GAP")
        finding_gap_count = sum(1 for g in ground_truth_gaps if g["gap_type"] == "UNREMEDIATED_FINDING")
        support_gap_count = sum(1 for g in ground_truth_gaps if g["gap_type"] == "SUPPORT_DEFICIENCY")
        mat_gap_count = sum(1 for g in ground_truth_gaps if g["gap_type"] == "MATERIALITY_UNTESTED")

        count_checks = 0
        if has_total_gaps:
            count_checks += 1
        if has_hr_count:
            count_checks += 1
        if str(proc_gap_count) in action:
            count_checks += 1
        if str(finding_gap_count) in action:
            count_checks += 1

        if count_checks >= 3:
            summary_score = 10
        elif count_checks >= 2:
            summary_score = 7
        elif count_checks >= 1:
            summary_score = 4
        else:
            summary_score = 0

        eval_criteria["executive_summary"] = {
            "passed": summary_score >= 7,
            "score": summary_score,
            "max_score": 10,
            "reason": f"Found {count_checks}/4 key statistics in response" if summary_score < 10 else ""
        }
        total_score += summary_score

        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

        return reward, info

    # -----------------------------------------------------------------------
    # Verify: prove solvability
    # -----------------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml

        # --- Step 1: Read workspace config files ---
        with open(os.path.join(self.workspace, "risk_scoring_policy.yaml")) as f:
            risk_policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "materiality_thresholds.json")) as f:
            materiality = json.load(f)
        with open(os.path.join(self.workspace, "required_procedures.yaml")) as f:
            req_procs = yaml.safe_load(f)

        # --- Step 2: List all audit areas via tool ---
        all_areas = []
        page = 1
        while True:
            result = self.tools["list_audit_areas"](page=page, page_size=20)
            all_areas.extend(result["areas"])
            if page * 20 >= result["total_count"]:
                break
            page += 1

        # --- Step 3: Parse support documents from workspace ---
        support_coverage = {}
        support_files = []
        for ext in ["*.txt", "*.csv", "*.json", "*.md"]:
            import glob as globmod
            support_files.extend(globmod.glob(os.path.join(self.workspace, f"client_support_*{ext}")))

        for fpath in support_files:
            fname = os.path.basename(fpath)
            if fpath.endswith(".csv"):
                with open(fpath, newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        aid = row.get("area_id", "").strip()
                        quality = row.get("coverage_quality", "").strip()
                        if aid:
                            support_coverage.setdefault(aid, []).append({"quality": quality, "filename": fname})
            elif fpath.endswith(".json"):
                with open(fpath) as f:
                    data = json.load(f)
                for rec in data.get("support_evidence", []):
                    aid = rec.get("area_id", "").strip()
                    quality = rec.get("coverage_quality", "").strip()
                    if aid:
                        support_coverage.setdefault(aid, []).append({"quality": quality, "filename": fname})
            elif fpath.endswith(".txt"):
                with open(fpath) as f:
                    content = f.read()
                current_area = None
                for line in content.split("\n"):
                    if line.startswith("Audit Area: "):
                        parts = line.replace("Audit Area: ", "").split(" (")
                        current_area = parts[0].strip()
                    elif line.startswith("Coverage Quality: ") and current_area:
                        quality = line.replace("Coverage Quality: ", "").strip()
                        support_coverage.setdefault(current_area, []).append({"quality": quality, "filename": fname})
            elif fpath.endswith(".md"):
                with open(fpath) as f:
                    content = f.read()
                current_area = None
                for line in content.split("\n"):
                    if line.startswith("## "):
                        parts = line[3:].strip().split(" - ", 1)
                        current_area = parts[0].strip()
                    elif "Coverage Quality" in line and current_area:
                        quality = line.split(":")[-1].strip().strip("*")
                        support_coverage.setdefault(current_area, []).append({"quality": quality, "filename": fname})

        # --- Step 4: For each area, gather findings and GL data via tools ---
        area_data = {}
        for area in all_areas:
            aid = area["area_id"]
            findings_result = self.tools["get_prior_findings"](area_id=aid)
            gl_result = self.tools["query_gl_summary"](area_id=aid)
            checklist_result = self.tools["get_checklist_items"](area_id=aid)
            area_data[aid] = {
                "area_name": area["area_name"],
                "department": area["department"],
                "inherent_risk": area["inherent_risk"],
                "findings": findings_result["findings"],
                "gl_total": gl_result["total_amount"],
                "checklist_items": checklist_result["items"],
            }

        # --- Step 5: Compute composite risk scores ---
        inherent_points = risk_policy["inherent_risk_points"]
        finding_adjustments = risk_policy["prior_finding_adjustments"]
        mat_points = risk_policy["materiality_exceeded_points"]
        no_support_points = risk_policy["no_support_docs_points"]
        thresholds = risk_policy["composite_risk_thresholds"]

        high_risk_areas = set()
        area_risk_info = {}

        for aid, data in area_data.items():
            score = inherent_points.get(data["inherent_risk"], 0)

            for adj in finding_adjustments:
                for f in data["findings"]:
                    if f["severity"] == adj["severity"] and f["remediation_status"] not in adj["remediation_not_in"]:
                        score += adj["points"]
                        break

            dept = data["department"]
            mat_threshold = materiality.get(dept, 500000)
            if data["gl_total"] > mat_threshold:
                score += mat_points

            if aid not in support_coverage:
                score += no_support_points

            if score >= thresholds["High"]:
                composite = "High"
                high_risk_areas.add(aid)
            elif score >= thresholds["Medium"]:
                composite = "Medium"
            else:
                composite = "Low"

            area_risk_info[aid] = {
                "composite_risk": composite,
                "score": score,
                "mat_threshold": mat_threshold,
            }

        # --- Step 6: Identify all gaps for high-risk areas ---
        all_gaps = []

        for aid in sorted(high_risk_areas):
            data = area_data[aid]
            composite = area_risk_info[aid]["composite_risk"]
            mat_threshold = area_risk_info[aid]["mat_threshold"]

            # Procedure gaps
            required = set(req_procs.get(composite, []))
            existing_procs = {item["procedure_type"] for item in data["checklist_items"]}
            missing_procs = required - existing_procs
            for proc in sorted(missing_procs):
                all_gaps.append({
                    "area_id": aid,
                    "area_name": data["area_name"],
                    "composite_risk_level": composite,
                    "gap_type": "PROCEDURE_GAP",
                    "gap_description": f"Missing required procedure: {proc}",
                    "severity": "High",
                    "recommendation": f"Add {proc} procedure to audit program for {aid}",
                })

            # Unremediated finding gaps
            for f in data["findings"]:
                if f["severity"] in ("Critical", "High") and f["remediation_status"] not in ("Remediated", "Not Applicable"):
                    all_gaps.append({
                        "area_id": aid,
                        "area_name": data["area_name"],
                        "composite_risk_level": composite,
                        "gap_type": "UNREMEDIATED_FINDING",
                        "gap_description": f"Finding {f['finding_id']} ({f['severity']}) status: {f['remediation_status']}",
                        "severity": "Critical" if f["severity"] == "Critical" else "High",
                        "recommendation": f"Perform follow-up procedures for finding {f['finding_id']}",
                    })

            # Support deficiency gaps
            area_support = support_coverage.get(aid, [])
            if not area_support:
                all_gaps.append({
                    "area_id": aid,
                    "area_name": data["area_name"],
                    "composite_risk_level": composite,
                    "gap_type": "SUPPORT_DEFICIENCY",
                    "gap_description": "No client support documents on file",
                    "severity": "High",
                    "recommendation": f"Request client support documentation for {aid}",
                })
            else:
                qualities = [s["quality"] for s in area_support]
                if all(q in ("Limited", "Partial") for q in qualities):
                    all_gaps.append({
                        "area_id": aid,
                        "area_name": data["area_name"],
                        "composite_risk_level": composite,
                        "gap_type": "SUPPORT_DEFICIENCY",
                        "gap_description": f"Support documentation quality insufficient: {', '.join(qualities)}",
                        "severity": "Medium",
                        "recommendation": f"Request additional or higher-quality documentation for {aid}",
                    })

            # Materiality untested gaps
            if data["gl_total"] > mat_threshold:
                if "detail_testing" not in existing_procs:
                    all_gaps.append({
                        "area_id": aid,
                        "area_name": data["area_name"],
                        "composite_risk_level": composite,
                        "gap_type": "MATERIALITY_UNTESTED",
                        "gap_description": f"GL total {data['gl_total']:.2f} exceeds materiality {mat_threshold:.2f} but no detail testing",
                        "severity": "High",
                        "recommendation": f"Add detail_testing procedure for {aid} given material GL activity",
                    })

        # Sort gaps
        all_gaps.sort(key=lambda g: (g["area_id"], g["gap_type"]))

        # --- Step 7: Write deliverable ---
        report_path = os.path.join(self.workspace, "coverage_gap_report.csv")
        fieldnames = ["area_id", "area_name", "composite_risk_level", "gap_type",
                       "gap_description", "severity", "recommendation"]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for gap in all_gaps:
                writer.writerow(gap)

        # --- Step 8: Build action string (executive summary) ---
        proc_gap_count = sum(1 for g in all_gaps if g["gap_type"] == "PROCEDURE_GAP")
        finding_gap_count = sum(1 for g in all_gaps if g["gap_type"] == "UNREMEDIATED_FINDING")
        support_gap_count = sum(1 for g in all_gaps if g["gap_type"] == "SUPPORT_DEFICIENCY")
        mat_gap_count = sum(1 for g in all_gaps if g["gap_type"] == "MATERIALITY_UNTESTED")

        action = (
            f"Coverage Gap Analysis Complete.\n\n"
            f"Total high-risk audit areas identified: {len(high_risk_areas)}\n"
            f"Total coverage gaps found: {len(all_gaps)}\n\n"
            f"Gap breakdown:\n"
            f"- Procedure gaps: {proc_gap_count}\n"
            f"- Unremediated finding gaps: {finding_gap_count}\n"
            f"- Support deficiency gaps: {support_gap_count}\n"
            f"- Materiality untested gaps: {mat_gap_count}\n\n"
            f"The coverage_gap_report.csv has been generated with all identified gaps, "
            f"sorted by area_id and gap_type. Each gap includes the composite risk level, "
            f"gap description, severity rating, and recommended remediation action.\n\n"
            f"High-risk areas: {', '.join(sorted(high_risk_areas))}"
        )

        return self.step(action)
