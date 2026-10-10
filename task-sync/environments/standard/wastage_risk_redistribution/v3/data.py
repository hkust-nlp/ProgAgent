#!/usr/bin/env python3
"""Data generation for blood-bank wastage-risk redistribution task."""

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

# ── Scale parameters (v0 base) ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 640,      # v3 = 8× base
    "num_workspace_files": 32,  # v3 = base + 3N  (N=8)
}

# ── Deterministic seeding ────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ── Domain constants ─────────────────────────────────────────────────────────
BLOOD_TYPES = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
COMPONENT_TYPES = ["Red Blood Cells", "Platelets", "Plasma", "Cryoprecipitate"]
UNIT_STATUSES = ["available", "reserved", "quarantine"]
TRANSFER_STATUSES = ["pending", "approved", "in_transit", "completed", "rejected"]
SHELF_LIFE = {
    "Red Blood Cells": 42,
    "Platelets": 5,
    "Plasma": 365,
    "Cryoprecipitate": 365,
}
URGENCY_LEVELS = ["routine", "urgent", "emergency"]

TODAY = datetime(2026, 4, 22)


def _create_tables(cur: sqlite3.Cursor):
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS blood_banks (
        bank_id       TEXT PRIMARY KEY,
        bank_name     TEXT NOT NULL,
        city          TEXT NOT NULL,
        region        TEXT NOT NULL,
        capacity      INTEGER NOT NULL,
        contact_email TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS blood_units (
        unit_id         TEXT PRIMARY KEY,
        bank_id         TEXT NOT NULL,
        blood_type      TEXT NOT NULL,
        component_type  TEXT NOT NULL,
        collection_date TEXT NOT NULL,
        expiration_date TEXT NOT NULL,
        volume_ml       INTEGER NOT NULL,
        status          TEXT NOT NULL,
        donor_id        TEXT NOT NULL,
        FOREIGN KEY (bank_id) REFERENCES blood_banks(bank_id)
    );
    CREATE TABLE IF NOT EXISTS hospital_contracts (
        contract_id     TEXT PRIMARY KEY,
        hospital_name   TEXT NOT NULL,
        bank_id         TEXT NOT NULL,
        blood_type      TEXT NOT NULL,
        component_type  TEXT NOT NULL,
        weekly_demand   INTEGER NOT NULL,
        priority_tier   INTEGER NOT NULL,
        contract_start  TEXT NOT NULL,
        contract_end    TEXT NOT NULL,
        FOREIGN KEY (bank_id) REFERENCES blood_banks(bank_id)
    );
    CREATE TABLE IF NOT EXISTS transfer_requests (
        request_id      TEXT PRIMARY KEY,
        source_bank_id  TEXT NOT NULL,
        dest_bank_id    TEXT NOT NULL,
        blood_type      TEXT NOT NULL,
        component_type  TEXT NOT NULL,
        units_requested INTEGER NOT NULL,
        urgency         TEXT NOT NULL,
        status          TEXT NOT NULL,
        request_date    TEXT NOT NULL,
        resolution_date TEXT,
        FOREIGN KEY (source_bank_id) REFERENCES blood_banks(bank_id),
        FOREIGN KEY (dest_bank_id)   REFERENCES blood_banks(bank_id)
    );
    """)


def _gen_banks(cur: sqlite3.Cursor, n_rows: int):
    """Generate blood banks.  Number of banks scales gently with rows."""
    n_banks = max(5, n_rows // 16)
    regions = ["North", "South", "East", "West", "Central"]
    banks = []
    for i in range(n_banks):
        bid = f"BB-{i+1:04d}"
        banks.append((
            bid,
            f"{fake.city()} Blood Center",
            fake.city(),
            regions[i % len(regions)],
            random.randint(200, 800),
            fake.email(),
        ))
    cur.executemany(
        "INSERT INTO blood_banks VALUES (?,?,?,?,?,?)", banks
    )
    return [b[0] for b in banks]


def _gen_units(cur: sqlite3.Cursor, bank_ids: list, n_rows: int):
    units = []
    for i in range(n_rows):
        comp = random.choice(COMPONENT_TYPES)
        shelf = SHELF_LIFE[comp]
        # Bias toward near-expiry for realism: 40 % within 7 days
        if random.random() < 0.40:
            days_left = random.randint(0, 7)
        else:
            days_left = random.randint(1, shelf)
        exp_date = TODAY + timedelta(days=days_left)
        col_date = exp_date - timedelta(days=shelf)
        units.append((
            f"U-{i+1:06d}",
            random.choice(bank_ids),
            random.choice(BLOOD_TYPES),
            comp,
            col_date.strftime("%Y-%m-%d"),
            exp_date.strftime("%Y-%m-%d"),
            random.choice([250, 300, 350, 450]),
            random.choice(UNIT_STATUSES),
            f"D-{random.randint(1000,9999)}",
        ))
    cur.executemany("INSERT INTO blood_units VALUES (?,?,?,?,?,?,?,?,?)", units)
    return units


def _gen_contracts(cur: sqlite3.Cursor, bank_ids: list, n_rows: int):
    contracts = []
    for i in range(n_rows):
        start = TODAY - timedelta(days=random.randint(30, 365))
        end = start + timedelta(days=random.randint(180, 730))
        contracts.append((
            f"C-{i+1:05d}",
            f"{fake.company()} Hospital",
            random.choice(bank_ids),
            random.choice(BLOOD_TYPES),
            random.choice(COMPONENT_TYPES),
            random.randint(2, 30),
            random.randint(1, 3),
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        ))
    cur.executemany(
        "INSERT INTO hospital_contracts VALUES (?,?,?,?,?,?,?,?,?)", contracts
    )
    return contracts


def _gen_transfers(cur: sqlite3.Cursor, bank_ids: list, n_rows: int):
    transfers = []
    for i in range(n_rows):
        src = random.choice(bank_ids)
        dst = random.choice([b for b in bank_ids if b != src])
        req_date = TODAY - timedelta(days=random.randint(0, 30))
        status = random.choice(TRANSFER_STATUSES)
        res_date = (req_date + timedelta(days=random.randint(1, 5))).strftime("%Y-%m-%d") if status in ("completed", "rejected") else None
        transfers.append((
            f"TR-{i+1:05d}",
            src, dst,
            random.choice(BLOOD_TYPES),
            random.choice(COMPONENT_TYPES),
            random.randint(1, 15),
            random.choice(URGENCY_LEVELS),
            status,
            req_date.strftime("%Y-%m-%d"),
            res_date,
        ))
    cur.executemany(
        "INSERT INTO transfer_requests VALUES (?,?,?,?,?,?,?,?,?,?)", transfers
    )
    return transfers


# ── Workspace generation ─────────────────────────────────────────────────────

def _write_inventory_snapshots(workspace: str, units: list, bank_ids: list,
                               n_files: int):
    """Write per-bank daily inventory CSV snapshots (scalable files)."""
    snap_dir = os.path.join(workspace, "inventory_snapshots")
    os.makedirs(snap_dir, exist_ok=True)

    # Distribute files across banks round-robin; each file is a daily snapshot
    for idx in range(n_files):
        bank = bank_ids[idx % len(bank_ids)]
        day_offset = idx // len(bank_ids)
        snap_date = (TODAY - timedelta(days=day_offset)).strftime("%Y-%m-%d")
        bank_units = [u for u in units if u[1] == bank]
        rows = []
        for u in bank_units:
            rows.append({
                "unit_id": u[0],
                "blood_type": u[2],
                "component_type": u[3],
                "expiration_date": u[5],
                "volume_ml": u[6],
                "status": u[7],
                "snapshot_date": snap_date,
            })
        df = pd.DataFrame(rows)
        fname = f"snapshot_{bank}_{snap_date}.csv"
        df.to_csv(os.path.join(snap_dir, fname), index=False)


def _write_demand_forecast_files(workspace: str, contracts: list,
                                 bank_ids: list, n_extra_files: int):
    """Write demand forecast JSON files (scalable)."""
    forecast_dir = os.path.join(workspace, "demand_forecasts")
    os.makedirs(forecast_dir, exist_ok=True)

    # Group contracts by bank
    bank_contracts = {b: [] for b in bank_ids}
    for c in contracts:
        bank_contracts[c[2]].append(c)

    # Base files: one per bank
    file_count = 0
    for bank in bank_ids:
        forecast = {}
        for c in bank_contracts[bank]:
            key = f"{c[3]}|{c[4]}"
            if key not in forecast:
                forecast[key] = {"blood_type": c[3], "component_type": c[4],
                                 "total_weekly_demand": 0,
                                 "max_priority_tier": 3}
            forecast[key]["total_weekly_demand"] += c[5]
            forecast[key]["max_priority_tier"] = min(
                forecast[key]["max_priority_tier"], c[6])
        out = {
            "bank_id": bank,
            "forecast_date": TODAY.strftime("%Y-%m-%d"),
            "items": list(forecast.values()),
        }
        with open(os.path.join(forecast_dir, f"forecast_{bank}.json"), "w") as f:
            json.dump(out, f, indent=2)
        file_count += 1

    # Additional forecast files for scaling
    for extra in range(n_extra_files):
        bank = bank_ids[extra % len(bank_ids)]
        future_date = (TODAY + timedelta(days=7 * (extra + 1))).strftime("%Y-%m-%d")
        # Slightly perturbed demand
        items = []
        for c in bank_contracts[bank]:
            items.append({
                "blood_type": c[3],
                "component_type": c[4],
                "projected_weekly_demand": max(1, c[5] + random.randint(-3, 3)),
                "priority_tier": c[6],
            })
        out = {"bank_id": bank, "forecast_date": future_date, "items": items}
        with open(os.path.join(forecast_dir,
                               f"forecast_{bank}_{future_date}.json"), "w") as f:
            json.dump(out, f, indent=2)


def _write_transfer_logs(workspace: str, transfers: list, n_files: int):
    """Write transfer-request log TXT files (scalable)."""
    log_dir = os.path.join(workspace, "transfer_logs")
    os.makedirs(log_dir, exist_ok=True)

    chunk_size = max(1, len(transfers) // n_files)
    for idx in range(n_files):
        chunk = transfers[idx * chunk_size: (idx + 1) * chunk_size]
        if not chunk:
            chunk = transfers[-1:]
        lines = []
        for t in chunk:
            line = (f"[{t[8]}] Request {t[0]}: {t[1]} -> {t[2]} | "
                    f"{t[5]} units of {t[3]} {t[4]} | "
                    f"urgency={t[6]} status={t[7]}")
            if t[9]:
                line += f" resolved={t[9]}"
            lines.append(line)
        fname = f"transfer_log_batch_{idx+1:03d}.txt"
        with open(os.path.join(log_dir, fname), "w") as f:
            f.write("\n".join(lines) + "\n")


# ── Fixed policy / config files (do NOT count toward SCALE files) ────────────

def _write_wastage_policy(workspace: str):
    """YAML config with thresholds that drive the risk-scoring model."""
    policy = {
        "wastage_risk_policy": {
            "risk_horizon_days": 7,
            "risk_scoring": {
                "days_to_expiry_weight": 0.40,
                "surplus_ratio_weight": 0.35,
                "transfer_activity_weight": 0.25,
            },
            "days_to_expiry_brackets": [
                {"max_days": 2, "score": 10},
                {"max_days": 4, "score": 7},
                {"max_days": 7, "score": 4},
            ],
            "surplus_ratio_thresholds": {
                "description": "surplus_ratio = available_units / weekly_demand. If weekly_demand is 0, treat ratio as 999.",
                "brackets": [
                    {"min_ratio": 5.0, "score": 10},
                    {"min_ratio": 3.0, "score": 7},
                    {"min_ratio": 1.5, "score": 4},
                    {"min_ratio": 0.0, "score": 1},
                ],
            },
            "transfer_activity_scoring": {
                "description": "Count pending or in_transit outbound transfers for this bank+blood_type+component. If count >= 2 reduce score by 3 (floor 0); if count == 1 reduce by 1.",
                "active_statuses": ["pending", "in_transit"],
            },
            "minimum_risk_score_for_redistribution": 8,
            "redistribution_priority_order": "descending risk_score, then ascending unit_id for ties",
        }
    }
    with open(os.path.join(workspace, "wastage_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)


def _write_component_handling_rules(workspace: str):
    """Markdown rules document — fixed across scales."""
    content = """# Component Handling Rules

## Platelets Special Handling

Platelets have a shelf life of only 5 days. Any platelet unit with 2 or fewer
days remaining must be flagged regardless of demand calculations. These units
receive an automatic risk score bonus of +3 on top of the computed score.

## Quarantine Exclusion

Units currently in quarantine status must be excluded entirely from wastage
risk analysis and redistribution lists. They are not considered available
inventory.

## Reserved Units

Reserved units should still be evaluated for wastage risk — a reservation
does not guarantee the unit will be used before expiry. However, reserved
units receive a risk score reduction of 2 (floor at 0) since they have a
pending allocation.

## Redistribution Output Requirements

The final redistribution list must be saved as `redistribution_list.csv` with
the following columns in order: unit_id, bank_id, blood_type, component_type,
expiration_date, days_to_expiry, risk_score, suggested_recipient_bank.

The suggested recipient bank is the bank with the highest unmet weekly demand
for that blood_type and component_type combination (demand minus current
available inventory). If no bank has positive unmet demand, use "DISCARD" as
the suggested recipient.

All numeric values should be integers. Days to expiry is calculated from
2026-04-22 (today).
"""
    with open(os.path.join(workspace, "component_handling_rules.md"), "w") as f:
        f.write(content)


def _write_bank_region_config(workspace: str, bank_ids: list, cur: sqlite3.Cursor):
    """JSON config mapping banks to transfer-eligible partners."""
    cur.execute("SELECT bank_id, region FROM blood_banks")
    bank_regions = {row[0]: row[1] for row in cur.fetchall()}

    # Banks can transfer to any bank in the same or adjacent region
    adjacency = {
        "North": ["North", "Central", "East"],
        "South": ["South", "Central", "West"],
        "East": ["East", "North", "Central"],
        "West": ["West", "South", "Central"],
        "Central": ["North", "South", "East", "West", "Central"],
    }
    config = {}
    for bid in bank_ids:
        region = bank_regions[bid]
        eligible = [b for b in bank_ids
                    if bank_regions[b] in adjacency[region] and b != bid]
        config[bid] = {
            "region": region,
            "eligible_recipients": eligible,
        }
    with open(os.path.join(workspace, "bank_transfer_eligibility.json"), "w") as f:
        json.dump(config, f, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_data_files = SCALE["num_workspace_files"]

    # ── Database ──────────────────────────────────────────────────────────
    conn = sqlite3.connect(args.db_path)
    cur = conn.cursor()
    _create_tables(cur)

    bank_ids = _gen_banks(cur, n_rows)
    units = _gen_units(cur, bank_ids, n_rows)
    contracts = _gen_contracts(cur, bank_ids, n_rows)
    transfers = _gen_transfers(cur, bank_ids, n_rows)
    conn.commit()

    # ── Workspace — scalable data files ───────────────────────────────────
    # Split n_data_files across three scalable categories
    n_snap = max(1, n_data_files // 3)
    n_forecast_extra = max(1, n_data_files // 3)
    n_tlog = max(1, n_data_files - n_snap - n_forecast_extra)

    _write_inventory_snapshots(args.workspace, units, bank_ids, n_snap)
    _write_demand_forecast_files(args.workspace, contracts, bank_ids,
                                 n_forecast_extra)
    _write_transfer_logs(args.workspace, transfers, n_tlog)

    # ── Workspace — fixed policy / config files ───────────────────────────
    _write_wastage_policy(args.workspace)
    _write_component_handling_rules(args.workspace)
    _write_bank_region_config(args.workspace, bank_ids, cur)

    conn.close()
    print(f"Data generated: {n_rows} rows/table, {len(bank_ids)} banks, "
          f"{n_data_files} scalable files + 3 fixed files.")


if __name__ == "__main__":
    main()
