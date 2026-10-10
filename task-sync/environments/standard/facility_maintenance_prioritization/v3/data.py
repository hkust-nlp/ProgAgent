#!/usr/bin/env python3
"""Data generator for branch facility maintenance prioritization task."""

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
    "rows_per_table": 640,
    "num_workspace_files": 48,
}

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

# ── Constants ──────────────────────────────────────────────────────────

EQUIPMENT_TYPES = [
    "HVAC", "Lighting", "Plumbing", "Elevator", "Fire Suppression",
    "Electrical Panel", "Generator", "Security System", "Water Heater",
    "Roofing", "Ventilation Fan", "Door Mechanism", "Sprinkler System",
    "Air Handling Unit", "Chiller",
]

COMPLAINT_CATEGORIES = [
    "Temperature Too High", "Temperature Too Low", "Humidity Issues",
    "Poor Air Quality", "Noise Disturbance", "Lighting Issues",
    "Water Leak", "Odor Complaint", "Drafty Area", "Elevator Malfunction",
]

SEVERITY_LEVELS = ["Low", "Medium", "High", "Critical"]

MAINTENANCE_TYPES = ["Preventative", "Corrective", "Emergency"]

VENDOR_SPECIALTIES = [
    "HVAC Systems", "Electrical", "Plumbing", "Elevator Service",
    "Fire Safety", "General Maintenance", "Security Systems",
    "Roofing", "Generator Service",
]

EQUIPMENT_TO_SPECIALTY = {
    "HVAC": "HVAC Systems",
    "Air Handling Unit": "HVAC Systems",
    "Chiller": "HVAC Systems",
    "Ventilation Fan": "HVAC Systems",
    "Lighting": "Electrical",
    "Electrical Panel": "Electrical",
    "Plumbing": "Plumbing",
    "Water Heater": "Plumbing",
    "Sprinkler System": "Plumbing",
    "Elevator": "Elevator Service",
    "Fire Suppression": "Fire Safety",
    "Generator": "Generator Service",
    "Security System": "Security Systems",
    "Roofing": "Roofing",
    "Door Mechanism": "General Maintenance",
}

REGIONS = ["Northeast", "Southeast", "Midwest", "Southwest", "West"]


def create_tables(conn):
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS branches (
            branch_id TEXT PRIMARY KEY,
            branch_name TEXT NOT NULL,
            address TEXT NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            region TEXT NOT NULL,
            square_footage INTEGER NOT NULL,
            year_built INTEGER NOT NULL,
            last_inspection_date TEXT NOT NULL,
            branch_tier TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS equipment (
            equipment_id TEXT PRIMARY KEY,
            branch_id TEXT NOT NULL,
            equipment_type TEXT NOT NULL,
            manufacturer TEXT NOT NULL,
            model_number TEXT NOT NULL,
            install_date TEXT NOT NULL,
            warranty_expiry TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (branch_id) REFERENCES branches(branch_id)
        );

        CREATE TABLE IF NOT EXISTS service_logs (
            log_id TEXT PRIMARY KEY,
            equipment_id TEXT NOT NULL,
            service_date TEXT NOT NULL,
            service_type TEXT NOT NULL,
            technician_name TEXT NOT NULL,
            description TEXT NOT NULL,
            parts_replaced TEXT,
            cost REAL NOT NULL,
            downtime_hours REAL NOT NULL,
            follow_up_needed INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (equipment_id) REFERENCES equipment(equipment_id)
        );

        CREATE TABLE IF NOT EXISTS complaint_tickets (
            ticket_id TEXT PRIMARY KEY,
            branch_id TEXT NOT NULL,
            complaint_date TEXT NOT NULL,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            description TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            status TEXT NOT NULL,
            resolution_date TEXT,
            linked_equipment_id TEXT,
            FOREIGN KEY (branch_id) REFERENCES branches(branch_id),
            FOREIGN KEY (linked_equipment_id) REFERENCES equipment(equipment_id)
        );

        CREATE TABLE IF NOT EXISTS maintenance_schedules (
            schedule_id TEXT PRIMARY KEY,
            equipment_id TEXT NOT NULL,
            maintenance_type TEXT NOT NULL,
            frequency_days INTEGER NOT NULL,
            last_performed TEXT NOT NULL,
            next_due TEXT NOT NULL,
            assigned_vendor_id TEXT,
            priority_level TEXT NOT NULL,
            estimated_cost REAL NOT NULL,
            FOREIGN KEY (equipment_id) REFERENCES equipment(equipment_id),
            FOREIGN KEY (assigned_vendor_id) REFERENCES vendor_contracts(vendor_id)
        );

        CREATE TABLE IF NOT EXISTS vendor_contracts (
            vendor_id TEXT PRIMARY KEY,
            vendor_name TEXT NOT NULL,
            specialty TEXT NOT NULL,
            contract_start TEXT NOT NULL,
            contract_end TEXT NOT NULL,
            guaranteed_response_hours INTEGER NOT NULL,
            hourly_rate REAL NOT NULL,
            satisfaction_rating REAL NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
    """)
    conn.commit()


def generate_branches(conn, n_rows):
    branches = []
    tiers = ["Flagship", "Standard", "Satellite"]
    tier_weights = [0.15, 0.55, 0.30]
    for i in range(n_rows):
        bid = f"BR-{i+1:04d}"
        tier = random.choices(tiers, weights=tier_weights, k=1)[0]
        region = random.choice(REGIONS)
        sqft = random.randint(2000, 25000) if tier != "Satellite" else random.randint(800, 3000)
        yr = random.randint(1975, 2020)
        insp = fake.date_between(start_date="-18m", end_date="-1m").isoformat()
        branches.append((
            bid,
            f"{fake.company()} Branch",
            fake.street_address(),
            fake.city(),
            fake.state_abbr(),
            region,
            sqft,
            yr,
            insp,
            tier,
        ))
    c = conn.cursor()
    c.executemany(
        "INSERT INTO branches VALUES (?,?,?,?,?,?,?,?,?,?)", branches
    )
    conn.commit()
    return [b[0] for b in branches]


def generate_equipment(conn, branch_ids, n_rows):
    equipment = []
    for i in range(n_rows):
        eid = f"EQ-{i+1:05d}"
        bid = random.choice(branch_ids)
        etype = random.choice(EQUIPMENT_TYPES)
        mfr = fake.company()
        model = fake.bothify("??-####").upper()
        install = fake.date_between(start_date="-15y", end_date="-6m").isoformat()
        warranty = fake.date_between(start_date="-2y", end_date="+3y").isoformat()
        status = random.choices(
            ["Operational", "Needs Repair", "Out of Service"],
            weights=[0.65, 0.25, 0.10], k=1
        )[0]
        equipment.append((eid, bid, etype, mfr, model, install, warranty, status))
    c = conn.cursor()
    c.executemany("INSERT INTO equipment VALUES (?,?,?,?,?,?,?,?)", equipment)
    conn.commit()
    return [e[0] for e in equipment], equipment


def generate_service_logs(conn, equip_ids, n_rows):
    logs = []
    for i in range(n_rows):
        lid = f"SL-{i+1:06d}"
        eid = random.choice(equip_ids)
        sdate = fake.date_between(start_date="-2y", end_date="today").isoformat()
        stype = random.choice(MAINTENANCE_TYPES)
        tech = fake.name()
        desc = fake.sentence(nb_words=10)
        parts = fake.sentence(nb_words=4) if random.random() < 0.4 else None
        cost = round(random.uniform(50, 5000), 2)
        downtime = round(random.uniform(0.5, 48), 1)
        follow_up = 1 if random.random() < 0.25 else 0
        logs.append((lid, eid, sdate, stype, tech, desc, parts, cost, downtime, follow_up))
    c = conn.cursor()
    c.executemany("INSERT INTO service_logs VALUES (?,?,?,?,?,?,?,?,?,?)", logs)
    conn.commit()


def generate_complaints(conn, branch_ids, equip_data, n_rows):
    """equip_data is list of (eid, bid, ...) tuples."""
    # Build branch -> equipment mapping
    branch_equip = {}
    for eq in equip_data:
        branch_equip.setdefault(eq[1], []).append(eq[0])

    tickets = []
    for i in range(n_rows):
        tid = f"CT-{i+1:06d}"
        bid = random.choice(branch_ids)
        cdate = fake.date_between(start_date="-6m", end_date="today").isoformat()
        cat = random.choice(COMPLAINT_CATEGORIES)
        sev = random.choices(SEVERITY_LEVELS, weights=[0.30, 0.35, 0.25, 0.10], k=1)[0]
        desc = fake.sentence(nb_words=12)
        cust = fake.name()
        status = random.choices(
            ["Open", "In Progress", "Resolved", "Closed"],
            weights=[0.30, 0.20, 0.30, 0.20], k=1
        )[0]
        cdate_dt = datetime.fromisoformat(cdate)
        today_dt = datetime.now().date()
        if status in ("Resolved", "Closed") and cdate_dt.date() < today_dt:
            res_date = fake.date_between(start_date=cdate_dt.date(), end_date=today_dt).isoformat()
        elif status in ("Resolved", "Closed"):
            res_date = cdate
        else:
            res_date = None
        # Link to equipment at the SAME branch
        branch_eqs = branch_equip.get(bid, [])
        linked = random.choice(branch_eqs) if branch_eqs and random.random() < 0.6 else None
        tickets.append((tid, bid, cdate, cat, sev, desc, cust, status, res_date, linked))
    c = conn.cursor()
    c.executemany("INSERT INTO complaint_tickets VALUES (?,?,?,?,?,?,?,?,?,?)", tickets)
    conn.commit()


def generate_vendors(conn, n_vendors):
    vendors = []
    used = set()
    for i in range(n_vendors):
        vid = f"VN-{i+1:03d}"
        vname = fake.company() + " Services"
        while vname in used:
            vname = fake.company() + " Services"
        used.add(vname)
        spec = random.choice(VENDOR_SPECIALTIES)
        cs = fake.date_between(start_date="-3y", end_date="-6m").isoformat()
        ce = fake.date_between(start_date="+1m", end_date="+3y").isoformat()
        resp_hrs = random.choice([4, 8, 12, 24, 48])
        rate = round(random.uniform(45, 200), 2)
        sat = round(random.uniform(2.5, 5.0), 1)
        active = 1 if random.random() < 0.85 else 0
        vendors.append((vid, vname, spec, cs, ce, resp_hrs, rate, sat, active))
    c = conn.cursor()
    c.executemany("INSERT INTO vendor_contracts VALUES (?,?,?,?,?,?,?,?,?)", vendors)
    conn.commit()
    return [v[0] for v in vendors], vendors


def generate_schedules(conn, equip_ids, vendor_ids, n_rows):
    schedules = []
    for i in range(n_rows):
        sid = f"MS-{i+1:05d}"
        eid = random.choice(equip_ids)
        mtype = random.choices(MAINTENANCE_TYPES, weights=[0.6, 0.3, 0.1], k=1)[0]
        freq = random.choice([30, 60, 90, 180, 365])
        last_p = fake.date_between(start_date="-1y", end_date="-1w").isoformat()
        last_dt = datetime.fromisoformat(last_p)
        next_due = (last_dt + timedelta(days=freq)).isoformat()[:10]
        vid = random.choice(vendor_ids) if random.random() < 0.7 else None
        prio = random.choices(SEVERITY_LEVELS, weights=[0.25, 0.35, 0.25, 0.15], k=1)[0]
        est_cost = round(random.uniform(100, 8000), 2)
        schedules.append((sid, eid, mtype, freq, last_p, next_due, vid, prio, est_cost))
    c = conn.cursor()
    c.executemany("INSERT INTO maintenance_schedules VALUES (?,?,?,?,?,?,?,?,?)", schedules)
    conn.commit()


# ── Workspace generation ──────────────────────────────────────────────

def generate_workspace(conn, workspace, n_files):
    os.makedirs(workspace, exist_ok=True)

    c = conn.cursor()

    # ── Fixed policy / config files (not counted toward n_files) ──

    # 1. Priority scoring config (YAML)
    priority_config = {
        "scoring_weights": {
            "complaint_severity_score": {
                "Critical": 40,
                "High": 25,
                "Medium": 15,
                "Low": 5,
            },
            "overdue_maintenance_multiplier": 1.5,
            "repeat_failure_bonus": 20,
            "vendor_response_penalty_threshold_hours": 24,
            "vendor_slow_response_penalty": 10,
            "equipment_age_threshold_years": 10,
            "equipment_age_bonus": 15,
            "branch_tier_multiplier": {
                "Flagship": 1.5,
                "Standard": 1.0,
                "Satellite": 0.75,
            },
        },
        "quarter_definition": {
            "start_date": "2026-04-01",
            "end_date": "2026-06-30",
        },
        "work_order_output": {
            "file_name": "ranked_work_orders.csv",
            "columns": [
                "rank", "work_order_id", "branch_id", "branch_name",
                "equipment_id", "equipment_type", "issue_summary",
                "priority_score", "assigned_vendor_id", "vendor_name",
                "estimated_cost", "target_completion_date",
            ],
        },
    }
    with open(os.path.join(workspace, "priority_config.yaml"), "w") as f:
        yaml.dump(priority_config, f, default_flow_style=False, sort_keys=False)

    # 2. Maintenance policy (MD)
    policy_md = """# Facility Maintenance Policy

## Work Order Generation Rules

A work order must be generated for any equipment item that meets at least one of the following conditions:

1. The equipment has an overdue preventative maintenance schedule (next_due date is before or on the quarter end date).
2. The equipment has been linked to at least one open or in-progress complaint ticket.
3. The equipment has a service log entry within the past 12 months where follow_up_needed is flagged.

## Priority Score Calculation

The priority score for each work order is calculated as follows:

- Start with a base score of zero.
- Add the complaint severity score for the highest-severity open/in-progress complaint linked to this equipment. If multiple complaints exist, use only the maximum severity. If no open/in-progress complaint is linked, add zero for this component.
- If the equipment has an overdue maintenance schedule, multiply the current score by the overdue maintenance multiplier.
- If the equipment has had three or more service log entries in the past 12 months (repeat failures), add the repeat failure bonus.
- If the assigned vendor's guaranteed response time exceeds the vendor response penalty threshold, subtract the vendor slow response penalty.
- If the equipment was installed more than the equipment age threshold years ago (strictly more than), add the equipment age bonus.
- Finally, multiply the total score by the branch tier multiplier corresponding to the equipment's branch tier.

Round the final priority score to two decimal places.

## Vendor Assignment

Each work order should be assigned to the active vendor whose specialty matches the equipment type (use the specialty mapping). If multiple active vendors share the same specialty, choose the one with the highest satisfaction rating. If no active vendor matches, leave the vendor fields as "UNASSIGNED".

## Target Completion Date

Set the target completion date to the quarter end date for all work orders.

## Work Order ID Format

Work order IDs follow the format WO-XXXX, numbered sequentially starting from WO-0001, ordered by descending priority score.

## Tie-Breaking

When two work orders have the same priority score, break ties by branch_id ascending, then by equipment_id ascending.
"""
    with open(os.path.join(workspace, "maintenance_policy.md"), "w") as f:
        f.write(policy_md)

    # 3. Equipment-to-specialty mapping (JSON) - fixed file
    with open(os.path.join(workspace, "equipment_specialty_map.json"), "w") as f:
        json.dump(EQUIPMENT_TO_SPECIALTY, f, indent=2)

    # ── Scalable data files (counted toward n_files) ──

    # Distribute files across formats
    n_csv = n_files // 4
    n_json = n_files // 4
    n_txt = n_files // 4
    n_yaml = n_files - n_csv - n_json - n_txt

    # CSV files: branch-level complaint summaries
    c.execute("SELECT DISTINCT branch_id FROM branches")
    all_branches = [r[0] for r in c.fetchall()]
    branches_per_csv = max(1, len(all_branches) // max(n_csv, 1))

    for fi in range(n_csv):
        start = fi * branches_per_csv
        end = start + branches_per_csv if fi < n_csv - 1 else len(all_branches)
        batch = all_branches[start:end]
        if not batch:
            batch = [random.choice(all_branches)]

        placeholders = ",".join("?" for _ in batch)
        c.execute(f"""
            SELECT ct.ticket_id, ct.branch_id, ct.complaint_date, ct.category,
                   ct.severity, ct.description, ct.status, ct.linked_equipment_id
            FROM complaint_tickets ct
            WHERE ct.branch_id IN ({placeholders})
              AND ct.status IN ('Open', 'In Progress')
        """, batch)
        rows = c.fetchall()
        df = pd.DataFrame(rows, columns=[
            "ticket_id", "branch_id", "complaint_date", "category",
            "severity", "description", "status", "linked_equipment_id"
        ])
        df.to_csv(os.path.join(workspace, f"complaint_batch_{fi+1}.csv"), index=False)

    # JSON files: vendor performance reports
    c.execute("SELECT * FROM vendor_contracts WHERE active = 1")
    vendors = c.fetchall()
    vendor_cols = ["vendor_id", "vendor_name", "specialty", "contract_start",
                   "contract_end", "guaranteed_response_hours", "hourly_rate",
                   "satisfaction_rating", "active"]
    vendors_per_json = max(1, len(vendors) // max(n_json, 1))

    for fi in range(n_json):
        start = fi * vendors_per_json
        end = start + vendors_per_json if fi < n_json - 1 else len(vendors)
        batch = vendors[start:end]
        if not batch:
            batch = [random.choice(vendors)]

        records = []
        for v in batch:
            vd = dict(zip(vendor_cols, v))
            # Add performance metrics from service logs
            c.execute("""
                SELECT COUNT(*), AVG(sl.cost), AVG(sl.downtime_hours)
                FROM service_logs sl
                JOIN equipment e ON sl.equipment_id = e.equipment_id
                JOIN maintenance_schedules ms ON ms.equipment_id = e.equipment_id
                WHERE ms.assigned_vendor_id = ?
            """, (vd["vendor_id"],))
            stats = c.fetchone()
            vd["total_jobs_linked"] = stats[0] or 0
            vd["avg_job_cost"] = round(stats[1], 2) if stats[1] else 0.0
            vd["avg_downtime_hours"] = round(stats[2], 1) if stats[2] else 0.0
            records.append(vd)

        with open(os.path.join(workspace, f"vendor_report_{fi+1}.json"), "w") as f:
            json.dump(records, f, indent=2)

    # TXT files: service log summaries per equipment batch
    c.execute("SELECT DISTINCT equipment_id FROM equipment")
    all_equip = [r[0] for r in c.fetchall()]
    equip_per_txt = max(1, len(all_equip) // max(n_txt, 1))

    for fi in range(n_txt):
        start = fi * equip_per_txt
        end = start + equip_per_txt if fi < n_txt - 1 else len(all_equip)
        batch = all_equip[start:end]
        if not batch:
            batch = [random.choice(all_equip)]

        placeholders = ",".join("?" for _ in batch)
        c.execute(f"""
            SELECT sl.log_id, sl.equipment_id, sl.service_date, sl.service_type,
                   sl.technician_name, sl.description, sl.parts_replaced,
                   sl.cost, sl.downtime_hours, sl.follow_up_needed
            FROM service_logs sl
            WHERE sl.equipment_id IN ({placeholders})
            ORDER BY sl.service_date DESC
        """, batch)
        rows = c.fetchall()

        lines = [f"Service Log Report - Batch {fi+1}", "=" * 50, ""]
        for r in rows:
            lines.append(f"Log ID: {r[0]}")
            lines.append(f"  Equipment: {r[1]}")
            lines.append(f"  Date: {r[2]}")
            lines.append(f"  Type: {r[3]}")
            lines.append(f"  Technician: {r[4]}")
            lines.append(f"  Description: {r[5]}")
            lines.append(f"  Parts Replaced: {r[6] or 'None'}")
            lines.append(f"  Cost: ${r[7]:.2f}")
            lines.append(f"  Downtime: {r[8]}h")
            lines.append(f"  Follow-up Needed: {'Yes' if r[9] else 'No'}")
            lines.append("")

        with open(os.path.join(workspace, f"service_summary_{fi+1}.txt"), "w") as f:
            f.write("\n".join(lines))

    # YAML files: maintenance schedule batches
    equip_per_yaml = max(1, len(all_equip) // max(n_yaml, 1))

    for fi in range(n_yaml):
        start = fi * equip_per_yaml
        end = start + equip_per_yaml if fi < n_yaml - 1 else len(all_equip)
        batch = all_equip[start:end]
        if not batch:
            batch = [random.choice(all_equip)]

        placeholders = ",".join("?" for _ in batch)
        c.execute(f"""
            SELECT ms.schedule_id, ms.equipment_id, ms.maintenance_type,
                   ms.frequency_days, ms.last_performed, ms.next_due,
                   ms.assigned_vendor_id, ms.priority_level, ms.estimated_cost
            FROM maintenance_schedules ms
            WHERE ms.equipment_id IN ({placeholders})
        """, batch)
        rows = c.fetchall()

        records = []
        for r in rows:
            records.append({
                "schedule_id": r[0],
                "equipment_id": r[1],
                "maintenance_type": r[2],
                "frequency_days": r[3],
                "last_performed": r[4],
                "next_due": r[5],
                "assigned_vendor_id": r[6],
                "priority_level": r[7],
                "estimated_cost": float(r[8]),
            })

        with open(os.path.join(workspace, f"schedule_batch_{fi+1}.yaml"), "w") as f:
            yaml.dump({"schedules": records}, f, default_flow_style=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)

    create_tables(conn)

    n = SCALE["rows_per_table"]

    # Number of branches ~ n // 5 (each branch has multiple equipment)
    n_branches = max(10, n // 5)
    n_equipment = n
    n_service_logs = int(n * 1.5)
    n_complaints = n
    n_vendors = max(8, n // 8)
    n_schedules = n

    branch_ids = generate_branches(conn, n_branches)
    equip_ids, equip_data = generate_equipment(conn, branch_ids, n_equipment)
    generate_service_logs(conn, equip_ids, n_service_logs)
    generate_complaints(conn, branch_ids, equip_data, n_complaints)
    vendor_ids, _ = generate_vendors(conn, n_vendors)
    generate_schedules(conn, equip_ids, vendor_ids, n_schedules)

    generate_workspace(conn, args.workspace, SCALE["num_workspace_files"])

    conn.close()
    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")


if __name__ == "__main__":
    main()
