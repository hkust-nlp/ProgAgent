"""
Clinical Trial Safety Protocol Compliance - Data Generation Script

Generates a SQLite database and workspace files for a clinical trial
safety protocol compliance task at configurable scale.
"""

import argparse
import os
import sqlite3
import json
import csv
import random

import numpy as np
import pandas as pd
from faker import Faker

# ── Scale parameters (v0 base) ──────────────────────────────────────
SCALE = {
    "rows_per_table": 60,       # v1 = 2x base
    "num_workspace_files": 16,  # v1 = base + N
}

# ── Deterministic seeds ─────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ── Domain constants ────────────────────────────────────────────────
THERAPEUTIC_AREAS = [
    "oncology", "cardiology", "neurology", "immunology",
    "infectious_disease", "endocrinology", "pulmonology", "hematology",
]
PHASES = [1, 2, 3, 4]
TRIAL_STATUSES = ["active", "active", "active", "suspended", "completed", "terminated"]
GUIDELINE_CATEGORIES = [
    "adverse_event_reporting", "dosage_monitoring", "informed_consent",
    "data_integrity", "biospecimen_handling", "patient_monitoring",
]
AUDIT_SEVERITIES = ["critical", "major", "minor", "observation"]
AUDIT_CATEGORIES = [
    "documentation", "protocol_adherence", "safety_reporting",
    "data_management", "facility_compliance", "staff_training",
]
AUDIT_RESOLUTIONS = ["open", "in_progress", "resolved", "overdue"]
REGIONS = ["North America", "Europe", "Asia Pacific", "Latin America"]
COUNTRIES_BY_REGION = {
    "North America": ["United States", "Canada", "Mexico"],
    "Europe": ["United Kingdom", "Germany", "France", "Spain", "Italy"],
    "Asia Pacific": ["Japan", "Australia", "South Korea", "India"],
    "Latin America": ["Brazil", "Argentina", "Colombia"],
}
CERT_LEVELS = ["A", "B", "C"]
CONSENT_STATUSES = ["current", "expired", "pending_review"]
SITE_STATUSES = ["active", "active", "active", "probation", "suspended"]

# ── New guidelines (fixed across all scales) ────────────────────────
NEW_GUIDELINES = [
    {
        "code": "NG-2026-001",
        "category": "adverse_event_reporting",
        "title": "Enhanced Serious Adverse Event Reporting for Immunotherapies",
        "severity": "critical",
        "applies_to_phases": [1, 2, 3],
        "applies_to_areas": ["oncology", "hematology", "immunology"],
        "consent_update_required": True,
        "effective_date": "2026-07-01",
        "requirements": (
            "All serious adverse events in immunotherapy trials must be reported "
            "within 24 hours. Sites must implement real-time electronic reporting "
            "and maintain a dedicated safety officer for each active trial."
        ),
    },
    {
        "code": "NG-2026-002",
        "category": "dosage_monitoring",
        "title": "Adaptive Dose Escalation Safety Controls",
        "severity": "major",
        "applies_to_phases": [1, 2],
        "applies_to_areas": ["oncology", "cardiology", "endocrinology"],
        "consent_update_required": False,
        "effective_date": "2026-08-15",
        "requirements": (
            "Phase 1 and 2 trials with dose escalation must conduct interim "
            "pharmacokinetic analyses every 4 weeks. A dose-limiting toxicity "
            "committee must review all escalation decisions."
        ),
    },
    {
        "code": "NG-2026-003",
        "category": "informed_consent",
        "title": "Genomic Data and Biobank Consent Transparency",
        "severity": "critical",
        "applies_to_phases": [1, 2, 3, 4],
        "applies_to_areas": THERAPEUTIC_AREAS[:],
        "consent_update_required": True,
        "effective_date": "2026-06-01",
        "requirements": (
            "All trials collecting genomic data or biobank specimens must obtain "
            "explicit, granular consent for each data use category. Existing "
            "consent forms must be re-versioned to include opt-in/opt-out for "
            "secondary research use."
        ),
    },
    {
        "code": "NG-2026-004",
        "category": "biospecimen_handling",
        "title": "Cold Chain Integrity for Biological Samples",
        "severity": "major",
        "applies_to_phases": [2, 3],
        "applies_to_areas": ["oncology", "immunology", "hematology", "infectious_disease"],
        "consent_update_required": True,
        "effective_date": "2026-09-01",
        "requirements": (
            "Trials handling biological specimens must implement continuous "
            "temperature monitoring with automated alerts. Chain-of-custody "
            "documentation must be digitized and auditable."
        ),
    },
    {
        "code": "NG-2026-005",
        "category": "patient_monitoring",
        "title": "Remote Patient Monitoring Standards",
        "severity": "minor",
        "applies_to_phases": [3, 4],
        "applies_to_areas": ["cardiology", "neurology", "pulmonology", "endocrinology"],
        "consent_update_required": False,
        "effective_date": "2026-10-01",
        "requirements": (
            "Phase 3 and 4 trials incorporating remote monitoring devices "
            "must establish data validation protocols and patient training "
            "programs. Device calibration records must be maintained."
        ),
    },
    {
        "code": "NG-2026-006",
        "category": "data_integrity",
        "title": "Electronic Data Capture Validation Requirements",
        "severity": "major",
        "applies_to_phases": [1, 2, 3],
        "applies_to_areas": THERAPEUTIC_AREAS[:],
        "consent_update_required": False,
        "effective_date": "2026-07-15",
        "requirements": (
            "All electronic data capture systems must undergo annual validation "
            "audits. Audit trail integrity checks must be automated, and any "
            "discrepancies must be reported within 48 hours."
        ),
    },
]


def create_tables(conn):
    """Create all database tables."""
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS trial_sites (
            site_id TEXT PRIMARY KEY,
            site_name TEXT NOT NULL,
            region TEXT NOT NULL,
            country TEXT NOT NULL,
            certification_level TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            last_inspection_date TEXT,
            status TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS clinical_trials (
            trial_id TEXT PRIMARY KEY,
            trial_name TEXT NOT NULL,
            phase INTEGER NOT NULL,
            status TEXT NOT NULL,
            site_id TEXT NOT NULL,
            sponsor TEXT NOT NULL,
            start_date TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            therapeutic_area TEXT NOT NULL,
            FOREIGN KEY (site_id) REFERENCES trial_sites(site_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS consent_forms (
            consent_id TEXT PRIMARY KEY,
            trial_id TEXT NOT NULL,
            form_version TEXT NOT NULL,
            language TEXT NOT NULL,
            approval_date TEXT NOT NULL,
            expiry_date TEXT,
            status TEXT NOT NULL,
            covers_genomic_data INTEGER NOT NULL DEFAULT 0,
            covers_biobank INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (trial_id) REFERENCES clinical_trials(trial_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS site_audits (
            audit_id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL,
            audit_date TEXT NOT NULL,
            auditor_name TEXT NOT NULL,
            finding_category TEXT NOT NULL,
            finding_description TEXT NOT NULL,
            severity TEXT NOT NULL,
            resolution_status TEXT NOT NULL,
            resolution_date TEXT,
            FOREIGN KEY (site_id) REFERENCES trial_sites(site_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS safety_guidelines (
            guideline_id TEXT PRIMARY KEY,
            code TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            requirement_text TEXT NOT NULL,
            severity_level TEXT NOT NULL,
            effective_date TEXT NOT NULL,
            applies_to_phases TEXT NOT NULL,
            applies_to_areas TEXT NOT NULL,
            is_superseded INTEGER NOT NULL DEFAULT 0,
            superseded_by TEXT
        )
    """)

    conn.commit()


def generate_sites(conn, n_sites):
    """Generate trial site records."""
    sites = []
    for i in range(n_sites):
        region = REGIONS[i % len(REGIONS)]
        country = random.choice(COUNTRIES_BY_REGION[region])
        site = {
            "site_id": f"SITE-{i+1:04d}",
            "site_name": f"{fake.company()} Research Center",
            "region": region,
            "country": country,
            "certification_level": random.choice(CERT_LEVELS),
            "capacity": random.randint(20, 200),
            "last_inspection_date": fake.date_between(
                start_date="-2y", end_date="-1m"
            ).isoformat(),
            "status": random.choice(SITE_STATUSES),
        }
        sites.append(site)

    df = pd.DataFrame(sites)
    df.to_sql("trial_sites", conn, if_exists="append", index=False)
    return sites


def generate_trials(conn, n_trials, sites):
    """Generate clinical trial records."""
    active_sites = [s for s in sites if s["status"] in ("active", "probation")]
    if not active_sites:
        active_sites = sites[:max(1, len(sites) // 2)]

    sponsors = [fake.company() for _ in range(max(5, n_trials // 5))]
    trials = []
    for i in range(n_trials):
        site = active_sites[i % len(active_sites)]
        status = random.choice(TRIAL_STATUSES)
        phase = random.choice(PHASES)
        area = THERAPEUTIC_AREAS[i % len(THERAPEUTIC_AREAS)]

        trial = {
            "trial_id": f"CT-{i+1:04d}",
            "trial_name": f"{fake.catch_phrase()} Trial - {area.title()} Phase {phase}",
            "phase": phase,
            "status": status,
            "site_id": site["site_id"],
            "sponsor": random.choice(sponsors),
            "start_date": fake.date_between(
                start_date="-3y", end_date="-2m"
            ).isoformat(),
            "protocol_version": f"v{random.randint(1, 5)}.{random.randint(0, 9)}",
            "therapeutic_area": area,
        }
        trials.append(trial)

    df = pd.DataFrame(trials)
    df.to_sql("clinical_trials", conn, if_exists="append", index=False)
    return trials


def generate_consent_forms(conn, n_forms, trials):
    """Generate consent form records."""
    forms = []
    languages = ["English", "Spanish", "French", "German", "Japanese", "Portuguese"]
    trial_list = trials * ((n_forms // len(trials)) + 1)

    for i in range(n_forms):
        trial = trial_list[i % len(trial_list)]
        approval = fake.date_between(start_date="-2y", end_date="-1m")
        expiry = fake.date_between(start_date="-1m", end_date="+1y")
        status = random.choice(CONSENT_STATUSES)
        # If expiry is in the past, set to expired
        from datetime import date
        if expiry <= date.today() and status == "current":
            status = "expired"

        form = {
            "consent_id": f"CF-{i+1:04d}",
            "trial_id": trial["trial_id"],
            "form_version": f"{random.randint(1, 4)}.{random.randint(0, 5)}",
            "language": random.choice(languages),
            "approval_date": approval.isoformat(),
            "expiry_date": expiry.isoformat(),
            "status": status,
            "covers_genomic_data": random.choice([0, 0, 1]),
            "covers_biobank": random.choice([0, 0, 1]),
        }
        forms.append(form)

    df = pd.DataFrame(forms)
    df.to_sql("consent_forms", conn, if_exists="append", index=False)
    return forms


def generate_site_audits(conn, n_audits, sites):
    """Generate site audit records."""
    audits = []
    auditors = [fake.name() for _ in range(max(3, n_audits // 10))]

    for i in range(n_audits):
        site = sites[i % len(sites)]
        audit_date = fake.date_between(start_date="-2y", end_date="-1m")
        severity = random.choice(AUDIT_SEVERITIES)
        resolution = random.choice(AUDIT_RESOLUTIONS)
        res_date = None
        if resolution == "resolved":
            res_date = fake.date_between(
                start_date=audit_date, end_date="today"
            ).isoformat()

        finding_cat = random.choice(AUDIT_CATEGORIES)

        audit = {
            "audit_id": f"AUD-{i+1:04d}",
            "site_id": site["site_id"],
            "audit_date": audit_date.isoformat(),
            "auditor_name": random.choice(auditors),
            "finding_category": finding_cat,
            "finding_description": _generate_finding_desc(finding_cat, severity),
            "severity": severity,
            "resolution_status": resolution,
            "resolution_date": res_date,
        }
        audits.append(audit)

    df = pd.DataFrame(audits)
    df.to_sql("site_audits", conn, if_exists="append", index=False)
    return audits


def _generate_finding_desc(category, severity):
    """Generate a realistic finding description."""
    descs = {
        "documentation": {
            "critical": "Missing essential regulatory documents for multiple study subjects",
            "major": "Incomplete source documentation for adverse event reporting",
            "minor": "Minor formatting inconsistencies in monitoring visit logs",
            "observation": "Suggest improving document version control practices",
        },
        "protocol_adherence": {
            "critical": "Systematic protocol deviations in dosing schedule across subjects",
            "major": "Failure to follow inclusion/exclusion criteria for several enrollments",
            "minor": "Delayed protocol amendment implementation by two weeks",
            "observation": "Consider additional protocol training for new staff",
        },
        "safety_reporting": {
            "critical": "Unreported serious adverse events discovered during audit review",
            "major": "Late reporting of adverse events beyond regulatory timelines",
            "minor": "Incomplete narrative descriptions in safety reports",
            "observation": "Safety reporting workflow could benefit from automation",
        },
        "data_management": {
            "critical": "Data integrity breach with unauthorized edits to electronic records",
            "major": "Missing audit trails in electronic data capture system",
            "minor": "Data queries not resolved within expected timeframe",
            "observation": "Database lock procedures should be standardized",
        },
        "facility_compliance": {
            "critical": "Temperature excursions in investigational product storage undetected",
            "major": "Calibration records missing for critical laboratory equipment",
            "minor": "Minor labeling discrepancies in pharmacy inventory",
            "observation": "Consider upgrading environmental monitoring systems",
        },
        "staff_training": {
            "critical": "Untrained personnel performing critical study procedures",
            "major": "Expired GCP certifications for multiple study coordinators",
            "minor": "Training records not updated after protocol amendment",
            "observation": "Annual refresher training schedule should be formalized",
        },
    }
    return descs.get(category, descs["documentation"]).get(severity, "General finding noted")


def generate_existing_guidelines(conn, n_guidelines):
    """Generate existing (historical) safety guideline records."""
    guidelines = []
    for i in range(n_guidelines):
        cat = GUIDELINE_CATEGORIES[i % len(GUIDELINE_CATEGORIES)]
        sev = random.choice(["critical", "major", "minor"])
        phases = sorted(random.sample(PHASES, k=random.randint(1, 4)))
        areas = sorted(random.sample(THERAPEUTIC_AREAS, k=random.randint(2, 6)))

        gl = {
            "guideline_id": f"GL-{i+1:04d}",
            "code": f"SAF-{2020 + (i % 6)}-{i+1:03d}",
            "category": cat,
            "title": f"Guideline for {cat.replace('_', ' ').title()} ({sev.title()})",
            "requirement_text": f"Standard {sev} requirements for {cat.replace('_', ' ')} in {', '.join(areas[:2])} trials.",
            "severity_level": sev,
            "effective_date": fake.date_between(
                start_date="-5y", end_date="-6m"
            ).isoformat(),
            "applies_to_phases": ",".join(str(p) for p in phases),
            "applies_to_areas": ",".join(areas),
            "is_superseded": 0,
            "superseded_by": None,
        }
        guidelines.append(gl)

    df = pd.DataFrame(guidelines)
    df.to_sql("safety_guidelines", conn, if_exists="append", index=False)
    return guidelines


# ── Workspace generation ────────────────────────────────────────────

def generate_workspace(workspace, sites, trials, consent_forms, audits):
    """Generate all workspace files."""
    os.makedirs(workspace, exist_ok=True)

    n_scalable = SCALE["num_workspace_files"]
    n_inspection = n_scalable // 2
    n_dossier = n_scalable - n_inspection

    # Fixed config files
    _write_new_guidelines_yaml(workspace)
    _write_severity_matrix(workspace)
    _write_amendment_priority_rules(workspace)
    _write_phase_requirements(workspace)
    _write_compliance_methodology(workspace)

    # Scalable: site inspection reports
    active_sites = [s for s in sites if s["status"] in ("active", "probation")]
    # Ensure deterministic selection
    inspection_sites = sorted(active_sites, key=lambda s: s["site_id"])[:n_inspection]
    site_audit_map = {}
    for a in audits:
        site_audit_map.setdefault(a["site_id"], []).append(a)

    for site in inspection_sites:
        _write_site_inspection(workspace, site, site_audit_map.get(site["site_id"], []))

    # Scalable: trial dossier files
    active_trials = [t for t in trials if t["status"] == "active"]
    dossier_trials = sorted(active_trials, key=lambda t: t["trial_id"])[:n_dossier]
    trial_consent_map = {}
    for cf in consent_forms:
        trial_consent_map.setdefault(cf["trial_id"], []).append(cf)

    for trial in dossier_trials:
        _write_trial_dossier(
            workspace, trial, trial_consent_map.get(trial["trial_id"], [])
        )


def _write_new_guidelines_yaml(workspace):
    """Write new guidelines YAML config (fixed, not scaling)."""
    # Write as structured text in YAML-like format
    import yaml

    data = {"new_guidelines": []}
    for gl in NEW_GUIDELINES:
        entry = {
            "code": gl["code"],
            "category": gl["category"],
            "title": gl["title"],
            "severity": gl["severity"],
            "applies_to_phases": gl["applies_to_phases"],
            "applies_to_areas": gl["applies_to_areas"],
            "consent_update_required": gl["consent_update_required"],
            "effective_date": gl["effective_date"],
            "requirements": gl["requirements"],
        }
        data["new_guidelines"].append(entry)

    path = os.path.join(workspace, "new_guidelines_2026.yaml")
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, width=120)


def _write_severity_matrix(workspace):
    """Write severity scoring matrix (fixed config)."""
    matrix = {
        "severity_weights": {"critical": 30, "major": 20, "minor": 10},
        "audit_finding_penalties": {
            "open": {"critical": 15, "major": 10, "minor": 5, "observation": 2},
            "overdue": {"critical": 25, "major": 18, "minor": 8, "observation": 3},
            "in_progress": {"critical": 5, "major": 3, "minor": 1, "observation": 0},
            "resolved": {"critical": 0, "major": 0, "minor": 0, "observation": 0},
        },
        "audit_penalty_cap": 40,
        "consent_penalties": {
            "expired": 12,
            "pending_review": 6,
            "current": 0,
        },
        "no_consent_penalty": 15,
        "site_risk_score_threshold": 75,
        "site_risk_penalty": 10,
        "deviation_count_threshold": 3,
        "deviation_penalty": 8,
    }

    path = os.path.join(workspace, "severity_matrix.json")
    with open(path, "w") as f:
        json.dump(matrix, f, indent=2)


def _write_amendment_priority_rules(workspace):
    """Write amendment priority rules (fixed config)."""
    import yaml

    rules = {
        "amendment_type_rules": [
            {
                "condition": "consent_update_required AND consent_expired_or_missing",
                "amendment_type": "urgent_consent_revision",
            },
            {
                "condition": "consent_update_required AND consent_current_or_pending",
                "amendment_type": "consent_and_protocol_update",
            },
            {
                "condition": "site_has_open_critical_findings",
                "amendment_type": "site_remediation_protocol",
            },
            {
                "condition": "default",
                "amendment_type": "standard_protocol_revision",
            },
        ],
        "deadline_brackets": [
            {"min_priority_score": 60, "deadline_days": 30},
            {"min_priority_score": 40, "deadline_days": 60},
            {"min_priority_score": 25, "deadline_days": 90},
            {"min_priority_score": 0, "deadline_days": 120},
        ],
        "notes": (
            "Amendment type is determined by the first matching condition. "
            "Deadline is set by the highest priority bracket whose min_priority_score "
            "the computed priority score meets or exceeds."
        ),
    }

    path = os.path.join(workspace, "amendment_priority_rules.yaml")
    with open(path, "w") as f:
        yaml.dump(rules, f, default_flow_style=False, sort_keys=False, width=120)


def _write_phase_requirements(workspace):
    """Write phase-specific compliance requirements (fixed config)."""
    rows = [
        {"phase": 1, "monitoring_requirement": "intensive_safety_review", "phase_bonus": 8},
        {"phase": 2, "monitoring_requirement": "expanded_safety_committee", "phase_bonus": 5},
        {"phase": 3, "monitoring_requirement": "full_dsmb_review", "phase_bonus": 3},
        {"phase": 4, "monitoring_requirement": "routine_pharmacovigilance", "phase_bonus": 0},
    ]

    path = os.path.join(workspace, "phase_requirements.csv")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["phase", "monitoring_requirement", "phase_bonus"])
        writer.writeheader()
        writer.writerows(rows)


def _write_compliance_methodology(workspace):
    """Write the compliance assessment methodology document (fixed config)."""
    content = """# Compliance Assessment Methodology

This document is the authoritative specification for how the compliance
action plan and the consent update report are derived. It is to be read
together with `new_guidelines_2026.yaml`, `severity_matrix.json`,
`amendment_priority_rules.yaml`, and `phase_requirements.csv`.

## 1. Scope of Assessment

Only clinical trials whose status is `active` are assessed. An active trial
is affected by a new guideline when BOTH of the following hold:

1. The trial's phase appears in the guideline's `applies_to_phases` list.
2. The trial's therapeutic area appears in the guideline's `applies_to_areas` list.

Each affected (trial, guideline) combination produces exactly one action
plan entry.

## 2. Priority Score

The priority score for an affected (trial, guideline) pair is the SUM of the
following six components. All parameter values referenced below are defined
in `severity_matrix.json` and `phase_requirements.csv`.

1. **Severity weight** — `severity_weights` value keyed by the guideline's
   severity classification.
2. **Audit penalty** — For EVERY audit finding recorded at the trial's site,
   look up `audit_finding_penalties[resolution_status][severity]` and sum
   the values. Cap the summed total at `audit_penalty_cap`.
3. **Consent penalty** — Determined by the trial's most recent consent form,
   where "most recent" means the form with the latest approval date. The
   penalty is `consent_penalties[status]` for that form's status. If the
   trial has NO consent form at all, apply `no_consent_penalty` instead and
   treat the trial's consent status as `missing`.
4. **Phase bonus** — The `phase_bonus` value for the trial's phase from the
   phase requirements table.
5. **Site risk penalty** — If a site inspection report exists for the
   trial's site and the Overall Risk Score stated in that report is
   strictly greater than `site_risk_score_threshold`, add
   `site_risk_penalty`. If no inspection report exists for the site, add
   nothing.
6. **Deviation penalty** — If a trial dossier file exists for the trial and
   its recorded `protocol_deviation_count` is strictly greater than
   `deviation_count_threshold`, add `deviation_penalty`. If no dossier
   exists for the trial, add nothing.

## 3. Amendment Type

The amendment type is decided by the FIRST matching condition in the
precedence order defined in `amendment_priority_rules.yaml`
(`amendment_type_rules`). The condition terms are defined as follows:

- `consent_expired_or_missing` — the trial's consent status (as determined
  in Section 2, component 3) is `expired` or `missing`.
- `consent_current_or_pending` — the trial's consent status is `current` or
  `pending_review`.
- `consent_update_required` — the guideline's `consent_update_required`
  flag is true.
- `site_has_open_critical_findings` — the trial's site has at least one
  audit finding of `critical` severity whose resolution status is `open`
  or `overdue`.

## 4. Compliance Deadline

The deadline in days comes from the `deadline_brackets` in
`amendment_priority_rules.yaml`: evaluate the brackets in the order listed
and use the FIRST bracket whose `min_priority_score` the computed priority
score meets or exceeds.

## 5. Consent Update Reporting

A trial requires a consent form revision when it is affected by at least
one guideline whose `consent_update_required` flag is true. For reporting
purposes, the trial's current form version is the version string of its
most recent consent form by approval date, or the literal string `none`
if the trial has no consent form.
"""

    path = os.path.join(workspace, "compliance_methodology.md")
    with open(path, "w") as f:
        f.write(content)


def _write_site_inspection(workspace, site, site_audits):
    """Write a detailed site inspection report markdown file."""
    np.random.seed(hash(site["site_id"]) % (2**31))
    risk_score = int(np.random.randint(30, 100))

    category_scores = {}
    for cat in AUDIT_CATEGORIES:
        category_scores[cat] = int(np.random.randint(40, 100))

    open_findings = [a for a in site_audits if a["resolution_status"] in ("open", "overdue")]

    content = f"""# Site Inspection Report

Site ID: {site["site_id"]}
Site Name: {site["site_name"]}
Region: {site["region"]}, {site["country"]}
Inspection Date: {site["last_inspection_date"]}
Certification Level: {site["certification_level"]}

## Overall Risk Score: {risk_score}

The overall risk score is calculated based on a weighted assessment of all compliance
categories, historical audit performance, and current operational status. A score above
75 indicates elevated risk requiring enhanced monitoring protocols.

## Category Compliance Scores

"""
    for cat, score in category_scores.items():
        status_label = "PASS" if score >= 70 else "ATTENTION REQUIRED"
        content += f"- {cat.replace('_', ' ').title()}: {score}/100 ({status_label})\n"

    content += f"""
## Open Findings Summary

Total open or overdue findings: {len(open_findings)}

"""
    for finding in open_findings[:5]:
        content += (
            f"- [{finding['severity'].upper()}] {finding['finding_category']}: "
            f"{finding['finding_description']} (Status: {finding['resolution_status']})\n"
        )

    content += f"""
## Inspector Recommendations

Based on the current assessment, {'enhanced monitoring is recommended' if risk_score > 75
else 'standard monitoring protocols are sufficient'}. The site should prioritize resolution
of any open critical findings before the next scheduled inspection cycle.

## Deviation History

Protocol deviation incidents recorded at this site require attention proportional to
their frequency and severity. Sites with deviation counts exceeding established thresholds
should implement corrective action plans.
"""

    path = os.path.join(workspace, f"site_inspection_{site['site_id']}.md")
    with open(path, "w") as f:
        f.write(content)

    # Reset random state
    np.random.seed(SEED)


def _write_trial_dossier(workspace, trial, consent_forms_list):
    """Write a trial dossier JSON file with protocol details."""
    np.random.seed(hash(trial["trial_id"]) % (2**31))
    deviation_count = int(np.random.randint(0, 10))

    amendments = []
    n_amendments = int(np.random.randint(1, 6))
    for j in range(n_amendments):
        amendments.append({
            "amendment_number": j + 1,
            "date": fake.date_between(start_date="-2y", end_date="-1m").isoformat(),
            "description": fake.sentence(nb_words=8),
            "category": random.choice(GUIDELINE_CATEGORIES),
        })

    active_consent = [cf for cf in consent_forms_list if cf["status"] == "current"]
    latest_consent_version = (
        max(active_consent, key=lambda x: x["approval_date"])["form_version"]
        if active_consent else "none"
    )

    dossier = {
        "trial_id": trial["trial_id"],
        "trial_name": trial["trial_name"],
        "phase": trial["phase"],
        "therapeutic_area": trial["therapeutic_area"],
        "site_id": trial["site_id"],
        "protocol_version": trial["protocol_version"],
        "protocol_deviation_count": deviation_count,
        "last_amendment_date": amendments[-1]["date"] if amendments else None,
        "amendment_history": amendments,
        "current_consent_version": latest_consent_version,
        "investigator_notes": (
            f"Trial is currently in {trial['status']} status. "
            f"{'High deviation count requires corrective review. ' if deviation_count > 3 else ''}"
            f"Protocol version {trial['protocol_version']} is the latest approved version."
        ),
    }

    path = os.path.join(workspace, f"trial_dossier_{trial['trial_id']}.json")
    with open(path, "w") as f:
        json.dump(dossier, f, indent=2)

    np.random.seed(SEED)


# ── Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate clinical trial compliance data")
    parser.add_argument("--db_path", required=True, help="Path to SQLite database")
    parser.add_argument("--workspace", required=True, help="Path to workspace directory")
    args = parser.parse_args()

    # Re-seed for reproducibility
    random.seed(SEED)
    np.random.seed(SEED)
    Faker.seed(SEED)

    n_rows = SCALE["rows_per_table"]

    # Remove existing DB
    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    # Generate data
    sites = generate_sites(conn, n_rows)
    trials = generate_trials(conn, n_rows, sites)
    consent_forms = generate_consent_forms(conn, n_rows, trials)
    audits = generate_site_audits(conn, n_rows, sites)
    generate_existing_guidelines(conn, n_rows)

    conn.commit()
    conn.close()

    # Generate workspace
    generate_workspace(args.workspace, sites, trials, consent_forms, audits)

    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")
    print(f"Scale: {SCALE}")


if __name__ == "__main__":
    main()
