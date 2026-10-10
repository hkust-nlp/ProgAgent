import os
import json
import csv
import sqlite3
import argparse
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 25,
    "num_workspace_files": 8,
}

SEED = 42
NUM_TIME_SLOTS = 6
PROGRAMS = ["Science", "Arts", "Commerce", "Technology"]
GRADES = [9, 10, 11, 12]

SUBJECTS = [
    "Mathematics", "Physics", "Chemistry", "Biology", "English",
    "History", "Geography", "Economics", "Computer Science", "Art",
    "Music", "Physical Education", "Foreign Language", "Philosophy",
    "Environmental Science",
]

COURSE_POOL = {
    "Mathematics": ["Algebra", "Calculus", "Statistics", "Geometry", "Trigonometry",
                     "Linear Algebra", "Discrete Math", "Number Theory", "Applied Math", "Math Modeling"],
    "Physics": ["Mechanics", "Electromagnetism", "Thermodynamics", "Optics", "Quantum Basics",
                "Astrophysics", "Wave Theory", "Nuclear Physics", "Fluid Dynamics", "Relativity"],
    "Chemistry": ["Organic Chemistry", "Inorganic Chemistry", "Analytical Chemistry", "Biochemistry",
                   "Physical Chemistry", "Polymer Chemistry", "Electrochemistry", "Thermochemistry",
                   "Green Chemistry", "Chemical Kinetics"],
    "Biology": ["Cell Biology", "Genetics", "Ecology", "Microbiology", "Anatomy",
                "Botany", "Zoology", "Evolution", "Marine Biology", "Neuroscience"],
    "English": ["Literature", "Creative Writing", "Grammar", "Public Speaking", "Journalism",
                "Poetry Analysis", "Drama Studies", "Film Studies", "Rhetoric", "World Literature"],
    "History": ["World History", "Ancient Civilizations", "Modern History", "American History",
                "European History", "Asian History", "War Studies", "Cultural History",
                "Renaissance Studies", "Medieval Studies"],
    "Geography": ["Physical Geography", "Human Geography", "Cartography", "Climate Studies",
                   "Urban Geography", "Geopolitics", "Oceanography", "Landform Studies", "GIS", "Demography"],
    "Economics": ["Microeconomics", "Macroeconomics", "International Trade", "Finance",
                   "Accounting", "Business Studies", "Economic History", "Development Economics",
                   "Game Theory", "Behavioral Economics"],
    "Computer Science": ["Programming", "Data Structures", "Web Development", "Database Systems",
                          "Algorithms", "AI Basics", "Cybersecurity", "Networking",
                          "Software Engineering", "Operating Systems"],
    "Art": ["Drawing", "Painting", "Sculpture", "Digital Art", "Art History",
            "Photography", "Printmaking", "Ceramics", "Graphic Design", "Animation"],
    "Music": ["Music Theory", "Band", "Choir", "Composition", "Music History",
              "Jazz Studies", "Orchestra", "Electronic Music", "Vocal Training", "Percussion"],
    "Physical Education": ["Fitness", "Team Sports", "Swimming", "Track and Field", "Yoga",
                            "Dance", "Martial Arts", "Health Science", "Gymnastics", "Outdoor Recreation"],
    "Foreign Language": ["Spanish", "French", "German", "Mandarin", "Japanese",
                          "Latin", "Italian", "Portuguese", "Korean", "Arabic"],
    "Philosophy": ["Ethics", "Logic", "Metaphysics", "Epistemology", "Political Philosophy",
                    "Aesthetics", "Philosophy of Science", "Eastern Philosophy", "Existentialism",
                    "Philosophy of Mind"],
    "Environmental Science": ["Ecology Systems", "Conservation", "Renewable Energy", "Pollution Studies",
                               "Wildlife Management", "Sustainability", "Climate Change",
                               "Environmental Policy", "Waste Management", "Water Resources"],
}


def _course_name(subject, index_within_subject):
    pool = COURSE_POOL[subject]
    base = pool[index_within_subject % len(pool)]
    cycle = index_within_subject // len(pool)
    if cycle == 0:
        return base
    elif cycle == 1:
        return f"Advanced {base}"
    else:
        return f"{base} Level {cycle + 1}"


def generate(db_path, workspace):
    np.random.seed(SEED)
    fake = Faker()
    Faker.seed(SEED)

    n = SCALE["rows_per_table"]
    nf = SCALE["num_workspace_files"]
    os.makedirs(workspace, exist_ok=True)

    # ================================================================
    # 1. Students
    # ================================================================
    students = []
    for i in range(n):
        students.append({
            "student_id": f"STU{i+1:04d}",
            "name": fake.unique.name(),
            "grade": GRADES[i % len(GRADES)],
            "program": PROGRAMS[i % len(PROGRAMS)],
            "gpa": round(float(np.random.uniform(2.0, 4.0)), 2),
        })

    # ================================================================
    # 2. Courses  (~50 % core, ~50 % elective)
    # ================================================================
    n_core = n // 2
    courses = []
    subj_counter = {}  # subject -> next index within subject
    for i in range(n):
        subj = SUBJECTS[i % len(SUBJECTS)]
        idx = subj_counter.get(subj, 0)
        subj_counter[subj] = idx + 1
        courses.append({
            "course_id": f"CRS{i+1:04d}",
            "course_name": _course_name(subj, idx),
            "course_type": "core" if i < n_core else "elective",
            "subject_area": subj,
        })

    # ================================================================
    # 3. Sections  (each course -> 1-2 sections; round-robin slots
    #    to guarantee every time slot gets coverage)
    # ================================================================
    sections = []
    sec_idx = 0
    slot_rr = 0  # round-robin counter for primary slot assignment
    for c in courses:
        n_sec = 1 if np.random.random() < 0.35 else 2
        used_slots = set()
        for j in range(n_sec):
            if j == 0:
                # primary section: round-robin across time slots
                slot = (slot_rr % NUM_TIME_SLOTS) + 1
                slot_rr += 1
            else:
                # secondary section: random unused slot
                avail = [s for s in range(1, NUM_TIME_SLOTS + 1) if s not in used_slots]
                slot = int(np.random.choice(avail))
            used_slots.add(slot)
            sec_idx += 1
            sections.append({
                "section_id": f"SEC{sec_idx:04d}",
                "course_id": c["course_id"],
                "time_slot": slot,
                "max_capacity": int(np.random.choice([15, 20, 25, 30])) * max(1, n // 25),
                "room": f"R{100 + sec_idx}",
            })
    # pad to meet SCALE minimum
    while len(sections) < n:
        c = courses[len(sections) % len(courses)]
        existing = {s["time_slot"] for s in sections if s["course_id"] == c["course_id"]}
        avail = [s for s in range(1, NUM_TIME_SLOTS + 1) if s not in existing]
        if avail:
            slot = int(np.random.choice(avail))
            sec_idx += 1
            sections.append({
                "section_id": f"SEC{sec_idx:04d}",
                "course_id": c["course_id"],
                "time_slot": slot,
                "max_capacity": int(np.random.choice([15, 20, 25, 30])) * max(1, n // 25),
                "room": f"R{100 + sec_idx}",
            })

    # ================================================================
    # 4. Teachers
    # ================================================================
    depts = sorted(set(c["subject_area"] for c in courses))
    teachers = []
    for i in range(n):
        teachers.append({
            "teacher_id": f"TCH{i+1:04d}",
            "teacher_name": fake.unique.name(),
            "department": depts[i % len(depts)],
        })

    # ================================================================
    # 5. Teacher availability  (each teacher available ~4-5 of 6 slots)
    # ================================================================
    teacher_avail = {}
    for t in teachers:
        cnt = int(np.random.choice([4, 5]))
        slots = sorted(np.random.choice(
            range(1, NUM_TIME_SLOTS + 1), size=cnt, replace=False
        ).tolist())
        teacher_avail[t["teacher_id"]] = slots

    # ================================================================
    # 6. Teacher assignments  (one teacher per section)
    # ================================================================
    dept_teachers = {}
    for t in teachers:
        dept_teachers.setdefault(t["department"], []).append(t["teacher_id"])

    teacher_assignments = []
    load = {}  # teacher_id -> count of assigned sections
    for sec in sections:
        c = next(co for co in courses if co["course_id"] == sec["course_id"])
        dept = c["subject_area"]
        slot = sec["time_slot"]

        # prefer same-department teachers available in this slot
        cands = [tid for tid in dept_teachers.get(dept, [])
                 if slot in teacher_avail.get(tid, [])]
        if not cands:
            # any teacher available
            cands = [t["teacher_id"] for t in teachers
                     if slot in teacher_avail.get(t["teacher_id"], [])]
        if not cands:
            # force-availability for a random teacher
            tid = teachers[len(teacher_assignments) % len(teachers)]["teacher_id"]
            teacher_avail[tid] = sorted(set(teacher_avail.get(tid, [])) | {slot})
            cands = [tid]

        cands.sort(key=lambda tid: (load.get(tid, 0), tid))
        chosen = cands[0]
        load[chosen] = load.get(chosen, 0) + 1
        teacher_assignments.append({
            "id": len(teacher_assignments) + 1,
            "teacher_id": chosen,
            "section_id": sec["section_id"],
        })

    # pad teacher_assignments if needed (shouldn't happen since #sections >= n)
    while len(teacher_assignments) < n:
        src = teacher_assignments[len(teacher_assignments) % len(sections)]
        teacher_assignments.append({
            "id": len(teacher_assignments) + 1,
            "teacher_id": src["teacher_id"],
            "section_id": src["section_id"],
        })

    # ================================================================
    # 7. Selectively invalidate ~15 % of sections (teacher becomes
    #    unavailable in that slot) to force cross-referencing.
    #    Guarantee every course keeps at least one *valid* section.
    # ================================================================
    # Helper: count active elective sections per time slot
    def _active_elective_per_slot():
        counts = {s: 0 for s in range(1, NUM_TIME_SLOTS + 1)}
        for sec in sections:
            c = next(co for co in courses if co["course_id"] == sec["course_id"])
            if c["course_type"] != "elective":
                continue
            ta = next(a for a in teacher_assignments if a["section_id"] == sec["section_id"])
            if sec["time_slot"] in teacher_avail.get(ta["teacher_id"], []):
                counts[sec["time_slot"]] += 1
        return counts

    n_inv = max(1, len(sections) // 7)
    invalidated = set()
    indices = list(range(len(sections)))
    np.random.shuffle(indices)

    for idx in indices:
        if len(invalidated) >= n_inv:
            break
        sec = sections[idx]
        cid = sec["course_id"]
        sid = sec["section_id"]
        slot = sec["time_slot"]
        ta_rec = next(a for a in teacher_assignments if a["section_id"] == sid)
        tid = ta_rec["teacher_id"]
        if slot not in teacher_avail.get(tid, []):
            continue

        # would this course still have >=1 valid section?
        other_valid = False
        for s2 in sections:
            if s2["course_id"] == cid and s2["section_id"] != sid:
                ta2 = next(a for a in teacher_assignments if a["section_id"] == s2["section_id"])
                if s2["time_slot"] in teacher_avail.get(ta2["teacher_id"], []):
                    other_valid = True
                    break
        if not other_valid:
            continue

        # don't reduce active electives in any slot below 2
        c_obj = next(co for co in courses if co["course_id"] == cid)
        if c_obj["course_type"] == "elective":
            elec_counts = _active_elective_per_slot()
            if elec_counts.get(slot, 0) <= 2:
                continue

        teacher_avail[tid] = [s for s in teacher_avail[tid] if s != slot]
        invalidated.add(sid)

    # ================================================================
    # 8. Core requirements  (3 per program-grade, non-conflicting slots)
    # ================================================================
    core_courses = [c for c in courses if c["course_type"] == "core"]

    # build valid-section-slot map (only sections where teacher IS available)
    valid_section_slots = {}   # course_id -> set of time_slots with valid sections
    for sec in sections:
        ta = next(a for a in teacher_assignments if a["section_id"] == sec["section_id"])
        if sec["time_slot"] in teacher_avail.get(ta["teacher_id"], []):
            valid_section_slots.setdefault(sec["course_id"], set()).add(sec["time_slot"])

    core_reqs = {}
    for prog in PROGRAMS:
        core_reqs[prog] = {}
        for grade in GRADES:
            seed_val = (PROGRAMS.index(prog) * len(GRADES) + GRADES.index(grade) + SEED) % (2**31)
            rng = np.random.RandomState(seed_val)
            shuffled = list(core_courses)
            rng.shuffle(shuffled)

            selected = []
            used_slots = set()
            for cc in shuffled:
                slots = valid_section_slots.get(cc["course_id"], set())
                free = slots - used_slots
                if free:
                    selected.append(cc["course_id"])
                    used_slots.add(min(free))
                if len(selected) >= 3:
                    break

            core_reqs[prog][str(grade)] = selected

    # ================================================================
    # 9. Student elective preferences
    # ================================================================
    electives = [c for c in courses if c["course_type"] == "elective"]
    elective_ids = [c["course_id"] for c in electives]
    student_prefs = {}
    for s in students:
        # rank ALL electives so every time slot can be filled
        shuffled_elecs = list(elective_ids)
        np.random.shuffle(shuffled_elecs)
        student_prefs[s["student_id"]] = [
            {"course_id": cid, "preference_rank": rank + 1}
            for rank, cid in enumerate(shuffled_elecs)
        ]

    # ================================================================
    # WRITE DATABASE
    # ================================================================
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS students (
        student_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        grade INTEGER NOT NULL,
        program TEXT NOT NULL,
        gpa REAL NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS courses (
        course_id TEXT PRIMARY KEY,
        course_name TEXT NOT NULL,
        course_type TEXT NOT NULL,
        subject_area TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS sections (
        section_id TEXT PRIMARY KEY,
        course_id TEXT NOT NULL,
        time_slot INTEGER NOT NULL,
        max_capacity INTEGER NOT NULL,
        room TEXT NOT NULL,
        FOREIGN KEY (course_id) REFERENCES courses(course_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS teachers (
        teacher_id TEXT PRIMARY KEY,
        teacher_name TEXT NOT NULL,
        department TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS teacher_assignments (
        id INTEGER PRIMARY KEY,
        teacher_id TEXT NOT NULL,
        section_id TEXT NOT NULL,
        FOREIGN KEY (teacher_id) REFERENCES teachers(teacher_id),
        FOREIGN KEY (section_id) REFERENCES sections(section_id)
    )""")

    for s in students:
        cur.execute("INSERT INTO students VALUES (?,?,?,?,?)",
                    (s["student_id"], s["name"], s["grade"], s["program"], s["gpa"]))
    for c in courses:
        cur.execute("INSERT INTO courses VALUES (?,?,?,?)",
                    (c["course_id"], c["course_name"], c["course_type"], c["subject_area"]))
    for sec in sections:
        cur.execute("INSERT INTO sections VALUES (?,?,?,?,?)",
                    (sec["section_id"], sec["course_id"], sec["time_slot"],
                     sec["max_capacity"], sec["room"]))
    for t in teachers:
        cur.execute("INSERT INTO teachers VALUES (?,?,?)",
                    (t["teacher_id"], t["teacher_name"], t["department"]))
    for ta in teacher_assignments:
        cur.execute("INSERT INTO teacher_assignments VALUES (?,?,?)",
                    (ta["id"], ta["teacher_id"], ta["section_id"]))

    conn.commit()
    conn.close()

    # ================================================================
    # WRITE WORKSPACE — fixed (policy / config) files
    # ================================================================

    # core_requirements.json
    with open(os.path.join(workspace, "core_requirements.json"), "w") as f:
        json.dump(core_reqs, f, indent=2)

    # scheduling_policy.yaml  (hand-written to avoid pyyaml dependency)
    with open(os.path.join(workspace, "scheduling_policy.yaml"), "w") as f:
        f.write("# Scheduling Policy Configuration\n")
        f.write("priority_order: gpa_descending\n")
        f.write("tiebreaker: student_id_ascending\n")
        f.write("core_section_selection: largest_remaining_capacity\n")
        f.write("core_section_tiebreaker: section_id_ascending\n")
        f.write("elective_overflow: next_preference\n")
        f.write("elective_section_selection: largest_remaining_capacity\n")
        f.write("elective_section_tiebreaker: section_id_ascending\n")
        f.write(f"max_time_slots: {NUM_TIME_SLOTS}\n")

    # period_definitions.txt
    times = [
        ("08:00", "09:00"), ("09:15", "10:15"), ("10:30", "11:30"),
        ("12:30", "13:30"), ("13:45", "14:45"), ("15:00", "16:00"),
    ]
    with open(os.path.join(workspace, "period_definitions.txt"), "w") as f:
        f.write("Semester Period Schedule\n")
        f.write("=" * 40 + "\n")
        for i, (start, end) in enumerate(times, 1):
            f.write(f"Time Slot {i}: {start} - {end}\n")
        f.write("\nAll courses meet once per day in their assigned time slot.\n")

    # enrollment_rules.md
    with open(os.path.join(workspace, "enrollment_rules.md"), "w") as f:
        f.write("# Enrollment Rules and Scheduling Procedures\n\n")
        f.write("Students are assigned to course sections following the scheduling policy "
                "parameters defined in the policy configuration file. The overall process is:\n\n")
        f.write("1. Students are processed in the priority order specified by the policy "
                "(typically by GPA, descending). When two students share the same GPA, "
                "the tiebreaker field determines who is processed first.\n\n")
        f.write("2. For each student, core courses mandated by their program and grade are "
                "assigned first. When a core course offers multiple active sections, the "
                "section selection rule in the policy applies (e.g., pick the section with "
                "the largest remaining capacity; break ties by section ID).\n\n")
        f.write("3. After core courses are placed, remaining empty time slots are filled with "
                "electives drawn from the student's preference survey. Preferences are tried "
                "in ascending rank order (rank 1 = most preferred). For each preference, the "
                "system looks for an active section of that course in one of the student's "
                "still-open time slots. If a matching section with remaining capacity exists, "
                "the student is enrolled. Otherwise the next preference is tried.\n\n")
        f.write("4. A section is considered **active** only if the teacher assigned to it is "
                "available during the section's time slot according to the current teacher "
                "schedule records. Sections whose assigned teacher is unavailable in the "
                "scheduled time slot must be treated as inactive and must never receive "
                "student enrollments.\n\n")
        f.write("5. If no elective can be placed in a time slot, it remains unassigned for "
                "that student.\n")

    # ================================================================
    # WRITE WORKSPACE — scalable files
    # ================================================================
    n_pref_files = nf // 2
    n_sched_files = nf - n_pref_files

    # preference batch CSVs
    pref_dir = os.path.join(workspace, "preferences")
    os.makedirs(pref_dir, exist_ok=True)
    sids = [s["student_id"] for s in students]
    batch = max(1, len(sids) // n_pref_files)
    for bi in range(n_pref_files):
        lo = bi * batch
        hi = lo + batch if bi < n_pref_files - 1 else len(sids)
        fp = os.path.join(pref_dir, f"batch_{bi+1:03d}.csv")
        with open(fp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["student_id", "course_id", "preference_rank"])
            for sid in sids[lo:hi]:
                for p in student_prefs.get(sid, []):
                    w.writerow([sid, p["course_id"], p["preference_rank"]])

    # teacher schedule CSVs
    sched_dir = os.path.join(workspace, "teacher_schedules")
    os.makedirs(sched_dir, exist_ok=True)
    tids = [t["teacher_id"] for t in teachers]
    batch_t = max(1, len(tids) // n_sched_files)
    for bi in range(n_sched_files):
        lo = bi * batch_t
        hi = lo + batch_t if bi < n_sched_files - 1 else len(tids)
        fp = os.path.join(sched_dir, f"schedule_{bi+1:03d}.csv")
        with open(fp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["teacher_id"] + [f"slot_{s}" for s in range(1, NUM_TIME_SLOTS + 1)])
            for tid in tids[lo:hi]:
                avail = teacher_avail.get(tid, [])
                w.writerow([tid] + [1 if s in avail else 0 for s in range(1, NUM_TIME_SLOTS + 1)])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    generate(args.db_path, args.workspace)


if __name__ == "__main__":
    main()
