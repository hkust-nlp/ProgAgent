import argparse
import os
import sqlite3
import json
import csv
import random
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta
import yaml

SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 20,
}

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

# ----- constants -----
BASE_DATE = datetime(2025, 1, 1)
DATE_RANGE_DAYS = 60  # Jan 1 - Mar 1, 2025

NUM_ZONES = 20
ZONE_IDS = [f"Z{str(i).zfill(3)}" for i in range(1, NUM_ZONES + 1)]
TIER_BREAKS = {"premium": (1, 5), "standard": (6, 13), "economy": (14, 20)}
ZONE_TIER = {}
for tier, (lo, hi) in TIER_BREAKS.items():
    for idx in range(lo, hi + 1):
        ZONE_TIER[f"Z{str(idx).zfill(3)}"] = tier

VEHICLE_TYPES = ["sedan", "suv", "compact", "luxury", "van"]
CAMPAIGN_TYPES = [
    "peak_surge_bonus",
    "completion_streak",
    "weekend_warrior",
    "new_zone_incentive",
    "loyalty_bonus",
]

PEAK_HOURS = {
    "weekday": {"morning": [7, 10], "evening": [17, 20]},
    "weekend": {"morning": [9, 12], "evening": [16, 19]},
}

ZONE_TIER_MULTIPLIERS = {"premium": 1.5, "standard": 1.0, "economy": 0.75}


# ================================================================
# helpers
# ================================================================
def _rand_dt(day_offset_range):
    hour_weights = [1] * 6 + [3, 5, 5, 4, 3, 3, 3, 3, 4, 4, 5, 6, 6, 5, 4, 3, 2, 1]
    day = random.randint(0, day_offset_range - 1)
    hour = random.choices(range(24), weights=hour_weights, k=1)[0]
    minute = random.randint(0, 59)
    return BASE_DATE + timedelta(days=day, hours=hour, minutes=minute)


# ================================================================
# generators
# ================================================================
def gen_drivers(n):
    rows = []
    for i in range(1, n + 1):
        rows.append(
            {
                "driver_id": f"D{str(i).zfill(4)}",
                "name": fake.name(),
                "license_number": fake.bothify("??-####-??").upper(),
                "vehicle_type": random.choice(VEHICLE_TYPES),
                "registration_date": (
                    BASE_DATE - timedelta(days=random.randint(30, 730))
                ).strftime("%Y-%m-%d"),
                "city": random.choice(
                    ["Metro City", "Harbor Town", "Mountain View", "Lake Side"]
                ),
            }
        )
    return pd.DataFrame(rows)


def gen_trips(n, driver_ids):
    rows = []
    for i in range(1, n + 1):
        start = _rand_dt(DATE_RANGE_DAYS)
        duration_min = random.randint(5, 90)
        end = start + timedelta(minutes=duration_min)
        distance = round(random.uniform(1.0, 45.0), 2)
        fare = round(distance * random.uniform(1.5, 4.0) + random.uniform(2, 10), 2)
        status = random.choices(
            ["completed", "cancelled", "no_show"], weights=[85, 10, 5], k=1
        )[0]
        rows.append(
            {
                "trip_id": f"T{str(i).zfill(5)}",
                "driver_id": random.choice(driver_ids),
                "zone_id": random.choice(ZONE_IDS),
                "start_time": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": end.strftime("%Y-%m-%d %H:%M:%S"),
                "distance_km": distance,
                "fare_amount": fare,
                "status": status,
                "passenger_rating": (
                    round(random.uniform(1.0, 5.0), 1)
                    if status == "completed"
                    else None
                ),
            }
        )
    return pd.DataFrame(rows)


def gen_surge_zones(n):
    rows = []
    for i in range(1, n + 1):
        zone = random.choice(ZONE_IDS)
        start = _rand_dt(DATE_RANGE_DAYS)
        duration = random.randint(15, 180)
        end = start + timedelta(minutes=duration)
        mult = round(random.choice([1.2, 1.3, 1.5, 1.8, 2.0, 2.2, 2.5]), 1)
        rows.append(
            {
                "record_id": i,
                "zone_id": zone,
                "surge_start": start.strftime("%Y-%m-%d %H:%M:%S"),
                "surge_end": end.strftime("%Y-%m-%d %H:%M:%S"),
                "surge_multiplier": mult,
            }
        )
    return pd.DataFrame(rows)


def gen_driver_sessions(n, driver_ids):
    rows = []
    for i in range(1, n + 1):
        driver = random.choice(driver_ids)
        day = random.randint(0, DATE_RANGE_DAYS - 1)
        hour = random.randint(4, 20)
        start = BASE_DATE + timedelta(
            days=day, hours=hour, minutes=random.randint(0, 59)
        )
        dur_h = random.uniform(1, 12)
        end = start + timedelta(hours=dur_h)
        rows.append(
            {
                "session_id": f"S{str(i).zfill(5)}",
                "driver_id": driver,
                "online_start": start.strftime("%Y-%m-%d %H:%M:%S"),
                "online_end": end.strftime("%Y-%m-%d %H:%M:%S"),
                "session_status": random.choices(
                    ["active", "idle", "break"], weights=[70, 20, 10], k=1
                )[0],
            }
        )
    return pd.DataFrame(rows)


def gen_campaigns(n):
    rows = []
    for i in range(1, n + 1):
        ctype = random.choice(CAMPAIGN_TYPES)
        start_off = random.randint(0, DATE_RANGE_DAYS - 14)
        dur = random.randint(3, 21)
        sd = BASE_DATE + timedelta(days=start_off)
        ed = sd + timedelta(days=dur)
        tier_opts = ["premium", "standard", "economy"]
        eligible = sorted(random.sample(tier_opts, random.randint(1, 3)))
        rows.append(
            {
                "campaign_id": f"C{str(i).zfill(3)}",
                "name": f"{ctype.replace('_', ' ').title()} #{i}",
                "campaign_type": ctype,
                "start_date": sd.strftime("%Y-%m-%d"),
                "end_date": ed.strftime("%Y-%m-%d"),
                "bonus_per_trip": round(random.uniform(3.0, 25.0), 2),
                "min_completed_trips": random.randint(1, 10),
                "min_online_hours": round(random.uniform(2.0, 20.0), 1),
                "min_driver_rating": round(
                    random.choice([3.0, 3.5, 4.0, 4.2, 4.5]), 1
                ),
                "eligible_zone_tiers": ",".join(eligible),
                "peak_hours_only": random.choices([0, 1], weights=[40, 60], k=1)[0],
                "max_payout_per_driver": round(random.uniform(50.0, 500.0), 2),
            }
        )
    return pd.DataFrame(rows)


def gen_claims(n, trips_df, campaign_ids):
    rows = []
    used = set()
    for i in range(1, n + 1):
        tidx = random.randint(0, len(trips_df) - 1)
        trip = trips_df.iloc[tidx]
        cid = random.choice(campaign_ids)
        combo = (trip["driver_id"], cid, trip["trip_id"])
        if combo in used and random.random() > 0.05:
            tidx = random.randint(0, len(trips_df) - 1)
            trip = trips_df.iloc[tidx]
            combo = (trip["driver_id"], cid, trip["trip_id"])
        used.add(combo)
        base_amt = round(random.uniform(3.0, 30.0), 2)
        claimed = (
            base_amt
            if random.random() > 0.25
            else round(base_amt * random.uniform(1.1, 2.0), 2)
        )
        trip_dt = datetime.strptime(trip["start_time"], "%Y-%m-%d %H:%M:%S")
        claim_date = trip_dt + timedelta(days=random.randint(0, 5))
        status = random.choices(
            ["pending", "processed", "rejected"], weights=[35, 45, 20], k=1
        )[0]
        rows.append(
            {
                "claim_id": f"CL{str(i).zfill(4)}",
                "driver_id": trip["driver_id"],
                "campaign_id": cid,
                "trip_id": trip["trip_id"],
                "claimed_amount": claimed,
                "claim_date": claim_date.strftime("%Y-%m-%d"),
                "status": status,
            }
        )
    return pd.DataFrame(rows)


# ================================================================
# workspace file generators
# ================================================================
def _write_peak_hours_config(ws):
    with open(os.path.join(ws, "peak_hours_config.json"), "w") as f:
        json.dump(PEAK_HOURS, f, indent=2)


def _write_zone_tier_mapping(ws):
    path = os.path.join(ws, "zone_tier_mapping.csv")
    area_names = {
        "premium": [
            "Downtown Core",
            "Financial District",
            "Central Plaza",
            "Civic Center",
            "Tech Park",
        ],
        "standard": [
            "Midtown",
            "University Row",
            "Market Street",
            "Riverside",
            "Greenfield",
            "Sunset Strip",
            "Lakefront",
            "Old Town",
        ],
        "economy": [
            "Industrial Zone",
            "Northgate",
            "Eastville",
            "Suburbia",
            "Farmington",
            "Hillcrest",
            "Westend",
        ],
    }
    idx_counter = {"premium": 0, "standard": 0, "economy": 0}
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["zone_id", "tier", "area_name"])
        for zid in ZONE_IDS:
            tier = ZONE_TIER[zid]
            names = area_names[tier]
            w.writerow([zid, tier, names[idx_counter[tier] % len(names)]])
            idx_counter[tier] += 1


def _write_payout_policy(ws):
    policy = {
        "payout_calculation": {
            "base": "campaign_bonus_per_trip",
            "surge_adjustment": "multiply_by_highest_active_surge",
            "zone_tier_multiplier": ZONE_TIER_MULTIPLIERS,
            "rounding_decimals": 2,
        },
        "eligibility": {
            "session_status_counted": ["active"],
            "trip_status_required": "completed",
            "duplicate_policy": "reject_all_duplicates",
        },
    }
    with open(os.path.join(ws, "payout_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)


def _write_daily_ops_logs(ws, trips_df, driver_ids, num_files):
    """
    Generate daily-operation log CSV files.  Each file covers a contiguous
    batch of days.  Columns: driver_id, report_date, daily_rating,
    trips_completed, online_minutes, complaints.
    """
    total_days = DATE_RANGE_DAYS
    days_per_file = max(1, math.ceil(total_days / num_files))

    file_idx = 0
    for batch_start in range(0, total_days, days_per_file):
        if file_idx >= num_files:
            break
        batch_end = min(batch_start + days_per_file, total_days)
        batch_dates = [
            (BASE_DATE + timedelta(days=d)).strftime("%Y-%m-%d")
            for d in range(batch_start, batch_end)
        ]
        rows = []
        for d_str in batch_dates:
            for did in driver_ids:
                day_trips = trips_df[
                    (trips_df["driver_id"] == did)
                    & (trips_df["start_time"].str.startswith(d_str))
                    & (trips_df["status"] == "completed")
                ]
                if len(day_trips) > 0:
                    base_r = day_trips["passenger_rating"].mean()
                else:
                    base_r = round(random.uniform(3.5, 4.8), 2)
                daily_rating = round(
                    np.clip(base_r + np.random.normal(0, 0.15), 1.0, 5.0), 2
                )
                rows.append(
                    {
                        "driver_id": did,
                        "report_date": d_str,
                        "daily_rating": daily_rating,
                        "trips_completed": len(day_trips),
                        "online_minutes": random.randint(0, 720),
                        "complaints": random.choices(
                            [0, 0, 0, 0, 1, 1, 2], k=1
                        )[0],
                    }
                )
        fname = f"daily_ops_log_{str(file_idx + 1).zfill(3)}.csv"
        pd.DataFrame(rows).to_csv(os.path.join(ws, fname), index=False)
        file_idx += 1


def _write_campaign_eligibility_notes(ws):
    """Fixed markdown doc explaining eligibility rules in prose."""
    text = (
        "Driver Incentive Eligibility Reference\n"
        "======================================\n\n"
        "Each promotional campaign specifies a set of qualifying criteria that a "
        "driver must satisfy before a payout can be approved.\n\n"
        "Rating Requirement: The driver's average daily rating over the campaign "
        "period, as recorded in the daily operations logs, must meet or exceed the "
        "campaign's minimum driver rating threshold. Only dates that fall within "
        "the campaign's active window (start date through end date, inclusive) are "
        "considered.\n\n"
        "Online-Hours Requirement: Total online hours are computed from driver "
        "session records whose status is listed under the counted statuses in the "
        "payout policy. Only sessions that overlap the campaign period contribute. "
        "For sessions that partially overlap, count only the overlapping portion.\n\n"
        "Trip-Count Requirement: The number of completed trips a driver has during "
        "the campaign window must meet or exceed the campaign's minimum.\n\n"
        "Zone Eligibility: The trip's zone must belong to one of the tier "
        "categories that the campaign designates as eligible. Zone-to-tier "
        "assignments are published in the zone tier mapping file.\n\n"
        "Peak-Hours Constraint: Campaigns flagged as peak-hours-only will only "
        "count trips whose start time falls within the defined peak-hour windows. "
        "Peak hours differ between weekdays and weekends and are published in the "
        "peak-hours configuration file.\n\n"
        "Surge Adjustment: The correct payout for an eligible trip is the "
        "campaign's base bonus per trip, multiplied by the zone-tier multiplier "
        "for the trip's zone, and further multiplied by the highest active surge "
        "multiplier in effect for that zone at the trip's start time. If no surge "
        "was active, the surge factor is 1.0.\n\n"
        "Duplicate Policy: If more than one pending claim references the same "
        "driver, campaign, and trip combination, all such duplicates are "
        "rejected.\n\n"
        "Per-Driver Cap: Each campaign defines a maximum total payout per driver. "
        "After computing eligible amounts for all of a driver's approved claims "
        "under a given campaign, if the cumulative total exceeds the cap the "
        "last claims (by claim ID ascending order) are reduced or zeroed to "
        "enforce the cap. Partially-capped claims receive the remainder; fully-"
        "capped claims receive zero. The discrepancy reason for any claim whose "
        "amount is reduced by the cap is 'per_driver_cap_exceeded'.\n"
    )
    with open(os.path.join(ws, "eligibility_rules.md"), "w") as f:
        f.write(text)


# ================================================================
# main
# ================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # --- generate dataframes ---
    drivers_df = gen_drivers(n_rows)
    driver_ids = drivers_df["driver_id"].tolist()

    trips_df = gen_trips(n_rows * 3, driver_ids)
    surge_df = gen_surge_zones(n_rows * 2)
    sessions_df = gen_driver_sessions(n_rows * 2, driver_ids)
    campaigns_df = gen_campaigns(n_rows)
    claims_df = gen_claims(n_rows, trips_df, campaigns_df["campaign_id"].tolist())

    # --- write to SQLite ---
    conn = sqlite3.connect(args.db_path)
    drivers_df.to_sql("drivers", conn, if_exists="replace", index=False)
    trips_df.to_sql("trips", conn, if_exists="replace", index=False)
    surge_df.to_sql("surge_zones", conn, if_exists="replace", index=False)
    sessions_df.to_sql("driver_sessions", conn, if_exists="replace", index=False)
    campaigns_df.to_sql("campaigns", conn, if_exists="replace", index=False)
    claims_df.to_sql("incentive_claims", conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()

    # --- workspace: fixed config files ---
    _write_peak_hours_config(args.workspace)
    _write_zone_tier_mapping(args.workspace)
    _write_payout_policy(args.workspace)
    _write_campaign_eligibility_notes(args.workspace)

    # --- workspace: scaling data files (daily ops logs) ---
    _write_daily_ops_logs(args.workspace, trips_df, driver_ids, n_files)

    print(
        f"Database written to {args.db_path}"
    )
    print(
        f"Workspace populated at {args.workspace}/ "
        f"({n_files} daily-ops logs + 4 config files)"
    )


if __name__ == "__main__":
    main()
