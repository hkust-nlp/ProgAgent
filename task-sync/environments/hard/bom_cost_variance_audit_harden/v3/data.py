import argparse
import json
import os
import random
import sqlite3

import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 160,
    "num_workspace_files": 32,
}

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

CATEGORIES = ["Electronics", "Furniture", "Automotive", "Appliances", "Industrial"]
PRODUCT_PREFIXES = ["Pro", "Ultra", "Max", "Elite", "Prime", "Core", "Eco", "Flex", "Nova", "Apex"]
PRODUCT_TYPES = ["Widget", "Bracket", "Module", "Panel", "Gear", "Valve", "Sensor", "Frame", "Housing", "Board"]

MATERIAL_BASES = [
    "Steel", "Aluminum", "Copper", "Plastic", "Rubber",
    "Glass", "Wood", "Titanium", "Zinc", "Nickel",
    "Carbon-Fiber", "Brass", "Silicon", "Ceramic", "Nylon",
]
MATERIAL_FORMS = ["Rod", "Sheet", "Wire", "Tube", "Plate", "Powder", "Pellet", "Bar", "Coil", "Block"]
MATERIAL_SPECS = ["1mm", "2mm", "5mm", "10mm", "15mm", "20mm", "25mm", "TypeA", "TypeB", "GradeI", "GradeII"]

OPERATIONS = ["Cutting", "Welding", "Assembly", "Painting", "Inspection",
              "Packaging", "Molding", "Polishing", "Testing", "Wiring"]
WASTE_TYPES = ["Scrap", "Rework", "Overrun", "Defective", "Spillage"]
UNITS = ["kg", "m", "pcs", "liters", "sheets"]

THRESHOLDS = {
    "total_variance_threshold": 10.0,
    "material_critical_threshold": 12.0,
    "total_critical_threshold": 15.0,
    "yield_loss_threshold": 0.92,
}


def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS finished_goods (
        product_id TEXT PRIMARY KEY,
        product_name TEXT,
        category TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS raw_materials (
        material_id TEXT PRIMARY KEY,
        material_name TEXT,
        unit TEXT,
        standard_price REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS bom_items (
        bom_id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id TEXT,
        material_id TEXT,
        standard_qty REAL,
        standard_unit_price REAL,
        FOREIGN KEY (product_id) REFERENCES finished_goods(product_id),
        FOREIGN KEY (material_id) REFERENCES raw_materials(material_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS approved_vendors (
        vendor_id TEXT PRIMARY KEY,
        vendor_name TEXT,
        material_id TEXT,
        is_preferred INTEGER,
        status TEXT,
        FOREIGN KEY (material_id) REFERENCES raw_materials(material_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS labor_routings (
        routing_id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id TEXT,
        operation_name TEXT,
        standard_hours REAL,
        standard_labor_rate REAL,
        FOREIGN KEY (product_id) REFERENCES finished_goods(product_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS production_yields (
        yield_id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id TEXT,
        batch_id TEXT,
        planned_qty INTEGER,
        actual_qty INTEGER,
        waste_type TEXT,
        waste_qty INTEGER,
        production_date TEXT,
        operator_notes TEXT,
        FOREIGN KEY (product_id) REFERENCES finished_goods(product_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS ground_truth (
        product_id TEXT PRIMARY KEY,
        product_name TEXT,
        standard_material_cost REAL,
        actual_material_cost REAL,
        material_variance REAL,
        material_variance_pct REAL,
        standard_labor_cost REAL,
        actual_labor_cost REAL,
        labor_variance REAL,
        labor_variance_pct REAL,
        yield_rate REAL,
        yield_adjusted_total REAL,
        total_standard_cost REAL,
        total_variance REAL,
        total_variance_pct REAL,
        flag TEXT,
        revision_recommended TEXT
    )""")
    conn.commit()


def generate_data(conn, scale):
    R = scale["rows_per_table"]
    c = conn.cursor()

    # ---- finished_goods (R rows) ----
    products = []
    for i in range(R):
        product_id = f"FG-{i+1:04d}"
        prefix = PRODUCT_PREFIXES[i % len(PRODUCT_PREFIXES)]
        ptype = PRODUCT_TYPES[i % len(PRODUCT_TYPES)]
        product_name = f"{prefix}-{ptype}-{i+1:03d}"
        category = CATEGORIES[i % len(CATEGORIES)]
        products.append((product_id, product_name, category))
    c.executemany("INSERT INTO finished_goods VALUES (?, ?, ?)", products)

    # ---- raw_materials (>= R rows) ----
    num_materials = max(R, 25)
    materials = []
    for i in range(num_materials):
        material_id = f"MAT-{i+1:04d}"
        base = MATERIAL_BASES[i % len(MATERIAL_BASES)]
        form = MATERIAL_FORMS[i % len(MATERIAL_FORMS)]
        spec = MATERIAL_SPECS[i % len(MATERIAL_SPECS)]
        material_name = f"{base}-{form}-{spec}"
        unit = UNITS[i % len(UNITS)]
        standard_price = round(random.uniform(2.0, 80.0), 2)
        materials.append((material_id, material_name, unit, standard_price))
    c.executemany("INSERT INTO raw_materials VALUES (?, ?, ?, ?)", materials)

    # ---- bom_items (>= R rows; each product gets 3-5 materials) ----
    bom_items = []
    product_bom = {}
    for product in products:
        product_id = product[0]
        num_mats = random.randint(3, min(6, num_materials))
        selected = random.sample(range(num_materials), num_mats)
        product_bom[product_id] = []
        for idx in selected:
            mat = materials[idx]
            material_id = mat[0]
            standard_qty = round(random.uniform(1.0, 25.0), 2)
            standard_unit_price = mat[3]
            bom_items.append((product_id, material_id, standard_qty, standard_unit_price))
            product_bom[product_id].append((material_id, standard_qty, standard_unit_price))
    c.executemany(
        "INSERT INTO bom_items (product_id, material_id, standard_qty, standard_unit_price) VALUES (?, ?, ?, ?)",
        bom_items,
    )

    # ---- approved_vendors (>= R rows; 2-4 vendors per material) ----
    vendors = []
    material_vendors = {}
    vendor_counter = 0
    for mat in materials:
        material_id = mat[0]
        num_v = random.randint(2, 4)
        preferred_idx = random.randint(0, num_v - 1)
        vendor_batch = []
        for j in range(num_v):
            vendor_counter += 1
            vendor_id = f"VND-{vendor_counter:04d}"
            vendor_name = fake.company()
            is_preferred = 1 if j == preferred_idx else 0
            status = "active" if random.random() < 0.85 else "inactive"
            vendor_batch.append((vendor_id, vendor_name, material_id, is_preferred, status))
        # Guarantee at least one active vendor
        if not any(v[4] == "active" for v in vendor_batch):
            lst = list(vendor_batch[-1])
            lst[4] = "active"
            vendor_batch[-1] = tuple(lst)
        material_vendors[material_id] = []
        for v in vendor_batch:
            vendors.append(v)
            material_vendors[material_id].append({
                "vendor_id": v[0],
                "vendor_name": v[1],
                "is_preferred": v[3],
                "status": v[4],
            })
    c.executemany("INSERT INTO approved_vendors VALUES (?, ?, ?, ?, ?)", vendors)

    # ---- labor_routings (>= R rows; 2-4 ops per product) ----
    routings_list = []
    product_routings = {}
    for product in products:
        product_id = product[0]
        num_ops = random.randint(2, min(4, len(OPERATIONS)))
        selected_ops = random.sample(OPERATIONS, num_ops)
        product_routings[product_id] = []
        for op in selected_ops:
            standard_hours = round(random.uniform(0.5, 10.0), 2)
            standard_rate = round(random.uniform(18.0, 85.0), 2)
            routings_list.append((product_id, op, standard_hours, standard_rate))
            product_routings[product_id].append((op, standard_hours, standard_rate))
    c.executemany(
        "INSERT INTO labor_routings (product_id, operation_name, standard_hours, standard_labor_rate) "
        "VALUES (?, ?, ?, ?)",
        routings_list,
    )

    # ---- production_yields (>= R rows; 2-5 batches per product) ----
    yields_data = []
    product_yields = {}
    for product in products:
        product_id = product[0]
        num_batches = random.randint(2, 5)
        product_yields[product_id] = []
        for b in range(num_batches):
            batch_id = f"B-{product_id}-{b+1:03d}"
            planned_qty = random.randint(50, 500)
            yrate = random.uniform(0.78, 0.99)
            actual_qty = max(1, int(planned_qty * yrate))
            waste_qty = planned_qty - actual_qty
            waste_type = random.choice(WASTE_TYPES)
            prod_date = str(fake.date_between(start_date="-90d", end_date="today"))
            note = fake.sentence()
            yields_data.append(
                (product_id, batch_id, planned_qty, actual_qty,
                 waste_type, waste_qty, prod_date, note)
            )
            product_yields[product_id].append((planned_qty, actual_qty))
    c.executemany(
        "INSERT INTO production_yields "
        "(product_id, batch_id, planned_qty, actual_qty, waste_type, waste_qty, production_date, operator_notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        yields_data,
    )

    conn.commit()
    return {
        "products": products,
        "materials": materials,
        "vendors": vendors,
        "material_vendors": material_vendors,
        "product_bom": product_bom,
        "product_routings": product_routings,
        "product_yields": product_yields,
    }


def generate_workspace(conn, workspace, scale, data):
    W = scale["num_workspace_files"]
    products = data["products"]
    materials = data["materials"]
    vendors = data["vendors"]
    material_vendors = data["material_vendors"]
    product_bom = data["product_bom"]
    product_routings = data["product_routings"]

    # Distribute scalable files across 4 formats
    n_csv = max(2, W // 4)
    n_json = max(2, W // 4)
    n_md = max(2, W // 4)
    n_txt = W - n_csv - n_json - n_md
    if n_txt < 1:
        n_txt = 1
        n_md = max(1, n_md - 1)

    # ---- vendor quoted prices ----
    vendor_quotes = {}
    for v in vendors:
        vendor_id, vendor_name, material_id, is_preferred, status = v
        mat = next(m for m in materials if m[0] == material_id)
        std_price = mat[3]
        factor = random.uniform(0.80, 1.30)
        quoted_price = round(std_price * factor, 2)
        eff_date = str(fake.date_between(start_date="-45d", end_date="-1d"))
        vendor_quotes[vendor_id] = {
            "vendor_id": vendor_id,
            "vendor_name": vendor_name,
            "material_id": material_id,
            "quoted_price": quoted_price,
            "effective_date": eff_date,
            "currency": "USD",
        }

    # ---- handling surcharges ----
    handling_costs = {}
    for mat in materials:
        handling_costs[mat[0]] = round(random.uniform(0.10, 5.00), 2)

    # ---- actual labor hours ----
    actual_hours = {}
    for product in products:
        product_id = product[0]
        for op, std_h, _ in product_routings[product_id]:
            factor = random.uniform(0.80, 1.35)
            actual_hours[(product_id, op)] = round(std_h * factor, 2)

    # ==== vendor_quotes JSON files ====
    vq_list = list(vendor_quotes.values())
    for i, chunk in enumerate(_split(vq_list, n_json)):
        fname = f"vendor_quotes_{i+1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump({
                "report_date": str(fake.date_between(start_date="-30d", end_date="today")),
                "quotes": chunk,
            }, f, indent=2)

    # ==== yield_report CSV files ====
    cur = conn.cursor()
    cur.execute(
        "SELECT product_id, batch_id, planned_qty, actual_qty, "
        "waste_type, waste_qty, production_date, operator_notes FROM production_yields"
    )
    yield_rows = cur.fetchall()
    for i, chunk in enumerate(_split(yield_rows, n_csv)):
        fname = f"yield_report_{i+1:03d}.csv"
        df = pd.DataFrame(chunk, columns=[
            "product_id", "batch_id", "planned_qty", "actual_qty",
            "waste_type", "waste_qty", "production_date", "operator_notes",
        ])
        df.to_csv(os.path.join(workspace, fname), index=False)

    # ==== production_summary MD files ====
    pid_list = [p[0] for p in products]
    for i, chunk_pids in enumerate(_split(pid_list, n_md)):
        fname = f"production_summary_{i+1:03d}.md"
        lines = [
            f"# Production Report - Period {i+1}",
            "",
            (f"Report generated on {fake.date_between(start_date='-10d', end_date='today')}. "
             f"This report covers actual labor performance for the products listed below. "
             f"Equipment utilization averaged {random.uniform(85, 96):.1f}% during this period."),
            "",
            "| Product ID | Operation | Scheduled Hours | Actual Hours | Efficiency % | Remarks |",
            "|------------|-----------|-----------------|--------------|--------------|---------|",
        ]
        for pid in chunk_pids:
            for op, std_h, _ in product_routings[pid]:
                ah = actual_hours[(pid, op)]
                eff = round(std_h / ah * 100, 1) if ah > 0 else 100.0
                remark = fake.sentence(nb_words=random.randint(3, 8))
                lines.append(f"| {pid} | {op} | {std_h:.2f} | {ah:.2f} | {eff} | {remark} |")
        lines += ["", f"Overall production notes: {fake.paragraph(nb_sentences=3)}", ""]
        with open(os.path.join(workspace, fname), "w") as f:
            f.write("\n".join(lines))

    # ==== material_specs TXT files ====
    mat_indices = list(range(len(materials)))
    for i, chunk_idx in enumerate(_split(mat_indices, max(1, n_txt))):
        fname = f"material_specs_{i+1:03d}.txt"
        lines = ["MATERIAL SPECIFICATION AND HANDLING NOTES", "=" * 45, ""]
        for idx in chunk_idx:
            mat = materials[idx]
            mid = mat[0]
            lines += [
                f"Material ID: {mid}",
                f"Material Name: {mat[1]}",
                f"Unit: {mat[2]}",
                f"Handling Surcharge: {handling_costs[mid]:.2f}",
                f"Storage Class: {random.choice(['A', 'B', 'C'])}",
                f"Notes: {fake.sentence()}",
                "", "---", "",
            ]
        with open(os.path.join(workspace, fname), "w") as f:
            f.write("\n".join(lines))

    # ==== Fixed config files ====
    with open(os.path.join(workspace, "cost_thresholds.yaml"), "w") as f:
        yaml.dump(THRESHOLDS, f, default_flow_style=False)

    revision_policy = (
        "COST REVISION POLICY\n"
        "====================\n\n"
        "A formal cost revision for a finished good is recommended when ANY of the\n"
        "following conditions is met:\n\n"
        "1. The absolute value of the total variance percentage exceeds the critical\n"
        "   total threshold.\n\n"
        "2. The absolute value of the material variance percentage exceeds the material\n"
        "   critical threshold AND at least one raw material in the product's bill of\n"
        "   materials was priced using a non-preferred vendor (i.e., the preferred\n"
        "   vendor for that material was inactive or unavailable, requiring fallback\n"
        "   to an alternative approved vendor).\n\n"
        "3. The product's actual yield rate (total actual good output divided by total\n"
        "   planned output across all recorded batches) falls below the minimum\n"
        "   acceptable yield threshold.\n\n"
        "All threshold values referenced above are defined in the cost thresholds\n"
        "configuration file.\n"
    )
    with open(os.path.join(workspace, "revision_policy.txt"), "w") as f:
        f.write(revision_policy)

    costing_methodology = (
        "# Standard Costing and Variance Methodology\n"
        "\n"
        "This document is the authoritative specification for the cost variance\n"
        "analysis. All computations must follow the definitions below exactly.\n"
        "\n"
        "## 1. Standard Costs\n"
        "\n"
        "A product's standard material cost is the sum, over every line of its bill\n"
        "of materials, of the line's standard quantity multiplied by the standard\n"
        "unit price recorded on that BOM line. A product's standard labor cost is\n"
        "the sum, over every operation in its labor routing, of the operation's\n"
        "standard hours multiplied by that operation's standard labor rate. The\n"
        "total standard cost is the sum of the standard material cost and the\n"
        "standard labor cost.\n"
        "\n"
        "## 2. Actual Material Unit Prices\n"
        "\n"
        "The actual unit price of a raw material is the applicable vendor quoted\n"
        "price plus the handling surcharge listed for that material in the material\n"
        "specification files. The applicable quoted price is determined as follows:\n"
        "identify the material's approved vendors whose status is active; among the\n"
        "active vendors, locate the one flagged as preferred and use that vendor's\n"
        "most recently quoted price from the vendor quote files. If the preferred\n"
        "vendor is inactive or no preferred vendor can be found among the active\n"
        "vendors, fall back to the lowest quoted price among all active approved\n"
        "vendors for that material, again adding the handling surcharge. Whenever\n"
        "this fallback is used for any material in a product's bill of materials,\n"
        "the product must be recorded as having sourced from a non-preferred\n"
        "vendor. A product's actual material cost is the sum, over every BOM line,\n"
        "of the line's standard quantity multiplied by the material's actual unit\n"
        "price.\n"
        "\n"
        "## 3. Actual Labor Cost\n"
        "\n"
        "A product's actual labor cost is the sum, over every operation in its\n"
        "routing, of the actual hours recorded for that operation in the production\n"
        "summary reports multiplied by the operation's standard labor rate. If no\n"
        "actual hours are recorded for an operation, its standard hours apply.\n"
        "\n"
        "## 4. Production Yield\n"
        "\n"
        "A product's yield rate is its total actual good output divided by its\n"
        "total planned output, summed across all recorded production batches in the\n"
        "yield report files. The yield-adjusted total actual cost is the sum of the\n"
        "actual material cost and the actual labor cost, divided by the yield rate.\n"
        "\n"
        "## 5. Variances\n"
        "\n"
        "- Material variance = actual material cost minus standard material cost.\n"
        "- Material variance percentage = material variance divided by standard\n"
        "  material cost, multiplied by one hundred.\n"
        "- Labor variance = actual labor cost minus standard labor cost.\n"
        "- Labor variance percentage = labor variance divided by standard labor\n"
        "  cost, multiplied by one hundred.\n"
        "- Total variance = yield-adjusted total actual cost minus total standard\n"
        "  cost.\n"
        "- Total variance percentage = total variance divided by total standard\n"
        "  cost, multiplied by one hundred.\n"
        "\n"
        "## 6. Flagging and Revision\n"
        "\n"
        "A product is flagged when the absolute value of its total variance\n"
        "percentage exceeds the total variance threshold defined in the cost\n"
        "thresholds configuration file. Formal cost-revision recommendations are\n"
        "governed by the cost revision policy document; every threshold it\n"
        "references is likewise defined in the cost thresholds configuration file.\n"
    )
    with open(os.path.join(workspace, "costing_methodology.md"), "w") as f:
        f.write(costing_methodology)

    # ==== Ground truth ====
    _compute_ground_truth(conn, workspace, data, handling_costs, vendor_quotes, actual_hours)


def _split(lst, n):
    """Split list into n roughly equal chunks."""
    k, m = divmod(len(lst), n)
    out, idx = [], 0
    for i in range(n):
        size = k + (1 if i < m else 0)
        out.append(lst[idx:idx + size])
        idx += size
    return out


def _compute_ground_truth(conn, workspace, data, handling_costs, vendor_quotes, actual_hours_map):
    products = data["products"]
    material_vendors = data["material_vendors"]
    product_bom = data["product_bom"]
    product_routings = data["product_routings"]
    product_yields = data["product_yields"]

    with open(os.path.join(workspace, "cost_thresholds.yaml")) as f:
        thresholds = yaml.safe_load(f)

    c = conn.cursor()
    rows = []

    for product in products:
        product_id, product_name = product[0], product[1]
        bom = product_bom[product_id]

        # -- standard material cost --
        std_mat = sum(qty * price for _, qty, price in bom)

        # -- actual material cost --
        act_mat = 0.0
        has_non_preferred = False
        for material_id, qty, _ in bom:
            mv = material_vendors[material_id]
            active = [v for v in mv if v["status"] == "active"]
            preferred = [v for v in active if v["is_preferred"] == 1]

            if preferred and preferred[0]["vendor_id"] in vendor_quotes:
                act_price = vendor_quotes[preferred[0]["vendor_id"]]["quoted_price"]
            else:
                has_non_preferred = True
                prices = [
                    vendor_quotes[v["vendor_id"]]["quoted_price"]
                    for v in active if v["vendor_id"] in vendor_quotes
                ]
                act_price = min(prices) if prices else 0.0

            handling = handling_costs.get(material_id, 0.0)
            act_mat += qty * (act_price + handling)

        mat_var = act_mat - std_mat
        mat_var_pct = (mat_var / std_mat * 100) if std_mat else 0.0

        # -- standard labor cost --
        routings = product_routings[product_id]
        std_lab = sum(h * r for _, h, r in routings)

        # -- actual labor cost --
        act_lab = sum(
            actual_hours_map.get((product_id, op), std_h) * rate
            for op, std_h, rate in routings
        )
        lab_var = act_lab - std_lab
        lab_var_pct = (lab_var / std_lab * 100) if std_lab else 0.0

        # -- yield --
        ylds = product_yields[product_id]
        total_planned = sum(p for p, _ in ylds)
        total_actual = sum(a for _, a in ylds)
        yield_rate = total_actual / total_planned if total_planned > 0 else 1.0

        yield_adj = (act_mat + act_lab) / yield_rate if yield_rate > 0 else (act_mat + act_lab)

        total_std = std_mat + std_lab
        total_var = yield_adj - total_std
        total_var_pct = (total_var / total_std * 100) if total_std else 0.0

        flag = "YES" if abs(total_var_pct) > thresholds["total_variance_threshold"] else "NO"

        revision = "NO"
        if abs(total_var_pct) > thresholds["total_critical_threshold"]:
            revision = "YES"
        elif abs(mat_var_pct) > thresholds["material_critical_threshold"] and has_non_preferred:
            revision = "YES"
        elif yield_rate < thresholds["yield_loss_threshold"]:
            revision = "YES"

        rows.append((
            product_id, product_name,
            round(std_mat, 2), round(act_mat, 2), round(mat_var, 2), round(mat_var_pct, 2),
            round(std_lab, 2), round(act_lab, 2), round(lab_var, 2), round(lab_var_pct, 2),
            round(yield_rate, 4), round(yield_adj, 2),
            round(total_std, 2), round(total_var, 2), round(total_var_pct, 2),
            flag, revision,
        ))

    c.executemany("INSERT INTO ground_truth VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)
    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    data = generate_data(conn, SCALE)
    generate_workspace(conn, args.workspace, SCALE, data)
    conn.close()


if __name__ == "__main__":
    main()
