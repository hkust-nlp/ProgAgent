"""
Energy Consumption Anomaly Detection - Environment
"""
import sqlite3
import os
import json
import csv
import math
import yaml
from typing import Tuple, Dict, List, Any


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


def _envelope(payload):
    """MCP-style tool result: payload JSON-encoded in a text content block."""
    return {"content": [{"type": "text",
                          "text": json.dumps(payload, ensure_ascii=False, default=str)}],
            "isError": False}


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

    # ------------------------------------------------------------------ #
    #  Tool methods
    # ------------------------------------------------------------------ #

    @tool(
        description=(
            "List households with optional zone filter. Returns paginated "
            "results with household_id, zone, address, account_number, "
            "num_occupants, sq_footage, and heating_type."
        ),
        parameters={
            "type": "object",
            "properties": {
                "zone": {
                    "type": "string",
                    "description": "Filter by zone name (e.g. 'North'). Omit for all zones.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting at 1. Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 20). Default 10.",
                },
            },
            "required": [],
        },
    )
    def list_households(self, zone: str = None, page: int = 1, page_size: int = 10):
        page_size = min(int(page_size), 20)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if zone:
            rows = conn.execute(
                "SELECT * FROM households WHERE zone = ? ORDER BY household_id",
                (zone,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM households ORDER BY household_id"
            ).fetchall()
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = [dict(r) for r in rows[start:end]]
        return json.dumps({
            "households": page_rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size),
        }, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Get detailed information for a single household by its ID."
        ),
        parameters={
            "type": "object",
            "properties": {
                "household_id": {
                    "type": "string",
                    "description": "The household identifier, e.g. 'H0001'.",
                },
            },
            "required": ["household_id"],
        },
    )
    def get_household_details(self, household_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM households WHERE household_id = ?",
            (household_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"Household {household_id} not found"}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description=(
            "Get the smart meter associated with a household."
        ),
        parameters={
            "type": "object",
            "properties": {
                "household_id": {
                    "type": "string",
                    "description": "The household identifier.",
                },
            },
            "required": ["household_id"],
        },
    )
    def get_meter_for_household(self, household_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM meters WHERE household_id = ?",
            (household_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return _envelope({"error": f"No meter found for household {household_id}"})
        return _envelope(dict(row))

    @tool(
        description=(
            "Retrieve daily meter readings for a given meter within a date "
            "range. Returns daily_kwh, peak_kwh, off_peak_kwh, and "
            "avg_voltage. Paginated."
        ),
        parameters={
            "type": "object",
            "properties": {
                "meter_id": {
                    "type": "string",
                    "description": "The meter identifier, e.g. 'M0001'.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date inclusive (YYYY-MM-DD). Omit for all.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date inclusive (YYYY-MM-DD). Omit for all.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting at 1. Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 50). Default 30.",
                },
            },
            "required": ["meter_id"],
        },
    )
    def get_meter_readings(self, meter_id: str, start_date: str = None,
                           end_date: str = None, page: int = 1,
                           page_size: int = 30):
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM meter_readings WHERE meter_id = ?"
        params: list = [meter_id]
        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)
        query += " ORDER BY date"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        total = len(rows)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_rows = [dict(r) for r in rows[start_idx:end_idx]]
        return json.dumps({
            "readings": page_rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if total > 0 else 0,
        }, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Look up all registered appliances for a household. Returns "
            "appliance_type, brand, rated_wattage, avg_daily_hours, and "
            "registration_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "household_id": {
                    "type": "string",
                    "description": "The household identifier.",
                },
            },
            "required": ["household_id"],
        },
    )
    def get_registered_appliances(self, household_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM appliances WHERE household_id = ? ORDER BY appliance_id",
            (household_id,),
        ).fetchall()
        conn.close()
        return _envelope({"appliances": [dict(r) for r in rows]})

    @tool(
        description=(
            "Retrieve daily weather observations for a date range. Returns "
            "temperature_c, humidity_pct, wind_speed_kmh, and condition."
        ),
        parameters={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date inclusive (YYYY-MM-DD).",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date inclusive (YYYY-MM-DD).",
                },
            },
            "required": ["start_date", "end_date"],
        },
    )
    def get_weather_data(self, start_date: str, end_date: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM weather_observations WHERE date >= ? AND date <= ? ORDER BY date",
            (start_date, end_date),
        ).fetchall()
        conn.close()
        return _envelope({"observations": [dict(r) for r in rows]})

    @tool(
        description=(
            "Get the applicable tariff rates for a zone on a specific date. "
            "Returns the most recent tariff entries effective on or before "
            "that date for all tiers."
        ),
        parameters={
            "type": "object",
            "properties": {
                "zone": {
                    "type": "string",
                    "description": "Zone name, e.g. 'North'.",
                },
                "date": {
                    "type": "string",
                    "description": "Reference date (YYYY-MM-DD).",
                },
            },
            "required": ["zone", "date"],
        },
    )
    def get_tariff_rates(self, zone: str, date: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM tariff_log
               WHERE zone = ? AND effective_date <= ?
               ORDER BY effective_date DESC, tier""",
            (zone, date),
        ).fetchall()
        conn.close()
        # Return the most recent entry per tier
        seen_tiers = set()
        result = []
        for r in rows:
            d = dict(r)
            if d["tier"] not in seen_tiers:
                seen_tiers.add(d["tier"])
                result.append(d)
            if len(seen_tiers) == 3:
                break
        return json.dumps({"tariffs": result}, ensure_ascii=False, default=str)

    # ------------------------------------------------------------------ #
    #  Evaluation
    # ------------------------------------------------------------------ #

    def _compute_ground_truth(self):
        """Compute the full ground-truth inspection list from the DB and workspace."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        households = [
            dict(r)
            for r in conn.execute("SELECT * FROM households ORDER BY household_id").fetchall()
        ]
        meters_rows = [
            dict(r)
            for r in conn.execute("SELECT * FROM meters ORDER BY household_id").fetchall()
        ]
        meter_map = {m["household_id"]: m for m in meters_rows}

        appliances = [
            dict(r) for r in conn.execute("SELECT * FROM appliances").fetchall()
        ]
        weather = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM weather_observations ORDER BY date"
            ).fetchall()
        ]
        readings = [
            dict(r) for r in conn.execute("SELECT * FROM meter_readings").fetchall()
        ]
        conn.close()

        # Load config
        with open(os.path.join(self.workspace, "anomaly_thresholds.yaml")) as f:
            cfg = yaml.safe_load(f)

        consumption_thresh = cfg["consumption_anomaly_threshold"]
        billing_thresh = cfg["billing_discrepancy_threshold"]
        heating_thresh_c = cfg["heating_threshold_c"]
        cooling_thresh_c = cfg["cooling_threshold_c"]
        heating_coeff = cfg["heating_coefficient"]
        cooling_coeff = cfg["cooling_coefficient"]

        # Load priority rules
        with open(os.path.join(self.workspace, "inspection_priority_rules.md")) as f:
            _priority_text = f.read()
        # Parse base scores
        base_scores = {
            "faulty_meter": 70,
            "unauthorized_usage": 90,
            "billing_discrepancy": 50,
        }
        actions_map = {
            "faulty_meter": "Replace or recalibrate meter",
            "unauthorized_usage": "On-site inspection for unauthorized connections",
            "billing_discrepancy": "Audit billing records and verify meter accuracy",
        }

        # Weather lookup
        weather_lookup = {w["date"]: w for w in weather}

        # Determine observation date range from readings
        all_dates = sorted(set(r["date"] for r in readings))

        # Expected consumption per household
        hh_apps = {}
        for a in appliances:
            hh_apps.setdefault(a["household_id"], []).append(a)

        # Readings per meter
        meter_readings_map = {}
        for r in readings:
            meter_readings_map.setdefault(r["meter_id"], []).append(r)

        # Billing data from workspace CSVs
        billing_by_hh = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("billing_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        hid = row["household_id"]
                        billing_by_hh[hid] = {
                            "billed_kwh": float(row["billed_kwh"]),
                            "total_amount": float(row["total_amount"]),
                        }

        # Maintenance data from workspace JSONs
        maint_issues_by_meter = {}  # meter_id -> set of issues
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("maintenance_log_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    entries = json.load(f)
                    for e in entries:
                        mid = e["meter_id"]
                        issue = e.get("issues_found", "none")
                        if issue and issue != "none":
                            maint_issues_by_meter.setdefault(mid, set()).add(issue)

        # Compute anomalies
        inspection_list = []
        for h in households:
            hid = h["household_id"]
            meter = meter_map.get(hid)
            if meter is None:
                continue
            mid = meter["meter_id"]
            apps = hh_apps.get(hid, [])
            base_daily = sum(
                a["rated_wattage"] * a["avg_daily_hours"] / 1000.0 for a in apps
            )

            # Sum expected and actual over the observation period
            total_expected = 0.0
            total_actual = 0.0
            m_readings = meter_readings_map.get(mid, [])
            for rd in m_readings:
                date_str = rd["date"]
                w = weather_lookup.get(date_str)
                factor = 1.0
                if w:
                    temp = w["temperature_c"]
                    if h["heating_type"] in ("electric", "heat_pump"):
                        if temp < heating_thresh_c:
                            factor += heating_coeff * (heating_thresh_c - temp) / 10.0
                        if temp > cooling_thresh_c:
                            factor += cooling_coeff * (temp - cooling_thresh_c) / 10.0
                    else:
                        if temp > cooling_thresh_c:
                            factor += cooling_coeff * (temp - cooling_thresh_c) / 10.0
                total_expected += base_daily * factor
                total_actual += rd["daily_kwh"]

            if total_expected == 0:
                continue

            deviation_ratio = (total_actual - total_expected) / total_expected

            # Check billing discrepancy
            billing = billing_by_hh.get(hid)
            billing_disc = False
            if billing:
                bill_dev = abs(billing["billed_kwh"] - total_actual) / max(total_actual, 0.01)
                if bill_dev > billing_thresh:
                    billing_disc = True

            # Check maintenance issues
            has_meter_issues = mid in maint_issues_by_meter

            # Determine anomaly type
            anomaly_type = None
            if abs(deviation_ratio) > consumption_thresh:
                if has_meter_issues:
                    anomaly_type = "faulty_meter"
                else:
                    anomaly_type = "unauthorized_usage"
            elif billing_disc:
                anomaly_type = "billing_discrepancy"

            if anomaly_type is None:
                continue

            base = base_scores[anomaly_type]
            bonus = min(abs(deviation_ratio) * 20, 30)
            priority_score = round(base + bonus, 1)

            inspection_list.append({
                "household_id": hid,
                "meter_id": mid,
                "address": h["address"],
                "zone": h["zone"],
                "anomaly_type": anomaly_type,
                "deviation_ratio": round(deviation_ratio, 2),
                "priority_score": priority_score,
                "recommended_action": actions_map[anomaly_type],
            })

        # Sort
        inspection_list.sort(key=lambda x: (-x["priority_score"], x["household_id"]))
        return inspection_list

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
        gt_ids = {r["household_id"] for r in ground_truth}
        gt_by_id = {r["household_id"]: r for r in ground_truth}

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ---- Criterion 1: inspection_list.csv exists (10 pts) ----
        csv_path = os.path.join(self.workspace, "inspection_list.csv")
        csv_exists = os.path.isfile(csv_path)
        c1_score = 10 if csv_exists else 0
        eval_criteria["inspection_list_exists"] = {
            "passed": csv_exists,
            "score": c1_score,
            "max_score": 10,
        }
        if not csv_exists:
            eval_criteria["inspection_list_exists"]["reason"] = (
                "inspection_list.csv not found in workspace"
            )
        total_score += c1_score
        max_score += 10

        # ---- Parse submitted CSV ----
        submitted = {}
        submitted_order = []
        if csv_exists:
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        hid = row.get("household_id", "").strip()
                        if hid:
                            submitted[hid] = row
                            submitted_order.append(hid)
            except Exception:
                pass

        # ---- Criterion 2: correct anomaly count (15 pts) ----
        expected_count = len(gt_ids)
        actual_count = len(submitted)
        if expected_count > 0 and actual_count == expected_count:
            c2_score = 15
            c2_pass = True
        elif expected_count > 0:
            c2_score = max(0, round(15 * (1 - abs(actual_count - expected_count) / expected_count)))
            c2_pass = False
        else:
            c2_score = 15 if actual_count == 0 else 0
            c2_pass = actual_count == 0
        eval_criteria["correct_anomaly_count"] = {
            "passed": c2_pass,
            "score": c2_score,
            "max_score": 15,
        }
        if not c2_pass:
            eval_criteria["correct_anomaly_count"]["reason"] = (
                f"Expected {expected_count} anomalies, got {actual_count}"
            )
        total_score += c2_score
        max_score += 15

        # ---- Criterion 3: correct household identification (25 pts) ----
        submitted_ids = set(submitted.keys())
        correct_ids = gt_ids & submitted_ids
        if len(gt_ids) > 0:
            c3_ratio = len(correct_ids) / len(gt_ids)
            c3_score = round(25 * c3_ratio)
        else:
            c3_score = 25 if len(submitted_ids) == 0 else 0
            c3_ratio = 1.0 if len(submitted_ids) == 0 else 0.0
        c3_pass = correct_ids == gt_ids and submitted_ids == gt_ids
        eval_criteria["correct_household_identification"] = {
            "passed": c3_pass,
            "score": c3_score,
            "max_score": 25,
        }
        if not c3_pass:
            missing = gt_ids - submitted_ids
            extra = submitted_ids - gt_ids
            eval_criteria["correct_household_identification"]["reason"] = (
                f"Missing: {sorted(missing)}, Extra: {sorted(extra)}"
            )
        total_score += c3_score
        max_score += 25

        # ---- Criterion 4: correct anomaly classification (20 pts) ----
        if len(correct_ids) > 0:
            correct_class = 0
            for hid in correct_ids:
                gt_type = gt_by_id[hid]["anomaly_type"]
                sub_type = submitted[hid].get("anomaly_type", "").strip()
                if sub_type == gt_type:
                    correct_class += 1
            c4_ratio = correct_class / len(correct_ids)
            c4_score = round(20 * c4_ratio)
            c4_pass = correct_class == len(correct_ids)
        else:
            c4_score = 0
            c4_pass = len(gt_ids) == 0
            c4_ratio = 0.0
        eval_criteria["correct_anomaly_classification"] = {
            "passed": c4_pass,
            "score": c4_score,
            "max_score": 20,
        }
        if not c4_pass:
            eval_criteria["correct_anomaly_classification"]["reason"] = (
                f"{c4_score}/20 classifications correct"
            )
        total_score += c4_score
        max_score += 20

        # ---- Criterion 5: correct deviation ratios (15 pts) ----
        if len(correct_ids) > 0:
            correct_dev = 0
            for hid in correct_ids:
                gt_dev = gt_by_id[hid]["deviation_ratio"]
                try:
                    sub_dev = float(submitted[hid].get("deviation_ratio", "nan"))
                except (ValueError, TypeError):
                    sub_dev = float("nan")
                if abs(sub_dev - gt_dev) <= 0.03:
                    correct_dev += 1
            c5_ratio = correct_dev / len(correct_ids)
            c5_score = round(15 * c5_ratio)
            c5_pass = correct_dev == len(correct_ids)
        else:
            c5_score = 0
            c5_pass = len(gt_ids) == 0
        eval_criteria["correct_deviation_values"] = {
            "passed": c5_pass,
            "score": c5_score,
            "max_score": 15,
        }
        if not c5_pass:
            eval_criteria["correct_deviation_values"]["reason"] = (
                f"{correct_dev if len(correct_ids) > 0 else 0}/{len(correct_ids) if correct_ids else 0} deviation ratios within tolerance"
            )
        total_score += c5_score
        max_score += 15

        # ---- Criterion 6: correct priority ranking (15 pts) ----
        gt_order = [r["household_id"] for r in ground_truth]
        if len(submitted_order) > 0 and len(gt_order) > 0:
            # Check if submitted order matches ground truth order for
            # overlapping entries
            sub_filtered = [h for h in submitted_order if h in gt_ids]
            gt_filtered = [h for h in gt_order if h in submitted_ids]
            if sub_filtered == gt_filtered and len(sub_filtered) == len(gt_order):
                c6_score = 15
                c6_pass = True
            else:
                # Partial: count longest common prefix
                common = 0
                for a, b in zip(sub_filtered, gt_filtered):
                    if a == b:
                        common += 1
                    else:
                        break
                c6_ratio = common / max(len(gt_order), 1)
                c6_score = round(15 * c6_ratio)
                c6_pass = False
        else:
            c6_score = 0
            c6_pass = len(gt_order) == 0
        eval_criteria["correct_priority_ranking"] = {
            "passed": c6_pass,
            "score": c6_score,
            "max_score": 15,
        }
        if not c6_pass:
            eval_criteria["correct_priority_ranking"]["reason"] = (
                "Inspection list not sorted correctly by priority_score desc, household_id asc"
            )
        total_score += c6_score
        max_score += 15

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ------------------------------------------------------------------ #
    #  Verify
    # ------------------------------------------------------------------ #

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as _csv

        tool_calls = 0

        # 1. Read config files from workspace
        with open(os.path.join(self.workspace, "anomaly_thresholds.yaml")) as f:
            cfg = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "inspection_priority_rules.md")) as f:
            priority_text = f.read()
        with open(os.path.join(self.workspace, "tariff_tier_mapping.txt")) as f:
            tariff_text = f.read()

        consumption_thresh = cfg["consumption_anomaly_threshold"]
        billing_thresh = cfg["billing_discrepancy_threshold"]
        heating_thresh = cfg["heating_threshold_c"]
        cooling_thresh = cfg["cooling_threshold_c"]
        heating_coeff = cfg["heating_coefficient"]
        cooling_coeff = cfg["cooling_coefficient"]

        base_scores = {"faulty_meter": 70, "unauthorized_usage": 90, "billing_discrepancy": 50}
        actions_map = {
            "faulty_meter": "Replace or recalibrate meter",
            "unauthorized_usage": "On-site inspection for unauthorized connections",
            "billing_discrepancy": "Audit billing records and verify meter accuracy",
        }

        # 2. Read billing CSVs from workspace
        billing_by_hh = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("billing_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = _csv.DictReader(f)
                    for row in reader:
                        billing_by_hh[row["household_id"]] = {
                            "billed_kwh": float(row["billed_kwh"]),
                            "total_amount": float(row["total_amount"]),
                        }

        # 3. Read maintenance logs from workspace
        maint_issues_by_meter = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("maintenance_log_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    entries = json.load(f)
                    for e in entries:
                        mid = e["meter_id"]
                        issue = e.get("issues_found", "none")
                        if issue and issue != "none":
                            maint_issues_by_meter.setdefault(mid, set()).add(issue)

        # 4. List all households via tool
        all_households = []
        page = 1
        while True:
            result = json.loads(self.tools["list_households"](page=page, page_size=20))
            tool_calls += 1
            all_households.extend(result["households"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 5. Get weather data for the observation period
        # Determine date range from first household's readings
        first_hh = all_households[0]
        first_meter = json.loads(self.tools["get_meter_for_household"](household_id=first_hh["household_id"])["content"][0]["text"])
        tool_calls += 1
        # Fetch all readings for first meter to determine date range
        first_readings = json.loads(self.tools["get_meter_readings"](
            meter_id=first_meter["meter_id"], page=1, page_size=50
        ))
        tool_calls += 1
        all_r_dates = [r["date"] for r in first_readings["readings"]]
        rp = 2
        while rp <= first_readings["total_pages"]:
            more = json.loads(self.tools["get_meter_readings"](
                meter_id=first_meter["meter_id"], page=rp, page_size=50
            ))
            tool_calls += 1
            all_r_dates.extend(r["date"] for r in more["readings"])
            rp += 1
        date_min = min(all_r_dates)
        date_max = max(all_r_dates)

        weather_result = json.loads(self.tools["get_weather_data"](
            start_date=date_min, end_date=date_max
        )["content"][0]["text"])
        tool_calls += 1
        weather_lookup = {w["date"]: w for w in weather_result["observations"]}

        # 6. Process each household
        inspection_list = []
        for h in all_households:
            hid = h["household_id"]

            # Get meter
            meter = json.loads(self.tools["get_meter_for_household"](household_id=hid)["content"][0]["text"])
            tool_calls += 1
            mid = meter["meter_id"]

            # Get appliances
            app_result = json.loads(self.tools["get_registered_appliances"](household_id=hid)["content"][0]["text"])
            tool_calls += 1
            apps = app_result["appliances"]
            base_daily = sum(
                a["rated_wattage"] * a["avg_daily_hours"] / 1000.0 for a in apps
            )

            # Get all readings (paginated)
            all_readings = []
            rpage = 1
            while True:
                rd_result = json.loads(self.tools["get_meter_readings"](
                    meter_id=mid, start_date=date_min, end_date=date_max,
                    page=rpage, page_size=50,
                ))
                tool_calls += 1
                all_readings.extend(rd_result["readings"])
                if rpage >= rd_result["total_pages"]:
                    break
                rpage += 1

            # Compute expected vs actual
            total_expected = 0.0
            total_actual = 0.0
            for rd in all_readings:
                date_str = rd["date"]
                w = weather_lookup.get(date_str)
                factor = 1.0
                if w:
                    temp = w["temperature_c"]
                    if h["heating_type"] in ("electric", "heat_pump"):
                        if temp < heating_thresh:
                            factor += heating_coeff * (heating_thresh - temp) / 10.0
                        if temp > cooling_thresh:
                            factor += cooling_coeff * (temp - cooling_thresh) / 10.0
                    else:
                        if temp > cooling_thresh:
                            factor += cooling_coeff * (temp - cooling_thresh) / 10.0
                total_expected += base_daily * factor
                total_actual += rd["daily_kwh"]

            if total_expected == 0:
                continue

            deviation_ratio = (total_actual - total_expected) / total_expected

            # Check billing discrepancy
            billing = billing_by_hh.get(hid)
            billing_disc = False
            if billing:
                bill_dev = abs(billing["billed_kwh"] - total_actual) / max(total_actual, 0.01)
                if bill_dev > billing_thresh:
                    billing_disc = True

            # Check maintenance issues
            has_meter_issues = mid in maint_issues_by_meter

            # Determine anomaly type
            anomaly_type = None
            if abs(deviation_ratio) > consumption_thresh:
                if has_meter_issues:
                    anomaly_type = "faulty_meter"
                else:
                    anomaly_type = "unauthorized_usage"
            elif billing_disc:
                anomaly_type = "billing_discrepancy"

            if anomaly_type is None:
                continue

            base = base_scores[anomaly_type]
            bonus = min(abs(deviation_ratio) * 20, 30)
            priority_score = round(base + bonus, 1)

            inspection_list.append({
                "household_id": hid,
                "meter_id": mid,
                "address": h["address"],
                "zone": h["zone"],
                "anomaly_type": anomaly_type,
                "deviation_ratio": round(deviation_ratio, 2),
                "priority_score": priority_score,
                "recommended_action": actions_map[anomaly_type],
            })

        # Sort
        inspection_list.sort(key=lambda x: (-x["priority_score"], x["household_id"]))

        # 7. Write inspection_list.csv
        csv_path = os.path.join(self.workspace, "inspection_list.csv")
        fieldnames = [
            "household_id", "meter_id", "address", "zone",
            "anomaly_type", "deviation_ratio", "priority_score",
            "recommended_action",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(inspection_list)

        # 8. Build action string (summary)
        type_counts = {}
        for item in inspection_list:
            t = item["anomaly_type"]
            type_counts[t] = type_counts.get(t, 0) + 1

        top3 = inspection_list[:3]
        top3_lines = []
        for item in top3:
            top3_lines.append(
                f"  {item['household_id']} (priority {item['priority_score']}, "
                f"{item['anomaly_type']})"
            )

        action = (
            f"Anomaly detection complete. Found {len(inspection_list)} anomalous households.\n"
            f"Breakdown: "
            + ", ".join(f"{v} {k}" for k, v in sorted(type_counts.items()))
            + "\n"
            f"Top priority households:\n" + "\n".join(top3_lines) + "\n"
            f"Full inspection list saved to inspection_list.csv."
        )

        assert tool_calls >= 15, f"Only {tool_calls} tool calls made, need at least 15"

        return self.step(action)
