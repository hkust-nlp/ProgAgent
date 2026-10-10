"""
Environment for conveyor belt replacement optimization task.
"""

import csv
import json
import os
import sqlite3
from datetime import datetime, timedelta
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

    def get_assistant_tools(self) -> List[Dict[str, Any]]:
        """
        Get tool definitions in OpenAI function calling format.
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

    # ── Tool Methods ─────────────────────────────────────────────────────

    @tool(
        description="List conveyor belts with basic information, paginated. Returns a list of belt records with belt_id, line_id, belt_type, status, and operating_hours.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 20)",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_belts(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM conveyor_belts")
        total = cursor.fetchone()[0]
        cursor.execute(
            "SELECT belt_id, line_id, belt_type, status, operating_hours "
            "FROM conveyor_belts ORDER BY belt_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return _envelope({
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": (total + page_size - 1) // page_size,
            "records": rows,
        })

    @tool(
        description="Get full details for a specific conveyor belt by its belt_id. Returns all belt attributes including manufacturer, install_date, length_meters, and width_mm.",
        parameters={
            "type": "object",
            "properties": {
                "belt_id": {
                    "type": "string",
                    "description": "The belt identifier, e.g. BELT-0001",
                },
            },
            "required": ["belt_id"],
        },
    )
    def get_belt_details(self, belt_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM conveyor_belts WHERE belt_id = ?", (belt_id,))
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"Belt {belt_id} not found"}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description="Get the latest vibration sensor reading for a specific belt. Returns rms_velocity_mm_s, peak_acceleration_g, dominant_freq_hz, and bearing_temp_c.",
        parameters={
            "type": "object",
            "properties": {
                "belt_id": {
                    "type": "string",
                    "description": "The belt identifier",
                },
            },
            "required": ["belt_id"],
        },
    )
    def get_vibration_reading(self, belt_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM vibration_readings WHERE belt_id = ? ORDER BY timestamp DESC LIMIT 1",
            (belt_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"No vibration readings found for {belt_id}"}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description="Get vibration readings for all belts on a specific production line. Returns a list of the latest reading per belt on that line.",
        parameters={
            "type": "object",
            "properties": {
                "line_id": {
                    "type": "string",
                    "description": "The production line identifier, e.g. LINE-01",
                },
            },
            "required": ["line_id"],
        },
    )
    def get_line_vibration_summary(self, line_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT vr.* FROM vibration_readings vr
            INNER JOIN (
                SELECT vr2.belt_id, MAX(vr2.timestamp) as max_ts
                FROM vibration_readings vr2
                INNER JOIN conveyor_belts cb ON vr2.belt_id = cb.belt_id
                WHERE cb.line_id = ?
                GROUP BY vr2.belt_id
            ) latest ON vr.belt_id = latest.belt_id AND vr.timestamp = latest.max_ts
            ORDER BY vr.belt_id
            """,
            (line_id,),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return json.dumps({"line_id": line_id, "readings": rows}, ensure_ascii=False, default=str)

    @tool(
        description="Get aggregated lifespan statistics for a given belt type from historical component failure records. Returns average, median, and standard deviation of hours_at_failure, plus the number of records and most common failure modes.",
        parameters={
            "type": "object",
            "properties": {
                "belt_type": {
                    "type": "string",
                    "description": "The belt type, e.g. heavy-duty-rubber",
                },
            },
            "required": ["belt_type"],
        },
    )
    def get_lifespan_stats(self, belt_type: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT hours_at_failure FROM component_lifespan_logs WHERE belt_type = ?",
            (belt_type,),
        )
        hours_list = [r[0] for r in cursor.fetchall()]

        if not hours_list:
            conn.close()
            return _envelope({"error": f"No lifespan records found for {belt_type}"})

        import numpy as np

        cursor.execute(
            "SELECT failure_mode, COUNT(*) as cnt FROM component_lifespan_logs "
            "WHERE belt_type = ? GROUP BY failure_mode ORDER BY cnt DESC LIMIT 3",
            (belt_type,),
        )
        failure_modes = [{"mode": r[0], "count": r[1]} for r in cursor.fetchall()]
        conn.close()

        return _envelope({
            "belt_type": belt_type,
            "avg_hours_to_failure": round(float(np.mean(hours_list)), 1),
            "median_hours": round(float(np.median(hours_list)), 1),
            "std_dev_hours": round(float(np.std(hours_list)), 1),
            "num_records": len(hours_list),
            "common_failure_modes": failure_modes,
        })

    @tool(
        description="Get the production schedule for a specific line on a specific date. Returns all shifts with product_type, throughput_units_hr, and priority_level.",
        parameters={
            "type": "object",
            "properties": {
                "line_id": {
                    "type": "string",
                    "description": "The production line identifier",
                },
                "date": {
                    "type": "string",
                    "description": "The date in YYYY-MM-DD format",
                },
            },
            "required": ["line_id", "date"],
        },
    )
    def get_production_schedule(self, line_id: str, date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM production_schedules WHERE line_id = ? AND date = ? ORDER BY shift",
            (line_id, date),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return _envelope({"line_id": line_id, "date": date, "shifts": rows})

    @tool(
        description="Query supplier options for a given belt type. Returns all available suppliers with lead_time_days, unit_cost, min_order_qty, and reliability_rating.",
        parameters={
            "type": "object",
            "properties": {
                "belt_type": {
                    "type": "string",
                    "description": "The belt type to search for",
                },
            },
            "required": ["belt_type"],
        },
    )
    def get_supplier_options(self, belt_type: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM supplier_catalog WHERE belt_type = ? ORDER BY supplier_id",
            (belt_type,),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return _envelope({"belt_type": belt_type, "suppliers": rows})

    @tool(
        description="Get all scheduled production dates for a specific line within a date range. Returns a list of dates that have scheduled production.",
        parameters={
            "type": "object",
            "properties": {
                "line_id": {
                    "type": "string",
                    "description": "The production line identifier",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format",
                },
            },
            "required": ["line_id", "start_date", "end_date"],
        },
    )
    def get_scheduled_dates(self, line_id: str, start_date: str, end_date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT DISTINCT date FROM production_schedules "
            "WHERE line_id = ? AND date >= ? AND date <= ? ORDER BY date",
            (line_id, start_date, end_date),
        )
        dates = [r[0] for r in cursor.fetchall()]
        conn.close()
        return json.dumps({"line_id": line_id, "start_date": start_date, "end_date": end_date, "dates": dates}, ensure_ascii=False, default=str)

    # ── Evaluation ───────────────────────────────────────────────────────

    def _compute_ground_truth(self) -> List[Dict[str, Any]]:
        """Compute the ground-truth maintenance calendar."""
        import numpy as np

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load workspace configs
        with open(os.path.join(self.workspace, "maintenance_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "supplier_contracts.json")) as f:
            contracts = json.load(f)

        cost_params = {}
        with open(os.path.join(self.workspace, "cost_parameters.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                cost_params[row["belt_type"]] = {
                    "labor_cost": float(row["labor_cost"]),
                    "estimated_downtime_hours": int(row["estimated_downtime_hours"]),
                }

        with open(os.path.join(self.workspace, "planning_horizon.txt")) as f:
            planning_text = f.read()
        ref_date = datetime.strptime("2025-07-01", "%Y-%m-%d")
        planning_window = 60

        # Load inspection data for visual wear scores
        wear_scores = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("inspection_report_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    batch = json.load(f)
                for entry in batch:
                    wear_scores[entry["belt_id"]] = entry["visual_wear_score"]

        # Get all belts
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM conveyor_belts ORDER BY belt_id")
        belts = [dict(r) for r in cursor.fetchall()]

        # Get latest vibration per belt
        vibrations = {}
        cursor.execute(
            """
            SELECT vr.* FROM vibration_readings vr
            INNER JOIN (
                SELECT belt_id, MAX(timestamp) as max_ts
                FROM vibration_readings GROUP BY belt_id
            ) latest ON vr.belt_id = latest.belt_id AND vr.timestamp = latest.max_ts
            """
        )
        for row in cursor.fetchall():
            vibrations[row[1]] = {  # belt_id is index 1
                "rms_velocity_mm_s": row[3],
                "peak_acceleration_g": row[4],
                "dominant_freq_hz": row[5],
                "bearing_temp_c": row[6],
            }

        # Get lifespan stats per belt type
        lifespan_avgs = {}
        for bt in set(b["belt_type"] for b in belts):
            cursor.execute(
                "SELECT AVG(hours_at_failure) FROM component_lifespan_logs WHERE belt_type = ?",
                (bt,),
            )
            result = cursor.fetchone()
            lifespan_avgs[bt] = result[0] if result[0] else 20000

        # Thresholds from policy
        vib_thresholds = policy["vibration_thresholds"]
        wear_threshold = policy["wear_threshold"]
        safety_factor = policy["safety_factor"]
        maint_priority_threshold = policy["maintenance_priority_threshold"]

        # Supplier selection
        preferred = set(contracts["preferred_suppliers"])
        preferred_mult = contracts["preferred_discount_multiplier"]

        # Get all suppliers
        suppliers_by_type = {}
        cursor.execute("SELECT * FROM supplier_catalog ORDER BY supplier_id")
        for row in cursor.fetchall():
            bt = row[3]
            if bt not in suppliers_by_type:
                suppliers_by_type[bt] = []
            suppliers_by_type[bt].append({
                "catalog_id": row[0],
                "supplier_id": row[1],
                "supplier_name": row[2],
                "belt_type": row[3],
                "lead_time_days": row[4],
                "unit_cost": row[5],
                "min_order_qty": row[6],
                "reliability_rating": row[7],
            })

        # Get all production schedules
        schedules = {}
        cursor.execute("SELECT * FROM production_schedules ORDER BY line_id, date, shift")
        for row in cursor.fetchall():
            key = (row[1], row[2])  # (line_id, date)
            if key not in schedules:
                schedules[key] = []
            schedules[key].append({
                "shift": row[3],
                "throughput_units_hr": row[5],
                "priority_level": row[6],
            })

        conn.close()

        # Determine replacements
        calendar = []
        for belt in belts:
            bid = belt["belt_id"]
            bt = belt["belt_type"]
            line_id = belt["line_id"]
            op_hours = belt["operating_hours"]

            vib = vibrations.get(bid, {})
            rms = vib.get("rms_velocity_mm_s", 0.0)
            wear = wear_scores.get(bid, 0)
            avg_life = lifespan_avgs.get(bt, 20000)

            # Check three replacement criteria
            warning_thresh = vib_thresholds.get(bt, {}).get("warning", 999)
            critical_thresh = vib_thresholds.get(bt, {}).get("critical", 999)

            crit_vibration = rms > warning_thresh
            crit_wear = wear >= wear_threshold
            crit_lifespan = op_hours > avg_life * safety_factor

            criteria_met = sum([crit_vibration, crit_wear, crit_lifespan])

            if criteria_met == 0:
                continue  # No replacement needed

            # Determine urgency
            if rms > critical_thresh:
                urgency = "CRITICAL"
            elif criteria_met >= 2:
                urgency = "HIGH"
            else:
                urgency = "MODERATE"

            # Select best supplier
            options = suppliers_by_type.get(bt, [])
            best_supplier = None
            best_score = float("inf")
            best_lead = float("inf")
            best_sid = ""
            for sup in options:
                score = sup["unit_cost"] * (1 - sup["reliability_rating"] / 10)
                if sup["supplier_id"] in preferred:
                    score *= preferred_mult
                if (score < best_score
                    or (score == best_score and sup["lead_time_days"] < best_lead)
                    or (score == best_score and sup["lead_time_days"] == best_lead and sup["supplier_id"] < best_sid)):
                    best_score = score
                    best_lead = sup["lead_time_days"]
                    best_sid = sup["supplier_id"]
                    best_supplier = sup

            if best_supplier is None:
                continue

            # Compute earliest possible date
            earliest = ref_date + timedelta(days=best_supplier["lead_time_days"])

            # Schedule replacement date
            if urgency == "CRITICAL":
                replacement_date = earliest
            else:
                # Find first maintenance-eligible day
                replacement_date = None
                for day_offset in range(planning_window + 1):
                    candidate = earliest + timedelta(days=day_offset)
                    key = (line_id, candidate.strftime("%Y-%m-%d"))
                    shifts = schedules.get(key, [])
                    if not shifts:
                        # No production scheduled = eligible
                        replacement_date = candidate
                        break
                    max_priority = max(s["priority_level"] for s in shifts)
                    if max_priority <= maint_priority_threshold:
                        replacement_date = candidate
                        break

                if replacement_date is None:
                    replacement_date = earliest + timedelta(days=30)

            # Compute estimated cost
            labor = cost_params.get(bt, {}).get("labor_cost", 0)
            estimated_cost = round(best_supplier["unit_cost"] + labor, 2)

            # Compute production impact score
            key = (line_id, replacement_date.strftime("%Y-%m-%d"))
            shifts = schedules.get(key, [])
            impact = round(sum(s["throughput_units_hr"] for s in shifts), 1)

            calendar.append({
                "belt_id": bid,
                "replacement_date": replacement_date.strftime("%Y-%m-%d"),
                "supplier_id": best_supplier["supplier_id"],
                "estimated_cost": estimated_cost,
                "urgency_tier": urgency,
                "production_impact_score": impact,
            })

        # Sort: replacement_date ascending, then urgency descending (CRITICAL > HIGH > MODERATE)
        urgency_order = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2}
        calendar.sort(key=lambda x: (x["replacement_date"], urgency_order.get(x["urgency_tier"], 9)))

        return calendar

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        ground_truth = self._compute_ground_truth()

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: Calendar file exists and has correct columns (10 pts) ──
        max_score += 10
        cal_path = os.path.join(self.workspace, "maintenance_calendar.csv")
        cal_exists = os.path.exists(cal_path)
        expected_cols = ["belt_id", "replacement_date", "supplier_id", "estimated_cost",
                         "urgency_tier", "production_impact_score"]
        correct_cols = False
        agent_calendar = []
        if cal_exists:
            with open(cal_path) as f:
                reader = csv.DictReader(f)
                actual_cols = [c.strip() for c in (reader.fieldnames or [])]
                correct_cols = actual_cols == expected_cols
                for row in reader:
                    cleaned = {k.strip(): v.strip() for k, v in row.items()}
                    agent_calendar.append(cleaned)

        if cal_exists and correct_cols:
            eval_criteria["file_format"] = {"passed": True, "score": 10, "max_score": 10}
            total_score += 10
        else:
            reason = "File not found" if not cal_exists else f"Expected columns {expected_cols}, got {actual_cols if cal_exists else 'N/A'}"
            eval_criteria["file_format"] = {"passed": False, "score": 0, "max_score": 10, "reason": reason}

        # ── Criterion 2: Correct belt identification (25 pts) ──
        max_score += 25
        gt_belt_ids = set(r["belt_id"] for r in ground_truth)
        agent_belt_ids = set(r.get("belt_id", "") for r in agent_calendar)

        if gt_belt_ids and agent_belt_ids:
            correct_ids = gt_belt_ids & agent_belt_ids
            precision = len(correct_ids) / len(agent_belt_ids) if agent_belt_ids else 0
            recall = len(correct_ids) / len(gt_belt_ids) if gt_belt_ids else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            belt_score = round(25 * f1)
            passed = f1 >= 0.95
        elif not gt_belt_ids and not agent_belt_ids:
            belt_score = 25
            passed = True
            f1 = 1.0
        else:
            belt_score = 0
            passed = False
            f1 = 0

        eval_criteria["belt_identification"] = {
            "passed": passed,
            "score": belt_score,
            "max_score": 25,
            "reason": "" if passed else f"F1={f1:.3f}, expected {len(gt_belt_ids)} belts, got {len(agent_belt_ids)}"
        }
        total_score += belt_score

        # ── Criterion 3: Correct urgency tier assignment (20 pts) ──
        max_score += 20
        gt_urgency = {r["belt_id"]: r["urgency_tier"] for r in ground_truth}
        agent_urgency = {r.get("belt_id", ""): r.get("urgency_tier", "") for r in agent_calendar}
        correct_urgency = sum(1 for bid in gt_urgency if agent_urgency.get(bid) == gt_urgency[bid])
        urgency_ratio = correct_urgency / len(gt_urgency) if gt_urgency else 1.0
        urgency_score = round(20 * urgency_ratio)
        eval_criteria["urgency_assignment"] = {
            "passed": urgency_ratio >= 0.95,
            "score": urgency_score,
            "max_score": 20,
            "reason": "" if urgency_ratio >= 0.95 else f"{correct_urgency}/{len(gt_urgency)} correct"
        }
        total_score += urgency_score

        # ── Criterion 4: Correct supplier selection (15 pts) ──
        max_score += 15
        gt_supplier = {r["belt_id"]: r["supplier_id"] for r in ground_truth}
        agent_supplier = {r.get("belt_id", ""): r.get("supplier_id", "") for r in agent_calendar}
        correct_supplier = sum(1 for bid in gt_supplier if agent_supplier.get(bid) == gt_supplier[bid])
        supplier_ratio = correct_supplier / len(gt_supplier) if gt_supplier else 1.0
        supplier_score = round(15 * supplier_ratio)
        eval_criteria["supplier_selection"] = {
            "passed": supplier_ratio >= 0.95,
            "score": supplier_score,
            "max_score": 15,
            "reason": "" if supplier_ratio >= 0.95 else f"{correct_supplier}/{len(gt_supplier)} correct"
        }
        total_score += supplier_score

        # ── Criterion 5: Correct replacement dates (15 pts) ──
        max_score += 15
        gt_dates = {r["belt_id"]: r["replacement_date"] for r in ground_truth}
        agent_dates = {r.get("belt_id", ""): r.get("replacement_date", "") for r in agent_calendar}
        correct_dates = sum(1 for bid in gt_dates if agent_dates.get(bid) == gt_dates[bid])
        date_ratio = correct_dates / len(gt_dates) if gt_dates else 1.0
        date_score = round(15 * date_ratio)
        eval_criteria["replacement_dates"] = {
            "passed": date_ratio >= 0.95,
            "score": date_score,
            "max_score": 15,
            "reason": "" if date_ratio >= 0.95 else f"{correct_dates}/{len(gt_dates)} correct"
        }
        total_score += date_score

        # ── Criterion 6: Correct cost and impact values (10 pts) ──
        max_score += 10
        gt_costs = {r["belt_id"]: (r["estimated_cost"], r["production_impact_score"]) for r in ground_truth}
        correct_values = 0
        for bid in gt_costs:
            agent_row = next((r for r in agent_calendar if r.get("belt_id") == bid), None)
            if agent_row:
                try:
                    a_cost = float(agent_row.get("estimated_cost", -1))
                    a_impact = float(agent_row.get("production_impact_score", -1))
                    if abs(a_cost - gt_costs[bid][0]) < 0.01 and abs(a_impact - gt_costs[bid][1]) < 0.15:
                        correct_values += 1
                except (ValueError, TypeError):
                    pass
        value_ratio = correct_values / len(gt_costs) if gt_costs else 1.0
        value_score = round(10 * value_ratio)
        eval_criteria["cost_and_impact"] = {
            "passed": value_ratio >= 0.95,
            "score": value_score,
            "max_score": 10,
            "reason": "" if value_ratio >= 0.95 else f"{correct_values}/{len(gt_costs)} correct"
        }
        total_score += value_score

        # ── Criterion 7: Response contains summary stats (5 pts) ──
        max_score += 5
        action_lower = action.lower() if action else ""
        has_total_count = str(len(ground_truth)) in action
        urgency_counts = {}
        for r in ground_truth:
            urgency_counts[r["urgency_tier"]] = urgency_counts.get(r["urgency_tier"], 0) + 1

        total_cost = round(sum(r["estimated_cost"] for r in ground_truth), 2)
        # Check if response mentions the total cost (allow some formatting variation)
        cost_str = f"{total_cost:.2f}"
        has_cost = cost_str in action or str(int(total_cost)) in action

        summary_score = 0
        if has_total_count:
            summary_score += 3
        if has_cost:
            summary_score += 2
        eval_criteria["response_summary"] = {
            "passed": summary_score >= 4,
            "score": summary_score,
            "max_score": 5,
            "reason": "" if summary_score >= 4 else "Missing total count or total cost in response"
        }
        total_score += summary_score

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
        import csv as _csv
        from datetime import datetime as _dt, timedelta as _td

        # ── Step 1: Read workspace config files ──
        with open(os.path.join(self.workspace, "maintenance_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "supplier_contracts.json")) as f:
            contracts = json.load(f)

        cost_params = {}
        with open(os.path.join(self.workspace, "cost_parameters.csv")) as f:
            reader = _csv.DictReader(f)
            for row in reader:
                cost_params[row["belt_type"]] = {
                    "labor_cost": float(row["labor_cost"]),
                    "estimated_downtime_hours": int(row["estimated_downtime_hours"]),
                }

        with open(os.path.join(self.workspace, "planning_horizon.txt")) as f:
            planning_text = f.read()

        with open(os.path.join(self.workspace, "downtime_cost_rates.yaml")) as f:
            downtime_rates = yaml.safe_load(f)

        ref_date = _dt.strptime("2025-07-01", "%Y-%m-%d")
        planning_window = 60

        # ── Step 2: Load inspection reports for wear scores ──
        wear_scores = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("inspection_report_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    batch = json.load(f)
                for entry in batch:
                    wear_scores[entry["belt_id"]] = entry["visual_wear_score"]

        # ── Step 3: List all belts using tools (paginated) ──
        all_belts = []
        page = 1
        tool_call_count = 0
        while True:
            result = json.loads(self.tools["list_belts"](page=page, page_size=20)["content"][0]["text"])
            tool_call_count += 1
            all_belts.extend(result["records"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ── Step 4: Get lifespan stats per belt type ──
        belt_types_seen = set(b["belt_type"] for b in all_belts)
        lifespan_stats = {}
        for bt in belt_types_seen:
            stats = json.loads(self.tools["get_lifespan_stats"](belt_type=bt)["content"][0]["text"])
            tool_call_count += 1
            lifespan_stats[bt] = stats

        # ── Step 5: Get vibration data per line ──
        lines_seen = set(b["line_id"] for b in all_belts)
        vibration_data = {}  # belt_id -> reading
        for line_id in sorted(lines_seen):
            result = json.loads(self.tools["get_line_vibration_summary"](line_id=line_id))
            tool_call_count += 1
            for reading in result["readings"]:
                vibration_data[reading["belt_id"]] = reading

        # ── Step 6: Determine which belts need replacement ──
        vib_thresholds = policy["vibration_thresholds"]
        wear_threshold = policy["wear_threshold"]
        safety_factor = policy["safety_factor"]
        maint_priority_threshold = policy["maintenance_priority_threshold"]

        replacement_candidates = []
        for belt in all_belts:
            bid = belt["belt_id"]
            bt = belt["belt_type"]
            op_hours = belt["operating_hours"]

            vib = vibration_data.get(bid, {})
            rms = vib.get("rms_velocity_mm_s", 0.0)
            wear = wear_scores.get(bid, 0)
            avg_life = lifespan_stats.get(bt, {}).get("avg_hours_to_failure", 20000)

            warning_thresh = vib_thresholds.get(bt, {}).get("warning", 999)
            critical_thresh = vib_thresholds.get(bt, {}).get("critical", 999)

            crit_vibration = rms > warning_thresh
            crit_wear = wear >= wear_threshold
            crit_lifespan = op_hours > avg_life * safety_factor

            criteria_met = sum([crit_vibration, crit_wear, crit_lifespan])
            if criteria_met == 0:
                continue

            if rms > critical_thresh:
                urgency = "CRITICAL"
            elif criteria_met >= 2:
                urgency = "HIGH"
            else:
                urgency = "MODERATE"

            replacement_candidates.append({
                "belt_id": bid,
                "belt_type": bt,
                "line_id": belt["line_id"],
                "urgency": urgency,
            })

        # ── Step 7: Get supplier options per belt type ──
        preferred = set(contracts["preferred_suppliers"])
        preferred_mult = contracts["preferred_discount_multiplier"]

        best_suppliers = {}
        for bt in belt_types_seen:
            result = json.loads(self.tools["get_supplier_options"](belt_type=bt)["content"][0]["text"])
            tool_call_count += 1
            options = result["suppliers"]

            best = None
            best_score = float("inf")
            best_lead = float("inf")
            best_sid = ""
            for sup in options:
                score = sup["unit_cost"] * (1 - sup["reliability_rating"] / 10)
                if sup["supplier_id"] in preferred:
                    score *= preferred_mult
                if (score < best_score
                    or (score == best_score and sup["lead_time_days"] < best_lead)
                    or (score == best_score and sup["lead_time_days"] == best_lead and sup["supplier_id"] < best_sid)):
                    best_score = score
                    best_lead = sup["lead_time_days"]
                    best_sid = sup["supplier_id"]
                    best = sup
            best_suppliers[bt] = best

        # ── Step 8: Schedule replacements ──
        # Get scheduled dates for each line
        end_date_str = (ref_date + _td(days=planning_window + 40)).strftime("%Y-%m-%d")

        line_schedules = {}  # (line_id, date_str) -> list of shifts
        for line_id in sorted(lines_seen):
            dates_result = json.loads(self.tools["get_scheduled_dates"](
                line_id=line_id,
                start_date=ref_date.strftime("%Y-%m-%d"),
                end_date=end_date_str,
            ))
            tool_call_count += 1

            for date_str in dates_result["dates"]:
                sched = json.loads(self.tools["get_production_schedule"](line_id=line_id, date=date_str)["content"][0]["text"])
                tool_call_count += 1
                line_schedules[(line_id, date_str)] = sched["shifts"]

        # Build calendar
        calendar = []
        for cand in replacement_candidates:
            bid = cand["belt_id"]
            bt = cand["belt_type"]
            line_id = cand["line_id"]
            urgency = cand["urgency"]

            supplier = best_suppliers.get(bt)
            if supplier is None:
                continue

            earliest = ref_date + _td(days=supplier["lead_time_days"])

            if urgency == "CRITICAL":
                replacement_date = earliest
            else:
                replacement_date = None
                for day_offset in range(planning_window + 1):
                    candidate_date = earliest + _td(days=day_offset)
                    date_str = candidate_date.strftime("%Y-%m-%d")
                    key = (line_id, date_str)
                    shifts = line_schedules.get(key, [])
                    if not shifts:
                        replacement_date = candidate_date
                        break
                    max_priority = max(s["priority_level"] for s in shifts)
                    if max_priority <= maint_priority_threshold:
                        replacement_date = candidate_date
                        break
                if replacement_date is None:
                    replacement_date = earliest + _td(days=30)

            labor = cost_params.get(bt, {}).get("labor_cost", 0)
            estimated_cost = round(supplier["unit_cost"] + labor, 2)

            date_str = replacement_date.strftime("%Y-%m-%d")
            key = (line_id, date_str)
            shifts = line_schedules.get(key, [])
            impact = round(sum(s["throughput_units_hr"] for s in shifts), 1)

            calendar.append({
                "belt_id": bid,
                "replacement_date": date_str,
                "supplier_id": supplier["supplier_id"],
                "estimated_cost": estimated_cost,
                "urgency_tier": urgency,
                "production_impact_score": impact,
            })

        # Sort
        urgency_order = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2}
        calendar.sort(key=lambda x: (x["replacement_date"], urgency_order.get(x["urgency_tier"], 9)))

        # ── Step 9: Write maintenance_calendar.csv ──
        cal_path = os.path.join(self.workspace, "maintenance_calendar.csv")
        fieldnames = ["belt_id", "replacement_date", "supplier_id", "estimated_cost",
                      "urgency_tier", "production_impact_score"]
        with open(cal_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(calendar)

        # ── Step 10: Build response summary ──
        total_cost = round(sum(r["estimated_cost"] for r in calendar), 2)
        urgency_counts = {}
        for r in calendar:
            urgency_counts[r["urgency_tier"]] = urgency_counts.get(r["urgency_tier"], 0) + 1

        action = (
            f"Maintenance calendar has been generated with {len(calendar)} belts scheduled for replacement. "
            f"Total estimated cost: {total_cost:.2f}. "
            f"Urgency distribution: "
            + ", ".join(f"{k}: {v}" for k, v in sorted(urgency_counts.items()))
            + "."
        )

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need at least 15"

        return self.step(action)
