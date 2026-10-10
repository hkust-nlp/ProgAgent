"""Environment for SLA breach detection task."""

import csv
import json
import os
import re
import sqlite3
from datetime import datetime
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
            "List tickets filtered by status. Returns paginated results "
            "with ticket_id, title, priority, status, sla_deadline, "
            "created_at, assigned_technician_id, and customer_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": [
                        "open", "in_progress", "pending",
                        "resolved", "closed",
                    ],
                    "description": "Filter by ticket status",
                },
                "priority": {
                    "type": "string",
                    "enum": ["P1", "P2", "P3", "P4"],
                    "description": "Optional: additionally filter by priority",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed (default 1)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page, max 20 (default 20)",
                },
            },
            "required": ["status"],
        },
    )
    def list_tickets(self, status: str, priority: str = None,
                     page: int = 1, page_size: int = 20) -> str:
        page_size = min(int(page_size), 20)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        sql = ("SELECT ticket_id, title, priority, status, sla_deadline, "
               "created_at, assigned_technician_id, customer_id "
               "FROM tickets WHERE status = ?")
        params: list = [status]
        if priority:
            sql += " AND priority = ?"
            params.append(priority)
        sql += " ORDER BY ticket_id"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start:start + page_size]
        return json.dumps({
            "tickets": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": start + page_size < total,
        })

    @tool(
        description=(
            "Get full details for a single ticket including description, "
            "category, and all timestamps."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "integer",
                    "description": "The ticket ID",
                },
            },
            "required": ["ticket_id"],
        },
    )
    def get_ticket_details(self, ticket_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM tickets WHERE ticket_id = ?",
            (int(ticket_id),),
        ).fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": "Ticket not found"})
        return json.dumps(dict(row))

    @tool(
        description="Get customer information including company name and service tier.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "integer",
                    "description": "The customer ID",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_customer_info(self, customer_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT customer_id, company_name, tier, contract_value, industry "
            "FROM customers WHERE customer_id = ?",
            (int(customer_id),),
        ).fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": "Customer not found"})
        return json.dumps(dict(row))

    @tool(
        description=(
            "Get the assignment history for a ticket. Returns all assignment "
            "records and total reassignment count."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "integer",
                    "description": "The ticket ID",
                },
            },
            "required": ["ticket_id"],
        },
    )
    def get_assignment_history(self, ticket_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM assignment_history WHERE ticket_id = ? "
            "ORDER BY assigned_at",
            (int(ticket_id),),
        ).fetchall()
        conn.close()
        records = [dict(r) for r in rows]
        return json.dumps({
            "ticket_id": int(ticket_id),
            "assignments": records,
            "total_reassignments": max(0, len(records) - 1),
        })

    @tool(
        description=(
            "Get escalation log entries for a ticket. Returns all "
            "escalation records and current escalation level."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "integer",
                    "description": "The ticket ID",
                },
            },
            "required": ["ticket_id"],
        },
    )
    def get_escalation_log(self, ticket_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM escalation_logs WHERE ticket_id = ? "
            "ORDER BY escalated_at",
            (int(ticket_id),),
        ).fetchall()
        conn.close()
        records = [dict(r) for r in rows]
        max_level = max((r["to_level"] for r in records), default=0)
        return json.dumps({
            "ticket_id": int(ticket_id),
            "logs": records,
            "current_escalation_level": max_level,
        })

    @tool(
        description="Get information about a specific technician.",
        parameters={
            "type": "object",
            "properties": {
                "tech_id": {
                    "type": "integer",
                    "description": "The technician ID",
                },
            },
            "required": ["tech_id"],
        },
    )
    def get_technician_info(self, tech_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT tech_id, name, skill_level, department_id, "
            "specialization, max_capacity FROM technicians "
            "WHERE tech_id = ?",
            (int(tech_id),),
        ).fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": "Technician not found"})
        return json.dumps(dict(row))

    @tool(
        description=(
            "List all technicians in a department. Returns tech_id, name, "
            "skill_level, specialization, and max_capacity."
        ),
        parameters={
            "type": "object",
            "properties": {
                "department_id": {
                    "type": "integer",
                    "description": "The department ID",
                },
            },
            "required": ["department_id"],
        },
    )
    def list_technicians_by_department(self, department_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT tech_id, name, skill_level, specialization, "
            "max_capacity FROM technicians WHERE department_id = ? "
            "ORDER BY tech_id",
            (int(department_id),),
        ).fetchall()
        conn.close()
        return json.dumps({
            "department_id": int(department_id),
            "technicians": [dict(r) for r in rows],
        })

    # ------------------------------------------------------------------
    # Helpers shared by step() and verify()
    # ------------------------------------------------------------------

    def _read_workspace_configs(self):
        """Read all configuration and data files from workspace."""
        with open(os.path.join(self.workspace, "sla_policy.yaml")) as f:
            sla_policy = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "escalation_rules.json")) as f:
            esc_rules = json.load(f)

        priority_weights = {}
        with open(os.path.join(self.workspace, "priority_weights.csv")) as f:
            for row in csv.DictReader(f):
                priority_weights[row["priority"]] = float(row["weight"])

        dept_managers: Dict[int, str] = {}
        with open(os.path.join(self.workspace, "department_contacts.md")) as f:
            for line in f:
                line = line.strip()
                if (not line or line.startswith("#")
                        or line.startswith("|--") or "Dept ID" in line):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 5:
                    try:
                        dept_managers[int(parts[1])] = parts[3]
                    except (ValueError, IndexError):
                        continue

        # ticket impact data
        impact_data: Dict[int, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if (fname.startswith("ticket_impact_batch_")
                    and fname.endswith(".json")):
                with open(os.path.join(self.workspace, fname)) as f:
                    for item in json.load(f):
                        impact_data[item["ticket_id"]] = item[
                            "business_impact_score"]

        # technician availability
        availability: Dict[int, Dict[str, Any]] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if (fname.startswith("availability_report_")
                    and fname.endswith(".csv")):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        availability[int(row["tech_id"])] = {
                            "name": row["name"],
                            "available_hours": float(row["available_hours"]),
                            "current_ticket_count": int(
                                row["current_ticket_count"]),
                            "max_concurrent": int(row["max_concurrent"]),
                        }

        return (sla_policy, esc_rules, priority_weights,
                dept_managers, impact_data, availability)

    def _compute_ground_truth(self):
        """Compute the expected intervention list from DB + workspace."""
        (sla_policy, esc_rules, priority_weights,
         dept_managers, impact_data, availability) = (
            self._read_workspace_configs())

        ref_date = datetime.strptime(
            sla_policy["reference_date"], "%Y-%m-%d %H:%M:%S")
        sla_hours_table = sla_policy["sla_hours"]
        warning_pct = sla_policy["warning_threshold_pct"]

        skill_val = esc_rules["skill_level_values"]
        skill_req = esc_rules["skill_requirements"]
        penalty_rate = esc_rules["reassignment_penalty_rate"]
        intervention_thr = esc_rules["intervention_threshold"]
        escalation_thr = esc_rules["escalation_threshold"]
        min_avail_hrs = esc_rules["min_available_hours"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        active = conn.execute(
            "SELECT * FROM tickets "
            "WHERE status IN ('open','in_progress') ORDER BY ticket_id"
        ).fetchall()

        intervention_list = []

        for ticket in active:
            tid = ticket["ticket_id"]
            priority = ticket["priority"]
            cust_id = ticket["customer_id"]
            tech_id = ticket["assigned_technician_id"]
            sla_deadline = datetime.strptime(
                ticket["sla_deadline"], "%Y-%m-%d %H:%M:%S")

            cust = conn.execute(
                "SELECT tier FROM customers WHERE customer_id = ?",
                (cust_id,)).fetchone()
            tier = cust["tier"]

            sla_hrs = sla_hours_table[priority][tier]
            hours_remaining = (
                (sla_deadline - ref_date).total_seconds() / 3600)
            warning_hrs = sla_hrs * warning_pct / 100.0

            if hours_remaining > warning_hrs:
                continue

            # reassignment count
            assign_cnt = conn.execute(
                "SELECT COUNT(*) c FROM assignment_history "
                "WHERE ticket_id = ?", (tid,)).fetchone()["c"]
            reassignment_count = max(0, assign_cnt - 1)

            # escalation level
            esc_row = conn.execute(
                "SELECT MAX(to_level) m FROM escalation_logs "
                "WHERE ticket_id = ?", (tid,)).fetchone()
            escalation_level = (esc_row["m"]
                                if esc_row["m"] is not None else 0)

            bis = impact_data.get(tid, 5.0)

            pw = priority_weights.get(priority, 1.0)
            time_urgency = max(
                0.1, min(2.0, 1.0 - hours_remaining / sla_hrs))
            risk_score = round(
                pw * time_urgency
                * (1 + penalty_rate * reassignment_count)
                * (bis / 10.0),
                2)

            if risk_score < intervention_thr:
                continue

            # recommendation
            tech = conn.execute(
                "SELECT * FROM technicians WHERE tech_id = ?",
                (tech_id,)).fetchone()
            dept_id = tech["department_id"]

            req_skill = skill_req.get(priority, "junior")
            req_val = skill_val.get(req_skill, 1)

            if risk_score >= escalation_thr:
                recommendation = "escalation"
                target = dept_managers.get(dept_id, "Unknown Manager")
            else:
                # try reassignment
                dept_techs = conn.execute(
                    "SELECT * FROM technicians "
                    "WHERE department_id = ? AND tech_id != ? "
                    "ORDER BY tech_id",
                    (dept_id, tech_id)).fetchall()

                best_name = None
                best_hrs = -1.0
                best_tid = float("inf")
                for dt in dept_techs:
                    dt_val = skill_val.get(dt["skill_level"], 1)
                    if dt_val < req_val:
                        continue
                    avail = availability.get(dt["tech_id"], {})
                    avail_hrs = avail.get("available_hours", 0.0)
                    if avail_hrs < min_avail_hrs:
                        continue
                    if (avail_hrs > best_hrs
                            or (avail_hrs == best_hrs
                                and dt["tech_id"] < best_tid)):
                        best_hrs = avail_hrs
                        best_tid = dt["tech_id"]
                        best_name = dt["name"]

                if best_name:
                    recommendation = "reassignment"
                    target = best_name
                else:
                    recommendation = "escalation"
                    target = dept_managers.get(dept_id, "Unknown Manager")

            intervention_list.append({
                "ticket_id": tid,
                "priority": priority,
                "customer_tier": tier,
                "sla_deadline": ticket["sla_deadline"],
                "hours_remaining": round(hours_remaining, 1),
                "reassignment_count": reassignment_count,
                "escalation_level": escalation_level,
                "business_impact_score": bis,
                "risk_score": risk_score,
                "current_technician_id": tech_id,
                "recommendation": recommendation,
                "target": target,
            })

        conn.close()

        intervention_list.sort(
            key=lambda x: (-x["risk_score"], x["hours_remaining"]))

        return intervention_list, len(active)

    # ------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------

    def step(
        self, action: str,
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
        gt_list, n_active = self._compute_ground_truth()
        gt_ids = {r["ticket_id"] for r in gt_list}

        criteria: Dict[str, Dict[str, Any]] = {}
        total_score = 0
        max_score = 0

        # --- C1: file exists (10 pts) ---
        csv_path = os.path.join(self.workspace, "intervention_list.csv")
        c1_pass = os.path.isfile(csv_path)
        criteria["file_exists"] = {
            "passed": c1_pass, "score": 10 if c1_pass else 0,
            "max_score": 10,
        }
        if not c1_pass:
            criteria["file_exists"]["reason"] = (
                "intervention_list.csv not found")

        # Try to read agent CSV
        agent_rows: List[Dict[str, str]] = []
        expected_cols = [
            "ticket_id", "priority", "customer_tier", "sla_deadline",
            "hours_remaining", "reassignment_count", "escalation_level",
            "business_impact_score", "risk_score",
            "current_technician_id", "recommendation", "target",
        ]
        if c1_pass:
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    agent_rows = list(reader)
            except Exception:
                agent_rows = []

        # --- C2: correct columns (10 pts) ---
        if agent_rows:
            actual_cols = list(agent_rows[0].keys())
            c2_pass = actual_cols == expected_cols
        else:
            actual_cols = []
            c2_pass = False
        criteria["correct_columns"] = {
            "passed": c2_pass, "score": 10 if c2_pass else 0,
            "max_score": 10,
        }
        if not c2_pass:
            criteria["correct_columns"]["reason"] = (
                f"Expected columns {expected_cols}, got {actual_cols}")

        # --- C3: correct ticket identification (25 pts) ---
        agent_ids = set()
        for r in agent_rows:
            try:
                agent_ids.add(int(r["ticket_id"]))
            except (KeyError, ValueError):
                pass
        if gt_ids:
            correct = len(agent_ids & gt_ids)
            extra = len(agent_ids - gt_ids)
            precision = correct / len(agent_ids) if agent_ids else 0
            recall = correct / len(gt_ids)
            f1 = (2 * precision * recall / (precision + recall)
                   if (precision + recall) > 0 else 0)
            c3_score = round(25 * f1)
        else:
            c3_score = 25 if len(agent_ids) == 0 else 0
        c3_pass = c3_score == 25
        criteria["ticket_identification"] = {
            "passed": c3_pass, "score": c3_score, "max_score": 25,
        }
        if not c3_pass:
            criteria["ticket_identification"]["reason"] = (
                f"Expected {len(gt_ids)} tickets "
                f"({sorted(gt_ids)}), got {len(agent_ids)} "
                f"({sorted(agent_ids)})")

        # --- C4: risk scores (20 pts) ---
        gt_scores = {r["ticket_id"]: r["risk_score"] for r in gt_list}
        if gt_ids and agent_rows:
            correct_scores = 0
            for r in agent_rows:
                try:
                    tid = int(r["ticket_id"])
                    agent_score = float(r["risk_score"])
                    if tid in gt_scores:
                        if abs(agent_score - gt_scores[tid]) <= 0.05:
                            correct_scores += 1
                except (KeyError, ValueError):
                    pass
            c4_score = round(20 * correct_scores / len(gt_ids))
        else:
            c4_score = 0
        c4_pass = c4_score == 20
        criteria["risk_scores"] = {
            "passed": c4_pass, "score": c4_score, "max_score": 20,
        }
        if not c4_pass:
            criteria["risk_scores"]["reason"] = (
                f"{correct_scores if gt_ids and agent_rows else 0}"
                f"/{len(gt_ids)} scores correct within tolerance")

        # --- C5: correct recommendations (15 pts) ---
        gt_recs = {r["ticket_id"]: r["recommendation"] for r in gt_list}
        if gt_ids and agent_rows:
            correct_recs = 0
            for r in agent_rows:
                try:
                    tid = int(r["ticket_id"])
                    if (tid in gt_recs
                            and r.get("recommendation") == gt_recs[tid]):
                        correct_recs += 1
                except (KeyError, ValueError):
                    pass
            c5_score = round(15 * correct_recs / len(gt_ids))
        else:
            c5_score = 0
        c5_pass = c5_score == 15
        criteria["recommendations"] = {
            "passed": c5_pass, "score": c5_score, "max_score": 15,
        }
        if not c5_pass:
            criteria["recommendations"]["reason"] = (
                f"{correct_recs if gt_ids and agent_rows else 0}"
                f"/{len(gt_ids)} recommendations correct")

        # --- C6: sort order (10 pts) ---
        if agent_rows and len(agent_rows) > 1:
            sorted_ok = True
            for idx in range(len(agent_rows) - 1):
                try:
                    s1 = float(agent_rows[idx]["risk_score"])
                    s2 = float(agent_rows[idx + 1]["risk_score"])
                    h1 = float(agent_rows[idx]["hours_remaining"])
                    h2 = float(agent_rows[idx + 1]["hours_remaining"])
                    if s1 < s2 or (s1 == s2 and h1 > h2):
                        sorted_ok = False
                        break
                except (KeyError, ValueError):
                    sorted_ok = False
                    break
            c6_score = 10 if sorted_ok else 0
        elif len(agent_rows) == 1:
            c6_score = 10
            sorted_ok = True
        else:
            c6_score = 0
            sorted_ok = False
        criteria["sort_order"] = {
            "passed": c6_score == 10, "score": c6_score, "max_score": 10,
        }
        if not sorted_ok:
            criteria["sort_order"]["reason"] = (
                "Rows not sorted by risk_score desc, "
                "hours_remaining asc")

        # --- C7: summary in response (10 pts) ---
        n_escalate_gt = sum(
            1 for r in gt_list if r["recommendation"] == "escalation")
        n_reassign_gt = sum(
            1 for r in gt_list if r["recommendation"] == "reassignment")
        top3_gt = [r["ticket_id"] for r in gt_list[:3]]

        # Count at-risk tickets (those that passed the warning threshold
        # but might not have passed intervention threshold)
        (sla_policy, esc_rules, priority_weights_map,
         dept_managers, impact_data, avail_data) = (
            self._read_workspace_configs())
        ref_date = datetime.strptime(
            sla_policy["reference_date"], "%Y-%m-%d %H:%M:%S")
        sla_hours_table = sla_policy["sla_hours"]
        warning_pct = sla_policy["warning_threshold_pct"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        active_all = conn.execute(
            "SELECT * FROM tickets "
            "WHERE status IN ('open','in_progress')").fetchall()
        n_at_risk = 0
        for t in active_all:
            cust = conn.execute(
                "SELECT tier FROM customers WHERE customer_id = ?",
                (t["customer_id"],)).fetchone()
            sla_hrs = sla_hours_table[t["priority"]][cust["tier"]]
            sla_dl = datetime.strptime(
                t["sla_deadline"], "%Y-%m-%d %H:%M:%S")
            hrs_rem = (sla_dl - ref_date).total_seconds() / 3600
            if hrs_rem <= sla_hrs * warning_pct / 100.0:
                n_at_risk += 1
        conn.close()

        c7_score = 0
        c7_details = []
        action_str = action if action else ""

        # check active count
        m = re.search(r"Active tickets examined:\s*(\d+)", action_str)
        if m and int(m.group(1)) == n_active:
            c7_score += 2
        else:
            c7_details.append(
                f"Active count: expected {n_active}")

        # check intervention count
        m = re.search(r"Interventions required:\s*(\d+)", action_str)
        if m and int(m.group(1)) == len(gt_list):
            c7_score += 2
        else:
            c7_details.append(
                f"Intervention count: expected {len(gt_list)}")

        # check escalation/reassignment breakdown
        m = re.search(
            r"Escalations:\s*(\d+),\s*Reassignments:\s*(\d+)",
            action_str)
        if (m and int(m.group(1)) == n_escalate_gt
                and int(m.group(2)) == n_reassign_gt):
            c7_score += 3
        else:
            c7_details.append(
                f"Breakdown: expected Escalations: {n_escalate_gt}, "
                f"Reassignments: {n_reassign_gt}")

        # check top 3 ticket IDs
        m = re.search(
            r"Top 3 risk ticket IDs:\s*([\d,\s]+)", action_str)
        if m:
            try:
                top3_agent = [
                    int(x.strip())
                    for x in m.group(1).split(",")[:3]]
                if top3_agent == top3_gt:
                    c7_score += 3
                else:
                    c7_details.append(
                        f"Top 3: expected {top3_gt}, got {top3_agent}")
            except ValueError:
                c7_details.append(f"Top 3: expected {top3_gt}")
        else:
            c7_details.append(f"Top 3: expected {top3_gt}")

        criteria["summary_accuracy"] = {
            "passed": c7_score == 10,
            "score": c7_score,
            "max_score": 10,
        }
        if c7_details:
            criteria["summary_accuracy"]["reason"] = "; ".join(c7_details)

        # aggregate
        for v in criteria.values():
            total_score += v["score"]
            max_score += v["max_score"]

        reward = total_score / max_score if max_score > 0 else 0.0

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

        This method proves end-to-end solvability. It must:
          - Use self.tools[name](**params) to gather data (no direct DB queries).
          - Read files from self.workspace as needed.
          - Write all required deliverables to self.workspace.
          - Construct the final action string.
          - Return self.step(action).
        """
        # ---- read workspace configs ----
        with open(os.path.join(self.workspace, "sla_policy.yaml")) as f:
            sla_policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "escalation_rules.json")) as f:
            esc_rules = json.load(f)

        priority_weights: Dict[str, float] = {}
        with open(os.path.join(self.workspace, "priority_weights.csv")) as f:
            for row in csv.DictReader(f):
                priority_weights[row["priority"]] = float(row["weight"])

        dept_managers: Dict[int, str] = {}
        with open(os.path.join(self.workspace, "department_contacts.md")) as f:
            for line in f:
                line = line.strip()
                if (not line or line.startswith("#")
                        or line.startswith("|--") or "Dept ID" in line):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 5:
                    try:
                        dept_managers[int(parts[1])] = parts[3]
                    except (ValueError, IndexError):
                        continue

        impact_data: Dict[int, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if (fname.startswith("ticket_impact_batch_")
                    and fname.endswith(".json")):
                with open(os.path.join(self.workspace, fname)) as f:
                    for item in json.load(f):
                        impact_data[item["ticket_id"]] = item[
                            "business_impact_score"]

        availability: Dict[int, Dict[str, Any]] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if (fname.startswith("availability_report_")
                    and fname.endswith(".csv")):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        availability[int(row["tech_id"])] = {
                            "name": row["name"],
                            "available_hours": float(
                                row["available_hours"]),
                        }

        ref_date = datetime.strptime(
            sla_policy["reference_date"], "%Y-%m-%d %H:%M:%S")
        sla_hours_table = sla_policy["sla_hours"]
        warning_pct = sla_policy["warning_threshold_pct"]
        skill_val = esc_rules["skill_level_values"]
        skill_req = esc_rules["skill_requirements"]
        penalty_rate = esc_rules["reassignment_penalty_rate"]
        intervention_thr = esc_rules["intervention_threshold"]
        escalation_thr = esc_rules["escalation_threshold"]
        min_avail_hrs = esc_rules["min_available_hours"]

        tool_call_count = 0

        # ---- gather active tickets via tools ----
        all_active = []
        for status in ["open", "in_progress"]:
            page = 1
            while True:
                result = json.loads(
                    self.tools["list_tickets"](
                        status=status, page=page, page_size=20))
                tool_call_count += 1
                all_active.extend(result["tickets"])
                if not result["has_more"]:
                    break
                page += 1

        # ---- get customer info (cache by customer_id) ----
        customer_cache: Dict[int, dict] = {}
        for t in all_active:
            cid = t["customer_id"]
            if cid not in customer_cache:
                customer_cache[cid] = json.loads(
                    self.tools["get_customer_info"](customer_id=cid))
                tool_call_count += 1

        # ---- identify at-risk tickets and compute intervention list ----
        intervention_list = []
        n_at_risk = 0

        for t in all_active:
            tid = t["ticket_id"]
            priority = t["priority"]
            cust = customer_cache[t["customer_id"]]
            tier = cust["tier"]
            sla_hrs = sla_hours_table[priority][tier]
            sla_deadline = datetime.strptime(
                t["sla_deadline"], "%Y-%m-%d %H:%M:%S")
            hours_remaining = (
                (sla_deadline - ref_date).total_seconds() / 3600)
            warning_hrs = sla_hrs * warning_pct / 100.0

            if hours_remaining > warning_hrs:
                continue

            n_at_risk += 1

            # get assignment history
            ah = json.loads(
                self.tools["get_assignment_history"](ticket_id=tid))
            tool_call_count += 1
            reassignment_count = ah["total_reassignments"]

            # get escalation log
            el = json.loads(
                self.tools["get_escalation_log"](ticket_id=tid))
            tool_call_count += 1
            escalation_level = el["current_escalation_level"]

            bis = impact_data.get(tid, 5.0)

            pw = priority_weights.get(priority, 1.0)
            time_urgency = max(
                0.1, min(2.0, 1.0 - hours_remaining / sla_hrs))
            risk_score = round(
                pw * time_urgency
                * (1 + penalty_rate * reassignment_count)
                * (bis / 10.0),
                2)

            if risk_score < intervention_thr:
                continue

            # determine recommendation
            tech_info = json.loads(
                self.tools["get_technician_info"](
                    tech_id=t["assigned_technician_id"]))
            tool_call_count += 1
            dept_id = tech_info["department_id"]

            req_skill = skill_req.get(priority, "junior")
            req_val = skill_val.get(req_skill, 1)

            if risk_score >= escalation_thr:
                recommendation = "escalation"
                target = dept_managers.get(dept_id, "Unknown Manager")
            else:
                dept_result = json.loads(
                    self.tools["list_technicians_by_department"](
                        department_id=dept_id))
                tool_call_count += 1
                dept_techs = dept_result["technicians"]

                best_name = None
                best_hrs = -1.0
                best_tid = float("inf")
                for dt in dept_techs:
                    if dt["tech_id"] == t["assigned_technician_id"]:
                        continue
                    dt_val = skill_val.get(dt["skill_level"], 1)
                    if dt_val < req_val:
                        continue
                    avail = availability.get(dt["tech_id"], {})
                    avail_hrs = avail.get("available_hours", 0.0)
                    if avail_hrs < min_avail_hrs:
                        continue
                    if (avail_hrs > best_hrs
                            or (avail_hrs == best_hrs
                                and dt["tech_id"] < best_tid)):
                        best_hrs = avail_hrs
                        best_tid = dt["tech_id"]
                        best_name = dt["name"]

                if best_name:
                    recommendation = "reassignment"
                    target = best_name
                else:
                    recommendation = "escalation"
                    target = dept_managers.get(
                        dept_id, "Unknown Manager")

            intervention_list.append({
                "ticket_id": tid,
                "priority": priority,
                "customer_tier": tier,
                "sla_deadline": t["sla_deadline"],
                "hours_remaining": round(hours_remaining, 1),
                "reassignment_count": reassignment_count,
                "escalation_level": escalation_level,
                "business_impact_score": bis,
                "risk_score": risk_score,
                "current_technician_id": t["assigned_technician_id"],
                "recommendation": recommendation,
                "target": target,
            })

        # sort
        intervention_list.sort(
            key=lambda x: (-x["risk_score"], x["hours_remaining"]))

        # ---- write CSV deliverable ----
        csv_path = os.path.join(self.workspace, "intervention_list.csv")
        fieldnames = [
            "ticket_id", "priority", "customer_tier", "sla_deadline",
            "hours_remaining", "reassignment_count", "escalation_level",
            "business_impact_score", "risk_score",
            "current_technician_id", "recommendation", "target",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in intervention_list:
                writer.writerow(row)

        # ---- build summary action ----
        n_escalate = sum(
            1 for r in intervention_list
            if r["recommendation"] == "escalation")
        n_reassign = sum(
            1 for r in intervention_list
            if r["recommendation"] == "reassignment")
        top3 = [r["ticket_id"] for r in intervention_list[:3]]

        action_lines = [
            f"Active tickets examined: {len(all_active)}",
            f"At-risk tickets: {n_at_risk}",
            f"Interventions required: {len(intervention_list)}",
            f"Escalations: {n_escalate}, Reassignments: {n_reassign}",
            f"Top 3 risk ticket IDs: {', '.join(str(x) for x in top3)}",
        ]
        action = "\n".join(action_lines)

        return self.step(action)
