"""
Environment for Technician Performance & Retraining Priority task.
"""

import csv
import json
import os
import sqlite3
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

    # ═══════════════════════════════════════════════════════
    # ── TOOL METHODS ──
    # ═══════════════════════════════════════════════════════

    @tool(
        description="Lists technicians with pagination. Returns a page of technician records including id, name, certification_level, hire_date, and region.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 20).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_technicians(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, certification_level, hire_date, region "
            "FROM technicians ORDER BY id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM technicians")
        total = cur.fetchone()[0]
        conn.close()
        return _envelope({
            "technicians": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        })

    @tool(
        description="Retrieves completed appointments for a given technician. Returns appointment id, customer_id, service_category_id, scheduled_date, scheduled_start_time, scheduled_end_time, and status. Only completed appointments are returned.",
        parameters={
            "type": "object",
            "properties": {
                "technician_id": {
                    "type": "string",
                    "description": "Technician ID, e.g. 'TECH_0001'.",
                },
            },
            "required": ["technician_id"],
        },
    )
    def get_technician_appointments(self, technician_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, customer_id, service_category_id, scheduled_date, "
            "scheduled_start_time, scheduled_end_time, status "
            "FROM appointments WHERE technician_id = ? AND status = 'completed' "
            "ORDER BY scheduled_date, scheduled_start_time",
            (technician_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return _envelope({"technician_id": technician_id, "appointments": rows})

    @tool(
        description="Retrieves satisfaction survey results for a given technician. Returns survey id, appointment_id, customer_id, overall_score, punctuality_score, professionalism_score, resolution_score, and survey_date.",
        parameters={
            "type": "object",
            "properties": {
                "technician_id": {
                    "type": "string",
                    "description": "Technician ID, e.g. 'TECH_0001'.",
                },
            },
            "required": ["technician_id"],
        },
    )
    def get_technician_surveys(self, technician_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, appointment_id, customer_id, overall_score, "
            "punctuality_score, professionalism_score, resolution_score, survey_date "
            "FROM satisfaction_surveys WHERE technician_id = ? ORDER BY survey_date",
            (technician_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return json.dumps({"technician_id": technician_id, "surveys": rows}, ensure_ascii=False, default=str)

    @tool(
        description="Retrieves details for a specific service category by its ID. Returns name, complexity_rating, avg_duration_minutes, and description.",
        parameters={
            "type": "object",
            "properties": {
                "category_id": {
                    "type": "integer",
                    "description": "Service category ID.",
                },
            },
            "required": ["category_id"],
        },
    )
    def get_service_category(self, category_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, complexity_rating, avg_duration_minutes, description "
            "FROM service_categories WHERE id = ?",
            (category_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"Category {category_id} not found"}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description="Retrieves details for a specific appointment by its ID. Returns technician_id, customer_id, service_category_id, scheduled_date, scheduled_start_time, scheduled_end_time, status, and region.",
        parameters={
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "Appointment ID, e.g. 'APPT_00001'.",
                },
            },
            "required": ["appointment_id"],
        },
    )
    def get_appointment_details(self, appointment_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, technician_id, customer_id, service_category_id, "
            "scheduled_date, scheduled_start_time, scheduled_end_time, "
            "status, region "
            "FROM appointments WHERE id = ?",
            (appointment_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"Appointment {appointment_id} not found"}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description="Retrieves customer information by customer ID. Returns name, address, phone, email, and tier.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Customer ID, e.g. 'CUST_0001'.",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_customer_info(self, customer_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, address, phone, email, tier "
            "FROM customers WHERE id = ?",
            (customer_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _envelope({"error": f"Customer {customer_id} not found"})
        return _envelope(dict(row))

    # ═══════════════════════════════════════════════════════
    # ── STEP (EVALUATION) ──
    # ═══════════════════════════════════════════════════════

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        import yaml

        # ── Compute ground truth ──
        gt = self._compute_ground_truth()

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: Output file exists with correct columns (10 pts) ──
        c1_max = 10
        max_score += c1_max
        csv_path = os.path.join(self.workspace, "retraining_priority.csv")
        expected_columns = [
            "technician_id", "technician_name", "total_tracked_appointments",
            "late_count", "late_rate", "avg_satisfaction", "avg_complexity_weight",
            "priority_score", "primary_issue",
        ]
        if os.path.exists(csv_path):
            try:
                with open(csv_path, "r") as f:
                    reader = csv.DictReader(f)
                    output_rows = list(reader)
                    output_cols = reader.fieldnames or []
                if set(expected_columns).issubset(set(output_cols)):
                    eval_criteria["file_structure"] = {
                        "passed": True, "score": c1_max, "max_score": c1_max,
                    }
                    total_score += c1_max
                else:
                    missing = set(expected_columns) - set(output_cols)
                    eval_criteria["file_structure"] = {
                        "passed": False, "score": 5, "max_score": c1_max,
                        "reason": f"Missing columns: {missing}",
                    }
                    total_score += 5
            except Exception as e:
                output_rows = []
                eval_criteria["file_structure"] = {
                    "passed": False, "score": 0, "max_score": c1_max,
                    "reason": f"Error reading CSV: {e}",
                }
        else:
            output_rows = []
            eval_criteria["file_structure"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "retraining_priority.csv not found",
            }

        # ── Criterion 2: Correct set of flagged technicians (25 pts) ──
        c2_max = 25
        max_score += c2_max
        gt_flagged_ids = set(gt["flagged_tech_ids"])
        output_ids = set()
        if output_rows:
            output_ids = {r.get("technician_id", "").strip() for r in output_rows}
        if gt_flagged_ids and output_ids == gt_flagged_ids:
            eval_criteria["correct_technicians"] = {
                "passed": True, "score": c2_max, "max_score": c2_max,
            }
            total_score += c2_max
        else:
            # Partial credit: Jaccard similarity
            if gt_flagged_ids or output_ids:
                intersection = gt_flagged_ids & output_ids
                union = gt_flagged_ids | output_ids
                jaccard = len(intersection) / len(union) if union else 0.0
                pts = round(c2_max * jaccard)
            else:
                pts = 0
            eval_criteria["correct_technicians"] = {
                "passed": False, "score": pts, "max_score": c2_max,
                "reason": f"Expected {len(gt_flagged_ids)} technicians, got {len(output_ids)}. "
                          f"Missing: {gt_flagged_ids - output_ids}, Extra: {output_ids - gt_flagged_ids}",
            }
            total_score += pts

        # ── Criterion 3: Late arrival rates correct (20 pts) ──
        c3_max = 20
        max_score += c3_max
        if output_rows and gt_flagged_ids:
            correct_rates = 0
            total_checked = 0
            for row in output_rows:
                tid = row.get("technician_id", "").strip()
                if tid in gt["tech_data"]:
                    total_checked += 1
                    try:
                        out_rate = float(row.get("late_rate", -1))
                        gt_rate = gt["tech_data"][tid]["late_rate"]
                        if abs(out_rate - gt_rate) < 0.02:
                            correct_rates += 1
                    except (ValueError, TypeError):
                        pass
            if total_checked > 0:
                frac = correct_rates / total_checked
                pts = round(c3_max * frac)
            else:
                pts = 0
            passed = pts == c3_max
            eval_criteria["late_rates"] = {
                "passed": passed, "score": pts, "max_score": c3_max,
            }
            if not passed:
                eval_criteria["late_rates"]["reason"] = (
                    f"{correct_rates}/{total_checked} late rates matched within tolerance"
                )
            total_score += pts
        else:
            eval_criteria["late_rates"] = {
                "passed": False, "score": 0, "max_score": c3_max,
                "reason": "No output rows or no ground truth to compare",
            }

        # ── Criterion 4: Avg satisfaction scores correct (15 pts) ──
        c4_max = 15
        max_score += c4_max
        if output_rows and gt_flagged_ids:
            correct_sat = 0
            total_checked = 0
            for row in output_rows:
                tid = row.get("technician_id", "").strip()
                if tid in gt["tech_data"]:
                    total_checked += 1
                    try:
                        out_sat = float(row.get("avg_satisfaction", -1))
                        gt_sat = gt["tech_data"][tid]["avg_satisfaction"]
                        if abs(out_sat - gt_sat) < 0.05:
                            correct_sat += 1
                    except (ValueError, TypeError):
                        pass
            if total_checked > 0:
                frac = correct_sat / total_checked
                pts = round(c4_max * frac)
            else:
                pts = 0
            passed = pts == c4_max
            eval_criteria["satisfaction_scores"] = {
                "passed": passed, "score": pts, "max_score": c4_max,
            }
            if not passed:
                eval_criteria["satisfaction_scores"]["reason"] = (
                    f"{correct_sat}/{total_checked} satisfaction scores matched"
                )
            total_score += pts
        else:
            eval_criteria["satisfaction_scores"] = {
                "passed": False, "score": 0, "max_score": c4_max,
                "reason": "No output rows or no ground truth to compare",
            }

        # ── Criterion 5: Priority scores correct (15 pts) ──
        c5_max = 15
        max_score += c5_max
        if output_rows and gt_flagged_ids:
            correct_pri = 0
            total_checked = 0
            for row in output_rows:
                tid = row.get("technician_id", "").strip()
                if tid in gt["tech_data"]:
                    total_checked += 1
                    try:
                        out_pri = float(row.get("priority_score", -1))
                        gt_pri = gt["tech_data"][tid]["priority_score"]
                        if abs(out_pri - gt_pri) < 0.02:
                            correct_pri += 1
                    except (ValueError, TypeError):
                        pass
            if total_checked > 0:
                frac = correct_pri / total_checked
                pts = round(c5_max * frac)
            else:
                pts = 0
            passed = pts == c5_max
            eval_criteria["priority_scores"] = {
                "passed": passed, "score": pts, "max_score": c5_max,
            }
            if not passed:
                eval_criteria["priority_scores"]["reason"] = (
                    f"{correct_pri}/{total_checked} priority scores matched"
                )
            total_score += pts
        else:
            eval_criteria["priority_scores"] = {
                "passed": False, "score": 0, "max_score": c5_max,
                "reason": "No output rows or no ground truth to compare",
            }

        # ── Criterion 6: Correct sort order (10 pts) ──
        c6_max = 10
        max_score += c6_max
        if output_rows and len(output_rows) > 1:
            try:
                out_scores = [float(r.get("priority_score", 0)) for r in output_rows]
                is_desc = all(out_scores[i] >= out_scores[i + 1] - 0.001 for i in range(len(out_scores) - 1))
                if is_desc:
                    eval_criteria["sort_order"] = {
                        "passed": True, "score": c6_max, "max_score": c6_max,
                    }
                    total_score += c6_max
                else:
                    eval_criteria["sort_order"] = {
                        "passed": False, "score": 0, "max_score": c6_max,
                        "reason": "Output not sorted by priority_score descending",
                    }
            except (ValueError, TypeError):
                eval_criteria["sort_order"] = {
                    "passed": False, "score": 0, "max_score": c6_max,
                    "reason": "Could not parse priority_score values for sort check",
                }
        elif output_rows and len(output_rows) == 1:
            eval_criteria["sort_order"] = {
                "passed": True, "score": c6_max, "max_score": c6_max,
            }
            total_score += c6_max
        else:
            eval_criteria["sort_order"] = {
                "passed": False, "score": 0, "max_score": c6_max,
                "reason": "No output rows to check sort order",
            }

        # ── Criterion 7: Response summary (5 pts) ──
        c7_max = 5
        max_score += c7_max
        action_lower = action.lower()
        has_total = any(
            kw in action_lower
            for kw in ["total", "evaluated", "technician"]
        )
        has_flagged_count = str(len(gt_flagged_ids)) in action
        if has_total and has_flagged_count:
            eval_criteria["response_summary"] = {
                "passed": True, "score": c7_max, "max_score": c7_max,
            }
            total_score += c7_max
        else:
            pts = 0
            if has_total:
                pts += 2
            if has_flagged_count:
                pts += 3
            eval_criteria["response_summary"] = {
                "passed": False, "score": pts, "max_score": c7_max,
                "reason": "Response should mention total technicians evaluated and number flagged",
            }
            total_score += pts

        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    def _compute_ground_truth(self) -> dict:
        """Compute ground truth from DB and workspace files."""
        import yaml

        # Read config files
        with open(os.path.join(self.workspace, "scoring_config.yaml"), "r") as f:
            config = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "complexity_matrix.json"), "r") as f:
            complexity_matrix = json.load(f)

        # Read penalty adjustments
        penalties = {}
        penalty_path = os.path.join(self.workspace, "penalty_adjustments.txt")
        with open(penalty_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 2:
                    penalties[parts[0]] = float(parts[1])

        # Read all GPS files to get arrival times per appointment
        gps_arrivals = {}  # appointment_id -> arrival_timestamp
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("gps_log_week_") and fname.endswith(".csv"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row["event_type"] == "arrived":
                            gps_arrivals[row["appointment_id"]] = row["arrival_timestamp"]

        # Read DB
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # All technicians
        techs = [dict(r) for r in conn.execute("SELECT * FROM technicians ORDER BY id").fetchall()]

        # Build per-technician data
        tech_data = {}
        flagged_ids = []

        for tech in techs:
            tid = tech["id"]

            # Completed appointments
            appts = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM appointments WHERE technician_id = ? AND status = 'completed' ORDER BY id",
                    (tid,),
                ).fetchall()
            ]

            if not appts:
                continue

            # GPS-tracked appointments (those with GPS arrival data)
            tracked = [a for a in appts if a["id"] in gps_arrivals]
            if not tracked:
                continue

            # Surveys
            surveys = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM satisfaction_surveys WHERE technician_id = ? ORDER BY id",
                    (tid,),
                ).fetchall()
            ]
            if not surveys:
                continue

            # Late arrivals
            late_threshold = config["late_threshold_minutes"]
            late_count = 0
            from datetime import datetime as _dt
            for appt in tracked:
                arrival_str = gps_arrivals[appt["id"]]
                arrival_dt = _dt.fromisoformat(arrival_str)
                sched_dt = _dt.fromisoformat(
                    f"{appt['scheduled_date']} {appt['scheduled_start_time']}"
                )
                diff_minutes = (arrival_dt - sched_dt).total_seconds() / 60.0
                if diff_minutes > late_threshold:
                    late_count += 1

            late_rate = late_count / len(tracked)

            # Avg satisfaction
            avg_satisfaction = sum(s["overall_score"] for s in surveys) / len(surveys)

            # Avg complexity weight
            category_weights = []
            for appt in tracked:
                cat_id = appt["service_category_id"]
                cat_row = conn.execute(
                    "SELECT complexity_rating FROM service_categories WHERE id = ?",
                    (cat_id,),
                ).fetchone()
                if cat_row:
                    cr = str(cat_row["complexity_rating"])
                    weight = complexity_matrix.get(cr, 0.5)
                    category_weights.append(weight)

            avg_complexity = sum(category_weights) / len(category_weights) if category_weights else 0.5

            # Priority score
            w = config["priority_weights"]
            raw_score = (
                w["late_rate"] * late_rate
                + w["satisfaction"] * (1.0 - avg_satisfaction / 5.0)
                + w["complexity"] * avg_complexity
            )

            # Apply penalty multiplier
            penalty_mult = penalties.get(tid, 1.0)
            priority_score = raw_score * penalty_mult

            # Determine primary issue
            late_flag = late_rate > config["late_rate_flag_threshold"]
            sat_flag = avg_satisfaction < config["satisfaction_threshold"]
            if late_flag and sat_flag:
                primary_issue = "both"
            elif late_flag:
                primary_issue = "lateness"
            elif sat_flag:
                primary_issue = "satisfaction"
            else:
                primary_issue = "complexity"

            tech_data[tid] = {
                "technician_id": tid,
                "technician_name": tech["name"],
                "total_tracked_appointments": len(tracked),
                "late_count": late_count,
                "late_rate": round(late_rate, 4),
                "avg_satisfaction": round(avg_satisfaction, 2),
                "avg_complexity_weight": round(avg_complexity, 4),
                "priority_score": round(priority_score, 4),
                "primary_issue": primary_issue,
            }

            if priority_score > config["retraining_threshold"]:
                flagged_ids.append(tid)

        conn.close()

        return {
            "tech_data": tech_data,
            "flagged_tech_ids": flagged_ids,
            "config": config,
        }

    # ═══════════════════════════════════════════════════════
    # ── VERIFY ──
    # ═══════════════════════════════════════════════════════

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml

        # ── Step 1: Read workspace config files ──
        with open(os.path.join(self.workspace, "scoring_config.yaml"), "r") as f:
            config = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "complexity_matrix.json"), "r") as f:
            complexity_matrix = json.load(f)

        # Read penalty adjustments
        penalties = {}
        with open(os.path.join(self.workspace, "penalty_adjustments.txt"), "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 2:
                    penalties[parts[0]] = float(parts[1])

        # ── Step 2: Read all GPS log files to get arrival times ──
        gps_arrivals = {}  # appointment_id -> arrival_timestamp string
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("gps_log_week_") and fname.endswith(".csv"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row["event_type"] == "arrived":
                            gps_arrivals[row["appointment_id"]] = row["arrival_timestamp"]

        # ── Step 3: List all technicians via tool (paginated) ──
        all_techs = []
        page = 1
        tool_call_count = 0
        while True:
            result = json.loads(self.tools["list_technicians"](page=page, page_size=20)["content"][0]["text"])
            tool_call_count += 1
            all_techs.extend(result["technicians"])
            if not result["has_more"]:
                break
            page += 1

        # ── Step 4: For each technician, gather data via tools ──
        # Cache service categories to avoid redundant calls
        category_cache = {}
        results = []

        for tech in all_techs:
            tid = tech["id"]

            # Get completed appointments
            appt_result = json.loads(self.tools["get_technician_appointments"](technician_id=tid)["content"][0]["text"])
            tool_call_count += 1
            appts = appt_result["appointments"]

            if not appts:
                continue

            # Filter to GPS-tracked appointments
            tracked = [a for a in appts if a["id"] in gps_arrivals]
            if not tracked:
                continue

            # Get surveys
            survey_result = json.loads(self.tools["get_technician_surveys"](technician_id=tid))
            tool_call_count += 1
            surveys = survey_result["surveys"]

            if not surveys:
                continue

            # Compute late arrivals
            late_threshold = config["late_threshold_minutes"]
            late_count = 0
            from datetime import datetime as _dt
            for appt in tracked:
                arrival_str = gps_arrivals[appt["id"]]
                arrival_dt = _dt.fromisoformat(arrival_str)
                sched_dt = _dt.fromisoformat(
                    f"{appt['scheduled_date']} {appt['scheduled_start_time']}"
                )
                diff_minutes = (arrival_dt - sched_dt).total_seconds() / 60.0
                if diff_minutes > late_threshold:
                    late_count += 1

            late_rate = late_count / len(tracked)

            # Avg satisfaction (overall_score)
            avg_satisfaction = sum(s["overall_score"] for s in surveys) / len(surveys)

            # Avg complexity weight - need to look up each category
            complexity_weights = []
            for appt in tracked:
                cat_id = appt["service_category_id"]
                if cat_id not in category_cache:
                    cat_result = json.loads(self.tools["get_service_category"](category_id=cat_id))
                    tool_call_count += 1
                    category_cache[cat_id] = cat_result
                cat_info = category_cache[cat_id]
                cr = str(cat_info["complexity_rating"])
                weight = complexity_matrix.get(cr, 0.5)
                complexity_weights.append(weight)

            avg_complexity = sum(complexity_weights) / len(complexity_weights) if complexity_weights else 0.5

            # Compute priority score
            w = config["priority_weights"]
            raw_score = (
                w["late_rate"] * late_rate
                + w["satisfaction"] * (1.0 - avg_satisfaction / 5.0)
                + w["complexity"] * avg_complexity
            )

            # Apply penalty
            penalty_mult = penalties.get(tid, 1.0)
            priority_score = raw_score * penalty_mult

            # Primary issue
            late_flag = late_rate > config["late_rate_flag_threshold"]
            sat_flag = avg_satisfaction < config["satisfaction_threshold"]
            if late_flag and sat_flag:
                primary_issue = "both"
            elif late_flag:
                primary_issue = "lateness"
            elif sat_flag:
                primary_issue = "satisfaction"
            else:
                primary_issue = "complexity"

            results.append({
                "technician_id": tid,
                "technician_name": tech["name"],
                "total_tracked_appointments": len(tracked),
                "late_count": late_count,
                "late_rate": round(late_rate, 4),
                "avg_satisfaction": round(avg_satisfaction, 2),
                "avg_complexity_weight": round(avg_complexity, 4),
                "priority_score": round(priority_score, 4),
                "primary_issue": primary_issue,
            })

        # ── Step 5: Filter and sort ──
        retraining_threshold = config["retraining_threshold"]
        flagged = [r for r in results if r["priority_score"] > retraining_threshold]
        flagged.sort(key=lambda x: (-x["priority_score"], x["technician_id"]))

        # ── Step 6: Write output CSV ──
        csv_path = os.path.join(self.workspace, "retraining_priority.csv")
        fieldnames = [
            "technician_id", "technician_name", "total_tracked_appointments",
            "late_count", "late_rate", "avg_satisfaction", "avg_complexity_weight",
            "priority_score", "primary_issue",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in flagged:
                writer.writerow(row)

        # ── Step 7: Build action response ──
        total_evaluated = len(all_techs)
        num_flagged = len(flagged)

        top3 = flagged[:3]
        top3_summary = "; ".join(
            f"{r['technician_id']} ({r['technician_name']}) with priority score {r['priority_score']}"
            for r in top3
        )

        action = (
            f"Retraining analysis complete. Evaluated {total_evaluated} technicians total. "
            f"{num_flagged} technicians flagged for retraining (priority score above "
            f"{retraining_threshold} threshold). "
            f"Top priority technicians: {top3_summary}. "
            f"Full results written to retraining_priority.csv with columns: "
            f"technician_id, technician_name, total_tracked_appointments, late_count, "
            f"late_rate, avg_satisfaction, avg_complexity_weight, priority_score, primary_issue. "
            f"Sorted by priority_score descending with technician_id as tiebreaker. "
            f"Tool calls made: {tool_call_count}."
        )

        return self.step(action)
