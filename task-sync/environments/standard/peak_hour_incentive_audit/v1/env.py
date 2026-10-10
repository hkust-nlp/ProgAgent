import sqlite3
import os
import json
import csv
import yaml
import glob
from datetime import datetime, timedelta
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
    # Tool methods
    # ================================================================

    @tool(
        description="List all pending incentive claims. Returns paginated results with claim_id, driver_id, campaign_id, trip_id, claimed_amount, and claim_date.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Each page returns up to 20 claims.",
                },
            },
            "required": ["page"],
        },
    )
    def list_pending_claims(self, page: int) -> dict:
        page_size = 20
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM incentive_claims WHERE status='pending'")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT claim_id, driver_id, campaign_id, trip_id, claimed_amount, claim_date "
            "FROM incentive_claims WHERE status='pending' ORDER BY claim_id "
            "LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total_pending": total,
            "total_pages": (total + page_size - 1) // page_size,
            "claims": rows,
        }

    @tool(
        description="Get detailed information about a specific trip by its trip ID.",
        parameters={
            "type": "object",
            "properties": {
                "trip_id": {
                    "type": "string",
                    "description": "The trip identifier, e.g. 'T00042'.",
                },
            },
            "required": ["trip_id"],
        },
    )
    def get_trip_details(self, trip_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM trips WHERE trip_id=?", (trip_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Trip {trip_id} not found"}
        return dict(row)

    @tool(
        description="Get campaign details by campaign ID, including bonus amount, eligibility criteria, and active dates.",
        parameters={
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign identifier, e.g. 'C042'.",
                },
            },
            "required": ["campaign_id"],
        },
    )
    def get_campaign_info(self, campaign_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Campaign {campaign_id} not found"}
        return dict(row)

    @tool(
        description="Get all online sessions for a driver within a date range. Returns session_id, online_start, online_end, and session_status.",
        parameters={
            "type": "object",
            "properties": {
                "driver_id": {
                    "type": "string",
                    "description": "Driver identifier, e.g. 'D0001'.",
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
            "required": ["driver_id", "start_date", "end_date"],
        },
    )
    def get_driver_sessions(
        self, driver_id: str, start_date: str, end_date: str
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        end_dt = end_date + " 23:59:59"
        start_dt = start_date + " 00:00:00"
        cur.execute(
            "SELECT session_id, online_start, online_end, session_status "
            "FROM driver_sessions "
            "WHERE driver_id=? AND online_end >= ? AND online_start <= ? "
            "ORDER BY online_start",
            (driver_id, start_dt, end_dt),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"driver_id": driver_id, "sessions": rows}

    @tool(
        description="Get surge pricing records for a specific zone on a given date. Returns all surge windows active on that date with their multipliers.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "string",
                    "description": "Zone identifier, e.g. 'Z001'.",
                },
                "date": {
                    "type": "string",
                    "description": "Date string, YYYY-MM-DD.",
                },
            },
            "required": ["zone_id", "date"],
        },
    )
    def get_surge_records(self, zone_id: str, date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        day_start = date + " 00:00:00"
        day_end = date + " 23:59:59"
        cur.execute(
            "SELECT record_id, zone_id, surge_start, surge_end, surge_multiplier "
            "FROM surge_zones "
            "WHERE zone_id=? AND surge_end >= ? AND surge_start <= ? "
            "ORDER BY surge_start",
            (zone_id, day_start, day_end),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"zone_id": zone_id, "date": date, "surge_records": rows}

    @tool(
        description="Count completed trips for a driver within a date range.",
        parameters={
            "type": "object",
            "properties": {
                "driver_id": {
                    "type": "string",
                    "description": "Driver identifier.",
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
            "required": ["driver_id", "start_date", "end_date"],
        },
    )
    def count_driver_completed_trips(
        self, driver_id: str, start_date: str, end_date: str
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM trips "
            "WHERE driver_id=? AND status='completed' "
            "AND start_time >= ? AND start_time <= ?",
            (driver_id, start_date + " 00:00:00", end_date + " 23:59:59"),
        )
        count = cur.fetchone()[0]
        conn.close()
        return {
            "driver_id": driver_id,
            "start_date": start_date,
            "end_date": end_date,
            "completed_trips": count,
        }

    @tool(
        description="Get basic information about a driver by their ID.",
        parameters={
            "type": "object",
            "properties": {
                "driver_id": {
                    "type": "string",
                    "description": "Driver identifier, e.g. 'D0001'.",
                },
            },
            "required": ["driver_id"],
        },
    )
    def get_driver_info(self, driver_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM drivers WHERE driver_id=?", (driver_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Driver {driver_id} not found"}
        return dict(row)

    # ================================================================
    # Evaluation
    # ================================================================

    def _load_workspace_config(self):
        """Load all workspace config files needed for ground-truth computation."""
        with open(os.path.join(self.workspace, "peak_hours_config.json")) as f:
            peak_hours = json.load(f)
        with open(os.path.join(self.workspace, "payout_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        zone_tier = {}
        with open(os.path.join(self.workspace, "zone_tier_mapping.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                zone_tier[row["zone_id"]] = row["tier"]
        return peak_hours, policy, zone_tier

    def _load_driver_ratings(self, driver_ids_needed=None):
        """Load daily ratings from workspace log files. Returns {driver_id: {date_str: rating}}."""
        ratings = {}
        log_files = sorted(glob.glob(os.path.join(self.workspace, "daily_ops_log_*.csv")))
        for fpath in log_files:
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    did = row["driver_id"]
                    if driver_ids_needed and did not in driver_ids_needed:
                        continue
                    ratings.setdefault(did, {})[row["report_date"]] = float(
                        row["daily_rating"]
                    )
        return ratings

    def _is_peak_hour(self, dt: datetime, peak_hours: dict) -> bool:
        wd = dt.weekday()
        day_type = "weekday" if wd < 5 else "weekend"
        h = dt.hour
        for window in peak_hours[day_type].values():
            if window[0] <= h < window[1]:
                return True
        return False

    def _compute_ground_truth(self):
        """
        Compute the ground-truth adjusted payout report using DB + workspace.
        Returns list of dicts with keys:
            claim_id, driver_id, campaign_id, trip_id, claimed_amount,
            eligible, adjusted_amount, discrepancy_reasons
        """
        peak_hours, policy, zone_tier = self._load_workspace_config()
        tier_mult = policy["payout_calculation"]["zone_tier_multiplier"]
        counted_statuses = set(policy["eligibility"]["session_status_counted"])
        rounding = policy["payout_calculation"]["rounding_decimals"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # load all pending claims
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM incentive_claims WHERE status='pending' ORDER BY claim_id"
        )
        pending = [dict(r) for r in cur.fetchall()]

        # detect duplicates: same (driver_id, campaign_id, trip_id) appearing >1 times in pending
        from collections import Counter

        combo_counts = Counter(
            (c["driver_id"], c["campaign_id"], c["trip_id"]) for c in pending
        )
        dup_combos = {k for k, v in combo_counts.items() if v > 1}

        # pre-load campaigns
        cur.execute("SELECT * FROM campaigns")
        campaigns = {r["campaign_id"]: dict(r) for r in cur.fetchall()}

        # gather driver IDs that have pending claims
        driver_ids_needed = {c["driver_id"] for c in pending}
        ratings = self._load_driver_ratings(driver_ids_needed)

        results = []
        # We need per-driver-campaign approved amounts for cap enforcement
        # First pass: determine eligibility (ignoring cap)
        pre_results = []
        for claim in pending:
            reasons = []
            cid = claim["campaign_id"]
            did = claim["driver_id"]
            tid = claim["trip_id"]
            camp = campaigns.get(cid)

            if camp is None:
                reasons.append("campaign_not_found")
                pre_results.append(
                    {
                        **claim,
                        "eligible": False,
                        "adjusted_amount": 0.0,
                        "discrepancy_reasons": reasons,
                        "computed_amount": 0.0,
                    }
                )
                continue

            # duplicate check
            if (did, cid, tid) in dup_combos:
                reasons.append("duplicate_claim")

            # get trip
            cur.execute("SELECT * FROM trips WHERE trip_id=?", (tid,))
            trip_row = cur.fetchone()
            if trip_row is None:
                reasons.append("trip_not_found")
                pre_results.append(
                    {
                        **claim,
                        "eligible": False,
                        "adjusted_amount": 0.0,
                        "discrepancy_reasons": reasons,
                        "computed_amount": 0.0,
                    }
                )
                continue
            trip = dict(trip_row)

            # trip completed?
            if trip["status"] != "completed":
                reasons.append("trip_not_completed")

            # trip within campaign dates?
            trip_start = datetime.strptime(trip["start_time"], "%Y-%m-%d %H:%M:%S")
            camp_start = datetime.strptime(camp["start_date"], "%Y-%m-%d")
            camp_end = datetime.strptime(camp["end_date"], "%Y-%m-%d") + timedelta(
                days=1
            ) - timedelta(seconds=1)
            if not (camp_start <= trip_start <= camp_end):
                reasons.append("trip_outside_campaign_period")

            # zone eligibility
            trip_zone = trip["zone_id"]
            trip_tier = zone_tier.get(trip_zone, "unknown")
            eligible_tiers = set(camp["eligible_zone_tiers"].split(","))
            if trip_tier not in eligible_tiers:
                reasons.append("zone_not_eligible")

            # peak hours check
            if camp["peak_hours_only"] == 1:
                if not self._is_peak_hour(trip_start, peak_hours):
                    reasons.append("trip_not_in_peak_hours")

            # driver completed trips in campaign period
            camp_sd = camp["start_date"]
            camp_ed = camp["end_date"]
            cur.execute(
                "SELECT COUNT(*) FROM trips "
                "WHERE driver_id=? AND status='completed' "
                "AND start_time >= ? AND start_time <= ?",
                (did, camp_sd + " 00:00:00", camp_ed + " 23:59:59"),
            )
            trip_count = cur.fetchone()[0]
            if trip_count < camp["min_completed_trips"]:
                reasons.append("insufficient_completed_trips")

            # driver online hours (only 'active' sessions)
            cur.execute(
                "SELECT online_start, online_end, session_status "
                "FROM driver_sessions "
                "WHERE driver_id=? AND online_end >= ? AND online_start <= ?",
                (did, camp_sd + " 00:00:00", camp_ed + " 23:59:59"),
            )
            total_hours = 0.0
            camp_start_dt = datetime.strptime(camp_sd, "%Y-%m-%d")
            camp_end_dt = datetime.strptime(camp_ed, "%Y-%m-%d") + timedelta(
                days=1
            ) - timedelta(seconds=1)
            for sess in cur.fetchall():
                if sess["session_status"] not in counted_statuses:
                    continue
                s = max(
                    datetime.strptime(sess["online_start"], "%Y-%m-%d %H:%M:%S"),
                    camp_start_dt,
                )
                e = min(
                    datetime.strptime(sess["online_end"], "%Y-%m-%d %H:%M:%S"),
                    camp_end_dt,
                )
                if e > s:
                    total_hours += (e - s).total_seconds() / 3600.0
            if total_hours < camp["min_online_hours"]:
                reasons.append("insufficient_online_hours")

            # driver rating from workspace
            driver_ratings = ratings.get(did, {})
            camp_dates = []
            d = datetime.strptime(camp_sd, "%Y-%m-%d")
            end_d = datetime.strptime(camp_ed, "%Y-%m-%d")
            while d <= end_d:
                camp_dates.append(d.strftime("%Y-%m-%d"))
                d += timedelta(days=1)
            period_ratings = [
                driver_ratings[dt] for dt in camp_dates if dt in driver_ratings
            ]
            if period_ratings:
                avg_rating = sum(period_ratings) / len(period_ratings)
            else:
                avg_rating = 0.0
            if avg_rating < camp["min_driver_rating"]:
                reasons.append("rating_below_minimum")

            # compute correct amount
            bonus = camp["bonus_per_trip"]
            zt_mult = tier_mult.get(trip_tier, 1.0)
            # surge: highest active at trip start
            trip_date_str = trip_start.strftime("%Y-%m-%d")
            cur.execute(
                "SELECT surge_multiplier FROM surge_zones "
                "WHERE zone_id=? AND surge_start <= ? AND surge_end >= ?",
                (trip_zone, trip["start_time"], trip["start_time"]),
            )
            surge_rows = cur.fetchall()
            surge_mult = max([r[0] for r in surge_rows], default=1.0)
            computed = round(bonus * zt_mult * surge_mult, rounding)

            if len(reasons) == 0:
                # check amount mismatch
                if abs(claim["claimed_amount"] - computed) > 0.01:
                    reasons.append("amount_mismatch")

            eligible = len(reasons) == 0
            adj_amount = computed if eligible else 0.0

            pre_results.append(
                {
                    **claim,
                    "eligible": eligible,
                    "adjusted_amount": adj_amount,
                    "discrepancy_reasons": reasons,
                    "computed_amount": computed,
                }
            )

        conn.close()

        # Second pass: enforce per-driver cap per campaign
        # Group eligible claims by (driver_id, campaign_id), sorted by claim_id
        from collections import defaultdict

        dc_groups = defaultdict(list)
        for i, pr in enumerate(pre_results):
            if pr["eligible"]:
                dc_groups[(pr["driver_id"], pr["campaign_id"])].append(i)

        for (did, cid), indices in dc_groups.items():
            camp = campaigns[cid]
            cap = camp["max_payout_per_driver"]
            indices.sort(key=lambda i: pre_results[i]["claim_id"])
            cumulative = 0.0
            for idx in indices:
                amt = pre_results[idx]["adjusted_amount"]
                if cumulative + amt <= cap:
                    cumulative += amt
                else:
                    remainder = max(0.0, cap - cumulative)
                    pre_results[idx]["adjusted_amount"] = round(remainder, 2)
                    if remainder < amt:
                        pre_results[idx]["discrepancy_reasons"].append(
                            "per_driver_cap_exceeded"
                        )
                        if remainder == 0.0:
                            pre_results[idx]["eligible"] = False
                    cumulative = cap

        # Build final results
        results = []
        for pr in pre_results:
            reasons_str = (
                ";".join(pr["discrepancy_reasons"])
                if pr["discrepancy_reasons"]
                else "none"
            )
            results.append(
                {
                    "claim_id": pr["claim_id"],
                    "driver_id": pr["driver_id"],
                    "campaign_id": pr["campaign_id"],
                    "trip_id": pr["trip_id"],
                    "claimed_amount": pr["claimed_amount"],
                    "eligible": pr["eligible"],
                    "adjusted_amount": pr["adjusted_amount"],
                    "discrepancy_reasons": reasons_str,
                }
            )
        return results

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
        gt_by_id = {r["claim_id"]: r for r in gt}
        total_gt = len(gt)

        criteria = {}

        # --- Criterion 1: Report file exists with correct name (10 pts) ---
        report_path = os.path.join(self.workspace, "adjusted_payout_report.csv")
        file_exists = os.path.isfile(report_path)
        criteria["report_file_exists"] = {
            "passed": file_exists,
            "score": 10 if file_exists else 0,
            "max_score": 10,
        }
        if not file_exists:
            criteria["report_file_exists"]["reason"] = (
                "adjusted_payout_report.csv not found in workspace"
            )

        # --- Parse report if exists ---
        agent_rows = []
        if file_exists:
            try:
                with open(report_path) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        agent_rows.append(row)
            except Exception as e:
                criteria["report_parse"] = {
                    "passed": False,
                    "score": 0,
                    "max_score": 0,
                    "reason": f"CSV parse error: {e}",
                }

        # --- Criterion 2: Correct columns (10 pts) ---
        expected_cols = {
            "claim_id",
            "driver_id",
            "campaign_id",
            "trip_id",
            "claimed_amount",
            "eligible",
            "adjusted_amount",
            "discrepancy_reasons",
        }
        if agent_rows:
            actual_cols = set(agent_rows[0].keys())
            cols_ok = expected_cols.issubset(actual_cols)
        else:
            cols_ok = False
        criteria["correct_columns"] = {
            "passed": cols_ok,
            "score": 10 if cols_ok else 0,
            "max_score": 10,
        }
        if not cols_ok:
            if agent_rows:
                criteria["correct_columns"]["reason"] = (
                    f"Missing columns: {expected_cols - set(agent_rows[0].keys())}"
                )
            else:
                criteria["correct_columns"]["reason"] = "No data rows in report"

        # --- Criterion 3: Correct number of rows (10 pts) ---
        row_count_ok = len(agent_rows) == total_gt
        criteria["correct_row_count"] = {
            "passed": row_count_ok,
            "score": 10 if row_count_ok else 0,
            "max_score": 10,
        }
        if not row_count_ok:
            criteria["correct_row_count"]["reason"] = (
                f"Expected {total_gt} rows, got {len(agent_rows)}"
            )

        # --- Criterion 4: Eligibility correctness (25 pts) ---
        if agent_rows and cols_ok:
            agent_by_id = {r["claim_id"]: r for r in agent_rows}
            correct_elig = 0
            for cid, gt_row in gt_by_id.items():
                ar = agent_by_id.get(cid)
                if ar is None:
                    continue
                gt_elig = str(gt_row["eligible"])
                ag_elig = str(ar.get("eligible", "")).strip()
                if ag_elig.lower() == gt_elig.lower():
                    correct_elig += 1
            elig_ratio = correct_elig / total_gt if total_gt > 0 else 0
            elig_score = round(25 * elig_ratio)
        else:
            elig_ratio = 0
            elig_score = 0
        criteria["eligibility_accuracy"] = {
            "passed": elig_ratio >= 0.95,
            "score": elig_score,
            "max_score": 25,
        }
        if elig_ratio < 0.95:
            criteria["eligibility_accuracy"]["reason"] = (
                f"Eligibility accuracy {elig_ratio:.2%} (need >= 95%)"
            )

        # --- Criterion 5: Adjusted amount correctness (25 pts) ---
        if agent_rows and cols_ok:
            correct_amt = 0
            for cid, gt_row in gt_by_id.items():
                ar = agent_by_id.get(cid)
                if ar is None:
                    continue
                try:
                    ag_amt = float(ar.get("adjusted_amount", -1))
                except (ValueError, TypeError):
                    ag_amt = -1
                if abs(ag_amt - gt_row["adjusted_amount"]) < 0.02:
                    correct_amt += 1
            amt_ratio = correct_amt / total_gt if total_gt > 0 else 0
            amt_score = round(25 * amt_ratio)
        else:
            amt_ratio = 0
            amt_score = 0
        criteria["adjusted_amount_accuracy"] = {
            "passed": amt_ratio >= 0.95,
            "score": amt_score,
            "max_score": 25,
        }
        if amt_ratio < 0.95:
            criteria["adjusted_amount_accuracy"]["reason"] = (
                f"Amount accuracy {amt_ratio:.2%} (need >= 95%)"
            )

        # --- Criterion 6: Discrepancy reasons correctness (10 pts) ---
        if agent_rows and cols_ok:
            correct_reasons = 0
            for cid, gt_row in gt_by_id.items():
                ar = agent_by_id.get(cid)
                if ar is None:
                    continue
                gt_set = set(gt_row["discrepancy_reasons"].split(";"))
                ag_raw = ar.get("discrepancy_reasons", "")
                ag_set = set(ag_raw.split(";")) if ag_raw else set()
                if gt_set == ag_set:
                    correct_reasons += 1
            reason_ratio = correct_reasons / total_gt if total_gt > 0 else 0
            reason_score = round(10 * reason_ratio)
        else:
            reason_ratio = 0
            reason_score = 0
        criteria["discrepancy_reasons_accuracy"] = {
            "passed": reason_ratio >= 0.90,
            "score": reason_score,
            "max_score": 10,
        }
        if reason_ratio < 0.90:
            criteria["discrepancy_reasons_accuracy"]["reason"] = (
                f"Reasons accuracy {reason_ratio:.2%} (need >= 90%)"
            )

        # --- Criterion 7: Summary in action text (10 pts) ---
        # Expect: total_claims_processed, total_approved, total_rejected,
        # total_claimed, total_adjusted
        total_approved = sum(1 for r in gt if r["eligible"])
        total_rejected = total_gt - total_approved
        total_claimed = round(sum(r["claimed_amount"] for r in gt), 2)
        total_adjusted = round(sum(r["adjusted_amount"] for r in gt), 2)

        summary_checks = 0
        action_lower = action.lower() if action else ""
        if str(total_gt) in action:
            summary_checks += 1
        if str(total_approved) in action:
            summary_checks += 1
        if str(total_rejected) in action:
            summary_checks += 1
        # Check total_adjusted amount appears (formatted as string)
        if f"{total_adjusted:.2f}" in action or str(total_adjusted) in action:
            summary_checks += 1
        summary_score = round(10 * (summary_checks / 4))
        criteria["action_summary"] = {
            "passed": summary_checks >= 3,
            "score": summary_score,
            "max_score": 10,
        }
        if summary_checks < 3:
            criteria["action_summary"]["reason"] = (
                f"Only {summary_checks}/4 summary items found in response "
                f"(expected total_processed={total_gt}, approved={total_approved}, "
                f"rejected={total_rejected}, total_adjusted={total_adjusted:.2f})"
            )

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as _csv
        import json as _json
        import yaml as _yaml
        import os as _os

        # ---- Step 1: read workspace config files ----
        ws = self.workspace

        with open(_os.path.join(ws, "peak_hours_config.json")) as f:
            peak_hours = _json.load(f)

        with open(_os.path.join(ws, "payout_policy.yaml")) as f:
            policy = _yaml.safe_load(f)

        zone_tier = {}
        with open(_os.path.join(ws, "zone_tier_mapping.csv")) as f:
            reader = _csv.DictReader(f)
            for row in reader:
                zone_tier[row["zone_id"]] = row["tier"]

        tier_mult = policy["payout_calculation"]["zone_tier_multiplier"]
        counted_statuses = set(policy["eligibility"]["session_status_counted"])
        rounding = policy["payout_calculation"]["rounding_decimals"]

        # read daily ratings
        import glob as _glob

        driver_ratings = {}  # {driver_id: {date: rating}}
        for fpath in sorted(_glob.glob(_os.path.join(ws, "daily_ops_log_*.csv"))):
            with open(fpath) as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    driver_ratings.setdefault(row["driver_id"], {})[
                        row["report_date"]
                    ] = float(row["daily_rating"])

        # ---- Step 2: list all pending claims via tool ----
        all_claims = []
        page = 1
        while True:
            result = self.tools["list_pending_claims"](page=page)
            all_claims.extend(result["claims"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ---- Step 3: gather unique campaigns, trips, drivers ----
        campaign_cache = {}
        trip_cache = {}

        for claim in all_claims:
            cid = claim["campaign_id"]
            if cid not in campaign_cache:
                campaign_cache[cid] = self.tools["get_campaign_info"](campaign_id=cid)

            tid = claim["trip_id"]
            if tid not in trip_cache:
                trip_cache[tid] = self.tools["get_trip_details"](trip_id=tid)

        # detect duplicates among pending claims
        from collections import Counter, defaultdict

        combo_counts = Counter(
            (c["driver_id"], c["campaign_id"], c["trip_id"]) for c in all_claims
        )
        dup_combos = {k for k, v in combo_counts.items() if v > 1}

        # helper: is peak hour
        def is_peak(dt):
            wd = dt.weekday()
            day_type = "weekday" if wd < 5 else "weekend"
            h = dt.hour
            for window in peak_hours[day_type].values():
                if window[0] <= h < window[1]:
                    return True
            return False

        # ---- Step 4: process each claim ----
        # We need driver sessions and trip counts per (driver, campaign) combo
        session_cache = {}  # (driver_id, start_date, end_date) -> sessions
        trip_count_cache = {}  # (driver_id, start_date, end_date) -> count

        pre_results = []
        for claim in all_claims:
            reasons = []
            cid = claim["campaign_id"]
            did = claim["driver_id"]
            tid = claim["trip_id"]
            camp = campaign_cache.get(cid)

            if camp is None or "error" in camp:
                reasons.append("campaign_not_found")
                pre_results.append(
                    {
                        "claim_id": claim["claim_id"],
                        "driver_id": did,
                        "campaign_id": cid,
                        "trip_id": tid,
                        "claimed_amount": claim["claimed_amount"],
                        "eligible": False,
                        "adjusted_amount": 0.0,
                        "discrepancy_reasons": reasons,
                    }
                )
                continue

            # duplicate
            if (did, cid, tid) in dup_combos:
                reasons.append("duplicate_claim")

            trip = trip_cache.get(tid)
            if trip is None or "error" in trip:
                reasons.append("trip_not_found")
                pre_results.append(
                    {
                        "claim_id": claim["claim_id"],
                        "driver_id": did,
                        "campaign_id": cid,
                        "trip_id": tid,
                        "claimed_amount": claim["claimed_amount"],
                        "eligible": False,
                        "adjusted_amount": 0.0,
                        "discrepancy_reasons": reasons,
                    }
                )
                continue

            # trip completed
            if trip["status"] != "completed":
                reasons.append("trip_not_completed")

            # trip in campaign period
            trip_start = datetime.strptime(trip["start_time"], "%Y-%m-%d %H:%M:%S")
            camp_sd = camp["start_date"]
            camp_ed = camp["end_date"]
            camp_start_dt = datetime.strptime(camp_sd, "%Y-%m-%d")
            camp_end_dt = datetime.strptime(camp_ed, "%Y-%m-%d") + timedelta(
                days=1
            ) - timedelta(seconds=1)
            if not (camp_start_dt <= trip_start <= camp_end_dt):
                reasons.append("trip_outside_campaign_period")

            # zone eligibility
            trip_zone = trip["zone_id"]
            trip_tier = zone_tier.get(trip_zone, "unknown")
            eligible_tiers = set(camp["eligible_zone_tiers"].split(","))
            if trip_tier not in eligible_tiers:
                reasons.append("zone_not_eligible")

            # peak hours
            if camp["peak_hours_only"] == 1:
                if not is_peak(trip_start):
                    reasons.append("trip_not_in_peak_hours")

            # driver completed trips
            tc_key = (did, camp_sd, camp_ed)
            if tc_key not in trip_count_cache:
                tc_res = self.tools["count_driver_completed_trips"](
                    driver_id=did, start_date=camp_sd, end_date=camp_ed
                )
                trip_count_cache[tc_key] = tc_res["completed_trips"]
            if trip_count_cache[tc_key] < camp["min_completed_trips"]:
                reasons.append("insufficient_completed_trips")

            # driver online hours
            sess_key = (did, camp_sd, camp_ed)
            if sess_key not in session_cache:
                sess_res = self.tools["get_driver_sessions"](
                    driver_id=did, start_date=camp_sd, end_date=camp_ed
                )
                session_cache[sess_key] = sess_res["sessions"]
            total_hours = 0.0
            for sess in session_cache[sess_key]:
                if sess["session_status"] not in counted_statuses:
                    continue
                s = max(
                    datetime.strptime(sess["online_start"], "%Y-%m-%d %H:%M:%S"),
                    camp_start_dt,
                )
                e = min(
                    datetime.strptime(sess["online_end"], "%Y-%m-%d %H:%M:%S"),
                    camp_end_dt,
                )
                if e > s:
                    total_hours += (e - s).total_seconds() / 3600.0
            if total_hours < camp["min_online_hours"]:
                reasons.append("insufficient_online_hours")

            # driver rating
            dr = driver_ratings.get(did, {})
            camp_dates = []
            d = datetime.strptime(camp_sd, "%Y-%m-%d")
            end_d = datetime.strptime(camp_ed, "%Y-%m-%d")
            while d <= end_d:
                camp_dates.append(d.strftime("%Y-%m-%d"))
                d += timedelta(days=1)
            period_r = [dr[dt] for dt in camp_dates if dt in dr]
            avg_r = sum(period_r) / len(period_r) if period_r else 0.0
            if avg_r < camp["min_driver_rating"]:
                reasons.append("rating_below_minimum")

            # compute correct amount
            bonus = camp["bonus_per_trip"]
            zt_mult = tier_mult.get(trip_tier, 1.0)
            # surge
            trip_date_str = trip_start.strftime("%Y-%m-%d")
            surge_res = self.tools["get_surge_records"](
                zone_id=trip_zone, date=trip_date_str
            )
            surge_mult = 1.0
            for sr in surge_res["surge_records"]:
                ss = datetime.strptime(sr["surge_start"], "%Y-%m-%d %H:%M:%S")
                se = datetime.strptime(sr["surge_end"], "%Y-%m-%d %H:%M:%S")
                if ss <= trip_start <= se:
                    surge_mult = max(surge_mult, sr["surge_multiplier"])
            computed = round(bonus * zt_mult * surge_mult, rounding)

            if len(reasons) == 0:
                if abs(claim["claimed_amount"] - computed) > 0.01:
                    reasons.append("amount_mismatch")

            eligible = len(reasons) == 0
            adj_amount = computed if eligible else 0.0

            pre_results.append(
                {
                    "claim_id": claim["claim_id"],
                    "driver_id": did,
                    "campaign_id": cid,
                    "trip_id": tid,
                    "claimed_amount": claim["claimed_amount"],
                    "eligible": eligible,
                    "adjusted_amount": adj_amount,
                    "discrepancy_reasons": reasons,
                    "computed_amount": computed,
                }
            )

        # ---- Step 5: enforce per-driver cap ----
        dc_groups = defaultdict(list)
        for i, pr in enumerate(pre_results):
            if pr["eligible"]:
                dc_groups[(pr["driver_id"], pr["campaign_id"])].append(i)

        for (did, cid), indices in dc_groups.items():
            camp = campaign_cache[cid]
            cap = camp["max_payout_per_driver"]
            indices.sort(key=lambda i: pre_results[i]["claim_id"])
            cumulative = 0.0
            for idx in indices:
                amt = pre_results[idx]["adjusted_amount"]
                if cumulative + amt <= cap:
                    cumulative += amt
                else:
                    remainder = max(0.0, cap - cumulative)
                    pre_results[idx]["adjusted_amount"] = round(remainder, rounding)
                    if remainder < amt:
                        pre_results[idx]["discrepancy_reasons"].append(
                            "per_driver_cap_exceeded"
                        )
                        if remainder == 0.0:
                            pre_results[idx]["eligible"] = False
                    cumulative = cap

        # ---- Step 6: write report ----
        report_path = _os.path.join(ws, "adjusted_payout_report.csv")
        with open(report_path, "w", newline="") as f:
            writer = _csv.DictWriter(
                f,
                fieldnames=[
                    "claim_id",
                    "driver_id",
                    "campaign_id",
                    "trip_id",
                    "claimed_amount",
                    "eligible",
                    "adjusted_amount",
                    "discrepancy_reasons",
                ],
            )
            writer.writeheader()
            for pr in pre_results:
                reasons_str = (
                    ";".join(pr["discrepancy_reasons"])
                    if pr["discrepancy_reasons"]
                    else "none"
                )
                writer.writerow(
                    {
                        "claim_id": pr["claim_id"],
                        "driver_id": pr["driver_id"],
                        "campaign_id": pr["campaign_id"],
                        "trip_id": pr["trip_id"],
                        "claimed_amount": pr["claimed_amount"],
                        "eligible": pr["eligible"],
                        "adjusted_amount": pr["adjusted_amount"],
                        "discrepancy_reasons": reasons_str,
                    }
                )

        # ---- Step 7: build action summary ----
        total_processed = len(pre_results)
        total_approved = sum(1 for pr in pre_results if pr["eligible"])
        total_rejected = total_processed - total_approved
        total_claimed = round(sum(pr["claimed_amount"] for pr in pre_results), 2)
        total_adjusted = round(sum(pr["adjusted_amount"] for pr in pre_results), 2)

        action = (
            f"Payout validation complete. "
            f"Total claims processed: {total_processed}. "
            f"Approved: {total_approved}. "
            f"Rejected: {total_rejected}. "
            f"Total claimed amount: {total_claimed:.2f}. "
            f"Total adjusted payout: {total_adjusted:.2f}. "
            f"Report saved as adjusted_payout_report.csv."
        )

        return self.step(action)
