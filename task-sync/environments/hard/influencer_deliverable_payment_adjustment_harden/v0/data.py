import argparse
import sqlite3
import os
import json
import csv
import yaml
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 50,
    "num_workspace_files": 8,
}


def main(db_path, workspace):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    # Remove existing DB so re-runs are clean
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    N = SCALE["rows_per_table"]
    F = SCALE["num_workspace_files"]

    # ======================== REGION MAPPING (shared constant) ========================
    region_map = {
        "North America": ["US", "CA", "MX"],
        "Europe": ["UK", "DE", "FR", "ES", "IT"],
        "Asia Pacific": ["AU", "JP", "KR", "IN", "PH", "ID", "TH"],
        "Latin America": ["BR", "AR", "CO", "MX"],
        "Middle East": ["AE", "SA", "QA", "BH", "KW"],
    }
    all_countries = sorted(
        set(c for cs in region_map.values() for c in cs)
        | {"NG", "ZA", "SE", "NO", "PL", "RU", "CN", "SG", "NZ", "CL"}
    )

    # ======================== TABLE 1: influencers ========================
    cur.execute(
        """CREATE TABLE influencers (
        influencer_id INTEGER PRIMARY KEY,
        name TEXT,
        platform TEXT,
        follower_count INTEGER,
        niche TEXT,
        country TEXT,
        verified INTEGER
    )"""
    )

    platforms = ["Instagram", "TikTok", "YouTube", "Twitter"]
    niches = [
        "Fashion", "Tech", "Food", "Travel",
        "Fitness", "Beauty", "Gaming", "Education",
    ]
    inf_countries = ["US", "UK", "CA", "AU", "DE", "FR", "BR", "IN", "JP", "MX"]

    influencers = []
    for i in range(1, N + 1):
        row = (
            i,
            fake.name(),
            platforms[int(np.random.randint(len(platforms)))],
            int(np.random.randint(10000, 5000000)),
            niches[int(np.random.randint(len(niches)))],
            inf_countries[int(np.random.randint(len(inf_countries)))],
            int(np.random.randint(0, 2)),
        )
        influencers.append(row)
        cur.execute("INSERT INTO influencers VALUES (?,?,?,?,?,?,?)", row)

    # ======================== TABLE 2: contracts ========================
    cur.execute(
        """CREATE TABLE contracts (
        contract_id INTEGER PRIMARY KEY,
        influencer_id INTEGER,
        campaign_name TEXT,
        start_date TEXT,
        end_date TEXT,
        required_posts INTEGER,
        min_engagement_rate REAL,
        base_payment REAL,
        target_region TEXT,
        min_region_pct REAL,
        posting_hour_start INTEGER,
        posting_hour_end INTEGER,
        status TEXT,
        FOREIGN KEY(influencer_id) REFERENCES influencers(influencer_id)
    )"""
    )

    campaign_bases = [
        "Summer Splash", "Winter Gala", "Back to School", "Holiday Cheer",
        "Spring Forward", "Tech Launch", "Fitness Wave", "Beauty Reveal",
        "Travel Diaries", "Food Festival",
    ]
    regions = list(region_map.keys())

    contracts = []
    base_date = datetime(2025, 10, 1)
    for i in range(1, N + 1):
        r = float(np.random.random())
        if r < 0.32:
            status = "pending_review"
        elif r < 0.85:
            status = "completed"
        else:
            status = "cancelled"

        inf_id = int(np.random.randint(1, N + 1))
        camp = campaign_bases[int(np.random.randint(len(campaign_bases)))]
        req_posts = int(np.random.randint(2, 6))
        min_eng = round(float(np.random.uniform(0.02, 0.08)), 4)
        base_pay = round(float(np.random.uniform(1000, 20000)), 2)
        target_reg = regions[int(np.random.randint(len(regions)))]
        min_reg = round(float(np.random.uniform(0.25, 0.65)), 2)
        h_start = int(np.random.randint(6, 14))
        h_end = h_start + int(np.random.randint(4, 10))
        h_end = min(h_end, 23)

        s_offset = int(np.random.randint(0, 150))
        start_d = base_date + timedelta(days=s_offset)
        dur = int(np.random.randint(30, 90))
        end_d = start_d + timedelta(days=dur)

        c_dict = {
            "contract_id": i,
            "influencer_id": inf_id,
            "campaign_name": f"{camp} #{i}",
            "start_date": start_d.strftime("%Y-%m-%d"),
            "end_date": end_d.strftime("%Y-%m-%d"),
            "required_posts": req_posts,
            "min_engagement_rate": min_eng,
            "base_payment": base_pay,
            "target_region": target_reg,
            "min_region_pct": min_reg,
            "posting_hour_start": h_start,
            "posting_hour_end": h_end,
            "status": status,
        }
        contracts.append(c_dict)
        cur.execute(
            "INSERT INTO contracts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                i, inf_id, c_dict["campaign_name"],
                c_dict["start_date"], c_dict["end_date"],
                req_posts, min_eng, base_pay, target_reg, min_reg,
                h_start, h_end, status,
            ),
        )

    # ======================== TABLE 3: posts ========================
    cur.execute(
        """CREATE TABLE posts (
        post_id INTEGER PRIMARY KEY,
        contract_id INTEGER,
        influencer_id INTEGER,
        posted_at TEXT,
        content_type TEXT,
        likes INTEGER,
        comments INTEGER,
        shares INTEGER,
        impressions INTEGER,
        FOREIGN KEY(contract_id) REFERENCES contracts(contract_id),
        FOREIGN KEY(influencer_id) REFERENCES influencers(influencer_id)
    )"""
    )

    content_types = ["image", "video", "reel", "story", "carousel"]
    posts = []
    pid = 1
    for c in contracts:
        n_posts = int(np.random.randint(1, c["required_posts"] + 2))
        sd = datetime.strptime(c["start_date"], "%Y-%m-%d")
        ed = datetime.strptime(c["end_date"], "%Y-%m-%d")
        dur_days = max((ed - sd).days, 1)

        for _ in range(n_posts):
            # 15% chance of date violation
            if float(np.random.random()) < 0.15:
                day_off = int(np.random.randint(-30, 0))
                pdt = sd + timedelta(days=int(day_off))
            else:
                day_off = int(np.random.randint(0, dur_days))
                pdt = sd + timedelta(days=int(day_off))

            # 20% chance of hour violation
            if float(np.random.random()) < 0.20:
                bad_hours = [
                    h for h in range(24)
                    if h < c["posting_hour_start"] or h > c["posting_hour_end"]
                ]
                hour = bad_hours[int(np.random.randint(len(bad_hours)))] if bad_hours else 0
            else:
                hour = int(
                    np.random.randint(c["posting_hour_start"], c["posting_hour_end"] + 1)
                )

            minute = int(np.random.randint(0, 60))
            pdt = pdt.replace(hour=hour, minute=minute, second=0)

            impressions = int(np.random.randint(5000, 500000))
            if float(np.random.random()) < 0.25:
                eng_rate = float(np.random.uniform(0.005, 0.019))
            else:
                eng_rate = float(np.random.uniform(0.03, 0.15))

            total_eng = max(int(impressions * eng_rate), 1)
            likes = max(int(total_eng * float(np.random.uniform(0.50, 0.70))), 0)
            comments = max(int(total_eng * float(np.random.uniform(0.10, 0.25))), 0)
            shares = max(total_eng - likes - comments, 0)

            ct = content_types[int(np.random.randint(len(content_types)))]

            posts.append(
                {
                    "post_id": pid,
                    "contract_id": c["contract_id"],
                    "influencer_id": c["influencer_id"],
                    "posted_at": pdt.strftime("%Y-%m-%d %H:%M:%S"),
                    "content_type": ct,
                    "likes": likes,
                    "comments": comments,
                    "shares": shares,
                    "impressions": impressions,
                }
            )
            cur.execute(
                "INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?)",
                (pid, c["contract_id"], c["influencer_id"],
                 pdt.strftime("%Y-%m-%d %H:%M:%S"), ct,
                 likes, comments, shares, impressions),
            )
            pid += 1

    # Pad to at least N rows
    while len(posts) < N:
        c = contracts[len(posts) % len(contracts)]
        sd = datetime.strptime(c["start_date"], "%Y-%m-%d")
        ed = datetime.strptime(c["end_date"], "%Y-%m-%d")
        dur_days = max((ed - sd).days, 1)
        day_off = int(np.random.randint(0, dur_days))
        pdt = sd + timedelta(days=int(day_off))
        hour = int(np.random.randint(0, 24))
        pdt = pdt.replace(hour=hour, minute=0, second=0)
        impressions = int(np.random.randint(5000, 500000))
        eng = float(np.random.uniform(0.01, 0.10))
        total_eng = max(int(impressions * eng), 1)
        likes = int(total_eng * 0.6)
        comments = int(total_eng * 0.2)
        shares = max(total_eng - likes - comments, 0)
        ct = content_types[int(np.random.randint(len(content_types)))]
        posts.append(
            {
                "post_id": pid,
                "contract_id": c["contract_id"],
                "influencer_id": c["influencer_id"],
                "posted_at": pdt.strftime("%Y-%m-%d %H:%M:%S"),
                "content_type": ct,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "impressions": impressions,
            }
        )
        cur.execute(
            "INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, c["contract_id"], c["influencer_id"],
             pdt.strftime("%Y-%m-%d %H:%M:%S"), ct,
             likes, comments, shares, impressions),
        )
        pid += 1

    # ======================== TABLE 4: bot_detection ========================
    cur.execute(
        """CREATE TABLE bot_detection (
        detection_id INTEGER PRIMARY KEY,
        post_id INTEGER,
        bot_score REAL,
        flagged_accounts INTEGER,
        scan_confidence REAL,
        scan_method TEXT,
        scan_date TEXT,
        FOREIGN KEY(post_id) REFERENCES posts(post_id)
    )"""
    )

    scan_methods = ["neural_network", "heuristic", "behavioral_analysis", "hybrid"]
    det_id = 1
    for p in posts:
        n_scans = int(np.random.randint(1, 4))  # 1-3 scans per post
        for _ in range(n_scans):
            if float(np.random.random()) < 0.22:
                bscore = round(float(np.random.uniform(0.46, 0.95)), 3)
            else:
                bscore = round(float(np.random.uniform(0.02, 0.44)), 3)

            sconf = round(float(np.random.uniform(0.55, 0.99)), 3)
            sm = scan_methods[int(np.random.randint(len(scan_methods)))]
            pdt = datetime.strptime(p["posted_at"], "%Y-%m-%d %H:%M:%S")
            sdate = (pdt + timedelta(days=int(np.random.randint(1, 10)))).strftime(
                "%Y-%m-%d"
            )

            cur.execute(
                "INSERT INTO bot_detection VALUES (?,?,?,?,?,?,?)",
                (det_id, p["post_id"], bscore,
                 int(np.random.randint(0, 500)),
                 sconf, sm, sdate),
            )
            det_id += 1

    conn.commit()

    # ======================== WORKSPACE FILES ========================

    # ---------- Scalable: audience geo JSON files ----------
    posts_per_file = max(1, len(posts) // F)
    for fi in range(F):
        si = fi * posts_per_file
        ei = len(posts) if fi == F - 1 else si + posts_per_file
        batch = posts[si:ei]

        audience_data = {}
        for p in batch:
            c = next(ct for ct in contracts if ct["contract_id"] == p["contract_id"])
            target = c["target_region"]
            target_cs = region_map.get(target, [])

            n_c = int(np.random.randint(6, 14))
            sel = list(
                np.random.choice(
                    all_countries, size=min(n_c, len(all_countries)), replace=False
                )
            )

            # Ensure some target countries appear
            if target_cs and float(np.random.random()) < 0.70:
                for tc in target_cs[:2]:
                    if tc not in sel:
                        sel.append(tc)

            raw = np.random.dirichlet(np.ones(len(sel)))

            # Sometimes boost target region
            if float(np.random.random()) < 0.55 and target_cs:
                tidx = [j for j, cc in enumerate(sel) if cc in target_cs]
                if tidx:
                    boost = float(np.random.uniform(0.08, 0.35))
                    for ti in tidx:
                        raw[ti] += boost
                    raw = raw / raw.sum()

            breakdown = {}
            for j, cc in enumerate(sel):
                breakdown[cc] = round(float(raw[j]) * 100, 2)

            total_bd = sum(breakdown.values())
            if total_bd > 0:
                factor = 100.0 / total_bd
                breakdown = {k: round(v * factor, 2) for k, v in breakdown.items()}

            audience_data[str(p["post_id"])] = {
                "post_id": p["post_id"],
                "audience_breakdown": breakdown,
                "total_sampled": int(np.random.randint(500, 50000)),
            }

        with open(os.path.join(workspace, f"audience_geo_{fi + 1:03d}.json"), "w") as f:
            json.dump(audience_data, f, indent=2)

    # ---------- Fixed: compliance_rules.yaml ----------
    rules = {
        "bot_detection": {
            "max_bot_score": 0.45,
            "min_scan_confidence": 0.75,
            "penalty_pct": 25,
        },
        "engagement": {"penalty_pct": 20},
        "timing": {
            "date_violation_penalty_pct": 15,
            "hour_violation_penalty_pct": 10,
        },
        "audience_location": {"penalty_pct": 20},
        "post_count": {"penalty_per_missing_post_pct": 10},
        "max_total_penalty_pct": 100,
        "region_country_mapping": region_map,
    }
    with open(os.path.join(workspace, "compliance_rules.yaml"), "w") as f:
        yaml.dump(rules, f, default_flow_style=False, sort_keys=False)

    # ---------- Fixed: payment_terms.md ----------
    with open(os.path.join(workspace, "payment_terms.md"), "w") as f:
        f.write(
            "Payment adjustments are calculated per contract.\n\n"
            "For each contract under review, violations are assessed across all "
            "associated posts. Each violation type is applied at most once per "
            "contract, except for post count shortfall which accumulates per "
            "missing post.\n\n"
            "Timing violations are split into two independent sub-types: date "
            "violations (post falls outside the contract date window) and hour "
            "violations (post falls outside the allowed posting hours). Each "
            "sub-type is counted as a separate penalty if at least one post "
            "triggers it.\n\n"
            "Bot detection violations use the scan record with the highest "
            "scan_confidence for each post. If that record's bot_score exceeds "
            "the threshold, the post is flagged. Only scans with scan_confidence "
            "at or above the minimum confidence threshold are considered valid.\n\n"
            "Engagement rate is computed as (likes + comments + shares) / "
            "impressions for each post. If any post's rate falls below the "
            "contract's min_engagement_rate, the engagement penalty applies.\n\n"
            "Audience location compliance checks whether the sum of audience "
            "percentages from countries in the contract's target region meets or "
            "exceeds the min_region_pct threshold. The min_region_pct value in "
            "the contract is expressed as a decimal fraction (e.g. 0.40 means "
            "40 percent). Compare it against the audience percentage sum divided "
            "by 100.\n\n"
            "Post count shortfall is the difference between required_posts and "
            "the actual number of posts delivered under the contract. Each "
            "missing post incurs the penalty_per_missing_post_pct.\n\n"
            "The total penalty percentage is the sum of all applicable "
            "penalties, capped at max_total_penalty_pct.\n\n"
            "Adjusted payment = base_payment * (1 - total_penalty_pct / 100), "
            "rounded to two decimal places.\n"
        )

    # ---------- Fixed: audit_methodology.md ----------
    with open(os.path.join(workspace, "audit_methodology.md"), "w") as f:
        f.write(
            "Compliance review methodology.\n\n"
            "Scope. Every contract whose status is pending review is audited. "
            "Contracts in any other status are out of scope. Violations are "
            "assessed per post: a single post can trigger several different "
            "violation types, and each (post, violation type) pair is flagged "
            "as its own violation.\n\n"
            "Boundary conventions. The contract date window runs from the start "
            "date through the end date and is inclusive on both ends: a post is "
            "a date violation only if its calendar date falls strictly before "
            "the start date or strictly after the end date. The allowed "
            "posting-hour window is likewise inclusive on both ends: a post is "
            "an hour violation only if its hour of publication is strictly "
            "below the contract's starting hour or strictly above its ending "
            "hour. Date and hour checks are independent and tracked as "
            "separate violation types.\n\n"
            "Audience geography data. Per-post audience composition is provided "
            "in the audience geography JSON documents stored in this workspace, "
            "keyed by post identifier, as per-country percentage breakdowns. "
            "The region-to-country mapping in the compliance configuration "
            "defines which countries belong to each target region; the audience "
            "location check itself follows the payment terms document.\n\n"
            "Bot activity data. Historical bot-detection scan records are "
            "retrieved through the review tooling, and a post may have multiple "
            "scan records. Scan validity, scan selection, and the flagging "
            "threshold follow the payment terms document and the compliance "
            "configuration.\n\n"
            "Recording results. Each audited contract's outcome — its total "
            "penalty percentage and its adjusted payment — is recorded through "
            "the payments system so the adjustment ledger reflects the review, "
            "including contracts that incurred no penalty.\n"
        )

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
