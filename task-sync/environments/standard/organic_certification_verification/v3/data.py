import argparse
import json
import os
import sqlite3
import random
import csv

import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta
import yaml

SCALE = {
    "rows_per_table": 480,
    "num_workspace_files": 32,
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DELIVERY_DATE = "2026-03-15"

ORGANIC_CHEMICALS = [
    "Neem Oil", "Pyrethrin", "Copper Sulfate", "Bacillus thuringiensis",
    "Spinosad", "Kaolin Clay", "Sulfur Dust", "Rotenone",
    "Diatomaceous Earth", "Horticultural Oil", "Garlic Extract",
    "Citric Acid Solution",
]

SYNTHETIC_CHEMICALS = [
    "Chlorpyrifos", "Malathion", "Glyphosate", "Carbaryl", "Atrazine",
    "Methyl Bromide", "Imidacloprid", "Cypermethrin", "Deltamethrin",
    "Paraquat", "2,4-D", "Dicamba",
]

ACCREDITED_LABS = [
    "GreenTest Laboratories", "EcoAnalytica Inc.", "PureEarth Labs",
    "BioAssay International", "TerraCheck Diagnostics", "OrganicVerify Labs",
    "SoilSafe Testing", "AgriCert Laboratories", "NatureLab Sciences",
    "CropGuard Analytics", "FreshFields Testing", "GlobalSoil Certifiers",
    "PrimeAgri Labs", "EarthPure Diagnostics", "GreenLeaf Analytics",
]

NON_ACCREDITED_LABS = [
    "QuickTest Services", "BudgetLab Inc.", "FastSoil Screening",
    "LocalAgri Tests", "RapidCheck Labs",
]

AUDITOR_ORGS = [
    "USDA Organic Certifiers", "EU BioInspect", "Global Organic Alliance",
    "CertOrganic International", "NatureCert Group", "OrganicTrust Auditors",
    "BioSuisse Inspectors", "IFOAM Accredited Auditors",
]

REGIONS = [
    "California Central Valley", "Michoacan Mexico", "Peru Coastal",
    "Chile Central", "Colombia Highland", "Dominican Republic",
    "Kenya Rift Valley", "South Africa Western Cape",
]

PROCESSORS = [
    "AvoPack Industries", "FreshHarvest Processing", "GreenGold Packers",
    "TropiFresh LLC", "OrganicSelect Processing", "PureAvocado Co.",
    "NaturePack Solutions", "HarvestPrime Processing",
]

GRADES = ["Premium", "Grade A", "Grade B", "Utility"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(db_path: str, workspace: str):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    num_farms = SCALE["rows_per_table"]
    num_pest_records = SCALE["rows_per_table"] * 4
    num_soil_tests = SCALE["rows_per_table"] * 2
    num_lots = SCALE["rows_per_table"] * 2
    num_certs = SCALE["rows_per_table"]
    num_batch_lots = SCALE["num_workspace_files"]

    delivery_date = datetime.strptime(DELIVERY_DATE, "%Y-%m-%d")

    # ======================================================================
    # 1. FARMS
    # ======================================================================
    farms = []
    for i in range(num_farms):
        farms.append(
            {
                "farm_id": f"FARM-{i+1:04d}",
                "farm_name": fake.company() + " Farms",
                "region": REGIONS[i % len(REGIONS)],
                "acreage": round(random.uniform(20, 500), 1),
                "organic_registered_date": fake.date_between(
                    start_date=datetime(2014, 1, 1),
                    end_date=datetime(2023, 6, 1),
                ).isoformat(),
                "contact_email": fake.email(),
            }
        )

    # ======================================================================
    # 2. PESTICIDE APPLICATIONS  (~15 % of farms get synthetic chemicals)
    # ======================================================================
    farms_with_synthetic = set(
        random.sample(range(num_farms), max(1, num_farms // 7))
    )

    pest_apps = []
    for i in range(num_pest_records):
        farm_idx = i % num_farms
        farm_id = farms[farm_idx]["farm_id"]
        app_date = fake.date_between(
            start_date=datetime(2022, 1, 1), end_date=datetime(2026, 3, 10)
        )
        if farm_idx in farms_with_synthetic and random.random() < 0.35:
            chemical = random.choice(SYNTHETIC_CHEMICALS)
            category = "synthetic"
        else:
            chemical = random.choice(ORGANIC_CHEMICALS)
            category = "organic_approved"

        pest_apps.append(
            {
                "app_id": i + 1,
                "farm_id": farm_id,
                "application_date": app_date.isoformat(),
                "chemical_name": chemical,
                "chemical_category": category,
                "dosage_kg_per_hectare": round(random.uniform(0.5, 15.0), 2),
                "field_section": random.choice(
                    ["North", "South", "East", "West", "Central"]
                ),
                "applicator_name": fake.name(),
            }
        )

    # ======================================================================
    # 3. SOIL TESTS  (~12 % of farms use non-accredited labs)
    # ======================================================================
    farms_with_bad_lab = set(
        random.sample(range(num_farms), max(1, num_farms // 8))
    )

    soil_tests = []
    for i in range(num_soil_tests):
        farm_idx = i % num_farms
        farm_id = farms[farm_idx]["farm_id"]
        test_date = fake.date_between(
            start_date=datetime(2024, 1, 1), end_date=datetime(2026, 2, 28)
        )

        if random.random() < 0.08:
            ph = round(random.uniform(4.0, 5.4), 2)
        else:
            ph = round(random.uniform(5.5, 7.8), 2)

        if random.random() < 0.06:
            lead = round(random.uniform(41, 80), 2)
        else:
            lead = round(random.uniform(5, 35), 2)

        if random.random() < 0.06:
            cadmium = round(random.uniform(1.6, 4.0), 2)
        else:
            cadmium = round(random.uniform(0.1, 1.3), 2)

        if random.random() < 0.05:
            organic_matter = round(random.uniform(0.5, 1.9), 2)
        else:
            organic_matter = round(random.uniform(2.5, 8.0), 2)

        if farm_idx in farms_with_bad_lab:
            lab = random.choice(NON_ACCREDITED_LABS)
        else:
            lab = random.choice(ACCREDITED_LABS)

        soil_tests.append(
            {
                "test_id": i + 1,
                "farm_id": farm_id,
                "sample_date": test_date.isoformat(),
                "ph_level": ph,
                "organic_matter_pct": organic_matter,
                "lead_ppm": lead,
                "cadmium_ppm": cadmium,
                "nitrogen_ppm": round(random.uniform(10, 200), 1),
                "lab_name": lab,
                "lab_certificate_number": f"LAB-{fake.bothify('??###??').upper()}",
            }
        )

    # ======================================================================
    # 4. AUDIT CERTIFICATES  (~12 % of farms have issues)
    # ======================================================================
    farms_with_bad_cert = set(
        random.sample(range(num_farms), max(1, num_farms // 8))
    )

    certs = []
    for i in range(num_certs):
        farm_idx = i % num_farms
        farm_id = farms[farm_idx]["farm_id"]

        if farm_idx in farms_with_bad_cert:
            if random.random() < 0.5:
                audit_date = fake.date_between(
                    start_date=datetime(2023, 1, 1),
                    end_date=datetime(2024, 6, 1),
                )
                expiry = audit_date + timedelta(days=random.randint(180, 365))
                status = "approved"
            else:
                audit_date = fake.date_between(
                    start_date=datetime(2024, 6, 1),
                    end_date=datetime(2025, 12, 1),
                )
                expiry = audit_date + timedelta(days=random.randint(365, 730))
                status = random.choice(["suspended", "revoked"])
        else:
            audit_date = fake.date_between(
                start_date=datetime(2025, 1, 1), end_date=datetime(2026, 1, 1)
            )
            expiry = audit_date + timedelta(days=random.randint(365, 730))
            status = "approved"

        certs.append(
            {
                "cert_id": i + 1,
                "farm_id": farm_id,
                "auditor_org": random.choice(AUDITOR_ORGS),
                "audit_date": audit_date.isoformat(),
                "expiry_date": expiry.isoformat(),
                "status": status,
                "certificate_number": f"ORG-{fake.bothify('####-??').upper()}",
                "scope": "Avocado Production - Organic",
            }
        )

    # ======================================================================
    # 5. PROCESSOR LOTS
    # ======================================================================
    lots = []
    for i in range(num_lots):
        farm_idx = i % num_farms
        farm_id = farms[farm_idx]["farm_id"]
        processor = PROCESSORS[i % len(PROCESSORS)]
        harvest_date = fake.date_between(
            start_date=datetime(2025, 10, 1), end_date=datetime(2026, 2, 28)
        )
        lot_code = f"LOT-{fake.bothify('???###').upper()}"
        lots.append(
            {
                "lot_id": i + 1,
                "lot_code": lot_code,
                "processor_name": processor,
                "farm_id": farm_id,
                "harvest_date": harvest_date.isoformat(),
                "weight_kg": round(random.uniform(500, 5000), 1),
                "grade": random.choice(GRADES),
                "processing_date": (
                    harvest_date + timedelta(days=random.randint(1, 5))
                ).isoformat(),
                "storage_facility": fake.city() + " Cold Storage",
            }
        )

    # ======================================================================
    # 6. SELECT BATCH LOTS
    # ======================================================================
    batch_lot_indices = sorted(random.sample(range(num_lots), num_batch_lots))
    batch_lots = [lots[i] for i in batch_lot_indices]

    # ======================================================================
    # 7. CREATE DATABASE
    # ======================================================================
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute(
        """CREATE TABLE farms (
        farm_id TEXT PRIMARY KEY,
        farm_name TEXT,
        region TEXT,
        acreage REAL,
        organic_registered_date TEXT,
        contact_email TEXT
    )"""
    )

    c.execute(
        """CREATE TABLE pesticide_applications (
        app_id INTEGER PRIMARY KEY,
        farm_id TEXT,
        application_date TEXT,
        chemical_name TEXT,
        chemical_category TEXT,
        dosage_kg_per_hectare REAL,
        field_section TEXT,
        applicator_name TEXT,
        FOREIGN KEY (farm_id) REFERENCES farms(farm_id)
    )"""
    )

    c.execute(
        """CREATE TABLE soil_tests (
        test_id INTEGER PRIMARY KEY,
        farm_id TEXT,
        sample_date TEXT,
        ph_level REAL,
        organic_matter_pct REAL,
        lead_ppm REAL,
        cadmium_ppm REAL,
        nitrogen_ppm REAL,
        lab_name TEXT,
        lab_certificate_number TEXT,
        FOREIGN KEY (farm_id) REFERENCES farms(farm_id)
    )"""
    )

    c.execute(
        """CREATE TABLE audit_certificates (
        cert_id INTEGER PRIMARY KEY,
        farm_id TEXT,
        auditor_org TEXT,
        audit_date TEXT,
        expiry_date TEXT,
        status TEXT,
        certificate_number TEXT,
        scope TEXT,
        FOREIGN KEY (farm_id) REFERENCES farms(farm_id)
    )"""
    )

    c.execute(
        """CREATE TABLE processor_lots (
        lot_id INTEGER PRIMARY KEY,
        lot_code TEXT UNIQUE,
        processor_name TEXT,
        farm_id TEXT,
        harvest_date TEXT,
        weight_kg REAL,
        grade TEXT,
        processing_date TEXT,
        storage_facility TEXT,
        FOREIGN KEY (farm_id) REFERENCES farms(farm_id)
    )"""
    )

    for f in farms:
        c.execute(
            "INSERT INTO farms VALUES (?,?,?,?,?,?)",
            (
                f["farm_id"], f["farm_name"], f["region"],
                f["acreage"], f["organic_registered_date"], f["contact_email"],
            ),
        )

    for p in pest_apps:
        c.execute(
            "INSERT INTO pesticide_applications VALUES (?,?,?,?,?,?,?,?)",
            (
                p["app_id"], p["farm_id"], p["application_date"],
                p["chemical_name"], p["chemical_category"],
                p["dosage_kg_per_hectare"], p["field_section"],
                p["applicator_name"],
            ),
        )

    for s in soil_tests:
        c.execute(
            "INSERT INTO soil_tests VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                s["test_id"], s["farm_id"], s["sample_date"],
                s["ph_level"], s["organic_matter_pct"], s["lead_ppm"],
                s["cadmium_ppm"], s["nitrogen_ppm"], s["lab_name"],
                s["lab_certificate_number"],
            ),
        )

    for cert in certs:
        c.execute(
            "INSERT INTO audit_certificates VALUES (?,?,?,?,?,?,?,?)",
            (
                cert["cert_id"], cert["farm_id"], cert["auditor_org"],
                cert["audit_date"], cert["expiry_date"], cert["status"],
                cert["certificate_number"], cert["scope"],
            ),
        )

    for lot in lots:
        c.execute(
            "INSERT INTO processor_lots VALUES (?,?,?,?,?,?,?,?,?)",
            (
                lot["lot_id"], lot["lot_code"], lot["processor_name"],
                lot["farm_id"], lot["harvest_date"], lot["weight_kg"],
                lot["grade"], lot["processing_date"], lot["storage_facility"],
            ),
        )

    conn.commit()
    conn.close()

    # ======================================================================
    # 8. WORKSPACE -- FIXED FILES
    # ======================================================================

    # 8a. batch_manifest.json
    batch_manifest = {
        "batch_id": f"BATCH-{fake.bothify('####').upper()}",
        "buyer": fake.company() + " Retail Group",
        "delivery_date": DELIVERY_DATE,
        "lot_codes": [lot["lot_code"] for lot in batch_lots],
        "origin_requirement": "Certified Organic",
        "destination": fake.city() + ", " + fake.state(),
    }
    with open(os.path.join(workspace, "batch_manifest.json"), "w") as fp:
        json.dump(batch_manifest, fp, indent=2)

    # 8b. organic_standards.yaml
    organic_standards = {
        "pesticide_compliance": {
            "lookback_months": 36,
            "banned_categories": ["synthetic"],
            "banned_substances": list(SYNTHETIC_CHEMICALS),
        },
        "soil_quality_thresholds": {
            "ph_min": 5.5,
            "ph_max": 8.0,
            "lead_max_ppm": 40.0,
            "cadmium_max_ppm": 1.5,
            "organic_matter_min_pct": 2.0,
        },
        "lot_inspection_thresholds": {
            "max_temperature_c": 8.0,
            "weight_tolerance_pct": 5.0,
            "max_defect_rate_pct": 8.0,
        },
        "audit_requirements": {
            "valid_statuses": ["approved"],
            "must_not_be_expired_by_delivery": True,
        },
        "lab_accreditation": {
            "require_accredited_lab": True,
            "note": "Soil tests must be performed by a laboratory listed in the approved laboratories registry.",
        },
    }
    with open(os.path.join(workspace, "organic_standards.yaml"), "w") as fp:
        yaml.dump(organic_standards, fp, default_flow_style=False, sort_keys=False)

    # 8c. approved_labs.csv
    with open(os.path.join(workspace, "approved_labs.csv"), "w", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(["lab_name", "accreditation_id", "valid_until"])
        for lab in ACCREDITED_LABS:
            writer.writerow(
                [
                    lab,
                    f"ACC-{fake.bothify('####').upper()}",
                    fake.date_between(
                        start_date=datetime(2026, 6, 1),
                        end_date=datetime(2028, 12, 31),
                    ).isoformat(),
                ]
            )

    # 8d. certification_policy.md  (fixed reference doc)
    policy_md = """# Organic Certification Compliance Policy

This document outlines the compliance verification procedure for organic avocado batches.

## Verification Steps

Each lot in a batch must be traced back to its source farm. For each farm the following
checks are performed:

### Pesticide Compliance
All pesticide applications within the lookback period (defined in the organic standards
configuration) must be reviewed. Any application of a banned substance or substance in a
banned category results in non-compliance for that farm and all associated lots.

### Soil Quality
The most recent soil test for each farm must meet all threshold values defined in the
organic standards. Additionally, the testing laboratory must appear in the approved
laboratories registry.

### Audit Certification
Each farm must hold a valid audit certificate with an approved status that has not expired
as of the batch delivery date.

### Lot Inspection
Physical inspection data for each lot must confirm that storage temperature, weight
accuracy, and defect rates are within acceptable limits defined in the organic standards.

## Compliance Determination
A lot is COMPLIANT only if it passes ALL four checks. If any check fails the lot is
NON_COMPLIANT and specific failure reasons must be documented.

The overall batch is APPROVED only if every lot is compliant. Otherwise the batch is
REJECTED.
"""
    with open(os.path.join(workspace, "certification_policy.md"), "w") as fp:
        fp.write(policy_md)

    # ======================================================================
    # 9. WORKSPACE -- SCALABLE FILES  (one inspection report per batch lot)
    # ======================================================================
    for idx, lot in enumerate(batch_lots):
        declared_weight = lot["weight_kg"]

        # ~18 % weight discrepancy beyond tolerance
        if random.random() < 0.18:
            measured_weight = round(
                declared_weight * random.uniform(1.06, 1.15), 1
            )
        else:
            measured_weight = round(
                declared_weight * random.uniform(0.97, 1.04), 1
            )

        # ~15 % temperature violation
        if random.random() < 0.15:
            temperature = round(random.uniform(8.5, 14.0), 1)
        else:
            temperature = round(random.uniform(1.0, 7.5), 1)

        # ~12 % defect-rate violation
        if random.random() < 0.12:
            defect_rate = round(random.uniform(8.5, 15.0), 1)
        else:
            defect_rate = round(random.uniform(0.5, 7.0), 1)

        inspection_data = {
            "lot_code": lot["lot_code"],
            "inspection_date": (
                delivery_date - timedelta(days=random.randint(1, 5))
            ).isoformat(),
            "inspector_name": fake.name(),
            "measured_weight_kg": measured_weight,
            "temperature_c": temperature,
            "defect_rate_pct": defect_rate,
            "visual_quality": random.choice(
                ["Excellent", "Good", "Acceptable", "Fair"]
            ),
            "notes": fake.sentence(),
        }

        if idx % 2 == 0:
            # JSON format
            fpath = os.path.join(
                workspace, f"inspection_{lot['lot_code']}.json"
            )
            with open(fpath, "w") as fp:
                json.dump(inspection_data, fp, indent=2)
        else:
            # TXT format
            fpath = os.path.join(
                workspace, f"inspection_{lot['lot_code']}.txt"
            )
            with open(fpath, "w") as fp:
                fp.write("LOT INSPECTION REPORT\n")
                fp.write("=" * 40 + "\n")
                fp.write(f"Lot Code: {inspection_data['lot_code']}\n")
                fp.write(
                    f"Inspection Date: {inspection_data['inspection_date']}\n"
                )
                fp.write(f"Inspector: {inspection_data['inspector_name']}\n")
                fp.write(
                    f"Measured Weight (kg): {inspection_data['measured_weight_kg']}\n"
                )
                fp.write(
                    f"Temperature (C): {inspection_data['temperature_c']}\n"
                )
                fp.write(
                    f"Defect Rate (%): {inspection_data['defect_rate_pct']}\n"
                )
                fp.write(
                    f"Visual Quality: {inspection_data['visual_quality']}\n"
                )
                fp.write(f"Notes: {inspection_data['notes']}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
