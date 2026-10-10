"""
Sponsored Content Delivery Reconciliation - Data Generator
Generates database and workspace files for ad delivery compliance checking.
"""
import argparse
import os
import sqlite3
import json
import csv
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 24,
}


def main(db_path, workspace):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    rows = SCALE["rows_per_table"]
    num_active = SCALE["num_workspace_files"]

    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ── Schema ──────────────────────────────────────────────────────
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS advertisers (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, industry TEXT,
            contact_email TEXT, tier TEXT, account_status TEXT);
        CREATE TABLE IF NOT EXISTS demographic_segments (
            id INTEGER PRIMARY KEY, segment_code TEXT UNIQUE NOT NULL,
            age_min INTEGER, age_max INTEGER, gender TEXT,
            income_level TEXT, region TEXT);
        CREATE TABLE IF NOT EXISTS insertion_orders (
            id INTEGER PRIMARY KEY, advertiser_id INTEGER NOT NULL,
            order_ref TEXT UNIQUE NOT NULL, start_date TEXT, end_date TEXT,
            status TEXT, guaranteed_impressions INTEGER,
            cpm_rate REAL, total_budget REAL,
            FOREIGN KEY(advertiser_id) REFERENCES advertisers(id));
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,
            campaign_name TEXT, platform TEXT, ad_format TEXT,
            target_segment_ids TEXT, start_date TEXT, end_date TEXT,
            status TEXT,
            FOREIGN KEY(order_id) REFERENCES insertion_orders(id));
        CREATE TABLE IF NOT EXISTS impression_logs (
            id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL,
            log_date TEXT, segment_id INTEGER,
            impressions_served INTEGER, clicks INTEGER,
            FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
            FOREIGN KEY(segment_id) REFERENCES demographic_segments(id));
        CREATE TABLE IF NOT EXISTS viewability_reports (
            id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL,
            report_date TEXT, measured_impressions INTEGER,
            viewable_impressions INTEGER, invalid_impressions INTEGER,
            verification_vendor TEXT,
            FOREIGN KEY(campaign_id) REFERENCES campaigns(id));
    """)

    # ── Demographic segments ────────────────────────────────────────
    age_ranges = [(18, 24), (25, 34), (35, 44), (45, 54), (55, 64), (65, 80)]
    genders = ["M", "F"]
    income_levels = ["LOW", "MED", "HIGH"]
    regions = ["NE", "SE", "MW", "W", "SW"]

    all_combos = []
    for ar in age_ranges:
        for g in genders:
            for il in income_levels:
                for r in regions:
                    all_combos.append(
                        (f"{g}{ar[0]}-{ar[1]}-{il}-{r}", ar[0], ar[1], g, il, r)
                    )
    # 180 possible combos, sample `rows`
    idx = np.random.choice(len(all_combos), size=min(rows, len(all_combos)), replace=False)
    idx.sort()
    segments = [all_combos[i] for i in idx]
    seg_code_to_id = {}
    for i, (code, amin, amax, g, il, r) in enumerate(segments, 1):
        cur.execute(
            "INSERT INTO demographic_segments VALUES(?,?,?,?,?,?,?)",
            (i, code, amin, amax, g, il, r),
        )
        seg_code_to_id[code] = i
    seg_codes = [s[0] for s in segments]
    seg_ids = list(range(1, len(segments) + 1))

    # ── Advertisers ─────────────────────────────────────────────────
    industries = [
        "Technology", "Finance", "Healthcare", "Retail", "Automotive",
        "Entertainment", "Food & Beverage", "Travel", "Education", "Real Estate",
    ]
    tiers_pool = ["Gold", "Silver", "Bronze"]
    advertisers = []
    for i in range(1, rows + 1):
        name = fake.company()
        adv = (
            i, name,
            str(np.random.choice(industries)),
            fake.company_email(),
            str(np.random.choice(tiers_pool, p=[0.2, 0.5, 0.3])),
            str(np.random.choice(["active", "inactive", "suspended"], p=[0.7, 0.2, 0.1])),
        )
        advertisers.append(adv)
    cur.executemany("INSERT INTO advertisers VALUES(?,?,?,?,?,?)", advertisers)
    adv_dict = {a[0]: a for a in advertisers}

    # ── Insertion orders (first num_active are active) ──────────────
    active_adv_ids = np.random.choice(
        range(1, rows + 1), size=num_active, replace=False
    ).tolist()

    platforms = ["Facebook", "Google", "Instagram", "TikTok", "YouTube"]
    ad_formats = ["display_banner", "video_pre_roll", "native_content", "rich_media"]
    vendors = ["DoubleVerify", "IAS", "Moat", "Comscore"]

    active_orders = []
    oid = 0

    for k in range(num_active):
        oid += 1
        adv_id = int(active_adv_ids[k])
        ref = f"IO-{1000 + oid}"
        guaranteed = int(np.random.choice([100000, 200000, 300000, 500000, 750000, 1000000]))
        cpm = round(float(np.random.uniform(5, 25)), 2)
        budget = round(guaranteed * cpm / 1000, 2)

        n_tgt = np.random.randint(2, min(6, len(seg_codes) + 1))
        tgt_idx = np.random.choice(len(seg_codes), size=n_tgt, replace=False)
        tgt_codes = [seg_codes[int(j)] for j in tgt_idx]
        tgt_ids = [seg_ids[int(j)] for j in tgt_idx]

        demo_thr = round(float(np.random.uniform(0.55, 0.80)), 2)
        view_thr = round(float(np.random.uniform(0.50, 0.75)), 2)

        delivery_factor = round(float(np.random.uniform(0.75, 1.15)), 4)
        demo_factor = round(float(np.random.uniform(0.50, 0.92)), 4)
        view_factor = round(float(np.random.uniform(0.45, 0.82)), 4)

        active_orders.append({
            "id": oid, "advertiser_id": adv_id, "order_ref": ref,
            "start_date": "2025-07-01", "end_date": "2025-12-31",
            "guaranteed": guaranteed, "cpm": cpm, "budget": budget,
            "target_codes": tgt_codes, "target_ids": tgt_ids,
            "demo_threshold": demo_thr, "view_threshold": view_thr,
            "delivery_factor": delivery_factor,
            "demo_factor": demo_factor, "view_factor": view_factor,
        })
        cur.execute(
            "INSERT INTO insertion_orders VALUES(?,?,?,?,?,?,?,?,?)",
            (oid, adv_id, ref, "2025-07-01", "2025-12-31", "active",
             guaranteed, cpm, budget),
        )

    # Inactive orders
    inactive_adv_pool = [i for i in range(1, rows + 1) if i not in active_adv_ids]
    if not inactive_adv_pool:
        inactive_adv_pool = list(range(1, rows + 1))
    for _ in range(rows - num_active):
        oid += 1
        adv_id = int(np.random.choice(inactive_adv_pool))
        ref = f"IO-{1000 + oid}"
        guaranteed = int(np.random.choice([50000, 100000, 200000]))
        cpm = round(float(np.random.uniform(5, 20)), 2)
        budget = round(guaranteed * cpm / 1000, 2)
        status = str(np.random.choice(["completed", "cancelled", "paused"]))
        cur.execute(
            "INSERT INTO insertion_orders VALUES(?,?,?,?,?,?,?,?,?)",
            (oid, adv_id, ref, "2025-01-01", "2025-06-30", status,
             guaranteed, cpm, budget),
        )

    # ── Campaigns ───────────────────────────────────────────────────
    cid = 0
    active_campaigns = []

    for o in active_orders:
        n_camp = np.random.randint(2, 6)  # 2-5 campaigns per active order
        for _ in range(n_camp):
            cid += 1
            cname = f"{fake.catch_phrase()} Campaign"
            plat = str(np.random.choice(platforms))
            fmt = str(np.random.choice(ad_formats))
            seg_str = ",".join(str(s) for s in o["target_ids"])
            active_campaigns.append({
                "id": cid, "order": o, "platform": plat, "ad_format": fmt,
            })
            cur.execute(
                "INSERT INTO campaigns VALUES(?,?,?,?,?,?,?,?,?)",
                (cid, o["id"], cname, plat, fmt, seg_str,
                 "2025-07-01", "2025-12-31", "active"),
            )

    # Pad inactive campaigns to reach `rows` minimum
    inactive_oids = list(range(num_active + 1, oid + 1))
    if not inactive_oids:
        inactive_oids = [1]
    while cid < rows:
        cid += 1
        cur.execute(
            "INSERT INTO campaigns VALUES(?,?,?,?,?,?,?,?,?)",
            (cid, int(np.random.choice(inactive_oids)),
             f"{fake.catch_phrase()} Campaign",
             str(np.random.choice(platforms)),
             str(np.random.choice(ad_formats)), "",
             "2025-01-01", "2025-06-30",
             str(np.random.choice(["completed", "paused"]))),
        )

    # ── Impression logs ─────────────────────────────────────────────
    months = pd.date_range("2025-07-01", "2025-12-01", freq="MS").strftime("%Y-%m-%d").tolist()
    lid = 0

    # Pre-compute campaign counts per order for impression allocation
    order_camp_count = {}
    for c in active_campaigns:
        oid_key = c["order"]["id"]
        order_camp_count[oid_key] = order_camp_count.get(oid_key, 0) + 1

    for camp in active_campaigns:
        o = camp["order"]
        n_camps_in_order = order_camp_count[o["id"]]
        camp_target = o["guaranteed"] * o["delivery_factor"] / n_camps_in_order

        for month in months:
            month_target = camp_target / len(months)
            on_target_total = month_target * o["demo_factor"]
            per_seg = on_target_total / max(1, len(o["target_ids"]))

            # On-target segments
            for seg_id in o["target_ids"]:
                imp = max(1, int(per_seg * float(np.random.uniform(0.8, 1.2))))
                clk = max(0, int(imp * float(np.random.uniform(0.005, 0.04))))
                lid += 1
                cur.execute(
                    "INSERT INTO impression_logs VALUES(?,?,?,?,?,?)",
                    (lid, camp["id"], month, int(seg_id), imp, clk),
                )

            # Off-target segments
            off_target_total = month_target * (1 - o["demo_factor"])
            off_segs = [s for s in seg_ids if s not in o["target_ids"]]
            n_off = min(3, len(off_segs))
            if off_segs and n_off > 0:
                chosen = np.random.choice(off_segs, size=n_off, replace=False)
                per_off = off_target_total / n_off
                for seg_id in chosen:
                    imp = max(1, int(per_off * float(np.random.uniform(0.7, 1.3))))
                    clk = max(0, int(imp * float(np.random.uniform(0.002, 0.03))))
                    lid += 1
                    cur.execute(
                        "INSERT INTO impression_logs VALUES(?,?,?,?,?,?)",
                        (lid, camp["id"], month, int(seg_id), imp, clk),
                    )

    # Pad to minimum
    while lid < rows:
        lid += 1
        c_id = int(np.random.choice([c["id"] for c in active_campaigns]))
        m = str(np.random.choice(months))
        s = int(np.random.choice(seg_ids))
        cur.execute(
            "INSERT INTO impression_logs VALUES(?,?,?,?,?,?)",
            (lid, c_id, m, s, int(np.random.randint(100, 3000)),
             int(np.random.randint(0, 50))),
        )

    # ── Viewability reports ─────────────────────────────────────────
    vid = 0
    for camp in active_campaigns:
        o = camp["order"]
        for month in months:
            vid += 1
            measured = int(np.random.randint(800, 8000))
            viewable = min(
                measured,
                max(0, int(measured * o["view_factor"]
                           * float(np.random.uniform(0.85, 1.15)))),
            )
            invalid = int(measured * float(np.random.uniform(0.01, 0.08)))
            vendor = str(np.random.choice(vendors))
            cur.execute(
                "INSERT INTO viewability_reports VALUES(?,?,?,?,?,?,?)",
                (vid, camp["id"], month, measured, viewable, invalid, vendor),
            )

    # Pad to minimum
    while vid < rows:
        vid += 1
        c_id = int(np.random.choice([c["id"] for c in active_campaigns]))
        m = str(np.random.choice(months))
        measured = int(np.random.randint(200, 5000))
        viewable = int(measured * float(np.random.uniform(0.3, 0.7)))
        invalid = int(measured * float(np.random.uniform(0.01, 0.12)))
        vendor = str(np.random.choice(vendors))
        cur.execute(
            "INSERT INTO viewability_reports VALUES(?,?,?,?,?,?,?)",
            (vid, c_id, m, measured, viewable, invalid, vendor),
        )

    conn.commit()

    # ── Workspace: config files (fixed) ─────────────────────────────
    cfg = os.path.join(workspace, "config")
    os.makedirs(cfg, exist_ok=True)

    # compliance_thresholds.yaml
    with open(os.path.join(cfg, "compliance_thresholds.yaml"), "w") as f:
        f.write("# Compliance evaluation configuration\n")
        f.write("delivery_tolerance_pct: 2.0\n")
        f.write("viewability_method: weighted_average\n")
        f.write("demographic_method: impression_weighted\n")
        f.write("penalty_calculation: bracket\n")
        f.write("certificate_fields:\n")
        f.write("  decimal_precision: 4\n")
        f.write("  currency: USD\n")

    # penalty_schedule.csv
    with open(os.path.join(cfg, "penalty_schedule.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["shortfall_pct_min", "shortfall_pct_max", "penalty_multiplier"])
        for row in [(0, 5, 0.00), (5, 15, 0.10), (15, 30, 0.25),
                     (30, 50, 0.50), (50, 100, 1.00)]:
            w.writerow(row)

    # viewability_benchmarks.json
    with open(os.path.join(cfg, "viewability_benchmarks.json"), "w") as f:
        json.dump({
            "display_banner":  {"min_measurement_sample": 3000, "industry_benchmark": 0.55},
            "video_pre_roll":  {"min_measurement_sample": 2000, "industry_benchmark": 0.70},
            "native_content":  {"min_measurement_sample": 2500, "industry_benchmark": 0.60},
            "rich_media":      {"min_measurement_sample": 2000, "industry_benchmark": 0.65},
        }, f, indent=2)

    # demographic_mapping.csv
    with open(os.path.join(cfg, "demographic_mapping.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["segment_id", "segment_code", "age_min", "age_max",
                     "gender", "income_level", "region"])
        for i, (code, amin, amax, g, il, r) in enumerate(segments, 1):
            w.writerow([i, code, amin, amax, g, il, r])

    # tier_adjustments.txt
    with open(os.path.join(cfg, "tier_adjustments.txt"), "w") as f:
        f.write("# Advertiser Tier Delivery Tolerance Adjustments\n")
        f.write("# Additional tolerance percentage added to the base delivery tolerance\n")
        f.write("# based on the advertiser's tier level.\n")
        f.write("#\n")
        f.write("Gold: 3.0\n")
        f.write("Silver: 1.5\n")
        f.write("Bronze: 0.0\n")

    # ── Workspace: contract files (scalable) ────────────────────────
    cdir = os.path.join(workspace, "contracts")
    os.makedirs(cdir, exist_ok=True)

    for o in active_orders:
        adv = adv_dict[o["advertiser_id"]]
        contract = {
            "order_ref": o["order_ref"],
            "advertiser_name": adv[1],
            "advertiser_tier": adv[4],
            "contract_period": {"start": o["start_date"], "end": o["end_date"]},
            "guaranteed_impressions": o["guaranteed"],
            "target_segments": o["target_codes"],
            "demographic_threshold": o["demo_threshold"],
            "viewability_threshold": o["view_threshold"],
            "cpm_rate": o["cpm"],
            "total_budget": o["budget"],
        }
        with open(os.path.join(cdir, f"{o['order_ref']}.json"), "w") as f:
            json.dump(contract, f, indent=2)

    conn.close()
    print(f"Generated: {rows} advertisers, {rows} orders ({num_active} active), "
          f"{cid} campaigns, {lid} impression logs, {vid} viewability reports, "
          f"{len(segments)} demographic segments")
    print(f"Workspace: {num_active} contracts, 5 config files")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db_path", required=True)
    p.add_argument("--workspace", required=True)
    args = p.parse_args()
    main(args.db_path, args.workspace)
