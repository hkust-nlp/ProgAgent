"""Yard crane deployment optimization environment."""

from typing import Tuple, Dict, List, Any
import sqlite3
import os
import json
import csv
import glob as glob_mod
from datetime import datetime, timedelta
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

    # ==================================================================
    # TOOLS
    # ==================================================================

    @tool(
        description="List vessels in the terminal. Supports filtering by status. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by vessel status: berthed, incoming, departed. Omit for all.",
                    "enum": ["berthed", "incoming", "departed"],
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 50). Default 20.",
                },
            },
            "required": [],
        },
    )
    def list_vessels(self, status: str = None, page: int = 1, page_size: int = 20):
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if status:
            rows = conn.execute(
                "SELECT * FROM vessels WHERE status=? ORDER BY vessel_id",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM vessels ORDER BY vessel_id").fetchall()
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start : start + page_size]
        return {
            "vessels": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, -(-total // page_size)),
        }

    @tool(
        description="Get detailed information for a single vessel by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "vessel_id": {
                    "type": "string",
                    "description": "Vessel identifier, e.g. V-0001.",
                }
            },
            "required": ["vessel_id"],
        },
    )
    def get_vessel_details(self, vessel_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM vessels WHERE vessel_id=?", (vessel_id,)).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Vessel {vessel_id} not found"}
        return dict(row)

    @tool(
        description="Search containers with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "vessel_id": {
                    "type": "string",
                    "description": "Filter by vessel ID.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by container status: pending_discharge, pending_load, completed, in_transit.",
                },
                "yard_block": {
                    "type": "string",
                    "description": "Filter by yard block, e.g. A1.",
                },
                "page": {"type": "integer", "description": "Page number (1-based). Default 1."},
                "page_size": {"type": "integer", "description": "Results per page (max 50). Default 20."},
            },
            "required": [],
        },
    )
    def search_containers(
        self,
        vessel_id: str = None,
        status: str = None,
        yard_block: str = None,
        page: int = 1,
        page_size: int = 20,
    ):
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        clauses, params = [], []
        if vessel_id:
            clauses.append("vessel_id=?")
            params.append(vessel_id)
        if status:
            clauses.append("status=?")
            params.append(status)
        if yard_block:
            clauses.append("yard_block=?")
            params.append(yard_block)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM containers{where} ORDER BY container_id", params
        ).fetchall()
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start : start + page_size]
        return {
            "containers": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, -(-total // page_size)),
        }

    @tool(
        description="Get full details for a single container by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "container_id": {
                    "type": "string",
                    "description": "Container identifier, e.g. CNTR-000001.",
                }
            },
            "required": ["container_id"],
        },
    )
    def get_container_info(self, container_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM containers WHERE container_id=?", (container_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Container {container_id} not found"}
        return dict(row)

    @tool(
        description="Retrieve crane maintenance log entries for a specific crane.",
        parameters={
            "type": "object",
            "properties": {
                "crane_id": {
                    "type": "string",
                    "description": "Crane identifier, e.g. YC-01.",
                }
            },
            "required": ["crane_id"],
        },
    )
    def get_crane_maintenance_log(self, crane_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM crane_maintenance WHERE crane_id=? ORDER BY start_time DESC",
            (crane_id,),
        ).fetchall()
        conn.close()
        return {"crane_id": crane_id, "records": [dict(r) for r in rows]}

    @tool(
        description="List truck arrivals at terminal gates. Supports filtering by status, container ID, or gate.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by truck status: waiting, processing, completed, no_show.",
                },
                "container_id": {
                    "type": "string",
                    "description": "Filter by associated container ID.",
                },
                "gate_id": {
                    "type": "string",
                    "description": "Filter by gate ID, e.g. GATE-01.",
                },
                "page": {"type": "integer", "description": "Page number (1-based). Default 1."},
                "page_size": {"type": "integer", "description": "Results per page (max 50). Default 20."},
            },
            "required": [],
        },
    )
    def list_truck_arrivals(
        self,
        status: str = None,
        container_id: str = None,
        gate_id: str = None,
        page: int = 1,
        page_size: int = 20,
    ):
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        clauses, params = [], []
        if status:
            clauses.append("status=?")
            params.append(status)
        if container_id:
            clauses.append("container_id=?")
            params.append(container_id)
        if gate_id:
            clauses.append("gate_id=?")
            params.append(gate_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM truck_arrivals{where} ORDER BY truck_id", params
        ).fetchall()
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start : start + page_size]
        return {
            "trucks": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, -(-total // page_size)),
        }

    @tool(
        description="Get a summary of containers in a specific yard block.",
        parameters={
            "type": "object",
            "properties": {
                "block_id": {
                    "type": "string",
                    "description": "Yard block identifier, e.g. A1.",
                }
            },
            "required": ["block_id"],
        },
    )
    def get_yard_block_summary(self, block_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM containers WHERE yard_block=? GROUP BY status",
            (block_id,),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM containers WHERE yard_block=?", (block_id,)
        ).fetchone()[0]
        conn.close()
        return {
            "block_id": block_id,
            "total_containers": total,
            "by_status": {r["status"]: r["cnt"] for r in rows},
        }

    # ==================================================================
    # GROUND TRUTH COMPUTATION (shared by step and verify helpers)
    # ==================================================================

    def _compute_ground_truth(self):
        """Compute the expected worklist using DB + workspace files."""

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # --- config files ---
        with open(os.path.join(self.workspace, "priority_rules.yaml")) as f:
            rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "shift_config.json")) as f:
            shift_cfg = json.load(f)
        with open(os.path.join(self.workspace, "terminal_layout.json")) as f:
            layout = json.load(f)
        with open(os.path.join(self.workspace, "crane_specs.yaml")) as f:
            crane_specs = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "maintenance_schedule.yaml")) as f:
            maint_sched = yaml.safe_load(f)

        shift_start = datetime.fromisoformat(shift_cfg["shift_start"])
        shift_end = datetime.fromisoformat(shift_cfg["shift_end"])
        buffer_min = rules["crane_rules"]["maintenance_buffer_minutes"]
        block_zone = layout["block_zone_map"]
        scoring = rules["scoring"]
        seq_weight = scoring["sequence_weight"]

        # --- berthed vessels ---
        berthed = [dict(r) for r in conn.execute(
            "SELECT * FROM vessels WHERE status='berthed'").fetchall()]
        vessel_map = {v["vessel_id"]: v for v in berthed}

        # --- actionable containers ---
        vids = list(vessel_map.keys())
        if not vids:
            conn.close()
            return []
        ph = ",".join("?" * len(vids))
        containers = [dict(r) for r in conn.execute(
            f"SELECT * FROM containers WHERE vessel_id IN ({ph}) "
            f"AND status IN ('pending_discharge','pending_load') ORDER BY container_id",
            vids).fetchall()]

        # --- GPS: resolve NULL yard_block ---
        gps_latest = {}  # container_id -> (timestamp, detected_block)
        for fp in sorted(glob_mod.glob(os.path.join(self.workspace, "gps_position_log_*.csv"))):
            with open(fp) as f:
                for row in csv.DictReader(f):
                    cid = row["container_id"]
                    ts = row["timestamp"]
                    if cid not in gps_latest or ts > gps_latest[cid][0]:
                        gps_latest[cid] = (ts, row["detected_block"])

        for c in containers:
            if c["yard_block"] is None:
                if c["container_id"] in gps_latest:
                    c["yard_block"] = gps_latest[c["container_id"]][1]
                else:
                    c["yard_block"] = "A1"  # fallback

        # --- stowage plan sequences ---
        seq_map = {}  # container_id -> sequence number
        for fp in sorted(glob_mod.glob(os.path.join(self.workspace, "stowage_plan_*.json"))):
            with open(fp) as f:
                plan = json.load(f)
            for entry in plan.get("discharge_plan", []):
                seq_map[entry["container_id"]] = entry["sequence"]
            for entry in plan.get("load_plan", []):
                seq_map[entry["container_id"]] = entry["sequence"]

        # --- truck bonus ---
        # DB trucks with active status
        db_active_cids = set()
        db_completed_cids = set()
        for row in conn.execute("SELECT container_id, status FROM truck_arrivals").fetchall():
            cid, st = row
            if st in ("waiting", "processing"):
                db_active_cids.add(cid)
            elif st == "completed":
                db_completed_cids.add(cid)

        # Workspace manifest trucks scheduled within shift
        ws_truck_cids = set()
        for fp in sorted(glob_mod.glob(os.path.join(self.workspace, "truck_manifest_batch_*.csv"))):
            with open(fp) as f:
                for row in csv.DictReader(f):
                    try:
                        sched = datetime.fromisoformat(row["scheduled_arrival"])
                    except (ValueError, KeyError):
                        continue
                    if shift_start <= sched <= shift_end:
                        ws_truck_cids.add(row["container_id"])

        truck_bonus_cids = set()
        for cid in set(c["container_id"] for c in containers):
            if cid in db_active_cids:
                truck_bonus_cids.add(cid)
            elif cid in ws_truck_cids and cid not in db_completed_cids:
                truck_bonus_cids.add(cid)

        # --- crane availability ---
        crane_unavailable = set()
        # DB maintenance
        for row in conn.execute("SELECT crane_id, start_time, end_time FROM crane_maintenance "
                                "WHERE status IN ('in_progress','scheduled')").fetchall():
            crid, st, et = row
            m_start = datetime.fromisoformat(st) - timedelta(minutes=buffer_min)
            m_end = datetime.fromisoformat(et)
            if m_start < shift_end and m_end > shift_start:
                crane_unavailable.add(crid)
        # Workspace scheduled maintenance
        for entry in maint_sched.get("scheduled_maintenance", []):
            m_start = datetime.fromisoformat(entry["start_time"]) - timedelta(minutes=buffer_min)
            m_end = datetime.fromisoformat(entry["end_time"])
            if m_start < shift_end and m_end > shift_start:
                crane_unavailable.add(entry["crane_id"])

        conn.close()

        # --- compute urgency scores ---
        worklist_raw = []
        for c in containers:
            cid = c["container_id"]
            vid = c["vessel_id"]
            vessel = vessel_map[vid]
            dep = datetime.fromisoformat(vessel["departure_deadline"])
            hours_to_dep = (dep - shift_start).total_seconds() / 3600.0

            # deadline score
            deadline_score = 0
            for tier in scoring["deadline_tiers"]:
                if hours_to_dep <= tier["max_hours"]:
                    deadline_score = tier["score"]
                    break

            truck_score = scoring["truck_waiting_bonus"] if cid in truck_bonus_cids else 0
            hazmat_score = scoring["hazmat_bonus"] if c["is_hazmat"] else 0
            reefer_score = scoring["reefer_bonus"] if c["is_reefer"] else 0

            seq_num = seq_map.get(cid, 1)
            sequence_score = max(0, seq_weight - (seq_num - 1))

            urgency = deadline_score + truck_score + hazmat_score + reefer_score + sequence_score

            op_type = "discharge" if c["status"] == "pending_discharge" else "load"
            duration = (rules["duration_estimates"]["time_20ft_minutes"]
                        if c["size_ft"] == 20
                        else rules["duration_estimates"]["time_40ft_minutes"])

            worklist_raw.append({
                "container_id": cid,
                "vessel_id": vid,
                "vessel_name": vessel["name"],
                "operation_type": op_type,
                "yard_block": c["yard_block"],
                "size_ft": c["size_ft"],
                "weight_tons": c["weight_tons"],
                "urgency_score": urgency,
                "departure_deadline": vessel["departure_deadline"],
                "estimated_duration_min": duration,
            })

        # sort
        worklist_raw.sort(key=lambda x: (-x["urgency_score"],
                                          x["departure_deadline"],
                                          x["container_id"]))

        # --- greedy crane assignment ---
        crane_list = crane_specs["cranes"]
        crane_zone_map = {cr["crane_id"]: cr["zone"] for cr in crane_list}
        crane_cap_map = {cr["crane_id"]: cr["max_capacity_tons"] for cr in crane_list}
        crane_load = {cr["crane_id"]: 0 for cr in crane_list}

        final_worklist = []
        for rank, item in enumerate(worklist_raw, 1):
            zone = block_zone.get(item["yard_block"])
            candidates = [
                cr["crane_id"] for cr in crane_list
                if cr["zone"] == zone
                and cr["crane_id"] not in crane_unavailable
                and cr["max_capacity_tons"] >= item["weight_tons"]
            ]
            if candidates:
                candidates.sort(key=lambda cid: (crane_load[cid], cid))
                assigned = candidates[0]
                crane_load[assigned] += 1
            else:
                assigned = "NONE"

            final_worklist.append({
                "priority_rank": rank,
                "crane_id": assigned,
                "container_id": item["container_id"],
                "vessel_id": item["vessel_id"],
                "vessel_name": item["vessel_name"],
                "operation_type": item["operation_type"],
                "yard_block": item["yard_block"],
                "estimated_duration_min": item["estimated_duration_min"],
                "urgency_score": item["urgency_score"],
            })

        return final_worklist

    # ==================================================================
    # STEP
    # ==================================================================

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
        expected = self._compute_ground_truth()
        expected_by_cid = {e["container_id"]: e for e in expected}
        expected_cids = set(expected_by_cid.keys())

        criteria = {}

        # ---- 1. Worklist structure (10 pts) ----
        wl_path = os.path.join(self.workspace, "crane_worklist.csv")
        EXPECTED_COLS = [
            "priority_rank", "crane_id", "container_id", "vessel_id",
            "vessel_name", "operation_type", "yard_block",
            "estimated_duration_min", "urgency_score",
        ]
        agent_rows = []
        struct_ok = False
        if os.path.exists(wl_path):
            try:
                with open(wl_path) as f:
                    reader = csv.DictReader(f)
                    cols = list(reader.fieldnames or [])
                    agent_rows = list(reader)
                if cols == EXPECTED_COLS:
                    struct_ok = True
                    reason = ""
                else:
                    reason = f"Column mismatch: got {cols}"
            except Exception as e:
                reason = str(e)
        else:
            reason = "crane_worklist.csv not found"

        criteria["worklist_structure"] = {
            "passed": struct_ok,
            "score": 10 if struct_ok else 0,
            "max_score": 10,
            "reason": reason if not struct_ok else "",
        }

        # ---- 2. Container coverage (20 pts) ----
        agent_cids = set()
        for r in agent_rows:
            agent_cids.add(r.get("container_id", ""))
        missing = expected_cids - agent_cids
        extra = agent_cids - expected_cids
        if expected_cids:
            coverage_ratio = max(0.0, 1.0 - (len(missing) + len(extra)) / len(expected_cids))
        else:
            coverage_ratio = 1.0 if not agent_cids else 0.0
        cov_score = round(20 * coverage_ratio, 2)
        criteria["container_coverage"] = {
            "passed": coverage_ratio == 1.0,
            "score": cov_score,
            "max_score": 20,
            "reason": f"missing={len(missing)}, extra={len(extra)}" if coverage_ratio < 1 else "",
        }

        # ---- 3. Urgency scoring (25 pts) ----
        score_matches = 0
        score_total = 0
        for r in agent_rows:
            cid = r.get("container_id", "")
            if cid in expected_by_cid:
                score_total += 1
                try:
                    agent_urg = int(float(r.get("urgency_score", -1)))
                except (ValueError, TypeError):
                    agent_urg = -1
                if agent_urg == expected_by_cid[cid]["urgency_score"]:
                    score_matches += 1
        if score_total > 0:
            urg_ratio = score_matches / score_total
        else:
            urg_ratio = 0.0
        urg_score = round(25 * urg_ratio, 2)
        criteria["urgency_scoring"] = {
            "passed": urg_ratio == 1.0,
            "score": urg_score,
            "max_score": 25,
            "reason": f"{score_matches}/{score_total} correct" if urg_ratio < 1 else "",
        }

        # ---- 4. Crane assignment validity (20 pts) ----
        with open(os.path.join(self.workspace, "terminal_layout.json")) as f:
            layout = json.load(f)
        with open(os.path.join(self.workspace, "crane_specs.yaml")) as f:
            crane_specs = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "maintenance_schedule.yaml")) as f:
            maint_sched = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "shift_config.json")) as f:
            shift_cfg = json.load(f)
        with open(os.path.join(self.workspace, "priority_rules.yaml")) as f:
            rules = yaml.safe_load(f)

        block_zone = layout["block_zone_map"]
        crane_zone_map = {cr["crane_id"]: cr["zone"] for cr in crane_specs["cranes"]}
        crane_cap_map = {cr["crane_id"]: cr["max_capacity_tons"] for cr in crane_specs["cranes"]}

        shift_start = datetime.fromisoformat(shift_cfg["shift_start"])
        shift_end = datetime.fromisoformat(shift_cfg["shift_end"])
        buffer_min = rules["crane_rules"]["maintenance_buffer_minutes"]

        crane_unavailable = set()
        conn = sqlite3.connect(self.db_path)
        for row in conn.execute(
                "SELECT crane_id, start_time, end_time FROM crane_maintenance "
                "WHERE status IN ('in_progress','scheduled')").fetchall():
            crid, st, et = row
            m_start = datetime.fromisoformat(st) - timedelta(minutes=buffer_min)
            m_end = datetime.fromisoformat(et)
            if m_start < shift_end and m_end > shift_start:
                crane_unavailable.add(crid)
        conn.close()
        for entry in maint_sched.get("scheduled_maintenance", []):
            m_start = datetime.fromisoformat(entry["start_time"]) - timedelta(minutes=buffer_min)
            m_end = datetime.fromisoformat(entry["end_time"])
            if m_start < shift_end and m_end > shift_start:
                crane_unavailable.add(entry["crane_id"])

        valid_assignments = 0
        assign_total = 0
        for r in agent_rows:
            cid = r.get("container_id", "")
            crane = r.get("crane_id", "")
            blk = r.get("yard_block", "")
            if cid not in expected_by_cid:
                continue
            assign_total += 1
            if crane == "NONE":
                # Check if no crane was indeed available
                exp_crane = expected_by_cid[cid]["crane_id"]
                if exp_crane == "NONE":
                    valid_assignments += 1
                continue
            zone = block_zone.get(blk)
            w = expected_by_cid[cid].get("weight_tons",
                    self._get_container_weight(cid))
            if (crane not in crane_unavailable
                    and crane_zone_map.get(crane) == zone
                    and crane_cap_map.get(crane, 0) >= w):
                valid_assignments += 1

        if assign_total > 0:
            crane_ratio = valid_assignments / assign_total
        else:
            crane_ratio = 0.0
        crane_score = round(20 * crane_ratio, 2)
        criteria["crane_validity"] = {
            "passed": crane_ratio == 1.0,
            "score": crane_score,
            "max_score": 20,
            "reason": f"{valid_assignments}/{assign_total} valid" if crane_ratio < 1 else "",
        }

        # ---- 5. Priority ordering (10 pts) ----
        order_ok = True
        if len(agent_rows) >= 2:
            for i in range(len(agent_rows) - 1):
                try:
                    s1 = int(float(agent_rows[i].get("urgency_score", 0)))
                    s2 = int(float(agent_rows[i + 1].get("urgency_score", 0)))
                except (ValueError, TypeError):
                    order_ok = False
                    break
                if s1 < s2:
                    order_ok = False
                    break
                if s1 == s2:
                    d1 = agent_rows[i].get("departure_deadline_sort", agent_rows[i].get("container_id", ""))
                    d2 = agent_rows[i + 1].get("departure_deadline_sort", agent_rows[i + 1].get("container_id", ""))
                    # relaxed: just check urgency desc is maintained
        else:
            order_ok = len(agent_rows) > 0

        # Stricter: compare against expected order
        expected_order = [e["container_id"] for e in expected]
        agent_order = [r.get("container_id", "") for r in agent_rows]
        if agent_order == expected_order:
            order_perfect = True
        else:
            order_perfect = False

        # Give full points for urgency-descending, partial deduction if not perfectly matching
        if agent_order == expected_order:
            ord_score = 10
        elif order_ok:
            ord_score = 7  # urgency descending correct but tiebreakers differ
        else:
            ord_score = 0
        criteria["priority_ordering"] = {
            "passed": agent_order == expected_order,
            "score": ord_score,
            "max_score": 10,
            "reason": "" if order_perfect else "Order does not exactly match expected tiebreakers" if order_ok else "Urgency scores not in descending order",
        }

        # ---- 6. Summary report (15 pts) ----
        sr_path = os.path.join(self.workspace, "summary_report.json")
        sr_score = 0
        sr_reasons = []
        if os.path.exists(sr_path):
            try:
                with open(sr_path) as f:
                    summary = json.load(f)

                # Expected summary values
                exp_total = len(expected)
                exp_vessels = sorted(set(e["vessel_name"] for e in expected))
                exp_cranes = len(set(e["crane_id"] for e in expected if e["crane_id"] != "NONE"))
                exp_avg_urg = round(sum(e["urgency_score"] for e in expected) / max(1, len(expected)), 2)
                exp_critical = sum(1 for e in expected if e["urgency_score"] >= 70)
                exp_total_hours = round(sum(e["estimated_duration_min"] for e in expected) / 60.0, 2)

                # Check each field (3 pts each, 5 fields)
                if summary.get("total_operations") == exp_total:
                    sr_score += 3
                else:
                    sr_reasons.append(f"total_operations: expected {exp_total}")

                agent_vessels = sorted(summary.get("vessels_served", []))
                if agent_vessels == exp_vessels:
                    sr_score += 3
                else:
                    sr_reasons.append(f"vessels_served mismatch")

                if summary.get("cranes_deployed") == exp_cranes:
                    sr_score += 3
                else:
                    sr_reasons.append(f"cranes_deployed: expected {exp_cranes}")

                try:
                    agent_avg = round(float(summary.get("average_urgency_score", -1)), 2)
                except (ValueError, TypeError):
                    agent_avg = -1
                if abs(agent_avg - exp_avg_urg) < 0.05:
                    sr_score += 3
                else:
                    sr_reasons.append(f"average_urgency_score: expected {exp_avg_urg}")

                if summary.get("critical_operations") == exp_critical:
                    sr_score += 3
                else:
                    sr_reasons.append(f"critical_operations: expected {exp_critical}")

            except Exception as e:
                sr_reasons.append(f"Parse error: {e}")
        else:
            sr_reasons.append("summary_report.json not found")

        criteria["summary_report"] = {
            "passed": sr_score == 15,
            "score": sr_score,
            "max_score": 15,
            "reason": "; ".join(sr_reasons) if sr_reasons else "",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    def _get_container_weight(self, container_id):
        """Helper to get container weight from DB."""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT weight_tons FROM containers WHERE container_id=?",
            (container_id,)).fetchone()
        conn.close()
        return row[0] if row else 0

    # ==================================================================
    # VERIFY
    # ==================================================================

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
        tool_calls = 0

        def call_tool(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        # --- Read workspace config files ---
        with open(os.path.join(self.workspace, "priority_rules.yaml")) as f:
            rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "shift_config.json")) as f:
            shift_cfg = json.load(f)
        with open(os.path.join(self.workspace, "terminal_layout.json")) as f:
            layout = json.load(f)
        with open(os.path.join(self.workspace, "crane_specs.yaml")) as f:
            crane_specs = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "maintenance_schedule.yaml")) as f:
            maint_sched = yaml.safe_load(f)

        shift_start = datetime.fromisoformat(shift_cfg["shift_start"])
        shift_end = datetime.fromisoformat(shift_cfg["shift_end"])
        buffer_min = rules["crane_rules"]["maintenance_buffer_minutes"]
        block_zone = layout["block_zone_map"]
        scoring = rules["scoring"]
        seq_weight = scoring["sequence_weight"]

        # --- 1. Get berthed vessels ---
        all_berthed = []
        res = call_tool("list_vessels", status="berthed", page=1, page_size=50)
        all_berthed.extend(res["vessels"])
        for pg in range(2, res["total_pages"] + 1):
            r2 = call_tool("list_vessels", status="berthed", page=pg, page_size=50)
            all_berthed.extend(r2["vessels"])

        # Get detailed vessel info
        vessel_map = {}
        for v in all_berthed:
            details = call_tool("get_vessel_details", vessel_id=v["vessel_id"])
            vessel_map[v["vessel_id"]] = details

        # --- 2. Get actionable containers ---
        all_containers = []
        for vid in vessel_map:
            for st in ("pending_discharge", "pending_load"):
                pg = 1
                while True:
                    res = call_tool("search_containers", vessel_id=vid, status=st,
                                    page=pg, page_size=50)
                    all_containers.extend(res["containers"])
                    if pg >= res["total_pages"]:
                        break
                    pg += 1

        # --- 3. GPS: resolve NULL yard_block ---
        gps_latest = {}
        for fp in sorted(glob_mod.glob(os.path.join(self.workspace, "gps_position_log_*.csv"))):
            with open(fp) as f:
                for row in csv.DictReader(f):
                    cid = row["container_id"]
                    ts = row["timestamp"]
                    if cid not in gps_latest or ts > gps_latest[cid][0]:
                        gps_latest[cid] = (ts, row["detected_block"])

        for c in all_containers:
            if c["yard_block"] is None:
                if c["container_id"] in gps_latest:
                    c["yard_block"] = gps_latest[c["container_id"]][1]
                else:
                    c["yard_block"] = "A1"

        # --- 4. Stowage plan sequences ---
        seq_map = {}
        for fp in sorted(glob_mod.glob(os.path.join(self.workspace, "stowage_plan_*.json"))):
            with open(fp) as f:
                plan = json.load(f)
            for entry in plan.get("discharge_plan", []):
                seq_map[entry["container_id"]] = entry["sequence"]
            for entry in plan.get("load_plan", []):
                seq_map[entry["container_id"]] = entry["sequence"]

        # --- 5. Truck bonus ---
        # DB: active trucks
        db_active_cids = set()
        db_completed_cids = set()
        for st_filter in ("waiting", "processing"):
            pg = 1
            while True:
                res = call_tool("list_truck_arrivals", status=st_filter, page=pg, page_size=50)
                for t in res["trucks"]:
                    db_active_cids.add(t["container_id"])
                if pg >= res["total_pages"]:
                    break
                pg += 1
        pg = 1
        while True:
            res = call_tool("list_truck_arrivals", status="completed", page=pg, page_size=50)
            for t in res["trucks"]:
                db_completed_cids.add(t["container_id"])
            if pg >= res["total_pages"]:
                break
            pg += 1

        # Workspace manifests
        ws_truck_cids = set()
        for fp in sorted(glob_mod.glob(os.path.join(self.workspace, "truck_manifest_batch_*.csv"))):
            with open(fp) as f:
                for row in csv.DictReader(f):
                    try:
                        sched = datetime.fromisoformat(row["scheduled_arrival"])
                    except (ValueError, KeyError):
                        continue
                    if shift_start <= sched <= shift_end:
                        ws_truck_cids.add(row["container_id"])

        truck_bonus_cids = set()
        action_cids = {c["container_id"] for c in all_containers}
        for cid in action_cids:
            if cid in db_active_cids:
                truck_bonus_cids.add(cid)
            elif cid in ws_truck_cids and cid not in db_completed_cids:
                truck_bonus_cids.add(cid)

        # --- 6. Crane maintenance ---
        crane_unavailable = set()
        for cr in crane_specs["cranes"]:
            maint_res = call_tool("get_crane_maintenance_log", crane_id=cr["crane_id"])
            for rec in maint_res["records"]:
                if rec["status"] in ("in_progress", "scheduled"):
                    m_start = datetime.fromisoformat(rec["start_time"]) - timedelta(minutes=buffer_min)
                    m_end = datetime.fromisoformat(rec["end_time"])
                    if m_start < shift_end and m_end > shift_start:
                        crane_unavailable.add(cr["crane_id"])
        # Workspace scheduled maintenance
        for entry in maint_sched.get("scheduled_maintenance", []):
            m_start = datetime.fromisoformat(entry["start_time"]) - timedelta(minutes=buffer_min)
            m_end = datetime.fromisoformat(entry["end_time"])
            if m_start < shift_end and m_end > shift_start:
                crane_unavailable.add(entry["crane_id"])

        # --- 7. Compute urgency scores ---
        worklist_raw = []
        for c in all_containers:
            cid = c["container_id"]
            vid = c["vessel_id"]
            vessel = vessel_map[vid]
            dep = datetime.fromisoformat(vessel["departure_deadline"])
            hours_to_dep = (dep - shift_start).total_seconds() / 3600.0

            deadline_score = 0
            for tier in scoring["deadline_tiers"]:
                if hours_to_dep <= tier["max_hours"]:
                    deadline_score = tier["score"]
                    break

            truck_score = scoring["truck_waiting_bonus"] if cid in truck_bonus_cids else 0
            hazmat_score = scoring["hazmat_bonus"] if c["is_hazmat"] else 0
            reefer_score = scoring["reefer_bonus"] if c["is_reefer"] else 0
            seq_num = seq_map.get(cid, 1)
            sequence_score = max(0, seq_weight - (seq_num - 1))

            urgency = deadline_score + truck_score + hazmat_score + reefer_score + sequence_score

            op_type = "discharge" if c["status"] == "pending_discharge" else "load"
            duration = (rules["duration_estimates"]["time_20ft_minutes"]
                        if c["size_ft"] == 20
                        else rules["duration_estimates"]["time_40ft_minutes"])

            worklist_raw.append({
                "container_id": cid,
                "vessel_id": vid,
                "vessel_name": vessel["name"],
                "operation_type": op_type,
                "yard_block": c["yard_block"],
                "weight_tons": c["weight_tons"],
                "urgency_score": urgency,
                "departure_deadline": vessel["departure_deadline"],
                "estimated_duration_min": duration,
            })

        worklist_raw.sort(key=lambda x: (-x["urgency_score"],
                                          x["departure_deadline"],
                                          x["container_id"]))

        # --- 8. Greedy crane assignment ---
        crane_load = {cr["crane_id"]: 0 for cr in crane_specs["cranes"]}
        final_worklist = []
        for rank, item in enumerate(worklist_raw, 1):
            zone = block_zone.get(item["yard_block"])
            candidates = [
                cr["crane_id"] for cr in crane_specs["cranes"]
                if cr["zone"] == zone
                and cr["crane_id"] not in crane_unavailable
                and cr["max_capacity_tons"] >= item["weight_tons"]
            ]
            if candidates:
                candidates.sort(key=lambda cid: (crane_load[cid], cid))
                assigned = candidates[0]
                crane_load[assigned] += 1
            else:
                assigned = "NONE"

            final_worklist.append({
                "priority_rank": rank,
                "crane_id": assigned,
                "container_id": item["container_id"],
                "vessel_id": item["vessel_id"],
                "vessel_name": item["vessel_name"],
                "operation_type": item["operation_type"],
                "yard_block": item["yard_block"],
                "estimated_duration_min": item["estimated_duration_min"],
                "urgency_score": item["urgency_score"],
            })

        # --- 9. Write deliverables ---
        wl_path = os.path.join(self.workspace, "crane_worklist.csv")
        with open(wl_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "priority_rank", "crane_id", "container_id", "vessel_id",
                "vessel_name", "operation_type", "yard_block",
                "estimated_duration_min", "urgency_score",
            ])
            writer.writeheader()
            writer.writerows(final_worklist)

        # Summary
        total_ops = len(final_worklist)
        vessels_served = sorted(set(e["vessel_name"] for e in final_worklist))
        cranes_deployed = len(set(e["crane_id"] for e in final_worklist if e["crane_id"] != "NONE"))
        avg_urgency = round(sum(e["urgency_score"] for e in final_worklist) / max(1, total_ops), 2)
        critical_ops = sum(1 for e in final_worklist if e["urgency_score"] >= 70)
        est_total_hours = round(sum(e["estimated_duration_min"] for e in final_worklist) / 60.0, 2)

        summary = {
            "total_operations": total_ops,
            "vessels_served": vessels_served,
            "cranes_deployed": cranes_deployed,
            "average_urgency_score": avg_urgency,
            "critical_operations": critical_ops,
            "estimated_total_hours": est_total_hours,
        }
        with open(os.path.join(self.workspace, "summary_report.json"), "w") as f:
            json.dump(summary, f, indent=2)

        # --- 10. Construct action string ---
        action = (
            f"Worklist generated with {total_ops} operations across "
            f"{len(vessels_served)} vessels using {cranes_deployed} cranes. "
            f"Average urgency score: {avg_urgency}. "
            f"Critical operations (score >= 70): {critical_ops}. "
            f"Estimated total crane-hours: {est_total_hours}."
        )

        assert tool_calls >= 15, f"Only {tool_calls} tool calls made, need at least 15"

        return self.step(action)
