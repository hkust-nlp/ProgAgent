"""
Hotel Room Demand Forecasting — Task Environment
Provides tools for querying hotel data and evaluates rate-adjustment deliverables.
"""

import glob as glob_module
import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import yaml


# --- Decorator ---------------------------------------------------------
def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# --- Helper: ground-truth computation used by both step and verify -----
def _compute_expected(db_path: str, workspace: str):
    """Return (expected_df, expected_summary, boundaries_dict, rules) using
    direct DB access and workspace files.  Used only inside step()."""

    conn = sqlite3.connect(db_path)

    with open(os.path.join(workspace, "pricing_rules.yaml")) as f:
        rules = yaml.safe_load(f)
    with open(os.path.join(workspace, "room_types.yaml")) as f:
        room_cfg = yaml.safe_load(f)["room_types"]
    with open(os.path.join(workspace, "seasonal_factors.json")) as f:
        seasonal = json.load(f)["monthly_factors"]
    boundaries = pd.read_csv(os.path.join(workspace, "rate_boundaries.csv"))

    ref_date = rules["forecast"]["reference_date"]
    forecast_days = rules["forecast"]["forecast_days"]
    weights = rules["demand_weights"]
    event_factors = rules["event_impact_factors"]
    occ_baseline = rules["occupancy_scoring"]["baseline"]
    occ_scale = rules["occupancy_scoring"]["scale_factor"]
    flight_divisor = rules["flight_demand_divisor"]
    trend_days = rules["demand_trend_recent_days"]
    max_adj = rules["max_adjustment_pct"]
    min_adj = rules["min_adjustment_pct"]
    default_conv = rules["default_conversion_rate"]

    ref = datetime.strptime(ref_date, "%Y-%m-%d")
    forecast_dates = [
        (ref + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(forecast_days)
    ]
    room_types = sorted(room_cfg.keys())

    # Read workspace data files
    comp_files = sorted(glob_module.glob(os.path.join(workspace, "competitor_*_rates.csv")))
    all_comp = pd.concat([pd.read_csv(f) for f in comp_files]) if comp_files else pd.DataFrame()

    origin_files = sorted(glob_module.glob(os.path.join(workspace, "origin_profile_*.json")))
    origin_profiles: Dict[str, dict] = {}
    for fp in origin_files:
        with open(fp) as f:
            origin_profiles.update(json.load(f))

    group_files = sorted(glob_module.glob(os.path.join(workspace, "group_bookings_*.csv")))
    all_groups = (
        pd.concat([pd.read_csv(f) for f in group_files])
        if group_files
        else pd.DataFrame(columns=["date", "room_type", "num_rooms"])
    )

    # DB queries
    occ_df = pd.read_sql_query(
        "SELECT record_date, room_type, rooms_occupied, rooms_available "
        "FROM occupancy_records WHERE record_date BETWEEN ? AND ?",
        conn,
        params=[forecast_dates[0], forecast_dates[-1]],
    )
    events_df = pd.read_sql_query(
        "SELECT event_date, category, expected_attendance "
        "FROM local_events WHERE event_date BETWEEN ? AND ?",
        conn,
        params=[forecast_dates[0], forecast_dates[-1]],
    )
    flights_df = pd.read_sql_query(
        "SELECT arrival_date, origin_city, passenger_count "
        "FROM flight_arrivals WHERE arrival_date BETWEEN ? AND ?",
        conn,
        params=[forecast_dates[0], forecast_dates[-1]],
    )
    history_end = (ref - timedelta(days=1)).strftime("%Y-%m-%d")
    demand_df = pd.read_sql_query(
        "SELECT record_date, room_type, bookings, cancellations "
        "FROM demand_history WHERE record_date <= ?",
        conn,
        params=[history_end],
    )
    conn.close()

    boundaries_dict: Dict[str, dict] = {}
    for _, row in boundaries.iterrows():
        boundaries_dict[row["room_type"]] = {
            "floor": row["floor_rate"],
            "ceiling": row["ceiling_rate"],
        }

    trend_start = (ref - timedelta(days=trend_days)).strftime("%Y-%m-%d")

    results = []
    for d in forecast_dates:
        month_name = datetime.strptime(d, "%Y-%m-%d").strftime("%B")
        s_factor = seasonal.get(month_name, 1.0)

        for rt in room_types:
            base_rate = room_cfg[rt]["base_rate"]
            cap = room_cfg[rt]["capacity"]

            # 1. Occupancy signal
            occ_mask = (occ_df["record_date"] == d) & (occ_df["room_type"] == rt)
            occ_rows = occ_df[occ_mask]
            if not occ_rows.empty:
                rooms_occ = int(occ_rows.iloc[0]["rooms_occupied"])
                rooms_avail = int(occ_rows.iloc[0]["rooms_available"])
            else:
                rooms_occ = 0
                rooms_avail = cap

            group_add = 0
            if not all_groups.empty:
                gmask = (all_groups["date"] == d) & (all_groups["room_type"] == rt)
                group_add = int(all_groups.loc[gmask, "num_rooms"].sum())
            eff_occ = rooms_occ + group_add
            occ_ratio = min(eff_occ / rooms_avail, 1.0)
            occ_score = (occ_ratio - occ_baseline) * occ_scale

            # 2. Competitor signal
            if not all_comp.empty:
                cmask = (all_comp["date"] == d) & (all_comp["room_type"] == rt)
                crates = all_comp.loc[cmask, "rate"]
                comp_avg = float(crates.mean()) if len(crates) > 0 else float(base_rate)
            else:
                comp_avg = float(base_rate)
            comp_score = (comp_avg - base_rate) / base_rate

            # 3. Event signal
            emask = events_df["event_date"] == d
            day_events = events_df[emask]
            event_score = 0.0
            for _, ev in day_events.iterrows():
                factor = event_factors.get(ev["category"], 0)
                event_score += ev["expected_attendance"] * factor / 10000.0

            # 4. Flight signal
            fmask = flights_df["arrival_date"] == d
            day_flights = flights_df[fmask]
            flight_demand = 0.0
            for _, fl in day_flights.iterrows():
                conv = origin_profiles.get(fl["origin_city"], {}).get(
                    "conversion_rate", default_conv
                )
                flight_demand += fl["passenger_count"] * conv
            flight_score = flight_demand / flight_divisor

            # 5. Demand-trend signal
            rt_demand = demand_df[demand_df["room_type"] == rt]
            if not rt_demand.empty:
                all_net = rt_demand["bookings"] - rt_demand["cancellations"]
                longterm_avg = float(all_net.mean())
                recent = rt_demand[rt_demand["record_date"] >= trend_start]
                if not recent.empty:
                    recent_avg = float((recent["bookings"] - recent["cancellations"]).mean())
                else:
                    recent_avg = longterm_avg
                trend_score = (
                    (recent_avg - longterm_avg) / longterm_avg if longterm_avg != 0 else 0.0
                )
            else:
                trend_score = 0.0

            # Combine
            demand_score = (
                weights["occupancy"] * occ_score
                + weights["competitor"] * comp_score
                + weights["events"] * event_score
                + weights["flights"] * flight_score
                + weights["demand_trend"] * trend_score
            )
            adj_pct = demand_score * s_factor
            adj_pct = max(min_adj, min(max_adj, adj_pct))
            rec_rate = base_rate * (1 + adj_pct)
            floor = boundaries_dict[rt]["floor"]
            ceiling = boundaries_dict[rt]["ceiling"]
            rec_rate = max(floor, min(ceiling, rec_rate))
            rec_rate = round(rec_rate, 2)
            adj_pct = round(adj_pct, 4)

            results.append(
                {
                    "date": d,
                    "room_type": rt,
                    "base_rate": base_rate,
                    "recommended_rate": rec_rate,
                    "adjustment_pct": adj_pct,
                }
            )

    expected_df = pd.DataFrame(results).sort_values(["date", "room_type"]).reset_index(drop=True)

    # Build expected summary
    summary: Dict[str, Any] = {}
    for rt in room_types:
        rt_data = expected_df[expected_df["room_type"] == rt]
        avg_rate = round(float(rt_data["recommended_rate"].mean()), 2)
        avg_adj = round(float(rt_data["adjustment_pct"].mean()), 4)
        max_idx = rt_data["recommended_rate"].idxmax()
        min_idx = rt_data["recommended_rate"].idxmin()
        summary[rt] = {
            "avg_recommended_rate": avg_rate,
            "avg_adjustment_pct": avg_adj,
            "max_rate_date": rt_data.loc[max_idx, "date"],
            "min_rate_date": rt_data.loc[min_idx, "date"],
        }

    total_rev = 0.0
    for _, row in expected_df.iterrows():
        total_rev += row["recommended_rate"] * room_cfg[row["room_type"]]["capacity"]
    total_rev = round(total_rev, 2)

    return expected_df, summary, total_rev, boundaries_dict, rules, room_types, room_cfg


# =======================================================================
# Task Environment
# =======================================================================
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
    # TOOLS
    # ===================================================================

    @tool(
        description="Returns the list of distinct room type names available at the property.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_room_types(self) -> List[str]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT room_type FROM occupancy_records ORDER BY room_type")
        types = [row[0] for row in cur.fetchall()]
        conn.close()
        return types

    @tool(
        description=(
            "Returns occupancy records for a given room type within a date range. "
            "Each record contains the date, number of rooms occupied, and number of rooms available."
        ),
        parameters={
            "type": "object",
            "properties": {
                "room_type": {
                    "type": "string",
                    "description": "Room type name (e.g. 'Standard').",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date inclusive, YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date inclusive, YYYY-MM-DD.",
                },
            },
            "required": ["room_type", "start_date", "end_date"],
        },
    )
    def get_occupancy(self, room_type: str, start_date: str, end_date: str) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT record_date, rooms_occupied, rooms_available "
            "FROM occupancy_records "
            "WHERE room_type = ? AND record_date BETWEEN ? AND ? "
            "ORDER BY record_date",
            (room_type, start_date, end_date),
        )
        rows = [
            {"date": r[0], "rooms_occupied": r[1], "rooms_available": r[2]}
            for r in cur.fetchall()
        ]
        conn.close()
        return rows

    @tool(
        description=(
            "Returns all local events scheduled on a specific date. "
            "Each event includes its name, category, expected attendance, and venue."
        ),
        parameters={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date to query, YYYY-MM-DD.",
                },
            },
            "required": ["date"],
        },
    )
    def get_events(self, date: str) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT event_name, category, expected_attendance, venue "
            "FROM local_events WHERE event_date = ? ORDER BY id",
            (date,),
        )
        rows = [
            {
                "event_name": r[0],
                "category": r[1],
                "expected_attendance": r[2],
                "venue": r[3],
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return rows

    @tool(
        description=(
            "Returns all flight arrivals for a specific date. "
            "Each record includes flight number, origin city, passenger count, and arrival time."
        ),
        parameters={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Arrival date to query, YYYY-MM-DD.",
                },
            },
            "required": ["date"],
        },
    )
    def get_flight_arrivals(self, date: str) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT flight_number, origin_city, passenger_count, arrival_time "
            "FROM flight_arrivals WHERE arrival_date = ? ORDER BY id",
            (date,),
        )
        rows = [
            {
                "flight_number": r[0],
                "origin_city": r[1],
                "passenger_count": r[2],
                "arrival_time": r[3],
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return rows

    @tool(
        description=(
            "Returns historical demand records for a room type within a date range. "
            "Each record includes the date, bookings, cancellations, revenue, and average daily rate."
        ),
        parameters={
            "type": "object",
            "properties": {
                "room_type": {
                    "type": "string",
                    "description": "Room type name.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date inclusive, YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date inclusive, YYYY-MM-DD.",
                },
            },
            "required": ["room_type", "start_date", "end_date"],
        },
    )
    def get_demand_history(self, room_type: str, start_date: str, end_date: str) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT record_date, bookings, cancellations, revenue, avg_daily_rate "
            "FROM demand_history "
            "WHERE room_type = ? AND record_date BETWEEN ? AND ? "
            "ORDER BY record_date",
            (room_type, start_date, end_date),
        )
        rows = [
            {
                "date": r[0],
                "bookings": r[1],
                "cancellations": r[2],
                "revenue": r[3],
                "avg_daily_rate": r[4],
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return rows

    # ===================================================================
    # STEP — evaluation
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
        (
            expected_df,
            expected_summary,
            expected_total_rev,
            boundaries_dict,
            rules,
            room_types,
            room_cfg,
        ) = _compute_expected(self.db_path, self.workspace)

        max_adj = rules["max_adjustment_pct"]
        min_adj = rules["min_adjustment_pct"]
        forecast_days = rules["forecast"]["forecast_days"]

        criteria: Dict[str, dict] = {}

        # ---- Criterion 1: rate_recommendations.csv exists with correct columns (15 pts)
        rec_path = os.path.join(self.workspace, "rate_recommendations.csv")
        c1_pass = False
        c1_score = 0
        actual_df = None
        required_cols = {"date", "room_type", "base_rate", "recommended_rate", "adjustment_pct"}
        try:
            actual_df = pd.read_csv(rec_path)
            if required_cols.issubset(set(actual_df.columns)):
                c1_pass = True
                c1_score = 15
        except Exception:
            pass
        criteria["csv_exists_and_columns"] = {
            "passed": c1_pass,
            "score": c1_score,
            "max_score": 15,
        }

        # ---- Criterion 2: correct row count (10 pts)
        expected_rows = forecast_days * len(room_types)
        c2_pass = False
        c2_score = 0
        if actual_df is not None and len(actual_df) == expected_rows:
            c2_pass = True
            c2_score = 10
        criteria["csv_row_count"] = {
            "passed": c2_pass,
            "score": c2_score,
            "max_score": 10,
            **(
                {}
                if c2_pass
                else {"reason": f"Expected {expected_rows} rows, got {len(actual_df) if actual_df is not None else 0}"}
            ),
        }

        # ---- Criterion 3: rate boundaries respected (15 pts)
        c3_pass = False
        c3_score = 0
        if actual_df is not None and c1_pass:
            bounds_ok = True
            for _, row in actual_df.iterrows():
                rt = row["room_type"]
                if rt in boundaries_dict:
                    if (
                        row["recommended_rate"] < boundaries_dict[rt]["floor"] - 0.02
                        or row["recommended_rate"] > boundaries_dict[rt]["ceiling"] + 0.02
                    ):
                        bounds_ok = False
                        break
                if row["adjustment_pct"] < min_adj - 0.001 or row["adjustment_pct"] > max_adj + 0.001:
                    bounds_ok = False
                    break
            if bounds_ok:
                c3_pass = True
                c3_score = 15
        criteria["rate_boundaries"] = {
            "passed": c3_pass,
            "score": c3_score,
            "max_score": 15,
        }

        # ---- Criterion 4: rate accuracy (25 pts)
        c4_score = 0
        if actual_df is not None and c1_pass and len(actual_df) == expected_rows:
            actual_sorted = actual_df.sort_values(["date", "room_type"]).reset_index(drop=True)
            matches = 0
            total = len(expected_df)
            for i in range(total):
                exp = expected_df.iloc[i]
                act = actual_sorted.iloc[i]
                if str(act["date"]) == str(exp["date"]) and str(act["room_type"]) == str(exp["room_type"]):
                    tol = max(1.0, abs(exp["recommended_rate"]) * 0.02)
                    if abs(float(act["recommended_rate"]) - float(exp["recommended_rate"])) <= tol:
                        matches += 1
            c4_score = round(25 * matches / total) if total > 0 else 0
        criteria["rate_accuracy"] = {
            "passed": c4_score >= 20,
            "score": c4_score,
            "max_score": 25,
        }

        # ---- Criterion 5: forecast_summary.json exists with structure (10 pts)
        summary_path = os.path.join(self.workspace, "forecast_summary.json")
        c5_pass = False
        c5_score = 0
        summary_data = None
        try:
            with open(summary_path) as f:
                summary_data = json.load(f)
            if "room_types" in summary_data and "total_revenue_projection" in summary_data:
                c5_pass = True
                c5_score = 10
        except Exception:
            pass
        criteria["summary_exists"] = {
            "passed": c5_pass,
            "score": c5_score,
            "max_score": 10,
        }

        # ---- Criterion 6: forecast_summary.json accuracy (15 pts)
        c6_score = 0
        if summary_data and c5_pass:
            total_checks = len(room_types) + 1
            summary_matches = 0
            for rt in room_types:
                if rt in summary_data.get("room_types", {}):
                    srt = summary_data["room_types"][rt]
                    exp_avg = expected_summary[rt]["avg_recommended_rate"]
                    tol = max(1.0, abs(exp_avg) * 0.02)
                    if abs(srt.get("avg_recommended_rate", 0) - exp_avg) <= tol:
                        summary_matches += 1
            rev_tol = max(100.0, abs(expected_total_rev) * 0.03)
            if abs(summary_data.get("total_revenue_projection", 0) - expected_total_rev) <= rev_tol:
                summary_matches += 1
            c6_score = round(15 * summary_matches / total_checks)
        criteria["summary_accuracy"] = {
            "passed": c6_score >= 12,
            "score": c6_score,
            "max_score": 15,
        }

        # ---- Criterion 7: response insights (10 pts)
        c7_score = 0
        exp_adj: Dict[str, float] = {}
        for rt in room_types:
            rt_data = expected_df[expected_df["room_type"] == rt]
            exp_adj[rt] = float(rt_data["adjustment_pct"].mean())
        highest_adj_rt = max(exp_adj, key=exp_adj.get)  # type: ignore[arg-type]

        date_totals = expected_df.groupby("date")["recommended_rate"].sum()
        highest_rate_date = str(date_totals.idxmax())

        if highest_adj_rt.lower() in action.lower():
            c7_score += 5
        if highest_rate_date in action:
            c7_score += 5
        criteria["response_insights"] = {
            "passed": c7_score == 10,
            "score": c7_score,
            "max_score": 10,
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ===================================================================
    # VERIFY — end-to-end solvability proof
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

        # 1. Discover room types  (1 tool call)
        room_types = self.tools["list_room_types"]()

        # 2. Read configuration files from workspace
        with open(os.path.join(self.workspace, "pricing_rules.yaml")) as f:
            rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "room_types.yaml")) as f:
            room_cfg = yaml.safe_load(f)["room_types"]
        with open(os.path.join(self.workspace, "seasonal_factors.json")) as f:
            seasonal = json.load(f)["monthly_factors"]
        boundaries = pd.read_csv(os.path.join(self.workspace, "rate_boundaries.csv"))

        ref_date = rules["forecast"]["reference_date"]
        forecast_days = rules["forecast"]["forecast_days"]
        weights = rules["demand_weights"]
        event_factors = rules["event_impact_factors"]
        occ_baseline = rules["occupancy_scoring"]["baseline"]
        occ_scale = rules["occupancy_scoring"]["scale_factor"]
        flight_divisor = rules["flight_demand_divisor"]
        trend_days = rules["demand_trend_recent_days"]
        max_adj = rules["max_adjustment_pct"]
        min_adj = rules["min_adjustment_pct"]
        default_conv = rules["default_conversion_rate"]

        ref = datetime.strptime(ref_date, "%Y-%m-%d")
        forecast_dates = [
            (ref + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(forecast_days)
        ]

        # 3. Read scalable workspace data files
        comp_files = sorted(glob_module.glob(os.path.join(self.workspace, "competitor_*_rates.csv")))
        all_comp = pd.concat([pd.read_csv(f) for f in comp_files]) if comp_files else pd.DataFrame()

        origin_files = sorted(glob_module.glob(os.path.join(self.workspace, "origin_profile_*.json")))
        origin_profiles: Dict[str, dict] = {}
        for fp in origin_files:
            with open(fp) as fh:
                origin_profiles.update(json.load(fh))

        group_files = sorted(glob_module.glob(os.path.join(self.workspace, "group_bookings_*.csv")))
        all_groups = (
            pd.concat([pd.read_csv(f) for f in group_files])
            if group_files
            else pd.DataFrame(columns=["date", "room_type", "num_rooms"])
        )

        boundaries_dict: Dict[str, dict] = {}
        for _, row in boundaries.iterrows():
            boundaries_dict[row["room_type"]] = {
                "floor": row["floor_rate"],
                "ceiling": row["ceiling_rate"],
            }

        # 4. Gather data via tools
        # Occupancy for forecast window — 1 call per room type  (5 calls)
        occupancy_data: Dict[tuple, dict] = {}
        for rt in room_types:
            occ_records = self.tools["get_occupancy"](
                room_type=rt, start_date=forecast_dates[0], end_date=forecast_dates[-1]
            )
            for rec in occ_records:
                occupancy_data[(rec["date"], rt)] = rec

        # Events per forecast date  (14 calls)
        events_data: Dict[str, list] = {}
        for d in forecast_dates:
            events_data[d] = self.tools["get_events"](date=d)

        # Flight arrivals per forecast date  (14 calls)
        flights_data: Dict[str, list] = {}
        for d in forecast_dates:
            flights_data[d] = self.tools["get_flight_arrivals"](date=d)

        # Demand history — 1 call per room type  (5 calls)
        history_end = (ref - timedelta(days=1)).strftime("%Y-%m-%d")
        history_start_all = (ref - timedelta(days=400)).strftime("%Y-%m-%d")
        trend_start = (ref - timedelta(days=trend_days)).strftime("%Y-%m-%d")

        demand_data: Dict[str, list] = {}
        for rt in room_types:
            demand_data[rt] = self.tools["get_demand_history"](
                room_type=rt, start_date=history_start_all, end_date=history_end
            )

        # Total tool calls: 1 + 5 + 14 + 14 + 5 = 39

        # 5. Compute rate recommendations
        results = []
        for d in forecast_dates:
            month_name = datetime.strptime(d, "%Y-%m-%d").strftime("%B")
            s_factor = seasonal.get(month_name, 1.0)

            for rt in room_types:
                base_rate = room_cfg[rt]["base_rate"]
                cap = room_cfg[rt]["capacity"]

                # Occupancy signal
                occ_rec = occupancy_data.get(
                    (d, rt), {"rooms_occupied": 0, "rooms_available": cap}
                )
                group_add = 0
                if not all_groups.empty:
                    gmask = (all_groups["date"] == d) & (all_groups["room_type"] == rt)
                    group_add = int(all_groups.loc[gmask, "num_rooms"].sum())
                eff_occ = occ_rec["rooms_occupied"] + group_add
                occ_ratio = min(eff_occ / occ_rec["rooms_available"], 1.0)
                occ_score = (occ_ratio - occ_baseline) * occ_scale

                # Competitor signal
                if not all_comp.empty:
                    cmask = (all_comp["date"] == d) & (all_comp["room_type"] == rt)
                    crates = all_comp.loc[cmask, "rate"]
                    comp_avg = float(crates.mean()) if len(crates) > 0 else float(base_rate)
                else:
                    comp_avg = float(base_rate)
                comp_score = (comp_avg - base_rate) / base_rate

                # Event signal
                events = events_data.get(d, [])
                event_score = 0.0
                for ev in events:
                    factor = event_factors.get(ev["category"], 0)
                    event_score += ev["expected_attendance"] * factor / 10000.0

                # Flight signal
                flights = flights_data.get(d, [])
                flight_demand = 0.0
                for fl in flights:
                    conv = origin_profiles.get(fl["origin_city"], {}).get(
                        "conversion_rate", default_conv
                    )
                    flight_demand += fl["passenger_count"] * conv
                flight_score = flight_demand / flight_divisor

                # Demand-trend signal
                hist = demand_data.get(rt, [])
                if hist:
                    all_net = [(h["bookings"] - h["cancellations"]) for h in hist]
                    longterm_avg = sum(all_net) / len(all_net)
                    recent = [h for h in hist if h["date"] >= trend_start]
                    if recent:
                        recent_net = [(h["bookings"] - h["cancellations"]) for h in recent]
                        recent_avg = sum(recent_net) / len(recent_net)
                    else:
                        recent_avg = longterm_avg
                    trend_score = (
                        (recent_avg - longterm_avg) / longterm_avg if longterm_avg != 0 else 0.0
                    )
                else:
                    trend_score = 0.0

                # Combine signals
                demand_score = (
                    weights["occupancy"] * occ_score
                    + weights["competitor"] * comp_score
                    + weights["events"] * event_score
                    + weights["flights"] * flight_score
                    + weights["demand_trend"] * trend_score
                )
                adj_pct = demand_score * s_factor
                adj_pct = max(min_adj, min(max_adj, adj_pct))
                rec_rate = base_rate * (1 + adj_pct)
                floor = boundaries_dict[rt]["floor"]
                ceiling = boundaries_dict[rt]["ceiling"]
                rec_rate = max(floor, min(ceiling, rec_rate))
                rec_rate = round(rec_rate, 2)
                adj_pct = round(adj_pct, 4)

                results.append(
                    {
                        "date": d,
                        "room_type": rt,
                        "base_rate": base_rate,
                        "recommended_rate": rec_rate,
                        "adjustment_pct": adj_pct,
                    }
                )

        rec_df = pd.DataFrame(results).sort_values(["date", "room_type"]).reset_index(drop=True)
        rec_df.to_csv(os.path.join(self.workspace, "rate_recommendations.csv"), index=False)

        # 6. Build forecast_summary.json
        summary: Dict[str, Any] = {}
        for rt in room_types:
            rt_data = rec_df[rec_df["room_type"] == rt]
            avg_rate = round(float(rt_data["recommended_rate"].mean()), 2)
            avg_adj = round(float(rt_data["adjustment_pct"].mean()), 4)
            max_idx = rt_data["recommended_rate"].idxmax()
            min_idx = rt_data["recommended_rate"].idxmin()
            summary[rt] = {
                "avg_recommended_rate": avg_rate,
                "avg_adjustment_pct": avg_adj,
                "max_rate_date": rt_data.loc[max_idx, "date"],
                "min_rate_date": rt_data.loc[min_idx, "date"],
            }

        total_rev = 0.0
        for _, row in rec_df.iterrows():
            total_rev += row["recommended_rate"] * room_cfg[row["room_type"]]["capacity"]
        total_rev = round(total_rev, 2)

        forecast_out = {"room_types": summary, "total_revenue_projection": total_rev}
        with open(os.path.join(self.workspace, "forecast_summary.json"), "w") as f:
            json.dump(forecast_out, f, indent=2)

        # 7. Construct action string
        highest_adj_rt = max(summary.keys(), key=lambda rt: summary[rt]["avg_adjustment_pct"])
        highest_adj_val = summary[highest_adj_rt]["avg_adjustment_pct"]

        date_totals = rec_df.groupby("date")["recommended_rate"].sum()
        highest_rate_date = str(date_totals.idxmax())
        highest_rate_total = round(float(date_totals.max()), 2)

        action = (
            f"Rate adjustment analysis complete. "
            f"The room type with the highest average adjustment is {highest_adj_rt} "
            f"at {highest_adj_val:.4f}. "
            f"The date with the highest total recommended rate across all room types is "
            f"{highest_rate_date} with a combined rate of {highest_rate_total:.2f}. "
            f"Detailed recommendations have been saved to rate_recommendations.csv "
            f"and the forecast summary to forecast_summary.json."
        )

        return self.step(action)
