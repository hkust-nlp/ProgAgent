"""Benefit overpayment detection — data generation script."""
import argparse
import json
import math
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yaml
from faker import Faker

# ---------------------------------------------------------------------------
# Scale parameters (only this block differs across v0 – v3)
# ---------------------------------------------------------------------------
SCALE = {
    "rows_per_table": 400,      # v3 = 8 × base
    "num_workspace_files": 32,  # v3 = base + 3N
}

# ---------------------------------------------------------------------------
# Deterministic seeds
# ---------------------------------------------------------------------------
random.seed(42)
np.random.seed(42)
Faker.seed(42)
fake = Faker()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BENEFIT_TYPES = [
    "unemployment",
    "disability",
    "housing_assistance",
    "food_assistance",
    "childcare_subsidy",
]
REGIONS = ["Northeast", "Southeast", "Midwest", "Southwest", "Northwest", "Central"]
REVIEW_MONTHS = ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06"]
EMPLOYER_POOL: list = []  # filled once in main

BENEFIT_AMOUNT_RANGES = {
    "unemployment":       (800,  2200),
    "disability":         (1000, 2800),
    "housing_assistance": (500,  1500),
    "food_assistance":    (200,  650),
    "childcare_subsidy":  (400,  1200),
}

MAX_MONTHLY_INCOME = {
    "unemployment":       500,
    "disability":         1350,
    "housing_assistance": 2000,
    "food_assistance":    1800,
    "childcare_subsidy":  2500,
}

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def create_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recipients (
            id                    INTEGER PRIMARY KEY,
            name                  TEXT    NOT NULL,
            ssn_last4             TEXT    NOT NULL,
            date_of_birth         TEXT    NOT NULL,
            benefit_type          TEXT    NOT NULL,
            monthly_benefit_amount REAL   NOT NULL,
            enrollment_date       TEXT    NOT NULL,
            account_status        TEXT    NOT NULL,
            region                TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS benefit_payments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_id  INTEGER NOT NULL,
            payment_date  TEXT    NOT NULL,
            amount        REAL    NOT NULL,
            period_month  TEXT    NOT NULL,
            status        TEXT    NOT NULL,
            FOREIGN KEY (recipient_id) REFERENCES recipients(id)
        );
        CREATE TABLE IF NOT EXISTS employment_updates (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_id            INTEGER NOT NULL,
            employer_name           TEXT    NOT NULL,
            employment_status       TEXT    NOT NULL,
            reported_monthly_salary REAL    NOT NULL,
            effective_date          TEXT    NOT NULL,
            source_hub              TEXT    NOT NULL,
            FOREIGN KEY (recipient_id) REFERENCES recipients(id)
        );
        CREATE TABLE IF NOT EXISTS bank_transaction_alerts (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_id       INTEGER NOT NULL,
            alert_date         TEXT    NOT NULL,
            deposit_amount     REAL    NOT NULL,
            source_description TEXT    NOT NULL,
            account_type       TEXT    NOT NULL,
            FOREIGN KEY (recipient_id) REFERENCES recipients(id)
        );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Data generators
# ---------------------------------------------------------------------------
def generate_recipients(n: int) -> list[dict]:
    recipients = []
    for i in range(1, n + 1):
        bt = random.choice(BENEFIT_TYPES)
        lo, hi = BENEFIT_AMOUNT_RANGES[bt]
        monthly = round(random.uniform(lo, hi), 2)
        enrollment = fake.date_between(start_date="-3y", end_date="-6m")
        status = random.choices(
            ["active", "suspended", "closed"], weights=[0.78, 0.12, 0.10]
        )[0]
        recipients.append(
            {
                "id": i,
                "name": fake.name(),
                "ssn_last4": fake.numerify("####"),
                "date_of_birth": fake.date_of_birth(
                    minimum_age=21, maximum_age=67
                ).isoformat(),
                "benefit_type": bt,
                "monthly_benefit_amount": monthly,
                "enrollment_date": enrollment.isoformat(),
                "account_status": status,
                "region": random.choice(REGIONS),
            }
        )
    return recipients


def classify_recipients(recipients: list[dict]) -> dict:
    """Decide which active recipients are dishonest & assign intended flag types."""
    active = [r for r in recipients if r["account_status"] == "active"]
    num_dishonest = max(5, int(len(active) * 0.30))
    dishonest_ids = set(r["id"] for r in random.sample(active, num_dishonest))

    classification: dict = {}
    for r in recipients:
        rid = r["id"]
        if rid in dishonest_ids:
            possible = []
            if r["benefit_type"] == "unemployment":
                possible.append("EMPLOYMENT_MISMATCH")
            possible += ["INCOME_OVER_LIMIT", "UNDECLARED_DEPOSITS"]
            k = min(random.choices([1, 2, len(possible)], weights=[0.35, 0.45, 0.20])[0],
                    len(possible))
            flags = random.sample(possible, k)
            classification[rid] = {"dishonest": True, "flags": flags}
        else:
            classification[rid] = {"dishonest": False, "flags": []}
    return classification


def generate_benefit_payments(recipients: list[dict], min_rows: int) -> list[dict]:
    payments: list[dict] = []
    for r in recipients:
        if r["account_status"] == "closed":
            continue
        n_months = random.randint(3, 6)
        months = sorted(random.sample(REVIEW_MONTHS, min(n_months, 6)))
        for m in months:
            y, mo = map(int, m.split("-"))
            if mo == 12:
                pay_dt = datetime(y + 1, 1, random.randint(1, 5))
            else:
                pay_dt = datetime(y, mo + 1, random.randint(1, 5))
            payments.append(
                {
                    "recipient_id": r["id"],
                    "payment_date": pay_dt.strftime("%Y-%m-%d"),
                    "amount": round(
                        r["monthly_benefit_amount"] * random.uniform(0.98, 1.02), 2
                    ),
                    "period_month": m,
                    "status": random.choices(
                        ["completed", "pending"], weights=[0.92, 0.08]
                    )[0],
                }
            )
    # pad
    active = [r for r in recipients if r["account_status"] != "closed"]
    while len(payments) < min_rows:
        r = random.choice(active)
        m = random.choice(REVIEW_MONTHS)
        y, mo = map(int, m.split("-"))
        pay_dt = datetime(y, mo + 1, random.randint(1, 5)) if mo < 12 else datetime(y + 1, 1, random.randint(1, 5))
        payments.append(
            {
                "recipient_id": r["id"],
                "payment_date": pay_dt.strftime("%Y-%m-%d"),
                "amount": round(
                    r["monthly_benefit_amount"] * random.uniform(0.98, 1.02), 2
                ),
                "period_month": m,
                "status": "completed",
            }
        )
    return payments


def generate_employment_updates(
    recipients: list[dict], classification: dict, min_rows: int
) -> list[dict]:
    updates: list[dict] = []
    for r in recipients:
        rid = r["id"]
        cls = classification[rid]

        if cls["dishonest"] and "EMPLOYMENT_MISMATCH" in cls["flags"]:
            for _ in range(random.randint(1, 2)):
                eff = fake.date_between(
                    start_date=datetime(2024, 6, 1), end_date=datetime(2025, 5, 1)
                )
                updates.append(
                    {
                        "recipient_id": rid,
                        "employer_name": random.choice(EMPLOYER_POOL),
                        "employment_status": random.choice(["employed", "part_time"]),
                        "reported_monthly_salary": round(
                            random.uniform(2500, 6000), 2
                        ),
                        "effective_date": eff.isoformat(),
                        "source_hub": random.choice(
                            ["PayrollHub_Alpha", "PayrollHub_Beta", "StateRegistry"]
                        ),
                    }
                )
        elif cls["dishonest"] and "INCOME_OVER_LIMIT" in cls["flags"]:
            max_inc = MAX_MONTHLY_INCOME[r["benefit_type"]]
            salary = round(random.uniform(max_inc * 1.5, max_inc * 3.0), 2)
            eff = fake.date_between(
                start_date=datetime(2024, 6, 1), end_date=datetime(2025, 5, 1)
            )
            updates.append(
                {
                    "recipient_id": rid,
                    "employer_name": random.choice(EMPLOYER_POOL),
                    "employment_status": random.choice(["employed", "part_time"]),
                    "reported_monthly_salary": salary,
                    "effective_date": eff.isoformat(),
                    "source_hub": random.choice(
                        ["PayrollHub_Alpha", "PayrollHub_Beta", "StateRegistry"]
                    ),
                }
            )
        else:
            # honest / non-applicable: old terminated records or nothing
            if random.random() < 0.4:
                eff = fake.date_between(
                    start_date=datetime(2023, 1, 1), end_date=datetime(2024, 3, 1)
                )
                updates.append(
                    {
                        "recipient_id": rid,
                        "employer_name": random.choice(EMPLOYER_POOL),
                        "employment_status": random.choice(
                            ["terminated", "laid_off", "resigned"]
                        ),
                        "reported_monthly_salary": 0.0,
                        "effective_date": eff.isoformat(),
                        "source_hub": random.choice(
                            ["PayrollHub_Alpha", "PayrollHub_Beta"]
                        ),
                    }
                )

    # pad with old terminated records
    while len(updates) < min_rows:
        r = random.choice(recipients)
        eff = fake.date_between(
            start_date=datetime(2023, 1, 1), end_date=datetime(2024, 3, 1)
        )
        updates.append(
            {
                "recipient_id": r["id"],
                "employer_name": random.choice(EMPLOYER_POOL),
                "employment_status": random.choice(
                    ["terminated", "laid_off", "resigned", "contract_ended"]
                ),
                "reported_monthly_salary": 0.0,
                "effective_date": eff.isoformat(),
                "source_hub": random.choice(
                    ["PayrollHub_Alpha", "PayrollHub_Beta", "StateRegistry"]
                ),
            }
        )
    return updates


def generate_bank_alerts(
    recipients: list[dict], classification: dict, min_rows: int
) -> list[dict]:
    alerts: list[dict] = []
    deposit_sources_large = [
        "wire_transfer",
        "direct_deposit",
        "ach_transfer",
        "check_deposit",
    ]
    deposit_sources_small = ["check_deposit", "cash_deposit", "tax_refund"]

    for r in recipients:
        rid = r["id"]
        cls = classification[rid]

        if cls["dishonest"] and "UNDECLARED_DEPOSITS" in cls["flags"]:
            for _ in range(random.randint(2, 5)):
                dt = fake.date_between(
                    start_date=datetime(2025, 1, 1), end_date=datetime(2025, 6, 28)
                )
                alerts.append(
                    {
                        "recipient_id": rid,
                        "alert_date": dt.isoformat(),
                        "deposit_amount": round(random.uniform(3000, 15000), 2),
                        "source_description": random.choice(deposit_sources_large),
                        "account_type": random.choice(["checking", "savings"]),
                    }
                )
        elif (
            cls["dishonest"]
            and "INCOME_OVER_LIMIT" in cls["flags"]
            and random.random() < 0.5
        ):
            for _ in range(random.randint(1, 3)):
                dt = fake.date_between(
                    start_date=datetime(2025, 1, 1), end_date=datetime(2025, 6, 28)
                )
                alerts.append(
                    {
                        "recipient_id": rid,
                        "alert_date": dt.isoformat(),
                        "deposit_amount": round(random.uniform(2000, 8000), 2),
                        "source_description": random.choice(deposit_sources_large),
                        "account_type": random.choice(["checking", "savings"]),
                    }
                )
        else:
            # honest: small rare deposits
            if random.random() < 0.20:
                dt = fake.date_between(
                    start_date=datetime(2025, 1, 1), end_date=datetime(2025, 6, 28)
                )
                alerts.append(
                    {
                        "recipient_id": rid,
                        "alert_date": dt.isoformat(),
                        "deposit_amount": round(random.uniform(200, 900), 2),
                        "source_description": random.choice(deposit_sources_small),
                        "account_type": random.choice(["checking", "savings"]),
                    }
                )

    # pad with tiny deposits
    while len(alerts) < min_rows:
        r = random.choice(recipients)
        dt = fake.date_between(
            start_date=datetime(2025, 1, 1), end_date=datetime(2025, 6, 28)
        )
        alerts.append(
            {
                "recipient_id": r["id"],
                "alert_date": dt.isoformat(),
                "deposit_amount": round(random.uniform(100, 400), 2),
                "source_description": random.choice(deposit_sources_small),
                "account_type": random.choice(["checking", "savings"]),
            }
        )
    return alerts


def generate_self_reports(
    recipients: list[dict], classification: dict
) -> list[dict]:
    reports: list[dict] = []
    for r in recipients:
        if r["account_status"] == "closed":
            continue
        rid = r["id"]
        cls = classification[rid]
        n_months = random.randint(3, 6)
        months = sorted(random.sample(REVIEW_MONTHS, min(n_months, 6)))

        for m in months:
            if cls["dishonest"]:
                if "EMPLOYMENT_MISMATCH" in cls["flags"]:
                    declared_income = round(random.uniform(0, 150), 2)
                    declared_status = random.choice(["unemployed", "not_working"])
                elif "UNDECLARED_DEPOSITS" in cls["flags"]:
                    declared_income = round(random.uniform(0, 250), 2)
                    declared_status = random.choice(
                        ["unemployed", "not_working", "odd_jobs"]
                    )
                elif "INCOME_OVER_LIMIT" in cls["flags"]:
                    max_inc = MAX_MONTHLY_INCOME[r["benefit_type"]]
                    declared_income = round(random.uniform(0, max_inc * 0.4), 2)
                    declared_status = random.choice(
                        ["part_time", "self_employed", "odd_jobs"]
                    )
                else:
                    declared_income = round(random.uniform(0, 150), 2)
                    declared_status = "unemployed"
                additional = random.choice(["none", "none", "small_gifts"])
            else:
                declared_income = round(random.uniform(0, 350), 2)
                declared_status = random.choice(
                    ["unemployed", "not_working", "seeking_employment"]
                )
                additional = random.choice(
                    ["none", "none", "none", "family_support"]
                )

            reports.append(
                {
                    "recipient_id": rid,
                    "report_month": m,
                    "declared_monthly_income": declared_income,
                    "declared_employment_status": declared_status,
                    "additional_income_sources": additional,
                }
            )
    return reports


# ---------------------------------------------------------------------------
# Workspace writer
# ---------------------------------------------------------------------------
def write_workspace(
    workspace: str,
    recipients: list[dict],
    self_reports: list[dict],
    num_files: int,
):
    os.makedirs(workspace, exist_ok=True)

    # ---- scalable batch CSV files ----
    by_rid: dict[int, list[dict]] = {}
    for sr in self_reports:
        by_rid.setdefault(sr["recipient_id"], []).append(sr)
    sorted_rids = sorted(by_rid.keys())
    batch_size = max(1, math.ceil(len(sorted_rids) / num_files))

    for i in range(num_files):
        batch_rids = sorted_rids[i * batch_size : (i + 1) * batch_size]
        rows = []
        for rid in batch_rids:
            rows.extend(by_rid.get(rid, []))
        if not rows:
            continue
        df = pd.DataFrame(rows).sort_values(["recipient_id", "report_month"])
        df.to_csv(
            os.path.join(workspace, f"self_reports_batch_{i + 1:02d}.csv"),
            index=False,
        )

    # ---- fixed config / policy files ----

    # 1. investigation_rules.yaml
    rules = {
        "review_period": {"start": "2025-01", "end": "2025-06"},
        "income_discrepancy_threshold_pct": 25,
        "large_deposit_threshold": 3000,
        "priority_weights": {
            "employment_mismatch": 40,
            "income_over_limit": 35,
            "undeclared_deposits": 25,
        },
        "severity_levels": {
            "critical": 80,
            "high": 60,
            "medium": 40,
            "low": 0,
        },
    }
    with open(os.path.join(workspace, "investigation_rules.yaml"), "w") as f:
        yaml.dump(rules, f, default_flow_style=False, sort_keys=False)

    # 2. benefit_eligibility.json
    eligibility = {
        "unemployment": {"max_monthly_income": 500, "requires_unemployed": True},
        "disability": {"max_monthly_income": 1350, "requires_unemployed": False},
        "housing_assistance": {"max_monthly_income": 2000, "requires_unemployed": False},
        "food_assistance": {"max_monthly_income": 1800, "requires_unemployed": False},
        "childcare_subsidy": {"max_monthly_income": 2500, "requires_unemployed": False},
    }
    with open(os.path.join(workspace, "benefit_eligibility.json"), "w") as f:
        json.dump(eligibility, f, indent=2)

    # 3. policy_guidelines.md
    policy = """\
# Benefit Overpayment Investigation Policy

## Purpose

This document outlines the methodology for calculating potential overpayment
amounts and selecting the final discrepancy figure when multiple indicators
apply to a single case.

## Detected Monthly Income

For each recipient under review, the detected monthly income is the greater of
two values: the reported monthly salary from their most recent employment
update (considering only updates where the status indicates active employment,
i.e. "employed" or "part_time") and the average monthly bank deposits
(total deposits in the review period divided by the number of months in that
period).

## Discrepancy Amount Calculation

Three flag-specific formulas may apply.  For each formula that applies to the
case, compute the value; the final discrepancy amount is the **largest** of all
applicable values, rounded to exactly two decimal places.

### EMPLOYMENT_MISMATCH

When the recipient's benefit program requires unemployment and the payroll data
shows active employment while the recipient's self-declaration states otherwise,
the discrepancy equals the **total benefit payments** the recipient received
during the review period.

### INCOME_OVER_LIMIT

When the detected monthly income exceeds the maximum monthly income allowed for
the recipient's benefit type, compute:

    (detected_monthly_income − max_monthly_income) × number_of_review_months

Cap this value at the total benefit payments received during the review period.

### UNDECLARED_DEPOSITS

When deposits are flagged, the discrepancy equals:

    total_deposits_in_period − total_declared_income_in_period

using only the positive difference (floor at zero).

## Final Amount Selection

If multiple flags apply, each formula above is evaluated and the **maximum**
value among them is used as the final discrepancy amount.
"""
    with open(os.path.join(workspace, "policy_guidelines.md"), "w") as f:
        f.write(policy)

    # 4. deposit_source_codes.txt
    codes = """\
wire_transfer    External wire transfer from another financial institution
direct_deposit   Automated direct deposit from employer payroll system
ach_transfer     ACH electronic funds transfer
check_deposit    Physical check deposited at branch or ATM
cash_deposit     Cash deposited at branch location
tax_refund       Government tax refund direct deposit
"""
    with open(os.path.join(workspace, "deposit_source_codes.txt"), "w") as f:
        f.write(codes)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    # pre-generate employer names
    global EMPLOYER_POOL
    EMPLOYER_POOL = [fake.company() for _ in range(30)]

    # --- recipients ---
    recipients = generate_recipients(n)

    # --- classification ---
    classification = classify_recipients(recipients)

    # --- related tables ---
    payments = generate_benefit_payments(recipients, n)
    emp_updates = generate_employment_updates(recipients, classification, n)
    bank_alerts = generate_bank_alerts(recipients, classification, n)
    self_reports = generate_self_reports(recipients, classification)

    # --- write DB ---
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    conn.executemany(
        "INSERT INTO recipients VALUES "
        "(:id,:name,:ssn_last4,:date_of_birth,:benefit_type,"
        ":monthly_benefit_amount,:enrollment_date,:account_status,:region)",
        recipients,
    )
    conn.executemany(
        "INSERT INTO benefit_payments "
        "(recipient_id,payment_date,amount,period_month,status) "
        "VALUES (:recipient_id,:payment_date,:amount,:period_month,:status)",
        payments,
    )
    conn.executemany(
        "INSERT INTO employment_updates "
        "(recipient_id,employer_name,employment_status,"
        "reported_monthly_salary,effective_date,source_hub) "
        "VALUES (:recipient_id,:employer_name,:employment_status,"
        ":reported_monthly_salary,:effective_date,:source_hub)",
        emp_updates,
    )
    conn.executemany(
        "INSERT INTO bank_transaction_alerts "
        "(recipient_id,alert_date,deposit_amount,source_description,account_type) "
        "VALUES (:recipient_id,:alert_date,:deposit_amount,:source_description,:account_type)",
        bank_alerts,
    )
    conn.commit()
    conn.close()

    # --- workspace ---
    write_workspace(args.workspace, recipients, self_reports, num_files)

    print(f"Recipients:  {len(recipients)}")
    print(f"Payments:    {len(payments)}")
    print(f"Emp updates: {len(emp_updates)}")
    print(f"Bank alerts: {len(bank_alerts)}")
    print(f"Self-reports:{len(self_reports)} across {num_files} batch files")


if __name__ == "__main__":
    main()
