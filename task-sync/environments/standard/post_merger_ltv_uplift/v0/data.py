import sqlite3
import os
import json
import csv
import argparse
import math
import numpy as np
import pandas as pd
from faker import Faker
import yaml

np.random.seed(42)
fake = Faker()
Faker.seed(42)

SCALE = {
    "rows_per_table": 80,
    "num_workspace_files": 8,
}

SEGMENTS = ["enterprise", "mid_market", "small_business", "consumer"]
REGIONS = ["north", "south", "east", "west"]
COMPANIES = ["acquirer", "target"]
PRODUCT_CATEGORIES = ["software", "hardware", "services", "support", "consulting"]


def generate_customers(n):
    customers = []
    for i in range(n):
        customers.append({
            "customer_id": f"CUST-{i+1:04d}",
            "name": fake.name(),
            "email": fake.email(),
            "segment": SEGMENTS[i % len(SEGMENTS)],
            "region": REGIONS[i % len(REGIONS)],
            "company": COMPANIES[i % len(COMPANIES)],
            "tenure_years": int(np.random.randint(1, 11)),
        })
    return pd.DataFrame(customers)


def generate_products(n):
    products = []
    for i in range(n):
        category = PRODUCT_CATEGORIES[i % len(PRODUCT_CATEGORIES)]
        base_cost = round(float(np.random.uniform(10, 500)), 2)
        margin = float(np.random.uniform(0.2, 0.7))
        retail_price = round(base_cost / (1 - margin), 2)
        products.append({
            "product_id": f"PROD-{i+1:04d}",
            "name": fake.bs().title(),
            "category": category,
            "base_cost": base_cost,
            "retail_price": retail_price,
        })
    return pd.DataFrame(products)


def generate_purchases(customers_df, products_df):
    purchases = []
    pid = 1
    product_ids = products_df["product_id"].tolist()
    n_products = len(product_ids)

    for _, cust in customers_df.iterrows():
        n_purchases = int(np.random.randint(3, 8))
        for _ in range(n_purchases):
            prod_idx = int(np.random.randint(0, n_products))
            prod_id = product_ids[prod_idx]
            year = int(np.random.choice([2022, 2023, 2024]))
            month = int(np.random.randint(1, 13))
            day = int(np.random.randint(1, 29))
            qty = int(np.random.randint(1, 20))
            prod_row = products_df.iloc[prod_idx]
            amount = round(qty * prod_row["retail_price"], 2)
            purchases.append({
                "purchase_id": f"PUR-{pid:06d}",
                "customer_id": cust["customer_id"],
                "product_id": prod_id,
                "purchase_date": f"{year}-{month:02d}-{day:02d}",
                "quantity": qty,
                "amount": amount,
            })
            pid += 1
    return pd.DataFrame(purchases)


def generate_churn(customers_df):
    records = []
    risk_tiers = {"low": (0.02, 0.10), "medium": (0.10, 0.25), "high": (0.25, 0.50)}
    tier_choices = ["low", "medium", "high"]
    tier_probs = [0.4, 0.35, 0.25]

    for _, cust in customers_df.iterrows():
        tier = str(np.random.choice(tier_choices, p=tier_probs))
        lo, hi = risk_tiers[tier]
        prob = round(float(np.random.uniform(lo, hi)), 4)
        records.append({
            "customer_id": cust["customer_id"],
            "annual_churn_probability": prob,
            "risk_tier": tier,
        })
    return pd.DataFrame(records)


def create_database(db_path, customers_df, products_df, purchases_df, churn_df):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)

    customers_df.to_sql("customers", conn, if_exists="replace", index=False)
    products_df.to_sql("products", conn, if_exists="replace", index=False)
    purchases_df.to_sql("purchase_history", conn, if_exists="replace", index=False)
    churn_df.to_sql("churn_records", conn, if_exists="replace", index=False)

    conn.commit()
    conn.close()


def create_workspace(workspace, customers_df, products_df):
    os.makedirs(workspace, exist_ok=True)

    n_files = SCALE["num_workspace_files"]
    n_cust_files = n_files // 2
    n_prod_files = n_files - n_cust_files

    # --- Scalable files: customer profiles (CSV) ---
    n_custs = len(customers_df)
    cust_per_file = math.ceil(n_custs / n_cust_files)
    for i in range(n_cust_files):
        start = i * cust_per_file
        end = min(start + cust_per_file, n_custs)
        batch = customers_df.iloc[start:end]
        rows = []
        for _, cust in batch.iterrows():
            rows.append({
                "customer_id": cust["customer_id"],
                "loyalty_score": round(float(np.random.uniform(10, 95)), 1),
                "nps_rating": int(np.random.randint(1, 11)),
                "cross_sell_propensity": round(float(np.random.uniform(0.05, 0.85)), 3),
            })
        df = pd.DataFrame(rows)
        df.to_csv(os.path.join(workspace, f"customer_profiles_batch_{i+1}.csv"), index=False)

    # --- Scalable files: product analysis (JSON) ---
    n_prods = len(products_df)
    prod_per_file = math.ceil(n_prods / n_prod_files)
    for i in range(n_prod_files):
        start = i * prod_per_file
        end = min(start + prod_per_file, n_prods)
        batch = products_df.iloc[start:end]
        records = []
        for _, prod in batch.iterrows():
            records.append({
                "product_id": prod["product_id"],
                "synergy_factor": round(float(np.random.uniform(0.85, 1.45)), 3),
                "post_merger_margin_adjustment": round(float(np.random.uniform(-0.05, 0.15)), 4),
                "cross_sell_compatibility": round(float(np.random.uniform(0.1, 0.9)), 3),
            })
        with open(os.path.join(workspace, f"product_analysis_batch_{i+1}.json"), "w") as f:
            json.dump(records, f, indent=2)

    # --- Fixed file 1: LTV config (YAML) ---
    ltv_config = {
        "discount_rate": 0.08,
        "projection_years": 3,
        "revenue_growth_rate": 0.03,
    }
    with open(os.path.join(workspace, "ltv_config.yaml"), "w") as f:
        yaml.dump(ltv_config, f, default_flow_style=False)

    # --- Fixed file 2: segment tier rules (JSON) ---
    segment_rules = {
        "enterprise": {"tier": 1, "value_multiplier": 1.5, "priority": "high"},
        "mid_market": {"tier": 2, "value_multiplier": 1.2, "priority": "medium"},
        "small_business": {"tier": 3, "value_multiplier": 1.0, "priority": "medium"},
        "consumer": {"tier": 4, "value_multiplier": 0.8, "priority": "low"},
    }
    with open(os.path.join(workspace, "segment_tier_rules.json"), "w") as f:
        json.dump(segment_rules, f, indent=2)

    # --- Fixed file 3: cross-sell conversion matrix (CSV) ---
    matrix_rows = []
    for seg in SEGMENTS:
        for cat in PRODUCT_CATEGORIES:
            rate = round(float(np.random.uniform(0.02, 0.30)), 3)
            matrix_rows.append({
                "segment": seg,
                "product_category": cat,
                "conversion_rate": rate,
            })
    matrix_df = pd.DataFrame(matrix_rows)
    matrix_df.to_csv(os.path.join(workspace, "cross_sell_conversion_matrix.csv"), index=False)

    # --- Fixed file 4: merger integration params (TXT) ---
    with open(os.path.join(workspace, "merger_integration_params.txt"), "w") as f:
        f.write("# Merger Integration Parameters\n")
        f.write("# Integration costs apply only to customers from the target company.\n")
        f.write("# Costs are amortized evenly over the specified number of years.\n")
        f.write("#\n")
        f.write("# Per-segment annual integration costs (pre-amortization)\n")
        f.write("\n")
        f.write("applies_to=target\n")
        f.write("amortization_years=3\n")
        f.write("\n")
        f.write("enterprise=5000.00\n")
        f.write("mid_market=3000.00\n")
        f.write("small_business=1500.00\n")
        f.write("consumer=800.00\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n_customers = SCALE["rows_per_table"]
    n_products = SCALE["rows_per_table"]

    customers_df = generate_customers(n_customers)
    products_df = generate_products(n_products)
    purchases_df = generate_purchases(customers_df, products_df)
    churn_df = generate_churn(customers_df)

    create_database(args.db_path, customers_df, products_df, purchases_df, churn_df)
    create_workspace(args.workspace, customers_df, products_df)

    print(f"Database created at {args.db_path}")
    print(f"  - customers: {len(customers_df)} rows")
    print(f"  - products: {len(products_df)} rows")
    print(f"  - purchase_history: {len(purchases_df)} rows")
    print(f"  - churn_records: {len(churn_df)} rows")
    print(f"Workspace created at {args.workspace}")
    print(f"  - {SCALE['num_workspace_files']} scalable data files")
    print(f"  - 4 fixed config files")


if __name__ == "__main__":
    main()
