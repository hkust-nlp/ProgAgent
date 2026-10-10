#!/usr/bin/env python3
"""Data generation for fundraising reconciliation task."""

import argparse
import csv
import json
import os
import random
import sqlite3

import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 50,
    "num_workspace_files": 10,
}


def main(db_path: str, workspace: str):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    rows = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    # ================================================================
    # TABLE 1: campaigns
    # ================================================================
    num_campaigns = rows
    num_active = max(8, num_campaigns // 6)
    num_paused = max(2, num_campaigns // 10)
    num_completed = num_campaigns - num_active - num_paused

    statuses = (
        ["active"] * num_active
        + ["completed"] * num_completed
        + ["paused"] * num_paused
    )
    random.shuffle(statuses)

    tiers = ["gold", "silver", "bronze"]
    campaigns = []
    for i in range(num_campaigns):
        campaigns.append(
            {
                "id": i + 1,
                "name": fake.catch_phrase() + " Fund",
                "status": statuses[i],
                "start_date": fake.date_between("-2y", "-6m").isoformat(),
                "end_date": fake.date_between("-3m", "+6m").isoformat(),
                "goal_amount": round(random.uniform(10000, 500000), 2),
                "tier": random.choice(tiers),
                "organizer": fake.name(),
            }
        )

    cursor.execute(
        """
        CREATE TABLE campaigns (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            goal_amount REAL NOT NULL,
            tier TEXT NOT NULL,
            organizer TEXT NOT NULL
        )
    """
    )
    for c in campaigns:
        cursor.execute(
            "INSERT INTO campaigns VALUES (?,?,?,?,?,?,?,?)",
            (
                c["id"], c["name"], c["status"], c["start_date"],
                c["end_date"], c["goal_amount"], c["tier"], c["organizer"],
            ),
        )

    active_ids = sorted([c["id"] for c in campaigns if c["status"] == "active"])
    all_ids = [c["id"] for c in campaigns]
    campaign_map = {c["id"]: c for c in campaigns}

    # ================================================================
    # TABLE 2: gateway_deposits
    # ================================================================
    gateways = ["stripe", "paypal", "square"]
    dep_statuses = ["cleared", "pending", "reversed"]
    dep_weights = [0.75, 0.15, 0.10]

    gateway_deposits = []
    row_id = 1
    # Guarantee at least 2 rows per active campaign
    for cid in active_ids:
        for _ in range(2):
            gateway_deposits.append(
                {
                    "id": row_id,
                    "campaign_id": cid,
                    "deposit_date": fake.date_between("-1y", "today").isoformat(),
                    "amount": round(random.uniform(50, 5000), 2),
                    "gateway": random.choice(gateways),
                    "transaction_ref": fake.bothify("TXN-########-????").upper(),
                    "status": random.choices(dep_statuses, weights=dep_weights)[0],
                }
            )
            row_id += 1

    remaining = max(0, rows - len(gateway_deposits))
    for _ in range(remaining):
        cid = random.choice(active_ids) if random.random() < 0.7 else random.choice(all_ids)
        gateway_deposits.append(
            {
                "id": row_id,
                "campaign_id": cid,
                "deposit_date": fake.date_between("-1y", "today").isoformat(),
                "amount": round(random.uniform(50, 5000), 2),
                "gateway": random.choice(gateways),
                "transaction_ref": fake.bothify("TXN-########-????").upper(),
                "status": random.choices(dep_statuses, weights=dep_weights)[0],
            }
        )
        row_id += 1

    cursor.execute(
        """
        CREATE TABLE gateway_deposits (
            id INTEGER PRIMARY KEY,
            campaign_id INTEGER NOT NULL,
            deposit_date TEXT NOT NULL,
            amount REAL NOT NULL,
            gateway TEXT NOT NULL,
            transaction_ref TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
        )
    """
    )
    for d in gateway_deposits:
        cursor.execute(
            "INSERT INTO gateway_deposits VALUES (?,?,?,?,?,?,?)",
            (d["id"], d["campaign_id"], d["deposit_date"], d["amount"],
             d["gateway"], d["transaction_ref"], d["status"]),
        )

    # ================================================================
    # TABLE 3: in_kind_donations
    # ================================================================
    conditions = ["excellent", "good", "fair"]
    categories = ["electronics", "furniture", "art", "vehicles", "clothing"]

    in_kind_donations = []
    row_id = 1
    for cid in active_ids:
        for _ in range(2):
            in_kind_donations.append(
                {
                    "id": row_id,
                    "campaign_id": cid,
                    "donation_date": fake.date_between("-1y", "today").isoformat(),
                    "item_description": fake.sentence(nb_words=4),
                    "base_appraised_value": round(random.uniform(100, 10000), 2),
                    "donor_name": fake.name(),
                    "condition_grade": random.choice(conditions),
                    "category": random.choice(categories),
                }
            )
            row_id += 1

    remaining = max(0, rows - len(in_kind_donations))
    for _ in range(remaining):
        cid = random.choice(active_ids) if random.random() < 0.7 else random.choice(all_ids)
        in_kind_donations.append(
            {
                "id": row_id,
                "campaign_id": cid,
                "donation_date": fake.date_between("-1y", "today").isoformat(),
                "item_description": fake.sentence(nb_words=4),
                "base_appraised_value": round(random.uniform(100, 10000), 2),
                "donor_name": fake.name(),
                "condition_grade": random.choice(conditions),
                "category": random.choice(categories),
            }
        )
        row_id += 1

    cursor.execute(
        """
        CREATE TABLE in_kind_donations (
            id INTEGER PRIMARY KEY,
            campaign_id INTEGER NOT NULL,
            donation_date TEXT NOT NULL,
            item_description TEXT NOT NULL,
            base_appraised_value REAL NOT NULL,
            donor_name TEXT NOT NULL,
            condition_grade TEXT NOT NULL,
            category TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
        )
    """
    )
    for d in in_kind_donations:
        cursor.execute(
            "INSERT INTO in_kind_donations VALUES (?,?,?,?,?,?,?,?)",
            (d["id"], d["campaign_id"], d["donation_date"], d["item_description"],
             d["base_appraised_value"], d["donor_name"], d["condition_grade"], d["category"]),
        )

    # ================================================================
    # TABLE 4: expenses
    # ================================================================
    expense_cats = ["marketing", "logistics", "venue", "staffing", "supplies"]
    exp_statuses = ["approved", "pending", "rejected"]
    exp_weights = [0.60, 0.20, 0.20]

    expenses_data = []
    row_id = 1
    for cid in active_ids:
        for _ in range(2):
            expenses_data.append(
                {
                    "id": row_id,
                    "campaign_id": cid,
                    "expense_date": fake.date_between("-1y", "today").isoformat(),
                    "category": random.choice(expense_cats),
                    "amount": round(random.uniform(50, 3000), 2),
                    "vendor": fake.company(),
                    "status": random.choices(exp_statuses, weights=exp_weights)[0],
                }
            )
            row_id += 1

    remaining = max(0, rows - len(expenses_data))
    for _ in range(remaining):
        cid = random.choice(active_ids) if random.random() < 0.7 else random.choice(all_ids)
        expenses_data.append(
            {
                "id": row_id,
                "campaign_id": cid,
                "expense_date": fake.date_between("-1y", "today").isoformat(),
                "category": random.choice(expense_cats),
                "amount": round(random.uniform(50, 3000), 2),
                "vendor": fake.company(),
                "status": random.choices(exp_statuses, weights=exp_weights)[0],
            }
        )
        row_id += 1

    cursor.execute(
        """
        CREATE TABLE expenses (
            id INTEGER PRIMARY KEY,
            campaign_id INTEGER NOT NULL,
            expense_date TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            vendor TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
        )
    """
    )
    for e in expenses_data:
        cursor.execute(
            "INSERT INTO expenses VALUES (?,?,?,?,?,?,?)",
            (e["id"], e["campaign_id"], e["expense_date"], e["category"],
             e["amount"], e["vendor"], e["status"]),
        )

    # ================================================================
    # TABLE 5: fee_waivers
    # ================================================================
    fee_types = ["platform", "processing", "service"]

    fee_waivers = []
    row_id = 1
    for cid in active_ids:
        fee_waivers.append(
            {
                "id": row_id,
                "campaign_id": cid,
                "waiver_date": fake.date_between("-1y", "today").isoformat(),
                "fee_type": random.choice(fee_types),
                "waiver_amount": round(random.uniform(10, 500), 2),
                "reason": fake.sentence(nb_words=6),
            }
        )
        row_id += 1

    remaining = max(0, rows - len(fee_waivers))
    for _ in range(remaining):
        cid = random.choice(active_ids) if random.random() < 0.7 else random.choice(all_ids)
        fee_waivers.append(
            {
                "id": row_id,
                "campaign_id": cid,
                "waiver_date": fake.date_between("-1y", "today").isoformat(),
                "fee_type": random.choice(fee_types),
                "waiver_amount": round(random.uniform(10, 500), 2),
                "reason": fake.sentence(nb_words=6),
            }
        )
        row_id += 1

    cursor.execute(
        """
        CREATE TABLE fee_waivers (
            id INTEGER PRIMARY KEY,
            campaign_id INTEGER NOT NULL,
            waiver_date TEXT NOT NULL,
            fee_type TEXT NOT NULL,
            waiver_amount REAL NOT NULL,
            reason TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
        )
    """
    )
    for w in fee_waivers:
        cursor.execute(
            "INSERT INTO fee_waivers VALUES (?,?,?,?,?,?)",
            (w["id"], w["campaign_id"], w["waiver_date"], w["fee_type"],
             w["waiver_amount"], w["reason"]),
        )

    conn.commit()

    # ================================================================
    # WORKSPACE: Fixed configuration files (not counted in num_files)
    # ================================================================
    tier_rates = {"gold": 0.03, "silver": 0.05, "bronze": 0.07}

    fee_schedule = {
        "tier_rates": tier_rates,
        "description": "Platform fee rate applied to total deposits (gateway cleared + manual) by campaign tier.",
    }
    with open(os.path.join(workspace, "fee_schedule.yaml"), "w") as f:
        yaml.dump(fee_schedule, f, default_flow_style=False)

    recon_rules = {
        "condition_multipliers": {
            "excellent": 1.00,
            "good": 0.85,
            "fair": 0.70,
        },
        "category_weights": {
            "electronics": 0.90,
            "furniture": 0.95,
            "art": 1.10,
            "vehicles": 0.80,
            "clothing": 0.75,
        },
        "fee_discrepancy_tolerance_pct": 5.0,
        "rounding_precision": 2,
        "notes": (
            "Adjusted in-kind value = (certified_value if available, else base_appraised_value)"
            " * condition_multiplier * category_weight. "
            "Fee discrepancy is flagged when abs(actual_fees - expected_fees) / expected_fees"
            " * 100 > tolerance_pct. Campaigns with zero expected fees are not evaluated for discrepancy."
        ),
    }
    with open(os.path.join(workspace, "reconciliation_rules.json"), "w") as f:
        json.dump(recon_rules, f, indent=2)

    # ================================================================
    # WORKSPACE: Scalable data files
    # ================================================================
    num_deposit_csv = max(2, round(num_files * 0.4))
    num_appraisal_json = max(2, round(num_files * 0.2))
    num_fee_yaml = max(2, round(num_files * 0.2))
    num_expense_txt = num_files - num_deposit_csv - num_appraisal_json - num_fee_yaml
    if num_expense_txt < 2:
        num_expense_txt = 2
        num_deposit_csv = num_files - num_appraisal_json - num_fee_yaml - num_expense_txt

    # --- Manual deposit batch CSVs ---
    num_manual = rows
    manual_deposits = []
    for i in range(num_manual):
        cid = random.choice(active_ids) if random.random() < 0.7 else random.choice(all_ids)
        manual_deposits.append(
            {
                "batch_id": f"MB-{i + 1:05d}",
                "campaign_id": cid,
                "deposit_date": fake.date_between("-1y", "today").isoformat(),
                "amount": round(random.uniform(25, 3000), 2),
                "method": random.choice(["cash", "check", "wire_transfer", "money_order"]),
                "donor_reference": fake.bothify("DON-####-??").upper(),
            }
        )

    _write_chunks_csv(
        manual_deposits,
        num_deposit_csv,
        workspace,
        "deposit_batch",
        ["batch_id", "campaign_id", "deposit_date", "amount", "method", "donor_reference"],
    )

    # --- Appraisal certificate JSONs ---
    sample_size = int(len(in_kind_donations) * 0.6)
    donations_with_certs = random.sample(in_kind_donations, k=sample_size)
    certs = []
    for d in donations_with_certs:
        base = d["base_appraised_value"]
        certified = round(base * random.uniform(0.80, 1.20), 2)
        certs.append(
            {
                "donation_id": d["id"],
                "campaign_id": d["campaign_id"],
                "certified_value": certified,
                "appraiser": fake.name(),
                "certification_date": fake.date_between("-6m", "today").isoformat(),
            }
        )

    _write_chunks_json(certs, num_appraisal_json, workspace, "appraisal_cert")

    # --- Fee statement YAMLs ---
    gateway_cleared_by_cid = {}
    for d in gateway_deposits:
        if d["status"] == "cleared":
            gateway_cleared_by_cid[d["campaign_id"]] = (
                gateway_cleared_by_cid.get(d["campaign_id"], 0) + d["amount"]
            )

    manual_by_cid = {}
    for d in manual_deposits:
        manual_by_cid[d["campaign_id"]] = (
            manual_by_cid.get(d["campaign_id"], 0) + d["amount"]
        )

    fee_entries = []
    for cid in active_ids:
        total_dep = gateway_cleared_by_cid.get(cid, 0) + manual_by_cid.get(cid, 0)
        tier = campaign_map[cid]["tier"]
        expected_fee = total_dep * tier_rates[tier]

        # ~30% get a significant discrepancy
        if random.random() < 0.3:
            actual_fee = round(expected_fee * random.uniform(1.08, 1.25), 2)
        else:
            actual_fee = round(expected_fee * random.uniform(0.98, 1.02), 2)

        platform_pct = random.uniform(0.50, 0.65)
        processing_pct = random.uniform(0.18, 0.30)
        service_pct = 1.0 - platform_pct - processing_pct

        fee_entries.append({"campaign_id": cid, "period": "2025-Q4", "fee_type": "platform",
                            "charged_amount": round(actual_fee * platform_pct, 2)})
        fee_entries.append({"campaign_id": cid, "period": "2025-Q4", "fee_type": "processing",
                            "charged_amount": round(actual_fee * processing_pct, 2)})
        fee_entries.append({"campaign_id": cid, "period": "2025-Q4", "fee_type": "service",
                            "charged_amount": round(actual_fee * service_pct, 2)})

    # Add some noise entries for non-active campaigns
    for cid in all_ids:
        if cid not in active_ids and random.random() < 0.25:
            total_dep = gateway_cleared_by_cid.get(cid, 0) + manual_by_cid.get(cid, 0)
            tier = campaign_map[cid]["tier"]
            fee_amt = round(total_dep * tier_rates[tier] * random.uniform(0.95, 1.05), 2)
            if fee_amt > 0:
                fee_entries.append({"campaign_id": cid, "period": "2025-Q3",
                                    "fee_type": "platform", "charged_amount": fee_amt})

    random.shuffle(fee_entries)
    _write_chunks_yaml(fee_entries, num_fee_yaml, workspace, "fee_statement")

    # --- Expense supplement TXTs (pipe-delimited) ---
    num_supp = max(rows // 3, 10)
    supp_expenses = []
    for i in range(num_supp):
        cid = random.choice(active_ids) if random.random() < 0.7 else random.choice(all_ids)
        supp_expenses.append(
            {
                "supplement_id": f"SUP-{i + 1:04d}",
                "campaign_id": cid,
                "expense_date": fake.date_between("-1y", "today").isoformat(),
                "category": random.choice(expense_cats),
                "amount": round(random.uniform(25, 1500), 2),
                "vendor": fake.company(),
                "notes": fake.sentence(nb_words=5),
            }
        )

    _write_chunks_txt(supp_expenses, num_expense_txt, workspace, "expense_supplement")

    conn.close()


# ---- helper writers ----

def _write_chunks_csv(records, num_chunks, workspace, prefix, fieldnames):
    chunk_size = max(1, len(records) // num_chunks)
    for fi in range(num_chunks):
        start = fi * chunk_size
        end = start + chunk_size if fi < num_chunks - 1 else len(records)
        chunk = records[start:end]
        path = os.path.join(workspace, f"{prefix}_{fi + 1}.csv")
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(chunk)


def _write_chunks_json(records, num_chunks, workspace, prefix):
    chunk_size = max(1, len(records) // num_chunks)
    for fi in range(num_chunks):
        start = fi * chunk_size
        end = start + chunk_size if fi < num_chunks - 1 else len(records)
        chunk = records[start:end]
        path = os.path.join(workspace, f"{prefix}_{fi + 1}.json")
        with open(path, "w") as f:
            json.dump(chunk, f, indent=2)


def _write_chunks_yaml(records, num_chunks, workspace, prefix):
    chunk_size = max(1, len(records) // num_chunks)
    for fi in range(num_chunks):
        start = fi * chunk_size
        end = start + chunk_size if fi < num_chunks - 1 else len(records)
        chunk = records[start:end]
        path = os.path.join(workspace, f"{prefix}_{fi + 1}.yaml")
        with open(path, "w") as f:
            yaml.dump({"fee_records": chunk}, f, default_flow_style=False)


def _write_chunks_txt(records, num_chunks, workspace, prefix):
    fields = ["supplement_id", "campaign_id", "expense_date", "category",
              "amount", "vendor", "notes"]
    chunk_size = max(1, len(records) // num_chunks)
    for fi in range(num_chunks):
        start = fi * chunk_size
        end = start + chunk_size if fi < num_chunks - 1 else len(records)
        chunk = records[start:end]
        path = os.path.join(workspace, f"{prefix}_{fi + 1}.txt")
        with open(path, "w") as f:
            f.write("|".join(fields) + "\n")
            for rec in chunk:
                f.write("|".join(str(rec[k]) for k in fields) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
