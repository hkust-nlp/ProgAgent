import argparse
import sqlite3
import os
import json
import csv
import random
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta
import yaml

SCALE = {
    "rows_per_table": 800,
    "num_workspace_files": 40,
}

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

REF_DATE = datetime(2026, 4, 25)

PORTS = [
    ("CNSHA", "Shanghai", 31.23, 121.47),
    ("USLAX", "Los Angeles", 33.74, -118.26),
    ("NLRTM", "Rotterdam", 51.95, 4.50),
    ("SGSIN", "Singapore", 1.26, 103.84),
    ("DEHAM", "Hamburg", 53.55, 9.93),
    ("JPYOK", "Yokohama", 35.44, 139.64),
    ("KRPUS", "Busan", 35.10, 129.04),
    ("AEJEA", "Jebel Ali", 25.01, 55.06),
    ("GBFXT", "Felixstowe", 51.96, 1.35),
    ("BRSSZ", "Santos", -23.95, -46.33),
    ("INMUN", "Mumbai", 18.95, 72.84),
    ("AUMEL", "Melbourne", -37.82, 144.96),
    ("TWKHH", "Kaohsiung", 22.61, 120.28),
    ("MYPKG", "Port Klang", 3.00, 101.39),
    ("USNYC", "New York", 40.68, -74.04),
]

COMMODITIES = ["ELEC", "TEXT", "MACH", "FOOD", "CHEM", "AUTO", "PHAR", "RAWM", "FURN", "TOYS"]

INCOTERMS = ["FOB", "CIF", "DAP", "DDP", "EXW", "FCA", "CFR", "CPT"]

CONGESTION_LEVELS = ["low", "moderate", "high", "severe"]


def haversine_nm(lat1, lon1, lat2, lon2):
    """Calculate great circle distance in nautical miles."""
    R_nm = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R_nm * 2 * math.asin(min(1.0, math.sqrt(a)))


def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS shipments (
        shipment_id TEXT PRIMARY KEY,
        vessel_id TEXT,
        shipper_id TEXT,
        origin_port TEXT,
        dest_port TEXT,
        commodity_code TEXT,
        incoterm TEXT,
        contract_delivery_date TEXT,
        status TEXT,
        booking_date TEXT,
        quantity_tons REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS vessels (
        vessel_id TEXT PRIMARY KEY,
        vessel_name TEXT,
        imo_number TEXT,
        current_lat REAL,
        current_lon REAL,
        speed_knots REAL,
        heading_degrees REAL,
        last_ais_update TEXT,
        destination_port TEXT,
        eta_destination TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS port_congestion (
        report_id TEXT PRIMARY KEY,
        port_code TEXT,
        terminal_name TEXT,
        congestion_level TEXT,
        avg_berth_wait_days REAL,
        vessel_queue_count INTEGER,
        report_date TEXT,
        notes TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS customs_history (
        record_id TEXT PRIMARY KEY,
        port_code TEXT,
        commodity_code TEXT,
        avg_clearance_hours REAL,
        p95_clearance_hours REAL,
        flagged_rate REAL,
        sample_size INTEGER,
        period TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS shippers (
        shipper_id TEXT PRIMARY KEY,
        shipper_name TEXT,
        contract_tier TEXT,
        penalty_rate_usd_per_day REAL,
        contact_email TEXT
    )""")
    conn.commit()


def generate_shippers(conn, n):
    rows = []
    tiers = ["platinum", "gold", "silver", "standard"]
    tier_weights = [0.1, 0.2, 0.3, 0.4]
    penalty_ranges = {
        "platinum": (800, 2000), "gold": (500, 1200),
        "silver": (200, 700), "standard": (50, 300)
    }
    for i in range(n):
        sid = f"SHP-{i+1:04d}"
        name = fake.company()
        tier = random.choices(tiers, weights=tier_weights, k=1)[0]
        lo, hi = penalty_ranges[tier]
        penalty = round(random.uniform(lo, hi), 2)
        email = fake.company_email()
        rows.append((sid, name, tier, penalty, email))
    conn.executemany("INSERT INTO shippers VALUES (?,?,?,?,?)", rows)
    conn.commit()
    return [r[0] for r in rows]


def generate_vessels(conn, n):
    rows = []
    used_names = set()
    suffixes = ['Star', 'Spirit', 'Pride', 'Glory', 'Fortune',
                'Harmony', 'Venture', 'Express', 'Pioneer', 'Guardian',
                'Voyager', 'Horizon', 'Endeavor', 'Phoenix', 'Titan']
    for i in range(n):
        vid = f"VSL-{i+1:04d}"
        while True:
            name = f"MV {fake.last_name()} {random.choice(suffixes)}"
            if name not in used_names:
                used_names.add(name)
                break
        imo = f"IMO{random.randint(9000000, 9999999)}"
        dest_port = random.choice(PORTS)
        dest_code = dest_port[0]
        dest_lat, dest_lon = dest_port[2], dest_port[3]
        origin_port = random.choice([p for p in PORTS if p[0] != dest_code])
        frac = random.uniform(0.3, 0.95)
        clat = origin_port[2] + frac * (dest_lat - origin_port[2]) + random.uniform(-2, 2)
        clon = origin_port[3] + frac * (dest_lon - origin_port[3]) + random.uniform(-3, 3)
        speed = round(random.uniform(8, 22), 1)
        heading = round(random.uniform(0, 360), 1)
        last_update = (REF_DATE - timedelta(hours=random.randint(1, 12))).strftime("%Y-%m-%dT%H:%M:%SZ")
        remaining_nm = haversine_nm(clat, clon, dest_lat, dest_lon)
        if speed > 0:
            sailing_hours = remaining_nm / speed
            eta_date = REF_DATE + timedelta(hours=sailing_hours)
        else:
            eta_date = REF_DATE + timedelta(days=random.randint(5, 20))
        eta_str = eta_date.strftime("%Y-%m-%d")
        rows.append((vid, name, imo, round(clat, 4), round(clon, 4), speed,
                      heading, last_update, dest_code, eta_str))
    conn.executemany("INSERT INTO vessels VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_shipments(conn, n, vessel_rows, shipper_ids):
    rows = []
    statuses = ["in_transit", "delivered", "pending", "cancelled"]
    status_weights = [0.45, 0.30, 0.15, 0.10]

    for i in range(n):
        sid = f"SHIP-{i+1:05d}"
        vessel = random.choice(vessel_rows)
        vid = vessel[0]
        dest_port_code = vessel[8]
        vessel_eta_str = vessel[9]
        vessel_eta = datetime.strptime(vessel_eta_str, "%Y-%m-%d")

        shipper_id = random.choice(shipper_ids)
        origin_candidates = [p[0] for p in PORTS if p[0] != dest_port_code]
        origin = random.choice(origin_candidates)
        commodity = random.choice(COMMODITIES)
        incoterm = random.choice(INCOTERMS)
        status = random.choices(statuses, weights=status_weights, k=1)[0]

        if status == "in_transit":
            offset = random.choice([-3, -1, 0, 1, 2, 3, 5, 7, 10, 14])
            contract_date = vessel_eta + timedelta(days=offset)
        elif status == "delivered":
            contract_date = REF_DATE - timedelta(days=random.randint(1, 30))
        else:
            contract_date = REF_DATE + timedelta(days=random.randint(10, 60))

        booking_date = (REF_DATE - timedelta(days=random.randint(15, 90))).strftime("%Y-%m-%d")
        quantity = round(random.uniform(50, 5000), 1)

        rows.append((sid, vid, shipper_id, origin, dest_port_code, commodity, incoterm,
                      contract_date.strftime("%Y-%m-%d"), status, booking_date, quantity))

    conn.executemany("INSERT INTO shipments VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_port_congestion(conn, n):
    rows = []
    terminals_per_port = {}
    for port in PORTS:
        code = port[0]
        num_terminals = random.randint(2, 5)
        terminals_per_port[code] = [f"{port[1]} Terminal {chr(65+j)}" for j in range(num_terminals)]

    record_idx = 0
    while record_idx < n:
        for port in PORTS:
            code = port[0]
            for terminal in terminals_per_port[code]:
                if record_idx >= n:
                    break
                rid = f"PCR-{record_idx+1:05d}"
                days_ago = random.randint(0, 14)
                report_date = (REF_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")
                level = random.choices(CONGESTION_LEVELS, weights=[0.3, 0.35, 0.25, 0.1], k=1)[0]
                wait_map = {"low": (0.5, 1.5), "moderate": (1.5, 3.0),
                            "high": (3.0, 6.0), "severe": (6.0, 12.0)}
                lo, hi = wait_map[level]
                wait_days = round(random.uniform(lo, hi), 1)
                queue = random.randint(2, 35)
                notes_options = [
                    "Normal operations.", "Labor negotiations ongoing.",
                    "Weather disruptions expected.", "Equipment maintenance scheduled.",
                    "Peak season congestion.", "New berth opening next week.",
                    "COVID protocols causing delays.", "Crane repairs in progress.",
                    "Dredging operations nearby.", "Holiday schedule in effect."
                ]
                notes = random.choice(notes_options)
                rows.append((rid, code, terminal, level, wait_days, queue, report_date, notes))
                record_idx += 1
            if record_idx >= n:
                break

    conn.executemany("INSERT INTO port_congestion VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_customs_history(conn, n):
    rows = []
    periods = [(REF_DATE - timedelta(days=30 * m)).strftime("%Y-%m") for m in range(6)]
    record_idx = 0

    while record_idx < n:
        for port in PORTS:
            for commodity in COMMODITIES:
                for period in periods:
                    if record_idx >= n:
                        break
                    rid = f"CUS-{record_idx+1:05d}"
                    base_hours = random.uniform(12, 96)
                    if commodity in ["PHAR", "FOOD", "CHEM"]:
                        base_hours *= 1.5
                    avg_hours = round(base_hours, 1)
                    p95_hours = round(base_hours * random.uniform(1.5, 2.5), 1)
                    flagged = round(random.uniform(0.01, 0.25), 3)
                    if commodity in ["PHAR", "CHEM"]:
                        flagged = round(random.uniform(0.1, 0.4), 3)
                    sample_size = random.randint(20, 500)
                    rows.append((rid, port[0], commodity, avg_hours, p95_hours,
                                 flagged, sample_size, period))
                    record_idx += 1
                if record_idx >= n:
                    break
            if record_idx >= n:
                break

    conn.executemany("INSERT INTO customs_history VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_workspace_files(workspace, shipment_rows, vessel_rows, n_files):
    """Generate scalable workspace data files."""
    os.makedirs(workspace, exist_ok=True)

    # Distribute files: route_updates (JSON 30%), customs_modifiers (CSV 30%),
    # contract_amendments (YAML 20%), port_advisories (MD 20%)
    n_route = max(1, n_files * 3 // 10)
    n_customs = max(1, n_files * 3 // 10)
    n_amendments = max(1, n_files * 2 // 10)
    n_advisories = n_files - n_route - n_customs - n_amendments

    in_transit = [s for s in shipment_rows if s[8] == "in_transit"]
    vessel_ids_in_transit = list(set(s[1] for s in in_transit))

    # --- Route deviation updates (JSON) ---
    vessel_deviations = {}
    n_dev_vessels = min(len(vessel_ids_in_transit), max(5, len(vessel_ids_in_transit) * 2 // 3))
    deviation_vessels = random.sample(vessel_ids_in_transit, n_dev_vessels)
    for vid in deviation_vessels:
        n_devs = random.randint(1, 3)
        devs = []
        for _ in range(n_devs):
            dtype = random.choice(["weather_delay", "mechanical_issue", "port_skip",
                                   "route_deviation", "bunkering_stop"])
            delay_h = round(random.uniform(4, 72), 1)
            reported = (REF_DATE - timedelta(days=random.randint(0, 7))).strftime("%Y-%m-%d")
            devs.append({
                "vessel_id": vid, "deviation_type": dtype,
                "delay_hours": delay_h, "reported_date": reported,
                "description": fake.sentence()
            })
        vessel_deviations[vid] = devs

    all_devs = []
    for vid, devs in vessel_deviations.items():
        all_devs.extend(devs)
    random.shuffle(all_devs)

    chunk_size = max(1, len(all_devs) // n_route)
    for i in range(n_route):
        start = i * chunk_size
        end = len(all_devs) if i == n_route - 1 else start + chunk_size
        chunk = all_devs[start:end]
        fpath = os.path.join(workspace, f"route_updates_{i+1:03d}.json")
        with open(fpath, "w") as f:
            json.dump({"route_deviation_reports": chunk,
                        "generated": REF_DATE.strftime("%Y-%m-%d")}, f, indent=2)

    # --- Customs modifiers (CSV) ---
    customs_mods = []
    dest_ports_in_use = list(set(s[4] for s in in_transit))
    commodities_in_use = list(set(s[5] for s in in_transit))
    for pc in dest_ports_in_use:
        n_commod = min(len(commodities_in_use), random.randint(2, 5))
        for cc in random.sample(commodities_in_use, n_commod):
            alert_level = random.choices(["normal", "elevated", "critical"],
                                         weights=[0.5, 0.35, 0.15], k=1)[0]
            mult_map = {
                "normal": 1.0,
                "elevated": round(random.uniform(1.2, 1.6), 2),
                "critical": round(random.uniform(1.7, 2.5), 2)
            }
            customs_mods.append({
                "port_code": pc, "commodity_code": cc,
                "alert_level": alert_level,
                "clearance_multiplier": mult_map[alert_level],
                "effective_date": (REF_DATE - timedelta(days=random.randint(0, 5))).strftime("%Y-%m-%d")
            })

    random.shuffle(customs_mods)
    chunk_size = max(1, len(customs_mods) // n_customs)
    for i in range(n_customs):
        start = i * chunk_size
        end = len(customs_mods) if i == n_customs - 1 else start + chunk_size
        chunk = customs_mods[start:end]
        fpath = os.path.join(workspace, f"customs_modifiers_{i+1:03d}.csv")
        with open(fpath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["port_code", "commodity_code",
                                                    "alert_level", "clearance_multiplier",
                                                    "effective_date"])
            writer.writeheader()
            writer.writerows(chunk)

    # --- Contract amendments (YAML) ---
    n_amend_shipments = min(len(in_transit), max(3, len(in_transit) // 4))
    amendment_shipments = random.sample([s[0] for s in in_transit], n_amend_shipments)
    amendments = []
    for sid in amendment_shipments:
        atype = random.choices(["deadline_extension", "priority_upgrade"],
                               weights=[0.7, 0.3], k=1)[0]
        if atype == "deadline_extension":
            ext_days = random.randint(1, 7)
            amendments.append({
                "shipment_id": sid, "amendment_type": atype,
                "extension_days": ext_days,
                "reason": random.choice([
                    "Buyer requested extension", "Force majeure clause invoked",
                    "Supplier delay acknowledged", "Port strike compensation",
                    "Seasonal demand adjustment"
                ]),
                "effective_date": (REF_DATE - timedelta(days=random.randint(0, 3))).strftime("%Y-%m-%d")
            })
        else:
            amendments.append({
                "shipment_id": sid, "amendment_type": atype,
                "customs_time_reduction_pct": random.randint(10, 40),
                "reason": "Priority customs lane approved",
                "effective_date": (REF_DATE - timedelta(days=random.randint(0, 3))).strftime("%Y-%m-%d")
            })

    random.shuffle(amendments)
    chunk_size = max(1, len(amendments) // n_amendments)
    for i in range(n_amendments):
        start = i * chunk_size
        end = len(amendments) if i == n_amendments - 1 else start + chunk_size
        chunk = amendments[start:end]
        fpath = os.path.join(workspace, f"contract_amendments_{i+1:03d}.yaml")
        with open(fpath, "w") as f:
            yaml.dump({"contract_amendments": chunk,
                        "last_updated": REF_DATE.strftime("%Y-%m-%d")},
                       f, default_flow_style=False)

    # --- Port advisories (MD) ---
    n_adv_ports = min(len(dest_ports_in_use), max(n_advisories * 2, 4))
    advisory_ports = random.sample(dest_ports_in_use, n_adv_ports)
    advisories = []
    for pc in advisory_ports:
        port_name = next(p[1] for p in PORTS if p[0] == pc)
        severity = random.choice(["INFO", "WARNING", "CRITICAL"])
        extra_wait = round(random.uniform(0.5, 3.0), 1) if severity != "INFO" else 0.0
        advisories.append({
            "port_code": pc, "port_name": port_name, "severity": severity,
            "extra_wait_days": extra_wait,
            "advisory": fake.paragraph(nb_sentences=3),
            "issued": (REF_DATE - timedelta(days=random.randint(0, 5))).strftime("%Y-%m-%d")
        })

    random.shuffle(advisories)
    chunk_size = max(1, len(advisories) // max(1, n_advisories))
    for i in range(max(1, n_advisories)):
        start = i * chunk_size
        end = len(advisories) if i == max(1, n_advisories) - 1 else start + chunk_size
        chunk = advisories[start:end]
        fpath = os.path.join(workspace, f"port_advisories_{i+1:03d}.md")
        with open(fpath, "w") as f:
            f.write("# Port Advisory Bulletins\n\n")
            for adv in chunk:
                f.write(f"## {adv['port_name']} ({adv['port_code']})\n\n")
                f.write(f"**Severity:** {adv['severity']}  \n")
                f.write(f"**Issued:** {adv['issued']}  \n")
                f.write(f"**Additional Wait Days:** {adv['extra_wait_days']}  \n\n")
                f.write(f"{adv['advisory']}\n\n---\n\n")


def generate_fixed_config_files(workspace):
    """Generate task-inherent fixed configuration files."""
    os.makedirs(workspace, exist_ok=True)

    # 1. Risk thresholds
    risk_thresholds = {
        "risk_levels": {
            "CRITICAL": {"min_delay_days": 7, "description": "Severe risk of missing delivery window"},
            "HIGH": {"min_delay_days": 4, "description": "Significant risk requiring immediate action"},
            "MEDIUM": {"min_delay_days": 2, "description": "Moderate risk requiring monitoring"},
            "LOW": {"min_delay_days": 1, "description": "Minor risk, contingency planning advised"}
        },
        "priority_sort_order": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
        "notes": "Shipments with delay_days < 1 are considered on-track and excluded from alerts."
    }
    with open(os.path.join(workspace, "risk_thresholds.json"), "w") as f:
        json.dump(risk_thresholds, f, indent=2)

    # 2. Incoterms guide
    incoterms_guide = {
        "incoterms": {
            "EXW": {"full_name": "Ex Works", "risk_bearer": "buyer",
                     "transfer_point": "seller_premises",
                     "seller_responsible_for_transport": False},
            "FCA": {"full_name": "Free Carrier", "risk_bearer": "buyer",
                     "transfer_point": "named_carrier",
                     "seller_responsible_for_transport": False},
            "FOB": {"full_name": "Free On Board", "risk_bearer": "buyer",
                     "transfer_point": "port_of_origin",
                     "seller_responsible_for_transport": False},
            "CFR": {"full_name": "Cost and Freight", "risk_bearer": "buyer",
                     "transfer_point": "port_of_origin",
                     "seller_responsible_for_transport": True},
            "CIF": {"full_name": "Cost Insurance and Freight", "risk_bearer": "buyer",
                     "transfer_point": "port_of_origin",
                     "seller_responsible_for_transport": True},
            "CPT": {"full_name": "Carriage Paid To", "risk_bearer": "buyer",
                     "transfer_point": "named_carrier",
                     "seller_responsible_for_transport": True},
            "DAP": {"full_name": "Delivered at Place", "risk_bearer": "seller",
                     "transfer_point": "destination",
                     "seller_responsible_for_transport": True},
            "DDP": {"full_name": "Delivered Duty Paid", "risk_bearer": "seller",
                     "transfer_point": "destination",
                     "seller_responsible_for_transport": True}
        }
    }
    with open(os.path.join(workspace, "incoterms_guide.yaml"), "w") as f:
        yaml.dump(incoterms_guide, f, default_flow_style=False)

    # 3. Contingency playbook
    playbook = {
        "contingency_actions": {
            "CRITICAL": {
                "seller": [
                    "Arrange partial air freight for high-value cargo",
                    "Notify buyer with revised delivery schedule",
                    "Prepare penalty mitigation documentation",
                    "Engage backup carrier for transshipment"
                ],
                "buyer": [
                    "Contact carrier for priority berthing arrangement",
                    "Arrange alternative inland transport from nearest port",
                    "File pre-emptive insurance claim notification",
                    "Activate backup supplier contingency"
                ]
            },
            "HIGH": {
                "seller": [
                    "Expedite customs pre-clearance documentation",
                    "Contact port agent for priority handling",
                    "Prepare buyer notification with updated ETA"
                ],
                "buyer": [
                    "Request priority customs processing",
                    "Coordinate with freight forwarder for expedited clearance",
                    "Review contract penalty clauses"
                ]
            },
            "MEDIUM": {
                "seller": [
                    "Monitor vessel progress daily",
                    "Pre-submit customs documentation",
                    "Alert internal logistics team"
                ],
                "buyer": [
                    "Monitor vessel tracking updates",
                    "Prepare alternative delivery scheduling",
                    "Notify downstream supply chain"
                ]
            },
            "LOW": {
                "seller": [
                    "Continue standard monitoring",
                    "Ensure documentation readiness"
                ],
                "buyer": [
                    "Track shipment status",
                    "No immediate action required"
                ]
            }
        },
        "action_format": "Actions are listed in priority order. The first action listed is the most critical to execute."
    }
    with open(os.path.join(workspace, "contingency_playbook.json"), "w") as f:
        json.dump(playbook, f, indent=2)

    # 4. Port coordinates reference
    port_coords_path = os.path.join(workspace, "port_coordinates.csv")
    with open(port_coords_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["port_code", "port_name", "latitude", "longitude"])
        for p in PORTS:
            writer.writerow([p[0], p[1], p[2], p[3]])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # Reset seeds
    random.seed(SEED)
    np.random.seed(SEED)
    Faker.seed(SEED)
    global fake
    fake = Faker()
    Faker.seed(SEED)

    n = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    shipper_ids = generate_shippers(conn, n)
    vessel_rows = generate_vessels(conn, n)
    shipment_rows = generate_shipments(conn, n, vessel_rows, shipper_ids)
    generate_port_congestion(conn, n)
    generate_customs_history(conn, n)

    conn.close()

    if os.path.exists(args.workspace):
        import shutil
        shutil.rmtree(args.workspace)
    os.makedirs(args.workspace, exist_ok=True)

    generate_workspace_files(args.workspace, shipment_rows, vessel_rows, n_files)
    generate_fixed_config_files(args.workspace)


if __name__ == "__main__":
    main()
