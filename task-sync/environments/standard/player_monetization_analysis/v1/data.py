import argparse
import sqlite3
import os
import json
import csv
import random
import math

import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 160,       # v1 = 2x base
    "num_workspace_files": 16,   # v1 = base + N = 8 + 8
}


def main(db_path: str, workspace: str):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    num_players = SCALE["rows_per_table"]
    num_ws_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ------------------------------------------------------------------ tables
    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            player_id   TEXT PRIMARY KEY,
            username    TEXT,
            tier        TEXT,
            registration_date TEXT,
            total_playtime_hours REAL,
            last_login_date TEXT,
            account_status TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id    TEXT PRIMARY KEY,
            event_name  TEXT,
            event_type  TEXT,
            start_date  TEXT,
            end_date    TEXT,
            bonus_multiplier REAL,
            min_tier_required TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchase_receipts (
            receipt_id  TEXT PRIMARY KEY,
            player_id   TEXT,
            item_name   TEXT,
            item_category TEXT,
            amount_usd  REAL,
            purchase_date TEXT,
            payment_method TEXT,
            event_id    TEXT,
            FOREIGN KEY (player_id) REFERENCES players(player_id),
            FOREIGN KEY (event_id) REFERENCES events(event_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS currency_transactions (
            txn_id      TEXT PRIMARY KEY,
            player_id   TEXT,
            currency_type TEXT,
            amount      REAL,
            txn_type    TEXT,
            source      TEXT,
            timestamp   TEXT,
            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS event_participation (
            participation_id TEXT PRIMARY KEY,
            player_id   TEXT,
            event_id    TEXT,
            joined_date TEXT,
            total_event_spend_usd REAL,
            currency_spent INTEGER,
            FOREIGN KEY (player_id) REFERENCES players(player_id),
            FOREIGN KEY (event_id) REFERENCES events(event_id)
        )
    """)

    # ----------------------------------------------------------- populate data

    tiers = ["Bronze", "Silver", "Gold", "Platinum", "Diamond"]
    tier_weights = [0.30, 0.25, 0.20, 0.15, 0.10]

    tier_playtime_mean = {
        "Bronze": 60, "Silver": 130, "Gold": 220,
        "Platinum": 370, "Diamond": 520,
    }

    players_rows = []
    for i in range(num_players):
        pid = f"P{i + 1:04d}"
        uname = fake.user_name() + str(random.randint(10, 99))
        tier = np.random.choice(tiers, p=tier_weights)
        reg = fake.date_between_dates(
            date_start=pd.Timestamp("2022-06-01"),
            date_end=pd.Timestamp("2025-06-01"),
        )
        pt = max(5.0, round(random.gauss(tier_playtime_mean[tier], 50), 1))
        ll = fake.date_between_dates(
            date_start=pd.Timestamp("2025-10-01"),
            date_end=pd.Timestamp("2025-12-31"),
        )
        status = np.random.choice(["active", "inactive"], p=[0.85, 0.15])
        players_rows.append((pid, uname, tier, str(reg), pt, str(ll), status))

    cur.executemany("INSERT INTO players VALUES (?,?,?,?,?,?,?)", players_rows)

    # events (fixed 12)
    event_names = [
        "Winter Wonderland", "Spring Bloom Festival", "Summer Showdown",
        "Autumn Harvest", "Black Friday Bonanza", "New Year Bash",
        "Valentine Special", "Easter Egg Hunt", "Mid-Year Madness",
        "Halloween Haunt", "Thanksgiving Feast", "Anniversary Celebration",
    ]
    event_types = ["seasonal", "flash_sale", "tournament", "holiday"]
    min_tier_cycle = ["Bronze", "Silver", "Gold", "Bronze", "Bronze", "Silver"]

    events_rows = []
    for i in range(12):
        eid = f"E{i + 1:03d}"
        etype = event_types[i % len(event_types)]
        sd = f"2025-{i + 1:02d}-01"
        ed = f"2025-{i + 1:02d}-{random.choice([14, 21, 28])}"
        bm = round(random.uniform(1.2, 3.0), 1)
        mt = min_tier_cycle[i % len(min_tier_cycle)]
        events_rows.append((eid, event_names[i], etype, sd, ed, bm, mt))

    cur.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?)", events_rows)

    # purchase receipts
    item_cats = ["cosmetic", "weapon", "booster", "currency_pack",
                 "season_pass", "loot_box"]
    items_by_cat = {
        "cosmetic": ["Dragon Skin", "Golden Armor", "Neon Wings",
                     "Shadow Cape", "Crystal Crown"],
        "weapon": ["Flame Sword", "Ice Bow", "Thunder Staff",
                   "Void Dagger", "Storm Axe"],
        "booster": ["XP Boost 2x", "Gold Boost 3x", "Luck Charm",
                    "Speed Potion", "Shield Aura"],
        "currency_pack": ["100 Gems", "500 Gems", "1000 Gems",
                          "50 Tokens", "200 Tokens"],
        "season_pass": ["Season Pass Basic", "Season Pass Premium",
                        "Season Pass Ultimate"],
        "loot_box": ["Mystery Box", "Legendary Crate", "Epic Bundle",
                     "Rare Chest"],
    }
    pay_methods = ["credit_card", "paypal", "google_pay", "apple_pay",
                   "gift_card"]
    tier_avg_spend = {
        "Bronze": 8, "Silver": 20, "Gold": 50,
        "Platinum": 100, "Diamond": 180,
    }

    receipts = []
    rid_counter = 0
    event_ids = [e[0] for e in events_rows]
    for p in players_rows:
        pid, _, tier, _, _, _, status = p
        if status == "inactive" and random.random() < 0.5:
            continue
        avg = tier_avg_spend[tier]
        factor = random.choice([0.15, 0.25, 0.35, 0.45, 0.65,
                                1.0, 1.0, 1.2, 1.5, 2.0])
        actual_avg = avg * factor
        n_purch = max(0, int(random.gauss(actual_avg / 4, 3)))
        n_purch = min(n_purch, 25)
        for _ in range(n_purch):
            rid_counter += 1
            cat = random.choice(item_cats)
            item = random.choice(items_by_cat[cat])
            amt = max(0.99, round(
                random.uniform(0.99, max(1.0, actual_avg * 0.7)), 2))
            pdate = fake.date_between_dates(
                date_start=pd.Timestamp("2025-04-01"),
                date_end=pd.Timestamp("2025-12-31"),
            )
            pm = random.choice(pay_methods)
            evid = random.choice(event_ids) if random.random() < 0.3 else None
            receipts.append((f"R{rid_counter:06d}", pid, item, cat, amt,
                             str(pdate), pm, evid))

    cur.executemany(
        "INSERT INTO purchase_receipts VALUES (?,?,?,?,?,?,?,?)", receipts
    )

    # currency transactions
    curr_types = ["gold", "gems", "tokens"]
    earn_src = ["quest_completion", "daily_login", "pvp_reward",
                "event_reward", "achievement"]
    spend_src = ["item_purchase", "upgrade", "gacha", "trade", "craft"]

    txns = []
    tid_counter = 0
    for p in players_rows:
        pid = p[0]
        n_txn = random.randint(3, 15)
        for _ in range(n_txn):
            tid_counter += 1
            ct = random.choice(curr_types)
            tt = random.choice(["earn", "spend"])
            amt = (random.randint(10, 500) if tt == "earn"
                   else random.randint(5, 300))
            src = random.choice(earn_src if tt == "earn" else spend_src)
            ts = str(fake.date_time_between_dates(
                datetime_start=pd.Timestamp("2025-04-01"),
                datetime_end=pd.Timestamp("2025-12-31 23:59:59"),
            ))
            txns.append((f"T{tid_counter:06d}", pid, ct, amt, tt, src, ts))

    cur.executemany(
        "INSERT INTO currency_transactions VALUES (?,?,?,?,?,?,?)", txns
    )

    # event participation
    tier_rank = {"Bronze": 0, "Silver": 1, "Gold": 2,
                 "Platinum": 3, "Diamond": 4}
    parts = []
    ep_counter = 0
    for p in players_rows:
        pid, _, tier, _, _, _, status = p
        if status == "inactive" and random.random() < 0.7:
            continue
        n_ev = random.randint(1, 8)
        chosen = random.sample(event_ids, min(n_ev, 12))
        for eid in chosen:
            ev = next(e for e in events_rows if e[0] == eid)
            if tier_rank[tier] < tier_rank[ev[6]]:
                continue
            ep_counter += 1
            jd = fake.date_between_dates(
                date_start=pd.Timestamp(ev[3]),
                date_end=pd.Timestamp(ev[4]),
            )
            es = round(random.uniform(0, 30), 2)
            cs = random.randint(0, 200)
            parts.append((f"EP{ep_counter:05d}", pid, eid, str(jd), es, cs))

    cur.executemany(
        "INSERT INTO event_participation VALUES (?,?,?,?,?,?)", parts
    )

    conn.commit()

    # ======================================================= workspace files

    # ---- fixed config files (not counted in SCALE) ----

    # 1. tier_config.yaml
    tier_config = {
        "tiers": {
            "Bronze":   {"expected_monthly_spending_usd": 5.0,
                         "engagement_weight": 1.0},
            "Silver":   {"expected_monthly_spending_usd": 15.0,
                         "engagement_weight": 1.2},
            "Gold":     {"expected_monthly_spending_usd": 40.0,
                         "engagement_weight": 1.5},
            "Platinum": {"expected_monthly_spending_usd": 80.0,
                         "engagement_weight": 1.8},
            "Diamond":  {"expected_monthly_spending_usd": 150.0,
                         "engagement_weight": 2.0},
        },
        "analysis_period_months": 6,
    }
    with open(os.path.join(workspace, "tier_config.yaml"), "w") as f:
        yaml.dump(tier_config, f, default_flow_style=False, sort_keys=False)

    # 2. segment_criteria.json
    seg = {
        "under_monetized_definition": {
            "spending_ratio_threshold": 0.6,
            "min_engagement_score": 40.0,
            "min_willingness_rating": 3,
            "required_account_status": "active",
        },
        "engagement_score_formula": {
            "description": (
                "engagement_score = min(100, "
                "(playtime_hours / playtime_cap * playtime_weight "
                "+ event_count / event_cap * event_weight "
                "+ currency_earned / currency_cap * currency_weight) * 100)"
            ),
            "playtime_weight": 0.40,
            "event_weight": 0.35,
            "currency_weight": 0.25,
            "playtime_cap": 500,
            "event_cap": 10,
            "currency_cap": 2000,
        },
        "priority_score_formula":
            "gap_ratio * engagement_score * willingness / 100",
    }
    with open(os.path.join(workspace, "segment_criteria.json"), "w") as f:
        json.dump(seg, f, indent=2)

    # 3. promotion_catalog.csv
    promos = [
        ["PROMO01", "Welcome Back Bundle", "discount",
         "Bronze,Silver", "all", 30, 0.3],
        ["PROMO02", "Whale Starter Pack", "bundle",
         "Gold,Platinum,Diamond", "all", 25, 0.4],
        ["PROMO03", "PvP Champion Offer", "targeted",
         "all", "pvp", 20, 0.2],
        ["PROMO04", "Explorer's Treasure", "targeted",
         "all", "pve", 20, 0.2],
        ["PROMO05", "Season Pass Discount", "season_pass",
         "Silver,Gold", "all", 40, 0.5],
        ["PROMO06", "Gem Rush Deal", "currency",
         "all", "all", 50, 0.3],
        ["PROMO07", "Social Butterfly Bonus", "targeted",
         "all", "social", 15, 0.2],
        ["PROMO08", "Elite Upgrade", "upgrade",
         "Platinum,Diamond", "all", 20, 0.6],
    ]
    with open(os.path.join(workspace, "promotion_catalog.csv"),
              "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["promo_id", "promo_name", "promo_type",
                     "target_tiers", "target_game_mode",
                     "discount_pct", "min_gap_ratio"])
        w.writerows(promos)

    # 4. campaign_rules.md
    rules_text = (
        "## Eligibility\n\n"
        "Only players classified as under-monetized according to the segment "
        "criteria are eligible for campaign inclusion.\n\n"
        "## Promotion Matching\n\n"
        "For each eligible player, assign the single promotion whose "
        "discount_pct is highest among all promotions satisfying every "
        "condition below:\n\n"
        "  - The player's tier appears in the promotion's target_tiers "
        "list, or target_tiers equals \"all\".\n"
        "  - The player's preferred_game_mode matches the promotion's "
        "target_game_mode, or target_game_mode equals \"all\".\n"
        "  - The player's gap_ratio is greater than or equal to the "
        "promotion's min_gap_ratio.\n\n"
        "When multiple promotions tie on discount_pct, choose the one "
        "whose promo_id comes first in ascending alphabetical order.\n\n"
        "If no promotion matches at all, assign promo_id \"PROMO06\" "
        "(Gem Rush Deal) as fallback.\n\n"
        "## Priority Score\n\n"
        "priority_score = gap_ratio * engagement_score * willingness / 100\n\n"
        "Round priority_score to two decimal places.\n\n"
        "## Sort Order\n\n"
        "The campaign list must be sorted by priority_score descending. "
        "Ties are broken by player_id ascending.\n"
    )
    with open(os.path.join(workspace, "campaign_rules.md"), "w") as f:
        f.write(rules_text)

    # ---- scalable data files ----

    game_modes = ["pvp", "pve", "social", "exploration", "competitive"]
    devices = ["mobile", "pc", "console"]
    regions = ["NA", "EU", "APAC", "LATAM", "MEA"]

    surveys = []
    for p in players_rows:
        pid = p[0]
        surveys.append({
            "player_id": pid,
            "preferred_game_mode": random.choice(game_modes),
            "spending_willingness": random.randint(1, 5),
            "device_type": random.choice(devices),
            "region": random.choice(regions),
            "feedback_score": random.randint(1, 10),
        })

    n_survey_files = num_ws_files // 2
    n_elog_files = num_ws_files - n_survey_files

    # survey batches (.json)
    batch_sz = math.ceil(len(surveys) / n_survey_files)
    for i in range(n_survey_files):
        batch = surveys[i * batch_sz: (i + 1) * batch_sz]
        path = os.path.join(workspace, f"player_survey_batch_{i + 1}.json")
        with open(path, "w") as f:
            json.dump(batch, f, indent=2)

    # event participation log files (.csv) — extra columns not in DB
    elog_rows = []
    for pt in parts:
        _, pid, eid, _, _, _ = pt
        elog_rows.append({
            "player_id": pid,
            "event_id": eid,
            "reward_tier_achieved": random.choice(
                ["none", "bronze_reward", "silver_reward", "gold_reward"]),
            "satisfaction_rating": random.randint(1, 5),
            "referrals_made": random.randint(0, 3),
        })

    elog_batch = max(1, math.ceil(len(elog_rows) / n_elog_files))
    for i in range(n_elog_files):
        batch = elog_rows[i * elog_batch: (i + 1) * elog_batch]
        fp = os.path.join(workspace, f"event_participation_log_{i + 1}.csv")
        with open(fp, "w", newline="") as f:
            if batch:
                w = csv.DictWriter(f, fieldnames=list(batch[0].keys()))
                w.writeheader()
                w.writerows(batch)

    conn.close()
    print(f"Done. DB: {db_path}  workspace: {workspace}  "
          f"players={num_players}  receipts={len(receipts)}  "
          f"txns={len(txns)}  participations={len(parts)}  "
          f"ws_files={n_survey_files + n_elog_files} scalable + 4 fixed")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db_path", required=True)
    ap.add_argument("--workspace", required=True)
    args = ap.parse_args()
    main(args.db_path, args.workspace)
