"""
Data generation for construction site inspection prioritization task.
Generates database tables and workspace files for cross-referencing
permit applications, contractor violations, zoning overlays, and complaints.
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

SCALE = {
    "rows_per_table": 60,
    "num_workspace_files": 8,
}

REFERENCE_DATE = datetime(2025, 7, 1)


def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    rows = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    # ── Generate core data ──────────────────────────────────────────
    zones = _generate_zones(fake, rows)
    contractors = _generate_contractors(fake, rows)
    permits = _generate_permits(fake, rows, contractors, zones)
    violations = _generate_violations(fake, rows, contractors, permits)
    complaints = _generate_complaints(fake, rows, permits)

    # ── Write database ──────────────────────────────────────────────
    _create_database(db_path, zones, contractors, permits, violations, complaints)

    # ── Write workspace files ───────────────────────────────────────
    _create_fixed_files(workspace, zones)
    _create_scalable_files(workspace, num_files, permits, contractors,
                           complaints, violations, zones, fake)


# ═══════════════════════════════════════════════════════════════════
#  Data generation helpers
# ═══════════════════════════════════════════════════════════════════

ZONE_TYPES = ["residential", "commercial", "industrial", "mixed_use", "institutional"]
PERMIT_TYPES = ["new_construction", "renovation", "demolition", "addition",
                "electrical", "plumbing", "mechanical", "foundation"]
PERMIT_STATUSES = ["active", "pending_review", "approved", "completed", "rejected", "suspended"]
PERMIT_STATUS_WEIGHTS = [0.30, 0.20, 0.15, 0.20, 0.10, 0.05]
VIOLATION_TYPES = ["safety_hazard", "structural_deficiency", "code_violation",
                   "environmental_violation", "documentation_failure", "unauthorized_work"]
COMPLAINT_TYPES = ["noise_disturbance", "safety_concern", "structural_damage",
                   "environmental_hazard", "traffic_obstruction", "working_hours_violation",
                   "dust_debris"]
SPECIALTIES = ["general", "electrical", "plumbing", "structural", "demolition",
               "hvac", "roofing", "concrete", "masonry", "excavation"]


def _generate_zones(fake, n):
    zones = []
    for i in range(n):
        zid = f"Z-{i+1:04d}"
        zone_type = ZONE_TYPES[i % len(ZONE_TYPES)]
        district = f"District-{(i % 12) + 1}"
        zones.append({
            "zone_id": zid,
            "zone_name": f"{fake.street_name()} Zone",
            "zone_type": zone_type,
            "district": district,
            "max_building_height": int(np.random.choice([35, 50, 75, 100, 150])),
        })
    return zones


def _generate_contractors(fake, n):
    contractors = []
    for i in range(n):
        cid = f"C-{i+1:04d}"
        # Some licenses expired, some expiring soon, most valid
        r = np.random.random()
        if r < 0.12:
            expiry = REFERENCE_DATE - timedelta(days=int(np.random.randint(1, 365)))
        elif r < 0.25:
            expiry = REFERENCE_DATE + timedelta(days=int(np.random.randint(1, 90)))
        else:
            expiry = REFERENCE_DATE + timedelta(days=int(np.random.randint(91, 1095)))

        contractors.append({
            "contractor_id": cid,
            "company_name": fake.company(),
            "license_number": f"LIC-{np.random.randint(100000, 999999)}",
            "license_expiry": expiry.strftime("%Y-%m-%d"),
            "insurance_valid": int(np.random.random() > 0.08),
            "years_in_business": int(np.random.randint(1, 40)),
            "specialty": np.random.choice(SPECIALTIES),
        })
    return contractors


def _generate_permits(fake, n, contractors, zones):
    permits = []
    for i in range(n):
        pid = f"P-{i+1:04d}"
        cid = contractors[int(np.random.randint(0, len(contractors)))]["contractor_id"]
        zid = zones[int(np.random.randint(0, len(zones)))]["zone_id"]
        status = np.random.choice(PERMIT_STATUSES, p=PERMIT_STATUS_WEIGHTS)
        ptype = np.random.choice(PERMIT_TYPES)

        # Project value: log-normal distribution
        base_val = np.exp(np.random.normal(13.5, 1.2))
        project_value = round(max(50000, min(base_val, 50000000)), 2)

        sub_date = REFERENCE_DATE - timedelta(days=int(np.random.randint(7, 540)))

        permits.append({
            "permit_id": pid,
            "site_address": fake.address().replace("\n", ", "),
            "contractor_id": cid,
            "zone_id": zid,
            "permit_type": ptype,
            "submission_date": sub_date.strftime("%Y-%m-%d"),
            "status": status,
            "project_value": project_value,
            "num_stories": int(np.random.choice([1, 2, 3, 4, 5, 8, 12, 20],
                                                 p=[0.15, 0.25, 0.20, 0.15, 0.10, 0.08, 0.05, 0.02])),
            "square_footage": int(np.random.randint(800, 120000)),
        })
    return permits


def _generate_violations(fake, n, contractors, permits):
    """Generate at least n violation records spread across contractors."""
    violations = []
    vid_counter = 0
    contractor_ids = [c["contractor_id"] for c in contractors]
    permit_ids = [p["permit_id"] for p in permits]

    # First pass: assign 0-6 violations per contractor to hit ≥ n
    target = max(n, int(n * 1.5))
    counts = np.random.choice([0, 1, 2, 3, 4, 5, 6],
                              size=len(contractor_ids),
                              p=[0.25, 0.20, 0.18, 0.15, 0.10, 0.07, 0.05])
    # Scale counts to hit target
    while sum(counts) < target:
        idx = int(np.random.randint(0, len(counts)))
        counts[idx] += 1

    for ci, cid in enumerate(contractor_ids):
        for _ in range(int(counts[ci])):
            vid_counter += 1
            severity = int(np.random.choice([1, 2, 3, 4, 5], p=[0.15, 0.25, 0.30, 0.20, 0.10]))
            v_date = REFERENCE_DATE - timedelta(days=int(np.random.randint(1, 1095)))
            resolved = int(np.random.random() > 0.35)
            violations.append({
                "violation_id": f"V-{vid_counter:05d}",
                "contractor_id": cid,
                "violation_type": np.random.choice(VIOLATION_TYPES),
                "severity": severity,
                "violation_date": v_date.strftime("%Y-%m-%d"),
                "resolved": resolved,
                "fine_amount": round(float(severity * np.random.randint(500, 5000)), 2),
            })
    return violations


def _generate_complaints(fake, n, permits):
    """Generate at least n complaints, linked to permits."""
    complaints = []
    target = max(n, int(n * 1.3))
    permit_ids = [p["permit_id"] for p in permits]
    cid_counter = 0

    # Distribute complaints: some permits get many, some none
    counts = np.zeros(len(permit_ids), dtype=int)
    for _ in range(target):
        idx = int(np.random.randint(0, len(permit_ids)))
        counts[idx] += 1

    for pi, pid in enumerate(permit_ids):
        for _ in range(int(counts[pi])):
            cid_counter += 1
            severity = int(np.random.choice([1, 2, 3, 4, 5], p=[0.10, 0.20, 0.35, 0.25, 0.10]))
            c_date = REFERENCE_DATE - timedelta(days=int(np.random.randint(1, 365)))
            complaints.append({
                "complaint_id": f"CMP-{cid_counter:05d}",
                "permit_id": pid,
                "complaint_type": np.random.choice(COMPLAINT_TYPES),
                "complaint_date": c_date.strftime("%Y-%m-%d"),
                "severity": severity,
                "status": np.random.choice(["open", "investigating", "resolved", "dismissed"],
                                           p=[0.30, 0.25, 0.30, 0.15]),
                "reporter_type": np.random.choice(["citizen", "inspector", "anonymous", "business_owner"],
                                                   p=[0.45, 0.20, 0.25, 0.10]),
            })
    return complaints


# ═══════════════════════════════════════════════════════════════════
#  Database
# ═══════════════════════════════════════════════════════════════════

def _create_database(db_path, zones, contractors, permits, violations, complaints):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE zones (
            zone_id TEXT PRIMARY KEY,
            zone_name TEXT,
            zone_type TEXT,
            district TEXT,
            max_building_height INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE contractors (
            contractor_id TEXT PRIMARY KEY,
            company_name TEXT,
            license_number TEXT,
            license_expiry TEXT,
            insurance_valid INTEGER,
            years_in_business INTEGER,
            specialty TEXT
        )
    """)
    c.execute("""
        CREATE TABLE permits (
            permit_id TEXT PRIMARY KEY,
            site_address TEXT,
            contractor_id TEXT,
            zone_id TEXT,
            permit_type TEXT,
            submission_date TEXT,
            status TEXT,
            project_value REAL,
            num_stories INTEGER,
            square_footage INTEGER,
            FOREIGN KEY (contractor_id) REFERENCES contractors(contractor_id),
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id)
        )
    """)
    c.execute("""
        CREATE TABLE violations (
            violation_id TEXT PRIMARY KEY,
            contractor_id TEXT,
            violation_type TEXT,
            severity INTEGER,
            violation_date TEXT,
            resolved INTEGER,
            fine_amount REAL,
            FOREIGN KEY (contractor_id) REFERENCES contractors(contractor_id)
        )
    """)
    c.execute("""
        CREATE TABLE complaints (
            complaint_id TEXT PRIMARY KEY,
            permit_id TEXT,
            complaint_type TEXT,
            complaint_date TEXT,
            severity INTEGER,
            status TEXT,
            reporter_type TEXT,
            FOREIGN KEY (permit_id) REFERENCES permits(permit_id)
        )
    """)

    for z in zones:
        c.execute("INSERT INTO zones VALUES (?,?,?,?,?)",
                  (z["zone_id"], z["zone_name"], z["zone_type"], z["district"],
                   z["max_building_height"]))
    for ct in contractors:
        c.execute("INSERT INTO contractors VALUES (?,?,?,?,?,?,?)",
                  (ct["contractor_id"], ct["company_name"], ct["license_number"],
                   ct["license_expiry"], ct["insurance_valid"], ct["years_in_business"],
                   ct["specialty"]))
    for p in permits:
        c.execute("INSERT INTO permits VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (p["permit_id"], p["site_address"], p["contractor_id"], p["zone_id"],
                   p["permit_type"], p["submission_date"], p["status"], p["project_value"],
                   p["num_stories"], p["square_footage"]))
    for v in violations:
        c.execute("INSERT INTO violations VALUES (?,?,?,?,?,?,?)",
                  (v["violation_id"], v["contractor_id"], v["violation_type"],
                   v["severity"], v["violation_date"], v["resolved"], v["fine_amount"]))
    for cm in complaints:
        c.execute("INSERT INTO complaints VALUES (?,?,?,?,?,?,?)",
                  (cm["complaint_id"], cm["permit_id"], cm["complaint_type"],
                   cm["complaint_date"], cm["severity"], cm["status"], cm["reporter_type"]))

    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════
#  Fixed workspace files (do not scale with num_workspace_files)
# ═══════════════════════════════════════════════════════════════════

def _create_fixed_files(workspace, zones):
    # ── risk_config.yaml ────────────────────────────────────────────
    config = {
        "reference_date": REFERENCE_DATE.strftime("%Y-%m-%d"),
        "risk_weights": {
            "violation_history": 0.25,
            "zone_hazard": 0.20,
            "complaint_severity": 0.20,
            "project_scale": 0.15,
            "contractor_reliability": 0.10,
            "site_condition": 0.10,
        },
        "severity_multipliers": {
            1: 0.2,
            2: 0.4,
            3: 0.6,
            4: 0.8,
            5: 1.0,
        },
        "project_value_tiers": [
            {"name": "low", "min_value": 0, "max_value": 500000, "risk_score": 20},
            {"name": "medium", "min_value": 500000, "max_value": 2000000, "risk_score": 45},
            {"name": "high", "min_value": 2000000, "max_value": 10000000, "risk_score": 70},
            {"name": "mega", "min_value": 10000000, "max_value": 999999999, "risk_score": 95},
        ],
        "risk_tiers": [
            {"name": "low", "min_score": 0, "max_score": 30},
            {"name": "moderate", "min_score": 30, "max_score": 55},
            {"name": "high", "min_score": 55, "max_score": 75},
            {"name": "critical", "min_score": 75, "max_score": 100},
        ],
        "expired_license_penalty": 25,
        "expiring_license_penalty": 15,
        "license_expiry_window_days": 90,
        "violation_base_score": 10,
        "unresolved_violation_multiplier": 1.5,
        "recent_violation_days": 365,
        "recent_violation_bonus": 8,
        "max_violation_score": 100,
        "complaint_base_score": 8,
        "escalated_complaint_bonus": 12,
        "max_complaint_score": 100,
    }
    with open(os.path.join(workspace, "risk_config.yaml"), "w") as f:
        # Write YAML manually for clarity and control
        _write_yaml(f, config)

    # ── zone_hazard_overlay.csv ─────────────────────────────────────
    np.random.seed(42 + 1000)
    with open(os.path.join(workspace, "zone_hazard_overlay.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["zone_id", "flood_risk", "seismic_factor", "environmental_sensitivity",
                         "infrastructure_proximity"])
        for z in zones:
            zt = z["zone_type"]
            # Base values depend on zone type
            base = {"residential": 30, "commercial": 40, "industrial": 55,
                    "mixed_use": 45, "institutional": 35}[zt]
            flood = round(min(100, max(0, base + float(np.random.normal(0, 20)))), 1)
            seismic = round(min(100, max(0, base * 0.8 + float(np.random.normal(0, 18)))), 1)
            env_sens = round(min(100, max(0, base * 0.6 + float(np.random.normal(0, 22)))), 1)
            infra = round(min(100, max(0, 50 + float(np.random.normal(0, 25)))), 1)
            writer.writerow([z["zone_id"], flood, seismic, env_sens, infra])

    # ── inspection_policy.md ────────────────────────────────────────
    policy = f"""# Construction Site Inspection Prioritization Policy

## Scope

This policy governs the weekly generation of prioritized inspection lists for all construction sites
holding permits with status "active" or "pending_review". Only these two statuses qualify a permit
for inclusion in the weekly inspection cycle.

## Reference Date

The current inspection cycle reference date is {REFERENCE_DATE.strftime("%Y-%m-%d")}. All time-based
calculations (license expiry, violation recency, complaint recency) use this date.

## Risk Score Computation

Each qualifying permit receives a composite risk score between 0 and 100. The score is the weighted
sum of six component scores, each individually scaled to the 0-100 range:

1. Violation History — based on the permit's contractor violation records
2. Zone Hazard — derived from geospatial hazard overlay data for the permit's zone
3. Complaint Severity — based on complaints filed against the permit
4. Project Scale — determined by the project value tier
5. Contractor Reliability — from third-party audit data
6. Site Condition — from on-site survey assessments

Weights for each component are defined in the risk configuration file.

## Violation History Score

For each violation on the contractor's record:
- Start with the violation base score multiplied by the severity multiplier for that violation's severity level.
- If the violation is unresolved, multiply by the unresolved violation multiplier.
- If the violation occurred within the recent violation window (counting back from the reference date), add the recent violation bonus.

Sum all per-violation scores. Cap at the maximum violation score.

## Zone Hazard Score

The zone hazard score is the simple average of the four hazard metrics (flood risk, seismic factor,
environmental sensitivity, infrastructure proximity) from the zone hazard overlay data.

## Complaint Severity Score

For each complaint linked to the permit:
- Start with the complaint base score multiplied by the severity multiplier for that complaint's severity level.
- If the complaint is flagged as escalated (from the detailed complaint reports), add the escalated complaint bonus.

Sum all per-complaint scores. Cap at the maximum complaint score.

## Project Scale Score

Map the permit's project value to the appropriate tier using the project value tier definitions.
The risk score for the matching tier is the project scale component score.

## Contractor Reliability Score

The contractor reliability risk score equals 100 minus the safety audit score found in the
contractor audit data. If no audit data is available for a contractor, use a default risk
score of 50.

## Site Condition Score

The site condition risk score equals 100 minus the average of the structural score, safety score,
and environmental score from the site survey data. If no survey data is available for a permit,
use a default risk score of 50.

## License Penalties

After computing the weighted sum, add license penalties:
- If the contractor's license has expired (expiry date before the reference date), add the expired license penalty.
- Otherwise, if the contractor's license expires within the license expiry window (days from reference date), add the expiring license penalty.

The final risk score is capped at 100.

## Risk Tier Assignment

Assign each permit to a risk tier based on the final score:
- A score in the range [min_score, max_score) maps to that tier.
- For the highest tier, the upper bound is inclusive of 100.

## Primary Risk Factors

For each permit, identify the two components with the highest weighted contribution (weight times
component score). List them in descending order, separated by a semicolon and a space. Use the
component names exactly as they appear in the risk weight configuration keys.

## Ranking

Sort the final list by risk score descending. Break ties by submission date ascending (earlier
submissions first). Break further ties by permit ID ascending (lexicographic).
"""
    with open(os.path.join(workspace, "inspection_policy.md"), "w") as f:
        f.write(policy)


def _write_yaml(f, data, indent=0):
    """Simple recursive YAML writer for basic types."""
    prefix = "  " * indent
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                f.write(f"{prefix}{k}:\n")
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict):
                            f.write(f"{prefix}- ")
                            first = True
                            for ik, iv in item.items():
                                if first:
                                    f.write(f"{ik}: {_yaml_val(iv)}\n")
                                    first = False
                                else:
                                    f.write(f"{prefix}  {ik}: {_yaml_val(iv)}\n")
                        else:
                            f.write(f"{prefix}- {_yaml_val(item)}\n")
                else:
                    _write_yaml(f, v, indent + 1)
            else:
                f.write(f"{prefix}{k}: {_yaml_val(v)}\n")


def _yaml_val(v):
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return str(v)
    return str(v)


# ═══════════════════════════════════════════════════════════════════
#  Scalable workspace files
# ═══════════════════════════════════════════════════════════════════

def _create_scalable_files(workspace, num_files, permits, contractors,
                           complaints, violations, zones, fake):
    np.random.seed(42 + 2000)

    # Identify inspectable permits (active or pending_review)
    inspectable = [p for p in permits if p["status"] in ("active", "pending_review")]
    inspectable_pids = {p["permit_id"] for p in inspectable}
    inspectable_cids = list({p["contractor_id"] for p in inspectable})
    inspectable_complaints = [c for c in complaints if c["permit_id"] in inspectable_pids]

    # File count distribution
    n_survey = num_files * 3 // 8
    if n_survey < 1:
        n_survey = 1
    n_complaint = num_files * 3 // 8
    if n_complaint < 1:
        n_complaint = 1
    n_audit = num_files - n_survey - n_complaint
    if n_audit < 1:
        n_audit = 1
        # Rebalance
        if n_survey + n_complaint + n_audit > num_files:
            n_complaint = num_files - n_survey - n_audit

    # ── Site survey files ───────────────────────────────────────────
    survey_chunks = _split_list(inspectable, n_survey)
    for i, chunk in enumerate(survey_chunks):
        path = os.path.join(workspace, f"site_survey_batch_{i+1}.csv")
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["permit_id", "survey_date", "structural_score",
                             "safety_score", "environmental_score"])
            for p in chunk:
                s_date = (REFERENCE_DATE - timedelta(days=int(np.random.randint(1, 60)))).strftime("%Y-%m-%d")
                struct = round(min(100, max(10, float(np.random.normal(65, 18)))), 1)
                safety = round(min(100, max(10, float(np.random.normal(60, 20)))), 1)
                env_sc = round(min(100, max(10, float(np.random.normal(70, 15)))), 1)
                writer.writerow([p["permit_id"], s_date, struct, safety, env_sc])

    # ── Complaint detail files ──────────────────────────────────────
    complaint_chunks = _split_list(inspectable_complaints, n_complaint)
    for i, chunk in enumerate(complaint_chunks):
        records = []
        for c in chunk:
            escalated = bool(np.random.random() < 0.22)
            records.append({
                "complaint_id": c["complaint_id"],
                "permit_id": c["permit_id"],
                "detailed_description": fake.paragraph(nb_sentences=3),
                "escalation_flag": escalated,
                "inspector_notes": fake.sentence() if escalated else "",
            })
        path = os.path.join(workspace, f"complaint_detail_{i+1}.json")
        with open(path, "w") as f:
            json.dump(records, f, indent=2)

    # ── Contractor audit files ──────────────────────────────────────
    audit_chunks = _split_list(inspectable_cids, n_audit)
    for i, chunk in enumerate(audit_chunks):
        path = os.path.join(workspace, f"contractor_audit_{i+1}.txt")
        with open(path, "w") as f:
            for cid in chunk:
                safety_score = round(min(100, max(5, float(np.random.normal(62, 20)))), 1)
                reliability = round(min(10, max(1, float(np.random.normal(6.5, 2)))), 1)
                f.write("=" * 50 + "\n")
                f.write(f"CONTRACTOR AUDIT REPORT\n")
                f.write(f"Contractor ID: {cid}\n")
                a_date = (REFERENCE_DATE - timedelta(days=int(np.random.randint(10, 180)))).strftime("%Y-%m-%d")
                f.write(f"Audit Date: {a_date}\n")
                f.write(f"Reliability Rating: {reliability}\n")
                f.write(f"Safety Audit Score: {safety_score}\n")
                f.write(f"Findings: {fake.paragraph(nb_sentences=2)}\n")
                f.write("=" * 50 + "\n\n")


def _split_list(lst, n):
    """Split list into n roughly-equal chunks."""
    if n <= 0:
        return [lst]
    k, m = divmod(len(lst), n)
    chunks = []
    start = 0
    for i in range(n):
        end = start + k + (1 if i < m else 0)
        chunks.append(lst[start:end])
        start = end
    return chunks


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
