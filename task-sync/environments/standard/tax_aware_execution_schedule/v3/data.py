import argparse
import sqlite3
import os
import json
import csv
import yaml
import numpy as np
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 480,
    "num_workspace_files": 32,
}

REFERENCE_DATE = datetime(2026, 4, 20)
REFERENCE_DATE_STR = "2026-04-20"

JURISDICTIONS = ["CA", "NY", "TX", "FL", "IL", "WA", "MA", "NJ"]
SECTORS = [
    "Technology", "Healthcare", "Financial Services", "Energy",
    "Consumer Discretionary", "Consumer Staples", "Industrials",
    "Utilities", "Real Estate", "Materials",
]
ASSET_CLASSES = ["us_equity", "intl_equity", "fixed_income", "etf", "reit"]
FILING_STATUSES = ["single", "married_joint", "married_separate"]
ACCOUNT_TYPES_MAP = {
    "taxable": ["individual", "joint", "trust"],
    "tax_deferred": ["traditional_ira", "401k"],
    "tax_exempt": ["roth_ira", "hsa"],
}
TAX_STATUS_CHOICES = ["taxable", "tax_deferred", "tax_exempt"]
TAX_STATUS_WEIGHTS = [0.60, 0.25, 0.15]

TRADE_REASONS = [
    "portfolio_drift", "target_rebalance", "risk_reduction",
    "sector_rotation", "cash_raise", "tax_loss_harvest",
    "overweight_correction", "underweight_correction",
]


def _create_tables(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS clients (
        client_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        tax_status TEXT NOT NULL,
        filing_status TEXT NOT NULL,
        jurisdiction TEXT NOT NULL,
        account_type TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS securities (
        security_id TEXT PRIMARY KEY,
        ticker TEXT NOT NULL,
        name TEXT NOT NULL,
        sector TEXT NOT NULL,
        asset_class TEXT NOT NULL,
        current_price REAL NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS tax_lots (
        lot_id TEXT PRIMARY KEY,
        client_id TEXT NOT NULL,
        security_id TEXT NOT NULL,
        purchase_date TEXT NOT NULL,
        quantity REAL NOT NULL,
        cost_basis_per_share REAL NOT NULL,
        is_covered INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (client_id) REFERENCES clients(client_id),
        FOREIGN KEY (security_id) REFERENCES securities(security_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS capital_gains_ytd (
        record_id TEXT PRIMARY KEY,
        client_id TEXT NOT NULL,
        security_id TEXT NOT NULL,
        realized_gain REAL NOT NULL,
        sale_date TEXT NOT NULL,
        holding_period TEXT NOT NULL,
        proceeds REAL NOT NULL,
        FOREIGN KEY (client_id) REFERENCES clients(client_id),
        FOREIGN KEY (security_id) REFERENCES securities(security_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS transaction_history (
        txn_id TEXT PRIMARY KEY,
        client_id TEXT NOT NULL,
        security_id TEXT NOT NULL,
        txn_type TEXT NOT NULL,
        txn_date TEXT NOT NULL,
        quantity REAL NOT NULL,
        price_per_share REAL NOT NULL,
        FOREIGN KEY (client_id) REFERENCES clients(client_id),
        FOREIGN KEY (security_id) REFERENCES securities(security_id)
    )""")


def _gen_config_files(workspace):
    """Write fixed policy / config files (not counted in SCALE)."""
    tax_rates = {
        "short_term_federal_rate": 0.35,
        "long_term_federal_rate": 0.15,
        "state_rates": {
            "CA": 0.133, "NY": 0.109, "TX": 0.0, "FL": 0.0,
            "IL": 0.0495, "WA": 0.0, "MA": 0.05, "NJ": 0.1075,
        },
    }
    with open(os.path.join(workspace, "tax_rates.json"), "w") as f:
        json.dump(tax_rates, f, indent=2)

    wash_sale_rules = {
        "federal": {
            "lookback_days": 30,
            "lookahead_days": 30,
            "applies_to_account_types": ["taxable"],
            "trigger": "substantially_identical_security",
        },
        "state_overrides": {
            "CA": {"conformity": "full", "additional_lookback_days": 0},
            "NY": {"conformity": "full", "additional_lookback_days": 0},
            "MA": {"conformity": "full", "additional_lookback_days": 0},
            "NJ": {"conformity": "full", "additional_lookback_days": 0},
            "IL": {"conformity": "full", "additional_lookback_days": 0},
        },
    }
    with open(os.path.join(workspace, "wash_sale_rules.yaml"), "w") as f:
        yaml.dump(wash_sale_rules, f, default_flow_style=False)

    policy = {
        "max_ytd_short_term_gain_per_client": 50000,
        "max_ytd_long_term_gain_per_client": 100000,
        "lot_selection_method": "highest_cost_first",
        "min_tax_savings_to_defer_usd": 500,
        "base_execution_date": "2026-05-01",
        "defer_date": "2027-01-02",
        "holding_period_long_term_days": 366,
        "reference_date": REFERENCE_DATE_STR,
    }
    with open(os.path.join(workspace, "rebalancing_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False)

    adjustments_md = (
        "The base gain thresholds specified in the rebalancing policy should be "
        "adjusted according to the client's filing status before comparing against "
        "year-to-date totals. Clients filing as married_joint receive a multiplier "
        "of 1.25 applied to both the short-term and long-term gain thresholds. "
        "Clients filing as married_separate receive a multiplier of 0.75. Clients "
        "filing as single use the base thresholds without adjustment (multiplier 1.0).\n"
    )
    with open(os.path.join(workspace, "gain_threshold_adjustments.md"), "w") as f:
        f.write(adjustments_md)


def main(db_path, workspace):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)
    os.makedirs(workspace, exist_ok=True)

    rows = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    num_clients = max(10, rows // 6)
    num_securities = max(15, rows // 4)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    _create_tables(cur)

    # ------------------------------------------------------------------ clients
    clients = []
    for i in range(num_clients):
        cid = f"C{i + 1:04d}"
        name = fake.name()
        ts = TAX_STATUS_CHOICES[int(np.random.choice(3, p=TAX_STATUS_WEIGHTS))]
        fs = FILING_STATUSES[int(np.random.randint(len(FILING_STATUSES)))]
        jur = JURISDICTIONS[int(np.random.randint(len(JURISDICTIONS)))]
        at = np.random.choice(ACCOUNT_TYPES_MAP[ts])
        clients.append((cid, name, ts, fs, jur, at))
    cur.executemany("INSERT INTO clients VALUES (?,?,?,?,?,?)", clients)

    taxable_clients = [c for c in clients if c[2] == "taxable"]
    client_ids = [c[0] for c in clients]

    # --------------------------------------------------------------- securities
    used_tickers = set()
    securities = []
    for i in range(num_securities):
        sid = f"SEC{i + 1:04d}"
        while True:
            tk = "".join(
                chr(int(np.random.randint(65, 91)))
                for _ in range(int(np.random.choice([3, 4])))
            )
            if tk not in used_tickers:
                used_tickers.add(tk)
                break
        sname = fake.company()
        sector = SECTORS[int(np.random.randint(len(SECTORS)))]
        ac = ASSET_CLASSES[int(np.random.randint(len(ASSET_CLASSES)))]
        price = round(float(np.random.uniform(20, 400)), 2)
        securities.append((sid, tk, sname, sector, ac, price))
    cur.executemany("INSERT INTO securities VALUES (?,?,?,?,?,?)", securities)

    sec_prices = {s[0]: s[5] for s in securities}
    security_ids = [s[0] for s in securities]

    # ------------------------------------------------------------ tax_lots
    lots = []
    lot_idx = 0

    # --- Injected lots for guaranteed patterns ---
    # Pattern A: WASH_SALE_RISK sell (loss lot + recent buy)
    #   Client = taxable_clients[0], Security = security_ids[0]
    if len(taxable_clients) >= 1:
        ws_c = taxable_clients[0][0]
        ws_s = security_ids[0]
        ws_p = sec_prices[ws_s]
        lot_idx += 1
        lots.append((
            f"LOT{lot_idx:06d}", ws_c, ws_s,
            (REFERENCE_DATE - timedelta(days=400)).strftime("%Y-%m-%d"),
            150.0, round(ws_p * 1.30, 2), 1,
        ))  # cost > current -> loss

    # Pattern B: SUBOPTIMAL_LOT sell (short-term + long-term lots, gain trade)
    #   Client = taxable_clients[0], Security = security_ids[1]
    if len(taxable_clients) >= 1 and len(security_ids) >= 2:
        sl_c = taxable_clients[0][0]
        sl_s = security_ids[1]
        sl_p = sec_prices[sl_s]
        lot_idx += 1
        lots.append((
            f"LOT{lot_idx:06d}", sl_c, sl_s,
            (REFERENCE_DATE - timedelta(days=500)).strftime("%Y-%m-%d"),
            120.0, round(sl_p * 0.55, 2), 1,
        ))  # long-term, low cost -> gain
        lot_idx += 1
        lots.append((
            f"LOT{lot_idx:06d}", sl_c, sl_s,
            (REFERENCE_DATE - timedelta(days=90)).strftime("%Y-%m-%d"),
            120.0, round(sl_p * 0.82, 2), 1,
        ))  # short-term, higher cost -> gain, selected first by highest_cost_first

    # Pattern C (lots for excessive-gain client)
    if len(taxable_clients) >= 3 and len(security_ids) >= 4:
        eg_c = taxable_clients[2][0]
        eg_s = security_ids[3]
        eg_p = sec_prices[eg_s]
        lot_idx += 1
        lots.append((
            f"LOT{lot_idx:06d}", eg_c, eg_s,
            (REFERENCE_DATE - timedelta(days=80)).strftime("%Y-%m-%d"),
            500.0, round(eg_p * 0.30, 2), 1,
        ))  # short-term, very low cost -> big gain

    # --- Random fill to reach rows ---
    remaining_lots = rows - lot_idx
    for _ in range(remaining_lots):
        lot_idx += 1
        cid = client_ids[int(np.random.randint(len(client_ids)))]
        sid = security_ids[int(np.random.randint(len(security_ids)))]
        cp = sec_prices[sid]
        days_ago = int(np.random.randint(30, 1100))
        pdate = (REFERENCE_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        qty = round(float(np.random.uniform(10, 300)), 2)
        cost_mult = float(np.random.choice([0.50, 0.65, 0.75, 0.85, 0.95, 1.05, 1.15, 1.30]))
        cb = round(cp * cost_mult, 2)
        is_cov = 1 if float(np.random.random()) > 0.1 else 0
        lots.append((f"LOT{lot_idx:06d}", cid, sid, pdate, qty, cb, is_cov))

    cur.executemany("INSERT INTO tax_lots VALUES (?,?,?,?,?,?,?)", lots)

    # Build holdings map for generating valid sell trades later
    holdings = {}  # (client_id, security_id) -> total_qty
    for lot in lots:
        key = (lot[1], lot[2])
        holdings[key] = holdings.get(key, 0) + lot[4]

    # --------------------------------------------------------- capital_gains_ytd
    cap_gains = []
    cg_idx = 0

    # Injection: excessive-gain client has ~62 000 YTD short-term gains
    if len(taxable_clients) >= 3:
        eg_c = taxable_clients[2][0]
        for g in [18000.0, 20000.0, 14000.0, 10000.0]:
            cg_idx += 1
            sid = security_ids[int(np.random.randint(len(security_ids)))]
            days_ago = int(np.random.randint(10, 100))
            sdate = (REFERENCE_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            proceeds = round(g + float(np.random.uniform(15000, 50000)), 2)
            cap_gains.append((
                f"CG{cg_idx:06d}", eg_c, sid, g, sdate, "short_term", proceeds,
            ))

    # Injection: loss record for buy-side wash sale
    #   Client = taxable_clients[1], Security = security_ids[2]
    if len(taxable_clients) >= 2 and len(security_ids) >= 3:
        ws_buy_c = taxable_clients[1][0]
        ws_buy_s = security_ids[2]
        cg_idx += 1
        loss_date = (REFERENCE_DATE - timedelta(days=12)).strftime("%Y-%m-%d")
        cap_gains.append((
            f"CG{cg_idx:06d}", ws_buy_c, ws_buy_s, -4200.0, loss_date,
            "short_term", round(4200.0 + 18000.0, 2),
        ))

    # Random fill
    num_cg = max(30, rows // 2)
    remaining_cg = num_cg - cg_idx
    for _ in range(remaining_cg):
        cg_idx += 1
        cid = client_ids[int(np.random.randint(len(client_ids)))]
        sid = security_ids[int(np.random.randint(len(security_ids)))]
        rg = round(float(np.random.uniform(-4000, 10000)), 2)
        days_ago = int(np.random.randint(1, 110))
        sdate = (REFERENCE_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        hp = "short_term" if float(np.random.random()) < 0.4 else "long_term"
        proceeds = round(abs(rg) + float(np.random.uniform(2000, 40000)), 2)
        cap_gains.append((f"CG{cg_idx:06d}", cid, sid, rg, sdate, hp, proceeds))

    cur.executemany("INSERT INTO capital_gains_ytd VALUES (?,?,?,?,?,?,?)", cap_gains)

    # ------------------------------------------------------ transaction_history
    txns = []
    txn_idx = 0

    # Injection: recent buy for sell-side wash sale
    if len(taxable_clients) >= 1:
        ws_c = taxable_clients[0][0]
        ws_s = security_ids[0]
        txn_idx += 1
        tdate = (REFERENCE_DATE - timedelta(days=8)).strftime("%Y-%m-%d")
        txns.append((
            f"TXN{txn_idx:06d}", ws_c, ws_s, "buy", tdate,
            60.0, round(sec_prices[ws_s] * 1.01, 2),
        ))

    # Injection: recent sell (loss) for buy-side wash sale
    if len(taxable_clients) >= 2 and len(security_ids) >= 3:
        ws_buy_c = taxable_clients[1][0]
        ws_buy_s = security_ids[2]
        txn_idx += 1
        tdate = (REFERENCE_DATE - timedelta(days=12)).strftime("%Y-%m-%d")
        txns.append((
            f"TXN{txn_idx:06d}", ws_buy_c, ws_buy_s, "sell", tdate,
            70.0, round(sec_prices[ws_buy_s] * 0.82, 2),
        ))

    # Random fill
    remaining_txns = rows - txn_idx
    for _ in range(remaining_txns):
        txn_idx += 1
        cid = client_ids[int(np.random.randint(len(client_ids)))]
        sid = security_ids[int(np.random.randint(len(security_ids)))]
        tt = "buy" if float(np.random.random()) < 0.5 else "sell"
        days_ago = int(np.random.randint(1, 90))
        tdate = (REFERENCE_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        qty = round(float(np.random.uniform(5, 200)), 2)
        price = round(sec_prices[sid] * float(np.random.uniform(0.85, 1.15)), 2)
        txns.append((f"TXN{txn_idx:06d}", cid, sid, tt, tdate, qty, price))

    cur.executemany("INSERT INTO transaction_history VALUES (?,?,?,?,?,?,?)", txns)

    conn.commit()
    conn.close()

    # ------------------------------------------------- workspace: config files
    _gen_config_files(workspace)

    # ------------------------------------------- workspace: proposed trade CSVs
    trades = []
    trade_idx = 0

    # Injected trades ---------------------------------------------------------
    # Trade 1 -> WASH_SALE_RISK sell (C=taxable[0], S=sec[0])
    if len(taxable_clients) >= 1:
        trade_idx += 1
        trades.append({
            "trade_id": f"TR{trade_idx:06d}",
            "client_id": taxable_clients[0][0],
            "security_id": security_ids[0],
            "action": "sell",
            "proposed_quantity": 50.0,
            "urgency": 3,
            "reason": "risk_reduction",
        })

    # Trade 2 -> SUBOPTIMAL_LOT sell (C=taxable[0], S=sec[1])
    if len(taxable_clients) >= 1 and len(security_ids) >= 2:
        trade_idx += 1
        trades.append({
            "trade_id": f"TR{trade_idx:06d}",
            "client_id": taxable_clients[0][0],
            "security_id": security_ids[1],
            "action": "sell",
            "proposed_quantity": 50.0,
            "urgency": 4,
            "reason": "overweight_correction",
        })

    # Trade 3 -> WASH_SALE_RISK buy (C=taxable[1], S=sec[2])
    if len(taxable_clients) >= 2 and len(security_ids) >= 3:
        trade_idx += 1
        trades.append({
            "trade_id": f"TR{trade_idx:06d}",
            "client_id": taxable_clients[1][0],
            "security_id": security_ids[2],
            "action": "buy",
            "proposed_quantity": 40.0,
            "urgency": 2,
            "reason": "underweight_correction",
        })

    # Trade 4 -> EXCESSIVE_GAIN sell (C=taxable[2], S=sec[3])
    if len(taxable_clients) >= 3 and len(security_ids) >= 4:
        trade_idx += 1
        trades.append({
            "trade_id": f"TR{trade_idx:06d}",
            "client_id": taxable_clients[2][0],
            "security_id": security_ids[3],
            "action": "sell",
            "proposed_quantity": 150.0,
            "urgency": 2,
            "reason": "cash_raise",
        })

    # Random fill trades ------------------------------------------------------
    np.random.seed(4242)  # secondary seed for trade generation
    total_trades = num_files * 4
    remaining_trades = total_trades - trade_idx

    holdings_list = list(holdings.keys())  # (client_id, security_id) pairs

    for _ in range(remaining_trades):
        trade_idx += 1
        action = "sell" if float(np.random.random()) < 0.60 else "buy"
        if action == "sell" and holdings_list:
            idx_h = int(np.random.randint(len(holdings_list)))
            cid, sid = holdings_list[idx_h]
            max_qty = holdings[(cid, sid)]
            qty = round(min(float(np.random.uniform(10, 150)), max_qty), 2)
        else:
            action = "buy"
            cid = client_ids[int(np.random.randint(len(client_ids)))]
            sid = security_ids[int(np.random.randint(len(security_ids)))]
            qty = round(float(np.random.uniform(10, 150)), 2)
        urg = int(np.random.randint(1, 6))
        reason = TRADE_REASONS[int(np.random.randint(len(TRADE_REASONS)))]
        trades.append({
            "trade_id": f"TR{trade_idx:06d}",
            "client_id": cid,
            "security_id": sid,
            "action": action,
            "proposed_quantity": qty,
            "urgency": urg,
            "reason": reason,
        })

    # Split into CSV batch files
    per_file = len(trades) // num_files
    leftover = len(trades) % num_files
    idx = 0
    for fi in range(num_files):
        cnt = per_file + (1 if fi < leftover else 0)
        batch = trades[idx: idx + cnt]
        idx += cnt
        fpath = os.path.join(workspace, f"proposed_trades_batch_{fi + 1:03d}.csv")
        with open(fpath, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "trade_id", "client_id", "security_id", "action",
                    "proposed_quantity", "urgency", "reason",
                ],
            )
            writer.writeheader()
            writer.writerows(batch)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
