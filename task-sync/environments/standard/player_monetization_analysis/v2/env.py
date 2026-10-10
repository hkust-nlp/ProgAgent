import sqlite3
import os
import json
import csv
import math
from typing import Tuple, Dict, List, Any

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

    # ================================================================= tools

    @tool(
        description=(
            "List players with pagination. Returns player_id, username, tier, "
            "total_playtime_hours, last_login_date, and account_status for "
            "each player on the requested page."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "1-based page number.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (max 20).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_players(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM players")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT player_id, username, tier, total_playtime_hours, "
            "last_login_date, account_status FROM players "
            "ORDER BY player_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total_players": total,
            "total_pages": math.ceil(total / page_size),
            "players": rows,
        }

    @tool(
        description=(
            "Get the total USD spending for a single player across all "
            "purchase receipts, along with a per-category breakdown."
        ),
        parameters={
            "type": "object",
            "properties": {
                "player_id": {
                    "type": "string",
                    "description": "The player ID, e.g. 'P0001'.",
                },
            },
            "required": ["player_id"],
        },
    )
    def get_player_spending(self, player_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(SUM(amount_usd), 0) FROM purchase_receipts "
            "WHERE player_id = ?",
            (player_id,),
        )
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT item_category, SUM(amount_usd) FROM purchase_receipts "
            "WHERE player_id = ? GROUP BY item_category",
            (player_id,),
        )
        breakdown = {row[0]: round(row[1], 2) for row in cur.fetchall()}
        conn.close()
        return {
            "player_id": player_id,
            "total_spending_usd": round(total, 2),
            "category_breakdown": breakdown,
        }

    @tool(
        description=(
            "Get engagement-related metrics for a single player: "
            "total playtime hours, number of events participated in, "
            "and total virtual currency earned."
        ),
        parameters={
            "type": "object",
            "properties": {
                "player_id": {
                    "type": "string",
                    "description": "The player ID, e.g. 'P0001'.",
                },
            },
            "required": ["player_id"],
        },
    )
    def get_player_engagement(self, player_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT total_playtime_hours FROM players WHERE player_id = ?",
            (player_id,),
        )
        row = cur.fetchone()
        playtime = row[0] if row else 0.0
        cur.execute(
            "SELECT COUNT(DISTINCT event_id) FROM event_participation "
            "WHERE player_id = ?",
            (player_id,),
        )
        event_count = cur.fetchone()[0]
        cur.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM currency_transactions "
            "WHERE player_id = ? AND txn_type = 'earn'",
            (player_id,),
        )
        currency_earned = cur.fetchone()[0]
        conn.close()
        return {
            "player_id": player_id,
            "total_playtime_hours": playtime,
            "event_participation_count": event_count,
            "total_currency_earned": round(currency_earned, 2),
        }

    @tool(
        description=(
            "List all limited-time events. Returns event_id, event_name, "
            "event_type, start_date, end_date, bonus_multiplier, and "
            "min_tier_required for every event."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_events(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM events ORDER BY event_id")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"events": rows}

    @tool(
        description=(
            "Get detailed information for a single event by its event_id, "
            "including the number of participants and total revenue generated "
            "during the event."
        ),
        parameters={
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "The event ID, e.g. 'E001'.",
                },
            },
            "required": ["event_id"],
        },
    )
    def get_event_details(self, event_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"error": f"Event {event_id} not found."}
        event = dict(row)
        cur.execute(
            "SELECT COUNT(DISTINCT player_id) FROM event_participation "
            "WHERE event_id = ?",
            (event_id,),
        )
        event["participant_count"] = cur.fetchone()[0]
        cur.execute(
            "SELECT COALESCE(SUM(amount_usd), 0) FROM purchase_receipts "
            "WHERE event_id = ?",
            (event_id,),
        )
        event["event_revenue_usd"] = round(cur.fetchone()[0], 2)
        conn.close()
        return event

    @tool(
        description=(
            "Retrieve the purchase receipts for a single player. Returns a "
            "list of receipts with receipt_id, item_name, item_category, "
            "amount_usd, purchase_date, payment_method, and event_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "player_id": {
                    "type": "string",
                    "description": "The player ID, e.g. 'P0001'.",
                },
            },
            "required": ["player_id"],
        },
    )
    def get_player_purchases(self, player_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT receipt_id, item_name, item_category, amount_usd, "
            "purchase_date, payment_method, event_id "
            "FROM purchase_receipts WHERE player_id = ? "
            "ORDER BY purchase_date",
            (player_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"player_id": player_id, "purchases": rows}

    # ============================================================ evaluation

    def _compute_ground_truth(self):
        """Compute the full ground-truth campaign list from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # load configs
        with open(os.path.join(self.workspace, "tier_config.yaml")) as f:
            tier_cfg = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "segment_criteria.json")) as f:
            seg = json.load(f)
        promo_rows = []
        with open(os.path.join(self.workspace, "promotion_catalog.csv")) as f:
            reader = csv.DictReader(f)
            for r in reader:
                r["discount_pct"] = float(r["discount_pct"])
                r["min_gap_ratio"] = float(r["min_gap_ratio"])
                promo_rows.append(r)

        # load surveys
        survey_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("player_survey_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for s in json.load(f):
                        survey_map[s["player_id"]] = s

        undef = seg["under_monetized_definition"]
        efm = seg["engagement_score_formula"]
        period = tier_cfg["analysis_period_months"]

        # all players
        cur.execute("SELECT * FROM players ORDER BY player_id")
        all_players = [dict(r) for r in cur.fetchall()]

        campaign = []
        for p in all_players:
            pid = p["player_id"]
            tier = p["tier"]
            status = p["account_status"]
            if status != undef["required_account_status"]:
                continue

            # actual spending
            cur.execute(
                "SELECT COALESCE(SUM(amount_usd), 0) FROM purchase_receipts "
                "WHERE player_id = ?", (pid,))
            actual = round(cur.fetchone()[0], 2)

            # expected
            expected = round(
                tier_cfg["tiers"][tier]["expected_monthly_spending_usd"]
                * period, 2)

            if expected == 0:
                continue

            spending_ratio = actual / expected
            if spending_ratio >= undef["spending_ratio_threshold"]:
                continue

            # engagement
            playtime = p["total_playtime_hours"]
            cur.execute(
                "SELECT COUNT(DISTINCT event_id) FROM event_participation "
                "WHERE player_id = ?", (pid,))
            ev_count = cur.fetchone()[0]
            cur.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM currency_transactions "
                "WHERE player_id = ? AND txn_type = 'earn'", (pid,))
            curr_earned = cur.fetchone()[0]

            eng = min(100.0, (
                playtime / efm["playtime_cap"] * efm["playtime_weight"]
                + ev_count / efm["event_cap"] * efm["event_weight"]
                + curr_earned / efm["currency_cap"] * efm["currency_weight"]
            ) * 100)
            eng = round(eng, 2)

            if eng < undef["min_engagement_score"]:
                continue

            # willingness from survey
            sv = survey_map.get(pid)
            if sv is None:
                continue
            willingness = sv["spending_willingness"]
            if willingness < undef["min_willingness_rating"]:
                continue

            gap = round(expected - actual, 2)
            gap_ratio = round(gap / expected, 4)

            priority = round(gap_ratio * eng * willingness / 100, 2)

            # promotion matching
            game_mode = sv["preferred_game_mode"]
            best_promo = None
            for pr in promo_rows:
                tiers_ok = (pr["target_tiers"] == "all"
                            or tier in pr["target_tiers"].split(","))
                mode_ok = (pr["target_game_mode"] == "all"
                           or pr["target_game_mode"] == game_mode)
                gap_ok = gap_ratio >= pr["min_gap_ratio"]
                if tiers_ok and mode_ok and gap_ok:
                    if (best_promo is None
                            or pr["discount_pct"] > best_promo["discount_pct"]
                            or (pr["discount_pct"] == best_promo["discount_pct"]
                                and pr["promo_id"] < best_promo["promo_id"])):
                        best_promo = pr
            if best_promo is None:
                best_promo = next(
                    p for p in promo_rows if p["promo_id"] == "PROMO06")

            campaign.append({
                "player_id": pid,
                "username": p["username"],
                "tier": tier,
                "actual_spending": actual,
                "expected_spending": expected,
                "spending_gap": gap,
                "gap_ratio": gap_ratio,
                "engagement_score": eng,
                "willingness": willingness,
                "priority_score": priority,
                "assigned_promo_id": best_promo["promo_id"],
                "assigned_promo_name": best_promo["promo_name"],
            })

        conn.close()

        # sort: priority desc, player_id asc
        campaign.sort(key=lambda x: (-x["priority_score"], x["player_id"]))
        return campaign

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
        gt = self._compute_ground_truth()
        gt_ids = {r["player_id"] for r in gt}
        gt_map = {r["player_id"]: r for r in gt}

        criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: campaign_list.csv exists with correct columns (10)
        csv_path = os.path.join(self.workspace, "campaign_list.csv")
        expected_cols = [
            "player_id", "username", "tier", "actual_spending",
            "expected_spending", "spending_gap", "gap_ratio",
            "engagement_score", "willingness", "priority_score",
            "assigned_promo_id", "assigned_promo_name",
        ]
        c1_score = 0
        c1_max = 10
        agent_rows = []
        if os.path.exists(csv_path):
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames or []
                if all(c in cols for c in expected_cols):
                    c1_score = 10
                    agent_rows = list(reader)
                else:
                    c1_score = 3  # partial: file exists but wrong columns
        criteria["csv_format"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": "" if c1_score == c1_max else "Missing columns or file",
        }
        total_score += c1_score
        max_score += c1_max

        # --- Criterion 2: correct under-monetized player IDs (25)
        c2_max = 25
        agent_ids = {r["player_id"] for r in agent_rows}
        if len(gt_ids) > 0:
            correct = len(agent_ids & gt_ids)
            extra = len(agent_ids - gt_ids)
            precision = correct / max(1, len(agent_ids))
            recall = correct / len(gt_ids)
            f1 = (2 * precision * recall / max(1e-9, precision + recall))
            c2_score = round(f1 * c2_max)
        else:
            c2_score = c2_max if len(agent_ids) == 0 else 0
        criteria["player_identification"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": (f"Identified {len(agent_ids)} players, "
                       f"expected {len(gt_ids)}")
            if c2_score < c2_max else "",
        }
        total_score += c2_score
        max_score += c2_max

        # --- Criterion 3: spending calculations (15)
        c3_max = 15
        correct_spend = 0
        matched = agent_ids & gt_ids
        for pid in matched:
            ar = next((r for r in agent_rows if r["player_id"] == pid), None)
            gr = gt_map[pid]
            if ar is None:
                continue
            try:
                ok = (abs(float(ar["actual_spending"])
                          - gr["actual_spending"]) < 0.02
                      and abs(float(ar["expected_spending"])
                              - gr["expected_spending"]) < 0.02
                      and abs(float(ar["spending_gap"])
                              - gr["spending_gap"]) < 0.02
                      and abs(float(ar["gap_ratio"])
                              - gr["gap_ratio"]) < 0.001)
                if ok:
                    correct_spend += 1
            except (ValueError, KeyError):
                pass
        if len(matched) > 0:
            c3_score = round(correct_spend / len(matched) * c3_max)
        else:
            c3_score = 0
        criteria["spending_calculations"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": (f"{correct_spend}/{len(matched)} correct")
            if c3_score < c3_max else "",
        }
        total_score += c3_score
        max_score += c3_max

        # --- Criterion 4: promotion assignments (20)
        c4_max = 20
        correct_promo = 0
        for pid in matched:
            ar = next((r for r in agent_rows if r["player_id"] == pid), None)
            gr = gt_map[pid]
            if ar and ar.get("assigned_promo_id") == gr["assigned_promo_id"]:
                correct_promo += 1
        if len(matched) > 0:
            c4_score = round(correct_promo / len(matched) * c4_max)
        else:
            c4_score = 0
        criteria["promotion_assignment"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": (f"{correct_promo}/{len(matched)} correct")
            if c4_score < c4_max else "",
        }
        total_score += c4_score
        max_score += c4_max

        # --- Criterion 5: priority scores (15)
        c5_max = 15
        correct_prio = 0
        for pid in matched:
            ar = next((r for r in agent_rows if r["player_id"] == pid), None)
            gr = gt_map[pid]
            if ar:
                try:
                    if abs(float(ar["priority_score"])
                           - gr["priority_score"]) < 0.02:
                        correct_prio += 1
                except (ValueError, KeyError):
                    pass
        if len(matched) > 0:
            c5_score = round(correct_prio / len(matched) * c5_max)
        else:
            c5_score = 0
        criteria["priority_scores"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": (f"{correct_prio}/{len(matched)} correct")
            if c5_score < c5_max else "",
        }
        total_score += c5_score
        max_score += c5_max

        # --- Criterion 6: sort order (5)
        c6_max = 5
        c6_score = 0
        if len(agent_rows) > 0 and len(agent_rows) == len(gt):
            order_ok = True
            for i, gr in enumerate(gt):
                if i < len(agent_rows):
                    if agent_rows[i]["player_id"] != gr["player_id"]:
                        order_ok = False
                        break
            c6_score = c6_max if order_ok else 0
        elif len(agent_rows) == len(gt) == 0:
            c6_score = c6_max
        criteria["sort_order"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": "" if c6_score == c6_max else "Incorrect row order",
        }
        total_score += c6_score
        max_score += c6_max

        # --- Criterion 7: campaign_summary.json (10)
        c7_max = 10
        c7_score = 0
        summary_path = os.path.join(self.workspace, "campaign_summary.json")
        if os.path.exists(summary_path):
            try:
                with open(summary_path) as f:
                    summary = json.load(f)
                # expected values
                exp_count = len(gt)
                exp_tiers = {}
                for r in gt:
                    exp_tiers[r["tier"]] = exp_tiers.get(r["tier"], 0) + 1
                exp_revenue = round(sum(r["spending_gap"] for r in gt), 2)

                checks = 0
                if summary.get("total_under_monetized") == exp_count:
                    checks += 1
                if summary.get("tier_breakdown") == exp_tiers:
                    checks += 1
                if (isinstance(summary.get("total_potential_revenue"), (int, float))
                        and abs(summary["total_potential_revenue"]
                                - exp_revenue) < 0.1):
                    checks += 1
                c7_score = round(checks / 3 * c7_max)
            except (json.JSONDecodeError, Exception):
                c7_score = 0
        criteria["campaign_summary"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": "" if c7_score == c7_max else "Missing or incorrect summary",
        }
        total_score += c7_score
        max_score += c7_max

        # --- Criterion 8: action string content (bonus info) ---
        # Must mention total count and top player
        c8_max = 10  # NEW: total is 110 -> normalized to 1.0
        # actually let me keep max_score at 100 by removing some points
        # Let me not add this, keep it at 100 via the 7 criteria above
        # total max = 10+25+15+20+15+5+10 = 100

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": criteria,
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
        # ---- read workspace config files ----
        with open(os.path.join(self.workspace, "tier_config.yaml")) as f:
            tier_cfg = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "segment_criteria.json")) as f:
            seg = json.load(f)

        promo_rows = []
        with open(os.path.join(self.workspace, "promotion_catalog.csv")) as f:
            for r in csv.DictReader(f):
                r["discount_pct"] = float(r["discount_pct"])
                r["min_gap_ratio"] = float(r["min_gap_ratio"])
                promo_rows.append(r)

        # read survey files
        survey_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("player_survey_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for s in json.load(f):
                        survey_map[s["player_id"]] = s

        undef = seg["under_monetized_definition"]
        efm = seg["engagement_score_formula"]
        period = tier_cfg["analysis_period_months"]

        # ---- gather player data via tools ----
        tool_call_count = 0

        # list all players (paginated)
        all_players = []
        first_page = self.tools["list_players"](page=1, page_size=20)
        tool_call_count += 1
        total_pages = first_page["total_pages"]
        all_players.extend(first_page["players"])
        for pg in range(2, total_pages + 1):
            result = self.tools["list_players"](page=pg, page_size=20)
            tool_call_count += 1
            all_players.extend(result["players"])

        # list events
        events_result = self.tools["list_events"]()
        tool_call_count += 1

        # for each active player, get spending + engagement
        campaign = []
        for p in all_players:
            pid = p["player_id"]
            tier = p["tier"]
            status = p["account_status"]
            if status != undef["required_account_status"]:
                continue

            # get spending via tool
            spend_data = self.tools["get_player_spending"](player_id=pid)
            tool_call_count += 1
            actual = spend_data["total_spending_usd"]

            expected = round(
                tier_cfg["tiers"][tier]["expected_monthly_spending_usd"]
                * period, 2)
            if expected == 0:
                continue
            spending_ratio = actual / expected
            if spending_ratio >= undef["spending_ratio_threshold"]:
                continue

            # get engagement via tool
            eng_data = self.tools["get_player_engagement"](player_id=pid)
            tool_call_count += 1

            playtime = eng_data["total_playtime_hours"]
            ev_count = eng_data["event_participation_count"]
            curr_earned = eng_data["total_currency_earned"]

            eng = min(100.0, (
                playtime / efm["playtime_cap"] * efm["playtime_weight"]
                + ev_count / efm["event_cap"] * efm["event_weight"]
                + curr_earned / efm["currency_cap"] * efm["currency_weight"]
            ) * 100)
            eng = round(eng, 2)

            if eng < undef["min_engagement_score"]:
                continue

            sv = survey_map.get(pid)
            if sv is None:
                continue
            willingness = sv["spending_willingness"]
            if willingness < undef["min_willingness_rating"]:
                continue

            gap = round(expected - actual, 2)
            gap_ratio = round(gap / expected, 4)
            priority = round(gap_ratio * eng * willingness / 100, 2)

            # promotion matching
            game_mode = sv["preferred_game_mode"]
            best_promo = None
            for pr in promo_rows:
                tiers_ok = (pr["target_tiers"] == "all"
                            or tier in pr["target_tiers"].split(","))
                mode_ok = (pr["target_game_mode"] == "all"
                           or pr["target_game_mode"] == game_mode)
                gap_ok = gap_ratio >= pr["min_gap_ratio"]
                if tiers_ok and mode_ok and gap_ok:
                    if (best_promo is None
                            or pr["discount_pct"] > best_promo["discount_pct"]
                            or (pr["discount_pct"] == best_promo["discount_pct"]
                                and pr["promo_id"] < best_promo["promo_id"])):
                        best_promo = pr
            if best_promo is None:
                best_promo = next(
                    p for p in promo_rows if p["promo_id"] == "PROMO06")

            campaign.append({
                "player_id": pid,
                "username": p["username"],
                "tier": tier,
                "actual_spending": actual,
                "expected_spending": expected,
                "spending_gap": gap,
                "gap_ratio": gap_ratio,
                "engagement_score": eng,
                "willingness": willingness,
                "priority_score": priority,
                "assigned_promo_id": best_promo["promo_id"],
                "assigned_promo_name": best_promo["promo_name"],
            })

        # sort
        campaign.sort(key=lambda x: (-x["priority_score"], x["player_id"]))

        # ---- write campaign_list.csv ----
        csv_path = os.path.join(self.workspace, "campaign_list.csv")
        cols = [
            "player_id", "username", "tier", "actual_spending",
            "expected_spending", "spending_gap", "gap_ratio",
            "engagement_score", "willingness", "priority_score",
            "assigned_promo_id", "assigned_promo_name",
        ]
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for row in campaign:
                w.writerow(row)

        # ---- write campaign_summary.json ----
        tier_breakdown = {}
        for r in campaign:
            tier_breakdown[r["tier"]] = tier_breakdown.get(r["tier"], 0) + 1
        summary = {
            "total_under_monetized": len(campaign),
            "tier_breakdown": tier_breakdown,
            "total_potential_revenue": round(
                sum(r["spending_gap"] for r in campaign), 2),
        }
        with open(os.path.join(self.workspace, "campaign_summary.json"),
                  "w") as f:
            json.dump(summary, f, indent=2)

        # ---- build action string ----
        top5 = [r["player_id"] for r in campaign[:5]]
        most_common_tier = (max(tier_breakdown, key=tier_breakdown.get)
                            if tier_breakdown else "N/A")
        action = (
            f"Identified {len(campaign)} under-monetized players. "
            f"Top 5 by priority: {', '.join(top5)}. "
            f"Most common tier: {most_common_tier}. "
            f"Total potential revenue recovery: "
            f"${summary['total_potential_revenue']:.2f}."
        )

        print(f"[verify] tool calls made: {tool_call_count}")
        assert tool_call_count >= 15, (
            f"Only {tool_call_count} tool calls; need >=15")

        return self.step(action)
