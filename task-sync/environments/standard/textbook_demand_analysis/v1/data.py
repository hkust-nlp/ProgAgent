"""
Data generation for textbook availability monitoring task.
Generates database tables and workspace files for cross-referencing
course enrollments, library inventory, circulation data, and reservation queues.
"""

import argparse
import json
import os
import sqlite3
import random
import yaml
import csv

import numpy as np
import pandas as pd
from faker import Faker


SCALE = {
    "rows_per_table": 100,
    "num_workspace_files": 20,
}

DEPARTMENTS = [
    "Computer Science",
    "Mathematics",
    "Physics",
    "Biology",
    "Chemistry",
    "Economics",
    "Psychology",
    "English Literature",
]

SEMESTERS = ["Fall 2025", "Spring 2026"]

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)


def create_tables(conn):
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS courses (
            course_id INTEGER PRIMARY KEY,
            course_code TEXT NOT NULL,
            course_name TEXT NOT NULL,
            department TEXT NOT NULL,
            semester TEXT NOT NULL,
            section TEXT NOT NULL,
            instructor TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS textbooks (
            textbook_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            isbn TEXT NOT NULL UNIQUE,
            edition INTEGER NOT NULL,
            publisher TEXT NOT NULL,
            retail_price REAL NOT NULL,
            year_published INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS course_textbooks (
            id INTEGER PRIMARY KEY,
            course_id INTEGER NOT NULL,
            textbook_id INTEGER NOT NULL,
            requirement_type TEXT NOT NULL,
            FOREIGN KEY (course_id) REFERENCES courses(course_id),
            FOREIGN KEY (textbook_id) REFERENCES textbooks(textbook_id)
        );

        CREATE TABLE IF NOT EXISTS inventory (
            inventory_id INTEGER PRIMARY KEY,
            textbook_id INTEGER NOT NULL,
            branch TEXT NOT NULL,
            total_copies INTEGER NOT NULL,
            available_copies INTEGER NOT NULL,
            condition TEXT NOT NULL,
            last_audit_date TEXT NOT NULL,
            FOREIGN KEY (textbook_id) REFERENCES textbooks(textbook_id)
        );

        CREATE TABLE IF NOT EXISTS circulation (
            circulation_id INTEGER PRIMARY KEY,
            textbook_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            checkout_date TEXT NOT NULL,
            due_date TEXT NOT NULL,
            return_date TEXT,
            branch TEXT NOT NULL,
            renewals INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (textbook_id) REFERENCES textbooks(textbook_id)
        );

        CREATE TABLE IF NOT EXISTS reservations (
            reservation_id INTEGER PRIMARY KEY,
            textbook_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            request_date TEXT NOT NULL,
            status TEXT NOT NULL,
            position_in_queue INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            FOREIGN KEY (textbook_id) REFERENCES textbooks(textbook_id),
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        );
    """)
    conn.commit()


def generate_courses(conn, n_courses):
    """Generate course records across departments and semesters."""
    course_prefixes = {
        "Computer Science": ("CS", ["Data Structures", "Algorithms", "Operating Systems",
            "Database Systems", "Machine Learning", "Computer Networks", "Software Engineering",
            "Artificial Intelligence", "Computer Architecture", "Compiler Design",
            "Distributed Systems", "Cybersecurity", "Computer Graphics", "Theory of Computation",
            "Parallel Computing", "Natural Language Processing", "Cloud Computing",
            "Embedded Systems", "Information Retrieval", "Quantum Computing"]),
        "Mathematics": ("MATH", ["Calculus", "Linear Algebra", "Discrete Mathematics",
            "Probability Theory", "Abstract Algebra", "Real Analysis", "Topology",
            "Number Theory", "Differential Equations", "Numerical Methods",
            "Complex Analysis", "Combinatorics", "Graph Theory", "Mathematical Logic",
            "Optimization", "Statistics", "Stochastic Processes", "Functional Analysis",
            "Algebraic Geometry", "Cryptography"]),
        "Physics": ("PHYS", ["Classical Mechanics", "Electromagnetism", "Quantum Mechanics",
            "Thermodynamics", "Optics", "Nuclear Physics", "Particle Physics",
            "Astrophysics", "Solid State Physics", "Statistical Mechanics",
            "Fluid Dynamics", "Relativity", "Plasma Physics", "Biophysics",
            "Photonics", "Acoustics", "Geophysics", "Materials Science",
            "Computational Physics", "Atomic Physics"]),
        "Biology": ("BIO", ["Cell Biology", "Genetics", "Molecular Biology",
            "Ecology", "Evolution", "Microbiology", "Biochemistry",
            "Anatomy", "Physiology", "Immunology",
            "Neuroscience", "Marine Biology", "Botany", "Zoology",
            "Developmental Biology", "Bioinformatics", "Virology", "Parasitology",
            "Conservation Biology", "Systems Biology"]),
        "Chemistry": ("CHEM", ["General Chemistry", "Organic Chemistry", "Inorganic Chemistry",
            "Physical Chemistry", "Analytical Chemistry", "Biochemistry Fundamentals",
            "Polymer Chemistry", "Environmental Chemistry", "Medicinal Chemistry",
            "Computational Chemistry", "Nuclear Chemistry", "Electrochemistry",
            "Spectroscopy", "Chemical Engineering Basics", "Surface Chemistry",
            "Geochemistry", "Food Chemistry", "Industrial Chemistry",
            "Nanochemistry", "Photochemistry"]),
        "Economics": ("ECON", ["Microeconomics", "Macroeconomics", "Econometrics",
            "International Trade", "Public Finance", "Labor Economics",
            "Development Economics", "Monetary Economics", "Game Theory",
            "Behavioral Economics", "Financial Economics", "Health Economics",
            "Environmental Economics", "Urban Economics", "Industrial Organization",
            "Economic History", "Agricultural Economics", "Political Economy",
            "Experimental Economics", "Welfare Economics"]),
        "Psychology": ("PSY", ["Cognitive Psychology", "Developmental Psychology",
            "Social Psychology", "Abnormal Psychology", "Clinical Psychology",
            "Neurocognition", "Behavioral Psychology", "Research Methods",
            "Personality Theory", "Educational Psychology",
            "Industrial Psychology", "Health Psychology", "Forensic Psychology",
            "Positive Psychology", "Psychopharmacology", "Psychometrics",
            "Evolutionary Psychology", "Cultural Psychology",
            "Sport Psychology", "Environmental Psychology"]),
        "English Literature": ("ENGL", ["British Literature", "American Literature",
            "World Literature", "Shakespeare Studies", "Creative Writing",
            "Literary Theory", "Modern Poetry", "Victorian Literature",
            "Postcolonial Literature", "Renaissance Literature",
            "Gothic Literature", "Children's Literature", "Drama Studies",
            "Romantic Literature", "Comparative Literature", "Digital Humanities",
            "Feminist Literature", "Science Fiction Studies",
            "Narrative Theory", "Linguistics"]),
    }

    courses = []
    course_id = 1
    courses_per_dept = max(n_courses // len(DEPARTMENTS), 2)

    for dept in DEPARTMENTS:
        prefix, names = course_prefixes[dept]
        n_for_dept = min(courses_per_dept, len(names))
        selected_names = names[:n_for_dept]
        for i, name in enumerate(selected_names):
            for sem in SEMESTERS:
                n_sections = random.randint(1, 2)
                for sec in range(1, n_sections + 1):
                    courses.append({
                        "course_id": course_id,
                        "course_code": f"{prefix}{100 + i * 10}",
                        "course_name": name,
                        "department": dept,
                        "semester": sem,
                        "section": f"SEC-{sec:02d}",
                        "instructor": fake.name(),
                    })
                    course_id += 1
                    if course_id > n_courses:
                        break
                if course_id > n_courses:
                    break
            if course_id > n_courses:
                break
        if course_id > n_courses:
            break

    # Fill remaining if needed
    while len(courses) < n_courses:
        dept = random.choice(DEPARTMENTS)
        prefix, names = course_prefixes[dept]
        name = random.choice(names)
        courses.append({
            "course_id": course_id,
            "course_code": f"{prefix}{100 + random.randint(0, 19) * 10}",
            "course_name": name,
            "department": dept,
            "semester": random.choice(SEMESTERS),
            "section": f"SEC-{random.randint(1, 3):02d}",
            "instructor": fake.name(),
        })
        course_id += 1

    df = pd.DataFrame(courses[:n_courses])
    df.to_sql("courses", conn, if_exists="replace", index=False)
    return df


def generate_textbooks(conn, n_textbooks):
    """Generate textbook catalog."""
    publishers = [
        "Pearson", "McGraw-Hill", "Wiley", "Cambridge University Press",
        "Oxford University Press", "Springer", "Cengage", "Elsevier",
        "MIT Press", "Academic Press", "CRC Press", "Routledge",
    ]
    subjects = [
        "Introduction to", "Advanced", "Fundamentals of", "Principles of",
        "Modern", "Applied", "Theoretical", "Computational",
        "Essential", "Comprehensive",
    ]
    topics = [
        "Computing", "Mathematics", "Physics", "Biology", "Chemistry",
        "Economics", "Psychology", "Statistics", "Engineering", "Logic",
        "Analysis", "Algebra", "Mechanics", "Systems", "Networks",
        "Genetics", "Ecology", "Finance", "Behavior", "Literature",
        "Algorithms", "Data Science", "Probability", "Topology", "Dynamics",
    ]

    textbooks = []
    used_isbns = set()
    for tid in range(1, n_textbooks + 1):
        subj = random.choice(subjects)
        topic = random.choice(topics)
        title = f"{subj} {topic}"
        # Ensure unique ISBN
        while True:
            isbn = f"978-{random.randint(0,9)}-{random.randint(1000,9999)}-{random.randint(1000,9999)}-{random.randint(0,9)}"
            if isbn not in used_isbns:
                used_isbns.add(isbn)
                break

        textbooks.append({
            "textbook_id": tid,
            "title": title,
            "author": fake.name(),
            "isbn": isbn,
            "edition": random.randint(1, 8),
            "publisher": random.choice(publishers),
            "retail_price": round(random.uniform(35.0, 180.0), 2),
            "year_published": random.randint(2015, 2025),
        })

    df = pd.DataFrame(textbooks)
    df.to_sql("textbooks", conn, if_exists="replace", index=False)
    return df


def generate_course_textbooks(conn, courses_df, textbooks_df, n_rows):
    """Generate course-textbook requirement mappings."""
    course_ids = courses_df["course_id"].tolist()
    textbook_ids = textbooks_df["textbook_id"].tolist()
    mappings = []
    used_pairs = set()
    mid = 1

    # Ensure every textbook is assigned to at least one course
    for tid in textbook_ids:
        cid = random.choice(course_ids)
        pair = (cid, tid)
        if pair not in used_pairs:
            used_pairs.add(pair)
            mappings.append({
                "id": mid,
                "course_id": cid,
                "textbook_id": tid,
                "requirement_type": random.choice(["required", "required", "recommended"]),
            })
            mid += 1

    # Fill to n_rows
    while len(mappings) < n_rows:
        cid = random.choice(course_ids)
        tid = random.choice(textbook_ids)
        pair = (cid, tid)
        if pair not in used_pairs:
            used_pairs.add(pair)
            mappings.append({
                "id": mid,
                "course_id": cid,
                "textbook_id": tid,
                "requirement_type": random.choice(["required", "required", "recommended"]),
            })
            mid += 1

    df = pd.DataFrame(mappings[:max(n_rows, len(mappings))])
    df.to_sql("course_textbooks", conn, if_exists="replace", index=False)
    return df


def generate_inventory(conn, textbooks_df, n_rows):
    """Generate library inventory records across branches."""
    branches = ["Main Library", "Science Library", "Humanities Library", "Engineering Library"]
    inventory = []
    inv_id = 1
    textbook_ids = textbooks_df["textbook_id"].tolist()

    # Ensure each textbook has at least one inventory entry
    for tid in textbook_ids:
        branch = random.choice(branches)
        total = random.randint(2, 20)
        available = random.randint(0, total)
        inventory.append({
            "inventory_id": inv_id,
            "textbook_id": tid,
            "branch": branch,
            "total_copies": total,
            "available_copies": available,
            "condition": random.choice(["new", "good", "fair", "worn"]),
            "last_audit_date": fake.date_between(
                start_date="-6m", end_date="today"
            ).isoformat(),
        })
        inv_id += 1

    # Fill remaining rows with additional branch entries
    while len(inventory) < n_rows:
        tid = random.choice(textbook_ids)
        branch = random.choice(branches)
        total = random.randint(1, 15)
        available = random.randint(0, total)
        inventory.append({
            "inventory_id": inv_id,
            "textbook_id": tid,
            "branch": branch,
            "total_copies": total,
            "available_copies": available,
            "condition": random.choice(["new", "good", "fair", "worn"]),
            "last_audit_date": fake.date_between(
                start_date="-6m", end_date="today"
            ).isoformat(),
        })
        inv_id += 1

    df = pd.DataFrame(inventory[:max(n_rows, len(inventory))])
    df.to_sql("inventory", conn, if_exists="replace", index=False)
    return df


def generate_circulation(conn, textbooks_df, n_rows):
    """Generate historical circulation (checkout) records."""
    textbook_ids = textbooks_df["textbook_id"].tolist()
    branches = ["Main Library", "Science Library", "Humanities Library", "Engineering Library"]
    records = []

    for cid in range(1, n_rows + 1):
        tid = random.choice(textbook_ids)
        checkout = fake.date_between(start_date="-12m", end_date="-1d")
        due = checkout + pd.Timedelta(days=random.choice([14, 21, 28]))
        # 70% returned, 30% still out
        if random.random() < 0.7:
            return_date = checkout + pd.Timedelta(days=random.randint(1, 35))
            return_date = min(return_date, pd.Timestamp.today().date())
            return_str = return_date.isoformat()
        else:
            return_str = None

        records.append({
            "circulation_id": cid,
            "textbook_id": tid,
            "student_id": f"STU{random.randint(10000, 99999)}",
            "checkout_date": checkout.isoformat(),
            "due_date": due.isoformat(),
            "return_date": return_str,
            "branch": random.choice(branches),
            "renewals": random.choices([0, 1, 2, 3], weights=[50, 30, 15, 5])[0],
        })

    df = pd.DataFrame(records)
    df.to_sql("circulation", conn, if_exists="replace", index=False)
    return df


def generate_reservations(conn, textbooks_df, courses_df, ct_df, n_rows):
    """Generate reservation queue records."""
    # Only create reservations for textbooks that are assigned to courses
    valid_tids = ct_df["textbook_id"].unique().tolist()
    course_for_textbook = {}
    for _, row in ct_df.iterrows():
        tid = row["textbook_id"]
        if tid not in course_for_textbook:
            course_for_textbook[tid] = []
        course_for_textbook[tid].append(row["course_id"])

    records = []
    # Group by textbook so position_in_queue makes sense
    tid_counts = {}
    for rid in range(1, n_rows + 1):
        tid = random.choice(valid_tids)
        tid_counts[tid] = tid_counts.get(tid, 0) + 1
        pos = tid_counts[tid]
        cid = random.choice(course_for_textbook[tid])

        records.append({
            "reservation_id": rid,
            "textbook_id": tid,
            "student_id": f"STU{random.randint(10000, 99999)}",
            "request_date": fake.date_between(start_date="-3m", end_date="today").isoformat(),
            "status": random.choice(["pending", "pending", "pending", "fulfilled", "cancelled"]),
            "position_in_queue": pos,
            "course_id": cid,
        })

    df = pd.DataFrame(records)
    df.to_sql("reservations", conn, if_exists="replace", index=False)
    return df


def generate_workspace(workspace, conn, courses_df, textbooks_df, ct_df):
    """Generate workspace files: scalable data files + fixed config files."""
    os.makedirs(workspace, exist_ok=True)

    n_files = SCALE["num_workspace_files"]
    n_enrollment_files = (n_files + 1) // 2
    n_circulation_files = n_files - n_enrollment_files

    # ---- Scalable files: enrollment batch CSVs ----
    # Each file contains enrollment details for a batch of courses
    # These include waitlist_count and lab_section_flag NOT in the database
    course_records = courses_df.to_dict("records")
    random.shuffle(course_records)
    batches = np.array_split(course_records, n_enrollment_files)

    for i, batch in enumerate(batches):
        rows = []
        for c in batch:
            enrollment = random.randint(15, 120)
            waitlist = random.randint(0, max(1, enrollment // 4))
            rows.append({
                "course_id": int(c["course_id"]),
                "course_code": c["course_code"],
                "course_name": c["course_name"],
                "department": c["department"],
                "semester": c["semester"],
                "section": c["section"],
                "enrolled_students": enrollment,
                "waitlisted_students": waitlist,
                "has_lab_section": random.choice(["yes", "no"]),
            })
        edf = pd.DataFrame(rows)
        edf.to_csv(os.path.join(workspace, f"enrollment_batch_{i+1:03d}.csv"), index=False)

    # ---- Scalable files: circulation summary CSVs ----
    # Monthly aggregated circulation data with overdue counts (not in DB directly)
    circ_df = pd.read_sql("SELECT * FROM circulation", conn)
    textbook_ids = textbooks_df["textbook_id"].tolist()

    months = []
    base_date = pd.Timestamp("2025-01-01")
    for m in range(n_circulation_files):
        month_start = base_date + pd.DateOffset(months=m)
        months.append(month_start.strftime("%Y-%m"))

    for i, month_str in enumerate(months):
        rows = []
        year, mo = month_str.split("-")
        year, mo = int(year), int(mo)
        for tid in textbook_ids:
            subset = circ_df[circ_df["textbook_id"] == tid]
            subset_month = subset[
                pd.to_datetime(subset["checkout_date"]).dt.month == ((mo - 1) % 12 + 1)
            ]
            checkouts = len(subset_month)
            if checkouts == 0 and random.random() < 0.5:
                continue
            overdue = 0
            for _, r in subset_month.iterrows():
                if r["return_date"] is not None and not pd.isna(r["return_date"]):
                    if r["return_date"] > r["due_date"]:
                        overdue += 1
                elif r["return_date"] is None or pd.isna(r["return_date"]):
                    overdue += 1

            rows.append({
                "textbook_id": int(tid),
                "month": month_str,
                "total_checkouts": checkouts,
                "overdue_count": overdue,
                "avg_loan_days": round(random.uniform(7.0, 28.0), 1),
                "peak_holds": random.randint(0, max(1, checkouts)),
            })
        if rows:
            cdf = pd.DataFrame(rows)
            cdf.to_csv(os.path.join(workspace, f"circulation_summary_{month_str}.csv"), index=False)

    # ---- Fixed config files ----

    # 1. Procurement policy (YAML)
    policy = {
        "shortage_risk_scoring": {
            "weights": {
                "demand_supply_ratio": 0.35,
                "reservation_pressure": 0.25,
                "circulation_intensity": 0.20,
                "waitlist_factor": 0.20,
            },
            "risk_thresholds": {
                "critical": 0.75,
                "high": 0.50,
                "medium": 0.25,
            },
            "notes": "Scores below medium threshold are classified as low risk.",
        },
        "purchase_quantity_formula": {
            "description": "Recommended purchase = ceil(total_demand * target_ratio) - total_inventory_copies",
            "target_ratio": 0.5,
            "minimum_order": 2,
            "notes": "If computed quantity is below minimum_order but positive, round up to minimum_order. If zero or negative, no purchase needed.",
        },
        "priority_tier_scores": {
            "critical": 4,
            "high": 3,
            "medium": 2,
            "low": 1,
        },
        "demand_calculation": {
            "description": "Total demand for a textbook = sum of (enrolled_students + waitlisted_students) across all courses that list it as required. Recommended-only textbooks are excluded from shortage analysis.",
        },
    }
    with open(os.path.join(workspace, "procurement_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # 2. Budget allocation (JSON)
    budget = {}
    for dept in DEPARTMENTS:
        budget[dept] = round(random.uniform(5000, 25000), 2)
    budget_data = {
        "fiscal_year": "2025-2026",
        "department_budgets": budget,
        "notes": "Budget amounts are the maximum allowable procurement spend per department for the fiscal year.",
    }
    with open(os.path.join(workspace, "budget_allocation.json"), "w") as f:
        json.dump(budget_data, f, indent=2)

    # 3. Supplier discount schedule (CSV)
    discount_rows = [
        {"quantity_min": 1, "quantity_max": 5, "discount_pct": 0.0},
        {"quantity_min": 6, "quantity_max": 15, "discount_pct": 5.0},
        {"quantity_min": 16, "quantity_max": 30, "discount_pct": 10.0},
        {"quantity_min": 31, "quantity_max": 50, "discount_pct": 15.0},
        {"quantity_min": 51, "quantity_max": 9999, "discount_pct": 20.0},
    ]
    ddf = pd.DataFrame(discount_rows)
    ddf.to_csv(os.path.join(workspace, "supplier_discounts.csv"), index=False)

    # 4. Branch priority mapping (TXT)
    with open(os.path.join(workspace, "branch_priority.txt"), "w") as f:
        f.write("Branch Priority Rankings for Procurement Allocation\n")
        f.write("=" * 50 + "\n\n")
        f.write("When distributing newly purchased copies across branches,\n")
        f.write("allocate proportionally to each branch's current demand.\n\n")
        f.write("Branch Name             | Priority Weight\n")
        f.write("-" * 45 + "\n")
        f.write("Main Library            | 0.40\n")
        f.write("Science Library         | 0.30\n")
        f.write("Humanities Library      | 0.15\n")
        f.write("Engineering Library     | 0.15\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # Set all seeds
    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    fake2 = Faker()
    Faker.seed(42)

    n_rows = SCALE["rows_per_table"]

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    courses_df = generate_courses(conn, n_rows)
    textbooks_df = generate_textbooks(conn, n_rows)
    ct_df = generate_course_textbooks(conn, courses_df, textbooks_df, n_rows)
    generate_inventory(conn, textbooks_df, n_rows)
    generate_circulation(conn, textbooks_df, max(n_rows, 2 * n_rows))
    generate_reservations(conn, textbooks_df, courses_df, ct_df, n_rows)

    generate_workspace(args.workspace, conn, courses_df, textbooks_df, ct_df)

    conn.close()
    print(f"Database created at {args.db_path}")
    print(f"Workspace files generated in {args.workspace}")


if __name__ == "__main__":
    main()
