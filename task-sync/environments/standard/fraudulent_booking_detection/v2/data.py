"""
Data generation for hotel reservation fraud detection task.
Generates a SQLite database and workspace files for fraud risk assessment.
"""

import argparse
import sqlite3
import os
import json
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker


SCALE = {
    "rows_per_table": 400,        # v2 = 4x base
    "num_workspace_files": 30,    # v2 = base + 2N (10 + 20)
}

REVIEW_DATE = "2025-07-15"
SEED = 42


def main(db_path, workspace):
    np.random.seed(SEED)
    fake = Faker()
    Faker.seed(SEED)

    os.makedirs(workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # ----------------------------------------------------------------
    # Table 1: guests
    # ----------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guests (
            guest_id TEXT PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            id_document_type TEXT,
            id_document_number TEXT,
            nationality TEXT,
            phone TEXT,
            email TEXT,
            registration_date TEXT
        )
    """)

    guests = []
    doc_numbers = set()
    for i in range(1, n_rows + 1):
        doc_num = fake.bothify("??########").upper()
        while doc_num in doc_numbers:
            doc_num = fake.bothify("??########").upper()
        doc_numbers.add(doc_num)
        guests.append({
            "guest_id": f"G{i:05d}",
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "id_document_type": str(np.random.choice(["passport", "national_id", "drivers_license"])),
            "id_document_number": doc_num,
            "nationality": fake.country_code(),
            "phone": fake.phone_number(),
            "email": fake.email(),
            "registration_date": fake.date_between("-2y", "-30d").isoformat(),
        })

    cursor.executemany(
        "INSERT INTO guests VALUES (?,?,?,?,?,?,?,?,?)",
        [(g["guest_id"], g["first_name"], g["last_name"], g["id_document_type"],
          g["id_document_number"], g["nationality"], g["phone"], g["email"],
          g["registration_date"]) for g in guests]
    )

    # ----------------------------------------------------------------
    # Table 2: blacklist
    # ----------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blacklist (
            blacklist_id TEXT PRIMARY KEY,
            id_document_number TEXT,
            reason TEXT,
            severity TEXT,
            date_added TEXT,
            source TEXT
        )
    """)

    blacklist = []
    n_blacklisted = max(8, int(n_rows * 0.15))
    blacklisted_indices = np.random.choice(n_rows, n_blacklisted, replace=False)
    blacklisted_doc_nums = set()

    for i, idx in enumerate(blacklisted_indices):
        doc_num = guests[int(idx)]["id_document_number"]
        blacklisted_doc_nums.add(doc_num)
        blacklist.append({
            "blacklist_id": f"BL{i + 1:05d}",
            "id_document_number": doc_num,
            "reason": str(np.random.choice(["fraud", "identity_theft", "chargeback_abuse", "document_forgery"])),
            "severity": str(np.random.choice(["high", "medium", "low"])),
            "date_added": fake.date_between("-1y", "-1d").isoformat(),
            "source": str(np.random.choice(["internal", "police_report", "industry_database", "partner_hotel"])),
        })

    # Fill remaining blacklist entries with non-guest documents
    for i in range(n_blacklisted, n_rows):
        doc_num = fake.bothify("XX########").upper()
        while doc_num in doc_numbers or doc_num in blacklisted_doc_nums:
            doc_num = fake.bothify("XX########").upper()
        blacklist.append({
            "blacklist_id": f"BL{i + 1:05d}",
            "id_document_number": doc_num,
            "reason": str(np.random.choice(["fraud", "identity_theft", "chargeback_abuse", "document_forgery"])),
            "severity": str(np.random.choice(["high", "medium", "low"])),
            "date_added": fake.date_between("-1y", "-1d").isoformat(),
            "source": str(np.random.choice(["internal", "police_report", "industry_database", "partner_hotel"])),
        })

    cursor.executemany(
        "INSERT INTO blacklist VALUES (?,?,?,?,?,?)",
        [(b["blacklist_id"], b["id_document_number"], b["reason"],
          b["severity"], b["date_added"], b["source"]) for b in blacklist]
    )

    # ----------------------------------------------------------------
    # Table 3: payment_methods
    # ----------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_methods (
            payment_method_id TEXT PRIMARY KEY,
            guest_id TEXT,
            card_type TEXT,
            card_last_four TEXT,
            is_prepaid INTEGER,
            fraud_flag_count INTEGER,
            billing_country TEXT,
            first_used_date TEXT,
            last_used_date TEXT,
            FOREIGN KEY (guest_id) REFERENCES guests(guest_id)
        )
    """)

    payment_methods = []
    # Ensure each guest gets at least one payment method
    guest_pm_map = {}
    for i in range(1, n_rows + 1):
        # Cycle through guests, some may get multiple payment methods
        guest_idx = (i - 1) % len(guests)
        guest_id = guests[guest_idx]["guest_id"]
        pm_id = f"PM{i:05d}"
        is_prepaid = int(np.random.random() < 0.2)
        fraud_flags = int(np.random.choice([0, 0, 0, 0, 1, 1, 2, 3, 4, 5]))
        pm = {
            "payment_method_id": pm_id,
            "guest_id": guest_id,
            "card_type": str(np.random.choice(["visa", "mastercard", "amex", "discover"])),
            "card_last_four": fake.numerify("####"),
            "is_prepaid": is_prepaid,
            "fraud_flag_count": fraud_flags,
            "billing_country": fake.country_code(),
            "first_used_date": fake.date_between("-2y", "-60d").isoformat(),
            "last_used_date": fake.date_between("-59d", "-1d").isoformat(),
        }
        payment_methods.append(pm)
        if guest_id not in guest_pm_map:
            guest_pm_map[guest_id] = []
        guest_pm_map[guest_id].append(pm_id)

    cursor.executemany(
        "INSERT INTO payment_methods VALUES (?,?,?,?,?,?,?,?,?)",
        [(p["payment_method_id"], p["guest_id"], p["card_type"], p["card_last_four"],
          p["is_prepaid"], p["fraud_flag_count"], p["billing_country"],
          p["first_used_date"], p["last_used_date"]) for p in payment_methods]
    )

    # ----------------------------------------------------------------
    # Table 4: reservations
    # ----------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            reservation_id TEXT PRIMARY KEY,
            guest_id TEXT,
            payment_method_id TEXT,
            room_type TEXT,
            check_in_date TEXT,
            check_out_date TEXT,
            booking_date TEXT,
            amount REAL,
            status TEXT,
            FOREIGN KEY (guest_id) REFERENCES guests(guest_id),
            FOREIGN KEY (payment_method_id) REFERENCES payment_methods(payment_method_id)
        )
    """)

    review_dt = pd.Timestamp(REVIEW_DATE)
    n_review = max(20, int(n_rows * 0.25))

    reservations = []
    for i in range(1, n_rows + 1):
        guest_idx = np.random.randint(0, len(guests))
        guest_id = guests[guest_idx]["guest_id"]

        # Pick a payment method belonging to this guest if possible
        if guest_id in guest_pm_map:
            pm_id = str(np.random.choice(guest_pm_map[guest_id]))
        else:
            pm_id = payment_methods[np.random.randint(0, len(payment_methods))]["payment_method_id"]

        if i <= n_review:
            check_in = REVIEW_DATE
            status = str(np.random.choice(["confirmed", "pending"]))
        else:
            offset = int(np.random.choice(list(range(-30, 0)) + list(range(1, 31))))
            check_in = (review_dt + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")
            status = str(np.random.choice(["confirmed", "checked_in", "cancelled", "completed", "pending"]))

        stay_days = int(np.random.randint(1, 8))
        check_out = (pd.Timestamp(check_in) + pd.Timedelta(days=stay_days)).strftime("%Y-%m-%d")
        booking_days_before = int(np.random.randint(1, 60))
        booking_date = (pd.Timestamp(check_in) - pd.Timedelta(days=booking_days_before)).strftime("%Y-%m-%d")
        amount = round(float(np.random.uniform(80, 600)), 2)

        reservations.append({
            "reservation_id": f"R{i:05d}",
            "guest_id": guest_id,
            "payment_method_id": pm_id,
            "room_type": str(np.random.choice(["standard", "deluxe", "suite", "economy"])),
            "check_in_date": check_in,
            "check_out_date": check_out,
            "booking_date": booking_date,
            "amount": amount,
            "status": status,
        })

    cursor.executemany(
        "INSERT INTO reservations VALUES (?,?,?,?,?,?,?,?,?)",
        [(r["reservation_id"], r["guest_id"], r["payment_method_id"], r["room_type"],
          r["check_in_date"], r["check_out_date"], r["booking_date"], r["amount"],
          r["status"]) for r in reservations]
    )

    # ----------------------------------------------------------------
    # Table 5: no_show_records
    # ----------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS no_show_records (
            record_id TEXT PRIMARY KEY,
            guest_id TEXT,
            reservation_id TEXT,
            no_show_date TEXT,
            penalty_amount REAL,
            FOREIGN KEY (guest_id) REFERENCES guests(guest_id)
        )
    """)

    no_show_records = []
    for i in range(1, n_rows + 1):
        guest_idx = int(np.random.randint(0, len(guests)))
        no_show_records.append({
            "record_id": f"NS{i:05d}",
            "guest_id": guests[guest_idx]["guest_id"],
            "reservation_id": f"R{int(np.random.randint(1, n_rows + 1)):05d}",
            "no_show_date": fake.date_between("-1y", "-1d").isoformat(),
            "penalty_amount": round(float(np.random.uniform(20, 200)), 2),
        })

    cursor.executemany(
        "INSERT INTO no_show_records VALUES (?,?,?,?,?)",
        [(ns["record_id"], ns["guest_id"], ns["reservation_id"],
          ns["no_show_date"], ns["penalty_amount"]) for ns in no_show_records]
    )

    conn.commit()
    conn.close()

    # ================================================================
    # Workspace files
    # ================================================================

    # --- Fixed files (not part of SCALE["num_workspace_files"]) ---

    # Fraud scoring configuration
    scoring_config = {
        "scoring_weights": {
            "blacklist_match": 35,
            "high_chargeback_ratio": 10,
            "high_fraud_flags": 15,
            "low_scan_confidence": 10,
            "no_show_history": 15,
            "prepaid_card": 10,
            "rapid_booking": 5,
        },
        "thresholds": {
            "fraud_flag_count_min": 2,
            "no_show_count_min": 2,
            "scan_confidence_min": 0.75,
            "chargeback_ratio_min": 0.3,
            "rapid_booking_min": 3,
            "risk_score_cutoff": 30,
        },
        "review_date": REVIEW_DATE,
    }

    # Write YAML manually to avoid pyyaml dependency
    yaml_lines = []
    yaml_lines.append("scoring_weights:")
    for k, v in scoring_config["scoring_weights"].items():
        yaml_lines.append(f"  {k}: {v}")
    yaml_lines.append("")
    yaml_lines.append("thresholds:")
    for k, v in scoring_config["thresholds"].items():
        yaml_lines.append(f"  {k}: {v}")
    yaml_lines.append("")
    yaml_lines.append(f"review_date: \"{REVIEW_DATE}\"")
    yaml_lines.append("")

    with open(os.path.join(workspace, "fraud_scoring_rules.yaml"), "w") as f:
        f.write("\n".join(yaml_lines))

    # Review policy document
    policy_text = """# Daily Fraud Review Policy

All reservations with check-in scheduled on the configured review date must undergo
a comprehensive risk assessment before guest arrival. The security team relies on
the daily review list to prioritize inspections and allocate resources.

Each reservation is scored individually against multiple risk indicators. The scoring
weights and activation thresholds are maintained in the scoring configuration file
and must not be overridden manually. If a risk factor's precondition is met for a
given reservation, its full weight is added to that reservation's total score.

Risk factors are evaluated independently; a single reservation may trigger any
combination of factors. The total risk score is the arithmetic sum of all triggered
factor weights.

Reservations meeting or exceeding the risk score cutoff must appear on the review
list. Those falling below the cutoff are excluded regardless of any individual
factor match.

Priority classification:
- A score of 60 or above warrants critical priority and immediate investigation.
- All other entries on the review list receive high priority.

The review list must be delivered as a structured file for integration with the
security dashboard. Accurate sorting by descending risk score ensures the most
urgent cases surface first.
"""
    with open(os.path.join(workspace, "review_policy.md"), "w") as f:
        f.write(policy_text)

    # --- Scalable workspace files ---
    # Distribution: 40% JSON (identity scans), 30% CSV (transaction logs), 30% TXT (booking patterns)
    n_json = max(1, round(n_files * 0.4))
    n_csv = max(1, round(n_files * 0.3))
    n_txt = n_files - n_json - n_csv

    # ----- Identity scan batch files (JSON) -----
    # Generate scan data for ALL guests, distributed across files
    np.random.seed(SEED + 100)  # Separate seed stream for workspace data
    scan_data_all = []
    for g in guests:
        confidence = round(float(np.random.beta(5, 2)), 4)  # Most scans are decent
        # Ensure some low-confidence scans
        if np.random.random() < 0.15:
            confidence = round(float(np.random.uniform(0.3, 0.74)), 4)
        scan_data_all.append({
            "guest_id": g["guest_id"],
            "document_number": g["id_document_number"],
            "scan_date": fake.date_between("-60d", "-1d").isoformat(),
            "scan_confidence": confidence,
            "document_verified": confidence >= 0.5,
        })

    # Shuffle and split across files
    np.random.shuffle(scan_data_all)
    scan_chunks = np.array_split(scan_data_all, n_json)
    for idx, chunk in enumerate(scan_chunks):
        fname = f"identity_scan_batch_{idx + 1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(list(chunk), f, indent=2, default=str)

    # ----- Transaction log files (CSV) -----
    # Generate transactions for ALL payment methods
    np.random.seed(SEED + 200)
    all_transactions = []
    txn_counter = 1
    for pm in payment_methods:
        n_txns = int(np.random.randint(5, 15))
        n_chargebacks = 0
        if np.random.random() < 0.2:
            n_chargebacks = int(np.random.randint(1, max(2, n_txns // 2)))

        for t in range(n_txns):
            is_cb = 1 if t < n_chargebacks else 0
            all_transactions.append({
                "transaction_id": f"TXN{txn_counter:07d}",
                "payment_method_id": pm["payment_method_id"],
                "transaction_date": fake.date_between("-180d", "-1d").isoformat(),
                "amount": round(float(np.random.uniform(10, 500)), 2),
                "merchant_category": str(np.random.choice([
                    "hotel", "restaurant", "retail", "online", "travel", "entertainment"
                ])),
                "is_chargeback": is_cb,
                "cross_border": int(np.random.random() < 0.3),
            })
            txn_counter += 1

    np.random.shuffle(all_transactions)
    txn_chunks = np.array_split(all_transactions, n_csv)
    for idx, chunk in enumerate(txn_chunks):
        fname = f"transaction_log_{idx + 1:03d}.csv"
        filepath = os.path.join(workspace, fname)
        chunk_list = list(chunk)
        if chunk_list:
            with open(filepath, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "transaction_id", "payment_method_id", "transaction_date",
                    "amount", "merchant_category", "is_chargeback", "cross_border"
                ])
                writer.writeheader()
                writer.writerows(chunk_list)

    # ----- Booking pattern summary files (TXT) -----
    # Compute booking counts per guest within a 60-day window around review date
    np.random.seed(SEED + 300)
    window_start = (review_dt - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    window_end = (review_dt + pd.Timedelta(days=30)).strftime("%Y-%m-%d")

    guest_booking_counts = {}
    for r in reservations:
        if window_start <= r["check_in_date"] <= window_end:
            gid = r["guest_id"]
            guest_booking_counts[gid] = guest_booking_counts.get(gid, 0) + 1

    booking_pattern_entries = []
    for g in guests:
        gid = g["guest_id"]
        count = guest_booking_counts.get(gid, 0)
        rapid = "yes" if count >= scoring_config["thresholds"]["rapid_booking_min"] else "no"
        booking_pattern_entries.append({
            "guest_id": gid,
            "window_start": window_start,
            "window_end": window_end,
            "total_bookings": count,
            "flagged_rapid": rapid,
        })

    np.random.shuffle(booking_pattern_entries)
    pattern_chunks = np.array_split(booking_pattern_entries, n_txt)
    for idx, chunk in enumerate(pattern_chunks):
        fname = f"booking_pattern_{idx + 1:03d}.txt"
        filepath = os.path.join(workspace, fname)
        lines = []
        for entry in chunk:
            lines.append(f"GUEST_ID: {entry['guest_id']}")
            lines.append(f"REVIEW_WINDOW: {entry['window_start']} to {entry['window_end']}")
            lines.append(f"TOTAL_BOOKINGS: {entry['total_bookings']}")
            lines.append(f"FLAGGED_RAPID: {entry['flagged_rapid']}")
            lines.append("---")
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
