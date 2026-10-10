"""
Data generation for code review bottleneck analysis task.
Generates a SQLite database and workspace files for analyzing
reviewer overload and generating rebalancing proposals.
"""
import argparse
import sqlite3
import os
import json
import csv
import numpy as np
import pandas as pd
from faker import Faker

try:
    import yaml
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml", "-q"])
    import yaml

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 40,
}

TEAMS = ["backend", "frontend", "platform", "data", "mobile"]
ROLES = ["junior", "mid", "senior", "lead"]
LANGUAGES = [
    "python", "javascript", "typescript", "go", "rust",
    "java", "kotlin", "swift", "ruby", "sql",
]
PRIORITIES = ["P0", "P1", "P2", "P3"]
ASSIGNMENT_STATUSES = ["pending", "in_progress", "completed", "declined"]
PR_STATUSES = ["open", "merged", "closed"]
REPOS = [
    "backend-api", "frontend-app", "platform-core", "data-pipeline",
    "mobile-ios", "mobile-android", "auth-service", "payment-gateway",
    "analytics-engine", "infra-tools", "ml-models", "notification-service",
    "search-engine", "user-service", "config-manager",
]
TIMEZONES = [
    "US/Eastern", "US/Pacific", "US/Central", "Europe/London",
    "Europe/Berlin", "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata",
]
TITLE_VERBS = ["Fix", "Add", "Update", "Refactor", "Implement", "Remove", "Optimize"]


def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS team_members (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        team TEXT NOT NULL,
        role TEXT NOT NULL,
        specializations TEXT NOT NULL,
        hire_date TEXT NOT NULL,
        timezone TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS pull_requests (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        repo TEXT NOT NULL,
        author_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        priority TEXT NOT NULL,
        complexity_score INTEGER NOT NULL,
        lines_changed INTEGER NOT NULL,
        language TEXT NOT NULL,
        status TEXT NOT NULL,
        FOREIGN KEY (author_id) REFERENCES team_members(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS review_assignments (
        id INTEGER PRIMARY KEY,
        pr_id INTEGER NOT NULL,
        reviewer_id INTEGER NOT NULL,
        assigned_at TEXT NOT NULL,
        completed_at TEXT,
        status TEXT NOT NULL,
        round_number INTEGER NOT NULL,
        FOREIGN KEY (pr_id) REFERENCES pull_requests(id),
        FOREIGN KEY (reviewer_id) REFERENCES team_members(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS review_completions (
        id INTEGER PRIMARY KEY,
        assignment_id INTEGER NOT NULL,
        duration_hours REAL NOT NULL,
        quality_score REAL NOT NULL,
        comments_count INTEGER NOT NULL,
        FOREIGN KEY (assignment_id) REFERENCES review_assignments(id)
    )""")
    conn.commit()


def generate_team_members(n, fake, rng):
    members = []
    for i in range(1, n + 1):
        team = TEAMS[i % len(TEAMS)]
        role = str(rng.choice(ROLES, p=[0.25, 0.35, 0.25, 0.15]))
        num_specs = int(rng.integers(2, 5))
        specs = list(rng.choice(LANGUAGES, size=num_specs, replace=False))
        hire_date = fake.date_between(start_date="-5y", end_date="-3m").isoformat()
        tz = str(rng.choice(TIMEZONES))
        members.append({
            "id": i,
            "name": fake.unique.name(),
            "email": f"dev{i}@company.com",
            "team": team,
            "role": role,
            "specializations": ",".join(specs),
            "hire_date": hire_date,
            "timezone": tz,
        })
    return members


def generate_pull_requests(n, members, fake, rng):
    prs = []
    for i in range(1, n + 1):
        author = members[int(rng.integers(0, len(members)))]
        repo = str(rng.choice(REPOS))
        priority = str(rng.choice(PRIORITIES, p=[0.10, 0.25, 0.40, 0.25]))
        complexity = int(rng.integers(1, 11))
        lines = int(rng.integers(10, 2001))
        lang = str(rng.choice(LANGUAGES))
        status = str(rng.choice(PR_STATUSES, p=[0.55, 0.30, 0.15]))
        created = fake.date_time_between(start_date="-30d", end_date="-1d").isoformat()
        verb = str(rng.choice(TITLE_VERBS))
        prs.append({
            "id": i,
            "title": f"{verb} {fake.bs()}",
            "repo": repo,
            "author_id": author["id"],
            "created_at": created,
            "priority": priority,
            "complexity_score": complexity,
            "lines_changed": lines,
            "language": lang,
            "status": status,
        })
    return prs


def generate_review_assignments(prs, members, fake, rng):
    """Generate review assignments with a skewed popularity distribution."""
    n_members = len(members)
    # Skew: some reviewers are much more popular
    popularity = rng.exponential(1.0, size=n_members)
    popularity = popularity / popularity.sum()

    assignments = []
    aid = 1
    for pr in prs:
        num_reviewers = int(rng.integers(1, 4))
        eligible_idx = [j for j, m in enumerate(members) if m["id"] != pr["author_id"]]
        if len(eligible_idx) < num_reviewers:
            num_reviewers = len(eligible_idx)

        # Weighted sampling for reviewer popularity skew
        eligible_pop = np.array([popularity[j] for j in eligible_idx])
        eligible_pop = eligible_pop / eligible_pop.sum()
        chosen_idx = list(rng.choice(eligible_idx, size=num_reviewers, replace=False, p=eligible_pop))

        for round_num, idx in enumerate(chosen_idx, 1):
            reviewer = members[idx]
            assigned_at = fake.date_time_between(start_date="-25d", end_date="-1d").isoformat()

            if pr["status"] == "merged":
                status = "completed"
                completed_at = fake.date_time_between(start_date="-20d", end_date="-1h").isoformat()
            elif pr["status"] == "closed":
                status = str(rng.choice(["completed", "declined"]))
                completed_at = (
                    fake.date_time_between(start_date="-20d", end_date="-1h").isoformat()
                    if status == "completed" else None
                )
            else:  # open
                status = str(rng.choice(
                    ["pending", "in_progress", "completed"],
                    p=[0.45, 0.35, 0.20],
                ))
                completed_at = (
                    fake.date_time_between(start_date="-10d", end_date="-1h").isoformat()
                    if status == "completed" else None
                )

            assignments.append({
                "id": aid,
                "pr_id": pr["id"],
                "reviewer_id": reviewer["id"],
                "assigned_at": assigned_at,
                "completed_at": completed_at,
                "status": status,
                "round_number": round_num,
            })
            aid += 1

    return assignments


def generate_review_completions(assignments, rng):
    completions = []
    cid = 1
    for a in assignments:
        if a["status"] == "completed":
            duration = round(float(rng.exponential(8.0)) + 0.5, 2)
            quality = round(float(rng.uniform(1.5, 5.0)), 2)
            comments = int(rng.integers(1, 30))
            completions.append({
                "id": cid,
                "assignment_id": a["id"],
                "duration_hours": duration,
                "quality_score": quality,
                "comments_count": comments,
            })
            cid += 1
    return completions


def generate_workspace(workspace, members, prs, assignments, rng):
    os.makedirs(workspace, exist_ok=True)

    num_avail_files = SCALE["num_workspace_files"]
    days = ["monday", "tuesday", "wednesday", "thursday", "friday"]

    # Pre-compute base availability per member (some members are low-availability)
    base_avail = {}
    for m in members:
        if rng.random() < 0.20:
            base_avail[m["id"]] = float(rng.uniform(0.5, 2.5))
        else:
            base_avail[m["id"]] = float(rng.uniform(3.0, 7.0))

    # Scalable data files: weekly availability schedules
    for week in range(1, num_avail_files + 1):
        rows = []
        for m in members:
            row = {"member_id": m["id"]}
            base = base_avail[m["id"]]
            for day in days:
                h = round(float(np.clip(rng.normal(base, 1.2), 0, 8)), 1)
                if rng.random() < 0.10:  # occasional day off
                    h = 0.0
                row[f"{day}_hours"] = h
            rows.append(row)
        df = pd.DataFrame(rows)
        df.to_csv(
            os.path.join(workspace, f"availability_schedule_week_{week:02d}.csv"),
            index=False,
        )

    # --- Fixed policy / config files ---

    # review_policy.yaml
    policy = {
        "overload_threshold": 1.5,
        "max_concurrent_reviews": {
            "junior": 3,
            "mid": 5,
            "senior": 7,
            "lead": 4,
        },
        "availability_lookback_weeks": 4,
        "review_sla_hours": {
            "P0": 4,
            "P1": 12,
            "P2": 48,
            "P3": 120,
        },
        "min_quality_score_for_reassignment_target": 3.0,
    }
    with open(os.path.join(workspace, "review_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # priority_weights.json
    weights = {"P0": 4.0, "P1": 2.5, "P2": 1.5, "P3": 1.0}
    with open(os.path.join(workspace, "priority_weights.json"), "w") as f:
        json.dump(weights, f, indent=2)

    # role_capacity.json
    capacity = {"junior": 0.6, "mid": 0.8, "senior": 1.0, "lead": 0.5}
    with open(os.path.join(workspace, "role_capacity.json"), "w") as f:
        json.dump(capacity, f, indent=2)

    # team_expertise_matrix.json — maps teams to their primary repos
    team_repos = {
        "backend": ["backend-api", "auth-service", "payment-gateway", "user-service"],
        "frontend": ["frontend-app", "notification-service"],
        "platform": ["platform-core", "infra-tools", "config-manager"],
        "data": ["data-pipeline", "analytics-engine", "ml-models", "search-engine"],
        "mobile": ["mobile-ios", "mobile-android"],
    }
    with open(os.path.join(workspace, "team_expertise_matrix.json"), "w") as f:
        json.dump(team_repos, f, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    np.random.seed(42)
    rng = np.random.default_rng(42)
    fake = Faker()
    Faker.seed(42)

    n = SCALE["rows_per_table"]

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    members = generate_team_members(n, fake, rng)
    prs = generate_pull_requests(n, members, fake, rng)
    assignments = generate_review_assignments(prs, members, fake, rng)
    completions = generate_review_completions(assignments, rng)

    c = conn.cursor()
    for m in members:
        c.execute(
            "INSERT INTO team_members VALUES (?,?,?,?,?,?,?,?)",
            (m["id"], m["name"], m["email"], m["team"], m["role"],
             m["specializations"], m["hire_date"], m["timezone"]),
        )
    for p in prs:
        c.execute(
            "INSERT INTO pull_requests VALUES (?,?,?,?,?,?,?,?,?,?)",
            (p["id"], p["title"], p["repo"], p["author_id"], p["created_at"],
             p["priority"], p["complexity_score"], p["lines_changed"],
             p["language"], p["status"]),
        )
    for a in assignments:
        c.execute(
            "INSERT INTO review_assignments VALUES (?,?,?,?,?,?,?)",
            (a["id"], a["pr_id"], a["reviewer_id"], a["assigned_at"],
             a["completed_at"], a["status"], a["round_number"]),
        )
    for comp in completions:
        c.execute(
            "INSERT INTO review_completions VALUES (?,?,?,?,?)",
            (comp["id"], comp["assignment_id"], comp["duration_hours"],
             comp["quality_score"], comp["comments_count"]),
        )

    conn.commit()
    conn.close()

    generate_workspace(args.workspace, members, prs, assignments, rng)

    print(f"Database created at {args.db_path}")
    print(f"  team_members:      {len(members)}")
    print(f"  pull_requests:     {len(prs)}")
    print(f"  review_assignments:{len(assignments)}")
    print(f"  review_completions:{len(completions)}")
    print(f"Workspace generated in {args.workspace}/ "
          f"({SCALE['num_workspace_files']} availability files + 3 config files)")


if __name__ == "__main__":
    main()
