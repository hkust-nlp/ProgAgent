#!/usr/bin/env python3
"""Generate database and workspace for yard crane deployment optimization task."""

import argparse
import sqlite3
import os
import json
import csv
import random
import math
import numpy as np
from datetime import datetime, timedelta
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 160,
    "num_workspace_files": 20,
}

# ---- Seeds ----
random.seed(42)
np.random.seed(42)
Faker.seed(42)
fake = Faker()

REFERENCE_TIME = datetime(2026, 4, 20, 8, 0, 0)
SHIFT_HOURS = 12

# ---- Terminal Configuration (constant across all scales) ----
ZONE_NAMES = ["ZONE-A", "ZONE-B", "ZONE-C", "ZONE-D", "ZONE-E"]

ZONES_CONFIG = {
    "ZONE-A": {"blocks": ["A1", "A2", "A3", "A4"],
               "berths": ["BERTH-01", "BERTH-02", "BERTH-03", "BERTH-04"]},
    "ZONE-B": {"blocks": ["B1", "B2", "B3", "B4"],
               "berths": ["BERTH-05", "BERTH-06", "BERTH-07", "BERTH-08"]},
    "ZONE-C": {"blocks": ["C1", "C2", "C3", "C4"],
               "berths": ["BERTH-09", "BERTH-10", "BERTH-11", "BERTH-12"]},
    "ZONE-D": {"blocks": ["D1", "D2", "D3", "D4"],
               "berths": ["BERTH-13", "BERTH-14", "BERTH-15", "BERTH-16"]},
    "ZONE-E": {"blocks": ["E1", "E2", "E3", "E4"],
               "berths": ["BERTH-17", "BERTH-18", "BERTH-19", "BERTH-20"]},
}

ALL_BLOCKS = [b for z in ZONE_NAMES for b in ZONES_CONFIG[z]["blocks"]]
ALL_BERTHS = [b for z in ZONE_NAMES for b in ZONES_CONFIG[z]["berths"]]

BLOCK_TO_ZONE = {}
for _z, _cfg in ZONES_CONFIG.items():
    for _b in _cfg["blocks"]:
        BLOCK_TO_ZONE[_b] = _z

BERTH_TO_ZONE = {}
for _z, _cfg in ZONES_CONFIG.items():
    for _b in _cfg["berths"]:
        BERTH_TO_ZONE[_b] = _z

# 15 cranes: 3 per zone, capacities 35 / 50 / 65 tons
CRANE_CAPACITIES = [35, 50, 65]
CRANE_DEFS = []
for _i in range(15):
    _zone_idx = _i // 3
    _cap_idx = _i % 3
    CRANE_DEFS.append({
        "crane_id": f"YC-{_i + 1:02d}",
        "zone": ZONE_NAMES[_zone_idx],
        "max_capacity_tons": CRANE_CAPACITIES[_cap_idx],
    })

CARGO_TYPES = [
    "general", "electronics", "food", "chemicals",
    "machinery", "textiles", "automotive", "pharmaceuticals",
]

VESSEL_SUFFIXES = [
    "Express", "Star", "Glory", "Fortune", "Pioneer",
    "Spirit", "Horizon", "Dawn", "Wave", "Voyager",
    "Atlas", "Phoenix", "Meridian", "Zenith", "Summit",
    "Compass", "Anchor", "Beacon", "Crest", "Tide",
]

MAINTENANCE_TYPES = [
    "hydraulic_check", "cable_inspection", "motor_service",
    "brake_adjustment", "structural_inspection", "electrical_overhaul",
    "lubrication", "sensor_calibration",
]
COMPONENTS = [
    "main_hoist", "trolley_drive", "gantry_motor", "spreader",
    "anti_sway_system", "power_cable", "control_panel", "braking_system",
]

BASE_LAT, BASE_LON = 1.2644, 103.8234


def _block_coords(block, container_id=""):
    """Deterministic lat/lon for a container in a yard block."""
    zone_idx = ZONE_NAMES.index(BLOCK_TO_ZONE[block])
    block_idx = ZONES_CONFIG[BLOCK_TO_ZONE[block]]["blocks"].index(block)
    h = hash(block + container_id) % 10000
    lat = BASE_LAT + zone_idx * 0.002 + block_idx * 0.0003 + (h % 100 - 50) * 1e-5
    lon = BASE_LON + block_idx * 0.001 + zone_idx * 0.0002 + ((h // 100) % 100 - 50) * 1e-5
    return round(lat, 6), round(lon, 6)


# ---- Berth assignment order: round-robin across zones ----
def _berth_order():
    order = []
    for slot in range(4):
        for z in ZONE_NAMES:
            order.append(ZONES_CONFIG[z]["berths"][slot])
    return order


def main(db_path, workspace):
    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    rpt = SCALE["rows_per_table"]
    nwf = SCALE["num_workspace_files"]

    # Derived counts
    n_stowage = min(max(3, nwf * 4 // 10), len(ALL_BERTHS))
    n_berthed = n_stowage
    remaining_files = nwf - n_stowage
    n_truck_manifests = max(2, remaining_files * 5 // 10)
    n_gps_logs = max(2, remaining_files - n_truck_manifests)

    n_incoming = max(2, rpt // 10)
    n_departed = max(1, rpt - n_berthed - n_incoming)

    n_containers = rpt * 3
    n_trucks = rpt
    n_maintenance = rpt

    berth_order = _berth_order()

    # Departure offsets (hours from REFERENCE_TIME) to spread across urgency tiers
    depart_offsets = [4, 8, 10, 14, 6, 18, 24, 36, 5, 11, 20, 28, 42, 48, 9, 15, 7, 22, 30, 12]

    # ==================================================================
    # TABLE: vessels
    # ==================================================================
    cur.execute("""CREATE TABLE IF NOT EXISTS vessels (
        vessel_id   TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        imo_number  TEXT,
        berth_id    TEXT,
        arrival_time       TEXT,
        departure_deadline TEXT,
        vessel_type TEXT,
        length_m    REAL,
        status      TEXT NOT NULL,
        priority_class TEXT
    )""")

    vessels = []
    berthed_vessels = []

    for i in range(n_berthed):
        vid = f"V-{i + 1:04d}"
        name = fake.last_name() + " " + VESSEL_SUFFIXES[i % len(VESSEL_SUFFIXES)]
        imo = f"IMO{9000000 + i}"
        berth = berth_order[i % len(berth_order)]
        arrival = REFERENCE_TIME - timedelta(hours=random.randint(12, 72))
        departure = REFERENCE_TIME + timedelta(hours=depart_offsets[i % len(depart_offsets)])
        v = dict(vessel_id=vid, name=name, imo_number=imo, berth_id=berth,
                 arrival_time=arrival.isoformat(), departure_deadline=departure.isoformat(),
                 vessel_type="container", length_m=round(random.uniform(200, 400), 1),
                 status="berthed", priority_class=random.choice(["A", "B", "C"]))
        vessels.append(v)
        berthed_vessels.append(v)

    for i in range(n_incoming):
        idx = n_berthed + i
        vid = f"V-{idx + 1:04d}"
        name = fake.last_name() + " " + VESSEL_SUFFIXES[(idx + 5) % len(VESSEL_SUFFIXES)]
        arrival = REFERENCE_TIME + timedelta(hours=random.randint(6, 72))
        departure = arrival + timedelta(hours=random.randint(24, 72))
        v = dict(vessel_id=vid, name=name, imo_number=f"IMO{9100000 + i}",
                 berth_id=None, arrival_time=arrival.isoformat(),
                 departure_deadline=departure.isoformat(),
                 vessel_type=random.choice(["container", "bulk"]),
                 length_m=round(random.uniform(180, 350), 1),
                 status="incoming", priority_class=random.choice(["A", "B", "C"]))
        vessels.append(v)

    for i in range(n_departed):
        idx = n_berthed + n_incoming + i
        vid = f"V-{idx + 1:04d}"
        name = fake.last_name() + " " + VESSEL_SUFFIXES[(idx + 10) % len(VESSEL_SUFFIXES)]
        departure = REFERENCE_TIME - timedelta(hours=random.randint(1, 240))
        arrival = departure - timedelta(hours=random.randint(24, 96))
        v = dict(vessel_id=vid, name=name, imo_number=f"IMO{9200000 + i}",
                 berth_id=None, arrival_time=arrival.isoformat(),
                 departure_deadline=departure.isoformat(),
                 vessel_type=random.choice(["container", "bulk", "tanker"]),
                 length_m=round(random.uniform(150, 400), 1),
                 status="departed", priority_class=random.choice(["A", "B", "C"]))
        vessels.append(v)

    for v in vessels:
        cur.execute(
            "INSERT INTO vessels VALUES (?,?,?,?,?,?,?,?,?,?)",
            (v["vessel_id"], v["name"], v["imo_number"], v["berth_id"],
             v["arrival_time"], v["departure_deadline"], v["vessel_type"],
             v["length_m"], v["status"], v["priority_class"]))

    # ==================================================================
    # TABLE: containers
    # ==================================================================
    cur.execute("""CREATE TABLE IF NOT EXISTS containers (
        container_id TEXT PRIMARY KEY,
        vessel_id    TEXT NOT NULL,
        size_ft      INTEGER NOT NULL,
        weight_tons  REAL NOT NULL,
        cargo_type   TEXT,
        is_reefer    INTEGER DEFAULT 0,
        is_hazmat    INTEGER DEFAULT 0,
        yard_block   TEXT,
        yard_slot    TEXT,
        status       TEXT NOT NULL,
        direction    TEXT NOT NULL,
        FOREIGN KEY (vessel_id) REFERENCES vessels(vessel_id)
    )""")

    n_berthed_c = int(n_containers * 0.50)
    n_incoming_c = int(n_containers * 0.20)
    n_departed_c = n_containers - n_berthed_c - n_incoming_c

    all_containers = []
    container_true_blocks = {}   # cid -> true block for NULL yard_block containers
    cidx = 0

    # --- Berthed vessel containers ---
    per_bv = n_berthed_c // max(1, n_berthed)
    bv_rem = n_berthed_c % max(1, n_berthed)
    for vi, bv in enumerate(berthed_vessels):
        nc = per_bv + (1 if vi < bv_rem else 0)
        zone = BERTH_TO_ZONE.get(bv["berth_id"], ZONE_NAMES[0])
        zone_blocks = ZONES_CONFIG[zone]["blocks"]
        for _ in range(nc):
            cidx += 1
            cid = f"CNTR-{cidx:06d}"
            size = random.choice([20, 20, 40, 40, 40])
            weight = round(random.uniform(2, 30) if size == 20 else random.uniform(5, 55), 1)
            is_reefer = 1 if random.random() < 0.12 else 0
            is_hazmat = 1 if random.random() < 0.08 else 0

            r = random.random()
            if r < 0.40:
                status, direction = "pending_discharge", "import"
            elif r < 0.65:
                status, direction = "pending_load", "export"
            else:
                status, direction = "completed", random.choice(["import", "export"])

            true_block = random.choice(zone_blocks) if random.random() < 0.75 else random.choice(ALL_BLOCKS)
            if status in ("pending_discharge", "pending_load") and random.random() < 0.15:
                yard_block, yard_slot = None, None
                container_true_blocks[cid] = true_block
            else:
                yard_block = true_block
                yard_slot = f"{random.randint(1, 50):03d}"

            all_containers.append(dict(
                container_id=cid, vessel_id=bv["vessel_id"],
                size_ft=size, weight_tons=weight, cargo_type=random.choice(CARGO_TYPES),
                is_reefer=is_reefer, is_hazmat=is_hazmat,
                yard_block=yard_block, yard_slot=yard_slot,
                status=status, direction=direction, true_block=true_block))

    # --- Incoming vessel containers ---
    inc_vessels = [v for v in vessels if v["status"] == "incoming"]
    per_iv = max(1, n_incoming_c // max(1, len(inc_vessels)))
    iv_rem = n_incoming_c % max(1, len(inc_vessels))
    for vi, iv in enumerate(inc_vessels):
        nc = per_iv + (1 if vi < iv_rem else 0)
        for _ in range(nc):
            cidx += 1
            cid = f"CNTR-{cidx:06d}"
            size = random.choice([20, 40])
            weight = round(random.uniform(2, 55 if size == 40 else 30), 1)
            blk = random.choice(ALL_BLOCKS)
            all_containers.append(dict(
                container_id=cid, vessel_id=iv["vessel_id"],
                size_ft=size, weight_tons=weight, cargo_type=random.choice(CARGO_TYPES),
                is_reefer=1 if random.random() < 0.10 else 0,
                is_hazmat=1 if random.random() < 0.05 else 0,
                yard_block=blk, yard_slot=f"{random.randint(1,50):03d}",
                status="in_transit", direction="import", true_block=blk))

    # --- Departed vessel containers ---
    dep_vessels = [v for v in vessels if v["status"] == "departed"]
    per_dv = max(1, n_departed_c // max(1, len(dep_vessels)))
    dv_rem = n_departed_c % max(1, len(dep_vessels))
    for vi, dv in enumerate(dep_vessels):
        nc = per_dv + (1 if vi < dv_rem else 0)
        if cidx >= n_containers:
            break
        for _ in range(nc):
            if cidx >= n_containers:
                break
            cidx += 1
            cid = f"CNTR-{cidx:06d}"
            size = random.choice([20, 40])
            weight = round(random.uniform(2, 55 if size == 40 else 30), 1)
            blk = random.choice(ALL_BLOCKS)
            all_containers.append(dict(
                container_id=cid, vessel_id=dv["vessel_id"],
                size_ft=size, weight_tons=weight, cargo_type=random.choice(CARGO_TYPES),
                is_reefer=1 if random.random() < 0.10 else 0,
                is_hazmat=1 if random.random() < 0.05 else 0,
                yard_block=blk, yard_slot=f"{random.randint(1,50):03d}",
                status="completed", direction=random.choice(["import", "export"]),
                true_block=blk))

    for c in all_containers:
        cur.execute(
            "INSERT INTO containers VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (c["container_id"], c["vessel_id"], c["size_ft"], c["weight_tons"],
             c["cargo_type"], c["is_reefer"], c["is_hazmat"],
             c["yard_block"], c["yard_slot"], c["status"], c["direction"]))

    berthed_vids = {bv["vessel_id"] for bv in berthed_vessels}
    actionable = [c for c in all_containers
                  if c["vessel_id"] in berthed_vids
                  and c["status"] in ("pending_discharge", "pending_load")]
    actionable_cids = {c["container_id"] for c in actionable}

    # ==================================================================
    # TABLE: truck_arrivals
    # ==================================================================
    cur.execute("""CREATE TABLE IF NOT EXISTS truck_arrivals (
        truck_id     TEXT PRIMARY KEY,
        truck_plate  TEXT NOT NULL,
        container_id TEXT,
        gate_id      TEXT,
        actual_arrival TEXT,
        status       TEXT NOT NULL,
        FOREIGN KEY (container_id) REFERENCES containers(container_id)
    )""")

    gates = [f"GATE-{g:02d}" for g in range(1, 7)]
    action_ids_list = list(actionable_cids)
    random.shuffle(action_ids_list)

    # ~35 % of actionable containers get a DB truck record
    n_act_trucks = int(len(action_ids_list) * 0.35)
    db_truck_cids = set(action_ids_list[:n_act_trucks])

    db_trucks = []
    tidx = 0

    for cid in db_truck_cids:
        tidx += 1
        status = random.choices(
            ["waiting", "processing", "completed", "no_show"],
            weights=[50, 15, 25, 10])[0]
        db_trucks.append(dict(
            truck_id=f"TRK-{tidx:05d}", truck_plate=fake.license_plate(),
            container_id=cid, gate_id=random.choice(gates),
            actual_arrival=(REFERENCE_TIME - timedelta(minutes=random.randint(5, 180))).isoformat(),
            status=status))

    # Noise trucks for non-actionable containers
    non_act_ids = [c["container_id"] for c in all_containers if c["container_id"] not in actionable_cids]
    random.shuffle(non_act_ids)
    for cid in non_act_ids[:n_trucks - len(db_trucks)]:
        tidx += 1
        db_trucks.append(dict(
            truck_id=f"TRK-{tidx:05d}", truck_plate=fake.license_plate(),
            container_id=cid, gate_id=random.choice(gates),
            actual_arrival=(REFERENCE_TIME - timedelta(hours=random.randint(1, 48))).isoformat(),
            status=random.choice(["completed", "processing", "waiting"])))

    for t in db_trucks:
        cur.execute("INSERT INTO truck_arrivals VALUES (?,?,?,?,?,?)",
                    (t["truck_id"], t["truck_plate"], t["container_id"],
                     t["gate_id"], t["actual_arrival"], t["status"]))

    # ==================================================================
    # TABLE: crane_maintenance
    # ==================================================================
    cur.execute("""CREATE TABLE IF NOT EXISTS crane_maintenance (
        log_id           TEXT PRIMARY KEY,
        crane_id         TEXT NOT NULL,
        maintenance_type TEXT,
        start_time       TEXT NOT NULL,
        end_time         TEXT NOT NULL,
        severity         TEXT,
        component        TEXT,
        status           TEXT NOT NULL
    )""")

    crane_ids = [cd["crane_id"] for cd in CRANE_DEFS]
    db_maint = []

    for i in range(n_maintenance):
        log_id = f"ML-{i + 1:05d}"
        crid = crane_ids[i % len(crane_ids)]
        mtype = random.choice(MAINTENANCE_TYPES)
        comp = random.choice(COMPONENTS)
        severity = random.choice(["minor", "moderate", "major"])

        r = random.random()
        if r < 0.75:
            end = REFERENCE_TIME - timedelta(hours=random.randint(24, 720))
            start = end - timedelta(hours=random.randint(2, 24))
            status = "completed"
        elif r < 0.90:
            start = REFERENCE_TIME - timedelta(hours=random.randint(1, 8))
            end = REFERENCE_TIME + timedelta(hours=random.randint(2, 10))
            status = "in_progress"
        else:
            start = REFERENCE_TIME + timedelta(hours=random.randint(0, 6))
            end = start + timedelta(hours=random.randint(2, 12))
            status = "scheduled"

        db_maint.append(dict(
            log_id=log_id, crane_id=crid, maintenance_type=mtype,
            start_time=start.isoformat(), end_time=end.isoformat(),
            severity=severity, component=comp, status=status))

    for m in db_maint:
        cur.execute("INSERT INTO crane_maintenance VALUES (?,?,?,?,?,?,?,?)",
                    (m["log_id"], m["crane_id"], m["maintenance_type"],
                     m["start_time"], m["end_time"], m["severity"],
                     m["component"], m["status"]))

    conn.commit()
    conn.close()

    # ==================================================================
    # WORKSPACE — Stowage Plans (one JSON per berthed vessel)
    # ==================================================================
    for bv in berthed_vessels:
        vid = bv["vessel_id"]
        vc = [c for c in all_containers if c["vessel_id"] == vid]
        discharge = sorted([c for c in vc if c["direction"] == "import"],
                           key=lambda c: c["container_id"])
        load = sorted([c for c in vc if c["direction"] == "export"],
                      key=lambda c: c["container_id"])

        discharge_plan = []
        for seq, c in enumerate(discharge, 1):
            discharge_plan.append(dict(
                container_id=c["container_id"], bay=(seq * 2) % 20 + 1,
                row=(seq % 10) + 1, tier=(seq % 6) + 1, sequence=seq))
        load_plan = []
        for seq, c in enumerate(load, 1):
            load_plan.append(dict(
                container_id=c["container_id"], bay=(seq * 2 + 1) % 20 + 1,
                row=(seq % 10) + 1, tier=(seq % 6) + 1, sequence=seq))

        with open(os.path.join(workspace, f"stowage_plan_{vid}.json"), "w") as f:
            json.dump(dict(vessel_id=vid, vessel_name=bv["name"],
                           discharge_plan=discharge_plan, load_plan=load_plan), f, indent=2)

    # ==================================================================
    # WORKSPACE — Truck Manifests (CSV)
    # ==================================================================
    shift_end = REFERENCE_TIME + timedelta(hours=SHIFT_HOURS)
    manifest_entries = []

    # Include DB trucks that match actionable containers
    for t in db_trucks:
        if t["container_id"] in actionable_cids:
            sched = (datetime.fromisoformat(t["actual_arrival"])
                     - timedelta(minutes=random.randint(0, 60)))
            manifest_entries.append(dict(
                booking_ref=f"BK-{random.randint(100000,999999)}",
                truck_plate=t["truck_plate"], container_id=t["container_id"],
                scheduled_arrival=sched.isoformat(),
                carrier_name=fake.company(),
                special_instructions=random.choice(["", "fragile", "temperature controlled", "oversized", ""])))

    # Workspace-only trucks for additional actionable containers
    no_truck_actionable = [c for c in actionable if c["container_id"] not in db_truck_cids]
    random.shuffle(no_truck_actionable)
    n_ws_only = int(len(no_truck_actionable) * 0.25)
    for c in no_truck_actionable[:n_ws_only]:
        if random.random() < 0.70:
            sched = REFERENCE_TIME + timedelta(minutes=random.randint(30, int(SHIFT_HOURS * 60) - 30))
        else:
            sched = REFERENCE_TIME + timedelta(hours=random.randint(SHIFT_HOURS + 1, 36))
        manifest_entries.append(dict(
            booking_ref=f"BK-{random.randint(100000,999999)}",
            truck_plate=fake.license_plate(), container_id=c["container_id"],
            scheduled_arrival=sched.isoformat(),
            carrier_name=fake.company(),
            special_instructions=random.choice(["", "priority", "hazmat escort", ""])))

    # Noise entries
    for _ in range(max(5, len(manifest_entries) // 3)):
        noise_cid = random.choice(non_act_ids) if non_act_ids else "CNTR-999999"
        sched = REFERENCE_TIME + timedelta(hours=random.randint(-12, 36))
        manifest_entries.append(dict(
            booking_ref=f"BK-{random.randint(100000,999999)}",
            truck_plate=fake.license_plate(), container_id=noise_cid,
            scheduled_arrival=sched.isoformat(),
            carrier_name=fake.company(), special_instructions=""))

    random.shuffle(manifest_entries)
    epm = math.ceil(len(manifest_entries) / n_truck_manifests)
    for fi in range(n_truck_manifests):
        chunk = manifest_entries[fi * epm:(fi + 1) * epm]
        with open(os.path.join(workspace, f"truck_manifest_batch_{fi + 1:03d}.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "booking_ref", "truck_plate", "container_id",
                "scheduled_arrival", "carrier_name", "special_instructions"])
            w.writeheader()
            w.writerows(chunk)

    # ==================================================================
    # WORKSPACE — GPS Position Logs (CSV)
    # ==================================================================
    gps_entries = []

    # Entries for actionable + 30 % sample of other containers
    gps_containers = list(actionable)
    others = [c for c in all_containers if c["container_id"] not in actionable_cids]
    random.shuffle(others)
    gps_containers.extend(others[:max(1, len(others) * 30 // 100)])

    for c in gps_containers:
        blk = c["true_block"]
        n_readings = random.randint(1, 3)
        for _ in range(n_readings):
            ts = REFERENCE_TIME - timedelta(minutes=random.randint(30, 720))
            lat, lon = _block_coords(blk, c["container_id"])
            gps_entries.append(dict(
                timestamp=ts.isoformat(), container_id=c["container_id"],
                latitude=lat, longitude=lon, detected_block=blk))

    # Guarantee recent entry for NULL-yard_block containers
    for cid, blk in container_true_blocks.items():
        lat, lon = _block_coords(blk, cid)
        gps_entries.append(dict(
            timestamp=(REFERENCE_TIME - timedelta(minutes=random.randint(2, 20))).isoformat(),
            container_id=cid, latitude=lat, longitude=lon, detected_block=blk))

    gps_entries.sort(key=lambda x: x["timestamp"])
    epg = math.ceil(len(gps_entries) / n_gps_logs)
    for fi in range(n_gps_logs):
        chunk = gps_entries[fi * epg:(fi + 1) * epg]
        with open(os.path.join(workspace, f"gps_position_log_{fi + 1:03d}.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "timestamp", "container_id", "latitude", "longitude", "detected_block"])
            w.writeheader()
            w.writerows(chunk)

    # ==================================================================
    # WORKSPACE — Fixed configuration files
    # ==================================================================

    # terminal_layout.json
    layout = {"zones": {}, "block_zone_map": BLOCK_TO_ZONE}
    for z, cfg in ZONES_CONFIG.items():
        layout["zones"][z] = {"blocks": cfg["blocks"], "berths": cfg["berths"]}
    with open(os.path.join(workspace, "terminal_layout.json"), "w") as f:
        json.dump(layout, f, indent=2)

    # crane_specs.yaml
    with open(os.path.join(workspace, "crane_specs.yaml"), "w") as f:
        yaml.dump({"cranes": CRANE_DEFS}, f, default_flow_style=False, sort_keys=False)

    # priority_rules.yaml
    priority_rules = {
        "scoring": {
            "deadline_tiers": [
                {"max_hours": 6, "score": 40},
                {"max_hours": 12, "score": 30},
                {"max_hours": 24, "score": 20},
                {"max_hours": 48, "score": 10},
            ],
            "truck_waiting_bonus": 20,
            "hazmat_bonus": 15,
            "reefer_bonus": 10,
            "sequence_weight": 15,
            "sequence_formula": "max(0, sequence_weight - (sequence_number - 1))",
        },
        "crane_rules": {"maintenance_buffer_minutes": 30},
        "duration_estimates": {"time_20ft_minutes": 4, "time_40ft_minutes": 6},
        "ordering": {
            "primary": "urgency_score descending",
            "secondary": "departure_deadline ascending",
            "tertiary": "container_id ascending",
        },
        "crane_selection": {
            "prefer": "crane with fewest current assignments",
            "tiebreaker": "crane_id ascending",
        },
    }
    with open(os.path.join(workspace, "priority_rules.yaml"), "w") as f:
        yaml.dump(priority_rules, f, default_flow_style=False, sort_keys=False)

    # shift_config.json
    with open(os.path.join(workspace, "shift_config.json"), "w") as f:
        json.dump({
            "shift_start": REFERENCE_TIME.isoformat(),
            "shift_end": (REFERENCE_TIME + timedelta(hours=SHIFT_HOURS)).isoformat(),
        }, f, indent=2)

    # maintenance_schedule.yaml  (workspace-only scheduled maintenance)
    ws_maint = []
    ws_crane_sample = random.sample(crane_ids, min(5, len(crane_ids)))
    for i, crid in enumerate(ws_crane_sample):
        if i < 2:  # first two overlap with the shift
            start = REFERENCE_TIME + timedelta(hours=random.randint(1, 6))
            end = start + timedelta(hours=random.randint(3, 8))
        else:
            start = REFERENCE_TIME + timedelta(hours=random.randint(24, 168))
            end = start + timedelta(hours=random.randint(2, 6))
        ws_maint.append(dict(
            crane_id=crid, maintenance_type=random.choice(MAINTENANCE_TYPES),
            start_time=start.isoformat(), end_time=end.isoformat()))

    with open(os.path.join(workspace, "maintenance_schedule.yaml"), "w") as f:
        yaml.dump({"scheduled_maintenance": ws_maint}, f,
                  default_flow_style=False, sort_keys=False)

    # operational_policy.md
    with open(os.path.join(workspace, "operational_policy.md"), "w") as f:
        f.write("""# Terminal Operational Policy

## Container Handling Priorities

Hazardous materials containers require dedicated safety clearance and must be handled with appropriate equipment certification. Reefer (refrigerated) containers must maintain cold chain integrity and should be connected to yard power within 30 minutes of discharge.

## Vessel Service Standards

Vessels are classified into priority classes A, B, and C. Class A vessels receive preferential crane allocation during peak periods. All vessels must be served within their contracted departure windows.

## Crane Operation Guidelines

Yard cranes must not exceed their rated lifting capacity under any circumstances. Cranes undergoing maintenance or within the pre-maintenance buffer window are excluded from all operations. Load balancing across cranes in the same zone is preferred to minimize mechanical wear.

## Truck Gate Coordination

Trucks waiting at gates should be factored into container prioritization to reduce gate congestion and demurrage charges. Pre-registered truck appointments visible in the advance booking system carry the same priority weight as trucks physically present at gates, provided the truck has not already been marked as completed or as a no-show in the gate system.
""")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db_path", required=True)
    p.add_argument("--workspace", required=True)
    main(p.parse_args().db_path, p.parse_args().workspace)
