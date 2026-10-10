import argparse
import os
import sqlite3
import json
import csv
import yaml
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 160,
    "num_workspace_files": 16,
}

REGIONS = ["NE", "SE", "MW", "SW", "WE", "NW", "SC", "NC", "AT", "PA"]
TIERS = ["platinum", "gold", "silver", "standard"]
REFERENCE_DATE = datetime(2026, 4, 1)


def _month_subtract(year, month, offset):
    """Return (year, month) after subtracting offset months."""
    m = month - offset
    y = year
    while m <= 0:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return y, m


def main(db_path, workspace):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    num_accounts = SCALE["rows_per_table"]
    num_regions = len(REGIONS)
    num_periods = max(1, SCALE["rows_per_table"] // num_regions)
    num_ws_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)

    # ===== Determine risky subsets =====
    all_indices = np.arange(num_accounts)
    ca_risky = set(np.random.choice(all_indices, size=int(num_accounts * 0.30), replace=False))
    cs_risky = set(np.random.choice(all_indices, size=int(num_accounts * 0.30), replace=False))
    mp_risky = set(np.random.choice(all_indices, size=int(num_accounts * 0.25), replace=False))

    # ===== TABLE 1: accounts =====
    accounts = []
    for i in range(num_accounts):
        acc_id = f"ACC_{i+1:05d}"
        name = fake.name()
        region = REGIONS[i % num_regions]
        tier = TIERS[int(np.random.choice(len(TIERS), p=[0.15, 0.25, 0.35, 0.25]))]
        credit_limit = int(np.random.choice([1000, 2000, 3000, 5000, 8000, 10000, 15000, 20000, 25000]))
        y, m = _month_subtract(REFERENCE_DATE.year, REFERENCE_DATE.month, int(np.random.randint(12, 60)))
        open_date = f"{y:04d}-{m:02d}-{int(np.random.randint(1, 29)):02d}"
        status = "active" if np.random.random() < 0.92 else "inactive"
        accounts.append({
            "account_id": acc_id,
            "customer_name": name,
            "region_code": region,
            "account_tier": tier,
            "credit_limit": credit_limit,
            "open_date": open_date,
            "status": status,
        })

    pd.DataFrame(accounts).to_sql("accounts", conn, index=False, if_exists="replace")

    # ===== TABLE 2: transactions =====
    transactions = []
    tx_id = 1
    for i in range(num_accounts):
        acc_id = accounts[i]["account_id"]
        num_tx = int(np.random.randint(5, 10))
        is_ca = i in ca_risky

        for _ in range(num_tx):
            if is_ca:
                tx_type = ["purchase", "cash_advance", "balance_transfer", "fee"][
                    int(np.random.choice(4, p=[0.40, 0.35, 0.15, 0.10]))
                ]
            else:
                tx_type = ["purchase", "cash_advance", "balance_transfer", "fee"][
                    int(np.random.choice(4, p=[0.65, 0.10, 0.15, 0.10]))
                ]

            if tx_type == "cash_advance":
                amount = round(float(np.random.uniform(200, 3000)), 2)
            elif tx_type == "purchase":
                amount = round(float(np.random.uniform(10, 1500)), 2)
            elif tx_type == "balance_transfer":
                amount = round(float(np.random.uniform(500, 5000)), 2)
            else:
                amount = round(float(np.random.uniform(25, 150)), 2)

            days_ago = int(np.random.randint(1, 181))
            tx_date = (REFERENCE_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")

            transactions.append({
                "tx_id": f"TX_{tx_id:07d}",
                "account_id": acc_id,
                "tx_date": tx_date,
                "amount": amount,
                "tx_type": tx_type,
            })
            tx_id += 1

    pd.DataFrame(transactions).to_sql("transactions", conn, index=False, if_exists="replace")

    # ===== TABLE 3: credit_bureau =====
    credit_records = []
    rec_id = 1
    num_reports = 8
    for i in range(num_accounts):
        acc_id = accounts[i]["account_id"]
        is_decline = i in cs_risky

        if is_decline:
            base_score = int(np.random.randint(650, 750))
            total_decline = int(np.random.randint(55, 100))
        else:
            base_score = int(np.random.randint(680, 800))
            total_decline = int(np.random.randint(-20, 30))

        for j in range(num_reports):
            y, m = _month_subtract(REFERENCE_DATE.year, REFERENCE_DATE.month, num_reports - 1 - j)
            report_date = f"{y:04d}-{m:02d}-01"
            progress = j / (num_reports - 1) if num_reports > 1 else 1.0
            score = int(base_score - total_decline * progress)
            score = max(300, min(850, score))

            credit_records.append({
                "record_id": f"CR_{rec_id:07d}",
                "account_id": acc_id,
                "report_date": report_date,
                "credit_score": score,
            })
            rec_id += 1

    pd.DataFrame(credit_records).to_sql("credit_bureau", conn, index=False, if_exists="replace")

    # ===== TABLE 4: payment_history =====
    payment_records = []
    pay_id = 1
    num_billing = 6
    for i in range(num_accounts):
        acc_id = accounts[i]["account_id"]
        credit_limit = accounts[i]["credit_limit"]
        is_mp = i in mp_risky

        for j in range(num_billing):
            y, m = _month_subtract(REFERENCE_DATE.year, REFERENCE_DATE.month, num_billing - j)
            billing_period = f"{y:04d}-{m:02d}"
            # Due date: 15th of the next month
            dm = m + 1
            dy = y
            if dm > 12:
                dm -= 12
                dy += 1
            due_date = f"{dy:04d}-{dm:02d}-15"

            statement_balance = round(float(np.random.uniform(200, credit_limit * 0.8)), 2)
            min_payment = round(max(25.0, statement_balance * 0.02), 2)

            if is_mp:
                if np.random.random() < 0.85:
                    amount_paid = min_payment
                else:
                    amount_paid = round(float(np.random.uniform(min_payment * 1.5, max(min_payment * 1.6, statement_balance))), 2)
            else:
                if np.random.random() < 0.12:
                    amount_paid = min_payment
                else:
                    amount_paid = round(float(np.random.uniform(min_payment * 2, max(min_payment * 2.1, statement_balance))), 2)

            late_days = int(np.random.choice([0, 0, 0, 0, 1, 2, 5]))
            pay_date = datetime.strptime(due_date, "%Y-%m-%d") + timedelta(days=late_days)
            payment_date = pay_date.strftime("%Y-%m-%d")

            payment_records.append({
                "payment_id": f"PAY_{pay_id:07d}",
                "account_id": acc_id,
                "billing_period": billing_period,
                "statement_balance": statement_balance,
                "min_payment_due": min_payment,
                "amount_paid": amount_paid,
                "due_date": due_date,
                "payment_date": payment_date,
            })
            pay_id += 1

    pd.DataFrame(payment_records).to_sql("payment_history", conn, index=False, if_exists="replace")

    # ===== TABLE 5: macro_delinquency =====
    high_delinq_regions = set(
        REGIONS[idx] for idx in np.random.choice(num_regions, size=3, replace=False)
    )

    macro_records = []
    for region in REGIONS:
        is_high = region in high_delinq_regions
        for p in range(num_periods):
            y, m = _month_subtract(REFERENCE_DATE.year, REFERENCE_DATE.month, num_periods - 1 - p)
            period = f"{y:04d}-{m:02d}"

            if is_high:
                delinq_rate = round(float(np.random.uniform(0.065, 0.12)), 4)
            else:
                delinq_rate = round(float(np.random.uniform(0.02, 0.055)), 4)

            avg_util = round(float(np.random.uniform(0.3, 0.7)), 4)
            charge_off = round(float(np.random.uniform(0.005, 0.03)), 4)

            macro_records.append({
                "region_code": region,
                "period": period,
                "delinquency_rate": delinq_rate,
                "avg_utilization": avg_util,
                "charge_off_rate": charge_off,
            })

    pd.DataFrame(macro_records).to_sql("macro_delinquency", conn, index=False, if_exists="replace")

    conn.commit()
    conn.close()

    # ===== WORKSPACE FILES =====
    _generate_workspace(accounts, workspace, num_ws_files)


def _generate_workspace(accounts, workspace, num_ws_files):
    rng = np.random.RandomState(4242)
    num_accounts = len(accounts)

    # --- Fixed configuration files ---

    # 1. risk_thresholds.yaml
    risk_config = {
        "evaluation_period_months": 6,
        "scoring_weights": {
            "cash_advance_ratio": 25,
            "credit_score_decline": 30,
            "minimum_payment_streak": 25,
            "regional_delinquency": 20,
        },
        "thresholds": {
            "cash_advance_ratio": 0.20,
            "credit_score_decline_points": 50,
            "minimum_payment_consecutive_months": 3,
            "regional_delinquency_rate": 0.06,
        },
        "dti_bonus": {
            "moderate_threshold": 0.50,
            "moderate_bonus": 10,
            "high_threshold": 0.70,
            "high_bonus": 20,
        },
        "high_risk_cutoff": 55,
        "risk_levels": {
            "critical": 75,
            "high": 55,
            "moderate": 40,
        },
        "factor_priority": [
            "cash_advance_ratio",
            "credit_score_decline",
            "minimum_payment_streak",
            "regional_delinquency",
        ],
        "regional_adjustment_formula": "adjusted_rate = delinquency_rate * (1 + unemployment_adjustment)",
    }
    with open(os.path.join(workspace, "risk_thresholds.yaml"), "w") as f:
        yaml.dump(risk_config, f, default_flow_style=False, sort_keys=False)

    # 2. tier_config.json
    tier_config = {
        "platinum": {
            "risk_multiplier": 0.85,
            "reduction_rates": {"moderate": 0.15, "high": 0.30, "critical": 0.50},
        },
        "gold": {
            "risk_multiplier": 1.0,
            "reduction_rates": {"moderate": 0.20, "high": 0.35, "critical": 0.50},
        },
        "silver": {
            "risk_multiplier": 1.1,
            "reduction_rates": {"moderate": 0.25, "high": 0.40, "critical": 0.55},
        },
        "standard": {
            "risk_multiplier": 1.2,
            "reduction_rates": {"moderate": 0.30, "high": 0.45, "critical": 0.60},
        },
    }
    with open(os.path.join(workspace, "tier_config.json"), "w") as f:
        json.dump(tier_config, f, indent=2)

    # 3. limit_adjustment_policy.md
    policy_text = (
        "The recommended credit limit is computed by taking the current credit limit "
        "and multiplying it by one minus the applicable reduction rate for the account's "
        "tier and risk level. If the computed limit falls below five hundred dollars, it "
        "must be set to five hundred dollars. The final recommended limit must be rounded "
        "down to the nearest one hundred dollars.\n\n"
        "The primary risk factor for each flagged account is determined by identifying which "
        "of the triggered risk components carries the highest scoring weight. When two or more "
        "triggered factors share the same highest weight, the factor listed earlier in the "
        "factor_priority configuration takes precedence.\n\n"
        "Accounts enrolled in a hardship program must be excluded from the high-risk list "
        "regardless of their computed risk score. Only accounts with an active status should "
        "be evaluated; inactive accounts are excluded from the analysis entirely."
    )
    with open(os.path.join(workspace, "limit_adjustment_policy.md"), "w") as f:
        f.write(policy_text)

    # 4. regional_adjustments.json
    regional_adj = {}
    for region in REGIONS:
        adj = round(float(rng.uniform(-0.05, 0.15)), 3)
        regional_adj[region] = {"unemployment_adjustment": adj}
    with open(os.path.join(workspace, "regional_adjustments.json"), "w") as f:
        json.dump(regional_adj, f, indent=2)

    # --- Scalable data files: account supplements ---
    hardship_count = max(1, int(num_accounts * 0.05))
    hardship_indices = set(rng.choice(num_accounts, size=hardship_count, replace=False))

    segments = ["prime", "near_prime", "subprime"]
    supplement_data = []
    for i in range(num_accounts):
        dti = round(float(rng.uniform(0.15, 0.85)), 2)
        hardship = "yes" if i in hardship_indices else "no"
        segment = segments[int(rng.choice(len(segments), p=[0.4, 0.35, 0.25]))]
        supplement_data.append({
            "account_id": accounts[i]["account_id"],
            "debt_to_income_ratio": dti,
            "hardship_program": hardship,
            "customer_segment": segment,
        })

    accounts_per_file = max(1, num_accounts // num_ws_files)
    for file_idx in range(num_ws_files):
        start = file_idx * accounts_per_file
        if file_idx == num_ws_files - 1:
            end = num_accounts
        else:
            end = start + accounts_per_file
        batch = supplement_data[start:end]

        filepath = os.path.join(workspace, f"account_supplement_{file_idx + 1:03d}.csv")
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["account_id", "debt_to_income_ratio", "hardship_program", "customer_segment"]
            )
            writer.writeheader()
            writer.writerows(batch)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
