import sqlite3
import os
import json
import csv
import glob as glob_module
from typing import Tuple, Dict, List, Any

import yaml


def tool(description: str, parameters: dict):
    """Decorator that attaches tool metadata to a method."""
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


CERT_LEVEL_ORDER = {"junior": 1, "senior": 2, "expert": 3}


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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _db_query(self, query, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description=(
            "List pending service requests with pagination. Returns request_id, "
            "customer_name, zone, required_skill, priority_level, "
            "estimated_duration_hours, status, and created_date for each request."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 50)",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_service_requests(self, page: int, page_size: int):
        page_size = min(int(page_size), 50)
        page = int(page)
        offset = (page - 1) * page_size
        total = self._db_query(
            "SELECT COUNT(*) as cnt FROM service_requests WHERE status='pending'"
        )[0]["cnt"]
        rows = self._db_query(
            "SELECT * FROM service_requests WHERE status='pending' "
            "ORDER BY request_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        return {
            "requests": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    @tool(
        description=(
            "List technicians with pagination. Returns tech_id, name, home_zone, "
            "experience_years, and active status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 50)",
                },
                "active_only": {
                    "type": "boolean",
                    "description": "If true, only return active technicians (default true)",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_technicians(self, page: int, page_size: int, active_only: bool = True):
        page_size = min(int(page_size), 50)
        page = int(page)
        offset = (page - 1) * page_size
        if isinstance(active_only, str):
            active_only = active_only.lower() in ("true", "1", "yes")
        where = "WHERE active=1" if active_only else ""
        total = self._db_query(
            f"SELECT COUNT(*) as cnt FROM technicians {where}"
        )[0]["cnt"]
        rows = self._db_query(
            f"SELECT * FROM technicians {where} ORDER BY tech_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        return {
            "technicians": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    @tool(
        description=(
            "Get all certifications for a specific technician. Returns cert_id, "
            "skill_name, cert_level, and expiry_date for each certification."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tech_id": {
                    "type": "integer",
                    "description": "Technician ID",
                },
            },
            "required": ["tech_id"],
        },
    )
    def get_technician_certifications(self, tech_id: int):
        rows = self._db_query(
            "SELECT cert_id, skill_name, cert_level, expiry_date "
            "FROM technician_certifications WHERE tech_id=? ORDER BY cert_id",
            (int(tech_id),),
        )
        return {"tech_id": int(tech_id), "certifications": rows}

    @tool(
        description=(
            "Get the list of parts required for a specific service request. "
            "Returns part_id and quantity_needed for each required part."
        ),
        parameters={
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "integer",
                    "description": "Service request ID",
                },
            },
            "required": ["request_id"],
        },
    )
    def get_required_parts(self, request_id: int):
        rows = self._db_query(
            "SELECT part_id, quantity_needed FROM service_parts_required "
            "WHERE request_id=? ORDER BY part_id",
            (int(request_id),),
        )
        return {"request_id": int(request_id), "parts": rows}

    @tool(
        description=(
            "Check inventory level for a specific part at a specific warehouse. "
            "Returns the quantity on hand and reorder ETA in days if the part "
            "needs to be reordered."
        ),
        parameters={
            "type": "object",
            "properties": {
                "part_id": {
                    "type": "string",
                    "description": "Part identifier (e.g. 'compressor', 'thermostat')",
                },
                "warehouse_id": {
                    "type": "integer",
                    "description": "Warehouse ID",
                },
            },
            "required": ["part_id", "warehouse_id"],
        },
    )
    def check_parts_inventory(self, part_id: str, warehouse_id: int):
        rows = self._db_query(
            "SELECT quantity, reorder_eta_days FROM parts_inventory "
            "WHERE part_id=? AND warehouse_id=? ORDER BY inv_id LIMIT 1",
            (str(part_id), int(warehouse_id)),
        )
        if rows:
            return {
                "part_id": str(part_id),
                "warehouse_id": int(warehouse_id),
                "quantity": rows[0]["quantity"],
                "reorder_eta_days": rows[0]["reorder_eta_days"],
            }
        return {
            "part_id": str(part_id),
            "warehouse_id": int(warehouse_id),
            "quantity": 0,
            "reorder_eta_days": 7,
        }

    # ------------------------------------------------------------------
    # Ground-truth computation (used by step)
    # ------------------------------------------------------------------

    def _load_workspace_data(self):
        """Load all workspace configuration and batch files."""
        # Travel matrix
        travel = {}
        with open(os.path.join(self.workspace, "travel_matrix.csv")) as f:
            reader = csv.DictReader(f)
            zones = [c for c in reader.fieldnames if c != "from_zone"]
            for row in reader:
                fz = row["from_zone"]
                travel[fz] = {z: int(row[z]) for z in zones}

        # Policy
        with open(os.path.join(self.workspace, "dispatch_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        # Cost weights
        with open(os.path.join(self.workspace, "cost_weights.json")) as f:
            weights = json.load(f)

        # Seasonal demand
        with open(os.path.join(self.workspace, "seasonal_demand.json")) as f:
            seasonal = json.load(f)

        # Warehouse directory
        with open(os.path.join(self.workspace, "warehouse_directory.yaml")) as f:
            warehouses = yaml.safe_load(f)

        # Service details from batch files
        service_details = {}
        batch_files = sorted(
            glob_module.glob(
                os.path.join(self.workspace, "service_details_batch_*.csv")
            )
        )
        for bf in batch_files:
            with open(bf) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    service_details[int(row["request_id"])] = {
                        "customer_tier": row["customer_tier"],
                        "preferred_day": row["preferred_day"],
                    }

        return travel, policy, weights, seasonal, warehouses, service_details

    def _compute_ground_truth(self):
        """Compute the optimal assignment roster from DB + workspace data."""
        travel, policy, weights, seasonal, warehouses, service_details = (
            self._load_workspace_data()
        )

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        requests = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM service_requests WHERE status='pending' "
                "ORDER BY request_id"
            ).fetchall()
        ]
        techs = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM technicians WHERE active=1 ORDER BY tech_id"
            ).fetchall()
        ]
        certs = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM technician_certifications ORDER BY cert_id"
            ).fetchall()
        ]
        parts_req = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM service_parts_required ORDER BY id"
            ).fetchall()
        ]
        inventory = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM parts_inventory ORDER BY inv_id"
            ).fetchall()
        ]
        conn.close()

        # Build indices
        cert_map: Dict[int, list] = {}
        for c in certs:
            cert_map.setdefault(c["tech_id"], []).append(c)

        parts_map: Dict[int, list] = {}
        for p in parts_req:
            parts_map.setdefault(p["request_id"], []).append(
                {"part_id": p["part_id"], "quantity_needed": p["quantity_needed"]}
            )

        inv_map: Dict[tuple, dict] = {}
        for inv in inventory:
            key = (inv["part_id"], inv["warehouse_id"])
            if key not in inv_map:
                inv_map[key] = {
                    "quantity": inv["quantity"],
                    "reorder_eta_days": inv["reorder_eta_days"],
                }

        return self._run_assignment(
            requests, techs, cert_map, parts_map, inv_map,
            travel, policy, weights, seasonal, warehouses, service_details,
        )

    @staticmethod
    def _run_assignment(
        requests, techs, cert_map, parts_map, inv_map,
        travel, policy, weights, seasonal, warehouses, service_details,
    ):
        """Deterministic greedy assignment algorithm."""
        ref_date = policy["reference_date"]
        cert_reqs = policy["certification_requirements"]
        tier_mult = policy["customer_tier_multiplier"]
        level_hier = policy["certification_level_hierarchy"]
        daily_cap = policy["max_assignments_per_tech_per_day"]
        weekly_cap = policy["max_weekly_assignments_per_tech"]
        sched_days = policy["scheduling_days"]
        w_travel = weights["travel_time_weight"]
        w_wait = weights["wait_time_weight"]

        # Compute effective priority
        for req in requests:
            rid = req["request_id"]
            det = service_details.get(
                rid, {"customer_tier": "bronze", "preferred_day": "Monday"}
            )
            req["customer_tier"] = det["customer_tier"]
            req["preferred_day"] = det["preferred_day"]
            tm = tier_mult.get(req["customer_tier"], 1.0)
            sf = seasonal.get(req["zone"], 1.0)
            req["effective_priority"] = req["priority_level"] * tm * sf

        requests.sort(key=lambda r: (-r["effective_priority"], r["request_id"]))

        # Capacity tracking
        tech_daily = {t["tech_id"]: {d: 0 for d in sched_days} for t in techs}
        tech_weekly = {t["tech_id"]: 0 for t in techs}
        tech_zone = {t["tech_id"]: t["home_zone"] for t in techs}

        wh_ids = sorted(warehouses.keys())

        assignments = []
        unassigned = []

        for req in requests:
            rid = req["request_id"]
            rzone = req["zone"]
            rskill = req["required_skill"]
            rprio = req["priority_level"]
            req_parts = parts_map.get(rid, [])

            # Minimum cert level
            min_level_name = cert_reqs.get(rprio, "junior")
            if isinstance(min_level_name, str):
                min_level = level_hier.get(min_level_name, 1)
            else:
                min_level = int(min_level_name)

            # Eligible technicians
            eligible = []
            for t in techs:
                tid = t["tech_id"]
                if tech_weekly[tid] >= weekly_cap:
                    continue
                tcerts = cert_map.get(tid, [])
                best = 0
                for c in tcerts:
                    if (
                        c["skill_name"] == rskill
                        and c["expiry_date"] >= ref_date
                    ):
                        cl = level_hier.get(c["cert_level"], 0)
                        best = max(best, cl)
                if best >= min_level:
                    eligible.append(tid)

            if not eligible:
                unassigned.append(rid)
                continue

            # Evaluate (tech, warehouse) pairs
            candidates = []
            for tid in eligible:
                tech_travel = travel.get(tech_zone[tid], {}).get(rzone, 999)
                for wid in wh_ids:
                    wh_zone = warehouses[wid]["zone"]
                    wh_travel = travel.get(wh_zone, {}).get(rzone, 999)
                    wait = 0
                    for p in req_parts:
                        inv = inv_map.get(
                            (p["part_id"], wid),
                            {"quantity": 0, "reorder_eta_days": 7},
                        )
                        if inv["quantity"] < p["quantity_needed"]:
                            wait = max(wait, inv["reorder_eta_days"])
                    cost = w_travel * (tech_travel + wh_travel) + w_wait * wait * 60
                    candidates.append(
                        {
                            "tech_id": tid,
                            "warehouse_id": wid,
                            "travel_time_minutes": tech_travel + wh_travel,
                            "part_wait_days": wait,
                            "cost": cost,
                        }
                    )

            candidates.sort(
                key=lambda c: (c["cost"], c["tech_id"], c["warehouse_id"])
            )

            assigned = False
            for cand in candidates:
                tid = cand["tech_id"]
                day_order = [req["preferred_day"]] + [
                    d for d in sched_days if d != req["preferred_day"]
                ]
                for day in day_order:
                    if (
                        tech_daily[tid][day] < daily_cap
                        and tech_weekly[tid] < weekly_cap
                    ):
                        assignments.append(
                            {
                                "request_id": rid,
                                "technician_id": tid,
                                "warehouse_id": cand["warehouse_id"],
                                "scheduled_day": day,
                                "travel_time_minutes": cand["travel_time_minutes"],
                                "part_wait_days": cand["part_wait_days"],
                                "assignment_cost": round(cand["cost"], 2),
                            }
                        )
                        tech_daily[tid][day] += 1
                        tech_weekly[tid] += 1
                        assigned = True
                        break
                if assigned:
                    break

            if not assigned:
                unassigned.append(rid)

        return assignments, unassigned

    # ------------------------------------------------------------------
    # step  –  evaluate task completion
    # ------------------------------------------------------------------

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's
        final response.

        Returns a reward based on evaluation results.

        Args:
            action: The agent's final response.

        Returns:
            reward: The reward based on task completion (between 0.0 and 1.0).
            info: Evaluation results.
        """
        eval_criteria: Dict[str, dict] = {}

        # Ground truth
        gt_assignments, gt_unassigned = self._compute_ground_truth()
        gt_roster: Dict[int, dict] = {a["request_id"]: a for a in gt_assignments}

        # ---- Criterion 1: Roster file format (10 pts) ----
        roster_path = os.path.join(self.workspace, "assignment_roster.csv")
        expected_cols = [
            "request_id", "technician_id", "warehouse_id", "scheduled_day",
            "travel_time_minutes", "part_wait_days", "assignment_cost",
        ]

        roster_data: list = []
        c1_pass = False
        if os.path.exists(roster_path):
            try:
                with open(roster_path) as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    if all(c in cols for c in expected_cols):
                        roster_data = list(reader)
                        c1_pass = True
            except Exception:
                pass

        eval_criteria["roster_format"] = {
            "passed": c1_pass,
            "score": 10 if c1_pass else 0,
            "max_score": 10,
            "reason": "" if c1_pass else (
                "assignment_roster.csv missing or has incorrect columns"
            ),
        }

        if not c1_pass:
            for cname, maxs in [
                ("request_coverage", 15),
                ("certification_validity", 20),
                ("parts_sourcing", 15),
                ("capacity_compliance", 15),
                ("travel_accuracy", 10),
                ("summary_metrics", 15),
            ]:
                eval_criteria[cname] = {
                    "passed": False, "score": 0, "max_score": maxs,
                    "reason": "Roster file not valid",
                }
            total = sum(c["score"] for c in eval_criteria.values())
            mx = sum(c["max_score"] for c in eval_criteria.values())
            return total / mx, {
                "eval_criteria": eval_criteria,
                "total_score": total,
                "max_score": mx,
            }

        # Parse agent roster
        agent_roster: Dict[int, dict] = {}
        for row in roster_data:
            try:
                rid = int(row["request_id"])
                agent_roster[rid] = {
                    "technician_id": int(row["technician_id"]),
                    "warehouse_id": int(row["warehouse_id"]),
                    "scheduled_day": row["scheduled_day"].strip(),
                    "travel_time_minutes": int(row["travel_time_minutes"]),
                    "part_wait_days": int(row["part_wait_days"]),
                    "assignment_cost": float(row["assignment_cost"]),
                }
            except (ValueError, KeyError):
                continue

        gt_rids = set(gt_roster.keys())
        agent_rids = set(agent_roster.keys())

        # ---- Criterion 2: Request coverage (15 pts) ----
        coverage_match = gt_rids == agent_rids
        if not coverage_match:
            missing = gt_rids - agent_rids
            extra = agent_rids - gt_rids
            correct = len(gt_rids & agent_rids)
            ratio = correct / len(gt_rids) if gt_rids else 1.0
            c2_score = int(round(15 * ratio))
            c2_reason = f"Missing {len(missing)}, extra {len(extra)} request(s)"
        else:
            c2_score = 15
            c2_reason = ""

        eval_criteria["request_coverage"] = {
            "passed": coverage_match,
            "score": c2_score,
            "max_score": 15,
            "reason": c2_reason,
        }

        common_rids = gt_rids & agent_rids

        # ---- Criterion 3: Certification validity (20 pts) ----
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        with open(os.path.join(self.workspace, "dispatch_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        ref_date = policy["reference_date"]
        cert_reqs = policy["certification_requirements"]
        level_hier = policy["certification_level_hierarchy"]

        cert_valid_count = 0
        cert_total = len(common_rids)
        for rid in common_rids:
            agent_a = agent_roster[rid]
            tid = agent_a["technician_id"]

            req_row = conn.execute(
                "SELECT required_skill, priority_level FROM service_requests "
                "WHERE request_id=?", (rid,),
            ).fetchone()
            if not req_row:
                continue

            rskill = req_row["required_skill"]
            rprio = req_row["priority_level"]
            min_level_name = cert_reqs.get(rprio, "junior")
            min_level = (
                level_hier.get(min_level_name, 1)
                if isinstance(min_level_name, str)
                else int(min_level_name)
            )

            # Check tech is active
            tech_row = conn.execute(
                "SELECT active FROM technicians WHERE tech_id=?", (tid,)
            ).fetchone()
            if not tech_row or not tech_row["active"]:
                continue

            tcerts = conn.execute(
                "SELECT skill_name, cert_level, expiry_date "
                "FROM technician_certifications WHERE tech_id=?", (tid,),
            ).fetchall()
            valid = False
            for c in tcerts:
                if (
                    c["skill_name"] == rskill
                    and c["expiry_date"] >= ref_date
                    and level_hier.get(c["cert_level"], 0) >= min_level
                ):
                    valid = True
                    break
            if valid:
                cert_valid_count += 1

        cert_ratio = cert_valid_count / cert_total if cert_total else 1.0
        c3_score = int(round(20 * cert_ratio))
        eval_criteria["certification_validity"] = {
            "passed": cert_ratio == 1.0,
            "score": c3_score,
            "max_score": 20,
            "reason": (
                ""
                if cert_ratio == 1.0
                else f"{cert_total - cert_valid_count} assignment(s) have invalid certifications"
            ),
        }

        # ---- Criterion 4: Parts sourcing / wait days (15 pts) ----
        with open(os.path.join(self.workspace, "warehouse_directory.yaml")) as f:
            warehouses = yaml.safe_load(f)

        parts_correct = 0
        parts_total = len(common_rids)
        for rid in common_rids:
            agent_a = agent_roster[rid]
            wid = agent_a["warehouse_id"]
            agent_wait = agent_a["part_wait_days"]

            req_parts = conn.execute(
                "SELECT part_id, quantity_needed FROM service_parts_required "
                "WHERE request_id=?", (rid,),
            ).fetchall()

            expected_wait = 0
            for p in req_parts:
                inv_row = conn.execute(
                    "SELECT quantity, reorder_eta_days FROM parts_inventory "
                    "WHERE part_id=? AND warehouse_id=? ORDER BY inv_id LIMIT 1",
                    (p["part_id"], wid),
                ).fetchone()
                if inv_row:
                    if inv_row["quantity"] < p["quantity_needed"]:
                        expected_wait = max(
                            expected_wait, inv_row["reorder_eta_days"]
                        )
                else:
                    expected_wait = max(expected_wait, 7)

            if agent_wait == expected_wait:
                parts_correct += 1

        parts_ratio = parts_correct / parts_total if parts_total else 1.0
        c4_score = int(round(15 * parts_ratio))
        eval_criteria["parts_sourcing"] = {
            "passed": parts_ratio == 1.0,
            "score": c4_score,
            "max_score": 15,
            "reason": (
                ""
                if parts_ratio == 1.0
                else f"{parts_total - parts_correct} assignment(s) have incorrect wait days"
            ),
        }

        # ---- Criterion 5: Capacity compliance (15 pts) ----
        daily_cap = policy["max_assignments_per_tech_per_day"]
        weekly_cap = policy["max_weekly_assignments_per_tech"]
        sched_days = policy["scheduling_days"]

        tech_daily_count: Dict[int, Dict[str, int]] = {}
        tech_weekly_count: Dict[int, int] = {}
        for rid, a in agent_roster.items():
            tid = a["technician_id"]
            day = a["scheduled_day"]
            if tid not in tech_daily_count:
                tech_daily_count[tid] = {d: 0 for d in sched_days}
                tech_weekly_count[tid] = 0
            tech_daily_count[tid][day] = tech_daily_count[tid].get(day, 0) + 1
            tech_weekly_count[tid] = tech_weekly_count.get(tid, 0) + 1

        cap_violations = 0
        for tid, daily in tech_daily_count.items():
            for day, cnt in daily.items():
                if cnt > daily_cap:
                    cap_violations += 1
            if tech_weekly_count.get(tid, 0) > weekly_cap:
                cap_violations += 1

        c5_pass = cap_violations == 0
        eval_criteria["capacity_compliance"] = {
            "passed": c5_pass,
            "score": 15 if c5_pass else 0,
            "max_score": 15,
            "reason": (
                "" if c5_pass else f"{cap_violations} capacity violation(s)"
            ),
        }

        # ---- Criterion 6: Travel time accuracy (10 pts) ----
        travel, *_ = self._load_workspace_data()[:1], None
        # Re-load travel cleanly
        travel_map = {}
        with open(os.path.join(self.workspace, "travel_matrix.csv")) as f:
            reader = csv.DictReader(f)
            zones = [c for c in reader.fieldnames if c != "from_zone"]
            for row in reader:
                fz = row["from_zone"]
                travel_map[fz] = {z: int(row[z]) for z in zones}

        travel_correct = 0
        travel_total = len(common_rids)
        for rid in common_rids:
            agent_a = agent_roster[rid]
            tid = agent_a["technician_id"]
            wid = agent_a["warehouse_id"]

            tech_row = conn.execute(
                "SELECT home_zone FROM technicians WHERE tech_id=?", (tid,),
            ).fetchone()
            req_row = conn.execute(
                "SELECT zone FROM service_requests WHERE request_id=?", (rid,),
            ).fetchone()

            if tech_row and req_row:
                tech_zone = tech_row["home_zone"]
                req_zone = req_row["zone"]
                wh_zone = warehouses[wid]["zone"]
                expected_travel = (
                    travel_map.get(tech_zone, {}).get(req_zone, 0)
                    + travel_map.get(wh_zone, {}).get(req_zone, 0)
                )
                if agent_a["travel_time_minutes"] == expected_travel:
                    travel_correct += 1

        conn.close()

        travel_ratio = travel_correct / travel_total if travel_total else 1.0
        c6_score = int(round(10 * travel_ratio))
        eval_criteria["travel_accuracy"] = {
            "passed": travel_ratio == 1.0,
            "score": c6_score,
            "max_score": 10,
            "reason": (
                ""
                if travel_ratio == 1.0
                else f"{travel_total - travel_correct} assignment(s) have incorrect travel time"
            ),
        }

        # ---- Criterion 7: Summary metrics in response (15 pts) ----
        gt_total_assigned = len(gt_assignments)
        gt_total_unassigned = len(gt_unassigned)
        gt_total_travel = sum(a["travel_time_minutes"] for a in gt_assignments)
        gt_total_wait = sum(a["part_wait_days"] for a in gt_assignments)

        metrics_found = 0
        metrics_total = 4
        if str(gt_total_assigned) in action:
            metrics_found += 1
        if str(gt_total_unassigned) in action:
            metrics_found += 1
        if str(gt_total_travel) in action:
            metrics_found += 1
        if str(gt_total_wait) in action:
            metrics_found += 1

        c7_ratio = metrics_found / metrics_total
        c7_score = int(round(15 * c7_ratio))
        eval_criteria["summary_metrics"] = {
            "passed": c7_ratio == 1.0,
            "score": c7_score,
            "max_score": 15,
            "reason": (
                ""
                if c7_ratio == 1.0
                else f"Only {metrics_found}/{metrics_total} summary metrics found in response"
            ),
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ------------------------------------------------------------------
    # verify  –  self-test
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
        tool_call_count = 0

        # ---- Read workspace config files ----
        travel = {}
        with open(os.path.join(self.workspace, "travel_matrix.csv")) as f:
            reader = csv.DictReader(f)
            zones = [c for c in reader.fieldnames if c != "from_zone"]
            for row in reader:
                fz = row["from_zone"]
                travel[fz] = {z: int(row[z]) for z in zones}

        with open(os.path.join(self.workspace, "dispatch_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "cost_weights.json")) as f:
            weights = json.load(f)

        with open(os.path.join(self.workspace, "seasonal_demand.json")) as f:
            seasonal = json.load(f)

        with open(os.path.join(self.workspace, "warehouse_directory.yaml")) as f:
            warehouses = yaml.safe_load(f)

        # Read batch files
        service_details = {}
        batch_files = sorted(
            glob_module.glob(
                os.path.join(self.workspace, "service_details_batch_*.csv")
            )
        )
        for bf in batch_files:
            with open(bf) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    service_details[int(row["request_id"])] = {
                        "customer_tier": row["customer_tier"],
                        "preferred_day": row["preferred_day"],
                    }

        # ---- Gather data via tools ----

        # List all pending service requests
        all_requests = []
        page = 1
        while True:
            result = self.tools["list_service_requests"](page=page, page_size=20)
            tool_call_count += 1
            all_requests.extend(result["requests"])
            if page * 20 >= result["total"]:
                break
            page += 1

        # List all active technicians
        all_techs = []
        page = 1
        while True:
            result = self.tools["list_technicians"](
                page=page, page_size=20, active_only=True
            )
            tool_call_count += 1
            all_techs.extend(result["technicians"])
            if page * 20 >= result["total"]:
                break
            page += 1

        # Get certifications for each tech
        cert_map: Dict[int, list] = {}
        for t in all_techs:
            result = self.tools["get_technician_certifications"](
                tech_id=t["tech_id"]
            )
            tool_call_count += 1
            cert_map[t["tech_id"]] = result["certifications"]

        # Get required parts for each request
        parts_map: Dict[int, list] = {}
        for req in all_requests:
            result = self.tools["get_required_parts"](
                request_id=req["request_id"]
            )
            tool_call_count += 1
            parts_map[req["request_id"]] = result["parts"]

        # Collect unique part IDs
        unique_parts = set()
        for parts_list in parts_map.values():
            for p in parts_list:
                unique_parts.add(p["part_id"])

        # Check inventory for all (part, warehouse) combos
        inv_cache: Dict[tuple, dict] = {}
        wh_ids = sorted(warehouses.keys())
        for pid in sorted(unique_parts):
            for wid in wh_ids:
                result = self.tools["check_parts_inventory"](
                    part_id=pid, warehouse_id=wid
                )
                tool_call_count += 1
                inv_cache[(pid, wid)] = {
                    "quantity": result["quantity"],
                    "reorder_eta_days": result["reorder_eta_days"],
                }

        # ---- Run assignment algorithm ----
        assignments, unassigned = self._run_assignment(
            all_requests, all_techs, cert_map, parts_map, inv_cache,
            travel, policy, weights, seasonal, warehouses, service_details,
        )

        # ---- Write output ----
        roster_path = os.path.join(self.workspace, "assignment_roster.csv")
        fieldnames = [
            "request_id", "technician_id", "warehouse_id", "scheduled_day",
            "travel_time_minutes", "part_wait_days", "assignment_cost",
        ]
        with open(roster_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for a in assignments:
                writer.writerow(a)

        total_travel = sum(a["travel_time_minutes"] for a in assignments)
        total_wait = sum(a["part_wait_days"] for a in assignments)

        action = (
            f"Weekly technician dispatch roster has been generated and saved as "
            f"assignment_roster.csv. "
            f"Total requests assigned: {len(assignments)}. "
            f"Unassigned requests: {len(unassigned)}. "
            f"Total travel time: {total_travel} minutes. "
            f"Total part wait days: {total_wait}."
        )

        assert tool_call_count >= 15, (
            f"Only {tool_call_count} tool calls made, need at least 15"
        )

        return self.step(action)
