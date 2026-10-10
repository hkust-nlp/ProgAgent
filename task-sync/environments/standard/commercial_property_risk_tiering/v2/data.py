"""
Commercial Property Insurance Risk Assessment - Data Generation Script

Generates a SQLite database and workspace files for evaluating insurance
applications by cross-referencing permits, claims, sensors, and financials.
"""

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
    "rows_per_table": 120,
    "num_workspace_files": 24,
}

# ---------------------------------------------------------------------------
# Deterministic seeding
# ---------------------------------------------------------------------------
SEED = 42
fake = Faker()
Faker.seed(SEED)
np.random.seed(SEED)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REGIONS = [
    "NE-01", "NE-02", "SE-01", "SE-02", "MW-01",
    "MW-02", "SW-01", "SW-02", "NW-01", "NW-02",
]
CONSTRUCTION_TYPES = [
    "steel_frame", "reinforced_concrete", "masonry", "wood_frame", "mixed"
]
STRUCTURAL_GRADES = ["A", "B", "C", "D", "F"]
APPLICATION_STATUSES = [
    "pending_review", "approved", "rejected", "under_investigation"
]
STATUS_PROBS = [0.40, 0.30, 0.15, 0.15]
CLAIM_TYPES = ["flood", "fire"]
SENSOR_STATUSES = ["operational", "operational", "operational", "degraded"]
BUILDING_CONDITIONS = ["good", "fair", "poor"]
CREDIT_RATINGS = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC", "D"]
INDUSTRIES = [
    "Retail", "Manufacturing", "Technology", "Healthcare", "Hospitality",
    "Logistics", "Education", "Financial Services", "Food & Beverage",
    "Real Estate", "Construction", "Energy", "Telecommunications",
]


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------
def create_tables(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS applicants (
        applicant_id   TEXT PRIMARY KEY,
        company_name   TEXT NOT NULL,
        contact_email  TEXT NOT NULL,
        industry       TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS properties (
        property_id    TEXT PRIMARY KEY,
        applicant_id   TEXT NOT NULL,
        address        TEXT NOT NULL,
        region_code    TEXT NOT NULL,
        building_name  TEXT NOT NULL,
        FOREIGN KEY (applicant_id) REFERENCES applicants(applicant_id)
    );

    CREATE TABLE IF NOT EXISTS applications (
        application_id TEXT PRIMARY KEY,
        property_id    TEXT NOT NULL,
        applicant_id   TEXT NOT NULL,
        status         TEXT NOT NULL,
        requested_coverage REAL NOT NULL,
        submission_date TEXT NOT NULL,
        FOREIGN KEY (property_id)  REFERENCES properties(property_id),
        FOREIGN KEY (applicant_id) REFERENCES applicants(applicant_id)
    );

    CREATE TABLE IF NOT EXISTS building_permits (
        permit_id          TEXT PRIMARY KEY,
        property_id        TEXT NOT NULL,
        construction_type  TEXT NOT NULL,
        year_built         INTEGER NOT NULL,
        last_renovation_year INTEGER,
        fire_safety_rating INTEGER NOT NULL,
        structural_grade   TEXT NOT NULL,
        total_sqft         INTEGER NOT NULL,
        max_occupancy      INTEGER NOT NULL,
        FOREIGN KEY (property_id) REFERENCES properties(property_id)
    );

    CREATE TABLE IF NOT EXISTS claims_history (
        claim_id       TEXT PRIMARY KEY,
        region_code    TEXT NOT NULL,
        claim_type     TEXT NOT NULL,
        claim_amount   REAL NOT NULL,
        claim_year     INTEGER NOT NULL,
        severity       INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS occupancy_sensors (
        reading_id         TEXT PRIMARY KEY,
        property_id        TEXT NOT NULL,
        reading_date       TEXT NOT NULL,
        avg_occupancy_pct  REAL NOT NULL,
        peak_occupancy_pct REAL NOT NULL,
        sensor_status      TEXT NOT NULL,
        FOREIGN KEY (property_id) REFERENCES properties(property_id)
    );

    CREATE TABLE IF NOT EXISTS financial_scores (
        score_id        TEXT PRIMARY KEY,
        applicant_id    TEXT NOT NULL,
        assessment_date TEXT NOT NULL,
        credit_rating   TEXT NOT NULL,
        liquidity_ratio REAL NOT NULL,
        stability_score INTEGER NOT NULL,
        debt_ratio      REAL NOT NULL,
        FOREIGN KEY (applicant_id) REFERENCES applicants(applicant_id)
    );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Data generation helpers
# ---------------------------------------------------------------------------

def _gen_applicants(n: int) -> pd.DataFrame:
    rows = []
    for i in range(n):
        rows.append({
            "applicant_id": f"APP-{i+1:04d}",
            "company_name": fake.company(),
            "contact_email": fake.company_email(),
            "industry": INDUSTRIES[i % len(INDUSTRIES)],
        })
    return pd.DataFrame(rows)


def _gen_properties(n: int, applicant_ids: list) -> pd.DataFrame:
    rows = []
    for i in range(n):
        aid = applicant_ids[i % len(applicant_ids)]
        rows.append({
            "property_id": f"PROP-{i+1:04d}",
            "applicant_id": aid,
            "address": fake.address().replace("\n", ", "),
            "region_code": REGIONS[i % len(REGIONS)],
            "building_name": f"{fake.last_name()} {np.random.choice(['Tower', 'Plaza', 'Center', 'Complex', 'Building', 'Park'])}",
        })
    return pd.DataFrame(rows)


def _gen_applications(n: int, property_ids: list, applicant_ids: list) -> pd.DataFrame:
    rows = []
    statuses = np.random.choice(APPLICATION_STATUSES, size=n, p=STATUS_PROBS)
    for i in range(n):
        pid = property_ids[i % len(property_ids)]
        aid = applicant_ids[i % len(applicant_ids)]
        cov = int(np.random.choice([1, 2, 3, 5, 8, 10, 15, 20, 25, 30]) * 1_000_000)
        date = fake.date_between(start_date="-2y", end_date="today")
        rows.append({
            "application_id": f"APPL-{i+1:04d}",
            "property_id": pid,
            "applicant_id": aid,
            "status": statuses[i],
            "requested_coverage": float(cov),
            "submission_date": date.isoformat(),
        })
    return pd.DataFrame(rows)


def _gen_building_permits(property_ids: list) -> pd.DataFrame:
    n = len(property_ids)
    rows = []
    for i in range(n):
        yb = int(np.random.randint(1960, 2023))
        lr = int(np.random.randint(yb, 2026)) if np.random.random() > 0.3 else None
        rows.append({
            "permit_id": f"PERM-{i+1:04d}",
            "property_id": property_ids[i],
            "construction_type": str(np.random.choice(CONSTRUCTION_TYPES)),
            "year_built": yb,
            "last_renovation_year": lr,
            "fire_safety_rating": int(np.random.randint(1, 6)),
            "structural_grade": str(np.random.choice(STRUCTURAL_GRADES, p=[0.15, 0.30, 0.30, 0.15, 0.10])),
            "total_sqft": int(np.random.randint(5000, 200001)),
            "max_occupancy": int(np.random.randint(50, 2001)),
        })
    return pd.DataFrame(rows)


def _gen_claims(n: int) -> pd.DataFrame:
    rows = []
    for i in range(n):
        rows.append({
            "claim_id": f"CLM-{i+1:05d}",
            "region_code": str(np.random.choice(REGIONS)),
            "claim_type": str(np.random.choice(CLAIM_TYPES)),
            "claim_amount": round(float(np.random.uniform(10000, 5000000)), 2),
            "claim_year": int(np.random.randint(2016, 2026)),
            "severity": int(np.random.randint(1, 11)),
        })
    return pd.DataFrame(rows)


def _gen_occupancy_sensors(n: int, property_ids: list) -> pd.DataFrame:
    rows = []
    for i in range(n):
        pid = property_ids[i % len(property_ids)]
        avg_occ = round(float(np.random.uniform(10, 95)), 1)
        peak = round(float(min(avg_occ + np.random.uniform(5, 30), 100.0)), 1)
        rows.append({
            "reading_id": f"SNS-{i+1:05d}",
            "property_id": pid,
            "reading_date": fake.date_between(start_date="-6m", end_date="today").isoformat(),
            "avg_occupancy_pct": avg_occ,
            "peak_occupancy_pct": peak,
            "sensor_status": str(np.random.choice(SENSOR_STATUSES)),
        })
    return pd.DataFrame(rows)


def _gen_financial_scores(applicant_ids: list) -> pd.DataFrame:
    n = len(applicant_ids)
    rows = []
    for i in range(n):
        stab = int(np.random.randint(15, 100))
        debt = round(float(np.random.uniform(0.1, 0.9)), 2)
        rows.append({
            "score_id": f"FIN-{i+1:04d}",
            "applicant_id": applicant_ids[i],
            "assessment_date": fake.date_between(start_date="-1y", end_date="today").isoformat(),
            "credit_rating": str(np.random.choice(CREDIT_RATINGS, p=[0.05, 0.10, 0.20, 0.25, 0.20, 0.10, 0.07, 0.03])),
            "liquidity_ratio": round(float(np.random.uniform(0.5, 4.0)), 2),
            "stability_score": stab,
            "debt_ratio": debt,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Workspace file generation
# ---------------------------------------------------------------------------

def _write_risk_scoring_rules(workspace: str):
    rules = {
        "version": "2.1",
        "components": {
            "construction_risk": {
                "max_points": 25,
                "base_scores": {
                    "steel_frame": 3,
                    "reinforced_concrete": 5,
                    "masonry": 10,
                    "wood_frame": 18,
                    "mixed": 14,
                },
                "age_penalty_per_decade": 2,
                "age_reference_year": 2025,
                "fire_safety_bonus_per_point": -1,
                "structural_grade_penalty": {
                    "A": 0,
                    "B": 1,
                    "C": 3,
                    "D": 5,
                    "F": 7,
                },
                "formula": "construction_risk = clamp(base_score + floor((age_reference_year - year_built) / 10) * age_penalty_per_decade + fire_safety_rating * fire_safety_bonus_per_point + structural_grade_penalty, 0, max_points)",
            },
            "claims_risk": {
                "max_points": 25,
                "flood_severity_weight": 1.5,
                "fire_severity_weight": 2.0,
                "dual_peril_bonus": 3,
                "note": "Use average severity of each claim type in the region (claim_year from 2016 to 2025 inclusive). Score = min(round(avg_flood_severity * flood_severity_weight + avg_fire_severity * fire_severity_weight + dual_peril_bonus_if_both_types_present), max_points). If no claims of a type exist in the region, treat that type contribution as 0. The dual peril bonus applies only when both flood and fire claims are present.",
            },
            "occupancy_risk": {
                "max_points": 20,
                "avg_occupancy_brackets": [
                    {"max_pct": 30, "score": 4},
                    {"max_pct": 50, "score": 8},
                    {"max_pct": 70, "score": 12},
                    {"max_pct": 85, "score": 16},
                    {"max_pct": 100, "score": 20},
                ],
                "degraded_sensor_penalty": 3,
                "note": "Compute the mean of avg_occupancy_pct across all sensor readings for the property. Find the first bracket where mean <= max_pct and use that score. Add degraded_sensor_penalty if ANY reading for the property has sensor_status equal to degraded. Clamp final value to [0, max_points].",
            },
            "financial_risk": {
                "max_points": 15,
                "formula": "base = round((100 - stability_score) * 15 / 100). Add 3 if debt_ratio > 0.60. Clamp result to [0, max_points].",
            },
            "environmental_risk": {
                "max_points": 15,
                "flood_proximity_brackets": [
                    {"max_distance_m": 500, "score": 6},
                    {"max_distance_m": 1500, "score": 4},
                    {"max_distance_m": 3000, "score": 2},
                    {"max_distance_m": 999999, "score": 0},
                ],
                "fire_station_brackets": [
                    {"max_km": 3, "score": 0},
                    {"max_km": 5, "score": 1},
                    {"max_km": 8, "score": 3},
                    {"max_km": 999, "score": 5},
                ],
                "condition_scores": {
                    "good": 0,
                    "fair": 2,
                    "poor": 4,
                },
                "note": "Sum flood_proximity score + fire_station score + condition score. Clamp to [0, max_points]. These values come from the property assessment batch files.",
            },
        },
        "total_max": 100,
        "tier_mapping": [
            {"tier_code": "T1", "label": "Low", "min_score": 0, "max_score": 24},
            {"tier_code": "T2", "label": "Medium", "min_score": 25, "max_score": 49},
            {"tier_code": "T3", "label": "High", "min_score": 50, "max_score": 74},
            {"tier_code": "T4", "label": "Critical", "min_score": 75, "max_score": 100},
        ],
    }
    path = os.path.join(workspace, "risk_scoring_rules.yaml")
    with open(path, "w") as f:
        yaml.dump(rules, f, default_flow_style=False, sort_keys=False)


def _write_premium_schedule(workspace: str):
    schedule = {
        "tier_base_rate_per_million": {
            "T1": 1200,
            "T2": 2500,
            "T3": 4800,
            "T4": 8500,
        },
        "construction_multiplier": {
            "steel_frame": 0.85,
            "reinforced_concrete": 0.90,
            "masonry": 1.00,
            "wood_frame": 1.25,
            "mixed": 1.10,
        },
        "stability_discount": {
            "min_stability_score": 80,
            "discount_pct": 5,
        },
        "calculation_steps": [
            "1. base = tier_base_rate_per_million[tier_code] * (recommended_coverage / 1000000)",
            "2. base = base * construction_multiplier[construction_type]",
            "3. base = base * (1 + risk_score / 200)",
            "4. if stability_score >= 80 then base = base * 0.95",
            "5. annual_premium = round(base, 2)",
        ],
    }
    path = os.path.join(workspace, "premium_schedule.json")
    with open(path, "w") as f:
        json.dump(schedule, f, indent=2)


def _write_coverage_matrix(workspace: str):
    """Coverage limits by tier and construction type (in millions USD)."""
    matrix = [
        {"tier_code": "T1", "construction_type": "steel_frame", "max_coverage_millions": 50},
        {"tier_code": "T1", "construction_type": "reinforced_concrete", "max_coverage_millions": 45},
        {"tier_code": "T1", "construction_type": "masonry", "max_coverage_millions": 35},
        {"tier_code": "T1", "construction_type": "wood_frame", "max_coverage_millions": 25},
        {"tier_code": "T1", "construction_type": "mixed", "max_coverage_millions": 30},
        {"tier_code": "T2", "construction_type": "steel_frame", "max_coverage_millions": 40},
        {"tier_code": "T2", "construction_type": "reinforced_concrete", "max_coverage_millions": 35},
        {"tier_code": "T2", "construction_type": "masonry", "max_coverage_millions": 25},
        {"tier_code": "T2", "construction_type": "wood_frame", "max_coverage_millions": 18},
        {"tier_code": "T2", "construction_type": "mixed", "max_coverage_millions": 22},
        {"tier_code": "T3", "construction_type": "steel_frame", "max_coverage_millions": 30},
        {"tier_code": "T3", "construction_type": "reinforced_concrete", "max_coverage_millions": 25},
        {"tier_code": "T3", "construction_type": "masonry", "max_coverage_millions": 18},
        {"tier_code": "T3", "construction_type": "wood_frame", "max_coverage_millions": 12},
        {"tier_code": "T3", "construction_type": "mixed", "max_coverage_millions": 15},
        {"tier_code": "T4", "construction_type": "steel_frame", "max_coverage_millions": 20},
        {"tier_code": "T4", "construction_type": "reinforced_concrete", "max_coverage_millions": 18},
        {"tier_code": "T4", "construction_type": "masonry", "max_coverage_millions": 12},
        {"tier_code": "T4", "construction_type": "wood_frame", "max_coverage_millions": 8},
        {"tier_code": "T4", "construction_type": "mixed", "max_coverage_millions": 10},
    ]
    path = os.path.join(workspace, "coverage_matrix.csv")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["tier_code", "construction_type", "max_coverage_millions"])
        writer.writeheader()
        writer.writerows(matrix)


def _write_underwriting_policy(workspace: str):
    policy = """\
Underwriting Policy Document -- Commercial Property Division
Revision 4.3, effective January 2025

This document governs the evaluation workflow for all pending commercial \
property insurance applications. Every application currently marked as \
pending review must be processed. Applications in any other status are \
excluded from the current evaluation cycle.

Eligibility Screening

Before computing a risk score or premium, each pending application must \
pass an eligibility gate. An application is declined when the applicant's \
most recent financial assessment shows a stability score strictly below 30 \
and, at the same time, a debt ratio strictly above 0.70. Both conditions \
must hold simultaneously for a decline. Declined applications must still \
appear in the final quote list but carry a status of DECLINED with no \
premium or coverage values.

Risk Score Calculation

A composite risk score ranging from 0 to 100 is assembled from five \
components. The detailed scoring brackets, weights, and formulas are \
specified in the risk scoring rules configuration file. In brief, the \
components are: construction characteristics drawn from permit records, \
historical claims experience for the property region, occupancy patterns \
from sensor telemetry, the applicant financial profile, and environmental \
factors documented in the property assessment files. Each component has a \
defined maximum contribution. After summing all components, clamp the total \
to the range zero through one hundred.

Tier Assignment

The risk score maps to one of four tiers as defined in the risk scoring \
rules configuration. Consult the tier mapping section of that file for the \
exact score boundaries and tier codes.

Recommended Coverage

The recommended coverage equals the lesser of the applicant requested \
coverage and the maximum permitted by the coverage matrix for the assigned \
tier and construction type combination. The coverage matrix is provided as \
a separate reference file. Coverage values are expressed in whole US dollars.

Premium Computation

The premium schedule configuration file contains the detailed calculation \
steps. The annual premium starts from the tier-specific base rate per \
million dollars of recommended coverage, scaled by the construction type \
multiplier and a risk-score loading factor. Applicants whose stability \
score meets the discount threshold receive a percentage discount as \
specified in the schedule. The final premium is rounded to exactly two \
decimal places.

Output Requirements

All results are recorded in a single file named quote_list.csv. The \
columns must appear in this exact order: application_id, company_name, \
property_address, region_code, risk_score, risk_tier, recommended_coverage, \
annual_premium, status. For quoted applications the status column reads \
QUOTED. For declined applications it reads DECLINED, and the \
recommended_coverage and annual_premium fields must be left empty. Rows \
must be sorted by risk_score in descending order; where two applications \
share the same risk_score, sort by application_id in ascending \
lexicographic order.

A companion file named risk_summary.json must contain the following keys: \
total_reviewed (integer count of all pending applications processed), \
declined_count (integer), quoted_count (integer), tier_distribution (an \
object mapping each tier code T1 through T4 to its count among quoted \
applications), average_premium (the arithmetic mean of annual premiums \
across quoted applications rounded to two decimal places), and \
total_recommended_coverage (sum of recommended coverage across quoted \
applications as an integer).
"""
    path = os.path.join(workspace, "underwriting_policy.md")
    with open(path, "w") as f:
        f.write(policy)


def _write_assessment_files(workspace: str, properties_df: pd.DataFrame, n_files: int):
    """Generate property assessment batch JSON files (scalable)."""
    n_props = len(properties_df)
    base_per_file = n_props // n_files
    remainder = n_props % n_files

    flood_distances = [150, 300, 500, 800, 1200, 1800, 2500, 3500, 5000, 8000, 12000, 15000]
    fire_station_kms = np.round(np.random.uniform(0.5, 14.0, size=n_props), 1)
    conditions = np.random.choice(BUILDING_CONDITIONS, size=n_props, p=[0.40, 0.40, 0.20])
    flood_dists = np.random.choice(flood_distances, size=n_props)

    idx = 0
    for file_i in range(n_files):
        count = base_per_file + (1 if file_i < remainder else 0)
        batch_props = properties_df.iloc[idx: idx + count]
        assessments = []
        for j, (_, prop) in enumerate(batch_props.iterrows()):
            global_j = idx + j
            assessments.append({
                "property_id": prop["property_id"],
                "flood_zone_distance_m": int(flood_dists[global_j]),
                "nearest_fire_station_km": float(fire_station_kms[global_j]),
                "building_condition": str(conditions[global_j]),
                "assessment_date": fake.date_between(start_date="-1y", end_date="today").isoformat(),
                "notes": f"Assessment for {prop['building_name']}. {fake.sentence()}",
            })
        filepath = os.path.join(workspace, f"property_assessment_batch_{file_i + 1}.json")
        with open(filepath, "w") as f:
            json.dump({"batch_id": file_i + 1, "assessments": assessments}, f, indent=2)
        idx += count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    db_path = args.db_path
    workspace = args.workspace
    os.makedirs(workspace, exist_ok=True)

    n = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # --- Generate dataframes ---
    applicants_df = _gen_applicants(n)
    properties_df = _gen_properties(n, applicants_df["applicant_id"].tolist())
    applications_df = _gen_applications(n, properties_df["property_id"].tolist(),
                                         applicants_df["applicant_id"].tolist())
    permits_df = _gen_building_permits(properties_df["property_id"].tolist())
    claims_df = _gen_claims(n * 3)  # ~3x for rich regional history
    sensors_df = _gen_occupancy_sensors(n * 2, properties_df["property_id"].tolist())
    financial_df = _gen_financial_scores(applicants_df["applicant_id"].tolist())

    # --- Write to database ---
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    applicants_df.to_sql("applicants", conn, if_exists="replace", index=False)
    properties_df.to_sql("properties", conn, if_exists="replace", index=False)
    applications_df.to_sql("applications", conn, if_exists="replace", index=False)
    permits_df.to_sql("building_permits", conn, if_exists="replace", index=False)
    claims_df.to_sql("claims_history", conn, if_exists="replace", index=False)
    sensors_df.to_sql("occupancy_sensors", conn, if_exists="replace", index=False)
    financial_df.to_sql("financial_scores", conn, if_exists="replace", index=False)
    conn.close()

    # --- Write fixed workspace config files ---
    _write_risk_scoring_rules(workspace)
    _write_premium_schedule(workspace)
    _write_coverage_matrix(workspace)
    _write_underwriting_policy(workspace)

    # --- Write scalable assessment files ---
    _write_assessment_files(workspace, properties_df, n_files)

    print(f"Database written to {db_path}")
    print(f"Workspace populated at {workspace}/ ({n_files} assessment files + 4 config files)")


if __name__ == "__main__":
    main()
