import argparse
import os
import sqlite3
import json
import random
import numpy as np
import pandas as pd
import yaml
from faker import Faker
from collections import defaultdict


SCALE = {
    "rows_per_table": 120,
    "num_workspace_files": 40,
}

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

REPORTING_WEEK_START = "2025-01-06"
REPORTING_WEEK_END = "2025-01-12"

SEVERITY_LEVELS = ["low", "medium", "high", "critical"]
VIOLATION_TYPES = [
    "unauthorized_entry", "overstay", "speeding_in_zone",
    "wrong_entry_point", "after_hours_access",
]
SLA_TIERS = ["gold", "silver", "bronze"]
DRIVER_STATUSES = ["active", "inactive", "on_leave"]
CERTIFICATION_LEVELS = ["standard", "advanced", "senior"]
SHIFT_STATUSES = ["completed", "incomplete", "no_show"]
REGIONS = [
    "Northeast", "Southeast", "Midwest",
    "Southwest", "Northwest", "Central",
]


def create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS depots (
            depot_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            region TEXT NOT NULL,
            manager_name TEXT NOT NULL,
            address TEXT NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS drivers (
            driver_id INTEGER PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            depot_id INTEGER NOT NULL,
            license_class TEXT NOT NULL,
            certification_level TEXT NOT NULL,
            hire_date TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (depot_id) REFERENCES depots(depot_id)
        );
        CREATE TABLE IF NOT EXISTS customers (
            customer_id INTEGER PRIMARY KEY,
            company_name TEXT NOT NULL,
            site_address TEXT NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            geofence_radius_m REAL NOT NULL,
            assigned_depot_id INTEGER NOT NULL,
            FOREIGN KEY (assigned_depot_id) REFERENCES depots(depot_id)
        );
        CREATE TABLE IF NOT EXISTS contracts (
            contract_id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            sla_tier TEXT NOT NULL,
            max_weekly_violations INTEGER NOT NULL,
            penalty_per_violation REAL NOT NULL,
            contract_start TEXT NOT NULL,
            contract_end TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        );
        CREATE TABLE IF NOT EXISTS gps_pings (
            ping_id INTEGER PRIMARY KEY,
            driver_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            speed_kmh REAL NOT NULL,
            heading_deg REAL NOT NULL,
            FOREIGN KEY (driver_id) REFERENCES drivers(driver_id)
        );
        CREATE TABLE IF NOT EXISTS shift_logs (
            shift_id INTEGER PRIMARY KEY,
            driver_id INTEGER NOT NULL,
            shift_date TEXT NOT NULL,
            clock_in TEXT NOT NULL,
            clock_out TEXT NOT NULL,
            vehicle_id TEXT NOT NULL,
            route_id TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (driver_id) REFERENCES drivers(driver_id)
        );
        CREATE TABLE IF NOT EXISTS violations (
            violation_id INTEGER PRIMARY KEY,
            driver_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            violation_type TEXT NOT NULL,
            distance_exceeded_m REAL,
            dwell_time_s REAL,
            severity TEXT NOT NULL,
            acknowledged INTEGER NOT NULL DEFAULT 0,
            resolved INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (driver_id) REFERENCES drivers(driver_id),
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        );
    """)
    conn.commit()


def generate_depots(conn, n):
    depots = []
    used = set()
    for i in range(1, n + 1):
        while True:
            city = fake.city()
            name = f"Depot {city}-{i:03d}"
            if name not in used:
                used.add(name)
                break
        depots.append((
            i, name, random.choice(REGIONS),
            fake.name(), fake.street_address(),
            city, fake.state_abbr(),
        ))
    conn.executemany("INSERT INTO depots VALUES (?,?,?,?,?,?,?)", depots)
    conn.commit()
    return depots


def generate_drivers(conn, n, depot_ids):
    drivers = []
    for i in range(1, n + 1):
        depot_id = depot_ids[(i - 1) % len(depot_ids)]
        if random.random() < 0.15:
            depot_id = random.choice(depot_ids)
        status = random.choices(
            DRIVER_STATUSES, weights=[0.80, 0.10, 0.10], k=1
        )[0]
        drivers.append((
            i, fake.first_name(), fake.last_name(),
            depot_id,
            random.choice(["A", "B", "C", "CDL"]),
            random.choice(CERTIFICATION_LEVELS),
            fake.date_between(start_date="-10y", end_date="-6m").isoformat(),
            status,
        ))
    conn.executemany("INSERT INTO drivers VALUES (?,?,?,?,?,?,?,?)", drivers)
    conn.commit()
    return drivers


def generate_customers(conn, n, depot_ids):
    customers = []
    for i in range(1, n + 1):
        customers.append((
            i, fake.company(), fake.street_address(),
            fake.city(), fake.state_abbr(),
            round(float(fake.latitude()), 6),
            round(float(fake.longitude()), 6),
            round(random.uniform(50, 500), 1),
            depot_ids[(i - 1) % len(depot_ids)],
        ))
    conn.executemany(
        "INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?)", customers
    )
    conn.commit()
    return customers


def generate_contracts(conn, customer_ids):
    tier_cfg = {
        "gold":   {"max_v": (1, 3),  "pen": (400, 600)},
        "silver": {"max_v": (3, 6),  "pen": (150, 300)},
        "bronze": {"max_v": (5, 12), "pen": (30, 80)},
    }
    contracts = []
    for i, cid in enumerate(customer_ids, start=1):
        tier = random.choice(SLA_TIERS)
        c = tier_cfg[tier]
        contracts.append((
            i, cid, tier,
            random.randint(*c["max_v"]),
            round(random.uniform(*c["pen"]), 2),
            fake.date_between(start_date="-2y", end_date="-6m").isoformat(),
            fake.date_between(start_date="+6m", end_date="+2y").isoformat(),
            1,
        ))
    conn.executemany(
        "INSERT INTO contracts VALUES (?,?,?,?,?,?,?,?)", contracts
    )
    conn.commit()
    return contracts


def generate_gps_pings(conn, n, driver_ids):
    from datetime import datetime, timedelta
    pings = []
    start = datetime(2025, 1, 6, 6, 0, 0)
    for i in range(1, n + 1):
        did = random.choice(driver_ids)
        ts = start + timedelta(
            days=random.randint(0, 6),
            hours=random.randint(0, 14),
            minutes=random.randint(0, 59),
            seconds=random.randint(0, 59),
        )
        pings.append((
            i, did, ts.strftime("%Y-%m-%d %H:%M:%S"),
            round(float(fake.latitude()), 6),
            round(float(fake.longitude()), 6),
            round(random.uniform(0, 120), 1),
            round(random.uniform(0, 360), 1),
        ))
    conn.executemany(
        "INSERT INTO gps_pings VALUES (?,?,?,?,?,?,?)", pings
    )
    conn.commit()


def generate_shift_logs(conn, n, driver_ids):
    from datetime import datetime, timedelta
    logs = []
    for i in range(1, n + 1):
        did = random.choice(driver_ids)
        day_off = random.randint(0, 6)
        sd = (datetime(2025, 1, 6) + timedelta(days=day_off)).strftime("%Y-%m-%d")
        sh = random.randint(5, 10)
        dur = random.randint(6, 12)
        ci = f"{sh:02d}:{random.randint(0, 59):02d}:00"
        eh = min(sh + dur, 23)
        co = f"{eh:02d}:{random.randint(0, 59):02d}:00"
        logs.append((
            i, did, sd, ci, co,
            f"VEH-{random.randint(100, 999)}",
            f"RT-{random.randint(1, 50):03d}",
            random.choices(SHIFT_STATUSES, weights=[0.75, 0.15, 0.10], k=1)[0],
        ))
    conn.executemany(
        "INSERT INTO shift_logs VALUES (?,?,?,?,?,?,?,?)", logs
    )
    conn.commit()


def generate_violations(conn, n, drivers, customers):
    from datetime import datetime, timedelta

    driver_depot = {d[0]: d[3] for d in drivers}
    driver_ids = [d[0] for d in drivers]
    customer_ids = [c[0] for c in customers]

    custs_by_depot = defaultdict(list)
    for c in customers:
        custs_by_depot[c[8]].append(c[0])

    raw_w = np.random.dirichlet(np.ones(len(driver_ids)) * 0.4)
    driver_weights = raw_w / raw_w.sum()

    violations = []
    for i in range(1, n + 1):
        did = int(np.random.choice(driver_ids, p=driver_weights))
        dep = driver_depot[did]
        dc = custs_by_depot.get(dep, [])
        cid = random.choice(dc) if dc else random.choice(customer_ids)

        ts = datetime(2025, 1, 6) + timedelta(
            days=random.randint(0, 6),
            hours=random.randint(6, 20),
            minutes=random.randint(0, 59),
        )
        vtype = random.choice(VIOLATION_TYPES)
        sev = random.choices(
            SEVERITY_LEVELS, weights=[0.30, 0.35, 0.25, 0.10], k=1
        )[0]
        dist = (
            round(random.uniform(5, 200), 1)
            if vtype in ["unauthorized_entry", "wrong_entry_point", "speeding_in_zone"]
            else None
        )
        dwell = (
            round(random.uniform(60, 7200), 0)
            if vtype in ["overstay", "after_hours_access"]
            else None
        )
        violations.append((
            i, did, cid,
            ts.strftime("%Y-%m-%d %H:%M:%S"),
            vtype, dist, dwell, sev,
            random.randint(0, 1), random.randint(0, 1),
        ))
    conn.executemany(
        "INSERT INTO violations VALUES (?,?,?,?,?,?,?,?,?,?)", violations
    )
    conn.commit()
    return violations


def generate_workspace(workspace, conn, num_files):
    os.makedirs(workspace, exist_ok=True)

    cur = conn.cursor()
    cur.execute("SELECT violation_id FROM violations")
    all_vids = [r[0] for r in cur.fetchall()]

    k = max(1, int(len(all_vids) * 0.75))
    covered = sorted(random.sample(all_vids, k=k))
    random.shuffle(covered)

    weathers = ["clear", "rain", "fog", "snow", "wind", "storm"]
    adj_pool = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.0, 1.0, 1.1, 1.2, 1.3, 1.5]

    chunks = (
        np.array_split(covered, num_files) if covered
        else [[] for _ in range(num_files)]
    )

    for idx in range(num_files):
        fp = os.path.join(workspace, f"incident_context_{idx + 1:03d}.csv")
        chunk = list(chunks[idx]) if idx < len(chunks) else []
        rows = []
        for vid in chunk:
            rows.append({
                "violation_id": int(vid),
                "adjustment_factor": round(random.choice(adj_pool), 2),
                "weather_condition": random.choice(weathers),
                "customer_feedback": fake.sentence(nb_words=8),
                "supervisor_notes": fake.sentence(nb_words=10),
                "disputed": 1 if random.random() < 0.08 else 0,
            })
        df = pd.DataFrame(rows, columns=[
            "violation_id", "adjustment_factor", "weather_condition",
            "customer_feedback", "supervisor_notes", "disputed",
        ])
        df.to_csv(fp, index=False)

    # ---- Fixed configuration files ----

    scoring = {
        "severity_weights": {
            "low": 2,
            "medium": 5,
            "high": 10,
            "critical": 20,
        },
        "default_adjustment_factor": 1.0,
        "sla_breach_multiplier": 1.5,
        "risk_thresholds": {
            "low":      {"min_score": 80},
            "medium":   {"min_score": 60},
            "high":     {"min_score": 40},
            "critical": {"min_score": 0},
        },
    }
    with open(os.path.join(workspace, "scoring_weights.json"), "w") as f:
        json.dump(scoring, f, indent=2)

    retraining = {
        "flag_conditions": {
            "min_violations": 3,
            "min_weighted_severity_score": 15.0,
            "critical_violation_auto_flag": True,
        },
        "recommended_actions": {
            "weighted_score_above_30": "immediate_suspension_and_retraining",
            "weighted_score_above_15": "mandatory_retraining",
            "default": "verbal_warning_and_monitoring",
        },
    }
    with open(os.path.join(workspace, "retraining_policy.json"), "w") as f:
        json.dump(retraining, f, indent=2)

    sla = {
        "tiers": {
            "gold": {
                "violation_weight_multiplier": 2.0,
                "description": (
                    "Premium tier customers with strictest "
                    "geofence compliance requirements"
                ),
            },
            "silver": {
                "violation_weight_multiplier": 1.5,
                "description": (
                    "Standard tier customers with moderate "
                    "compliance expectations"
                ),
            },
            "bronze": {
                "violation_weight_multiplier": 1.0,
                "description": (
                    "Basic tier customers with baseline "
                    "compliance monitoring"
                ),
            },
        }
    }
    with open(os.path.join(workspace, "sla_tiers.yaml"), "w") as f:
        yaml.dump(sla, f, default_flow_style=False, sort_keys=False)

    # compliance_methodology.md — authoritative definition of the audit rules
    methodology_md = """# Fleet Geofence Compliance Methodology

This document, together with the scoring configuration
(`scoring_weights.json`), the SLA tier definitions (`sla_tiers.yaml`), and
the retraining policy (`retraining_policy.json`), is the authoritative
specification for the weekly compliance audit. The reporting week runs from
2025-01-06 through 2025-01-12 inclusive.

## Violation eligibility and adjustment factors

Only geofence violations that occurred during the reporting week are in
scope. Incident context records accompany a subset of the violations and
supply an adjustment factor that modifies the severity weight for that
particular event. Any violation whose incident context record is marked as
disputed must be excluded from all calculations entirely. When no incident
context record exists for a given violation, the default adjustment factor
specified in the scoring configuration applies instead.

## Violation penalties

Each non-disputed violation carries a penalty equal to its severity weight
(from the scoring configuration), multiplied by the violation weight
multiplier for the SLA tier of the customer where the violation occurred
(the tier is found in that customer's active contract; the multiplier per
tier is in the SLA tier definitions), then further multiplied by the
violation's adjustment factor.

## SLA breaches

For each depot, group the non-disputed violations committed by that depot's
drivers by customer. Whenever a customer's weekly violation count strictly
exceeds the maximum weekly violations permitted under their contract, that
customer is in breach. Every violation at a breached customer has its
penalty additionally multiplied by the SLA breach multiplier from the
scoring configuration. A depot's SLA breach count is the number of distinct
customers whose non-disputed weekly violation count from that depot's
drivers exceeds the contractual maximum.

## Depot compliance score

A depot's compliance score equals one hundred minus the sum of all its
violation penalties divided by the number of active drivers assigned to
that depot, floored at zero and rounded to two decimal places. If a depot
has no active drivers, treat the divisor as one.

## Risk rating

Assign a risk rating to each depot according to the risk thresholds in the
scoring configuration. A score at or above the low threshold earns a rating
of low, a score at or above the medium threshold but below the low
threshold earns medium, at or above the high threshold but below medium
earns high, and anything below that earns critical.

## Driver retraining flags

Evaluate every driver across the entire fleet. A driver is flagged if any
of the following conditions from the retraining policy configuration are
met: their total non-disputed violation count is at or above the minimum
violations threshold, their weighted severity score is at or above the
minimum weighted severity score threshold, or they have at least one
non-disputed critical-severity violation when the critical violation
auto-flag setting is enabled. The weighted severity score for a driver is
the sum of each non-disputed violation's severity weight multiplied by its
adjustment factor, rounded to two decimal places. Note that the SLA tier
multiplier and the breach multiplier do NOT apply to the weighted severity
score; they apply only to depot penalty computations.

The primary flag reason is `critical_violation` if the driver has any
non-disputed critical violations, otherwise `high_severity_score` if their
weighted severity score meets the threshold, otherwise
`excessive_violations`.

The recommended action is determined by comparing the driver's weighted
severity score against the action bands in the retraining policy: a score
strictly above thirty maps to the action configured for scores above
thirty, a score strictly above fifteen maps to the action configured for
scores above fifteen, and anything else maps to the default action.
"""
    with open(os.path.join(workspace, "compliance_methodology.md"), "w") as f:
        f.write(methodology_md)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    rpt = SCALE["rows_per_table"]

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    depots = generate_depots(conn, rpt)
    depot_ids = [d[0] for d in depots]

    drivers = generate_drivers(conn, rpt * 4, depot_ids)
    driver_ids = [d[0] for d in drivers]

    customers = generate_customers(conn, rpt * 2, depot_ids)
    customer_ids = [c[0] for c in customers]

    generate_contracts(conn, customer_ids)
    generate_gps_pings(conn, rpt * 25, driver_ids)
    generate_shift_logs(conn, rpt * 6, driver_ids)
    generate_violations(conn, rpt * 3, drivers, customers)

    generate_workspace(args.workspace, conn, SCALE["num_workspace_files"])

    conn.close()
    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")


if __name__ == "__main__":
    main()
