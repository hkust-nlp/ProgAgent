"""
Insurance Claims Fraud Investigation - Data Generation Script
Generates database and workspace files for fraud detection task.
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
from faker import Faker
from datetime import datetime, timedelta
import yaml

SCALE = {
    "rows_per_table": 120,
    "num_workspace_files": 20,
}

# ---- All random seeds pinned to 42 ----
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ---- Constants ----
SPECIALTIES = [
    "Orthopedics", "Cardiology", "Neurology", "General Practice",
    "Dermatology", "Radiology", "Physical Therapy", "Chiropractic",
    "Pain Management", "Emergency Medicine", "Internal Medicine",
    "Psychiatry", "Ophthalmology", "Urology", "Gastroenterology",
]

REGIONS = ["Northeast", "Southeast", "Midwest", "Southwest", "West", "Northwest"]

POLICY_TYPES = ["Basic", "Standard", "Premium", "Platinum"]

PROCEDURE_CATALOG = [
    ("Diagnostic Imaging", "Diagnostic"),
    ("Laboratory Tests", "Diagnostic"),
    ("Physical Examination", "Diagnostic"),
    ("Health Screening", "Diagnostic"),
    ("MRI Scan", "Diagnostic"),
    ("CT Scan", "Diagnostic"),
    ("X-Ray Imaging", "Diagnostic"),
    ("Ultrasound", "Diagnostic"),
    ("Physical Therapy Session", "Therapeutic"),
    ("Injection Therapy", "Therapeutic"),
    ("Medication Management", "Therapeutic"),
    ("Wound Care", "Therapeutic"),
    ("Occupational Therapy", "Therapeutic"),
    ("Chiropractic Adjustment", "Therapeutic"),
    ("Acupuncture Session", "Therapeutic"),
    ("Minor Surgery", "Surgical"),
    ("Arthroscopy", "Surgical"),
    ("Endoscopy", "Surgical"),
    ("Biopsy", "Surgical"),
    ("Laparoscopy", "Surgical"),
    ("Specialist Consultation", "Consultation"),
    ("Follow-up Visit", "Consultation"),
    ("Telehealth Visit", "Consultation"),
    ("Second Opinion", "Consultation"),
    ("ER Visit", "Emergency"),
    ("Urgent Care", "Emergency"),
    ("Ambulance Transport", "Emergency"),
    ("Trauma Assessment", "Emergency"),
]

RED_FLAG_KEYWORDS = [
    "inconsistent statements",
    "pre-existing condition suspected",
    "unverified injury",
    "suspicious timing",
    "conflicting documentation",
    "exaggerated symptoms",
]

RED_FLAG_SENTENCES = {
    "inconsistent statements": [
        "Inconsistent statements were noted regarding the circumstances of the incident. ",
        "The claimant's account contained inconsistent statements compared to the initial report. ",
        "Multiple inconsistent statements were identified during the follow-up interview. ",
    ],
    "pre-existing condition suspected": [
        "Medical history suggests a pre-existing condition suspected to be relevant to this claim. ",
        "Records indicate a pre-existing condition suspected of contributing to the reported symptoms. ",
        "A pre-existing condition suspected to predate the policy was noted in external medical records. ",
    ],
    "unverified injury": [
        "The reported injury remains an unverified injury based on available medical evidence. ",
        "Physical examination results were inconclusive, leaving an unverified injury on record. ",
        "Independent medical review flagged an unverified injury requiring further assessment. ",
    ],
    "suspicious timing": [
        "The claim filing exhibits suspicious timing relative to policy activation. ",
        "Suspicious timing was noted between the reported incident and the medical visit. ",
        "The sequence of events shows suspicious timing that warrants further review. ",
    ],
    "conflicting documentation": [
        "Conflicting documentation was found between provider records and claimant statements. ",
        "The file contains conflicting documentation regarding treatment dates. ",
        "Conflicting documentation between the police report and medical records was identified. ",
    ],
    "exaggerated symptoms": [
        "Clinical assessment suggests exaggerated symptoms beyond what imaging supports. ",
        "The treating physician noted potentially exaggerated symptoms in their evaluation. ",
        "Functional capacity evaluation indicates exaggerated symptoms relative to objective findings. ",
    ],
}

OBSERVATION_TEMPLATES = [
    "The claimant was interviewed at their residence. {flags}The overall demeanor appeared {demeanor}.",
    "A field visit was conducted at the reported incident location. {flags}Documentation provided was {doc_quality}.",
    "The claimant provided medical records for review. {flags}The treatment timeline {timeline_note}.",
    "Surveillance was conducted over a {duration}-day period. {flags}Activity levels observed were {activity}.",
    "Witness interviews were conducted in the surrounding area. {flags}Corroborating evidence was {evidence_status}.",
    "Medical records from the treating provider were reviewed. {flags}The diagnosis {diagnosis_note}.",
]


# ---- Database schema ----
def create_database(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS claimants (
            claimant_id TEXT PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            date_of_birth TEXT NOT NULL,
            address TEXT NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            zip_code TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS providers (
            provider_id TEXT PRIMARY KEY,
            provider_name TEXT NOT NULL,
            specialty TEXT NOT NULL,
            license_number TEXT NOT NULL,
            address TEXT NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            region TEXT NOT NULL,
            phone TEXT NOT NULL,
            npi_number TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS policies (
            policy_id TEXT PRIMARY KEY,
            claimant_id TEXT NOT NULL,
            policy_type TEXT NOT NULL,
            coverage_amount REAL NOT NULL,
            premium_monthly REAL NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (claimant_id) REFERENCES claimants(claimant_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            claim_id TEXT PRIMARY KEY,
            policy_id TEXT NOT NULL,
            claimant_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            procedure_code TEXT NOT NULL,
            diagnosis_code TEXT NOT NULL,
            claim_amount REAL NOT NULL,
            claim_date TEXT NOT NULL,
            status TEXT NOT NULL,
            description TEXT NOT NULL,
            FOREIGN KEY (policy_id) REFERENCES policies(policy_id),
            FOREIGN KEY (claimant_id) REFERENCES claimants(claimant_id),
            FOREIGN KEY (provider_id) REFERENCES providers(provider_id),
            FOREIGN KEY (procedure_code) REFERENCES billing_codes(code)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS billing_codes (
            code TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            expected_min REAL NOT NULL,
            expected_max REAL NOT NULL
        )
    """)
    conn.commit()


# ---- Data generators ----
def generate_claimants(conn, n):
    rows = []
    for i in range(n):
        rows.append({
            "claimant_id": f"CLT-{i+1:04d}",
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "date_of_birth": fake.date_of_birth(minimum_age=18, maximum_age=80).isoformat(),
            "address": fake.street_address(),
            "city": fake.city(),
            "state": fake.state_abbr(),
            "zip_code": fake.zipcode(),
            "phone": fake.phone_number(),
            "email": fake.email(),
        })
    pd.DataFrame(rows).to_sql("claimants", conn, if_exists="replace", index=False)
    return rows


def generate_providers(conn, n):
    rows = []
    for i in range(n):
        is_individual = random.random() < 0.7
        rows.append({
            "provider_id": f"PRV-{i+1:04d}",
            "provider_name": f"Dr. {fake.last_name()}" if is_individual else f"{fake.company()} Medical",
            "specialty": random.choice(SPECIALTIES),
            "license_number": f"LIC-{fake.bothify('??######').upper()}",
            "address": fake.street_address(),
            "city": fake.city(),
            "state": fake.state_abbr(),
            "region": random.choice(REGIONS),
            "phone": fake.phone_number(),
            "npi_number": f"NPI-{random.randint(1000000000, 9999999999)}",
        })
    pd.DataFrame(rows).to_sql("providers", conn, if_exists="replace", index=False)
    return rows


def generate_billing_codes(conn, n):
    rows = []
    for idx, (desc, cat) in enumerate(PROCEDURE_CATALOG):
        base_min = random.randint(80, 600)
        base_max = base_min + random.randint(200, 1800)
        rows.append({
            "code": f"CPT-{10000+idx}",
            "description": desc,
            "category": cat,
            "expected_min": float(base_min),
            "expected_max": float(base_max),
        })
    idx = len(PROCEDURE_CATALOG)
    while len(rows) < n:
        base_min = random.randint(80, 800)
        base_max = base_min + random.randint(200, 2000)
        rows.append({
            "code": f"CPT-{10000+idx}",
            "description": f"Specialized Procedure {idx - len(PROCEDURE_CATALOG) + 1}",
            "category": random.choice(["Diagnostic", "Therapeutic", "Surgical", "Consultation", "Emergency"]),
            "expected_min": float(base_min),
            "expected_max": float(base_max),
        })
        idx += 1
    pd.DataFrame(rows).to_sql("billing_codes", conn, if_exists="replace", index=False)
    return rows


def generate_policies(conn, n, claimants):
    rows = []
    for i in range(n):
        claimant = claimants[i % len(claimants)]
        ptype = random.choice(POLICY_TYPES)
        cov_ranges = {
            "Basic": (10000, 50000),
            "Standard": (50000, 150000),
            "Premium": (150000, 500000),
            "Platinum": (500000, 1000000),
        }
        lo, hi = cov_ranges[ptype]
        coverage = round(random.uniform(lo, hi), 2)
        if random.random() < 0.15:
            start = fake.date_between(start_date="-55d", end_date="-5d")
        else:
            start = fake.date_between(start_date="-5y", end_date="-120d")
        end = start + timedelta(days=365)
        premium = round(coverage * random.uniform(0.003, 0.012), 2)
        status = "active" if end >= datetime.now().date() else "expired"
        if random.random() < 0.05:
            status = "cancelled"
        rows.append({
            "policy_id": f"POL-{i+1:04d}",
            "claimant_id": claimant["claimant_id"],
            "policy_type": ptype,
            "coverage_amount": coverage,
            "premium_monthly": premium,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "status": status,
        })
    pd.DataFrame(rows).to_sql("policies", conn, if_exists="replace", index=False)
    return rows


def generate_claims(conn, n, policies, providers, billing_codes):
    """Generate n claims with weighted policy assignment for claimant concentration."""
    rows = []
    n_policies = len(policies)

    # Power-law weights so some claimants accumulate multiple claims
    weights = np.array([1.0 / (i + 1) ** 0.5 for i in range(n_policies)])
    weights /= weights.sum()
    policy_indices = np.random.choice(n_policies, size=n, p=weights)

    # ~25 % under_investigation
    investigation_set = set(random.sample(range(n), max(n // 4, 5)))

    # Identify concentrated claimants for date clustering
    from collections import Counter
    idx_counts = Counter(policy_indices.tolist())
    concentrated = {p for p, c in idx_counts.items() if c >= 3}

    diag_prefixes = list("MSGIIJKRZ")

    for i in range(n):
        pidx = int(policy_indices[i])
        policy = policies[pidx]
        provider = random.choice(providers)
        bcode = random.choice(billing_codes)

        status = "under_investigation" if i in investigation_set else random.choice(
            ["approved", "approved", "approved", "pending", "denied"]
        )

        exp_min, exp_max = bcode["expected_min"], bcode["expected_max"]
        if status == "under_investigation" and random.random() < 0.40:
            claim_amount = round(exp_max * random.uniform(1.35, 2.2), 2)
        else:
            claim_amount = round(random.uniform(exp_min, exp_max), 2)

        policy_start = datetime.fromisoformat(policy["start_date"]).date()
        if pidx in concentrated and random.random() < 0.65:
            claim_date = fake.date_between(start_date="-80d", end_date="-5d")
        else:
            earliest = max(policy_start, datetime.now().date() - timedelta(days=730))
            claim_date = fake.date_between(start_date=earliest, end_date="-5d")

        dp = random.choice(diag_prefixes)
        dn = random.randint(10, 99)
        rows.append({
            "claim_id": f"CLM-{i+1:04d}",
            "policy_id": policy["policy_id"],
            "claimant_id": policy["claimant_id"],
            "provider_id": provider["provider_id"],
            "procedure_code": bcode["code"],
            "diagnosis_code": f"{dp}{dn}.{random.randint(0,9)}",
            "claim_amount": claim_amount,
            "claim_date": claim_date.isoformat(),
            "status": status,
            "description": fake.sentence(nb_words=10),
        })

    pd.DataFrame(rows).to_sql("claims", conn, if_exists="replace", index=False)
    return rows


# ---- Workspace generators ----
def generate_adjuster_reports(workspace, claims, claimants, scale):
    """Write adjuster field reports covering all under_investigation claims."""
    under_inv = [c for c in claims if c["status"] == "under_investigation"]
    claimant_map = {c["claimant_id"]: c for c in claimants}

    num_files = max(int(scale["num_workspace_files"] * 0.7), 1)

    buckets = [[] for _ in range(num_files)]
    for idx, claim in enumerate(under_inv):
        buckets[idx % num_files].append(claim)

    rng = random.Random(42)

    for fi in range(num_files):
        adjuster_name = fake.name()
        report_date = fake.date_between(start_date="-30d", end_date="-1d").isoformat()

        lines = [
            f"# Field Investigation Report - Batch {fi+1:02d}",
            "",
            f"Report Date: {report_date}",
            f"Assigned Adjuster: {adjuster_name}",
            f"Cases in Batch: {len(buckets[fi])}",
            "",
            "---",
            "",
        ]

        if not buckets[fi]:
            lines.append("No active investigations assigned to this batch.")
            lines.append("")
        else:
            for claim in buckets[fi]:
                ct = claimant_map.get(claim["claimant_id"], {})
                cname = f"{ct.get('first_name','Unknown')} {ct.get('last_name','Unknown')}"
                lines.append(f"## Claim {claim['claim_id']}")
                lines.append("")
                lines.append(f"Claimant: {cname}")
                lines.append(f"Claim Date: {claim['claim_date']}")
                lines.append(f"Provider: {claim['provider_id']}")
                lines.append(f"Amount: ${claim['claim_amount']:,.2f}")
                lines.append("")

                flags_text = ""
                for kw in RED_FLAG_KEYWORDS:
                    if rng.random() < 0.30:
                        flags_text += rng.choice(RED_FLAG_SENTENCES[kw])

                template = rng.choice(OBSERVATION_TEMPLATES)
                obs = template.format(
                    flags=flags_text,
                    demeanor=rng.choice(["cooperative", "evasive", "anxious", "calm", "defensive"]),
                    doc_quality=rng.choice(["complete", "incomplete", "inconsistent", "thorough"]),
                    timeline_note=rng.choice(["appears consistent", "has minor gaps", "raises questions", "is well-documented"]),
                    duration=rng.randint(2, 7),
                    activity=rng.choice(["consistent with reported limitations", "somewhat inconsistent with claims", "within expected range", "notably unrestricted"]),
                    evidence_status=rng.choice(["limited", "sufficient", "contradictory", "unavailable", "strong"]),
                    diagnosis_note=rng.choice(["is consistent with the reported mechanism", "appears standard for the procedure", "requires additional verification", "is well-supported by imaging"]),
                )
                lines.append("### Observations")
                lines.append("")
                lines.append(obs)
                lines.append("")
                lines.append("---")
                lines.append("")

        path = os.path.join(workspace, f"adjuster_report_{fi+1:02d}.md")
        with open(path, "w") as f:
            f.write("\n".join(lines))


def generate_provider_audits(workspace, providers, claims, scale):
    """Write provider audit JSON files with billing deviation stats."""
    num_adjuster = max(int(scale["num_workspace_files"] * 0.7), 1)
    num_audits = max(scale["num_workspace_files"] - num_adjuster, 1)

    prov_claims = {}
    for c in claims:
        prov_claims.setdefault(c["provider_id"], []).append(c)

    buckets = [[] for _ in range(num_audits)]
    for idx, prov in enumerate(providers):
        buckets[idx % num_audits].append(prov)

    rng = random.Random(4242)

    for fi in range(num_audits):
        audit_date = fake.date_between(start_date="-90d", end_date="-10d").isoformat()
        entries = []
        for prov in buckets[fi]:
            pid = prov["provider_id"]
            n_reviewed = len(prov_claims.get(pid, []))
            dev = round(rng.uniform(2.0, 55.0), 1)
            flagged = max(0, int(n_reviewed * dev / 100))
            entries.append({
                "provider_id": pid,
                "provider_name": prov["provider_name"],
                "specialty": prov["specialty"],
                "total_claims_reviewed": n_reviewed,
                "flagged_claims_count": flagged,
                "avg_claim_deviation_pct": dev,
                "notes": rng.choice([
                    "Billing patterns within normal range",
                    "Minor billing irregularities noted",
                    "Elevated billing rates compared to peers",
                    "Significant deviation from expected billing patterns",
                    "Under continued monitoring",
                    "No concerns identified",
                ]),
            })
        data = {
            "audit_batch": f"{fi+1:02d}",
            "audit_date": audit_date,
            "audit_period": "Last 12 months",
            "providers": entries,
        }
        path = os.path.join(workspace, f"provider_audit_{fi+1:02d}.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


def generate_config_files(workspace):
    """Write fixed configuration files (not scaled by num_workspace_files)."""
    rules = {
        "scoring_weights": {
            "amount_anomaly": 25,
            "rapid_claims": 20,
            "provider_risk": 15,
            "new_policy": 15,
            "adjuster_flags": 15,
            "coverage_ratio": 10,
        },
        "thresholds": {
            "amount_deviation_pct": 30,
            "rapid_claims_window_days": 90,
            "rapid_claims_min_count": 3,
            "new_policy_max_days": 60,
            "coverage_ratio_min": 0.80,
        },
        "provider_risk_thresholds": {
            "critical": 40,
            "high": 25,
            "medium": 10,
        },
        "priority_tiers": {
            "critical": 70,
            "high": 50,
            "medium": 30,
        },
    }
    with open(os.path.join(workspace, "fraud_scoring_rules.yaml"), "w") as f:
        yaml.dump(rules, f, default_flow_style=False, sort_keys=False)

    adj = [
        {"region": "Northeast", "adjustment_factor": 1.25},
        {"region": "Southeast", "adjustment_factor": 0.90},
        {"region": "Midwest", "adjustment_factor": 0.95},
        {"region": "Southwest", "adjustment_factor": 1.00},
        {"region": "West", "adjustment_factor": 1.30},
        {"region": "Northwest", "adjustment_factor": 1.10},
    ]
    with open(os.path.join(workspace, "regional_cost_adjustments.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["region", "adjustment_factor"])
        writer.writeheader()
        writer.writerows(adj)


# ---- Main ----
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.db_path) or ".", exist_ok=True)
    os.makedirs(args.workspace, exist_ok=True)

    conn = sqlite3.connect(args.db_path)
    create_database(conn)

    n = SCALE["rows_per_table"]
    claimants = generate_claimants(conn, n)
    providers = generate_providers(conn, n)
    billing_codes = generate_billing_codes(conn, n)
    policies = generate_policies(conn, n, claimants)
    # Claims use 2x rows_per_table for claimant concentration (rapid-claims pattern)
    claims = generate_claims(conn, n * 2, policies, providers, billing_codes)

    conn.close()

    generate_adjuster_reports(args.workspace, claims, claimants, SCALE)
    generate_provider_audits(args.workspace, providers, claims, SCALE)
    generate_config_files(args.workspace)


if __name__ == "__main__":
    main()
