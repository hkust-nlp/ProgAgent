"""
Data generation for royalty overpayment detection task.
Generates database tables and workspace files for territory split verification.
"""

import argparse
import csv
import json
import os
import random
import sqlite3
from datetime import date, timedelta

import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 32,
}

# Fixed territory definitions
TERRITORIES = [
    ("US", "United States", "North America", True),
    ("CA", "Canada", "North America", False),
    ("GB", "United Kingdom", "Europe", False),
    ("DE", "Germany", "Europe", False),
    ("FR", "France", "Europe", False),
    ("JP", "Japan", "Asia-Pacific", False),
    ("AU", "Australia", "Asia-Pacific", False),
    ("BR", "Brazil", "Latin America", False),
    ("MX", "Mexico", "Latin America", False),
    ("KR", "South Korea", "Asia-Pacific", False),
    ("SE", "Sweden", "Europe", False),
    ("NG", "Nigeria", "Africa", False),
]

TAX_TREATY_RATES = {
    "US": {"withholding_rate": 0.00, "treaty_name": "US Domestic", "effective_date": "2020-01-01"},
    "CA": {"withholding_rate": 0.05, "treaty_name": "US-Canada Tax Treaty", "effective_date": "2019-06-15"},
    "GB": {"withholding_rate": 0.03, "treaty_name": "US-UK Tax Convention", "effective_date": "2018-03-01"},
    "DE": {"withholding_rate": 0.04, "treaty_name": "US-Germany Tax Treaty", "effective_date": "2019-01-01"},
    "FR": {"withholding_rate": 0.045, "treaty_name": "US-France Tax Convention", "effective_date": "2019-07-01"},
    "JP": {"withholding_rate": 0.07, "treaty_name": "US-Japan Tax Treaty", "effective_date": "2020-01-01"},
    "AU": {"withholding_rate": 0.05, "treaty_name": "US-Australia Tax Convention", "effective_date": "2018-06-01"},
    "BR": {"withholding_rate": 0.10, "treaty_name": "US-Brazil Tax Treaty", "effective_date": "2021-01-01"},
    "MX": {"withholding_rate": 0.08, "treaty_name": "US-Mexico Tax Convention", "effective_date": "2020-04-01"},
    "KR": {"withholding_rate": 0.06, "treaty_name": "US-South Korea Tax Treaty", "effective_date": "2019-09-01"},
    "SE": {"withholding_rate": 0.035, "treaty_name": "US-Sweden Tax Convention", "effective_date": "2018-11-01"},
    "NG": {"withholding_rate": 0.12, "treaty_name": "US-Nigeria Tax Treaty", "effective_date": "2021-06-01"},
}


def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    fake = Faker()

    os.makedirs(workspace, exist_ok=True)
    os.makedirs(os.path.join(workspace, "reports"), exist_ok=True)

    territory_codes = [t[0] for t in TERRITORIES]

    # --- Derived counts ---
    n_artists = SCALE["rows_per_table"]
    n_distributors = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]
    n_sales_per_file = max(15, (SCALE["rows_per_table"] * 2) // n_files)
    n_total_sales = n_sales_per_file * n_files

    # --- Generate artists ---
    genres = ["Pop", "Rock", "Hip-Hop", "R&B", "Electronic", "Country",
              "Jazz", "Classical", "Latin", "Indie", "Folk", "Metal"]
    labels = ["Universal Music", "Sony Music", "Warner Music", "BMG", "Concord",
              "Kobalt", "Downtown", "Reservoir", "Hipgnosis", "Primary Wave",
              "AWAL", "Believe Digital", "Empire", "Ditto Music"]

    artists = []
    for i in range(n_artists):
        artists.append({
            "artist_id": i + 1,
            "name": fake.unique.name(),
            "label": random.choice(labels),
            "genre": random.choice(genres),
            "country": fake.country_code(representation="alpha-2"),
        })

    # --- Generate contracts ---
    # Each artist gets contracts in 3-6 territories (ensures cross-territory lookup needs)
    contracts = []
    contract_id = 1
    artist_contract_map = {}  # artist_id -> {territory_code: revenue_share_pct}

    for artist in artists:
        n_terr = random.randint(3, min(6, len(territory_codes)))
        chosen_territories = random.sample(territory_codes, n_terr)
        artist_contract_map[artist["artist_id"]] = {}

        for tc in chosen_territories:
            tid = territory_codes.index(tc) + 1
            share = round(random.uniform(0.08, 0.25), 4)
            start = fake.date_between(start_date=date(2021, 1, 1), end_date=date(2023, 6, 30))
            end = start + timedelta(days=random.randint(730, 1825))

            contracts.append({
                "contract_id": contract_id,
                "artist_id": artist["artist_id"],
                "territory_id": tid,
                "territory_code": tc,
                "revenue_share_pct": share,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "status": "active",
            })
            artist_contract_map[artist["artist_id"]][tc] = share
            contract_id += 1

    # Pad contracts if below minimum
    while len(contracts) < SCALE["rows_per_table"]:
        artist = random.choice(artists)
        tc = random.choice(territory_codes)
        if tc not in artist_contract_map[artist["artist_id"]]:
            tid = territory_codes.index(tc) + 1
            share = round(random.uniform(0.08, 0.25), 4)
            start = fake.date_between(start_date=date(2021, 1, 1), end_date=date(2023, 6, 30))
            end = start + timedelta(days=random.randint(730, 1825))
            contracts.append({
                "contract_id": contract_id,
                "artist_id": artist["artist_id"],
                "territory_id": tid,
                "territory_code": tc,
                "revenue_share_pct": share,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "status": "active",
            })
            artist_contract_map[artist["artist_id"]][tc] = share
            contract_id += 1

    # --- Generate distributors ---
    distributors = []
    for i in range(n_distributors):
        distributors.append({
            "distributor_id": i + 1,
            "name": fake.unique.company(),
            "country": fake.country_code(representation="alpha-2"),
            "tier": random.choice(["platinum", "gold", "silver", "bronze"]),
        })

    # --- Generate sales and payments ---
    quarters = ["Q1-2025", "Q2-2025", "Q3-2025", "Q4-2025"]
    product_types = ["streaming", "download", "physical", "sync_license"]

    # Pre-determine which sales will have territory mismatches (~22%)
    mismatch_indices = set(random.sample(range(n_total_sales),
                                         int(n_total_sales * 0.22)))

    sales = []
    payments = []
    sale_id = 1
    payment_id = 1

    # Filter artists that have at least 2 territory contracts (needed for mismatches)
    multi_terr_artists = [a for a in artists if len(artist_contract_map[a["artist_id"]]) >= 2]
    single_terr_artists = [a for a in artists if len(artist_contract_map[a["artist_id"]]) == 1]

    for file_idx in range(n_files):
        file_sales = []
        for _ in range(n_sales_per_file):
            global_idx = sale_id - 1
            is_mismatch = global_idx in mismatch_indices

            # For mismatches, pick artist with 2+ territories
            if is_mismatch and multi_terr_artists:
                artist = random.choice(multi_terr_artists)
            else:
                artist = random.choice(artists)

            avail_terr = list(artist_contract_map[artist["artist_id"]].keys())
            actual_territory = random.choice(avail_terr)
            gross_revenue = round(random.uniform(500, 50000), 2)
            quarter = random.choice(quarters)
            product_type = random.choice(product_types)
            sale_date = fake.date_between(start_date=date(2025, 1, 1),
                                          end_date=date(2025, 12, 15))

            distributor = random.choice(distributors)
            sale_ref = f"S{sale_id:06d}"

            sale_record = {
                "sale_ref": sale_ref,
                "distributor_id": distributor["distributor_id"],
                "artist_id": artist["artist_id"],
                "artist_name": artist["name"],
                "territory_code": actual_territory,
                "quarter": quarter,
                "gross_revenue": gross_revenue,
                "units_sold": random.randint(100, 100000),
                "product_type": product_type,
                "sale_date": sale_date.isoformat(),
            }
            sales.append(sale_record)
            file_sales.append(sale_record)

            # Determine applied territory
            if is_mismatch and len(avail_terr) > 1:
                actual_rate = artist_contract_map[artist["artist_id"]][actual_territory]
                other_terr = [t for t in avail_terr if t != actual_territory]
                # Bias toward higher-rate territories (70% chance) to create overpayments
                higher_rate = [t for t in other_terr
                               if artist_contract_map[artist["artist_id"]][t] > actual_rate]
                if higher_rate and random.random() < 0.70:
                    applied_territory = random.choice(higher_rate)
                else:
                    applied_territory = random.choice(other_terr)
            else:
                applied_territory = actual_territory

            # Calculate payment amount using applied territory's rate and withholding
            applied_rate = artist_contract_map[artist["artist_id"]][applied_territory]
            applied_withholding = TAX_TREATY_RATES[applied_territory]["withholding_rate"]
            amount_paid = round(gross_revenue * applied_rate * (1 - applied_withholding), 2)

            payment_date = fake.date_between(start_date=sale_date,
                                             end_date=min(sale_date + timedelta(days=60),
                                                          date(2025, 12, 31)))
            payments.append({
                "payment_id": payment_id,
                "sale_ref": sale_ref,
                "artist_id": artist["artist_id"],
                "territory_code": actual_territory,
                "applied_territory_code": applied_territory,
                "amount_paid": amount_paid,
                "payment_date": payment_date.isoformat(),
                "status": "processed",
            })

            sale_id += 1
            payment_id += 1

        # Write workspace CSV for this batch
        filename = f"sales_report_{file_idx + 1:03d}.csv"
        df = pd.DataFrame(file_sales)
        col_order = ["sale_ref", "distributor_id", "artist_id", "artist_name",
                      "territory_code", "quarter", "gross_revenue", "units_sold",
                      "product_type", "sale_date"]
        df[col_order].to_csv(os.path.join(workspace, "reports", filename), index=False)

    # --- Create database ---
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS artists (
        artist_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        label TEXT,
        genre TEXT,
        country TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS territories (
        territory_id INTEGER PRIMARY KEY,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        region TEXT,
        is_domestic INTEGER
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS contracts (
        contract_id INTEGER PRIMARY KEY,
        artist_id INTEGER NOT NULL,
        territory_id INTEGER NOT NULL,
        territory_code TEXT NOT NULL,
        revenue_share_pct REAL NOT NULL,
        start_date TEXT,
        end_date TEXT,
        status TEXT,
        FOREIGN KEY (artist_id) REFERENCES artists(artist_id),
        FOREIGN KEY (territory_id) REFERENCES territories(territory_id)
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS distributors (
        distributor_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        country TEXT,
        tier TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS payments (
        payment_id INTEGER PRIMARY KEY,
        sale_ref TEXT NOT NULL,
        artist_id INTEGER NOT NULL,
        territory_code TEXT NOT NULL,
        applied_territory_code TEXT NOT NULL,
        amount_paid REAL NOT NULL,
        payment_date TEXT,
        status TEXT,
        FOREIGN KEY (artist_id) REFERENCES artists(artist_id)
    )""")

    for a in artists:
        cur.execute("INSERT INTO artists VALUES (?,?,?,?,?)",
                    (a["artist_id"], a["name"], a["label"], a["genre"], a["country"]))

    for i, (code, name, region, is_dom) in enumerate(TERRITORIES):
        cur.execute("INSERT INTO territories VALUES (?,?,?,?,?)",
                    (i + 1, code, name, region, int(is_dom)))

    for c in contracts:
        cur.execute("INSERT INTO contracts VALUES (?,?,?,?,?,?,?,?)",
                    (c["contract_id"], c["artist_id"], c["territory_id"],
                     c["territory_code"], c["revenue_share_pct"],
                     c["start_date"], c["end_date"], c["status"]))

    for d in distributors:
        cur.execute("INSERT INTO distributors VALUES (?,?,?,?)",
                    (d["distributor_id"], d["name"], d["country"], d["tier"]))

    for p in payments:
        cur.execute("INSERT INTO payments VALUES (?,?,?,?,?,?,?,?)",
                    (p["payment_id"], p["sale_ref"], p["artist_id"],
                     p["territory_code"], p["applied_territory_code"],
                     p["amount_paid"], p["payment_date"], p["status"]))

    conn.commit()
    conn.close()

    # --- Write fixed workspace files ---

    # Tax treaties YAML
    with open(os.path.join(workspace, "tax_treaties.yaml"), "w") as f:
        yaml.safe_dump({"tax_treaties": TAX_TREATY_RATES}, f,
                       default_flow_style=False, sort_keys=False)

    # Policy configuration YAML
    policy_config = {
        "overpayment_policy": {
            "minimum_threshold": 50.00,
            "currency": "USD",
            "recovery_priority_rules": {
                "high": {"min_overpayment": 500.00},
                "medium": {"min_overpayment": 200.00},
                "low": {"min_overpayment": 0.00},
            },
            "claim_id_format": "RC-{sequence:04d}",
            "review_period_days": 90,
        }
    }
    with open(os.path.join(workspace, "policy_config.yaml"), "w") as f:
        yaml.safe_dump(policy_config, f, default_flow_style=False, sort_keys=False)

    # Territory reference JSON
    territory_ref = {}
    for code, name, region, is_dom in TERRITORIES:
        territory_ref[code] = {"name": name, "region": region, "is_domestic": is_dom}
    with open(os.path.join(workspace, "territory_reference.json"), "w") as f:
        json.dump(territory_ref, f, indent=2)

    # Royalty calculation rules (Markdown)
    rules_md = """# Royalty Calculation Reference

## Net Royalty Formula

The net royalty payable to an artist for a given sale is computed as:

    net_royalty = gross_revenue * revenue_share_pct * (1 - withholding_rate)

Where:
- **gross_revenue** is the total revenue from the sale as reported by the distributor.
- **revenue_share_pct** is the contractual percentage for the artist in the territory
  where the sale actually occurred.
- **withholding_rate** is the tax treaty withholding rate for the territory where the
  sale actually occurred.

## Territory Determination

The territory of a sale is determined by the market in which the end consumer purchased
or streamed the content. This territory code appears in the distributor sales report.
When verifying payments, always use the territory from the original sale report, not
the territory that may have been applied during payment processing.

## Overpayment Identification

An overpayment exists when the amount actually paid exceeds the correctly calculated
net royalty. Only overpayments exceeding the minimum threshold defined in the policy
configuration should be flagged for recovery.
"""
    with open(os.path.join(workspace, "royalty_calculation_rules.md"), "w") as f:
        f.write(rules_md)

    # Audit context (TXT)
    audit_txt = """ROYALTY AUDIT - TERRITORY SPLIT VERIFICATION
=============================================

Audit Period: Q1-2025 through Q4-2025
Audit Scope: All processed payments across international territories

Background:
Internal controls flagged potential discrepancies in territory-based royalty
calculations. Some payments may have been processed using the revenue share
percentage and/or withholding rate from an incorrect territory. For example,
a sale occurring in Germany might have been paid using the United Kingdom's
contractual rate and withholding schedule.

The payment system records both the actual territory of the sale and the
territory whose rates were applied during payment processing. A mismatch
between these two fields indicates a potential calculation error.

Investigation Procedure:
1. Collect all distributor sales reports for the audit period.
2. Cross-reference each payment against its corresponding sale record.
3. Verify the correct contractual revenue share for the artist in the
   territory where the sale occurred.
4. Apply the appropriate withholding rate from the tax treaty schedule.
5. Calculate the correct net royalty and compare against the amount paid.
6. Flag overpayments exceeding the policy threshold for recovery.

Recovery claims must be documented with full traceability to source records.
"""
    with open(os.path.join(workspace, "audit_context.txt"), "w") as f:
        f.write(audit_txt)

    print(f"Database created at {db_path}")
    print(f"Workspace populated at {workspace}")
    print(f"  Artists: {len(artists)}")
    print(f"  Territories: {len(TERRITORIES)}")
    print(f"  Contracts: {len(contracts)}")
    print(f"  Distributors: {len(distributors)}")
    print(f"  Sales/Payments: {len(payments)}")
    print(f"  Workspace files: {n_files} report CSVs + 4 fixed files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
