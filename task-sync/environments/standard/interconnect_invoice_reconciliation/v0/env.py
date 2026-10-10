import sqlite3
import os
import json
import csv
import math
import re
import yaml
from typing import Tuple, Dict, List, Any


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

    # ================================================================
    # TOOL METHODS
    # ================================================================

    @tool(
        description="List carriers with optional status filter. Returns a paginated list of carriers.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "inactive", "suspended"],
                    "description": "Filter by carrier status. Omit to list all.",
                },
                "carrier_type": {
                    "type": "string",
                    "enum": ["home", "partner", "wholesale", "transit"],
                    "description": "Filter by carrier type. Omit to list all.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 50). Default 20.",
                },
            },
            "required": [],
        },
    )
    def list_carriers(self, status: str = None, carrier_type: str = None,
                      page: int = 1, page_size: int = 20) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)

        query = "SELECT * FROM carriers WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if carrier_type:
            query += " AND carrier_type = ?"
            params.append(carrier_type)

        # Count
        count_q = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = cur.execute(count_q, params).fetchone()[0]

        query += " ORDER BY carrier_id LIMIT ? OFFSET ?"
        params.extend([page_size, (page - 1) * page_size])
        rows = cur.execute(query, params).fetchall()
        conn.close()

        return {
            "carriers": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size),
        }

    @tool(
        description="Get all switches belonging to a specific carrier.",
        parameters={
            "type": "object",
            "properties": {
                "carrier_id": {
                    "type": "integer",
                    "description": "The carrier ID to look up switches for.",
                },
            },
            "required": ["carrier_id"],
        },
    )
    def get_switches_by_carrier(self, carrier_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM switches WHERE carrier_id = ? ORDER BY switch_id",
            (int(carrier_id),),
        ).fetchall()
        conn.close()
        return {"carrier_id": int(carrier_id), "switches": [dict(r) for r in rows]}

    @tool(
        description="Query call detail records with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "originating_switch_id": {
                    "type": "integer",
                    "description": "Filter by originating switch ID.",
                },
                "terminating_switch_id": {
                    "type": "integer",
                    "description": "Filter by terminating switch ID.",
                },
                "call_type": {
                    "type": "string",
                    "enum": ["local", "long_distance", "international", "mobile"],
                    "description": "Filter by call type.",
                },
                "completion_status": {
                    "type": "string",
                    "enum": ["completed", "failed", "dropped"],
                    "description": "Filter by completion status.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 50). Default 20.",
                },
            },
            "required": [],
        },
    )
    def query_cdrs(self, originating_switch_id: int = None,
                   terminating_switch_id: int = None,
                   call_type: str = None,
                   completion_status: str = None,
                   page: int = 1, page_size: int = 20) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)

        query = "SELECT * FROM cdrs WHERE 1=1"
        params = []
        if originating_switch_id is not None:
            query += " AND originating_switch_id = ?"
            params.append(int(originating_switch_id))
        if terminating_switch_id is not None:
            query += " AND terminating_switch_id = ?"
            params.append(int(terminating_switch_id))
        if call_type:
            query += " AND call_type = ?"
            params.append(call_type)
        if completion_status:
            query += " AND completion_status = ?"
            params.append(completion_status)

        count_q = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = cur.execute(count_q, params).fetchone()[0]

        query += " ORDER BY cdr_id LIMIT ? OFFSET ?"
        params.extend([page_size, (page - 1) * page_size])
        rows = cur.execute(query, params).fetchall()
        conn.close()

        return {
            "cdrs": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size),
        }

    @tool(
        description="Get bilateral agreement rates between two carriers. Returns all call-type rates for the pair.",
        parameters={
            "type": "object",
            "properties": {
                "carrier_a_id": {
                    "type": "integer",
                    "description": "First carrier ID.",
                },
                "carrier_b_id": {
                    "type": "integer",
                    "description": "Second carrier ID.",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "expired"],
                    "description": "Filter by agreement status. Default returns all.",
                },
            },
            "required": ["carrier_a_id", "carrier_b_id"],
        },
    )
    def get_bilateral_rates(self, carrier_a_id: int, carrier_b_id: int,
                            status: str = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        a, b = int(carrier_a_id), int(carrier_b_id)
        query = ("SELECT * FROM bilateral_agreements "
                 "WHERE ((carrier_a_id = ? AND carrier_b_id = ?) "
                 "OR (carrier_a_id = ? AND carrier_b_id = ?))")
        params = [a, b, b, a]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY call_type"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return {"agreements": [dict(r) for r in rows]}

    @tool(
        description="Query disputes with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "carrier_id": {
                    "type": "integer",
                    "description": "Filter disputes involving this carrier (as filing or counter party).",
                },
                "status": {
                    "type": "string",
                    "enum": ["open", "resolved", "rejected"],
                    "description": "Filter by dispute status.",
                },
                "billing_period": {
                    "type": "string",
                    "description": "Filter by billing period (YYYY-MM format).",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 50). Default 20.",
                },
            },
            "required": [],
        },
    )
    def query_disputes(self, carrier_id: int = None, status: str = None,
                       billing_period: str = None,
                       page: int = 1, page_size: int = 20) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)

        query = "SELECT * FROM disputes WHERE 1=1"
        params = []
        if carrier_id is not None:
            query += " AND (filing_carrier_id = ? OR counter_carrier_id = ?)"
            params.extend([int(carrier_id), int(carrier_id)])
        if status:
            query += " AND status = ?"
            params.append(status)
        if billing_period:
            query += " AND billing_period = ?"
            params.append(billing_period)

        count_q = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = cur.execute(count_q, params).fetchone()[0]

        query += " ORDER BY dispute_id LIMIT ? OFFSET ?"
        params.extend([page_size, (page - 1) * page_size])
        rows = cur.execute(query, params).fetchall()
        conn.close()

        return {
            "disputes": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size),
        }

    @tool(
        description="Get routing rule details for a specific route ID.",
        parameters={
            "type": "object",
            "properties": {
                "route_id": {
                    "type": "integer",
                    "description": "The route ID to look up.",
                },
            },
            "required": ["route_id"],
        },
    )
    def get_route_info(self, route_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM routing_rules WHERE route_id = ?",
            (int(route_id),),
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Route {route_id} not found"}

    # ================================================================
    # GROUND-TRUTH COMPUTATION (shared by step & verify)
    # ================================================================

    def _compute_ground_truth(self) -> dict:
        """Compute the full ground-truth settlement using DB + workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load config files
        with open(os.path.join(self.workspace, "settlement_rules.json")) as f:
            rules = json.load(f)
        with open(os.path.join(self.workspace, "rate_adjustments.yaml")) as f:
            adj_data = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "tier_discounts.json")) as f:
            tiers_data = json.load(f)

        billing_period = rules["billing_period"]
        min_duration = rules["minimum_billable_duration_seconds"]
        quality_threshold = rules["quality_score_threshold"]
        quality_penalty = rules["quality_penalty_multiplier"]

        # Build rate adjustment lookup: (carrier_a, carrier_b, call_type) -> pct
        rate_adj_map = {}
        for adj in adj_data.get("adjustments", []):
            key = (adj["carrier_a_id"], adj["carrier_b_id"], adj["call_type"])
            rate_adj_map[key] = adj["adjustment_pct"]
            # Also store reversed pair
            key2 = (adj["carrier_b_id"], adj["carrier_a_id"], adj["call_type"])
            rate_adj_map[key2] = adj["adjustment_pct"]

        # Load routing penalties
        route_surcharge_map = {}
        rp_path = os.path.join(self.workspace, "routing_penalties.csv")
        with open(rp_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                route_surcharge_map[int(row["route_id"])] = float(row["surcharge_pct"])

        # Load CDR quality data from all batch files
        quality_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("cdr_quality_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        quality_map[int(row["cdr_id"])] = int(row["quality_score"])

        # Load dispute memos
        dispute_credit_map = {}  # dispute_id -> approved_credit_amount
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("dispute_memo_batch_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                for block in content.strip().split("---"):
                    block = block.strip()
                    if not block:
                        continue
                    lines = block.split("\n")
                    d = {}
                    for line in lines:
                        if ": " in line:
                            key, val = line.split(": ", 1)
                            d[key.strip()] = val.strip()
                    if "DISPUTE_ID" in d and "APPROVED_CREDIT" in d:
                        dispute_credit_map[int(d["DISPUTE_ID"])] = float(d["APPROVED_CREDIT"])

        # Get active partners
        partners = conn.execute(
            "SELECT * FROM carriers WHERE carrier_type='partner' AND status='active'"
        ).fetchall()

        # Build switch -> carrier map
        switch_carrier = {}
        for row in conn.execute("SELECT switch_id, carrier_id FROM switches").fetchall():
            switch_carrier[row["switch_id"]] = row["carrier_id"]

        # Home carrier ID
        home_id = conn.execute(
            "SELECT carrier_id FROM carriers WHERE carrier_type='home'"
        ).fetchone()["carrier_id"]

        # Get all completed CDRs
        all_cdrs = conn.execute(
            "SELECT * FROM cdrs WHERE completion_status='completed'"
        ).fetchall()

        # Get bilateral rates: (home, partner, call_type) -> rate
        rate_map = {}
        for row in conn.execute(
            "SELECT * FROM bilateral_agreements WHERE status='active'"
        ).fetchall():
            a, b = row["carrier_a_id"], row["carrier_b_id"]
            ct = row["call_type"]
            rate_map[(a, b, ct)] = row["rate_per_minute"]
            rate_map[(b, a, ct)] = row["rate_per_minute"]

        # Get resolved disputes for billing period
        resolved_disputes = conn.execute(
            "SELECT * FROM disputes WHERE status='resolved' AND billing_period=?",
            (billing_period,),
        ).fetchall()

        # Compute per-partner settlement
        results = {}
        for partner in partners:
            pid = partner["carrier_id"]
            pname = partner["carrier_name"]

            incoming_minutes = 0
            outgoing_minutes = 0
            incoming_charges = 0.0
            outgoing_charges = 0.0

            for cdr in all_cdrs:
                orig_carrier = switch_carrier.get(cdr["originating_switch_id"])
                term_carrier = switch_carrier.get(cdr["terminating_switch_id"])

                if orig_carrier is None or term_carrier is None:
                    continue

                # Must involve home and this partner
                if not ((orig_carrier == home_id and term_carrier == pid) or
                        (orig_carrier == pid and term_carrier == home_id)):
                    continue

                dur = cdr["duration_seconds"]
                if dur < min_duration:
                    continue

                billable_min = math.ceil(dur / 60)
                ct = cdr["call_type"]

                # Base rate
                base_rate = rate_map.get((home_id, pid, ct))
                if base_rate is None:
                    continue

                # Rate adjustment
                adj_key = (home_id, pid, ct)
                adj_pct = rate_adj_map.get(adj_key, 0.0)
                adjusted_rate = base_rate * (1 + adj_pct / 100.0)

                # Routing surcharge
                rid = cdr["route_id"]
                route_pct = route_surcharge_map.get(rid, 0.0)
                adjusted_rate = adjusted_rate * (1 + route_pct / 100.0)

                # Quality penalty
                qs = quality_map.get(cdr["cdr_id"])
                if qs is not None and qs < quality_threshold:
                    adjusted_rate = adjusted_rate * quality_penalty

                charge = round(billable_min * adjusted_rate, 2)

                if orig_carrier == pid and term_carrier == home_id:
                    # Incoming: partner originated -> home terminated => partner owes home
                    incoming_minutes += billable_min
                    incoming_charges += charge
                else:
                    # Outgoing: home originated -> partner terminated => home owes partner
                    outgoing_minutes += billable_min
                    outgoing_charges += charge

            incoming_charges = round(incoming_charges, 2)
            outgoing_charges = round(outgoing_charges, 2)

            # Tier discount
            total_min = incoming_minutes + outgoing_minutes
            tier_discount_pct = 0.0
            for tier in tiers_data["tiers"]:
                low = tier["min_minutes"]
                high = tier["max_minutes"]
                if high is None:
                    if total_min >= low:
                        tier_discount_pct = tier["discount_pct"]
                else:
                    if low <= total_min < high:
                        tier_discount_pct = tier["discount_pct"]

            adj_incoming = round(incoming_charges * (1 - tier_discount_pct / 100.0), 2)
            adj_outgoing = round(outgoing_charges * (1 - tier_discount_pct / 100.0), 2)

            # Dispute credits
            dispute_credits = 0.0
            for disp in resolved_disputes:
                # Dispute involves home and this partner
                if not ((disp["filing_carrier_id"] == pid and disp["counter_carrier_id"] == home_id) or
                        (disp["filing_carrier_id"] == home_id and disp["counter_carrier_id"] == pid)):
                    continue
                did = disp["dispute_id"]
                if did in dispute_credit_map:
                    dispute_credits += dispute_credit_map[did]
            dispute_credits = round(dispute_credits, 2)

            net_settlement = round(adj_incoming - adj_outgoing - dispute_credits, 2)

            results[pid] = {
                "carrier_id": pid,
                "carrier_name": pname,
                "total_incoming_minutes": incoming_minutes,
                "total_outgoing_minutes": outgoing_minutes,
                "incoming_charges": round(adj_incoming, 2),
                "outgoing_charges": round(adj_outgoing, 2),
                "tier_discount_pct": tier_discount_pct,
                "dispute_credits": dispute_credits,
                "net_settlement": net_settlement,
            }

        conn.close()

        total_net = round(sum(r["net_settlement"] for r in results.values()), 2)
        top_carrier = max(results.values(), key=lambda x: abs(x["net_settlement"]))

        return {
            "partner_settlements": results,
            "total_net_settlement": total_net,
            "top_carrier_name": top_carrier["carrier_name"],
            "top_carrier_abs_net": abs(top_carrier["net_settlement"]),
        }

    # ================================================================
    # STEP
    # ================================================================

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
        gt_settlements = gt["partner_settlements"]
        gt_total_net = gt["total_net_settlement"]
        gt_top_name = gt["top_carrier_name"]

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: invoice_summary.csv exists with correct columns (10 pts) ---
        c1_max = 10
        c1_score = 0
        csv_path = os.path.join(self.workspace, "invoice_summary.csv")
        expected_cols = ["carrier_id", "carrier_name", "total_incoming_minutes",
                         "total_outgoing_minutes", "incoming_charges",
                         "outgoing_charges", "tier_discount_pct",
                         "dispute_credits", "net_settlement"]
        csv_data = []
        if os.path.exists(csv_path):
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                actual_cols = reader.fieldnames or []
                if set(expected_cols) <= set(actual_cols):
                    c1_score = c1_max
                    csv_data = list(reader)
                else:
                    c1_score = 3  # File exists but wrong columns
        eval_criteria["file_format"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": "" if c1_score == c1_max else "invoice_summary.csv missing or wrong columns",
        }

        # --- Criterion 2: Correct set of partner carriers (15 pts) ---
        c2_max = 15
        c2_score = 0
        expected_ids = set(gt_settlements.keys())
        actual_ids = set()
        for row in csv_data:
            try:
                actual_ids.add(int(row["carrier_id"]))
            except (KeyError, ValueError):
                pass
        if actual_ids == expected_ids:
            c2_score = c2_max
        elif len(actual_ids & expected_ids) > 0:
            overlap = len(actual_ids & expected_ids)
            c2_score = round(c2_max * overlap / max(len(expected_ids), len(actual_ids)))
        eval_criteria["carrier_set"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": "" if c2_score == c2_max else
                f"Expected {len(expected_ids)} partners, got {len(actual_ids)} "
                f"(overlap {len(actual_ids & expected_ids)})",
        }

        # --- Criterion 3: Correct incoming/outgoing minutes (15 pts) ---
        c3_max = 15
        c3_score = 0
        if csv_data and c2_score > 0:
            correct_min = 0
            total_checks = 0
            for row in csv_data:
                try:
                    cid = int(row["carrier_id"])
                except (KeyError, ValueError):
                    continue
                if cid not in gt_settlements:
                    continue
                gt_entry = gt_settlements[cid]
                total_checks += 2
                try:
                    if int(row["total_incoming_minutes"]) == gt_entry["total_incoming_minutes"]:
                        correct_min += 1
                except (KeyError, ValueError):
                    pass
                try:
                    if int(row["total_outgoing_minutes"]) == gt_entry["total_outgoing_minutes"]:
                        correct_min += 1
                except (KeyError, ValueError):
                    pass
            if total_checks > 0:
                c3_score = round(c3_max * correct_min / total_checks)
        eval_criteria["minutes_accuracy"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": "" if c3_score == c3_max else "Some minute totals are incorrect",
        }

        # --- Criterion 4: Correct charges per carrier (20 pts) ---
        c4_max = 20
        c4_score = 0
        if csv_data and c2_score > 0:
            correct_chg = 0
            total_chg_checks = 0
            for row in csv_data:
                try:
                    cid = int(row["carrier_id"])
                except (KeyError, ValueError):
                    continue
                if cid not in gt_settlements:
                    continue
                gt_entry = gt_settlements[cid]
                total_chg_checks += 2
                try:
                    if abs(float(row["incoming_charges"]) - gt_entry["incoming_charges"]) < 0.015:
                        correct_chg += 1
                except (KeyError, ValueError):
                    pass
                try:
                    if abs(float(row["outgoing_charges"]) - gt_entry["outgoing_charges"]) < 0.015:
                        correct_chg += 1
                except (KeyError, ValueError):
                    pass
            if total_chg_checks > 0:
                c4_score = round(c4_max * correct_chg / total_chg_checks)
        eval_criteria["charges_accuracy"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": "" if c4_score == c4_max else "Some charge values are incorrect",
        }

        # --- Criterion 5: Correct dispute credits (15 pts) ---
        c5_max = 15
        c5_score = 0
        if csv_data and c2_score > 0:
            correct_dc = 0
            total_dc_checks = 0
            for row in csv_data:
                try:
                    cid = int(row["carrier_id"])
                except (KeyError, ValueError):
                    continue
                if cid not in gt_settlements:
                    continue
                gt_entry = gt_settlements[cid]
                total_dc_checks += 1
                try:
                    if abs(float(row["dispute_credits"]) - gt_entry["dispute_credits"]) < 0.015:
                        correct_dc += 1
                except (KeyError, ValueError):
                    pass
            if total_dc_checks > 0:
                c5_score = round(c5_max * correct_dc / total_dc_checks)
        eval_criteria["dispute_credits_accuracy"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": "" if c5_score == c5_max else "Some dispute credits are incorrect",
        }

        # --- Criterion 6: Correct net settlement per carrier (15 pts) ---
        c6_max = 15
        c6_score = 0
        if csv_data and c2_score > 0:
            correct_ns = 0
            total_ns_checks = 0
            for row in csv_data:
                try:
                    cid = int(row["carrier_id"])
                except (KeyError, ValueError):
                    continue
                if cid not in gt_settlements:
                    continue
                gt_entry = gt_settlements[cid]
                total_ns_checks += 1
                try:
                    if abs(float(row["net_settlement"]) - gt_entry["net_settlement"]) < 0.015:
                        correct_ns += 1
                except (KeyError, ValueError):
                    pass
            if total_ns_checks > 0:
                c6_score = round(c6_max * correct_ns / total_ns_checks)
        eval_criteria["net_settlement_accuracy"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": "" if c6_score == c6_max else "Some net settlement values are incorrect",
        }

        # --- Criterion 7: Response contains total and top carrier (10 pts) ---
        c7_max = 10
        c7_score = 0
        action_lower = action.lower() if action else ""
        # Check total net settlement in response
        total_net_str = f"{gt_total_net:.2f}"
        if total_net_str in action or str(gt_total_net) in action:
            c7_score += 5
        # Check top carrier name in response
        if gt_top_name.lower() in action_lower:
            c7_score += 5
        eval_criteria["response_summary"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": "" if c7_score == c7_max else
                f"Expected total={total_net_str} and top carrier={gt_top_name} in response",
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score_total = sum(c["max_score"] for c in eval_criteria.values())

        return total_score / max_score_total, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score_total,
        }

    # ================================================================
    # VERIFY
    # ================================================================

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

        # --- Step 1: Load workspace config files ---
        with open(os.path.join(self.workspace, "settlement_rules.json")) as f:
            rules = json.load(f)
        with open(os.path.join(self.workspace, "rate_adjustments.yaml")) as f:
            adj_data = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "tier_discounts.json")) as f:
            tiers_data = json.load(f)

        billing_period = rules["billing_period"]
        min_duration = rules["minimum_billable_duration_seconds"]
        quality_threshold = rules["quality_score_threshold"]
        quality_penalty = rules["quality_penalty_multiplier"]

        # Build rate adjustment lookup
        rate_adj_map = {}
        for adj in adj_data.get("adjustments", []):
            key = (adj["carrier_a_id"], adj["carrier_b_id"], adj["call_type"])
            rate_adj_map[key] = adj["adjustment_pct"]
            key2 = (adj["carrier_b_id"], adj["carrier_a_id"], adj["call_type"])
            rate_adj_map[key2] = adj["adjustment_pct"]

        # Load routing penalties
        route_surcharge_map = {}
        rp_path = os.path.join(self.workspace, "routing_penalties.csv")
        with open(rp_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                route_surcharge_map[int(row["route_id"])] = float(row["surcharge_pct"])

        # Load CDR quality data
        quality_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("cdr_quality_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        quality_map[int(row["cdr_id"])] = int(row["quality_score"])

        # Load dispute memos
        dispute_credit_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("dispute_memo_batch_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                for block in content.strip().split("---"):
                    block = block.strip()
                    if not block:
                        continue
                    lines = block.split("\n")
                    d = {}
                    for line in lines:
                        if ": " in line:
                            key, val = line.split(": ", 1)
                            d[key.strip()] = val.strip()
                    if "DISPUTE_ID" in d and "APPROVED_CREDIT" in d:
                        dispute_credit_map[int(d["DISPUTE_ID"])] = float(d["APPROVED_CREDIT"])

        # --- Step 2: Get home carrier info ---
        res = self.tools["list_carriers"](carrier_type="home", status="active")
        tool_calls += 1
        home_id = res["carriers"][0]["carrier_id"]

        # --- Step 3: Get active partner carriers ---
        all_partners = []
        page = 1
        while True:
            res = self.tools["list_carriers"](carrier_type="partner", status="active",
                                              page=page, page_size=50)
            tool_calls += 1
            all_partners.extend(res["carriers"])
            if page >= res["total_pages"]:
                break
            page += 1

        # --- Step 4: Get home switches ---
        res = self.tools["get_switches_by_carrier"](carrier_id=home_id)
        tool_calls += 1
        home_switch_ids = set(s["switch_id"] for s in res["switches"])

        # --- Step 5: Get partner switches ---
        partner_switch_map = {}  # switch_id -> carrier_id
        for partner in all_partners:
            pid = partner["carrier_id"]
            res = self.tools["get_switches_by_carrier"](carrier_id=pid)
            tool_calls += 1
            for s in res["switches"]:
                partner_switch_map[s["switch_id"]] = pid

        # --- Step 6: Get bilateral rates for each partner ---
        rate_map = {}  # (home, partner, call_type) -> rate
        for partner in all_partners:
            pid = partner["carrier_id"]
            res = self.tools["get_bilateral_rates"](carrier_a_id=home_id,
                                                     carrier_b_id=pid,
                                                     status="active")
            tool_calls += 1
            for ag in res["agreements"]:
                rate_map[(home_id, pid, ag["call_type"])] = ag["rate_per_minute"]

        # --- Step 7: Get all completed CDRs (paginated) ---
        all_cdrs = []
        page = 1
        while True:
            res = self.tools["query_cdrs"](completion_status="completed",
                                           page=page, page_size=50)
            tool_calls += 1
            all_cdrs.extend(res["cdrs"])
            if page >= res["total_pages"]:
                break
            page += 1

        # --- Step 8: Get resolved disputes for billing period ---
        all_disputes = []
        page = 1
        while True:
            res = self.tools["query_disputes"](status="resolved",
                                               billing_period=billing_period,
                                               page=page, page_size=50)
            tool_calls += 1
            all_disputes.extend(res["disputes"])
            if page >= res["total_pages"]:
                break
            page += 1

        # --- Step 9: Compute settlement per partner ---
        partner_map = {p["carrier_id"]: p for p in all_partners}
        results = {}

        for partner in all_partners:
            pid = partner["carrier_id"]
            pname = partner["carrier_name"]

            incoming_minutes = 0
            outgoing_minutes = 0
            incoming_charges = 0.0
            outgoing_charges = 0.0

            for cdr in all_cdrs:
                orig = cdr["originating_switch_id"]
                term = cdr["terminating_switch_id"]

                orig_is_home = orig in home_switch_ids
                term_is_home = term in home_switch_ids
                orig_partner = partner_switch_map.get(orig)
                term_partner = partner_switch_map.get(term)

                # Must be between home and this partner
                if orig_is_home and term_partner == pid:
                    direction = "outgoing"
                elif orig_partner == pid and term_is_home:
                    direction = "incoming"
                else:
                    continue

                dur = cdr["duration_seconds"]
                if dur < min_duration:
                    continue

                billable_min = math.ceil(dur / 60)
                ct = cdr["call_type"]

                base_rate = rate_map.get((home_id, pid, ct))
                if base_rate is None:
                    continue

                adj_pct = rate_adj_map.get((home_id, pid, ct), 0.0)
                adjusted_rate = base_rate * (1 + adj_pct / 100.0)

                route_pct = route_surcharge_map.get(cdr["route_id"], 0.0)
                adjusted_rate = adjusted_rate * (1 + route_pct / 100.0)

                qs = quality_map.get(cdr["cdr_id"])
                if qs is not None and qs < quality_threshold:
                    adjusted_rate = adjusted_rate * quality_penalty

                charge = round(billable_min * adjusted_rate, 2)

                if direction == "incoming":
                    incoming_minutes += billable_min
                    incoming_charges += charge
                else:
                    outgoing_minutes += billable_min
                    outgoing_charges += charge

            incoming_charges = round(incoming_charges, 2)
            outgoing_charges = round(outgoing_charges, 2)

            # Tier discount
            total_min = incoming_minutes + outgoing_minutes
            tier_discount_pct = 0.0
            for tier in tiers_data["tiers"]:
                low = tier["min_minutes"]
                high = tier["max_minutes"]
                if high is None:
                    if total_min >= low:
                        tier_discount_pct = tier["discount_pct"]
                else:
                    if low <= total_min < high:
                        tier_discount_pct = tier["discount_pct"]

            adj_incoming = round(incoming_charges * (1 - tier_discount_pct / 100.0), 2)
            adj_outgoing = round(outgoing_charges * (1 - tier_discount_pct / 100.0), 2)

            # Dispute credits
            dispute_credits = 0.0
            for disp in all_disputes:
                if not ((disp["filing_carrier_id"] == pid and disp["counter_carrier_id"] == home_id) or
                        (disp["filing_carrier_id"] == home_id and disp["counter_carrier_id"] == pid)):
                    continue
                did = disp["dispute_id"]
                if did in dispute_credit_map:
                    dispute_credits += dispute_credit_map[did]
            dispute_credits = round(dispute_credits, 2)

            net_settlement = round(adj_incoming - adj_outgoing - dispute_credits, 2)

            results[pid] = {
                "carrier_id": pid,
                "carrier_name": pname,
                "total_incoming_minutes": incoming_minutes,
                "total_outgoing_minutes": outgoing_minutes,
                "incoming_charges": round(adj_incoming, 2),
                "outgoing_charges": round(adj_outgoing, 2),
                "tier_discount_pct": tier_discount_pct,
                "dispute_credits": dispute_credits,
                "net_settlement": net_settlement,
            }

        # --- Step 10: Write invoice_summary.csv ---
        csv_path = os.path.join(self.workspace, "invoice_summary.csv")
        fieldnames = ["carrier_id", "carrier_name", "total_incoming_minutes",
                      "total_outgoing_minutes", "incoming_charges",
                      "outgoing_charges", "tier_discount_pct",
                      "dispute_credits", "net_settlement"]
        sorted_results = sorted(results.values(), key=lambda x: x["carrier_id"])
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in sorted_results:
                writer.writerow({
                    "carrier_id": r["carrier_id"],
                    "carrier_name": r["carrier_name"],
                    "total_incoming_minutes": r["total_incoming_minutes"],
                    "total_outgoing_minutes": r["total_outgoing_minutes"],
                    "incoming_charges": f"{r['incoming_charges']:.2f}",
                    "outgoing_charges": f"{r['outgoing_charges']:.2f}",
                    "tier_discount_pct": f"{r['tier_discount_pct']:.1f}",
                    "dispute_credits": f"{r['dispute_credits']:.2f}",
                    "net_settlement": f"{r['net_settlement']:.2f}",
                })

        # --- Step 11: Build response ---
        total_net = round(sum(r["net_settlement"] for r in results.values()), 2)
        top_carrier = max(results.values(), key=lambda x: abs(x["net_settlement"]))

        action = (
            f"Monthly interconnect settlement for billing period {billing_period} "
            f"has been computed for {len(results)} partner carriers.\n\n"
            f"Total net settlement: {total_net:.2f} USD\n"
            f"Carrier with highest absolute net settlement: "
            f"{top_carrier['carrier_name']} "
            f"(net: {top_carrier['net_settlement']:.2f} USD)\n\n"
            f"The reconciled invoice summary has been saved to invoice_summary.csv "
            f"with columns: carrier_id, carrier_name, total_incoming_minutes, "
            f"total_outgoing_minutes, incoming_charges, outgoing_charges, "
            f"tier_discount_pct, dispute_credits, net_settlement.\n\n"
            f"Total tool calls made: {tool_calls}"
        )

        return self.step(action)
