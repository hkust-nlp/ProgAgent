#!/usr/bin/env python3
"""Data generation for privileged-document clawback task."""

import argparse
import sqlite3
import os
import json
import csv
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 160,
    "num_workspace_files": 16,
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def create_tables(conn):
    cursor = conn.cursor()
    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS employees (
        employee_id   INTEGER PRIMARY KEY,
        full_name     TEXT NOT NULL,
        email_address TEXT NOT NULL,
        department    TEXT NOT NULL,
        role          TEXT NOT NULL,
        bar_number    TEXT,
        hire_date     TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS emails (
        email_id         INTEGER PRIMARY KEY,
        internal_ref     TEXT NOT NULL UNIQUE,
        sender_id        INTEGER NOT NULL,
        sent_date        TEXT NOT NULL,
        subject          TEXT NOT NULL,
        has_attachment   INTEGER NOT NULL DEFAULT 0,
        confidential_flag INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (sender_id) REFERENCES employees(employee_id)
    );

    CREATE TABLE IF NOT EXISTS email_recipients (
        id             INTEGER PRIMARY KEY,
        email_id       INTEGER NOT NULL,
        employee_id    INTEGER NOT NULL,
        recipient_type TEXT NOT NULL CHECK(recipient_type IN ('TO','CC','BCC')),
        FOREIGN KEY (email_id)   REFERENCES emails(email_id),
        FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
    );

    CREATE TABLE IF NOT EXISTS privilege_log (
        log_id                INTEGER PRIMARY KEY,
        email_ref             TEXT NOT NULL,
        privilege_type        TEXT NOT NULL,
        basis                 TEXT NOT NULL,
        date_logged           TEXT NOT NULL,
        reviewing_attorney_id INTEGER NOT NULL,
        status                TEXT NOT NULL CHECK(status IN ('confirmed','pending','waived')),
        FOREIGN KEY (reviewing_attorney_id) REFERENCES employees(employee_id)
    );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROLE_POOLS = {
    "Legal":            ["Paralegal", "Legal Assistant", "Legal Analyst", "Compliance Officer"],
    "Engineering":      ["Software Engineer", "Engineering Manager", "QA Engineer", "DevOps Engineer", "Data Engineer"],
    "Sales":            ["Sales Representative", "Account Manager", "Sales Director", "Business Analyst"],
    "Marketing":        ["Marketing Analyst", "Content Manager", "Brand Strategist", "Marketing Director"],
    "Finance":          ["Financial Analyst", "Controller", "Accountant", "Finance Manager", "Treasury Analyst"],
    "Human Resources":  ["HR Specialist", "Recruiter", "HR Manager", "Benefits Coordinator"],
    "Operations":       ["Operations Manager", "Project Manager", "Logistics Coordinator", "Process Analyst"],
    "IT":               ["IT Administrator", "Network Engineer", "Security Analyst", "IT Manager", "Systems Architect"],
    "Compliance":       ["Compliance Analyst", "Compliance Manager", "Audit Specialist", "Risk Analyst"],
    "Executive":        ["VP Strategy", "VP Operations", "Chief of Staff", "Executive Assistant"],
}

DEPARTMENTS = list(ROLE_POOLS.keys())

LEGAL_SUBJECTS = [
    "Re: Legal review of merger agreement",
    "FW: Draft settlement terms",
    "Litigation hold notice",
    "Analysis of patent claims",
    "Re: Damages calculation update",
    "Contract indemnification clause review",
    "Re: Regulatory compliance concerns",
    "Privileged assessment of IP portfolio",
    "FW: Deposition preparation materials",
    "Re: Amendments to licensing agreement",
    "Antitrust risk assessment memo",
    "Re: Employment dispute approach",
    "FW: Insurance coverage opinion",
    "Re: Board resolution legal review",
    "Trademark opposition strategy",
    "Re: Discovery response review",
    "FW: Expert witness engagement",
    "Re: Confidential investigation update",
    "Sanctions risk memorandum",
    "Re: Non-compete enforceability analysis",
]

GENERAL_SUBJECTS = [
    "Weekly team standup agenda",
    "Budget forecast Q4 2025",
    "New hire onboarding schedule",
    "Product launch timeline update",
    "RE: Office renovation plans",
    "FW: Vendor evaluation summary",
    "Q3 performance review submissions",
    "Holiday party planning committee",
    "System maintenance window notification",
    "RE: Client feedback survey results",
    "FW: Travel reimbursement policy",
    "Monthly all-hands meeting notes",
    "RE: Conference room booking policy",
    "Training session registration reminder",
    "FW: IT security awareness update",
    "RE: Quarterly business review prep",
    "Team building event RSVP",
    "FW: Expense report deadline",
    "RE: New project kickoff meeting",
    "Facilities request form update",
]

PRIVILEGE_BASES = [
    "Communication seeking legal advice from in-house counsel",
    "Attorney mental impressions and legal analysis",
    "Litigation strategy discussion with counsel",
    "Legal opinion provided by in-house attorney",
    "Work product prepared in anticipation of litigation",
    "Joint defense communication between co-defendants' counsel",
    "Confidential legal assessment of regulatory risk",
    "Attorney-supervised investigation materials",
    "Legal memorandum analyzing potential liability",
    "Privileged communication regarding settlement strategy",
]


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

def generate_employees(n, fake, rng):
    n_attorneys = max(int(n * 0.18), 3)
    n_gc = max(int(n * 0.025), 1)

    records = []
    for i in range(n):
        eid = i + 1
        name = fake.unique.name()

        if i < n_attorneys:
            dept = "Legal"
            role = "Attorney"
            bar = f"BAR{rng.randint(100000, 999999)}"
        elif i < n_attorneys + n_gc:
            dept = "Legal"
            role = "General Counsel"
            bar = f"BAR{rng.randint(100000, 999999)}"
        else:
            dept = str(rng.choice(DEPARTMENTS))
            role = str(rng.choice(ROLE_POOLS[dept]))
            bar = None

        email_addr = (
            name.lower().replace(" ", ".").replace("'", "").replace("-", "")
            + "@acmecorp.com"
        )
        hire = date(2015, 1, 1) + timedelta(days=int(rng.randint(0, 3650)))
        records.append((eid, name, email_addr, dept, role, bar, hire.isoformat()))
    return records


def generate_emails(n, employees, fake, rng):
    emp_ids = [e[0] for e in employees]
    records = []
    for i in range(n):
        eid = i + 1
        iref = f"EM-{eid:05d}"
        sid = int(rng.choice(emp_ids))
        if rng.random() < 0.4:
            subj = str(rng.choice(LEGAL_SUBJECTS))
        else:
            subj = str(rng.choice(GENERAL_SUBJECTS))
        sdate = date(2024, 1, 1) + timedelta(days=int(rng.randint(0, 545)))
        has_att = int(rng.random() < 0.3)
        conf = int(rng.random() < 0.2)
        records.append((eid, iref, sid, sdate.isoformat(), subj, has_att, conf))
    return records


def generate_recipients(emails, employees, rng):
    emp_ids = [e[0] for e in employees]
    records = []
    rid = 1
    for email in emails:
        email_id = email[0]
        sender_id = email[2]
        n_recip = int(rng.randint(1, 5))
        available = [eid for eid in emp_ids if eid != sender_id]
        chosen = rng.choice(available, size=min(n_recip, len(available)), replace=False)
        for j, emp_id in enumerate(chosen):
            if j == 0:
                rtype = "TO"
            elif rng.random() < 0.25:
                rtype = "BCC"
            else:
                rtype = str(rng.choice(["TO", "CC"]))
            records.append((rid, email_id, int(emp_id), rtype))
            rid += 1
    return records


def generate_privilege_log(n, emails, attorney_email_ids, attorney_emp_ids, fake, rng):
    privilege_types = ["attorney-client", "work-product", "joint-defense"]
    type_weights = np.array([0.50, 0.35, 0.15])
    statuses = ["confirmed", "pending", "waived"]
    status_weights = np.array([0.50, 0.30, 0.20])

    email_id_to_ref = {e[0]: e[1] for e in emails}

    attorney_email_refs = [email_id_to_ref[eid] for eid in attorney_email_ids if eid in email_id_to_ref]
    all_email_refs = [e[1] for e in emails]
    non_attorney_email_refs = [r for r in all_email_refs if r not in set(attorney_email_refs)]
    atty_ids = list(attorney_emp_ids)

    n_atty_entries = int(n * 0.45)
    n_non_atty_entries = int(n * 0.25)
    n_doc_entries = n - n_atty_entries - n_non_atty_entries

    records = []
    lid = 1

    # Attorney-involved email entries
    if attorney_email_refs:
        chosen = rng.choice(
            attorney_email_refs,
            size=min(n_atty_entries, len(attorney_email_refs)),
            replace=len(attorney_email_refs) < n_atty_entries,
        )
        for ref in chosen:
            ptype = str(rng.choice(privilege_types, p=type_weights))
            status = str(rng.choice(statuses, p=status_weights))
            basis = str(rng.choice(PRIVILEGE_BASES))
            dlogged = (date(2025, 1, 1) + timedelta(days=int(rng.randint(0, 270)))).isoformat()
            rev = int(rng.choice(atty_ids))
            records.append((lid, str(ref), ptype, basis, dlogged, rev, status))
            lid += 1

    # Non-attorney email entries
    if non_attorney_email_refs:
        chosen = rng.choice(
            non_attorney_email_refs,
            size=min(n_non_atty_entries, len(non_attorney_email_refs)),
            replace=len(non_attorney_email_refs) < n_non_atty_entries,
        )
        for ref in chosen:
            ptype = str(rng.choice(privilege_types, p=type_weights))
            status = str(rng.choice(statuses, p=status_weights))
            basis = str(rng.choice(PRIVILEGE_BASES))
            dlogged = (date(2025, 1, 1) + timedelta(days=int(rng.randint(0, 270)))).isoformat()
            rev = int(rng.choice(atty_ids))
            records.append((lid, str(ref), ptype, basis, dlogged, rev, status))
            lid += 1

    # Non-email document entries
    for j in range(n_doc_entries):
        doc_ref = f"DOC-{j + 1:05d}"
        ptype = str(rng.choice(privilege_types, p=type_weights))
        status = str(rng.choice(statuses, p=status_weights))
        basis = str(rng.choice(PRIVILEGE_BASES))
        dlogged = (date(2025, 1, 1) + timedelta(days=int(rng.randint(0, 270)))).isoformat()
        rev = int(rng.choice(atty_ids))
        records.append((lid, doc_ref, ptype, basis, dlogged, rev, status))
        lid += 1

    return records


def generate_production_files(n_docs, n_files, emails, priv_log, attorney_email_ids, workspace, fake, rng):
    email_refs = [e[1] for e in emails]
    priv_email_refs = set(p[1] for p in priv_log if p[1].startswith("EM-"))

    n_email_docs = int(n_docs * 0.38)
    n_other_docs = n_docs - n_email_docs

    priv_refs_list = [r for r in email_refs if r in priv_email_refs]
    non_priv_refs_list = [r for r in email_refs if r not in priv_email_refs]

    n_from_priv = min(int(n_email_docs * 0.65), len(priv_refs_list))
    n_from_non = min(n_email_docs - n_from_priv, len(non_priv_refs_list))

    chosen_priv = list(rng.choice(priv_refs_list, size=n_from_priv, replace=False)) if n_from_priv else []
    chosen_non = list(rng.choice(non_priv_refs_list, size=n_from_non, replace=False)) if n_from_non else []
    chosen_email_refs = list(chosen_priv) + list(chosen_non)
    rng.shuffle(chosen_email_refs)

    docs = []
    bates = 1

    for ref in chosen_email_refs:
        pdate = date(2025, 6, 1) + timedelta(days=int(rng.randint(0, 213)))
        docs.append({
            "bates_number": f"PROD-{bates:06d}",
            "document_type": "email",
            "source_ref": str(ref),
            "page_count": str(int(rng.randint(1, 15))),
            "production_date": pdate.isoformat(),
            "producing_party": "Acme Corporation",
        })
        bates += 1

    other_types = ["memo", "contract", "report", "presentation", "spreadsheet"]
    for i in range(n_other_docs):
        pdate = date(2025, 6, 1) + timedelta(days=int(rng.randint(0, 213)))
        docs.append({
            "bates_number": f"PROD-{bates:06d}",
            "document_type": str(rng.choice(other_types)),
            "source_ref": f"MISC-{i + 1:05d}",
            "page_count": str(int(rng.randint(1, 50))),
            "production_date": pdate.isoformat(),
            "producing_party": "Acme Corporation",
        })
        bates += 1

    rng.shuffle(docs)

    # Split into batch files
    docs_per_file = len(docs) // n_files
    remainder = len(docs) % n_files
    idx = 0
    for f_idx in range(n_files):
        count = docs_per_file + (1 if f_idx < remainder else 0)
        batch_id = f"BATCH-{f_idx + 1:03d}"
        batch_docs = docs[idx : idx + count]
        for d in batch_docs:
            d["batch_id"] = batch_id

        fpath = os.path.join(workspace, f"production_batch_{f_idx + 1:03d}.csv")
        with open(fpath, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "bates_number", "document_type", "source_ref",
                    "page_count", "production_date", "producing_party", "batch_id",
                ],
            )
            writer.writeheader()
            writer.writerows(batch_docs)
        idx += count


def write_config_files(workspace):
    # ---- privilege_criteria.yaml ----
    yaml_text = """\
# Privilege Review Criteria Configuration
# Applicable to: Acme Corp. v. Globex Industries, Case No. 2025-CV-04821
# Last updated: 2025-08-15

triggering_roles:
  - Attorney
  - General Counsel

clawback_eligible_statuses:
  - confirmed
  - pending

privilege_assessment_notes: >
  Any communication in which at least one participant holds a
  triggering role is potentially subject to attorney-client privilege.
  A corresponding privilege log entry with an eligible status must
  exist for the document to qualify for clawback.
"""
    with open(os.path.join(workspace, "privilege_criteria.yaml"), "w") as f:
        f.write(yaml_text)

    # ---- clawback_rules.json ----
    rules = {
        "eligible_privilege_types": ["attorney-client", "work-product"],
        "exclude_waived": True,
        "production_date_cutoff": "2025-11-30",
        "require_attorney_participant": True,
        "output_sort_order": "bates_number_asc",
        "rule_version": "2.1",
        "effective_date": "2025-09-01",
    }
    with open(os.path.join(workspace, "clawback_rules.json"), "w") as f:
        json.dump(rules, f, indent=2)

    # ---- case_summary.txt ----
    case_text = """\
CASE SUMMARY
============
Acme Corporation v. Globex Industries
Case No.: 2025-CV-04821
Court: United States District Court, Southern District of New York
Judge: Hon. Patricia M. Clearwater

BACKGROUND
----------
Acme Corporation filed suit against Globex Industries alleging breach of
a joint development agreement and misappropriation of trade secrets related
to proprietary manufacturing processes for advanced composite materials.

CURRENT STATUS
--------------
The case is in the discovery phase. Acme Corporation has produced multiple
batches of documents to opposing counsel per the agreed-upon production
schedule. A post-production privilege review has been initiated after an
internal audit flagged potential inadvertent production of privileged
attorney-client communications and work-product materials.

APPLICABLE RULES
----------------
Under Federal Rule of Civil Procedure 26(b)(5)(B), if information produced
in discovery is subject to a claim of privilege, the producing party may
notify the receiving party of the claim. The receiving party must then
promptly return, sequester, or destroy the specified information and any
copies it has made.

The privilege review team must identify all qualifying documents and
prepare a formal clawback request listing specific Bates numbers.
"""
    with open(os.path.join(workspace, "case_summary.txt"), "w") as f:
        f.write(case_text)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(db_path, workspace):
    os.makedirs(workspace, exist_ok=True)

    rng = np.random.RandomState(42)
    random.seed(42)
    fake = Faker()
    Faker.seed(42)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    create_tables(conn)
    cursor = conn.cursor()

    # 1. Employees
    employees = generate_employees(n_rows, fake, rng)
    cursor.executemany("INSERT INTO employees VALUES (?,?,?,?,?,?,?)", employees)

    # 2. Emails
    emails = generate_emails(n_rows, employees, fake, rng)
    cursor.executemany("INSERT INTO emails VALUES (?,?,?,?,?,?,?)", emails)

    # 3. Email recipients
    recipients = generate_recipients(emails, employees, rng)
    cursor.executemany("INSERT INTO email_recipients VALUES (?,?,?,?)", recipients)

    # Identify attorney-involved emails
    attorney_emp_ids = set(e[0] for e in employees if e[4] in ("Attorney", "General Counsel"))
    email_id_to_ref = {e[0]: e[1] for e in emails}
    attorney_email_ids = set()
    for email in emails:
        if email[2] in attorney_emp_ids:
            attorney_email_ids.add(email[0])
    for r in recipients:
        if r[2] in attorney_emp_ids:
            attorney_email_ids.add(r[1])

    # 4. Privilege log
    priv_log = generate_privilege_log(n_rows, emails, attorney_email_ids, attorney_emp_ids, fake, rng)
    cursor.executemany("INSERT INTO privilege_log VALUES (?,?,?,?,?,?,?)", priv_log)

    conn.commit()

    # 5. Production batch files
    generate_production_files(n_rows, n_files, emails, priv_log, attorney_email_ids, workspace, fake, rng)

    # 6. Config files
    write_config_files(workspace)

    conn.close()
    print(f"Data generated: {db_path}, workspace: {workspace}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
