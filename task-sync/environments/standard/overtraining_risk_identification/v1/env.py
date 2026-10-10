import sqlite3
import os
import json
import csv
import glob
import yaml
from datetime import datetime, timedelta
from typing import Tuple, Dict, List, Any


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

    # =========================================================================
    # TOOLS
    # =========================================================================

    @tool(
        description=(
            "Lists athletes with pagination. Returns a JSON object with 'athletes' "
            "(list of {athlete_id, name, age, position}), 'page', 'page_size', and "
            "'total_athletes'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of athletes per page, max 20. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def list_athletes(self, page: int = 1, page_size: int = 20) -> str:
        page_size = min(int(page_size), 20)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM athletes")
        total = c.fetchone()[0]
        offset = (page - 1) * page_size
        c.execute(
            "SELECT athlete_id, name, age, position FROM athletes "
            "ORDER BY athlete_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps({
            "athletes": rows,
            "page": page,
            "page_size": page_size,
            "total_athletes": total,
        })

    @tool(
        description=(
            "Retrieves daily wellness survey scores for a batch of athletes within a "
            "date range. athlete_ids is a comma-separated string of up to 10 athlete "
            "IDs. Returns a JSON list of records with athlete_id, date, fatigue_rating, "
            "mood_rating, soreness_rating, stress_rating, sleep_quality_rating."
        ),
        parameters={
            "type": "object",
            "properties": {
                "athlete_ids": {
                    "type": "string",
                    "description": "Comma-separated athlete IDs (max 10).",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date inclusive, YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date inclusive, YYYY-MM-DD.",
                },
            },
            "required": ["athlete_ids", "start_date", "end_date"],
        },
    )
    def get_wellness_scores(self, athlete_ids: str, start_date: str, end_date: str) -> str:
        ids = [int(x.strip()) for x in athlete_ids.split(",")][:10]
        placeholders = ",".join("?" for _ in ids)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            f"SELECT athlete_id, date, fatigue_rating, mood_rating, soreness_rating, "
            f"stress_rating, sleep_quality_rating FROM wellness_surveys "
            f"WHERE athlete_id IN ({placeholders}) AND date >= ? AND date <= ? "
            f"ORDER BY athlete_id, date",
            (*ids, start_date, end_date),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps(rows)

    @tool(
        description=(
            "Retrieves GPS training load data for a batch of athletes within a date "
            "range. athlete_ids is a comma-separated string of up to 10 athlete IDs. "
            "Returns a JSON list of records with athlete_id, date, total_distance_m, "
            "high_speed_distance_m, sprint_count, duration_min, player_load."
        ),
        parameters={
            "type": "object",
            "properties": {
                "athlete_ids": {
                    "type": "string",
                    "description": "Comma-separated athlete IDs (max 10).",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date inclusive, YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date inclusive, YYYY-MM-DD.",
                },
            },
            "required": ["athlete_ids", "start_date", "end_date"],
        },
    )
    def get_training_load(self, athlete_ids: str, start_date: str, end_date: str) -> str:
        ids = [int(x.strip()) for x in athlete_ids.split(",")][:10]
        placeholders = ",".join("?" for _ in ids)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            f"SELECT athlete_id, date, total_distance_m, high_speed_distance_m, "
            f"sprint_count, duration_min, player_load FROM gps_training_load "
            f"WHERE athlete_id IN ({placeholders}) AND date >= ? AND date <= ? "
            f"ORDER BY athlete_id, date",
            (*ids, start_date, end_date),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps(rows)

    @tool(
        description=(
            "Retrieves sleep tracker data for a batch of athletes within a date range. "
            "athlete_ids is a comma-separated string of up to 10 athlete IDs. Returns "
            "a JSON list of records with athlete_id, date, total_sleep_hours, "
            "deep_sleep_pct, rem_sleep_pct, awakenings, sleep_efficiency."
        ),
        parameters={
            "type": "object",
            "properties": {
                "athlete_ids": {
                    "type": "string",
                    "description": "Comma-separated athlete IDs (max 10).",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date inclusive, YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date inclusive, YYYY-MM-DD.",
                },
            },
            "required": ["athlete_ids", "start_date", "end_date"],
        },
    )
    def get_sleep_data(self, athlete_ids: str, start_date: str, end_date: str) -> str:
        ids = [int(x.strip()) for x in athlete_ids.split(",")][:10]
        placeholders = ",".join("?" for _ in ids)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            f"SELECT athlete_id, date, total_sleep_hours, deep_sleep_pct, "
            f"rem_sleep_pct, awakenings, sleep_efficiency FROM sleep_tracker "
            f"WHERE athlete_id IN ({placeholders}) AND date >= ? AND date <= ? "
            f"ORDER BY athlete_id, date",
            (*ids, start_date, end_date),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps(rows)

    @tool(
        description=(
            "Retrieves injury history for a batch of athletes. athlete_ids is a "
            "comma-separated string of up to 10 athlete IDs. Returns a JSON list of "
            "records with athlete_id, injury_date, injury_type, severity (1-5), "
            "days_missed, body_region, is_recurring."
        ),
        parameters={
            "type": "object",
            "properties": {
                "athlete_ids": {
                    "type": "string",
                    "description": "Comma-separated athlete IDs (max 10).",
                },
            },
            "required": ["athlete_ids"],
        },
    )
    def get_injury_records(self, athlete_ids: str) -> str:
        ids = [int(x.strip()) for x in athlete_ids.split(",")][:10]
        placeholders = ",".join("?" for _ in ids)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            f"SELECT athlete_id, injury_date, injury_type, severity, days_missed, "
            f"body_region, is_recurring FROM injury_logs "
            f"WHERE athlete_id IN ({placeholders}) ORDER BY athlete_id, injury_date DESC",
            tuple(ids),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps(rows)

    # =========================================================================
    # GROUND-TRUTH COMPUTATION (shared by step and verify)
    # =========================================================================

    def _load_config(self):
        """Load all workspace configuration files."""
        with open(os.path.join(self.workspace, "risk_thresholds.yaml")) as f:
            risk_cfg = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "fatigue_weights.json")) as f:
            weights = json.load(f)
        multipliers = {}
        with open(os.path.join(self.workspace, "body_region_multipliers.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                multipliers[row["body_region"]] = float(row["multiplier"])
        return risk_cfg, weights, multipliers

    def _load_session_data(self):
        """Load all training session CSV files from workspace.
        Returns dict: athlete_id -> list of (date_str, rpe, duration)."""
        sessions = {}
        pattern = os.path.join(self.workspace, "training_session_*.csv")
        for fpath in sorted(glob.glob(pattern)):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    aid = int(row["athlete_id"])
                    sessions.setdefault(aid, []).append({
                        "date": os.path.basename(fpath).replace(
                            "training_session_", "").replace(".csv", ""),
                        "rpe": float(row["rpe_score"]),
                        "duration": float(row["session_duration_min"]),
                    })
        return sessions

    def _load_team_roster(self):
        """Load team roster from workspace CSV. Returns dict: athlete_id -> row dict."""
        roster = {}
        with open(os.path.join(self.workspace, "team_roster.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                roster[int(row["athlete_id"])] = row
        return roster

    def _compute_wellness_component(self, wellness_rows, ref_date_str, window_days):
        """Compute wellness deficit from daily survey records."""
        ref = datetime.strptime(ref_date_str, "%Y-%m-%d")
        cutoff = (ref - timedelta(days=window_days - 1)).strftime("%Y-%m-%d")
        filtered = [r for r in wellness_rows if cutoff <= r["date"] <= ref_date_str]
        if not filtered:
            return 5.0
        daily_avgs = []
        for r in filtered:
            avg = (r["fatigue_rating"] + r["mood_rating"] + r["soreness_rating"]
                   + r["stress_rating"] + r["sleep_quality_rating"]) / 5.0
            daily_avgs.append(avg)
        return 10.0 - (sum(daily_avgs) / len(daily_avgs))

    def _compute_training_component(self, session_entries, gps_rows,
                                     ref_date_str, window_days):
        """Compute training ACWR from session RPE loads and GPS player loads."""
        ref = datetime.strptime(ref_date_str, "%Y-%m-%d")
        acute_cutoff = (ref - timedelta(days=window_days - 1)).strftime("%Y-%m-%d")

        # Session loads (RPE * duration)
        all_session_loads = {}  # date -> total
        for s in session_entries:
            d = s["date"]
            all_session_loads[d] = all_session_loads.get(d, 0) + s["rpe"] * s["duration"]

        # GPS player loads
        all_gps_loads = {}
        for g in gps_rows:
            d = g["date"]
            all_gps_loads[d] = all_gps_loads.get(d, 0) + g["player_load"]

        all_dates = sorted(set(list(all_session_loads.keys()) + list(all_gps_loads.keys())))
        if not all_dates:
            return 5.0  # neutral

        num_total_days = len(all_dates)

        acute_session = sum(v for d, v in all_session_loads.items()
                           if acute_cutoff <= d <= ref_date_str)
        chronic_session = sum(all_session_loads.values())
        acute_gps = sum(v for d, v in all_gps_loads.items()
                       if acute_cutoff <= d <= ref_date_str)
        chronic_gps = sum(all_gps_loads.values())

        acute_total = acute_session + acute_gps
        chronic_total = chronic_session + chronic_gps

        num_weeks = num_total_days / 7.0
        chronic_weekly = chronic_total / num_weeks if num_weeks > 0 else 0

        if chronic_weekly > 0:
            acwr = acute_total / chronic_weekly
        else:
            acwr = 1.5

        return min(10.0, acwr * 3.5)

    def _compute_sleep_component(self, sleep_rows, ref_date_str, window_days):
        """Compute sleep deficit score from tracker data."""
        ref = datetime.strptime(ref_date_str, "%Y-%m-%d")
        cutoff = (ref - timedelta(days=window_days - 1)).strftime("%Y-%m-%d")
        filtered = [r for r in sleep_rows if cutoff <= r["date"] <= ref_date_str]
        if not filtered:
            return 3.0
        deficits = []
        for r in filtered:
            deficit = (max(0, 8.0 - r["total_sleep_hours"])
                       + r["awakenings"] * 0.5
                       + max(0, 85.0 - r["sleep_efficiency"]) * 0.1)
            deficits.append(deficit)
        return min(10.0, sum(deficits) / len(deficits))

    def _compute_injury_component(self, injury_rows, ref_date_str,
                                   lookback_days, multipliers):
        """Compute injury burden from historical records."""
        ref = datetime.strptime(ref_date_str, "%Y-%m-%d")
        cutoff = ref - timedelta(days=lookback_days)
        total_burden = 0.0
        for inj in injury_rows:
            inj_date = datetime.strptime(inj["injury_date"], "%Y-%m-%d")
            if inj_date < cutoff or inj_date > ref:
                continue
            days_since = (ref - inj_date).days
            if days_since <= 30:
                recency = 1.0
            elif days_since <= 60:
                recency = 0.5
            else:
                recency = 0.25
            mult = multipliers.get(inj["body_region"], 1.0)
            total_burden += inj["severity"] * mult * recency
        return min(10.0, total_burden)

    def _classify_risk(self, score, risk_levels):
        """Assign risk level and protocol based on score and thresholds."""
        for level in ["critical", "high", "moderate"]:
            if score >= risk_levels[level]["min_score"]:
                return level, risk_levels[level]["protocol"]
        return "low", "None"

    def _compute_ground_truth(self):
        """Compute ground-truth fatigue scores and risk classifications
        directly from database and workspace files."""
        risk_cfg, weights, multipliers = self._load_config()
        session_data = self._load_session_data()
        roster = self._load_team_roster()

        ref_date = risk_cfg["reference_date"]
        window = risk_cfg["analysis_window_days"]
        lookback = risk_cfg["injury_lookback_days"]
        risk_levels = risk_cfg["risk_levels"]

        w_well = weights["wellness_weight"]
        w_train = weights["training_weight"]
        w_sleep = weights["sleep_weight"]
        w_inj = weights["injury_weight"]

        # Gather earliest date from session files for full-range queries
        all_session_dates = []
        for entries in session_data.values():
            for e in entries:
                all_session_dates.append(e["date"])
        earliest_date = min(all_session_dates) if all_session_dates else ref_date

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT athlete_id, name FROM athletes ORDER BY athlete_id")
        athletes = [dict(r) for r in c.fetchall()]

        results = []
        for ath in athletes:
            aid = ath["athlete_id"]

            # Wellness
            c.execute(
                "SELECT date, fatigue_rating, mood_rating, soreness_rating, "
                "stress_rating, sleep_quality_rating FROM wellness_surveys "
                "WHERE athlete_id = ? ORDER BY date", (aid,))
            wellness_rows = [dict(r) for r in c.fetchall()]
            wellness_comp = self._compute_wellness_component(
                wellness_rows, ref_date, window)

            # GPS
            c.execute(
                "SELECT date, player_load FROM gps_training_load "
                "WHERE athlete_id = ? ORDER BY date", (aid,))
            gps_rows = [dict(r) for r in c.fetchall()]

            # Training (session data from workspace + GPS from DB)
            athlete_sessions = session_data.get(aid, [])
            training_comp = self._compute_training_component(
                athlete_sessions, gps_rows, ref_date, window)

            # Sleep
            c.execute(
                "SELECT date, total_sleep_hours, awakenings, sleep_efficiency "
                "FROM sleep_tracker WHERE athlete_id = ? ORDER BY date", (aid,))
            sleep_rows = [dict(r) for r in c.fetchall()]
            sleep_comp = self._compute_sleep_component(
                sleep_rows, ref_date, window)

            # Injuries
            c.execute(
                "SELECT injury_date, severity, body_region "
                "FROM injury_logs WHERE athlete_id = ?", (aid,))
            injury_rows = [dict(r) for r in c.fetchall()]
            injury_comp = self._compute_injury_component(
                injury_rows, ref_date, lookback, multipliers)

            fatigue_score = round(
                w_well * wellness_comp + w_train * training_comp
                + w_sleep * sleep_comp + w_inj * injury_comp, 2)

            risk_level, protocol = self._classify_risk(fatigue_score, risk_levels)

            results.append({
                "athlete_id": aid,
                "athlete_name": ath["name"],
                "team": roster.get(aid, {}).get("team", "Unknown"),
                "fatigue_score": fatigue_score,
                "risk_level": risk_level,
                "protocol": protocol,
            })

        conn.close()

        # Sort: fatigue_score desc, athlete_id asc (tie-break)
        results.sort(key=lambda x: (-x["fatigue_score"], x["athlete_id"]))

        # Filter to moderate+
        flagged = [r for r in results if r["risk_level"] in ("critical", "high", "moderate")]

        # Assign priority ranks
        for i, r in enumerate(flagged):
            r["priority_rank"] = i + 1

        # Summary counts
        counts = {"critical": 0, "high": 0, "moderate": 0, "low": 0}
        for r in results:
            counts[r["risk_level"]] += 1

        return flagged, counts, len(results)

    # =========================================================================
    # STEP
    # =========================================================================

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        criteria = {}
        flagged_gt, counts_gt, total_athletes = self._compute_ground_truth()

        # ---------- Criterion 1: rest_protocol_list.csv exists (10 pts) ----------
        csv_path = os.path.join(self.workspace, "rest_protocol_list.csv")
        if os.path.exists(csv_path):
            criteria["file_exists"] = {
                "passed": True, "score": 10, "max_score": 10,
            }
        else:
            criteria["file_exists"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "rest_protocol_list.csv not found in workspace",
            }
            # Can't evaluate further file criteria
            for c_name, ms in [("correct_columns", 10), ("correct_athletes", 20),
                                ("correct_scores", 20), ("correct_risk_protocols", 15),
                                ("correct_ranking", 10), ("risk_summary_json", 15)]:
                criteria[c_name] = {
                    "passed": False, "score": 0, "max_score": ms,
                    "reason": "rest_protocol_list.csv missing",
                }
            total = sum(c["score"] for c in criteria.values())
            max_total = sum(c["max_score"] for c in criteria.values())
            return total / max_total, {
                "eval_criteria": criteria,
                "total_score": total,
                "max_score": max_total,
            }

        # Read submitted CSV
        submitted = []
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            for row in reader:
                submitted.append(row)

        # ---------- Criterion 2: correct columns (10 pts) ----------
        expected_cols = ["athlete_id", "athlete_name", "team", "fatigue_score",
                         "risk_level", "protocol", "priority_rank"]
        if headers == expected_cols:
            criteria["correct_columns"] = {
                "passed": True, "score": 10, "max_score": 10,
            }
        else:
            criteria["correct_columns"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": f"Expected columns {expected_cols}, got {headers}",
            }

        # Build lookup from submitted data
        sub_by_id = {}
        for row in submitted:
            try:
                aid = int(row.get("athlete_id", -1))
                sub_by_id[aid] = row
            except (ValueError, TypeError):
                pass

        gt_by_id = {r["athlete_id"]: r for r in flagged_gt}
        gt_ids = set(gt_by_id.keys())
        sub_ids = set(sub_by_id.keys())

        # ---------- Criterion 3: correct athletes identified (20 pts) ----------
        if gt_ids == sub_ids:
            criteria["correct_athletes"] = {
                "passed": True, "score": 20, "max_score": 20,
            }
        else:
            missing = gt_ids - sub_ids
            extra = sub_ids - gt_ids
            overlap = len(gt_ids & sub_ids)
            partial = round(20 * overlap / max(len(gt_ids), 1))
            criteria["correct_athletes"] = {
                "passed": False, "score": partial, "max_score": 20,
                "reason": f"Missing {len(missing)}, extra {len(extra)} athletes",
            }

        # ---------- Criterion 4: correct fatigue scores (20 pts) ----------
        common_ids = gt_ids & sub_ids
        score_matches = 0
        for aid in common_ids:
            try:
                sub_score = float(sub_by_id[aid].get("fatigue_score", -1))
                gt_score = gt_by_id[aid]["fatigue_score"]
                if abs(sub_score - gt_score) <= 0.05:
                    score_matches += 1
            except (ValueError, TypeError):
                pass
        if common_ids:
            pct = score_matches / len(common_ids)
        else:
            pct = 0
        score_pts = round(20 * pct)
        criteria["correct_scores"] = {
            "passed": score_pts == 20,
            "score": score_pts,
            "max_score": 20,
        }
        if score_pts < 20:
            criteria["correct_scores"]["reason"] = (
                f"{score_matches}/{len(common_ids)} scores within tolerance"
            )

        # ---------- Criterion 5: correct risk levels & protocols (15 pts) ----------
        risk_prot_matches = 0
        for aid in common_ids:
            sub_rl = sub_by_id[aid].get("risk_level", "").strip().lower()
            sub_pr = sub_by_id[aid].get("protocol", "").strip()
            gt_rl = gt_by_id[aid]["risk_level"]
            gt_pr = gt_by_id[aid]["protocol"]
            if sub_rl == gt_rl and sub_pr == gt_pr:
                risk_prot_matches += 1
        if common_ids:
            pct_rp = risk_prot_matches / len(common_ids)
        else:
            pct_rp = 0
        rp_pts = round(15 * pct_rp)
        criteria["correct_risk_protocols"] = {
            "passed": rp_pts == 15,
            "score": rp_pts,
            "max_score": 15,
        }
        if rp_pts < 15:
            criteria["correct_risk_protocols"]["reason"] = (
                f"{risk_prot_matches}/{len(common_ids)} risk+protocol correct"
            )

        # ---------- Criterion 6: correct ranking order (10 pts) ----------
        sub_order = [int(row.get("athlete_id", -1)) for row in submitted]
        gt_order = [r["athlete_id"] for r in flagged_gt]
        if sub_order == gt_order:
            criteria["correct_ranking"] = {
                "passed": True, "score": 10, "max_score": 10,
            }
        else:
            # Partial: Kendall-tau style — fraction of pairwise orderings correct
            correct_pairs = 0
            total_pairs = 0
            for i in range(len(gt_order)):
                for j in range(i + 1, len(gt_order)):
                    total_pairs += 1
                    a, b = gt_order[i], gt_order[j]
                    if a in sub_by_id and b in sub_by_id:
                        try:
                            sa = int(sub_by_id[a].get("priority_rank", 999))
                            sb = int(sub_by_id[b].get("priority_rank", 999))
                            if sa < sb:
                                correct_pairs += 1
                        except (ValueError, TypeError):
                            pass
            rank_pct = correct_pairs / max(total_pairs, 1)
            rank_pts = round(10 * rank_pct)
            criteria["correct_ranking"] = {
                "passed": False, "score": rank_pts, "max_score": 10,
                "reason": f"Ranking pairwise accuracy: {rank_pct:.2%}",
            }

        # ---------- Criterion 7: risk_summary.json (15 pts) ----------
        summary_path = os.path.join(self.workspace, "risk_summary.json")
        if os.path.exists(summary_path):
            try:
                with open(summary_path) as f:
                    summary = json.load(f)
                checks = 0
                total_checks = 5
                if summary.get("total_athletes_analyzed") == total_athletes:
                    checks += 1
                if summary.get("critical_count") == counts_gt["critical"]:
                    checks += 1
                if summary.get("high_count") == counts_gt["high"]:
                    checks += 1
                if summary.get("moderate_count") == counts_gt["moderate"]:
                    checks += 1
                expected_flagged = [r["athlete_id"] for r in flagged_gt]
                if summary.get("flagged_athletes") == expected_flagged:
                    checks += 1
                s_pts = round(15 * checks / total_checks)
                criteria["risk_summary_json"] = {
                    "passed": s_pts == 15,
                    "score": s_pts,
                    "max_score": 15,
                }
                if s_pts < 15:
                    criteria["risk_summary_json"]["reason"] = (
                        f"{checks}/{total_checks} summary fields correct"
                    )
            except Exception as e:
                criteria["risk_summary_json"] = {
                    "passed": False, "score": 0, "max_score": 15,
                    "reason": f"Error reading risk_summary.json: {e}",
                }
        else:
            criteria["risk_summary_json"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "risk_summary.json not found",
            }

        total = sum(c["score"] for c in criteria.values())
        max_total = sum(c["max_score"] for c in criteria.values())
        return total / max_total, {
            "eval_criteria": criteria,
            "total_score": total,
            "max_score": max_total,
        }

    # =========================================================================
    # VERIFY
    # =========================================================================

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        # ---- 1. Load workspace configs ----
        risk_cfg, weights, multipliers = self._load_config()
        roster = self._load_team_roster()
        session_data = self._load_session_data()

        ref_date = risk_cfg["reference_date"]
        window = risk_cfg["analysis_window_days"]
        lookback = risk_cfg["injury_lookback_days"]
        risk_levels = risk_cfg["risk_levels"]

        w_well = weights["wellness_weight"]
        w_train = weights["training_weight"]
        w_sleep = weights["sleep_weight"]
        w_inj = weights["injury_weight"]

        ref_dt = datetime.strptime(ref_date, "%Y-%m-%d")
        window_start = (ref_dt - timedelta(days=window - 1)).strftime("%Y-%m-%d")

        # Earliest date from session files
        all_session_dates = []
        for entries in session_data.values():
            for e in entries:
                all_session_dates.append(e["date"])
        earliest_date = min(all_session_dates) if all_session_dates else ref_date

        # ---- 2. List all athletes via tool ----
        all_athletes = []
        page = 1
        tool_call_count = 0
        while True:
            result = json.loads(self.tools["list_athletes"](page=page, page_size=20))
            tool_call_count += 1
            all_athletes.extend(result["athletes"])
            if page * 20 >= result["total_athletes"]:
                break
            page += 1

        athlete_ids = [a["athlete_id"] for a in all_athletes]
        athlete_names = {a["athlete_id"]: a["name"] for a in all_athletes}

        # ---- 3. Query data in batches of 10 ----
        def batch_ids(ids, size=10):
            for i in range(0, len(ids), size):
                yield ids[i:i + size]

        # Wellness
        wellness_by_athlete = {}
        for batch in batch_ids(athlete_ids):
            ids_str = ",".join(str(x) for x in batch)
            rows = json.loads(self.tools["get_wellness_scores"](
                athlete_ids=ids_str, start_date=window_start, end_date=ref_date))
            tool_call_count += 1
            for r in rows:
                wellness_by_athlete.setdefault(r["athlete_id"], []).append(r)

        # GPS training load (need full range for chronic calculation)
        gps_by_athlete = {}
        for batch in batch_ids(athlete_ids):
            ids_str = ",".join(str(x) for x in batch)
            rows = json.loads(self.tools["get_training_load"](
                athlete_ids=ids_str, start_date=earliest_date, end_date=ref_date))
            tool_call_count += 1
            for r in rows:
                gps_by_athlete.setdefault(r["athlete_id"], []).append(r)

        # Sleep
        sleep_by_athlete = {}
        for batch in batch_ids(athlete_ids):
            ids_str = ",".join(str(x) for x in batch)
            rows = json.loads(self.tools["get_sleep_data"](
                athlete_ids=ids_str, start_date=window_start, end_date=ref_date))
            tool_call_count += 1
            for r in rows:
                sleep_by_athlete.setdefault(r["athlete_id"], []).append(r)

        # Injuries
        injury_by_athlete = {}
        for batch in batch_ids(athlete_ids):
            ids_str = ",".join(str(x) for x in batch)
            rows = json.loads(self.tools["get_injury_records"](athlete_ids=ids_str))
            tool_call_count += 1
            for r in rows:
                injury_by_athlete.setdefault(r["athlete_id"], []).append(r)

        # ---- 4. Compute fatigue scores ----
        results = []
        for aid in athlete_ids:
            wellness_comp = self._compute_wellness_component(
                wellness_by_athlete.get(aid, []), ref_date, window)
            training_comp = self._compute_training_component(
                session_data.get(aid, []),
                gps_by_athlete.get(aid, []),
                ref_date, window)
            sleep_comp = self._compute_sleep_component(
                sleep_by_athlete.get(aid, []), ref_date, window)
            injury_comp = self._compute_injury_component(
                injury_by_athlete.get(aid, []), ref_date, lookback, multipliers)

            fatigue_score = round(
                w_well * wellness_comp + w_train * training_comp
                + w_sleep * sleep_comp + w_inj * injury_comp, 2)

            risk_level, protocol = self._classify_risk(fatigue_score, risk_levels)

            results.append({
                "athlete_id": aid,
                "athlete_name": athlete_names[aid],
                "team": roster.get(aid, {}).get("team", "Unknown"),
                "fatigue_score": fatigue_score,
                "risk_level": risk_level,
                "protocol": protocol,
            })

        # Sort: fatigue_score desc, athlete_id asc
        results.sort(key=lambda x: (-x["fatigue_score"], x["athlete_id"]))

        # Filter to moderate+
        flagged = [r for r in results if r["risk_level"] in ("critical", "high", "moderate")]
        for i, r in enumerate(flagged):
            r["priority_rank"] = i + 1

        # Counts
        counts = {"critical": 0, "high": 0, "moderate": 0, "low": 0}
        for r in results:
            counts[r["risk_level"]] += 1

        # ---- 5. Write deliverables ----
        csv_path = os.path.join(self.workspace, "rest_protocol_list.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "athlete_id", "athlete_name", "team", "fatigue_score",
                "risk_level", "protocol", "priority_rank"])
            writer.writeheader()
            for r in flagged:
                writer.writerow(r)

        summary = {
            "total_athletes_analyzed": len(results),
            "critical_count": counts["critical"],
            "high_count": counts["high"],
            "moderate_count": counts["moderate"],
            "low_count": counts["low"],
            "flagged_athletes": [r["athlete_id"] for r in flagged],
        }
        with open(os.path.join(self.workspace, "risk_summary.json"), "w") as f:
            json.dump(summary, f, indent=2)

        # ---- 6. Build action string ----
        top3 = flagged[:3]
        top3_str = "; ".join(
            f"{r['athlete_name']} (ID {r['athlete_id']}, score {r['fatigue_score']})"
            for r in top3
        )
        action = (
            f"Analysis complete. {len(flagged)} athletes flagged for overtraining risk "
            f"out of {len(results)} total. Top 3 highest-risk athletes: {top3_str}. "
            f"Breakdown — Critical: {counts['critical']}, High: {counts['high']}, "
            f"Moderate: {counts['moderate']}, Low: {counts['low']}. "
            f"Rest protocol list saved to rest_protocol_list.csv and summary to "
            f"risk_summary.json."
        )

        assert tool_call_count >= 15, (
            f"verify used only {tool_call_count} tool calls, need >=15"
        )

        return self.step(action)
