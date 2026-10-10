#!/usr/bin/env python3
"""Data generation for reinsurer quarterly profit commission validation task."""

import argparse
import json
import os
import sqlite3
import random

import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 32,
}

# --------------- deterministic seeds ---------------
random.seed(42)
np.random.seed(42)
Faker.seed(42)
fake = Faker()

# --------------- domain constants ---------------
LINES_OF_BUSINESS = ["Property", "Casualty", "Marine", "Liability"]
QUARTER = "Q4-2025"
MONTHS = ["2025-10", "2025-11", "2025-12"]

SLIDING_SCALE = {
    "Property": [
        {"min_lr": 0.00, "max_lr": 0.40, "rate": 0.47},
        {"min_lr": 0.40, "max_lr": 0.50, "rate": 0.42},
        {"min_lr": 0.50, "max_lr": 0.60, "rate": 0.35},
        {"min_lr": 0.60, "max_lr": 0.70, "rate": 0.27},
        {"min_lr": 0.70, "max_lr": 0.80, "rate": 0.18},
        {"min_lr": 0.80, "max_lr": 1.00, "rate": 0.08},
        {"min_lr": 1.00, "max_lr": 9.99, "rate": 0.00},
    ],
    "Casualty": [
        {"min_lr": 0.00, "max_lr": 0.35, "rate": 0.50},
        {"min_lr": 0.35, "max_lr": 0.45, "rate": 0.44},
        {"min_lr": 0.45, "max_lr": 0.55, "rate": 0.37},
        {"min_lr": 0.55, "max_lr": 0.65, "rate": 0.29},
        {"min_lr": 0.65, "max_lr": 0.75, "rate": 0.20},
        {"min_lr": 0.75, "max_lr": 1.00, "rate": 0.10},
        {"min_lr": 1.00, "max_lr": 9.99, "rate": 0.00},
    ],
    "Marine": [
        {"min_lr": 0.00, "max_lr": 0.45, "rate": 0.43},
        {"min_lr": 0.45, "max_lr": 0.55, "rate": 0.38},
        {"min_lr": 0.55, "max_lr": 0.65, "rate": 0.30},
        {"min_lr": 0.65, "max_lr": 0.75, "rate": 0.22},
        {"min_lr": 0.75, "max_lr": 0.85, "rate": 0.13},
        {"min_lr": 0.85, "max_lr": 1.00, "rate": 0.05},
        {"min_lr": 1.00, "max_lr": 9.99, "rate": 0.00},
    ],
    "Liability": [
        {"min_lr": 0.00, "max_lr": 0.38, "rate": 0.48},
        {"min_lr": 0.38, "max_lr": 0.48, "rate": 0.41},
        {"min_lr": 0.48, "max_lr": 0.58, "rate": 0.33},
        {"min_lr": 0.58, "max_lr": 0.68, "rate": 0.25},
        {"min_lr": 0.68, "max_lr": 0.78, "rate": 0.16},
        {"min_lr": 0.78, "max_lr": 1.00, "rate": 0.07},
        {"min_lr": 1.00, "max_lr": 9.99, "rate": 0.00},
    ],
}

# Error injection cycle (None = correct statement)
ERROR_CYCLE = [
    None,              # 0 - correct
    "lae_omitted",     # 1 - LAE not included in incurred losses
    None,              # 2 - correct
    "wrong_cf",        # 3 - uses opening_balance instead of closing_balance
    None,              # 4 - correct
    "wrong_bracket",   # 5 - adjacent sliding-scale bracket used
    None,              # 6 - correct
    "premium_error",   # 7 - one month's premium omitted from total
]


# --------------- helpers ---------------

def lookup_rate(lob: str, loss_ratio: float) -> float:
    for b in SLIDING_SCALE[lob]:
        if b["min_lr"] <= loss_ratio < b["max_lr"]:
            return b["rate"]
    return 0.0


def adjacent_rate(lob: str, loss_ratio: float) -> float:
    """Return the commission rate from one bracket above (lower loss-ratio)."""
    table = SLIDING_SCALE[lob]
    for i, b in enumerate(table):
        if b["min_lr"] <= loss_ratio < b["max_lr"]:
            if i > 0:
                return table[i - 1]["rate"]
            if i + 1 < len(table):
                return table[i + 1]["rate"]
            return b["rate"]
    return 0.0


# --------------- schema ---------------

def create_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS treaties (
            treaty_id        TEXT PRIMARY KEY,
            cedant_name      TEXT,
            line_of_business TEXT,
            inception_date   TEXT,
            expiry_date      TEXT,
            treaty_type      TEXT,
            currency         TEXT
        );
        CREATE TABLE IF NOT EXISTS ceded_premiums (
            premium_id       TEXT PRIMARY KEY,
            treaty_id        TEXT REFERENCES treaties(treaty_id),
            month            TEXT,
            written_premium  REAL,
            ceded_percentage REAL,
            ceded_premium    REAL
        );
        CREATE TABLE IF NOT EXISTS paid_losses (
            loss_id          TEXT PRIMARY KEY,
            treaty_id        TEXT REFERENCES treaties(treaty_id),
            claim_ref        TEXT,
            incurred_date    TEXT,
            paid_date        TEXT,
            paid_amount      REAL,
            claim_status     TEXT,
            loss_category    TEXT
        );
        CREATE TABLE IF NOT EXISTS commission_statements (
            statement_id              TEXT PRIMARY KEY,
            treaty_id                 TEXT REFERENCES treaties(treaty_id),
            quarter                   TEXT,
            reported_ceded_premium    REAL,
            reported_incurred_losses  REAL,
            reported_expense_loading  REAL,
            reported_carryforward     REAL,
            reported_loss_ratio       REAL,
            reported_commission_rate  REAL,
            reported_commission_amount REAL,
            status                    TEXT DEFAULT 'PENDING'
        );
        CREATE TABLE IF NOT EXISTS loss_carryforward (
            cf_id            TEXT PRIMARY KEY,
            treaty_id        TEXT REFERENCES treaties(treaty_id),
            prior_year       TEXT,
            opening_balance  REAL,
            adjustments      REAL,
            closing_balance  REAL
        );
    """)


# --------------- main ---------------

def main(db_path: str, workspace: str):
    os.makedirs(workspace, exist_ok=True)
    num_treaties = SCALE["num_workspace_files"]
    rows = SCALE["rows_per_table"]

    # ---- 1. treaties ----
    treaties = []
    for i in range(num_treaties):
        treaties.append({
            "treaty_id": f"TR-{i + 1:03d}",
            "cedant_name": fake.company(),
            "line_of_business": LINES_OF_BUSINESS[i % len(LINES_OF_BUSINESS)],
            "inception_date": "2025-01-01",
            "expiry_date": "2025-12-31",
            "treaty_type": "Quota Share" if i % 2 == 0 else "Surplus",
            "currency": "USD",
        })

    # ---- 2. expense parameters (workspace-only) ----
    expense_params = {}
    for t in treaties:
        mgmt = round(float(np.random.uniform(0.03, 0.07)), 4)
        brk = round(float(np.random.uniform(0.015, 0.035)), 4)
        expense_params[t["treaty_id"]] = {
            "management_expense_pct": mgmt,
            "brokerage_fee_pct": brk,
            "total_expense_pct": round(mgmt + brk, 4),
        }

    # ---- 3. ceded premiums ----
    premiums: list[dict] = []
    pid = 1
    base_per = max(3, rows // num_treaties)
    rem = max(0, rows - base_per * num_treaties)
    for i, t in enumerate(treaties):
        n = base_per + (1 if i < rem else 0)
        base_wp = float(np.random.uniform(800_000, 4_000_000))
        ceded_pct = round(float(np.random.uniform(0.25, 0.55)), 4)
        for j in range(n):
            month = MONTHS[j % 3]
            wp = round(base_wp * float(np.random.uniform(0.85, 1.15)) / max(1, n // 3), 2)
            cp = round(wp * ceded_pct, 2)
            premiums.append({
                "premium_id": f"P-{pid:05d}",
                "treaty_id": t["treaty_id"],
                "month": month,
                "written_premium": wp,
                "ceded_percentage": ceded_pct,
                "ceded_premium": cp,
            })
            pid += 1

    # ---- 4. paid losses ----
    losses: list[dict] = []
    lid = 1
    base_per_l = max(2, rows // num_treaties)
    rem_l = max(0, rows - base_per_l * num_treaties)
    cats = [
        "Property Damage", "Bodily Injury", "Business Interruption",
        "Third Party Liability", "Natural Catastrophe",
    ]
    statuses = ["Paid", "Partially Paid", "Settled"]

    for i, t in enumerate(treaties):
        n = base_per_l + (1 if i < rem_l else 0)
        total_cp = sum(p["ceded_premium"] for p in premiums
                       if p["treaty_id"] == t["treaty_id"])
        target_lr = float(np.random.uniform(0.30, 0.55))
        target_total = total_cp * target_lr
        raw = np.random.uniform(5_000, 200_000, size=n)
        props = raw / raw.sum()

        for j in range(n):
            amt = round(float(target_total * props[j]), 2)
            amt = max(amt, 500.0)
            m = random.choice([10, 11, 12])
            d = random.randint(1, 28)
            losses.append({
                "loss_id": f"L-{lid:05d}",
                "treaty_id": t["treaty_id"],
                "claim_ref": f"CLM-{t['treaty_id'][3:]}-{lid:04d}",
                "incurred_date": f"2025-{m:02d}-{d:02d}",
                "paid_date": f"2025-{min(m + 1, 12):02d}-{min(d + 5, 28):02d}",
                "paid_amount": amt,
                "claim_status": random.choice(statuses),
                "loss_category": random.choice(cats),
            })
            lid += 1

    # ---- 5. LAE data (workspace-only, in bordereaux CSVs) ----
    lae_types = ["Legal Fees", "Adjuster Fees", "Expert Witness",
                 "Investigation", "Survey Costs"]
    lae_data: dict[str, list] = {}
    for t in treaties:
        tid = t["treaty_id"]
        t_losses = [l for l in losses if l["treaty_id"] == tid]
        entries: list[dict] = []
        for l in t_losses:
            if random.random() < 0.70:
                for _ in range(random.randint(1, 2)):
                    entries.append({
                        "claim_ref": l["claim_ref"],
                        "lae_type": random.choice(lae_types),
                        "lae_amount": round(
                            l["paid_amount"] * float(np.random.uniform(0.04, 0.14)), 2
                        ),
                        "adjuster": fake.name(),
                    })
        lae_data[tid] = entries

    # ---- 6. loss carry-forward ----
    carryforwards: list[dict] = []
    for i, t in enumerate(treaties):
        opening = round(float(np.random.uniform(5_000, 80_000)), 2)
        adj = round(float(np.random.uniform(-20_000, 30_000)), 2)
        closing = round(opening + adj, 2)
        if closing < 0:
            closing = 0.0
            adj = round(-opening, 2)
        carryforwards.append({
            "cf_id": f"CF-{i + 1:03d}",
            "treaty_id": t["treaty_id"],
            "prior_year": "2024",
            "opening_balance": opening,
            "adjustments": adj,
            "closing_balance": closing,
        })

    # ---- 7. correct commissions ----
    correct: dict[str, dict] = {}
    for t in treaties:
        tid = t["treaty_id"]
        lob = t["line_of_business"]
        total_cp = sum(p["ceded_premium"] for p in premiums if p["treaty_id"] == tid)
        total_paid = sum(l["paid_amount"] for l in losses if l["treaty_id"] == tid)
        total_lae = sum(e["lae_amount"] for e in lae_data.get(tid, []))
        total_inc = total_paid + total_lae
        exp_pct = expense_params[tid]["total_expense_pct"]
        exp_load = total_cp * exp_pct
        cf_rec = next(c for c in carryforwards if c["treaty_id"] == tid)
        cf_bal = cf_rec["closing_balance"]
        lr = total_inc / total_cp if total_cp else 0.0
        rate = lookup_rate(lob, lr)
        net = total_cp - total_inc - exp_load - cf_bal
        comm = round(net * rate, 2) if net > 0 else 0.0
        correct[tid] = {
            "total_ceded_premium": round(total_cp, 2),
            "total_paid_losses": round(total_paid, 2),
            "total_lae": round(total_lae, 2),
            "total_incurred": round(total_inc, 2),
            "expense_loading": round(exp_load, 2),
            "carryforward": round(cf_bal, 2),
            "loss_ratio": lr,
            "commission_rate": rate,
            "net_profit": round(net, 2),
            "commission": comm,
        }

    # ---- 8. commission statements (with injected errors) ----
    statements: list[dict] = []
    for i, t in enumerate(treaties):
        tid = t["treaty_id"]
        lob = t["line_of_business"]
        c = correct[tid]
        err = ERROR_CYCLE[i % len(ERROR_CYCLE)]

        # start with correct values
        rep = {
            "reported_ceded_premium": c["total_ceded_premium"],
            "reported_incurred_losses": c["total_incurred"],
            "reported_expense_loading": c["expense_loading"],
            "reported_carryforward": c["carryforward"],
            "reported_loss_ratio": round(c["loss_ratio"], 6),
            "reported_commission_rate": c["commission_rate"],
            "reported_commission_amount": c["commission"],
        }

        if err == "lae_omitted":
            wrong_inc = c["total_paid_losses"]
            wrong_lr = (wrong_inc / c["total_ceded_premium"]
                        if c["total_ceded_premium"] else 0.0)
            wrong_rate = lookup_rate(lob, wrong_lr)
            wrong_net = (c["total_ceded_premium"] - wrong_inc
                         - c["expense_loading"] - c["carryforward"])
            wrong_comm = round(wrong_net * wrong_rate, 2) if wrong_net > 0 else 0.0
            rep.update(
                reported_incurred_losses=round(wrong_inc, 2),
                reported_loss_ratio=round(wrong_lr, 6),
                reported_commission_rate=wrong_rate,
                reported_commission_amount=wrong_comm,
            )

        elif err == "wrong_cf":
            cf_rec = next(cf for cf in carryforwards if cf["treaty_id"] == tid)
            wrong_cf = cf_rec["opening_balance"]
            wrong_net = (c["total_ceded_premium"] - c["total_incurred"]
                         - c["expense_loading"] - wrong_cf)
            wrong_comm = (round(wrong_net * c["commission_rate"], 2)
                          if wrong_net > 0 else 0.0)
            rep.update(
                reported_carryforward=round(wrong_cf, 2),
                reported_commission_amount=wrong_comm,
            )

        elif err == "wrong_bracket":
            wrong_rate = adjacent_rate(lob, c["loss_ratio"])
            wrong_comm = (round(c["net_profit"] * wrong_rate, 2)
                          if c["net_profit"] > 0 else 0.0)
            rep.update(
                reported_commission_rate=wrong_rate,
                reported_commission_amount=wrong_comm,
            )

        elif err == "premium_error":
            t_prems = [p for p in premiums if p["treaty_id"] == tid]
            if len(t_prems) > 1:
                omitted = t_prems[-1]["ceded_premium"]
                wrong_cp = round(c["total_ceded_premium"] - omitted, 2)
            else:
                wrong_cp = c["total_ceded_premium"]
            wrong_exp = round(
                wrong_cp * expense_params[tid]["total_expense_pct"], 2
            )
            wrong_lr = c["total_incurred"] / wrong_cp if wrong_cp else 0.0
            wrong_rate = lookup_rate(lob, wrong_lr)
            wrong_net = (wrong_cp - c["total_incurred"]
                         - wrong_exp - c["carryforward"])
            wrong_comm = (round(wrong_net * wrong_rate, 2)
                          if wrong_net > 0 else 0.0)
            rep.update(
                reported_ceded_premium=round(wrong_cp, 2),
                reported_expense_loading=wrong_exp,
                reported_loss_ratio=round(wrong_lr, 6),
                reported_commission_rate=wrong_rate,
                reported_commission_amount=wrong_comm,
            )

        statements.append({
            "statement_id": f"CS-{i + 1:03d}",
            "treaty_id": tid,
            "quarter": QUARTER,
            **rep,
            "status": "PENDING",
        })

    # ---- 9. write database ----
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    cur = conn.cursor()

    for t in treaties:
        cur.execute(
            "INSERT INTO treaties VALUES (?,?,?,?,?,?,?)",
            (t["treaty_id"], t["cedant_name"], t["line_of_business"],
             t["inception_date"], t["expiry_date"], t["treaty_type"],
             t["currency"]),
        )
    for p in premiums:
        cur.execute(
            "INSERT INTO ceded_premiums VALUES (?,?,?,?,?,?)",
            (p["premium_id"], p["treaty_id"], p["month"],
             p["written_premium"], p["ceded_percentage"], p["ceded_premium"]),
        )
    for l in losses:
        cur.execute(
            "INSERT INTO paid_losses VALUES (?,?,?,?,?,?,?,?)",
            (l["loss_id"], l["treaty_id"], l["claim_ref"],
             l["incurred_date"], l["paid_date"], l["paid_amount"],
             l["claim_status"], l["loss_category"]),
        )
    for s in statements:
        cur.execute(
            "INSERT INTO commission_statements VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (s["statement_id"], s["treaty_id"], s["quarter"],
             s["reported_ceded_premium"], s["reported_incurred_losses"],
             s["reported_expense_loading"], s["reported_carryforward"],
             s["reported_loss_ratio"], s["reported_commission_rate"],
             s["reported_commission_amount"], s["status"]),
        )
    for cf in carryforwards:
        cur.execute(
            "INSERT INTO loss_carryforward VALUES (?,?,?,?,?,?)",
            (cf["cf_id"], cf["treaty_id"], cf["prior_year"],
             cf["opening_balance"], cf["adjustments"], cf["closing_balance"]),
        )
    conn.commit()
    conn.close()

    # ---- 10. write workspace files ----

    # 10a. sliding_scale_commission.yaml  (fixed config)
    yaml_lines: list[str] = []
    for lob, brackets in SLIDING_SCALE.items():
        yaml_lines.append(f"{lob}:")
        for b in brackets:
            yaml_lines.append(f"  - min_lr: {b['min_lr']}")
            yaml_lines.append(f"    max_lr: {b['max_lr']}")
            yaml_lines.append(f"    rate: {b['rate']}")
    with open(os.path.join(workspace, "sliding_scale_commission.yaml"), "w") as f:
        f.write("\n".join(yaml_lines) + "\n")

    # 10b. expense_parameters.json  (fixed config)
    with open(os.path.join(workspace, "expense_parameters.json"), "w") as f:
        json.dump(expense_params, f, indent=2)

    # 10c. validation_rules.txt  (fixed config)
    rules = """\
PROFIT COMMISSION VALIDATION RULES
========================================

1. Loss ratio calculation:
   loss_ratio = total_incurred_losses / total_ceded_premium
   where total_incurred_losses = sum(paid_losses) + sum(loss_adjustment_expenses)
   The loss carry-forward does NOT enter the loss ratio.

2. Expense loading:
   expense_loading = total_ceded_premium * total_expense_pct

3. Net profit:
   net_profit = total_ceded_premium - total_incurred_losses
                - expense_loading - loss_carry_forward_closing_balance

4. Commission:
   If net_profit > 0: profit_commission = net_profit * commission_rate
   If net_profit <= 0: profit_commission = 0.00

5. The commission_rate is determined by the sliding-scale table for the
   treaty's line of business.  Find the bracket where
   min_lr <= loss_ratio < max_lr.

6. Loss carry-forward: use the closing_balance
   (= opening_balance + adjustments) from the prior year record.

7. Tolerance: a variance of less than $1.00 in absolute value between the
   reported and independently calculated commission is acceptable (APPROVED).
   Any variance of $1.00 or more is a DISCREPANCY.

8. All monetary values are rounded to 2 decimal places.
"""
    with open(os.path.join(workspace, "validation_rules.txt"), "w") as f:
        f.write(rules)

    # 10d. prior_year_summary.md  (fixed reference)
    with open(os.path.join(workspace, "prior_year_summary.md"), "w") as f:
        f.write("# Prior Year Loss Carry-Forward Summary (2024)\n\n")
        f.write(
            "The following carry-forward positions were finalized during the "
            "2024 annual settlement.\nClosing balances should be applied to "
            "the Q4-2025 profit commission calculation.\n\n"
        )
        for cf in carryforwards:
            tid = cf["treaty_id"]
            tname = next(
                tr["cedant_name"] for tr in treaties if tr["treaty_id"] == tid
            )
            f.write(
                f"**{tid}** - {tname}: "
                f"Opening ${cf['opening_balance']:,.2f}, "
                f"Adjustments ${cf['adjustments']:+,.2f}, "
                f"Closing ${cf['closing_balance']:,.2f}\n\n"
            )

    # 10e. bordereaux CSV files  (scalable: one per treaty)
    for t in treaties:
        tid = t["treaty_id"]
        entries = lae_data.get(tid, [])
        if entries:
            df = pd.DataFrame(entries)
        else:
            df = pd.DataFrame(
                columns=["claim_ref", "lae_type", "lae_amount", "adjuster"]
            )
        df.to_csv(os.path.join(workspace, f"bordereaux_{tid}.csv"), index=False)

    print(
        f"Created {db_path}: {num_treaties} treaties, "
        f"{len(premiums)} premium records, {len(losses)} loss records"
    )
    print(f"Workspace: {len(os.listdir(workspace))} files in {workspace}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
