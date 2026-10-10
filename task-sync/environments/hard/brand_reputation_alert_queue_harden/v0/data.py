#!/usr/bin/env python3
"""Brand reputation monitoring – data generation script."""

import argparse
import sqlite3
import os
import json
import csv
import random
import numpy as np
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 50,       # v0 base; v1=2x, v2=4x, v3=8x
    "num_workspace_files": 8,   # v0 base; v1=+N, v2=+2N, v3=+3N (N=base)
}

# ---------------------------------------------------------------------------
# Constants / templates
# ---------------------------------------------------------------------------
INDUSTRIES = [
    "Technology", "Finance", "Healthcare", "Retail", "Energy",
    "Automotive", "Telecommunications", "Food & Beverage",
    "Pharmaceutical", "Media & Entertainment",
]
REGIONS = ["North America", "Europe", "Asia Pacific", "Latin America", "Middle East"]
PLATFORMS = ["twitter", "facebook", "reddit"]
TIERS = ["platinum", "gold", "silver", "bronze"]

TICKET_CATEGORIES = ["billing", "product", "service", "account", "privacy", "technical"]
TICKET_STATUSES = ["open", "in_progress", "resolved", "escalated"]
CUSTOMER_TIERS = ["enterprise", "business", "individual"]

COMM_TYPES = ["press_release", "public_statement", "earnings_call",
              "investor_briefing", "internal_memo"]
COMM_ISSUES = [
    "data privacy concerns", "product safety allegations",
    "regulatory compliance gaps", "financial reporting questions",
    "workplace culture issues",
]

NEWS_SOURCES = [
    "Reuters", "Bloomberg", "CNBC", "Financial Times",
    "Wall Street Journal", "TechCrunch", "The Guardian",
    "Associated Press", "BBC News", "Forbes",
]
NEWS_CATEGORIES = ["product", "legal", "financial", "executive", "regulatory", "partnership"]

# --- headline templates ---
NEG_HEADLINE_TEMPLATES = [
    "{brand} faces lawsuit over data handling practices",
    "{brand} under investigation for financial irregularities",
    "Sources report {brand} breach affecting customer accounts",
    "{brand} announces massive product recall amid safety concerns",
    "{brand} scandal deepens as whistleblower comes forward",
    "Regulatory penalty imposed on {brand} for compliance violation",
    "{brand} confirms significant workforce layoff across divisions",
    "Allegations of fraud surface against {brand} leadership",
]
CRIT_HEADLINE_TEMPLATES = [
    "{brand} confirms major data breach exposing millions of records",
    "Class action lawsuit filed against {brand} over consumer harm",
    "{brand} teeters near bankruptcy as debts mount",
    "Fatal incident linked to {brand} product raises alarm",
    "Criminal investigation launched into {brand} executive conduct",
]
POS_HEADLINE_TEMPLATES = [
    "{brand} reports record revenue and strong growth trajectory",
    "{brand} earns prestigious innovation award at global summit",
    "{brand} announces landmark partnership with industry leader",
    "{brand} expansion into new markets signals confidence",
    "{brand} breakthrough technology receives widespread acclaim",
]
NEUTRAL_HEADLINE_TEMPLATES = [
    "{brand} to present at annual industry conference next month",
    "{brand} releases quarterly earnings in line with expectations",
    "{brand} appoints new independent board member",
    "{brand} opens regional office to support operations",
    "{brand} updates corporate governance policies",
]

# --- ticket body templates ---
NEG_TICKET_SUBJECTS = [
    "Frustrated with service quality",
    "Product defective and no response",
    "Billing complaint - overcharged",
    "Unacceptable wait times",
    "Data privacy violation concern",
]
NEG_TICKET_BODIES = [
    "I am extremely frustrated with the quality of service. Despite multiple attempts to get help, the problem persists and nobody seems to care about resolving this complaint.",
    "The product I received is completely defective. I have filed multiple complaints but the issue remains unresolved. This is a serious problem that needs immediate attention.",
    "I was overcharged on my last three billing cycles. This feels like fraud. I demand an immediate investigation and refund for the penalty charges.",
    "The wait times are unacceptable. I have been trying to reach support for days. The decline in your service quality is alarming.",
    "I believe my personal data was involved in a breach. This violation of trust is deeply concerning. I need answers about this data privacy scandal immediately.",
]
POS_TICKET_SUBJECTS = [
    "Great experience with support",
    "Impressed with product quality",
    "Thank you for quick resolution",
]
POS_TICKET_BODIES = [
    "Just wanted to say thank you for the outstanding support. The team was helpful and professional throughout the process. Great growth in service quality.",
    "I am really impressed with the product innovation. The new features represent a real breakthrough in usability. Keep up the great work!",
    "Thank you for resolving my issue so quickly. The partnership between your support team and engineering was evident. Award-worthy service!",
]
NEUTRAL_TICKET_SUBJECTS = [
    "Question about account settings",
    "Request for product information",
    "General inquiry about services",
]
NEUTRAL_TICKET_BODIES = [
    "I have a question about my account settings. Could someone provide guidance on how to update my preferences? Thank you in advance.",
    "I would like to learn more about your product lineup. Could you send me the latest catalog or direct me to the relevant resources?",
    "I am interested in your enterprise services. Could someone from the sales team reach out to discuss options?",
]

# --- exec-comm summary templates ---
CRISIS_COMM_TEMPLATES = [
    "Urgent communication addressing {issue}. {spokesperson} emphasized the need for immediate response and damage control measures across all departments.",
    "Emergency communication regarding {issue}. {spokesperson} called for crisis management protocols to be activated immediately.",
    "Critical update on {issue}. {spokesperson} acknowledged the urgent nature of the situation and committed to emergency remediation.",
]
NORMAL_COMM_TEMPLATES = [
    "Quarterly business update highlighting strategic initiatives and market positioning. {spokesperson} outlined growth plans for the coming quarter.",
    "Annual report presentation covering financial performance and future outlook. {spokesperson} discussed innovation investments.",
    "Industry event keynote addressing technology trends and market opportunities. {spokesperson} shared the company partnership strategy.",
    "Internal communication about organizational changes and team expansion. {spokesperson} welcomed new leadership appointments.",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pick(rng, lst):
    return lst[int(rng.randint(0, len(lst)))]


def _generate_brands(num_brands, rng, fake):
    brands = []
    for i in range(1, num_brands + 1):
        name = fake.company().replace(",", "")
        industry = INDUSTRIES[i % len(INDUSTRIES)]
        region = REGIONS[i % len(REGIONS)]
        ticker = fake.lexify("????").upper()
        emp_count = int(rng.randint(200, 50000))
        tier = TIERS[i % len(TIERS)]
        is_troubled = bool(rng.random() < 0.35)
        brands.append(dict(
            id=i, name=name, industry=industry, region=region,
            stock_ticker=ticker, employee_count=emp_count,
            tier=tier, is_troubled=is_troubled,
        ))
    return brands


def _generate_baselines(brands, rng):
    baselines = {}
    for b in brands:
        mean_val = float(rng.randint(200, 2000))
        std_val = round(mean_val * (0.10 + rng.random() * 0.10), 2)
        baselines[b["id"]] = {"mean": mean_val, "std": std_val}
    return baselines


# ---------------------------------------------------------------------------
# Database population
# ---------------------------------------------------------------------------

def _create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS brands (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, industry TEXT NOT NULL,
        region TEXT NOT NULL, stock_ticker TEXT, employee_count INTEGER
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS news_headlines (
        id INTEGER PRIMARY KEY AUTOINCREMENT, brand_id INTEGER NOT NULL,
        headline TEXT NOT NULL, source TEXT NOT NULL,
        published_date TEXT NOT NULL, category TEXT NOT NULL,
        FOREIGN KEY (brand_id) REFERENCES brands(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS social_media_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT, brand_id INTEGER NOT NULL,
        date TEXT NOT NULL, platform TEXT NOT NULL,
        mention_count INTEGER NOT NULL, engagement_score REAL NOT NULL,
        FOREIGN KEY (brand_id) REFERENCES brands(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS support_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, brand_id INTEGER NOT NULL,
        subject TEXT NOT NULL, body TEXT NOT NULL, category TEXT NOT NULL,
        created_date TEXT NOT NULL, status TEXT NOT NULL, customer_tier TEXT NOT NULL,
        FOREIGN KEY (brand_id) REFERENCES brands(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS executive_communications (
        id INTEGER PRIMARY KEY AUTOINCREMENT, brand_id INTEGER NOT NULL,
        comm_type TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
        date TEXT NOT NULL, spokesperson TEXT NOT NULL,
        FOREIGN KEY (brand_id) REFERENCES brands(id)
    )""")
    conn.commit()


def _insert_brands(conn, brands):
    c = conn.cursor()
    for b in brands:
        c.execute("INSERT INTO brands VALUES (?,?,?,?,?,?)",
                  (b["id"], b["name"], b["industry"], b["region"],
                   b["stock_ticker"], b["employee_count"]))
    conn.commit()


def _insert_headlines(conn, brands, rng):
    c = conn.cursor()
    dates = [f"2026-04-{19+d:02d}" for d in range(7)]
    for b in brands:
        if b["is_troubled"]:
            num_h = max(3, int(rng.poisson(5)))
        else:
            num_h = max(1, int(rng.poisson(2)))
        for _ in range(num_h):
            r = rng.random()
            if b["is_troubled"]:
                if r < 0.15:
                    tpl = _pick(rng, CRIT_HEADLINE_TEMPLATES)
                elif r < 0.65:
                    tpl = _pick(rng, NEG_HEADLINE_TEMPLATES)
                elif r < 0.85:
                    tpl = _pick(rng, NEUTRAL_HEADLINE_TEMPLATES)
                else:
                    tpl = _pick(rng, POS_HEADLINE_TEMPLATES)
            else:
                if r < 0.10:
                    tpl = _pick(rng, NEG_HEADLINE_TEMPLATES)
                elif r < 0.40:
                    tpl = _pick(rng, POS_HEADLINE_TEMPLATES)
                else:
                    tpl = _pick(rng, NEUTRAL_HEADLINE_TEMPLATES)
            headline = tpl.format(brand=b["name"])
            source = _pick(rng, NEWS_SOURCES)
            pub_date = _pick(rng, dates)
            cat = _pick(rng, NEWS_CATEGORIES)
            c.execute(
                "INSERT INTO news_headlines (brand_id,headline,source,published_date,category) VALUES (?,?,?,?,?)",
                (b["id"], headline, source, pub_date, cat),
            )
    conn.commit()


def _insert_social_media(conn, brands, baselines, rng):
    c = conn.cursor()
    dates = [f"2026-04-{19+d:02d}" for d in range(7)]
    platform_shares = {"twitter": 0.50, "facebook": 0.30, "reddit": 0.20}
    for b in brands:
        bl = baselines[b["id"]]
        for date in dates:
            if b["is_troubled"]:
                daily_total = bl["mean"] * (2.0 + rng.random() * 1.5)
            else:
                daily_total = bl["mean"] * (0.85 + rng.random() * 0.30)
            for plat in PLATFORMS:
                share = platform_shares[plat]
                mc = max(1, int(daily_total * share * (0.90 + rng.random() * 0.20)))
                es = round(mc * (0.05 + rng.random() * 0.15), 2)
                c.execute(
                    "INSERT INTO social_media_metrics (brand_id,date,platform,mention_count,engagement_score) VALUES (?,?,?,?,?)",
                    (b["id"], date, plat, mc, es),
                )
    conn.commit()


def _insert_tickets(conn, brands, rng):
    c = conn.cursor()
    dates = [f"2026-04-{19+d:02d}" for d in range(7)]
    for b in brands:
        num_t = max(2, int(rng.poisson(3))) if b["is_troubled"] else max(1, int(rng.poisson(2)))
        for _ in range(num_t):
            r = rng.random()
            if b["is_troubled"]:
                if r < 0.55:
                    subj = _pick(rng, NEG_TICKET_SUBJECTS)
                    body = _pick(rng, NEG_TICKET_BODIES)
                elif r < 0.75:
                    subj = _pick(rng, NEUTRAL_TICKET_SUBJECTS)
                    body = _pick(rng, NEUTRAL_TICKET_BODIES)
                else:
                    subj = _pick(rng, POS_TICKET_SUBJECTS)
                    body = _pick(rng, POS_TICKET_BODIES)
            else:
                if r < 0.15:
                    subj = _pick(rng, NEG_TICKET_SUBJECTS)
                    body = _pick(rng, NEG_TICKET_BODIES)
                elif r < 0.55:
                    subj = _pick(rng, NEUTRAL_TICKET_SUBJECTS)
                    body = _pick(rng, NEUTRAL_TICKET_BODIES)
                else:
                    subj = _pick(rng, POS_TICKET_SUBJECTS)
                    body = _pick(rng, POS_TICKET_BODIES)
            cat = _pick(rng, TICKET_CATEGORIES)
            created = _pick(rng, dates)
            status = _pick(rng, TICKET_STATUSES)
            ct = _pick(rng, CUSTOMER_TIERS)
            c.execute(
                "INSERT INTO support_tickets (brand_id,subject,body,category,created_date,status,customer_tier) VALUES (?,?,?,?,?,?,?)",
                (b["id"], subj, body, cat, created, status, ct),
            )
    conn.commit()


def _insert_exec_comms(conn, brands, rng, fake):
    """Returns exec_names dict {brand_id: [name, ...]} for watchlist generation."""
    c = conn.cursor()
    dates = [f"2026-04-{19+d:02d}" for d in range(7)]
    exec_names = {}
    for b in brands:
        n_execs = int(rng.randint(2, 5))
        execs = [fake.name() for _ in range(n_execs)]
        exec_names[b["id"]] = execs

        num_comms = max(1, int(rng.poisson(1.5)))
        for _ in range(num_comms):
            spokesperson = _pick(rng, execs)
            r = rng.random()
            if b["is_troubled"] and r < 0.45:
                issue = _pick(rng, COMM_ISSUES)
                tpl = _pick(rng, CRISIS_COMM_TEMPLATES)
                summary = tpl.format(issue=issue, spokesperson=spokesperson)
                title = f"Statement on {issue}"
            else:
                tpl = _pick(rng, NORMAL_COMM_TEMPLATES)
                summary = tpl.format(spokesperson=spokesperson)
                title = "Business Update"
            ct = _pick(rng, COMM_TYPES)
            date = _pick(rng, dates)
            c.execute(
                "INSERT INTO executive_communications (brand_id,comm_type,title,summary,date,spokesperson) VALUES (?,?,?,?,?,?)",
                (b["id"], ct, title, summary, date, spokesperson),
            )
    conn.commit()
    return exec_names


# ---------------------------------------------------------------------------
# Workspace generation
# ---------------------------------------------------------------------------

def _generate_workspace(workspace, brands, baselines, exec_names, rng):
    num_files = SCALE["num_workspace_files"]
    files_per_type = max(1, num_files // 4)
    num_brands = len(brands)
    brands_per_file = max(1, num_brands // files_per_type)

    # ---- Fixed config files (not counted in SCALE) ----

    # anomaly_config.yaml
    anomaly_config = {
        "z_score_threshold": 1.5,
        "min_daily_mentions": 10,
        "monitoring_window_days": 7,
        "platforms": list(PLATFORMS),
    }
    with open(os.path.join(workspace, "anomaly_config.yaml"), "w") as f:
        yaml.dump(anomaly_config, f, default_flow_style=False)

    # sentiment_rules.json
    sentiment_rules = {
        "negative_keywords": [
            "lawsuit", "investigation", "breach", "recall", "scandal",
            "penalty", "layoff", "fraud", "decline", "violation",
            "frustrated", "unacceptable", "complaint", "defective", "overcharged",
        ],
        "critical_keywords": [
            "data breach", "class action", "bankruptcy", "fatal", "criminal",
        ],
        "positive_keywords": [
            "growth", "innovation", "award", "partnership", "record revenue",
            "expansion", "breakthrough", "helpful", "professional", "resolved",
        ],
        "crisis_keywords": [
            "urgent", "crisis", "emergency", "damage control", "immediate response",
        ],
    }
    with open(os.path.join(workspace, "sentiment_rules.json"), "w") as f:
        json.dump(sentiment_rules, f, indent=2)

    # priority_matrix.json
    priority_matrix = {
        "weights": {
            "social_anomaly": 0.35,
            "headline_sentiment": 0.25,
            "ticket_sentiment": 0.20,
            "executive_comms": 0.20,
        },
        "signal_scaling": {
            "social_anomaly": 10,
            "headline_sentiment": 100,
            "ticket_sentiment": 100,
            "executive_comms": 100,
        },
        "alert_threshold": 15.0,
        "tier_multipliers": {
            "platinum": 2.0,
            "gold": 1.5,
            "silver": 1.0,
            "bronze": 0.75,
        },
        "severity_override_multipliers": {
            "elevated": 1.5,
            "normal": 1.0,
            "low": 0.5,
        },
        "risk_assessment_multipliers": {
            "high": 2.0,
            "medium": 1.0,
            "low": 0.5,
        },
    }
    with open(os.path.join(workspace, "priority_matrix.json"), "w") as f:
        json.dump(priority_matrix, f, indent=2)

    # alert_methodology.md — authoritative computation spec (fixed, not scaled)
    methodology = """# Brand Reputation Alert Methodology

This document is the authoritative specification for computing the brand
reputation alert queue. Numeric parameters referenced below are defined in
`priority_matrix.json`; the sentiment lexicon lives in `sentiment_rules.json`;
monitoring parameters in `anomaly_config.yaml`. Brand monitoring tiers are
assigned in the `brand_tier_*.csv` files, historical social baselines in the
`social_baseline_*.json` files, analyst ticket severity assessments in the
`ticket_notes_*.txt` files, and executive watchlists in the
`exec_watchlist_*.yaml` files.

All keyword matching in this methodology is case-insensitive substring
matching against the relevant text.

## Signal 1 — Social media volume anomaly

For each brand, take its daily social media mention counts across all tracked
platforms. For each day, sum the mention counts across platforms to obtain a
daily total, then compute the average daily total over the monitoring window.
The anomaly is measured as a z-score against the brand's historical baseline:
subtract the baseline mean from the current average and divide by the baseline
standard deviation. The raw social anomaly signal is the z-score clamped to
zero at the lower end: only positive z-scores contribute; if the current
average falls at or below the baseline mean, the raw signal is zero. (The
z-score itself, before clamping, is what gets reported as `social_zscore` and
may be negative.)

## Signal 2 — News headline sentiment

For each brand, take all of its headlines from the monitoring period. Count
how many headlines contain at least one critical keyword, and separately count
how many contain at least one negative keyword. A headline that matches any
critical keyword is counted only as critical, not also as negative. The raw
headline risk is: (number of negative headlines + 2 x number of critical
headlines) / total number of headlines for the brand. If a brand has no
headlines the headline risk is zero. This raw fraction is what gets reported
as `headline_risk`.

## Signal 3 — Support ticket sentiment

For each brand, take all of its support tickets and examine the full content
of each ticket by combining its subject line and body text. Classify a ticket
as negative if the combined text contains at least one negative keyword. The
base ticket negativity ratio is the fraction of negative tickets out of the
brand's total ticket count (zero if the brand has no tickets). Multiply the
base ratio by the severity override multiplier (from
`severity_override_multipliers` in the priority configuration) corresponding
to the "Overall ticket severity" assigned to the brand in the analyst ticket
notes; brands without an assessment default to "normal". This adjusted value
is the raw ticket signal and is what gets reported as `ticket_negativity`.

## Signal 4 — Executive communications risk

For each brand, take all of its executive communications and identify the
spokesperson of each. Cross-reference the spokespersons against the brand's
executive watchlist, which lists the watched executives and a risk assessment
level. The executive risk flag is one if at least one communication is
authored by a watched executive and its detailed summary content contains at
least one crisis keyword; otherwise the flag is zero. The raw executive signal
is the flag multiplied by the risk assessment multiplier (from
`risk_assessment_multipliers` in the priority configuration) for the brand's
risk assessment level; brands without a watchlist entry default to "medium".
The flag itself (zero or one) is what gets reported as `exec_risk_flag`.

## Combining signals into the final severity score

Each of the four signals has a raw value as defined above. Multiply each raw
value by its scaling factor (`signal_scaling`) to bring the signals to a
common scale, then multiply each scaled value by its category weight
(`weights`). Sum the four weighted components, then multiply the sum by the
tier multiplier (`tier_multipliers`) corresponding to the brand's monitoring
tier (brands without a tier assignment default to "silver"). Round the result
to two decimal places to obtain the brand's final severity score.

## Alerting

A brand enters the alert queue when its final severity score meets or exceeds
`alert_threshold` in the priority configuration. The queue is sorted in
descending order of severity score, with ties broken by ascending brand
identifier, and ranked starting at one.
"""
    with open(os.path.join(workspace, "alert_methodology.md"), "w") as f:
        f.write(methodology)

    # ---- Scalable data files (4 types x files_per_type) ----

    def _chunk(lst, fi):
        start = fi * brands_per_file
        end = (fi + 1) * brands_per_file if fi < files_per_type - 1 else num_brands
        return lst[start:end]

    # Type A – brand_tier CSVs
    for fi in range(files_per_type):
        chunk = _chunk(brands, fi)
        fpath = os.path.join(workspace, f"brand_tier_{fi+1}.csv")
        with open(fpath, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["brand_id", "brand_name", "monitoring_tier"])
            for b in chunk:
                w.writerow([b["id"], b["name"], b["tier"]])

    # Type B – social_baseline JSONs
    for fi in range(files_per_type):
        chunk = _chunk(brands, fi)
        data = {}
        for b in chunk:
            bl = baselines[b["id"]]
            data[str(b["id"])] = {"mean": bl["mean"], "std": bl["std"]}
        fpath = os.path.join(workspace, f"social_baseline_{fi+1}.json")
        with open(fpath, "w") as f:
            json.dump(data, f, indent=2)

    # Type C – ticket_notes TXTs
    for fi in range(files_per_type):
        chunk = _chunk(brands, fi)
        lines = []
        for b in chunk:
            if b["is_troubled"]:
                severity = "elevated" if rng.random() < 0.70 else "normal"
            else:
                severity = "low" if rng.random() < 0.25 else "normal"
            lines.append(f"=== Brand: {b['name']} (ID: {b['id']}) ===")
            lines.append("Analyst assessment of recent support ticket trends.")
            lines.append(f"Overall ticket severity: {severity}")
            if severity == "elevated":
                lines.append("Notes: Multiple unresolved complaints with recurring patterns observed. Elevated monitoring recommended.")
            elif severity == "low":
                lines.append("Notes: Below-average ticket volume with high resolution rates. Low risk profile.")
            else:
                lines.append("Notes: Standard support volume with typical resolution rates. No unusual patterns detected.")
            lines.append("---")
            lines.append("")
        fpath = os.path.join(workspace, f"ticket_notes_{fi+1}.txt")
        with open(fpath, "w") as f:
            f.write("\n".join(lines))

    # Type D – exec_watchlist YAMLs
    for fi in range(files_per_type):
        chunk = _chunk(brands, fi)
        watchlist_data = []
        for b in chunk:
            execs = exec_names[b["id"]]
            if b["is_troubled"]:
                num_watched = min(len(execs), int(rng.randint(1, 3)))
                watched = [str(x) for x in rng.choice(execs, num_watched, replace=False)]
                risk = "high" if rng.random() < 0.60 else "medium"
            else:
                if rng.random() < 0.30:
                    watched = [execs[0]]
                    risk = "low"
                else:
                    watched = []
                    risk = "low"
            watchlist_data.append({
                "brand_id": int(b["id"]),
                "brand_name": b["name"],
                "watched_executives": watched,
                "risk_assessment": risk,
            })
        fpath = os.path.join(workspace, f"exec_watchlist_{fi+1}.yaml")
        with open(fpath, "w") as f:
            yaml.dump(watchlist_data, f, default_flow_style=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate brand-reputation monitoring data")
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # Deterministic seeding
    random.seed(42)
    np.random.seed(42)
    rng = np.random.RandomState(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(args.workspace, exist_ok=True)

    # Build brands & baselines
    num_brands = SCALE["rows_per_table"]
    brands = _generate_brands(num_brands, rng, fake)
    baselines = _generate_baselines(brands, rng)

    # Database
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    _create_tables(conn)
    _insert_brands(conn, brands)
    _insert_headlines(conn, brands, rng)
    _insert_social_media(conn, brands, baselines, rng)
    _insert_tickets(conn, brands, rng)
    exec_names = _insert_exec_comms(conn, brands, rng, fake)
    conn.close()

    # Workspace
    _generate_workspace(args.workspace, brands, baselines, exec_names, rng)

    print(f"Database created at {args.db_path}")
    print(f"Workspace generated in {args.workspace}")


if __name__ == "__main__":
    main()
