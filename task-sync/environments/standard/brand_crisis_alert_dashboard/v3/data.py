import sqlite3
import os
import json
import csv
import argparse
import random
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 800,
    "num_workspace_files": 40,
}


def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    fake = Faker()

    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    rows = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    industries = [
        "Technology", "Food & Beverage", "Automotive", "Fashion", "Healthcare",
        "Finance", "Entertainment", "Retail", "Travel", "Telecom",
    ]
    regions = ["North America", "Europe", "Asia Pacific", "Latin America", "Middle East"]
    platforms = ["twitter", "instagram", "facebook", "tiktok"]

    # ---- brands table ----
    brands = []
    for i in range(1, rows + 1):
        brand_name = fake.company()
        industry = industries[i % len(industries)]
        region = regions[i % len(regions)]
        brands.append((i, brand_name, industry, region))

    cursor.execute("DROP TABLE IF EXISTS brands")
    cursor.execute("""
        CREATE TABLE brands (
            brand_id INTEGER PRIMARY KEY,
            brand_name TEXT,
            industry TEXT,
            region TEXT
        )
    """)
    cursor.executemany("INSERT INTO brands VALUES (?, ?, ?, ?)", brands)

    # Crisis level per brand: 0=normal, 1=spike only, 2=spike+sentiment, 3=full crisis
    crisis_levels = np.random.choice([0, 1, 2, 3], size=rows, p=[0.63, 0.12, 0.12, 0.13])

    # Baseline daily volume per brand (across all platforms)
    baseline_volumes = {}
    for i in range(1, rows + 1):
        baseline_volumes[i] = int(np.random.uniform(20, 100))

    # ---- monitoring data (workspace) ----
    dates = pd.date_range(end="2026-04-19", periods=7).strftime("%Y-%m-%d").tolist()
    platform_shares = {"twitter": 0.35, "instagram": 0.25, "facebook": 0.20, "tiktok": 0.20}

    monitoring_data = []
    for i in range(1, rows + 1):
        base_vol = baseline_volumes[i]
        cl = crisis_levels[i - 1]
        for date in dates:
            for plat in platforms:
                daily_base = max(1, int(base_vol * platform_shares[plat]))
                if cl >= 1:
                    mult = float(np.random.uniform(1.8, 3.5))
                    count = max(1, int(daily_base * mult + np.random.normal(0, 2)))
                else:
                    count = max(1, int(daily_base + np.random.normal(0, daily_base * 0.15)))
                monitoring_data.append((i, date, plat, count))

    # ---- influencers table ----
    niches = ["beauty", "tech", "food", "fitness", "travel",
              "gaming", "fashion", "finance", "health", "comedy"]
    influencers = []
    for i in range(1, rows + 1):
        handle = f"@{fake.user_name()}"
        platform = platforms[i % len(platforms)]
        follower_count = int(np.random.lognormal(10, 1.5))
        is_verified = int(np.random.random() < 0.35)
        niche = niches[i % len(niches)]
        influencers.append((i, handle, platform, follower_count, is_verified, niche))

    cursor.execute("DROP TABLE IF EXISTS influencers")
    cursor.execute("""
        CREATE TABLE influencers (
            influencer_id INTEGER PRIMARY KEY,
            handle TEXT,
            platform TEXT,
            follower_count INTEGER,
            is_verified INTEGER,
            niche TEXT
        )
    """)
    cursor.executemany("INSERT INTO influencers VALUES (?, ?, ?, ?, ?, ?)", influencers)

    # ---- product name pool ----
    product_prefixes = [
        "Nova", "Apex", "Pulse", "Core", "Flex",
        "Zeno", "Vibe", "Echo", "Peak", "Drift",
        "Spark", "Volt", "Aura", "Blaze", "Crest",
    ]
    product_suffixes = [
        "Pro", "Plus", "Lite", "Max", "360",
        "One", "X", "Go", "Air", "Hub",
        "Edge", "Neo", "Wave", "Link", "Sync",
    ]
    product_names_pool = [f"{p} {s}" for p, s in zip(product_prefixes, product_suffixes)]

    brand_products = {}
    for i in range(1, rows + 1):
        n_prods = 3 + (i % 3)
        start = (i * 3) % len(product_names_pool)
        prods = [product_names_pool[(start + j) % len(product_names_pool)] for j in range(n_prods)]
        brand_products[i] = prods

    # ---- posts table ----
    num_posts = rows * 3
    posts = []
    post_id = 1

    def _make_post(pid, bid):
        nonlocal post_id
        cl = crisis_levels[bid - 1]
        is_by_inf = int(np.random.random() < 0.15)
        author_id = int(np.random.randint(1, rows + 1)) if is_by_inf else None
        if cl >= 3 and np.random.random() < 0.35:
            is_by_inf = 1
            author_id = int(np.random.randint(1, rows + 1))
        plat = platforms[int(np.random.randint(0, 4))]
        pdate = dates[int(np.random.randint(0, 7))]
        snippet = fake.sentence(nb_words=12)
        eng = int(np.random.lognormal(5, 2))
        return (pid, bid, author_id, plat, pdate, snippet, eng, is_by_inf)

    # Phase 1: 2 guaranteed posts per brand
    for bid in range(1, rows + 1):
        for _ in range(2):
            posts.append(_make_post(post_id, bid))
            post_id += 1

    # Phase 2: remaining posts
    for _ in range(num_posts - 2 * rows):
        bid = int(np.random.randint(1, rows + 1))
        posts.append(_make_post(post_id, bid))
        post_id += 1

    actual_num_posts = len(posts)

    cursor.execute("DROP TABLE IF EXISTS posts")
    cursor.execute("""
        CREATE TABLE posts (
            post_id INTEGER PRIMARY KEY,
            brand_id INTEGER,
            author_id INTEGER,
            platform TEXT,
            post_date TEXT,
            content_snippet TEXT,
            engagement_count INTEGER,
            is_by_influencer INTEGER,
            FOREIGN KEY (brand_id) REFERENCES brands(brand_id),
            FOREIGN KEY (author_id) REFERENCES influencers(influencer_id)
        )
    """)
    cursor.executemany("INSERT INTO posts VALUES (?, ?, ?, ?, ?, ?, ?, ?)", posts)

    # Build lookup: post_id -> brand_id
    post_brand = {p[0]: p[1] for p in posts}
    # brand_id -> list of post_ids
    brand_post_ids = {}
    for p in posts:
        brand_post_ids.setdefault(p[1], []).append(p[0])

    # ---- comments table ----
    num_comments = rows * 5
    comments = []
    comment_id = 1

    def _make_comment(cid, pid):
        bid = post_brand[pid]
        cl = crisis_levels[bid - 1]
        if cl >= 2:
            score = round(float(np.random.uniform(-0.9, 0.1)), 4)
        else:
            score = round(float(np.random.uniform(-0.4, 0.85)), 4)
        if score < -0.2:
            label = "negative"
        elif score > 0.2:
            label = "positive"
        else:
            label = "neutral"
        text = fake.sentence(nb_words=10)
        cdate = dates[int(np.random.randint(0, 7))]
        return (cid, pid, score, label, text, cdate)

    # Phase 1: 1 comment per post
    for pid in range(1, actual_num_posts + 1):
        comments.append(_make_comment(comment_id, pid))
        comment_id += 1

    # Phase 2: remaining
    for _ in range(num_comments - actual_num_posts):
        pid = int(np.random.randint(1, actual_num_posts + 1))
        comments.append(_make_comment(comment_id, pid))
        comment_id += 1

    cursor.execute("DROP TABLE IF EXISTS comments")
    cursor.execute("""
        CREATE TABLE comments (
            comment_id INTEGER PRIMARY KEY,
            post_id INTEGER,
            sentiment_score REAL,
            sentiment_label TEXT,
            comment_text TEXT,
            comment_date TEXT,
            FOREIGN KEY (post_id) REFERENCES posts(post_id)
        )
    """)
    cursor.executemany("INSERT INTO comments VALUES (?, ?, ?, ?, ?, ?)", comments)

    # ---- product_mentions table ----
    severity_tags = ["low", "medium", "high", "critical"]
    mention_types = ["complaint", "praise", "neutral", "question"]
    num_mentions = rows * 2
    product_mentions = []
    mention_id = 1

    def _make_mention(mid, pid, bid):
        cl = crisis_levels[bid - 1]
        product_name = str(np.random.choice(brand_products[bid]))
        if cl >= 3:
            mtype = str(np.random.choice(mention_types, p=[0.55, 0.10, 0.20, 0.15]))
            stag = str(np.random.choice(severity_tags, p=[0.10, 0.15, 0.35, 0.40]))
        else:
            mtype = str(np.random.choice(mention_types, p=[0.20, 0.30, 0.30, 0.20]))
            stag = str(np.random.choice(severity_tags, p=[0.40, 0.30, 0.20, 0.10]))
        return (mid, pid, bid, product_name, mtype, stag)

    # Phase 1: 1 mention per brand (using first post of each brand)
    for bid in range(1, rows + 1):
        pid = brand_post_ids[bid][0]
        product_mentions.append(_make_mention(mention_id, pid, bid))
        mention_id += 1

    # Phase 2: remaining mentions
    for _ in range(num_mentions - rows):
        pid = int(np.random.randint(1, actual_num_posts + 1))
        bid = post_brand[pid]
        product_mentions.append(_make_mention(mention_id, pid, bid))
        mention_id += 1

    cursor.execute("DROP TABLE IF EXISTS product_mentions")
    cursor.execute("""
        CREATE TABLE product_mentions (
            mention_id INTEGER PRIMARY KEY,
            post_id INTEGER,
            brand_id INTEGER,
            product_name TEXT,
            mention_type TEXT,
            severity_tag TEXT,
            FOREIGN KEY (post_id) REFERENCES posts(post_id),
            FOREIGN KEY (brand_id) REFERENCES brands(brand_id)
        )
    """)
    cursor.executemany("INSERT INTO product_mentions VALUES (?, ?, ?, ?, ?, ?)", product_mentions)

    conn.commit()

    # ================================================================
    # WORKSPACE FILES
    # ================================================================

    # --- Fixed config files ---

    # 1. crisis_config.yaml
    import yaml
    config = {
        "volume_spike_multiplier": 1.5,
        "sentiment_threshold": -0.15,
        "min_critical_mentions": 2,
        "alert_levels": {
            "CRITICAL": 75,
            "HIGH": 50,
            "MEDIUM": 25,
        },
    }
    with open(os.path.join(workspace, "crisis_config.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # 2. scoring_weights.json
    weights = {
        "volume_spike_weight": 30,
        "sentiment_weight": 25,
        "influencer_weight": 25,
        "product_mention_weight": 20,
    }
    with open(os.path.join(workspace, "scoring_weights.json"), "w") as f:
        json.dump(weights, f, indent=2)

    # 3. brand_tiers.csv
    tiers = []
    for i in range(1, rows + 1):
        tier_val = int(np.random.choice([1, 2, 3], p=[0.15, 0.35, 0.50]))
        tier_name = f"Tier{tier_val}"
        multiplier = {1: 2.0, 2: 1.5, 3: 1.0}[tier_val]
        tiers.append((i, tier_name, multiplier))

    with open(os.path.join(workspace, "brand_tiers.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["brand_id", "tier_name", "priority_multiplier"])
        writer.writerows(tiers)

    # 4. scoring_formula.txt
    formula_text = """Crisis Score Calculation Formula
================================

For each brand that meets ALL qualification criteria, compute the following four
components and sum them to obtain the crisis score.

1. Volume Component = min(spike_ratio, 5.0) * (volume_spike_weight / 5.0)
   where spike_ratio = recent_avg_daily_volume / baseline_avg_daily_volume
   and recent_avg_daily_volume = (total post count across all platforms and all
   dates in the monitoring reports for the brand) / (number of distinct dates)

2. Sentiment Component = min(abs(avg_sentiment_score), 1.0) * sentiment_weight
   where avg_sentiment_score is the mean sentiment across all comments on the
   brand's posts (retrieved via tools)

3. Influencer Component = min(verified_influencer_count, 5) * (influencer_weight / 5.0)
   where verified_influencer_count is the number of distinct verified influencer
   accounts that have posted about the brand

4. Product Mention Component = min(critical_mention_ratio, 1.0) * product_mention_weight
   where critical_mention_ratio = number_of_critical_mentions / total_mentions
   for the brand

crisis_score = round(vol_comp + sent_comp + inf_comp + mention_comp, 2)

final_score = round(crisis_score * priority_multiplier, 2)
   where priority_multiplier comes from the brand tier classification file.

Qualification Criteria (ALL must be met for a brand to appear on the dashboard):
  - spike_ratio >= volume_spike_multiplier  (from crisis config)
  - avg_sentiment_score < sentiment_threshold  (from crisis config)
  - number_of_critical_mentions >= min_critical_mentions  (from crisis config)

Alert Level Assignment (based on final_score):
  - final_score >= CRITICAL threshold  -> "CRITICAL"
  - final_score >= HIGH threshold      -> "HIGH"
  - final_score >= MEDIUM threshold    -> "MEDIUM"
  - otherwise                          -> "LOW"
"""
    with open(os.path.join(workspace, "scoring_formula.txt"), "w") as f:
        f.write(formula_text)

    # 5. baseline_volumes.csv
    with open(os.path.join(workspace, "baseline_volumes.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["brand_id", "avg_daily_volume"])
        for bid in range(1, rows + 1):
            writer.writerow([bid, baseline_volumes[bid]])

    # --- Scalable files: monitoring reports ---
    brands_per_file = max(1, rows // num_files)
    for file_idx in range(num_files):
        start_brand = file_idx * brands_per_file + 1
        if file_idx == num_files - 1:
            end_brand = rows
        else:
            end_brand = (file_idx + 1) * brands_per_file

        file_data = [row for row in monitoring_data if start_brand <= row[0] <= end_brand]

        filename = f"monitoring_report_{file_idx + 1:03d}.csv"
        with open(os.path.join(workspace, filename), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["brand_id", "date", "platform", "post_count"])
            writer.writerows(file_data)

    conn.close()
    print(f"Database written to {db_path}")
    print(f"Workspace files written to {workspace}/")
    print(f"  - {num_files} monitoring report CSVs (scalable)")
    print(f"  - 5 config/reference files (fixed)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
