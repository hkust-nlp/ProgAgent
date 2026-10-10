"""
Data generation for Financial Regulation Reporting Threshold Task.
Generates a SQLite database and workspace files for evaluating
which clients are impacted by new reporting threshold regulations.
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
import yaml
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 640,
    "num_workspace_files": 32,
}

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# --- Constants ---
JURISDICTIONS = [
    "US-NY", "US-CA", "US-TX", "US-FL", "US-IL",
    "UK-LON", "UK-MAN", "EU-DE", "EU-FR", "EU-NL",
    "SG", "HK", "JP", "AU", "CA-ON",
]

TXN_TYPES = [
    "wire_transfer", "securities_trade", "foreign_exchange",
    "derivative", "cash_deposit", "loan_disbursement",
]

CLIENT_TYPES = ["individual", "corporate", "institutional"]

ACCOUNT_TYPES = ["checking", "savings", "brokerage", "custody", "margin"]

CURRENCIES = ["USD", "EUR", "GBP", "JPY", "SGD", "HKD", "AUD", "CAD", "CHF"]

RISK_RATINGS = ["low", "medium", "high"]
COMPLIANCE_TIERS = ["basic", "standard", "premium"]

REPORT_TYPES = ["quarterly_disclosure", "annual_summary", "threshold_breach", "ad_hoc_filing"]

REGULATION_CODE = "FRT-2024"

REPORTING_PERIOD_START = "2024-01-01"
REPORTING_PERIOD_END = "2024-06-30"
REGULATION_EFFECTIVE_DATE = "2024-07-01"

# Jurisdiction display names
JURISDICTION_NAMES = {
    "US-NY": "New York, United States",
    "US-CA": "California, United States",
    "US-TX": "Texas, United States",
    "US-FL": "Florida, United States",
    "US-IL": "Illinois, United States",
    "UK-LON": "London, United Kingdom",
    "UK-MAN": "Manchester, United Kingdom",
    "EU-DE": "Germany, European Union",
    "EU-FR": "France, European Union",
    "EU-NL": "Netherlands, European Union",
    "SG": "Singapore",
    "HK": "Hong Kong",
    "JP": "Japan",
    "AU": "Australia",
    "CA-ON": "Ontario, Canada",
}

JURISDICTION_REGIONS = {
    "US-NY": "North America", "US-CA": "North America", "US-TX": "North America",
    "US-FL": "North America", "US-IL": "North America",
    "UK-LON": "Europe", "UK-MAN": "Europe",
    "EU-DE": "Europe", "EU-FR": "Europe", "EU-NL": "Europe",
    "SG": "Asia-Pacific", "HK": "Asia-Pacific", "JP": "Asia-Pacific",
    "AU": "Asia-Pacific", "CA-ON": "North America",
}

JURISDICTION_BODIES = {
    "US-NY": "SEC / FINRA", "US-CA": "SEC / DFPI", "US-TX": "SEC / TSSB",
    "US-FL": "SEC / OFR", "US-IL": "SEC / IDFPR",
    "UK-LON": "FCA", "UK-MAN": "FCA",
    "EU-DE": "BaFin", "EU-FR": "AMF", "EU-NL": "AFM",
    "SG": "MAS", "HK": "SFC", "JP": "FSA",
    "AU": "ASIC", "CA-ON": "OSC",
}


def create_tables(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            client_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            jurisdiction_code TEXT NOT NULL,
            client_type TEXT NOT NULL,
            registration_date TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            account_id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            account_number TEXT NOT NULL,
            account_type TEXT NOT NULL,
            balance REAL NOT NULL,
            currency TEXT NOT NULL,
            opened_date TEXT NOT NULL,
            FOREIGN KEY (client_id) REFERENCES clients(client_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            txn_id INTEGER PRIMARY KEY,
            account_id INTEGER NOT NULL,
            client_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            txn_type TEXT NOT NULL,
            txn_date TEXT NOT NULL,
            currency TEXT NOT NULL,
            counterparty TEXT NOT NULL,
            FOREIGN KEY (account_id) REFERENCES accounts(account_id),
            FOREIGN KEY (client_id) REFERENCES clients(client_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS previous_reports (
            report_id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            report_type TEXT NOT NULL,
            filing_date TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            threshold_applied REAL NOT NULL,
            total_reported_amount REAL NOT NULL,
            jurisdiction_code TEXT NOT NULL,
            txn_type TEXT NOT NULL,
            filing_status TEXT NOT NULL,
            FOREIGN KEY (client_id) REFERENCES clients(client_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS regulation_clauses (
            clause_id INTEGER PRIMARY KEY,
            regulation_code TEXT NOT NULL,
            txn_type TEXT NOT NULL,
            jurisdiction_code TEXT NOT NULL,
            client_type TEXT NOT NULL,
            old_threshold REAL NOT NULL,
            new_threshold REAL NOT NULL,
            effective_date TEXT NOT NULL,
            description TEXT NOT NULL
        )
    """)
    conn.commit()


def generate_clients(n):
    rows = []
    statuses = ["active"] * 75 + ["inactive"] * 15 + ["suspended"] * 10
    for i in range(1, n + 1):
        name = fake.company() if random.random() < 0.6 else fake.name()
        jur = random.choice(JURISDICTIONS)
        ctype = random.choice(CLIENT_TYPES)
        reg_date = fake.date_between(start_date="-5y", end_date="-30d").isoformat()
        status = random.choice(statuses)
        rows.append((i, name, jur, ctype, reg_date, status))
    return rows


def generate_accounts(n, client_ids):
    rows = []
    for i in range(1, n + 1):
        cid = random.choice(client_ids)
        acct_num = f"ACCT-{fake.unique.random_int(min=100000, max=999999)}"
        atype = random.choice(ACCOUNT_TYPES)
        balance = round(random.uniform(1000, 5000000), 2)
        currency = random.choice(CURRENCIES)
        opened = fake.date_between(start_date="-4y", end_date="-60d").isoformat()
        rows.append((i, cid, acct_num, atype, balance, currency, opened))
    fake.unique.clear()
    return rows


def generate_transactions(n, accounts_by_client, client_ids):
    """Generate transactions. We generate 4*n_clients spread across clients, minimum n."""
    total_txns = max(n, 4 * len(client_ids))
    rows = []
    period_start = datetime(2024, 1, 1)
    period_end = datetime(2024, 6, 30)
    full_start = datetime(2023, 1, 1)

    for i in range(1, total_txns + 1):
        cid = random.choice(client_ids)
        accts = accounts_by_client.get(cid, [])
        if not accts:
            continue
        aid = random.choice(accts)
        # 80% in-period, 20% out-of-period
        if random.random() < 0.8:
            txn_date = fake.date_between_dates(
                date_start=period_start, date_end=period_end
            ).isoformat()
        else:
            txn_date = fake.date_between_dates(
                date_start=full_start, date_end=datetime(2023, 12, 31)
            ).isoformat()
        txn_type = random.choice(TXN_TYPES)
        amount = round(random.uniform(500, 200000), 2)
        currency = random.choice(CURRENCIES[:4])  # Major currencies
        counterparty = fake.company()
        rows.append((i, aid, cid, amount, txn_type, txn_date, currency, counterparty))
    return rows


def generate_regulation_clauses(n):
    """Generate regulation clauses - combinations of txn_type x jurisdiction x client_type."""
    rows = []
    clause_id = 0
    combos = []
    for tt in TXN_TYPES:
        for jur in JURISDICTIONS:
            for ct in CLIENT_TYPES:
                combos.append((tt, jur, ct))
    random.shuffle(combos)

    # Base thresholds by txn_type
    base_old_thresholds = {
        "wire_transfer": 50000,
        "securities_trade": 100000,
        "foreign_exchange": 75000,
        "derivative": 150000,
        "cash_deposit": 25000,
        "loan_disbursement": 200000,
    }
    # Reduction factors by jurisdiction region
    region_factors = {
        "North America": 0.50,
        "Europe": 0.55,
        "Asia-Pacific": 0.45,
    }

    for tt, jur, ct in combos[:max(n, len(combos))]:
        clause_id += 1
        region = JURISDICTION_REGIONS[jur]
        base_old = base_old_thresholds[tt]
        # Client type adjustments
        ct_mult = {"individual": 1.0, "corporate": 1.5, "institutional": 2.0}[ct]
        old_threshold = round(base_old * ct_mult, 2)
        reduction = region_factors[region]
        new_threshold = round(old_threshold * reduction, 2)
        desc = (f"Clause {clause_id}: Under {REGULATION_CODE}, {tt} threshold for "
                f"{ct} clients in {jur} reduced from {old_threshold} to {new_threshold}")
        rows.append((
            clause_id, REGULATION_CODE, tt, jur, ct,
            old_threshold, new_threshold,
            REGULATION_EFFECTIVE_DATE, desc
        ))

    # Pad if needed to meet minimum
    while len(rows) < n:
        clause_id += 1
        tt = random.choice(TXN_TYPES)
        jur = random.choice(JURISDICTIONS)
        ct = random.choice(CLIENT_TYPES)
        base_old = base_old_thresholds[tt]
        ct_mult = {"individual": 1.0, "corporate": 1.5, "institutional": 2.0}[ct]
        old_threshold = round(base_old * ct_mult, 2)
        region = JURISDICTION_REGIONS[jur]
        reduction = region_factors[region]
        new_threshold = round(old_threshold * reduction, 2)
        desc = (f"Clause {clause_id}: Under {REGULATION_CODE}, {tt} threshold for "
                f"{ct} clients in {jur} reduced from {old_threshold} to {new_threshold}")
        rows.append((
            clause_id, REGULATION_CODE, tt, jur, ct,
            old_threshold, new_threshold,
            REGULATION_EFFECTIVE_DATE, desc
        ))

    return rows


def generate_previous_reports(n, clients_data, regulation_clauses):
    """Generate previous report filings."""
    rows = []
    report_id = 0
    # Build clause lookup for thresholds
    clause_lookup = {}
    for c in regulation_clauses:
        key = (c[2], c[3], c[4])  # txn_type, jurisdiction, client_type
        clause_lookup[key] = (c[5], c[6])  # old_threshold, new_threshold

    active_clients = [c for c in clients_data if c[5] == "active"]
    target = max(n, 2 * len(active_clients))

    while len(rows) < target:
        for client in active_clients:
            if len(rows) >= target:
                break
            cid, name, jur, ctype = client[0], client[1], client[2], client[3]
            tt = random.choice(TXN_TYPES)
            key = (tt, jur, ctype)
            if key in clause_lookup:
                old_thresh = clause_lookup[key][0]
            else:
                old_thresh = round(random.uniform(20000, 200000), 2)

            report_id += 1
            rtype = random.choice(REPORT_TYPES)
            filing_date = fake.date_between(
                start_date=datetime(2024, 4, 1),
                end_date=datetime(2024, 6, 30)
            ).isoformat()
            total_amt = round(random.uniform(old_thresh * 0.3, old_thresh * 2.5), 2)
            fstatus = random.choice(["filed", "filed", "filed", "amended", "pending"])
            rows.append((
                report_id, cid, rtype, filing_date,
                REPORTING_PERIOD_START, REPORTING_PERIOD_END,
                old_thresh, total_amt, jur, tt, fstatus
            ))

    return rows


def generate_workspace(workspace, clients_data, db_path):
    """Generate workspace files."""
    os.makedirs(workspace, exist_ok=True)

    n_files = SCALE["num_workspace_files"]
    n_clients = len(clients_data)
    clients_per_file = math.ceil(n_clients / n_files)

    # --- Scalable files: client portfolio JSONs ---
    for fi in range(n_files):
        start_idx = fi * clients_per_file
        end_idx = min(start_idx + clients_per_file, n_clients)
        batch = clients_data[start_idx:end_idx]

        portfolio_entries = []
        for client in batch:
            cid = client[0]
            risk = random.choice(RISK_RATINGS)
            tier = random.choice(COMPLIANCE_TIERS)
            last_audit = fake.date_between(
                start_date="-2y", end_date="-30d"
            ).isoformat()
            aml_flag = random.random() < 0.08
            edd = random.random() < 0.12
            portfolio_entries.append({
                "client_id": cid,
                "risk_rating": risk,
                "compliance_tier": tier,
                "last_audit_date": last_audit,
                "aml_flag": aml_flag,
                "enhanced_due_diligence": edd,
            })

        fname = f"client_portfolio_{fi + 1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(portfolio_entries, f, indent=2)

    # --- Fixed file 1: regulation_update.yaml ---
    regulation_data = {
        "regulation": {
            "code": REGULATION_CODE,
            "title": "Financial Reporting Threshold Reform Act of 2024",
            "effective_date": REGULATION_EFFECTIVE_DATE,
            "issuing_body": "International Financial Oversight Council (IFOC)",
            "summary": (
                "This regulation mandates a reduction in reporting thresholds across "
                "all monitored transaction types. The reduction factors vary by "
                "geographic region to account for local market conditions."
            ),
            "reporting_period": {
                "start": REPORTING_PERIOD_START,
                "end": REPORTING_PERIOD_END,
            },
            "scope": "All active clients with transactions in the reporting period",
            "impact_criteria": (
                "A client is impacted if, for any transaction type, their total "
                "transaction volume during the reporting period meets or exceeds "
                "the new threshold AND they have a previously filed report for that "
                "transaction type in the same period that used the old threshold."
            ),
            "notes": (
                "Only transactions dated within the reporting period "
                "(2024-01-01 to 2024-06-30 inclusive) should be counted. "
                "Inactive and suspended clients are excluded from the impact assessment."
            ),
        }
    }
    with open(os.path.join(workspace, "regulation_update.yaml"), "w") as f:
        yaml.dump(regulation_data, f, default_flow_style=False, sort_keys=False)

    # --- Fixed file 2: jurisdiction_config.json ---
    jur_config = {}
    for code in JURISDICTIONS:
        jur_config[code] = {
            "display_name": JURISDICTION_NAMES[code],
            "region": JURISDICTION_REGIONS[code],
            "regulatory_body": JURISDICTION_BODIES[code],
            "active": True,
            "currency_primary": {
                "US-NY": "USD", "US-CA": "USD", "US-TX": "USD",
                "US-FL": "USD", "US-IL": "USD",
                "UK-LON": "GBP", "UK-MAN": "GBP",
                "EU-DE": "EUR", "EU-FR": "EUR", "EU-NL": "EUR",
                "SG": "SGD", "HK": "HKD", "JP": "JPY",
                "AU": "AUD", "CA-ON": "CAD",
            }[code],
        }
    with open(os.path.join(workspace, "jurisdiction_config.json"), "w") as f:
        json.dump(jur_config, f, indent=2)

    # --- Fixed file 3: exemption_policy.txt ---
    exemption_text = """EXEMPTION POLICY FOR REGULATION FRT-2024
========================================

The following exemption criteria apply when determining whether an impacted
client requires updated disclosures under Regulation FRT-2024.

A client is EXEMPT from updated disclosure requirements if ALL of the
following conditions are satisfied simultaneously:

  1. The client's risk rating is "low".
  2. The client's compliance tier is "premium".
  3. The client has no active AML (Anti-Money Laundering) flag.

Additionally, a client is EXEMPT regardless of the above if:

  4. The client's registration date is within 90 days before the regulation
     effective date (i.e., registered on or after 2024-04-02). Newly
     registered clients are handled under a separate onboarding disclosure
     process and are excluded from this regulation's scope.

If ANY exemption condition set (conditions 1-3 together, OR condition 4 alone)
is fully met, the client shall not appear on the impacted clients list.

All exemption determinations must be documented. A client who does not meet
any complete exemption set is considered non-exempt and must receive updated
disclosures.
"""
    with open(os.path.join(workspace, "exemption_policy.txt"), "w") as f:
        f.write(exemption_text)

    # --- Fixed file 4: priority_matrix.csv ---
    priority_rows = [
        ["risk_rating", "gap_ratio_min", "gap_ratio_max", "disclosure_priority"],
        ["high", "0.00", "0.50", "high"],
        ["high", "0.50", "1.00", "critical"],
        ["high", "1.00", "999.00", "critical"],
        ["medium", "0.00", "0.50", "medium"],
        ["medium", "0.50", "1.00", "high"],
        ["medium", "1.00", "999.00", "critical"],
        ["low", "0.00", "0.50", "low"],
        ["low", "0.50", "1.00", "medium"],
        ["low", "1.00", "999.00", "high"],
    ]
    with open(os.path.join(workspace, "priority_matrix.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(priority_rows)

    # --- Fixed file 5: disclosure_format_spec.md ---
    spec_text = """# Disclosure Output Specification

The final impacted clients report must be saved as `impacted_clients.csv` in the working directory.

## Required Columns (in this exact order)

client_id, client_name, jurisdiction_code, transaction_type, total_amount, old_threshold, new_threshold, gap_amount, previous_report_id, disclosure_priority

## Column Definitions

- client_id: Integer identifier for the client.
- client_name: Full name of the client as registered.
- jurisdiction_code: The jurisdiction code (e.g., US-NY, EU-DE).
- transaction_type: The transaction type triggering the impact (e.g., wire_transfer).
- total_amount: Sum of all in-period transactions of that type for the client, rounded to 2 decimal places.
- old_threshold: The threshold that was applied in the previous report filing.
- new_threshold: The new threshold under FRT-2024.
- gap_amount: Difference between total_amount and new_threshold, rounded to 2 decimal places.
- previous_report_id: The report_id of the most recent previous filing for this client and transaction type.
- disclosure_priority: One of "critical", "high", "medium", "low" as determined by the priority matrix.

## Sorting

Rows must be sorted by disclosure_priority in descending urgency order (critical first, then high, then medium, then low). Within the same priority level, sort by gap_amount in descending order. If gap_amount is also equal, sort by client_id ascending as a tiebreaker.

## Formatting

- All numeric amounts must use exactly 2 decimal places (e.g., 75000.00, not 75000).
- No trailing whitespace on any line.
- Use standard CSV formatting with no quoting unless a field contains a comma.
"""
    with open(os.path.join(workspace, "disclosure_format_spec.md"), "w") as f:
        f.write(spec_text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # Reset seeds for reproducibility
    random.seed(SEED)
    np.random.seed(SEED)
    Faker.seed(SEED)
    fake.unique.clear()

    n = SCALE["rows_per_table"]

    # Remove existing DB
    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    # Generate clients
    clients_data = generate_clients(n)
    conn.executemany(
        "INSERT INTO clients VALUES (?,?,?,?,?,?)", clients_data
    )

    # Generate accounts (at least n, ~1.5 per client)
    n_accounts = max(n, int(n * 1.5))
    client_ids = [c[0] for c in clients_data]
    accounts_data = generate_accounts(n_accounts, client_ids)
    conn.executemany(
        "INSERT INTO accounts VALUES (?,?,?,?,?,?,?)", accounts_data
    )

    # Build account lookup
    accounts_by_client = {}
    for a in accounts_data:
        accounts_by_client.setdefault(a[1], []).append(a[0])

    # Generate transactions (at least n, targeting 4 per client)
    transactions_data = generate_transactions(n, accounts_by_client, client_ids)
    conn.executemany(
        "INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?)", transactions_data
    )

    # Generate regulation clauses
    regulation_clauses = generate_regulation_clauses(n)
    conn.executemany(
        "INSERT INTO regulation_clauses VALUES (?,?,?,?,?,?,?,?,?)",
        regulation_clauses
    )

    # Generate previous reports
    previous_reports = generate_previous_reports(n, clients_data, regulation_clauses)
    conn.executemany(
        "INSERT INTO previous_reports VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        previous_reports
    )

    conn.commit()
    conn.close()

    # Generate workspace
    generate_workspace(args.workspace, clients_data, args.db_path)

    # Summary
    print(f"Database created at {args.db_path}")
    conn2 = sqlite3.connect(args.db_path)
    for table in ["clients", "accounts", "transactions", "previous_reports", "regulation_clauses"]:
        count = conn2.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count} rows")
    conn2.close()

    ws_files = os.listdir(args.workspace)
    print(f"Workspace files ({len(ws_files)}): {sorted(ws_files)}")


if __name__ == "__main__":
    main()
