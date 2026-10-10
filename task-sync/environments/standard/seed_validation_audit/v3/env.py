#!/usr/bin/env python3
"""Environment for tournament seeding error detection task."""
import sqlite3
import os
import json
import csv
import glob
import math
from typing import Tuple, Dict, List, Any


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
        }
        return func
    return decorator


class Task_Env:
    def __init__(self, db_path: str, workspace: str):
        """
        Init env.
        Args:
            db_path: Path to the database file.
            workspace: Path to workspace directory for file isolation.
        """
        self.db_path = db_path
        self.workspace = workspace

        # Auto-collect all @tool decorated methods
        self.tools = {}
        for name in dir(self):
            method = getattr(self, name, None)
            if callable(method) and hasattr(method, "_tool_info"):
                self.tools[name] = method

    # --- keep this implementation unchanged ---
    def get_assistant_tools(self) -> List[Dict[str, Any]]:
        """
        Get tool definitions in OpenAI function calling format.

        Returns:
            List of tool definitions compatible with OpenAI API
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": method._tool_info["description"],
                    "parameters": method._tool_info["parameters"],
                },
            }
            for name, method in self.tools.items()
        ]

    # ── Tool methods ─────────────────────────────────────────────────────

    @tool(
        description="List all distinct round numbers in the bracket.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_bracket_rounds(self) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT DISTINCT round_number FROM bracket_matches ORDER BY round_number")
        rounds = [r[0] for r in c.fetchall()]
        conn.close()
        return {"rounds": rounds}

    @tool(
        description=(
            "Get bracket matches for a specific round with pagination. "
            "Returns match_id, round_number, match_position, player1_id, player2_id, "
            "player1_seed, player2_seed, winner_id, score, status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "round_number": {
                    "type": "integer",
                    "description": "The round number to query",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Default 20.",
                },
            },
            "required": ["round_number"],
        },
    )
    def get_bracket_matches(self, round_number: int,
                            page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        offset = (page - 1) * page_size
        c.execute(
            "SELECT * FROM bracket_matches WHERE round_number = ? "
            "ORDER BY match_id LIMIT ? OFFSET ?",
            (round_number, page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        c.execute(
            "SELECT COUNT(*) FROM bracket_matches WHERE round_number = ?",
            (round_number,),
        )
        total = c.fetchone()[0]
        conn.close()
        return {
            "matches": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }

    @tool(
        description=(
            "Get detailed information about a single player by ID. "
            "Returns player_id, name, country, region, seed_number, "
            "ranking_points, age, is_seeded."
        ),
        parameters={
            "type": "object",
            "properties": {
                "player_id": {
                    "type": "integer",
                    "description": "The player's unique ID",
                },
            },
            "required": ["player_id"],
        },
    )
    def get_player_info(self, player_id: int) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM players WHERE player_id = ?", (player_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Player {player_id} not found"}
        return dict(row)

    @tool(
        description=(
            "Get the overall head-to-head record between two players. "
            "Returns player1_id, player2_id, player1_wins, player2_wins, "
            "total_matches, last_match_date. Returns null if no record exists."
        ),
        parameters={
            "type": "object",
            "properties": {
                "player1_id": {
                    "type": "integer",
                    "description": "First player's ID",
                },
                "player2_id": {
                    "type": "integer",
                    "description": "Second player's ID",
                },
            },
            "required": ["player1_id", "player2_id"],
        },
    )
    def get_head_to_head(self, player1_id: int,
                         player2_id: int) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        lo, hi = min(player1_id, player2_id), max(player1_id, player2_id)
        c.execute(
            "SELECT * FROM head_to_head "
            "WHERE player1_id = ? AND player2_id = ?",
            (lo, hi),
        )
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"record": None}
        rec = dict(row)
        # Flip perspective if queried in reverse order
        if player1_id > player2_id:
            rec["player1_id"], rec["player2_id"] = player2_id, player1_id
            rec["player1_wins"], rec["player2_wins"] = rec["player2_wins"], rec["player1_wins"]
        return {"record": rec}

    @tool(
        description=(
            "Get qualifier round results for a specific player. "
            "Returns a list of qualifier round records with round_num, score, "
            "opponent_score, performance_rating, duration_minutes, aces, "
            "double_faults, win."
        ),
        parameters={
            "type": "object",
            "properties": {
                "player_id": {
                    "type": "integer",
                    "description": "The player's ID",
                },
            },
            "required": ["player_id"],
        },
    )
    def get_qualifier_performance(self, player_id: int) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT round_num, score, opponent_score, performance_rating, "
            "duration_minutes, aces, double_faults, win "
            "FROM qualifier_results WHERE player_id = ? ORDER BY round_num",
            (player_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"player_id": player_id, "results": rows}

    # ── Evaluation helpers ───────────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute ground-truth flagged matches using the same logic as verify."""
        import yaml

        # Read config
        with open(os.path.join(self.workspace, "seeding_rules.yaml")) as f:
            rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "tournament_info.json")) as f:
            tourney = json.load(f)
        tournament_surface = tourney["surface"]
        fr = rules["flag_rules"]

        # Read all regional data
        power_index_map = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "regional_data_*.csv"))):
            import pandas as pd
            df = pd.read_csv(fp)
            for _, row in df.iterrows():
                power_index_map[int(row["player_id"])] = float(row["power_index"])

        # Read all qualifier details
        form_trend_map = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "qualifier_detail_*.json"))):
            with open(fp) as f:
                for item in json.load(f):
                    form_trend_map[int(item["player_id"])] = float(item["form_trend"])

        # Read all surface H2H
        surface_h2h = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "surface_h2h_*.txt"))):
            with open(fp) as f:
                header = f.readline()
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("|")
                    p1 = int(parts[0])
                    p2 = int(parts[1])
                    surf = parts[2].strip()
                    w1 = int(parts[3])
                    w2 = int(parts[4])
                    key = (min(p1, p2), max(p1, p2), surf)
                    if key not in surface_h2h:
                        surface_h2h[key] = {"p1_wins": 0, "p2_wins": 0}
                    if p1 < p2:
                        surface_h2h[key]["p1_wins"] += w1
                        surface_h2h[key]["p2_wins"] += w2
                    else:
                        surface_h2h[key]["p1_wins"] += w2
                        surface_h2h[key]["p2_wins"] += w1

        # Get all players and seeds from DB
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT * FROM players")
        all_players = {r["player_id"]: dict(r) for r in c.fetchall()}

        # Compute power_rank among seeded players
        seeded = [(pid, pinfo) for pid, pinfo in all_players.items()
                  if pinfo["seed_number"] > 0]
        seeded_with_pi = [(pid, power_index_map.get(pid, 0)) for pid, _ in seeded]
        seeded_with_pi.sort(key=lambda x: -x[1])
        power_rank = {pid: rank + 1 for rank, (pid, _) in enumerate(seeded_with_pi)}

        # Get all bracket matches
        c.execute("SELECT * FROM bracket_matches ORDER BY match_id")
        all_matches = [dict(r) for r in c.fetchall()]

        # Get H2H records
        c.execute("SELECT * FROM head_to_head")
        h2h_db = {}
        for r in c.fetchall():
            r = dict(r)
            key = (min(r["player1_id"], r["player2_id"]),
                   max(r["player1_id"], r["player2_id"]))
            h2h_db[key] = r

        # Get qualifier averages
        c.execute(
            "SELECT player_id, AVG(performance_rating) as avg_rating "
            "FROM qualifier_results GROUP BY player_id"
        )
        qual_avg = {r["player_id"]: r["avg_rating"] for r in c.fetchall()}
        conn.close()

        # Flag evaluation
        rsm_cfg = fr["rank_seed_mismatch"]
        h2h_cfg = fr["h2h_surface_dominance"]
        qfc_cfg = fr["qualifier_form_concern"]

        flags = []

        for m in all_matches:
            mid = m["match_id"]
            rnd = m["round_number"]
            p1id = m["player1_id"]
            p2id = m["player2_id"]
            p1s = m["player1_seed"]
            p2s = m["player2_seed"]
            p1 = all_players[p1id]
            p2 = all_players[p2id]

            # ── RANK_SEED_MISMATCH ──
            for pid, seed in [(p1id, p1s), (p2id, p2s)]:
                if seed > 0 and pid in power_rank:
                    diff = abs(seed - power_rank[pid])
                    if diff > rsm_cfg["max_rank_seed_diff"]:
                        if diff > rsm_cfg["severity"]["high_threshold"]:
                            sev = "high"
                        else:
                            sev = "medium"
                        pname = all_players[pid]["name"]
                        detail = (
                            f"Player {pname} (ID:{pid}) seed={seed} "
                            f"but power_rank={power_rank[pid]}, diff={diff}"
                        )
                        flags.append({
                            "match_id": mid, "round": rnd,
                            "player1_id": p1id,
                            "player1_name": p1["name"],
                            "player2_id": p2id,
                            "player2_name": p2["name"],
                            "flag_type": "RANK_SEED_MISMATCH",
                            "severity": sev, "details": detail,
                        })
                        break  # one flag per match per type

            # ── H2H_SURFACE_DOMINANCE ──
            if p1s > 0 or p2s > 0:
                lo, hi = min(p1id, p2id), max(p1id, p2id)
                h2h_key = (lo, hi)
                h2h_rec = h2h_db.get(h2h_key)
                surf_key = (lo, hi, tournament_surface)
                surf_rec = surface_h2h.get(surf_key)

                if h2h_rec and surf_rec:
                    total_matches = h2h_rec["total_matches"]
                    surf_total = surf_rec["p1_wins"] + surf_rec["p2_wins"]

                    if (total_matches >= h2h_cfg["min_total_matches"]
                            and surf_total >= h2h_cfg["min_surface_matches"]):
                        # Determine higher/lower seed
                        eff_s1 = p1s if p1s > 0 else 9999
                        eff_s2 = p2s if p2s > 0 else 9999
                        if eff_s1 < eff_s2:
                            higher_id, lower_id = p1id, p2id
                        else:
                            higher_id, lower_id = p2id, p1id

                        # Lower seed's wins on this surface
                        if lower_id == lo:
                            lower_surf_wins = surf_rec["p1_wins"]
                        else:
                            lower_surf_wins = surf_rec["p2_wins"]

                        win_rate = lower_surf_wins / surf_total
                        if win_rate >= h2h_cfg["dominance_win_rate"]:
                            if win_rate >= h2h_cfg["severity"]["high_threshold"]:
                                sev = "high"
                            else:
                                sev = "medium"
                            ln = all_players[lower_id]["name"]
                            hn = all_players[higher_id]["name"]
                            ls = seed_map_val(all_players[lower_id])
                            hs = seed_map_val(all_players[higher_id])
                            detail = (
                                f"Lower-seeded {ln} (seed {ls}) has "
                                f"{win_rate:.0%} surface win rate vs "
                                f"{hn} (seed {hs}) over {surf_total} "
                                f"{tournament_surface} matches"
                            )
                            flags.append({
                                "match_id": mid, "round": rnd,
                                "player1_id": p1id,
                                "player1_name": p1["name"],
                                "player2_id": p2id,
                                "player2_name": p2["name"],
                                "flag_type": "H2H_SURFACE_DOMINANCE",
                                "severity": sev, "details": detail,
                            })

            # ── QUALIFIER_FORM_CONCERN ──
            tiers = qfc_cfg["seed_tiers"]
            min_perf = qfc_cfg["min_avg_performance"]
            form_thresh = qfc_cfg["form_trend_threshold"]
            sev_map = qfc_cfg["severity_by_tier"]

            for pid, seed in [(p1id, p1s), (p2id, p2s)]:
                if seed <= 0:
                    continue
                # Determine tier
                if seed <= tiers["tier_1"]:
                    tier_label = "tier_1"
                elif seed <= tiers["tier_2"]:
                    tier_label = "tier_2"
                elif seed <= tiers["tier_3"]:
                    tier_label = "tier_3"
                else:
                    continue

                avg_r = qual_avg.get(pid)
                ft = form_trend_map.get(pid)
                if avg_r is None or ft is None:
                    continue

                threshold = min_perf[tier_label]
                if avg_r < threshold and ft < form_thresh:
                    sev = sev_map[tier_label]
                    pname = all_players[pid]["name"]
                    detail = (
                        f"Player {pname} (seed {seed}, {tier_label}) "
                        f"avg_qualifier={avg_r:.1f} (min {threshold:.1f}), "
                        f"form_trend={ft:.1f} (threshold {form_thresh:.1f})"
                    )
                    flags.append({
                        "match_id": mid, "round": rnd,
                        "player1_id": p1id,
                        "player1_name": p1["name"],
                        "player2_id": p2id,
                        "player2_name": p2["name"],
                        "flag_type": "QUALIFIER_FORM_CONCERN",
                        "severity": sev, "details": detail,
                    })
                    break  # one per match per type

        # Sort: severity desc (high>med>low), round asc, match_id asc
        sev_order = {"high": 0, "medium": 1, "low": 2}
        flags.sort(key=lambda x: (sev_order.get(x["severity"], 9),
                                  x["round"], x["match_id"]))
        return flags

    def step(
        self, action: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.

        Returns a reward based on evaluation results.

        Args:
            action: The agent's final response.

        Returns:
            reward: The reward based on task completion (between 0.0 and 1.0).
            info: Evaluation results.
        """
        ground_truth = self._compute_ground_truth()

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: File exists with correct columns (10 pts) ───────
        max_c1 = 10
        max_score += max_c1
        csv_path = os.path.join(self.workspace, "flagged_matches.csv")
        expected_cols = [
            "match_id", "round", "player1_id", "player1_name",
            "player2_id", "player2_name", "flag_type", "severity", "details",
        ]
        agent_rows = []
        c1_pass = False
        c1_reason = ""
        if not os.path.exists(csv_path):
            c1_reason = "flagged_matches.csv not found"
        else:
            try:
                with open(csv_path, newline="") as f:
                    reader = csv.DictReader(f)
                    if reader.fieldnames is None:
                        c1_reason = "CSV has no header"
                    elif list(reader.fieldnames) != expected_cols:
                        c1_reason = (
                            f"Column mismatch: got {list(reader.fieldnames)}"
                        )
                    else:
                        agent_rows = list(reader)
                        c1_pass = True
            except Exception as e:
                c1_reason = f"CSV parse error: {e}"

        c1_score = max_c1 if c1_pass else 0
        total_score += c1_score
        eval_criteria["file_format"] = {
            "passed": c1_pass,
            "score": c1_score,
            "max_score": max_c1,
            **({"reason": c1_reason} if not c1_pass else {}),
        }

        if not c1_pass:
            # Can't evaluate further without valid file
            for crit_name, crit_max in [
                ("rank_seed_mismatch_flags", 25),
                ("h2h_surface_dominance_flags", 25),
                ("qualifier_form_concern_flags", 20),
                ("severity_accuracy", 10),
                ("sort_order", 10),
            ]:
                max_score += crit_max
                eval_criteria[crit_name] = {
                    "passed": False, "score": 0, "max_score": crit_max,
                    "reason": "Cannot evaluate - CSV missing or malformed",
                }
            return total_score / max_score, {
                "eval_criteria": eval_criteria,
                "total_score": total_score,
                "max_score": max_score,
            }

        # Parse agent rows into (match_id, flag_type) sets per flag type
        def parse_agent(flag_type):
            return {
                int(r["match_id"]) for r in agent_rows
                if r["flag_type"].strip() == flag_type
            }

        def parse_gt(flag_type):
            return {f["match_id"] for f in ground_truth if f["flag_type"] == flag_type}

        def score_flag(agent_set, gt_set, max_pts):
            if len(gt_set) == 0:
                return (max_pts, True, "") if len(agent_set) == 0 else (
                    max(0, max_pts - len(agent_set) * 2), False,
                    f"Expected 0 flags, got {len(agent_set)}")
            correct = len(agent_set & gt_set)
            false_pos = len(agent_set - gt_set)
            raw = max(0.0, (correct - 0.5 * false_pos) / len(gt_set))
            score = round(raw * max_pts)
            passed = score >= max_pts * 0.8
            reason = "" if passed else (
                f"correct={correct}/{len(gt_set)}, false_pos={false_pos}"
            )
            return score, passed, reason

        # ── Criterion 2: RANK_SEED_MISMATCH (25 pts) ────────────────────
        max_c2 = 25
        max_score += max_c2
        a_rsm = parse_agent("RANK_SEED_MISMATCH")
        g_rsm = parse_gt("RANK_SEED_MISMATCH")
        c2_score, c2_pass, c2_reason = score_flag(a_rsm, g_rsm, max_c2)
        total_score += c2_score
        eval_criteria["rank_seed_mismatch_flags"] = {
            "passed": c2_pass, "score": c2_score, "max_score": max_c2,
            **({"reason": c2_reason} if not c2_pass else {}),
        }

        # ── Criterion 3: H2H_SURFACE_DOMINANCE (25 pts) ─────────────────
        max_c3 = 25
        max_score += max_c3
        a_h2h = parse_agent("H2H_SURFACE_DOMINANCE")
        g_h2h = parse_gt("H2H_SURFACE_DOMINANCE")
        c3_score, c3_pass, c3_reason = score_flag(a_h2h, g_h2h, max_c3)
        total_score += c3_score
        eval_criteria["h2h_surface_dominance_flags"] = {
            "passed": c3_pass, "score": c3_score, "max_score": max_c3,
            **({"reason": c3_reason} if not c3_pass else {}),
        }

        # ── Criterion 4: QUALIFIER_FORM_CONCERN (20 pts) ────────────────
        max_c4 = 20
        max_score += max_c4
        a_qfc = parse_agent("QUALIFIER_FORM_CONCERN")
        g_qfc = parse_gt("QUALIFIER_FORM_CONCERN")
        c4_score, c4_pass, c4_reason = score_flag(a_qfc, g_qfc, max_c4)
        total_score += c4_score
        eval_criteria["qualifier_form_concern_flags"] = {
            "passed": c4_pass, "score": c4_score, "max_score": max_c4,
            **({"reason": c4_reason} if not c4_pass else {}),
        }

        # ── Criterion 5: Severity accuracy (10 pts) ─────────────────────
        max_c5 = 10
        max_score += max_c5
        gt_sev = {(f["match_id"], f["flag_type"]): f["severity"] for f in ground_truth}
        correct_sev = 0
        total_checked = 0
        for r in agent_rows:
            try:
                key = (int(r["match_id"]), r["flag_type"].strip())
            except (ValueError, KeyError):
                continue
            if key in gt_sev:
                total_checked += 1
                if r["severity"].strip() == gt_sev[key]:
                    correct_sev += 1

        if total_checked > 0:
            c5_score = round(correct_sev / total_checked * max_c5)
        else:
            c5_score = 0
        c5_pass = c5_score >= max_c5 * 0.8
        c5_reason = "" if c5_pass else (
            f"{correct_sev}/{total_checked} severities correct"
        )
        total_score += c5_score
        eval_criteria["severity_accuracy"] = {
            "passed": c5_pass, "score": c5_score, "max_score": max_c5,
            **({"reason": c5_reason} if not c5_pass else {}),
        }

        # ── Criterion 6: Sort order (10 pts) ────────────────────────────
        max_c6 = 10
        max_score += max_c6
        sev_order = {"high": 0, "medium": 1, "low": 2}

        def sort_key(row):
            return (
                sev_order.get(row.get("severity", "").strip(), 9),
                int(row.get("round", 0)),
                int(row.get("match_id", 0)),
            )

        sorted_agent = sorted(agent_rows, key=sort_key)
        c6_pass = True
        for i, (a, s) in enumerate(zip(agent_rows, sorted_agent)):
            if sort_key(a) != sort_key(s):
                c6_pass = False
                break
        c6_score = max_c6 if c6_pass else 0
        c6_reason = "" if c6_pass else "Rows not sorted correctly"
        total_score += c6_score
        eval_criteria["sort_order"] = {
            "passed": c6_pass, "score": c6_score, "max_score": max_c6,
            **({"reason": c6_reason} if not c6_pass else {}),
        }

        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml
        import pandas as pd

        # ── 1. Read workspace config files ───────────────────────────────
        with open(os.path.join(self.workspace, "seeding_rules.yaml")) as f:
            rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "tournament_info.json")) as f:
            tourney = json.load(f)
        tournament_surface = tourney["surface"]
        fr = rules["flag_rules"]

        # ── 2. Read regional data files ──────────────────────────────────
        power_index_map = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "regional_data_*.csv"))):
            df = pd.read_csv(fp)
            for _, row in df.iterrows():
                power_index_map[int(row["player_id"])] = float(row["power_index"])

        # ── 3. Read qualifier detail files ───────────────────────────────
        form_trend_map = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "qualifier_detail_*.json"))):
            with open(fp) as f:
                for item in json.load(f):
                    form_trend_map[int(item["player_id"])] = float(item["form_trend"])

        # ── 4. Read surface H2H files ────────────────────────────────────
        surface_h2h = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "surface_h2h_*.txt"))):
            with open(fp) as f:
                _header = f.readline()
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("|")
                    p1 = int(parts[0])
                    p2 = int(parts[1])
                    surf = parts[2].strip()
                    w1 = int(parts[3])
                    w2 = int(parts[4])
                    key = (min(p1, p2), max(p1, p2), surf)
                    if key not in surface_h2h:
                        surface_h2h[key] = {"p1_wins": 0, "p2_wins": 0}
                    if p1 < p2:
                        surface_h2h[key]["p1_wins"] += w1
                        surface_h2h[key]["p2_wins"] += w2
                    else:
                        surface_h2h[key]["p1_wins"] += w2
                        surface_h2h[key]["p2_wins"] += w1

        # ── 5. Get bracket rounds and matches via tools ──────────────────
        rounds_resp = self.tools["list_bracket_rounds"]()
        all_rounds = rounds_resp["rounds"]

        all_matches = []
        for rnd in all_rounds:
            page = 1
            while True:
                resp = self.tools["get_bracket_matches"](
                    round_number=rnd, page=page, page_size=20
                )
                all_matches.extend(resp["matches"])
                if not resp["has_more"]:
                    break
                page += 1

        # ── 6. Collect all unique player IDs and fetch info via tool ─────
        player_ids = set()
        for m in all_matches:
            player_ids.add(m["player1_id"])
            player_ids.add(m["player2_id"])

        player_info = {}
        for pid in player_ids:
            info = self.tools["get_player_info"](player_id=pid)
            if "error" not in info:
                player_info[pid] = info

        # ── 7. Compute power_rank among seeded players ───────────────────
        seeded_players = [
            (pid, pi) for pid, pi in player_info.items()
            if pi["seed_number"] > 0
        ]
        seeded_with_pi = [
            (pid, power_index_map.get(pid, 0)) for pid, _ in seeded_players
        ]
        seeded_with_pi.sort(key=lambda x: -x[1])
        power_rank = {pid: rank + 1 for rank, (pid, _) in enumerate(seeded_with_pi)}

        # ── 8. Flag analysis ─────────────────────────────────────────────
        rsm_cfg = fr["rank_seed_mismatch"]
        h2h_cfg = fr["h2h_surface_dominance"]
        qfc_cfg = fr["qualifier_form_concern"]

        # Cache qualifier averages via tool
        qual_avg_cache = {}

        def get_qual_avg(pid):
            if pid not in qual_avg_cache:
                resp = self.tools["get_qualifier_performance"](player_id=pid)
                results = resp.get("results", [])
                if results:
                    qual_avg_cache[pid] = sum(
                        r["performance_rating"] for r in results
                    ) / len(results)
                else:
                    qual_avg_cache[pid] = None
            return qual_avg_cache[pid]

        flags = []

        for m in all_matches:
            mid = m["match_id"]
            rnd = m["round_number"]
            p1id = m["player1_id"]
            p2id = m["player2_id"]
            p1s = m["player1_seed"]
            p2s = m["player2_seed"]
            p1_name = player_info.get(p1id, {}).get("name", "Unknown")
            p2_name = player_info.get(p2id, {}).get("name", "Unknown")

            # ── RANK_SEED_MISMATCH ──
            for pid, seed in [(p1id, p1s), (p2id, p2s)]:
                if seed > 0 and pid in power_rank:
                    diff = abs(seed - power_rank[pid])
                    if diff > rsm_cfg["max_rank_seed_diff"]:
                        if diff > rsm_cfg["severity"]["high_threshold"]:
                            sev = "high"
                        else:
                            sev = "medium"
                        pname = player_info[pid]["name"]
                        detail = (
                            f"Player {pname} (ID:{pid}) seed={seed} "
                            f"but power_rank={power_rank[pid]}, diff={diff}"
                        )
                        flags.append({
                            "match_id": mid, "round": rnd,
                            "player1_id": p1id, "player1_name": p1_name,
                            "player2_id": p2id, "player2_name": p2_name,
                            "flag_type": "RANK_SEED_MISMATCH",
                            "severity": sev, "details": detail,
                        })
                        break

            # ── H2H_SURFACE_DOMINANCE ──
            if p1s > 0 or p2s > 0:
                lo, hi = min(p1id, p2id), max(p1id, p2id)
                # Check overall H2H via tool
                h2h_resp = self.tools["get_head_to_head"](
                    player1_id=lo, player2_id=hi
                )
                rec = h2h_resp.get("record")
                surf_key = (lo, hi, tournament_surface)
                surf_rec = surface_h2h.get(surf_key)

                if rec and surf_rec:
                    total_matches = rec["total_matches"]
                    surf_total = surf_rec["p1_wins"] + surf_rec["p2_wins"]

                    if (total_matches >= h2h_cfg["min_total_matches"]
                            and surf_total >= h2h_cfg["min_surface_matches"]):
                        eff_s1 = p1s if p1s > 0 else 9999
                        eff_s2 = p2s if p2s > 0 else 9999
                        if eff_s1 < eff_s2:
                            higher_id, lower_id = p1id, p2id
                        else:
                            higher_id, lower_id = p2id, p1id

                        if lower_id == lo:
                            lower_surf_wins = surf_rec["p1_wins"]
                        else:
                            lower_surf_wins = surf_rec["p2_wins"]

                        if surf_total > 0:
                            win_rate = lower_surf_wins / surf_total
                        else:
                            win_rate = 0.0

                        if win_rate >= h2h_cfg["dominance_win_rate"]:
                            if win_rate >= h2h_cfg["severity"]["high_threshold"]:
                                sev = "high"
                            else:
                                sev = "medium"
                            ln = player_info[lower_id]["name"]
                            hn = player_info[higher_id]["name"]
                            ls = player_info[lower_id]["seed_number"]
                            hs = player_info[higher_id]["seed_number"]
                            detail = (
                                f"Lower-seeded {ln} (seed {ls}) has "
                                f"{win_rate:.0%} surface win rate vs "
                                f"{hn} (seed {hs}) over {surf_total} "
                                f"{tournament_surface} matches"
                            )
                            flags.append({
                                "match_id": mid, "round": rnd,
                                "player1_id": p1id,
                                "player1_name": p1_name,
                                "player2_id": p2id,
                                "player2_name": p2_name,
                                "flag_type": "H2H_SURFACE_DOMINANCE",
                                "severity": sev, "details": detail,
                            })

            # ── QUALIFIER_FORM_CONCERN ──
            tiers = qfc_cfg["seed_tiers"]
            min_perf = qfc_cfg["min_avg_performance"]
            form_thresh = qfc_cfg["form_trend_threshold"]
            sev_map_qfc = qfc_cfg["severity_by_tier"]

            for pid, seed in [(p1id, p1s), (p2id, p2s)]:
                if seed <= 0:
                    continue
                if seed <= tiers["tier_1"]:
                    tier_label = "tier_1"
                elif seed <= tiers["tier_2"]:
                    tier_label = "tier_2"
                elif seed <= tiers["tier_3"]:
                    tier_label = "tier_3"
                else:
                    continue

                avg_r = get_qual_avg(pid)
                ft = form_trend_map.get(pid)
                if avg_r is None or ft is None:
                    continue

                threshold = min_perf[tier_label]
                if avg_r < threshold and ft < form_thresh:
                    sev = sev_map_qfc[tier_label]
                    pname = player_info[pid]["name"]
                    detail = (
                        f"Player {pname} (seed {seed}, {tier_label}) "
                        f"avg_qualifier={avg_r:.1f} (min {threshold:.1f}), "
                        f"form_trend={ft:.1f} (threshold {form_thresh:.1f})"
                    )
                    flags.append({
                        "match_id": mid, "round": rnd,
                        "player1_id": p1id,
                        "player1_name": p1_name,
                        "player2_id": p2id,
                        "player2_name": p2_name,
                        "flag_type": "QUALIFIER_FORM_CONCERN",
                        "severity": sev, "details": detail,
                    })
                    break

        # ── 9. Sort flags ────────────────────────────────────────────────
        sev_order = {"high": 0, "medium": 1, "low": 2}
        flags.sort(key=lambda x: (sev_order.get(x["severity"], 9),
                                  x["round"], x["match_id"]))

        # ── 10. Write flagged_matches.csv ────────────────────────────────
        csv_path = os.path.join(self.workspace, "flagged_matches.csv")
        fieldnames = [
            "match_id", "round", "player1_id", "player1_name",
            "player2_id", "player2_name", "flag_type", "severity", "details",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flags)

        # ── 11. Build action summary ─────────────────────────────────────
        type_counts = {}
        sev_counts = {}
        for fl in flags:
            type_counts[fl["flag_type"]] = type_counts.get(fl["flag_type"], 0) + 1
            sev_counts[fl["severity"]] = sev_counts.get(fl["severity"], 0) + 1

        summary_parts = [f"Total flagged entries: {len(flags)}."]
        for ft, cnt in sorted(type_counts.items()):
            summary_parts.append(f"  {ft}: {cnt}")
        for sv in ["high", "medium", "low"]:
            if sv in sev_counts:
                summary_parts.append(f"  Severity {sv}: {sev_counts[sv]}")

        action = (
            "Analysis complete. Flagged matches saved to flagged_matches.csv.\n"
            + "\n".join(summary_parts)
        )

        return self.step(action)


def seed_map_val(player_dict):
    """Helper to get seed_number from a player dict."""
    return player_dict.get("seed_number", 0)
