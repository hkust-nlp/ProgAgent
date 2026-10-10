"""
Data generator for the Contract Amendment Impact Report task.
Generates a SQLite database and workspace files for cross-referencing
MSA clauses, change orders, vendor certifications, and milestone payments.
"""

import argparse
import os
import sqlite3
import json
import csv
import math
import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 240,
    "num_workspace_files": 32,
}

# ---------------------------------------------------------------------------
# Seed everything
# ---------------------------------------------------------------------------
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ---------------------------------------------------------------------------
# Reference date for expiry / overdue checks
# ---------------------------------------------------------------------------
REFERENCE_DATE = datetime(2026, 4, 22)

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------
CLAUSE_TYPES = [
    "payment_terms", "liability", "termination", "ip_rights",
    "confidentiality", "service_level", "indemnification", "data_protection",
]
COMPLIANCE_CATEGORIES = ["financial", "operational", "legal", "safety"]
CHANGE_ORDER_STATUSES = ["active", "pending_review", "approved", "rejected"]
CHANGE_ORDER_STATUS_WEIGHTS = [0.60, 0.15, 0.15, 0.10]
PRIORITIES = ["low", "medium", "high", "critical"]
PAYMENT_STATUSES = ["scheduled", "paid", "overdue", "disputed"]
PAYMENT_STATUS_WEIGHTS = [0.35, 0.30, 0.20, 0.15]
SIGNATORY_TITLES = [
    "Project Manager", "Department Director",
    "Vice President", "Chief Executive Officer",
]
CERT_NAMES = {
    "financial": ["SOC 2 Type II", "ISO 27001 Financial Controls", "PCI DSS"],
    "operational": ["ISO 9001", "CMMI Level 3", "ITIL Foundation"],
    "legal": ["Legal Compliance Cert", "GDPR Compliance", "HIPAA Compliance"],
    "safety": ["OSHA Certification", "ISO 45001", "Safety Management Cert"],
}


# ========================================================================== #
#  Helpers                                                                    #
# ========================================================================== #
def _rand_date(start: datetime, end: datetime) -> str:
    """Return a random date string between *start* and *end*."""
    delta = (end - start).days
    if delta <= 0:
        return start.strftime("%Y-%m-%d")
    return (start + timedelta(days=random.randint(0, delta))).strftime("%Y-%m-%d")


def _rand_amount(lo: float, hi: float) -> float:
    return round(random.uniform(lo, hi), 2)


# ========================================================================== #
#  Database creation                                                          #
# ========================================================================== #
def create_tables(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS contracts (
        contract_id   TEXT PRIMARY KEY,
        contract_name TEXT NOT NULL,
        vendor_id     TEXT NOT NULL,
        start_date    TEXT NOT NULL,
        end_date      TEXT NOT NULL,
        total_value   REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS vendors (
        vendor_id       TEXT PRIMARY KEY,
        vendor_name     TEXT NOT NULL,
        primary_contact TEXT NOT NULL,
        signatory_name  TEXT NOT NULL,
        signatory_title TEXT NOT NULL,
        signatory_level INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS msa_clauses (
        clause_id            TEXT PRIMARY KEY,
        contract_id          TEXT NOT NULL,
        clause_number        TEXT NOT NULL,
        clause_type          TEXT NOT NULL,
        clause_text          TEXT NOT NULL,
        amendment_threshold  REAL NOT NULL,
        compliance_category  TEXT NOT NULL,
        requires_signatory_level INTEGER NOT NULL,
        FOREIGN KEY (contract_id) REFERENCES contracts(contract_id)
    );

    CREATE TABLE IF NOT EXISTS change_orders (
        order_id             TEXT PRIMARY KEY,
        contract_id          TEXT NOT NULL,
        clause_id            TEXT NOT NULL,
        requested_by         TEXT NOT NULL,
        change_description   TEXT NOT NULL,
        cost_impact          REAL NOT NULL,
        schedule_impact_days INTEGER NOT NULL,
        priority             TEXT NOT NULL,
        status               TEXT NOT NULL,
        submission_date      TEXT NOT NULL,
        FOREIGN KEY (contract_id) REFERENCES contracts(contract_id),
        FOREIGN KEY (clause_id) REFERENCES msa_clauses(clause_id)
    );

    CREATE TABLE IF NOT EXISTS vendor_certifications (
        cert_id              TEXT PRIMARY KEY,
        vendor_id            TEXT NOT NULL,
        compliance_category  TEXT NOT NULL,
        certification_name   TEXT NOT NULL,
        issue_date           TEXT NOT NULL,
        expiry_date          TEXT NOT NULL,
        certification_level  INTEGER NOT NULL,
        FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id)
    );

    CREATE TABLE IF NOT EXISTS milestone_payments (
        payment_id       TEXT PRIMARY KEY,
        contract_id      TEXT NOT NULL,
        milestone_name   TEXT NOT NULL,
        milestone_number INTEGER NOT NULL,
        due_date         TEXT NOT NULL,
        amount           REAL NOT NULL,
        status           TEXT NOT NULL,
        linked_clause_id TEXT,
        FOREIGN KEY (contract_id) REFERENCES contracts(contract_id),
        FOREIGN KEY (linked_clause_id) REFERENCES msa_clauses(clause_id)
    );
    """)
    conn.commit()


# ========================================================================== #
#  Data generation                                                            #
# ========================================================================== #
def generate_vendors(n: int):
    vendors = []
    for i in range(n):
        level = int(np.random.choice([1, 2, 3, 4], p=[0.30, 0.30, 0.25, 0.15]))
        vendors.append({
            "vendor_id": f"V-{i + 1:04d}",
            "vendor_name": fake.company(),
            "primary_contact": fake.name(),
            "signatory_name": fake.name(),
            "signatory_title": SIGNATORY_TITLES[level - 1],
            "signatory_level": level,
        })
    return vendors


def generate_contracts(n: int, vendors):
    contracts = []
    assigned = list(np.random.choice(
        [v["vendor_id"] for v in vendors], size=n, replace=False
    ))
    for i in range(n):
        start = REFERENCE_DATE - timedelta(days=random.randint(365, 1095))
        end = start + timedelta(days=random.randint(365, 1460))
        contracts.append({
            "contract_id": f"C-{i + 1:04d}",
            "contract_name": f"MSA-{fake.word().capitalize()}-{random.randint(100, 999)}",
            "vendor_id": assigned[i],
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "total_value": _rand_amount(100_000, 5_000_000),
        })
    return contracts


def generate_clauses(n: int, contracts):
    clauses = []
    contract_ids = [c["contract_id"] for c in contracts]
    # Track clause numbering per contract
    clause_counters = {cid: 0 for cid in contract_ids}
    thresholds = [25_000, 50_000, 75_000, 100_000, 150_000, 200_000]

    for i in range(n):
        cid = contract_ids[i % len(contract_ids)]
        clause_counters[cid] += 1
        section = (clause_counters[cid] - 1) // len(CLAUSE_TYPES) + 1
        subsection = ((clause_counters[cid] - 1) % len(CLAUSE_TYPES)) + 1
        clause_type = CLAUSE_TYPES[(i) % len(CLAUSE_TYPES)]
        cat = COMPLIANCE_CATEGORIES[i % len(COMPLIANCE_CATEGORIES)]
        level = int(np.random.choice([1, 2, 3, 4], p=[0.25, 0.35, 0.25, 0.15]))
        clauses.append({
            "clause_id": f"CL-{i + 1:04d}",
            "contract_id": cid,
            "clause_number": f"{section}.{subsection}",
            "clause_type": clause_type,
            "clause_text": fake.paragraph(nb_sentences=3),
            "amendment_threshold": float(random.choice(thresholds)),
            "compliance_category": cat,
            "requires_signatory_level": level,
        })
    return clauses


def generate_change_orders(n: int, contracts, clauses):
    orders = []
    contract_ids = [c["contract_id"] for c in contracts]
    # Map contract_id -> list of clause_ids
    clause_map = {}
    for cl in clauses:
        clause_map.setdefault(cl["contract_id"], []).append(cl["clause_id"])

    for i in range(n):
        cid = contract_ids[i % len(contract_ids)]
        clause_id = random.choice(clause_map[cid])
        status = np.random.choice(CHANGE_ORDER_STATUSES, p=CHANGE_ORDER_STATUS_WEIGHTS)
        priority = random.choice(PRIORITIES)
        # Cost impact: deliberately spread across threshold boundaries
        cost = _rand_amount(10_000, 300_000)
        schedule = random.randint(5, 120)
        orders.append({
            "order_id": f"CO-{i + 1:04d}",
            "contract_id": cid,
            "clause_id": clause_id,
            "requested_by": fake.name(),
            "change_description": fake.sentence(nb_words=10),
            "cost_impact": cost,
            "schedule_impact_days": schedule,
            "priority": str(priority),
            "status": str(status),
            "submission_date": _rand_date(
                REFERENCE_DATE - timedelta(days=180),
                REFERENCE_DATE - timedelta(days=5),
            ),
        })
    return orders


def generate_certifications(n: int, vendors):
    certs = []
    vendor_ids = [v["vendor_id"] for v in vendors]
    for i in range(n):
        vid = vendor_ids[i % len(vendor_ids)]
        cat = COMPLIANCE_CATEGORIES[i % len(COMPLIANCE_CATEGORIES)]
        cert_name = random.choice(CERT_NAMES[cat])
        # ~30% expired
        if random.random() < 0.30:
            issue = REFERENCE_DATE - timedelta(days=random.randint(730, 1095))
            expiry = REFERENCE_DATE - timedelta(days=random.randint(1, 365))
        else:
            issue = REFERENCE_DATE - timedelta(days=random.randint(90, 365))
            expiry = REFERENCE_DATE + timedelta(days=random.randint(30, 730))
        level = int(np.random.choice([1, 2, 3, 4, 5], p=[0.10, 0.20, 0.30, 0.25, 0.15]))
        certs.append({
            "cert_id": f"CERT-{i + 1:04d}",
            "vendor_id": vid,
            "compliance_category": cat,
            "certification_name": cert_name,
            "issue_date": issue.strftime("%Y-%m-%d"),
            "expiry_date": expiry.strftime("%Y-%m-%d"),
            "certification_level": level,
        })
    return certs


def generate_milestone_payments(n: int, contracts, clauses):
    payments = []
    contract_ids = [c["contract_id"] for c in contracts]
    clause_ids = [cl["clause_id"] for cl in clauses]

    for i in range(n):
        cid = contract_ids[i % len(contract_ids)]
        # Link ~60% of payments to a clause in the same contract
        linked = None
        contract_clauses = [cl["clause_id"] for cl in clauses if cl["contract_id"] == cid]
        if random.random() < 0.60 and contract_clauses:
            linked = random.choice(contract_clauses)
        status = str(np.random.choice(PAYMENT_STATUSES, p=PAYMENT_STATUS_WEIGHTS))
        if status == "overdue":
            due = _rand_date(REFERENCE_DATE - timedelta(days=180),
                             REFERENCE_DATE - timedelta(days=1))
        else:
            due = _rand_date(REFERENCE_DATE - timedelta(days=60),
                             REFERENCE_DATE + timedelta(days=365))
        payments.append({
            "payment_id": f"PAY-{i + 1:04d}",
            "contract_id": cid,
            "milestone_name": f"Milestone {i + 1} - {fake.bs().title()}",
            "milestone_number": i + 1,
            "due_date": due,
            "amount": _rand_amount(5_000, 500_000),
            "status": status,
            "linked_clause_id": linked,
        })
    return payments


# ========================================================================== #
#  Insert into DB                                                             #
# ========================================================================== #
def insert_data(conn, table, rows, columns):
    if not rows:
        return
    placeholders = ", ".join(["?"] * len(columns))
    col_str = ", ".join(columns)
    conn.executemany(
        f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})",
        [tuple(r[c] for c in columns) for r in rows],
    )
    conn.commit()


# ========================================================================== #
#  Workspace generation                                                       #
# ========================================================================== #
def generate_workspace(workspace: str, change_orders, vendors, payments,
                       contracts, clauses, certifications):
    os.makedirs(workspace, exist_ok=True)
    num_files = SCALE["num_workspace_files"]
    files_per_type = num_files // 4
    remainder = num_files % 4
    # Distribute remainder across types
    counts = [files_per_type] * 4
    for r in range(remainder):
        counts[r] += 1
    n_co_notes, n_vendor_audit, n_pay_adj, n_amend_hist = counts

    # ---- Fixed config files ----
    _write_compliance_rules(workspace)
    _write_signatory_matrix(workspace)
    _write_amendment_policy(workspace)

    # ---- Scalable: change_order_notes (JSON) ----
    _write_change_order_notes(workspace, change_orders, n_co_notes)

    # ---- Scalable: vendor_audit (TXT) ----
    _write_vendor_audits(workspace, vendors, n_vendor_audit)

    # ---- Scalable: payment_adjustment (CSV) ----
    _write_payment_adjustments(workspace, payments, n_pay_adj)

    # ---- Scalable: amendment_history (YAML) ----
    _write_amendment_history(workspace, contracts, n_amend_hist)


def _write_compliance_rules(workspace: str):
    """Write compliance_rules.yaml with thresholds and rules."""
    content = """# Compliance Rules Configuration
# Reference date for expiry checks
reference_date: "2026-04-22"

# Maximum allowed schedule impact days by priority
max_schedule_days:
  low: 90
  medium: 60
  high: 30
  critical: 14

# Risk rating threshold for payment risk non-compliance
risk_threshold: 3

# Minimum certification level by compliance category
min_cert_level:
  financial: 3
  operational: 2
  legal: 4
  safety: 3

# Prior amendment count above which signatory level escalates by 1
escalation_threshold: 3

# Recognized non-compliance types
non_compliance_types:
  - threshold_breach
  - schedule_violation
  - payment_risk
  - certification_gap
"""
    with open(os.path.join(workspace, "compliance_rules.yaml"), "w") as f:
        f.write(content)


def _write_signatory_matrix(workspace: str):
    """Write signatory_matrix.json mapping cost impact to required signatory level."""
    matrix = {
        "levels": [
            {"min_cost": 0, "max_cost": 50000, "required_level": 1},
            {"min_cost": 50000, "max_cost": 150000, "required_level": 2},
            {"min_cost": 150000, "max_cost": 300000, "required_level": 3},
            {"min_cost": 300000, "max_cost": None, "required_level": 4},
        ],
        "level_titles": {
            "1": "Project Manager",
            "2": "Department Director",
            "3": "Vice President",
            "4": "Chief Executive Officer",
        },
    }
    with open(os.path.join(workspace, "signatory_matrix.json"), "w") as f:
        json.dump(matrix, f, indent=2)


def _write_amendment_policy(workspace: str):
    """Write amendment_policy.md with general policy text."""
    content = """# Amendment Policy

All contract amendments must be reviewed against the master service agreement
before execution. Any change order whose cost impact exceeds the amendment
threshold specified in the corresponding MSA clause requires elevated signatory
approval as defined in the signatory matrix.

Non-compliance is triggered when any of the following conditions hold for an
active change order:

A threshold breach occurs when the cost impact of a change order exceeds
the amendment threshold of its linked MSA clause and the contracting vendor
does not hold a valid (non-expired) certification in the compliance category
of that clause.

A schedule violation occurs when the schedule impact in days exceeds the
maximum allowed for the change order's stated priority level.

A payment risk arises when a milestone payment linked to the same clause as
the change order has an overdue status and the change order carries a risk
rating at or above the configured threshold.

A certification gap is identified when the vendor has an active penalty flag
from an audit and the vendor's certification level in the relevant compliance
category falls below the configured minimum.

When determining the required signatory level for a non-compliant change order,
start with the base level from the signatory matrix (determined by cost impact),
then escalate by one level if the contract has more prior amendments than the
escalation threshold, and further ensure the level is at least three if the
change order requires legal review. The signatory level is capped at four.
"""
    with open(os.path.join(workspace, "amendment_policy.md"), "w") as f:
        f.write(content)


def _write_change_order_notes(workspace: str, change_orders, num_files: int):
    """Write change_order_notes JSON files with risk ratings and review info."""
    # Only generate notes for orders (all of them, not just active)
    buckets = [[] for _ in range(num_files)]
    for idx, co in enumerate(change_orders):
        bucket = idx % num_files
        risk = int(np.random.choice([1, 2, 3, 4, 5], p=[0.15, 0.20, 0.25, 0.25, 0.15]))
        legal = bool(random.random() < 0.25)
        buckets[bucket].append({
            "order_id": co["order_id"],
            "risk_rating": risk,
            "reviewer_name": fake.name(),
            "review_date": _rand_date(
                REFERENCE_DATE - timedelta(days=60),
                REFERENCE_DATE - timedelta(days=1),
            ),
            "notes": fake.sentence(nb_words=12),
            "requires_legal_review": legal,
        })
    for i, bucket in enumerate(buckets):
        path = os.path.join(workspace, f"change_order_notes_{i + 1}.json")
        with open(path, "w") as f:
            json.dump(bucket, f, indent=2)


def _write_vendor_audits(workspace: str, vendors, num_files: int):
    """Write vendor_audit TXT files with penalty flags and audit findings."""
    buckets = [[] for _ in range(num_files)]
    for idx, v in enumerate(vendors):
        bucket = idx % num_files
        penalty = "Yes" if random.random() < 0.25 else "No"
        score = random.randint(40, 100)
        buckets[bucket].append(
            f"Vendor ID: {v['vendor_id']}\n"
            f"Vendor Name: {v['vendor_name']}\n"
            f"Audit Date: {_rand_date(REFERENCE_DATE - timedelta(days=180), REFERENCE_DATE - timedelta(days=10))}\n"
            f"Audit Score: {score}/100\n"
            f"Penalty Flag: {penalty}\n"
            f"Findings: {fake.paragraph(nb_sentences=2)}\n"
            f"Recommended Action: {fake.sentence(nb_words=8)}\n"
        )
    for i, bucket in enumerate(buckets):
        path = os.path.join(workspace, f"vendor_audit_{i + 1}.txt")
        with open(path, "w") as f:
            f.write("\n---\n".join(bucket))


def _write_payment_adjustments(workspace: str, payments, num_files: int):
    """Write payment_adjustment CSV files with adjustment percentages."""
    buckets = [[] for _ in range(num_files)]
    for idx, p in enumerate(payments):
        bucket = idx % num_files
        adj_pct = round(random.uniform(-15.0, 15.0), 2)
        buckets[bucket].append({
            "payment_id": p["payment_id"],
            "adjustment_percent": adj_pct,
            "adjustment_reason": random.choice([
                "scope_change", "delay_penalty", "early_completion_bonus",
                "material_cost_increase", "regulatory_update", "renegotiation",
            ]),
            "approved_by": fake.name(),
            "effective_date": _rand_date(
                REFERENCE_DATE - timedelta(days=90),
                REFERENCE_DATE + timedelta(days=90),
            ),
        })
    for i, bucket in enumerate(buckets):
        path = os.path.join(workspace, f"payment_adjustment_{i + 1}.csv")
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "payment_id", "adjustment_percent", "adjustment_reason",
                "approved_by", "effective_date",
            ])
            writer.writeheader()
            writer.writerows(bucket)


def _write_amendment_history(workspace: str, contracts, num_files: int):
    """Write amendment_history YAML files with prior amendment counts."""
    buckets = [[] for _ in range(num_files)]
    for idx, c in enumerate(contracts):
        bucket = idx % num_files
        prior = random.randint(0, 7)
        last_date = _rand_date(
            REFERENCE_DATE - timedelta(days=365),
            REFERENCE_DATE - timedelta(days=30),
        )
        cum_cost = round(random.uniform(-50000, 200000), 2)
        buckets[bucket].append(
            f"- contract_id: \"{c['contract_id']}\"\n"
            f"  prior_amendments: {prior}\n"
            f"  last_amendment_date: \"{last_date}\"\n"
            f"  cumulative_cost_change: {cum_cost}\n"
            f"  notes: \"{fake.sentence(nb_words=8)}\"\n"
        )
    for i, bucket in enumerate(buckets):
        path = os.path.join(workspace, f"amendment_history_{i + 1}.yaml")
        with open(path, "w") as f:
            f.write("\n".join(bucket))


# ========================================================================== #
#  Main                                                                       #
# ========================================================================== #
def main():
    parser = argparse.ArgumentParser(description="Generate contract amendment data")
    parser.add_argument("--db_path", required=True, help="Path to SQLite database")
    parser.add_argument("--workspace", required=True, help="Path to workspace directory")
    args = parser.parse_args()

    rows = SCALE["rows_per_table"]
    num_contracts = max(5, rows // 6)
    num_vendors = num_contracts + max(2, num_contracts // 3)

    # Generate data
    vendors = generate_vendors(num_vendors)
    contracts = generate_contracts(num_contracts, vendors)
    clauses = generate_clauses(rows, contracts)
    change_orders = generate_change_orders(rows, contracts, clauses)
    certifications = generate_certifications(rows, vendors)
    payments = generate_milestone_payments(rows, contracts, clauses)

    # Create database
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    insert_data(conn, "vendors", vendors,
                ["vendor_id", "vendor_name", "primary_contact",
                 "signatory_name", "signatory_title", "signatory_level"])
    insert_data(conn, "contracts", contracts,
                ["contract_id", "contract_name", "vendor_id",
                 "start_date", "end_date", "total_value"])
    insert_data(conn, "msa_clauses", clauses,
                ["clause_id", "contract_id", "clause_number", "clause_type",
                 "clause_text", "amendment_threshold", "compliance_category",
                 "requires_signatory_level"])
    insert_data(conn, "change_orders", change_orders,
                ["order_id", "contract_id", "clause_id", "requested_by",
                 "change_description", "cost_impact", "schedule_impact_days",
                 "priority", "status", "submission_date"])
    insert_data(conn, "vendor_certifications", certifications,
                ["cert_id", "vendor_id", "compliance_category",
                 "certification_name", "issue_date", "expiry_date",
                 "certification_level"])
    insert_data(conn, "milestone_payments", payments,
                ["payment_id", "contract_id", "milestone_name",
                 "milestone_number", "due_date", "amount", "status",
                 "linked_clause_id"])
    conn.close()

    # Generate workspace
    generate_workspace(args.workspace, change_orders, vendors, payments,
                       contracts, clauses, certifications)

    print(f"Database written to {args.db_path}")
    print(f"Workspace created at {args.workspace}")
    print(f"  Contracts: {len(contracts)}")
    print(f"  Vendors: {len(vendors)}")
    print(f"  MSA Clauses: {len(clauses)}")
    print(f"  Change Orders: {len(change_orders)}")
    print(f"  Certifications: {len(certifications)}")
    print(f"  Milestone Payments: {len(payments)}")
    print(f"  Workspace files: {len(os.listdir(args.workspace))}")


if __name__ == "__main__":
    main()
