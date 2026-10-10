"""
Insider Trading Detection — Task Environment.
Provides tools for querying employee, trade, event, access, and options data,
plus evaluation logic for the compliance investigation task.
"""

import sqlite3
import os
import json
import csv
import glob as _glob
import yaml
from typing import Tuple, Dict, List, Any
from datetime import datetime, timedelta


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

    # ─────────────────────────────────────────────
    # TOOL METHODS
    # ─────────────────────────────────────────────

    @tool(
        description="List employees with optional filters. Returns a paginated list of employee records.",
        parameters={
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": "Filter by department name (exact match).",
                },
                "is_officer": {
                    "type": "boolean",
                    "description": "Filter by officer status.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page. Default 20.",
                },
            },
            "required": [],
        },
    )
    def list_employees(
        self,
        department: str = None,
        is_officer: bool = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        query = "SELECT * FROM employees WHERE 1=1"
        params = []
        if department:
            query += " AND department = ?"
            params.append(department)
        if is_officer is not None:
            query += " AND is_officer = ?"
            params.append(1 if is_officer else 0)
        query += " ORDER BY employee_id"
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "employees": rows[start:end],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get details of a single employee by their employee ID.",
        parameters={
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "The employee ID (e.g. 'EMP-0001').",
                },
            },
            "required": ["employee_id"],
        },
    )
    def get_employee_by_id(self, employee_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM employees WHERE employee_id = ?", (employee_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return {"employee": dict(row)}
        return {"error": f"Employee {employee_id} not found"}

    @tool(
        description="Query trade pre-clearance logs with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "Filter by employee ID.",
                },
                "ticker": {
                    "type": "string",
                    "description": "Filter by stock ticker.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by preclearance status (approved/denied/pending/expired).",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page. Default 20.",
                },
            },
            "required": [],
        },
    )
    def get_preclearance_logs(
        self,
        employee_id: str = None,
        ticker: str = None,
        status: str = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        query = "SELECT * FROM trade_preclearance WHERE 1=1"
        params = []
        if employee_id:
            query += " AND employee_id = ?"
            params.append(employee_id)
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker)
        if status:
            query += " AND preclearance_status = ?"
            params.append(status)
        query += " ORDER BY log_id"
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "logs": rows[start:end],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Query corporate events with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Filter by stock ticker.",
                },
                "event_type": {
                    "type": "string",
                    "description": "Filter by event type.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Filter events on or after this date (YYYY-MM-DD).",
                },
                "end_date": {
                    "type": "string",
                    "description": "Filter events on or before this date (YYYY-MM-DD).",
                },
                "min_sensitivity": {
                    "type": "integer",
                    "description": "Filter events with sensitivity_level >= this value.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page. Default 20.",
                },
            },
            "required": [],
        },
    )
    def get_corporate_events(
        self,
        ticker: str = None,
        event_type: str = None,
        start_date: str = None,
        end_date: str = None,
        min_sensitivity: int = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        query = "SELECT * FROM corporate_events WHERE 1=1"
        params = []
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if start_date:
            query += " AND event_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND event_date <= ?"
            params.append(end_date)
        if min_sensitivity is not None:
            query += " AND sensitivity_level >= ?"
            params.append(min_sensitivity)
        query += " ORDER BY event_id"
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        total = len(rows)
        start_i = (page - 1) * page_size
        end_i = start_i + page_size
        return {
            "events": rows[start_i:end_i],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Query sensitive data access logs with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "Filter by employee ID.",
                },
                "data_category": {
                    "type": "string",
                    "description": "Filter by data category.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Filter access on or after this date (YYYY-MM-DD).",
                },
                "end_date": {
                    "type": "string",
                    "description": "Filter access on or before this date (YYYY-MM-DD).",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page. Default 20.",
                },
            },
            "required": [],
        },
    )
    def get_access_logs(
        self,
        employee_id: str = None,
        data_category: str = None,
        start_date: str = None,
        end_date: str = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        query = "SELECT * FROM data_access_logs WHERE 1=1"
        params = []
        if employee_id:
            query += " AND employee_id = ?"
            params.append(employee_id)
        if data_category:
            query += " AND data_category = ?"
            params.append(data_category)
        if start_date:
            query += " AND access_timestamp >= ?"
            params.append(start_date)
        if end_date:
            query += " AND access_timestamp <= ?"
            params.append(end_date + " 23:59:59")
        query += " ORDER BY access_id"
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        total = len(rows)
        start_i = (page - 1) * page_size
        end_i = start_i + page_size
        return {
            "logs": rows[start_i:end_i],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Query unusual options volume alerts with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Filter by stock ticker.",
                },
                "min_severity": {
                    "type": "string",
                    "description": "Minimum alert severity (low/medium/high/critical). Returns alerts at or above this level.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Filter alerts on or after this date (YYYY-MM-DD).",
                },
                "end_date": {
                    "type": "string",
                    "description": "Filter alerts on or before this date (YYYY-MM-DD).",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page. Default 20.",
                },
            },
            "required": [],
        },
    )
    def get_options_alerts(
        self,
        ticker: str = None,
        min_severity: str = None,
        start_date: str = None,
        end_date: str = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        sev_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        query = "SELECT * FROM options_alerts WHERE 1=1"
        params = []
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker)
        if start_date:
            query += " AND alert_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND alert_date <= ?"
            params.append(end_date)
        query += " ORDER BY alert_id"
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        if min_severity and min_severity in sev_order:
            min_val = sev_order[min_severity]
            rows = [r for r in rows if sev_order.get(r["alert_severity"], 0) >= min_val]
        total = len(rows)
        start_i = (page - 1) * page_size
        end_i = start_i + page_size
        return {
            "alerts": rows[start_i:end_i],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    # ─────────────────────────────────────────────
    # GROUND TRUTH COMPUTATION (used by step)
    # ─────────────────────────────────────────────

    def _compute_ground_truth(self) -> List[dict]:
        """Compute the expected investigation cases from database + workspace."""
        # Load config files
        with open(os.path.join(self.workspace, "investigation_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "risk_scoring_rules.json")) as f:
            scoring = json.load(f)

        blackout_days = policy["blackout_window_days"]
        mnpi_lookback = policy["mnpi_access_lookback_days"]
        options_window = policy["options_correlation_window_days"]
        repeat_mult = policy["repeat_offender_multiplier"]
        min_score = policy["case_inclusion_min_score"]
        flag_points = {k: v["points"] for k, v in scoring["flags"].items()}

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load all data from DB
        employees = {
            r["employee_id"]: dict(r)
            for r in conn.execute("SELECT * FROM employees")
        }
        trades = [
            dict(r) for r in conn.execute("SELECT * FROM trade_preclearance")
        ]
        events = [
            dict(r) for r in conn.execute("SELECT * FROM corporate_events")
        ]
        access_logs = [
            dict(r) for r in conn.execute("SELECT * FROM data_access_logs")
        ]
        options = [
            dict(r) for r in conn.execute("SELECT * FROM options_alerts")
        ]
        conn.close()

        # Build lookup structures
        events_by_ticker = {}
        for ev in events:
            events_by_ticker.setdefault(ev["ticker"], []).append(ev)

        options_by_ticker = {}
        for opt in options:
            options_by_ticker.setdefault(opt["ticker"], []).append(opt)

        access_by_employee = {}
        for acc in access_logs:
            access_by_employee.setdefault(acc["employee_id"], []).append(acc)

        # Load broker confirmations from workspace
        broker_trades = []
        for fp in sorted(_glob.glob(os.path.join(self.workspace, "broker_confirmation_*.csv"))):
            with open(fp) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    broker_trades.append(row)

        # Build set of precleared (employee_id, ticker, execution_date)
        precleared_keys = set()
        for t in trades:
            if t["execution_date"]:
                precleared_keys.add(
                    (t["employee_id"], t["ticker"], t["execution_date"])
                )

        # Load repeat offenders from compliance memos
        repeat_offender_ids = set()
        for fp in sorted(_glob.glob(os.path.join(self.workspace, "compliance_memo_*.txt"))):
            with open(fp) as f:
                for line in f:
                    if line.startswith("Subject:"):
                        # Format: "Subject: EMP-XXXX (Name)"
                        eid = line.split(":")[1].strip().split(" ")[0]
                        repeat_offender_ids.add(eid)

        # --- Build cases per (employee_id, ticker) pair ---
        case_map = {}  # (employee_id, ticker) -> set of flags

        # A) Check preclearance trades against corporate events (blackout)
        for t in trades:
            emp_id = t["employee_id"]
            ticker = t["ticker"]
            req_date = datetime.strptime(t["requested_date"], "%Y-%m-%d")

            ticker_events = events_by_ticker.get(ticker, [])
            for ev in ticker_events:
                ev_date = datetime.strptime(ev["event_date"], "%Y-%m-%d")
                # blackout window: trade requested within blackout_days before event
                if timedelta(0) <= (ev_date - req_date) <= timedelta(days=blackout_days):
                    key = (emp_id, ticker)
                    if key not in case_map:
                        case_map[key] = set()
                    case_map[key].add("blackout_trade")

                    # high sensitivity event
                    if ev["sensitivity_level"] >= 4:
                        case_map[key].add("high_sensitivity_event")

                    # Check MNPI access
                    emp_access = access_by_employee.get(emp_id, [])
                    for acc in emp_access:
                        acc_date = datetime.strptime(
                            acc["access_timestamp"][:10], "%Y-%m-%d"
                        )
                        if timedelta(0) <= (ev_date - acc_date) <= timedelta(
                            days=mnpi_lookback
                        ):
                            case_map[key].add("mnpi_access")
                            break

                    # Check options correlation
                    ticker_opts = options_by_ticker.get(ticker, [])
                    for opt in ticker_opts:
                        opt_date = datetime.strptime(opt["alert_date"], "%Y-%m-%d")
                        if abs((opt_date - req_date).days) <= options_window:
                            case_map[key].add("options_correlation")
                            break
                    break  # one event match is enough for this trade

        # B) Check unreported trades from broker confirmations
        for bt in broker_trades:
            key_check = (bt["employee_id"], bt["ticker"], bt["execution_date"])
            if key_check not in precleared_keys:
                case_key = (bt["employee_id"], bt["ticker"])
                if case_key not in case_map:
                    case_map[case_key] = set()
                case_map[case_key].add("unreported_trade")

        # C) Apply officer flag and repeat offender
        for (emp_id, ticker), flags in case_map.items():
            emp = employees.get(emp_id)
            if emp and emp["is_officer"]:
                flags.add("officer_trade")
            if emp_id in repeat_offender_ids:
                flags.add("repeat_offender")

        # --- Score and build case list ---
        cases = []
        for (emp_id, ticker), flags in case_map.items():
            emp = employees.get(emp_id, {})
            raw_score = sum(flag_points.get(f, 0) for f in flags)
            if "repeat_offender" in flags:
                raw_score = raw_score * repeat_mult
            risk_score = int(round(raw_score))

            if risk_score < min_score:
                continue

            # Determine tier
            tier = "MEDIUM"
            action = "enhanced_monitoring"
            for tier_name in ["CRITICAL", "HIGH", "MEDIUM"]:
                tier_info = policy["risk_tiers"][tier_name]
                if risk_score >= tier_info["min_score"]:
                    tier = tier_name
                    action = tier_info["recommended_action"]
                    break

            sorted_flags = sorted(flags)
            cases.append(
                {
                    "employee_id": emp_id,
                    "employee_name": emp.get("name", ""),
                    "ticker": ticker,
                    "risk_score": risk_score,
                    "risk_tier": tier,
                    "flags": "|".join(sorted_flags),
                    "recommended_action": action,
                }
            )

        # Sort: risk_score desc, employee_name asc
        cases.sort(key=lambda c: (-c["risk_score"], c["employee_name"]))

        # Assign case IDs
        for i, c in enumerate(cases):
            c["case_id"] = f"CASE-{i + 1:04d}"

        return cases

    # ─────────────────────────────────────────────
    # STEP
    # ─────────────────────────────────────────────

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
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: investigation_cases.csv exists and is parseable (10 pts) ──
        csv_path = os.path.join(self.workspace, "investigation_cases.csv")
        csv_exists = os.path.exists(csv_path)
        agent_cases = []
        csv_parseable = False
        if csv_exists:
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    agent_cases = list(reader)
                csv_parseable = True
            except Exception:
                pass

        c1_pass = csv_exists and csv_parseable
        c1_score = 10 if c1_pass else 0
        eval_criteria["csv_file_valid"] = {
            "passed": c1_pass,
            "score": c1_score,
            "max_score": 10,
            "reason": "" if c1_pass else "investigation_cases.csv missing or not parseable",
        }
        total_score += c1_score
        max_score += 10

        # ── Criterion 2: correct columns in CSV (10 pts) ──
        expected_cols = [
            "case_id", "employee_id", "employee_name", "ticker",
            "risk_score", "risk_tier", "flags", "recommended_action",
        ]
        if agent_cases:
            actual_cols = list(agent_cases[0].keys())
            c2_pass = actual_cols == expected_cols
        else:
            c2_pass = False
        c2_score = 10 if c2_pass else 0
        eval_criteria["csv_columns_correct"] = {
            "passed": c2_pass,
            "score": c2_score,
            "max_score": 10,
            "reason": "" if c2_pass else f"Expected columns {expected_cols}, got {list(agent_cases[0].keys()) if agent_cases else '[]'}",
        }
        total_score += c2_score
        max_score += 10

        # ── Criterion 3: correct number of cases (15 pts) ──
        c3_pass = len(agent_cases) == len(ground_truth)
        c3_score = 15 if c3_pass else 0
        eval_criteria["case_count_correct"] = {
            "passed": c3_pass,
            "score": c3_score,
            "max_score": 15,
            "reason": "" if c3_pass else f"Expected {len(ground_truth)} cases, got {len(agent_cases)}",
        }
        total_score += c3_score
        max_score += 15

        # ── Criterion 4: correct sort order (15 pts) ──
        c4_pass = False
        if len(agent_cases) == len(ground_truth) and len(ground_truth) > 0:
            agent_order = [
                (ac.get("employee_id", ""), ac.get("ticker", ""))
                for ac in agent_cases
            ]
            gt_order = [(gc["employee_id"], gc["ticker"]) for gc in ground_truth]
            c4_pass = agent_order == gt_order
        c4_score = 15 if c4_pass else 0
        eval_criteria["sort_order_correct"] = {
            "passed": c4_pass,
            "score": c4_score,
            "max_score": 15,
            "reason": "" if c4_pass else "Cases not sorted correctly by risk_score desc, employee_name asc",
        }
        total_score += c4_score
        max_score += 15

        # ── Criterion 5: risk scores correct (20 pts) ──
        gt_score_map = {
            (gc["employee_id"], gc["ticker"]): gc["risk_score"]
            for gc in ground_truth
        }
        correct_scores = 0
        total_gt = len(ground_truth)
        for ac in agent_cases:
            key = (ac.get("employee_id", ""), ac.get("ticker", ""))
            try:
                agent_score_val = int(ac.get("risk_score", -1))
            except (ValueError, TypeError):
                agent_score_val = -1
            if key in gt_score_map and gt_score_map[key] == agent_score_val:
                correct_scores += 1
        if total_gt > 0:
            score_ratio = correct_scores / total_gt
        else:
            score_ratio = 1.0 if len(agent_cases) == 0 else 0.0
        c5_score = int(round(20 * score_ratio))
        c5_pass = c5_score == 20
        eval_criteria["risk_scores_correct"] = {
            "passed": c5_pass,
            "score": c5_score,
            "max_score": 20,
            "reason": "" if c5_pass else f"{correct_scores}/{total_gt} scores correct",
        }
        total_score += c5_score
        max_score += 20

        # ── Criterion 6: flags correct (15 pts) ──
        gt_flag_map = {
            (gc["employee_id"], gc["ticker"]): gc["flags"]
            for gc in ground_truth
        }
        correct_flags = 0
        for ac in agent_cases:
            key = (ac.get("employee_id", ""), ac.get("ticker", ""))
            if key in gt_flag_map and ac.get("flags", "") == gt_flag_map[key]:
                correct_flags += 1
        if total_gt > 0:
            flag_ratio = correct_flags / total_gt
        else:
            flag_ratio = 1.0 if len(agent_cases) == 0 else 0.0
        c6_score = int(round(15 * flag_ratio))
        c6_pass = c6_score == 15
        eval_criteria["flags_correct"] = {
            "passed": c6_pass,
            "score": c6_score,
            "max_score": 15,
            "reason": "" if c6_pass else f"{correct_flags}/{total_gt} flag sets correct",
        }
        total_score += c6_score
        max_score += 15

        # ── Criterion 7: response summary (15 pts) ──
        # Check that action contains: total case count, tier breakdown, top case employee
        c7_pts = 0
        action_lower = action.lower() if action else ""
        # Total case count mentioned
        if str(len(ground_truth)) in action:
            c7_pts += 5
        # At least one tier name mentioned
        for tier in ["CRITICAL", "HIGH", "MEDIUM"]:
            if tier.lower() in action_lower or tier in action:
                c7_pts += 5
                break
        # Top case employee name mentioned
        if ground_truth:
            top_name = ground_truth[0]["employee_name"]
            if top_name.lower() in action_lower:
                c7_pts += 5
        else:
            c7_pts += 5  # no cases expected, skip this sub-check
        c7_pass = c7_pts == 15
        eval_criteria["response_summary"] = {
            "passed": c7_pass,
            "score": c7_pts,
            "max_score": 15,
            "reason": "" if c7_pass else "Response missing total count, tier names, or top case employee name",
        }
        total_score += c7_pts
        max_score += 15

        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ─────────────────────────────────────────────
    # VERIFY
    # ─────────────────────────────────────────────

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
        import math

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # 1. Load config files from workspace
        with open(os.path.join(self.workspace, "investigation_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "risk_scoring_rules.json")) as f:
            scoring = json.load(f)

        blackout_days = policy["blackout_window_days"]
        mnpi_lookback = policy["mnpi_access_lookback_days"]
        options_window = policy["options_correlation_window_days"]
        repeat_mult = policy["repeat_offender_multiplier"]
        min_score = policy["case_inclusion_min_score"]
        flag_points = {k: v["points"] for k, v in scoring["flags"].items()}

        # 2. Load all employees via tool (paginated)
        employees = {}
        result = call_tool("list_employees", page=1, page_size=20)
        for emp in result["employees"]:
            employees[emp["employee_id"]] = emp
        total_pages = result["total_pages"]
        for p in range(2, total_pages + 1):
            result = call_tool("list_employees", page=p, page_size=20)
            for emp in result["employees"]:
                employees[emp["employee_id"]] = emp

        # 3. Load all trade preclearance logs via tool (paginated)
        trades = []
        result = call_tool("get_preclearance_logs", page=1, page_size=20)
        trades.extend(result["logs"])
        total_pages = result["total_pages"]
        for p in range(2, total_pages + 1):
            result = call_tool("get_preclearance_logs", page=p, page_size=20)
            trades.extend(result["logs"])

        # 4. Load all corporate events via tool (paginated)
        events = []
        result = call_tool("get_corporate_events", page=1, page_size=20)
        events.extend(result["events"])
        total_pages = result["total_pages"]
        for p in range(2, total_pages + 1):
            result = call_tool("get_corporate_events", page=p, page_size=20)
            events.extend(result["events"])

        # 5. Load all access logs via tool (paginated)
        all_access = []
        result = call_tool("get_access_logs", page=1, page_size=20)
        all_access.extend(result["logs"])
        total_pages = result["total_pages"]
        for p in range(2, total_pages + 1):
            result = call_tool("get_access_logs", page=p, page_size=20)
            all_access.extend(result["logs"])

        # 6. Load all options alerts via tool (paginated)
        all_options = []
        result = call_tool("get_options_alerts", page=1, page_size=20)
        all_options.extend(result["alerts"])
        total_pages = result["total_pages"]
        for p in range(2, total_pages + 1):
            result = call_tool("get_options_alerts", page=p, page_size=20)
            all_options.extend(result["alerts"])

        # 7. Load broker confirmations from workspace
        broker_trades = []
        for fp in sorted(_glob.glob(os.path.join(self.workspace, "broker_confirmation_*.csv"))):
            with open(fp) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    broker_trades.append(row)

        # 8. Load repeat offenders from compliance memos
        repeat_offender_ids = set()
        for fp in sorted(_glob.glob(os.path.join(self.workspace, "compliance_memo_*.txt"))):
            with open(fp) as f:
                for line in f:
                    if line.startswith("Subject:"):
                        eid = line.split(":")[1].strip().split(" ")[0]
                        repeat_offender_ids.add(eid)

        # 9. Build lookup structures
        events_by_ticker = {}
        for ev in events:
            events_by_ticker.setdefault(ev["ticker"], []).append(ev)

        options_by_ticker = {}
        for opt in all_options:
            options_by_ticker.setdefault(opt["ticker"], []).append(opt)

        access_by_employee = {}
        for acc in all_access:
            access_by_employee.setdefault(acc["employee_id"], []).append(acc)

        precleared_keys = set()
        for t in trades:
            if t["execution_date"]:
                precleared_keys.add(
                    (t["employee_id"], t["ticker"], t["execution_date"])
                )

        # 10. Detect suspicious patterns
        case_map = {}

        # A) Blackout trade detection
        for t in trades:
            emp_id = t["employee_id"]
            ticker = t["ticker"]
            req_date = datetime.strptime(t["requested_date"], "%Y-%m-%d")

            ticker_events = events_by_ticker.get(ticker, [])
            for ev in ticker_events:
                ev_date = datetime.strptime(ev["event_date"], "%Y-%m-%d")
                if timedelta(0) <= (ev_date - req_date) <= timedelta(days=blackout_days):
                    key = (emp_id, ticker)
                    if key not in case_map:
                        case_map[key] = set()
                    case_map[key].add("blackout_trade")

                    if ev["sensitivity_level"] >= 4:
                        case_map[key].add("high_sensitivity_event")

                    emp_access = access_by_employee.get(emp_id, [])
                    for acc in emp_access:
                        acc_date = datetime.strptime(
                            acc["access_timestamp"][:10], "%Y-%m-%d"
                        )
                        if timedelta(0) <= (ev_date - acc_date) <= timedelta(
                            days=mnpi_lookback
                        ):
                            case_map[key].add("mnpi_access")
                            break

                    ticker_opts = options_by_ticker.get(ticker, [])
                    for opt in ticker_opts:
                        opt_date = datetime.strptime(opt["alert_date"], "%Y-%m-%d")
                        if abs((opt_date - req_date).days) <= options_window:
                            case_map[key].add("options_correlation")
                            break
                    break

        # B) Unreported trades
        for bt in broker_trades:
            key_check = (bt["employee_id"], bt["ticker"], bt["execution_date"])
            if key_check not in precleared_keys:
                case_key = (bt["employee_id"], bt["ticker"])
                if case_key not in case_map:
                    case_map[case_key] = set()
                case_map[case_key].add("unreported_trade")

        # C) Officer + repeat offender flags
        for (emp_id, ticker), flags in case_map.items():
            emp = employees.get(emp_id, {})
            if emp.get("is_officer"):
                flags.add("officer_trade")
            if emp_id in repeat_offender_ids:
                flags.add("repeat_offender")

        # 11. Score and build case list
        cases = []
        for (emp_id, ticker), flags in case_map.items():
            emp = employees.get(emp_id, {})
            raw_score = sum(flag_points.get(f, 0) for f in flags)
            if "repeat_offender" in flags:
                raw_score = raw_score * repeat_mult
            risk_score = int(round(raw_score))

            if risk_score < min_score:
                continue

            tier = "MEDIUM"
            action_str = "enhanced_monitoring"
            for tier_name in ["CRITICAL", "HIGH", "MEDIUM"]:
                tier_info = policy["risk_tiers"][tier_name]
                if risk_score >= tier_info["min_score"]:
                    tier = tier_name
                    action_str = tier_info["recommended_action"]
                    break

            sorted_flags = sorted(flags)
            cases.append({
                "employee_id": emp_id,
                "employee_name": emp.get("name", ""),
                "ticker": ticker,
                "risk_score": risk_score,
                "risk_tier": tier,
                "flags": "|".join(sorted_flags),
                "recommended_action": action_str,
            })

        cases.sort(key=lambda c: (-c["risk_score"], c["employee_name"]))
        for i, c in enumerate(cases):
            c["case_id"] = f"CASE-{i + 1:04d}"

        # 12. Write investigation_cases.csv
        csv_path = os.path.join(self.workspace, "investigation_cases.csv")
        fieldnames = [
            "case_id", "employee_id", "employee_name", "ticker",
            "risk_score", "risk_tier", "flags", "recommended_action",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for c in cases:
                writer.writerow({
                    "case_id": c["case_id"],
                    "employee_id": c["employee_id"],
                    "employee_name": c["employee_name"],
                    "ticker": c["ticker"],
                    "risk_score": c["risk_score"],
                    "risk_tier": c["risk_tier"],
                    "flags": c["flags"],
                    "recommended_action": c["recommended_action"],
                })

        # 13. Build action string
        tier_counts = {}
        for c in cases:
            tier_counts[c["risk_tier"]] = tier_counts.get(c["risk_tier"], 0) + 1

        top_cases_desc = ""
        for c in cases[:5]:
            top_cases_desc += (
                f"  - {c['case_id']}: {c['employee_name']} ({c['employee_id']}) "
                f"trading {c['ticker']}, score {c['risk_score']} ({c['risk_tier']})\n"
            )

        action = (
            f"Investigation complete. Generated {len(cases)} cases meeting the minimum score threshold.\n\n"
            f"Tier breakdown:\n"
        )
        for tier in ["CRITICAL", "HIGH", "MEDIUM"]:
            cnt = tier_counts.get(tier, 0)
            if cnt > 0:
                action += f"  - {tier}: {cnt} cases\n"
        action += f"\nTop cases:\n{top_cases_desc}"
        action += f"\nAll {len(cases)} cases have been saved to investigation_cases.csv."

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need at least 15"

        return self.step(action)
