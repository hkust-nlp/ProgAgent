import sqlite3
import os
import json
import glob
import yaml
import math
import pandas as pd
from typing import Tuple, Dict, List, Any
from collections import defaultdict


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
    # Tools
    # ------------------------------------------------------------------

    @tool(
        description=(
            "Returns a list of all depots with their id, name, region, "
            "manager, and location."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_depots(self) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT depot_id, name, region, manager_name, city, state "
            "FROM depots ORDER BY depot_id"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @tool(
        description=(
            "Returns all drivers assigned to a given depot, including "
            "driver id, name, certification level, hire date, and status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "depot_id": {
                    "type": "integer",
                    "description": "The depot ID to look up drivers for.",
                },
            },
            "required": ["depot_id"],
        },
    )
    def get_depot_drivers(self, depot_id: int) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT driver_id, first_name, last_name, depot_id, "
            "license_class, certification_level, hire_date, status "
            "FROM drivers WHERE depot_id = ? ORDER BY driver_id",
            (int(depot_id),),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @tool(
        description=(
            "Returns geofence violation records for drivers belonging to "
            "a depot during the reporting week (2025-01-06 to 2025-01-12). "
            "Results are paginated."
        ),
        parameters={
            "type": "object",
            "properties": {
                "depot_id": {
                    "type": "integer",
                    "description": "Depot ID whose drivers' violations to query.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page. Default 20.",
                },
            },
            "required": ["depot_id"],
        },
    )
    def query_violations(
        self, depot_id: int, page: int = 1, page_size: int = 20
    ) -> dict:
        depot_id = int(depot_id)
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        offset = (page - 1) * page_size

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        total = conn.execute(
            "SELECT COUNT(*) FROM violations v "
            "JOIN drivers d ON v.driver_id = d.driver_id "
            "WHERE d.depot_id = ? "
            "AND v.timestamp >= '2025-01-06' AND v.timestamp < '2025-01-13'",
            (depot_id,),
        ).fetchone()[0]

        rows = conn.execute(
            "SELECT v.violation_id, v.driver_id, v.customer_id, "
            "v.timestamp, v.violation_type, v.distance_exceeded_m, "
            "v.dwell_time_s, v.severity, v.acknowledged, v.resolved "
            "FROM violations v "
            "JOIN drivers d ON v.driver_id = d.driver_id "
            "WHERE d.depot_id = ? "
            "AND v.timestamp >= '2025-01-06' AND v.timestamp < '2025-01-13' "
            "ORDER BY v.violation_id "
            "LIMIT ? OFFSET ?",
            (depot_id, page_size, offset),
        ).fetchall()
        conn.close()

        return {
            "violations": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total_count": total,
            "has_more": offset + page_size < total,
        }

    @tool(
        description=(
            "Returns the active contract / SLA details for a customer, "
            "including SLA tier, maximum weekly violations, and penalty "
            "per violation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "integer",
                    "description": "Customer ID to look up.",
                },
            },
            "required": ["customer_id"],
        },
    )
    def get_customer_contract(self, customer_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT contract_id, customer_id, sla_tier, "
            "max_weekly_violations, penalty_per_violation, "
            "contract_start, contract_end, active "
            "FROM contracts WHERE customer_id = ? AND active = 1 "
            "ORDER BY contract_id LIMIT 1",
            (int(customer_id),),
        ).fetchone()
        conn.close()
        return dict(row) if row else {}

    @tool(
        description=(
            "Returns shift log entries for a driver during the reporting "
            "week (2025-01-06 to 2025-01-12)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "driver_id": {
                    "type": "integer",
                    "description": "Driver ID to look up.",
                },
            },
            "required": ["driver_id"],
        },
    )
    def get_driver_shift_log(self, driver_id: int) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT shift_id, driver_id, shift_date, clock_in, clock_out, "
            "vehicle_id, route_id, status "
            "FROM shift_logs "
            "WHERE driver_id = ? "
            "AND shift_date >= '2025-01-06' AND shift_date <= '2025-01-12' "
            "ORDER BY shift_date, clock_in",
            (int(driver_id),),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Ground-truth computation (used by step and verify)
    # ------------------------------------------------------------------

    def _load_workspace_configs(self):
        with open(os.path.join(self.workspace, "scoring_weights.json")) as f:
            scoring = json.load(f)
        with open(os.path.join(self.workspace, "retraining_policy.json")) as f:
            retraining = json.load(f)
        with open(os.path.join(self.workspace, "sla_tiers.yaml")) as f:
            sla = yaml.safe_load(f)
        return scoring, retraining, sla

    def _load_incident_map(self):
        """Return {violation_id: {adjustment_factor, disputed}}."""
        inc_map = {}
        for fp in sorted(glob.glob(
            os.path.join(self.workspace, "incident_context_*.csv")
        )):
            df = pd.read_csv(fp)
            for _, row in df.iterrows():
                inc_map[int(row["violation_id"])] = {
                    "adjustment_factor": float(row["adjustment_factor"]),
                    "disputed": bool(int(row["disputed"])),
                }
        return inc_map

    def _compute_ground_truth(self):
        scoring, retraining, sla = self._load_workspace_configs()
        inc_map = self._load_incident_map()

        sev_w = scoring["severity_weights"]
        default_adj = scoring["default_adjustment_factor"]
        breach_mult = scoring["sla_breach_multiplier"]
        risk_thr = scoring["risk_thresholds"]
        tier_mults = {
            t: d["violation_weight_multiplier"]
            for t, d in sla["tiers"].items()
        }
        flag_cond = retraining["flag_conditions"]
        rec_actions = retraining["recommended_actions"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        depots = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM depots ORDER BY depot_id"
            ).fetchall()
        ]
        drivers_all = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM drivers ORDER BY driver_id"
            ).fetchall()
        ]
        violations_all = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM violations "
                "WHERE timestamp >= '2025-01-06' AND timestamp < '2025-01-13' "
                "ORDER BY violation_id"
            ).fetchall()
        ]

        # cache contracts
        contract_cache = {}
        for r in conn.execute(
            "SELECT * FROM contracts WHERE active = 1"
        ).fetchall():
            contract_cache[r["customer_id"]] = dict(r)

        conn.close()

        # group drivers by depot
        drivers_by_depot = defaultdict(list)
        for d in drivers_all:
            drivers_by_depot[d["depot_id"]].append(d)

        # group violations by driver
        viols_by_driver = defaultdict(list)
        for v in violations_all:
            viols_by_driver[v["driver_id"]].append(v)

        # ---- Per-depot scorecard ----
        scorecard = []
        for depot in depots:
            did = depot["depot_id"]
            dep_drivers = drivers_by_depot.get(did, [])
            total_drivers = len(dep_drivers)
            active_drivers = sum(
                1 for d in dep_drivers if d["status"] == "active"
            )

            # violations for this depot's drivers
            dep_viols = []
            for drv in dep_drivers:
                dep_viols.extend(viols_by_driver.get(drv["driver_id"], []))

            # filter non-disputed
            nd_viols = []
            for v in dep_viols:
                inc = inc_map.get(v["violation_id"])
                if inc and inc["disputed"]:
                    continue
                nd_viols.append(v)

            total_violations = len(nd_viols)
            critical_violations = sum(
                1 for v in nd_viols if v["severity"] == "critical"
            )

            # group by customer for SLA breach check
            viols_by_cust = defaultdict(list)
            for v in nd_viols:
                viols_by_cust[v["customer_id"]].append(v)

            breached_customers = set()
            for cid, cvs in viols_by_cust.items():
                contract = contract_cache.get(cid, {})
                max_wv = contract.get("max_weekly_violations", 999)
                if len(cvs) > max_wv:
                    breached_customers.add(cid)

            sla_breach_count = len(breached_customers)

            # compute penalty
            total_penalty = 0.0
            for v in nd_viols:
                sw = sev_w.get(v["severity"], 0)
                contract = contract_cache.get(v["customer_id"], {})
                tier = contract.get("sla_tier", "bronze")
                tm = tier_mults.get(tier, 1.0)
                inc = inc_map.get(v["violation_id"])
                adj = inc["adjustment_factor"] if inc else default_adj
                pen = sw * tm * adj
                if v["customer_id"] in breached_customers:
                    pen *= breach_mult
                total_penalty += pen

            denom = max(active_drivers, 1)
            raw_score = 100.0 - total_penalty / denom
            compliance_score = round(max(0.0, raw_score), 2)

            # risk rating
            if compliance_score >= risk_thr["low"]["min_score"]:
                risk_rating = "low"
            elif compliance_score >= risk_thr["medium"]["min_score"]:
                risk_rating = "medium"
            elif compliance_score >= risk_thr["high"]["min_score"]:
                risk_rating = "high"
            else:
                risk_rating = "critical"

            scorecard.append({
                "depot_id": did,
                "depot_name": depot["name"],
                "region": depot["region"],
                "total_drivers": total_drivers,
                "active_drivers": active_drivers,
                "total_violations": total_violations,
                "critical_violations": critical_violations,
                "sla_breach_count": sla_breach_count,
                "compliance_score": compliance_score,
                "risk_rating": risk_rating,
            })

        scorecard.sort(key=lambda x: x["depot_id"])

        # ---- Flagged drivers ----
        depot_name_map = {d["depot_id"]: d["name"] for d in depots}
        flagged = []
        for drv in drivers_all:
            dvs = viols_by_driver.get(drv["driver_id"], [])
            # filter non-disputed
            nd = []
            for v in dvs:
                inc = inc_map.get(v["violation_id"])
                if inc and inc["disputed"]:
                    continue
                nd.append(v)

            violation_count = len(nd)
            ws = 0.0
            has_critical = False
            for v in nd:
                sw = sev_w.get(v["severity"], 0)
                inc = inc_map.get(v["violation_id"])
                adj = inc["adjustment_factor"] if inc else default_adj
                ws += sw * adj
                if v["severity"] == "critical":
                    has_critical = True
            ws = round(ws, 2)

            should_flag = False
            if violation_count >= flag_cond["min_violations"]:
                should_flag = True
            if ws >= flag_cond["min_weighted_severity_score"]:
                should_flag = True
            if has_critical and flag_cond["critical_violation_auto_flag"]:
                should_flag = True

            if not should_flag:
                continue

            if has_critical:
                reason = "critical_violation"
            elif ws >= flag_cond["min_weighted_severity_score"]:
                reason = "high_severity_score"
            else:
                reason = "excessive_violations"

            if ws > 30:
                action = rec_actions["weighted_score_above_30"]
            elif ws > 15:
                action = rec_actions["weighted_score_above_15"]
            else:
                action = rec_actions["default"]

            flagged.append({
                "driver_id": drv["driver_id"],
                "driver_name": f"{drv['first_name']} {drv['last_name']}",
                "depot_id": drv["depot_id"],
                "depot_name": depot_name_map.get(drv["depot_id"], ""),
                "violation_count": violation_count,
                "weighted_severity_score": ws,
                "primary_flag_reason": reason,
                "recommended_action": action,
            })

        flagged.sort(key=lambda x: (-x["weighted_severity_score"], x["driver_id"]))

        return scorecard, flagged

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

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
        gt_scorecard, gt_flagged = self._compute_ground_truth()
        criteria = {}
        total_score = 0.0
        max_score = 0.0

        # ---- 1. Scorecard file structure (15 pts) ----
        sc_path = os.path.join(self.workspace, "compliance_scorecard.csv")
        sc_cols = [
            "depot_id", "depot_name", "region", "total_drivers",
            "active_drivers", "total_violations", "critical_violations",
            "sla_breach_count", "compliance_score", "risk_rating",
        ]
        crit1_max = 15
        max_score += crit1_max
        crit1_score = 0
        crit1_reason = ""
        try:
            sc_df = pd.read_csv(sc_path)
            if list(sc_df.columns) == sc_cols:
                crit1_score = crit1_max
            else:
                missing = set(sc_cols) - set(sc_df.columns)
                extra = set(sc_df.columns) - set(sc_cols)
                if not missing:
                    crit1_score = crit1_max * 0.7
                    crit1_reason = f"Column order mismatch or extra columns: {extra}"
                else:
                    crit1_score = crit1_max * 0.3
                    crit1_reason = f"Missing columns: {missing}"
        except Exception as e:
            crit1_reason = f"Cannot read file: {e}"
        total_score += crit1_score
        criteria["scorecard_structure"] = {
            "passed": crit1_score == crit1_max,
            "score": round(crit1_score, 2),
            "max_score": crit1_max,
            "reason": crit1_reason or None,
        }

        # ---- 2. Scorecard depot completeness (15 pts) ----
        crit2_max = 15
        max_score += crit2_max
        crit2_score = 0
        crit2_reason = ""
        try:
            sc_df = pd.read_csv(sc_path)
            gt_ids = set(r["depot_id"] for r in gt_scorecard)
            pred_ids = set(int(x) for x in sc_df["depot_id"].tolist())
            if gt_ids == pred_ids:
                crit2_score = crit2_max
            else:
                overlap = len(gt_ids & pred_ids)
                crit2_score = crit2_max * overlap / max(len(gt_ids), 1)
                crit2_reason = (
                    f"Expected {len(gt_ids)} depots, got {len(pred_ids)}; "
                    f"overlap {overlap}"
                )
        except Exception as e:
            crit2_reason = f"Cannot read file: {e}"
        total_score += crit2_score
        criteria["scorecard_completeness"] = {
            "passed": crit2_score == crit2_max,
            "score": round(crit2_score, 2),
            "max_score": crit2_max,
            "reason": crit2_reason or None,
        }

        # ---- 3. Scorecard values accuracy (25 pts) ----
        crit3_max = 25
        max_score += crit3_max
        crit3_score = 0
        crit3_reason = ""
        try:
            sc_df = pd.read_csv(sc_path)
            gt_map = {r["depot_id"]: r for r in gt_scorecard}
            per_depot = crit3_max / max(len(gt_map), 1)
            details = []
            for _, row in sc_df.iterrows():
                did = int(row["depot_id"])
                gt = gt_map.get(did)
                if not gt:
                    continue
                ok = True
                # check numeric fields
                for field in [
                    "total_violations", "critical_violations",
                    "sla_breach_count", "active_drivers", "total_drivers",
                ]:
                    if int(row[field]) != gt[field]:
                        ok = False
                        details.append(
                            f"depot {did} {field}: "
                            f"expected {gt[field]}, got {int(row[field])}"
                        )
                # compliance score tolerance 0.05
                if abs(float(row["compliance_score"]) - gt["compliance_score"]) > 0.05:
                    ok = False
                    details.append(
                        f"depot {did} compliance_score: "
                        f"expected {gt['compliance_score']}, "
                        f"got {float(row['compliance_score'])}"
                    )
                # risk rating exact
                if str(row["risk_rating"]).strip().lower() != gt["risk_rating"]:
                    ok = False
                    details.append(
                        f"depot {did} risk_rating: "
                        f"expected {gt['risk_rating']}, got {row['risk_rating']}"
                    )
                if ok:
                    crit3_score += per_depot
            if details:
                crit3_reason = "; ".join(details[:10])
        except Exception as e:
            crit3_reason = f"Cannot evaluate: {e}"
        total_score += crit3_score
        criteria["scorecard_accuracy"] = {
            "passed": abs(crit3_score - crit3_max) < 0.01,
            "score": round(crit3_score, 2),
            "max_score": crit3_max,
            "reason": crit3_reason or None,
        }

        # ---- 4. Flagged drivers file structure (10 pts) ----
        fl_path = os.path.join(self.workspace, "flagged_drivers_report.csv")
        fl_cols = [
            "driver_id", "driver_name", "depot_id", "depot_name",
            "violation_count", "weighted_severity_score",
            "primary_flag_reason", "recommended_action",
        ]
        crit4_max = 10
        max_score += crit4_max
        crit4_score = 0
        crit4_reason = ""
        try:
            fl_df = pd.read_csv(fl_path)
            if list(fl_df.columns) == fl_cols:
                crit4_score = crit4_max
            else:
                missing = set(fl_cols) - set(fl_df.columns)
                if not missing:
                    crit4_score = crit4_max * 0.7
                    crit4_reason = "Column order mismatch"
                else:
                    crit4_score = crit4_max * 0.3
                    crit4_reason = f"Missing columns: {missing}"
        except Exception as e:
            crit4_reason = f"Cannot read file: {e}"
        total_score += crit4_score
        criteria["flagged_structure"] = {
            "passed": crit4_score == crit4_max,
            "score": round(crit4_score, 2),
            "max_score": crit4_max,
            "reason": crit4_reason or None,
        }

        # ---- 5. Flagged drivers accuracy (25 pts) ----
        crit5_max = 25
        max_score += crit5_max
        crit5_score = 0
        crit5_reason = ""
        try:
            fl_df = pd.read_csv(fl_path)
            gt_ids = set(r["driver_id"] for r in gt_flagged)
            pred_ids = set(int(x) for x in fl_df["driver_id"].tolist())

            # 15 pts for correct set
            if gt_ids == pred_ids:
                set_score = 15.0
            else:
                correct = len(gt_ids & pred_ids)
                total_relevant = max(len(gt_ids | pred_ids), 1)
                set_score = 15.0 * correct / total_relevant
                crit5_reason = (
                    f"Expected {len(gt_ids)} flagged drivers, "
                    f"got {len(pred_ids)}; correct {correct}"
                )
            crit5_score += set_score

            # 10 pts for detail accuracy of correctly identified drivers
            gt_map = {r["driver_id"]: r for r in gt_flagged}
            correct_ids = gt_ids & pred_ids
            if correct_ids:
                per_d = 10.0 / len(correct_ids)
                detail_errs = []
                for _, row in fl_df.iterrows():
                    did = int(row["driver_id"])
                    if did not in correct_ids:
                        continue
                    gt = gt_map[did]
                    ok = True
                    if abs(
                        float(row["weighted_severity_score"])
                        - gt["weighted_severity_score"]
                    ) > 0.05:
                        ok = False
                        detail_errs.append(
                            f"driver {did} ws: "
                            f"expected {gt['weighted_severity_score']}, "
                            f"got {float(row['weighted_severity_score'])}"
                        )
                    if (
                        str(row["primary_flag_reason"]).strip()
                        != gt["primary_flag_reason"]
                    ):
                        ok = False
                        detail_errs.append(
                            f"driver {did} reason mismatch"
                        )
                    if (
                        str(row["recommended_action"]).strip()
                        != gt["recommended_action"]
                    ):
                        ok = False
                        detail_errs.append(
                            f"driver {did} action mismatch"
                        )
                    if ok:
                        crit5_score += per_d
                if detail_errs:
                    crit5_reason = (
                        (crit5_reason + "; " if crit5_reason else "")
                        + "; ".join(detail_errs[:10])
                    )
        except Exception as e:
            crit5_reason = f"Cannot evaluate: {e}"
        total_score += crit5_score
        criteria["flagged_accuracy"] = {
            "passed": abs(crit5_score - crit5_max) < 0.01,
            "score": round(crit5_score, 2),
            "max_score": crit5_max,
            "reason": crit5_reason or None,
        }

        # ---- 6. Response summary accuracy (10 pts) ----
        crit6_max = 10
        max_score += crit6_max
        crit6_score = 0
        crit6_reason = ""
        try:
            action_lower = action.lower() if action else ""

            # overall fleet compliance score
            fleet_avg = round(
                sum(s["compliance_score"] for s in gt_scorecard)
                / max(len(gt_scorecard), 1),
                2,
            )
            # check if the number appears
            fleet_str = f"{fleet_avg:.2f}"
            # also accept one-decimal variant
            fleet_str1 = f"{fleet_avg:.1f}"
            if fleet_str in action or fleet_str1 in action:
                crit6_score += 4
            else:
                crit6_reason += f"Fleet avg {fleet_str} not found in response. "

            # risk distribution
            risk_dist = defaultdict(int)
            for s in gt_scorecard:
                risk_dist[s["risk_rating"]] += 1
            risk_ok = True
            for rating, count in risk_dist.items():
                if str(count) not in action:
                    risk_ok = False
            if risk_ok:
                crit6_score += 3
            else:
                crit6_reason += (
                    f"Risk distribution {dict(risk_dist)} not fully in response. "
                )

            # total flagged
            total_flagged = len(gt_flagged)
            if str(total_flagged) in action:
                crit6_score += 3
            else:
                crit6_reason += (
                    f"Total flagged count {total_flagged} not in response. "
                )
        except Exception as e:
            crit6_reason = f"Cannot evaluate response: {e}"
        total_score += crit6_score
        criteria["response_summary"] = {
            "passed": crit6_score == crit6_max,
            "score": round(crit6_score, 2),
            "max_score": crit6_max,
            "reason": crit6_reason.strip() or None,
        }

        # ---- Aggregate ----
        info = {
            "eval_criteria": criteria,
            "total_score": round(total_score, 2),
            "max_score": round(max_score, 2),
        }
        reward = round(total_score / max(max_score, 1), 4)
        return reward, info

    # ------------------------------------------------------------------
    # Verification
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
        import csv as csv_mod

        tool_calls = 0

        # ---- Load workspace configs ----
        with open(os.path.join(self.workspace, "scoring_weights.json")) as f:
            scoring = json.load(f)
        with open(os.path.join(self.workspace, "retraining_policy.json")) as f:
            retraining = json.load(f)
        with open(os.path.join(self.workspace, "sla_tiers.yaml")) as f:
            sla = yaml.safe_load(f)

        sev_w = scoring["severity_weights"]
        default_adj = scoring["default_adjustment_factor"]
        breach_mult = scoring["sla_breach_multiplier"]
        risk_thr = scoring["risk_thresholds"]
        tier_mults = {
            t: d["violation_weight_multiplier"]
            for t, d in sla["tiers"].items()
        }
        flag_cond = retraining["flag_conditions"]
        rec_actions = retraining["recommended_actions"]

        # ---- Load incident context ----
        inc_map = {}
        for fp in sorted(glob.glob(
            os.path.join(self.workspace, "incident_context_*.csv")
        )):
            df = pd.read_csv(fp)
            for _, row in df.iterrows():
                inc_map[int(row["violation_id"])] = {
                    "adjustment_factor": float(row["adjustment_factor"]),
                    "disputed": bool(int(row["disputed"])),
                }

        # ---- Tool calls: gather data ----
        depots = self.tools["list_depots"]()
        tool_calls += 1

        all_drivers = {}          # driver_id -> driver dict
        depot_drivers = {}        # depot_id -> [driver dicts]
        depot_violations = {}     # depot_id -> [violation dicts]
        contract_cache = {}       # customer_id -> contract dict

        for depot in depots:
            did = depot["depot_id"]

            drivers = self.tools["get_depot_drivers"](depot_id=did)
            tool_calls += 1
            depot_drivers[did] = drivers
            for d in drivers:
                all_drivers[d["driver_id"]] = d

            # paginated violations
            all_viols = []
            page = 1
            while True:
                result = self.tools["query_violations"](
                    depot_id=did, page=page, page_size=20,
                )
                tool_calls += 1
                all_viols.extend(result["violations"])
                if not result["has_more"]:
                    break
                page += 1
            depot_violations[did] = all_viols

            # fetch contracts for unique customers
            cust_ids = set(v["customer_id"] for v in all_viols)
            for cid in cust_ids:
                if cid not in contract_cache:
                    contract_cache[cid] = self.tools["get_customer_contract"](
                        customer_id=cid
                    )
                    tool_calls += 1

        # ---- Compute scorecard ----
        scorecard_rows = []
        for depot in depots:
            did = depot["depot_id"]
            drivers = depot_drivers.get(did, [])
            total_drivers = len(drivers)
            active_drivers = sum(
                1 for d in drivers if d["status"] == "active"
            )

            viols = depot_violations.get(did, [])
            # filter non-disputed
            nd_viols = []
            for v in viols:
                inc = inc_map.get(v["violation_id"])
                if inc and inc["disputed"]:
                    continue
                nd_viols.append(v)

            total_violations = len(nd_viols)
            critical_violations = sum(
                1 for v in nd_viols if v["severity"] == "critical"
            )

            # SLA breach
            viols_by_cust = defaultdict(list)
            for v in nd_viols:
                viols_by_cust[v["customer_id"]].append(v)

            breached = set()
            for cid, cvs in viols_by_cust.items():
                contract = contract_cache.get(cid, {})
                max_wv = contract.get("max_weekly_violations", 999)
                if len(cvs) > max_wv:
                    breached.add(cid)

            sla_breach_count = len(breached)

            # penalty
            total_penalty = 0.0
            for v in nd_viols:
                sw = sev_w.get(v["severity"], 0)
                contract = contract_cache.get(v["customer_id"], {})
                tier = contract.get("sla_tier", "bronze")
                tm = tier_mults.get(tier, 1.0)
                inc = inc_map.get(v["violation_id"])
                adj = inc["adjustment_factor"] if inc else default_adj
                pen = sw * tm * adj
                if v["customer_id"] in breached:
                    pen *= breach_mult
                total_penalty += pen

            denom = max(active_drivers, 1)
            compliance_score = round(max(0.0, 100.0 - total_penalty / denom), 2)

            if compliance_score >= risk_thr["low"]["min_score"]:
                risk_rating = "low"
            elif compliance_score >= risk_thr["medium"]["min_score"]:
                risk_rating = "medium"
            elif compliance_score >= risk_thr["high"]["min_score"]:
                risk_rating = "high"
            else:
                risk_rating = "critical"

            scorecard_rows.append({
                "depot_id": did,
                "depot_name": depot["name"],
                "region": depot["region"],
                "total_drivers": total_drivers,
                "active_drivers": active_drivers,
                "total_violations": total_violations,
                "critical_violations": critical_violations,
                "sla_breach_count": sla_breach_count,
                "compliance_score": compliance_score,
                "risk_rating": risk_rating,
            })

        scorecard_rows.sort(key=lambda x: x["depot_id"])

        # ---- Compute flagged drivers ----
        depot_name_map = {d["depot_id"]: d["name"] for d in depots}

        # group violations by driver across all depots
        viols_by_driver = defaultdict(list)
        for did, vs in depot_violations.items():
            for v in vs:
                viols_by_driver[v["driver_id"]].append(v)

        flagged_rows = []
        for drv_id, drv in all_drivers.items():
            dvs = viols_by_driver.get(drv_id, [])
            nd = []
            for v in dvs:
                inc = inc_map.get(v["violation_id"])
                if inc and inc["disputed"]:
                    continue
                nd.append(v)

            violation_count = len(nd)
            ws = 0.0
            has_critical = False
            for v in nd:
                sw = sev_w.get(v["severity"], 0)
                inc = inc_map.get(v["violation_id"])
                adj = inc["adjustment_factor"] if inc else default_adj
                ws += sw * adj
                if v["severity"] == "critical":
                    has_critical = True
            ws = round(ws, 2)

            should_flag = False
            if violation_count >= flag_cond["min_violations"]:
                should_flag = True
            if ws >= flag_cond["min_weighted_severity_score"]:
                should_flag = True
            if has_critical and flag_cond["critical_violation_auto_flag"]:
                should_flag = True

            if not should_flag:
                continue

            if has_critical:
                reason = "critical_violation"
            elif ws >= flag_cond["min_weighted_severity_score"]:
                reason = "high_severity_score"
            else:
                reason = "excessive_violations"

            if ws > 30:
                act = rec_actions["weighted_score_above_30"]
            elif ws > 15:
                act = rec_actions["weighted_score_above_15"]
            else:
                act = rec_actions["default"]

            flagged_rows.append({
                "driver_id": drv_id,
                "driver_name": f"{drv['first_name']} {drv['last_name']}",
                "depot_id": drv["depot_id"],
                "depot_name": depot_name_map.get(drv["depot_id"], ""),
                "violation_count": violation_count,
                "weighted_severity_score": ws,
                "primary_flag_reason": reason,
                "recommended_action": act,
            })

        flagged_rows.sort(
            key=lambda x: (-x["weighted_severity_score"], x["driver_id"])
        )

        # ---- Write deliverables ----
        sc_path = os.path.join(self.workspace, "compliance_scorecard.csv")
        sc_cols = [
            "depot_id", "depot_name", "region", "total_drivers",
            "active_drivers", "total_violations", "critical_violations",
            "sla_breach_count", "compliance_score", "risk_rating",
        ]
        with open(sc_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=sc_cols)
            writer.writeheader()
            writer.writerows(scorecard_rows)

        fl_path = os.path.join(self.workspace, "flagged_drivers_report.csv")
        fl_cols = [
            "driver_id", "driver_name", "depot_id", "depot_name",
            "violation_count", "weighted_severity_score",
            "primary_flag_reason", "recommended_action",
        ]
        with open(fl_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=fl_cols)
            writer.writeheader()
            writer.writerows(flagged_rows)

        # ---- Build response ----
        fleet_avg = round(
            sum(r["compliance_score"] for r in scorecard_rows)
            / max(len(scorecard_rows), 1),
            2,
        )
        risk_dist = defaultdict(int)
        for r in scorecard_rows:
            risk_dist[r["risk_rating"]] += 1

        total_flagged = len(flagged_rows)

        action = (
            f"Overall fleet compliance score: {fleet_avg:.2f}. "
            f"Depot risk distribution: "
            + ", ".join(
                f"{rating} = {count}"
                for rating, count in sorted(risk_dist.items())
            )
            + f". Total drivers flagged for retraining: {total_flagged}."
        )

        print(f"verify: {tool_calls} tool calls made")
        return self.step(action)
