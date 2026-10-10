import argparse
import os
import sqlite3
import json
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 160,
    "num_workspace_files": 40,
}

TRADES = [
    "Electrical", "Plumbing", "HVAC", "Concrete", "Steel Erection",
    "Roofing", "Drywall", "Painting", "Flooring", "Landscaping",
    "Fire Protection", "Masonry", "Glazing", "Carpentry", "Waterproofing",
    "Insulation", "Demolition", "Excavation", "Paving", "Elevator Installation",
    "Tiling", "Plastering", "Fencing", "Scaffolding", "Signage",
    "Acoustic Ceiling", "Window Installation", "Siding", "Grading", "Piling",
]

WORK_DESCRIPTIONS = {
    "Electrical": ["Main panel installation", "Branch circuit wiring", "Lighting fixture installation", "Emergency power systems", "Fire alarm wiring"],
    "Plumbing": ["Water supply rough-in", "Drainage system installation", "Fixture installation", "Hot water system", "Backflow prevention"],
    "HVAC": ["Ductwork installation", "AHU installation", "Chiller piping", "Controls and BMS wiring", "Exhaust fan installation"],
    "Concrete": ["Foundation pouring", "Slab on grade", "Column forming and pouring", "Retaining wall construction", "Concrete finishing"],
    "Steel Erection": ["Column erection", "Beam installation", "Joist and deck placement", "Connection bolting", "Structural bracing"],
    "Roofing": ["Membrane application", "Flashing installation", "Insulation board placement", "Drainage system", "Roof penetration sealing"],
    "Drywall": ["Metal framing", "Board installation", "Taping and finishing", "Fireproofing assembly", "Acoustic treatment"],
    "Painting": ["Surface preparation", "Primer application", "Finish coat application", "Specialty coating", "Touch-up and punch list"],
    "Flooring": ["Subfloor preparation", "Tile installation", "Carpet installation", "Epoxy floor coating", "Hardwood installation"],
    "Landscaping": ["Grading and soil prep", "Irrigation system", "Planting and seeding", "Hardscape installation", "Landscape lighting"],
    "Fire Protection": ["Sprinkler main installation", "Branch line installation", "Head installation", "Alarm valve assembly", "Fire pump installation"],
    "Masonry": ["Block wall construction", "Brick veneer installation", "Stone cladding", "Mortar joint finishing", "Masonry reinforcement"],
    "Glazing": ["Curtain wall framing", "Glass panel installation", "Sealant application", "Storefront assembly", "Skylight installation"],
    "Carpentry": ["Rough framing", "Finish carpentry", "Cabinet installation", "Door and hardware", "Millwork installation"],
    "Waterproofing": ["Below-grade membrane", "Above-grade coating", "Joint sealant application", "Drainage board install", "Vapor barrier"],
    "Insulation": ["Wall cavity insulation", "Roof insulation", "Pipe insulation", "Acoustic insulation", "Spray foam application"],
    "Demolition": ["Interior demolition", "Structural demolition", "Hazmat abatement", "Selective demolition", "Debris removal"],
    "Excavation": ["Site excavation", "Trench digging", "Backfill and compaction", "Rock removal", "Dewatering"],
    "Paving": ["Base course installation", "Asphalt paving", "Concrete paving", "Curb and gutter", "Striping and marking"],
    "Elevator Installation": ["Shaft preparation", "Rail installation", "Car assembly", "Controller installation", "Final adjustment and testing"],
    "Tiling": ["Floor tile layout", "Wall tile installation", "Grout application", "Waterproof membrane", "Mosaic installation"],
    "Plastering": ["Base coat application", "Finish plaster coat", "Texture application", "Patching and repair", "Venetian plaster"],
    "Fencing": ["Post installation", "Panel attachment", "Gate installation", "Security fencing", "Decorative fence"],
    "Scaffolding": ["Scaffold erection", "Platform installation", "Safety netting", "Scaffold modification", "Dismantling"],
    "Signage": ["Exterior signage", "Interior wayfinding", "Safety signage", "Illuminated signs", "ADA signage"],
    "Acoustic Ceiling": ["Grid installation", "Tile placement", "Specialty panel", "Access panel install", "Cloud ceiling"],
    "Window Installation": ["Frame installation", "Glass fitting", "Hardware install", "Weathersealing", "Screen installation"],
    "Siding": ["Substrate preparation", "Panel installation", "Trim and flashing", "Corner treatment", "Soffit installation"],
    "Grading": ["Rough grading", "Fine grading", "Slope stabilization", "Drainage swale", "Compaction testing"],
    "Piling": ["Pile driving", "Pile cap construction", "Load testing", "Sheet piling", "Micropile installation"],
}

MATERIALS = {
    "Electrical": ["Copper wire", "Conduit", "Circuit breakers", "Junction boxes", "Light fixtures", "Switches", "Outlets"],
    "Plumbing": ["PVC pipe", "Copper pipe", "Fittings", "Valves", "Fixtures", "Water heater", "Drain assemblies"],
    "HVAC": ["Ductwork", "AHU units", "Refrigerant", "Thermostats", "Dampers", "Filters", "Insulation wrap"],
    "Concrete": ["Ready-mix concrete", "Rebar", "Form lumber", "Form ties", "Curing compound", "Expansion joints"],
    "Steel Erection": ["Steel beams", "Steel columns", "Bolts", "Welding rods", "Shear studs", "Base plates"],
    "Roofing": ["Roofing membrane", "Insulation board", "Flashing material", "Fasteners", "Sealant", "Gravel"],
    "Drywall": ["Gypsum board", "Metal studs", "Joint compound", "Tape", "Corner bead", "Screws"],
    "Painting": ["Primer", "Finish paint", "Brushes and rollers", "Drop cloths", "Masking tape", "Thinner"],
    "Flooring": ["Floor tiles", "Adhesive", "Grout", "Underlayment", "Carpet rolls", "Transition strips"],
    "Landscaping": ["Topsoil", "Mulch", "Plants", "Irrigation pipe", "Sod", "Landscape fabric"],
}

INSPECTORS = [
    "Robert Chen, PE", "Sarah Mitchell, AIA", "James O'Brien, RA",
    "Dr. Patricia Huang", "Michael Torres, SE", "Angela Davis, CBO",
    "Thomas Park, PE", "Linda Nakamura, AIA", "William Foster, RA",
    "Karen Patel, PE",
]


def create_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subcontractors (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            trade TEXT NOT NULL,
            license_number TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            contract_value REAL NOT NULL,
            bond_amount REAL NOT NULL,
            start_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schedule_items (
            id INTEGER PRIMARY KEY,
            subcontractor_id INTEGER NOT NULL,
            item_code TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL,
            planned_start TEXT NOT NULL,
            planned_end TEXT NOT NULL,
            budgeted_amount REAL NOT NULL,
            unit_of_measure TEXT,
            planned_quantity REAL,
            FOREIGN KEY (subcontractor_id) REFERENCES subcontractors(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_applications (
            id INTEGER PRIMARY KEY,
            subcontractor_id INTEGER NOT NULL,
            schedule_item_id INTEGER NOT NULL,
            application_number TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            claimed_completion_pct REAL NOT NULL,
            claimed_amount REAL NOT NULL,
            submission_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            FOREIGN KEY (subcontractor_id) REFERENCES subcontractors(id),
            FOREIGN KEY (schedule_item_id) REFERENCES schedule_items(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS material_deliveries (
            id INTEGER PRIMARY KEY,
            schedule_item_id INTEGER NOT NULL,
            subcontractor_id INTEGER NOT NULL,
            po_number TEXT NOT NULL,
            material_description TEXT NOT NULL,
            quantity REAL NOT NULL,
            unit_price REAL NOT NULL,
            total_amount REAL NOT NULL,
            delivery_date TEXT NOT NULL,
            received_by TEXT NOT NULL,
            FOREIGN KEY (schedule_item_id) REFERENCES schedule_items(id),
            FOREIGN KEY (subcontractor_id) REFERENCES subcontractors(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inspection_reports (
            id INTEGER PRIMARY KEY,
            schedule_item_id INTEGER NOT NULL,
            inspection_date TEXT NOT NULL,
            inspector_name TEXT NOT NULL,
            verified_completion_pct REAL NOT NULL,
            deficiency_flag INTEGER NOT NULL DEFAULT 0,
            deficiency_description TEXT,
            overall_rating TEXT NOT NULL,
            sign_off_status TEXT NOT NULL DEFAULT 'pending',
            FOREIGN KEY (schedule_item_id) REFERENCES schedule_items(id)
        )
    """)


def generate_subcontractors(cursor, fake, num):
    subs = []
    used_trades = []
    for i in range(1, num + 1):
        trade = TRADES[(i - 1) % len(TRADES)]
        used_trades.append(trade)
        name = fake.company()
        license_no = f"LIC-{fake.unique.random_number(digits=6, fix_len=True)}"
        phone = fake.phone_number()
        email = fake.company_email()
        contract_value = round(np.random.uniform(50000, 500000), 2)
        bond_amount = round(contract_value * np.random.uniform(0.08, 0.15), 2)
        month = np.random.randint(1, 7)
        day = np.random.randint(1, 28)
        start_date = f"2024-{month:02d}-{day:02d}"
        status = "active"
        subs.append((i, name, trade, license_no, phone, email, contract_value, bond_amount, start_date, status))
    cursor.executemany(
        "INSERT INTO subcontractors VALUES (?,?,?,?,?,?,?,?,?,?)", subs
    )
    return subs


def generate_schedule_items(cursor, fake, subs, num):
    items = []
    item_id = 1
    # Distribute items across subcontractors, at least 2 per sub
    items_per_sub = max(2, num // len(subs))
    remaining = num - items_per_sub * len(subs)

    for sub in subs:
        sub_id = sub[0]
        trade = sub[2]
        descs = WORK_DESCRIPTIONS.get(trade, ["General construction work", "Site preparation", "Installation", "Finishing", "Cleanup"])
        n_items = items_per_sub + (1 if remaining > 0 else 0)
        if remaining > 0:
            remaining -= 1

        for j in range(n_items):
            item_code = f"SI-{item_id:03d}"
            desc = descs[j % len(descs)]
            # Stagger start dates
            start_offset = np.random.randint(0, 180)
            duration = np.random.randint(30, 120)
            start_date = pd.Timestamp("2024-01-15") + pd.Timedelta(days=int(start_offset))
            end_date = start_date + pd.Timedelta(days=int(duration))
            budgeted_amount = round(np.random.uniform(10000, 80000), 2)
            units = np.random.choice(["sqft", "linear ft", "cubic yd", "each", "lump sum", "tons"])
            qty = round(np.random.uniform(50, 500), 1)
            items.append((item_id, sub_id, item_code, desc, str(start_date.date()), str(end_date.date()), budgeted_amount, units, qty))
            item_id += 1

    # Ensure we have at least num items
    while len(items) < num:
        sub = subs[len(items) % len(subs)]
        sub_id = sub[0]
        trade = sub[2]
        descs = WORK_DESCRIPTIONS.get(trade, ["Additional work"])
        item_code = f"SI-{item_id:03d}"
        desc = descs[len(items) % len(descs)] + " (additional)"
        start_offset = np.random.randint(0, 180)
        duration = np.random.randint(30, 120)
        start_date = pd.Timestamp("2024-01-15") + pd.Timedelta(days=int(start_offset))
        end_date = start_date + pd.Timedelta(days=int(duration))
        budgeted_amount = round(np.random.uniform(10000, 80000), 2)
        units = np.random.choice(["sqft", "linear ft", "cubic yd", "each", "lump sum"])
        qty = round(np.random.uniform(50, 500), 1)
        items.append((item_id, sub_id, item_code, desc, str(start_date.date()), str(end_date.date()), budgeted_amount, units, qty))
        item_id += 1

    cursor.executemany(
        "INSERT INTO schedule_items VALUES (?,?,?,?,?,?,?,?,?)", items
    )
    return items


def generate_payment_applications(cursor, fake, subs, items, num, num_pending):
    apps = []
    # First num_pending are 'pending', rest are other statuses
    # Assign pending apps to distinct schedule items
    pending_item_indices = np.random.choice(len(items), size=min(num_pending, len(items)), replace=False)
    pending_item_indices = sorted(pending_item_indices)

    used_item_ids = set()
    app_id = 1

    # Generate pending applications
    for idx in pending_item_indices:
        item = items[idx]
        item_id = item[0]
        sub_id = item[1]
        used_item_ids.add(item_id)
        app_number = f"PA-{app_id:04d}"
        # Period around mid-project
        period_start_offset = np.random.randint(60, 200)
        period_start = pd.Timestamp("2024-01-01") + pd.Timedelta(days=int(period_start_offset))
        period_end = period_start + pd.Timedelta(days=30)
        claimed_pct = round(np.random.uniform(25, 85), 1)
        budgeted = item[6]
        claimed_amount = round(budgeted * claimed_pct / 100, 2)
        submission_date = str((period_end + pd.Timedelta(days=np.random.randint(1, 5))).date())
        apps.append((app_id, sub_id, item_id, app_number, str(period_start.date()), str(period_end.date()),
                      claimed_pct, claimed_amount, submission_date, "pending"))
        app_id += 1

    # Generate non-pending applications to fill up to num
    other_statuses = ["approved", "paid", "rejected"]
    available_items = [it for it in items if it[0] not in used_item_ids]
    if not available_items:
        available_items = list(items)

    while len(apps) < num:
        item = available_items[len(apps) % len(available_items)]
        item_id = item[0]
        sub_id = item[1]
        app_number = f"PA-{app_id:04d}"
        period_start_offset = np.random.randint(30, 250)
        period_start = pd.Timestamp("2024-01-01") + pd.Timedelta(days=int(period_start_offset))
        period_end = period_start + pd.Timedelta(days=30)
        claimed_pct = round(np.random.uniform(20, 95), 1)
        budgeted = item[6]
        claimed_amount = round(budgeted * claimed_pct / 100, 2)
        submission_date = str((period_end + pd.Timedelta(days=np.random.randint(1, 5))).date())
        status = np.random.choice(other_statuses, p=[0.5, 0.3, 0.2])
        apps.append((app_id, sub_id, item_id, app_number, str(period_start.date()), str(period_end.date()),
                      claimed_pct, claimed_amount, submission_date, status))
        app_id += 1

    cursor.executemany(
        "INSERT INTO payment_applications VALUES (?,?,?,?,?,?,?,?,?,?)", apps
    )
    return apps


def generate_material_deliveries(cursor, fake, items, subs, num):
    deliveries = []
    del_id = 1
    # Ensure at least one delivery per schedule item for the first num items, then pad
    sub_map = {s[0]: s for s in subs}
    for i, item in enumerate(items):
        if del_id > num and i >= num:
            break
        item_id = item[0]
        sub_id = item[1]
        trade = sub_map[sub_id][2]
        mats = MATERIALS.get(trade, ["General supplies", "Fasteners", "Adhesive", "Filler", "Sealant"])
        material = mats[i % len(mats)]
        po_number = f"PO-{fake.unique.random_number(digits=5, fix_len=True)}"
        qty = round(np.random.uniform(10, 200), 1)
        unit_price = round(np.random.uniform(5, 150), 2)
        total = round(qty * unit_price, 2)
        delivery_offset = np.random.randint(60, 250)
        delivery_date = str((pd.Timestamp("2024-01-01") + pd.Timedelta(days=int(delivery_offset))).date())
        received_by = fake.name()
        deliveries.append((del_id, item_id, sub_id, po_number, material, qty, unit_price, total, delivery_date, received_by))
        del_id += 1

    # Pad to reach num
    while len(deliveries) < num:
        item = items[len(deliveries) % len(items)]
        item_id = item[0]
        sub_id = item[1]
        trade = sub_map[sub_id][2]
        mats = MATERIALS.get(trade, ["General supplies", "Fasteners", "Adhesive"])
        material = mats[len(deliveries) % len(mats)]
        po_number = f"PO-{fake.unique.random_number(digits=5, fix_len=True)}"
        qty = round(np.random.uniform(10, 200), 1)
        unit_price = round(np.random.uniform(5, 150), 2)
        total = round(qty * unit_price, 2)
        delivery_offset = np.random.randint(60, 250)
        delivery_date = str((pd.Timestamp("2024-01-01") + pd.Timedelta(days=int(delivery_offset))).date())
        received_by = fake.name()
        deliveries.append((del_id, item_id, sub_id, po_number, material, qty, unit_price, total, delivery_date, received_by))
        del_id += 1

    cursor.executemany(
        "INSERT INTO material_deliveries VALUES (?,?,?,?,?,?,?,?,?,?)", deliveries
    )
    return deliveries


def generate_inspection_reports(cursor, fake, items, num, pending_apps):
    reports = []
    report_id = 1
    # Pending apps' schedule items get specific inspection reports
    pending_item_ids = {app[2] for app in pending_apps}
    ratings = ["Satisfactory", "Good", "Excellent", "Needs Improvement", "Unsatisfactory"]

    # Generate reports for pending items first
    for app in pending_apps:
        item_id = app[2]
        claimed_pct = app[6]
        # verified_pct varies: sometimes lower, sometimes equal, rarely higher
        delta = np.random.choice([-15, -10, -5, 0, 0, 5], p=[0.1, 0.2, 0.2, 0.25, 0.15, 0.1])
        verified_pct = round(max(5, min(100, claimed_pct + delta)), 1)
        # Some have deficiencies
        deficiency = int(np.random.random() < 0.3)
        deficiency_desc = ""
        if deficiency:
            deficiency_desc = np.random.choice([
                "Minor cracks observed in finished surface",
                "Alignment deviation exceeding 5mm tolerance",
                "Incomplete fire-stopping at penetrations",
                "Surface finish below specified standards",
                "Missing fasteners at connection points",
                "Inadequate drainage slope in installed section",
            ])
        rating = np.random.choice(ratings[:4] if not deficiency else ratings[3:], p=[0.3, 0.3, 0.2, 0.2] if not deficiency else [0.6, 0.4])
        insp_date_offset = np.random.randint(180, 280)
        insp_date = str((pd.Timestamp("2024-01-01") + pd.Timedelta(days=int(insp_date_offset))).date())
        inspector = np.random.choice(INSPECTORS)
        sign_off = "approved" if not deficiency or np.random.random() < 0.5 else "conditional"
        reports.append((report_id, item_id, insp_date, inspector, verified_pct, deficiency, deficiency_desc, rating, sign_off))
        report_id += 1

    # Fill remaining reports for other items
    other_items = [it for it in items if it[0] not in pending_item_ids]
    for item in other_items:
        if report_id > num and len(reports) >= num:
            break
        item_id = item[0]
        verified_pct = round(np.random.uniform(30, 100), 1)
        deficiency = int(np.random.random() < 0.15)
        deficiency_desc = ""
        if deficiency:
            deficiency_desc = "Minor issue noted during inspection"
        rating = np.random.choice(ratings[:4])
        insp_date_offset = np.random.randint(60, 300)
        insp_date = str((pd.Timestamp("2024-01-01") + pd.Timedelta(days=int(insp_date_offset))).date())
        inspector = np.random.choice(INSPECTORS)
        sign_off = "approved"
        reports.append((report_id, item_id, insp_date, inspector, verified_pct, deficiency, deficiency_desc, rating, sign_off))
        report_id += 1

    # Pad to reach num
    while len(reports) < num:
        item = items[len(reports) % len(items)]
        item_id = item[0]
        verified_pct = round(np.random.uniform(30, 100), 1)
        deficiency = 0
        rating = np.random.choice(ratings[:3])
        insp_date_offset = np.random.randint(60, 300)
        insp_date = str((pd.Timestamp("2024-01-01") + pd.Timedelta(days=int(insp_date_offset))).date())
        inspector = np.random.choice(INSPECTORS)
        reports.append((report_id, item_id, insp_date, inspector, verified_pct, deficiency, "", rating, "approved"))
        report_id += 1

    cursor.executemany(
        "INSERT INTO inspection_reports VALUES (?,?,?,?,?,?,?,?,?)", reports
    )
    return reports


def generate_workspace_files(workspace, fake, subs, items, pending_apps, deliveries, inspections, num_files):
    """Generate workspace files: certificates, supervisor logs, material invoices, plus fixed policy files."""
    sub_map = {s[0]: s for s in subs}
    item_map = {it[0]: it for it in items}
    insp_by_item = {}
    for r in inspections:
        insp_by_item.setdefault(r[1], []).append(r)
    del_by_item = {}
    for d in deliveries:
        del_by_item.setdefault(d[1], []).append(d)

    num_certificates = len(pending_apps)
    num_logs = max(3, (num_files - num_certificates) // 2)
    num_invoices = max(2, num_files - num_certificates - num_logs)

    # --- Completion Certificates (JSON) ---
    cert_dir = os.path.join(workspace, "certificates")
    os.makedirs(cert_dir, exist_ok=True)

    for app in pending_apps:
        app_id = app[0]
        sub_id = app[1]
        item_id = app[2]
        claimed_pct = app[6]

        # certified_pct: sometimes matches claimed, sometimes lower
        cert_delta = np.random.choice([0, 0, -3, -5, -8, -12], p=[0.3, 0.2, 0.15, 0.15, 0.1, 0.1])
        certified_pct = round(max(5, claimed_pct + cert_delta), 1)

        # supervisor sign-off: ~20% not signed
        supervisor_signed = bool(np.random.random() > 0.2)

        cert_data = {
            "certificate_number": f"WCC-{app_id:04d}",
            "application_id": app_id,
            "schedule_item_id": item_id,
            "subcontractor_id": sub_id,
            "certified_completion_pct": certified_pct,
            "supervisor_signed_off": supervisor_signed,
            "certification_date": app[8],  # submission_date
            "site_conditions": np.random.choice(["Acceptable", "Good", "Fair", "Needs attention"]),
            "weather_delays_days": int(np.random.choice([0, 0, 0, 1, 2, 3])),
            "remarks": np.random.choice([
                "Work progressing within acceptable parameters",
                "Satisfactory progress observed on site",
                "Minor issues noted but overall progress adequate",
                "Some rework required before full certification",
                "Excellent workmanship throughout inspected area",
                "Progress consistent with submitted documentation",
            ])
        }
        with open(os.path.join(cert_dir, f"cert_{app_id:04d}.json"), "w") as f:
            json.dump(cert_data, f, indent=2)

    # --- Supervisor Daily Logs (MD) ---
    logs_dir = os.path.join(workspace, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    # Generate logs covering dates that overlap with pending application periods
    all_period_starts = [pd.Timestamp(app[4]) for app in pending_apps]
    all_period_ends = [pd.Timestamp(app[5]) for app in pending_apps]
    if all_period_starts:
        earliest = min(all_period_starts)
        latest = max(all_period_ends)
    else:
        earliest = pd.Timestamp("2024-06-01")
        latest = pd.Timestamp("2024-09-01")

    total_days = (latest - earliest).days
    if total_days < num_logs:
        total_days = num_logs * 5

    log_dates = sorted(np.random.choice(
        [earliest + pd.Timedelta(days=int(d)) for d in range(max(1, total_days))],
        size=min(num_logs, max(1, total_days)),
        replace=False
    ))

    # Build activity data for logs - reference pending app schedule items
    pending_item_ids = [app[2] for app in pending_apps]
    pending_item_codes = [item_map[iid][2] for iid in pending_item_ids if iid in item_map]

    for log_idx, log_date in enumerate(log_dates):
        weather = np.random.choice(["Clear", "Partly Cloudy", "Overcast", "Light Rain", "Heavy Rain", "Windy"])
        temp_high = np.random.randint(65, 95)
        temp_low = temp_high - np.random.randint(10, 20)

        lines = [
            f"# Site Supervisor Daily Log - {log_date.strftime('%Y-%m-%d')}",
            "",
            f"Weather: {weather}, High {temp_high}F / Low {temp_low}F",
            f"Site Supervisor: {fake.name()}",
            "",
            "## Activities",
            "",
        ]

        # Include some pending item activities, some with stoppages
        num_mentioned = min(len(pending_item_codes), np.random.randint(2, max(3, len(pending_item_codes))))
        mentioned_codes = list(np.random.choice(pending_item_codes, size=num_mentioned, replace=False))

        for code in mentioned_codes:
            # ~25% chance of no activity (stoppage)
            if np.random.random() < 0.25:
                reason = np.random.choice([
                    "No activity. Material delivery pending.",
                    "No activity. Crew not mobilized.",
                    "No activity. Work suspended due to weather.",
                    "No activity. Awaiting inspection clearance.",
                    "No activity. Safety hold in effect.",
                ])
                lines.append(f"- {code}: {reason}")
            else:
                crew_size = np.random.randint(3, 15)
                activity = np.random.choice([
                    f"Work in progress. Crew: {crew_size} workers. Progress satisfactory.",
                    f"Active installation phase. {crew_size} workers on site.",
                    f"Continuing from previous day. Crew of {crew_size}. On schedule.",
                    f"Major push today. {crew_size} workers deployed. Good progress.",
                    f"Finishing phase underway. {crew_size}-person crew.",
                ])
                lines.append(f"- {code}: {activity}")

        # Add some non-pending items too for noise
        other_codes = [item_map[it[0]][2] for it in items if it[0] not in pending_item_ids]
        if other_codes:
            num_others = min(len(other_codes), np.random.randint(1, 4))
            for code in np.random.choice(other_codes, size=num_others, replace=False):
                crew_size = np.random.randint(2, 10)
                lines.append(f"- {code}: Work proceeding. Crew: {crew_size}.")

        lines.extend([
            "",
            "## Notes",
            "",
            np.random.choice([
                "Overall progress within expected parameters. No safety incidents reported.",
                "Good coordination between trades today. Minor congestion at loading dock.",
                "Safety briefing conducted at 0700. All workers compliant with PPE requirements.",
                "Concrete delivery delayed by 2 hours. Otherwise normal operations.",
                "Quality control team conducted spot checks. Results satisfactory.",
                "Material staging area reorganized for efficiency. No incidents.",
            ]),
            "",
        ])

        with open(os.path.join(logs_dir, f"log_{log_date.strftime('%Y-%m-%d')}.md"), "w") as f:
            f.write("\n".join(lines))

    # --- Material Invoices (CSV) ---
    invoices_dir = os.path.join(workspace, "invoices")
    os.makedirs(invoices_dir, exist_ok=True)

    # Group deliveries by schedule_item_id for pending items, create invoice files
    # Some invoices will have discrepancies with DB totals
    invoice_items = pending_item_ids[:num_invoices] if len(pending_item_ids) >= num_invoices else \
        pending_item_ids + [items[i % len(items)][0] for i in range(num_invoices - len(pending_item_ids))]

    for inv_idx, item_id in enumerate(invoice_items):
        item_dels = del_by_item.get(item_id, [])
        if not item_dels:
            continue

        invoice_rows = []
        for d in item_dels:
            # Sometimes introduce a small discrepancy in the invoice amount
            discrepancy_factor = 1.0
            if np.random.random() < 0.25:
                discrepancy_factor = np.random.choice([0.92, 0.95, 1.05, 1.08])
            inv_total = round(d[7] * discrepancy_factor, 2)
            invoice_rows.append({
                "delivery_id": d[0],
                "po_number": d[3],
                "material": d[4],
                "quantity": d[5],
                "unit_price": d[6],
                "line_total": inv_total,
                "invoice_number": f"INV-{2024}-{d[0]:05d}",
                "verification_status": np.random.choice(["verified", "verified", "verified", "unverified"]),
            })

        item = item_map[item_id]
        item_code = item[2]
        with open(os.path.join(invoices_dir, f"invoice_{item_code}.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["delivery_id", "po_number", "material", "quantity", "unit_price", "line_total", "invoice_number", "verification_status"])
            writer.writeheader()
            writer.writerows(invoice_rows)

    # --- Fixed Files ---

    # Payment Policy (YAML)
    policy = {
        "retention_rate": 0.10,
        "deficiency_deduction_rate": 0.05,
        "material_discrepancy_tolerance": 0.05,
        "material_discrepancy_penalty_rate": 0.03,
        "max_allowed_stoppage_days": 2,
        "delay_penalty_rate": 0.02,
        "minimum_approved_pct": 5.0,
        "maximum_single_payment_pct": 95.0,
        "approval_rules": {
            "supervisor_signoff_required": True,
            "inspection_report_required": True,
            "material_verification_required": True,
        },
    }
    with open(os.path.join(workspace, "payment_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # Project Schedule Summary (CSV)
    schedule_rows = []
    for item in items:
        sub = sub_map[item[1]]
        schedule_rows.append({
            "item_code": item[2],
            "description": item[3],
            "subcontractor": sub[1],
            "trade": sub[2],
            "planned_start": item[4],
            "planned_end": item[5],
            "budgeted_amount": item[6],
        })
    with open(os.path.join(workspace, "project_schedule.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["item_code", "description", "subcontractor", "trade", "planned_start", "planned_end", "budgeted_amount"])
        writer.writeheader()
        writer.writerows(schedule_rows)

    # Subcontractor Directory (TXT)
    with open(os.path.join(workspace, "subcontractor_directory.txt"), "w") as f:
        f.write("SUBCONTRACTOR DIRECTORY\n")
        f.write("=" * 60 + "\n\n")
        for sub in subs:
            f.write(f"ID: {sub[0]}\n")
            f.write(f"Company: {sub[1]}\n")
            f.write(f"Trade: {sub[2]}\n")
            f.write(f"License: {sub[3]}\n")
            f.write(f"Phone: {sub[4]}\n")
            f.write(f"Email: {sub[5]}\n")
            f.write(f"Contract Value: ${sub[6]:,.2f}\n")
            f.write("-" * 40 + "\n")


def main(db_path, workspace):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    rows = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    # Derive counts
    num_subcontractors = rows
    num_schedule_items = max(rows, num_subcontractors * 2)
    num_pending = max(5, num_files // 2)
    num_payment_apps = max(rows, num_pending + rows)
    num_deliveries = max(rows, num_schedule_items)
    num_inspections = max(rows, num_schedule_items)

    create_tables(cursor)

    subs = generate_subcontractors(cursor, fake, num_subcontractors)
    items = generate_schedule_items(cursor, fake, subs, num_schedule_items)

    # Generate pending apps first, then fill rest
    pending_apps_data = generate_payment_applications(cursor, fake, subs, items, num_payment_apps, num_pending)
    pending_apps = [a for a in pending_apps_data if a[9] == "pending"]

    deliveries = generate_material_deliveries(cursor, fake, items, subs, num_deliveries)
    inspections = generate_inspection_reports(cursor, fake, items, num_inspections, pending_apps)

    conn.commit()

    generate_workspace_files(workspace, fake, subs, items, pending_apps, deliveries, inspections, num_files)

    conn.close()
    print(f"Database created at {db_path}")
    print(f"Workspace initialized at {workspace}")
    print(f"  - Subcontractors: {num_subcontractors}")
    print(f"  - Schedule items: {len(items)}")
    print(f"  - Payment applications: {len(pending_apps_data)} (pending: {len(pending_apps)})")
    print(f"  - Material deliveries: {len(deliveries)}")
    print(f"  - Inspection reports: {len(inspections)}")
    print(f"  - Workspace files: {num_files} scalable + 3 fixed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
