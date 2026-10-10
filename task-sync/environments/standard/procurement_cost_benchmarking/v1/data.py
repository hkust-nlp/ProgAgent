import argparse
import json
import os
import sqlite3
import random
import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 80,
    "num_workspace_files": 24,
}

SEED = 42
CATEGORIES = [
    "cloud_services",
    "cybersecurity",
    "hardware",
    "networking",
    "software_licensing",
]


def main(db_path, workspace):
    random.seed(SEED)
    np.random.seed(SEED)
    fake = Faker()
    Faker.seed(SEED)
    os.makedirs(workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ------------------------------------------------------------------ #
    # Table 1: vendors                                                    #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vendors (
            vendor_id       INTEGER PRIMARY KEY,
            vendor_name     TEXT,
            incorporation_year INTEGER,
            size_category   TEXT,
            headquarters_state TEXT,
            primary_category TEXT,
            active          INTEGER
        )
    """)

    states = ["CA", "TX", "NY", "FL", "WA", "VA", "IL", "GA", "MA", "CO",
              "OH", "PA", "NC", "NJ", "AZ"]
    sizes = ["small", "medium", "large"]

    vendors = []
    for i in range(1, n_rows + 1):
        vendors.append((
            i,
            fake.company(),
            random.randint(1990, 2022),
            random.choice(sizes),
            random.choice(states),
            random.choice(CATEGORIES),
            1 if random.random() > 0.08 else 0,
        ))
    cur.executemany("INSERT INTO vendors VALUES (?,?,?,?,?,?,?)", vendors)

    # ------------------------------------------------------------------ #
    # Table 2: historical_bids                                            #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS historical_bids (
            bid_id          INTEGER PRIMARY KEY,
            vendor_id       INTEGER,
            category        TEXT,
            bid_amount      REAL,
            materials_pct   REAL,
            labor_pct       REAL,
            overhead_pct    REAL,
            awarded         INTEGER,
            bid_year        INTEGER,
            bid_quarter     INTEGER,
            FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id)
        )
    """)

    bid_years = [2021, 2022, 2023, 2024, 2025]
    n_bids = max(n_rows, len(vendors) * 3)
    bids = []
    for bid_id in range(1, n_bids + 1):
        v_id = random.randint(1, len(vendors))
        cat = random.choice(CATEGORIES)
        base_amount = random.uniform(80000, 600000)
        mat_pct = round(random.uniform(0.20, 0.50), 2)
        lab_pct = round(random.uniform(0.25, 0.45), 2)
        ovh_pct = round(max(0.05, 1.0 - mat_pct - lab_pct), 2)
        bids.append((
            bid_id, v_id, cat,
            round(base_amount, 2), mat_pct, lab_pct, ovh_pct,
            1 if random.random() > 0.55 else 0,
            random.choice(bid_years),
            random.randint(1, 4),
        ))
    cur.executemany("INSERT INTO historical_bids VALUES (?,?,?,?,?,?,?,?,?,?)", bids)

    # ------------------------------------------------------------------ #
    # Table 3: material_price_indices                                     #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS material_price_indices (
            index_id          INTEGER PRIMARY KEY,
            material_category TEXT,
            year              INTEGER,
            quarter           INTEGER,
            index_value       REAL,
            volatility        REAL
        )
    """)

    n_years_needed = max(4, (n_rows // (len(CATEGORIES) * 4)) + 2)
    start_year = 2026 - n_years_needed
    idx_id = 1
    indices = []
    for cat in CATEGORIES:
        base_val = 100.0 + random.uniform(-5, 5)
        for yr in range(start_year, 2027):
            for q in range(1, 5):
                drift = random.uniform(-2.5, 4.0)
                base_val = max(75, min(160, base_val + drift))
                vol = round(random.uniform(0.02, 0.14), 4)
                indices.append((idx_id, cat, yr, q, round(base_val, 2), vol))
                idx_id += 1
    cur.executemany("INSERT INTO material_price_indices VALUES (?,?,?,?,?,?)", indices)

    # ------------------------------------------------------------------ #
    # Table 4: vendor_financials                                          #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vendor_financials (
            record_id     INTEGER PRIMARY KEY,
            vendor_id     INTEGER,
            fiscal_year   INTEGER,
            revenue       REAL,
            net_income    REAL,
            total_debt    REAL,
            total_assets  REAL,
            current_ratio REAL,
            credit_score  INTEGER,
            FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id)
        )
    """)

    fin_years = [2023, 2024, 2025]
    rec_id = 1
    financials = []
    for v_id in range(1, len(vendors) + 1):
        base_rev = random.uniform(2e6, 8e8)
        for yr in fin_years:
            rev = round(base_rev * random.uniform(0.85, 1.15), 2)
            net_inc = round(rev * random.uniform(-0.04, 0.22), 2)
            total_assets = round(rev * random.uniform(0.9, 2.8), 2)
            total_debt = round(total_assets * random.uniform(0.10, 0.72), 2)
            cur_ratio = round(random.uniform(0.6, 3.8), 2)
            credit = random.randint(380, 840)
            financials.append((
                rec_id, v_id, yr, rev, net_inc,
                total_debt, total_assets, cur_ratio, credit,
            ))
            rec_id += 1
    cur.executemany("INSERT INTO vendor_financials VALUES (?,?,?,?,?,?,?,?,?)", financials)

    # ------------------------------------------------------------------ #
    # Table 5: budget_forecasts                                           #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS budget_forecasts (
            forecast_id    INTEGER PRIMARY KEY,
            fiscal_year    INTEGER,
            category       TEXT,
            allocated_budget REAL,
            priority_level TEXT
        )
    """)

    priorities = ["critical", "high", "medium", "low"]
    fc_id = 1
    budgets = []
    budget_years = list(range(2024, 2028))
    for yr in budget_years:
        for cat in CATEGORIES:
            amt = round(random.uniform(800000, 5000000), 2)
            budgets.append((fc_id, yr, cat, amt, random.choice(priorities)))
            fc_id += 1
    # pad to n_rows
    while len(budgets) < n_rows:
        yr = random.choice(budget_years)
        cat = random.choice(CATEGORIES)
        amt = round(random.uniform(800000, 5000000), 2)
        budgets.append((fc_id, yr, cat, amt, random.choice(priorities)))
        fc_id += 1
    cur.executemany("INSERT INTO budget_forecasts VALUES (?,?,?,?,?)", budgets)

    conn.commit()

    # ================================================================== #
    # Workspace: vendor-specific data (ONLY available through files)      #
    # ================================================================== #

    # --- operational_risk_rating per vendor (1.0 = best, 5.0 = worst) ---
    operational_risk = {}
    for v in vendors:
        operational_risk[v[0]] = round(random.uniform(1.0, 5.0), 1)

    # --- past_delivery_score per vendor (0-100, higher = better) ---
    delivery_scores = {}
    for v in vendors:
        delivery_scores[v[0]] = round(random.uniform(45, 98), 1)

    # --- forecast_adjustment_factor per category ---
    forecast_adj = {}
    for cat in CATEGORIES:
        forecast_adj[cat] = round(random.uniform(0.96, 1.12), 4)

    # ================================================================== #
    # Fixed config files (not counted in SCALE)                           #
    # ================================================================== #

    # scoring_weights.yaml
    scoring_cfg = {
        "risk_score_weights": {
            "financial_health": 0.40,
            "operational_risk": 0.30,
            "delivery_track_record": 0.30,
        },
        "financial_health_sub_weights": {
            "credit_score_normalized": 0.40,
            "current_ratio_normalized": 0.30,
            "leverage_score": 0.30,
        },
        "normalization": {
            "credit_score_min": 300,
            "credit_score_range": 550,
            "current_ratio_cap": 3.0,
        },
        "risk_premium": {
            "base": 0.02,
            "scale_factor": 0.08,
        },
        "price_adjustment": {
            "reference_year": 2025,
            "reference_quarter": 4,
            "base_year": 2023,
            "base_quarter": 1,
        },
    }
    with open(os.path.join(workspace, "scoring_weights.yaml"), "w") as f:
        yaml.dump(scoring_cfg, f, default_flow_style=False, sort_keys=False)

    # eligibility_criteria.json
    eligibility = {
        "min_credit_score": 550,
        "min_current_ratio": 1.0,
        "max_debt_to_asset_ratio": 0.65,
        "min_years_active": 3,
        "must_be_active": True,
        "reference_fiscal_year": 2025,
        "procurement_year": 2026,
    }
    with open(os.path.join(workspace, "eligibility_criteria.json"), "w") as f:
        json.dump(eligibility, f, indent=2)

    # market_forecast.json  (forecast_adjustment per category)
    mf = {
        "forecast_period": "FY2026",
        "generated": "2025-12-20",
        "category_adjustments": {}
    }
    for cat in CATEGORIES:
        mf["category_adjustments"][cat] = {
            "forecast_adjustment_factor": forecast_adj[cat],
            "trend": random.choice(["rising", "stable", "declining"]),
            "confidence": round(random.uniform(0.70, 0.95), 2),
        }
    with open(os.path.join(workspace, "market_forecast.json"), "w") as f:
        json.dump(mf, f, indent=2)

    # ================================================================== #
    # Scalable workspace files                                            #
    # ================================================================== #

    # Distribute into 3 types: .md, .csv, .txt
    n_md = n_files // 3 + (1 if n_files % 3 >= 1 else 0)
    n_csv = n_files // 3 + (1 if n_files % 3 >= 2 else 0)
    n_txt = n_files - n_md - n_csv
    if n_txt < 1:
        n_txt = 1
        n_md = max(1, n_md - 1)

    all_vendor_ids = [v[0] for v in vendors]

    # --- vendor dossiers (.md): contain operational_risk_rating ---
    batch_size_md = max(1, len(all_vendor_ids) // n_md + (1 if len(all_vendor_ids) % n_md else 0))
    for i in range(n_md):
        start = i * batch_size_md
        end = min(start + batch_size_md, len(all_vendor_ids))
        batch = all_vendor_ids[start:end]
        if not batch:
            break

        lines = [
            f"# Vendor Risk Assessment Dossier - Batch {i + 1}",
            f"",
            f"Assessment Period: Q4 2025",
            f"Prepared by: Procurement Risk Analysis Division",
            f"",
        ]
        for v_id in batch:
            v = vendors[v_id - 1]
            rating = operational_risk[v_id]
            lines.append(f"## Vendor {v_id}: {v[1]}")
            lines.append(f"")
            lines.append(f"- Operational Risk Rating: {rating}")
            lines.append(f"- Size Category: {v[3]}")
            lines.append(f"- Headquarters: {v[4]}")
            lines.append(f"- Primary Category: {v[5]}")
            if rating >= 4.0:
                lines.append(f"- Flag: Major operational concerns identified in recent audit cycle.")
            elif rating >= 3.0:
                lines.append(f"- Flag: Moderate operational risks; recommend enhanced monitoring.")
            else:
                lines.append(f"- Flag: Operational profile within acceptable parameters.")
            lines.append(f"")

        with open(os.path.join(workspace, f"vendor_dossier_{i + 1}.md"), "w") as f:
            f.write("\n".join(lines))

    # --- performance data (.csv): contain past_delivery_score ---
    batch_size_csv = max(1, len(all_vendor_ids) // n_csv + (1 if len(all_vendor_ids) % n_csv else 0))
    for i in range(n_csv):
        start = i * batch_size_csv
        end = min(start + batch_size_csv, len(all_vendor_ids))
        batch = all_vendor_ids[start:end]
        if not batch:
            break

        rows = []
        for v_id in batch:
            v = vendors[v_id - 1]
            rows.append({
                "vendor_id": v_id,
                "vendor_name": v[1],
                "past_delivery_score": delivery_scores[v_id],
                "on_time_delivery_pct": round(random.uniform(55, 100), 1),
                "quality_rating": round(random.uniform(2.0, 5.0), 1),
                "assessment_year": 2025,
            })
        df = pd.DataFrame(rows)
        df.to_csv(os.path.join(workspace, f"performance_data_{i + 1}.csv"), index=False)

    # --- evaluation notes (.txt): supplementary vendor context ---
    batch_size_txt = max(1, len(all_vendor_ids) // n_txt + (1 if len(all_vendor_ids) % n_txt else 0))
    for i in range(n_txt):
        start = i * batch_size_txt
        end = min(start + batch_size_txt, len(all_vendor_ids))
        batch = all_vendor_ids[start:end]
        if not batch:
            batch = all_vendor_ids[-2:]

        lines = [
            f"PROCUREMENT EVALUATION NOTES - SET {i + 1}",
            f"Date: 2025-11-30",
            f"Evaluator: Senior Procurement Analyst",
            f"{'=' * 55}",
            f"",
        ]
        for v_id in batch:
            v = vendors[v_id - 1]
            ds = delivery_scores[v_id]
            opr = operational_risk[v_id]
            lines.append(f"Vendor ID {v_id} - {v[1]}")
            lines.append(f"  Category Focus: {v[5]}")
            lines.append(f"  Size: {v[3].capitalize()}")
            if ds >= 80 and opr <= 2.5:
                lines.append(f"  Overall Assessment: Strong candidate with proven track record.")
            elif ds < 60 or opr >= 4.0:
                lines.append(f"  Overall Assessment: Significant concerns; proceed with caution.")
            else:
                lines.append(f"  Overall Assessment: Adequate performance; standard due diligence applies.")
            lines.append(f"")

        with open(os.path.join(workspace, f"evaluation_notes_{i + 1}.txt"), "w") as f:
            f.write("\n".join(lines))

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
