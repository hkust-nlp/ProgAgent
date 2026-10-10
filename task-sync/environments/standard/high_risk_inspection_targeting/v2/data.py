"""
Data generation for customs import shipment inspection task.
Generates database tables and workspace files for identifying high-risk shipments.
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

# ── Scale configuration (v0 base) ──────────────────────────────────────────
SCALE = {
    "rows_per_table": 320,      # v2: 4x base
    "num_workspace_files": 30,  # v2: base + 2N (N=10)
}

# ── Deterministic seeds ────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

TARGET_DATE = "2026-04-20"

# ── Reference data ─────────────────────────────────────────────────────────
COUNTRIES = [
    "China", "Vietnam", "India", "Bangladesh", "Turkey", "Indonesia",
    "Thailand", "Malaysia", "Pakistan", "Nigeria", "Brazil", "Mexico",
    "South Korea", "Taiwan", "Philippines", "Cambodia", "Egypt",
    "South Africa", "Colombia", "Myanmar",
]

HIGH_RISK_COUNTRIES = ["Myanmar", "Nigeria", "Pakistan", "Cambodia", "Bangladesh"]

PORTS = [
    "Los Angeles", "Long Beach", "New York/Newark", "Savannah",
    "Houston", "Seattle", "Norfolk", "Charleston", "Oakland", "Miami",
]

HS_CHAPTERS = {
    "01-05": "Animal Products",
    "06-14": "Vegetable Products",
    "15": "Fats and Oils",
    "16-24": "Foodstuffs",
    "25-27": "Mineral Products",
    "28-38": "Chemicals",
    "39-40": "Plastics and Rubber",
    "41-43": "Leather and Hides",
    "44-49": "Wood and Paper",
    "50-63": "Textiles",
    "64-67": "Footwear and Headgear",
    "68-71": "Stone and Glass",
    "72-83": "Metals",
    "84-85": "Machinery and Electronics",
    "86-89": "Vehicles and Transport",
    "90-97": "Miscellaneous Manufactured",
}

COMPLIANCE_TIERS = ["A", "B", "C", "D"]
VIOLATION_TYPES = [
    "Undervaluation", "Misclassification", "Country of Origin Fraud",
    "Quantity Discrepancy", "Restricted Goods", "Documentation Fraud",
    "Sanitary Violation", "IPR Infringement",
]
INSPECTION_OUTCOMES = ["Clean", "Minor Violation", "Major Violation"]

# ── Valuation benchmarks ──────────────────────────────────────────────────
CATEGORY_BENCHMARKS = {}
for _cat in sorted(set(HS_CHAPTERS.values())):
    if _cat in ("Machinery and Electronics", "Vehicles and Transport"):
        _mn, _mx = 50, 500
    elif _cat in ("Textiles", "Footwear and Headgear"):
        _mn, _mx = 2, 40
    elif _cat in ("Chemicals", "Plastics and Rubber"):
        _mn, _mx = 5, 80
    else:
        _mn, _mx = 3, 100
    CATEGORY_BENCHMARKS[_cat] = {
        "min": _mn, "max": _mx, "median": (_mn + _mx) / 2
    }


def generate_hs_codes(n_codes):
    """Generate realistic HS codes with chapter, category, duty rate."""
    chapters = list(HS_CHAPTERS.keys())
    codes = []
    used = set()
    for _ in range(n_codes):
        chapter = random.choice(chapters)
        ch_num = int(chapter.split("-")[0])
        code = f"{ch_num:02d}{random.randint(1, 99):02d}.{random.randint(10, 99)}"
        while code in used:
            code = f"{ch_num:02d}{random.randint(1, 99):02d}.{random.randint(10, 99)}"
        used.add(code)
        category = HS_CHAPTERS[chapter]
        duty_rate = round(random.uniform(0, 25), 1)
        requires_license = 1 if random.random() < 0.15 else 0
        codes.append({
            "hs_code": code,
            "chapter": chapter,
            "category": category,
            "description": f"{category} - {fake.bs()}",
            "standard_duty_rate_pct": duty_rate,
            "requires_special_license": requires_license,
        })
    return codes


def generate_shippers(n_shippers):
    """Generate shipper profiles with compliance history.

    Ensures at least 15% of shippers are tier D with high violation rates.
    """
    shippers = []
    n_bad = max(int(n_shippers * 0.15), 3)

    # Generate high-risk shippers first
    for i in range(n_bad):
        shipper_id = f"SH{i + 1:04d}"
        # High violation rate: many violations relative to total shipments
        violation_count = random.randint(15, 40)
        total_shipments = random.randint(violation_count + 5,
                                         violation_count + 30)
        shippers.append({
            "shipper_id": shipper_id,
            "company_name": fake.company(),
            "registration_country": random.choice(HIGH_RISK_COUNTRIES),
            "years_active": random.randint(1, 5),
            "total_shipments": total_shipments,
            "violation_count": violation_count,
            "compliance_tier": "D",
            "last_audit_date": fake.date_between(
                start_date="-2y", end_date="today"
            ).isoformat(),
        })

    # Generate remaining shippers normally
    for i in range(n_bad, n_shippers):
        shipper_id = f"SH{i + 1:04d}"
        violation_count = int(np.random.exponential(2))
        total_shipments = random.randint(max(violation_count + 5, 20), 500)
        tier_weights = [0.30, 0.35, 0.25, 0.10]
        tier = random.choices(COMPLIANCE_TIERS, weights=tier_weights, k=1)[0]
        if violation_count > 5:
            tier = random.choices(["C", "D"], weights=[0.5, 0.5], k=1)[0]
        elif violation_count > 2:
            tier = random.choices(["B", "C", "D"],
                                  weights=[0.3, 0.5, 0.2], k=1)[0]
        shippers.append({
            "shipper_id": shipper_id,
            "company_name": fake.company(),
            "registration_country": random.choice(COUNTRIES),
            "years_active": random.randint(1, 30),
            "total_shipments": total_shipments,
            "violation_count": violation_count,
            "compliance_tier": tier,
            "last_audit_date": fake.date_between(
                start_date="-2y", end_date="today"
            ).isoformat(),
        })
    return shippers


def generate_evasion_watchlist(hs_codes):
    """Generate evasion watchlist ensuring some CRITICAL entries for high-risk countries."""
    chapters = list(set(h["chapter"] for h in hs_codes))
    evasion_pairs = []
    used_pairs = set()

    # Ensure CRITICAL entries for high-risk countries
    for country in HIGH_RISK_COUNTRIES[:3]:
        ch = random.choice(chapters)
        pair = (ch, country)
        if pair not in used_pairs:
            used_pairs.add(pair)
            evasion_pairs.append({
                "hs_chapter": ch,
                "country_of_origin": country,
                "evasion_type": random.choice(VIOLATION_TYPES),
                "severity": "CRITICAL",
                "match_score": 1.0,
            })

    # Fill remaining entries
    n_pairs = max(15, len(chapters))
    while len(evasion_pairs) < n_pairs:
        ch = random.choice(chapters)
        co = random.choice(COUNTRIES)
        pair = (ch, co)
        if pair not in used_pairs:
            used_pairs.add(pair)
            severity = random.choice(["HIGH", "MEDIUM", "CRITICAL"])
            evasion_pairs.append({
                "hs_chapter": ch,
                "country_of_origin": co,
                "evasion_type": random.choice(VIOLATION_TYPES),
                "severity": severity,
                "match_score": 1.0 if severity == "CRITICAL" else (
                    0.8 if severity == "HIGH" else 0.5
                ),
            })
    return evasion_pairs


def generate_country_risks():
    """Generate country risk scores."""
    country_risks = {}
    for c in COUNTRIES:
        if c in HIGH_RISK_COUNTRIES:
            country_risks[c] = random.randint(80, 98)
        elif c in ["Vietnam", "China", "India", "Turkey", "Indonesia",
                    "Thailand", "Egypt", "Colombia", "Philippines"]:
            country_risks[c] = random.randint(35, 69)
        else:
            country_risks[c] = random.randint(5, 34)
    return country_risks


def generate_shipments(n_shipments, shippers, hs_codes, evasion_pairs,
                       country_risks):
    """Generate import shipment declarations.

    Constructs ~25% of today's shipments as deliberately high-risk:
    tier-D shipper + evasion-matching HS/country + anomalous valuation.
    """
    shipper_ids = [s["shipper_id"] for s in shippers]
    shipper_map = {s["shipper_id"]: s for s in shippers}
    hs_code_list = [h["hs_code"] for h in hs_codes]
    hs_categories = {h["hs_code"]: h["category"] for h in hs_codes}

    # Build evasion lookup
    evasion_lookup = {}
    for ep in evasion_pairs:
        key = (ep["hs_chapter"], ep["country_of_origin"])
        evasion_lookup[key] = float(ep["match_score"])

    # Find CRITICAL evasion entries for high-risk countries
    critical_combos = [
        (ep["hs_chapter"], ep["country_of_origin"])
        for ep in evasion_pairs
        if ep["severity"] == "CRITICAL"
        and ep["country_of_origin"] in HIGH_RISK_COUNTRIES
    ]

    # Use only the intentionally-created high-risk shippers (first few)
    # These have high violation rates + tier D
    bad_shippers = [s["shipper_id"] for s in shippers
                    if s["compliance_tier"] == "D"
                    and s["violation_count"] >= 10]
    if not bad_shippers:
        bad_shippers = shipper_ids[:2]

    # HS codes by chapter
    hs_by_chapter = {}
    for h in hs_codes:
        hs_by_chapter.setdefault(h["chapter"], []).append(h["hs_code"])

    shipments = []
    target_dt = datetime.strptime(TARGET_DATE, "%Y-%m-%d")
    n_today = max(int(n_shipments * 0.20), 12)
    n_high_risk = max(int(n_today * 0.30), 4)
    n_normal_today = n_today - n_high_risk
    n_other = n_shipments - n_today

    other_dates = []
    for _ in range(n_other):
        offset = random.randint(1, 60)
        d = target_dt - timedelta(days=offset)
        other_dates.append(d.strftime("%Y-%m-%d"))

    idx = 0

    # ── High-risk today shipments ──────────────────────────────────────
    for i in range(n_high_risk):
        idx += 1
        sid = f"IMP{idx:05d}"
        shipper_id = random.choice(bad_shippers)

        if critical_combos:
            chapter, country = critical_combos[i % len(critical_combos)]
            if chapter in hs_by_chapter:
                hs_code = random.choice(hs_by_chapter[chapter])
            else:
                hs_code = random.choice(hs_code_list)
        else:
            hs_code = random.choice(hs_code_list)
            country = random.choice(HIGH_RISK_COUNTRIES)

        category = hs_categories[hs_code]
        bench = CATEGORY_BENCHMARKS.get(category, {"median": 50})
        # Very anomalous valuation: unit price far below median
        anomalous_unit_price = bench["median"] * random.uniform(0.01, 0.08)
        quantity = random.randint(200, 3000)
        declared_value = round(anomalous_unit_price * quantity, 2)
        weight = round(random.uniform(500, 40000), 1)

        shipments.append({
            "shipment_id": sid,
            "shipper_id": shipper_id,
            "hs_code": hs_code,
            "country_of_origin": country,
            "declared_value": declared_value,
            "quantity": quantity,
            "weight_kg": weight,
            "declaration_date": TARGET_DATE,
            "port_of_entry": random.choice(PORTS),
            "commodity_description": f"{category} goods - {fake.catch_phrase()}",
            "consignee_name": fake.company(),
        })

    # ── Normal today shipments ─────────────────────────────────────────
    for i in range(n_normal_today):
        idx += 1
        sid = f"IMP{idx:05d}"
        shipper_id = random.choice(shipper_ids)
        hs_code = random.choice(hs_code_list)
        country = random.choice(COUNTRIES)
        category = hs_categories[hs_code]

        if category in ("Machinery and Electronics", "Vehicles and Transport"):
            base_value = random.uniform(50000, 500000)
        elif category in ("Textiles", "Footwear and Headgear"):
            base_value = random.uniform(5000, 80000)
        else:
            base_value = random.uniform(2000, 200000)

        quantity = random.randint(10, 5000)
        weight = round(random.uniform(100, 50000), 1)

        shipments.append({
            "shipment_id": sid,
            "shipper_id": shipper_id,
            "hs_code": hs_code,
            "country_of_origin": country,
            "declared_value": round(base_value, 2),
            "quantity": quantity,
            "weight_kg": weight,
            "declaration_date": TARGET_DATE,
            "port_of_entry": random.choice(PORTS),
            "commodity_description": f"{category} goods - {fake.catch_phrase()}",
            "consignee_name": fake.company(),
        })

    # ── Historical shipments ───────────────────────────────────────────
    for i in range(n_other):
        idx += 1
        sid = f"IMP{idx:05d}"
        shipper_id = random.choice(shipper_ids)
        hs_code = random.choice(hs_code_list)
        country = random.choice(COUNTRIES)
        category = hs_categories[hs_code]

        if category in ("Machinery and Electronics", "Vehicles and Transport"):
            base_value = random.uniform(50000, 500000)
        elif category in ("Textiles", "Footwear and Headgear"):
            base_value = random.uniform(5000, 80000)
        else:
            base_value = random.uniform(2000, 200000)

        quantity = random.randint(10, 5000)
        weight = round(random.uniform(100, 50000), 1)

        shipments.append({
            "shipment_id": sid,
            "shipper_id": shipper_id,
            "hs_code": hs_code,
            "country_of_origin": country,
            "declared_value": round(base_value, 2),
            "quantity": quantity,
            "weight_kg": weight,
            "declaration_date": other_dates[i],
            "port_of_entry": random.choice(PORTS),
            "commodity_description": f"{category} goods - {fake.catch_phrase()}",
            "consignee_name": fake.company(),
        })

    return shipments


def generate_inspections(n_inspections, shipments, shippers):
    """Generate past inspection results."""
    historical = [s for s in shipments if s["declaration_date"] != TARGET_DATE]
    if not historical:
        historical = shipments[:max(1, len(shipments) // 2)]

    inspections = []
    for i in range(n_inspections):
        shipment = random.choice(historical)
        outcome = random.choices(
            INSPECTION_OUTCOMES, weights=[0.55, 0.30, 0.15], k=1
        )[0]
        violation_type = (
            random.choice(VIOLATION_TYPES) if outcome != "Clean" else None
        )
        penalty = (
            round(random.uniform(500, 50000), 2)
            if outcome == "Major Violation"
            else round(random.uniform(100, 5000), 2)
            if outcome == "Minor Violation"
            else 0.0
        )
        inspections.append({
            "inspection_id": f"INS{i + 1:05d}",
            "shipment_id": shipment["shipment_id"],
            "shipper_id": shipment["shipper_id"],
            "inspection_date": shipment["declaration_date"],
            "outcome": outcome,
            "violation_type": violation_type,
            "penalty_amount": penalty,
        })
    return inspections


def create_database(db_path, shippers, hs_codes, shipments, inspections):
    """Create SQLite database with all tables."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS shippers (
        shipper_id TEXT PRIMARY KEY,
        company_name TEXT,
        registration_country TEXT,
        years_active INTEGER,
        total_shipments INTEGER,
        violation_count INTEGER,
        compliance_tier TEXT,
        last_audit_date TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS hs_codes (
        hs_code TEXT PRIMARY KEY,
        chapter TEXT,
        category TEXT,
        description TEXT,
        standard_duty_rate_pct REAL,
        requires_special_license INTEGER
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS shipments (
        shipment_id TEXT PRIMARY KEY,
        shipper_id TEXT,
        hs_code TEXT,
        country_of_origin TEXT,
        declared_value REAL,
        quantity INTEGER,
        weight_kg REAL,
        declaration_date TEXT,
        port_of_entry TEXT,
        commodity_description TEXT,
        consignee_name TEXT,
        FOREIGN KEY (shipper_id) REFERENCES shippers(shipper_id),
        FOREIGN KEY (hs_code) REFERENCES hs_codes(hs_code)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS inspection_results (
        inspection_id TEXT PRIMARY KEY,
        shipment_id TEXT,
        shipper_id TEXT,
        inspection_date TEXT,
        outcome TEXT,
        violation_type TEXT,
        penalty_amount REAL,
        FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id),
        FOREIGN KEY (shipper_id) REFERENCES shippers(shipper_id)
    )""")

    for s in shippers:
        c.execute(
            "INSERT INTO shippers VALUES (?,?,?,?,?,?,?,?)",
            (s["shipper_id"], s["company_name"], s["registration_country"],
             s["years_active"], s["total_shipments"], s["violation_count"],
             s["compliance_tier"], s["last_audit_date"]),
        )
    for h in hs_codes:
        c.execute(
            "INSERT INTO hs_codes VALUES (?,?,?,?,?,?)",
            (h["hs_code"], h["chapter"], h["category"], h["description"],
             h["standard_duty_rate_pct"], h["requires_special_license"]),
        )
    for s in shipments:
        c.execute(
            "INSERT INTO shipments VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (s["shipment_id"], s["shipper_id"], s["hs_code"],
             s["country_of_origin"], s["declared_value"], s["quantity"],
             s["weight_kg"], s["declaration_date"], s["port_of_entry"],
             s["commodity_description"], s["consignee_name"]),
        )
    for ins in inspections:
        c.execute(
            "INSERT INTO inspection_results VALUES (?,?,?,?,?,?,?)",
            (ins["inspection_id"], ins["shipment_id"], ins["shipper_id"],
             ins["inspection_date"], ins["outcome"], ins["violation_type"],
             ins["penalty_amount"]),
        )

    conn.commit()
    conn.close()


def generate_workspace(workspace, shippers, hs_codes, shipments, inspections,
                       evasion_pairs, country_risks):
    """Generate workspace files: fixed policy files + scalable dossier files."""
    os.makedirs(workspace, exist_ok=True)

    # ── Fixed policy files (do not scale) ──────────────────────────────────

    # 1. anomaly_weights.yaml
    weights = {
        "anomaly_scoring": {
            "threshold": 0.85,
            "weights": {
                "shipper_compliance": 0.25,
                "country_risk": 0.20,
                "evasion_pattern": 0.20,
                "valuation_anomaly": 0.15,
                "dossier_alerts": 0.20,
            },
            "shipper_tier_scores": {
                "A": 0.10,
                "B": 0.30,
                "C": 0.60,
                "D": 0.90,
            },
            "shipper_compliance_blend": {
                "tier_weight": 0.6,
                "violation_rate_weight": 0.4,
                "violation_rate_multiplier": 5.0,
            },
            "dossier_defaults": {
                "missing_dossier_score": 0.50,
                "alert_divisor": 10.0,
            },
        }
    }
    with open(os.path.join(workspace, "anomaly_weights.yaml"), "w") as f:
        yaml.dump(weights, f, default_flow_style=False, sort_keys=False)

    # 2. country_risk_tiers.json
    with open(os.path.join(workspace, "country_risk_tiers.json"), "w") as f:
        json.dump(country_risks, f, indent=2)

    # 3. evasion_watchlist.csv
    evasion_df = pd.DataFrame(evasion_pairs)
    evasion_df.to_csv(
        os.path.join(workspace, "evasion_watchlist.csv"), index=False
    )

    # 4. valuation_benchmarks.md
    lines = [
        "# Commodity Valuation Benchmarks\n",
        "Reference unit prices (USD per unit) for declared value validation.\n",
        "| Category | Min Price/Unit | Max Price/Unit | Median Price/Unit |",
        "|----------|---------------|---------------|-------------------|",
    ]
    for cat in sorted(set(HS_CHAPTERS.values())):
        b = CATEGORY_BENCHMARKS[cat]
        lines.append(
            f"| {cat} | {b['min']:.2f} | {b['max']:.2f} | {b['median']:.2f} |"
        )
    with open(os.path.join(workspace, "valuation_benchmarks.md"), "w") as f:
        f.write("\n".join(lines) + "\n")

    # ── Scalable dossier files ─────────────────────────────────────────────
    n_dossiers = SCALE["num_workspace_files"]
    today_shipper_ids = list(set(
        s["shipper_id"] for s in shipments
        if s["declaration_date"] == TARGET_DATE
    ))
    all_shipper_ids = [s["shipper_id"] for s in shippers]
    # Prioritize today's shippers for dossier coverage
    dossier_shipper_ids = today_shipper_ids[:n_dossiers]
    remaining_needed = n_dossiers - len(dossier_shipper_ids)
    if remaining_needed > 0:
        other_ids = [sid for sid in all_shipper_ids
                     if sid not in dossier_shipper_ids]
        dossier_shipper_ids.extend(other_ids[:remaining_needed])
    dossier_shipper_ids = dossier_shipper_ids[:n_dossiers]

    shipper_map = {s["shipper_id"]: s for s in shippers}

    for sid in dossier_shipper_ids:
        shipper = shipper_map[sid]
        shipper_inspections = [
            ins for ins in inspections if ins["shipper_id"] == sid
        ]
        n_violations_found = sum(
            1 for ins in shipper_inspections if ins["outcome"] != "Clean"
        )
        recent_alert_count = int(np.random.exponential(2))
        pending_investigations = random.randint(0, 3)
        if shipper["compliance_tier"] == "D":
            # Ensure high dossier scores for tier-D shippers
            recent_alert_count = max(recent_alert_count, random.randint(5, 10))
            pending_investigations = max(pending_investigations,
                                         random.randint(3, 5))
        elif shipper["compliance_tier"] == "C":
            recent_alert_count = max(recent_alert_count, random.randint(2, 5))
            pending_investigations = max(pending_investigations,
                                         random.randint(1, 3))

        dossier = {
            "shipper_id": sid,
            "company_name": shipper["company_name"],
            "review_date": TARGET_DATE,
            "recent_alert_count": recent_alert_count,
            "pending_investigations": pending_investigations,
            "historical_violations_found": n_violations_found,
            "compliance_notes": fake.paragraph(nb_sentences=3),
            "last_physical_inspection": fake.date_between(
                start_date="-1y", end_date="today"
            ).isoformat(),
            "watchlist_status": random.choice(
                ["CLEAR", "MONITORING", "FLAGGED"]
            ),
        }
        fname = f"shipper_dossier_{sid}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(dossier, f, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Generate customs inspection task data"
    )
    parser.add_argument("--db_path", required=True, help="Path to SQLite DB")
    parser.add_argument("--workspace", required=True,
                        help="Path to workspace directory")
    args = parser.parse_args()

    random.seed(SEED)
    np.random.seed(SEED)
    Faker.seed(SEED)
    global fake
    fake = Faker()
    Faker.seed(SEED)

    n_rows = SCALE["rows_per_table"]
    n_shippers = max(n_rows // 4, 20)
    n_hs_codes = max(n_rows // 2, 30)

    hs_codes = generate_hs_codes(n_hs_codes)
    shippers = generate_shippers(n_shippers)
    evasion_pairs = generate_evasion_watchlist(hs_codes)
    country_risks = generate_country_risks()

    shipments = generate_shipments(n_rows, shippers, hs_codes,
                                   evasion_pairs, country_risks)
    inspections = generate_inspections(n_rows, shipments, shippers)

    create_database(args.db_path, shippers, hs_codes, shipments, inspections)
    generate_workspace(args.workspace, shippers, hs_codes, shipments,
                       inspections, evasion_pairs, country_risks)

    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")
    print(f"  Shippers: {len(shippers)}")
    print(f"  HS codes: {len(hs_codes)}")
    print(f"  Shipments: {len(shipments)}")
    print(f"  Inspections: {len(inspections)}")
    today_count = sum(
        1 for s in shipments if s["declaration_date"] == TARGET_DATE
    )
    print(f"  Shipments on {TARGET_DATE}: {today_count}")
    ws_files = os.listdir(args.workspace)
    print(f"  Workspace files: {len(ws_files)}")


if __name__ == "__main__":
    main()
