"""
Data generation for high-risk project milestone flagging task.
Generates SQLite DB and workspace files for sprint planning risk analysis.
"""

import argparse
import sqlite3
import os
import json
import csv
import math
import random
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta
import yaml

SCALE = {
    "rows_per_table": 50,
    "num_workspace_files": 8,
}

# Fix all seeds
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# Constants
REFERENCE_DATE = datetime(2026, 4, 20)
PROJECTS = [
    "Atlas Platform", "Mercury API", "Horizon Dashboard",
    "Nexus Integration", "Quantum Analytics", "Phoenix Migration",
    "Titan Infrastructure", "Orion Search", "Nova Payments", "Stellar Auth",
]
PRIORITIES = ["critical", "high", "medium", "low"]
ROLES = [
    "Software Engineer", "Senior Engineer", "Tech Lead", "QA Engineer",
    "DevOps Engineer", "Product Manager", "Designer", "Data Engineer",
    "Backend Developer", "Frontend Developer",
]
DEPARTMENTS = ["Engineering", "QA", "DevOps", "Product", "Design", "Data"]
SEVERITIES = ["critical", "major", "minor", "trivial"]
FOUND_PHASES = ["development", "qa", "staging", "production"]
DEP_TYPES = ["blocks", "depends_on", "related"]
DEP_STATUSES = ["resolved", "active", "at_risk"]
MILESTONE_ROLES_LIST = ["lead", "developer", "reviewer", "tester", "support"]

FEATURE_VERBS = [
    "Implement", "Refactor", "Add", "Update", "Fix", "Create",
    "Design", "Integrate", "Optimize", "Migrate", "Build", "Configure",
]
FEATURE_NOUNS = [
    "authentication flow", "dashboard widget", "API endpoint",
    "database schema", "caching layer", "notification service",
    "payment gateway", "search index", "user profile", "analytics module",
    "logging pipeline", "rate limiter", "file uploader", "webhook handler",
    "permission model", "CI pipeline", "health check", "config loader",
]


def create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS milestones (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            project TEXT NOT NULL,
            target_date TEXT NOT NULL,
            status TEXT NOT NULL,
            priority TEXT NOT NULL,
            description TEXT
        );
        CREATE TABLE IF NOT EXISTS sprints (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            milestone_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            planned_points INTEGER NOT NULL,
            completed_points INTEGER NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (milestone_id) REFERENCES milestones(id)
        );
        CREATE TABLE IF NOT EXISTS stories (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            sprint_id INTEGER NOT NULL,
            milestone_id INTEGER NOT NULL,
            estimated_points INTEGER NOT NULL,
            actual_points INTEGER NOT NULL,
            assignee_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (sprint_id) REFERENCES sprints(id),
            FOREIGN KEY (milestone_id) REFERENCES milestones(id),
            FOREIGN KEY (assignee_id) REFERENCES team_members(id)
        );
        CREATE TABLE IF NOT EXISTS bugs (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            severity TEXT NOT NULL,
            found_phase TEXT NOT NULL,
            milestone_id INTEGER NOT NULL,
            sprint_id INTEGER,
            status TEXT NOT NULL,
            reported_date TEXT NOT NULL,
            FOREIGN KEY (milestone_id) REFERENCES milestones(id),
            FOREIGN KEY (sprint_id) REFERENCES sprints(id)
        );
        CREATE TABLE IF NOT EXISTS team_members (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            department TEXT NOT NULL,
            hire_date TEXT NOT NULL,
            departure_date TEXT,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS milestone_assignments (
            id INTEGER PRIMARY KEY,
            milestone_id INTEGER NOT NULL,
            team_member_id INTEGER NOT NULL,
            role_in_milestone TEXT NOT NULL,
            allocation_pct REAL NOT NULL,
            FOREIGN KEY (milestone_id) REFERENCES milestones(id),
            FOREIGN KEY (team_member_id) REFERENCES team_members(id)
        );
        CREATE TABLE IF NOT EXISTS dependencies (
            id INTEGER PRIMARY KEY,
            source_milestone_id INTEGER NOT NULL,
            target_milestone_id INTEGER NOT NULL,
            dependency_type TEXT NOT NULL,
            status TEXT NOT NULL,
            description TEXT,
            FOREIGN KEY (source_milestone_id) REFERENCES milestones(id),
            FOREIGN KEY (target_milestone_id) REFERENCES milestones(id)
        );
    """)
    conn.commit()


def generate_milestones(conn):
    n = SCALE["rows_per_table"]
    rows = []
    for i in range(1, n + 1):
        project = PROJECTS[i % len(PROJECTS)]
        r = random.random()
        if r < 0.16:
            status = "upcoming"
        elif r < 0.32:
            status = "in_progress"
        elif r < 0.87:
            status = "completed"
        else:
            status = "cancelled"

        priority = random.choices(PRIORITIES, weights=[15, 25, 40, 20])[0]
        if status in ("upcoming", "in_progress"):
            target_date = REFERENCE_DATE + timedelta(days=random.randint(14, 120))
        elif status == "completed":
            target_date = REFERENCE_DATE - timedelta(days=random.randint(1, 365))
        else:
            target_date = REFERENCE_DATE - timedelta(days=random.randint(1, 180))

        verb = random.choice(FEATURE_VERBS)
        noun = random.choice(FEATURE_NOUNS)
        name = f"{project} - {verb} {noun}".title()
        description = fake.paragraph(nb_sentences=2)
        rows.append((i, name, project, target_date.strftime("%Y-%m-%d"),
                     status, priority, description))

    conn.executemany("INSERT INTO milestones VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_team_members(conn):
    n = SCALE["rows_per_table"]
    rows = []
    for i in range(1, n + 1):
        name = fake.unique.name()
        role = random.choice(ROLES)
        dept = random.choice(DEPARTMENTS)
        hire_date = REFERENCE_DATE - timedelta(days=random.randint(100, 1095))

        r = random.random()
        if r < 0.15:
            status = "departed"
            dep_dt = REFERENCE_DATE - timedelta(days=random.randint(1, 80))
            departure_str = dep_dt.strftime("%Y-%m-%d")
        else:
            status = "active"
            departure_str = None

        # ~12% are recent hires (within 90 days)
        if status == "active" and random.random() < 0.12:
            hire_date = REFERENCE_DATE - timedelta(days=random.randint(1, 85))

        rows.append((i, name, role, dept, hire_date.strftime("%Y-%m-%d"),
                     departure_str, status))

    conn.executemany("INSERT INTO team_members VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_sprints(conn, milestones):
    n_sprints = SCALE["rows_per_table"] * 2
    active_ms = [m for m in milestones if m[4] != "cancelled"]
    if not active_ms:
        active_ms = milestones[:max(1, len(milestones) // 2)]

    rows = []
    sprint_id = 1
    per_ms = max(2, n_sprints // len(active_ms))

    for m in active_ms:
        m_id, m_status, m_target_str = m[0], m[4], m[3]
        m_target = datetime.strptime(m_target_str, "%Y-%m-%d")
        ns = random.randint(max(1, per_ms - 1), per_ms + 1)
        for j in range(ns):
            if sprint_id > n_sprints:
                break
            start = m_target - timedelta(days=(ns - j) * 14 + random.randint(0, 7))
            end = start + timedelta(days=14)
            planned = random.randint(15, 60)
            if m_status == "completed" or end < REFERENCE_DATE:
                sp_status = "completed"
                ratio = random.uniform(0.5, 1.5)
                completed = max(0, int(planned * ratio))
            elif start <= REFERENCE_DATE <= end:
                sp_status = "active"
                completed = int(planned * random.uniform(0.2, 0.7))
            else:
                sp_status = "planned"
                completed = 0
            rows.append((sprint_id, f"Sprint {sprint_id}", m_id,
                         start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
                         planned, completed, sp_status))
            sprint_id += 1
        if sprint_id > n_sprints:
            break

    # back-fill to minimum
    while sprint_id <= SCALE["rows_per_table"]:
        m = random.choice(active_ms)
        start = REFERENCE_DATE - timedelta(days=random.randint(14, 180))
        end = start + timedelta(days=14)
        planned = random.randint(15, 60)
        completed = int(planned * random.uniform(0.5, 1.3))
        rows.append((sprint_id, f"Sprint {sprint_id}", m[0],
                     start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
                     planned, completed, "completed"))
        sprint_id += 1

    conn.executemany("INSERT INTO sprints VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_stories(conn, sprints, team_members):
    n_stories = SCALE["rows_per_table"] * 5
    member_ids = [m[0] for m in team_members]
    rows = []
    sid = 1
    per_sp = max(3, n_stories // max(1, len(sprints)))

    for s in sprints:
        s_id, s_mid, s_status = s[0], s[2], s[7]
        ns = random.randint(max(2, per_sp - 2), per_sp + 2)
        for _ in range(ns):
            if sid > n_stories:
                break
            verb = random.choice(FEATURE_VERBS)
            noun = random.choice(FEATURE_NOUNS)
            title = f"STORY-{sid}: {verb} {noun}"
            est = random.choice([1, 2, 3, 5, 8, 13])
            if s_status == "completed":
                st = random.choices(["done", "blocked"], weights=[9, 1])[0]
                act = max(1, int(est * random.uniform(0.4, 2.2))) if st == "done" else 0
            elif s_status == "active":
                st = random.choice(["done", "in_progress", "todo", "blocked"])
                act = max(1, int(est * random.uniform(0.4, 2.2))) if st == "done" else 0
            else:
                st = "todo"
                act = 0
            assignee = random.choice(member_ids)
            rows.append((sid, title, s_id, s_mid, est, act, assignee, st))
            sid += 1
        if sid > n_stories:
            break

    while sid <= SCALE["rows_per_table"]:
        s = random.choice(sprints)
        assignee = random.choice(member_ids)
        est = random.choice([1, 2, 3, 5, 8, 13])
        act = max(1, int(est * random.uniform(0.5, 2.0)))
        rows.append((sid, f"STORY-{sid}: misc task", s[0], s[2],
                     est, act, assignee, "done"))
        sid += 1

    conn.executemany("INSERT INTO stories VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_bugs(conn, milestones, sprints):
    n_bugs = SCALE["rows_per_table"] * 2
    active_ms = [m for m in milestones if m[4] != "cancelled"]
    if not active_ms:
        active_ms = milestones
    ms_sprints = {}
    for s in sprints:
        ms_sprints.setdefault(s[2], []).append(s[0])

    rows = []
    for i in range(1, n_bugs + 1):
        m = random.choice(active_ms)
        m_id = m[0]
        sp_list = ms_sprints.get(m_id, [])
        s_id = random.choice(sp_list) if sp_list else None
        title = f"BUG-{i}: {fake.sentence(nb_words=5)}"
        sev = random.choices(SEVERITIES, weights=[10, 25, 40, 25])[0]
        phase = random.choices(FOUND_PHASES, weights=[30, 30, 18, 22])[0]
        status = random.choice(["open", "fixed", "wontfix", "in_progress"])
        rep_date = (REFERENCE_DATE - timedelta(days=random.randint(1, 180))).strftime("%Y-%m-%d")
        rows.append((i, title, sev, phase, m_id, s_id, status, rep_date))

    conn.executemany("INSERT INTO bugs VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_assignments(conn, milestones, team_members):
    n_assign = SCALE["rows_per_table"] * 3
    active_ms = [m for m in milestones if m[4] in ("upcoming", "in_progress")]
    other_ms = [m for m in milestones if m[4] == "completed"]
    all_ms = active_ms + other_ms
    if not all_ms:
        all_ms = milestones
    mem_ids = [m[0] for m in team_members]
    rows = []
    aid = 1
    used = set()

    # Guarantee each active milestone has 3-8 members
    for m in active_ms:
        nm = random.randint(3, min(8, len(mem_ids)))
        chosen = random.sample(mem_ids, nm)
        for mid in chosen:
            if aid > n_assign:
                break
            if (m[0], mid) in used:
                continue
            used.add((m[0], mid))
            role = random.choice(MILESTONE_ROLES_LIST)
            alloc = random.choice([25, 50, 75, 100])
            rows.append((aid, m[0], mid, role, alloc))
            aid += 1

    attempts = 0
    while aid <= n_assign and attempts < n_assign * 5:
        attempts += 1
        m = random.choice(all_ms)
        mid = random.choice(mem_ids)
        if (m[0], mid) in used:
            continue
        used.add((m[0], mid))
        role = random.choice(MILESTONE_ROLES_LIST)
        alloc = random.choice([25, 50, 75, 100])
        rows.append((aid, m[0], mid, role, alloc))
        aid += 1

    conn.executemany("INSERT INTO milestone_assignments VALUES (?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_dependencies(conn, milestones):
    n_deps = SCALE["rows_per_table"] * 2
    non_cancel = [m for m in milestones if m[4] != "cancelled"]
    if not non_cancel:
        non_cancel = milestones
    m_ids = [m[0] for m in non_cancel]
    rows = []
    used = set()
    did = 1
    attempts = 0
    while did <= n_deps and attempts < n_deps * 10:
        attempts += 1
        src = random.choice(m_ids)
        tgt = random.choice(m_ids)
        if src == tgt or (src, tgt) in used:
            continue
        used.add((src, tgt))
        dtype = random.choice(DEP_TYPES)
        dstatus = random.choices(DEP_STATUSES, weights=[40, 35, 25])[0]
        desc = fake.sentence(nb_words=8)
        rows.append((did, src, tgt, dtype, dstatus, desc))
        did += 1

    conn.executemany("INSERT INTO dependencies VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


# ====================================================================
# Workspace file generators
# ====================================================================

def write_config_files(workspace):
    """Write fixed (non-scaling) config files."""
    risk_config = {
        "reference_date": "2026-04-20",
        "churn_window_days": 90,
        "estimation_accuracy": {
            "normalization_factor": 0.5,
        },
        "dependency_risk": {
            "active_blocking_factor": 0.5,
        },
        "bug_escape": {
            "escaped_phases": ["staging", "production"],
            "normalization_factor": 0.4,
        },
        "team_churn": {
            "normalization_factor": 0.4,
        },
        "risk_levels": {
            "high_threshold": 0.55,
            "medium_threshold": 0.35,
        },
        "mitigation_action_threshold": 0.4,
    }
    with open(os.path.join(workspace, "risk_config.yaml"), "w") as f:
        yaml.dump(risk_config, f, default_flow_style=False, sort_keys=False)

    weights = {
        "estimation_accuracy": 0.30,
        "dependency_risk": 0.25,
        "bug_escape": 0.25,
        "team_churn": 0.20,
    }
    with open(os.path.join(workspace, "scoring_weights.json"), "w") as f:
        json.dump(weights, f, indent=2)


def write_confluence_files(workspace, deps, milestones, n_files):
    """Generate confluence dependency docs with severity weights."""
    ms_map = {m[0]: m[1] for m in milestones}
    rng = random.Random(42)
    dep_weights = {}
    for d in deps:
        dep_weights[d[0]] = rng.randint(1, 5)

    chunk_size = max(1, math.ceil(len(deps) / n_files))
    for idx in range(n_files):
        chunk = deps[idx * chunk_size: (idx + 1) * chunk_size]
        lines = [f"# Confluence Dependency Analysis - Batch {idx + 1}\n"]
        lines.append("| dep_id | source_milestone | target_milestone | severity_weight | risk_notes |")
        lines.append("|--------|-----------------|-----------------|-----------------|------------|")
        for d in chunk:
            did, src, tgt, dtype, dstatus, desc = d
            src_name = ms_map.get(src, f"MS-{src}")
            tgt_name = ms_map.get(tgt, f"MS-{tgt}")
            w = dep_weights[did]
            notes = desc if dstatus == "at_risk" else "Standard linkage"
            lines.append(f"| {did} | {src_name} | {tgt_name} | {w} | {notes} |")
        fname = os.path.join(workspace, f"confluence_dep_{idx + 1}.md")
        with open(fname, "w") as f:
            f.write("\n".join(lines) + "\n")


def write_qa_files(workspace, sprints, n_files):
    """Generate QA metrics CSVs with test coverage info per sprint."""
    rng = random.Random(4242)
    qa_rows = []
    for s in sprints:
        s_id, s_mid = s[0], s[2]
        total_tc = rng.randint(40, 200)
        passed = int(total_tc * rng.uniform(0.65, 0.98))
        coverage = round(rng.uniform(45.0, 95.0), 1)
        regressions = rng.randint(0, 12)
        qa_rows.append({
            "sprint_id": s_id,
            "milestone_id": s_mid,
            "test_cases_total": total_tc,
            "test_cases_passed": passed,
            "test_coverage_pct": coverage,
            "regression_count": regressions,
        })

    chunk_size = max(1, math.ceil(len(qa_rows) / n_files))
    for idx in range(n_files):
        chunk = qa_rows[idx * chunk_size: (idx + 1) * chunk_size]
        fname = os.path.join(workspace, f"qa_report_{idx + 1}.csv")
        with open(fname, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "sprint_id", "milestone_id", "test_cases_total",
                "test_cases_passed", "test_coverage_pct", "regression_count"])
            w.writeheader()
            w.writerows(chunk)


def write_team_capacity_files(workspace, team_members, n_files):
    """Generate team capacity JSON files with effective capacity pct."""
    rng = random.Random(4243)
    members_data = []
    for tm in team_members:
        tid, tname, trole, tdept, thire, tdep, tstatus = tm
        if tstatus == "departed":
            cap = 0
        elif rng.random() < 0.2:
            cap = rng.choice([25, 40, 50, 60, 75])
        else:
            cap = 100
        members_data.append({
            "member_id": tid,
            "name": tname,
            "effective_capacity_pct": cap,
            "notes": "Full capacity" if cap == 100 else
                     ("Departed" if cap == 0 else "Partial allocation - shared with other projects"),
        })

    chunk_size = max(1, math.ceil(len(members_data) / n_files))
    for idx in range(n_files):
        chunk = members_data[idx * chunk_size: (idx + 1) * chunk_size]
        fname = os.path.join(workspace, f"team_capacity_{idx + 1}.json")
        with open(fname, "w") as f:
            json.dump({"report_date": "2026-04-15", "members": chunk}, f, indent=2)


def generate_workspace(workspace, milestones, sprints, team_members, deps):
    os.makedirs(workspace, exist_ok=True)
    nf = SCALE["num_workspace_files"]
    n_conf = (nf + 2) // 3
    n_qa = (nf + 1) // 3
    n_team = nf - n_conf - n_qa

    write_config_files(workspace)
    write_confluence_files(workspace, deps, milestones, n_conf)
    write_qa_files(workspace, sprints, n_qa)
    write_team_capacity_files(workspace, team_members, n_team)


# ====================================================================
# Main
# ====================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    milestones = generate_milestones(conn)
    team_members = generate_team_members(conn)
    sprints = generate_sprints(conn, milestones)
    stories = generate_stories(conn, sprints, team_members)
    bugs = generate_bugs(conn, milestones, sprints)
    assignments = generate_assignments(conn, milestones, team_members)
    deps = generate_dependencies(conn, milestones)

    conn.close()

    generate_workspace(args.workspace, milestones, sprints, team_members, deps)

    # Summary
    conn2 = sqlite3.connect(args.db_path)
    for tbl in ["milestones", "sprints", "stories", "bugs",
                "team_members", "milestone_assignments", "dependencies"]:
        cnt = conn2.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl}: {cnt} rows")
    conn2.close()
    wf = [f for f in os.listdir(args.workspace)]
    print(f"  workspace files: {len(wf)}")


if __name__ == "__main__":
    main()
