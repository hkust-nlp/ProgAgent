"""
Environment for prerequisite waiver audit task.
Evaluates compliance of approved waiver petitions against degree audit rules.
"""

import json
import os
import csv
import sqlite3
from typing import Tuple, Dict, List, Any

import yaml


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
        }
        return func
    return decorator


GRADE_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "F", "W"]
AUTHORITY_RANK = {"instructor": 1, "department_chair": 2, "dean": 3, "provost": 4}


def grade_meets_minimum(grade, min_grade):
    """Check if grade meets or exceeds min_grade."""
    if grade not in GRADE_ORDER or min_grade not in GRADE_ORDER:
        return False
    return GRADE_ORDER.index(grade) <= GRADE_ORDER.index(min_grade)


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

    # ==================== TOOLS ====================

    @tool(
        description="List approved waiver petitions with pagination. Returns petition IDs and basic info.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Each page returns up to 10 results."
                },
                "semester_filter": {
                    "type": "string",
                    "description": "Optional filter by semester (e.g. 'Fall 2023'). Leave empty for all."
                }
            },
            "required": ["page"]
        }
    )
    def list_approved_waivers(self, page: int, semester_filter: str = "") -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if semester_filter:
            cursor.execute(
                "SELECT petition_id, student_id, course_id, waiver_type, semester "
                "FROM waiver_petitions WHERE status='approved' AND semester=? "
                "ORDER BY petition_id",
                (semester_filter,)
            )
        else:
            cursor.execute(
                "SELECT petition_id, student_id, course_id, waiver_type, semester "
                "FROM waiver_petitions WHERE status='approved' ORDER BY petition_id"
            )

        all_rows = cursor.fetchall()
        conn.close()

        page_size = 10
        total = len(all_rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = all_rows[start:end]

        return {
            "total_count": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
            "results": [dict(r) for r in page_rows]
        }

    @tool(
        description="Get detailed information about a specific waiver petition by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "petition_id": {
                    "type": "string",
                    "description": "The petition ID (e.g. 'WP20001')"
                }
            },
            "required": ["petition_id"]
        }
    )
    def get_petition_details(self, petition_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM waiver_petitions WHERE petition_id=?", (petition_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Petition {petition_id} not found"}

    @tool(
        description="Get student academic profile including GPA, program, and enrollment info.",
        parameters={
            "type": "object",
            "properties": {
                "student_id": {
                    "type": "string",
                    "description": "The student ID (e.g. 'STU10001')"
                }
            },
            "required": ["student_id"]
        }
    )
    def get_student_profile(self, student_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM students WHERE student_id=?", (student_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Student {student_id} not found"}

    @tool(
        description="Get course information including prerequisites, credits, level, and department.",
        parameters={
            "type": "object",
            "properties": {
                "course_id": {
                    "type": "string",
                    "description": "The course ID (e.g. 'CS301')"
                }
            },
            "required": ["course_id"]
        }
    )
    def get_course_info(self, course_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM courses WHERE course_id=?", (course_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Course {course_id} not found"}

    @tool(
        description="Get the degree audit rule for a specific course within a program. Returns waiver authority requirements, minimum grade, and whether the course is waivable.",
        parameters={
            "type": "object",
            "properties": {
                "program_id": {
                    "type": "string",
                    "description": "The program ID (e.g. 'CS_BS')"
                },
                "course_id": {
                    "type": "string",
                    "description": "The course ID to look up rules for"
                }
            },
            "required": ["program_id", "course_id"]
        }
    )
    def get_degree_rule(self, program_id: str, course_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM degree_audit_rules WHERE program_id=? AND course_id=?",
            (program_id, course_id)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"No rule found for program={program_id}, course={course_id}"}

    @tool(
        description="Get transcript records for a student, showing courses taken and grades earned.",
        parameters={
            "type": "object",
            "properties": {
                "student_id": {
                    "type": "string",
                    "description": "The student ID"
                },
                "course_id": {
                    "type": "string",
                    "description": "Optional: filter by specific course ID. Leave empty for all."
                }
            },
            "required": ["student_id"]
        }
    )
    def get_transcript_records(self, student_id: str, course_id: str = "") -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if course_id:
            cursor.execute(
                "SELECT * FROM grade_transcripts WHERE student_id=? AND course_id=? ORDER BY semester",
                (student_id, course_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM grade_transcripts WHERE student_id=? ORDER BY semester",
                (student_id,)
            )

        rows = cursor.fetchall()
        conn.close()
        return {"records": [dict(r) for r in rows]}

    @tool(
        description="Get course substitution records associated with a petition.",
        parameters={
            "type": "object",
            "properties": {
                "petition_id": {
                    "type": "string",
                    "description": "The petition ID to look up substitutions for"
                }
            },
            "required": ["petition_id"]
        }
    )
    def get_substitution_for_petition(self, petition_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM course_substitutions WHERE petition_id=?",
            (petition_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return {"substitutions": [dict(r) for r in rows]}

    @tool(
        description="Look up the actual authority level of a faculty approver from the registry.",
        parameters={
            "type": "object",
            "properties": {
                "approver_id": {
                    "type": "string",
                    "description": "The approver's faculty ID (e.g. 'FAC1001')"
                }
            },
            "required": ["approver_id"]
        }
    )
    def get_approver_authority(self, approver_id: str) -> dict:
        registry_path = os.path.join(self.workspace, "approver_registry.yaml")
        if not os.path.exists(registry_path):
            return {"error": "Approver registry not found"}

        with open(registry_path, "r") as f:
            data = yaml.safe_load(f)

        for approver in data.get("approvers", []):
            if approver["id"] == approver_id:
                return approver
        return {"error": f"Approver {approver_id} not found in registry"}

    # ==================== STEP ====================

    def _compute_violations(self):
        """Compute all compliance violations from the data."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Load compliance policy
        policy_path = os.path.join(self.workspace, "compliance_policy.json")
        with open(policy_path, "r") as f:
            policy = json.load(f)

        # Load approver registry
        registry_path = os.path.join(self.workspace, "approver_registry.yaml")
        with open(registry_path, "r") as f:
            registry = yaml.safe_load(f)
        approver_map = {a["id"]: a for a in registry.get("approvers", [])}

        # Get all approved petitions
        cursor.execute("SELECT * FROM waiver_petitions WHERE status='approved'")
        approved = [dict(r) for r in cursor.fetchall()]

        # Get all substitutions
        cursor.execute("SELECT * FROM course_substitutions")
        all_subs = [dict(r) for r in cursor.fetchall()]
        sub_by_petition = {}
        for s in all_subs:
            sub_by_petition.setdefault(s["petition_id"], []).append(s)

        # Get student info
        cursor.execute("SELECT * FROM students")
        students = {r["student_id"]: dict(r) for r in cursor.fetchall()}

        # Get courses
        cursor.execute("SELECT * FROM courses")
        courses = {r["course_id"]: dict(r) for r in cursor.fetchall()}

        # Get degree audit rules
        cursor.execute("SELECT * FROM degree_audit_rules")
        rules = cursor.fetchall()
        rule_map = {}
        for r in rules:
            key = (r["program_id"], r["course_id"])
            rule_map[key] = dict(r)

        # Get transcripts
        cursor.execute("SELECT * FROM grade_transcripts")
        transcripts = cursor.fetchall()
        transcript_map = {}
        for t in transcripts:
            key = (t["student_id"], t["course_id"])
            if key not in transcript_map:
                transcript_map[key] = []
            transcript_map[key].append(dict(t))

        conn.close()

        # Count waivers per student
        waivers_per_student = {}
        for p in approved:
            waivers_per_student[p["student_id"]] = waivers_per_student.get(p["student_id"], 0) + 1

        semester_starts = policy["deadline_policy"]["semester_start_dates"]

        violations = []

        for petition in approved:
            pid = petition["petition_id"]
            sid = petition["student_id"]
            cid = petition["course_id"]
            student = students.get(sid)
            course = courses.get(cid)

            if not student or not course:
                continue

            petition_violations = []

            # Check 1: GPA threshold
            if student["cumulative_gpa"] < policy["gpa_threshold_for_waiver"]:
                petition_violations.append({
                    "violation_type": "gpa_below_threshold",
                    "detail": f"Student GPA {student['cumulative_gpa']:.2f} below required {policy['gpa_threshold_for_waiver']}"
                })

            # Check 2: Authority level compliance
            # Get the rule for this course in the student's program
            rule = rule_map.get((student["program_id"], cid))
            if rule:
                required_authority = rule["waiver_authority_level"]
                # Get actual authority from registry
                approver_info = approver_map.get(petition["approver_id"])
                if approver_info:
                    actual_authority = approver_info["level"]
                    if AUTHORITY_RANK.get(actual_authority, 0) < AUTHORITY_RANK.get(required_authority, 0):
                        petition_violations.append({
                            "violation_type": "insufficient_authority",
                            "detail": f"Approver {petition['approver_id']} has level '{actual_authority}' but '{required_authority}' required"
                        })

                # Check 3: Non-waivable course override
                if rule["is_waivable"] == 0:
                    override_authority = policy["non_waivable_override_authority"]
                    approver_info = approver_map.get(petition["approver_id"])
                    if approver_info:
                        if AUTHORITY_RANK.get(approver_info["level"], 0) < AUTHORITY_RANK.get(override_authority, 0):
                            petition_violations.append({
                                "violation_type": "non_waivable_without_override",
                                "detail": f"Course {cid} is non-waivable; requires '{override_authority}' override but approver is '{approver_info['level']}'"
                            })

            # Check 4: Processing time exceeded
            from datetime import datetime
            try:
                submitted = datetime.fromisoformat(petition["submitted_date"])
                decided = datetime.fromisoformat(petition["decision_date"])
                days = (decided - submitted).days
                if days > policy["max_processing_days"]:
                    petition_violations.append({
                        "violation_type": "processing_time_exceeded",
                        "detail": f"Processing took {days} days, max allowed is {policy['max_processing_days']}"
                    })
            except (ValueError, TypeError):
                pass

            # Check 5: Petition submitted after semester start
            semester = petition["semester"]
            if semester in semester_starts:
                try:
                    sem_start = datetime.fromisoformat(semester_starts[semester])
                    submitted = datetime.fromisoformat(petition["submitted_date"])
                    if submitted > sem_start:
                        petition_violations.append({
                            "violation_type": "late_petition",
                            "detail": f"Petition submitted {petition['submitted_date']} after semester start {semester_starts[semester]}"
                        })
                except (ValueError, TypeError):
                    pass

            # Check 6: Max waivers per student exceeded
            if waivers_per_student.get(sid, 0) > policy["max_waivers_per_student"]:
                petition_violations.append({
                    "violation_type": "max_waivers_exceeded",
                    "detail": f"Student has {waivers_per_student[sid]} approved waivers, max is {policy['max_waivers_per_student']}"
                })

            # Check 7: Credit equivalence for substitutions
            subs = sub_by_petition.get(pid, [])
            for sub in subs:
                if sub["credit_equivalence"] < policy["credit_equivalence_minimum"]:
                    petition_violations.append({
                        "violation_type": "credit_equivalence_below_minimum",
                        "detail": f"Substitution {sub['substitution_id']} has credit equivalence {sub['credit_equivalence']:.2f}, minimum is {policy['credit_equivalence_minimum']}"
                    })

            if petition_violations:
                violations.append({
                    "petition_id": pid,
                    "student_id": sid,
                    "course_id": cid,
                    "semester": petition["semester"],
                    "violations": petition_violations
                })

        # Sort by petition_id
        violations.sort(key=lambda x: x["petition_id"])
        return violations

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
        expected_violations = self._compute_violations()

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # Criterion 1: Compliance dossier file exists (15 pts)
        dossier_path = os.path.join(self.workspace, "compliance_dossier.csv")
        dossier_exists = os.path.exists(dossier_path)
        eval_criteria["dossier_file_exists"] = {
            "passed": dossier_exists,
            "score": 15 if dossier_exists else 0,
            "max_score": 15,
            "reason": "" if dossier_exists else "compliance_dossier.csv not found in workspace"
        }
        total_score += eval_criteria["dossier_file_exists"]["score"]
        max_score += 15

        # Criterion 2: Dossier has correct columns (10 pts)
        expected_columns = ["petition_id", "student_id", "course_id", "semester", "violation_type", "detail"]
        correct_columns = False
        dossier_rows = []
        if dossier_exists:
            try:
                with open(dossier_path, "r") as f:
                    reader = csv.DictReader(f)
                    actual_cols = [c.strip() for c in reader.fieldnames] if reader.fieldnames else []
                    correct_columns = all(c in actual_cols for c in expected_columns)
                    dossier_rows = list(reader)
            except Exception:
                pass

        eval_criteria["dossier_columns"] = {
            "passed": correct_columns,
            "score": 10 if correct_columns else 0,
            "max_score": 10,
            "reason": "" if correct_columns else f"Expected columns {expected_columns}, got {actual_cols if dossier_exists else 'N/A'}"
        }
        total_score += eval_criteria["dossier_columns"]["score"]
        max_score += 10

        # Criterion 3: Correct number of non-compliant petitions identified (20 pts)
        expected_petition_ids = sorted(set(v["petition_id"] for v in expected_violations))
        found_petition_ids = sorted(set(r.get("petition_id", "").strip() for r in dossier_rows))

        petition_match = set(found_petition_ids) == set(expected_petition_ids)
        # Partial credit: proportion of correct identifications
        if expected_petition_ids:
            true_positives = len(set(found_petition_ids) & set(expected_petition_ids))
            false_positives = len(set(found_petition_ids) - set(expected_petition_ids))
            precision = true_positives / max(len(found_petition_ids), 1)
            recall = true_positives / len(expected_petition_ids)
            f1 = 2 * precision * recall / max(precision + recall, 0.001)
            petition_score = round(20 * f1)
        else:
            petition_score = 20 if not found_petition_ids else 0

        eval_criteria["petition_identification"] = {
            "passed": petition_match,
            "score": petition_score,
            "max_score": 20,
            "reason": "" if petition_match else f"Expected {len(expected_petition_ids)} petitions, found {len(found_petition_ids)}. Missing: {set(expected_petition_ids) - set(found_petition_ids) if len(set(expected_petition_ids) - set(found_petition_ids)) <= 5 else '...'}"
        }
        total_score += petition_score
        max_score += 20

        # Criterion 4: Correct violation types identified (20 pts)
        expected_violation_entries = []
        for v in expected_violations:
            for viol in v["violations"]:
                expected_violation_entries.append((v["petition_id"], viol["violation_type"]))
        expected_violation_set = set(expected_violation_entries)

        found_violation_entries = set()
        for r in dossier_rows:
            pid = r.get("petition_id", "").strip()
            vtype = r.get("violation_type", "").strip()
            if pid and vtype:
                found_violation_entries.add((pid, vtype))

        if expected_violation_set:
            tp = len(found_violation_entries & expected_violation_set)
            fp = len(found_violation_entries - expected_violation_set)
            prec = tp / max(len(found_violation_entries), 1)
            rec = tp / len(expected_violation_set)
            f1 = 2 * prec * rec / max(prec + rec, 0.001)
            violation_score = round(20 * f1)
        else:
            violation_score = 20 if not found_violation_entries else 0

        violations_match = found_violation_entries == expected_violation_set
        eval_criteria["violation_types"] = {
            "passed": violations_match,
            "score": violation_score,
            "max_score": 20,
            "reason": "" if violations_match else f"Expected {len(expected_violation_set)} violation entries, found {len(found_violation_entries)}"
        }
        total_score += violation_score
        max_score += 20

        # Criterion 5: Summary statistics in response (15 pts)
        summary_score = 0
        # Check that the response mentions total violations count
        total_violations_count = len(expected_violations)
        total_violation_entries_count = len(expected_violation_set)

        has_petition_count = str(total_violations_count) in action
        has_violation_count = str(total_violation_entries_count) in action

        if has_petition_count:
            summary_score += 8
        if has_violation_count:
            summary_score += 7

        eval_criteria["summary_statistics"] = {
            "passed": summary_score == 15,
            "score": summary_score,
            "max_score": 15,
            "reason": "" if summary_score == 15 else f"Expected mention of {total_violations_count} non-compliant petitions and {total_violation_entries_count} total violations"
        }
        total_score += summary_score
        max_score += 15

        # Criterion 6: Summary report file exists with breakdown by type (20 pts)
        summary_path = os.path.join(self.workspace, "violation_summary.json")
        summary_exists = os.path.exists(summary_path)
        summary_score_6 = 0

        if summary_exists:
            try:
                with open(summary_path, "r") as f:
                    summary_data = json.load(f)

                # Expected: breakdown by violation type
                expected_type_counts = {}
                for v in expected_violations:
                    for viol in v["violations"]:
                        vt = viol["violation_type"]
                        expected_type_counts[vt] = expected_type_counts.get(vt, 0) + 1

                if "violation_type_counts" in summary_data:
                    actual_type_counts = summary_data["violation_type_counts"]
                    if actual_type_counts == expected_type_counts:
                        summary_score_6 = 20
                    else:
                        # Partial credit for getting some right
                        correct = sum(1 for k, v in expected_type_counts.items()
                                     if actual_type_counts.get(k) == v)
                        summary_score_6 = round(20 * correct / max(len(expected_type_counts), 1))
                else:
                    summary_score_6 = 5  # File exists but missing key
            except Exception:
                summary_score_6 = 2  # File exists but unreadable

        eval_criteria["summary_report"] = {
            "passed": summary_score_6 == 20,
            "score": summary_score_6,
            "max_score": 20,
            "reason": "" if summary_score_6 == 20 else "violation_summary.json missing or incorrect violation_type_counts"
        }
        total_score += summary_score_6
        max_score += 20

        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import os

        # Step 1: Read compliance policy from workspace
        policy_path = os.path.join(self.workspace, "compliance_policy.json")
        with open(policy_path, "r") as f:
            policy = json.load(f)

        # Step 2: Paginate through all approved waivers
        all_petitions = []
        page = 1
        while True:
            result = self.tools["list_approved_waivers"](page=page)
            all_petitions.extend(result["results"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 3: For each approved petition, check compliance
        violations = []
        waivers_per_student = {}

        # First pass: count waivers per student
        for p in all_petitions:
            sid = p["student_id"]
            waivers_per_student[sid] = waivers_per_student.get(sid, 0) + 1

        # Second pass: check each petition
        for p in all_petitions:
            pid = p["petition_id"]
            sid = p["student_id"]
            cid = p["course_id"]

            # Get petition details
            details = self.tools["get_petition_details"](petition_id=pid)

            # Get student profile
            student = self.tools["get_student_profile"](student_id=sid)

            # Get course info
            course = self.tools["get_course_info"](course_id=cid)

            petition_violations = []

            # Check 1: GPA threshold
            if student.get("cumulative_gpa", 0) < policy["gpa_threshold_for_waiver"]:
                petition_violations.append({
                    "violation_type": "gpa_below_threshold",
                    "detail": f"Student GPA {student['cumulative_gpa']:.2f} below required {policy['gpa_threshold_for_waiver']}"
                })

            # Check 2 & 3: Authority and waivability
            program_id = student.get("program_id", "")
            rule = self.tools["get_degree_rule"](program_id=program_id, course_id=cid)

            if "error" not in rule:
                required_authority = rule["waiver_authority_level"]
                approver_info = self.tools["get_approver_authority"](approver_id=details["approver_id"])

                if "error" not in approver_info:
                    actual_authority = approver_info["level"]
                    if AUTHORITY_RANK.get(actual_authority, 0) < AUTHORITY_RANK.get(required_authority, 0):
                        petition_violations.append({
                            "violation_type": "insufficient_authority",
                            "detail": f"Approver {details['approver_id']} has level '{actual_authority}' but '{required_authority}' required"
                        })

                    # Non-waivable check
                    if rule["is_waivable"] == 0:
                        override_authority = policy["non_waivable_override_authority"]
                        if AUTHORITY_RANK.get(approver_info["level"], 0) < AUTHORITY_RANK.get(override_authority, 0):
                            petition_violations.append({
                                "violation_type": "non_waivable_without_override",
                                "detail": f"Course {cid} is non-waivable; requires '{override_authority}' override but approver is '{approver_info['level']}'"
                            })

            # Check 4: Processing time
            from datetime import datetime
            try:
                submitted = datetime.fromisoformat(details["submitted_date"])
                decided = datetime.fromisoformat(details["decision_date"])
                days = (decided - submitted).days
                if days > policy["max_processing_days"]:
                    petition_violations.append({
                        "violation_type": "processing_time_exceeded",
                        "detail": f"Processing took {days} days, max allowed is {policy['max_processing_days']}"
                    })
            except (ValueError, TypeError):
                pass

            # Check 5: Late petition
            semester = details.get("semester", "")
            semester_starts = policy["deadline_policy"]["semester_start_dates"]
            if semester in semester_starts:
                try:
                    sem_start = datetime.fromisoformat(semester_starts[semester])
                    sub_date = datetime.fromisoformat(details["submitted_date"])
                    if sub_date > sem_start:
                        petition_violations.append({
                            "violation_type": "late_petition",
                            "detail": f"Petition submitted {details['submitted_date']} after semester start {semester_starts[semester]}"
                        })
                except (ValueError, TypeError):
                    pass

            # Check 6: Max waivers exceeded
            if waivers_per_student.get(sid, 0) > policy["max_waivers_per_student"]:
                petition_violations.append({
                    "violation_type": "max_waivers_exceeded",
                    "detail": f"Student has {waivers_per_student[sid]} approved waivers, max is {policy['max_waivers_per_student']}"
                })

            # Check 7: Credit equivalence for substitutions
            subs = self.tools["get_substitution_for_petition"](petition_id=pid)
            for sub in subs.get("substitutions", []):
                if sub["credit_equivalence"] < policy["credit_equivalence_minimum"]:
                    petition_violations.append({
                        "violation_type": "credit_equivalence_below_minimum",
                        "detail": f"Substitution {sub['substitution_id']} has credit equivalence {sub['credit_equivalence']:.2f}, minimum is {policy['credit_equivalence_minimum']}"
                    })

            if petition_violations:
                violations.append({
                    "petition_id": pid,
                    "student_id": sid,
                    "course_id": cid,
                    "semester": details.get("semester", ""),
                    "violations": petition_violations
                })

        # Write compliance_dossier.csv
        dossier_path = os.path.join(self.workspace, "compliance_dossier.csv")
        with open(dossier_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["petition_id", "student_id", "course_id", "semester", "violation_type", "detail"])
            for v in sorted(violations, key=lambda x: x["petition_id"]):
                for viol in v["violations"]:
                    writer.writerow([
                        v["petition_id"],
                        v["student_id"],
                        v["course_id"],
                        v["semester"],
                        viol["violation_type"],
                        viol["detail"]
                    ])

        # Write violation_summary.json
        type_counts = {}
        for v in violations:
            for viol in v["violations"]:
                vt = viol["violation_type"]
                type_counts[vt] = type_counts.get(vt, 0) + 1

        summary = {
            "total_non_compliant_petitions": len(violations),
            "total_violation_entries": sum(type_counts.values()),
            "violation_type_counts": type_counts
        }
        summary_path = os.path.join(self.workspace, "violation_summary.json")
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        # Construct action string
        action = (
            f"Compliance review complete. Identified {len(violations)} non-compliant petitions "
            f"with {sum(type_counts.values())} total violations. "
            f"Violation breakdown: {json.dumps(type_counts)}. "
            f"Results saved to compliance_dossier.csv and violation_summary.json."
        )

        return self.step(action)
