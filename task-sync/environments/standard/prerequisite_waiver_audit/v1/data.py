"""
Data generation script for prerequisite waiver audit task.
Generates database and workspace files for graduation clearance compliance review.
"""

import argparse
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker
import yaml

# All random seeds pinned to 42
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

fake = Faker()
Faker.seed(SEED)

SCALE = {
    "rows_per_table": 160,
    "num_workspace_files": 16,
}

# Fixed configuration
DEPARTMENTS = [
    "Computer Science", "Mathematics", "Physics", "Chemistry",
    "Biology", "English", "History", "Economics", "Psychology", "Engineering"
]

PROGRAMS = [
    {"id": "CS_BS", "name": "B.S. Computer Science", "dept": "Computer Science"},
    {"id": "MATH_BS", "name": "B.S. Mathematics", "dept": "Mathematics"},
    {"id": "PHYS_BS", "name": "B.S. Physics", "dept": "Physics"},
    {"id": "CHEM_BS", "name": "B.S. Chemistry", "dept": "Chemistry"},
    {"id": "BIO_BS", "name": "B.S. Biology", "dept": "Biology"},
    {"id": "ENG_BA", "name": "B.A. English", "dept": "English"},
    {"id": "HIST_BA", "name": "B.A. History", "dept": "History"},
    {"id": "ECON_BS", "name": "B.S. Economics", "dept": "Economics"},
    {"id": "PSYCH_BS", "name": "B.S. Psychology", "dept": "Psychology"},
    {"id": "ENGR_BS", "name": "B.S. Engineering", "dept": "Engineering"},
]

APPROVER_LEVELS = ["instructor", "department_chair", "dean", "provost"]

WAIVER_TYPES = ["prerequisite_waiver", "course_substitution", "credit_transfer", "experience_based"]

SEMESTERS = ["Fall 2022", "Spring 2023", "Fall 2023", "Spring 2024", "Fall 2024", "Spring 2025"]

GRADE_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "F", "W"]
GRADE_POINTS = {
    "A+": 4.0, "A": 4.0, "A-": 3.7,
    "B+": 3.3, "B": 3.0, "B-": 2.7,
    "C+": 2.3, "C": 2.0, "C-": 1.7,
    "D+": 1.3, "D": 1.0, "F": 0.0, "W": 0.0
}

AUTHORITY_RANK = {"instructor": 1, "department_chair": 2, "dean": 3, "provost": 4}


def create_tables(conn):
    """Create all database tables."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            program_id TEXT,
            enrollment_year INTEGER,
            cumulative_gpa REAL,
            credits_completed INTEGER,
            status TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            course_id TEXT PRIMARY KEY,
            course_name TEXT,
            department TEXT,
            credits INTEGER,
            level INTEGER,
            prerequisites TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS waiver_petitions (
            petition_id TEXT PRIMARY KEY,
            student_id TEXT,
            course_id TEXT,
            waiver_type TEXT,
            prerequisite_waived TEXT,
            reason TEXT,
            submitted_date TEXT,
            decision_date TEXT,
            status TEXT,
            approver_id TEXT,
            approver_level TEXT,
            semester TEXT,
            FOREIGN KEY (student_id) REFERENCES students(student_id),
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS course_substitutions (
            substitution_id TEXT PRIMARY KEY,
            petition_id TEXT,
            student_id TEXT,
            original_course_id TEXT,
            substitute_course_id TEXT,
            credit_equivalence REAL,
            approved_by TEXT,
            approval_date TEXT,
            justification TEXT,
            FOREIGN KEY (petition_id) REFERENCES waiver_petitions(petition_id),
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS grade_transcripts (
            record_id TEXT PRIMARY KEY,
            student_id TEXT,
            course_id TEXT,
            semester TEXT,
            grade TEXT,
            credits_earned REAL,
            grade_points REAL,
            FOREIGN KEY (student_id) REFERENCES students(student_id),
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS degree_audit_rules (
            rule_id TEXT PRIMARY KEY,
            program_id TEXT,
            rule_type TEXT,
            course_id TEXT,
            requirement_description TEXT,
            min_grade TEXT,
            is_waivable INTEGER,
            waiver_authority_level TEXT,
            max_substitution_credit_diff REAL
        )
    """)

    conn.commit()


def generate_courses(n_courses):
    """Generate course catalog."""
    courses = []
    course_ids_set = set()

    dept_prefixes = {
        "Computer Science": "CS", "Mathematics": "MATH", "Physics": "PHYS",
        "Chemistry": "CHEM", "Biology": "BIO", "English": "ENG",
        "History": "HIST", "Economics": "ECON", "Psychology": "PSYCH",
        "Engineering": "ENGR"
    }

    courses_per_dept = max(n_courses // len(DEPARTMENTS), 8)

    for dept in DEPARTMENTS:
        prefix = dept_prefixes[dept]
        for i in range(courses_per_dept):
            level = random.choice([100, 200, 300, 400, 500])
            course_num = level + random.randint(1, 99)
            course_id = f"{prefix}{course_num}"
            if course_id in course_ids_set:
                continue
            course_ids_set.add(course_id)

            credits = random.choice([3, 3, 3, 4, 4])
            course_name = fake.bs().title()

            courses.append({
                "course_id": course_id,
                "course_name": course_name,
                "department": dept,
                "credits": credits,
                "level": level,
                "prerequisites": ""
            })

    # Assign prerequisites (lower-level courses as prereqs for higher-level ones)
    for dept in DEPARTMENTS:
        dept_courses = [c for c in courses if c["department"] == dept]
        dept_courses.sort(key=lambda x: x["level"])
        for i, course in enumerate(dept_courses):
            if course["level"] >= 300 and i > 0:
                eligible_prereqs = [c for c in dept_courses[:i] if c["level"] < course["level"]]
                if eligible_prereqs:
                    n_prereqs = random.randint(1, min(2, len(eligible_prereqs)))
                    prereqs = random.sample(eligible_prereqs, n_prereqs)
                    course["prerequisites"] = ",".join(p["course_id"] for p in prereqs)

    return courses[:n_courses]


def generate_students(n_students, programs):
    """Generate student records."""
    students = []
    for i in range(n_students):
        student_id = f"STU{10000 + i}"
        program = random.choice(programs)
        gpa = round(np.random.normal(3.2, 0.5), 2)
        gpa = max(1.5, min(4.0, gpa))

        students.append({
            "student_id": student_id,
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "program_id": program["id"],
            "enrollment_year": random.randint(2019, 2023),
            "cumulative_gpa": gpa,
            "credits_completed": random.randint(30, 130),
            "status": random.choice(["active", "active", "active", "probation", "graduated"])
        })
    return students


def generate_grade_transcripts(students, courses, n_records):
    """Generate grade transcript records."""
    grade_options = list(GRADE_POINTS.keys())
    grade_weights = [3, 10, 8, 8, 12, 8, 6, 10, 5, 4, 3, 2, 1]

    records = []
    for i in range(n_records):
        student = random.choice(students)
        course = random.choice(courses)
        grade = random.choices(grade_options, weights=grade_weights, k=1)[0]
        semester = random.choice(SEMESTERS)

        records.append({
            "record_id": f"GR{100000 + i}",
            "student_id": student["student_id"],
            "course_id": course["course_id"],
            "semester": semester,
            "grade": grade,
            "credits_earned": course["credits"] if grade not in ["F", "W"] else 0,
            "grade_points": GRADE_POINTS[grade] * course["credits"]
        })
    return records


def generate_waiver_petitions(students, courses, n_petitions):
    """Generate waiver petition records with some non-compliant ones."""
    petitions = []
    approver_ids = [f"FAC{1000 + i}" for i in range(20)]
    courses_with_prereqs = [c for c in courses if c["prerequisites"]]

    for i in range(n_petitions):
        student = random.choice(students)
        if courses_with_prereqs:
            course = random.choice(courses_with_prereqs)
        else:
            course = random.choice(courses)

        prereqs = course["prerequisites"].split(",") if course["prerequisites"] else []
        prereq_waived = random.choice(prereqs) if prereqs else course["course_id"]

        waiver_type = random.choice(WAIVER_TYPES)
        submitted = fake.date_between(start_date="-2y", end_date="today")
        decision_days = random.randint(3, 45)
        decision_date = submitted + timedelta(days=decision_days)

        status = random.choices(["approved", "denied", "pending"], weights=[70, 20, 10], k=1)[0]
        approver = random.choice(approver_ids)
        approver_level = random.choice(APPROVER_LEVELS)
        semester = random.choice(SEMESTERS)

        petitions.append({
            "petition_id": f"WP{20000 + i}",
            "student_id": student["student_id"],
            "course_id": course["course_id"],
            "waiver_type": waiver_type,
            "prerequisite_waived": prereq_waived,
            "reason": fake.sentence(nb_words=12),
            "submitted_date": submitted.isoformat(),
            "decision_date": decision_date.isoformat(),
            "status": status,
            "approver_id": approver,
            "approver_level": approver_level,
            "semester": semester
        })
    return petitions


def generate_substitutions(petitions, courses, n_subs):
    """Generate course substitution records."""
    substitutions = []
    approved_petitions = [p for p in petitions if p["status"] == "approved"]
    course_map = {c["course_id"]: c for c in courses}

    for i in range(min(n_subs, len(approved_petitions))):
        petition = approved_petitions[i % len(approved_petitions)]
        original_course = course_map.get(petition["course_id"], random.choice(courses))

        same_dept_courses = [c for c in courses if c["department"] == original_course["department"]
                            and c["course_id"] != original_course["course_id"]]
        diff_dept_courses = [c for c in courses if c["department"] != original_course["department"]]

        if random.random() < 0.7 and same_dept_courses:
            sub_course = random.choice(same_dept_courses)
        else:
            sub_course = random.choice(diff_dept_courses)

        credit_equiv = round(sub_course["credits"] / max(original_course["credits"], 1), 2)
        approval_date = fake.date_between(start_date="-2y", end_date="today")

        substitutions.append({
            "substitution_id": f"SUB{30000 + i}",
            "petition_id": petition["petition_id"],
            "student_id": petition["student_id"],
            "original_course_id": original_course["course_id"],
            "substitute_course_id": sub_course["course_id"],
            "credit_equivalence": credit_equiv,
            "approved_by": petition["approver_id"],
            "approval_date": approval_date.isoformat(),
            "justification": fake.sentence(nb_words=8)
        })
    return substitutions


def generate_degree_audit_rules(programs, courses):
    """Generate degree audit rules."""
    rules = []
    rule_id = 0

    for program in programs:
        dept = program["dept"]
        dept_courses = [c for c in courses if c["department"] == dept]

        for course in dept_courses:
            rule_id += 1
            if course["level"] >= 400:
                authority = "dean"
                min_grade = "C"
                is_waivable = random.choice([0, 1])
            elif course["level"] >= 300:
                authority = "department_chair"
                min_grade = "C-"
                is_waivable = 1
            else:
                authority = "instructor"
                min_grade = "D"
                is_waivable = 1

            max_credit_diff = 1.0 if course["level"] < 300 else 0.5

            rules.append({
                "rule_id": f"RULE{40000 + rule_id}",
                "program_id": program["id"],
                "rule_type": "prerequisite_requirement",
                "course_id": course["course_id"],
                "requirement_description": f"Prerequisite completion required for {course['course_id']}",
                "min_grade": min_grade,
                "is_waivable": is_waivable,
                "waiver_authority_level": authority,
                "max_substitution_credit_diff": max_credit_diff
            })
    return rules


def populate_database(conn, students, courses, transcripts, petitions, substitutions, rules):
    """Insert all generated data into the database."""
    cursor = conn.cursor()

    for s in students:
        cursor.execute("INSERT OR REPLACE INTO students VALUES (?,?,?,?,?,?,?,?)",
                       (s["student_id"], s["first_name"], s["last_name"], s["program_id"],
                        s["enrollment_year"], s["cumulative_gpa"], s["credits_completed"], s["status"]))

    for c in courses:
        cursor.execute("INSERT OR REPLACE INTO courses VALUES (?,?,?,?,?,?)",
                       (c["course_id"], c["course_name"], c["department"], c["credits"],
                        c["level"], c["prerequisites"]))

    for t in transcripts:
        cursor.execute("INSERT OR REPLACE INTO grade_transcripts VALUES (?,?,?,?,?,?,?)",
                       (t["record_id"], t["student_id"], t["course_id"], t["semester"],
                        t["grade"], t["credits_earned"], t["grade_points"]))

    for p in petitions:
        cursor.execute("INSERT OR REPLACE INTO waiver_petitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (p["petition_id"], p["student_id"], p["course_id"], p["waiver_type"],
                        p["prerequisite_waived"], p["reason"], p["submitted_date"], p["decision_date"],
                        p["status"], p["approver_id"], p["approver_level"], p["semester"]))

    for sub in substitutions:
        cursor.execute("INSERT OR REPLACE INTO course_substitutions VALUES (?,?,?,?,?,?,?,?,?)",
                       (sub["substitution_id"], sub["petition_id"], sub["student_id"],
                        sub["original_course_id"], sub["substitute_course_id"],
                        sub["credit_equivalence"], sub["approved_by"], sub["approval_date"],
                        sub["justification"]))

    for r in rules:
        cursor.execute("INSERT OR REPLACE INTO degree_audit_rules VALUES (?,?,?,?,?,?,?,?,?)",
                       (r["rule_id"], r["program_id"], r["rule_type"], r["course_id"],
                        r["requirement_description"], r["min_grade"], r["is_waivable"],
                        r["waiver_authority_level"], r["max_substitution_credit_diff"]))

    conn.commit()


def generate_workspace_files(workspace, students, courses, petitions, substitutions, transcripts, rules):
    """Generate workspace files with complementary information."""
    os.makedirs(workspace, exist_ok=True)

    n_files = SCALE["num_workspace_files"]

    # --- Fixed policy/config files (do not scale) ---

    # 1. Compliance policy configuration
    compliance_config = {
        "gpa_threshold_for_waiver": 2.5,
        "max_processing_days": 30,
        "authority_hierarchy": {
            "instructor": 1,
            "department_chair": 2,
            "dean": 3,
            "provost": 4
        },
        "level_authority_requirements": {
            "100-200": "instructor",
            "300": "department_chair",
            "400-500": "dean"
        },
        "max_waivers_per_student": 3,
        "credit_equivalence_minimum": 0.75,
        "non_waivable_override_authority": "provost",
        "deadline_policy": {
            "petition_must_be_submitted_before_semester_start": True,
            "semester_start_dates": {
                "Fall 2022": "2022-08-22",
                "Spring 2023": "2023-01-17",
                "Fall 2023": "2023-08-21",
                "Spring 2024": "2024-01-16",
                "Fall 2024": "2024-08-19",
                "Spring 2025": "2025-01-13"
            }
        }
    }
    with open(os.path.join(workspace, "compliance_policy.json"), "w") as f:
        json.dump(compliance_config, f, indent=2)

    # 2. Grade equivalence table
    grade_equiv_content = """# Grade Equivalence and Minimum Standards

| Grade | Points | Passing | Meets_Min_C | Meets_Min_B |
|-------|--------|---------|-------------|-------------|
| A+    | 4.0    | Yes     | Yes         | Yes         |
| A     | 4.0    | Yes     | Yes         | Yes         |
| A-    | 3.7    | Yes     | Yes         | Yes         |
| B+    | 3.3    | Yes     | Yes         | Yes         |
| B     | 3.0    | Yes     | Yes         | Yes         |
| B-    | 2.7    | Yes     | Yes         | No          |
| C+    | 2.3    | Yes     | Yes         | No          |
| C     | 2.0    | Yes     | Yes         | No          |
| C-    | 1.7    | Yes     | Partial     | No          |
| D+    | 1.3    | Yes     | No          | No          |
| D     | 1.0    | Yes     | No          | No          |
| F     | 0.0    | No      | No          | No          |
| W     | 0.0    | No      | No          | No          |

## Minimum Grade Policy for Prerequisite Satisfaction
- Courses at 100-200 level: minimum D required
- Courses at 300 level: minimum C- required
- Courses at 400-500 level: minimum C required

## Grade Ordering (for comparison)
A+ > A > A- > B+ > B > B- > C+ > C > C- > D+ > D > F > W
"""
    with open(os.path.join(workspace, "grade_equivalence.md"), "w") as f:
        f.write(grade_equiv_content)

    # 3. Approver registry (YAML format)
    approver_data = {"approvers": []}
    approver_ids_used = sorted(set(p["approver_id"] for p in petitions))
    for approver_id in approver_ids_used:
        dept = random.choice(DEPARTMENTS)
        level = random.choice(APPROVER_LEVELS)
        name = fake.name()
        approver_data["approvers"].append({
            "id": approver_id,
            "name": name,
            "level": level,
            "department": dept,
            "active": True
        })

    with open(os.path.join(workspace, "approver_registry.yaml"), "w") as f:
        yaml.dump(approver_data, f, default_flow_style=False, sort_keys=False)

    # --- Scalable data files ---
    approved_petitions = [p for p in petitions if p["status"] == "approved"]
    petitions_per_file = max(1, len(approved_petitions) // n_files)
    student_map = {s["student_id"]: s for s in students}

    for file_idx in range(n_files):
        start = file_idx * petitions_per_file
        end = start + petitions_per_file if file_idx < n_files - 1 else len(approved_petitions)
        batch = approved_petitions[start:end]

        if not batch:
            batch = [random.choice(approved_petitions)]

        file_type = file_idx % 4  # Rotate through formats

        if file_type == 0:
            # JSON format - petition detail batches
            records = []
            for p in batch:
                student = student_map.get(p["student_id"])
                records.append({
                    "petition_id": p["petition_id"],
                    "student_id": p["student_id"],
                    "student_name": f"{student['first_name']} {student['last_name']}" if student else "Unknown",
                    "course_id": p["course_id"],
                    "waiver_type": p["waiver_type"],
                    "prerequisite_waived": p["prerequisite_waived"],
                    "semester": p["semester"],
                    "approver_level": p["approver_level"],
                    "decision_date": p["decision_date"]
                })
            with open(os.path.join(workspace, f"petition_batch_{file_idx + 1}.json"), "w") as f:
                json.dump(records, f, indent=2)

        elif file_type == 1:
            # CSV format - substitution details
            sub_petition_ids = {p["petition_id"] for p in batch}
            sub_records = [s for s in substitutions if s["petition_id"] in sub_petition_ids]
            if not sub_records:
                sub_records = substitutions[file_idx:file_idx + 3] if file_idx < len(substitutions) else [substitutions[0]]
            df = pd.DataFrame(sub_records)
            df.to_csv(os.path.join(workspace, f"substitution_log_{file_idx + 1}.csv"), index=False)

        elif file_type == 2:
            # TXT format - narrative waiver justifications
            content = f"=== Waiver Justification Batch {file_idx + 1} ===\n\n"
            for p in batch:
                student = student_map.get(p["student_id"])
                content += f"Petition: {p['petition_id']}\n"
                if student:
                    content += f"Student: {p['student_id']} ({student['first_name']} {student['last_name']} - GPA: {student['cumulative_gpa']:.2f})\n"
                else:
                    content += f"Student: {p['student_id']}\n"
                content += f"Course: {p['course_id']} | Prerequisite Waived: {p['prerequisite_waived']}\n"
                content += f"Type: {p['waiver_type']}\n"
                content += f"Reason: {p['reason']}\n"
                content += f"Submitted: {p['submitted_date']} | Decided: {p['decision_date']}\n"
                content += f"Approver: {p['approver_id']} (Level: {p['approver_level']})\n"
                content += "-" * 60 + "\n\n"
            with open(os.path.join(workspace, f"waiver_justifications_{file_idx + 1}.txt"), "w") as f:
                f.write(content)

        else:
            # YAML format - student academic summaries
            student_ids_in_batch = list(set(p["student_id"] for p in batch))
            student_entries = []
            for sid in student_ids_in_batch:
                student = student_map.get(sid)
                if student:
                    n_transcript = len([t for t in transcripts if t["student_id"] == sid])
                    student_entries.append({
                        "id": sid,
                        "name": f"{student['first_name']} {student['last_name']}",
                        "program": student["program_id"],
                        "gpa": round(student["cumulative_gpa"], 2),
                        "credits": student["credits_completed"],
                        "courses_taken": n_transcript,
                        "enrollment_year": student["enrollment_year"]
                    })
            data = {"students": student_entries}
            with open(os.path.join(workspace, f"student_summaries_{file_idx + 1}.yaml"), "w") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n_rows = SCALE["rows_per_table"]

    courses = generate_courses(n_rows)
    students = generate_students(n_rows, PROGRAMS)
    transcripts = generate_grade_transcripts(students, courses, n_rows * 3)
    petitions = generate_waiver_petitions(students, courses, n_rows)
    substitutions = generate_substitutions(petitions, courses, int(n_rows * 0.6))
    rules = generate_degree_audit_rules(PROGRAMS, courses)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    populate_database(conn, students, courses, transcripts, petitions, substitutions, rules)
    conn.close()

    generate_workspace_files(args.workspace, students, courses, petitions, substitutions, transcripts, rules)

    print(f"Database created at {args.db_path}")
    print(f"Workspace files generated in {args.workspace}")
    print(f"  Students: {len(students)}")
    print(f"  Courses: {len(courses)}")
    print(f"  Transcripts: {len(transcripts)}")
    print(f"  Petitions: {len(petitions)}")
    print(f"  Substitutions: {len(substitutions)}")
    print(f"  Degree rules: {len(rules)}")


if __name__ == "__main__":
    main()
