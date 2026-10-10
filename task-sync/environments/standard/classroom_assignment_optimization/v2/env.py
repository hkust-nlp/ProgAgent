import sqlite3
import os
import json
import csv
import math
import yaml
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

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description=(
            "List teachers with pagination. Returns a page of teacher records "
            "including teacher_id, name, department, max_periods_per_day, and "
            "max_periods_per_week."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (default 10).",
                },
            },
            "required": ["page"],
        },
    )
    def list_teachers(self, page: int, page_size: int = 10) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        total = cur.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]
        offset = (page - 1) * page_size
        rows = cur.execute(
            "SELECT * FROM teachers ORDER BY teacher_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        teachers = [dict(r) for r in rows]
        return {
            "teachers": teachers,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": offset + page_size < total,
        }

    @tool(
        description=(
            "Get all subject certifications for a specific teacher. "
            "Returns a list of certification records with subject and "
            "certification_level."
        ),
        parameters={
            "type": "object",
            "properties": {
                "teacher_id": {
                    "type": "integer",
                    "description": "The teacher's ID.",
                },
            },
            "required": ["teacher_id"],
        },
    )
    def get_teacher_certifications(self, teacher_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT cert_id, subject, certification_level "
            "FROM certifications WHERE teacher_id = ? ORDER BY cert_id",
            (teacher_id,),
        ).fetchall()
        conn.close()
        return {
            "teacher_id": teacher_id,
            "certifications": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "List classes with pagination. Returns class_id, class_name, "
            "subject, grade_level, teacher_id, and num_students. "
            "Optionally filter by subject or grade_level."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (default 10).",
                },
                "subject": {
                    "type": "string",
                    "description": "Optional subject filter.",
                },
                "grade_level": {
                    "type": "integer",
                    "description": "Optional grade level filter.",
                },
            },
            "required": ["page"],
        },
    )
    def list_classes(self, page: int, page_size: int = 10,
                     subject: str = None, grade_level: int = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        clauses = []
        params: list = []
        if subject:
            clauses.append("subject = ?")
            params.append(subject)
        if grade_level is not None:
            clauses.append("grade_level = ?")
            params.append(grade_level)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM classes{where}", params
        ).fetchone()[0]
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT * FROM classes{where} ORDER BY class_id "
            f"LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        conn.close()
        return {
            "classes": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": offset + page_size < total,
        }

    @tool(
        description=(
            "List rooms with pagination. Returns room_id, room_name, "
            "capacity, room_type, building, and floor. "
            "Optionally filter by room_type or minimum capacity."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (default 10).",
                },
                "room_type": {
                    "type": "string",
                    "description": "Optional room type filter.",
                },
                "min_capacity": {
                    "type": "integer",
                    "description": "Optional minimum capacity filter.",
                },
            },
            "required": ["page"],
        },
    )
    def list_rooms(self, page: int, page_size: int = 10,
                   room_type: str = None, min_capacity: int = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        clauses = []
        params: list = []
        if room_type:
            clauses.append("room_type = ?")
            params.append(room_type)
        if min_capacity is not None:
            clauses.append("capacity >= ?")
            params.append(min_capacity)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM rooms{where}", params
        ).fetchone()[0]
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT * FROM rooms{where} ORDER BY room_id "
            f"LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        conn.close()
        return {
            "rooms": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": offset + page_size < total,
        }

    @tool(
        description=(
            "Get detailed information for a single room by room_id. "
            "Returns room_id, room_name, capacity, room_type, building, "
            "and floor."
        ),
        parameters={
            "type": "object",
            "properties": {
                "room_id": {
                    "type": "integer",
                    "description": "The room's ID.",
                },
            },
            "required": ["room_id"],
        },
    )
    def get_room_details(self, room_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM rooms WHERE room_id = ?", (room_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Room {room_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Get detailed information for a single class by class_id. "
            "Returns class_id, class_name, subject, grade_level, "
            "teacher_id, and num_students."
        ),
        parameters={
            "type": "object",
            "properties": {
                "class_id": {
                    "type": "integer",
                    "description": "The class's ID.",
                },
            },
            "required": ["class_id"],
        },
    )
    def get_class_details(self, class_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM classes WHERE class_id = ?", (class_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Class {class_id} not found."}
        return dict(row)

    # ------------------------------------------------------------------
    # Helpers used by step / verify
    # ------------------------------------------------------------------

    def _load_ground_truth(self):
        """Load all reference data needed for evaluation."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        teachers = {
            r["teacher_id"]: dict(r)
            for r in conn.execute("SELECT * FROM teachers").fetchall()
        }
        classes = {
            r["class_id"]: dict(r)
            for r in conn.execute("SELECT * FROM classes").fetchall()
        }
        rooms = {
            r["room_id"]: dict(r)
            for r in conn.execute("SELECT * FROM rooms").fetchall()
        }
        certs = {}
        for r in conn.execute("SELECT * FROM certifications").fetchall():
            certs.setdefault(r["teacher_id"], []).append(r["subject"])
        conn.close()

        # Policy
        with open(os.path.join(self.workspace,
                               "scheduling_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        period_dur = policy["period_duration_minutes"]

        # Instructional minutes
        instr = {}
        with open(os.path.join(self.workspace,
                               "instructional_minutes.csv")) as f:
            for row in csv.DictReader(f):
                instr[(row["subject"], int(row["grade_level"]))] = int(
                    row["min_weekly_minutes"]
                )

        # Subject equipment requirements
        with open(os.path.join(self.workspace,
                               "subject_equipment_requirements.json")) as f:
            subj_equip = json.load(f)

        # Room equipment from YAML files
        room_equip: Dict[int, List[str]] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("room_equipment_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                for entry in data["rooms"]:
                    room_equip[entry["room_id"]] = [
                        e["name"] for e in entry["equipment"]
                    ]

        # Teacher unavailability
        teacher_unavail: Dict[int, set] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if (fname.startswith("teacher_availability_")
                    and fname.endswith(".csv")):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        tid = int(row["teacher_id"])
                        teacher_unavail.setdefault(tid, set()).add(
                            (row["day"], int(row["period"]))
                        )

        # Compute required periods per class
        class_periods = {}
        for cid, c in classes.items():
            key = (c["subject"], c["grade_level"])
            mins = instr.get(key, 135)
            class_periods[cid] = math.ceil(mins / period_dur)

        return {
            "teachers": teachers,
            "classes": classes,
            "rooms": rooms,
            "certs": certs,
            "policy": policy,
            "subj_equip": subj_equip,
            "room_equip": room_equip,
            "teacher_unavail": teacher_unavail,
            "class_periods": class_periods,
        }

    # ------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------

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
        gt = self._load_ground_truth()
        classes = gt["classes"]
        rooms = gt["rooms"]
        teachers = gt["teachers"]
        subj_equip = gt["subj_equip"]
        room_equip = gt["room_equip"]
        teacher_unavail = gt["teacher_unavail"]
        class_periods = gt["class_periods"]
        policy = gt["policy"]

        criteria: Dict[str, Dict[str, Any]] = {}

        # ------ Criterion 1: schedule file valid (10 pts) ------
        schedule_path = os.path.join(self.workspace, "weekly_schedule.csv")
        required_cols = {"day", "period", "class_id", "class_name",
                         "room_id", "room_name", "teacher_id", "teacher_name"}
        sched_rows = []
        c1_pass = True
        c1_reason = ""
        try:
            with open(schedule_path) as f:
                reader = csv.DictReader(f)
                cols = set(reader.fieldnames or [])
                if not required_cols.issubset(cols):
                    c1_pass = False
                    c1_reason = (
                        f"Missing columns: {required_cols - cols}"
                    )
                else:
                    for row in reader:
                        sched_rows.append(row)
                    if len(sched_rows) == 0:
                        c1_pass = False
                        c1_reason = "Schedule file is empty."
        except FileNotFoundError:
            c1_pass = False
            c1_reason = "weekly_schedule.csv not found."
        except Exception as e:
            c1_pass = False
            c1_reason = f"Error reading schedule: {e}"

        criteria["schedule_file_valid"] = {
            "passed": c1_pass,
            "score": 10 if c1_pass else 0,
            "max_score": 10,
        }
        if not c1_pass:
            criteria["schedule_file_valid"]["reason"] = c1_reason

        # If file invalid, remaining checks score 0
        if not c1_pass:
            for name, mx in [("all_classes_covered", 20),
                             ("no_room_conflicts", 15),
                             ("no_teacher_conflicts", 15),
                             ("capacity_respected", 15),
                             ("equipment_satisfied", 15),
                             ("summary_response", 10)]:
                criteria[name] = {
                    "passed": False, "score": 0, "max_score": mx,
                    "reason": "Schedule file invalid; cannot evaluate.",
                }
            total = sum(c["score"] for c in criteria.values())
            mx_total = sum(c["max_score"] for c in criteria.values())
            return total / mx_total, {
                "eval_criteria": criteria,
                "total_score": total,
                "max_score": mx_total,
            }

        # Parse rows into typed dicts
        parsed = []
        for row in sched_rows:
            parsed.append({
                "day": row["day"].strip(),
                "period": int(row["period"]),
                "class_id": int(row["class_id"]),
                "class_name": row["class_name"].strip(),
                "room_id": int(row["room_id"]),
                "room_name": row["room_name"].strip(),
                "teacher_id": int(row["teacher_id"]),
                "teacher_name": row["teacher_name"].strip(),
            })

        # ------ Criterion 2: all classes covered (20 pts) ------
        class_counts: Dict[int, int] = {}
        for r in parsed:
            class_counts[r["class_id"]] = class_counts.get(
                r["class_id"], 0) + 1

        c2_errors = []
        for cid, expected in class_periods.items():
            actual = class_counts.get(cid, 0)
            if actual != expected:
                cname = classes[cid]["class_name"]
                c2_errors.append(
                    f"{cname}(id={cid}): expected {expected}, got {actual}"
                )
        # Also check for unknown class ids in schedule
        for cid in class_counts:
            if cid not in classes:
                c2_errors.append(f"Unknown class_id {cid} in schedule.")

        c2_pass = len(c2_errors) == 0
        c2_score = 20 if c2_pass else max(
            0, 20 - 2 * len(c2_errors))
        criteria["all_classes_covered"] = {
            "passed": c2_pass,
            "score": c2_score,
            "max_score": 20,
        }
        if not c2_pass:
            criteria["all_classes_covered"]["reason"] = (
                f"{len(c2_errors)} mismatches: " +
                "; ".join(c2_errors[:5])
            )

        # ------ Criterion 3: no room conflicts (15 pts) ------
        room_slots: Dict[tuple, list] = {}
        for r in parsed:
            key = (r["day"], r["period"], r["room_id"])
            room_slots.setdefault(key, []).append(r["class_id"])
        conflicts_room = {k: v for k, v in room_slots.items() if len(v) > 1}
        c3_pass = len(conflicts_room) == 0
        c3_score = 15 if c3_pass else max(0, 15 - 3 * len(conflicts_room))
        criteria["no_room_conflicts"] = {
            "passed": c3_pass,
            "score": c3_score,
            "max_score": 15,
        }
        if not c3_pass:
            criteria["no_room_conflicts"]["reason"] = (
                f"{len(conflicts_room)} room-slot conflicts found."
            )

        # ------ Criterion 4: no teacher conflicts (15 pts) ------
        teacher_slots: Dict[tuple, list] = {}
        for r in parsed:
            key = (r["day"], r["period"], r["teacher_id"])
            teacher_slots.setdefault(key, []).append(r["class_id"])
        conflicts_teacher = {
            k: v for k, v in teacher_slots.items() if len(v) > 1
        }
        c4_pass = len(conflicts_teacher) == 0
        c4_score = 15 if c4_pass else max(
            0, 15 - 3 * len(conflicts_teacher))
        criteria["no_teacher_conflicts"] = {
            "passed": c4_pass,
            "score": c4_score,
            "max_score": 15,
        }
        if not c4_pass:
            criteria["no_teacher_conflicts"]["reason"] = (
                f"{len(conflicts_teacher)} teacher-slot conflicts found."
            )

        # ------ Criterion 5: capacity respected (15 pts) ------
        cap_violations = 0
        for r in parsed:
            cid = r["class_id"]
            rid = r["room_id"]
            if cid in classes and rid in rooms:
                if rooms[rid]["capacity"] < classes[cid]["num_students"]:
                    cap_violations += 1
        c5_pass = cap_violations == 0
        c5_score = 15 if c5_pass else max(0, 15 - 2 * cap_violations)
        criteria["capacity_respected"] = {
            "passed": c5_pass,
            "score": c5_score,
            "max_score": 15,
        }
        if not c5_pass:
            criteria["capacity_respected"]["reason"] = (
                f"{cap_violations} capacity violations."
            )

        # ------ Criterion 6: equipment satisfied (15 pts) ------
        equip_violations = 0
        for r in parsed:
            cid = r["class_id"]
            rid = r["room_id"]
            if cid in classes and rid in room_equip:
                subj = classes[cid]["subject"]
                required = set(subj_equip.get(subj, []))
                available = set(room_equip.get(rid, []))
                if not required.issubset(available):
                    equip_violations += 1
        c6_pass = equip_violations == 0
        c6_score = 15 if c6_pass else max(0, 15 - 2 * equip_violations)
        criteria["equipment_satisfied"] = {
            "passed": c6_pass,
            "score": c6_score,
            "max_score": 15,
        }
        if not c6_pass:
            criteria["equipment_satisfied"]["reason"] = (
                f"{equip_violations} equipment violations."
            )

        # ------ Criterion 7: summary response (10 pts) ------
        # Expect: "Scheduling Summary: X classes across Y periods using Z rooms"
        import re
        total_classes_gt = len(classes)
        total_periods_gt = sum(class_periods.values())
        # Count rooms actually needed (any room that is compatible with at
        # least one class can be used; we check the agent's self-reported
        # value against their actual schedule).
        agent_rooms_used = len(set(r["room_id"] for r in parsed))
        agent_classes = len(set(r["class_id"] for r in parsed))
        agent_periods = len(parsed)

        pattern = (
            r"Scheduling Summary:\s*(\d+)\s*classes?\s+across\s+(\d+)\s*"
            r"periods?\s+using\s+(\d+)\s*rooms?"
        )
        match = re.search(pattern, action, re.IGNORECASE)
        c7_pass = False
        c7_reason = ""
        if match:
            rep_cls = int(match.group(1))
            rep_per = int(match.group(2))
            rep_rm = int(match.group(3))
            if (rep_cls == agent_classes
                    and rep_per == agent_periods
                    and rep_rm == agent_rooms_used):
                c7_pass = True
            else:
                c7_reason = (
                    f"Reported {rep_cls}/{rep_per}/{rep_rm} but schedule "
                    f"has {agent_classes}/{agent_periods}/{agent_rooms_used}."
                )
        else:
            c7_reason = "Summary line not found in response."

        criteria["summary_response"] = {
            "passed": c7_pass,
            "score": 10 if c7_pass else 0,
            "max_score": 10,
        }
        if not c7_pass:
            criteria["summary_response"]["reason"] = c7_reason

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
        import math as _math

        # ---- 1. Collect all teachers via paginated tool calls ----
        all_teachers = []
        page = 1
        while True:
            result = self.tools["list_teachers"](page=page, page_size=10)
            all_teachers.extend(result["teachers"])
            if not result["has_more"]:
                break
            page += 1

        # ---- 2. Collect certifications per teacher ----
        teacher_certs: Dict[int, List[str]] = {}
        for t in all_teachers:
            res = self.tools["get_teacher_certifications"](
                teacher_id=t["teacher_id"]
            )
            teacher_certs[t["teacher_id"]] = [
                c["subject"] for c in res["certifications"]
            ]

        # ---- 3. Collect all classes ----
        all_classes = []
        page = 1
        while True:
            result = self.tools["list_classes"](page=page, page_size=10)
            all_classes.extend(result["classes"])
            if not result["has_more"]:
                break
            page += 1

        # ---- 4. Collect all rooms ----
        all_rooms = []
        page = 1
        while True:
            result = self.tools["list_rooms"](page=page, page_size=10)
            all_rooms.extend(result["rooms"])
            if not result["has_more"]:
                break
            page += 1

        # ---- 5. Read workspace files ----
        # 5a. Scheduling policy
        with open(os.path.join(self.workspace,
                               "scheduling_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        period_dur = policy["period_duration_minutes"]
        days = policy["days"]
        periods_per_day = policy["periods_per_day"]

        # 5b. Instructional minutes
        instr_mins: Dict[tuple, int] = {}
        with open(os.path.join(self.workspace,
                               "instructional_minutes.csv")) as f:
            for row in csv.DictReader(f):
                instr_mins[(row["subject"], int(row["grade_level"]))] = int(
                    row["min_weekly_minutes"]
                )

        # 5c. Subject equipment requirements
        with open(os.path.join(self.workspace,
                               "subject_equipment_requirements.json")) as f:
            subj_equip = json.load(f)

        # 5d. Room equipment from YAML files
        room_equip: Dict[int, List[str]] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("room_equipment_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                for entry in data["rooms"]:
                    room_equip[entry["room_id"]] = [
                        e["name"] for e in entry["equipment"]
                    ]

        # 5e. Teacher unavailability
        teacher_unavail: Dict[int, set] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if (fname.startswith("teacher_availability_")
                    and fname.endswith(".csv")):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        tid = int(row["teacher_id"])
                        teacher_unavail.setdefault(tid, set()).add(
                            (row["day"], int(row["period"]))
                        )

        # 5f. Room priority rules (read to honour best-fit, etc.)
        with open(os.path.join(self.workspace,
                               "room_priority_rules.txt")) as _:
            pass  # rules are applied in scheduling logic below

        # ---- 6. Compute required periods per class ----
        class_periods: Dict[int, int] = {}
        for c in all_classes:
            key = (c["subject"], c["grade_level"])
            mins = instr_mins.get(key, 135)
            class_periods[c["class_id"]] = _math.ceil(mins / period_dur)

        # ---- 7. Determine compatible rooms per class ----
        room_map = {r["room_id"]: r for r in all_rooms}
        teacher_map = {t["teacher_id"]: t for t in all_teachers}

        # Build set of specialist room types
        specialist_room_types = {
            "computer_lab", "science_lab", "art_studio",
            "music_room", "gymnasium",
        }

        # Map subject -> required room types (subjects needing specialist
        # equipment can only go in rooms that have that equipment)
        class_compat: Dict[int, List[int]] = {}
        for c in all_classes:
            required = set(subj_equip.get(c["subject"], []))
            compat = []
            for r in all_rooms:
                avail_eq = set(room_equip.get(r["room_id"], []))
                # Equipment check
                if not required.issubset(avail_eq):
                    continue
                # Specialist-room exclusivity: regular subjects may NOT
                # use specialist rooms.
                if (not required
                        and r["room_type"] in specialist_room_types):
                    continue
                # Capacity check
                if r["capacity"] < c["num_students"]:
                    continue
                compat.append(r["room_id"])

            # Sort compatible rooms by best-fit (smallest surplus), then
            # by room_id as tie-breaker (rules 2 & 4).
            compat.sort(key=lambda rid: (
                room_map[rid]["capacity"] - c["num_students"],
                rid,
            ))
            class_compat[c["class_id"]] = compat

        # ---- 8. Greedy scheduling ----
        # Sort classes: larger enrollment first (rule 3), then fewer
        # compatible rooms first (most constrained).
        sorted_classes = sorted(
            all_classes,
            key=lambda c: (-c["num_students"],
                           len(class_compat[c["class_id"]])),
        )

        PERIODS = list(range(1, periods_per_day + 1))

        room_schedule: set = set()        # (day, period, room_id)
        teacher_schedule: set = set()     # (day, period, teacher_id)
        teacher_daily: Dict[tuple, int] = {}   # (tid, day) -> count
        teacher_weekly: Dict[int, int] = {}    # tid -> count

        schedule_rows = []

        for c in sorted_classes:
            cid = c["class_id"]
            tid = c["teacher_id"]
            needed = class_periods[cid]
            compat = class_compat[cid]
            unavail = teacher_unavail.get(tid, set())
            t_info = teacher_map[tid]
            max_daily = t_info["max_periods_per_day"]
            max_weekly = t_info["max_periods_per_week"]

            assigned = 0
            for day in days:
                if assigned >= needed:
                    break
                for period in PERIODS:
                    if assigned >= needed:
                        break
                    if (day, period) in unavail:
                        continue
                    if (day, period, tid) in teacher_schedule:
                        continue
                    dk = (tid, day)
                    if teacher_daily.get(dk, 0) >= max_daily:
                        continue
                    if teacher_weekly.get(tid, 0) >= max_weekly:
                        continue

                    for rid in compat:
                        if (day, period, rid) not in room_schedule:
                            # Assign
                            room_schedule.add((day, period, rid))
                            teacher_schedule.add((day, period, tid))
                            teacher_daily[dk] = (
                                teacher_daily.get(dk, 0) + 1
                            )
                            teacher_weekly[tid] = (
                                teacher_weekly.get(tid, 0) + 1
                            )
                            schedule_rows.append({
                                "day": day,
                                "period": period,
                                "class_id": cid,
                                "class_name": c["class_name"],
                                "room_id": rid,
                                "room_name": room_map[rid]["room_name"],
                                "teacher_id": tid,
                                "teacher_name": t_info["name"],
                            })
                            assigned += 1
                            break

        # ---- 9. Sort output ----
        day_order = {d: i for i, d in enumerate(days)}
        schedule_rows.sort(
            key=lambda r: (day_order[r["day"]], r["period"], r["class_id"])
        )

        # ---- 10. Write weekly_schedule.csv ----
        out_path = os.path.join(self.workspace, "weekly_schedule.csv")
        fieldnames = [
            "day", "period", "class_id", "class_name",
            "room_id", "room_name", "teacher_id", "teacher_name",
        ]
        with open(out_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(schedule_rows)

        # ---- 11. Build action string ----
        total_classes = len(set(r["class_id"] for r in schedule_rows))
        total_periods = len(schedule_rows)
        rooms_used = len(set(r["room_id"] for r in schedule_rows))

        action = (
            f"Scheduling Summary: {total_classes} classes across "
            f"{total_periods} periods using {rooms_used} rooms"
        )

        return self.step(action)
