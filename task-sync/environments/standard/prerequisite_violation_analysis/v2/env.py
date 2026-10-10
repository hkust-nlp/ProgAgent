"""Environment for prerequisite violation detection task."""
import csv
import json
import os
import sqlite3
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


SEMESTERS = [
    "Fall 2020", "Spring 2021", "Fall 2021", "Spring 2022",
    "Fall 2022", "Spring 2023", "Fall 2023", "Spring 2024",
]
SEMESTER_ORDER = {s: i for i, s in enumerate(SEMESTERS)}


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
    # Tools
    # ------------------------------------------------------------------

    @tool(
        description="List students with pagination. Returns student_id, name, major, enrollment_year, and academic_standing.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 50).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_students(self, page: int, page_size: int):
        page_size = min(page_size, 50)
        offset = (max(page, 1) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM students ORDER BY student_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "results": [dict(r) for r in rows],
        }

    @tool(
        description="Retrieve the full academic transcript for a single student. Each record contains course_id, semester, grade, and credits_earned.",
        parameters={
            "type": "object",
            "properties": {
                "student_id": {
                    "type": "string",
                    "description": "The student ID, e.g. 'S1000'.",
                },
            },
            "required": ["student_id"],
        },
    )
    def get_student_transcript(self, student_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT record_id, course_id, semester, grade, credits_earned "
            "FROM transcripts WHERE student_id = ? ORDER BY record_id",
            (student_id,),
        ).fetchall()
        conn.close()
        return {"student_id": student_id, "records": [dict(r) for r in rows]}

    @tool(
        description="List courses with optional department filter and pagination. Returns course_id, course_name, department, level, and credits.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 50).",
                },
                "department": {
                    "type": "string",
                    "description": "Optional department code to filter (e.g. 'CS').",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_courses(self, page: int, page_size: int, department: str = None):
        page_size = min(page_size, 50)
        offset = (max(page, 1) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if department:
            rows = conn.execute(
                "SELECT * FROM courses WHERE department = ? ORDER BY course_id LIMIT ? OFFSET ?",
                (department, page_size, offset),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM courses WHERE department = ?", (department,)
            ).fetchone()[0]
        else:
            rows = conn.execute(
                "SELECT * FROM courses ORDER BY course_id LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "results": [dict(r) for r in rows],
        }

    @tool(
        description="Get the prerequisite requirements for a specific course. Returns a list of prerequisite course IDs and the minimum grade required for each.",
        parameters={
            "type": "object",
            "properties": {
                "course_id": {
                    "type": "string",
                    "description": "The course ID to look up prerequisites for.",
                },
            },
            "required": ["course_id"],
        },
    )
    def get_course_prerequisites(self, course_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT prereq_course_id, min_grade FROM prerequisites WHERE course_id = ? ORDER BY prereq_course_id",
            (course_id,),
        ).fetchall()
        conn.close()
        return {"course_id": course_id, "prerequisites": [dict(r) for r in rows]}

    @tool(
        description="List all prerequisite relationships with pagination. Each record contains course_id, prereq_course_id, and min_grade.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 50).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_prerequisites(self, page: int, page_size: int):
        page_size = min(page_size, 50)
        offset = (max(page, 1) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT course_id, prereq_course_id, min_grade FROM prerequisites ORDER BY course_id, prereq_course_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM prerequisites").fetchone()[0]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "results": [dict(r) for r in rows],
        }

    @tool(
        description="Search registration attempts with optional filters. Returns attempt_id, student_id, course_id, semester, outcome, and attempt_date.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 50).",
                },
                "student_id": {
                    "type": "string",
                    "description": "Filter by student ID.",
                },
                "course_id": {
                    "type": "string",
                    "description": "Filter by course ID.",
                },
                "semester": {
                    "type": "string",
                    "description": "Filter by semester, e.g. 'Fall 2023'.",
                },
                "outcome": {
                    "type": "string",
                    "enum": ["approved", "denied", "waitlisted"],
                    "description": "Filter by registration outcome.",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def search_registration_attempts(
        self,
        page: int,
        page_size: int,
        student_id: str = None,
        course_id: str = None,
        semester: str = None,
        outcome: str = None,
    ):
        page_size = min(page_size, 50)
        offset = (max(page, 1) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        where_clauses = []
        params: list = []
        if student_id:
            where_clauses.append("student_id = ?")
            params.append(student_id)
        if course_id:
            where_clauses.append("course_id = ?")
            params.append(course_id)
        if semester:
            where_clauses.append("semester = ?")
            params.append(semester)
        if outcome:
            where_clauses.append("outcome = ?")
            params.append(outcome)

        where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        rows = conn.execute(
            f"SELECT * FROM registration_attempts{where} ORDER BY attempt_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM registration_attempts{where}", params
        ).fetchone()[0]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "results": [dict(r) for r in rows],
        }

    @tool(
        description="Get the list of all department codes in the system.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def get_departments(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT DISTINCT department FROM courses ORDER BY department"
        ).fetchall()
        conn.close()
        return {"departments": [r[0] for r in rows]}

    # ------------------------------------------------------------------
    # Ground-truth computation (used by step & verify)
    # ------------------------------------------------------------------

    def _load_grade_scale(self):
        with open(os.path.join(self.workspace, "grade_scale.json")) as f:
            return json.load(f)["scale"]

    def _load_enforcement_policy(self):
        with open(os.path.join(self.workspace, "enforcement_policy.yaml")) as f:
            return yaml.safe_load(f)

    def _load_overrides(self):
        overrides = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("advisor_overrides_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    overrides.extend(json.load(f))
        return overrides

    def _load_advisor_map(self):
        mapping = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("student_advisor_map_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        mapping[row["student_id"]] = row
        return mapping

    def _compute_ground_truth(self):
        """Return (violations_list, overrides_list, advisor_map, policy, grade_scale)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        students = {r["student_id"]: dict(r) for r in conn.execute("SELECT * FROM students").fetchall()}
        courses = {r["course_id"]: dict(r) for r in conn.execute("SELECT * FROM courses").fetchall()}

        prereq_map: dict = {}
        for r in conn.execute("SELECT course_id, prereq_course_id, min_grade FROM prerequisites").fetchall():
            prereq_map.setdefault(r["course_id"], []).append((r["prereq_course_id"], r["min_grade"]))

        # Per-student transcripts: sid -> {cid: [(sem, grade)]}
        stu_trans: dict = {}
        for r in conn.execute("SELECT student_id, course_id, semester, grade FROM transcripts").fetchall():
            stu_trans.setdefault(r["student_id"], {}).setdefault(r["course_id"], []).append(
                (r["semester"], r["grade"])
            )

        approved_regs = [
            dict(r) for r in conn.execute(
                "SELECT * FROM registration_attempts WHERE outcome = 'approved' ORDER BY attempt_id"
            ).fetchall()
        ]
        conn.close()

        grade_scale = self._load_grade_scale()
        policy = self._load_enforcement_policy()
        overrides = self._load_overrides()
        advisor_map = self._load_advisor_map()

        # Override lookup: (student_id, course_id, prereq_course_id) -> override record
        override_lookup: dict = {}
        for o in overrides:
            key = (o["student_id"], o["course_id"], o["prereq_course_id"])
            override_lookup[key] = o

        violations = []
        seen = set()
        for reg in approved_regs:
            cid = reg["course_id"]
            sid = reg["student_id"]
            reg_sem = reg["semester"]
            if cid not in prereq_map:
                continue
            reg_ord = SEMESTER_ORDER.get(reg_sem, 999)
            for prereq_id, min_grade in prereq_map[cid]:
                vkey = (sid, cid, prereq_id, reg_sem)
                if vkey in seen:
                    continue

                records = stu_trans.get(sid, {}).get(prereq_id, [])
                prior_grades = [g for sem, g in records if SEMESTER_ORDER.get(sem, 999) < reg_ord]

                violation_type = None
                if not prior_grades:
                    violation_type = "missing"
                else:
                    best = max(prior_grades, key=lambda g: grade_scale.get(g, 0))
                    if grade_scale.get(best, 0) < grade_scale.get(min_grade, 0):
                        violation_type = "grade_insufficient"

                if violation_type:
                    seen.add(vkey)
                    stu = students.get(sid, {})
                    crs = courses.get(cid, {})
                    ovr_key = (sid, cid, prereq_id)
                    has_ovr = ovr_key in override_lookup
                    ovr_reason = override_lookup[ovr_key]["reason"] if has_ovr else ""

                    # Severity
                    s_major = stu.get("major", "")
                    c_dept = crs.get("department", "")
                    in_major = (s_major == c_dept)
                    if violation_type == "missing" and in_major:
                        severity = "critical"
                    elif violation_type == "missing" and not in_major:
                        severity = "major"
                    elif violation_type == "grade_insufficient" and in_major:
                        severity = "major"
                    else:
                        severity = "minor"

                    violations.append({
                        "student_id": sid,
                        "student_name": stu.get("name", ""),
                        "course_id": cid,
                        "course_name": crs.get("course_name", ""),
                        "missing_prereq_id": prereq_id,
                        "violation_type": violation_type,
                        "severity": severity,
                        "has_override": "yes" if has_ovr else "no",
                        "override_reason": ovr_reason,
                        "semester": reg_sem,
                    })

        # Sort: severity order (critical, major, minor), then student_id
        sev_rank = {"critical": 0, "major": 1, "minor": 2}
        violations.sort(key=lambda v: (sev_rank.get(v["severity"], 9), v["student_id"], v["course_id"]))

        return violations, overrides, advisor_map, policy, grade_scale

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
        gt_violations, gt_overrides, advisor_map, policy, grade_scale = self._compute_ground_truth()

        criteria: dict = {}
        total_score = 0
        max_score = 0

        # ---- Criterion 1: violation_report.csv exists with correct columns (10 pts) ----
        c1_max = 10
        max_score += c1_max
        report_path = os.path.join(self.workspace, "violation_report.csv")
        expected_cols = [
            "student_id", "student_name", "course_id", "course_name",
            "missing_prereq_id", "violation_type", "severity",
            "has_override", "override_reason", "semester",
        ]
        if os.path.exists(report_path):
            with open(report_path) as f:
                reader = csv.DictReader(f)
                report_rows = list(reader)
                actual_cols = list(reader.fieldnames) if reader.fieldnames else []
            cols_match = all(c in actual_cols for c in expected_cols)
            if cols_match:
                criteria["report_structure"] = {"passed": True, "score": c1_max, "max_score": c1_max}
                total_score += c1_max
            else:
                missing = [c for c in expected_cols if c not in actual_cols]
                criteria["report_structure"] = {
                    "passed": False, "score": 0, "max_score": c1_max,
                    "reason": f"Missing columns: {missing}",
                }
        else:
            report_rows = []
            criteria["report_structure"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "violation_report.csv not found",
            }

        # ---- Criterion 2: correct number of violations (20 pts) ----
        c2_max = 20
        max_score += c2_max
        gt_count = len(gt_violations)
        agent_count = len(report_rows)
        if agent_count == gt_count:
            criteria["violation_count"] = {"passed": True, "score": c2_max, "max_score": c2_max}
            total_score += c2_max
        else:
            # Partial credit: proportional to how close
            ratio = min(agent_count, gt_count) / max(agent_count, gt_count, 1)
            partial = int(c2_max * ratio * 0.5)
            criteria["violation_count"] = {
                "passed": False, "score": partial, "max_score": c2_max,
                "reason": f"Expected {gt_count} violations, got {agent_count}",
            }
            total_score += partial

        # ---- Criterion 3: correct violation identification (20 pts) ----
        c3_max = 20
        max_score += c3_max
        gt_keys = {(v["student_id"], v["course_id"], v["missing_prereq_id"]) for v in gt_violations}
        agent_keys = set()
        for r in report_rows:
            agent_keys.add((r.get("student_id", ""), r.get("course_id", ""), r.get("missing_prereq_id", "")))
        if gt_keys:
            overlap = len(gt_keys & agent_keys)
            precision = overlap / max(len(agent_keys), 1)
            recall = overlap / len(gt_keys)
            f1 = 2 * precision * recall / max(precision + recall, 1e-9)
            score3 = int(c3_max * f1)
        else:
            score3 = c3_max if len(agent_keys) == 0 else 0
        criteria["violation_identification"] = {
            "passed": score3 == c3_max,
            "score": score3,
            "max_score": c3_max,
            "reason": "" if score3 == c3_max else f"F1={f1:.2f} (precision={precision:.2f}, recall={recall:.2f})",
        }
        total_score += score3

        # ---- Criterion 4: severity classification (15 pts) ----
        c4_max = 15
        max_score += c4_max
        gt_sev = {(v["student_id"], v["course_id"], v["missing_prereq_id"]): v["severity"] for v in gt_violations}
        correct_sev = 0
        total_matched = 0
        for r in report_rows:
            key = (r.get("student_id", ""), r.get("course_id", ""), r.get("missing_prereq_id", ""))
            if key in gt_sev:
                total_matched += 1
                if r.get("severity", "") == gt_sev[key]:
                    correct_sev += 1
        if total_matched > 0:
            sev_ratio = correct_sev / total_matched
            score4 = int(c4_max * sev_ratio)
        else:
            score4 = 0
        criteria["severity_classification"] = {
            "passed": score4 == c4_max,
            "score": score4,
            "max_score": c4_max,
            "reason": "" if score4 == c4_max else f"{correct_sev}/{total_matched} correct severity labels",
        }
        total_score += score4

        # ---- Criterion 5: override status (10 pts) ----
        c5_max = 10
        max_score += c5_max
        gt_ovr = {(v["student_id"], v["course_id"], v["missing_prereq_id"]): v["has_override"] for v in gt_violations}
        correct_ovr = 0
        total_ovr_checked = 0
        for r in report_rows:
            key = (r.get("student_id", ""), r.get("course_id", ""), r.get("missing_prereq_id", ""))
            if key in gt_ovr:
                total_ovr_checked += 1
                if r.get("has_override", "").strip().lower() == gt_ovr[key]:
                    correct_ovr += 1
        if total_ovr_checked > 0:
            ovr_ratio = correct_ovr / total_ovr_checked
            score5 = int(c5_max * ovr_ratio)
        else:
            score5 = 0
        criteria["override_status"] = {
            "passed": score5 == c5_max,
            "score": score5,
            "max_score": c5_max,
            "reason": "" if score5 == c5_max else f"{correct_ovr}/{total_ovr_checked} correct override labels",
        }
        total_score += score5

        # ---- Criterion 6: policy_recommendations.json structure (10 pts) ----
        c6_max = 10
        max_score += c6_max
        rec_path = os.path.join(self.workspace, "policy_recommendations.json")
        rec_data = None
        if os.path.exists(rec_path):
            try:
                with open(rec_path) as f:
                    rec_data = json.load(f)
                required_keys = ["summary", "by_department", "top_violated_courses", "recommendations"]
                has_keys = all(k in rec_data for k in required_keys)
                if has_keys:
                    # Check summary sub-keys
                    summary_keys = ["total_violations", "overridden_violations", "unresolved_violations"]
                    has_summary = isinstance(rec_data.get("summary"), dict) and all(
                        k in rec_data["summary"] for k in summary_keys
                    )
                    if has_summary:
                        criteria["recommendations_structure"] = {"passed": True, "score": c6_max, "max_score": c6_max}
                        total_score += c6_max
                    else:
                        criteria["recommendations_structure"] = {
                            "passed": False, "score": 5, "max_score": c6_max,
                            "reason": "summary section missing required keys",
                        }
                        total_score += 5
                else:
                    missing = [k for k in required_keys if k not in rec_data]
                    criteria["recommendations_structure"] = {
                        "passed": False, "score": 3, "max_score": c6_max,
                        "reason": f"Missing keys: {missing}",
                    }
                    total_score += 3
            except (json.JSONDecodeError, Exception) as e:
                criteria["recommendations_structure"] = {
                    "passed": False, "score": 0, "max_score": c6_max,
                    "reason": f"Invalid JSON: {e}",
                }
        else:
            criteria["recommendations_structure"] = {
                "passed": False, "score": 0, "max_score": c6_max,
                "reason": "policy_recommendations.json not found",
            }

        # ---- Criterion 7: recommendation summary accuracy (10 pts) ----
        c7_max = 10
        max_score += c7_max
        gt_total = len(gt_violations)
        gt_overridden = sum(1 for v in gt_violations if v["has_override"] == "yes")
        gt_unresolved = gt_total - gt_overridden
        score7 = 0
        if rec_data and isinstance(rec_data.get("summary"), dict):
            s = rec_data["summary"]
            if s.get("total_violations") == gt_total:
                score7 += 4
            if s.get("overridden_violations") == gt_overridden:
                score7 += 3
            if s.get("unresolved_violations") == gt_unresolved:
                score7 += 3
        criteria["recommendations_accuracy"] = {
            "passed": score7 == c7_max,
            "score": score7,
            "max_score": c7_max,
            "reason": "" if score7 == c7_max else f"Expected total={gt_total}, overridden={gt_overridden}, unresolved={gt_unresolved}",
        }
        total_score += score7

        # ---- Criterion 8: final response summary (5 pts) ----
        c8_max = 5
        max_score += c8_max
        action_lower = action.lower()
        score8 = 0
        if str(gt_total) in action:
            score8 += 2
        if "violation" in action_lower:
            score8 += 1
        if any(sev in action_lower for sev in ["critical", "major", "minor"]):
            score8 += 1
        if "override" in action_lower or "overridden" in action_lower:
            score8 += 1
        criteria["response_summary"] = {
            "passed": score8 == c8_max,
            "score": score8,
            "max_score": c8_max,
            "reason": "" if score8 == c8_max else "Missing summary elements in final response",
        }
        total_score += score8

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, info

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
        tool_calls = 0

        # 1. Read workspace files
        with open(os.path.join(self.workspace, "grade_scale.json")) as f:
            grade_info = json.load(f)
        grade_scale = grade_info["scale"]

        with open(os.path.join(self.workspace, "enforcement_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        # Load all advisor overrides from workspace
        overrides = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("advisor_overrides_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    overrides.extend(json.load(f))

        override_lookup = {}
        for o in overrides:
            key = (o["student_id"], o["course_id"], o["prereq_course_id"])
            override_lookup[key] = o

        # Load student-advisor map
        advisor_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("student_advisor_map_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        advisor_map[row["student_id"]] = row

        # 2. Gather all prerequisites via tools
        all_prereqs = []
        page = 1
        while True:
            result = self.tools["list_prerequisites"](page=page, page_size=50)
            tool_calls += 1
            all_prereqs.extend(result["results"])
            if page >= result["total_pages"]:
                break
            page += 1

        prereq_map = {}
        courses_with_prereqs = set()
        for p in all_prereqs:
            prereq_map.setdefault(p["course_id"], []).append(
                (p["prereq_course_id"], p["min_grade"])
            )
            courses_with_prereqs.add(p["course_id"])

        # 3. Gather all students
        all_students = []
        page = 1
        while True:
            result = self.tools["list_students"](page=page, page_size=50)
            tool_calls += 1
            all_students.extend(result["results"])
            if page >= result["total_pages"]:
                break
            page += 1

        student_map = {s["student_id"]: s for s in all_students}

        # 4. Gather all courses
        all_courses = []
        page = 1
        while True:
            result = self.tools["list_courses"](page=page, page_size=50)
            tool_calls += 1
            all_courses.extend(result["results"])
            if page >= result["total_pages"]:
                break
            page += 1

        course_map = {c["course_id"]: c for c in all_courses}

        # 5. Gather approved registration attempts
        approved_regs = []
        page = 1
        while True:
            result = self.tools["search_registration_attempts"](
                page=page, page_size=50, outcome="approved"
            )
            tool_calls += 1
            approved_regs.extend(result["results"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 6. Identify which students registered for courses with prereqs
        students_to_check = set()
        reg_by_student: dict = {}
        for reg in approved_regs:
            if reg["course_id"] in courses_with_prereqs:
                students_to_check.add(reg["student_id"])
                reg_by_student.setdefault(reg["student_id"], []).append(reg)

        # 7. Get transcripts for relevant students
        transcripts_by_student: dict = {}
        for sid in sorted(students_to_check):
            result = self.tools["get_student_transcript"](student_id=sid)
            tool_calls += 1
            transcripts_by_student[sid] = result["records"]

        # 8. Detect violations
        violations = []
        seen = set()
        for sid in sorted(students_to_check):
            regs = reg_by_student.get(sid, [])
            transcript = transcripts_by_student.get(sid, [])
            # Build per-course transcript: cid -> [(sem, grade)]
            stu_courses: dict = {}
            for t in transcript:
                stu_courses.setdefault(t["course_id"], []).append((t["semester"], t["grade"]))

            for reg in regs:
                cid = reg["course_id"]
                reg_sem = reg["semester"]
                reg_ord = SEMESTER_ORDER.get(reg_sem, 999)

                for prereq_id, min_grade in prereq_map.get(cid, []):
                    vkey = (sid, cid, prereq_id, reg_sem)
                    if vkey in seen:
                        continue

                    prior = stu_courses.get(prereq_id, [])
                    prior_grades = [g for sem, g in prior if SEMESTER_ORDER.get(sem, 999) < reg_ord]

                    violation_type = None
                    if not prior_grades:
                        violation_type = "missing"
                    else:
                        best = max(prior_grades, key=lambda g: grade_scale.get(g, 0))
                        if grade_scale.get(best, 0) < grade_scale.get(min_grade, 0):
                            violation_type = "grade_insufficient"

                    if violation_type:
                        seen.add(vkey)
                        stu = student_map.get(sid, {})
                        crs = course_map.get(cid, {})
                        ovr_key = (sid, cid, prereq_id)
                        has_ovr = ovr_key in override_lookup
                        ovr_reason = override_lookup[ovr_key]["reason"] if has_ovr else ""

                        s_major = stu.get("major", "")
                        c_dept = crs.get("department", "")
                        in_major = (s_major == c_dept)

                        if violation_type == "missing" and in_major:
                            severity = "critical"
                        elif violation_type == "missing" and not in_major:
                            severity = "major"
                        elif violation_type == "grade_insufficient" and in_major:
                            severity = "major"
                        else:
                            severity = "minor"

                        violations.append({
                            "student_id": sid,
                            "student_name": stu.get("name", ""),
                            "course_id": cid,
                            "course_name": crs.get("course_name", ""),
                            "missing_prereq_id": prereq_id,
                            "violation_type": violation_type,
                            "severity": severity,
                            "has_override": "yes" if has_ovr else "no",
                            "override_reason": ovr_reason,
                            "semester": reg_sem,
                        })

        # Sort: severity (critical, major, minor), then student_id
        sev_rank = {"critical": 0, "major": 1, "minor": 2}
        violations.sort(key=lambda v: (sev_rank.get(v["severity"], 9), v["student_id"], v["course_id"]))

        # 9. Write violation_report.csv
        report_path = os.path.join(self.workspace, "violation_report.csv")
        fieldnames = [
            "student_id", "student_name", "course_id", "course_name",
            "missing_prereq_id", "violation_type", "severity",
            "has_override", "override_reason", "semester",
        ]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for v in violations:
                writer.writerow({k: v[k] for k in fieldnames})

        # 10. Build policy_recommendations.json
        total_violations = len(violations)
        overridden_count = sum(1 for v in violations if v["has_override"] == "yes")
        unresolved_count = total_violations - overridden_count

        # By department
        dept_violations: dict = {}
        for v in violations:
            crs = course_map.get(v["course_id"], {})
            dept = crs.get("department", "unknown")
            dept_violations.setdefault(dept, 0)
            dept_violations[dept] += 1

        by_department = sorted(
            [{"department": d, "violations": c} for d, c in dept_violations.items()],
            key=lambda x: -x["violations"],
        )

        # Top violated courses
        course_violations: dict = {}
        for v in violations:
            course_violations.setdefault(v["course_id"], 0)
            course_violations[v["course_id"]] += 1

        top_courses = sorted(
            [{"course_id": cid, "violation_count": cnt} for cid, cnt in course_violations.items()],
            key=lambda x: (-x["violation_count"], x["course_id"]),
        )[:5]

        # Recommendations
        thresholds = policy.get("thresholds", {})
        dept_alert = thresholds.get("department_alert", 5)
        course_alert = thresholds.get("course_alert", 3)
        advisor_alert = thresholds.get("advisor_alert", 4)
        rec_rules = policy.get("recommendation_rules", {})

        recommendations = []
        for dd in by_department:
            if dd["violations"] >= dept_alert:
                recommendations.append(
                    f"{dd['department']}: {rec_rules.get('high_violation_department', 'Requires review.')}"
                )
        for tc in top_courses:
            if tc["violation_count"] >= course_alert:
                recommendations.append(
                    f"{tc['course_id']}: {rec_rules.get('high_violation_course', 'Requires review.')}"
                )

        # Advisor override counts
        advisor_override_counts: dict = {}
        for o in overrides:
            advisor_override_counts.setdefault(o["advisor_name"], 0)
            advisor_override_counts[o["advisor_name"]] += 1
        for adv_name, cnt in advisor_override_counts.items():
            if cnt >= advisor_alert:
                recommendations.append(
                    f"{adv_name}: {rec_rules.get('high_override_advisor', 'Requires review.')}"
                )

        rec_data = {
            "summary": {
                "total_violations": total_violations,
                "overridden_violations": overridden_count,
                "unresolved_violations": unresolved_count,
            },
            "by_department": by_department,
            "top_violated_courses": top_courses,
            "recommendations": recommendations,
        }

        rec_path = os.path.join(self.workspace, "policy_recommendations.json")
        with open(rec_path, "w") as f:
            json.dump(rec_data, f, indent=2)

        # 11. Construct final action
        action = (
            f"Prerequisite violation analysis complete. "
            f"Found {total_violations} total violations: "
            f"{overridden_count} overridden, {unresolved_count} unresolved. "
            f"Severity breakdown: "
            f"{sum(1 for v in violations if v['severity'] == 'critical')} critical, "
            f"{sum(1 for v in violations if v['severity'] == 'major')} major, "
            f"{sum(1 for v in violations if v['severity'] == 'minor')} minor. "
            f"Results saved to violation_report.csv and policy_recommendations.json."
        )

        assert tool_calls >= 15, f"Only {tool_calls} tool calls made, need >= 15"

        return self.step(action)
