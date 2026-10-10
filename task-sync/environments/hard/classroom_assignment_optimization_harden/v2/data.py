import argparse
import sqlite3
import os
import json
import csv
import random
import math
import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 48,
    "num_workspace_files": 24,
}

SEED = 42

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
PERIODS_PER_DAY = 8

ALL_SUBJECTS = [
    "Mathematics", "English", "Science", "History", "Geography",
    "Computer Science", "Art", "Music", "Physical Education",
    "Chemistry", "Physics", "Biology", "Foreign Language",
    "Economics", "Literature",
]

SUBJECT_EQUIPMENT_MAP = {
    "Mathematics": [],
    "English": [],
    "History": [],
    "Geography": [],
    "Literature": [],
    "Economics": [],
    "Foreign Language": [],
    "Computer Science": ["computers"],
    "Art": ["art_supplies"],
    "Music": ["music_equipment"],
    "Physical Education": ["gym_equipment"],
    "Chemistry": ["lab_stations", "fume_hoods"],
    "Physics": ["lab_stations", "physics_kits"],
    "Biology": ["lab_stations", "microscopes"],
    "Science": ["lab_stations"],
}

SPECIALIST_ROOM_TYPE = {
    "Computer Science": "computer_lab",
    "Chemistry": "science_lab",
    "Physics": "science_lab",
    "Biology": "science_lab",
    "Science": "science_lab",
    "Art": "art_studio",
    "Music": "music_room",
    "Physical Education": "gymnasium",
}

ROOM_TYPE_EQUIPMENT = {
    "classroom": ["projector", "whiteboard"],
    "computer_lab": ["computers", "projector", "whiteboard"],
    "science_lab": ["lab_stations", "fume_hoods", "microscopes", "physics_kits", "projector"],
    "art_studio": ["art_supplies", "easels", "sink"],
    "music_room": ["music_equipment", "sound_system"],
    "gymnasium": ["gym_equipment"],
}

GRADE_LEVELS = [7, 8, 9, 10, 11, 12]

DEPARTMENTS = [
    "Mathematics", "Languages", "Sciences",
    "Humanities", "Arts", "Physical Education",
]

DEPT_SUBJECTS = {
    "Mathematics": ["Mathematics"],
    "Languages": ["English", "Foreign Language", "Literature"],
    "Sciences": ["Science", "Chemistry", "Physics", "Biology", "Computer Science"],
    "Humanities": ["History", "Geography", "Economics"],
    "Arts": ["Art", "Music"],
    "Physical Education": ["Physical Education"],
}

BUILDINGS = ["Main Building", "Science Wing", "Arts Center", "North Block", "South Block"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    random.seed(SEED)
    np.random.seed(SEED)
    fake = Faker()
    Faker.seed(SEED)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    os.makedirs(args.workspace, exist_ok=True)

    # ----------------------------------------------------------------
    # 1. Generate rooms
    # ----------------------------------------------------------------
    n_rooms = n_rows
    specialist_types = ["computer_lab", "science_lab", "art_studio",
                        "music_room", "gymnasium"]
    specialist_per_type = max(1, n_rooms // 10)
    room_types_list = []
    for st in specialist_types:
        room_types_list.extend([st] * specialist_per_type)
    remaining = n_rooms - len(room_types_list)
    if remaining < 0:
        room_types_list = room_types_list[:n_rooms]
    else:
        room_types_list.extend(["classroom"] * remaining)
    random.shuffle(room_types_list)

    room_name_counters = {}
    rooms = []
    for i in range(n_rooms):
        rt = room_types_list[i]
        prefix = {
            "classroom": "CR", "computer_lab": "CL", "science_lab": "SL",
            "art_studio": "AS", "music_room": "MR", "gymnasium": "GY",
        }[rt]
        room_name_counters[prefix] = room_name_counters.get(prefix, 0) + 1
        cap = {
            "classroom": random.randint(28, 40),
            "computer_lab": random.randint(22, 32),
            "science_lab": random.randint(22, 32),
            "art_studio": random.randint(18, 28),
            "music_room": random.randint(22, 32),
            "gymnasium": random.randint(45, 80),
        }[rt]
        rooms.append({
            "room_id": i + 1,
            "room_name": f"{prefix}-{100 + room_name_counters[prefix]}",
            "capacity": cap,
            "room_type": rt,
            "building": BUILDINGS[i % len(BUILDINGS)],
            "floor": random.randint(1, 3),
        })

    specialist_room_counts = {}
    for r in rooms:
        specialist_room_counts[r["room_type"]] = (
            specialist_room_counts.get(r["room_type"], 0) + 1
        )

    # ----------------------------------------------------------------
    # 2. Generate teachers
    # ----------------------------------------------------------------
    n_teachers = n_rows
    teachers = []
    for i in range(n_teachers):
        teachers.append({
            "teacher_id": i + 1,
            "name": fake.unique.name(),
            "department": DEPARTMENTS[i % len(DEPARTMENTS)],
            "max_periods_per_day": random.randint(5, 7),
            "max_periods_per_week": random.randint(22, 30),
        })

    # ----------------------------------------------------------------
    # 3. Generate certifications
    # ----------------------------------------------------------------
    certifications = []
    cert_id = 1
    teacher_subjects = {}  # teacher_id -> [subjects]
    for t in teachers:
        dept = t["department"]
        possible = DEPT_SUBJECTS[dept]
        n_certs = min(len(possible), random.randint(1, 3))
        chosen = random.sample(possible, n_certs)
        teacher_subjects[t["teacher_id"]] = list(chosen)
        for subj in chosen:
            certifications.append({
                "cert_id": cert_id,
                "teacher_id": t["teacher_id"],
                "subject": subj,
                "certification_level": random.choice(["primary", "secondary"]),
            })
            cert_id += 1

    # Pad certifications to reach n_rows minimum
    while len(certifications) < n_rows:
        t = random.choice(teachers)
        tid = t["teacher_id"]
        existing = teacher_subjects.get(tid, [])
        dept_pool = DEPT_SUBJECTS[t["department"]]
        candidates = [s for s in dept_pool if s not in existing]
        if not candidates:
            all_s = [s for sl in DEPT_SUBJECTS.values() for s in sl]
            candidates = [s for s in all_s if s not in existing]
        if candidates:
            subj = random.choice(candidates)
            teacher_subjects.setdefault(tid, []).append(subj)
            certifications.append({
                "cert_id": cert_id,
                "teacher_id": tid,
                "subject": subj,
                "certification_level": "secondary",
            })
            cert_id += 1

    # ----------------------------------------------------------------
    # 4. Generate classes
    # ----------------------------------------------------------------
    n_classes = n_rows
    regular_subjects = [s for s in ALL_SUBJECTS if s not in SPECIALIST_ROOM_TYPE]
    specialist_subjects = list(SPECIALIST_ROOM_TYPE.keys())
    available_spec = [
        s for s in specialist_subjects
        if specialist_room_counts.get(SPECIALIST_ROOM_TYPE[s], 0) > 0
    ]

    n_specialist = max(1, n_classes // 4)
    n_regular = n_classes - n_specialist

    classes = []
    class_id = 1
    subject_grade_counter = {}

    def ensure_teacher_for(subj):
        nonlocal cert_id
        candidates = [
            tid for tid, subs in teacher_subjects.items() if subj in subs
        ]
        if candidates:
            return random.choice(candidates)
        t = random.choice(teachers)
        tid = t["teacher_id"]
        teacher_subjects.setdefault(tid, []).append(subj)
        certifications.append({
            "cert_id": cert_id,
            "teacher_id": tid,
            "subject": subj,
            "certification_level": "secondary",
        })
        cert_id += 1
        return tid

    for i in range(n_specialist):
        subj = available_spec[i % len(available_spec)]
        tid = ensure_teacher_for(subj)
        grade = GRADE_LEVELS[i % len(GRADE_LEVELS)]
        key = (subj, grade)
        subject_grade_counter[key] = subject_grade_counter.get(key, 0)
        section = chr(65 + subject_grade_counter[key])
        subject_grade_counter[key] += 1
        enrollment = random.randint(15, 25)
        classes.append({
            "class_id": class_id,
            "class_name": f"{subj} {grade}{section}",
            "subject": subj,
            "grade_level": grade,
            "teacher_id": tid,
            "num_students": enrollment,
        })
        class_id += 1

    for i in range(n_regular):
        subj = regular_subjects[i % len(regular_subjects)]
        tid = ensure_teacher_for(subj)
        grade = GRADE_LEVELS[i % len(GRADE_LEVELS)]
        key = (subj, grade)
        subject_grade_counter[key] = subject_grade_counter.get(key, 0)
        section = chr(65 + subject_grade_counter[key])
        subject_grade_counter[key] += 1
        enrollment = random.randint(20, 35)
        classes.append({
            "class_id": class_id,
            "class_name": f"{subj} {grade}{section}",
            "subject": subj,
            "grade_level": grade,
            "teacher_id": tid,
            "num_students": enrollment,
        })
        class_id += 1

    # ----------------------------------------------------------------
    # 5. Write database
    # ----------------------------------------------------------------
    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    cur = conn.cursor()

    cur.execute("""CREATE TABLE teachers (
        teacher_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        department TEXT NOT NULL,
        max_periods_per_day INTEGER NOT NULL,
        max_periods_per_week INTEGER NOT NULL
    )""")

    cur.execute("""CREATE TABLE certifications (
        cert_id INTEGER PRIMARY KEY,
        teacher_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        certification_level TEXT NOT NULL,
        FOREIGN KEY (teacher_id) REFERENCES teachers(teacher_id)
    )""")

    cur.execute("""CREATE TABLE classes (
        class_id INTEGER PRIMARY KEY,
        class_name TEXT NOT NULL,
        subject TEXT NOT NULL,
        grade_level INTEGER NOT NULL,
        teacher_id INTEGER NOT NULL,
        num_students INTEGER NOT NULL,
        FOREIGN KEY (teacher_id) REFERENCES teachers(teacher_id)
    )""")

    cur.execute("""CREATE TABLE rooms (
        room_id INTEGER PRIMARY KEY,
        room_name TEXT NOT NULL,
        capacity INTEGER NOT NULL,
        room_type TEXT NOT NULL,
        building TEXT NOT NULL,
        floor INTEGER NOT NULL
    )""")

    for t in teachers:
        cur.execute(
            "INSERT INTO teachers VALUES (?,?,?,?,?)",
            (t["teacher_id"], t["name"], t["department"],
             t["max_periods_per_day"], t["max_periods_per_week"]),
        )
    for c in certifications:
        cur.execute(
            "INSERT INTO certifications VALUES (?,?,?,?)",
            (c["cert_id"], c["teacher_id"], c["subject"],
             c["certification_level"]),
        )
    for c in classes:
        cur.execute(
            "INSERT INTO classes VALUES (?,?,?,?,?,?)",
            (c["class_id"], c["class_name"], c["subject"],
             c["grade_level"], c["teacher_id"], c["num_students"]),
        )
    for r in rooms:
        cur.execute(
            "INSERT INTO rooms VALUES (?,?,?,?,?,?)",
            (r["room_id"], r["room_name"], r["capacity"],
             r["room_type"], r["building"], r["floor"]),
        )

    conn.commit()
    conn.close()

    # ----------------------------------------------------------------
    # 6. Workspace — fixed policy / config files
    # ----------------------------------------------------------------

    # 6a. scheduling_policy.yaml
    policy = {
        "period_duration_minutes": 45,
        "max_consecutive_periods_per_teacher": 3,
        "min_free_periods_per_teacher_per_day": 1,
        "days": DAYS,
        "periods_per_day": PERIODS_PER_DAY,
    }
    with open(os.path.join(args.workspace, "scheduling_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # 6b. instructional_minutes.csv
    instr_rows = []
    for subj in ALL_SUBJECTS:
        for grade in GRADE_LEVELS:
            if subj in ("Mathematics", "English"):
                mins = 225    # -> ceil(225/45) = 5 periods
            elif subj in ("Science", "Chemistry", "Physics", "Biology",
                          "Computer Science"):
                mins = 180    # -> 4 periods
            elif subj == "Physical Education":
                mins = 135    # -> 3 periods
            else:
                mins = 135    # -> 3 periods
            instr_rows.append({
                "subject": subj,
                "grade_level": grade,
                "min_weekly_minutes": mins,
            })
    with open(os.path.join(args.workspace, "instructional_minutes.csv"),
              "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["subject", "grade_level", "min_weekly_minutes"])
        w.writeheader()
        w.writerows(instr_rows)

    # 6c. subject_equipment_requirements.json
    with open(os.path.join(args.workspace,
                           "subject_equipment_requirements.json"), "w") as f:
        json.dump(SUBJECT_EQUIPMENT_MAP, f, indent=2)

    # 6d. room_priority_rules.txt
    with open(os.path.join(args.workspace, "room_priority_rules.txt"), "w") as f:
        f.write("Room Assignment Priority Rules\n")
        f.write("=" * 40 + "\n\n")
        f.write(
            "1. Specialist rooms (labs, studios, gymnasium) must be reserved "
            "exclusively\n"
            "   for classes whose subject requires the specialist equipment.\n"
            "   Regular-subject classes may NOT be placed in specialist rooms.\n\n"
        )
        f.write(
            "2. When multiple rooms satisfy a class's requirements, assign the "
            "room\n"
            "   whose surplus capacity (room capacity minus enrollment) is "
            "smallest\n"
            "   but still non-negative (best-fit).\n\n"
        )
        f.write(
            "3. Classes with larger enrollment should be scheduled first to "
            "guarantee\n"
            "   they receive rooms with adequate capacity.\n\n"
        )
        f.write(
            "4. If two rooms have identical surplus capacity for a class, "
            "prefer the\n"
            "   room with the lower room_id.\n\n"
        )
        f.write(
            "5. Within a single day, no teacher may be assigned more periods "
            "than\n"
            "   their max_periods_per_day value.\n"
        )

    # 6e. scheduling_methodology.md
    with open(os.path.join(args.workspace, "scheduling_methodology.md"), "w") as f:
        f.write("# Scheduling Methodology\n\n")
        f.write("## School week\n\n")
        f.write(
            "The timetable covers exactly the days and the number of periods "
            "per day defined in the scheduling policy file.\n\n"
        )
        f.write("## Required weekly meetings per class\n\n")
        f.write(
            "A class's required number of weekly meeting periods is not "
            "stored directly. It is derived as:\n\n"
            "    required_periods = ceil(min_weekly_minutes / "
            "period_duration_minutes)\n\n"
            "where min_weekly_minutes is the value recorded for the class's "
            "subject and grade level in the instructional-minutes reference "
            "table, and period_duration_minutes comes from the scheduling "
            "policy. Round up to a whole number of periods. Each class must "
            "appear exactly that many times in the final weekly schedule.\n\n"
        )
        f.write("## Teacher availability and load\n\n")
        f.write(
            "The teacher availability files list the specific day-and-period "
            "combinations during which a teacher is UNAVAILABLE. Any slot not "
            "listed in those files is considered available. A class must "
            "never be scheduled in a slot where its teacher is marked "
            "unavailable. In addition, no teacher may exceed their "
            "max_periods_per_day within a single day or their "
            "max_periods_per_week across the week.\n\n"
        )
        f.write("## Room eligibility\n\n")
        f.write(
            "A room is eligible for a class only if both conditions hold:\n\n"
            "1. The room's seating capacity is at least as large as the "
            "class's student enrollment.\n"
            "2. The room's installed equipment (per the room equipment "
            "manifests) includes every item required by the class's subject "
            "(per the subject equipment requirements mapping). Subjects with "
            "an empty requirements list need no special equipment.\n\n"
            "Priorities and tie-breaking among eligible rooms and classes "
            "are governed by the room assignment priority rules document.\n"
        )

    # ----------------------------------------------------------------
    # 7. Workspace — scalable data files
    # ----------------------------------------------------------------
    n_room_files = n_files // 2
    n_teacher_files = n_files - n_room_files

    # 7a. Room equipment manifests (YAML)
    rooms_per_file = max(1, math.ceil(len(rooms) / n_room_files))
    for fidx in range(n_room_files):
        start = fidx * rooms_per_file
        end = min(start + rooms_per_file, len(rooms))
        batch = rooms[start:end]
        room_data = []
        for r in batch:
            equip_names = ROOM_TYPE_EQUIPMENT.get(r["room_type"], [])
            entries = []
            for eq in equip_names:
                qty = (random.randint(15, 35) if eq == "computers"
                       else random.randint(1, 6))
                entries.append({
                    "name": eq,
                    "quantity": qty,
                    "condition": random.choice(["good", "excellent", "fair"]),
                })
            room_data.append({
                "room_id": r["room_id"],
                "room_name": r["room_name"],
                "equipment": entries,
            })
        with open(os.path.join(args.workspace,
                               f"room_equipment_{fidx + 1}.yaml"), "w") as f:
            yaml.dump({"rooms": room_data}, f,
                      default_flow_style=False, sort_keys=False)

    # 7b. Teacher availability / unavailability (CSV)
    teachers_per_file = max(1, math.ceil(len(teachers) / n_teacher_files))
    for fidx in range(n_teacher_files):
        start = fidx * teachers_per_file
        end = min(start + teachers_per_file, len(teachers))
        batch = teachers[start:end]
        avail_rows = []
        for t in batch:
            n_unavail = random.randint(3, 6)
            unavail_slots = set()
            attempts = 0
            while len(unavail_slots) < n_unavail and attempts < 200:
                day = random.choice(DAYS)
                period = random.randint(1, PERIODS_PER_DAY)
                unavail_slots.add((day, period))
                attempts += 1
            for day, period in sorted(
                unavail_slots, key=lambda x: (DAYS.index(x[0]), x[1])
            ):
                avail_rows.append({
                    "teacher_id": t["teacher_id"],
                    "teacher_name": t["name"],
                    "day": day,
                    "period": period,
                    "available": 0,
                })
        with open(os.path.join(args.workspace,
                               f"teacher_availability_{fidx + 1}.csv"),
                  "w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["teacher_id", "teacher_name",
                            "day", "period", "available"],
            )
            w.writeheader()
            w.writerows(avail_rows)

    print(f"Database created at {args.db_path}")
    print(f"  Teachers:       {len(teachers)}")
    print(f"  Certifications: {len(certifications)}")
    print(f"  Classes:        {len(classes)}")
    print(f"  Rooms:          {len(rooms)}")
    print(f"Workspace created at {args.workspace}")
    print(f"  Scalable files: {n_files} "
          f"({n_room_files} room equip + {n_teacher_files} teacher avail)")
    print(f"  Fixed files:    5")


if __name__ == "__main__":
    main()
