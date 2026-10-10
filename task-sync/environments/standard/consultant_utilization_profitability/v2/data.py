"""
Data generation for consultant utilization and project profitability analysis task.
"""

import argparse
import os
import sqlite3
import json
import csv
import datetime
import math
import numpy as np
import pandas as pd
from faker import Faker

try:
    import yaml
except ImportError:
    yaml = None

SCALE = {
    "rows_per_table": 160,
    "num_workspace_files": 30,
}

# ── Constants ──────────────────────────────────────────────────────────────────
ROLES = [
    "Junior Consultant", "Senior Consultant", "Manager",
    "Principal", "Analyst", "Specialist",
]
DEPARTMENTS = [
    "Strategy", "Technology", "Operations",
    "Finance", "Marketing", "Human Resources",
]
INDUSTRIES = [
    "Financial Services", "Healthcare", "Technology", "Retail",
    "Manufacturing", "Energy", "Telecommunications", "Media",
]
BILLING_TIERS = ["Platinum", "Gold", "Silver", "Bronze"]
SKILL_NAMES = [
    "Strategy", "Data Analysis", "Project Management", "Financial Modeling",
    "Change Management", "Digital Transformation", "Process Optimization",
    "Risk Management", "Cloud Architecture", "Stakeholder Engagement",
    "Business Intelligence", "Agile Methodology", "Supply Chain",
    "Cybersecurity", "Machine Learning", "UX Design",
]
PROJECT_STATUSES = ["active", "completed", "on_hold"]
BUDGET_CATEGORIES = ["Labor", "Travel", "Software", "Training", "Contingency", "Equipment"]

ANALYSIS_START = datetime.date(2025, 10, 6)  # Monday of week 1
ANALYSIS_WEEKS = 12

BASE_BILLING_RATES = {
    "Platinum": {
        "Junior Consultant": 180, "Senior Consultant": 280, "Manager": 380,
        "Principal": 480, "Analyst": 160, "Specialist": 300,
    },
    "Gold": {
        "Junior Consultant": 150, "Senior Consultant": 240, "Manager": 330,
        "Principal": 420, "Analyst": 135, "Specialist": 260,
    },
    "Silver": {
        "Junior Consultant": 120, "Senior Consultant": 200, "Manager": 280,
        "Principal": 360, "Analyst": 110, "Specialist": 220,
    },
    "Bronze": {
        "Junior Consultant": 95, "Senior Consultant": 165, "Manager": 230,
        "Principal": 300, "Analyst": 90, "Specialist": 180,
    },
}

COST_RANGES = {
    "Junior Consultant": (40, 65),
    "Senior Consultant": (70, 110),
    "Manager": (115, 160),
    "Principal": (165, 220),
    "Analyst": (35, 55),
    "Specialist": (90, 140),
}


# ── Generators ─────────────────────────────────────────────────────────────────

def generate_consultants(fake, n):
    rows = []
    for i in range(1, n + 1):
        role = ROLES[int(np.random.randint(0, len(ROLES)))]
        dept = DEPARTMENTS[int(np.random.randint(0, len(DEPARTMENTS)))]
        lo, hi = COST_RANGES[role]
        rows.append({
            "consultant_id": i,
            "name": fake.unique.name(),
            "role": role,
            "department": dept,
            "hourly_cost": round(float(np.random.uniform(lo, hi)), 2),
        })
    return rows


def generate_clients(fake, n):
    rows = []
    weights = [0.15, 0.30, 0.35, 0.20]
    for i in range(1, n + 1):
        rows.append({
            "client_id": i,
            "name": fake.unique.company(),
            "industry": INDUSTRIES[int(np.random.randint(0, len(INDUSTRIES)))],
            "billing_tier": str(np.random.choice(BILLING_TIERS, p=weights)),
        })
    return rows


def generate_projects(fake, n, clients):
    rows = []
    cids = [c["client_id"] for c in clients]
    for i in range(1, n + 1):
        cid = int(np.random.choice(cids))
        status = str(np.random.choice(PROJECT_STATUSES, p=[0.55, 0.30, 0.15]))
        start = ANALYSIS_START - datetime.timedelta(days=int(np.random.randint(30, 180)))
        end = ANALYSIS_START + datetime.timedelta(days=int(np.random.randint(60, 240)))
        budget = round(float(np.random.uniform(30000, 400000)), 2)
        rows.append({
            "project_id": i,
            "name": fake.catch_phrase(),
            "client_id": cid,
            "status": status,
            "start_date": str(start),
            "end_date": str(end),
            "total_budget": budget,
        })
    return rows


def generate_timesheets(consultants, projects):
    entries = []
    eid = 1
    pool = [p for p in projects if p["status"] in ("active", "completed")]
    if len(pool) < 3:
        pool = projects[: max(3, len(projects))]

    n = len(consultants)
    n_under = max(1, int(n * 0.30))
    n_over = max(1, int(n * 0.20))
    cats = ["under"] * n_under + ["normal"] * (n - n_under - n_over) + ["over"] * n_over
    np.random.shuffle(cats)

    for idx, c in enumerate(consultants):
        cat = cats[idx]
        if cat == "under":
            np_proj, mu, sigma = 1, 18, 4
        elif cat == "normal":
            np_proj, mu, sigma = min(int(np.random.randint(2, 4)), len(pool)), 35, 4
        else:
            np_proj, mu, sigma = min(int(np.random.randint(2, 4)), len(pool)), 46, 3

        assigned = np.random.choice(len(pool), size=np_proj, replace=False)
        for week in range(1, ANALYSIS_WEEKS + 1):
            total = max(0.0, float(np.random.normal(mu, sigma)))
            splits = (np.random.dirichlet(np.ones(np_proj)) * total) if np_proj > 1 else [total]
            for j, pi in enumerate(assigned):
                hrs = round(float(max(0, splits[j])), 1)
                if hrs < 0.5:
                    continue
                billable = 1 if np.random.random() > 0.12 else 0
                wk_start = ANALYSIS_START + datetime.timedelta(weeks=week - 1)
                work_date = wk_start + datetime.timedelta(days=int(np.random.randint(0, 5)))
                entries.append({
                    "entry_id": eid,
                    "consultant_id": c["consultant_id"],
                    "project_id": pool[pi]["project_id"],
                    "work_date": str(work_date),
                    "hours": hrs,
                    "is_billable": billable,
                })
                eid += 1
    return entries


def generate_skills(consultants, n_min):
    rows = []
    sid = 1
    for c in consultants:
        k = int(np.random.randint(2, 5))
        chosen = list(np.random.choice(SKILL_NAMES, size=k, replace=False))
        for s in chosen:
            rows.append({
                "skill_id": sid,
                "consultant_id": c["consultant_id"],
                "skill_name": str(s),
                "proficiency_level": int(np.random.randint(1, 6)),
            })
            sid += 1
    while len(rows) < n_min:
        c = consultants[int(np.random.randint(0, len(consultants)))]
        existing = {r["skill_name"] for r in rows if r["consultant_id"] == c["consultant_id"]}
        avail = [s for s in SKILL_NAMES if s not in existing]
        if not avail:
            continue
        rows.append({
            "skill_id": sid,
            "consultant_id": c["consultant_id"],
            "skill_name": str(np.random.choice(avail)),
            "proficiency_level": int(np.random.randint(1, 6)),
        })
        sid += 1
    return rows


def generate_budget_allocations(projects, n_min):
    rows = []
    aid = 1
    for p in projects:
        k = int(np.random.randint(2, 5))
        cats = list(np.random.choice(BUDGET_CATEGORIES, size=min(k, len(BUDGET_CATEGORIES)), replace=False))
        fracs = np.random.dirichlet(np.ones(len(cats)))
        for cat, f in zip(cats, fracs):
            rows.append({
                "alloc_id": aid,
                "project_id": p["project_id"],
                "category": str(cat),
                "allocated_amount": round(float(p["total_budget"] * f), 2),
            })
            aid += 1
    while len(rows) < n_min:
        p = projects[int(np.random.randint(0, len(projects)))]
        existing = {r["category"] for r in rows if r["project_id"] == p["project_id"]}
        avail = [c for c in BUDGET_CATEGORIES if c not in existing]
        if not avail:
            break
        rows.append({
            "alloc_id": aid,
            "project_id": p["project_id"],
            "category": str(np.random.choice(avail)),
            "allocated_amount": round(float(np.random.uniform(1000, 20000)), 2),
        })
        aid += 1
    return rows


# ── Database ───────────────────────────────────────────────────────────────────

def create_database(db_path, consultants, clients, projects, timesheets, skills, allocations):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""CREATE TABLE consultants (
        consultant_id INTEGER PRIMARY KEY, name TEXT, role TEXT,
        department TEXT, hourly_cost REAL)""")
    c.execute("""CREATE TABLE clients (
        client_id INTEGER PRIMARY KEY, name TEXT, industry TEXT, billing_tier TEXT)""")
    c.execute("""CREATE TABLE projects (
        project_id INTEGER PRIMARY KEY, name TEXT, client_id INTEGER,
        status TEXT, start_date TEXT, end_date TEXT, total_budget REAL,
        FOREIGN KEY (client_id) REFERENCES clients(client_id))""")
    c.execute("""CREATE TABLE timesheets (
        entry_id INTEGER PRIMARY KEY, consultant_id INTEGER, project_id INTEGER,
        work_date TEXT, hours REAL, is_billable INTEGER,
        FOREIGN KEY (consultant_id) REFERENCES consultants(consultant_id),
        FOREIGN KEY (project_id) REFERENCES projects(project_id))""")
    c.execute("""CREATE TABLE consultant_skills (
        skill_id INTEGER PRIMARY KEY, consultant_id INTEGER,
        skill_name TEXT, proficiency_level INTEGER,
        FOREIGN KEY (consultant_id) REFERENCES consultants(consultant_id))""")
    c.execute("""CREATE TABLE budget_allocations (
        alloc_id INTEGER PRIMARY KEY, project_id INTEGER,
        category TEXT, allocated_amount REAL,
        FOREIGN KEY (project_id) REFERENCES projects(project_id))""")

    for r in consultants:
        c.execute("INSERT INTO consultants VALUES (?,?,?,?,?)",
                  (r["consultant_id"], r["name"], r["role"], r["department"], r["hourly_cost"]))
    for r in clients:
        c.execute("INSERT INTO clients VALUES (?,?,?,?)",
                  (r["client_id"], r["name"], r["industry"], r["billing_tier"]))
    for r in projects:
        c.execute("INSERT INTO projects VALUES (?,?,?,?,?,?,?)",
                  (r["project_id"], r["name"], r["client_id"], r["status"],
                   r["start_date"], r["end_date"], r["total_budget"]))
    for r in timesheets:
        c.execute("INSERT INTO timesheets VALUES (?,?,?,?,?,?)",
                  (r["entry_id"], r["consultant_id"], r["project_id"],
                   r["work_date"], r["hours"], r["is_billable"]))
    for r in skills:
        c.execute("INSERT INTO consultant_skills VALUES (?,?,?,?)",
                  (r["skill_id"], r["consultant_id"], r["skill_name"], r["proficiency_level"]))
    for r in allocations:
        c.execute("INSERT INTO budget_allocations VALUES (?,?,?,?)",
                  (r["alloc_id"], r["project_id"], r["category"], r["allocated_amount"]))
    conn.commit()
    conn.close()


# ── Workspace ──────────────────────────────────────────────────────────────────

def _write_yaml(filepath, data):
    """Write data as YAML."""
    if yaml is not None:
        with open(filepath, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    else:
        with open(filepath, "w") as f:
            _yaml_ser(f, data, 0)


def _yaml_ser(f, obj, indent):
    pfx = "  " * indent
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                f.write(f"{pfx}{k}:\n")
                _yaml_ser(f, v, indent + 1)
            elif v is None:
                f.write(f"{pfx}{k}: null\n")
            elif isinstance(v, bool):
                f.write(f"{pfx}{k}: {'true' if v else 'false'}\n")
            elif isinstance(v, str):
                if any(c in v for c in ":#{}[]&*?|>!%@`"):
                    f.write(f"{pfx}{k}: '{v}'\n")
                else:
                    f.write(f"{pfx}{k}: {v}\n")
            else:
                f.write(f"{pfx}{k}: {v}\n")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                f.write(f"{pfx}-\n")
                _yaml_ser(f, item, indent + 1)
            else:
                f.write(f"{pfx}- {item}\n")


def create_workspace(workspace, fake, consultants, clients, projects, n_files):
    os.makedirs(workspace, exist_ok=True)

    # ── Fixed config files (not counted in SCALE) ─────────────────────────────

    # 1. billing_rate_tiers.yaml
    _write_yaml(os.path.join(workspace, "billing_rate_tiers.yaml"), BASE_BILLING_RATES)

    # 2. utilization_thresholds.yaml
    _write_yaml(os.path.join(workspace, "utilization_thresholds.yaml"), {
        "underutilized_threshold": 0.60,
        "overutilized_threshold": 0.95,
        "target_utilization_min": 0.70,
        "target_utilization_max": 0.90,
        "analysis_period_weeks": ANALYSIS_WEEKS,
    })

    # 3. overservicing_rules.json
    with open(os.path.join(workspace, "overservicing_rules.json"), "w") as f:
        json.dump({
            "budget_overrun_threshold_pct": 15,
            "flag_if_total_cost_exceeds_budget_by_threshold": True,
        }, f, indent=2)

    # 4. skill_demand_weights.json
    with open(os.path.join(workspace, "skill_demand_weights.json"), "w") as f:
        json.dump({s: round(float(np.random.uniform(0.5, 2.0)), 2) for s in SKILL_NAMES}, f, indent=2)

    # 5. reallocation_constraints.txt
    with open(os.path.join(workspace, "reallocation_constraints.txt"), "w") as f:
        f.write("Reallocation Policy Constraints\n")
        f.write("=" * 40 + "\n\n")
        f.write("1. A consultant may be assigned to at most 3 projects simultaneously.\n")
        f.write("2. Reallocation is only permitted for consultants classified as underutilized.\n")
        f.write("3. Target projects for reallocation must have status 'active'.\n")
        f.write("4. The consultant must possess at least one skill required by the target project "
                "with proficiency >= 3.\n")
        f.write("5. Recommended weekly hours must not push the consultant's projected utilization "
                "above the overutilized threshold.\n")
        f.write("6. Maximum recommended weekly hours per reallocation entry: 20 hours.\n")
        f.write("7. Priority should be given to over-serviced active projects as targets.\n")
        f.write("8. Projected utilization after all reallocations is computed as:\n")
        f.write("   (current total_hours_worked + sum of recommended_weekly_hours * "
                "analysis_period_weeks) / total_available_hours\n")

    # ── Scalable data files ───────────────────────────────────────────────────

    n_capacity = max(1, n_files * 4 // 10)   # ~40 %
    n_proj_req = max(1, n_files * 3 // 10)   # ~30 %
    n_rate_card = n_files - n_capacity - n_proj_req  # ~30 %

    # — consultant_capacity_{i}.csv —
    per = max(1, len(consultants) // n_capacity)
    for i in range(n_capacity):
        s = i * per
        e = s + per if i < n_capacity - 1 else len(consultants)
        batch = consultants[s:e]
        fp = os.path.join(workspace, f"consultant_capacity_{i + 1}.csv")
        with open(fp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["consultant_id", "consultant_name", "week_number", "target_hours", "notes"])
            for c in batch:
                for wk in range(1, ANALYSIS_WEEKS + 1):
                    if np.random.random() < 0.15:
                        th = int(np.random.choice([20, 24, 30, 32, 36]))
                        note = str(np.random.choice([
                            "partial leave", "training", "internal project", "reduced schedule"]))
                    else:
                        th = 40
                        note = ""
                    w.writerow([c["consultant_id"], c["name"], wk, th, note])

    # — project_requirements_{i}.json —
    per = max(1, len(projects) // n_proj_req)
    for i in range(n_proj_req):
        s = i * per
        e = s + per if i < n_proj_req - 1 else len(projects)
        batch = projects[s:e]
        reqs = []
        for p in batch:
            k = int(np.random.randint(2, 5))
            reqs.append({
                "project_id": p["project_id"],
                "project_name": p["name"],
                "required_skills": [str(x) for x in np.random.choice(SKILL_NAMES, size=k, replace=False)],
                "priority_score": int(np.random.randint(1, 11)),
                "min_proficiency_required": 3,
            })
        with open(os.path.join(workspace, f"project_requirements_{i + 1}.json"), "w") as f:
            json.dump(reqs, f, indent=2)

    # — client_rate_card_{i}.yaml —
    per = max(1, len(clients) // n_rate_card)
    for i in range(n_rate_card):
        s = i * per
        e = s + per if i < n_rate_card - 1 else len(clients)
        batch = clients[s:e]
        cards = {}
        for cl in batch:
            tier = cl["billing_tier"]
            base = BASE_BILLING_RATES[tier]
            if np.random.random() < 0.30:
                custom = {}
                for role, rate in base.items():
                    custom[role] = round(rate * float(np.random.uniform(0.85, 0.98)), 2)
                cards[cl["client_id"]] = {
                    "client_name": cl["name"],
                    "base_tier": tier,
                    "negotiated_rates": custom,
                    "rate_type": "custom",
                }
            else:
                cards[cl["client_id"]] = {
                    "client_name": cl["name"],
                    "base_tier": tier,
                    "negotiated_rates": None,
                    "rate_type": "standard",
                }
        _write_yaml(os.path.join(workspace, f"client_rate_card_{i + 1}.yaml"), cards)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    Faker.seed(42)
    np.random.seed(42)
    fake = Faker()

    n = SCALE["rows_per_table"]

    consultants = generate_consultants(fake, n)
    clients = generate_clients(fake, n)
    projects = generate_projects(fake, n, clients)
    timesheets = generate_timesheets(consultants, projects)
    skills = generate_skills(consultants, n)
    allocations = generate_budget_allocations(projects, n)

    create_database(args.db_path, consultants, clients, projects, timesheets, skills, allocations)
    create_workspace(args.workspace, fake, consultants, clients, projects, SCALE["num_workspace_files"])

    print(f"Consultants: {len(consultants)}, Clients: {len(clients)}, Projects: {len(projects)}")
    print(f"Timesheets: {len(timesheets)}, Skills: {len(skills)}, Allocations: {len(allocations)}")


if __name__ == "__main__":
    main()
