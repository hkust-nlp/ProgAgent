"""Data generation for rental applicant risk screening task."""

import argparse
import json
import os
import sqlite3
import random
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta
import yaml

SCALE = {
    "rows_per_table": 80,
    "num_workspace_files": 16,
}

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

# Fixed reference dates for deterministic behavior
REF_DATE = datetime(2026, 1, 1)
APP_DATE_START = datetime(2025, 11, 1)
APP_DATE_END = datetime(2025, 12, 31)
EVICTION_DATE_START = datetime(2018, 1, 1)
EVICTION_DATE_END = datetime(2025, 6, 1)
REPORT_DATE_START = datetime(2025, 11, 15)
REPORT_DATE_END = datetime(2025, 12, 31)
REFERENCE_DATE_START = datetime(2025, 1, 1)
REFERENCE_DATE_END = datetime(2025, 12, 31)


def create_tables(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS applicants (
            applicant_id INTEGER PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            application_date TEXT,
            property_id INTEGER,
            status TEXT DEFAULT 'pending'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS credit_reports (
            report_id INTEGER PRIMARY KEY,
            applicant_id INTEGER NOT NULL,
            credit_score INTEGER,
            num_delinquencies INTEGER,
            bankruptcy_flag INTEGER,
            credit_utilization REAL,
            total_debt REAL,
            report_date TEXT,
            FOREIGN KEY (applicant_id) REFERENCES applicants(applicant_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS eviction_records (
            record_id INTEGER PRIMARY KEY,
            applicant_id INTEGER NOT NULL,
            eviction_date TEXT,
            court_name TEXT,
            case_number TEXT,
            judgment_amount REAL,
            reason TEXT,
            FOREIGN KEY (applicant_id) REFERENCES applicants(applicant_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS landlord_references (
            reference_id INTEGER PRIMARY KEY,
            applicant_id INTEGER NOT NULL,
            landlord_name TEXT,
            reference_date TEXT,
            payment_timeliness INTEGER,
            property_care INTEGER,
            lease_compliance INTEGER,
            would_rent_again TEXT,
            comments TEXT,
            FOREIGN KEY (applicant_id) REFERENCES applicants(applicant_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS properties (
            property_id INTEGER PRIMARY KEY,
            address TEXT,
            property_type TEXT,
            bedrooms INTEGER,
            neighborhood TEXT
        )
    """)
    conn.commit()


def generate_properties(n_properties):
    """Generate property data. Returns (db_rows, rent_info)."""
    property_types = ['apartment', 'house', 'condo', 'townhouse', 'duplex']
    neighborhoods = ['Downtown', 'Midtown', 'Westside', 'Eastview', 'Northpark',
                     'Southgate', 'Riverside', 'Hillcrest', 'Lakewood', 'Oakdale']

    db_rows = []
    rent_info = []
    for i in range(1, n_properties + 1):
        bedrooms = random.choice([1, 1, 2, 2, 2, 3, 3, 4])
        base_rent = {1: 1200, 2: 1600, 3: 2100, 4: 2800}[bedrooms]
        rent = base_rent + random.randint(-200, 400)
        prop_type = random.choice(property_types)
        neighborhood = random.choice(neighborhoods)
        address = fake.street_address()

        db_rows.append((i, address, prop_type, bedrooms, neighborhood))
        rent_info.append({
            "property_id": i,
            "monthly_rent": rent,
            "address": address,
            "neighborhood": neighborhood,
        })

    return db_rows, rent_info


def generate_applicants(n_applicants, n_properties):
    rows = []
    for i in range(1, n_applicants + 1):
        first_name = fake.first_name()
        last_name = fake.last_name()
        email = f"{first_name.lower()}.{last_name.lower()}@{fake.free_email_domain()}"
        phone = fake.phone_number()
        app_date = fake.date_between_dates(
            date_start=APP_DATE_START, date_end=APP_DATE_END
        ).isoformat()
        property_id = random.randint(1, n_properties)
        rows.append((i, first_name, last_name, email, phone, app_date, property_id, 'pending'))
    return rows


def generate_credit_reports(n_applicants):
    reports = []
    for i in range(1, n_applicants + 1):
        profile = random.choices(
            ['excellent', 'good', 'fair', 'poor'],
            weights=[0.2, 0.35, 0.3, 0.15]
        )[0]

        if profile == 'excellent':
            score = random.randint(750, 850)
            delinq = 0
            bankruptcy = 0
            util = round(random.uniform(0.05, 0.25), 2)
            debt = round(random.uniform(1000, 15000), 2)
        elif profile == 'good':
            score = random.randint(670, 749)
            delinq = random.choice([0, 0, 1])
            bankruptcy = 0
            util = round(random.uniform(0.15, 0.45), 2)
            debt = round(random.uniform(5000, 40000), 2)
        elif profile == 'fair':
            score = random.randint(580, 669)
            delinq = random.choice([0, 1, 2, 2])
            bankruptcy = random.choice([0, 0, 0, 1])
            util = round(random.uniform(0.30, 0.70), 2)
            debt = round(random.uniform(10000, 80000), 2)
        else:
            score = random.randint(300, 579)
            delinq = random.choice([1, 2, 3, 4])
            bankruptcy = random.choice([0, 1, 1])
            util = round(random.uniform(0.50, 0.95), 2)
            debt = round(random.uniform(20000, 150000), 2)

        report_date = fake.date_between_dates(
            date_start=REPORT_DATE_START, date_end=REPORT_DATE_END
        ).isoformat()
        reports.append((i, i, score, delinq, bankruptcy, util, debt, report_date))
    return reports


def generate_eviction_records(n_applicants):
    reasons = ['nonpayment', 'property_damage', 'lease_violation', 'illegal_activity', 'nuisance']
    applicants_with_evictions = sorted(random.sample(
        range(1, n_applicants + 1),
        k=max(1, int(n_applicants * 0.25))
    ))

    records = []
    record_id = 1
    for app_id in applicants_with_evictions:
        num_evictions = random.choices([1, 2, 3], weights=[0.6, 0.3, 0.1])[0]
        for _ in range(num_evictions):
            eviction_date = fake.date_between_dates(
                date_start=EVICTION_DATE_START, date_end=EVICTION_DATE_END
            ).isoformat()
            court = f"{fake.city()} County Court"
            case_num = f"EV-{random.randint(2018, 2025)}-{random.randint(10000, 99999)}"
            judgment = round(random.uniform(500, 15000), 2)
            reason = random.choice(reasons)
            records.append((record_id, app_id, eviction_date, court, case_num, judgment, reason))
            record_id += 1
    return records


def generate_landlord_references(n_applicants):
    comments_pool = [
        "Reliable tenant overall.",
        "Had some late payments but communicated well.",
        "Left the unit in good condition.",
        "Multiple complaints from neighbors.",
        "Would not recommend.",
        "Excellent tenant, always on time.",
        "Required frequent reminders for rent.",
        "Caused minor property damage.",
        "Very respectful of the property.",
        "Had issues with lease terms.",
        "No significant issues during tenancy.",
        "Outstanding tenant in every regard.",
    ]

    references = []
    ref_id = 1
    for app_id in range(1, n_applicants + 1):
        num_refs = random.choices([0, 1, 2, 3], weights=[0.1, 0.3, 0.4, 0.2])[0]
        for _ in range(num_refs):
            landlord = fake.name()
            ref_date = fake.date_between_dates(
                date_start=REFERENCE_DATE_START, date_end=REFERENCE_DATE_END
            ).isoformat()
            payment = random.randint(1, 5)
            care = random.randint(1, 5)
            compliance = random.randint(1, 5)
            rent_again = random.choices(['yes', 'no', 'maybe'], weights=[0.5, 0.2, 0.3])[0]
            comment = random.choice(comments_pool)
            references.append((ref_id, app_id, landlord, ref_date, payment, care, compliance, rent_again, comment))
            ref_id += 1
    return references


def generate_workspace_files(workspace, rent_info, applicants, references):
    os.makedirs(workspace, exist_ok=True)

    n_applicants = len(applicants)
    n_scalable = SCALE["num_workspace_files"]

    # Split scalable files: ~50% financial JSON, ~25% rental CSV, ~25% reference TXT
    n_financial = max(1, n_scalable // 2)
    n_property = max(1, (n_scalable - n_financial) // 2)
    n_ref_notes = max(1, n_scalable - n_financial - n_property)

    # --- Applicant financial JSON files ---
    financial_data = []
    for app in applicants:
        app_id = app[0]
        emp_type = random.choice(['full-time', 'part-time', 'self-employed', 'contract', 'retired'])
        income_map = {
            'full-time': (3000, 12000),
            'part-time': (1500, 4000),
            'self-employed': (2000, 15000),
            'contract': (2500, 10000),
            'retired': (2000, 5000),
        }
        lo, hi = income_map[emp_type]
        monthly_income = round(random.uniform(lo, hi), 2)
        additional_income = round(random.choice([0, 0, 0, random.uniform(200, 2000)]), 2)

        financial_data.append({
            "applicant_id": app_id,
            "monthly_income": monthly_income,
            "additional_income": additional_income,
            "employment_type": emp_type,
            "employer": fake.company(),
            "months_employed": random.randint(3, 120),
        })

    _write_chunks_json(financial_data, n_financial, workspace, "applicant_income")

    # --- Rental listings CSV files ---
    rent_df = pd.DataFrame(rent_info)
    _write_chunks_csv(rent_df, n_property, workspace, "rental_listings")

    # --- Reference verification TXT files ---
    ref_verifications = []
    for ref in references:
        ref_id, app_id = ref[0], ref[1]
        status = random.choices(['VERIFIED', 'UNVERIFIED'], weights=[0.75, 0.25])[0]
        ref_verifications.append((ref_id, app_id, status))

    _write_chunks_txt(ref_verifications, n_ref_notes, workspace, "reference_verification")

    # --- Fixed (non-scaling) workspace files ---

    # Risk scoring configuration (YAML)
    risk_config = {
        "weights": {
            "credit": 0.30,
            "income_ratio": 0.25,
            "eviction": 0.25,
            "references": 0.20,
        },
        "credit_scoring": {
            "base_threshold": 750,
            "score_range": 450,
            "bankruptcy_penalty": 15,
            "delinquency_penalty_per_item": 5,
            "max_delinquency_penalty": 20,
            "high_utilization_threshold": 0.50,
            "high_utilization_penalty": 10,
        },
        "income_ratio": {
            "minimum_ratio": 3.0,
        },
        "eviction_scoring": {
            "recency_years": 5,
            "recency_multiplier": 1.5,
            "base_scale_factor": 25,
        },
        "reference_scoring": {
            "no_references_score": 50,
            "would_not_rent_again_penalty": 15,
            "uncertain_recommendation_penalty": 8,
        },
        "review_threshold": 40,
        "reference_date": "2026-01-01",
        "risk_tiers": {
            "Critical": 75,
            "High": 55,
            "Moderate": 35,
            "Low": 0,
        },
    }
    with open(os.path.join(workspace, "risk_config.yaml"), 'w') as f:
        yaml.dump(risk_config, f, default_flow_style=False, sort_keys=False)

    # Eviction severity weights (CSV)
    severity_data = pd.DataFrame({
        'reason': ['nonpayment', 'property_damage', 'lease_violation', 'illegal_activity', 'nuisance'],
        'severity_weight': [0.8, 0.7, 0.6, 1.0, 0.5],
    })
    severity_data.to_csv(os.path.join(workspace, "eviction_severity.csv"), index=False)

    # Screening guidelines (MD)
    guidelines = """# Rental Applicant Screening Guidelines

## Overview
All rental applicants must undergo a comprehensive risk assessment before approval.
The screening process evaluates four primary dimensions: creditworthiness, income
stability relative to rent obligations, eviction history, and landlord reference patterns.

## Credit Assessment
The credit component measures financial reliability. Applicants with scores below the
base threshold receive escalating risk points. Additional penalties apply for bankruptcy
filings, delinquent accounts, and high credit utilization rates. The credit risk sub-score
is computed as a percentage of the maximum possible risk, with all penalty items added
and the total capped at 100.

## Income-to-Rent Evaluation
The income-to-rent ratio is calculated using the applicant's total monthly income
(base salary plus any additional income sources) divided by the monthly rent of the
applied property. Ratios below the configured minimum threshold indicate financial
strain. The sub-score scales linearly from 0 (at or above the threshold) to a maximum
when income barely covers rent.

## Eviction History Analysis
Each eviction record contributes to the risk score based on its severity classification
and recency. Recent evictions within the configured window receive a higher multiplier.
The eviction sub-score is the sum of all weighted eviction contributions, scaled by the
base scale factor and capped at 100.

## Landlord Reference Evaluation
References are evaluated based on average ratings across payment timeliness, property
care, and lease compliance. Only verified references should be included in the score
calculation. Negative and uncertain rental recommendations incur additional penalties.
Applicants with no verified references receive a default risk score for this component.

## Risk Classification
The final risk score is a weighted combination of all four component scores. Applicants
are classified into tiers based on their total risk score, and those exceeding the review
threshold are placed in the prioritized review queue.
"""
    with open(os.path.join(workspace, "screening_guidelines.md"), 'w') as f:
        f.write(guidelines)


def _write_chunks_json(data, n_files, workspace, prefix):
    chunk_size = max(1, len(data) // n_files)
    for i in range(n_files):
        start = i * chunk_size
        chunk = data[start:] if i == n_files - 1 else data[start:start + chunk_size]
        with open(os.path.join(workspace, f"{prefix}_{i + 1}.json"), 'w') as f:
            json.dump(chunk, f, indent=2)


def _write_chunks_csv(df, n_files, workspace, prefix):
    chunk_size = max(1, len(df) // n_files)
    for i in range(n_files):
        start = i * chunk_size
        chunk = df.iloc[start:] if i == n_files - 1 else df.iloc[start:start + chunk_size]
        chunk.to_csv(os.path.join(workspace, f"{prefix}_{i + 1}.csv"), index=False)


def _write_chunks_txt(records, n_files, workspace, prefix):
    chunk_size = max(1, len(records) // n_files)
    for i in range(n_files):
        start = i * chunk_size
        chunk = records[start:] if i == n_files - 1 else records[start:start + chunk_size]
        with open(os.path.join(workspace, f"{prefix}_{i + 1}.txt"), 'w') as f:
            for ref_id, app_id, status in chunk:
                f.write(f"Reference ID: {ref_id} | Applicant ID: {app_id} | Verification: {status}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db_path', required=True)
    parser.add_argument('--workspace', required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n_rows = SCALE["rows_per_table"]
    n_properties = max(10, n_rows // 4)

    # Generate data
    prop_db_rows, rent_info = generate_properties(n_properties)
    applicant_rows = generate_applicants(n_rows, n_properties)
    credit_rows = generate_credit_reports(n_rows)
    eviction_rows = generate_eviction_records(n_rows)
    reference_rows = generate_landlord_references(n_rows)

    # Insert into database
    cursor = conn.cursor()
    cursor.executemany("INSERT INTO properties VALUES (?, ?, ?, ?, ?)", prop_db_rows)
    cursor.executemany("INSERT INTO applicants VALUES (?, ?, ?, ?, ?, ?, ?, ?)", applicant_rows)
    cursor.executemany("INSERT INTO credit_reports VALUES (?, ?, ?, ?, ?, ?, ?, ?)", credit_rows)
    cursor.executemany("INSERT INTO eviction_records VALUES (?, ?, ?, ?, ?, ?, ?)", eviction_rows)
    cursor.executemany("INSERT INTO landlord_references VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", reference_rows)
    conn.commit()
    conn.close()

    # Generate workspace files
    generate_workspace_files(args.workspace, rent_info, applicant_rows, reference_rows)
    print(f"Generated database at {args.db_path}")
    print(f"Generated workspace at {args.workspace}")
    print(f"  - {n_rows} applicants, {n_properties} properties")
    print(f"  - {len(eviction_rows)} eviction records")
    print(f"  - {len(reference_rows)} landlord references")


if __name__ == '__main__':
    main()
