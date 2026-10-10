"""
Data generation script for Recruitment Channel ROI Optimization task.
Generates a SQLite database and workspace files for evaluating recruitment
channel effectiveness and producing budget allocation plans.
"""

import argparse
import os
import sqlite3
import json
import csv
import random
import math

import numpy as np
import pandas as pd
from faker import Faker
import yaml

# ────────────────────────────────────────────
# SCALE — only this block differs across v0…v3
# ────────────────────────────────────────────
SCALE = {
    "rows_per_table": 400,       # v2 = 4x base
    "num_workspace_files": 30,   # v2 = base + 2N (N=10)
}

# ────────────────────────────────────────────
# Fixed reference data
# ────────────────────────────────────────────
SOURCES = [
    {"source_id": 1, "name": "LinkedIn",           "type": "job_board"},
    {"source_id": 2, "name": "Indeed",              "type": "job_board"},
    {"source_id": 3, "name": "Glassdoor",           "type": "job_board"},
    {"source_id": 4, "name": "Employee Referrals",  "type": "referral"},
    {"source_id": 5, "name": "Apex Staffing",       "type": "agency"},
]

DEPARTMENTS = [
    {"dept_id": 1, "name": "Engineering"},
    {"dept_id": 2, "name": "Sales"},
    {"dept_id": 3, "name": "Marketing"},
    {"dept_id": 4, "name": "Operations"},
]

QUARTERS = ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"]

# (source_id, dept_id) -> (hire_rate, mean_days_to_hire, retention_12m_rate, perf_mean)
SOURCE_DEPT_PARAMS = {
    (1, 1): (0.72, 32, 0.87, 3.9), (1, 2): (0.60, 25, 0.74, 3.4),
    (1, 3): (0.65, 27, 0.80, 3.6), (1, 4): (0.58, 34, 0.70, 3.2),
    (2, 1): (0.55, 38, 0.72, 3.3), (2, 2): (0.68, 22, 0.78, 3.5),
    (2, 3): (0.62, 26, 0.75, 3.4), (2, 4): (0.70, 20, 0.82, 3.7),
    (3, 1): (0.64, 34, 0.83, 3.7), (3, 2): (0.58, 28, 0.73, 3.3),
    (3, 3): (0.70, 24, 0.85, 3.8), (3, 4): (0.60, 30, 0.76, 3.4),
    (4, 1): (0.82, 20, 0.93, 4.2), (4, 2): (0.78, 17, 0.89, 4.0),
    (4, 3): (0.76, 18, 0.91, 4.1), (4, 4): (0.80, 16, 0.92, 4.1),
    (5, 1): (0.66, 24, 0.79, 3.5), (5, 2): (0.62, 26, 0.73, 3.3),
    (5, 3): (0.60, 28, 0.75, 3.4), (5, 4): (0.68, 22, 0.81, 3.6),
}

COST_PARAMS = {
    "job_board":  {"recruiter_hours_mean": 8,  "interview_hours_mean": 6, "admin_mean": 350},
    "referral":   {"recruiter_hours_mean": 4,  "interview_hours_mean": 5, "admin_mean": 250},
    "agency":     {"recruiter_hours_mean": 3,  "interview_hours_mean": 6, "admin_mean": 200},
}
HOURLY_RATES = {"recruiter": 75, "interview_panel": 120}

ROLE_TITLES = {
    1: ["Software Engineer", "Backend Developer", "Data Engineer", "DevOps Engineer",
        "Frontend Developer", "ML Engineer", "QA Engineer", "Platform Engineer"],
    2: ["Account Executive", "Sales Representative", "Business Development Rep",
        "Sales Manager", "Enterprise Account Mgr", "Sales Engineer"],
    3: ["Marketing Analyst", "Content Strategist", "Growth Manager",
        "Brand Manager", "Digital Marketing Specialist", "SEO Analyst"],
    4: ["Operations Analyst", "Supply Chain Coordinator", "Project Manager",
        "Operations Manager", "Logistics Specialist", "Process Engineer"],
}

EXIT_REASONS = ["better_offer", "relocation", "performance", "cultural_fit",
                "career_change", "layoff", "personal"]


def seed_all(seed=42):
    random.seed(seed)
    np.random.seed(seed)


def create_tables(conn):
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            source_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS departments (
            dept_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS candidates (
            candidate_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            dept_id INTEGER NOT NULL,
            role_title TEXT NOT NULL,
            applied_date TEXT NOT NULL,
            hired_date TEXT,
            status TEXT NOT NULL,
            quarter TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(source_id),
            FOREIGN KEY (dept_id) REFERENCES departments(dept_id)
        );
        CREATE TABLE IF NOT EXISTS hiring_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            event_date TEXT NOT NULL,
            FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id)
        );
        CREATE TABLE IF NOT EXISTS hiring_costs (
            candidate_id INTEGER PRIMARY KEY,
            recruiter_hours REAL NOT NULL,
            interview_hours REAL NOT NULL,
            admin_cost REAL NOT NULL,
            total_internal_cost REAL NOT NULL,
            FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id)
        );
        CREATE TABLE IF NOT EXISTS retention (
            candidate_id INTEGER PRIMARY KEY,
            months_employed INTEGER NOT NULL,
            is_active_at_12m INTEGER NOT NULL,
            performance_rating REAL,
            exit_reason TEXT,
            FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id)
        );
    """)
    conn.commit()


def insert_reference_data(conn):
    c = conn.cursor()
    for s in SOURCES:
        c.execute("INSERT INTO sources VALUES (?,?,?)",
                  (s["source_id"], s["name"], s["type"]))
    for d in DEPARTMENTS:
        c.execute("INSERT INTO departments VALUES (?,?)",
                  (d["dept_id"], d["name"]))
    conn.commit()


def _source_name(sid):
    return next(s["name"] for s in SOURCES if s["source_id"] == sid)


def _dept_name(did):
    return next(d["name"] for d in DEPARTMENTS if d["dept_id"] == did)


def generate_candidates(conn, fake, rows_per_table):
    """Generate candidates and all associated records."""
    num_candidates = rows_per_table * 2  # ensures downstream tables >= rows_per_table
    c = conn.cursor()

    combos = [(s["source_id"], d["dept_id"]) for s in SOURCES for d in DEPARTMENTS]
    base_per_combo = num_candidates // len(combos)
    remainder = num_candidates % len(combos)

    candidate_id = 0
    all_candidates = []
    hired_candidates = []

    for idx, (src_id, dept_id) in enumerate(combos):
        n = base_per_combo + (1 if idx < remainder else 0)
        hire_rate, mean_days, ret_rate, perf_mean = SOURCE_DEPT_PARAMS[(src_id, dept_id)]
        source_type = next(s["type"] for s in SOURCES if s["source_id"] == src_id)

        for _ in range(n):
            candidate_id += 1
            name = fake.name()
            email = fake.email()
            quarter = random.choice(QUARTERS)
            q_num = int(quarter.split("-Q")[1])
            month_start = (q_num - 1) * 3 + 1
            applied_date = fake.date_between_dates(
                date_start=pd.Timestamp(f"2025-{month_start:02d}-01"),
                date_end=pd.Timestamp(f"2025-{month_start + 2:02d}-28"),
            )
            role_title = random.choice(ROLE_TITLES[dept_id])
            is_hired = random.random() < hire_rate
            status = "hired" if is_hired else random.choice(["rejected", "withdrawn"])
            days_to_hire = max(7, int(np.random.normal(mean_days, mean_days * 0.25)))
            hired_date = (
                (applied_date + pd.Timedelta(days=days_to_hire)).strftime("%Y-%m-%d")
                if is_hired else None
            )

            c.execute(
                "INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?,?)",
                (candidate_id, name, email, src_id, dept_id, role_title,
                 applied_date.strftime("%Y-%m-%d"), hired_date, status, quarter),
            )

            # Hiring events
            events = [("application_received", applied_date.strftime("%Y-%m-%d"))]
            screen_date = applied_date + pd.Timedelta(days=random.randint(1, 5))
            events.append(("screening", screen_date.strftime("%Y-%m-%d")))
            if status != "withdrawn" or random.random() < 0.5:
                interview_date = screen_date + pd.Timedelta(days=random.randint(3, 10))
                events.append(("interview", interview_date.strftime("%Y-%m-%d")))
                if is_hired:
                    offer_date = interview_date + pd.Timedelta(days=random.randint(2, 7))
                    events.append(("offer_extended", offer_date.strftime("%Y-%m-%d")))
                    events.append(("hired", hired_date))
                else:
                    events.append((
                        status,
                        (interview_date + pd.Timedelta(days=random.randint(1, 5))).strftime("%Y-%m-%d"),
                    ))
            for etype, edate in events:
                c.execute(
                    "INSERT INTO hiring_events (candidate_id, event_type, event_date) VALUES (?,?,?)",
                    (candidate_id, etype, edate),
                )

            # Hiring costs
            cp = COST_PARAMS[source_type]
            rec_h = max(1.0, np.random.normal(cp["recruiter_hours_mean"], 2))
            int_h = max(1.0, np.random.normal(cp["interview_hours_mean"], 1.5)) if (is_hired or status == "rejected") else 0
            admin = max(50.0, np.random.normal(cp["admin_mean"], 80))
            total_internal = round(
                rec_h * HOURLY_RATES["recruiter"]
                + int_h * HOURLY_RATES["interview_panel"]
                + admin, 2,
            )
            c.execute(
                "INSERT INTO hiring_costs VALUES (?,?,?,?,?)",
                (candidate_id, round(rec_h, 2), round(int_h, 2), round(admin, 2), total_internal),
            )

            rec = {
                "candidate_id": candidate_id,
                "name": name,
                "source_id": src_id,
                "source_name": _source_name(src_id),
                "dept_id": dept_id,
                "department": _dept_name(dept_id),
                "quarter": quarter,
                "status": status,
                "hired_date": hired_date,
                "role_title": role_title,
                "applied_date": applied_date.strftime("%Y-%m-%d"),
                "days_to_hire": days_to_hire if is_hired else None,
                "total_internal_cost": total_internal,
            }
            all_candidates.append(rec)

            if is_hired:
                is_active = random.random() < ret_rate
                months = 12 if is_active else random.randint(1, 11)
                perf = round(min(5.0, max(1.0, np.random.normal(perf_mean, 0.6))), 2)
                exit_reason = None if is_active else random.choice(EXIT_REASONS)
                c.execute(
                    "INSERT INTO retention VALUES (?,?,?,?,?)",
                    (candidate_id, months, 1 if is_active else 0, perf, exit_reason),
                )
                rec["months_employed"] = months
                rec["is_active_at_12m"] = is_active
                rec["performance_rating"] = perf
                hired_candidates.append(rec)

    conn.commit()
    return all_candidates, hired_candidates


# ────────────────────────────────────────────
# Workspace file generation
# ────────────────────────────────────────────

def generate_workspace_files(workspace, all_candidates, hired_candidates, num_workspace_files):
    os.makedirs(workspace, exist_ok=True)

    n_csv = max(1, round(num_workspace_files * 0.4))
    n_json = max(1, round(num_workspace_files * 0.3))
    n_yaml = num_workspace_files - n_csv - n_json
    if n_yaml < 1:
        n_yaml = 1
        n_csv = num_workspace_files - n_json - n_yaml

    interviewed = [c for c in all_candidates if c["status"] in ("hired", "rejected")]
    random.shuffle(interviewed)
    _write_interview_csvs(workspace, interviewed, n_csv)

    random.shuffle(hired_candidates)
    _write_manager_reviews(workspace, hired_candidates, n_json)
    _write_onboarding_yamls(workspace, hired_candidates, n_yaml)

    # Fixed config files
    _write_channel_pricing(workspace)
    _write_kpi_formula(workspace)
    _write_budget_rules(workspace)
    _write_quarterly_targets(workspace)


def _split_into_batches(items, n_batches):
    k, m = divmod(len(items), n_batches)
    batches, idx = [], 0
    for i in range(n_batches):
        size = k + (1 if i < m else 0)
        batches.append(items[idx:idx + size])
        idx += size
    return batches


def _write_interview_csvs(workspace, candidates, n_files):
    batches = _split_into_batches(candidates, n_files)
    for i, batch in enumerate(batches, 1):
        rows = []
        for c in batch:
            base = SOURCE_DEPT_PARAMS[(c["source_id"], c["dept_id"])][3]
            rows.append({
                "candidate_id": c["candidate_id"],
                "source_name": c["source_name"],
                "department": c["department"],
                "technical_score": round(min(5.0, max(1.0, np.random.normal(base, 0.7))), 2),
                "behavioral_score": round(min(5.0, max(1.0, np.random.normal(base - 0.1, 0.6))), 2),
                "cultural_fit_score": round(min(5.0, max(1.0, np.random.normal(base + 0.1, 0.5))), 2),
            })
        pd.DataFrame(rows).to_csv(
            os.path.join(workspace, f"interview_scores_{i:02d}.csv"), index=False,
        )


def _write_manager_reviews(workspace, hired_candidates, n_files):
    batches = _split_into_batches(hired_candidates, n_files)
    for i, batch in enumerate(batches, 1):
        reviews = []
        for c in batch:
            base = SOURCE_DEPT_PARAMS[(c["source_id"], c["dept_id"])][3]
            reviews.append({
                "candidate_id": c["candidate_id"],
                "source_name": c["source_name"],
                "department": c["department"],
                "manager_satisfaction": round(min(5.0, max(1.0, np.random.normal(base + 0.05, 0.5))), 2),
                "teamwork_rating": round(min(5.0, max(1.0, np.random.normal(base, 0.6))), 2),
                "productivity_rating": round(min(5.0, max(1.0, np.random.normal(base - 0.05, 0.55))), 2),
            })
        with open(os.path.join(workspace, f"manager_reviews_{i:02d}.json"), "w") as f:
            json.dump(reviews, f, indent=2)


def _write_onboarding_yamls(workspace, hired_candidates, n_files):
    batches = _split_into_batches(hired_candidates, n_files)
    for i, batch in enumerate(batches, 1):
        records = []
        for c in batch:
            base_pct = 60 + SOURCE_DEPT_PARAMS[(c["source_id"], c["dept_id"])][3] * 8
            records.append({
                "candidate_id": c["candidate_id"],
                "source_name": c["source_name"],
                "department": c["department"],
                "completion_pct": round(min(100.0, max(20.0, np.random.normal(base_pct, 10))), 1),
                "assessment_score": round(min(100.0, max(10.0, np.random.normal(base_pct + 5, 12))), 1),
                "weeks_to_full_productivity": max(
                    1, int(np.random.normal(12 - SOURCE_DEPT_PARAMS[(c["source_id"], c["dept_id"])][3], 2)),
                ),
            })
        with open(os.path.join(workspace, f"onboarding_metrics_{i:02d}.yaml"), "w") as f:
            yaml.dump(records, f, default_flow_style=False, sort_keys=False)


def _write_channel_pricing(workspace):
    pricing = {
        "source_fees": {
            "job_board": {
                "quarterly_posting_fee": 2500,
                "per_hire_fee": 350,
            },
            "referral": {
                "referral_bonus": 3500,
            },
            "agency": {
                "placement_fee_pct": 0.15,
            },
        },
        "department_avg_salary": {
            "Engineering": 135000,
            "Sales": 92000,
            "Marketing": 105000,
            "Operations": 82000,
        },
        "notes": (
            "For agency sources, the external fee is placement_fee_pct multiplied by the "
            "department average salary. For job boards, the per_hire_fee applies to each hire. "
            "The quarterly_posting_fee is a flat cost per source per quarter, divided equally "
            "across all hires from that source in the most recent quarter (2025-Q4). "
            "For referrals, the referral_bonus is paid per hire."
        ),
    }
    with open(os.path.join(workspace, "channel_pricing.yaml"), "w") as f:
        yaml.dump(pricing, f, default_flow_style=False, sort_keys=False)


def _write_kpi_formula(workspace):
    formula = {
        "quality_of_hire_weights": {
            "retention_rate": 0.30,
            "time_to_hire_efficiency": 0.15,
            "interview_quality": 0.20,
            "manager_satisfaction": 0.20,
            "onboarding_success": 0.15,
        },
        "normalization": {
            "time_to_hire_efficiency": (
                "Computed as max(0, 1 - avg_days_to_hire / 60). "
                "A hire completed in 0 days scores 1.0; 60+ days scores 0.0."
            ),
            "interview_quality": (
                "Average of (technical_score + behavioral_score + cultural_fit_score) / 3 "
                "across all interviewed candidates for the source-department pair, then divided by 5."
            ),
            "manager_satisfaction": (
                "Average manager_satisfaction rating across hired candidates "
                "for the source-department pair, divided by 5."
            ),
            "onboarding_success": (
                "Average completion_pct across hired candidates "
                "for the source-department pair, divided by 100."
            ),
            "retention_rate": (
                "Fraction of hired candidates active at 12 months "
                "for the source-department pair. Use directly (already 0-1)."
            ),
        },
    }
    with open(os.path.join(workspace, "kpi_formula.json"), "w") as f:
        json.dump(formula, f, indent=2)


def _write_budget_rules(workspace):
    rules = """Budget Allocation Policy for Quarterly Recruitment Spend

Allocation Method:
The total quarterly budget (specified in quarterly_targets.csv for the target quarter)
is allocated across source-department pairs using an efficiency-weighted approach.

Step 1 - Compute the efficiency score for each source-department pair:
  efficiency_score = quality_score / total_cost_per_hire * 10000

  where total_cost_per_hire = avg_internal_cost (from historical data) + external_channel_fee
  (from channel_pricing.yaml).

  For the external_channel_fee:
    - job_board sources: per_hire_fee + (quarterly_posting_fee / number_of_hires_from_that_source_in_2025-Q4)
    - referral sources: referral_bonus
    - agency sources: placement_fee_pct * department_avg_salary

Step 2 - Compute raw allocation weights:
  For each source-department pair:
    raw_weight = efficiency_score * historical_hire_count
  where historical_hire_count is the total number of hires from that source-department
  pair across all quarters.

Step 3 - Normalize weights to get raw budget percentages:
  raw_pct[source][dept] = raw_weight[source][dept] / sum(all raw_weights)

Step 4 - Apply per-source constraints:
  Aggregate raw_pct by source (sum across departments for each source).
  Each source must receive at least 8% of the total budget.
  Each source must receive no more than 35% of the total budget.

  If a source falls below the minimum, set it to the minimum.
  If a source exceeds the maximum, cap it at the maximum.
  Redistribute the surplus or deficit proportionally among unconstrained sources.
  Repeat until all constraints are satisfied.

  After source-level adjustment, distribute each source's allocation back to its
  departments proportionally to the original department-level raw weights within
  that source.

Step 5 - Compute final allocated budget:
  allocated_budget[source][dept] = adjusted_pct[source][dept] * total_budget
  Round to the nearest whole dollar.

Step 6 - Compute expected hires:
  expected_hires[source][dept] = allocated_budget[source][dept] / total_cost_per_hire[source][dept]
  Round to one decimal place.
"""
    with open(os.path.join(workspace, "budget_rules.md"), "w") as f:
        f.write(rules)


def _write_quarterly_targets(workspace):
    pd.DataFrame([
        {"quarter": "2026-Q1", "total_budget": 500000, "target_total_hires": 55},
    ]).to_csv(os.path.join(workspace, "quarterly_targets.csv"), index=False)


# ────────────────────────────────────────────
# Main
# ────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    seed_all(42)
    fake = Faker()
    Faker.seed(42)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    insert_reference_data(conn)
    all_candidates, hired_candidates = generate_candidates(conn, fake, SCALE["rows_per_table"])
    conn.close()

    generate_workspace_files(args.workspace, all_candidates, hired_candidates, SCALE["num_workspace_files"])

    print(f"Database: {args.db_path}  ({len(all_candidates)} candidates, {len(hired_candidates)} hired)")
    print(f"Workspace: {args.workspace}/  ({SCALE['num_workspace_files']} scalable + 4 fixed files)")


if __name__ == "__main__":
    main()
