import argparse
import json
import os
import random
import sqlite3

import numpy as np
from faker import Faker

SCALE = {
    "num_buildings": 4,
    "tenants_per_building": 5,
    "num_periods": 2,
    "num_workspace_files": 8,
}

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

UTILITY_TYPES = ["electricity", "gas", "water"]
UTILITY_UNITS = {"electricity": "kWh", "gas": "therm", "water": "gallon"}
BILLING_METHODS = ["sub_metered", "pro_rata_sqft", "pro_rata_units", "fixed"]

# Base usage per 1000 sqft per period
USAGE_BASE = {"electricity": 4800.0, "gas": 280.0, "water": 18000.0}

# Tenant and building name components
BLDG_NAMES = [
    "Riverside", "Lakewood", "Summit", "Westview", "Eastgate", "Northpark",
    "Southfield", "Central", "Hillside", "Bayview", "Cedarwood", "Mapleton",
    "Pinecrest", "Oakwood", "Elmwood", "Birchwood", "Aspendale", "Willowbrook",
    "Stonecroft", "Silverleaf", "Goldview", "Rosewood", "Sagebrush", "Juniper",
    "Hawthorne", "Magnolia", "Redwood", "Sequoia", "Cypress", "Maplewood",
    "Fernwood", "Briarwood",
]

COMPANY_SUFFIXES = ["LLC", "Corp", "Inc", "Ltd", "Co"]
BUSINESS_TYPES = [
    "Consulting", "Solutions", "Services", "Group", "Associates", "Partners",
    "Ventures", "Technologies", "Industries", "Enterprises", "Advisory",
    "Resources", "Systems", "Capital", "Agency",
]


def _split(lst, n):
    """Split list into n roughly equal chunks (returns list of lists)."""
    if n <= 0:
        return [lst]
    k, m = divmod(len(lst), n)
    out, idx = [], 0
    for i in range(n):
        size = k + (1 if i < m else 0)
        out.append(lst[idx:idx + size])
        idx += size
    return out


def create_tables(conn):
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS buildings (
        building_id   TEXT PRIMARY KEY,
        building_name TEXT NOT NULL,
        address       TEXT NOT NULL,
        total_sqft    REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS tenants (
        tenant_id    TEXT PRIMARY KEY,
        building_id  TEXT NOT NULL,
        unit_number  TEXT NOT NULL,
        tenant_name  TEXT NOT NULL,
        leased_sqft  REAL NOT NULL,
        FOREIGN KEY (building_id) REFERENCES buildings(building_id)
    );

    CREATE TABLE IF NOT EXISTS lease_utility_clauses (
        clause_id      TEXT PRIMARY KEY,
        tenant_id      TEXT NOT NULL,
        utility_type   TEXT NOT NULL,
        billing_method TEXT NOT NULL,
        fixed_monthly  REAL,
        FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
    );

    CREATE TABLE IF NOT EXISTS tariff_schedules (
        tariff_id      TEXT PRIMARY KEY,
        utility_type   TEXT NOT NULL,
        effective_from TEXT NOT NULL,
        rate_per_unit  REAL NOT NULL,
        unit           TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS billing_history (
        billing_id     TEXT PRIMARY KEY,
        tenant_id      TEXT NOT NULL,
        building_id    TEXT NOT NULL,
        utility_type   TEXT NOT NULL,
        period         TEXT NOT NULL,
        original_billed REAL NOT NULL,
        FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
    );

    CREATE TABLE IF NOT EXISTS ground_truth (
        tenant_id       TEXT NOT NULL,
        building_id     TEXT NOT NULL,
        utility_type    TEXT NOT NULL,
        period          TEXT NOT NULL,
        billing_method  TEXT NOT NULL,
        metered_charge  REAL NOT NULL,
        ca_charge       REAL NOT NULL,
        total_charge    REAL NOT NULL,
        original_billed REAL NOT NULL,
        adjustment      REAL NOT NULL,
        PRIMARY KEY (tenant_id, utility_type, period)
    );
    """)
    conn.commit()


def generate_data(conn, scale):
    num_b = scale["num_buildings"]
    tpb = scale["tenants_per_building"]
    num_periods = scale["num_periods"]
    c = conn.cursor()

    # ── buildings ────────────────────────────────────────────────────────────
    buildings = []
    for i in range(num_b):
        bid = f"BLD-{i + 1:04d}"
        name = f"{BLDG_NAMES[i % len(BLDG_NAMES)]} Plaza"
        addr = f"{random.randint(100, 9999)} {fake.street_name()}"
        sqft = round(random.uniform(12000.0, 60000.0), 0)
        buildings.append((bid, name, addr, sqft))
    c.executemany("INSERT INTO buildings VALUES (?,?,?,?)", buildings)

    # ── tenants ──────────────────────────────────────────────────────────────
    tenants = []
    for bid, _, _, bld_sqft in buildings:
        tenant_area = bld_sqft * 0.88  # 12 % common area
        for j in range(tpb):
            tid = f"TNT-{bid[4:]}-{j + 1:02d}"
            sqft = round(tenant_area / tpb * random.uniform(0.75, 1.25), 0)
            sqft = max(sqft, 300.0)
            btype = random.choice(BUSINESS_TYPES)
            suf = random.choice(COMPANY_SUFFIXES)
            name = f"{fake.last_name()} {btype} {suf}"
            tenants.append((tid, bid, f"Suite {(j + 1) * 100}", name, sqft))
    c.executemany("INSERT INTO tenants VALUES (?,?,?,?,?)", tenants)

    # ── lease utility clauses ────────────────────────────────────────────────
    clauses = []
    clause_idx = 1
    clause_map = {}  # (tid, ut) -> (method, fixed_monthly)
    for tid, bid, _, _, _ in tenants:
        for ut in UTILITY_TYPES:
            method = random.choice(BILLING_METHODS)
            fixed = round(random.uniform(80.0, 600.0), 2) if method == "fixed" else None
            cid = f"CLS-{clause_idx:06d}"
            clauses.append((cid, tid, ut, method, fixed))
            clause_map[(tid, ut)] = (method, fixed)
            clause_idx += 1
    c.executemany("INSERT INTO lease_utility_clauses VALUES (?,?,?,?,?)", clauses)

    # ── tariff schedules ─────────────────────────────────────────────────────
    tariffs = []
    base_rates = {"electricity": 0.135, "gas": 2.10, "water": 0.0082}
    tariff_idx = 1
    # Two rate tiers per utility
    for ut in UTILITY_TYPES:
        for offset in [0, 6]:
            rate = round(base_rates[ut] * random.uniform(0.88, 1.18), 6)
            eff = f"2024-{(1 + offset):02d}-01"
            tid_r = f"TAR-{tariff_idx:04d}"
            tariffs.append((tid_r, ut, eff, rate, UTILITY_UNITS[ut]))
            tariff_idx += 1
    c.executemany("INSERT INTO tariff_schedules VALUES (?,?,?,?,?)", tariffs)

    # ── build rate lookup (period -> utility -> rate) ─────────────────────────
    # periods: e.g. ["2025-01", "2025-02"]
    periods = []
    for k in range(num_periods):
        mo = (1 + k) % 12 or 12
        yr = 2025 + (1 + k) // 13
        periods.append(f"{yr}-{mo:02d}")

    rate_lookup = {}  # (ut, period) -> rate
    for ut in UTILITY_TYPES:
        ut_tariffs = sorted(
            [(t[2], t[3]) for t in tariffs if t[1] == ut],
            key=lambda x: x[0]
        )
        for period in periods:
            period_date = period + "-01"
            applicable = [r for eff, r in ut_tariffs if eff <= period_date]
            rate_lookup[(ut, period)] = applicable[-1] if applicable else ut_tariffs[0][1]

    # ── CA allocation parameters (random per building per utility) ────────────
    # ca_fraction: fraction of master meter reading that is common-area usage
    # allocation_basis: "sqft" or "units" – how CA cost is distributed to tenants
    ca_params = {}  # (bid, ut) -> (ca_fraction, alloc_basis)
    for bid, _, _, _ in buildings:
        for ut in UTILITY_TYPES:
            frac = round(random.uniform(0.05, 0.20), 4)
            basis = random.choice(["sqft", "units"])
            ca_params[(bid, ut)] = (frac, basis)

    # ── master meter usage (per building, utility, period) ───────────────────
    master_usage = {}  # (bid, ut, period) -> usage
    for bid, _, _, bld_sqft in buildings:
        for ut in UTILITY_TYPES:
            for period in periods:
                base = USAGE_BASE[ut] * (bld_sqft / 1000.0)
                usage = round(base * random.uniform(0.82, 1.18), 2)
                master_usage[(bid, ut, period)] = usage

    # ── sub-meter readings (only for sub_metered clauses) ────────────────────
    sub_usage = {}  # (tid, ut, period) -> usage
    for tid, bid, _, _, tsqft in tenants:
        for ut in UTILITY_TYPES:
            method, _ = clause_map[(tid, ut)]
            if method == "sub_metered":
                for period in periods:
                    # Approximate sub-meter usage as proportion of master
                    tpb_ = sum(1 for t in tenants if t[1] == bid)
                    tenant_sqft_total = sum(t[4] for t in tenants if t[1] == bid)
                    frac = tsqft / tenant_sqft_total if tenant_sqft_total > 0 else 1.0 / tpb_
                    ca_frac, _ = ca_params[(bid, ut)]
                    approx = (1.0 - ca_frac) * master_usage[(bid, ut, period)] * frac
                    noise = random.uniform(0.80, 1.20)
                    sub_usage[(tid, ut, period)] = round(approx * noise, 2)

    # ── building helper lookups ──────────────────────────────────────────────
    bld_tenants = {}
    for tid, bid, _, _, tsqft in tenants:
        bld_tenants.setdefault(bid, []).append((tid, tsqft))

    # ── compute ground truth and billing history ─────────────────────────────
    gt_rows = []
    hist_rows = []
    hist_idx = 1

    for tid, bid, _, tname, tsqft in tenants:
        tenant_list = bld_tenants[bid]
        num_t = len(tenant_list)
        total_sqft_bld = sum(s for _, s in tenant_list)

        for ut in UTILITY_TYPES:
            method, fixed_mo = clause_map[(tid, ut)]
            ca_frac, alloc_basis = ca_params[(bid, ut)]

            for period in periods:
                rate = rate_lookup[(ut, period)]
                master = master_usage[(bid, ut, period)]

                # ── metered_charge and ca_charge ────────────────────────────
                if method == "fixed":
                    metered_charge = 0.0
                    ca_charge = 0.0
                    total_charge = fixed_mo

                elif method == "sub_metered":
                    usage = sub_usage.get((tid, ut, period), 0.0)
                    metered_charge = usage * rate
                    # Common-area cost
                    ca_cost = ca_frac * master * rate
                    if alloc_basis == "sqft":
                        ca_share = (tsqft / total_sqft_bld) * ca_cost
                    else:  # "units"
                        ca_share = (1.0 / num_t) * ca_cost
                    ca_charge = ca_share
                    total_charge = metered_charge + ca_charge

                elif method == "pro_rata_sqft":
                    frac = tsqft / total_sqft_bld if total_sqft_bld > 0 else 0.0
                    metered_charge = frac * master * rate
                    ca_charge = 0.0
                    total_charge = metered_charge

                else:  # pro_rata_units
                    frac = 1.0 / num_t if num_t > 0 else 0.0
                    metered_charge = frac * master * rate
                    ca_charge = 0.0
                    total_charge = metered_charge

                # ── original billing (naive equal-split) ────────────────────
                equal_master_cost = master * rate / num_t
                original_billed = round(equal_master_cost, 2)

                adjustment = round(total_charge - original_billed, 2)

                gt_rows.append((
                    tid, bid, ut, period, method,
                    round(metered_charge, 2),
                    round(ca_charge, 2),
                    round(total_charge, 2),
                    original_billed,
                    adjustment,
                ))
                hist_rows.append((
                    f"HIST-{hist_idx:07d}", tid, bid, ut, period, original_billed
                ))
                hist_idx += 1

    c.executemany("INSERT INTO billing_history VALUES (?,?,?,?,?,?)", hist_rows)
    c.executemany("INSERT INTO ground_truth VALUES (?,?,?,?,?,?,?,?,?,?)", gt_rows)
    conn.commit()

    return {
        "buildings": buildings,
        "tenants": tenants,
        "clause_map": clause_map,
        "ca_params": ca_params,
        "master_usage": master_usage,
        "sub_usage": sub_usage,
        "rate_lookup": rate_lookup,
        "periods": periods,
        "tariffs": tariffs,
        "bld_tenants": bld_tenants,
    }


def generate_workspace(workspace, scale, data):
    W = scale["num_workspace_files"]
    buildings = data["buildings"]
    tenants = data["tenants"]
    ca_params = data["ca_params"]
    master_usage = data["master_usage"]
    sub_usage = data["sub_usage"]
    periods = data["periods"]
    tariffs = data["tariffs"]

    # File count distribution:
    # – CA allocation JSONs:  W // 3 files, each covers a batch of buildings
    # – Master meter CSVs:    W // 3 files, each covers a batch of (building, period) rows
    # – Sub-meter CSVs:       remaining files
    n_ca = max(1, W // 3)
    n_master = max(1, W // 3)
    n_sub = max(1, W - n_ca - n_master)

    # ── CA allocation JSONs ───────────────────────────────────────────────────
    bld_list = buildings
    for i, chunk in enumerate(_split(bld_list, n_ca)):
        fname = f"ca_allocation_{i + 1:03d}.json"
        payload = []
        for bid, bname, addr, sqft in chunk:
            allocs = []
            for ut in UTILITY_TYPES:
                frac, basis = ca_params[(bid, ut)]
                allocs.append({
                    "utility_type": ut,
                    "ca_fraction": frac,
                    "allocation_basis": basis,
                })
            payload.append({
                "building_id": bid,
                "building_name": bname,
                "total_sqft": sqft,
                "common_area_allocations": allocs,
            })
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(payload, f, indent=2)

    # ── Master meter CSVs ─────────────────────────────────────────────────────
    all_master_rows = []
    for bid, _, _, _ in buildings:
        for ut in UTILITY_TYPES:
            for period in periods:
                usage = master_usage[(bid, ut, period)]
                all_master_rows.append((bid, ut, period, usage, UTILITY_UNITS[ut]))
    header = "building_id,utility_type,period,total_usage,unit\n"
    for i, chunk in enumerate(_split(all_master_rows, n_master)):
        fname = f"master_meter_{i + 1:03d}.csv"
        lines = [header]
        for row in chunk:
            lines.append(f"{row[0]},{row[1]},{row[2]},{row[3]},{row[4]}\n")
        with open(os.path.join(workspace, fname), "w") as f:
            f.writelines(lines)

    # ── Sub-meter CSVs ────────────────────────────────────────────────────────
    all_sub_rows = []
    for (tid, ut, period), usage in sorted(sub_usage.items()):
        # look up building_id
        bid = next(t[1] for t in tenants if t[0] == tid)
        all_sub_rows.append((tid, bid, ut, period, usage, UTILITY_UNITS[ut]))
    sub_header = "tenant_id,building_id,utility_type,period,usage,unit\n"
    if all_sub_rows:
        for i, chunk in enumerate(_split(all_sub_rows, n_sub)):
            fname = f"sub_meter_{i + 1:03d}.csv"
            lines = [sub_header]
            for row in chunk:
                lines.append(f"{row[0]},{row[1]},{row[2]},{row[3]},{row[4]},{row[5]}\n")
            with open(os.path.join(workspace, fname), "w") as f:
                f.writelines(lines)
    else:
        # Edge case: no sub-metered tenants – write empty files
        for i in range(n_sub):
            with open(os.path.join(workspace, f"sub_meter_{i + 1:03d}.csv"), "w") as f:
                f.write(sub_header)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)
    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    data = generate_data(conn, SCALE)
    generate_workspace(args.workspace, SCALE, data)
    conn.close()


if __name__ == "__main__":
    main()
