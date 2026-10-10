"""
Environment for short-term rental compliance sweep task.
"""

import sqlite3
import os
import json
import csv
import math
from typing import Tuple, Dict, List, Any

import yaml
import pandas as pd


# --- Decorator (keep unchanged) ---
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

    # ================================================================ #
    #  Tool methods                                                     #
    # ================================================================ #

    @tool(
        description=(
            "Search for rental listings with a given status. Returns a paginated list "
            "of listings (listing_id, property_id, platform, nightly_rate, listing_status). "
            "Page numbering starts at 1. Each page contains up to page_size results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "inactive", "suspended"],
                    "description": "Filter listings by this status.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20).",
                },
            },
            "required": ["status", "page", "page_size"],
        },
    )
    def search_listings(self, status: str, page: int, page_size: int) -> dict:
        page_size = min(int(page_size), 20)
        page = max(int(page), 1)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(
            "SELECT COUNT(*) as c FROM rental_listings WHERE listing_status = ?",
            (status,),
        ).fetchone()["c"]
        rows = conn.execute(
            "SELECT listing_id, property_id, platform, nightly_rate, listing_status "
            "FROM rental_listings WHERE listing_status = ? "
            "ORDER BY listing_id LIMIT ? OFFSET ?",
            (status, page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "results": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "Retrieve detailed information for a single property by its property_id. "
            "Returns address, owner_name, owner_type, property_type, assessed_value, "
            "tax_status, zoning_code, neighborhood, year_built, and square_feet."
        ),
        parameters={
            "type": "object",
            "properties": {
                "property_id": {
                    "type": "string",
                    "description": "The property identifier, e.g. PROP-00001.",
                },
            },
            "required": ["property_id"],
        },
    )
    def get_property_info(self, property_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM properties WHERE property_id = ?", (property_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Property {property_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Check occupancy-permit records for a property. Returns a list of all "
            "permits on file (permit_id, permit_type, issue_date, expiry_date, "
            "permit_status). An empty list means no permits exist."
        ),
        parameters={
            "type": "object",
            "properties": {
                "property_id": {
                    "type": "string",
                    "description": "The property identifier.",
                },
            },
            "required": ["property_id"],
        },
    )
    def get_permit_status(self, property_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT permit_id, permit_type, issue_date, expiry_date, permit_status "
            "FROM occupancy_permits WHERE property_id = ? ORDER BY expiry_date DESC",
            (property_id,),
        ).fetchall()
        conn.close()
        return {"property_id": property_id, "permits": [dict(r) for r in rows]}

    @tool(
        description=(
            "Retrieve monthly utility-consumption records for a property within a date "
            "range (inclusive). Each record contains billing_month, electricity_kwh, "
            "water_gallons, and gas_therms."
        ),
        parameters={
            "type": "object",
            "properties": {
                "property_id": {
                    "type": "string",
                    "description": "The property identifier.",
                },
                "start_month": {
                    "type": "string",
                    "description": "Start month inclusive, YYYY-MM format.",
                },
                "end_month": {
                    "type": "string",
                    "description": "End month inclusive, YYYY-MM format.",
                },
            },
            "required": ["property_id", "start_month", "end_month"],
        },
    )
    def get_utility_history(self, property_id: str, start_month: str, end_month: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT billing_month, electricity_kwh, water_gallons, gas_therms "
            "FROM utility_records "
            "WHERE property_id = ? AND billing_month >= ? AND billing_month <= ? "
            "ORDER BY billing_month",
            (property_id, start_month, end_month),
        ).fetchall()
        conn.close()
        return {"property_id": property_id, "records": [dict(r) for r in rows]}

    @tool(
        description=(
            "Get full details for a specific rental listing by its listing_id. "
            "Returns listing_id, property_id, platform, listing_title, nightly_rate, "
            "min_stay_nights, avg_occupancy_pct, review_count, listing_created_date, "
            "and listing_status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "listing_id": {
                    "type": "string",
                    "description": "The listing identifier, e.g. LST-00001.",
                },
            },
            "required": ["listing_id"],
        },
    )
    def get_listing_details(self, listing_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM rental_listings WHERE listing_id = ?", (listing_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Listing {listing_id} not found."}
        return dict(row)

    # ================================================================ #
    #  Ground-truth computation (used by step and verify)               #
    # ================================================================ #

    def _compute_ground_truth(self) -> List[dict]:
        """Return the expected list of violation cases, sorted by risk_score desc then property_id asc."""
        conn = sqlite3.connect(self.db_path)

        # Load config files from workspace
        with open(os.path.join(self.workspace, "enforcement_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "zoning_map.json")) as f:
            zoning_map = json.load(f)
        baselines_df = pd.read_csv(os.path.join(self.workspace, "utility_baselines.csv"))

        base_scores = config["violation_base_scores"]
        mods = config["modifiers"]
        cap = config["risk_score_cap"]
        actions = config["recommended_actions"]

        # Properties with active listings
        active_listings_df = pd.read_sql(
            "SELECT * FROM rental_listings WHERE listing_status = 'active'", conn
        )
        if active_listings_df.empty:
            conn.close()
            return []

        # Group listings by property
        listings_by_prop = active_listings_df.groupby("property_id")

        # Property info
        active_pids = active_listings_df["property_id"].unique().tolist()
        placeholders = ",".join(["?"] * len(active_pids))
        props_df = pd.read_sql(
            f"SELECT * FROM properties WHERE property_id IN ({placeholders})",
            conn,
            params=active_pids,
        )

        # Permits
        permits_df = pd.read_sql(
            f"SELECT * FROM occupancy_permits WHERE property_id IN ({placeholders})",
            conn,
            params=active_pids,
        )

        # Utility records
        utility_df = pd.read_sql(
            f"SELECT * FROM utility_records WHERE property_id IN ({placeholders})",
            conn,
            params=active_pids,
        )
        conn.close()

        # Complaint counts from workspace
        complaint_counts = self._count_complaints_by_address()

        # Platform intel (estimated annual revenue by property)
        revenue_by_prop = self._load_platform_revenue()

        cases = []
        for _, prop in props_df.iterrows():
            pid = prop["property_id"]
            zone = prop["zoning_code"]
            zone_info = zoning_map.get(zone, {})

            # Determine violation type
            if not zone_info.get("str_permitted", True):
                violation_type = "zoning_violation"
            elif not zone_info.get("requires_permit", False):
                # e.g. C1 — no permit needed, no violation
                continue
            else:
                # Zone requires permit — check permit records
                prop_permits = permits_df[permits_df["property_id"] == pid]
                str_permits = prop_permits[prop_permits["permit_type"] == "str_permit"]
                if str_permits.empty:
                    violation_type = "no_permit"
                else:
                    active_str = str_permits[str_permits["permit_status"] == "active"]
                    if not active_str.empty:
                        continue  # Has valid permit — compliant
                    expired = str_permits[str_permits["permit_status"] == "expired"]
                    if not expired.empty:
                        violation_type = "expired_permit"
                    else:
                        # revoked or pending
                        violation_type = "no_permit"

            # Compute risk score
            score = base_scores.get(violation_type, 0)

            # Complaint modifier
            addr = prop["address"]
            n_complaints = complaint_counts.get(addr, 0)
            if n_complaints >= mods["complaint_threshold"]:
                score += mods["complaint_bonus"]

            # Utility anomaly modifier
            prop_util = utility_df[utility_df["property_id"] == pid]
            has_anomaly = False
            if not prop_util.empty:
                baseline_row = baselines_df[
                    (baselines_df["property_type"] == prop["property_type"])
                    & (baselines_df["sqft_min"] <= prop["square_feet"])
                    & (baselines_df["sqft_max"] >= prop["square_feet"])
                ]
                if not baseline_row.empty:
                    bl = baseline_row.iloc[0]
                    sqft = prop["square_feet"]
                    avg_kwh = prop_util["electricity_kwh"].mean()
                    avg_gal = prop_util["water_gallons"].mean()
                    avg_thm = prop_util["gas_therms"].mean()
                    expected_kwh = bl["monthly_kwh_per_sqft"] * sqft
                    expected_gal = bl["monthly_gal_per_sqft"] * sqft
                    expected_thm = bl["monthly_therm_per_sqft"] * sqft
                    threshold = mods["utility_spike_threshold"]
                    if (
                        avg_kwh > expected_kwh * threshold
                        or avg_gal > expected_gal * threshold
                        or avg_thm > expected_thm * threshold
                    ):
                        has_anomaly = True
            if has_anomaly:
                score += mods["utility_anomaly_bonus"]

            # Extra listing modifier
            n_active = len(listings_by_prop.get_group(pid))
            if n_active > 1:
                score += mods["extra_listing_bonus"] * (n_active - 1)

            score = min(score, cap)

            # Recommended action
            if score >= actions["high"]["min_score"]:
                rec_action = actions["high"]["action"]
            elif score >= actions["medium"]["min_score"]:
                rec_action = actions["medium"]["action"]
            else:
                rec_action = actions["low"]["action"]

            # Revenue
            rev = revenue_by_prop.get(pid, 0.0)

            cases.append({
                "property_id": pid,
                "address": addr,
                "owner_name": prop["owner_name"],
                "violation_type": violation_type,
                "risk_score": score,
                "complaint_count": n_complaints,
                "utility_anomaly": "yes" if has_anomaly else "no",
                "active_listing_count": int(n_active),
                "estimated_annual_revenue": round(rev, 2),
                "recommended_action": rec_action,
            })

        # Sort: risk_score desc, then property_id asc
        cases.sort(key=lambda c: (-c["risk_score"], c["property_id"]))
        return cases

    def _count_complaints_by_address(self) -> dict:
        """Read all complaint_batch_*.csv files and return {address: count}."""
        counts: dict = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("complaint_batch_") and fname.endswith(".csv"):
                fpath = os.path.join(self.workspace, fname)
                df = pd.read_csv(fpath)
                for addr in df["property_address"]:
                    counts[addr] = counts.get(addr, 0) + 1
        return counts

    def _load_platform_revenue(self) -> dict:
        """Read platform_intel_*.json and return {property_id: total_estimated_annual_revenue}."""
        rev: dict = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("platform_intel_") and fname.endswith(".json"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath) as f:
                    data = json.load(f)
                for entry in data:
                    pid = entry["property_id"]
                    rev[pid] = rev.get(pid, 0.0) + entry.get("estimated_annual_revenue", 0.0)
        return rev

    # ================================================================ #
    #  Evaluation                                                       #
    # ================================================================ #

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
        expected_pids = {c["property_id"] for c in expected}
        expected_map = {c["property_id"]: c for c in expected}
        n_expected = len(expected)

        criteria: Dict[str, dict] = {}

        # ---- Criterion 1: CSV exists with correct columns (10 pts) ----
        csv_path = os.path.join(self.workspace, "compliance_cases.csv")
        required_cols = [
            "property_id", "address", "owner_name", "violation_type",
            "risk_score", "recommended_action", "evidence_summary",
        ]
        csv_ok = False
        agent_rows = []
        if os.path.isfile(csv_path):
            try:
                df = pd.read_csv(csv_path)
                actual_cols = [c.strip().lower() for c in df.columns]
                if all(rc in actual_cols for rc in required_cols):
                    csv_ok = True
                    # Normalize column names
                    df.columns = [c.strip().lower() for c in df.columns]
                    agent_rows = df.to_dict("records")
            except Exception:
                pass

        criteria["csv_structure"] = {
            "passed": csv_ok,
            "score": 10 if csv_ok else 0,
            "max_score": 10,
            "reason": "" if csv_ok else "compliance_cases.csv missing or has wrong columns",
        }

        # ---- Criterion 2: Correct property IDs identified (25 pts) ----
        agent_pids = set()
        for row in agent_rows:
            pid = str(row.get("property_id", "")).strip()
            if pid:
                agent_pids.add(pid)

        if n_expected > 0 and len(agent_pids) > 0:
            tp = len(agent_pids & expected_pids)
            precision = tp / len(agent_pids) if agent_pids else 0
            recall = tp / n_expected
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            id_score = round(f1 * 25, 1)
        elif n_expected == 0 and len(agent_pids) == 0:
            id_score = 25.0
        else:
            id_score = 0.0

        criteria["property_identification"] = {
            "passed": id_score >= 25.0,
            "score": id_score,
            "max_score": 25,
            "reason": f"F1={id_score/25:.3f}" if id_score < 25 else "",
        }

        # ---- Criterion 3: Correct violation types (20 pts) ----
        agent_map = {}
        for row in agent_rows:
            pid = str(row.get("property_id", "")).strip()
            if pid:
                agent_map[pid] = row

        correct_types = 0
        checked = 0
        for pid in agent_pids & expected_pids:
            checked += 1
            agent_vtype = str(agent_map.get(pid, {}).get("violation_type", "")).strip().lower()
            expected_vtype = expected_map[pid]["violation_type"].lower()
            if agent_vtype == expected_vtype:
                correct_types += 1

        type_score = round((correct_types / checked * 20) if checked > 0 else 0, 1)
        criteria["violation_types"] = {
            "passed": type_score >= 20.0,
            "score": type_score,
            "max_score": 20,
            "reason": f"{correct_types}/{checked} correct" if type_score < 20 else "",
        }

        # ---- Criterion 4: Risk scores within ±5 (15 pts) ----
        correct_scores = 0
        score_checked = 0
        for pid in agent_pids & expected_pids:
            score_checked += 1
            try:
                agent_score = float(agent_map[pid].get("risk_score", -999))
                exp_score = expected_map[pid]["risk_score"]
                if abs(agent_score - exp_score) <= 5:
                    correct_scores += 1
            except (ValueError, TypeError):
                pass

        risk_score_pts = round((correct_scores / score_checked * 15) if score_checked > 0 else 0, 1)
        criteria["risk_scores"] = {
            "passed": risk_score_pts >= 15.0,
            "score": risk_score_pts,
            "max_score": 15,
            "reason": f"{correct_scores}/{score_checked} within tolerance" if risk_score_pts < 15 else "",
        }

        # ---- Criterion 5: Correct recommended actions (15 pts) ----
        correct_actions = 0
        action_checked = 0
        for pid in agent_pids & expected_pids:
            action_checked += 1
            agent_act = str(agent_map.get(pid, {}).get("recommended_action", "")).strip().lower()
            exp_act = expected_map[pid]["recommended_action"].lower()
            if agent_act == exp_act:
                correct_actions += 1

        action_pts = round((correct_actions / action_checked * 15) if action_checked > 0 else 0, 1)
        criteria["recommended_actions"] = {
            "passed": action_pts >= 15.0,
            "score": action_pts,
            "max_score": 15,
            "reason": f"{correct_actions}/{action_checked} correct" if action_pts < 15 else "",
        }

        # ---- Criterion 6: Response summary accuracy (15 pts) ----
        # Check total count (5 pts), violation breakdown (5 pts), top-3 (5 pts)
        summary_pts = 0.0
        action_lower = action.lower() if action else ""

        # Total count
        if str(n_expected) in action_lower:
            summary_pts += 5.0

        # Violation type breakdown
        type_counts: dict = {}
        for c in expected:
            vt = c["violation_type"]
            type_counts[vt] = type_counts.get(vt, 0) + 1
        breakdown_ok = 0
        for vt, cnt in type_counts.items():
            # Look for patterns like "no_permit: 5" or "no_permit — 5" or "5 no_permit"
            if vt in action_lower and str(cnt) in action_lower:
                breakdown_ok += 1
        if type_counts and breakdown_ok == len(type_counts):
            summary_pts += 5.0
        elif type_counts and breakdown_ok > 0:
            summary_pts += round(5.0 * breakdown_ok / len(type_counts), 1)

        # Top-3 highest risk
        top3_expected = [c["property_id"] for c in expected[:3]]
        top3_found = sum(1 for pid in top3_expected if pid in action_lower.upper())
        # Case-insensitive property_id check
        top3_found = 0
        for pid in top3_expected:
            if pid.lower() in action_lower:
                top3_found += 1
        if top3_found == len(top3_expected):
            summary_pts += 5.0
        elif top3_found > 0:
            summary_pts += round(5.0 * top3_found / max(len(top3_expected), 1), 1)

        criteria["response_summary"] = {
            "passed": summary_pts >= 15.0,
            "score": summary_pts,
            "max_score": 15,
            "reason": f"scored {summary_pts}/15" if summary_pts < 15 else "",
        }

        total = sum(c["score"] for c in criteria.values())
        max_total = sum(c["max_score"] for c in criteria.values())

        return total / max_total, {
            "eval_criteria": criteria,
            "total_score": total,
            "max_score": max_total,
        }

    # ================================================================ #
    #  Self-verification                                                #
    # ================================================================ #

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
        import yaml as _yaml

        tool_calls = 0

        def call_tool(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        # 1. Read workspace config files
        with open(os.path.join(self.workspace, "enforcement_config.yaml")) as f:
            config = _yaml.safe_load(f)
        with open(os.path.join(self.workspace, "zoning_map.json")) as f:
            zoning_map = json.load(f)
        baselines_df = pd.read_csv(os.path.join(self.workspace, "utility_baselines.csv"))

        base_scores = config["violation_base_scores"]
        mods = config["modifiers"]
        cap = config["risk_score_cap"]
        actions_cfg = config["recommended_actions"]

        # 2. Read complaint files to build address→count map
        complaint_counts: dict = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("complaint_batch_") and fname.endswith(".csv"):
                df = pd.read_csv(os.path.join(self.workspace, fname))
                for addr in df["property_address"]:
                    complaint_counts[addr] = complaint_counts.get(addr, 0) + 1

        # 3. Read platform intel for revenue
        revenue_by_prop: dict = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("platform_intel_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                for entry in data:
                    pid = entry["property_id"]
                    revenue_by_prop[pid] = revenue_by_prop.get(pid, 0.0) + entry.get(
                        "estimated_annual_revenue", 0.0
                    )

        # 4. Paginate through all active listings
        all_active_listings = []
        page = 1
        while True:
            result = call_tool("search_listings", status="active", page=page, page_size=20)
            all_active_listings.extend(result["results"])
            if page * 20 >= result["total"]:
                break
            page += 1

        # Group by property_id
        listings_by_prop: dict = {}
        for lst in all_active_listings:
            pid = lst["property_id"]
            listings_by_prop.setdefault(pid, []).append(lst)

        # 5. For each property with active listings, check violation status
        cases = []
        for pid in sorted(listings_by_prop.keys()):
            prop_info = call_tool("get_property_info", property_id=pid)
            if "error" in prop_info:
                continue

            zone = prop_info["zoning_code"]
            zone_info = zoning_map.get(zone, {})

            # Determine violation
            if not zone_info.get("str_permitted", True):
                violation_type = "zoning_violation"
            elif not zone_info.get("requires_permit", False):
                continue  # No permit required (e.g., C1) — not a violation
            else:
                permit_result = call_tool("get_permit_status", property_id=pid)
                str_permits = [
                    p for p in permit_result["permits"] if p["permit_type"] == "str_permit"
                ]
                if not str_permits:
                    violation_type = "no_permit"
                else:
                    active_str = [p for p in str_permits if p["permit_status"] == "active"]
                    if active_str:
                        continue  # Compliant
                    expired = [p for p in str_permits if p["permit_status"] == "expired"]
                    if expired:
                        violation_type = "expired_permit"
                    else:
                        violation_type = "no_permit"

            # For R1 properties, still need permit call for evidence but skip if already zoning
            if violation_type == "zoning_violation":
                permit_result = call_tool("get_permit_status", property_id=pid)

            # Risk score computation
            score = base_scores.get(violation_type, 0)

            # Complaints
            addr = prop_info["address"]
            n_complaints = complaint_counts.get(addr, 0)
            if n_complaints >= mods["complaint_threshold"]:
                score += mods["complaint_bonus"]

            # Utility anomaly
            util_result = call_tool(
                "get_utility_history",
                property_id=pid,
                start_month="2025-01",
                end_month="2025-12",
            )
            has_anomaly = False
            if util_result["records"]:
                sqft = prop_info["square_feet"]
                ptype = prop_info["property_type"]
                bl_match = baselines_df[
                    (baselines_df["property_type"] == ptype)
                    & (baselines_df["sqft_min"] <= sqft)
                    & (baselines_df["sqft_max"] >= sqft)
                ]
                if not bl_match.empty:
                    bl = bl_match.iloc[0]
                    avg_kwh = sum(r["electricity_kwh"] for r in util_result["records"]) / len(
                        util_result["records"]
                    )
                    avg_gal = sum(r["water_gallons"] for r in util_result["records"]) / len(
                        util_result["records"]
                    )
                    avg_thm = sum(r["gas_therms"] for r in util_result["records"]) / len(
                        util_result["records"]
                    )
                    threshold = mods["utility_spike_threshold"]
                    if (
                        avg_kwh > bl["monthly_kwh_per_sqft"] * sqft * threshold
                        or avg_gal > bl["monthly_gal_per_sqft"] * sqft * threshold
                        or avg_thm > bl["monthly_therm_per_sqft"] * sqft * threshold
                    ):
                        has_anomaly = True

            if has_anomaly:
                score += mods["utility_anomaly_bonus"]

            # Extra listing bonus
            n_active = len(listings_by_prop[pid])
            if n_active > 1:
                score += mods["extra_listing_bonus"] * (n_active - 1)

            score = min(score, cap)

            # Recommended action
            if score >= actions_cfg["high"]["min_score"]:
                rec_action = actions_cfg["high"]["action"]
            elif score >= actions_cfg["medium"]["min_score"]:
                rec_action = actions_cfg["medium"]["action"]
            else:
                rec_action = actions_cfg["low"]["action"]

            rev = revenue_by_prop.get(pid, 0.0)

            evidence_parts = [
                f"Violation: {violation_type}",
                f"Complaints: {n_complaints}",
                f"Utility anomaly: {'yes' if has_anomaly else 'no'}",
                f"Active listings: {n_active}",
                f"Est. annual revenue: ${rev:,.2f}",
            ]

            cases.append({
                "property_id": pid,
                "address": addr,
                "owner_name": prop_info["owner_name"],
                "violation_type": violation_type,
                "risk_score": score,
                "complaint_count": n_complaints,
                "utility_anomaly": "yes" if has_anomaly else "no",
                "active_listing_count": n_active,
                "estimated_annual_revenue": round(rev, 2),
                "recommended_action": rec_action,
                "evidence_summary": "; ".join(evidence_parts),
            })

        # Sort by risk_score desc, then property_id asc
        cases.sort(key=lambda c: (-c["risk_score"], c["property_id"]))

        # Write compliance_cases.csv
        csv_path = os.path.join(self.workspace, "compliance_cases.csv")
        fieldnames = [
            "property_id", "address", "owner_name", "violation_type",
            "risk_score", "recommended_action", "evidence_summary",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for case in cases:
                writer.writerow({k: case[k] for k in fieldnames})

        # Build response summary
        total_cases = len(cases)
        type_counts: dict = {}
        for c in cases:
            vt = c["violation_type"]
            type_counts[vt] = type_counts.get(vt, 0) + 1

        top3 = cases[:3]

        summary_lines = [
            f"Total compliance violation cases identified: {total_cases}",
            "",
            "Violation type breakdown:",
        ]
        for vt in sorted(type_counts.keys()):
            summary_lines.append(f"  {vt}: {type_counts[vt]}")
        summary_lines.append("")
        summary_lines.append("Top 3 highest risk properties:")
        for c in top3:
            summary_lines.append(
                f"  {c['property_id']} (risk_score={c['risk_score']}, "
                f"violation={c['violation_type']}, address={c['address']})"
            )

        action_str = "\n".join(summary_lines)

        print(f"Tool calls made: {tool_calls}")
        assert tool_calls >= 15, f"Only {tool_calls} tool calls; need at least 15"

        return self.step(action_str)
