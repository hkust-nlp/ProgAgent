import argparse
import os
import sqlite3
import json
import csv
import random
from datetime import date

import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 30,
}


def main(db_path, workspace):
    np.random.seed(42)
    random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)
    n = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # ----------------------------------------------------------------
    # Reference constants
    # ----------------------------------------------------------------
    CATEGORIES = ["Electronics", "Textiles", "Machinery", "Chemicals", "Agricultural"]
    HS_PREFIXES = {
        "Electronics": "85",
        "Textiles": "52",
        "Machinery": "84",
        "Chemicals": "29",
        "Agricultural": "08",
    }
    CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CNY", "KRW", "INR", "BRL", "MXN", "THB"]
    EXCHANGE_RATES = {
        "USD": 1.0,
        "EUR": 1.08,
        "GBP": 1.27,
        "JPY": 0.0067,
        "CNY": 0.14,
        "KRW": 0.00075,
        "INR": 0.012,
        "BRL": 0.20,
        "MXN": 0.058,
        "THB": 0.028,
    }
    PORTS = [
        "Los Angeles", "New York", "Houston", "Miami",
        "Seattle", "Chicago", "Savannah", "Norfolk",
    ]
    PORT_SURCHARGES = {
        "Los Angeles": 0.04,
        "New York": 0.05,
        "Houston": 0.03,
        "Miami": 0.06,
        "Seattle": 0.035,
        "Chicago": 0.025,
        "Savannah": 0.03,
        "Norfolk": 0.045,
    }
    INCOTERMS = ["FOB", "CIF", "CFR", "EXW"]
    COUNTRIES = [
        "China", "India", "Vietnam", "Mexico", "Brazil",
        "Germany", "Japan", "South Korea", "Thailand", "Turkey",
    ]
    UNITS = ["unit", "kg", "meter", "liter", "piece"]

    # ----------------------------------------------------------------
    # Generate products
    # ----------------------------------------------------------------
    products = []
    for i in range(n):
        cat = CATEGORIES[i % len(CATEGORIES)]
        prefix = HS_PREFIXES[cat]
        suffix = f"{i // len(CATEGORIES):04d}"
        hs_code = prefix + suffix
        benchmark = round(float(np.random.uniform(20, 500)), 2)
        products.append({
            "product_id": f"P{i + 1:04d}",
            "hs_code": hs_code,
            "product_name": fake.catch_phrase() + f" {cat[:3]}{i + 1}",
            "category": cat,
            "unit_of_measure": UNITS[i % len(UNITS)],
            "benchmark_price_usd": benchmark,
        })

    # ----------------------------------------------------------------
    # Generate suppliers
    # ----------------------------------------------------------------
    suppliers = []
    for i in range(n):
        suppliers.append({
            "supplier_id": f"S{i + 1:04d}",
            "supplier_name": fake.company(),
            "country": COUNTRIES[i % len(COUNTRIES)],
            "registration_number": fake.bothify("REG-####-??##"),
        })

    # ----------------------------------------------------------------
    # Generate invoices, shipments, freight records, supplements
    # ----------------------------------------------------------------
    invoices = []
    shipments = []
    freight_records = []
    supplements = []

    for i in range(n):
        product = products[int(np.random.randint(0, n))]
        supplier_id = f"S{int(np.random.randint(1, n + 1)):04d}"
        currency = CURRENCIES[int(np.random.randint(0, len(CURRENCIES)))]
        rate = EXCHANGE_RATES[currency]
        quantity = int(np.random.randint(50, 500))
        incoterm = INCOTERMS[int(np.random.randint(0, len(INCOTERMS)))]
        port = PORTS[int(np.random.randint(0, len(PORTS)))]
        surcharge_rate = PORT_SURCHARGES[port]

        freight = round(float(np.random.uniform(200, 3000)), 2)
        insurance = round(float(np.random.uniform(50, 800)), 2)
        packaging = round(float(np.random.uniform(30, 300)), 2)
        handling = round(float(np.random.uniform(10, 150)), 2)

        benchmark = product["benchmark_price_usd"]

        # Decide target CIF per unit
        r = float(np.random.random())
        if r < 0.25:
            # Under-declaration: 15 - 45 % below benchmark
            discount = float(np.random.uniform(0.15, 0.45))
            target_cif = benchmark * (1 - discount)
        else:
            # Normal: within +/- 8 %
            variation = float(np.random.uniform(-0.08, 0.08))
            target_cif = benchmark * (1 + variation)

        # Back-calculate declared_unit_value from target CIF per unit
        total_target = target_cif * quantity

        if incoterm in ("FOB", "EXW"):
            freight_adj = freight
            insurance_adj = insurance
        elif incoterm == "CFR":
            freight_adj = 0
            insurance_adj = insurance
        else:  # CIF
            freight_adj = 0
            insurance_adj = 0

        surcharge_amount = freight * surcharge_rate
        adjustments = freight_adj + insurance_adj + surcharge_amount + packaging + handling

        declared_value_usd_total = total_target - adjustments
        if declared_value_usd_total < quantity * 0.50:
            declared_value_usd_total = quantity * 0.50

        declared_unit_value = round(declared_value_usd_total / (rate * quantity), 2)
        if declared_unit_value < 0.01:
            declared_unit_value = 0.01

        invoice_id = f"INV-{i + 1:04d}"
        inv_date = fake.date_between(
            start_date=date(2024, 1, 1), end_date=date(2025, 12, 31)
        ).isoformat()

        invoices.append({
            "invoice_id": invoice_id,
            "supplier_id": supplier_id,
            "product_id": product["product_id"],
            "declared_unit_value": declared_unit_value,
            "currency": currency,
            "quantity": quantity,
            "invoice_date": inv_date,
        })

        shipments.append({
            "shipment_id": f"SHP-{i + 1:04d}",
            "invoice_id": invoice_id,
            "port_of_entry": port,
            "incoterm": incoterm,
        })

        freight_records.append({
            "invoice_id": invoice_id,
            "freight_cost_usd": freight,
            "insurance_cost_usd": insurance,
        })

        supplements.append({
            "invoice_id": invoice_id,
            "packaging_cost_usd": packaging,
            "handling_cost_usd": handling,
        })

    # ----------------------------------------------------------------
    # Create database
    # ----------------------------------------------------------------
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE products (
        product_id      TEXT PRIMARY KEY,
        hs_code         TEXT NOT NULL,
        product_name    TEXT NOT NULL,
        category        TEXT NOT NULL,
        unit_of_measure TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE suppliers (
        supplier_id         TEXT PRIMARY KEY,
        supplier_name       TEXT NOT NULL,
        country             TEXT NOT NULL,
        registration_number TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE invoices (
        invoice_id          TEXT PRIMARY KEY,
        supplier_id         TEXT NOT NULL,
        product_id          TEXT NOT NULL,
        declared_unit_value REAL NOT NULL,
        currency            TEXT NOT NULL,
        quantity            INTEGER NOT NULL,
        invoice_date        TEXT NOT NULL,
        FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
        FOREIGN KEY (product_id) REFERENCES products(product_id)
    )""")

    c.execute("""CREATE TABLE shipments (
        shipment_id   TEXT PRIMARY KEY,
        invoice_id    TEXT NOT NULL UNIQUE,
        port_of_entry TEXT NOT NULL,
        incoterm      TEXT NOT NULL,
        FOREIGN KEY (invoice_id) REFERENCES invoices(invoice_id)
    )""")

    for p in products:
        c.execute(
            "INSERT INTO products (product_id, hs_code, product_name, "
            "category, unit_of_measure) VALUES (?,?,?,?,?)",
            (p["product_id"], p["hs_code"], p["product_name"],
             p["category"], p["unit_of_measure"]),
        )

    for s in suppliers:
        c.execute(
            "INSERT INTO suppliers VALUES (?,?,?,?)",
            (s["supplier_id"], s["supplier_name"], s["country"],
             s["registration_number"]),
        )

    for inv in invoices:
        c.execute(
            "INSERT INTO invoices VALUES (?,?,?,?,?,?,?)",
            (inv["invoice_id"], inv["supplier_id"], inv["product_id"],
             inv["declared_unit_value"], inv["currency"], inv["quantity"],
             inv["invoice_date"]),
        )

    for shp in shipments:
        c.execute(
            "INSERT INTO shipments VALUES (?,?,?,?)",
            (shp["shipment_id"], shp["invoice_id"],
             shp["port_of_entry"], shp["incoterm"]),
        )

    conn.commit()
    conn.close()

    # ----------------------------------------------------------------
    # Workspace - scalable data files
    # ----------------------------------------------------------------
    # ~40 % freight ledgers, ~30 % supplements, ~30 % benchmarks
    n_freight_files = max(1, n_files * 4 // 10)
    n_supp_files = max(1, n_files * 3 // 10)
    n_bench_files = max(1, n_files - n_freight_files - n_supp_files)

    # 1. Freight / insurance ledger files  (CSV)
    for f_idx in range(n_freight_files):
        chunk = [freight_records[j] for j in range(n) if j % n_freight_files == f_idx]
        fpath = os.path.join(workspace, f"freight_insurance_ledger_{f_idx + 1}.csv")
        with open(fpath, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["invoice_id", "freight_cost_usd", "insurance_cost_usd"]
            )
            writer.writeheader()
            writer.writerows(chunk)

    # 2. Invoice supplement files  (CSV)
    for f_idx in range(n_supp_files):
        chunk = [supplements[j] for j in range(n) if j % n_supp_files == f_idx]
        fpath = os.path.join(workspace, f"invoice_supplements_{f_idx + 1}.csv")
        with open(fpath, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["invoice_id", "packaging_cost_usd", "handling_cost_usd"]
            )
            writer.writeheader()
            writer.writerows(chunk)

    # 3. Market benchmark files  (JSON) - keyed by hs_code
    all_bench = []
    for p in products:
        all_bench.append({
            "hs_code": p["hs_code"],
            "benchmark_unit_price_usd": p["benchmark_price_usd"],
            "product_name": p["product_name"],
            "category": p["category"],
        })
    for f_idx in range(n_bench_files):
        chunk = {}
        for j in range(len(all_bench)):
            if j % n_bench_files == f_idx:
                entry = all_bench[j]
                chunk[entry["hs_code"]] = {
                    "benchmark_unit_price_usd": entry["benchmark_unit_price_usd"],
                    "product_name": entry["product_name"],
                    "category": entry["category"],
                }
        fpath = os.path.join(workspace, f"market_benchmarks_{f_idx + 1}.json")
        with open(fpath, "w") as f:
            json.dump(chunk, f, indent=2)

    # ----------------------------------------------------------------
    # Workspace - fixed reference / policy files
    # ----------------------------------------------------------------

    # Exchange rates  (CSV)
    fpath = os.path.join(workspace, "exchange_rates.csv")
    with open(fpath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["currency_code", "rate_to_usd"])
        for code in sorted(EXCHANGE_RATES.keys()):
            writer.writerow([code, EXCHANGE_RATES[code]])

    # Port surcharges  (YAML)
    fpath = os.path.join(workspace, "port_surcharges.yaml")
    with open(fpath, "w") as f:
        yaml.dump(PORT_SURCHARGES, f, default_flow_style=False)

    # Customs valuation policy  (Markdown)
    policy = """# Customs Valuation Policy

## CIF Value Calculation

The customs value for duty assessment is the adjusted CIF (Cost, Insurance, Freight)
value per unit. The calculation method depends on the trade term (Incoterm) of each
shipment.

### Incoterm Adjustment Rules

- FOB (Free on Board) and EXW (Ex Works): The declared value covers only the goods
  at origin. Add the full freight cost and insurance cost to the declared value.
- CFR (Cost and Freight): Freight is included in the declared value. Add only the
  insurance cost.
- CIF (Cost, Insurance, and Freight): Both freight and insurance are included.
  Neither is added.

### Port Surcharge

A port-specific surcharge is always applied regardless of incoterm.
It is calculated as: freight_cost_usd multiplied by the port surcharge rate.
This amount is added to the total customs value for every invoice.

### Additional Costs

Packaging costs and handling costs from the supplement records are always added
to the total customs value regardless of incoterm.

### Adjusted CIF Per Unit Formula

adjusted_cif_per_unit = total_customs_value / quantity

Where:

  total_customs_value = declared_value_usd
                      + freight_adjustment
                      + insurance_adjustment
                      + port_surcharge_amount
                      + packaging_cost_usd
                      + handling_cost_usd

  declared_value_usd      = declared_unit_value * rate_to_usd * quantity
  freight_adjustment      = freight_cost_usd   if incoterm is FOB or EXW, else 0
  insurance_adjustment    = insurance_cost_usd if incoterm is FOB, EXW, or CFR, else 0
  port_surcharge_amount   = freight_cost_usd * port_surcharge_rate   (always applied)

### Discrepancy Calculation

discrepancy_pct = (benchmark_unit_price_usd - adjusted_cif_per_unit)
                / benchmark_unit_price_usd * 100

A positive value indicates the declared customs value is below the market benchmark.
Flag entries where discrepancy_pct is strictly greater than 10.0.

## Risk Classification

- Medium:   discrepancy_pct > 10.0  and <= 20.0
- High:     discrepancy_pct > 20.0  and <= 35.0
- Critical: discrepancy_pct > 35.0
"""
    with open(os.path.join(workspace, "customs_valuation_policy.md"), "w") as f:
        f.write(policy)

    # Incoterm reference  (YAML)
    incoterm_ref = {
        "FOB": {"add_freight": True, "add_insurance": True,
                "full_name": "Free on Board"},
        "EXW": {"add_freight": True, "add_insurance": True,
                "full_name": "Ex Works"},
        "CFR": {"add_freight": False, "add_insurance": True,
                "full_name": "Cost and Freight"},
        "CIF": {"add_freight": False, "add_insurance": False,
                "full_name": "Cost Insurance and Freight"},
    }
    with open(os.path.join(workspace, "incoterm_reference.yaml"), "w") as f:
        yaml.dump(incoterm_ref, f, default_flow_style=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
