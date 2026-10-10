import sqlite3
import os
import json
import csv
import argparse
import math
import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 640,
    "num_workspace_files": 48,
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REGIONS = ["NE-101", "SE-202", "MW-303", "SW-404", "WE-505"]
PROGRAM_TYPES = ["HCV", "PBV", "PH"]
UTILITY_TYPES = ["electric", "gas", "water", "trash"]
INCOME_SOURCES = [
    "Employment", "Self-Employment", "Social Security",
    "SSI", "Pension", "TANF", "Unemployment", "Child Support",
]
BEDROOM_COUNTS = [0, 1, 2, 3, 4]

# Area Median Income base (4-person household) per region
AMI_BASE_4PERSON = {
    "NE-101": 78000,
    "SE-202": 62000,
    "MW-303": 67000,
    "SW-404": 56000,
    "WE-505": 88000,
}

# Household-size adjustment factors (HUD standard ratios)
HH_SIZE_FACTORS = {
    1: 0.70, 2: 0.80, 3: 0.90, 4: 1.00,
    5: 1.08, 6: 1.16, 7: 1.24, 8: 1.32,
}

# Fair Market Rent per region/bedroom (2026 base year)
FMR_TABLE = {
    "NE-101": {0: 950, 1: 1100, 2: 1350, 3: 1650, 4: 1850},
    "SE-202": {0: 780, 1: 900,  2: 1100, 3: 1350, 4: 1500},
    "MW-303": {0: 820, 1: 950,  2: 1150, 3: 1400, 4: 1580},
    "SW-404": {0: 720, 1: 830,  2: 1020, 3: 1250, 4: 1400},
    "WE-505": {0: 1100, 1: 1280, 2: 1550, 3: 1900, 4: 2150},
}

# Utility allowance per region/bedroom
UTILITY_ALLOW = {
    "NE-101": {0: 82, 1: 97,  2: 120, 3: 140, 4: 155},
    "SE-202": {0: 75, 1: 89,  2: 110, 3: 128, 4: 142},
    "MW-303": {0: 79, 1: 93,  2: 115, 3: 134, 4: 148},
    "SW-404": {0: 70, 1: 83,  2: 102, 3: 119, 4: 132},
    "WE-505": {0: 90, 1: 106, 2: 131, 3: 153, 4: 169},
}

# FMR yearly growth factors (relative to 2026)
FMR_YEARS = [2023, 2024, 2025, 2026]
FMR_GROWTH = {2023: 0.91, 2024: 0.94, 2025: 0.97, 2026: 1.00}

# Policy parameters (also written to workspace)
POLICY = {
    "income_threshold_pct": 0.80,
    "min_utility_compliance": 0.60,
    "min_inspection_score": 60,
    "rent_burden_ratio": 0.30,
    "minimum_rent": 50.0,
    "adjustment_threshold": 0.10,
    "effective_date": "2026-05-01",
    "critical_deficiency_auto_suspend": True,
}

# Deficiency templates
MINOR_DEFS = [
    "Peeling paint on exterior wall section",
    "Minor crack in sidewalk near entrance",
    "Loose doorknob on storage closet",
    "Stained ceiling tile in second-floor hallway",
    "Worn carpet in common area near elevator",
    "Missing caulking around window frame, Unit {u}",
    "Small water stain on ceiling, Unit {u}",
    "Chipped tile in lobby restroom",
    "Faded exit sign on ground floor",
    "Squeaky hinge on laundry room door",
]
MAJOR_DEFS = [
    "Broken handrail on rear staircase",
    "Water damage on basement ceiling requiring repair",
    "HVAC system operating at reduced capacity",
    "Cracked window pane in common area, Building {b}",
    "Damaged roof flashing causing intermittent leak",
    "Insufficient exterior lighting in parking area",
    "Trip hazard from raised concrete slab at entrance",
    "Deteriorating grout in communal shower facility",
]
CRITICAL_DEFS = [
    "Non-functional fire escape mechanism, Building {b}",
    "Exposed electrical wiring in laundry room",
    "Inoperative smoke detector on residential floor {f}",
    "Structural crack in load-bearing wall, Building {b}",
    "Gas leak detected near boiler room",
    "Mold contamination in ventilation ductwork",
    "Missing carbon monoxide detector in occupied unit",
    "Blocked emergency exit on floor {f}",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_ami(region_code, household_size):
    base = AMI_BASE_4PERSON[region_code]
    hs = max(1, min(8, household_size))
    factor = HH_SIZE_FACTORS.get(hs, HH_SIZE_FACTORS[4])
    return base * factor


def compute_benefit(annual_income, fmr, utility_allowance):
    contribution = max(annual_income * POLICY["rent_burden_ratio"] / 12.0,
                       POLICY["minimum_rent"])
    benefit = fmr + utility_allowance - contribution
    return round(max(benefit, 0.0), 2)


def distribute(items, n_batches):
    """Distribute items round-robin across n_batches."""
    batches = [[] for _ in range(n_batches)]
    for i, item in enumerate(items):
        batches[i % n_batches].append(item)
    return batches


# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------
def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS tenants (
        tenant_id TEXT PRIMARY KEY,
        first_name TEXT,
        last_name TEXT,
        property_id TEXT,
        unit_number TEXT,
        region_code TEXT,
        bedroom_count INTEGER,
        program_type TEXT,
        enrollment_date TEXT,
        active INTEGER
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS properties (
        property_id TEXT PRIMARY KEY,
        property_name TEXT,
        address TEXT,
        region_code TEXT,
        total_units INTEGER,
        year_built INTEGER,
        owner_name TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS income_certifications (
        cert_id TEXT PRIMARY KEY,
        tenant_id TEXT,
        certification_date TEXT,
        annual_income REAL,
        income_source TEXT,
        household_size INTEGER,
        dependents INTEGER,
        is_verified INTEGER,
        FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS utility_bills (
        bill_id TEXT PRIMARY KEY,
        tenant_id TEXT,
        bill_month TEXT,
        utility_type TEXT,
        amount_due REAL,
        amount_paid REAL,
        due_date TEXT,
        paid_date TEXT,
        FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS inspections (
        inspection_id TEXT PRIMARY KEY,
        property_id TEXT,
        inspection_date TEXT,
        overall_score INTEGER,
        health_safety_score INTEGER,
        maintenance_score INTEGER,
        deficiency_count INTEGER,
        FOREIGN KEY(property_id) REFERENCES properties(property_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS fair_market_rents (
        fmr_id TEXT PRIMARY KEY,
        region_code TEXT,
        bedroom_count INTEGER,
        monthly_fmr REAL,
        effective_year INTEGER
    )""")
    conn.commit()


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------
def generate_all(n_rows, n_files):
    fake = Faker()
    Faker.seed(42)
    np.random.seed(42)

    # ---- Properties ----
    properties = []
    suffixes = ["Apartments", "Complex", "Residences", "Towers", "Village",
                "Place", "Court", "Manor", "Gardens", "Heights"]
    for i in range(n_rows):
        region = REGIONS[i % len(REGIONS)]
        properties.append({
            "property_id": f"P{i+1:04d}",
            "property_name": fake.last_name() + " " + suffixes[i % len(suffixes)],
            "address": fake.address().replace("\n", ", "),
            "region_code": region,
            "total_units": int(np.random.randint(10, 101)),
            "year_built": int(np.random.randint(1960, 2016)),
            "owner_name": fake.name(),
        })
    prop_by_id = {p["property_id"]: p for p in properties}

    # ---- Tenants ----
    tenants = []
    active_flags = (np.random.random(n_rows) < 0.85).astype(int)
    for i in range(n_rows):
        prop_idx = int(np.random.randint(0, len(properties)))
        prop = properties[prop_idx]
        tenants.append({
            "tenant_id": f"T{i+1:04d}",
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "property_id": prop["property_id"],
            "unit_number": f"{np.random.randint(1, 10)}{chr(65 + int(np.random.randint(0, 4)))}",
            "region_code": prop["region_code"],
            "bedroom_count": int(np.random.choice(BEDROOM_COUNTS, p=[0.05, 0.25, 0.35, 0.25, 0.10])),
            "program_type": str(np.random.choice(PROGRAM_TYPES)),
            "enrollment_date": fake.date_between(start_date="-10y", end_date="-1y").isoformat(),
            "active": int(active_flags[i]),
        })

    active_tenants = [t for t in tenants if t["active"] == 1]
    n_active = len(active_tenants)

    # ---- Household sizes (cert vs current) ----
    cert_hh_sizes = np.random.choice([1, 2, 3, 4, 5, 6], size=n_rows,
                                     p=[0.10, 0.25, 0.30, 0.20, 0.10, 0.05])
    hh_change_mask = np.random.random(n_rows) < 0.20
    hh_delta = np.random.choice([-1, 1], size=n_rows)
    current_hh_sizes = cert_hh_sizes.copy()
    current_hh_sizes[hh_change_mask] = np.clip(
        cert_hh_sizes[hh_change_mask] + hh_delta[hh_change_mask], 1, 8
    )

    for i, t in enumerate(tenants):
        t["_cert_hh_size"] = int(cert_hh_sizes[i])
        t["_current_hh_size"] = int(current_hh_sizes[i])

    # ---- Income generation ----
    income_limits = np.array([
        get_ami(t["region_code"], t["_current_hh_size"]) * POLICY["income_threshold_pct"]
        for t in tenants
    ])

    over_income_mask = np.random.random(n_rows) < 0.12
    recent_income_fracs = np.where(
        over_income_mask,
        np.random.uniform(1.03, 1.30, n_rows),
        np.random.uniform(0.30, 0.92, n_rows),
    )
    recent_incomes = np.round(income_limits * recent_income_fracs, 2)

    change_type = np.random.choice(
        ["up", "down", "stable"], size=n_rows, p=[0.15, 0.15, 0.70]
    )
    old_income_factor = np.where(
        change_type == "up",
        np.random.uniform(0.60, 0.82, n_rows),
        np.where(
            change_type == "down",
            np.random.uniform(1.20, 1.50, n_rows),
            np.random.uniform(0.96, 1.04, n_rows),
        )
    )
    old_incomes = np.round(recent_incomes * old_income_factor, 2)

    # ---- Income certifications ----
    certs = []
    cert_counter = 0
    for i, t in enumerate(tenants):
        cert_counter += 1
        old_date = fake.date_between(start_date="-22m", end_date="-15m").isoformat()
        certs.append({
            "cert_id": f"IC{cert_counter:06d}",
            "tenant_id": t["tenant_id"],
            "certification_date": old_date,
            "annual_income": float(old_incomes[i]),
            "income_source": str(np.random.choice(INCOME_SOURCES)),
            "household_size": int(cert_hh_sizes[i]),
            "dependents": max(0, int(cert_hh_sizes[i]) - 1),
            "is_verified": 1,
        })
        cert_counter += 1
        recent_date = fake.date_between(start_date="-10m", end_date="-3m").isoformat()
        certs.append({
            "cert_id": f"IC{cert_counter:06d}",
            "tenant_id": t["tenant_id"],
            "certification_date": recent_date,
            "annual_income": float(recent_incomes[i]),
            "income_source": str(np.random.choice(INCOME_SOURCES)),
            "household_size": int(cert_hh_sizes[i]),
            "dependents": max(0, int(cert_hh_sizes[i]) - 1),
            "is_verified": 1,
        })

    # ---- Utility compliance ----
    low_compliance_mask = np.random.random(n_rows) < 0.12
    compliance_rates = np.where(
        low_compliance_mask,
        np.random.uniform(0.35, 0.58, n_rows),
        np.random.uniform(0.65, 1.00, n_rows),
    )
    compliance_rates = np.round(compliance_rates, 2)

    # ---- Utility bills (for DB, derived from compliance) ----
    bills = []
    bill_counter = 0
    months = [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 4)]
    for i, t in enumerate(tenants):
        n_bills_total = len(months) * len(UTILITY_TYPES)
        n_late = int(round(n_bills_total * (1.0 - compliance_rates[i])))
        late_indices = set(np.random.choice(n_bills_total, size=min(n_late, n_bills_total),
                                            replace=False)) if n_late > 0 else set()
        bill_idx = 0
        for month in months:
            for utype in UTILITY_TYPES:
                bill_counter += 1
                is_late = bill_idx in late_indices
                amount = round(float(np.random.uniform(40, 250)), 2)
                due_date = f"{month}-15"
                if is_late:
                    offset = int(np.random.randint(5, 20))
                    day = min(28, 15 + offset)
                    paid_date = f"{month}-{day:02d}"
                    amount_paid = round(amount * float(np.random.uniform(0.0, 1.0)), 2)
                else:
                    day = int(np.random.randint(1, 16))
                    paid_date = f"{month}-{day:02d}"
                    amount_paid = amount
                bills.append({
                    "bill_id": f"UB{bill_counter:06d}",
                    "tenant_id": t["tenant_id"],
                    "bill_month": month,
                    "utility_type": utype,
                    "amount_due": amount,
                    "amount_paid": amount_paid,
                    "due_date": due_date,
                    "paid_date": paid_date,
                })
                bill_idx += 1

    # ---- Inspections ----
    low_score_mask = np.random.random(n_rows) < 0.15
    scores = np.where(
        low_score_mask,
        np.random.randint(30, 59, n_rows),
        np.random.randint(62, 100, n_rows),
    )
    critical_mask = np.random.random(n_rows) < 0.08
    critical_property_ids = set()

    inspections = []
    deficiency_details = {}
    for i, p in enumerate(properties):
        score = int(scores[i])
        hs_score = int(np.clip(score + int(np.random.randint(-10, 11)), 0, 100))
        maint_score = int(np.clip(score + int(np.random.randint(-10, 11)), 0, 100))

        defs_list = []
        if score < 50:
            n_minor = int(np.random.randint(2, 5))
            n_major = int(np.random.randint(1, 4))
        elif score < 70:
            n_minor = int(np.random.randint(1, 4))
            n_major = int(np.random.randint(0, 3))
        elif score < 85:
            n_minor = int(np.random.randint(0, 3))
            n_major = int(np.random.randint(0, 2))
        else:
            n_minor = int(np.random.randint(0, 2))
            n_major = 0

        for _ in range(n_minor):
            desc = str(np.random.choice(MINOR_DEFS)).format(
                u=f"{np.random.randint(1,10)}{chr(65+int(np.random.randint(0,4)))}")
            defs_list.append(("MINOR", desc))
        for _ in range(n_major):
            desc = str(np.random.choice(MAJOR_DEFS)).format(
                b=chr(65 + int(np.random.randint(0, 3))))
            defs_list.append(("MAJOR", desc))

        if bool(critical_mask[i]):
            critical_property_ids.add(p["property_id"])
            desc = str(np.random.choice(CRITICAL_DEFS)).format(
                b=chr(65 + int(np.random.randint(0, 3))),
                f=int(np.random.randint(1, 6)))
            defs_list.append(("CRITICAL", desc))
        if score < 40 and p["property_id"] not in critical_property_ids:
            if float(np.random.random()) < 0.5:
                critical_property_ids.add(p["property_id"])
                desc = str(np.random.choice(CRITICAL_DEFS)).format(
                    b=chr(65 + int(np.random.randint(0, 3))),
                    f=int(np.random.randint(1, 6)))
                defs_list.append(("CRITICAL", desc))

        deficiency_details[p["property_id"]] = defs_list
        def_count = len(defs_list)

        insp_date = fake.date_between(start_date="-8m", end_date="-1m").isoformat()
        for j in range(2):
            insp_id = f"IN{i*2+j+1:05d}"
            if j == 0:
                old_insp_date = fake.date_between(start_date="-20m", end_date="-10m").isoformat()
                old_score = int(np.clip(score + int(np.random.randint(-15, 16)), 0, 100))
                inspections.append({
                    "inspection_id": insp_id,
                    "property_id": p["property_id"],
                    "inspection_date": old_insp_date,
                    "overall_score": old_score,
                    "health_safety_score": int(np.clip(old_score + int(np.random.randint(-10, 11)), 0, 100)),
                    "maintenance_score": int(np.clip(old_score + int(np.random.randint(-10, 11)), 0, 100)),
                    "deficiency_count": max(0, def_count + int(np.random.randint(-2, 3))),
                })
            else:
                inspections.append({
                    "inspection_id": insp_id,
                    "property_id": p["property_id"],
                    "inspection_date": insp_date,
                    "overall_score": score,
                    "health_safety_score": hs_score,
                    "maintenance_score": maint_score,
                    "deficiency_count": def_count,
                })

    # ---- Fair Market Rents ----
    fmr_data = []
    fmr_counter = 0
    for region in REGIONS:
        for br in BEDROOM_COUNTS:
            base = FMR_TABLE[region][br]
            for year in FMR_YEARS:
                fmr_counter += 1
                fmr_data.append({
                    "fmr_id": f"FMR{fmr_counter:04d}",
                    "region_code": region,
                    "bedroom_count": br,
                    "monthly_fmr": round(base * FMR_GROWTH[year], 2),
                    "effective_year": year,
                })

    # ---- Compute current benefits (from old income) ----
    current_benefits = {}
    for i, t in enumerate(tenants):
        if t["active"] != 1:
            continue
        fmr = FMR_TABLE[t["region_code"]][t["bedroom_count"]]
        ua = UTILITY_ALLOW[t["region_code"]][t["bedroom_count"]]
        current_benefits[t["tenant_id"]] = compute_benefit(
            float(old_incomes[i]), fmr, ua)

    return {
        "properties": properties,
        "tenants": tenants,
        "certs": certs,
        "bills": bills,
        "inspections": inspections,
        "fmr_data": fmr_data,
        "compliance_rates": {t["tenant_id"]: float(compliance_rates[i]) for i, t in enumerate(tenants)},
        "current_benefits": current_benefits,
        "deficiency_details": deficiency_details,
        "critical_property_ids": critical_property_ids,
    }


# ---------------------------------------------------------------------------
# Workspace creation
# ---------------------------------------------------------------------------
def create_workspace(workspace, data, n_files):
    os.makedirs(workspace, exist_ok=True)

    tenants = data["tenants"]
    properties = data["properties"]

    n_profiles = max(1, n_files // 3)
    n_compliance = max(1, n_files // 3)
    n_inspections = max(1, n_files // 6)
    n_ami = max(1, n_files - n_profiles - n_compliance - n_inspections)

    # ---- Policy directory (fixed files) ----
    policy_dir = os.path.join(workspace, "policy")
    os.makedirs(policy_dir, exist_ok=True)

    with open(os.path.join(policy_dir, "eligibility_rules.yaml"), "w") as f:
        yaml.dump(POLICY, f, default_flow_style=False, sort_keys=False)

    with open(os.path.join(policy_dir, "utility_allowance_schedule.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["region_code", "bedroom_count", "monthly_allowance"])
        for region in REGIONS:
            for br in BEDROOM_COUNTS:
                w.writerow([region, br, UTILITY_ALLOW[region][br]])

    # ---- current_benefits.csv (fixed, one file) ----
    with open(os.path.join(workspace, "current_benefits.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tenant_id", "current_monthly_benefit"])
        for tid in sorted(data["current_benefits"].keys()):
            w.writerow([tid, f"{data['current_benefits'][tid]:.2f}"])

    # ---- Profiles (JSON, scalable) ----
    profiles_dir = os.path.join(workspace, "profiles")
    os.makedirs(profiles_dir, exist_ok=True)
    profile_batches = distribute(tenants, n_profiles)
    for batch_idx, batch in enumerate(profile_batches):
        batch_data = {}
        for t in batch:
            batch_data[t["tenant_id"]] = {
                "current_household_size": t["_current_hh_size"],
                "special_needs": bool(np.random.random() < 0.08),
                "accommodation_type": str(np.random.choice(
                    ["standard", "accessible", "elderly", "family"],
                    p=[0.70, 0.10, 0.10, 0.10])),
            }
        with open(os.path.join(profiles_dir, f"batch_{batch_idx+1:02d}.json"), "w") as f:
            json.dump(batch_data, f, indent=2)

    # ---- Compliance (CSV, scalable) ----
    compliance_dir = os.path.join(workspace, "compliance")
    os.makedirs(compliance_dir, exist_ok=True)
    compliance_batches = distribute(tenants, n_compliance)
    for batch_idx, batch in enumerate(compliance_batches):
        with open(os.path.join(compliance_dir, f"records_{batch_idx+1:02d}.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["tenant_id", "utility_compliance_rate", "review_period",
                         "total_bills", "on_time_payments"])
            for t in batch:
                rate = data["compliance_rates"][t["tenant_id"]]
                total = 60
                on_time = int(round(total * rate))
                w.writerow([t["tenant_id"], f"{rate:.2f}", "2025-01 to 2026-03",
                            total, on_time])

    # ---- Inspection reports (MD, scalable) ----
    insp_dir = os.path.join(workspace, "inspections")
    os.makedirs(insp_dir, exist_ok=True)
    insp_batches = distribute(properties, n_inspections)
    for batch_idx, batch in enumerate(insp_batches):
        lines = []
        for p in batch:
            defs = data["deficiency_details"].get(p["property_id"], [])
            latest_insp = None
            for insp in data["inspections"]:
                if insp["property_id"] == p["property_id"]:
                    if latest_insp is None or insp["inspection_date"] > latest_insp["inspection_date"]:
                        latest_insp = insp
            lines.append(f"## Property {p['property_id']} - {p['property_name']}")
            lines.append("")
            if latest_insp:
                lines.append(f"**Inspection Date:** {latest_insp['inspection_date']}")
                lines.append(f"**Overall Score:** {latest_insp['overall_score']}")
                lines.append(f"**Deficiency Count:** {latest_insp['deficiency_count']}")
            lines.append("")
            if defs:
                lines.append("### Deficiency List")
                for severity, desc in defs:
                    lines.append(f"- [{severity}] {desc}")
            else:
                lines.append("No deficiencies recorded.")
            lines.append("")
            lines.append("---")
            lines.append("")
        with open(os.path.join(insp_dir, f"report_{batch_idx+1:02d}.md"), "w") as f:
            f.write("\n".join(lines))

    # ---- AMI data (YAML, scalable) ----
    ami_dir = os.path.join(workspace, "ami_data")
    os.makedirs(ami_dir, exist_ok=True)
    ami_entries = []
    for region in REGIONS:
        for hh_size in sorted(HH_SIZE_FACTORS.keys()):
            ami_entries.append({
                "region_code": region,
                "household_size": int(hh_size),
                "area_median_income": float(get_ami(region, hh_size)),
            })
    ami_batches = distribute(ami_entries, n_ami)
    for batch_idx, batch in enumerate(ami_batches):
        with open(os.path.join(ami_dir, f"schedule_{batch_idx+1:02d}.yaml"), "w") as f:
            yaml.dump({"ami_records": batch}, f, default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    data = generate_all(n_rows, n_files)

    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    conn.executemany(
        "INSERT INTO properties VALUES (?,?,?,?,?,?,?)",
        [(p["property_id"], p["property_name"], p["address"],
          p["region_code"], p["total_units"], p["year_built"], p["owner_name"])
         for p in data["properties"]])

    conn.executemany(
        "INSERT INTO tenants VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(t["tenant_id"], t["first_name"], t["last_name"], t["property_id"],
          t["unit_number"], t["region_code"], t["bedroom_count"],
          t["program_type"], t["enrollment_date"], t["active"])
         for t in data["tenants"]])

    conn.executemany(
        "INSERT INTO income_certifications VALUES (?,?,?,?,?,?,?,?)",
        [(c["cert_id"], c["tenant_id"], c["certification_date"],
          c["annual_income"], c["income_source"], c["household_size"],
          c["dependents"], c["is_verified"])
         for c in data["certs"]])

    conn.executemany(
        "INSERT INTO utility_bills VALUES (?,?,?,?,?,?,?,?)",
        [(b["bill_id"], b["tenant_id"], b["bill_month"], b["utility_type"],
          b["amount_due"], b["amount_paid"], b["due_date"], b["paid_date"])
         for b in data["bills"]])

    conn.executemany(
        "INSERT INTO inspections VALUES (?,?,?,?,?,?,?)",
        [(ins["inspection_id"], ins["property_id"], ins["inspection_date"],
          ins["overall_score"], ins["health_safety_score"],
          ins["maintenance_score"], ins["deficiency_count"])
         for ins in data["inspections"]])

    conn.executemany(
        "INSERT INTO fair_market_rents VALUES (?,?,?,?,?)",
        [(f["fmr_id"], f["region_code"], f["bedroom_count"],
          f["monthly_fmr"], f["effective_year"])
         for f in data["fmr_data"]])

    conn.commit()
    conn.close()

    create_workspace(args.workspace, data, n_files)

    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")
    n_active = sum(1 for t in data["tenants"] if t["active"] == 1)
    print(f"Tables: tenants={len(data['tenants'])}, properties={len(data['properties'])}, "
          f"certs={len(data['certs'])}, bills={len(data['bills'])}, "
          f"inspections={len(data['inspections'])}, fmr={len(data['fmr_data'])}")
    print(f"Active tenants: {n_active}")
    print(f"Workspace files: {n_files} scalable + 3 fixed")


if __name__ == "__main__":
    main()
