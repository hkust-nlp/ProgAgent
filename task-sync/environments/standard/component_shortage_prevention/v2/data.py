"""Data generation for component stockout prevention task."""
import os
import json
import csv
import sqlite3
import argparse
import math
import numpy as np
import pandas as pd
import yaml
from faker import Faker
from datetime import date, timedelta

SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 24,
}

REFERENCE_DATE = date(2026, 4, 20)


def main(db_path, workspace):
    fake = Faker()
    Faker.seed(42)
    np.random.seed(42)
    rng = np.random.default_rng(42)

    os.makedirs(workspace, exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    n_comp = SCALE["rows_per_table"]
    n_supp = SCALE["rows_per_table"]
    n_lines = SCALE["rows_per_table"]
    n_ws = SCALE["num_workspace_files"]
    today = REFERENCE_DATE

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # ── Create tables ──
    c.executescript("""
    CREATE TABLE components (
        component_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        unit TEXT NOT NULL
    );
    CREATE TABLE suppliers (
        supplier_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        region TEXT NOT NULL,
        email TEXT NOT NULL
    );
    CREATE TABLE supplier_components (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier_id INTEGER NOT NULL,
        component_id INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        lead_time_days INTEGER NOT NULL,
        min_order_qty INTEGER NOT NULL,
        FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
        FOREIGN KEY (component_id) REFERENCES components(component_id)
    );
    CREATE TABLE inventory (
        component_id INTEGER PRIMARY KEY,
        quantity_on_hand INTEGER NOT NULL,
        reserved_quantity INTEGER NOT NULL,
        last_updated TEXT NOT NULL,
        FOREIGN KEY (component_id) REFERENCES components(component_id)
    );
    CREATE TABLE assembly_lines (
        line_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        product TEXT NOT NULL,
        status TEXT NOT NULL
    );
    CREATE TABLE production_schedules (
        schedule_id INTEGER PRIMARY KEY,
        line_id INTEGER NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        daily_target INTEGER NOT NULL,
        priority TEXT NOT NULL,
        status TEXT NOT NULL,
        FOREIGN KEY (line_id) REFERENCES assembly_lines(line_id)
    );
    CREATE TABLE line_components (
        line_id INTEGER NOT NULL,
        component_id INTEGER NOT NULL,
        units_per_product REAL NOT NULL,
        PRIMARY KEY (line_id, component_id),
        FOREIGN KEY (line_id) REFERENCES assembly_lines(line_id),
        FOREIGN KEY (component_id) REFERENCES components(component_id)
    );
    """)

    # ── Components ──
    cat_bases = {
        "electronic": [
            "Capacitor", "Resistor", "Transistor", "Diode", "IC_Chip",
            "LED", "Relay", "Fuse", "Connector", "Transformer", "Inductor", "Crystal",
        ],
        "mechanical": [
            "Bearing", "Gear", "Spring", "Shaft", "Bracket",
            "Bushing", "Coupling", "Gasket", "Seal", "Pin", "Valve", "Hinge",
        ],
        "raw_material": [
            "Steel_Sheet", "Copper_Wire", "Aluminum_Bar", "Rubber_Strip",
            "Plastic_Pellet", "Solder_Paste", "Adhesive", "Insulation_Tape",
        ],
        "chemical": [
            "Flux", "Cleaning_Agent", "Coolant", "Etch_Solution",
            "Plating_Sol", "Coating_Compound",
        ],
        "fastener": [
            "M3_Bolt", "M4_Screw", "M5_Nut", "Flat_Washer",
            "Rivet", "Clip", "Anchor_Bolt", "Stud_Pin",
        ],
    }
    cat_order = ["electronic", "mechanical", "raw_material", "chemical", "fastener"]
    unit_map = {
        "electronic": "pcs", "mechanical": "pcs", "fastener": "pcs",
        "chemical": "L", "raw_material": "kg",
    }

    templates = []
    for cat in cat_order:
        for base in cat_bases[cat]:
            templates.append((base, cat, unit_map[cat]))

    components = []
    for i in range(n_comp):
        base, cat, unit = templates[i % len(templates)]
        ver = i // len(templates) + 1
        components.append((i + 1, f"{base}_{ver:02d}", cat, unit))
    c.executemany("INSERT INTO components VALUES (?,?,?,?)", components)

    # ── Suppliers ──
    regions = ["domestic", "asia", "europe", "americas"]
    suppliers = []
    for sid in range(1, n_supp + 1):
        suppliers.append((sid, fake.company(), regions[(sid - 1) % len(regions)],
                          fake.company_email()))
    c.executemany("INSERT INTO suppliers VALUES (?,?,?,?)", suppliers)

    # ── Supplier-Components ──
    sc_rows = []
    for comp_id, _, _, _ in components:
        n_for = int(rng.choice([1, 2, 2, 3]))
        chosen = sorted(rng.choice(n_supp, size=min(n_for, n_supp), replace=False) + 1)
        for sid in chosen:
            price = round(float(rng.uniform(0.5, 50.0)), 2)
            lead = int(rng.choice([3, 5, 7, 10, 14, 21, 28]))
            moq = int(rng.choice([10, 25, 50, 100, 200, 500]))
            sc_rows.append((int(sid), comp_id, price, lead, moq))
    c.executemany(
        "INSERT INTO supplier_components "
        "(supplier_id,component_id,unit_price,lead_time_days,min_order_qty) "
        "VALUES (?,?,?,?,?)",
        sc_rows,
    )

    # ── Assembly Lines ──
    products = [
        "Widget_Alpha", "Sensor_Module", "Control_Board", "Power_Supply",
        "Motor_Assembly", "Display_Panel", "Comm_Hub", "Battery_Pack",
        "Actuator_Unit", "Nav_Module", "Thermal_Ctrl", "Signal_Proc",
        "Hydraulic_Valve", "Optical_Scanner", "Robot_Joint", "Data_Logger",
    ]
    status_pat = ["active", "active", "active", "maintenance", "idle"]
    lines = []
    for lid in range(1, n_lines + 1):
        lines.append((lid, f"Line-{lid:02d}",
                       products[(lid - 1) % len(products)],
                       status_pat[(lid - 1) % len(status_pat)]))
    c.executemany("INSERT INTO assembly_lines VALUES (?,?,?,?)", lines)

    # ── Production Schedules ──
    prio_choices = ["high", "medium", "low"]
    sched_rows = []
    sched_id = 1
    for lid, _, _, status in lines:
        if status == "active":
            start_off = int(rng.integers(-35, -5))
            duration = int(rng.integers(20, 50))
            start = today + timedelta(days=start_off)
            end = start + timedelta(days=duration)
            dt = int(rng.integers(50, 300))
            pri = prio_choices[int(rng.integers(0, 3))]
            sched_rows.append((sched_id, lid, str(start), str(end),
                               dt, pri, "active"))
        else:
            start = today - timedelta(days=int(rng.integers(30, 60)))
            end = today - timedelta(days=int(rng.integers(1, 10)))
            dt = int(rng.integers(50, 200))
            sched_rows.append((sched_id, lid, str(start), str(end),
                               dt, "low", "completed"))
        sched_id += 1
    c.executemany("INSERT INTO production_schedules VALUES (?,?,?,?,?,?,?)",
                  sched_rows)

    # ── Line-Components (BOM) ──
    lc_rows = []
    for lid, _, _, _ in lines:
        n_bom = int(rng.integers(8, min(16, n_comp // 2 + 1)))
        chosen = sorted(rng.choice(n_comp, size=n_bom, replace=False) + 1)
        for cid in chosen:
            upr = round(float(rng.uniform(0.5, 5.0)), 2)
            lc_rows.append((int(lid), int(cid), upr))
    c.executemany("INSERT INTO line_components VALUES (?,?,?)", lc_rows)

    # ── Compute demand for inventory calibration ──
    active_scheds = [s for s in sched_rows if s[6] == "active"]
    lc_map = {}
    for lid, cid, upr in lc_rows:
        lc_map.setdefault(lid, []).append((cid, upr))

    demand = {}
    for _, lid, sdate, edate, dt, pri, st in active_scheds:
        remaining = max(0, (date.fromisoformat(edate) - today).days)
        for cid, upr in lc_map.get(lid, []):
            demand[cid] = demand.get(cid, 0) + remaining * dt * upr

    # ── Inventory (calibrated: ~50% under-stocked) ──
    inv_rows = []
    for comp_id, _, cat, _ in components:
        d = demand.get(comp_id, 0)
        if d > 0:
            if rng.random() < 0.5:
                qty = max(1, int(d * float(rng.uniform(0.05, 0.5))))
            else:
                qty = int(d * float(rng.uniform(1.5, 4.0)))
        else:
            qty = int(rng.integers(500, 5000))
        reserved = int(qty * float(rng.uniform(0, 0.2)))
        last_upd = str(today - timedelta(days=int(rng.integers(0, 3))))
        inv_rows.append((comp_id, qty, reserved, last_upd))
    c.executemany("INSERT INTO inventory VALUES (?,?,?,?)", inv_rows)

    conn.commit()

    # ════════════════════════════════════════════
    #  WORKSPACE FILES
    # ════════════════════════════════════════════
    cur = conn.cursor()

    active_sched_db = cur.execute(
        "SELECT schedule_id, line_id, daily_target, start_date, end_date "
        "FROM production_schedules WHERE status='active'"
    ).fetchall()
    lc_db = cur.execute(
        "SELECT line_id, component_id, units_per_product FROM line_components"
    ).fetchall()
    lc_map_db = {}
    for lid, cid, upr in lc_db:
        lc_map_db.setdefault(lid, []).append((cid, upr))

    # Waste factors per component (persistent across logs)
    waste_factors = {}
    for comp_id, _, _, _ in components:
        if rng.random() < 0.25:
            waste_factors[comp_id] = round(float(rng.uniform(1.2, 1.5)), 3)
        else:
            waste_factors[comp_id] = round(float(rng.uniform(1.0, 1.1)), 3)

    n_cons = max(1, n_ws // 2)
    n_supp_rpt = max(1, n_ws - n_cons)

    # ── Consumption Logs (CSV) ──
    for log_idx in range(n_cons):
        week_start = today - timedelta(days=7 * (n_cons - log_idx))
        rows = []
        for day_off in range(5):
            log_date = week_start + timedelta(days=day_off)
            for _, lid, dt, sdate, edate in active_sched_db:
                if date.fromisoformat(sdate) <= log_date <= date.fromisoformat(edate):
                    for cid, upr in lc_map_db.get(lid, []):
                        expected = dt * upr
                        wf = waste_factors.get(cid, 1.0)
                        actual = round(
                            expected * wf * float(rng.uniform(0.9, 1.1)), 1
                        )
                        rows.append({
                            "date": str(log_date),
                            "line_id": lid,
                            "component_id": cid,
                            "units_consumed": actual,
                        })
        df = (pd.DataFrame(rows) if rows
              else pd.DataFrame(columns=["date", "line_id",
                                         "component_id", "units_consumed"]))
        df.to_csv(os.path.join(workspace,
                               f"consumption_log_week_{log_idx + 1}.csv"),
                  index=False)

    # ── Supplier Delivery Reports (JSON) ──
    sc_by_supp = {}
    for row in cur.execute(
        "SELECT supplier_id, component_id, lead_time_days "
        "FROM supplier_components"
    ):
        sc_by_supp.setdefault(row[0], []).append((row[1], row[2]))

    supp_ids = list(range(1, n_supp + 1))
    chunk = max(1, len(supp_ids) // n_supp_rpt)

    for rpt_idx in range(n_supp_rpt):
        si = rpt_idx * chunk
        ei = si + chunk if rpt_idx < n_supp_rpt - 1 else len(supp_ids)
        batch = supp_ids[si:ei]

        records = []
        for sid in batch:
            for cid, base_lead in sc_by_supp.get(sid, []):
                n_del = int(rng.integers(5, 15))
                for _ in range(n_del):
                    if rng.random() < 0.75:
                        actual = int(base_lead + rng.integers(-1, 2))
                    else:
                        actual = int(base_lead + rng.integers(2, 10))
                    records.append({
                        "supplier_id": int(sid),
                        "component_id": int(cid),
                        "promised_lead_days": int(base_lead),
                        "actual_lead_days": max(1, actual),
                        "quantity_delivered": int(rng.integers(50, 500)),
                        "delivery_date": str(
                            today - timedelta(days=int(rng.integers(10, 180)))
                        ),
                    })

        with open(os.path.join(workspace,
                               f"supplier_delivery_batch_{rpt_idx + 1}.json"),
                  "w") as f:
            json.dump(records, f, indent=2)

    # ── Fixed: risk_config.yaml ──
    risk_config = {
        "safety_stock_days": {
            "electronic": 7,
            "mechanical": 5,
            "raw_material": 10,
            "chemical": 8,
            "fastener": 3,
        },
        "risk_levels": {
            "critical": 0.8,
            "high": 0.5,
            "medium": 0.2,
            "low": 0.0,
        },
    }
    with open(os.path.join(workspace, "risk_config.yaml"), "w") as f:
        yaml.dump(risk_config, f, default_flow_style=False, sort_keys=False)

    # ── Fixed: priority_weights.json ──
    priority_weights = {
        "weights": {
            "shortage_severity": 0.35,
            "criticality": 0.25,
            "production_priority": 0.20,
            "lead_time_urgency": 0.20,
        },
        "criticality_scores": {
            "tier_1": 1.0,
            "tier_2": 0.6,
            "tier_3": 0.3,
        },
        "production_priority_scores": {
            "high": 1.0,
            "medium": 0.6,
            "low": 0.3,
        },
    }
    with open(os.path.join(workspace, "priority_weights.json"), "w") as f:
        json.dump(priority_weights, f, indent=2)

    # ── Fixed: procurement_policy.md ──
    policy = (
        "When selecting a supplier for a component, evaluate all available "
        "suppliers using their on-time delivery rate computed from historical "
        "delivery records. The on-time delivery rate is the fraction of "
        "deliveries where the actual lead time did not exceed the promised "
        "lead time.\n\n"
        "A supplier qualifies if their on-time delivery rate is at least "
        "0.80. Among qualifying suppliers, select the one with the lowest "
        "adjusted cost. The adjusted cost equals unit_price multiplied by "
        "the lead time adjustment factor.\n\n"
        "Lead time adjustment factors:\n"
        "- On-time rate >= 0.90: factor = 1.00\n"
        "- On-time rate >= 0.80 and < 0.90: factor = 1.15\n"
        "- On-time rate >= 0.70 and < 0.80: factor = 1.30\n"
        "- On-time rate < 0.70: factor = 1.50\n\n"
        "If no supplier for a component achieves an on-time rate of 0.80 or "
        "above, select the supplier with the highest on-time rate.\n\n"
        "Order quantities must be rounded up to the nearest multiple of the "
        "selected supplier's minimum order quantity. If the base order "
        "quantity (net need) is less than the minimum order quantity, order "
        "exactly the minimum order quantity.\n\n"
        "The estimated lead time for a purchase order equals the supplier's "
        "base lead time (from the database) divided by their on-time rate, "
        "rounded up to the nearest whole number of days.\n"
    )
    with open(os.path.join(workspace, "procurement_policy.md"), "w") as f:
        f.write(policy)

    # ── Fixed: component_criticality.csv ──
    crit_rows = []
    for comp_id, _, cat, _ in components:
        r = float(rng.random())
        if cat in ("electronic", "chemical"):
            tier = 1 if r < 0.4 else (2 if r < 0.75 else 3)
        elif cat in ("mechanical", "raw_material"):
            tier = 1 if r < 0.2 else (2 if r < 0.6 else 3)
        else:
            tier = 1 if r < 0.1 else (2 if r < 0.4 else 3)
        crit_rows.append({"component_id": comp_id, "criticality_tier": tier})
    pd.DataFrame(crit_rows).to_csv(
        os.path.join(workspace, "component_criticality.csv"), index=False
    )

    conn.close()
    print(f"Database: {db_path}  |  Workspace: {workspace}/")
    print(f"  {n_cons} consumption logs, {n_supp_rpt} supplier reports, "
          "4 config files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
