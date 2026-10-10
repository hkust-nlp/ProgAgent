"""
Water Distribution Leakage Detection - Task Environment
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

    # ─────────────────────── Tool Methods ───────────────────────

    @tool(
        description="List water distribution zones with pagination. Returns zone_id, zone_name, district, and population_served for each zone.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of zones per page (max 10)"
                }
            },
            "required": ["page", "page_size"]
        }
    )
    def list_zones(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 10)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM zones").fetchone()[0]
        rows = conn.execute(
            "SELECT zone_id, zone_name, district, population_served FROM zones ORDER BY zone_id LIMIT ? OFFSET ?",
            (page_size, offset)
        ).fetchall()
        conn.close()
        return {
            "zones": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total_zones": total,
            "total_pages": math.ceil(total / page_size)
        }

    @tool(
        description="Get detailed information about a specific zone by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "integer",
                    "description": "The zone ID to look up"
                }
            },
            "required": ["zone_id"]
        }
    )
    def get_zone_details(self, zone_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM zones WHERE zone_id = ?", (zone_id,)).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Zone {zone_id} not found"}
        return dict(row)

    @tool(
        description="Retrieve hourly flow meter readings for a specific zone within a date range. Returns inflow, outflow, and billed consumption in m³. Maximum span of 2 days per request.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "integer",
                    "description": "The zone ID"
                },
                "start_datetime": {
                    "type": "string",
                    "description": "Start datetime in YYYY-MM-DD HH:MM:SS format"
                },
                "end_datetime": {
                    "type": "string",
                    "description": "End datetime in YYYY-MM-DD HH:MM:SS format"
                }
            },
            "required": ["zone_id", "start_datetime", "end_datetime"]
        }
    )
    def get_flow_readings(self, zone_id: int, start_datetime: str, end_datetime: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT timestamp, inflow_m3, outflow_m3, billed_consumption_m3
               FROM flow_readings
               WHERE zone_id = ? AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp
               LIMIT 49""",
            (zone_id, start_datetime, end_datetime)
        ).fetchall()
        conn.close()
        readings = [dict(r) for r in rows]
        return {
            "zone_id": zone_id,
            "readings_count": len(readings),
            "readings": readings
        }

    @tool(
        description="Get pressure sensor readings for a specific zone on a given date. Returns sensor_id, timestamp, pressure in kPa, and anomaly flag.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "integer",
                    "description": "The zone ID"
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format"
                }
            },
            "required": ["zone_id", "date"]
        }
    )
    def get_pressure_readings(self, zone_id: int, date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT sensor_id, timestamp, pressure_kpa, anomaly_flag
               FROM pressure_readings
               WHERE zone_id = ? AND timestamp LIKE ?
               ORDER BY sensor_id, timestamp""",
            (zone_id, f"{date}%")
        ).fetchall()
        conn.close()
        readings = [dict(r) for r in rows]
        total_readings = len(readings)
        anomaly_count = sum(1 for r in readings if r["anomaly_flag"] == 1)
        return {
            "zone_id": zone_id,
            "date": date,
            "total_readings": total_readings,
            "anomaly_count": anomaly_count,
            "anomaly_rate": round(anomaly_count / total_readings, 4) if total_readings > 0 else 0,
            "readings": readings
        }

    @tool(
        description="Query work orders for a specific zone, optionally filtered by status. Returns order details including type, status, priority, and cost.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "integer",
                    "description": "The zone ID"
                },
                "status_filter": {
                    "type": "string",
                    "description": "Filter by status: 'Open', 'In Progress', 'Completed', 'Deferred', or 'all'",
                    "enum": ["Open", "In Progress", "Completed", "Deferred", "all"]
                }
            },
            "required": ["zone_id", "status_filter"]
        }
    )
    def get_work_orders(self, zone_id: int, status_filter: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if status_filter == "all":
            rows = conn.execute(
                "SELECT * FROM work_orders WHERE zone_id = ? ORDER BY created_date DESC",
                (zone_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM work_orders WHERE zone_id = ? AND status = ? ORDER BY created_date DESC",
                (zone_id, status_filter)
            ).fetchall()
        conn.close()
        orders = [dict(r) for r in rows]
        return {
            "zone_id": zone_id,
            "status_filter": status_filter,
            "total_orders": len(orders),
            "orders": orders
        }

    @tool(
        description="Get aggregate flow statistics for a zone: total inflow, total outflow, total billed consumption, and computed loss percentage over the full monitoring period.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "integer",
                    "description": "The zone ID"
                }
            },
            "required": ["zone_id"]
        }
    )
    def get_flow_summary(self, zone_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            """SELECT
                 SUM(inflow_m3) as total_inflow,
                 SUM(outflow_m3) as total_outflow,
                 SUM(billed_consumption_m3) as total_consumption,
                 COUNT(*) as total_hours
               FROM flow_readings WHERE zone_id = ?""",
            (zone_id,)
        ).fetchone()
        conn.close()
        total_inflow = row[0] or 0
        total_outflow = row[1] or 0
        total_consumption = row[2] or 0
        total_hours = row[3] or 0
        loss = total_inflow - total_outflow - total_consumption
        loss_pct = (loss / total_inflow * 100) if total_inflow > 0 else 0
        return {
            "zone_id": zone_id,
            "total_inflow_m3": round(total_inflow, 2),
            "total_outflow_m3": round(total_outflow, 2),
            "total_billed_consumption_m3": round(total_consumption, 2),
            "total_loss_m3": round(loss, 2),
            "avg_loss_pct": round(loss_pct, 2),
            "total_hours": total_hours
        }

    # ─────────────────────── Evaluation ───────────────────────

    def _compute_ground_truth(self):
        """Compute full ground truth using database and workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load config
        with open(os.path.join(self.workspace, "leakage_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "material_risk_factors.json")) as f:
            risk_config = json.load(f)

        threshold = policy["leakage_detection"]["loss_threshold_pct"]
        consec_hours = policy["leakage_detection"]["consecutive_hours_required"]
        weights = policy["priority_scoring"]["weights"]
        actions_config = policy["repair_schedule"]["recommended_actions"]
        current_year = risk_config["current_year_for_calculation"]
        material_multipliers = risk_config["material_risk_multipliers"]

        zones = conn.execute("SELECT * FROM zones ORDER BY zone_id").fetchall()
        zones = [dict(z) for z in zones]

        flagged_zones = []

        for zone in zones:
            zid = zone["zone_id"]
            # Get hourly flow readings
            readings = conn.execute(
                """SELECT timestamp, inflow_m3, outflow_m3, billed_consumption_m3
                   FROM flow_readings WHERE zone_id = ? ORDER BY timestamp""",
                (zid,)
            ).fetchall()

            # Compute hourly loss percentages
            hourly_loss = []
            for r in readings:
                inflow = r[1]
                outflow = r[2]
                consumption = r[3]
                if inflow > 0:
                    loss_pct = (inflow - outflow - consumption) / inflow * 100
                else:
                    loss_pct = 0
                hourly_loss.append(loss_pct)

            # Find max consecutive hours above threshold
            max_consec = 0
            current_consec = 0
            for lp in hourly_loss:
                if lp > threshold:
                    current_consec += 1
                    max_consec = max(max_consec, current_consec)
                else:
                    current_consec = 0

            if max_consec >= consec_hours:
                avg_loss = sum(hourly_loss) / len(hourly_loss) if hourly_loss else 0
                flagged_zones.append({
                    "zone_id": zid,
                    "zone_name": zone["zone_name"],
                    "avg_loss_pct": avg_loss,
                    "max_consecutive_hours": max_consec,
                    "population_served": zone["population_served"]
                })

        # Compute pipe risk scores from workspace files
        pipe_data = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("pipe_inventory_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        zid = int(row["zone_id"])
                        if zid not in pipe_data:
                            pipe_data[zid] = []
                        material = row["material"]
                        install_year = int(row["install_year"])
                        condition_score = float(row["condition_score"])

                        mat_mult = material_multipliers.get(material, 1.0)
                        age_factor = min((current_year - install_year) / 50.0, 2.0)
                        cond_factor = (10 - condition_score) / 9.0
                        pipe_risk = mat_mult * age_factor * cond_factor
                        pipe_data[zid].append(pipe_risk)

        # Compute pressure anomaly rates
        pressure_anomaly_rates = {}
        for zone in flagged_zones:
            zid = zone["zone_id"]
            result = conn.execute(
                """SELECT COUNT(*) as total, SUM(anomaly_flag) as anomalies
                   FROM pressure_readings WHERE zone_id = ?""",
                (zid,)
            ).fetchone()
            total = result[0] or 0
            anomalies = result[1] or 0
            pressure_anomaly_rates[zid] = anomalies / total if total > 0 else 0

        # Compute open work orders count
        open_wo_counts = {}
        for zone in flagged_zones:
            zid = zone["zone_id"]
            result = conn.execute(
                "SELECT COUNT(*) FROM work_orders WHERE zone_id = ? AND status IN ('Open', 'In Progress')",
                (zid,)
            ).fetchone()
            open_wo_counts[zid] = result[0]

        conn.close()

        if not flagged_zones:
            return flagged_zones, []

        # Normalize factors and compute composite score
        avg_losses = [z["avg_loss_pct"] for z in flagged_zones]
        pipe_risks = [sum(pipe_data.get(z["zone_id"], [1.0])) / max(len(pipe_data.get(z["zone_id"], [1.0])), 1) for z in flagged_zones]
        anomaly_rates = [pressure_anomaly_rates.get(z["zone_id"], 0) for z in flagged_zones]
        wo_counts = [open_wo_counts.get(z["zone_id"], 0) for z in flagged_zones]
        populations = [z["population_served"] for z in flagged_zones]

        def min_max_normalize(values):
            mn, mx = min(values), max(values)
            if mx == mn:
                return [0.5] * len(values)
            return [(v - mn) / (mx - mn) for v in values]

        norm_loss = min_max_normalize(avg_losses)
        norm_pipe = min_max_normalize(pipe_risks)
        norm_anom = min_max_normalize(anomaly_rates)
        norm_wo = min_max_normalize(wo_counts)
        norm_pop = min_max_normalize(populations)

        schedule = []
        for i, zone in enumerate(flagged_zones):
            composite = (
                weights["avg_loss_rate"] * norm_loss[i] +
                weights["pipe_risk_score"] * norm_pipe[i] +
                weights["pressure_anomaly_rate"] * norm_anom[i] +
                weights["open_work_orders_factor"] * norm_wo[i] +
                weights["population_impact"] * norm_pop[i]
            )

            if composite >= 0.7:
                action = "Emergency Repair"
            elif composite >= 0.4:
                action = "Urgent Repair"
            else:
                action = "Scheduled Maintenance"

            schedule.append({
                "zone_id": zone["zone_id"],
                "zone_name": zone["zone_name"],
                "avg_loss_pct": round(zone["avg_loss_pct"], 2),
                "max_consecutive_hours_above_threshold": zone["max_consecutive_hours"],
                "pipe_risk_score": round(pipe_risks[i], 2),
                "pressure_anomaly_rate": round(anomaly_rates[i], 4),
                "open_work_orders": wo_counts[i],
                "population_served": zone["population_served"],
                "composite_priority_score": round(composite, 2),
                "recommended_action": action
            })

        # Sort by composite score descending, tie-break by zone name ascending
        schedule.sort(key=lambda x: (-x["composite_priority_score"], x["zone_name"]))

        # Assign ranks
        for idx, entry in enumerate(schedule):
            entry["priority_rank"] = idx + 1

        return flagged_zones, schedule

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
        flagged_zones, gt_schedule = self._compute_ground_truth()
        gt_zone_ids = set(z["zone_id"] for z in flagged_zones)
        gt_zone_names = set(z["zone_name"] for z in flagged_zones)

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: Correct flagged zones identified (20 pts) ──
        max_c1 = 20
        max_score += max_c1
        # Check action text for zone names
        found_flagged = set()
        false_positives = 0
        # Parse from action text
        for zone in gt_schedule:
            if zone["zone_name"] in action:
                found_flagged.add(zone["zone_id"])

        # Also check the repair_schedule.csv file
        schedule_path = os.path.join(self.workspace, "repair_schedule.csv")
        file_zone_ids = set()
        if os.path.exists(schedule_path):
            try:
                with open(schedule_path) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        zid = int(row.get("zone_id", -1))
                        file_zone_ids.add(zid)
                        if zid in gt_zone_ids:
                            found_flagged.add(zid)
            except Exception:
                pass

        if gt_zone_ids:
            recall = len(found_flagged) / len(gt_zone_ids)
            # Penalize false positives
            fp_in_file = file_zone_ids - gt_zone_ids
            precision_penalty = min(len(fp_in_file) * 0.1, 0.5)
            score_c1 = max(0, round(max_c1 * (recall - precision_penalty)))
        else:
            score_c1 = max_c1 if not file_zone_ids else 0

        total_score += score_c1
        eval_criteria["flagged_zones_correct"] = {
            "passed": score_c1 == max_c1,
            "score": score_c1,
            "max_score": max_c1,
            "reason": f"Found {len(found_flagged)}/{len(gt_zone_ids)} flagged zones" +
                      (f", {len(file_zone_ids - gt_zone_ids)} false positives" if file_zone_ids - gt_zone_ids else "")
        }

        # ── Criterion 2: repair_schedule.csv exists with correct columns (15 pts) ──
        max_c2 = 15
        max_score += max_c2
        expected_cols = [
            "priority_rank", "zone_id", "zone_name", "avg_loss_pct",
            "max_consecutive_hours_above_threshold", "pipe_risk_score",
            "pressure_anomaly_rate", "open_work_orders", "population_served",
            "composite_priority_score", "recommended_action"
        ]
        score_c2 = 0
        schedule_rows = []
        if os.path.exists(schedule_path):
            try:
                with open(schedule_path) as f:
                    reader = csv.DictReader(f)
                    actual_cols = reader.fieldnames or []
                    schedule_rows = list(reader)
                if set(expected_cols).issubset(set(actual_cols)):
                    score_c2 = max_c2
                else:
                    missing = set(expected_cols) - set(actual_cols)
                    score_c2 = max(0, max_c2 - len(missing) * 2)
            except Exception as e:
                score_c2 = 0
        total_score += score_c2
        eval_criteria["schedule_file_format"] = {
            "passed": score_c2 == max_c2,
            "score": score_c2,
            "max_score": max_c2,
            "reason": "repair_schedule.csv not found or missing columns" if score_c2 < max_c2 else ""
        }

        # ── Criterion 3: Correct priority ranking order (20 pts) ──
        max_c3 = 20
        max_score += max_c3
        score_c3 = 0
        if schedule_rows and gt_schedule:
            try:
                file_order = [int(r["zone_id"]) for r in schedule_rows]
                gt_order = [z["zone_id"] for z in gt_schedule]
                if file_order == gt_order:
                    score_c3 = max_c3
                else:
                    # Partial credit: Kendall tau distance
                    matches = 0
                    total_pairs = 0
                    for i in range(len(gt_order)):
                        for j in range(i + 1, len(gt_order)):
                            if gt_order[i] in file_order and gt_order[j] in file_order:
                                total_pairs += 1
                                fi = file_order.index(gt_order[i])
                                fj = file_order.index(gt_order[j])
                                if fi < fj:
                                    matches += 1
                    if total_pairs > 0:
                        score_c3 = round(max_c3 * matches / total_pairs)
            except Exception:
                score_c3 = 0

        total_score += score_c3
        eval_criteria["priority_ranking"] = {
            "passed": score_c3 == max_c3,
            "score": score_c3,
            "max_score": max_c3,
            "reason": "" if score_c3 == max_c3 else "Priority ordering does not match ground truth"
        }

        # ── Criterion 4: Correct avg_loss_pct values (15 pts) ──
        max_c4 = 15
        max_score += max_c4
        score_c4 = 0
        if schedule_rows and gt_schedule:
            gt_loss_map = {z["zone_id"]: z["avg_loss_pct"] for z in gt_schedule}
            correct = 0
            total_checked = 0
            for row in schedule_rows:
                try:
                    zid = int(row["zone_id"])
                    file_loss = float(row["avg_loss_pct"])
                    if zid in gt_loss_map:
                        total_checked += 1
                        if abs(file_loss - gt_loss_map[zid]) < 0.5:
                            correct += 1
                except (ValueError, KeyError):
                    pass
            if total_checked > 0:
                score_c4 = round(max_c4 * correct / total_checked)

        total_score += score_c4
        eval_criteria["loss_values_accuracy"] = {
            "passed": score_c4 == max_c4,
            "score": score_c4,
            "max_score": max_c4,
            "reason": "" if score_c4 == max_c4 else "Some avg_loss_pct values differ from ground truth"
        }

        # ── Criterion 5: Correct recommended actions (15 pts) ──
        max_c5 = 15
        max_score += max_c5
        score_c5 = 0
        if schedule_rows and gt_schedule:
            gt_action_map = {z["zone_id"]: z["recommended_action"] for z in gt_schedule}
            correct = 0
            total_checked = 0
            for row in schedule_rows:
                try:
                    zid = int(row["zone_id"])
                    file_action = row["recommended_action"].strip()
                    if zid in gt_action_map:
                        total_checked += 1
                        if file_action == gt_action_map[zid]:
                            correct += 1
                except (ValueError, KeyError):
                    pass
            if total_checked > 0:
                score_c5 = round(max_c5 * correct / total_checked)

        total_score += score_c5
        eval_criteria["recommended_actions"] = {
            "passed": score_c5 == max_c5,
            "score": score_c5,
            "max_score": max_c5,
            "reason": "" if score_c5 == max_c5 else "Some recommended actions do not match"
        }

        # ── Criterion 6: Response lists all flagged zone names with loss % (15 pts) ──
        max_c6 = 15
        max_score += max_c6
        score_c6 = 0
        zones_mentioned_with_loss = 0
        for zone in gt_schedule:
            name_in = zone["zone_name"] in action
            # Check if approximate loss pct is mentioned
            loss_str = f"{zone['avg_loss_pct']:.1f}"
            loss_str2 = f"{zone['avg_loss_pct']:.2f}"
            loss_in = loss_str in action or loss_str2 in action
            if name_in and loss_in:
                zones_mentioned_with_loss += 1
            elif name_in:
                zones_mentioned_with_loss += 0.5

        if gt_schedule:
            score_c6 = round(max_c6 * min(zones_mentioned_with_loss / len(gt_schedule), 1.0))

        total_score += score_c6
        eval_criteria["response_completeness"] = {
            "passed": score_c6 == max_c6,
            "score": score_c6,
            "max_score": max_c6,
            "reason": "" if score_c6 == max_c6 else "Response missing some flagged zones or loss percentages"
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
        """
        import csv as csv_mod

        # Step 1: Discover all zones via paginated list_zones
        all_zones = []
        page = 1
        while True:
            result = self.tools["list_zones"](page=page, page_size=10)
            all_zones.extend(result["zones"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 2: Load config files from workspace
        with open(os.path.join(self.workspace, "leakage_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "material_risk_factors.json")) as f:
            risk_config = json.load(f)

        threshold = policy["leakage_detection"]["loss_threshold_pct"]
        consec_hours_req = policy["leakage_detection"]["consecutive_hours_required"]
        weights = policy["priority_scoring"]["weights"]
        current_year = risk_config["current_year_for_calculation"]
        material_multipliers = risk_config["material_risk_multipliers"]

        # Step 3: For each zone, get flow readings and check for persistent leakage
        # We need to query in 2-day windows (tool limit is 48 hours)
        date_ranges = [
            ("2025-03-10 00:00:00", "2025-03-11 23:59:59"),
            ("2025-03-12 00:00:00", "2025-03-13 23:59:59"),
        ]

        flagged_zones = []

        for zone in all_zones:
            zid = zone["zone_id"]

            # Get flow summary first
            summary = self.tools["get_flow_summary"](zone_id=zid)

            # If average loss is clearly below threshold, skip detailed analysis
            if summary["avg_loss_pct"] < threshold - 5:
                continue

            # Get detailed hourly readings to check consecutive hours
            all_readings = []
            for start_dt, end_dt in date_ranges:
                result = self.tools["get_flow_readings"](
                    zone_id=zid, start_datetime=start_dt, end_datetime=end_dt
                )
                all_readings.extend(result["readings"])

            # Compute hourly loss percentages
            hourly_losses = []
            for r in all_readings:
                inflow = r["inflow_m3"]
                outflow = r["outflow_m3"]
                consumption = r["billed_consumption_m3"]
                if inflow > 0:
                    loss_pct = (inflow - outflow - consumption) / inflow * 100
                else:
                    loss_pct = 0
                hourly_losses.append(loss_pct)

            # Find max consecutive hours above threshold
            max_consec = 0
            current_consec = 0
            for lp in hourly_losses:
                if lp > threshold:
                    current_consec += 1
                    max_consec = max(max_consec, current_consec)
                else:
                    current_consec = 0

            if max_consec >= consec_hours_req:
                avg_loss = sum(hourly_losses) / len(hourly_losses) if hourly_losses else 0
                flagged_zones.append({
                    "zone_id": zid,
                    "zone_name": zone["zone_name"],
                    "avg_loss_pct": avg_loss,
                    "max_consecutive_hours": max_consec,
                })

        # Step 4: For flagged zones, get additional data
        # Get zone details (for population)
        zone_details = {}
        for zone in flagged_zones:
            details = self.tools["get_zone_details"](zone_id=zone["zone_id"])
            zone_details[zone["zone_id"]] = details

        # Get pressure anomaly rates
        pressure_anomaly_rates = {}
        dates_to_check = ["2025-03-10", "2025-03-11", "2025-03-12", "2025-03-13"]
        for zone in flagged_zones:
            total_readings = 0
            total_anomalies = 0
            for date in dates_to_check:
                result = self.tools["get_pressure_readings"](zone_id=zone["zone_id"], date=date)
                total_readings += result["total_readings"]
                total_anomalies += result["anomaly_count"]
            pressure_anomaly_rates[zone["zone_id"]] = total_anomalies / total_readings if total_readings > 0 else 0

        # Get open work orders
        open_wo_counts = {}
        for zone in flagged_zones:
            result_open = self.tools["get_work_orders"](zone_id=zone["zone_id"], status_filter="Open")
            result_inprog = self.tools["get_work_orders"](zone_id=zone["zone_id"], status_filter="In Progress")
            open_wo_counts[zone["zone_id"]] = result_open["total_orders"] + result_inprog["total_orders"]

        # Step 5: Load pipe inventory from workspace
        pipe_data = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("pipe_inventory_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv_mod.DictReader(f)
                    for row in reader:
                        zid = int(row["zone_id"])
                        if zid not in pipe_data:
                            pipe_data[zid] = []
                        material = row["material"]
                        install_year = int(row["install_year"])
                        condition_score = float(row["condition_score"])

                        mat_mult = material_multipliers.get(material, 1.0)
                        age_factor = min((current_year - install_year) / 50.0, 2.0)
                        cond_factor = (10 - condition_score) / 9.0
                        pipe_risk = mat_mult * age_factor * cond_factor
                        pipe_data[zid].append(pipe_risk)

        # Step 6: Compute composite priority scores
        pipe_risks = []
        anomaly_rates_list = []
        wo_list = []
        pop_list = []
        avg_losses = []

        for zone in flagged_zones:
            zid = zone["zone_id"]
            avg_losses.append(zone["avg_loss_pct"])
            pr = pipe_data.get(zid, [1.0])
            pipe_risks.append(sum(pr) / len(pr))
            anomaly_rates_list.append(pressure_anomaly_rates.get(zid, 0))
            wo_list.append(open_wo_counts.get(zid, 0))
            pop_list.append(zone_details.get(zid, {}).get("population_served", 0))

        def min_max_normalize(values):
            mn, mx = min(values), max(values)
            if mx == mn:
                return [0.5] * len(values)
            return [(v - mn) / (mx - mn) for v in values]

        norm_loss = min_max_normalize(avg_losses)
        norm_pipe = min_max_normalize(pipe_risks)
        norm_anom = min_max_normalize(anomaly_rates_list)
        norm_wo = min_max_normalize(wo_list)
        norm_pop = min_max_normalize(pop_list)

        schedule = []
        for i, zone in enumerate(flagged_zones):
            composite = (
                weights["avg_loss_rate"] * norm_loss[i] +
                weights["pipe_risk_score"] * norm_pipe[i] +
                weights["pressure_anomaly_rate"] * norm_anom[i] +
                weights["open_work_orders_factor"] * norm_wo[i] +
                weights["population_impact"] * norm_pop[i]
            )

            if composite >= 0.7:
                action = "Emergency Repair"
            elif composite >= 0.4:
                action = "Urgent Repair"
            else:
                action = "Scheduled Maintenance"

            schedule.append({
                "priority_rank": 0,
                "zone_id": zone["zone_id"],
                "zone_name": zone["zone_name"],
                "avg_loss_pct": round(zone["avg_loss_pct"], 2),
                "max_consecutive_hours_above_threshold": zone["max_consecutive_hours"],
                "pipe_risk_score": round(pipe_risks[i], 2),
                "pressure_anomaly_rate": round(anomaly_rates_list[i], 4),
                "open_work_orders": wo_list[i],
                "population_served": pop_list[i],
                "composite_priority_score": round(composite, 2),
                "recommended_action": action
            })

        # Sort by composite score descending, tie-break by zone name ascending
        schedule.sort(key=lambda x: (-x["composite_priority_score"], x["zone_name"]))
        for idx, entry in enumerate(schedule):
            entry["priority_rank"] = idx + 1

        # Step 7: Write repair_schedule.csv
        columns = [
            "priority_rank", "zone_id", "zone_name", "avg_loss_pct",
            "max_consecutive_hours_above_threshold", "pipe_risk_score",
            "pressure_anomaly_rate", "open_work_orders", "population_served",
            "composite_priority_score", "recommended_action"
        ]
        schedule_path = os.path.join(self.workspace, "repair_schedule.csv")
        with open(schedule_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for entry in schedule:
                writer.writerow(entry)

        # Step 8: Build action string
        action_lines = ["Persistent High Leakage Analysis Complete.\n"]
        action_lines.append(f"Flagged {len(schedule)} zones with water loss exceeding 15% for 72+ consecutive hours:\n")
        for entry in schedule:
            action_lines.append(
                f"Priority #{entry['priority_rank']}: {entry['zone_name']} (Zone {entry['zone_id']}) - "
                f"Avg Loss: {entry['avg_loss_pct']:.2f}%, "
                f"Max Consecutive Hours: {entry['max_consecutive_hours_above_threshold']}, "
                f"Composite Score: {entry['composite_priority_score']:.2f}, "
                f"Action: {entry['recommended_action']}"
            )
        action_lines.append(f"\nRepair schedule has been saved to repair_schedule.csv with full details.")

        action = "\n".join(action_lines)

        return self.step(action)
