#!/usr/bin/env python3
"""Data generation for cross-border payment reconciliation task."""

import argparse
import csv
import json
import os
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 640,
    "num_workspace_files": 40,
}

# ── Constants ────────────────────────────────────────────────────────────────

CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF"]

AMOUNT_RANGES = {
    "USD": (10_000, 2_000_000),
    "EUR": (8_000, 1_800_000),
    "GBP": (7_000, 1_500_000),
    "JPY": (1_000_000, 200_000_000),
    "CHF": (9_000, 1_700_000),
}

HIGH_VALUE_THRESHOLDS = {
    "USD": 500_000,
    "EUR": 400_000,
    "GBP": 350_000,
    "JPY": 50_000_000,
    "CHF": 450_000,
}

FEE_RATES = {
    "USD": 0.0015,
    "EUR": 0.0018,
    "GBP": 0.0020,
    "JPY": 0.0008,
    "CHF": 0.0016,
}

MINIMUM_FEES = {
    "USD": 25.00,
    "EUR": 22.00,
    "GBP": 28.00,
    "JPY": 3000.00,
    "CHF": 24.00,
}

PAYMENT_STATUSES = ["COMPLETED", "FAILED", "PENDING", "RETURNED"]
STATUS_WEIGHTS = [0.55, 0.25, 0.10, 0.10]

SWIFT_FAILURE_CODES = [
    "AC01", "AC04", "AC06", "AG01", "AM04",
    "BE04", "CNOR", "FF01", "MS03", "RC01", "TM01", "DUPL",
]

SWIFT_STATUS_CODE_DEFS = {
    "AC01": {
        "description": "Incorrect Account Number",
        "category": "ACCOUNT_ISSUE",
        "severity": "HIGH",
    },
    "AC04": {
        "description": "Closed Account Number",
        "category": "ACCOUNT_ISSUE",
        "severity": "HIGH",
    },
    "AC06": {
        "description": "Blocked Account",
        "category": "ACCOUNT_ISSUE",
        "severity": "CRITICAL",
    },
    "AG01": {
        "description": "Transaction Forbidden on Regulatory Grounds",
        "category": "COMPLIANCE_ISSUE",
        "severity": "CRITICAL",
    },
    "AM04": {
        "description": "Insufficient Funds in Nostro Account",
        "category": "INSUFFICIENT_FUNDS",
        "severity": "HIGH",
    },
    "BE04": {
        "description": "Missing Creditor Address",
        "category": "COMPLIANCE_ISSUE",
        "severity": "MEDIUM",
    },
    "CNOR": {
        "description": "Creditor Bank Is Not Registered",
        "category": "BANK_ROUTING_ERROR",
        "severity": "HIGH",
    },
    "FF01": {
        "description": "Invalid File Format",
        "category": "FORMAT_ERROR",
        "severity": "MEDIUM",
    },
    "MS03": {
        "description": "Reason Not Specified by Agent",
        "category": "UNSPECIFIED",
        "severity": "MEDIUM",
    },
    "RC01": {
        "description": "Bank Identifier Incorrect",
        "category": "BANK_ROUTING_ERROR",
        "severity": "HIGH",
    },
    "TM01": {
        "description": "Cut Off Time Exceeded",
        "category": "CUTOFF_EXCEEDED",
        "severity": "LOW",
    },
    "DUPL": {
        "description": "Duplicate Payment Detected",
        "category": "DUPLICATE_PAYMENT",
        "severity": "MEDIUM",
    },
    "FOCR": {
        "description": "Following Cancellation Request",
        "category": "CANCELLATION",
        "severity": "LOW",
    },
    "CUST": {
        "description": "Requested By Customer",
        "category": "CANCELLATION",
        "severity": "LOW",
    },
}

ROOT_CAUSE_INTERVENTIONS = {
    "ACCOUNT_ISSUE": "Contact beneficiary bank to verify account details. Request updated account information from customer. Resubmit with corrected account number once confirmed.",
    "COMPLIANCE_ISSUE": "Escalate to compliance team for review. Obtain all required documentation from the originator. Resubmit only after compliance clearance is granted.",
    "INSUFFICIENT_FUNDS": "Alert treasury desk immediately. Arrange emergency funding for the nostro account. Requeue payment once sufficient balance is confirmed.",
    "BANK_ROUTING_ERROR": "Verify correspondent BIC against the SWIFT directory. Contact the correspondent bank to confirm routing. Resubmit with validated routing information.",
    "FORMAT_ERROR": "Review the original SWIFT message for formatting issues. Correct the message fields according to MT103 standards. Resubmit the corrected message.",
    "CUTOFF_EXCEEDED": "Schedule resubmission for the next available business day. Notify the customer of the delayed value date. No manual correction needed beyond requeue.",
    "DUPLICATE_PAYMENT": "Confirm the duplicate status by cross-checking references. Cancel the duplicate instance. Ensure only one payment is processed and reconciled.",
    "UNSPECIFIED": "Contact correspondent bank operations desk for clarification on rejection reason. Document response and determine appropriate remediation.",
    "CANCELLATION": "Confirm cancellation instruction with the originating customer. Process refund or credit to customer account. Update records to reflect final cancelled status.",
    "BANK_INACTIVE": "Identify an alternative active correspondent in the same jurisdiction. Reroute the payment through the new correspondent. Update standing instructions for future payments.",
}

BANKS_DATA = [
    ("DEUTDEFF", "Deutsche Bank AG", "DE", 1, "LOW"),
    ("BNPAFRPP", "BNP Paribas SA", "FR", 1, "LOW"),
    ("CHASUS33", "JPMorgan Chase Bank", "US", 1, "LOW"),
    ("BARCGB22", "Barclays Bank PLC", "GB", 1, "LOW"),
    ("UBSWCHZH", "UBS Group AG", "CH", 1, "MEDIUM"),
    ("CITIUS33", "Citibank NA", "US", 1, "LOW"),
    ("HSBCHKHH", "HSBC Hong Kong", "HK", 1, "MEDIUM"),
    ("SCBLSGSG", "Standard Chartered Singapore", "SG", 1, "MEDIUM"),
    ("MABORUMM", "Meridian Apex Bank Romania", "RO", 0, "HIGH"),
    ("NWBKGB2L", "NatWest Group PLC", "GB", 1, "LOW"),
    ("COBADEFF", "Commerzbank AG", "DE", 1, "LOW"),
    ("SOGEGB2L", "Societe Generale UK", "GB", 1, "MEDIUM"),
    ("BOFAUS3N", "Bank of America NA", "US", 1, "LOW"),
    ("ANZBAU3M", "ANZ Banking Group", "AU", 1, "MEDIUM"),
    ("TRCKJPTK", "TransConnect Japan KK", "JP", 0, "HIGH"),
    ("BKTRUS33", "Bank of New York Mellon", "US", 1, "LOW"),
    ("CRESCHZZ", "Credit Suisse AG", "CH", 1, "MEDIUM"),
    ("MIDLGB22", "HSBC UK Bank PLC", "GB", 1, "LOW"),
]

BASE_DATE = datetime(2024, 1, 8)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _business_days(start, count):
    """Return a list of `count` business days starting from `start`."""
    days = []
    d = start
    while len(days) < count:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _round2(val):
    return round(float(val), 2)


# ── Table Creation ───────────────────────────────────────────────────────────

def create_tables(conn):
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS correspondent_banks (
        id INTEGER PRIMARY KEY,
        bic_code TEXT UNIQUE NOT NULL,
        bank_name TEXT NOT NULL,
        country TEXT NOT NULL,
        is_active INTEGER NOT NULL,
        risk_rating TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY,
        payment_ref TEXT UNIQUE NOT NULL,
        customer_id TEXT NOT NULL,
        customer_name TEXT NOT NULL,
        amount REAL NOT NULL,
        currency TEXT NOT NULL,
        sender_bic TEXT NOT NULL,
        receiver_bic TEXT NOT NULL,
        initiated_date TEXT NOT NULL,
        value_date TEXT NOT NULL,
        status TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS swift_messages (
        id INTEGER PRIMARY KEY,
        payment_ref TEXT NOT NULL,
        message_type TEXT NOT NULL,
        status_code TEXT,
        timestamp TEXT NOT NULL,
        narrative TEXT,
        FOREIGN KEY (payment_ref) REFERENCES payments(payment_ref)
    );
    CREATE TABLE IF NOT EXISTS nostro_entries (
        id INTEGER PRIMARY KEY,
        account_id TEXT NOT NULL,
        entry_date TEXT NOT NULL,
        value_date TEXT NOT NULL,
        dc_indicator TEXT NOT NULL,
        amount REAL NOT NULL,
        currency TEXT NOT NULL,
        payment_ref TEXT NOT NULL,
        balance_after REAL NOT NULL,
        FOREIGN KEY (payment_ref) REFERENCES payments(payment_ref)
    );
    CREATE TABLE IF NOT EXISTS fee_records (
        id INTEGER PRIMARY KEY,
        payment_ref TEXT UNIQUE NOT NULL,
        fee_type TEXT NOT NULL,
        expected_amount REAL NOT NULL,
        actual_amount REAL NOT NULL,
        currency TEXT NOT NULL,
        charged_date TEXT NOT NULL,
        FOREIGN KEY (payment_ref) REFERENCES payments(payment_ref)
    );
    """)
    conn.commit()


# ── Data Generation ──────────────────────────────────────────────────────────

def generate_correspondent_banks(conn):
    c = conn.cursor()
    for i, (bic, name, country, active, risk) in enumerate(BANKS_DATA, 1):
        c.execute(
            "INSERT INTO correspondent_banks VALUES (?,?,?,?,?,?)",
            (i, bic, name, country, active, risk),
        )
    conn.commit()


def generate_payments(conn, fake, n):
    """Generate n payment records. Returns the list of payment dicts."""
    bic_list = [b[0] for b in BANKS_DATA]
    active_bics = [b[0] for b in BANKS_DATA if b[3] == 1]
    inactive_bics = [b[0] for b in BANKS_DATA if b[3] == 0]

    biz_days = _business_days(BASE_DATE, max(30, n // 2))

    payments = []
    c = conn.cursor()

    for i in range(n):
        pid = i + 1
        ref = f"PAY-{pid:05d}"
        cust_id = f"CUST-{np.random.randint(1000, 9999)}"
        cust_name = fake.name()
        ccy = np.random.choice(CURRENCIES)
        lo, hi = AMOUNT_RANGES[ccy]
        amount = _round2(np.random.uniform(lo, hi))
        sender_bic = np.random.choice(active_bics)

        status = np.random.choice(PAYMENT_STATUSES, p=STATUS_WEIGHTS)

        # For ~15% of FAILED payments, route to an inactive bank to trigger BANK_INACTIVE
        if status == "FAILED" and np.random.random() < 0.15 and inactive_bics:
            receiver_bic = np.random.choice(inactive_bics)
        else:
            receiver_bic = np.random.choice(bic_list)
            while receiver_bic == sender_bic:
                receiver_bic = np.random.choice(bic_list)

        init_date = np.random.choice(biz_days)
        val_date = init_date + timedelta(days=int(np.random.choice([1, 2, 3])))

        c.execute(
            "INSERT INTO payments VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                pid, ref, cust_id, cust_name, amount, ccy,
                sender_bic, receiver_bic,
                init_date.strftime("%Y-%m-%d"),
                val_date.strftime("%Y-%m-%d"),
                status,
            ),
        )

        payments.append({
            "id": pid,
            "payment_ref": ref,
            "customer_id": cust_id,
            "customer_name": cust_name,
            "amount": amount,
            "currency": ccy,
            "sender_bic": sender_bic,
            "receiver_bic": receiver_bic,
            "initiated_date": init_date.strftime("%Y-%m-%d"),
            "value_date": val_date.strftime("%Y-%m-%d"),
            "status": status,
        })

    conn.commit()
    return payments


def generate_swift_messages(conn, fake, payments):
    """Generate SWIFT message trails for each payment."""
    c = conn.cursor()
    msg_id = 0

    for p in payments:
        ref = p["payment_ref"]
        init_dt = datetime.strptime(p["initiated_date"], "%Y-%m-%d")
        status = p["status"]

        # MT103 — initial transfer message
        msg_id += 1
        ts1 = init_dt.replace(hour=9, minute=np.random.randint(0, 59))
        c.execute(
            "INSERT INTO swift_messages VALUES (?,?,?,?,?,?)",
            (msg_id, ref, "MT103", None, ts1.strftime("%Y-%m-%d %H:%M:%S"),
             f"Customer transfer {ref} initiated"),
        )

        if status == "COMPLETED":
            # MT900 debit confirmation, then MT910 credit confirmation
            msg_id += 1
            ts2 = ts1 + timedelta(hours=np.random.randint(1, 4))
            c.execute(
                "INSERT INTO swift_messages VALUES (?,?,?,?,?,?)",
                (msg_id, ref, "MT900", None, ts2.strftime("%Y-%m-%d %H:%M:%S"),
                 f"Debit confirmed for {ref}"),
            )
            msg_id += 1
            ts3 = ts2 + timedelta(hours=np.random.randint(1, 6))
            c.execute(
                "INSERT INTO swift_messages VALUES (?,?,?,?,?,?)",
                (msg_id, ref, "MT910", None, ts3.strftime("%Y-%m-%d %H:%M:%S"),
                 f"Credit confirmed for {ref}"),
            )

        elif status == "FAILED":
            # Some get a debit confirmation before failure, some don't
            has_debit = np.random.random() < 0.6
            if has_debit:
                msg_id += 1
                ts2 = ts1 + timedelta(hours=np.random.randint(1, 3))
                c.execute(
                    "INSERT INTO swift_messages VALUES (?,?,?,?,?,?)",
                    (msg_id, ref, "MT900", None, ts2.strftime("%Y-%m-%d %H:%M:%S"),
                     f"Debit confirmed for {ref}"),
                )
                ts_fail = ts2 + timedelta(hours=np.random.randint(2, 8))
            else:
                ts_fail = ts1 + timedelta(hours=np.random.randint(1, 6))

            # Rejection message
            code = np.random.choice(SWIFT_FAILURE_CODES)
            # If receiver is inactive, override to CNOR
            receiver_active = any(
                b[0] == p["receiver_bic"] and b[3] == 1 for b in BANKS_DATA
            )
            if not receiver_active:
                code = "CNOR"

            msg_id += 1
            c.execute(
                "INSERT INTO swift_messages VALUES (?,?,?,?,?,?)",
                (msg_id, ref, "MT199", code, ts_fail.strftime("%Y-%m-%d %H:%M:%S"),
                 f"Rejection: {SWIFT_STATUS_CODE_DEFS.get(code, {}).get('description', code)}"),
            )

        elif status == "RETURNED":
            # Debit, credit, then return
            msg_id += 1
            ts2 = ts1 + timedelta(hours=np.random.randint(1, 3))
            c.execute(
                "INSERT INTO swift_messages VALUES (?,?,?,?,?,?)",
                (msg_id, ref, "MT900", None, ts2.strftime("%Y-%m-%d %H:%M:%S"),
                 f"Debit confirmed for {ref}"),
            )
            msg_id += 1
            ts3 = ts2 + timedelta(hours=np.random.randint(1, 4))
            c.execute(
                "INSERT INTO swift_messages VALUES (?,?,?,?,?,?)",
                (msg_id, ref, "MT910", None, ts3.strftime("%Y-%m-%d %H:%M:%S"),
                 f"Credit confirmed for {ref}"),
            )
            msg_id += 1
            ts4 = ts3 + timedelta(days=np.random.randint(1, 3))
            ret_code = np.random.choice(["FOCR", "CUST"])
            c.execute(
                "INSERT INTO swift_messages VALUES (?,?,?,?,?,?)",
                (msg_id, ref, "MT103", ret_code, ts4.strftime("%Y-%m-%d %H:%M:%S"),
                 f"Return: {SWIFT_STATUS_CODE_DEFS[ret_code]['description']}"),
            )

        elif status == "PENDING":
            # Just MT103, maybe an MT199 query with no code
            if np.random.random() < 0.5:
                msg_id += 1
                ts2 = ts1 + timedelta(hours=np.random.randint(4, 24))
                c.execute(
                    "INSERT INTO swift_messages VALUES (?,?,?,?,?,?)",
                    (msg_id, ref, "MT199", None, ts2.strftime("%Y-%m-%d %H:%M:%S"),
                     f"Status query pending for {ref}"),
                )

    conn.commit()


def generate_nostro_entries(conn, payments):
    """Generate nostro account entries."""
    c = conn.cursor()
    entry_id = 0
    running_balances = {}  # per (account_id, currency)

    for p in payments:
        ref = p["payment_ref"]
        ccy = p["currency"]
        amount = p["amount"]
        status = p["status"]
        init_date = p["initiated_date"]
        val_date = p["value_date"]
        sender = p["sender_bic"]
        account_id = f"NOSTRO-{sender}-{ccy}"

        if account_id not in running_balances:
            running_balances[account_id] = _round2(np.random.uniform(5_000_000, 50_000_000))

        if status == "COMPLETED":
            # Debit entry
            entry_id += 1
            running_balances[account_id] = _round2(running_balances[account_id] - amount)
            c.execute(
                "INSERT INTO nostro_entries VALUES (?,?,?,?,?,?,?,?,?)",
                (entry_id, account_id, init_date, val_date, "D", amount, ccy, ref,
                 running_balances[account_id]),
            )

        elif status == "FAILED":
            # Check if this failure had a debit (from swift_messages)
            row = c.execute(
                "SELECT COUNT(*) FROM swift_messages WHERE payment_ref=? AND message_type='MT900'",
                (ref,),
            ).fetchone()
            has_debit = row[0] > 0
            if has_debit:
                entry_id += 1
                running_balances[account_id] = _round2(running_balances[account_id] - amount)
                c.execute(
                    "INSERT INTO nostro_entries VALUES (?,?,?,?,?,?,?,?,?)",
                    (entry_id, account_id, init_date, val_date, "D", amount, ccy, ref,
                     running_balances[account_id]),
                )
                # Some get reversed
                if np.random.random() < 0.35:
                    entry_id += 1
                    running_balances[account_id] = _round2(running_balances[account_id] + amount)
                    rev_date = (datetime.strptime(val_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                    c.execute(
                        "INSERT INTO nostro_entries VALUES (?,?,?,?,?,?,?,?,?)",
                        (entry_id, account_id, rev_date, rev_date, "C", amount, ccy, ref,
                         running_balances[account_id]),
                    )

        elif status == "RETURNED":
            # Debit then credit (return)
            entry_id += 1
            running_balances[account_id] = _round2(running_balances[account_id] - amount)
            c.execute(
                "INSERT INTO nostro_entries VALUES (?,?,?,?,?,?,?,?,?)",
                (entry_id, account_id, init_date, val_date, "D", amount, ccy, ref,
                 running_balances[account_id]),
            )
            entry_id += 1
            ret_date = (datetime.strptime(val_date, "%Y-%m-%d") + timedelta(days=np.random.randint(1, 3))).strftime("%Y-%m-%d")
            running_balances[account_id] = _round2(running_balances[account_id] + amount)
            c.execute(
                "INSERT INTO nostro_entries VALUES (?,?,?,?,?,?,?,?,?)",
                (entry_id, account_id, ret_date, ret_date, "C", amount, ccy, ref,
                 running_balances[account_id]),
            )

        elif status == "PENDING":
            # Debit only
            entry_id += 1
            running_balances[account_id] = _round2(running_balances[account_id] - amount)
            c.execute(
                "INSERT INTO nostro_entries VALUES (?,?,?,?,?,?,?,?,?)",
                (entry_id, account_id, init_date, val_date, "D", amount, ccy, ref,
                 running_balances[account_id]),
            )

    conn.commit()


def generate_fee_records(conn, payments):
    """Generate fee records. For some failed payments, introduce discrepancies."""
    c = conn.cursor()

    for i, p in enumerate(payments):
        ref = p["payment_ref"]
        ccy = p["currency"]
        amount = p["amount"]
        status = p["status"]
        init_date = p["initiated_date"]

        expected = _round2(max(amount * FEE_RATES[ccy], MINIMUM_FEES[ccy]))

        # Introduce fee discrepancies for ~30% of FAILED payments
        if status == "FAILED" and np.random.random() < 0.30:
            # Fee overcharge or undercharge
            factor = np.random.choice([1.15, 1.25, 1.50, 0.0])
            actual = _round2(expected * factor)
        else:
            actual = expected

        c.execute(
            "INSERT INTO fee_records VALUES (?,?,?,?,?,?,?)",
            (i + 1, ref, "WIRE_FEE", expected, actual, ccy, init_date),
        )

    conn.commit()


# ── Workspace Generation ─────────────────────────────────────────────────────

def generate_workspace_configs(workspace):
    """Generate fixed configuration files."""

    # 1. SWIFT status codes
    with open(os.path.join(workspace, "swift_status_codes.json"), "w") as f:
        json.dump(SWIFT_STATUS_CODE_DEFS, f, indent=2)

    # 2. High-value thresholds
    with open(os.path.join(workspace, "high_value_thresholds.json"), "w") as f:
        json.dump({
            "description": "Payments at or above these amounts (in local currency) are classified as high-value.",
            "thresholds": HIGH_VALUE_THRESHOLDS,
        }, f, indent=2)

    # 3. Fee corridor config
    with open(os.path.join(workspace, "fee_corridor_config.yaml"), "w") as f:
        yaml.dump({
            "fee_calculation": {
                "method": "percentage_with_minimum",
                "description": "Expected fee = max(amount * rate, minimum). Compare against actual charged.",
            },
            "fee_rates": FEE_RATES,
            "minimum_fees": MINIMUM_FEES,
        }, f, default_flow_style=False, sort_keys=False)

    # 4. Reconciliation rules
    with open(os.path.join(workspace, "reconciliation_rules.yaml"), "w") as f:
        yaml.dump({
            "priority_determination": {
                "rules": [
                    {"condition": "correspondent bank is inactive", "priority": "CRITICAL"},
                    {"condition": "root cause category is INSUFFICIENT_FUNDS", "priority": "CRITICAL"},
                    {"condition": "customer urgency is CRITICAL", "priority": "CRITICAL"},
                    {"condition": "amount exceeds twice the high-value threshold for its currency",
                     "priority": "HIGH"},
                    {"condition": "customer urgency is URGENT", "priority": "HIGH"},
                    {"condition": "fee discrepancy exceeds 20 percent of expected fee", "priority": "HIGH"},
                    {"condition": "none of the above apply", "priority": "MEDIUM"},
                ],
                "note": "Rules are evaluated top to bottom. First match wins.",
            },
            "sort_order": {
                "primary": "priority (CRITICAL first, then HIGH, then MEDIUM)",
                "secondary": "amount descending within each priority group",
            },
            "nostro_impact_classification": {
                "STRANDED_DEBIT": "A debit exists on the nostro account with no corresponding reversal credit.",
                "REVERSED": "A debit exists and has been reversed by a subsequent credit entry.",
                "NO_DEBIT": "No debit was posted to the nostro account for this payment.",
            },
        }, f, default_flow_style=False, sort_keys=False)

    # 5. Escalation procedures
    with open(os.path.join(workspace, "escalation_procedures.md"), "w") as f:
        f.write("Each failed payment must be assigned a manual intervention description "
                "based on the root cause category determined from the SWIFT rejection code "
                "and correspondent bank status. When the correspondent bank used for a "
                "payment is flagged as inactive, the root cause must be overridden to "
                "BANK_INACTIVE regardless of the SWIFT status code.\n\n")
        for cause, steps in ROOT_CAUSE_INTERVENTIONS.items():
            f.write(f"{cause}: {steps}\n\n")


def generate_nostro_statements(workspace, conn, n_files):
    """Generate daily nostro statement CSV files with reconciliation flags."""
    c = conn.cursor()

    # Get all nostro entries
    entries = c.execute("""
        SELECT ne.id, ne.account_id, ne.entry_date, ne.value_date, ne.dc_indicator,
               ne.amount, ne.currency, ne.payment_ref, ne.balance_after,
               p.status
        FROM nostro_entries ne
        JOIN payments p ON ne.payment_ref = p.payment_ref
        ORDER BY ne.entry_date, ne.id
    """).fetchall()

    if not entries:
        return

    # Determine date range and distribute across files
    all_dates = sorted(set(e[2] for e in entries))

    # Distribute dates across files
    dates_per_file = max(1, len(all_dates) // n_files)
    file_date_groups = []
    for i in range(n_files):
        start_idx = i * dates_per_file
        if i == n_files - 1:
            end_idx = len(all_dates)
        else:
            end_idx = (i + 1) * dates_per_file
        if start_idx < len(all_dates):
            file_date_groups.append(all_dates[start_idx:end_idx])

    # Find which payment_refs have both D and C entries (reversed)
    reversed_refs = set()
    debit_refs = set()
    for e in entries:
        if e[4] == "D":
            debit_refs.add(e[7])
        elif e[4] == "C":
            reversed_refs.add(e[7])

    for idx, date_group in enumerate(file_date_groups):
        if not date_group:
            continue
        fname = f"nostro_statement_{date_group[0].replace('-', '')}_to_{date_group[-1].replace('-', '')}.csv"
        fpath = os.path.join(workspace, fname)

        with open(fpath, "w", newline="") as csvf:
            writer = csv.writer(csvf)
            writer.writerow([
                "entry_id", "account_id", "entry_date", "value_date",
                "dc_indicator", "amount", "currency", "reference",
                "balance_after", "reconciliation_flag", "operator_notes",
            ])

            for e in entries:
                if e[2] not in date_group:
                    continue
                eid, acct, edate, vdate, dc, amt, ccy, pref, bal, pstatus = e

                # Determine reconciliation flag
                if pstatus == "COMPLETED":
                    flag = "MATCHED"
                    note = "Settled"
                elif pstatus == "RETURNED":
                    if dc == "C":
                        flag = "MATCHED"
                        note = "Return credit processed"
                    else:
                        flag = "MATCHED"
                        note = "Original debit - returned"
                elif pstatus == "FAILED":
                    if dc == "D":
                        if pref in reversed_refs:
                            flag = "MATCHED"
                            note = "Debit reversed after failure"
                        else:
                            flag = "UNMATCHED"
                            note = "Debit pending reversal - payment failed"
                    else:
                        flag = "MATCHED"
                        note = "Reversal credit for failed payment"
                elif pstatus == "PENDING":
                    flag = "PENDING_REVIEW"
                    note = "Awaiting settlement confirmation"
                else:
                    flag = "UNKNOWN"
                    note = ""

                writer.writerow([eid, acct, edate, vdate, dc, f"{amt:.2f}", ccy, pref, f"{bal:.2f}", flag, note])


def generate_customer_batches(workspace, conn, n_files):
    """Generate customer batch JSON files with urgency/instructions."""
    fake = Faker()
    Faker.seed(42)
    np.random.seed(42 + 1000)  # offset seed for this section

    c = conn.cursor()
    payments = c.execute("""
        SELECT payment_ref, customer_id, customer_name, amount, currency, receiver_bic, initiated_date
        FROM payments ORDER BY id
    """).fetchall()

    urgency_levels = ["STANDARD", "URGENT", "CRITICAL"]
    urgency_weights = [0.65, 0.25, 0.10]

    instructions_pool = [
        "Please process at earliest convenience.",
        "Beneficiary expecting funds by value date.",
        "Regulatory deadline - must settle by end of week.",
        "Customer VIP - prioritize accordingly.",
        "Part of structured trade finance deal.",
        "Related to import letter of credit.",
        "Recurring scheduled payment.",
        "First-time payment to this beneficiary.",
        "Urgent supplier payment - production line dependent.",
        "Intercompany transfer - standard processing.",
    ]

    per_file = max(1, len(payments) // n_files)

    for idx in range(n_files):
        start = idx * per_file
        if idx == n_files - 1:
            batch_payments = payments[start:]
        else:
            batch_payments = payments[start:start + per_file]

        if not batch_payments:
            continue

        batch = {
            "batch_id": f"BATCH-{idx + 1:03d}",
            "submission_date": batch_payments[0][6],
            "total_payments": len(batch_payments),
            "payments": [],
        }

        for pay in batch_payments:
            urgency = np.random.choice(urgency_levels, p=urgency_weights)
            instr = np.random.choice(instructions_pool)
            batch["payments"].append({
                "payment_ref": pay[0],
                "customer_id": pay[1],
                "customer_name": pay[2],
                "amount": pay[3],
                "currency": pay[4],
                "beneficiary_bic": pay[5],
                "urgency": urgency,
                "special_instructions": instr,
            })

        fpath = os.path.join(workspace, f"customer_batch_{idx + 1:03d}.json")
        with open(fpath, "w") as f:
            json.dump(batch, f, indent=2)


# ── Main ─────────────────────────────────────────────────────────────────────

def main(db_path, workspace):
    np.random.seed(42)
    Faker.seed(42)
    fake = Faker()
    fake.seed_instance(42)

    os.makedirs(workspace, exist_ok=True)

    # Remove old DB if exists
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    create_tables(conn)

    # Generate DB data
    generate_correspondent_banks(conn)
    payments = generate_payments(conn, fake, SCALE["rows_per_table"])
    generate_swift_messages(conn, fake, payments)
    generate_nostro_entries(conn, payments)
    generate_fee_records(conn, payments)

    # Generate workspace files
    n_files = SCALE["num_workspace_files"]
    n_nostro_files = n_files // 2
    n_batch_files = n_files - n_nostro_files

    generate_workspace_configs(workspace)
    generate_nostro_statements(workspace, conn, n_nostro_files)
    generate_customer_batches(workspace, conn, n_batch_files)

    conn.close()
    print(f"Data generated: {db_path}, workspace at {workspace}/")
    print(f"  Tables: correspondent_banks, payments, swift_messages, nostro_entries, fee_records")
    print(f"  Workspace files: {len(os.listdir(workspace))}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
