import argparse
import sqlite3
import os
import json
import csv
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, date

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 24,
}

REFERENCE_DATE = date(2026, 4, 20)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    fake = Faker()
    Faker.seed(42)
    np.random.seed(42)

    db_path = args.db_path
    workspace = args.workspace
    os.makedirs(workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ------------------------------------------------------------------ #
    # Table 1: customers
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id   INTEGER PRIMARY KEY,
            name          TEXT,
            email         TEXT,
            phone         TEXT,
            registration_date TEXT,
            country       TEXT,
            account_tier  TEXT
        )
    """)

    countries = [
        "US", "UK", "CA", "DE", "FR", "AU", "JP", "BR", "IN", "MX",
        "NG", "RU", "CN", "KR", "IT", "ES", "NL", "SE", "PL", "AR",
    ]
    tiers = ["standard", "premium", "gold", "platinum"]
    tier_p = [0.4, 0.3, 0.2, 0.1]

    customers = []
    for i in range(1, n_rows + 1):
        reg = fake.date_between(start_date="-3y", end_date="today")
        customers.append((
            i,
            fake.name(),
            fake.email(),
            fake.phone_number(),
            str(reg),
            str(np.random.choice(countries)),
            str(np.random.choice(tiers, p=tier_p)),
        ))
    cur.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?)", customers)

    # ------------------------------------------------------------------ #
    # Table 2: orders
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id         TEXT PRIMARY KEY,
            customer_id      INTEGER,
            order_date       TEXT,
            total_amount     REAL,
            currency         TEXT,
            status           TEXT,
            shipping_country TEXT,
            ip_address       TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        )
    """)

    statuses = ["completed", "pending_review", "processing", "cancelled", "refunded"]
    status_p = [0.40, 0.30, 0.15, 0.10, 0.05]

    orders = []
    for i in range(1, n_rows + 1):
        cid = int(np.random.randint(1, n_rows + 1))
        cust_country = customers[cid - 1][5]
        if np.random.random() < 0.15:
            others = [c for c in countries if c != cust_country]
            ship = str(np.random.choice(others))
        else:
            ship = cust_country
        orders.append((
            f"ORD-{i:05d}",
            cid,
            str(fake.date_between(start_date="-6m", end_date="today")),
            round(float(np.random.lognormal(4, 1.5)), 2),
            "USD",
            str(np.random.choice(statuses, p=status_p)),
            ship,
            fake.ipv4(),
        ))
    cur.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)", orders)

    # ------------------------------------------------------------------ #
    # Table 3: ip_geolocation_checks
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ip_geolocation_checks (
            check_id          INTEGER PRIMARY KEY,
            order_id          TEXT,
            ip_country        TEXT,
            ip_region         TEXT,
            customer_country  TEXT,
            mismatch_flag     INTEGER,
            proxy_detected    INTEGER,
            vpn_detected      INTEGER,
            confidence_score  REAL,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    """)

    ip_checks = []
    for idx, o in enumerate(orders, 1):
        cid = o[1]
        cust_country = customers[cid - 1][5]
        if np.random.random() < 0.20:
            ip_country = str(np.random.choice([c for c in countries if c != cust_country]))
            mismatch = 1
        else:
            ip_country = cust_country
            mismatch = 0
        proxy = 1 if np.random.random() < 0.08 else 0
        vpn = 1 if np.random.random() < 0.12 else 0
        ip_checks.append((
            idx, o[0], ip_country,
            fake.city(), cust_country,
            mismatch, proxy, vpn,
            round(float(np.random.uniform(0.6, 1.0)), 2),
        ))
    cur.executemany(
        "INSERT INTO ip_geolocation_checks VALUES (?,?,?,?,?,?,?,?,?)", ip_checks
    )

    # ------------------------------------------------------------------ #
    # Table 4: card_transactions
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS card_transactions (
            transaction_id    INTEGER PRIMARY KEY,
            order_id          TEXT,
            card_last_four    TEXT,
            issuer_bank       TEXT,
            decline_code      TEXT,
            response_message  TEXT,
            retry_count       INTEGER,
            authorized_amount REAL,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    """)

    decline_pool = [
        ("00", "Approved"), ("00", "Approved"), ("00", "Approved"),
        ("00", "Approved"), ("00", "Approved"),
        ("01", "Refer to issuer"),
        ("05", "Do not honor"),
        ("14", "Invalid card number"),
        ("41", "Lost card"),
        ("43", "Stolen card"),
        ("51", "Insufficient funds"),
        ("54", "Expired card"),
        ("57", "Transaction not permitted"),
        ("61", "Exceeds withdrawal limit"),
        ("65", "Activity count exceeded"),
    ]
    banks = [
        "Chase", "Bank of America", "Wells Fargo", "Citi", "Capital One",
        "Barclays", "HSBC", "Deutsche Bank", "BNP Paribas", "Santander",
    ]

    card_txns = []
    for idx, o in enumerate(orders, 1):
        pick = int(np.random.randint(0, len(decline_pool)))
        code, msg = decline_pool[pick]
        retry = int(np.random.choice([0, 1, 2, 3], p=[0.6, 0.2, 0.15, 0.05]))
        auth = o[3] if code == "00" else round(float(o[3] * np.random.uniform(0, 0.5)), 2)
        card_txns.append((
            idx, o[0],
            fake.credit_card_number()[-4:],
            str(np.random.choice(banks)),
            code, msg, retry, auth,
        ))
    cur.executemany(
        "INSERT INTO card_transactions VALUES (?,?,?,?,?,?,?,?)", card_txns
    )

    # ------------------------------------------------------------------ #
    # Table 5: address_verifications
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS address_verifications (
            verification_id     INTEGER PRIMARY KEY,
            order_id            TEXT,
            avs_response_code   TEXT,
            avs_score           INTEGER,
            street_match        INTEGER,
            zip_match           INTEGER,
            city_match          INTEGER,
            verification_status TEXT,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    """)

    addr_v = []
    for idx, o in enumerate(orders, 1):
        score = int(np.clip(np.random.normal(75, 20), 0, 100))
        street = 1 if score >= 60 else (1 if np.random.random() < 0.3 else 0)
        zipm = 1 if score >= 50 else (1 if np.random.random() < 0.4 else 0)
        citym = 1 if score >= 40 else (1 if np.random.random() < 0.5 else 0)
        if score >= 80:
            status, code = "verified", str(np.random.choice(["Y", "A"]))
        elif score >= 60:
            status, code = "partial", str(np.random.choice(["Z", "A", "G"]))
        elif score >= 40:
            status, code = "partial", str(np.random.choice(["N", "U"]))
        else:
            status, code = "failed", str(np.random.choice(["N", "R", "S"]))
        addr_v.append((idx, o[0], code, score, street, zipm, citym, status))
    cur.executemany(
        "INSERT INTO address_verifications VALUES (?,?,?,?,?,?,?,?)", addr_v
    )

    conn.commit()
    conn.close()

    # ================================================================== #
    #  WORKSPACE FILES                                                    #
    # ================================================================== #
    _build_workspace(workspace, customers, orders, n_rows, n_files)


def _build_workspace(workspace, customers, orders, n_rows, n_files):
    # Use a separate RNG so workspace data is independent of table count
    rng = np.random.RandomState(12345)

    # ------ fixed config files (not counted in SCALE) ------ #

    # 1. risk_scoring_config.yaml  (written as plain text to avoid yaml dep)
    cfg_text = """\
risk_factors:
  ip_geolocation:
    mismatch_points: 25
    proxy_vpn_points: 15
  card_issuer:
    severity_source: issuer_response_codes.json
    max_points: 20
  address_verification:
    tier_source: avs_score_tiers.csv
    max_points: 20
  customer_history:
    fraud_count_multiplier: 10
    chargeback_multiplier: 8
    new_account_threshold_days: 30
    new_account_bonus: 5
  transaction_patterns:
    rapid_order_points: 8
    unusual_amount_points: 7
    multiple_address_points: 6
thresholds:
  high_risk: 50
  medium_risk: 30
output_requirements:
  sort_by: risk_score
  sort_order: descending
  tiebreaker: order_id_ascending
  include_risk_levels:
    - HIGH
    - MEDIUM
  score_cap: 100
"""
    with open(os.path.join(workspace, "risk_scoring_config.yaml"), "w") as f:
        f.write(cfg_text)

    # 2. issuer_response_codes.json
    codes = {
        "00": {"description": "Approved", "severity": 0},
        "01": {"description": "Refer to issuer", "severity": 8},
        "05": {"description": "Do not honor", "severity": 15},
        "14": {"description": "Invalid card number", "severity": 18},
        "41": {"description": "Lost card", "severity": 20},
        "43": {"description": "Stolen card", "severity": 20},
        "51": {"description": "Insufficient funds", "severity": 3},
        "54": {"description": "Expired card", "severity": 6},
        "57": {"description": "Transaction not permitted", "severity": 12},
        "61": {"description": "Exceeds withdrawal limit", "severity": 5},
        "65": {"description": "Activity count exceeded", "severity": 7},
    }
    with open(os.path.join(workspace, "issuer_response_codes.json"), "w") as f:
        json.dump(codes, f, indent=2)

    # 3. avs_score_tiers.csv
    with open(os.path.join(workspace, "avs_score_tiers.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["min_score", "max_score", "tier", "risk_points"])
        w.writerow([90, 100, "full_match", 0])
        w.writerow([70, 89, "partial_match", 5])
        w.writerow([50, 69, "weak_match", 12])
        w.writerow([0, 49, "no_match", 20])

    # 4. verification_procedures.md
    proc = """\
# Fraud Verification Procedures

## IP Geolocation Issues

When an IP geolocation mismatch is detected, the recommended action is: "Verify customer identity via phone call and confirm shipping destination"

When proxy or VPN usage is detected, the recommended action is: "Request customer to disable VPN and retry transaction, escalate to senior analyst if refused"

## Card Issuer Concerns

When the card issuer decline severity is 10 or above, the recommended action is: "Contact card issuer for manual verification and request 3D Secure re-authentication"

When the card issuer decline severity is between 5 and 9 inclusive, the recommended action is: "Request additional cardholder identity verification"

## Address Verification Failures

When the AVS risk points are 12 or above, the recommended action is: "Place shipment on hold and confirm shipping address via registered email"

When the AVS risk points are between 5 and 11 inclusive, the recommended action is: "Send address confirmation request before dispatching"

## Customer History Red Flags

When the customer has any previous fraud incidents, the recommended action is: "Escalate to senior fraud analyst for full manual review"

When the customer has more than 2 chargebacks, the recommended action is: "Require alternative payment method or prepayment before processing"

## Transaction Pattern Anomalies

When a rapid ordering pattern is flagged, the recommended action is: "Verify order intent with customer and check for bot activity"

When an unusual transaction amount is flagged, the recommended action is: "Confirm order amount directly with customer before processing"

When multiple shipping addresses are flagged, the recommended action is: "Verify all shipping addresses on file with customer"
"""
    with open(os.path.join(workspace, "verification_procedures.md"), "w") as f:
        f.write(proc)

    # 5. fraud_review_policy.txt  (general policy document)
    policy = """\
FRAUD REVIEW POLICY — INTERNAL USE ONLY

All orders entering the manual review queue must be processed in descending
order of their composite risk score. Analysts should not skip ahead or
cherry-pick orders.

Every order classified as HIGH risk requires at least two independent
verification steps before it may be released for fulfillment. MEDIUM risk
orders require at least one verification step.

Risk scores are computed as the sum of individual risk-factor points and
are capped at the maximum value specified in the scoring configuration.
The score must be recorded as an integer.

Analysts must document the outcome of each verification step. If any step
fails, the order must be escalated to the fraud-investigations team.

This policy applies to all order channels and all customer tiers equally.
No exemptions are granted based on account tier or order history alone.
"""
    with open(os.path.join(workspace, "fraud_review_policy.txt"), "w") as f:
        f.write(policy)

    # ------ scaling data files ------ #

    # Customer risk profile data (NOT stored in DB)
    cust_risk = []
    for c in customers:
        cid = c[0]
        reg_dt = datetime.strptime(c[4], "%Y-%m-%d").date()
        age_days = (REFERENCE_DATE - reg_dt).days

        prev_fraud = int(rng.choice([0, 0, 0, 0, 0, 0, 0, 1, 1, 2]))
        chargebacks = int(rng.choice([0, 0, 0, 0, 0, 1, 1, 2, 3, 4]))
        hist_orders = int(rng.randint(1, 200))
        avg_val = round(float(rng.lognormal(4, 1)), 2)

        if prev_fraud > 0:
            tier = "elevated"
        elif chargebacks > 2:
            tier = "watch"
        elif age_days < 30:
            tier = "new"
        else:
            tier = "normal"

        cust_risk.append({
            "customer_id": cid,
            "previous_fraud_count": prev_fraud,
            "chargeback_count": chargebacks,
            "total_historical_orders": hist_orders,
            "average_order_value": avg_val,
            "account_age_days": age_days,
            "risk_tier": tier,
        })

    # Transaction pattern data (NOT stored in DB)
    txn_patterns = []
    for o in orders:
        txn_patterns.append({
            "order_id": o[0],
            "customer_id": int(o[1]),
            "rapid_order_flag": int(rng.random() < 0.10),
            "unusual_amount_flag": int(rng.random() < 0.08),
            "multiple_address_flag": int(rng.random() < 0.12),
        })

    # Split into files
    n_profile_files = n_files // 2
    n_pattern_files = n_files - n_profile_files

    # customer risk profile batches (CSV)
    _write_batches_csv(
        workspace, "customer_risk_profile_batch", cust_risk, n_profile_files
    )

    # transaction pattern batches (JSON)
    _write_batches_json(
        workspace, "transaction_pattern_batch", txn_patterns, n_pattern_files
    )


def _write_batches_csv(workspace, prefix, records, n_files):
    chunk = max(1, len(records) // n_files)
    for i in range(n_files):
        start = i * chunk
        data = records[start:] if i == n_files - 1 else records[start:start + chunk]
        df = pd.DataFrame(data)
        df.to_csv(os.path.join(workspace, f"{prefix}_{i + 1}.csv"), index=False)


def _write_batches_json(workspace, prefix, records, n_files):
    chunk = max(1, len(records) // n_files)
    for i in range(n_files):
        start = i * chunk
        data = records[start:] if i == n_files - 1 else records[start:start + chunk]
        with open(os.path.join(workspace, f"{prefix}_{i + 1}.json"), "w") as f:
            json.dump(data, f, indent=2)


if __name__ == "__main__":
    main()
