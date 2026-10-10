#!/usr/bin/env python3
"""Data generation for cash reserves forecasting task."""
import argparse
import os
import sqlite3
import json
import csv
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 120,       # v1 = 2x base
    "num_workspace_files": 16,   # v1 = base + N (8 + 8)
}

# ---------- Fixed configuration ----------
REFERENCE_DATE = "2025-01-13"   # Monday — start of forecast week
HISTORY_DAYS = 30
FORECAST_DAYS = 7

DEPARTMENTS = [
    "Finance", "Engineering", "Sales", "Marketing",
    "Operations", "HR", "Legal", "IT"
]
VENDOR_CATEGORIES = [
    "Office Supplies", "Software Licenses", "Professional Services",
    "Utilities", "Maintenance", "Logistics"
]
EXPENSE_CATEGORIES = [
    "Salaries & Benefits", "Office Operations", "Technology",
    "Travel", "Marketing & Ads"
]

INFLOW_SOURCES = [
    "Customer Payment", "Service Revenue", "Investment Return",
    "Tax Refund", "Other"
]

DAY_OF_WEEK_WEIGHTS = {
    "Monday": 1.10,
    "Tuesday": 1.05,
    "Wednesday": 1.00,
    "Thursday": 0.95,
    "Friday": 1.15,
    "Saturday": 0.40,
    "Sunday": 0.35,
}

VARIANCE_ADJUSTMENTS = {
    "Salaries & Benefits": {"adjustment_factor": 1.02, "note": "Slight upward trend due to overtime"},
    "Office Operations":   {"adjustment_factor": 1.05, "note": "Seasonal supply-cost increase"},
    "Technology":          {"adjustment_factor": 0.98, "note": "Contract renegotiation savings"},
    "Travel":              {"adjustment_factor": 1.15, "note": "Q1 conference season surge"},
    "Marketing & Ads":     {"adjustment_factor": 1.08, "note": "New-year campaign ramp-up"},
}

CASH_POLICY = {
    "minimum_balance": 250000.0,
    "target_buffer_pct": 0.15,
    "emergency_reserve_pct": 0.05,
    "funding_tiers": [
        {"max_amount": 100000,  "method": "internal_transfer",  "lead_time_days": 0},
        {"max_amount": 500000,  "method": "credit_line_draw",   "lead_time_days": 1},
        {"max_amount": 2000000, "method": "asset_liquidation",  "lead_time_days": 2},
    ],
    "review_frequency": "weekly",
}


# ================================================================
# Database creation
# ================================================================

def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS employees (
        employee_id      INTEGER PRIMARY KEY,
        name             TEXT,
        department       TEXT,
        base_salary      REAL,
        pay_frequency    TEXT,
        pay_day_of_week  INTEGER,
        pay_day_of_month INTEGER,
        pay_anchor_date  TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS vendors (
        vendor_id            INTEGER PRIMARY KEY,
        vendor_name          TEXT,
        category             TEXT,
        payment_amount       REAL,
        payment_frequency    TEXT,
        payment_day_of_week  INTEGER,
        payment_day_of_month INTEGER,
        is_active            INTEGER
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tax_liabilities (
        tax_id             INTEGER PRIMARY KEY,
        tax_type           TEXT,
        jurisdiction       TEXT,
        amount             REAL,
        due_date           TEXT,
        status             TEXT,
        penalty_rate_daily REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS expense_history (
        record_id       INTEGER PRIMARY KEY,
        record_date     TEXT,
        department      TEXT,
        category        TEXT,
        budgeted_amount REAL,
        actual_amount   REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS account_info (
        account_id      INTEGER PRIMARY KEY,
        account_name    TEXT,
        current_balance REAL,
        balance_date    TEXT
    )""")
    conn.commit()


# ================================================================
# Data population
# ================================================================

def populate_employees(conn):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    n = SCALE["rows_per_table"]
    frequencies = ["weekly", "biweekly", "monthly"]
    freq_weights = [0.30, 0.40, 0.30]

    rows = []
    for i in range(n):
        dept = DEPARTMENTS[i % len(DEPARTMENTS)]
        freq = str(np.random.choice(frequencies, p=freq_weights))
        salary = round(float(np.random.uniform(2000, 12000)), 2)

        if freq == "weekly":
            dow = 4          # Friday
            dom = None
            anchor = None
        elif freq == "biweekly":
            dow = 4          # Friday
            dom = None
            anchor = "2025-01-03" if i % 2 == 0 else "2025-01-10"
        else:
            dow = None
            dom = int(np.random.choice([1, 15]))
            anchor = None

        rows.append((i + 1, fake.name(), dept, salary, freq, dow, dom, anchor))

    conn.executemany("INSERT INTO employees VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()


def populate_vendors(conn):
    np.random.seed(142)
    fake = Faker()
    Faker.seed(142)

    n = SCALE["rows_per_table"]
    frequencies = ["weekly", "monthly", "quarterly"]
    freq_weights = [0.20, 0.60, 0.20]

    rows = []
    for i in range(n):
        cat = VENDOR_CATEGORIES[i % len(VENDOR_CATEGORIES)]
        freq = str(np.random.choice(frequencies, p=freq_weights))
        amount = round(float(np.random.uniform(500, 15000)), 2)
        active = 1 if float(np.random.random()) > 0.1 else 0

        if freq == "weekly":
            dow = int(np.random.choice([0, 1, 2, 3, 4]))
            dom = None
        elif freq == "monthly":
            dom = int(np.random.choice([1, 5, 10, 15, 17, 20]))
            dow = None
        else:  # quarterly
            dom = int(np.random.choice([1, 10, 15]))
            dow = None

        rows.append((i + 1, fake.company(), cat, amount, freq, dow, dom, active))

    conn.executemany("INSERT INTO vendors VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()


def populate_tax_liabilities(conn):
    np.random.seed(242)
    fake = Faker()
    Faker.seed(242)

    n = SCALE["rows_per_table"]
    tax_types = [
        "Federal Income Tax", "State Income Tax", "Sales Tax",
        "Payroll Tax", "Property Tax", "Excise Tax"
    ]
    jurisdictions = [
        "Federal", "State-CA", "State-NY", "State-TX", "Local-LA", "Local-NYC"
    ]
    statuses = ["pending", "paid", "deferred"]
    ref = pd.Timestamp(REFERENCE_DATE)

    rows = []
    for i in range(n):
        tt = tax_types[i % len(tax_types)]
        jur = jurisdictions[i % len(jurisdictions)]
        amount = round(float(np.random.uniform(1000, 50000)), 2)
        penalty = round(float(np.random.uniform(0.0005, 0.005)), 4)

        # First ~15 % are guaranteed pending in forecast week
        if i < max(n // 6, 8):
            offset = int(np.random.choice(range(FORECAST_DAYS)))
            status = "pending"
        else:
            offset = int(np.random.choice(range(-15, 35)))
            status = str(np.random.choice(statuses, p=[0.35, 0.50, 0.15]))

        due = (ref + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")
        rows.append((i + 1, tt, jur, amount, due, status, penalty))

    conn.executemany("INSERT INTO tax_liabilities VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()


def populate_expense_history(conn):
    np.random.seed(342)

    n_records = SCALE["rows_per_table"] * 3
    ref = pd.Timestamp(REFERENCE_DATE)

    rows = []
    for i in range(n_records):
        days_ago = int(np.random.choice(range(1, HISTORY_DAYS + 1)))
        rdate = (ref - pd.Timedelta(days=days_ago)).strftime("%Y-%m-%d")
        dept = DEPARTMENTS[i % len(DEPARTMENTS)]
        cat = EXPENSE_CATEGORIES[i % len(EXPENSE_CATEGORIES)]
        budgeted = round(float(np.random.uniform(500, 10000)), 2)
        variance_factor = float(np.random.uniform(0.80, 1.30))
        actual = round(budgeted * variance_factor, 2)
        rows.append((i + 1, rdate, dept, cat, budgeted, actual))

    conn.executemany("INSERT INTO expense_history VALUES (?,?,?,?,?,?)", rows)
    conn.commit()


def populate_account_info(conn):
    balance = round(SCALE["rows_per_table"] * 12500.0, 2)
    conn.execute(
        "INSERT INTO account_info VALUES (?,?,?,?)",
        (1, "Operating Account", balance, REFERENCE_DATE)
    )
    conn.commit()


# ================================================================
# Workspace generation
# ================================================================

def write_cash_policy(workspace):
    """Write cash_policy.yaml (fixed config, not scaled)."""
    path = os.path.join(workspace, "cash_policy.yaml")
    lines = [
        "# Cash Management Policy",
        f"minimum_balance: {CASH_POLICY['minimum_balance']:.2f}",
        f"target_buffer_pct: {CASH_POLICY['target_buffer_pct']}",
        f"emergency_reserve_pct: {CASH_POLICY['emergency_reserve_pct']}",
        f"review_frequency: \"{CASH_POLICY['review_frequency']}\"",
        "",
        "funding_tiers:",
    ]
    for tier in CASH_POLICY["funding_tiers"]:
        lines.append(f"  - max_amount: {tier['max_amount']}")
        lines.append(f"    method: \"{tier['method']}\"")
        lines.append(f"    lead_time_days: {tier['lead_time_days']}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_variance_adjustments(workspace):
    """Write variance_adjustments.json (fixed config, not scaled)."""
    path = os.path.join(workspace, "variance_adjustments.json")
    with open(path, "w") as f:
        json.dump(VARIANCE_ADJUSTMENTS, f, indent=2)


def write_forecast_parameters(workspace):
    """Write forecast_parameters.txt (fixed config, not scaled)."""
    path = os.path.join(workspace, "forecast_parameters.txt")
    lines = [
        f"Reference Date: {REFERENCE_DATE}",
        f"Forecast Period: {FORECAST_DAYS} days",
        "",
        "Day-of-Week Expense Weights:",
    ]
    for day_name, weight in DAY_OF_WEEK_WEIGHTS.items():
        lines.append(f"  {day_name}: {weight:.2f}")
    lines.append("")
    lines.append("Notes:")
    lines.append("  These weights are multiplied against the adjusted average daily")
    lines.append("  operating expense to reflect weekday vs. weekend spending patterns.")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_weekly_inflows(workspace):
    """Generate num_workspace_files weekly-inflow CSV files (scaled)."""
    n_files = SCALE["num_workspace_files"]
    ref = pd.Timestamp(REFERENCE_DATE)
    source_weights = [0.45, 0.25, 0.15, 0.08, 0.07]

    for fi in range(n_files):
        np.random.seed(500 + fi)
        week_start = ref - pd.Timedelta(days=7 * (fi + 1))

        rows = []
        for d in range(7):
            day = week_start + pd.Timedelta(days=d)
            day_str = day.strftime("%Y-%m-%d")
            weekday = day.weekday()

            # More entries and higher amounts on weekdays
            if weekday < 5:
                n_entries = int(np.random.choice(range(4, 9)))
                lo, hi = 5000.0, 80000.0
            else:
                n_entries = int(np.random.choice(range(1, 4)))
                lo, hi = 1000.0, 15000.0

            for _ in range(n_entries):
                src = str(np.random.choice(INFLOW_SOURCES, p=source_weights))
                amt = round(float(np.random.uniform(lo, hi)), 2)
                rows.append([day_str, src, f"{amt:.2f}"])

        fname = f"weekly_inflows_w{fi + 1:02d}.csv"
        fpath = os.path.join(workspace, fname)
        with open(fpath, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "source", "amount"])
            w.writerows(rows)


# ================================================================
# Main
# ================================================================

def main(db_path, workspace):
    os.makedirs(workspace, exist_ok=True)

    conn = sqlite3.connect(db_path)
    create_tables(conn)

    populate_employees(conn)
    populate_vendors(conn)
    populate_tax_liabilities(conn)
    populate_expense_history(conn)
    populate_account_info(conn)

    # Fixed workspace files
    write_cash_policy(workspace)
    write_variance_adjustments(workspace)
    write_forecast_parameters(workspace)

    # Scalable workspace files
    write_weekly_inflows(workspace)

    conn.close()
    print(f"Database written to {db_path}")
    print(f"Workspace populated in {workspace}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
