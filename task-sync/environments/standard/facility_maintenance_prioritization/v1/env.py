#!/usr/bin/env python3
"""Environment for branch facility maintenance prioritization task."""

import csv
import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Tuple


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

    # ── Tool Methods ──────────────────────────────────────────────────

    @tool(
        description="List all branch IDs and names. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Each page returns up to 10 branches.",
                },
            },
            "required": ["page"],
        },
    )
    def list_branches(self, page: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        offset = (page - 1) * 10
        c.execute(
            "SELECT branch_id, branch_name, branch_tier, region FROM branches ORDER BY branch_id LIMIT 10 OFFSET ?",
            (offset,),
        )
        rows = c.fetchall()
        c.execute("SELECT COUNT(*) FROM branches")
        total = c.fetchone()[0]
        conn.close()
        return {
            "branches": [
                {"branch_id": r[0], "branch_name": r[1], "branch_tier": r[2], "region": r[3]}
                for r in rows
            ],
            "page": page,
            "total_branches": total,
            "total_pages": (total + 9) // 10,
        }

    @tool(
        description="Get detailed information for a specific branch.",
        parameters={
            "type": "object",
            "properties": {
                "branch_id": {
                    "type": "string",
                    "description": "The branch ID, e.g. 'BR-0001'.",
                },
            },
            "required": ["branch_id"],
        },
    )
    def get_branch_details(self, branch_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM branches WHERE branch_id = ?", (branch_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return {"error": f"Branch {branch_id} not found."}
        cols = [
            "branch_id", "branch_name", "address", "city", "state",
            "region", "square_footage", "year_built", "last_inspection_date", "branch_tier",
        ]
        return dict(zip(cols, row))

    @tool(
        description="List equipment for a given branch. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "branch_id": {
                    "type": "string",
                    "description": "The branch ID.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Each page returns up to 10 items.",
                },
            },
            "required": ["branch_id", "page"],
        },
    )
    def list_equipment_by_branch(self, branch_id: str, page: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        offset = (page - 1) * 10
        c.execute(
            "SELECT equipment_id, equipment_type, status, install_date FROM equipment WHERE branch_id = ? ORDER BY equipment_id LIMIT 10 OFFSET ?",
            (branch_id, offset),
        )
        rows = c.fetchall()
        c.execute("SELECT COUNT(*) FROM equipment WHERE branch_id = ?", (branch_id,))
        total = c.fetchone()[0]
        conn.close()
        return {
            "equipment": [
                {"equipment_id": r[0], "equipment_type": r[1], "status": r[2], "install_date": r[3]}
                for r in rows
            ],
            "branch_id": branch_id,
            "page": page,
            "total_equipment": total,
            "total_pages": (total + 9) // 10,
        }

    @tool(
        description="Get full details for a specific piece of equipment.",
        parameters={
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "The equipment ID, e.g. 'EQ-00001'.",
                },
            },
            "required": ["equipment_id"],
        },
    )
    def get_equipment_details(self, equipment_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM equipment WHERE equipment_id = ?", (equipment_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return {"error": f"Equipment {equipment_id} not found."}
        cols = [
            "equipment_id", "branch_id", "equipment_type", "manufacturer",
            "model_number", "install_date", "warranty_expiry", "status",
        ]
        return dict(zip(cols, row))

    @tool(
        description="Get service logs for a specific piece of equipment. Returns paginated results ordered by service date descending.",
        parameters={
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "The equipment ID.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Each page returns up to 10 logs.",
                },
            },
            "required": ["equipment_id", "page"],
        },
    )
    def get_service_logs(self, equipment_id: str, page: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        offset = (page - 1) * 10
        c.execute(
            "SELECT * FROM service_logs WHERE equipment_id = ? ORDER BY service_date DESC LIMIT 10 OFFSET ?",
            (equipment_id, offset),
        )
        rows = c.fetchall()
        c.execute("SELECT COUNT(*) FROM service_logs WHERE equipment_id = ?", (equipment_id,))
        total = c.fetchone()[0]
        conn.close()
        cols = [
            "log_id", "equipment_id", "service_date", "service_type",
            "technician_name", "description", "parts_replaced", "cost",
            "downtime_hours", "follow_up_needed",
        ]
        return {
            "logs": [dict(zip(cols, r)) for r in rows],
            "equipment_id": equipment_id,
            "page": page,
            "total_logs": total,
            "total_pages": (total + 9) // 10,
        }

    @tool(
        description="Get complaint tickets for a specific branch, filtered by status. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "branch_id": {
                    "type": "string",
                    "description": "The branch ID.",
                },
                "status_filter": {
                    "type": "string",
                    "enum": ["Open", "In Progress", "Resolved", "Closed", "All"],
                    "description": "Filter by ticket status. Use 'All' to get all statuses.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Each page returns up to 10 tickets.",
                },
            },
            "required": ["branch_id", "status_filter", "page"],
        },
    )
    def get_complaint_tickets(self, branch_id: str, status_filter: str, page: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        offset = (page - 1) * 10
        if status_filter == "All":
            c.execute(
                "SELECT * FROM complaint_tickets WHERE branch_id = ? ORDER BY complaint_date DESC LIMIT 10 OFFSET ?",
                (branch_id, offset),
            )
            c2 = conn.cursor()
            c2.execute("SELECT COUNT(*) FROM complaint_tickets WHERE branch_id = ?", (branch_id,))
        else:
            c.execute(
                "SELECT * FROM complaint_tickets WHERE branch_id = ? AND status = ? ORDER BY complaint_date DESC LIMIT 10 OFFSET ?",
                (branch_id, status_filter, offset),
            )
            c2 = conn.cursor()
            c2.execute("SELECT COUNT(*) FROM complaint_tickets WHERE branch_id = ? AND status = ?", (branch_id, status_filter))
        rows = c.fetchall()
        total = c2.fetchone()[0]
        conn.close()
        cols = [
            "ticket_id", "branch_id", "complaint_date", "category",
            "severity", "description", "customer_name", "status",
            "resolution_date", "linked_equipment_id",
        ]
        return {
            "tickets": [dict(zip(cols, r)) for r in rows],
            "branch_id": branch_id,
            "status_filter": status_filter,
            "page": page,
            "total_tickets": total,
            "total_pages": (total + 9) // 10,
        }

    @tool(
        description="Get maintenance schedules for a specific piece of equipment.",
        parameters={
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "The equipment ID.",
                },
            },
            "required": ["equipment_id"],
        },
    )
    def get_maintenance_schedules(self, equipment_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT * FROM maintenance_schedules WHERE equipment_id = ? ORDER BY next_due",
            (equipment_id,),
        )
        rows = c.fetchall()
        conn.close()
        cols = [
            "schedule_id", "equipment_id", "maintenance_type", "frequency_days",
            "last_performed", "next_due", "assigned_vendor_id", "priority_level",
            "estimated_cost",
        ]
        return {
            "schedules": [dict(zip(cols, r)) for r in rows],
            "equipment_id": equipment_id,
            "total_schedules": len(rows),
        }

    @tool(
        description="Get details for a specific vendor contract.",
        parameters={
            "type": "object",
            "properties": {
                "vendor_id": {
                    "type": "string",
                    "description": "The vendor ID, e.g. 'VN-001'.",
                },
            },
            "required": ["vendor_id"],
        },
    )
    def get_vendor_details(self, vendor_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM vendor_contracts WHERE vendor_id = ?", (vendor_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return {"error": f"Vendor {vendor_id} not found."}
        cols = [
            "vendor_id", "vendor_name", "specialty", "contract_start",
            "contract_end", "guaranteed_response_hours", "hourly_rate",
            "satisfaction_rating", "active",
        ]
        return dict(zip(cols, row))

    @tool(
        description="Search for vendors by specialty. Returns all matching vendors.",
        parameters={
            "type": "object",
            "properties": {
                "specialty": {
                    "type": "string",
                    "description": "The vendor specialty to search for, e.g. 'HVAC Systems', 'Electrical'.",
                },
            },
            "required": ["specialty"],
        },
    )
    def search_vendors_by_specialty(self, specialty: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT * FROM vendor_contracts WHERE specialty = ? ORDER BY satisfaction_rating DESC",
            (specialty,),
        )
        rows = c.fetchall()
        conn.close()
        cols = [
            "vendor_id", "vendor_name", "specialty", "contract_start",
            "contract_end", "guaranteed_response_hours", "hourly_rate",
            "satisfaction_rating", "active",
        ]
        return {
            "vendors": [dict(zip(cols, r)) for r in rows],
            "specialty": specialty,
            "total_found": len(rows),
        }

    @tool(
        description="Count service logs for a specific equipment within a date range.",
        parameters={
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "The equipment ID.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format.",
                },
            },
            "required": ["equipment_id", "start_date", "end_date"],
        },
    )
    def count_service_logs_in_range(self, equipment_id: str, start_date: str, end_date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM service_logs WHERE equipment_id = ? AND service_date >= ? AND service_date <= ?",
            (equipment_id, start_date, end_date),
        )
        count = c.fetchone()[0]
        c.execute(
            "SELECT SUM(follow_up_needed) FROM service_logs WHERE equipment_id = ? AND service_date >= ? AND service_date <= ?",
            (equipment_id, start_date, end_date),
        )
        follow_ups = c.fetchone()[0] or 0
        conn.close()
        return {
            "equipment_id": equipment_id,
            "start_date": start_date,
            "end_date": end_date,
            "total_logs": count,
            "follow_up_needed_count": follow_ups,
        }

    # ── Evaluation ────────────────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute the expected ranked work order list."""
        import yaml as _yaml

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Load config
        with open(os.path.join(self.workspace, "priority_config.yaml")) as f:
            config = _yaml.safe_load(f)

        sw = config["scoring_weights"]
        severity_scores = sw["complaint_severity_score"]
        overdue_mult = sw["overdue_maintenance_multiplier"]
        repeat_bonus = sw["repeat_failure_bonus"]
        vendor_resp_thresh = sw["vendor_response_penalty_threshold_hours"]
        vendor_penalty = sw["vendor_slow_response_penalty"]
        age_thresh = sw["equipment_age_threshold_years"]
        age_bonus = sw["equipment_age_bonus"]
        tier_mult = sw["branch_tier_multiplier"]

        quarter_end = config["quarter_definition"]["end_date"]

        # Load specialty mapping
        with open(os.path.join(self.workspace, "equipment_specialty_map.json")) as f:
            specialty_map = json.load(f)

        # 12 months ago from quarter end
        quarter_end_dt = datetime.fromisoformat(quarter_end)
        twelve_months_ago = (quarter_end_dt.replace(year=quarter_end_dt.year - 1)).isoformat()[:10]

        # Get all equipment
        c.execute("SELECT * FROM equipment")
        all_equipment = [dict(r) for r in c.fetchall()]

        # For each equipment, check eligibility
        work_orders = []
        for eq in all_equipment:
            eid = eq["equipment_id"]
            bid = eq["branch_id"]

            # Condition 1: overdue maintenance
            c.execute(
                "SELECT COUNT(*) FROM maintenance_schedules WHERE equipment_id = ? AND next_due <= ?",
                (eid, quarter_end),
            )
            has_overdue = c.fetchone()[0] > 0

            # Condition 2: open/in-progress complaints linked to this equipment
            c.execute(
                "SELECT severity FROM complaint_tickets WHERE linked_equipment_id = ? AND status IN ('Open', 'In Progress')",
                (eid,),
            )
            complaint_sevs = [r[0] for r in c.fetchall()]
            has_complaints = len(complaint_sevs) > 0

            # Condition 3: follow-up needed in past 12 months
            c.execute(
                "SELECT COUNT(*) FROM service_logs WHERE equipment_id = ? AND service_date >= ? AND service_date <= ? AND follow_up_needed = 1",
                (eid, twelve_months_ago, quarter_end),
            )
            has_follow_up = c.fetchone()[0] > 0

            if not (has_overdue or has_complaints or has_follow_up):
                continue

            # ── Priority score calculation ──
            score = 0.0

            # Complaint severity (max)
            if complaint_sevs:
                sev_order = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
                max_sev = max(complaint_sevs, key=lambda s: sev_order.get(s, 0))
                score += severity_scores.get(max_sev, 0)

            # Overdue maintenance multiplier
            if has_overdue:
                score *= overdue_mult

            # Repeat failures (3+ logs in past 12 months)
            c.execute(
                "SELECT COUNT(*) FROM service_logs WHERE equipment_id = ? AND service_date >= ? AND service_date <= ?",
                (eid, twelve_months_ago, quarter_end),
            )
            log_count_12m = c.fetchone()[0]
            if log_count_12m >= 3:
                score += repeat_bonus

            # Vendor assignment
            eq_type = eq["equipment_type"]
            specialty = specialty_map.get(eq_type)
            assigned_vendor = None
            if specialty:
                c.execute(
                    "SELECT * FROM vendor_contracts WHERE specialty = ? AND active = 1 ORDER BY satisfaction_rating DESC LIMIT 1",
                    (specialty,),
                )
                vrow = c.fetchone()
                if vrow:
                    assigned_vendor = dict(vrow)

            # Vendor response penalty
            if assigned_vendor and assigned_vendor["guaranteed_response_hours"] > vendor_resp_thresh:
                score -= vendor_penalty

            # Equipment age bonus
            install_dt = datetime.fromisoformat(eq["install_date"])
            age_years = (quarter_end_dt - install_dt).days / 365.25
            if age_years > age_thresh:
                score += age_bonus

            # Branch tier multiplier
            c.execute("SELECT branch_tier, branch_name FROM branches WHERE branch_id = ?", (bid,))
            branch_row = c.fetchone()
            branch_tier = branch_row[0]
            branch_name = branch_row[1]
            score *= tier_mult.get(branch_tier, 1.0)

            score = round(score, 2)

            # Issue summary
            issues = []
            if has_overdue:
                issues.append("Overdue maintenance")
            if has_complaints:
                issues.append(f"Complaints ({len(complaint_sevs)} open/in-progress)")
            if has_follow_up:
                issues.append("Follow-up needed from service")
            issue_summary = "; ".join(issues)

            # Estimated cost from schedule or default
            c.execute(
                "SELECT estimated_cost FROM maintenance_schedules WHERE equipment_id = ? ORDER BY estimated_cost DESC LIMIT 1",
                (eid,),
            )
            cost_row = c.fetchone()
            estimated_cost = round(cost_row[0], 2) if cost_row else 0.0

            work_orders.append({
                "branch_id": bid,
                "branch_name": branch_name,
                "equipment_id": eid,
                "equipment_type": eq_type,
                "issue_summary": issue_summary,
                "priority_score": score,
                "assigned_vendor_id": assigned_vendor["vendor_id"] if assigned_vendor else "UNASSIGNED",
                "vendor_name": assigned_vendor["vendor_name"] if assigned_vendor else "UNASSIGNED",
                "estimated_cost": estimated_cost,
                "target_completion_date": quarter_end,
            })

        # Sort: descending priority_score, then branch_id asc, equipment_id asc
        work_orders.sort(key=lambda wo: (-wo["priority_score"], wo["branch_id"], wo["equipment_id"]))

        # Assign work order IDs
        for i, wo in enumerate(work_orders):
            wo["rank"] = i + 1
            wo["work_order_id"] = f"WO-{i+1:04d}"

        conn.close()
        return work_orders

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

        # ── Criterion 1: Output file exists (10 pts) ──
        output_path = os.path.join(self.workspace, "ranked_work_orders.csv")
        file_exists = os.path.exists(output_path)
        eval_criteria["output_file_exists"] = {
            "passed": file_exists,
            "score": 10 if file_exists else 0,
            "max_score": 10,
            "reason": "" if file_exists else "ranked_work_orders.csv not found in workspace",
        }
        total_score += eval_criteria["output_file_exists"]["score"]
        max_score += 10

        # ── Criterion 2: Correct columns (10 pts) ──
        correct_columns = False
        expected_cols = [
            "rank", "work_order_id", "branch_id", "branch_name",
            "equipment_id", "equipment_type", "issue_summary",
            "priority_score", "assigned_vendor_id", "vendor_name",
            "estimated_cost", "target_completion_date",
        ]
        agent_rows = []
        if file_exists:
            try:
                with open(output_path, "r") as f:
                    reader = csv.DictReader(f)
                    actual_cols = [c.strip() for c in reader.fieldnames] if reader.fieldnames else []
                    correct_columns = actual_cols == expected_cols
                    agent_rows = [r for r in reader]
            except Exception:
                pass
        eval_criteria["correct_columns"] = {
            "passed": correct_columns,
            "score": 10 if correct_columns else 0,
            "max_score": 10,
            "reason": "" if correct_columns else f"Expected columns {expected_cols}, got {actual_cols if file_exists else 'N/A'}",
        }
        total_score += eval_criteria["correct_columns"]["score"]
        max_score += 10

        # ── Criterion 3: Correct number of work orders (15 pts) ──
        correct_count = len(agent_rows) == len(ground_truth)
        eval_criteria["correct_work_order_count"] = {
            "passed": correct_count,
            "score": 15 if correct_count else 0,
            "max_score": 15,
            "reason": "" if correct_count else f"Expected {len(ground_truth)} work orders, got {len(agent_rows)}",
        }
        total_score += eval_criteria["correct_work_order_count"]["score"]
        max_score += 15

        # ── Criterion 4: Correct equipment set (15 pts) ──
        gt_equip_set = set(wo["equipment_id"] for wo in ground_truth)
        agent_equip_set = set(r.get("equipment_id", "").strip() for r in agent_rows)
        equip_match = gt_equip_set == agent_equip_set
        eval_criteria["correct_equipment_set"] = {
            "passed": equip_match,
            "score": 15 if equip_match else 0,
            "max_score": 15,
            "reason": "" if equip_match else f"Missing: {gt_equip_set - agent_equip_set}, Extra: {agent_equip_set - gt_equip_set}",
        }
        total_score += eval_criteria["correct_equipment_set"]["score"]
        max_score += 15

        # ── Criterion 5: Priority scores correct (20 pts) ──
        score_correct_count = 0
        if agent_rows and ground_truth:
            gt_score_map = {wo["equipment_id"]: wo["priority_score"] for wo in ground_truth}
            for row in agent_rows:
                eid = row.get("equipment_id", "").strip()
                try:
                    agent_score = round(float(row.get("priority_score", "0").strip()), 2)
                except (ValueError, TypeError):
                    agent_score = -1
                if eid in gt_score_map and agent_score == gt_score_map[eid]:
                    score_correct_count += 1
            score_pct = score_correct_count / len(ground_truth) if ground_truth else 0
        else:
            score_pct = 0
        pts_5 = round(20 * score_pct)
        eval_criteria["priority_scores_correct"] = {
            "passed": score_pct == 1.0,
            "score": pts_5,
            "max_score": 20,
            "reason": "" if score_pct == 1.0 else f"{score_correct_count}/{len(ground_truth)} scores matched",
        }
        total_score += pts_5
        max_score += 20

        # ── Criterion 6: Correct ranking order (15 pts) ──
        rank_correct = False
        if agent_rows and len(agent_rows) == len(ground_truth):
            agent_order = [r.get("equipment_id", "").strip() for r in agent_rows]
            gt_order = [wo["equipment_id"] for wo in ground_truth]
            rank_correct = agent_order == gt_order
        eval_criteria["correct_ranking_order"] = {
            "passed": rank_correct,
            "score": 15 if rank_correct else 0,
            "max_score": 15,
            "reason": "" if rank_correct else "Work order ranking does not match expected order",
        }
        total_score += eval_criteria["correct_ranking_order"]["score"]
        max_score += 15

        # ── Criterion 7: Vendor assignments correct (15 pts) ──
        vendor_correct_count = 0
        if agent_rows and ground_truth:
            gt_vendor_map = {wo["equipment_id"]: wo["assigned_vendor_id"] for wo in ground_truth}
            for row in agent_rows:
                eid = row.get("equipment_id", "").strip()
                agent_vid = row.get("assigned_vendor_id", "").strip()
                if eid in gt_vendor_map and agent_vid == gt_vendor_map[eid]:
                    vendor_correct_count += 1
            vendor_pct = vendor_correct_count / len(ground_truth) if ground_truth else 0
        else:
            vendor_pct = 0
        pts_7 = round(15 * vendor_pct)
        eval_criteria["vendor_assignments_correct"] = {
            "passed": vendor_pct == 1.0,
            "score": pts_7,
            "max_score": 15,
            "reason": "" if vendor_pct == 1.0 else f"{vendor_correct_count}/{len(ground_truth)} vendor assignments matched",
        }
        total_score += pts_7
        max_score += 15

        # ── Criterion 8: Response summary (10 pts) ──
        response_has_summary = False
        if action:
            # Check that the response mentions total work orders and top priority
            has_total = str(len(ground_truth)) in action
            has_top = ground_truth[0]["work_order_id"] in action if ground_truth else True
            response_has_summary = has_total and has_top
        eval_criteria["response_summary"] = {
            "passed": response_has_summary,
            "score": 10 if response_has_summary else 0,
            "max_score": 10,
            "reason": "" if response_has_summary else "Response should mention total work order count and top priority work order ID",
        }
        total_score += eval_criteria["response_summary"]["score"]
        max_score += 10

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
        import yaml as _yaml

        # Step 1: Read config files from workspace
        with open(os.path.join(self.workspace, "priority_config.yaml")) as f:
            config = _yaml.safe_load(f)

        with open(os.path.join(self.workspace, "equipment_specialty_map.json")) as f:
            specialty_map = json.load(f)

        with open(os.path.join(self.workspace, "maintenance_policy.md")) as f:
            policy = f.read()

        sw = config["scoring_weights"]
        severity_scores = sw["complaint_severity_score"]
        overdue_mult = sw["overdue_maintenance_multiplier"]
        repeat_bonus = sw["repeat_failure_bonus"]
        vendor_resp_thresh = sw["vendor_response_penalty_threshold_hours"]
        vendor_penalty = sw["vendor_slow_response_penalty"]
        age_thresh = sw["equipment_age_threshold_years"]
        age_bonus = sw["equipment_age_bonus"]
        tier_mult = sw["branch_tier_multiplier"]
        quarter_end = config["quarter_definition"]["end_date"]
        quarter_end_dt = datetime.fromisoformat(quarter_end)
        twelve_months_ago = quarter_end_dt.replace(year=quarter_end_dt.year - 1).isoformat()[:10]

        tool_call_count = 0

        # Step 2: List all branches via tool
        all_branches = []
        page = 1
        while True:
            result = self.tools["list_branches"](page=page)
            tool_call_count += 1
            all_branches.extend(result["branches"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 3: Read complaint CSV files from workspace
        complaint_files = [f for f in os.listdir(self.workspace) if f.startswith("complaint_batch_") and f.endswith(".csv")]
        # complaints from workspace files (open/in-progress with linked equipment)
        ws_complaints = {}  # equipment_id -> list of severities
        for cf in complaint_files:
            import csv as _csv
            with open(os.path.join(self.workspace, cf)) as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    linked_eid = row.get("linked_equipment_id", "").strip()
                    if linked_eid and row.get("status", "").strip() in ("Open", "In Progress"):
                        ws_complaints.setdefault(linked_eid, []).append(row["severity"].strip())

        # Step 4: Read service summary TXT files to find follow-up needed
        service_files = [f for f in os.listdir(self.workspace) if f.startswith("service_summary_") and f.endswith(".txt")]
        ws_follow_ups = set()  # equipment_ids with follow-up needed
        ws_service_counts = {}  # equipment_id -> count of service logs
        for sf in service_files:
            with open(os.path.join(self.workspace, sf)) as f:
                content = f.read()
            current_eid = None
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("Equipment:"):
                    current_eid = line.split(":", 1)[1].strip()
                    ws_service_counts[current_eid] = ws_service_counts.get(current_eid, 0) + 1
                elif line.startswith("Follow-up Needed: Yes") and current_eid:
                    ws_follow_ups.add(current_eid)

        # Step 5: Read schedule YAML files
        schedule_files = [f for f in os.listdir(self.workspace) if f.startswith("schedule_batch_") and f.endswith(".yaml")]
        ws_schedules = {}  # equipment_id -> list of schedules
        for sf in schedule_files:
            with open(os.path.join(self.workspace, sf)) as f:
                data = _yaml.safe_load(f)
            for sched in data.get("schedules", []):
                eid = sched["equipment_id"]
                ws_schedules.setdefault(eid, []).append(sched)

        # Step 6: For each branch, get equipment list via tools
        all_equipment = []
        for branch in all_branches:
            bid = branch["branch_id"]
            page = 1
            while True:
                result = self.tools["list_equipment_by_branch"](branch_id=bid, page=page)
                tool_call_count += 1
                for eq in result["equipment"]:
                    eq["branch_id"] = bid
                    eq["branch_tier"] = branch["branch_tier"]
                all_equipment.extend(result["equipment"])
                if page >= result["total_pages"]:
                    break
                page += 1

        # Step 7: Determine eligible equipment and compute scores
        work_orders = []
        vendor_cache = {}  # specialty -> best vendor

        for eq in all_equipment:
            eid = eq["equipment_id"]
            bid = eq["branch_id"]

            # Check overdue schedules via tool
            sched_result = self.tools["get_maintenance_schedules"](equipment_id=eid)
            tool_call_count += 1
            has_overdue = any(
                s["next_due"] <= quarter_end
                for s in sched_result["schedules"]
            )

            # Check complaints via tool (for this equipment's branch)
            # We also need complaints linked to this specific equipment
            complaint_result = self.tools["get_complaint_tickets"](branch_id=bid, status_filter="Open", page=1)
            tool_call_count += 1
            complaint_sevs = []
            # Check all pages
            for ticket in complaint_result["tickets"]:
                if ticket.get("linked_equipment_id") == eid:
                    complaint_sevs.append(ticket["severity"])
            cp = 2
            while cp <= complaint_result["total_pages"]:
                cr2 = self.tools["get_complaint_tickets"](branch_id=bid, status_filter="Open", page=cp)
                tool_call_count += 1
                for ticket in cr2["tickets"]:
                    if ticket.get("linked_equipment_id") == eid:
                        complaint_sevs.append(ticket["severity"])
                cp += 1

            # Also check In Progress
            ip_result = self.tools["get_complaint_tickets"](branch_id=bid, status_filter="In Progress", page=1)
            tool_call_count += 1
            for ticket in ip_result["tickets"]:
                if ticket.get("linked_equipment_id") == eid:
                    complaint_sevs.append(ticket["severity"])
            cp = 2
            while cp <= ip_result["total_pages"]:
                cr2 = self.tools["get_complaint_tickets"](branch_id=bid, status_filter="In Progress", page=cp)
                tool_call_count += 1
                for ticket in cr2["tickets"]:
                    if ticket.get("linked_equipment_id") == eid:
                        complaint_sevs.append(ticket["severity"])
                cp += 1

            has_complaints = len(complaint_sevs) > 0

            # Check follow-up needed via tool
            log_result = self.tools["count_service_logs_in_range"](
                equipment_id=eid, start_date=twelve_months_ago, end_date=quarter_end
            )
            tool_call_count += 1
            has_follow_up = log_result["follow_up_needed_count"] > 0
            log_count_12m = log_result["total_logs"]

            if not (has_overdue or has_complaints or has_follow_up):
                continue

            # Get equipment details via tool for install_date
            eq_details = self.tools["get_equipment_details"](equipment_id=eid)
            tool_call_count += 1

            # Get branch details via tool
            branch_details = self.tools["get_branch_details"](branch_id=bid)
            tool_call_count += 1

            # ── Priority score calculation ──
            score = 0.0

            # Complaint severity (max)
            if complaint_sevs:
                sev_order = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
                max_sev = max(complaint_sevs, key=lambda s: sev_order.get(s, 0))
                score += severity_scores.get(max_sev, 0)

            # Overdue maintenance multiplier
            if has_overdue:
                score *= overdue_mult

            # Repeat failures
            if log_count_12m >= 3:
                score += repeat_bonus

            # Vendor assignment
            eq_type = eq_details["equipment_type"]
            specialty = specialty_map.get(eq_type)
            assigned_vendor = None
            if specialty:
                if specialty not in vendor_cache:
                    v_result = self.tools["search_vendors_by_specialty"](specialty=specialty)
                    tool_call_count += 1
                    active = [v for v in v_result["vendors"] if v["active"]]
                    vendor_cache[specialty] = active[0] if active else None
                assigned_vendor = vendor_cache[specialty]

            # Vendor response penalty
            if assigned_vendor and assigned_vendor["guaranteed_response_hours"] > vendor_resp_thresh:
                score -= vendor_penalty

            # Equipment age bonus
            install_dt = datetime.fromisoformat(eq_details["install_date"])
            age_years = (quarter_end_dt - install_dt).days / 365.25
            if age_years > age_thresh:
                score += age_bonus

            # Branch tier multiplier
            branch_tier = branch_details["branch_tier"]
            score *= tier_mult.get(branch_tier, 1.0)
            score = round(score, 2)

            # Issue summary
            issues = []
            if has_overdue:
                issues.append("Overdue maintenance")
            if has_complaints:
                issues.append(f"Complaints ({len(complaint_sevs)} open/in-progress)")
            if has_follow_up:
                issues.append("Follow-up needed from service")
            issue_summary = "; ".join(issues)

            # Estimated cost
            est_cost = 0.0
            for s in sched_result["schedules"]:
                if s["estimated_cost"] > est_cost:
                    est_cost = s["estimated_cost"]
            est_cost = round(est_cost, 2)

            work_orders.append({
                "branch_id": bid,
                "branch_name": branch_details["branch_name"],
                "equipment_id": eid,
                "equipment_type": eq_type,
                "issue_summary": issue_summary,
                "priority_score": score,
                "assigned_vendor_id": assigned_vendor["vendor_id"] if assigned_vendor else "UNASSIGNED",
                "vendor_name": assigned_vendor["vendor_name"] if assigned_vendor else "UNASSIGNED",
                "estimated_cost": est_cost,
                "target_completion_date": quarter_end,
            })

        # Sort
        work_orders.sort(key=lambda wo: (-wo["priority_score"], wo["branch_id"], wo["equipment_id"]))

        # Assign IDs
        for i, wo in enumerate(work_orders):
            wo["rank"] = i + 1
            wo["work_order_id"] = f"WO-{i+1:04d}"

        # Write output CSV
        output_path = os.path.join(self.workspace, "ranked_work_orders.csv")
        columns = [
            "rank", "work_order_id", "branch_id", "branch_name",
            "equipment_id", "equipment_type", "issue_summary",
            "priority_score", "assigned_vendor_id", "vendor_name",
            "estimated_cost", "target_completion_date",
        ]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for wo in work_orders:
                writer.writerow({c: wo[c] for c in columns})

        # Build action string
        action = f"I have generated the ranked work order list for Q2 2026. "
        action += f"A total of {len(work_orders)} work orders were created. "
        if work_orders:
            action += f"The highest priority work order is {work_orders[0]['work_order_id']} "
            action += f"for equipment {work_orders[0]['equipment_id']} at branch {work_orders[0]['branch_id']} "
            action += f"with a priority score of {work_orders[0]['priority_score']}. "
        action += f"The results have been saved to ranked_work_orders.csv."

        print(f"verify: tool calls made = {tool_call_count}")
        return self.step(action)
