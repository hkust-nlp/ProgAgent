"""
Data generation script for grant application risk assessment task.
Generates database and workspace files for evaluating budget risk in grant proposals.
"""

import argparse
import json
import os
import sqlite3
import yaml
import csv

import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 100,       # v0 base; v1 = 2×, v2 = 4×, v3 = 8×
    "num_workspace_files": 20,  # v0 base; v1 = +N, v2 = +2N, v3 = +3N  (N = base)
}

fake = Faker()
Faker.seed(42)
np.random.seed(42)

# --- Constants ---
INSTITUTION_TYPES = ["university", "research_institute", "medical_center", "national_lab", "nonprofit"]
CAREER_STAGES = ["early", "mid", "senior"]
DEPARTMENTS = [
    "Biology", "Chemistry", "Physics", "Computer Science", "Engineering",
    "Mathematics", "Environmental Science", "Neuroscience", "Public Health",
    "Biomedical Engineering", "Materials Science", "Economics", "Psychology",
    "Sociology", "Political Science"
]
PROGRAM_AREAS = [
    "Biomedical Research", "Environmental Sciences", "Physical Sciences",
    "Engineering & Technology", "Social & Behavioral Sciences", "Computational Sciences",
    "Interdisciplinary Studies", "Public Health", "Agricultural Sciences"
]
EXPENSE_CATEGORIES = [
    "personnel", "equipment", "travel", "supplies", "contractual",
    "other_direct", "indirect_costs"
]
EXPENSE_SUBCATEGORIES = {
    "personnel": ["PI salary", "postdoc salary", "grad student stipend", "technician salary", "admin support"],
    "equipment": ["computing hardware", "lab instruments", "field equipment", "software licenses", "specialized apparatus"],
    "travel": ["domestic conference", "international conference", "field work", "collaboration visit", "training workshop"],
    "supplies": ["lab consumables", "chemicals", "animal subjects", "data storage", "office supplies"],
    "contractual": ["subcontract", "consulting", "services agreement", "data acquisition", "facility rental"],
    "other_direct": ["publication costs", "participant support", "tuition remission", "communication", "insurance"],
    "indirect_costs": ["facilities", "administration", "utilities", "depreciation", "general overhead"],
}
APP_STATUSES = ["pending_review", "approved", "rejected", "under_revision"]


def create_tables(conn):
    """Create all database tables."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS institutions (
            institution_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            state TEXT NOT NULL,
            base_overhead_rate REAL NOT NULL,
            negotiated_date TEXT NOT NULL,
            nih_approved INTEGER NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pi_profiles (
            pi_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            department TEXT NOT NULL,
            institution_id INTEGER NOT NULL,
            career_stage TEXT NOT NULL,
            h_index INTEGER NOT NULL,
            years_active INTEGER NOT NULL,
            FOREIGN KEY (institution_id) REFERENCES institutions(institution_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS grant_applications (
            app_id INTEGER PRIMARY KEY,
            pi_id INTEGER NOT NULL,
            institution_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            program_area TEXT NOT NULL,
            submission_date TEXT NOT NULL,
            total_requested REAL NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (pi_id) REFERENCES pi_profiles(pi_id),
            FOREIGN KEY (institution_id) REFERENCES institutions(institution_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expense_line_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            subcategory TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT NOT NULL,
            FOREIGN KEY (app_id) REFERENCES grant_applications(app_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historical_financial_reports (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pi_id INTEGER NOT NULL,
            grant_year INTEGER NOT NULL,
            category TEXT NOT NULL,
            budgeted_amount REAL NOT NULL,
            actual_spent REAL NOT NULL,
            FOREIGN KEY (pi_id) REFERENCES pi_profiles(pi_id)
        )
    """)

    conn.commit()


def generate_institutions(conn, n):
    """Generate institution records."""
    rows = []
    used_names = set()
    university_suffixes = [
        "University", "Institute of Technology", "State University",
        "College", "Polytechnic Institute", "Academy of Sciences"
    ]
    research_names = [
        "Research Institute", "Research Center", "Research Laboratory",
        "Science Foundation", "Innovation Hub"
    ]
    states = [
        "CA", "NY", "TX", "MA", "IL", "PA", "OH", "FL", "WA", "NC",
        "MI", "GA", "VA", "MD", "MN", "CO", "AZ", "OR", "CT", "NJ",
        "WI", "IN", "MO", "TN", "SC"
    ]

    for i in range(n):
        inst_type = INSTITUTION_TYPES[i % len(INSTITUTION_TYPES)]
        while True:
            city = fake.city()
            if inst_type == "university":
                name = f"{city} {np.random.choice(university_suffixes)}"
            elif inst_type == "research_institute":
                name = f"{city} {np.random.choice(research_names)}"
            elif inst_type == "medical_center":
                name = f"{city} Medical Center"
            elif inst_type == "national_lab":
                name = f"{city} National Laboratory"
            else:
                name = f"{city} Nonprofit Research Foundation"
            if name not in used_names:
                used_names.add(name)
                break

        # Overhead rates vary by institution type
        base_rates = {
            "university": (45.0, 65.0),
            "research_institute": (35.0, 55.0),
            "medical_center": (50.0, 70.0),
            "national_lab": (30.0, 50.0),
            "nonprofit": (20.0, 40.0),
        }
        low, high = base_rates[inst_type]
        overhead_rate = round(np.random.uniform(low, high), 1)

        year = np.random.randint(2019, 2025)
        month = np.random.randint(1, 13)
        negotiated_date = f"{year}-{month:02d}-01"
        nih_approved = int(np.random.random() < 0.7)
        state = np.random.choice(states)

        rows.append((i + 1, name, inst_type, state, overhead_rate, negotiated_date, nih_approved))

    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO institutions VALUES (?, ?, ?, ?, ?, ?, ?)", rows
    )
    conn.commit()
    return rows


def generate_pi_profiles(conn, n, institutions):
    """Generate PI profile records."""
    rows = []
    for i in range(n):
        name = fake.name()
        email = fake.email()
        department = np.random.choice(DEPARTMENTS)
        institution_id = institutions[i % len(institutions)][0]
        career_stage = np.random.choice(CAREER_STAGES, p=[0.3, 0.4, 0.3])
        if career_stage == "early":
            h_index = int(np.random.randint(2, 15))
            years_active = int(np.random.randint(1, 7))
        elif career_stage == "mid":
            h_index = int(np.random.randint(10, 35))
            years_active = int(np.random.randint(5, 16))
        else:
            h_index = int(np.random.randint(25, 70))
            years_active = int(np.random.randint(12, 35))

        rows.append((i + 1, name, email, department, institution_id, career_stage, h_index, years_active))

    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO pi_profiles VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
    )
    conn.commit()
    return rows


def generate_grant_applications(conn, n, pi_profiles, institutions):
    """Generate grant application records."""
    rows = []
    # Ensure roughly 40% are pending_review
    for i in range(n):
        pi = pi_profiles[i % len(pi_profiles)]
        pi_id = pi[0]
        institution_id = pi[4]  # institution_id from pi_profile

        title = f"Investigation of {fake.bs().title()}"
        program_area = np.random.choice(PROGRAM_AREAS)
        year = np.random.randint(2024, 2027)
        month = np.random.randint(1, 13)
        day = np.random.randint(1, 29)
        submission_date = f"{year}-{month:02d}-{day:02d}"

        # Budget between 50K and 2M
        total_requested = round(float(np.random.uniform(50000, 2000000)), 2)

        if i < int(n * 0.4):
            status = "pending_review"
        else:
            status = np.random.choice(["approved", "rejected", "under_revision"], p=[0.5, 0.3, 0.2])

        rows.append((i + 1, pi_id, institution_id, title, program_area, submission_date, total_requested, status))

    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO grant_applications VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
    )
    conn.commit()
    return rows


def generate_expense_line_items(conn, applications, min_rows):
    """Generate expense line items for each application."""
    rows = []
    item_id = 1
    for app in applications:
        app_id = app[0]
        total_requested = app[6]

        # Generate 4-7 categories per application
        num_cats = int(np.random.randint(4, 8))
        cats = list(np.random.choice(EXPENSE_CATEGORIES, size=min(num_cats, len(EXPENSE_CATEGORIES)), replace=False))

        # Distribute budget across categories with some randomness
        raw_weights = np.random.dirichlet(np.ones(len(cats)) * 2)
        amounts = (raw_weights * total_requested).tolist()

        for j, cat in enumerate(cats):
            subcats = EXPENSE_SUBCATEGORIES[cat]
            subcat = np.random.choice(subcats)
            amount = round(amounts[j], 2)
            description = f"{subcat} for {fake.catch_phrase().lower()}"
            rows.append((item_id, app_id, cat, subcat, amount, description))
            item_id += 1

    # Ensure minimum row count
    while len(rows) < min_rows:
        app = applications[len(rows) % len(applications)]
        app_id = app[0]
        cat = np.random.choice(EXPENSE_CATEGORIES)
        subcat = np.random.choice(EXPENSE_SUBCATEGORIES[cat])
        amount = round(float(np.random.uniform(1000, 50000)), 2)
        description = f"Additional {subcat} for {fake.catch_phrase().lower()}"
        rows.append((item_id, app_id, cat, subcat, amount, description))
        item_id += 1

    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO expense_line_items VALUES (?, ?, ?, ?, ?, ?)", rows
    )
    conn.commit()
    return rows


def generate_historical_reports(conn, pi_profiles, min_rows):
    """Generate historical financial report records."""
    rows = []
    report_id = 1
    for pi in pi_profiles:
        pi_id = pi[0]
        years_active = pi[7]
        # Generate 2-5 historical report entries per PI
        num_reports = int(np.random.randint(2, 6))
        for _ in range(num_reports):
            grant_year = int(np.random.randint(2018, 2026))
            cat = np.random.choice(EXPENSE_CATEGORIES)
            budgeted = round(float(np.random.uniform(10000, 500000)), 2)
            # Variance: most PIs stay close, some have large deviations
            if np.random.random() < 0.2:
                # High variance PI
                variance_pct = np.random.uniform(-0.4, 0.5)
            else:
                variance_pct = np.random.uniform(-0.15, 0.15)
            actual = round(budgeted * (1 + variance_pct), 2)
            rows.append((report_id, pi_id, grant_year, cat, budgeted, actual))
            report_id += 1

    # Ensure minimum row count
    while len(rows) < min_rows:
        pi = pi_profiles[len(rows) % len(pi_profiles)]
        pi_id = pi[0]
        grant_year = int(np.random.randint(2018, 2026))
        cat = np.random.choice(EXPENSE_CATEGORIES)
        budgeted = round(float(np.random.uniform(10000, 500000)), 2)
        variance_pct = np.random.uniform(-0.2, 0.2)
        actual = round(budgeted * (1 + variance_pct), 2)
        rows.append((report_id, pi_id, grant_year, cat, budgeted, actual))
        report_id += 1

    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO historical_financial_reports VALUES (?, ?, ?, ?, ?, ?)", rows
    )
    conn.commit()
    return rows


def generate_workspace(workspace, applications, pi_profiles, institutions, historical_reports):
    """Generate all workspace files."""
    os.makedirs(workspace, exist_ok=True)
    n_files = SCALE["num_workspace_files"]

    # --- Fixed policy/config files (not counted in SCALE) ---

    # 1. Category benchmarks (max % of total budget per category)
    benchmarks = {
        "category_benchmarks": {
            "personnel": {"max_pct": 60.0, "warning_pct": 50.0},
            "equipment": {"max_pct": 25.0, "warning_pct": 20.0},
            "travel": {"max_pct": 10.0, "warning_pct": 7.0},
            "supplies": {"max_pct": 15.0, "warning_pct": 10.0},
            "contractual": {"max_pct": 30.0, "warning_pct": 25.0},
            "other_direct": {"max_pct": 15.0, "warning_pct": 10.0},
            "indirect_costs": {"max_pct": 35.0, "warning_pct": 28.0},
        },
        "notes": "Percentages are of total requested budget. Exceeding max_pct triggers a flag."
    }
    with open(os.path.join(workspace, "category_benchmarks.yaml"), "w") as f:
        yaml.dump(benchmarks, f, default_flow_style=False, sort_keys=False)

    # 2. Risk scoring configuration
    risk_config = {
        "risk_weights": {
            "category_benchmark_flags": 30,
            "pub_funding_ratio": 25,
            "historical_variance": 25,
            "overhead_compliance": 20
        },
        "pub_funding_ratio": {
            "description": "Ratio of total_publications to total_funding_received (per $100K). Low ratio suggests limited output relative to funding.",
            "low_threshold": 1.5,
            "critical_threshold": 0.8
        },
        "historical_variance": {
            "description": "Average absolute percentage deviation between budgeted and actual spending across all historical reports.",
            "warning_pct": 15.0,
            "critical_pct": 25.0
        },
        "risk_tiers": {
            "Low": {"min_score": 0, "max_score": 25},
            "Medium": {"min_score": 25, "max_score": 50},
            "High": {"min_score": 50, "max_score": 75},
            "Critical": {"min_score": 75, "max_score": 100}
        },
        "scoring_rules": {
            "category_flags": "Each category exceeding max_pct adds (30 / total_categories_in_budget) points to the category_benchmark_flags component. Cap at 30.",
            "pub_funding": "If ratio < critical_threshold: full 25 points. If ratio < low_threshold: 12.5 points. Otherwise: 0 points.",
            "historical": "If avg_variance > critical_pct: full 25 points. If avg_variance > warning_pct: 12.5 points. Otherwise: 0 points.",
            "overhead": "If institution overhead_rate > approved_max for its type: full 20 points. Otherwise: 0 points."
        }
    }
    with open(os.path.join(workspace, "risk_scoring_config.json"), "w") as f:
        json.dump(risk_config, f, indent=2)

    # 3. Overhead rate tiers (approved max rates by institution type)
    overhead_tiers = [
        {"institution_type": "university", "approved_max_rate": 58.0, "federal_cap": 65.0},
        {"institution_type": "research_institute", "approved_max_rate": 48.0, "federal_cap": 55.0},
        {"institution_type": "medical_center", "approved_max_rate": 62.0, "federal_cap": 70.0},
        {"institution_type": "national_lab", "approved_max_rate": 42.0, "federal_cap": 50.0},
        {"institution_type": "nonprofit", "approved_max_rate": 32.0, "federal_cap": 40.0},
    ]
    with open(os.path.join(workspace, "overhead_rate_tiers.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["institution_type", "approved_max_rate", "federal_cap"])
        writer.writeheader()
        writer.writerows(overhead_tiers)

    # 4. Review guidelines
    guidelines = """Grant Risk Assessment Review Guidelines

Applications must be evaluated across four risk dimensions. Each pending application
requires a complete assessment before panel review.

For the publication-to-funding ratio, compute the value as the PI's total number of
publications divided by their total funding received expressed in units of one hundred
thousand dollars. For instance, a PI with 30 publications and $1,500,000 in total
funding has a ratio of 30 / 15.0 = 2.0.

Historical spending variance should be computed as the mean of the absolute percentage
deviations across all historical financial report entries for the PI. For each entry
the deviation is abs(actual_spent - budgeted_amount) / budgeted_amount * 100.

When multiple expense line items share the same category within a single application,
sum their amounts before computing the category percentage of the total requested budget.

Applications are sorted in the final report by risk_score descending; ties are broken
by app_id ascending.
"""
    with open(os.path.join(workspace, "review_guidelines.md"), "w") as f:
        f.write(guidelines)

    # --- Scalable data files (counted in SCALE["num_workspace_files"]) ---
    # PI funding history files - contain publication and funding data
    # This is the ONLY source for publication counts and total funding received
    pi_funding_dir = os.path.join(workspace, "pi_funding_records")
    os.makedirs(pi_funding_dir, exist_ok=True)

    pis_per_file = max(1, len(pi_profiles) // n_files)
    file_idx = 0
    for batch_start in range(0, len(pi_profiles), pis_per_file):
        if file_idx >= n_files:
            # Last file gets remaining PIs
            batch_start_actual = (n_files - 1) * pis_per_file
            break
        batch = pi_profiles[batch_start:batch_start + pis_per_file]
        records = []
        for pi in batch:
            pi_id = pi[0]
            h_index = pi[6]
            years_active = pi[7]
            career_stage = pi[5]

            # Generate publication count correlated with h_index
            total_publications = int(h_index * np.random.uniform(1.2, 3.0))

            # Generate funding received correlated with career stage
            if career_stage == "early":
                total_funding = round(float(np.random.uniform(50000, 500000)), 2)
            elif career_stage == "mid":
                total_funding = round(float(np.random.uniform(300000, 2000000)), 2)
            else:
                total_funding = round(float(np.random.uniform(1000000, 5000000)), 2)

            grants_awarded = int(np.random.randint(1, years_active + 1))
            avg_grant_size = round(total_funding / grants_awarded, 2)

            records.append({
                "pi_id": int(pi_id),
                "total_publications": int(total_publications),
                "total_citations": int(total_publications * np.random.uniform(5, 30)),
                "grants_awarded": int(grants_awarded),
                "total_funding_received": total_funding,
                "avg_grant_size": avg_grant_size,
            })

        file_num = file_idx + 1
        with open(os.path.join(pi_funding_dir, f"batch_{file_num:03d}.json"), "w") as f:
            json.dump(records, f, indent=2)
        file_idx += 1

    # Handle any remaining PIs in the last file
    if file_idx < n_files:
        # Generate additional empty batch files to meet the count
        while file_idx < n_files:
            file_num = file_idx + 1
            with open(os.path.join(pi_funding_dir, f"batch_{file_num:03d}.json"), "w") as f:
                json.dump([], f, indent=2)
            file_idx += 1
    elif len(pi_profiles) > n_files * pis_per_file:
        # Append remaining PIs to last file
        last_file = os.path.join(pi_funding_dir, f"batch_{n_files:03d}.json")
        with open(last_file, "r") as f:
            existing = json.load(f)
        remaining = pi_profiles[n_files * pis_per_file:]
        for pi in remaining:
            pi_id = pi[0]
            h_index = pi[6]
            years_active = pi[7]
            career_stage = pi[5]
            total_publications = int(h_index * np.random.uniform(1.2, 3.0))
            if career_stage == "early":
                total_funding = round(float(np.random.uniform(50000, 500000)), 2)
            elif career_stage == "mid":
                total_funding = round(float(np.random.uniform(300000, 2000000)), 2)
            else:
                total_funding = round(float(np.random.uniform(1000000, 5000000)), 2)
            grants_awarded = int(np.random.randint(1, years_active + 1))
            avg_grant_size = round(total_funding / grants_awarded, 2)
            existing.append({
                "pi_id": int(pi_id),
                "total_publications": int(total_publications),
                "total_citations": int(total_publications * np.random.uniform(5, 30)),
                "grants_awarded": int(grants_awarded),
                "total_funding_received": total_funding,
                "avg_grant_size": avg_grant_size,
            })
        with open(last_file, "w") as f:
            json.dump(existing, f, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # Remove existing DB
    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n = SCALE["rows_per_table"]

    institutions = generate_institutions(conn, n)
    pi_profiles = generate_pi_profiles(conn, n, institutions)
    applications = generate_grant_applications(conn, n, pi_profiles, institutions)
    expense_items = generate_expense_line_items(conn, applications, n)
    historical_reports = generate_historical_reports(conn, pi_profiles, n)

    conn.close()

    generate_workspace(args.workspace, applications, pi_profiles, institutions, historical_reports)

    # Print summary
    conn = sqlite3.connect(args.db_path)
    cursor = conn.cursor()
    for table in ["institutions", "pi_profiles", "grant_applications", "expense_line_items", "historical_financial_reports"]:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"{table}: {cursor.fetchone()[0]} rows")
    cursor.execute("SELECT COUNT(*) FROM grant_applications WHERE status='pending_review'")
    print(f"Pending review applications: {cursor.fetchone()[0]}")
    conn.close()

    # Count workspace files
    ws_files = []
    for root, dirs, files in os.walk(args.workspace):
        for f in files:
            ws_files.append(os.path.join(root, f))
    print(f"Workspace files: {len(ws_files)}")


if __name__ == "__main__":
    main()
