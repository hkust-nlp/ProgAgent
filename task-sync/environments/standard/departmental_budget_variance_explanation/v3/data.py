"""Budget Variance Analysis - Data Generation Script."""
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

SCALE = {
    "rows_per_table": 640,
    "num_workspace_files": 32,
}

# ---------------------------------------------------------------------------
# Fixed reference lists (do NOT scale)
# ---------------------------------------------------------------------------
DEPARTMENTS = [
    "Finance", "Engineering", "Marketing", "Sales",
    "Human Resources", "Operations", "Legal", "Research",
]

CATEGORIES = [
    "Personnel", "Software Licenses", "Hardware", "Travel",
    "Consulting", "Office Supplies", "Training", "Advertising",
    "Facilities", "Miscellaneous",
]

PO_STATUSES = ["Open", "Closed", "Cancelled"]
MILESTONE_STATUSES = ["Completed", "Pending", "Cancelled"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_into_n(items, n):
    """Split a list into n roughly-equal chunks."""
    k, m = divmod(len(items), n)
    chunks = []
    idx = 0
    for i in range(n):
        size = k + (1 if i < m else 0)
        chunks.append(items[idx:idx + size])
        idx += size
    return chunks


def _random_date(fake, year=2025):
    """Return a random date string in *year*."""
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    return f"{year}-{month:02d}-{day:02d}"


# ===================================================================
# Database
# ===================================================================

def create_tables(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS budget_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department TEXT NOT NULL,
            category TEXT NOT NULL,
            fiscal_year INTEGER NOT NULL,
            annual_budget REAL NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS gl_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department TEXT NOT NULL,
            category TEXT NOT NULL,
            entry_date TEXT NOT NULL,
            amount REAL NOT NULL,
            vendor TEXT,
            description TEXT,
            reference_no TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department TEXT NOT NULL,
            category TEXT NOT NULL,
            vendor TEXT NOT NULL,
            po_number TEXT NOT NULL,
            po_date TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL,
            project_name TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS invoice_line_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT NOT NULL,
            vendor TEXT NOT NULL,
            department TEXT NOT NULL,
            category TEXT NOT NULL,
            line_description TEXT,
            amount REAL NOT NULL,
            invoice_date TEXT NOT NULL,
            po_number TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS project_milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            department TEXT NOT NULL,
            category TEXT NOT NULL,
            milestone_name TEXT NOT NULL,
            planned_date TEXT NOT NULL,
            forecast_amount REAL NOT NULL,
            status TEXT NOT NULL
        )
    """)
    conn.commit()


# ===================================================================
# Data generation
# ===================================================================

def generate_data(conn, fake, scale):
    rpt = scale["rows_per_table"]
    c = conn.cursor()

    # ------------------------------------------------------------------
    # 1. Budget allocations  (>= rpt rows)
    # ------------------------------------------------------------------
    # Build all possible (dept, cat) combos, shuffle, take rpt
    all_combos = [(d, cat) for d in DEPARTMENTS for cat in CATEGORIES]
    random.shuffle(all_combos)
    budget_combos = all_combos[:rpt]

    budget_rows = []
    for dept, cat in budget_combos:
        annual = round(random.uniform(50_000, 500_000), 2)
        budget_rows.append((dept, cat, 2025, annual))
    c.executemany(
        "INSERT INTO budget_allocations (department, category, fiscal_year, annual_budget) VALUES (?,?,?,?)",
        budget_rows,
    )

    # ------------------------------------------------------------------
    # 2. Vendors (used across POs, invoices, GL)
    # ------------------------------------------------------------------
    n_vendors = max(20, rpt // 4)
    vendors = list(dict.fromkeys(fake.company() for _ in range(n_vendors * 2)))[:n_vendors]

    # ------------------------------------------------------------------
    # 3. GL entries  (>= rpt rows)
    # ------------------------------------------------------------------
    gl_rows = []
    for _ in range(rpt):
        dept, cat = random.choice(budget_combos)
        amt = round(random.uniform(500, 50_000), 2)
        vendor = random.choice(vendors)
        desc = fake.sentence(nb_words=6)
        ref = f"GL-{random.randint(100000, 999999)}"
        date = _random_date(fake)
        gl_rows.append((dept, cat, date, amt, vendor, desc, ref))
    c.executemany(
        "INSERT INTO gl_entries (department, category, entry_date, amount, vendor, description, reference_no) VALUES (?,?,?,?,?,?,?)",
        gl_rows,
    )

    # ------------------------------------------------------------------
    # 4. Projects (reference, not a scaled table)
    # ------------------------------------------------------------------
    projects = []
    for dept in DEPARTMENTS:
        n_proj = max(2, rpt // 25)
        for i in range(n_proj):
            pname = f"{dept[:3].upper()}-{fake.word().capitalize()}-{random.randint(100,999)}"
            projects.append({"name": pname, "department": dept})

    # ------------------------------------------------------------------
    # 5. Purchase orders  (>= rpt rows)
    # ------------------------------------------------------------------
    po_rows = []
    po_numbers = set()
    for _ in range(rpt):
        dept, cat = random.choice(budget_combos)
        vendor = random.choice(vendors)
        po_num = f"PO-{random.randint(100000,999999)}"
        while po_num in po_numbers:
            po_num = f"PO-{random.randint(100000,999999)}"
        po_numbers.add(po_num)
        date = _random_date(fake)
        amt = round(random.uniform(1_000, 100_000), 2)
        status = random.choices(PO_STATUSES, weights=[0.5, 0.35, 0.15])[0]
        proj = random.choice(projects)["name"] if random.random() < 0.6 else None
        po_rows.append((dept, cat, vendor, po_num, date, amt, status, proj))
    c.executemany(
        "INSERT INTO purchase_orders (department, category, vendor, po_number, po_date, amount, status, project_name) VALUES (?,?,?,?,?,?,?,?)",
        po_rows,
    )

    # ------------------------------------------------------------------
    # 6. Invoice line items  (>= rpt rows)
    # ------------------------------------------------------------------
    inv_rows = []
    for _ in range(rpt):
        dept, cat = random.choice(budget_combos)
        vendor = random.choice(vendors)
        inv_num = f"INV-{random.randint(100000,999999)}"
        date = _random_date(fake)
        amt = round(random.uniform(200, 30_000), 2)
        desc = fake.sentence(nb_words=5)
        # Optionally link to a PO
        linked_po = None
        if random.random() < 0.4 and po_rows:
            linked_po = random.choice(po_rows)[3]  # po_number
        inv_rows.append((inv_num, vendor, dept, cat, desc, amt, date, linked_po))
    c.executemany(
        "INSERT INTO invoice_line_items (invoice_number, vendor, department, category, line_description, amount, invoice_date, po_number) VALUES (?,?,?,?,?,?,?,?)",
        inv_rows,
    )

    # ------------------------------------------------------------------
    # 7. Project milestones  (>= rpt rows)
    # ------------------------------------------------------------------
    ms_rows = []
    for _ in range(rpt):
        proj = random.choice(projects)
        dept = proj["department"]
        cat = random.choice([c for d, c in budget_combos if d == dept] or [random.choice(CATEGORIES)])
        ms_name = f"MS-{fake.word().capitalize()}-{random.randint(10,99)}"
        date = _random_date(fake)
        amt = round(random.uniform(5_000, 80_000), 2)
        status = random.choices(MILESTONE_STATUSES, weights=[0.35, 0.50, 0.15])[0]
        ms_rows.append((proj["name"], dept, cat, ms_name, date, amt, status))
    c.executemany(
        "INSERT INTO project_milestones (project_name, department, category, milestone_name, planned_date, forecast_amount, status) VALUES (?,?,?,?,?,?,?)",
        ms_rows,
    )

    conn.commit()

    return {
        "budget_combos": budget_combos,
        "vendors": vendors,
        "projects": projects,
        "po_rows": po_rows,
    }


# ===================================================================
# Workspace files
# ===================================================================

def generate_workspace(conn, fake, workspace, scale, meta):
    n_files = scale["num_workspace_files"]
    budget_combos = meta["budget_combos"]
    vendors = meta["vendors"]
    projects = meta["projects"]

    # Distribute scalable files across three types
    n_amendment = (n_files + 2) // 3
    n_forecast = (n_files + 1) // 3
    n_vendor = n_files - n_amendment - n_forecast

    # ------------------------------------------------------------------
    # A. Budget amendment CSV files  (scalable)
    # ------------------------------------------------------------------
    # Generate all amendment records, then split across files
    n_amendments_total = n_amendment * 5  # ~5 amendments per file
    amendments = []
    for _ in range(n_amendments_total):
        dept, cat = random.choice(budget_combos)
        amt = round(random.uniform(-30_000, 60_000), 2)
        reason = random.choice([
            "Mid-year reallocation",
            "Emergency funding approved",
            "Budget cut directive",
            "Project scope expansion",
            "Seasonal adjustment",
            "Executive override",
            "Departmental transfer",
        ])
        date = _random_date(fake)
        amendments.append({
            "department": dept,
            "category": cat,
            "amendment_amount": amt,
            "reason": reason,
            "approval_date": date,
        })

    amendment_chunks = _split_into_n(amendments, n_amendment)
    for i, chunk in enumerate(amendment_chunks, 1):
        fpath = os.path.join(workspace, f"budget_amendment_{i}.csv")
        with open(fpath, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["department", "category", "amendment_amount", "reason", "approval_date"])
            w.writeheader()
            w.writerows(chunk)

    # ------------------------------------------------------------------
    # B. Project forecast adjustment YAML files  (scalable)
    # ------------------------------------------------------------------
    # Each project gets a risk_adjustment_factor
    project_factors = {}
    for proj in projects:
        project_factors[proj["name"]] = round(random.uniform(0.75, 1.35), 4)

    proj_items = list(project_factors.items())
    random.shuffle(proj_items)
    forecast_chunks = _split_into_n(proj_items, n_forecast)
    for i, chunk in enumerate(forecast_chunks, 1):
        fpath = os.path.join(workspace, f"project_forecast_{i}.yaml")
        data = {}
        for pname, factor in chunk:
            data[pname] = {
                "risk_adjustment_factor": factor,
                "last_reviewed": _random_date(fake),
                "reviewer": fake.name(),
            }
        with open(fpath, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    # ------------------------------------------------------------------
    # C. Vendor contract JSON files  (scalable)
    # ------------------------------------------------------------------
    vendor_contracts = {}
    for v in vendors:
        vendor_contracts[v] = {
            "vendor_name": v,
            "contract_id": f"CTR-{random.randint(10000,99999)}",
            "payment_terms_days": random.choice([15, 30, 45, 60, 90]),
            "committed_discount_pct": round(random.uniform(0, 0.15), 4),
            "primary_contact": fake.name(),
            "email": fake.email(),
        }

    vendor_items = list(vendor_contracts.values())
    random.shuffle(vendor_items)
    vendor_chunks = _split_into_n(vendor_items, max(n_vendor, 1))
    for i, chunk in enumerate(vendor_chunks, 1):
        fpath = os.path.join(workspace, f"vendor_contract_{i}.json")
        with open(fpath, "w") as f:
            json.dump(chunk, f, indent=2)

    # ------------------------------------------------------------------
    # D. Fixed files (not counted in SCALE["num_workspace_files"])
    # ------------------------------------------------------------------

    # D1. Variance policy (YAML)
    policy = {
        "variance_threshold_pct": 10.0,
        "flagged_severity_levels": {
            "warning": {"min_pct": 10.0, "max_pct": 25.0},
            "critical": {"min_pct": 25.0, "max_pct": None},
        },
        "excluded_categories": [],
        "report_settings": {
            "sort_by": ["department", "category"],
            "decimal_places": 2,
        },
    }
    with open(os.path.join(workspace, "variance_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # D2. Category-to-GL-account mapping (JSON)
    gl_mapping = {}
    for idx, cat in enumerate(CATEGORIES):
        gl_mapping[cat] = {
            "gl_account": f"{5000 + idx * 100}",
            "account_name": cat,
            "cost_type": random.choice(["direct", "indirect", "overhead"]),
        }
    with open(os.path.join(workspace, "category_gl_mapping.json"), "w") as f:
        json.dump(gl_mapping, f, indent=2)

    # D3. Department cost-center mapping (TXT - Markdown table)
    lines = ["# Department Cost Center Directory\n"]
    lines.append("| Department | Cost Center | Division |")
    lines.append("|---|---|---|")
    divisions = ["Corporate", "Technology", "Revenue", "Support"]
    for dept in DEPARTMENTS:
        cc = f"CC-{random.randint(1000,9999)}"
        div = random.choice(divisions)
        lines.append(f"| {dept} | {cc} | {div} |")
    with open(os.path.join(workspace, "department_cost_centers.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    fake = Faker()

    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    os.makedirs(args.workspace, exist_ok=True)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    meta = generate_data(conn, fake, SCALE)
    generate_workspace(conn, fake, args.workspace, SCALE, meta)
    conn.close()

    print(f"Database created at {args.db_path}")
    print(f"Workspace populated at {args.workspace}")


if __name__ == "__main__":
    main()
