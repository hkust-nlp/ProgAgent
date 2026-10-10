import argparse
import os
import sqlite3
import json
import csv
import math
from datetime import date
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 50,
    "num_workspace_files": 10,
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GENRES = [
    "True Crime", "Comedy", "Technology", "Health & Wellness", "Business",
    "Education", "News", "Sports", "Science", "Entertainment",
]
NETWORKS = [
    "PodcastOne", "Wondery", "Gimlet", "Radiotopia", "Earwolf",
    "Stitcher", "iHeart", "NPR", "Spotify Studios", "Independent",
]
AD_TYPES = ["pre-roll", "mid-roll", "post-roll"]
AGE_GROUPS = ["18-24", "25-34", "35-44", "45-54", "55+"]
CONTENT_TYPES = [
    "interview", "monologue", "panel_discussion", "listener_qa",
    "news_recap", "deep_dive", "sponsor_segment", "case_study",
    "storytelling", "tutorial",
]
SEGMENT_TOPICS = [
    "opening_remarks", "guest_spotlight", "industry_trends",
    "audience_questions", "product_review", "weekly_roundup",
    "expert_debate", "behind_the_scenes", "personal_story",
    "data_breakdown", "cultural_commentary", "book_review",
    "tech_demo", "health_tips", "career_advice", "travel_stories",
    "cooking_corner", "finance_update", "science_explainer",
    "closing_thoughts",
]
NAME_TEMPLATES = [
    "The {adj} {noun} Show",
    "{adj} Unplugged",
    "The {noun} Hour",
    "{adj} & {noun}",
    "{noun} Uncovered",
    "The {adj} Podcast",
    "{noun} Today",
    "Inside {adj}",
    "Beyond {noun}",
    "{adj} Chronicles",
    "The Daily {noun}",
    "{noun} Explained",
    "{adj} Live",
    "The {noun} Report",
    "{adj} Nation",
    "{noun} After Dark",
    "The {adj} Files",
    "{adj} Matters",
    "All About {noun}",
    "{noun} Unfiltered",
]

BASELINE_PERIOD = "2025-Q3"
CURRENT_PERIOD = "2025-Q4"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def generate_podcast_name(fake, idx):
    template = NAME_TEMPLATES[idx % len(NAME_TEMPLATES)]
    return template.format(adj=fake.word().title(), noun=fake.word().title())


def make_segment_boundaries(initial, final, num_segments, rng, concentrated=False):
    """Return list of num_segments+1 listener-count boundary values."""
    if num_segments <= 1:
        return [int(initial), int(final)]
    total_drop = initial - final
    if total_drop <= 0:
        return [int(initial)] * num_segments + [int(final)]
    # random weights for per-segment drop
    if concentrated:
        raw = rng.exponential(1.0, size=num_segments)
        n_boost = min(2, num_segments)
        boost_idx = rng.choice(num_segments, size=n_boost, replace=False)
        raw[boost_idx] *= rng.uniform(4.0, 8.0, size=n_boost)
    else:
        raw = rng.uniform(0.5, 2.0, size=num_segments)
    weights = raw / raw.sum()
    drops = np.round(weights * total_drop).astype(int)
    drops = np.maximum(drops, 0)
    drops[-1] = total_drop - drops[:-1].sum()
    if drops[-1] < 0:
        drops[-1] = 0
    # redistribute any leftover
    leftover = total_drop - int(drops.sum())
    if leftover > 0:
        for i in np.argsort(drops)[::-1]:
            if leftover <= 0:
                break
            drops[i] += 1
            leftover -= 1
    boundaries = [int(initial)]
    cur = int(initial)
    for i in range(num_segments):
        if i == num_segments - 1:
            boundaries.append(int(final))
        else:
            cur = max(cur - int(drops[i]), int(final))
            boundaries.append(cur)
    return boundaries


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(db_path, workspace):
    os.makedirs(workspace, exist_ok=True)
    rng = np.random.default_rng(42)
    fake = Faker()
    Faker.seed(42)

    num_podcasts = SCALE["rows_per_table"]
    eps_per_podcast = 6          # 3 baseline + 3 current
    num_declining = max(4, num_podcasts // 5)
    n_ws_files = SCALE["num_workspace_files"]

    # ------------------------------------------------------------------
    # 1. Podcasts
    # ------------------------------------------------------------------
    used_names = set()
    podcasts = []
    for i in range(1, num_podcasts + 1):
        name = generate_podcast_name(fake, i)
        while name in used_names:
            name = generate_podcast_name(fake, i + len(used_names) + 100)
        used_names.add(name)
        podcasts.append({
            "podcast_id": i,
            "name": name,
            "genre": GENRES[(i - 1) % len(GENRES)],
            "host": fake.name(),
            "network": NETWORKS[(i - 1) % len(NETWORKS)],
            "launch_date": fake.date_between(start_date="-3y", end_date="-1y").isoformat(),
            "status": "active" if rng.random() < 0.85 else "paused",
        })

    # ------------------------------------------------------------------
    # 2. Select declining podcast IDs
    # ------------------------------------------------------------------
    declining_ids = set(
        (rng.choice(num_podcasts, size=num_declining, replace=False) + 1).tolist()
    )

    # ------------------------------------------------------------------
    # 3. Episodes
    # ------------------------------------------------------------------
    episodes = []
    ep_id = 1
    for p in podcasts:
        for ep_num in range(1, eps_per_podcast + 1):
            if ep_num <= eps_per_podcast // 2:
                period = BASELINE_PERIOD
                air_date = fake.date_between(
                    start_date=date(2025, 7, 1), end_date=date(2025, 9, 30)
                ).isoformat()
            else:
                period = CURRENT_PERIOD
                air_date = fake.date_between(
                    start_date=date(2025, 10, 1), end_date=date(2025, 12, 31)
                ).isoformat()
            num_segments = int(rng.integers(4, 7))
            duration = int(num_segments * rng.integers(300, 901))
            episodes.append({
                "episode_id": ep_id,
                "podcast_id": p["podcast_id"],
                "podcast_name": p["name"],
                "episode_number": ep_num,
                "title": f"Ep{ep_num}: {fake.sentence(nb_words=4).rstrip('.')}",
                "air_date": air_date,
                "duration_seconds": duration,
                "num_segments": num_segments,
                "period": period,
            })
            ep_id += 1

    # ------------------------------------------------------------------
    # 4. Listener retention (one row per episode)
    # ------------------------------------------------------------------
    retention = []
    for ep in episodes:
        pid = ep["podcast_id"]
        is_declining = pid in declining_ids
        is_current = ep["period"] == CURRENT_PERIOD
        if is_declining and is_current:
            rate = float(rng.uniform(0.38, 0.62))
        elif is_declining:
            rate = float(rng.uniform(0.72, 0.88))
        else:
            rate = float(rng.uniform(0.64, 0.86))
        initial = int(rng.integers(5000, 50001))
        final = max(1, int(round(initial * rate)))
        actual_rate = round(final / initial, 4)
        retention.append({
            "episode_id": ep["episode_id"],
            "initial_listeners": initial,
            "final_listeners": final,
            "retention_rate": actual_rate,
        })

    # ------------------------------------------------------------------
    # 5. Ad placements
    # ------------------------------------------------------------------
    advertisers = [fake.company() for _ in range(30)]
    ad_rows = []
    ad_id = 1
    for ep in episodes:
        n_ads = int(rng.integers(1, 4))
        dur = ep["duration_seconds"]
        for _ in range(n_ads):
            ad_type = str(rng.choice(AD_TYPES))
            if ad_type == "pre-roll":
                pos = int(rng.integers(0, min(30, dur)))
            elif ad_type == "mid-roll":
                lo = max(1, dur // 3)
                hi = max(lo + 1, 2 * dur // 3)
                pos = int(rng.integers(lo, hi))
            else:
                lo = max(1, dur - 120)
                hi = max(lo + 1, dur)
                pos = int(rng.integers(lo, hi))
            ad_rows.append({
                "ad_id": ad_id,
                "episode_id": ep["episode_id"],
                "ad_position_seconds": pos,
                "ad_duration_seconds": int(rng.choice([15, 30, 60])),
                "ad_type": ad_type,
                "advertiser": str(rng.choice(advertisers)),
                "revenue_per_mille": round(float(rng.uniform(15.0, 45.0)), 2),
            })
            ad_id += 1

    # Pad to minimum row count
    while len(ad_rows) < SCALE["rows_per_table"]:
        ep = episodes[len(ad_rows) % len(episodes)]
        ad_rows.append({
            "ad_id": ad_id,
            "episode_id": ep["episode_id"],
            "ad_position_seconds": int(rng.integers(0, max(1, ep["duration_seconds"]))),
            "ad_duration_seconds": 30,
            "ad_type": "mid-roll",
            "advertiser": str(rng.choice(advertisers)),
            "revenue_per_mille": round(float(rng.uniform(15.0, 45.0)), 2),
        })
        ad_id += 1

    # ------------------------------------------------------------------
    # 6. Listener demographics
    # ------------------------------------------------------------------
    demo_rows = []
    demo_id = 1
    for p in podcasts:
        for period in [BASELINE_PERIOD, CURRENT_PERIOD]:
            total = int(rng.integers(10000, 100001))
            is_declining = p["podcast_id"] in declining_ids
            is_current = period == CURRENT_PERIOD
            if is_declining and is_current:
                # Demographic shift: younger drops, older increases
                base_weights = np.array([0.08, 0.14, 0.24, 0.30, 0.24])
            else:
                base_weights = np.array([0.22, 0.30, 0.24, 0.14, 0.10])
            noise = rng.uniform(-0.02, 0.02, size=5)
            weights = base_weights + noise
            weights = np.maximum(weights, 0.01)
            weights /= weights.sum()
            for j, ag in enumerate(AGE_GROUPS):
                count = int(round(total * weights[j]))
                demo_rows.append({
                    "demo_id": demo_id,
                    "podcast_id": p["podcast_id"],
                    "period": period,
                    "age_group": ag,
                    "listener_count": count,
                })
                demo_id += 1

    # ------------------------------------------------------------------
    # 7. Competitor shows
    # ------------------------------------------------------------------
    comp_rows = []
    comp_id = 1
    comps_per_genre = max(SCALE["rows_per_table"] // len(GENRES), 5)
    for genre in GENRES:
        for _ in range(comps_per_genre):
            comp_rows.append({
                "competitor_id": comp_id,
                "genre": genre,
                "show_name": f"{fake.word().title()} {fake.word().title()}",
                "network": str(rng.choice(NETWORKS)),
                "avg_retention_rate": round(float(rng.uniform(0.60, 0.92)), 4),
                "monthly_listeners": int(rng.integers(10000, 500001)),
            })
            comp_id += 1

    # ------------------------------------------------------------------
    # 8. Create database
    # ------------------------------------------------------------------
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE podcasts (
            podcast_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            genre TEXT NOT NULL,
            host TEXT NOT NULL,
            network TEXT NOT NULL,
            launch_date TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE episodes (
            episode_id INTEGER PRIMARY KEY,
            podcast_id INTEGER NOT NULL,
            episode_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            air_date TEXT NOT NULL,
            duration_seconds INTEGER NOT NULL,
            num_segments INTEGER NOT NULL,
            period TEXT NOT NULL,
            FOREIGN KEY (podcast_id) REFERENCES podcasts(podcast_id)
        )
    """)
    cur.execute("""
        CREATE TABLE listener_retention (
            episode_id INTEGER PRIMARY KEY,
            initial_listeners INTEGER NOT NULL,
            final_listeners INTEGER NOT NULL,
            retention_rate REAL NOT NULL,
            FOREIGN KEY (episode_id) REFERENCES episodes(episode_id)
        )
    """)
    cur.execute("""
        CREATE TABLE ad_placements (
            ad_id INTEGER PRIMARY KEY,
            episode_id INTEGER NOT NULL,
            ad_position_seconds INTEGER NOT NULL,
            ad_duration_seconds INTEGER NOT NULL,
            ad_type TEXT NOT NULL,
            advertiser TEXT NOT NULL,
            revenue_per_mille REAL NOT NULL,
            FOREIGN KEY (episode_id) REFERENCES episodes(episode_id)
        )
    """)
    cur.execute("""
        CREATE TABLE listener_demographics (
            demo_id INTEGER PRIMARY KEY,
            podcast_id INTEGER NOT NULL,
            period TEXT NOT NULL,
            age_group TEXT NOT NULL,
            listener_count INTEGER NOT NULL,
            FOREIGN KEY (podcast_id) REFERENCES podcasts(podcast_id)
        )
    """)
    cur.execute("""
        CREATE TABLE competitor_shows (
            competitor_id INTEGER PRIMARY KEY,
            genre TEXT NOT NULL,
            show_name TEXT NOT NULL,
            network TEXT NOT NULL,
            avg_retention_rate REAL NOT NULL,
            monthly_listeners INTEGER NOT NULL
        )
    """)

    cur.executemany(
        "INSERT INTO podcasts VALUES (?,?,?,?,?,?,?)",
        [(p["podcast_id"], p["name"], p["genre"], p["host"],
          p["network"], p["launch_date"], p["status"]) for p in podcasts],
    )
    cur.executemany(
        "INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?)",
        [(e["episode_id"], e["podcast_id"], e["episode_number"],
          e["title"], e["air_date"], e["duration_seconds"],
          e["num_segments"], e["period"]) for e in episodes],
    )
    cur.executemany(
        "INSERT INTO listener_retention VALUES (?,?,?,?)",
        [(r["episode_id"], r["initial_listeners"],
          r["final_listeners"], r["retention_rate"]) for r in retention],
    )
    cur.executemany(
        "INSERT INTO ad_placements VALUES (?,?,?,?,?,?,?)",
        [(a["ad_id"], a["episode_id"], a["ad_position_seconds"],
          a["ad_duration_seconds"], a["ad_type"], a["advertiser"],
          a["revenue_per_mille"]) for a in ad_rows],
    )
    cur.executemany(
        "INSERT INTO listener_demographics VALUES (?,?,?,?,?)",
        [(d["demo_id"], d["podcast_id"], d["period"],
          d["age_group"], d["listener_count"]) for d in demo_rows],
    )
    cur.executemany(
        "INSERT INTO competitor_shows VALUES (?,?,?,?,?,?)",
        [(c["competitor_id"], c["genre"], c["show_name"],
          c["network"], c["avg_retention_rate"],
          c["monthly_listeners"]) for c in comp_rows],
    )
    conn.commit()
    conn.close()

    # ------------------------------------------------------------------
    # 9. Workspace – fixed config files
    # ------------------------------------------------------------------
    # retention_config.yaml
    import yaml
    config = {
        "baseline_period": BASELINE_PERIOD,
        "current_period": CURRENT_PERIOD,
        "retention_drop_threshold_pct": 15.0,
        "demographic_shift_threshold_pct": 10.0,
        "max_revision_segments_per_podcast": 3,
        "priority_weights": {
            "retention_drop": 0.35,
            "competitor_gap": 0.25,
            "demographic_shift": 0.20,
            "ad_revenue_impact": 0.20,
        },
    }
    with open(os.path.join(workspace, "retention_config.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    # scoring_rubric.json
    rubric = {
        "normalization": {
            "retention_drop_pct": {"min": 15.0, "max": 50.0},
            "competitor_gap": {"min": 0.0, "max": 0.40},
            "demographic_shift_pct": {"min": 0.0, "max": 50.0},
            "ad_revenue_impact": {"min": 0.0, "max": 1.0},
        },
        "output_format": {
            "file_name": "priority_report.csv",
            "columns": [
                "podcast_name", "genre", "retention_drop_pct",
                "priority_score", "flagged_episode_count",
                "top_revision_segments", "demographic_shift_flag",
            ],
            "sort_by": "priority_score",
            "sort_order": "descending",
            "tie_breaker": "retention_drop_pct",
            "decimal_places": 2,
        },
    }
    with open(os.path.join(workspace, "scoring_rubric.json"), "w") as f:
        json.dump(rubric, f, indent=2)

    # audit_methodology.md — authoritative definition of every audit metric
    methodology_md = """# Retention Audit Methodology

## Flagging

For every podcast, compute the average episode retention rate separately for the
baseline period and the current period (periods are named in the retention
configuration). The retention drop percentage equals the baseline average minus
the current average, divided by the baseline average, multiplied by 100. A
podcast is flagged for review when its retention drop percentage exceeds the
retention drop threshold in the configuration.

## Metrics for flagged podcasts

Competitor gap: the average retention rate across all competitor shows in the
podcast's genre, minus the podcast's current-period average retention, floored
at zero.

Demographic shift: for the current period, compute each age group's fraction of
the podcast's total listeners, take the absolute difference against the
corresponding genre baseline fraction from the demographic baseline table, sum
across age groups, and multiply by 100 to express it in percentage points. The
demographic shift flag is "yes" when this value exceeds the demographic shift
threshold in the configuration, otherwise "no".

Ad revenue impact: for each episode in a period, each ad placement contributes
revenue equal to its revenue-per-mille times the genre's ad-rate adjustment
multiplier times the episode's initial listener count divided by 1000. Average
the per-episode totals within the baseline period and within the current
period. The impact equals the baseline average minus the current average,
divided by the baseline average, clamped to the range 0 to 1.

## Priority score

Normalize each of the four metrics (retention drop percentage, competitor gap,
demographic shift percentage, ad revenue impact) into the 0-1 range using the
min and max bounds in the scoring rubric, clamping values outside the bounds.
The priority score is the weighted sum of the four normalized metrics using the
weights in the retention configuration, multiplied by 100 and rounded to two
decimal places.

## Revision segments

Segment-level listener counts are recorded in the segment batch files. For each
flagged podcast, consider only its current-period episodes. A segment's drop
rate equals its starting listener count minus its ending listener count,
divided by its starting listener count. Rank all such segments across the
podcast's current-period episodes by drop rate in descending order and keep the
top segments up to the per-podcast maximum in the configuration. Format each
selected segment as the episode number prefixed by "Ep", a colon, the segment
index prefixed by "Seg", a hyphen, and the content type — for example
"Ep4:Seg2-interview" — and join multiple segments with "; ".
"""
    with open(os.path.join(workspace, "audit_methodology.md"), "w") as f:
        f.write(methodology_md)

    # demographic_baseline.csv  (per-genre ideal distribution)
    demo_baseline_rows = []
    demo_baseline_map = {}
    for genre in GENRES:
        # Standard baseline
        baseline_pcts = [0.20, 0.28, 0.24, 0.16, 0.12]
        for j, ag in enumerate(AGE_GROUPS):
            demo_baseline_rows.append({
                "genre": genre,
                "age_group": ag,
                "baseline_pct": baseline_pcts[j],
            })
            demo_baseline_map[(genre, ag)] = baseline_pcts[j]
    with open(os.path.join(workspace, "demographic_baseline.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["genre", "age_group", "baseline_pct"])
        writer.writeheader()
        writer.writerows(demo_baseline_rows)

    # ad_rate_adjustments.json  (per-genre CPM multipliers)
    rate_adj = {}
    for i, genre in enumerate(GENRES):
        rate_adj[genre] = round(0.8 + 0.05 * i, 2)
    with open(os.path.join(workspace, "ad_rate_adjustments.json"), "w") as f:
        json.dump(rate_adj, f, indent=2)

    # ------------------------------------------------------------------
    # 10. Workspace – scalable segment files
    # ------------------------------------------------------------------
    # Build a retention lookup
    ret_map = {r["episode_id"]: r for r in retention}

    all_segments = []
    for ep in episodes:
        r = ret_map[ep["episode_id"]]
        is_declining_current = (
            ep["podcast_id"] in declining_ids and ep["period"] == CURRENT_PERIOD
        )
        boundaries = make_segment_boundaries(
            r["initial_listeners"],
            r["final_listeners"],
            ep["num_segments"],
            rng,
            concentrated=is_declining_current,
        )
        seg_dur = ep["duration_seconds"] // ep["num_segments"]
        for si in range(ep["num_segments"]):
            start_sec = si * seg_dur
            end_sec = (si + 1) * seg_dur if si < ep["num_segments"] - 1 else ep["duration_seconds"]
            all_segments.append({
                "podcast_id": ep["podcast_id"],
                "podcast_name": ep["podcast_name"],
                "episode_id": ep["episode_id"],
                "episode_number": ep["episode_number"],
                "segment_index": si + 1,
                "segment_topic": str(rng.choice(SEGMENT_TOPICS)),
                "content_type": str(rng.choice(CONTENT_TYPES)),
                "segment_start_sec": start_sec,
                "segment_end_sec": end_sec,
                "listeners_at_start": boundaries[si],
                "listeners_at_end": boundaries[si + 1],
            })

    # Split into batches by podcast_id
    podcasts_per_batch = math.ceil(num_podcasts / n_ws_files)
    seg_fields = [
        "podcast_id", "podcast_name", "episode_id", "episode_number",
        "segment_index", "segment_topic", "content_type",
        "segment_start_sec", "segment_end_sec",
        "listeners_at_start", "listeners_at_end",
    ]
    for batch_idx in range(n_ws_files):
        lo = batch_idx * podcasts_per_batch + 1
        hi = lo + podcasts_per_batch
        batch = [s for s in all_segments if lo <= s["podcast_id"] < hi]
        fname = f"episode_segments_batch_{batch_idx + 1:02d}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=seg_fields)
            writer.writeheader()
            writer.writerows(batch)

    print(f"Database written to {db_path}")
    print(f"Workspace files written to {workspace}/")
    print(f"  - {n_ws_files} segment batch files")
    print(f"  - 4 config files")
    print(f"  - {num_podcasts} podcasts, {len(episodes)} episodes")
    print(f"  - {num_declining} podcasts selected for declining retention")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
