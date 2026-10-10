"""
Data generation script for fraudulent water damage claim detection task.
Generates database tables and workspace files for cross-referencing
policy details, weather data, contractor estimates, and claims history.
"""

import argparse
import json
import os
import random
import sqlite3
import csv
import yaml

import numpy as np
import pandas as pd
from faker import Faker

# ─── Global seed ───
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ─── Scale parameters (only this block changes across versions) ───
SCALE = {
    "rows_per_table": 200,      # v2 = 4 × 50
    "num_workspace_files": 24,  # v2 = 8 + 2×8
}

# ─── Zip codes pool ───
ZIP_CODES = [
    "30301", "30302", "30303", "30304", "30305",
    "30306", "30307", "30308", "30309", "30310",
    "30311", "30312", "30313", "30314", "30315",
    "30316", "30317", "30318", "30319", "30320",
    "77001", "77002", "77003", "77004", "77005",
    "77006", "77007", "77008", "77009", "77010",
    "33101", "33102", "33103", "33104", "33105",
    "33106", "33107", "33108", "33109", "33110",
    "70112", "70113", "70114", "70115", "70116",
    "70117", "70118", "70119", "70120", "70121",
]

DAMAGE_TYPES = [
    "burst_pipe", "roof_leak", "flooding", "appliance_overflow",
    "sewer_backup", "storm_damage", "foundation_seepage", "sprinkler_malfunction"
]

COVERAGE_TYPES = ["basic", "standard", "premium", "comprehensive"]

CLAIM_STATUSES = ["pending", "approved", "denied", "under_review", "closed"]

STORM_EVENTS = [None, None, None, "tropical_storm", "hurricane", "thunderstorm", "tornado_warning", "flash_flood"]


def create_tables(conn):
    """Create all database tables."""
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS policies (
            policy_id TEXT PRIMARY KEY,
            holder_name TEXT NOT NULL,
            address TEXT NOT NULL,
            zip_code TEXT NOT NULL,
            coverage_type TEXT NOT NULL,
            coverage_limit REAL NOT NULL,
            deductible REAL NOT NULL,
            premium_annual REAL NOT NULL,
            effective_date TEXT NOT NULL,
            expiration_date TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            claim_id TEXT PRIMARY KEY,
            policy_id TEXT NOT NULL,
            incident_date TEXT NOT NULL,
            filed_date TEXT NOT NULL,
            incident_zip TEXT NOT NULL,
            damage_type TEXT NOT NULL,
            damage_description TEXT NOT NULL,
            claimed_amount REAL NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (policy_id) REFERENCES policies(policy_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS weather_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zip_code TEXT NOT NULL,
            date TEXT NOT NULL,
            precipitation_mm REAL NOT NULL,
            wind_speed_kmh REAL NOT NULL,
            temperature_c REAL NOT NULL,
            flood_alert INTEGER NOT NULL,
            storm_event TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS claim_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_id TEXT NOT NULL,
            prior_claim_date TEXT NOT NULL,
            claim_type TEXT NOT NULL,
            claim_amount REAL NOT NULL,
            payout REAL NOT NULL,
            outcome TEXT NOT NULL,
            FOREIGN KEY (policy_id) REFERENCES policies(policy_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS contractors (
            contractor_id TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            license_number TEXT,
            license_status TEXT NOT NULL,
            specialty TEXT NOT NULL,
            rating REAL NOT NULL,
            years_in_business INTEGER NOT NULL
        )
    """)

    conn.commit()


def generate_policies(conn, n_rows):
    """Generate policy records."""
    policies = []
    for i in range(n_rows):
        policy_id = f"POL-{10000 + i}"
        holder_name = fake.name()
        address = fake.street_address()
        zip_code = random.choice(ZIP_CODES)
        coverage_type = random.choice(COVERAGE_TYPES)

        coverage_limits = {"basic": 50000, "standard": 100000, "premium": 200000, "comprehensive": 500000}
        coverage_limit = coverage_limits[coverage_type] + random.randint(-5000, 20000)
        deductible = random.choice([500, 1000, 1500, 2000, 2500])
        premium_annual = round(coverage_limit * random.uniform(0.005, 0.02), 2)

        # Some policies are expired to create coverage gaps
        if random.random() < 0.15:
            eff = fake.date_between(start_date="-5y", end_date="-2y")
            exp = fake.date_between_dates(date_start=eff, date_end=pd.Timestamp(eff) + pd.DateOffset(years=1))
        else:
            eff = fake.date_between(start_date="-3y", end_date="-6m")
            exp = fake.date_between_dates(
                date_start=pd.Timestamp(eff) + pd.DateOffset(years=1),
                date_end=pd.Timestamp(eff) + pd.DateOffset(years=3)
            )

        policies.append((
            policy_id, holder_name, address, zip_code, coverage_type,
            coverage_limit, deductible, premium_annual,
            str(eff), str(exp)
        ))

    conn.executemany(
        "INSERT INTO policies VALUES (?,?,?,?,?,?,?,?,?,?)", policies
    )
    conn.commit()
    return policies


def generate_contractors(conn, n_rows):
    """Generate contractor records."""
    specialties = ["plumbing", "roofing", "general_restoration", "mold_remediation", "structural_repair"]
    statuses = ["active", "active", "active", "active", "suspended", "revoked", "expired"]
    contractors = []
    for i in range(n_rows):
        cid = f"CTR-{5000 + i}"
        company = fake.company() + " " + random.choice(["Restoration", "Repairs", "Services", "Solutions"])
        lic_status = random.choice(statuses)
        lic_num = f"LIC-{random.randint(100000, 999999)}" if lic_status == "active" else None
        specialty = random.choice(specialties)
        rating = round(random.uniform(1.5, 5.0), 1)
        years = random.randint(1, 30)
        contractors.append((cid, company, lic_num, lic_status, specialty, rating, years))

    conn.executemany(
        "INSERT INTO contractors VALUES (?,?,?,?,?,?,?)", contractors
    )
    conn.commit()
    return contractors


def generate_weather(conn, n_rows, zip_codes_used):
    """Generate weather records covering relevant dates and zips."""
    records = []
    dates_pool = pd.date_range("2023-01-01", "2025-12-31", freq="D")

    # Ensure we cover all used zips with some records
    zips_cycle = list(zip_codes_used) * (n_rows // len(zip_codes_used) + 1)
    random.shuffle(zips_cycle)

    for i in range(n_rows):
        zip_code = zips_cycle[i % len(zips_cycle)]
        date = str(random.choice(dates_pool).date())
        precip = round(random.choice([0, 0, 0, 0.5, 1.2, 3.5, 8.0, 15.0, 25.0, 50.0, 80.0, 120.0]), 1)
        wind = round(random.uniform(0, 100), 1)
        temp = round(random.uniform(-5, 40), 1)
        flood_alert = 1 if precip > 40 or random.random() < 0.05 else 0
        storm = random.choice(STORM_EVENTS) if precip > 10 or wind > 50 else None
        records.append((zip_code, date, precip, wind, temp, flood_alert, storm))

    conn.executemany(
        "INSERT INTO weather_records (zip_code, date, precipitation_mm, wind_speed_kmh, temperature_c, flood_alert, storm_event) VALUES (?,?,?,?,?,?,?)",
        records
    )
    conn.commit()
    return records


def generate_claim_history(conn, n_rows, policy_ids):
    """Generate prior claims history."""
    claim_types = DAMAGE_TYPES + ["fire", "theft", "vandalism", "wind_damage"]
    outcomes = ["paid", "paid", "paid", "denied", "partial"]
    history = []
    for i in range(n_rows):
        pid = random.choice(policy_ids)
        claim_date = str(fake.date_between(start_date="-4y", end_date="-3m"))
        ctype = random.choice(claim_types)
        amount = round(random.uniform(500, 80000), 2)
        outcome = random.choice(outcomes)
        payout = round(amount * random.uniform(0.3, 1.0), 2) if outcome in ("paid", "partial") else 0.0
        history.append((pid, claim_date, ctype, amount, payout, outcome))

    conn.executemany(
        "INSERT INTO claim_history (policy_id, prior_claim_date, claim_type, claim_amount, payout, outcome) VALUES (?,?,?,?,?,?)",
        history
    )
    conn.commit()
    return history


def generate_claims(conn, n_rows, policy_ids, zip_codes_used):
    """Generate claim records. ~30% are pending for investigation."""
    claims = []
    pending_claim_ids = []

    for i in range(n_rows):
        claim_id = f"CLM-{20000 + i}"
        pid = random.choice(policy_ids)
        incident_date = str(fake.date_between(start_date="-18m", end_date="-1m"))

        # Some claims filed much later (late filing flag)
        if random.random() < 0.2:
            delay = random.randint(35, 120)
        else:
            delay = random.randint(1, 25)
        filed_date = str((pd.Timestamp(incident_date) + pd.DateOffset(days=delay)).date())

        incident_zip = random.choice(zip_codes_used)
        damage_type = random.choice(DAMAGE_TYPES)
        damage_desc = fake.sentence(nb_words=12)
        claimed_amount = round(random.uniform(2000, 150000), 2)

        # Assign status: ~30% pending
        if random.random() < 0.30:
            status = "pending"
            pending_claim_ids.append(claim_id)
        else:
            status = random.choice(["approved", "denied", "under_review", "closed"])

        claims.append((
            claim_id, pid, incident_date, filed_date, incident_zip,
            damage_type, damage_desc, claimed_amount, status
        ))

    conn.executemany(
        "INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?)", claims
    )
    conn.commit()
    return claims, pending_claim_ids


def generate_workspace(workspace, conn, n_workspace_files):
    """Generate workspace files."""
    os.makedirs(workspace, exist_ok=True)

    c = conn.cursor()

    # ─── Fixed config files (not counted in SCALE) ───

    # 1. Fraud detection configuration
    fraud_config = {
        "fraud_indicators": {
            "weather_mismatch": {
                "description": "No significant weather event at incident location on incident date",
                "weight": 25,
                "precipitation_threshold_mm": 5.0,
                "wind_threshold_kmh": 40.0
            },
            "estimate_discrepancy": {
                "description": "Claimed amount exceeds highest contractor estimate by more than threshold",
                "weight": 20,
                "excess_threshold_pct": 30.0
            },
            "repeat_claimant": {
                "description": "Policyholder has excessive prior claims within lookback window",
                "weight": 15,
                "min_prior_claims": 3,
                "lookback_months": 24
            },
            "late_filing": {
                "description": "Claim filed too long after the incident date",
                "weight": 15,
                "max_days_to_file": 30
            },
            "unlicensed_contractor": {
                "description": "Contractor providing estimate does not hold an active license",
                "weight": 10
            },
            "coverage_gap": {
                "description": "Policy was not active on the date of the incident",
                "weight": 15
            }
        },
        "priority_levels": {
            "critical": {"min_score": 50},
            "high": {"min_score": 30},
            "medium": {"min_score": 15},
            "low": {"min_score": 1}
        },
        "output_format": {
            "filename": "investigation_list.csv",
            "columns": ["claim_id", "policy_id", "holder_name", "fraud_score", "flags", "priority_level", "priority_rank"],
            "sort_primary": "fraud_score_desc",
            "sort_tiebreaker": "claim_id_asc",
            "flags_separator": "; "
        }
    }
    with open(os.path.join(workspace, "fraud_detection_config.yaml"), "w") as f:
        yaml.dump(fraud_config, f, default_flow_style=False, sort_keys=False)

    # 2. Contractor registry CSV
    c.execute("SELECT * FROM contractors")
    contractors = c.fetchall()
    cols = [desc[0] for desc in c.description]
    with open(os.path.join(workspace, "contractor_registry.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        writer.writerows(contractors)

    # 3. Flood zone map
    flood_zones = []
    zone_types = ["A", "AE", "AH", "AO", "V", "VE", "X", "X500", "B", "C"]
    zone_risk = {"A": "high", "AE": "high", "AH": "high", "AO": "high",
                 "V": "very_high", "VE": "very_high",
                 "X": "low", "X500": "moderate", "B": "moderate", "C": "low"}
    for zc in ZIP_CODES:
        zone = random.choice(zone_types)
        flood_zones.append({"zip_code": zc, "flood_zone": zone, "risk_level": zone_risk[zone]})
    with open(os.path.join(workspace, "flood_zone_map.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["zip_code", "flood_zone", "risk_level"])
        writer.writeheader()
        writer.writerows(flood_zones)

    # ─── Scaling workspace files: contractor estimate reports ───
    # Each estimate file corresponds to a pending claim
    c.execute("SELECT claim_id, policy_id, claimed_amount, damage_type FROM claims WHERE status = 'pending'")
    pending_claims = c.fetchall()

    # Get all contractor IDs
    c.execute("SELECT contractor_id, company_name, license_status FROM contractors")
    all_contractors = c.fetchall()

    os.makedirs(os.path.join(workspace, "estimates"), exist_ok=True)

    # Generate exactly n_workspace_files estimate files
    # If we have more pending claims than workspace files, take first n
    # If fewer, generate for all pending + some approved/under_review
    estimate_claims = list(pending_claims)
    if len(estimate_claims) < n_workspace_files:
        c.execute(
            "SELECT claim_id, policy_id, claimed_amount, damage_type FROM claims WHERE status != 'pending' LIMIT ?",
            (n_workspace_files - len(estimate_claims),)
        )
        estimate_claims.extend(c.fetchall())
    estimate_claims = estimate_claims[:n_workspace_files]

    for claim_id, policy_id, claimed_amount, damage_type in estimate_claims:
        # 1-3 contractor estimates per claim
        n_estimates = random.randint(1, 3)
        selected_contractors = random.sample(all_contractors, min(n_estimates, len(all_contractors)))

        estimates = []
        for ctr_id, ctr_name, lic_status in selected_contractors:
            # Some estimates are significantly below claimed amount (indicating fraud)
            if random.random() < 0.25:
                est_amount = round(claimed_amount * random.uniform(0.3, 0.6), 2)
            else:
                est_amount = round(claimed_amount * random.uniform(0.7, 1.15), 2)

            estimates.append({
                "contractor_id": ctr_id,
                "contractor_name": ctr_name,
                "estimate_amount": est_amount,
                "scope": fake.sentence(nb_words=8),
                "estimate_date": str(fake.date_between(start_date="-12m", end_date="-1m")),
                "materials_cost": round(est_amount * random.uniform(0.3, 0.5), 2),
                "labor_cost": round(est_amount * random.uniform(0.3, 0.5), 2)
            })

        estimate_doc = {
            "claim_id": claim_id,
            "damage_type": damage_type,
            "estimates": estimates
        }

        with open(os.path.join(workspace, "estimates", f"{claim_id}.json"), "w") as f:
            json.dump(estimate_doc, f, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)

    n_rows = SCALE["rows_per_table"]
    n_ws = SCALE["num_workspace_files"]

    create_tables(conn)

    # Generate data
    policies = generate_policies(conn, n_rows)
    policy_ids = [p[0] for p in policies]
    zip_codes_used = list(set(p[3] for p in policies))

    contractors = generate_contractors(conn, max(n_rows // 2, 20))
    generate_weather(conn, n_rows * 3, zip_codes_used)  # More weather records for coverage
    generate_claim_history(conn, n_rows, policy_ids)
    claims, pending_ids = generate_claims(conn, n_rows, policy_ids, zip_codes_used)

    # Ensure we have weather data for incident dates of pending claims
    c = conn.cursor()
    c.execute("SELECT claim_id, incident_zip, incident_date FROM claims WHERE status = 'pending'")
    pending_details = c.fetchall()
    extra_weather = []
    for _, izip, idate in pending_details:
        # Check if weather record exists
        c.execute("SELECT COUNT(*) FROM weather_records WHERE zip_code=? AND date=?", (izip, idate))
        if c.fetchone()[0] == 0:
            precip = round(random.choice([0, 0, 0.5, 2.0, 8.0, 15.0, 30.0, 60.0, 100.0]), 1)
            wind = round(random.uniform(0, 80), 1)
            temp = round(random.uniform(0, 35), 1)
            flood_alert = 1 if precip > 40 else 0
            storm = random.choice(STORM_EVENTS) if precip > 10 or wind > 50 else None
            extra_weather.append((izip, idate, precip, wind, temp, flood_alert, storm))

    if extra_weather:
        conn.executemany(
            "INSERT INTO weather_records (zip_code, date, precipitation_mm, wind_speed_kmh, temperature_c, flood_alert, storm_event) VALUES (?,?,?,?,?,?,?)",
            extra_weather
        )
        conn.commit()

    generate_workspace(args.workspace, conn, n_ws)
    conn.close()
    print(f"Database created at {args.db_path} with {n_rows} rows/table")
    print(f"Workspace created at {args.workspace} with {n_ws} estimate files")


if __name__ == "__main__":
    main()
