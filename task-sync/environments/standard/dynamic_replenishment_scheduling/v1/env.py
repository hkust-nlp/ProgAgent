"""
Warehouse replenishment optimization - task environment.
"""

import csv
import glob
import json
import math
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import pandas as pd
import yaml


# ── Tool decorator ───────────────────────────────────────────────────

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ── Task Environment ─────────────────────────────────────────────────

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

    # ── Tool methods ─────────────────────────────────────────────────

    @tool(
        description="Returns the list of all warehouse zone identifiers.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def get_zone_ids(self) -> List[str]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT DISTINCT zone_id FROM pick_faces ORDER BY zone_id")
        zones = [r[0] for r in c.fetchall()]
        conn.close()
        return zones

    @tool(
        description="Returns pick-face stock records for a given zone, paginated. Each page contains up to page_size records.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "string",
                    "description": "The zone identifier, e.g. 'Z01'.",
                },
                "page": {
                    "type": "integer",
                    "description": "1-based page number (default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (default 20).",
                },
            },
            "required": ["zone_id"],
        },
    )
    def query_pick_faces(self, zone_id: str, page: int = 1, page_size: int = 20) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        offset = (page - 1) * page_size
        c.execute(
            "SELECT pick_face_id, sku_id, zone_id, aisle, position, current_qty, max_capacity, last_replenished "
            "FROM pick_faces WHERE zone_id = ? ORDER BY pick_face_id LIMIT ? OFFSET ?",
            (zone_id, page_size + 1, offset),
        )
        rows = c.fetchall()
        conn.close()
        cols = ["pick_face_id", "sku_id", "zone_id", "aisle", "position",
                "current_qty", "max_capacity", "last_replenished"]
        data = [dict(zip(cols, r)) for r in rows[:page_size]]
        return {"data": data, "page": page, "has_more": len(rows) > page_size}

    @tool(
        description="Returns detailed information for a single SKU, including case pack quantity, weight, category, and storage type.",
        parameters={
            "type": "object",
            "properties": {
                "sku_id": {
                    "type": "string",
                    "description": "The SKU identifier, e.g. 'SKU-0001'.",
                },
            },
            "required": ["sku_id"],
        },
    )
    def get_sku_details(self, sku_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT sku_id, sku_name, category, case_pack_qty, weight_per_case_kg, storage_type "
            "FROM sku_master WHERE sku_id = ?",
            (sku_id,),
        )
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"SKU {sku_id} not found"}
        cols = ["sku_id", "sku_name", "category", "case_pack_qty",
                "weight_per_case_kg", "storage_type"]
        return dict(zip(cols, row))

    @tool(
        description="Returns the historical average picking rate for a single SKU, including average, peak, and off-peak units per hour.",
        parameters={
            "type": "object",
            "properties": {
                "sku_id": {
                    "type": "string",
                    "description": "The SKU identifier.",
                },
            },
            "required": ["sku_id"],
        },
    )
    def get_picking_rate(self, sku_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT sku_id, avg_units_per_hour, peak_rate, off_peak_rate "
            "FROM picking_rates WHERE sku_id = ?",
            (sku_id,),
        )
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"No picking rate for {sku_id}"}
        cols = ["sku_id", "avg_units_per_hour", "peak_rate", "off_peak_rate"]
        return dict(zip(cols, row))

    @tool(
        description="Returns inbound dock schedules, optionally filtered by status. Paginated.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: 'scheduled', 'in_transit', 'arrived', or 'unloading'. Omit for all.",
                },
                "page": {
                    "type": "integer",
                    "description": "1-based page number (default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (default 50).",
                },
            },
            "required": [],
        },
    )
    def query_dock_schedule(self, status: str = None, page: int = 1, page_size: int = 50) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        offset = (page - 1) * page_size
        if status:
            c.execute(
                "SELECT schedule_id, dock_id, sku_id, eta_hours, cases_expected, carrier, status, priority_flag "
                "FROM dock_schedules WHERE status = ? ORDER BY eta_hours LIMIT ? OFFSET ?",
                (status, page_size + 1, offset),
            )
        else:
            c.execute(
                "SELECT schedule_id, dock_id, sku_id, eta_hours, cases_expected, carrier, status, priority_flag "
                "FROM dock_schedules ORDER BY eta_hours LIMIT ? OFFSET ?",
                (page_size + 1, offset),
            )
        rows = c.fetchall()
        conn.close()
        cols = ["schedule_id", "dock_id", "sku_id", "eta_hours", "cases_expected",
                "carrier", "status", "priority_flag"]
        data = [dict(zip(cols, r)) for r in rows[:page_size]]
        return {"data": data, "page": page, "has_more": len(rows) > page_size}

    @tool(
        description="Returns the most recent telemetry snapshot for each forklift, optionally filtered by zone. Includes forklift_id, zone_id, battery_pct, status, and operator_id.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "string",
                    "description": "Filter by zone identifier. Omit for all zones.",
                },
            },
            "required": [],
        },
    )
    def get_forklift_status(self, zone_id: str = None) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        base = (
            "SELECT ft.forklift_id, ft.zone_id, ft.battery_pct, ft.status, ft.operator_id, ft.last_update "
            "FROM forklift_telemetry ft "
            "INNER JOIN ("
            "  SELECT forklift_id, MAX(record_id) AS max_id "
            "  FROM forklift_telemetry GROUP BY forklift_id"
            ") latest ON ft.record_id = latest.max_id"
        )
        if zone_id:
            c.execute(base + " WHERE ft.zone_id = ? ORDER BY ft.forklift_id", (zone_id,))
        else:
            c.execute(base + " ORDER BY ft.forklift_id")
        rows = c.fetchall()
        conn.close()
        cols = ["forklift_id", "zone_id", "battery_pct", "status", "operator_id", "last_update"]
        return [dict(zip(cols, r)) for r in rows]

    # ── Workspace readers (shared by step & verify) ──────────────────

    def _read_policy(self) -> dict:
        with open(os.path.join(self.workspace, "replenishment_policy.yaml")) as f:
            return yaml.safe_load(f)

    def _read_time_standards(self) -> dict:
        with open(os.path.join(self.workspace, "time_standards.json")) as f:
            return json.load(f)

    def _read_zone_config(self) -> dict:
        df = pd.read_csv(os.path.join(self.workspace, "zone_config.csv"))
        return {
            row["zone_id"]: {
                "zone_type": row["zone_type"],
                "travel_factor": float(row["travel_factor"]),
                "congestion_factor": float(row["congestion_factor"]),
            }
            for _, row in df.iterrows()
        }

    def _read_demand_adjustments(self) -> dict:
        dm = {}
        pattern = os.path.join(self.workspace, "demand_adjustment_*.csv")
        for path in sorted(glob.glob(pattern)):
            df = pd.read_csv(path)
            for _, row in df.iterrows():
                dm[row["sku_id"]] = float(row["demand_multiplier"])
        return dm

    def _read_forklift_roster(self) -> dict:
        eff = {}
        with open(os.path.join(self.workspace, "forklift_roster.txt")) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                eff[parts[0]] = float(parts[2])
        return eff

    # ── Shared computation ───────────────────────────────────────────

    def _compute_plan(
        self,
        pick_faces: list,
        skus: dict,
        rates: dict,
        dock_schedules: list,
        forklift_status: dict,
        zone_config: dict,
        policy: dict,
        time_std: dict,
        demand_mult: dict,
        forklift_eff: dict,
    ) -> list:
        thresholds = policy["stock_thresholds"]
        weights = policy["priority_weights"]
        storage_factors = policy["storage_type_factors"]
        target_fill = policy["target_fill_pct"]
        min_battery = policy["min_battery_pct"]
        dock_thresh = policy["dock_threshold_hours"]

        proactive = time_std["proactive_time_per_case_min"]
        reactive = time_std["reactive_time_per_case_min"]
        base_travel = time_std["base_travel_time_min"]
        idle_penalty = time_std["picker_idle_penalty_min"]

        max_storage = max(storage_factors.values())

        # Identify candidates
        candidates = []
        for pf in pick_faces:
            sku_id = pf["sku_id"]
            zone_id = pf["zone_id"]
            ztype = zone_config[zone_id]["zone_type"]
            thresh = thresholds[ztype]
            stock_pct = pf["current_qty"] / pf["max_capacity"] * 100.0

            if stock_pct >= thresh:
                continue

            sku = skus.get(sku_id)
            rate_info = rates.get(sku_id)
            if sku is None or rate_info is None:
                continue

            dm = demand_mult.get(sku_id, 1.0)
            adjusted_rate = rate_info["avg_units_per_hour"] * dm

            if adjusted_rate <= 0:
                hours_dep = 999.0
            else:
                hours_dep = pf["current_qty"] / adjusted_rate

            cases_needed = math.ceil(
                (pf["max_capacity"] * target_fill / 100.0 - pf["current_qty"])
                / sku["case_pack_qty"]
            )
            cases_needed = max(1, cases_needed)

            # Dock factor
            has_incoming = False
            for ds in dock_schedules:
                if (ds["sku_id"] == sku_id
                        and ds["status"] in ("scheduled", "in_transit")
                        and ds["eta_hours"] < dock_thresh):
                    has_incoming = True
                    break
            dock_factor = 0.0 if has_incoming else 1.0

            candidates.append({
                "pick_face_id": pf["pick_face_id"],
                "sku_id": sku_id,
                "zone_id": zone_id,
                "current_stock_pct": round(stock_pct, 1),
                "hours_until_depletion": round(hours_dep, 2),
                "cases_needed": cases_needed,
                "adjusted_rate": adjusted_rate,
                "dock_factor": dock_factor,
                "storage_type": sku["storage_type"],
            })

        if not candidates:
            return []

        # Normalize urgency & demand
        urgencies = [1.0 / max(c["hours_until_depletion"], 0.001) for c in candidates]
        demands = [c["adjusted_rate"] for c in candidates]
        max_urg = max(urgencies)
        max_dem = max(demands)

        for i, c in enumerate(candidates):
            norm_urg = urgencies[i] / max_urg if max_urg else 0
            norm_dem = demands[i] / max_dem if max_dem else 0
            sf = storage_factors.get(c["storage_type"], 1.0)
            c["priority_score"] = (
                weights["urgency"] * norm_urg
                + weights["demand"] * norm_dem
                + weights["storage_penalty"] * (sf / max_storage)
                + weights["dock_proximity"] * c["dock_factor"]
            )

        # Sort: score desc, sku_id asc
        candidates.sort(key=lambda x: (-x["priority_score"], x["sku_id"]))

        # Forklift assignment per zone (highest battery idle forklift)
        zone_fl = {}
        for zid, fls in forklift_status.items():
            avail = [f for f in fls
                     if f["status"] == "idle" and f["battery_pct"] >= min_battery]
            avail.sort(key=lambda x: -x["battery_pct"])
            zone_fl[zid] = avail[0]["forklift_id"] if avail else "NONE"

        # Build plan
        plan = []
        for rank, c in enumerate(candidates, 1):
            fl_id = zone_fl.get(c["zone_id"], "NONE")
            eff = forklift_eff.get(fl_id, 1.0) if fl_id != "NONE" else 1.0

            zc = zone_config[c["zone_id"]]
            travel = base_travel * zc["travel_factor"] * zc["congestion_factor"]
            replenish_time = round(travel + c["cases_needed"] * proactive / eff, 2)
            time_saving = round(
                c["cases_needed"] * (reactive - proactive) / eff + idle_penalty, 2
            )

            plan.append({
                "priority_rank": rank,
                "sku_id": c["sku_id"],
                "pick_face_id": c["pick_face_id"],
                "zone_id": c["zone_id"],
                "current_stock_pct": c["current_stock_pct"],
                "hours_until_depletion": c["hours_until_depletion"],
                "cases_needed": c["cases_needed"],
                "assigned_forklift": fl_id,
                "estimated_replenish_time_min": replenish_time,
                "time_saving_min": time_saving,
            })
        return plan

    # ── DB readers (for step ground-truth) ───────────────────────────

    def _db_all_pick_faces(self, conn) -> list:
        c = conn.cursor()
        c.execute("SELECT pick_face_id, sku_id, zone_id, aisle, position, "
                  "current_qty, max_capacity, last_replenished FROM pick_faces")
        cols = ["pick_face_id", "sku_id", "zone_id", "aisle", "position",
                "current_qty", "max_capacity", "last_replenished"]
        return [dict(zip(cols, r)) for r in c.fetchall()]

    def _db_all_skus(self, conn) -> dict:
        c = conn.cursor()
        c.execute("SELECT sku_id, sku_name, category, case_pack_qty, "
                  "weight_per_case_kg, storage_type FROM sku_master")
        cols = ["sku_id", "sku_name", "category", "case_pack_qty",
                "weight_per_case_kg", "storage_type"]
        return {r[0]: dict(zip(cols, r)) for r in c.fetchall()}

    def _db_all_rates(self, conn) -> dict:
        c = conn.cursor()
        c.execute("SELECT sku_id, avg_units_per_hour, peak_rate, off_peak_rate FROM picking_rates")
        cols = ["sku_id", "avg_units_per_hour", "peak_rate", "off_peak_rate"]
        return {r[0]: dict(zip(cols, r)) for r in c.fetchall()}

    def _db_all_dock_schedules(self, conn) -> list:
        c = conn.cursor()
        c.execute("SELECT schedule_id, dock_id, sku_id, eta_hours, cases_expected, "
                  "carrier, status, priority_flag FROM dock_schedules")
        cols = ["schedule_id", "dock_id", "sku_id", "eta_hours", "cases_expected",
                "carrier", "status", "priority_flag"]
        return [dict(zip(cols, r)) for r in c.fetchall()]

    def _db_latest_forklift_status(self, conn) -> dict:
        c = conn.cursor()
        c.execute(
            "SELECT ft.forklift_id, ft.zone_id, ft.battery_pct, ft.status, ft.operator_id "
            "FROM forklift_telemetry ft "
            "INNER JOIN ("
            "  SELECT forklift_id, MAX(record_id) AS max_id "
            "  FROM forklift_telemetry GROUP BY forklift_id"
            ") latest ON ft.record_id = latest.max_id"
        )
        cols = ["forklift_id", "zone_id", "battery_pct", "status", "operator_id"]
        by_zone: dict = {}
        for r in c.fetchall():
            d = dict(zip(cols, r))
            by_zone.setdefault(d["zone_id"], []).append(d)
        return by_zone

    # ── Evaluation ───────────────────────────────────────────────────

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
        # ── Compute ground truth ──
        policy = self._read_policy()
        time_std = self._read_time_standards()
        zone_config = self._read_zone_config()
        demand_mult = self._read_demand_adjustments()
        forklift_eff = self._read_forklift_roster()

        conn = sqlite3.connect(self.db_path)
        pfs = self._db_all_pick_faces(conn)
        skus = self._db_all_skus(conn)
        rates = self._db_all_rates(conn)
        docks = self._db_all_dock_schedules(conn)
        fl_status = self._db_latest_forklift_status(conn)
        conn.close()

        expected = self._compute_plan(
            pfs, skus, rates, docks, fl_status,
            zone_config, policy, time_std, demand_mult, forklift_eff,
        )

        criteria: Dict[str, dict] = {}

        # ── Criterion 1: file_format (10 pts) ──
        plan_path = os.path.join(self.workspace, "replenishment_plan.csv")
        required_cols = [
            "priority_rank", "sku_id", "pick_face_id", "zone_id",
            "current_stock_pct", "hours_until_depletion", "cases_needed",
            "assigned_forklift", "estimated_replenish_time_min", "time_saving_min",
        ]
        actual_rows = []
        try:
            df = pd.read_csv(plan_path)
            has_cols = all(c in df.columns for c in required_cols)
            if has_cols:
                actual_rows = df.to_dict("records")
            criteria["file_format"] = {
                "passed": has_cols and len(df) == len(expected),
                "score": 10 if (has_cols and len(df) == len(expected)) else (5 if has_cols else 0),
                "max_score": 10,
            }
        except Exception as e:
            criteria["file_format"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": f"Cannot read CSV: {e}",
            }

        # Helper: map actual rows by sku_id+pick_face_id
        actual_map = {}
        for r in actual_rows:
            key = (str(r.get("sku_id", "")), str(r.get("pick_face_id", "")))
            actual_map[key] = r
        expected_map = {(r["sku_id"], r["pick_face_id"]): r for r in expected}

        # ── Criterion 2: sku_identification (20 pts) ──
        expected_keys = set(expected_map.keys())
        actual_keys = set(actual_map.keys())
        if expected_keys:
            overlap = len(expected_keys & actual_keys)
            score2 = round(20 * overlap / len(expected_keys))
        else:
            score2 = 20 if not actual_keys else 0
        criteria["sku_identification"] = {
            "passed": expected_keys == actual_keys,
            "score": score2, "max_score": 20,
        }
        if expected_keys != actual_keys:
            missing = expected_keys - actual_keys
            extra = actual_keys - expected_keys
            reason = ""
            if missing:
                reason += f"Missing {len(missing)} items. "
            if extra:
                reason += f"Extra {len(extra)} items."
            criteria["sku_identification"]["reason"] = reason.strip()

        # ── Criterion 3: priority_ranking (15 pts) ──
        expected_order = [(r["sku_id"], r["pick_face_id"]) for r in expected]
        actual_order = []
        if actual_rows:
            try:
                sorted_actual = sorted(actual_rows, key=lambda r: int(r.get("priority_rank", 9999)))
                actual_order = [(str(r.get("sku_id", "")), str(r.get("pick_face_id", ""))) for r in sorted_actual]
            except (ValueError, TypeError):
                actual_order = [(str(r.get("sku_id", "")), str(r.get("pick_face_id", ""))) for r in actual_rows]
        check_n = min(5, len(expected_order), len(actual_order))
        rank_matches = sum(1 for i in range(check_n) if expected_order[i] == actual_order[i])
        score3 = rank_matches * 3
        criteria["priority_ranking"] = {
            "passed": score3 == 15,
            "score": score3, "max_score": 15,
        }
        if score3 < 15:
            criteria["priority_ranking"]["reason"] = f"{rank_matches}/{check_n} top positions correct"

        # ── Criterion 4: depletion_accuracy (15 pts) ──
        dep_correct = 0
        dep_total = len(expected_map)
        for key, exp in expected_map.items():
            act = actual_map.get(key)
            if act is None:
                continue
            try:
                act_dep = float(act.get("hours_until_depletion", -1))
                exp_dep = exp["hours_until_depletion"]
                if exp_dep == 0:
                    if act_dep == 0:
                        dep_correct += 1
                elif abs(act_dep - exp_dep) / abs(exp_dep) <= 0.05:
                    dep_correct += 1
            except (ValueError, TypeError):
                pass
        score4 = round(15 * dep_correct / dep_total) if dep_total else 0
        criteria["depletion_accuracy"] = {
            "passed": dep_correct == dep_total,
            "score": score4, "max_score": 15,
        }
        if dep_correct < dep_total:
            criteria["depletion_accuracy"]["reason"] = f"{dep_correct}/{dep_total} within 5% tolerance"

        # ── Criterion 5: cases_accuracy (15 pts) ──
        cases_correct = 0
        for key, exp in expected_map.items():
            act = actual_map.get(key)
            if act is None:
                continue
            try:
                if int(act.get("cases_needed", -1)) == exp["cases_needed"]:
                    cases_correct += 1
            except (ValueError, TypeError):
                pass
        score5 = round(15 * cases_correct / dep_total) if dep_total else 0
        criteria["cases_accuracy"] = {
            "passed": cases_correct == dep_total,
            "score": score5, "max_score": 15,
        }
        if cases_correct < dep_total:
            criteria["cases_accuracy"]["reason"] = f"{cases_correct}/{dep_total} exact matches"

        # ── Criterion 6: forklift_assignment (10 pts) ──
        fl_correct = 0
        for key, exp in expected_map.items():
            act = actual_map.get(key)
            if act is None:
                continue
            if str(act.get("assigned_forklift", "")).strip() == exp["assigned_forklift"]:
                fl_correct += 1
        score6 = round(10 * fl_correct / dep_total) if dep_total else 0
        criteria["forklift_assignment"] = {
            "passed": fl_correct == dep_total,
            "score": score6, "max_score": 10,
        }
        if fl_correct < dep_total:
            criteria["forklift_assignment"]["reason"] = f"{fl_correct}/{dep_total} correct"

        # ── Criterion 7: summary_response (15 pts) ──
        total_tasks = len(expected)
        total_savings = round(sum(r["time_saving_min"] for r in expected), 2)
        top_sku = expected[0]["sku_id"] if expected else ""

        s7 = 0
        # 5 pts: total task count in response
        if str(total_tasks) in action:
            s7 += 5
        # 5 pts: total time savings (within 1%)
        try:
            # Search for a number close to total_savings in the action
            import re
            nums = re.findall(r"[\d]+\.?\d*", action)
            for n in nums:
                val = float(n)
                if total_savings > 0 and abs(val - total_savings) / total_savings <= 0.01:
                    s7 += 5
                    break
        except Exception:
            pass
        # 5 pts: top priority SKU mentioned
        if top_sku and top_sku in action:
            s7 += 5
        criteria["summary_response"] = {
            "passed": s7 == 15,
            "score": s7, "max_score": 15,
        }
        if s7 < 15:
            criteria["summary_response"]["reason"] = f"Expected total_tasks={total_tasks}, total_savings={total_savings}, top_sku={top_sku}"

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score, info

    # ── Verification ─────────────────────────────────────────────────

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
        # ── Read workspace configuration ──
        policy = self._read_policy()
        time_std = self._read_time_standards()
        zone_config = self._read_zone_config()
        demand_mult = self._read_demand_adjustments()
        forklift_eff = self._read_forklift_roster()

        thresholds = policy["stock_thresholds"]

        # ── Gather data via tools ──
        zone_ids = self.tools["get_zone_ids"]()

        # All pick faces
        all_pfs = []
        for zid in zone_ids:
            page = 1
            while True:
                result = self.tools["query_pick_faces"](zone_id=zid, page=page, page_size=20)
                all_pfs.extend(result["data"])
                if result["has_more"]:
                    page += 1
                else:
                    break

        # Identify low-stock pick faces
        low_stock_pfs = []
        for pf in all_pfs:
            ztype = zone_config[pf["zone_id"]]["zone_type"]
            stock_pct = pf["current_qty"] / pf["max_capacity"] * 100.0
            if stock_pct < thresholds[ztype]:
                low_stock_pfs.append(pf)

        # Get SKU details & picking rates for needed SKUs
        needed_skus = sorted(set(pf["sku_id"] for pf in low_stock_pfs))
        skus_map = {}
        rates_map = {}
        for sid in needed_skus:
            skus_map[sid] = self.tools["get_sku_details"](sku_id=sid)
            rates_map[sid] = self.tools["get_picking_rate"](sku_id=sid)

        # Dock schedules (all pages)
        all_docks = []
        page = 1
        while True:
            result = self.tools["query_dock_schedule"](page=page, page_size=50)
            all_docks.extend(result["data"])
            if result["has_more"]:
                page += 1
            else:
                break

        # Forklift status per zone
        fl_by_zone = {}
        for zid in zone_ids:
            fl_by_zone[zid] = self.tools["get_forklift_status"](zone_id=zid)

        # ── Compute plan ──
        plan = self._compute_plan(
            low_stock_pfs, skus_map, rates_map, all_docks, fl_by_zone,
            zone_config, policy, time_std, demand_mult, forklift_eff,
        )

        # ── Write deliverable ──
        plan_path = os.path.join(self.workspace, "replenishment_plan.csv")
        fieldnames = [
            "priority_rank", "sku_id", "pick_face_id", "zone_id",
            "current_stock_pct", "hours_until_depletion", "cases_needed",
            "assigned_forklift", "estimated_replenish_time_min", "time_saving_min",
        ]
        with open(plan_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(plan)

        # ── Construct action string ──
        total_tasks = len(plan)
        total_savings = round(sum(r["time_saving_min"] for r in plan), 2)
        top3 = plan[:3]
        top3_str = ", ".join(
            f"{r['sku_id']} (rank {r['priority_rank']}, {r['hours_until_depletion']} hours until depletion)"
            for r in top3
        )
        action = (
            f"Replenishment plan generated with {total_tasks} tasks. "
            f"Total estimated time savings: {total_savings} minutes. "
            f"Top 3 priorities: {top3_str}."
        )

        return self.step(action)
