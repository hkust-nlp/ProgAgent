"""
data.py  --  Generate database and workspace for roaming-charge dispute task.
Usage:  python data.py --db_path data.db --workspace workspace
"""

import argparse
import sqlite3
import os
import json
import csv
import random
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

# ── Scale Configuration ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 80,       # v0 base; v1=2x, v2=4x, v3=8x
    "num_workspace_files": 8,   # v0 base; v1=+N, v2=+2N, v3=+3N
}

# ── Domain Constants ─────────────────────────────────────────────────
COUNTRY_COORDS = {
    "USA": (38.90, -77.04), "UK": (51.51, -0.13),
    "Germany": (52.52, 13.41), "France": (48.86, 2.35),
    "Japan": (35.68, 139.69), "Australia": (-33.87, 151.21),
    "Canada": (45.42, -75.70), "Brazil": (-15.79, -47.88),
    "India": (28.61, 77.21), "South Korea": (37.57, 126.98),
    "Italy": (41.90, 12.50), "Spain": (40.42, -3.70),
    "Mexico": (19.43, -99.13), "Netherlands": (52.37, 4.90),
    "Sweden": (59.33, 18.07),
}

PARTNER_CARRIERS = [
    "GlobalTel", "EuroConnect", "AsiaLink", "PacificNet", "AmericasMobile",
    "NordicComm", "MediterraneanTel", "TransAtlantic", "IndoPacific", "LatAmCell",
]

ZONES = {
    "Zone_A": ["USA", "Canada", "UK"],
    "Zone_B": ["Germany", "France", "Netherlands", "Sweden", "Italy", "Spain"],
    "Zone_C": ["Japan", "South Korea", "Australia"],
    "Zone_D": ["Brazil", "Mexico", "India"],
}

ZONE_BASE_RATES = {
    "Zone_A": {"voice": 0.15, "data": 0.05, "sms": 0.10},
    "Zone_B": {"voice": 0.25, "data": 0.08, "sms": 0.15},
    "Zone_C": {"voice": 0.35, "data": 0.12, "sms": 0.20},
    "Zone_D": {"voice": 0.45, "data": 0.15, "sms": 0.25},
}

HOME_COUNTRIES = ["USA", "UK", "Germany", "France", "Canada"]
PLAN_TYPES = ["basic", "premium", "enterprise"]


def _country_to_zone(country):
    for zone, countries in ZONES.items():
        if country in countries:
            return zone
    return "Zone_D"


# ── Main ─────────────────────────────────────────────────────────────
def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]
    all_countries = list(COUNTRY_COORDS.keys())

    # ────────────────────────────────────────────────────────────────
    # 1.  SUBSCRIBERS
    # ────────────────────────────────────────────────────────────────
    cur.execute("""CREATE TABLE subscribers (
        subscriber_id TEXT PRIMARY KEY, name TEXT, phone TEXT,
        home_country TEXT, plan_type TEXT, registration_date TEXT)""")

    subscribers = []
    for i in range(n_rows):
        subscribers.append((
            f"S{i+1:04d}",
            fake.name(),
            fake.phone_number(),
            HOME_COUNTRIES[i % len(HOME_COUNTRIES)],
            PLAN_TYPES[i % len(PLAN_TYPES)],
            fake.date_between(
                start_date=datetime(2022, 1, 1),
                end_date=datetime(2024, 6, 30),
            ).isoformat(),
        ))
    cur.executemany("INSERT INTO subscribers VALUES (?,?,?,?,?,?)", subscribers)

    # helper: subscriber lookup
    sub_by_id = {s[0]: s for s in subscribers}

    # ────────────────────────────────────────────────────────────────
    # 2.  TARIFF AGREEMENTS
    # ────────────────────────────────────────────────────────────────
    cur.execute("""CREATE TABLE tariff_agreements (
        agreement_id TEXT PRIMARY KEY, partner_carrier TEXT, zone TEXT,
        voice_rate_per_min REAL, data_rate_per_mb REAL, sms_rate REAL,
        effective_date TEXT, expiry_date TEXT, currency TEXT)""")

    tariffs = []
    ta_idx = 0

    # Current agreements: every carrier x every zone
    for ci, carrier in enumerate(PARTNER_CARRIERS):
        for zone_name in sorted(ZONES.keys()):
            base = ZONE_BASE_RATES[zone_name]
            factor = 1.0 + (ci * 3 % 20) / 100.0
            tariffs.append((
                f"TA{ta_idx+1:04d}", carrier, zone_name,
                round(base["voice"] * factor, 4),
                round(base["data"] * factor, 4),
                round(base["sms"] * factor, 4),
                "2025-01-01", "2027-12-31", "USD",
            ))
            ta_idx += 1

    # Expired agreements (higher rates) to fill up to n_rows
    for ci, carrier in enumerate(PARTNER_CARRIERS):
        for zone_name in sorted(ZONES.keys()):
            if ta_idx >= n_rows:
                break
            base = ZONE_BASE_RATES[zone_name]
            factor = 1.35 + (ci * 5 % 25) / 100.0
            tariffs.append((
                f"TA{ta_idx+1:04d}", carrier, zone_name,
                round(base["voice"] * factor, 4),
                round(base["data"] * factor, 4),
                round(base["sms"] * factor, 4),
                "2024-01-01", "2025-08-31", "USD",
            ))
            ta_idx += 1
        if ta_idx >= n_rows:
            break

    cur.executemany(
        "INSERT INTO tariff_agreements VALUES (?,?,?,?,?,?,?,?,?)", tariffs
    )

    # lookup helpers
    current_tariff = {}
    for t in tariffs:
        key = (t[1], t[2])  # (carrier, zone)
        exp = datetime.strptime(t[7], "%Y-%m-%d")
        if exp > datetime(2026, 1, 1):
            current_tariff[key] = t

    def _correct_amount(carrier, zone, dur, data_mb, sms):
        t = current_tariff.get((carrier, zone))
        if t:
            return round(dur * t[3] + data_mb * t[4] + sms * t[5], 2)
        b = ZONE_BASE_RATES.get(zone, ZONE_BASE_RATES["Zone_D"])
        return round(dur * b["voice"] + data_mb * b["data"] + sms * b["sms"], 2)

    # ────────────────────────────────────────────────────────────────
    # 3.  ERROR PLANNING
    # ────────────────────────────────────────────────────────────────
    n_open = max(20, n_rows // 4)
    n_erroneous = max(12, int(n_open * 0.6))

    n_rate = n_erroneous * 5 // 12
    n_home = n_erroneous * 4 // 12
    n_dup = n_erroneous - n_rate - n_home
    # guarantee minimums
    if n_rate < 4:
        n_rate = 4
    if n_home < 3:
        n_home = 3
    if n_dup < 2:
        n_dup = 2
    # re-adjust to total
    total_assigned = n_rate + n_home + n_dup
    if total_assigned > n_erroneous:
        n_rate = n_erroneous - n_home - n_dup
    elif total_assigned < n_erroneous:
        n_rate += n_erroneous - total_assigned

    error_list = (
        ["rate_overcharge"] * n_rate
        + ["not_roaming"] * n_home
        + ["duplicate_charge"] * n_dup
    )
    random.shuffle(error_list)

    # ────────────────────────────────────────────────────────────────
    # 4.  ROAMING LOGS
    # ────────────────────────────────────────────────────────────────
    cur.execute("""CREATE TABLE roaming_logs (
        log_id TEXT PRIMARY KEY, subscriber_id TEXT, event_timestamp TEXT,
        visited_country TEXT, partner_carrier TEXT,
        call_duration_min REAL, data_usage_mb REAL, sms_count INTEGER,
        billed_amount REAL, billing_currency TEXT,
        FOREIGN KEY (subscriber_id) REFERENCES subscribers(subscriber_id))""")

    base_date = datetime(2025, 9, 1)
    logs = []
    error_map = {}        # log_id -> error_type (only for open disputes)
    loc_records = []      # location pings for workspace
    charge_ref_map = {}   # log_id -> charge_reference

    for i in range(n_rows):
        log_id = f"RL{i+1:05d}"
        sub = subscribers[i % len(subscribers)]
        sub_id, sub_name, _, sub_home = sub[0], sub[1], sub[2], sub[3]

        dur = round(random.uniform(2, 40), 2)
        data_mb = round(random.uniform(5, 400), 2)
        sms = random.randint(0, 15)

        visited = random.choice([c for c in all_countries if c != sub_home])
        zone = _country_to_zone(visited)
        carrier = PARTNER_CARRIERS[random.randint(0, len(PARTNER_CARRIERS) - 1)]

        ts = base_date + timedelta(
            days=random.randint(0, 45),
            hours=random.randint(6, 22),
            minutes=random.randint(0, 59),
        )
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")

        correct = _correct_amount(carrier, zone, dur, data_mb, sms)
        billed = correct
        actual_country = visited
        error_type = "none"

        if i < n_erroneous:
            error_type = error_list[i]
            if error_type == "rate_overcharge":
                factor = round(random.uniform(1.15, 1.80), 4)
                billed = round(correct * factor, 2)
            elif error_type == "not_roaming":
                actual_country = sub_home
                # billed stays at roaming rate; charge should not exist
            # duplicate_charge: billed stays correct; copy created later
        elif i < n_open:
            error_type = "none"

        error_map[log_id] = error_type

        # Location pings (near event time)
        actual_coords = COUNTRY_COORDS.get(actual_country, (0, 0))
        for offset_min in [0, random.randint(-50, -5), random.randint(5, 50)]:
            ping_ts = (ts + timedelta(minutes=offset_min)).strftime("%Y-%m-%d %H:%M:%S")
            loc_records.append({
                "subscriber_id": sub_id,
                "timestamp": ping_ts,
                "latitude": round(actual_coords[0] + random.uniform(-0.3, 0.3), 4),
                "longitude": round(actual_coords[1] + random.uniform(-0.3, 0.3), 4),
                "detected_country": actual_country,
                "signal_source": random.choice(["gps", "cell_tower", "wifi"]),
            })

        # Charge reference
        ref = f"CHG-{ts.strftime('%Y%m%d')}-{random.randint(10000, 99999)}"
        charge_ref_map[log_id] = ref

        logs.append(
            (log_id, sub_id, ts_str, visited, carrier,
             dur, data_mb, sms, billed, "USD")
        )

    # ── duplicate copies ──
    dup_map = {}  # original_log_id -> copy_log_id
    dup_extra = []
    for log_id, etype in error_map.items():
        if etype != "duplicate_charge":
            continue
        orig = next(l for l in logs if l[0] == log_id)
        copy_id = f"RL{n_rows + len(dup_extra) + 1:05d}"
        dup_extra.append((copy_id,) + orig[1:])
        dup_map[log_id] = copy_id
        ts_date = orig[2].split(" ")[0].replace("-", "")
        charge_ref_map[copy_id] = f"CHG-{ts_date}-{random.randint(10000, 99999)}"

    logs.extend(dup_extra)
    cur.executemany("INSERT INTO roaming_logs VALUES (?,?,?,?,?,?,?,?,?,?)", logs)

    # ────────────────────────────────────────────────────────────────
    # 5.  DISPUTE TICKETS
    # ────────────────────────────────────────────────────────────────
    cur.execute("""CREATE TABLE dispute_tickets (
        ticket_id TEXT PRIMARY KEY, subscriber_id TEXT, roaming_log_id TEXT,
        dispute_reason TEXT, status TEXT, filed_date TEXT,
        amount_disputed REAL,
        FOREIGN KEY (subscriber_id) REFERENCES subscribers(subscriber_id),
        FOREIGN KEY (roaming_log_id) REFERENCES roaming_logs(log_id))""")

    reason_text = {
        "rate_overcharge": "Charged amount appears higher than expected rate",
        "not_roaming": "Was not traveling abroad during this period",
        "duplicate_charge": "Appears to be a duplicate charge for same usage",
        "none": "Believe the roaming charge is incorrect",
    }

    disputes = []
    ground_truth = []
    ticket_idx = 0
    disputed_log_ids = set()

    # -- open / pending_review disputes (first n_open logs)
    for i in range(n_open):
        log = logs[i]
        log_id = log[0]
        etype = error_map.get(log_id, "none")
        ticket_id = f"DT{ticket_idx+1:05d}"
        reason = reason_text.get(etype, reason_text["none"])
        status = "open" if random.random() < 0.6 else "pending_review"
        filed = (
            datetime.strptime(log[2], "%Y-%m-%d %H:%M:%S")
            + timedelta(days=random.randint(1, 14))
        ).strftime("%Y-%m-%d")
        disputes.append(
            (ticket_id, log[1], log_id, reason, status, filed, log[8])
        )
        disputed_log_ids.add(log_id)

        # ground truth
        sub = sub_by_id[log[1]]
        zone = _country_to_zone(log[3])
        correct = _correct_amount(log[4], zone, log[5], log[6], log[7])

        if etype == "rate_overcharge":
            refund = round(log[8] - correct, 2)
            gt_log_id = log_id
        elif etype == "not_roaming":
            correct = 0.0
            refund = log[8]
            gt_log_id = log_id
        elif etype == "duplicate_charge":
            copy_id = dup_map[log_id]
            correct = 0.0
            refund = log[8]
            gt_log_id = copy_id
        else:
            correct = log[8]
            refund = 0.0
            gt_log_id = log_id

        ground_truth.append((
            ticket_id, gt_log_id, log[1], sub[1], etype,
            log[8], correct, refund,
            charge_ref_map.get(gt_log_id, ""),
        ))
        ticket_idx += 1

    # -- resolved / rejected disputes (fill to n_rows)
    remaining = [l for l in logs if l[0] not in disputed_log_ids]
    for i in range(n_rows - n_open):
        log = remaining[i % len(remaining)]
        ticket_id = f"DT{ticket_idx+1:05d}"
        status = random.choice(["resolved", "rejected"])
        filed = (
            datetime.strptime(log[2], "%Y-%m-%d %H:%M:%S")
            + timedelta(days=random.randint(1, 30))
        ).strftime("%Y-%m-%d")
        disputes.append(
            (ticket_id, log[1], log[0],
             "Previously disputed charge", status, filed, log[8])
        )
        ticket_idx += 1

    cur.executemany(
        "INSERT INTO dispute_tickets VALUES (?,?,?,?,?,?,?)", disputes
    )

    # ── ground-truth table (hidden from agent) ──
    cur.execute("""CREATE TABLE ground_truth (
        ticket_id TEXT, log_id TEXT, subscriber_id TEXT, subscriber_name TEXT,
        error_type TEXT, billed_amount REAL, correct_amount REAL,
        refund_amount REAL, charge_reference TEXT)""")
    cur.executemany(
        "INSERT INTO ground_truth VALUES (?,?,?,?,?,?,?,?,?)", ground_truth
    )

    conn.commit()
    conn.close()

    # ────────────────────────────────────────────────────────────────
    # 6.  WORKSPACE FILES  (scalable)
    # ────────────────────────────────────────────────────────────────
    n_json = max(1, n_files * 3 // 8)
    n_csv = max(1, n_files * 3 // 8)
    n_txt = max(1, n_files - n_json - n_csv)

    # ── location_records_XX.json ──
    random.shuffle(loc_records)
    for fi in range(n_json):
        start = fi * len(loc_records) // n_json
        end = (
            len(loc_records) if fi == n_json - 1
            else (fi + 1) * len(loc_records) // n_json
        )
        path = os.path.join(workspace, f"location_records_{fi+1:02d}.json")
        with open(path, "w") as f:
            json.dump(loc_records[start:end], f, indent=2)

    # ── charge_references_XX.csv ──
    all_refs = list(charge_ref_map.items())
    random.shuffle(all_refs)
    for fi in range(n_csv):
        start = fi * len(all_refs) // n_csv
        end = (
            len(all_refs) if fi == n_csv - 1
            else (fi + 1) * len(all_refs) // n_csv
        )
        path = os.path.join(workspace, f"charge_references_{fi+1:02d}.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["log_id", "charge_reference", "invoice_id"])
            for lid, ref in all_refs[start:end]:
                inv = f"INV-{ref.split('-')[1]}-{random.randint(1000, 9999)}"
                w.writerow([lid, ref, inv])

    # ── dispute_notes_XX.txt ──
    open_disputes = [d for d in disputes if d[4] in ("open", "pending_review")]
    for fi in range(n_txt):
        start = fi * len(open_disputes) // n_txt
        end = (
            len(open_disputes) if fi == n_txt - 1
            else (fi + 1) * len(open_disputes) // n_txt
        )
        path = os.path.join(workspace, f"dispute_notes_{fi+1:02d}.txt")
        with open(path, "w") as f:
            for d in open_disputes[start:end]:
                f.write(f"Ticket: {d[0]}\n")
                f.write(f"Subscriber: {d[1]}\n")
                f.write(f"Log Reference: {d[2]}\n")
                f.write(f"Reason: {d[3]}\n")
                f.write(f"Amount Disputed: ${d[6]:.2f}\n")
                f.write(f"Filed: {d[5]}\n")
                f.write("-" * 40 + "\n\n")

    # ────────────────────────────────────────────────────────────────
    # 7.  WORKSPACE FILES  (fixed config / policy)
    # ────────────────────────────────────────────────────────────────

    # billing_rules.yaml
    with open(os.path.join(workspace, "billing_rules.yaml"), "w") as f:
        f.write("rate_overcharge_tolerance_pct: 5.0\n")
        f.write("duplicate_check_window_minutes: 5\n")
        f.write("location_check_window_minutes: 60\n")
        f.write("minimum_refund_amount: 1.00\n")

    # carrier_zones.json
    with open(os.path.join(workspace, "carrier_zones.json"), "w") as f:
        json.dump(ZONES, f, indent=2)

    # refund_policy.md
    with open(os.path.join(workspace, "refund_policy.md"), "w") as f:
        f.write(
            "Refund Policy for Roaming Charge Disputes\n"
            "==========================================\n\n"
            "A roaming charge dispute is eligible for investigation when the\n"
            "ticket status is \"open\" or \"pending_review\".\n\n"
            "Error Type: rate_overcharge\n"
            "When the billed amount exceeds the correctly calculated charge\n"
            "(based on the current partner carrier tariff agreement for the\n"
            "applicable billing zone) by more than the tolerance percentage\n"
            "specified in the billing rules configuration, the charge is\n"
            "classified as a rate overcharge. The refund amount equals the\n"
            "difference between the billed amount and the correctly calculated\n"
            "amount.\n\n"
            "The correctly calculated amount is computed as:\n"
            "  (call_duration_min x voice_rate_per_min)\n"
            "  + (data_usage_mb x data_rate_per_mb)\n"
            "  + (sms_count x sms_rate)\n"
            "using the rates from the tariff agreement that is valid on the\n"
            "date of the roaming event for the given partner carrier and\n"
            "billing zone.\n\n"
            "Error Type: not_roaming\n"
            "When location tracking data confirms the subscriber was in their\n"
            "home country at the time the roaming charge was incurred, the\n"
            "full billed amount is refundable. Location verification requires\n"
            "at least one location record within the time window specified in\n"
            "the billing rules showing the subscriber in their home country.\n\n"
            "Error Type: duplicate_charge\n"
            "When two or more roaming log entries exist for the same\n"
            "subscriber with identical event timestamps and identical usage\n"
            "details (same call duration, data usage, and SMS count), only\n"
            "one charge is valid. The entry with the higher log ID is\n"
            "considered the duplicate. The refund amount for a duplicate\n"
            "equals its full billed amount. In the refund list, use the\n"
            "ticket ID of the dispute that surfaced the duplicate, and the\n"
            "log ID of the duplicate entry (the one with the higher ID).\n\n"
            "Only charges where an actual billing error is confirmed should\n"
            "appear in the refund list. Disputes where investigation shows\n"
            "the original charge was correct must not be included.\n\n"
            "All monetary amounts in the refund list must be rounded to two\n"
            "decimal places.\n"
        )

    print(f"Database written to {db_path}")
    print(f"Workspace written to {workspace}/")
    print(f"  Scalable files: {n_json} JSON + {n_csv} CSV + {n_txt} TXT = {n_files}")
    print(f"  Fixed files:    billing_rules.yaml, carrier_zones.json, refund_policy.md")
    print(f"  Subscribers:    {n_rows}")
    print(f"  Tariff agmts:   {len(tariffs)}")
    print(f"  Roaming logs:   {len(logs)}")
    print(f"  Disputes:       {len(disputes)} ({n_open} open, {n_erroneous} erroneous)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
