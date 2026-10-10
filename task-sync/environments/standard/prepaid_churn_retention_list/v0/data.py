#!/usr/bin/env python3
"""Data generation for prepaid subscriber retention task."""

import argparse
import csv
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 60,
    "num_workspace_files": 8,
}

# ---- Seeds ----
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ---- Constants ----
REFERENCE_DATE = datetime(2026, 4, 1)
REGIONS = ["North", "South", "East", "West", "Central"]
PLAN_TYPES = ["basic", "standard", "premium"]
COMPETITORS = ["TeleMax", "NetWave", "QuickConnect", "BudgetMobile"]
TOPUP_CHANNELS = ["app", "ussd", "retailer", "bank_transfer"]
INTERACTION_CHANNELS = ["phone", "chat", "email", "store_visit"]
INTERACTION_CATEGORIES = [
    "billing_complaint", "network_issue", "plan_inquiry",
    "port_out_request", "general_feedback",
]
CALL_TYPES = ["voice_outgoing", "voice_incoming", "sms_outgoing", "sms_incoming"]

# Monthly voice-call counts per profile (index 0 = oldest month, 5 = newest)
CALL_PATTERNS = {
    "declining": [12, 11, 10, 7, 5, 3],
    "stable":    [8,  8,  8,  8, 8, 8],
    "growing":   [4,  5,  6,  8, 10, 12],
}

# Monthly top-up patterns: (count, avg_amount)
TOPUP_PATTERNS = {
    "declining": [(3, 15), (3, 14), (2, 12), (2, 10), (1, 8), (1, 5)],
    "stable":    [(2, 12), (2, 12), (2, 12), (2, 12), (2, 12), (2, 12)],
    "growing":   [(1, 8),  (1, 9),  (2, 10), (2, 12), (3, 14), (3, 16)],
}


def _get_month_range(months_ago):
    """Return (start, end) datetimes for a calendar month *months_ago* before REFERENCE_DATE."""
    m = REFERENCE_DATE.month - months_ago
    y = REFERENCE_DATE.year
    while m <= 0:
        m += 12
        y -= 1
    start = datetime(y, m, 1)
    if m == 12:
        end = datetime(y + 1, 1, 1) - timedelta(seconds=1)
    else:
        end = datetime(y, m + 1, 1) - timedelta(seconds=1)
    return start, end


# ------------------------------------------------------------------ #
#  Database helpers                                                    #
# ------------------------------------------------------------------ #

def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS subscribers (
        subscriber_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        region TEXT NOT NULL,
        plan_type TEXT NOT NULL,
        registration_date TEXT NOT NULL,
        account_status TEXT NOT NULL,
        monthly_arpu REAL NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS call_detail_records (
        cdr_id INTEGER PRIMARY KEY AUTOINCREMENT,
        subscriber_id TEXT NOT NULL,
        call_date TEXT NOT NULL,
        call_type TEXT NOT NULL,
        duration_seconds INTEGER NOT NULL,
        destination TEXT,
        FOREIGN KEY (subscriber_id) REFERENCES subscribers(subscriber_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS topup_transactions (
        topup_id INTEGER PRIMARY KEY AUTOINCREMENT,
        subscriber_id TEXT NOT NULL,
        topup_date TEXT NOT NULL,
        amount REAL NOT NULL,
        channel TEXT NOT NULL,
        balance_after REAL NOT NULL,
        FOREIGN KEY (subscriber_id) REFERENCES subscribers(subscriber_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS service_interactions (
        interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        subscriber_id TEXT NOT NULL,
        interaction_date TEXT NOT NULL,
        channel TEXT NOT NULL,
        category TEXT NOT NULL,
        sentiment_score REAL NOT NULL,
        resolution TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        notes TEXT,
        FOREIGN KEY (subscriber_id) REFERENCES subscribers(subscriber_id)
    )""")
    conn.commit()


# ------------------------------------------------------------------ #
#  Data generators                                                     #
# ------------------------------------------------------------------ #

def generate_subscribers(conn, n):
    """Insert *n* subscribers. Returns list of profile tuples."""
    risk_profiles = []
    rows = []
    for i in range(n):
        sub_id = f"SUB_{i+1:04d}"
        name = fake.name()
        phone = fake.phone_number()
        region = REGIONS[i % len(REGIONS)]
        plan_type = PLAN_TYPES[i % len(PLAN_TYPES)]

        r = random.random()
        if r < 0.30:
            profile = "declining"
            status = random.choices(
                ["active", "suspended", "inactive"], weights=[0.60, 0.30, 0.10]
            )[0]
            arpu = round(random.uniform(5, 25), 2)
        elif r < 0.80:
            profile = "stable"
            status = random.choices(
                ["active", "suspended", "inactive"], weights=[0.85, 0.10, 0.05]
            )[0]
            arpu = round(random.uniform(15, 50), 2)
        else:
            profile = "growing"
            status = "active"
            arpu = round(random.uniform(20, 60), 2)

        reg_days = random.randint(60, 730)
        reg_date = (REFERENCE_DATE - timedelta(days=reg_days)).strftime("%Y-%m-%d")

        rows.append((sub_id, name, phone, region, plan_type, reg_date, status, arpu))
        risk_profiles.append({
            "subscriber_id": sub_id,
            "profile": profile,
            "region": region,
            "plan_type": plan_type,
            "status": status,
            "arpu": arpu,
            "name": name,
            "phone": phone,
            "reg_date": reg_date,
        })

    conn.executemany("INSERT INTO subscribers VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return risk_profiles


def generate_cdrs(conn, risk_profiles):
    cdrs = []
    for rp in risk_profiles:
        pattern = CALL_PATTERNS[rp["profile"]]
        for month_idx in range(6):
            months_ago = 6 - month_idx
            start, end = _get_month_range(months_ago)
            n_calls = max(1, pattern[month_idx] + random.randint(-2, 2))
            for _ in range(n_calls):
                delta_secs = random.randint(0, int((end - start).total_seconds()))
                call_dt = start + timedelta(seconds=delta_secs)
                call_type = random.choice(CALL_TYPES)
                duration = random.randint(15, 600) if call_type.startswith("voice") else 0
                dest = fake.phone_number() if "outgoing" in call_type else ""
                cdrs.append((
                    rp["subscriber_id"],
                    call_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    call_type,
                    duration,
                    dest,
                ))
    conn.executemany(
        "INSERT INTO call_detail_records "
        "(subscriber_id, call_date, call_type, duration_seconds, destination) "
        "VALUES (?,?,?,?,?)",
        cdrs,
    )
    conn.commit()


def generate_topups(conn, risk_profiles):
    topups = []
    for rp in risk_profiles:
        pattern = TOPUP_PATTERNS[rp["profile"]]
        balance = round(random.uniform(5, 30), 2)
        for month_idx in range(6):
            months_ago = 6 - month_idx
            start, end = _get_month_range(months_ago)
            count, avg_amt = pattern[month_idx]
            count = max(0, count + random.randint(-1, 1))
            for _ in range(count):
                delta_days = random.randint(0, (end - start).days)
                topup_date = (start + timedelta(days=delta_days)).strftime("%Y-%m-%d")
                amount = round(max(1.0, avg_amt + random.uniform(-3, 3)), 2)
                balance = round(balance + amount, 2)
                channel = random.choice(TOPUP_CHANNELS)
                topups.append((rp["subscriber_id"], topup_date, amount, channel, balance))
    conn.executemany(
        "INSERT INTO topup_transactions "
        "(subscriber_id, topup_date, amount, channel, balance_after) "
        "VALUES (?,?,?,?,?)",
        topups,
    )
    conn.commit()


def generate_interactions(conn, risk_profiles):
    interactions = []
    for rp in risk_profiles:
        profile = rp["profile"]
        if profile == "declining":
            n_int = random.randint(3, 6)
            sent_lo, sent_hi = -0.9, 0.1
            cat_w = [0.30, 0.25, 0.10, 0.20, 0.15]
            esc_prob = 0.35
        elif profile == "stable":
            n_int = random.randint(1, 3)
            sent_lo, sent_hi = -0.3, 0.7
            cat_w = [0.15, 0.20, 0.25, 0.05, 0.35]
            esc_prob = 0.10
        else:
            n_int = random.randint(0, 2)
            sent_lo, sent_hi = 0.0, 0.9
            cat_w = [0.05, 0.10, 0.30, 0.00, 0.55]
            esc_prob = 0.05

        for _ in range(n_int):
            days_ago = random.randint(1, 180)
            int_date = (REFERENCE_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            channel = random.choice(INTERACTION_CHANNELS)
            category = random.choices(INTERACTION_CATEGORIES, weights=cat_w)[0]
            sentiment = round(random.uniform(sent_lo, sent_hi), 2)
            resolution = (
                "escalated"
                if random.random() < esc_prob
                else random.choice(["resolved", "pending"])
            )
            agent_id = f"AGT_{random.randint(1, 20):03d}"

            if category == "port_out_request":
                comp = random.choice(COMPETITORS)
                reason = random.choice(
                    ["better price", "more data", "poor network", "friend recommendation"]
                )
                notes = f"Customer inquired about porting to {comp}. Reason: {reason}"
            elif category == "billing_complaint":
                notes = random.choice([
                    "Disputed charge on last bill, wants explanation",
                    "Unhappy about rate increase, considering alternatives",
                    "Unexpected deduction from balance",
                    "Charged for service not used",
                ])
            elif category == "network_issue":
                notes = random.choice([
                    "Frequent call drops in residential area",
                    "Very slow data speed in downtown area",
                    "No signal inside office building",
                    "Call quality deteriorating over past month",
                ])
            else:
                notes = fake.sentence()

            interactions.append((
                rp["subscriber_id"], int_date, channel, category,
                sentiment, resolution, agent_id, notes,
            ))

    conn.executemany(
        "INSERT INTO service_interactions "
        "(subscriber_id, interaction_date, channel, category, "
        "sentiment_score, resolution, agent_id, notes) "
        "VALUES (?,?,?,?,?,?,?,?)",
        interactions,
    )
    conn.commit()


# ------------------------------------------------------------------ #
#  Workspace file generators                                           #
# ------------------------------------------------------------------ #

def create_fixed_workspace_files(workspace):
    """Create policy/config files that do not scale with data size."""

    # 1. Scoring configuration (YAML)
    config = {
        "analysis_date": "2026-04-01",
        "periods": {
            "recent_months": 3,
            "historical_months": 3,
        },
        "weights": {
            "usage_decline": 0.30,
            "topup_decline": 0.25,
            "sentiment": 0.25,
            "churn_intent": 0.20,
        },
        "usage_decline_thresholds": {
            "severe": -50,
            "moderate": -25,
            "mild": -10,
        },
        "topup_decline_thresholds": {
            "severe": -60,
            "moderate": -30,
            "mild": -15,
        },
        "sentiment_thresholds": {
            "very_negative": -0.5,
            "negative": -0.2,
            "neutral": 0.1,
        },
        "escalation_penalty": 0.15,
        "competitor_mention_bonus": 0.2,
        "port_out_bonus": 0.15,
        "campaign_match_bonus": 0.1,
    }
    with open(os.path.join(workspace, "retention_scoring_config.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # 2. Risk classification rules (JSON)
    rules = {
        "risk_tiers": {
            "critical": {"min_score": 0.75},
            "high":     {"min_score": 0.50},
            "medium":   {"min_score": 0.30},
            "low":      {"min_score": 0.0},
        },
        "call_list_tiers": ["critical", "high"],
        "eligible_statuses": ["active", "suspended"],
        "min_tenure_days": 30,
        "sort_order": ["risk_score_desc", "monthly_arpu_desc"],
    }
    with open(os.path.join(workspace, "risk_classification_rules.json"), "w") as f:
        json.dump(rules, f, indent=2)

    # 3. Offer matrix (CSV)
    offer_rows = [
        ("usage_decline",     "basic",    "bonus_500mb_data"),
        ("usage_decline",     "standard", "bonus_1gb_data_100min"),
        ("usage_decline",     "premium",  "bonus_2gb_data_unlimited_weekend"),
        ("topup_decline",     "basic",    "20pct_cashback_next_topup"),
        ("topup_decline",     "standard", "25pct_cashback_next_topup"),
        ("topup_decline",     "premium",  "30pct_cashback_plus_rollover"),
        ("negative_sentiment","basic",    "priority_support_5_credit"),
        ("negative_sentiment","standard", "priority_support_10_credit"),
        ("negative_sentiment","premium",  "dedicated_manager_15_credit"),
        ("churn_intent",      "basic",    "price_match_3month_lock"),
        ("churn_intent",      "standard", "price_match_bonus_data_3month"),
        ("churn_intent",      "premium",  "loyalty_bonus_premium_retention"),
    ]
    with open(os.path.join(workspace, "offer_matrix.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["primary_risk_factor", "plan_type", "recommended_offer"])
        writer.writerows(offer_rows)

    # 4. Analysis guidelines (Markdown)
    guidelines = """\
## Analysis Guidelines

The analysis reference date is specified in the scoring configuration file. All time-based calculations use this date as the anchor.

When computing usage decline, compare the total number of voice calls (both incoming and outgoing) during the recent period against the historical period. The recent period covers the three calendar months immediately preceding the analysis date, and the historical period covers the three months before the recent period. Express the change as a percentage: (recent_total - historical_total) / historical_total * 100. If a subscriber has zero calls in the historical period, treat their usage decline percentage as zero.

Top-up decline follows the same logic but uses total top-up amounts instead of call counts.

For the usage and top-up decline component scores, check the threshold brackets defined in the scoring configuration from most severe to least severe. If the decline percentage is less than or equal to the severe threshold, the component score is 1.0. If it is less than or equal to the moderate threshold, the score is 0.7. If less than or equal to the mild threshold, the score is 0.4. Otherwise the score is 0.0. The same bracket-to-score mapping applies to both usage and top-up decline.

Sentiment scoring uses the average sentiment score across all service interactions for the subscriber. Apply the same bracket logic using the sentiment thresholds: if average sentiment is at most the very_negative threshold, score is 1.0; at most the negative threshold, 0.7; at most the neutral threshold, 0.4; otherwise 0.0. When at least one interaction has a resolution of "escalated", add the escalation penalty to the sentiment component score, capping at 1.0. If a subscriber has no interactions, the sentiment component score is zero.

Churn intent combines survey data, competitor campaign exposure, and interaction history. For subscribers with survey responses, compute the average likelihood_to_switch and divide by ten. If any survey response names a competitor, add the competitor mention bonus. If the subscriber has any interaction with category "port_out_request", add the port-out bonus. If any competitor campaign in the intelligence files targets both the subscriber's region and plan type, add the campaign match bonus. Cap the final churn intent score at 1.0. Subscribers with no survey data, no port-out requests, and no matching campaigns receive zero.

The primary risk factor is whichever component has the highest raw score (before weighting). Ties are broken in this order: usage_decline, churn_intent, negative_sentiment, topup_decline.

Risk scores and churn intent scores should be rounded to four decimal places in the output. Usage and top-up decline percentages and average sentiment should be rounded to two decimal places.
"""
    with open(os.path.join(workspace, "analysis_guidelines.md"), "w") as f:
        f.write(guidelines)


def create_scalable_workspace_files(workspace, risk_profiles, n_files):
    """Create data files that grow in number with scale."""
    n_feedback = n_files // 2
    n_competitor = n_files - n_feedback

    # ---- Feedback survey files (.json) ----
    all_surveys = []
    for rp in risk_profiles:
        profile = rp["profile"]
        if profile == "declining":
            if random.random() >= 0.70:
                continue
            likelihood = random.randint(6, 9)
            competitor = random.choice(COMPETITORS) if random.random() < 0.60 else None
        elif profile == "stable":
            if random.random() >= 0.40:
                continue
            likelihood = random.randint(2, 5)
            competitor = random.choice(COMPETITORS) if random.random() < 0.10 else None
        else:
            if random.random() >= 0.20:
                continue
            likelihood = random.randint(1, 3)
            competitor = None

        days_ago = random.randint(1, 90)
        survey_date = (REFERENCE_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")

        texts_by_profile = {
            "declining": [
                "Service has been getting worse. Calls drop frequently.",
                "The rates keep going up but quality stays the same.",
                "My friend switched to {comp} and is very happy.",
                "I am seriously considering switching providers.",
                "Not getting value for money anymore.",
            ],
            "stable": [
                "Service is okay but nothing special.",
                "Would like better data plans.",
                "Generally satisfied but open to better offers.",
            ],
            "growing": [
                "Happy with current service.",
                "Good coverage in my area.",
            ],
        }
        text = random.choice(texts_by_profile[profile])
        if competitor and "{comp}" in text:
            text = text.replace("{comp}", competitor)
        elif competitor:
            text += f" Have been looking at {competitor} offers."

        all_surveys.append({
            "subscriber_id": rp["subscriber_id"],
            "survey_date": survey_date,
            "likelihood_to_switch": likelihood,
            "competitor_mentioned": competitor,
            "feedback_text": text,
        })

    random.shuffle(all_surveys)
    per_file = max(1, len(all_surveys) // n_feedback)
    for i in range(n_feedback):
        start = i * per_file
        batch = all_surveys[start:] if i == n_feedback - 1 else all_surveys[start:start + per_file]
        fname = f"feedback_survey_batch_{i+1:02d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump({"survey_responses": batch}, f, indent=2)

    # ---- Competitor campaign files (.yaml) ----
    offer_descriptions = {
        "data_bonus":    ["Double data on all recharges", "Extra 2GB free with every top-up",
                          "5GB bonus data for new activations", "Unlimited data weekends"],
        "call_discount": ["50% off all outgoing calls", "Free calls to same network",
                          "Discounted international calls", "Free 100 minutes daily"],
        "bundle_deal":   ["All-in-one bundle: calls + data + SMS", "Family plan with shared data",
                          "Student special bundle", "Weekend unlimited bundle"],
        "cashback":      ["30% cashback on first recharge", "Loyalty cashback program",
                          "Refer-a-friend cashback bonus", "Monthly cashback rewards"],
    }

    campaigns = []
    for comp in COMPETITORS:
        for region in REGIONS:
            if random.random() < 0.5:
                offer_type = random.choice(list(offer_descriptions.keys()))
                campaigns.append({
                    "campaign_id": f"CAMP_{len(campaigns)+1:03d}",
                    "competitor": comp,
                    "target_region": region,
                    "offer_type": offer_type,
                    "description": random.choice(offer_descriptions[offer_type]),
                    "discount_pct": round(random.uniform(10, 40), 1),
                    "bonus_data_gb": round(random.uniform(1, 10), 1),
                    "target_plans": random.sample(PLAN_TYPES, k=random.randint(1, 3)),
                    "start_date": (REFERENCE_DATE - timedelta(days=random.randint(10, 60))).strftime("%Y-%m-%d"),
                    "end_date":   (REFERENCE_DATE + timedelta(days=random.randint(10, 60))).strftime("%Y-%m-%d"),
                    "port_in_bonus": round(random.uniform(20, 100), 0),
                })

    # If we don't have enough campaigns, pad with extra random ones
    while len(campaigns) < n_competitor:
        comp = random.choice(COMPETITORS)
        region = random.choice(REGIONS)
        offer_type = random.choice(list(offer_descriptions.keys()))
        campaigns.append({
            "campaign_id": f"CAMP_{len(campaigns)+1:03d}",
            "competitor": comp,
            "target_region": region,
            "offer_type": offer_type,
            "description": random.choice(offer_descriptions[offer_type]),
            "discount_pct": round(random.uniform(10, 40), 1),
            "bonus_data_gb": round(random.uniform(1, 10), 1),
            "target_plans": random.sample(PLAN_TYPES, k=random.randint(1, 3)),
            "start_date": (REFERENCE_DATE - timedelta(days=random.randint(10, 60))).strftime("%Y-%m-%d"),
            "end_date":   (REFERENCE_DATE + timedelta(days=random.randint(10, 60))).strftime("%Y-%m-%d"),
            "port_in_bonus": round(random.uniform(20, 100), 0),
        })

    random.shuffle(campaigns)
    per_file = max(1, len(campaigns) // n_competitor)
    for i in range(n_competitor):
        start = i * per_file
        batch = campaigns[start:] if i == n_competitor - 1 else campaigns[start:start + per_file]
        fname = f"competitor_campaign_{i+1:02d}.yaml"
        with open(os.path.join(workspace, fname), "w") as f:
            yaml.dump({"campaigns": batch}, f, default_flow_style=False, sort_keys=False)


# ------------------------------------------------------------------ #
#  Main                                                                #
# ------------------------------------------------------------------ #

def main():
    parser = argparse.ArgumentParser(description="Generate data for prepaid retention task")
    parser.add_argument("--db_path", required=True, help="Path to SQLite database")
    parser.add_argument("--workspace", required=True, help="Path to workspace directory")
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    risk_profiles = generate_subscribers(conn, SCALE["rows_per_table"])
    generate_cdrs(conn, risk_profiles)
    generate_topups(conn, risk_profiles)
    generate_interactions(conn, risk_profiles)
    conn.close()

    create_fixed_workspace_files(args.workspace)
    create_scalable_workspace_files(args.workspace, risk_profiles, SCALE["num_workspace_files"])
    print(f"Data generation complete: {SCALE['rows_per_table']} subscribers, "
          f"{SCALE['num_workspace_files']} scalable + 4 fixed workspace files.")


if __name__ == "__main__":
    main()
