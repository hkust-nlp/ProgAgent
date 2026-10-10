"""
Data generation for warranty claim fraud detection task.
Usage: python data.py --db_path data.db --workspace workspace
"""

import argparse
import os
import json
import sqlite3
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 80,
    "num_workspace_files": 12,
}

PRODUCT_MODELS = {
    "ProMax-X1": {"warranty_days": 730, "msrp": 1299},
    "ProMax-X2": {"warranty_days": 730, "msrp": 1499},
    "Elite-S3": {"warranty_days": 545, "msrp": 899},
    "Elite-S4": {"warranty_days": 545, "msrp": 999},
    "Standard-A1": {"warranty_days": 365, "msrp": 599},
    "Standard-A2": {"warranty_days": 365, "msrp": 649},
    "Budget-B1": {"warranty_days": 180, "msrp": 299},
    "Budget-B2": {"warranty_days": 180, "msrp": 349},
}

CLAIM_TYPES = [
    "manufacturing_defect", "component_failure",
    "wear_and_tear", "accidental_damage",
]
CLAIM_STATUSES = ["pending_review", "approved", "denied", "under_investigation"]
STATUS_WEIGHTS = [0.35, 0.30, 0.20, 0.15]
QC_TEST_TYPES = [
    "visual_inspection", "electrical_test", "stress_test",
    "calibration_check", "thermal_cycling",
]
REPAIR_TYPES = ["warranty_repair", "paid_repair", "recall_service", "diagnostic_only"]
PRODUCTION_LINES = ["LINE-A", "LINE-B", "LINE-C", "LINE-D"]

FRAUD_PATTERNS = [
    ["PHOTO_TIMESTAMP_ANOMALY"],
    ["WARRANTY_EXPIRED"],
    ["QC_PASS_CONTRADICTION"],
    ["PRODUCTION_DATE_ANOMALY"],
    ["REPEAT_SERVICE", "EXCESSIVE_REPAIR_COST"],
    ["PHOTO_TIMESTAMP_ANOMALY", "WARRANTY_EXPIRED"],
    ["QC_PASS_CONTRADICTION", "EXCESSIVE_REPAIR_COST"],
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)
    rng = np.random.RandomState(42)

    rows = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]
    num_photo_batches = max(1, num_files * 2 // 3)
    num_repair_centers = max(1, num_files - num_photo_batches)

    os.makedirs(args.workspace, exist_ok=True)
    model_names = list(PRODUCT_MODELS.keys())

    # =========================================================================
    # 1. Generate Customers
    # =========================================================================
    customers = []
    for i in range(rows):
        customers.append({
            "customer_id": f"CUST-{i + 1:04d}",
            "name": fake.name(),
            "email": fake.email(),
            "phone": fake.phone_number(),
            "address": fake.address().replace("\n", ", "),
            "registration_date": fake.date_between(
                start_date="-5y", end_date="-1y"
            ).isoformat(),
        })

    # =========================================================================
    # 2. Generate Products (initial production dates)
    # =========================================================================
    products = []
    for i in range(rows):
        model = model_names[i % len(model_names)]
        prod_date = datetime(2022, 1, 1) + timedelta(days=int(rng.randint(0, 730)))
        products.append({
            "serial_number": f"SN-{i + 1:05d}",
            "model_name": model,
            "production_date": prod_date.date().isoformat(),
            "production_line": PRODUCTION_LINES[i % len(PRODUCTION_LINES)],
            "batch_id": f"BATCH-{(i // 10) + 1:03d}",
            "msrp": PRODUCT_MODELS[model]["msrp"],
        })

    # =========================================================================
    # 3. Determine claim statuses & fraud assignments
    # =========================================================================
    statuses = list(rng.choice(CLAIM_STATUSES, size=rows, p=STATUS_WEIGHTS))
    pending_indices = [i for i, s in enumerate(statuses) if s == "pending_review"]

    fraud_rng = np.random.RandomState(4242)
    n_pending = len(pending_indices)
    n_fraud = max(4, int(0.30 * n_pending))

    shuffled_pending = pending_indices.copy()
    fraud_rng.shuffle(shuffled_pending)
    fraud_list = shuffled_pending[:n_fraud]
    fraud_indices_set = set(fraud_list)

    claim_fraud_flags = {}
    for fi, idx in enumerate(fraud_list):
        pattern = FRAUD_PATTERNS[fi % len(FRAUD_PATTERNS)]
        claim_fraud_flags[idx] = pattern

    # =========================================================================
    # 4. Generate Claims (safe defaults, then inject fraud)
    # =========================================================================
    claims = []
    for i in range(rows):
        prod = products[i % len(products)]
        cust = customers[i % len(customers)]
        model = prod["model_name"]
        warranty_days = PRODUCT_MODELS[model]["warranty_days"]
        prod_date = datetime.fromisoformat(prod["production_date"])

        flags = claim_fraud_flags.get(i, [])
        is_fraud = i in fraud_indices_set

        # --- Safe base values (no flags triggered) ---
        purchase_date = prod_date + timedelta(days=int(rng.randint(15, 61)))
        max_claim_days = max(31, warranty_days - 30)
        claim_date = purchase_date + timedelta(
            days=int(rng.randint(30, min(max_claim_days, 400) + 1))
        )

        # Claim type: only QC_PASS_CONTRADICTION gets manufacturing_defect
        if "QC_PASS_CONTRADICTION" in flags:
            claim_type = "manufacturing_defect"
        elif statuses[i] == "pending_review":
            claim_type = str(
                rng.choice(["component_failure", "wear_and_tear", "accidental_damage"])
            )
        else:
            claim_type = str(rng.choice(CLAIM_TYPES))

        # --- Inject fraud modifications ---
        if "WARRANTY_EXPIRED" in flags:
            purchase_date = claim_date - timedelta(
                days=warranty_days + int(fraud_rng.randint(30, 91))
            )
            if prod_date >= purchase_date:
                new_prod_date = purchase_date - timedelta(
                    days=int(fraud_rng.randint(15, 61))
                )
                products[i % len(products)]["production_date"] = (
                    new_prod_date.date().isoformat()
                )

        if "PRODUCTION_DATE_ANOMALY" in flags:
            new_prod_date = purchase_date + timedelta(
                days=int(fraud_rng.randint(30, 181))
            )
            products[i % len(products)]["production_date"] = (
                new_prod_date.date().isoformat()
            )

        claims.append({
            "claim_id": f"CLM-{i + 1:04d}",
            "customer_id": cust["customer_id"],
            "serial_number": prod["serial_number"],
            "claim_date": claim_date.date().isoformat(),
            "claim_type": claim_type,
            "failure_description": fake.sentence(nb_words=12),
            "status": statuses[i],
            "purchase_date": purchase_date.date().isoformat(),
        })

    # =========================================================================
    # 5. Generate QC Records
    # =========================================================================
    qc_records = []
    qc_id = 1
    tests_per_product = max(2, math.ceil(rows / len(products)) + 1)

    for prod_idx in range(len(products)):
        sn = products[prod_idx]["serial_number"]
        prod_date = datetime.fromisoformat(products[prod_idx]["production_date"])

        needs_all_pass = (
            prod_idx in claim_fraud_flags
            and "QC_PASS_CONTRADICTION" in claim_fraud_flags[prod_idx]
        )

        n_tests = min(tests_per_product, len(QC_TEST_TYPES))
        for t in range(n_tests):
            test_type = QC_TEST_TYPES[t % len(QC_TEST_TYPES)]
            test_date = prod_date - timedelta(days=int(rng.randint(1, 6)))

            if needs_all_pass:
                result = "pass"
                defect_code = ""
            else:
                result = str(rng.choice(["pass", "fail"], p=[0.85, 0.15]))
                defect_code = (
                    "" if result == "pass"
                    else f"DEF-{int(rng.randint(100, 999))}"
                )

            qc_records.append({
                "qc_id": f"QC-{qc_id:05d}",
                "serial_number": sn,
                "test_station": f"TS-{int(rng.randint(1, 6)):02d}",
                "test_type": test_type,
                "test_date": test_date.date().isoformat(),
                "result": result,
                "defect_code": defect_code,
                "inspector_id": f"INS-{int(rng.randint(1, 21)):03d}",
            })
            qc_id += 1

    # =========================================================================
    # 6. Generate Service History
    # =========================================================================
    service_records = []
    svc_id = 1

    # Base: one service record per product
    for i in range(rows):
        prod_idx = i % len(products)
        sn = products[prod_idx]["serial_number"]
        prod_date = datetime.fromisoformat(products[prod_idx]["production_date"])
        msrp = products[prod_idx]["msrp"]

        svc_date = prod_date + timedelta(days=int(rng.randint(60, 501)))
        max_cost = min(300, msrp * 0.4)
        repair_cost = round(float(rng.uniform(30, max(31, max_cost))), 2)

        service_records.append({
            "service_id": f"SVC-{svc_id:05d}",
            "serial_number": sn,
            "repair_center_id": f"RC-{((svc_id - 1) % num_repair_centers) + 1:03d}",
            "service_date": svc_date.date().isoformat(),
            "repair_type": str(rng.choice(REPAIR_TYPES)),
            "parts_replaced": fake.word() + "_" + fake.word(),
            "repair_cost": repair_cost,
            "technician_id": f"TECH-{int(rng.randint(1, 31)):03d}",
        })
        svc_id += 1

    # Phase A: add extra records for REPEAT_SERVICE fraud
    for idx, flags in claim_fraud_flags.items():
        if "REPEAT_SERVICE" in flags:
            sn = claims[idx]["serial_number"]
            msrp_val = products[idx % len(products)]["msrp"]
            for _ in range(2):
                claim_dt = datetime.fromisoformat(claims[idx]["claim_date"])
                svc_date = claim_dt - timedelta(days=int(fraud_rng.randint(10, 201)))
                cost = (
                    round(float(msrp_val * 0.35), 2)
                    if "EXCESSIVE_REPAIR_COST" in flags
                    else round(float(fraud_rng.uniform(30, 150)), 2)
                )
                service_records.append({
                    "service_id": f"SVC-{svc_id:05d}",
                    "serial_number": sn,
                    "repair_center_id": (
                        f"RC-{((svc_id - 1) % num_repair_centers) + 1:03d}"
                    ),
                    "service_date": svc_date.date().isoformat(),
                    "repair_type": "warranty_repair",
                    "parts_replaced": fake.word() + "_module",
                    "repair_cost": cost,
                    "technician_id": f"TECH-{int(fraud_rng.randint(1, 31)):03d}",
                })
                svc_id += 1

    # Phase B: boost cost for EXCESSIVE_REPAIR_COST only (no REPEAT_SERVICE)
    for idx, flags in claim_fraud_flags.items():
        if "EXCESSIVE_REPAIR_COST" in flags and "REPEAT_SERVICE" not in flags:
            sn = claims[idx]["serial_number"]
            msrp_val = products[idx % len(products)]["msrp"]
            for sr in service_records:
                if sr["serial_number"] == sn:
                    sr["repair_cost"] = round(float(msrp_val * 0.80), 2)
                    break

    service_df = pd.DataFrame(service_records)

    # Phase C: uniform high cost for REPEAT_SERVICE + EXCESSIVE_REPAIR_COST
    for idx, flags in claim_fraud_flags.items():
        if "EXCESSIVE_REPAIR_COST" in flags and "REPEAT_SERVICE" in flags:
            sn = claims[idx]["serial_number"]
            msrp_val = products[idx % len(products)]["msrp"]
            mask = service_df["serial_number"] == sn
            service_df.loc[mask, "repair_cost"] = round(float(msrp_val * 0.35), 2)

    # =========================================================================
    # 7. Write Database
    # =========================================================================
    customers_df = pd.DataFrame(customers)
    products_df = pd.DataFrame(products)
    claims_df = pd.DataFrame(claims)
    qc_df = pd.DataFrame(qc_records)

    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    customers_df.to_sql("customers", conn, if_exists="replace", index=False)
    products_df.to_sql("products", conn, if_exists="replace", index=False)
    claims_df.to_sql("claims", conn, if_exists="replace", index=False)
    qc_df.to_sql("qc_records", conn, if_exists="replace", index=False)
    service_df.to_sql("service_history", conn, if_exists="replace", index=False)
    conn.close()

    # =========================================================================
    # 8. Generate Workspace Files
    # =========================================================================

    # 8a. Photo analysis batch files (.json, scalable)
    photo_dir = os.path.join(args.workspace, "photo_analysis")
    os.makedirs(photo_dir, exist_ok=True)

    photo_rng = np.random.RandomState(42)
    claims_per_batch = max(1, len(claims) // num_photo_batches)

    for batch_idx in range(num_photo_batches):
        start = batch_idx * claims_per_batch
        end = (
            len(claims)
            if batch_idx == num_photo_batches - 1
            else start + claims_per_batch
        )
        batch_claims = claims[start:end]

        batch_entries = []
        for claim in batch_claims:
            claim_date = datetime.fromisoformat(claim["claim_date"])
            claim_idx_orig = int(claim["claim_id"].split("-")[1]) - 1

            if (
                claim_idx_orig in claim_fraud_flags
                and "PHOTO_TIMESTAMP_ANOMALY"
                in claim_fraud_flags[claim_idx_orig]
            ):
                days_off = int(photo_rng.randint(90, 251))
                photo_date = claim_date - timedelta(days=days_off)
            else:
                days_off = int(photo_rng.randint(0, 6))
                photo_date = claim_date - timedelta(days=days_off)

            batch_entries.append({
                "claim_id": claim["claim_id"],
                "photo_taken_date": photo_date.date().isoformat(),
                "device_model": str(
                    photo_rng.choice(
                        ["iPhone-14", "Galaxy-S23", "Pixel-8", "OnePlus-11"]
                    )
                ),
                "file_hash": fake.sha256()[:16],
                "image_resolution": str(
                    photo_rng.choice(
                        ["1920x1080", "3024x4032", "2560x1440", "4000x3000"]
                    )
                ),
                "file_size_kb": int(photo_rng.randint(500, 8001)),
            })

        batch_file = os.path.join(photo_dir, f"batch_{batch_idx + 1:03d}.json")
        with open(batch_file, "w") as f:
            json.dump(batch_entries, f, indent=2)

    # 8b. Repair center log files (.csv, scalable)
    repair_dir = os.path.join(args.workspace, "repair_logs")
    os.makedirs(repair_dir, exist_ok=True)

    repair_rng = np.random.RandomState(42)
    for center_idx in range(num_repair_centers):
        center_id = f"RC-{center_idx + 1:03d}"
        mask = service_df["repair_center_id"] == center_id
        center_services = service_df[mask].to_dict("records")

        center_data = []
        for svc in center_services:
            center_data.append({
                "service_id": svc["service_id"],
                "serial_number": svc["serial_number"],
                "service_date": svc["service_date"],
                "repair_type": svc["repair_type"],
                "parts_replaced": svc["parts_replaced"],
                "repair_cost": svc["repair_cost"],
                "labor_hours": round(float(repair_rng.uniform(0.5, 8.0)), 1),
                "technician_notes": fake.sentence(nb_words=8),
            })

        center_file = os.path.join(repair_dir, f"center_{center_id}.csv")
        if center_data:
            pd.DataFrame(center_data).to_csv(center_file, index=False)
        else:
            pd.DataFrame(columns=[
                "service_id", "serial_number", "service_date", "repair_type",
                "parts_replaced", "repair_cost", "labor_hours", "technician_notes",
            ]).to_csv(center_file, index=False)

    # 8c. Fixed: warranty_policy.yaml
    import yaml

    warranty_data = {
        "warranty_durations_days": {
            m: info["warranty_days"] for m, info in PRODUCT_MODELS.items()
        },
        "coverage_types": {
            "manufacturing_defect": "full",
            "component_failure": "full",
            "wear_and_tear": "limited",
            "accidental_damage": "none",
        },
    }
    with open(os.path.join(args.workspace, "warranty_policy.yaml"), "w") as f:
        yaml.dump(warranty_data, f, default_flow_style=False, sort_keys=False)

    # 8d. Fixed: fraud_detection_rules.yaml
    fraud_rules = {
        "rules": {
            "PHOTO_TIMESTAMP_ANOMALY": {
                "description": (
                    "Photo taken date deviates too far from claim submission date"
                ),
                "max_days_before_claim": 60,
                "max_days_after_claim": 7,
                "risk_points": 25,
            },
            "WARRANTY_EXPIRED": {
                "description": (
                    "Claim filed after warranty period ended based on purchase"
                    " date and model warranty duration"
                ),
                "risk_points": 20,
            },
            "QC_PASS_CONTRADICTION": {
                "description": (
                    "All quality control tests passed for the product but claim"
                    " type is manufacturing_defect"
                ),
                "risk_points": 30,
            },
            "PRODUCTION_DATE_ANOMALY": {
                "description": (
                    "Product production date is after the recorded purchase date"
                    " indicating potential serial number fraud"
                ),
                "risk_points": 35,
            },
            "REPEAT_SERVICE": {
                "description": (
                    "Serial number has excessive prior service visits"
                ),
                "max_prior_services": 2,
                "risk_points": 15,
            },
            "EXCESSIVE_REPAIR_COST": {
                "description": (
                    "Total prior repair costs exceed threshold percentage"
                    " of product MSRP"
                ),
                "cost_threshold_pct": 75,
                "risk_points": 10,
            },
        },
        "risk_score_cap": 100,
        "output_format": {
            "file_name": "flagged_claims_report.csv",
            "columns": [
                "claim_id", "serial_number", "customer_id",
                "flags", "flag_count", "risk_score",
            ],
            "flags_separator": "|",
            "flags_order": "alphabetical",
            "sort_by": [
                {"field": "risk_score", "order": "descending"},
                {"field": "claim_id", "order": "ascending"},
            ],
        },
    }
    with open(os.path.join(args.workspace, "fraud_detection_rules.yaml"), "w") as f:
        yaml.dump(fraud_rules, f, default_flow_style=False, sort_keys=False)

    # 8e. Fixed: defect_code_reference.md
    defect_ref = (
        "# Defect Code Reference\n\n"
        "| Code Range | Category | Description |\n"
        "|-----------|----------|-------------|\n"
        "| DEF-100 to DEF-299 | Electrical | Electrical component failures,"
        " short circuits, power issues |\n"
        "| DEF-300 to DEF-499 | Mechanical | Physical damage, broken parts,"
        " alignment issues |\n"
        "| DEF-500 to DEF-699 | Software | Firmware bugs, calibration drift,"
        " sensor errors |\n"
        "| DEF-700 to DEF-899 | Cosmetic | Surface damage, discoloration,"
        " labeling errors |\n"
        "| DEF-900 to DEF-999 | Safety | Critical safety-related failures"
        " requiring immediate action |\n\n"
        "## Severity Levels\n\n"
        "- Critical (DEF-900+): Immediate recall consideration\n"
        "- Major (DEF-100 to DEF-499): Standard warranty coverage\n"
        "- Minor (DEF-500 to DEF-899): Case-by-case evaluation\n"
    )
    with open(os.path.join(args.workspace, "defect_code_reference.md"), "w") as f:
        f.write(defect_ref)

    # --- Summary ---
    n_pending = sum(1 for s in statuses if s == "pending_review")
    print(f"Database: {args.db_path}")
    print(f"  customers:       {len(customers_df)}")
    print(f"  products:        {len(products_df)}")
    print(f"  claims:          {len(claims_df)}  (pending: {n_pending})")
    print(f"  qc_records:      {len(qc_df)}")
    print(f"  service_history: {len(service_df)}")
    print(f"Workspace: {args.workspace}")
    print(f"  photo batches:   {num_photo_batches}")
    print(f"  repair centers:  {num_repair_centers}")
    print(f"  fixed files:     3")
    print(f"Fraud claims:      {len(fraud_indices_set)}")


if __name__ == "__main__":
    main()
