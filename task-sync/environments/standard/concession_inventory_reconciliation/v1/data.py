#!/usr/bin/env python3
"""
Data generation for Concession Stand Inventory Shrinkage Detection.
Generates SQLite database and workspace files at configurable scale.
"""

import argparse
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from faker import Faker


# ── Scale Configuration ──────────────────────────────────────────
SCALE = {
    "rows_per_table": 200,       # v1 = 2x base
    "num_workspace_files": 20,   # v1 = base + N
}

# ── Seeds ─────────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ── Constants ─────────────────────────────────────────────────────
NUM_STANDS = 10
NUM_PRODUCTS = 20
ANALYSIS_START = datetime(2025, 1, 6)
ANALYSIS_END = datetime(2025, 1, 19)
NUM_DAYS = (ANALYSIS_END - ANALYSIS_START).days + 1  # 14 days
SHIFT_TYPES = ["morning", "evening"]
SHRINKAGE_STAND_INDICES = [1, 4, 7]  # 0-indexed: stands 2, 5, 8

STAND_NAMES = [
    "North Gate Snacks", "Main Court Beverages", "East Wing Grill",
    "South Entrance Treats", "VIP Lounge Bar", "Family Zone Eats",
    "West Terrace Cafe", "Arena Core Drinks", "Skybox Catering",
    "Plaza Food Court",
]
SECTIONS = [
    "North", "Central", "East", "South", "VIP",
    "Family", "West", "Central", "Upper", "Plaza",
]

PRODUCTS_DATA = [
    ("Hot Dog", "Food", 1.20, 4.50),
    ("Nachos", "Food", 1.50, 5.00),
    ("Popcorn Large", "Snacks", 0.80, 6.00),
    ("Popcorn Small", "Snacks", 0.40, 3.50),
    ("Soft Pretzel", "Snacks", 0.90, 4.00),
    ("Cotton Candy", "Snacks", 0.50, 5.50),
    ("Ice Cream Bar", "Frozen", 1.00, 4.50),
    ("Frozen Lemonade", "Frozen", 0.70, 5.00),
    ("Soda Large", "Beverages", 0.30, 5.50),
    ("Soda Small", "Beverages", 0.20, 3.00),
    ("Bottled Water", "Beverages", 0.15, 3.50),
    ("Beer Draft", "Alcohol", 1.80, 8.00),
    ("Beer Bottle", "Alcohol", 2.00, 7.50),
    ("Pizza Slice", "Food", 1.40, 5.50),
    ("Chicken Tenders", "Food", 2.00, 7.00),
    ("French Fries", "Food", 0.60, 4.00),
    ("Candy Bar", "Snacks", 0.80, 3.00),
    ("Peanuts", "Snacks", 0.50, 4.50),
    ("Energy Drink", "Beverages", 1.50, 5.00),
    ("Coffee", "Beverages", 0.40, 3.50),
]

VENDORS = [
    "FreshFoods Inc.", "BeverageCo Supply", "SnackWorld Distribution",
    "PremiumGoods LLC", "QuickServe Wholesale",
]

WASTE_REASONS = ["spoilage", "damage", "expired", "contamination", "overproduction"]
RETURN_REASONS = ["wrong_order", "quality_issue", "changed_mind", "overcharged"]
PAYMENT_METHODS = ["cash", "card", "mobile"]


def build_ids():
    stand_ids = [f"STD-{i+1:03d}" for i in range(NUM_STANDS)]
    product_ids = [f"PRD-{i+1:03d}" for i in range(NUM_PRODUCTS)]
    return stand_ids, product_ids


def generate_staff(num):
    return [{"employee_id": f"EMP-{i+1:03d}", "employee_name": fake.name()} for i in range(num)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    db_path = args.db_path
    workspace = args.workspace
    os.makedirs(workspace, exist_ok=True)

    rows = SCALE["rows_per_table"]
    num_ws_files = SCALE["num_workspace_files"]

    stand_ids, product_ids = build_ids()
    num_staff = max(NUM_STANDS * 4, 40)
    staff = generate_staff(num_staff)

    # ══════════════════════════════════════════════════════════════
    # Phase 1: Generate raw transaction data
    # ══════════════════════════════════════════════════════════════

    # --- POS Transactions ---
    num_txns = max(rows, rows * 5)
    pos_transactions = []
    for i in range(num_txns):
        sid = random.choice(stand_ids)
        pid = random.choice(product_ids)
        pidx = product_ids.index(pid)
        qty = random.randint(1, 5)
        day = random.randint(0, NUM_DAYS - 1)
        hour = random.randint(8, 21)
        minute = random.randint(0, 59)
        txn_time = (ANALYSIS_START + timedelta(days=day)).replace(hour=hour, minute=minute)
        shift = "morning" if hour < 15 else "evening"
        pos_transactions.append({
            "transaction_id": i + 1,
            "stand_id": sid,
            "product_id": pid,
            "quantity_sold": qty,
            "unit_price": PRODUCTS_DATA[pidx][3],
            "transaction_time": txn_time.strftime("%Y-%m-%d %H:%M:%S"),
            "shift_type": shift,
            "payment_method": random.choice(PAYMENT_METHODS),
        })

    # --- Delivery records (for workspace files) ---
    num_deliveries = max(rows, rows * 2)
    all_deliveries = []
    for i in range(num_deliveries):
        sid = random.choice(stand_ids)
        pid = random.choice(product_ids)
        pidx = product_ids.index(pid)
        qty = random.randint(10, 50)
        day = random.randint(0, NUM_DAYS - 1)
        d_date = (ANALYSIS_START + timedelta(days=day)).strftime("%Y-%m-%d")
        vendor = random.choice(VENDORS)
        all_deliveries.append({
            "invoice_number": f"INV-{100000 + i:06d}",
            "stand_id": sid,
            "product_id": pid,
            "product_name": PRODUCTS_DATA[pidx][0],
            "quantity_delivered": qty,
            "delivery_date": d_date,
            "vendor": vendor,
            "unit_cost": PRODUCTS_DATA[pidx][2],
            "total_cost": round(qty * PRODUCTS_DATA[pidx][2], 2),
        })

    # --- Waste records (for workspace files) ---
    all_waste = []
    for sid in stand_ids:
        for pid in product_ids:
            pidx = product_ids.index(pid)
            if random.random() < 0.45:
                qty = random.randint(1, 10)
                day = random.randint(0, NUM_DAYS - 1)
                w_date = (ANALYSIS_START + timedelta(days=day)).strftime("%Y-%m-%d")
                all_waste.append({
                    "stand_id": sid,
                    "product_id": pid,
                    "product_name": PRODUCTS_DATA[pidx][0],
                    "quantity_wasted": qty,
                    "waste_date": w_date,
                    "reason": random.choice(WASTE_REASONS),
                    "shift_type": random.choice(SHIFT_TYPES),
                })

    # --- Customer Returns ---
    num_returns = max(rows, rows)
    customer_returns = []
    for i in range(num_returns):
        sid = random.choice(stand_ids)
        pid = random.choice(product_ids)
        pidx = product_ids.index(pid)
        qty = random.randint(1, 3)
        day = random.randint(0, NUM_DAYS - 1)
        r_date = (ANALYSIS_START + timedelta(days=day)).strftime("%Y-%m-%d")
        customer_returns.append({
            "return_id": i + 1,
            "stand_id": sid,
            "product_id": pid,
            "quantity_returned": qty,
            "return_date": r_date,
            "reason": random.choice(RETURN_REASONS),
            "refund_amount": round(qty * PRODUCTS_DATA[pidx][3], 2),
        })

    # --- Inter-stand Transfers ---
    num_transfers = max(rows, rows)
    transfers = []
    for i in range(num_transfers):
        from_s = random.choice(stand_ids)
        to_s = random.choice([s for s in stand_ids if s != from_s])
        pid = random.choice(product_ids)
        qty = random.randint(2, 15)
        day = random.randint(0, NUM_DAYS - 1)
        t_date = (ANALYSIS_START + timedelta(days=day)).strftime("%Y-%m-%d")
        transfers.append({
            "transfer_id": i + 1,
            "from_stand_id": from_s,
            "to_stand_id": to_s,
            "product_id": pid,
            "quantity": qty,
            "transfer_date": t_date,
            "approved_by": random.choice(staff)["employee_name"],
        })

    # --- Staff Schedules ---
    staff_schedules = []
    sched_id = 0
    for day_offset in range(NUM_DAYS):
        shift_date = (ANALYSIS_START + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        for sid in stand_ids:
            for shift in SHIFT_TYPES:
                n_assigned = random.randint(2, 4)
                chosen = random.sample(staff, n_assigned)
                for emp in chosen:
                    sched_id += 1
                    cin = "07:00" if shift == "morning" else "15:00"
                    cout = "15:00" if shift == "morning" else "23:00"
                    staff_schedules.append({
                        "schedule_id": sched_id,
                        "employee_id": emp["employee_id"],
                        "employee_name": emp["employee_name"],
                        "stand_id": sid,
                        "shift_date": shift_date,
                        "shift_type": shift,
                        "clock_in": cin,
                        "clock_out": cout,
                    })
    # Pad to meet SCALE minimum
    while len(staff_schedules) < rows:
        sched_id += 1
        emp = random.choice(staff)
        sid = random.choice(stand_ids)
        day_offset = random.randint(0, NUM_DAYS - 1)
        shift_date = (ANALYSIS_START + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        shift = random.choice(SHIFT_TYPES)
        cin = "07:00" if shift == "morning" else "15:00"
        cout = "15:00" if shift == "morning" else "23:00"
        staff_schedules.append({
            "schedule_id": sched_id,
            "employee_id": emp["employee_id"],
            "employee_name": emp["employee_name"],
            "stand_id": sid,
            "shift_date": shift_date,
            "shift_type": shift,
            "clock_in": cin,
            "clock_out": cout,
        })

    # ══════════════════════════════════════════════════════════════
    # Phase 2: Aggregate per (stand, product)
    # ══════════════════════════════════════════════════════════════

    sales_agg = {}
    for t in pos_transactions:
        key = (t["stand_id"], t["product_id"])
        sales_agg[key] = sales_agg.get(key, 0) + t["quantity_sold"]

    delivery_agg = {}
    for d in all_deliveries:
        key = (d["stand_id"], d["product_id"])
        delivery_agg[key] = delivery_agg.get(key, 0) + d["quantity_delivered"]

    waste_agg = {}
    for w in all_waste:
        key = (w["stand_id"], w["product_id"])
        waste_agg[key] = waste_agg.get(key, 0) + w["quantity_wasted"]

    returns_agg = {}
    for r in customer_returns:
        key = (r["stand_id"], r["product_id"])
        returns_agg[key] = returns_agg.get(key, 0) + r["quantity_returned"]

    transfers_in_agg = {}
    transfers_out_agg = {}
    for t in transfers:
        k_out = (t["from_stand_id"], t["product_id"])
        k_in = (t["to_stand_id"], t["product_id"])
        transfers_out_agg[k_out] = transfers_out_agg.get(k_out, 0) + t["quantity"]
        transfers_in_agg[k_in] = transfers_in_agg.get(k_in, 0) + t["quantity"]

    # ══════════════════════════════════════════════════════════════
    # Phase 3: Compute beginning inventory (ensure positive ending)
    # ══════════════════════════════════════════════════════════════

    beginning_inventory = {}
    for sid in stand_ids:
        beginning_inventory[sid] = {}
        for pid in product_ids:
            key = (sid, pid)
            sold = sales_agg.get(key, 0)
            wasted = waste_agg.get(key, 0)
            t_out = transfers_out_agg.get(key, 0)
            delivered = delivery_agg.get(key, 0)
            t_in = transfers_in_agg.get(key, 0)
            returned = returns_agg.get(key, 0)

            consumed = sold + wasted + t_out
            supplied = delivered + t_in + returned
            min_begin = consumed - supplied + 15
            beginning_inventory[sid][pid] = max(30, min_begin + random.randint(5, 30))

    # ══════════════════════════════════════════════════════════════
    # Phase 4: Compute ending inventory with shrinkage
    # ══════════════════════════════════════════════════════════════

    ending_inventory = {}
    for sid in stand_ids:
        ending_inventory[sid] = {}
        sidx = stand_ids.index(sid)
        is_shrinkage = sidx in SHRINKAGE_STAND_INDICES

        for pid in product_ids:
            key = (sid, pid)
            begin = beginning_inventory[sid][pid]
            delivered = delivery_agg.get(key, 0)
            t_in = transfers_in_agg.get(key, 0)
            returned = returns_agg.get(key, 0)
            sold = sales_agg.get(key, 0)
            wasted = waste_agg.get(key, 0)
            t_out = transfers_out_agg.get(key, 0)

            supply = begin + delivered + t_in + returned
            consumed = sold + wasted + t_out
            expected_ending = supply - consumed

            shrinkage = 0
            if is_shrinkage:
                if random.random() < 0.65:
                    shrinkage_pct = random.uniform(0.06, 0.18)
                    shrinkage = max(1, int(supply * shrinkage_pct))
            else:
                if random.random() < 0.15:
                    shrinkage = 1

            actual_ending = max(0, expected_ending - shrinkage)
            ending_inventory[sid][pid] = actual_ending

    # ══════════════════════════════════════════════════════════════
    # Phase 5: Write database
    # ══════════════════════════════════════════════════════════════

    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE pos_transactions (
            transaction_id INTEGER PRIMARY KEY,
            stand_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            quantity_sold INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            transaction_time TEXT NOT NULL,
            shift_type TEXT NOT NULL,
            payment_method TEXT NOT NULL
        )
    """)
    cur.executemany(
        "INSERT INTO pos_transactions VALUES (?,?,?,?,?,?,?,?)",
        [(t["transaction_id"], t["stand_id"], t["product_id"],
          t["quantity_sold"], t["unit_price"], t["transaction_time"],
          t["shift_type"], t["payment_method"]) for t in pos_transactions],
    )

    cur.execute("""
        CREATE TABLE staff_schedules (
            schedule_id INTEGER PRIMARY KEY,
            employee_id TEXT NOT NULL,
            employee_name TEXT NOT NULL,
            stand_id TEXT NOT NULL,
            shift_date TEXT NOT NULL,
            shift_type TEXT NOT NULL,
            clock_in TEXT NOT NULL,
            clock_out TEXT NOT NULL
        )
    """)
    cur.executemany(
        "INSERT INTO staff_schedules VALUES (?,?,?,?,?,?,?,?)",
        [(s["schedule_id"], s["employee_id"], s["employee_name"],
          s["stand_id"], s["shift_date"], s["shift_type"],
          s["clock_in"], s["clock_out"]) for s in staff_schedules],
    )

    cur.execute("""
        CREATE TABLE customer_returns (
            return_id INTEGER PRIMARY KEY,
            stand_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            quantity_returned INTEGER NOT NULL,
            return_date TEXT NOT NULL,
            reason TEXT NOT NULL,
            refund_amount REAL NOT NULL
        )
    """)
    cur.executemany(
        "INSERT INTO customer_returns VALUES (?,?,?,?,?,?,?)",
        [(r["return_id"], r["stand_id"], r["product_id"],
          r["quantity_returned"], r["return_date"], r["reason"],
          r["refund_amount"]) for r in customer_returns],
    )

    cur.execute("""
        CREATE TABLE inter_stand_transfers (
            transfer_id INTEGER PRIMARY KEY,
            from_stand_id TEXT NOT NULL,
            to_stand_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            transfer_date TEXT NOT NULL,
            approved_by TEXT NOT NULL
        )
    """)
    cur.executemany(
        "INSERT INTO inter_stand_transfers VALUES (?,?,?,?,?,?,?)",
        [(t["transfer_id"], t["from_stand_id"], t["to_stand_id"],
          t["product_id"], t["quantity"], t["transfer_date"],
          t["approved_by"]) for t in transfers],
    )

    conn.commit()
    conn.close()

    # ══════════════════════════════════════════════════════════════
    # Phase 6: Write workspace files
    # ══════════════════════════════════════════════════════════════

    # ── Fixed files ──────────────────────────────────────────────

    # Product catalog (JSON)
    catalog = {}
    for i, (name, cat, cost, price) in enumerate(PRODUCTS_DATA):
        pid = f"PRD-{i+1:03d}"
        catalog[pid] = {
            "name": name,
            "category": cat,
            "unit_cost": cost,
            "unit_price": price,
        }
    with open(os.path.join(workspace, "product_catalog.json"), "w") as f:
        json.dump(catalog, f, indent=2)

    # Stand directory (YAML)
    stand_dir = {}
    for i in range(NUM_STANDS):
        sid = f"STD-{i+1:03d}"
        stand_dir[sid] = {
            "name": STAND_NAMES[i],
            "section": SECTIONS[i],
            "capacity": random.randint(2, 6),
        }
    with open(os.path.join(workspace, "stand_directory.yaml"), "w") as f:
        yaml.dump(stand_dir, f, default_flow_style=False, sort_keys=True)

    # Shrinkage policy (YAML)
    policy = {
        "analysis_period": {
            "start_date": ANALYSIS_START.strftime("%Y-%m-%d"),
            "end_date": ANALYSIS_END.strftime("%Y-%m-%d"),
        },
        "flagging_criteria": {
            "shrinkage_pct_threshold": 5.0,
            "min_shrinkage_value_usd": 50.0,
        },
        "investigation_priority": {
            "high": {"min_shrinkage_pct": 10.0},
            "medium": {"min_shrinkage_pct": 5.0},
            "low": {"min_shrinkage_pct": 2.0},
        },
        "value_basis": "unit_cost",
        "rounding_precision": 2,
    }
    with open(os.path.join(workspace, "shrinkage_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # Beginning inventory (CSV)
    begin_rows = []
    for sid in stand_ids:
        for pid in product_ids:
            begin_rows.append({
                "stand_id": sid,
                "product_id": pid,
                "quantity": beginning_inventory[sid][pid],
            })
    pd.DataFrame(begin_rows).to_csv(
        os.path.join(workspace, "beginning_inventory.csv"), index=False)

    # Ending inventory (CSV)
    end_rows = []
    for sid in stand_ids:
        for pid in product_ids:
            end_rows.append({
                "stand_id": sid,
                "product_id": pid,
                "quantity": ending_inventory[sid][pid],
            })
    pd.DataFrame(end_rows).to_csv(
        os.path.join(workspace, "ending_inventory.csv"), index=False)

    # ── Scalable files ───────────────────────────────────────────

    num_delivery_files = max(1, round(num_ws_files * 0.6))
    num_waste_files = num_ws_files - num_delivery_files

    # Delivery invoices (CSV)
    os.makedirs(os.path.join(workspace, "delivery_invoices"), exist_ok=True)
    random.shuffle(all_deliveries)
    chunks = np.array_split(range(len(all_deliveries)), num_delivery_files)
    for idx, indices in enumerate(chunks):
        chunk = [all_deliveries[int(j)] for j in indices]
        if not chunk:
            chunk = [all_deliveries[0]]
        pd.DataFrame(chunk).to_csv(
            os.path.join(workspace, "delivery_invoices", f"batch_{idx+1:03d}.csv"),
            index=False)

    # Waste logs (mixed formats: CSV, TXT pipe-delimited, MD table)
    os.makedirs(os.path.join(workspace, "waste_logs"), exist_ok=True)
    random.shuffle(all_waste)
    if all_waste:
        w_chunks = np.array_split(range(len(all_waste)), max(1, num_waste_files))
    else:
        w_chunks = [[] for _ in range(num_waste_files)]

    fmt_cycle = ["csv", "txt", "csv", "md"]
    for idx, indices in enumerate(w_chunks):
        chunk = [all_waste[int(j)] for j in indices]
        if not chunk:
            continue
        fmt = fmt_cycle[idx % len(fmt_cycle)]
        fname_base = f"waste_sheet_{idx+1:03d}"

        if fmt == "csv":
            pd.DataFrame(chunk).to_csv(
                os.path.join(workspace, "waste_logs", f"{fname_base}.csv"),
                index=False)
        elif fmt == "txt":
            header = "stand_id|product_id|product_name|quantity_wasted|waste_date|reason|shift_type"
            lines = [header]
            for w in chunk:
                lines.append(
                    f"{w['stand_id']}|{w['product_id']}|{w['product_name']}|"
                    f"{w['quantity_wasted']}|{w['waste_date']}|{w['reason']}|{w['shift_type']}"
                )
            with open(os.path.join(workspace, "waste_logs", f"{fname_base}.txt"), "w") as f:
                f.write("\n".join(lines) + "\n")
        elif fmt == "md":
            lines = [
                "| stand_id | product_id | product_name | quantity_wasted | waste_date | reason | shift_type |",
                "|----------|------------|--------------|-----------------|------------|--------|------------|",
            ]
            for w in chunk:
                lines.append(
                    f"| {w['stand_id']} | {w['product_id']} | {w['product_name']} "
                    f"| {w['quantity_wasted']} | {w['waste_date']} | {w['reason']} | {w['shift_type']} |"
                )
            with open(os.path.join(workspace, "waste_logs", f"{fname_base}.md"), "w") as f:
                f.write("\n".join(lines) + "\n")

    print(f"Database: {db_path}")
    print(f"Workspace: {workspace}")
    print(f"  POS transactions: {len(pos_transactions)}")
    print(f"  Staff schedules:  {len(staff_schedules)}")
    print(f"  Customer returns: {len(customer_returns)}")
    print(f"  Transfers:        {len(transfers)}")
    print(f"  Delivery files:   {num_delivery_files}")
    print(f"  Waste log files:  {num_waste_files}")


if __name__ == "__main__":
    main()
