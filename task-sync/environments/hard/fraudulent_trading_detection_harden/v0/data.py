import argparse
import sqlite3
import os
import json
import csv
import random
import math
import numpy as np
from faker import Faker
from datetime import datetime, timedelta

try:
    import yaml
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml", "-q"])
    import yaml

SCALE = {
    "rows_per_table": 100,
    "num_workspace_files": 10,
}

# --------------- deterministic seeds ---------------
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# --------------- constants ---------------
REFERENCE_DATE = datetime(2025, 6, 15)

REGIONS = ["NA", "EU", "APAC", "SA", "Other"]
RARITY_TIERS = ["Common", "Uncommon", "Rare", "Epic", "Legendary"]
RARITY_WEIGHTS = [0.35, 0.25, 0.20, 0.12, 0.08]
RARITY_BASE_RANGES = {
    "Common": (10, 100),
    "Uncommon": (100, 500),
    "Rare": (500, 2000),
    "Epic": (2000, 10000),
    "Legendary": (10000, 50000),
}
RARITY_LEVEL_BRACKETS = {
    "Common": (1, 20),
    "Uncommon": (10, 40),
    "Rare": (20, 60),
    "Epic": (40, 80),
    "Legendary": (60, 100),
}
ITEM_CATEGORIES = ["Weapon", "Armor", "Mount", "Consumable", "Cosmetic", "Material"]
ALERT_TYPES = ["rapid_gold_gain", "bulk_transfer", "suspicious_deposit", "anomalous_trade"]
ALERT_SEVERITIES = ["low", "medium", "high", "critical"]
TX_TYPES = ["trade_sale", "trade_purchase", "quest_reward", "gift_received",
            "gift_sent", "auction_sale"]
FLAG_TYPES = ["suspicious_trade", "bot_detection", "rmt_warning",
              "velocity_alert", "multi_account"]

ADJECTIVES = [
    "Ancient", "Blazing", "Cursed", "Divine", "Ethereal", "Frozen", "Golden",
    "Haunted", "Infernal", "Jade", "Mystic", "Obsidian", "Phantom", "Royal",
    "Shadow", "Thunder", "Void", "Wicked", "Crystal", "Demonic", "Feral",
    "Gilded", "Iron", "Lunar", "Nether", "Primal", "Runic", "Savage",
    "Twilight", "Venomous",
]
NOUNS = [
    "Sword", "Shield", "Helm", "Ring", "Amulet", "Staff", "Bow", "Cloak",
    "Boots", "Gauntlets", "Orb", "Tome", "Pendant", "Crown", "Dagger",
    "Plate", "Wand", "Scepter", "Chalice", "Mantle", "Greaves", "Halberd",
    "Crossbow", "Trinket",
]
SUFFIXES = [
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "Prime", "Alpha", "Omega", "Elite", "Proto", "MkII",
]


# ============================================================
#  Data generation helpers
# ============================================================

def generate_players(n):
    players = []
    for i in range(1, n + 1):
        is_new = random.random() < 0.15
        if is_new:
            reg_date = REFERENCE_DATE - timedelta(days=random.randint(5, 60))
            level = random.randint(1, 30)
            gold = round(random.uniform(50000, 500000), 2)
        else:
            reg_date = REFERENCE_DATE - timedelta(days=random.randint(90, 730))
            level = random.randint(10, 100)
            gold = round(random.uniform(1000, 200000), 2)
        players.append({
            "player_id": i,
            "username": fake.user_name() + str(random.randint(10, 99)),
            "registration_date": reg_date.strftime("%Y-%m-%d"),
            "account_level": level,
            "region": random.choice(REGIONS),
            "total_gold": gold,
            "account_status": random.choices(
                ["active", "suspended", "restricted"], weights=[0.85, 0.05, 0.10]
            )[0],
        })
    return players


def generate_items(n):
    items = []
    used_names: set = set()
    for i in range(1, n + 1):
        rarity = random.choices(RARITY_TIERS, weights=RARITY_WEIGHTS)[0]
        vmin, vmax = RARITY_BASE_RANGES[rarity]
        lmin, lmax = RARITY_LEVEL_BRACKETS[rarity]

        name = None
        for _ in range(200):
            base = f"{random.choice(ADJECTIVES)} {random.choice(NOUNS)}"
            if base not in used_names:
                name = base
                break
            candidate = f"{base} {random.choice(SUFFIXES)}"
            if candidate not in used_names:
                name = candidate
                break
        if name is None:
            name = f"{random.choice(ADJECTIVES)} {random.choice(NOUNS)} #{i}"
        used_names.add(name)

        items.append({
            "item_id": i,
            "item_name": name,
            "rarity_tier": rarity,
            "base_value": round(random.uniform(vmin, vmax), 2),
            "category": random.choice(ITEM_CATEGORIES),
            "level_requirement": random.randint(lmin, lmax),
        })
    return items


def generate_marketplace_listings(n, players, items):
    listings = []
    pids = [p["player_id"] for p in players]
    item_map = {it["item_id"]: it for it in items}
    iids = list(item_map.keys())

    for i in range(1, n + 1):
        seller = random.choice(pids)
        item_id = random.choice(iids)
        item = item_map[item_id]

        if random.random() < 0.20:
            price_mult = random.uniform(3.5, 8.0)
        else:
            price_mult = random.uniform(0.7, 1.8)

        price = round(item["base_value"] * price_mult, 2)
        listing_date = (REFERENCE_DATE - timedelta(days=random.randint(0, 30))).strftime("%Y-%m-%d")
        status = random.choices(["sold", "active", "cancelled"],
                                weights=[0.5, 0.35, 0.15])[0]
        buyer = None
        if status == "sold":
            candidates = [p for p in pids if p != seller]
            buyer = random.choice(candidates) if candidates else None

        listings.append({
            "listing_id": i,
            "seller_id": seller,
            "buyer_id": buyer,
            "item_id": item_id,
            "price": price,
            "listing_date": listing_date,
            "status": status,
        })
    return listings


def generate_wealth_alerts(n, players):
    alerts = []
    pids = [p["player_id"] for p in players]
    for i in range(1, n + 1):
        pid = random.choice(pids)
        alert_date = (REFERENCE_DATE - timedelta(days=random.randint(0, 14))).strftime("%Y-%m-%d")
        review_status = "pending" if random.random() < 0.20 else random.choice(["resolved", "dismissed"])
        severity = random.choices(ALERT_SEVERITIES, weights=[0.25, 0.30, 0.30, 0.15])[0]
        influx = round(random.uniform(10000, 300000), 2)
        alerts.append({
            "alert_id": i,
            "player_id": pid,
            "alert_date": alert_date,
            "alert_type": random.choice(ALERT_TYPES),
            "severity": severity,
            "influx_amount": influx,
            "review_status": review_status,
        })
    return alerts


def generate_transactions(n, players):
    txs = []
    pids = [p["player_id"] for p in players]
    for i in range(1, n + 1):
        pid = random.choice(pids)
        tx_type = random.choice(TX_TYPES)
        amount = round(random.uniform(100, 100000), 2)
        counterparty = None
        if tx_type in ("trade_sale", "trade_purchase", "gift_received", "gift_sent"):
            candidates = [p for p in pids if p != pid]
            counterparty = random.choice(candidates) if candidates else None
        ts = (REFERENCE_DATE - timedelta(
            days=random.randint(0, 30),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )).strftime("%Y-%m-%d %H:%M:%S")
        txs.append({
            "tx_id": i,
            "player_id": pid,
            "tx_type": tx_type,
            "amount": amount,
            "counterparty_id": counterparty,
            "timestamp": ts,
        })
    return txs


# ============================================================
#  Database
# ============================================================

def create_database(db_path):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""CREATE TABLE players (
        player_id INTEGER PRIMARY KEY,
        username TEXT NOT NULL,
        registration_date TEXT NOT NULL,
        account_level INTEGER NOT NULL,
        region TEXT NOT NULL,
        total_gold REAL NOT NULL,
        account_status TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE items (
        item_id INTEGER PRIMARY KEY,
        item_name TEXT NOT NULL,
        rarity_tier TEXT NOT NULL,
        base_value REAL NOT NULL,
        category TEXT NOT NULL,
        level_requirement INTEGER NOT NULL
    )""")
    c.execute("""CREATE TABLE marketplace_listings (
        listing_id INTEGER PRIMARY KEY,
        seller_id INTEGER NOT NULL,
        buyer_id INTEGER,
        item_id INTEGER NOT NULL,
        price REAL NOT NULL,
        listing_date TEXT NOT NULL,
        status TEXT NOT NULL,
        FOREIGN KEY (seller_id) REFERENCES players(player_id),
        FOREIGN KEY (buyer_id) REFERENCES players(player_id),
        FOREIGN KEY (item_id) REFERENCES items(item_id)
    )""")
    c.execute("""CREATE TABLE wealth_alerts (
        alert_id INTEGER PRIMARY KEY,
        player_id INTEGER NOT NULL,
        alert_date TEXT NOT NULL,
        alert_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        influx_amount REAL NOT NULL,
        review_status TEXT NOT NULL,
        FOREIGN KEY (player_id) REFERENCES players(player_id)
    )""")
    c.execute("""CREATE TABLE player_transactions (
        tx_id INTEGER PRIMARY KEY,
        player_id INTEGER NOT NULL,
        tx_type TEXT NOT NULL,
        amount REAL NOT NULL,
        counterparty_id INTEGER,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (player_id) REFERENCES players(player_id),
        FOREIGN KEY (counterparty_id) REFERENCES players(player_id)
    )""")
    conn.commit()
    return conn


def insert_data(conn, players, items, listings, alerts, transactions):
    c = conn.cursor()
    for p in players:
        c.execute("INSERT INTO players VALUES (?,?,?,?,?,?,?)",
                  (p["player_id"], p["username"], p["registration_date"],
                   p["account_level"], p["region"], p["total_gold"],
                   p["account_status"]))
    for it in items:
        c.execute("INSERT INTO items VALUES (?,?,?,?,?,?)",
                  (it["item_id"], it["item_name"], it["rarity_tier"],
                   it["base_value"], it["category"], it["level_requirement"]))
    for li in listings:
        c.execute("INSERT INTO marketplace_listings VALUES (?,?,?,?,?,?,?)",
                  (li["listing_id"], li["seller_id"], li["buyer_id"],
                   li["item_id"], li["price"], li["listing_date"], li["status"]))
    for a in alerts:
        c.execute("INSERT INTO wealth_alerts VALUES (?,?,?,?,?,?,?)",
                  (a["alert_id"], a["player_id"], a["alert_date"],
                   a["alert_type"], a["severity"], a["influx_amount"],
                   a["review_status"]))
    for t in transactions:
        c.execute("INSERT INTO player_transactions VALUES (?,?,?,?,?,?)",
                  (t["tx_id"], t["player_id"], t["tx_type"], t["amount"],
                   t["counterparty_id"], t["timestamp"]))
    conn.commit()


# ============================================================
#  Workspace
# ============================================================

def create_workspace(workspace, players, items, listings, alerts, transactions):
    os.makedirs(workspace, exist_ok=True)

    n_files = SCALE["num_workspace_files"]
    n_sessions = max(1, round(n_files * 0.4))
    n_flags = max(1, round(n_files * 0.3))
    n_prices = max(1, n_files - n_sessions - n_flags)

    # ---- fixed config files (not counted in SCALE) ----

    fraud_rules = {
        "analysis_date": REFERENCE_DATE.strftime("%Y-%m-%d"),
        "scoring_weights": {
            "new_account_bonus": 15,
            "high_frequency_trading": 10,
            "price_anomaly_per_listing": 8,
            "level_mismatch_per_listing": 12,
            "multi_ip_sessions": 10,
            "wealth_influx_severity": 5,
            "prior_flag_per_incident": 7,
        },
        "thresholds": {
            "new_account_threshold_days": 90,
            "trade_frequency_threshold": 5,
            "trade_frequency_period_days": 30,
            "price_anomaly_multiplier": 3.0,
            "multi_ip_threshold": 3,
            "wealth_influx_base": 50000,
            "suspicious_score_threshold": 40,
        },
        "alert_base_scores": {
            "critical": 25,
            "high": 15,
            "medium": 10,
            "low": 5,
        },
        "recommendation_tiers": {
            "block_multiplier": 2.0,
            "restrict_multiplier": 1.5,
        },
    }
    with open(os.path.join(workspace, "fraud_rules.yaml"), "w") as f:
        yaml.dump(fraud_rules, f, default_flow_style=False, sort_keys=False)

    rarity_config = {}
    for tier in RARITY_TIERS:
        rarity_config[tier] = {
            "min_value": RARITY_BASE_RANGES[tier][0],
            "max_value": RARITY_BASE_RANGES[tier][1],
            "level_bracket": list(RARITY_LEVEL_BRACKETS[tier]),
        }
    with open(os.path.join(workspace, "rarity_config.json"), "w") as f:
        json.dump(rarity_config, f, indent=2)

    region_risks = [
        {"region": "NA", "risk_multiplier": "1.0"},
        {"region": "EU", "risk_multiplier": "1.0"},
        {"region": "APAC", "risk_multiplier": "1.2"},
        {"region": "SA", "risk_multiplier": "1.1"},
        {"region": "Other", "risk_multiplier": "1.3"},
    ]
    with open(os.path.join(workspace, "region_risk.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["region", "risk_multiplier"])
        w.writeheader()
        w.writerows(region_risks)

    # fraud_scoring_methodology.md — authoritative definition of the scoring
    # procedure (fixed policy document, not counted in SCALE)
    methodology_md = """# Fraud Scoring Methodology

## Scope

The review covers every player who has at least one wealth alert whose review
status is pending. Alerts in any other review status are ignored. All
date-based computations use the analysis date given in the fraud rules
configuration as the reference point.

## Base score and alert type

Each reviewed player's score starts from a base determined by the
highest-severity pending alert for that player (severity ranks, highest
first: critical, high, medium, low). The base score for each severity level
is listed under the alert base scores in the fraud rules configuration. The
alert type attributed to the player is the alert type of that same
highest-severity pending alert.

## Scoring factors

Account age: if the number of days between the player's registration date and
the analysis date is less than the new-account threshold in the
configuration, add the new-account bonus weight.

Trade frequency: count the marketplace listings where the player is the
seller and the listing date falls within the trade-frequency period — that
is, the listing date is on or after the analysis date minus the
trade-frequency period length in days. If that count exceeds (is strictly
greater than) the trade-frequency threshold, add the high-frequency-trading
weight.

Price anomaly: for each of the player's seller listings within the
trade-frequency period, determine the market reference price for the listed
item as the average of the three most recent price snapshot observations
recorded in the price history data files (most recent by snapshot date); if
fewer than three snapshots exist use however many are available, and if none
exist fall back to the item's base value from the item catalog. If the
listing price is strictly greater than the price-anomaly multiplier times the
market reference price, add the price-anomaly-per-listing weight for that
listing.

Level mismatch: for each of those same listings, if the item's level
requirement is strictly greater than the player's account level, add the
level-mismatch-per-listing weight for that listing.

Multiple IP addresses: count the distinct IP addresses the player has used
across all session log files. If that count exceeds (is strictly greater
than) the multi-IP threshold, add the multi-IP-sessions weight.

Wealth influx: sum the influx amounts across all of the player's pending
alerts. If the total is strictly greater than the wealth-influx base, add the
integer part of the quotient of (total minus base) divided by the base,
multiplied by the wealth-influx-severity weight.

Prior flags: count the player's entries in the historical account-flag files
and add the prior-flag-per-incident weight once for each flag found.

## Final score, suspicion, and recommendation

Sum the base score and all factor contributions, then multiply the total by
the region risk multiplier corresponding to the player's region (players in a
region not listed in the region risk table use a multiplier of 1.0). Round
the resulting fraud score to one decimal place. A player is considered
suspicious only when this final score is greater than or equal to the
suspicious-score threshold in the configuration.

For each suspicious player, assign a recommendation: "block" if the final
score is at or above the threshold multiplied by the block multiplier;
otherwise "restrict" if at or above the threshold multiplied by the restrict
multiplier; otherwise "investigate".

## Primary evidence

The primary evidence for a suspicious player is the scoring factor (excluding
the alert base score) that contributed the most points before the region
multiplier was applied. If two factors tie, choose the one whose identifier
comes first alphabetically. If no factor other than the base contributed any
points, the primary evidence is the base score itself. The canonical factor
identifiers, exactly as they must appear in the report, are:

- new_account_bonus (account age)
- high_frequency_trading (trade frequency)
- price_anomaly (price anomaly, per-listing contributions summed)
- level_mismatch (level mismatch, per-listing contributions summed)
- multi_ip_sessions (multiple IP addresses)
- wealth_influx_severity (wealth influx)
- prior_flags (prior flags)
- alert_base (the base score, used only when everything else is zero)
"""
    with open(os.path.join(workspace, "fraud_scoring_methodology.md"), "w") as f:
        f.write(methodology_md)

    # ---- scalable data files ----

    # 1) Player session logs (CSV)
    all_sessions = []
    session_id = 1
    for p in players:
        n_sess = random.randint(3, 15)
        if random.random() < 0.15:
            n_ips = random.randint(4, 8)
        else:
            n_ips = random.randint(1, 3)
        ips = [fake.ipv4() for _ in range(n_ips)]
        devices = random.choices(["PC", "Mobile", "Console", "Tablet"], k=n_sess)
        for j in range(n_sess):
            login = REFERENCE_DATE - timedelta(
                days=random.randint(0, 30), hours=random.randint(0, 23))
            dur = random.randint(5, 480)
            logout = login + timedelta(minutes=dur)
            all_sessions.append({
                "session_id": session_id,
                "player_id": p["player_id"],
                "login_time": login.strftime("%Y-%m-%d %H:%M:%S"),
                "logout_time": logout.strftime("%Y-%m-%d %H:%M:%S"),
                "ip_address": random.choice(ips),
                "device_type": devices[j],
            })
            session_id += 1
    random.shuffle(all_sessions)
    _write_csv_chunks(workspace, "player_sessions", all_sessions,
                      ["session_id", "player_id", "login_time", "logout_time",
                       "ip_address", "device_type"],
                      n_sessions)

    # 2) Account flags (JSON)
    all_flags = []
    flag_id = 1
    for p in players:
        if random.random() < 0.20:
            nf = random.randint(1, 4)
            for _ in range(nf):
                all_flags.append({
                    "flag_id": flag_id,
                    "player_id": p["player_id"],
                    "flag_type": random.choice(FLAG_TYPES),
                    "flag_date": (REFERENCE_DATE - timedelta(
                        days=random.randint(30, 365))).strftime("%Y-%m-%d"),
                    "details": fake.sentence(nb_words=8),
                })
                flag_id += 1
    random.shuffle(all_flags)
    _write_json_chunks(workspace, "account_flags", all_flags, n_flags)

    # 3) Item price snapshots (CSV)
    all_snapshots = []
    for item in items:
        ns = random.randint(3, 10)
        for k in range(ns):
            snap_date = (REFERENCE_DATE - timedelta(days=k * 3)).strftime("%Y-%m-%d")
            observed = round(item["base_value"] * random.uniform(0.8, 1.4), 2)
            all_snapshots.append({
                "item_id": item["item_id"],
                "snapshot_date": snap_date,
                "observed_price": observed,
                "source": random.choice(["auction_house", "player_market", "npc_vendor"]),
            })
    random.shuffle(all_snapshots)
    _write_csv_chunks(workspace, "item_price_snapshots", all_snapshots,
                      ["item_id", "snapshot_date", "observed_price", "source"],
                      n_prices)


def _write_csv_chunks(workspace, prefix, rows, fieldnames, n_chunks):
    chunk_size = max(1, math.ceil(len(rows) / n_chunks))
    for idx in range(n_chunks):
        chunk = rows[idx * chunk_size:(idx + 1) * chunk_size]
        fname = f"{prefix}_{idx + 1:03d}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(chunk)


def _write_json_chunks(workspace, prefix, rows, n_chunks):
    chunk_size = max(1, math.ceil(len(rows) / n_chunks))
    for idx in range(n_chunks):
        chunk = rows[idx * chunk_size:(idx + 1) * chunk_size]
        fname = f"{prefix}_{idx + 1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(chunk, f, indent=2)


# ============================================================
#  Main
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    conn = create_database(args.db_path)

    players = generate_players(SCALE["rows_per_table"])
    items = generate_items(SCALE["rows_per_table"])
    listings = generate_marketplace_listings(SCALE["rows_per_table"], players, items)
    alerts = generate_wealth_alerts(SCALE["rows_per_table"], players)
    transactions = generate_transactions(SCALE["rows_per_table"], players)

    insert_data(conn, players, items, listings, alerts, transactions)
    conn.close()

    create_workspace(args.workspace, players, items, listings, alerts, transactions)
    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")


if __name__ == "__main__":
    main()
