"""
Data generation for SLA-Aware Bug Triage Scoring task.
Generates database tables and workspace files for bug prioritization.
"""

import argparse
import json
import os
import random
import sqlite3
import csv
import yaml

import numpy as np
import pandas as pd
from faker import Faker

# ── Global seed ──────────────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ── Scale parameters (v0 base) ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 400,      # v3 = 8x base
    "num_workspace_files": 40,  # v3 = base + 3N
}

# ── Constants ────────────────────────────────────────────────────────────────
SEVERITIES = ["critical", "high", "medium", "low"]
CONTRACT_TIERS = ["platinum", "gold", "silver", "bronze"]
MODULES = [
    "authentication", "payments", "dashboard", "api",
    "reports", "notifications", "search", "user_management",
    "analytics", "integrations", "file_storage", "messaging",
]
TEAMS = [
    "security", "billing", "frontend", "backend",
    "data", "platform", "infrastructure", "mobile",
]
SKILLS = [
    "python", "javascript", "sql", "react", "java",
    "go", "rust", "kubernetes", "aws", "debugging",
    "performance", "security_audit", "database", "networking",
    "ci_cd", "testing", "devops", "machine_learning",
]


def create_tables(conn: sqlite3.Connection):
    """Create all database tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id INTEGER PRIMARY KEY,
            company_name TEXT NOT NULL,
            contract_tier TEXT NOT NULL,
            annual_revenue REAL NOT NULL,
            account_manager TEXT NOT NULL,
            industry TEXT NOT NULL,
            support_contacts INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS features (
            feature_id INTEGER PRIMARY KEY,
            feature_name TEXT NOT NULL,
            module TEXT NOT NULL,
            daily_active_users INTEGER NOT NULL,
            monthly_active_users INTEGER NOT NULL,
            error_rate REAL NOT NULL,
            revenue_contribution REAL NOT NULL,
            launch_date TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS developers (
            dev_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            team TEXT NOT NULL,
            skills TEXT NOT NULL,
            experience_years INTEGER NOT NULL,
            max_concurrent_bugs INTEGER NOT NULL,
            active_bugs INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bugs_history (
            bug_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            severity TEXT NOT NULL,
            feature_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            component TEXT NOT NULL,
            reported_date TEXT NOT NULL,
            resolved_date TEXT NOT NULL,
            developer_id INTEGER NOT NULL,
            fix_time_hours REAL NOT NULL,
            FOREIGN KEY (feature_id) REFERENCES features(feature_id),
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
            FOREIGN KEY (developer_id) REFERENCES developers(dev_id)
        );
    """)


def generate_customers(conn: sqlite3.Connection, n: int):
    """Generate customer records."""
    industries = [
        "fintech", "healthcare", "e-commerce", "saas", "education",
        "logistics", "media", "manufacturing", "telecom", "government",
    ]
    rows = []
    for i in range(1, n + 1):
        tier = CONTRACT_TIERS[i % len(CONTRACT_TIERS)]
        rows.append((
            i,
            fake.company(),
            tier,
            round(random.uniform(50_000, 5_000_000), 2),
            fake.name(),
            random.choice(industries),
            random.randint(1, 10),
        ))
    conn.executemany(
        "INSERT INTO customers VALUES (?,?,?,?,?,?,?)", rows
    )
    return rows


def generate_features(conn: sqlite3.Connection, n: int):
    """Generate feature catalogue with telemetry."""
    rows = []
    feature_names_used = set()
    for i in range(1, n + 1):
        module = MODULES[i % len(MODULES)]
        while True:
            fname = f"{module}_{fake.word()}_{i}"
            if fname not in feature_names_used:
                feature_names_used.add(fname)
                break
        dau = random.randint(100, 50000)
        rows.append((
            i,
            fname,
            module,
            dau,
            dau * random.randint(15, 30),
            round(random.uniform(0.001, 0.15), 4),
            round(random.uniform(0.5, 15.0), 2),
            fake.date_between(start_date="-3y", end_date="-6m").isoformat(),
        ))
    conn.executemany(
        "INSERT INTO features VALUES (?,?,?,?,?,?,?,?)", rows
    )
    return rows


def generate_developers(conn: sqlite3.Connection, n: int):
    """Generate developer profiles."""
    rows = []
    for i in range(1, n + 1):
        team = TEAMS[i % len(TEAMS)]
        num_skills = random.randint(2, 5)
        skills = ", ".join(random.sample(SKILLS, num_skills))
        max_bugs = random.randint(3, 8)
        active = random.randint(0, max_bugs)
        rows.append((
            i,
            fake.name(),
            fake.email(),
            team,
            skills,
            random.randint(1, 15),
            max_bugs,
            active,
        ))
    conn.executemany(
        "INSERT INTO developers VALUES (?,?,?,?,?,?,?,?)", rows
    )
    return rows


def generate_bugs_history(conn: sqlite3.Connection, n: int,
                          num_features: int, num_customers: int,
                          num_devs: int):
    """Generate historical resolved bug records."""
    rows = []
    for i in range(1, n + 1):
        severity = random.choice(SEVERITIES)
        feature_id = random.randint(1, num_features)
        customer_id = random.randint(1, num_customers)
        module = MODULES[feature_id % len(MODULES)]
        reported = fake.date_between(start_date="-2y", end_date="-30d")
        # Fix time depends on severity
        base_hours = {"critical": 8, "high": 20, "medium": 40, "low": 72}
        fix_hours = round(
            max(1, np.random.normal(base_hours[severity],
                                     base_hours[severity] * 0.4)),
            1,
        )
        resolved = pd.Timestamp(reported) + pd.Timedelta(hours=fix_hours)
        rows.append((
            i,
            f"Bug: {fake.sentence(nb_words=6)}",
            severity,
            feature_id,
            customer_id,
            module,
            reported.isoformat(),
            resolved.strftime("%Y-%m-%d"),
            random.randint(1, num_devs),
            fix_hours,
        ))
    conn.executemany(
        "INSERT INTO bugs_history VALUES (?,?,?,?,?,?,?,?,?,?)", rows
    )
    return rows


# ── Workspace generation ────────────────────────────────────────────────────

def generate_new_bug_reports(workspace: str, n_files: int,
                             num_features: int, num_customers: int,
                             features_rows, customers_rows):
    """Generate individual new bug report files in mixed formats."""
    # Determine how many bugs per format cycle
    bug_reports = []
    for idx in range(1, n_files + 1):
        bug_id = f"NEW-{idx:04d}"
        severity = random.choice(SEVERITIES)
        feature_row = features_rows[(idx - 1) % len(features_rows)]
        feature_id = feature_row[0]
        feature_name = feature_row[1]
        module = feature_row[2]
        customer_row = customers_rows[(idx * 3) % len(customers_rows)]
        customer_id = customer_row[0]
        company_name = customer_row[1]

        report = {
            "bug_id": bug_id,
            "title": f"Issue: {fake.sentence(nb_words=7)}",
            "severity": severity,
            "affected_feature": feature_name,
            "feature_id": feature_id,
            "module": module,
            "reported_by_customer_id": customer_id,
            "reported_by_company": company_name,
            "description": fake.paragraph(nb_sentences=3),
            "steps_to_reproduce": [fake.sentence() for _ in range(3)],
            "environment": random.choice(["production", "staging"]),
            "reported_date": fake.date_between(
                start_date="-7d", end_date="today"
            ).isoformat(),
        }
        bug_reports.append(report)

        # Alternate formats
        fmt = idx % 4
        if fmt == 0:
            # JSON format
            fpath = os.path.join(workspace, f"bug_report_{bug_id}.json")
            with open(fpath, "w") as f:
                json.dump(report, f, indent=2)
        elif fmt == 1:
            # Markdown format
            fpath = os.path.join(workspace, f"bug_report_{bug_id}.md")
            with open(fpath, "w") as f:
                f.write(f"# Bug Report {bug_id}\n\n")
                f.write(f"**Title:** {report['title']}\n\n")
                f.write(f"**Severity:** {report['severity']}\n\n")
                f.write(f"**Affected Feature:** {report['affected_feature']}"
                        f" (ID: {report['feature_id']})\n\n")
                f.write(f"**Module:** {report['module']}\n\n")
                f.write(f"**Reported By:** {report['reported_by_company']}"
                        f" (Customer ID: {report['reported_by_customer_id']})"
                        f"\n\n")
                f.write(f"**Environment:** {report['environment']}\n\n")
                f.write(f"**Reported Date:** {report['reported_date']}\n\n")
                f.write(f"## Description\n\n{report['description']}\n\n")
                f.write("## Steps to Reproduce\n\n")
                for j, step in enumerate(report["steps_to_reproduce"], 1):
                    f.write(f"{j}. {step}\n")
        elif fmt == 2:
            # YAML format
            fpath = os.path.join(workspace, f"bug_report_{bug_id}.yaml")
            with open(fpath, "w") as f:
                yaml.dump(report, f, default_flow_style=False, sort_keys=False)
        else:
            # TXT format
            fpath = os.path.join(workspace, f"bug_report_{bug_id}.txt")
            with open(fpath, "w") as f:
                f.write(f"BUG ID: {bug_id}\n")
                f.write(f"TITLE: {report['title']}\n")
                f.write(f"SEVERITY: {report['severity']}\n")
                f.write(f"FEATURE: {report['affected_feature']}"
                        f" (ID: {report['feature_id']})\n")
                f.write(f"MODULE: {report['module']}\n")
                f.write(f"CUSTOMER: {report['reported_by_company']}"
                        f" (ID: {report['reported_by_customer_id']})\n")
                f.write(f"ENVIRONMENT: {report['environment']}\n")
                f.write(f"DATE: {report['reported_date']}\n")
                f.write(f"\nDESCRIPTION:\n{report['description']}\n")
                f.write("\nSTEPS TO REPRODUCE:\n")
                for j, step in enumerate(report["steps_to_reproduce"], 1):
                    f.write(f"  {j}. {step}\n")

    return bug_reports


def generate_developer_schedules(workspace: str, dev_rows, n_schedule_files: int):
    """Generate developer availability schedule files as CSV."""
    devs_per_file = max(1, len(dev_rows) // n_schedule_files)
    for file_idx in range(n_schedule_files):
        start = file_idx * devs_per_file
        end = start + devs_per_file if file_idx < n_schedule_files - 1 else len(dev_rows)
        chunk = dev_rows[start:end]

        fpath = os.path.join(workspace, f"dev_schedule_week_{file_idx + 1}.csv")
        with open(fpath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "dev_id", "name", "available_hours_this_week",
                "on_call", "pto_days", "current_sprint_load_pct",
            ])
            for dev in chunk:
                dev_id = dev[0]
                name = dev[1]
                avail_hours = random.randint(10, 40)
                on_call = random.choice(["yes", "no"])
                pto = random.randint(0, 3)
                sprint_load = random.randint(20, 95)
                writer.writerow([
                    dev_id, name, avail_hours, on_call, pto, sprint_load,
                ])


def generate_fixed_config_files(workspace: str):
    """Generate task-inherent configuration files (not scaled)."""

    # 1. SLA tier configuration
    sla_config = {
        "tiers": {
            "platinum": {
                "response_hours": 4,
                "resolution_hours": 24,
                "escalation_threshold_pct": 80,
                "penalty_per_hour_late": 500.0,
            },
            "gold": {
                "response_hours": 8,
                "resolution_hours": 48,
                "escalation_threshold_pct": 60,
                "penalty_per_hour_late": 200.0,
            },
            "silver": {
                "response_hours": 24,
                "resolution_hours": 120,
                "escalation_threshold_pct": 40,
                "penalty_per_hour_late": 50.0,
            },
            "bronze": {
                "response_hours": 48,
                "resolution_hours": 240,
                "escalation_threshold_pct": 20,
                "penalty_per_hour_late": 10.0,
            },
        }
    }
    with open(os.path.join(workspace, "sla_config.yaml"), "w") as f:
        yaml.dump(sla_config, f, default_flow_style=False, sort_keys=False)

    # 2. Priority scoring weights
    scoring_weights = {
        "severity_weight": 0.30,
        "sla_urgency_weight": 0.25,
        "feature_impact_weight": 0.25,
        "historical_complexity_weight": 0.20,
        "severity_scores": {
            "critical": 10.0,
            "high": 7.0,
            "medium": 4.0,
            "low": 1.0,
        },
        "sla_urgency_scores": {
            "platinum": 10.0,
            "gold": 7.0,
            "silver": 4.0,
            "bronze": 2.0,
        },
        "feature_impact_formula": "normalized DAU (0-10 scale) multiplied by (1 + error_rate * 10)",
        "historical_complexity_formula": "10 minus normalized average fix time (0-10 scale, higher means simpler/faster fix, more urgent to fix quickly)",
    }
    with open(os.path.join(workspace, "priority_weights.json"), "w") as f:
        json.dump(scoring_weights, f, indent=2)

    # 3. Module-to-team mapping
    module_teams = {
        "module_team_mapping": {
            "authentication": "security",
            "payments": "billing",
            "dashboard": "frontend",
            "api": "backend",
            "reports": "data",
            "notifications": "platform",
            "search": "backend",
            "user_management": "security",
            "analytics": "data",
            "integrations": "platform",
            "file_storage": "infrastructure",
            "messaging": "platform",
        },
        "assignment_rules": {
            "prefer_same_team": True,
            "prefer_experienced_for_critical": True,
            "min_experience_years_for_critical": 5,
            "max_active_bugs_pct": 0.85,
            "tiebreaker": "lowest_active_bugs_then_highest_experience",
        },
    }
    with open(os.path.join(workspace, "team_module_mapping.yaml"), "w") as f:
        yaml.dump(module_teams, f, default_flow_style=False, sort_keys=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    # Database setup
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    customers_rows = generate_customers(conn, n)
    features_rows = generate_features(conn, n)
    dev_rows = generate_developers(conn, n)
    generate_bugs_history(conn, n, len(features_rows),
                          len(customers_rows), len(dev_rows))
    conn.commit()
    conn.close()

    # Workspace: scalable files
    # 80% bug reports, 20% schedule files (at least 2 schedule files)
    n_schedule = max(2, n_files // 5)
    n_bugs = n_files - n_schedule

    generate_new_bug_reports(
        args.workspace, n_bugs,
        len(features_rows), len(customers_rows),
        features_rows, customers_rows,
    )
    generate_developer_schedules(args.workspace, dev_rows, n_schedule)

    # Fixed config files (not counted in SCALE)
    generate_fixed_config_files(args.workspace)

    print(f"Data generated: {n} rows/table, {n_files} scalable workspace files"
          f" + 3 config files")


if __name__ == "__main__":
    main()
