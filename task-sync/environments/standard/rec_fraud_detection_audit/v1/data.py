import argparse
import os
import sqlite3
import json
import yaml
import csv
import random
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta, date
from collections import defaultdict

SCALE = {
    "rows_per_table": 160,
    "num_workspace_files": 20,
}

ENERGY_TYPES = ["solar", "wind", "hydro", "biomass", "geothermal"]
CERTIFYING_BODIES = ["NARR", "GreenTrack", "REC Verify", "EcoStandard"]
INDUSTRY_SECTORS = [
    "Technology", "Manufacturing", "Retail", "Finance", "Healthcare",
    "Education", "Energy", "Transportation", "Agriculture", "Real Estate",
]
SUSTAINABILITY_TIERS = ["gold", "silver", "bronze"]

BASE_PRICES = {
    "solar": 35.0,
    "wind": 40.0,
    "hydro": 45.0,
    "biomass": 55.0,
    "geothermal": 60.0,
}
PRICE_STD = {
    "solar": 5.0,
    "wind": 6.0,
    "hydro": 5.5,
    "biomass": 7.0,
    "geothermal": 6.5,
}

VINTAGE_MONTHS = ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06"]


def _month_end(year, month):
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def main(db_path, workspace):
    fake = Faker()
    Faker.seed(42)
    random.seed(42)
    np.random.seed(42)

    os.makedirs(workspace, exist_ok=True)

    rows = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ── Create tables ──────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS generators (
            generator_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            energy_type TEXT NOT NULL,
            capacity_mw REAL NOT NULL,
            location_state TEXT NOT NULL,
            commissioned_date TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accreditation_certificates (
            cert_id TEXT PRIMARY KEY,
            generator_id TEXT NOT NULL,
            issue_date TEXT NOT NULL,
            expiry_date TEXT NOT NULL,
            certifying_body TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (generator_id) REFERENCES generators(generator_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS buyers (
            buyer_id TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            industry_sector TEXT NOT NULL,
            sustainability_tier TEXT NOT NULL,
            registered_date TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rec_transactions (
            transaction_id TEXT PRIMARY KEY,
            rec_serial TEXT NOT NULL UNIQUE,
            generator_id TEXT NOT NULL,
            buyer_id TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            trade_time TEXT NOT NULL,
            quantity_mwh REAL NOT NULL,
            price_per_mwh REAL NOT NULL,
            energy_type TEXT NOT NULL,
            vintage_month TEXT NOT NULL,
            FOREIGN KEY (generator_id) REFERENCES generators(generator_id),
            FOREIGN KEY (buyer_id) REFERENCES buyers(buyer_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS meter_readings (
            reading_id TEXT PRIMARY KEY,
            generator_id TEXT NOT NULL,
            month TEXT NOT NULL,
            total_generation_mwh REAL NOT NULL,
            peak_output_mw REAL NOT NULL,
            reading_date TEXT NOT NULL,
            FOREIGN KEY (generator_id) REFERENCES generators(generator_id)
        )
    """)

    # ── 1. Generators ──────────────────────────────────────────────
    generators = []
    for i in range(rows):
        gen_id = f"GEN-{i:04d}"
        name = (fake.company() + " "
                + random.choice(["Power", "Energy", "Renewables", "Generation"]))
        energy_type = random.choice(ENERGY_TYPES)
        capacity_mw = round(random.uniform(5, 200), 1)
        state = fake.state_abbr()
        commissioned = fake.date_between(
            start_date=date(2015, 1, 1), end_date=date(2023, 12, 31)
        ).isoformat()
        generators.append((gen_id, name, energy_type, capacity_mw, state, commissioned))
    cur.executemany("INSERT INTO generators VALUES (?,?,?,?,?,?)", generators)
    gen_energy = {g[0]: g[2] for g in generators}
    gen_cap = {g[0]: g[3] for g in generators}

    # ── 2. Accreditation certificates ──────────────────────────────
    num_expired = max(int(rows * 0.10), 4)
    expired_gen_indices = set(sorted(random.sample(range(rows), num_expired)))

    certs = []
    for i in range(rows):
        cert_id = f"CERT-{i:04d}"
        gen_id = f"GEN-{i:04d}"
        if i in expired_gen_indices:
            issue_date = fake.date_between(
                start_date=date(2019, 1, 1), end_date=date(2022, 6, 30))
            expiry_date = fake.date_between(
                start_date=date(2023, 6, 1), end_date=date(2024, 12, 15))
            status = random.choice(["expired", "suspended", "revoked"])
        else:
            issue_date = fake.date_between(
                start_date=date(2022, 1, 1), end_date=date(2024, 6, 30))
            expiry_date = fake.date_between(
                start_date=date(2026, 1, 1), end_date=date(2028, 12, 31))
            status = "active"
        certifying_body = random.choice(CERTIFYING_BODIES)
        certs.append((cert_id, gen_id, issue_date.isoformat(),
                       expiry_date.isoformat(), certifying_body, status))
    cur.executemany(
        "INSERT INTO accreditation_certificates VALUES (?,?,?,?,?,?)", certs)

    expired_gen_ids = {f"GEN-{i:04d}" for i in expired_gen_indices}

    # ── 3. Buyers ──────────────────────────────────────────────────
    buyers = []
    for i in range(rows):
        buyer_id = f"BUY-{i:04d}"
        company = fake.company()
        sector = random.choice(INDUSTRY_SECTORS)
        tier = random.choice(SUSTAINABILITY_TIERS)
        reg_date = fake.date_between(
            start_date=date(2018, 1, 1), end_date=date(2024, 12, 31)
        ).isoformat()
        buyers.append((buyer_id, company, sector, tier, reg_date))
    cur.executemany("INSERT INTO buyers VALUES (?,?,?,?,?)", buyers)

    # ── 4. Prepare transaction skeletons ───────────────────────────
    num_active_gen = min(rows, max(rows // 2, 30))
    active_gen_ids = [f"GEN-{i:04d}"
                      for i in sorted(random.sample(range(rows), num_active_gen))]
    num_active_buy = min(rows, max(rows // 3, 20))
    active_buyer_ids = [f"BUY-{i:04d}"
                        for i in sorted(random.sample(range(rows), num_active_buy))]

    num_off_hours = max(int(rows * 0.06), 3)
    off_hours_set = set(random.sample(range(rows), num_off_hours))

    num_price_outlier = max(int(rows * 0.06), 3)
    remaining_idx = [i for i in range(rows) if i not in off_hours_set]
    price_outlier_set = set(random.sample(
        remaining_idx, min(num_price_outlier, len(remaining_idx))))

    txn_skeletons = []
    for i in range(rows):
        gen_id = random.choice(active_gen_ids)
        buyer_id = random.choice(active_buyer_ids)
        energy_type = gen_energy[gen_id]
        vintage_month = random.choice(VINTAGE_MONTHS)
        y, m = map(int, vintage_month.split("-"))
        month_start = date(y, m, 1)
        month_end_dt = _month_end(y, m)
        trade_date = fake.date_between(
            start_date=month_start,
            end_date=min(month_end_dt + timedelta(days=30), date(2025, 7, 31)),
        )
        if i in off_hours_set:
            hour = random.choice(
                [random.randint(0, 5), random.randint(22, 23)])
        else:
            hour = random.randint(6, 21)
        minute = random.randint(0, 59)
        trade_time = f"{hour:02d}:{minute:02d}:00"
        quantity = round(random.uniform(10, 500), 2)
        rec_serial = f"REC-{vintage_month.replace('-', '')}-{i:05d}"
        txn_skeletons.append({
            "idx": i,
            "txn_id": f"TXN-{i:05d}",
            "rec_serial": rec_serial,
            "gen_id": gen_id,
            "buyer_id": buyer_id,
            "trade_date": trade_date,
            "trade_time": trade_time,
            "quantity": quantity,
            "energy_type": energy_type,
            "vintage_month": vintage_month,
        })

    # ── 5. Reference prices (for workspace + transaction pricing) ─
    all_trade_dates = sorted({s["trade_date"] for s in txn_skeletons})
    ref_prices = {}
    price_records = []
    for d in all_trade_dates:
        for et in ENERGY_TYPES:
            rp = round(BASE_PRICES[et] + random.gauss(0, PRICE_STD[et] * 0.3), 2)
            rs = round(PRICE_STD[et] * random.uniform(0.8, 1.2), 2)
            ref_prices[(d.isoformat(), et)] = (rp, rs)
            price_records.append({
                "date": d.isoformat(),
                "energy_type": et,
                "reference_price": rp,
                "reference_std": rs,
            })

    # ── 6. Finalize transaction prices ─────────────────────────────
    transactions = []
    for s in txn_skeletons:
        rp, rs = ref_prices[(s["trade_date"].isoformat(), s["energy_type"])]
        if s["idx"] in price_outlier_set:
            direction = random.choice([-1, 1])
            price = round(rp + direction * rs * random.uniform(3.2, 5.5), 2)
        else:
            price = round(rp + random.gauss(0, rs * 0.3), 2)
        transactions.append((
            s["txn_id"], s["rec_serial"], s["gen_id"], s["buyer_id"],
            s["trade_date"].isoformat(), s["trade_time"], s["quantity"],
            price, s["energy_type"], s["vintage_month"],
        ))
    cur.executemany(
        "INSERT INTO rec_transactions VALUES (?,?,?,?,?,?,?,?,?,?)", transactions)

    # ── 7. Meter readings ─────────────────────────────────────────
    gen_month_qty = defaultdict(float)
    for t in transactions:
        gen_month_qty[(t[2], t[9])] += t[6]

    num_over_gen = max(int(len(gen_month_qty) * 0.08), 3)
    gm_keys = list(gen_month_qty.keys())
    over_gen_keys = set(random.sample(gm_keys, min(num_over_gen, len(gm_keys))))

    meter_readings = []
    existing_gm = set()
    reading_idx = 0

    for (gen_id, month_str), total_qty in gen_month_qty.items():
        y, m = map(int, month_str.split("-"))
        if (gen_id, month_str) in over_gen_keys:
            total_gen = round(total_qty * random.uniform(0.4, 0.9), 2)
        else:
            total_gen = round(total_qty * random.uniform(1.3, 3.0), 2)
        peak = round(min(gen_cap.get(gen_id, 100),
                         random.uniform(10, 150)), 2)
        reading_date = _month_end(y, m).isoformat()
        meter_readings.append((
            f"MTR-{reading_idx:05d}", gen_id, month_str,
            total_gen, peak, reading_date,
        ))
        existing_gm.add((gen_id, month_str))
        reading_idx += 1

    all_gen_ids = [g[0] for g in generators]
    fill_attempts = 0
    while reading_idx < rows and fill_attempts < rows * 5:
        fill_attempts += 1
        gen_id = all_gen_ids[fill_attempts % len(all_gen_ids)]
        month_str = VINTAGE_MONTHS[fill_attempts % len(VINTAGE_MONTHS)]
        if (gen_id, month_str) in existing_gm:
            continue
        total_gen = round(random.uniform(200, 5000), 2)
        y, m = map(int, month_str.split("-"))
        peak = round(min(gen_cap.get(gen_id, 100),
                         random.uniform(10, 150)), 2)
        reading_date = _month_end(y, m).isoformat()
        meter_readings.append((
            f"MTR-{reading_idx:05d}", gen_id, month_str,
            total_gen, peak, reading_date,
        ))
        existing_gm.add((gen_id, month_str))
        reading_idx += 1

    cur.executemany(
        "INSERT INTO meter_readings VALUES (?,?,?,?,?,?)", meter_readings)
    conn.commit()
    conn.close()

    # ================================================================
    #  WORKSPACE FILES
    # ================================================================

    # ── Fixed config files ─────────────────────────────────────────
    trading_rules = {
        "allowed_trading_hours": {"start": "06:00", "end": "22:00"},
        "timezone": "UTC",
        "max_daily_volume_mwh": 5000,
        "settlement_currency": "USD",
    }
    with open(os.path.join(workspace, "trading_rules.json"), "w") as f:
        json.dump(trading_rules, f, indent=2)

    thresholds = {
        "over_generation_tolerance": 1.05,
        "price_outlier_std_multiplier": 2.5,
        "severity_levels": {
            "EXPIRED_CERT": "HIGH",
            "OVER_GENERATION": "HIGH",
            "OFF_HOURS": "MEDIUM",
            "PRICE_OUTLIER": "MEDIUM",
            "FAILED_VALIDATION": "HIGH",
            "DOUBLE_COUNT": "HIGH",
        },
    }
    with open(os.path.join(workspace, "anomaly_thresholds.yaml"), "w") as f:
        yaml.dump(thresholds, f, default_flow_style=False)

    with open(os.path.join(workspace, "certification_standards.md"), "w") as f:
        f.write(
            "# REC Certification Standards\n\n"
            "A Renewable Energy Certificate transaction is considered valid only "
            "when the originating generator holds an accreditation certificate "
            "that is both unexpired and carries an active status at the time of "
            "the trade. Certificates whose status is expired, suspended, or "
            "revoked invalidate any REC transactions dated on or after the "
            "expiry date or status change.\n\n"
            "When evaluating certificate validity for a transaction, the trade "
            "date must fall on or before the certificate expiry date, AND the "
            "certificate status must be exactly 'active'. A transaction where "
            "either condition fails should be flagged as an EXPIRED_CERT "
            "anomaly.\n"
        )

    # ── Scalable file counts ───────────────────────────────────────
    num_meter_val = max(num_files * 4 // 10, 1)
    num_buyer_claims = max(num_files * 3 // 10, 1)
    num_price_idx = num_files - num_meter_val - num_buyer_claims

    # -- Meter validation reports (CSV) --
    num_failed_val = max(int(len(gm_keys) * 0.08), 3)
    candidates_for_fail = [k for k in gm_keys if k not in over_gen_keys]
    failed_val_keys = set(random.sample(
        candidates_for_fail, min(num_failed_val, len(candidates_for_fail))))

    all_validations = []
    for gm in sorted(existing_gm):
        gen_id, month_str = gm
        if gm in failed_val_keys:
            val_status = "FAIL"
            notes = random.choice([
                "Meter calibration error detected",
                "Data transmission gap identified",
                "Inconsistent readings with backup meter",
                "Sensor malfunction reported",
            ])
        else:
            val_status = random.choice(["PASS"] * 9 + ["WARNING"])
            if val_status == "PASS":
                notes = "No issues"
            else:
                notes = "Minor variance within tolerance"
        all_validations.append({
            "generator_id": gen_id,
            "month": month_str,
            "validation_status": val_status,
            "inspector_id": f"INS-{random.randint(100, 999)}",
            "notes": notes,
        })

    val_per_file = math.ceil(len(all_validations) / num_meter_val)
    for fidx in range(num_meter_val):
        batch = all_validations[fidx * val_per_file:(fidx + 1) * val_per_file]
        fp = os.path.join(workspace,
                          f"meter_validation_batch_{fidx + 1:03d}.csv")
        with open(fp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "generator_id", "month", "validation_status",
                "inspector_id", "notes",
            ])
            w.writeheader()
            w.writerows(batch)

    # -- Buyer sustainability claims (YAML) --
    buyer_claims_map = defaultdict(list)
    for t in transactions:
        buyer_claims_map[t[3]].append(t[1])

    num_double = max(int(rows * 0.05), 3)
    all_serials = [t[1] for t in transactions]
    double_serials = random.sample(all_serials, min(num_double, len(all_serials)))
    serial_to_buyer = {t[1]: t[3] for t in transactions}

    buyer_ids_with_claims = sorted(buyer_claims_map.keys())
    for serial in double_serials:
        orig_buyer = serial_to_buyer[serial]
        others = [b for b in buyer_ids_with_claims if b != orig_buyer]
        if others:
            target = random.choice(others)
            buyer_claims_map[target].append(serial)

    buyer_ids_with_claims = sorted(buyer_claims_map.keys())
    claims_per_file = math.ceil(len(buyer_ids_with_claims) / num_buyer_claims)
    for fidx in range(num_buyer_claims):
        batch_ids = buyer_ids_with_claims[
            fidx * claims_per_file:(fidx + 1) * claims_per_file]
        claims = []
        for bid in batch_ids:
            claims.append({
                "buyer_id": bid,
                "claimed_rec_serials": sorted(set(buyer_claims_map[bid])),
                "reporting_period": "2025-H1",
                "sustainability_goal": random.choice([
                    "100% renewable by 2030",
                    "Carbon neutral operations",
                    "50% renewable energy mix",
                    "Net zero by 2035",
                ]),
            })
        fp = os.path.join(workspace,
                          f"buyer_claims_batch_{fidx + 1:03d}.yaml")
        with open(fp, "w") as f:
            yaml.dump(claims, f, default_flow_style=False)

    # -- Price index files (JSON) --
    recs_per_file = math.ceil(len(price_records) / num_price_idx)
    for fidx in range(num_price_idx):
        batch = price_records[fidx * recs_per_file:(fidx + 1) * recs_per_file]
        fp = os.path.join(workspace, f"price_index_{fidx + 1:03d}.json")
        with open(fp, "w") as f:
            json.dump(batch, f, indent=2)

    total_scalable = num_meter_val + num_buyer_claims + num_price_idx
    print(f"Database created at {db_path}")
    print(f"Workspace initialized at {workspace} "
          f"({total_scalable} scalable + 3 fixed files)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
