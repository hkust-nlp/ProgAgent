"""
Data generation for credit-risk delinquency identification task.
Generates a SQLite database and workspace files for proactive credit management.
"""
import argparse
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yaml
from faker import Faker

# ── Scale parameters (v0 base) ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 160,      # v1 = 2x base
    "num_workspace_files": 20,  # v1 = base + N  (N=10)
}

# ── Deterministic seeds ─────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ── Domain constants ────────────────────────────────────────────────────────
INDUSTRIES = [
    "TECH", "MFGR", "RTAIL", "HLTHC", "CONSTR",
    "ENRGY", "FINSV", "FOOD", "TRANS", "MEDIA",
]

PAYMENT_METHODS = ["wire", "check", "ach", "credit_card"]
ORDER_STATUSES = ["completed", "shipped", "pending", "cancelled"]
INVOICE_STATUSES = ["paid", "partial", "overdue", "open"]
ACCOUNT_STATUSES = ["active", "inactive", "suspended", "under_review"]

REFERENCE_DATE = datetime(2026, 3, 31)


# ── Helper utilities ────────────────────────────────────────────────────────
def _rand_date(start: datetime, end: datetime) -> datetime:
    delta = (end - start).days
    if delta <= 0:
        return start
    return start + timedelta(days=random.randint(0, delta))


def _industry_cycle(n: int):
    """Return n industry codes, cycling through the list."""
    return [INDUSTRIES[i % len(INDUSTRIES)] for i in range(n)]


# ── Table builders ──────────────────────────────────────────────────────────
def build_customers(n_rows: int) -> pd.DataFrame:
    records = []
    industries = _industry_cycle(n_rows)
    random.shuffle(industries)
    for i in range(1, n_rows + 1):
        opened = _rand_date(datetime(2018, 1, 1), datetime(2025, 6, 30))
        terms = random.choice([15, 30, 45, 60, 90])
        credit_limit = round(random.uniform(5000, 500000), 2)
        records.append({
            "customer_id": f"CUST-{i:05d}",
            "company_name": fake.company(),
            "industry_code": industries[i - 1],
            "credit_limit": credit_limit,
            "payment_terms_days": terms,
            "contact_name": fake.name(),
            "contact_email": fake.email(),
            "contact_phone": fake.phone_number(),
            "account_status": random.choices(
                ACCOUNT_STATUSES, weights=[70, 10, 5, 15], k=1
            )[0],
            "account_opened_date": opened.strftime("%Y-%m-%d"),
        })
    return pd.DataFrame(records)


def build_invoices(customers_df: pd.DataFrame, n_rows: int) -> pd.DataFrame:
    records = []
    cust_ids = customers_df["customer_id"].tolist()
    terms_map = dict(
        zip(customers_df["customer_id"], customers_df["payment_terms_days"])
    )
    for i in range(1, n_rows + 1):
        cid = random.choice(cust_ids)
        inv_date = _rand_date(datetime(2025, 1, 1), REFERENCE_DATE)
        terms = terms_map[cid]
        due_date = inv_date + timedelta(days=terms)
        amount = round(random.uniform(500, 80000), 2)

        # Determine payment behaviour
        roll = random.random()
        if roll < 0.35:
            # paid on time
            paid_date = _rand_date(inv_date, due_date)
            paid_amount = amount
            status = "paid"
        elif roll < 0.55:
            # paid late
            late_days = random.randint(1, 120)
            paid_date = due_date + timedelta(days=late_days)
            paid_amount = amount
            status = "paid"
        elif roll < 0.70:
            # partial payment
            paid_date = _rand_date(inv_date, due_date + timedelta(days=60))
            paid_amount = round(amount * random.uniform(0.2, 0.8), 2)
            status = "partial"
        elif roll < 0.85:
            # overdue, unpaid
            paid_date = None
            paid_amount = 0.0
            status = "overdue"
        else:
            # open / not yet due or recently opened
            paid_date = None
            paid_amount = 0.0
            status = "open"

        records.append({
            "invoice_id": f"INV-{i:06d}",
            "customer_id": cid,
            "invoice_date": inv_date.strftime("%Y-%m-%d"),
            "due_date": due_date.strftime("%Y-%m-%d"),
            "amount": amount,
            "paid_amount": paid_amount,
            "paid_date": paid_date.strftime("%Y-%m-%d") if paid_date else None,
            "status": status,
        })
    return pd.DataFrame(records)


def build_orders(customers_df: pd.DataFrame, n_rows: int) -> pd.DataFrame:
    records = []
    cust_ids = customers_df["customer_id"].tolist()
    for i in range(1, n_rows + 1):
        cid = random.choice(cust_ids)
        order_date = _rand_date(datetime(2025, 6, 1), REFERENCE_DATE)
        records.append({
            "order_id": f"ORD-{i:06d}",
            "customer_id": cid,
            "order_date": order_date.strftime("%Y-%m-%d"),
            "total_amount": round(random.uniform(200, 60000), 2),
            "order_status": random.choices(
                ORDER_STATUSES, weights=[50, 25, 15, 10], k=1
            )[0],
        })
    return pd.DataFrame(records)


def build_payment_records(
    invoices_df: pd.DataFrame, n_rows: int
) -> pd.DataFrame:
    paid_inv = invoices_df[invoices_df["paid_date"].notna()].copy()
    records = []
    idx = 1
    # Generate payment records from invoices that were paid
    for _, row in paid_inv.iterrows():
        if idx > n_rows:
            break
        records.append({
            "payment_id": f"PAY-{idx:06d}",
            "customer_id": row["customer_id"],
            "invoice_id": row["invoice_id"],
            "payment_date": row["paid_date"],
            "amount": row["paid_amount"],
            "method": random.choice(PAYMENT_METHODS),
        })
        idx += 1
    # Fill remaining with synthetic extra payments
    cust_ids = invoices_df["customer_id"].unique().tolist()
    while idx <= n_rows:
        cid = random.choice(cust_ids)
        records.append({
            "payment_id": f"PAY-{idx:06d}",
            "customer_id": cid,
            "invoice_id": None,
            "payment_date": _rand_date(
                datetime(2025, 1, 1), REFERENCE_DATE
            ).strftime("%Y-%m-%d"),
            "amount": round(random.uniform(100, 30000), 2),
            "method": random.choice(PAYMENT_METHODS),
        })
        idx += 1
    return pd.DataFrame(records)


# ── Database writer ─────────────────────────────────────────────────────────
def create_database(db_path: str, customers, invoices, orders, payments):
    conn = sqlite3.connect(db_path)
    customers.to_sql("customers", conn, if_exists="replace", index=False)
    invoices.to_sql("invoices", conn, if_exists="replace", index=False)
    orders.to_sql("orders", conn, if_exists="replace", index=False)
    payments.to_sql("payment_records", conn, if_exists="replace", index=False)

    # Create indices for performance
    cur = conn.cursor()
    cur.execute("CREATE INDEX IF NOT EXISTS idx_inv_cust ON invoices(customer_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ord_cust ON orders(customer_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pay_cust ON payment_records(customer_id)")
    conn.commit()
    conn.close()


# ── Workspace builders ──────────────────────────────────────────────────────
def build_workspace(workspace: str, customers: pd.DataFrame, invoices: pd.DataFrame):
    os.makedirs(workspace, exist_ok=True)

    n_files = SCALE["num_workspace_files"]
    # Split scalable files: half are aging snapshots (CSV), half are account notes (TXT/MD)
    n_aging = n_files // 2
    n_notes = n_files - n_aging

    # ── Fixed policy / config files (not counted in SCALE) ──────────────
    _write_credit_policy(workspace)
    _write_risk_classification(workspace)
    _write_industry_indicators(workspace)
    _write_scoring_coefficients(workspace)

    # ── Scalable: monthly aging snapshot CSVs ───────────────────────────
    _write_aging_snapshots(workspace, customers, invoices, n_aging)

    # ── Scalable: account manager review notes ──────────────────────────
    _write_account_notes(workspace, customers, n_notes)


def _write_credit_policy(ws: str):
    policy = {
        "scoring_model": {
            "weights": {
                "payment_delay_score": 0.30,
                "aging_concentration_score": 0.25,
                "order_trend_score": 0.20,
                "industry_risk_score": 0.15,
                "credit_utilization_score": 0.10,
            },
            "max_component_score": 100,
        },
        "risk_thresholds": {
            "high_risk_min": 62,
            "medium_risk_min": 35,
        },
        "delinquency_definition": {
            "days_past_due_threshold": 60,
            "lookback_months": 12,
        },
        "aging_buckets": {
            "current": {"min_days": 0, "max_days": 30},
            "bucket_31_60": {"min_days": 31, "max_days": 60},
            "bucket_61_90": {"min_days": 61, "max_days": 90},
            "bucket_91_120": {"min_days": 91, "max_days": 120},
            "bucket_121_plus": {"min_days": 121, "max_days": None},
        },
        "contact_priority_rules": {
            "sort_primary": "risk_score",
            "sort_direction": "descending",
            "tiebreaker": "total_outstanding",
            "tiebreaker_direction": "descending",
        },
        "eligible_account_statuses": ["active", "under_review"],
    }
    with open(os.path.join(ws, "credit_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)


def _write_risk_classification(ws: str):
    classification = {
        "risk_levels": [
            {
                "level": "CRITICAL",
                "score_min": 80,
                "score_max": 100,
                "recommended_action": "Immediate account freeze review and executive escalation",
                "contact_urgency": "within_24h",
            },
            {
                "level": "HIGH",
                "score_min": 62,
                "score_max": 79,
                "recommended_action": "Reduce credit limit and require prepayment for new orders",
                "contact_urgency": "within_3d",
            },
            {
                "level": "ELEVATED",
                "score_min": 35,
                "score_max": 61,
                "recommended_action": "Increase monitoring frequency and request payment plan",
                "contact_urgency": "within_7d",
            },
            {
                "level": "LOW",
                "score_min": 0,
                "score_max": 34,
                "recommended_action": "Standard monitoring",
                "contact_urgency": "routine",
            },
        ]
    }
    with open(os.path.join(ws, "risk_classification.json"), "w") as f:
        json.dump(classification, f, indent=2)


def _write_industry_indicators(ws: str):
    """Write industry-level economic risk indicators (one CSV)."""
    rows = []
    for ind in INDUSTRIES:
        np.random.seed(SEED + hash(ind) % 10000)
        rows.append({
            "industry_code": ind,
            "sector_default_rate_pct": round(np.random.uniform(1.0, 12.0), 2),
            "gdp_growth_pct": round(np.random.uniform(-2.0, 5.0), 2),
            "yoy_revenue_change_pct": round(np.random.uniform(-8.0, 15.0), 2),
            "avg_dso_industry": round(np.random.uniform(25, 75), 1),
            "bankruptcy_index": round(np.random.uniform(0, 100), 1),
        })
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(ws, "industry_economic_indicators.csv"), index=False)


def _write_scoring_coefficients(ws: str):
    """Component scoring formulas live here so the agent must read them."""
    coefficients = {
        "payment_delay_score": {
            "description": "Score based on average days late across paid invoices in lookback period",
            "formula": "min(100, (avg_days_late / payment_terms_days) * 120)",
            "floor": 0,
            "cap": 100,
        },
        "aging_concentration_score": {
            "description": "Score based on proportion of outstanding amount in 60+ day buckets",
            "formula": "(amount_over_60_days / total_outstanding) * 100 if total_outstanding > 0 else 0",
            "floor": 0,
            "cap": 100,
        },
        "order_trend_score": {
            "description": "Score based on recent order decline; higher score means riskier",
            "formula": "max(0, (1 - recent_3mo_orders / prior_3mo_orders) * 100) if prior_3mo_orders > 0 else 50",
            "note": "If no orders in either period, score is 50. If prior is 0 but recent > 0, score is 0.",
            "floor": 0,
            "cap": 100,
        },
        "industry_risk_score": {
            "description": "Derived from industry_economic_indicators.csv",
            "formula": "(sector_default_rate_pct * 4) + (max(0, -gdp_growth_pct) * 8) + (bankruptcy_index * 0.3)",
            "floor": 0,
            "cap": 100,
        },
        "credit_utilization_score": {
            "description": "Score based on total outstanding relative to credit limit",
            "formula": "min(100, (total_outstanding / credit_limit) * 100) if credit_limit > 0 else 50",
            "floor": 0,
            "cap": 100,
        },
    }
    with open(os.path.join(ws, "scoring_coefficients.json"), "w") as f:
        json.dump(coefficients, f, indent=2)


def _write_aging_snapshots(ws: str, customers, invoices, n_snapshots: int):
    """Generate monthly aging snapshot CSVs."""
    snap_dir = os.path.join(ws, "aging_snapshots")
    os.makedirs(snap_dir, exist_ok=True)

    # Generate snapshots going back from reference date
    for m in range(n_snapshots):
        snap_date = REFERENCE_DATE - timedelta(days=30 * m)
        snap_label = snap_date.strftime("%Y-%m")

        rows = []
        for _, cust in customers.iterrows():
            cid = cust["customer_id"]
            cust_inv = invoices[invoices["customer_id"] == cid]

            # Compute aging buckets as of snap_date
            current = bucket_31_60 = bucket_61_90 = bucket_91_120 = bucket_121_plus = 0.0
            for _, inv in cust_inv.iterrows():
                due = datetime.strptime(inv["due_date"], "%Y-%m-%d")
                paid_date = (
                    datetime.strptime(inv["paid_date"], "%Y-%m-%d")
                    if pd.notna(inv["paid_date"])
                    else None
                )
                # Only count if unpaid or partially paid as of snap_date
                if paid_date and paid_date <= snap_date:
                    continue
                outstanding = inv["amount"] - inv["paid_amount"]
                if outstanding <= 0:
                    continue
                days_past = (snap_date - due).days
                if days_past <= 0:
                    current += outstanding
                elif days_past <= 30:
                    current += outstanding
                elif days_past <= 60:
                    bucket_31_60 += outstanding
                elif days_past <= 90:
                    bucket_61_90 += outstanding
                elif days_past <= 120:
                    bucket_91_120 += outstanding
                else:
                    bucket_121_plus += outstanding

            total = current + bucket_31_60 + bucket_61_90 + bucket_91_120 + bucket_121_plus
            if total > 0:
                rows.append({
                    "customer_id": cid,
                    "snapshot_date": snap_label,
                    "current": round(current, 2),
                    "bucket_31_60": round(bucket_31_60, 2),
                    "bucket_61_90": round(bucket_61_90, 2),
                    "bucket_91_120": round(bucket_91_120, 2),
                    "bucket_121_plus": round(bucket_121_plus, 2),
                    "total_outstanding": round(total, 2),
                })

        df = pd.DataFrame(rows)
        df.to_csv(os.path.join(snap_dir, f"aging_{snap_label}.csv"), index=False)


def _write_account_notes(ws: str, customers: pd.DataFrame, n_notes: int):
    """Generate account manager review notes as text files."""
    notes_dir = os.path.join(ws, "account_notes")
    os.makedirs(notes_dir, exist_ok=True)

    note_templates = [
        "Spoke with {contact} at {company}. They indicated cash flow tightness due to seasonal downturn. "
        "Requested 15-day extension on upcoming invoices. Recommend monitoring closely.",
        "Account {cid} ({company}) has been consistently paying within terms. "
        "No concerns at this time. Contact: {contact}.",
        "Follow-up with {company} regarding overdue balance. {contact} promised payment by end of month. "
        "History of similar promises with partial follow-through. Flag for review.",
        "New management at {company}. {contact} has taken over accounts payable. "
        "Payment patterns may shift. Recommend standard watch.",
        "Received partial payment from {company} ({cid}). {contact} mentioned dispute on invoice line items. "
        "Escalated to billing department. Risk: moderate.",
        "{company} reported strong Q3 results publicly. {contact} confirmed expansion plans. "
        "Credit line increase may be warranted.",
        "Warning: {company} ({cid}) missed two consecutive payment deadlines. "
        "{contact} unreachable by phone. Sent formal demand letter.",
        "Routine check on {company}. All invoices current. {contact} responsive. "
        "Industry outlook stable per latest sector report.",
    ]

    selected_custs = customers.sample(n=min(n_notes, len(customers)), random_state=SEED)
    for idx, (_, row) in enumerate(selected_custs.iterrows()):
        if idx >= n_notes:
            break
        template = note_templates[idx % len(note_templates)]
        note_text = template.format(
            contact=row["contact_name"],
            company=row["company_name"],
            cid=row["customer_id"],
        )
        review_date = (REFERENCE_DATE - timedelta(days=random.randint(1, 60))).strftime(
            "%Y-%m-%d"
        )
        content = (
            f"Account Review Note\n"
            f"Date: {review_date}\n"
            f"Customer: {row['customer_id']} - {row['company_name']}\n"
            f"Reviewer: {fake.name()}\n"
            f"---\n"
            f"{note_text}\n"
        )
        fname = f"note_{row['customer_id'].replace('CUST-', '')}.txt"
        with open(os.path.join(notes_dir, fname), "w") as f:
            f.write(content)


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n_rows = SCALE["rows_per_table"]

    customers = build_customers(n_rows)
    invoices = build_invoices(customers, n_rows * 3)   # ~3 invoices per customer
    orders = build_orders(customers, n_rows * 2)       # ~2 orders per customer
    payments = build_payment_records(invoices, n_rows * 2)

    create_database(args.db_path, customers, invoices, orders, payments)
    build_workspace(args.workspace, customers, invoices)

    print(f"Database created at {args.db_path}")
    print(f"  customers: {len(customers)} rows")
    print(f"  invoices:  {len(invoices)} rows")
    print(f"  orders:    {len(orders)} rows")
    print(f"  payments:  {len(payments)} rows")
    print(f"Workspace created at {args.workspace}")
    print(f"  Aging snapshots: {SCALE['num_workspace_files'] // 2}")
    print(f"  Account notes:   {SCALE['num_workspace_files'] - SCALE['num_workspace_files'] // 2}")
    print(f"  Fixed config files: 4")


if __name__ == "__main__":
    main()
