import os
import json
import csv
import math
import sqlite3
import argparse
import random
import numpy as np
from faker import Faker

SCALE = {
    "rows_per_table": 100,
    "num_workspace_files": 16,
}

REGIONS = [
    "Northeast", "Southeast", "Midwest", "Southwest",
    "Northwest", "Mid_Atlantic", "Great_Plains", "Pacific",
]

LOAN_TYPES = ["mortgage", "auto", "personal", "business", "home_equity"]

PROPERTY_TYPE_MAP = {
    "mortgage": ["single_family", "condo", "townhouse", "multi_family"],
    "home_equity": ["single_family", "condo", "townhouse"],
    "auto": ["vehicle"],
    "personal": ["N/A"],
    "business": ["commercial"],
}

ALERT_TYPES = [
    "identity_mismatch", "income_discrepancy", "address_inconsistency",
    "document_forgery", "velocity_alert", "watchlist_match",
]

SEVERITIES = ["low", "medium", "high", "critical"]

INCOME_SOURCES = ["employment", "self_employment", "investment", "pension", "rental"]


# ---------------------------------------------------------------------------
# Data generation helpers
# ---------------------------------------------------------------------------

def generate_applications(n, fake):
    apps = []
    for i in range(1, n + 1):
        app_id = f"APP-{i:04d}"
        name = fake.name()
        region = random.choice(REGIONS)
        loan_type = random.choice(LOAN_TYPES)
        prop_type = random.choice(PROPERTY_TYPE_MAP[loan_type])

        if loan_type == "mortgage":
            amount = round(random.uniform(150000, 750000), 2)
        elif loan_type == "home_equity":
            amount = round(random.uniform(30000, 200000), 2)
        elif loan_type == "auto":
            amount = round(random.uniform(15000, 65000), 2)
        elif loan_type == "personal":
            amount = round(random.uniform(5000, 50000), 2)
        else:
            amount = round(random.uniform(50000, 500000), 2)

        r = random.random()
        if r < 0.60:
            status = "pending"
        elif r < 0.85:
            status = "approved"
        else:
            status = "rejected"

        app_date = fake.date_between(start_date="-90d", end_date="today").isoformat()
        apps.append((app_id, name, region, amount, loan_type, prop_type, app_date, status))
    return apps


def generate_credit_bureau(apps):
    data = []
    for i, app in enumerate(apps, 1):
        app_id = app[0]
        credit_score = int(np.clip(np.random.normal(690, 60), 450, 850))
        delinquencies = int(np.random.choice(
            [0, 1, 2, 3, 4, 5],
            p=[0.55, 0.20, 0.10, 0.08, 0.04, 0.03],
        ))
        utilization = round(float(np.clip(np.random.normal(0.35, 0.20), 0.01, 0.99)), 2)
        revolving = round(random.uniform(2000, 80000), 2)
        installment = round(random.uniform(5000, 200000), 2)
        monthly_payment = round((revolving * 0.03) + (installment / 60), 2)
        inquiries = int(np.random.choice(
            range(0, 8),
            p=[0.30, 0.25, 0.15, 0.10, 0.08, 0.05, 0.04, 0.03],
        ))
        oldest = round(random.uniform(1, 25), 1)
        data.append((
            i, app_id, credit_score, delinquencies, utilization,
            revolving, installment, monthly_payment, inquiries, oldest,
        ))
    return data


def generate_fraud_alerts(n_min, apps, fake):
    data = []
    alert_id = 1
    n_with_alerts = max(int(len(apps) * 0.35), 1)
    selected = random.sample(range(len(apps)), k=n_with_alerts)
    for idx in selected:
        app_id = apps[idx][0]
        num_alerts = random.choices([1, 2, 3], weights=[0.50, 0.35, 0.15])[0]
        for _ in range(num_alerts):
            atype = random.choice(ALERT_TYPES)
            severity = random.choices(SEVERITIES, weights=[0.25, 0.30, 0.25, 0.20])[0]
            desc = f"{atype.replace('_', ' ').title()} detected"
            adate = fake.date_between(start_date="-60d", end_date="today").isoformat()
            is_resolved = random.choices([0, 1], weights=[0.65, 0.35])[0]
            data.append((alert_id, app_id, atype, severity, desc, adate, is_resolved))
            alert_id += 1

    # Pad to minimum row count
    while len(data) < n_min:
        idx = random.randint(0, len(apps) - 1)
        app_id = apps[idx][0]
        atype = random.choice(ALERT_TYPES)
        severity = random.choices(SEVERITIES, weights=[0.25, 0.30, 0.25, 0.20])[0]
        desc = f"{atype.replace('_', ' ').title()} detected"
        adate = fake.date_between(start_date="-60d", end_date="today").isoformat()
        is_resolved = random.choices([0, 1], weights=[0.65, 0.35])[0]
        data.append((alert_id, app_id, atype, severity, desc, adate, is_resolved))
        alert_id += 1
    return data


def generate_regional_defaults(n_min):
    data = []
    rec_id = 1
    base_years = list(range(2015, 2026))
    quarters = [1, 2, 3, 4]
    natural_count = len(REGIONS) * len(base_years) * len(quarters)

    if natural_count < n_min:
        extra = math.ceil((n_min - natural_count) / (len(REGIONS) * len(quarters)))
        years = list(range(2015 - extra, 2026))
    else:
        years = base_years

    region_base_rates = {r: round(random.uniform(2.0, 10.0), 2) for r in REGIONS}

    for region in REGIONS:
        base_rate = region_base_rates[region]
        for year in years:
            for quarter in quarters:
                drift = random.uniform(-1.5, 1.5)
                rate = round(max(0.5, base_rate + drift + (year - 2020) * 0.1), 2)
                loss_severity = round(random.uniform(0.30, 0.70), 2)
                n_loans = random.randint(500, 5000)
                n_defaults = max(1, int(n_loans * rate / 100))
                data.append((rec_id, region, year, quarter, rate, loss_severity, n_loans, n_defaults))
                rec_id += 1
    return data


def generate_applicant_history(n_min, apps, fake):
    data = []
    hist_id = 1
    for app in apps:
        app_id = app[0]
        n_prior = random.choices([0, 1, 2, 3], weights=[0.40, 0.30, 0.20, 0.10])[0]
        for _ in range(n_prior):
            prior_date = fake.date_between(start_date="-5y", end_date="-91d").isoformat()
            prior_amount = round(random.uniform(5000, 500000), 2)
            prior_type = random.choice(LOAN_TYPES)
            outcome = random.choices(
                ["repaid", "defaulted", "current", "settled"],
                weights=[0.50, 0.15, 0.25, 0.10],
            )[0]
            data.append((hist_id, app_id, prior_date, prior_amount, prior_type, outcome))
            hist_id += 1

    while len(data) < n_min:
        idx = random.randint(0, len(apps) - 1)
        app_id = apps[idx][0]
        prior_date = fake.date_between(start_date="-5y", end_date="-91d").isoformat()
        prior_amount = round(random.uniform(5000, 500000), 2)
        prior_type = random.choice(LOAN_TYPES)
        outcome = random.choices(
            ["repaid", "defaulted", "current", "settled"],
            weights=[0.50, 0.15, 0.25, 0.10],
        )[0]
        data.append((hist_id, app_id, prior_date, prior_amount, prior_type, outcome))
        hist_id += 1
    return data


# ---------------------------------------------------------------------------
# Workspace file generators
# ---------------------------------------------------------------------------

def generate_income_data(apps, fake):
    records = []
    for app in apps:
        app_id, _, _, loan_amount, loan_type = app[0], app[1], app[2], app[3], app[4]
        if loan_type == "mortgage":
            base_income = loan_amount * random.uniform(0.15, 0.50)
        elif loan_type == "business":
            base_income = loan_amount * random.uniform(0.20, 0.60)
        else:
            base_income = loan_amount * random.uniform(0.50, 2.00)
        annual_income = round(max(25000, min(500000, base_income)), 2)
        source = random.choice(INCOME_SOURCES)
        employer = fake.company()
        emp_length = round(random.uniform(0.5, 30.0), 1)
        ver_date = fake.date_between(start_date="-30d", end_date="today").isoformat()
        ver_status = random.choices(
            ["verified", "partially_verified", "unverified"],
            weights=[0.70, 0.20, 0.10],
        )[0]
        records.append({
            "applicant_id": app_id,
            "verified_annual_income": annual_income,
            "income_source": source,
            "employer": employer,
            "employment_length_years": emp_length,
            "verification_date": ver_date,
            "verification_status": ver_status,
        })
    return records


def generate_property_appraisals(apps, fake):
    appraisals = []
    for app in apps:
        app_id, _, region, loan_amount, loan_type = app[0], app[1], app[2], app[3], app[4]
        if loan_type not in ("mortgage", "home_equity"):
            continue
        ltv = random.uniform(0.60, 1.05)
        appraised_value = round(loan_amount / ltv, 2)
        appraisal_date = fake.date_between(start_date="-45d", end_date="-5d").isoformat()
        condition = random.choice(["excellent", "good", "fair", "poor"])
        appraisals.append({
            "application_id": app_id,
            "appraised_value": appraised_value,
            "appraisal_date": appraisal_date,
            "condition_rating": condition,
            "property_region": region,
        })
    return appraisals


def write_income_files(workspace, records, n_files):
    batch_size = math.ceil(len(records) / max(n_files, 1))
    for i in range(n_files):
        batch = records[i * batch_size : (i + 1) * batch_size]
        fname = f"income_verification_batch_{i + 1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(batch, f, indent=2)


def write_property_files(workspace, appraisals, n_files):
    if n_files == 0:
        return
    batch_size = max(1, math.ceil(len(appraisals) / n_files))
    fieldnames = ["application_id", "appraised_value", "appraisal_date",
                  "condition_rating", "property_region"]
    for i in range(n_files):
        batch = appraisals[i * batch_size : (i + 1) * batch_size]
        fname = f"property_appraisal_{i + 1:03d}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rec in batch:
                writer.writerow(rec)


def write_risk_config(workspace):
    """Write risk_scoring_config.yaml using manual YAML formatting."""
    content = """risk_weights:
  credit_score: 0.25
  debt_to_income: 0.20
  fraud_severity: 0.20
  regional_default: 0.15
  loan_to_value: 0.10
  prior_defaults: 0.10

credit_score_tiers:
  excellent:
    min_score: 750
    risk_factor: 0.1
  good:
    min_score: 700
    risk_factor: 0.3
  fair:
    min_score: 650
    risk_factor: 0.5
  poor:
    min_score: 600
    risk_factor: 0.7
  very_poor:
    min_score: 0
    risk_factor: 1.0

dti_thresholds:
  low:
    max_ratio: 0.36
    risk_factor: 0.2
  moderate:
    max_ratio: 0.43
    risk_factor: 0.5
  high:
    max_ratio: 0.50
    risk_factor: 0.8
  very_high:
    max_ratio: 999.0
    risk_factor: 1.0

fraud_severity_scores:
  critical: 1.0
  high: 0.8
  medium: 0.5
  low: 0.2
  none: 0.0

regional_risk_thresholds:
  high_risk:
    min_default_rate: 8.0
    risk_factor: 1.0
  elevated:
    min_default_rate: 5.0
    risk_factor: 0.7
  moderate:
    min_default_rate: 3.0
    risk_factor: 0.4
  low_risk:
    min_default_rate: 0.0
    risk_factor: 0.2

ltv_thresholds:
  safe:
    max_ltv: 0.80
    risk_factor: 0.2
  standard:
    max_ltv: 0.90
    risk_factor: 0.5
  high:
    max_ltv: 0.95
    risk_factor: 0.8
  very_high:
    max_ltv: 999.0
    risk_factor: 1.0

ltv_non_applicable_risk_factor: 0.3

prior_default_risk:
  - max_defaults: 0
    risk_factor: 0.0
  - max_defaults: 1
    risk_factor: 0.6
  - max_defaults: 999
    risk_factor: 1.0

priority_tiers:
  critical:
    min_score: 0.75
  high:
    min_score: 0.55
  medium:
    min_score: 0.35
  low:
    min_score: 0.0

policy_overrides:
  critical_fraud_override:
    enabled: true
    trigger_severity: critical
    assign_tier: critical
  multiple_alerts_adjustment:
    enabled: true
    min_unresolved_alerts: 2
    score_adjustment: 0.10
  combined_dti_fraud_escalation:
    enabled: true
    dti_threshold: 0.50
    min_tier: high
"""
    with open(os.path.join(workspace, "risk_scoring_config.yaml"), "w") as f:
        f.write(content)


def write_underwriting_policy(workspace):
    policy = """Underwriting Review Policy

Override Rules

The following rules take precedence over the computed risk score when assigning
priority tiers to the review queue. They must be applied after the initial risk
score computation, in the order listed below. The specific numeric thresholds
referenced here are defined in the risk scoring configuration file.

Rule 1 - Critical Fraud Override:
Any loan application associated with at least one unresolved fraud alert whose
severity matches the trigger severity specified in the configuration must be
placed in the tier designated by the critical fraud override setting, regardless
of the computed risk score.

Rule 2 - Multiple Unresolved Alerts Adjustment:
If an applicant has a number of unresolved fraud alerts meeting or exceeding the
multiple-alerts threshold in the configuration, add the configured score
adjustment to their computed risk score before determining the priority tier.
The adjusted score must be capped at 1.0.

Rule 3 - Combined DTI and Fraud Escalation:
If an applicant's debt-to-income ratio exceeds the combined-escalation DTI
threshold specified in the configuration AND the applicant has at least one
unresolved fraud alert of any severity, the application must be assigned to at
minimum the escalation tier specified in the configuration. If the computed
tier (after any adjustments from Rules 1 and 2) is already equal to or more
urgent than the escalation tier, no change is needed.

Notes:
- Rule 1 takes absolute precedence. If triggered, the tier is set to the
  override tier regardless of Rules 2 and 3.
- The primary_risk_factor field in the output should always reflect the highest
  weighted risk component from the base calculation, not the override reason.
"""
    with open(os.path.join(workspace, "underwriting_policy.md"), "w") as f:
        f.write(policy)


# ---------------------------------------------------------------------------
# Database creation
# ---------------------------------------------------------------------------

def create_database(db_path, apps, credit, fraud, regional, history):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS loan_applications (
        application_id TEXT PRIMARY KEY,
        applicant_name TEXT,
        region TEXT,
        loan_amount REAL,
        loan_type TEXT,
        property_type TEXT,
        application_date TEXT,
        status TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS credit_bureau (
        record_id INTEGER PRIMARY KEY,
        applicant_id TEXT,
        credit_score INTEGER,
        num_delinquencies INTEGER,
        credit_utilization_pct REAL,
        total_revolving_debt REAL,
        total_installment_debt REAL,
        monthly_debt_payment REAL,
        hard_inquiries_12m INTEGER,
        oldest_account_years REAL,
        FOREIGN KEY (applicant_id) REFERENCES loan_applications(application_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS fraud_alerts (
        alert_id INTEGER PRIMARY KEY,
        applicant_id TEXT,
        alert_type TEXT,
        severity TEXT,
        description TEXT,
        alert_date TEXT,
        is_resolved INTEGER,
        FOREIGN KEY (applicant_id) REFERENCES loan_applications(application_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS regional_defaults (
        record_id INTEGER PRIMARY KEY,
        region TEXT,
        year INTEGER,
        quarter INTEGER,
        default_rate_pct REAL,
        avg_loss_severity REAL,
        total_loans INTEGER,
        total_defaults INTEGER
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS applicant_history (
        history_id INTEGER PRIMARY KEY,
        applicant_id TEXT,
        prior_application_date TEXT,
        prior_loan_amount REAL,
        prior_loan_type TEXT,
        outcome TEXT,
        FOREIGN KEY (applicant_id) REFERENCES loan_applications(application_id)
    )""")

    c.executemany("INSERT INTO loan_applications VALUES (?,?,?,?,?,?,?,?)", apps)
    c.executemany("INSERT INTO credit_bureau VALUES (?,?,?,?,?,?,?,?,?,?)", credit)
    c.executemany("INSERT INTO fraud_alerts VALUES (?,?,?,?,?,?,?)", fraud)
    c.executemany("INSERT INTO regional_defaults VALUES (?,?,?,?,?,?,?,?)", regional)
    c.executemany("INSERT INTO applicant_history VALUES (?,?,?,?,?,?)", history)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    n_apps = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # Generate all data
    apps = generate_applications(n_apps, fake)
    credit = generate_credit_bureau(apps)
    fraud = generate_fraud_alerts(n_apps, apps, fake)
    regional = generate_regional_defaults(n_apps)
    history = generate_applicant_history(n_apps, apps, fake)

    # Create database
    create_database(db_path, apps, credit, fraud, regional, history)

    # Generate workspace files
    n_income = math.ceil(n_files * 0.6)
    n_property = n_files - n_income

    income_records = generate_income_data(apps, fake)
    appraisals = generate_property_appraisals(apps, fake)

    write_income_files(workspace, income_records, n_income)
    write_property_files(workspace, appraisals, n_property)
    write_risk_config(workspace)
    write_underwriting_policy(workspace)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
