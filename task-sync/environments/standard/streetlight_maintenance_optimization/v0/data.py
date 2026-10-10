"""
Streetlight Maintenance Budget Allocation - Data Generation Script
Generates database and workspace files for the streetlight maintenance optimization task.
"""

import argparse
import json
import os
import random
import sqlite3
import yaml

import numpy as np
import pandas as pd
from faker import Faker

# ── Scale parameters (v0 base) ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 100,       # v0 base; v1 = 2x, v2 = 4x, v3 = 8x
    "num_workspace_files": 10,   # v0 base; v1 = +N, v2 = +2N, v3 = +3N
}

# ── Deterministic seeding ────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ── Domain constants ─────────────────────────────────────────────────────────
NUM_ZONES = 8
LIGHT_TYPES = ["LED", "HPS", "Metal Halide", "Fluorescent"]
ISSUE_TYPES = ["Bulb Failure", "Electrical Fault", "Pole Damage", "Wiring Issue",
               "Sensor Malfunction", "Timer Failure", "Corrosion", "Vandalism"]
COMPLAINT_TYPES = ["Dark Street", "Flickering Light", "Broken Fixture",
                   "Light Pollution", "Delayed Repair", "Buzzing Noise"]
SEVERITY_LEVELS = ["Low", "Medium", "High", "Critical"]
ACCIDENT_SEVERITY = ["Minor", "Moderate", "Severe", "Fatal"]
STATUS_OPTIONS = ["Completed", "Pending", "In Progress"]


def create_tables(conn):
    """Create all database tables."""
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS zones (
            zone_id INTEGER PRIMARY KEY,
            zone_name TEXT NOT NULL,
            district TEXT NOT NULL,
            population INTEGER NOT NULL,
            area_sqkm REAL NOT NULL,
            num_streetlights INTEGER NOT NULL,
            current_annual_budget REAL NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS streetlights (
            light_id INTEGER PRIMARY KEY,
            zone_id INTEGER NOT NULL,
            light_type TEXT NOT NULL,
            wattage INTEGER NOT NULL,
            install_date TEXT NOT NULL,
            last_maintenance_date TEXT,
            status TEXT NOT NULL,
            pole_material TEXT NOT NULL,
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS work_orders (
            order_id INTEGER PRIMARY KEY,
            light_id INTEGER NOT NULL,
            zone_id INTEGER NOT NULL,
            issue_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            date_reported TEXT NOT NULL,
            date_completed TEXT,
            repair_cost REAL NOT NULL,
            technician_id TEXT NOT NULL,
            status TEXT NOT NULL,
            parts_replaced TEXT,
            FOREIGN KEY (light_id) REFERENCES streetlights(light_id),
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS energy_consumption (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            kwh_consumed REAL NOT NULL,
            cost_per_kwh REAL NOT NULL,
            total_cost REAL NOT NULL,
            peak_demand_kw REAL NOT NULL,
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS citizen_complaints (
            complaint_id INTEGER PRIMARY KEY,
            zone_id INTEGER NOT NULL,
            light_id INTEGER,
            complaint_type TEXT NOT NULL,
            date_filed TEXT NOT NULL,
            date_resolved TEXT,
            priority TEXT NOT NULL,
            description TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id),
            FOREIGN KEY (light_id) REFERENCES streetlights(light_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS traffic_accidents (
            accident_id INTEGER PRIMARY KEY,
            zone_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            time_of_day TEXT NOT NULL,
            severity TEXT NOT NULL,
            lighting_related INTEGER NOT NULL,
            injuries INTEGER NOT NULL,
            fatalities INTEGER NOT NULL,
            nearest_light_id INTEGER,
            road_type TEXT NOT NULL,
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id),
            FOREIGN KEY (nearest_light_id) REFERENCES streetlights(light_id)
        )
    """)

    conn.commit()


def generate_zones(conn):
    """Generate zone data."""
    districts = ["North", "South", "East", "West"]
    zones = []
    for i in range(1, NUM_ZONES + 1):
        zone = (
            i,
            f"Zone-{chr(64 + i)}",
            districts[(i - 1) % len(districts)],
            random.randint(8000, 50000),
            round(random.uniform(2.0, 15.0), 2),
            random.randint(80, 400),
            round(random.uniform(50000, 300000), 2),
        )
        zones.append(zone)
    conn.executemany(
        "INSERT INTO zones VALUES (?, ?, ?, ?, ?, ?, ?)", zones
    )
    conn.commit()
    return zones


def generate_streetlights(conn, zones):
    """Generate streetlight inventory."""
    rows = SCALE["rows_per_table"]
    lights = []
    light_id = 1
    zone_ids = [z[0] for z in zones]
    zone_light_counts = {z[0]: z[5] for z in zones}

    # Distribute lights across zones proportionally, up to rows count
    total_db_lights = rows
    weights = [zone_light_counts[zid] for zid in zone_ids]
    total_w = sum(weights)
    zone_alloc = {}
    allocated = 0
    for idx, zid in enumerate(zone_ids):
        if idx == len(zone_ids) - 1:
            zone_alloc[zid] = total_db_lights - allocated
        else:
            n = max(5, int(total_db_lights * weights[idx] / total_w))
            zone_alloc[zid] = n
            allocated += n

    pole_materials = ["Steel", "Aluminum", "Concrete", "Fiberglass"]
    statuses = ["Active", "Inactive", "Under Repair", "Decommissioned"]

    for zid in zone_ids:
        for _ in range(zone_alloc[zid]):
            install_year = random.randint(2005, 2023)
            install_date = f"{install_year}-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
            last_maint = None
            if random.random() > 0.2:
                my = random.randint(install_year, 2025)
                last_maint = f"{my}-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
            lt = random.choice(LIGHT_TYPES)
            wattage_map = {"LED": [50, 100, 150], "HPS": [150, 250, 400],
                           "Metal Halide": [175, 250, 400], "Fluorescent": [40, 60, 80]}
            lights.append((
                light_id, zid, lt,
                random.choice(wattage_map[lt]),
                install_date, last_maint,
                random.choices(statuses, weights=[70, 10, 12, 8])[0],
                random.choice(pole_materials),
            ))
            light_id += 1

    conn.executemany(
        "INSERT INTO streetlights VALUES (?, ?, ?, ?, ?, ?, ?, ?)", lights
    )
    conn.commit()
    return lights


def generate_work_orders(conn, lights, zones):
    """Generate historical repair work orders."""
    rows = SCALE["rows_per_table"]
    zone_ids = [z[0] for z in zones]
    light_by_zone = {}
    for l in lights:
        light_by_zone.setdefault(l[1], []).append(l[0])

    orders = []
    for oid in range(1, rows + 1):
        zid = random.choice(zone_ids)
        lid = random.choice(light_by_zone[zid])
        issue = random.choice(ISSUE_TYPES)
        severity = random.choices(SEVERITY_LEVELS, weights=[25, 35, 25, 15])[0]
        year = random.randint(2022, 2025)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        date_reported = f"{year}-{month:02d}-{day:02d}"
        status = random.choices(STATUS_OPTIONS, weights=[60, 25, 15])[0]
        date_completed = None
        if status == "Completed":
            days_to_fix = random.randint(1, 30)
            from datetime import datetime, timedelta
            dr = datetime(year, month, day)
            dc = dr + timedelta(days=days_to_fix)
            date_completed = dc.strftime("%Y-%m-%d")

        cost_map = {"Low": (50, 200), "Medium": (200, 600),
                    "High": (600, 1500), "Critical": (1500, 4000)}
        lo, hi = cost_map[severity]
        repair_cost = round(random.uniform(lo, hi), 2)

        tech_id = f"TECH-{random.randint(1, 20):03d}"
        parts = random.choice(["Bulb", "Ballast", "Wiring", "Pole Section",
                               "Sensor", "Timer", "Fuse", "None"])

        orders.append((
            oid, lid, zid, issue, severity, date_reported,
            date_completed, repair_cost, tech_id, status, parts
        ))

    conn.executemany(
        "INSERT INTO work_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", orders
    )
    conn.commit()
    return orders


def generate_energy_consumption(conn, zones):
    """Generate energy consumption records per zone per month."""
    rows = SCALE["rows_per_table"]
    zone_ids = [z[0] for z in zones]
    # Determine how many months of data per zone
    months_per_zone = max(6, rows // NUM_ZONES)
    records = []

    base_kwh_per_light = {"LED": 8, "HPS": 20, "Metal Halide": 22, "Fluorescent": 6}

    for z in zones:
        zid = z[0]
        n_lights = z[5]
        base_kwh = n_lights * 15  # average per month
        month_counter = 0
        for year in [2023, 2024, 2025]:
            for month in range(1, 13):
                if month_counter >= months_per_zone:
                    break
                seasonal = 1.0 + 0.15 * np.sin((month - 6) * np.pi / 6)
                kwh = round(base_kwh * seasonal * random.uniform(0.85, 1.15), 2)
                cost_per = round(random.uniform(0.08, 0.15), 4)
                total_cost = round(kwh * cost_per, 2)
                peak = round(kwh / (30 * 10) * random.uniform(0.9, 1.3), 2)
                records.append((
                    zid, year, month, kwh, cost_per, total_cost, peak
                ))
                month_counter += 1

    conn.executemany(
        "INSERT INTO energy_consumption (zone_id, year, month, kwh_consumed, cost_per_kwh, total_cost, peak_demand_kw) VALUES (?, ?, ?, ?, ?, ?, ?)",
        records
    )
    conn.commit()
    return records


def generate_complaints(conn, lights, zones):
    """Generate citizen complaint logs."""
    rows = SCALE["rows_per_table"]
    zone_ids = [z[0] for z in zones]
    light_by_zone = {}
    for l in lights:
        light_by_zone.setdefault(l[1], []).append(l[0])

    complaints = []
    for cid in range(1, rows + 1):
        zid = random.choice(zone_ids)
        lid = random.choice(light_by_zone[zid]) if random.random() > 0.3 else None
        ctype = random.choice(COMPLAINT_TYPES)
        year = random.randint(2023, 2025)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        date_filed = f"{year}-{month:02d}-{day:02d}"
        resolved = random.choices([0, 1], weights=[35, 65])[0]
        date_resolved = None
        if resolved:
            from datetime import datetime, timedelta
            df = datetime(year, month, day)
            dr = df + timedelta(days=random.randint(1, 45))
            date_resolved = dr.strftime("%Y-%m-%d")
        priority = random.choices(SEVERITY_LEVELS, weights=[20, 35, 30, 15])[0]
        desc = fake.sentence(nb_words=random.randint(8, 15))

        complaints.append((
            cid, zid, lid, ctype, date_filed, date_resolved,
            priority, desc, resolved
        ))

    conn.executemany(
        "INSERT INTO citizen_complaints VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        complaints
    )
    conn.commit()
    return complaints


def generate_accidents(conn, lights, zones):
    """Generate traffic accident reports."""
    rows = SCALE["rows_per_table"]
    zone_ids = [z[0] for z in zones]
    light_by_zone = {}
    for l in lights:
        light_by_zone.setdefault(l[1], []).append(l[0])

    accidents = []
    times_of_day = ["Night", "Dusk", "Dawn", "Day"]
    road_types = ["Highway", "Arterial", "Residential", "Collector"]

    for aid in range(1, rows + 1):
        zid = random.choice(zone_ids)
        year = random.randint(2022, 2025)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        date = f"{year}-{month:02d}-{day:02d}"
        tod = random.choices(times_of_day, weights=[40, 25, 15, 20])[0]
        sev = random.choices(ACCIDENT_SEVERITY, weights=[40, 30, 20, 10])[0]
        lighting_related = 1 if (tod in ["Night", "Dusk", "Dawn"] and random.random() > 0.4) else 0
        injuries = 0
        fatalities = 0
        if sev == "Minor":
            injuries = random.randint(0, 1)
        elif sev == "Moderate":
            injuries = random.randint(1, 3)
        elif sev == "Severe":
            injuries = random.randint(2, 5)
            fatalities = random.choices([0, 1], weights=[70, 30])[0]
        elif sev == "Fatal":
            injuries = random.randint(1, 4)
            fatalities = random.randint(1, 3)
        nearest_lid = random.choice(light_by_zone[zid]) if random.random() > 0.2 else None
        road = random.choice(road_types)

        accidents.append((
            aid, zid, date, tod, sev, lighting_related,
            injuries, fatalities, nearest_lid, road
        ))

    conn.executemany(
        "INSERT INTO traffic_accidents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        accidents
    )
    conn.commit()
    return accidents


# ── Workspace generation ─────────────────────────────────────────────────────

def generate_workspace(workspace, conn, zones, lights, work_orders, complaints, accidents):
    """Generate workspace files combining DB data and supplementary info."""
    os.makedirs(workspace, exist_ok=True)

    # ── Fixed config files (not scaled) ──────────────────────────────────
    _write_priority_weights(workspace)
    _write_budget_rules(workspace)
    _write_maintenance_policy(workspace)
    _write_risk_scoring_config(workspace)

    # ── Scalable data files ──────────────────────────────────────────────
    num_files = SCALE["num_workspace_files"]
    _write_zone_energy_reports(workspace, conn, zones, num_files)


def _write_priority_weights(workspace):
    """Write priority scoring weights config."""
    weights = {
        "failure_rate_weight": 0.30,
        "complaint_density_weight": 0.20,
        "accident_risk_weight": 0.25,
        "energy_efficiency_weight": 0.10,
        "infrastructure_age_weight": 0.15,
        "severity_multipliers": {
            "Low": 1.0,
            "Medium": 2.0,
            "High": 3.5,
            "Critical": 5.0
        },
        "accident_severity_scores": {
            "Minor": 1,
            "Moderate": 3,
            "Severe": 7,
            "Fatal": 15
        },
        "lighting_related_bonus": 2.0
    }
    with open(os.path.join(workspace, "priority_weights.yaml"), "w") as f:
        yaml.dump(weights, f, default_flow_style=False, sort_keys=False)


def _write_budget_rules(workspace):
    """Write budget allocation rules."""
    rules = {
        "total_annual_budget": 1500000.00,
        "minimum_zone_allocation_pct": 5.0,
        "maximum_zone_allocation_pct": 25.0,
        "emergency_reserve_pct": 10.0,
        "allocation_method": "risk_proportional",
        "tier_definitions": {
            "critical": {"min_risk_score": 75, "budget_priority": "immediate", "response_days": 7},
            "high": {"min_risk_score": 50, "budget_priority": "urgent", "response_days": 14},
            "medium": {"min_risk_score": 25, "budget_priority": "scheduled", "response_days": 30},
            "low": {"min_risk_score": 0, "budget_priority": "routine", "response_days": 60}
        },
        "cost_escalation_factor": 1.05,
        "preventive_maintenance_pct": 15.0
    }
    with open(os.path.join(workspace, "budget_rules.json"), "w") as f:
        json.dump(rules, f, indent=2)


def _write_maintenance_policy(workspace):
    """Write maintenance policy document."""
    policy = """MUNICIPAL STREETLIGHT MAINTENANCE POLICY - FY2025

Section 1: Maintenance Prioritization
Zones shall be ranked by composite risk score. The composite risk score for each zone
is computed as a weighted sum of five normalized component scores: failure rate,
complaint density, accident risk, energy efficiency deviation, and infrastructure age.
Each component score ranges from 0 to 100 before weighting.

Section 2: Failure Rate Calculation
The failure rate for a zone is defined as the number of work orders with severity
High or Critical divided by the total number of streetlights in that zone, multiplied
by 100. Only work orders from the most recent two calendar years (2024 and 2025) are
counted. The resulting value is capped at 100.

Section 3: Complaint Density
Complaint density is the total number of unresolved complaints in a zone divided by
the zone area in square kilometers. The raw density is then normalized to 0-100 by
dividing each zone's density by the maximum density across all zones and multiplying
by 100.

Section 4: Accident Risk Score
For each zone, sum the accident severity scores (from the scoring configuration) for
all lighting-related accidents in 2024 and 2025. Add the lighting-related bonus
multiplier for each lighting-related accident. Normalize to 0-100 by dividing by the
maximum zone total and multiplying by 100.

Section 5: Energy Efficiency Deviation
Compute each zone's average monthly energy cost per streetlight using the most recent
12 months of data. The zone with the highest per-light cost gets a score of 100; others
are scored proportionally (zone_cost / max_cost * 100).

Section 6: Infrastructure Age Score
The infrastructure age score is the average age in years of all streetlights in a zone
(calculated from install_date to 2025-06-01), normalized to 0-100 by dividing by the
maximum average age across all zones and multiplying by 100.

Section 7: Budget Allocation Formula
After computing composite risk scores, allocate the distributable budget (total budget
minus emergency reserve) proportionally to each zone's composite risk score. Each zone
allocation must respect the minimum and maximum percentage bounds defined in the budget
rules. If a zone's proportional share falls below the minimum, it is set to the minimum;
if above the maximum, it is capped at the maximum. After capping, any surplus from capped
zones is redistributed proportionally among uncapped zones, iterating until all
allocations are within bounds.

Section 8: Repair Schedule Priority
Pending and In Progress work orders shall be scheduled in descending order of zone
composite risk score. Within the same zone, order by severity (Critical > High >
Medium > Low), then by date_reported ascending (oldest first).
"""
    with open(os.path.join(workspace, "maintenance_policy.md"), "w") as f:
        f.write(policy)


def _write_risk_scoring_config(workspace):
    """Write risk scoring normalization config."""
    config = {
        "normalization": "max_scaling",
        "reference_year_start": 2024,
        "reference_year_end": 2025,
        "age_reference_date": "2025-06-01",
        "energy_lookback_months": 12,
        "energy_lookback_end": "2025-12",
        "composite_score_precision": 2,
        "budget_allocation_precision": 2
    }
    with open(os.path.join(workspace, "scoring_config.json"), "w") as f:
        json.dump(config, f, indent=2)


def _write_zone_energy_reports(workspace, conn, zones, num_files):
    """Write scalable zone-specific data files combining energy and supplementary data."""
    c = conn.cursor()

    # Distribute files across zones in round-robin
    zone_ids = [z[0] for z in zones]
    zone_names = {z[0]: z[1] for z in zones}

    files_written = 0

    # Type 1: Zone energy summary CSVs (one per zone, cycles if more files needed)
    energy_csv_count = max(NUM_ZONES, num_files // 4)
    for i in range(energy_csv_count):
        if files_written >= num_files:
            break
        zid = zone_ids[i % NUM_ZONES]
        zname = zone_names[zid]
        c.execute("""
            SELECT year, month, kwh_consumed, cost_per_kwh, total_cost, peak_demand_kw
            FROM energy_consumption WHERE zone_id = ? ORDER BY year, month
        """, (zid,))
        rows = c.fetchall()
        if not rows:
            continue
        df = pd.DataFrame(rows, columns=["year", "month", "kwh_consumed",
                                          "cost_per_kwh", "total_cost", "peak_demand_kw"])
        suffix = f"_{i // NUM_ZONES + 1}" if i >= NUM_ZONES else ""
        df.to_csv(os.path.join(workspace, f"energy_report_{zname}{suffix}.csv"), index=False)
        files_written += 1

    # Type 2: Complaint detail JSON files per zone
    complaint_json_count = max(1, (num_files - files_written) // 3)
    for i in range(complaint_json_count):
        if files_written >= num_files:
            break
        zid = zone_ids[i % NUM_ZONES]
        zname = zone_names[zid]
        c.execute("""
            SELECT complaint_id, light_id, complaint_type, date_filed, priority, description, resolved
            FROM citizen_complaints WHERE zone_id = ? ORDER BY date_filed
        """, (zid,))
        rows = c.fetchall()
        data = [{"complaint_id": r[0], "light_id": r[1], "complaint_type": r[2],
                 "date_filed": r[3], "priority": r[4], "description": r[5],
                 "resolved": bool(r[6])} for r in rows]
        suffix = f"_{i // NUM_ZONES + 1}" if i >= NUM_ZONES else ""
        with open(os.path.join(workspace, f"complaints_{zname}{suffix}.json"), "w") as f:
            json.dump(data, f, indent=2)
        files_written += 1

    # Type 3: Accident summary TXT files
    while files_written < num_files:
        zid = zone_ids[files_written % NUM_ZONES]
        zname = zone_names[zid]
        c.execute("""
            SELECT accident_id, date, time_of_day, severity, lighting_related,
                   injuries, fatalities, nearest_light_id, road_type
            FROM traffic_accidents WHERE zone_id = ? ORDER BY date
        """, (zid,))
        rows = c.fetchall()
        lines = [f"TRAFFIC ACCIDENT REPORT - {zname}"]
        lines.append("=" * 50)
        for r in rows:
            lines.append(
                f"ID:{r[0]} | Date:{r[1]} | Time:{r[2]} | Severity:{r[3]} | "
                f"LightingRelated:{bool(r[4])} | Injuries:{r[5]} | "
                f"Fatalities:{r[6]} | NearestLight:{r[7]} | Road:{r[8]}"
            )
        suffix = f"_{files_written // NUM_ZONES + 1}" if files_written >= NUM_ZONES else ""
        with open(os.path.join(workspace, f"accidents_{zname}{suffix}.txt"), "w") as f:
            f.write("\n".join(lines))
        files_written += 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    zones = generate_zones(conn)
    lights = generate_streetlights(conn, zones)
    work_orders = generate_work_orders(conn, lights, zones)
    energy = generate_energy_consumption(conn, zones)
    complaints = generate_complaints(conn, lights, zones)
    accidents = generate_accidents(conn, lights, zones)

    generate_workspace(args.workspace, conn, zones, lights, work_orders, complaints, accidents)

    conn.close()
    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")


if __name__ == "__main__":
    main()
