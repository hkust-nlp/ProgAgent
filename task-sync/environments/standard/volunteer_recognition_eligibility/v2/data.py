import argparse
import os
import sqlite3
import json
from datetime import date
import numpy as np
import pandas as pd
from faker import Faker
import yaml


def _split_df(df, n):
    L = len(df)
    base, rem = divmod(L, n)
    out, start = [], 0
    for i in range(n):
        size = base + (1 if i < rem else 0)
        out.append(df.iloc[start:start + size])
        start += size
    return out


SCALE = {
    "rows_per_table": 320,
    "num_workspace_files": 30,
}


def main(db_path, workspace):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    num_volunteers = SCALE["rows_per_table"]
    num_workspace_files = SCALE["num_workspace_files"]

    # --------------- Generate Volunteers ---------------
    departments = [
        "Community Outreach", "Education", "Healthcare", "Environment",
        "Youth Services", "Senior Care", "Disaster Relief", "Animal Welfare",
    ]

    volunteers = []
    for i in range(1, num_volunteers + 1):
        volunteers.append({
            "volunteer_id": f"V{i:04d}",
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "email": fake.email(),
            "department": departments[np.random.randint(0, len(departments))],
            "join_date": fake.date_between(
                start_date=date(2021, 1, 1), end_date=date(2025, 12, 31)
            ).isoformat(),
            "status": np.random.choice(["active", "inactive"], p=[0.85, 0.15]),
        })

    vol_ids = [v["volunteer_id"] for v in volunteers]

    # --------------- Generate Hours Log ---------------
    # 8x rows_per_table to ensure rich data; dates span Oct 2025 – Mar 2026
    activity_types = [
        "tutoring", "mentoring", "event_support", "admin",
        "outreach", "training", "fundraising", "counseling",
    ]

    num_hours_entries = SCALE["rows_per_table"] * 8
    hours_entries = []
    for _ in range(num_hours_entries):
        vid = vol_ids[np.random.randint(0, len(vol_ids))]
        log_date = fake.date_between(
            start_date=date(2025, 10, 1), end_date=date(2026, 3, 31)
        )
        hours = round(float(np.random.uniform(1.0, 8.0)), 1)
        hours_entries.append({
            "volunteer_id": vid,
            "log_date": log_date.isoformat(),
            "hours": hours,
            "activity_type": activity_types[np.random.randint(0, len(activity_types))],
        })

    # --------------- Generate Certifications ---------------
    cert_categories = [
        "first_aid", "leadership", "counseling", "data_analysis",
        "project_management", "conflict_resolution", "public_speaking",
        "grant_writing", "crisis_intervention", "community_health",
    ]
    cert_names_map = {
        "first_aid": ["CPR & First Aid Basics", "Advanced First Aid", "Wilderness First Aid"],
        "leadership": ["Team Leadership Fundamentals", "Advanced Leadership Workshop", "Strategic Leadership"],
        "counseling": ["Peer Counseling 101", "Crisis Counseling", "Youth Counseling Certification"],
        "data_analysis": ["Data Analysis for Nonprofits", "Excel for Volunteers", "Survey Design & Analysis"],
        "project_management": ["Project Management Basics", "Agile for Nonprofits", "Event Planning Certification"],
        "conflict_resolution": ["Conflict Resolution Basics", "Mediation Skills", "Restorative Justice Training"],
        "public_speaking": ["Public Speaking 101", "Presentation Skills", "Advocacy Communication"],
        "grant_writing": ["Grant Writing Fundamentals", "Advanced Grant Proposals", "Federal Grant Applications"],
        "crisis_intervention": ["Crisis Intervention Training", "Mental Health First Aid", "Trauma-Informed Care"],
        "community_health": ["Community Health Worker", "Health Education Basics", "Nutrition & Wellness"],
    }

    num_certs = SCALE["rows_per_table"] * 2
    certs = []
    for i in range(num_certs):
        vid = vol_ids[np.random.randint(0, len(vol_ids))]
        cat = cert_categories[np.random.randint(0, len(cert_categories))]
        names = cert_names_map[cat]
        cert_name = names[np.random.randint(0, len(names))]
        completion_date = fake.date_between(
            start_date=date(2023, 1, 1), end_date=date(2026, 3, 31)
        )
        is_active = int(np.random.choice([1, 0], p=[0.8, 0.2]))
        certs.append({
            "cert_id": i + 1,
            "volunteer_id": vid,
            "cert_name": cert_name,
            "cert_category": cat,
            "completion_date": completion_date.isoformat(),
            "is_active": is_active,
        })

    # --------------- Generate Peer Feedback ---------------
    quarters = ["Q4_2025", "Q1_2026"]
    feedback_categories = ["reliability", "teamwork", "communication", "initiative", "skill"]

    num_feedbacks = SCALE["rows_per_table"] * 3
    feedbacks = []
    for i in range(num_feedbacks):
        vid = vol_ids[np.random.randint(0, len(vol_ids))]
        reviewer_idx = np.random.randint(0, len(vol_ids))
        while vol_ids[reviewer_idx] == vid:
            reviewer_idx = np.random.randint(0, len(vol_ids))
        score = round(float(np.random.uniform(1.0, 5.0)), 1)
        quarter = quarters[np.random.randint(0, len(quarters))]
        feedbacks.append({
            "feedback_id": i + 1,
            "volunteer_id": vid,
            "reviewer_id": vol_ids[reviewer_idx],
            "score": score,
            "quarter": quarter,
            "category": feedback_categories[np.random.randint(0, len(feedback_categories))],
        })

    # --------------- Generate Event Leadership ---------------
    role_types = ["lead_organizer", "co_organizer", "section_lead", "coordinator"]
    event_suffixes = ["Drive", "Gala", "Workshop", "Summit", "Fair", "Campaign", "Rally", "Forum"]

    num_leaderships = SCALE["rows_per_table"] * 2
    leaderships = []
    for i in range(num_leaderships):
        vid = vol_ids[np.random.randint(0, len(vol_ids))]
        event_date = fake.date_between(
            start_date=date(2025, 10, 1), end_date=date(2026, 3, 31)
        )
        quarter = "Q1_2026" if event_date >= pd.Timestamp("2026-01-01").date() else "Q4_2025"
        suffix = event_suffixes[np.random.randint(0, len(event_suffixes))]
        leaderships.append({
            "leadership_id": i + 1,
            "volunteer_id": vid,
            "event_name": fake.catch_phrase() + " " + suffix,
            "role_type": role_types[np.random.randint(0, len(role_types))],
            "event_date": event_date.isoformat(),
            "quarter": quarter,
        })

    # =============== Create Database ===============
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS volunteers (
            volunteer_id TEXT PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT,
            department TEXT,
            join_date TEXT,
            status TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hours_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            volunteer_id TEXT NOT NULL,
            log_date TEXT,
            hours REAL,
            activity_type TEXT,
            FOREIGN KEY (volunteer_id) REFERENCES volunteers(volunteer_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS certifications (
            cert_id INTEGER PRIMARY KEY,
            volunteer_id TEXT NOT NULL,
            cert_name TEXT,
            cert_category TEXT,
            completion_date TEXT,
            is_active INTEGER,
            FOREIGN KEY (volunteer_id) REFERENCES volunteers(volunteer_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS peer_feedback (
            feedback_id INTEGER PRIMARY KEY,
            volunteer_id TEXT NOT NULL,
            reviewer_id TEXT,
            score REAL,
            quarter TEXT,
            category TEXT,
            FOREIGN KEY (volunteer_id) REFERENCES volunteers(volunteer_id),
            FOREIGN KEY (reviewer_id) REFERENCES volunteers(volunteer_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS event_leadership (
            leadership_id INTEGER PRIMARY KEY,
            volunteer_id TEXT NOT NULL,
            event_name TEXT,
            role_type TEXT,
            event_date TEXT,
            quarter TEXT,
            FOREIGN KEY (volunteer_id) REFERENCES volunteers(volunteer_id)
        )
    """)

    for v in volunteers:
        cur.execute(
            "INSERT INTO volunteers VALUES (?,?,?,?,?,?,?)",
            (v["volunteer_id"], v["first_name"], v["last_name"],
             v["email"], v["department"], v["join_date"], v["status"]),
        )
    for h in hours_entries:
        cur.execute(
            "INSERT INTO hours_log (volunteer_id, log_date, hours, activity_type) VALUES (?,?,?,?)",
            (h["volunteer_id"], h["log_date"], h["hours"], h["activity_type"]),
        )
    for c in certs:
        cur.execute(
            "INSERT INTO certifications VALUES (?,?,?,?,?,?)",
            (c["cert_id"], c["volunteer_id"], c["cert_name"],
             c["cert_category"], c["completion_date"], c["is_active"]),
        )
    for f in feedbacks:
        cur.execute(
            "INSERT INTO peer_feedback VALUES (?,?,?,?,?,?)",
            (f["feedback_id"], f["volunteer_id"], f["reviewer_id"],
             f["score"], f["quarter"], f["category"]),
        )
    for l in leaderships:
        cur.execute(
            "INSERT INTO event_leadership VALUES (?,?,?,?,?,?)",
            (l["leadership_id"], l["volunteer_id"], l["event_name"],
             l["role_type"], l["event_date"], l["quarter"]),
        )

    conn.commit()
    conn.close()

    # =============== Create Workspace Files ===============

    # --- Fixed config files (not part of SCALE["num_workspace_files"]) ---

    # award_policy.yaml — tier definitions and eligibility rules
    award_policy = {
        "evaluation_quarter": "Q1_2026",
        "quarter_start": "2026-01-01",
        "quarter_end": "2026-03-31",
        "eligibility": {
            "status_required": "active",
            "joined_on_or_before": "2025-12-31",
        },
        "tiers": {
            "Platinum": {
                "min_total_hours": 22.0,
                "min_specialized_cert_categories": 2,
                "min_avg_feedback": 3.0,
                "min_leadership_roles": 1,
            },
            "Gold": {
                "min_total_hours": 16.0,
                "min_specialized_cert_categories": 1,
                "min_avg_feedback": 2.5,
                "min_leadership_roles": 1,
            },
            "Silver": {
                "min_total_hours": 11.0,
                "min_specialized_cert_categories": 0,
                "min_avg_feedback": 2.5,
                "min_leadership_roles": 1,
            },
            "Bronze": {
                "min_total_hours": 6.0,
                "min_specialized_cert_categories": 0,
                "min_avg_feedback": 2.0,
                "min_leadership_roles": 0,
            },
        },
        "tier_priority": ["Platinum", "Gold", "Silver", "Bronze"],
    }
    with open(os.path.join(workspace, "award_policy.yaml"), "w") as f:
        yaml.dump(award_policy, f, default_flow_style=False, sort_keys=False)

    # specialized_certs.json — which cert categories count as specialized
    specialized = {
        "description": "Certification categories that qualify as specialized training for award consideration.",
        "specialized_categories": [
            "crisis_intervention",
            "counseling",
            "leadership",
            "project_management",
            "grant_writing",
        ],
    }
    with open(os.path.join(workspace, "specialized_certs.json"), "w") as f:
        json.dump(specialized, f, indent=2)

    # department_contacts.md — reference file with department info (additional context)
    dept_lines = ["# Department Contact Directory\n"]
    for dept in departments:
        dept_lines.append(f"## {dept}\n")
        dept_lines.append(f"- Coordinator: {fake.name()}\n")
        dept_lines.append(f"- Email: {fake.company_email()}\n")
        dept_lines.append(f"- Phone: {fake.phone_number()}\n\n")
    with open(os.path.join(workspace, "department_contacts.md"), "w") as f:
        f.writelines(dept_lines)

    # --- Scalable data files: hours log CSVs (count = num_workspace_files) ---
    hours_df = pd.DataFrame(hours_entries)
    hours_df = hours_df.sort_values("log_date").reset_index(drop=True)

    chunks = _split_df(hours_df, num_workspace_files)
    for idx, chunk in enumerate(chunks):
        filename = f"hours_log_part_{idx + 1:03d}.csv"
        chunk.to_csv(os.path.join(workspace, filename), index=False)

    print(f"Database created at {db_path}")
    print(f"Workspace created at {workspace}")
    print(f"  Volunteers:    {len(volunteers)}")
    print(f"  Hours entries: {len(hours_entries)}")
    print(f"  Certs:         {len(certs)}")
    print(f"  Feedbacks:     {len(feedbacks)}")
    print(f"  Leaderships:   {len(leaderships)}")
    print(f"  Workspace data files: {num_workspace_files}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
