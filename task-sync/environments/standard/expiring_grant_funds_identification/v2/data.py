import argparse
import sqlite3
import os
import json
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

try:
    import yaml
except ImportError:
    import json as _json_fallback

    class yaml:
        @staticmethod
        def dump(data, stream=None, **kwargs):
            import io
            def _to_yaml_str(obj, indent=0):
                lines = []
                prefix = "  " * indent
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(v, (dict, list)):
                            lines.append(f"{prefix}{k}:")
                            lines.append(_to_yaml_str(v, indent + 1))
                        else:
                            lines.append(f"{prefix}{k}: {_format_val(v)}")
                elif isinstance(obj, list):
                    for item in obj:
                        if isinstance(item, (dict, list)):
                            lines.append(f"{prefix}-")
                            lines.append(_to_yaml_str(item, indent + 1))
                        else:
                            lines.append(f"{prefix}- {_format_val(item)}")
                return "\n".join(lines)

            def _format_val(v):
                if isinstance(v, bool):
                    return "true" if v else "false"
                if isinstance(v, str):
                    if any(c in v for c in ":#{}[]&*?|>!%@`"):
                        return f'"{v}"'
                    return v
                return str(v)

            text = _to_yaml_str(data) + "\n"
            if stream:
                stream.write(text)
            else:
                return text

        @staticmethod
        def safe_load(stream):
            raise NotImplementedError("yaml.safe_load fallback not implemented")


SCALE = {
    "rows_per_table": 320,
    "num_workspace_files": 24,
}

REFERENCE_DATE = datetime(2025, 7, 1)
WINDOW_DAYS = 90

DEPARTMENTS = [
    "Biology", "Chemistry", "Physics", "Engineering",
    "Computer Science", "Mathematics", "Psychology", "Economics",
    "Environmental Science", "Biomedical Engineering",
]

SPONSORS = [
    "NSF", "NIH", "DOE", "DOD", "NASA",
    "USDA", "EPA", "Private Foundation Alpha",
    "Private Foundation Beta", "State Science Board",
]

EXPENSE_CATEGORIES = [
    "personnel", "fringe_benefits", "travel", "equipment",
    "supplies", "contractual", "participant_support",
    "tuition_remission", "other",
]

GRANT_TYPES = ["research", "training", "equipment_grant", "center", "fellowship"]


def main(db_path, workspace):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    num_grants = SCALE["rows_per_table"]
    num_workspace_files = SCALE["num_workspace_files"]

    # ---- Create tables ----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS grants (
            grant_id TEXT PRIMARY KEY,
            title TEXT,
            project_director TEXT,
            department TEXT,
            sponsor TEXT,
            original_budget REAL,
            start_date TEXT,
            end_date TEXT,
            status TEXT,
            grant_type TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenditures (
            exp_id TEXT PRIMARY KEY,
            grant_id TEXT,
            transaction_date TEXT,
            amount REAL,
            expense_category TEXT,
            description TEXT,
            fiscal_year INTEGER,
            FOREIGN KEY (grant_id) REFERENCES grants(grant_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS award_modifications (
            mod_id TEXT PRIMARY KEY,
            grant_id TEXT,
            mod_type TEXT,
            amount_change REAL,
            effective_date TEXT,
            new_end_date TEXT,
            description TEXT,
            FOREIGN KEY (grant_id) REFERENCES grants(grant_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sponsor_payments (
            payment_id TEXT PRIMARY KEY,
            grant_id TEXT,
            payment_date TEXT,
            amount REAL,
            payment_method TEXT,
            invoice_number TEXT,
            FOREIGN KEY (grant_id) REFERENCES grants(grant_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS indirect_cost_rates (
            rate_id TEXT PRIMARY KEY,
            department TEXT,
            fiscal_year INTEGER,
            rate_pct REAL,
            base_type TEXT
        )
    """)

    # ---- Generate grants ----
    in_window_count = max(int(num_grants * 0.25), 10)
    nce_out_count = max(2, in_window_count // 5)
    carryover_count = max(2, (in_window_count - nce_out_count) // 4)

    grants = []
    for i in range(num_grants):
        grant_id = f"GRT-{i + 1:04d}"
        title = fake.catch_phrase() + " " + np.random.choice(
            ["Study", "Project", "Initiative", "Program", "Investigation"]
        )
        director = fake.name()
        dept = DEPARTMENTS[i % len(DEPARTMENTS)]
        sponsor = SPONSORS[int(np.random.randint(0, len(SPONSORS)))]
        original_budget = round(float(np.random.uniform(100000, 2000000)), 2)
        grant_type = GRANT_TYPES[int(np.random.randint(0, len(GRANT_TYPES)))]

        start_offset = int(np.random.randint(365, 1460))
        start_date = REFERENCE_DATE - timedelta(days=start_offset)

        if i < in_window_count:
            days_into_window = int(np.random.randint(2, WINDOW_DAYS - 1))
            end_date = REFERENCE_DATE + timedelta(days=days_into_window)
        elif i < in_window_count + max(int(num_grants * 0.1), 4):
            end_date = REFERENCE_DATE - timedelta(days=int(np.random.randint(1, 180)))
        else:
            end_date = REFERENCE_DATE + timedelta(
                days=int(np.random.randint(WINDOW_DAYS + 30, 1200))
            )

        status = "active" if end_date >= REFERENCE_DATE else "closed"

        grants.append(
            {
                "grant_id": grant_id,
                "title": title,
                "project_director": director,
                "department": dept,
                "sponsor": sponsor,
                "original_budget": original_budget,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "status": status,
                "grant_type": grant_type,
            }
        )

    for g in grants:
        cursor.execute(
            "INSERT INTO grants VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                g["grant_id"], g["title"], g["project_director"],
                g["department"], g["sponsor"], g["original_budget"],
                g["start_date"], g["end_date"], g["status"], g["grant_type"],
            ),
        )

    # ---- Generate expenditures ----
    expenditures = []
    exp_counter = 0
    for g in grants:
        num_exp = int(np.random.randint(3, 10))
        start = datetime.strptime(g["start_date"], "%Y-%m-%d")
        end = min(datetime.strptime(g["end_date"], "%Y-%m-%d"), REFERENCE_DATE)
        if end <= start:
            end = start + timedelta(days=30)
        span = max((end - start).days, 1)

        for _ in range(num_exp):
            exp_counter += 1
            trans_date = start + timedelta(days=int(np.random.randint(0, span)))
            category = EXPENSE_CATEGORIES[int(np.random.randint(0, len(EXPENSE_CATEGORIES)))]

            if category == "personnel":
                amount = round(float(np.random.uniform(5000, 80000)), 2)
            elif category == "equipment":
                amount = round(float(np.random.uniform(10000, 150000)), 2)
            elif category == "travel":
                amount = round(float(np.random.uniform(500, 15000)), 2)
            elif category == "fringe_benefits":
                amount = round(float(np.random.uniform(1000, 25000)), 2)
            elif category == "participant_support":
                amount = round(float(np.random.uniform(2000, 50000)), 2)
            elif category == "tuition_remission":
                amount = round(float(np.random.uniform(5000, 40000)), 2)
            else:
                amount = round(float(np.random.uniform(500, 30000)), 2)

            fy = trans_date.year

            expenditures.append(
                {
                    "exp_id": f"EXP-{exp_counter:06d}",
                    "grant_id": g["grant_id"],
                    "transaction_date": trans_date.strftime("%Y-%m-%d"),
                    "amount": amount,
                    "expense_category": category,
                    "description": fake.sentence(nb_words=6),
                    "fiscal_year": fy,
                }
            )

    while len(expenditures) < SCALE["rows_per_table"]:
        exp_counter += 1
        g = grants[int(np.random.randint(0, len(grants)))]
        start = datetime.strptime(g["start_date"], "%Y-%m-%d")
        end = min(datetime.strptime(g["end_date"], "%Y-%m-%d"), REFERENCE_DATE)
        if end <= start:
            end = start + timedelta(days=30)
        span = max((end - start).days, 1)
        trans_date = start + timedelta(days=int(np.random.randint(0, span)))
        category = EXPENSE_CATEGORIES[int(np.random.randint(0, len(EXPENSE_CATEGORIES)))]
        amount = round(float(np.random.uniform(500, 50000)), 2)
        expenditures.append(
            {
                "exp_id": f"EXP-{exp_counter:06d}",
                "grant_id": g["grant_id"],
                "transaction_date": trans_date.strftime("%Y-%m-%d"),
                "amount": amount,
                "expense_category": category,
                "description": fake.sentence(nb_words=6),
                "fiscal_year": trans_date.year,
            }
        )

    for e in expenditures:
        cursor.execute(
            "INSERT INTO expenditures VALUES (?,?,?,?,?,?,?)",
            (
                e["exp_id"], e["grant_id"], e["transaction_date"],
                e["amount"], e["expense_category"], e["description"],
                e["fiscal_year"],
            ),
        )

    # ---- Generate award modifications ----
    modifications = []
    mod_counter = 0

    # Explicit NCE modifications for in-window grants that should be pushed out
    nce_grant_ids = set()
    for i in range(nce_out_count):
        g = grants[i]
        mod_counter += 1
        orig_end = datetime.strptime(g["end_date"], "%Y-%m-%d")
        new_end = REFERENCE_DATE + timedelta(days=WINDOW_DAYS + int(np.random.randint(60, 300)))
        eff_date = orig_end - timedelta(days=int(np.random.randint(30, 120)))
        modifications.append(
            {
                "mod_id": f"MOD-{mod_counter:05d}",
                "grant_id": g["grant_id"],
                "mod_type": "no_cost_extension",
                "amount_change": 0.0,
                "effective_date": eff_date.strftime("%Y-%m-%d"),
                "new_end_date": new_end.strftime("%Y-%m-%d"),
                "description": "No-cost extension approved by sponsor to complete remaining work.",
            }
        )
        nce_grant_ids.add(g["grant_id"])

    # Random modifications for other grants
    for g in grants:
        if np.random.random() < 0.4:
            num_mods = int(np.random.randint(1, 4))
            for _ in range(num_mods):
                mod_counter += 1
                mod_type = str(np.random.choice(["supplement", "reduction", "rebudget"]))
                if mod_type == "supplement":
                    amount_change = round(float(np.random.uniform(10000, 300000)), 2)
                elif mod_type == "reduction":
                    amount_change = round(float(-np.random.uniform(5000, 100000)), 2)
                else:
                    amount_change = 0.0

                start = datetime.strptime(g["start_date"], "%Y-%m-%d")
                end = datetime.strptime(g["end_date"], "%Y-%m-%d")
                span = max((end - start).days, 60)
                eff_offset = int(np.random.randint(30, span))
                eff_date = start + timedelta(days=eff_offset)

                modifications.append(
                    {
                        "mod_id": f"MOD-{mod_counter:05d}",
                        "grant_id": g["grant_id"],
                        "mod_type": mod_type,
                        "amount_change": amount_change,
                        "effective_date": eff_date.strftime("%Y-%m-%d"),
                        "new_end_date": "",
                        "description": fake.sentence(nb_words=8),
                    }
                )

    while len(modifications) < SCALE["rows_per_table"]:
        mod_counter += 1
        g = grants[int(np.random.randint(0, len(grants)))]
        mod_type = str(np.random.choice(["supplement", "reduction", "rebudget"]))
        if mod_type == "supplement":
            amount_change = round(float(np.random.uniform(5000, 100000)), 2)
        elif mod_type == "reduction":
            amount_change = round(float(-np.random.uniform(2000, 50000)), 2)
        else:
            amount_change = 0.0
        start = datetime.strptime(g["start_date"], "%Y-%m-%d")
        end = datetime.strptime(g["end_date"], "%Y-%m-%d")
        span = max((end - start).days, 60)
        eff_date = start + timedelta(days=int(np.random.randint(30, span)))
        modifications.append(
            {
                "mod_id": f"MOD-{mod_counter:05d}",
                "grant_id": g["grant_id"],
                "mod_type": mod_type,
                "amount_change": amount_change,
                "effective_date": eff_date.strftime("%Y-%m-%d"),
                "new_end_date": "",
                "description": fake.sentence(nb_words=8),
            }
        )

    for m in modifications:
        cursor.execute(
            "INSERT INTO award_modifications VALUES (?,?,?,?,?,?,?)",
            (
                m["mod_id"], m["grant_id"], m["mod_type"],
                m["amount_change"], m["effective_date"],
                m["new_end_date"], m["description"],
            ),
        )

    # ---- Generate sponsor payments ----
    payments = []
    pay_counter = 0
    for g in grants:
        num_pay = int(np.random.randint(1, 6))
        start = datetime.strptime(g["start_date"], "%Y-%m-%d")
        end = min(datetime.strptime(g["end_date"], "%Y-%m-%d"), REFERENCE_DATE)
        if end <= start:
            end = start + timedelta(days=30)
        span = max((end - start).days, 1)

        for _ in range(num_pay):
            pay_counter += 1
            pay_date = start + timedelta(days=int(np.random.randint(0, span)))
            amount = round(float(np.random.uniform(10000, g["original_budget"] * 0.3)), 2)
            method = str(np.random.choice(["wire_transfer", "check", "ach", "letter_of_credit"]))
            invoice = f"INV-{fake.unique.random_number(digits=8):08d}"

            payments.append(
                {
                    "payment_id": f"PAY-{pay_counter:06d}",
                    "grant_id": g["grant_id"],
                    "payment_date": pay_date.strftime("%Y-%m-%d"),
                    "amount": amount,
                    "payment_method": method,
                    "invoice_number": invoice,
                }
            )

    while len(payments) < SCALE["rows_per_table"]:
        pay_counter += 1
        g = grants[int(np.random.randint(0, len(grants)))]
        start = datetime.strptime(g["start_date"], "%Y-%m-%d")
        end = min(datetime.strptime(g["end_date"], "%Y-%m-%d"), REFERENCE_DATE)
        if end <= start:
            end = start + timedelta(days=30)
        span = max((end - start).days, 1)
        pay_date = start + timedelta(days=int(np.random.randint(0, span)))
        amount = round(float(np.random.uniform(10000, 200000)), 2)
        method = str(np.random.choice(["wire_transfer", "check", "ach"]))
        invoice = f"INV-{fake.unique.random_number(digits=8):08d}"
        payments.append(
            {
                "payment_id": f"PAY-{pay_counter:06d}",
                "grant_id": g["grant_id"],
                "payment_date": pay_date.strftime("%Y-%m-%d"),
                "amount": amount,
                "payment_method": method,
                "invoice_number": invoice,
            }
        )

    for p in payments:
        cursor.execute(
            "INSERT INTO sponsor_payments VALUES (?,?,?,?,?,?)",
            (
                p["payment_id"], p["grant_id"], p["payment_date"],
                p["amount"], p["payment_method"], p["invoice_number"],
            ),
        )

    # ---- Generate indirect cost rates ----
    rates = []
    rate_counter = 0
    fiscal_years = [2022, 2023, 2024, 2025]
    base_types = ["MTDC", "TDC"]

    for dept in DEPARTMENTS:
        base_rate = float(np.random.uniform(42, 62))
        for fy in fiscal_years:
            for bt in base_types:
                rate_counter += 1
                rate_pct = round(base_rate + float(np.random.uniform(-3, 3)), 2)
                if bt == "TDC":
                    rate_pct = round(rate_pct * 0.7, 2)
                rates.append(
                    {
                        "rate_id": f"IDC-{rate_counter:04d}",
                        "department": dept,
                        "fiscal_year": fy,
                        "rate_pct": rate_pct,
                        "base_type": bt,
                    }
                )

    while len(rates) < SCALE["rows_per_table"]:
        rate_counter += 1
        dept = DEPARTMENTS[int(np.random.randint(0, len(DEPARTMENTS)))]
        fy = int(np.random.randint(2018, 2022))
        bt = str(np.random.choice(base_types))
        rate_pct = round(float(np.random.uniform(30, 65)), 2)
        rates.append(
            {
                "rate_id": f"IDC-{rate_counter:04d}",
                "department": dept,
                "fiscal_year": fy,
                "rate_pct": rate_pct,
                "base_type": bt,
            }
        )

    for r in rates:
        cursor.execute(
            "INSERT INTO indirect_cost_rates VALUES (?,?,?,?,?)",
            (r["rate_id"], r["department"], r["fiscal_year"], r["rate_pct"], r["base_type"]),
        )

    conn.commit()

    # ================================================================
    # WORKSPACE FILES
    # ================================================================

    # ---- Fixed config files (not counted in SCALE) ----

    # 1. reporting_config.yaml
    config = {
        "reference_date": "2025-07-01",
        "window_days": 90,
        "output_file": "use_it_or_lose_it_report.csv",
        "output_columns": [
            "grant_id", "title", "project_director", "director_email",
            "department", "sponsor", "total_awarded", "total_spent",
            "idc_charges", "pending_obligations", "remaining_balance",
            "remaining_pct", "days_to_expiration", "priority_tier",
        ],
        "decimal_precision": 2,
        "sort_primary": "priority_tier",
        "sort_secondary": "days_to_expiration",
        "sort_secondary_order": "ascending",
    }
    with open(os.path.join(workspace, "reporting_config.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # 2. priority_tiers.json
    tiers_config = {
        "tiers": [
            {"name": "critical", "max_days_to_expiration": 30, "min_remaining_pct": 30.0},
            {"name": "high", "max_days_to_expiration": 60, "min_remaining_pct": 20.0},
            {"name": "medium", "max_days_to_expiration": 90, "min_remaining_pct": 10.0},
            {"name": "low", "max_days_to_expiration": 90, "min_remaining_pct": 0.0},
        ],
        "evaluation_order": "first_match",
        "sort_order": ["critical", "high", "medium", "low"],
        "sort_tiebreaker": "days_to_expiration_asc",
    }
    with open(os.path.join(workspace, "priority_tiers.json"), "w") as f:
        json.dump(tiers_config, f, indent=2)

    # 3. idc_policy.yaml
    idc_policy = {
        "base_type": "MTDC",
        "excluded_categories": ["equipment", "participant_support", "tuition_remission"],
        "fiscal_year_start_month": 1,
        "notes": "IDC is calculated on the Modified Total Direct Cost base. Apply the negotiated rate for the fiscal year containing the reporting reference date to cumulative IDC-eligible direct costs. Excluded categories are subtracted from total direct costs before applying the rate.",
    }
    with open(os.path.join(workspace, "idc_policy.yaml"), "w") as f:
        yaml.dump(idc_policy, f, default_flow_style=False, sort_keys=False)

    # ---- Scalable workspace files ----

    num_files = SCALE["num_workspace_files"]
    num_memo_files = max(1, num_files * 3 // 8)
    num_contact_files = max(1, num_files * 2 // 8)
    num_obligation_files = max(1, num_files - num_memo_files - num_contact_files)

    # Identify carryover grants (among in-window, non-NCE grants)
    in_window_grants = []
    for g in grants:
        if g["status"] != "active":
            continue
        end_dt = datetime.strptime(g["end_date"], "%Y-%m-%d")
        if REFERENCE_DATE <= end_dt <= REFERENCE_DATE + timedelta(days=WINDOW_DAYS):
            if g["grant_id"] not in nce_grant_ids:
                in_window_grants.append(g)

    carryover_grant_ids = set()
    for idx in range(min(carryover_count, len(in_window_grants))):
        carryover_grant_ids.add(in_window_grants[idx]["grant_id"])

    # --- Grant memos ---
    os.makedirs(os.path.join(workspace, "grant_memos"), exist_ok=True)
    grants_per_memo = math.ceil(len(grants) / num_memo_files)

    note_templates = [
        "Annual progress report submitted on schedule.",
        "Budget reconciliation completed for current period.",
        "Personnel change: Co-PI added effective last quarter.",
        "Subcontract amendment pending review.",
        "Equipment purchase approved under capital threshold.",
        "Travel reallocation approved per sponsor guidelines.",
        "No outstanding compliance issues noted.",
        "Quarterly financial report filed with sponsor.",
        "IRB renewal approved for human subjects protocol.",
        "Data management plan updated per sponsor requirements.",
    ]

    for file_idx in range(num_memo_files):
        start_idx = file_idx * grants_per_memo
        end_idx = min(start_idx + grants_per_memo, len(grants))
        memo_grants = grants[start_idx:end_idx]

        lines = []
        for g in memo_grants:
            lines.append(f"--- Grant: {g['grant_id']} ---")
            lines.append(f"Project: {g['title']}")
            lines.append(f"Director: {g['project_director']}")
            lines.append(f"Period: {g['start_date']} to {g['end_date']}")

            if g["grant_id"] in carryover_grant_ids:
                lines.append(
                    "NOTE: Carryover of unspent funds has been approved by the sponsor. "
                    "Remaining balance may be carried forward to the next budget period."
                )
            else:
                note = note_templates[int(np.random.randint(0, len(note_templates)))]
                lines.append(f"Status: {note}")
            lines.append("")

        with open(
            os.path.join(workspace, "grant_memos", f"memo_batch_{file_idx + 1}.txt"), "w"
        ) as f:
            f.write("\n".join(lines))

    # --- Director contacts ---
    os.makedirs(os.path.join(workspace, "director_contacts"), exist_ok=True)
    unique_directors = sorted(set(g["project_director"] for g in grants))
    directors_per_file = math.ceil(len(unique_directors) / num_contact_files)

    director_contacts = {}
    for director in unique_directors:
        director_contacts[director] = {
            "email": fake.email(),
            "phone": fake.phone_number(),
            "office": f"Room {int(np.random.randint(100, 999))}, {fake.street_name()} Building",
        }

    for file_idx in range(num_contact_files):
        si = file_idx * directors_per_file
        ei = min(si + directors_per_file, len(unique_directors))
        batch = {d: director_contacts[d] for d in unique_directors[si:ei]}
        with open(
            os.path.join(workspace, "director_contacts", f"contacts_batch_{file_idx + 1}.json"),
            "w",
        ) as f:
            json.dump(batch, f, indent=2)

    # --- Pending obligations ---
    os.makedirs(os.path.join(workspace, "pending_obligations"), exist_ok=True)
    active_grants = [g for g in grants if g["status"] == "active"]
    obligations = []
    for g in active_grants:
        if np.random.random() < 0.55:
            num_oblig = int(np.random.randint(1, 4))
            for _ in range(num_oblig):
                obligations.append(
                    {
                        "grant_id": g["grant_id"],
                        "po_number": f"PO-{int(np.random.randint(100000, 999999))}",
                        "vendor": fake.company(),
                        "amount": round(float(np.random.uniform(1000, 50000)), 2),
                        "obligation_date": (
                            REFERENCE_DATE - timedelta(days=int(np.random.randint(1, 60)))
                        ).strftime("%Y-%m-%d"),
                        "expected_payment_date": (
                            REFERENCE_DATE + timedelta(days=int(np.random.randint(1, 90)))
                        ).strftime("%Y-%m-%d"),
                        "description": fake.sentence(nb_words=5),
                    }
                )

    if not obligations:
        obligations.append(
            {
                "grant_id": active_grants[0]["grant_id"],
                "po_number": "PO-000001",
                "vendor": fake.company(),
                "amount": round(float(np.random.uniform(1000, 10000)), 2),
                "obligation_date": (REFERENCE_DATE - timedelta(days=10)).strftime("%Y-%m-%d"),
                "expected_payment_date": (REFERENCE_DATE + timedelta(days=30)).strftime("%Y-%m-%d"),
                "description": fake.sentence(nb_words=5),
            }
        )

    oblig_per_file = math.ceil(len(obligations) / num_obligation_files)
    for file_idx in range(num_obligation_files):
        si = file_idx * oblig_per_file
        ei = min(si + oblig_per_file, len(obligations))
        batch = obligations[si:ei]
        filepath = os.path.join(
            workspace, "pending_obligations", f"obligations_batch_{file_idx + 1}.csv"
        )
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "grant_id", "po_number", "vendor", "amount",
                    "obligation_date", "expected_payment_date", "description",
                ],
            )
            writer.writeheader()
            for row in batch:
                writer.writerow(row)

    conn.close()
    print(f"Database created at {db_path}")
    print(f"Workspace created at {workspace}")
    print(f"  Grants: {num_grants}")
    print(f"  Expenditures: {len(expenditures)}")
    print(f"  Award modifications: {len(modifications)}")
    print(f"  Sponsor payments: {len(payments)}")
    print(f"  IDC rates: {len(rates)}")
    print(f"  Scalable workspace files: {num_memo_files + num_contact_files + num_obligation_files}")
    print(f"  Fixed config files: 3")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
