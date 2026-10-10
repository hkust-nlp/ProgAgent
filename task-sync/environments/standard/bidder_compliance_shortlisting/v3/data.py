#!/usr/bin/env python3
"""Data generation for municipal infrastructure tender vendor evaluation task."""

import argparse
import os
import sqlite3
import json
import csv
import random
import math

import numpy as np
import pandas as pd
import yaml
from faker import Faker


SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 48,
}


def main(db_path: str, workspace: str):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    rows = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ========== TABLE 1: suppliers ==========
    cur.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            supplier_id INTEGER PRIMARY KEY,
            name TEXT,
            registration_number TEXT,
            city TEXT,
            state TEXT,
            established_year INTEGER,
            primary_category TEXT,
            employee_count INTEGER,
            contact_email TEXT
        )
    """)

    categories = [
        "Civil Engineering", "Environmental Services", "Construction",
        "Water Infrastructure", "Transportation", "Electrical Systems",
        "Waste Management", "Urban Planning",
    ]

    suppliers = []
    for i in range(1, rows + 1):
        name = fake.company()
        reg = f"REG-{fake.unique.random_int(min=10000, max=99999)}"
        city = fake.city()
        state = fake.state_abbr()
        year = random.randint(1985, 2022)
        cat = random.choice(categories)
        emp = random.randint(20, 5000)
        email = fake.company_email()
        suppliers.append((i, name, reg, city, state, year, cat, emp, email))

    cur.executemany("INSERT INTO suppliers VALUES (?,?,?,?,?,?,?,?,?)", suppliers)

    # ========== TABLE 2: tender_bids (which suppliers submitted bids) ==========
    num_bidders = max(10, rows * 55 // 100)
    bidder_ids = sorted(random.sample(range(1, rows + 1), num_bidders))

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tender_bids (
            bid_id INTEGER PRIMARY KEY,
            supplier_id INTEGER,
            tender_id TEXT,
            submission_date TEXT,
            status TEXT,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
        )
    """)

    tender_id = "TENDER-2026-MI-001"
    bids_data = []
    for idx, sid in enumerate(bidder_ids, 1):
        sub_date = fake.date_between(start_date="-60d", end_date="-30d").isoformat()
        bids_data.append((idx, sid, tender_id, sub_date, "submitted"))
    cur.executemany("INSERT INTO tender_bids VALUES (?,?,?,?,?)", bids_data)

    # ========== TABLE 3: certificates ==========
    cur.execute("""
        CREATE TABLE IF NOT EXISTS certificates (
            cert_id INTEGER PRIMARY KEY,
            supplier_id INTEGER,
            cert_type TEXT,
            issuing_body TEXT,
            issue_date TEXT,
            expiry_date TEXT,
            cert_status TEXT,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
        )
    """)

    cert_types_all = [
        "ISO 9001", "ISO 14001", "ISO 45001", "Municipal Works License",
        "Environmental Compliance", "Safety Certification", "Financial Guarantee Bond",
    ]
    issuing_bodies = [
        "National Standards Board", "Municipal Licensing Authority",
        "Environmental Protection Agency", "Occupational Safety Council",
        "Financial Regulatory Commission",
    ]

    cert_id = 1
    all_certs = []
    for sid in range(1, rows + 1):
        n_certs = random.randint(3, min(7, len(cert_types_all)))
        chosen_types = random.sample(cert_types_all, n_certs)
        for ct in chosen_types:
            ib = random.choice(issuing_bodies)
            issue = fake.date_between(start_date="-5y", end_date="-6m")
            if random.random() < 0.12:
                expiry = fake.date_between(start_date="-1y", end_date="-1d")
                status = "expired"
            else:
                expiry = fake.date_between(start_date="+6m", end_date="+3y")
                status = "active"
            all_certs.append(
                (cert_id, sid, ct, ib, issue.isoformat(), expiry.isoformat(), status)
            )
            cert_id += 1

    cur.executemany("INSERT INTO certificates VALUES (?,?,?,?,?,?,?)", all_certs)

    # ========== TABLE 4: project_history ==========
    cur.execute("""
        CREATE TABLE IF NOT EXISTS project_history (
            record_id INTEGER PRIMARY KEY,
            supplier_id INTEGER,
            project_name TEXT,
            client_name TEXT,
            domain TEXT,
            contract_value REAL,
            performance_score REAL,
            completion_year INTEGER,
            on_time INTEGER,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
        )
    """)

    domains = [
        "Road Construction", "Bridge Engineering", "Water Treatment",
        "Sewer Systems", "Public Buildings", "Park Development",
        "Electrical Grid", "Waste Processing",
    ]

    rec_id = 1
    all_projects = []
    for sid in range(1, rows + 1):
        n_projects = random.randint(3, max(4, rows // 6))
        for _ in range(n_projects):
            pname = f"{fake.city()} {random.choice(domains)} Project"
            client = fake.company()
            domain = random.choice(domains)
            value = round(random.uniform(500000, 50000000), 2)
            score = round(random.uniform(40, 100), 1)
            year = random.randint(2018, 2025)
            on_time = 1 if random.random() < 0.7 else 0
            all_projects.append(
                (rec_id, sid, pname, client, domain, value, score, year, on_time)
            )
            rec_id += 1

    cur.executemany("INSERT INTO project_history VALUES (?,?,?,?,?,?,?,?,?)", all_projects)

    # ========== TABLE 5: bid_line_items ==========
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bid_line_items (
            item_id INTEGER PRIMARY KEY,
            supplier_id INTEGER,
            tender_id TEXT,
            line_item_code TEXT,
            description TEXT,
            unit TEXT,
            unit_price REAL,
            quantity INTEGER,
            total_price REAL,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
        )
    """)

    line_items_def = [
        ("LI-001", "Site preparation and earthworks", "sq_m"),
        ("LI-002", "Concrete foundation works", "cu_m"),
        ("LI-003", "Steel reinforcement supply and installation", "ton"),
        ("LI-004", "Drainage system installation", "linear_m"),
        ("LI-005", "Road surface paving", "sq_m"),
        ("LI-006", "Utility connection works", "unit"),
        ("LI-007", "Environmental remediation", "sq_m"),
        ("LI-008", "Safety barriers and signage", "unit"),
    ]

    base_prices = {
        "LI-001": 45, "LI-002": 320, "LI-003": 2800,
        "LI-004": 180, "LI-005": 95, "LI-006": 12000,
        "LI-007": 65, "LI-008": 750,
    }

    item_id = 1
    all_items = []
    for sid in bidder_ids:
        for code, desc, unit in line_items_def:
            price = round(base_prices[code] * random.uniform(0.7, 1.5), 2)
            qty = random.randint(50, 500)
            total = round(price * qty, 2)
            all_items.append(
                (item_id, sid, tender_id, code, desc, unit, price, qty, total)
            )
            item_id += 1

    cur.executemany("INSERT INTO bid_line_items VALUES (?,?,?,?,?,?,?,?,?)", all_items)

    # ========== TABLE 6: sustainability_responses ==========
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sustainability_responses (
            response_id INTEGER PRIMARY KEY,
            supplier_id INTEGER,
            criterion_id TEXT,
            response TEXT,
            evidence_reference TEXT,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
        )
    """)

    sustainability_criteria = [
        {"criterion_id": "SC-01", "name": "Carbon Emission Reduction Plan",
         "mandatory": True, "category": "Environmental"},
        {"criterion_id": "SC-02", "name": "Waste Management Strategy",
         "mandatory": True, "category": "Environmental"},
        {"criterion_id": "SC-03", "name": "Local Workforce Employment Commitment",
         "mandatory": True, "category": "Social"},
        {"criterion_id": "SC-04", "name": "Renewable Energy Usage Policy",
         "mandatory": False, "category": "Environmental"},
        {"criterion_id": "SC-05", "name": "Supply Chain Sustainability Audit",
         "mandatory": True, "category": "Governance"},
        {"criterion_id": "SC-06", "name": "Biodiversity Impact Assessment",
         "mandatory": False, "category": "Environmental"},
        {"criterion_id": "SC-07", "name": "Community Engagement Framework",
         "mandatory": False, "category": "Social"},
        {"criterion_id": "SC-08", "name": "Water Conservation Measures",
         "mandatory": True, "category": "Environmental"},
        {"criterion_id": "SC-09", "name": "Anti-Corruption and Ethics Policy",
         "mandatory": True, "category": "Governance"},
        {"criterion_id": "SC-10", "name": "Health and Safety Beyond Compliance",
         "mandatory": False, "category": "Social"},
    ]

    resp_id = 1
    all_responses = []
    for sid in bidder_ids:
        for sc in sustainability_criteria:
            if sc["mandatory"]:
                r = random.random()
                if r < 0.78:
                    response = "compliant"
                elif r < 0.90:
                    response = "partial"
                else:
                    response = "non_compliant"
            else:
                r = random.random()
                if r < 0.60:
                    response = "compliant"
                elif r < 0.80:
                    response = "partial"
                else:
                    response = "non_compliant"
            evidence = (
                f"DOC-{sid}-{sc['criterion_id']}" if response != "non_compliant" else ""
            )
            all_responses.append(
                (resp_id, sid, sc["criterion_id"], response, evidence)
            )
            resp_id += 1

    cur.executemany(
        "INSERT INTO sustainability_responses VALUES (?,?,?,?,?)", all_responses
    )

    conn.commit()
    conn.close()

    # ================================================================
    # WORKSPACE FILES
    # ================================================================

    # ---------- Fixed config files ----------

    # 1. tender_specification.yaml
    tender_spec = {
        "tender_id": tender_id,
        "title": "Municipal Infrastructure Improvement Program - Phase III",
        "category": "Municipal Infrastructure",
        "required_certificates": [
            "ISO 9001", "ISO 14001", "Municipal Works License", "Safety Certification",
        ],
        "min_avg_performance_score": 65.0,
        "min_established_years": 3,
        "evaluation_date": "2026-04-15",
        "description": (
            "Multi-phase infrastructure upgrade including roads, drainage, "
            "utilities and environmental remediation for the greater metropolitan area."
        ),
    }
    with open(os.path.join(workspace, "tender_specification.yaml"), "w") as f:
        yaml.dump(tender_spec, f, default_flow_style=False, sort_keys=False)

    # 2. sustainability_criteria.json
    with open(os.path.join(workspace, "sustainability_criteria.json"), "w") as f:
        json.dump({"criteria": sustainability_criteria}, f, indent=2)

    # 3. scoring_methodology.yaml
    scoring = {
        "dimensions": {
            "performance": {
                "weight": 0.25,
                "description": "Combined project performance and client reliability",
                "components": {
                    "project_history_avg": {
                        "weight": 0.70,
                        "description": (
                            "Arithmetic mean of all performance_score values "
                            "from past project records"
                        ),
                    },
                    "reliability_rating": {
                        "weight": 0.30,
                        "description": (
                            "From reference summary files; normalize to 0-100 "
                            "by (rating / 10) * 100; use 50.0 as default if not found"
                        ),
                    },
                },
            },
            "financial": {
                "weight": 0.20,
                "description": "Financial health composite score",
                "components": {
                    "profit_margin_pct": {
                        "weight": 0.30,
                        "normalization": "min(value / 30.0 * 100, 100)",
                    },
                    "liquidity_ratio": {
                        "weight": 0.25,
                        "normalization": "min(value / 5.0 * 100, 100)",
                    },
                    "debt_health": {
                        "weight": 0.25,
                        "normalization": "(1 - debt_ratio) * 100",
                    },
                    "credit_score": {
                        "weight": 0.20,
                        "normalization": "min(value / 850 * 100, 100)",
                    },
                },
            },
            "pricing": {
                "weight": 0.20,
                "description": "Bid competitiveness score",
                "method": (
                    "total_bid = sum of all line item total_prices for the supplier; "
                    "score = (lowest_total_among_qualified / supplier_total) * 100"
                ),
            },
            "sustainability": {
                "weight": 0.15,
                "description": "Sustainability compliance score across all criteria",
                "method": (
                    "For each criterion: compliant=1.0, partial=0.5, non_compliant=0.0. "
                    "score = (sum_of_values / total_criteria_count) * 100"
                ),
            },
            "technical": {
                "weight": 0.20,
                "description": "Technical evaluation composite from evaluation files",
                "components": {
                    "technical_score": {"weight": 0.50},
                    "innovation_score": {"weight": 0.30},
                    "methodology_score": {"weight": 0.20},
                },
            },
        },
        "composite_formula": (
            "Sum of (dimension_score * dimension_weight) for all five dimensions"
        ),
        "ranking": (
            "Descending by composite_score; "
            "ties broken by lower total_bid_amount"
        ),
    }
    with open(os.path.join(workspace, "scoring_methodology.yaml"), "w") as f:
        yaml.dump(scoring, f, default_flow_style=False, sort_keys=False)

    # 4. disqualification_rules.json
    disq_rules = {
        "rules": [
            {
                "rule_id": "DQ-01",
                "description": "Missing any required certificate type listed in tender specification",
                "action": "disqualify",
            },
            {
                "rule_id": "DQ-02",
                "description": "Any required certificate has expired status",
                "action": "disqualify",
            },
            {
                "rule_id": "DQ-03",
                "description": "Mandatory sustainability criteria compliance below 100 percent",
                "detail": "All mandatory criteria must have compliant response",
                "action": "disqualify",
            },
            {
                "rule_id": "DQ-04",
                "description": "Average past performance score below tender minimum threshold",
                "action": "disqualify",
            },
            {
                "rule_id": "DQ-05",
                "description": "Debt ratio exceeds 0.70",
                "action": "disqualify",
            },
            {
                "rule_id": "DQ-06",
                "description": (
                    "Company established less than minimum required years "
                    "before tender evaluation date"
                ),
                "action": "disqualify",
            },
        ],
    }
    with open(os.path.join(workspace, "disqualification_rules.json"), "w") as f:
        json.dump(disq_rules, f, indent=2)

    # ---------- Scalable data files ----------

    num_financial = num_files // 3
    num_reference = num_files // 3
    num_technical = num_files - num_financial - num_reference

    # Re-open DB read-only for workspace file generation
    conn = sqlite3.connect(db_path)

    # -- Financial batch CSV files --
    all_supplier_ids = list(range(1, rows + 1))
    shuffled_for_fin = list(all_supplier_ids)
    random.shuffle(shuffled_for_fin)
    financial_batches = [
        list(b) for b in np.array_split(shuffled_for_fin, num_financial)
    ]

    for batch_idx, batch_sids in enumerate(financial_batches):
        records = []
        for sid in sorted(batch_sids):
            name_row = conn.execute(
                "SELECT name FROM suppliers WHERE supplier_id=?", (int(sid),)
            ).fetchone()
            records.append({
                "supplier_id": int(sid),
                "supplier_name": name_row[0],
                "annual_revenue_millions": round(random.uniform(5, 500), 2),
                "profit_margin_pct": round(random.uniform(2, 28), 2),
                "debt_ratio": round(random.uniform(0.10, 0.85), 2),
                "liquidity_ratio": round(random.uniform(0.8, 6.0), 2),
                "credit_score": random.randint(400, 850),
            })
        df = pd.DataFrame(records)
        df.to_csv(
            os.path.join(workspace, f"financial_batch_{batch_idx + 1}.csv"),
            index=False,
        )

    # -- Reference summary TXT files --
    shuffled_bidders = list(bidder_ids)
    random.shuffle(shuffled_bidders)
    ref_batches = [list(b) for b in np.array_split(shuffled_bidders, num_reference)]

    for batch_idx, batch_sids in enumerate(ref_batches):
        lines = []
        for sid in sorted(batch_sids):
            name_row = conn.execute(
                "SELECT name FROM suppliers WHERE supplier_id=?", (int(sid),)
            ).fetchone()
            sname = name_row[0]
            rating = round(random.uniform(4.0, 9.8), 1)
            lines.append(f"=== Reference Summary for {sname} (ID: {sid}) ===")
            lines.append(
                "Based on feedback from previous municipal and private sector clients,"
            )
            lines.append(
                f"{sname} has demonstrated consistent delivery capabilities."
            )
            lines.append(
                f"Client satisfaction surveys indicate an overall reliability_rating: {rating}/10"
            )
            lines.append(
                "This rating reflects timeliness, communication quality, and workmanship."
            )
            lines.append("")

        with open(
            os.path.join(workspace, f"reference_summary_{batch_idx + 1}.txt"), "w"
        ) as f:
            f.write("\n".join(lines))

    # -- Technical evaluation JSON files --
    tech_batches = [list(b) for b in np.array_split(bidder_ids, num_technical)]

    for batch_idx, batch_sids in enumerate(tech_batches):
        evaluations = []
        for sid in batch_sids:
            evaluations.append({
                "supplier_id": int(sid),
                "technical_score": round(random.uniform(40, 98), 1),
                "innovation_score": round(random.uniform(30, 95), 1),
                "methodology_score": round(random.uniform(35, 95), 1),
            })
        with open(
            os.path.join(workspace, f"technical_evaluation_{batch_idx + 1}.json"), "w"
        ) as f:
            json.dump({"evaluations": evaluations}, f, indent=2)

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
