import os
import json
import csv
import sqlite3
import argparse
import numpy as np
import pandas as pd
from faker import Faker
import yaml
import random


SCALE = {
    "rows_per_table": 320,
    "num_workspace_files": 24,
}

SEED = 42


def seed_all():
    np.random.seed(SEED)
    random.seed(SEED)
    Faker.seed(SEED)


# ── reference data ──────────────────────────────────────────────────────────

DEPARTMENTS = [
    "Public Safety", "Health Services", "Education", "Finance",
    "Transportation", "Housing", "Environment", "Legal Affairs",
    "Human Resources", "Information Technology", "Urban Planning",
    "Parks and Recreation", "Utilities", "Public Works", "Administration",
]

CATEGORIES = [
    "Personnel Records", "Financial Records", "Contracts and Procurement",
    "Permits and Licenses", "Inspection Reports", "Meeting Minutes",
    "Correspondence", "Legal Documents", "Policy Documents",
    "Complaints and Grievances", "Audit Reports", "Statistical Data",
]

COMMERCIAL_DOMAINS = [
    "databrokers.com", "infoextract.net", "publicrecordsearch.com",
    "datamining-solutions.com", "bulkrecords.org", "recordsharvest.com",
    "massfoia.com", "openrecords-biz.net", "govdatapull.com",
    "recordsmine.io",
]

NORMAL_DOMAINS = [
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "protonmail.com", "aol.com", "icloud.com", "mail.com",
]

DEPARTMENT_SENSITIVITY = {
    "Public Safety": 5, "Health Services": 5, "Education": 3, "Finance": 4,
    "Transportation": 2, "Housing": 3, "Environment": 2, "Legal Affairs": 5,
    "Human Resources": 4, "Information Technology": 3, "Urban Planning": 2,
    "Parks and Recreation": 1, "Utilities": 2, "Public Works": 2,
    "Administration": 3,
}

CATEGORY_RISK_SCORES = {
    "Personnel Records": 9, "Financial Records": 8,
    "Contracts and Procurement": 6, "Permits and Licenses": 4,
    "Inspection Reports": 5, "Meeting Minutes": 2, "Correspondence": 7,
    "Legal Documents": 8, "Policy Documents": 3,
    "Complaints and Grievances": 7, "Audit Reports": 6,
    "Statistical Data": 3,
}

REQUEST_SUBJECTS = [
    "records related to {dept} department staffing",
    "all {dept} expenditure reports for the past fiscal year",
    "copies of contracts awarded by {dept}",
    "inspection records for facilities under {dept}",
    "correspondence between {dept} and external consultants",
    "budget proposals submitted by {dept}",
    "employee grievance filings within {dept}",
    "audit findings for {dept} programs",
    "policy revisions issued by {dept}",
    "permit applications processed by {dept}",
    "meeting minutes from {dept} advisory board",
    "statistical summaries compiled by {dept}",
    "vendor payment records from {dept}",
    "incident reports filed with {dept}",
    "internal memos circulated within {dept}",
]

WAIVER_REASONS = [
    "Journalistic purpose – public interest reporting",
    "Academic research – non-commercial scholarly study",
    "Non-profit advocacy – community benefit",
    "Indigent requester – inability to pay",
    "Government oversight – legislative inquiry",
    "Commercial research – market analysis",
    "Bulk data compilation – aggregation project",
    "Legal proceeding – litigation support",
    "Public accountability – transparency initiative",
    "Educational use – curriculum development",
]


# ── helpers ─────────────────────────────────────────────────────────────────

def _make_email(fake, name, domain):
    parts = name.lower().split()
    user = ".".join(parts[:2]) if len(parts) >= 2 else parts[0]
    user = user.replace("'", "").replace(",", "")
    return f"{user}@{domain}"


def _random_date(rng, start="2022-01-01", end="2025-12-31"):
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    delta = (e - s).days
    if delta <= 0:
        return str(s.date())
    return str((s + pd.Timedelta(days=int(rng.integers(0, delta)))).date())


# ── generation ──────────────────────────────────────────────────────────────

def generate_requestors(fake, rng, n):
    """Generate requestor records. ~18% commercial miners, ~10% legit high-volume."""
    rows = []
    n_commercial = max(2, int(n * 0.18))
    n_legit_high = max(2, int(n * 0.10))
    types = ["individual", "organization", "government", "media"]

    for i in range(1, n + 1):
        name = fake.name()
        city = fake.city()
        state = fake.state_abbr()
        phone = fake.phone_number()
        address = fake.street_address()

        if i <= n_commercial:
            rtype = "organization"
            org = fake.company() + " Data Services"
            domain = rng.choice(NORMAL_DOMAINS)
            email = _make_email(fake, name, domain)
        elif i <= n_commercial + n_legit_high:
            rtype = str(rng.choice(["media", "government"]))
            org = fake.company() + (" News" if rtype == "media" else " Agency")
            domain = rng.choice(NORMAL_DOMAINS)
            email = _make_email(fake, name, domain)
        else:
            rtype = str(rng.choice(types, p=[0.50, 0.25, 0.10, 0.15]))
            org = fake.company() if rtype == "organization" else ""
            domain = rng.choice(NORMAL_DOMAINS)
            email = _make_email(fake, name, domain)

        rows.append({
            "id": i, "name": name, "email": email, "phone": phone,
            "organization": org, "address": address, "city": city,
            "state": state, "requestor_type": rtype,
        })
    return rows


def generate_requests(fake, rng, requestors, n_requests):
    """Distribute requests so commercial miners get many, others few."""
    n_req = len(requestors)
    n_commercial = max(2, int(n_req * 0.18))
    n_legit_high = max(2, int(n_req * 0.10))

    counts = np.zeros(n_req, dtype=int)
    for i in range(n_commercial):
        counts[i] = int(rng.integers(8, 16))
    for i in range(n_commercial, n_commercial + n_legit_high):
        counts[i] = int(rng.integers(5, 11))

    # distribute remaining requests among other requestors
    used = int(counts.sum())
    n_others = n_req - n_commercial - n_legit_high
    remaining = max(0, n_requests - used)
    if n_others > 0 and remaining > 0:
        # give each "other" requestor 1 request, then distribute leftovers
        for i in range(n_commercial + n_legit_high, n_req):
            counts[i] = 1
        leftover = remaining - n_others
        idx = n_commercial + n_legit_high
        while leftover > 0 and idx < n_req:
            add = min(int(rng.integers(1, 3)), leftover)
            counts[idx] += add
            leftover -= add
            idx += 1

    # final adjustment to hit exact target
    total = int(counts.sum())
    while total < n_requests:
        idx = int(rng.integers(0, n_req))
        counts[idx] += 1
        total += 1
    while total > n_requests:
        # reduce from the largest "other" requestor
        others_range = list(range(n_commercial + n_legit_high, n_req))
        others_range.sort(key=lambda x: -counts[x])
        for idx in others_range:
            if counts[idx] > 0 and total > n_requests:
                counts[idx] -= 1
                total -= 1

    rows = []
    rid = 1
    n_dept = len(DEPARTMENTS)
    n_cat = len(CATEGORIES)
    statuses = ["open", "closed", "pending", "fulfilled"]

    for req_idx, req in enumerate(requestors):
        n_this = int(counts[req_idx])
        if req_idx < n_commercial:
            dept_pool = list(range(1, n_dept + 1))
            cat_pool = list(range(1, n_cat + 1))
        else:
            dept_pool = rng.choice(range(1, n_dept + 1),
                                   size=min(3, n_dept), replace=False).tolist()
            cat_pool = rng.choice(range(1, n_cat + 1),
                                  size=min(4, n_cat), replace=False).tolist()

        for _ in range(n_this):
            dept_id = int(rng.choice(dept_pool))
            cat_id = int(rng.choice(cat_pool))
            dept_name = DEPARTMENTS[dept_id - 1]
            subject_template = str(rng.choice(REQUEST_SUBJECTS))
            subject = subject_template.format(dept=dept_name)
            date_filed = _random_date(rng)
            status = str(rng.choice(statuses, p=[0.15, 0.35, 0.15, 0.35]))
            rows.append({
                "id": rid, "requestor_id": req["id"],
                "date_filed": date_filed, "subject": subject,
                "status": status, "category_id": cat_id,
                "department_id": dept_id,
            })
            rid += 1
    return rows


def generate_productions(fake, rng, requests, n_productions):
    """Generate document production logs tied to requests."""
    rows = []
    eligible = [r for r in requests if r["status"] in ("closed", "fulfilled")]
    eligible_copy = list(eligible)
    rng.shuffle(eligible_copy)

    pid = 1
    formats = ["pdf", "paper", "electronic", "scanned"]

    for req in eligible_copy[:n_productions]:
        pages = int(rng.integers(5, 500))
        cost = round(float(pages * rng.uniform(0.10, 0.50)), 2)
        hours = round(float(rng.uniform(0.5, 8.0)), 1)
        prod_date = _random_date(rng, req["date_filed"], "2025-12-31")
        fmt = str(rng.choice(formats))
        rows.append({
            "id": pid, "request_id": req["id"],
            "pages_produced": pages, "production_date": prod_date,
            "format": fmt, "cost": cost, "staff_hours": hours,
        })
        pid += 1

    while len(rows) < n_productions:
        req = eligible_copy[int(rng.integers(0, len(eligible_copy)))]
        pages = int(rng.integers(5, 300))
        cost = round(float(pages * rng.uniform(0.10, 0.50)), 2)
        hours = round(float(rng.uniform(0.5, 6.0)), 1)
        prod_date = _random_date(rng, req["date_filed"], "2025-12-31")
        fmt = str(rng.choice(formats))
        rows.append({
            "id": pid, "request_id": req["id"],
            "pages_produced": pages, "production_date": prod_date,
            "format": fmt, "cost": cost, "staff_hours": hours,
        })
        pid += 1

    return rows


def generate_fee_waivers(fake, rng, requests, requestors, n_waivers):
    """Generate fee waiver records. Commercial miners request many waivers."""
    n_req_total = len(requestors)
    n_commercial = max(2, int(n_req_total * 0.18))

    commercial_ids = set(r["id"] for r in requestors[:n_commercial])
    commercial_requests = [r for r in requests if r["requestor_id"] in commercial_ids]
    other_requests = [r for r in requests if r["requestor_id"] not in commercial_ids]

    rows = []
    wid = 1
    approvers = [fake.name() for _ in range(5)]
    waiver_types = ["full", "partial"]
    waiver_statuses_denied = ["denied", "pending"]

    n_commercial_waivers = min(int(n_waivers * 0.55), len(commercial_requests))
    comm_copy = list(commercial_requests)
    rng.shuffle(comm_copy)
    for req in comm_copy[:n_commercial_waivers]:
        amount_req = round(float(rng.uniform(20, 500)), 2)
        is_approved = rng.random() < 0.75
        wtype = str(rng.choice(waiver_types))
        if is_approved:
            amount_waived = amount_req if wtype == "full" else round(
                amount_req * float(rng.uniform(0.3, 0.8)), 2)
            status = "approved"
        else:
            amount_waived = 0.0
            status = str(rng.choice(waiver_statuses_denied))
        reason = str(rng.choice(WAIVER_REASONS))
        approval_date = _random_date(rng, req["date_filed"], "2025-12-31")
        rows.append({
            "id": wid, "request_id": req["id"],
            "requestor_id": req["requestor_id"],
            "waiver_type": wtype, "amount_requested": amount_req,
            "amount_waived": amount_waived, "reason": reason,
            "approved_by": str(rng.choice(approvers)),
            "approval_date": approval_date, "status": status,
        })
        wid += 1

    remaining_waivers = n_waivers - len(rows)
    other_copy = list(other_requests)
    rng.shuffle(other_copy)
    for req in other_copy[:remaining_waivers]:
        amount_req = round(float(rng.uniform(10, 200)), 2)
        is_approved = rng.random() < 0.40
        wtype = str(rng.choice(waiver_types))
        if is_approved:
            amount_waived = amount_req if wtype == "full" else round(
                amount_req * float(rng.uniform(0.3, 0.7)), 2)
            status = "approved"
        else:
            amount_waived = 0.0
            status = str(rng.choice(waiver_statuses_denied))
        reason = str(rng.choice(WAIVER_REASONS))
        approval_date = _random_date(rng, req["date_filed"], "2025-12-31")
        rows.append({
            "id": wid, "request_id": req["id"],
            "requestor_id": req["requestor_id"],
            "waiver_type": wtype, "amount_requested": amount_req,
            "amount_waived": amount_waived, "reason": reason,
            "approved_by": str(rng.choice(approvers)),
            "approval_date": approval_date, "status": status,
        })
        wid += 1

    return rows


# ── database ────────────────────────────────────────────────────────────────

def create_database(db_path, requestors, requests, productions, fee_waivers):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("DROP TABLE IF EXISTS fee_waivers")
    c.execute("DROP TABLE IF EXISTS document_productions")
    c.execute("DROP TABLE IF EXISTS requests")
    c.execute("DROP TABLE IF EXISTS requestors")
    c.execute("DROP TABLE IF EXISTS categories")
    c.execute("DROP TABLE IF EXISTS departments")

    c.execute("""CREATE TABLE departments (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL)""")
    for i, name in enumerate(DEPARTMENTS, 1):
        c.execute("INSERT INTO departments VALUES (?, ?)", (i, name))

    c.execute("""CREATE TABLE categories (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL)""")
    for i, name in enumerate(CATEGORIES, 1):
        c.execute("INSERT INTO categories VALUES (?, ?)", (i, name))

    c.execute("""CREATE TABLE requestors (
        id INTEGER PRIMARY KEY, name TEXT, email TEXT,
        phone TEXT, organization TEXT, address TEXT,
        city TEXT, state TEXT, requestor_type TEXT)""")
    for r in requestors:
        c.execute("INSERT INTO requestors VALUES (?,?,?,?,?,?,?,?,?)",
                  (r["id"], r["name"], r["email"], r["phone"],
                   r["organization"], r["address"], r["city"],
                   r["state"], r["requestor_type"]))

    c.execute("""CREATE TABLE requests (
        id INTEGER PRIMARY KEY, requestor_id INTEGER,
        date_filed TEXT, subject TEXT, status TEXT,
        category_id INTEGER, department_id INTEGER,
        FOREIGN KEY (requestor_id) REFERENCES requestors(id),
        FOREIGN KEY (category_id) REFERENCES categories(id),
        FOREIGN KEY (department_id) REFERENCES departments(id))""")
    for r in requests:
        c.execute("INSERT INTO requests VALUES (?,?,?,?,?,?,?)",
                  (r["id"], r["requestor_id"], r["date_filed"],
                   r["subject"], r["status"], r["category_id"],
                   r["department_id"]))

    c.execute("""CREATE TABLE document_productions (
        id INTEGER PRIMARY KEY, request_id INTEGER,
        pages_produced INTEGER, production_date TEXT,
        format TEXT, cost REAL, staff_hours REAL,
        FOREIGN KEY (request_id) REFERENCES requests(id))""")
    for p in productions:
        c.execute("INSERT INTO document_productions VALUES (?,?,?,?,?,?,?)",
                  (p["id"], p["request_id"], p["pages_produced"],
                   p["production_date"], p["format"], p["cost"],
                   p["staff_hours"]))

    c.execute("""CREATE TABLE fee_waivers (
        id INTEGER PRIMARY KEY, request_id INTEGER,
        requestor_id INTEGER, waiver_type TEXT,
        amount_requested REAL, amount_waived REAL,
        reason TEXT, approved_by TEXT, approval_date TEXT,
        status TEXT,
        FOREIGN KEY (request_id) REFERENCES requests(id),
        FOREIGN KEY (requestor_id) REFERENCES requestors(id))""")
    for w in fee_waivers:
        c.execute("INSERT INTO fee_waivers VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (w["id"], w["request_id"], w["requestor_id"],
                   w["waiver_type"], w["amount_requested"],
                   w["amount_waived"], w["reason"], w["approved_by"],
                   w["approval_date"], w["status"]))

    conn.commit()
    conn.close()


# ── workspace ───────────────────────────────────────────────────────────────

def create_workspace(workspace, requestors, requests, productions, fee_waivers,
                     rng, fake):
    os.makedirs(workspace, exist_ok=True)

    n_req = len(requestors)
    n_commercial = max(2, int(n_req * 0.18))

    # ── fixed config files ──────────────────────────────────────────────────

    # 1. thresholds.yaml
    thresholds = {
        "volume_threshold": 5,
        "risk_score_threshold": 0.60,
        "scoring_weights": {
            "request_volume": 0.20,
            "commercial_domain_match": 0.25,
            "fee_waiver_ratio": 0.20,
            "department_spread": 0.15,
            "document_sensitivity": 0.10,
            "cross_agency_history": 0.10,
        },
        "normalization": {
            "volume_cap": 20,
            "department_spread_cap": 6,
            "cross_agency_cap": 10,
        },
    }
    with open(os.path.join(workspace, "thresholds.yaml"), "w") as f:
        yaml.dump(thresholds, f, default_flow_style=False, sort_keys=False)

    # 2. commercial_domains.json
    with open(os.path.join(workspace, "commercial_domains.json"), "w") as f:
        json.dump({"known_commercial_domains": COMMERCIAL_DOMAINS}, f, indent=2)

    # 3. department_sensitivity.csv
    with open(os.path.join(workspace, "department_sensitivity.csv"), "w",
              newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["department_id", "department_name", "sensitivity_level"])
        for i, name in enumerate(DEPARTMENTS, 1):
            writer.writerow([i, name, DEPARTMENT_SENSITIVITY[name]])

    # 4. category_risk_scores.json
    cat_scores = []
    for i, name in enumerate(CATEGORIES, 1):
        cat_scores.append({"category_id": i, "category_name": name,
                           "risk_score": CATEGORY_RISK_SCORES[name]})
    with open(os.path.join(workspace, "category_risk_scores.json"), "w") as f:
        json.dump(cat_scores, f, indent=2)

    # 5. fee_waiver_policy.md
    policy = (
        "Fee Waiver Review Policy\n\n"
        "Waivers are granted when disclosure primarily benefits the general public. "
        "The following guidelines help reviewers assess whether a fee waiver request "
        "is appropriate and identify patterns that may indicate commercial exploitation "
        "of the public-records process.\n\n"
        "A fee waiver approval ratio is computed per requestor as the number of approved "
        "fee waivers divided by that requestor's total number of filed requests. When the "
        "approval ratio exceeds fifty percent for a requestor who has also been classified "
        "as high-volume, the pattern should be treated as a risk indicator for commercial "
        "data mining.\n\n"
        "Approved waiver reasons containing the phrases \"commercial\", \"market analysis\", "
        "\"bulk data\", or \"aggregation\" are considered commercially-oriented justifications. "
        "Each requestor who has at least one approved waiver with a commercially-oriented "
        "justification receives an additional flag noted as \"commercial_waiver_language\" "
        "in the output report.\n"
    )
    with open(os.path.join(workspace, "fee_waiver_policy.md"), "w") as f:
        f.write(policy)

    # ── scalable data files ─────────────────────────────────────────────────

    n_files = SCALE["num_workspace_files"]
    n_profile_files = n_files // 2
    n_manifest_files = n_files - n_profile_files

    # -- requestor profile batches (CSV) --
    profile_records = []
    for req in requestors:
        has_profile = rng.random() < 0.70
        if not has_profile:
            continue
        if req["id"] <= n_commercial:
            alt_domain = str(rng.choice(COMMERCIAL_DOMAINS))
            alt_email = _make_email(fake, req["name"], alt_domain)
            aff_org = (fake.company() + " " +
                       str(rng.choice(["Analytics", "Data Solutions",
                                       "Information Services",
                                       "Research Group"])))
            cross_agency = int(rng.integers(5, 25))
        else:
            maybe_domain = str(rng.choice(NORMAL_DOMAINS + [""]))
            if maybe_domain:
                alt_email = _make_email(fake, req["name"], maybe_domain)
            else:
                alt_email = ""
            aff_org = req["organization"] if req["organization"] else ""
            cross_agency = int(rng.integers(0, 5))

        profile_records.append({
            "requestor_id": req["id"],
            "alternate_email": alt_email,
            "affiliated_organization": aff_org,
            "cross_agency_request_count": cross_agency,
        })

    rng.shuffle(profile_records)
    chunks = np.array_split(profile_records, n_profile_files)
    for idx, chunk in enumerate(chunks, 1):
        path = os.path.join(workspace, f"requestor_profile_batch_{idx}.csv")
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "requestor_id", "alternate_email",
                "affiliated_organization", "cross_agency_request_count"])
            writer.writeheader()
            for row in chunk:
                writer.writerow(row)

    # -- production manifest batches (JSON) --
    doc_types = [
        "personal_identifiable_info", "financial_data", "legal_records",
        "public_safety_records", "administrative_records",
        "statistical_tables", "correspondence", "contracts",
    ]
    manifest_records = []
    req_by_id = {r["id"]: r for r in requests}
    for prod in productions:
        req_match = req_by_id.get(prod["request_id"])
        if req_match is None:
            continue
        n_doc_types = int(rng.integers(1, 4))
        selected_types = rng.choice(doc_types, size=n_doc_types,
                                    replace=False).tolist()
        base_sens = float(rng.uniform(1.0, 3.0))
        dept_id = req_match["department_id"]
        dept_name = DEPARTMENTS[dept_id - 1]
        dept_sens = DEPARTMENT_SENSITIVITY[dept_name]
        avg_sensitivity = round((base_sens + dept_sens) / 2, 2)

        manifest_records.append({
            "production_id": prod["id"],
            "request_id": prod["request_id"],
            "document_types": selected_types,
            "avg_document_sensitivity": avg_sensitivity,
        })

    rng.shuffle(manifest_records)
    m_chunks = np.array_split(manifest_records, n_manifest_files)
    for idx, chunk in enumerate(m_chunks, 1):
        path = os.path.join(workspace, f"production_manifest_batch_{idx}.json")
        records = []
        for r in chunk:
            records.append({
                "production_id": int(r["production_id"]),
                "request_id": int(r["request_id"]),
                "document_types": list(r["document_types"]),
                "avg_document_sensitivity": float(r["avg_document_sensitivity"]),
            })
        with open(path, "w") as f:
            json.dump(records, f, indent=2)


# ── main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    seed_all()
    rng = np.random.default_rng(SEED)
    fake = Faker()
    Faker.seed(SEED)

    n_requestors = SCALE["rows_per_table"]
    n_requests = SCALE["rows_per_table"] * 3
    n_productions = SCALE["rows_per_table"] * 2
    n_fee_waivers = SCALE["rows_per_table"]

    requestors = generate_requestors(fake, rng, n_requestors)
    requests_list = generate_requests(fake, rng, requestors, n_requests)
    productions = generate_productions(fake, rng, requests_list, n_productions)
    fee_waivers = generate_fee_waivers(fake, rng, requests_list, requestors,
                                       n_fee_waivers)

    create_database(args.db_path, requestors, requests_list, productions,
                    fee_waivers)
    create_workspace(args.workspace, requestors, requests_list, productions,
                     fee_waivers, rng, fake)

    print(f"Database created at {args.db_path}")
    print(f"  requestors:           {len(requestors)}")
    print(f"  requests:             {len(requests_list)}")
    print(f"  document_productions: {len(productions)}")
    print(f"  fee_waivers:          {len(fee_waivers)}")
    print(f"Workspace created at {args.workspace}")
    print(f"  scalable files:       {SCALE['num_workspace_files']}")


if __name__ == "__main__":
    main()
