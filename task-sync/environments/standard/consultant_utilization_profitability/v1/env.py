"""
Environment for consultant utilization and project profitability analysis task.
"""

import sqlite3
import os
import csv
import json
import math
import glob as glob_mod
from typing import Tuple, Dict, List, Any

try:
    import yaml
except ImportError:
    yaml = None


def _load_yaml(path):
    if yaml is not None:
        with open(path) as f:
            return yaml.safe_load(f)
    # Minimal fallback – works for the flat/nested dicts this task produces
    import re
    with open(path) as f:
        text = f.read()
    # Use a simple approach: try json-ifying
    # Actually just require pyyaml for this task
    raise ImportError("pyyaml is required")


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

    # ── Tools ──────────────────────────────────────────────────────────────────

    @tool(
        description="List consultants with optional filters. Returns paginated results including each consultant's id, name, role, department, and hourly internal cost rate.",
        parameters={
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": "Filter by department name (exact match). Optional.",
                },
                "role": {
                    "type": "string",
                    "description": "Filter by role (exact match). Optional.",
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
    def list_consultants(self, department: str = None, role: str = None,
                         page: int = 1, page_size: int = 20) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        clauses, params = [], []
        if department:
            clauses.append("department = ?"); params.append(department)
        if role:
            clauses.append("role = ?"); params.append(role)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        cur.execute(f"SELECT COUNT(*) FROM consultants{where}", params)
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        cur.execute(
            f"SELECT consultant_id, name, role, department, hourly_cost "
            f"FROM consultants{where} ORDER BY consultant_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"consultants": rows, "page": page, "page_size": page_size,
                "total_pages": total_pages, "total_count": total}

    @tool(
        description="Get full details for a single consultant by ID, including hourly internal cost rate.",
        parameters={
            "type": "object",
            "properties": {
                "consultant_id": {"type": "integer", "description": "Consultant ID."},
            },
            "required": ["consultant_id"],
        },
    )
    def get_consultant_details(self, consultant_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM consultants WHERE consultant_id = ?", (consultant_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else {"error": "Not found"}

    @tool(
        description="List projects with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: 'active', 'completed', or 'on_hold'. Optional.",
                },
                "client_id": {
                    "type": "integer",
                    "description": "Filter by client ID. Optional.",
                },
                "page": {"type": "integer", "description": "Page number (1-indexed). Default 1."},
                "page_size": {"type": "integer", "description": "Results per page. Default 20."},
            },
            "required": [],
        },
    )
    def list_projects(self, status: str = None, client_id: int = None,
                      page: int = 1, page_size: int = 20) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        clauses, params = [], []
        if status:
            clauses.append("status = ?"); params.append(status)
        if client_id is not None:
            clauses.append("client_id = ?"); params.append(client_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        cur.execute(f"SELECT COUNT(*) FROM projects{where}", params)
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        cur.execute(
            f"SELECT project_id, name, client_id, status, start_date, end_date, total_budget "
            f"FROM projects{where} ORDER BY project_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"projects": rows, "page": page, "page_size": page_size,
                "total_pages": total_pages, "total_count": total}

    @tool(
        description="Get full details for a single project by ID.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID."},
            },
            "required": ["project_id"],
        },
    )
    def get_project_details(self, project_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else {"error": "Not found"}

    @tool(
        description="Retrieve timesheet entries with optional filters. Returns paginated results with entry_id, consultant_id, project_id, work_date, hours, and is_billable flag.",
        parameters={
            "type": "object",
            "properties": {
                "consultant_id": {"type": "integer", "description": "Filter by consultant ID. Optional."},
                "project_id": {"type": "integer", "description": "Filter by project ID. Optional."},
                "page": {"type": "integer", "description": "Page number (1-indexed). Default 1."},
                "page_size": {"type": "integer", "description": "Results per page. Default 50."},
            },
            "required": [],
        },
    )
    def get_timesheet_entries(self, consultant_id: int = None, project_id: int = None,
                              page: int = 1, page_size: int = 50) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        clauses, params = [], []
        if consultant_id is not None:
            clauses.append("consultant_id = ?"); params.append(consultant_id)
        if project_id is not None:
            clauses.append("project_id = ?"); params.append(project_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        cur.execute(f"SELECT COUNT(*) FROM timesheets{where}", params)
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        cur.execute(
            f"SELECT entry_id, consultant_id, project_id, work_date, hours, is_billable "
            f"FROM timesheets{where} ORDER BY entry_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"entries": rows, "page": page, "page_size": page_size,
                "total_pages": total_pages, "total_count": total}

    @tool(
        description="Get information about a client by ID, including name, industry, and billing tier.",
        parameters={
            "type": "object",
            "properties": {
                "client_id": {"type": "integer", "description": "Client ID."},
            },
            "required": ["client_id"],
        },
    )
    def get_client_info(self, client_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else {"error": "Not found"}

    @tool(
        description="Get the skill set for a specific consultant, returning skill names and proficiency levels (1-5).",
        parameters={
            "type": "object",
            "properties": {
                "consultant_id": {"type": "integer", "description": "Consultant ID."},
            },
            "required": ["consultant_id"],
        },
    )
    def get_consultant_skills(self, consultant_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT skill_name, proficiency_level FROM consultant_skills "
            "WHERE consultant_id = ? ORDER BY skill_name",
            (consultant_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"consultant_id": consultant_id, "skills": rows}

    @tool(
        description="Get budget allocation breakdown for a project, showing how its total budget is distributed across categories.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID."},
            },
            "required": ["project_id"],
        },
    )
    def get_budget_breakdown(self, project_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT category, allocated_amount FROM budget_allocations "
            "WHERE project_id = ? ORDER BY category",
            (project_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"project_id": project_id, "allocations": rows}

    # ── Helpers for step (direct DB access allowed) ────────────────────────────

    def _read_workspace_configs(self):
        """Read all workspace config/data files needed for ground truth."""
        ws = self.workspace

        # Billing rate tiers
        tier_rates = _load_yaml(os.path.join(ws, "billing_rate_tiers.yaml"))

        # Utilization thresholds
        util_cfg = _load_yaml(os.path.join(ws, "utilization_thresholds.yaml"))

        # Over-servicing rules
        with open(os.path.join(ws, "overservicing_rules.json")) as f:
            oversvc = json.load(f)

        # Consultant capacity (all CSV files)
        capacity = {}  # consultant_id -> total_target_hours
        for fp in sorted(glob_mod.glob(os.path.join(ws, "consultant_capacity_*.csv"))):
            with open(fp, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    cid = int(row["consultant_id"])
                    capacity[cid] = capacity.get(cid, 0) + int(row["target_hours"])

        # Client rate cards (all YAML files)
        client_rates = {}  # client_id -> {rate_type, base_tier, negotiated_rates}
        for fp in sorted(glob_mod.glob(os.path.join(ws, "client_rate_card_*.yaml"))):
            data = _load_yaml(fp)
            for cid_key, info in data.items():
                client_rates[int(cid_key)] = info

        # Project requirements (all JSON files)
        proj_reqs = {}  # project_id -> {required_skills, priority_score, ...}
        for fp in sorted(glob_mod.glob(os.path.join(ws, "project_requirements_*.json"))):
            with open(fp) as f:
                for entry in json.load(f):
                    proj_reqs[entry["project_id"]] = entry

        # Skill demand weights
        with open(os.path.join(ws, "skill_demand_weights.json")) as f:
            skill_weights = json.load(f)

        return {
            "tier_rates": tier_rates,
            "util_cfg": util_cfg,
            "oversvc": oversvc,
            "capacity": capacity,
            "client_rates": client_rates,
            "proj_reqs": proj_reqs,
            "skill_weights": skill_weights,
        }

    def _get_billing_rate(self, role, client_id, cfg):
        """Look up the billing rate for a role + client."""
        cr = cfg["client_rates"].get(client_id, {})
        if cr.get("rate_type") == "custom" and cr.get("negotiated_rates"):
            return cr["negotiated_rates"].get(role, 0)
        tier = cr.get("base_tier")
        if tier and tier in cfg["tier_rates"]:
            return cfg["tier_rates"][tier].get(role, 0)
        return 0

    def _compute_ground_truth(self):
        """Compute all ground-truth values from DB + workspace."""
        cfg = self._read_workspace_configs()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Load full tables
        cur.execute("SELECT * FROM consultants ORDER BY consultant_id")
        consultants = {r["consultant_id"]: dict(r) for r in cur.fetchall()}

        cur.execute("SELECT * FROM projects ORDER BY project_id")
        projects = {r["project_id"]: dict(r) for r in cur.fetchall()}

        cur.execute("SELECT * FROM clients ORDER BY client_id")
        clients = {r["client_id"]: dict(r) for r in cur.fetchall()}

        cur.execute("SELECT * FROM timesheets ORDER BY entry_id")
        timesheets = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM consultant_skills ORDER BY consultant_id, skill_name")
        skills_raw = [dict(r) for r in cur.fetchall()]

        conn.close()

        # Consultant skills map
        consultant_skills = {}
        for s in skills_raw:
            consultant_skills.setdefault(s["consultant_id"], []).append(s)

        # ── Utilization ────────────────────────────────────────────────────────
        hours_worked = {}  # consultant_id -> total hours
        for t in timesheets:
            hours_worked[t["consultant_id"]] = hours_worked.get(t["consultant_id"], 0) + t["hours"]

        util_threshold_under = cfg["util_cfg"]["underutilized_threshold"]
        util_threshold_over = cfg["util_cfg"]["overutilized_threshold"]
        analysis_weeks = cfg["util_cfg"]["analysis_period_weeks"]

        utilization = {}
        for cid, c in consultants.items():
            hw = round(hours_worked.get(cid, 0), 1)
            avail = cfg["capacity"].get(cid, 40 * analysis_weeks)
            avail = round(float(avail), 1)
            rate = round(hw / avail, 4) if avail > 0 else 0.0
            if rate < util_threshold_under:
                status = "underutilized"
            elif rate > util_threshold_over:
                status = "overutilized"
            else:
                status = "normal"
            utilization[cid] = {
                "consultant_id": cid,
                "consultant_name": c["name"],
                "role": c["role"],
                "department": c["department"],
                "total_hours_worked": hw,
                "total_available_hours": avail,
                "utilization_rate": rate,
                "status": status,
            }

        # ── Profitability ──────────────────────────────────────────────────────
        proj_costs = {}   # project_id -> total cost
        proj_revenue = {} # project_id -> total revenue
        for t in timesheets:
            pid = t["project_id"]
            cid = t["consultant_id"]
            c = consultants[cid]
            p = projects[pid]
            cost = t["hours"] * c["hourly_cost"]
            proj_costs[pid] = proj_costs.get(pid, 0) + cost

            if t["is_billable"]:
                client_id = p["client_id"]
                rate = self._get_billing_rate(c["role"], client_id, cfg)
                proj_revenue[pid] = proj_revenue.get(pid, 0) + t["hours"] * rate

        oversvc_threshold = cfg["oversvc"]["budget_overrun_threshold_pct"]

        profitability = {}
        for pid, p in projects.items():
            tc = round(proj_costs.get(pid, 0), 2)
            tr = round(proj_revenue.get(pid, 0), 2)
            budget = p["total_budget"]
            margin = round((tr - tc) / tr * 100, 2) if tr > 0 else 0.0
            flag = tc > budget * (1 + oversvc_threshold / 100)
            client_name = clients[p["client_id"]]["name"]
            profitability[pid] = {
                "project_id": pid,
                "project_name": p["name"],
                "client_name": client_name,
                "total_cost": tc,
                "total_revenue": tr,
                "total_budget": budget,
                "margin_pct": margin,
                "overservicing_flag": flag,
            }

        # ── Identify underutilized & over-serviced ─────────────────────────────
        underutilized = [cid for cid, u in utilization.items() if u["status"] == "underutilized"]
        underutilized.sort()

        overserviced_active = sorted([
            pid for pid, pf in profitability.items()
            if pf["overservicing_flag"] and projects[pid]["status"] == "active"
        ])

        active_projects = sorted([pid for pid, p in projects.items() if p["status"] == "active"])

        # ── Reallocation proposal ──────────────────────────────────────────────
        # Current project assignments per consultant
        current_projects = {}
        for t in timesheets:
            current_projects.setdefault(t["consultant_id"], set()).add(t["project_id"])

        proposals = []
        # Track cumulative proposed hours per consultant for utilization projection
        proposed_hours = {}  # consultant_id -> sum of recommended_weekly_hours

        for cid in underutilized:
            c = consultants[cid]
            u = utilization[cid]
            c_skills = {s["skill_name"]: s["proficiency_level"]
                        for s in consultant_skills.get(cid, [])}
            cur_proj_count = len(current_projects.get(cid, set()))

            # Prioritize over-serviced active projects, then other active projects
            target_pids = overserviced_active + [
                pid for pid in active_projects if pid not in overserviced_active
            ]

            for pid in target_pids:
                if cur_proj_count >= 3:
                    break
                if pid in current_projects.get(cid, set()):
                    continue
                req = cfg["proj_reqs"].get(pid, {})
                req_skills = req.get("required_skills", [])
                min_prof = req.get("min_proficiency_required", 3)

                matching = [s for s in req_skills
                            if s in c_skills and c_skills[s] >= min_prof]
                if not matching:
                    continue

                # Compute max allowed hours
                avail = u["total_available_hours"]
                prev_proposed = proposed_hours.get(cid, 0)
                max_by_util = ((util_threshold_over * avail -
                                u["total_hours_worked"] - prev_proposed * analysis_weeks)
                               / analysis_weeks)
                max_hours = min(20.0, max(0, max_by_util))
                if max_hours < 1.0:
                    continue

                rec_hours = round(max_hours, 1)

                # Billing rate for this consultant's role on the target project's client
                client_id = projects[pid]["client_id"]
                billing_rate = self._get_billing_rate(c["role"], client_id, cfg)
                margin_impact = round(rec_hours * (billing_rate - c["hourly_cost"]), 2)

                proposals.append({
                    "consultant_id": cid,
                    "consultant_name": c["name"],
                    "target_project_id": pid,
                    "target_project_name": projects[pid]["name"],
                    "recommended_weekly_hours": rec_hours,
                    "matching_skills": ";".join(sorted(matching)),
                    "projected_weekly_margin_impact": margin_impact,
                })
                proposed_hours[cid] = prev_proposed + rec_hours
                cur_proj_count += 1

        # Sort proposals
        proposals.sort(key=lambda x: (x["consultant_id"], x["target_project_id"]))

        total_margin_improvement = round(sum(p["projected_weekly_margin_impact"] for p in proposals), 2)

        return {
            "utilization": utilization,
            "profitability": profitability,
            "underutilized": underutilized,
            "overserviced_active": overserviced_active,
            "proposals": proposals,
            "total_margin_improvement": total_margin_improvement,
            "cfg": cfg,
            "consultants": consultants,
            "projects": projects,
            "clients": clients,
            "timesheets": timesheets,
            "consultant_skills": consultant_skills,
        }

    # ── Step ───────────────────────────────────────────────────────────────────

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
        gt = self._compute_ground_truth()
        cfg = gt["cfg"]
        criteria = {}

        # ── 1. utilization_report.csv exists & columns correct (10 pts) ────────
        util_path = os.path.join(self.workspace, "utilization_report.csv")
        expected_cols = ["consultant_id", "consultant_name", "role", "department",
                         "total_hours_worked", "total_available_hours",
                         "utilization_rate", "status"]
        if os.path.exists(util_path):
            with open(util_path, newline="") as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames or []
                if all(c in cols for c in expected_cols):
                    criteria["utilization_report_format"] = {
                        "passed": True, "score": 10, "max_score": 10}
                else:
                    criteria["utilization_report_format"] = {
                        "passed": False, "score": 0, "max_score": 10,
                        "reason": f"Missing columns. Expected {expected_cols}, got {cols}"}
        else:
            criteria["utilization_report_format"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "utilization_report.csv not found"}

        # ── 2. utilization rates correct (20 pts) ─────────────────────────────
        if criteria["utilization_report_format"]["passed"]:
            with open(util_path, newline="") as f:
                reader = csv.DictReader(f)
                agent_util = {}
                for row in reader:
                    try:
                        cid = int(row["consultant_id"])
                        agent_util[cid] = {
                            "total_hours_worked": float(row["total_hours_worked"]),
                            "total_available_hours": float(row["total_available_hours"]),
                            "utilization_rate": float(row["utilization_rate"]),
                            "status": row["status"].strip(),
                        }
                    except (ValueError, KeyError):
                        continue

            n_total = len(gt["utilization"])
            n_correct_rate = 0
            n_correct_status = 0
            for cid, truth in gt["utilization"].items():
                agent = agent_util.get(cid)
                if agent is None:
                    continue
                if abs(agent["utilization_rate"] - truth["utilization_rate"]) < 0.01:
                    n_correct_rate += 1
                if agent["status"] == truth["status"]:
                    n_correct_status += 1

            rate_frac = n_correct_rate / n_total if n_total > 0 else 0
            status_frac = n_correct_status / n_total if n_total > 0 else 0
            rate_score = round(20 * rate_frac)
            status_score = round(10 * status_frac)
            criteria["utilization_rates"] = {
                "passed": rate_frac >= 0.9, "score": rate_score, "max_score": 20,
                "reason": f"{n_correct_rate}/{n_total} rates correct" if rate_frac < 0.9 else ""}
            criteria["utilization_status"] = {
                "passed": status_frac >= 0.9, "score": status_score, "max_score": 10,
                "reason": f"{n_correct_status}/{n_total} statuses correct" if status_frac < 0.9 else ""}
        else:
            criteria["utilization_rates"] = {"passed": False, "score": 0, "max_score": 20,
                                             "reason": "No valid report"}
            criteria["utilization_status"] = {"passed": False, "score": 0, "max_score": 10,
                                              "reason": "No valid report"}

        # ── 3. profitability_analysis.csv format (10 pts) ─────────────────────
        prof_path = os.path.join(self.workspace, "profitability_analysis.csv")
        prof_cols = ["project_id", "project_name", "client_name", "total_cost",
                     "total_revenue", "total_budget", "margin_pct", "overservicing_flag"]
        if os.path.exists(prof_path):
            with open(prof_path, newline="") as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames or []
                if all(c in cols for c in prof_cols):
                    criteria["profitability_format"] = {
                        "passed": True, "score": 10, "max_score": 10}
                else:
                    criteria["profitability_format"] = {
                        "passed": False, "score": 0, "max_score": 10,
                        "reason": f"Missing columns. Expected {prof_cols}, got {cols}"}
        else:
            criteria["profitability_format"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "profitability_analysis.csv not found"}

        # ── 4. profitability margins correct (15 pts) ─────────────────────────
        if criteria["profitability_format"]["passed"]:
            with open(prof_path, newline="") as f:
                reader = csv.DictReader(f)
                agent_prof = {}
                for row in reader:
                    try:
                        pid = int(row["project_id"])
                        agent_prof[pid] = {
                            "total_cost": float(row["total_cost"]),
                            "total_revenue": float(row["total_revenue"]),
                            "margin_pct": float(row["margin_pct"]),
                            "overservicing_flag": row["overservicing_flag"].strip(),
                        }
                    except (ValueError, KeyError):
                        continue

            n_total = len(gt["profitability"])
            n_margin_ok = 0
            n_flag_ok = 0
            for pid, truth in gt["profitability"].items():
                agent = agent_prof.get(pid)
                if agent is None:
                    continue
                if abs(agent["margin_pct"] - truth["margin_pct"]) < 1.0:
                    n_margin_ok += 1
                truth_flag = str(truth["overservicing_flag"])
                if agent["overservicing_flag"] == truth_flag:
                    n_flag_ok += 1

            margin_frac = n_margin_ok / n_total if n_total > 0 else 0
            flag_frac = n_flag_ok / n_total if n_total > 0 else 0
            criteria["profitability_margins"] = {
                "passed": margin_frac >= 0.85, "score": round(15 * margin_frac), "max_score": 15,
                "reason": f"{n_margin_ok}/{n_total} margins correct" if margin_frac < 0.85 else ""}
            criteria["overservicing_flags"] = {
                "passed": flag_frac >= 0.85, "score": round(10 * flag_frac), "max_score": 10,
                "reason": f"{n_flag_ok}/{n_total} flags correct" if flag_frac < 0.85 else ""}
        else:
            criteria["profitability_margins"] = {"passed": False, "score": 0, "max_score": 15,
                                                  "reason": "No valid report"}
            criteria["overservicing_flags"] = {"passed": False, "score": 0, "max_score": 10,
                                                "reason": "No valid report"}

        # ── 5. reallocation_proposal.csv valid (15 pts) ───────────────────────
        realloc_path = os.path.join(self.workspace, "reallocation_proposal.csv")
        realloc_cols = ["consultant_id", "consultant_name", "target_project_id",
                        "target_project_name", "recommended_weekly_hours",
                        "matching_skills", "projected_weekly_margin_impact"]
        realloc_score = 0
        if os.path.exists(realloc_path):
            with open(realloc_path, newline="") as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames or []
                if not all(c in cols for c in realloc_cols):
                    criteria["reallocation_proposal"] = {
                        "passed": False, "score": 0, "max_score": 15,
                        "reason": f"Missing columns. Expected {realloc_cols}"}
                else:
                    f.seek(0)
                    reader = csv.DictReader(f)
                    entries = list(reader)

                    # Validate constraints
                    util_threshold_over = cfg["util_cfg"]["overutilized_threshold"]
                    analysis_weeks = cfg["util_cfg"]["analysis_period_weeks"]
                    n_valid = 0
                    n_entries = len(entries)
                    proposed_totals = {}
                    for e in entries:
                        try:
                            cid = int(e["consultant_id"])
                            tpid = int(e["target_project_id"])
                            rwh = float(e["recommended_weekly_hours"])
                        except (ValueError, KeyError):
                            continue

                        valid = True
                        # Must be underutilized
                        if cid not in gt["underutilized"]:
                            valid = False
                        # Target must be active
                        if tpid not in gt["projects"] or gt["projects"][tpid]["status"] != "active":
                            valid = False
                        # Hours cap
                        if rwh > 20.5 or rwh < 0:
                            valid = False

                        if valid:
                            n_valid += 1
                        proposed_totals[cid] = proposed_totals.get(cid, 0) + rwh

                    if n_entries > 0:
                        realloc_score = round(15 * (n_valid / n_entries))
                    else:
                        realloc_score = 0

                    criteria["reallocation_proposal"] = {
                        "passed": n_entries > 0 and n_valid == n_entries,
                        "score": realloc_score,
                        "max_score": 15,
                        "reason": "" if n_valid == n_entries else f"{n_valid}/{n_entries} entries valid"}
        else:
            criteria["reallocation_proposal"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "reallocation_proposal.csv not found"}

        # ── 6. Total margin improvement in response (10 pts) ──────────────────
        import re
        margin_match = re.search(
            r"Total Forecasted Weekly Margin Improvement:\s*\$?([\d,]+\.?\d*)", action, re.IGNORECASE)

        if margin_match:
            try:
                stated = float(margin_match.group(1).replace(",", ""))
                # Compute expected from the agent's own proposal
                agent_total = 0
                if os.path.exists(realloc_path):
                    with open(realloc_path, newline="") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            try:
                                agent_total += float(row["projected_weekly_margin_impact"])
                            except (ValueError, KeyError):
                                pass
                agent_total = round(agent_total, 2)
                if abs(stated - agent_total) < 1.0:
                    criteria["margin_improvement_stated"] = {
                        "passed": True, "score": 10, "max_score": 10}
                else:
                    criteria["margin_improvement_stated"] = {
                        "passed": False, "score": 0, "max_score": 10,
                        "reason": f"Stated ${stated}, expected ${agent_total} (sum of proposal)"}
            except ValueError:
                criteria["margin_improvement_stated"] = {
                    "passed": False, "score": 0, "max_score": 10,
                    "reason": "Could not parse margin value"}
        else:
            criteria["margin_improvement_stated"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "Pattern 'Total Forecasted Weekly Margin Improvement: $X.XX' not found"}

        # ── Aggregate ──────────────────────────────────────────────────────────
        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score if max_score > 0 else 0.0, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ── Verify ─────────────────────────────────────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        ws = self.workspace

        # ── 1. Gather all consultants via tool ─────────────────────────────────
        all_consultants = []
        page = 1
        while True:
            res = self.tools["list_consultants"](page=page, page_size=20)
            all_consultants.extend(res["consultants"])
            if page >= res["total_pages"]:
                break
            page += 1

        # ── 2. Gather all projects via tool ────────────────────────────────────
        all_projects = []
        page = 1
        while True:
            res = self.tools["list_projects"](page=page, page_size=20)
            all_projects.extend(res["projects"])
            if page >= res["total_pages"]:
                break
            page += 1

        # ── 3. Gather all timesheet entries via tool ───────────────────────────
        all_timesheets = []
        page = 1
        while True:
            res = self.tools["get_timesheet_entries"](page=page, page_size=50)
            all_timesheets.extend(res["entries"])
            if page >= res["total_pages"]:
                break
            page += 1

        # ── 4. Get client info for all unique clients ──────────────────────────
        client_ids = set(p["client_id"] for p in all_projects)
        clients = {}
        for cid in sorted(client_ids):
            clients[cid] = self.tools["get_client_info"](client_id=cid)

        # ── 5. Read workspace config files ─────────────────────────────────────
        tier_rates = _load_yaml(os.path.join(ws, "billing_rate_tiers.yaml"))
        util_cfg = _load_yaml(os.path.join(ws, "utilization_thresholds.yaml"))
        with open(os.path.join(ws, "overservicing_rules.json")) as f:
            oversvc = json.load(f)

        # Read capacity CSVs
        capacity = {}
        for fp in sorted(glob_mod.glob(os.path.join(ws, "consultant_capacity_*.csv"))):
            with open(fp, newline="") as f:
                for row in csv.DictReader(f):
                    cid = int(row["consultant_id"])
                    capacity[cid] = capacity.get(cid, 0) + int(row["target_hours"])

        # Read client rate cards
        client_rate_info = {}
        for fp in sorted(glob_mod.glob(os.path.join(ws, "client_rate_card_*.yaml"))):
            data = _load_yaml(fp)
            for k, v in data.items():
                client_rate_info[int(k)] = v

        # Read project requirements
        proj_reqs = {}
        for fp in sorted(glob_mod.glob(os.path.join(ws, "project_requirements_*.json"))):
            with open(fp) as f:
                for entry in json.load(f):
                    proj_reqs[entry["project_id"]] = entry

        # Build consultant lookup
        consultant_map = {c["consultant_id"]: c for c in all_consultants}
        project_map = {p["project_id"]: p for p in all_projects}
        analysis_weeks = util_cfg["analysis_period_weeks"]

        # ── Helper: billing rate ───────────────────────────────────────────────
        def get_rate(role, client_id):
            cr = client_rate_info.get(client_id, {})
            if cr.get("rate_type") == "custom" and cr.get("negotiated_rates"):
                return cr["negotiated_rates"].get(role, 0)
            tier = cr.get("base_tier") or clients.get(client_id, {}).get("billing_tier")
            if tier and tier in tier_rates:
                return tier_rates[tier].get(role, 0)
            return 0

        # ── 6. Compute utilization ─────────────────────────────────────────────
        hours_worked = {}
        for t in all_timesheets:
            hours_worked[t["consultant_id"]] = hours_worked.get(t["consultant_id"], 0) + t["hours"]

        util_under = util_cfg["underutilized_threshold"]
        util_over = util_cfg["overutilized_threshold"]

        utilization_rows = []
        for c in all_consultants:
            cid = c["consultant_id"]
            hw = round(hours_worked.get(cid, 0), 1)
            avail = round(float(capacity.get(cid, 40 * analysis_weeks)), 1)
            rate = round(hw / avail, 4) if avail > 0 else 0.0
            status = ("underutilized" if rate < util_under
                      else "overutilized" if rate > util_over
                      else "normal")
            utilization_rows.append({
                "consultant_id": cid,
                "consultant_name": c["name"],
                "role": c["role"],
                "department": c["department"],
                "total_hours_worked": hw,
                "total_available_hours": avail,
                "utilization_rate": rate,
                "status": status,
            })

        # Write utilization_report.csv
        with open(os.path.join(ws, "utilization_report.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "consultant_id", "consultant_name", "role", "department",
                "total_hours_worked", "total_available_hours", "utilization_rate", "status"])
            w.writeheader()
            for row in sorted(utilization_rows, key=lambda x: x["consultant_id"]):
                w.writerow(row)

        # ── 7. Compute profitability ───────────────────────────────────────────
        proj_cost = {}
        proj_rev = {}
        for t in all_timesheets:
            pid = t["project_id"]
            cid = t["consultant_id"]
            c = consultant_map[cid]
            p = project_map.get(pid)
            if not p:
                continue
            proj_cost[pid] = proj_cost.get(pid, 0) + t["hours"] * c["hourly_cost"]
            if t["is_billable"]:
                br = get_rate(c["role"], p["client_id"])
                proj_rev[pid] = proj_rev.get(pid, 0) + t["hours"] * br

        oversvc_threshold = oversvc["budget_overrun_threshold_pct"]

        profitability_rows = []
        for p in all_projects:
            pid = p["project_id"]
            tc = round(proj_cost.get(pid, 0), 2)
            tr = round(proj_rev.get(pid, 0), 2)
            budget = p["total_budget"]
            margin = round((tr - tc) / tr * 100, 2) if tr > 0 else 0.0
            flag = tc > budget * (1 + oversvc_threshold / 100)
            profitability_rows.append({
                "project_id": pid,
                "project_name": p["name"],
                "client_name": clients[p["client_id"]]["name"],
                "total_cost": tc,
                "total_revenue": tr,
                "total_budget": budget,
                "margin_pct": margin,
                "overservicing_flag": flag,
            })

        with open(os.path.join(ws, "profitability_analysis.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "project_id", "project_name", "client_name", "total_cost",
                "total_revenue", "total_budget", "margin_pct", "overservicing_flag"])
            w.writeheader()
            for row in sorted(profitability_rows, key=lambda x: x["project_id"]):
                w.writerow(row)

        # ── 8. Reallocation proposal ───────────────────────────────────────────
        underutilized_ids = [u["consultant_id"] for u in utilization_rows
                             if u["status"] == "underutilized"]
        overserviced_active_pids = sorted([
            r["project_id"] for r in profitability_rows
            if r["overservicing_flag"] and project_map[r["project_id"]]["status"] == "active"
        ])
        active_pids = sorted([p["project_id"] for p in all_projects if p["status"] == "active"])

        # Get skills for underutilized consultants
        consultant_skills = {}
        for cid in underutilized_ids:
            res = self.tools["get_consultant_skills"](consultant_id=cid)
            consultant_skills[cid] = {s["skill_name"]: s["proficiency_level"]
                                      for s in res["skills"]}

        # Current project assignments
        current_proj = {}
        for t in all_timesheets:
            current_proj.setdefault(t["consultant_id"], set()).add(t["project_id"])

        proposals = []
        proposed_hours = {}

        target_order = overserviced_active_pids + [
            pid for pid in active_pids if pid not in overserviced_active_pids]

        for cid in sorted(underutilized_ids):
            c = consultant_map[cid]
            u = next(r for r in utilization_rows if r["consultant_id"] == cid)
            c_skills = consultant_skills.get(cid, {})
            cur_count = len(current_proj.get(cid, set()))

            for pid in target_order:
                if cur_count >= 3:
                    break
                if pid in current_proj.get(cid, set()):
                    continue
                req = proj_reqs.get(pid, {})
                req_skills = req.get("required_skills", [])
                min_prof = req.get("min_proficiency_required", 3)
                matching = [s for s in req_skills
                            if s in c_skills and c_skills[s] >= min_prof]
                if not matching:
                    continue

                avail = u["total_available_hours"]
                prev = proposed_hours.get(cid, 0)
                max_by_util = ((util_over * avail -
                                u["total_hours_worked"] - prev * analysis_weeks)
                               / analysis_weeks)
                max_hrs = min(20.0, max(0, max_by_util))
                if max_hrs < 1.0:
                    continue

                rec = round(max_hrs, 1)
                br = get_rate(c["role"], project_map[pid]["client_id"])
                impact = round(rec * (br - c["hourly_cost"]), 2)

                proposals.append({
                    "consultant_id": cid,
                    "consultant_name": c["name"],
                    "target_project_id": pid,
                    "target_project_name": project_map[pid]["name"],
                    "recommended_weekly_hours": rec,
                    "matching_skills": ";".join(sorted(matching)),
                    "projected_weekly_margin_impact": impact,
                })
                proposed_hours[cid] = prev + rec
                cur_count += 1

        proposals.sort(key=lambda x: (x["consultant_id"], x["target_project_id"]))

        with open(os.path.join(ws, "reallocation_proposal.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "consultant_id", "consultant_name", "target_project_id",
                "target_project_name", "recommended_weekly_hours",
                "matching_skills", "projected_weekly_margin_impact"])
            w.writeheader()
            for row in proposals:
                w.writerow(row)

        total_improvement = round(sum(p["projected_weekly_margin_impact"] for p in proposals), 2)

        action = f"Total Forecasted Weekly Margin Improvement: ${total_improvement}"

        return self.step(action)
