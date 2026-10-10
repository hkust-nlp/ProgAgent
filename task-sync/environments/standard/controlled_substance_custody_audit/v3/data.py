"""
Data generation for Controlled Substance Chain-of-Custody Reconciliation.
Generates SQLite database and workspace files for shipment audit scenarios.
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

# ── Scale parameters (v0 base) ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 400,       # v3 = 8x base
    "num_workspace_files": 40,   # v3 = base + 3N (N=10)
}

# ── Constants ────────────────────────────────────────────────────────────────
SUBSTANCES = {
    "II": [("Oxycodone", "tablets"), ("Fentanyl", "mg"), ("Morphine Sulfate", "mL"),
           ("Methadone", "tablets"), ("Hydromorphone", "mg")],
    "III": [("Ketamine", "mL"), ("Testosterone Cypionate", "mL"),
            ("Buprenorphine", "mg"), ("Anabolic Compound", "tablets")],
    "IV": [("Diazepam", "tablets"), ("Alprazolam", "tablets"),
           ("Zolpidem", "tablets"), ("Tramadol", "tablets")],
    "V":  [("Pregabalin", "tablets"), ("Codeine Preparation", "mL"),
           ("Lacosamide", "tablets")],
}
ALL_SCHEDULES = ["II", "III", "IV", "V"]
FACILITY_TYPES = ["manufacturer", "distributor", "pharmacy", "hospital", "research_lab"]
ROUTE_TYPES = ["SHORT", "STANDARD", "EXTENDED"]
CHECKPOINT_MAP = {
    "SHORT":    ["ORIGIN", "DESTINATION"],
    "STANDARD": ["ORIGIN", "TRANSIT_A", "DESTINATION"],
    "EXTENDED": ["ORIGIN", "TRANSIT_A", "TRANSIT_B", "DESTINATION"],
}
STATES = ["CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "MI",
          "NJ", "VA", "WA", "AZ", "MA", "TN", "IN", "MO", "MD", "WI"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # Deterministic seeds
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(args.workspace, exist_ok=True)

    n = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]
    base_date = datetime(2025, 3, 1)  # reference date for the dataset

    # ── 1. Generate Facilities ───────────────────────────────────────────────
    facilities = []
    for i in range(n):
        ftype = FACILITY_TYPES[i % len(FACILITY_TYPES)]
        state = STATES[i % len(STATES)]
        company = fake.company()
        suffix_map = {"manufacturer": "Manufacturing", "distributor": "Distribution",
                      "pharmacy": "Pharmacy", "hospital": "Hospital",
                      "research_lab": "Research Lab"}
        name = f"{company} {suffix_map[ftype]}"
        dea_letter = chr(65 + (i % 26))
        dea_num = f"A{dea_letter}{random.randint(1000000, 9999999)}"
        lic_num = f"LIC-{state}-{random.randint(100000, 999999)}"

        # Default: active, future expiry, all schedules
        status = "active"
        exp_date = base_date + timedelta(days=random.randint(180, 730))
        authorized = list(ALL_SCHEDULES)

        # Deterministic anomaly injection
        if i % 10 == 2:      # expired license
            exp_date = base_date - timedelta(days=random.randint(30, 365))
            status = "expired"
        elif i % 10 == 7:    # suspended license
            status = "suspended"
        if i % 15 == 4:      # not authorized for Schedule II
            authorized = [s for s in authorized if s != "II"]
        elif i % 15 == 9:    # not authorized for Schedule II or III
            authorized = [s for s in authorized if s not in ("II", "III")]

        facilities.append({
            "facility_id": f"FAC-{i+1:04d}",
            "facility_name": name,
            "facility_type": ftype,
            "state": state,
            "dea_number": dea_num,
            "license_number": lic_num,
            "license_expiry_date": exp_date.strftime("%Y-%m-%d"),
            "license_status": status,
            "schedules_authorized": ",".join(sorted(authorized)),
        })

    # ── 2. Generate Carriers ─────────────────────────────────────────────────
    carriers = []
    for i in range(n):
        cname = f"{fake.last_name()} {random.choice(['Logistics', 'Transport', 'Freight', 'Express', 'Carriers'])}"
        dot = f"DOT-{random.randint(100000, 999999)}"

        # Defaults: compliant
        cert_exp = base_date + timedelta(days=random.randint(180, 730))
        hazmat = True
        cs_cert = True
        dea_reg = True

        # Deterministic anomaly injection
        if i % 10 == 3:      # cert expired
            cert_exp = base_date - timedelta(days=random.randint(30, 180))
        if i % 10 == 6:      # no hazmat endorsement
            hazmat = False
        if i % 10 == 9:      # not DEA-registered + no CS cert
            dea_reg = False
            cs_cert = False

        carriers.append({
            "carrier_id": f"CAR-{i+1:04d}",
            "carrier_name": cname,
            "dot_number": dot,
            "certification_expiry": cert_exp.strftime("%Y-%m-%d"),
            "hazmat_certified": hazmat,
            "controlled_substance_certified": cs_cert,
            "dea_registered": dea_reg,
        })

    # ── 3. Generate Shipments ────────────────────────────────────────────────
    shipments = []
    for i in range(n):
        schedule = ALL_SCHEDULES[i % len(ALL_SCHEDULES)]
        substance, unit = random.choice(SUBSTANCES[schedule])
        origin_idx = random.randint(0, n - 1)
        dest_idx = random.randint(0, n - 1)
        while dest_idx == origin_idx:
            dest_idx = random.randint(0, n - 1)
        carrier_idx = random.randint(0, n - 1)

        dep_date = base_date - timedelta(days=random.randint(5, 85))
        transit_h = random.randint(8, 60)
        exp_arrival = dep_date + timedelta(hours=transit_h)
        delay_h = random.randint(-2, 12)
        act_arrival = exp_arrival + timedelta(hours=delay_h)

        quantity = random.randint(100, 5000)
        route_type = ROUTE_TYPES[i % len(ROUTE_TYPES)]
        status = "delivered" if random.random() < 0.85 else "in_transit"

        shipments.append({
            "shipment_id": f"SHP-{i+1:05d}",
            "manifest_number": f"MAN-{random.randint(100000, 999999)}",
            "substance_name": substance,
            "dea_schedule": schedule,
            "quantity_shipped": quantity,
            "unit": unit,
            "origin_facility_id": facilities[origin_idx]["facility_id"],
            "destination_facility_id": facilities[dest_idx]["facility_id"],
            "carrier_id": carriers[carrier_idx]["carrier_id"],
            "departure_date": dep_date.strftime("%Y-%m-%d"),
            "expected_arrival_date": exp_arrival.strftime("%Y-%m-%d %H:%M"),
            "actual_arrival_date": act_arrival.strftime("%Y-%m-%d %H:%M") if status == "delivered" else None,
            "route_type": route_type,
            "status": status,
        })

    # ── 4. Generate DEA Forms (one per shipment) ─────────────────────────────
    fac_map = {f["facility_id"]: f for f in facilities}
    dea_forms = []
    for i, s in enumerate(shipments):
        dep = datetime.strptime(s["departure_date"], "%Y-%m-%d")
        issue_date = dep - timedelta(days=random.randint(1, 14))

        # Default: matching, valid
        auth_qty = s["quantity_shipped"]
        form_schedule = s["dea_schedule"]
        form_expiry = issue_date + timedelta(days=random.randint(60, 365))

        # Deterministic anomalies
        if i % 7 == 2:       # quantity mismatch
            pct = random.uniform(0.05, 0.20)
            direction = random.choice([-1, 1])
            auth_qty = max(1, int(s["quantity_shipped"] * (1 + direction * pct)))
        if i % 11 == 5:      # schedule mismatch
            others = [sc for sc in ALL_SCHEDULES if sc != s["dea_schedule"]]
            form_schedule = random.choice(others)
        if i % 13 == 3:      # form expired before departure
            form_expiry = issue_date + timedelta(days=random.randint(1, 5))
            # ensure expired before departure
            if form_expiry >= dep:
                form_expiry = dep - timedelta(days=1)

        origin_fac = fac_map[s["origin_facility_id"]]
        dest_fac = fac_map[s["destination_facility_id"]]

        dea_forms.append({
            "form_id": f"DEA222-{i+1:06d}",
            "shipment_id": s["shipment_id"],
            "form_number": f"222-{random.randint(10000000, 99999999)}",
            "authorized_quantity": auth_qty,
            "substance_schedule_on_form": form_schedule,
            "supplier_dea_number": origin_fac["dea_number"],
            "purchaser_dea_number": dest_fac["dea_number"],
            "issue_date": issue_date.strftime("%Y-%m-%d"),
            "expiry_date": form_expiry.strftime("%Y-%m-%d"),
        })

    # ── 5. Generate GPS Logs ─────────────────────────────────────────────────
    gps_logs = []
    log_id = 1
    n_entries_per_shipment = 10

    for i, s in enumerate(shipments):
        dep_dt = datetime.strptime(s["departure_date"], "%Y-%m-%d")
        dep_dt = dep_dt.replace(hour=random.randint(6, 14))
        if s["actual_arrival_date"]:
            arr_dt = datetime.strptime(s["actual_arrival_date"], "%Y-%m-%d %H:%M")
        else:
            arr_dt = datetime.strptime(s["expected_arrival_date"], "%Y-%m-%d %H:%M")
        total_sec = max(3600, (arr_dt - dep_dt).total_seconds())

        route = s["route_type"]
        checkpoints = CHECKPOINT_MAP[route]

        # Determine if this shipment has a custody gap (missing checkpoint)
        has_gap = (i % 8 == 4) and len(checkpoints) > 2
        gap_zone = None
        if has_gap:
            # skip a middle checkpoint
            mid_indices = list(range(1, len(checkpoints) - 1))
            gap_zone = checkpoints[mid_indices[0]]

        # Determine if this shipment has geofence violations
        has_violation = (i % 9 == 1)

        for j in range(n_entries_per_shipment):
            progress = j / max(1, n_entries_per_shipment - 1)
            ts = dep_dt + timedelta(seconds=total_sec * progress)
            jitter = random.randint(-300, 300)
            ts = ts + timedelta(seconds=jitter)

            # Assign zone based on progress and route
            if len(checkpoints) == 2:
                zone = checkpoints[0] if progress < 0.5 else checkpoints[1]
            elif len(checkpoints) == 3:
                if progress < 0.25:
                    zone = checkpoints[0]
                elif progress < 0.75:
                    zone = checkpoints[1]
                else:
                    zone = checkpoints[2]
            else:  # 4 checkpoints
                if progress < 0.2:
                    zone = checkpoints[0]
                elif progress < 0.5:
                    zone = checkpoints[1]
                elif progress < 0.8:
                    zone = checkpoints[2]
                else:
                    zone = checkpoints[3]

            # Skip entries for gap zone
            if has_gap and zone == gap_zone:
                continue

            # Coordinates
            base_lat = 33.0 + progress * 9.0
            base_lon = -118.0 + progress * 40.0
            lat = round(base_lat + random.uniform(-0.5, 0.5), 6)
            lon = round(base_lon + random.uniform(-0.5, 0.5), 6)
            speed = round(random.uniform(30, 70), 1)
            if j == 0 or j == n_entries_per_shipment - 1:
                speed = 0.0

            geofence_status = "inside"
            if has_violation and j in (3, 6):
                geofence_status = "outside"
                lat += random.uniform(3.0, 6.0)
                lon += random.uniform(3.0, 6.0)

            gps_logs.append({
                "log_id": log_id,
                "shipment_id": s["shipment_id"],
                "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                "latitude": lat,
                "longitude": lon,
                "speed_mph": speed,
                "zone_name": zone,
                "geofence_status": geofence_status,
            })
            log_id += 1

    # ── 6. Create Database ───────────────────────────────────────────────────
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE facilities (
        facility_id TEXT PRIMARY KEY, facility_name TEXT, facility_type TEXT,
        state TEXT, dea_number TEXT UNIQUE, license_number TEXT,
        license_expiry_date TEXT, license_status TEXT, schedules_authorized TEXT
    )""")
    c.execute("""CREATE TABLE carriers (
        carrier_id TEXT PRIMARY KEY, carrier_name TEXT, dot_number TEXT,
        certification_expiry TEXT, hazmat_certified INTEGER,
        controlled_substance_certified INTEGER, dea_registered INTEGER
    )""")
    c.execute("""CREATE TABLE shipments (
        shipment_id TEXT PRIMARY KEY, manifest_number TEXT, substance_name TEXT,
        dea_schedule TEXT, quantity_shipped INTEGER, unit TEXT,
        origin_facility_id TEXT, destination_facility_id TEXT, carrier_id TEXT,
        departure_date TEXT, expected_arrival_date TEXT, actual_arrival_date TEXT,
        route_type TEXT, status TEXT,
        FOREIGN KEY (origin_facility_id) REFERENCES facilities(facility_id),
        FOREIGN KEY (destination_facility_id) REFERENCES facilities(facility_id),
        FOREIGN KEY (carrier_id) REFERENCES carriers(carrier_id)
    )""")
    c.execute("""CREATE TABLE dea_forms (
        form_id TEXT PRIMARY KEY, shipment_id TEXT, form_number TEXT,
        authorized_quantity INTEGER, substance_schedule_on_form TEXT,
        supplier_dea_number TEXT, purchaser_dea_number TEXT,
        issue_date TEXT, expiry_date TEXT,
        FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id)
    )""")
    c.execute("""CREATE TABLE gps_logs (
        log_id INTEGER PRIMARY KEY, shipment_id TEXT, timestamp TEXT,
        latitude REAL, longitude REAL, speed_mph REAL,
        zone_name TEXT, geofence_status TEXT,
        FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id)
    )""")

    for f in facilities:
        c.execute("INSERT INTO facilities VALUES (?,?,?,?,?,?,?,?,?)",
                  (f["facility_id"], f["facility_name"], f["facility_type"],
                   f["state"], f["dea_number"], f["license_number"],
                   f["license_expiry_date"], f["license_status"],
                   f["schedules_authorized"]))
    for cr in carriers:
        c.execute("INSERT INTO carriers VALUES (?,?,?,?,?,?,?)",
                  (cr["carrier_id"], cr["carrier_name"], cr["dot_number"],
                   cr["certification_expiry"], int(cr["hazmat_certified"]),
                   int(cr["controlled_substance_certified"]),
                   int(cr["dea_registered"])))
    for s in shipments:
        c.execute("INSERT INTO shipments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (s["shipment_id"], s["manifest_number"], s["substance_name"],
                   s["dea_schedule"], s["quantity_shipped"], s["unit"],
                   s["origin_facility_id"], s["destination_facility_id"],
                   s["carrier_id"], s["departure_date"],
                   s["expected_arrival_date"], s["actual_arrival_date"],
                   s["route_type"], s["status"]))
    for d in dea_forms:
        c.execute("INSERT INTO dea_forms VALUES (?,?,?,?,?,?,?,?,?)",
                  (d["form_id"], d["shipment_id"], d["form_number"],
                   d["authorized_quantity"], d["substance_schedule_on_form"],
                   d["supplier_dea_number"], d["purchaser_dea_number"],
                   d["issue_date"], d["expiry_date"]))
    for g in gps_logs:
        c.execute("INSERT INTO gps_logs VALUES (?,?,?,?,?,?,?,?)",
                  (g["log_id"], g["shipment_id"], g["timestamp"],
                   g["latitude"], g["longitude"], g["speed_mph"],
                   g["zone_name"], g["geofence_status"]))

    conn.commit()
    conn.close()

    # ── 7. Generate Workspace Files ──────────────────────────────────────────
    # Split scalable files across formats
    n_csv = max(2, round(n_files * 0.35))
    n_json = max(1, round(n_files * 0.25))
    n_txt = max(1, round(n_files * 0.25))
    n_md = max(1, n_files - n_csv - n_json - n_txt)

    # 7a. Shipment manifest CSVs
    batch = max(1, n // n_csv)
    for fi in range(n_csv):
        start = fi * batch
        end = start + batch if fi < n_csv - 1 else n
        rows = []
        for s in shipments[start:end]:
            orig = fac_map[s["origin_facility_id"]]
            dest = fac_map[s["destination_facility_id"]]
            car = {c["carrier_id"]: c for c in carriers}[s["carrier_id"]]
            rows.append({
                "shipment_id": s["shipment_id"],
                "manifest_number": s["manifest_number"],
                "substance_name": s["substance_name"],
                "dea_schedule": s["dea_schedule"],
                "quantity_shipped": s["quantity_shipped"],
                "unit": s["unit"],
                "origin_facility_id": orig["facility_id"],
                "origin_facility_name": orig["facility_name"],
                "destination_facility_id": dest["facility_id"],
                "destination_facility_name": dest["facility_name"],
                "carrier_id": s["carrier_id"],
                "carrier_name": car["carrier_name"],
                "departure_date": s["departure_date"],
                "expected_arrival_date": s["expected_arrival_date"],
                "status": s["status"],
            })
        pd.DataFrame(rows).to_csv(
            os.path.join(args.workspace, f"manifest_batch_{fi+1:03d}.csv"), index=False)

    # 7b. Route plan + GPS summary JSONs
    gps_by_ship = {}
    for g in gps_logs:
        gps_by_ship.setdefault(g["shipment_id"], []).append(g)
    batch_g = max(1, n // n_json)
    for fi in range(n_json):
        start = fi * batch_g
        end = start + batch_g if fi < n_json - 1 else n
        entries = []
        for s in shipments[start:end]:
            ship_gps = gps_by_ship.get(s["shipment_id"], [])
            zones_seen = []
            for g in ship_gps:
                if not zones_seen or zones_seen[-1] != g["zone_name"]:
                    zones_seen.append(g["zone_name"])
            entries.append({
                "shipment_id": s["shipment_id"],
                "route_type": s["route_type"],
                "required_checkpoints": CHECKPOINT_MAP[s["route_type"]],
                "total_gps_pings": len(ship_gps),
                "zones_observed": zones_seen,
                "first_ping": ship_gps[0]["timestamp"] if ship_gps else None,
                "last_ping": ship_gps[-1]["timestamp"] if ship_gps else None,
            })
        with open(os.path.join(args.workspace, f"route_plan_{fi+1:03d}.json"), "w") as fp:
            json.dump(entries, fp, indent=2)

    # 7c. Carrier summary TXTs
    car_map = {c["carrier_id"]: c for c in carriers}
    batch_c = max(1, n // n_txt)
    for fi in range(n_txt):
        start = fi * batch_c
        end = start + batch_c if fi < n_txt - 1 else n
        lines = []
        for cr in carriers[start:end]:
            assigned = [s for s in shipments if s["carrier_id"] == cr["carrier_id"]]
            lines.append(f"=== {cr['carrier_name']} ({cr['carrier_id']}) ===")
            lines.append(f"DOT: {cr['dot_number']}")
            lines.append(f"Shipments assigned: {len(assigned)}")
            for a in assigned:
                lines.append(f"  {a['shipment_id']}: {a['substance_name']} "
                             f"(Schedule {a['dea_schedule']}), "
                             f"{a['origin_facility_id']} -> {a['destination_facility_id']}")
            lines.append("")
        with open(os.path.join(args.workspace, f"carrier_log_{fi+1:03d}.txt"), "w") as fp:
            fp.write("\n".join(lines))

    # 7d. Facility inspection MDs
    batch_f = max(1, n // n_md)
    for fi in range(n_md):
        start = fi * batch_f
        end = start + batch_f if fi < n_md - 1 else n
        lines = []
        for fac in facilities[start:end]:
            insp_date = (base_date - timedelta(days=random.randint(10, 180))).strftime("%Y-%m-%d")
            outcomes = ["satisfactory", "minor_deficiency", "major_deficiency", "satisfactory"]
            outcome = outcomes[random.randint(0, len(outcomes) - 1)]
            lines.append(f"## {fac['facility_name']}")
            lines.append(f"- ID: {fac['facility_id']}")
            lines.append(f"- Type: {fac['facility_type']}")
            lines.append(f"- State: {fac['state']}")
            lines.append(f"- DEA Number: {fac['dea_number']}")
            lines.append(f"- License: {fac['license_number']}")
            lines.append(f"- Last Inspection: {insp_date} — {outcome}")
            if outcome == "major_deficiency":
                lines.append("  - Follow-up required within 30 days")
            lines.append("")
        with open(os.path.join(args.workspace, f"facility_notes_{fi+1:03d}.md"), "w") as fp:
            fp.write("\n".join(lines))

    # ── 8. Fixed configuration files (do not scale) ──────────────────────────

    # Regulatory config
    reg = {
        "discrepancy_types": {
            "QUANTITY_MISMATCH": {
                "description": "Authorized quantity on DEA Form 222 does not match manifest shipped quantity",
                "severity": "high",
            },
            "EXPIRED_FACILITY_LICENSE": {
                "description": "Origin or destination facility license is expired or suspended at departure",
                "severity": "critical",
            },
            "SCHEDULE_MISMATCH": {
                "description": "DEA Form 222 schedule does not match shipment manifest schedule",
                "severity": "critical",
            },
            "UNAUTHORIZED_SCHEDULE": {
                "description": "Facility not authorized to handle the substance schedule",
                "severity": "critical",
            },
            "CUSTODY_GAP": {
                "description": "Required route checkpoint missing from GPS tracking data",
                "severity": "high",
            },
            "GEOFENCE_VIOLATION": {
                "description": "GPS ping detected outside authorized geofence zone",
                "severity": "medium",
            },
            "CARRIER_NONCOMPLIANT": {
                "description": "Carrier certification expired, missing hazmat endorsement for Sched I/II, or not DEA-registered",
                "severity": "medium",
            },
            "DEA_FORM_EXPIRED": {
                "description": "DEA Form 222 expired before shipment departure date",
                "severity": "critical",
            },
        },
        "recommended_actions": {
            "critical": "QUARANTINE_AND_NOTIFY_DEA",
            "high": "SUSPEND_AND_INVESTIGATE",
            "medium": "FLAG_FOR_AUDIT_REVIEW",
        },
        "carrier_rules": {
            "hazmat_required_schedules": ["II"],
            "dea_registration_required": True,
            "controlled_substance_cert_required": True,
        },
    }
    with open(os.path.join(args.workspace, "regulatory_config.yaml"), "w") as fp:
        yaml.dump(reg, fp, default_flow_style=False, sort_keys=False)

    # Geofence zone definitions
    geo = {
        "authorized_zones": {
            "ORIGIN":    {"lat_range": [32.5, 35.5], "lon_range": [-118.5, -117.5]},
            "TRANSIT_A": {"lat_range": [35.0, 38.0], "lon_range": [-110.0, -100.0]},
            "TRANSIT_B": {"lat_range": [37.0, 40.0], "lon_range": [-100.0, -85.0]},
            "DESTINATION": {"lat_range": [39.0, 42.5], "lon_range": [-80.0, -73.5]},
        },
        "note": "GPS pings with geofence_status 'outside' were recorded beyond these zone boundaries.",
    }
    with open(os.path.join(args.workspace, "geofence_zones.json"), "w") as fp:
        json.dump(geo, fp, indent=2)

    # DEA schedule handling rules
    dea_rules = {
        "schedule_handling": {
            "II": {
                "form_222_required": True,
                "hazmat_carrier_required": True,
                "max_transit_hours": 36,
            },
            "III": {
                "form_222_required": True,
                "hazmat_carrier_required": False,
                "max_transit_hours": 48,
            },
            "IV": {
                "form_222_required": True,
                "hazmat_carrier_required": False,
                "max_transit_hours": 72,
            },
            "V": {
                "form_222_required": True,
                "hazmat_carrier_required": False,
                "max_transit_hours": 96,
            },
        },
        "general_rules": (
            "All facilities must hold an active, non-expired license and be authorized "
            "for the specific schedule being transferred. All carriers must be DEA-registered "
            "and hold a valid controlled-substance transportation certification. "
            "Schedule II shipments require a hazmat-endorsed carrier."
        ),
    }
    with open(os.path.join(args.workspace, "dea_schedule_rules.yaml"), "w") as fp:
        yaml.dump(dea_rules, fp, default_flow_style=False, sort_keys=False)

    # Print summary
    print(f"Database: {args.db_path}")
    print(f"  facilities={len(facilities)}, carriers={len(carriers)}, "
          f"shipments={len(shipments)}, dea_forms={len(dea_forms)}, "
          f"gps_logs={len(gps_logs)}")
    ws = sorted(os.listdir(args.workspace))
    print(f"Workspace: {len(ws)} files -> {ws}")


if __name__ == "__main__":
    main()
