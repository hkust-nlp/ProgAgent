import argparse
import sqlite3
import os
import json
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

try:
    import yaml
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml"])
    import yaml

SCALE = {
    "rows_per_table": 240,
    "num_workspace_files": 40,
}

# ---------------------------------------------------------------------------
# Pool data for deterministic generation
# ---------------------------------------------------------------------------

REGION_POOL = [
    ("East China - Shanghai", "China", "Asia"),
    ("South China - Guangdong", "China", "Asia"),
    ("North China - Beijing", "China", "Asia"),
    ("Central China - Wuhan", "China", "Asia"),
    ("Vietnam - Ho Chi Minh", "Vietnam", "Asia"),
    ("Vietnam - Hanoi", "Vietnam", "Asia"),
    ("Thailand - Bangkok", "Thailand", "Asia"),
    ("India - Tamil Nadu", "India", "Asia"),
    ("India - Maharashtra", "India", "Asia"),
    ("India - Gujarat", "India", "Asia"),
    ("South Korea - Seoul", "South Korea", "Asia"),
    ("Japan - Osaka", "Japan", "Asia"),
    ("Japan - Tokyo", "Japan", "Asia"),
    ("Taiwan - Hsinchu", "Taiwan", "Asia"),
    ("Indonesia - Java", "Indonesia", "Asia"),
    ("Malaysia - Penang", "Malaysia", "Asia"),
    ("Philippines - Manila", "Philippines", "Asia"),
    ("Bangladesh - Dhaka", "Bangladesh", "Asia"),
    ("Pakistan - Karachi", "Pakistan", "Asia"),
    ("Turkey - Istanbul", "Turkey", "Europe"),
    ("Germany - Bavaria", "Germany", "Europe"),
    ("Germany - NRW", "Germany", "Europe"),
    ("Poland - Silesia", "Poland", "Europe"),
    ("Romania - Bucharest", "Romania", "Europe"),
    ("France - Ile-de-France", "France", "Europe"),
    ("UK - Midlands", "United Kingdom", "Europe"),
    ("Sweden - Gothenburg", "Sweden", "Europe"),
    ("Czech Republic - Prague", "Czech Republic", "Europe"),
    ("Italy - Lombardy", "Italy", "Europe"),
    ("Russia - Urals", "Russia", "Europe"),
    ("Ukraine - Kyiv", "Ukraine", "Europe"),
    ("Serbia - Belgrade", "Serbia", "Europe"),
    ("USA - Midwest", "United States", "North America"),
    ("USA - Southeast", "United States", "North America"),
    ("USA - Texas", "United States", "North America"),
    ("Mexico - Monterrey", "Mexico", "North America"),
    ("Mexico - Guadalajara", "Mexico", "North America"),
    ("Canada - Ontario", "Canada", "North America"),
    ("Brazil - Sao Paulo", "Brazil", "South America"),
    ("Brazil - Minas Gerais", "Brazil", "South America"),
    ("Chile - Santiago", "Chile", "South America"),
    ("Colombia - Bogota", "Colombia", "South America"),
    ("Argentina - Buenos Aires", "Argentina", "South America"),
    ("Peru - Lima", "Peru", "South America"),
    ("UAE - Dubai", "UAE", "Middle East"),
    ("Saudi Arabia - Riyadh", "Saudi Arabia", "Middle East"),
    ("Israel - Tel Aviv", "Israel", "Middle East"),
    ("South Africa - Johannesburg", "South Africa", "Africa"),
    ("Morocco - Casablanca", "Morocco", "Africa"),
    ("Nigeria - Lagos", "Nigeria", "Africa"),
    ("Egypt - Cairo", "Egypt", "Africa"),
    ("Kenya - Nairobi", "Kenya", "Africa"),
    ("Ethiopia - Addis Ababa", "Ethiopia", "Africa"),
    ("Kazakhstan - Almaty", "Kazakhstan", "Central Asia"),
    ("Uzbekistan - Tashkent", "Uzbekistan", "Central Asia"),
    ("Australia - Melbourne", "Australia", "Oceania"),
    ("New Zealand - Auckland", "New Zealand", "Oceania"),
]

COUNTRY_RISK = {
    "China": 50, "Vietnam": 52, "Thailand": 35, "India": 48,
    "South Korea": 18, "Japan": 12, "Taiwan": 32, "Indonesia": 45,
    "Malaysia": 30, "Philippines": 48, "Bangladesh": 58, "Pakistan": 62,
    "Turkey": 42, "Germany": 10, "Poland": 22, "Romania": 28,
    "France": 12, "United Kingdom": 11, "Sweden": 8, "Czech Republic": 18,
    "Italy": 15, "Russia": 68, "Ukraine": 75, "Serbia": 35,
    "United States": 8, "Mexico": 38, "Canada": 7,
    "Brazil": 40, "Chile": 28, "Colombia": 44, "Argentina": 48, "Peru": 42,
    "UAE": 22, "Saudi Arabia": 35, "Israel": 42,
    "South Africa": 45, "Morocco": 36, "Nigeria": 62, "Egypt": 52,
    "Kenya": 50, "Ethiopia": 58,
    "Kazakhstan": 50, "Uzbekistan": 55,
    "Australia": 6, "New Zealand": 5,
}

MATERIAL_POOL = [
    ("Copper Wire", "Metals", "kg", 8.50, 3),
    ("Aluminum Sheet", "Metals", "kg", 2.30, 2),
    ("Steel Coil", "Metals", "ton", 650.00, 2),
    ("Titanium Rod", "Metals", "kg", 25.00, 4),
    ("Nickel Ingot", "Metals", "kg", 15.80, 3),
    ("Zinc Plate", "Metals", "kg", 3.20, 2),
    ("Tungsten Powder", "Metals", "kg", 42.00, 4),
    ("Tin Solder", "Metals", "kg", 22.00, 2),
    ("Manganese Ore", "Metals", "ton", 280.00, 3),
    ("Chromium Alloy", "Metals", "kg", 12.50, 3),
    ("Silicon Wafer", "Electronics", "unit", 5.00, 5),
    ("MLCC Capacitor", "Electronics", "unit", 0.05, 4),
    ("OLED Panel", "Electronics", "unit", 35.00, 4),
    ("PCB Board", "Electronics", "unit", 2.50, 3),
    ("Semiconductor Chip", "Electronics", "unit", 8.00, 5),
    ("LED Module", "Electronics", "unit", 1.20, 2),
    ("Power Transistor", "Electronics", "unit", 0.80, 3),
    ("Microcontroller", "Electronics", "unit", 3.50, 4),
    ("Sensor Array", "Electronics", "unit", 12.00, 4),
    ("Connector Assembly", "Electronics", "unit", 0.45, 2),
    ("Polyethylene Resin", "Polymers", "kg", 1.20, 1),
    ("Polycarbonate Pellet", "Polymers", "kg", 3.50, 2),
    ("Nylon 66", "Polymers", "kg", 4.00, 3),
    ("PTFE Sheet", "Polymers", "kg", 18.00, 3),
    ("PVC Compound", "Polymers", "kg", 1.00, 1),
    ("ABS Granule", "Polymers", "kg", 2.20, 1),
    ("Lithium Carbonate", "Chemicals", "kg", 45.00, 5),
    ("Cobalt Sulfate", "Chemicals", "kg", 33.00, 5),
    ("Rare Earth Oxide", "Chemicals", "kg", 120.00, 5),
    ("Epoxy Resin", "Chemicals", "kg", 6.00, 2),
    ("Isopropyl Alcohol", "Chemicals", "L", 1.50, 1),
    ("Sodium Hydroxide", "Chemicals", "L", 0.80, 1),
    ("Carbon Fiber", "Composites", "kg", 22.00, 4),
    ("Fiberglass Mat", "Composites", "kg", 6.00, 2),
    ("Aramid Composite", "Composites", "kg", 55.00, 4),
    ("Graphene Sheet", "Composites", "m2", 200.00, 5),
    ("Kevlar Fabric", "Textiles", "m2", 45.00, 4),
    ("Natural Rubber", "Rubber", "kg", 1.80, 2),
    ("Silicone Rubber", "Rubber", "kg", 7.50, 3),
    ("Borosilicate Glass", "Glass", "kg", 8.00, 2),
    ("Tempered Glass", "Glass", "m2", 12.00, 2),
    ("Ceramic Substrate", "Ceramics", "unit", 4.00, 3),
    ("Zirconia Powder", "Ceramics", "kg", 35.00, 3),
    ("Alumina Disc", "Ceramics", "unit", 6.00, 2),
    ("Cotton Blend", "Textiles", "m2", 3.00, 1),
    ("Polyester Weave", "Textiles", "m2", 2.50, 1),
    ("EPDM Rubber", "Rubber", "kg", 4.50, 2),
    ("Optical Fiber", "Glass", "km", 80.00, 4),
    ("Sulfuric Acid", "Chemicals", "L", 0.25, 1),
    ("Palladium Wire", "Metals", "g", 45.00, 5),
]


# ---------------------------------------------------------------------------
# Data generation helpers
# ---------------------------------------------------------------------------

def generate_regions(n, rng):
    regions = []
    for i in range(n):
        if i < len(REGION_POOL):
            name, country, continent = REGION_POOL[i]
        else:
            base_idx = i % len(REGION_POOL)
            cycle = i // len(REGION_POOL) + 1
            name, country, continent = REGION_POOL[base_idx]
            name = f"{name} Zone {cycle}"
        base_risk = COUNTRY_RISK.get(country, 40)
        risk = int(np.clip(base_risk + rng.randint(-10, 11), 5, 95))
        regions.append((i + 1, name, country, continent, risk))
    return regions


def generate_materials(n, rng):
    materials = []
    for i in range(n):
        if i < len(MATERIAL_POOL):
            name, cat, unit, price, crit = MATERIAL_POOL[i]
        else:
            base_idx = i % len(MATERIAL_POOL)
            cycle = i // len(MATERIAL_POOL)
            name, cat, unit, price, crit = MATERIAL_POOL[base_idx]
            grade = chr(65 + cycle)
            name = f"{name} Grade {grade}"
            price = round(price * (0.8 + rng.random() * 0.4), 2)
            crit = int(np.clip(crit + rng.randint(-1, 2), 1, 5))
        materials.append((i + 1, name, cat, unit, price, crit))
    return materials


def generate_suppliers(n, fake, rng, num_regions, num_materials):
    suppliers = []
    used_names = set()
    for i in range(n):
        name = fake.company()
        while name in used_names:
            name = fake.company()
        used_names.add(name)
        region_id = int(rng.randint(1, num_regions + 1))
        material_id = int(rng.randint(1, num_materials + 1))
        start_year = int(rng.randint(2018, 2024))
        start_month = int(rng.randint(1, 13))
        start_date = f"{start_year}-{start_month:02d}-01"
        end_year = start_year + int(rng.randint(2, 6))
        end_date = f"{end_year}-{start_month:02d}-01"
        r = rng.random()
        if r < 0.75:
            status = "active"
        elif r < 0.90:
            status = "probation"
        else:
            status = "inactive"
        suppliers.append((i + 1, name, region_id, material_id, start_date, end_date, status))
    return suppliers


def generate_delivery_records(n, rng, suppliers):
    """Generate delivery records with per-supplier reliability profiles."""
    reliability = {}
    for s in suppliers:
        reliability[s[0]] = 0.3 + rng.random() * 0.65

    records = []
    base_date = datetime(2024, 1, 1)
    for i in range(n):
        s = suppliers[int(rng.randint(0, len(suppliers)))]
        sid = s[0]
        mid = s[3]  # primary material

        order_offset = int(rng.randint(0, 730))
        order_date = base_date + timedelta(days=order_offset)
        lead_days = int(rng.randint(7, 46))
        promised_date = order_date + timedelta(days=lead_days)

        rel = reliability[sid]
        delay = max(0, int(rng.normal(loc=(1 - rel) * 15, scale=5)))
        actual_date = promised_date + timedelta(days=delay)

        qty_ordered = round(float(rng.uniform(100, 5000)), 1)
        shortfall_rate = max(0.0, float(rng.normal(loc=(1 - rel) * 0.10, scale=0.04)))
        qty_delivered = round(qty_ordered * (1 - shortfall_rate), 1)

        records.append((
            i + 1, sid, mid,
            order_date.strftime("%Y-%m-%d"),
            promised_date.strftime("%Y-%m-%d"),
            actual_date.strftime("%Y-%m-%d"),
            qty_ordered, qty_delivered,
        ))
    return records


def generate_forecasts(num_materials, rng):
    """Four quarterly forecasts per material."""
    periods = ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]
    records = []
    fid = 1
    for mid in range(1, num_materials + 1):
        base_qty = float(rng.uniform(500, 20000))
        trend = float(rng.normal(0.0, 0.12))  # per-quarter growth rate
        for pi, period in enumerate(periods):
            qty = round(base_qty * (1 + trend * pi), 1)
            confidence = round(float(rng.uniform(0.60, 0.99)), 2)
            records.append((fid, mid, period, qty, confidence))
            fid += 1
    return records


def generate_alternates(n_suppliers, rng, suppliers):
    """Generate alternate supplier entries; some suppliers get 0, some 1-3."""
    statuses = ["qualified", "pending", "failed"]
    records = []
    aid = 1
    supplier_ids = [s[0] for s in suppliers]
    for s in suppliers:
        sid = s[0]
        n_alts = int(rng.choice([0, 0, 0, 1, 1, 1, 2, 2, 3]))
        candidates = [x for x in supplier_ids if x != sid]
        if n_alts > len(candidates):
            n_alts = len(candidates)
        chosen = list(rng.choice(candidates, size=n_alts, replace=False)) if n_alts > 0 else []
        for alt_sid in chosen:
            status = statuses[int(rng.randint(0, 3))]
            year = int(rng.randint(2023, 2026))
            month = int(rng.randint(1, 13))
            q_date = f"{year}-{month:02d}-15"
            cap = round(float(rng.uniform(10, 80)), 1)
            mid = s[3]
            records.append((aid, sid, mid, int(alt_sid), status, q_date, cap))
            aid += 1
    return records


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def create_tables(conn):
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS regions (
            region_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            country TEXT NOT NULL,
            continent TEXT NOT NULL,
            base_risk_score REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS materials (
            material_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            unit TEXT NOT NULL,
            base_price_usd REAL NOT NULL,
            criticality_level INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS suppliers (
            supplier_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            region_id INTEGER NOT NULL REFERENCES regions(region_id),
            primary_material_id INTEGER NOT NULL REFERENCES materials(material_id),
            contract_start_date TEXT NOT NULL,
            contract_end_date TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS delivery_records (
            record_id INTEGER PRIMARY KEY,
            supplier_id INTEGER NOT NULL REFERENCES suppliers(supplier_id),
            material_id INTEGER NOT NULL REFERENCES materials(material_id),
            order_date TEXT NOT NULL,
            promised_date TEXT NOT NULL,
            actual_delivery_date TEXT NOT NULL,
            quantity_ordered REAL NOT NULL,
            quantity_delivered REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS consumption_forecasts (
            forecast_id INTEGER PRIMARY KEY,
            material_id INTEGER NOT NULL REFERENCES materials(material_id),
            period TEXT NOT NULL,
            forecasted_qty REAL NOT NULL,
            confidence_level REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS alternate_suppliers (
            alt_id INTEGER PRIMARY KEY,
            primary_supplier_id INTEGER NOT NULL REFERENCES suppliers(supplier_id),
            material_id INTEGER NOT NULL REFERENCES materials(material_id),
            alt_supplier_id INTEGER NOT NULL REFERENCES suppliers(supplier_id),
            qualification_status TEXT NOT NULL,
            qualification_date TEXT NOT NULL,
            max_capacity_pct REAL NOT NULL
        );
    """)
    conn.commit()


def insert_data(conn, regions, materials, suppliers, deliveries, forecasts, alternates):
    c = conn.cursor()
    c.executemany("INSERT INTO regions VALUES (?,?,?,?,?)", regions)
    c.executemany("INSERT INTO materials VALUES (?,?,?,?,?,?)", materials)
    c.executemany("INSERT INTO suppliers VALUES (?,?,?,?,?,?,?)", suppliers)
    c.executemany("INSERT INTO delivery_records VALUES (?,?,?,?,?,?,?,?)", deliveries)
    c.executemany("INSERT INTO consumption_forecasts VALUES (?,?,?,?,?)", forecasts)
    c.executemany("INSERT INTO alternate_suppliers VALUES (?,?,?,?,?,?,?)", alternates)
    conn.commit()


# ---------------------------------------------------------------------------
# Workspace: fixed configuration files
# ---------------------------------------------------------------------------

def generate_config_files(workspace):
    # risk_scoring_config.yaml
    config = {
        "weights": {
            "delivery_performance": 0.25,
            "geopolitical_risk": 0.20,
            "material_criticality": 0.15,
            "supply_alternative": 0.15,
            "quality_compliance": 0.15,
            "financial_health": 0.10,
        },
        "risk_tiers": {
            "critical": {"min_score": 75, "urgency_days": 7},
            "high": {"min_score": 50, "urgency_days": 30},
            "medium": {"min_score": 30, "urgency_days": 90},
        },
        "late_delivery_threshold_days": 3,
        "quantity_shortfall_threshold_pct": 5,
    }
    with open(os.path.join(workspace, "risk_scoring_config.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # mitigation_playbook.json
    playbook = {
        "actions": {
            "delivery_performance": {
                "critical": "Activate emergency backup supplier and impose contractual penalties",
                "high": "Implement weekly delivery monitoring and escalate to supplier management",
                "medium": "Increase safety stock levels and schedule quarterly performance review",
            },
            "geopolitical_risk": {
                "critical": "Immediately dual-source from low-risk region and begin supplier transition",
                "high": "Develop regional diversification plan and pre-qualify alternate suppliers",
                "medium": "Monitor geopolitical developments and update contingency plans",
            },
            "material_criticality": {
                "critical": "Secure long-term supply contracts and explore material substitution R&D",
                "high": "Build strategic inventory buffer and negotiate priority allocation agreements",
                "medium": "Review consumption forecasts quarterly and optimize usage efficiency",
            },
            "supply_alternative": {
                "critical": "Fast-track qualification of at least two alternate suppliers within 60 days",
                "high": "Initiate alternate supplier qualification process and capacity assessment",
                "medium": "Maintain updated list of potential alternates and conduct annual reviews",
            },
            "quality_compliance": {
                "critical": "Suspend shipments pending quality audit and require corrective action plan",
                "high": "Deploy on-site quality inspectors and increase incoming inspection rate",
                "medium": "Schedule additional quality audits and review compliance documentation",
            },
            "financial_health": {
                "critical": "Require financial guarantees and begin transitioning volume to stable suppliers",
                "high": "Increase financial monitoring frequency and establish escrow arrangements",
                "medium": "Request quarterly financial statements and monitor credit rating changes",
            },
        }
    }
    with open(os.path.join(workspace, "mitigation_playbook.json"), "w") as f:
        json.dump(playbook, f, indent=2)

    # criticality_matrix.csv
    with open(os.path.join(workspace, "criticality_matrix.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["criticality_level", "base_risk_score", "label"])
        w.writerow([1, 10, "Low"])
        w.writerow([2, 25, "Moderate"])
        w.writerow([3, 45, "Significant"])
        w.writerow([4, 65, "High"])
        w.writerow([5, 85, "Extreme"])


# ---------------------------------------------------------------------------
# Workspace: scalable data files
# ---------------------------------------------------------------------------

def _distribute(items, n_files):
    """Round-robin distribute items across n_files buckets."""
    buckets = [[] for _ in range(n_files)]
    for i, item in enumerate(items):
        buckets[i % n_files].append(item)
    return buckets


def generate_scalable_files(workspace, nwf, fake, rng, conn, suppliers, regions, materials):
    n_audit = max(1, nwf * 3 // 10)
    n_intel = max(1, nwf * 3 // 10)
    n_demand = max(1, nwf * 2 // 10)
    n_fin = nwf - n_audit - n_intel - n_demand

    supplier_ids = [s[0] for s in suppliers]
    region_ids = [r[0] for r in regions]
    material_ids = [m[0] for m in materials]

    # --- Audit reports (CSV) ---
    audit_buckets = _distribute(supplier_ids, n_audit)
    findings_pool = [
        "No issues found",
        "Minor documentation gaps",
        "Labeling irregularities noted",
        "Packaging quality below standard",
        "Environmental compliance concerns",
        "Worker safety protocols incomplete",
        "Traceability records missing",
        "Calibration certificates expired",
        "Storage conditions suboptimal",
        "Failed incoming material test",
    ]
    for idx, bucket in enumerate(audit_buckets):
        path = os.path.join(workspace, f"audit_report_{idx + 1}.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["supplier_id", "audit_date", "quality_score", "compliance_flag", "findings"])
            for sid in bucket:
                year = int(rng.choice([2025, 2026]))
                month = int(rng.randint(1, 13))
                day = int(rng.randint(1, 29))
                audit_date = f"{year}-{month:02d}-{day:02d}"
                quality_score = round(float(rng.uniform(40, 98)), 1)
                compliance_flag = int(rng.random() > 0.20)
                finding = findings_pool[int(rng.randint(0, len(findings_pool)))]
                w.writerow([sid, audit_date, quality_score, compliance_flag, finding])

    # --- Regional intelligence (JSON) ---
    intel_buckets = _distribute(region_ids, n_intel)
    for idx, bucket in enumerate(intel_buckets):
        entries = []
        for rid in bucket:
            sanctions = bool(rng.random() < 0.15)
            restriction = int(rng.randint(0, 4))
            trend = str(rng.choice(["improving", "stable", "stable", "declining"]))
            entries.append({
                "region_id": int(rid),
                "sanctions_active": sanctions,
                "trade_restriction_level": restriction,
                "political_stability_trend": trend,
            })
        path = os.path.join(workspace, f"regional_intel_{idx + 1}.json")
        with open(path, "w") as f:
            json.dump(entries, f, indent=2)

    # --- Demand adjustment (YAML) ---
    demand_buckets = _distribute(material_ids, n_demand)
    reasons_pool = [
        "Projected increase in automotive sector demand",
        "Market oversupply expected in next quarter",
        "New regulatory requirements driving adoption",
        "Seasonal demand pattern adjustment",
        "Customer base expansion in Asia-Pacific",
        "Technology substitution reducing demand",
        "Infrastructure build-out accelerating consumption",
        "Post-pandemic inventory normalization",
    ]
    for idx, bucket in enumerate(demand_buckets):
        adjustments = []
        for mid in bucket:
            factor = round(float(rng.uniform(0.70, 1.50)), 2)
            reason = reasons_pool[int(rng.randint(0, len(reasons_pool)))]
            adjustments.append({
                "material_id": int(mid),
                "adjustment_factor": float(factor),
                "reason": reason,
            })
        data = {"adjustments": adjustments}
        path = os.path.join(workspace, f"demand_adjustment_{idx + 1}.yaml")
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    # --- Supplier financials (TXT) ---
    fin_buckets = _distribute(supplier_ids, n_fin)
    supplier_name_map = {s[0]: s[1] for s in suppliers}
    for idx, bucket in enumerate(fin_buckets):
        lines = []
        for sid in bucket:
            rating = str(rng.choice(["A", "A", "B", "B", "B", "C", "C", "D"]))
            trend = str(rng.choice(["growing", "stable", "stable", "declining"]))
            debt_ratio = round(float(rng.uniform(0.05, 0.92)), 2)
            year = int(rng.choice([2025, 2026]))
            month = int(rng.randint(1, 13))
            day = int(rng.randint(1, 29))
            assess_date = f"{year}-{month:02d}-{day:02d}"
            lines.append(f"Supplier ID: {sid}")
            lines.append(f"Supplier Name: {supplier_name_map[sid]}")
            lines.append(f"Credit Rating: {rating}")
            lines.append(f"Revenue Trend: {trend}")
            lines.append(f"Debt Ratio: {debt_ratio}")
            lines.append(f"Last Assessment: {assess_date}")
            lines.append("")
        path = os.path.join(workspace, f"supplier_financials_{idx + 1}.txt")
        with open(path, "w") as f:
            f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    rng = np.random.RandomState(42)
    Faker.seed(42)
    fake = Faker()

    os.makedirs(args.workspace, exist_ok=True)

    rpt = SCALE["rows_per_table"]
    nwf = SCALE["num_workspace_files"]

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    regions = generate_regions(rpt, rng)
    materials = generate_materials(rpt, rng)
    suppliers = generate_suppliers(rpt, fake, rng, len(regions), len(materials))
    deliveries = generate_delivery_records(rpt * 6, rng, suppliers)
    forecasts = generate_forecasts(len(materials), rng)
    alternates = generate_alternates(rpt, rng, suppliers)

    insert_data(conn, regions, materials, suppliers, deliveries, forecasts, alternates)

    generate_config_files(args.workspace)
    generate_scalable_files(args.workspace, nwf, fake, rng, conn, suppliers, regions, materials)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
