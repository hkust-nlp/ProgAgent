#!/usr/bin/env python3
"""Data generation for quarterly contract renewal forecast task."""

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

SCALE = {
    "rows_per_table": 50,
    "num_workspace_files": 8,
}

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# --- Constants ---
PLATFORMS = [
    "Salesforce", "Slack", "Jira", "Snowflake", "Datadog",
    "HubSpot", "Zendesk", "ServiceNow", "Workday", "Tableau",
    "Confluence", "GitHub Enterprise", "PagerDuty", "Splunk", "Okta",
]

INDUSTRIES = [
    "Technology", "Financial Services", "Healthcare", "Manufacturing",
    "Retail", "Education", "Energy", "Telecommunications", "Media", "Logistics",
]

TIERS = ["Bronze", "Silver", "Gold", "Platinum"]
TIER_WEIGHTS = [0.25, 0.35, 0.25, 0.15]

REGIONS = ["North America", "Europe", "Asia-Pacific", "Latin America"]

SENTIMENTS = ["positive", "neutral", "negative"]
SENTIMENT_WEIGHTS = [0.40, 0.35, 0.25]

CHANNELS = ["email", "phone", "meeting", "survey", "support_ticket"]

NEGOTIATION_OUTCOMES = ["renewed", "escalated", "concession_made", "pending", "lost"]

CONTACT_ROLES = [
    "VP of Engineering", "CTO", "IT Director", "Procurement Manager",
    "CFO", "Head of Operations", "Product Manager", "Chief Data Officer",
]

PAYMENT_TERMS = ["monthly", "quarterly", "annual"]

# Usage metric generation months (6 months ending 2026-04)
USAGE_MONTHS = ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04"]


def create_tables(conn):
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS clients (
            client_id TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            industry TEXT NOT NULL,
            region TEXT NOT NULL,
            tier TEXT NOT NULL,
            account_manager TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS contracts (
            contract_id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            platform_name TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            annual_value REAL NOT NULL,
            status TEXT NOT NULL,
            auto_renew INTEGER NOT NULL,
            payment_terms TEXT NOT NULL,
            FOREIGN KEY (client_id) REFERENCES clients(client_id)
        );

        CREATE TABLE IF NOT EXISTS usage_metrics (
            metric_id TEXT PRIMARY KEY,
            contract_id TEXT NOT NULL,
            month TEXT NOT NULL,
            active_users INTEGER NOT NULL,
            api_calls INTEGER NOT NULL,
            storage_used_gb REAL NOT NULL,
            feature_adoption_pct REAL NOT NULL,
            FOREIGN KEY (contract_id) REFERENCES contracts(contract_id)
        );

        CREATE TABLE IF NOT EXISTS stakeholder_feedback (
            feedback_id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            contact_name TEXT NOT NULL,
            contact_role TEXT NOT NULL,
            sentiment TEXT NOT NULL,
            feedback_text TEXT NOT NULL,
            feedback_date TEXT NOT NULL,
            channel TEXT NOT NULL,
            FOREIGN KEY (client_id) REFERENCES clients(client_id)
        );

        CREATE TABLE IF NOT EXISTS negotiation_history (
            negotiation_id TEXT PRIMARY KEY,
            contract_id TEXT NOT NULL,
            negotiation_date TEXT NOT NULL,
            negotiator TEXT NOT NULL,
            outcome TEXT NOT NULL,
            discount_offered_pct REAL NOT NULL,
            final_discount_pct REAL NOT NULL,
            duration_days INTEGER NOT NULL,
            notes TEXT NOT NULL,
            FOREIGN KEY (contract_id) REFERENCES contracts(contract_id)
        );
    """)
    conn.commit()


def generate_clients(conn, n):
    clients = []
    for i in range(n):
        client_id = f"CLI-{i+1:04d}"
        company_name = fake.company()
        industry = random.choice(INDUSTRIES)
        region = random.choice(REGIONS)
        tier = random.choices(TIERS, weights=TIER_WEIGHTS, k=1)[0]
        account_manager = fake.name()
        clients.append(
            (client_id, company_name, industry, region, tier, account_manager)
        )
    conn.executemany("INSERT INTO clients VALUES (?, ?, ?, ?, ?, ?)", clients)
    conn.commit()
    return clients


def generate_contracts(conn, n, client_rows):
    client_ids = [c[0] for c in client_rows]
    contracts = []
    for i in range(n):
        contract_id = f"CNT-{i+1:04d}"
        client_id = client_ids[i % len(client_ids)]
        platform_name = PLATFORMS[i % len(PLATFORMS)]

        # ~30% expire in Q3 2026 (target quarter)
        if random.random() < 0.30:
            end_month = random.randint(7, 9)
            end_day = random.randint(1, 28)
            end_date = f"2026-{end_month:02d}-{end_day:02d}"
        else:
            quarter_month = random.choice([10, 11, 12, 1, 2, 3, 4, 5, 6])
            year = 2026 if quarter_month >= 10 else 2027
            end_day = random.randint(1, 28)
            end_date = f"{year}-{quarter_month:02d}-{end_day:02d}"

        years_back = random.choice([1, 2, 3])
        ep = end_date.split("-")
        start_year = int(ep[0]) - years_back
        start_date = f"{start_year}-{ep[1]}-{ep[2]}"

        annual_value = round(random.uniform(10000, 500000), 2)
        status = "active"
        auto_renew = random.choice([0, 1])
        payment_terms = random.choice(PAYMENT_TERMS)

        contracts.append(
            (
                contract_id,
                client_id,
                platform_name,
                start_date,
                end_date,
                annual_value,
                status,
                auto_renew,
                payment_terms,
            )
        )
    conn.executemany("INSERT INTO contracts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", contracts)
    conn.commit()
    return contracts


def generate_usage_metrics(conn, contracts):
    """Generate 6 months of usage data per contract."""
    metrics = []
    metric_counter = 0
    for contract in contracts:
        contract_id = contract[0]
        base_users = random.randint(10, 1000)
        base_api = random.randint(1000, 500000)
        base_storage = round(random.uniform(1.0, 200.0), 2)
        base_adoption = round(random.uniform(20.0, 95.0), 2)

        # Monthly trend: some contracts declining, some stable, some growing
        user_trend = random.choice([-0.08, -0.05, -0.02, 0.0, 0.02, 0.05, 0.08])
        api_trend = random.choice([-0.06, -0.03, 0.0, 0.03, 0.06])

        for m_idx, month in enumerate(USAGE_MONTHS):
            metric_counter += 1
            metric_id = f"MET-{metric_counter:06d}"
            factor = 1.0 + user_trend * m_idx
            active_users = max(1, int(base_users * factor + random.gauss(0, base_users * 0.05)))
            api_factor = 1.0 + api_trend * m_idx
            api_calls = max(0, int(base_api * api_factor + random.gauss(0, base_api * 0.05)))
            storage = max(0.1, round(base_storage + random.gauss(0, 1.0), 2))
            adoption = max(5.0, min(100.0, round(base_adoption + random.gauss(0, 2.0), 2)))

            metrics.append(
                (metric_id, contract_id, month, active_users, api_calls, storage, adoption)
            )
    conn.executemany("INSERT INTO usage_metrics VALUES (?, ?, ?, ?, ?, ?, ?)", metrics)
    conn.commit()


def generate_stakeholder_feedback(conn, n, client_rows):
    """Generate at least n feedback entries spread across clients."""
    feedback_list = []
    fb_counter = 0
    entries_per_client = max(1, n // len(client_rows))
    remainder = n - entries_per_client * len(client_rows)

    for idx, client_row in enumerate(client_rows):
        client_id = client_row[0]
        count = entries_per_client + (1 if idx < remainder else 0)
        for _ in range(count):
            fb_counter += 1
            feedback_id = f"FB-{fb_counter:05d}"
            contact_name = fake.name()
            contact_role = random.choice(CONTACT_ROLES)
            sentiment = random.choices(SENTIMENTS, weights=SENTIMENT_WEIGHTS, k=1)[0]
            feedback_text = fake.paragraph(nb_sentences=3)
            feedback_date = fake.date_between_dates(
                date_start=pd.Timestamp("2025-06-01"),
                date_end=pd.Timestamp("2026-04-15"),
            ).isoformat()
            channel = random.choice(CHANNELS)
            feedback_list.append(
                (feedback_id, client_id, contact_name, contact_role, sentiment, feedback_text, feedback_date, channel)
            )
    conn.executemany(
        "INSERT INTO stakeholder_feedback VALUES (?, ?, ?, ?, ?, ?, ?, ?)", feedback_list
    )
    conn.commit()


def generate_negotiation_history(conn, n, contracts):
    """Generate at least n negotiation records spread across contracts."""
    history = []
    neg_counter = 0
    entries_per_contract = max(1, n // len(contracts))
    remainder = n - entries_per_contract * len(contracts)

    for idx, contract in enumerate(contracts):
        contract_id = contract[0]
        count = entries_per_contract + (1 if idx < remainder else 0)
        for _ in range(count):
            neg_counter += 1
            neg_id = f"NEG-{neg_counter:05d}"
            neg_date = fake.date_between_dates(
                date_start=pd.Timestamp("2024-01-01"),
                date_end=pd.Timestamp("2026-04-01"),
            ).isoformat()
            negotiator = fake.name()
            outcome = random.choice(NEGOTIATION_OUTCOMES)
            discount_offered = round(random.uniform(0, 25), 2)
            final_discount = round(random.uniform(0, discount_offered) if discount_offered > 0 else 0, 2)
            duration_days = random.randint(5, 90)
            notes = fake.paragraph(nb_sentences=2)
            history.append(
                (neg_id, contract_id, neg_date, negotiator, outcome, discount_offered, final_discount, duration_days, notes)
            )
    conn.executemany(
        "INSERT INTO negotiation_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", history
    )
    conn.commit()


# --- Workspace generation ---

def generate_config_files(workspace):
    """Generate fixed configuration files (not scaled)."""
    config_dir = os.path.join(workspace, "config")
    os.makedirs(config_dir, exist_ok=True)

    # scoring_config.yaml
    scoring_config = (
        "scoring_weights:\n"
        "  usage_decline: 0.25\n"
        "  sentiment_risk: 0.20\n"
        "  strategic_importance: 0.20\n"
        "  competitive_threat: 0.20\n"
        "  negotiation_difficulty: 0.15\n"
        "\n"
        "normalization:\n"
        "  usage_decline:\n"
        '    description: "Percentage decline in average monthly active_users over the last 3 months vs the first 3 months of the 6-month window. A positive value means decline. Score equals min(100, max(0, decline_pct * 2)). If usage grew, decline_pct is 0."\n'
        "  sentiment_risk:\n"
        '    description: "Percentage of negative-sentiment feedback entries for the client. Score equals (negative_count / total_count) * 100. If no feedback exists, score is 50."\n'
        "  strategic_importance:\n"
        '    description: "Taken directly from client dossier files. Value on 1-10 scale is multiplied by 10 to yield 0-100 score."\n'
        "  competitive_threat:\n"
        '    description: "Taken directly from competitive analysis files. Value on 1-10 scale is multiplied by 10 to yield 0-100 score."\n'
        "  negotiation_difficulty:\n"
        '    description: "Taken directly from negotiation brief files. Value on 1-10 scale is multiplied by 10 to yield 0-100 score."\n'
        "\n"
        "target_quarter:\n"
        '  label: "Q3 2026"\n'
        '  start_date: "2026-07-01"\n'
        '  end_date: "2026-09-30"\n'
    )
    with open(os.path.join(config_dir, "scoring_config.yaml"), "w") as f:
        f.write(scoring_config)

    # renewal_policy.json
    renewal_policy = {
        "action_thresholds": {
            "Platinum": {
                "auto_renew_below": 30,
                "standard_renewal_below": 55,
                "manager_review_below": 75,
                "executive_escalation_at_or_above": 75,
            },
            "Gold": {
                "auto_renew_below": 25,
                "standard_renewal_below": 50,
                "manager_review_below": 70,
                "executive_escalation_at_or_above": 70,
            },
            "Silver": {
                "auto_renew_below": 20,
                "standard_renewal_below": 45,
                "manager_review_below": 65,
                "executive_escalation_at_or_above": 65,
            },
            "Bronze": {
                "auto_renew_below": 15,
                "standard_renewal_below": 40,
                "manager_review_below": 60,
                "executive_escalation_at_or_above": 60,
            },
        },
        "action_labels": [
            "auto_renew",
            "standard_renewal",
            "manager_review",
            "executive_escalation",
        ],
    }
    with open(os.path.join(config_dir, "renewal_policy.json"), "w") as f:
        json.dump(renewal_policy, f, indent=2)

    # discount_schedule.csv
    rows = [["tier", "min_value", "max_value", "max_discount_pct"]]
    for tier, discounts in [
        ("Bronze", [5, 8, 10]),
        ("Silver", [8, 12, 15]),
        ("Gold", [10, 15, 18]),
        ("Platinum", [12, 18, 22]),
    ]:
        rows.append([tier, 0, 50000, discounts[0]])
        rows.append([tier, 50001, 200000, discounts[1]])
        rows.append([tier, 200001, 500000, discounts[2]])
    with open(os.path.join(config_dir, "discount_schedule.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def generate_client_dossiers(conn, workspace, num_files):
    """Generate client dossier JSON files with strategic_importance and budget_flexibility."""
    dossier_dir = os.path.join(workspace, "client_dossiers")
    os.makedirs(dossier_dir, exist_ok=True)

    cursor = conn.cursor()
    cursor.execute("SELECT client_id, company_name FROM clients ORDER BY client_id")
    all_clients = cursor.fetchall()

    batch_size = math.ceil(len(all_clients) / num_files)
    for file_idx in range(num_files):
        start = file_idx * batch_size
        end = min(start + batch_size, len(all_clients))
        batch = all_clients[start:end]

        dossier_entries = []
        for client_id, company_name in batch:
            dossier_entries.append(
                {
                    "client_id": client_id,
                    "company_name": company_name,
                    "strategic_importance": random.randint(1, 10),
                    "budget_flexibility": random.choice(["low", "medium", "high"]),
                    "key_contact": fake.name(),
                    "last_business_review": fake.date_between_dates(
                        date_start=pd.Timestamp("2025-10-01"),
                        date_end=pd.Timestamp("2026-04-01"),
                    ).isoformat(),
                }
            )

        with open(os.path.join(dossier_dir, f"batch_{file_idx+1:03d}.json"), "w") as f:
            json.dump(dossier_entries, f, indent=2)


def generate_competitive_analysis(conn, workspace, num_files):
    """Generate competitive analysis CSV files with competitor_threat_level per contract."""
    analysis_dir = os.path.join(workspace, "competitive_analysis")
    os.makedirs(analysis_dir, exist_ok=True)

    competitors = [
        "Oracle Cloud", "Microsoft Azure", "Google Workspace", "SAP",
        "Freshworks", "Monday.com", "Asana", "Notion", "Databricks",
        "New Relic", "Elastic", "Sumo Logic", "CrowdStrike", "Auth0",
    ]

    cursor = conn.cursor()
    cursor.execute("SELECT contract_id, platform_name FROM contracts ORDER BY contract_id")
    all_contracts = cursor.fetchall()

    batch_size = math.ceil(len(all_contracts) / num_files)
    for file_idx in range(num_files):
        start = file_idx * batch_size
        end = min(start + batch_size, len(all_contracts))
        batch = all_contracts[start:end]

        filepath = os.path.join(analysis_dir, f"analysis_{file_idx+1:03d}.csv")
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["contract_id", "competitor_threat_level", "primary_competitor", "switching_cost_estimate"])
            for contract_id, platform_name in batch:
                threat = random.randint(1, 10)
                competitor = random.choice(competitors)
                switching_cost = round(random.uniform(5000, 300000), 2)
                writer.writerow([contract_id, threat, competitor, switching_cost])


def generate_negotiation_briefs(conn, workspace, num_files):
    """Generate negotiation brief markdown files with negotiation_difficulty per contract."""
    brief_dir = os.path.join(workspace, "negotiation_briefs")
    os.makedirs(brief_dir, exist_ok=True)

    cursor = conn.cursor()
    cursor.execute("SELECT contract_id FROM contracts ORDER BY contract_id")
    all_contracts = [r[0] for r in cursor.fetchall()]

    batch_size = math.ceil(len(all_contracts) / num_files)
    for file_idx in range(num_files):
        start = file_idx * batch_size
        end = min(start + batch_size, len(all_contracts))
        batch = all_contracts[start:end]

        lines = []
        for contract_id in batch:
            difficulty = random.randint(1, 10)
            key_concern = random.choice([
                "price sensitivity due to budget cuts",
                "desire for expanded feature set",
                "concerns about platform reliability",
                "competitive offers from alternative vendors",
                "internal reorganization affecting decision-makers",
                "compliance requirements driving urgency",
                "multi-year commitment hesitancy",
                "integration complexity with existing stack",
            ])
            approach = random.choice([
                "Offer multi-year discount in exchange for commitment",
                "Provide additional training and onboarding support",
                "Propose phased feature rollout with milestone reviews",
                "Arrange executive-level relationship building meeting",
                "Present ROI analysis with customized benchmarks",
                "Bundle complementary services at reduced rate",
            ])
            lines.append(f"## {contract_id}\n")
            lines.append(f"**Negotiation Difficulty:** {difficulty}\n")
            lines.append(f"**Key Concern:** {key_concern}\n")
            lines.append(f"**Recommended Approach:** {approach}\n")
            lines.append(f"**Context:** {fake.paragraph(nb_sentences=3)}\n")
            lines.append("")

        filepath = os.path.join(brief_dir, f"brief_{file_idx+1:03d}.md")
        with open(filepath, "w") as f:
            f.write("\n".join(lines))


def generate_workspace(conn, workspace, num_files):
    """Generate all workspace files."""
    os.makedirs(workspace, exist_ok=True)

    # Fixed config files
    generate_config_files(workspace)

    # Scalable data files
    n_dossiers = num_files * 3 // 8
    n_analyses = num_files * 3 // 8
    n_briefs = num_files - n_dossiers - n_analyses

    # Ensure at least 1 file per type
    if n_dossiers < 1:
        n_dossiers = 1
    if n_analyses < 1:
        n_analyses = 1
    if n_briefs < 1:
        n_briefs = 1
    # Re-adjust to total
    total = n_dossiers + n_analyses + n_briefs
    if total > num_files:
        n_briefs = num_files - n_dossiers - n_analyses
    elif total < num_files:
        n_briefs += num_files - total

    generate_client_dossiers(conn, workspace, n_dossiers)
    generate_competitive_analysis(conn, workspace, n_analyses)
    generate_negotiation_briefs(conn, workspace, n_briefs)


def main():
    parser = argparse.ArgumentParser(description="Generate data for contract renewal forecast task.")
    parser.add_argument("--db_path", required=True, help="Path to SQLite database")
    parser.add_argument("--workspace", required=True, help="Path to workspace directory")
    args = parser.parse_args()

    # Reset seeds before generation for reproducibility
    random.seed(SEED)
    np.random.seed(SEED)
    Faker.seed(SEED)
    global fake
    fake = Faker()
    Faker.seed(SEED)

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n = SCALE["rows_per_table"]

    # Generate data
    client_rows = generate_clients(conn, n)
    contracts = generate_contracts(conn, n, client_rows)
    generate_usage_metrics(conn, contracts)
    generate_stakeholder_feedback(conn, n, client_rows)
    generate_negotiation_history(conn, n, contracts)

    # Generate workspace
    generate_workspace(conn, args.workspace, SCALE["num_workspace_files"])

    conn.close()
    print(f"Database created at {args.db_path} with {n} rows per main table.")
    print(f"Workspace created at {args.workspace} with {SCALE['num_workspace_files']} scalable data files + config files.")


if __name__ == "__main__":
    main()
