"""
Data generation for vessel catch-log / quota reconciliation task.
Generates SQLite DB and workspace files for the monitoring environment.
"""

import argparse
import json
import os
import random
import sqlite3
import csv
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

# ── Scale parameters (v0 base) ─────────────────────────────────────
SCALE = {
    "rows_per_table": 640,      # v3 = 8× base
    "num_workspace_files": 40,  # v3 = base + 3N (N=10)
}

# ── Deterministic seeding ───────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ── Domain constants ────────────────────────────────────────────────
SPECIES = [
    ("COD", "Atlantic Cod"),
    ("HAD", "Haddock"),
    ("POL", "Pollock"),
    ("HKE", "Hake"),
    ("SOL", "Common Sole"),
    ("PLE", "Plaice"),
    ("MAC", "Atlantic Mackerel"),
    ("HER", "Atlantic Herring"),
    ("TUN", "Bluefin Tuna"),
    ("SWO", "Swordfish"),
]

ZONES = ["Z-NW1", "Z-NW2", "Z-NE1", "Z-NE2", "Z-SE1", "Z-SE2", "Z-SW1", "Z-SW2"]

PORTS = ["Grimsby", "Peterhead", "Boulogne", "Vigo", "Tromso", "Reykjavik"]

VESSEL_TYPES = ["Trawler", "Longliner", "Purse Seiner", "Gillnetter"]

FLAG_STATES = ["GBR", "FRA", "ESP", "NOR", "ISL", "NLD"]

INSPECTORS = [
    "Cpt. L. Harmon", "Agt. R. De Vries", "Insp. M. Soares",
    "Off. K. Johansen", "Agt. P. Moreau", "Insp. T. Nakamura",
]


def create_tables(conn):
    """Create all database tables."""
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS vessels (
            vessel_id INTEGER PRIMARY KEY,
            vessel_name TEXT NOT NULL,
            registration_number TEXT UNIQUE NOT NULL,
            flag_state TEXT NOT NULL,
            vessel_type TEXT NOT NULL,
            home_port TEXT NOT NULL,
            length_m REAL NOT NULL,
            gross_tonnage REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS catch_reports (
            report_id INTEGER PRIMARY KEY,
            vessel_id INTEGER NOT NULL,
            report_date TEXT NOT NULL,
            species_code TEXT NOT NULL,
            reported_quantity_kg REAL NOT NULL,
            catch_zone TEXT NOT NULL,
            submission_timestamp TEXT NOT NULL,
            FOREIGN KEY (vessel_id) REFERENCES vessels(vessel_id)
        );

        CREATE TABLE IF NOT EXISTS quota_certificates (
            certificate_id INTEGER PRIMARY KEY,
            vessel_id INTEGER NOT NULL,
            species_code TEXT NOT NULL,
            allocated_quota_kg REAL NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            certificate_number TEXT UNIQUE NOT NULL,
            issuing_authority TEXT NOT NULL,
            FOREIGN KEY (vessel_id) REFERENCES vessels(vessel_id)
        );

        CREATE TABLE IF NOT EXISTS port_inspections (
            inspection_id INTEGER PRIMARY KEY,
            vessel_id INTEGER NOT NULL,
            inspection_date TEXT NOT NULL,
            port TEXT NOT NULL,
            inspector_name TEXT NOT NULL,
            species_code TEXT NOT NULL,
            measured_quantity_kg REAL NOT NULL,
            compliance_flag TEXT NOT NULL,
            remarks TEXT,
            FOREIGN KEY (vessel_id) REFERENCES vessels(vessel_id)
        );

        CREATE TABLE IF NOT EXISTS ais_tracking (
            ais_id INTEGER PRIMARY KEY,
            vessel_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            speed_knots REAL NOT NULL,
            heading REAL NOT NULL,
            zone_code TEXT NOT NULL,
            FOREIGN KEY (vessel_id) REFERENCES vessels(vessel_id)
        );
    """)
    conn.commit()


def generate_vessels(conn, n_vessels):
    """Generate vessel records."""
    vessels = []
    for i in range(1, n_vessels + 1):
        reg = f"V-{fake.unique.bothify(text='???-####').upper()}"
        vessel = (
            i,
            fake.company()[:30] + " " + random.choice(["I", "II", "III", "IV", "V"]),
            reg,
            random.choice(FLAG_STATES),
            random.choice(VESSEL_TYPES),
            random.choice(PORTS),
            round(random.uniform(18.0, 65.0), 1),
            round(random.uniform(50.0, 500.0), 1),
        )
        vessels.append(vessel)
    conn.executemany(
        "INSERT INTO vessels VALUES (?,?,?,?,?,?,?,?)", vessels
    )
    conn.commit()
    return vessels


def generate_catch_reports(conn, vessels, n_rows):
    """Generate electronic catch reports."""
    base_date = datetime(2026, 1, 1)
    reports = []
    for rid in range(1, n_rows + 1):
        v = random.choice(vessels)
        vid = v[0]
        day_offset = random.randint(0, 89)  # Q1 2026
        rdate = (base_date + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        sp = random.choice(SPECIES)[0]
        qty = round(random.uniform(20.0, 800.0), 2)
        zone = random.choice(ZONES)
        ts = (base_date + timedelta(days=day_offset, hours=random.randint(6, 22),
                                     minutes=random.randint(0, 59))).isoformat()
        reports.append((rid, vid, rdate, sp, qty, zone, ts))
    conn.executemany(
        "INSERT INTO catch_reports VALUES (?,?,?,?,?,?,?)", reports
    )
    conn.commit()
    return reports


def generate_quota_certificates(conn, vessels, species_list):
    """Generate quota certificates -- one per vessel per species (subset)."""
    certs = []
    cid = 1
    for v in vessels:
        vid = v[0]
        # Each vessel gets quotas for 4-7 species
        n_sp = random.randint(4, 7)
        chosen = random.sample(species_list, n_sp)
        for sp_code, _ in chosen:
            quota = round(random.uniform(500.0, 5000.0), 2)
            cert_num = f"QC-{vid:04d}-{sp_code}-{fake.bothify(text='####')}"
            authority = random.choice([
                "North Atlantic Fisheries Board",
                "EU Fisheries Commission",
                "Nordic Marine Authority",
            ])
            certs.append((
                cid, vid, sp_code, quota,
                "2026-01-01", "2026-03-31", cert_num, authority
            ))
            cid += 1
    conn.executemany(
        "INSERT INTO quota_certificates VALUES (?,?,?,?,?,?,?,?)", certs
    )
    conn.commit()
    return certs


def generate_port_inspections(conn, vessels, n_rows):
    """Generate port agent inspection records."""
    base_date = datetime(2026, 1, 1)
    inspections = []
    for iid in range(1, n_rows + 1):
        v = random.choice(vessels)
        vid = v[0]
        day_offset = random.randint(0, 89)
        idate = (base_date + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        port = random.choice(PORTS)
        inspector = random.choice(INSPECTORS)
        sp = random.choice(SPECIES)[0]
        qty = round(random.uniform(30.0, 900.0), 2)
        comp = random.choice(["PASS", "PASS", "PASS", "FLAG", "FLAG"])
        remarks = fake.sentence(nb_words=8) if comp == "FLAG" else ""
        inspections.append((iid, vid, idate, port, inspector, sp, qty, comp, remarks))
    conn.executemany(
        "INSERT INTO port_inspections VALUES (?,?,?,?,?,?,?,?,?)", inspections
    )
    conn.commit()
    return inspections


def generate_ais_tracking(conn, vessels, n_rows):
    """Generate satellite AIS tracking data."""
    base_date = datetime(2026, 1, 1)
    records = []
    for aid in range(1, n_rows + 1):
        v = random.choice(vessels)
        vid = v[0]
        day_offset = random.randint(0, 89)
        ts = (base_date + timedelta(
            days=day_offset,
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59)
        )).isoformat()
        lat = round(random.uniform(48.0, 70.0), 4)
        lon = round(random.uniform(-25.0, 10.0), 4)
        speed = round(random.uniform(0.0, 14.0), 1)
        heading = round(random.uniform(0.0, 360.0), 1)
        zone = random.choice(ZONES)
        records.append((aid, vid, ts, lat, lon, speed, heading, zone))
    conn.executemany(
        "INSERT INTO ais_tracking VALUES (?,?,?,?,?,?,?,?)", records
    )
    conn.commit()
    return records


# ── Workspace file generation ───────────────────────────────────────

def generate_workspace(workspace, conn, vessels, catch_reports, inspections, ais_records):
    """Generate workspace files mixing formats."""
    os.makedirs(workspace, exist_ok=True)

    n_vessels = len(vessels)
    n_scalable = SCALE["num_workspace_files"]

    # ── Fixed policy/config files (not counted in SCALE) ────────────

    # 1. quota_rules.yaml -- tolerance thresholds, seasonal multipliers, zone restrictions
    import yaml
    quota_rules = {
        "tolerance_pct": 5.0,
        "overage_tiers": [
            {"tier": "minor", "min_pct": 5.01, "max_pct": 15.0, "penalty_multiplier": 1.5},
            {"tier": "major", "min_pct": 15.01, "max_pct": 30.0, "penalty_multiplier": 3.0},
            {"tier": "critical", "min_pct": 30.01, "max_pct": 999.0, "penalty_multiplier": 5.0},
        ],
        "seasonal_adjustments": {
            "January": 1.0,
            "February": 1.0,
            "March": 0.85,
        },
        "zone_restricted_species": {
            "Z-NW1": ["TUN", "SWO"],
            "Z-NW2": ["TUN"],
            "Z-NE1": ["SWO"],
            "Z-NE2": [],
            "Z-SE1": ["TUN", "SWO"],
            "Z-SE2": [],
            "Z-SW1": ["TUN"],
            "Z-SW2": ["SWO"],
        },
        "inspection_discrepancy_threshold_pct": 10.0,
    }
    with open(os.path.join(workspace, "quota_rules.yaml"), "w") as f:
        yaml.dump(quota_rules, f, default_flow_style=False, sort_keys=False)

    # 2. species_reference.json
    species_ref = {code: name for code, name in SPECIES}
    with open(os.path.join(workspace, "species_reference.json"), "w") as f:
        json.dump(species_ref, f, indent=2)

    # 3. zone_definitions.md
    zone_md = "# Fishing Zone Definitions\n\n"
    zone_coords = {
        "Z-NW1": ("60.0-70.0N", "25.0-15.0W"),
        "Z-NW2": ("55.0-60.0N", "25.0-15.0W"),
        "Z-NE1": ("60.0-70.0N", "0.0-10.0E"),
        "Z-NE2": ("55.0-60.0N", "0.0-10.0E"),
        "Z-SE1": ("48.0-55.0N", "0.0-10.0E"),
        "Z-SE2": ("48.0-52.0N", "5.0W-0.0"),
        "Z-SW1": ("52.0-58.0N", "15.0-5.0W"),
        "Z-SW2": ("48.0-52.0N", "15.0-5.0W"),
    }
    for z, (lat_range, lon_range) in zone_coords.items():
        zone_md += f"## {z}\nLatitude range: {lat_range}, Longitude range: {lon_range}\n\n"
    with open(os.path.join(workspace, "zone_definitions.md"), "w") as f:
        f.write(zone_md)

    # 4. authority_contacts.txt
    contacts = (
        "North Atlantic Fisheries Board | compliance@nafb.org | +44 20 7946 0001\n"
        "EU Fisheries Commission | enforcement@eufc.europa.eu | +32 2 299 1111\n"
        "Nordic Marine Authority | ops@nma.no | +47 22 24 9001\n"
    )
    with open(os.path.join(workspace, "authority_contacts.txt"), "w") as f:
        f.write(contacts)

    # ── Scalable data files ─────────────────────────────────────────

    # Distribute: ~40% CSV landing supplements, ~30% JSON AIS summaries, ~30% TXT inspector notes
    n_csv = max(1, int(n_scalable * 0.4))
    n_json = max(1, int(n_scalable * 0.3))
    n_txt = n_scalable - n_csv - n_json

    # --- CSV: port daily landing supplements (manual records NOT in DB) ---
    base_date = datetime(2026, 1, 1)
    port_date_combos = []
    for d_off in range(0, 90):
        for port in PORTS:
            port_date_combos.append((port, base_date + timedelta(days=d_off)))
    random.shuffle(port_date_combos)

    for fi in range(n_csv):
        port, day = port_date_combos[fi]
        date_str = day.strftime("%Y-%m-%d")
        fname = f"landing_supplement_{port.lower()}_{date_str}.csv"
        rows = []
        candidate_vessels = [v for v in vessels if v[5] == port]
        if not candidate_vessels:
            candidate_vessels = random.sample(vessels, min(3, n_vessels))
        n_entries = random.randint(2, 5)
        for _ in range(n_entries):
            v = random.choice(candidate_vessels)
            sp = random.choice(SPECIES)[0]
            qty = round(random.uniform(10.0, 200.0), 2)
            rows.append({
                "vessel_id": v[0],
                "vessel_name": v[1],
                "date": date_str,
                "species_code": sp,
                "manual_landing_kg": qty,
                "port": port,
                "recorded_by": random.choice(INSPECTORS),
            })
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    # --- JSON: AIS zone-time summaries per vessel ---
    vessel_ids_for_json = list(range(1, n_vessels + 1))
    random.shuffle(vessel_ids_for_json)
    for fi in range(n_json):
        vid = vessel_ids_for_json[fi % n_vessels]
        vname = vessels[vid - 1][1]
        zone_hours = {}
        for z in ZONES:
            hrs = round(random.uniform(0, 120.0), 1)
            if hrs > 5.0:
                zone_hours[z] = hrs
        summary = {
            "vessel_id": vid,
            "vessel_name": vname,
            "period": "2026-Q1",
            "zone_hours": zone_hours,
            "total_hours_at_sea": round(sum(zone_hours.values()) + random.uniform(10, 50), 1),
            "generated": datetime(2026, 4, 1).isoformat(),
        }
        fname = f"ais_zone_summary_vessel_{vid}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(summary, f, indent=2)

    # --- TXT: Inspector amendment notes ---
    insp_sample = random.sample(inspections, min(n_txt * 3, len(inspections)))
    chunk_size = max(1, len(insp_sample) // max(1, n_txt))
    for fi in range(n_txt):
        chunk = insp_sample[fi * chunk_size: (fi + 1) * chunk_size]
        lines = ["INSPECTOR AMENDMENT RECORD", f"Filed: 2026-04-{10 + fi:02d}", ""]
        for rec in chunk:
            iid, vid, idate, port, inspector, sp, qty, comp, remarks = rec
            delta = round(random.uniform(-50.0, 50.0), 2)
            corrected = round(qty + delta, 2)
            lines.append(
                f"Inspection #{iid} | Vessel {vid} | {idate} | {sp} | "
                f"Original: {qty:.2f} kg | Corrected: {corrected:.2f} kg | "
                f"Reason: {fake.sentence(nb_words=6)}"
            )
        lines.append("")
        fname = f"inspector_amendments_batch_{fi + 1}.txt"
        with open(os.path.join(workspace, fname), "w") as f:
            f.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    rpt = SCALE["rows_per_table"]
    n_vessels = max(16, rpt // 5)

    vessels = generate_vessels(conn, n_vessels)
    catch_reports = generate_catch_reports(conn, vessels, rpt)
    certs = generate_quota_certificates(conn, vessels, SPECIES)
    inspections = generate_port_inspections(conn, vessels, rpt)
    ais_records = generate_ais_tracking(conn, vessels, rpt * 2)

    conn.close()

    conn = sqlite3.connect(args.db_path)
    generate_workspace(args.workspace, conn, vessels, catch_reports, inspections, ais_records)
    conn.close()

    print(f"Database created at {args.db_path}")
    print(f"Workspace populated at {args.workspace}")
    print(f"  Vessels: {n_vessels}")
    print(f"  Catch reports: {rpt}")
    print(f"  Quota certificates: {len(certs)}")
    print(f"  Port inspections: {rpt}")
    print(f"  AIS records: {rpt * 2}")
    print(f"  Scalable workspace files: {SCALE['num_workspace_files']}")


if __name__ == "__main__":
    main()
