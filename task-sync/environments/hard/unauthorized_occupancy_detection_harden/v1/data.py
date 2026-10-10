"""
Data generation for unauthorized subletting / occupancy-violation detection task.
Seeds are pinned to 42 for reproducibility.
"""

import os
import json
import csv
import sqlite3
import argparse
import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 100,      # v1: 2x base
    "num_workspace_files": 20,  # v1: base + N  (N=10)
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(db_path: str, workspace: str):
    os.makedirs(workspace, exist_ok=True)

    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    N = SCALE["rows_per_table"]
    F = SCALE["num_workspace_files"]

    # ======================================================================
    # 1. UNITS
    # ======================================================================
    units = []
    for i in range(N):
        bedrooms = int(np.random.choice([1, 2, 3], p=[0.3, 0.5, 0.2]))
        units.append({
            "unit_id": f"U{i+1:04d}",
            "building": "A" if i % 2 == 0 else "B",
            "floor": (i % 10) + 1,
            "bedrooms": bedrooms,
            "unit_type": {1: "studio", 2: "standard", 3: "premium"}[bedrooms],
        })

    # ======================================================================
    # 2. SUSPICIOUS UNIT SELECTION (~20 %)
    # ======================================================================
    n_susp = max(5, N // 5)
    susp_indices = sorted(
        np.random.choice(N, size=n_susp, replace=False).tolist()
    )
    susp_set = set(susp_indices)

    # Per-suspicious-unit inflation factor (consistent across months)
    susp_factors = {}
    for idx in susp_indices:
        susp_factors[idx] = float(np.random.uniform(2.0, 3.5))

    # ======================================================================
    # 3. LEASES
    # ======================================================================
    leases = []
    for i, u in enumerate(units):
        br = u["bedrooms"]
        max_occ = br + int(np.random.choice([0, 1]))
        subletting = bool(np.random.random() < 0.3)
        sm = int(np.random.randint(1, 7))
        em = int(np.random.randint(6, 13))
        leases.append({
            "lease_id": f"L{i+1:04d}",
            "unit_id": u["unit_id"],
            "tenant_name": fake.name(),
            "lease_start": f"2025-{sm:02d}-01",
            "lease_end": f"2026-{em:02d}-01",
            "max_occupants": int(max_occ),
            "subletting_allowed": int(subletting),
            "monthly_rent": int(800 + br * 400 + int(np.random.randint(-100, 200))),
        })

    # ======================================================================
    # 4. REGISTERED OCCUPANTS
    # ======================================================================
    occupants = []
    oid = 1
    for i, ls in enumerate(leases):
        occupants.append({
            "occupant_id": oid,
            "unit_id": ls["unit_id"],
            "lease_id": ls["lease_id"],
            "occupant_name": ls["tenant_name"],
            "is_primary": 1,
        })
        oid += 1
        for _ in range(ls["max_occupants"] - 1):
            occupants.append({
                "occupant_id": oid,
                "unit_id": ls["unit_id"],
                "lease_id": ls["lease_id"],
                "occupant_name": fake.name(),
                "is_primary": 0,
            })
            oid += 1

    # ======================================================================
    # 5. UTILITY READINGS  (6 months: Jul - Dec 2025)
    # ======================================================================
    BASE_ELEC = 300    # kWh / occupant / month
    BASE_WATER = 2000  # gal / occupant / month
    BASE_GAS = 30      # therms / occupant / month
    MONTHS = ["2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]

    util_rows = []
    rid = 1
    for i, u in enumerate(units):
        mo = leases[i]["max_occupants"]
        for month in MONTHS:
            if i in susp_set:
                f = susp_factors[i]
                e = BASE_ELEC * mo * f * np.random.uniform(0.9, 1.1) + np.random.normal(0, 20)
                w = BASE_WATER * mo * f * np.random.uniform(0.9, 1.1) + np.random.normal(0, 100)
                g = BASE_GAS * mo * f * np.random.uniform(0.9, 1.1) + np.random.normal(0, 3)
            else:
                e = BASE_ELEC * mo * np.random.uniform(0.7, 1.3) + np.random.normal(0, 20)
                w = BASE_WATER * mo * np.random.uniform(0.7, 1.3) + np.random.normal(0, 100)
                g = BASE_GAS * mo * np.random.uniform(0.7, 1.3) + np.random.normal(0, 3)
            util_rows.append({
                "reading_id": rid,
                "unit_id": u["unit_id"],
                "month": month,
                "electricity_kwh": round(max(0.0, float(e)), 1),
                "water_gallons": round(max(0.0, float(w)), 1),
                "gas_therms": round(max(0.0, float(g)), 1),
            })
            rid += 1

    # ======================================================================
    # 6. ACCESS CARD DATA  &  ACCESS LOGS
    # ======================================================================
    occ_by_unit = {}
    for o in occupants:
        occ_by_unit.setdefault(o["unit_id"], []).append(o["occupant_name"])

    card_counter = 1
    access_log_rows = []
    unit_card_summaries = {}   # uid -> dict for workspace JSON

    for i, u in enumerate(units):
        uid = u["unit_id"]
        mo = leases[i]["max_occupants"]

        if i in susp_set:
            n_cards = max(mo + 1, int(mo * np.random.uniform(2.0, 4.0)))
        else:
            n_cards = mo + (1 if np.random.random() < 0.10 else 0)

        holders = list(occ_by_unit.get(uid, []))
        while len(holders) < n_cards:
            holders.append(fake.name())

        card_details = []
        for holder in holders:
            cid = f"CARD{card_counter:05d}"
            card_counter += 1
            n_events = int(np.random.randint(5, 35))
            for _ in range(n_events):
                mi = int(np.random.randint(0, 6))
                d = int(np.random.randint(1, 29))
                h = int(np.random.randint(6, 23))
                mn = int(np.random.randint(0, 60))
                ap = str(np.random.choice(
                    ["main_entrance", "garage", "side_door", "elevator"]))
                access_log_rows.append({
                    "unit_id": uid,
                    "timestamp": f"2025-{7+mi:02d}-{d:02d} {h:02d}:{mn:02d}:00",
                    "card_id": cid,
                    "card_holder": holder,
                    "access_point": ap,
                })
            card_details.append({
                "card_id": cid,
                "holder_name": holder,
                "entry_count": n_events,
            })

        unit_card_summaries[uid] = {
            "unit_id": uid,
            "monitoring_period": "2025-07-01 to 2025-12-31",
            "total_access_events": sum(c["entry_count"] for c in card_details),
            "unique_access_cards": len(card_details),
            "card_details": card_details,
        }

    # Add sequential log_id
    for idx, row in enumerate(access_log_rows):
        row["log_id"] = idx + 1

    # ======================================================================
    # 7. COMPLAINTS
    # ======================================================================
    CONCERN_CATS = [
        "unauthorized_occupant", "suspected_subletting",
        "excessive_noise", "unknown_persons",
    ]
    OTHER_CATS = [
        "parking_violation", "pet_violation",
        "maintenance_request", "property_damage", "lease_violation",
    ]
    ALL_CATS = CONCERN_CATS + OTHER_CATS

    complaint_rows = []
    comp_id = 1

    # Suspicious units get guaranteed concern-category complaints
    for i in susp_indices:
        uid = f"U{i+1:04d}"
        nc = int(np.random.randint(1, 4))
        for _ in range(nc):
            cat = str(np.random.choice(CONCERN_CATS))
            ri = int(np.random.choice([j for j in range(N) if j != i]))
            m = int(np.random.randint(7, 13))
            d = int(np.random.randint(1, 29))
            complaint_rows.append({
                "complaint_id": comp_id,
                "reporting_unit": f"U{ri+1:04d}",
                "target_unit": uid,
                "date": f"2025-{m:02d}-{d:02d}",
                "category": cat,
                "description": fake.sentence(nb_words=12),
                "status": str(np.random.choice(["open", "under_review", "resolved"])),
            })
            comp_id += 1

    # Fill remaining to meet minimum row count
    while len(complaint_rows) < N:
        ti = int(np.random.randint(0, N))
        ri = int(np.random.choice([j for j in range(N) if j != ti]))
        cat = str(np.random.choice(ALL_CATS))
        m = int(np.random.randint(7, 13))
        d = int(np.random.randint(1, 29))
        complaint_rows.append({
            "complaint_id": comp_id,
            "reporting_unit": f"U{ri+1:04d}",
            "target_unit": f"U{ti+1:04d}",
            "date": f"2025-{m:02d}-{d:02d}",
            "category": cat,
            "description": fake.sentence(nb_words=12),
            "status": str(np.random.choice(["open", "under_review", "resolved"])),
        })
        comp_id += 1

    # ======================================================================
    # 8. WRITE DATABASE
    # ======================================================================
    conn = sqlite3.connect(db_path)

    pd.DataFrame(units).to_sql("units", conn, index=False, if_exists="replace")
    pd.DataFrame(leases).to_sql("leases", conn, index=False, if_exists="replace")
    pd.DataFrame(occupants).to_sql("registered_occupants", conn, index=False, if_exists="replace")
    pd.DataFrame(util_rows).to_sql("utility_readings", conn, index=False, if_exists="replace")
    pd.DataFrame(access_log_rows).to_sql("access_logs", conn, index=False, if_exists="replace")
    pd.DataFrame(complaint_rows).to_sql("complaints", conn, index=False, if_exists="replace")

    conn.close()

    # ======================================================================
    # 9. WRITE WORKSPACE FILES
    # ======================================================================

    # ---- Fixed / policy files (not counted toward num_workspace_files) ----

    # investigation_policy.yaml
    policy = {
        "investigation_criteria": {
            "high_electricity": {
                "description": "Average monthly electricity exceeds threshold per occupant",
                "threshold_kwh_per_occupant": 500,
                "score": 2,
            },
            "high_water": {
                "description": "Average monthly water usage exceeds threshold per occupant",
                "threshold_gallons_per_occupant": 3500,
                "score": 2,
            },
            "excess_access_cards": {
                "description": "Unique access cards exceed allowed multiplier of max occupants",
                "multiplier": 1.5,
                "score": 2,
            },
            "complaint_signals": {
                "description": "Complaints filed in categories of concern",
                "categories_of_concern": CONCERN_CATS,
                "score_per_complaint": 1,
                "max_score": 3,
            },
            "subletting_prohibited": {
                "description": "Lease explicitly prohibits subletting; additional weight when other signals present",
                "score": 1,
                "condition": "Applies only when at least one other signal has already triggered",
            },
        },
        "investigation_threshold": 4,
        "output_format": {
            "filename": "investigation_report.csv",
            "columns": ["unit_id", "total_score", "signals", "subletting_allowed"],
            "signals_separator": "; ",
            "signals_order": "alphabetical",
            "sort_primary": "total_score descending",
            "sort_secondary": "unit_id ascending",
            "subletting_allowed_values": "yes / no",
        },
    }
    with open(os.path.join(workspace, "investigation_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # occupancy_standards.csv
    with open(os.path.join(workspace, "occupancy_standards.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bedrooms", "unit_type",
                     "baseline_electricity_kwh", "baseline_water_gallons",
                     "baseline_gas_therms"])
        w.writerow([1, "studio",   300, 2000, 30])
        w.writerow([2, "standard", 600, 4000, 60])
        w.writerow([3, "premium",  900, 6000, 90])

    # building_regulations.md
    with open(os.path.join(workspace, "building_regulations.md"), "w") as f:
        f.write("# Building Occupancy Regulations\n\n")
        f.write("All residential tenants must comply with the following regulations:\n\n")
        f.write("1. Only persons listed on the lease agreement may reside in a unit on a "
                "permanent basis. Overnight guests are permitted for up to 14 consecutive "
                "days without prior written approval from management.\n\n")
        f.write("2. Subletting, whether partial or whole-unit, is permitted only when the "
                "lease explicitly authorizes it. Unauthorized subletting is grounds for "
                "lease termination.\n\n")
        f.write("3. Each authorized occupant receives one access card. Additional cards "
                "may be issued to immediate family members with management approval. "
                "Sharing of access cards with non-residents is prohibited.\n\n")
        f.write("4. Residents observing potential occupancy violations should file a "
                "complaint through the property management portal, selecting the "
                "appropriate category.\n\n")
        f.write("5. Management reserves the right to investigate any unit where credible "
                "evidence of unauthorized occupancy exists. Investigations will follow the "
                "criteria and scoring methodology outlined in the current investigation "
                "policy.\n")

    # investigation_methodology.md — authoritative definition of the scoring
    methodology_md = """# Occupancy Investigation Methodology

This document defines exactly how each investigation signal is evaluated.
Numeric thresholds, multipliers, caps, point values, the list of complaint
categories of concern, and the investigation threshold are set in the current
investigation policy; this document defines the computations they plug into.
Every unit in the portfolio must be evaluated.

## Utility consumption signals

For each unit, compute the average monthly electricity consumption (kWh) and
the average monthly water consumption (gallons) across all months of the
monitoring window.

The `high_electricity` signal triggers when the unit's average monthly
electricity consumption is strictly greater than the policy's per-occupant
electricity threshold multiplied by the unit's maximum allowed occupant count
as stated on its lease. The `high_water` signal applies the same logic
independently to average monthly water consumption using the policy's
per-occupant water threshold. Gas consumption plays no role in scoring.

## Access card signal

The `excess_access_cards` signal triggers when the number of unique access
cards recorded for a unit over the monitoring period is strictly greater than
the unit's maximum allowed occupant count multiplied by the access-card
multiplier in the policy. The count of formally registered occupants is not
used in this comparison — only the lease's maximum allowed occupant count.

## Complaint signal

Each complaint filed against a unit whose category appears in the policy's
categories of concern contributes the per-complaint score from the policy,
up to the capped maximum stated there. Complaint status and date do not
matter; resolved complaints count the same as open ones. When at least one
qualifying complaint exists, the (possibly capped) total is added as the
`complaint_signals` signal; a unit with no qualifying complaints does not
receive this signal.

## Subletting-prohibited signal

If a unit's lease explicitly prohibits subletting AND at least one other
signal has already been triggered for that unit, the additional
`subletting_prohibited` score from the policy is added. A prohibited-subletting
lease with no other triggered signals contributes nothing.

## Flagging

A unit's total score is the sum of the points from all triggered signals.
A unit is flagged for formal investigation only when its total score meets or
exceeds the investigation threshold in the policy. The signal names listed
above are the exact names to be reported for each flagged unit, formatted
according to the policy's output rules.
"""
    with open(os.path.join(workspace, "investigation_methodology.md"), "w") as f:
        f.write(methodology_md)

    # ---- Scalable data files ----

    n_util_files = F // 2
    n_access_files = F - n_util_files

    unit_ids = [u["unit_id"] for u in units]

    # Utility billing CSVs
    util_df = pd.DataFrame(util_rows)
    chunk = max(1, N // n_util_files)
    for fi in range(n_util_files):
        start = fi * chunk
        end = start + chunk if fi < n_util_files - 1 else N
        ids_slice = unit_ids[start:end]
        subset = util_df[util_df["unit_id"].isin(ids_slice)][
            ["unit_id", "month", "electricity_kwh", "water_gallons", "gas_therms"]
        ]
        fname = f"utility_bills_{fi+1:03d}.csv"
        subset.to_csv(os.path.join(workspace, fname), index=False)

    # Access card report JSONs
    chunk = max(1, N // n_access_files)
    for fi in range(n_access_files):
        start = fi * chunk
        end = start + chunk if fi < n_access_files - 1 else N
        ids_slice = unit_ids[start:end]
        data = [unit_card_summaries[uid] for uid in ids_slice
                if uid in unit_card_summaries]
        fname = f"access_card_report_{fi+1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(data, f, indent=2)

    total_files = n_util_files + n_access_files + 3   # +3 fixed
    print(f"Database written to {db_path}")
    print(f"Workspace created at {workspace}/ with {total_files} files "
          f"({n_util_files} utility CSVs, {n_access_files} access JSONs, "
          f"3 fixed policy/reference files)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
