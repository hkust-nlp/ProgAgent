"""Task environment for project schedule compliance monitoring.

The agent must cross-reference the baseline Gantt chart and configuration files
in the workspace with live project data (accessible only through tools) to
produce a variance report with critical-path impact assessments.
"""

from typing import Tuple, Dict, List, Any
import json
import os
import csv
import sqlite3
import re
import glob as globmod
from datetime import datetime

import yaml
import pandas as pd


# --- Decorator (keep unchanged) -------------------------------------------
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

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description="List project tasks with optional filtering. Returns task_id, task_code, task_name, phase, and status. Results are paginated.",
        parameters={
            "type": "object",
            "properties": {
                "phase": {
                    "type": "string",
                    "description": "Filter by phase: Foundation, Structural, MEP, or Finishing. Omit for all.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: completed, in_progress, not_started. Omit for all.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 20). Default 10.",
                },
            },
            "required": [],
        },
    )
    def list_tasks(self, phase: str = None, status: str = None,
                   page: int = 1, page_size: int = 10) -> dict:
        page_size = min(int(page_size), 20)
        page = max(1, int(page))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        sql = "SELECT task_id, task_code, task_name, phase, status FROM project_tasks WHERE 1=1"
        params = []
        if phase:
            sql += " AND phase = ?"
            params.append(phase)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY task_id"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start:start + page_size]
        return {
            "tasks": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get detailed actual progress for a single task by its task_id. Returns status, actual_start_date, actual_end_date, and percent_complete.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The numeric task_id.",
                },
            },
            "required": ["task_id"],
        },
    )
    def get_task_details(self, task_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM project_tasks WHERE task_id = ?", (int(task_id),)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"task_id {task_id} not found"}
        return dict(row)

    @tool(
        description="Get equipment telemetry summary for a task: total hours operated, total downtime hours, days used, and downtime reasons.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The numeric task_id.",
                },
            },
            "required": ["task_id"],
        },
    )
    def get_task_equipment_summary(self, task_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """SELECT equipment_id,
                      SUM(hours_operated) as total_hours,
                      SUM(downtime_hours) as total_downtime,
                      SUM(fuel_consumption_liters) as total_fuel,
                      COUNT(DISTINCT record_date) as days_used
               FROM equipment_telemetry
               WHERE task_id = ?
               GROUP BY equipment_id""",
            (int(task_id),),
        ).fetchall()
        # Downtime reasons
        reasons = conn.execute(
            """SELECT equipment_id, downtime_reason, COUNT(*) as occurrences
               FROM equipment_telemetry
               WHERE task_id = ? AND downtime_hours > 0
               GROUP BY equipment_id, downtime_reason""",
            (int(task_id),),
        ).fetchall()
        conn.close()
        return {
            "task_id": task_id,
            "equipment_summary": [
                {"equipment_id": r[0], "total_hours_operated": round(r[1], 2),
                 "total_downtime_hours": round(r[2], 2),
                 "total_fuel_liters": round(r[3], 2),
                 "days_used": r[4]}
                for r in rows
            ],
            "downtime_incidents": [
                {"equipment_id": r[0], "reason": r[1], "occurrences": r[2]}
                for r in reasons
            ],
        }

    @tool(
        description="Get labor cost summary for a task: total regular hours, overtime hours, and cost by worker role. Hourly rates are NOT included; they must be obtained from workspace files.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The numeric task_id.",
                },
            },
            "required": ["task_id"],
        },
    )
    def get_labor_summary(self, task_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """SELECT worker_id, role,
                      SUM(regular_hours) as total_regular,
                      SUM(overtime_hours) as total_overtime
               FROM labor_timecards
               WHERE task_id = ?
               GROUP BY worker_id, role""",
            (int(task_id),),
        ).fetchall()
        conn.close()
        return {
            "task_id": task_id,
            "labor_entries": [
                {"worker_id": r[0], "role": r[1],
                 "total_regular_hours": round(r[2], 2),
                 "total_overtime_hours": round(r[3], 2)}
                for r in rows
            ],
        }

    @tool(
        description="Get material procurement items for a task: material code/name, quantities ordered/received, unit cost, delivery dates, and status.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The numeric task_id.",
                },
            },
            "required": ["task_id"],
        },
    )
    def get_procurement_items(self, task_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM material_procurement WHERE task_id = ?",
            (int(task_id),),
        ).fetchall()
        conn.close()
        return {
            "task_id": task_id,
            "items": [dict(r) for r in rows],
        }

    @tool(
        description="Query weather delay logs within a date range. Returns records where delay_hours > 0, grouped by date with affected task IDs.",
        parameters={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD).",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD).",
                },
            },
            "required": ["start_date", "end_date"],
        },
    )
    def query_weather_delays(self, start_date: str, end_date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """SELECT record_date, weather_type, severity, delay_hours,
                      affected_task_ids
               FROM weather_delay_logs
               WHERE delay_hours > 0
                 AND record_date >= ? AND record_date <= ?
               ORDER BY record_date""",
            (start_date, end_date),
        ).fetchall()
        conn.close()
        results = []
        for r in rows:
            results.append({
                "record_date": r[0],
                "weather_type": r[1],
                "severity": r[2],
                "delay_hours": r[3],
                "affected_task_ids": json.loads(r[4]) if r[4] else [],
            })
        return {"delays": results, "count": len(results)}

    @tool(
        description="Get the list of predecessor task codes for a given task (from the baseline schedule stored in the workspace). Returns predecessor codes and whether the task is on the critical path.",
        parameters={
            "type": "object",
            "properties": {
                "task_code": {
                    "type": "string",
                    "description": "The task code (e.g., 'FND-001').",
                },
            },
            "required": ["task_code"],
        },
    )
    def get_task_predecessors(self, task_code: str) -> dict:
        gantt_path = os.path.join(self.workspace, "gantt_baseline.csv")
        df = pd.read_csv(gantt_path)
        row = df[df["task_code"] == task_code]
        if row.empty:
            return {"error": f"task_code {task_code} not found in baseline"}
        r = row.iloc[0]
        preds = [p.strip() for p in str(r["predecessors"]).split(";") if p.strip() and p.strip() != "nan"]
        return {
            "task_code": task_code,
            "predecessors": preds,
            "is_critical_path": str(r["is_critical_path"]).upper() == "TRUE",
            "total_float_days": int(r["total_float_days"]),
        }

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _compute_ground_truth(self) -> pd.DataFrame:
        """Compute the expected variance report from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        db_tasks = {
            r["task_code"]: dict(r)
            for r in conn.execute("SELECT * FROM project_tasks").fetchall()
        }

        # Read baseline
        gantt = pd.read_csv(os.path.join(self.workspace, "gantt_baseline.csv"))
        budget = pd.read_csv(os.path.join(self.workspace, "budget_allocation.csv"))
        with open(os.path.join(self.workspace, "variance_thresholds.json")) as f:
            thresholds = json.load(f)
        with open(os.path.join(self.workspace, "weather_impact_policy.json")) as f:
            wpolicy = json.load(f)
        with open(os.path.join(self.workspace, "worker_roster.yaml")) as f:
            roster = yaml.safe_load(f)

        reporting_date = datetime.strptime(thresholds["reporting_date"], "%Y-%m-%d")
        sev_weights = wpolicy["severity_delay_weight"]
        ot_mult = thresholds["overtime_multiplier"]
        sv_thresh = thresholds["schedule_variance"]
        cv_thresh = thresholds["cost_variance"]

        # Weather delays per task: sum(delay_hours * severity_weight) / 8
        weather_rows = conn.execute(
            "SELECT delay_hours, severity, affected_task_ids FROM weather_delay_logs WHERE delay_hours > 0"
        ).fetchall()
        weather_by_task = {}  # task_id -> weighted delay hours
        for wr in weather_rows:
            hrs = wr[0]
            sev = wr[1]
            weight = sev_weights.get(sev, 1.0)
            affected = json.loads(wr[2]) if wr[2] else []
            for tid in affected:
                weather_by_task[tid] = weather_by_task.get(tid, 0.0) + hrs * weight

        # Inspection risk flags: latest risk per task_code
        risk_flags = self._extract_risk_flags()

        # Labor cost per task
        labor_by_task = {}
        lrows = conn.execute(
            "SELECT task_id, worker_id, SUM(regular_hours), SUM(overtime_hours) FROM labor_timecards GROUP BY task_id, worker_id"
        ).fetchall()
        for lr in lrows:
            tid, wid, reg, ot = lr
            rate = roster.get(wid, {}).get("hourly_rate", 0)
            cost = reg * rate + ot * rate * ot_mult
            labor_by_task[tid] = labor_by_task.get(tid, 0.0) + cost

        # Material cost per task
        mat_by_task = {}
        mrows = conn.execute(
            "SELECT task_id, SUM(quantity_received * unit_cost) FROM material_procurement GROUP BY task_id"
        ).fetchall()
        for mr in mrows:
            mat_by_task[mr[0]] = mr[1] or 0.0

        # Equipment cost per task
        equip_reg_path = os.path.join(self.workspace, "equipment_registry.json")
        with open(equip_reg_path) as f:
            equip_reg = json.load(f)
        equip_by_task = {}
        erows = conn.execute(
            "SELECT task_id, equipment_id, COUNT(DISTINCT record_date) FROM equipment_telemetry GROUP BY task_id, equipment_id"
        ).fetchall()
        for er in erows:
            tid, eid, days_used = er
            daily_cost = equip_reg.get(eid, {}).get("daily_rental_cost", 0)
            equip_by_task[tid] = equip_by_task.get(tid, 0.0) + days_used * daily_cost

        conn.close()

        # Build report rows
        budget_map = {r["task_code"]: r for _, r in budget.iterrows()}
        report_rows = []
        for _, g in gantt.iterrows():
            tc = g["task_code"]
            db = db_tasks.get(tc, {})
            b = budget_map.get(tc, {})
            tid = db.get("task_id")

            ps = g["planned_start"]
            pe = g["planned_end"]
            a_start = db.get("actual_start_date") or ""
            a_end = db.get("actual_end_date") or ""
            status = db.get("status", "not_started")

            # Schedule variance
            planned_end_dt = datetime.strptime(pe, "%Y-%m-%d")
            if status == "completed" and a_end:
                actual_end_dt = datetime.strptime(a_end, "%Y-%m-%d")
                sv_days = (actual_end_dt - planned_end_dt).days
            elif status == "in_progress":
                sv_days = max(0, (reporting_date - planned_end_dt).days)
            elif status == "not_started":
                planned_start_dt = datetime.strptime(ps, "%Y-%m-%d")
                if planned_start_dt < reporting_date:
                    sv_days = (reporting_date - planned_end_dt).days
                else:
                    sv_days = 0
            else:
                sv_days = 0

            # Costs
            planned_cost = b.get("planned_total_cost", 0.0)
            actual_labor = labor_by_task.get(tid, 0.0)
            actual_mat = mat_by_task.get(tid, 0.0)
            actual_equip = equip_by_task.get(tid, 0.0)
            actual_cost = actual_labor + actual_mat + actual_equip
            cost_var = actual_cost - planned_cost
            cost_var_pct = (cost_var / planned_cost * 100) if planned_cost else 0.0

            is_cp = str(g["is_critical_path"]).upper() == "TRUE"
            wd_hours = weather_by_task.get(tid, 0.0)
            wd_days = round(wd_hours / 8, 2)

            risk = risk_flags.get(tc, "NONE")

            # Impact assessment
            impact = self._assess_impact(
                sv_days, cost_var_pct, is_cp, sv_thresh, cv_thresh
            )

            report_rows.append({
                "task_code": tc,
                "task_name": g["task_name"],
                "phase": g["phase"],
                "planned_start": ps,
                "planned_end": pe,
                "actual_start": a_start,
                "actual_end": a_end,
                "schedule_variance_days": sv_days,
                "planned_cost": round(planned_cost, 2),
                "actual_cost": round(actual_cost, 2),
                "cost_variance": round(cost_var, 2),
                "cost_variance_pct": round(cost_var_pct, 2),
                "is_critical_path": "TRUE" if is_cp else "FALSE",
                "weather_delay_days": wd_days,
                "risk_flag": risk,
                "impact_assessment": impact,
            })

        return pd.DataFrame(report_rows)

    def _extract_risk_flags(self) -> dict:
        """Parse all inspection reports; keep the LATEST risk_level per task_code."""
        risk_map = {}  # task_code -> (date_str, risk_level)
        ws = self.workspace
        for fname in sorted(os.listdir(ws)):
            if not fname.startswith("inspection_report_"):
                continue
            fpath = os.path.join(ws, fname)
            # Extract date from filename
            m = re.search(r"inspection_report_(\d{4}-\d{2}-\d{2})", fname)
            if not m:
                continue
            report_date = m.group(1)

            if fname.endswith(".json"):
                with open(fpath) as f:
                    data = json.load(f)
                for a in data.get("assessments", []):
                    tc = a["task_code"]
                    if tc not in risk_map or report_date > risk_map[tc][0]:
                        risk_map[tc] = (report_date, a["risk_level"])

            elif fname.endswith(".csv"):
                try:
                    df = pd.read_csv(fpath)
                    for _, row in df.iterrows():
                        tc = row["task_code"]
                        if tc not in risk_map or report_date > risk_map[tc][0]:
                            risk_map[tc] = (report_date, row["risk_level"])
                except Exception:
                    pass

            elif fname.endswith(".yaml"):
                with open(fpath) as f:
                    data = yaml.safe_load(f)
                for a in (data or {}).get("assessments", []):
                    tc = a["task_code"]
                    if tc not in risk_map or report_date > risk_map[tc][0]:
                        risk_map[tc] = (report_date, a["risk_level"])

            elif fname.endswith(".md"):
                with open(fpath) as f:
                    content = f.read()
                # Parse ### TASK_CODE - name blocks
                blocks = re.split(r"###\s+", content)
                for block in blocks[1:]:
                    code_m = re.match(r"(\S+)", block)
                    risk_m = re.search(r"Risk Level:\s*(\S+)", block)
                    if code_m and risk_m:
                        tc = code_m.group(1)
                        if tc not in risk_map or report_date > risk_map[tc][0]:
                            risk_map[tc] = (report_date, risk_m.group(1))

            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    for line in f:
                        tm = re.match(r"Task\s+(\S+)\s+\(.*?\):\s+Risk=(\S+)", line)
                        if tm:
                            tc = tm.group(1)
                            risk = tm.group(2).rstrip(",")
                            if tc not in risk_map or report_date > risk_map[tc][0]:
                                risk_map[tc] = (report_date, risk)

        return {tc: v[1] for tc, v in risk_map.items()}

    @staticmethod
    def _assess_impact(sv_days, cv_pct, is_cp, sv_t, cv_t):
        """Determine impact assessment level based on thresholds."""
        if is_cp and sv_days >= sv_t["critical_threshold_days"]:
            return "CRITICAL"
        if abs(cv_pct) >= cv_t["critical_threshold_pct"]:
            return "CRITICAL"
        if sv_days >= sv_t["significant_threshold_days"] or abs(cv_pct) >= cv_t["significant_threshold_pct"]:
            return "SIGNIFICANT"
        if sv_days >= sv_t["moderate_threshold_days"] or abs(cv_pct) >= cv_t["moderate_threshold_pct"]:
            return "MODERATE"
        if sv_days > 0 or cv_pct > 0:
            return "MINOR"
        return "NONE"

    # ------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        gt = self._compute_ground_truth()
        criteria = {}
        total_score = 0
        max_score = 0

        # --- C1: variance_report.csv exists with correct columns (10 pts) ---
        report_path = os.path.join(self.workspace, "variance_report.csv")
        expected_cols = [
            "task_code", "task_name", "phase", "planned_start", "planned_end",
            "actual_start", "actual_end", "schedule_variance_days",
            "planned_cost", "actual_cost", "cost_variance", "cost_variance_pct",
            "is_critical_path", "weather_delay_days", "risk_flag", "impact_assessment",
        ]
        c1_max = 10
        if os.path.exists(report_path):
            try:
                submitted = pd.read_csv(report_path)
                submitted_cols = [c.strip().lower() for c in submitted.columns]
                expected_lower = [c.lower() for c in expected_cols]
                missing = [c for c in expected_lower if c not in submitted_cols]
                if not missing:
                    c1_score = c1_max
                    c1_pass = True
                    c1_reason = ""
                else:
                    c1_score = max(0, c1_max - len(missing) * 2)
                    c1_pass = False
                    c1_reason = f"Missing columns: {missing}"
            except Exception as e:
                submitted = pd.DataFrame()
                c1_score = 0
                c1_pass = False
                c1_reason = f"Cannot parse CSV: {e}"
        else:
            submitted = pd.DataFrame()
            c1_score = 0
            c1_pass = False
            c1_reason = "variance_report.csv not found"

        criteria["report_structure"] = {
            "passed": c1_pass, "score": c1_score, "max_score": c1_max,
            "reason": c1_reason if not c1_pass else "",
        }
        total_score += c1_score
        max_score += c1_max

        # --- C2: Task coverage (15 pts) ---
        c2_max = 15
        if not submitted.empty and "task_code" in [c.lower() for c in submitted.columns]:
            col = [c for c in submitted.columns if c.strip().lower() == "task_code"][0]
            submitted_codes = set(submitted[col].astype(str).str.strip())
            gt_codes = set(gt["task_code"].astype(str))
            matched = submitted_codes & gt_codes
            coverage = len(matched) / len(gt_codes) if gt_codes else 0
            c2_score = round(c2_max * coverage, 1)
            c2_pass = coverage >= 0.95
            c2_reason = f"{len(matched)}/{len(gt_codes)} tasks" if not c2_pass else ""
        else:
            c2_score = 0
            c2_pass = False
            c2_reason = "No task_code column or empty report"
        criteria["task_coverage"] = {
            "passed": c2_pass, "score": c2_score, "max_score": c2_max,
            "reason": c2_reason if not c2_pass else "",
        }
        total_score += c2_score
        max_score += c2_max

        # Helper: merge submitted with GT on task_code
        merged = pd.DataFrame()
        if not submitted.empty:
            # Normalize column names
            submitted.columns = [c.strip().lower() for c in submitted.columns]
            try:
                merged = pd.merge(
                    gt, submitted, on="task_code", suffixes=("_gt", "_sub"), how="inner"
                )
            except Exception:
                pass

        # --- C3: Schedule variance accuracy (25 pts) ---
        c3_max = 25
        if not merged.empty and "schedule_variance_days_sub" in merged.columns:
            try:
                gt_sv = merged["schedule_variance_days_gt"].astype(float)
                sub_sv = merged["schedule_variance_days_sub"].astype(float)
                exact = (gt_sv == sub_sv).sum()
                close = ((gt_sv - sub_sv).abs() <= 1).sum()
                total_tasks = len(merged)
                accuracy = (exact * 1.0 + (close - exact) * 0.5) / total_tasks if total_tasks else 0
                c3_score = round(c3_max * accuracy, 1)
                c3_pass = accuracy >= 0.8
                c3_reason = f"Exact: {exact}/{total_tasks}, within-1: {close}/{total_tasks}" if not c3_pass else ""
            except Exception as e:
                c3_score = 0
                c3_pass = False
                c3_reason = str(e)
        else:
            c3_score = 0
            c3_pass = False
            c3_reason = "schedule_variance_days not found in submission"
        criteria["schedule_variance_accuracy"] = {
            "passed": c3_pass, "score": c3_score, "max_score": c3_max,
            "reason": c3_reason if not c3_pass else "",
        }
        total_score += c3_score
        max_score += c3_max

        # --- C4: Cost variance accuracy (20 pts) ---
        c4_max = 20
        if not merged.empty and "cost_variance_sub" in merged.columns:
            try:
                gt_cv = merged["cost_variance_gt"].astype(float)
                sub_cv = merged["cost_variance_sub"].astype(float)
                # Allow 5% relative tolerance or $500 absolute
                close_mask = ((gt_cv - sub_cv).abs() <= 500) | (
                    ((gt_cv - sub_cv).abs() / gt_cv.abs().clip(lower=1)) <= 0.05
                )
                frac = close_mask.sum() / len(merged) if len(merged) else 0
                c4_score = round(c4_max * frac, 1)
                c4_pass = frac >= 0.7
                c4_reason = f"Within tolerance: {close_mask.sum()}/{len(merged)}" if not c4_pass else ""
            except Exception as e:
                c4_score = 0
                c4_pass = False
                c4_reason = str(e)
        else:
            c4_score = 0
            c4_pass = False
            c4_reason = "cost_variance not found in submission"
        criteria["cost_variance_accuracy"] = {
            "passed": c4_pass, "score": c4_score, "max_score": c4_max,
            "reason": c4_reason if not c4_pass else "",
        }
        total_score += c4_score
        max_score += c4_max

        # --- C5: Critical path + weather delay (15 pts) ---
        c5_max = 15
        cp_score_part = 0
        wd_score_part = 0
        if not merged.empty:
            # Critical path
            if "is_critical_path_sub" in merged.columns:
                gt_cp = merged["is_critical_path_gt"].astype(str).str.upper()
                sub_cp = merged["is_critical_path_sub"].astype(str).str.upper()
                cp_match = (gt_cp == sub_cp).sum()
                cp_score_part = round(7.5 * cp_match / len(merged), 1) if len(merged) else 0

            # Weather delay days
            if "weather_delay_days_sub" in merged.columns:
                try:
                    gt_wd = merged["weather_delay_days_gt"].astype(float)
                    sub_wd = merged["weather_delay_days_sub"].astype(float)
                    close_wd = ((gt_wd - sub_wd).abs() <= 0.5).sum()
                    wd_score_part = round(7.5 * close_wd / len(merged), 1) if len(merged) else 0
                except Exception:
                    pass

        c5_score = round(cp_score_part + wd_score_part, 1)
        c5_pass = c5_score >= c5_max * 0.7
        c5_reason = "" if c5_pass else f"CP: {cp_score_part}/7.5, WD: {wd_score_part}/7.5"
        criteria["critical_path_and_weather"] = {
            "passed": c5_pass, "score": c5_score, "max_score": c5_max,
            "reason": c5_reason,
        }
        total_score += c5_score
        max_score += c5_max

        # --- C6: Impact assessment accuracy (15 pts) ---
        c6_max = 15
        if not merged.empty and "impact_assessment_sub" in merged.columns:
            gt_ia = merged["impact_assessment_gt"].astype(str).str.upper().str.strip()
            sub_ia = merged["impact_assessment_sub"].astype(str).str.upper().str.strip()
            exact_ia = (gt_ia == sub_ia).sum()
            frac_ia = exact_ia / len(merged) if len(merged) else 0
            c6_score = round(c6_max * frac_ia, 1)
            c6_pass = frac_ia >= 0.7
            c6_reason = f"Match: {exact_ia}/{len(merged)}" if not c6_pass else ""
        else:
            c6_score = 0
            c6_pass = False
            c6_reason = "impact_assessment not found"
        criteria["impact_assessment_accuracy"] = {
            "passed": c6_pass, "score": c6_score, "max_score": c6_max,
            "reason": c6_reason if not c6_pass else "",
        }
        total_score += c6_score
        max_score += c6_max

        # --- C7: Response summary (10 pts) ---
        c7_max = 10
        c7_score = 0
        # Check for key summary stats in action
        gt_behind = int((gt["schedule_variance_days"] > 0).sum())
        gt_overbudget = int((gt["cost_variance"] > 0).sum())
        gt_cp_impacted = int(
            ((gt["is_critical_path"] == "TRUE") & (gt["schedule_variance_days"] > 0)).sum()
        )
        gt_critical_count = int((gt["impact_assessment"] == "CRITICAL").sum())

        checks = 0
        if str(gt_behind) in action:
            checks += 1
        if str(gt_overbudget) in action:
            checks += 1
        if str(gt_cp_impacted) in action:
            checks += 1
        if str(gt_critical_count) in action:
            checks += 1

        c7_score = round(c7_max * checks / 4, 1)
        c7_pass = checks >= 3
        c7_reason = f"Found {checks}/4 summary stats" if not c7_pass else ""
        criteria["response_summary"] = {
            "passed": c7_pass, "score": c7_score, "max_score": c7_max,
            "reason": c7_reason if not c7_pass else "",
        }
        total_score += c7_score
        max_score += c7_max

        total_score = round(total_score, 1)
        reward = round(total_score / max_score, 4) if max_score else 0.0

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ------------------------------------------------------------------
    # verify
    # ------------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml as _yaml

        tool_calls = 0

        # 1. Read workspace config files
        ws = self.workspace
        gantt = pd.read_csv(os.path.join(ws, "gantt_baseline.csv"))
        budget = pd.read_csv(os.path.join(ws, "budget_allocation.csv"))
        with open(os.path.join(ws, "variance_thresholds.json")) as f:
            thresholds = json.load(f)
        with open(os.path.join(ws, "weather_impact_policy.json")) as f:
            wpolicy = json.load(f)
        with open(os.path.join(ws, "equipment_registry.json")) as f:
            equip_reg = json.load(f)
        with open(os.path.join(ws, "worker_roster.yaml")) as f:
            roster = _yaml.safe_load(f)

        reporting_date = datetime.strptime(thresholds["reporting_date"], "%Y-%m-%d")
        ot_mult = thresholds["overtime_multiplier"]
        sev_weights = wpolicy["severity_delay_weight"]
        sv_thresh = thresholds["schedule_variance"]
        cv_thresh = thresholds["cost_variance"]

        # 2. List all tasks via paginated tool calls
        all_task_ids = []
        page = 1
        while True:
            result = self.tools["list_tasks"](page=page, page_size=15)
            tool_calls += 1
            for t in result["tasks"]:
                all_task_ids.append((t["task_id"], t["task_code"]))
            if page >= result["total_pages"]:
                break
            page += 1

        # 3. Get details for each task
        task_details = {}
        for tid, tcode in all_task_ids:
            result = self.tools["get_task_details"](task_id=tid)
            tool_calls += 1
            task_details[tcode] = result

        # 4. Get labor summaries for all started tasks
        labor_costs = {}
        for tid, tcode in all_task_ids:
            d = task_details[tcode]
            if d["status"] == "not_started":
                continue
            result = self.tools["get_labor_summary"](task_id=tid)
            tool_calls += 1
            cost = 0.0
            for entry in result["labor_entries"]:
                wid = entry["worker_id"]
                rate = roster.get(wid, {}).get("hourly_rate", 0)
                cost += entry["total_regular_hours"] * rate
                cost += entry["total_overtime_hours"] * rate * ot_mult
            labor_costs[tcode] = cost

        # 5. Get procurement costs for ALL tasks (materials may be pre-ordered)
        mat_costs = {}
        for tid, tcode in all_task_ids:
            result = self.tools["get_procurement_items"](task_id=tid)
            tool_calls += 1
            cost = sum(
                item["quantity_received"] * item["unit_cost"]
                for item in result["items"]
            )
            mat_costs[tcode] = cost

        # 6. Get equipment summary for all started tasks
        equip_costs = {}
        for tid, tcode in all_task_ids:
            d = task_details[tcode]
            if d["status"] == "not_started":
                continue
            result = self.tools["get_task_equipment_summary"](task_id=tid)
            tool_calls += 1
            cost = 0.0
            for es in result["equipment_summary"]:
                eid = es["equipment_id"]
                daily_cost = equip_reg.get(eid, {}).get("daily_rental_cost", 0)
                days_used = es.get("days_used", 0)
                cost += days_used * daily_cost
            equip_costs[tcode] = cost

        # 7. Query weather delays for entire project
        result = self.tools["query_weather_delays"](
            start_date="2026-01-01", end_date="2026-12-31"
        )
        tool_calls += 1
        weather_by_task_id = {}
        for d in result["delays"]:
            weight = sev_weights.get(d["severity"], 1.0)
            for tid in d["affected_task_ids"]:
                weather_by_task_id[tid] = weather_by_task_id.get(tid, 0.0) + d["delay_hours"] * weight

        # 8. Extract risk flags from inspection reports
        risk_flags = self._extract_risk_flags()

        # 9. Build the report
        budget_map = {r["task_code"]: r for _, r in budget.iterrows()}
        tid_map = {tcode: tid for tid, tcode in all_task_ids}

        report_rows = []
        for _, g in gantt.iterrows():
            tc = g["task_code"]
            td = task_details.get(tc, {})
            b = budget_map.get(tc, {})
            tid = tid_map.get(tc)

            ps = g["planned_start"]
            pe = g["planned_end"]
            a_start = td.get("actual_start_date") or ""
            a_end = td.get("actual_end_date") or ""
            status = td.get("status", "not_started")

            planned_end_dt = datetime.strptime(pe, "%Y-%m-%d")
            if status == "completed" and a_end:
                actual_end_dt = datetime.strptime(a_end, "%Y-%m-%d")
                sv_days = (actual_end_dt - planned_end_dt).days
            elif status == "in_progress":
                sv_days = max(0, (reporting_date - planned_end_dt).days)
            elif status == "not_started":
                planned_start_dt = datetime.strptime(ps, "%Y-%m-%d")
                if planned_start_dt < reporting_date:
                    sv_days = (reporting_date - planned_end_dt).days
                else:
                    sv_days = 0
            else:
                sv_days = 0

            planned_cost = b.get("planned_total_cost", 0.0)
            actual_cost = labor_costs.get(tc, 0.0) + mat_costs.get(tc, 0.0) + equip_costs.get(tc, 0.0)
            cost_var = actual_cost - planned_cost
            cost_var_pct = (cost_var / planned_cost * 100) if planned_cost else 0.0

            is_cp = str(g["is_critical_path"]).upper() == "TRUE"
            wd_hours = weather_by_task_id.get(tid, 0.0)
            wd_days = round(wd_hours / 8, 2)

            risk = risk_flags.get(tc, "NONE")
            impact = self._assess_impact(sv_days, cost_var_pct, is_cp, sv_thresh, cv_thresh)

            report_rows.append({
                "task_code": tc,
                "task_name": g["task_name"],
                "phase": g["phase"],
                "planned_start": ps,
                "planned_end": pe,
                "actual_start": a_start,
                "actual_end": a_end,
                "schedule_variance_days": sv_days,
                "planned_cost": round(planned_cost, 2),
                "actual_cost": round(actual_cost, 2),
                "cost_variance": round(cost_var, 2),
                "cost_variance_pct": round(cost_var_pct, 2),
                "is_critical_path": "TRUE" if is_cp else "FALSE",
                "weather_delay_days": wd_days,
                "risk_flag": risk,
                "impact_assessment": impact,
            })

        # Write report
        report_df = pd.DataFrame(report_rows)
        report_df.to_csv(os.path.join(ws, "variance_report.csv"), index=False)

        # Build response summary
        behind = int((report_df["schedule_variance_days"] > 0).sum())
        overbudget = int((report_df["cost_variance"] > 0).sum())
        cp_impacted = int(
            ((report_df["is_critical_path"] == "TRUE") &
             (report_df["schedule_variance_days"] > 0)).sum()
        )
        critical_count = int((report_df["impact_assessment"] == "CRITICAL").sum())

        action = (
            f"Variance report has been generated and saved as variance_report.csv. "
            f"Summary: {behind} tasks are behind schedule, {overbudget} tasks are over budget, "
            f"{cp_impacted} critical-path tasks are impacted, and "
            f"{critical_count} tasks have CRITICAL impact assessment."
        )

        print(f"[verify] tool_calls={tool_calls}")
        return self.step(action)
