import os
import sys
import json
import csv
import sqlite3
import argparse
import random
import math
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 40,
    "num_workspace_files": 8,
}

# ── Seed everything ──────────────────────────────────────────────────────
random.seed(42)
np.random.seed(42)
Faker.seed(42)
fake = Faker()


# ═════════════════════════════════════════════════════════════════════════
#  DATA GENERATION HELPERS
# ═════════════════════════════════════════════════════════════════════════

COMPONENT_PREFIXES = {
    "Sub-Assembly": [
        "Drive Module", "Control Board", "Sensor Array", "Actuator Pack",
        "Power Unit", "Interface Panel", "Valve Assembly", "Gear Train",
        "Filter Block", "Pump Head", "Motor Assembly", "Relay Bank",
        "Switch Panel", "Coupling Unit", "Bearing Housing", "Bracket Assembly",
        "Wiring Harness", "Cooling Fan Unit", "Display Panel", "Signal Converter",
    ],
    "Electronic": [
        "Capacitor", "Resistor Pack", "IC Chip", "Transistor Set",
        "Diode Array", "LED Module", "Connector Pin", "PCB Board",
        "Crystal Oscillator", "Voltage Regulator", "Fuse Link", "Relay Coil",
        "Transformer Core", "Inductor", "Thermistor", "Varistor",
        "Optocoupler", "MOSFET Module", "DAC Unit", "ADC Chip",
    ],
    "Mechanical": [
        "Steel Shaft", "Aluminum Plate", "Copper Bushing", "Titanium Rod",
        "Spring Set", "Gasket Ring", "O-Ring Pack", "Bolt Kit",
        "Washer Set", "Pin Assembly", "Cam Roller", "Piston Ring",
        "Flange Disc", "Spacer Block", "Retainer Clip", "Dowel Pin",
        "Bearing Ball", "Chain Link", "Sprocket Gear", "Hinge Bracket",
    ],
    "Chemical": [
        "Epoxy Resin", "Lubricant Oil", "Thermal Paste", "Solder Wire",
        "Flux Solution", "Adhesive Film", "Coolant Fluid", "Cleaning Agent",
        "Coating Powder", "Sealant Tube", "Primer Solution", "Etching Acid",
        "Plating Salt", "Catalyst Bead", "Desiccant Pack", "Electrolyte Gel",
        "Hardener Mix", "Solvent Blend", "Wax Emulsion", "Pigment Paste",
    ],
    "Raw Material": [
        "Copper Wire", "Steel Sheet", "Rubber Strip", "Glass Fiber",
        "Carbon Rod", "Nylon Thread", "Silicone Sheet", "Ceramic Disc",
        "Foam Pad", "Mica Sheet", "Graphite Block", "Polymer Pellet",
        "Iron Powder", "Zinc Ingot", "Tin Foil", "Lead-free Solder Bar",
        "Brass Tube", "Acrylic Panel", "Kevlar Cord", "Tungsten Tip",
    ],
}

PRODUCT_NAMES = [
    "Industrial Controller Unit", "Hydraulic Pump Assembly",
    "Precision Servo Motor", "Automated Valve Station",
    "Thermal Management System", "Signal Processing Module",
    "Robotic Arm Joint", "Power Distribution Panel",
    "Environmental Sensor Hub", "Fluid Metering Device",
    "Laser Alignment Tool", "CNC Spindle Head",
    "Pneumatic Actuator Bank", "Vibration Dampener Unit",
    "Optical Inspection Camera", "Weld Controller Box",
    "Conveyor Drive Mechanism", "Pressure Regulator Assembly",
    "Electric Motor Starter", "Battery Management System",
    "Frequency Inverter Module", "Emergency Shutoff Valve",
    "Temperature Control Unit", "Load Cell Amplifier",
]

PRODUCT_CATEGORIES = [
    "Electronics", "Automotive", "Industrial",
    "Consumer", "Medical", "Aerospace",
]

UNITS = ["pcs", "kg", "m", "L", "sheets", "rolls", "sets"]
COUNTRIES = [
    "USA", "China", "Germany", "Japan", "South Korea",
    "Taiwan", "Mexico", "India", "Vietnam", "Brazil",
]
RATINGS = ["A", "A", "B", "B", "B", "C", "C", "D"]
RESERVATION_REASONS = [
    "Maintenance backlog commitment",
    "Quality assurance hold",
    "Export order pre-allocation",
    "R&D prototype reservation",
    "Warranty replacement stock",
    "Customer-specific safety stock",
    "Rework buffer allocation",
    "Engineering change hold",
    "Pending inspection release",
    "Long-term contract reserve",
]


# ═════════════════════════════════════════════════════════════════════════
#  TABLE GENERATORS
# ═════════════════════════════════════════════════════════════════════════

def _pick_name(category, idx):
    """Deterministic component name from category prefix list."""
    pool = COMPONENT_PREFIXES.get(category, COMPONENT_PREFIXES["Raw Material"])
    base = pool[idx % len(pool)]
    suffix = f" {fake.lexify('??').upper()}-{100 + idx}"
    return base + suffix


def generate_products(rows_per_table):
    num_products = min(len(PRODUCT_NAMES), max(8, rows_per_table // 5))
    products = []
    for i in range(num_products):
        products.append({
            "product_code": f"PROD-{i + 1:03d}",
            "product_name": PRODUCT_NAMES[i % len(PRODUCT_NAMES)],
            "category": PRODUCT_CATEGORIES[i % len(PRODUCT_CATEGORIES)],
        })
    return products


def generate_components(rows_per_table):
    num_sub = max(6, rows_per_table // 5)
    num_raw = rows_per_table - num_sub

    raw_categories = ["Electronic", "Mechanical", "Chemical", "Raw Material"]
    components = []

    for i in range(num_sub):
        components.append({
            "component_id": f"CMP-{i + 1:04d}",
            "name": _pick_name("Sub-Assembly", i),
            "category": "Sub-Assembly",
            "unit": "pcs",
            "unit_cost": round(random.uniform(50, 500), 2),
            "is_critical": 1 if random.random() < 0.25 else 0,
        })

    for i in range(num_raw):
        idx = num_sub + i
        cat = raw_categories[i % len(raw_categories)]
        components.append({
            "component_id": f"CMP-{idx + 1:04d}",
            "name": _pick_name(cat, i),
            "category": cat,
            "unit": random.choice(UNITS),
            "unit_cost": round(random.uniform(1, 100), 2),
            "is_critical": 1 if random.random() < 0.30 else 0,
        })
    return components


def generate_production_orders(rows_per_table, products):
    statuses = ["Active"] * 3 + ["Completed", "On Hold"]
    priorities = ["High", "Medium", "Medium", "Low"]
    orders = []
    for i in range(rows_per_table):
        prod = products[i % len(products)]
        orders.append({
            "order_id": f"PO-{i + 1:04d}",
            "product_code": prod["product_code"],
            "product_name": prod["product_name"],
            "quantity": random.randint(50, 500),
            "due_date": fake.date_between(start_date="+5d", end_date="+90d").isoformat(),
            "status": random.choice(statuses),
            "priority": random.choice(priorities),
        })
    return orders


def generate_bom(products, components, rows_per_table):
    sub_ids = [c["component_id"] for c in components if c["category"] == "Sub-Assembly"]
    raw_ids = [c["component_id"] for c in components if c["category"] != "Sub-Assembly"]

    entries = []
    bom_id = 1

    # ── product -> direct children (sub-assemblies + some raw materials) ──
    for prod in products:
        n_subs = random.randint(2, min(4, len(sub_ids)))
        chosen_subs = random.sample(sub_ids, n_subs)
        for sid in chosen_subs:
            entries.append({
                "bom_id": bom_id,
                "product_code": prod["product_code"],
                "parent_component_id": None,
                "child_component_id": sid,
                "quantity_per_unit": round(random.uniform(1, 4), 1),
            })
            bom_id += 1

        n_direct_raw = random.randint(1, min(3, len(raw_ids)))
        chosen_raw = random.sample(raw_ids, n_direct_raw)
        for rid in chosen_raw:
            entries.append({
                "bom_id": bom_id,
                "product_code": prod["product_code"],
                "parent_component_id": None,
                "child_component_id": rid,
                "quantity_per_unit": round(random.uniform(1, 8), 1),
            })
            bom_id += 1

    # ── sub-assembly -> raw materials (product-independent, product_code=NULL) ──
    for sid in sub_ids:
        n_children = random.randint(2, min(4, len(raw_ids)))
        chosen = random.sample(raw_ids, n_children)
        for rid in chosen:
            entries.append({
                "bom_id": bom_id,
                "product_code": None,
                "parent_component_id": sid,
                "child_component_id": rid,
                "quantity_per_unit": round(random.uniform(0.5, 6), 1),
            })
            bom_id += 1

    # pad to reach rows_per_table if short
    while len(entries) < rows_per_table:
        prod = random.choice(products)
        rid = random.choice(raw_ids)
        sid = random.choice(sub_ids)
        entries.append({
            "bom_id": bom_id,
            "product_code": None,
            "parent_component_id": sid,
            "child_component_id": rid,
            "quantity_per_unit": round(random.uniform(0.5, 4), 1),
        })
        bom_id += 1

    return entries


def generate_inventory(components, num_warehouses, rows_per_table):
    warehouses = [f"WH-{i + 1:02d}" for i in range(num_warehouses)]
    records = []
    inv_id = 1

    for comp in components:
        n_wh = random.randint(1, min(3, num_warehouses))
        chosen = random.sample(warehouses, n_wh)
        for wh in chosen:
            # bias: ~40 % of components get low stock
            if random.random() < 0.4:
                qty = round(random.uniform(0, 200), 1)
            else:
                qty = round(random.uniform(100, 2000), 1)
            records.append({
                "inventory_id": inv_id,
                "component_id": comp["component_id"],
                "warehouse_id": wh,
                "quantity_on_hand": qty,
                "last_updated": fake.date_between(
                    start_date="-30d", end_date="today"
                ).isoformat(),
            })
            inv_id += 1

    while len(records) < rows_per_table:
        comp = random.choice(components)
        wh = random.choice(warehouses)
        records.append({
            "inventory_id": inv_id,
            "component_id": comp["component_id"],
            "warehouse_id": wh,
            "quantity_on_hand": round(random.uniform(0, 300), 1),
            "last_updated": fake.date_between(
                start_date="-30d", end_date="today"
            ).isoformat(),
        })
        inv_id += 1

    return records, warehouses


def generate_suppliers(rows_per_table):
    suppliers = []
    for i in range(rows_per_table):
        suppliers.append({
            "supplier_id": f"SUP-{i + 1:04d}",
            "name": fake.company(),
            "country": random.choice(COUNTRIES),
            "base_lead_time_days": random.randint(3, 45),
            "reliability_rating": random.choice(RATINGS),
        })
    return suppliers


def generate_component_suppliers(components, suppliers, rows_per_table):
    records = []
    cs_id = 1
    used_pairs = set()

    for comp in components:
        n_sup = random.randint(1, min(3, len(suppliers)))
        chosen = random.sample(suppliers, n_sup)
        for j, sup in enumerate(chosen):
            pair = (comp["component_id"], sup["supplier_id"])
            if pair in used_pairs:
                continue
            used_pairs.add(pair)
            records.append({
                "id": cs_id,
                "component_id": comp["component_id"],
                "supplier_id": sup["supplier_id"],
                "supply_lead_time_days": max(1, sup["base_lead_time_days"] + random.randint(-5, 10)),
                "min_order_quantity": random.randint(10, 200),
                "unit_price": round(comp["unit_cost"] * random.uniform(0.8, 1.4), 2),
                "is_preferred": 1 if j == 0 else 0,
            })
            cs_id += 1

    while len(records) < rows_per_table:
        comp = random.choice(components)
        sup = random.choice(suppliers)
        pair = (comp["component_id"], sup["supplier_id"])
        if pair in used_pairs:
            continue
        used_pairs.add(pair)
        records.append({
            "id": cs_id,
            "component_id": comp["component_id"],
            "supplier_id": sup["supplier_id"],
            "supply_lead_time_days": max(1, sup["base_lead_time_days"] + random.randint(-5, 10)),
            "min_order_quantity": random.randint(10, 200),
            "unit_price": round(random.uniform(5, 200), 2),
            "is_preferred": 0,
        })
        cs_id += 1

    return records


# ═════════════════════════════════════════════════════════════════════════
#  DATABASE WRITER
# ═════════════════════════════════════════════════════════════════════════

def write_database(db_path, components, orders, bom, inventory, suppliers, comp_suppliers):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE components (
        component_id TEXT PRIMARY KEY,
        name TEXT,
        category TEXT,
        unit TEXT,
        unit_cost REAL,
        is_critical INTEGER
    )""")
    c.executemany(
        "INSERT INTO components VALUES (?,?,?,?,?,?)",
        [(r["component_id"], r["name"], r["category"], r["unit"],
          r["unit_cost"], r["is_critical"]) for r in components],
    )

    c.execute("""CREATE TABLE production_orders (
        order_id TEXT PRIMARY KEY,
        product_code TEXT,
        product_name TEXT,
        quantity INTEGER,
        due_date TEXT,
        status TEXT,
        priority TEXT
    )""")
    c.executemany(
        "INSERT INTO production_orders VALUES (?,?,?,?,?,?,?)",
        [(r["order_id"], r["product_code"], r["product_name"], r["quantity"],
          r["due_date"], r["status"], r["priority"]) for r in orders],
    )

    c.execute("""CREATE TABLE bill_of_materials (
        bom_id INTEGER PRIMARY KEY,
        product_code TEXT,
        parent_component_id TEXT,
        child_component_id TEXT,
        quantity_per_unit REAL
    )""")
    c.executemany(
        "INSERT INTO bill_of_materials VALUES (?,?,?,?,?)",
        [(r["bom_id"], r["product_code"], r["parent_component_id"],
          r["child_component_id"], r["quantity_per_unit"]) for r in bom],
    )

    c.execute("""CREATE TABLE inventory (
        inventory_id INTEGER PRIMARY KEY,
        component_id TEXT,
        warehouse_id TEXT,
        quantity_on_hand REAL,
        last_updated TEXT
    )""")
    c.executemany(
        "INSERT INTO inventory VALUES (?,?,?,?,?)",
        [(r["inventory_id"], r["component_id"], r["warehouse_id"],
          r["quantity_on_hand"], r["last_updated"]) for r in inventory],
    )

    c.execute("""CREATE TABLE suppliers (
        supplier_id TEXT PRIMARY KEY,
        name TEXT,
        country TEXT,
        base_lead_time_days INTEGER,
        reliability_rating TEXT
    )""")
    c.executemany(
        "INSERT INTO suppliers VALUES (?,?,?,?,?)",
        [(r["supplier_id"], r["name"], r["country"],
          r["base_lead_time_days"], r["reliability_rating"]) for r in suppliers],
    )

    c.execute("""CREATE TABLE component_suppliers (
        id INTEGER PRIMARY KEY,
        component_id TEXT,
        supplier_id TEXT,
        supply_lead_time_days INTEGER,
        min_order_quantity INTEGER,
        unit_price REAL,
        is_preferred INTEGER
    )""")
    c.executemany(
        "INSERT INTO component_suppliers VALUES (?,?,?,?,?,?,?)",
        [(r["id"], r["component_id"], r["supplier_id"],
          r["supply_lead_time_days"], r["min_order_quantity"],
          r["unit_price"], r["is_preferred"]) for r in comp_suppliers],
    )

    conn.commit()
    conn.close()


# ═════════════════════════════════════════════════════════════════════════
#  WORKSPACE FILE GENERATORS
# ═════════════════════════════════════════════════════════════════════════

def generate_stockout_policy(workspace):
    lines = [
        "# Stockout Risk Assessment Policy",
        "# All scoring parameters for procurement alert prioritization",
        "",
        "priority_weights:",
        "  shortage_ratio: 0.35",
        "  criticality: 0.25",
        "  lead_time_pressure: 0.20",
        "  order_urgency: 0.20",
        "",
        "priority_tiers:",
        "  Critical: 75",
        "  High: 55",
        "  Medium: 35",
        "",
        "max_lead_time_benchmark_days: 60",
        "",
        "criticality_tier_bonus: 10",
        "",
    ]
    path = os.path.join(workspace, "stockout_policy.yaml")
    with open(path, "w") as f:
        f.write("\n".join(lines))


def generate_procurement_rules(workspace):
    text = """\
PROCUREMENT ALERT RULES AND GUIDELINES

Component Eligibility:
Only components with a positive shortage quantity (total adjusted demand exceeding
available inventory) are included in the procurement alert list. Components whose
available inventory meets or exceeds total demand are not at risk and must be excluded.

Available Inventory Calculation:
Available inventory for a component equals the sum of on-hand quantities across all
warehouses, minus any reserved quantities documented in the warehouse status reports.
If the resulting value is negative, treat it as zero.

Demand Calculation:
For every active production order, trace the product through its bill of materials.
A product decomposes into direct children (sub-assemblies and raw materials). Each
sub-assembly further decomposes into its own child components. The demand contribution
of a leaf component through a sub-assembly path is:
  order_quantity * sub_assembly_qty_per_product * leaf_qty_per_sub_assembly
The demand contribution of a leaf component that is a direct child of the product is:
  order_quantity * leaf_qty_per_product
Sum contributions from all active orders and all BOM paths, then multiply by the
product-level demand adjustment factor from the demand forecast files.

Supplier Selection:
For each at-risk component, identify the preferred supplier (the one marked as
preferred in the system). If no preferred supplier exists for a component, select the
supplier offering the shortest effective lead time for that component.

Effective Lead Time:
The effective lead time for a supplier equals the supply lead time recorded in the
system plus any additional lead time adjustment days noted in the supplier performance
reports. If a supplier does not appear in any performance report, assume zero
adjustment days.

Priority Score Calculation:
The priority score for each component is computed as a weighted sum of four factors,
each scaled to the 0-100 range before weighting:

  shortage_pct = min(100.0, (shortage_quantity / total_demand) * 100.0)
  criticality_pct = 100.0 if the component is marked critical, otherwise 0.0
  lead_time_pct = min(100.0, (effective_lead_time_days / max_lead_time_benchmark_days) * 100.0)
  urgency_pct = maximum order priority score among all active orders that use this
                component (directly or through sub-assemblies), where
                High = 100.0, Medium = 60.0, Low = 30.0

  priority_score = shortage_ratio_weight * shortage_pct
                 + criticality_weight * criticality_pct
                 + lead_time_pressure_weight * lead_time_pct
                 + order_urgency_weight * urgency_pct

  Round the final priority_score to exactly two decimal places.

The weights and max_lead_time_benchmark_days values are defined in the stockout
policy configuration file.

Tier Assignment:
After computing the raw priority score, derive a tier-assignment score by adding the
criticality_tier_bonus (from the policy file) if and only if the component is marked
critical. Use this adjusted score solely for tier lookup:
  - Critical tier if adjusted score >= Critical threshold
  - High tier if adjusted score >= High threshold
  - Medium tier if adjusted score >= Medium threshold
  - Low tier otherwise
Tier thresholds are defined in the stockout policy configuration file.

Sorting:
The final alert list must be sorted by the raw priority_score (not the tier-adjusted
score) in descending order. When two components have the same priority_score (after
rounding to two decimal places), sort them by component_id in ascending alphabetical
order.
"""
    path = os.path.join(workspace, "procurement_rules.txt")
    with open(path, "w") as f:
        f.write(text)


def generate_demand_forecasts(workspace, products, n_files):
    """CSV files with demand_adjustment_factor per product."""
    file_buckets = [[] for _ in range(n_files)]
    for i, prod in enumerate(products):
        file_buckets[i % n_files].append(prod)

    for fi in range(n_files):
        rows = []
        for prod in file_buckets[fi]:
            adj = round(random.uniform(0.7, 1.5), 2)
            rows.append({
                "product_code": prod["product_code"],
                "product_name": prod["product_name"],
                "daily_demand_rate": round(random.uniform(5, 50), 1),
                "demand_adjustment_factor": adj,
            })
        path = os.path.join(workspace, f"demand_forecast_group_{fi + 1}.csv")
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "product_code", "product_name",
                "daily_demand_rate", "demand_adjustment_factor",
            ])
            w.writeheader()
            w.writerows(rows)


def generate_supplier_reports(workspace, comp_suppliers, suppliers_lookup, n_files):
    """JSON files with lead_time_adjustment_days per supplier."""
    referenced_sup_ids = sorted(set(cs["supplier_id"] for cs in comp_suppliers))

    file_buckets = [[] for _ in range(n_files)]
    for i, sid in enumerate(referenced_sup_ids):
        file_buckets[i % n_files].append(sid)

    for fi in range(n_files):
        assessments = []
        for sid in file_buckets[fi]:
            sup = suppliers_lookup[sid]
            adj_days = random.randint(0, 10)
            assessments.append({
                "supplier_id": sid,
                "supplier_name": sup["name"],
                "quality_score": random.randint(50, 99),
                "on_time_delivery_pct": round(random.uniform(70, 99.5), 1),
                "lead_time_adjustment_days": adj_days,
            })
        report = {
            "report_date": fake.date_between(
                start_date="-15d", end_date="today"
            ).isoformat(),
            "batch": fi + 1,
            "assessments": assessments,
        }
        path = os.path.join(workspace, f"supplier_performance_batch_{fi + 1}.json")
        with open(path, "w") as f:
            json.dump(report, f, indent=2)


def generate_warehouse_reports(workspace, components, inventory_records, warehouses, n_files):
    """Markdown files with reserved inventory in semi-structured tables."""
    wh_buckets = [[] for _ in range(n_files)]
    for i, wh in enumerate(warehouses):
        wh_buckets[i % n_files].append(wh)

    # Build lookup: (component_id, warehouse_id) -> total quantity_on_hand
    inv_lookup = {}
    for rec in inventory_records:
        key = (rec["component_id"], rec["warehouse_id"])
        inv_lookup[key] = inv_lookup.get(key, 0) + rec["quantity_on_hand"]

    for fi in range(n_files):
        whs = wh_buckets[fi]
        lines = []
        for wh in whs:
            lines.append(f"# Warehouse {wh} Status Report")
            lines.append("")
            lines.append(f"**Facility code:** {wh}")
            lines.append(
                f"**Report generated:** "
                f"{fake.date_between(start_date='-7d', end_date='today').isoformat()}"
            )
            lines.append("")
            lines.append(
                f"This report covers the current reservation status of "
                f"warehouse {wh}. Items listed below have quantities set aside "
                f"for prior commitments and cannot be allocated to new "
                f"production orders."
            )
            lines.append("")
            lines.append("## Reserved Inventory")
            lines.append("")
            lines.append("| Component ID | Reserved Qty | Reservation Reason |")
            lines.append("|---|---|---|")

            wh_comps = [
                cid for (cid, w) in inv_lookup.keys()
                if w == wh and inv_lookup[(cid, w)] > 0
            ]
            n_reserved = max(1, int(len(wh_comps) * 0.30))
            reserved_comps = random.sample(
                wh_comps, min(n_reserved, len(wh_comps))
            )
            for cid in sorted(reserved_comps):
                on_hand = inv_lookup.get((cid, wh), 0)
                frac = random.uniform(0.05, 0.40)
                reserved = round(on_hand * frac, 1)
                reason = random.choice(RESERVATION_REASONS)
                lines.append(f"| {cid} | {reserved} | {reason} |")

            lines.append("")
            cap_pct = random.randint(55, 95)
            lines.append("## Capacity Notes")
            lines.append("")
            lines.append(
                f"Warehouse {wh} is currently operating at approximately "
                f"{cap_pct}% capacity. "
                f"{fake.sentence()} {fake.sentence()}"
            )
            lines.append("")

        path = os.path.join(workspace, f"warehouse_status_{fi + 1}.md")
        with open(path, "w") as f:
            f.write("\n".join(lines))


# ═════════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════════

def main(db_path, workspace):
    os.makedirs(workspace, exist_ok=True)

    rows = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    # ── Derived counts ──
    n_csv = max(2, num_files // 4)
    n_json = max(2, num_files // 4)
    n_md = num_files - n_csv - n_json
    num_warehouses = max(3, n_md + 1)

    # ── Generate data ──
    products = generate_products(rows)
    components = generate_components(rows)
    orders = generate_production_orders(rows, products)
    bom = generate_bom(products, components, rows)
    inventory_records, warehouses = generate_inventory(
        components, num_warehouses, rows
    )
    suppliers = generate_suppliers(rows)
    comp_suppliers = generate_component_suppliers(components, suppliers, rows)

    # ── Write DB ──
    if os.path.exists(db_path):
        os.remove(db_path)
    write_database(
        db_path, components, orders, bom,
        inventory_records, suppliers, comp_suppliers,
    )

    # ── Write workspace files ──
    # Fixed config files
    generate_stockout_policy(workspace)
    generate_procurement_rules(workspace)

    # Scaled data files
    suppliers_lookup = {s["supplier_id"]: s for s in suppliers}
    generate_demand_forecasts(workspace, products, n_csv)
    generate_supplier_reports(workspace, comp_suppliers, suppliers_lookup, n_json)
    generate_warehouse_reports(
        workspace, components, inventory_records, warehouses, n_md,
    )

    print(f"Database written to {db_path}")
    print(f"Workspace files written to {workspace}/")
    print(f"  Tables: components({len(components)}), orders({len(orders)}), "
          f"bom({len(bom)}), inventory({len(inventory_records)}), "
          f"suppliers({len(suppliers)}), comp_suppliers({len(comp_suppliers)})")
    print(f"  Workspace: {n_csv} CSV + {n_json} JSON + {n_md} MD "
          f"+ 2 fixed (yaml+txt) = {n_csv + n_json + n_md + 2} files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
