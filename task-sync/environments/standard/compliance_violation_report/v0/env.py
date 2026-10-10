"""
Environment for labor law compliance violation detection task.
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

    # ── Tool Methods ─────────────────────────────────────────────────────

    @tool(
        description="List employees with optional filters. Returns up to 20 results per page.",
        parameters={
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": "Filter by department name (e.g. 'Assembly', 'Welding', 'Packaging', 'QualityControl', 'Maintenance')"
                },
                "union_code": {
                    "type": "string",
                    "description": "Filter by union code (e.g. 'UAW-Local-101')"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1. Default is 1."
                },
            },
            "required": [],
        },
    )
    def list_employees(self, department: str = None, union_code: str = None, page: int = 1):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM employees WHERE is_active = 1"
        params = []
        if department:
            query += " AND department = ?"
            params.append(department)
        if union_code:
            query += " AND union_code = ?"
            params.append(union_code)
        query += " ORDER BY employee_id"
        page_size = 20
        offset = (max(1, page) - 1) * page_size
        query += f" LIMIT {page_size} OFFSET {offset}"
        rows = conn.execute(query, params).fetchall()
        total_q = "SELECT COUNT(*) FROM employees WHERE is_active = 1"
        tp = []
        if department:
            total_q += " AND department = ?"
            tp.append(department)
        if union_code:
            total_q += " AND union_code = ?"
            tp.append(union_code)
        total = conn.execute(total_q, tp).fetchone()[0]
        conn.close()
        return _envelope({
            "employees": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        })

    @tool(
        description="Get detailed information for a single employee by their ID.",
        parameters={
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "The employee ID, e.g. 'EMP-0001'"
                },
            },
            "required": ["employee_id"],
        },
    )
    def get_employee(self, employee_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ?", (employee_id,)
        ).fetchone()
        conn.close()
        if row:
            return json.dumps(dict(row), ensure_ascii=False, default=str)
        return json.dumps({"error": f"Employee {employee_id} not found"}, ensure_ascii=False, default=str)

    @tool(
        description="Get time punch records for a specific employee on a given date, or all punches for a date. Returns clock-in/out and shift type.",
        parameters={
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "Employee ID to filter by"
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (20 results per page). Default 1."
                },
            },
            "required": [],
        },
    )
    def get_time_punches(self, employee_id: str = None, date: str = None, page: int = 1):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM time_punches WHERE 1=1"
        params = []
        if employee_id:
            query += " AND employee_id = ?"
            params.append(employee_id)
        if date:
            query += " AND punch_date = ?"
            params.append(date)
        count_q = query.replace("SELECT *", "SELECT COUNT(*)")
        total = conn.execute(count_q, params).fetchone()[0]
        query += " ORDER BY punch_date, clock_in"
        page_size = 20
        offset = (max(1, page) - 1) * page_size
        query += f" LIMIT {page_size} OFFSET {offset}"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return _envelope({
            "punches": [dict(r) for r in rows],
            "page": page,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        })

    @tool(
        description="Get break records for a specific punch or employee. Returns break type (meal/rest), start and end times.",
        parameters={
            "type": "object",
            "properties": {
                "punch_id": {
                    "type": "string",
                    "description": "Punch ID to get breaks for"
                },
                "employee_id": {
                    "type": "string",
                    "description": "Employee ID to get all breaks for"
                },
            },
            "required": [],
        },
    )
    def get_break_records(self, punch_id: str = None, employee_id: str = None):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM break_records WHERE 1=1"
        params = []
        if punch_id:
            query += " AND punch_id = ?"
            params.append(punch_id)
        if employee_id:
            query += " AND employee_id = ?"
            params.append(employee_id)
        query += " ORDER BY break_start"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return json.dumps({"breaks": [dict(r) for r in rows], "count": len(rows)}, ensure_ascii=False, default=str)

    @tool(
        description="Get training certification records for an employee. Shows skill, completion date, and expiry date.",
        parameters={
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "Employee ID"
                },
            },
            "required": ["employee_id"],
        },
    )
    def get_training_records(self, employee_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM training_records WHERE employee_id = ? ORDER BY skill_name",
            (employee_id,),
        ).fetchall()
        conn.close()
        return json.dumps({"records": [dict(r) for r in rows], "count": len(rows)}, ensure_ascii=False, default=str)

    @tool(
        description="Get weekly hour totals for employees. Returns total hours worked in the week of 2025-03-10 to 2025-03-16.",
        parameters={
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "Employee ID. If omitted returns all employees."
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (20 per page). Default 1."
                },
            },
            "required": [],
        },
    )
    def get_weekly_hours(self, employee_id: str = None, page: int = 1):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = """
            SELECT employee_id, punch_date, clock_in, clock_out
            FROM time_punches
            WHERE punch_date BETWEEN '2025-03-10' AND '2025-03-16'
        """
        params = []
        if employee_id:
            query += " AND employee_id = ?"
            params.append(employee_id)
        query += " ORDER BY employee_id, punch_date"
        rows = conn.execute(query, params).fetchall()
        conn.close()

        # Compute per-employee weekly totals
        emp_hours = {}
        emp_daily = {}
        for r in rows:
            eid = r["employee_id"]
            in_h, in_m = map(int, r["clock_in"].split(":"))
            out_h, out_m = map(int, r["clock_out"].split(":"))
            start = in_h * 60 + in_m
            end = out_h * 60 + out_m
            if end <= start:
                end += 24 * 60
            hours = (end - start) / 60.0
            emp_hours[eid] = emp_hours.get(eid, 0) + hours
            if eid not in emp_daily:
                emp_daily[eid] = {}
            emp_daily[eid][r["punch_date"]] = round(hours, 2)

        results = [
            {"employee_id": eid, "weekly_hours": round(emp_hours[eid], 2),
             "daily_breakdown": emp_daily[eid]}
            for eid in sorted(emp_hours.keys())
        ]
        page_size = 20
        total = len(results)
        offset = (max(1, page) - 1) * page_size
        page_results = results[offset:offset + page_size]
        return {
            "results": page_results,
            "page": page,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get all departments and a count of active employees in each.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def get_department_summary(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT department, COUNT(*) as count FROM employees WHERE is_active=1 GROUP BY department ORDER BY department"
        ).fetchall()
        conn.close()
        return _envelope({"departments": [{"department": r[0], "employee_count": r[1]} for r in rows]})

    # ── Evaluation ───────────────────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute all violations as ground truth for evaluation."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load config files from workspace
        with open(os.path.join(self.workspace, "union_contract_rules.json")) as f:
            union_rules = json.load(f)
        with open(os.path.join(self.workspace, "overtime_policy.json")) as f:
            overtime_rules = json.load(f)
        with open(os.path.join(self.workspace, "energy_thresholds.yaml")) as f:
            energy_thresholds = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "severity_config.yaml")) as f:
            severity_config = yaml.safe_load(f)

        # Load training requirements
        training_reqs = {}
        with open(os.path.join(self.workspace, "training_requirements.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                dept = row["department"]
                if dept not in training_reqs:
                    training_reqs[dept] = []
                training_reqs[dept].append(row["required_skill"])

        # Get all employees
        employees = {
            r["employee_id"]: dict(r)
            for r in conn.execute("SELECT * FROM employees WHERE is_active=1").fetchall()
        }

        # Get all punches for the week
        punches = conn.execute(
            "SELECT * FROM time_punches WHERE punch_date BETWEEN '2025-03-10' AND '2025-03-16' ORDER BY employee_id, punch_date"
        ).fetchall()

        violations = []
        sev_map = severity_config["violation_severity"]

        # ── Break violations ─────────────────────────────────────────
        for punch in punches:
            punch = dict(punch)
            emp = employees.get(punch["employee_id"])
            if not emp:
                continue
            union_code = emp["union_code"]
            rules = union_rules.get(union_code)
            if not rules:
                continue

            in_h, in_m = map(int, punch["clock_in"].split(":"))
            out_h, out_m = map(int, punch["clock_out"].split(":"))
            start_min = in_h * 60 + in_m
            end_min = out_h * 60 + out_m
            if end_min <= start_min:
                end_min += 24 * 60
            shift_hours = (end_min - start_min) / 60.0

            # Get breaks for this punch
            breaks = conn.execute(
                "SELECT * FROM break_records WHERE punch_id = ?",
                (punch["punch_id"],)
            ).fetchall()
            breaks = [dict(b) for b in breaks]

            meal_breaks = [b for b in breaks if b["break_type"] == "meal"]
            rest_breaks = [b for b in breaks if b["break_type"] == "rest"]

            # Check meal break
            if shift_hours >= rules["meal_break_after_hours"]:
                if not meal_breaks:
                    violations.append({
                        "employee_id": punch["employee_id"],
                        "employee_name": emp["name"],
                        "violation_type": "break_meal_missing",
                        "violation_date": punch["punch_date"],
                        "severity": sev_map["break_meal_missing"]["level"],
                        "points": sev_map["break_meal_missing"]["points"],
                        "details": f"No meal break taken during {shift_hours:.1f}h shift (required after {rules['meal_break_after_hours']}h per {union_code})",
                    })
                else:
                    for mb in meal_breaks:
                        bs_h, bs_m = map(int, mb["break_start"].split(":"))
                        be_h, be_m = map(int, mb["break_end"].split(":"))
                        bs_min = bs_h * 60 + bs_m
                        be_min = be_h * 60 + be_m
                        if be_min <= bs_min:
                            be_min += 24 * 60
                        actual_min = be_min - bs_min
                        if actual_min < rules["meal_break_minutes"]:
                            violations.append({
                                "employee_id": punch["employee_id"],
                                "employee_name": emp["name"],
                                "violation_type": "break_meal_short",
                                "violation_date": punch["punch_date"],
                                "severity": sev_map["break_meal_short"]["level"],
                                "points": sev_map["break_meal_short"]["points"],
                                "details": f"Meal break only {actual_min}min (required {rules['meal_break_minutes']}min per {union_code})",
                            })

            # Check rest breaks
            n_rest_expected = max(0, int(shift_hours / rules["rest_break_interval_hours"]) - 1)
            n_rest_actual = len(rest_breaks)
            if n_rest_actual < n_rest_expected:
                missing = n_rest_expected - n_rest_actual
                violations.append({
                    "employee_id": punch["employee_id"],
                    "employee_name": emp["name"],
                    "violation_type": "break_rest_missing",
                    "violation_date": punch["punch_date"],
                    "severity": sev_map["break_rest_missing"]["level"],
                    "points": sev_map["break_rest_missing"]["points"],
                    "details": f"Missing {missing} rest break(s); had {n_rest_actual} of {n_rest_expected} expected (every {rules['rest_break_interval_hours']}h per {union_code})",
                })

        # ── Overtime violations ──────────────────────────────────────
        daily_max = overtime_rules["daily_max_hours"]
        weekly_max = overtime_rules["weekly_max_hours"]
        weekend_thresh = overtime_rules["weekend_flag_threshold_hours"]

        emp_weekly_hours = {}
        for punch in punches:
            punch = dict(punch)
            eid = punch["employee_id"]
            in_h, in_m = map(int, punch["clock_in"].split(":"))
            out_h, out_m = map(int, punch["clock_out"].split(":"))
            start = in_h * 60 + in_m
            end = out_h * 60 + out_m
            if end <= start:
                end += 24 * 60
            hours = (end - start) / 60.0

            emp_weekly_hours.setdefault(eid, 0)
            emp_weekly_hours[eid] += hours

            emp = employees.get(eid)
            if not emp:
                continue

            # Daily overtime
            if hours > daily_max:
                violations.append({
                    "employee_id": eid,
                    "employee_name": emp["name"],
                    "violation_type": "overtime_daily",
                    "violation_date": punch["punch_date"],
                    "severity": sev_map["overtime_daily"]["level"],
                    "points": sev_map["overtime_daily"]["points"],
                    "details": f"Worked {hours:.1f}h exceeding daily max of {daily_max}h",
                })

            # Weekend long shift
            from datetime import datetime as dt
            pdate = dt.strptime(punch["punch_date"], "%Y-%m-%d")
            if pdate.weekday() >= 5 and hours > weekend_thresh:
                violations.append({
                    "employee_id": eid,
                    "employee_name": emp["name"],
                    "violation_type": "weekend_long_shift",
                    "violation_date": punch["punch_date"],
                    "severity": sev_map["weekend_long_shift"]["level"],
                    "points": sev_map["weekend_long_shift"]["points"],
                    "details": f"Weekend shift of {hours:.1f}h exceeds threshold of {weekend_thresh}h",
                })

        # Weekly overtime
        for eid, total_h in emp_weekly_hours.items():
            emp = employees.get(eid)
            if not emp:
                continue
            if total_h > weekly_max:
                violations.append({
                    "employee_id": eid,
                    "employee_name": emp["name"],
                    "violation_type": "overtime_weekly",
                    "violation_date": "2025-03-10/2025-03-16",
                    "severity": sev_map["overtime_weekly"]["level"],
                    "points": sev_map["overtime_weekly"]["points"],
                    "details": f"Weekly total {total_h:.1f}h exceeds max of {weekly_max}h",
                })

        # ── Training violations ──────────────────────────────────────
        week_start_str = "2025-03-10"
        for eid, emp in employees.items():
            dept = emp["department"]
            required_skills = training_reqs.get(dept, [])
            if not required_skills:
                continue

            # Check if employee worked during the week
            emp_punches = [dict(p) for p in conn.execute(
                "SELECT * FROM time_punches WHERE employee_id = ? AND punch_date BETWEEN '2025-03-10' AND '2025-03-16'",
                (eid,)
            ).fetchall()]
            if not emp_punches:
                continue

            # Get training records
            tr_rows = conn.execute(
                "SELECT * FROM training_records WHERE employee_id = ?", (eid,)
            ).fetchall()
            skill_expiry = {}
            for tr in tr_rows:
                tr = dict(tr)
                skill_expiry[tr["skill_name"]] = tr["expiry_date"]

            for skill in required_skills:
                if skill not in skill_expiry:
                    # No record at all for a required skill
                    violations.append({
                        "employee_id": eid,
                        "employee_name": emp["name"],
                        "violation_type": "training_expired",
                        "violation_date": "2025-03-10/2025-03-16",
                        "severity": sev_map["training_expired"]["level"],
                        "points": sev_map["training_expired"]["points"],
                        "details": f"No certification record for required skill '{skill}' (dept: {dept})",
                    })
                elif skill_expiry[skill] < week_start_str:
                    violations.append({
                        "employee_id": eid,
                        "employee_name": emp["name"],
                        "violation_type": "training_expired",
                        "violation_date": "2025-03-10/2025-03-16",
                        "severity": sev_map["training_expired"]["level"],
                        "points": sev_map["training_expired"]["points"],
                        "details": f"Certification for '{skill}' expired on {skill_expiry[skill]} (dept: {dept})",
                    })

        # ── Energy violations ────────────────────────────────────────
        # Read all energy log CSVs from workspace
        energy_entries = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("machine_energy_log_") and fname.endswith(".csv"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        energy_entries.append(row)

        for entry in energy_entries:
            machine_id = entry["machine_id"]
            prefix = machine_id.split("-")[0]
            threshold = energy_thresholds.get(prefix)
            if not threshold:
                continue
            duration_h = float(entry["duration_hours"])
            kwh = float(entry["energy_kwh"])
            max_allowed = threshold["max_kwh_per_hour"] * duration_h
            if kwh > max_allowed:
                emp = employees.get(entry["employee_id"])
                if not emp:
                    continue
                violations.append({
                    "employee_id": entry["employee_id"],
                    "employee_name": emp["name"],
                    "violation_type": "energy_exceeded",
                    "violation_date": entry["date"],
                    "severity": sev_map["energy_exceeded"]["level"],
                    "points": sev_map["energy_exceeded"]["points"],
                    "details": f"Machine {machine_id} used {kwh:.2f} kWh in {duration_h:.2f}h (max {max_allowed:.2f} kWh)",
                })

        conn.close()

        # Sort violations: by severity (critical > major > minor), then employee_id, then date
        sev_order = {"critical": 0, "major": 1, "minor": 2}
        violations.sort(key=lambda v: (sev_order.get(v["severity"], 9), v["employee_id"], v["violation_date"]))

        return violations

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        ground_truth = self._compute_ground_truth()
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: Report file exists with correct name (10 pts) ───
        report_path = os.path.join(self.workspace, "weekly_violation_report.csv")
        c1_score = 0
        c1_max = 10
        if os.path.exists(report_path):
            c1_score = 10
        eval_criteria["report_file_exists"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": "" if c1_score == c1_max else "weekly_violation_report.csv not found in workspace",
        }
        total_score += c1_score
        max_score += c1_max

        # ── Criterion 2: Report has correct columns (10 pts) ─────────────
        c2_score = 0
        c2_max = 10
        expected_cols = {"employee_id", "employee_name", "violation_type",
                         "violation_date", "severity", "details"}
        report_rows = []
        c2_reason = ""
        if os.path.exists(report_path):
            try:
                with open(report_path) as f:
                    reader = csv.DictReader(f)
                    report_rows = list(reader)
                    actual_cols = set(reader.fieldnames) if reader.fieldnames else set()
                if expected_cols.issubset(actual_cols):
                    c2_score = 10
                else:
                    missing = expected_cols - actual_cols
                    c2_reason = f"Missing columns: {missing}"
            except Exception as e:
                c2_reason = f"Error reading CSV: {e}"
        else:
            c2_reason = "Report file not found"
        eval_criteria["report_columns"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": c2_reason,
        }
        total_score += c2_score
        max_score += c2_max

        # ── Criterion 3: Violation count accuracy (20 pts) ───────────────
        c3_score = 0
        c3_max = 20
        gt_count = len(ground_truth)
        report_count = len(report_rows)
        if gt_count > 0:
            accuracy = 1.0 - abs(gt_count - report_count) / gt_count
            accuracy = max(0, accuracy)
            c3_score = int(round(accuracy * c3_max))
        elif report_count == 0:
            c3_score = c3_max
        c3_reason = f"Expected {gt_count} violations, got {report_count}" if c3_score < c3_max else ""
        eval_criteria["violation_count"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": c3_reason,
        }
        total_score += c3_score
        max_score += c3_max

        # ── Criterion 4: Violation type coverage (20 pts) ────────────────
        c4_score = 0
        c4_max = 20
        gt_types = set(v["violation_type"] for v in ground_truth)
        report_types = set(r.get("violation_type", "") for r in report_rows)
        if gt_types:
            coverage = len(gt_types & report_types) / len(gt_types)
            c4_score = int(round(coverage * c4_max))
        elif not report_types:
            c4_score = c4_max
        c4_reason = ""
        if c4_score < c4_max:
            missing_types = gt_types - report_types
            c4_reason = f"Missing violation types: {missing_types}"
        eval_criteria["violation_type_coverage"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": c4_reason,
        }
        total_score += c4_score
        max_score += c4_max

        # ── Criterion 5: Specific violation matching (25 pts) ────────────
        c5_score = 0
        c5_max = 25
        # Match by (employee_id, violation_type, violation_date)
        gt_keys = set()
        for v in ground_truth:
            gt_keys.add((v["employee_id"], v["violation_type"], v["violation_date"]))
        report_keys = set()
        for r in report_rows:
            report_keys.add((r.get("employee_id", ""), r.get("violation_type", ""),
                             r.get("violation_date", "")))
        if gt_keys:
            matched = len(gt_keys & report_keys)
            precision = matched / len(report_keys) if report_keys else 0
            recall = matched / len(gt_keys)
            if precision + recall > 0:
                f1 = 2 * precision * recall / (precision + recall)
            else:
                f1 = 0
            c5_score = int(round(f1 * c5_max))
        elif not report_keys:
            c5_score = c5_max
        c5_reason = ""
        if c5_score < c5_max:
            c5_reason = f"Matched {len(gt_keys & report_keys)} of {len(gt_keys)} expected violations (F1-based scoring)"
        eval_criteria["violation_matching"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": c5_reason,
        }
        total_score += c5_score
        max_score += c5_max

        # ── Criterion 6: Response summary accuracy (15 pts) ──────────────
        c6_score = 0
        c6_max = 15
        # Check that the response mentions the correct total violation count
        # and has a breakdown by type
        action_lower = action.lower() if action else ""

        checks_passed = 0
        total_checks = 4

        # Check total count mentioned
        if str(gt_count) in (action or ""):
            checks_passed += 1

        # Check at least 3 violation types mentioned in response
        type_mentions = 0
        for vt in gt_types:
            if vt.replace("_", " ") in action_lower or vt in (action or ""):
                type_mentions += 1
        if type_mentions >= min(3, len(gt_types)):
            checks_passed += 1

        # Check per-type counts in response
        gt_type_counts = {}
        for v in ground_truth:
            gt_type_counts[v["violation_type"]] = gt_type_counts.get(v["violation_type"], 0) + 1
        type_count_matches = 0
        for vtype, count in gt_type_counts.items():
            if str(count) in (action or ""):
                type_count_matches += 1
        if type_count_matches >= min(2, len(gt_type_counts)):
            checks_passed += 1

        # Check that top-5 employees by violation count are mentioned in the response
        from collections import Counter as _Counter
        emp_violation_counts = _Counter(v["employee_id"] for v in ground_truth)
        top5_eids = [eid for eid, _ in emp_violation_counts.most_common(5)]
        top5_mentions = sum(1 for eid in top5_eids if eid in (action or ""))
        if top5_mentions >= min(3, len(top5_eids)):
            checks_passed += 1

        c6_score = int(round(checks_passed / total_checks * c6_max))
        c6_reason = ""
        if c6_score < c6_max:
            c6_reason = f"Response summary checks: {checks_passed}/{total_checks} passed"
        eval_criteria["response_summary"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": c6_reason,
        }
        total_score += c6_score
        max_score += c6_max

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as _csv
        import json as _json

        import yaml as _yaml

        # Step 1: Read workspace config files
        ws = self.workspace
        with open(os.path.join(ws, "union_contract_rules.json")) as f:
            union_rules = _json.load(f)
        with open(os.path.join(ws, "overtime_policy.json")) as f:
            overtime_rules = _json.load(f)
        with open(os.path.join(ws, "energy_thresholds.yaml")) as f:
            energy_thresholds = _yaml.safe_load(f)
        with open(os.path.join(ws, "severity_config.yaml")) as f:
            severity_config = _yaml.safe_load(f)
        with open(os.path.join(ws, "training_requirements.csv")) as f:
            reader = _csv.DictReader(f)
            training_reqs = {}
            for row in reader:
                training_reqs.setdefault(row["department"], []).append(row["required_skill"])

        sev_map = severity_config["violation_severity"]
        tool_call_count = 0

        # Step 2: Get all employees (paginated)
        all_employees = []
        page = 1
        while True:
            result = json.loads(self.tools["list_employees"](page=page)["content"][0]["text"])
            tool_call_count += 1
            all_employees.extend(result["employees"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 3: Get department summary
        dept_summary = json.loads(self.tools["get_department_summary"]()["content"][0]["text"])
        tool_call_count += 1

        violations = []

        # Step 4: For each employee, get time punches and check break/overtime violations
        emp_weekly_hours = {}

        for emp in all_employees:
            eid = emp["employee_id"]
            union_code = emp["union_code"]
            rules = union_rules.get(union_code, {})

            # Get all punches for this employee (paginated)
            all_punches = []
            page = 1
            while True:
                result = json.loads(self.tools["get_time_punches"](employee_id=eid, page=page)["content"][0]["text"])
                tool_call_count += 1
                all_punches.extend(result["punches"])
                if page >= result["total_pages"]:
                    break
                page += 1

            # Filter to the analysis week
            week_punches = [p for p in all_punches
                           if "2025-03-10" <= p["punch_date"] <= "2025-03-16"]

            weekly_total = 0.0

            for punch in week_punches:
                in_h, in_m = map(int, punch["clock_in"].split(":"))
                out_h, out_m = map(int, punch["clock_out"].split(":"))
                start = in_h * 60 + in_m
                end = out_h * 60 + out_m
                if end <= start:
                    end += 24 * 60
                shift_hours = (end - start) / 60.0
                weekly_total += shift_hours

                # Check breaks for this punch
                brk_result = json.loads(self.tools["get_break_records"](punch_id=punch["punch_id"]))
                tool_call_count += 1
                brk_list = brk_result["breaks"]
                meal_breaks = [b for b in brk_list if b["break_type"] == "meal"]
                rest_breaks = [b for b in brk_list if b["break_type"] == "rest"]

                # Meal break check
                if shift_hours >= rules.get("meal_break_after_hours", 999):
                    if not meal_breaks:
                        violations.append({
                            "employee_id": eid,
                            "employee_name": emp["name"],
                            "violation_type": "break_meal_missing",
                            "violation_date": punch["punch_date"],
                            "severity": sev_map["break_meal_missing"]["level"],
                            "details": f"No meal break taken during {shift_hours:.1f}h shift (required after {rules['meal_break_after_hours']}h per {union_code})",
                        })
                    else:
                        for mb in meal_breaks:
                            bs_h, bs_m = map(int, mb["break_start"].split(":"))
                            be_h, be_m = map(int, mb["break_end"].split(":"))
                            bs_min = bs_h * 60 + bs_m
                            be_min = be_h * 60 + be_m
                            if be_min <= bs_min:
                                be_min += 24 * 60
                            actual = be_min - bs_min
                            if actual < rules["meal_break_minutes"]:
                                violations.append({
                                    "employee_id": eid,
                                    "employee_name": emp["name"],
                                    "violation_type": "break_meal_short",
                                    "violation_date": punch["punch_date"],
                                    "severity": sev_map["break_meal_short"]["level"],
                                    "details": f"Meal break only {actual}min (required {rules['meal_break_minutes']}min per {union_code})",
                                })

                # Rest break check
                n_rest_expected = max(0, int(shift_hours / rules.get("rest_break_interval_hours", 999)) - 1)
                n_rest_actual = len(rest_breaks)
                if n_rest_actual < n_rest_expected:
                    missing = n_rest_expected - n_rest_actual
                    violations.append({
                        "employee_id": eid,
                        "employee_name": emp["name"],
                        "violation_type": "break_rest_missing",
                        "violation_date": punch["punch_date"],
                        "severity": sev_map["break_rest_missing"]["level"],
                        "details": f"Missing {missing} rest break(s); had {n_rest_actual} of {n_rest_expected} expected (every {rules['rest_break_interval_hours']}h per {union_code})",
                    })

                # Daily overtime
                daily_max = overtime_rules["daily_max_hours"]
                if shift_hours > daily_max:
                    violations.append({
                        "employee_id": eid,
                        "employee_name": emp["name"],
                        "violation_type": "overtime_daily",
                        "violation_date": punch["punch_date"],
                        "severity": sev_map["overtime_daily"]["level"],
                        "details": f"Worked {shift_hours:.1f}h exceeding daily max of {daily_max}h",
                    })

                # Weekend long shift
                from datetime import datetime as dt
                pdate = dt.strptime(punch["punch_date"], "%Y-%m-%d")
                weekend_thresh = overtime_rules["weekend_flag_threshold_hours"]
                if pdate.weekday() >= 5 and shift_hours > weekend_thresh:
                    violations.append({
                        "employee_id": eid,
                        "employee_name": emp["name"],
                        "violation_type": "weekend_long_shift",
                        "violation_date": punch["punch_date"],
                        "severity": sev_map["weekend_long_shift"]["level"],
                        "details": f"Weekend shift of {shift_hours:.1f}h exceeds threshold of {weekend_thresh}h",
                    })

            emp_weekly_hours[eid] = weekly_total

            # Weekly overtime check
            weekly_max = overtime_rules["weekly_max_hours"]
            if weekly_total > weekly_max:
                violations.append({
                    "employee_id": eid,
                    "employee_name": emp["name"],
                    "violation_type": "overtime_weekly",
                    "violation_date": "2025-03-10/2025-03-16",
                    "severity": sev_map["overtime_weekly"]["level"],
                    "details": f"Weekly total {weekly_total:.1f}h exceeds max of {weekly_max}h",
                })

            # Training violations
            dept = emp["department"]
            required_skills = training_reqs.get(dept, [])
            if required_skills and week_punches:
                tr_result = json.loads(self.tools["get_training_records"](employee_id=eid))
                tool_call_count += 1
                skill_expiry = {}
                for tr in tr_result["records"]:
                    skill_expiry[tr["skill_name"]] = tr["expiry_date"]

                for skill in required_skills:
                    if skill not in skill_expiry:
                        violations.append({
                            "employee_id": eid,
                            "employee_name": emp["name"],
                            "violation_type": "training_expired",
                            "violation_date": "2025-03-10/2025-03-16",
                            "severity": sev_map["training_expired"]["level"],
                            "details": f"No certification record for required skill '{skill}' (dept: {dept})",
                        })
                    elif skill_expiry[skill] < "2025-03-10":
                        violations.append({
                            "employee_id": eid,
                            "employee_name": emp["name"],
                            "violation_type": "training_expired",
                            "violation_date": "2025-03-10/2025-03-16",
                            "severity": sev_map["training_expired"]["level"],
                            "details": f"Certification for '{skill}' expired on {skill_expiry[skill]} (dept: {dept})",
                        })

        # Step 5: Energy violations from workspace files
        energy_entries = []
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("machine_energy_log_") and fname.endswith(".csv"):
                with open(os.path.join(ws, fname)) as f:
                    reader = _csv.DictReader(f)
                    for row in reader:
                        energy_entries.append(row)

        emp_lookup = {e["employee_id"]: e for e in all_employees}
        for entry in energy_entries:
            machine_id = entry["machine_id"]
            prefix = machine_id.split("-")[0]
            threshold = energy_thresholds.get(prefix)
            if not threshold:
                continue
            duration_h = float(entry["duration_hours"])
            kwh = float(entry["energy_kwh"])
            max_allowed = threshold["max_kwh_per_hour"] * duration_h
            if kwh > max_allowed:
                emp = emp_lookup.get(entry["employee_id"])
                if not emp:
                    continue
                violations.append({
                    "employee_id": entry["employee_id"],
                    "employee_name": emp["name"],
                    "violation_type": "energy_exceeded",
                    "violation_date": entry["date"],
                    "severity": sev_map["energy_exceeded"]["level"],
                    "details": f"Machine {machine_id} used {kwh} kWh in {duration_h}h (max {max_allowed:.2f} kWh)",
                })

        # Sort violations
        sev_order = {"critical": 0, "major": 1, "minor": 2}
        violations.sort(key=lambda v: (sev_order.get(v["severity"], 9), v["employee_id"], v["violation_date"]))

        # Step 6: Write the report CSV
        report_path = os.path.join(ws, "weekly_violation_report.csv")
        with open(report_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=[
                "employee_id", "employee_name", "violation_type",
                "violation_date", "severity", "details"
            ])
            writer.writeheader()
            for v in violations:
                writer.writerow({
                    "employee_id": v["employee_id"],
                    "employee_name": v["employee_name"],
                    "violation_type": v["violation_type"],
                    "violation_date": v["violation_date"],
                    "severity": v["severity"],
                    "details": v["details"],
                })

        # Step 7: Build summary action string
        type_counts = {}
        for v in violations:
            type_counts[v["violation_type"]] = type_counts.get(v["violation_type"], 0) + 1

        # Top offenders
        emp_violation_counts = {}
        for v in violations:
            emp_violation_counts[v["employee_id"]] = emp_violation_counts.get(v["employee_id"], 0) + 1
        top_offenders = sorted(emp_violation_counts.items(), key=lambda x: -x[1])[:5]

        action_lines = [
            f"Weekly Violation Report Summary for 2025-03-10 to 2025-03-16",
            f"Total violations found: {len(violations)}",
            "",
            "Breakdown by violation type:",
        ]
        for vtype, count in sorted(type_counts.items()):
            action_lines.append(f"  {vtype}: {count}")

        action_lines.append("")
        action_lines.append("Top offenders:")
        for eid, count in top_offenders:
            emp = emp_lookup.get(eid, {})
            action_lines.append(f"  {eid} ({emp.get('name', 'Unknown')}): {count} violations")

        action_lines.append("")
        action_lines.append(f"Report saved to weekly_violation_report.csv with {len(violations)} rows.")
        action_lines.append(f"Tool calls made: {tool_call_count}")

        action = "\n".join(action_lines)
        return self.step(action)
