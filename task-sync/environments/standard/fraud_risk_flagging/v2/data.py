import argparse
import os
import sqlite3
import json
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker
import yaml
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 240,
    "num_workspace_files": 30,
}

# ── constants ──────────────────────────────────────────────────────────
INJURY_TYPES = [
    "sprain", "fracture", "laceration", "burn", "contusion",
    "repetitive_strain", "back_injury", "head_injury",
]
BODY_PARTS = [
    "back", "neck", "shoulder", "knee", "wrist",
    "ankle", "head", "hand", "elbow", "hip",
]
LOCATIONS = [
    "warehouse", "office", "loading_dock", "parking_lot",
    "manufacturing_floor", "break_room", "stairwell",
    "restroom", "conference_room", "outdoor_area",
]
DEPARTMENTS = [
    "Manufacturing", "Logistics", "Sales", "IT", "HR",
    "Finance", "Maintenance", "Quality Control", "R&D", "Customer Service",
]
POSITIONS = [
    "Operator", "Technician", "Supervisor", "Analyst", "Coordinator",
    "Specialist", "Manager", "Associate", "Lead", "Inspector",
]
SPECIALTIES = [
    "Orthopedics", "General Practice", "Emergency Medicine",
    "Physical Therapy", "Neurology", "Pain Management",
    "Chiropractic", "Occupational Medicine", "Radiology", "Internal Medicine",
]
DIAGNOSIS_CODES = {
    "sprain": ["S93.4", "S63.5", "S83.5"],
    "fracture": ["S52.5", "S82.0", "S42.0"],
    "laceration": ["S61.0", "S81.0", "S71.1"],
    "burn": ["T30.0", "T31.0", "T20.1"],
    "contusion": ["S80.1", "S70.0", "S40.0"],
    "repetitive_strain": ["M54.5", "M77.1", "G56.0"],
    "back_injury": ["S33.5", "M54.16", "S23.3"],
    "head_injury": ["S09.9", "S06.0", "S00.9"],
}
MISMATCHED_CODES = {
    "sprain": ["S52.5", "T30.0"],
    "fracture": ["S93.4", "M54.5"],
    "laceration": ["S80.1", "G56.0"],
    "burn": ["S61.0", "S83.5"],
    "contusion": ["S52.5", "T30.0"],
    "repetitive_strain": ["S52.5", "S82.0"],
    "back_injury": ["S52.5", "T30.0"],
    "head_injury": ["S93.4", "M77.1"],
}
AMOUNT_THRESHOLDS = {
    "sprain": 5000,
    "fracture": 15000,
    "laceration": 8000,
    "burn": 12000,
    "contusion": 4000,
    "repetitive_strain": 6000,
    "back_injury": 10000,
    "head_injury": 20000,
}
PROCEDURES = {
    "sprain": ["Physical therapy session", "Joint immobilization", "Anti-inflammatory prescription"],
    "fracture": ["X-ray imaging", "Cast application", "Surgical fixation"],
    "laceration": ["Wound cleaning and suturing", "Tetanus booster", "Follow-up wound check"],
    "burn": ["Burn debridement", "Skin graft consultation", "Topical treatment application"],
    "contusion": ["Ice and compression therapy", "Pain management consultation", "Follow-up evaluation"],
    "repetitive_strain": ["Ergonomic assessment", "Cortisone injection", "Physical therapy session"],
    "back_injury": ["MRI scan", "Spinal decompression therapy", "Pain management consultation"],
    "head_injury": ["CT scan", "Neurological evaluation", "Cognitive rest protocol"],
}


def _build_db(db_path, rng, fake, n_rows):
    """Create and populate the SQLite database."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ── schema ─────────────────────────────────────────────────────────
    cur.executescript("""
        DROP TABLE IF EXISTS medical_treatments;
        DROP TABLE IF EXISTS witness_statements;
        DROP TABLE IF EXISTS claims;
        DROP TABLE IF EXISTS employees;
        DROP TABLE IF EXISTS medical_providers;

        CREATE TABLE employees (
            employee_id TEXT PRIMARY KEY,
            name TEXT,
            department TEXT,
            hire_date TEXT,
            position TEXT,
            salary REAL,
            employment_status TEXT,
            supervisor TEXT
        );
        CREATE TABLE medical_providers (
            provider_id TEXT PRIMARY KEY,
            name TEXT,
            specialty TEXT,
            license_number TEXT,
            address TEXT,
            city TEXT,
            state TEXT
        );
        CREATE TABLE claims (
            claim_id TEXT PRIMARY KEY,
            employee_id TEXT,
            injury_date TEXT,
            filing_date TEXT,
            injury_type TEXT,
            body_part TEXT,
            location TEXT,
            description TEXT,
            claim_amount REAL,
            status TEXT,
            FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
        );
        CREATE TABLE medical_treatments (
            treatment_id TEXT PRIMARY KEY,
            claim_id TEXT,
            provider_id TEXT,
            treatment_date TEXT,
            diagnosis_code TEXT,
            procedure_description TEXT,
            treatment_cost REAL,
            FOREIGN KEY (claim_id) REFERENCES claims(claim_id),
            FOREIGN KEY (provider_id) REFERENCES medical_providers(provider_id)
        );
        CREATE TABLE witness_statements (
            statement_id TEXT PRIMARY KEY,
            claim_id TEXT,
            witness_name TEXT,
            relationship TEXT,
            statement_date TEXT,
            statement_text TEXT,
            consistency_rating REAL,
            FOREIGN KEY (claim_id) REFERENCES claims(claim_id)
        );
    """)

    # ── employees ──────────────────────────────────────────────────────
    base_date = datetime(2020, 1, 1)
    employees = []
    for i in range(n_rows):
        eid = f"EMP-{i+1:04d}"
        hire_offset = int(rng.randint(0, 1800))
        hire_date = base_date + timedelta(days=hire_offset)
        emp = {
            "employee_id": eid,
            "name": fake.name(),
            "department": DEPARTMENTS[int(rng.randint(0, len(DEPARTMENTS)))],
            "hire_date": hire_date.strftime("%Y-%m-%d"),
            "position": POSITIONS[int(rng.randint(0, len(POSITIONS)))],
            "salary": round(float(rng.uniform(35000, 120000)), 2),
            "employment_status": rng.choice(["active", "active", "active", "probation", "leave"]),
            "supervisor": fake.name(),
        }
        employees.append(emp)
    cur.executemany(
        "INSERT INTO employees VALUES (?,?,?,?,?,?,?,?)",
        [(e["employee_id"], e["name"], e["department"], e["hire_date"],
          e["position"], e["salary"], e["employment_status"], e["supervisor"])
         for e in employees],
    )

    # ── medical providers ──────────────────────────────────────────────
    providers = []
    for i in range(n_rows):
        pid = f"PRV-{i+1:04d}"
        prov = {
            "provider_id": pid,
            "name": f"Dr. {fake.last_name()}",
            "specialty": SPECIALTIES[int(rng.randint(0, len(SPECIALTIES)))],
            "license_number": f"LIC-{fake.bothify('####??').upper()}",
            "address": fake.street_address(),
            "city": fake.city(),
            "state": fake.state_abbr(),
        }
        providers.append(prov)
    cur.executemany(
        "INSERT INTO medical_providers VALUES (?,?,?,?,?,?,?)",
        [(p["provider_id"], p["name"], p["specialty"], p["license_number"],
          p["address"], p["city"], p["state"]) for p in providers],
    )

    # ── decide fraud assignments ───────────────────────────────────────
    n_claims = n_rows
    fraud_ratio = 0.20
    n_fraud = max(4, int(n_claims * fraud_ratio))
    fraud_indices = set(rng.choice(n_claims, size=n_fraud, replace=False).tolist())

    # some legitimate claims get exactly 1 minor indicator (noise)
    n_noise = max(2, int(n_claims * 0.08))
    non_fraud = [i for i in range(n_claims) if i not in fraud_indices]
    noise_indices = set(rng.choice(non_fraud, size=min(n_noise, len(non_fraud)), replace=False).tolist())

    # assign employees to claims (some employees get multiple)
    emp_ids = [e["employee_id"] for e in employees]
    # ~75% of claims go to unique employees; rest are repeats
    unique_count = int(n_claims * 0.75)
    claim_emp_ids = list(rng.choice(emp_ids[:unique_count], size=unique_count, replace=False))
    repeat_pool = list(rng.choice(claim_emp_ids, size=n_claims - unique_count, replace=True))
    claim_emp_ids.extend(repeat_pool)
    rng.shuffle(claim_emp_ids)

    # pick some providers to be "anomalous" (high billing anomaly score)
    n_anomalous_providers = max(3, int(n_rows * 0.12))
    anomalous_provider_indices = set(rng.choice(n_rows, size=n_anomalous_providers, replace=False).tolist())
    provider_anomaly_scores = {}
    for i in range(n_rows):
        pid = providers[i]["provider_id"]
        if i in anomalous_provider_indices:
            provider_anomaly_scores[pid] = round(float(rng.uniform(0.72, 0.95)), 2)
        else:
            provider_anomaly_scores[pid] = round(float(rng.uniform(0.05, 0.55)), 2)

    # ── claims + treatments + witnesses ────────────────────────────────
    claims_data = []
    treatments_data = []
    witnesses_data = []
    treat_counter = 0
    wit_counter = 0

    # fraud indicator assignments per claim
    INDICATOR_POOL = [
        "late_filing", "excessive_amount", "provider_anomaly",
        "witness_inconsistency", "repeat_claimant", "treatment_timing",
        "new_employee", "low_credibility",
    ]

    claim_indicators = {}  # index -> set of indicators
    for idx in range(n_claims):
        if idx in fraud_indices:
            n_ind = int(rng.randint(2, 5))  # 2-4 indicators
            chosen = list(rng.choice(INDICATOR_POOL, size=min(n_ind, len(INDICATOR_POOL)), replace=False))
            claim_indicators[idx] = set(chosen)
        elif idx in noise_indices:
            chosen = [rng.choice(["late_filing", "new_employee", "low_credibility"])]
            claim_indicators[idx] = set(chosen)
        else:
            claim_indicators[idx] = set()

    emp_hire_lookup = {e["employee_id"]: e["hire_date"] for e in employees}

    for idx in range(n_claims):
        cid = f"CLM-{idx+1:04d}"
        eid = claim_emp_ids[idx]
        indicators = claim_indicators[idx]
        injury_type = INJURY_TYPES[int(rng.randint(0, len(INJURY_TYPES)))]
        body_part = BODY_PARTS[int(rng.randint(0, len(BODY_PARTS)))]
        location = LOCATIONS[int(rng.randint(0, len(LOCATIONS)))]

        # injury date: 2024-01-01 to 2024-12-31
        injury_offset = int(rng.randint(0, 365))
        injury_date = datetime(2024, 1, 1) + timedelta(days=injury_offset)

        # filing delay
        if "late_filing" in indicators:
            filing_delay = int(rng.randint(35, 90))
        else:
            filing_delay = int(rng.randint(1, 25))
        filing_date = injury_date + timedelta(days=filing_delay)

        # claim amount
        threshold = AMOUNT_THRESHOLDS[injury_type]
        if "excessive_amount" in indicators:
            amount = round(float(rng.uniform(threshold * 1.3, threshold * 3.0)), 2)
        else:
            amount = round(float(rng.uniform(threshold * 0.2, threshold * 0.9)), 2)

        # new employee check - modify hire date if needed
        if "new_employee" in indicators:
            new_hire = injury_date - timedelta(days=int(rng.randint(10, 80)))
            cur.execute("UPDATE employees SET hire_date=? WHERE employee_id=?",
                        (new_hire.strftime("%Y-%m-%d"), eid))
            emp_hire_lookup[eid] = new_hire.strftime("%Y-%m-%d")

        description = _generate_claim_description(fake, rng, injury_type, body_part, location)
        status = rng.choice(["open", "under_review", "pending"])

        claims_data.append({
            "claim_id": cid, "employee_id": eid,
            "injury_date": injury_date.strftime("%Y-%m-%d"),
            "filing_date": filing_date.strftime("%Y-%m-%d"),
            "injury_type": injury_type, "body_part": body_part,
            "location": location, "description": description,
            "claim_amount": amount, "status": status,
        })

        # ── treatments ─────────────────────────────────────────────────
        n_treatments = int(rng.randint(1, 4))  # 1-3 treatments
        for t in range(n_treatments):
            treat_counter += 1
            tid = f"TRT-{treat_counter:05d}"

            # pick provider - if provider_anomaly indicator, use anomalous one
            if "provider_anomaly" in indicators and t == 0:
                anom_pids = [providers[i]["provider_id"] for i in anomalous_provider_indices]
                prov_id = rng.choice(anom_pids)
            else:
                prov_id = providers[int(rng.randint(0, n_rows))]["provider_id"]

            # treatment date
            if "treatment_timing" in indicators and t == 0:
                # treatment BEFORE injury (fraud indicator)
                treat_date = injury_date - timedelta(days=int(rng.randint(1, 15)))
            else:
                treat_date = injury_date + timedelta(days=int(rng.randint(1, 60)))

            # diagnosis code
            diag_codes = DIAGNOSIS_CODES[injury_type]
            diag = rng.choice(diag_codes)

            proc = rng.choice(PROCEDURES[injury_type])
            cost = round(float(rng.uniform(200, 5000)), 2)

            treatments_data.append({
                "treatment_id": tid, "claim_id": cid, "provider_id": prov_id,
                "treatment_date": treat_date.strftime("%Y-%m-%d"),
                "diagnosis_code": diag, "procedure_description": proc,
                "treatment_cost": cost,
            })

        # ── witness statements ─────────────────────────────────────────
        n_witnesses = int(rng.randint(1, 4))  # 1-3 witnesses
        for w in range(n_witnesses):
            wit_counter += 1
            sid = f"WIT-{wit_counter:05d}"
            wname = fake.name()
            rel = rng.choice(["coworker", "supervisor", "bystander", "security_guard"])
            stmt_date = injury_date + timedelta(days=int(rng.randint(0, 14)))

            if "witness_inconsistency" in indicators:
                consistency = round(float(rng.uniform(1.0, 2.8)), 1)
                stmt_text = _generate_inconsistent_statement(fake, rng, injury_type, location)
            else:
                consistency = round(float(rng.uniform(3.2, 5.0)), 1)
                stmt_text = _generate_consistent_statement(fake, rng, injury_type, location)

            witnesses_data.append({
                "statement_id": sid, "claim_id": cid,
                "witness_name": wname, "relationship": rel,
                "statement_date": stmt_date.strftime("%Y-%m-%d"),
                "statement_text": stmt_text, "consistency_rating": consistency,
            })

    # pad treatments / witnesses to reach n_rows minimum
    while len(treatments_data) < n_rows:
        treat_counter += 1
        tid = f"TRT-{treat_counter:05d}"
        cid = claims_data[int(rng.randint(0, n_claims))]["claim_id"]
        claim_rec = next(c for c in claims_data if c["claim_id"] == cid)
        injury_type = claim_rec["injury_type"]
        injury_date_dt = datetime.strptime(claim_rec["injury_date"], "%Y-%m-%d")
        prov_id = providers[int(rng.randint(0, n_rows))]["provider_id"]
        treat_date = injury_date_dt + timedelta(days=int(rng.randint(1, 60)))
        diag = rng.choice(DIAGNOSIS_CODES[injury_type])
        proc = rng.choice(PROCEDURES[injury_type])
        cost = round(float(rng.uniform(200, 5000)), 2)
        treatments_data.append({
            "treatment_id": tid, "claim_id": cid, "provider_id": prov_id,
            "treatment_date": treat_date.strftime("%Y-%m-%d"),
            "diagnosis_code": diag, "procedure_description": proc,
            "treatment_cost": cost,
        })

    while len(witnesses_data) < n_rows:
        wit_counter += 1
        sid = f"WIT-{wit_counter:05d}"
        cid = claims_data[int(rng.randint(0, n_claims))]["claim_id"]
        claim_rec = next(c for c in claims_data if c["claim_id"] == cid)
        injury_date_dt = datetime.strptime(claim_rec["injury_date"], "%Y-%m-%d")
        wname = fake.name()
        rel = rng.choice(["coworker", "supervisor", "bystander", "security_guard"])
        stmt_date = injury_date_dt + timedelta(days=int(rng.randint(0, 14)))
        consistency = round(float(rng.uniform(3.0, 5.0)), 1)
        stmt_text = _generate_consistent_statement(fake, rng, claim_rec["injury_type"], claim_rec["location"])
        witnesses_data.append({
            "statement_id": sid, "claim_id": cid,
            "witness_name": wname, "relationship": rel,
            "statement_date": stmt_date.strftime("%Y-%m-%d"),
            "statement_text": stmt_text, "consistency_rating": consistency,
        })

    # ── insert ─────────────────────────────────────────────────────────
    cur.executemany(
        "INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(c["claim_id"], c["employee_id"], c["injury_date"], c["filing_date"],
          c["injury_type"], c["body_part"], c["location"], c["description"],
          c["claim_amount"], c["status"]) for c in claims_data],
    )
    cur.executemany(
        "INSERT INTO medical_treatments VALUES (?,?,?,?,?,?,?)",
        [(t["treatment_id"], t["claim_id"], t["provider_id"], t["treatment_date"],
          t["diagnosis_code"], t["procedure_description"], t["treatment_cost"])
         for t in treatments_data],
    )
    cur.executemany(
        "INSERT INTO witness_statements VALUES (?,?,?,?,?,?,?)",
        [(w["statement_id"], w["claim_id"], w["witness_name"], w["relationship"],
          w["statement_date"], w["statement_text"], w["consistency_rating"])
         for w in witnesses_data],
    )

    conn.commit()
    conn.close()
    return claims_data, employees, providers, treatments_data, witnesses_data, \
           claim_indicators, provider_anomaly_scores, anomalous_provider_indices


def _generate_claim_description(fake, rng, injury_type, body_part, location):
    templates = [
        f"Employee reported {injury_type} to {body_part} while working in {location}. {fake.sentence()}",
        f"Incident occurred in {location} resulting in {injury_type} affecting {body_part}. {fake.sentence()}",
        f"Worker sustained {injury_type} injury to {body_part} during routine duties in {location}. {fake.sentence()}",
    ]
    return rng.choice(templates)


def _generate_inconsistent_statement(fake, rng, injury_type, location):
    templates = [
        f"I think the injury happened in {location}, or maybe it was somewhere else. The details are unclear. {fake.sentence()}",
        f"I saw something but I am not sure about the timing. The worker mentioned {injury_type} but the circumstances seemed unusual. {fake.sentence()}",
        f"My recollection differs from the official report. I believe the incident may not have occurred as described. {fake.sentence()}",
    ]
    return rng.choice(templates)


def _generate_consistent_statement(fake, rng, injury_type, location):
    templates = [
        f"I directly witnessed the incident in {location}. The worker sustained a clear {injury_type} injury as described. {fake.sentence()}",
        f"I was present when the injury occurred in {location}. The account matches what I observed regarding the {injury_type}. {fake.sentence()}",
        f"The incident report accurately reflects what happened in {location}. The {injury_type} was clearly work-related. {fake.sentence()}",
    ]
    return rng.choice(templates)


# ── workspace generation ───────────────────────────────────────────────

def _build_workspace(workspace, rng, fake, claims_data, employees, providers,
                     treatments_data, witnesses_data, claim_indicators,
                     provider_anomaly_scores, anomalous_provider_indices, n_rows):
    os.makedirs(workspace, exist_ok=True)
    n_files = SCALE["num_workspace_files"]

    # distribution of scalable files
    n_dossiers = max(1, int(math.ceil(n_files * 0.5)))
    n_audits = max(1, int(math.ceil(n_files * 0.3)))
    n_assessments = max(1, n_files - n_dossiers - n_audits)

    # ── fixed config files ─────────────────────────────────────────────
    _write_fraud_scoring_rules(workspace)
    _write_risk_thresholds(workspace)
    _write_investigation_policy(workspace)

    # ── claim dossiers (JSON) ──────────────────────────────────────────
    dossier_dir = os.path.join(workspace, "claim_dossiers")
    os.makedirs(dossier_dir, exist_ok=True)
    claims_per_batch = max(1, math.ceil(len(claims_data) / n_dossiers))
    for batch_idx in range(n_dossiers):
        start = batch_idx * claims_per_batch
        end = min(start + claims_per_batch, len(claims_data))
        batch_claims = claims_data[start:end]
        dossier_entries = []
        for c in batch_claims:
            idx = int(c["claim_id"].split("-")[1]) - 1
            indicators = claim_indicators.get(idx, set())
            if "low_credibility" in indicators:
                cred = round(float(rng.uniform(0.10, 0.38)), 2)
            else:
                cred = round(float(rng.uniform(0.55, 0.95)), 2)
            red_flags = []
            if "late_filing" in indicators:
                red_flags.append("delayed_reporting")
            if "low_credibility" in indicators:
                red_flags.append("evasive_behavior")
            if "witness_inconsistency" in indicators:
                red_flags.append("conflicting_accounts")
            # add some noise red flags that don't affect scoring
            if float(rng.uniform(0, 1)) < 0.15:
                red_flags.append("minor_documentation_gap")
            dossier_entries.append({
                "claim_id": c["claim_id"],
                "adjuster_id": f"ADJ-{int(rng.randint(1, 20)):03d}",
                "assessment_date": c["filing_date"],
                "adjuster_notes": _gen_adjuster_notes(fake, rng, indicators),
                "credibility_score": cred,
                "physical_evidence_rating": rng.choice(["strong", "moderate", "weak"]),
                "surveillance_conducted": bool(rng.choice([True, False])),
                "red_flag_indicators": red_flags,
            })
        fpath = os.path.join(dossier_dir, f"dossier_batch_{batch_idx+1:03d}.json")
        with open(fpath, "w") as f:
            json.dump(dossier_entries, f, indent=2)

    # ── provider audit reports (CSV) ───────────────────────────────────
    audit_dir = os.path.join(workspace, "provider_audit_reports")
    os.makedirs(audit_dir, exist_ok=True)
    provs_per_batch = max(1, math.ceil(len(providers) / n_audits))
    for batch_idx in range(n_audits):
        start = batch_idx * provs_per_batch
        end = min(start + provs_per_batch, len(providers))
        batch_provs = providers[start:end]
        fpath = os.path.join(audit_dir, f"audit_report_{batch_idx+1:03d}.csv")
        with open(fpath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "provider_id", "audit_date", "billing_anomaly_score",
                "avg_claim_deviation_pct", "referral_pattern_flag", "audit_outcome",
            ])
            for p in batch_provs:
                pid = p["provider_id"]
                anom = provider_anomaly_scores[pid]
                dev = round(float(rng.uniform(2, 50)) if anom > 0.7 else float(rng.uniform(1, 15)), 1)
                ref_flag = "true" if anom > 0.7 and float(rng.uniform(0, 1)) > 0.3 else "false"
                outcome = "fail" if anom > 0.7 else "pass"
                audit_date = (datetime(2024, 1, 1) + timedelta(days=int(rng.randint(0, 180)))).strftime("%Y-%m-%d")
                writer.writerow([pid, audit_date, anom, dev, ref_flag, outcome])

    # ── witness assessments (TXT) ──────────────────────────────────────
    assess_dir = os.path.join(workspace, "witness_assessments")
    os.makedirs(assess_dir, exist_ok=True)
    wits_per_batch = max(1, math.ceil(len(witnesses_data) / n_assessments))
    for batch_idx in range(n_assessments):
        start = batch_idx * wits_per_batch
        end = min(start + wits_per_batch, len(witnesses_data))
        batch_wits = witnesses_data[start:end]
        lines = [
            f"WITNESS RELIABILITY ASSESSMENT - BATCH {batch_idx+1:03d}",
            f"Generated: 2024-07-01",
            f"Assessor: Internal Investigations Unit",
            "",
        ]
        for w in batch_wits:
            c_idx = int(w["claim_id"].split("-")[1]) - 1
            indicators = claim_indicators.get(c_idx, set())
            if "witness_inconsistency" in indicators:
                reliability = round(float(rng.uniform(0.10, 0.38)), 2)
            else:
                reliability = round(float(rng.uniform(0.55, 0.95)), 2)
            lines.append("---")
            lines.append(f"Claim ID: {w['claim_id']}")
            lines.append(f"Witness: {w['witness_name']}")
            lines.append(f"Reliability Rating: {reliability}")
            assessment_note = "Inconsistent timeline, credibility concerns" if reliability < 0.4 \
                else "Consistent account, appears credible"
            lines.append(f"Notes: {assessment_note}")
            lines.append("")
        fpath = os.path.join(assess_dir, f"assessment_batch_{batch_idx+1:03d}.txt")
        with open(fpath, "w") as f:
            f.write("\n".join(lines))


def _gen_adjuster_notes(fake, rng, indicators):
    notes = []
    if "low_credibility" in indicators:
        notes.append("Claimant appeared evasive during interview.")
    if "late_filing" in indicators:
        notes.append("Significant delay between reported injury and claim filing.")
    if not notes:
        notes.append("Standard interview conducted; no unusual observations.")
    notes.append(fake.sentence())
    return " ".join(notes)


def _write_fraud_scoring_rules(workspace):
    rules = {
        "scoring_rules": {
            "late_filing": {
                "description": "Filing delay exceeds threshold",
                "threshold_days": 30,
                "weight": 15,
            },
            "excessive_amount": {
                "description": "Claim amount exceeds injury type threshold",
                "weight": 20,
            },
            "provider_anomaly": {
                "description": "Treatment provider has high billing anomaly score",
                "anomaly_threshold": 0.7,
                "weight": 25,
            },
            "witness_inconsistency": {
                "description": "Low witness consistency or reliability ratings",
                "consistency_threshold": 3.0,
                "reliability_threshold": 0.4,
                "weight": 20,
            },
            "repeat_claimant": {
                "description": "Employee filed multiple claims within lookback period",
                "lookback_months": 12,
                "weight": 15,
            },
            "treatment_timing": {
                "description": "Treatment date precedes reported injury date",
                "weight": 30,
            },
            "new_employee": {
                "description": "Employee hired within threshold period before injury",
                "threshold_days": 90,
                "weight": 10,
            },
            "low_credibility": {
                "description": "Low credibility score from adjuster assessment",
                "credibility_threshold": 0.4,
                "weight": 15,
            },
        },
        "risk_levels": {
            "critical": {"min_score": 60, "recommended_action": "Immediate SIU investigation"},
            "high": {"min_score": 40, "recommended_action": "Priority SIU review within 48 hours"},
            "medium": {"min_score": 25, "recommended_action": "Enhanced monitoring and review within 1 week"},
        },
        "investigation_threshold": 25,
    }
    with open(os.path.join(workspace, "fraud_scoring_rules.yaml"), "w") as f:
        yaml.dump(rules, f, default_flow_style=False, sort_keys=False)


def _write_risk_thresholds(workspace):
    fpath = os.path.join(workspace, "risk_thresholds.csv")
    with open(fpath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["injury_type", "amount_threshold"])
        for itype, thresh in sorted(AMOUNT_THRESHOLDS.items()):
            writer.writerow([itype, thresh])


def _write_investigation_policy(workspace):
    policy = """SPECIAL INVESTIGATIONS UNIT - INVESTIGATION PRIORITY POLICY

All claims reaching or exceeding the investigation threshold score shall be placed on the
investigation list. The investigation threshold and scoring weights are defined in the
fraud scoring rules configuration.

Priority classification is determined by the total risk score as follows. A claim scoring
at or above the critical threshold receives a risk level of "critical" and warrants
immediate SIU investigation. A claim scoring at or above the high threshold but below the
critical threshold receives a risk level of "high" and should be reviewed by SIU within
48 hours. A claim scoring at or above the investigation threshold but below the high
threshold receives a risk level of "medium" and is placed under enhanced monitoring with
review within one week.

The investigation list must be sorted in descending order of risk score. When two claims
share the same risk score, the claim with the lexicographically smaller claim ID takes
higher priority (i.e., appears first).

For each claim on the list, the following fields are required: rank (starting from 1),
claim_id, employee_name, department, risk_score (integer), risk_level (one of critical,
high, medium), fraud_indicators (a pipe-separated list of triggered indicator names sorted
alphabetically, e.g. "late_filing|provider_anomaly"), and recommended_action (the action
text corresponding to the risk level).

A summary report must also be produced containing the total number of claims analyzed, the
number of flagged claims, the count of claims at each risk level (critical, high, medium),
and the overall average risk score across ALL analyzed claims rounded to two decimal places.
"""
    with open(os.path.join(workspace, "investigation_priority_policy.md"), "w") as f:
        f.write(policy)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    rng = np.random.RandomState(42)
    fake = Faker()
    Faker.seed(42)

    n_rows = SCALE["rows_per_table"]

    claims, employees, providers, treatments, witnesses, \
        claim_indicators, provider_anomaly_scores, anomalous_provider_indices = \
        _build_db(args.db_path, rng, fake, n_rows)

    _build_workspace(
        args.workspace, rng, fake, claims, employees, providers,
        treatments, witnesses, claim_indicators,
        provider_anomaly_scores, anomalous_provider_indices, n_rows,
    )
    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")


if __name__ == "__main__":
    main()
