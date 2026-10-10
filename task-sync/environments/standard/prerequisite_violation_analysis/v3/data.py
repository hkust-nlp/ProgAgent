"""Data generation for prerequisite violation detection task."""
import argparse
import json
import os
import random
import sqlite3

import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 640,
    "num_workspace_files": 32,
}

# ---------------------------------------------------------------------------
# Seed everything
# ---------------------------------------------------------------------------
fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEPARTMENTS = ["CS", "MATH", "PHYS", "CHEM", "BIO", "ENG"]

DEPT_FULL = {
    "CS": "Computer Science",
    "MATH": "Mathematics",
    "PHYS": "Physics",
    "CHEM": "Chemistry",
    "BIO": "Biology",
    "ENG": "English",
}

DEPT_SUBJECTS = {
    "CS": [
        "Programming", "Data Structures", "Algorithms", "Computer Systems",
        "Networks", "Databases", "Artificial Intelligence", "Security",
        "Graphics", "Computation Theory", "Software Engineering",
        "Computer Architecture", "Compilers", "Machine Learning",
        "Distributed Computing", "Operating Systems", "HCI",
        "Parallel Computing", "Cryptography", "Robotics",
        "Web Development", "Mobile Computing", "Cloud Computing",
        "Data Mining", "Computer Vision",
    ],
    "MATH": [
        "Calculus", "Linear Algebra", "Statistics", "Number Theory",
        "Topology", "Real Analysis", "Probability", "Differential Equations",
        "Abstract Algebra", "Combinatorics", "Geometry",
        "Numerical Methods", "Optimization", "Mathematical Logic",
        "Complex Analysis", "Set Theory", "Game Theory", "Graph Theory",
        "Functional Analysis", "Measure Theory",
        "Applied Mathematics", "Discrete Mathematics", "Stochastic Processes",
        "Mathematical Modeling", "Algebraic Geometry",
    ],
    "PHYS": [
        "Classical Mechanics", "Electromagnetism", "Thermodynamics",
        "Quantum Mechanics", "Optics", "Astrophysics", "Nuclear Physics",
        "Particle Physics", "Solid State Physics", "Fluid Dynamics",
        "Relativity", "Acoustics", "Biophysics", "Plasma Physics",
        "Computational Physics", "Statistical Mechanics", "Wave Theory",
        "Materials Science", "Photonics", "Geophysics",
        "Experimental Methods", "Electronics", "Nanophysics",
        "Atomic Physics", "Cosmology",
    ],
    "CHEM": [
        "General Chemistry", "Organic Chemistry", "Inorganic Chemistry",
        "Physical Chemistry", "Analytical Chemistry", "Biochemistry",
        "Polymer Chemistry", "Environmental Chemistry",
        "Medicinal Chemistry", "Spectroscopy", "Chemical Kinetics",
        "Thermochemistry", "Electrochemistry", "Surface Chemistry",
        "Nuclear Chemistry", "Quantum Chemistry", "Photochemistry",
        "Materials Chemistry", "Catalysis", "Chemical Engineering",
        "Green Chemistry", "Food Chemistry", "Forensic Chemistry",
        "Astrochemistry", "Nanochemistry",
    ],
    "BIO": [
        "Cell Biology", "Genetics", "Ecology", "Evolution",
        "Microbiology", "Molecular Biology", "Anatomy", "Physiology",
        "Neuroscience", "Immunology", "Developmental Biology",
        "Marine Biology", "Botany", "Zoology", "Bioinformatics",
        "Epidemiology", "Virology", "Genomics", "Proteomics",
        "Systems Biology", "Bioethics", "Conservation Biology",
        "Parasitology", "Mycology", "Endocrinology",
    ],
    "ENG": [
        "Composition", "Literature", "Creative Writing", "Rhetoric",
        "Linguistics", "Poetry", "Drama", "Fiction Writing",
        "Critical Theory", "American Literature", "British Literature",
        "World Literature", "Technical Writing", "Journalism",
        "Film Studies", "Comparative Literature", "Medieval Literature",
        "Modern Literature", "Postcolonial Literature",
        "Digital Humanities", "Sociolinguistics", "Phonetics",
        "Semantics", "Translation Studies", "Discourse Analysis",
    ],
}

LEVEL_PREFIX = {100: "Introduction to", 200: "Intermediate", 300: "Advanced", 400: "Topics in"}

SEMESTERS = [
    "Fall 2020", "Spring 2021", "Fall 2021", "Spring 2022",
    "Fall 2022", "Spring 2023", "Fall 2023", "Spring 2024",
]
SEMESTER_ORDER = {s: i for i, s in enumerate(SEMESTERS)}

GRADES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F"]
GRADE_VALUES = {
    "A+": 4.0, "A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7,
    "C+": 2.3, "C": 2.0, "C-": 1.7, "D+": 1.3, "D": 1.0, "D-": 0.7, "F": 0.0,
}

MIN_GRADE_POOL = ["D+", "C-", "C", "C", "C", "C", "C+", "B-"]


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------
def generate_courses(n: int):
    """Return *n* course dicts distributed across departments and levels."""
    levels = [100, 200, 300, 400]
    level_weights = [0.30, 0.30, 0.25, 0.15]

    # How many per dept
    per_dept = {d: n // len(DEPARTMENTS) for d in DEPARTMENTS}
    for i in range(n % len(DEPARTMENTS)):
        per_dept[DEPARTMENTS[i]] += 1

    courses = []
    for dept in DEPARTMENTS:
        dn = per_dept[dept]
        # distribute across levels
        counts = []
        for j in range(len(levels)):
            if j < len(levels) - 1:
                counts.append(max(1, int(dn * level_weights[j])))
            else:
                counts.append(max(1, dn - sum(counts)))
        # adjust if sum != dn
        while sum(counts) < dn:
            counts[0] += 1
        while sum(counts) > dn:
            for k in range(len(counts) - 1, -1, -1):
                if counts[k] > 1 and sum(counts) > dn:
                    counts[k] -= 1

        subjects = DEPT_SUBJECTS[dept][:]
        random.shuffle(subjects)
        si = 0
        for level, cnt in zip(levels, counts):
            for seq in range(1, cnt + 1):
                cid = f"{dept}{level + seq}"
                subj = subjects[si % len(subjects)]
                si += 1
                name = f"{LEVEL_PREFIX[level]} {subj}"
                credits = random.choice([3, 3, 3, 4, 4]) if level < 400 else random.choice([3, 4])
                courses.append({
                    "course_id": cid,
                    "course_name": name,
                    "department": dept,
                    "level": level,
                    "credits": credits,
                })
    random.shuffle(courses)
    return courses[:n]


def generate_prerequisites(courses, n_prereqs: int):
    """Build prerequisite edges. Higher-level courses depend on lower-level ones."""
    by_dept_level: dict = {}
    for c in courses:
        by_dept_level.setdefault((c["department"], c["level"]), []).append(c["course_id"])

    prereqs = []
    seen = set()

    # Within-department: level L+100 requires something from level L
    for dept in DEPARTMENTS:
        for level in [200, 300, 400]:
            higher = by_dept_level.get((dept, level), [])
            lower = by_dept_level.get((dept, level - 100), [])
            if not higher or not lower:
                continue
            for h in higher:
                k = min(random.choice([1, 1, 2]), len(lower))
                for p in random.sample(lower, k):
                    key = (h, p)
                    if key not in seen:
                        seen.add(key)
                        prereqs.append({
                            "course_id": h,
                            "prereq_course_id": p,
                            "min_grade": random.choice(MIN_GRADE_POOL),
                        })

    # Cross-department: CS & PHYS 200+ sometimes need MATH 100
    math100 = by_dept_level.get(("MATH", 100), [])
    for dept in ["CS", "PHYS"]:
        pool = []
        for lv in [200, 300]:
            pool.extend(by_dept_level.get((dept, lv), []))
        if math100 and pool:
            for c in random.sample(pool, min(3, len(pool))):
                p = random.choice(math100)
                key = (c, p)
                if key not in seen:
                    seen.add(key)
                    prereqs.append({
                        "course_id": c,
                        "prereq_course_id": p,
                        "min_grade": random.choice(["C", "C-", "D+"]),
                    })

    # BIO 200+ sometimes needs CHEM 100
    chem100 = by_dept_level.get(("CHEM", 100), [])
    bio_pool = []
    for lv in [200, 300]:
        bio_pool.extend(by_dept_level.get(("BIO", lv), []))
    if chem100 and bio_pool:
        for c in random.sample(bio_pool, min(2, len(bio_pool))):
            p = random.choice(chem100)
            key = (c, p)
            if key not in seen:
                seen.add(key)
                prereqs.append({
                    "course_id": c,
                    "prereq_course_id": p,
                    "min_grade": random.choice(["C", "C-"]),
                })

    # Pad if needed
    all_higher = [c for c in courses if c["level"] >= 200]
    while len(prereqs) < n_prereqs:
        h = random.choice(all_higher)
        lower_level = h["level"] - 100
        lower = by_dept_level.get((h["department"], lower_level), [])
        if not lower:
            lower = by_dept_level.get((h["department"], 100), [])
        if not lower:
            continue
        p = random.choice(lower)
        key = (h["course_id"], p)
        if key not in seen:
            seen.add(key)
            prereqs.append({
                "course_id": h["course_id"],
                "prereq_course_id": p,
                "min_grade": random.choice(MIN_GRADE_POOL),
            })

    # Trim if over
    random.shuffle(prereqs)
    return prereqs[:n_prereqs]


def generate_students(n: int):
    students = []
    standings = ["good", "good", "good", "good", "probation", "dean's list"]
    years = [2020, 2021, 2022, 2023]
    for i in range(n):
        students.append({
            "student_id": f"S{1000 + i}",
            "name": fake.name(),
            "major": random.choice(DEPARTMENTS),
            "enrollment_year": random.choice(years),
            "academic_standing": random.choice(standings),
        })
    return students


def generate_advisors(n_departments: int):
    """Return a list of advisor dicts, 2-3 per department."""
    advisors = []
    for dept in DEPARTMENTS[:n_departments]:
        k = random.choice([2, 2, 3])
        for _ in range(k):
            advisors.append({
                "advisor_name": f"Dr. {fake.last_name()}",
                "department": dept,
            })
    return advisors


def _prereqs_satisfied(course_id, completed_with_grades, prereq_map, grade_values):
    """Check if all prereqs for course_id are satisfied given completed courses and grades."""
    if course_id not in prereq_map:
        return True
    for prereq_id, min_grade in prereq_map[course_id]:
        if prereq_id not in completed_with_grades:
            return False
        best = max(completed_with_grades[prereq_id], key=lambda g: grade_values.get(g, 0))
        if grade_values.get(best, 0) < grade_values.get(min_grade, 0):
            return False
    return True


def generate_transcripts_and_registrations(students, courses, prerequisites):
    """Create transcript records and registration attempts.

    Students are assigned courses respecting prerequisite order so that
    violations arise only from deliberate injection (not random assignment).
    Returns (transcripts, registrations).
    """
    prereq_map: dict = {}
    for p in prerequisites:
        prereq_map.setdefault(p["course_id"], []).append(
            (p["prereq_course_id"], p["min_grade"])
        )

    courses_with_prereqs = [c for c in courses if c["course_id"] in prereq_map]

    transcripts = []
    registrations = []
    rid = 0
    tid = 0

    student_completed: dict = {}       # sid -> set of course_ids
    student_completed_grades: dict = {}  # sid -> { cid: [grades] }

    for student in students:
        sid = student["student_id"]
        major = student["major"]

        major_courses = [c for c in courses if c["department"] == major]
        other_courses = [c for c in courses if c["department"] != major]

        n_take = random.randint(8, min(15, len(courses)))
        n_major = min(random.randint(4, 8), len(major_courses))
        n_other = min(n_take - n_major, len(other_courses))

        candidate_pool = random.sample(major_courses, min(n_major + 4, len(major_courses))) + \
                         random.sample(other_courses, min(n_other + 4, len(other_courses)))
        # Sort by level so lower-level courses come first
        candidate_pool.sort(key=lambda c: (c["level"], c["course_id"]))

        completed_set: set = set()
        completed_grades: dict = {}  # cid -> [grades]
        taken_count = 0

        for course in candidate_pool:
            if taken_count >= n_take:
                break
            cid = course["course_id"]
            if cid in completed_set:
                continue
            # Only take course if prereqs are satisfied
            if not _prereqs_satisfied(cid, completed_grades, prereq_map, GRADE_VALUES):
                continue

            sem_idx = min(taken_count * len(SEMESTERS) // max(n_take, 1), len(SEMESTERS) - 1)
            semester = SEMESTERS[sem_idx]
            grade = random.choices(
                GRADES,
                weights=[2, 8, 7, 7, 14, 10, 8, 13, 6, 4, 6, 3, 7],
                k=1,
            )[0]

            tid += 1
            transcripts.append({
                "record_id": tid,
                "student_id": sid,
                "course_id": cid,
                "semester": semester,
                "grade": grade,
                "credits_earned": course["credits"] if grade != "F" else 0,
            })
            rid += 1
            registrations.append({
                "attempt_id": rid,
                "student_id": sid,
                "course_id": cid,
                "semester": semester,
                "outcome": "approved",
                "attempt_date": fake.date_between(start_date="-3y", end_date="today").isoformat(),
            })
            completed_set.add(cid)
            completed_grades.setdefault(cid, []).append(grade)
            taken_count += 1

        student_completed[sid] = completed_set
        student_completed_grades[sid] = completed_grades

    # ---- Inject deliberate violations (type 1: missing prereq) ----
    n_missing = max(20, len(students) // 3)
    candidates_missing = random.sample(students, min(n_missing, len(students)))

    for student in candidates_missing:
        sid = student["student_id"]
        completed = student_completed.get(sid, set())

        # Find courses where at least one prereq is entirely missing
        eligible = [
            c for c in courses_with_prereqs
            if c["course_id"] not in completed
            and any(p[0] not in completed for p in prereq_map[c["course_id"]])
        ]
        if not eligible:
            continue
        target = random.choice(eligible)
        semester = random.choice(SEMESTERS[-3:])
        grade = random.choices(
            GRADES, weights=[2, 8, 7, 7, 14, 10, 8, 13, 6, 4, 6, 3, 7], k=1
        )[0]

        tid += 1
        transcripts.append({
            "record_id": tid,
            "student_id": sid,
            "course_id": target["course_id"],
            "semester": semester,
            "grade": grade,
            "credits_earned": target["credits"] if grade != "F" else 0,
        })
        rid += 1
        registrations.append({
            "attempt_id": rid,
            "student_id": sid,
            "course_id": target["course_id"],
            "semester": semester,
            "outcome": "approved",
            "attempt_date": fake.date_between(start_date="-1y", end_date="today").isoformat(),
        })
        student_completed.setdefault(sid, set()).add(target["course_id"])

    # ---- Inject deliberate violations (type 2: grade_insufficient) ----
    # Find students who completed a prereq with a low grade, then register
    # for the higher course in a later semester.
    n_grade_viol = max(8, len(students) // 8)
    grade_viol_added = 0
    shuffled_students = students[:]
    random.shuffle(shuffled_students)
    for student in shuffled_students:
        if grade_viol_added >= n_grade_viol:
            break
        sid = student["student_id"]
        completed = student_completed.get(sid, set())
        completed_g = student_completed_grades.get(sid, {})

        for course in courses_with_prereqs:
            if grade_viol_added >= n_grade_viol:
                break
            cid = course["course_id"]
            if cid in completed:
                continue
            prereqs = prereq_map[cid]
            # Check if all prereqs are completed but at least one has insufficient grade
            all_completed = all(p[0] in completed for p in prereqs)
            if not all_completed:
                continue
            has_insuff = False
            for p_id, min_g in prereqs:
                grades = completed_g.get(p_id, [])
                if grades:
                    best = max(grades, key=lambda g: GRADE_VALUES.get(g, 0))
                    if GRADE_VALUES.get(best, 0) < GRADE_VALUES.get(min_g, 0):
                        has_insuff = True
                        break
            if not has_insuff:
                continue

            # This student completed all prereqs but at least one grade is too low
            semester = random.choice(SEMESTERS[-2:])
            grade = random.choices(
                GRADES, weights=[2, 8, 7, 7, 14, 10, 8, 13, 6, 4, 6, 3, 7], k=1
            )[0]
            tid += 1
            transcripts.append({
                "record_id": tid,
                "student_id": sid,
                "course_id": cid,
                "semester": semester,
                "grade": grade,
                "credits_earned": course["credits"] if grade != "F" else 0,
            })
            rid += 1
            registrations.append({
                "attempt_id": rid,
                "student_id": sid,
                "course_id": cid,
                "semester": semester,
                "outcome": "approved",
                "attempt_date": fake.date_between(start_date="-1y", end_date="today").isoformat(),
            })
            student_completed.setdefault(sid, set()).add(cid)
            grade_viol_added += 1
            break

    # ---- Denied / waitlisted registrations ----
    n_extra = max(len(students) // 4, 10)
    for _ in range(n_extra):
        rid += 1
        registrations.append({
            "attempt_id": rid,
            "student_id": random.choice(students)["student_id"],
            "course_id": random.choice(courses_with_prereqs)["course_id"] if courses_with_prereqs else random.choice(courses)["course_id"],
            "semester": random.choice(SEMESTERS),
            "outcome": random.choice(["denied", "denied", "waitlisted"]),
            "attempt_date": fake.date_between(start_date="-3y", end_date="today").isoformat(),
        })

    return transcripts, registrations


# ---------------------------------------------------------------------------
# Violation computation (used to produce override workspace files)
# ---------------------------------------------------------------------------
def compute_violations(students, courses, prerequisites, transcripts, registrations):
    """Detect all prerequisite violations in approved registrations."""
    prereq_map: dict = {}
    for p in prerequisites:
        prereq_map.setdefault(p["course_id"], []).append(
            (p["prereq_course_id"], p["min_grade"])
        )

    stu_map = {s["student_id"]: s for s in students}
    crs_map = {c["course_id"]: c for c in courses}

    # Build per-student transcript: sid -> { cid: [(sem, grade)] }
    stu_trans: dict = {}
    for t in transcripts:
        stu_trans.setdefault(t["student_id"], {}).setdefault(t["course_id"], []).append(
            (t["semester"], t["grade"])
        )

    violations = []
    seen_keys = set()

    for reg in registrations:
        if reg["outcome"] != "approved":
            continue
        cid = reg["course_id"]
        sid = reg["student_id"]
        reg_sem = reg["semester"]
        if cid not in prereq_map:
            continue

        reg_ord = SEMESTER_ORDER.get(reg_sem, 999)

        for prereq_id, min_grade in prereq_map[cid]:
            vkey = (sid, cid, prereq_id, reg_sem)
            if vkey in seen_keys:
                continue

            records = stu_trans.get(sid, {}).get(prereq_id, [])
            prior = [g for sem, g in records if SEMESTER_ORDER.get(sem, 999) < reg_ord]

            if not prior:
                seen_keys.add(vkey)
                violations.append({
                    "student_id": sid,
                    "student_name": stu_map[sid]["name"],
                    "student_major": stu_map[sid]["major"],
                    "course_id": cid,
                    "course_name": crs_map[cid]["course_name"] if cid in crs_map else cid,
                    "course_department": crs_map[cid]["department"] if cid in crs_map else "",
                    "prereq_course_id": prereq_id,
                    "violation_type": "missing",
                    "semester": reg_sem,
                })
            else:
                best = max(prior, key=lambda g: GRADE_VALUES.get(g, 0))
                if GRADE_VALUES.get(best, 0) < GRADE_VALUES.get(min_grade, 0):
                    seen_keys.add(vkey)
                    violations.append({
                        "student_id": sid,
                        "student_name": stu_map[sid]["name"],
                        "student_major": stu_map[sid]["major"],
                        "course_id": cid,
                        "course_name": crs_map[cid]["course_name"] if cid in crs_map else cid,
                        "course_department": crs_map[cid]["department"] if cid in crs_map else "",
                        "prereq_course_id": prereq_id,
                        "violation_type": "grade_insufficient",
                        "semester": reg_sem,
                        "actual_grade": best,
                        "required_grade": min_grade,
                    })

    return violations


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def create_database(db_path, courses, students, prerequisites, transcripts, registrations):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS courses (
        course_id TEXT PRIMARY KEY,
        course_name TEXT,
        department TEXT,
        level INTEGER,
        credits INTEGER
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS students (
        student_id TEXT PRIMARY KEY,
        name TEXT,
        major TEXT,
        enrollment_year INTEGER,
        academic_standing TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS prerequisites (
        prereq_id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id TEXT,
        prereq_course_id TEXT,
        min_grade TEXT,
        FOREIGN KEY(course_id) REFERENCES courses(course_id),
        FOREIGN KEY(prereq_course_id) REFERENCES courses(course_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS transcripts (
        record_id INTEGER PRIMARY KEY,
        student_id TEXT,
        course_id TEXT,
        semester TEXT,
        grade TEXT,
        credits_earned INTEGER,
        FOREIGN KEY(student_id) REFERENCES students(student_id),
        FOREIGN KEY(course_id) REFERENCES courses(course_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS registration_attempts (
        attempt_id INTEGER PRIMARY KEY,
        student_id TEXT,
        course_id TEXT,
        semester TEXT,
        outcome TEXT,
        attempt_date TEXT,
        FOREIGN KEY(student_id) REFERENCES students(student_id),
        FOREIGN KEY(course_id) REFERENCES courses(course_id)
    )""")

    for cr in courses:
        c.execute("INSERT INTO courses VALUES (?,?,?,?,?)",
                  (cr["course_id"], cr["course_name"], cr["department"], cr["level"], cr["credits"]))
    for s in students:
        c.execute("INSERT INTO students VALUES (?,?,?,?,?)",
                  (s["student_id"], s["name"], s["major"], s["enrollment_year"], s["academic_standing"]))
    for p in prerequisites:
        c.execute("INSERT INTO prerequisites (course_id, prereq_course_id, min_grade) VALUES (?,?,?)",
                  (p["course_id"], p["prereq_course_id"], p["min_grade"]))
    for t in transcripts:
        c.execute("INSERT INTO transcripts VALUES (?,?,?,?,?,?)",
                  (t["record_id"], t["student_id"], t["course_id"], t["semester"], t["grade"], t["credits_earned"]))
    for r in registrations:
        c.execute("INSERT INTO registration_attempts VALUES (?,?,?,?,?,?)",
                  (r["attempt_id"], r["student_id"], r["course_id"], r["semester"], r["outcome"], r["attempt_date"]))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Workspace files
# ---------------------------------------------------------------------------
def write_grade_scale(workspace):
    gs = {
        "description": "Official grade-point conversion table",
        "scale": {g: v for g, v in GRADE_VALUES.items()},
    }
    with open(os.path.join(workspace, "grade_scale.json"), "w") as f:
        json.dump(gs, f, indent=2)


def write_enforcement_policy(workspace):
    policy = {
        "severity_classification": {
            "critical": {
                "description": "Prerequisite was never completed and the course is within the student's declared major department",
                "rule": "violation_type == 'missing' AND course_department == student_major",
            },
            "major": {
                "description": "Prerequisite was never completed but the course is outside the student's major, OR prerequisite grade was insufficient and the course is within the student's major",
                "rule": "(violation_type == 'missing' AND course_department != student_major) OR (violation_type == 'grade_insufficient' AND course_department == student_major)",
            },
            "minor": {
                "description": "Prerequisite grade was insufficient and the course is outside the student's major department",
                "rule": "violation_type == 'grade_insufficient' AND course_department != student_major",
            },
        },
        "severity_order": ["critical", "major", "minor"],
        "thresholds": {
            "department_alert": 5,
            "course_alert": 3,
            "advisor_alert": 4,
        },
        "recommendation_rules": {
            "high_violation_department": "Departments with total violations >= department_alert threshold require enhanced automated prerequisite verification at registration time.",
            "high_violation_course": "Courses with total violations >= course_alert threshold should add a mandatory prerequisite confirmation step.",
            "high_override_advisor": "Advisors who approved overrides >= advisor_alert threshold should undergo override-authority review.",
        },
    }
    with open(os.path.join(workspace, "enforcement_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)


def distribute_file_counts(n_total):
    """Return dict of file counts per type summing to n_total."""
    # Ratios: json 25%, csv 25%, txt 25%, yaml 12.5%, md 12.5%
    n_json = max(1, round(n_total * 0.25))
    n_csv = max(1, round(n_total * 0.25))
    n_txt = max(1, round(n_total * 0.25))
    n_yaml = max(1, round(n_total * 0.125))
    n_md = max(1, n_total - n_json - n_csv - n_txt - n_yaml)
    return {"json": n_json, "csv": n_csv, "txt": n_txt, "yaml": n_yaml, "md": n_md}


def generate_workspace_files(workspace, violations, students, courses, advisors, n_files):
    os.makedirs(workspace, exist_ok=True)

    # ---- Fixed files ----
    write_grade_scale(workspace)
    write_enforcement_policy(workspace)

    # ---- Advisor overrides (subset of violations) ----
    n_overridden = max(5, int(len(violations) * 0.45))
    overridden = random.sample(violations, min(n_overridden, len(violations)))
    override_records = []
    for idx, v in enumerate(overridden):
        advisor = random.choice(advisors)
        reasons = [
            "Student demonstrated equivalent competency via standardized test",
            "Transfer credit from accredited institution covers prerequisite content",
            "Student completed equivalent coursework at partner university",
            "Professional work experience substitutes for prerequisite",
            "Student enrolled concurrently in prerequisite course",
            "Department chair approved due to exceptional circumstances",
            "Student completed prerequisite at community college (transcript pending)",
            "Advisor verified competency through placement exam",
        ]
        override_records.append({
            "override_id": f"OVR{idx + 1:04d}",
            "student_id": v["student_id"],
            "course_id": v["course_id"],
            "prereq_course_id": v["prereq_course_id"],
            "advisor_name": advisor["advisor_name"],
            "advisor_department": advisor["department"],
            "reason": random.choice(reasons),
            "override_date": fake.date_between(start_date="-2y", end_date="today").isoformat(),
            "override_type": random.choice(["prerequisite_waiver", "grade_exception", "department_approval"]),
        })

    # ---- Student-advisor assignments ----
    stu_advisor_rows = []
    for s in students:
        dept_advisors = [a for a in advisors if a["department"] == s["major"]]
        if not dept_advisors:
            dept_advisors = advisors
        adv = random.choice(dept_advisors)
        stu_advisor_rows.append({
            "student_id": s["student_id"],
            "student_name": s["name"],
            "advisor_name": adv["advisor_name"],
            "advisor_department": adv["department"],
            "assignment_date": fake.date_between(start_date="-4y", end_date="-1y").isoformat(),
            "meeting_frequency": random.choice(["biweekly", "monthly", "quarterly"]),
        })

    # ---- Distribute files ----
    fc = distribute_file_counts(n_files)

    # JSON: advisor override batches
    chunk = max(1, len(override_records) // fc["json"])
    for i in range(fc["json"]):
        start = i * chunk
        end = len(override_records) if i == fc["json"] - 1 else start + chunk
        batch = override_records[start:end]
        with open(os.path.join(workspace, f"advisor_overrides_batch_{i + 1}.json"), "w") as f:
            json.dump(batch, f, indent=2)

    # CSV: student-advisor maps
    chunk = max(1, len(stu_advisor_rows) // fc["csv"])
    for i in range(fc["csv"]):
        start = i * chunk
        end = len(stu_advisor_rows) if i == fc["csv"] - 1 else start + chunk
        df = pd.DataFrame(stu_advisor_rows[start:end])
        df.to_csv(os.path.join(workspace, f"student_advisor_map_{i + 1}.csv"), index=False)

    # TXT: registration audit logs
    audit_entries = []
    for v in violations:
        ts = fake.date_time_between(start_date="-2y", end_date="now").strftime("%Y-%m-%d %H:%M:%S")
        audit_entries.append(
            f"[{ts}] PREREQ_CHECK_FAILED: {v['student_id']} attempted {v['course_id']} "
            f"- missing/insufficient prerequisite {v['prereq_course_id']}"
        )
    for ovr in override_records:
        ts = fake.date_time_between(start_date="-2y", end_date="now").strftime("%Y-%m-%d %H:%M:%S")
        audit_entries.append(
            f"[{ts}] OVERRIDE_APPLIED: {ovr['student_id']} {ovr['course_id']} "
            f"- {ovr['override_type']} by {ovr['advisor_name']}"
        )
    random.shuffle(audit_entries)
    chunk = max(1, len(audit_entries) // fc["txt"])
    for i in range(fc["txt"]):
        start = i * chunk
        end = len(audit_entries) if i == fc["txt"] - 1 else start + chunk
        with open(os.path.join(workspace, f"registration_audit_log_{i + 1}.txt"), "w") as f:
            f.write("\n".join(audit_entries[start:end]) + "\n")

    # YAML: department capacity data
    dept_data_list = []
    for dept in DEPARTMENTS:
        for sem in SEMESTERS[-4:]:
            dept_data_list.append({
                "department": dept,
                "semester": sem,
                "total_capacity": random.randint(200, 500),
                "total_enrolled": random.randint(150, 450),
                "prerequisite_enforced_courses": random.randint(5, 15),
                "override_requests_received": random.randint(0, 12),
            })
    chunk = max(1, len(dept_data_list) // fc["yaml"])
    for i in range(fc["yaml"]):
        start = i * chunk
        end = len(dept_data_list) if i == fc["yaml"] - 1 else start + chunk
        with open(os.path.join(workspace, f"department_capacity_{i + 1}.yaml"), "w") as f:
            yaml.dump(dept_data_list[start:end], f, default_flow_style=False)

    # MD: prerequisite review notes
    review_notes_blocks = []
    for dept in DEPARTMENTS:
        dept_violations = [v for v in violations if v.get("course_department") == dept]
        note = (
            f"## {DEPT_FULL.get(dept, dept)} Department Prerequisite Review\n\n"
            f"Total prerequisite violation incidents flagged: {len(dept_violations)}.\n\n"
        )
        if dept_violations:
            sample = dept_violations[:3]
            for v in sample:
                note += (
                    f"- Student {v['student_id']} registered for {v['course_id']} "
                    f"without completing {v['prereq_course_id']} ({v['violation_type']})\n"
                )
            note += "\n"
        note += "The committee recommends continued monitoring of prerequisite enforcement.\n\n---\n\n"
        review_notes_blocks.append(note)

    chunk = max(1, len(review_notes_blocks) // fc["md"])
    for i in range(fc["md"]):
        start = i * chunk
        end = len(review_notes_blocks) if i == fc["md"] - 1 else start + chunk
        with open(os.path.join(workspace, f"prerequisite_review_{i + 1}.md"), "w") as f:
            f.write("".join(review_notes_blocks[start:end]))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n_rows = SCALE["rows_per_table"]
    n_ws = SCALE["num_workspace_files"]

    courses = generate_courses(n_rows)
    students = generate_students(n_rows)
    prerequisites = generate_prerequisites(courses, n_rows)
    advisors = generate_advisors(len(DEPARTMENTS))

    transcripts, registrations = generate_transcripts_and_registrations(
        students, courses, prerequisites
    )

    # Compute violations for workspace override files
    violations = compute_violations(students, courses, prerequisites, transcripts, registrations)

    # Persist
    create_database(args.db_path, courses, students, prerequisites, transcripts, registrations)
    generate_workspace_files(args.workspace, violations, students, courses, advisors, n_ws)

    print(f"Database created at {args.db_path}")
    print(f"  courses: {len(courses)}")
    print(f"  students: {len(students)}")
    print(f"  prerequisites: {len(prerequisites)}")
    print(f"  transcripts: {len(transcripts)}")
    print(f"  registrations: {len(registrations)}")
    print(f"  violations detected: {len(violations)}")
    print(f"Workspace files created in {args.workspace}/")


if __name__ == "__main__":
    main()
