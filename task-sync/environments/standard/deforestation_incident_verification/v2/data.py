import argparse
import json
import os
import random
import sqlite3
import numpy as np
import pandas as pd
from faker import Faker
import yaml
from datetime import date

SCALE = {
    "rows_per_table": 320,
    "num_workspace_files": 30,
}

# --------------- constants ---------------
REGIONS = ["Norte", "Sur", "Este", "Oeste", "Central", "Amazonia", "Sierra", "Costa"]
LAND_TYPES = ["tropical_forest", "mangrove", "savanna", "cloud_forest", "dry_forest", "wetland"]
CHANGE_TYPES_ALL = [
    "deforestation", "land_clearing", "regrowth",
    "construction", "agriculture_expansion", "natural_event",
]
SENSOR_TYPES = ["Landsat-8", "Sentinel-2", "MODIS", "VIIRS", "Planet-Scope"]
OWNER_TYPES = ["individual", "corporate", "government", "community", "trust"]
HABITAT_TYPES = [
    "primary_rainforest", "secondary_growth", "mangrove_estuary",
    "cloud_forest", "dry_deciduous", "riparian_corridor",
]
CONSERVATION_PRIORITIES = ["low", "medium", "high", "critical"]
TREE_SPECIES = ["Teak", "Mahogany", "Cedar", "Pine", "Eucalyptus", "Balsa"]
ALL_ANIMAL_SPECIES = [
    "Jaguar", "Harpy Eagle", "Giant Otter", "Tapir", "Spectacled Bear",
    "Poison Dart Frog", "Howler Monkey", "Macaw", "Toucan", "Anaconda",
    "Capybara", "Sloth", "Ocelot", "Puma", "Caiman",
    "Tree Frog", "Iguana", "Piranha", "River Dolphin", "Manatee",
    "Spider Monkey", "Tamarin", "Quetzal", "Condor", "Armadillo",
]
PROTECTED_SPECIES = [
    {"species_name": "Jaguar", "iucn_status": "Near Threatened", "protection_level": "full"},
    {"species_name": "Harpy Eagle", "iucn_status": "Vulnerable", "protection_level": "full"},
    {"species_name": "Giant Otter", "iucn_status": "Endangered", "protection_level": "full"},
    {"species_name": "Spectacled Bear", "iucn_status": "Vulnerable", "protection_level": "full"},
    {"species_name": "River Dolphin", "iucn_status": "Endangered", "protection_level": "full"},
    {"species_name": "Manatee", "iucn_status": "Vulnerable", "protection_level": "full"},
    {"species_name": "Condor", "iucn_status": "Vulnerable", "protection_level": "full"},
    {"species_name": "Quetzal", "iucn_status": "Near Threatened", "protection_level": "partial"},
    {"species_name": "Tamarin", "iucn_status": "Endangered", "protection_level": "full"},
    {"species_name": "Spider Monkey", "iucn_status": "Critically Endangered", "protection_level": "full"},
]


def main(db_path: str, workspace: str):
    # ---- deterministic seeds ----
    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    fake = Faker()

    os.makedirs(workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # ================================================================
    # TABLE 1: parcels
    # ================================================================
    parcels = []
    for i in range(n_rows):
        parcels.append({
            "parcel_id": f"P-{i+1:04d}",
            "region": random.choice(REGIONS),
            "area_hectares": round(random.uniform(10, 500), 2),
            "land_type": random.choice(LAND_TYPES),
            "latitude": round(random.uniform(-15, 5), 6),
            "longitude": round(random.uniform(-80, -45), 6),
        })
    parcels_df = pd.DataFrame(parcels)
    parcel_ids = [p["parcel_id"] for p in parcels]

    # ================================================================
    # TABLE 2: satellite_changes
    # ================================================================
    changes = []
    for i in range(n_rows):
        pid = random.choice(parcel_ids)
        det_date = fake.date_between(start_date=date(2022, 1, 1), end_date=date(2025, 12, 31))
        if random.random() < 0.35:
            ctype = random.choice(["deforestation", "land_clearing"])
        else:
            ctype = random.choice(CHANGE_TYPES_ALL)
        changes.append({
            "change_id": f"SC-{i+1:05d}",
            "parcel_id": pid,
            "detection_date": det_date.isoformat(),
            "change_type": ctype,
            "affected_area_hectares": round(random.uniform(0.5, 50), 2),
            "confidence_score": round(random.uniform(0.3, 1.0), 2),
            "sensor_type": random.choice(SENSOR_TYPES),
        })
    changes_df = pd.DataFrame(changes)

    # ================================================================
    # TABLE 3: land_ownership  (one current row per parcel; extras historical)
    # ================================================================
    ownerships = []
    for i, pid in enumerate(parcel_ids):
        ownerships.append({
            "ownership_id": f"OWN-{i+1:04d}",
            "parcel_id": pid,
            "owner_name": fake.company() if random.random() > 0.5 else fake.name(),
            "owner_type": random.choice(OWNER_TYPES),
            "registration_date": fake.date_between(
                start_date=date(2010, 1, 1), end_date=date(2023, 12, 31)
            ).isoformat(),
            "contact_email": fake.email(),
            "is_current": 1,
        })
    oid = len(parcel_ids)
    while len(ownerships) < n_rows:
        oid += 1
        pid = random.choice(parcel_ids)
        ownerships.append({
            "ownership_id": f"OWN-{oid:04d}",
            "parcel_id": pid,
            "owner_name": fake.name(),
            "owner_type": random.choice(OWNER_TYPES),
            "registration_date": fake.date_between(
                start_date=date(2005, 1, 1), end_date=date(2009, 12, 31)
            ).isoformat(),
            "contact_email": fake.email(),
            "is_current": 0,
        })
    ownership_df = pd.DataFrame(ownerships[:n_rows])

    # ================================================================
    # TABLE 4: logging_concessions  (~50 % of parcels get at least one)
    # ================================================================
    n_conc_parcels = max(1, n_rows // 2)
    concession_parcels = random.sample(parcel_ids, k=min(len(parcel_ids), n_conc_parcels))
    concessions = []
    cid = 0
    for pid in concession_parcels:
        cid += 1
        granted = fake.date_between(start_date=date(2020, 1, 1), end_date=date(2024, 6, 30))
        r = random.random()
        if r < 0.30:
            expiry = fake.date_between(start_date=date(2024, 1, 1), end_date=date(2025, 6, 30))
            status = "expired"
        elif r < 0.40:
            expiry = fake.date_between(start_date=date(2025, 7, 1), end_date=date(2028, 12, 31))
            status = "suspended"
        else:
            expiry = fake.date_between(start_date=date(2025, 7, 1), end_date=date(2028, 12, 31))
            status = "active"
        concessions.append({
            "concession_id": f"CON-{cid:04d}",
            "parcel_id": pid,
            "permit_number": f"PMT-{random.randint(10000, 99999)}",
            "granted_date": granted.isoformat(),
            "expiry_date": expiry.isoformat(),
            "permitted_hectares": round(random.uniform(5, 30), 2),
            "permitted_species": ", ".join(random.sample(TREE_SPECIES, k=random.randint(1, 3))),
            "status": status,
        })
    while len(concessions) < n_rows:
        cid += 1
        pid = random.choice(parcel_ids)
        granted = fake.date_between(start_date=date(2015, 1, 1), end_date=date(2019, 12, 31))
        expiry = fake.date_between(start_date=date(2019, 1, 1), end_date=date(2023, 12, 31))
        concessions.append({
            "concession_id": f"CON-{cid:04d}",
            "parcel_id": pid,
            "permit_number": f"PMT-{random.randint(10000, 99999)}",
            "granted_date": granted.isoformat(),
            "expiry_date": expiry.isoformat(),
            "permitted_hectares": round(random.uniform(5, 30), 2),
            "permitted_species": ", ".join(random.sample(TREE_SPECIES, k=random.randint(1, 3))),
            "status": "expired",
        })
    concessions_df = pd.DataFrame(concessions[:n_rows])

    # ================================================================
    # TABLE 5: conservation_reports
    # ================================================================
    reports = []
    for i in range(n_rows):
        reports.append({
            "report_id": f"CR-{i+1:05d}",
            "parcel_id": random.choice(parcel_ids),
            "report_date": fake.date_between(
                start_date=date(2020, 1, 1), end_date=date(2025, 12, 31)
            ).isoformat(),
            "habitat_type": random.choice(HABITAT_TYPES),
            "biodiversity_index": round(random.uniform(0.1, 1.0), 3),
            "conservation_priority": random.choice(CONSERVATION_PRIORITIES),
            "inspector_name": fake.name(),
        })
    reports_df = pd.DataFrame(reports)

    # ================================================================
    # Write DB
    # ================================================================
    conn = sqlite3.connect(db_path)
    parcels_df.to_sql("parcels", conn, if_exists="replace", index=False)
    changes_df.to_sql("satellite_changes", conn, if_exists="replace", index=False)
    ownership_df.to_sql("land_ownership", conn, if_exists="replace", index=False)
    concessions_df.to_sql("logging_concessions", conn, if_exists="replace", index=False)
    reports_df.to_sql("conservation_reports", conn, if_exists="replace", index=False)
    conn.close()

    # ================================================================
    # FIXED workspace files  (not counted in SCALE)
    # ================================================================

    # 1. deforestation_policy.yaml
    policy = {
        "confidence_threshold": 0.75,
        "change_types_of_interest": ["deforestation", "land_clearing"],
        "area_tolerance_pct": 10,
        "min_conservation_priority_for_critical": "high",
        "min_biodiversity_index_for_critical": 0.6,
        "severity_ranking": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
        "violation_rules": {
            "no_permit": {
                "description": "No logging concession has ever been issued for the parcel",
                "severity": "HIGH",
            },
            "expired_permit": {
                "description": "Concession(s) exist but none are valid at the detection date",
                "severity": "LOW",
            },
            "area_exceeded": {
                "description": "Affected area exceeds permitted hectares beyond tolerance",
                "severity": "MEDIUM",
            },
            "conservation_violation": {
                "description": "Parcel in high-priority conservation area with protected species",
                "severity": "CRITICAL",
            },
        },
    }
    with open(os.path.join(workspace, "deforestation_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # 2. protected_species_list.json
    with open(os.path.join(workspace, "protected_species_list.json"), "w") as f:
        json.dump(PROTECTED_SPECIES, f, indent=2)

    # 3. severity_matrix.csv
    severity_rows = [
        {"severity_tier": "CRITICAL", "priority_order": 1,
         "recommended_action": "immediate_enforcement", "response_deadline_days": 7},
        {"severity_tier": "HIGH", "priority_order": 2,
         "recommended_action": "investigation_and_penalty", "response_deadline_days": 14},
        {"severity_tier": "MEDIUM", "priority_order": 3,
         "recommended_action": "compliance_review", "response_deadline_days": 30},
        {"severity_tier": "LOW", "priority_order": 4,
         "recommended_action": "warning_notice", "response_deadline_days": 60},
    ]
    pd.DataFrame(severity_rows).to_csv(
        os.path.join(workspace, "severity_matrix.csv"), index=False
    )

    # ================================================================
    # SCALABLE workspace files
    # ================================================================
    n_field_inspections = n_files // 2
    n_species_surveys = n_files - n_field_inspections

    # ---- field inspection JSONs ----
    deforestation_changes = [c for c in changes if c["change_type"] in ("deforestation", "land_clearing")]
    other_changes = [c for c in changes if c["change_type"] not in ("deforestation", "land_clearing")]
    random.shuffle(deforestation_changes)
    random.shuffle(other_changes)

    inspected_deforestation = deforestation_changes[:max(1, int(len(deforestation_changes) * 0.70))]
    inspected_other = other_changes[:max(1, int(len(other_changes) * 0.20))]
    all_inspected = inspected_deforestation + inspected_other
    random.shuffle(all_inspected)

    chunk_size = max(1, len(all_inspected) // n_field_inspections)
    for fi in range(n_field_inspections):
        start = fi * chunk_size
        chunk = all_inspected[start:] if fi == n_field_inspections - 1 else all_inspected[start:start + chunk_size]
        inspections = []
        for c in chunk:
            if c["change_type"] in ("deforestation", "land_clearing"):
                if c["confidence_score"] >= 0.75:
                    status = random.choices(["confirmed", "false_positive"], weights=[0.85, 0.15])[0]
                else:
                    status = random.choices(
                        ["confirmed", "false_positive", "inconclusive"], weights=[0.4, 0.3, 0.3]
                    )[0]
            else:
                status = random.choices(
                    ["confirmed", "false_positive", "inconclusive"], weights=[0.5, 0.3, 0.2]
                )[0]
            inspections.append({
                "change_id": c["change_id"],
                "parcel_id": c["parcel_id"],
                "inspection_date": fake.date_between(
                    start_date=date(2023, 1, 1), end_date=date(2025, 12, 31)
                ).isoformat(),
                "inspector_name": fake.name(),
                "verification_status": status,
                "notes": fake.sentence(nb_words=12),
            })
        with open(os.path.join(workspace, f"field_inspection_{fi+1:03d}.json"), "w") as f:
            json.dump(inspections, f, indent=2)

    # ---- species survey CSVs ----
    shuffled_parcels = list(parcel_ids)
    random.shuffle(shuffled_parcels)
    parcels_per_survey = max(1, len(shuffled_parcels) // n_species_surveys)

    for si in range(n_species_surveys):
        start = si * parcels_per_survey
        survey_parcels = (
            shuffled_parcels[start:]
            if si == n_species_surveys - 1
            else shuffled_parcels[start:start + parcels_per_survey]
        )
        records = []
        for pid in survey_parcels:
            n_sp = random.randint(2, 8)
            observed = random.sample(ALL_ANIMAL_SPECIES, k=n_sp)
            for sp in observed:
                records.append({
                    "parcel_id": pid,
                    "species_name": sp,
                    "observation_date": fake.date_between(
                        start_date=date(2022, 1, 1), end_date=date(2025, 12, 31)
                    ).isoformat(),
                    "count": random.randint(1, 20),
                    "survey_method": random.choice(
                        ["camera_trap", "transect", "point_count", "acoustic"]
                    ),
                })
        pd.DataFrame(records).to_csv(
            os.path.join(workspace, f"species_survey_{si+1:03d}.csv"), index=False
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
