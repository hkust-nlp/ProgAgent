"""
Cold-chain food safety task — data generation.
Builds the SQLite database and workspace files for agent evaluation.
"""
import argparse
import sqlite3
import os
import json
import csv
import random
import numpy as np
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 160,
    "num_workspace_files": 20,
}

# ── Fixed domain constants ──────────────────────────────────────────
NUM_PRODUCTS = 20
NUM_FACILITIES = 15
NUM_SUPPLIERS = 12

PRODUCT_TEMPLATES = [
    ("PRD-001", "Vanilla Ice Cream", "frozen"),
    ("PRD-002", "Frozen Peas", "frozen"),
    ("PRD-003", "Frozen Atlantic Salmon", "frozen"),
    ("PRD-004", "Frozen Chicken Nuggets", "frozen"),
    ("PRD-005", "Frozen Pizza Margherita", "frozen"),
    ("PRD-006", "Frozen Blueberries", "frozen"),
    ("PRD-007", "Frozen Shrimp", "frozen"),
    ("PRD-008", "Whole Milk 1L", "chilled"),
    ("PRD-009", "Greek Yogurt 500g", "chilled"),
    ("PRD-010", "Fresh Ground Beef", "chilled"),
    ("PRD-011", "Fresh Chicken Breast", "chilled"),
    ("PRD-012", "Orange Juice 2L", "chilled"),
    ("PRD-013", "Sliced Turkey Deli", "chilled"),
    ("PRD-014", "Heavy Cream 500ml", "chilled"),
    ("PRD-015", "Aged Cheddar Block", "cool"),
    ("PRD-016", "Unsalted Butter 250g", "cool"),
    ("PRD-017", "Free Range Eggs 12pk", "cool"),
    ("PRD-018", "Gouda Cheese Wheel", "cool"),
    ("PRD-019", "Cream Cheese Spread", "cool"),
    ("PRD-020", "Smoked Gouda Slices", "cool"),
]

CATEGORY_PARAMS = {
    "frozen":  {"max_temp_c": -15.0, "nominal_c": -20.0, "std_c": 1.0},
    "chilled": {"max_temp_c":   4.0, "nominal_c":   1.5, "std_c": 0.5},
    "cool":    {"max_temp_c":  12.0, "nominal_c":   8.0, "std_c": 0.8},
}

SYMPTOM_DEFS = {
    "SYM-001": {"name": "Nausea/Vomiting", "severity": "high"},
    "SYM-002": {"name": "Diarrhea", "severity": "high"},
    "SYM-003": {"name": "Abdominal Cramps", "severity": "moderate"},
    "SYM-004": {"name": "Fever", "severity": "high"},
    "SYM-005": {"name": "Off-taste/Odor", "severity": "low"},
    "SYM-006": {"name": "Allergic Reaction", "severity": "critical"},
    "SYM-007": {"name": "Headache", "severity": "low"},
    "SYM-008": {"name": "Skin Rash", "severity": "moderate"},
    "SYM-009": {"name": "Bloating", "severity": "low"},
    "SYM-010": {"name": "Respiratory Distress", "severity": "critical"},
}

INGREDIENT_NAMES = [
    "Milk Powder", "Soy Lecithin", "Palm Oil", "Corn Starch",
    "Sodium Benzoate", "Citric Acid", "Modified Starch", "Whey Protein",
    "Xanthan Gum", "Gelatin", "Sugar", "Salt",
    "Egg Powder", "Cocoa Butter", "Wheat Flour", "Yeast Extract",
]

AUDIT_CATEGORIES = [
    "Equipment Sanitation", "Personnel Hygiene", "Pest Control",
    "Temperature Monitoring", "Chemical Storage", "Waste Management",
    "Cross-Contamination Prevention", "Water Quality",
]

CARRIERS = [
    "Arctic Express Logistics", "ColdChain Corp", "FrostLine Transport",
    "PolarBear Freight", "ChillWave Carriers", "IcePath Shipping",
    "TempGuard Logistics", "FreezeNet Delivery",
]


def chunk_list(lst, n):
    """Split *lst* into *n* roughly equal chunks."""
    if n <= 0 or not lst:
        return [lst] if lst else [[]]
    k, m = divmod(len(lst), n)
    return [lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # ── Seed everything ──────────────────────────────────────────
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    R = SCALE["rows_per_table"]
    W = SCALE["num_workspace_files"]
    ws = args.workspace
    os.makedirs(ws, exist_ok=True)

    # ── Reference data (workspace-only) ──────────────────────────
    products = list(PRODUCT_TEMPLATES)  # (pid, pname, cat)
    prod_map = {p[0]: (p[1], p[2]) for p in products}

    ftypes = ["production"] * 8 + ["distribution"] * 4 + ["supplier"] * 3
    facilities = []
    for i in range(NUM_FACILITIES):
        fid = f"FAC-{i + 1:03d}"
        facilities.append(
            (fid, fake.company() + f" {ftypes[i].title()}", ftypes[i],
             fake.city(), fake.state_abbr()))
    fac_map = {f[0]: f for f in facilities}
    prod_fids = [f[0] for f in facilities if f[2] == "production"]
    all_fids = [f[0] for f in facilities]

    cert_pool = (["active"] * 7 + ["probation"] * 2
                 + ["suspended"] * 2 + ["revoked"] * 1)
    random.shuffle(cert_pool)
    suppliers = []
    for i in range(NUM_SUPPLIERS):
        sid = f"SUP-{i + 1:03d}"
        sname = fake.company() + " Ingredients"
        exp_d = (datetime(2025, 6, 1)
                 + timedelta(days=random.randint(-180, 365))).strftime("%Y-%m-%d")
        suppliers.append((sid, sname, cert_pool[i], exp_d))
    sup_map = {s[0]: s for s in suppliers}
    bad_sups = [s[0] for s in suppliers if s[2] in ("suspended", "revoked")]

    # ── DB setup ─────────────────────────────────────────────────
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    cur = conn.cursor()

    # ── Table: lots ──────────────────────────────────────────────
    cur.execute("""CREATE TABLE lots (
        lot_code        TEXT PRIMARY KEY,
        product_id      TEXT,
        facility_id     TEXT,
        production_date TEXT,
        expiry_date     TEXT
    )""")
    base_date = datetime(2025, 1, 15)
    lots = []
    for i in range(R):
        lc = f"LOT-{i + 1:04d}"
        pid = random.choice([p[0] for p in products])
        fid = random.choice(prod_fids)
        pd_ = base_date + timedelta(days=random.randint(0, 150))
        ed = pd_ + timedelta(days=random.randint(30, 365))
        lots.append((lc, pid, fid, pd_.strftime("%Y-%m-%d"),
                      ed.strftime("%Y-%m-%d")))
    cur.executemany("INSERT INTO lots VALUES (?,?,?,?,?)", lots)
    lot_map = {l[0]: l for l in lots}

    # ── Decide which lots / facilities trigger each criterion ────
    n_exc = max(5, int(R * 0.12))
    exc_indices = sorted(random.sample(range(R), n_exc))
    exc_lot_codes = {lots[i][0] for i in exc_indices}

    # 2 violation facilities (1 production, 1 non-production)
    viol_prod = random.choice(prod_fids)
    non_prod_fids = [f[0] for f in facilities if f[2] != "production"]
    viol_dist = random.choice(non_prod_fids)
    viol_fids = {viol_prod, viol_dist}

    n_cc = max(4, int(R * 0.09))
    cc_indices = sorted(random.sample(range(R), n_cc))
    cc_lot_codes = {lots[i][0] for i in cc_indices}

    # ── Table: shipments ─────────────────────────────────────────
    n_ship = max(R, int(R * 1.3))
    cur.execute("""CREATE TABLE shipments (
        shipment_id TEXT PRIMARY KEY,
        lot_code    TEXT,
        depart_ts   TEXT,
        arrive_ts   TEXT,
        FOREIGN KEY (lot_code) REFERENCES lots(lot_code)
    )""")
    ship_assign = list(lot_map.keys())
    for _ in range(n_ship - R):
        ship_assign.append(random.choice(list(lot_map.keys())))
    random.shuffle(ship_assign)
    shipments = []
    for i, lc in enumerate(ship_assign):
        sid = f"SHP-{i + 1:04d}"
        lot_pd = datetime.strptime(lot_map[lc][3], "%Y-%m-%d")
        dep = lot_pd + timedelta(hours=random.randint(12, 72))
        arr = dep + timedelta(hours=random.randint(6, 48))
        shipments.append((sid, lc,
                          dep.strftime("%Y-%m-%d %H:%M"),
                          arr.strftime("%Y-%m-%d %H:%M")))
    cur.executemany("INSERT INTO shipments VALUES (?,?,?,?)", shipments)

    lot_to_ships = {}
    for s in shipments:
        lot_to_ships.setdefault(s[1], []).append(s)

    # Mark excursion shipments (at least 1 per excursion lot)
    exc_ship_ids = set()
    for lc in exc_lot_codes:
        lships = lot_to_ships.get(lc, [])
        if lships:
            exc_ship_ids.add(lships[0][0])
            for s in lships[1:]:
                if random.random() < 0.4:
                    exc_ship_ids.add(s[0])

    # ── Table: temperature_readings ──────────────────────────────
    cur.execute("""CREATE TABLE temperature_readings (
        reading_id    TEXT PRIMARY KEY,
        shipment_id   TEXT,
        sensor_id     TEXT,
        timestamp     TEXT,
        temperature_c REAL,
        FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id)
    )""")
    readings = []
    rc = 0
    for s in shipments:
        sid, lc = s[0], s[1]
        pid = lot_map[lc][1]
        cat = prod_map[pid][1]
        params = CATEGORY_PARAMS[cat]
        dep = datetime.strptime(s[2], "%Y-%m-%d %H:%M")
        arr = datetime.strptime(s[3], "%Y-%m-%d %H:%M")
        dur_h = max(1, (arr - dep).total_seconds() / 3600)
        n_rd = max(4, int(dur_h / 2))
        sensor = f"SENS-{random.randint(1, 50):03d}"
        is_exc = sid in exc_ship_ids

        for j in range(n_rd):
            rc += 1
            rid = f"RD-{rc:06d}"
            ts = dep + timedelta(hours=j * dur_h / n_rd)
            if is_exc and j >= max(1, n_rd // 3):
                excess = random.uniform(2.5, 8.0)
                temp = params["max_temp_c"] + excess
            else:
                temp = float(np.random.normal(params["nominal_c"],
                                               params["std_c"]))
                temp = min(temp, params["max_temp_c"] - 1.0)
            readings.append((rid, sid, sensor,
                             ts.strftime("%Y-%m-%d %H:%M:%S"),
                             round(temp, 2)))
    cur.executemany(
        "INSERT INTO temperature_readings VALUES (?,?,?,?,?)", readings)

    # ── Table: ingredient_lots ───────────────────────────────────
    cur.execute("""CREATE TABLE ingredient_lots (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        lot_code            TEXT,
        ingredient_lot_code TEXT,
        ingredient_name     TEXT,
        supplier_id         TEXT,
        FOREIGN KEY (lot_code) REFERENCES lots(lot_code)
    )""")
    n_uniq_ing = max(20, int(R * 0.5))
    ing_pool = []
    for i in range(n_uniq_ing):
        ilc = f"ING-{i + 1:04d}"
        iname = random.choice(INGREDIENT_NAMES)
        isup = random.choice([s[0] for s in suppliers])
        ing_pool.append((ilc, iname, isup))
    ingredients = []
    for lot in lots:
        lc = lot[0]
        n_ing = random.randint(2, 4)
        sel = random.sample(ing_pool, min(n_ing, len(ing_pool)))
        for ilc, iname, isup in sel:
            ingredients.append((lc, ilc, iname, isup))

    # Ensure ingredient-link criterion is satisfiable
    san_lots = {l[0] for l in lots if l[2] in viol_fids}
    primary_flagged = exc_lot_codes | san_lots | cc_lot_codes
    non_flagged = [l[0] for l in lots if l[0] not in primary_flagged]
    n_link = max(3, int(R * 0.06))
    if non_flagged and primary_flagged and bad_sups:
        link_tgts = random.sample(non_flagged,
                                   min(n_link, len(non_flagged)))
        for lt in link_tgts:
            pf = random.choice(sorted(primary_flagged))
            shared_ilc = f"ING-S-{lt[-4:]}"
            shared_name = random.choice(INGREDIENT_NAMES)
            shared_sup = random.choice(bad_sups)
            ingredients.append((lt, shared_ilc, shared_name, shared_sup))
            ingredients.append((pf, shared_ilc, shared_name, shared_sup))
    cur.executemany(
        "INSERT INTO ingredient_lots"
        " (lot_code, ingredient_lot_code, ingredient_name, supplier_id)"
        " VALUES (?,?,?,?)", ingredients)

    # ── Table: complaints ────────────────────────────────────────
    cur.execute("""CREATE TABLE complaints (
        complaint_id   TEXT PRIMARY KEY,
        lot_code       TEXT,
        complaint_date TEXT,
        reporter_name  TEXT,
        FOREIGN KEY (lot_code) REFERENCES lots(lot_code)
    )""")
    high_crit_syms = [s for s, d in SYMPTOM_DEFS.items()
                      if d["severity"] in ("high", "critical")]
    all_syms = list(SYMPTOM_DEFS.keys())
    complaints = []
    comp_syms = {}
    cc_counter = 0

    for lc in sorted(cc_lot_codes):
        sym = random.choice(high_crit_syms)
        n_cl = random.randint(3, 5)
        for _ in range(n_cl):
            cc_counter += 1
            cid = f"CMP-{cc_counter:05d}"
            cd = (datetime(2025, 3, 1)
                  + timedelta(days=random.randint(0, 90))).strftime("%Y-%m-%d")
            complaints.append((cid, lc, cd, fake.name()))
            comp_syms[cid] = sym

    remaining = max(0, R - len(complaints))
    non_cc_lots = [l[0] for l in lots if l[0] not in cc_lot_codes]
    for _ in range(remaining):
        cc_counter += 1
        cid = f"CMP-{cc_counter:05d}"
        lc = random.choice(non_cc_lots) if non_cc_lots else lots[0][0]
        cd = (datetime(2025, 3, 1)
              + timedelta(days=random.randint(0, 120))).strftime("%Y-%m-%d")
        complaints.append((cid, lc, cd, fake.name()))
        comp_syms[cid] = random.choice(all_syms)
    cur.executemany("INSERT INTO complaints VALUES (?,?,?,?)", complaints)

    conn.commit()
    conn.close()

    # =================================================================
    # WORKSPACE — Fixed files
    # =================================================================

    # 1. temperature_policy.yaml
    with open(os.path.join(ws, "temperature_policy.yaml"), "w") as f:
        f.write("storage_categories:\n")
        f.write("  frozen:\n    max_temp_c: -15.0\n")
        f.write("  chilled:\n    max_temp_c: 4.0\n")
        f.write("  cool:\n    max_temp_c: 12.0\n")
        f.write("\n")
        f.write("excursion_rules:\n")
        f.write("  count_threshold: 3\n")
        f.write("  single_excess_threshold_c: 5.0\n")

    # 2. hold_criteria.md
    with open(os.path.join(ws, "hold_criteria.md"), "w") as f:
        f.write("""# Product Hold Decision Criteria

A product lot must be placed on immediate hold if it satisfies one or more of the
following criteria. Each criterion is evaluated independently.

## TEMP_EXCURSION (30 risk points)

A lot is flagged when any of its associated shipments contains a temperature
excursion. A shipment has an excursion when the total count of individual
temperature sensor readings that exceed the maximum allowed temperature for the
product's storage category (defined in temperature_policy.yaml, category mapped
via product_catalog.csv) reaches or exceeds the count_threshold specified in the
temperature policy, OR when any single reading exceeds the maximum by more than
single_excess_threshold_c degrees.

## SANITATION (25 risk points)

A lot is flagged when its production facility, or any facility that appears as
origin or destination in the shipment manifests for that lot's shipments, has two
or more unresolved violations of "critical" severity across all sanitation audit
report files.

## COMPLAINT_CLUSTER (25 risk points)

A lot is flagged when it has three or more consumer complaints that share an
identical symptom code, and that symptom code carries a severity rating of "high"
or "critical" as defined in symptom_codes.json. Complaint-to-symptom mappings are
found in the complaint detail files.

## INGREDIENT_LINK (20 risk points)

A lot is flagged when it shares an ingredient lot code with any lot that is
flagged under TEMP_EXCURSION, SANITATION, or COMPLAINT_CLUSTER (the "primary"
criteria), and the supplier of that shared ingredient has a certification status
of "suspended" or "revoked" in supplier_directory.csv.

## Risk Score

For each held lot, sum the points of every applicable criterion.
Maximum possible score is 100.

## Output Specification

Produce a file named hold_report.csv with columns in this exact order:
lot_code, product_name, facility_name, hold_reasons, risk_score

Sort rows by risk_score descending; break ties by lot_code ascending.

The hold_reasons field lists applicable criterion codes separated by a pipe
character in this fixed order: TEMP_EXCURSION|SANITATION|COMPLAINT_CLUSTER|INGREDIENT_LINK
(include only those that apply).

The final response must state the held lot codes as a comma-separated list in
ascending alphabetical order, prefixed exactly with:
HOLD_LOTS: LOT-xxxx, LOT-yyyy, ...
""")

    # 3. product_catalog.csv
    with open(os.path.join(ws, "product_catalog.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["product_id", "product_name", "storage_category"])
        for pid, pname, cat in products:
            w.writerow([pid, pname, cat])

    # 4. facility_registry.csv
    with open(os.path.join(ws, "facility_registry.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["facility_id", "facility_name", "facility_type",
                     "city", "state"])
        for row in facilities:
            w.writerow(row)

    # 5. supplier_directory.csv
    with open(os.path.join(ws, "supplier_directory.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["supplier_id", "supplier_name",
                     "certification_status", "certification_expiry"])
        for row in suppliers:
            w.writerow(row)

    # 6. symptom_codes.json
    with open(os.path.join(ws, "symptom_codes.json"), "w") as f:
        json.dump(SYMPTOM_DEFS, f, indent=2)

    # =================================================================
    # WORKSPACE — Scalable files
    # =================================================================
    n_audit_files = max(1, round(W * 0.3))
    n_manifest_files = max(1, round(W * 0.4))
    n_complaint_files = max(1, W - n_audit_files - n_manifest_files)

    # ── Audit report CSVs ────────────────────────────────────────
    audit_records = []
    ac = 0
    num_audits_base = max(3, R // 10)
    for fid, fname, ftype, city, state in facilities:
        n_aud = random.randint(max(2, num_audits_base - 2),
                               num_audits_base + 3)
        for _ in range(n_aud):
            ac += 1
            aid = f"AUD-{ac:04d}"
            adate = (datetime(2024, 6, 1)
                     + timedelta(days=random.randint(0, 365))
                     ).strftime("%Y-%m-%d")
            auditor = fake.name()
            category = random.choice(AUDIT_CATEGORIES)
            if fid in viol_fids:
                sev = random.choices(
                    ["minor", "major", "critical"],
                    weights=[0.15, 0.25, 0.60])[0]
                resolved = random.choices(
                    ["yes", "no"], weights=[0.25, 0.75])[0]
            else:
                sev = random.choices(
                    ["minor", "major", "critical"],
                    weights=[0.55, 0.30, 0.15])[0]
                resolved = random.choices(
                    ["yes", "no"], weights=[0.85, 0.15])[0]
            desc = (f"{category} deficiency identified during scheduled "
                    f"inspection at {fname.split()[0]} facility")
            audit_records.append({
                "audit_id": aid, "facility_id": fid,
                "audit_date": adate, "auditor": auditor,
                "category": category,
                "violation_description": desc,
                "severity": sev, "resolved": resolved,
            })
    random.shuffle(audit_records)
    for idx, chunk in enumerate(chunk_list(audit_records, n_audit_files)):
        fp = os.path.join(ws, f"audit_report_{idx + 1:03d}.csv")
        with open(fp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "audit_id", "facility_id", "audit_date", "auditor",
                "category", "violation_description", "severity", "resolved"])
            w.writeheader()
            w.writerows(chunk)

    # ── Shipment manifest JSONs ──────────────────────────────────
    manifests = []
    for s in shipments:
        sid, lc = s[0], s[1]
        origin = random.choice(all_fids)
        dest = random.choice([f for f in all_fids if f != origin])
        manifests.append({
            "shipment_id": sid,
            "lot_code": lc,
            "carrier_name": random.choice(CARRIERS),
            "origin_facility_id": origin,
            "destination_facility_id": dest,
            "handling_instructions": random.choice([
                "Standard cold-chain protocol",
                "Priority temperature-sensitive handling",
                "Expedited refrigerated transport",
                "Standard frozen freight protocol",
            ]),
        })
    for idx, chunk in enumerate(chunk_list(manifests, n_manifest_files)):
        fp = os.path.join(ws, f"shipment_manifest_{idx + 1:03d}.json")
        with open(fp, "w") as f:
            json.dump(chunk, f, indent=2)

    # ── Complaint detail JSONs ───────────────────────────────────
    details = []
    for cid, lc, cdate, reporter in complaints:
        sym = comp_syms.get(cid, "SYM-005")
        details.append({
            "complaint_id": cid,
            "lot_code": lc,
            "symptom_code": sym,
            "narrative": fake.paragraph(nb_sentences=3),
        })
    for idx, chunk in enumerate(chunk_list(details, n_complaint_files)):
        fp = os.path.join(ws, f"complaint_detail_{idx + 1:03d}.json")
        with open(fp, "w") as f:
            json.dump(chunk, f, indent=2)


if __name__ == "__main__":
    main()
