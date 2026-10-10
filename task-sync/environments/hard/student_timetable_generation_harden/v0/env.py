"""
Student Timetable Generation - Environment (hardened tool surface)

Hardened surface (M0 + M1 + M4):
  - M1: list_students and list_courses each take a single JSON-encoded string
    `filter` parameter; malformed JSON, wrong-typed values, or unsupported
    keys produce recoverable API-style errors.
  - M4: a new create_enrollment write tool records each student-section
    placement into the database through a deeply nested request payload
    (parent + properties) validated layer by layer with Notion-style error
    messages. step() gains one DB-state criterion (SOURCE had no write tool).
  - Success and error responses share no keys; tools never raise.
Task semantics, data generation, ground-truth scoring of the timetable, and
the deliverable contract are unchanged from the base environment.
"""

import os
import ast
import json
import csv
import sqlite3
import glob
import hashlib
from typing import Tuple, Dict, List, Any


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ---------------------------------------------------------------------------
# Hardened tool-surface helpers
# ---------------------------------------------------------------------------

def _request_id(message: str) -> str:
    return "req_" + hashlib.md5(message.encode("utf-8")).hexdigest()[:12]


def _error(status: int, code: str, message: str) -> dict:
    """Error responses share NO keys with success responses."""
    return {
        "status": status,
        "object": "error",
        "code": code,
        "message": message,
        "request_id": _request_id(f"{status}:{code}:{message}"),
    }


def _envelope(payload) -> dict:
    """MCP-style envelope: payload is JSON-encoded into a text content block."""
    return {
        "meta": None,
        "content": [
            {"type": "text",
             "text": json.dumps(payload, ensure_ascii=False, default=str)}
        ],
        "isError": False,
    }


def _shape(value) -> str:
    """Short rendering of a wrong-typed value for error text."""
    if value is None:
        return "'undefined'"
    r = repr(value)
    if len(r) > 60:
        r = r[:57] + "..."
    return f"'{r}'"


def _parse_json_string_param(raw, param_name: str):
    if raw is None or raw == "":
        return {}, None
    if isinstance(raw, (dict, list)):
        return None, _error(400, "invalid_request",
            f"body.{param_name} should be a JSON-encoded string, instead was an object. "
            f"Serialize it to a JSON string before passing it.")
    if not isinstance(raw, str):
        return None, _error(400, "invalid_request",
            f"body.{param_name} should be a JSON-encoded string, instead was {type(raw).__name__}.")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, _error(400, "invalid_json",
            f"Failed to parse {param_name}: {e.msg}: line {e.lineno} column {e.colno} (char {e.pos})")
    if not isinstance(value, dict):
        return None, _error(400, "invalid_request",
            f"body.{param_name} should encode a JSON object, instead was {type(value).__name__}.")
    return value, None


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
            "Returns a paginated list of student records. Filtering is "
            "expressed as a JSON-encoded string, e.g. "
            "filter='{\"grade\": 10, \"program\": \"Science\"}'. Supported "
            "filter properties: grade (integer, 9-12) and program (string). "
            "Each result entry contains student_id, name, grade, program, "
            "and gpa. Each page contains at most page_size entries."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"grade\": 11, \"program\": \"Arts\"}'. "
                        "Pass '{}' or omit for no filtering."
                    ),
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
    def list_students(self, filter: Any = None, page=1, page_size=10):
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"grade", "program"}
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: grade, program.")

        clauses = []
        params: list = []
        if "grade" in parsed:
            grade = parsed["grade"]
            if not isinstance(grade, int) or isinstance(grade, bool):
                return _error(400, "validation_error",
                    f"body.filter.grade should be an integer, instead was {_shape(grade)}.")
            clauses.append("grade = ?")
            params.append(grade)
        if "program" in parsed:
            program = parsed["program"]
            if not isinstance(program, str):
                return _error(400, "validation_error",
                    f"body.filter.program should be a string, instead was {_shape(program)}.")
            clauses.append("program = ?")
            params.append(program)

        page_size = min(int(page_size), 10)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM students"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
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
            return _error(404, "object_not_found",
                          f"Could not find student with ID: {student_id}.")
        return dict(row)

    @tool(
        description=(
            "Returns a paginated list of course records. Filtering is "
            "expressed as a JSON-encoded string, e.g. "
            "filter='{\"course_type\": \"core\"}'. Supported filter "
            "properties: course_type (core | elective) and subject_area "
            "(string). Each result entry contains course_id, course_name, "
            "course_type, and subject_area."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "JSON-encoded filter object as a string. Example: "
                        "'{\"course_type\": \"elective\", \"subject_area\": \"Music\"}'. "
                        "Pass '{}' or omit for no filtering."
                    ),
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
    def list_courses(self, filter: Any = None, page=1, page_size=10):
        parsed, err = _parse_json_string_param(filter, "filter")
        if err is not None:
            return err

        supported = {"course_type", "subject_area"}
        for key in parsed:
            if key not in supported:
                return _error(400, "validation_error",
                    f"body.filter.{key} is not a supported filter property. "
                    f"Supported properties: course_type, subject_area.")

        clauses = []
        params: list = []
        if "course_type" in parsed:
            course_type = parsed["course_type"]
            if not isinstance(course_type, str) or course_type not in ("core", "elective"):
                return _error(400, "validation_error",
                    f"body.filter.course_type should be one of \"core\", \"elective\", "
                    f"instead was {_shape(course_type)}.")
            clauses.append("course_type = ?")
            params.append(course_type)
        if "subject_area" in parsed:
            subject_area = parsed["subject_area"]
            if not isinstance(subject_area, str):
                return _error(400, "validation_error",
                    f"body.filter.subject_area should be a string, instead was "
                    f"{_shape(subject_area)}.")
            clauses.append("subject_area = ?")
            params.append(subject_area)

        page_size = min(int(page_size), 10)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM courses"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
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
        exists = conn.execute(
            "SELECT 1 FROM courses WHERE course_id = ?", (course_id,)
        ).fetchone()
        if exists is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find course with ID: {course_id}.")
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
            return _error(404, "object_not_found",
                          f"Could not find teacher assignment for section with ID: {section_id}.")
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
        exists = conn.execute(
            "SELECT 1 FROM teachers WHERE teacher_id = ?", (teacher_id,)
        ).fetchone()
        if exists is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find teacher with ID: {teacher_id}.")
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
            return _error(404, "object_not_found",
                          f"Could not find course with ID: {course_id}.")
        return dict(row)

    @tool(
        description=(
            "Creates an enrollment: places a student into a course section's "
            "roster so the official database reflects the assignment. The "
            "request body must contain a `parent` object identifying the "
            "receiving section roster and a `properties` object with a "
            "`Student` reference property. Example body: "
            "{\"parent\": {\"type\": \"section_roster\", \"section_id\": "
            "\"SEC0012\"}, \"properties\": {\"Student\": {\"type\": "
            "\"reference\", \"reference\": {\"student_id\": \"STU0003\"}}}}. "
            "An optional `Note` rich_text property may be included in "
            "`properties`. On success the enrollment is recorded in the "
            "section's roster."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "The enrollment request body.",
                    "properties": {
                        "parent": {
                            "type": "object",
                            "description": (
                                "The section roster that receives the student. "
                                "Must contain type='section_roster' and a "
                                "section_id string."
                            ),
                            "properties": {
                                "type": {"type": "string"},
                                "section_id": {"type": "string"},
                            },
                            "required": ["type", "section_id"],
                            "additionalProperties": True,
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Enrollment properties. Must include a 'Student' "
                                "reference property. May include a 'Note' "
                                "rich_text property."
                            ),
                            "additionalProperties": True,
                        },
                    },
                    "required": ["parent", "properties"],
                    "additionalProperties": True,
                },
            },
            "required": ["payload"],
        },
    )
    def create_enrollment(self, payload: Any = None) -> dict:
        # --- Layered request-body validation, one error at a time ---
        if payload is None:
            return _error(400, "validation_error",
                          "body should be defined, instead was 'undefined'.")
        if isinstance(payload, str):
            return _error(400, "validation_error",
                          f"body should be an object, instead was {_shape(payload)}. "
                          f"Pass a JSON object, not a string.")
        if not isinstance(payload, dict):
            return _error(400, "validation_error",
                          f"body should be an object, instead was {_shape(payload)}.")

        parent = payload.get("parent")
        if parent is None:
            return _error(400, "validation_error",
                          "body.parent should be defined, instead was 'undefined'.")
        if not isinstance(parent, dict):
            return _error(400, "validation_error",
                          f"body.parent should be an object, instead was {_shape(parent)}.")
        if parent.get("type") != "section_roster":
            return _error(400, "validation_error",
                          f"body.parent.type should be \"section_roster\", instead was "
                          f"{_shape(parent.get('type'))}.")
        section_id = parent.get("section_id")
        if not isinstance(section_id, str) or not section_id:
            return _error(400, "validation_error",
                          f"body.parent.section_id should be a non-empty string, instead was "
                          f"{_shape(section_id)}.")

        props = payload.get("properties")
        if props is None:
            return _error(400, "validation_error",
                          "body.properties should be defined, instead was 'undefined'.")
        if not isinstance(props, dict):
            return _error(400, "validation_error",
                          f"body.properties should be an object, instead was {_shape(props)}.")

        student_prop = props.get("Student")
        if student_prop is None:
            return _error(400, "validation_error",
                          "body.properties.Student should be defined, instead was 'undefined'.")
        if not isinstance(student_prop, dict):
            return _error(400, "validation_error",
                          f"body.properties.Student should be an object, instead was "
                          f"{_shape(student_prop)}.")
        if student_prop.get("type") != "reference":
            return _error(400, "validation_error",
                          f"body.properties.Student.type should be \"reference\", instead was "
                          f"{_shape(student_prop.get('type'))}.")
        reference = student_prop.get("reference")
        if not isinstance(reference, dict):
            return _error(400, "validation_error",
                          f"body.properties.Student.reference should be an object, instead was "
                          f"{_shape(reference)}.")
        student_id = reference.get("student_id")
        if not isinstance(student_id, str) or not student_id:
            return _error(400, "validation_error",
                          f"body.properties.Student.reference.student_id should be a non-empty "
                          f"string, instead was {_shape(student_id)}.")

        note_prop = props.get("Note")
        if note_prop is not None:
            if not isinstance(note_prop, dict) or note_prop.get("type") != "rich_text":
                return _error(400, "validation_error",
                              "body.properties.Note.type should be \"rich_text\".")
            rich = note_prop.get("rich_text")
            if not isinstance(rich, list):
                return _error(400, "validation_error",
                              f"body.properties.Note.rich_text should be an array, instead was "
                              f"{_shape(rich)}.")
            for i, item in enumerate(rich):
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("text"), dict)
                    or not isinstance(item["text"].get("content"), str)
                ):
                    return _error(400, "validation_error",
                                  f"body.properties.Note.rich_text[{i}].text.content should be "
                                  f"a string, instead was 'undefined'.")

        # --- Business validation ---
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT time_slot FROM sections WHERE section_id = ?", (section_id,))
        sec_row = c.fetchone()
        if sec_row is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find section roster with ID: {section_id}.")
        c.execute("SELECT 1 FROM students WHERE student_id = ?", (student_id,))
        if c.fetchone() is None:
            conn.close()
            return _error(404, "object_not_found",
                          f"Could not find student with ID: {student_id}.")

        c.execute(
            """CREATE TABLE IF NOT EXISTS enrollments (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   student_id TEXT NOT NULL,
                   section_id TEXT NOT NULL,
                   UNIQUE(student_id, section_id)
               )"""
        )
        c.execute(
            "SELECT 1 FROM enrollments WHERE student_id = ? AND section_id = ?",
            (student_id, section_id),
        )
        if c.fetchone() is not None:
            conn.close()
            return _error(400, "validation_error",
                          f"Student '{student_id}' is already enrolled in section "
                          f"'{section_id}'.")

        # --- Perform enrollment ---
        c.execute(
            "INSERT INTO enrollments (student_id, section_id) VALUES (?, ?)",
            (student_id, section_id),
        )
        conn.commit()
        conn.close()

        # Success response: deep echo, shape entirely different from errors.
        return {
            "object": "enrollment",
            "id": "enr_" + hashlib.md5(f"{student_id}:{section_id}".encode()).hexdigest()[:10],
            "parent": {"type": "section_roster", "section_id": section_id},
            "properties": {
                "Student": {"type": "reference", "reference": {"student_id": student_id}},
                "TimeSlot": {"type": "number", "number": sec_row[0]},
            },
            "created": True,
        }

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

        # ----------------------------------------------------------
        # Criterion 8: Enrollments recorded in DB via create_enrollment
        #              (10 pts, proportional; M4 DB-state criterion)
        # ----------------------------------------------------------
        c8_max = 10
        max_score += c8_max
        conn = sqlite3.connect(self.db_path)
        try:
            db_enr = set(conn.execute(
                "SELECT student_id, section_id FROM enrollments").fetchall())
        except sqlite3.OperationalError:
            db_enr = set()
        conn.close()
        matched = sum(1 for r in tt_rows
                      if (r["student_id"], r["section_id"]) in db_enr)
        frac8 = matched / max(len(tt_rows), 1)
        c8_score = round(c8_max * frac8, 2)
        info["eval_criteria"]["db_enrollments_recorded"] = {
            "passed": len(tt_rows) > 0 and matched == len(tt_rows),
            "score": c8_score,
            "max_score": c8_max,
            **({"reason": f"{matched}/{len(tt_rows)} timetable assignments recorded in DB"}
               if matched < len(tt_rows) or not tt_rows else {}),
        }
        total_score += c8_score

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

        Note: the hardened tool surface requires JSON-encoded string filters
        for list_students/list_courses and nested request payloads for
        create_enrollment.
        """
        tool_calls = 0

        def _call(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

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
        while True:
            res = _call("list_students", page=page, page_size=10)
            all_students.extend(res["students"])
            if page >= res["total_pages"]:
                break
            page += 1

        # Sort students by GPA descending, tiebreak student_id ascending
        all_students.sort(key=lambda s: (-s["gpa"], s["student_id"]))

        # --------------------------------------------------
        # 3. Gather all courses via tools (JSON-string filters, paginated)
        # --------------------------------------------------
        all_courses = []
        for ctype in ("core", "elective"):
            filter_str = json.dumps({"course_type": ctype})
            page = 1
            while True:
                res = _call("list_courses", filter=filter_str, page=page, page_size=10)
                all_courses.extend(res["courses"])
                if page >= res["total_pages"]:
                    break
                page += 1
        all_courses.sort(key=lambda c: c["course_id"])

        course_map = {c["course_id"]: c for c in all_courses}

        # --------------------------------------------------
        # 4. For every course, get sections + teacher info
        # --------------------------------------------------
        course_sections: Dict[str, list] = {}  # course_id -> [section dicts]
        section_teacher: Dict[str, str] = {}   # section_id -> teacher_id

        for c in all_courses:
            res = _call("get_course_sections", course_id=c["course_id"])
            course_sections[c["course_id"]] = res["sections"]

            for sec in res["sections"]:
                tres = _call("get_section_teacher", section_id=sec["section_id"])
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

            # Record enrollments via the nested write API and write rows
            for slot in sorted(used_slots):
                a = used_slots[slot]
                result = _call(
                    "create_enrollment",
                    payload={
                        "parent": {"type": "section_roster",
                                   "section_id": a["section_id"]},
                        "properties": {
                            "Student": {
                                "type": "reference",
                                "reference": {"student_id": sid},
                            },
                        },
                    },
                )
                if not (result.get("object") == "enrollment" and result.get("created")):
                    continue
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

        print(f"[verify] total tool calls: {tool_calls}")
        return self.step(action)
