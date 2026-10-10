"""
Data generation for turbine overhaul regulatory compliance task.
Generates database tables and workspace files for cross-referencing
emission logs, spare parts, permits, and technician certifications.
"""

import argparse
import json
import os
import random
import sqlite3

import numpy as np
import pandas as pd
import yaml
from faker import Faker

# ── Scale parameters (v0 base) ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 160,      # v1 = 2× base
    "num_workspace_files": 20,  # v1 = base + N = 10 + 10
}

# ── Deterministic seeds ─────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ── Domain constants ────────────────────────────────────────────────────────
TURBINE_MODELS = [
    "GE-7FA", "GE-9HA", "Siemens-SGT800", "Siemens-SGT6-5000F",
    "MHI-M501J", "MHI-M701F", "Ansaldo-AE94.3A", "Solar-Titan250",
]

POLLUTANTS = ["NOx", "SO2", "CO", "PM2.5", "VOC"]

CERT_TYPES = [
    "combustion_specialist",
    "emissions_monitoring",
    "rotor_balancing",
    "blade_inspection",
    "control_systems",
    "fuel_systems",
    "exhaust_systems",
    "vibration_analysis",
]

CERT_LEVELS = ["Level-1", "Level-2", "Level-3"]

PART_CATEGORIES = [
    "combustion_liner", "transition_piece", "turbine_blade",
    "compressor_blade", "bearing_assembly", "seal_ring",
    "fuel_nozzle", "igniter", "thermocouple", "filter_element",
    "gasket_set", "control_valve", "oil_pump", "exhaust_duct_section",
]

TASK_TYPES = [
    "combustion_inspection", "hot_gas_path_inspection",
    "major_overhaul", "compressor_wash", "blade_replacement",
    "bearing_replacement", "fuel_nozzle_overhaul",
    "control_system_calibration", "exhaust_system_repair",
    "vibration_assessment",
]

SEVERITY_MAP = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def create_tables(conn):
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS turbines (
        turbine_id TEXT PRIMARY KEY,
        model TEXT,
        site_id TEXT,
        location TEXT,
        rated_capacity_mw REAL,
        installation_year INTEGER,
        status TEXT,
        last_overhaul_date TEXT
    );

    CREATE TABLE IF NOT EXISTS emission_logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        turbine_id TEXT,
        pollutant TEXT,
        reading_value REAL,
        unit TEXT,
        measurement_date TEXT,
        FOREIGN KEY (turbine_id) REFERENCES turbines(turbine_id)
    );

    CREATE TABLE IF NOT EXISTS spare_parts (
        part_id TEXT PRIMARY KEY,
        part_number TEXT,
        part_name TEXT,
        category TEXT,
        compatible_models TEXT,
        qty_on_hand INTEGER,
        reorder_point INTEGER,
        lead_time_days INTEGER,
        unit_cost REAL
    );

    CREATE TABLE IF NOT EXISTS permits (
        permit_id TEXT PRIMARY KEY,
        site_id TEXT,
        pollutant TEXT,
        limit_value REAL,
        unit TEXT,
        effective_date TEXT,
        expiry_date TEXT,
        special_conditions TEXT
    );

    CREATE TABLE IF NOT EXISTS technicians (
        tech_id TEXT PRIMARY KEY,
        name TEXT,
        cert_type TEXT,
        cert_level TEXT,
        cert_expiry TEXT,
        home_site_id TEXT,
        is_active INTEGER
    );

    CREATE TABLE IF NOT EXISTS overhaul_tasks (
        task_id TEXT PRIMARY KEY,
        turbine_id TEXT,
        task_type TEXT,
        task_name TEXT,
        required_cert_type TEXT,
        required_cert_level TEXT,
        required_parts TEXT,
        estimated_hours REAL,
        priority TEXT,
        FOREIGN KEY (turbine_id) REFERENCES turbines(turbine_id)
    );
    """)
    conn.commit()


def generate_turbines(conn, n_rows):
    """Generate turbine records. ~15% are scheduled_overhaul."""
    rows = []
    sites = [f"SITE-{i:03d}" for i in range(1, max(6, n_rows // 12) + 1)]
    cities = [fake.city() for _ in sites]
    statuses = ["operational", "scheduled_overhaul", "maintenance", "standby"]
    status_weights = [0.55, 0.15, 0.15, 0.15]

    for i in range(1, n_rows + 1):
        site_idx = (i - 1) % len(sites)
        model = random.choice(TURBINE_MODELS)
        status = random.choices(statuses, weights=status_weights, k=1)[0]
        inst_year = random.randint(2005, 2022)
        last_oh = fake.date_between_dates(
            date_start=pd.Timestamp(f"{inst_year}-01-01"),
            date_end=pd.Timestamp("2025-06-01"),
        ).isoformat()
        rows.append((
            f"TRB-{i:04d}", model, sites[site_idx], cities[site_idx],
            round(random.uniform(50, 500), 1), inst_year, status, last_oh,
        ))

    pd.DataFrame(rows, columns=[
        "turbine_id", "model", "site_id", "location",
        "rated_capacity_mw", "installation_year", "status", "last_overhaul_date",
    ]).to_sql("turbines", conn, if_exists="append", index=False)
    return rows


def generate_emission_logs(conn, turbine_rows, n_rows):
    """Generate emission log entries spread across turbines/pollutants."""
    records = []
    log_id = 1
    turbine_ids = [r[0] for r in turbine_rows]
    units_map = {"NOx": "ppm", "SO2": "ppm", "CO": "ppm", "PM2.5": "mg/m3", "VOC": "ppm"}

    while len(records) < n_rows:
        tid = random.choice(turbine_ids)
        poll = random.choice(POLLUTANTS)
        val = round(random.uniform(0.5, 120.0), 2)
        date = fake.date_between_dates(
            date_start=pd.Timestamp("2024-01-01"),
            date_end=pd.Timestamp("2026-03-31"),
        ).isoformat()
        records.append((log_id, tid, poll, val, units_map[poll], date))
        log_id += 1

    pd.DataFrame(records, columns=[
        "log_id", "turbine_id", "pollutant", "reading_value", "unit", "measurement_date",
    ]).to_sql("emission_logs", conn, if_exists="append", index=False)
    return records


def generate_spare_parts(conn, n_rows):
    """Generate spare parts inventory."""
    rows = []
    part_num = 1
    while len(rows) < n_rows:
        cat = PART_CATEGORIES[part_num % len(PART_CATEGORIES)]
        n_compat = random.randint(1, 4)
        compat = ",".join(random.sample(TURBINE_MODELS, n_compat))
        qty = random.randint(0, 30)
        reorder = random.randint(3, 10)
        lead = random.randint(7, 90)
        cost = round(random.uniform(500, 50000), 2)
        part_name = f"{cat.replace('_', ' ').title()} Type-{random.choice('ABCDEFGH')}{random.randint(1,99)}"
        rows.append((
            f"SP-{part_num:04d}", f"PN-{part_num:06d}", part_name,
            cat, compat, qty, reorder, lead, cost,
        ))
        part_num += 1

    pd.DataFrame(rows, columns=[
        "part_id", "part_number", "part_name", "category",
        "compatible_models", "qty_on_hand", "reorder_point",
        "lead_time_days", "unit_cost",
    ]).to_sql("spare_parts", conn, if_exists="append", index=False)
    return rows


def generate_permits(conn, turbine_rows, n_rows):
    """Generate environmental permits per site per pollutant."""
    sites = list({r[2] for r in turbine_rows})
    rows = []
    pid = 1
    units_map = {"NOx": "ppm", "SO2": "ppm", "CO": "ppm", "PM2.5": "mg/m3", "VOC": "ppm"}
    limit_ranges = {
        "NOx": (20, 60), "SO2": (15, 45), "CO": (30, 80),
        "PM2.5": (5, 25), "VOC": (10, 40),
    }

    while len(rows) < n_rows:
        site = sites[pid % len(sites)]
        poll = POLLUTANTS[pid % len(POLLUTANTS)]
        lo, hi = limit_ranges[poll]
        limit_val = round(random.uniform(lo, hi), 1)
        eff = fake.date_between_dates(
            date_start=pd.Timestamp("2023-01-01"),
            date_end=pd.Timestamp("2025-01-01"),
        ).isoformat()
        exp = fake.date_between_dates(
            date_start=pd.Timestamp("2026-06-01"),
            date_end=pd.Timestamp("2028-12-31"),
        ).isoformat()
        cond = random.choice([
            "Continuous monitoring required",
            "Quarterly reporting mandatory",
            "Annual stack test required",
            "Monthly calibration check",
            "Real-time data submission to regulator",
        ])
        rows.append((
            f"PRM-{pid:04d}", site, poll, limit_val,
            units_map[poll], eff, exp, cond,
        ))
        pid += 1

    pd.DataFrame(rows, columns=[
        "permit_id", "site_id", "pollutant", "limit_value",
        "unit", "effective_date", "expiry_date", "special_conditions",
    ]).to_sql("permits", conn, if_exists="append", index=False)
    return rows


def generate_technicians(conn, turbine_rows, n_rows):
    """Generate technician records with certifications."""
    sites = list({r[2] for r in turbine_rows})
    rows = []
    for i in range(1, n_rows + 1):
        cert_type = CERT_TYPES[(i - 1) % len(CERT_TYPES)]
        cert_level = random.choice(CERT_LEVELS)
        # ~20% have expired certifications
        if random.random() < 0.2:
            exp = fake.date_between_dates(
                date_start=pd.Timestamp("2025-01-01"),
                date_end=pd.Timestamp("2026-03-31"),
            ).isoformat()
        else:
            exp = fake.date_between_dates(
                date_start=pd.Timestamp("2026-06-01"),
                date_end=pd.Timestamp("2028-12-31"),
            ).isoformat()
        is_active = 1 if random.random() < 0.85 else 0
        rows.append((
            f"TECH-{i:04d}", fake.name(), cert_type, cert_level,
            exp, random.choice(sites), is_active,
        ))

    pd.DataFrame(rows, columns=[
        "tech_id", "name", "cert_type", "cert_level",
        "cert_expiry", "home_site_id", "is_active",
    ]).to_sql("technicians", conn, if_exists="append", index=False)
    return rows


def generate_overhaul_tasks(conn, turbine_rows, spare_parts_rows, n_rows):
    """Generate overhaul tasks for turbines with scheduled_overhaul status."""
    scheduled = [r for r in turbine_rows if r[6] == "scheduled_overhaul"]
    if not scheduled:
        # Ensure at least some scheduled turbines
        scheduled = turbine_rows[:5]

    rows = []
    task_id = 1
    # Map task types to required cert types
    task_cert_map = {
        "combustion_inspection": "combustion_specialist",
        "hot_gas_path_inspection": "blade_inspection",
        "major_overhaul": "combustion_specialist",
        "compressor_wash": "emissions_monitoring",
        "blade_replacement": "blade_inspection",
        "bearing_replacement": "rotor_balancing",
        "fuel_nozzle_overhaul": "fuel_systems",
        "control_system_calibration": "control_systems",
        "exhaust_system_repair": "exhaust_systems",
        "vibration_assessment": "vibration_analysis",
    }

    all_part_ids = [r[0] for r in spare_parts_rows]

    # Distribute tasks across scheduled turbines
    while len(rows) < n_rows:
        turb = scheduled[task_id % len(scheduled)]
        tid = turb[0]
        tt = TASK_TYPES[task_id % len(TASK_TYPES)]
        cert_type = task_cert_map[tt]
        cert_level = random.choice(["Level-1", "Level-2", "Level-3"])
        # Each task requires 1-3 parts
        n_parts = random.randint(1, 3)
        req_parts = json.dumps(random.sample(all_part_ids, min(n_parts, len(all_part_ids))))
        est_hours = round(random.uniform(4, 80), 1)
        priority = random.choice(["HIGH", "MEDIUM", "LOW"])
        task_name = f"{tt.replace('_', ' ').title()} - {tid}"
        rows.append((
            f"OHT-{task_id:04d}", tid, tt, task_name,
            cert_type, cert_level, req_parts, est_hours, priority,
        ))
        task_id += 1

    pd.DataFrame(rows, columns=[
        "task_id", "turbine_id", "task_type", "task_name",
        "required_cert_type", "required_cert_level", "required_parts",
        "estimated_hours", "priority",
    ]).to_sql("overhaul_tasks", conn, if_exists="append", index=False)
    return rows


# ── Workspace file generation ───────────────────────────────────────────────

def generate_workspace(workspace, conn, turbine_rows, spare_parts_rows, emission_logs):
    os.makedirs(workspace, exist_ok=True)
    n_files = SCALE["num_workspace_files"]

    sites = sorted({r[2] for r in turbine_rows})

    # ── Fixed config files (not counted in SCALE) ───────────────────────────

    # 1. compliance_rules.yaml — thresholds and business rules
    compliance_rules = {
        "emission_compliance": {
            "evaluation_window_days": 365,
            "reference_date": "2026-04-20",
            "exceedance_tolerance_pct": 10.0,
            "max_exceedances_before_flag": 2,
            "severity_mapping": {
                "exceedance_pct_ge_50": "HIGH",
                "exceedance_pct_ge_20": "MEDIUM",
                "exceedance_pct_lt_20": "LOW",
            },
        },
        "parts_compliance": {
            "min_stock_multiplier": 1.0,
            "critical_lead_time_days": 30,
            "shortage_severity": {
                "zero_stock": "HIGH",
                "below_reorder": "MEDIUM",
                "adequate": "OK",
            },
        },
        "technician_compliance": {
            "cert_must_be_valid_through": "2026-07-31",
            "required_active_status": True,
            "level_hierarchy": ["Level-1", "Level-2", "Level-3"],
            "level_satisfies_or_above": True,
        },
        "priority_order": ["HIGH", "MEDIUM", "LOW"],
    }
    with open(os.path.join(workspace, "compliance_rules.yaml"), "w") as f:
        yaml.dump(compliance_rules, f, default_flow_style=False, sort_keys=False)

    # 2. certification_requirements.md
    cert_req_lines = [
        "# Certification Requirements for Turbine Overhaul\n",
        "Each overhaul task specifies a required certification type and minimum level.",
        "A technician satisfies the requirement if:",
        "- Their cert_type matches the task's required_cert_type exactly.",
        "- Their cert_level is equal to or higher than the required level (Level-3 > Level-2 > Level-1).",
        "- Their certification has not expired as of the validity date in compliance_rules.yaml.",
        "- They are marked as active.\n",
        "If no qualifying technician is found for a task, the task is flagged as a TECHNICIAN gap.",
        "The gap severity is HIGH if priority is HIGH, MEDIUM if priority is MEDIUM, LOW otherwise.\n",
    ]
    with open(os.path.join(workspace, "certification_requirements.md"), "w") as f:
        f.write("\n".join(cert_req_lines))

    # 3. overhaul_policy.json — output format specs
    overhaul_policy = {
        "checklist_output_file": "compliance_checklist.csv",
        "gap_report_output_file": "gap_report.csv",
        "checklist_columns": [
            "turbine_id", "model", "site_id", "emission_status",
            "parts_status", "technician_status", "overall_status",
        ],
        "gap_report_columns": [
            "turbine_id", "task_id", "gap_type", "detail", "severity",
        ],
        "emission_status_values": ["COMPLIANT", "NON-COMPLIANT"],
        "parts_status_values": ["AVAILABLE", "SHORTAGE"],
        "technician_status_values": ["COVERED", "GAP"],
        "overall_status_rule": "NON-COMPLIANT if any sub-status is NON-COMPLIANT or SHORTAGE or GAP, else COMPLIANT",
        "sort_order": {
            "checklist": ["turbine_id"],
            "gap_report": ["severity_desc", "turbine_id", "task_id"],
        },
        "severity_sort_key": {"HIGH": 1, "MEDIUM": 2, "LOW": 3},
    }
    with open(os.path.join(workspace, "overhaul_policy.json"), "w") as f:
        json.dump(overhaul_policy, f, indent=2)

    # ── Scalable data files ─────────────────────────────────────────────────

    # Distribute n_files across categories
    # Category A: site emission summaries (CSV) — ~ 40% of files
    # Category B: technician availability schedules (JSON) — ~ 30% of files
    # Category C: pending parts orders (TXT) — ~ 20% of files
    # Category D: site inspection notes (YAML) — ~ 10% of files

    n_a = max(2, int(n_files * 0.4))
    n_b = max(2, int(n_files * 0.3))
    n_c = max(2, int(n_files * 0.2))
    n_d = max(1, n_files - n_a - n_b - n_c)

    # Cursor for DB reads
    cur = conn.cursor()

    # Category A: site emission summary CSVs
    # These contain per-turbine average emissions that are NOT in the DB
    # (the DB has individual readings; these files add rolling averages + trend)
    for i in range(n_a):
        site = sites[i % len(sites)]
        cur.execute("""
            SELECT e.turbine_id, e.pollutant,
                   ROUND(AVG(e.reading_value), 2) as avg_reading,
                   COUNT(*) as num_readings,
                   MAX(e.measurement_date) as latest_date
            FROM emission_logs e
            JOIN turbines t ON e.turbine_id = t.turbine_id
            WHERE t.site_id = ?
            GROUP BY e.turbine_id, e.pollutant
        """, (site,))
        rows_data = cur.fetchall()
        if not rows_data:
            # Generate synthetic rows if site has no data
            site_turbines = [r[0] for r in turbine_rows if r[2] == site]
            rows_data = []
            for st in site_turbines[:3]:
                for p in POLLUTANTS[:3]:
                    rows_data.append((st, p, round(random.uniform(5, 50), 2), random.randint(1, 10), "2026-03-01"))

        df = pd.DataFrame(rows_data, columns=[
            "turbine_id", "pollutant", "avg_reading", "num_readings", "latest_date",
        ])
        # Add a trend column (not in DB) — RISING / STABLE / DECLINING
        np.random.seed(SEED + i)
        df["trend"] = np.random.choice(["RISING", "STABLE", "DECLINING"], size=len(df), p=[0.3, 0.4, 0.3])
        fname = f"emission_summary_{site.lower().replace('-', '_')}.csv"
        df.to_csv(os.path.join(workspace, fname), index=False)

    # Category B: technician availability schedules (JSON)
    # Contains availability windows NOT stored in DB
    cur.execute("SELECT tech_id, name, home_site_id FROM technicians")
    all_techs = cur.fetchall()
    techs_per_file = max(1, len(all_techs) // n_b)
    for i in range(n_b):
        start = i * techs_per_file
        end = start + techs_per_file if i < n_b - 1 else len(all_techs)
        chunk = all_techs[start:end]
        schedule = {}
        for tech_id, name, home_site in chunk:
            # Available date ranges in 2026
            n_windows = random.randint(1, 3)
            windows = []
            for _ in range(n_windows):
                start_d = fake.date_between_dates(
                    date_start=pd.Timestamp("2026-04-01"),
                    date_end=pd.Timestamp("2026-09-01"),
                )
                end_d = fake.date_between_dates(
                    date_start=start_d,
                    date_end=pd.Timestamp("2026-12-31"),
                )
                windows.append({
                    "start": start_d.isoformat(),
                    "end": end_d.isoformat(),
                })
            schedule[tech_id] = {
                "name": name,
                "home_site": home_site,
                "available_windows": windows,
                "max_weekly_hours": random.choice([40, 48, 56]),
            }
        fname = f"technician_schedule_batch_{i + 1:02d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(schedule, f, indent=2)

    # Category C: pending parts orders (TXT)
    # These contain incoming orders that add to available stock — critical info
    cur.execute("SELECT part_id, part_number, part_name FROM spare_parts")
    all_parts = cur.fetchall()
    parts_per_file = max(1, len(all_parts) // n_c)
    for i in range(n_c):
        start = i * parts_per_file
        end = start + parts_per_file if i < n_c - 1 else len(all_parts)
        chunk = all_parts[start:end]
        lines = ["PENDING PARTS ORDERS", f"Generated: 2026-04-18", "=" * 50, ""]
        for part_id, part_num, part_name in chunk:
            # ~30% have pending orders
            if random.random() < 0.3:
                qty_incoming = random.randint(1, 15)
                eta = fake.date_between_dates(
                    date_start=pd.Timestamp("2026-04-20"),
                    date_end=pd.Timestamp("2026-06-30"),
                ).isoformat()
                lines.append(f"PART_ID: {part_id}")
                lines.append(f"  Part Number: {part_num}")
                lines.append(f"  Description: {part_name}")
                lines.append(f"  Qty Incoming: {qty_incoming}")
                lines.append(f"  ETA: {eta}")
                lines.append(f"  Status: IN_TRANSIT")
                lines.append("")
        if len(lines) <= 4:
            lines.append("No pending orders in this batch.")
        fname = f"pending_orders_batch_{i + 1:02d}.txt"
        with open(os.path.join(workspace, fname), "w") as f:
            f.write("\n".join(lines))

    # Category D: site inspection notes (YAML)
    # Contains additional restrictions / notes per site — complements permits
    for i in range(n_d):
        site = sites[i % len(sites)]
        cur.execute("""
            SELECT turbine_id, model, status FROM turbines WHERE site_id = ?
        """, (site,))
        site_turbs = cur.fetchall()
        notes = {
            "site_id": site,
            "last_inspection_date": fake.date_between_dates(
                date_start=pd.Timestamp("2025-06-01"),
                date_end=pd.Timestamp("2026-03-01"),
            ).isoformat(),
            "inspector": fake.name(),
            "turbines": {},
        }
        for tid, model, status in site_turbs:
            notes["turbines"][tid] = {
                "model": model,
                "condition": random.choice(["good", "fair", "needs_attention"]),
                "notes": random.choice([
                    "Routine inspection passed.",
                    "Minor corrosion detected on exhaust section.",
                    "Vibration levels slightly elevated.",
                    "Recent blade tip repair completed.",
                    "Control system firmware update pending.",
                ]),
            }
        fname = f"inspection_notes_{site.lower().replace('-', '_')}.yaml"
        with open(os.path.join(workspace, fname), "w") as f:
            yaml.dump(notes, f, default_flow_style=False, sort_keys=False)


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

    turbine_rows = generate_turbines(conn, n)
    emission_logs = generate_emission_logs(conn, turbine_rows, n)
    spare_parts_rows = generate_spare_parts(conn, n)
    generate_permits(conn, turbine_rows, n)
    generate_technicians(conn, turbine_rows, n)
    generate_overhaul_tasks(conn, turbine_rows, spare_parts_rows, n)

    generate_workspace(args.workspace, conn, turbine_rows, spare_parts_rows, emission_logs)

    conn.commit()
    conn.close()
    print(f"Database written to {args.db_path}")
    print(f"Workspace generated at {args.workspace}")


if __name__ == "__main__":
    main()
