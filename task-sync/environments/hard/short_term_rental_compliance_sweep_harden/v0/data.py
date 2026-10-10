"""
Data generator for short-term rental compliance sweep task.
Produces a SQLite database and workspace files for the agent.
"""

import argparse
import sqlite3
import os
import json
import csv
import math

import yaml
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 80,       # v0 base; v1 = 2x, v2 = 4x, v3 = 8x
    "num_workspace_files": 8,   # v0 base; v1 = +N, v2 = +2N, v3 = +3N
}

fake = Faker()
Faker.seed(42)
np.random.seed(42)


def main(db_path: str, workspace: str):
    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # ------------------------------------------------------------------ #
    #  Table 1: properties                                                #
    # ------------------------------------------------------------------ #
    zones = ["R1", "R2", "R3", "MU", "C1"]
    zone_probs = [0.25, 0.30, 0.20, 0.15, 0.10]
    property_types = ["single_family", "condo", "townhouse", "multi_family"]
    owner_types = ["individual", "llc", "trust"]
    neighborhoods = [
        "Riverside", "Oakwood", "Maplewood", "Cedar Hills",
        "Lakefront", "Downtown", "Southgate", "Northbridge",
    ]

    properties = []
    for i in range(n_rows):
        sqft = int(np.random.uniform(600, 4000))
        properties.append({
            "property_id": f"PROP-{i + 1:05d}",
            "address": fake.street_address(),
            "owner_name": fake.name() if np.random.random() < 0.7 else fake.company(),
            "owner_type": str(np.random.choice(owner_types, p=[0.6, 0.3, 0.1])),
            "property_type": str(np.random.choice(property_types)),
            "assessed_value": int(np.random.uniform(150000, 900000)),
            "tax_status": str(np.random.choice(["current", "delinquent"], p=[0.85, 0.15])),
            "zoning_code": str(np.random.choice(zones, p=zone_probs)),
            "neighborhood": str(np.random.choice(neighborhoods)),
            "year_built": int(np.random.uniform(1950, 2024)),
            "square_feet": sqft,
        })

    df_props = pd.DataFrame(properties)
    df_props.to_sql("properties", conn, index=False, if_exists="replace")

    # ------------------------------------------------------------------ #
    #  Table 2: rental_listings                                           #
    # ------------------------------------------------------------------ #
    platforms = ["airbnb", "vrbo", "booking"]
    listing_statuses = ["active", "inactive", "suspended"]
    listing_status_probs = [0.75, 0.15, 0.10]

    # ~35 % of properties get at least one listing
    n_listed = max(int(n_rows * 0.35), 10)
    listed_indices = np.random.choice(n_rows, size=n_listed, replace=False)

    listings = []
    lid = 1
    for idx in listed_indices:
        prop = properties[idx]
        n_per = int(np.random.choice([1, 2], p=[0.8, 0.2]))
        for _ in range(n_per):
            listings.append({
                "listing_id": f"LST-{lid:05d}",
                "property_id": prop["property_id"],
                "platform": str(np.random.choice(platforms)),
                "listing_title": f"{fake.catch_phrase()} - {prop['property_type'].replace('_', ' ').title()}",
                "nightly_rate": round(float(np.random.uniform(50, 350)), 2),
                "min_stay_nights": int(np.random.choice([1, 2, 3, 7, 14, 30])),
                "avg_occupancy_pct": round(float(np.random.uniform(20, 95)), 1),
                "review_count": max(0, int(np.random.exponential(20))),
                "listing_created_date": fake.date_between(
                    start_date="-3y", end_date="-1m"
                ).isoformat(),
                "listing_status": str(np.random.choice(listing_statuses, p=listing_status_probs)),
            })
            lid += 1

    # Pad to minimum row count
    while len(listings) < n_rows:
        idx = int(np.random.choice(n_rows))
        prop = properties[idx]
        listings.append({
            "listing_id": f"LST-{lid:05d}",
            "property_id": prop["property_id"],
            "platform": str(np.random.choice(platforms)),
            "listing_title": f"{fake.catch_phrase()} - {prop['property_type'].replace('_', ' ').title()}",
            "nightly_rate": round(float(np.random.uniform(50, 350)), 2),
            "min_stay_nights": int(np.random.choice([1, 2, 3, 7, 14, 30])),
            "avg_occupancy_pct": round(float(np.random.uniform(20, 95)), 1),
            "review_count": max(0, int(np.random.exponential(20))),
            "listing_created_date": fake.date_between(
                start_date="-3y", end_date="-1m"
            ).isoformat(),
            "listing_status": str(np.random.choice(listing_statuses, p=listing_status_probs)),
        })
        lid += 1

    df_listings = pd.DataFrame(listings)
    df_listings.to_sql("rental_listings", conn, index=False, if_exists="replace")

    # ------------------------------------------------------------------ #
    #  Table 3: utility_records  (12 months per property)                 #
    # ------------------------------------------------------------------ #
    active_listing_pids = set(
        l["property_id"] for l in listings if l["listing_status"] == "active"
    )
    months = [f"2025-{m:02d}" for m in range(1, 13)]

    utility_records = []
    uid = 1
    for prop in properties:
        sqft = prop["square_feet"]
        base_kwh = sqft * 0.020
        base_gal = sqft * 0.050
        base_thm = sqft * 0.005
        is_str = prop["property_id"] in active_listing_pids
        for month in months:
            mult = float(np.random.uniform(1.3, 2.2) if is_str else np.random.uniform(0.8, 1.2))
            utility_records.append({
                "record_id": f"UTL-{uid:06d}",
                "property_id": prop["property_id"],
                "billing_month": month,
                "electricity_kwh": round(base_kwh * mult * float(np.random.uniform(0.9, 1.1)), 1),
                "water_gallons": round(base_gal * mult * float(np.random.uniform(0.9, 1.1)), 1),
                "gas_therms": round(base_thm * mult * float(np.random.uniform(0.9, 1.1)), 2),
            })
            uid += 1

    df_util = pd.DataFrame(utility_records)
    df_util.to_sql("utility_records", conn, index=False, if_exists="replace")

    # ------------------------------------------------------------------ #
    #  Table 4: occupancy_permits                                         #
    # ------------------------------------------------------------------ #
    permit_types = ["str_permit", "long_term_rental", "owner_occupied"]
    permits = []
    pid = 1
    for prop in properties:
        if np.random.random() < 0.50:
            ptype = str(np.random.choice(permit_types, p=[0.30, 0.40, 0.30]))
            issue_date = fake.date_between(start_date="-5y", end_date="-6m")
            r = np.random.random()
            if r < 0.20:
                expiry_date = fake.date_between(start_date="-1y", end_date="-1m")
                status = "expired"
            elif r < 0.28:
                expiry_date = fake.date_between(start_date="+1m", end_date="+2y")
                status = "revoked"
            else:
                expiry_date = fake.date_between(start_date="+1m", end_date="+3y")
                status = "active"
            permits.append({
                "permit_id": f"PRM-{pid:05d}",
                "property_id": prop["property_id"],
                "permit_type": ptype,
                "issue_date": issue_date.isoformat(),
                "expiry_date": expiry_date.isoformat(),
                "permit_status": status,
            })
            pid += 1

    # Pad to minimum
    while len(permits) < n_rows:
        idx = int(np.random.choice(n_rows))
        prop = properties[idx]
        ptype = str(np.random.choice(permit_types))
        issue_date = fake.date_between(start_date="-5y", end_date="-6m")
        expiry_date = fake.date_between(start_date="+1m", end_date="+3y")
        permits.append({
            "permit_id": f"PRM-{pid:05d}",
            "property_id": prop["property_id"],
            "permit_type": ptype,
            "issue_date": issue_date.isoformat(),
            "expiry_date": expiry_date.isoformat(),
            "permit_status": "active",
        })
        pid += 1

    df_permits = pd.DataFrame(permits)
    df_permits.to_sql("occupancy_permits", conn, index=False, if_exists="replace")

    conn.commit()

    # ================================================================== #
    #  Workspace files — fixed (policy / config)                          #
    # ================================================================== #

    # 1. enforcement_config.yaml
    config = {
        "violation_base_scores": {
            "no_permit": 40,
            "expired_permit": 30,
            "zoning_violation": 60,
        },
        "modifiers": {
            "complaint_bonus": 15,
            "complaint_threshold": 2,
            "utility_anomaly_bonus": 10,
            "utility_spike_threshold": 1.5,
            "extra_listing_bonus": 5,
        },
        "risk_score_cap": 100,
        "recommended_actions": {
            "high": {"min_score": 70, "action": "immediate_inspection"},
            "medium": {"min_score": 45, "action": "notice_of_violation"},
            "low": {"min_score": 0, "action": "warning_letter"},
        },
    }
    with open(os.path.join(workspace, "enforcement_config.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # 2. zoning_map.json
    zoning_map = {
        "R1": {"description": "Single-Family Residential", "str_permitted": False},
        "R2": {"description": "Multi-Family Residential", "str_permitted": True, "requires_permit": True},
        "R3": {"description": "High-Density Residential", "str_permitted": True, "requires_permit": True},
        "MU": {"description": "Mixed Use", "str_permitted": True, "requires_permit": True},
        "C1": {"description": "Commercial", "str_permitted": True, "requires_permit": False},
    }
    with open(os.path.join(workspace, "zoning_map.json"), "w") as f:
        json.dump(zoning_map, f, indent=2)

    # 3. utility_baselines.csv
    baselines = [
        {"property_type": "single_family", "sqft_min": 0, "sqft_max": 1500,
         "monthly_kwh_per_sqft": 0.020, "monthly_gal_per_sqft": 0.050, "monthly_therm_per_sqft": 0.005},
        {"property_type": "single_family", "sqft_min": 1501, "sqft_max": 3000,
         "monthly_kwh_per_sqft": 0.018, "monthly_gal_per_sqft": 0.045, "monthly_therm_per_sqft": 0.005},
        {"property_type": "single_family", "sqft_min": 3001, "sqft_max": 99999,
         "monthly_kwh_per_sqft": 0.016, "monthly_gal_per_sqft": 0.040, "monthly_therm_per_sqft": 0.004},
        {"property_type": "condo", "sqft_min": 0, "sqft_max": 1200,
         "monthly_kwh_per_sqft": 0.022, "monthly_gal_per_sqft": 0.048, "monthly_therm_per_sqft": 0.005},
        {"property_type": "condo", "sqft_min": 1201, "sqft_max": 99999,
         "monthly_kwh_per_sqft": 0.019, "monthly_gal_per_sqft": 0.043, "monthly_therm_per_sqft": 0.005},
        {"property_type": "townhouse", "sqft_min": 0, "sqft_max": 1800,
         "monthly_kwh_per_sqft": 0.021, "monthly_gal_per_sqft": 0.050, "monthly_therm_per_sqft": 0.005},
        {"property_type": "townhouse", "sqft_min": 1801, "sqft_max": 99999,
         "monthly_kwh_per_sqft": 0.018, "monthly_gal_per_sqft": 0.045, "monthly_therm_per_sqft": 0.005},
        {"property_type": "multi_family", "sqft_min": 0, "sqft_max": 2000,
         "monthly_kwh_per_sqft": 0.023, "monthly_gal_per_sqft": 0.055, "monthly_therm_per_sqft": 0.006},
        {"property_type": "multi_family", "sqft_min": 2001, "sqft_max": 99999,
         "monthly_kwh_per_sqft": 0.020, "monthly_gal_per_sqft": 0.050, "monthly_therm_per_sqft": 0.005},
    ]
    pd.DataFrame(baselines).to_csv(
        os.path.join(workspace, "utility_baselines.csv"), index=False
    )

    # 4. enforcement_methodology.md — authoritative analysis methodology
    methodology = """# Short-Term Rental Enforcement Methodology

This document is the authoritative specification for the compliance sweep.
It works together with `enforcement_config.yaml` (numeric scores, bonuses,
thresholds, cap, and action tiers), `zoning_map.json` (per-zone short-term
rental rules), and `utility_baselines.csv` (expected monthly consumption
rates per square foot by property type and square-footage bracket).

## Scope

A property enters the sweep if it has at least one rental listing with
status `active` on any platform. Properties with only inactive or suspended
listings are out of scope.

## Violation classification

Classify each in-scope property using the zoning map entry for its zoning
code:

1. If short-term rentals are not permitted in the zone (`str_permitted` is
   false), the violation type is `zoning_violation`, regardless of any
   permits on file.
2. If the zone permits short-term rentals and requires a permit
   (`requires_permit` is true), examine the property's occupancy-permit
   records, considering only permits of type `str_permit`:
   - If no `str_permit` exists at all, the violation type is `no_permit`.
   - If a `str_permit` with status `active` exists, the property is
     compliant and is NOT a violation case.
   - Otherwise, if any `str_permit` has status `expired`, the violation
     type is `expired_permit`.
   - A `str_permit` in any other non-active state (e.g. revoked or
     pending) is treated the same as having no permit: the violation type
     is `no_permit`.
3. If the zone permits short-term rentals without requiring a permit, the
   property is not a violation.

## Risk score

Each violation case receives a risk score. Start with the base score for
its violation type as defined in the enforcement configuration, then apply
the modifiers:

- **Complaint bonus** — count the total number of complaints filed against
  the property's street address across all complaint batch files. If that
  count meets or exceeds the complaint threshold, add the complaint bonus
  (once).
- **Utility anomaly bonus** — compute the property's average monthly
  electricity (kWh), water (gallons), and gas (therms) consumption over the
  full twelve months of 2025 (2025-01 through 2025-12). Look up the
  baseline row matching the property's type and square footage. A utility
  anomaly exists if ANY of the three averages exceeds the corresponding
  per-square-foot baseline rate multiplied by the property's square footage
  and then multiplied by the utility spike threshold. If an anomaly exists,
  add the utility anomaly bonus (once).
- **Extra listing bonus** — add the extra listing bonus once for each
  additional active listing beyond the first.

Finally, cap the risk score at the configured maximum.

## Recommended enforcement action

Compare the final (capped) risk score against the action tiers in the
enforcement configuration, checking from the highest tier downward; the
first tier whose minimum score is met determines the recommended action.

## Estimated annual revenue

The platform intelligence files contain one entry per listing, each with an
`estimated_annual_revenue` figure. Aggregate revenue by property: sum the
estimated annual revenue across all listings that belong to the same
property. Properties with no intelligence entries have revenue 0.
"""
    with open(os.path.join(workspace, "enforcement_methodology.md"), "w") as f:
        f.write(methodology)

    # ================================================================== #
    #  Workspace files — scalable                                         #
    # ================================================================== #
    # Distribute across 4 formats: .csv (complaints), .json (platform intel),
    # .txt (neighborhood digest), .md (tax memo)
    n_csv = max(1, n_files * 3 // 8)
    n_json = max(1, n_files * 3 // 8)
    n_txt = max(1, (n_files - n_csv - n_json) // 2)
    n_md = n_files - n_csv - n_json - n_txt
    if n_md < 1:
        n_md = 1
        n_txt = n_files - n_csv - n_json - n_md

    # ---------- complaint batch CSVs ----------
    complaint_types = ["noise", "parking", "trash", "safety", "overcrowding", "commercial_activity"]
    all_complaints = []
    cid = 1
    for prop in properties:
        if prop["property_id"] in active_listing_pids:
            nc = int(np.random.choice([0, 1, 2, 3, 4], p=[0.25, 0.25, 0.20, 0.18, 0.12]))
        else:
            nc = int(np.random.choice([0, 1], p=[0.92, 0.08]))
        for _ in range(nc):
            all_complaints.append({
                "complaint_id": f"CMP-{cid:05d}",
                "property_address": prop["address"],
                "report_date": fake.date_between(start_date="-1y", end_date="today").isoformat(),
                "complaint_type": str(np.random.choice(complaint_types)),
                "reporter_notes": fake.sentence(nb_words=12),
            })
            cid += 1

    # Shuffle and split across files
    np.random.shuffle(all_complaints)
    chunk = max(1, len(all_complaints) // n_csv)
    for i in range(n_csv):
        start = i * chunk
        end = start + chunk if i < n_csv - 1 else len(all_complaints)
        batch = all_complaints[start:end]
        if batch:
            pd.DataFrame(batch).to_csv(
                os.path.join(workspace, f"complaint_batch_{i + 1}.csv"), index=False
            )
        else:
            pd.DataFrame(columns=["complaint_id", "property_address", "report_date",
                                   "complaint_type", "reporter_notes"]).to_csv(
                os.path.join(workspace, f"complaint_batch_{i + 1}.csv"), index=False
            )

    # ---------- platform intel JSONs ----------
    active_listings = [l for l in listings if l["listing_status"] == "active"]
    all_intel = []
    for lst in active_listings:
        all_intel.append({
            "listing_id": lst["listing_id"],
            "property_id": lst["property_id"],
            "estimated_annual_revenue": round(
                lst["nightly_rate"] * 365 * lst["avg_occupancy_pct"] / 100, 2
            ),
            "host_response_rate_pct": round(float(np.random.uniform(60, 100)), 1),
            "average_rating": round(float(np.random.uniform(3.0, 5.0)), 2),
            "recent_booking_count_30d": int(np.random.uniform(0, 20)),
            "property_photos_count": int(np.random.uniform(3, 25)),
            "superhost_badge": bool(np.random.random() < 0.3),
        })
    chunk = max(1, len(all_intel) // n_json)
    for i in range(n_json):
        start = i * chunk
        end = start + chunk if i < n_json - 1 else len(all_intel)
        batch = all_intel[start:end]
        with open(os.path.join(workspace, f"platform_intel_{i + 1}.json"), "w") as f:
            json.dump(batch if batch else [], f, indent=2)

    # ---------- neighborhood digest TXTs ----------
    # Summarise complaint counts per neighborhood
    nbr_complaints: dict = {}
    for c in all_complaints:
        # Find the property's neighborhood via address lookup
        for prop in properties:
            if prop["address"] == c["property_address"]:
                nb = prop["neighborhood"]
                nbr_complaints.setdefault(nb, []).append(c)
                break

    nbr_list = sorted(nbr_complaints.keys())
    chunk_nb = max(1, len(nbr_list) // n_txt)
    for i in range(n_txt):
        start = i * chunk_nb
        end = start + chunk_nb if i < n_txt - 1 else len(nbr_list)
        lines = []
        for nb in nbr_list[start:end]:
            lines.append(f"=== Neighborhood: {nb} ===")
            lines.append(f"Total complaints filed: {len(nbr_complaints[nb])}")
            type_counts: dict = {}
            for c in nbr_complaints[nb]:
                type_counts[c["complaint_type"]] = type_counts.get(c["complaint_type"], 0) + 1
            for ct, cnt in sorted(type_counts.items()):
                lines.append(f"  {ct}: {cnt}")
            lines.append("")
        with open(os.path.join(workspace, f"neighborhood_digest_{i + 1}.txt"), "w") as f:
            f.write("\n".join(lines))

    # ---------- tax memo MDs ----------
    # Delinquent-tax properties with active listings — a red flag
    delinquent_active = [
        p for p in properties
        if p["tax_status"] == "delinquent" and p["property_id"] in active_listing_pids
    ]
    chunk_d = max(1, len(delinquent_active) // n_md) if delinquent_active else 1
    for i in range(n_md):
        start = i * chunk_d
        end = start + chunk_d if i < n_md - 1 else len(delinquent_active)
        batch = delinquent_active[start:end]
        lines = [f"# Tax Delinquency Memo — Batch {i + 1}", ""]
        if batch:
            for p in batch:
                lines.append(f"## {p['property_id']} — {p['address']}")
                lines.append(f"Owner: {p['owner_name']} ({p['owner_type']})")
                lines.append(f"Assessed value: ${p['assessed_value']:,}")
                lines.append(f"Tax status: **{p['tax_status']}**")
                lines.append("")
        else:
            lines.append("No delinquent-tax properties with active rental listings in this batch.")
        with open(os.path.join(workspace, f"tax_memo_{i + 1}.md"), "w") as f:
            f.write("\n".join(lines))

    conn.close()
    print(f"Database written to {db_path}")
    print(f"Workspace files written to {workspace}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
