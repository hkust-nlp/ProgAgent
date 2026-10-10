"""
REC Portfolio Compliance Gap Analysis - Data Generator (v0)
Generates SQLite DB and workspace files for REC compliance analysis task.
"""

import argparse
import csv
import json
import os
import random
import sqlite3
from datetime import date

import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 60,
    "num_workspace_files": 8,
}

JURISDICTIONS = ["CA", "TX", "NY", "PJM", "MISO", "SPP", "ISO-NE", "ERCOT"]
TECH_TYPES = ["solar", "wind", "biomass", "geothermal", "small_hydro"]
SUBMISSION_TYPES = [
    "annual_compliance",
    "quarterly_report_q1",
    "quarterly_report_q2",
    "quarterly_report_q3",
    "quarterly_report_q4",
    "mid_year_review",
    "preliminary_filing",
    "final_reconciliation",
]
CERT_STATUSES = ["active", "retired", "expired", "pending_verification"]
DELIVERY_STATUSES = ["delivered", "pending", "partial", "cancelled"]
TECH_PREFERENCES = ["solar", "wind", "biomass", "geothermal", "small_hydro", "any", None]

TECHNOLOGY_MULTIPLIERS = {
    "solar": 1.0,
    "wind": 1.2,
    "biomass": 0.8,
    "geothermal": 1.5,
    "small_hydro": 1.1,
}

PENALTY_SCHEDULE = {
    "CA": {"penalty_rate_per_mwh": 50.0, "grace_period_days": 15},
    "TX": {"penalty_rate_per_mwh": 35.0, "grace_period_days": 10},
    "NY": {"penalty_rate_per_mwh": 60.0, "grace_period_days": 20},
    "PJM": {"penalty_rate_per_mwh": 45.0, "grace_period_days": 12},
    "MISO": {"penalty_rate_per_mwh": 40.0, "grace_period_days": 18},
    "SPP": {"penalty_rate_per_mwh": 30.0, "grace_period_days": 8},
    "ISO-NE": {"penalty_rate_per_mwh": 55.0, "grace_period_days": 14},
    "ERCOT": {"penalty_rate_per_mwh": 38.0, "grace_period_days": 10},
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    np.random.seed(42)
    random.seed(42)
    fake = Faker()
    Faker.seed(42)

    rows = SCALE["rows_per_table"]
    num_ws = SCALE["num_workspace_files"]

    os.makedirs(args.workspace, exist_ok=True)

    # Remove existing DB
    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    cur = conn.cursor()

    # ── Table 1: portfolios ──
    cur.execute("""
        CREATE TABLE portfolios (
            portfolio_id TEXT PRIMARY KEY,
            owner_name TEXT,
            jurisdiction_code TEXT,
            compliance_year INTEGER,
            target_mwh REAL,
            technology_preference TEXT
        )
    """)

    comp_years = np.random.choice(
        [2026, 2025, 2027, 2024], size=rows, p=[0.4, 0.3, 0.2, 0.1]
    )
    portfolios = []
    for i in range(rows):
        pid = f"P-{i + 1:04d}"
        owner = fake.name()
        jur = random.choice(JURISDICTIONS)
        cy = int(comp_years[i])
        target = round(random.uniform(200, 800), 2)
        tp = random.choice(TECH_PREFERENCES)
        portfolios.append((pid, owner, jur, cy, target, tp))
    cur.executemany(
        "INSERT INTO portfolios VALUES (?,?,?,?,?,?)", portfolios
    )

    # ── Table 2: facilities ──
    cur.execute("""
        CREATE TABLE facilities (
            facility_id TEXT PRIMARY KEY,
            facility_name TEXT,
            tech_type TEXT,
            jurisdiction_code TEXT,
            capacity_rating_mw REAL,
            commissioning_date TEXT
        )
    """)

    facilities = []
    for i in range(rows):
        fid = f"F-{i + 1:04d}"
        fname = fake.company() + " " + random.choice(
            ["Solar Farm", "Wind Park", "Biomass Plant", "Geothermal Station", "Hydro Facility"]
        )
        tt = random.choice(TECH_TYPES)
        jur = random.choice(JURISDICTIONS)
        cap = round(random.uniform(5, 100), 2)
        comm = date(
            random.randint(2015, 2024), random.randint(1, 12), random.randint(1, 28)
        ).isoformat()
        facilities.append((fid, fname, tt, jur, cap, comm))
    cur.executemany(
        "INSERT INTO facilities VALUES (?,?,?,?,?,?)", facilities
    )

    # ── Table 3: certificates (3 * rows) ──
    cur.execute("""
        CREATE TABLE certificates (
            cert_id TEXT PRIMARY KEY,
            portfolio_id TEXT,
            vintage_year INTEGER,
            vintage_month INTEGER,
            tech_type TEXT,
            capacity_mwh REAL,
            status TEXT,
            facility_id TEXT,
            FOREIGN KEY (portfolio_id) REFERENCES portfolios(portfolio_id),
            FOREIGN KEY (facility_id) REFERENCES facilities(facility_id)
        )
    """)

    num_certs = 3 * rows
    portfolio_ids = [p[0] for p in portfolios]
    facility_ids = [f[0] for f in facilities]

    # Each portfolio gets at least 2 certs via round-robin
    cert_portfolio_assignments = []
    for pid in portfolio_ids:
        cert_portfolio_assignments.extend([pid] * 2)
    remaining = num_certs - len(cert_portfolio_assignments)
    if remaining > 0:
        extra_pids = np.random.choice(portfolio_ids, size=remaining).tolist()
        cert_portfolio_assignments.extend(extra_pids)
    random.shuffle(cert_portfolio_assignments)

    status_choices = np.random.choice(
        CERT_STATUSES, size=num_certs, p=[0.50, 0.15, 0.15, 0.20]
    )

    certificates = []
    for i in range(num_certs):
        cid = f"REC-{i + 1:04d}"
        pid = cert_portfolio_assignments[i]
        vy = random.choice([2022, 2023, 2024, 2025, 2026])
        vm = random.randint(1, 12)
        tt = random.choice(TECH_TYPES)
        cap = round(random.uniform(10, 50), 2)
        st = str(status_choices[i])
        fid = random.choice(facility_ids)
        certificates.append((cid, pid, vy, vm, tt, cap, st, fid))
    cur.executemany(
        "INSERT INTO certificates VALUES (?,?,?,?,?,?,?,?)", certificates
    )

    # ── Table 4: purchase_contracts (2 * rows) ──
    cur.execute("""
        CREATE TABLE purchase_contracts (
            contract_id TEXT PRIMARY KEY,
            portfolio_id TEXT,
            vendor_name TEXT,
            execution_date TEXT,
            delivery_date TEXT,
            contracted_mwh REAL,
            price_per_mwh REAL,
            delivery_status TEXT,
            FOREIGN KEY (portfolio_id) REFERENCES portfolios(portfolio_id)
        )
    """)

    num_contracts = 2 * rows
    contract_portfolio_assignments = []
    for pid in portfolio_ids:
        contract_portfolio_assignments.append(pid)
    remaining = num_contracts - len(contract_portfolio_assignments)
    if remaining > 0:
        extra_pids = np.random.choice(portfolio_ids, size=remaining).tolist()
        contract_portfolio_assignments.extend(extra_pids)
    random.shuffle(contract_portfolio_assignments)

    ds_choices = np.random.choice(
        DELIVERY_STATUSES, size=num_contracts, p=[0.30, 0.35, 0.15, 0.20]
    )

    contracts = []
    for i in range(num_contracts):
        cid = f"CON-{i + 1:04d}"
        pid = contract_portfolio_assignments[i]
        vendor = fake.company()
        exec_date = date(2025, random.randint(1, 12), random.randint(1, 28)).isoformat()
        del_date = date(2026, random.randint(1, 12), random.randint(1, 28)).isoformat()
        cmwh = round(random.uniform(50, 200), 2)
        ppm = round(random.uniform(15, 60), 2)
        ds = str(ds_choices[i])
        contracts.append((cid, pid, vendor, exec_date, del_date, cmwh, ppm, ds))
    cur.executemany(
        "INSERT INTO purchase_contracts VALUES (?,?,?,?,?,?,?,?)", contracts
    )

    # ── Table 5: grid_injections (2 * rows) ──
    cur.execute("""
        CREATE TABLE grid_injections (
            injection_id TEXT PRIMARY KEY,
            facility_id TEXT,
            injection_date TEXT,
            injected_mwh REAL,
            meter_id TEXT,
            verified INTEGER,
            credited INTEGER,
            FOREIGN KEY (facility_id) REFERENCES facilities(facility_id)
        )
    """)

    num_injections = 2 * rows
    inj_facility_assignments = []
    for fid in facility_ids:
        inj_facility_assignments.append(fid)
    remaining = num_injections - len(inj_facility_assignments)
    if remaining > 0:
        extra_fids = np.random.choice(facility_ids, size=remaining).tolist()
        inj_facility_assignments.extend(extra_fids)
    random.shuffle(inj_facility_assignments)

    injections = []
    for i in range(num_injections):
        iid = f"INJ-{i + 1:04d}"
        fid = inj_facility_assignments[i]
        inj_date = date(2026, random.randint(1, 4), random.randint(1, 28)).isoformat()
        imwh = round(random.uniform(5, 40), 2)
        meter = f"MTR-{random.randint(1000, 9999)}"
        verified = 1 if random.random() < 0.70 else 0
        credited = 1 if random.random() < 0.60 else 0
        injections.append((iid, fid, inj_date, imwh, meter, verified, credited))
    cur.executemany(
        "INSERT INTO grid_injections VALUES (?,?,?,?,?,?,?)", injections
    )

    # ── Table 6: regulatory_deadlines ──
    cur.execute("""
        CREATE TABLE regulatory_deadlines (
            deadline_id TEXT PRIMARY KEY,
            jurisdiction_code TEXT,
            submission_type TEXT,
            deadline_date TEXT,
            description TEXT
        )
    """)

    deadlines = []
    dl_idx = 0
    for jur in JURISDICTIONS:
        for st in SUBMISSION_TYPES:
            dl_idx += 1
            did = f"DL-{dl_idx:04d}"
            if st == "annual_compliance":
                month = random.randint(5, 9)
                day = random.randint(1, 28)
                dd = date(2026, month, day).isoformat()
            elif st == "quarterly_report_q1":
                dd = date(2026, 4, random.randint(1, 28)).isoformat()
            elif st == "quarterly_report_q2":
                dd = date(2026, 7, random.randint(1, 28)).isoformat()
            elif st == "quarterly_report_q3":
                dd = date(2026, 10, random.randint(1, 28)).isoformat()
            elif st == "quarterly_report_q4":
                dd = date(2027, 1, random.randint(1, 28)).isoformat()
            elif st == "mid_year_review":
                dd = date(2026, 6, random.randint(1, 28)).isoformat()
            elif st == "preliminary_filing":
                dd = date(2026, 3, random.randint(1, 28)).isoformat()
            elif st == "final_reconciliation":
                dd = date(2026, 12, random.randint(1, 28)).isoformat()
            desc = f"{jur} {st.replace('_', ' ').title()} deadline"
            deadlines.append((did, jur, st, dd, desc))
    cur.executemany(
        "INSERT INTO regulatory_deadlines VALUES (?,?,?,?,?)", deadlines
    )

    conn.commit()
    conn.close()

    # ═══════════════════ WORKSPACE FILES ═══════════════════

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    all_portfolio_ids = [
        r["portfolio_id"]
        for r in cur.execute("SELECT portfolio_id FROM portfolios").fetchall()
    ]
    all_contract_ids = [
        r["contract_id"]
        for r in cur.execute("SELECT contract_id FROM purchase_contracts").fetchall()
    ]
    all_injection_ids = [
        r["injection_id"]
        for r in cur.execute("SELECT injection_id FROM grid_injections").fetchall()
    ]
    all_cert_ids = [
        r["cert_id"]
        for r in cur.execute("SELECT cert_id FROM certificates").fetchall()
    ]

    files_per_type = num_ws // 4  # 2 at v0

    # ── 1-2: portfolio_adjustments_batch_{n}.csv ──
    adj_pids = random.sample(all_portfolio_ids, k=int(len(all_portfolio_ids) * 0.8))
    random.shuffle(adj_pids)
    notes_choices = [
        "Regulatory update",
        "Target revision per board decision",
        "Load forecast adjustment",
        "Voluntary increase",
        "Reduced obligation per settlement",
    ]
    adj_records = []
    for pid in adj_pids:
        adj_records.append({
            "portfolio_id": pid,
            "adjustment_factor": round(random.uniform(0.8, 1.3), 4),
            "notes": random.choice(notes_choices),
        })
    adj_df = pd.DataFrame(adj_records)
    chunk_size = max(1, len(adj_df) // files_per_type)
    for fi in range(files_per_type):
        start = fi * chunk_size
        end = len(adj_df) if fi == files_per_type - 1 else (fi + 1) * chunk_size
        fpath = os.path.join(args.workspace, f"portfolio_adjustments_batch_{fi + 1}.csv")
        adj_df.iloc[start:end].to_csv(fpath, index=False)

    # ── 3-4: contract_amendments_{n}.txt ──
    amend_cids = random.sample(all_contract_ids, k=int(len(all_contract_ids) * 0.3))
    random.shuffle(amend_cids)
    chunk_size = max(1, len(amend_cids) // files_per_type)
    for fi in range(files_per_type):
        start = fi * chunk_size
        end = len(amend_cids) if fi == files_per_type - 1 else (fi + 1) * chunk_size
        chunk = amend_cids[start:end]
        fpath = os.path.join(args.workspace, f"contract_amendments_{fi + 1}.txt")
        with open(fpath, "w") as f:
            for j, cid in enumerate(chunk):
                amended_mwh = round(random.uniform(0, 180), 1)
                eff_date = date(
                    2026, random.randint(1, 4), random.randint(1, 28)
                ).isoformat()
                reason = random.choice([
                    "Partial delivery renegotiation",
                    "Contract cancelled",
                    "Volume increase amendment",
                    "Price and volume adjustment",
                    "Force majeure settlement",
                ])
                f.write("CONTRACT_AMENDMENT\n")
                f.write(f"Contract ID: {cid}\n")
                f.write(f"Amended MWh: {amended_mwh}\n")
                f.write(f"Effective Date: {eff_date}\n")
                f.write(f"Reason: {reason}\n")
                if j < len(chunk) - 1:
                    f.write("---\n")

    # ── 5-6: injection_overrides_{n}.json ──
    override_iids = random.sample(
        all_injection_ids, k=int(len(all_injection_ids) * 0.2)
    )
    random.shuffle(override_iids)
    chunk_size = max(1, len(override_iids) // files_per_type)
    for fi in range(files_per_type):
        start = fi * chunk_size
        end = len(override_iids) if fi == files_per_type - 1 else (fi + 1) * chunk_size
        chunk = override_iids[start:end]
        fpath = os.path.join(args.workspace, f"injection_overrides_{fi + 1}.json")
        overrides = []
        for iid in chunk:
            overrides.append({
                "injection_id": iid,
                "verified_override": random.choice([True, False]),
                "reason": random.choice([
                    "Meter recalibration",
                    "Audit correction",
                    "Verification dispute resolved",
                    "Manual inspection override",
                ]),
            })
        with open(fpath, "w") as f:
            json.dump(overrides, f, indent=2)

    # ── 7-8: cert_updates_{n}.yaml ──
    update_cids = random.sample(all_cert_ids, k=int(len(all_cert_ids) * 0.15))
    random.shuffle(update_cids)
    chunk_size = max(1, len(update_cids) // files_per_type)
    for fi in range(files_per_type):
        start = fi * chunk_size
        end = len(update_cids) if fi == files_per_type - 1 else (fi + 1) * chunk_size
        chunk = update_cids[start:end]
        fpath = os.path.join(args.workspace, f"cert_updates_{fi + 1}.yaml")
        with open(fpath, "w") as f:
            for cid in chunk:
                new_status = random.choice(["retired", "active"])
                reason = random.choice([
                    "Annual audit reclassification",
                    "Ownership transfer completed",
                    "Verification review passed",
                    "Expiration reversal",
                    "Administrative correction",
                ])
                f.write(f"- cert_id: \"{cid}\"\n")
                f.write(f"  updated_status: \"{new_status}\"\n")
                f.write(f"  reason: \"{reason}\"\n")

    # ── Fixed config files ──
    config = {
        "eligible_vintage_years": [2024, 2025, 2026],
        "reference_date": "2026-04-20",
        "minimum_shortfall_threshold_mwh": 0.5,
    }
    with open(os.path.join(args.workspace, "compliance_config.json"), "w") as f:
        json.dump(config, f, indent=2)

    with open(
        os.path.join(args.workspace, "technology_multipliers.csv"), "w", newline=""
    ) as f:
        writer = csv.writer(f)
        writer.writerow(["tech_type", "credit_multiplier"])
        for tt, mult in TECHNOLOGY_MULTIPLIERS.items():
            writer.writerow([tt, mult])

    with open(os.path.join(args.workspace, "penalty_schedule.yaml"), "w") as f:
        for jur, info in PENALTY_SCHEDULE.items():
            f.write(f"{jur}:\n")
            f.write(f"  penalty_rate_per_mwh: {info['penalty_rate_per_mwh']}\n")
            f.write(f"  grace_period_days: {info['grace_period_days']}\n")

    conn.close()
    print(f"Generated DB at {args.db_path} and workspace at {args.workspace}")


if __name__ == "__main__":
    main()
