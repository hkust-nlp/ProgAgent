import csv
import json
import math
import os
import sqlite3
import glob as glob_mod
from datetime import datetime, timedelta
from typing import Tuple, Dict, List, Any

import yaml


# --- Decorator ---
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

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description=(
            "List feature flags with optional filtering. Returns paginated results "
            "including each flag's id, name, service, enabled status, rollout "
            "percentage, and the date of its most recent configuration change (if any)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Filter by service name (exact match). Omit to list all services.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Default 20.",
                },
            },
            "required": [],
        },
    )
    def list_feature_flags(self, service: str = None, page: int = 1, page_size: int = 20):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        base = """
            SELECT f.flag_id, f.flag_name, f.service, f.is_enabled,
                   f.rollout_percentage,
                   MAX(ch.change_date) AS last_change_date
            FROM feature_flags f
            LEFT JOIN flag_changes ch ON f.flag_id = ch.flag_id
        """
        params: list = []
        if service:
            base += " WHERE f.service = ? "
            params.append(service)
        base += " GROUP BY f.flag_id ORDER BY f.flag_id"

        c.execute(base, params)
        all_rows = c.fetchall()
        conn.close()

        total = len(all_rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = all_rows[start:end]

        return {
            "page": page,
            "page_size": page_size,
            "total_flags": total,
            "total_pages": math.ceil(total / page_size) if page_size else 1,
            "flags": [
                {
                    "flag_id": r["flag_id"],
                    "flag_name": r["flag_name"],
                    "service": r["service"],
                    "is_enabled": bool(r["is_enabled"]),
                    "rollout_percentage": r["rollout_percentage"],
                    "last_change_date": r["last_change_date"],
                }
                for r in page_rows
            ],
        }

    @tool(
        description=(
            "Get the full configuration change history for a specific feature flag, "
            "ordered chronologically. Returns change date, field changed, old/new "
            "values, who made the change, and the stated reason."
        ),
        parameters={
            "type": "object",
            "properties": {
                "flag_id": {
                    "type": "integer",
                    "description": "The ID of the feature flag.",
                },
            },
            "required": ["flag_id"],
        },
    )
    def get_flag_change_history(self, flag_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT change_id, change_date, field_changed, old_value, new_value, "
            "changed_by, reason FROM flag_changes WHERE flag_id = ? ORDER BY change_date",
            (flag_id,),
        )
        rows = c.fetchall()
        conn.close()
        return {"flag_id": flag_id, "changes": [dict(r) for r in rows]}

    @tool(
        description=(
            "Compare key metrics for a feature flag before and after a specified "
            "change date. Returns error count, average user satisfaction, session "
            "count, and support-ticket count for both the before and after windows. "
            "The window size is configurable."
        ),
        parameters={
            "type": "object",
            "properties": {
                "flag_id": {
                    "type": "integer",
                    "description": "The ID of the feature flag.",
                },
                "change_date": {
                    "type": "string",
                    "description": "Reference date for comparison in YYYY-MM-DD or YYYY-MM-DD HH:MM:SS format.",
                },
                "window_days": {
                    "type": "integer",
                    "description": "Number of days for each comparison window. Default 14.",
                },
            },
            "required": ["flag_id", "change_date"],
        },
    )
    def get_flag_metric_comparison(self, flag_id: int, change_date: str, window_days: int = 14):
        # Parse change_date
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                cd = datetime.strptime(change_date, fmt)
                break
            except ValueError:
                continue
        else:
            return {"error": f"Invalid date format: {change_date}"}

        before_start = (cd - timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M:%S")
        before_end = cd.strftime("%Y-%m-%d %H:%M:%S")
        after_start = cd.strftime("%Y-%m-%d %H:%M:%S")
        after_end = (cd + timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M:%S")

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        def _error_count(start, end):
            c.execute(
                "SELECT COUNT(*) FROM error_logs "
                "WHERE associated_flag_id = ? AND timestamp >= ? AND timestamp < ?",
                (flag_id, start, end),
            )
            return c.fetchone()[0]

        def _session_stats(start, end):
            c.execute(
                "SELECT AVG(satisfaction_score), COUNT(*) FROM user_sessions "
                "WHERE (',' || exposed_flags || ',') LIKE ? "
                "AND start_time >= ? AND start_time < ?",
                (f"%,{flag_id},%", start, end),
            )
            row = c.fetchone()
            avg_sat = round(row[0], 2) if row[0] is not None else None
            return avg_sat, row[1]

        def _ticket_count(start, end):
            c.execute(
                "SELECT COUNT(*) FROM support_tickets "
                "WHERE related_flag_id = ? AND created_date >= ? AND created_date < ?",
                (flag_id, start, end),
            )
            return c.fetchone()[0]

        b_err = _error_count(before_start, before_end)
        a_err = _error_count(after_start, after_end)
        b_sat, b_sess = _session_stats(before_start, before_end)
        a_sat, a_sess = _session_stats(after_start, after_end)
        b_tix = _ticket_count(before_start, before_end)
        a_tix = _ticket_count(after_start, after_end)
        conn.close()

        return {
            "flag_id": flag_id,
            "change_date": change_date,
            "window_days": window_days,
            "before": {
                "error_count": b_err,
                "avg_satisfaction": b_sat,
                "session_count": b_sess,
                "ticket_count": b_tix,
            },
            "after": {
                "error_count": a_err,
                "avg_satisfaction": a_sat,
                "session_count": a_sess,
                "ticket_count": a_tix,
            },
        }

    @tool(
        description=(
            "Retrieve individual error log records associated with a feature flag. "
            "Supports filtering by severity and pagination."
        ),
        parameters={
            "type": "object",
            "properties": {
                "flag_id": {
                    "type": "integer",
                    "description": "The feature flag ID to look up errors for.",
                },
                "severity": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "description": "Filter by severity level.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return. Default 20.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip. Default 0.",
                },
            },
            "required": ["flag_id"],
        },
    )
    def get_error_details(self, flag_id: int, severity: str = None,
                          limit: int = 20, offset: int = 0):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        q = ("SELECT error_id, timestamp, service, error_type, severity, message "
             "FROM error_logs WHERE associated_flag_id = ?")
        params: list = [flag_id]
        if severity:
            q += " AND severity = ?"
            params.append(severity)
        q += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        c.execute(q, params)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"flag_id": flag_id, "errors": rows}

    @tool(
        description=(
            "Search and browse support tickets. Can filter by related feature flag "
            "and/or priority. Paginated."
        ),
        parameters={
            "type": "object",
            "properties": {
                "flag_id": {
                    "type": "integer",
                    "description": "Filter tickets by related feature flag ID.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["P1", "P2", "P3", "P4"],
                    "description": "Filter by ticket priority.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return. Default 20.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip. Default 0.",
                },
            },
            "required": [],
        },
    )
    def search_support_tickets(self, flag_id: int = None, priority: str = None,
                               limit: int = 20, offset: int = 0):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        q = "SELECT ticket_id, created_date, subject, category, priority, status, resolution_time_hours FROM support_tickets WHERE 1=1"
        params: list = []
        if flag_id is not None:
            q += " AND related_flag_id = ?"
            params.append(flag_id)
        if priority:
            q += " AND priority = ?"
            params.append(priority)
        q += " ORDER BY created_date DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        c.execute(q, params)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {"tickets": rows}

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _compute_ground_truth(self):
        """Compute the expected rollback report from raw data."""
        # Load policy
        policy_path = os.path.join(self.workspace, "rollback_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)
        window_days = policy["analysis"]["window_days"]
        lookback = policy["analysis"]["recent_change_lookback_days"]
        ref_date = datetime.strptime(policy["analysis"]["reference_date"], "%Y-%m-%d")
        cutoff = ref_date - timedelta(days=lookback)
        rb_thresh = policy["thresholds"]["rollback"]
        mon_thresh = policy["thresholds"]["monitor"]

        # Load service config
        svc_path = os.path.join(self.workspace, "service_config.json")
        with open(svc_path) as f:
            svc_cfg = json.load(f)

        # Load flag details for rollback_complexity
        complexity_map = {}
        fd_dir = os.path.join(self.workspace, "flag_details")
        if os.path.isdir(fd_dir):
            for fn in sorted(os.listdir(fd_dir)):
                if fn.endswith(".json"):
                    with open(os.path.join(fd_dir, fn)) as f:
                        for item in json.load(f):
                            complexity_map[item["flag_id"]] = item["rollback_complexity"]

        # Load incident mentions
        incident_flags = set()
        inc_dir = os.path.join(self.workspace, "incident_notes")
        if os.path.isdir(inc_dir):
            for fn in sorted(os.listdir(inc_dir)):
                fp = os.path.join(inc_dir, fn)
                with open(fp) as f:
                    text = f.read()
                # Extract flag IDs mentioned as "(ID: <num>)"
                import re
                for m in re.finditer(r"\(ID:\s*(\d+)\)", text):
                    incident_flags.add(int(m.group(1)))

        # Load session logs for response-time data
        session_rt = []  # list of (session_id, exposed_flags_str, response_time_ms, timestamp_str)
        sl_dir = os.path.join(self.workspace, "session_logs")
        if os.path.isdir(sl_dir):
            for fn in sorted(os.listdir(sl_dir)):
                if fn.endswith(".csv"):
                    with open(os.path.join(sl_dir, fn)) as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            session_rt.append((
                                row["exposed_flags"],
                                int(row["response_time_ms"]),
                                row["timestamp"],
                            ))

        # Query DB for flags with recent changes
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Get all flags
        c.execute("SELECT * FROM feature_flags ORDER BY flag_id")
        flags = {r["flag_id"]: dict(r) for r in c.fetchall()}

        # Get latest change date per flag
        c.execute(
            "SELECT flag_id, MAX(change_date) as lcd FROM flag_changes GROUP BY flag_id"
        )
        lcd_map = {}
        for r in c.fetchall():
            lcd_map[r["flag_id"]] = r["lcd"]

        # Identify recently changed flags
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        recently_changed = {}
        for fid, lcd in lcd_map.items():
            if lcd >= cutoff_str:
                recently_changed[fid] = lcd

        results = []
        for fid in sorted(recently_changed.keys()):
            lcd = recently_changed[fid]
            # Parse lcd
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    cd = datetime.strptime(lcd, fmt)
                    break
                except ValueError:
                    continue

            before_start = (cd - timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M:%S")
            before_end = cd.strftime("%Y-%m-%d %H:%M:%S")
            after_start = cd.strftime("%Y-%m-%d %H:%M:%S")
            after_end = (cd + timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M:%S")

            # Error counts
            c.execute(
                "SELECT COUNT(*) FROM error_logs WHERE associated_flag_id=? AND timestamp>=? AND timestamp<?",
                (fid, before_start, before_end),
            )
            err_before = c.fetchone()[0]
            c.execute(
                "SELECT COUNT(*) FROM error_logs WHERE associated_flag_id=? AND timestamp>=? AND timestamp<?",
                (fid, after_start, after_end),
            )
            err_after = c.fetchone()[0]

            # Satisfaction
            like_pat = f"%,{fid},%"
            c.execute(
                "SELECT AVG(satisfaction_score) FROM user_sessions "
                "WHERE (',' || exposed_flags || ',') LIKE ? AND start_time>=? AND start_time<?",
                (like_pat, before_start, before_end),
            )
            sat_before = c.fetchone()[0]
            c.execute(
                "SELECT AVG(satisfaction_score) FROM user_sessions "
                "WHERE (',' || exposed_flags || ',') LIKE ? AND start_time>=? AND start_time<?",
                (like_pat, after_start, after_end),
            )
            sat_after = c.fetchone()[0]

            # Tickets
            c.execute(
                "SELECT COUNT(*) FROM support_tickets WHERE related_flag_id=? AND created_date>=? AND created_date<?",
                (fid, before_start, before_end),
            )
            tix_before = c.fetchone()[0]
            c.execute(
                "SELECT COUNT(*) FROM support_tickets WHERE related_flag_id=? AND created_date>=? AND created_date<?",
                (fid, after_start, after_end),
            )
            tix_after = c.fetchone()[0]

            # Compute metrics
            if err_before > 0:
                error_increase_pct = round(((err_after - err_before) / err_before) * 100, 1)
            else:
                error_increase_pct = round(float(err_after) * 100, 1) if err_after > 0 else 0.0

            if sat_before is not None and sat_after is not None:
                satisfaction_change = round(sat_after - sat_before, 2)
            else:
                satisfaction_change = 0.0

            if tix_before > 0:
                ticket_ratio = round(tix_after / tix_before, 2)
            else:
                ticket_ratio = round(float(tix_after), 2) if tix_after > 0 else 0.0

            # Response time from workspace session logs
            rt_before_vals = []
            rt_after_vals = []
            for exposed_str, rt_ms, ts_str in session_rt:
                flag_ids_in_session = [int(x) for x in exposed_str.split(",") if x.strip()]
                if fid not in flag_ids_in_session:
                    continue
                if before_start <= ts_str < before_end:
                    rt_before_vals.append(rt_ms)
                elif after_start <= ts_str < after_end:
                    rt_after_vals.append(rt_ms)

            if rt_before_vals and rt_after_vals:
                avg_rt_before = sum(rt_before_vals) / len(rt_before_vals)
                avg_rt_after = sum(rt_after_vals) / len(rt_after_vals)
                if avg_rt_before > 0:
                    rt_change_pct = round(((avg_rt_after - avg_rt_before) / avg_rt_before) * 100, 1)
                else:
                    rt_change_pct = 0.0
            else:
                rt_change_pct = 0.0

            flag_info = flags[fid]
            svc = flag_info["service"]
            criticality = svc_cfg.get(svc, {}).get("criticality", "unknown")
            complexity = complexity_map.get(fid, "unknown")
            mentioned = fid in incident_flags

            # Recommendation
            recommendation, primary_reason = self._classify(
                error_increase_pct, satisfaction_change, ticket_ratio,
                rb_thresh, mon_thresh,
            )

            results.append({
                "flag_id": fid,
                "flag_name": flag_info["flag_name"],
                "service": svc,
                "criticality": criticality,
                "error_increase_pct": error_increase_pct,
                "satisfaction_change": satisfaction_change,
                "ticket_ratio": ticket_ratio,
                "avg_response_time_change_pct": rt_change_pct,
                "rollback_complexity": complexity,
                "mentioned_in_incidents": "yes" if mentioned else "no",
                "recommendation": recommendation,
                "primary_reason": primary_reason,
            })

        conn.close()

        # Sort: ROLLBACK > MONITOR > KEEP, then by flag_id
        order = {"ROLLBACK": 0, "MONITOR": 1, "KEEP": 2}
        results.sort(key=lambda r: (order.get(r["recommendation"], 9), r["flag_id"]))

        return results

    @staticmethod
    def _classify(error_increase_pct, satisfaction_change, ticket_ratio,
                  rb_thresh, mon_thresh):
        """Return (recommendation, primary_reason)."""
        # Check rollback thresholds (in order: error, satisfaction, ticket)
        rb_reasons = []
        if error_increase_pct > rb_thresh["error_increase_pct"]:
            rb_reasons.append("error_increase")
        if satisfaction_change < -rb_thresh["satisfaction_drop"]:
            rb_reasons.append("satisfaction_drop")
        if ticket_ratio > rb_thresh["ticket_spike_multiplier"]:
            rb_reasons.append("ticket_spike")
        if rb_reasons:
            return "ROLLBACK", rb_reasons[0]

        # Check monitor thresholds
        mon_reasons = []
        if error_increase_pct > mon_thresh["error_increase_pct"]:
            mon_reasons.append("error_increase")
        if satisfaction_change < -mon_thresh["satisfaction_drop"]:
            mon_reasons.append("satisfaction_drop")
        if ticket_ratio > mon_thresh["ticket_spike_multiplier"]:
            mon_reasons.append("ticket_spike")
        if mon_reasons:
            return "MONITOR", mon_reasons[0]

        return "KEEP", "within_limits"

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
        ground_truth = self._compute_ground_truth()
        gt_map = {r["flag_id"]: r for r in ground_truth}
        expected_ids = set(gt_map.keys())

        criteria = {}
        total_score = 0
        max_score = 0

        # --- 1. Report exists and has correct columns (10 pts) ---
        report_path = os.path.join(self.workspace, "rollback_report.csv")
        expected_cols = [
            "flag_id", "flag_name", "service", "criticality",
            "error_increase_pct", "satisfaction_change", "ticket_ratio",
            "avg_response_time_change_pct", "rollback_complexity",
            "mentioned_in_incidents", "recommendation", "primary_reason",
        ]
        c1_score = 0
        c1_max = 10
        agent_rows = []
        if os.path.isfile(report_path):
            try:
                with open(report_path, newline="") as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    if all(ec in cols for ec in expected_cols):
                        c1_score = 10
                    else:
                        missing = [ec for ec in expected_cols if ec not in cols]
                        c1_score = max(0, 10 - 2 * len(missing))
                    agent_rows = list(reader)
            except Exception:
                c1_score = 0
        criteria["report_format"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
        }
        if c1_score < c1_max:
            criteria["report_format"]["reason"] = "Missing or malformed rollback_report.csv"
        total_score += c1_score
        max_score += c1_max

        # Build agent map
        agent_map = {}
        for row in agent_rows:
            try:
                fid = int(row.get("flag_id", -1))
                agent_map[fid] = row
            except (ValueError, TypeError):
                pass

        agent_ids = set(agent_map.keys())

        # --- 2. Correct set of flags (10 pts) ---
        c2_max = 10
        if expected_ids:
            correct = len(expected_ids & agent_ids)
            extra = len(agent_ids - expected_ids)
            penalty = min(correct, extra)
            c2_score = round(c2_max * max(0, correct - penalty) / len(expected_ids))
        else:
            c2_score = c2_max if not agent_ids else 0
        criteria["correct_flags"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
        }
        if c2_score < c2_max:
            criteria["correct_flags"]["reason"] = (
                f"Expected {len(expected_ids)} flags, got {len(agent_ids)}. "
                f"Missing: {sorted(expected_ids - agent_ids)[:5]}, "
                f"Extra: {sorted(agent_ids - expected_ids)[:5]}"
            )
        total_score += c2_score
        max_score += c2_max

        # Helper for per-flag metric comparison
        def _metric_accuracy(metric_key, tolerance, max_pts, cast_fn=float):
            correct = 0
            checked = 0
            for fid in expected_ids:
                gt_val = gt_map[fid][metric_key]
                if fid in agent_map:
                    try:
                        ag_val = cast_fn(agent_map[fid].get(metric_key, ""))
                        if abs(ag_val - gt_val) <= tolerance:
                            correct += 1
                    except (ValueError, TypeError):
                        pass
                checked += 1
            score = round(max_pts * correct / max(1, checked))
            return score, max_pts, correct, checked

        # --- 3. Error increase accuracy (15 pts) ---
        s3, m3, cor3, chk3 = _metric_accuracy("error_increase_pct", 5.0, 15)
        criteria["error_metrics"] = {
            "passed": s3 == m3, "score": s3, "max_score": m3,
        }
        if s3 < m3:
            criteria["error_metrics"]["reason"] = f"{cor3}/{chk3} flags within tolerance"
        total_score += s3
        max_score += m3

        # --- 4. Satisfaction change accuracy (15 pts) ---
        s4, m4, cor4, chk4 = _metric_accuracy("satisfaction_change", 0.1, 15)
        criteria["satisfaction_metrics"] = {
            "passed": s4 == m4, "score": s4, "max_score": m4,
        }
        if s4 < m4:
            criteria["satisfaction_metrics"]["reason"] = f"{cor4}/{chk4} flags within tolerance"
        total_score += s4
        max_score += m4

        # --- 5. Ticket ratio accuracy (10 pts) ---
        s5, m5, cor5, chk5 = _metric_accuracy("ticket_ratio", 0.2, 10)
        criteria["ticket_metrics"] = {
            "passed": s5 == m5, "score": s5, "max_score": m5,
        }
        if s5 < m5:
            criteria["ticket_metrics"]["reason"] = f"{cor5}/{chk5} flags within tolerance"
        total_score += s5
        max_score += m5

        # --- 6. Response time accuracy (10 pts) ---
        s6, m6, cor6, chk6 = _metric_accuracy("avg_response_time_change_pct", 5.0, 10)
        criteria["response_time_metrics"] = {
            "passed": s6 == m6, "score": s6, "max_score": m6,
        }
        if s6 < m6:
            criteria["response_time_metrics"]["reason"] = f"{cor6}/{chk6} flags within tolerance"
        total_score += s6
        max_score += m6

        # --- 7. Recommendation correctness (15 pts) ---
        c7_max = 15
        correct_rec = 0
        for fid in expected_ids:
            if fid in agent_map:
                if agent_map[fid].get("recommendation", "").strip().upper() == gt_map[fid]["recommendation"]:
                    correct_rec += 1
        c7_score = round(c7_max * correct_rec / max(1, len(expected_ids)))
        criteria["recommendations"] = {
            "passed": c7_score == c7_max, "score": c7_score, "max_score": c7_max,
        }
        if c7_score < c7_max:
            criteria["recommendations"]["reason"] = f"{correct_rec}/{len(expected_ids)} correct"
        total_score += c7_score
        max_score += c7_max

        # --- 8. Sort order (5 pts) ---
        c8_max = 5
        rec_order = {"ROLLBACK": 0, "MONITOR": 1, "KEEP": 2}
        agent_sort_keys = []
        for row in agent_rows:
            try:
                fid = int(row.get("flag_id", 9999))
                rec = row.get("recommendation", "KEEP").strip().upper()
                agent_sort_keys.append((rec_order.get(rec, 9), fid))
            except (ValueError, TypeError):
                agent_sort_keys.append((9, 9999))
        is_sorted = agent_sort_keys == sorted(agent_sort_keys)
        c8_score = c8_max if is_sorted else 0
        criteria["sort_order"] = {
            "passed": is_sorted, "score": c8_score, "max_score": c8_max,
        }
        if not is_sorted:
            criteria["sort_order"]["reason"] = "Report not sorted by recommendation then flag_id"
        total_score += c8_score
        max_score += c8_max

        # --- 9. Action summary (10 pts) ---
        c9_max = 10
        c9_score = 0
        n_rollback = sum(1 for r in ground_truth if r["recommendation"] == "ROLLBACK")
        n_monitor = sum(1 for r in ground_truth if r["recommendation"] == "MONITOR")
        n_keep = sum(1 for r in ground_truth if r["recommendation"] == "KEEP")
        if action:
            # Check if action mentions total analyzed
            if str(len(ground_truth)) in action:
                c9_score += 3
            # Check rollback count
            if str(n_rollback) in action:
                c9_score += 4
            # Check at least one rollback flag name mentioned
            rollback_names = [r["flag_name"] for r in ground_truth if r["recommendation"] == "ROLLBACK"]
            if any(name in action for name in rollback_names):
                c9_score += 3
        criteria["action_summary"] = {
            "passed": c9_score == c9_max, "score": c9_score, "max_score": c9_max,
        }
        if c9_score < c9_max:
            criteria["action_summary"]["reason"] = "Action text missing expected summary elements"
        total_score += c9_score
        max_score += c9_max

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
        import re

        # 1. Read rollback policy
        with open(os.path.join(self.workspace, "rollback_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        window_days = policy["analysis"]["window_days"]
        lookback = policy["analysis"]["recent_change_lookback_days"]
        ref_date_str = policy["analysis"]["reference_date"]
        ref_date = datetime.strptime(ref_date_str, "%Y-%m-%d")
        cutoff = ref_date - timedelta(days=lookback)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        rb_thresh = policy["thresholds"]["rollback"]
        mon_thresh = policy["thresholds"]["monitor"]

        # 2. Read service config
        with open(os.path.join(self.workspace, "service_config.json")) as f:
            svc_cfg = json.load(f)

        # 3. Read flag details
        complexity_map = {}
        fd_dir = os.path.join(self.workspace, "flag_details")
        for fn in sorted(os.listdir(fd_dir)):
            if fn.endswith(".json"):
                with open(os.path.join(fd_dir, fn)) as f:
                    for item in json.load(f):
                        complexity_map[item["flag_id"]] = item["rollback_complexity"]

        # 4. Read session logs
        session_rt = []
        sl_dir = os.path.join(self.workspace, "session_logs")
        for fn in sorted(os.listdir(sl_dir)):
            if fn.endswith(".csv"):
                with open(os.path.join(sl_dir, fn)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        session_rt.append((
                            row["exposed_flags"],
                            int(row["response_time_ms"]),
                            row["timestamp"],
                        ))

        # 5. Read incident notes
        incident_flags = set()
        inc_dir = os.path.join(self.workspace, "incident_notes")
        for fn in sorted(os.listdir(inc_dir)):
            fp = os.path.join(inc_dir, fn)
            with open(fp) as f:
                text = f.read()
            for m in re.finditer(r"\(ID:\s*(\d+)\)", text):
                incident_flags.add(int(m.group(1)))

        # 6. List all feature flags (paginated) via tools
        all_flags = []
        page = 1
        while True:
            result = self.tools["list_feature_flags"](page=page, page_size=20)
            all_flags.extend(result["flags"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 7. Identify recently changed flags
        changed_flags = []
        for fl in all_flags:
            lcd = fl.get("last_change_date")
            if lcd and lcd >= cutoff_str:
                changed_flags.append(fl)

        # 8. For each changed flag, get metric comparison
        report_rows = []
        for fl in changed_flags:
            fid = fl["flag_id"]
            lcd = fl["last_change_date"]

            # Get change history (for context)
            _hist = self.tools["get_flag_change_history"](flag_id=fid)

            # Get metric comparison
            comp = self.tools["get_flag_metric_comparison"](
                flag_id=fid, change_date=lcd, window_days=window_days
            )

            before = comp["before"]
            after = comp["after"]

            # Error increase pct
            if before["error_count"] > 0:
                err_inc = round(
                    ((after["error_count"] - before["error_count"]) / before["error_count"]) * 100, 1
                )
            else:
                err_inc = round(float(after["error_count"]) * 100, 1) if after["error_count"] > 0 else 0.0

            # Satisfaction change
            if before["avg_satisfaction"] is not None and after["avg_satisfaction"] is not None:
                sat_change = round(after["avg_satisfaction"] - before["avg_satisfaction"], 2)
            else:
                sat_change = 0.0

            # Ticket ratio
            if before["ticket_count"] > 0:
                tix_ratio = round(after["ticket_count"] / before["ticket_count"], 2)
            else:
                tix_ratio = round(float(after["ticket_count"]), 2) if after["ticket_count"] > 0 else 0.0

            # Response time change from session logs
            # Parse change_date for comparison
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    cd_dt = datetime.strptime(lcd, fmt)
                    break
                except ValueError:
                    continue
            before_start = (cd_dt - timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M:%S")
            before_end = cd_dt.strftime("%Y-%m-%d %H:%M:%S")
            after_start = cd_dt.strftime("%Y-%m-%d %H:%M:%S")
            after_end = (cd_dt + timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M:%S")

            rt_b, rt_a = [], []
            for exposed_str, rt_ms, ts_str in session_rt:
                flag_ids = [int(x) for x in exposed_str.split(",") if x.strip()]
                if fid not in flag_ids:
                    continue
                if before_start <= ts_str < before_end:
                    rt_b.append(rt_ms)
                elif after_start <= ts_str < after_end:
                    rt_a.append(rt_ms)

            if rt_b and rt_a:
                avg_rt_b = sum(rt_b) / len(rt_b)
                avg_rt_a = sum(rt_a) / len(rt_a)
                rt_change_pct = round(((avg_rt_a - avg_rt_b) / avg_rt_b) * 100, 1) if avg_rt_b > 0 else 0.0
            else:
                rt_change_pct = 0.0

            criticality = svc_cfg.get(fl["service"], {}).get("criticality", "unknown")
            complexity = complexity_map.get(fid, "unknown")
            mentioned = "yes" if fid in incident_flags else "no"

            rec, reason = self._classify(err_inc, sat_change, tix_ratio, rb_thresh, mon_thresh)

            report_rows.append({
                "flag_id": fid,
                "flag_name": fl["flag_name"],
                "service": fl["service"],
                "criticality": criticality,
                "error_increase_pct": err_inc,
                "satisfaction_change": sat_change,
                "ticket_ratio": tix_ratio,
                "avg_response_time_change_pct": rt_change_pct,
                "rollback_complexity": complexity,
                "mentioned_in_incidents": mentioned,
                "recommendation": rec,
                "primary_reason": reason,
            })

        # Sort
        rec_order = {"ROLLBACK": 0, "MONITOR": 1, "KEEP": 2}
        report_rows.sort(key=lambda r: (rec_order.get(r["recommendation"], 9), r["flag_id"]))

        # Write CSV
        fieldnames = [
            "flag_id", "flag_name", "service", "criticality",
            "error_increase_pct", "satisfaction_change", "ticket_ratio",
            "avg_response_time_change_pct", "rollback_complexity",
            "mentioned_in_incidents", "recommendation", "primary_reason",
        ]
        report_path = os.path.join(self.workspace, "rollback_report.csv")
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(report_rows)

        # Compose action string
        n_total = len(report_rows)
        n_rb = sum(1 for r in report_rows if r["recommendation"] == "ROLLBACK")
        n_mon = sum(1 for r in report_rows if r["recommendation"] == "MONITOR")
        n_keep = sum(1 for r in report_rows if r["recommendation"] == "KEEP")
        rb_flags = [r for r in report_rows if r["recommendation"] == "ROLLBACK"]

        action_parts = [
            f"Analyzed {n_total} feature flags with recent configuration changes.",
            f"Recommendations: {n_rb} ROLLBACK, {n_mon} MONITOR, {n_keep} KEEP.",
        ]
        if rb_flags:
            action_parts.append("Flags recommended for rollback:")
            for r in rb_flags:
                action_parts.append(
                    f"  - {r['flag_name']} ({r['service']}, {r['primary_reason']})"
                )
        action = "\n".join(action_parts)

        return self.step(action)
