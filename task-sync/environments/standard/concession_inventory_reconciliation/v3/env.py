#!/usr/bin/env python3
"""
Environment for Concession Stand Inventory Shrinkage Detection.
Defines tools for querying POS, returns, transfers, and staff data,
plus step/verify for evaluation.
"""

import csv
import json
import os
import re
import sqlite3
from typing import Any, Dict, List, Tuple

import pandas as pd
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

    # ══════════════════════════════════════════════════════════════
    # Tool methods
    # ══════════════════════════════════════════════════════════════

    @tool(
        description=(
            "Retrieve point-of-sale transaction records for a specific concession stand. "
            "Results are paginated with 50 records per page. Returns transactions with "
            "fields: transaction_id, stand_id, product_id, quantity_sold, unit_price, "
            "transaction_time, shift_type, payment_method."
        ),
        parameters={
            "type": "object",
            "properties": {
                "stand_id": {
                    "type": "string",
                    "description": "The stand identifier, e.g. 'STD-001'.",
                },
                "product_id": {
                    "type": "string",
                    "description": "Optional product filter, e.g. 'PRD-005'. If omitted, returns all products.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Defaults to 1.",
                },
            },
            "required": ["stand_id"],
        },
    )
    def query_transactions(self, stand_id: str, product_id: str = None, page: int = 1) -> str:
        page_size = 50
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        where = "WHERE stand_id = ?"
        params: list = [stand_id]
        if product_id:
            where += " AND product_id = ?"
            params.append(product_id)

        cur.execute(f"SELECT COUNT(*) as cnt FROM pos_transactions {where}", params)
        total = cur.fetchone()["cnt"]

        offset = (max(1, int(page)) - 1) * page_size
        cur.execute(
            f"SELECT * FROM pos_transactions {where} ORDER BY transaction_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        return json.dumps({
            "transactions": rows,
            "page": int(page) if page else 1,
            "page_size": page_size,
            "total_count": total,
            "has_more": offset + page_size < total,
        })

    @tool(
        description=(
            "Retrieve customer return records for a specific concession stand. "
            "Returns all return records with fields: return_id, stand_id, product_id, "
            "quantity_returned, return_date, reason, refund_amount."
        ),
        parameters={
            "type": "object",
            "properties": {
                "stand_id": {
                    "type": "string",
                    "description": "The stand identifier, e.g. 'STD-001'.",
                },
                "product_id": {
                    "type": "string",
                    "description": "Optional product filter. If omitted, returns all products.",
                },
            },
            "required": ["stand_id"],
        },
    )
    def query_returns(self, stand_id: str, product_id: str = None) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        where = "WHERE stand_id = ?"
        params: list = [stand_id]
        if product_id:
            where += " AND product_id = ?"
            params.append(product_id)

        cur.execute(
            f"SELECT * FROM customer_returns {where} ORDER BY return_id", params
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return json.dumps({"returns": rows, "count": len(rows)})

    @tool(
        description=(
            "Retrieve inter-stand product transfer records involving a specific stand. "
            "Specify direction as 'inbound' (transfers TO this stand) or 'outbound' "
            "(transfers FROM this stand). Returns fields: transfer_id, from_stand_id, "
            "to_stand_id, product_id, quantity, transfer_date, approved_by."
        ),
        parameters={
            "type": "object",
            "properties": {
                "stand_id": {
                    "type": "string",
                    "description": "The stand identifier, e.g. 'STD-001'.",
                },
                "direction": {
                    "type": "string",
                    "enum": ["inbound", "outbound"],
                    "description": "Transfer direction relative to the stand.",
                },
                "product_id": {
                    "type": "string",
                    "description": "Optional product filter.",
                },
            },
            "required": ["stand_id", "direction"],
        },
    )
    def query_transfers(self, stand_id: str, direction: str, product_id: str = None) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        if direction == "inbound":
            where = "WHERE to_stand_id = ?"
        else:
            where = "WHERE from_stand_id = ?"
        params: list = [stand_id]
        if product_id:
            where += " AND product_id = ?"
            params.append(product_id)

        cur.execute(
            f"SELECT * FROM inter_stand_transfers {where} ORDER BY transfer_id", params
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return json.dumps({"transfers": rows, "count": len(rows)})

    @tool(
        description=(
            "Retrieve staff schedule records for a specific concession stand. "
            "Returns employee assignments with fields: schedule_id, employee_id, "
            "employee_name, stand_id, shift_date, shift_type, clock_in, clock_out."
        ),
        parameters={
            "type": "object",
            "properties": {
                "stand_id": {
                    "type": "string",
                    "description": "The stand identifier, e.g. 'STD-001'.",
                },
                "shift_date": {
                    "type": "string",
                    "description": "Optional date filter in YYYY-MM-DD format.",
                },
                "shift_type": {
                    "type": "string",
                    "enum": ["morning", "evening"],
                    "description": "Optional shift type filter.",
                },
            },
            "required": ["stand_id"],
        },
    )
    def query_staff_schedule(self, stand_id: str, shift_date: str = None, shift_type: str = None) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        where = "WHERE stand_id = ?"
        params: list = [stand_id]
        if shift_date:
            where += " AND shift_date = ?"
            params.append(shift_date)
        if shift_type:
            where += " AND shift_type = ?"
            params.append(shift_type)

        cur.execute(
            f"SELECT * FROM staff_schedules {where} ORDER BY shift_date, shift_type, employee_name",
            params,
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return json.dumps({"schedules": rows, "count": len(rows)})

    # ══════════════════════════════════════════════════════════════
    # Ground truth computation (used by both step and verify-check)
    # ══════════════════════════════════════════════════════════════

    def _compute_ground_truth(self):
        """Compute the full ground-truth reconciliation from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # --- Load reference files ---
        with open(os.path.join(self.workspace, "product_catalog.json")) as f:
            catalog = json.load(f)
        with open(os.path.join(self.workspace, "stand_directory.yaml")) as f:
            stand_dir = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "shrinkage_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        stand_ids = sorted(stand_dir.keys())
        product_ids = sorted(catalog.keys())

        # Beginning inventory
        begin_df = pd.read_csv(os.path.join(self.workspace, "beginning_inventory.csv"))
        begin_map = {}
        for _, row in begin_df.iterrows():
            begin_map[(row["stand_id"], row["product_id"])] = int(row["quantity"])

        # Ending inventory
        end_df = pd.read_csv(os.path.join(self.workspace, "ending_inventory.csv"))
        end_map = {}
        for _, row in end_df.iterrows():
            end_map[(row["stand_id"], row["product_id"])] = int(row["quantity"])

        # Deliveries from workspace files
        delivery_agg = {}
        inv_dir = os.path.join(self.workspace, "delivery_invoices")
        if os.path.isdir(inv_dir):
            for fname in sorted(os.listdir(inv_dir)):
                fpath = os.path.join(inv_dir, fname)
                if fname.endswith(".csv"):
                    df = pd.read_csv(fpath)
                    for _, row in df.iterrows():
                        key = (row["stand_id"], row["product_id"])
                        delivery_agg[key] = delivery_agg.get(key, 0) + int(row["quantity_delivered"])

        # Waste from workspace files
        waste_agg = {}
        waste_dir = os.path.join(self.workspace, "waste_logs")
        if os.path.isdir(waste_dir):
            for fname in sorted(os.listdir(waste_dir)):
                fpath = os.path.join(waste_dir, fname)
                if fname.endswith(".csv"):
                    df = pd.read_csv(fpath)
                    for _, row in df.iterrows():
                        key = (row["stand_id"], row["product_id"])
                        waste_agg[key] = waste_agg.get(key, 0) + int(row["quantity_wasted"])
                elif fname.endswith(".txt"):
                    with open(fpath) as f:
                        lines = f.read().strip().split("\n")
                    for line in lines[1:]:  # skip header
                        parts = line.split("|")
                        if len(parts) >= 4:
                            key = (parts[0].strip(), parts[1].strip())
                            waste_agg[key] = waste_agg.get(key, 0) + int(parts[3].strip())
                elif fname.endswith(".md"):
                    with open(fpath) as f:
                        lines = f.read().strip().split("\n")
                    for line in lines[2:]:  # skip header and separator
                        parts = [p.strip() for p in line.split("|")]
                        parts = [p for p in parts if p]
                        if len(parts) >= 4:
                            key = (parts[0], parts[1])
                            waste_agg[key] = waste_agg.get(key, 0) + int(parts[3])

        # Sales from DB
        sales_agg = {}
        cur = conn.cursor()
        cur.execute(
            "SELECT stand_id, product_id, SUM(quantity_sold) as total "
            "FROM pos_transactions GROUP BY stand_id, product_id"
        )
        for row in cur.fetchall():
            sales_agg[(row[0], row[1])] = row[2]

        # Returns from DB
        returns_agg = {}
        cur.execute(
            "SELECT stand_id, product_id, SUM(quantity_returned) as total "
            "FROM customer_returns GROUP BY stand_id, product_id"
        )
        for row in cur.fetchall():
            returns_agg[(row[0], row[1])] = row[2]

        # Transfers from DB
        transfers_in_agg = {}
        transfers_out_agg = {}
        cur.execute(
            "SELECT to_stand_id, product_id, SUM(quantity) as total "
            "FROM inter_stand_transfers GROUP BY to_stand_id, product_id"
        )
        for row in cur.fetchall():
            transfers_in_agg[(row[0], row[1])] = row[2]
        cur.execute(
            "SELECT from_stand_id, product_id, SUM(quantity) as total "
            "FROM inter_stand_transfers GROUP BY from_stand_id, product_id"
        )
        for row in cur.fetchall():
            transfers_out_agg[(row[0], row[1])] = row[2]

        conn.close()

        # --- Build variance report ---
        variance_rows = []
        for sid in stand_ids:
            for pid in product_ids:
                key = (sid, pid)
                begin = begin_map.get(key, 0)
                delivered = delivery_agg.get(key, 0)
                t_in = transfers_in_agg.get(key, 0)
                returned = returns_agg.get(key, 0)
                sold = sales_agg.get(key, 0)
                wasted = waste_agg.get(key, 0)
                t_out = transfers_out_agg.get(key, 0)
                actual_end = end_map.get(key, 0)

                supply = begin + delivered + t_in + returned
                consumed = sold + wasted + t_out
                expected_end = supply - consumed
                variance = expected_end - actual_end
                variance_pct = round((variance / supply * 100) if supply > 0 else 0.0, 2)
                unit_cost = catalog[pid]["unit_cost"]
                shrinkage_val = round(max(0, variance) * unit_cost, 2)

                variance_rows.append({
                    "stand_id": sid,
                    "stand_name": stand_dir[sid]["name"],
                    "product_id": pid,
                    "product_name": catalog[pid]["name"],
                    "beginning_qty": begin,
                    "delivered_qty": delivered,
                    "transferred_in_qty": t_in,
                    "returned_qty": returned,
                    "sold_qty": sold,
                    "wasted_qty": wasted,
                    "transferred_out_qty": t_out,
                    "expected_ending_qty": expected_end,
                    "actual_ending_qty": actual_end,
                    "variance_qty": variance,
                    "variance_pct": variance_pct,
                    "shrinkage_value_usd": shrinkage_val,
                })

        # --- Flagged stands ---
        pct_thresh = policy["flagging_criteria"]["shrinkage_pct_threshold"]
        val_thresh = policy["flagging_criteria"]["min_shrinkage_value_usd"]
        priority_bands = policy["investigation_priority"]

        stand_agg = {}
        for vr in variance_rows:
            sid = vr["stand_id"]
            if sid not in stand_agg:
                stand_agg[sid] = {"pos_variance": 0, "total_supply": 0, "name": vr["stand_name"]}
            if vr["variance_qty"] > 0:
                stand_agg[sid]["pos_variance"] += vr["variance_qty"] * \
                    catalog[vr["product_id"]]["unit_cost"]
            stand_agg[sid]["total_supply"] += (
                vr["beginning_qty"] + vr["delivered_qty"] +
                vr["transferred_in_qty"] + vr["returned_qty"]
            )

        # For shrinkage pct: sum positive variances / sum total supply
        stand_shrinkage_pct = {}
        stand_pos_var_units = {}
        for vr in variance_rows:
            sid = vr["stand_id"]
            if sid not in stand_pos_var_units:
                stand_pos_var_units[sid] = 0
            if vr["variance_qty"] > 0:
                stand_pos_var_units[sid] += vr["variance_qty"]

        for sid in stand_ids:
            total_supply = stand_agg[sid]["total_supply"]
            pos_units = stand_pos_var_units.get(sid, 0)
            stand_shrinkage_pct[sid] = round(
                (pos_units / total_supply * 100) if total_supply > 0 else 0.0, 2
            )

        # Get staff for all stands
        conn2 = sqlite3.connect(self.db_path)
        cur2 = conn2.cursor()

        flagged = []
        for sid in stand_ids:
            total_val = round(stand_agg[sid]["pos_variance"], 2)
            pct = stand_shrinkage_pct[sid]
            if total_val > val_thresh and pct > pct_thresh:
                # Determine priority
                if pct >= priority_bands["high"]["min_shrinkage_pct"]:
                    priority = "high"
                elif pct >= priority_bands["medium"]["min_shrinkage_pct"]:
                    priority = "medium"
                else:
                    priority = "low"

                # Get staff
                cur2.execute(
                    "SELECT DISTINCT employee_name FROM staff_schedules WHERE stand_id = ? ORDER BY employee_name",
                    (sid,),
                )
                staff_names = [r[0] for r in cur2.fetchall()]

                flagged.append({
                    "stand_id": sid,
                    "stand_name": stand_agg[sid]["name"],
                    "total_shrinkage_value": total_val,
                    "shrinkage_pct": pct,
                    "investigation_priority": priority,
                    "staff_on_duty": "; ".join(staff_names),
                })

        conn2.close()
        flagged.sort(key=lambda x: x["total_shrinkage_value"], reverse=True)

        return {
            "variance_rows": variance_rows,
            "flagged": flagged,
            "num_stands": len(stand_ids),
            "catalog": catalog,
            "stand_dir": stand_dir,
            "policy": policy,
        }

    # ══════════════════════════════════════════════════════════════
    # Evaluation
    # ══════════════════════════════════════════════════════════════

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
        gt_var = gt["variance_rows"]
        gt_flagged = gt["flagged"]
        num_stands = gt["num_stands"]

        criteria = {}

        # ── Criterion 1: variance_report.csv exists with correct columns (10 pts) ──
        vr_path = os.path.join(self.workspace, "variance_report.csv")
        expected_cols = [
            "stand_id", "stand_name", "product_id", "product_name",
            "beginning_qty", "delivered_qty", "transferred_in_qty", "returned_qty",
            "sold_qty", "wasted_qty", "transferred_out_qty",
            "expected_ending_qty", "actual_ending_qty",
            "variance_qty", "variance_pct", "shrinkage_value_usd",
        ]
        if os.path.exists(vr_path):
            try:
                vr_df = pd.read_csv(vr_path)
                agent_cols = list(vr_df.columns)
                if agent_cols == expected_cols:
                    criteria["variance_report_format"] = {
                        "passed": True, "score": 10, "max_score": 10,
                    }
                else:
                    missing = set(expected_cols) - set(agent_cols)
                    extra = set(agent_cols) - set(expected_cols)
                    criteria["variance_report_format"] = {
                        "passed": False, "score": 3, "max_score": 10,
                        "reason": f"Column mismatch. Missing: {missing}. Extra: {extra}.",
                    }
            except Exception as e:
                vr_df = None
                criteria["variance_report_format"] = {
                    "passed": False, "score": 0, "max_score": 10,
                    "reason": f"Failed to read CSV: {e}",
                }
        else:
            vr_df = None
            criteria["variance_report_format"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "variance_report.csv not found in workspace.",
            }

        # ── Criterion 2: Variance quantities correct (25 pts) ──
        if vr_df is not None and "variance_qty" in vr_df.columns:
            gt_map = {}
            for vr in gt_var:
                gt_map[(vr["stand_id"], vr["product_id"])] = vr

            correct = 0
            total_checked = 0
            for _, row in vr_df.iterrows():
                key = (str(row.get("stand_id", "")), str(row.get("product_id", "")))
                if key in gt_map:
                    total_checked += 1
                    gt_row = gt_map[key]
                    try:
                        agent_var = int(float(row["variance_qty"]))
                        if agent_var == gt_row["variance_qty"]:
                            correct += 1
                    except (ValueError, TypeError):
                        pass

            expected_total = len(gt_var)
            if expected_total > 0:
                score = round(25 * correct / expected_total, 1)
            else:
                score = 0
            criteria["variance_calculations"] = {
                "passed": correct == expected_total,
                "score": score,
                "max_score": 25,
                "reason": f"{correct}/{expected_total} variance quantities correct." if correct < expected_total else "",
            }
        else:
            criteria["variance_calculations"] = {
                "passed": False, "score": 0, "max_score": 25,
                "reason": "variance_report.csv missing or lacks variance_qty column.",
            }

        # ── Criterion 3: Flagged stands identification (20 pts) ──
        fs_path = os.path.join(self.workspace, "flagged_stands.csv")
        if os.path.exists(fs_path):
            try:
                fs_df = pd.read_csv(fs_path)
                gt_flagged_ids = set(f["stand_id"] for f in gt_flagged)
                agent_flagged_ids = set(str(s) for s in fs_df["stand_id"].tolist()) if "stand_id" in fs_df.columns else set()

                if gt_flagged_ids == agent_flagged_ids:
                    criteria["flagged_stands_identification"] = {
                        "passed": True, "score": 20, "max_score": 20,
                    }
                else:
                    tp = len(gt_flagged_ids & agent_flagged_ids)
                    total_gt = len(gt_flagged_ids)
                    total_agent = len(agent_flagged_ids)
                    if total_gt > 0:
                        recall = tp / total_gt
                    else:
                        recall = 1.0
                    if total_agent > 0:
                        precision = tp / total_agent
                    else:
                        precision = 0.0
                    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
                    score = round(20 * f1, 1)
                    criteria["flagged_stands_identification"] = {
                        "passed": False, "score": score, "max_score": 20,
                        "reason": f"Expected {gt_flagged_ids}, got {agent_flagged_ids}.",
                    }
            except Exception as e:
                fs_df = None
                criteria["flagged_stands_identification"] = {
                    "passed": False, "score": 0, "max_score": 20,
                    "reason": f"Failed to read flagged_stands.csv: {e}",
                }
        else:
            fs_df = None
            criteria["flagged_stands_identification"] = {
                "passed": False, "score": 0, "max_score": 20,
                "reason": "flagged_stands.csv not found in workspace.",
            }

        # ── Criterion 4: Investigation priority correct (15 pts) ──
        if fs_df is not None and "investigation_priority" in fs_df.columns:
            gt_prio = {f["stand_id"]: f["investigation_priority"] for f in gt_flagged}
            correct_prio = 0
            checked_prio = 0
            for _, row in fs_df.iterrows():
                sid = str(row.get("stand_id", ""))
                if sid in gt_prio:
                    checked_prio += 1
                    if str(row.get("investigation_priority", "")).strip().lower() == gt_prio[sid]:
                        correct_prio += 1
            total_prio = len(gt_prio)
            if total_prio > 0:
                score = round(15 * correct_prio / total_prio, 1)
            else:
                score = 15
            criteria["priority_assignment"] = {
                "passed": correct_prio == total_prio,
                "score": score,
                "max_score": 15,
                "reason": f"{correct_prio}/{total_prio} priorities correct." if correct_prio < total_prio else "",
            }
        else:
            criteria["priority_assignment"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "flagged_stands.csv missing or lacks investigation_priority column.",
            }

        # ── Criterion 5: Staff names correct (15 pts) ──
        if fs_df is not None and "staff_on_duty" in fs_df.columns:
            gt_staff = {f["stand_id"]: set(f["staff_on_duty"].split("; ")) for f in gt_flagged}
            correct_staff = 0
            total_staff_checks = len(gt_staff)
            for _, row in fs_df.iterrows():
                sid = str(row.get("stand_id", ""))
                if sid in gt_staff:
                    agent_staff_str = str(row.get("staff_on_duty", ""))
                    agent_staff = set(s.strip() for s in agent_staff_str.split("; ") if s.strip())
                    if agent_staff == gt_staff[sid]:
                        correct_staff += 1
            if total_staff_checks > 0:
                score = round(15 * correct_staff / total_staff_checks, 1)
            else:
                score = 15
            criteria["staff_association"] = {
                "passed": correct_staff == total_staff_checks,
                "score": score,
                "max_score": 15,
                "reason": f"{correct_staff}/{total_staff_checks} staff lists correct." if correct_staff < total_staff_checks else "",
            }
        else:
            criteria["staff_association"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "flagged_stands.csv missing or lacks staff_on_duty column.",
            }

        # ── Criterion 6: Response summary (15 pts) ──
        summary_score = 0
        summary_reasons = []
        if action:
            action_lower = action.lower()
            # Check total stands analyzed
            if str(num_stands) in action:
                summary_score += 3
            else:
                summary_reasons.append(f"Total stands ({num_stands}) not found in response.")

            # Check number flagged
            num_flagged = len(gt_flagged)
            if str(num_flagged) in action:
                summary_score += 3
            else:
                summary_reasons.append(f"Number flagged ({num_flagged}) not found in response.")

            # Check total shrinkage value
            total_shrinkage = round(sum(f["total_shrinkage_value"] for f in gt_flagged), 2)
            total_str = f"{total_shrinkage:.2f}"
            if total_str in action or str(round(total_shrinkage, 2)) in action:
                summary_score += 4
            else:
                summary_reasons.append(f"Total shrinkage value ({total_str}) not found in response.")

            # Check highest shrinkage stand
            if gt_flagged:
                top_stand = gt_flagged[0]  # sorted desc by value
                if top_stand["stand_name"] in action:
                    summary_score += 3
                else:
                    summary_reasons.append(f"Top stand name ({top_stand['stand_name']}) not found.")
                top_val_str = f"{top_stand['total_shrinkage_value']:.2f}"
                if top_val_str in action:
                    summary_score += 2
                else:
                    summary_reasons.append(f"Top stand value ({top_val_str}) not found.")
        else:
            summary_reasons.append("Empty response.")

        criteria["response_summary"] = {
            "passed": summary_score == 15,
            "score": summary_score,
            "max_score": 15,
            "reason": "; ".join(summary_reasons) if summary_reasons else "",
        }

        # ── Aggregate ──
        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ══════════════════════════════════════════════════════════════
    # Verification
    # ══════════════════════════════════════════════════════════════

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
        import csv as csv_mod

        tool_calls = 0

        # ── Step 1: Read workspace files ──
        with open(os.path.join(self.workspace, "product_catalog.json")) as f:
            catalog = json.load(f)
        with open(os.path.join(self.workspace, "stand_directory.yaml")) as f:
            stand_dir = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "shrinkage_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        stand_ids = sorted(stand_dir.keys())
        product_ids = sorted(catalog.keys())

        # Beginning inventory
        begin_map = {}
        begin_df = pd.read_csv(os.path.join(self.workspace, "beginning_inventory.csv"))
        for _, row in begin_df.iterrows():
            begin_map[(row["stand_id"], row["product_id"])] = int(row["quantity"])

        # Ending inventory
        end_map = {}
        end_df = pd.read_csv(os.path.join(self.workspace, "ending_inventory.csv"))
        for _, row in end_df.iterrows():
            end_map[(row["stand_id"], row["product_id"])] = int(row["quantity"])

        # Deliveries from invoice files
        delivery_agg = {}
        inv_dir = os.path.join(self.workspace, "delivery_invoices")
        if os.path.isdir(inv_dir):
            for fname in sorted(os.listdir(inv_dir)):
                fpath = os.path.join(inv_dir, fname)
                if fname.endswith(".csv"):
                    df = pd.read_csv(fpath)
                    for _, row in df.iterrows():
                        key = (row["stand_id"], row["product_id"])
                        delivery_agg[key] = delivery_agg.get(key, 0) + int(row["quantity_delivered"])

        # Waste from waste log files
        waste_agg = {}
        waste_dir = os.path.join(self.workspace, "waste_logs")
        if os.path.isdir(waste_dir):
            for fname in sorted(os.listdir(waste_dir)):
                fpath = os.path.join(waste_dir, fname)
                if fname.endswith(".csv"):
                    df = pd.read_csv(fpath)
                    for _, row in df.iterrows():
                        key = (row["stand_id"], row["product_id"])
                        waste_agg[key] = waste_agg.get(key, 0) + int(row["quantity_wasted"])
                elif fname.endswith(".txt"):
                    with open(fpath) as f:
                        lines = f.read().strip().split("\n")
                    for line in lines[1:]:
                        parts = line.split("|")
                        if len(parts) >= 4:
                            key = (parts[0].strip(), parts[1].strip())
                            waste_agg[key] = waste_agg.get(key, 0) + int(parts[3].strip())
                elif fname.endswith(".md"):
                    with open(fpath) as f:
                        lines = f.read().strip().split("\n")
                    for line in lines[2:]:
                        parts = [p.strip() for p in line.split("|")]
                        parts = [p for p in parts if p]
                        if len(parts) >= 4:
                            key = (parts[0], parts[1])
                            waste_agg[key] = waste_agg.get(key, 0) + int(parts[3])

        # ── Step 2: Query tools for each stand ──
        sales_agg = {}
        returns_agg = {}
        transfers_in_agg = {}
        transfers_out_agg = {}

        for sid in stand_ids:
            # Query POS transactions (paginated)
            page = 1
            while True:
                result = json.loads(self.tools["query_transactions"](stand_id=sid, page=page))
                tool_calls += 1
                for txn in result["transactions"]:
                    key = (txn["stand_id"], txn["product_id"])
                    sales_agg[key] = sales_agg.get(key, 0) + txn["quantity_sold"]
                if not result["has_more"]:
                    break
                page += 1

            # Query returns
            result = json.loads(self.tools["query_returns"](stand_id=sid))
            tool_calls += 1
            for ret in result["returns"]:
                key = (ret["stand_id"], ret["product_id"])
                returns_agg[key] = returns_agg.get(key, 0) + ret["quantity_returned"]

            # Query inbound transfers
            result = json.loads(self.tools["query_transfers"](stand_id=sid, direction="inbound"))
            tool_calls += 1
            for tr in result["transfers"]:
                key = (tr["to_stand_id"], tr["product_id"])
                transfers_in_agg[key] = transfers_in_agg.get(key, 0) + tr["quantity"]

            # Query outbound transfers
            result = json.loads(self.tools["query_transfers"](stand_id=sid, direction="outbound"))
            tool_calls += 1
            for tr in result["transfers"]:
                key = (tr["from_stand_id"], tr["product_id"])
                transfers_out_agg[key] = transfers_out_agg.get(key, 0) + tr["quantity"]

        # ── Step 3: Compute variance report ──
        variance_rows = []
        for sid in stand_ids:
            for pid in product_ids:
                key = (sid, pid)
                begin = begin_map.get(key, 0)
                delivered = delivery_agg.get(key, 0)
                t_in = transfers_in_agg.get(key, 0)
                returned = returns_agg.get(key, 0)
                sold = sales_agg.get(key, 0)
                wasted = waste_agg.get(key, 0)
                t_out = transfers_out_agg.get(key, 0)
                actual_end = end_map.get(key, 0)

                supply = begin + delivered + t_in + returned
                consumed = sold + wasted + t_out
                expected_end = supply - consumed
                variance = expected_end - actual_end
                variance_pct = round((variance / supply * 100) if supply > 0 else 0.0, 2)
                unit_cost = catalog[pid]["unit_cost"]
                shrinkage_val = round(max(0, variance) * unit_cost, 2)

                variance_rows.append({
                    "stand_id": sid,
                    "stand_name": stand_dir[sid]["name"],
                    "product_id": pid,
                    "product_name": catalog[pid]["name"],
                    "beginning_qty": begin,
                    "delivered_qty": delivered,
                    "transferred_in_qty": t_in,
                    "returned_qty": returned,
                    "sold_qty": sold,
                    "wasted_qty": wasted,
                    "transferred_out_qty": t_out,
                    "expected_ending_qty": expected_end,
                    "actual_ending_qty": actual_end,
                    "variance_qty": variance,
                    "variance_pct": variance_pct,
                    "shrinkage_value_usd": shrinkage_val,
                })

        # Write variance_report.csv (sorted by stand_id, product_id)
        variance_rows.sort(key=lambda x: (x["stand_id"], x["product_id"]))
        vr_path = os.path.join(self.workspace, "variance_report.csv")
        cols = [
            "stand_id", "stand_name", "product_id", "product_name",
            "beginning_qty", "delivered_qty", "transferred_in_qty", "returned_qty",
            "sold_qty", "wasted_qty", "transferred_out_qty",
            "expected_ending_qty", "actual_ending_qty",
            "variance_qty", "variance_pct", "shrinkage_value_usd",
        ]
        with open(vr_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            writer.writerows(variance_rows)

        # ── Step 4: Determine flagged stands ──
        pct_thresh = policy["flagging_criteria"]["shrinkage_pct_threshold"]
        val_thresh = policy["flagging_criteria"]["min_shrinkage_value_usd"]
        priority_bands = policy["investigation_priority"]

        # Aggregate per stand
        stand_pos_var_value = {}  # sum of positive variance * unit_cost
        stand_pos_var_units = {}  # sum of positive variance units
        stand_total_supply = {}
        for vr in variance_rows:
            sid = vr["stand_id"]
            if sid not in stand_pos_var_value:
                stand_pos_var_value[sid] = 0.0
                stand_pos_var_units[sid] = 0
                stand_total_supply[sid] = 0
            if vr["variance_qty"] > 0:
                stand_pos_var_value[sid] += vr["variance_qty"] * catalog[vr["product_id"]]["unit_cost"]
                stand_pos_var_units[sid] += vr["variance_qty"]
            stand_total_supply[sid] += (
                vr["beginning_qty"] + vr["delivered_qty"] +
                vr["transferred_in_qty"] + vr["returned_qty"]
            )

        flagged = []
        for sid in stand_ids:
            total_val = round(stand_pos_var_value.get(sid, 0.0), 2)
            total_supply = stand_total_supply.get(sid, 0)
            pos_units = stand_pos_var_units.get(sid, 0)
            pct = round((pos_units / total_supply * 100) if total_supply > 0 else 0.0, 2)

            if total_val > val_thresh and pct > pct_thresh:
                if pct >= priority_bands["high"]["min_shrinkage_pct"]:
                    priority = "high"
                elif pct >= priority_bands["medium"]["min_shrinkage_pct"]:
                    priority = "medium"
                else:
                    priority = "low"

                # Query staff
                result = json.loads(self.tools["query_staff_schedule"](stand_id=sid))
                tool_calls += 1
                staff_names = sorted(set(s["employee_name"] for s in result["schedules"]))

                flagged.append({
                    "stand_id": sid,
                    "stand_name": stand_dir[sid]["name"],
                    "total_shrinkage_value": total_val,
                    "shrinkage_pct": pct,
                    "investigation_priority": priority,
                    "staff_on_duty": "; ".join(staff_names),
                })

        flagged.sort(key=lambda x: x["total_shrinkage_value"], reverse=True)

        # Write flagged_stands.csv
        fs_path = os.path.join(self.workspace, "flagged_stands.csv")
        fs_cols = [
            "stand_id", "stand_name", "total_shrinkage_value",
            "shrinkage_pct", "investigation_priority", "staff_on_duty",
        ]
        with open(fs_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=fs_cols)
            writer.writeheader()
            writer.writerows(flagged)

        # ── Step 5: Construct action string ──
        num_stands = len(stand_ids)
        num_flagged = len(flagged)
        total_shrinkage = round(sum(f["total_shrinkage_value"] for f in flagged), 2)
        if flagged:
            top = flagged[0]
            top_name = top["stand_name"]
            top_val = f"{top['total_shrinkage_value']:.2f}"
        else:
            top_name = "N/A"
            top_val = "0.00"

        action = (
            f"Inventory shrinkage reconciliation complete. "
            f"Total stands analyzed: {num_stands}. "
            f"Stands flagged for investigation: {num_flagged}. "
            f"Total shrinkage value across flagged stands: ${total_shrinkage:.2f} USD. "
            f"The stand with the highest shrinkage value is {top_name} at ${top_val}."
        )

        print(f"[verify] Tool calls made: {tool_calls}")
        assert tool_calls >= 15, f"Too few tool calls: {tool_calls}"

        return self.step(action)
