"""Data generation for recruitment agency vendor performance evaluation task."""
import argparse
import sqlite3
import os
import json
import csv
import random
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

try:
    import yaml
except ImportError:
    import json as yaml  # fallback; we write yaml manually below

SCALE = {
    "rows_per_table": 50,
    "num_workspace_files": 10,
}


DEPARTMENTS = [
    "Engineering", "Sales", "Marketing", "Finance", "Operations",
    "Human Resources", "Legal", "Product", "Data Science", "Customer Support",
]

ROLES_BY_DEPT = {
    "Engineering": ["Software Engineer", "Senior Software Engineer", "DevOps Engineer",
                    "QA Engineer", "Tech Lead", "Backend Developer", "Frontend Developer"],
    "Sales": ["Account Executive", "Sales Manager", "Business Development Rep",
              "Sales Director", "Regional Sales Lead"],
    "Marketing": ["Marketing Manager", "Content Strategist", "Digital Marketing Specialist",
                  "Brand Manager", "SEO Analyst"],
    "Finance": ["Financial Analyst", "Senior Accountant", "FP&A Manager",
                "Controller", "Accounts Payable Specialist"],
    "Operations": ["Operations Manager", "Supply Chain Analyst", "Process Improvement Lead",
                   "Facilities Manager", "Logistics Coordinator"],
    "Human Resources": ["HR Business Partner", "Recruiter", "Compensation Analyst",
                        "HR Director", "Benefits Administrator"],
    "Legal": ["Corporate Counsel", "Paralegal", "Compliance Officer",
              "Legal Operations Manager", "Contract Specialist"],
    "Product": ["Product Manager", "Senior Product Manager", "Product Analyst",
                "UX Researcher", "Product Designer"],
    "Data Science": ["Data Scientist", "ML Engineer", "Data Analyst",
                     "Analytics Manager", "Data Engineer"],
    "Customer Support": ["Support Manager", "Customer Success Manager",
                         "Technical Support Lead", "Support Analyst", "CX Specialist"],
}

SPECIALTIES = [
    "Technology", "Finance & Accounting", "Healthcare", "General Staffing",
    "Executive Search", "Sales & Marketing", "Engineering & Manufacturing",
    "Legal & Compliance",
]

REGIONS = ["Northeast", "Southeast", "Midwest", "West Coast", "Southwest"]

EDUCATION_LEVELS = ["High School", "Associate's", "Bachelor's", "Master's", "PhD"]
EDUCATION_WEIGHTS = [5, 10, 45, 30, 10]

AGENCY_SUFFIXES = [
    "Staffing", "Recruiting", "Talent Solutions", "Personnel",
    "Search Group", "HR Solutions", "Talent Partners", "Workforce Solutions",
    "Recruitment Services", "Staffing Partners",
]

DEPARTURE_REASONS = [
    "Voluntary - Better Opportunity", "Voluntary - Relocation",
    "Voluntary - Career Change", "Involuntary - Performance",
    "Involuntary - Restructuring", "Voluntary - Personal Reasons",
    "Voluntary - Return to School", "Involuntary - Position Eliminated",
]


def generate_agencies(fake, n_agencies):
    """Generate agency records."""
    agencies = []
    used_names = set()
    for i in range(1, n_agencies + 1):
        while True:
            base = fake.company()
            suffix = random.choice(AGENCY_SUFFIXES)
            name = f"{base} {suffix}"
            if name not in used_names:
                used_names.add(name)
                break
        agencies.append((
            i,
            name,
            random.choice(SPECIALTIES),
            random.choice(REGIONS),
            random.randint(1985, 2020),
            round(random.uniform(8.0, 25.0), 1),
        ))
    return agencies


def generate_candidates(fake, n_candidates, n_agencies, date_start, date_end):
    """Generate candidate records with status assignment."""
    # Ensure each agency gets at least 3 candidates
    agency_assignments = []
    for aid in range(1, n_agencies + 1):
        agency_assignments.extend([aid] * 3)
    remaining = n_candidates - len(agency_assignments)
    if remaining > 0:
        agency_assignments.extend(random.choices(range(1, n_agencies + 1), k=remaining))
    random.shuffle(agency_assignments)

    date_range_days = (date_end - date_start).days

    statuses = np.random.choice(
        ["rejected_screening", "rejected_interview", "offer_declined", "hired"],
        size=n_candidates,
        p=[0.12, 0.30, 0.05, 0.53],
    )

    candidates = []
    for i in range(n_candidates):
        cid = i + 1
        aid = agency_assignments[i]
        dept = random.choice(DEPARTMENTS)
        role = random.choice(ROLES_BY_DEPT[dept])
        sub_date = date_start + timedelta(days=random.randint(0, date_range_days))
        exp = random.randint(0, 25)
        edu = random.choices(EDUCATION_LEVELS, weights=EDUCATION_WEIGHTS, k=1)[0]
        candidates.append((
            cid, aid, fake.name(), role, dept,
            sub_date.strftime("%Y-%m-%d"), exp, edu, statuses[i],
        ))
    return candidates


def generate_interviews(candidates, date_start):
    """Generate interview records based on candidate status."""
    interviews = []
    iid = 1
    for cand in candidates:
        cid, aid, name, role, dept, sub_date_str, exp, edu, status = cand
        if status == "rejected_screening":
            continue

        sub_dt = datetime.strptime(sub_date_str, "%Y-%m-%d")

        if status == "rejected_interview":
            n_rounds = random.randint(1, 2)
        else:
            n_rounds = random.randint(2, 3)

        for r in range(1, n_rounds + 1):
            int_date = sub_dt + timedelta(days=7 * r + random.randint(0, 5))
            if status == "rejected_interview" and r == n_rounds:
                score = round(random.uniform(2.0, 5.5), 1)
                passed = 0
            else:
                score = round(random.uniform(5.0, 10.0), 1)
                passed = 1

            interviews.append((
                iid, cid, r, int_date.strftime("%Y-%m-%d"), score, passed,
            ))
            iid += 1

    return interviews


def generate_hires(candidates, interviews):
    """Generate hire records for candidates with 'hired' status."""
    # Build interview lookup
    interviews_by_cand = {}
    for iv in interviews:
        iid, cid, rnd, dt_str, score, passed = iv
        interviews_by_cand.setdefault(cid, []).append(iv)

    hires = []
    hid = 1
    for cand in candidates:
        cid, aid, name, role, dept, sub_date_str, exp, edu, status = cand
        if status != "hired":
            continue

        sub_dt = datetime.strptime(sub_date_str, "%Y-%m-%d")
        cand_ivs = interviews_by_cand.get(cid, [])
        if cand_ivs:
            last_iv_date = max(datetime.strptime(iv[3], "%Y-%m-%d") for iv in cand_ivs)
        else:
            last_iv_date = sub_dt + timedelta(days=14)

        offer_date = last_iv_date + timedelta(days=random.randint(2, 10))
        start_date = offer_date + timedelta(days=random.randint(14, 45))

        salary = round(random.uniform(45000, 180000), 2)

        # Retention: reference date 2025-10-01
        ref_date = datetime(2025, 10, 1)
        max_months = max(1, int((ref_date - start_date).days / 30))

        is_active = int(random.random() < 0.65)
        if is_active:
            months_retained = max_months
            departure_reason = None
        else:
            months_retained = random.randint(1, max(1, max_months - 1))
            departure_reason = random.choice(DEPARTURE_REASONS)

        hires.append((
            hid, cid, offer_date.strftime("%Y-%m-%d"),
            start_date.strftime("%Y-%m-%d"), salary,
            is_active, months_retained, departure_reason,
        ))
        hid += 1

    return hires


def generate_workspace(conn, workspace, n_files, agencies, candidates, hires):
    """Generate all workspace files."""
    agency_dict = {a[0]: a[1] for a in agencies}
    agency_fees = {a[0]: a[5] for a in agencies}
    n_agencies = len(agencies)

    # --- Scalable files: monthly spend CSVs ---
    # Compute per-agency retainer (deterministic from agency_id)
    retainers = {}
    for aid in range(1, n_agencies + 1):
        retainers[aid] = round(2000 + ((aid * 7919) % 11000), 2)

    # Build hire start-month lookup
    cand_agency = {c[0]: c[1] for c in candidates}
    hire_by_month = {}
    for h in hires:
        hid, cid, offer_d, start_d, salary, is_act, mr, dr = h
        month_key = start_d[:7]  # "YYYY-MM"
        hire_by_month.setdefault(month_key, []).append((cid, salary))

    date_start = datetime(2023, 1, 1)
    months = pd.period_range(start="2023-01", periods=n_files, freq="M")

    for month in months:
        month_str = str(month)  # "2023-01"
        month_hires = hire_by_month.get(month_str, [])

        rows = []
        for aid in range(1, n_agencies + 1):
            placement_fee = 0.0
            for cid, salary in month_hires:
                if cand_agency.get(cid) == aid:
                    placement_fee += salary * agency_fees[aid] / 100.0

            retainer = retainers[aid]
            total = round(retainer + placement_fee, 2)
            rows.append({
                "agency_id": aid,
                "agency_name": agency_dict[aid],
                "month": month_str,
                "retainer_fee": round(retainer, 2),
                "placement_fee": round(placement_fee, 2),
                "total_spend": total,
            })

        filepath = os.path.join(workspace, f"monthly_spend_{month_str}.csv")
        pd.DataFrame(rows).to_csv(filepath, index=False)

    # --- Fixed files ---

    # 1. scoring_config.yaml
    scoring_config = {
        "metric_weights": {
            "conversion_rate": 0.20,
            "avg_time_to_fill_days": 0.20,
            "retention_rate": 0.25,
            "cost_per_hire": 0.20,
            "avg_quality_score": 0.15,
        },
        "normalization": {
            "conversion_rate": {"min": 0.0, "max": 1.0, "higher_is_better": True},
            "avg_time_to_fill_days": {"min": 15, "max": 120, "higher_is_better": False},
            "retention_rate": {"min": 0.0, "max": 1.0, "higher_is_better": True},
            "cost_per_hire": {"min": 5000, "max": 80000, "higher_is_better": False},
            "avg_quality_score": {"min": 1.0, "max": 10.0, "higher_is_better": True},
        },
        "retention_threshold_months": 6,
        "zero_hire_defaults": {
            "avg_time_to_fill_days": 120,
            "cost_per_hire": 80000,
            "avg_quality_score": 1.0,
            "retention_rate": 0.0,
        },
    }
    # Write YAML manually to avoid import dependency issues
    yaml_lines = []
    yaml_lines.append("metric_weights:")
    for k, v in scoring_config["metric_weights"].items():
        yaml_lines.append(f"  {k}: {v}")
    yaml_lines.append("")
    yaml_lines.append("normalization:")
    for metric, params in scoring_config["normalization"].items():
        yaml_lines.append(f"  {metric}:")
        yaml_lines.append(f"    min: {params['min']}")
        yaml_lines.append(f"    max: {params['max']}")
        yaml_lines.append(f"    higher_is_better: {'true' if params['higher_is_better'] else 'false'}")
    yaml_lines.append("")
    yaml_lines.append(f"retention_threshold_months: {scoring_config['retention_threshold_months']}")
    yaml_lines.append("")
    yaml_lines.append("zero_hire_defaults:")
    for k, v in scoring_config["zero_hire_defaults"].items():
        yaml_lines.append(f"  {k}: {v}")
    yaml_lines.append("")

    with open(os.path.join(workspace, "scoring_config.yaml"), "w") as f:
        f.write("\n".join(yaml_lines))

    # 2. performance_tiers.json
    tiers = {
        "tiers": [
            {"name": "Platinum", "min_score": 0.85},
            {"name": "Gold", "min_score": 0.70},
            {"name": "Silver", "min_score": 0.50},
            {"name": "Bronze", "min_score": 0.0},
        ],
        "assignment_rule": "Assign the highest tier whose min_score the agency overall_score meets or exceeds.",
    }
    with open(os.path.join(workspace, "performance_tiers.json"), "w") as f:
        json.dump(tiers, f, indent=2)

    # 3. renewal_rules.md
    renewal_rules = (
        "## Vendor Renewal Decision Framework\n\n"
        "Apply the following rules in order to determine the renewal recommendation "
        "for each agency based on their assigned performance tier and individual metrics.\n\n"
        "- Platinum tier agencies receive \"Strongly Recommend Renewal\".\n"
        "- Gold tier agencies with a retention_rate at or above 0.50 receive \"Recommend Renewal\".\n"
        "- Gold tier agencies with a retention_rate below 0.50 receive \"Conditional Renewal\".\n"
        "- Silver tier agencies with a conversion_rate at or above 0.15 and a retention_rate "
        "at or above 0.40 receive \"Conditional Renewal\".\n"
        "- Silver tier agencies that do not meet both conditions above receive \"Review Required\".\n"
        "- Bronze tier agencies with at least one hire and a conversion_rate at or above 0.10 "
        "receive \"Review Required\".\n"
        "- All other Bronze tier agencies receive \"Do Not Renew\".\n"
    )
    with open(os.path.join(workspace, "renewal_rules.md"), "w") as f:
        f.write(renewal_rules)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    n = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    n_agencies = n
    n_candidates = n * 5

    os.makedirs(args.workspace, exist_ok=True)
    conn = sqlite3.connect(args.db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS agencies (
            agency_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            specialty TEXT NOT NULL,
            region TEXT NOT NULL,
            founded_year INTEGER NOT NULL,
            fee_rate_pct REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS candidates (
            candidate_id INTEGER PRIMARY KEY,
            agency_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            role_title TEXT NOT NULL,
            department TEXT NOT NULL,
            submission_date TEXT NOT NULL,
            experience_years INTEGER NOT NULL,
            education_level TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (agency_id) REFERENCES agencies(agency_id)
        );
        CREATE TABLE IF NOT EXISTS interviews (
            interview_id INTEGER PRIMARY KEY,
            candidate_id INTEGER NOT NULL,
            round_number INTEGER NOT NULL,
            interview_date TEXT NOT NULL,
            score REAL NOT NULL,
            passed INTEGER NOT NULL,
            FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id)
        );
        CREATE TABLE IF NOT EXISTS hires (
            hire_id INTEGER PRIMARY KEY,
            candidate_id INTEGER NOT NULL,
            offer_date TEXT NOT NULL,
            start_date TEXT NOT NULL,
            annual_salary REAL NOT NULL,
            is_active INTEGER NOT NULL,
            months_retained INTEGER NOT NULL,
            departure_reason TEXT,
            FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id)
        );
    """)

    # Date range: n_files months starting Jan 2023
    date_start = datetime(2023, 1, 1)
    date_end = date_start + timedelta(days=30 * n_files)

    agencies = generate_agencies(fake, n_agencies)
    cur.executemany("INSERT INTO agencies VALUES (?,?,?,?,?,?)", agencies)

    candidates = generate_candidates(fake, n_candidates, n_agencies, date_start, date_end)
    cur.executemany("INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?)", candidates)

    interviews = generate_interviews(candidates, date_start)
    cur.executemany("INSERT INTO interviews VALUES (?,?,?,?,?,?)", interviews)

    hires = generate_hires(candidates, interviews)
    cur.executemany("INSERT INTO hires VALUES (?,?,?,?,?,?,?,?)", hires)

    # Verify minimum row counts
    for table in ["agencies", "candidates", "interviews", "hires"]:
        count = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count >= SCALE["rows_per_table"], (
            f"{table} has {count} rows, need >= {SCALE['rows_per_table']}"
        )

    conn.commit()

    generate_workspace(conn, args.workspace, n_files, agencies, candidates, hires)

    conn.close()

    # Summary
    print(f"Database: {args.db_path}")
    print(f"  agencies:   {len(agencies)}")
    print(f"  candidates: {len(candidates)}")
    print(f"  interviews: {len(interviews)}")
    print(f"  hires:      {len(hires)}")
    print(f"Workspace: {args.workspace}")
    print(f"  monthly spend files: {n_files}")
    print(f"  fixed config files:  3")


if __name__ == "__main__":
    main()
