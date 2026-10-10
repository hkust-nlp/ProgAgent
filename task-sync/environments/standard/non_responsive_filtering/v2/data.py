"""Data generation for non-responsive document exclusion task."""
import argparse
import os
import sqlite3
import json
import csv
import random
import numpy as np
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 320,
    "num_workspace_files": 24,
}

# All random seeds pinned to 42
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

DEPARTMENTS = [
    "Legal", "Finance", "Engineering", "Sales", "Marketing",
    "HR", "Operations", "Executive", "IT", "Compliance",
]

TOPIC_CATEGORIES = [
    "contract_disputes", "financial_irregularities", "employment_practices",
    "ip_infringement", "regulatory_compliance", "merger_activity",
    "trade_secrets", "antitrust",
]

KEYWORDS_POOL = [
    "merger", "acquisition", "contract", "agreement", "liability",
    "revenue", "profit", "loss", "compliance", "regulation",
    "patent", "trademark", "copyright", "trade_secret", "confidential",
    "termination", "severance", "bonus", "compensation", "equity",
    "audit", "investigation", "subpoena", "discovery", "production",
    "pricing", "market_share", "competitor", "antitrust", "monopoly",
    "forecast", "budget", "expenditure", "reimbursement", "invoice",
    "negotiation", "settlement", "mediation", "arbitration", "litigation",
]

FILE_TYPES = [
    "pdf", "docx", "xlsx", "eml", "pptx", "txt", "csv", "msg", "tmp", "bak",
]

SOURCE_SYSTEMS = [
    "email_archive", "file_share", "sharepoint", "slack_export",
    "local_drive", "cloud_storage", "crm_system",
]


# ---------------------------------------------------------------------------
# Database generation
# ---------------------------------------------------------------------------

def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS custodians (
        custodian_id INTEGER PRIMARY KEY,
        full_name TEXT NOT NULL,
        department TEXT NOT NULL,
        email TEXT NOT NULL,
        hire_date TEXT NOT NULL,
        termination_date TEXT,
        data_volume_gb REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS documents (
        doc_id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        custodian_id INTEGER NOT NULL,
        date_created TEXT NOT NULL,
        file_type TEXT NOT NULL,
        file_size_kb REAL,
        source_system TEXT,
        bates_prefix TEXT,
        FOREIGN KEY (custodian_id) REFERENCES custodians(custodian_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS keyword_hits (
        hit_id INTEGER PRIMARY KEY,
        doc_id INTEGER NOT NULL,
        keyword TEXT NOT NULL,
        hit_count INTEGER NOT NULL,
        FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS rfp_criteria (
        criterion_id INTEGER PRIMARY KEY,
        rfp_number TEXT NOT NULL,
        subrequest_label TEXT NOT NULL,
        topic_category TEXT NOT NULL,
        criterion_keyword TEXT NOT NULL,
        date_start TEXT NOT NULL,
        date_end TEXT NOT NULL
    )""")
    conn.commit()


def gen_custodians(conn, n):
    rows = []
    for i in range(n):
        cid = i + 1
        name = fake.name()
        dept = DEPARTMENTS[i % len(DEPARTMENTS)]
        email = fake.email()
        hire = fake.date_between(start_date="-15y", end_date="-1y").isoformat()
        term = (
            fake.date_between(start_date="-1y", end_date="today").isoformat()
            if random.random() < 0.15
            else None
        )
        vol = round(random.uniform(0.5, 50.0), 2)
        rows.append((cid, name, dept, email, hire, term, vol))
    conn.executemany("INSERT INTO custodians VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def gen_documents(conn, n, num_custodians):
    rows = []
    for i in range(n):
        did = i + 1
        title = fake.sentence(nb_words=random.randint(3, 8)).rstrip(".")
        cid = random.randint(1, num_custodians)
        dc = fake.date_between(start_date="-6y", end_date="today").isoformat()
        ft = random.choice(FILE_TYPES)
        sz = round(random.uniform(10, 5000), 1)
        src = random.choice(SOURCE_SYSTEMS)
        bates = f"PROD-{did:06d}"
        rows.append((did, title, cid, dc, ft, sz, src, bates))
    conn.executemany("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def gen_keyword_hits(conn, num_docs, min_rows):
    rows = []
    hit_id = 0
    used = set()
    for doc_id in range(1, num_docs + 1):
        n_kw = random.randint(2, 6)
        kws = random.sample(KEYWORDS_POOL, min(n_kw, len(KEYWORDS_POOL)))
        for kw in kws:
            if (doc_id, kw) not in used:
                hit_id += 1
                cnt = random.randint(1, 15)
                rows.append((hit_id, doc_id, kw, cnt))
                used.add((doc_id, kw))
    while len(rows) < min_rows:
        doc_id = random.randint(1, num_docs)
        kw = random.choice(KEYWORDS_POOL)
        if (doc_id, kw) not in used:
            hit_id += 1
            cnt = random.randint(1, 15)
            rows.append((hit_id, doc_id, kw, cnt))
            used.add((doc_id, kw))
    conn.executemany("INSERT INTO keyword_hits VALUES (?,?,?,?)", rows)
    conn.commit()
    return rows


def gen_rfp_criteria(conn, min_rows):
    num_rfps = max(6, min_rows // 12)
    rfp_numbers = [f"RFP-{i + 1:03d}" for i in range(num_rfps)]
    rows = []
    crit_id = 0
    for rfp in rfp_numbers:
        n_sub = random.randint(1, 3)
        for si in range(n_sub):
            label = f"{rfp}.{si + 1}"
            topic = random.choice(TOPIC_CATEGORIES)
            ds = fake.date_between(start_date="-5y", end_date="-2y").isoformat()
            de = fake.date_between(start_date="-2y", end_date="today").isoformat()
            if ds > de:
                ds, de = de, ds
            n_kw = random.randint(2, 5)
            kws = random.sample(KEYWORDS_POOL, n_kw)
            for kw in kws:
                crit_id += 1
                rows.append((crit_id, rfp, label, topic, kw, ds, de))
    while len(rows) < min_rows:
        rfp = random.choice(rfp_numbers)
        label = f"{rfp}.extra"
        topic = random.choice(TOPIC_CATEGORIES)
        ds = fake.date_between(start_date="-5y", end_date="-2y").isoformat()
        de = fake.date_between(start_date="-2y", end_date="today").isoformat()
        if ds > de:
            ds, de = de, ds
        kw = random.choice(KEYWORDS_POOL)
        crit_id += 1
        rows.append((crit_id, rfp, label, topic, kw, ds, de))
    conn.executemany("INSERT INTO rfp_criteria VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows, rfp_numbers


# ---------------------------------------------------------------------------
# Workspace generation
# ---------------------------------------------------------------------------

def gen_workspace(workspace, custodians, documents, rfp_numbers):
    F = SCALE["num_workspace_files"]
    R = SCALE["rows_per_table"]

    # ── Fixed files (not counted in F) ────────────────────────────────────

    # exclusion_rules.json
    rules = {
        "min_keyword_hit_count": 2,
        "date_buffer_days": 30,
        "min_weighted_relevance_score": 0.45,
        "excluded_file_types": ["tmp", "bak"],
        "require_litigation_hold": True,
        "protected_confidentiality_levels": ["highly_confidential"],
    }
    with open(os.path.join(workspace, "exclusion_rules.json"), "w") as fh:
        json.dump(rules, fh, indent=2)

    # privilege_log.csv
    num_priv = max(3, R // 20)
    priv_ids = sorted(random.sample(range(1, len(documents) + 1), num_priv))
    with open(os.path.join(workspace, "privilege_log.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["doc_id", "privilege_type", "reviewed_by", "review_date"])
        for did in priv_ids:
            w.writerow([
                did,
                random.choice(["attorney_client", "work_product", "joint_defense"]),
                fake.name(),
                fake.date_between(start_date="-1y", end_date="today").isoformat(),
            ])

    # ── Scalable files (F total, 4 format categories) ────────────────────
    n1 = max(1, F // 4)       # custodian_rfp_map   .csv
    n2 = max(1, F // 4)       # keyword_weights     .json
    n3 = max(1, F // 4)       # document_supplement .md
    n4 = F - n1 - n2 - n3     # custodian_status    .yaml
    if n4 < 1:
        n4 = 1
        n3 = F - n1 - n2 - n4

    cust_ids = [c[0] for c in custodians]
    doc_ids = [d[0] for d in documents]

    # ---- Category 1: custodian_rfp_map_XX.csv ----
    batch = max(1, len(cust_ids) // n1)
    for bi in range(n1):
        s = bi * batch
        e = len(cust_ids) if bi == n1 - 1 else (bi + 1) * batch
        bc = cust_ids[s:e]
        rows = []
        for cid in bc:
            na = random.randint(1, min(4, len(rfp_numbers)))
            for rfp in random.sample(rfp_numbers, na):
                rows.append({
                    "custodian_id": cid,
                    "rfp_number": rfp,
                    "scope_status": "in_scope",
                })
        path = os.path.join(workspace, f"custodian_rfp_map_{bi + 1:02d}.csv")
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(
                fh, fieldnames=["custodian_id", "rfp_number", "scope_status"]
            )
            w.writeheader()
            w.writerows(rows)

    # ---- Category 2: keyword_weights_XX.json ----
    tpf = max(1, len(TOPIC_CATEGORIES) // n2)
    for bi in range(n2):
        s = bi * tpf
        e = (
            len(TOPIC_CATEGORIES) if bi == n2 - 1 else (bi + 1) * tpf
        )
        bt = TOPIC_CATEGORIES[s:e]
        weights = {}
        for topic in bt:
            weights[topic] = {
                kw: round(random.uniform(0.0, 1.0), 3) for kw in KEYWORDS_POOL
            }
        path = os.path.join(workspace, f"keyword_weights_{bi + 1:02d}.json")
        with open(path, "w") as fh:
            json.dump(weights, fh, indent=2)

    # ---- Category 3: document_supplement_XX.md (markdown table) ----
    conf_levels = ["public", "internal", "confidential", "highly_confidential"]
    ret_cats = ["permanent", "7_year", "3_year", "1_year", "no_retention"]
    batch = max(1, len(doc_ids) // n3)
    for bi in range(n3):
        s = bi * batch
        e = len(doc_ids) if bi == n3 - 1 else (bi + 1) * batch
        bd = doc_ids[s:e]
        lines = [
            "| doc_id | confidentiality_level | retention_category | review_priority |",
            "|---|---|---|---|",
        ]
        for did in bd:
            cl = random.choice(conf_levels)
            rc = random.choice(ret_cats)
            rp = random.randint(1, 5)
            lines.append(f"| {did} | {cl} | {rc} | {rp} |")
        path = os.path.join(workspace, f"document_supplement_{bi + 1:02d}.md")
        with open(path, "w") as fh:
            fh.write("\n".join(lines) + "\n")

    # ---- Category 4: custodian_status_XX.yaml ----
    batch = max(1, len(cust_ids) // n4)
    for bi in range(n4):
        s = bi * batch
        e = len(cust_ids) if bi == n4 - 1 else (bi + 1) * batch
        bc = cust_ids[s:e]
        statuses = []
        for cid in bc:
            statuses.append({
                "custodian_id": int(cid),
                "litigation_hold": bool(random.random() < 0.7),
                "collection_complete": bool(random.random() < 0.85),
                "last_collection_date": fake.date_between(
                    start_date="-1y", end_date="today"
                ).isoformat(),
            })
        path = os.path.join(workspace, f"custodian_status_{bi + 1:02d}.yaml")
        with open(path, "w") as fh:
            yaml.dump(
                {"custodian_statuses": statuses}, fh, default_flow_style=False
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(db_path, workspace):
    os.makedirs(workspace, exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    R = SCALE["rows_per_table"]
    conn = sqlite3.connect(db_path)
    create_tables(conn)

    custodians = gen_custodians(conn, R)
    documents = gen_documents(conn, R, R)
    gen_keyword_hits(conn, R, R)
    _rfp_criteria, rfp_numbers = gen_rfp_criteria(conn, R)

    conn.close()

    gen_workspace(workspace, custodians, documents, rfp_numbers)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db_path", required=True)
    p.add_argument("--workspace", required=True)
    main(**vars(p.parse_args()))
