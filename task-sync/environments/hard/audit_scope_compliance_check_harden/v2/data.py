#!/usr/bin/env python3
"""Data generation for audit scope-creep / unauthorized-work detection task."""

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

# ── Scale parameters (only this block changes across v0-v3) ──────────────
SCALE = {
    "rows_per_table": 240,      # v2 = 4x base
    "num_workspace_files": 36,  # v2 = base + 2N
}
# ─────────────────────────────────────────────────────────────────────────

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

# ── Domain constants ────────────────────────────────────────────────────
ENGAGEMENT_TYPES = [
    "financial_audit", "tax_compliance", "advisory",
    "internal_controls", "risk_assessment",
]

CERT_LEVELS = ["junior", "senior", "manager", "partner"]
CERT_RANK = {c: i for i, c in enumerate(CERT_LEVELS)}

SCOPE_CATEGORIES = [
    "financial_statements", "tax_returns", "consulting",
    "controls_testing", "risk_modeling", "regulatory_compliance",
    "valuations", "forensic_review",
]

TASK_CODES = {
    "FS01": "financial_statements", "FS02": "financial_statements",
    "TX01": "tax_returns",          "TX02": "tax_returns",
    "CN01": "consulting",           "CN02": "consulting",
    "CT01": "controls_testing",     "CT02": "controls_testing",
    "RM01": "risk_modeling",        "RM02": "risk_modeling",
    "RC01": "regulatory_compliance","RC02": "regulatory_compliance",
    "VL01": "valuations",
    "FR01": "forensic_review",
}

DEPARTMENTS = ["Audit", "Tax", "Advisory", "Risk", "Forensics"]
ACCESS_TYPES = ["read", "write", "download", "upload"]
DOC_TYPES = [
    "financial_report", "tax_filing", "contract", "memo",
    "spreadsheet", "correspondence", "legal_document",
]
DOC_STATUSES = ["pending", "fulfilled", "denied", "in_progress"]
ROLES_ON_ENGAGEMENT = [
    "lead_auditor", "staff_auditor", "tax_specialist",
    "advisory_consultant", "reviewer", "analyst",
]
ENGAGEMENT_STATUSES = ["active", "completed", "on_hold", "planning"]


# ── Helpers ─────────────────────────────────────────────────────────────

def _rand_date(start: str, end: str) -> str:
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    delta = (e - s).days
    if delta <= 0:
        return start
    return (s + timedelta(days=random.randint(0, delta))).strftime("%Y-%m-%d")


def _rand_timestamp(date_str: str) -> str:
    h = random.randint(0, 23)
    m = random.randint(0, 59)
    s = random.randint(0, 59)
    return f"{date_str} {h:02d}:{m:02d}:{s:02d}"


# ── Data generators ─────────────────────────────────────────────────────

def generate_staff(n: int):
    rows = []
    for i in range(n):
        sid = f"S{i+1:04d}"
        rows.append({
            "staff_id": sid,
            "name": fake.name(),
            "role": random.choice(ROLES_ON_ENGAGEMENT),
            "certification_level": random.choice(CERT_LEVELS),
            "department": random.choice(DEPARTMENTS),
            "hire_date": _rand_date("2010-01-01", "2024-06-01"),
        })
    return pd.DataFrame(rows)


def generate_engagements(n: int, staff_df: pd.DataFrame):
    partner_ids = staff_df[staff_df["certification_level"] == "partner"]["staff_id"].tolist()
    if not partner_ids:
        partner_ids = staff_df["staff_id"].tolist()[:3]
    rows = []
    for i in range(n):
        eid = f"E{i+1:04d}"
        start = _rand_date("2024-01-01", "2025-06-01")
        end_dt = datetime.strptime(start, "%Y-%m-%d") + timedelta(days=random.randint(30, 365))
        rows.append({
            "engagement_id": eid,
            "client_name": fake.company(),
            "engagement_type": random.choice(ENGAGEMENT_TYPES),
            "start_date": start,
            "end_date": end_dt.strftime("%Y-%m-%d"),
            "status": random.choice(ENGAGEMENT_STATUSES),
            "partner_id": random.choice(partner_ids),
        })
    return pd.DataFrame(rows)


def generate_assignments(n: int, eng_df: pd.DataFrame, staff_df: pd.DataFrame):
    """Generate legitimate assignments, ensuring every engagement has ≥1."""
    eids = eng_df["engagement_id"].tolist()
    sids = staff_df["staff_id"].tolist()
    rows = []
    assigned_pairs = set()

    # Ensure every engagement has at least one assignment
    for eid in eids:
        sid = random.choice(sids)
        pair = (eid, sid)
        if pair not in assigned_pairs:
            assigned_pairs.add(pair)
            erow = eng_df[eng_df["engagement_id"] == eid].iloc[0]
            rows.append({
                "assignment_id": f"A{len(rows)+1:05d}",
                "engagement_id": eid,
                "staff_id": sid,
                "assigned_role": random.choice(ROLES_ON_ENGAGEMENT),
                "start_date": erow["start_date"],
                "end_date": erow["end_date"],
                "is_active": 1,
            })

    # Fill remaining
    while len(rows) < n:
        eid = random.choice(eids)
        sid = random.choice(sids)
        pair = (eid, sid)
        if pair in assigned_pairs:
            continue
        assigned_pairs.add(pair)
        erow = eng_df[eng_df["engagement_id"] == eid].iloc[0]
        rows.append({
            "assignment_id": f"A{len(rows)+1:05d}",
            "engagement_id": eid,
            "staff_id": sid,
            "assigned_role": random.choice(ROLES_ON_ENGAGEMENT),
            "start_date": erow["start_date"],
            "end_date": erow["end_date"],
            "is_active": random.choices([1, 0], weights=[0.85, 0.15])[0],
        })
    return pd.DataFrame(rows), assigned_pairs


def _pick_scope_areas(eng_type: str) -> list:
    """Deterministic-ish scope areas per engagement type."""
    base_map = {
        "financial_audit": ["financial_statements", "controls_testing"],
        "tax_compliance": ["tax_returns", "regulatory_compliance"],
        "advisory": ["consulting", "valuations"],
        "internal_controls": ["controls_testing", "risk_modeling"],
        "risk_assessment": ["risk_modeling", "forensic_review"],
    }
    areas = list(base_map.get(eng_type, ["consulting"]))
    # Randomly add one extra
    extras = [c for c in SCOPE_CATEGORIES if c not in areas]
    if extras:
        areas.append(random.choice(extras))
    return areas


def generate_time_entries(n: int, eng_df: pd.DataFrame, assigned_pairs: set,
                          staff_df: pd.DataFrame):
    """Generate time entries. ~12% are unauthorized (staff not assigned)."""
    eids = eng_df["engagement_id"].tolist()
    sids = staff_df["staff_id"].tolist()
    task_code_list = list(TASK_CODES.keys())
    rows = []
    unauthorized_fraction = 0.12

    for i in range(n):
        eid = random.choice(eids)
        erow = eng_df[eng_df["engagement_id"] == eid].iloc[0]

        if random.random() < unauthorized_fraction:
            # Pick staff NOT assigned to this engagement
            assigned_to_eng = {s for (e, s) in assigned_pairs if e == eid}
            candidates = [s for s in sids if s not in assigned_to_eng]
            if candidates:
                sid = random.choice(candidates)
            else:
                sid = random.choice(sids)
        else:
            assigned_to_eng = [s for (e, s) in assigned_pairs if e == eid]
            if assigned_to_eng:
                sid = random.choice(assigned_to_eng)
            else:
                sid = random.choice(sids)

        entry_date = _rand_date(erow["start_date"], erow["end_date"])
        hours = round(random.uniform(0.5, 12.0), 1)
        tc = random.choice(task_code_list)
        rows.append({
            "entry_id": f"T{i+1:06d}",
            "staff_id": sid,
            "engagement_id": eid,
            "entry_date": entry_date,
            "hours": hours,
            "task_code": tc,
            "description": fake.sentence(nb_words=8),
        })
    return pd.DataFrame(rows)


def generate_file_access_logs(n: int, eng_df: pd.DataFrame, assigned_pairs: set,
                              staff_df: pd.DataFrame):
    """Generate file access logs. ~10% are unauthorized."""
    eids = eng_df["engagement_id"].tolist()
    sids = staff_df["staff_id"].tolist()
    unauthorized_fraction = 0.10
    rows = []
    file_names = [
        "GL_export.xlsx", "trial_balance.csv", "bank_statements.pdf",
        "audit_plan.docx", "tax_return_draft.pdf", "engagement_letter.pdf",
        "workpaper_A1.xlsx", "workpaper_B2.xlsx", "client_contracts.zip",
        "management_letter.docx", "revenue_schedule.csv", "payroll_data.xlsx",
        "fixed_assets.csv", "inventory_count.xlsx", "minutes_board.pdf",
    ]

    for i in range(n):
        eid = random.choice(eids)
        erow = eng_df[eng_df["engagement_id"] == eid].iloc[0]

        if random.random() < unauthorized_fraction:
            assigned_to_eng = {s for (e, s) in assigned_pairs if e == eid}
            candidates = [s for s in sids if s not in assigned_to_eng]
            if candidates:
                sid = random.choice(candidates)
            else:
                sid = random.choice(sids)
        else:
            assigned_to_eng = [s for (e, s) in assigned_pairs if e == eid]
            if assigned_to_eng:
                sid = random.choice(assigned_to_eng)
            else:
                sid = random.choice(sids)

        access_date = _rand_date(erow["start_date"], erow["end_date"])
        rows.append({
            "log_id": f"L{i+1:06d}",
            "staff_id": sid,
            "engagement_id": eid,
            "file_name": random.choice(file_names),
            "access_type": random.choice(ACCESS_TYPES),
            "access_timestamp": _rand_timestamp(access_date),
        })
    return pd.DataFrame(rows)


def generate_document_requests(n: int, eng_df: pd.DataFrame, scope_map: dict,
                               assigned_pairs: set, staff_df: pd.DataFrame):
    """Generate document requests. ~15% reference out-of-scope areas."""
    eids = eng_df["engagement_id"].tolist()
    sids = staff_df["staff_id"].tolist()
    out_of_scope_fraction = 0.15
    rows = []

    for i in range(n):
        eid = random.choice(eids)
        authorized = scope_map.get(eid, SCOPE_CATEGORIES[:2])

        # Pick requester (anyone assigned, or anyone)
        assigned_to_eng = [s for (e, s) in assigned_pairs if e == eid]
        sid = random.choice(assigned_to_eng) if assigned_to_eng else random.choice(sids)

        if random.random() < out_of_scope_fraction:
            outside = [c for c in SCOPE_CATEGORIES if c not in authorized]
            scope_area = random.choice(outside) if outside else random.choice(SCOPE_CATEGORIES)
        else:
            scope_area = random.choice(authorized)

        req_date = _rand_date("2024-01-01", "2025-12-01")
        rows.append({
            "request_id": f"R{i+1:05d}",
            "engagement_id": eid,
            "requester_staff_id": sid,
            "document_type": random.choice(DOC_TYPES),
            "request_date": req_date,
            "scope_area": scope_area,
            "status": random.choice(DOC_STATUSES),
        })
    return pd.DataFrame(rows)


# ── Workspace generation ────────────────────────────────────────────────

def write_engagement_scope_files(workspace: str, eng_df: pd.DataFrame, scope_map: dict,
                                 num_files: int):
    """Write engagement scope/budget YAML files (scalable)."""
    eids = eng_df["engagement_id"].tolist()
    per_file = max(1, len(eids) // num_files)
    file_idx = 0

    for start in range(0, len(eids), per_file):
        batch = eids[start:start + per_file]
        records = {}
        for eid in batch:
            erow = eng_df[eng_df["engagement_id"] == eid].iloc[0]
            budget_hours = round(random.uniform(200, 3000), 1)
            records[eid] = {
                "client_name": erow["client_name"],
                "engagement_type": erow["engagement_type"],
                "budget_hours": budget_hours,
                "authorized_scope_areas": scope_map[eid],
            }
        file_idx += 1
        path = os.path.join(workspace, f"engagement_scope_batch_{file_idx:03d}.yaml")
        with open(path, "w") as f:
            yaml.dump(records, f, default_flow_style=False, sort_keys=False)


def write_fixed_workspace_files(workspace: str, eng_df: pd.DataFrame):
    """Write non-scaling policy / config files."""
    # 1. flagging_policy.yaml
    policy = {
        "flag_types": {
            "UNAUTHORIZED_TIME": {
                "description": "Staff member logged time to an engagement they are not assigned to",
                "default_severity": "HIGH",
            },
            "BUDGET_OVERRUN": {
                "description": "Total billed hours exceed the engagement budget",
                "severity_rules": {
                    "overrun_pct_medium": 15,
                    "overrun_pct_high": 40,
                },
                "note": "If overrun percentage >= overrun_pct_high the severity is HIGH, "
                        "else if >= overrun_pct_medium the severity is MEDIUM, else no flag.",
            },
            "UNAUTHORIZED_ACCESS": {
                "description": "Staff member accessed engagement files without assignment",
                "default_severity": "HIGH",
            },
            "OUT_OF_SCOPE_REQUEST": {
                "description": "Document request references a scope area not authorized for the engagement",
                "default_severity": "MEDIUM",
            },
            "CERTIFICATION_VIOLATION": {
                "description": "Staff member assigned to an engagement that requires a higher certification level",
                "default_severity": "HIGH",
            },
        },
        "business_hours": {"start": 7, "end": 20},
    }
    with open(os.path.join(workspace, "flagging_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # 2. certification_requirements.csv
    cert_req = pd.DataFrame([
        {"engagement_type": "financial_audit",   "min_certification": "senior"},
        {"engagement_type": "tax_compliance",    "min_certification": "senior"},
        {"engagement_type": "advisory",          "min_certification": "manager"},
        {"engagement_type": "internal_controls", "min_certification": "senior"},
        {"engagement_type": "risk_assessment",   "min_certification": "manager"},
    ])
    cert_req.to_csv(os.path.join(workspace, "certification_requirements.csv"), index=False)

    # 3. task_code_mapping.json
    with open(os.path.join(workspace, "task_code_mapping.json"), "w") as f:
        json.dump(TASK_CODES, f, indent=2)

    # 4. review_guidelines.txt  (plain-text policy reference)
    guidelines = (
        "Partner Review Guidelines — Flagged Activities\n"
        "================================================\n\n"
        "Certification hierarchy (lowest to highest): junior, senior, manager, partner.\n"
        "A staff member's certification level must meet or exceed the minimum\n"
        "required for the engagement type they are assigned to.\n\n"
        "Only active assignments (is_active = 1) are considered when determining\n"
        "whether a staff member is authorized to bill time to or access files for\n"
        "a given engagement. Inactive or terminated assignments do not confer\n"
        "authorization.\n\n"
        "Budget overrun thresholds are defined in flagging_policy.yaml and apply\n"
        "to the ratio of total billed hours to budgeted hours for each engagement.\n"
        "The percentage is computed as ((total_hours - budget_hours) / budget_hours) * 100.\n\n"
        "Out-of-scope document requests are identified by comparing the scope_area\n"
        "field of each request against the authorized_scope_areas list in the\n"
        "corresponding engagement scope file.\n"
    )
    with open(os.path.join(workspace, "review_guidelines.txt"), "w") as f:
        f.write(guidelines)

    # 5. audit_methodology.md  (granularity / deduplication conventions)
    methodology = (
        "# Flag Compilation Methodology\n"
        "\n"
        "The following conventions govern how flagged activities are enumerated.\n"
        "They complement flagging_policy.yaml and review_guidelines.txt.\n"
        "\n"
        "## Unauthorized time\n"
        "\n"
        "Every time entry must be cross-referenced against the active engagement\n"
        "assignments. Each individual time entry logged by a staff member who is\n"
        "not actively assigned to that engagement is flagged separately — one\n"
        "flag per time entry record.\n"
        "\n"
        "## Unauthorized access\n"
        "\n"
        "Every file access event must be checked against the active assignments\n"
        "for that engagement. Each individual access event by a staff member who\n"
        "is not actively assigned to the engagement is flagged separately — one\n"
        "flag per access log record.\n"
        "\n"
        "## Out-of-scope document requests\n"
        "\n"
        "Every client document request whose scope area falls outside the\n"
        "authorized scope areas for its engagement is flagged separately — one\n"
        "flag per request record.\n"
        "\n"
        "## Budget overruns\n"
        "\n"
        "Evaluated once per engagement: aggregate the total hours billed to the\n"
        "engagement across all time entries (regardless of who billed them) and\n"
        "compare against the budgeted hours defined in the engagement scope\n"
        "definitions. Engagements below the medium overrun threshold are not\n"
        "flagged. Severity is determined by which threshold the overrun\n"
        "percentage crosses, per flagging_policy.yaml.\n"
        "\n"
        "## Certification violations\n"
        "\n"
        "Evaluated over active assignments only: the assigned staff member must\n"
        "hold at least the minimum certification required for the engagement\n"
        "type. When a single staff member has multiple active assignments to the\n"
        "same engagement, exactly one flag is produced per unique\n"
        "engagement-staff pair.\n"
    )
    with open(os.path.join(workspace, "audit_methodology.md"), "w") as f:
        f.write(methodology)


# ── Main ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # Generate core entities
    staff_df = generate_staff(n_rows)
    eng_df = generate_engagements(n_rows, staff_df)

    # Scope map (used for workspace files + document requests)
    scope_map = {}
    for _, row in eng_df.iterrows():
        scope_map[row["engagement_id"]] = _pick_scope_areas(row["engagement_type"])

    assign_df, assigned_pairs = generate_assignments(n_rows * 2, eng_df, staff_df)
    time_df = generate_time_entries(n_rows * 5, eng_df, assigned_pairs, staff_df)
    access_df = generate_file_access_logs(n_rows * 4, eng_df, assigned_pairs, staff_df)
    docreq_df = generate_document_requests(n_rows * 2, eng_df, scope_map, assigned_pairs, staff_df)

    # Write DB
    conn = sqlite3.connect(args.db_path)
    _create_tables(conn)
    staff_df.to_sql("staff", conn, if_exists="replace", index=False)
    eng_df.to_sql("engagements", conn, if_exists="replace", index=False)
    assign_df.to_sql("assignments", conn, if_exists="replace", index=False)
    time_df.to_sql("time_entries", conn, if_exists="replace", index=False)
    access_df.to_sql("file_access_logs", conn, if_exists="replace", index=False)
    docreq_df.to_sql("document_requests", conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()

    # Write workspace files
    write_engagement_scope_files(args.workspace, eng_df, scope_map, n_files)
    write_fixed_workspace_files(args.workspace, eng_df)


def _create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS engagements (
        engagement_id TEXT PRIMARY KEY, client_name TEXT,
        engagement_type TEXT, start_date TEXT, end_date TEXT,
        status TEXT, partner_id TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS staff (
        staff_id TEXT PRIMARY KEY, name TEXT, role TEXT,
        certification_level TEXT, department TEXT, hire_date TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS assignments (
        assignment_id TEXT PRIMARY KEY, engagement_id TEXT,
        staff_id TEXT, assigned_role TEXT, start_date TEXT,
        end_date TEXT, is_active INTEGER,
        FOREIGN KEY (engagement_id) REFERENCES engagements(engagement_id),
        FOREIGN KEY (staff_id) REFERENCES staff(staff_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS time_entries (
        entry_id TEXT PRIMARY KEY, staff_id TEXT,
        engagement_id TEXT, entry_date TEXT, hours REAL,
        task_code TEXT, description TEXT,
        FOREIGN KEY (staff_id) REFERENCES staff(staff_id),
        FOREIGN KEY (engagement_id) REFERENCES engagements(engagement_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS file_access_logs (
        log_id TEXT PRIMARY KEY, staff_id TEXT,
        engagement_id TEXT, file_name TEXT, access_type TEXT,
        access_timestamp TEXT,
        FOREIGN KEY (staff_id) REFERENCES staff(staff_id),
        FOREIGN KEY (engagement_id) REFERENCES engagements(engagement_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS document_requests (
        request_id TEXT PRIMARY KEY, engagement_id TEXT,
        requester_staff_id TEXT, document_type TEXT,
        request_date TEXT, scope_area TEXT, status TEXT,
        FOREIGN KEY (engagement_id) REFERENCES engagements(engagement_id),
        FOREIGN KEY (requester_staff_id) REFERENCES staff(staff_id))""")
    conn.commit()


if __name__ == "__main__":
    main()
