"""
Environment for weekly referee assignment roster task.
Tools expose DB data; workspace files provide availability and policy config.
"""

import csv
import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
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

    # ────────────────────────── Tool methods ──────────────────────────

    @tool(
        description="Retrieve a paginated list of fixtures for the week. Returns up to page_size fixtures per page.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of fixtures per page (max 10, default 5).",
                },
            },
            "required": ["page"],
        },
    )
    def get_fixtures(self, page: int, page_size: int = 5) -> dict:
        page_size = min(int(page_size), 10)
        page = int(page)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM fixtures").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM fixtures ORDER BY fixture_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "fixtures": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total_fixtures": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get detailed information about a single referee by their ID.",
        parameters={
            "type": "object",
            "properties": {
                "referee_id": {
                    "type": "integer",
                    "description": "The referee's unique identifier.",
                },
            },
            "required": ["referee_id"],
        },
    )
    def get_referee_info(self, referee_id: int) -> dict:
        referee_id = int(referee_id)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM referees WHERE referee_id = ?", (referee_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Referee {referee_id} not found."}
        return dict(row)

    @tool(
        description="Get all certifications held by a specific referee.",
        parameters={
            "type": "object",
            "properties": {
                "referee_id": {
                    "type": "integer",
                    "description": "The referee's unique identifier.",
                },
            },
            "required": ["referee_id"],
        },
    )
    def get_certifications(self, referee_id: int) -> dict:
        referee_id = int(referee_id)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM certifications WHERE referee_id = ?", (referee_id,)
        ).fetchall()
        conn.close()
        return {"referee_id": referee_id, "certifications": [dict(r) for r in rows]}

    @tool(
        description="Get all conflict records for a specific referee. Returns both active and inactive conflicts.",
        parameters={
            "type": "object",
            "properties": {
                "referee_id": {
                    "type": "integer",
                    "description": "The referee's unique identifier.",
                },
            },
            "required": ["referee_id"],
        },
    )
    def get_conflicts(self, referee_id: int) -> dict:
        referee_id = int(referee_id)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM conflicts WHERE referee_id = ?", (referee_id,)
        ).fetchall()
        conn.close()
        return {"referee_id": referee_id, "conflicts": [dict(r) for r in rows]}

    @tool(
        description="Get information about a specific venue by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "venue_id": {
                    "type": "integer",
                    "description": "The venue's unique identifier.",
                },
            },
            "required": ["venue_id"],
        },
    )
    def get_venue_info(self, venue_id: int) -> dict:
        venue_id = int(venue_id)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM venues WHERE venue_id = ?", (venue_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Venue {venue_id} not found."}
        return dict(row)

    @tool(
        description="Get information about a specific team by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "team_id": {
                    "type": "integer",
                    "description": "The team's unique identifier.",
                },
            },
            "required": ["team_id"],
        },
    )
    def get_team_info(self, team_id: int) -> dict:
        team_id = int(team_id)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM teams WHERE team_id = ?", (team_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Team {team_id} not found."}
        return dict(row)

    @tool(
        description="List all referee IDs registered in the system (not necessarily available this week). Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of referees per page (max 20, default 10).",
                },
            },
            "required": ["page"],
        },
    )
    def list_referees(self, page: int, page_size: int = 10) -> dict:
        page_size = min(int(page_size), 20)
        page = int(page)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM referees").fetchone()[0]
        rows = conn.execute(
            "SELECT referee_id, name FROM referees ORDER BY referee_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "referees": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total_referees": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    # ────────────────────────── Evaluation ──────────────────────────

    def _compute_ground_truth(self) -> List[dict]:
        """Compute the correct roster assignment using the deterministic algorithm."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load all data
        fixtures = [dict(r) for r in conn.execute("SELECT * FROM fixtures").fetchall()]
        referees = {
            r["referee_id"]: dict(r)
            for r in conn.execute("SELECT * FROM referees").fetchall()
        }
        venues = {
            r["venue_id"]: dict(r)
            for r in conn.execute("SELECT * FROM venues").fetchall()
        }
        teams = {
            r["team_id"]: dict(r)
            for r in conn.execute("SELECT * FROM teams").fetchall()
        }
        certs_raw = [dict(r) for r in conn.execute("SELECT * FROM certifications").fetchall()]
        conflicts_raw = [dict(r) for r in conn.execute("SELECT * FROM conflicts").fetchall()]
        conn.close()

        # Build cert lookup: referee_id -> {match_type: cert_level_str}
        cert_map = {}
        for c in certs_raw:
            cert_map.setdefault(c["referee_id"], {})[c["match_type"]] = c["cert_level"]

        # Build active conflict lookup: referee_id -> set of team_ids
        conflict_map = {}
        for c in conflicts_raw:
            if c["active"] == 1:
                conflict_map.setdefault(c["referee_id"], set()).add(c["team_id"])

        # Load policy
        with open(os.path.join(self.workspace, "policy.yaml"), "r") as f:
            policy = yaml.safe_load(f)
        max_distance = policy["max_travel_distance_km"]

        # Load match requirements
        with open(os.path.join(self.workspace, "match_requirements.json"), "r") as f:
            match_reqs = json.load(f)

        # Load travel matrix
        import pandas as pd
        dist_df = pd.read_csv(os.path.join(self.workspace, "travel_matrix.csv"))
        dist_df = dist_df.set_index("city")
        distance_lookup = {}
        for c1 in dist_df.index:
            for c2 in dist_df.columns:
                distance_lookup[(c1, c2)] = int(dist_df.loc[c1, c2])

        # Load availability from workspace files
        avail_dir = os.path.join(self.workspace, "availability")
        availability = {}  # referee_id -> {day: [slots]}
        available_ref_ids = set()
        if os.path.isdir(avail_dir):
            for fname in os.listdir(avail_dir):
                if fname.endswith(".json"):
                    with open(os.path.join(avail_dir, fname), "r") as f:
                        data = json.load(f)
                    rid = data["referee_id"]
                    available_ref_ids.add(rid)
                    availability[rid] = data["availability"]

        cert_level_num = {"basic": 1, "advanced": 2, "elite": 3}
        slot_order = {"morning": 0, "afternoon": 1, "evening": 2}

        # Sort fixtures by: priority_level DESC, match_date ASC, time_slot ASC, fixture_id ASC
        fixtures.sort(
            key=lambda f: (-f["priority_level"], f["match_date"], slot_order.get(f["time_slot"], 0), f["fixture_id"])
        )

        # Track assignments
        ref_assignment_count = {rid: 0 for rid in available_ref_ids}
        ref_day_slot_used = {}  # (referee_id, day, slot) -> True

        roster = []
        for fix in fixtures:
            fid = fix["fixture_id"]
            match_type = fix["match_type"]
            day = fix["day_of_week"]
            slot = fix["time_slot"]
            venue = venues[fix["venue_id"]]
            venue_city = venue["city"]
            home_team_id = fix["home_team_id"]
            away_team_id = fix["away_team_id"]
            home_team_name = teams[home_team_id]["name"]
            away_team_name = teams[away_team_id]["name"]

            req_level_str = match_reqs.get(match_type, "basic")
            req_level_num = cert_level_num[req_level_str]

            # Find eligible referees
            candidates = []
            for rid in sorted(available_ref_ids):
                ref = referees[rid]
                # Check max weekly assignments
                if ref_assignment_count[rid] >= ref["max_weekly_assignments"]:
                    continue
                # Check time slot conflict
                if ref_day_slot_used.get((rid, day, slot)):
                    continue
                # Check availability
                ref_avail = availability.get(rid, {})
                if day not in ref_avail or slot not in ref_avail[day]:
                    continue
                # Check certification
                ref_certs = cert_map.get(rid, {})
                if match_type not in ref_certs:
                    continue
                ref_cert_level = cert_level_num.get(ref_certs[match_type], 0)
                if ref_cert_level < req_level_num:
                    continue
                # Check conflicts (active only)
                ref_conflicts = conflict_map.get(rid, set())
                if home_team_id in ref_conflicts or away_team_id in ref_conflicts:
                    continue
                # Check travel distance
                ref_city = ref["home_city"]
                dist = distance_lookup.get((ref_city, venue_city), distance_lookup.get((venue_city, ref_city), 9999))
                if dist > max_distance:
                    continue

                candidates.append((rid, ref_cert_level, ref["experience_years"]))

            if candidates:
                # Tiebreak: highest cert level, most experience, lowest id
                candidates.sort(key=lambda x: (-x[1], -x[2], x[0]))
                chosen_rid = candidates[0][0]
                ref_assignment_count[chosen_rid] += 1
                ref_day_slot_used[(chosen_rid, day, slot)] = True
                ref_name = referees[chosen_rid]["name"]
            else:
                chosen_rid = -1
                ref_name = "UNASSIGNED"

            roster.append({
                "fixture_id": fid,
                "match_date": fix["match_date"],
                "day_of_week": day,
                "time_slot": slot,
                "home_team": home_team_name,
                "away_team": away_team_name,
                "venue_name": venue["name"],
                "referee_id": chosen_rid,
                "referee_name": ref_name,
            })

        # Sort output by fixture_id
        roster.sort(key=lambda r: r["fixture_id"])
        return roster

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
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
        gt_by_id = {r["fixture_id"]: r for r in ground_truth}
        total_fixtures = len(ground_truth)

        eval_criteria = {}

        # ── Criterion 1: roster.csv exists and is readable (10 pts) ──
        roster_path = os.path.join(self.workspace, "roster.csv")
        roster_exists = os.path.isfile(roster_path)
        submitted_rows = []
        parse_error = None
        if roster_exists:
            try:
                with open(roster_path, "r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    submitted_rows = [row for row in reader]
            except Exception as e:
                parse_error = str(e)

        eval_criteria["roster_file_exists"] = {
            "passed": roster_exists and parse_error is None,
            "score": 10 if (roster_exists and parse_error is None) else 0,
            "max_score": 10,
            "reason": None if (roster_exists and parse_error is None) else (
                f"Parse error: {parse_error}" if parse_error else "roster.csv not found"
            ),
        }

        # ── Criterion 2: correct columns in correct order (10 pts) ──
        expected_cols = [
            "fixture_id", "match_date", "day_of_week", "time_slot",
            "home_team", "away_team", "venue_name", "referee_id", "referee_name",
        ]
        if submitted_rows:
            actual_cols = list(submitted_rows[0].keys())
            cols_correct = actual_cols == expected_cols
        else:
            actual_cols = []
            cols_correct = False
        eval_criteria["correct_columns"] = {
            "passed": cols_correct,
            "score": 10 if cols_correct else 0,
            "max_score": 10,
            "reason": None if cols_correct else f"Expected {expected_cols}, got {actual_cols}",
        }

        # ── Criterion 3: correct number of rows (all fixtures present) (10 pts) ──
        row_count_ok = len(submitted_rows) == total_fixtures
        eval_criteria["all_fixtures_present"] = {
            "passed": row_count_ok,
            "score": 10 if row_count_ok else 0,
            "max_score": 10,
            "reason": None if row_count_ok else f"Expected {total_fixtures} rows, got {len(submitted_rows)}",
        }

        # ── Criterion 4: fixture metadata correct (match_date, day_of_week, time_slot, teams, venue) (20 pts) ──
        metadata_correct = 0
        metadata_total = 0
        for row in submitted_rows:
            try:
                fid = int(row.get("fixture_id", -999))
            except (ValueError, TypeError):
                continue
            gt = gt_by_id.get(fid)
            if gt is None:
                continue
            metadata_total += 1
            if (
                row.get("match_date") == gt["match_date"]
                and row.get("day_of_week") == gt["day_of_week"]
                and row.get("time_slot") == gt["time_slot"]
                and row.get("home_team") == gt["home_team"]
                and row.get("away_team") == gt["away_team"]
                and row.get("venue_name") == gt["venue_name"]
            ):
                metadata_correct += 1

        if metadata_total > 0:
            meta_ratio = metadata_correct / metadata_total
        else:
            meta_ratio = 0.0
        meta_score = round(meta_ratio * 20, 2)
        eval_criteria["fixture_metadata_accuracy"] = {
            "passed": meta_ratio == 1.0,
            "score": meta_score,
            "max_score": 20,
            "reason": None if meta_ratio == 1.0 else f"{metadata_correct}/{metadata_total} fixtures have correct metadata",
        }

        # ── Criterion 5: referee assignments match ground truth (30 pts) ──
        assign_correct = 0
        assign_total = 0
        for row in submitted_rows:
            try:
                fid = int(row.get("fixture_id", -999))
                submitted_rid = int(row.get("referee_id", -999))
            except (ValueError, TypeError):
                continue
            gt = gt_by_id.get(fid)
            if gt is None:
                continue
            assign_total += 1
            if submitted_rid == gt["referee_id"]:
                assign_correct += 1

        if assign_total > 0:
            assign_ratio = assign_correct / assign_total
        else:
            assign_ratio = 0.0
        assign_score = round(assign_ratio * 30, 2)
        eval_criteria["referee_assignment_accuracy"] = {
            "passed": assign_ratio == 1.0,
            "score": assign_score,
            "max_score": 30,
            "reason": None if assign_ratio == 1.0 else f"{assign_correct}/{assign_total} correct assignments",
        }

        # ── Criterion 6: referee names match (10 pts) ──
        name_correct = 0
        name_total = 0
        for row in submitted_rows:
            try:
                fid = int(row.get("fixture_id", -999))
            except (ValueError, TypeError):
                continue
            gt = gt_by_id.get(fid)
            if gt is None:
                continue
            name_total += 1
            if row.get("referee_name", "").strip() == gt["referee_name"]:
                name_correct += 1

        if name_total > 0:
            name_ratio = name_correct / name_total
        else:
            name_ratio = 0.0
        name_score = round(name_ratio * 10, 2)
        eval_criteria["referee_name_accuracy"] = {
            "passed": name_ratio == 1.0,
            "score": name_score,
            "max_score": 10,
            "reason": None if name_ratio == 1.0 else f"{name_correct}/{name_total} correct names",
        }

        # ── Criterion 7: sort order (fixture_id ascending) (10 pts) ──
        sort_ok = False
        if submitted_rows:
            try:
                fids = [int(r["fixture_id"]) for r in submitted_rows]
                sort_ok = fids == sorted(fids)
            except (ValueError, KeyError):
                sort_ok = False
        eval_criteria["sort_order"] = {
            "passed": sort_ok,
            "score": 10 if sort_ok else 0,
            "max_score": 10,
            "reason": None if sort_ok else "Rows are not sorted by fixture_id ascending",
        }

        # ── Compute totals ──
        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())
        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.

        This method proves end-to-end solvability. It must:
          - Use self.tools[name](**params) to gather data (no direct DB queries).
          - Read files from self.workspace as needed.
          - Write all required deliverables to self.workspace.
          - Construct the final action string.
          - Return self.step(action).
        """
        import pandas as pd

        # ── Step 1: Load workspace config files ──
        with open(os.path.join(self.workspace, "policy.yaml"), "r") as f:
            policy = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "match_requirements.json"), "r") as f:
            match_reqs = json.load(f)

        dist_df = pd.read_csv(os.path.join(self.workspace, "travel_matrix.csv"))
        dist_df = dist_df.set_index("city")

        max_distance = policy["max_travel_distance_km"]

        # ── Step 2: Load availability files ──
        avail_dir = os.path.join(self.workspace, "availability")
        availability = {}  # referee_id -> {day: [slots]}
        available_ref_ids = set()
        for fname in sorted(os.listdir(avail_dir)):
            if fname.endswith(".json"):
                with open(os.path.join(avail_dir, fname), "r") as f:
                    data = json.load(f)
                rid = data["referee_id"]
                available_ref_ids.add(rid)
                availability[rid] = data["availability"]

        # ── Step 3: Get all fixtures via tool (paginated) ──
        tool_call_count = 0
        all_fixtures = []
        page = 1
        while True:
            result = self.tools["get_fixtures"](page=page, page_size=10)
            tool_call_count += 1
            all_fixtures.extend(result["fixtures"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ── Step 4: For each available referee, get info, certs, conflicts ──
        ref_info = {}
        ref_certs = {}  # rid -> {match_type: cert_level_str}
        ref_conflicts = {}  # rid -> set of team_ids (active only)

        for rid in sorted(available_ref_ids):
            info = self.tools["get_referee_info"](referee_id=rid)
            tool_call_count += 1
            ref_info[rid] = info

            certs_result = self.tools["get_certifications"](referee_id=rid)
            tool_call_count += 1
            cmap = {}
            for c in certs_result["certifications"]:
                cmap[c["match_type"]] = c["cert_level"]
            ref_certs[rid] = cmap

            conflicts_result = self.tools["get_conflicts"](referee_id=rid)
            tool_call_count += 1
            active_conflicts = set()
            for c in conflicts_result["conflicts"]:
                if c["active"] == 1:
                    active_conflicts.add(c["team_id"])
            ref_conflicts[rid] = active_conflicts

        # ── Step 5: Get venue and team info for each fixture ──
        venue_cache = {}
        team_cache = {}

        for fix in all_fixtures:
            vid = fix["venue_id"]
            if vid not in venue_cache:
                venue_cache[vid] = self.tools["get_venue_info"](venue_id=vid)
                tool_call_count += 1

            for tid in [fix["home_team_id"], fix["away_team_id"]]:
                if tid not in team_cache:
                    team_cache[tid] = self.tools["get_team_info"](team_id=tid)
                    tool_call_count += 1

        # ── Step 6: Build distance lookup from workspace file ──
        distance_lookup = {}
        for c1 in dist_df.index:
            for c2 in dist_df.columns:
                distance_lookup[(c1, c2)] = int(dist_df.loc[c1, c2])

        cert_level_num = {"basic": 1, "advanced": 2, "elite": 3}
        slot_order = {"morning": 0, "afternoon": 1, "evening": 2}

        # ── Step 7: Sort fixtures by assignment priority ──
        all_fixtures.sort(
            key=lambda f: (
                -f["priority_level"],
                f["match_date"],
                slot_order.get(f["time_slot"], 0),
                f["fixture_id"],
            )
        )

        # ── Step 8: Greedy assignment ──
        ref_assignment_count = {rid: 0 for rid in available_ref_ids}
        ref_day_slot_used = {}
        roster = []

        for fix in all_fixtures:
            fid = fix["fixture_id"]
            match_type = fix["match_type"]
            day = fix["day_of_week"]
            slot = fix["time_slot"]
            venue = venue_cache[fix["venue_id"]]
            venue_city = venue["city"]
            home_team_id = fix["home_team_id"]
            away_team_id = fix["away_team_id"]
            home_team_name = team_cache[home_team_id]["name"]
            away_team_name = team_cache[away_team_id]["name"]
            venue_name = venue["name"]

            req_level_str = match_reqs.get(match_type, "basic")
            req_level_num = cert_level_num[req_level_str]

            candidates = []
            for rid in sorted(available_ref_ids):
                ri = ref_info[rid]
                if ref_assignment_count[rid] >= ri["max_weekly_assignments"]:
                    continue
                if ref_day_slot_used.get((rid, day, slot)):
                    continue
                ref_avail = availability.get(rid, {})
                if day not in ref_avail or slot not in ref_avail[day]:
                    continue
                rc = ref_certs.get(rid, {})
                if match_type not in rc:
                    continue
                ref_cert_lv = cert_level_num.get(rc[match_type], 0)
                if ref_cert_lv < req_level_num:
                    continue
                if home_team_id in ref_conflicts.get(rid, set()) or away_team_id in ref_conflicts.get(rid, set()):
                    continue
                ref_city = ri["home_city"]
                dist = distance_lookup.get(
                    (ref_city, venue_city),
                    distance_lookup.get((venue_city, ref_city), 9999),
                )
                if dist > max_distance:
                    continue
                candidates.append((rid, ref_cert_lv, ri["experience_years"]))

            if candidates:
                candidates.sort(key=lambda x: (-x[1], -x[2], x[0]))
                chosen_rid = candidates[0][0]
                ref_assignment_count[chosen_rid] += 1
                ref_day_slot_used[(chosen_rid, day, slot)] = True
                chosen_name = ref_info[chosen_rid]["name"]
            else:
                chosen_rid = -1
                chosen_name = "UNASSIGNED"

            roster.append({
                "fixture_id": fid,
                "match_date": fix["match_date"],
                "day_of_week": day,
                "time_slot": slot,
                "home_team": home_team_name,
                "away_team": away_team_name,
                "venue_name": venue_name,
                "referee_id": chosen_rid,
                "referee_name": chosen_name,
            })

        # Sort by fixture_id ascending
        roster.sort(key=lambda r: r["fixture_id"])

        # ── Step 9: Write roster.csv ──
        roster_path = os.path.join(self.workspace, "roster.csv")
        fieldnames = [
            "fixture_id", "match_date", "day_of_week", "time_slot",
            "home_team", "away_team", "venue_name", "referee_id", "referee_name",
        ]
        with open(roster_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(roster)

        # ── Step 10: Build action string ──
        assigned = [r for r in roster if r["referee_id"] != -1]
        unassigned = [r for r in roster if r["referee_id"] == -1]

        action = (
            f"Roster generation complete. "
            f"Total fixtures: {len(roster)}. "
            f"Assigned: {len(assigned)}. "
            f"Unassigned: {len(unassigned)}. "
            f"The roster has been saved to roster.csv."
        )

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made; need >= 15"

        return self.step(action)
