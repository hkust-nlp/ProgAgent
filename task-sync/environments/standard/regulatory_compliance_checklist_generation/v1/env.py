"""
Environment for turbine overhaul regulatory compliance task.
Provides tools for querying turbines, emissions, permits, parts, technicians,
and overhaul tasks. Evaluates compliance checklist and gap report outputs.
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

    # ── Tool Methods ─────────────────────────────────────────────────────────

    @tool(
        description="List turbines filtered by status. Returns up to 20 results per page.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by turbine status (e.g. 'scheduled_overhaul', 'operational', 'maintenance', 'standby'). Leave empty for all.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
            },
            "required": [],
        },
    )
    def list_turbines(self, status: str = "", page: int = 1) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        page_size = 20
        offset = (max(1, page) - 1) * page_size
        if status:
            cur.execute(
                "SELECT turbine_id, model, site_id, location, rated_capacity_mw, installation_year, status, last_overhaul_date "
                "FROM turbines WHERE status = ? ORDER BY turbine_id LIMIT ? OFFSET ?",
                (status, page_size, offset),
            )
        else:
            cur.execute(
                "SELECT turbine_id, model, site_id, location, rated_capacity_mw, installation_year, status, last_overhaul_date "
                "FROM turbines ORDER BY turbine_id LIMIT ? OFFSET ?",
                (page_size, offset),
            )
        rows = [dict(r) for r in cur.fetchall()]
        # Get total count
        if status:
            cur.execute("SELECT COUNT(*) FROM turbines WHERE status = ?", (status,))
        else:
            cur.execute("SELECT COUNT(*) FROM turbines")
        total = cur.fetchone()[0]
        conn.close()
        return {
            "turbines": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get detailed information for a specific turbine by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "turbine_id": {
                    "type": "string",
                    "description": "The turbine ID (e.g. 'TRB-0001').",
                },
            },
            "required": ["turbine_id"],
        },
    )
    def get_turbine_info(self, turbine_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM turbines WHERE turbine_id = ?", (turbine_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Turbine {turbine_id} not found."}

    @tool(
        description="Get overhaul tasks assigned to a specific turbine.",
        parameters={
            "type": "object",
            "properties": {
                "turbine_id": {
                    "type": "string",
                    "description": "The turbine ID.",
                },
            },
            "required": ["turbine_id"],
        },
    )
    def get_overhaul_tasks(self, turbine_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT task_id, turbine_id, task_type, task_name, required_cert_type, "
            "required_cert_level, required_parts, estimated_hours, priority "
            "FROM overhaul_tasks WHERE turbine_id = ? ORDER BY task_id",
            (turbine_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"tasks": rows, "count": len(rows)}

    @tool(
        description="Query emission logs for a turbine, optionally filtered by pollutant. Returns up to 50 records per page.",
        parameters={
            "type": "object",
            "properties": {
                "turbine_id": {
                    "type": "string",
                    "description": "The turbine ID.",
                },
                "pollutant": {
                    "type": "string",
                    "description": "Optional pollutant filter (e.g. 'NOx', 'SO2').",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
            },
            "required": ["turbine_id"],
        },
    )
    def query_emission_logs(self, turbine_id: str, pollutant: str = "", page: int = 1) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        page_size = 50
        offset = (max(1, page) - 1) * page_size
        if pollutant:
            cur.execute(
                "SELECT log_id, turbine_id, pollutant, reading_value, unit, measurement_date "
                "FROM emission_logs WHERE turbine_id = ? AND pollutant = ? "
                "ORDER BY measurement_date DESC LIMIT ? OFFSET ?",
                (turbine_id, pollutant, page_size, offset),
            )
            cur2 = conn.cursor()
            cur2.execute(
                "SELECT COUNT(*) FROM emission_logs WHERE turbine_id = ? AND pollutant = ?",
                (turbine_id, pollutant),
            )
        else:
            cur.execute(
                "SELECT log_id, turbine_id, pollutant, reading_value, unit, measurement_date "
                "FROM emission_logs WHERE turbine_id = ? "
                "ORDER BY measurement_date DESC LIMIT ? OFFSET ?",
                (turbine_id, page_size, offset),
            )
            cur2 = conn.cursor()
            cur2.execute(
                "SELECT COUNT(*) FROM emission_logs WHERE turbine_id = ?",
                (turbine_id,),
            )
        rows = [dict(r) for r in cur.fetchall()]
        total = cur2.fetchone()[0]
        conn.close()
        return {
            "logs": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get environmental permits for a given site.",
        parameters={
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "The site ID (e.g. 'SITE-001').",
                },
            },
            "required": ["site_id"],
        },
    )
    def get_permits_for_site(self, site_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT permit_id, site_id, pollutant, limit_value, unit, "
            "effective_date, expiry_date, special_conditions "
            "FROM permits WHERE site_id = ? ORDER BY pollutant",
            (site_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"permits": rows, "count": len(rows)}

    @tool(
        description="Check spare part availability by part ID. Returns stock level and details.",
        parameters={
            "type": "object",
            "properties": {
                "part_id": {
                    "type": "string",
                    "description": "The spare part ID (e.g. 'SP-0001').",
                },
            },
            "required": ["part_id"],
        },
    )
    def check_part_availability(self, part_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT part_id, part_number, part_name, category, compatible_models, "
            "qty_on_hand, reorder_point, lead_time_days, unit_cost "
            "FROM spare_parts WHERE part_id = ?",
            (part_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Part {part_id} not found."}

    @tool(
        description="Search technicians by certification type and optionally minimum certification level. Returns up to 20 results per page.",
        parameters={
            "type": "object",
            "properties": {
                "cert_type": {
                    "type": "string",
                    "description": "Certification type to search for.",
                },
                "min_cert_level": {
                    "type": "string",
                    "description": "Minimum certification level ('Level-1', 'Level-2', 'Level-3'). Default: no minimum.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
            },
            "required": ["cert_type"],
        },
    )
    def search_technicians(self, cert_type: str, min_cert_level: str = "", page: int = 1) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        page_size = 20
        offset = (max(1, page) - 1) * page_size

        level_map = {"Level-1": 1, "Level-2": 2, "Level-3": 3}

        if min_cert_level and min_cert_level in level_map:
            min_val = level_map[min_cert_level]
            # Filter by cert_type and level >= min
            valid_levels = [k for k, v in level_map.items() if v >= min_val]
            placeholders = ",".join("?" * len(valid_levels))
            cur.execute(
                f"SELECT tech_id, name, cert_type, cert_level, cert_expiry, home_site_id, is_active "
                f"FROM technicians WHERE cert_type = ? AND cert_level IN ({placeholders}) "
                f"ORDER BY tech_id LIMIT ? OFFSET ?",
                (cert_type, *valid_levels, page_size, offset),
            )
            cur2 = conn.cursor()
            cur2.execute(
                f"SELECT COUNT(*) FROM technicians WHERE cert_type = ? AND cert_level IN ({placeholders})",
                (cert_type, *valid_levels),
            )
        else:
            cur.execute(
                "SELECT tech_id, name, cert_type, cert_level, cert_expiry, home_site_id, is_active "
                "FROM technicians WHERE cert_type = ? ORDER BY tech_id LIMIT ? OFFSET ?",
                (cert_type, page_size, offset),
            )
            cur2 = conn.cursor()
            cur2.execute(
                "SELECT COUNT(*) FROM technicians WHERE cert_type = ?",
                (cert_type,),
            )
        rows = [dict(r) for r in cur.fetchall()]
        total = cur2.fetchone()[0]
        conn.close()
        return {
            "technicians": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get detailed information about a specific technician.",
        parameters={
            "type": "object",
            "properties": {
                "tech_id": {
                    "type": "string",
                    "description": "The technician ID (e.g. 'TECH-0001').",
                },
            },
            "required": ["tech_id"],
        },
    )
    def get_technician_details(self, tech_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT tech_id, name, cert_type, cert_level, cert_expiry, home_site_id, is_active "
            "FROM technicians WHERE tech_id = ?",
            (tech_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Technician {tech_id} not found."}

    # ── Evaluation ───────────────────────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute the expected compliance checklist and gap report from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Load compliance rules
        rules_path = os.path.join(self.workspace, "compliance_rules.yaml")
        with open(rules_path) as f:
            rules = yaml.safe_load(f)

        policy_path = os.path.join(self.workspace, "overhaul_policy.json")
        with open(policy_path) as f:
            policy = json.load(f)

        em_rules = rules["emission_compliance"]
        parts_rules = rules["parts_compliance"]
        tech_rules = rules["technician_compliance"]

        ref_date = datetime.strptime(em_rules["reference_date"], "%Y-%m-%d")
        window_start = ref_date - timedelta(days=em_rules["evaluation_window_days"])
        cert_valid_through = tech_rules["cert_must_be_valid_through"]
        max_exc = em_rules["max_exceedances_before_flag"]

        level_map = {"Level-1": 1, "Level-2": 2, "Level-3": 3}

        # Get scheduled_overhaul turbines
        cur.execute(
            "SELECT turbine_id, model, site_id FROM turbines WHERE status = 'scheduled_overhaul' ORDER BY turbine_id"
        )
        scheduled = [dict(r) for r in cur.fetchall()]

        # Load pending orders from workspace
        pending_orders = {}  # part_id -> total qty incoming
        for fname in os.listdir(self.workspace):
            if fname.startswith("pending_orders_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    lines = f.readlines()
                current_part = None
                for line in lines:
                    line = line.strip()
                    if line.startswith("PART_ID:"):
                        current_part = line.split(":", 1)[1].strip()
                    elif line.startswith("Qty Incoming:") and current_part:
                        qty = int(line.split(":", 1)[1].strip())
                        pending_orders[current_part] = pending_orders.get(current_part, 0) + qty
                        current_part = None

        # Load technician schedules from workspace
        tech_schedules = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("technician_schedule_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                tech_schedules.update(data)

        checklist = []
        gaps = []

        for turb in scheduled:
            tid = turb["turbine_id"]
            model = turb["model"]
            site_id = turb["site_id"]

            # ── Emission compliance ──────────────────────────────────────
            # Get permits for site
            cur.execute(
                "SELECT pollutant, limit_value FROM permits WHERE site_id = ?", (site_id,)
            )
            permit_limits = {}
            for r in cur.fetchall():
                poll = r["pollutant"]
                if poll not in permit_limits or r["limit_value"] < permit_limits[poll]:
                    permit_limits[poll] = r["limit_value"]

            # Get emission logs within window
            cur.execute(
                "SELECT pollutant, reading_value, measurement_date FROM emission_logs "
                "WHERE turbine_id = ? AND measurement_date >= ? AND measurement_date <= ?",
                (tid, window_start.strftime("%Y-%m-%d"), ref_date.strftime("%Y-%m-%d")),
            )
            logs = cur.fetchall()

            exceedances_by_pollutant = {}
            for log in logs:
                poll = log["pollutant"]
                if poll in permit_limits:
                    if log["reading_value"] > permit_limits[poll]:
                        exceedances_by_pollutant.setdefault(poll, []).append(log["reading_value"])

            emission_compliant = True
            for poll, exc_values in exceedances_by_pollutant.items():
                if len(exc_values) >= max_exc:
                    emission_compliant = False
                    # Calculate severity
                    limit = permit_limits[poll]
                    max_exc_val = max(exc_values)
                    pct = ((max_exc_val - limit) / limit) * 100
                    if pct >= 50:
                        sev = "HIGH"
                    elif pct >= 20:
                        sev = "MEDIUM"
                    else:
                        sev = "LOW"
                    gaps.append({
                        "turbine_id": tid,
                        "task_id": "N/A",
                        "gap_type": "EMISSION",
                        "detail": f"{poll} exceeded limit {limit} with {len(exc_values)} readings above threshold (max {max_exc_val})",
                        "severity": sev,
                    })

            emission_status = "COMPLIANT" if emission_compliant else "NON-COMPLIANT"

            # ── Parts compliance ─────────────────────────────────────────
            cur.execute(
                "SELECT task_id, required_parts, priority, required_cert_type, required_cert_level "
                "FROM overhaul_tasks WHERE turbine_id = ?",
                (tid,),
            )
            tasks = [dict(r) for r in cur.fetchall()]

            parts_ok = True
            for task in tasks:
                req_parts = json.loads(task["required_parts"])
                for pid in req_parts:
                    cur.execute(
                        "SELECT qty_on_hand, reorder_point, lead_time_days FROM spare_parts WHERE part_id = ?",
                        (pid,),
                    )
                    prow = cur.fetchone()
                    if prow:
                        total_avail = prow["qty_on_hand"] + pending_orders.get(pid, 0)
                        needed = int(parts_rules["min_stock_multiplier"])
                        if total_avail < needed:
                            parts_ok = False
                            if prow["qty_on_hand"] == 0 and pending_orders.get(pid, 0) == 0:
                                sev = "HIGH"
                            elif total_avail < prow["reorder_point"]:
                                sev = "MEDIUM"
                            else:
                                sev = "LOW"
                            gaps.append({
                                "turbine_id": tid,
                                "task_id": task["task_id"],
                                "gap_type": "PARTS",
                                "detail": f"Part {pid} has {prow['qty_on_hand']} on hand + {pending_orders.get(pid, 0)} incoming, need {needed}",
                                "severity": sev,
                            })

            parts_status = "AVAILABLE" if parts_ok else "SHORTAGE"

            # ── Technician compliance ────────────────────────────────────
            tech_ok = True
            for task in tasks:
                req_cert = task["required_cert_type"]
                req_level = task["required_cert_level"]
                req_level_val = level_map.get(req_level, 1)

                # Find qualifying technicians
                cur.execute(
                    "SELECT tech_id, cert_level, cert_expiry, is_active FROM technicians WHERE cert_type = ?",
                    (req_cert,),
                )
                candidates = cur.fetchall()

                found = False
                for cand in candidates:
                    cand_level = level_map.get(cand["cert_level"], 0)
                    if cand_level < req_level_val:
                        continue
                    if cand["is_active"] != 1:
                        continue
                    if cand["cert_expiry"] < cert_valid_through:
                        continue
                    # Check availability from schedule
                    sched = tech_schedules.get(cand["tech_id"])
                    if sched and sched.get("available_windows"):
                        found = True
                        break

                if not found:
                    tech_ok = False
                    priority = task["priority"]
                    if priority == "HIGH":
                        sev = "HIGH"
                    elif priority == "MEDIUM":
                        sev = "MEDIUM"
                    else:
                        sev = "LOW"
                    gaps.append({
                        "turbine_id": tid,
                        "task_id": task["task_id"],
                        "gap_type": "TECHNICIAN",
                        "detail": f"No qualified {req_cert} at {req_level} or above available",
                        "severity": sev,
                    })

            tech_status = "COVERED" if tech_ok else "GAP"

            overall = "COMPLIANT" if (
                emission_status == "COMPLIANT"
                and parts_status == "AVAILABLE"
                and tech_status == "COVERED"
            ) else "NON-COMPLIANT"

            checklist.append({
                "turbine_id": tid,
                "model": model,
                "site_id": site_id,
                "emission_status": emission_status,
                "parts_status": parts_status,
                "technician_status": tech_status,
                "overall_status": overall,
            })

        # Sort checklist by turbine_id
        checklist.sort(key=lambda x: x["turbine_id"])

        # Sort gaps by severity desc, then turbine_id, then task_id
        sev_key = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}
        gaps.sort(key=lambda x: (sev_key.get(x["severity"], 99), x["turbine_id"], x["task_id"]))

        conn.close()
        return checklist, gaps

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
        expected_checklist, expected_gaps = self._compute_ground_truth()

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # Load policy for column names
        policy_path = os.path.join(self.workspace, "overhaul_policy.json")
        with open(policy_path) as f:
            policy = json.load(f)

        # ── Criterion 1: compliance_checklist.csv exists and has correct structure (15 pts) ──
        c1_max = 15
        max_score += c1_max
        checklist_path = os.path.join(self.workspace, "compliance_checklist.csv")
        checklist_ok = False
        agent_checklist = []
        if os.path.exists(checklist_path):
            try:
                with open(checklist_path) as f:
                    reader = csv.DictReader(f)
                    agent_checklist = list(reader)
                expected_cols = set(policy["checklist_columns"])
                actual_cols = set(reader.fieldnames) if reader.fieldnames else set()
                if expected_cols.issubset(actual_cols) and len(agent_checklist) > 0:
                    checklist_ok = True
                    eval_criteria["checklist_structure"] = {
                        "passed": True, "score": c1_max, "max_score": c1_max,
                    }
                    total_score += c1_max
                else:
                    eval_criteria["checklist_structure"] = {
                        "passed": False, "score": 0, "max_score": c1_max,
                        "reason": f"Missing columns. Expected {expected_cols}, got {actual_cols}",
                    }
            except Exception as e:
                eval_criteria["checklist_structure"] = {
                    "passed": False, "score": 0, "max_score": c1_max,
                    "reason": f"Error reading CSV: {str(e)}",
                }
        else:
            eval_criteria["checklist_structure"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "compliance_checklist.csv not found in workspace",
            }

        # ── Criterion 2: Correct set of turbines in checklist (15 pts) ──
        c2_max = 15
        max_score += c2_max
        expected_ids = {r["turbine_id"] for r in expected_checklist}
        agent_ids = {r.get("turbine_id", "") for r in agent_checklist}
        if expected_ids == agent_ids:
            eval_criteria["checklist_turbine_coverage"] = {
                "passed": True, "score": c2_max, "max_score": c2_max,
            }
            total_score += c2_max
        else:
            missing = expected_ids - agent_ids
            extra = agent_ids - expected_ids
            partial = max(0, c2_max - len(missing) * 2 - len(extra))
            eval_criteria["checklist_turbine_coverage"] = {
                "passed": False, "score": partial, "max_score": c2_max,
                "reason": f"Missing: {missing}, Extra: {extra}",
            }
            total_score += partial

        # ── Criterion 3: Emission status accuracy (15 pts) ──
        c3_max = 15
        max_score += c3_max
        expected_em = {r["turbine_id"]: r["emission_status"] for r in expected_checklist}
        correct_em = 0
        for row in agent_checklist:
            tid = row.get("turbine_id", "")
            if tid in expected_em and row.get("emission_status", "") == expected_em[tid]:
                correct_em += 1
        if expected_em:
            em_score = round(c3_max * correct_em / len(expected_em), 1)
        else:
            em_score = c3_max
        eval_criteria["emission_status_accuracy"] = {
            "passed": em_score == c3_max, "score": em_score, "max_score": c3_max,
            **({} if em_score == c3_max else {"reason": f"{correct_em}/{len(expected_em)} correct"}),
        }
        total_score += em_score

        # ── Criterion 4: Parts status accuracy (15 pts) ──
        c4_max = 15
        max_score += c4_max
        expected_ps = {r["turbine_id"]: r["parts_status"] for r in expected_checklist}
        correct_ps = 0
        for row in agent_checklist:
            tid = row.get("turbine_id", "")
            if tid in expected_ps and row.get("parts_status", "") == expected_ps[tid]:
                correct_ps += 1
        if expected_ps:
            ps_score = round(c4_max * correct_ps / len(expected_ps), 1)
        else:
            ps_score = c4_max
        eval_criteria["parts_status_accuracy"] = {
            "passed": ps_score == c4_max, "score": ps_score, "max_score": c4_max,
            **({} if ps_score == c4_max else {"reason": f"{correct_ps}/{len(expected_ps)} correct"}),
        }
        total_score += ps_score

        # ── Criterion 5: Technician status accuracy (15 pts) ──
        c5_max = 15
        max_score += c5_max
        expected_ts = {r["turbine_id"]: r["technician_status"] for r in expected_checklist}
        correct_ts = 0
        for row in agent_checklist:
            tid = row.get("turbine_id", "")
            if tid in expected_ts and row.get("technician_status", "") == expected_ts[tid]:
                correct_ts += 1
        if expected_ts:
            ts_score = round(c5_max * correct_ts / len(expected_ts), 1)
        else:
            ts_score = c5_max
        eval_criteria["technician_status_accuracy"] = {
            "passed": ts_score == c5_max, "score": ts_score, "max_score": c5_max,
            **({} if ts_score == c5_max else {"reason": f"{correct_ts}/{len(expected_ts)} correct"}),
        }
        total_score += ts_score

        # ── Criterion 6: gap_report.csv exists and structure (10 pts) ──
        c6_max = 10
        max_score += c6_max
        gap_path = os.path.join(self.workspace, "gap_report.csv")
        agent_gaps = []
        if os.path.exists(gap_path):
            try:
                with open(gap_path) as f:
                    reader = csv.DictReader(f)
                    agent_gaps = list(reader)
                expected_gcols = set(policy["gap_report_columns"])
                actual_gcols = set(reader.fieldnames) if reader.fieldnames else set()
                if expected_gcols.issubset(actual_gcols):
                    eval_criteria["gap_report_structure"] = {
                        "passed": True, "score": c6_max, "max_score": c6_max,
                    }
                    total_score += c6_max
                else:
                    eval_criteria["gap_report_structure"] = {
                        "passed": False, "score": 0, "max_score": c6_max,
                        "reason": f"Missing columns. Expected {expected_gcols}, got {actual_gcols}",
                    }
            except Exception as e:
                eval_criteria["gap_report_structure"] = {
                    "passed": False, "score": 0, "max_score": c6_max,
                    "reason": f"Error reading gap CSV: {str(e)}",
                }
        else:
            eval_criteria["gap_report_structure"] = {
                "passed": False, "score": 0, "max_score": c6_max,
                "reason": "gap_report.csv not found in workspace",
            }

        # ── Criterion 7: Gap report content accuracy (15 pts) ──
        c7_max = 15
        max_score += c7_max
        # Match on (turbine_id, task_id, gap_type)
        expected_gap_keys = {
            (g["turbine_id"], g["task_id"], g["gap_type"]) for g in expected_gaps
        }
        agent_gap_keys = {
            (g.get("turbine_id", ""), g.get("task_id", ""), g.get("gap_type", ""))
            for g in agent_gaps
        }
        if expected_gap_keys:
            matched = expected_gap_keys & agent_gap_keys
            gap_score = round(c7_max * len(matched) / len(expected_gap_keys), 1)
        else:
            # No gaps expected — agent should also have none
            gap_score = c7_max if len(agent_gaps) == 0 else 0
        eval_criteria["gap_report_content"] = {
            "passed": gap_score == c7_max, "score": gap_score, "max_score": c7_max,
            **({} if gap_score == c7_max else {
                "reason": f"Matched {len(expected_gap_keys & agent_gap_keys)}/{len(expected_gap_keys)} gaps"
            }),
        }
        total_score += gap_score

        total_score = round(total_score, 1)
        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0

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

        tool_calls = 0

        # ── Read workspace config files ──────────────────────────────────
        rules_path = os.path.join(self.workspace, "compliance_rules.yaml")
        with open(rules_path) as f:
            rules = yaml.safe_load(f)

        policy_path = os.path.join(self.workspace, "overhaul_policy.json")
        with open(policy_path) as f:
            policy = json.load(f)

        cert_req_path = os.path.join(self.workspace, "certification_requirements.md")
        with open(cert_req_path) as f:
            cert_req_text = f.read()

        em_rules = rules["emission_compliance"]
        parts_rules = rules["parts_compliance"]
        tech_rules = rules["technician_compliance"]
        ref_date = datetime.strptime(em_rules["reference_date"], "%Y-%m-%d")
        window_start = ref_date - timedelta(days=em_rules["evaluation_window_days"])
        cert_valid_through = tech_rules["cert_must_be_valid_through"]
        max_exc = em_rules["max_exceedances_before_flag"]
        level_map = {"Level-1": 1, "Level-2": 2, "Level-3": 3}

        # ── Read pending orders from workspace ───────────────────────────
        pending_orders = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("pending_orders_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    lines = f.readlines()
                current_part = None
                for line in lines:
                    line = line.strip()
                    if line.startswith("PART_ID:"):
                        current_part = line.split(":", 1)[1].strip()
                    elif line.startswith("Qty Incoming:") and current_part:
                        qty = int(line.split(":", 1)[1].strip())
                        pending_orders[current_part] = pending_orders.get(current_part, 0) + qty
                        current_part = None

        # ── Read technician schedules from workspace ─────────────────────
        tech_schedules = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("technician_schedule_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                tech_schedules.update(data)

        # ── Step 1: Get all scheduled_overhaul turbines via tool ─────────
        all_turbines = []
        page = 1
        while True:
            result = self.tools["list_turbines"](status="scheduled_overhaul", page=page)
            tool_calls += 1
            all_turbines.extend(result["turbines"])
            if page >= result["total_pages"]:
                break
            page += 1

        checklist = []
        gaps = []

        for turb in all_turbines:
            tid = turb["turbine_id"]
            model = turb["model"]
            site_id = turb["site_id"]

            # ── Emission check: get permits for site ─────────────────────
            permits_result = self.tools["get_permits_for_site"](site_id=site_id)
            tool_calls += 1
            permit_limits = {}
            for p in permits_result["permits"]:
                poll = p["pollutant"]
                if poll not in permit_limits or p["limit_value"] < permit_limits[poll]:
                    permit_limits[poll] = p["limit_value"]

            # Get emission logs for this turbine
            all_logs = []
            pg = 1
            while True:
                logs_result = self.tools["query_emission_logs"](turbine_id=tid, page=pg)
                tool_calls += 1
                all_logs.extend(logs_result["logs"])
                if pg >= logs_result["total_pages"]:
                    break
                pg += 1

            # Filter to window and check exceedances
            exceedances_by_pollutant = {}
            for log in all_logs:
                if window_start.strftime("%Y-%m-%d") <= log["measurement_date"] <= ref_date.strftime("%Y-%m-%d"):
                    poll = log["pollutant"]
                    if poll in permit_limits and log["reading_value"] > permit_limits[poll]:
                        exceedances_by_pollutant.setdefault(poll, []).append(log["reading_value"])

            emission_compliant = True
            for poll, exc_vals in exceedances_by_pollutant.items():
                if len(exc_vals) >= max_exc:
                    emission_compliant = False
                    limit = permit_limits[poll]
                    max_val = max(exc_vals)
                    pct = ((max_val - limit) / limit) * 100
                    if pct >= 50:
                        sev = "HIGH"
                    elif pct >= 20:
                        sev = "MEDIUM"
                    else:
                        sev = "LOW"
                    gaps.append({
                        "turbine_id": tid,
                        "task_id": "N/A",
                        "gap_type": "EMISSION",
                        "detail": f"{poll} exceeded limit {limit} with {len(exc_vals)} readings above threshold (max {max_val})",
                        "severity": sev,
                    })

            emission_status = "COMPLIANT" if emission_compliant else "NON-COMPLIANT"

            # ── Parts check: get overhaul tasks ──────────────────────────
            tasks_result = self.tools["get_overhaul_tasks"](turbine_id=tid)
            tool_calls += 1
            tasks = tasks_result["tasks"]

            parts_ok = True
            for task in tasks:
                req_parts = json.loads(task["required_parts"])
                for pid in req_parts:
                    part_info = self.tools["check_part_availability"](part_id=pid)
                    tool_calls += 1
                    if "error" not in part_info:
                        total_avail = part_info["qty_on_hand"] + pending_orders.get(pid, 0)
                        needed = int(parts_rules["min_stock_multiplier"])
                        if total_avail < needed:
                            parts_ok = False
                            if part_info["qty_on_hand"] == 0 and pending_orders.get(pid, 0) == 0:
                                sev = "HIGH"
                            elif total_avail < part_info["reorder_point"]:
                                sev = "MEDIUM"
                            else:
                                sev = "LOW"
                            gaps.append({
                                "turbine_id": tid,
                                "task_id": task["task_id"],
                                "gap_type": "PARTS",
                                "detail": f"Part {pid} has {part_info['qty_on_hand']} on hand + {pending_orders.get(pid, 0)} incoming, need {needed}",
                                "severity": sev,
                            })

            parts_status = "AVAILABLE" if parts_ok else "SHORTAGE"

            # ── Technician check ─────────────────────────────────────────
            tech_ok = True
            for task in tasks:
                req_cert = task["required_cert_type"]
                req_level = task["required_cert_level"]
                req_level_val = level_map.get(req_level, 1)

                # Search for technicians with this cert type
                all_techs = []
                pg = 1
                while True:
                    t_result = self.tools["search_technicians"](cert_type=req_cert, min_cert_level=req_level, page=pg)
                    tool_calls += 1
                    all_techs.extend(t_result["technicians"])
                    if pg >= t_result["total_pages"]:
                        break
                    pg += 1

                found = False
                for tech in all_techs:
                    if tech["is_active"] != 1:
                        continue
                    if tech["cert_expiry"] < cert_valid_through:
                        continue
                    sched = tech_schedules.get(tech["tech_id"])
                    if sched and sched.get("available_windows"):
                        found = True
                        break

                if not found:
                    tech_ok = False
                    priority = task["priority"]
                    if priority == "HIGH":
                        sev = "HIGH"
                    elif priority == "MEDIUM":
                        sev = "MEDIUM"
                    else:
                        sev = "LOW"
                    gaps.append({
                        "turbine_id": tid,
                        "task_id": task["task_id"],
                        "gap_type": "TECHNICIAN",
                        "detail": f"No qualified {req_cert} at {req_level} or above available",
                        "severity": sev,
                    })

            tech_status = "COVERED" if tech_ok else "GAP"

            overall = "COMPLIANT" if (
                emission_status == "COMPLIANT"
                and parts_status == "AVAILABLE"
                and tech_status == "COVERED"
            ) else "NON-COMPLIANT"

            checklist.append({
                "turbine_id": tid,
                "model": model,
                "site_id": site_id,
                "emission_status": emission_status,
                "parts_status": parts_status,
                "technician_status": tech_status,
                "overall_status": overall,
            })

        # Sort
        checklist.sort(key=lambda x: x["turbine_id"])
        sev_key = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}
        gaps.sort(key=lambda x: (sev_key.get(x["severity"], 99), x["turbine_id"], x["task_id"]))

        # ── Write deliverables ───────────────────────────────────────────
        checklist_path = os.path.join(self.workspace, "compliance_checklist.csv")
        with open(checklist_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=policy["checklist_columns"])
            writer.writeheader()
            writer.writerows(checklist)

        gap_path = os.path.join(self.workspace, "gap_report.csv")
        with open(gap_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=policy["gap_report_columns"])
            writer.writeheader()
            writer.writerows(gaps)

        # ── Build action string ──────────────────────────────────────────
        n_compliant = sum(1 for c in checklist if c["overall_status"] == "COMPLIANT")
        n_total = len(checklist)
        action = (
            f"Compliance analysis complete for {n_total} turbines scheduled for overhaul. "
            f"{n_compliant} are fully COMPLIANT, {n_total - n_compliant} are NON-COMPLIANT. "
            f"Found {len(gaps)} compliance gaps total. "
            f"Results written to compliance_checklist.csv and gap_report.csv."
        )

        print(f"[verify] Total tool calls: {tool_calls}")
        assert tool_calls >= 15, f"Tool calls ({tool_calls}) below minimum 15"

        return self.step(action)
