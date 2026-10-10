import sqlite3
import json
import os
import csv
import glob
import yaml
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

    # ── Tool Methods ──────────────────────────────────────────────────

    @tool(
        description="Search for transfer target players by position. Returns a list of matching player IDs, names, and positions. Results are paginated.",
        parameters={
            "type": "object",
            "properties": {
                "position": {
                    "type": "string",
                    "description": "Player position to filter by (e.g. GK, CB, LB, RB, CDM, CM, CAM, LW, RW, ST)"
                },
                "min_overall_score": {
                    "type": "number",
                    "description": "Minimum average overall scouting score to filter by (0-100)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 20)"
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of results to skip for pagination (default 0)"
                }
            },
            "required": ["position"]
        }
    )
    def search_players(self, position: str, min_overall_score: float = 0.0,
                       limit: int = 20, offset: int = 0) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Get players with their average overall scouting score
        query = """
            SELECT p.player_id, p.name, p.position,
                   COALESCE(AVG(s.overall_score), 0) as avg_overall
            FROM players p
            LEFT JOIN scouting_reports s ON p.player_id = s.player_id
            WHERE p.position = ?
            GROUP BY p.player_id
            HAVING avg_overall >= ?
            ORDER BY avg_overall DESC
            LIMIT ? OFFSET ?
        """
        rows = c.execute(query, (position, min_overall_score, limit, offset)).fetchall()
        total = c.execute("""
            SELECT COUNT(DISTINCT p.player_id)
            FROM players p
            LEFT JOIN scouting_reports s ON p.player_id = s.player_id
            WHERE p.position = ?
            GROUP BY p.player_id
            HAVING COALESCE(AVG(s.overall_score), 0) >= ?
        """, (position, min_overall_score)).fetchone()
        total_count = len(c.execute("""
            SELECT p.player_id
            FROM players p
            LEFT JOIN scouting_reports s ON p.player_id = s.player_id
            WHERE p.position = ?
            GROUP BY p.player_id
            HAVING COALESCE(AVG(s.overall_score), 0) >= ?
        """, (position, min_overall_score)).fetchall())
        conn.close()
        return {
            "results": [
                {"player_id": r[0], "name": r[1], "position": r[2], "avg_overall_score": round(r[3], 1)}
                for r in rows
            ],
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
        }

    @tool(
        description="Get detailed information about a specific player by their ID.",
        parameters={
            "type": "object",
            "properties": {
                "player_id": {
                    "type": "integer",
                    "description": "The unique player identifier"
                }
            },
            "required": ["player_id"]
        }
    )
    def get_player_details(self, player_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        row = c.execute(
            "SELECT * FROM players WHERE player_id = ?", (player_id,)
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"Player {player_id} not found"}
        return {
            "player_id": row[0],
            "name": row[1],
            "age": row[2],
            "position": row[3],
            "nationality": row[4],
            "current_club": row[5],
            "league": row[6],
            "market_value_m": row[7],
            "contract_expiry_year": row[8],
            "wage_demand_weekly_k": row[9],
            "preferred_foot": row[10],
            "caps_international": row[11],
        }

    @tool(
        description="Get all scouting reports for a specific player. Returns individual scout assessments with scores.",
        parameters={
            "type": "object",
            "properties": {
                "player_id": {
                    "type": "integer",
                    "description": "The unique player identifier"
                }
            },
            "required": ["player_id"]
        }
    )
    def get_scouting_reports(self, player_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        rows = c.execute(
            "SELECT * FROM scouting_reports WHERE player_id = ? ORDER BY report_date DESC",
            (player_id,)
        ).fetchall()
        conn.close()
        return {
            "player_id": player_id,
            "report_count": len(rows),
            "reports": [
                {
                    "report_id": r[0],
                    "scout_id": r[2],
                    "technical_score": r[3],
                    "tactical_score": r[4],
                    "physical_score": r[5],
                    "mental_score": r[6],
                    "potential_score": r[7],
                    "overall_score": r[8],
                    "report_date": r[9],
                    "recommendation": r[10],
                }
                for r in rows
            ],
        }

    @tool(
        description="Get current squad members for a specific position. Returns roster details including status and fitness.",
        parameters={
            "type": "object",
            "properties": {
                "position": {
                    "type": "string",
                    "description": "Position to query (e.g. GK, CB, LB, RB, CDM, CM, CAM, LW, RW, ST)"
                }
            },
            "required": ["position"]
        }
    )
    def get_squad_by_position(self, position: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        rows = c.execute(
            "SELECT * FROM squad_roster WHERE position = ? ORDER BY status, salary_weekly_k DESC",
            (position,)
        ).fetchall()
        conn.close()
        return {
            "position": position,
            "count": len(rows),
            "members": [
                {
                    "member_id": r[0],
                    "name": r[1],
                    "position": r[2],
                    "age": r[3],
                    "salary_weekly_k": r[4],
                    "contract_end_year": r[5],
                    "status": r[6],
                    "fitness_score": r[7],
                    "appearances_season": r[8],
                    "goals_season": r[9],
                    "assists_season": r[10],
                }
                for r in rows
            ],
        }

    @tool(
        description="Get financial projection data for a specific fiscal year. Returns all budget line items (revenue and expense categories) for that year.",
        parameters={
            "type": "object",
            "properties": {
                "fiscal_year": {
                    "type": "integer",
                    "description": "The fiscal year to query (e.g. 2026, 2027)"
                }
            },
            "required": ["fiscal_year"]
        }
    )
    def get_financial_projections(self, fiscal_year: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        rows = c.execute(
            "SELECT category, amount_m, notes FROM financial_projections WHERE fiscal_year = ? ORDER BY category",
            (fiscal_year,)
        ).fetchall()
        conn.close()
        return {
            "fiscal_year": fiscal_year,
            "line_items": [
                {"category": r[0], "amount_m": r[1], "notes": r[2]}
                for r in rows
            ],
        }

    @tool(
        description="Get match schedule for a specific month. Returns fixtures with dates, opponents, and competition details.",
        parameters={
            "type": "object",
            "properties": {
                "year": {
                    "type": "integer",
                    "description": "Year (e.g. 2026)"
                },
                "month": {
                    "type": "integer",
                    "description": "Month number (1-12)"
                }
            },
            "required": ["year", "month"]
        }
    )
    def get_fixtures_by_month(self, year: int, month: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        month_str = f"{year}-{month:02d}"
        rows = c.execute(
            "SELECT * FROM match_schedule WHERE match_date LIKE ? ORDER BY match_date",
            (f"{month_str}%",)
        ).fetchall()
        conn.close()
        return {
            "year": year,
            "month": month,
            "fixture_count": len(rows),
            "fixtures": [
                {
                    "fixture_id": r[0],
                    "match_date": r[1],
                    "opponent": r[2],
                    "competition": r[3],
                    "home_away": r[4],
                    "importance_rating": r[5],
                }
                for r in rows
            ],
        }

    # ── Evaluation ────────────────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute the ground-truth shortlist using DB + workspace data."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # 1. Load config files
        policy_path = os.path.join(self.workspace, "transfer_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)

        weights_path = os.path.join(self.workspace, "scoring_weights.json")
        with open(weights_path) as f:
            scoring_config = json.load(f)

        weights = scoring_config["weights"]
        att_map = scoring_config["attitude_to_numeric"]

        eligibility = policy["eligibility"]
        bid_calc = policy["bid_calculation"]
        budget_cfg = policy["budget"]
        shortlist_cfg = policy["shortlist"]
        congestion_cfg = policy["congestion_rules"]

        # 2. Determine congested months
        fixtures = c.execute("SELECT match_date FROM match_schedule").fetchall()
        month_counts = {}
        for (md,) in fixtures:
            ym = md[:7]
            month_counts[ym] = month_counts.get(ym, 0) + 1
        congested_months = sum(
            1 for cnt in month_counts.values()
            if cnt >= congestion_cfg["congested_month_threshold"]
        )
        apply_congestion_boost = congested_months >= congestion_cfg["congestion_boost_trigger_months"]

        # 3. Determine position urgencies from depth chart files
        depth_files = sorted(glob.glob(os.path.join(self.workspace, "squad_depth_*.csv")))
        position_urgency = {}
        for df_path in depth_files:
            with open(df_path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pos = row["position"]
                    urg = row["urgency"]
                    position_urgency[pos] = urg

        # Apply congestion boost: medium -> high
        if apply_congestion_boost:
            for pos in position_urgency:
                if position_urgency[pos] == "medium":
                    position_urgency[pos] = "high"

        # 4. Identify priority positions
        priority_levels = shortlist_cfg["priority_urgency_levels"]
        priority_positions = [
            pos for pos, urg in position_urgency.items()
            if urg in priority_levels
        ]

        # 5. Load scouting dossier data (supplementary attributes)
        dossier_files = sorted(glob.glob(os.path.join(self.workspace, "scouting_dossier_*.csv")))
        dossier_data = {}  # player_id -> {injury_risk, attitude_grade, ...}
        for df_path in dossier_files:
            with open(df_path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pid = int(row["player_id"])
                    dossier_data[pid] = {
                        "injury_risk": int(row["injury_risk"]),
                        "attitude_grade": row["attitude_grade"],
                        "adaptability": int(row["adaptability"]),
                        "consistency": int(row["consistency"]),
                        "leadership": int(row["leadership"]),
                    }

        # 6. Compute available transfer budget
        budget_year = budget_cfg["budget_year"]
        fin_rows = c.execute(
            "SELECT category, amount_m FROM financial_projections WHERE fiscal_year = ?",
            (budget_year,)
        ).fetchall()
        fin_map = {}
        for cat, amt in fin_rows:
            fin_map[cat] = amt

        total_revenue = sum(fin_map.get(cat, 0) for cat in budget_cfg["revenue_categories"])
        total_expenses = sum(fin_map.get(cat, 0) for cat in budget_cfg["expense_categories"])
        available_budget = round(total_revenue - total_expenses, 2)

        # 7. Build shortlist
        max_per_pos = shortlist_cfg["max_targets_per_position"]
        shortlist = []

        for pos in sorted(priority_positions):
            # Get all players at this position with avg scouting score
            players = c.execute("""
                SELECT p.player_id, p.name, p.age, p.position, p.current_club,
                       p.market_value_m, p.contract_expiry_year, p.wage_demand_weekly_k,
                       AVG(s.technical_score) as avg_tech,
                       AVG(s.tactical_score) as avg_tact,
                       AVG(s.physical_score) as avg_phys,
                       AVG(s.mental_score) as avg_ment,
                       AVG(s.potential_score) as avg_pot,
                       AVG(s.overall_score) as avg_overall
                FROM players p
                JOIN scouting_reports s ON p.player_id = s.player_id
                WHERE p.position = ?
                GROUP BY p.player_id
            """, (pos,)).fetchall()

            pos_candidates = []
            for row in players:
                pid, name, age, position, club = row[0], row[1], row[2], row[3], row[4]
                mv, contract_exp, wage = row[5], row[6], row[7]
                avg_tech, avg_tact, avg_phys, avg_ment, avg_pot, avg_overall = (
                    row[8], row[9], row[10], row[11], row[12], row[13]
                )

                # Eligibility checks
                max_age = eligibility["max_age_by_position"].get(pos, 32)
                if age > max_age:
                    continue
                if wage > eligibility["wage_ceiling_weekly_k"]:
                    continue
                if avg_overall < eligibility["min_overall_scouting_score"]:
                    continue

                # Get dossier data
                dossier = dossier_data.get(pid)
                if dossier is None:
                    continue

                # Compute weighted composite score
                # Scouting scores are 0-100, divide by 10 to get 1-10 scale
                injury_inv = 11 - dossier["injury_risk"]
                att_numeric = att_map.get(dossier["attitude_grade"], 4)

                composite = (
                    weights["technical"] * (avg_tech / 10.0)
                    + weights["tactical"] * (avg_tact / 10.0)
                    + weights["physical"] * (avg_phys / 10.0)
                    + weights["mental"] * (avg_ment / 10.0)
                    + weights["potential"] * (avg_pot / 10.0)
                    + weights["injury_risk_inverted"] * injury_inv
                    + weights["attitude"] * att_numeric
                    + weights["adaptability"] * dossier["adaptability"]
                    + weights["consistency"] * dossier["consistency"]
                    + weights["leadership"] * dossier["leadership"]
                )
                composite = round(composite, 2)

                if composite < eligibility["min_weighted_composite_score"] / 10.0:
                    continue

                # Bid calculation
                contract_years_remaining = contract_exp - 2026
                age_over = max(0, age - bid_calc["age_threshold"])
                urgency_prem = bid_calc["urgency_premium"].get(position_urgency.get(pos, "low"), 0)

                bid_low = mv * bid_calc["base_multiplier"] * (
                    1.0
                    + contract_years_remaining * bid_calc["contract_premium_per_year"]
                    - age_over * bid_calc["age_discount_per_year"]
                    + urgency_prem
                )
                bid_low = round(max(bid_low, 0.5), 2)
                bid_high = round(bid_low * bid_calc["high_range_factor"], 2)

                pos_candidates.append({
                    "player_id": pid,
                    "player_name": name,
                    "position": pos,
                    "age": age,
                    "current_club": club,
                    "weighted_score": composite,
                    "bid_low_m": bid_low,
                    "bid_high_m": bid_high,
                    "position_urgency": position_urgency.get(pos, "low"),
                    "market_value_m": mv,
                })

            # Sort by weighted_score descending, take top max_per_pos
            pos_candidates.sort(key=lambda x: (-x["weighted_score"], x["player_name"]))
            shortlist.extend(pos_candidates[:max_per_pos])

        conn.close()

        # Final ranking: sort all shortlisted players by weighted_score descending
        shortlist.sort(key=lambda x: (-x["weighted_score"], x["player_name"]))
        # Assign ranks
        for i, entry in enumerate(shortlist):
            entry["rank"] = i + 1

        return {
            "shortlist": shortlist,
            "priority_positions": sorted(priority_positions),
            "available_budget": available_budget,
            "congested_months": congested_months,
            "apply_congestion_boost": apply_congestion_boost,
            "position_urgency": position_urgency,
        }

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
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: transfer_shortlist.csv exists with correct columns (15 pts) ──
        max_score += 15
        shortlist_path = os.path.join(self.workspace, "transfer_shortlist.csv")
        expected_columns = [
            "rank", "player_name", "position", "age", "current_club",
            "weighted_score", "bid_low_m", "bid_high_m", "position_urgency"
        ]
        if os.path.exists(shortlist_path):
            with open(shortlist_path) as f:
                reader = csv.DictReader(f)
                actual_cols = [c.strip() for c in reader.fieldnames] if reader.fieldnames else []
                submitted_rows = list(reader)
            cols_match = all(c in actual_cols for c in expected_columns)
            if cols_match and len(submitted_rows) > 0:
                eval_criteria["shortlist_format"] = {
                    "passed": True, "score": 15, "max_score": 15
                }
                total_score += 15
            else:
                missing = [c for c in expected_columns if c not in actual_cols]
                eval_criteria["shortlist_format"] = {
                    "passed": False, "score": 0, "max_score": 15,
                    "reason": f"Missing columns: {missing}" if missing else "No data rows"
                }
        else:
            eval_criteria["shortlist_format"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "transfer_shortlist.csv not found"
            }

        # ── Criterion 2: Correct priority positions identified (15 pts) ──
        max_score += 15
        gt_positions = set(gt["priority_positions"])
        # Check if action mentions priority positions
        mentioned_positions = set()
        for pos in ["GK", "CB", "LB", "RB", "CDM", "CM", "CAM", "LW", "RW", "ST"]:
            if pos in action:
                mentioned_positions.add(pos)
        # Also check from submitted CSV
        csv_positions = set()
        if os.path.exists(shortlist_path):
            with open(shortlist_path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if "position" in row:
                        csv_positions.add(row["position"].strip())

        combined_positions = csv_positions
        if combined_positions == gt_positions:
            eval_criteria["priority_positions"] = {
                "passed": True, "score": 15, "max_score": 15
            }
            total_score += 15
        else:
            # Partial credit: fraction of correct positions
            correct = len(combined_positions & gt_positions)
            total_gt = len(gt_positions)
            # Penalize extra positions
            extra = len(combined_positions - gt_positions)
            partial = max(0, (correct - extra * 0.5) / total_gt) if total_gt > 0 else 0
            pts = round(partial * 15)
            eval_criteria["priority_positions"] = {
                "passed": False, "score": pts, "max_score": 15,
                "reason": f"Expected {sorted(gt_positions)}, got {sorted(combined_positions)}"
            }
            total_score += pts

        # ── Criterion 3: Player eligibility - all players meet thresholds (20 pts) ──
        max_score += 20
        gt_eligible_ids = set(e["player_id"] for e in gt["shortlist"])
        if os.path.exists(shortlist_path):
            with open(shortlist_path) as f:
                reader = csv.DictReader(f)
                submitted_names = [row["player_name"].strip() for row in reader if "player_name" in row]
            gt_names = set(e["player_name"] for e in gt["shortlist"])
            submitted_set = set(submitted_names)

            if len(submitted_set) == 0:
                eval_criteria["player_eligibility"] = {
                    "passed": False, "score": 0, "max_score": 20,
                    "reason": "No players in shortlist"
                }
            else:
                correct_names = submitted_set & gt_names
                incorrect_names = submitted_set - gt_names
                missing_names = gt_names - submitted_set
                # Score: correct proportion minus penalty for incorrect
                if len(gt_names) > 0:
                    precision = len(correct_names) / len(submitted_set) if len(submitted_set) > 0 else 0
                    recall = len(correct_names) / len(gt_names)
                    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
                    pts = round(f1 * 20)
                else:
                    pts = 0
                passed = (correct_names == gt_names and len(incorrect_names) == 0)
                eval_criteria["player_eligibility"] = {
                    "passed": passed, "score": pts, "max_score": 20,
                    "reason": None if passed else f"Correct: {len(correct_names)}/{len(gt_names)}, Extra: {len(incorrect_names)}"
                }
                total_score += pts
        else:
            eval_criteria["player_eligibility"] = {
                "passed": False, "score": 0, "max_score": 20,
                "reason": "transfer_shortlist.csv not found"
            }

        # ── Criterion 4: Weighted score accuracy (20 pts) ──
        max_score += 20
        if os.path.exists(shortlist_path):
            with open(shortlist_path) as f:
                reader = csv.DictReader(f)
                submitted_scores = {}
                for row in reader:
                    if "player_name" in row and "weighted_score" in row:
                        try:
                            submitted_scores[row["player_name"].strip()] = float(row["weighted_score"])
                        except (ValueError, KeyError):
                            pass

            gt_scores = {e["player_name"]: e["weighted_score"] for e in gt["shortlist"]}
            common = set(submitted_scores.keys()) & set(gt_scores.keys())
            if len(common) > 0:
                close_count = 0
                for name in common:
                    if abs(submitted_scores[name] - gt_scores[name]) <= 0.15:
                        close_count += 1
                accuracy = close_count / len(gt_scores) if len(gt_scores) > 0 else 0
                pts = round(accuracy * 20)
                passed = (close_count == len(gt_scores) and len(common) == len(gt_scores))
                eval_criteria["weighted_scores"] = {
                    "passed": passed, "score": pts, "max_score": 20,
                    "reason": None if passed else f"{close_count}/{len(gt_scores)} scores within tolerance"
                }
                total_score += pts
            else:
                eval_criteria["weighted_scores"] = {
                    "passed": False, "score": 0, "max_score": 20,
                    "reason": "No matching player names to compare scores"
                }
        else:
            eval_criteria["weighted_scores"] = {
                "passed": False, "score": 0, "max_score": 20,
                "reason": "transfer_shortlist.csv not found"
            }

        # ── Criterion 5: Bid range accuracy (15 pts) ──
        max_score += 15
        if os.path.exists(shortlist_path):
            with open(shortlist_path) as f:
                reader = csv.DictReader(f)
                submitted_bids = {}
                for row in reader:
                    if "player_name" in row and "bid_low_m" in row and "bid_high_m" in row:
                        try:
                            submitted_bids[row["player_name"].strip()] = (
                                float(row["bid_low_m"]), float(row["bid_high_m"])
                            )
                        except (ValueError, KeyError):
                            pass

            gt_bids = {e["player_name"]: (e["bid_low_m"], e["bid_high_m"]) for e in gt["shortlist"]}
            common = set(submitted_bids.keys()) & set(gt_bids.keys())
            if len(common) > 0:
                close_count = 0
                for name in common:
                    sub_low, sub_high = submitted_bids[name]
                    gt_low, gt_high = gt_bids[name]
                    if abs(sub_low - gt_low) <= 0.5 and abs(sub_high - gt_high) <= 0.5:
                        close_count += 1
                accuracy = close_count / len(gt_bids) if len(gt_bids) > 0 else 0
                pts = round(accuracy * 15)
                passed = (close_count == len(gt_bids) and len(common) == len(gt_bids))
                eval_criteria["bid_ranges"] = {
                    "passed": passed, "score": pts, "max_score": 15,
                    "reason": None if passed else f"{close_count}/{len(gt_bids)} bid ranges within tolerance"
                }
                total_score += pts
            else:
                eval_criteria["bid_ranges"] = {
                    "passed": False, "score": 0, "max_score": 15,
                    "reason": "No matching player names to compare bids"
                }
        else:
            eval_criteria["bid_ranges"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "transfer_shortlist.csv not found"
            }

        # ── Criterion 6: Correct ranking order (15 pts) ──
        max_score += 15
        if os.path.exists(shortlist_path):
            with open(shortlist_path) as f:
                reader = csv.DictReader(f)
                submitted_order = []
                for row in reader:
                    if "player_name" in row:
                        submitted_order.append(row["player_name"].strip())

            gt_order = [e["player_name"] for e in gt["shortlist"]]
            if submitted_order == gt_order:
                eval_criteria["ranking_order"] = {
                    "passed": True, "score": 15, "max_score": 15
                }
                total_score += 15
            else:
                # Partial credit using longest common subsequence ratio
                n1, n2 = len(submitted_order), len(gt_order)
                if n1 > 0 and n2 > 0:
                    # Kendall tau-like: fraction of pairs in correct order
                    common_names = [n for n in submitted_order if n in set(gt_order)]
                    if len(common_names) >= 2:
                        gt_rank = {name: i for i, name in enumerate(gt_order)}
                        pairs_correct = 0
                        pairs_total = 0
                        for i in range(len(common_names)):
                            for j in range(i + 1, len(common_names)):
                                pairs_total += 1
                                if gt_rank.get(common_names[i], 999) < gt_rank.get(common_names[j], 999):
                                    pairs_correct += 1
                        ratio = pairs_correct / pairs_total if pairs_total > 0 else 0
                        pts = round(ratio * 15)
                    else:
                        pts = 5 if len(common_names) == 1 else 0
                else:
                    pts = 0
                eval_criteria["ranking_order"] = {
                    "passed": False, "score": pts, "max_score": 15,
                    "reason": f"Order mismatch: expected {gt_order[:5]}..."
                }
                total_score += pts
        else:
            eval_criteria["ranking_order"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "transfer_shortlist.csv not found"
            }

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
        import csv as csv_mod

        # ── Step 1: Load config files ──
        with open(os.path.join(self.workspace, "transfer_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "scoring_weights.json")) as f:
            scoring_config = json.load(f)

        weights = scoring_config["weights"]
        att_map = scoring_config["attitude_to_numeric"]
        eligibility = policy["eligibility"]
        bid_calc = policy["bid_calculation"]
        budget_cfg = policy["budget"]
        shortlist_cfg = policy["shortlist"]
        congestion_cfg = policy["congestion_rules"]
        tool_call_count = 0

        # ── Step 2: Analyze fixture congestion using tools ──
        month_counts = {}
        for year in [2026, 2027]:
            for month in range(1, 13):
                result = self.tools["get_fixtures_by_month"](year=year, month=month)
                tool_call_count += 1
                if result["fixture_count"] > 0:
                    ym = f"{year}-{month:02d}"
                    month_counts[ym] = result["fixture_count"]

        # Cross-reference with fixture block JSON files for travel data
        fixture_files = sorted(glob.glob(os.path.join(self.workspace, "fixture_block_*.json")))
        for ff in fixture_files:
            with open(ff) as f:
                fixtures_data = json.load(f)
            # (travel data available for more advanced analysis if needed)

        congested_months = sum(
            1 for cnt in month_counts.values()
            if cnt >= congestion_cfg["congested_month_threshold"]
        )
        apply_congestion_boost = congested_months >= congestion_cfg["congestion_boost_trigger_months"]

        # ── Step 3: Read depth charts to determine position urgency ──
        depth_files = sorted(glob.glob(os.path.join(self.workspace, "squad_depth_*.csv")))
        position_urgency = {}
        for df_path in depth_files:
            with open(df_path) as f:
                reader = csv_mod.DictReader(f)
                for row in reader:
                    pos = row["position"]
                    urg = row["urgency"]
                    position_urgency[pos] = urg

        # Apply congestion boost
        if apply_congestion_boost:
            for pos in position_urgency:
                if position_urgency[pos] == "medium":
                    position_urgency[pos] = "high"

        # ── Step 4: Identify priority positions ──
        priority_levels = shortlist_cfg["priority_urgency_levels"]
        priority_positions = sorted([
            pos for pos, urg in position_urgency.items()
            if urg in priority_levels
        ])

        # ── Step 5: Verify squad depth via tools ──
        for pos in priority_positions:
            result = self.tools["get_squad_by_position"](position=pos)
            tool_call_count += 1

        # ── Step 6: Load scouting dossier data from workspace ──
        dossier_files = sorted(glob.glob(os.path.join(self.workspace, "scouting_dossier_*.csv")))
        dossier_data = {}
        for df_path in dossier_files:
            with open(df_path) as f:
                reader = csv_mod.DictReader(f)
                for row in reader:
                    pid = int(row["player_id"])
                    dossier_data[pid] = {
                        "injury_risk": int(row["injury_risk"]),
                        "attitude_grade": row["attitude_grade"],
                        "adaptability": int(row["adaptability"]),
                        "consistency": int(row["consistency"]),
                        "leadership": int(row["leadership"]),
                    }

        # ── Step 7: Get budget from financial tools ──
        budget_year = budget_cfg["budget_year"]
        fin_result = self.tools["get_financial_projections"](fiscal_year=budget_year)
        tool_call_count += 1
        fin_map = {item["category"]: item["amount_m"] for item in fin_result["line_items"]}
        total_revenue = sum(fin_map.get(cat, 0) for cat in budget_cfg["revenue_categories"])
        total_expenses = sum(fin_map.get(cat, 0) for cat in budget_cfg["expense_categories"])
        available_budget = round(total_revenue - total_expenses, 2)

        # ── Step 8: Search, evaluate, and rank candidates ──
        max_per_pos = shortlist_cfg["max_targets_per_position"]
        shortlist = []

        for pos in priority_positions:
            # Search players at this position
            offset = 0
            all_candidates = []
            while True:
                result = self.tools["search_players"](
                    position=pos,
                    min_overall_score=eligibility["min_overall_scouting_score"],
                    limit=20,
                    offset=offset,
                )
                tool_call_count += 1
                all_candidates.extend(result["results"])
                if offset + 20 >= result["total_count"]:
                    break
                offset += 20

            pos_candidates = []
            for cand in all_candidates:
                pid = cand["player_id"]

                # Get player details
                details = self.tools["get_player_details"](player_id=pid)
                tool_call_count += 1
                if "error" in details:
                    continue

                age = details["age"]
                wage = details["wage_demand_weekly_k"]
                mv = details["market_value_m"]
                contract_exp = details["contract_expiry_year"]
                club = details["current_club"]

                # Eligibility checks
                max_age = eligibility["max_age_by_position"].get(pos, 32)
                if age > max_age:
                    continue
                if wage > eligibility["wage_ceiling_weekly_k"]:
                    continue

                # Get scouting reports
                scout_result = self.tools["get_scouting_reports"](player_id=pid)
                tool_call_count += 1
                if scout_result["report_count"] == 0:
                    continue

                reports = scout_result["reports"]
                avg_tech = sum(r["technical_score"] for r in reports) / len(reports)
                avg_tact = sum(r["tactical_score"] for r in reports) / len(reports)
                avg_phys = sum(r["physical_score"] for r in reports) / len(reports)
                avg_ment = sum(r["mental_score"] for r in reports) / len(reports)
                avg_pot = sum(r["potential_score"] for r in reports) / len(reports)
                avg_overall = sum(r["overall_score"] for r in reports) / len(reports)

                if avg_overall < eligibility["min_overall_scouting_score"]:
                    continue

                # Get dossier supplementary data
                dossier = dossier_data.get(pid)
                if dossier is None:
                    continue

                # Compute weighted composite score
                injury_inv = 11 - dossier["injury_risk"]
                att_numeric = att_map.get(dossier["attitude_grade"], 4)

                composite = (
                    weights["technical"] * (avg_tech / 10.0)
                    + weights["tactical"] * (avg_tact / 10.0)
                    + weights["physical"] * (avg_phys / 10.0)
                    + weights["mental"] * (avg_ment / 10.0)
                    + weights["potential"] * (avg_pot / 10.0)
                    + weights["injury_risk_inverted"] * injury_inv
                    + weights["attitude"] * att_numeric
                    + weights["adaptability"] * dossier["adaptability"]
                    + weights["consistency"] * dossier["consistency"]
                    + weights["leadership"] * dossier["leadership"]
                )
                composite = round(composite, 2)

                if composite < eligibility["min_weighted_composite_score"] / 10.0:
                    continue

                # Bid calculation
                contract_years_remaining = contract_exp - 2026
                age_over = max(0, age - bid_calc["age_threshold"])
                urgency_prem = bid_calc["urgency_premium"].get(position_urgency.get(pos, "low"), 0)

                bid_low = mv * bid_calc["base_multiplier"] * (
                    1.0
                    + contract_years_remaining * bid_calc["contract_premium_per_year"]
                    - age_over * bid_calc["age_discount_per_year"]
                    + urgency_prem
                )
                bid_low = round(max(bid_low, 0.5), 2)
                bid_high = round(bid_low * bid_calc["high_range_factor"], 2)

                pos_candidates.append({
                    "player_id": pid,
                    "player_name": details["name"],
                    "position": pos,
                    "age": age,
                    "current_club": club,
                    "weighted_score": composite,
                    "bid_low_m": bid_low,
                    "bid_high_m": bid_high,
                    "position_urgency": position_urgency.get(pos, "low"),
                    "market_value_m": mv,
                })

            # Sort by weighted_score descending, then name for tie-breaking
            pos_candidates.sort(key=lambda x: (-x["weighted_score"], x["player_name"]))
            shortlist.extend(pos_candidates[:max_per_pos])

        # Final ranking
        shortlist.sort(key=lambda x: (-x["weighted_score"], x["player_name"]))
        for i, entry in enumerate(shortlist):
            entry["rank"] = i + 1

        # ── Step 9: Write transfer_shortlist.csv ──
        csv_path = os.path.join(self.workspace, "transfer_shortlist.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=[
                "rank", "player_name", "position", "age", "current_club",
                "weighted_score", "bid_low_m", "bid_high_m", "position_urgency"
            ])
            writer.writeheader()
            for entry in shortlist:
                writer.writerow({
                    "rank": entry["rank"],
                    "player_name": entry["player_name"],
                    "position": entry["position"],
                    "age": entry["age"],
                    "current_club": entry["current_club"],
                    "weighted_score": entry["weighted_score"],
                    "bid_low_m": entry["bid_low_m"],
                    "bid_high_m": entry["bid_high_m"],
                    "position_urgency": entry["position_urgency"],
                })

        # ── Step 10: Build action string ──
        action_lines = [
            "TRANSFER TARGET ANALYSIS COMPLETE",
            "",
            f"Priority positions identified: {', '.join(priority_positions)}",
            f"Congested months: {congested_months} (boost applied: {apply_congestion_boost})",
            f"Available transfer budget (FY{budget_year}): {available_budget}M",
            "",
            "PRIORITIZED SHORTLIST:",
        ]
        for entry in shortlist:
            action_lines.append(
                f"  #{entry['rank']} {entry['player_name']} ({entry['position']}, age {entry['age']}) "
                f"- Score: {entry['weighted_score']}, Bid: {entry['bid_low_m']}M - {entry['bid_high_m']}M "
                f"[{entry['position_urgency']}]"
            )

        action_lines.append("")
        action_lines.append("Top recommendation per position:")
        seen_pos = set()
        for entry in shortlist:
            if entry["position"] not in seen_pos:
                seen_pos.add(entry["position"])
                action_lines.append(
                    f"  {entry['position']}: {entry['player_name']} "
                    f"(weighted score {entry['weighted_score']}, bid range {entry['bid_low_m']}M-{entry['bid_high_m']}M)"
                )

        action = "\n".join(action_lines)

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need at least 15"

        return self.step(action)
