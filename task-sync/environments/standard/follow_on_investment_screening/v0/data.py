import argparse
import sqlite3
import os
import json
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 20,
    "num_workspace_files": 10,
}

SEED = 42


def main(db_path, workspace):
    np.random.seed(SEED)
    fake = Faker()
    Faker.seed(SEED)

    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    num_companies = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    # ------------------------------------------------------------------ #
    #  Sector / stage pools                                               #
    # ------------------------------------------------------------------ #
    sectors = [
        "FinTech", "HealthTech", "EdTech", "SaaS",
        "CleanTech", "AI/ML", "Cybersecurity", "E-Commerce",
    ]
    stages = ["Pre-Seed", "Seed", "Series A", "Series B", "Series C"]
    stage_probs = [0.05, 0.10, 0.40, 0.35, 0.10]

    # ------------------------------------------------------------------ #
    #  Table 1: companies                                                 #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            company_id   INTEGER PRIMARY KEY,
            name         TEXT NOT NULL,
            sector       TEXT NOT NULL,
            stage        TEXT NOT NULL,
            founded_year INTEGER,
            hq_city      TEXT,
            employee_count INTEGER,
            initial_investment_date TEXT
        )
    """)

    companies = []
    used_names = set()
    for i in range(num_companies):
        name = fake.company()
        while name in used_names:
            name = fake.company()
        used_names.add(name)
        c = {
            "company_id": i + 1,
            "name": name,
            "sector": str(np.random.choice(sectors)),
            "stage": str(np.random.choice(stages, p=stage_probs)),
            "founded_year": int(np.random.randint(2015, 2024)),
            "hq_city": fake.city(),
            "employee_count": int(np.random.randint(10, 500)),
            "initial_investment_date": fake.date_between(
                start_date="-5y", end_date="-1y"
            ).isoformat(),
        }
        companies.append(c)

    for c in companies:
        cur.execute(
            "INSERT INTO companies VALUES (?,?,?,?,?,?,?,?)",
            (
                c["company_id"], c["name"], c["sector"], c["stage"],
                c["founded_year"], c["hq_city"], c["employee_count"],
                c["initial_investment_date"],
            ),
        )

    # ------------------------------------------------------------------ #
    #  Table 2: monthly_financials  (12 months per company)               #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS monthly_financials (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id  INTEGER,
            month       TEXT,
            revenue     REAL,
            expenses    REAL,
            burn_rate   REAL,
            cash_on_hand REAL,
            FOREIGN KEY (company_id) REFERENCES companies(company_id)
        )
    """)

    months = (
        pd.date_range("2024-01-01", periods=12, freq="MS")
        .strftime("%Y-%m")
        .tolist()
    )

    for c in companies:
        base_rev = float(np.random.uniform(20000, 300000))
        growth = float(np.random.uniform(-0.02, 0.08))
        base_exp = base_rev * float(np.random.uniform(0.8, 2.5))
        cash = float(np.random.uniform(500000, 10000000))

        for idx, month in enumerate(months):
            rev = base_rev * (1 + growth) ** idx
            exp = base_exp * (1 + float(np.random.uniform(-0.02, 0.04))) ** idx
            burn = exp - rev
            cash = cash - burn
            cur.execute(
                "INSERT INTO monthly_financials "
                "(company_id, month, revenue, expenses, burn_rate, cash_on_hand) "
                "VALUES (?,?,?,?,?,?)",
                (
                    c["company_id"], month,
                    round(rev, 2), round(exp, 2),
                    round(burn, 2), round(cash, 2),
                ),
            )

    # ------------------------------------------------------------------ #
    #  Table 3: cap_table                                                 #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cap_table (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id       INTEGER,
            shareholder_name TEXT,
            shareholder_type TEXT,
            shares           INTEGER,
            ownership_pct    REAL,
            round_acquired   TEXT,
            FOREIGN KEY (company_id) REFERENCES companies(company_id)
        )
    """)

    rounds_pool = ["Founding", "Seed", "Series A", "Series B"]
    min_shareholders = max(5, math.ceil(SCALE["rows_per_table"] / num_companies * 5))

    for c in companies:
        remaining = 100.0
        shareholders = []

        # Founders
        num_founders = int(np.random.randint(1, 4))
        founder_total = float(np.random.uniform(15, 65))
        for f in range(num_founders):
            pct = round(founder_total / num_founders, 2)
            shareholders.append(
                (
                    fake.name(),
                    "Founder" if f == 0 else "Co-Founder",
                    int(pct * 10000),
                    pct,
                    "Founding",
                )
            )
            remaining -= pct

        # Other shareholders
        for _ in range(min_shareholders - num_founders):
            if remaining <= 0.5:
                break
            sh_type = str(np.random.choice(
                ["Angel", "VC", "Employee Pool"], p=[0.3, 0.5, 0.2]
            ))
            pct = round(min(float(np.random.uniform(1, 12)), remaining), 2)
            remaining -= pct
            shareholders.append(
                (
                    fake.name() if sh_type != "Employee Pool" else "ESOP",
                    sh_type,
                    int(pct * 10000),
                    pct,
                    str(np.random.choice(rounds_pool[1:])),
                )
            )

        for sh in shareholders:
            cur.execute(
                "INSERT INTO cap_table "
                "(company_id, shareholder_name, shareholder_type, shares, "
                "ownership_pct, round_acquired) VALUES (?,?,?,?,?,?)",
                (c["company_id"], *sh),
            )

    # ------------------------------------------------------------------ #
    #  Table 4: competitor_funding                                        #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS competitor_funding (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            competitor_name TEXT,
            sector          TEXT,
            round_type      TEXT,
            amount_raised   REAL,
            lead_investor   TEXT,
            funding_date    TEXT
        )
    """)

    num_competitors = max(SCALE["rows_per_table"], num_companies * 3)
    for _ in range(num_competitors):
        cur.execute(
            "INSERT INTO competitor_funding "
            "(competitor_name, sector, round_type, amount_raised, "
            "lead_investor, funding_date) VALUES (?,?,?,?,?,?)",
            (
                fake.company(),
                str(np.random.choice(sectors)),
                str(np.random.choice(
                    ["Seed", "Series A", "Series B", "Series C", "Series D"]
                )),
                round(float(np.random.uniform(500000, 100000000)), 2),
                fake.company(),
                fake.date_between(start_date="-2y", end_date="today").isoformat(),
            ),
        )

    # ------------------------------------------------------------------ #
    #  Table 5: partner_sentiments                                        #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS partner_sentiments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id      INTEGER,
            partner_name    TEXT,
            sentiment_score REAL,
            assessment_date TEXT,
            focus_area      TEXT,
            FOREIGN KEY (company_id) REFERENCES companies(company_id)
        )
    """)

    partner_pool = [fake.name() for _ in range(8)]
    focus_areas = [
        "Growth Potential", "Market Fit", "Team Strength",
        "Technology", "Unit Economics", "Competitive Moat",
    ]

    # Ensure at least SCALE["rows_per_table"] total rows
    min_assessments_total = SCALE["rows_per_table"]
    base_per_company = max(2, math.ceil(min_assessments_total / num_companies))

    for c in companies:
        n_assess = int(np.random.randint(base_per_company, base_per_company + 4))
        for _ in range(n_assess):
            cur.execute(
                "INSERT INTO partner_sentiments "
                "(company_id, partner_name, sentiment_score, "
                "assessment_date, focus_area) VALUES (?,?,?,?,?)",
                (
                    c["company_id"],
                    str(np.random.choice(partner_pool)),
                    round(float(np.random.uniform(1.0, 10.0)), 1),
                    fake.date_between(
                        start_date="-1y", end_date="today"
                    ).isoformat(),
                    str(np.random.choice(focus_areas)),
                ),
            )

    conn.commit()

    # ================================================================== #
    #  WORKSPACE FILES                                                    #
    # ================================================================== #

    # ---- Fixed file 1: investment_criteria.yaml ---- #
    criteria = {
        "eligibility": {
            "allowed_stages": ["Series A", "Series B"],
            "min_avg_monthly_revenue": 40000,
            "min_founder_ownership_pct": 12.0,
            "min_avg_partner_sentiment": 5.5,
        },
        "tier_thresholds": {
            "high_priority_min": 75,
            "medium_priority_min": 50,
        },
        "output": {
            "filename": "prioritized_outreach.csv",
            "sort_primary": "composite_score_descending",
            "sort_tiebreaker": "company_name_ascending",
            "score_decimal_places": 2,
        },
    }
    with open(os.path.join(workspace, "investment_criteria.yaml"), "w") as f:
        yaml.dump(criteria, f, default_flow_style=False, sort_keys=False)

    # ---- Fixed file 2: scoring_config.json ---- #
    scoring = {
        "weights": {
            "revenue_growth": 0.25,
            "burn_efficiency": 0.20,
            "dilution_health": 0.15,
            "competitive_position": 0.15,
            "partner_sentiment": 0.15,
            "strategic_fit": 0.10,
        },
        "normalization": {
            "max_revenue_growth_pct": 20.0,
            "max_burn_multiple": 5.0,
            "benchmark_founder_ownership_pct": 50.0,
            "max_sector_competitor_funding": 500000000,
        },
        "metric_definitions": {
            "revenue_growth": "Average month-over-month revenue growth percentage across the last three monthly transitions of available data.",
            "burn_efficiency": "Average burn multiple over the last three months, where burn multiple equals burn rate divided by revenue. If monthly revenue is zero or negative, treat that months burn multiple as the max_burn_multiple value.",
            "dilution_health": "Sum of ownership_pct for all shareholders classified as Founder or Co-Founder.",
            "competitive_position": "Total amount_raised across all competitor funding rounds in the same sector as the portfolio company.",
            "partner_sentiment": "Arithmetic mean of all sentiment scores recorded for the company.",
            "strategic_fit": "Strategic fit score as recorded in the firms intelligence assessments.",
        },
        "score_formulas": {
            "revenue_growth_score": "min(100, max(0, avg_growth_pct / max_revenue_growth_pct * 100))",
            "burn_efficiency_score": "min(100, max(0, (1 - avg_burn_multiple / max_burn_multiple) * 100))",
            "dilution_health_score": "min(100, founder_ownership_pct / benchmark_founder_ownership_pct * 100)",
            "competitive_position_score": "min(100, max(0, (1 - total_sector_funding / max_sector_competitor_funding) * 100))",
            "partner_sentiment_score": "min(100, avg_sentiment / 10.0 * 100)",
            "strategic_fit_score": "min(100, strategic_fit_value / 10.0 * 100)",
        },
        "composite": "Sum of (weight_i * score_i) for each factor.",
    }
    with open(os.path.join(workspace, "scoring_config.json"), "w") as f:
        json.dump(scoring, f, indent=2)

    # ---- Scalable files: intelligence reports ---- #
    # Generate strategic fit scores (ONLY stored in workspace, not in DB)
    strategic_scores = {}
    for c in companies:
        strategic_scores[c["company_id"]] = round(
            float(np.random.uniform(2.0, 10.0)), 1
        )

    companies_per_file = max(1, math.ceil(num_companies / num_files))
    fmt_cycle = [".md", ".json", ".txt", ".csv", ".yaml"]

    for fi in range(num_files):
        start = fi * companies_per_file
        end = min(start + companies_per_file, num_companies)
        batch = companies[start:end] if start < num_companies else [companies[fi % num_companies]]

        fmt = fmt_cycle[fi % len(fmt_cycle)]
        fname = f"intel_report_{fi + 1:03d}{fmt}"
        fpath = os.path.join(workspace, fname)

        if fmt == ".md":
            _write_md(fpath, batch, strategic_scores, fake)
        elif fmt == ".json":
            _write_json(fpath, batch, strategic_scores, fake)
        elif fmt == ".txt":
            _write_txt(fpath, batch, strategic_scores, fake)
        elif fmt == ".csv":
            _write_csv(fpath, batch, strategic_scores)
        elif fmt == ".yaml":
            _write_yaml(fpath, batch, strategic_scores, fake)

    conn.close()
    print(f"Database created at {db_path}")
    print(f"Workspace populated in {workspace}")


# ------------------------------------------------------------------ #
#  Workspace-file writers                                             #
# ------------------------------------------------------------------ #
def _write_md(path, batch, scores, fake):
    with open(path, "w") as f:
        for c in batch:
            f.write(f"# Intelligence Report: {c['name']}\n\n")
            f.write(f"Company ID: {c['company_id']}\n\n")
            f.write("## Strategic Assessment\n\n")
            f.write(f"Strategic Fit Score: {scores[c['company_id']]}\n\n")
            f.write(f"Observations: {fake.paragraph(nb_sentences=3)}\n\n")
            f.write(f"Risk Factors: {fake.paragraph(nb_sentences=2)}\n\n")
            f.write("---\n\n")


def _write_json(path, batch, scores, fake):
    data = []
    for c in batch:
        data.append({
            "company_id": c["company_id"],
            "company_name": c["name"],
            "strategic_fit_score": scores[c["company_id"]],
            "market_position": fake.sentence(),
            "risk_assessment": fake.sentence(),
        })
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _write_txt(path, batch, scores, fake):
    with open(path, "w") as f:
        for c in batch:
            f.write(f"COMPANY: {c['name']} (ID: {c['company_id']})\n")
            f.write(f"STRATEGIC FIT SCORE: {scores[c['company_id']]}\n")
            f.write(f"NOTES: {fake.paragraph(nb_sentences=3)}\n")
            f.write("=" * 60 + "\n")


def _write_csv(path, batch, scores):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["company_id", "company_name", "strategic_fit_score"])
        for c in batch:
            w.writerow([c["company_id"], c["name"], scores[c["company_id"]]])


def _write_yaml(path, batch, scores, fake):
    data = {}
    for c in batch:
        data[f"company_{c['company_id']}"] = {
            "name": c["name"],
            "strategic_fit_score": scores[c["company_id"]],
            "analyst_notes": fake.sentence(),
        }
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
