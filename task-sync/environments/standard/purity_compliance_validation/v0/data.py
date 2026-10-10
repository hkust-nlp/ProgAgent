"""
Data generation for Certified Seed Lot Purity Compliance Validation task.
Generates database tables and workspace files for cross-referencing
field harvest logs, lab germination tests, parent seed stock certificates,
and government inspection records.
"""

import argparse
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 50,
    "num_workspace_files": 10,
}

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

CROP_TYPES = ["corn", "wheat", "soybean", "rice", "cotton", "sunflower"]
CROP_VARIETIES = {
    "corn": ["Golden Harvest GH4920", "DeKalb DKC62-08", "Pioneer P1197", "Syngenta NK8200", "LG Seeds LG5525"],
    "wheat": ["Hard Red Spring HRS-12", "Soft White Winter SWW-7", "Durum Amber DA-3", "Winter Wheat WW-19", "Spring Wheat SP-44"],
    "soybean": ["Asgrow AG36X6", "Pioneer P22T41R", "Channel 3517R2X", "Stine 36BA22", "NK Soy S32-G2"],
    "rice": ["Clearfield CL151", "Cypress Long Grain", "Jupiter Medium", "Calhoun Short", "Mermentau LG"],
    "cotton": ["Deltapine DP1646", "PhytoGen PHY490", "Stoneville ST5020", "FiberMax FM2334", "Americot AM1550"],
    "sunflower": ["Nuseed N4HM354", "Syngenta SY3636", "Pioneer P64HE01", "LG Seeds LG5665", "Mycogen 8N421"],
}
CERTIFICATION_BODIES = [
    "National Seed Certification Agency",
    "State Seed Testing Laboratory",
    "Federal Crop Inspection Bureau",
    "Regional Seed Quality Authority",
    "International Seed Testing Association",
]
LAB_NAMES = [
    "AgriTest Central Lab",
    "National Seed Analysis Center",
    "Greenfield Quality Assurance",
    "PurityCheck Laboratories",
    "CropScience Testing Institute",
]
EQUIPMENT_IDS = [f"EQ-{i:03d}" for i in range(1, 21)]
INSPECTOR_POOL = [fake.name() for _ in range(15)]
TECHNICIAN_POOL = [fake.name() for _ in range(12)]
OPERATOR_POOL = [fake.name() for _ in range(18)]

COMPLIANCE_THRESHOLDS = {
    "corn": {
        "min_germination_rate": 90.0,
        "min_purity_pct": 98.0,
        "max_moisture_pct": 14.0,
        "max_weed_seed_count": 5,
        "max_other_crop_seed_count": 3,
        "max_inert_matter_pct": 2.0,
        "min_vigor_score": 72.0,
        "max_harvest_temperature_c": 38.0,
        "max_harvest_rainfall_mm": 12.0,
        "valid_parent_generations": ["foundation", "registered"],
    },
    "wheat": {
        "min_germination_rate": 85.0,
        "min_purity_pct": 98.0,
        "max_moisture_pct": 13.5,
        "max_weed_seed_count": 4,
        "max_other_crop_seed_count": 2,
        "max_inert_matter_pct": 1.5,
        "min_vigor_score": 70.0,
        "max_harvest_temperature_c": 35.0,
        "max_harvest_rainfall_mm": 10.0,
        "valid_parent_generations": ["foundation", "registered"],
    },
    "soybean": {
        "min_germination_rate": 80.0,
        "min_purity_pct": 98.0,
        "max_moisture_pct": 13.0,
        "max_weed_seed_count": 5,
        "max_other_crop_seed_count": 3,
        "max_inert_matter_pct": 2.0,
        "min_vigor_score": 68.0,
        "max_harvest_temperature_c": 36.0,
        "max_harvest_rainfall_mm": 8.0,
        "valid_parent_generations": ["foundation", "registered"],
    },
    "rice": {
        "min_germination_rate": 80.0,
        "min_purity_pct": 98.0,
        "max_moisture_pct": 14.0,
        "max_weed_seed_count": 3,
        "max_other_crop_seed_count": 2,
        "max_inert_matter_pct": 1.5,
        "min_vigor_score": 70.0,
        "max_harvest_temperature_c": 37.0,
        "max_harvest_rainfall_mm": 15.0,
        "valid_parent_generations": ["foundation", "registered"],
    },
    "cotton": {
        "min_germination_rate": 80.0,
        "min_purity_pct": 97.0,
        "max_moisture_pct": 12.0,
        "max_weed_seed_count": 6,
        "max_other_crop_seed_count": 3,
        "max_inert_matter_pct": 2.5,
        "min_vigor_score": 65.0,
        "max_harvest_temperature_c": 40.0,
        "max_harvest_rainfall_mm": 10.0,
        "valid_parent_generations": ["foundation", "registered"],
    },
    "sunflower": {
        "min_germination_rate": 75.0,
        "min_purity_pct": 97.0,
        "max_moisture_pct": 10.0,
        "max_weed_seed_count": 5,
        "max_other_crop_seed_count": 4,
        "max_inert_matter_pct": 3.0,
        "min_vigor_score": 65.0,
        "max_harvest_temperature_c": 38.0,
        "max_harvest_rainfall_mm": 8.0,
        "valid_parent_generations": ["foundation", "registered"],
    },
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # ---- Generate parent certificates first ----
    parent_records = []
    base_date = datetime(2024, 1, 1)
    for i in range(n_rows):
        crop = CROP_TYPES[i % len(CROP_TYPES)]
        variety = random.choice(CROP_VARIETIES[crop])
        generation = random.choice(["foundation", "registered"])
        issue_date = base_date + timedelta(days=random.randint(-730, -180))
        # ~15% expired certificates
        if random.random() < 0.15:
            expiry_date = issue_date + timedelta(days=random.randint(180, 365))
        else:
            expiry_date = issue_date + timedelta(days=random.randint(730, 1460))
        cert_status = "valid"
        if expiry_date < datetime(2025, 6, 1):
            cert_status = "expired"
        if random.random() < 0.05:
            cert_status = "revoked"
        parent_records.append({
            "cert_id": f"PCERT-{i+1:04d}",
            "parent_lot_id": f"PARENT-{i+1:04d}",
            "certification_body": random.choice(CERTIFICATION_BODIES),
            "issue_date": issue_date.strftime("%Y-%m-%d"),
            "expiry_date": expiry_date.strftime("%Y-%m-%d"),
            "generation": generation,
            "crop_type": crop,
            "variety": variety,
            "cert_status": cert_status,
        })
    parent_certs_df = pd.DataFrame(parent_records)

    # ---- Generate harvest logs ----
    harvest_records = []
    harvest_base = datetime(2025, 7, 1)
    for i in range(n_rows):
        crop = CROP_TYPES[i % len(CROP_TYPES)]
        harvest_date = harvest_base + timedelta(days=random.randint(0, 120))
        harvest_records.append({
            "log_id": f"HLOG-{i+1:04d}",
            "field_id": f"FIELD-{i+1:04d}",
            "crop_type": crop,
            "harvest_date": harvest_date.strftime("%Y-%m-%d"),
            "yield_kg": round(random.uniform(500, 5000), 1),
            "equipment_id": random.choice(EQUIPMENT_IDS),
            "operator_name": random.choice(OPERATOR_POOL),
            "notes": fake.sentence(nb_words=8),
        })
    harvest_logs_df = pd.DataFrame(harvest_records)

    # ---- Generate seed lots ----
    # Key: link each seed lot to a parent cert with MATCHING crop+variety for ~70% of lots
    # The remaining ~30% get random parent (may mismatch)
    seed_records = []
    for i in range(n_rows):
        crop = CROP_TYPES[i % len(CROP_TYPES)]

        # ~30% pending_review, ~50% certified, ~20% rejected
        r = random.random()
        if r < 0.30:
            status = "pending_review"
        elif r < 0.80:
            status = "certified"
        else:
            status = "rejected"

        # For pending_review lots, give ~60% a matching parent (so some can pass)
        # For others, random assignment
        matching_parents = parent_certs_df[
            (parent_certs_df["crop_type"] == crop) &
            (parent_certs_df["cert_status"] == "valid")
        ]
        if status == "pending_review" and random.random() < 0.60 and len(matching_parents) > 0:
            parent = matching_parents.sample(1, random_state=42 + i).iloc[0]
            parent_lot_id = parent["parent_lot_id"]
            variety = parent["variety"]  # Ensure match
        else:
            variety = random.choice(CROP_VARIETIES[crop])
            crop_parents = parent_certs_df[parent_certs_df["crop_type"] == crop]
            if len(crop_parents) > 0:
                parent = crop_parents.sample(1, random_state=42 + i).iloc[0]
                parent_lot_id = parent["parent_lot_id"]
            else:
                parent_lot_id = parent_certs_df.sample(1, random_state=42 + i).iloc[0]["parent_lot_id"]

        # Assign a field with matching crop type
        matching_fields = harvest_logs_df[harvest_logs_df["crop_type"] == crop]
        if len(matching_fields) > 0:
            field_row = matching_fields.sample(1, random_state=42 + i).iloc[0]
        else:
            field_row = harvest_logs_df.sample(1, random_state=42 + i).iloc[0]
        field_id = field_row["field_id"]
        harvest_date = field_row["harvest_date"]

        seed_records.append({
            "lot_id": f"LOT-{i+1:04d}",
            "crop_type": crop,
            "variety": variety,
            "parent_lot_id": parent_lot_id,
            "field_id": field_id,
            "harvest_date": harvest_date,
            "weight_kg": round(random.uniform(200, 3000), 1),
            "status": status,
        })
    seed_lots_df = pd.DataFrame(seed_records)

    # ---- Generate germination tests ----
    germ_records = []
    germ_base = datetime(2025, 9, 1)
    lot_ids = seed_lots_df["lot_id"].tolist()
    for i in range(n_rows):
        lot_id = lot_ids[i % len(lot_ids)]
        crop = seed_lots_df[seed_lots_df["lot_id"] == lot_id].iloc[0]["crop_type"]
        test_date = germ_base + timedelta(days=random.randint(0, 90))
        thresh = COMPLIANCE_THRESHOLDS[crop]

        # ~25% produce marginal/failing values, ~75% pass
        if random.random() < 0.25:
            germination_rate = round(random.uniform(65.0, thresh["min_germination_rate"] + 2), 1)
            purity_pct = round(random.uniform(94.0, thresh["min_purity_pct"] + 0.5), 1)
            moisture_pct = round(random.uniform(thresh["max_moisture_pct"] - 2, thresh["max_moisture_pct"] + 4), 1)
            weed_seed_count = random.randint(0, thresh["max_weed_seed_count"] + 4)
            other_crop_count = random.randint(0, thresh["max_other_crop_seed_count"] + 3)
            inert_matter_pct = round(random.uniform(0.5, thresh["max_inert_matter_pct"] + 2), 1)
        else:
            germination_rate = round(random.uniform(thresh["min_germination_rate"], 99.5), 1)
            purity_pct = round(random.uniform(thresh["min_purity_pct"], 99.9), 1)
            moisture_pct = round(random.uniform(6.0, thresh["max_moisture_pct"]), 1)
            weed_seed_count = random.randint(0, thresh["max_weed_seed_count"])
            other_crop_count = random.randint(0, thresh["max_other_crop_seed_count"])
            inert_matter_pct = round(random.uniform(0.1, thresh["max_inert_matter_pct"]), 1)

        germ_records.append({
            "test_id": f"GTEST-{i+1:04d}",
            "lot_id": lot_id,
            "test_date": test_date.strftime("%Y-%m-%d"),
            "germination_rate": germination_rate,
            "purity_pct": purity_pct,
            "moisture_pct": moisture_pct,
            "weed_seed_count": weed_seed_count,
            "other_crop_seed_count": other_crop_count,
            "inert_matter_pct": inert_matter_pct,
            "lab_name": random.choice(LAB_NAMES),
            "technician_name": random.choice(TECHNICIAN_POOL),
        })
    germ_tests_df = pd.DataFrame(germ_records)

    # ---- Generate inspection records ----
    insp_records = []
    insp_base = datetime(2025, 10, 1)
    for i in range(n_rows):
        lot_id = lot_ids[i % len(lot_ids)]
        inspection_date = insp_base + timedelta(days=random.randint(0, 60))
        field_passed = 1 if random.random() < 0.85 else 0
        lab_passed = 1 if random.random() < 0.88 else 0
        doc_complete = 1 if random.random() < 0.90 else 0
        if field_passed and lab_passed and doc_complete:
            overall = "passed"
        elif random.random() < 0.3:
            overall = "conditional"
        else:
            overall = "failed"
        insp_records.append({
            "inspection_id": f"INSP-{i+1:04d}",
            "lot_id": lot_id,
            "inspector_name": random.choice(INSPECTOR_POOL),
            "inspection_date": inspection_date.strftime("%Y-%m-%d"),
            "field_inspection_passed": field_passed,
            "lab_inspection_passed": lab_passed,
            "documentation_complete": doc_complete,
            "overall_result": overall,
            "notes": fake.sentence(nb_words=10),
        })
    inspections_df = pd.DataFrame(insp_records)

    # ---- Create database ----
    conn = sqlite3.connect(args.db_path)
    parent_certs_df.to_sql("parent_certificates", conn, if_exists="replace", index=False)
    harvest_logs_df.to_sql("harvest_logs", conn, if_exists="replace", index=False)
    seed_lots_df.to_sql("seed_lots", conn, if_exists="replace", index=False)
    germ_tests_df.to_sql("germination_tests", conn, if_exists="replace", index=False)
    inspections_df.to_sql("inspection_records", conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()

    # ---- Generate workspace files ----
    os.makedirs(args.workspace, exist_ok=True)

    # --- Fixed config files (not scaled) ---

    # 1. Compliance thresholds YAML
    with open(os.path.join(args.workspace, "compliance_thresholds.yaml"), "w") as f:
        yaml.dump({"crop_thresholds": COMPLIANCE_THRESHOLDS}, f,
                  default_flow_style=False, sort_keys=False)

    # 2. Traceability rules markdown
    rules_content = """# Seed Lot Traceability and Compliance Rules

## Parent Stock Validation

A seed lot's parent stock certificate must satisfy all of the following conditions
for the lot to be considered traceable:

1. The parent certificate status must be "valid" (not "expired" or "revoked").
2. The parent certificate expiry date must be on or after the seed lot's harvest date.
3. The parent certificate's crop type must match the seed lot's crop type.
4. The parent certificate's variety must match the seed lot's variety.
5. The parent generation must be one of the valid parent generations listed
   in the compliance thresholds for the lot's crop type.

## Germination and Purity Standards

When multiple germination tests exist for a single lot, use the result from
the most recent test date. The test values must meet ALL thresholds for the
lot's crop type as specified in the compliance thresholds configuration:

- Germination rate must be >= the minimum germination rate.
- Purity percentage must be >= the minimum purity percentage.
- Moisture percentage must be <= the maximum moisture percentage.
- Weed seed count must be <= the maximum weed seed count.
- Other crop seed count must be <= the maximum other crop seed count.
- Inert matter percentage must be <= the maximum inert matter percentage.

## Vigor Assessment

Each lot must have a vigor score recorded in the lab analysis reports.
The vigor score must meet or exceed the minimum vigor score threshold
for the lot's crop type. If no vigor score is found in the lab reports,
the lot fails this criterion.

## Field Condition Assessment

The field condition report for the lot's field must show acceptable harvest
conditions. Specifically:

- The maximum temperature recorded for the field on the harvest date must
  not exceed the crop's maximum harvest temperature threshold.
- The total rainfall recorded for the field on the harvest date must not
  exceed the crop's maximum harvest rainfall threshold.

If no field condition record is found for the lot's field, the lot fails
this criterion.

## Government Inspection

The government inspection record for the lot must have an overall_result
of "passed". Lots with "failed" or "conditional" results do not qualify
for certification. When multiple inspection records exist for a lot,
use the most recent inspection date.

## Compliance Certificate Generation

A lot receives a compliance certificate only if ALL of the above criteria
are satisfied. The certificate number follows the format:
    CERT-{lot_id}-{YYYYMMDD}
where lot_id is the numeric portion of the lot ID (e.g., "0015" from "LOT-0015")
and YYYYMMDD is the certification date (2025-12-01).

The certification date for all certificates in this batch is 2025-12-01.
"""
    with open(os.path.join(args.workspace, "traceability_rules.md"), "w") as f:
        f.write(rules_content)

    # --- Scalable data files ---
    # Distribution: 50% field condition CSVs, 30% lab report JSONs, 20% inspector note TXTs
    n_field_csv = max(1, int(n_files * 0.5))
    n_lab_json = max(1, int(n_files * 0.3))
    n_inspector_txt = max(1, n_files - n_field_csv - n_lab_json)

    # Field condition reports (CSV) - weather at harvest for each field
    all_field_ids = harvest_logs_df["field_id"].tolist()
    fields_per_file = max(1, len(all_field_ids) // n_field_csv)

    # Pre-determine which pending lots should have good field conditions
    pending_lots = seed_lots_df[seed_lots_df["status"] == "pending_review"]
    pending_field_ids = set(pending_lots["field_id"].tolist())

    for fidx in range(n_field_csv):
        start = fidx * fields_per_file
        end = start + fields_per_file if fidx < n_field_csv - 1 else len(all_field_ids)
        file_fields = all_field_ids[start:end]

        rows = []
        for fid in file_fields:
            harvest_row = harvest_logs_df[harvest_logs_df["field_id"] == fid].iloc[0]
            h_date = harvest_row["harvest_date"]
            crop = harvest_row["crop_type"]
            thresh = COMPLIANCE_THRESHOLDS[crop]

            # For pending lots' fields, ~70% get acceptable conditions
            if fid in pending_field_ids and random.random() < 0.70:
                temp = round(random.uniform(18.0, thresh["max_harvest_temperature_c"] - 1), 1)
                rainfall = round(random.uniform(0.0, thresh["max_harvest_rainfall_mm"] - 1), 1)
            else:
                temp = round(random.uniform(18.0, 42.0), 1)
                rainfall = round(random.uniform(0.0, 20.0), 1)

            humidity = round(random.uniform(30.0, 90.0), 1)
            soil_moisture = round(random.uniform(15.0, 60.0), 1)
            wind_speed = round(random.uniform(0.0, 35.0), 1)
            condition_rating = random.choice(["excellent", "good", "fair", "poor"])
            rows.append({
                "field_id": fid,
                "date": h_date,
                "temperature_c": temp,
                "humidity_pct": humidity,
                "rainfall_mm": rainfall,
                "soil_moisture_pct": soil_moisture,
                "wind_speed_kmh": wind_speed,
                "condition_rating": condition_rating,
            })
        df = pd.DataFrame(rows)
        df.to_csv(os.path.join(args.workspace, f"field_condition_report_{fidx+1:03d}.csv"),
                  index=False)

    # Lab analysis reports (JSON) - vigor scores for each lot
    all_lot_ids = seed_lots_df["lot_id"].tolist()
    lots_per_lab_file = max(1, len(all_lot_ids) // n_lab_json)
    pending_lot_ids = set(pending_lots["lot_id"].tolist())

    for lidx in range(n_lab_json):
        start = lidx * lots_per_lab_file
        end = start + lots_per_lab_file if lidx < n_lab_json - 1 else len(all_lot_ids)
        file_lots = all_lot_ids[start:end]

        lab_entries = []
        for lot_id in file_lots:
            crop = seed_lots_df[seed_lots_df["lot_id"] == lot_id].iloc[0]["crop_type"]
            thresh = COMPLIANCE_THRESHOLDS[crop]

            # For pending lots, ~70% get passing vigor scores
            if lot_id in pending_lot_ids and random.random() < 0.70:
                vigor = round(random.uniform(thresh["min_vigor_score"], 98.0), 1)
            else:
                vigor = round(random.uniform(50.0, 98.0), 1)

            lab_entries.append({
                "lot_id": lot_id,
                "vigor_score": vigor,
                "abnormal_seedlings_pct": round(random.uniform(0.0, 15.0), 1),
                "hard_seeds_pct": round(random.uniform(0.0, 8.0), 1),
                "dead_seeds_pct": round(random.uniform(0.0, 10.0), 1),
                "fresh_ungerminated_pct": round(random.uniform(0.0, 5.0), 1),
                "analysis_date": (datetime(2025, 10, 1) + timedelta(
                    days=random.randint(0, 45))).strftime("%Y-%m-%d"),
                "lab_name": random.choice(LAB_NAMES),
            })
        with open(os.path.join(args.workspace, f"lab_analysis_report_{lidx+1:03d}.json"), "w") as f:
            json.dump(lab_entries, f, indent=2)

    # Inspector field notes (TXT) - narrative notes from inspections
    all_inspections = inspections_df.to_dict("records")
    insps_per_file = max(1, len(all_inspections) // n_inspector_txt)
    for tidx in range(n_inspector_txt):
        start = tidx * insps_per_file
        end = start + insps_per_file if tidx < n_inspector_txt - 1 else len(all_inspections)
        file_insps = all_inspections[start:end]

        lines = []
        for rec in file_insps:
            lines.append(f"=== Inspection {rec['inspection_id']} ===")
            lines.append(f"Lot: {rec['lot_id']}")
            lines.append(f"Inspector: {rec['inspector_name']}")
            lines.append(f"Date: {rec['inspection_date']}")
            lines.append(f"Field Inspection: {'PASSED' if rec['field_inspection_passed'] else 'FAILED'}")
            lines.append(f"Lab Inspection: {'PASSED' if rec['lab_inspection_passed'] else 'FAILED'}")
            lines.append(f"Documentation: {'COMPLETE' if rec['documentation_complete'] else 'INCOMPLETE'}")
            lines.append(f"Overall: {rec['overall_result'].upper()}")
            lines.append(f"Notes: {rec['notes']}")
            lines.append("")
        with open(os.path.join(args.workspace, f"inspector_notes_{tidx+1:03d}.txt"), "w") as f:
            f.write("\n".join(lines))

    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")
    print(f"  - {n_rows} rows per table")
    print(f"  - {n_files} scalable workspace files + 2 fixed config files")


if __name__ == "__main__":
    main()
