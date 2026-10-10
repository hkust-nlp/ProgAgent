import argparse
import os
import sqlite3
import json
import csv
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from faker import Faker

SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 20,
}

NUM_UNITS = 20
REFERENCE_DATE = datetime(2025, 12, 31)
REFINERIES = ["Baytown", "Whiting", "Baton_Rouge", "Port_Arthur"]
CATALYST_TYPES = ["ZSM-5", "USY", "REY", "REUSY", "Beta-Zeolite"]
SUPPLIERS = ["BASF", "Grace_Davison", "Albemarle", "Sinopec_Catalyst", "JGC_Catalysts"]
FEED_TYPES = ["Light_VGO", "Heavy_VGO", "Residual", "Mixed_VGO", "Atmospheric_Residue"]

CATALYST_REFERENCE = {
    "ZSM-5": {"baseline_activity": 95.0, "expected_lifetime_days": 365, "baseline_conversion": 78.0},
    "USY": {"baseline_activity": 92.0, "expected_lifetime_days": 300, "baseline_conversion": 75.0},
    "REY": {"baseline_activity": 88.0, "expected_lifetime_days": 270, "baseline_conversion": 72.0},
    "REUSY": {"baseline_activity": 90.0, "expected_lifetime_days": 330, "baseline_conversion": 74.0},
    "Beta-Zeolite": {"baseline_activity": 93.0, "expected_lifetime_days": 350, "baseline_conversion": 76.0},
}

SCORING_CONFIG = {
    "weights": {
        "activity_decline": 0.30,
        "energy_efficiency": 0.25,
        "feedstock_severity": 0.20,
        "conversion_loss": 0.15,
        "catalyst_age": 0.10,
    },
    "normalization": {
        "activity_decline": {"min": 0.0, "max": 5.0},
        "energy_efficiency": {"min": 1.0, "max": 1.5},
        "feedstock_severity": {"min": 0.0, "max": 100.0},
        "conversion_loss": {"min": 0.0, "max": 15.0},
        "catalyst_age": {"min": 0.0, "max": 2.0},
    },
    "energy_conversion": {
        "steam_to_mmbtu": 1.194,
        "electricity_to_mmbtu": 3.412,
    },
    "tiers": {
        "critical": {"min_score": 75},
        "high": {"min_score": 50},
        "medium": {"min_score": 25},
        "low": {"min_score": 0},
    },
    "feedstock_severity_weights": {
        "sulfur_pct": 25.0,
        "ccr_pct": 20.0,
        "nitrogen_per_1000ppm": 15.0,
        "nickel_per_10ppm": 20.0,
        "vanadium_per_10ppm": 20.0,
    },
}


def generate_units(rng, fake):
    """Generate unit info."""
    units = []
    for i in range(NUM_UNITS):
        unit_id = f"FCC-{i + 1:02d}"
        refinery = REFINERIES[i % len(REFINERIES)]
        unit_type = rng.choice(["FCC", "RFCC"], p=[0.7, 0.3])
        capacity = int(rng.uniform(30000, 80000))
        commissioned = fake.date_between(
            start_date=datetime(2005, 1, 1), end_date=datetime(2020, 12, 31)
        )
        units.append(
            {
                "unit_id": unit_id,
                "unit_name": f"{refinery}_{unit_id}",
                "refinery": refinery,
                "unit_type": unit_type,
                "capacity_bpd": capacity,
                "commissioned_date": commissioned.strftime("%Y-%m-%d"),
            }
        )
    return units


def generate_unit_inspections(units, rng, fake, rows_per_table):
    """Generate unit inspection records. Each unit gets rows_per_table // NUM_UNITS inspections."""
    rows_per_unit = max(rows_per_table // NUM_UNITS, 1)
    extra = rows_per_table - rows_per_unit * NUM_UNITS
    records = []
    inspectors = [fake.name() for _ in range(8)]
    rec_id = 1
    for idx, u in enumerate(units):
        n = rows_per_unit + (1 if idx < extra else 0)
        for j in range(n):
            days_back = int(rng.uniform(30, 900))
            insp_date = REFERENCE_DATE - timedelta(days=days_back)
            records.append(
                {
                    "inspection_id": rec_id,
                    "unit_id": u["unit_id"],
                    "unit_name": u["unit_name"],
                    "refinery": u["refinery"],
                    "unit_type": u["unit_type"],
                    "capacity_bpd": u["capacity_bpd"],
                    "inspection_date": insp_date.strftime("%Y-%m-%d"),
                    "inspector": rng.choice(inspectors),
                    "compliance_status": rng.choice(
                        ["compliant", "minor_issues", "major_issues"],
                        p=[0.6, 0.3, 0.1],
                    ),
                    "notes": fake.sentence(nb_words=10),
                }
            )
            rec_id += 1
    return records


def generate_catalyst_batches(units, rng, rows_per_table):
    """Generate catalyst batch records. One active batch per unit, rest are historical."""
    rows_per_unit = max(rows_per_table // NUM_UNITS, 1)
    extra = rows_per_table - rows_per_unit * NUM_UNITS
    records = []
    batch_id = 1
    active_batches = {}  # unit_id -> active batch info

    for idx, u in enumerate(units):
        n = rows_per_unit + (1 if idx < extra else 0)
        cat_type = CATALYST_TYPES[idx % len(CATALYST_TYPES)]
        supplier = SUPPLIERS[idx % len(SUPPLIERS)]
        ref = CATALYST_REFERENCE[cat_type]

        # Generate batch load dates, most recent is active
        load_dates = sorted(
            [
                REFERENCE_DATE - timedelta(days=int(rng.uniform(90, 800)))
                for _ in range(n)
            ]
        )

        for j, ld in enumerate(load_dates):
            is_active = j == len(load_dates) - 1
            init_act = round(ref["baseline_activity"] * rng.uniform(0.95, 1.05), 2)
            exp_life = ref["expected_lifetime_days"]
            status = "active" if is_active else rng.choice(["spent", "replaced"])
            rec = {
                "batch_id": batch_id,
                "unit_id": u["unit_id"],
                "catalyst_type": cat_type,
                "supplier": supplier,
                "load_date": ld.strftime("%Y-%m-%d"),
                "initial_activity": init_act,
                "expected_lifetime_days": exp_life,
                "status": status,
            }
            records.append(rec)
            if is_active:
                active_batches[u["unit_id"]] = rec.copy()
            batch_id += 1
    return records, active_batches


def generate_activity_measurements(units, active_batches, health_factors, rng, rows_per_table):
    """Generate activity measurement records."""
    rows_per_unit = max(rows_per_table // NUM_UNITS, 1)
    extra = rows_per_table - rows_per_unit * NUM_UNITS
    records = []
    meas_id = 1

    for idx, u in enumerate(units):
        n = rows_per_unit + (1 if idx < extra else 0)
        uid = u["unit_id"]
        ab = active_batches[uid]
        load_date = datetime.strptime(ab["load_date"], "%Y-%m-%d")
        days_active = (REFERENCE_DATE - load_date).days
        health = health_factors[idx]

        # Activity decline: bad health → steep decline
        initial_act = ab["initial_activity"]
        # Monthly decline rate inversely proportional to health
        monthly_decline = (1.0 - health) * 3.5 + 0.3  # 0.3% to 3.8% per month

        for j in range(n):
            frac = (j + 1) / n
            days_elapsed = int(days_active * frac)
            meas_date = load_date + timedelta(days=days_elapsed)
            months_elapsed = days_elapsed / 30.0
            activity = initial_act * (1 - monthly_decline / 100.0) ** months_elapsed
            activity = max(activity, 20.0)  # floor

            coke = round(0.5 + (1 - health) * 2.0 * frac + rng.normal(0, 0.1), 2)
            coke = max(coke, 0.1)
            selectivity = round(85 + health * 10 - (1 - health) * 5 * frac + rng.normal(0, 1), 2)
            selectivity = min(max(selectivity, 60), 99)
            regen_temp = round(1250 + (1 - health) * 100 * frac + rng.normal(0, 10), 1)

            records.append(
                {
                    "measurement_id": meas_id,
                    "batch_id": ab["batch_id"],
                    "unit_id": uid,
                    "measurement_date": meas_date.strftime("%Y-%m-%d"),
                    "activity_index": round(activity, 2),
                    "coke_on_catalyst_pct": coke,
                    "selectivity_pct": selectivity,
                    "regenerator_temp_f": regen_temp,
                }
            )
            meas_id += 1
    return records


def generate_throughput_records(units, active_batches, health_factors, rng, rows_per_table):
    """Generate throughput records."""
    rows_per_unit = max(rows_per_table // NUM_UNITS, 1)
    extra = rows_per_table - rows_per_unit * NUM_UNITS
    records = []
    rec_id = 1

    for idx, u in enumerate(units):
        n = rows_per_unit + (1 if idx < extra else 0)
        uid = u["unit_id"]
        ab = active_batches[uid]
        cat_type = ab["catalyst_type"]
        ref = CATALYST_REFERENCE[cat_type]
        load_date = datetime.strptime(ab["load_date"], "%Y-%m-%d")
        days_active = (REFERENCE_DATE - load_date).days
        health = health_factors[idx]

        base_conversion = ref["baseline_conversion"]
        base_feed_rate = u["capacity_bpd"] * rng.uniform(0.75, 0.95)

        for j in range(n):
            frac = (j + 1) / n
            days_elapsed = int(days_active * frac)
            rec_date = load_date + timedelta(days=days_elapsed)

            # Conversion degrades for unhealthy units
            conv_loss = (1 - health) * 12.0 * frac  # up to 12% loss
            conversion = base_conversion - conv_loss + rng.normal(0, 0.5)
            conversion = min(max(conversion, 50), 95)

            feed_rate = base_feed_rate * (1 - (1 - health) * 0.1 * frac) + rng.normal(0, 500)
            feed_rate = max(feed_rate, 10000)

            gasoline = round(conversion * 0.6 + rng.normal(0, 1), 2)
            lcgo = round(conversion * 0.15 + rng.normal(0, 0.5), 2)
            hcgo = round(conversion * 0.1 + rng.normal(0, 0.3), 2)
            slurry = round(100 - conversion - rng.uniform(2, 5), 2)

            records.append(
                {
                    "record_id": rec_id,
                    "unit_id": uid,
                    "record_date": rec_date.strftime("%Y-%m-%d"),
                    "feed_rate_bpd": round(feed_rate, 1),
                    "conversion_pct": round(conversion, 2),
                    "gasoline_yield_pct": gasoline,
                    "lcgo_yield_pct": lcgo,
                    "hcgo_yield_pct": hcgo,
                    "slurry_yield_pct": max(slurry, 1),
                }
            )
            rec_id += 1
    return records


def generate_energy_records(units, active_batches, health_factors, rng, rows_per_table):
    """Generate energy consumption records."""
    rows_per_unit = max(rows_per_table // NUM_UNITS, 1)
    extra = rows_per_table - rows_per_unit * NUM_UNITS
    records = []
    rec_id = 1

    for idx, u in enumerate(units):
        n = rows_per_unit + (1 if idx < extra else 0)
        uid = u["unit_id"]
        ab = active_batches[uid]
        load_date = datetime.strptime(ab["load_date"], "%Y-%m-%d")
        days_active = (REFERENCE_DATE - load_date).days
        health = health_factors[idx]

        base_fuel = u["capacity_bpd"] * 0.00015  # MMBTU per barrel baseline
        base_steam = u["capacity_bpd"] * 0.0003
        base_elec = u["capacity_bpd"] * 0.00008

        for j in range(n):
            frac = (j + 1) / n
            days_elapsed = int(days_active * frac)
            rec_date = load_date + timedelta(days=days_elapsed)

            # Energy increases for unhealthy units
            degradation = 1 + (1 - health) * 0.4 * frac
            fuel_gas = round(base_fuel * degradation * u["capacity_bpd"] + rng.normal(0, 50), 2)
            steam = round(base_steam * degradation * u["capacity_bpd"] / 1000 + rng.normal(0, 2), 2)
            electricity = round(base_elec * degradation * u["capacity_bpd"] / 1000 + rng.normal(0, 0.5), 2)
            air_blower = round(60 + (1 - health) * 30 * frac + rng.normal(0, 3), 1)
            air_blower = min(max(air_blower, 30), 100)
            regen_heat = round(fuel_gas * 0.35 + rng.normal(0, 20), 2)

            records.append(
                {
                    "record_id": rec_id,
                    "unit_id": uid,
                    "record_date": rec_date.strftime("%Y-%m-%d"),
                    "fuel_gas_mmbtu": max(fuel_gas, 100),
                    "steam_klb": max(steam, 1),
                    "electricity_mwh": max(electricity, 0.5),
                    "air_blower_load_pct": air_blower,
                    "regenerator_heat_mmbtu": max(regen_heat, 50),
                }
            )
            rec_id += 1
    return records


def generate_feedstock_files(units, active_batches, health_factors, rng, workspace, rows_per_table, num_files):
    """Generate feedstock quality report CSV files in workspace."""
    total_rows = rows_per_table
    rows_per_unit = max(total_rows // NUM_UNITS, 1)

    # Build all feedstock data first
    all_data = []
    for idx, u in enumerate(units):
        uid = u["unit_id"]
        ab = active_batches[uid]
        load_date = datetime.strptime(ab["load_date"], "%Y-%m-%d")
        days_active = (REFERENCE_DATE - load_date).days
        health = health_factors[idx]
        n = rows_per_unit + (1 if idx < (total_rows - rows_per_unit * NUM_UNITS) else 0)

        for j in range(n):
            frac = (j + 1) / n
            days_elapsed = int(days_active * frac)
            sample_date = load_date + timedelta(days=days_elapsed)

            # Heavier feedstocks for less healthy units
            api_gravity = round(22 + health * 10 + rng.normal(0, 1.5), 1)
            sulfur = round(0.5 + (1 - health) * 2.5 + rng.normal(0, 0.15), 3)
            sulfur = max(sulfur, 0.1)
            nitrogen = round(800 + (1 - health) * 2000 + rng.normal(0, 100), 0)
            nitrogen = max(nitrogen, 200)
            ccr = round(3 + (1 - health) * 8 + rng.normal(0, 0.5), 2)
            ccr = max(ccr, 0.5)
            nickel = round(2 + (1 - health) * 12 + rng.normal(0, 0.5), 1)
            nickel = max(nickel, 0.1)
            vanadium = round(3 + (1 - health) * 15 + rng.normal(0, 0.8), 1)
            vanadium = max(vanadium, 0.2)

            probs = [
                0.1 + health * 0.3,
                0.25,
                0.1 + (1 - health) * 0.2,
                0.25,
                0.1 + (1 - health) * 0.1,
            ]
            probs = [p / sum(probs) for p in probs]
            feed_type = rng.choice(FEED_TYPES, p=probs)

            all_data.append({
                "date": sample_date.strftime("%Y-%m-%d"),
                "unit_id": uid,
                "api_gravity": api_gravity,
                "sulfur_pct": sulfur,
                "nitrogen_ppm": int(nitrogen),
                "ccr_pct": ccr,
                "nickel_ppm": nickel,
                "vanadium_ppm": vanadium,
                "feed_type": feed_type,
            })

    # Distribute rows across files
    # Sort by unit_id then date to keep related data together
    all_data.sort(key=lambda x: (x["unit_id"], x["date"]))

    # Split into num_files chunks
    chunk_size = max(len(all_data) // num_files, 1)
    file_idx = 1
    for start in range(0, len(all_data), chunk_size):
        if file_idx > num_files:
            # Append remaining to last file
            chunk = all_data[start:]
            fname = os.path.join(workspace, f"feedstock_report_{num_files:03d}.csv")
            with open(fname, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(all_data[0].keys()))
                writer.writerows(chunk)
            break
        chunk = all_data[start : start + chunk_size]
        fname = os.path.join(workspace, f"feedstock_report_{file_idx:03d}.csv")
        with open(fname, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_data[0].keys()))
            writer.writeheader()
            writer.writerows(chunk)
        file_idx += 1


def write_fixed_workspace_files(workspace):
    """Write fixed configuration/reference files that do not scale."""
    # scoring_config.yaml
    import yaml

    with open(os.path.join(workspace, "scoring_config.yaml"), "w") as f:
        yaml.dump(SCORING_CONFIG, f, default_flow_style=False, sort_keys=False)

    # catalyst_reference.json
    with open(os.path.join(workspace, "catalyst_reference.json"), "w") as f:
        json.dump(CATALYST_REFERENCE, f, indent=2)

    # maintenance_guidelines.txt
    guidelines = """Catalyst Maintenance Decision Guidelines
==========================================

Action Assignment Rules (based on priority tier and catalyst age factor):

1. If the priority tier is Critical and the catalyst age factor exceeds 1.5, the
   recommended action is "immediate_replacement" with an estimated downtime of 14 days.

2. If the priority tier is Critical and the catalyst age factor is 1.5 or below, the
   recommended action is "emergency_regeneration" with an estimated downtime of 10 days.

3. If the priority tier is High, the recommended action is "scheduled_regeneration"
   with an estimated downtime of 7 days.

4. If the priority tier is Medium, the recommended action is "enhanced_monitoring"
   with an estimated downtime of 3 days.

5. If the priority tier is Low, the recommended action is "normal_operation"
   with an estimated downtime of 0 days.

Tier Determination:
- Critical: priority score >= 75
- High: priority score >= 50
- Medium: priority score >= 25
- Low: priority score < 25

Catalyst Age Factor:
- Calculated as the number of days since catalyst load divided by the expected
  lifetime in days (from the catalyst reference specifications).

Priority Score Calculation:
- Each factor is normalized to a 0-100 scale using the min/max ranges in the
  scoring configuration, then multiplied by its weight. The priority score is
  the sum of all weighted normalized factors.
- Normalization formula: clip((value - min) / (max - min), 0, 1) * 100

Activity Decline Rate Calculation:
- Monthly percentage decline computed as:
  (first_activity - last_activity) / first_activity * 100 / (days_between / 30)
  where first_activity and last_activity are the earliest and latest activity
  index measurements for the unit's active catalyst batch, and days_between is
  the number of days between those measurements.

Energy Efficiency Ratio Calculation:
- Compute energy per barrel for each record:
  energy_per_bbl = (fuel_gas_mmbtu + steam_klb * steam_to_mmbtu + electricity_mwh * electricity_to_mmbtu) / feed_rate_bpd
  where feed_rate_bpd comes from the throughput record for the same unit on
  the closest date. Use the conversion factors from scoring_config.yaml.
- Split records into first half and second half chronologically.
- Ratio = mean(energy_per_bbl in second half) / mean(energy_per_bbl in first half).

Conversion Loss Calculation:
- baseline_conversion from catalyst_reference.json for the unit's catalyst type.
- current_conversion = mean of the last two throughput records' conversion_pct.
- conversion_loss = baseline_conversion - current_conversion.

Feedstock Severity Score Calculation:
- Compute from the feedstock quality reports using the formula:
  severity = sulfur_pct * sulfur_weight + ccr_pct * ccr_weight +
             (nitrogen_ppm / 1000) * nitrogen_weight +
             (nickel_ppm / 10) * nickel_weight +
             (vanadium_ppm / 10) * vanadium_weight
  where the weights come from scoring_config.yaml feedstock_severity_weights.
- Use the mean severity across all feedstock records for the unit.
"""
    with open(os.path.join(workspace, "maintenance_guidelines.txt"), "w") as f:
        f.write(guidelines)


def create_tables(conn):
    """Create all database tables."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS unit_inspections (
            inspection_id INTEGER PRIMARY KEY,
            unit_id TEXT NOT NULL,
            unit_name TEXT NOT NULL,
            refinery TEXT NOT NULL,
            unit_type TEXT NOT NULL,
            capacity_bpd INTEGER NOT NULL,
            inspection_date TEXT NOT NULL,
            inspector TEXT NOT NULL,
            compliance_status TEXT NOT NULL,
            notes TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS catalyst_batches (
            batch_id INTEGER PRIMARY KEY,
            unit_id TEXT NOT NULL,
            catalyst_type TEXT NOT NULL,
            supplier TEXT NOT NULL,
            load_date TEXT NOT NULL,
            initial_activity REAL NOT NULL,
            expected_lifetime_days INTEGER NOT NULL,
            status TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_measurements (
            measurement_id INTEGER PRIMARY KEY,
            batch_id INTEGER NOT NULL,
            unit_id TEXT NOT NULL,
            measurement_date TEXT NOT NULL,
            activity_index REAL NOT NULL,
            coke_on_catalyst_pct REAL NOT NULL,
            selectivity_pct REAL NOT NULL,
            regenerator_temp_f REAL NOT NULL,
            FOREIGN KEY (batch_id) REFERENCES catalyst_batches(batch_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS throughput_records (
            record_id INTEGER PRIMARY KEY,
            unit_id TEXT NOT NULL,
            record_date TEXT NOT NULL,
            feed_rate_bpd REAL NOT NULL,
            conversion_pct REAL NOT NULL,
            gasoline_yield_pct REAL NOT NULL,
            lcgo_yield_pct REAL NOT NULL,
            hcgo_yield_pct REAL NOT NULL,
            slurry_yield_pct REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS energy_consumption (
            record_id INTEGER PRIMARY KEY,
            unit_id TEXT NOT NULL,
            record_date TEXT NOT NULL,
            fuel_gas_mmbtu REAL NOT NULL,
            steam_klb REAL NOT NULL,
            electricity_mwh REAL NOT NULL,
            air_blower_load_pct REAL NOT NULL,
            regenerator_heat_mmbtu REAL NOT NULL
        )
    """)


def insert_records(conn, table, records):
    """Insert records into a table."""
    if not records:
        return
    cols = list(records[0].keys())
    placeholders = ", ".join(["?"] * len(cols))
    col_names = ", ".join(cols)
    conn.executemany(
        f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
        [tuple(r[c] for c in cols) for r in records],
    )


def main(db_path, workspace):
    rng = np.random.RandomState(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    rows_per_table = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    # Generate health factors for each unit (controls performance characteristics)
    health_factors = rng.uniform(0.15, 0.95, NUM_UNITS)

    # Generate unit metadata
    units = generate_units(rng, fake)

    # Generate DB records
    inspections = generate_unit_inspections(units, rng, fake, rows_per_table)
    batches, active_batches = generate_catalyst_batches(units, rng, rows_per_table)
    activity = generate_activity_measurements(
        units, active_batches, health_factors, rng, rows_per_table
    )
    throughput = generate_throughput_records(
        units, active_batches, health_factors, rng, rows_per_table
    )
    energy = generate_energy_records(
        units, active_batches, health_factors, rng, rows_per_table
    )

    # Create database
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    insert_records(conn, "unit_inspections", inspections)
    insert_records(conn, "catalyst_batches", batches)
    insert_records(conn, "activity_measurements", activity)
    insert_records(conn, "throughput_records", throughput)
    insert_records(conn, "energy_consumption", energy)
    conn.commit()
    conn.close()

    # Generate workspace files
    generate_feedstock_files(
        units, active_batches, health_factors, rng, workspace, rows_per_table, num_files
    )
    write_fixed_workspace_files(workspace)

    print(f"Database created at {db_path}")
    print(f"Workspace files created in {workspace}/")
    print(f"  - {num_files} feedstock report CSV files")
    print(f"  - 3 fixed configuration files")
    print(f"  - Total DB rows per table: {rows_per_table}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
