"""
Data generation for visa application triage task.
Generates a SQLite database and workspace files for cross-referencing
applicant biometric submissions, visa quotas, embassy appointment backlogs,
and document verification flags.
"""

import argparse
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yaml
from faker import Faker

# ── Scale parameters ──────────────────────────────────────────────────────────
SCALE = {
    "rows_per_table": 200,       # v1 = 2x base
    "num_workspace_files": 20,   # v1 = base + N
}

# ── Constants ─────────────────────────────────────────────────────────────────
REFERENCE_DATE = datetime(2026, 4, 22)
SEED = 42

VISA_CATEGORIES = ["diplomatic", "employment", "business", "student", "family_reunion", "tourist"]
PRIORITY_LEVELS = ["critical", "high", "medium", "low"]
EMBASSY_CODES = [
    "EMB_001", "EMB_002", "EMB_003", "EMB_004", "EMB_005",
    "EMB_006", "EMB_007", "EMB_008", "EMB_009", "EMB_010",
]
NATIONALITIES = [
    "United States", "China", "India", "Brazil", "Nigeria",
    "Germany", "Japan", "Mexico", "Philippines", "Egypt",
    "South Korea", "Turkey", "Indonesia", "Vietnam", "Pakistan",
]
BIO_TYPES = ["fingerprint", "iris_scan", "facial_photo"]
BIO_STATUSES = ["valid", "expired", "pending_review"]
DOC_TYPES = ["passport", "financial_statement", "employment_letter",
             "medical_certificate", "invitation_letter", "police_clearance"]
DOC_VERIFICATION_STATUSES = ["verified", "flagged", "pending", "rejected"]
DOC_FLAG_REASONS = [
    "inconsistent_dates", "missing_signature", "expired_document",
    "unverifiable_source", "translation_incomplete", "watermark_missing",
    "notarization_invalid", "format_non_compliant",
]
APPT_TYPES = ["interview", "biometric_capture", "document_submission", "final_review"]
APPT_STATUSES = ["completed", "scheduled", "missed", "cancelled", "pending"]
APP_STATUSES = ["pending", "in_review", "on_hold", "awaiting_documents", "approved", "denied"]
SPONSOR_TIERS = ["platinum", "gold", "silver", "none"]
SPECIAL_CIRCUMSTANCES = [
    "Medical emergency travel",
    "Diplomatic courtesy request",
    "Corporate relocation deadline",
    "Academic term start imminent",
    "Family reunification urgency",
    "Humanitarian grounds",
    None, None, None, None,  # 40% chance of no special circumstance
]

RECOMMENDED_ACTIONS = {
    "biometric_expired": "Schedule biometric renewal",
    "document_flags_unresolved": "Expedite document review",
    "sla_exceeded": "Escalate to senior case officer",
    "appointment_backlogged": "Fast-track appointment scheduling",
    "quota_critical": "Request quota reallocation",
}
STALL_REASON_PRIORITY = [
    "biometric_expired",
    "document_flags_unresolved",
    "sla_exceeded",
    "appointment_backlogged",
    "quota_critical",
]


def set_seeds():
    random.seed(SEED)
    np.random.seed(SEED)


def create_tables(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS applicants (
            applicant_id TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            nationality TEXT NOT NULL,
            visa_category TEXT NOT NULL,
            priority_level TEXT NOT NULL,
            embassy_id TEXT NOT NULL,
            submission_date TEXT NOT NULL,
            current_status TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS biometric_submissions (
            bio_id TEXT PRIMARY KEY,
            applicant_id TEXT NOT NULL,
            bio_type TEXT NOT NULL,
            capture_date TEXT NOT NULL,
            quality_score REAL NOT NULL,
            status TEXT NOT NULL,
            expiry_date TEXT NOT NULL,
            FOREIGN KEY (applicant_id) REFERENCES applicants(applicant_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS document_verifications (
            doc_id TEXT PRIMARY KEY,
            applicant_id TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            flag_reason TEXT,
            reviewer_id TEXT,
            verification_date TEXT,
            FOREIGN KEY (applicant_id) REFERENCES applicants(applicant_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS embassy_appointments (
            appt_id TEXT PRIMARY KEY,
            applicant_id TEXT NOT NULL,
            embassy_id TEXT NOT NULL,
            appointment_type TEXT NOT NULL,
            appointment_date TEXT,
            scheduled_date TEXT NOT NULL,
            status TEXT NOT NULL,
            wait_days INTEGER NOT NULL,
            FOREIGN KEY (applicant_id) REFERENCES applicants(applicant_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS visa_quotas (
            quota_id TEXT PRIMARY KEY,
            visa_category TEXT NOT NULL,
            embassy_id TEXT NOT NULL,
            fiscal_year INTEGER NOT NULL,
            quarter TEXT NOT NULL,
            allocated_quota INTEGER NOT NULL,
            used_count INTEGER NOT NULL
        )
    """)
    conn.commit()


def generate_applicants(fake, n):
    rows = []
    # Status distribution: ~60% active (can be stalled), 40% terminal
    status_weights = [0.22, 0.15, 0.12, 0.11, 0.25, 0.15]

    for i in range(n):
        app_id = f"APP_{i+1:05d}"
        name = fake.name()
        nationality = random.choice(NATIONALITIES)
        visa_cat = random.choice(VISA_CATEGORIES)
        priority = random.choices(
            PRIORITY_LEVELS,
            weights=[0.08, 0.22, 0.45, 0.25],
            k=1
        )[0]
        embassy = random.choice(EMBASSY_CODES)
        # Submission dates: 10-300 days ago
        days_ago = random.randint(10, 300)
        sub_date = (REFERENCE_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        status = random.choices(APP_STATUSES, weights=status_weights, k=1)[0]
        rows.append((app_id, name, nationality, visa_cat, priority, embassy, sub_date, status))
    return rows


def generate_biometrics(applicant_ids, n_per_table):
    rows = []
    bio_counter = 0
    # Ensure at least one biometric per applicant, some get multiple
    for app_id in applicant_ids:
        num_bios = random.choices([1, 2, 3], weights=[0.5, 0.35, 0.15], k=1)[0]
        for _ in range(num_bios):
            bio_counter += 1
            bio_id = f"BIO_{bio_counter:05d}"
            bio_type = random.choice(BIO_TYPES)
            # Capture date: 5-400 days ago
            capture_days = random.randint(5, 400)
            capture_date = (REFERENCE_DATE - timedelta(days=capture_days)).strftime("%Y-%m-%d")
            quality = round(random.uniform(30, 100), 1)

            # Status and expiry logic
            validity_days = random.randint(180, 730)
            expiry_date_dt = datetime.strptime(capture_date, "%Y-%m-%d") + timedelta(days=validity_days)
            expiry_date = expiry_date_dt.strftime("%Y-%m-%d")

            if expiry_date_dt < REFERENCE_DATE:
                status = "expired"
            elif (expiry_date_dt - REFERENCE_DATE).days <= 30:
                status = random.choice(["valid", "pending_review"])
            else:
                status = random.choices(["valid", "pending_review"], weights=[0.85, 0.15], k=1)[0]

            rows.append((bio_id, app_id, bio_type, capture_date, quality, status, expiry_date))

    # Pad to meet minimum row count
    while len(rows) < n_per_table:
        bio_counter += 1
        bio_id = f"BIO_{bio_counter:05d}"
        app_id = random.choice(applicant_ids)
        bio_type = random.choice(BIO_TYPES)
        capture_days = random.randint(5, 400)
        capture_date = (REFERENCE_DATE - timedelta(days=capture_days)).strftime("%Y-%m-%d")
        quality = round(random.uniform(30, 100), 1)
        validity_days = random.randint(180, 730)
        expiry_date_dt = datetime.strptime(capture_date, "%Y-%m-%d") + timedelta(days=validity_days)
        expiry_date = expiry_date_dt.strftime("%Y-%m-%d")
        if expiry_date_dt < REFERENCE_DATE:
            status = "expired"
        elif (expiry_date_dt - REFERENCE_DATE).days <= 30:
            status = random.choice(["valid", "pending_review"])
        else:
            status = random.choices(["valid", "pending_review"], weights=[0.85, 0.15], k=1)[0]
        rows.append((bio_id, app_id, bio_type, capture_date, quality, status, expiry_date))

    return rows


def generate_document_verifications(applicant_ids, n_per_table):
    rows = []
    doc_counter = 0

    for app_id in applicant_ids:
        num_docs = random.choices([2, 3, 4, 5], weights=[0.2, 0.35, 0.3, 0.15], k=1)[0]
        chosen_types = random.sample(DOC_TYPES, min(num_docs, len(DOC_TYPES)))
        for doc_type in chosen_types:
            doc_counter += 1
            doc_id = f"DOC_{doc_counter:05d}"
            ver_status = random.choices(
                DOC_VERIFICATION_STATUSES,
                weights=[0.50, 0.20, 0.18, 0.12],
                k=1
            )[0]
            flag_reason = random.choice(DOC_FLAG_REASONS) if ver_status == "flagged" else None
            reviewer = f"REV_{random.randint(1, 20):03d}" if ver_status != "pending" else None
            ver_days = random.randint(1, 200)
            ver_date = (REFERENCE_DATE - timedelta(days=ver_days)).strftime("%Y-%m-%d") if ver_status != "pending" else None
            rows.append((doc_id, app_id, doc_type, ver_status, flag_reason, reviewer, ver_date))

    while len(rows) < n_per_table:
        doc_counter += 1
        doc_id = f"DOC_{doc_counter:05d}"
        app_id = random.choice(applicant_ids)
        doc_type = random.choice(DOC_TYPES)
        ver_status = random.choices(
            DOC_VERIFICATION_STATUSES,
            weights=[0.50, 0.20, 0.18, 0.12],
            k=1
        )[0]
        flag_reason = random.choice(DOC_FLAG_REASONS) if ver_status == "flagged" else None
        reviewer = f"REV_{random.randint(1, 20):03d}" if ver_status != "pending" else None
        ver_days = random.randint(1, 200)
        ver_date = (REFERENCE_DATE - timedelta(days=ver_days)).strftime("%Y-%m-%d") if ver_status != "pending" else None
        rows.append((doc_id, app_id, doc_type, ver_status, flag_reason, reviewer, ver_date))

    return rows


def generate_appointments(applicant_ids, n_per_table):
    rows = []
    appt_counter = 0

    for app_id in applicant_ids:
        num_appts = random.choices([1, 2, 3], weights=[0.45, 0.40, 0.15], k=1)[0]
        for _ in range(num_appts):
            appt_counter += 1
            appt_id = f"APPT_{appt_counter:05d}"
            embassy = random.choice(EMBASSY_CODES)
            appt_type = random.choice(APPT_TYPES)
            status = random.choices(
                APPT_STATUSES,
                weights=[0.30, 0.25, 0.10, 0.10, 0.25],
                k=1
            )[0]
            sched_days = random.randint(5, 250)
            scheduled_date = (REFERENCE_DATE - timedelta(days=sched_days)).strftime("%Y-%m-%d")
            if status == "completed":
                appt_date = (REFERENCE_DATE - timedelta(days=random.randint(1, sched_days))).strftime("%Y-%m-%d")
            elif status == "scheduled":
                appt_date = (REFERENCE_DATE + timedelta(days=random.randint(1, 90))).strftime("%Y-%m-%d")
            else:
                appt_date = None
            wait_days = random.randint(5, 120)
            rows.append((appt_id, app_id, embassy, appt_type, appt_date, scheduled_date, status, wait_days))

    while len(rows) < n_per_table:
        appt_counter += 1
        appt_id = f"APPT_{appt_counter:05d}"
        app_id = random.choice(applicant_ids)
        embassy = random.choice(EMBASSY_CODES)
        appt_type = random.choice(APPT_TYPES)
        status = random.choices(APPT_STATUSES, weights=[0.30, 0.25, 0.10, 0.10, 0.25], k=1)[0]
        sched_days = random.randint(5, 250)
        scheduled_date = (REFERENCE_DATE - timedelta(days=sched_days)).strftime("%Y-%m-%d")
        if status == "completed":
            appt_date = (REFERENCE_DATE - timedelta(days=random.randint(1, sched_days))).strftime("%Y-%m-%d")
        elif status == "scheduled":
            appt_date = (REFERENCE_DATE + timedelta(days=random.randint(1, 90))).strftime("%Y-%m-%d")
        else:
            appt_date = None
        wait_days = random.randint(5, 120)
        rows.append((appt_id, app_id, embassy, appt_type, appt_date, scheduled_date, status, wait_days))

    return rows


def generate_visa_quotas(n_per_table):
    rows = []
    quota_counter = 0
    quarters = ["Q1", "Q2", "Q3", "Q4"]

    for embassy in EMBASSY_CODES:
        for cat in VISA_CATEGORIES:
            for q in quarters:
                quota_counter += 1
                quota_id = f"QTA_{quota_counter:05d}"
                allocated = random.randint(50, 500)
                # Vary utilization: some near capacity
                util_pct = random.choices(
                    [random.uniform(0.3, 0.7), random.uniform(0.7, 0.89), random.uniform(0.90, 0.99)],
                    weights=[0.5, 0.3, 0.2],
                    k=1
                )[0]
                used = min(int(allocated * util_pct), allocated)
                rows.append((quota_id, cat, embassy, 2026, q, allocated, used))

    # Quota table is fully covered by the (embassy x category x quarter) grid.
    # Do not pad with duplicates: (visa_category, embassy_id, quarter) must be
    # unique so utilization lookups are deterministic.
    return rows


def insert_data(conn, applicants, biometrics, doc_vers, appointments, quotas):
    c = conn.cursor()
    c.executemany("INSERT INTO applicants VALUES (?,?,?,?,?,?,?,?)", applicants)
    c.executemany("INSERT INTO biometric_submissions VALUES (?,?,?,?,?,?,?)", biometrics)
    c.executemany("INSERT INTO document_verifications VALUES (?,?,?,?,?,?,?)", doc_vers)
    c.executemany("INSERT INTO embassy_appointments VALUES (?,?,?,?,?,?,?,?)", appointments)
    c.executemany("INSERT INTO visa_quotas VALUES (?,?,?,?,?,?,?)", quotas)
    conn.commit()


def generate_workspace(workspace, applicants):
    os.makedirs(workspace, exist_ok=True)

    # ── Fixed policy/config files ─────────────────────────────────────────
    # 1. Stall criteria
    stall_criteria = {
        "reference_date": REFERENCE_DATE.strftime("%Y-%m-%d"),
        "processing_time_threshold_multiplier": 1.5,
        "biometric_expiry_warning_days": 30,
        "min_unresolved_document_flags": 2,
        "appointment_wait_threshold_days": 45,
        "quota_utilization_critical_pct": 90
    }
    with open(os.path.join(workspace, "stall_criteria.json"), "w") as f:
        json.dump(stall_criteria, f, indent=2)

    # 2. Priority scoring rules
    priority_rules = {
        "base_scores": {
            "diplomatic": 100,
            "employment": 70,
            "business": 65,
            "student": 60,
            "family_reunion": 55,
            "tourist": 40,
        },
        "modifiers": {
            "escalation_multiplier": 0.15,
            "days_stalled_factor": 0.5,
            "quota_pressure_bonus": 20,
            "biometric_expiry_bonus": 15,
            "document_flag_penalty": -5,
            "sponsor_tier_bonus": {
                "platinum": 30,
                "gold": 20,
                "silver": 10,
                "none": 0,
            },
        },
        "priority_level_multiplier": {
            "critical": 2.0,
            "high": 1.5,
            "medium": 1.0,
            "low": 0.7,
        },
        "high_priority_conditions": {
            "priority_levels": ["critical", "high"],
            "min_escalation_level": 3,
            "sponsor_tiers": ["platinum"],
        },
        "stall_reason_action_mapping": {
            "biometric_expired": "Schedule biometric renewal",
            "document_flags_unresolved": "Expedite document review",
            "sla_exceeded": "Escalate to senior case officer",
            "appointment_backlogged": "Fast-track appointment scheduling",
            "quota_critical": "Request quota reallocation",
        },
        "stall_reason_priority_order": [
            "biometric_expired",
            "document_flags_unresolved",
            "sla_exceeded",
            "appointment_backlogged",
            "quota_critical",
        ],
    }
    with open(os.path.join(workspace, "priority_scoring_rules.yaml"), "w") as f:
        yaml.dump(priority_rules, f, default_flow_style=False, sort_keys=False)

    # 3. Visa processing standards
    standards = pd.DataFrame([
        {"visa_category": "diplomatic", "standard_sla_days": 30, "requires_interview": "no", "max_renewals": 999},
        {"visa_category": "employment", "standard_sla_days": 90, "requires_interview": "yes", "max_renewals": 2},
        {"visa_category": "business", "standard_sla_days": 60, "requires_interview": "yes", "max_renewals": 3},
        {"visa_category": "student", "standard_sla_days": 75, "requires_interview": "no", "max_renewals": 1},
        {"visa_category": "family_reunion", "standard_sla_days": 120, "requires_interview": "yes", "max_renewals": 1},
        {"visa_category": "tourist", "standard_sla_days": 45, "requires_interview": "no", "max_renewals": 5},
    ])
    standards.to_csv(os.path.join(workspace, "visa_processing_standards.csv"), index=False)

    # 4. Embassy directory (fixed reference)
    embassy_info = {
        "directory_version": "2026-Q2",
        "embassies": {}
    }
    regions = ["North America", "Europe", "Asia Pacific", "Middle East", "Africa",
               "South America", "Central Asia", "Southeast Asia", "Caribbean", "Oceania"]
    for i, emb in enumerate(EMBASSY_CODES):
        embassy_info["embassies"][emb] = {
            "region": regions[i % len(regions)],
            "capacity_tier": random.choice(["large", "medium", "small"]),
            "operating_hours": "08:00-17:00 local",
            "current_quarter": "Q2",
        }
    with open(os.path.join(workspace, "embassy_directory.json"), "w") as f:
        json.dump(embassy_info, f, indent=2)

    # 5. Triage methodology (fixed reference; the authoritative procedure
    #    for stall determination, high-priority filtering, scoring, and
    #    intervention recording)
    methodology = """# Stalled Application Triage Methodology

This document is the authoritative procedure for the consular operations
center's stalled-application review. Numeric thresholds referenced below are
defined in `stall_criteria.json`; scoring parameters, high-priority
conditions, and action mappings are defined in `priority_scoring_rules.yaml`;
per-category SLAs are defined in `visa_processing_standards.csv`.

## 1. Scope: active applications

An application is in scope if and only if its current status is one of:
`pending`, `in_review`, `on_hold`, `awaiting_documents`. Applications with
status `approved` or `denied` are excluded. Every embassy in the system is
covered.

All date arithmetic uses the `reference_date` from `stall_criteria.json`.
"Days since submission" (also reported as days stalled) is the number of
days between the reference date and the application's submission date.

## 2. Stall determination

An active application is **stalled** if it triggers ANY one or more of the
following five conditions. Each condition has a fixed reason code.

1. `biometric_expired` — any of the applicant's biometric submissions has
   status `expired`, OR any biometric submission's expiry date falls within
   the warning window: (expiry date − reference date) in days is less than
   or equal to `biometric_expiry_warning_days`.
2. `document_flags_unresolved` — the number of the applicant's document
   verification records with verification status `flagged` is greater than
   or equal to `min_unresolved_document_flags`.
3. `sla_exceeded` — days since submission is STRICTLY greater than
   (`standard_sla_days` for the applicant's visa category) ×
   (`processing_time_threshold_multiplier`).
4. `appointment_backlogged` — any of the applicant's embassy appointments
   has status `pending` or `scheduled` AND a wait time in days STRICTLY
   greater than `appointment_wait_threshold_days`.
5. `quota_critical` — the current-quarter quota utilization percentage for
   the applicant's visa category at the applicant's embassy, computed as
   used count ÷ allocated quota × 100, is greater than or equal to
   `quota_utilization_critical_pct`. The current quarter for all quota
   lookups is Q2. If no quota record exists for the category/embassy pair,
   this condition does not trigger.

## 3. High-priority filter

A stalled application is retained on the intervention list only if it is
high-priority. It is high-priority if ANY of the following hold (see
`high_priority_conditions`):

- the applicant's priority level is one of the listed `priority_levels`;
- the applicant's escalation level, as recorded in the case dossier files,
  is greater than or equal to `min_escalation_level`;
- the applicant's sponsor tier, as recorded in the case dossier files, is
  one of the listed `sponsor_tiers`.

Escalation levels and sponsor tiers live ONLY in the case dossier batch
files (`case_dossier_batch_*`), which are split across multiple files in
mixed formats (JSON, CSV, plain text, YAML, Markdown). Every batch file must
be read to obtain complete coverage. If an applicant appears in no dossier
file, use escalation level 0 and sponsor tier `none`.

## 4. Intervention priority score

For each stalled high-priority application compute:

    score = base_score(visa_category) × priority_level_multiplier(priority_level)
          + base_score(visa_category) × escalation_multiplier × escalation_level
          + days_since_submission × days_stalled_factor
          + quota_pressure_bonus            (only if quota_critical triggered)
          + biometric_expiry_bonus          (only if biometric_expired triggered)
          + document_flag_penalty × total number of the applicant's flagged
            document verification records   (applied whether or not condition
            2 triggered; the penalty value is negative)
          + sponsor_tier_bonus(sponsor_tier)

Use base score 50 for a visa category missing from `base_scores` and
multiplier 1.0 for a priority level missing from
`priority_level_multiplier`. Round the final score to two decimal places.

## 5. Recommended action

Among the stall reason codes an application triggered, find the one that
appears EARLIEST in `stall_reason_priority_order`; the recommended action is
that reason's entry in `stall_reason_action_mapping`. If no listed reason
applies, use `Review case`.

## 6. Intervention recording

Every application on the final intervention list must also be filed as an
intervention request in the case management system, routed to the
applicant's own embassy queue and carrying that applicant's recommended
action.
"""
    with open(os.path.join(workspace, "triage_methodology.md"), "w") as f:
        f.write(methodology)

    # ── Scalable case dossier files ───────────────────────────────────────
    num_files = SCALE["num_workspace_files"]
    app_ids = [a[0] for a in applicants]
    app_names = {a[0]: a[1] for a in applicants}

    # Distribute applicants across files
    random.shuffle(app_ids)
    chunks = []
    chunk_size = max(1, len(app_ids) // num_files)
    for i in range(num_files):
        start = i * chunk_size
        end = start + chunk_size if i < num_files - 1 else len(app_ids)
        if start < len(app_ids):
            chunks.append(app_ids[start:end])

    # Ensure we have exactly num_files chunks
    while len(chunks) < num_files:
        chunks.append(random.sample(app_ids, min(5, len(app_ids))))

    formats = ["json", "csv", "txt", "yaml", "md"]

    for idx, chunk in enumerate(chunks[:num_files]):
        fmt = formats[idx % len(formats)]
        records = []
        for app_id in chunk:
            rec = {
                "applicant_id": app_id,
                "escalation_level": random.choices(
                    [0, 1, 2, 3, 4, 5],
                    weights=[0.25, 0.20, 0.20, 0.15, 0.12, 0.08],
                    k=1
                )[0],
                "sponsor_tier": random.choices(
                    SPONSOR_TIERS,
                    weights=[0.10, 0.20, 0.30, 0.40],
                    k=1
                )[0],
                "special_circumstances": random.choice(SPECIAL_CIRCUMSTANCES),
                "last_officer_contact": (REFERENCE_DATE - timedelta(days=random.randint(1, 180))).strftime("%Y-%m-%d"),
            }
            records.append(rec)

        if fmt == "json":
            fname = f"case_dossier_batch_{idx+1:03d}.json"
            with open(os.path.join(workspace, fname), "w") as f:
                json.dump(records, f, indent=2)

        elif fmt == "csv":
            fname = f"case_dossier_batch_{idx+1:03d}.csv"
            df = pd.DataFrame(records)
            df.to_csv(os.path.join(workspace, fname), index=False)

        elif fmt == "txt":
            fname = f"case_dossier_batch_{idx+1:03d}.txt"
            lines = []
            for rec in records:
                lines.append(f"--- Applicant: {rec['applicant_id']} ---")
                lines.append(f"Escalation Level: {rec['escalation_level']}")
                lines.append(f"Sponsor Tier: {rec['sponsor_tier']}")
                circ = rec['special_circumstances'] if rec['special_circumstances'] else "None"
                lines.append(f"Special Circumstances: {circ}")
                lines.append(f"Last Officer Contact: {rec['last_officer_contact']}")
                lines.append("")
            with open(os.path.join(workspace, fname), "w") as f:
                f.write("\n".join(lines))

        elif fmt == "yaml":
            fname = f"case_dossier_batch_{idx+1:03d}.yaml"
            with open(os.path.join(workspace, fname), "w") as f:
                yaml.dump(records, f, default_flow_style=False)

        elif fmt == "md":
            fname = f"case_dossier_batch_{idx+1:03d}.md"
            lines = []
            for rec in records:
                lines.append(f"## {rec['applicant_id']}")
                lines.append("")
                lines.append(f"| Field | Value |")
                lines.append(f"|-------|-------|")
                lines.append(f"| Escalation Level | {rec['escalation_level']} |")
                lines.append(f"| Sponsor Tier | {rec['sponsor_tier']} |")
                circ = rec['special_circumstances'] if rec['special_circumstances'] else "None"
                lines.append(f"| Special Circumstances | {circ} |")
                lines.append(f"| Last Officer Contact | {rec['last_officer_contact']} |")
                lines.append("")
            with open(os.path.join(workspace, fname), "w") as f:
                f.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    set_seeds()
    fake = Faker()
    Faker.seed(SEED)

    n = SCALE["rows_per_table"]

    # Generate data
    applicants = generate_applicants(fake, n)
    app_ids = [a[0] for a in applicants]

    biometrics = generate_biometrics(app_ids, n)
    doc_vers = generate_document_verifications(app_ids, n)
    appointments = generate_appointments(app_ids, n)
    quotas = generate_visa_quotas(n)

    # Create database
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    insert_data(conn, applicants, biometrics, doc_vers, appointments, quotas)
    conn.close()

    # Create workspace
    generate_workspace(args.workspace, applicants)
    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")
    print(f"  Applicants: {len(applicants)}")
    print(f"  Biometrics: {len(biometrics)}")
    print(f"  Document verifications: {len(doc_vers)}")
    print(f"  Appointments: {len(appointments)}")
    print(f"  Quotas: {len(quotas)}")


if __name__ == "__main__":
    main()
