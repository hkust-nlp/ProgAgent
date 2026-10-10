import argparse
import json
import os
import sqlite3
import random
import csv
import numpy as np
from faker import Faker

SCALE = {
    "rows_per_table": 30,
    "num_workspace_files": 20,
}

METRICS = [
    "mrr", "arr", "monthly_churn_rate", "customer_count",
    "net_revenue_retention", "gross_margin", "monthly_burn_rate",
]

SECTORS = ["FinTech", "HealthTech", "EdTech", "DevTools", "MarketingTech", "Cybersecurity"]
FUNDS = ["Fund I", "Fund II", "Fund III", "Fund IV"]
STAGES = ["Seed", "Series A", "Series B", "Series C"]

CURRENT_QUARTER = "Q4-2025"
PREVIOUS_QUARTER = "Q3-2025"


def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS companies (
        company_id INTEGER PRIMARY KEY,
        name TEXT UNIQUE,
        sector TEXT,
        fund TEXT,
        stage TEXT,
        board_seat_partner TEXT,
        investment_date TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS saas_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id INTEGER,
        quarter TEXT,
        metric_name TEXT,
        value REAL,
        FOREIGN KEY (company_id) REFERENCES companies(company_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS board_deck_figures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id INTEGER,
        quarter TEXT,
        metric_name TEXT,
        value REAL,
        signoff_partner TEXT,
        signoff_date TEXT,
        FOREIGN KEY (company_id) REFERENCES companies(company_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS previous_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id INTEGER,
        quarter TEXT,
        metric_name TEXT,
        value REAL,
        validated INTEGER DEFAULT 1,
        FOREIGN KEY (company_id) REFERENCES companies(company_id)
    )""")
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    # Deterministic seeds
    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    fake = Faker()
    rng = np.random.RandomState(42)

    num_companies = SCALE["rows_per_table"]
    num_submissions = SCALE["num_workspace_files"]

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    # ---- Generate companies ----
    companies = []
    used_names = set()
    for i in range(1, num_companies + 1):
        while True:
            name = fake.company().replace("'", "").replace('"', "")
            if name not in used_names:
                used_names.add(name)
                break
        sector = SECTORS[int(rng.randint(0, len(SECTORS)))]
        fund = FUNDS[int(rng.randint(0, len(FUNDS)))]
        stage = STAGES[int(rng.randint(0, len(STAGES)))]
        partner = fake.name()
        inv_date = fake.date_between(start_date="-5y", end_date="-1y").isoformat()
        companies.append((i, name, sector, fund, stage, partner, inv_date))

    conn.executemany("INSERT INTO companies VALUES (?,?,?,?,?,?,?)", companies)
    company_map = {
        c[0]: {"id": c[0], "name": c[1], "sector": c[2], "fund": c[3],
               "stage": c[4], "partner": c[5], "inv_date": c[6]}
        for c in companies
    }

    # ---- Generate previous quarter metrics ----
    prev_metrics = {}
    for cid in range(1, num_companies + 1):
        prev_metrics[cid] = {}
        mrr = round(float(rng.uniform(50, 500)), 2)
        prev_metrics[cid]["mrr"] = mrr
        prev_metrics[cid]["arr"] = round(mrr * 12, 2)
        prev_metrics[cid]["monthly_churn_rate"] = round(float(rng.uniform(0.5, 8.0)), 2)
        prev_metrics[cid]["customer_count"] = int(rng.uniform(50, 5000))
        prev_metrics[cid]["net_revenue_retention"] = round(float(rng.uniform(85, 130)), 2)
        prev_metrics[cid]["gross_margin"] = round(float(rng.uniform(40, 85)), 2)
        prev_metrics[cid]["monthly_burn_rate"] = round(float(rng.uniform(20, 300)), 2)

        for metric in METRICS:
            conn.execute(
                "INSERT INTO previous_reports (company_id, quarter, metric_name, value, validated) VALUES (?,?,?,?,?)",
                (cid, PREVIOUS_QUARTER, metric, prev_metrics[cid][metric], 1),
            )

    # ---- Generate current quarter SaaS platform metrics (ground truth) ----
    saas_metrics = {}

    for cid in range(1, num_companies + 1):
        saas_metrics[cid] = {}

        # MRR with possible extreme growth
        prev_mrr = prev_metrics[cid]["mrr"]
        mrr_growth = float(rng.uniform(-0.10, 0.20))
        if rng.random() < 0.12:
            mrr_growth = float(rng.uniform(0.55, 1.50))
        saas_metrics[cid]["mrr"] = round(max(5.0, prev_mrr * (1 + mrr_growth)), 2)

        # ARR always 12 * MRR
        saas_metrics[cid]["arr"] = round(saas_metrics[cid]["mrr"] * 12, 2)

        # Customer count
        prev_cc = prev_metrics[cid]["customer_count"]
        cc_growth = float(rng.uniform(-0.08, 0.15))
        if rng.random() < 0.12:
            cc_growth = float(rng.uniform(0.45, 1.80))
        saas_metrics[cid]["customer_count"] = max(10, int(prev_cc * (1 + cc_growth)))

        # Churn rate (additive change)
        prev_churn = prev_metrics[cid]["monthly_churn_rate"]
        saas_metrics[cid]["monthly_churn_rate"] = round(
            max(0.1, prev_churn + float(rng.uniform(-1.5, 1.5))), 2
        )

        # Net Revenue Retention
        prev_nrr = prev_metrics[cid]["net_revenue_retention"]
        saas_metrics[cid]["net_revenue_retention"] = round(
            max(50, min(180, prev_nrr + float(rng.uniform(-3, 3)))), 2
        )

        # Gross Margin
        prev_gm = prev_metrics[cid]["gross_margin"]
        saas_metrics[cid]["gross_margin"] = round(
            max(10, min(95, prev_gm + float(rng.uniform(-2, 2)))), 2
        )

        # Burn rate
        prev_burn = prev_metrics[cid]["monthly_burn_rate"]
        burn_growth = float(rng.uniform(-0.10, 0.15))
        if rng.random() < 0.12:
            burn_growth = float(rng.uniform(0.65, 2.20))
        saas_metrics[cid]["monthly_burn_rate"] = round(
            max(5.0, prev_burn * (1 + burn_growth)), 2
        )

        for metric in METRICS:
            conn.execute(
                "INSERT INTO saas_metrics (company_id, quarter, metric_name, value) VALUES (?,?,?,?)",
                (cid, CURRENT_QUARTER, metric, saas_metrics[cid][metric]),
            )

    # ---- Generate board deck figures (~18% transcription error rate) ----
    board_deck = {}
    for cid in range(1, num_companies + 1):
        board_deck[cid] = {}
        partner = company_map[cid]["partner"]
        signoff_date = fake.date_between(start_date="-30d", end_date="-5d").isoformat()

        for metric in METRICS:
            saas_val = saas_metrics[cid][metric]
            val = saas_val

            if rng.random() < 0.18:
                if metric == "customer_count":
                    mag = max(10, int(abs(saas_val) * 0.08))
                    error = int(rng.choice([-1, 1])) * int(rng.randint(5, mag))
                    val = max(1, int(saas_val + error))
                else:
                    error_pct = float(rng.uniform(0.03, 0.12)) * int(rng.choice([-1, 1]))
                    val = round(saas_val * (1 + error_pct), 2)

            board_deck[cid][metric] = val
            conn.execute(
                "INSERT INTO board_deck_figures (company_id, quarter, metric_name, value, signoff_partner, signoff_date) VALUES (?,?,?,?,?,?)",
                (cid, CURRENT_QUARTER, metric, val, partner, signoff_date),
            )

    # ---- Select submitting companies ----
    all_ids = list(range(1, num_companies + 1))
    submitting_ids = sorted(
        rng.choice(all_ids, size=min(num_submissions, num_companies), replace=False).tolist()
    )

    # ---- Generate submission files (~22% per-metric error vs board deck) ----
    for cid in submitting_ids:
        metrics_submitted = {}
        for metric in METRICS:
            deck_val = board_deck[cid][metric]
            val = deck_val

            if rng.random() < 0.22:
                if metric == "customer_count":
                    mag = max(6, int(abs(deck_val) * 0.06))
                    error = int(rng.choice([-1, 1])) * int(rng.randint(3, mag))
                    val = max(1, int(deck_val + error))
                else:
                    error_pct = float(rng.uniform(0.025, 0.10)) * int(rng.choice([-1, 1]))
                    val = round(deck_val * (1 + error_pct), 2)

            metrics_submitted[metric] = val

        company_name = company_map[cid]["name"]
        safe_name = (
            company_name.replace(" ", "_")
            .replace(",", "")
            .replace(".", "")
            .replace("&", "and")
            .replace("-", "_")
        )
        filename = f"{safe_name}_Q4_2025_submission.json"

        submission = {
            "company_id": cid,
            "company_name": company_name,
            "quarter": CURRENT_QUARTER,
            "submission_date": fake.date_between(
                start_date="-15d", end_date="-1d"
            ).isoformat(),
            "metrics": metrics_submitted,
        }

        with open(os.path.join(args.workspace, filename), "w") as f:
            json.dump(submission, f, indent=2)

    # ================================================================
    # Fixed configuration files (not counted in num_workspace_files)
    # ================================================================

    # --- validation_rules.yaml ---
    validation_rules = """# Portfolio KPI Validation Rules
# Tolerances define the maximum acceptable discrepancy before flagging.

tolerances:
  mrr:
    type: relative
    value: 0.02
  arr:
    type: relative
    value: 0.02
  monthly_churn_rate:
    type: absolute
    value: 0.5
  customer_count:
    type: relative
    value: 0.03
  net_revenue_retention:
    type: absolute
    value: 1.0
  gross_margin:
    type: absolute
    value: 1.0
  monthly_burn_rate:
    type: relative
    value: 0.05

qoq_growth_caps:
  mrr: 0.50
  arr: 0.50
  customer_count: 0.40
  monthly_burn_rate: 0.60

severity_rules:
  critical: "discrepancy exceeds 3x tolerance AND absolute discrepancy exceeds materiality threshold"
  high: "discrepancy exceeds 3x tolerance OR absolute discrepancy exceeds materiality threshold"
  medium: "discrepancy exceeds 2x tolerance but not 3x, and does not exceed materiality threshold"
  low: "discrepancy exceeds 1x tolerance but not 2x, and does not exceed materiality threshold"
"""
    with open(os.path.join(args.workspace, "validation_rules.yaml"), "w") as f:
        f.write(validation_rules)

    # --- materiality_thresholds.csv ---
    sector_multipliers = {
        "FinTech": 1.0, "HealthTech": 1.2, "EdTech": 0.8,
        "DevTools": 0.9, "MarketingTech": 0.85, "Cybersecurity": 1.1,
    }
    mat_rows = []
    for sector in SECTORS:
        bm = sector_multipliers[sector]
        mat_rows.append({
            "sector": sector,
            "mrr": round(15 * bm, 2),
            "arr": round(180 * bm, 2),
            "monthly_churn_rate": round(1.5 * bm, 2),
            "customer_count": int(100 * bm),
            "net_revenue_retention": round(3.0 * bm, 2),
            "gross_margin": round(3.0 * bm, 2),
            "monthly_burn_rate": round(25 * bm, 2),
        })

    with open(os.path.join(args.workspace, "materiality_thresholds.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["sector"] + METRICS)
        writer.writeheader()
        writer.writerows(mat_rows)

    # --- fund_review_policy.txt ---
    fund_policy = """Fund Review Policy for Quarterly KPI Validation
===============================================

All portfolio companies across all funds must undergo full validation:
cross-referencing submitted financials against both SaaS platform data
and signed board deck figures, plus quarter-over-quarter growth analysis.

Fund-specific severity escalation rules:
- Fund I: No escalation. Standard severity classification applies.
- Fund II: No escalation. Standard severity classification applies.
- Fund III: All MEDIUM severity exceptions are escalated to HIGH.
- Fund IV: All MEDIUM severity exceptions are escalated to HIGH.

This escalation is applied after the initial severity classification
based on tolerance multiples and materiality thresholds.
"""
    with open(os.path.join(args.workspace, "fund_review_policy.txt"), "w") as f:
        f.write(fund_policy)

    # --- submissions_manifest.csv ---
    manifest_rows = []
    for cid in submitting_ids:
        company_name = company_map[cid]["name"]
        safe_name = (
            company_name.replace(" ", "_")
            .replace(",", "")
            .replace(".", "")
            .replace("&", "and")
            .replace("-", "_")
        )
        manifest_rows.append({
            "company_id": cid,
            "company_name": company_name,
            "submission_file": f"{safe_name}_Q4_2025_submission.json",
            "quarter": CURRENT_QUARTER,
        })

    with open(os.path.join(args.workspace, "submissions_manifest.csv"), "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["company_id", "company_name", "submission_file", "quarter"]
        )
        writer.writeheader()
        writer.writerows(manifest_rows)

    # --- metric_definitions.md ---
    metric_defs = """# SaaS KPI Metric Definitions

MRR (Monthly Recurring Revenue): Total predictable revenue normalized to a monthly
amount, expressed in thousands of dollars. ARR is always exactly 12 times MRR.

ARR (Annual Recurring Revenue): Annualized recurring revenue, expressed in thousands
of dollars. Computed as MRR multiplied by 12.

Monthly Churn Rate: Percentage of customers lost per month. Expressed as a percentage
value (e.g., 2.5 means 2.5 percent).

Customer Count: Total number of active paying customers at quarter end. Integer value.

Net Revenue Retention (NRR): Revenue retained from existing customers including
expansions and contractions. Expressed as a percentage (e.g., 110 means 110 percent).

Gross Margin: Revenue minus cost of goods sold divided by revenue. Expressed as a
percentage.

Monthly Burn Rate: Net cash outflow per month, expressed in thousands of dollars.
"""
    with open(os.path.join(args.workspace, "metric_definitions.md"), "w") as f:
        f.write(metric_defs)

    conn.commit()
    conn.close()
    print(f"Database created at {args.db_path}")
    print(
        f"Workspace initialized at {args.workspace} with "
        f"{len(submitting_ids)} submission files + config files"
    )


if __name__ == "__main__":
    main()
