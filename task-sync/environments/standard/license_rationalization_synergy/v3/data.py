"""
Data generation script for the Software License Rationalization task.
Generates database tables and workspace files for a post-merger SaaS
subscription consolidation analysis between two companies.
"""

import argparse
import sqlite3
import os
import json
import yaml
import csv
import random
import math
from datetime import date, datetime
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 320,
    "num_workspace_files": 40,
}

# ── Constants ────────────────────────────────────────────────────────────────

COMPANY_A = "Apex Digital"
COMPANY_B = "Nexus Technologies"

DIRECT_OVERLAPS = [
    {"software_name": "Salesforce CRM", "vendor": "Salesforce Inc.", "category": "CRM"},
    {"software_name": "Google Workspace", "vendor": "Google LLC", "category": "Productivity"},
    {"software_name": "Workday HCM", "vendor": "Workday Inc.", "category": "HR"},
    {"software_name": "GitHub Enterprise", "vendor": "Microsoft Corp.", "category": "Development"},
]

EQUIVALENT_OVERLAPS = [
    {
        "a": {"software_name": "Jira", "vendor": "Atlassian", "category": "Project Management"},
        "b": {"software_name": "Asana", "vendor": "Asana Inc.", "category": "Project Management"},
    },
    {
        "a": {"software_name": "Slack", "vendor": "Salesforce Inc.", "category": "Communication"},
        "b": {"software_name": "Microsoft Teams", "vendor": "Microsoft Corp.", "category": "Communication"},
    },
    {
        "a": {"software_name": "QuickBooks Enterprise", "vendor": "Intuit Inc.", "category": "Accounting"},
        "b": {"software_name": "Xero Business", "vendor": "Xero Ltd.", "category": "Accounting"},
    },
    {
        "a": {"software_name": "Tableau", "vendor": "Salesforce Inc.", "category": "Analytics"},
        "b": {"software_name": "Power BI Pro", "vendor": "Microsoft Corp.", "category": "Analytics"},
    },
]

UNIQUE_PRODUCTS = [
    {"software_name": "Zoom Workplace", "vendor": "Zoom Video Communications", "category": "Communication"},
    {"software_name": "Dropbox Business", "vendor": "Dropbox Inc.", "category": "Cloud Storage"},
    {"software_name": "Box Enterprise", "vendor": "Box Inc.", "category": "Cloud Storage"},
    {"software_name": "BambooHR", "vendor": "BambooHR LLC", "category": "HR"},
    {"software_name": "SAP SuccessFactors", "vendor": "SAP SE", "category": "HR"},
    {"software_name": "NetSuite ERP", "vendor": "Oracle Corp.", "category": "ERP"},
    {"software_name": "CrowdStrike Falcon", "vendor": "CrowdStrike Inc.", "category": "Security"},
    {"software_name": "Okta Identity", "vendor": "Okta Inc.", "category": "Security"},
    {"software_name": "Palo Alto Prisma", "vendor": "Palo Alto Networks", "category": "Security"},
    {"software_name": "Looker", "vendor": "Google LLC", "category": "Analytics"},
    {"software_name": "Figma Enterprise", "vendor": "Figma Inc.", "category": "Design"},
    {"software_name": "Adobe Creative Cloud", "vendor": "Adobe Inc.", "category": "Design"},
    {"software_name": "Sketch Business", "vendor": "Sketch B.V.", "category": "Design"},
    {"software_name": "GitLab Ultimate", "vendor": "GitLab Inc.", "category": "Development"},
    {"software_name": "Bitbucket Cloud", "vendor": "Atlassian", "category": "Development"},
    {"software_name": "Confluence", "vendor": "Atlassian", "category": "Documentation"},
    {"software_name": "Notion Enterprise", "vendor": "Notion Labs", "category": "Documentation"},
    {"software_name": "DocuSign", "vendor": "DocuSign Inc.", "category": "Legal Tech"},
    {"software_name": "Zendesk", "vendor": "Zendesk Inc.", "category": "Customer Support"},
    {"software_name": "Freshdesk", "vendor": "Freshworks Inc.", "category": "Customer Support"},
    {"software_name": "Snowflake", "vendor": "Snowflake Inc.", "category": "Data Platform"},
    {"software_name": "Databricks", "vendor": "Databricks Inc.", "category": "Data Platform"},
    {"software_name": "Splunk Enterprise", "vendor": "Cisco Systems", "category": "Monitoring"},
    {"software_name": "Datadog", "vendor": "Datadog Inc.", "category": "Monitoring"},
]

CATEGORY_PRICE_RANGE = {
    "CRM": (120, 350),
    "Project Management": (80, 250),
    "Communication": (50, 150),
    "Productivity": (60, 200),
    "Cloud Storage": (40, 120),
    "HR": (130, 400),
    "Accounting": (100, 350),
    "Security": (80, 300),
    "Analytics": (100, 400),
    "Design": (80, 300),
    "Development": (80, 350),
    "ERP": (150, 450),
    "Documentation": (40, 120),
    "Legal Tech": (60, 200),
    "Customer Support": (60, 200),
    "Data Platform": (120, 400),
    "Monitoring": (80, 280),
    "Collaboration": (40, 150),
    "Automation": (60, 250),
    "Compliance": (80, 300),
    "Marketing": (70, 250),
    "Supply Chain": (100, 350),
    "Testing": (60, 200),
    "Backup": (40, 150),
    "Networking": (50, 180),
    "BI": (90, 320),
    "Integration": (70, 230),
    "Governance": (80, 280),
    "Scheduling": (30, 100),
    "Task Management": (40, 130),
}

DEPARTMENT_NAMES = [
    "Engineering", "Sales", "Marketing", "Finance", "Human Resources",
    "Operations", "Legal", "Customer Support", "Product Management", "Data Science",
    "DevOps", "Quality Assurance", "Business Development", "Research", "Information Technology",
    "Compliance", "Procurement", "Training", "Design", "Strategy",
    "Facilities", "Public Relations", "Internal Audit", "Supply Chain", "Investor Relations",
    "Security Operations", "Analytics", "Content", "Partnerships", "Growth",
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _generate_extra_products(n, rng):
    """Generate additional unique software products for larger scales."""
    categories = [
        "CRM", "HR", "Analytics", "Security", "Development",
        "Compliance", "Marketing", "ERP", "Supply Chain", "BI",
        "Testing", "Monitoring", "Backup", "Networking", "Collaboration",
        "Automation", "Integration", "Governance",
    ]
    prefixes = [
        "Alpha", "Beta", "Gamma", "Delta", "Sigma", "Omega",
        "Nova", "Apex", "Core", "Prime", "Ultra", "Zeta",
        "Quantum", "Stellar", "Vertex", "Zenith", "Pulse", "Flux",
        "Arc", "Helix", "Cipher", "Vortex", "Nimbus", "Stratos",
    ]
    suffixes = [
        "Pro", "Enterprise", "Cloud", "Plus", "360",
        "Max", "Elite", "Suite", "Hub", "One",
    ]

    products = []
    used_names = set()
    idx = 0
    while len(products) < n:
        c_i = idx % len(categories)
        p_i = (idx // len(categories)) % len(prefixes)
        s_i = (idx // (len(categories) * len(prefixes))) % len(suffixes)
        cat = categories[c_i]
        name = f"{prefixes[p_i]}{suffixes[s_i]} {cat}"
        if name not in used_names:
            used_names.add(name)
            vendor = f"{prefixes[p_i]} Software Inc."
            products.append({"software_name": name, "vendor": vendor, "category": cat})
        idx += 1
    return products[:n]


def _generate_dept_names(n):
    """Generate n department names, extending beyond the base pool if needed."""
    if n <= len(DEPARTMENT_NAMES):
        return DEPARTMENT_NAMES[:n]
    names = list(DEPARTMENT_NAMES)
    sub_units = [
        "Team Alpha", "Team Beta", "Team Gamma", "Team Delta",
        "Division I", "Division II", "Division III",
        "Group A", "Group B", "Group C", "Group D",
        "Unit 1", "Unit 2", "Unit 3", "Unit 4",
    ]
    idx = 0
    while len(names) < n:
        base = DEPARTMENT_NAMES[idx % len(DEPARTMENT_NAMES)]
        sub = sub_units[idx // len(DEPARTMENT_NAMES) % len(sub_units)]
        candidate = f"{base} - {sub}"
        if candidate not in names:
            names.append(candidate)
        idx += 1
    return names[:n]


def _price_for_category(category, rng):
    """Generate a per-seat annual price for a software category."""
    lo, hi = CATEGORY_PRICE_RANGE.get(category, (50, 250))
    return round(rng.uniform(lo, hi), 2)


# ── Main ─────────────────────────────────────────────────────────────────────

def main(db_path, workspace):
    os.makedirs(workspace, exist_ok=True)

    fake = Faker()
    Faker.seed(42)
    random.seed(42)
    np.random.seed(42)
    rng = random.Random(42)

    rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ── 1. Departments ───────────────────────────────────────────────────
    n_depts = max(rows, 20)  # at least 20 to ensure meaningful departments
    n_per_company = n_depts // 2
    dept_pool = _generate_dept_names(n_per_company)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY,
            name TEXT,
            company TEXT,
            location TEXT,
            cost_center TEXT
        )
    """)

    departments = []
    dept_id = 1
    company_locations = {
        COMPANY_A: [fake.city() for _ in range(5)],
        COMPANY_B: [fake.city() for _ in range(5)],
    }
    for company in [COMPANY_A, COMPANY_B]:
        for i in range(n_per_company):
            dept = {
                "id": dept_id,
                "name": dept_pool[i],
                "company": company,
                "location": rng.choice(company_locations[company]),
                "cost_center": f"CC-{company[:3].upper()}-{dept_id:04d}",
            }
            departments.append(dept)
            dept_id += 1

    for d in departments:
        cur.execute(
            "INSERT INTO departments VALUES (?,?,?,?,?)",
            (d["id"], d["name"], d["company"], d["location"], d["cost_center"]),
        )

    # ── 2. Employees ─────────────────────────────────────────────────────
    n_employees = max(rows, len(departments) * 3)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY,
            name TEXT,
            email TEXT,
            department_id INTEGER,
            company TEXT,
            role TEXT,
            hire_date TEXT,
            is_active INTEGER,
            employment_type TEXT,
            FOREIGN KEY (department_id) REFERENCES departments(id)
        )
    """)

    roles = [
        "Software Engineer", "Senior Engineer", "Manager", "Director",
        "Analyst", "Specialist", "Coordinator", "Associate", "Lead",
        "Architect", "Consultant", "Administrator", "Technician",
    ]
    emp_types_weights = [("full-time", 0.75), ("part-time", 0.15), ("contractor", 0.10)]
    emp_type_vals = [t for t, _ in emp_types_weights]
    emp_type_wts = [w for _, w in emp_types_weights]

    depts_by_company = {}
    for d in departments:
        depts_by_company.setdefault(d["company"], []).append(d)

    employees = []
    for emp_id in range(1, n_employees + 1):
        company = COMPANY_A if emp_id % 2 == 1 else COMPANY_B
        dept = rng.choice(depts_by_company[company])
        emp = {
            "id": emp_id,
            "name": fake.name(),
            "email": fake.email(),
            "department_id": dept["id"],
            "company": company,
            "role": rng.choice(roles),
            "hire_date": fake.date_between(start_date="-10y", end_date="-30d").isoformat(),
            "is_active": 1 if rng.random() > 0.05 else 0,
            "employment_type": rng.choices(emp_type_vals, weights=emp_type_wts, k=1)[0],
        }
        employees.append(emp)

    for e in employees:
        cur.execute(
            "INSERT INTO employees VALUES (?,?,?,?,?,?,?,?,?)",
            (e["id"], e["name"], e["email"], e["department_id"],
             e["company"], e["role"], e["hire_date"], e["is_active"],
             e["employment_type"]),
        )

    # ── 3. Software contracts ────────────────────────────────────────────
    n_contracts = max(rows, 20)
    n_per_company = n_contracts // 2

    overlap_count = len(DIRECT_OVERLAPS) + len(EQUIVALENT_OVERLAPS)  # 8
    unique_needed_per_company = n_per_company - overlap_count

    # Build unique product list
    unique_pool = list(UNIQUE_PRODUCTS)
    if len(unique_pool) < unique_needed_per_company * 2:
        extra = _generate_extra_products(
            unique_needed_per_company * 2 - len(unique_pool), rng
        )
        unique_pool.extend(extra)
    rng.shuffle(unique_pool)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS software_contracts (
            id INTEGER PRIMARY KEY,
            software_name TEXT,
            vendor TEXT,
            category TEXT,
            company TEXT,
            price_per_seat REAL,
            total_seats INTEGER,
            annual_cost REAL,
            contract_start TEXT,
            contract_end TEXT
        )
    """)

    contracts = []
    contract_id = 1

    active_emp_a = [e for e in employees if e["company"] == COMPANY_A and e["is_active"]]
    active_emp_b = [e for e in employees if e["company"] == COMPANY_B and e["is_active"]]

    def _make_contract(prod, company, cid, active_emps):
        price = _price_for_category(prod["category"], rng)
        seats = max(5, int(len(active_emps) * rng.uniform(0.15, 0.45)))
        return {
            "id": cid,
            "software_name": prod["software_name"],
            "vendor": prod["vendor"],
            "category": prod["category"],
            "company": company,
            "price_per_seat": price,
            "total_seats": seats,
            "annual_cost": round(price * seats, 2),
            "contract_start": fake.date_between(start_date="-3y", end_date="-1y").isoformat(),
            "contract_end": fake.date_between(start_date="+3m", end_date="+2y").isoformat(),
        }

    # Direct overlaps
    for prod in DIRECT_OVERLAPS:
        c_a = _make_contract(prod, COMPANY_A, contract_id, active_emp_a)
        contract_id += 1
        c_b = _make_contract(prod, COMPANY_B, contract_id, active_emp_b)
        contract_id += 1
        # Ensure prices differ so there's a clear winner
        if c_a["price_per_seat"] == c_b["price_per_seat"]:
            c_b["price_per_seat"] = round(c_b["price_per_seat"] * 1.05, 2)
            c_b["annual_cost"] = round(c_b["price_per_seat"] * c_b["total_seats"], 2)
        contracts.extend([c_a, c_b])

    # Equivalent overlaps
    for pair in EQUIVALENT_OVERLAPS:
        c_a = _make_contract(pair["a"], COMPANY_A, contract_id, active_emp_a)
        contract_id += 1
        c_b = _make_contract(pair["b"], COMPANY_B, contract_id, active_emp_b)
        contract_id += 1
        if c_a["price_per_seat"] == c_b["price_per_seat"]:
            c_b["price_per_seat"] = round(c_b["price_per_seat"] * 0.95, 2)
            c_b["annual_cost"] = round(c_b["price_per_seat"] * c_b["total_seats"], 2)
        contracts.extend([c_a, c_b])

    # Unique products
    unique_a = unique_pool[:unique_needed_per_company]
    unique_b = unique_pool[unique_needed_per_company: unique_needed_per_company * 2]

    for prod in unique_a:
        c = _make_contract(prod, COMPANY_A, contract_id, active_emp_a)
        contracts.append(c)
        contract_id += 1
    for prod in unique_b:
        c = _make_contract(prod, COMPANY_B, contract_id, active_emp_b)
        contracts.append(c)
        contract_id += 1

    for c in contracts:
        cur.execute(
            "INSERT INTO software_contracts VALUES (?,?,?,?,?,?,?,?,?,?)",
            (c["id"], c["software_name"], c["vendor"], c["category"],
             c["company"], c["price_per_seat"], c["total_seats"],
             c["annual_cost"], c["contract_start"], c["contract_end"]),
        )

    # ── 4. License assignments ───────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS license_assignments (
            id INTEGER PRIMARY KEY,
            employee_id INTEGER,
            contract_id INTEGER,
            is_active INTEGER,
            assigned_date TEXT,
            FOREIGN KEY (employee_id) REFERENCES employees(id),
            FOREIGN KEY (contract_id) REFERENCES software_contracts(id)
        )
    """)

    contracts_by_company = {}
    for c in contracts:
        contracts_by_company.setdefault(c["company"], []).append(c)

    assignments = []
    assign_id = 1
    emp_contract_pairs = set()

    for company in [COMPANY_A, COMPANY_B]:
        comp_employees = [e for e in employees if e["company"] == company and e["is_active"]]
        comp_contracts = contracts_by_company.get(company, [])

        for cont in comp_contracts:
            n_assign = min(cont["total_seats"], len(comp_employees))
            chosen = rng.sample(comp_employees, n_assign)
            for emp in chosen:
                pair = (emp["id"], cont["id"])
                if pair in emp_contract_pairs:
                    continue
                emp_contract_pairs.add(pair)
                a = {
                    "id": assign_id,
                    "employee_id": emp["id"],
                    "contract_id": cont["id"],
                    "is_active": 1,
                    "assigned_date": fake.date_between(
                        start_date=date.fromisoformat(cont["contract_start"]),
                        end_date="today",
                    ).isoformat(),
                }
                assignments.append(a)
                assign_id += 1

    # Ensure license_assignments has >= rows
    assert len(assignments) >= rows, (
        f"Only {len(assignments)} assignments generated, need >= {rows}"
    )

    for a in assignments:
        cur.execute(
            "INSERT INTO license_assignments VALUES (?,?,?,?,?)",
            (a["id"], a["employee_id"], a["contract_id"],
             a["is_active"], a["assigned_date"]),
        )

    # ── 5. Access logs ───────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS access_logs (
            id INTEGER PRIMARY KEY,
            employee_id INTEGER,
            contract_id INTEGER,
            sessions_30d INTEGER,
            avg_duration_min REAL,
            last_access_date TEXT,
            FOREIGN KEY (employee_id) REFERENCES employees(id),
            FOREIGN KEY (contract_id) REFERENCES software_contracts(id)
        )
    """)

    access_logs = []
    log_id = 1
    for a in assignments:
        # ~80% of assigned users have some access, 20% have zero
        if rng.random() < 0.80:
            sessions = max(1, int(rng.gauss(12, 6)))
            avg_dur = round(rng.uniform(5, 90), 1)
            last_date = fake.date_between(start_date="-30d", end_date="today").isoformat()
        else:
            sessions = 0
            avg_dur = 0.0
            last_date = fake.date_between(start_date="-180d", end_date="-31d").isoformat()

        log = {
            "id": log_id,
            "employee_id": a["employee_id"],
            "contract_id": a["contract_id"],
            "sessions_30d": sessions,
            "avg_duration_min": avg_dur,
            "last_access_date": last_date,
        }
        access_logs.append(log)
        log_id += 1

    for lg in access_logs:
        cur.execute(
            "INSERT INTO access_logs VALUES (?,?,?,?,?,?)",
            (lg["id"], lg["employee_id"], lg["contract_id"],
             lg["sessions_30d"], lg["avg_duration_min"], lg["last_access_date"]),
        )

    conn.commit()

    # ── 6. Workspace files ───────────────────────────────────────────────

    # --- Fixed files ---

    # 6a. software_equivalence.yaml
    equiv_data = {
        "description": "Mapping of functionally equivalent software products across companies.",
        "equivalences": [],
    }
    for pair in EQUIVALENT_OVERLAPS:
        equiv_data["equivalences"].append({
            "software_1": pair["a"]["software_name"],
            "company_1": COMPANY_A,
            "software_2": pair["b"]["software_name"],
            "company_2": COMPANY_B,
            "category": pair["a"]["category"],
        })
    with open(os.path.join(workspace, "software_equivalence.yaml"), "w") as f:
        yaml.dump(equiv_data, f, default_flow_style=False, sort_keys=False)

    # 6b. rationalization_rules.yaml
    rules = {
        "underutilization_threshold": {
            "min_sessions_30d": 3,
            "description": "Employees with fewer than this many sessions in the past 30 days are considered underutilized.",
        },
        "eligible_employment_types": ["full-time"],
        "employment_type_note": "Only employees with these employment types should be counted toward consolidated seat allocations.",
        "retention_decision": {
            "primary_rule": "Retain the contract with the lower price_per_seat.",
            "tie_breaker": "If price_per_seat is identical, retain the contract with more total_seats.",
            "second_tie_breaker": "If still tied, retain the contract whose software_name comes first alphabetically.",
        },
    }
    with open(os.path.join(workspace, "rationalization_rules.yaml"), "w") as f:
        yaml.dump(rules, f, default_flow_style=False, sort_keys=False)

    # 6c. vendor_discounts.json
    all_vendors = sorted(set(c["vendor"] for c in contracts))
    vendor_discounts = {}
    for vendor in all_vendors:
        base_disc = rng.choice([3, 5, 7, 8, 10])
        vendor_discounts[vendor] = [
            {"min_seats": 1, "max_seats": 50, "discount_pct": 0},
            {"min_seats": 51, "max_seats": 150, "discount_pct": base_disc},
            {"min_seats": 151, "max_seats": 300, "discount_pct": base_disc + rng.choice([3, 5])},
            {"min_seats": 301, "max_seats": 999999, "discount_pct": base_disc + rng.choice([7, 10, 12])},
        ]
    with open(os.path.join(workspace, "vendor_discounts.json"), "w") as f:
        json.dump(vendor_discounts, f, indent=2)

    # --- Scaling files ---
    n_access_files = int(round(n_files * 0.7))
    n_roster_files = n_files - n_access_files

    # 6d. access_log_*.csv  — per-user access data (only users with >=1 session)
    # Workspace access logs include ONLY users with sessions > 0.
    # Users with 0 sessions are in the DB but NOT in workspace files.
    active_access = [lg for lg in access_logs if lg["sessions_30d"] > 0]
    emp_by_id = {e["id"]: e for e in employees}
    contract_by_id = {c["id"]: c for c in contracts}

    # Shuffle then split into n_access_files batches
    rng.shuffle(active_access)
    batch_size_acc = max(1, math.ceil(len(active_access) / n_access_files))
    for file_idx in range(n_access_files):
        batch = active_access[file_idx * batch_size_acc: (file_idx + 1) * batch_size_acc]
        fname = f"access_log_{file_idx + 1:03d}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "employee_id", "employee_name", "contract_id",
                "software_name", "sessions_30d", "avg_duration_min",
                "last_access_date",
            ])
            for lg in batch:
                emp = emp_by_id[lg["employee_id"]]
                cont = contract_by_id[lg["contract_id"]]
                writer.writerow([
                    lg["employee_id"], emp["name"], lg["contract_id"],
                    cont["software_name"], lg["sessions_30d"],
                    lg["avg_duration_min"], lg["last_access_date"],
                ])

    # 6e. employee_roster_*.md  — employee details with employment_type
    # employment_type is NOT exposed by any tool; roster files are the only source.
    rng_emps = list(employees)
    rng.shuffle(rng_emps)
    batch_size_ros = max(1, math.ceil(len(rng_emps) / n_roster_files))
    for file_idx in range(n_roster_files):
        batch = rng_emps[file_idx * batch_size_ros: (file_idx + 1) * batch_size_ros]
        fname = f"employee_roster_{file_idx + 1:03d}.md"
        lines = [f"# Employee Roster - Batch {file_idx + 1}", ""]
        lines.append("| employee_id | name | department | company | employment_type |")
        lines.append("|---|---|---|---|---|")
        for emp in batch:
            dept_name = next(d["name"] for d in departments if d["id"] == emp["department_id"])
            lines.append(
                f"| {emp['id']} | {emp['name']} | {dept_name} "
                f"| {emp['company']} | {emp['employment_type']} |"
            )
        with open(os.path.join(workspace, fname), "w") as f:
            f.write("\n".join(lines) + "\n")

    conn.close()
    print(f"Database created at {db_path}")
    print(f"Workspace files created in {workspace}/")
    print(f"  Tables: departments({len(departments)}), employees({len(employees)}), "
          f"software_contracts({len(contracts)}), license_assignments({len(assignments)}), "
          f"access_logs({len(access_logs)})")
    ws_files = os.listdir(workspace)
    print(f"  Workspace files: {len(ws_files)} total ({n_access_files} access logs, "
          f"{n_roster_files} rosters, 3 config)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
