import os
import json
import csv
import sqlite3
import glob
from typing import Tuple, Dict, List, Any


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

    # ================================================================
    # TOOL METHODS
    # ================================================================

    @tool(
        description=(
            "List students with optional filters. Returns a paginated list of "
            "student records. Each page contains at most page_size entries."
        ),
        parameters={
            "type": "object",
            "properties": {
                "grade": {
                    "type": "integer",
                    "description": "Filter by grade level (9, 10, 11, or 12). Omit to include all grades.",
                },
                "program": {
                    "type": "string",
                    "description": "Filter by program name. Omit to include all programs.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 10). Defaults to 10.",
                },
            },
            "required": [],
        },
    )
    def list_students(self, grade=None, program=None, page=1, page_size=10):
        page_size = min(int(page_size), 10)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM students WHERE 1=1"
        params = []
        if grade is not None:
            query += " AND grade = ?"
            params.append(int(grade))
        if program is not None:
            query += " AND program = ?"
            params.append(str(program))
        query += " ORDER BY student_id"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start:start + page_size]
        return {
            "students": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get detailed information for a single student by student ID.",
        parameters={
            "type": "object",
            "properties": {
                "student_id": {
                    "type": "string",
                    "description": "The student identifier, e.g. 'STU0001'.",
                },
            },
            "required": ["student_id"],
        },
    )
    def get_student_info(self, student_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM students WHERE student_id = ?", (student_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Student {student_id} not found"}
        return dict(row)

    @tool(
        description=(
            "List courses with optional filters. Returns a paginated list."
        ),
        parameters={
            "type": "object",
            "properties": {
                "course_type": {
                    "type": "string",
                    "enum": ["core", "elective"],
                    "description": "Filter by course type.",
                },
                "subject_area": {
                    "type": "string",
                    "description": "Filter by subject area.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 10). Defaults to 10.",
                },
            },
            "required": [],
        },
    )
    def list_courses(self, course_type=None, subject_area=None, page=1, page_size=10):
        page_size = min(int(page_size), 10)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM courses WHERE 1=1"
        params = []
        if course_type is not None:
            query += " AND course_type = ?"
            params.append(str(course_type))
        if subject_area is not None:
            query += " AND subject_area = ?"
            params.append(str(subject_area))
        query += " ORDER BY course_id"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start:start + page_size]
        return {
            "courses": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description=(
            "Get all sections offered for a given course. Each section includes "
            "its section_id, time_slot, max_capacity, and room."
        ),
        parameters={
            "type": "object",
            "properties": {
                "course_id": {
                    "type": "string",
                    "description": "The course identifier, e.g. 'CRS0001'.",
                },
            },
            "required": ["course_id"],
        },
    )
    def get_course_sections(self, course_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM sections WHERE course_id = ? ORDER BY section_id",
            (course_id,),
        ).fetchall()
        conn.close()
        return {"course_id": course_id, "sections": [dict(r) for r in rows]}

    @tool(
        description=(
            "Get the teacher assigned to a specific section. Returns teacher_id, "
            "teacher_name, and department."
        ),
        parameters={
            "type": "object",
            "properties": {
                "section_id": {
                    "type": "string",
                    "description": "The section identifier, e.g. 'SEC0001'.",
                },
            },
            "required": ["section_id"],
        },
    )
    def get_section_teacher(self, section_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT ta.teacher_id, t.teacher_name, t.department
               FROM teacher_assignments ta
               JOIN teachers t ON ta.teacher_id = t.teacher_id
               WHERE ta.section_id = ?""",
            (section_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"No teacher assigned to section {section_id}"}
        return {"section_id": section_id, **dict(row)}

    @tool(
        description=(
            "List all sections that a given teacher is assigned to teach, "
            "along with each section's time_slot and course_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "teacher_id": {
                    "type": "string",
                    "description": "The teacher identifier, e.g. 'TCH0001'.",
                },
            },
            "required": ["teacher_id"],
        },
    )
    def get_teacher_sections(self, teacher_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT ta.section_id, s.course_id, s.time_slot, s.max_capacity, s.room
               FROM teacher_assignments ta
               JOIN sections s ON ta.section_id = s.section_id
               WHERE ta.teacher_id = ?
               ORDER BY ta.section_id""",
            (teacher_id,),
        ).fetchall()
        conn.close()
        return {"teacher_id": teacher_id, "sections": [dict(r) for r in rows]}

    @tool(
        description="Get detailed information for a single course by course ID.",
        parameters={
            "type": "object",
            "properties": {
                "course_id": {
                    "type": "string",
                    "description": "The course identifier, e.g. 'CRS0001'.",
                },
            },
            "required": ["course_id"],
        },
    )
    def get_course_info(self, course_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM courses WHERE course_id = ?", (course_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Course {course_id} not found"}
        return dict(row)

    # ================================================================
    # HELPERS (shared by step & verify)
    # ================================================================

    def _load_teacher_availability(self) -> Dict[str, List[int]]:
        """Read all teacher_schedules/*.csv and return {teacher_id: [available slots]}."""
        avail = {}
        sched_dir = os.path.join(self.workspace, "teacher_schedules")
        for fp in sorted(glob.glob(os.path.join(sched_dir, "*.csv"))):
            with open(fp, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    tid = row["teacher_id"]
                    slots = []
                    for s in range(1, 7):  # slots 1-6
                        key = f"slot_{s}"
                        if key in row and int(row[key]) == 1:
                            slots.append(s)
                    avail[tid] = slots
        return avail

    def _load_student_preferences(self) -> Dict[str, List[Dict]]:
        """Read all preferences/*.csv -> {student_id: [{course_id, preference_rank}]}."""
        prefs: Dict[str, List[Dict]] = {}
        pref_dir = os.path.join(self.workspace, "preferences")
        for fp in sorted(glob.glob(os.path.join(pref_dir, "*.csv"))):
            with open(fp, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sid = row["student_id"]
                    prefs.setdefault(sid, []).append({
                        "course_id": row["course_id"],
                        "preference_rank": int(row["preference_rank"]),
                    })
        # sort by rank
        for sid in prefs:
            prefs[sid].sort(key=lambda p: p["preference_rank"])
        return prefs

    def _load_core_requirements(self) -> dict:
        with open(os.path.join(self.workspace, "core_requirements.json")) as f:
            return json.load(f)

    def _build_section_index(self):
        """Return full section + teacher data from DB."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        sections = [dict(r) for r in conn.execute(
            "SELECT * FROM sections ORDER BY section_id").fetchall()]
        assignments = {}
        for r in conn.execute(
                "SELECT ta.section_id, ta.teacher_id FROM teacher_assignments ta"):
            assignments[r["section_id"]] = r["teacher_id"]
        courses = {}
        for r in conn.execute("SELECT * FROM courses"):
            courses[r["course_id"]] = dict(r)
        students = [dict(r) for r in conn.execute(
            "SELECT * FROM students ORDER BY student_id").fetchall()]
        conn.close()
        return sections, assignments, courses, students

    def _get_active_sections(self, sections, assignments, teacher_avail):
        """Return list of sections where teacher IS available in the section's slot."""
        active = []
        for sec in sections:
            tid = assignments.get(sec["section_id"])
            if tid and sec["time_slot"] in teacher_avail.get(tid, []):
                active.append(sec)
        return active

    # ================================================================
    # STEP
    # ================================================================

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        info: Dict[str, Any] = {"eval_criteria": {}}
        total_score = 0
        max_score = 0

        # Load reference data
        sections_all, assignments, courses_db, students_db = self._build_section_index()
        teacher_avail = self._load_teacher_availability()
        core_reqs = self._load_core_requirements()
        student_prefs = self._load_student_preferences()
        active_sections = self._get_active_sections(sections_all, assignments, teacher_avail)
        active_ids = {s["section_id"] for s in active_sections}

        sec_map = {s["section_id"]: s for s in sections_all}
        course_name_map = {c["course_id"]: c["course_name"] for c in courses_db.values()} \
            if isinstance(courses_db, dict) else {cid: courses_db[cid]["course_name"] for cid in courses_db}

        student_map = {s["student_id"]: s for s in students_db}
        n_students = len(students_db)

        # ----------------------------------------------------------
        # Criterion 1: timetable.csv exists with correct columns (10 pts)
        # ----------------------------------------------------------
        c1_max = 10
        max_score += c1_max
        tt_path = os.path.join(self.workspace, "timetable.csv")
        expected_cols = ["student_id", "student_name", "time_slot",
                         "course_id", "course_name", "section_id", "teacher_id"]
        tt_rows = []
        c1_ok = False
        try:
            with open(tt_path, newline="") as f:
                reader = csv.DictReader(f)
                cols = list(reader.fieldnames or [])
                tt_rows = list(reader)
            if cols == expected_cols:
                c1_ok = True
        except Exception:
            pass

        if c1_ok:
            total_score += c1_max
            info["eval_criteria"]["file_format"] = {
                "passed": True, "score": c1_max, "max_score": c1_max}
        else:
            info["eval_criteria"]["file_format"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "timetable.csv missing or wrong columns"}

        # ----------------------------------------------------------
        # Criterion 2: All students present (15 pts, proportional)
        # ----------------------------------------------------------
        c2_max = 15
        max_score += c2_max
        present_ids = set(r["student_id"] for r in tt_rows)
        expected_ids = set(s["student_id"] for s in students_db)
        frac2 = len(present_ids & expected_ids) / max(n_students, 1)
        c2_score = round(c2_max * frac2, 2)
        info["eval_criteria"]["student_coverage"] = {
            "passed": frac2 == 1.0,
            "score": c2_score,
            "max_score": c2_max,
            **({"reason": f"Missing {n_students - len(present_ids & expected_ids)} students"}
               if frac2 < 1 else {}),
        }
        total_score += c2_score

        # ----------------------------------------------------------
        # Criterion 3: Each student has exactly one entry per time slot,
        #              no duplicates (15 pts, proportional)
        # ----------------------------------------------------------
        c3_max = 15
        max_score += c3_max
        complete_count = 0
        for sid in present_ids & expected_ids:
            stu_rows = [r for r in tt_rows if r["student_id"] == sid]
            slots = [int(r["time_slot"]) for r in stu_rows]
            if sorted(slots) == list(range(1, 7)):
                complete_count += 1
        frac3 = complete_count / max(n_students, 1)
        c3_score = round(c3_max * frac3, 2)
        info["eval_criteria"]["schedule_completeness"] = {
            "passed": frac3 == 1.0,
            "score": c3_score,
            "max_score": c3_max,
            **({"reason": f"Only {complete_count}/{n_students} fully scheduled"} if frac3 < 1 else {}),
        }
        total_score += c3_score

        # ----------------------------------------------------------
        # Criterion 4: Core requirements met (20 pts, proportional)
        # ----------------------------------------------------------
        c4_max = 20
        max_score += c4_max
        core_met = 0
        core_total = 0
        for sid in present_ids & expected_ids:
            s = student_map[sid]
            prog = s["program"]
            grade = str(s["grade"])
            req_courses = core_reqs.get(prog, {}).get(grade, [])
            stu_courses = set(r["course_id"] for r in tt_rows if r["student_id"] == sid)
            for rc in req_courses:
                core_total += 1
                if rc in stu_courses:
                    core_met += 1
        frac4 = core_met / max(core_total, 1)
        c4_score = round(c4_max * frac4, 2)
        info["eval_criteria"]["core_requirements"] = {
            "passed": frac4 == 1.0,
            "score": c4_score,
            "max_score": c4_max,
            **({"reason": f"Core met {core_met}/{core_total}"} if frac4 < 1 else {}),
        }
        total_score += c4_score

        # ----------------------------------------------------------
        # Criterion 5: Section capacity respected (15 pts, proportional)
        # ----------------------------------------------------------
        c5_max = 15
        max_score += c5_max
        enroll_count: Dict[str, int] = {}
        for r in tt_rows:
            enroll_count[r["section_id"]] = enroll_count.get(r["section_id"], 0) + 1
        violations = 0
        checked = 0
        for sec_id, cnt in enroll_count.items():
            checked += 1
            sec = sec_map.get(sec_id)
            if sec and cnt > sec["max_capacity"]:
                violations += 1
        frac5 = 1.0 - violations / max(checked, 1)
        c5_score = round(c5_max * frac5, 2)
        info["eval_criteria"]["capacity_limits"] = {
            "passed": violations == 0,
            "score": c5_score,
            "max_score": c5_max,
            **({"reason": f"{violations} sections over capacity"} if violations else {}),
        }
        total_score += c5_score

        # ----------------------------------------------------------
        # Criterion 6: Teacher availability (sections used are active) (15 pts)
        # ----------------------------------------------------------
        c6_max = 15
        max_score += c6_max
        inactive_uses = 0
        total_uses = 0
        for r in tt_rows:
            total_uses += 1
            if r["section_id"] not in active_ids:
                inactive_uses += 1
        frac6 = 1.0 - inactive_uses / max(total_uses, 1)
        c6_score = round(c6_max * frac6, 2)
        info["eval_criteria"]["teacher_availability"] = {
            "passed": inactive_uses == 0,
            "score": c6_score,
            "max_score": c6_max,
            **({"reason": f"{inactive_uses} assignments to inactive sections"} if inactive_uses else {}),
        }
        total_score += c6_score

        # ----------------------------------------------------------
        # Criterion 7: Summary statistics in response (10 pts)
        # ----------------------------------------------------------
        c7_max = 10
        max_score += c7_max
        pts_per_stat = c7_max / 4.0

        # compute expected stats from the submitted timetable
        exp_total_scheduled = len(present_ids & expected_ids)
        exp_fully = complete_count
        exp_total_assignments = len(tt_rows)
        # avg elective preference rank
        elec_ranks = []
        for r in tt_rows:
            sid = r["student_id"]
            cid = r["course_id"]
            s = student_map.get(sid)
            if s is None:
                continue
            prog = s["program"]
            grade = str(s["grade"])
            req_courses = set(core_reqs.get(prog, {}).get(grade, []))
            if cid not in req_courses:
                # elective — find rank
                sp = student_prefs.get(sid, [])
                for p in sp:
                    if p["course_id"] == cid:
                        elec_ranks.append(p["preference_rank"])
                        break
        exp_avg_rank = round(sum(elec_ranks) / max(len(elec_ranks), 1), 2)

        c7_score = 0
        if str(exp_total_scheduled) in action:
            c7_score += pts_per_stat
        if str(exp_fully) in action:
            c7_score += pts_per_stat
        if str(exp_total_assignments) in action:
            c7_score += pts_per_stat
        if f"{exp_avg_rank:.2f}" in action:
            c7_score += pts_per_stat
        c7_score = round(c7_score, 2)
        info["eval_criteria"]["summary_statistics"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            **({"reason": f"Expected total_scheduled={exp_total_scheduled}, "
                          f"fully_scheduled={exp_fully}, "
                          f"total_assignments={exp_total_assignments}, "
                          f"avg_elective_rank={exp_avg_rank:.2f}"}
               if c7_score < c7_max else {}),
        }
        total_score += c7_score

        total_score = round(total_score, 2)
        info["total_score"] = total_score
        info["max_score"] = max_score
        return total_score / max_score, info

    # ================================================================
    # VERIFY
    # ================================================================

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        # --------------------------------------------------
        # 1. Read workspace files
        # --------------------------------------------------
        core_reqs = self._load_core_requirements()
        student_prefs = self._load_student_preferences()
        teacher_avail = self._load_teacher_availability()

        # Read scheduling policy
        policy = {}
        with open(os.path.join(self.workspace, "scheduling_policy.yaml")) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    k, v = line.split(":", 1)
                    policy[k.strip()] = v.strip()

        # --------------------------------------------------
        # 2. Gather all students via tools (paginated)
        # --------------------------------------------------
        all_students = []
        page = 1
        tool_calls = 0
        while True:
            res = self.tools["list_students"](page=page, page_size=10)
            tool_calls += 1
            all_students.extend(res["students"])
            if page >= res["total_pages"]:
                break
            page += 1

        # Sort students by GPA descending, tiebreak student_id ascending
        all_students.sort(key=lambda s: (-s["gpa"], s["student_id"]))

        # --------------------------------------------------
        # 3. Gather all courses via tools (paginated)
        # --------------------------------------------------
        all_courses = []
        page = 1
        while True:
            res = self.tools["list_courses"](page=page, page_size=10)
            tool_calls += 1
            all_courses.extend(res["courses"])
            if page >= res["total_pages"]:
                break
            page += 1

        course_map = {c["course_id"]: c for c in all_courses}

        # --------------------------------------------------
        # 4. For every course, get sections + teacher info
        # --------------------------------------------------
        course_sections: Dict[str, list] = {}  # course_id -> [section dicts]
        section_teacher: Dict[str, str] = {}   # section_id -> teacher_id

        for c in all_courses:
            res = self.tools["get_course_sections"](course_id=c["course_id"])
            tool_calls += 1
            course_sections[c["course_id"]] = res["sections"]

            for sec in res["sections"]:
                tres = self.tools["get_section_teacher"](section_id=sec["section_id"])
                tool_calls += 1
                if "teacher_id" in tres:
                    section_teacher[sec["section_id"]] = tres["teacher_id"]

        # --------------------------------------------------
        # 5. Determine active sections (teacher available in slot)
        # --------------------------------------------------
        active_section_ids = set()
        sec_lookup = {}  # section_id -> section dict
        for secs in course_sections.values():
            for sec in secs:
                sec_lookup[sec["section_id"]] = sec
                tid = section_teacher.get(sec["section_id"])
                if tid and sec["time_slot"] in teacher_avail.get(tid, []):
                    active_section_ids.add(sec["section_id"])

        # active sections grouped by course
        active_by_course: Dict[str, list] = {}
        for sid in active_section_ids:
            sec = sec_lookup[sid]
            active_by_course.setdefault(sec["course_id"], []).append(sec)

        # --------------------------------------------------
        # 6. Greedy scheduling
        # --------------------------------------------------
        enroll_count: Dict[str, int] = {}  # section_id -> current enrollment

        timetable = []  # list of dicts for timetable.csv

        for stu in all_students:
            sid = stu["student_id"]
            prog = stu["program"]
            grade = str(stu["grade"])
            used_slots: Dict[int, dict] = {}  # slot -> assignment dict

            # --- Core courses first (most-constrained-first ordering) ---
            req_course_ids = core_reqs.get(prog, {}).get(grade, [])

            # Sort core courses by number of available active slots (ascending)
            # so most constrained courses are placed first
            def _core_options(cid):
                secs = active_by_course.get(cid, [])
                return len(set(s["time_slot"] for s in secs))

            ordered_reqs = sorted(req_course_ids, key=lambda cid: (_core_options(cid), cid))

            # Try to assign all core courses; use simple backtracking if greedy fails
            def _assign_cores(remaining, used):
                if not remaining:
                    return {}
                cid = remaining[0]
                secs = active_by_course.get(cid, [])
                candidates = [
                    s for s in secs
                    if s["time_slot"] not in used
                    and enroll_count.get(s["section_id"], 0) < s["max_capacity"]
                ]
                candidates.sort(
                    key=lambda s: (
                        -(s["max_capacity"] - enroll_count.get(s["section_id"], 0)),
                        s["section_id"],
                    )
                )
                for cand in candidates:
                    sub = _assign_cores(remaining[1:], used | {cand["time_slot"]})
                    if sub is not None:
                        sub[cand["time_slot"]] = {
                            "course_id": cid,
                            "section_id": cand["section_id"],
                            "teacher_id": section_teacher.get(cand["section_id"], ""),
                        }
                        return sub
                return None

            core_assignment = _assign_cores(ordered_reqs, set(used_slots.keys()))
            if core_assignment:
                for slot, asgn in core_assignment.items():
                    enroll_count[asgn["section_id"]] = enroll_count.get(asgn["section_id"], 0) + 1
                    used_slots[slot] = asgn

            # --- Electives ---
            prefs = student_prefs.get(sid, [])
            for pref in prefs:
                cid = pref["course_id"]
                secs = active_by_course.get(cid, [])
                candidates = [
                    s for s in secs
                    if s["time_slot"] not in used_slots
                    and enroll_count.get(s["section_id"], 0) < s["max_capacity"]
                ]
                candidates.sort(
                    key=lambda s: (
                        -(s["max_capacity"] - enroll_count.get(s["section_id"], 0)),
                        s["section_id"],
                    )
                )
                if candidates:
                    chosen = candidates[0]
                    enroll_count[chosen["section_id"]] = enroll_count.get(chosen["section_id"], 0) + 1
                    used_slots[chosen["time_slot"]] = {
                        "course_id": cid,
                        "section_id": chosen["section_id"],
                        "teacher_id": section_teacher.get(chosen["section_id"], ""),
                    }

                if len(used_slots) == 6:
                    break

            # Write rows for this student
            for slot in sorted(used_slots):
                a = used_slots[slot]
                cinfo = course_map.get(a["course_id"], {})
                timetable.append({
                    "student_id": sid,
                    "student_name": stu["name"],
                    "time_slot": slot,
                    "course_id": a["course_id"],
                    "course_name": cinfo.get("course_name", ""),
                    "section_id": a["section_id"],
                    "teacher_id": a["teacher_id"],
                })

        # --------------------------------------------------
        # 7. Write timetable.csv
        # --------------------------------------------------
        tt_path = os.path.join(self.workspace, "timetable.csv")
        cols = ["student_id", "student_name", "time_slot",
                "course_id", "course_name", "section_id", "teacher_id"]
        with open(tt_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for row in timetable:
                writer.writerow(row)

        # --------------------------------------------------
        # 8. Compute summary statistics
        # --------------------------------------------------
        student_ids_in_tt = set(r["student_id"] for r in timetable)
        total_scheduled = len(student_ids_in_tt)

        fully_scheduled = 0
        for sid in student_ids_in_tt:
            stu_rows = [r for r in timetable if r["student_id"] == sid]
            if len(stu_rows) == 6:
                fully_scheduled += 1

        total_assignments = len(timetable)

        # avg elective preference rank
        elec_ranks = []
        for r in timetable:
            sid = r["student_id"]
            cid = r["course_id"]
            s = next((st for st in all_students if st["student_id"] == sid), None)
            if s is None:
                continue
            req_courses = set(core_reqs.get(s["program"], {}).get(str(s["grade"]), []))
            if cid not in req_courses:
                sp = student_prefs.get(sid, [])
                for p in sp:
                    if p["course_id"] == cid:
                        elec_ranks.append(p["preference_rank"])
                        break
        avg_rank = round(sum(elec_ranks) / max(len(elec_ranks), 1), 2)

        action = (
            f"Timetable generation complete. "
            f"total_students_scheduled: {total_scheduled}, "
            f"fully_scheduled_students: {fully_scheduled}, "
            f"total_assignments: {total_assignments}, "
            f"avg_elective_preference_rank: {avg_rank:.2f}"
        )

        return self.step(action)
