#!/usr/bin/env python3
"""Data generation for network adequacy compliance task."""

import numpy as np
import pandas as pd
from faker import Faker
import sqlite3
import os
import json
import argparse
import math
from datetime import date, timedelta


def _split_df(df, n):
    L = len(df)
    base, rem = divmod(L, n)
    out, start = [], 0
    for i in range(n):
        size = base + (1 if i < rem else 0)
        out.append(df.iloc[start:start + size])
        start += size
    return out


SCALE = {
    "rows_per_table": 100,
    "num_workspace_files": 10,
}

# ── Fixed seeds ──────────────────────────────────────────────────────────────
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ── Reference constants (do not scale) ───────────────────────────────────────
SERVICE_AREAS = [
    {"area_id": 1, "area_name": "Metro Central",  "area_type": "urban",    "state": "CA", "center_lat": 34.05,  "center_lon": -118.25},
    {"area_id": 2, "area_name": "North Valley",   "area_type": "suburban", "state": "CA", "center_lat": 38.58,  "center_lon": -121.49},
    {"area_id": 3, "area_name": "South Coast",    "area_type": "urban",    "state": "CA", "center_lat": 32.72,  "center_lon": -117.16},
    {"area_id": 4, "area_name": "East Highland",  "area_type": "rural",    "state": "CA", "center_lat": 34.10,  "center_lon": -116.43},
    {"area_id": 5, "area_name": "West Plains",    "area_type": "suburban", "state": "CA", "center_lat": 35.37,  "center_lon": -119.02},
]

SPECIALTIES = [
    {"specialty_id": 1, "specialty_name": "Primary Care",      "category": "primary"},
    {"specialty_id": 2, "specialty_name": "Cardiology",        "category": "specialist"},
    {"specialty_id": 3, "specialty_name": "Orthopedics",       "category": "specialist"},
    {"specialty_id": 4, "specialty_name": "Dermatology",       "category": "specialist"},
    {"specialty_id": 5, "specialty_name": "Behavioral Health", "category": "behavioral"},
    {"specialty_id": 6, "specialty_name": "OB/GYN",            "category": "specialist"},
    {"specialty_id": 7, "specialty_name": "Pediatrics",        "category": "primary"},
    {"specialty_id": 8, "specialty_name": "Endocrinology",     "category": "specialist"},
]

PLAN_TYPES = ["HMO", "PPO", "EPO"]

# Weights for distributing provider locations across service areas
AREA_WEIGHTS = [0.30, 0.20, 0.25, 0.10, 0.15]

# Weights for distributing locations across specialties
SPECIALTY_WEIGHTS = [0.20, 0.12, 0.12, 0.10, 0.12, 0.12, 0.15, 0.07]

# Coordinate spread (std in degrees)
MEMBER_COORD_STD = 0.08
PROVIDER_COORD_STD = 0.12

# Distance thresholds: specialty_name -> area_type -> miles
DISTANCE_THRESHOLDS = {
    "Primary Care":      {"urban": 15, "suburban": 25, "rural": 40},
    "Cardiology":        {"urban": 20, "suburban": 35, "rural": 60},
    "Orthopedics":       {"urban": 20, "suburban": 35, "rural": 60},
    "Dermatology":       {"urban": 25, "suburban": 40, "rural": 65},
    "Behavioral Health": {"urban": 20, "suburban": 30, "rural": 50},
    "OB/GYN":            {"urban": 15, "suburban": 30, "rural": 55},
    "Pediatrics":        {"urban": 15, "suburban": 25, "rural": 40},
    "Endocrinology":     {"urban": 25, "suburban": 40, "rural": 65},
}

REQUIRED_COVERAGE_PCT = {
    "Primary Care": 90.0,
    "Cardiology": 80.0,
    "Orthopedics": 80.0,
    "Dermatology": 75.0,
    "Behavioral Health": 85.0,
    "OB/GYN": 85.0,
    "Pediatrics": 90.0,
    "Endocrinology": 75.0,
}

REFERENCE_DATE = "2026-01-15"


# ── Data generation helpers ──────────────────────────────────────────────────

def generate_members(n):
    """Generate n member records distributed evenly across service areas."""
    rows = []
    for i in range(n):
        sa = SERVICE_AREAS[i % len(SERVICE_AREAS)]
        lat = sa["center_lat"] + np.random.normal(0, MEMBER_COORD_STD)
        lon = sa["center_lon"] + np.random.normal(0, MEMBER_COORD_STD)
        rows.append({
            "member_id": i + 1,
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "plan_type": np.random.choice(PLAN_TYPES),
            "service_area_id": sa["area_id"],
            "enrollment_date": fake.date_between(
                start_date=date(2023, 1, 1), end_date=date(2025, 12, 31)
            ).isoformat(),
            "date_of_birth": fake.date_of_birth(
                minimum_age=1, maximum_age=85
            ).isoformat(),
            "gender": np.random.choice(["M", "F"]),
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "address": fake.street_address(),
            "city": sa["area_name"].split()[0],
            "state": "CA",
            "zip_code": fake.zipcode_in_state("CA"),
        })
    return pd.DataFrame(rows)


def generate_providers(n):
    """Generate n provider records."""
    credential_types = ["MD", "DO", "NP", "PA"]
    cred_weights = [0.50, 0.25, 0.15, 0.10]
    rows = []
    for i in range(n):
        rows.append({
            "provider_id": i + 1,
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "npi": str(fake.unique.random_number(digits=10, fix_len=True)),
            "accepting_new_patients": int(np.random.random() < 0.85),
            "credential_type": np.random.choice(credential_types, p=cred_weights),
        })
    return pd.DataFrame(rows)


def generate_provider_locations(n, n_providers):
    """Generate provider-specialty-location records.

    Each row links a provider to one specialty at one geographic location.
    Round-robin assignment guarantees every provider gets at least one location.
    """
    rows = []
    for i in range(n):
        pid = (i % n_providers) + 1

        area_idx = np.random.choice(len(SERVICE_AREAS), p=AREA_WEIGHTS)
        sa = SERVICE_AREAS[area_idx]

        spec_idx = np.random.choice(len(SPECIALTIES), p=SPECIALTY_WEIGHTS)
        specialty_id = SPECIALTIES[spec_idx]["specialty_id"]

        lat = sa["center_lat"] + np.random.normal(0, PROVIDER_COORD_STD)
        lon = sa["center_lon"] + np.random.normal(0, PROVIDER_COORD_STD)

        rows.append({
            "location_id": i + 1,
            "provider_id": pid,
            "specialty_id": specialty_id,
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "office_name": fake.company() + " Medical",
        })
    return pd.DataFrame(rows)


def generate_network_contracts(n, n_providers):
    """Generate network contract records.

    First pass: one contract per provider (cycling through plan types).
    Remaining rows add second/third contracts for random providers.
    """
    rows = []
    for i in range(n):
        if i < n_providers:
            pid = i + 1
            plan_type = PLAN_TYPES[i % len(PLAN_TYPES)]
        else:
            pid = int(np.random.randint(1, n_providers + 1))
            plan_type = np.random.choice(PLAN_TYPES)

        is_active = np.random.random() < 0.85

        eff = fake.date_between(start_date=date(2022, 1, 1), end_date=date(2024, 6, 30))
        if is_active:
            term = fake.date_between(start_date=date(2026, 6, 1), end_date=date(2027, 12, 31))
            status = "active"
        else:
            term = fake.date_between(start_date=date(2024, 7, 1), end_date=date(2025, 12, 31))
            status = "terminated"

        rows.append({
            "contract_id": i + 1,
            "provider_id": pid,
            "plan_type": plan_type,
            "effective_date": eff.isoformat(),
            "termination_date": term.isoformat(),
            "status": status,
        })
    return pd.DataFrame(rows)


def generate_provider_credentials(providers_df):
    """Generate credential data for workspace files.

    Returns a list of dicts (one per provider) with board-certification info.
    """
    ref = date.fromisoformat(REFERENCE_DATE)
    creds = []
    for _, row in providers_df.iterrows():
        board_cert = bool(np.random.random() < 0.88)
        if board_cert:
            if np.random.random() < 0.85:
                exp = fake.date_between(start_date=ref + timedelta(days=30),
                                        end_date=ref + timedelta(days=900))
            else:
                exp = fake.date_between(start_date=ref - timedelta(days=600),
                                        end_date=ref - timedelta(days=1))
        else:
            exp = None

        creds.append({
            "provider_id": int(row["provider_id"]),
            "provider_name": f"Dr. {row['first_name']} {row['last_name']}",
            "credential_type": row["credential_type"],
            "board_certified": board_cert,
            "certification_expiry": exp.isoformat() if exp else None,
        })
    return creds


# ── Database creation ────────────────────────────────────────────────────────

def create_database(db_path, members_df, providers_df, locations_df, contracts_df):
    """Persist all generated data into a SQLite database."""
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Reference tables
    cur.execute("""
        CREATE TABLE service_areas (
            area_id INTEGER PRIMARY KEY,
            area_name TEXT NOT NULL,
            area_type TEXT NOT NULL,
            state TEXT NOT NULL,
            center_lat REAL,
            center_lon REAL
        )
    """)
    for sa in SERVICE_AREAS:
        cur.execute(
            "INSERT INTO service_areas VALUES (?,?,?,?,?,?)",
            (sa["area_id"], sa["area_name"], sa["area_type"],
             sa["state"], sa["center_lat"], sa["center_lon"]),
        )

    cur.execute("""
        CREATE TABLE specialties (
            specialty_id INTEGER PRIMARY KEY,
            specialty_name TEXT NOT NULL,
            category TEXT NOT NULL
        )
    """)
    for sp in SPECIALTIES:
        cur.execute(
            "INSERT INTO specialties VALUES (?,?,?)",
            (sp["specialty_id"], sp["specialty_name"], sp["category"]),
        )

    # Main tables via pandas (handles schema automatically)
    members_df.to_sql("members", conn, if_exists="replace", index=False)
    providers_df.to_sql("providers", conn, if_exists="replace", index=False)
    locations_df.to_sql("provider_locations", conn, if_exists="replace", index=False)
    contracts_df.to_sql("network_contracts", conn, if_exists="replace", index=False)

    conn.commit()
    conn.close()


# ── Workspace creation ───────────────────────────────────────────────────────

def create_workspace(workspace, members_df, providers_df, credentials):
    """Build workspace directory with scalable data files and fixed config files."""
    os.makedirs(workspace, exist_ok=True)

    nf = SCALE["num_workspace_files"]
    n_roster = nf // 2
    n_cred = nf - n_roster

    # ── Scalable: member roster CSV files ────────────────────────────────
    roster_cols = ["member_id", "first_name", "last_name",
                   "address", "city", "state", "zip_code", "plan_type"]
    chunks = _split_df(members_df[roster_cols], n_roster)
    for idx, chunk in enumerate(chunks, start=1):
        fname = f"member_roster_{idx:03d}.csv"
        chunk.to_csv(os.path.join(workspace, fname), index=False)

    # ── Scalable: provider credential JSON files ─────────────────────────
    cred_chunks = np.array_split(range(len(credentials)), n_cred)
    for idx, indices in enumerate(cred_chunks, start=1):
        fname = f"provider_cred_{idx:03d}.json"
        records = [credentials[i] for i in indices]
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(records, f, indent=2)

    # ── Fixed: distance_thresholds.yaml ──────────────────────────────────
    yaml_lines = []
    for spec_name in sorted(DISTANCE_THRESHOLDS.keys()):
        by_area = DISTANCE_THRESHOLDS[spec_name]
        yaml_lines.append(f"{spec_name}:")
        for at in ["urban", "suburban", "rural"]:
            yaml_lines.append(f"  {at}: {by_area[at]}")
    with open(os.path.join(workspace, "distance_thresholds.yaml"), "w") as f:
        f.write("\n".join(yaml_lines) + "\n")

    # ── Fixed: compliance_standards.json ──────────────────────────────────
    standards = {
        "reference_date": REFERENCE_DATE,
        "required_coverage_pct": REQUIRED_COVERAGE_PCT,
    }
    with open(os.path.join(workspace, "compliance_standards.json"), "w") as f:
        json.dump(standards, f, indent=2)

    # ── Fixed: eligibility_rules.md ──────────────────────────────────────
    rules_md = (
        "# Provider Eligibility Criteria\n\n"
        "A provider is considered eligible to serve a member for a given specialty "
        "when ALL of the following conditions hold:\n\n"
        "1. The provider holds board certification that has not expired as of the "
        "compliance reference date specified in the compliance standards file.\n"
        "2. The provider is currently accepting new patients.\n"
        "3. The provider maintains at least one active network contract whose plan "
        "type matches the member's coverage plan.\n"
        "4. The straight-line (haversine) distance from the member's geocoded "
        "location to the provider's office location for that specialty does not "
        "exceed the distance threshold applicable to that specialty and the "
        "service area's classification (urban, suburban, or rural).\n\n"
        "## Coverage Determination\n\n"
        "- When a provider has multiple office locations registered for the same "
        "specialty, use the location closest to the member for the distance check.\n"
        "- A member is covered for a specialty if at least one eligible provider "
        "exists within the applicable distance threshold.\n"
        "- Coverage percentage for a service-area / specialty pair equals "
        "(number of covered members / total members in that service area) "
        "multiplied by 100, rounded to two decimal places.\n"
        "- The pair is compliant when its coverage percentage meets or exceeds "
        "the required coverage percentage from the compliance standards.\n"
    )
    with open(os.path.join(workspace, "eligibility_rules.md"), "w") as f:
        f.write(rules_md)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate network adequacy data.")
    parser.add_argument("--db_path", required=True, help="Path to SQLite database file.")
    parser.add_argument("--workspace", required=True, help="Path to workspace directory.")
    args = parser.parse_args()

    n = SCALE["rows_per_table"]

    # Generate data frames
    members_df = generate_members(n)
    providers_df = generate_providers(n)
    n_locations = max(n, int(n * 1.5))
    locations_df = generate_provider_locations(n_locations, n)
    n_contracts = max(n, n * 2)
    contracts_df = generate_network_contracts(n_contracts, n)
    credentials = generate_provider_credentials(providers_df)

    # Persist
    create_database(args.db_path, members_df, providers_df, locations_df, contracts_df)
    create_workspace(args.workspace, members_df, providers_df, credentials)

    print(f"Database written to {args.db_path}")
    print(f"  members:            {len(members_df)} rows")
    print(f"  providers:          {len(providers_df)} rows")
    print(f"  provider_locations: {len(locations_df)} rows")
    print(f"  network_contracts:  {len(contracts_df)} rows")
    print(f"Workspace created at {args.workspace}")
    print(f"  scalable files:     {SCALE['num_workspace_files']}")
    print(f"  fixed config files: 3")


if __name__ == "__main__":
    main()
