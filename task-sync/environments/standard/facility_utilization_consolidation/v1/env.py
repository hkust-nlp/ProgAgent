#!/usr/bin/env python3
"""Task environment for public facility consolidation analysis."""

import csv
import glob
import json
import math
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import yaml


# ---------------------------------------------------------------------------
# Tool decorator
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
    # TOOL METHODS
    # ===================================================================

    @tool(
        description=(
            "Lists all public facilities with basic information. "
            "Returns a paginated list of facility summaries including "
            "facility_id, name, type, zone, and capacity."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed, default 1)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of facilities per page (default 10, max 50)",
                },
            },
            "required": [],
        },
    )
    def list_facilities(self, page: int = 1, page_size: int = 10) -> dict:
        page_size = min(page_size, 50)
        offset = (max(1, page) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM facilities")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT facility_id, name, type, zone, capacity "
            "FROM facilities ORDER BY facility_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total_facilities": total,
            "total_pages": math.ceil(total / page_size),
            "facilities": rows,
        }

    @tool(
        description=(
            "Retrieves detailed information for a single facility, including "
            "square footage, year built, address, and other attributes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "Facility identifier, e.g. 'FAC-0001'",
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_facility_details(self, facility_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM facilities WHERE facility_id = ?", (facility_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Facility '{facility_id}' not found"}
        return dict(row)

    @tool(
        description=(
            "Retrieves quarterly utility billing records for a facility. "
            "Optionally filter by billing quarter."
        ),
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "Facility identifier",
                },
                "billing_quarter": {
                    "type": "string",
                    "description": "Optional quarter filter, e.g. 'Q1_2025'",
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_utility_bills(self, facility_id: str, billing_quarter: str = None) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if billing_quarter:
            cur.execute(
                "SELECT * FROM utility_bills WHERE facility_id = ? AND billing_quarter = ? "
                "ORDER BY billing_quarter, utility_type",
                (facility_id, billing_quarter),
            )
        else:
            cur.execute(
                "SELECT * FROM utility_bills WHERE facility_id = ? "
                "ORDER BY billing_quarter, utility_type",
                (facility_id,),
            )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @tool(
        description=(
            "Retrieves maintenance log entries for a facility. "
            "Optionally filter by maintenance status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "Facility identifier",
                },
                "status": {
                    "type": "string",
                    "enum": ["completed", "scheduled", "deferred", "in_progress"],
                    "description": "Optional status filter",
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_maintenance_logs(self, facility_id: str, status: str = None) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if status:
            cur.execute(
                "SELECT * FROM maintenance_logs WHERE facility_id = ? AND status = ? "
                "ORDER BY scheduled_date",
                (facility_id, status),
            )
        else:
            cur.execute(
                "SELECT * FROM maintenance_logs WHERE facility_id = ? "
                "ORDER BY scheduled_date",
                (facility_id,),
            )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @tool(
        description=(
            "Retrieves program attendance session records for a facility. "
            "Results are paginated."
        ),
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "Facility identifier",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return (default 20)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip (default 0)",
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_program_attendance(
        self, facility_id: str, limit: int = 20, offset: int = 0
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM program_attendance WHERE facility_id = ?",
            (facility_id,),
        )
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT * FROM program_attendance WHERE facility_id = ? "
            "ORDER BY session_date LIMIT ? OFFSET ?",
            (facility_id, limit, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"total_records": total, "offset": offset, "limit": limit, "records": rows}

    @tool(
        description=(
            "Retrieves capital improvement requests for a facility. "
            "Optionally filter by status or fiscal year."
        ),
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "Facility identifier",
                },
                "status": {
                    "type": "string",
                    "enum": ["approved", "pending", "denied"],
                    "description": "Optional status filter",
                },
                "fiscal_year": {
                    "type": "integer",
                    "description": "Optional fiscal year filter",
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_capital_requests(
        self, facility_id: str, status: str = None, fiscal_year: int = None
    ) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        query = "SELECT * FROM capital_improvement_requests WHERE facility_id = ?"
        params: list = [facility_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        if fiscal_year:
            query += " AND fiscal_year = ?"
            params.append(fiscal_year)
        query += " ORDER BY fiscal_year, request_id"
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    # ===================================================================
    # GROUND TRUTH COMPUTATION (shared by step and verify-check)
    # ===================================================================

    def _compute_ground_truth(self) -> pd.DataFrame:
        """Compute the full ground-truth report for all flagged facilities."""

        # --- 1. Load policy ---
        with open(os.path.join(self.workspace, "consolidation_policy.yaml")) as fp:
            policy = yaml.safe_load(fp)
        occ_threshold = policy["occupancy_threshold"]
        weights = policy["scoring_weights"]
        benchmarks = policy["benchmarks"]
        rec_thresh = policy["recommendation_thresholds"]

        # --- 2. Load annual budgets ---
        with open(os.path.join(self.workspace, "annual_budgets.json")) as fp:
            budgets = json.load(fp)

        # --- 3. Load occupancy surveys ---
        survey_files = sorted(glob.glob(
            os.path.join(self.workspace, "occupancy_survey_*.csv")
        ))
        all_surveys = pd.concat(
            [pd.read_csv(sf) for sf in survey_files], ignore_index=True
        )
        occ_avg = (
            all_surveys.groupby("facility_id")["avg_daily_visitors"]
            .mean()
            .to_dict()
        )

        # --- 4. Load facility data from DB ---
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        facilities = {
            r["facility_id"]: dict(r)
            for r in conn.execute("SELECT * FROM facilities ORDER BY facility_id")
        }

        # --- 5. Compute occupancy rates & flag ---
        flagged_ids = []
        occ_rates = {}
        for fid, fac in facilities.items():
            avg_vis = occ_avg.get(fid, 0)
            rate = avg_vis / fac["capacity"] if fac["capacity"] else 0
            occ_rates[fid] = rate
            if rate < occ_threshold:
                flagged_ids.append(fid)

        # --- 6. Compute metrics for flagged facilities ---
        rows = []
        for fid in sorted(flagged_ids):
            fac = facilities[fid]

            # Utility cost
            cur = conn.execute(
                "SELECT SUM(amount) FROM utility_bills WHERE facility_id = ?", (fid,)
            )
            annual_utility = cur.fetchone()[0] or 0.0

            # Maintenance cost
            cur = conn.execute(
                "SELECT SUM(actual_cost) FROM maintenance_logs "
                "WHERE facility_id = ? AND status = 'completed'",
                (fid,),
            )
            maint_completed = cur.fetchone()[0] or 0.0
            cur = conn.execute(
                "SELECT SUM(estimated_cost) FROM maintenance_logs "
                "WHERE facility_id = ? AND status != 'completed'",
                (fid,),
            )
            maint_other = cur.fetchone()[0] or 0.0
            annual_maint = maint_completed + maint_other

            # Pending capital
            cur = conn.execute(
                "SELECT SUM(requested_amount) FROM capital_improvement_requests "
                "WHERE facility_id = ? AND status = 'pending'",
                (fid,),
            )
            pending_cap = cur.fetchone()[0] or 0.0

            # Program attendance rate
            cur = conn.execute(
                "SELECT attended, max_capacity FROM program_attendance "
                "WHERE facility_id = ?",
                (fid,),
            )
            att_rows = cur.fetchall()
            if att_rows:
                ratios = [r[0] / r[1] for r in att_rows if r[1] > 0]
                avg_att_rate = float(np.mean(ratios)) if ratios else 0.0
            else:
                avg_att_rate = 0.0

            sqft = fac["square_footage"]
            budget = budgets.get(fid, 1.0)
            cost_per_sqft = annual_utility / sqft if sqft else 0.0
            maint_burden_pct = (annual_maint / budget) * 100 if budget else 0.0
            occ_rate = occ_rates[fid]
            occ_pct = occ_rate * 100

            # Component scores (clamped 0-100)
            def clamp(v):
                return max(0.0, min(100.0, v))

            comp_occ = clamp(((occ_threshold - occ_rate) / occ_threshold) * 100)
            comp_util = clamp(
                (cost_per_sqft / benchmarks["utility_cost_per_sqft_annual"]) * 100
            )
            comp_maint = clamp(maint_burden_pct)
            comp_cap = clamp(
                (pending_cap / benchmarks["capital_request_threshold"]) * 100
            )
            comp_prog = clamp(
                (
                    (benchmarks["program_attendance_threshold"] - avg_att_rate)
                    / benchmarks["program_attendance_threshold"]
                )
                * 100
            )

            score = (
                weights["occupancy"] * comp_occ
                + weights["utility_cost_efficiency"] * comp_util
                + weights["maintenance_burden"] * comp_maint
                + weights["capital_exposure"] * comp_cap
                + weights["program_utilization"] * comp_prog
            )
            score = round(score, 1)

            if score >= rec_thresh["closure"]:
                recommendation = "closure"
            elif score >= rec_thresh["shared_space"]:
                recommendation = "shared_space"
            else:
                recommendation = "retain_with_review"

            rows.append({
                "facility_id": fid,
                "facility_name": fac["name"],
                "zone": fac["zone"],
                "facility_type": fac["type"],
                "capacity": fac["capacity"],
                "square_footage": sqft,
                "avg_occupancy_pct": round(occ_pct, 2),
                "annual_utility_cost": round(annual_utility, 2),
                "annual_maintenance_cost": round(annual_maint, 2),
                "pending_capital_amount": round(pending_cap, 2),
                "cost_per_sqft": round(cost_per_sqft, 2),
                "maintenance_burden_pct": round(maint_burden_pct, 2),
                "program_attendance_pct": round(avg_att_rate * 100, 2),
                "consolidation_score": score,
                "recommendation": recommendation,
            })

        conn.close()

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values(
                ["consolidation_score", "facility_id"],
                ascending=[False, True],
            ).reset_index(drop=True)
        return df

    # ===================================================================
    # STEP
    # ===================================================================

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
        criteria: Dict[str, Dict[str, Any]] = {}

        # ------------------------------------------------------------------
        # 1. Report existence & structure  (10 pts)
        # ------------------------------------------------------------------
        report_path = os.path.join(self.workspace, "consolidation_report.csv")
        expected_cols = [
            "facility_id", "facility_name", "zone", "facility_type",
            "capacity", "square_footage", "avg_occupancy_pct",
            "annual_utility_cost", "annual_maintenance_cost",
            "pending_capital_amount", "cost_per_sqft",
            "maintenance_burden_pct", "program_attendance_pct",
            "consolidation_score", "recommendation",
        ]
        try:
            agent_df = pd.read_csv(report_path)
            cols_match = list(agent_df.columns) == expected_cols
            row_count_match = len(agent_df) == len(gt)
            struct_ok = cols_match and row_count_match
            reason = ""
            if not cols_match:
                reason += f"Column mismatch: got {list(agent_df.columns)}. "
            if not row_count_match:
                reason += f"Row count: got {len(agent_df)}, expected {len(gt)}. "
        except Exception as e:
            agent_df = pd.DataFrame()
            struct_ok = False
            reason = str(e)

        criteria["report_structure"] = {
            "passed": struct_ok,
            "score": 10 if struct_ok else 0,
            "max_score": 10,
            "reason": reason if not struct_ok else "",
        }

        # Early-out helpers
        def _empty_crit(name, pts, reason="Report missing or malformed"):
            return {"passed": False, "score": 0, "max_score": pts, "reason": reason}

        if agent_df.empty or not cols_match:
            for name, pts in [
                ("flagged_facilities", 20),
                ("occupancy_accuracy", 15),
                ("cost_metrics", 15),
                ("maint_capital_metrics", 10),
                ("consolidation_scores", 15),
                ("recommendations_and_sort", 15),
            ]:
                criteria[name] = _empty_crit(name, pts)
            criteria["response_summary"] = _empty_crit("response_summary", 10)
            total = sum(c["score"] for c in criteria.values())
            max_total = sum(c["max_score"] for c in criteria.values())
            return total / max_total, {
                "eval_criteria": criteria,
                "total_score": total,
                "max_score": max_total,
            }

        # Align on facility_id
        agent_df = agent_df.copy()
        agent_df["facility_id"] = agent_df["facility_id"].astype(str).str.strip()
        gt_ids = set(gt["facility_id"].tolist())
        agent_ids = set(agent_df["facility_id"].tolist())

        # ------------------------------------------------------------------
        # 2. Correct flagged facilities  (20 pts)
        # ------------------------------------------------------------------
        ids_match = gt_ids == agent_ids
        criteria["flagged_facilities"] = {
            "passed": ids_match,
            "score": 20 if ids_match else max(0, 20 - 4 * len(gt_ids.symmetric_difference(agent_ids))),
            "max_score": 20,
            "reason": "" if ids_match else f"Missing: {gt_ids - agent_ids}, Extra: {agent_ids - gt_ids}",
        }

        # Merge for per-row comparison
        merged = gt.merge(agent_df, on="facility_id", suffixes=("_gt", "_agent"), how="inner")

        # ------------------------------------------------------------------
        # 3. Occupancy accuracy  (15 pts)
        # ------------------------------------------------------------------
        if len(merged) > 0:
            occ_ok = all(
                abs(row["avg_occupancy_pct_gt"] - row["avg_occupancy_pct_agent"]) <= 1.0
                for _, row in merged.iterrows()
            )
            n_correct = sum(
                1
                for _, row in merged.iterrows()
                if abs(row["avg_occupancy_pct_gt"] - row["avg_occupancy_pct_agent"]) <= 1.0
            )
            occ_score = round(15 * n_correct / len(merged))
        else:
            occ_ok = False
            occ_score = 0
        criteria["occupancy_accuracy"] = {
            "passed": occ_ok,
            "score": occ_score,
            "max_score": 15,
        }

        # ------------------------------------------------------------------
        # 4. Cost metrics: utility & cost_per_sqft  (15 pts)
        # ------------------------------------------------------------------
        if len(merged) > 0:
            n_util = sum(
                1
                for _, r in merged.iterrows()
                if abs(r["annual_utility_cost_gt"] - r["annual_utility_cost_agent"]) <= 5.0
            )
            n_cpsf = sum(
                1
                for _, r in merged.iterrows()
                if abs(r["cost_per_sqft_gt"] - r["cost_per_sqft_agent"]) <= 0.5
            )
            cost_score = round(15 * (n_util + n_cpsf) / (2 * len(merged)))
            cost_ok = cost_score == 15
        else:
            cost_ok = False
            cost_score = 0
        criteria["cost_metrics"] = {
            "passed": cost_ok,
            "score": cost_score,
            "max_score": 15,
        }

        # ------------------------------------------------------------------
        # 5. Maintenance & capital metrics  (10 pts)
        # ------------------------------------------------------------------
        if len(merged) > 0:
            n_maint = sum(
                1
                for _, r in merged.iterrows()
                if abs(r["annual_maintenance_cost_gt"] - r["annual_maintenance_cost_agent"]) <= 5.0
            )
            n_cap = sum(
                1
                for _, r in merged.iterrows()
                if abs(r["pending_capital_amount_gt"] - r["pending_capital_amount_agent"]) <= 5.0
            )
            mc_score = round(10 * (n_maint + n_cap) / (2 * len(merged)))
            mc_ok = mc_score == 10
        else:
            mc_ok = False
            mc_score = 0
        criteria["maint_capital_metrics"] = {
            "passed": mc_ok,
            "score": mc_score,
            "max_score": 10,
        }

        # ------------------------------------------------------------------
        # 6. Consolidation scores  (15 pts)
        # ------------------------------------------------------------------
        if len(merged) > 0:
            n_score = sum(
                1
                for _, r in merged.iterrows()
                if abs(r["consolidation_score_gt"] - r["consolidation_score_agent"]) <= 1.5
            )
            cs_score = round(15 * n_score / len(merged))
            cs_ok = cs_score == 15
        else:
            cs_ok = False
            cs_score = 0
        criteria["consolidation_scores"] = {
            "passed": cs_ok,
            "score": cs_score,
            "max_score": 15,
        }

        # ------------------------------------------------------------------
        # 7. Recommendations & sort order  (15 pts)
        # ------------------------------------------------------------------
        if len(merged) > 0:
            n_rec = sum(
                1
                for _, r in merged.iterrows()
                if str(r.get("recommendation_gt", "")).strip()
                == str(r.get("recommendation_agent", "")).strip()
            )
            rec_pts = round(10 * n_rec / len(merged))
        else:
            rec_pts = 0

        # Check sort order in agent CSV
        if len(agent_df) >= 2:
            sorted_ok = True
            for i in range(len(agent_df) - 1):
                s1 = float(agent_df.iloc[i]["consolidation_score"])
                s2 = float(agent_df.iloc[i + 1]["consolidation_score"])
                if s1 < s2:
                    sorted_ok = False
                    break
                if s1 == s2:
                    if str(agent_df.iloc[i]["facility_id"]) > str(agent_df.iloc[i + 1]["facility_id"]):
                        sorted_ok = False
                        break
            sort_pts = 5 if sorted_ok else 0
        else:
            sort_pts = 5  # trivially sorted

        rs_ok = rec_pts == 10 and sort_pts == 5
        criteria["recommendations_and_sort"] = {
            "passed": rs_ok,
            "score": rec_pts + sort_pts,
            "max_score": 15,
        }

        # ------------------------------------------------------------------
        # 8. Response summary  (10 pts — mentions correct count + facility IDs)
        # ------------------------------------------------------------------
        action_lower = action.lower() if action else ""
        expected_count = len(gt)
        count_mentioned = str(expected_count) in action if action else False
        ids_mentioned = sum(
            1 for fid in gt["facility_id"] if fid.lower() in action_lower
        )
        frac_ids = ids_mentioned / max(1, expected_count)
        resp_pts = 0
        if count_mentioned:
            resp_pts += 4
        resp_pts += round(6 * frac_ids)
        resp_ok = resp_pts == 10
        criteria["response_summary"] = {
            "passed": resp_ok,
            "score": resp_pts,
            "max_score": 10,
        }

        # ------------------------------------------------------------------
        total = sum(c["score"] for c in criteria.values())
        max_total = sum(c["max_score"] for c in criteria.values())
        return total / max_total, {
            "eval_criteria": criteria,
            "total_score": total,
            "max_score": max_total,
        }

    # ===================================================================
    # VERIFY
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

        # ---- 1. Load policy config ----
        with open(os.path.join(self.workspace, "consolidation_policy.yaml")) as fp:
            policy = yaml.safe_load(fp)
        occ_threshold = policy["occupancy_threshold"]
        weights = policy["scoring_weights"]
        benchmarks = policy["benchmarks"]
        rec_thresh = policy["recommendation_thresholds"]

        # ---- 2. Load annual budgets ----
        with open(os.path.join(self.workspace, "annual_budgets.json")) as fp:
            budgets = json.load(fp)

        # ---- 3. Load occupancy surveys ----
        survey_files = sorted(glob.glob(
            os.path.join(self.workspace, "occupancy_survey_*.csv")
        ))
        all_surveys = pd.concat(
            [pd.read_csv(sf) for sf in survey_files], ignore_index=True
        )
        occ_mean = (
            all_surveys.groupby("facility_id")["avg_daily_visitors"]
            .mean()
            .to_dict()
        )

        # ---- 4. List all facilities via tools (paginated) ----
        facility_map = {}  # fid -> {name, type, zone, capacity}
        page = 1
        while True:
            result = self.tools["list_facilities"](page=page, page_size=10)
            for f in result["facilities"]:
                facility_map[f["facility_id"]] = f
            if page >= result["total_pages"]:
                break
            page += 1

        # ---- 5. Compute occupancy and flag ----
        flagged_ids = []
        occ_rates = {}
        for fid, finfo in facility_map.items():
            avg_vis = occ_mean.get(fid, 0)
            rate = avg_vis / finfo["capacity"] if finfo["capacity"] else 0
            occ_rates[fid] = rate
            if rate < occ_threshold:
                flagged_ids.append(fid)

        # ---- 6. Gather detailed data for flagged facilities ----
        report_rows = []
        for fid in sorted(flagged_ids):
            # Facility details (square_footage, etc.)
            details = self.tools["get_facility_details"](facility_id=fid)

            # Utility bills
            bills = self.tools["get_utility_bills"](facility_id=fid)
            annual_utility = sum(b["amount"] for b in bills)

            # Maintenance logs
            logs = self.tools["get_maintenance_logs"](facility_id=fid)
            annual_maint = 0.0
            for lg in logs:
                if lg["status"] == "completed":
                    annual_maint += lg["actual_cost"] or 0.0
                else:
                    annual_maint += lg["estimated_cost"] or 0.0

            # Capital requests
            cap_reqs = self.tools["get_capital_requests"](facility_id=fid)
            pending_cap = sum(
                cr["requested_amount"] for cr in cap_reqs if cr["status"] == "pending"
            )

            # Program attendance (paginated)
            att_ratios = []
            offset = 0
            while True:
                att_result = self.tools["get_program_attendance"](
                    facility_id=fid, limit=20, offset=offset
                )
                for rec in att_result["records"]:
                    if rec["max_capacity"] > 0:
                        att_ratios.append(rec["attended"] / rec["max_capacity"])
                if offset + att_result["limit"] >= att_result["total_records"]:
                    break
                offset += att_result["limit"]

            avg_att_rate = float(np.mean(att_ratios)) if att_ratios else 0.0

            sqft = details["square_footage"]
            budget = budgets.get(fid, 1.0)
            cost_per_sqft = annual_utility / sqft if sqft else 0.0
            maint_burden_pct = (annual_maint / budget) * 100 if budget else 0.0
            occ_rate = occ_rates[fid]
            occ_pct = occ_rate * 100

            def clamp(v):
                return max(0.0, min(100.0, v))

            comp_occ = clamp(((occ_threshold - occ_rate) / occ_threshold) * 100)
            comp_util = clamp(
                (cost_per_sqft / benchmarks["utility_cost_per_sqft_annual"]) * 100
            )
            comp_maint = clamp(maint_burden_pct)
            comp_cap = clamp(
                (pending_cap / benchmarks["capital_request_threshold"]) * 100
            )
            comp_prog = clamp(
                (
                    (benchmarks["program_attendance_threshold"] - avg_att_rate)
                    / benchmarks["program_attendance_threshold"]
                )
                * 100
            )

            score = (
                weights["occupancy"] * comp_occ
                + weights["utility_cost_efficiency"] * comp_util
                + weights["maintenance_burden"] * comp_maint
                + weights["capital_exposure"] * comp_cap
                + weights["program_utilization"] * comp_prog
            )
            score = round(score, 1)

            if score >= rec_thresh["closure"]:
                recommendation = "closure"
            elif score >= rec_thresh["shared_space"]:
                recommendation = "shared_space"
            else:
                recommendation = "retain_with_review"

            report_rows.append({
                "facility_id": fid,
                "facility_name": details["name"],
                "zone": details["zone"],
                "facility_type": details["type"],
                "capacity": details["capacity"],
                "square_footage": sqft,
                "avg_occupancy_pct": round(occ_pct, 2),
                "annual_utility_cost": round(annual_utility, 2),
                "annual_maintenance_cost": round(annual_maint, 2),
                "pending_capital_amount": round(pending_cap, 2),
                "cost_per_sqft": round(cost_per_sqft, 2),
                "maintenance_burden_pct": round(maint_burden_pct, 2),
                "program_attendance_pct": round(avg_att_rate * 100, 2),
                "consolidation_score": score,
                "recommendation": recommendation,
            })

        # ---- 7. Sort & write report ----
        report_df = pd.DataFrame(report_rows)
        if not report_df.empty:
            report_df = report_df.sort_values(
                ["consolidation_score", "facility_id"],
                ascending=[False, True],
            ).reset_index(drop=True)

        report_path = os.path.join(self.workspace, "consolidation_report.csv")
        report_df.to_csv(report_path, index=False)

        # ---- 8. Construct action string ----
        lines = [
            f"Consolidation review complete. {len(report_rows)} facilities flagged "
            f"with average occupancy below {occ_threshold*100:.0f}%.",
            "",
        ]
        for _, row in report_df.iterrows():
            lines.append(
                f"  {row['facility_id']} ({row['facility_name']}): "
                f"score {row['consolidation_score']}, recommendation: {row['recommendation']}"
            )
        lines.append("")
        lines.append("Full results saved to consolidation_report.csv.")
        action = "\n".join(lines)

        return self.step(action)
