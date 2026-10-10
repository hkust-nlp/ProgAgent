import argparse
import os
import sqlite3
import json
import csv
import random
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta
import yaml


SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 24,
}

# ── Seeds ──────────────────────────────────────────────────────────────
random.seed(42)
np.random.seed(42)
Faker.seed(42)
fake = Faker()

# ── Constants ──────────────────────────────────────────────────────────
PRODUCTION_START = datetime(2026, 3, 2)
PRODUCTION_DAYS = 84  # 12 weeks

CATEGORIES = ["Camera", "Lighting", "Sound", "Grip", "Special_Effects"]

EQUIPMENT_TEMPLATES = {
    "Camera": [
        "ARRI Alexa 35", "RED V-Raptor", "Sony Venice 2", "Canon C500 II",
        "Blackmagic URSA 12K", "ARRI Amira", "RED Komodo", "Sony FX9",
        "Canon R5C", "Panasonic Varicam", "ARRI Alexa Mini LF", "RED Ranger",
        "Sony FX6", "Canon C300 III", "Blackmagic Pocket 6K Pro",
    ],
    "Lighting": [
        "ARRI SkyPanel S60", "Aputure 600d Pro", "Litepanels Gemini 2x1",
        "Kino Flo Celeb 450", "ARRI M18 HMI", "Nanlite Forza 720",
        "Creamsource Vortex8", "Dedolight DLED7", "Quasar Science Rainbow",
        "Astera Titan Tube", "ARRI SkyPanel S120", "Aputure 300d II",
        "Kino Flo Select 30", "ARRI M40 HMI", "Nanlite Forza 500",
    ],
    "Sound": [
        "Sennheiser MKH 416", "Schoeps CMIT 5U", "Sound Devices 888",
        "Lectrosonics SRc", "DPA 4017B", "Rode NTG5", "Zoom F8n Pro",
        "Wisycom MCR54", "Sanken COS-11D", "Audio Ltd A10-TX",
        "Sennheiser MKH 8060", "Sound Devices 833", "Lectrosonics DSQD",
        "DPA 4018", "Rode NTG3",
    ],
    "Grip": [
        "Chapman PeeWee IV Dolly", "Fisher 11 Dolly", "Matthews 40x40 Butterfly",
        "Avenger C-Stand Kit", "Dana Dolly Portable", "Steadicam M-2",
        "DJI Ronin 2 Gimbal", "Losmandy Spider Dolly", "Matthews Mini Jib",
        "Noga Articulating Arm", "Chapman Super PeeWee", "Fisher 10 Dolly",
        "Matthews 20x20 Overhead", "Cardellini Clamp Set", "Kupo C-Stand Kit",
    ],
    "Special_Effects": [
        "Ultratec Radiance Hazer", "Look Solutions Cryo Fog", "Reel EFX DF-50",
        "Aqua FX Rain Bar", "Wind Machine 36in", "Martin JEM Glaciator",
        "Smoke Factory Captain D", "Reel EFX Snow Machine", "SFX Lightning Gen",
        "Ultratec LSG MKII", "Look Solutions Unique 2.1", "Reel EFX Fan Fogger",
        "Aqua FX Mist Maker", "Wind Machine 48in", "Martin JEM ZR44",
    ],
}

RENTAL_HOUSES = [
    "CineGear_Pro", "LensWorks_Rentals", "StageCraft_Supply",
    "FilmTech_Depot", "ProMotion_Gear",
]

DAILY_RATE_RANGES = {
    "Camera": (200, 600),
    "Lighting": (50, 200),
    "Sound": (40, 150),
    "Grip": (30, 100),
    "Special_Effects": (100, 350),
}

LOCATIONS = [
    "Stage A - Main Interior", "Stage B - Office Set", "Stage C - Hospital Wing",
    "Stage D - Green Screen", "Backlot - Urban Street", "Backlot - Park Gardens",
    "Location - Beach House Ext", "Location - Downtown Core",
    "Location - Mountain Road", "Location - Industrial Warehouse",
    "Location - Suburban Home", "Location - Rooftop Terrace",
]


# ═══════════════════════════════════════════════════════════════════════
#  Database creation
# ═══════════════════════════════════════════════════════════════════════

def create_database(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS scene_equipment")
    c.execute("DROP TABLE IF EXISTS rental_agreements")
    c.execute("DROP TABLE IF EXISTS scenes")
    c.execute("DROP TABLE IF EXISTS equipment")

    c.execute("""CREATE TABLE equipment (
        equipment_id INTEGER PRIMARY KEY,
        name         TEXT NOT NULL,
        category     TEXT NOT NULL,
        weight_kg    REAL
    )""")

    c.execute("""CREATE TABLE scenes (
        scene_id      INTEGER PRIMARY KEY,
        scene_name    TEXT NOT NULL,
        shoot_date    TEXT NOT NULL,
        duration_days INTEGER NOT NULL,
        location      TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE scene_equipment (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        scene_id     INTEGER NOT NULL,
        equipment_id INTEGER NOT NULL,
        FOREIGN KEY (scene_id)     REFERENCES scenes(scene_id),
        FOREIGN KEY (equipment_id) REFERENCES equipment(equipment_id)
    )""")

    c.execute("""CREATE TABLE rental_agreements (
        agreement_id INTEGER PRIMARY KEY AUTOINCREMENT,
        equipment_id INTEGER NOT NULL,
        rental_house TEXT NOT NULL,
        start_date   TEXT NOT NULL,
        end_date     TEXT NOT NULL,
        daily_rate   REAL NOT NULL,
        FOREIGN KEY (equipment_id) REFERENCES equipment(equipment_id)
    )""")

    conn.commit()
    return conn


# ═══════════════════════════════════════════════════════════════════════
#  Data generators
# ═══════════════════════════════════════════════════════════════════════

def generate_equipment(conn):
    n = SCALE["rows_per_table"]
    items_per_cat = n // len(CATEGORIES)
    remainder = n % len(CATEGORIES)

    rows = []
    eid = 1
    for ci, cat in enumerate(CATEGORIES):
        count = items_per_cat + (1 if ci < remainder else 0)
        templates = EQUIPMENT_TEMPLATES[cat]
        for i in range(count):
            base_name = templates[i % len(templates)]
            unit_num = i // len(templates) + 1
            name = base_name if unit_num == 1 else f"{base_name} Unit {unit_num}"
            weight = round(random.uniform(2.0, 45.0), 1)
            rows.append((eid, name, cat, weight))
            eid += 1

    conn.executemany("INSERT INTO equipment VALUES (?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_scenes(conn):
    n = SCALE["rows_per_table"]
    rows = []
    for sid in range(1, n + 1):
        day_offset = random.randint(0, PRODUCTION_DAYS - 5)
        shoot_date = (PRODUCTION_START + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        duration = random.choice([1, 1, 2, 2, 2, 3, 3, 4])
        location = random.choice(LOCATIONS)
        scene_name = f"SC-{sid:03d} {fake.catch_phrase()}"
        rows.append((sid, scene_name, shoot_date, duration, location))

    conn.executemany("INSERT INTO scenes VALUES (?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_scene_equipment(conn, scenes, equipment):
    equipment_ids = [e[0] for e in equipment]
    scene_ids = [s[0] for s in scenes]

    assignments = set()
    used_equipment = set()

    for scene in scenes:
        sid = scene[0]
        n_equip = random.randint(3, min(7, len(equipment_ids)))
        selected = random.sample(equipment_ids, n_equip)
        for eid in selected:
            assignments.add((sid, eid))
            used_equipment.add(eid)

    for eid in equipment_ids:
        if eid not in used_equipment:
            sid = random.choice(scene_ids)
            assignments.add((sid, eid))

    rows = sorted(assignments)
    conn.executemany(
        "INSERT INTO scene_equipment (scene_id, equipment_id) VALUES (?,?)", rows
    )
    conn.commit()
    return rows


def generate_rental_agreements(conn, equipment, scenes, scene_equip):
    scene_dict = {s[0]: s for s in scenes}

    equip_scenes = {}
    for sid, eid in scene_equip:
        equip_scenes.setdefault(eid, []).append(sid)

    rows = []
    for e in equipment:
        eid, _, cat, _ = e
        sids = equip_scenes.get(eid, [])
        if not sids:
            continue

        scene_dates = []
        for sid in sids:
            s = scene_dict[sid]
            start = datetime.strptime(s[2], "%Y-%m-%d")
            end = start + timedelta(days=s[3] - 1)
            scene_dates.append((start, end))

        first_date = min(d[0] for d in scene_dates)
        last_date = max(d[1] for d in scene_dates)

        rental_start = first_date - timedelta(days=random.randint(2, 7))

        idx = eid % 10
        if idx < 5:      # 50 % — big gap
            extra = random.randint(15, 35)
        elif idx < 8:    # 30 % — marginal
            extra = random.randint(5, 12)
        else:            # 20 % — tiny gap
            extra = random.randint(0, 3)

        rental_end = last_date + timedelta(days=extra)
        max_end = PRODUCTION_START + timedelta(days=PRODUCTION_DAYS + 14)
        if rental_end > max_end:
            rental_end = max_end

        rate_lo, rate_hi = DAILY_RATE_RANGES[cat]
        daily_rate = round(random.uniform(rate_lo, rate_hi), 2)
        rental_house = RENTAL_HOUSES[eid % len(RENTAL_HOUSES)]

        rows.append((
            eid, rental_house,
            rental_start.strftime("%Y-%m-%d"),
            rental_end.strftime("%Y-%m-%d"),
            daily_rate,
        ))

    conn.executemany(
        "INSERT INTO rental_agreements "
        "(equipment_id, rental_house, start_date, end_date, daily_rate) "
        "VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    return rows


# ═══════════════════════════════════════════════════════════════════════
#  Workspace generation
# ═══════════════════════════════════════════════════════════════════════

def generate_workspace(workspace, scenes, equipment, scene_equip):
    os.makedirs(workspace, exist_ok=True)

    n_files = SCALE["num_workspace_files"]
    n_schedule = n_files // 2
    n_condition = n_files - n_schedule

    # ── Schedule-block CSVs ────────────────────────────────────────────
    scene_list = list(scenes)
    random.shuffle(scene_list)
    chunks = np.array_split(range(len(scene_list)), n_schedule)

    for i, chunk_idx in enumerate(chunks):
        fp = os.path.join(workspace, f"schedule_block_{i + 1:02d}.csv")
        with open(fp, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["scene_id", "priority", "weather_dependent"])
            for idx in chunk_idx:
                scene = scene_list[int(idx)]
                sid = scene[0]
                location = scene[4]
                is_exterior = ("Location" in location) or ("Backlot" in location)
                weather_dep = is_exterior and random.random() < 0.6
                priority = random.choices(
                    ["A", "B", "C"], weights=[0.25, 0.45, 0.30]
                )[0]
                writer.writerow([sid, priority, weather_dep])

    # ── Condition-report JSONs ─────────────────────────────────────────
    equip_list = list(equipment)
    random.shuffle(equip_list)
    equip_chunks = np.array_split(range(len(equip_list)), n_condition)

    for i, chunk_idx in enumerate(equip_chunks):
        fp = os.path.join(workspace, f"condition_report_{i + 1:02d}.json")
        reports = []
        for idx in chunk_idx:
            e = equip_list[int(idx)]
            eid = e[0]
            n_assess = random.randint(3, 5)

            if eid % 5 == 0:  # ~20 % bad condition
                ratings = [round(random.uniform(1.0, 2.8), 1)
                           for _ in range(n_assess)]
            else:
                ratings = [round(random.uniform(3.0, 5.0), 1)
                           for _ in range(n_assess)]

            for rating in ratings:
                adate = (
                    PRODUCTION_START + timedelta(days=random.randint(0, PRODUCTION_DAYS))
                ).strftime("%Y-%m-%d")
                reports.append({
                    "equipment_id": eid,
                    "assessment_date": adate,
                    "condition_rating": rating,
                    "inspector": fake.name(),
                    "notes": random.choice([
                        "Normal wear", "Good condition", "Minor scratches",
                        "Needs cleaning", "Slight damage noted", "Excellent shape",
                        "Overheating observed", "Lens fog detected", "Cable fraying",
                        "Battery degradation", "Functioning normally",
                        "Calibration needed",
                    ]),
                })

        with open(fp, "w") as f:
            json.dump(reports, f, indent=2)

    # ── Fixed: contingency_policy.yaml ─────────────────────────────────
    policy = {
        "base_buffer_days": {
            "Camera": 3,
            "Lighting": 2,
            "Sound": 2,
            "Grip": 1,
            "Special_Effects": 4,
        },
        "weather_dependent_addition": 2,
        "high_priority_addition": 1,
    }
    with open(os.path.join(workspace, "contingency_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False)

    # ── Fixed: rate_cards.json ─────────────────────────────────────────
    fee_pcts = [0.05, 0.08, 0.03, 0.10, 0.06]
    rate_cards = {
        rh: {"early_return_fee_pct": fee_pcts[i]}
        for i, rh in enumerate(RENTAL_HOUSES)
    }
    with open(os.path.join(workspace, "rate_cards.json"), "w") as f:
        json.dump(rate_cards, f, indent=2)

    # ── Fixed: return_eligibility.md ───────────────────────────────────
    rules = (
        "# Equipment Early Return Eligibility Rules\n\n"
        "Minimum average condition rating required: 3.0\n\n"
        "Minimum rental period (days): 7\n\n"
        "Equipment must have at least one recorded condition assessment "
        "to be eligible for early return.\n\n"
        "All early return requests must be submitted at least 24 hours "
        "before the adjusted return date.\n"
    )
    with open(os.path.join(workspace, "return_eligibility.md"), "w") as f:
        f.write(rules)


# ═══════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    conn = create_database(args.db_path)
    equipment = generate_equipment(conn)
    scenes = generate_scenes(conn)
    scene_equip = generate_scene_equipment(conn, scenes, equipment)
    generate_rental_agreements(conn, equipment, scenes, scene_equip)
    generate_workspace(args.workspace, scenes, equipment, scene_equip)
    conn.close()
    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")


if __name__ == "__main__":
    main()
