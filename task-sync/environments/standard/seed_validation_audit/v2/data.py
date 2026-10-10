#!/usr/bin/env python3
"""Data generation for tournament seeding error detection task."""
import argparse
import sqlite3
import os
import json
import math
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 320,
    "num_workspace_files": 24,
}

REGIONS = ["North America", "Europe", "Asia", "South America", "Africa", "Oceania"]
SURFACES = ["hard", "clay", "grass", "carpet"]
TOURNAMENT_SURFACE = "hard"


def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS players (
        player_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        country TEXT NOT NULL,
        region TEXT NOT NULL,
        seed_number INTEGER DEFAULT 0,
        ranking_points INTEGER NOT NULL,
        age INTEGER NOT NULL,
        is_seeded INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS head_to_head (
        h2h_id INTEGER PRIMARY KEY AUTOINCREMENT,
        player1_id INTEGER NOT NULL,
        player2_id INTEGER NOT NULL,
        player1_wins INTEGER NOT NULL,
        player2_wins INTEGER NOT NULL,
        total_matches INTEGER NOT NULL,
        last_match_date TEXT,
        FOREIGN KEY (player1_id) REFERENCES players(player_id),
        FOREIGN KEY (player2_id) REFERENCES players(player_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS qualifier_results (
        result_id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        round_num INTEGER NOT NULL,
        score INTEGER NOT NULL,
        opponent_score INTEGER NOT NULL,
        performance_rating REAL NOT NULL,
        duration_minutes INTEGER NOT NULL,
        aces INTEGER DEFAULT 0,
        double_faults INTEGER DEFAULT 0,
        win INTEGER NOT NULL,
        FOREIGN KEY (player_id) REFERENCES players(player_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS bracket_matches (
        match_id INTEGER PRIMARY KEY AUTOINCREMENT,
        round_number INTEGER NOT NULL,
        match_position INTEGER NOT NULL,
        player1_id INTEGER NOT NULL,
        player2_id INTEGER NOT NULL,
        player1_seed INTEGER DEFAULT 0,
        player2_seed INTEGER DEFAULT 0,
        winner_id INTEGER,
        score TEXT,
        status TEXT DEFAULT 'scheduled',
        FOREIGN KEY (player1_id) REFERENCES players(player_id),
        FOREIGN KEY (player2_id) REFERENCES players(player_id)
    )""")
    conn.commit()


def gen_match_score():
    """Generate a realistic tennis-like match score string."""
    sets = []
    for _ in range(np.random.choice([2, 3], p=[0.6, 0.4])):
        w = int(np.random.randint(6, 8))
        l = int(np.random.randint(0, min(w, 6)))
        sets.append(f"{w}-{l}")
    return ", ".join(sets)


def generate_bracket(ordered_players, seed_map, target_count):
    """Generate single-elimination bracket matches + consolation to hit target."""
    matches = []
    current = list(ordered_players)
    round_num = 1
    all_losers = []

    while len(current) > 1:
        next_round = []
        n = len(current)
        pairs = []

        if n % 2 == 1:
            next_round.append(current[0])
            matchable = current[1:]
        else:
            matchable = current

        nm = len(matchable)
        if round_num == 1:
            for i in range(nm // 2):
                pairs.append((matchable[i], matchable[nm - 1 - i]))
        else:
            for i in range(0, nm, 2):
                if i + 1 < nm:
                    pairs.append((matchable[i], matchable[i + 1]))
                else:
                    next_round.append(matchable[i])

        for pos, (p1, p2) in enumerate(pairs):
            r1 = p1["ranking_points"]
            r2 = p2["ranking_points"]
            win_prob = r1 / (r1 + r2 + 1)
            if np.random.random() < win_prob:
                winner, loser = p1, p2
            else:
                winner, loser = p2, p1

            matches.append({
                "round_number": round_num,
                "match_position": pos + 1,
                "player1_id": p1["player_id"],
                "player2_id": p2["player_id"],
                "player1_seed": seed_map.get(p1["player_id"], 0),
                "player2_seed": seed_map.get(p2["player_id"], 0),
                "winner_id": winner["player_id"],
                "score": gen_match_score(),
                "status": "completed",
            })
            next_round.append(winner)
            all_losers.append(loser)

        current = next_round
        round_num += 1

    # Add consolation matches to reach target_count
    lidx = 0
    while len(matches) < target_count and lidx + 1 < len(all_losers):
        p1 = all_losers[lidx]
        p2 = all_losers[lidx + 1]
        winner = p1 if np.random.random() < 0.5 else p2
        matches.append({
            "round_number": 0,
            "match_position": len(matches) + 1,
            "player1_id": p1["player_id"],
            "player2_id": p2["player_id"],
            "player1_seed": seed_map.get(p1["player_id"], 0),
            "player2_seed": seed_map.get(p2["player_id"], 0),
            "winner_id": winner["player_id"],
            "score": gen_match_score(),
            "status": "completed",
        })
        lidx += 2

    return matches


def main(db_path, workspace):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)
    os.makedirs(workspace, exist_ok=True)

    N = SCALE["rows_per_table"]
    F = SCALE["num_workspace_files"]
    # Distribute F across 3 scaling file types: CSV, JSON, TXT
    files_per_type = [F // 3 + (1 if i < F % 3 else 0) for i in range(3)]

    conn = sqlite3.connect(db_path)
    create_tables(conn)

    # ── 1. Generate players ──────────────────────────────────────────────
    players = []
    for i in range(1, N + 1):
        players.append({
            "player_id": i,
            "name": fake.unique.name(),
            "country": fake.country(),
            "region": REGIONS[(i - 1) % len(REGIONS)],
            "ranking_points": max(200, min(3000, int(np.random.normal(1500, 400)))),
            "age": int(np.random.randint(18, 38)),
            "seed_number": 0,
            "is_seeded": 0,
        })

    # Assign seeds to top players by ranking_points
    by_rank = sorted(players, key=lambda x: -x["ranking_points"])
    num_seeded = min(32, N // 2)
    seed_map = {}
    for idx, p in enumerate(by_rank):
        if idx < num_seeded:
            p["seed_number"] = idx + 1
            p["is_seeded"] = 1
            seed_map[p["player_id"]] = idx + 1

    c = conn.cursor()
    for p in players:
        c.execute(
            "INSERT INTO players VALUES (?,?,?,?,?,?,?,?)",
            (p["player_id"], p["name"], p["country"], p["region"],
             p["seed_number"], p["ranking_points"], p["age"], p["is_seeded"]),
        )
    conn.commit()
    player_map = {p["player_id"]: p for p in players}

    # ── 2. Generate bracket ──────────────────────────────────────────────
    bracket_matches = generate_bracket(by_rank, seed_map, N)
    c = conn.cursor()
    for m in bracket_matches:
        c.execute(
            "INSERT INTO bracket_matches "
            "(round_number, match_position, player1_id, player2_id, "
            "player1_seed, player2_seed, winner_id, score, status) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (m["round_number"], m["match_position"], m["player1_id"],
             m["player2_id"], m["player1_seed"], m["player2_seed"],
             m["winner_id"], m["score"], m["status"]),
        )
    conn.commit()

    # Collect bracket pairs for H2H generation
    bracket_pairs = set()
    for m in bracket_matches:
        bracket_pairs.add((min(m["player1_id"], m["player2_id"]),
                           max(m["player1_id"], m["player2_id"])))

    # Identify bracket pairs with at least one seeded player (for H2H flag targets)
    seeded_bracket_pairs = []
    for m in bracket_matches:
        if m["player1_seed"] > 0 or m["player2_seed"] > 0:
            key = (min(m["player1_id"], m["player2_id"]),
                   max(m["player1_id"], m["player2_id"]))
            seeded_bracket_pairs.append((key, m))
    seen_pairs = set()
    unique_seeded = []
    for key, m in seeded_bracket_pairs:
        if key not in seen_pairs:
            seen_pairs.add(key)
            unique_seeded.append((key, m))

    # Pick pairs for deliberate H2H surface dominance flags
    num_h2h_flags = max(3, len(unique_seeded) // 6)
    h2h_flag_indices = np.random.choice(
        len(unique_seeded), size=min(num_h2h_flags, len(unique_seeded)), replace=False
    )
    h2h_flag_pair_set = set()
    for idx in h2h_flag_indices:
        h2h_flag_pair_set.add(unique_seeded[int(idx)][0])

    # ── 3. Generate H2H records ──────────────────────────────────────────
    h2h_records = []
    surface_h2h_data = []
    generated_pairs = set()

    def make_h2h(p1_id, p2_id, force_flag=False):
        """Create H2H record + surface breakdown for a pair."""
        key = (min(p1_id, p2_id), max(p1_id, p2_id))
        if key in generated_pairs:
            return
        generated_pairs.add(key)

        pa = player_map[key[0]]
        pb = player_map[key[1]]

        if force_flag:
            total = int(np.random.randint(4, 10))
        else:
            total = int(np.random.randint(1, 10))

        ra = pa["ranking_points"]
        rb = pb["ranking_points"]
        a_wins = int(np.random.binomial(total, ra / (ra + rb + 1)))
        b_wins = total - a_wins

        year = int(np.random.randint(2020, 2026))
        month = int(np.random.randint(1, 13))
        h2h_records.append({
            "player1_id": key[0],
            "player2_id": key[1],
            "player1_wins": a_wins,
            "player2_wins": b_wins,
            "total_matches": total,
            "last_match_date": f"{year}-{month:02d}-01",
        })

        # Surface breakdown
        remaining_a = a_wins
        remaining_b = b_wins
        surfaces_shuffled = list(np.random.permutation(SURFACES))

        if force_flag:
            # Determine which player is lower-seeded in this bracket pair
            seed_a = seed_map.get(key[0], 999)
            seed_b = seed_map.get(key[1], 999)
            lower_seed_is_a = seed_a > seed_b

            # Put tournament surface first
            if TOURNAMENT_SURFACE in surfaces_shuffled:
                ti = surfaces_shuffled.index(TOURNAMENT_SURFACE)
                surfaces_shuffled[0], surfaces_shuffled[ti] = \
                    surfaces_shuffled[ti], surfaces_shuffled[0]

            # Allocate at least 3 matches on tournament surface, biased to lower seed
            surf_total = min(total, max(3, total // 2 + 1))
            if lower_seed_is_a:
                surf_a = int(np.random.binomial(surf_total, 0.82))
                surf_b = surf_total - surf_a
            else:
                surf_b = int(np.random.binomial(surf_total, 0.82))
                surf_a = surf_total - surf_b

            surface_h2h_data.append({
                "player1_id": key[0], "player2_id": key[1],
                "surface": TOURNAMENT_SURFACE,
                "p1_wins": max(0, surf_a), "p2_wins": max(0, surf_b),
            })
            remaining_a = max(0, remaining_a - surf_a)
            remaining_b = max(0, remaining_b - surf_b)
            start_idx = 1
        else:
            start_idx = 0

        for surf in surfaces_shuffled[start_idx:]:
            if remaining_a + remaining_b <= 0:
                break
            pool = remaining_a + remaining_b
            alloc = int(np.random.randint(0, pool + 1))
            if alloc == 0:
                continue
            sa = min(remaining_a, int(np.random.binomial(
                alloc, remaining_a / pool if pool > 0 else 0.5)))
            sb = alloc - sa
            sb = min(remaining_b, sb)
            sa = alloc - sb
            if sa + sb > 0:
                surface_h2h_data.append({
                    "player1_id": key[0], "player2_id": key[1],
                    "surface": surf, "p1_wins": max(0, sa), "p2_wins": max(0, sb),
                })
            remaining_a = max(0, remaining_a - sa)
            remaining_b = max(0, remaining_b - sb)

        # Remaining to a random surface
        if remaining_a + remaining_b > 0:
            surf = str(np.random.choice(SURFACES))
            found = False
            for rec in surface_h2h_data:
                if (rec["player1_id"] == key[0] and rec["player2_id"] == key[1]
                        and rec["surface"] == surf):
                    rec["p1_wins"] += remaining_a
                    rec["p2_wins"] += remaining_b
                    found = True
                    break
            if not found and remaining_a + remaining_b > 0:
                surface_h2h_data.append({
                    "player1_id": key[0], "player2_id": key[1],
                    "surface": surf, "p1_wins": remaining_a, "p2_wins": remaining_b,
                })

    # H2H for all bracket pairs
    for pair_key in bracket_pairs:
        is_flag = pair_key in h2h_flag_pair_set
        make_h2h(pair_key[0], pair_key[1], force_flag=is_flag)

    # Add random extra pairs to fill table
    all_ids = [p["player_id"] for p in players]
    attempts = 0
    while len(h2h_records) < N and attempts < N * 10:
        attempts += 1
        a = int(np.random.choice(all_ids))
        b = int(np.random.choice(all_ids))
        if a == b:
            continue
        key = (min(a, b), max(a, b))
        if key in generated_pairs:
            continue
        make_h2h(a, b)

    c = conn.cursor()
    for h in h2h_records:
        c.execute(
            "INSERT INTO head_to_head "
            "(player1_id, player2_id, player1_wins, player2_wins, "
            "total_matches, last_match_date) VALUES (?,?,?,?,?,?)",
            (h["player1_id"], h["player2_id"], h["player1_wins"],
             h["player2_wins"], h["total_matches"], h["last_match_date"]),
        )
    conn.commit()

    # ── 4. Qualifier results ─────────────────────────────────────────────
    qual_results = []
    num_rounds = 3
    for p in players:
        base_skill = 50.0 + (p["ranking_points"] - 1000) / 40.0
        # Per-player qualifier aptitude variation: some strong players
        # are poor qualifiers (adds noise independent of ranking)
        qualifier_adjust = float(np.random.normal(0, 15))
        effective_skill = base_skill + qualifier_adjust
        for r in range(1, num_rounds + 1):
            perf = max(10.0, min(100.0, effective_skill + float(np.random.normal(0, 12))))
            score = int(np.random.randint(40, 100))
            opp = int(np.random.randint(20, max(21, score)))
            qual_results.append({
                "player_id": p["player_id"],
                "round_num": r,
                "score": score,
                "opponent_score": opp,
                "performance_rating": round(perf, 1),
                "duration_minutes": int(np.random.randint(45, 180)),
                "aces": int(np.random.randint(0, 20)),
                "double_faults": int(np.random.randint(0, 10)),
                "win": 1 if score > opp else 0,
            })

    c = conn.cursor()
    for q in qual_results:
        c.execute(
            "INSERT INTO qualifier_results "
            "(player_id, round_num, score, opponent_score, performance_rating, "
            "duration_minutes, aces, double_faults, win) VALUES (?,?,?,?,?,?,?,?,?)",
            (q["player_id"], q["round_num"], q["score"], q["opponent_score"],
             q["performance_rating"], q["duration_minutes"], q["aces"],
             q["double_faults"], q["win"]),
        )
    conn.commit()

    # ── 5. Workspace-only data ───────────────────────────────────────────

    # 5a. Regional data with power_index
    seeded_pids = [p["player_id"] for p in players if p["is_seeded"]]
    num_rank_errors = max(3, len(seeded_pids) // 7)
    error_pids = set(
        int(x) for x in np.random.choice(seeded_pids, size=num_rank_errors, replace=False)
    )

    regional_data = []
    for p in players:
        noise = float(np.random.normal(0, 50))
        if p["player_id"] in error_pids:
            noise += float(np.random.choice([-1, 1])) * float(np.random.uniform(400, 700))
        power_index = max(100, int(p["ranking_points"] + noise))
        regional_data.append({
            "player_id": p["player_id"],
            "name": p["name"],
            "region": p["region"],
            "power_index": power_index,
        })

    # Compute regional_rank within each region
    by_region = {}
    for rd in regional_data:
        by_region.setdefault(rd["region"], []).append(rd)
    for region, entries in by_region.items():
        entries.sort(key=lambda x: -x["power_index"])
        for i, e in enumerate(entries):
            e["regional_rank"] = i + 1
            e["regional_points"] = e["power_index"]

    # 5b. Qualifier details with form_trend
    qualifier_details = []
    for p in players:
        p_quals = sorted(
            [q for q in qual_results if q["player_id"] == p["player_id"]],
            key=lambda x: x["round_num"],
        )
        if len(p_quals) >= 2:
            ratings = [q["performance_rating"] for q in p_quals]
            trend = ratings[-1] - ratings[0]
        else:
            trend = 0.0
        form_trend = round(trend + float(np.random.normal(0, 3)), 1)
        if len(p_quals) > 1:
            consistency = round(
                100.0 - float(np.std([q["performance_rating"] for q in p_quals])), 1
            )
        else:
            consistency = 80.0
        qualifier_details.append({
            "player_id": p["player_id"],
            "form_trend": form_trend,
            "consistency_score": max(0.0, min(100.0, consistency)),
            "clutch_rating": round(float(np.random.uniform(3, 10)), 1),
        })

    conn.close()

    # ── 6. Write workspace files ─────────────────────────────────────────

    # Fixed files
    import yaml

    seeding_rules = {
        "flag_rules": {
            "rank_seed_mismatch": {
                "description": (
                    "Flag when a seeded player's power-index rank among all seeded "
                    "players differs significantly from their actual seed number"
                ),
                "max_rank_seed_diff": 5,
                "severity": {
                    "high_threshold": 10,
                    "note": "diff > high_threshold -> high; diff > max_rank_seed_diff -> medium",
                },
            },
            "h2h_surface_dominance": {
                "description": (
                    "Flag when the lower-seeded player in a bracket match has a "
                    "dominant win rate on the tournament surface"
                ),
                "min_surface_matches": 2,
                "min_total_matches": 3,
                "dominance_win_rate": 0.70,
                "severity": {
                    "high_threshold": 0.85,
                    "note": "win_rate >= high_threshold -> high; "
                            "win_rate >= dominance_win_rate -> medium",
                },
            },
            "qualifier_form_concern": {
                "description": (
                    "Flag when a seeded player's average qualifier performance is "
                    "below their tier threshold AND their form trend is declining"
                ),
                "seed_tiers": {"tier_1": 8, "tier_2": 16, "tier_3": 32},
                "min_avg_performance": {
                    "tier_1": 80.0,
                    "tier_2": 70.0,
                    "tier_3": 60.0,
                },
                "form_trend_threshold": -3.0,
                "severity_by_tier": {
                    "tier_1": "high",
                    "tier_2": "medium",
                    "tier_3": "low",
                },
            },
        },
        "output_format": {
            "file_name": "flagged_matches.csv",
            "columns": [
                "match_id", "round", "player1_id", "player1_name",
                "player2_id", "player2_name", "flag_type", "severity", "details",
            ],
            "sort_order": [
                "severity descending (high > medium > low)",
                "round ascending",
                "match_id ascending",
            ],
        },
    }

    with open(os.path.join(workspace, "seeding_rules.yaml"), "w") as f:
        yaml.dump(seeding_rules, f, default_flow_style=False, sort_keys=False)

    tournament_info = {
        "tournament_name": "Global Championship 2026",
        "surface": TOURNAMENT_SURFACE,
        "location": "Melbourne, Australia",
        "start_date": "2026-03-15",
        "end_date": "2026-03-29",
    }
    with open(os.path.join(workspace, "tournament_info.json"), "w") as f:
        json.dump(tournament_info, f, indent=2)

    # Scaling files
    all_regional = list(regional_data)
    # Use a fixed shuffle based on player_id for reproducibility
    all_regional.sort(key=lambda x: x["player_id"])

    n_csv = files_per_type[0]
    n_json = files_per_type[1]
    n_txt = files_per_type[2]

    # CSV: regional data batches
    batch_size_csv = math.ceil(len(all_regional) / n_csv)
    for i in range(n_csv):
        batch = all_regional[i * batch_size_csv: (i + 1) * batch_size_csv]
        df = pd.DataFrame(batch)[["player_id", "name", "region", "regional_rank",
                                   "regional_points", "power_index"]]
        df.to_csv(os.path.join(workspace, f"regional_data_{i + 1}.csv"), index=False)

    # JSON: qualifier details batches
    all_qd = sorted(qualifier_details, key=lambda x: x["player_id"])
    batch_size_json = math.ceil(len(all_qd) / n_json)
    for i in range(n_json):
        batch = all_qd[i * batch_size_json: (i + 1) * batch_size_json]
        with open(os.path.join(workspace, f"qualifier_detail_{i + 1}.json"), "w") as f:
            json.dump(batch, f, indent=2)

    # TXT: surface H2H batches
    all_sh2h = sorted(surface_h2h_data,
                      key=lambda x: (x["player1_id"], x["player2_id"], x["surface"]))
    batch_size_txt = max(1, math.ceil(len(all_sh2h) / max(1, n_txt)))
    for i in range(n_txt):
        batch = all_sh2h[i * batch_size_txt: (i + 1) * batch_size_txt]
        with open(os.path.join(workspace, f"surface_h2h_{i + 1}.txt"), "w") as f:
            f.write("PLAYER1_ID|PLAYER2_ID|SURFACE|P1_WINS|P2_WINS\n")
            for rec in batch:
                f.write(
                    f"{rec['player1_id']}|{rec['player2_id']}|"
                    f"{rec['surface']}|{rec['p1_wins']}|{rec['p2_wins']}\n"
                )

    print(f"Generated {len(players)} players ({num_seeded} seeded)")
    print(f"Generated {len(h2h_records)} H2H records, "
          f"{len(surface_h2h_data)} surface H2H records")
    print(f"Generated {len(qual_results)} qualifier results")
    print(f"Generated {len(bracket_matches)} bracket matches")
    print(f"Workspace: {n_csv} CSV + {n_json} JSON + {n_txt} TXT "
          f"scaling files + 2 fixed files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
