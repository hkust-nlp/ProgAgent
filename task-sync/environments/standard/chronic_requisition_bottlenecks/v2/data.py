#!/usr/bin/env python3
"""Data generation for chronic requisition bottleneck analysis task."""

import argparse
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 240,
    "num_workspace_files": 24,
}

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

# ---------- constants ----------
REFERENCE_DATE = datetime(2026, 4, 15)

DEPARTMENTS = [
    {"id": 1,  "name": "Engineering",       "division": "Technology"},
    {"id": 2,  "name": "Data Science",       "division": "Technology"},
    {"id": 3,  "name": "Product Management", "division": "Product"},
    {"id": 4,  "name": "Design",             "division": "Product"},
    {"id": 5,  "name": "Marketing",          "division": "Commercial"},
    {"id": 6,  "name": "Sales",              "division": "Commercial"},
    {"id": 7,  "name": "Finance",            "division": "Operations"},
    {"id": 8,  "name": "Human Resources",    "division": "Operations"},
    {"id": 9,  "name": "Legal",              "division": "Operations"},
    {"id": 10, "name": "Customer Support",   "division": "Commercial"},
]

STATUSES = ["open", "closed", "on_hold", "cancelled"]
LOCATIONS = [
    "New York, NY", "San Francisco, CA", "Austin, TX", "Seattle, WA",
    "Chicago, IL", "Boston, MA", "Denver, CO", "Remote",
]
CANDIDATE_STAGES = [
    "applied", "phone_screen", "technical_interview",
    "onsite_interview", "offer_extended", "hired", "rejected", "withdrawn",
]
CANDIDATE_SOURCES = [
    "linkedin", "referral", "careers_page", "indeed",
    "glassdoor", "recruiter_outreach", "university",
]
FEEDBACK_CATEGORIES = [
    "technical_skills", "communication", "culture_fit",
    "experience_relevance", "leadership_potential",
]
UNASSIGN_REASONS = [
    "workload_rebalance", "recruiter_departure", "specialization_mismatch",
    "manager_request", "performance_concern",
]

PIPELINE_STAGES_CONFIG = [
    {"stage": "applied",              "expected_days": 3},
    {"stage": "phone_screen",         "expected_days": 5},
    {"stage": "technical_interview",  "expected_days": 7},
    {"stage": "onsite_interview",     "expected_days": 7},
    {"stage": "offer_extended",       "expected_days": 5},
]

DEPT_THRESHOLDS = {
    d["name"]: {
        "days_open_flag": 60,
        "min_weekly_application_rate": round(np.random.uniform(1.5, 4.0), 1),
        "min_acceptable_feedback_score": round(np.random.uniform(2.5, 3.5), 1),
        "max_recruiter_changes": int(np.random.choice([2, 3])),
    }
    for d in DEPARTMENTS
}

BOTTLENECK_DEFS = {
    "low_application_flow": {
        "condition": "Average weekly application rate is below the department minimum threshold.",
        "severity_weight": 3,
    },
    "high_stage_stagnation": {
        "condition": "More than 40% of active candidates are stuck beyond the expected duration of their current pipeline stage.",
        "severity_weight": 4,
    },
    "low_feedback_scores": {
        "condition": "Average hiring-manager feedback score for the requisition is below the department minimum acceptable score.",
        "severity_weight": 2,
    },
    "recruiter_instability": {
        "condition": "Number of recruiter reassignments exceeds the department maximum allowed changes.",
        "severity_weight": 3,
    },
    "feedback_delay": {
        "condition": "Fewer than 50% of active candidates who reached onsite_interview stage have received any hiring-manager feedback.",
        "severity_weight": 2,
    },
}

PRIORITY_SCORING_TEXT = """Priority Scoring Rules
======================

For each requisition flagged as open longer than the department threshold (days_open_flag), compute a priority score as follows.

Base score equals the number of days the requisition has been open divided by ten, rounded down to the nearest integer, and capped at a maximum of ten.

Apply the following additive modifiers:

If the requisition triggers the "low_application_flow" bottleneck, add the severity weight for that bottleneck type.
If the requisition triggers the "high_stage_stagnation" bottleneck, add the severity weight for that bottleneck type.
If the requisition triggers the "low_feedback_scores" bottleneck, add the severity weight for that bottleneck type.
If the requisition triggers the "recruiter_instability" bottleneck, add the severity weight for that bottleneck type.
If the requisition triggers the "feedback_delay" bottleneck, add the severity weight for that bottleneck type.

The final priority score is the sum of the base score and all applicable modifiers.

Sort the intervention list by priority_score descending. For ties, sort by requisition_id ascending.
"""


def create_tables(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS departments (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        division TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS requisitions (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        department_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        open_date TEXT NOT NULL,
        close_date TEXT,
        priority_level TEXT NOT NULL,
        target_headcount INTEGER NOT NULL,
        location TEXT NOT NULL,
        FOREIGN KEY (department_id) REFERENCES departments(id)
    );
    CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY,
        requisition_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        application_date TEXT NOT NULL,
        current_stage TEXT NOT NULL,
        source TEXT NOT NULL,
        FOREIGN KEY (requisition_id) REFERENCES requisitions(id)
    );
    CREATE TABLE IF NOT EXISTS recruiter_assignments (
        id INTEGER PRIMARY KEY,
        requisition_id INTEGER NOT NULL,
        recruiter_id INTEGER NOT NULL,
        recruiter_name TEXT NOT NULL,
        assigned_date TEXT NOT NULL,
        unassigned_date TEXT,
        reason TEXT,
        FOREIGN KEY (requisition_id) REFERENCES requisitions(id)
    );
    CREATE TABLE IF NOT EXISTS hiring_manager_feedback (
        id INTEGER PRIMARY KEY,
        requisition_id INTEGER NOT NULL,
        candidate_id INTEGER NOT NULL,
        feedback_date TEXT NOT NULL,
        score REAL NOT NULL,
        category TEXT NOT NULL,
        comments TEXT,
        FOREIGN KEY (requisition_id) REFERENCES requisitions(id),
        FOREIGN KEY (candidate_id) REFERENCES candidates(id)
    );
    """)


def generate_departments(conn: sqlite3.Connection):
    conn.executemany(
        "INSERT INTO departments (id, name, division) VALUES (?, ?, ?)",
        [(d["id"], d["name"], d["division"]) for d in DEPARTMENTS],
    )
    conn.commit()


def generate_requisitions(conn: sqlite3.Connection):
    n = SCALE["rows_per_table"]
    titles_pool = [
        "Senior Software Engineer", "Backend Developer", "Frontend Developer",
        "ML Engineer", "Data Analyst", "Product Manager", "UX Designer",
        "DevOps Engineer", "QA Engineer", "Security Analyst",
        "Technical Writer", "Solutions Architect", "Site Reliability Engineer",
        "iOS Developer", "Android Developer", "Full Stack Developer",
        "Data Engineer", "Business Analyst", "Scrum Master", "Cloud Architect",
        "Marketing Manager", "Sales Representative", "Account Executive",
        "Financial Analyst", "HR Coordinator", "Legal Counsel",
        "Customer Success Manager", "Support Engineer", "Growth Hacker",
        "Content Strategist",
    ]
    priority_levels = ["critical", "high", "medium", "low"]

    rows = []
    for i in range(1, n + 1):
        dept_id = random.choice([d["id"] for d in DEPARTMENTS])
        title = random.choice(titles_pool)
        # Ensure a good mix: ~60% open, some long-open
        status = random.choices(STATUSES, weights=[0.6, 0.2, 0.15, 0.05])[0]
        days_back = random.randint(10, 180)
        open_date = REFERENCE_DATE - timedelta(days=days_back)
        close_date = None
        if status == "closed":
            max_close_days = max(15, days_back)
            close_date = open_date + timedelta(days=random.randint(15, max_close_days))
            if close_date > REFERENCE_DATE:
                close_date = REFERENCE_DATE - timedelta(days=random.randint(1, 5))
        elif status == "cancelled":
            max_cancel_days = max(5, min(30, days_back))
            close_date = open_date + timedelta(days=random.randint(5, max_cancel_days))
            if close_date > REFERENCE_DATE:
                close_date = REFERENCE_DATE - timedelta(days=1)
        priority = random.choices(priority_levels, weights=[0.15, 0.3, 0.35, 0.2])[0]
        headcount = random.choices([1, 2, 3, 5], weights=[0.5, 0.3, 0.15, 0.05])[0]
        loc = random.choice(LOCATIONS)
        rows.append((
            i, title, dept_id, status,
            open_date.strftime("%Y-%m-%d"),
            close_date.strftime("%Y-%m-%d") if close_date else None,
            priority, headcount, loc,
        ))
    conn.executemany(
        "INSERT INTO requisitions VALUES (?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_candidates(conn: sqlite3.Connection, requisitions):
    n_base = SCALE["rows_per_table"]
    rows = []
    cid = 1
    # Distribute candidates across requisitions
    req_ids = [r[0] for r in requisitions]
    # Ensure at least n_base * 3 candidates total, spread across reqs
    total_needed = max(n_base, n_base * 3)
    per_req_base = max(2, total_needed // len(req_ids))
    for req in requisitions:
        req_id = req[0]
        open_date_str = req[4]
        open_date = datetime.strptime(open_date_str, "%Y-%m-%d")
        n_cands = random.randint(max(1, per_req_base - 2), per_req_base + 4)
        for _ in range(n_cands):
            days_after = random.randint(0, (REFERENCE_DATE - open_date).days)
            app_date = open_date + timedelta(days=days_after)
            stage = random.choices(
                CANDIDATE_STAGES,
                weights=[0.15, 0.15, 0.2, 0.15, 0.05, 0.05, 0.15, 0.1],
            )[0]
            source = random.choice(CANDIDATE_SOURCES)
            rows.append((
                cid, req_id, fake.name(),
                app_date.strftime("%Y-%m-%d"), stage, source,
            ))
            cid += 1
    conn.executemany("INSERT INTO candidates VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_recruiter_assignments(conn: sqlite3.Connection, requisitions):
    n_base = SCALE["rows_per_table"]
    recruiter_pool_size = max(10, n_base // 5)
    recruiter_names = [fake.name() for _ in range(recruiter_pool_size)]
    rows = []
    aid = 1
    total_needed = max(n_base, int(n_base * 1.5))
    per_req = max(1, total_needed // len(requisitions))

    for req in requisitions:
        req_id = req[0]
        open_date = datetime.strptime(req[4], "%Y-%m-%d")
        n_assignments = random.choices(
            [1, 2, 3, 4], weights=[0.35, 0.30, 0.20, 0.15]
        )[0]
        n_assignments = min(n_assignments, max(1, per_req + 1))
        current_date = open_date
        for j in range(n_assignments):
            rec_id = random.randint(1, recruiter_pool_size)
            rec_name = recruiter_names[rec_id - 1]
            assigned = current_date + timedelta(days=random.randint(0, 3))
            if j < n_assignments - 1:
                duration = random.randint(7, 40)
                unassigned = assigned + timedelta(days=duration)
                if unassigned > REFERENCE_DATE:
                    unassigned = REFERENCE_DATE - timedelta(days=1)
                reason = random.choice(UNASSIGN_REASONS)
                rows.append((
                    aid, req_id, rec_id, rec_name,
                    assigned.strftime("%Y-%m-%d"),
                    unassigned.strftime("%Y-%m-%d"),
                    reason,
                ))
                current_date = unassigned + timedelta(days=1)
            else:
                rows.append((
                    aid, req_id, rec_id, rec_name,
                    assigned.strftime("%Y-%m-%d"),
                    None, None,
                ))
            aid += 1
    conn.executemany(
        "INSERT INTO recruiter_assignments VALUES (?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_feedback(conn: sqlite3.Connection, requisitions, candidates):
    n_base = SCALE["rows_per_table"]
    # Build candidate lookup by requisition
    cands_by_req = {}
    for c in candidates:
        cands_by_req.setdefault(c[1], []).append(c)

    rows = []
    fid = 1
    for req in requisitions:
        req_id = req[0]
        open_date = datetime.strptime(req[4], "%Y-%m-%d")
        req_cands = cands_by_req.get(req_id, [])
        # Feedback for candidates who reached at least technical_interview
        advanced_stages = {"technical_interview", "onsite_interview", "offer_extended", "hired"}
        advanced_cands = [c for c in req_cands if c[4] in advanced_stages]
        for cand in advanced_cands:
            n_feedback = random.randint(1, 3)
            for _ in range(n_feedback):
                cand_app_date = datetime.strptime(cand[3], "%Y-%m-%d")
                days_after = random.randint(3, max(4, (REFERENCE_DATE - cand_app_date).days))
                fb_date = cand_app_date + timedelta(days=days_after)
                if fb_date > REFERENCE_DATE:
                    fb_date = REFERENCE_DATE
                score = round(random.uniform(1.0, 5.0), 1)
                category = random.choice(FEEDBACK_CATEGORIES)
                comments = fake.sentence(nb_words=random.randint(5, 15))
                rows.append((
                    fid, req_id, cand[0],
                    fb_date.strftime("%Y-%m-%d"),
                    score, category, comments,
                ))
                fid += 1

    # Pad if we have fewer than n_base rows
    while len(rows) < n_base:
        req = random.choice(requisitions)
        req_id = req[0]
        req_cands = cands_by_req.get(req_id, [])
        if not req_cands:
            continue
        cand = random.choice(req_cands)
        cand_app_date = datetime.strptime(cand[3], "%Y-%m-%d")
        days_after = random.randint(3, max(4, (REFERENCE_DATE - cand_app_date).days))
        fb_date = cand_app_date + timedelta(days=days_after)
        if fb_date > REFERENCE_DATE:
            fb_date = REFERENCE_DATE
        rows.append((
            fid, req_id, cand[0],
            fb_date.strftime("%Y-%m-%d"),
            round(random.uniform(1.0, 5.0), 1),
            random.choice(FEEDBACK_CATEGORIES),
            fake.sentence(nb_words=random.randint(5, 15)),
        ))
        fid += 1

    conn.executemany(
        "INSERT INTO hiring_manager_feedback VALUES (?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_workspace(workspace: str, conn: sqlite3.Connection, requisitions, candidates):
    os.makedirs(workspace, exist_ok=True)
    n_files = SCALE["num_workspace_files"]

    # ---- Fixed config files (not part of SCALE count) ----
    # 1. department_thresholds.yaml
    with open(os.path.join(workspace, "department_thresholds.yaml"), "w") as f:
        yaml.dump(DEPT_THRESHOLDS, f, default_flow_style=False)

    # 2. pipeline_stages.csv
    df_stages = pd.DataFrame(PIPELINE_STAGES_CONFIG)
    df_stages.to_csv(os.path.join(workspace, "pipeline_stages.csv"), index=False)

    # 3. bottleneck_classification.json
    with open(os.path.join(workspace, "bottleneck_classification.json"), "w") as f:
        json.dump(BOTTLENECK_DEFS, f, indent=2)

    # 4. priority_scoring_rules.txt
    with open(os.path.join(workspace, "priority_scoring_rules.txt"), "w") as f:
        f.write(PRIORITY_SCORING_TEXT)

    # 5. recruiter_roster.csv  (includes capacity info not in DB)
    recruiter_ids = set()
    cur = conn.execute("SELECT DISTINCT recruiter_id, recruiter_name FROM recruiter_assignments")
    rec_rows = cur.fetchall()
    roster_data = []
    specializations = [
        "engineering", "product", "commercial", "operations", "general",
    ]
    for rec_id, rec_name in rec_rows:
        roster_data.append({
            "recruiter_id": rec_id,
            "recruiter_name": rec_name,
            "max_concurrent_reqs": random.randint(3, 8),
            "specialization": random.choice(specializations),
            "active": random.choices([True, False], weights=[0.85, 0.15])[0],
        })
    pd.DataFrame(roster_data).to_csv(
        os.path.join(workspace, "recruiter_roster.csv"), index=False
    )

    # ---- Scalable workspace files: weekly pipeline snapshots ----
    # Generate n_files weeks of pipeline snapshots
    # Each file covers one week and has per-requisition stage counts
    req_ids = [r[0] for r in requisitions]

    # Build candidate data for snapshots
    cands_by_req = {}
    for c in candidates:
        cands_by_req.setdefault(c[1], []).append(c)

    stage_order = [s["stage"] for s in PIPELINE_STAGES_CONFIG] + ["hired", "rejected", "withdrawn"]

    for week_idx in range(n_files):
        week_start = REFERENCE_DATE - timedelta(weeks=n_files - week_idx)
        week_end = week_start + timedelta(days=6)
        snapshot_rows = []
        for req_id in req_ids:
            req_cands = cands_by_req.get(req_id, [])
            # Count candidates who applied on or before week_end
            active_cands = [
                c for c in req_cands
                if datetime.strptime(c[3], "%Y-%m-%d") <= week_end
            ]
            stage_counts = {s: 0 for s in stage_order}
            for c in active_cands:
                stage_counts[c[4]] = stage_counts.get(c[4], 0) + 1
            new_apps = len([
                c for c in req_cands
                if week_start <= datetime.strptime(c[3], "%Y-%m-%d") <= week_end
            ])
            snapshot_rows.append({
                "requisition_id": req_id,
                "week_start": week_start.strftime("%Y-%m-%d"),
                "week_end": week_end.strftime("%Y-%m-%d"),
                "new_applications": new_apps,
                **{f"stage_{s}": stage_counts.get(s, 0) for s in stage_order},
            })
        fname = f"weekly_pipeline_week_{week_idx + 1:02d}.csv"
        pd.DataFrame(snapshot_rows).to_csv(
            os.path.join(workspace, fname), index=False
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    generate_departments(conn)
    requisitions = generate_requisitions(conn)
    candidates = generate_candidates(conn, requisitions)
    recruiter_assignments = generate_recruiter_assignments(conn, requisitions)
    feedback = generate_feedback(conn, requisitions, candidates)
    generate_workspace(args.workspace, conn, requisitions, candidates)
    conn.close()
    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")


if __name__ == "__main__":
    main()
