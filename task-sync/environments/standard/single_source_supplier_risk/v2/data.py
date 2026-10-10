"""
Data generation script for single-source supplier risk monitoring task.
Generates database tables and workspace files for the evaluation environment.
"""

import argparse
import json
import os
import sqlite3
import yaml

import numpy as np
import pandas as pd
from faker import Faker

# ── Scale parameters (v0 base) ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 400,       # v2 = 4x base
    "num_workspace_files": 30,   # v2 = base + 2N (N=10)
}

# ── Deterministic seeds ─────────────────────────────────────────────────────
SEED = 42
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ── Reference data ──────────────────────────────────────────────────────────
COUNTRIES_DATA = [
    ("United States", "Americas", 15, 8.2, 1, 0),
    ("Canada", "Americas", 12, 8.5, 1, 0),
    ("Mexico", "Americas", 35, 5.8, 2, 0),
    ("Brazil", "Americas", 42, 5.2, 2, 0),
    ("Argentina", "Americas", 48, 4.8, 3, 0),
    ("Germany", "Europe", 10, 8.8, 1, 0),
    ("France", "Europe", 14, 8.4, 1, 0),
    ("United Kingdom", "Europe", 13, 8.3, 1, 0),
    ("Italy", "Europe", 22, 7.2, 1, 0),
    ("Spain", "Europe", 20, 7.4, 1, 0),
    ("Poland", "Europe", 25, 6.8, 1, 0),
    ("Turkey", "Europe", 55, 4.5, 3, 0),
    ("Russia", "Europe", 78, 2.8, 4, 1),
    ("China", "Asia", 45, 5.0, 3, 0),
    ("Japan", "Asia", 8, 9.0, 1, 0),
    ("South Korea", "Asia", 18, 7.8, 1, 0),
    ("India", "Asia", 48, 5.0, 2, 0),
    ("Vietnam", "Asia", 40, 5.5, 2, 0),
    ("Thailand", "Asia", 32, 6.0, 2, 0),
    ("Taiwan", "Asia", 35, 6.2, 2, 0),
    ("Indonesia", "Asia", 50, 4.8, 3, 0),
    ("Malaysia", "Asia", 28, 6.5, 2, 0),
    ("Philippines", "Asia", 44, 5.2, 2, 0),
    ("South Africa", "Africa", 52, 4.5, 3, 0),
    ("Nigeria", "Africa", 68, 3.2, 4, 0),
    ("Egypt", "Africa", 58, 4.0, 3, 0),
    ("Kenya", "Africa", 55, 4.2, 3, 0),
    ("Saudi Arabia", "Middle East", 42, 5.5, 2, 0),
    ("UAE", "Middle East", 20, 7.5, 1, 0),
    ("Israel", "Middle East", 45, 6.0, 3, 0),
    ("Australia", "Oceania", 9, 8.8, 1, 0),
    ("New Zealand", "Oceania", 7, 9.0, 1, 0),
]

COMPONENT_BASES = [
    ("Capacitor", "Electronics"), ("Resistor", "Electronics"),
    ("Inductor", "Electronics"), ("Transistor", "Electronics"),
    ("Diode", "Electronics"), ("IC Chip", "Electronics"),
    ("PCB Board", "Electronics"), ("Connector", "Electronics"),
    ("Microcontroller", "Semiconductor"), ("Memory Module", "Semiconductor"),
    ("FPGA Unit", "Semiconductor"), ("Power IC", "Semiconductor"),
    ("Steel Alloy", "Materials"), ("Aluminum Sheet", "Materials"),
    ("Copper Wire", "Materials"), ("Titanium Rod", "Materials"),
    ("Carbon Fiber", "Materials"), ("Ceramic Plate", "Materials"),
    ("Bearing Assembly", "Mechanical"), ("Gear Module", "Mechanical"),
    ("Shaft Coupling", "Mechanical"), ("Hydraulic Valve", "Mechanical"),
    ("Spring Set", "Mechanical"), ("Fastener Kit", "Mechanical"),
    ("Epoxy Resin", "Chemical"), ("Adhesive Compound", "Chemical"),
    ("Solvent Mix", "Chemical"), ("Coating Agent", "Chemical"),
    ("Optical Lens", "Optical"), ("Fiber Cable", "Optical"),
    ("LED Module", "Optical"), ("Sensor Array", "Optical"),
    ("Heat Sink", "Thermal"), ("Thermal Paste", "Thermal"),
    ("Cooling Fan", "Thermal"), ("Heat Exchanger", "Thermal"),
    ("Battery Cell", "Power"), ("Power Supply", "Power"),
    ("Transformer", "Power"), ("Voltage Regulator", "Power"),
]

CRITICALITY_LEVELS = ["A", "B", "C"]
PO_STATUSES = ["delivered", "delivered", "delivered", "delivered", "pending", "cancelled"]

REGIONS_MAP = {}
for c, r, *_ in COUNTRIES_DATA:
    REGIONS_MAP[c] = r


def generate_component_name(base_name: str, variant: int) -> str:
    """Generate a unique component name with variant suffix."""
    series = ["X", "Z", "Q", "M", "R", "P", "V", "T", "S", "N"]
    s = series[variant % len(series)]
    num = 100 + (variant // len(series)) * 100 + variant * 7
    return f"{base_name} {s}-{num}"


def create_tables(conn: sqlite3.Connection):
    """Create all database tables."""
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            supplier_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            country TEXT NOT NULL,
            region TEXT NOT NULL,
            established_year INTEGER,
            contact_email TEXT,
            primary_product_category TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS components (
            component_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            subcategory TEXT,
            unit_cost REAL,
            criticality_level TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS purchase_orders (
            po_id TEXT PRIMARY KEY,
            supplier_id TEXT NOT NULL,
            component_id TEXT NOT NULL,
            order_date TEXT NOT NULL,
            quantity INTEGER,
            unit_price REAL,
            total_amount REAL,
            status TEXT,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
            FOREIGN KEY (component_id) REFERENCES components(component_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            component_id TEXT PRIMARY KEY,
            quantity_on_hand INTEGER,
            daily_usage_rate REAL,
            reorder_point INTEGER,
            last_updated TEXT,
            FOREIGN KEY (component_id) REFERENCES components(component_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS country_risks (
            country TEXT PRIMARY KEY,
            risk_index REAL,
            political_stability REAL,
            trade_openness_level INTEGER,
            sanctions_flag INTEGER
        )
    """)
    conn.commit()


def populate_country_risks(conn: sqlite3.Connection):
    """Insert country risk data."""
    c = conn.cursor()
    for country, region, risk_idx, stability, trade_lvl, sanctions in COUNTRIES_DATA:
        c.execute(
            "INSERT INTO country_risks VALUES (?, ?, ?, ?, ?)",
            (country, float(risk_idx), stability, trade_lvl, sanctions)
        )
    conn.commit()


def populate_suppliers(conn: sqlite3.Connection, rng: np.random.RandomState) -> pd.DataFrame:
    """Generate and insert supplier records."""
    n = SCALE["rows_per_table"]
    countries = [c[0] for c in COUNTRIES_DATA]
    categories = list(set(cat for _, cat in COMPONENT_BASES))

    rows = []
    for i in range(n):
        sid = f"SUP-{i+1:04d}"
        name = fake.company()
        country = countries[rng.randint(0, len(countries))]
        region = REGIONS_MAP[country]
        year = int(rng.randint(1960, 2022))
        email = fake.company_email()
        cat = categories[rng.randint(0, len(categories))]
        rows.append((sid, name, country, region, year, email, cat))

    c = conn.cursor()
    c.executemany("INSERT INTO suppliers VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    return pd.DataFrame(rows, columns=[
        "supplier_id", "name", "country", "region",
        "established_year", "contact_email", "primary_product_category"
    ])


def populate_components(conn: sqlite3.Connection, rng: np.random.RandomState) -> pd.DataFrame:
    """Generate and insert component records."""
    n = SCALE["rows_per_table"]
    rows = []
    for i in range(n):
        cid = f"CMP-{i+1:04d}"
        base_idx = i % len(COMPONENT_BASES)
        base_name, category = COMPONENT_BASES[base_idx]
        variant = i // len(COMPONENT_BASES)
        name = generate_component_name(base_name, variant)
        subcategory = base_name
        unit_cost = round(float(rng.uniform(0.5, 500.0)), 2)
        criticality = CRITICALITY_LEVELS[rng.randint(0, 3)]
        rows.append((cid, name, category, subcategory, unit_cost, criticality))

    c = conn.cursor()
    c.executemany("INSERT INTO components VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    return pd.DataFrame(rows, columns=[
        "component_id", "name", "category", "subcategory", "unit_cost", "criticality_level"
    ])


def populate_purchase_orders(
    conn: sqlite3.Connection,
    suppliers_df: pd.DataFrame,
    components_df: pd.DataFrame,
    rng: np.random.RandomState,
) -> tuple:
    """
    Generate POs. ~40% of components get exactly 1 supplier (single-source).
    Returns (po_dataframe, component_supplier_map).
    """
    n_components = len(components_df)
    n_suppliers = len(suppliers_df)
    supplier_ids = suppliers_df["supplier_id"].tolist()

    # Decide how many suppliers each component has
    component_supplier_map = {}
    for i in range(n_components):
        cid = components_df.iloc[i]["component_id"]
        if rng.random() < 0.40:
            num_sup = 1
        else:
            num_sup = int(rng.randint(2, min(5, n_suppliers) + 1))
        chosen = rng.choice(n_suppliers, size=num_sup, replace=False)
        component_supplier_map[cid] = [supplier_ids[j] for j in chosen]

    # Generate POs to hit at least SCALE["rows_per_table"] rows
    target_pos = max(SCALE["rows_per_table"], n_components * 5)
    rows = []
    po_counter = 0

    # First pass: ensure every component-supplier pair has at least 1 PO
    for cid, sups in component_supplier_map.items():
        for sid in sups:
            po_counter += 1
            po_id = f"PO-{po_counter:06d}"
            days_back = int(rng.randint(30, 730))
            order_date = (pd.Timestamp("2026-04-01") - pd.Timedelta(days=days_back)).strftime("%Y-%m-%d")
            qty = int(rng.randint(10, 5000))
            price = round(float(rng.uniform(1.0, 300.0)), 2)
            total = round(qty * price, 2)
            status = PO_STATUSES[rng.randint(0, len(PO_STATUSES))]
            rows.append((po_id, sid, cid, order_date, qty, price, total, status))

    # Second pass: fill remaining POs randomly
    component_ids = components_df["component_id"].tolist()
    while len(rows) < target_pos:
        po_counter += 1
        po_id = f"PO-{po_counter:06d}"
        cid = component_ids[rng.randint(0, n_components)]
        sups = component_supplier_map[cid]
        sid = sups[rng.randint(0, len(sups))]
        days_back = int(rng.randint(30, 730))
        order_date = (pd.Timestamp("2026-04-01") - pd.Timedelta(days=days_back)).strftime("%Y-%m-%d")
        qty = int(rng.randint(10, 5000))
        price = round(float(rng.uniform(1.0, 300.0)), 2)
        total = round(qty * price, 2)
        status = PO_STATUSES[rng.randint(0, len(PO_STATUSES))]
        rows.append((po_id, sid, cid, order_date, qty, price, total, status))

    c = conn.cursor()
    c.executemany("INSERT INTO purchase_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    return (
        pd.DataFrame(rows, columns=[
            "po_id", "supplier_id", "component_id", "order_date",
            "quantity", "unit_price", "total_amount", "status"
        ]),
        component_supplier_map,
    )


def populate_inventory(
    conn: sqlite3.Connection,
    components_df: pd.DataFrame,
    rng: np.random.RandomState,
) -> pd.DataFrame:
    """Generate inventory records for every component."""
    rows = []
    for i in range(len(components_df)):
        cid = components_df.iloc[i]["component_id"]
        daily_rate = round(float(rng.uniform(5.0, 200.0)), 1)
        # Some components deliberately have low stock
        if rng.random() < 0.30:
            qty = int(daily_rate * rng.uniform(2, 20))
        else:
            qty = int(daily_rate * rng.uniform(20, 90))
        reorder = int(daily_rate * 14)
        last_upd = (pd.Timestamp("2026-04-01") - pd.Timedelta(days=int(rng.randint(0, 14)))).strftime("%Y-%m-%d")
        rows.append((cid, qty, daily_rate, reorder, last_upd))

    c = conn.cursor()
    c.executemany("INSERT INTO inventory VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    return pd.DataFrame(rows, columns=[
        "component_id", "quantity_on_hand", "daily_usage_rate", "reorder_point", "last_updated"
    ])


# ── Workspace file generators ───────────────────────────────────────────────

def _split_indices(n_items: int, n_files: int):
    """Split item indices into roughly equal chunks for n_files."""
    indices = list(range(n_items))
    chunk_size = max(1, len(indices) // n_files)
    chunks = []
    for i in range(n_files):
        start = i * chunk_size
        if i == n_files - 1:
            chunks.append(indices[start:])
        else:
            chunks.append(indices[start:start + chunk_size])
    return [c for c in chunks if c]


def _file_distribution(n_total: int):
    """Return (n_financial, n_alternates, n_audits, n_leadtimes)."""
    n_fin = max(1, n_total * 3 // 10)
    n_alt = max(1, n_total * 3 // 10)
    n_aud = max(1, n_total * 2 // 10)
    n_lt = n_total - n_fin - n_alt - n_aud
    if n_lt < 1:
        n_lt = 1
        n_fin = n_total - n_alt - n_aud - n_lt
    return n_fin, n_alt, n_aud, n_lt


def generate_financial_files(
    workspace: str,
    suppliers_df: pd.DataFrame,
    rng: np.random.RandomState,
    n_files: int,
) -> dict:
    """Generate supplier financial health CSV files. Returns {supplier_id: score}."""
    n = len(suppliers_df)
    scores = {}
    # Deliberately give ~25% of suppliers low financial health
    for i in range(n):
        sid = suppliers_df.iloc[i]["supplier_id"]
        if rng.random() < 0.25:
            scores[sid] = round(float(rng.uniform(15, 45)), 1)
        else:
            scores[sid] = round(float(rng.uniform(45, 95)), 1)

    chunks = _split_indices(n, n_files)
    for file_idx, idx_chunk in enumerate(chunks):
        rows = []
        for i in idx_chunk:
            row = suppliers_df.iloc[i]
            sid = row["supplier_id"]
            fhs = scores[sid]
            credit = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC"][
                min(6, int((100 - fhs) / 15))
            ]
            dte = round(float(rng.uniform(0.1, 3.5)), 2)
            rev_growth = round(float(rng.uniform(-15, 25)), 1)
            rows.append({
                "supplier_id": sid,
                "financial_health_score": fhs,
                "credit_rating": credit,
                "debt_to_equity": dte,
                "revenue_growth_pct": rev_growth,
            })
        df = pd.DataFrame(rows)
        path = os.path.join(workspace, f"supplier_financials_part_{file_idx+1}.csv")
        df.to_csv(path, index=False)

    return scores


def generate_alternate_files(
    workspace: str,
    components_df: pd.DataFrame,
    component_supplier_map: dict,
    rng: np.random.RandomState,
    n_files: int,
):
    """Generate component alternate-supplier JSON files. Returns {cid: num_alternates}."""
    n = len(components_df)
    alternates = {}
    qual_statuses = ["qualified", "under_evaluation", "not_qualified", "none_identified"]

    for i in range(n):
        cid = components_df.iloc[i]["component_id"]
        n_current = len(component_supplier_map.get(cid, []))
        if n_current == 1:
            # Single-source: some have known alternates, some don't
            if rng.random() < 0.35:
                num_alt = 0
                qual = "none_identified"
            elif rng.random() < 0.5:
                num_alt = int(rng.randint(1, 3))
                qual = "under_evaluation"
            else:
                num_alt = int(rng.randint(1, 4))
                qual = "qualified"
        else:
            num_alt = n_current - 1
            qual = "qualified"
        alternates[cid] = {"num_known_alternates": num_alt, "qualification_status": qual}

    chunks = _split_indices(n, n_files)
    for file_idx, idx_chunk in enumerate(chunks):
        records = []
        for i in idx_chunk:
            cid = components_df.iloc[i]["component_id"]
            info = alternates[cid]
            records.append({
                "component_id": cid,
                "component_name": components_df.iloc[i]["name"],
                "num_known_alternates": info["num_known_alternates"],
                "qualification_status": info["qualification_status"],
            })
        path = os.path.join(workspace, f"component_alternates_part_{file_idx+1}.json")
        with open(path, "w") as f:
            json.dump(records, f, indent=2)

    return alternates


def generate_audit_files(
    workspace: str,
    suppliers_df: pd.DataFrame,
    rng: np.random.RandomState,
    n_files: int,
) -> dict:
    """Generate supplier quality audit TXT files. Returns {supplier_id: quality_score}."""
    n = len(suppliers_df)
    quality_scores = {}
    findings_templates = [
        "All quality metrics within acceptable range. Documentation complete.",
        "Minor deviations noted in batch testing procedures. Follow-up scheduled.",
        "Quality management system certifications current. No major findings.",
        "Some inconsistencies in incoming material inspection records.",
        "Significant gaps in quality control documentation identified.",
        "Corrective actions from previous audit still pending resolution.",
        "Excellent process controls and traceability systems observed.",
        "Non-conformance rate above target threshold for two consecutive quarters.",
        "Supplier demonstrates strong commitment to continuous improvement.",
        "Failure to meet delivery quality standards on three recent shipments.",
    ]

    for i in range(n):
        sid = suppliers_df.iloc[i]["supplier_id"]
        if rng.random() < 0.20:
            quality_scores[sid] = round(float(rng.uniform(25, 50)), 1)
        else:
            quality_scores[sid] = round(float(rng.uniform(50, 98)), 1)

    chunks = _split_indices(n, n_files)
    for file_idx, idx_chunk in enumerate(chunks):
        lines = [f"Supplier Quality Audit Report - Part {file_idx+1}", "=" * 50, ""]
        for i in idx_chunk:
            row = suppliers_df.iloc[i]
            sid = row["supplier_id"]
            qs = quality_scores[sid]
            audit_date = (pd.Timestamp("2026-03-01") - pd.Timedelta(days=int(rng.randint(0, 180)))).strftime("%Y-%m-%d")
            finding = findings_templates[rng.randint(0, len(findings_templates))]
            lines.append(f"Supplier: {sid} | Quality Score: {qs} | Audit Date: {audit_date}")
            lines.append(f"Findings: {finding}")
            lines.append("")
        path = os.path.join(workspace, f"quality_audits_part_{file_idx+1}.txt")
        with open(path, "w") as f:
            f.write("\n".join(lines))

    return quality_scores


def generate_leadtime_files(
    workspace: str,
    components_df: pd.DataFrame,
    rng: np.random.RandomState,
    n_files: int,
) -> dict:
    """Generate component lead-time YAML files. Returns {cid: lead_time_days}."""
    n = len(components_df)
    lead_times = {}
    for i in range(n):
        cid = components_df.iloc[i]["component_id"]
        lead_times[cid] = int(rng.randint(7, 90))

    chunks = _split_indices(n, n_files)
    for file_idx, idx_chunk in enumerate(chunks):
        records = []
        for i in idx_chunk:
            cid = components_df.iloc[i]["component_id"]
            lt = lead_times[cid]
            variability = int(rng.randint(1, max(2, lt // 3)))
            records.append({
                "component_id": cid,
                "lead_time_days": lt,
                "variability_days": variability,
            })
        path = os.path.join(workspace, f"lead_times_part_{file_idx+1}.yaml")
        with open(path, "w") as f:
            yaml.dump(records, f, default_flow_style=False, sort_keys=False)

    return lead_times


def generate_fixed_config_files(workspace: str):
    """Generate task-inherent configuration files (not scaled)."""
    # risk_config.yaml
    config = {
        "risk_weights": {
            "financial_health": 0.30,
            "geopolitical_risk": 0.25,
            "inventory_risk": 0.25,
            "quality_score": 0.20,
        },
        "thresholds": {
            "inventory_buffer_days": 60,
        },
        "risk_tiers": {
            "Critical": 70,
            "High": 50,
            "Medium": 30,
        },
    }
    with open(os.path.join(workspace, "risk_config.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # scoring_policy.md
    policy = """# Scoring Policy for Supplier Risk Assessment

## Composite Risk Score Calculation

Each single-source component receives a composite risk score from 0 to 100
(higher means greater risk). The score is the weighted sum of four normalized
risk factors.

### Factor Normalization

Each factor is mapped to a 0-100 scale where 100 represents the highest risk:

1. Financial Risk = 100 minus the supplier financial health score.
2. Geopolitical Risk = the country risk index (already 0-100).
3. Inventory Risk = max(0, min(100, (1 minus coverage_days divided by buffer_threshold_days) times 100)),
   where coverage_days equals quantity_on_hand divided by daily_usage_rate,
   and buffer_threshold_days is specified in risk_config.yaml.
4. Quality Risk = 100 minus the supplier quality audit score.

### Weighted Sum

composite_risk_score = (financial_weight * financial_risk)
                     + (geopolitical_weight * geopolitical_risk)
                     + (inventory_weight * inventory_risk)
                     + (quality_weight * quality_risk)

Weights are defined in risk_config.yaml under risk_weights.

### Risk Tier Assignment

Using the thresholds from risk_config.yaml (risk_tiers section):
- composite_risk_score >= Critical threshold -> "Critical"
- composite_risk_score >= High threshold -> "High"
- composite_risk_score >= Medium threshold -> "Medium"
- below Medium threshold -> "Low"

### Recommended Action

Based on risk tier and alternate supplier status (from component alternates files):
- Critical with qualification_status "none_identified": "Immediate: identify and qualify new alternate suppliers"
- Critical with qualification_status "under_evaluation": "Immediate: fast-track alternate supplier qualification"
- Critical with qualification_status "qualified": "Immediate: activate qualified alternate supply"
- High with qualification_status "none_identified": "Within 30 days: source potential alternate suppliers"
- High with qualification_status "under_evaluation": "Within 30 days: accelerate qualification process"
- High with qualification_status "qualified": "Within 30 days: onboard qualified alternate supplier"
- Medium (any status): "Quarterly review: monitor risk indicators"
- Low (any status): "Annual review: standard monitoring"

### Sorting

The final mitigation list is sorted by composite_risk_score in descending order.
Ties are broken by component_id in ascending lexicographic order.
"""
    with open(os.path.join(workspace, "scoring_policy.md"), "w") as f:
        f.write(policy)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    rng = np.random.RandomState(SEED)

    # Database
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)

    create_tables(conn)
    populate_country_risks(conn)
    suppliers_df = populate_suppliers(conn, rng)
    components_df = populate_components(conn, rng)
    po_df, component_supplier_map = populate_purchase_orders(conn, suppliers_df, components_df, rng)
    inventory_df = populate_inventory(conn, components_df, rng)
    conn.close()

    # Workspace files (scalable)
    n_files = SCALE["num_workspace_files"]
    n_fin, n_alt, n_aud, n_lt = _file_distribution(n_files)

    generate_financial_files(args.workspace, suppliers_df, rng, n_fin)
    generate_alternate_files(args.workspace, components_df, component_supplier_map, rng, n_alt)
    generate_audit_files(args.workspace, suppliers_df, rng, n_aud)
    generate_leadtime_files(args.workspace, components_df, rng, n_lt)

    # Fixed config files
    generate_fixed_config_files(args.workspace)

    print(f"Database created at {args.db_path}")
    print(f"Workspace populated at {args.workspace}")
    print(f"  - {n_fin} financial files, {n_alt} alternate files, {n_aud} audit files, {n_lt} lead-time files")
    print(f"  - Plus 2 fixed config files (risk_config.yaml, scoring_policy.md)")


if __name__ == "__main__":
    main()
