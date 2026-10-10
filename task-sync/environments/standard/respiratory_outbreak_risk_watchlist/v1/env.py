"""
Environment for Cattle Respiratory Outbreak Risk Watchlist task.
"""
import csv
import json
import math
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

    # ── Tool methods ────────────────────────────────────────────────────

    @tool(
        description="List cattle in the herd. Returns paginated results with cattle_id, tag_number, breed, age_months, weight_kg, current_pen_id, arrival_date, and status. Use offset/limit to iterate through all animals.",
        parameters={
            "type": "object",
            "properties": {
                "pen_id": {
                    "type": "string",
                    "description": "Optional pen ID to filter cattle (e.g. 'PEN-001'). If omitted, returns all cattle."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of records to return (default 20, max 50)."
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip (default 0)."
                }
            },
            "required": []
        }
    )
    def list_cattle(self, pen_id: str = None, limit: int = 20, offset: int = 0) -> dict:
        limit = min(int(limit) if limit else 20, 50)
        offset = int(offset) if offset else 0
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if pen_id:
            rows = conn.execute(
                "SELECT * FROM cattle WHERE current_pen_id = ? ORDER BY cattle_id LIMIT ? OFFSET ?",
                (pen_id, limit, offset)
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM cattle WHERE current_pen_id = ?", (pen_id,)
            ).fetchone()[0]
        else:
            rows = conn.execute(
                "SELECT * FROM cattle ORDER BY cattle_id LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM cattle").fetchone()[0]
        conn.close()
        return {
            "cattle": [dict(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset
        }

    @tool(
        description="Get detailed information about a specific animal by its cattle ID.",
        parameters={
            "type": "object",
            "properties": {
                "cattle_id": {
                    "type": "integer",
                    "description": "The unique cattle ID."
                }
            },
            "required": ["cattle_id"]
        }
    )
    def get_cattle_details(self, cattle_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM cattle WHERE cattle_id = ?", (int(cattle_id),)
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"No cattle found with ID {cattle_id}"}

    @tool(
        description="Retrieve vaccination history for a specific animal. Returns all vaccination records including vaccine name, date administered, and batch number.",
        parameters={
            "type": "object",
            "properties": {
                "cattle_id": {
                    "type": "integer",
                    "description": "The unique cattle ID."
                }
            },
            "required": ["cattle_id"]
        }
    )
    def get_vaccination_history(self, cattle_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM vaccinations WHERE cattle_id = ? ORDER BY administered_date DESC",
            (int(cattle_id),)
        ).fetchall()
        conn.close()
        return {
            "cattle_id": int(cattle_id),
            "vaccinations": [dict(r) for r in rows],
            "total": len(rows)
        }

    @tool(
        description="Get environmental sensor readings for a specific barn on a specific date. Returns hourly readings for temperature, humidity, ammonia, and airflow.",
        parameters={
            "type": "object",
            "properties": {
                "barn_id": {
                    "type": "string",
                    "description": "The barn identifier (e.g. 'BARN-A')."
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format."
                }
            },
            "required": ["barn_id", "date"]
        }
    )
    def get_sensor_readings(self, barn_id: str, date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM sensor_readings WHERE barn_id = ? AND reading_date = ? ORDER BY reading_hour",
            (barn_id, date)
        ).fetchall()
        conn.close()
        return {
            "barn_id": barn_id,
            "date": date,
            "readings": [dict(r) for r in rows],
            "total": len(rows)
        }

    @tool(
        description="Get movement history for a specific animal. Returns all pen-transfer records with dates and reasons.",
        parameters={
            "type": "object",
            "properties": {
                "cattle_id": {
                    "type": "integer",
                    "description": "The unique cattle ID."
                }
            },
            "required": ["cattle_id"]
        }
    )
    def get_movement_history(self, cattle_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM movement_logs WHERE cattle_id = ? ORDER BY move_date DESC",
            (int(cattle_id),)
        ).fetchall()
        conn.close()
        return {
            "cattle_id": int(cattle_id),
            "movements": [dict(r) for r in rows],
            "total": len(rows)
        }

    @tool(
        description="Get veterinary treatment records for a specific animal. Returns all treatment records including diagnosis, medication, treating vet, and follow-up status.",
        parameters={
            "type": "object",
            "properties": {
                "cattle_id": {
                    "type": "integer",
                    "description": "The unique cattle ID."
                }
            },
            "required": ["cattle_id"]
        }
    )
    def get_treatment_records(self, cattle_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM treatments WHERE cattle_id = ? ORDER BY treatment_date DESC",
            (int(cattle_id),)
        ).fetchall()
        conn.close()
        return {
            "cattle_id": int(cattle_id),
            "treatments": [dict(r) for r in rows],
            "total": len(rows)
        }

    @tool(
        description="List all distinct barns in the sensor system.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    def list_barns(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT DISTINCT barn_id FROM sensor_readings ORDER BY barn_id"
        ).fetchall()
        conn.close()
        return {"barns": [r[0] for r in rows]}

    @tool(
        description="Search treatment records across all animals, filtered by date range and optionally by diagnosis category. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format."
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format."
                },
                "diagnosis_contains": {
                    "type": "string",
                    "description": "Optional substring filter for diagnosis field (case-insensitive)."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum records to return (default 20, max 50)."
                },
                "offset": {
                    "type": "integer",
                    "description": "Records to skip (default 0)."
                }
            },
            "required": ["start_date", "end_date"]
        }
    )
    def search_treatments(self, start_date: str, end_date: str,
                          diagnosis_contains: str = None,
                          limit: int = 20, offset: int = 0) -> dict:
        limit = min(int(limit) if limit else 20, 50)
        offset = int(offset) if offset else 0
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if diagnosis_contains:
            rows = conn.execute(
                "SELECT * FROM treatments WHERE treatment_date BETWEEN ? AND ? "
                "AND LOWER(diagnosis) LIKE ? ORDER BY treatment_date DESC LIMIT ? OFFSET ?",
                (start_date, end_date, f"%{diagnosis_contains.lower()}%", limit, offset)
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM treatments WHERE treatment_date BETWEEN ? AND ? "
                "AND LOWER(diagnosis) LIKE ?",
                (start_date, end_date, f"%{diagnosis_contains.lower()}%")
            ).fetchone()[0]
        else:
            rows = conn.execute(
                "SELECT * FROM treatments WHERE treatment_date BETWEEN ? AND ? "
                "ORDER BY treatment_date DESC LIMIT ? OFFSET ?",
                (start_date, end_date, limit, offset)
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM treatments WHERE treatment_date BETWEEN ? AND ?",
                (start_date, end_date)
            ).fetchone()[0]
        conn.close()
        return {
            "treatments": [dict(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset
        }

    @tool(
        description="Get movement logs for animals moved within a specific date range. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format."
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum records to return (default 20, max 50)."
                },
                "offset": {
                    "type": "integer",
                    "description": "Records to skip (default 0)."
                }
            },
            "required": ["start_date", "end_date"]
        }
    )
    def search_movements(self, start_date: str, end_date: str,
                         limit: int = 20, offset: int = 0) -> dict:
        limit = min(int(limit) if limit else 20, 50)
        offset = int(offset) if offset else 0
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM movement_logs WHERE move_date BETWEEN ? AND ? "
            "ORDER BY move_date DESC LIMIT ? OFFSET ?",
            (start_date, end_date, limit, offset)
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM movement_logs WHERE move_date BETWEEN ? AND ?",
            (start_date, end_date)
        ).fetchone()[0]
        conn.close()
        return {
            "movements": [dict(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset
        }

    # ── Evaluation ──────────────────────────────────────────────────────

    def _compute_ground_truth(self) -> Tuple[List[dict], dict]:
        """Compute the ground-truth watchlist using DB + workspace files.
        Returns (watchlist_rows, env_scores_by_barn).
        """
        from datetime import datetime, timedelta

        TODAY = datetime(2026, 4, 22)

        # Load configs
        with open(os.path.join(self.workspace, "risk_thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "vaccine_protocols.json")) as f:
            protocols = json.load(f)

        # Load pen-barn mapping
        pen_barn = {}
        with open(os.path.join(self.workspace, "pen_barn_mapping.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                pen_barn[row["pen_id"]] = row["barn_id"]

        # Load health observations from all batch files
        symptom_flags = {}  # tag_number -> bool (has respiratory symptoms)
        for fname in sorted(os.listdir(self.workspace)):
            if not fname.startswith("health_obs_batch_"):
                continue
            fpath = os.path.join(self.workspace, fname)
            records = []
            if fname.endswith(".csv"):
                df = __import__("pandas").read_csv(fpath)
                records = df.to_dict("records")
            elif fname.endswith(".json"):
                with open(fpath) as f:
                    records = json.load(f)
            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    lines = f.read().strip().split("\n")
                header = lines[0].split("|")
                for line in lines[1:]:
                    vals = line.split("|")
                    records.append(dict(zip(header, vals)))
            elif fname.endswith(".yaml"):
                with open(fpath) as f:
                    records = yaml.safe_load(f)
            for rec in records:
                tag = rec.get("tag_number", "")
                symptoms = str(rec.get("symptoms", "none"))
                has_symptoms = symptoms.strip().lower() != "none" and symptoms.strip() != ""
                symptom_flags[tag] = has_symptoms

        # Load DB data
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        cattle = [dict(r) for r in conn.execute("SELECT * FROM cattle ORDER BY cattle_id").fetchall()]
        vax_rows = [dict(r) for r in conn.execute("SELECT * FROM vaccinations").fetchall()]
        move_rows = [dict(r) for r in conn.execute("SELECT * FROM movement_logs").fetchall()]
        treat_rows = [dict(r) for r in conn.execute("SELECT * FROM treatments").fetchall()]
        sensor_rows = [dict(r) for r in conn.execute("SELECT * FROM sensor_readings").fetchall()]
        conn.close()

        # Index vaccinations by cattle_id
        vax_by_cattle = {}
        for v in vax_rows:
            vax_by_cattle.setdefault(v["cattle_id"], []).append(v)

        # Index movements by cattle_id
        moves_by_cattle = {}
        for m in move_rows:
            moves_by_cattle.setdefault(m["cattle_id"], []).append(m)

        # Index treatments by cattle_id
        treats_by_cattle = {}
        for t in treat_rows:
            treats_by_cattle.setdefault(t["cattle_id"], []).append(t)

        # Compute environmental breaches per barn (most recent 24 hours)
        # Find the latest date in sensor data
        all_dates = sorted(set(r["reading_date"] for r in sensor_rows))
        latest_date = all_dates[-1] if all_dates else TODAY.strftime("%Y-%m-%d")

        env_thresh = thresholds["environmental_thresholds"]
        env_weight = thresholds["risk_score_weights"]["environmental"]
        n_env_types = 5  # temp_high, temp_low, humidity_high, ammonia_high, airflow_low

        barn_breaches = {}  # barn_id -> set of breach types
        for r in sensor_rows:
            if r["reading_date"] != latest_date:
                continue
            barn = r["barn_id"]
            if barn not in barn_breaches:
                barn_breaches[barn] = set()
            if r["temperature_f"] > env_thresh["temperature_high_f"]:
                barn_breaches[barn].add("ENV_TEMP_HIGH")
            if r["temperature_f"] < env_thresh["temperature_low_f"]:
                barn_breaches[barn].add("ENV_TEMP_LOW")
            if r["humidity_pct"] > env_thresh["humidity_high_pct"]:
                barn_breaches[barn].add("ENV_HUMIDITY_HIGH")
            if r["ammonia_ppm"] > env_thresh["ammonia_high_ppm"]:
                barn_breaches[barn].add("ENV_AMMONIA_HIGH")
            if r["airflow_cfm"] < env_thresh["airflow_low_cfm"]:
                barn_breaches[barn].add("ENV_AIRFLOW_LOW")

        # Compute per-animal risk scores
        weights = thresholds["risk_score_weights"]
        move_window = thresholds["recent_move_window_days"]
        treat_window = thresholds["recent_treatment_window_days"]
        overdue_days = thresholds["vaccine_overdue_days"]
        quarantine_thresh = thresholds["quarantine_threshold"]

        required_vaccines = protocols["required_vaccines"]
        missing_critical_pts = protocols["missing_critical_vaccine_risk_points"]
        missing_high_pts = protocols["missing_high_vaccine_risk_points"]
        overdue_booster_pts = protocols["overdue_booster_risk_points"]

        respiratory_keywords = [
            "respiratory", "pneumonia", "shipping fever", "pleuritis"
        ]

        watchlist = []
        for c in cattle:
            cid = c["cattle_id"]
            tag = c["tag_number"]
            pen = c["current_pen_id"]
            barn = pen_barn.get(pen, "")
            arrival_date = datetime.strptime(c["arrival_date"], "%Y-%m-%d")

            score = 0.0
            risk_factors = set()

            # 1. Environmental score
            breaches = barn_breaches.get(barn, set())
            n_breaches = len(breaches)
            env_score = n_breaches * (env_weight / n_env_types)
            score += env_score
            risk_factors.update(breaches)

            # 2. Vaccination gap score
            my_vax = vax_by_cattle.get(cid, [])
            vax_score = 0.0
            for req in required_vaccines:
                vname = req["vaccine_name"]
                booster_interval = req["booster_interval_days"]
                priority = req["priority"]
                # Find all matching vaccinations
                matching = [v for v in my_vax if v["vaccine_name"] == vname]
                if not matching:
                    # Never administered
                    if priority == "critical":
                        vax_score += missing_critical_pts
                        risk_factors.add("VAX_MISSING_CRITICAL")
                    else:
                        vax_score += missing_high_pts
                        risk_factors.add("VAX_MISSING_HIGH")
                else:
                    # Check if last dose is overdue for booster
                    last_date = max(
                        datetime.strptime(v["administered_date"], "%Y-%m-%d")
                        for v in matching
                    )
                    days_since = (TODAY - last_date).days
                    if days_since > booster_interval:
                        vax_score += overdue_booster_pts
                        risk_factors.add("VAX_OVERDUE_BOOSTER")
                # Cap: only highest penalty per vaccine already handled by if/else
            score += vax_score

            # 3. Recent movement score
            my_moves = moves_by_cattle.get(cid, [])
            cutoff_move = (TODAY - timedelta(days=move_window)).strftime("%Y-%m-%d")
            recent_moves = [m for m in my_moves if m["move_date"] >= cutoff_move]
            if recent_moves:
                score += weights["recent_movement"]
                risk_factors.add("RECENT_MOVE")

            # 4. Treatment history score
            my_treats = treats_by_cattle.get(cid, [])
            cutoff_treat = (TODAY - timedelta(days=treat_window)).strftime("%Y-%m-%d")
            has_resp_treat = False
            for t in my_treats:
                if t["treatment_date"] >= cutoff_treat:
                    diag_lower = t["diagnosis"].lower()
                    if any(kw in diag_lower for kw in respiratory_keywords):
                        has_resp_treat = True
                        break
            if has_resp_treat:
                score += weights["treatment_history"]
                risk_factors.add("RESP_TREATMENT_HISTORY")

            # 5. Observation symptoms score
            has_symptoms = symptom_flags.get(tag, False)
            if has_symptoms:
                score += weights["observation_symptoms"]
                risk_factors.add("OBSERVATION_SYMPTOMS")

            int_score = math.floor(score)

            if int_score >= quarantine_thresh:
                factors_sorted = ";".join(sorted(risk_factors))
                watchlist.append({
                    "tag_number": tag,
                    "pen_id": pen,
                    "barn_id": barn,
                    "risk_score": int_score,
                    "risk_factors": factors_sorted,
                })

        # Sort: descending score, ascending tag for ties
        watchlist.sort(key=lambda x: (-x["risk_score"], x["tag_number"]))
        return watchlist, barn_breaches

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
        gt_watchlist, barn_breaches = self._compute_ground_truth()
        gt_tags = [r["tag_number"] for r in gt_watchlist]
        gt_count = len(gt_watchlist)

        eval_criteria = {}

        # ── Criterion 1: watchlist CSV file exists with correct columns (15 pts) ──
        csv_path = os.path.join(self.workspace, "quarantine_watchlist.csv")
        csv_exists = os.path.exists(csv_path)
        csv_rows = []
        expected_cols = {"tag_number", "pen_id", "barn_id", "risk_score", "risk_factors"}
        cols_ok = False
        if csv_exists:
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    csv_rows = list(reader)
                    actual_cols = set(reader.fieldnames) if reader.fieldnames else set()
                    cols_ok = expected_cols.issubset(actual_cols)
            except Exception:
                pass
        eval_criteria["csv_structure"] = {
            "passed": csv_exists and cols_ok,
            "score": 15 if (csv_exists and cols_ok) else 0,
            "max_score": 15,
            "reason": "" if (csv_exists and cols_ok) else
                      "quarantine_watchlist.csv missing or wrong columns"
        }

        # ── Criterion 2: correct set of animals on watchlist (25 pts) ──
        csv_tags = [r.get("tag_number", "").strip() for r in csv_rows]
        correct_tags = set(gt_tags)
        submitted_tags = set(csv_tags)
        precision = len(correct_tags & submitted_tags) / len(submitted_tags) if submitted_tags else 0
        recall = len(correct_tags & submitted_tags) / len(correct_tags) if correct_tags else 0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0
        tag_score = round(f1 * 25)
        eval_criteria["watchlist_animals"] = {
            "passed": tag_score >= 23,
            "score": tag_score,
            "max_score": 25,
            "reason": "" if tag_score >= 23 else
                      f"F1={f1:.2f} (precision={precision:.2f}, recall={recall:.2f}), "
                      f"expected {gt_count} animals, got {len(csv_tags)}"
        }

        # ── Criterion 3: correct risk scores (20 pts) ──
        gt_score_map = {r["tag_number"]: r["risk_score"] for r in gt_watchlist}
        csv_score_map = {}
        for r in csv_rows:
            tag = r.get("tag_number", "").strip()
            try:
                csv_score_map[tag] = int(r.get("risk_score", -1))
            except (ValueError, TypeError):
                csv_score_map[tag] = -1
        common_tags = correct_tags & submitted_tags
        score_matches = 0
        for tag in common_tags:
            if gt_score_map.get(tag) == csv_score_map.get(tag):
                score_matches += 1
        score_accuracy = score_matches / len(common_tags) if common_tags else 0
        score_pts = round(score_accuracy * 20)
        eval_criteria["risk_scores"] = {
            "passed": score_pts >= 18,
            "score": score_pts,
            "max_score": 20,
            "reason": "" if score_pts >= 18 else
                      f"Score accuracy {score_accuracy:.2f} on {len(common_tags)} common animals"
        }

        # ── Criterion 4: correct sort order (10 pts) ──
        order_ok = True
        if csv_tags and csv_tags == [r["tag_number"] for r in gt_watchlist[:len(csv_tags)]]:
            order_ok = True
        else:
            # Check if the csv is sorted correctly by its own scores
            order_ok = False
            if len(csv_rows) >= 2:
                try:
                    prev_score = int(csv_rows[0].get("risk_score", 0))
                    prev_tag = csv_rows[0].get("tag_number", "")
                    ok = True
                    for r in csv_rows[1:]:
                        cur_score = int(r.get("risk_score", 0))
                        cur_tag = r.get("tag_number", "")
                        if cur_score > prev_score:
                            ok = False
                            break
                        if cur_score == prev_score and cur_tag < prev_tag:
                            ok = False
                            break
                        prev_score = cur_score
                        prev_tag = cur_tag
                    order_ok = ok
                except (ValueError, TypeError):
                    order_ok = False
            elif len(csv_rows) <= 1:
                order_ok = True

        # Also check if it matches GT order exactly
        exact_order = csv_tags == gt_tags
        eval_criteria["sort_order"] = {
            "passed": exact_order,
            "score": 10 if exact_order else (5 if order_ok else 0),
            "max_score": 10,
            "reason": "" if exact_order else
                      ("correct sort direction but order differs from GT" if order_ok
                       else "incorrect sort order")
        }

        # ── Criterion 5: correct risk factors (15 pts) ──
        gt_factors_map = {r["tag_number"]: r["risk_factors"] for r in gt_watchlist}
        factor_matches = 0
        for r in csv_rows:
            tag = r.get("tag_number", "").strip()
            factors = r.get("risk_factors", "").strip()
            if tag in gt_factors_map and factors == gt_factors_map[tag]:
                factor_matches += 1
        factor_accuracy = factor_matches / gt_count if gt_count else 0
        factor_pts = round(factor_accuracy * 15)
        eval_criteria["risk_factors"] = {
            "passed": factor_pts >= 13,
            "score": factor_pts,
            "max_score": 15,
            "reason": "" if factor_pts >= 13 else
                      f"Factor accuracy {factor_accuracy:.2f} ({factor_matches}/{gt_count})"
        }

        # ── Criterion 6: response contains summary stats (15 pts) ──
        response_pts = 0
        action_lower = action.lower() if action else ""
        # Must mention total count
        if str(gt_count) in action:
            response_pts += 5
        # Must mention highest risk animal
        if gt_watchlist and gt_watchlist[0]["tag_number"] in action:
            response_pts += 5
        # Must mention quarantine watchlist file
        if "quarantine_watchlist.csv" in action:
            response_pts += 5
        eval_criteria["response_summary"] = {
            "passed": response_pts >= 12,
            "score": response_pts,
            "max_score": 15,
            "reason": "" if response_pts >= 12 else
                      f"Missing summary elements in response (got {response_pts}/15)"
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import math
        from datetime import datetime, timedelta

        TODAY = datetime(2026, 4, 22)
        tool_call_count = 0

        # ── Step 1: Read workspace config files ────────────────────────
        with open(os.path.join(self.workspace, "risk_thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "vaccine_protocols.json")) as f:
            protocols = json.load(f)

        # Pen-barn mapping
        pen_barn = {}
        with open(os.path.join(self.workspace, "pen_barn_mapping.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                pen_barn[row["pen_id"]] = row["barn_id"]

        # Quarantine policy
        with open(os.path.join(self.workspace, "quarantine_policy.md")) as f:
            _ = f.read()

        # Health observations
        symptom_flags = {}
        for fname in sorted(os.listdir(self.workspace)):
            if not fname.startswith("health_obs_batch_"):
                continue
            fpath = os.path.join(self.workspace, fname)
            records = []
            if fname.endswith(".csv"):
                import pandas as pd
                df = pd.read_csv(fpath)
                records = df.to_dict("records")
            elif fname.endswith(".json"):
                with open(fpath) as f:
                    records = json.load(f)
            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    lines = f.read().strip().split("\n")
                header = lines[0].split("|")
                for line in lines[1:]:
                    vals = line.split("|")
                    records.append(dict(zip(header, vals)))
            elif fname.endswith(".yaml"):
                with open(fpath) as f:
                    records = yaml.safe_load(f)
            for rec in records:
                tag = rec.get("tag_number", "")
                symptoms = str(rec.get("symptoms", "none"))
                has_symptoms = symptoms.strip().lower() != "none" and symptoms.strip() != ""
                symptom_flags[tag] = has_symptoms

        # ── Step 2: List all cattle via tools (paginated) ──────────────
        all_cattle = []
        offset = 0
        while True:
            result = self.tools["list_cattle"](limit=50, offset=offset)
            tool_call_count += 1
            all_cattle.extend(result["cattle"])
            if offset + result["limit"] >= result["total"]:
                break
            offset += result["limit"]

        # ── Step 3: Get barn list and sensor data ─────────────────────
        barn_result = self.tools["list_barns"]()
        tool_call_count += 1
        barns = barn_result["barns"]

        latest_date = TODAY.strftime("%Y-%m-%d")
        env_thresh = thresholds["environmental_thresholds"]
        env_weight = thresholds["risk_score_weights"]["environmental"]
        n_env_types = 5

        barn_breaches = {}
        for barn_id in barns:
            readings = self.tools["get_sensor_readings"](barn_id=barn_id, date=latest_date)
            tool_call_count += 1
            breaches = set()
            for r in readings["readings"]:
                if r["temperature_f"] > env_thresh["temperature_high_f"]:
                    breaches.add("ENV_TEMP_HIGH")
                if r["temperature_f"] < env_thresh["temperature_low_f"]:
                    breaches.add("ENV_TEMP_LOW")
                if r["humidity_pct"] > env_thresh["humidity_high_pct"]:
                    breaches.add("ENV_HUMIDITY_HIGH")
                if r["ammonia_ppm"] > env_thresh["ammonia_high_ppm"]:
                    breaches.add("ENV_AMMONIA_HIGH")
                if r["airflow_cfm"] < env_thresh["airflow_low_cfm"]:
                    breaches.add("ENV_AIRFLOW_LOW")
            barn_breaches[barn_id] = breaches

        # ── Step 4: For each animal, compute risk score ───────────────
        weights = thresholds["risk_score_weights"]
        move_window = thresholds["recent_move_window_days"]
        treat_window = thresholds["recent_treatment_window_days"]
        required_vaccines = protocols["required_vaccines"]
        missing_critical_pts = protocols["missing_critical_vaccine_risk_points"]
        missing_high_pts = protocols["missing_high_vaccine_risk_points"]
        overdue_booster_pts = protocols["overdue_booster_risk_points"]
        quarantine_thresh = thresholds["quarantine_threshold"]

        respiratory_keywords = [
            "respiratory", "pneumonia", "shipping fever", "pleuritis"
        ]

        watchlist = []
        for c in all_cattle:
            cid = c["cattle_id"]
            tag = c["tag_number"]
            pen = c["current_pen_id"]
            barn = pen_barn.get(pen, "")

            score = 0.0
            risk_factors = set()

            # Environmental
            breaches = barn_breaches.get(barn, set())
            score += len(breaches) * (env_weight / n_env_types)
            risk_factors.update(breaches)

            # Vaccination
            vax_result = self.tools["get_vaccination_history"](cattle_id=cid)
            tool_call_count += 1
            my_vax = vax_result["vaccinations"]
            for req in required_vaccines:
                vname = req["vaccine_name"]
                booster_interval = req["booster_interval_days"]
                priority = req["priority"]
                matching = [v for v in my_vax if v["vaccine_name"] == vname]
                if not matching:
                    if priority == "critical":
                        score += missing_critical_pts
                        risk_factors.add("VAX_MISSING_CRITICAL")
                    else:
                        score += missing_high_pts
                        risk_factors.add("VAX_MISSING_HIGH")
                else:
                    last_date = max(
                        datetime.strptime(v["administered_date"], "%Y-%m-%d")
                        for v in matching
                    )
                    if (TODAY - last_date).days > booster_interval:
                        score += overdue_booster_pts
                        risk_factors.add("VAX_OVERDUE_BOOSTER")

            # Recent movement
            move_result = self.tools["get_movement_history"](cattle_id=cid)
            tool_call_count += 1
            cutoff_move = (TODAY - timedelta(days=move_window)).strftime("%Y-%m-%d")
            recent = [m for m in move_result["movements"] if m["move_date"] >= cutoff_move]
            if recent:
                score += weights["recent_movement"]
                risk_factors.add("RECENT_MOVE")

            # Treatment history
            treat_result = self.tools["get_treatment_records"](cattle_id=cid)
            tool_call_count += 1
            cutoff_treat = (TODAY - timedelta(days=treat_window)).strftime("%Y-%m-%d")
            for t in treat_result["treatments"]:
                if t["treatment_date"] >= cutoff_treat:
                    diag_lower = t["diagnosis"].lower()
                    if any(kw in diag_lower for kw in respiratory_keywords):
                        score += weights["treatment_history"]
                        risk_factors.add("RESP_TREATMENT_HISTORY")
                        break

            # Observation symptoms
            if symptom_flags.get(tag, False):
                score += weights["observation_symptoms"]
                risk_factors.add("OBSERVATION_SYMPTOMS")

            int_score = math.floor(score)

            if int_score >= quarantine_thresh:
                watchlist.append({
                    "tag_number": tag,
                    "pen_id": pen,
                    "barn_id": barn,
                    "risk_score": int_score,
                    "risk_factors": ";".join(sorted(risk_factors)),
                })

        # Sort: descending score, ascending tag for ties
        watchlist.sort(key=lambda x: (-x["risk_score"], x["tag_number"]))

        # ── Step 5: Write deliverable ─────────────────────────────────
        import pandas as pd
        df = pd.DataFrame(watchlist, columns=[
            "tag_number", "pen_id", "barn_id", "risk_score", "risk_factors"
        ])
        df.to_csv(os.path.join(self.workspace, "quarantine_watchlist.csv"), index=False)

        # ── Step 6: Construct response ────────────────────────────────
        highest_tag = watchlist[0]["tag_number"] if watchlist else "N/A"
        highest_score = watchlist[0]["risk_score"] if watchlist else 0
        action = (
            f"Daily quarantine watchlist generated and saved to quarantine_watchlist.csv. "
            f"Total animals flagged: {len(watchlist)}. "
            f"Highest risk animal: {highest_tag} with risk score {highest_score}."
        )

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made"

        return self.step(action)
