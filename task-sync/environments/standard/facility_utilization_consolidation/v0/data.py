#!/usr/bin/env python3
"""Generate database and workspace for public facility consolidation task."""

import argparse
import os
import sqlite3
import json
import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 20,
    "num_workspace_files": 10,
}


def main(db_path, workspace):
    fake = Faker()
    Faker.seed(42)
    np.random.seed(42)

    os.makedirs(workspace, exist_ok=True)

    num_facilities = SCALE["rows_per_table"]
    num_survey_months = SCALE["num_workspace_files"]

    # --- Constants ---
    FACILITY_TYPES = [
        "community_center", "library", "recreation_center",
        "senior_center", "youth_center", "multipurpose_hall",
    ]
    ZONES = ["North", "South", "East", "West", "Central"]
    UTILITY_TYPES = ["electricity", "water", "natural_gas", "sewer"]
    USAGE_UNITS = {
        "electricity": "kWh",
        "water": "gallons",
        "natural_gas": "therms",
        "sewer": "gallons",
    }
    MAINTENANCE_TYPES = [
        "HVAC_service", "plumbing_repair", "electrical_inspection",
        "roof_maintenance", "grounds_keeping", "janitorial_deep_clean",
        "fire_safety_check", "elevator_service",
    ]
    MAINTENANCE_STATUSES = ["completed", "scheduled", "deferred", "in_progress"]
    PROGRAM_TYPES = [
        "fitness_class", "art_workshop", "youth_sports", "senior_wellness",
        "community_meeting", "tutoring", "music_lessons", "cooking_class",
        "book_club", "dance_class", "technology_training", "language_class",
    ]
    CAPITAL_CATEGORIES = [
        "safety", "energy_efficiency", "accessibility", "structural", "technology",
    ]
    CAPITAL_PRIORITIES = ["critical", "high", "medium", "low"]
    CAPITAL_STATUSES = ["approved", "pending", "denied"]
    QUARTERS = ["Q1_2025", "Q2_2025", "Q3_2025", "Q4_2025"]

    # --- Generate facility attributes (numpy-only for determinism) ---
    capacities = np.random.randint(100, 450, size=num_facilities)
    sqft_multipliers = np.random.randint(18, 35, size=num_facilities)
    years_built = np.random.randint(1965, 2012, size=num_facilities)
    budgets = np.round(np.random.uniform(80000, 400000, size=num_facilities), 2)

    # Select underutilized facilities (~30%)
    num_underutilized = max(4, int(num_facilities * 0.30))
    underutil_indices = sorted(
        np.random.choice(num_facilities, num_underutilized, replace=False).tolist()
    )
    underutil_set = set(underutil_indices)

    # Build facility records
    facilities = []
    for i in range(num_facilities):
        ftype = FACILITY_TYPES[i % len(FACILITY_TYPES)]
        zone = ZONES[i % len(ZONES)]
        cap = int(capacities[i])
        sqft = int(cap * int(sqft_multipliers[i]))
        yb = int(years_built[i])
        budget = float(budgets[i])
        name = f"{fake.unique.city()} {ftype.replace('_', ' ').title()}"
        address = fake.address().replace("\n", ", ")

        facilities.append({
            "facility_id": f"FAC-{i+1:04d}",
            "name": name,
            "type": ftype,
            "zone": zone,
            "address": address,
            "capacity": cap,
            "square_footage": sqft,
            "year_built": yb,
            "annual_operating_budget": budget,
        })

    # ================================================================
    # DATABASE
    # ================================================================
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Table 1: facilities (note: annual_operating_budget is NOT stored here)
    cur.execute("""
        CREATE TABLE facilities (
            facility_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            zone TEXT NOT NULL,
            address TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            square_footage INTEGER NOT NULL,
            year_built INTEGER NOT NULL
        )
    """)
    for f in facilities:
        cur.execute(
            "INSERT INTO facilities VALUES (?,?,?,?,?,?,?,?)",
            (f["facility_id"], f["name"], f["type"], f["zone"],
             f["address"], f["capacity"], f["square_footage"], f["year_built"]),
        )

    # Table 2: utility_bills  (4 quarters x 4 types per facility)
    cur.execute("""
        CREATE TABLE utility_bills (
            bill_id INTEGER PRIMARY KEY AUTOINCREMENT,
            facility_id TEXT NOT NULL,
            billing_quarter TEXT NOT NULL,
            utility_type TEXT NOT NULL,
            amount REAL NOT NULL,
            usage_quantity REAL NOT NULL,
            usage_unit TEXT NOT NULL,
            FOREIGN KEY (facility_id) REFERENCES facilities(facility_id)
        )
    """)
    for f in facilities:
        for q in QUARTERS:
            for ut in UTILITY_TYPES:
                base = float(np.random.uniform(800, 6000))
                if f["square_footage"] > 5000:
                    base *= 1.4
                amount = round(base, 2)
                usage = round(float(np.random.uniform(200, 8000)), 2)
                cur.execute(
                    "INSERT INTO utility_bills "
                    "(facility_id, billing_quarter, utility_type, amount, usage_quantity, usage_unit) "
                    "VALUES (?,?,?,?,?,?)",
                    (f["facility_id"], q, ut, amount, usage, USAGE_UNITS[ut]),
                )

    # Table 3: maintenance_logs  (4-9 per facility)
    cur.execute("""
        CREATE TABLE maintenance_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            facility_id TEXT NOT NULL,
            scheduled_date TEXT NOT NULL,
            maintenance_type TEXT NOT NULL,
            description TEXT NOT NULL,
            estimated_cost REAL NOT NULL,
            actual_cost REAL,
            status TEXT NOT NULL,
            contractor TEXT,
            FOREIGN KEY (facility_id) REFERENCES facilities(facility_id)
        )
    """)
    for f in facilities:
        num_logs = int(np.random.randint(4, 10))
        for _ in range(num_logs):
            mtype = str(np.random.choice(MAINTENANCE_TYPES))
            date = fake.date_between_dates(
                date_start=pd.Timestamp("2025-01-01"),
                date_end=pd.Timestamp("2025-12-31"),
            ).isoformat()
            est_cost = round(float(np.random.uniform(500, 25000)), 2)
            status = str(np.random.choice(MAINTENANCE_STATUSES))
            act_cost = (
                round(est_cost * float(np.random.uniform(0.8, 1.3)), 2)
                if status == "completed"
                else None
            )
            contractor = (
                fake.company() if status in ("completed", "in_progress") else None
            )
            desc = f"{mtype.replace('_', ' ').title()} - {fake.sentence()}"
            cur.execute(
                "INSERT INTO maintenance_logs "
                "(facility_id, scheduled_date, maintenance_type, description, "
                "estimated_cost, actual_cost, status, contractor) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (f["facility_id"], date, mtype, desc, est_cost, act_cost,
                 status, contractor),
            )

    # Table 4: program_attendance  (5-11 programs x 2-5 sessions each)
    cur.execute("""
        CREATE TABLE program_attendance (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            facility_id TEXT NOT NULL,
            program_name TEXT NOT NULL,
            session_date TEXT NOT NULL,
            max_capacity INTEGER NOT NULL,
            registered INTEGER NOT NULL,
            attended INTEGER NOT NULL,
            FOREIGN KEY (facility_id) REFERENCES facilities(facility_id)
        )
    """)
    for f_idx, f in enumerate(facilities):
        num_programs = int(np.random.randint(5, 12))
        n_pick = min(num_programs, len(PROGRAM_TYPES))
        assigned = list(np.random.choice(PROGRAM_TYPES, n_pick, replace=False))
        for prog in assigned:
            num_sessions = int(np.random.randint(2, 6))
            for _ in range(num_sessions):
                date = fake.date_between_dates(
                    date_start=pd.Timestamp("2025-01-01"),
                    date_end=pd.Timestamp("2025-12-31"),
                ).isoformat()
                max_cap = int(np.random.randint(15, 60))
                if f_idx in underutil_set:
                    upper = max(3, int(max_cap * 0.35))
                    reg = int(np.random.randint(2, upper + 1))
                else:
                    lower = max(1, int(max_cap * 0.45))
                    reg = int(np.random.randint(lower, max_cap + 1))
                att_lo = max(1, int(reg * 0.5))
                att = int(np.random.randint(att_lo, reg + 1))
                cur.execute(
                    "INSERT INTO program_attendance "
                    "(facility_id, program_name, session_date, max_capacity, "
                    "registered, attended) VALUES (?,?,?,?,?,?)",
                    (f["facility_id"], prog, date, max_cap, reg, att),
                )

    # Table 5: capital_improvement_requests  (2-5 per facility)
    cur.execute("""
        CREATE TABLE capital_improvement_requests (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            facility_id TEXT NOT NULL,
            fiscal_year INTEGER NOT NULL,
            project_description TEXT NOT NULL,
            requested_amount REAL NOT NULL,
            priority TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (facility_id) REFERENCES facilities(facility_id)
        )
    """)
    for f in facilities:
        num_req = int(np.random.randint(2, 6))
        for _ in range(num_req):
            fy = int(np.random.choice([2024, 2025, 2026]))
            cat = str(np.random.choice(CAPITAL_CATEGORIES))
            desc = f"{cat.replace('_', ' ').title()} - {fake.sentence()}"
            amount = round(float(np.random.uniform(10000, 350000)), 2)
            priority = str(np.random.choice(CAPITAL_PRIORITIES))
            status = str(np.random.choice(CAPITAL_STATUSES))
            cur.execute(
                "INSERT INTO capital_improvement_requests "
                "(facility_id, fiscal_year, project_description, requested_amount, "
                "priority, category, status) VALUES (?,?,?,?,?,?,?)",
                (f["facility_id"], fy, desc, amount, priority, cat, status),
            )

    conn.commit()
    conn.close()

    # ================================================================
    # WORKSPACE FILES
    # ================================================================

    # A. Monthly occupancy survey CSVs  (scalable — count = num_survey_months)
    for m_idx in range(num_survey_months):
        month_num = (m_idx % 12) + 1
        year = 2023 + m_idx // 12
        rows = []
        for f_idx, fac in enumerate(facilities):
            cap = fac["capacity"]
            if f_idx in underutil_set:
                avg_vis = int(round(cap * float(np.random.uniform(0.08, 0.27))))
            else:
                avg_vis = int(round(cap * float(np.random.uniform(0.40, 0.88))))
            peak_vis = int(round(avg_vis * float(np.random.uniform(1.1, 1.6))))
            days_open = int(np.random.randint(20, 27))
            rows.append({
                "facility_id": fac["facility_id"],
                "survey_month": f"{year}-{month_num:02d}",
                "avg_daily_visitors": avg_vis,
                "peak_daily_visitors": peak_vis,
                "days_operational": days_open,
            })
        df = pd.DataFrame(rows)
        fname = f"occupancy_survey_{year}_{month_num:02d}.csv"
        df.to_csv(os.path.join(workspace, fname), index=False)

    # B. Consolidation policy YAML  (fixed config)
    policy = {
        "occupancy_threshold": 0.30,
        "scoring_weights": {
            "occupancy": 0.30,
            "utility_cost_efficiency": 0.20,
            "maintenance_burden": 0.15,
            "capital_exposure": 0.20,
            "program_utilization": 0.15,
        },
        "benchmarks": {
            "utility_cost_per_sqft_annual": 15.00,
            "capital_request_threshold": 200000.00,
            "program_attendance_threshold": 0.40,
        },
        "recommendation_thresholds": {
            "closure": 70.0,
            "shared_space": 45.0,
        },
        "recommendation_rules": (
            "consolidation_score >= 70.0 -> closure; "
            ">= 45.0 -> shared_space; "
            "otherwise -> retain_with_review"
        ),
    }
    with open(os.path.join(workspace, "consolidation_policy.yaml"), "w") as fp:
        yaml.dump(policy, fp, default_flow_style=False, sort_keys=False)

    # C. Annual budgets JSON  (fixed — the ONLY source of operating budgets)
    budget_data = {f["facility_id"]: f["annual_operating_budget"] for f in facilities}
    with open(os.path.join(workspace, "annual_budgets.json"), "w") as fp:
        json.dump(budget_data, fp, indent=2)

    # D. Metric definitions Markdown  (fixed reference doc)
    definitions_md = """\
# Metric Definitions for Facility Consolidation Analysis

## Annual Utility Cost
Sum of the `amount` field from all quarterly utility billing records for the facility.

## Annual Maintenance Cost
For maintenance logs with status `completed`, use the `actual_cost` field.
For all other statuses (`scheduled`, `deferred`, `in_progress`), use the `estimated_cost` field.
Sum all values to obtain the annual maintenance cost.

## Total Pending Capital
Sum of `requested_amount` from capital improvement requests where `status` is `pending`.

## Cost Per Square Foot
`annual_utility_cost` divided by `square_footage`.

## Maintenance Burden Percentage
(`annual_maintenance_cost` / `annual_operating_budget`) * 100.

## Average Occupancy Rate
Compute the mean of `avg_daily_visitors` across all monthly survey records for the facility,
then divide by the facility's `capacity`.

## Average Program Attendance Rate
For each program session record at the facility, compute `attended / max_capacity`.
The facility's average program attendance rate is the mean of these ratios across all session records.

## Component Scores
Each scoring component is calculated as follows and clamped to the range [0, 100]:

- Occupancy: ((occupancy_threshold - avg_occupancy_rate) / occupancy_threshold) * 100
- Utility Cost Efficiency: (cost_per_sqft / utility_cost_per_sqft_annual) * 100
- Maintenance Burden: maintenance_burden_pct (already on a 0-100 scale, clamp to max 100)
- Capital Exposure: (total_pending_capital / capital_request_threshold) * 100
- Program Utilization: ((program_attendance_threshold - avg_program_attendance_rate) / program_attendance_threshold) * 100

## Consolidation Score
Weighted sum of all component scores using the scoring weights from the policy configuration.
Round the final score to one decimal place.
"""
    with open(os.path.join(workspace, "metric_definitions.md"), "w") as fp:
        fp.write(definitions_md)

    # E. Zone adjacency TXT  (fixed reference)
    zone_adj = """\
# Zone Adjacency Map
# Facilities in adjacent zones may be candidates for shared-space consolidation
North - Central
South - Central
East - Central
West - Central
North - East
South - West
"""
    with open(os.path.join(workspace, "zone_adjacency.txt"), "w") as fp:
        fp.write(zone_adj)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
