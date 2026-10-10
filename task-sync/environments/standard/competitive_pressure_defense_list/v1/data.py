"""
Data generation for competitive-pressure analysis task.
Generates a SQLite database and workspace files for the agent environment.
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
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 100,
    "num_workspace_files": 16,
}


def main(db_path: str, workspace: str):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ------------------------------------------------------------------ #
    #  Reference lists                                                     #
    # ------------------------------------------------------------------ #
    industries = [
        "Technology", "Healthcare", "Finance", "Manufacturing",
        "Retail", "Energy", "Telecom", "Media", "Logistics", "Education",
    ]
    tiers = ["Enterprise", "Mid-Market", "SMB"]
    regions = ["North America", "Europe", "Asia Pacific", "Latin America"]
    market_focuses = [
        "Enterprise Software", "Cloud Services", "Cybersecurity",
        "Data Analytics", "AI/ML", "DevOps", "CRM", "ERP",
        "Marketing Tech", "FinTech",
    ]
    platforms = ["Twitter", "LinkedIn", "Facebook", "Instagram"]
    stages = [
        "Prospecting", "Qualification", "Proposal",
        "Negotiation", "Closed Won", "Closed Lost", "At Risk",
    ]
    keywords_pool = [
        "enterprise software", "cloud migration", "data security",
        "business analytics", "digital transformation", "SaaS solutions",
        "IT infrastructure", "automation platform", "machine learning ops",
        "cybersecurity platform",
    ]
    products_pool = [
        "Basic Plan", "Professional Plan", "Enterprise Plan",
        "Data Add-on", "Security Module", "Analytics Suite",
        "API Access", "Premium Support", "Starter Pack", "Growth Plan",
    ]

    # ------------------------------------------------------------------ #
    #  Table 1: accounts                                                   #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            account_id        INTEGER PRIMARY KEY,
            name              TEXT,
            industry          TEXT,
            tier              TEXT,
            region            TEXT,
            annual_revenue    REAL,
            contract_end_date TEXT
        )
    """)
    account_names_used: set = set()
    accounts_rows = []
    for i in range(1, n_rows + 1):
        while True:
            aname = fake.company()
            if aname not in account_names_used:
                account_names_used.add(aname)
                break
        accounts_rows.append((
            i,
            aname,
            random.choice(industries),
            random.choice(tiers),
            random.choice(regions),
            round(random.uniform(1_000_000, 500_000_000), 2),
            fake.date_between(start_date="+1m", end_date="+12m").isoformat(),
        ))
    cur.executemany("INSERT INTO accounts VALUES (?,?,?,?,?,?,?)", accounts_rows)

    # ------------------------------------------------------------------ #
    #  Table 2: competitors                                                #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS competitors (
            competitor_id INTEGER PRIMARY KEY,
            name          TEXT,
            domain        TEXT,
            market_focus  TEXT,
            founded_year  INTEGER
        )
    """)
    comp_names_used: set = set()
    competitors_rows = []
    for i in range(1, n_rows + 1):
        while True:
            cname = fake.company()
            if cname not in comp_names_used and cname not in account_names_used:
                comp_names_used.add(cname)
                break
        domain = (
            cname.lower()
            .replace(" ", "")
            .replace(",", "")
            .replace(".", "")
            .replace("-", "")
            + ".com"
        )
        competitors_rows.append((
            i, cname, domain,
            random.choice(market_focuses),
            random.randint(1990, 2023),
        ))
    cur.executemany("INSERT INTO competitors VALUES (?,?,?,?,?)", competitors_rows)

    # ------------------------------------------------------------------ #
    #  Table 3: search_rankings  (daily ranks per competitor+keyword)      #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS search_rankings (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            competitor_id INTEGER,
            keyword       TEXT,
            rank_position INTEGER,
            search_date   TEXT,
            FOREIGN KEY (competitor_id) REFERENCES competitors(competitor_id)
        )
    """)
    dates_30 = pd.date_range(end="2026-04-20", periods=30).strftime("%Y-%m-%d").tolist()

    ranking_data = []
    for comp_id in range(1, n_rows + 1):
        n_kw = random.randint(2, 4)
        comp_kws = random.sample(keywords_pool, n_kw)
        for kw in comp_kws:
            base_rank = random.randint(3, 45)
            # positive trend = competitor rank number decreasing = rising
            trend = random.choice([-0.4, -0.25, -0.1, 0.0, 0.1, 0.2, 0.35])
            for j, d in enumerate(dates_30):
                r = max(1, int(base_rank - trend * j + random.gauss(0, 1.5)))
                ranking_data.append((comp_id, kw, r, d))
    cur.executemany(
        "INSERT INTO search_rankings (competitor_id, keyword, rank_position, search_date) "
        "VALUES (?,?,?,?)",
        ranking_data,
    )

    # ------------------------------------------------------------------ #
    #  Table 4: pricing_feeds                                              #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pricing_feeds (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            competitor_id    INTEGER,
            product_name     TEXT,
            our_price        REAL,
            competitor_price REAL,
            date_observed    TEXT,
            FOREIGN KEY (competitor_id) REFERENCES competitors(competitor_id)
        )
    """)
    pricing_data = []
    for comp_id in range(1, n_rows + 1):
        n_prod = random.randint(2, 5)
        comp_prods = random.sample(products_pool, n_prod)
        for prod in comp_prods:
            our_p = round(random.uniform(50, 5000), 2)
            for d in dates_30[-7:]:
                undercut_factor = random.uniform(0.70, 1.15)
                comp_p = round(our_p * undercut_factor, 2)
                pricing_data.append((comp_id, prod, our_p, comp_p, d))
    cur.executemany(
        "INSERT INTO pricing_feeds (competitor_id, product_name, our_price, "
        "competitor_price, date_observed) VALUES (?,?,?,?,?)",
        pricing_data,
    )

    # ------------------------------------------------------------------ #
    #  Table 5: social_media                                               #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS social_media (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            competitor_id    INTEGER,
            platform         TEXT,
            daily_posts      INTEGER,
            engagement_score REAL,
            post_date        TEXT,
            FOREIGN KEY (competitor_id) REFERENCES competitors(competitor_id)
        )
    """)
    social_data = []
    for comp_id in range(1, n_rows + 1):
        n_plat = random.randint(2, 4)
        comp_plats = random.sample(platforms, n_plat)
        for plat in comp_plats:
            base_posts = random.randint(2, 25)
            growth = random.choice([-0.3, 0.0, 0.3, 0.6, 1.2])
            for j, d in enumerate(dates_30):
                posts = max(0, int(base_posts + growth * j + random.gauss(0, 2)))
                eng = round(random.uniform(0, 100), 1)
                social_data.append((comp_id, plat, posts, eng, d))
    cur.executemany(
        "INSERT INTO social_media (competitor_id, platform, daily_posts, "
        "engagement_score, post_date) VALUES (?,?,?,?,?)",
        social_data,
    )

    # ------------------------------------------------------------------ #
    #  Table 6: deal_pipeline                                              #
    # ------------------------------------------------------------------ #
    cur.execute("""
        CREATE TABLE IF NOT EXISTS deal_pipeline (
            deal_id       INTEGER PRIMARY KEY,
            account_id    INTEGER,
            competitor_id INTEGER,
            stage         TEXT,
            deal_value    REAL,
            probability   REAL,
            last_activity TEXT,
            FOREIGN KEY (account_id)    REFERENCES accounts(account_id),
            FOREIGN KEY (competitor_id) REFERENCES competitors(competitor_id)
        )
    """)
    deal_data = []
    for deal_id in range(1, n_rows + 1):
        acc_id = random.randint(1, n_rows)
        comp_id = random.randint(1, n_rows)
        stage = random.choice(stages)
        deal_val = round(random.uniform(10_000, 2_000_000), 2)
        prob = round(random.uniform(0.05, 0.95), 2)
        act_date = fake.date_between(start_date="-60d", end_date="today").isoformat()
        deal_data.append((deal_id, acc_id, comp_id, stage, deal_val, prob, act_date))
    cur.executemany("INSERT INTO deal_pipeline VALUES (?,?,?,?,?,?,?)", deal_data)

    conn.commit()

    # ================================================================== #
    #  Workspace: fixed configuration files (not counted in SCALE)         #
    # ================================================================== #

    # 1. scoring_config.yaml
    scoring_config = {
        "weights": {
            "search_ranking": 0.25,
            "pricing_undercut": 0.30,
            "social_media_surge": 0.15,
            "pipeline_risk": 0.30,
        },
        "analysis_period_days": 30,
        "recent_window_days": 7,
    }
    with open(os.path.join(workspace, "scoring_config.yaml"), "w") as f:
        yaml.dump(scoring_config, f, default_flow_style=False)

    # 2. pressure_thresholds.json
    thresholds = {
        "HIGH": 0.65,
        "MEDIUM": 0.40,
        "LOW": 0.0,
    }
    with open(os.path.join(workspace, "pressure_thresholds.json"), "w") as f:
        json.dump(thresholds, f, indent=2)

    # 3. pipeline_stage_risks.csv
    stage_risks = [
        ("Prospecting",   0.10),
        ("Qualification",  0.20),
        ("Proposal",       0.50),
        ("Negotiation",    0.70),
        ("Closed Won",     0.00),
        ("Closed Lost",    0.00),
        ("At Risk",        0.90),
    ]
    with open(os.path.join(workspace, "pipeline_stage_risks.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stage", "risk_factor"])
        w.writerows(stage_risks)

    # 4. defense_playbook.md
    playbook = (
        "# Defense Playbook\n\n"
        "## HIGH Pressure\n"
        "Recommended action: Immediate executive engagement\n\n"
        "## MEDIUM Pressure\n"
        "Recommended action: Proactive account review\n\n"
        "## LOW Pressure\n"
        "Recommended action: Standard monitoring\n"
    )
    with open(os.path.join(workspace, "defense_playbook.md"), "w") as f:
        f.write(playbook)

    # ================================================================== #
    #  Workspace: scalable field-intelligence reports                      #
    # ================================================================== #
    accounts_df = pd.read_sql("SELECT * FROM accounts", conn)
    competitors_df = pd.read_sql("SELECT * FROM competitors", conn)

    accounts_per_file = max(1, math.ceil(len(accounts_df) / n_files))

    for fidx in range(n_files):
        start = fidx * accounts_per_file
        end = min(start + accounts_per_file, len(accounts_df))
        if fidx == n_files - 1:
            end = len(accounts_df)
        batch = accounts_df.iloc[start:end]

        entries = []
        for _, acc in batch.iterrows():
            modifier = round(random.uniform(0.50, 2.00), 2)
            obs_comp = competitors_df.iloc[random.randint(0, len(competitors_df) - 1)]
            entries.append({
                "account_id": int(acc["account_id"]),
                "account_name": acc["name"],
                "competitor_observed": obs_comp["name"],
                "observation": fake.paragraph(nb_sentences=2),
                "intel_modifier": modifier,
            })

        report = {
            "report_id": f"FIR-{fidx + 1:03d}",
            "analyst": fake.name(),
            "report_date": fake.date_between(
                start_date="-30d", end_date="today"
            ).isoformat(),
            "entries": entries,
        }
        with open(
            os.path.join(workspace, f"field_intel_report_{fidx + 1:03d}.json"), "w"
        ) as f:
            json.dump(report, f, indent=2)

    conn.close()
    print(f"Database created at {db_path}")
    print(f"Workspace populated at {workspace} ({n_files} intel files + 4 config files)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
