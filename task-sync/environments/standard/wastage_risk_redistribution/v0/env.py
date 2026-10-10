#!/usr/bin/env python3
"""Environment for blood-bank wastage-risk redistribution task."""

import csv
import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


# --- Decorator (keep unchanged) -----------------------------------------------
def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


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

    # ── Tool methods ──────────────────────────────────────────────────────────

    @tool(
        description="List all blood bank IDs and names.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_banks(self) -> List[Dict[str, str]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT bank_id, bank_name, city, region FROM blood_banks ORDER BY bank_id")
        rows = cur.fetchall()
        conn.close()
        return _envelope([{"bank_id": r[0], "bank_name": r[1], "city": r[2], "region": r[3]} for r in rows])

    @tool(
        description="Get available inventory counts for a specific bank, grouped by blood_type and component_type. Only counts units with status 'available' or 'reserved'.",
        parameters={
            "type": "object",
            "properties": {
                "bank_id": {"type": "string", "description": "Blood bank ID, e.g. BB-0001"},
            },
            "required": ["bank_id"],
        },
    )
    def get_inventory_summary(self, bank_id: str) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT blood_type, component_type, status, COUNT(*) as cnt
            FROM blood_units
            WHERE bank_id = ? AND status IN ('available', 'reserved')
            GROUP BY blood_type, component_type, status
            ORDER BY blood_type, component_type, status
        """, (bank_id,))
        rows = cur.fetchall()
        conn.close()
        return json.dumps([{"blood_type": r[0], "component_type": r[1], "status": r[2], "count": r[3]} for r in rows], ensure_ascii=False, default=str)

    @tool(
        description="Get units expiring within a given number of days for a specific bank. Returns unit details. Maximum 50 results per call; use offset for pagination.",
        parameters={
            "type": "object",
            "properties": {
                "bank_id": {"type": "string", "description": "Blood bank ID"},
                "days": {"type": "integer", "description": "Number of days from today (2026-04-22) to look ahead"},
                "offset": {"type": "integer", "description": "Pagination offset (default 0)"},
            },
            "required": ["bank_id", "days"],
        },
    )
    def get_expiring_units(self, bank_id: str, days: int, offset: int = 0) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        deadline = f"2026-04-{22 + days:02d}" if days <= 8 else "2026-05-01"
        # Compute proper deadline
        from datetime import datetime, timedelta
        today = datetime(2026, 4, 22)
        deadline = (today + timedelta(days=days)).strftime("%Y-%m-%d")
        cur.execute("""
            SELECT unit_id, blood_type, component_type, expiration_date, volume_ml, status
            FROM blood_units
            WHERE bank_id = ? AND expiration_date <= ? AND status != 'quarantine'
            ORDER BY expiration_date ASC, unit_id ASC
            LIMIT 50 OFFSET ?
        """, (bank_id, deadline, offset))
        rows = cur.fetchall()
        cur.execute("""
            SELECT COUNT(*)
            FROM blood_units
            WHERE bank_id = ? AND expiration_date <= ? AND status != 'quarantine'
        """, (bank_id, deadline))
        total = cur.fetchone()[0]
        conn.close()
        units = [{"unit_id": r[0], "blood_type": r[1], "component_type": r[2],
                  "expiration_date": r[3], "volume_ml": r[4], "status": r[5]}
                 for r in rows]
        return _envelope({"units": units, "total": total, "offset": offset, "limit": 50})

    @tool(
        description="Get hospital contracts for a specific bank. Returns contract details.",
        parameters={
            "type": "object",
            "properties": {
                "bank_id": {"type": "string", "description": "Blood bank ID"},
            },
            "required": ["bank_id"],
        },
    )
    def get_contracts_for_bank(self, bank_id: str) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        today = "2026-04-22"
        cur.execute("""
            SELECT contract_id, hospital_name, blood_type, component_type,
                   weekly_demand, priority_tier
            FROM hospital_contracts
            WHERE bank_id = ? AND contract_start <= ? AND contract_end >= ?
            ORDER BY priority_tier ASC, weekly_demand DESC
        """, (bank_id, today, today))
        rows = cur.fetchall()
        conn.close()
        return _envelope([{"contract_id": r[0], "hospital_name": r[1], "blood_type": r[2],
                 "component_type": r[3], "weekly_demand": r[4], "priority_tier": r[5]}
                for r in rows])

    @tool(
        description="Get outbound transfer requests from a specific bank, optionally filtered by status.",
        parameters={
            "type": "object",
            "properties": {
                "bank_id": {"type": "string", "description": "Source bank ID"},
                "status_filter": {"type": "string", "description": "Filter by status (pending, approved, in_transit, completed, rejected). Omit for all."},
            },
            "required": ["bank_id"],
        },
    )
    def get_outbound_transfers(self, bank_id: str, status_filter: str = None) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if status_filter:
            cur.execute("""
                SELECT request_id, dest_bank_id, blood_type, component_type,
                       units_requested, urgency, status, request_date
                FROM transfer_requests
                WHERE source_bank_id = ? AND status = ?
                ORDER BY request_date DESC
            """, (bank_id, status_filter))
        else:
            cur.execute("""
                SELECT request_id, dest_bank_id, blood_type, component_type,
                       units_requested, urgency, status, request_date
                FROM transfer_requests
                WHERE source_bank_id = ?
                ORDER BY request_date DESC
            """, (bank_id,))
        rows = cur.fetchall()
        conn.close()
        return _envelope([{"request_id": r[0], "dest_bank_id": r[1], "blood_type": r[2],
                 "component_type": r[3], "units_requested": r[4], "urgency": r[5],
                 "status": r[6], "request_date": r[7]} for r in rows])

    @tool(
        description="Get details of a specific blood unit by its unit ID.",
        parameters={
            "type": "object",
            "properties": {
                "unit_id": {"type": "string", "description": "Unit ID, e.g. U-000001"},
            },
            "required": ["unit_id"],
        },
    )
    def get_unit_details(self, unit_id: str) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT unit_id, bank_id, blood_type, component_type,
                   collection_date, expiration_date, volume_ml, status, donor_id
            FROM blood_units WHERE unit_id = ?
        """, (unit_id,))
        r = cur.fetchone()
        conn.close()
        if not r:
            return json.dumps({"error": f"Unit {unit_id} not found"}, ensure_ascii=False, default=str)
        return json.dumps({"unit_id": r[0], "bank_id": r[1], "blood_type": r[2],
                "component_type": r[3], "collection_date": r[4],
                "expiration_date": r[5], "volume_ml": r[6], "status": r[7],
                "donor_id": r[8]}, ensure_ascii=False, default=str)

    @tool(
        description="Get the total weekly demand for a given blood_type and component_type across all banks from active contracts.",
        parameters={
            "type": "object",
            "properties": {
                "blood_type": {"type": "string", "description": "Blood type, e.g. O+"},
                "component_type": {"type": "string", "description": "Component type, e.g. Platelets"},
            },
            "required": ["blood_type", "component_type"],
        },
    )
    def get_demand_by_type(self, blood_type: str, component_type: str) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        today = "2026-04-22"
        cur.execute("""
            SELECT bank_id, SUM(weekly_demand) as total_demand
            FROM hospital_contracts
            WHERE blood_type = ? AND component_type = ?
              AND contract_start <= ? AND contract_end >= ?
            GROUP BY bank_id
            ORDER BY total_demand DESC
        """, (blood_type, component_type, today, today))
        rows = cur.fetchall()
        conn.close()
        return json.dumps({"blood_type": blood_type, "component_type": component_type,
                "demand_by_bank": [{"bank_id": r[0], "weekly_demand": r[1]} for r in rows]}, ensure_ascii=False, default=str)

    @tool(
        description="Get available (non-quarantine) unit count for a specific bank, blood_type, and component_type.",
        parameters={
            "type": "object",
            "properties": {
                "bank_id": {"type": "string", "description": "Blood bank ID"},
                "blood_type": {"type": "string", "description": "Blood type"},
                "component_type": {"type": "string", "description": "Component type"},
            },
            "required": ["bank_id", "blood_type", "component_type"],
        },
    )
    def get_available_count(self, bank_id: str, blood_type: str, component_type: str) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*)
            FROM blood_units
            WHERE bank_id = ? AND blood_type = ? AND component_type = ?
              AND status IN ('available', 'reserved')
        """, (bank_id, blood_type, component_type))
        count = cur.fetchone()[0]
        conn.close()
        return json.dumps({"bank_id": bank_id, "blood_type": blood_type,
                "component_type": component_type, "available_count": count}, ensure_ascii=False, default=str)

    # ── step: evaluation ──────────────────────────────────────────────────────

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        from datetime import datetime, timedelta
        today = datetime(2026, 4, 22)

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Ground-truth computation ──────────────────────────────────────
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # Load wastage policy
        policy_path = os.path.join(self.workspace, "wastage_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)["wastage_risk_policy"]

        horizon = policy["risk_horizon_days"]
        min_score_thresh = policy["minimum_risk_score_for_redistribution"]
        weights = policy["risk_scoring"]
        dte_brackets = policy["days_to_expiry_brackets"]
        surplus_brackets = policy["surplus_ratio_thresholds"]["brackets"]
        transfer_active = policy["transfer_activity_scoring"]["active_statuses"]

        # Load eligibility config
        elig_path = os.path.join(self.workspace, "bank_transfer_eligibility.json")
        with open(elig_path) as f:
            eligibility = json.load(f)

        # Get all non-quarantine units expiring within horizon
        deadline = (today + timedelta(days=horizon)).strftime("%Y-%m-%d")
        cur.execute("""
            SELECT unit_id, bank_id, blood_type, component_type,
                   expiration_date, volume_ml, status
            FROM blood_units
            WHERE expiration_date <= ? AND status != 'quarantine'
            ORDER BY unit_id
        """, (deadline,))
        expiring_units = cur.fetchall()

        # Compute weekly demand per (bank, blood_type, component_type)
        cur.execute("""
            SELECT bank_id, blood_type, component_type, SUM(weekly_demand)
            FROM hospital_contracts
            WHERE contract_start <= '2026-04-22' AND contract_end >= '2026-04-22'
            GROUP BY bank_id, blood_type, component_type
        """)
        demand_map = {}
        for r in cur.fetchall():
            demand_map[(r[0], r[1], r[2])] = r[3]

        # Compute available counts per (bank, blood_type, component_type)
        cur.execute("""
            SELECT bank_id, blood_type, component_type, COUNT(*)
            FROM blood_units
            WHERE status IN ('available', 'reserved')
            GROUP BY bank_id, blood_type, component_type
        """)
        avail_map = {}
        for r in cur.fetchall():
            avail_map[(r[0], r[1], r[2])] = r[3]

        # Compute active outbound transfer counts per (bank, blood_type, component_type)
        placeholders = ",".join(f"'{s}'" for s in transfer_active)
        cur.execute(f"""
            SELECT source_bank_id, blood_type, component_type, COUNT(*)
            FROM transfer_requests
            WHERE status IN ({placeholders})
            GROUP BY source_bank_id, blood_type, component_type
        """)
        transfer_count_map = {}
        for r in cur.fetchall():
            transfer_count_map[(r[0], r[1], r[2])] = r[3]

        conn.close()

        # Score each unit
        gt_rows = []
        for u in expiring_units:
            uid, bid, bt, ct, exp_str, vol, status = u
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
            dte = (exp_date - today).days

            # days_to_expiry score
            dte_score = 0
            for bracket in dte_brackets:
                if dte <= bracket["max_days"]:
                    dte_score = bracket["score"]
                    break

            # surplus ratio score
            avail = avail_map.get((bid, bt, ct), 0)
            demand = demand_map.get((bid, bt, ct), 0)
            ratio = avail / demand if demand > 0 else 999
            surplus_score = 0
            for bracket in surplus_brackets:
                if ratio >= bracket["min_ratio"]:
                    surplus_score = bracket["score"]
                    break

            # transfer activity score
            tc = transfer_count_map.get((bid, bt, ct), 0)
            transfer_reduction = 0
            if tc >= 2:
                transfer_reduction = 3
            elif tc == 1:
                transfer_reduction = 1

            raw = (dte_score * weights["days_to_expiry_weight"] +
                   surplus_score * weights["surplus_ratio_weight"] +
                   (10 - transfer_reduction) * weights["transfer_activity_weight"])

            # Platelet bonus
            if ct == "Platelets" and dte <= 2:
                raw += 3

            # Reserved reduction
            if status == "reserved":
                raw = max(0, raw - 2)

            risk_score = int(round(raw))

            if risk_score < min_score_thresh:
                continue

            # Suggested recipient: bank with highest unmet demand for bt+ct
            # among eligible recipients
            eligible_banks = eligibility.get(bid, {}).get("eligible_recipients", [])
            best_bank = "DISCARD"
            best_unmet = 0
            for eb in eligible_banks:
                eb_demand = demand_map.get((eb, bt, ct), 0)
                eb_avail = avail_map.get((eb, bt, ct), 0)
                unmet = eb_demand - eb_avail
                if unmet > best_unmet:
                    best_unmet = unmet
                    best_bank = eb

            gt_rows.append({
                "unit_id": uid,
                "bank_id": bid,
                "blood_type": bt,
                "component_type": ct,
                "expiration_date": exp_str,
                "days_to_expiry": dte,
                "risk_score": risk_score,
                "suggested_recipient_bank": best_bank,
            })

        # Sort ground truth: descending risk_score, ascending unit_id for ties
        gt_rows.sort(key=lambda x: (-x["risk_score"], x["unit_id"]))

        # ── Criterion 1: redistribution_list.csv exists ───────────────────
        csv_path = os.path.join(self.workspace, "redistribution_list.csv")
        csv_exists = os.path.isfile(csv_path)
        c1_score = 10 if csv_exists else 0
        eval_criteria["file_exists"] = {
            "passed": csv_exists, "score": c1_score, "max_score": 10,
            "reason": "" if csv_exists else "redistribution_list.csv not found"
        }
        total_score += c1_score
        max_score += 10

        if csv_exists:
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                submitted_rows = list(reader)

            # ── Criterion 2: correct columns ──────────────────────────────
            expected_cols = ["unit_id", "bank_id", "blood_type", "component_type",
                             "expiration_date", "days_to_expiry", "risk_score",
                             "suggested_recipient_bank"]
            if submitted_rows:
                actual_cols = list(submitted_rows[0].keys())
            else:
                actual_cols = list(reader.fieldnames) if reader.fieldnames else []
            cols_match = actual_cols == expected_cols
            c2_score = 10 if cols_match else 0
            eval_criteria["correct_columns"] = {
                "passed": cols_match, "score": c2_score, "max_score": 10,
                "reason": "" if cols_match else f"Expected columns {expected_cols}, got {actual_cols}"
            }
            total_score += c2_score
            max_score += 10

            # ── Criterion 3: correct unit set (unit IDs) ─────────────────
            gt_ids = [r["unit_id"] for r in gt_rows]
            sub_ids = [r.get("unit_id", "") for r in submitted_rows]
            ids_match = set(gt_ids) == set(sub_ids)
            # Partial: fraction of correct IDs
            if gt_ids:
                correct_ids = set(gt_ids) & set(sub_ids)
                extra_ids = set(sub_ids) - set(gt_ids)
                frac = max(0, len(correct_ids) - len(extra_ids)) / len(gt_ids)
            else:
                frac = 1.0 if not sub_ids else 0.0
            c3_max = 25
            c3_score = int(round(frac * c3_max))
            eval_criteria["correct_unit_set"] = {
                "passed": ids_match, "score": c3_score, "max_score": c3_max,
                "reason": "" if ids_match else f"Expected {len(gt_ids)} units, got {len(sub_ids)} ({len(set(gt_ids)&set(sub_ids))} overlap)"
            }
            total_score += c3_score
            max_score += c3_max

            # ── Criterion 4: correct risk scores ─────────────────────────
            gt_score_map = {r["unit_id"]: r["risk_score"] for r in gt_rows}
            score_matches = 0
            score_total = len(gt_rows)
            for sr in submitted_rows:
                uid = sr.get("unit_id", "")
                try:
                    sub_rs = int(sr.get("risk_score", -1))
                except (ValueError, TypeError):
                    sub_rs = -1
                if uid in gt_score_map and gt_score_map[uid] == sub_rs:
                    score_matches += 1
            c4_max = 20
            c4_frac = score_matches / score_total if score_total else 1.0
            c4_score = int(round(c4_frac * c4_max))
            eval_criteria["correct_risk_scores"] = {
                "passed": c4_frac == 1.0, "score": c4_score, "max_score": c4_max,
                "reason": "" if c4_frac == 1.0 else f"{score_matches}/{score_total} risk scores correct"
            }
            total_score += c4_score
            max_score += c4_max

            # ── Criterion 5: correct sort order ──────────────────────────
            c5_max = 15
            if sub_ids == gt_ids:
                c5_score = c5_max
                c5_passed = True
            else:
                c5_score = 0
                c5_passed = False
            eval_criteria["correct_sort_order"] = {
                "passed": c5_passed, "score": c5_score, "max_score": c5_max,
                "reason": "" if c5_passed else "Sort order does not match expected"
            }
            total_score += c5_score
            max_score += c5_max

            # ── Criterion 6: correct suggested recipients ────────────────
            gt_recip_map = {r["unit_id"]: r["suggested_recipient_bank"] for r in gt_rows}
            recip_matches = 0
            recip_total = len(gt_rows)
            for sr in submitted_rows:
                uid = sr.get("unit_id", "")
                sub_recip = sr.get("suggested_recipient_bank", "")
                if uid in gt_recip_map and gt_recip_map[uid] == sub_recip:
                    recip_matches += 1
            c6_max = 20
            c6_frac = recip_matches / recip_total if recip_total else 1.0
            c6_score = int(round(c6_frac * c6_max))
            eval_criteria["correct_recipients"] = {
                "passed": c6_frac == 1.0, "score": c6_score, "max_score": c6_max,
                "reason": "" if c6_frac == 1.0 else f"{recip_matches}/{recip_total} recipients correct"
            }
            total_score += c6_score
            max_score += c6_max
        else:
            # File doesn't exist — all downstream criteria score 0
            for name, mx in [("correct_columns", 10), ("correct_unit_set", 25),
                              ("correct_risk_scores", 20), ("correct_sort_order", 15),
                              ("correct_recipients", 20)]:
                eval_criteria[name] = {"passed": False, "score": 0, "max_score": mx,
                                       "reason": "redistribution_list.csv missing"}
                max_score += mx

        # ── Criterion 7: response contains summary count ─────────────────
        c7_max = 10
        expected_count_str = str(len(gt_rows))
        c7_passed = expected_count_str in action
        c7_score = c7_max if c7_passed else 0
        eval_criteria["response_unit_count"] = {
            "passed": c7_passed, "score": c7_score, "max_score": c7_max,
            "reason": "" if c7_passed else f"Response should mention {expected_count_str} units at risk"
        }
        total_score += c7_score
        max_score += c7_max

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ── verify: self-test ─────────────────────────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        from datetime import datetime, timedelta
        import csv as _csv

        today = datetime(2026, 4, 22)

        # 1. Read policy files from workspace
        with open(os.path.join(self.workspace, "wastage_policy.yaml")) as f:
            policy = yaml.safe_load(f)["wastage_risk_policy"]

        horizon = policy["risk_horizon_days"]
        min_risk = policy["minimum_risk_score_for_redistribution"]
        weights = policy["risk_scoring"]
        dte_brackets = policy["days_to_expiry_brackets"]
        surplus_brackets = policy["surplus_ratio_thresholds"]["brackets"]
        transfer_cfg = policy["transfer_activity_scoring"]

        with open(os.path.join(self.workspace, "component_handling_rules.md")) as f:
            rules_text = f.read()

        with open(os.path.join(self.workspace, "bank_transfer_eligibility.json")) as f:
            eligibility = json.load(f)

        # 2. List banks via tool
        banks = json.loads(self.tools["list_banks"]()["content"][0]["text"])

        # 3. For each bank, gather expiring units and contracts
        all_expiring = []
        bank_contracts = {}
        bank_outbound = {}

        for bank in banks:
            bid = bank["bank_id"]

            # Get expiring units (paginate)
            offset = 0
            while True:
                result = json.loads(self.tools["get_expiring_units"](bank_id=bid, days=horizon, offset=offset)["content"][0]["text"])
                all_expiring.extend([(u, bid) for u in result["units"]])
                if offset + len(result["units"]) >= result["total"]:
                    break
                offset += result["limit"]

            # Get contracts
            bank_contracts[bid] = json.loads(self.tools["get_contracts_for_bank"](bank_id=bid)["content"][0]["text"])

            # Get active outbound transfers
            outbound_pending = json.loads(self.tools["get_outbound_transfers"](bank_id=bid, status_filter="pending")["content"][0]["text"])
            outbound_transit = json.loads(self.tools["get_outbound_transfers"](bank_id=bid, status_filter="in_transit")["content"][0]["text"])
            bank_outbound[bid] = outbound_pending + outbound_transit

        # 4. Compute demand map per (bank, bt, ct) from contracts
        demand_map = {}
        for bid, contracts in bank_contracts.items():
            for c in contracts:
                key = (bid, c["blood_type"], c["component_type"])
                demand_map[key] = demand_map.get(key, 0) + c["weekly_demand"]

        # 5. Compute transfer count map from outbound
        transfer_count_map = {}
        for bid, transfers in bank_outbound.items():
            for t in transfers:
                key = (bid, t["blood_type"], t["component_type"])
                transfer_count_map[key] = transfer_count_map.get(key, 0) + 1

        # 6. Get available counts for all (bank, bt, ct) combos we need
        blood_types = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
        component_types = ["Red Blood Cells", "Platelets", "Plasma", "Cryoprecipitate"]

        # Collect unique (bt, ct) combos from expiring units
        needed_combos = set()
        for u, bid in all_expiring:
            needed_combos.add((u["blood_type"], u["component_type"]))

        # Get available counts per bank for needed combos
        avail_map = {}
        for bank in banks:
            bid = bank["bank_id"]
            inv = json.loads(self.tools["get_inventory_summary"](bank_id=bid))
            for item in inv:
                key = (bid, item["blood_type"], item["component_type"])
                avail_map[key] = avail_map.get(key, 0) + item["count"]

        # 7. Score each expiring unit
        redistribution = []
        for u, source_bid in all_expiring:
            uid = u["unit_id"]
            bt = u["blood_type"]
            ct = u["component_type"]
            exp_str = u["expiration_date"]
            status = u["status"]

            exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
            dte = (exp_date - today).days

            # DTE score
            dte_score = 0
            for bracket in dte_brackets:
                if dte <= bracket["max_days"]:
                    dte_score = bracket["score"]
                    break

            # Surplus ratio score
            avail = avail_map.get((source_bid, bt, ct), 0)
            demand = demand_map.get((source_bid, bt, ct), 0)
            ratio = avail / demand if demand > 0 else 999
            surplus_score = 0
            for bracket in surplus_brackets:
                if ratio >= bracket["min_ratio"]:
                    surplus_score = bracket["score"]
                    break

            # Transfer activity
            tc = transfer_count_map.get((source_bid, bt, ct), 0)
            transfer_reduction = 0
            if tc >= 2:
                transfer_reduction = 3
            elif tc == 1:
                transfer_reduction = 1

            raw = (dte_score * weights["days_to_expiry_weight"] +
                   surplus_score * weights["surplus_ratio_weight"] +
                   (10 - transfer_reduction) * weights["transfer_activity_weight"])

            # Platelet bonus
            if ct == "Platelets" and dte <= 2:
                raw += 3

            # Reserved reduction
            if status == "reserved":
                raw = max(0, raw - 2)

            risk_score = int(round(raw))

            if risk_score < min_risk:
                continue

            # Find best recipient among eligible banks
            eligible_banks = eligibility.get(source_bid, {}).get("eligible_recipients", [])
            best_bank = "DISCARD"
            best_unmet = 0
            for eb in eligible_banks:
                eb_demand = demand_map.get((eb, bt, ct), 0)
                eb_avail = avail_map.get((eb, bt, ct), 0)
                unmet = eb_demand - eb_avail
                if unmet > best_unmet:
                    best_unmet = unmet
                    best_bank = eb

            redistribution.append({
                "unit_id": uid,
                "bank_id": source_bid,
                "blood_type": bt,
                "component_type": ct,
                "expiration_date": exp_str,
                "days_to_expiry": dte,
                "risk_score": risk_score,
                "suggested_recipient_bank": best_bank,
            })

        # 8. Sort: descending risk_score, ascending unit_id
        redistribution.sort(key=lambda x: (-x["risk_score"], x["unit_id"]))

        # 9. Write CSV
        csv_path = os.path.join(self.workspace, "redistribution_list.csv")
        fieldnames = ["unit_id", "bank_id", "blood_type", "component_type",
                      "expiration_date", "days_to_expiry", "risk_score",
                      "suggested_recipient_bank"]
        with open(csv_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(redistribution)

        # 10. Build action string
        action = (
            f"I have completed the wastage risk analysis. "
            f"A total of {len(redistribution)} blood units were identified as at risk of wastage "
            f"(risk score >= {min_risk}) within the {horizon}-day horizon. "
            f"The prioritized redistribution list has been saved to redistribution_list.csv, "
            f"sorted by descending risk score with unit ID as tie-breaker."
        )

        return self.step(action)
