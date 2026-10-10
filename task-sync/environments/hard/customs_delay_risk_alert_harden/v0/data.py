import os
import json
import math
import csv
import yaml
import sqlite3
import argparse
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 100,
    "num_workspace_files": 10,
}


def main(db_path, workspace):
    fake = Faker()
    Faker.seed(42)
    np.random.seed(42)

    os.makedirs(workspace, exist_ok=True)
    rows = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    # ── Create Tables ──────────────────────────────────────────────
    cur.executescript("""
        DROP TABLE IF EXISTS shipments;
        DROP TABLE IF EXISTS hs_codes;
        DROP TABLE IF EXISTS suppliers;
        DROP TABLE IF EXISTS carriers;
        DROP TABLE IF EXISTS ports;

        CREATE TABLE ports (
            port_id INTEGER PRIMARY KEY,
            port_name TEXT UNIQUE NOT NULL,
            country TEXT NOT NULL,
            region TEXT NOT NULL,
            congestion_index REAL NOT NULL,
            avg_wait_hours REAL NOT NULL,
            vessel_queue_size INTEGER NOT NULL,
            last_updated TEXT NOT NULL
        );

        CREATE TABLE carriers (
            carrier_id INTEGER PRIMARY KEY,
            carrier_name TEXT NOT NULL,
            country TEXT NOT NULL,
            fleet_size INTEGER NOT NULL,
            on_time_rate REAL NOT NULL,
            avg_transit_days REAL NOT NULL,
            license_number TEXT NOT NULL
        );

        CREATE TABLE suppliers (
            supplier_id INTEGER PRIMARY KEY,
            supplier_name TEXT NOT NULL,
            country TEXT NOT NULL,
            city TEXT NOT NULL,
            registration_date TEXT NOT NULL,
            product_category TEXT NOT NULL,
            contact_email TEXT NOT NULL
        );

        CREATE TABLE hs_codes (
            hs_code TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            base_inspection_rate REAL NOT NULL,
            avg_clearance_days REAL NOT NULL,
            restricted_flag INTEGER NOT NULL
        );

        CREATE TABLE shipments (
            shipment_id TEXT PRIMARY KEY,
            carrier_id INTEGER NOT NULL,
            supplier_id INTEGER NOT NULL,
            hs_code TEXT NOT NULL,
            origin_port_id INTEGER NOT NULL,
            dest_port_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            eta TEXT NOT NULL,
            departure_date TEXT NOT NULL,
            declared_value REAL NOT NULL,
            container_count INTEGER NOT NULL,
            weight_kg REAL NOT NULL,
            FOREIGN KEY (carrier_id) REFERENCES carriers(carrier_id),
            FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
            FOREIGN KEY (hs_code) REFERENCES hs_codes(hs_code),
            FOREIGN KEY (origin_port_id) REFERENCES ports(port_id),
            FOREIGN KEY (dest_port_id) REFERENCES ports(port_id)
        );
    """)

    # ── Generate Ports ─────────────────────────────────────────────
    regions = [
        "East Asia", "Southeast Asia", "South Asia", "Middle East",
        "Northern Europe", "Southern Europe", "West Africa", "East Africa",
        "North America", "South America", "Central America", "Oceania",
    ]

    well_known_ports = [
        ("Port of Shanghai", "China", "East Asia"),
        ("Port of Singapore", "Singapore", "Southeast Asia"),
        ("Port of Rotterdam", "Netherlands", "Northern Europe"),
        ("Port of Los Angeles", "United States", "North America"),
        ("Port of Hamburg", "Germany", "Northern Europe"),
        ("Port of Busan", "South Korea", "East Asia"),
        ("Port of Antwerp", "Belgium", "Northern Europe"),
        ("Port of Qingdao", "China", "East Asia"),
        ("Port of Dubai", "UAE", "Middle East"),
        ("Port of Ningbo", "China", "East Asia"),
        ("Port of Felixstowe", "United Kingdom", "Northern Europe"),
        ("Port of Yokohama", "Japan", "East Asia"),
        ("Port of Santos", "Brazil", "South America"),
        ("Port of Mumbai", "India", "South Asia"),
        ("Port of Colombo", "Sri Lanka", "South Asia"),
        ("Port of Piraeus", "Greece", "Southern Europe"),
        ("Port of Valencia", "Spain", "Southern Europe"),
        ("Port of Laem Chabang", "Thailand", "Southeast Asia"),
        ("Port of Kaohsiung", "Taiwan", "East Asia"),
        ("Port of Durban", "South Africa", "East Africa"),
    ]

    port_records = []
    used_port_names = set()

    for i, (name, country, region) in enumerate(
        well_known_ports[: min(len(well_known_ports), rows)]
    ):
        used_port_names.add(name)
        cong = round(float(np.random.beta(3, 5) * 100), 1)
        port_records.append(
            (
                i + 1,
                name,
                country,
                region,
                cong,
                round(float(np.random.uniform(2, 120)), 1),
                int(np.random.randint(0, 80)),
                fake.date_between(start_date="-7d", end_date="today").isoformat(),
            )
        )

    idx = len(port_records) + 1
    while len(port_records) < rows:
        city = fake.city()
        name = f"Port of {city}"
        if name in used_port_names:
            continue
        used_port_names.add(name)
        country = fake.country()
        region = str(np.random.choice(regions))
        cong = round(float(np.random.beta(3, 5) * 100), 1)
        port_records.append(
            (
                idx,
                name,
                country,
                region,
                cong,
                round(float(np.random.uniform(2, 120)), 1),
                int(np.random.randint(0, 80)),
                fake.date_between(start_date="-7d", end_date="today").isoformat(),
            )
        )
        idx += 1

    cur.executemany("INSERT INTO ports VALUES (?,?,?,?,?,?,?,?)", port_records)
    port_id_to_name = {r[0]: r[1] for r in port_records}

    # ── Generate Carriers ──────────────────────────────────────────
    carrier_suffixes = [
        "Shipping", "Lines", "Maritime", "Logistics", "Transport",
        "Freight", "Cargo", "Navigation", "Ocean Services", "Global Shipping",
    ]

    carrier_records = []
    used_carrier_names = set()
    for i in range(rows):
        while True:
            base = fake.company()
            suffix = carrier_suffixes[i % len(carrier_suffixes)]
            name = f"{base} {suffix}"
            if name not in used_carrier_names:
                break
        used_carrier_names.add(name)
        on_time = round(float(np.clip(np.random.beta(8, 2), 0.60, 0.99)), 4)
        carrier_records.append(
            (
                i + 1,
                name,
                fake.country(),
                int(np.random.randint(5, 500)),
                on_time,
                round(float(np.random.uniform(5, 45)), 1),
                fake.bothify("??-####-???").upper(),
            )
        )

    cur.executemany("INSERT INTO carriers VALUES (?,?,?,?,?,?,?)", carrier_records)

    # ── Generate Suppliers ─────────────────────────────────────────
    product_categories = [
        "Electronics", "Textiles", "Chemicals", "Food & Beverage", "Machinery",
        "Pharmaceuticals", "Automotive", "Raw Materials", "Consumer Goods", "Agriculture",
    ]

    supplier_records = []
    for i in range(rows):
        supplier_records.append(
            (
                i + 1,
                fake.company(),
                fake.country(),
                fake.city(),
                fake.date_between(start_date="-10y", end_date="-6m").isoformat(),
                str(np.random.choice(product_categories)),
                fake.company_email(),
            )
        )

    cur.executemany("INSERT INTO suppliers VALUES (?,?,?,?,?,?,?)", supplier_records)

    # ── Generate HS Codes ──────────────────────────────────────────
    hs_categories = [
        "Electronics", "Textiles", "Chemicals", "Food Products", "Machinery",
        "Pharmaceuticals", "Automotive Parts", "Raw Materials",
        "Consumer Goods", "Agricultural Products",
    ]

    hs_code_set = set()
    while len(hs_code_set) < rows:
        chapter = int(np.random.randint(1, 98))
        heading = int(np.random.randint(1, 100))
        code = f"{chapter:02d}{heading:04d}"
        hs_code_set.add(code)

    hs_code_list = sorted(hs_code_set)
    hs_records = []
    for code in hs_code_list:
        rate = round(float(np.clip(np.random.beta(2, 8), 0.02, 0.85)), 4)
        hs_records.append(
            (
                code,
                fake.bs().title(),
                str(np.random.choice(hs_categories)),
                rate,
                round(float(np.random.uniform(0.5, 10)), 1),
                int(np.random.random() < 0.15),
            )
        )

    cur.executemany("INSERT INTO hs_codes VALUES (?,?,?,?,?,?)", hs_records)

    # ── Generate Shipments ─────────────────────────────────────────
    statuses = ["in_transit", "at_port", "pending_clearance", "cleared", "delivered"]
    status_weights = [0.30, 0.20, 0.15, 0.20, 0.15]

    num_active_carriers = max(15, min(rows // 5, 50))
    num_active_dest_ports = max(15, min(rows // 5, 50))
    num_active_origin_ports = max(12, min(rows // 5, 40))
    num_active_hs = max(20, min(rows // 4, 60))
    num_active_suppliers = max(20, min(rows // 4, 60))

    active_carrier_ids = np.random.choice(
        range(1, rows + 1), size=num_active_carriers, replace=False
    ).tolist()
    active_dest_port_ids = np.random.choice(
        range(1, rows + 1), size=num_active_dest_ports, replace=False
    ).tolist()
    active_origin_port_ids = np.random.choice(
        range(1, rows + 1), size=num_active_origin_ports, replace=False
    ).tolist()
    active_hs_codes = np.random.choice(
        hs_code_list, size=num_active_hs, replace=False
    ).tolist()
    active_supplier_ids = np.random.choice(
        range(1, rows + 1), size=num_active_suppliers, replace=False
    ).tolist()

    shipment_records = []
    for i in range(rows):
        sid = f"SHP-{i + 1:04d}"
        status = str(np.random.choice(statuses, p=status_weights))
        carrier_id = int(np.random.choice(active_carrier_ids))
        supplier_id = int(np.random.choice(active_supplier_ids))
        hs_code = str(np.random.choice(active_hs_codes))
        origin_port_id = int(np.random.choice(active_origin_port_ids))
        dest_port_id = int(np.random.choice(active_dest_port_ids))
        while dest_port_id == origin_port_id:
            dest_port_id = int(np.random.choice(active_dest_port_ids))

        eta = fake.date_between(start_date="-2d", end_date="+30d").isoformat()
        departure = fake.date_between(start_date="-45d", end_date="-5d").isoformat()
        declared_value = round(float(np.random.lognormal(10, 1.5)), 2)
        containers = int(np.random.randint(1, 20))
        weight = round(float(np.random.lognormal(9, 1)), 2)

        shipment_records.append(
            (
                sid, carrier_id, supplier_id, hs_code,
                origin_port_id, dest_port_id, status,
                eta, departure, declared_value, containers, weight,
            )
        )

    cur.executemany(
        "INSERT INTO shipments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", shipment_records
    )
    conn.commit()

    # ── Fixed workspace files ──────────────────────────────────────

    # risk_scoring_config.yaml
    config = {
        "weights": {
            "port_congestion": 0.30,
            "hs_inspection": 0.25,
            "supplier_compliance": 0.25,
            "carrier_reliability": 0.20,
        },
        "alert_threshold": 60,
        "priority_levels": {"URGENT": 75, "HIGH": 60},
        "risk_levels": {"CRITICAL": 75, "HIGH": 60},
        "supplier_tier_scoring": {
            "tier_1": 10,
            "tier_2": 30,
            "tier_3": 60,
            "tier_4": 90,
            "unrated": 80,
        },
        "carrier_on_time_brackets": [
            {"upper_bound": 0.85, "score": 90},
            {"upper_bound": 0.92, "score": 60},
            {"upper_bound": 0.97, "score": 30},
            {"upper_bound": 1.00, "score": 10},
        ],
        "special_handling_risk": {
            "hazmat": 20,
            "oversized": 10,
            "temperature_controlled": 10,
            "fragile": 5,
            "none": 0,
        },
        "documentation_incomplete_penalty": 15,
        "violation_threshold": 3,
        "violation_penalty": 15,
        "audit_penalties": {
            "failed": 25,
            "conditional": 10,
            "pending": 15,
            "passed": 0,
        },
        "recommended_actions": {
            "port_congestion": "Reroute shipment or arrange pre-clearance with destination customs",
            "hs_inspection": "Prepare supplementary HS classification documentation and lab reports",
            "supplier_compliance": "Request updated compliance certificates from supplier",
            "carrier_reliability": "Arrange backup carrier or expedited handling at destination",
        },
    }

    with open(os.path.join(workspace, "risk_scoring_config.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # inspection_override_rules.json
    num_overrides = max(5, rows // 7)
    override_codes = np.random.choice(
        hs_code_list, size=min(num_overrides, len(hs_code_list)), replace=False
    ).tolist()
    override_reasons = [
        "High-value goods requiring additional scrutiny",
        "Controlled substance precursor",
        "Dual-use technology component",
        "Recently flagged category",
        "Trade restriction watchlist item",
        "Counterfeit-prone product category",
        "Sanction-adjacent commodity",
    ]
    overrides_list = []
    for code in override_codes:
        bonus = int(np.random.choice([10, 15, 20, 25]))
        reason = str(np.random.choice(override_reasons))
        overrides_list.append({"hs_code": code, "bonus": bonus, "reason": reason})

    with open(os.path.join(workspace, "inspection_override_rules.json"), "w") as f:
        json.dump({"overrides": overrides_list}, f, indent=2)

    # risk_methodology.md (fixed policy document)
    methodology = """# Customs Delay Risk Scoring Methodology

This document is the authoritative specification for the customs delay risk
assessment. All numeric parameters it refers to (weights, thresholds, bracket
tables, tier mappings, penalty and bonus values, recommended actions) are
defined in the risk scoring configuration and the companion policy files
stored alongside it.

## Assessment scope

The assessment covers every shipment that has not yet completed customs
clearance, i.e. shipments whose status is `in_transit`, `at_port`, or
`pending_clearance`.

## Risk dimensions

Four risk dimensions feed the composite score. Each dimension's raw score is
capped at 100 before weighting.

1. **Port congestion** — the destination port's congestion index, plus the
   additional delay factor from any active port advisory affecting that
   destination port.
2. **HS code inspection** — the commodity's base inspection rate multiplied
   by 100, plus the override bonus if the HS code appears in the inspection
   override rules.
3. **Supplier compliance** — the score mapped to the supplier's compliance
   tier, plus the configured violation penalty if the supplier's violation
   count exceeds the violation threshold, plus the audit penalty
   corresponding to the supplier's latest audit status. Suppliers without a
   compliance record are treated as `unrated` with an audit status of
   `pending` and zero violations.
4. **Carrier reliability** — the score for the carrier's on-time rate, taken
   from the first bracket (in the order listed in the configuration) whose
   upper bound is greater than or equal to that rate, plus the risk points
   for the shipment's special handling code from its carrier manifest, plus
   the documentation incomplete penalty when the manifest marks the
   shipment's documentation as not complete. Shipments without a manifest
   entry are treated as special handling `none` with complete documentation.

## Composite score

The composite score is the sum over the four dimensions of each dimension's
raw score multiplied by its configured weight, plus the trade lane risk bonus
if the shipment's origin-to-destination corridor appears in the trade lane
risk assessments. The composite is capped at 100 and rounded to exactly two
decimal places.

## Alerting and classification

A shipment is high risk when its composite score is greater than or equal to
the alert threshold. Risk level is `CRITICAL` when the composite is at or
above the CRITICAL risk-level threshold, otherwise `HIGH`. Broker priority is
`URGENT` when the composite is at or above the URGENT priority threshold,
otherwise `HIGH`.

The primary risk factor of a high-risk shipment is the dimension whose
weighted contribution to the composite is greatest. When two or more
dimensions tie for the greatest weighted contribution, select the one
appearing earliest in this sequence: port congestion, HS code inspection,
supplier compliance, carrier reliability. The recommended action is the
configured action mapped to the primary risk factor.

## Broker dispatch policy

Every shipment classified as high risk must have a broker dispatch filed
against it through the dispatch system, carrying that shipment's broker
priority (`URGENT` or `HIGH`).
"""
    with open(os.path.join(workspace, "risk_methodology.md"), "w") as f:
        f.write(methodology)

    # ── Scalable workspace files ───────────────────────────────────

    num_supplier_files = max(1, round(num_files * 0.4))
    num_manifest_files = max(1, round(num_files * 0.3))
    num_advisory_files = max(1, round(num_files * 0.2))
    num_trade_lane_files = max(
        1, num_files - num_supplier_files - num_manifest_files - num_advisory_files
    )

    # Supplier compliance reports (.json)
    compliance_tiers = ["tier_1", "tier_2", "tier_3", "tier_4", "unrated"]
    tier_probs = [0.25, 0.30, 0.25, 0.12, 0.08]
    audit_statuses_list = ["passed", "conditional", "failed", "pending"]
    audit_probs = [0.40, 0.25, 0.15, 0.20]

    supplier_compliance_data = []
    for i in range(rows):
        tier = str(np.random.choice(compliance_tiers, p=tier_probs))
        violations = int(np.random.poisson(1.5))
        audit_status = str(np.random.choice(audit_statuses_list, p=audit_probs))
        supplier_compliance_data.append(
            {
                "supplier_id": i + 1,
                "compliance_tier": tier,
                "violation_count": violations,
                "audit_status": audit_status,
                "last_audit_date": fake.date_between(
                    start_date="-2y", end_date="-1m"
                ).isoformat(),
            }
        )

    for fi in range(num_supplier_files):
        batch = [
            d for j, d in enumerate(supplier_compliance_data)
            if j % num_supplier_files == fi
        ]
        fname = f"supplier_compliance_{fi + 1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(batch, f, indent=2)

    # Carrier manifest files (.csv)
    special_handling_codes = [
        "none", "fragile", "hazmat", "temperature_controlled", "oversized",
    ]
    handling_probs = [0.55, 0.15, 0.10, 0.12, 0.08]

    manifest_data_list = []
    for rec in shipment_records:
        sid = rec[0]
        handling = str(np.random.choice(special_handling_codes, p=handling_probs))
        doc_complete = "yes" if float(np.random.random()) < 0.75 else "no"
        manifest_data_list.append(
            {
                "shipment_id": sid,
                "special_handling_code": handling,
                "documentation_complete": doc_complete,
            }
        )

    for fi in range(num_manifest_files):
        batch = [
            d for j, d in enumerate(manifest_data_list)
            if j % num_manifest_files == fi
        ]
        fname = f"carrier_manifest_{fi + 1:03d}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "shipment_id", "special_handling_code", "documentation_complete",
                ],
            )
            writer.writeheader()
            writer.writerows(batch)

    # Port advisory bulletins (.md)
    disruption_types = [
        "Labor Strike", "Weather Event", "Equipment Failure",
        "Security Alert", "Capacity Overflow", "Regulatory Change",
    ]
    severities = ["Low", "Moderate", "High", "Critical"]

    num_disrupted = max(5, rows // 4)
    disrupted_port_ids = np.random.choice(
        range(1, rows + 1), size=min(num_disrupted, rows), replace=False
    ).tolist()

    disruption_entries = []
    for pid in disrupted_port_ids:
        port_name = port_id_to_name[pid]
        disruption = str(np.random.choice(disruption_types))
        severity = str(np.random.choice(severities, p=[0.20, 0.30, 0.35, 0.15]))
        delay_factor = int(np.random.choice([5, 8, 10, 12, 15, 18, 20, 25, 30]))
        disruption_entries.append(
            {
                "port_name": port_name,
                "disruption_type": disruption,
                "severity": severity,
                "additional_delay_factor": delay_factor,
                "effective_date": fake.date_between(
                    start_date="-14d", end_date="today"
                ).isoformat(),
                "notes": fake.sentence(nb_words=10),
            }
        )

    for fi in range(num_advisory_files):
        batch = [
            d for j, d in enumerate(disruption_entries) if j % num_advisory_files == fi
        ]
        fname = f"port_advisory_{fi + 1:03d}.md"
        with open(os.path.join(workspace, fname), "w") as f:
            f.write(f"# Port Advisory Bulletin #{fi + 1}\n\n")
            for entry in batch:
                f.write(f"## {entry['port_name']}\n")
                f.write(f"- Disruption Type: {entry['disruption_type']}\n")
                f.write(f"- Severity: {entry['severity']}\n")
                f.write(
                    f"- Additional Delay Factor: {entry['additional_delay_factor']}\n"
                )
                f.write(f"- Effective Date: {entry['effective_date']}\n")
                f.write(f"- Notes: {entry['notes']}\n\n")

    # Trade lane risk assessments (.yaml)
    num_trade_lanes = max(8, rows // 5)
    trade_lane_entries = []
    used_lanes = set()
    attempts = 0
    while len(trade_lane_entries) < num_trade_lanes and attempts < num_trade_lanes * 10:
        attempts += 1
        origin_id = int(np.random.choice(active_origin_port_ids))
        dest_id = int(np.random.choice(active_dest_port_ids))
        if origin_id == dest_id:
            continue
        origin_name = port_id_to_name[origin_id]
        dest_name = port_id_to_name[dest_id]
        lane_key = (origin_name, dest_name)
        if lane_key in used_lanes:
            continue
        used_lanes.add(lane_key)
        bonus = int(np.random.choice([3, 5, 7, 8, 10, 12, 15]))
        trade_lane_entries.append(
            {
                "origin": origin_name,
                "destination": dest_name,
                "risk_bonus": bonus,
                "reason": fake.sentence(nb_words=8),
            }
        )

    for fi in range(num_trade_lane_files):
        batch = [
            d for j, d in enumerate(trade_lane_entries)
            if j % num_trade_lane_files == fi
        ]
        fname = f"trade_lane_risk_{fi + 1:03d}.yaml"
        with open(os.path.join(workspace, fname), "w") as f:
            yaml.dump(
                {"trade_lanes": batch}, f, default_flow_style=False, sort_keys=False
            )

    conn.close()
    print(f"Database written to {db_path}")
    print(f"Workspace files written to {workspace}/")
    print(f"  - {num_supplier_files} supplier compliance reports (.json)")
    print(f"  - {num_manifest_files} carrier manifest files (.csv)")
    print(f"  - {num_advisory_files} port advisory bulletins (.md)")
    print(f"  - {num_trade_lane_files} trade lane risk assessments (.yaml)")
    print(f"  - 3 fixed policy/config files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
