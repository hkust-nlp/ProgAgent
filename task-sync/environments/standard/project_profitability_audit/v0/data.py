import argparse
import os
import sqlite3
import json
import csv
import random
import numpy as np
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 30,
    "num_workspace_files": 8,
}

# ---- All random seeds pinned to 42 ----
random.seed(42)
np.random.seed(42)
Faker.seed(42)
fake = Faker()

# ---- Constants ----
PROJECT_TYPES = ["residential", "commercial", "institutional", "mixed_use", "industrial"]
BUDGET_CATEGORIES = ["labor", "materials", "subcontractor", "permits_fees", "overhead", "contingency"]
VENDOR_COST_CATEGORIES = [
    "structural_engineering", "mep_services", "landscaping",
    "surveying", "interior_design", "environmental_consulting",
]
ARCHITECT_ROLES = ["junior_architect", "architect", "senior_architect", "principal", "project_manager"]
DEPARTMENTS = ["design", "engineering", "planning", "interiors"]
TASK_CATEGORIES = ["design", "drafting", "review", "site_visit", "coordination", "documentation"]
INDIRECT_COST_CATEGORIES = ["insurance", "permits", "travel", "equipment_rental", "printing", "legal_fees"]
PROJECT_STATUSES = ["active", "completed", "on_hold"]
PAYMENT_STATUSES = ["paid", "pending", "overdue"]
REGIONS = ["Northeast", "Southeast", "Midwest", "West", "Southwest"]

OVERHEAD_MULTIPLIERS = {
    "residential": 1.15,
    "commercial": 1.25,
    "institutional": 1.20,
    "mixed_use": 1.22,
    "industrial": 1.18,
}

ROLE_BASE_PREMIUMS = {
    "junior_architect": 1.0,
    "architect": 1.1,
    "senior_architect": 1.25,
    "principal": 1.4,
    "project_manager": 1.3,
}

HOURLY_RATE_BASES = {
    "junior_architect": 45,
    "architect": 75,
    "senior_architect": 105,
    "principal": 140,
    "project_manager": 120,
}

BUILDING_SUFFIXES = [
    "Tower", "Plaza", "Center", "Complex", "Building",
    "Residence", "Campus", "Park", "Hall", "House",
]

ENTRIES_PER_PROJECT = 8  # timesheet entries per project (fixed across scales)


# ---- SQL DDL ----
def create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            project_name TEXT NOT NULL,
            client_name TEXT NOT NULL,
            project_type TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS architects (
            architect_id TEXT PRIMARY KEY,
            architect_name TEXT NOT NULL,
            role TEXT NOT NULL,
            department TEXT NOT NULL,
            hourly_rate REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS timesheets (
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            architect_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            work_date TEXT NOT NULL,
            hours_worked REAL NOT NULL,
            task_category TEXT NOT NULL,
            FOREIGN KEY (architect_id) REFERENCES architects(architect_id),
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        );
        CREATE TABLE IF NOT EXISTS budget_allocations (
            allocation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            budget_category TEXT NOT NULL,
            allocated_amount REAL NOT NULL,
            fiscal_year INTEGER NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        );
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            invoice_number TEXT NOT NULL,
            invoice_date TEXT NOT NULL,
            amount_billed REAL NOT NULL,
            payment_status TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        );
        CREATE TABLE IF NOT EXISTS vendor_costs (
            cost_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            vendor_name TEXT NOT NULL,
            cost_category TEXT NOT NULL,
            amount REAL NOT NULL,
            invoice_date TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        );
    """)
    conn.commit()


# ---- Data generation (in-memory) ----
def generate_data(scale):
    num_rows = scale["rows_per_table"]

    # -- Projects --
    projects = []
    for i in range(num_rows):
        pid = f"PRJ-{i+1:04d}"
        pname = f"{fake.company()} {random.choice(BUILDING_SUFFIXES)}"
        client = fake.company()
        ptype = random.choice(PROJECT_TYPES)
        start = fake.date_between(start_date="-2y", end_date="-6m")
        end = fake.date_between(start_date=start, end_date="+1y")
        status = random.choice(PROJECT_STATUSES)
        projects.append({
            "project_id": pid, "project_name": pname, "client_name": client,
            "project_type": ptype, "start_date": str(start), "end_date": str(end),
            "status": status,
        })

    project_ids = [p["project_id"] for p in projects]
    project_type_map = {p["project_id"]: p["project_type"] for p in projects}

    # -- Architects --
    architects = []
    for i in range(num_rows):
        aid = f"ARC-{i+1:04d}"
        role = random.choice(ARCHITECT_ROLES)
        rate = round(HOURLY_RATE_BASES[role] + random.uniform(-10, 10), 2)
        architects.append({
            "architect_id": aid, "architect_name": fake.name(),
            "role": role, "department": random.choice(DEPARTMENTS),
            "hourly_rate": rate,
        })

    architect_ids = [a["architect_id"] for a in architects]
    architect_map = {a["architect_id"]: a for a in architects}

    # -- Assign architects to projects --
    project_architects = {}
    for pid in project_ids:
        n_assigned = random.randint(3, min(6, num_rows))
        project_architects[pid] = random.sample(architect_ids, n_assigned)

    # -- Timesheets --
    timesheets = []
    for pid in project_ids:
        assigned = project_architects[pid]
        for _ in range(ENTRIES_PER_PROJECT):
            aid = random.choice(assigned)
            hours = round(random.choice([2.0, 4.0, 6.0, 8.0]) + random.uniform(-0.5, 0.5), 1)
            hours = max(0.5, hours)
            timesheets.append({
                "architect_id": aid, "project_id": pid,
                "work_date": str(fake.date_between(start_date="-1y", end_date="today")),
                "hours_worked": hours, "task_category": random.choice(TASK_CATEGORIES),
            })

    # -- Vendor costs --
    vendor_pool = [fake.company() for _ in range(20)]
    vendor_costs = []
    for pid in project_ids:
        for _ in range(random.randint(3, 6)):
            vendor_costs.append({
                "project_id": pid, "vendor_name": random.choice(vendor_pool),
                "cost_category": random.choice(VENDOR_COST_CATEGORIES),
                "amount": round(random.uniform(2000, 60000), 2),
                "invoice_date": str(fake.date_between(start_date="-1y", end_date="today")),
            })

    # -- Invoices --
    invoices = []
    for pid in project_ids:
        for j in range(random.randint(2, 5)):
            invoices.append({
                "project_id": pid,
                "invoice_number": f"INV-{pid}-{j+1:03d}",
                "invoice_date": str(fake.date_between(start_date="-1y", end_date="today")),
                "amount_billed": round(random.uniform(5000, 100000), 2),
                "payment_status": random.choice(PAYMENT_STATUSES),
            })

    # ---- Workspace-only data ----
    retention_pcts = {pid: round(random.uniform(3.0, 12.0), 1) for pid in project_ids}

    architect_premiums = {}
    for a in architects:
        base = ROLE_BASE_PREMIUMS[a["role"]]
        architect_premiums[a["architect_id"]] = round(base + random.uniform(-0.05, 0.05), 3)

    change_orders = {}
    for pid in project_ids:
        if random.random() < 0.6:
            orders = []
            for _ in range(random.randint(1, 3)):
                orders.append({
                    "description": fake.sentence(nb_words=6),
                    "approved_amount": round(random.uniform(5000, 40000), 2),
                    "date": str(fake.date_between(start_date="-6m", end_date="today")),
                })
            change_orders[pid] = orders

    indirect_costs = {}
    for pid in project_ids:
        costs = []
        for _ in range(random.randint(1, 4)):
            costs.append({
                "category": random.choice(INDIRECT_COST_CATEGORIES),
                "amount": round(random.uniform(500, 8000), 2),
                "date": str(fake.date_between(start_date="-1y", end_date="today")),
                "description": fake.sentence(nb_words=5),
            })
        indirect_costs[pid] = costs

    project_regions = {pid: random.choice(REGIONS) for pid in project_ids}

    # ---- Compute actual costs per project (for budget calibration) ----
    actual_costs = {}
    for pid in project_ids:
        p_ts = [t for t in timesheets if t["project_id"] == pid]
        labor = sum(
            t["hours_worked"] * architect_map[t["architect_id"]]["hourly_rate"]
            * architect_premiums[t["architect_id"]]
            for t in p_ts
        )
        labor *= OVERHEAD_MULTIPLIERS[project_type_map[pid]]

        p_vc = [v for v in vendor_costs if v["project_id"] == pid]
        vendor_raw = sum(v["amount"] for v in p_vc)
        vendor_adj = vendor_raw * (1 - retention_pcts[pid] / 100)

        indirect_total = sum(c["amount"] for c in indirect_costs.get(pid, []))
        co_total = sum(co["approved_amount"] for co in change_orders.get(pid, []))

        actual_costs[pid] = {
            "labor": labor, "vendor": vendor_adj, "indirect": indirect_total,
            "total_actual": labor + vendor_adj + indirect_total, "co_total": co_total,
        }

    # ---- Generate budgets calibrated to desired variance distribution ----
    n = len(project_ids)
    variance_targets = []
    for i in range(n):
        frac = i / n
        if frac < 0.25:
            target = random.uniform(-20, -3)       # Within Budget
        elif frac < 0.40:
            target = random.uniform(1, 4.5)        # Within Tolerance
        elif frac < 0.60:
            target = random.uniform(6, 14)         # Minor Overrun
        elif frac < 0.80:
            target = random.uniform(16, 28)        # Moderate Overrun
        else:
            target = random.uniform(32, 55)        # Significant Overrun
        variance_targets.append(target)
    random.shuffle(variance_targets)

    budget_allocations = []
    for idx, pid in enumerate(project_ids):
        target_pct = variance_targets[idx]
        total_actual = actual_costs[pid]["total_actual"]
        co_total = actual_costs[pid]["co_total"]

        adjusted_budget_target = total_actual / (1 + target_pct / 100)
        total_budget_target = adjusted_budget_target - co_total
        if total_budget_target < 1000:
            total_budget_target = max(1000, adjusted_budget_target * 0.5)

        proportions = [random.random() for _ in BUDGET_CATEGORIES]
        prop_sum = sum(proportions)
        for j, cat in enumerate(BUDGET_CATEGORIES):
            amount = round(total_budget_target * proportions[j] / prop_sum, 2)
            budget_allocations.append({
                "project_id": pid, "budget_category": cat,
                "allocated_amount": amount,
                "fiscal_year": random.choice([2024, 2025]),
            })

    return {
        "projects": projects, "architects": architects,
        "timesheets": timesheets, "budget_allocations": budget_allocations,
        "invoices": invoices, "vendor_costs": vendor_costs,
        "retention_pcts": retention_pcts, "architect_premiums": architect_premiums,
        "change_orders": change_orders, "indirect_costs": indirect_costs,
        "project_regions": project_regions,
    }


# ---- Write to SQLite ----
def write_database(conn, data):
    c = conn.cursor()
    for p in data["projects"]:
        c.execute("INSERT INTO projects VALUES (?,?,?,?,?,?,?)",
                  (p["project_id"], p["project_name"], p["client_name"],
                   p["project_type"], p["start_date"], p["end_date"], p["status"]))
    for a in data["architects"]:
        c.execute("INSERT INTO architects VALUES (?,?,?,?,?)",
                  (a["architect_id"], a["architect_name"], a["role"],
                   a["department"], a["hourly_rate"]))
    for t in data["timesheets"]:
        c.execute(
            "INSERT INTO timesheets (architect_id,project_id,work_date,hours_worked,task_category) VALUES (?,?,?,?,?)",
            (t["architect_id"], t["project_id"], t["work_date"], t["hours_worked"], t["task_category"]))
    for b in data["budget_allocations"]:
        c.execute(
            "INSERT INTO budget_allocations (project_id,budget_category,allocated_amount,fiscal_year) VALUES (?,?,?,?)",
            (b["project_id"], b["budget_category"], b["allocated_amount"], b["fiscal_year"]))
    for inv in data["invoices"]:
        c.execute(
            "INSERT INTO invoices (project_id,invoice_number,invoice_date,amount_billed,payment_status) VALUES (?,?,?,?,?)",
            (inv["project_id"], inv["invoice_number"], inv["invoice_date"],
             inv["amount_billed"], inv["payment_status"]))
    for v in data["vendor_costs"]:
        c.execute(
            "INSERT INTO vendor_costs (project_id,vendor_name,cost_category,amount,invoice_date) VALUES (?,?,?,?,?)",
            (v["project_id"], v["vendor_name"], v["cost_category"], v["amount"], v["invoice_date"]))
    conn.commit()


# ---- Write workspace files ----
def write_workspace(workspace, data, scale):
    os.makedirs(workspace, exist_ok=True)
    project_ids = [p["project_id"] for p in data["projects"]]
    architect_ids = [a["architect_id"] for a in data["architects"]]
    num_files = scale["num_workspace_files"]
    fpt = num_files // 4  # files per type

    # ---- Fixed files (not counted in num_workspace_files) ----
    with open(os.path.join(workspace, "overhead_config.yaml"), "w") as f:
        yaml.dump({"overhead_multipliers": OVERHEAD_MULTIPLIERS}, f, default_flow_style=False)

    thresholds = {
        "classifications": [
            {"label": "Within Budget", "min_pct": None, "max_pct": 0.0},
            {"label": "Within Tolerance", "min_pct": 0.0, "max_pct": 5.0},
            {"label": "Minor Overrun", "min_pct": 5.0, "max_pct": 15.0},
            {"label": "Moderate Overrun", "min_pct": 15.0, "max_pct": 30.0},
            {"label": "Significant Overrun", "min_pct": 30.0, "max_pct": None},
        ],
        "report_scope": "all_projects",
    }
    with open(os.path.join(workspace, "variance_thresholds.json"), "w") as f:
        json.dump(thresholds, f, indent=2)

    # ---- Helper: split IDs into fpt batches ----
    def batches(ids, n):
        bs = max(1, len(ids) // n)
        result = []
        for i in range(n):
            start = i * bs
            result.append(ids[start:] if i == n - 1 else ids[start:start + bs])
        return result

    # 1. Project financials CSV
    for i, batch in enumerate(batches(project_ids, fpt)):
        path = os.path.join(workspace, f"project_financials_{i+1}.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["project_id", "retention_pct", "region"])
            for pid in batch:
                w.writerow([pid, data["retention_pcts"][pid], data["project_regions"][pid]])

    # 2. Architect premiums JSON
    for i, batch in enumerate(batches(architect_ids, fpt)):
        payload = {aid: {"role_multiplier": data["architect_premiums"][aid]} for aid in batch}
        path = os.path.join(workspace, f"architect_premiums_{i+1}.json")
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)

    # 3. Change orders YAML
    for i, batch in enumerate(batches(project_ids, fpt)):
        payload = {}
        for pid in batch:
            if pid in data["change_orders"]:
                payload[pid] = data["change_orders"][pid]
        path = os.path.join(workspace, f"change_orders_{i+1}.yaml")
        with open(path, "w") as f:
            yaml.dump(payload, f, default_flow_style=False)

    # 4. Indirect costs TXT
    for i, batch in enumerate(batches(project_ids, fpt)):
        path = os.path.join(workspace, f"indirect_costs_{i+1}.txt")
        with open(path, "w") as f:
            for pid in batch:
                for cost in data["indirect_costs"].get(pid, []):
                    f.write(f"Project: {pid}\n")
                    f.write(f"Category: {cost['category']}\n")
                    f.write(f"Amount: {cost['amount']}\n")
                    f.write(f"Date: {cost['date']}\n")
                    f.write(f"Description: {cost['description']}\n")
                    f.write("---\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    data = generate_data(SCALE)
    write_database(conn, data)
    write_workspace(args.workspace, data, SCALE)
    conn.close()
    print("Data generation complete.")


if __name__ == "__main__":
    main()
