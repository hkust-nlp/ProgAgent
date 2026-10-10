"""
Data generation for franchisee procurement compliance audit task.
Generates database tables and workspace files for cross-referencing
purchase orders, approved vendor lists, DC shipment records, and
quality complaints.
"""

import argparse
import sqlite3
import os
import json
import yaml
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime

SCALE = {
    "rows_per_table": 60,        # v1 = 2x base
    "num_workspace_files": 16,   # v1 = base + N (8 + 8)
}

# --- Constants ---
PRODUCT_CATEGORIES = [
    "Produce", "Dairy", "Meat", "Bakery", "Beverages",
    "Frozen", "Condiments", "Packaging",
]

PRODUCTS = {
    "Produce": ["Organic Lettuce", "Roma Tomatoes", "Baby Spinach", "Bell Peppers"],
    "Dairy": ["Whole Milk", "Cheddar Cheese", "Greek Yogurt", "Heavy Cream"],
    "Meat": ["Ground Beef", "Chicken Wings", "Pork Tenderloin", "Turkey Breast"],
    "Bakery": ["Sourdough Bread", "Hamburger Buns", "Croissants", "Tortillas"],
    "Beverages": ["Orange Juice", "Cola Syrup", "Coffee Beans", "Iced Tea Mix"],
    "Frozen": ["Frozen Fries", "Ice Cream", "Frozen Vegetables", "Frozen Pizza Dough"],
    "Condiments": ["Ketchup", "Tomato Sauce", "Mustard", "Ranch Dressing"],
    "Packaging": ["Paper Cups", "Napkins", "Plastic Wrap", "Takeout Containers"],
}

COMPLAINT_TYPES = [
    "contamination", "wrong_quantity", "damaged_goods",
    "expired_product", "foreign_object", "mislabeled", "temperature_violation",
]


def main(db_path, workspace):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    rows = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]
    num_regions = max(2, num_files // 2)
    num_dc_batches = num_files - num_regions

    region_names = [f"Region_{chr(65 + i)}" for i in range(num_regions)]

    # Flat product list and category mapping
    all_products = []
    product_to_category = {}
    for cat, prods in PRODUCTS.items():
        for p in prods:
            all_products.append(p)
            product_to_category[p] = cat

    # ================================================================
    # TABLE 1: franchisees
    # ================================================================
    num_franchisees = rows
    franchisees = []
    for i in range(num_franchisees):
        roll = np.random.random()
        if roll < 0.75:
            status = "active"
        elif roll < 0.88:
            status = "probation"
        else:
            status = "suspended"
        franchisees.append({
            "id": i + 1,
            "name": fake.company(),
            "region": region_names[i % num_regions],
            "city": fake.city(),
            "state": fake.state_abbr(),
            "status": status,
            "join_date": fake.date_between(
                start_date=datetime(2020, 1, 1),
                end_date=datetime(2024, 6, 30),
            ).isoformat(),
        })

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS franchisees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            region TEXT NOT NULL,
            city TEXT,
            state TEXT,
            status TEXT NOT NULL,
            join_date TEXT NOT NULL
        )
    """)
    for f in franchisees:
        cursor.execute(
            "INSERT INTO franchisees VALUES (?,?,?,?,?,?,?)",
            (f["id"], f["name"], f["region"], f["city"],
             f["state"], f["status"], f["join_date"]),
        )

    # ================================================================
    # TABLE 2: suppliers
    # ================================================================
    num_suppliers = rows
    suppliers = []
    suffix_pool = ["Supply Co", "Distributors", "Foods", "Inc", "LLC",
                   "Trading", "Wholesale", "Group"]
    cert_levels = ["Gold", "Silver", "Bronze", "None"]
    cert_probs = [0.2, 0.3, 0.3, 0.2]

    for i in range(num_suppliers):
        cat = PRODUCT_CATEGORIES[i % len(PRODUCT_CATEGORIES)]
        suppliers.append({
            "id": i + 1,
            "name": fake.company() + " " + str(np.random.choice(suffix_pool)),
            "primary_category": cat,
            "country": str(np.random.choice(["US", "US", "US", "Canada", "Mexico"])),
            "city": fake.city(),
            "certification_level": str(np.random.choice(cert_levels, p=cert_probs)),
            "contact_email": fake.email(),
        })

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            primary_category TEXT NOT NULL,
            country TEXT,
            city TEXT,
            certification_level TEXT,
            contact_email TEXT
        )
    """)
    for s in suppliers:
        cursor.execute(
            "INSERT INTO suppliers VALUES (?,?,?,?,?,?,?)",
            (s["id"], s["name"], s["primary_category"], s["country"],
             s["city"], s["certification_level"], s["contact_email"]),
        )

    # ================================================================
    # TABLE 3: purchase_orders  (5x rows for density)
    # ================================================================
    num_pos = rows * 5
    purchase_orders = []
    used_invoices = set()

    for i in range(num_pos):
        fid = (i % num_franchisees) + 1
        sid = int(np.random.randint(1, num_suppliers + 1))
        product = str(np.random.choice(all_products))
        qty = int(np.random.randint(10, 500))
        unit_price = round(float(np.random.uniform(1.5, 50.0)), 2)

        while True:
            inv = f"INV-{np.random.randint(10000, 99999)}"
            if inv not in used_invoices:
                used_invoices.add(inv)
                break

        purchase_orders.append({
            "id": i + 1,
            "franchisee_id": fid,
            "supplier_id": sid,
            "product_name": product,
            "product_category": product_to_category[product],
            "quantity": qty,
            "unit_price": unit_price,
            "total_amount": round(qty * unit_price, 2),
            "order_date": fake.date_between(
                start_date=datetime(2025, 1, 1),
                end_date=datetime(2025, 12, 31),
            ).isoformat(),
            "invoice_number": inv,
            "payment_status": str(np.random.choice(
                ["paid", "pending", "overdue"], p=[0.6, 0.25, 0.15])),
        })

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY,
            franchisee_id INTEGER NOT NULL,
            supplier_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            product_category TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            total_amount REAL NOT NULL,
            order_date TEXT NOT NULL,
            invoice_number TEXT NOT NULL UNIQUE,
            payment_status TEXT NOT NULL,
            FOREIGN KEY (franchisee_id) REFERENCES franchisees(id),
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        )
    """)
    for po in purchase_orders:
        cursor.execute(
            "INSERT INTO purchase_orders VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (po["id"], po["franchisee_id"], po["supplier_id"],
             po["product_name"], po["product_category"], po["quantity"],
             po["unit_price"], po["total_amount"], po["order_date"],
             po["invoice_number"], po["payment_status"]),
        )

    # ================================================================
    # TABLE 4: quality_complaints  (skewed toward bad suppliers)
    # ================================================================
    num_complaints = rows
    bad_supplier_count = max(3, num_suppliers // 8)
    bad_supplier_ids = list(range(1, bad_supplier_count + 1))
    severity_levels = ["low", "medium", "high", "critical"]
    severity_probs = [0.25, 0.35, 0.25, 0.15]

    quality_complaints = []
    for i in range(num_complaints):
        if np.random.random() < 0.55:
            sid = int(np.random.choice(bad_supplier_ids))
        else:
            sid = int(np.random.randint(1, num_suppliers + 1))
        fid = int(np.random.randint(1, num_franchisees + 1))
        quality_complaints.append({
            "id": i + 1,
            "franchisee_id": fid,
            "supplier_id": sid,
            "product_name": str(np.random.choice(all_products)),
            "complaint_type": str(np.random.choice(COMPLAINT_TYPES)),
            "severity_level": str(np.random.choice(severity_levels, p=severity_probs)),
            "complaint_date": fake.date_between(
                start_date=datetime(2025, 1, 1),
                end_date=datetime(2025, 12, 31),
            ).isoformat(),
            "resolved": int(np.random.choice([0, 1], p=[0.3, 0.7])),
        })

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quality_complaints (
            id INTEGER PRIMARY KEY,
            franchisee_id INTEGER NOT NULL,
            supplier_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            complaint_type TEXT NOT NULL,
            severity_level TEXT NOT NULL,
            complaint_date TEXT NOT NULL,
            resolved INTEGER NOT NULL,
            FOREIGN KEY (franchisee_id) REFERENCES franchisees(id),
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        )
    """)
    for qc in quality_complaints:
        cursor.execute(
            "INSERT INTO quality_complaints VALUES (?,?,?,?,?,?,?,?)",
            (qc["id"], qc["franchisee_id"], qc["supplier_id"],
             qc["product_name"], qc["complaint_type"],
             qc["severity_level"], qc["complaint_date"], qc["resolved"]),
        )

    conn.commit()

    # ================================================================
    # WORKSPACE: Fixed files (not counted in SCALE)
    # ================================================================

    # --- compliance_policy.yaml ---
    policy = {
        "violation_types": {
            "UNAPPROVED_SUPPLIER": {
                "description": "Purchase from a supplier not on the approved vendor list for the franchisee region",
                "severity_weight": 10,
            },
            "EXPIRED_APPROVAL": {
                "description": "Purchase from a supplier whose regional approval had expired before the order date",
                "severity_weight": 7,
            },
            "QUALITY_FLAGGED": {
                "description": "Purchase from a supplier whose total complaint count meets or exceeds the complaint threshold",
                "severity_weight": 8,
            },
            "DC_BYPASS": {
                "description": "Purchase order with no matching central distribution center shipment record",
                "severity_weight": 5,
            },
        },
        "complaint_threshold": 3,
        "severity_multipliers": {
            "critical": 4.0,
            "high": 3.0,
            "medium": 2.0,
            "low": 1.0,
        },
        "severity_score_formula": (
            "For QUALITY_FLAGGED: severity_weight * max(severity_multipliers "
            "across all complaint severity levels for that supplier). "
            "For all other violation types: severity_weight * 1.0."
        ),
        "report_requirements": {
            "output_file": "compliance_report.csv",
            "columns": [
                "franchisee_id", "franchisee_name", "supplier_id",
                "supplier_name", "violation_type", "invoice_number",
                "order_date", "total_amount", "severity_score", "evidence",
            ],
            "sort_order": (
                "descending by severity_score, then ascending by franchisee_id, "
                "then ascending by order_date"
            ),
        },
    }
    with open(os.path.join(workspace, "compliance_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # --- audit_parameters.txt ---
    audit_text = (
        "audit_period_start=2025-01-01\n"
        "audit_period_end=2025-12-31\n"
        "franchisee_status_filter=active,probation\n"
        "report_currency=USD\n"
        "severity_score_precision=2\n"
    )
    with open(os.path.join(workspace, "audit_parameters.txt"), "w") as f:
        f.write(audit_text)

    # ================================================================
    # WORKSPACE: Scalable files
    # ================================================================

    # --- Approved vendor lists per region (CSV) ---
    avl_rng = np.random.RandomState(42)

    for region in region_names:
        num_approved = max(
            int(num_suppliers * 0.78),
            num_suppliers - max(3, num_suppliers // 6),
        )
        approved_ids = sorted(
            avl_rng.choice(
                range(1, num_suppliers + 1), size=num_approved, replace=False,
            ).tolist()
        )

        entries = []
        for sid in approved_ids:
            sup = suppliers[sid - 1]
            if avl_rng.random() < 0.12:
                a_start = fake.date_between(
                    start_date=datetime(2022, 1, 1),
                    end_date=datetime(2023, 6, 30),
                ).isoformat()
                a_end = fake.date_between(
                    start_date=datetime(2024, 1, 1),
                    end_date=datetime(2024, 12, 31),
                ).isoformat()
            else:
                a_start = fake.date_between(
                    start_date=datetime(2023, 1, 1),
                    end_date=datetime(2024, 6, 30),
                ).isoformat()
                a_end = fake.date_between(
                    start_date=datetime(2026, 1, 1),
                    end_date=datetime(2027, 12, 31),
                ).isoformat()

            entries.append({
                "supplier_id": sid,
                "supplier_name": sup["name"],
                "approved_categories": sup["primary_category"],
                "approval_start": a_start,
                "approval_end": a_end,
            })

        path = os.path.join(workspace, f"approved_vendors_{region.lower()}.csv")
        pd.DataFrame(entries).to_csv(path, index=False)

    # --- DC shipment batch files (JSON) ---
    dc_rng = np.random.RandomState(4242)
    all_shipments = []
    ship_counter = 1

    for po in purchase_orders:
        if dc_rng.random() < 0.80:
            all_shipments.append({
                "shipment_id": f"SH-{ship_counter:06d}",
                "franchisee_id": po["franchisee_id"],
                "supplier_id": po["supplier_id"],
                "product_name": po["product_name"],
                "quantity_shipped": po["quantity"],
                "shipment_date": po["order_date"],
                "invoice_ref": po["invoice_number"],
            })
            ship_counter += 1

    dc_rng.shuffle(all_shipments)
    batch_size = max(1, len(all_shipments) // num_dc_batches)
    for b in range(num_dc_batches):
        start = b * batch_size
        if b == num_dc_batches - 1:
            batch = all_shipments[start:]
        else:
            batch = all_shipments[start:start + batch_size]
        path = os.path.join(workspace, f"dc_shipment_batch_{b + 1}.json")
        with open(path, "w") as f:
            json.dump(batch, f, indent=2)

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
