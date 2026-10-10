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
    "rows_per_table": 320,
    "num_workspace_files": 30,
}

ASSET_TYPES = ["broadcast", "signage", "social_media"]
PLATFORMS = ["twitter", "instagram", "facebook", "tiktok", "youtube"]
CAMERA_ANGLES = [
    "wide_left", "wide_right", "center_field", "sideline_close",
    "overhead", "behind_goal", "corner_view", "press_box",
    "tunnel_cam", "crowd_pan",
]
SCREEN_LOCATIONS = [
    "north_concourse", "south_concourse", "east_entrance", "west_entrance",
    "main_scoreboard", "ribbon_board_level1", "ribbon_board_level2",
    "vip_lounge", "concession_area_A", "concession_area_B",
    "gate_1_digital", "gate_2_digital", "gate_3_digital",
    "press_room", "parking_display",
]
TIERS = ["platinum", "gold", "silver", "bronze"]
VENUES = [
    "Grand Arena", "National Stadium", "City Convention Center",
    "Riverside Amphitheater", "Metro Dome", "Coastal Pavilion",
    "Highland Park Arena", "Downtown Fieldhouse", "Lakeside Complex",
    "Westfield Coliseum", "Summit Stadium", "Heritage Hall",
]
EVENT_TYPES = ["match", "concert", "festival", "conference", "gala"]


def main(db_path, workspace):
    np.random.seed(42)
    random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    R = SCALE["rows_per_table"]
    F = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ── Table: sponsors ──
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sponsors (
            sponsor_id INTEGER PRIMARY KEY,
            sponsor_name TEXT NOT NULL,
            tier TEXT NOT NULL,
            industry TEXT NOT NULL,
            contact_email TEXT NOT NULL,
            contract_start TEXT NOT NULL,
            contract_end TEXT NOT NULL
        )
    """)

    industries = [
        "Technology", "Finance", "Automotive", "Beverage", "Apparel",
        "Telecommunications", "Healthcare", "Energy", "Retail", "Insurance",
    ]
    sponsors = []
    used_names = set()
    for i in range(1, R + 1):
        while True:
            name = fake.company()
            if name not in used_names:
                used_names.add(name)
                break
        tier = TIERS[np.random.randint(0, len(TIERS))]
        industry = industries[np.random.randint(0, len(industries))]
        email = fake.company_email()
        start = fake.date_between(start_date="-2y", end_date="-1y").isoformat()
        end = fake.date_between(start_date="+6m", end_date="+2y").isoformat()
        sponsors.append((i, name, tier, industry, email, start, end))
    cur.executemany(
        "INSERT INTO sponsors VALUES (?,?,?,?,?,?,?)", sponsors
    )

    # ── Table: events ──
    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY,
            event_name TEXT NOT NULL,
            event_date TEXT NOT NULL,
            venue TEXT NOT NULL,
            event_type TEXT NOT NULL,
            attendance INTEGER NOT NULL
        )
    """)

    events = []
    for i in range(1, R + 1):
        etype = EVENT_TYPES[np.random.randint(0, len(EVENT_TYPES))]
        name = f"{fake.catch_phrase()} {etype.title()} {i}"
        date = fake.date_between(start_date="-6m", end_date="+3m").isoformat()
        venue = VENUES[np.random.randint(0, len(VENUES))]
        attendance = int(np.random.randint(5000, 80001))
        events.append((i, name, date, venue, etype, attendance))
    cur.executemany(
        "INSERT INTO events VALUES (?,?,?,?,?,?)", events
    )

    # ── Table: entitlements ──
    cur.execute("""
        CREATE TABLE IF NOT EXISTS entitlements (
            entitlement_id INTEGER PRIMARY KEY,
            sponsor_id INTEGER NOT NULL,
            event_id INTEGER NOT NULL,
            asset_type TEXT NOT NULL,
            contracted_impressions INTEGER NOT NULL,
            penalty_rate_pct REAL NOT NULL,
            FOREIGN KEY (sponsor_id) REFERENCES sponsors(sponsor_id),
            FOREIGN KEY (event_id) REFERENCES events(event_id)
        )
    """)

    entitlements = []
    ent_id = 1
    # Ensure at least R entitlements; distribute across sponsors × events × asset_types
    sponsor_ids = [s[0] for s in sponsors]
    event_ids = [e[0] for e in events]
    pairs_used = set()
    while len(entitlements) < R:
        sid = sponsor_ids[np.random.randint(0, len(sponsor_ids))]
        eid = event_ids[np.random.randint(0, len(event_ids))]
        atype = ASSET_TYPES[np.random.randint(0, len(ASSET_TYPES))]
        key = (sid, eid, atype)
        if key in pairs_used:
            continue
        pairs_used.add(key)
        contracted = int(np.random.randint(5000, 100001))
        penalty = round(float(np.random.choice([5.0, 8.0, 10.0, 12.0, 15.0])), 1)
        entitlements.append((ent_id, sid, eid, atype, contracted, penalty))
        ent_id += 1
    cur.executemany(
        "INSERT INTO entitlements VALUES (?,?,?,?,?,?)", entitlements
    )

    # Build lookup for generating delivery data
    ent_by_type = {"broadcast": [], "signage": [], "social_media": []}
    for e in entitlements:
        ent_by_type[e[3]].append(e)

    # ── Table: broadcast_logs ──
    cur.execute("""
        CREATE TABLE IF NOT EXISTS broadcast_logs (
            log_id INTEGER PRIMARY KEY,
            event_id INTEGER NOT NULL,
            sponsor_id INTEGER NOT NULL,
            camera_angle TEXT NOT NULL,
            segment_start_sec INTEGER NOT NULL,
            segment_end_sec INTEGER NOT NULL,
            raw_impressions INTEGER NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(event_id),
            FOREIGN KEY (sponsor_id) REFERENCES sponsors(sponsor_id)
        )
    """)

    broadcast_logs = []
    blog_id = 1
    # Generate multiple logs per broadcast entitlement
    for ent in ent_by_type["broadcast"]:
        _, sid, eid, _, contracted, _ = ent
        n_logs = np.random.randint(2, 6)
        total_target = contracted * np.random.uniform(0.7, 1.1)
        portions = np.random.dirichlet(np.ones(n_logs)) * total_target
        t = 0
        for k in range(n_logs):
            angle = CAMERA_ANGLES[np.random.randint(0, len(CAMERA_ANGLES))]
            duration = int(np.random.randint(15, 121))
            impr = max(1, int(portions[k]))
            broadcast_logs.append(
                (blog_id, eid, sid, angle, t, t + duration, impr)
            )
            blog_id += 1
            t += duration + int(np.random.randint(60, 600))
    # Pad to meet minimum row count
    while len(broadcast_logs) < R:
        sid = sponsor_ids[np.random.randint(0, len(sponsor_ids))]
        eid = event_ids[np.random.randint(0, len(event_ids))]
        angle = CAMERA_ANGLES[np.random.randint(0, len(CAMERA_ANGLES))]
        t = int(np.random.randint(0, 3600))
        dur = int(np.random.randint(10, 60))
        impr = int(np.random.randint(100, 5000))
        broadcast_logs.append((blog_id, eid, sid, angle, t, t + dur, impr))
        blog_id += 1
    cur.executemany(
        "INSERT INTO broadcast_logs VALUES (?,?,?,?,?,?,?)", broadcast_logs
    )

    # ── Table: signage_schedules ──
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signage_schedules (
            schedule_id INTEGER PRIMARY KEY,
            event_id INTEGER NOT NULL,
            sponsor_id INTEGER NOT NULL,
            screen_id TEXT NOT NULL,
            slot_start TEXT NOT NULL,
            slot_end TEXT NOT NULL,
            scheduled_displays INTEGER NOT NULL,
            actual_displays INTEGER NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(event_id),
            FOREIGN KEY (sponsor_id) REFERENCES sponsors(sponsor_id)
        )
    """)

    signage_rows = []
    sig_id = 1
    # Map venues to screens (deterministic)
    venue_screens = {}
    rng_screens = np.random.RandomState(42)
    for v in VENUES:
        n_scr = rng_screens.randint(3, 8)
        venue_screens[v] = [
            SCREEN_LOCATIONS[i % len(SCREEN_LOCATIONS)]
            for i in range(n_scr)
        ]

    for ent in ent_by_type["signage"]:
        _, sid, eid, _, contracted, _ = ent
        venue = dict((e[0], e[3]) for e in events)[eid]
        screens = venue_screens.get(venue, SCREEN_LOCATIONS[:3])
        n_slots = np.random.randint(2, min(6, len(screens) + 1))
        chosen = [screens[i % len(screens)] for i in range(n_slots)]
        for scr in chosen:
            sched = int(np.random.randint(50, 301))
            # Actual may be less or equal
            actual = max(0, sched - int(np.random.randint(0, int(sched * 0.4) + 1)))
            hour_s = np.random.randint(9, 20)
            hour_e = min(23, hour_s + np.random.randint(1, 4))
            signage_rows.append((
                sig_id, eid, sid, scr,
                f"{hour_s:02d}:00", f"{hour_e:02d}:00",
                sched, actual,
            ))
            sig_id += 1
    while len(signage_rows) < R:
        sid = sponsor_ids[np.random.randint(0, len(sponsor_ids))]
        eid = event_ids[np.random.randint(0, len(event_ids))]
        scr = SCREEN_LOCATIONS[np.random.randint(0, len(SCREEN_LOCATIONS))]
        sched = int(np.random.randint(30, 200))
        actual = max(0, sched - int(np.random.randint(0, 60)))
        signage_rows.append((
            sig_id, eid, sid, scr,
            f"{np.random.randint(9,18):02d}:00",
            f"{np.random.randint(18,23):02d}:00",
            sched, actual,
        ))
        sig_id += 1
    cur.executemany(
        "INSERT INTO signage_schedules VALUES (?,?,?,?,?,?,?,?)", signage_rows
    )

    # ── Table: social_media_feeds ──
    cur.execute("""
        CREATE TABLE IF NOT EXISTS social_media_feeds (
            feed_id INTEGER PRIMARY KEY,
            event_id INTEGER NOT NULL,
            sponsor_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            post_type TEXT NOT NULL,
            impressions INTEGER NOT NULL,
            engagement_count INTEGER NOT NULL,
            captured_ts TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(event_id),
            FOREIGN KEY (sponsor_id) REFERENCES sponsors(sponsor_id)
        )
    """)

    post_types = ["organic", "paid", "influencer", "repost"]
    sm_rows = []
    sm_id = 1
    for ent in ent_by_type["social_media"]:
        _, sid, eid, _, contracted, _ = ent
        n_posts = np.random.randint(3, 8)
        total_target = contracted * np.random.uniform(0.65, 1.15)
        portions = np.random.dirichlet(np.ones(n_posts)) * total_target
        for k in range(n_posts):
            plat = PLATFORMS[np.random.randint(0, len(PLATFORMS))]
            ptype = post_types[np.random.randint(0, len(post_types))]
            impr = max(1, int(portions[k]))
            eng = max(0, int(impr * np.random.uniform(0.01, 0.15)))
            ts = fake.date_time_between(start_date="-6m", end_date="now").isoformat()
            sm_rows.append((sm_id, eid, sid, plat, ptype, impr, eng, ts))
            sm_id += 1
    while len(sm_rows) < R:
        sid = sponsor_ids[np.random.randint(0, len(sponsor_ids))]
        eid = event_ids[np.random.randint(0, len(event_ids))]
        plat = PLATFORMS[np.random.randint(0, len(PLATFORMS))]
        ptype = post_types[np.random.randint(0, len(post_types))]
        impr = int(np.random.randint(500, 20000))
        eng = int(impr * np.random.uniform(0.01, 0.1))
        ts = fake.date_time_between(start_date="-6m", end_date="now").isoformat()
        sm_rows.append((sm_id, eid, sid, plat, ptype, impr, eng, ts))
        sm_id += 1
    cur.executemany(
        "INSERT INTO social_media_feeds VALUES (?,?,?,?,?,?,?,?)", sm_rows
    )

    conn.commit()

    # ═══════════════════════════════════════════════════════════════
    # Workspace files
    # ═══════════════════════════════════════════════════════════════

    # --- Fixed files (not counted in SCALE["num_workspace_files"]) ---

    # 1. compliance_thresholds.yaml
    #    Minimum delivery percentage by sponsor tier to be "compliant"
    import yaml
    thresholds = {
        "compliance_thresholds": {
            "platinum": 0.95,
            "gold": 0.90,
            "silver": 0.85,
            "bronze": 0.80,
        },
        "description": (
            "Minimum fraction of contracted impressions that must be delivered "
            "for the entitlement to be considered compliant. Looked up by sponsor tier."
        ),
    }
    with open(os.path.join(workspace, "compliance_thresholds.yaml"), "w") as f:
        yaml.dump(thresholds, f, default_flow_style=False, sort_keys=False)

    # 2. billing_adjustment_rates.json
    #    Shortfall bands → adjustment multiplier applied to (contracted - delivered) * penalty_rate
    adj_rates = {
        "shortfall_bands": [
            {"min_shortfall_pct": 0.0, "max_shortfall_pct": 5.0, "adjustment_multiplier": 0.0},
            {"min_shortfall_pct": 5.0, "max_shortfall_pct": 15.0, "adjustment_multiplier": 0.5},
            {"min_shortfall_pct": 15.0, "max_shortfall_pct": 30.0, "adjustment_multiplier": 1.0},
            {"min_shortfall_pct": 30.0, "max_shortfall_pct": 100.0, "adjustment_multiplier": 1.5},
        ],
        "description": (
            "Shortfall percentage = (contracted - delivered) / contracted * 100. "
            "Find the band where shortfall_pct falls. "
            "billing_adjustment = shortfall_impressions * (penalty_rate_pct / 100) * adjustment_multiplier. "
            "shortfall_impressions = contracted - delivered (only when delivered < contracted)."
        ),
    }
    with open(os.path.join(workspace, "billing_adjustment_rates.json"), "w") as f:
        json.dump(adj_rates, f, indent=2)

    # 3. impression_weights.csv
    #    Platform-level multipliers for social media impressions
    platform_weights = [
        {"platform": "twitter", "weight": 1.0},
        {"platform": "instagram", "weight": 1.2},
        {"platform": "facebook", "weight": 0.9},
        {"platform": "tiktok", "weight": 1.3},
        {"platform": "youtube", "weight": 1.5},
    ]
    with open(os.path.join(workspace, "impression_weights.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["platform", "weight"])
        writer.writeheader()
        writer.writerows(platform_weights)

    # 4. verification_policy.txt
    #    Rules for how verified vs unverified social media posts are counted
    with open(os.path.join(workspace, "verification_policy.txt"), "w") as f:
        f.write(
            "Social Media Impression Verification Policy\n"
            "============================================\n\n"
            "Each social media feed entry may be classified as verified or unverified.\n"
            "Verification status is determined by the external audit batches stored in\n"
            "the social verification CSV files.\n\n"
            "Counting rules:\n"
            "- Verified posts: impressions count at 100% of their platform-weighted value.\n"
            "- Unverified posts: impressions count at 50% of their platform-weighted value.\n"
            "- If a feed_id does not appear in any verification batch file, treat it as unverified.\n\n"
            "Effective impressions for a social media feed entry:\n"
            "  effective = raw_impressions * platform_weight * verification_factor\n"
            "  where verification_factor = 1.0 if verified, 0.5 if unverified.\n"
        )

    # --- Scalable files ---

    # Split into two categories:
    #   - venue_report_XXX.json  (visibility factors for signage screens)
    #   - social_verification_batch_XXX.csv  (verified/unverified flags for feeds)

    n_venue_reports = F // 2
    n_social_batches = F - n_venue_reports

    # Venue reports: assign visibility factors to screens per venue
    # Each report covers a subset of events (by venue)
    all_venues_used = sorted(set(e[3] for e in events))
    venues_per_report = max(1, len(all_venues_used) // max(1, n_venue_reports))

    # Build a mapping: (event_id, screen_id) -> visibility_factor
    # stored in venue reports for later reference
    visibility_map = {}
    rng_vis = np.random.RandomState(42)

    for rpt_idx in range(n_venue_reports):
        start_v = rpt_idx * venues_per_report
        end_v = len(all_venues_used) if rpt_idx == n_venue_reports - 1 else (rpt_idx + 1) * venues_per_report
        report_venues = all_venues_used[start_v:end_v]

        report_data = {"report_index": rpt_idx + 1, "venues": []}
        for venue_name in report_venues:
            screens = venue_screens.get(venue_name, SCREEN_LOCATIONS[:3])
            screen_entries = []
            for scr in screens:
                vis = round(float(rng_vis.uniform(0.5, 1.0)), 2)
                screen_entries.append({
                    "screen_id": scr,
                    "visibility_factor": vis,
                })
                # Store for all events at this venue
                for ev in events:
                    if ev[3] == venue_name:
                        visibility_map[(ev[0], scr)] = vis
            report_data["venues"].append({
                "venue_name": venue_name,
                "screens": screen_entries,
            })

        fname = f"venue_report_{rpt_idx + 1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(report_data, f, indent=2)

    # Social verification batches: assign verified status to feed entries
    all_feed_ids = [row[0] for row in sm_rows]
    np.random.shuffle(all_feed_ids)
    # ~75% of feeds appear in verification files; rest are "missing" → unverified
    n_verified_feeds = int(len(all_feed_ids) * 0.75)
    feeds_in_batches = all_feed_ids[:n_verified_feeds]
    feeds_per_batch = max(1, len(feeds_in_batches) // max(1, n_social_batches))

    verification_status = {}  # feed_id -> verified bool
    rng_ver = np.random.RandomState(123)

    for batch_idx in range(n_social_batches):
        start_f = batch_idx * feeds_per_batch
        end_f = len(feeds_in_batches) if batch_idx == n_social_batches - 1 else (batch_idx + 1) * feeds_per_batch
        batch_feeds = feeds_in_batches[start_f:end_f]

        rows_out = []
        for fid in sorted(batch_feeds):
            is_verified = bool(rng_ver.random() > 0.3)  # ~70% verified
            verification_status[fid] = is_verified
            rows_out.append({
                "feed_id": fid,
                "verified": is_verified,
                "audit_date": fake.date_between(start_date="-3m", end_date="now").isoformat(),
            })

        fname = f"social_verification_batch_{batch_idx + 1:03d}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["feed_id", "verified", "audit_date"])
            writer.writeheader()
            writer.writerows(rows_out)

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
