"""
Data generation for audit coverage gap analysis task.
Generates database tables and workspace files for cross-referencing
audit checklists, prior findings, GL entries, and support documents.
"""

import argparse
import sqlite3
import os
import json
import csv
import random
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 240,
    "num_workspace_files": 40,
}

random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ---------------------------------------------------------------------------
# Domain data pools
# ---------------------------------------------------------------------------

AUDIT_DOMAINS = [
    "Revenue Recognition", "Cost of Sales", "Operating Expenses",
    "Cash Management", "Accounts Receivable", "Inventory Valuation",
    "Prepaid Assets", "Fixed Assets", "Intangible Assets",
    "Investment Securities", "Accounts Payable", "Accrued Liabilities",
    "Long-Term Debt", "Lease Obligations", "Shareholders Equity",
    "Income Tax Provision", "Payroll Processing", "Employee Benefits",
    "Insurance Reserves", "Derivative Instruments", "Goodwill Impairment",
    "Contingent Liabilities", "Contractual Commitments", "Related Party Transactions",
    "Foreign Currency Translation", "Segment Reporting", "Going Concern Assessment",
    "Subsequent Events", "IT General Controls", "Consolidation Adjustments",
]

AUDIT_FOCUS = [
    "Completeness", "Existence", "Valuation", "Rights and Obligations",
    "Classification", "Cutoff", "Presentation", "Accuracy",
]

DEPARTMENTS = [
    "Finance", "Operations", "Human Resources",
    "Information Technology", "Legal and Compliance", "Treasury", "Tax",
]

PROCEDURE_TYPES = [
    "substantive_testing",
    "analytical_review",
    "detail_testing",
    "management_inquiry",
    "third_party_confirmation",
    "walkthrough",
    "sampling",
    "recalculation",
]

SEVERITY_LEVELS = ["Critical", "High", "Medium", "Low"]
REMEDIATION_STATUSES = ["Remediated", "Partially Remediated", "Open", "Not Applicable"]

SUPPORT_DOC_TYPES = ["confirmation_letter", "bank_statement", "schedule",
                     "analysis_memo", "reconciliation", "management_representation",
                     "third_party_report", "contract_extract"]


def _generate_area_names(n):
    """Generate n unique audit area names from domain x focus combinations."""
    names = []
    combos = [(d, f) for d in AUDIT_DOMAINS for f in AUDIT_FOCUS]
    random.shuffle(combos)
    for d, f in combos[:n]:
        names.append(f"{d} - {f}")
    # If we need more than len(combos), extend with numbered variants
    idx = len(combos)
    while len(names) < n:
        base = AUDIT_DOMAINS[idx % len(AUDIT_DOMAINS)]
        names.append(f"{base} - Extended Review {idx}")
        idx += 1
    return names[:n]


def create_tables(conn):
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS audit_areas (
            area_id TEXT PRIMARY KEY,
            area_name TEXT NOT NULL,
            department TEXT NOT NULL,
            inherent_risk TEXT NOT NULL,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS checklist_items (
            item_id TEXT PRIMARY KEY,
            area_id TEXT NOT NULL,
            procedure_type TEXT NOT NULL,
            procedure_description TEXT NOT NULL,
            completion_status TEXT NOT NULL,
            assigned_to TEXT,
            due_date TEXT,
            FOREIGN KEY (area_id) REFERENCES audit_areas(area_id)
        );

        CREATE TABLE IF NOT EXISTS prior_year_findings (
            finding_id TEXT PRIMARY KEY,
            area_id TEXT NOT NULL,
            finding_year INTEGER NOT NULL,
            severity TEXT NOT NULL,
            finding_description TEXT NOT NULL,
            remediation_status TEXT NOT NULL,
            management_response TEXT,
            FOREIGN KEY (area_id) REFERENCES audit_areas(area_id)
        );

        CREATE TABLE IF NOT EXISTS gl_entries (
            entry_id TEXT PRIMARY KEY,
            area_id TEXT NOT NULL,
            account_code TEXT NOT NULL,
            account_name TEXT NOT NULL,
            amount REAL NOT NULL,
            entry_date TEXT NOT NULL,
            memo TEXT,
            posted_by TEXT,
            FOREIGN KEY (area_id) REFERENCES audit_areas(area_id)
        );
    """)
    conn.commit()


def generate_audit_areas(conn, n):
    """Generate n audit areas with deterministic risk distribution."""
    area_names = _generate_area_names(n)
    risk_pool = (["High"] * max(1, n // 3)
                 + ["Medium"] * max(1, n // 3)
                 + ["Low"] * max(1, n - 2 * (n // 3)))
    random.shuffle(risk_pool)

    rows = []
    for i in range(n):
        area_id = f"AREA_{i+1:04d}"
        dept = DEPARTMENTS[i % len(DEPARTMENTS)]
        risk = risk_pool[i]
        desc = fake.sentence(nb_words=12)
        rows.append((area_id, area_names[i], dept, risk, desc))

    conn.executemany(
        "INSERT INTO audit_areas VALUES (?,?,?,?,?)", rows
    )
    conn.commit()
    return [r[0] for r in rows]  # area_ids


def generate_checklist_items(conn, n, area_ids):
    """
    Generate checklist items. Each area gets 2-6 procedures.
    Deliberately leave some gaps in high-risk areas for required procedures.
    Total rows >= n.
    """
    rows = []
    item_counter = 0

    for area_id in area_ids:
        num_items = random.randint(2, 6)
        chosen_procs = random.sample(PROCEDURE_TYPES, min(num_items, len(PROCEDURE_TYPES)))
        for proc in chosen_procs:
            item_counter += 1
            item_id = f"CHK_{item_counter:05d}"
            status = random.choices(
                ["Complete", "In Progress", "Not Started"],
                weights=[0.5, 0.3, 0.2]
            )[0]
            assigned = fake.name()
            due = fake.date_between(start_date="-60d", end_date="+90d").isoformat()
            desc = f"Perform {proc.replace('_', ' ')} procedures for {area_id}"
            rows.append((item_id, area_id, proc, desc, status, assigned, due))

    # Ensure minimum row count
    while len(rows) < n:
        item_counter += 1
        aid = random.choice(area_ids)
        proc = random.choice(PROCEDURE_TYPES)
        item_id = f"CHK_{item_counter:05d}"
        desc = f"Supplementary {proc.replace('_', ' ')} for {aid}"
        rows.append((item_id, aid, proc, desc, "Not Started", fake.name(),
                      fake.date_between(start_date="+30d", end_date="+90d").isoformat()))

    conn.executemany(
        "INSERT INTO checklist_items VALUES (?,?,?,?,?,?,?)", rows
    )
    conn.commit()


def generate_prior_year_findings(conn, n, area_ids):
    """
    Generate prior year findings. ~60% of areas have 1-3 findings.
    Some high-severity findings are left unremediated to create gaps.
    Total rows >= n.
    """
    rows = []
    finding_counter = 0
    areas_with_findings = random.sample(area_ids, max(1, int(len(area_ids) * 0.6)))

    for area_id in areas_with_findings:
        num_findings = random.randint(1, 3)
        for _ in range(num_findings):
            finding_counter += 1
            fid = f"FIND_{finding_counter:05d}"
            year = random.choice([2023, 2024, 2024])  # bias toward 2024
            severity = random.choices(
                SEVERITY_LEVELS, weights=[0.1, 0.25, 0.4, 0.25]
            )[0]
            remediation = random.choices(
                REMEDIATION_STATUSES, weights=[0.35, 0.25, 0.3, 0.1]
            )[0]
            desc = fake.sentence(nb_words=15)
            mgmt_resp = fake.sentence(nb_words=10) if remediation != "Not Applicable" else ""
            rows.append((fid, area_id, year, severity, desc, remediation, mgmt_resp))

    # Ensure minimum row count
    while len(rows) < n:
        finding_counter += 1
        fid = f"FIND_{finding_counter:05d}"
        aid = random.choice(area_ids)
        rows.append((fid, aid, 2024,
                      random.choice(SEVERITY_LEVELS),
                      fake.sentence(nb_words=15),
                      random.choice(REMEDIATION_STATUSES),
                      fake.sentence(nb_words=10)))

    conn.executemany(
        "INSERT INTO prior_year_findings VALUES (?,?,?,?,?,?,?)", rows
    )
    conn.commit()


def generate_gl_entries(conn, n, area_ids):
    """
    Generate GL entries. Each area gets 2-8 entries with varying amounts.
    Some areas will have totals exceeding materiality thresholds.
    Total rows >= n.
    """
    rows = []
    entry_counter = 0
    account_base = 1000

    for area_id in area_ids:
        num_entries = random.randint(2, 8)
        acct_code = f"{account_base + int(area_id.split('_')[1]):04d}"
        acct_name = fake.bs().title()
        for _ in range(num_entries):
            entry_counter += 1
            eid = f"GL_{entry_counter:06d}"
            # Mix of small and large amounts; some deliberately large
            if random.random() < 0.15:
                amount = round(random.uniform(200000, 1500000), 2)
            else:
                amount = round(random.uniform(1000, 250000), 2)
            edate = fake.date_between(start_date="-365d", end_date="today").isoformat()
            memo = fake.sentence(nb_words=6)
            posted = fake.name()
            rows.append((eid, area_id, acct_code, acct_name, amount, edate, memo, posted))

    # Ensure minimum row count
    while len(rows) < n:
        entry_counter += 1
        eid = f"GL_{entry_counter:06d}"
        aid = random.choice(area_ids)
        acct_code = f"{account_base + int(aid.split('_')[1]):04d}"
        rows.append((eid, aid, acct_code, fake.bs().title(),
                      round(random.uniform(1000, 100000), 2),
                      fake.date_between(start_date="-365d", end_date="today").isoformat(),
                      fake.sentence(nb_words=6), fake.name()))

    conn.executemany(
        "INSERT INTO gl_entries VALUES (?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Workspace generation
# ---------------------------------------------------------------------------

MATERIALITY_THRESHOLDS = {
    "Finance": 500000,
    "Operations": 750000,
    "Human Resources": 300000,
    "Information Technology": 400000,
    "Legal and Compliance": 250000,
    "Treasury": 600000,
    "Tax": 450000,
}

REQUIRED_PROCEDURES = {
    "High": [
        "substantive_testing",
        "analytical_review",
        "detail_testing",
        "management_inquiry",
        "third_party_confirmation",
    ],
    "Medium": [
        "substantive_testing",
        "analytical_review",
        "management_inquiry",
    ],
    "Low": [
        "analytical_review",
        "management_inquiry",
    ],
}

RISK_SCORING_POLICY = {
    "inherent_risk_points": {
        "High": 3,
        "Medium": 2,
        "Low": 1,
    },
    "prior_finding_adjustments": [
        {"severity": "Critical", "remediation_not_in": ["Remediated"], "points": 3},
        {"severity": "High", "remediation_not_in": ["Remediated"], "points": 2},
        {"severity": "Medium", "remediation_not_in": ["Remediated"], "points": 1},
    ],
    "materiality_exceeded_points": 2,
    "no_support_docs_points": 1,
    "composite_risk_thresholds": {
        "High": 5,
        "Medium": 3,
    },
    "note": "Score >= High threshold -> High risk; >= Medium threshold -> Medium; else Low",
}


def generate_fixed_config_files(workspace, conn):
    """Generate policy/config workspace files that do not scale."""
    import yaml

    # 1. Risk scoring policy (YAML)
    with open(os.path.join(workspace, "risk_scoring_policy.yaml"), "w") as f:
        yaml.dump(RISK_SCORING_POLICY, f, default_flow_style=False, sort_keys=False)

    # 2. Materiality thresholds (JSON)
    with open(os.path.join(workspace, "materiality_thresholds.json"), "w") as f:
        json.dump(MATERIALITY_THRESHOLDS, f, indent=2)

    # 3. Required procedures by risk level (YAML)
    with open(os.path.join(workspace, "required_procedures.yaml"), "w") as f:
        yaml.dump(REQUIRED_PROCEDURES, f, default_flow_style=False, sort_keys=False)

    # 4. Department-area mapping (CSV) - maps departments to audit leads and review deadlines
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT department FROM audit_areas")
    depts = [r[0] for r in cur.fetchall()]
    with open(os.path.join(workspace, "department_audit_leads.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["department", "lead_auditor", "review_deadline", "escalation_contact"])
        for dept in depts:
            w.writerow([dept, fake.name(), fake.date_between(start_date="+30d", end_date="+120d").isoformat(), fake.email()])


def generate_support_doc_files(conn, workspace, num_files):
    """
    Generate scaled client support document files.
    Each file covers 1-3 audit areas and uses a rotating format.
    """
    import yaml

    cur = conn.cursor()
    cur.execute("SELECT area_id, area_name, department FROM audit_areas")
    areas = cur.fetchall()
    area_ids = [a[0] for a in areas]
    area_map = {a[0]: {"name": a[1], "dept": a[2]} for a in areas}

    # Distribute areas across files; some areas may not be covered (intentional gaps)
    # Shuffle and assign areas to files
    shuffled_areas = list(area_ids)
    random.shuffle(shuffled_areas)

    # Each file covers 1-3 areas; not all areas will be covered
    file_area_assignments = []
    idx = 0
    for i in range(num_files):
        cover_count = random.randint(1, 3)
        covered = []
        for _ in range(cover_count):
            if idx < len(shuffled_areas):
                covered.append(shuffled_areas[idx])
                idx += 1
        if not covered:
            # If we've run out of areas, pick random ones
            covered = [random.choice(area_ids)]
        file_area_assignments.append(covered)

    formats = [".txt", ".csv", ".json", ".md"]

    for i, covered_areas in enumerate(file_area_assignments):
        fmt = formats[i % len(formats)]
        filename = f"client_support_{i+1:03d}{fmt}"
        filepath = os.path.join(workspace, filename)

        coverage_quality = random.choice(["Full", "Partial", "Sufficient", "Limited"])

        if fmt == ".txt":
            _write_txt_support(filepath, covered_areas, area_map, coverage_quality)
        elif fmt == ".csv":
            _write_csv_support(filepath, covered_areas, area_map, coverage_quality)
        elif fmt == ".json":
            _write_json_support(filepath, covered_areas, area_map, coverage_quality)
        elif fmt == ".md":
            _write_md_support(filepath, covered_areas, area_map, coverage_quality)


def _write_txt_support(filepath, covered_areas, area_map, quality):
    lines = [f"CLIENT SUPPORT DOCUMENT", f"Date Prepared: {fake.date_this_year().isoformat()}", ""]
    for aid in covered_areas:
        info = area_map[aid]
        lines.append(f"Audit Area: {aid} ({info['name']})")
        lines.append(f"Department: {info['dept']}")
        lines.append(f"Coverage Quality: {quality}")
        lines.append(f"Evidence Description: {fake.paragraph(nb_sentences=3)}")
        lines.append(f"Prepared By: {fake.name()}")
        lines.append("")
    with open(filepath, "w") as f:
        f.write("\n".join(lines))


def _write_csv_support(filepath, covered_areas, area_map, quality):
    with open(filepath, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["area_id", "area_name", "department", "coverage_quality",
                     "document_type", "evidence_summary", "preparer"])
        for aid in covered_areas:
            info = area_map[aid]
            w.writerow([aid, info["name"], info["dept"], quality,
                        random.choice(SUPPORT_DOC_TYPES),
                        fake.sentence(nb_words=10), fake.name()])


def _write_json_support(filepath, covered_areas, area_map, quality):
    records = []
    for aid in covered_areas:
        info = area_map[aid]
        records.append({
            "area_id": aid,
            "area_name": info["name"],
            "department": info["dept"],
            "coverage_quality": quality,
            "document_type": random.choice(SUPPORT_DOC_TYPES),
            "evidence_items": [fake.sentence(nb_words=8) for _ in range(random.randint(1, 4))],
            "date_received": fake.date_this_year().isoformat(),
            "preparer": fake.name(),
        })
    with open(filepath, "w") as f:
        json.dump({"support_evidence": records}, f, indent=2)


def _write_md_support(filepath, covered_areas, area_map, quality):
    lines = [f"# Client Support Documentation\n"]
    lines.append(f"Prepared: {fake.date_this_year().isoformat()}\n")
    for aid in covered_areas:
        info = area_map[aid]
        lines.append(f"## {aid} - {info['name']}\n")
        lines.append(f"- **Department**: {info['dept']}")
        lines.append(f"- **Coverage Quality**: {quality}")
        lines.append(f"- **Document Type**: {random.choice(SUPPORT_DOC_TYPES)}")
        lines.append(f"- **Summary**: {fake.paragraph(nb_sentences=2)}\n")
    with open(filepath, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate audit coverage gap analysis data")
    parser.add_argument("--db_path", required=True, help="Path to SQLite database")
    parser.add_argument("--workspace", required=True, help="Path to workspace directory")
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n = SCALE["rows_per_table"]
    area_ids = generate_audit_areas(conn, n)
    generate_checklist_items(conn, n, area_ids)
    generate_prior_year_findings(conn, n, area_ids)
    generate_gl_entries(conn, n, area_ids)

    generate_fixed_config_files(args.workspace, conn)
    generate_support_doc_files(conn, args.workspace, SCALE["num_workspace_files"])

    conn.close()
    print(f"Database created at {args.db_path}")
    print(f"Workspace populated at {args.workspace}")


if __name__ == "__main__":
    main()
