"""
Technical Support Ticket Routing - Environment
"""

import sqlite3
import json
import os
import csv
import re
import glob
import math
from typing import Tuple, Dict, List, Any
from datetime import datetime


# ---------------------------------------------------------------------------
# @tool decorator  (keep unchanged)
# ---------------------------------------------------------------------------

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ---------------------------------------------------------------------------
# Task_Env
# ---------------------------------------------------------------------------

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

    # ===================================================================
    # Tool methods
    # ===================================================================

    @tool(
        description=(
            "Returns a paginated list of pending support tickets. Each entry "
            "contains ticket_id, title, priority, customer_id, and created_at. "
            "Does not include the error code or full description."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def get_pending_tickets(self, page: int = 1, page_size: int = 20) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM tickets WHERE status='pending'"
        )
        total = c.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        c.execute(
            "SELECT ticket_id, title, priority, customer_id, created_at "
            "FROM tickets WHERE status='pending' "
            "ORDER BY priority DESC, ticket_id ASC "
            "LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps({
            "tickets": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Looks up a product by its SKU and returns product_id, sku, name, "
            "category, and support_tier."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sku": {
                    "type": "string",
                    "description": "The product SKU to look up.",
                },
            },
            "required": ["sku"],
        },
    )
    def lookup_product(self, sku: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM products WHERE sku=?", (sku,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return _envelope({"error": f"No product found with SKU '{sku}'."})
        return _envelope(dict(row))

    @tool(
        description=(
            "Returns a paginated list of engineers, optionally filtered by shift "
            "and/or active status. Each entry contains engineer_id, name, email, "
            "team, shift, is_active, and max_queue_size."
        ),
        parameters={
            "type": "object",
            "properties": {
                "shift": {
                    "type": "string",
                    "description": "Filter by shift: morning, afternoon, or night.",
                },
                "is_active": {
                    "type": "boolean",
                    "description": "Filter by active status.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def list_engineers(
        self,
        shift: str = None,
        is_active: bool = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        clauses = []
        params: list = []
        if shift is not None:
            clauses.append("shift=?")
            params.append(shift)
        if is_active is not None:
            clauses.append("is_active=?")
            params.append(int(is_active))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        c.execute(f"SELECT COUNT(*) FROM engineers{where}", params)
        total = c.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        c.execute(
            f"SELECT * FROM engineers{where} ORDER BY engineer_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps({
            "engineers": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Returns all certification records for a given engineer, including "
            "cert_id, product_category, cert_level, cert_level_num, "
            "certified_date, and expiry_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "engineer_id": {
                    "type": "string",
                    "description": "The engineer ID to look up certifications for.",
                },
            },
            "required": ["engineer_id"],
        },
    )
    def get_engineer_certifications(self, engineer_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT cert_id, product_category, cert_level, cert_level_num, "
            "certified_date, expiry_date "
            "FROM certifications WHERE engineer_id=? ORDER BY product_category",
            (engineer_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return _envelope({"engineer_id": engineer_id, "certifications": rows})

    @tool(
        description=(
            "Returns the current queue depth for an engineer: how many tickets "
            "are currently assigned (in_progress or assigned status), their "
            "max_queue_size, and available capacity."
        ),
        parameters={
            "type": "object",
            "properties": {
                "engineer_id": {
                    "type": "string",
                    "description": "The engineer ID.",
                },
            },
            "required": ["engineer_id"],
        },
    )
    def get_queue_depth(self, engineer_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM tickets "
            "WHERE assigned_to=? AND status IN ('in_progress','assigned')",
            (engineer_id,),
        )
        depth = c.fetchone()[0]
        c.execute(
            "SELECT max_queue_size FROM engineers WHERE engineer_id=?",
            (engineer_id,),
        )
        row = c.fetchone()
        conn.close()
        if row is None:
            return _envelope({"error": f"Engineer '{engineer_id}' not found."})
        return _envelope({
            "engineer_id": engineer_id,
            "current_queue_depth": depth,
            "max_queue_size": row[0],
            "available_capacity": row[0] - depth,
        })

    @tool(
        description=(
            "Assigns a pending ticket to an engineer. Updates the ticket status "
            "to 'assigned' and records the engineer. Returns success/failure."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "The ticket ID to assign.",
                },
                "engineer_id": {
                    "type": "string",
                    "description": "The engineer ID to assign the ticket to.",
                },
            },
            "required": ["ticket_id", "engineer_id"],
        },
    )
    def assign_ticket(self, ticket_id: str, engineer_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Verify ticket exists and is pending
        c.execute(
            "SELECT status FROM tickets WHERE ticket_id=?", (ticket_id,)
        )
        row = c.fetchone()
        if row is None:
            conn.close()
            return json.dumps({"success": False, "message": f"Ticket '{ticket_id}' not found."}, ensure_ascii=False, default=str)
        if row[0] not in ("pending",):
            conn.close()
            return json.dumps({
                "success": False,
                "message": f"Ticket '{ticket_id}' is not pending (status='{row[0]}').",
            }, ensure_ascii=False, default=str)
        # Verify engineer exists
        c.execute(
            "SELECT engineer_id FROM engineers WHERE engineer_id=?",
            (engineer_id,),
        )
        if c.fetchone() is None:
            conn.close()
            return json.dumps({
                "success": False,
                "message": f"Engineer '{engineer_id}' not found.",
            }, ensure_ascii=False, default=str)
        # Perform assignment
        c.execute(
            "UPDATE tickets SET status='assigned', assigned_to=? WHERE ticket_id=?",
            (engineer_id, ticket_id),
        )
        conn.commit()
        conn.close()
        return json.dumps({
            "success": True,
            "ticket_id": ticket_id,
            "engineer_id": engineer_id,
            "message": "Ticket assigned successfully.",
        }, ensure_ascii=False, default=str)

    # ===================================================================
    # Evaluation
    # ===================================================================

    def _compute_ground_truth(self, conn) -> List[Dict[str, Any]]:
        """Compute the deterministic optimal assignment sequence."""
        import pandas as pd

        # Originally-pending tickets (now status pending or assigned)
        pending = pd.read_sql_query(
            "SELECT ticket_id, priority, error_code FROM tickets "
            "WHERE status IN ('pending','assigned') "
            "ORDER BY priority DESC, ticket_id ASC",
            conn,
        )

        # Error code details
        errors = pd.read_sql_query("SELECT code, product_sku, severity FROM error_codes", conn)
        error_map = {r["code"]: r for _, r in errors.iterrows()}

        # Products
        products = pd.read_sql_query("SELECT sku, category FROM products", conn)
        product_map = {r["sku"]: r["category"] for _, r in products.iterrows()}

        # Routing rules from workspace
        with open(os.path.join(self.workspace, "routing_rules.json")) as f:
            rules = json.load(f)
        severity_to_cert = rules["severity_to_cert_level"]

        # Shift schedule
        with open(os.path.join(self.workspace, "shift_schedule.json")) as f:
            shift_info = json.load(f)
        current_shift = shift_info["current_shift"]
        ref_date = shift_info["reference_date"]

        # Eligible engineers
        engineers = pd.read_sql_query(
            "SELECT * FROM engineers WHERE is_active=1 AND shift=?",
            conn,
            params=[current_shift],
        )

        # Valid certifications (not expired as of reference date)
        certs = pd.read_sql_query(
            "SELECT * FROM certifications WHERE expiry_date > ?",
            conn,
            params=[ref_date],
        )

        # Build cert lookup: (engineer_id, category) -> max cert_level_num
        cert_lookup: Dict[tuple, int] = {}
        for _, c in certs.iterrows():
            key = (c["engineer_id"], c["product_category"])
            cert_lookup[key] = max(cert_lookup.get(key, 0), int(c["cert_level_num"]))

        # Initial queue depths (only in_progress — assignments by agent not counted)
        queue_df = pd.read_sql_query(
            "SELECT assigned_to AS engineer_id, COUNT(*) AS depth "
            "FROM tickets WHERE status='in_progress' AND assigned_to IS NOT NULL "
            "GROUP BY assigned_to",
            conn,
        )
        running_queue: Dict[str, int] = dict(
            zip(queue_df["engineer_id"], queue_df["depth"])
        )

        eng_max = dict(zip(engineers["engineer_id"], engineers["max_queue_size"]))
        eng_names = dict(zip(engineers["engineer_id"], engineers["name"]))

        assignments: List[Dict[str, Any]] = []
        for _, ticket in pending.iterrows():
            tid = ticket["ticket_id"]
            ec = ticket["error_code"]
            if ec not in error_map:
                continue
            err = error_map[ec]
            sku = err["product_sku"]
            severity = err["severity"]
            category = product_map.get(sku)
            if category is None:
                continue
            required_level = severity_to_cert.get(severity, 1)

            best_eng = None
            best_queue = float("inf")
            for _, eng in engineers.iterrows():
                eid = eng["engineer_id"]
                cur_q = running_queue.get(eid, 0)
                max_q = int(eng["max_queue_size"])
                if cur_q >= max_q:
                    continue
                clvl = cert_lookup.get((eid, category), 0)
                if clvl < required_level:
                    continue
                if cur_q < best_queue or (
                    cur_q == best_queue and (best_eng is None or eid < best_eng)
                ):
                    best_queue = cur_q
                    best_eng = eid

            if best_eng is not None:
                assignments.append(
                    {
                        "ticket_id": tid,
                        "error_code": ec,
                        "product_sku": sku,
                        "product_category": category,
                        "severity": severity,
                        "required_cert_level": required_level,
                        "assigned_engineer_id": best_eng,
                        "assigned_engineer_name": eng_names.get(best_eng, ""),
                    }
                )
                running_queue[best_eng] = running_queue.get(best_eng, 0) + 1

        return assignments

    def step(
        self, action: str
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
        conn = sqlite3.connect(self.db_path)
        ground_truth = self._compute_ground_truth(conn)
        gt_map = {a["ticket_id"]: a for a in ground_truth}
        num_gt = len(ground_truth)

        criteria: Dict[str, Dict[str, Any]] = {}

        # ------------------------------------------------------------------
        # 1. assignments.csv exists with correct columns  (10 pts)
        # ------------------------------------------------------------------
        csv_path = os.path.join(self.workspace, "assignments.csv")
        expected_cols = [
            "ticket_id",
            "error_code",
            "product_sku",
            "product_category",
            "severity",
            "required_cert_level",
            "assigned_engineer_id",
            "assigned_engineer_name",
        ]
        agent_rows: List[Dict[str, str]] = []
        csv_ok = False
        if os.path.isfile(csv_path):
            try:
                with open(csv_path, newline="") as f:
                    reader = csv.DictReader(f)
                    if reader.fieldnames is not None and all(
                        c in reader.fieldnames for c in expected_cols
                    ):
                        agent_rows = list(reader)
                        csv_ok = True
            except Exception:
                pass

        criteria["assignments_file_format"] = {
            "passed": csv_ok,
            "score": 10 if csv_ok else 0,
            "max_score": 10,
            "reason": "" if csv_ok else "assignments.csv missing or has wrong columns",
        }

        # Build agent map keyed by ticket_id
        agent_map: Dict[str, Dict[str, str]] = {}
        for row in agent_rows:
            agent_map[row["ticket_id"]] = row

        # ------------------------------------------------------------------
        # 2. All pending tickets covered  (10 pts)
        # ------------------------------------------------------------------
        covered = sum(1 for tid in gt_map if tid in agent_map)
        cov_score = round(10 * covered / max(num_gt, 1))
        criteria["all_tickets_covered"] = {
            "passed": covered == num_gt,
            "score": cov_score,
            "max_score": 10,
            "reason": "" if covered == num_gt else f"Covered {covered}/{num_gt} tickets",
        }

        # ------------------------------------------------------------------
        # 3. Error codes correct  (15 pts)
        # ------------------------------------------------------------------
        ec_correct = 0
        for tid, gt in gt_map.items():
            ag = agent_map.get(tid, {})
            if ag.get("error_code") == gt["error_code"]:
                ec_correct += 1
        ec_score = round(15 * ec_correct / max(num_gt, 1))
        criteria["error_codes_correct"] = {
            "passed": ec_correct == num_gt,
            "score": ec_score,
            "max_score": 15,
            "reason": "" if ec_correct == num_gt else f"{ec_correct}/{num_gt} error codes correct",
        }

        # ------------------------------------------------------------------
        # 4. Product SKU + category correct  (15 pts)
        # ------------------------------------------------------------------
        sku_correct = 0
        for tid, gt in gt_map.items():
            ag = agent_map.get(tid, {})
            if (
                ag.get("product_sku") == gt["product_sku"]
                and ag.get("product_category") == gt["product_category"]
            ):
                sku_correct += 1
        sku_score = round(15 * sku_correct / max(num_gt, 1))
        criteria["product_mapping_correct"] = {
            "passed": sku_correct == num_gt,
            "score": sku_score,
            "max_score": 15,
            "reason": "" if sku_correct == num_gt else f"{sku_correct}/{num_gt} SKU/category correct",
        }

        # ------------------------------------------------------------------
        # 5. Assigned engineers have valid certification at required level (20 pts)
        # ------------------------------------------------------------------
        with open(os.path.join(self.workspace, "shift_schedule.json")) as f:
            ref_date = json.load(f)["reference_date"]
        valid_certs = {}
        c = conn.cursor()
        c.execute(
            "SELECT engineer_id, product_category, cert_level_num "
            "FROM certifications WHERE expiry_date > ?",
            (ref_date,),
        )
        for eid, pcat, clvl in c.fetchall():
            key = (eid, pcat)
            valid_certs[key] = max(valid_certs.get(key, 0), clvl)

        cert_ok = 0
        for tid, gt in gt_map.items():
            ag = agent_map.get(tid, {})
            eng_id = ag.get("assigned_engineer_id", "")
            cat = gt["product_category"]
            req = gt["required_cert_level"]
            if valid_certs.get((eng_id, cat), 0) >= req:
                cert_ok += 1
        cert_score = round(20 * cert_ok / max(num_gt, 1))
        criteria["certification_valid"] = {
            "passed": cert_ok == num_gt,
            "score": cert_score,
            "max_score": 20,
            "reason": "" if cert_ok == num_gt else f"{cert_ok}/{num_gt} have valid cert",
        }

        # ------------------------------------------------------------------
        # 6. Optimal assignment (correct engineer)  (20 pts)
        # ------------------------------------------------------------------
        opt_ok = 0
        for tid, gt in gt_map.items():
            ag = agent_map.get(tid, {})
            if ag.get("assigned_engineer_id") == gt["assigned_engineer_id"]:
                opt_ok += 1
        opt_score = round(20 * opt_ok / max(num_gt, 1))
        criteria["optimal_assignment"] = {
            "passed": opt_ok == num_gt,
            "score": opt_score,
            "max_score": 20,
            "reason": "" if opt_ok == num_gt else f"{opt_ok}/{num_gt} match optimal engineer",
        }

        # ------------------------------------------------------------------
        # 7. DB assignments recorded via assign_ticket  (10 pts)
        # ------------------------------------------------------------------
        c.execute(
            "SELECT ticket_id, assigned_to FROM tickets WHERE status='assigned'"
        )
        db_assigned = {r[0]: r[1] for r in c.fetchall()}
        db_ok = 0
        for tid, gt in gt_map.items():
            if db_assigned.get(tid) == gt["assigned_engineer_id"]:
                db_ok += 1
        db_score = round(10 * db_ok / max(num_gt, 1))
        criteria["db_assignments_recorded"] = {
            "passed": db_ok == num_gt,
            "score": db_score,
            "max_score": 10,
            "reason": "" if db_ok == num_gt else f"{db_ok}/{num_gt} recorded in DB",
        }

        conn.close()

        total_score = sum(v["score"] for v in criteria.values())
        max_score = sum(v["max_score"] for v in criteria.values())
        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ===================================================================
    # Verification
    # ===================================================================

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

        def _call(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        # 1. Gather pending tickets (paginated)
        all_pending = []
        page = 1
        while True:
            resp = json.loads(_call("get_pending_tickets", page=page, page_size=20))
            all_pending.extend(resp["tickets"])
            if page >= resp["total_pages"]:
                break
            page += 1

        # 2. Read ticket files -> parse error codes
        ticket_error_map: Dict[str, str] = {}  # ticket_id -> error_code
        for ticket in all_pending:
            tid = ticket["ticket_id"]
            fpath = os.path.join(self.workspace, f"ticket_{tid}.txt")
            if not os.path.isfile(fpath):
                continue
            with open(fpath) as f:
                text = f.read()
            match = re.search(r"ERR-[A-Z]{3}-\d{4}", text)
            if match:
                ticket_error_map[tid] = match.group(0)

        # 3. Read portal logs -> build error_code -> (product_sku, severity) map
        error_info_map: Dict[str, Dict[str, str]] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("portal_log_") and fname.endswith(".csv"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath, newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        ec = row["error_code"]
                        if ec not in error_info_map:
                            error_info_map[ec] = {
                                "product_sku": row["product_sku"],
                                "severity": row["severity"],
                            }

        # 4. Read config files
        with open(os.path.join(self.workspace, "routing_rules.json")) as f:
            rules = json.load(f)
        severity_to_cert = rules["severity_to_cert_level"]

        with open(os.path.join(self.workspace, "shift_schedule.json")) as f:
            shift_info = json.load(f)
        current_shift = shift_info["current_shift"]
        ref_date = shift_info["reference_date"]

        # 5. For each pending ticket, look up product category via tool
        ticket_product_map: Dict[str, dict] = {}  # tid -> {sku, category, severity, req_level}
        for tid in sorted(ticket_error_map.keys()):
            ec = ticket_error_map[tid]
            info = error_info_map.get(ec)
            if info is None:
                continue
            prod = json.loads(_call("lookup_product", sku=info["product_sku"])["content"][0]["text"])
            if "error" in prod:
                continue
            req_level = severity_to_cert.get(info["severity"], 1)
            ticket_product_map[tid] = {
                "error_code": ec,
                "product_sku": info["product_sku"],
                "severity": info["severity"],
                "product_category": prod["category"],
                "required_cert_level": req_level,
            }

        # 6. Get all active engineers on current shift (paginated)
        all_engineers = []
        page = 1
        while True:
            resp = json.loads(_call(
                "list_engineers", shift=current_shift, is_active=True, page=page, page_size=20
            ))
            all_engineers.extend(resp["engineers"])
            if page >= resp["total_pages"]:
                break
            page += 1

        # 7. Get certifications for each engineer
        eng_certs: Dict[str, Dict[str, int]] = {}  # eid -> {category: max_level}
        for eng in all_engineers:
            eid = eng["engineer_id"]
            resp = json.loads(_call("get_engineer_certifications", engineer_id=eid)["content"][0]["text"])
            certs_for_eng: Dict[str, int] = {}
            for cert in resp["certifications"]:
                if cert["expiry_date"] > ref_date:
                    cat = cert["product_category"]
                    certs_for_eng[cat] = max(
                        certs_for_eng.get(cat, 0), cert["cert_level_num"]
                    )
            eng_certs[eid] = certs_for_eng

        # 8. Get initial queue depths for each engineer
        eng_queue: Dict[str, int] = {}
        eng_max: Dict[str, int] = {}
        for eng in all_engineers:
            eid = eng["engineer_id"]
            resp = json.loads(_call("get_queue_depth", engineer_id=eid)["content"][0]["text"])
            eng_queue[eid] = resp["current_queue_depth"]
            eng_max[eid] = resp["max_queue_size"]

        eng_name_map = {e["engineer_id"]: e["name"] for e in all_engineers}

        # 9. Sort pending tickets by priority DESC, ticket_id ASC
        sorted_tickets = sorted(
            all_pending,
            key=lambda t: (-t["priority"], t["ticket_id"]),
        )

        # 10. Assign tickets
        assignments: List[Dict[str, Any]] = []
        for ticket in sorted_tickets:
            tid = ticket["ticket_id"]
            info = ticket_product_map.get(tid)
            if info is None:
                continue
            category = info["product_category"]
            req_level = info["required_cert_level"]

            best_eng = None
            best_queue = float("inf")
            for eng in all_engineers:
                eid = eng["engineer_id"]
                cur_q = eng_queue.get(eid, 0)
                mx = eng_max.get(eid, 0)
                if cur_q >= mx:
                    continue
                clvl = eng_certs.get(eid, {}).get(category, 0)
                if clvl < req_level:
                    continue
                if cur_q < best_queue or (cur_q == best_queue and (best_eng is None or eid < best_eng)):
                    best_queue = cur_q
                    best_eng = eid

            if best_eng is not None:
                result = json.loads(_call("assign_ticket", ticket_id=tid, engineer_id=best_eng))
                if result.get("success"):
                    eng_queue[best_eng] = eng_queue.get(best_eng, 0) + 1
                    assignments.append(
                        {
                            "ticket_id": tid,
                            "error_code": info["error_code"],
                            "product_sku": info["product_sku"],
                            "product_category": info["product_category"],
                            "severity": info["severity"],
                            "required_cert_level": str(info["required_cert_level"]),
                            "assigned_engineer_id": best_eng,
                            "assigned_engineer_name": eng_name_map.get(best_eng, ""),
                        }
                    )

        # 11. Write assignments.csv
        csv_path = os.path.join(self.workspace, "assignments.csv")
        fieldnames = [
            "ticket_id",
            "error_code",
            "product_sku",
            "product_category",
            "severity",
            "required_cert_level",
            "assigned_engineer_id",
            "assigned_engineer_name",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(assignments)

        # 12. Build action string
        action = (
            f"Routed {len(assignments)} pending tickets to qualified engineers. "
            f"All assignments have been recorded in the system and saved to assignments.csv."
        )

        print(f"[verify] total tool calls: {tool_calls}")
        return self.step(action)
