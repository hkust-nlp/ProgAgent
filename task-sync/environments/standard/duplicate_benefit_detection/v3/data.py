#!/usr/bin/env python3
"""
Duplicate Benefit Application Detection - Data Generator
Generates database and workspace files for cross-referencing applicant records.
"""

import argparse
import sqlite3
import os
import json
import csv
import random
import numpy as np
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 800,
    "num_workspace_files": 40,
}

PROGRAMS = ["SNAP", "TANF", "Medicaid", "CHIP", "WIC", "LIHEAP", "Section8"]
RELATIONSHIPS = ["spouse", "child", "parent", "sibling", "grandchild", "other"]
INCOME_SOURCES = ["employment", "self_employment", "social_security", "disability",
                  "unemployment", "pension"]
VERIFICATION_METHODS = ["pay_stub", "tax_return", "employer_letter",
                        "bank_statement", "self_declaration"]
DOC_TYPES = ["drivers_license", "passport", "state_id", "military_id", "tribal_id"]
CHANNELS = ["online_portal", "in_person", "mail", "phone", "fax"]
STATUSES = ["pending", "approved", "denied", "under_review"]


def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)
    os.makedirs(workspace, exist_ok=True)

    n_app = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # --- Duplicate counts (scale-proportional) ---
    n_dup_ssn = max(3, n_app // 30)
    n_dup_name = max(2, n_app // 40)
    n_dup_hh = max(2, n_app // 40)
    n_dup_doc = max(2, n_app // 40)
    n_dup_addr = max(1, n_app // 80)

    # --- Create DB ---
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS applicants (
        applicant_id TEXT PRIMARY KEY,
        first_name TEXT,
        last_name TEXT,
        ssn TEXT,
        dob TEXT,
        address TEXT,
        city TEXT,
        state TEXT,
        zip_code TEXT,
        phone TEXT,
        email TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS household_members (
        member_id TEXT PRIMARY KEY,
        applicant_id TEXT,
        relationship TEXT,
        first_name TEXT,
        last_name TEXT,
        dob TEXT,
        ssn TEXT,
        FOREIGN KEY (applicant_id) REFERENCES applicants(applicant_id)
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS applications (
        application_id TEXT PRIMARY KEY,
        applicant_id TEXT,
        program_type TEXT,
        submission_date TEXT,
        status TEXT,
        prior_application_id TEXT,
        requested_amount REAL,
        FOREIGN KEY (applicant_id) REFERENCES applicants(applicant_id)
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS income_verifications (
        verification_id TEXT PRIMARY KEY,
        applicant_id TEXT,
        income_source TEXT,
        annual_amount REAL,
        verification_date TEXT,
        verification_method TEXT,
        employer_name TEXT,
        FOREIGN KEY (applicant_id) REFERENCES applicants(applicant_id)
    )""")

    # =========================================================
    # 1. Generate base applicants
    # =========================================================
    applicants = []
    seen_ssns = set()
    for i in range(n_app):
        aid = f"APP-{i+1:04d}"
        fn = fake.first_name()
        ln = fake.last_name()
        ssn = fake.ssn()
        while ssn in seen_ssns:
            ssn = fake.ssn()
        seen_ssns.add(ssn)
        dob = fake.date_of_birth(minimum_age=18, maximum_age=75).isoformat()
        addr = fake.street_address()
        city = fake.city()
        state = fake.state_abbr()
        zc = fake.zipcode()
        phone = fake.phone_number()
        email = fake.email()
        applicants.append({
            "applicant_id": aid, "first_name": fn, "last_name": ln,
            "ssn": ssn, "dob": dob, "address": addr, "city": city,
            "state": state, "zip_code": zc, "phone": phone, "email": email,
        })

    # =========================================================
    # 2. Inject duplicates
    # =========================================================
    all_indices = list(range(n_app))
    random.shuffle(all_indices)
    ptr = 0

    def take(n):
        nonlocal ptr
        out = all_indices[ptr:ptr + n]
        ptr += n
        return out

    # 2a. SSN duplicates
    ssn_slots = take(n_dup_ssn * 2)
    dup_ssn_pairs = []
    for k in range(0, len(ssn_slots), 2):
        src, tgt = ssn_slots[k], ssn_slots[k + 1]
        applicants[tgt]["ssn"] = applicants[src]["ssn"]
        pair = tuple(sorted([applicants[src]["applicant_id"],
                             applicants[tgt]["applicant_id"]]))
        dup_ssn_pairs.append(pair)

    # 2b. Name+DOB duplicates (keep different SSN)
    name_slots = take(n_dup_name * 2)
    dup_name_pairs = []
    for k in range(0, len(name_slots), 2):
        src, tgt = name_slots[k], name_slots[k + 1]
        applicants[tgt]["first_name"] = applicants[src]["first_name"]
        applicants[tgt]["last_name"] = applicants[src]["last_name"]
        applicants[tgt]["dob"] = applicants[src]["dob"]
        pair = tuple(sorted([applicants[src]["applicant_id"],
                             applicants[tgt]["applicant_id"]]))
        dup_name_pairs.append(pair)

    # 2c. Household overlap pairs (selected, injected after member generation)
    hh_slots = take(n_dup_hh * 2)
    dup_hh_pairs_indices = [(hh_slots[k], hh_slots[k + 1])
                            for k in range(0, len(hh_slots), 2)]

    # 2d. Identity-doc duplicate indices (handled during workspace generation)
    doc_slots = take(n_dup_doc * 2)
    dup_doc_pairs_indices = [(doc_slots[k], doc_slots[k + 1])
                            for k in range(0, len(doc_slots), 2)]

    # 2e. Address+income duplicates
    addr_slots = take(n_dup_addr * 2)
    dup_addr_pairs = []
    for k in range(0, len(addr_slots), 2):
        src, tgt = addr_slots[k], addr_slots[k + 1]
        applicants[tgt]["address"] = applicants[src]["address"]
        applicants[tgt]["city"] = applicants[src]["city"]
        applicants[tgt]["state"] = applicants[src]["state"]
        applicants[tgt]["zip_code"] = applicants[src]["zip_code"]
        pair = tuple(sorted([applicants[src]["applicant_id"],
                             applicants[tgt]["applicant_id"]]))
        dup_addr_pairs.append((pair, src, tgt))

    # Insert applicants
    cur.executemany(
        "INSERT INTO applicants VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(a["applicant_id"], a["first_name"], a["last_name"], a["ssn"],
          a["dob"], a["address"], a["city"], a["state"], a["zip_code"],
          a["phone"], a["email"]) for a in applicants])

    # =========================================================
    # 3. Generate household members
    # =========================================================
    all_members = []
    mem_counter = 0
    applicant_members = {a["applicant_id"]: [] for a in applicants}

    for i, app in enumerate(applicants):
        aid = app["applicant_id"]
        n_mem = random.randint(1, 5)
        for _ in range(n_mem):
            mem_counter += 1
            mid = f"MEM-{mem_counter:05d}"
            rel = random.choice(RELATIONSHIPS)
            fn = fake.first_name()
            ln = app["last_name"] if random.random() < 0.6 else fake.last_name()
            dob = fake.date_of_birth(minimum_age=0, maximum_age=90).isoformat()
            mssn = fake.ssn()
            rec = (mid, aid, rel, fn, ln, dob, mssn)
            all_members.append(rec)
            applicant_members[aid].append(rec)

    # Inject household overlaps: copy 2 members from src to tgt
    dup_hh_pairs = []
    for src_idx, tgt_idx in dup_hh_pairs_indices:
        src_aid = applicants[src_idx]["applicant_id"]
        tgt_aid = applicants[tgt_idx]["applicant_id"]
        src_mems = applicant_members[src_aid]
        share_count = min(2, len(src_mems))
        shared = random.sample(src_mems, share_count)
        for sm in shared:
            mem_counter += 1
            new_mid = f"MEM-{mem_counter:05d}"
            new_rec = (new_mid, tgt_aid, sm[2], sm[3], sm[4], sm[5], sm[6])
            all_members.append(new_rec)
            applicant_members[tgt_aid].append(new_rec)
        pair = tuple(sorted([src_aid, tgt_aid]))
        dup_hh_pairs.append(pair)

    cur.executemany(
        "INSERT INTO household_members VALUES (?,?,?,?,?,?,?)", all_members)

    # =========================================================
    # 4. Generate applications
    # =========================================================
    all_applications = []
    app_id_counter = 0

    # For address+income pairs, ensure they share at least one program
    addr_shared_programs = {}
    for pair, src_idx, tgt_idx in dup_addr_pairs:
        prog = random.choice(PROGRAMS)
        addr_shared_programs[src_idx] = prog
        addr_shared_programs[tgt_idx] = prog

    for i, app in enumerate(applicants):
        aid = app["applicant_id"]
        n_apps = random.randint(1, 3)
        for j in range(n_apps):
            app_id_counter += 1
            appl_id = f"APPL-{app_id_counter:05d}"
            if j == 0 and i in addr_shared_programs:
                prog = addr_shared_programs[i]
            else:
                prog = random.choice(PROGRAMS)
            sub_date = fake.date_between(
                start_date="-2y", end_date="today").isoformat()
            status = random.choice(STATUSES)
            prior = ""
            if random.random() < 0.15 and app_id_counter > 10:
                prior = f"APPL-{random.randint(1, app_id_counter - 1):05d}"
            amount = round(random.uniform(500, 15000), 2)
            all_applications.append(
                (appl_id, aid, prog, sub_date, status, prior, amount))

    cur.executemany(
        "INSERT INTO applications VALUES (?,?,?,?,?,?,?)", all_applications)

    # =========================================================
    # 5. Generate income verifications
    # =========================================================
    all_income = []
    ver_counter = 0
    applicant_incomes = {}  # aid -> list of (annual_amount, employer)

    for i, app in enumerate(applicants):
        aid = app["applicant_id"]
        n_ver = random.randint(1, 2)
        records = []
        for _ in range(n_ver):
            ver_counter += 1
            vid = f"VER-{ver_counter:05d}"
            src = random.choice(INCOME_SOURCES)
            amount = round(random.uniform(8000, 120000), 2)
            vdate = fake.date_between(
                start_date="-1y", end_date="today").isoformat()
            method = random.choice(VERIFICATION_METHODS)
            employer = fake.company() if src in (
                "employment", "self_employment") else ""
            all_income.append((vid, aid, src, amount, vdate, method, employer))
            records.append((amount, employer))
        applicant_incomes[aid] = records

    # For address+income pairs, make ALL employer-verified income records similar
    for pair, src_idx, tgt_idx in dup_addr_pairs:
        src_aid = applicants[src_idx]["applicant_id"]
        tgt_aid = applicants[tgt_idx]["applicant_id"]
        if applicant_incomes[src_aid]:
            base_amount = applicant_incomes[src_aid][0][0]
            for idx in range(len(all_income)):
                if all_income[idx][1] == tgt_aid:
                    similar_amount = round(
                        base_amount * random.uniform(0.93, 1.07), 2)
                    old = all_income[idx]
                    all_income[idx] = (old[0], old[1], old[2], similar_amount,
                                       old[4], old[5], old[6])

    cur.executemany(
        "INSERT INTO income_verifications VALUES (?,?,?,?,?,?,?)", all_income)

    conn.commit()

    # Build income lookup for workspace generation
    income_by_applicant = {}
    for rec in all_income:
        vid, aid, src, amount, vdate, method, employer = rec
        if aid not in income_by_applicant:
            income_by_applicant[aid] = []
        income_by_applicant[aid].append({
            "verification_id": vid, "income_source": src,
            "annual_amount": amount, "verification_date": vdate,
            "verification_method": method, "employer_name": employer,
        })

    # =========================================================
    # 6. Generate workspace files
    # =========================================================

    # --- 6a. Fixed files ---

    # detection_rules.yaml
    rules = {
        "duplicate_detection_rules": {
            "SSN_MATCH": {
                "enabled": True,
                "confidence": 1.0,
                "description": "Two applicants share the same Social Security Number",
                "action": "flag_for_review",
            },
            "NAME_DOB_MATCH": {
                "enabled": True,
                "confidence": 0.9,
                "description": "Two applicants share first name, last name, and date of birth but have different SSNs",
                "action": "flag_for_review",
            },
            "HOUSEHOLD_OVERLAP": {
                "enabled": True,
                "min_shared_members": 2,
                "confidence": 0.85,
                "description": "Two applicants share two or more household members identified by matching SSN",
                "action": "flag_for_review",
            },
            "ID_DOC_MATCH": {
                "enabled": True,
                "confidence": 0.95,
                "description": "Two applicants presented identity documents with the same document number",
                "action": "flag_for_review",
            },
            "ADDRESS_INCOME_MATCH": {
                "enabled": True,
                "income_tolerance_pct": 15,
                "income_source": "employer_verified",
                "income_comparison": "max",
                "confidence": 0.7,
                "description": "Two applicants at the same address applied for the same program with employer-verified incomes within tolerance, using the maximum reported income per applicant for comparison",
                "action": "secondary_review",
            },
        },
        "confidence_threshold": 0.6,
        "output_format": {
            "filename": "flagged_cases.csv",
            "columns": [
                "case_id", "applicant_id_1", "applicant_id_2",
                "duplicate_type", "confidence_score",
                "programs_affected", "recommended_action",
            ],
            "sort_order": "confidence_score descending, then applicant_id_1 ascending, then applicant_id_2 ascending",
            "case_id_format": "CASE-NNN zero-padded to 3 digits starting at 001",
            "applicant_id_order": "lower ID first as applicant_id_1",
            "programs_affected_format": "semicolon-separated list of programs both applicants applied for alphabetically sorted",
            "confidence_score_format": "two decimal places",
        },
    }
    with open(os.path.join(workspace, "detection_rules.yaml"), "w") as f:
        yaml.dump(rules, f, default_flow_style=False, sort_keys=False)

    # program_policies.md
    policies = """This document outlines the benefit program policies relevant to duplicate detection.

Each applicant may apply to multiple programs simultaneously. However, certain program
combinations are subject to additional scrutiny when a duplicate is detected:

SNAP and TANF: These programs serve overlapping populations. A duplicate applicant
receiving both is considered high priority for overpayment review.

Medicaid and CHIP: These are mutually exclusive for a single individual (CHIP covers
children not eligible for Medicaid). Duplicate detection should flag if the same
individual appears in both.

Section8 and LIHEAP: Both address housing costs. Dual enrollment by a duplicate
applicant may indicate overpayment.

WIC: This program is independent and has its own duplicate screening. Include
in the programs_affected list but it does not elevate review priority.

When determining programs_affected for a flagged pair, list all programs for which
both applicants in the pair have submitted applications, regardless of application
status. Sort the programs alphabetically and separate them with semicolons.

The recommended_action for each flagged case is determined by the duplicate type
as specified in the detection rules configuration.
"""
    with open(os.path.join(workspace, "program_policies.md"), "w") as f:
        f.write(policies)

    # --- 6b. Scalable files ---
    n_csv = max(1, round(n_files * 0.4))
    n_json = max(1, round(n_files * 0.3))
    n_txt = max(1, round(n_files * 0.2))
    n_yaml = max(1, n_files - n_csv - n_json - n_txt)

    def split_indices(total, n_parts):
        """Split range(total) into n_parts roughly equal sublists."""
        parts = []
        base = total // n_parts
        rem = total % n_parts
        start = 0
        for p in range(n_parts):
            end = start + base + (1 if p < rem else 0)
            parts.append(list(range(start, end)))
            start = end
        return parts

    # --- CSV: submission_batch files ---
    csv_splits = split_indices(len(all_applications), n_csv)
    for fidx in range(n_csv):
        fname = f"submission_batch_{fidx + 1:03d}.csv"
        rows = [all_applications[j] for j in csv_splits[fidx]]
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "application_id", "applicant_id", "program_type",
                "submission_date", "submission_channel",
                "submission_ip", "reviewer_notes",
            ])
            for r in rows:
                appl_id, aid, prog, sub_date, status, prior, amount = r
                channel = random.choice(CHANNELS)
                ip = (f"{random.randint(10,200)}.{random.randint(0,255)}."
                      f"{random.randint(0,255)}.{random.randint(1,254)}")
                notes = ""
                if random.random() < 0.1:
                    notes = random.choice([
                        "Flagged by automated screening",
                        "Manual review recommended",
                        "Address verification pending",
                        "Income docs incomplete",
                    ])
                writer.writerow([appl_id, aid, prog, sub_date, channel,
                                 ip, notes])

    # --- JSON: identity_docs files ---
    json_splits = split_indices(n_app, n_json)

    identity_docs = []
    for i, app in enumerate(applicants):
        aid = app["applicant_id"]
        doc_type = random.choice(DOC_TYPES)
        state_code = app["state"]
        if doc_type == "drivers_license":
            doc_num = f"DL-{state_code}-{random.randint(100000, 999999)}"
        elif doc_type == "passport":
            doc_num = f"PP-{random.randint(10000000, 99999999)}"
        elif doc_type == "state_id":
            doc_num = f"SID-{state_code}-{random.randint(100000, 999999)}"
        elif doc_type == "military_id":
            doc_num = f"MIL-{random.randint(1000000, 9999999)}"
        else:
            doc_num = f"TID-{random.randint(100000, 999999)}"
        exp_date = fake.date_between(
            start_date="today", end_date="+5y").isoformat()
        ver_status = random.choice(["verified", "pending", "failed"])
        ver_date = fake.date_between(
            start_date="-6m", end_date="today").isoformat()
        identity_docs.append({
            "applicant_id": aid,
            "document_type": doc_type,
            "document_number": doc_num,
            "issuing_state": state_code,
            "expiry_date": exp_date,
            "verification_status": ver_status,
            "verification_date": ver_date,
        })

    # Inject identity doc duplicates
    dup_doc_pairs = []
    for src_idx, tgt_idx in dup_doc_pairs_indices:
        identity_docs[tgt_idx]["document_number"] = \
            identity_docs[src_idx]["document_number"]
        identity_docs[tgt_idx]["document_type"] = \
            identity_docs[src_idx]["document_type"]
        pair = tuple(sorted([applicants[src_idx]["applicant_id"],
                             applicants[tgt_idx]["applicant_id"]]))
        dup_doc_pairs.append(pair)

    for fidx in range(n_json):
        fname = f"identity_docs_{fidx + 1:03d}.json"
        docs = [identity_docs[j] for j in json_splits[fidx]]
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(docs, f, indent=2)

    # --- TXT: income_report files (employer-verified income) ---
    txt_splits = split_indices(n_app, n_txt)
    for fidx in range(n_txt):
        fname = f"income_report_{fidx + 1:03d}.txt"
        lines = []
        for j in txt_splits[fidx]:
            app = applicants[j]
            aid = app["applicant_id"]
            recs = income_by_applicant.get(aid, [])
            for ridx, rec in enumerate(recs):
                rpt_id = f"RPT-{aid}-{ridx + 1:02d}"
                employer = rec["employer_name"] if rec["employer_name"] else "N/A"
                lines.append(f"=== INCOME REPORT: {rpt_id} ===")
                lines.append(f"Applicant ID: {aid}")
                lines.append(f"Income Source: {rec['income_source']}")
                lines.append(f"Employer: {employer}")
                lines.append(f"Annual Income: {rec['annual_amount']:.2f}")
                lines.append(f"Verification Date: {rec['verification_date']}")
                lines.append(f"Verification Method: {rec['verification_method']}")
                lines.append("")
        with open(os.path.join(workspace, fname), "w") as f:
            f.write("\n".join(lines))

    # --- YAML: household_survey files ---
    yaml_splits = split_indices(n_app, n_yaml)
    for fidx in range(n_yaml):
        fname = f"household_survey_{fidx + 1:03d}.yaml"
        surveys = []
        for j in yaml_splits[fidx]:
            app = applicants[j]
            aid = app["applicant_id"]
            mems = applicant_members[aid]
            n_children = sum(1 for m in mems if m[2] == "child")
            n_elderly = sum(1 for m in mems
                           if m[2] in ("parent", "grandchild"))
            surveys.append({
                "applicant_id": aid,
                "survey_date": fake.date_between(
                    start_date="-6m", end_date="today").isoformat(),
                "household_size": len(mems) + 1,
                "dependents_under_18": n_children,
                "elderly_members": n_elderly,
                "primary_language": random.choice(
                    ["English", "Spanish", "Chinese", "Vietnamese",
                     "Arabic", "French", "Korean"]),
                "housing_type": random.choice(
                    ["owned_home", "rented_apartment", "rented_house",
                     "subsidized_housing", "shelter", "other"]),
            })
        with open(os.path.join(workspace, fname), "w") as f:
            yaml.dump({"surveys": surveys}, f, default_flow_style=False,
                      sort_keys=False)

    conn.close()

    print(f"Database created at {db_path}")
    print(f"  applicants: {n_app}")
    print(f"  household_members: {len(all_members)}")
    print(f"  applications: {len(all_applications)}")
    print(f"  income_verifications: {len(all_income)}")
    print(f"Workspace files in {workspace}/:")
    print(f"  Fixed: detection_rules.yaml, program_policies.md")
    print(f"  CSV submission batches: {n_csv}")
    print(f"  JSON identity docs: {n_json}")
    print(f"  TXT income reports: {n_txt}")
    print(f"  YAML household surveys: {n_yaml}")
    print(f"Injected duplicates:")
    print(f"  SSN_MATCH pairs: {len(dup_ssn_pairs)}")
    print(f"  NAME_DOB_MATCH pairs: {len(dup_name_pairs)}")
    print(f"  HOUSEHOLD_OVERLAP pairs: {len(dup_hh_pairs)}")
    print(f"  ID_DOC_MATCH pairs: {len(dup_doc_pairs)}")
    print(f"  ADDRESS_INCOME_MATCH pairs: {len(dup_addr_pairs)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
