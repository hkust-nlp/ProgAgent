"""
Streetlight Maintenance Budget Allocation - Task Environment
"""

import csv
import json
import math
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Tuple


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

    # ── Tool Methods ─────────────────────────────────────────────────────

    @tool(
        description="List all zones with basic information. Returns zone_id, zone_name, district, population, area_sqkm, num_streetlights, and current_annual_budget.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_zones(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT zone_id, zone_name, district, population, area_sqkm, num_streetlights, current_annual_budget FROM zones ORDER BY zone_id")
        rows = c.fetchall()
        conn.close()
        return [
            {"zone_id": r[0], "zone_name": r[1], "district": r[2],
             "population": r[3], "area_sqkm": r[4],
             "num_streetlights": r[5], "current_annual_budget": r[6]}
            for r in rows
        ]

    @tool(
        description="Get work orders for a specific zone. Returns paginated results with order_id, light_id, issue_type, severity, date_reported, date_completed, repair_cost, technician_id, status, and parts_replaced. Maximum 20 results per page.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {"type": "integer", "description": "The zone ID to query"},
                "status_filter": {"type": "string", "description": "Optional filter: Completed, Pending, or In Progress", "enum": ["Completed", "Pending", "In Progress"]},
                "severity_filter": {"type": "string", "description": "Optional filter: Low, Medium, High, or Critical", "enum": ["Low", "Medium", "High", "Critical"]},
                "page": {"type": "integer", "description": "Page number, starting from 1. Default 1."},
            },
            "required": ["zone_id"],
        },
    )
    def get_work_orders(self, zone_id: int, status_filter: str = None,
                        severity_filter: str = None, page: int = 1) -> Dict:
        page_size = 20
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        query = "SELECT order_id, light_id, issue_type, severity, date_reported, date_completed, repair_cost, technician_id, status, parts_replaced FROM work_orders WHERE zone_id = ?"
        params = [zone_id]
        if status_filter:
            query += " AND status = ?"
            params.append(status_filter)
        if severity_filter:
            query += " AND severity = ?"
            params.append(severity_filter)
        query += " ORDER BY date_reported DESC"

        # Get total count
        count_q = query.replace(
            "SELECT order_id, light_id, issue_type, severity, date_reported, date_completed, repair_cost, technician_id, status, parts_replaced",
            "SELECT COUNT(*)"
        )
        c.execute(count_q, params)
        total = c.fetchone()[0]

        offset = (page - 1) * page_size
        query += f" LIMIT {page_size} OFFSET {offset}"
        c.execute(query, params)
        rows = c.fetchall()
        conn.close()

        return {
            "zone_id": zone_id,
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": math.ceil(total / page_size) if total > 0 else 1,
            "records": [
                {"order_id": r[0], "light_id": r[1], "issue_type": r[2],
                 "severity": r[3], "date_reported": r[4], "date_completed": r[5],
                 "repair_cost": r[6], "technician_id": r[7], "status": r[8],
                 "parts_replaced": r[9]}
                for r in rows
            ],
        }

    @tool(
        description="Get details for a specific streetlight by its ID. Returns light_id, zone_id, light_type, wattage, install_date, last_maintenance_date, status, and pole_material.",
        parameters={
            "type": "object",
            "properties": {
                "light_id": {"type": "integer", "description": "The streetlight ID"},
            },
            "required": ["light_id"],
        },
    )
    def get_streetlight_details(self, light_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT light_id, zone_id, light_type, wattage, install_date, last_maintenance_date, status, pole_material FROM streetlights WHERE light_id = ?", (light_id,))
        r = c.fetchone()
        conn.close()
        if not r:
            return {"error": f"No streetlight found with ID {light_id}"}
        return {"light_id": r[0], "zone_id": r[1], "light_type": r[2],
                "wattage": r[3], "install_date": r[4],
                "last_maintenance_date": r[5], "status": r[6], "pole_material": r[7]}

    @tool(
        description="Get energy consumption data for a specific zone in a given year. Returns monthly records with kwh_consumed, cost_per_kwh, total_cost, and peak_demand_kw.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {"type": "integer", "description": "The zone ID to query"},
                "year": {"type": "integer", "description": "The year to query (e.g. 2024)"},
            },
            "required": ["zone_id", "year"],
        },
    )
    def get_energy_data(self, zone_id: int, year: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT month, kwh_consumed, cost_per_kwh, total_cost, peak_demand_kw FROM energy_consumption WHERE zone_id = ? AND year = ? ORDER BY month",
            (zone_id, year),
        )
        rows = c.fetchall()
        conn.close()
        return {
            "zone_id": zone_id,
            "year": year,
            "records": [
                {"month": r[0], "kwh_consumed": r[1], "cost_per_kwh": r[2],
                 "total_cost": r[3], "peak_demand_kw": r[4]}
                for r in rows
            ],
        }

    @tool(
        description="Get citizen complaints for a zone. Returns paginated results with complaint_id, light_id, complaint_type, date_filed, date_resolved, priority, description, and resolved status. Maximum 20 per page.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {"type": "integer", "description": "The zone ID to query"},
                "resolved_filter": {"type": "integer", "description": "Optional: 0 for unresolved, 1 for resolved"},
                "page": {"type": "integer", "description": "Page number starting from 1. Default 1."},
            },
            "required": ["zone_id"],
        },
    )
    def get_complaints(self, zone_id: int, resolved_filter: int = None, page: int = 1) -> Dict:
        page_size = 20
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        query = "SELECT complaint_id, light_id, complaint_type, date_filed, date_resolved, priority, description, resolved FROM citizen_complaints WHERE zone_id = ?"
        params = [zone_id]
        if resolved_filter is not None:
            query += " AND resolved = ?"
            params.append(resolved_filter)
        query += " ORDER BY date_filed DESC"

        count_q = query.replace(
            "SELECT complaint_id, light_id, complaint_type, date_filed, date_resolved, priority, description, resolved",
            "SELECT COUNT(*)"
        )
        c.execute(count_q, params)
        total = c.fetchone()[0]

        offset = (page - 1) * page_size
        query += f" LIMIT {page_size} OFFSET {offset}"
        c.execute(query, params)
        rows = c.fetchall()
        conn.close()

        return {
            "zone_id": zone_id,
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": math.ceil(total / page_size) if total > 0 else 1,
            "records": [
                {"complaint_id": r[0], "light_id": r[1], "complaint_type": r[2],
                 "date_filed": r[3], "date_resolved": r[4], "priority": r[5],
                 "description": r[6], "resolved": bool(r[7])}
                for r in rows
            ],
        }

    @tool(
        description="Get traffic accident reports for a zone, filtered by year. Returns accident_id, date, time_of_day, severity, lighting_related, injuries, fatalities, nearest_light_id, and road_type.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {"type": "integer", "description": "The zone ID to query"},
                "year": {"type": "integer", "description": "The year to filter by"},
                "lighting_related_only": {"type": "boolean", "description": "If true, only return lighting-related accidents. Default false."},
            },
            "required": ["zone_id", "year"],
        },
    )
    def get_accident_reports(self, zone_id: int, year: int, lighting_related_only: bool = False) -> Dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        query = "SELECT accident_id, date, time_of_day, severity, lighting_related, injuries, fatalities, nearest_light_id, road_type FROM traffic_accidents WHERE zone_id = ? AND date LIKE ?"
        params = [zone_id, f"{year}-%"]
        if lighting_related_only:
            query += " AND lighting_related = 1"
        query += " ORDER BY date"
        c.execute(query, params)
        rows = c.fetchall()
        conn.close()
        return {
            "zone_id": zone_id,
            "year": year,
            "total_records": len(rows),
            "records": [
                {"accident_id": r[0], "date": r[1], "time_of_day": r[2],
                 "severity": r[3], "lighting_related": bool(r[4]),
                 "injuries": r[5], "fatalities": r[6],
                 "nearest_light_id": r[7], "road_type": r[8]}
                for r in rows
            ],
        }

    @tool(
        description="Get streetlight inventory statistics for a zone. Returns counts by light_type, status, pole_material, and average/min/max install year.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {"type": "integer", "description": "The zone ID to query"},
            },
            "required": ["zone_id"],
        },
    )
    def get_zone_light_stats(self, zone_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT light_type, COUNT(*) FROM streetlights WHERE zone_id = ? GROUP BY light_type", (zone_id,))
        by_type = {r[0]: r[1] for r in c.fetchall()}

        c.execute("SELECT status, COUNT(*) FROM streetlights WHERE zone_id = ? GROUP BY status", (zone_id,))
        by_status = {r[0]: r[1] for r in c.fetchall()}

        c.execute("SELECT pole_material, COUNT(*) FROM streetlights WHERE zone_id = ? GROUP BY pole_material", (zone_id,))
        by_material = {r[0]: r[1] for r in c.fetchall()}

        c.execute("SELECT AVG(CAST(SUBSTR(install_date, 1, 4) AS INTEGER)), MIN(CAST(SUBSTR(install_date, 1, 4) AS INTEGER)), MAX(CAST(SUBSTR(install_date, 1, 4) AS INTEGER)), COUNT(*) FROM streetlights WHERE zone_id = ?", (zone_id,))
        stats = c.fetchone()

        conn.close()
        return {
            "zone_id": zone_id,
            "total_lights": stats[3],
            "by_type": by_type,
            "by_status": by_status,
            "by_pole_material": by_material,
            "avg_install_year": round(stats[0], 1) if stats[0] else None,
            "min_install_year": stats[1],
            "max_install_year": stats[2],
        }

    @tool(
        description="Get a summary of work order statistics for a zone including counts by severity, status, issue type, total repair cost, and average repair cost.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {"type": "integer", "description": "The zone ID to query"},
                "year_from": {"type": "integer", "description": "Optional: start year filter (inclusive)"},
                "year_to": {"type": "integer", "description": "Optional: end year filter (inclusive)"},
            },
            "required": ["zone_id"],
        },
    )
    def get_work_order_summary(self, zone_id: int, year_from: int = None, year_to: int = None) -> Dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        base = "FROM work_orders WHERE zone_id = ?"
        params = [zone_id]
        if year_from:
            base += " AND date_reported >= ?"
            params.append(f"{year_from}-01-01")
        if year_to:
            base += " AND date_reported <= ?"
            params.append(f"{year_to}-12-31")

        c.execute(f"SELECT severity, COUNT(*) {base} GROUP BY severity", params)
        by_severity = {r[0]: r[1] for r in c.fetchall()}

        c.execute(f"SELECT status, COUNT(*) {base} GROUP BY status", params)
        by_status = {r[0]: r[1] for r in c.fetchall()}

        c.execute(f"SELECT issue_type, COUNT(*) {base} GROUP BY issue_type", params)
        by_issue = {r[0]: r[1] for r in c.fetchall()}

        c.execute(f"SELECT COUNT(*), SUM(repair_cost), AVG(repair_cost) {base}", params)
        agg = c.fetchone()

        conn.close()
        return {
            "zone_id": zone_id,
            "total_orders": agg[0],
            "total_repair_cost": round(agg[1], 2) if agg[1] else 0,
            "avg_repair_cost": round(agg[2], 2) if agg[2] else 0,
            "by_severity": by_severity,
            "by_status": by_status,
            "by_issue_type": by_issue,
        }

    @tool(
        description="Retrieve all streetlight install dates for a given zone. Returns a list of {light_id, install_date} for computing infrastructure age.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {"type": "integer", "description": "The zone ID to query"},
            },
            "required": ["zone_id"],
        },
    )
    def get_zone_install_dates(self, zone_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT light_id, install_date FROM streetlights WHERE zone_id = ? ORDER BY light_id", (zone_id,))
        rows = c.fetchall()
        conn.close()
        return {
            "zone_id": zone_id,
            "total": len(rows),
            "lights": [{"light_id": r[0], "install_date": r[1]} for r in rows],
        }

    # ── step: evaluate task completion ───────────────────────────────────

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # Compute ground truth
        gt = self._compute_ground_truth()

        # Criterion 1: repair_schedule.csv exists and has correct structure (15 pts)
        c1 = self._eval_repair_schedule(gt)
        eval_criteria["repair_schedule_structure"] = c1
        total_score += c1["score"]
        max_score += c1["max_score"]

        # Criterion 2: repair schedule ordering is correct (20 pts)
        c2 = self._eval_schedule_ordering(gt)
        eval_criteria["repair_schedule_ordering"] = c2
        total_score += c2["score"]
        max_score += c2["max_score"]

        # Criterion 3: budget_proposal.csv exists and has correct structure (15 pts)
        c3 = self._eval_budget_proposal_structure(gt)
        eval_criteria["budget_proposal_structure"] = c3
        total_score += c3["score"]
        max_score += c3["max_score"]

        # Criterion 4: budget allocations are correctly computed (20 pts)
        c4 = self._eval_budget_allocations(gt)
        eval_criteria["budget_allocations"] = c4
        total_score += c4["score"]
        max_score += c4["max_score"]

        # Criterion 5: zone risk rankings in response (15 pts)
        c5 = self._eval_risk_rankings(gt, action)
        eval_criteria["risk_rankings_in_response"] = c5
        total_score += c5["score"]
        max_score += c5["max_score"]

        # Criterion 6: composite risk scores accuracy (15 pts)
        c6 = self._eval_composite_scores(gt, action)
        eval_criteria["composite_risk_scores"] = c6
        total_score += c6["score"]
        max_score += c6["max_score"]

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, info

    def _compute_ground_truth(self) -> Dict:
        """Compute ground truth values for all evaluation criteria."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Load config files
        with open(os.path.join(self.workspace, "priority_weights.yaml")) as f:
            weights = __import__("yaml").safe_load(f)
        with open(os.path.join(self.workspace, "budget_rules.json")) as f:
            budget_rules = json.load(f)
        with open(os.path.join(self.workspace, "scoring_config.json")) as f:
            scoring_config = json.load(f)

        ref_start = scoring_config["reference_year_start"]
        ref_end = scoring_config["reference_year_end"]
        age_ref = scoring_config["age_reference_date"]
        energy_lookback = scoring_config["energy_lookback_months"]
        precision = scoring_config["composite_score_precision"]

        # Get zones
        c.execute("SELECT zone_id, zone_name, area_sqkm, num_streetlights FROM zones ORDER BY zone_id")
        zones = c.fetchall()
        zone_data = {z[0]: {"name": z[1], "area": z[2], "num_lights": z[3]} for z in zones}

        # 1. Failure rate per zone
        failure_rates = {}
        for zid in zone_data:
            c.execute(
                "SELECT COUNT(*) FROM work_orders WHERE zone_id = ? AND severity IN ('High', 'Critical') AND date_reported >= ? AND date_reported <= ?",
                (zid, f"{ref_start}-01-01", f"{ref_end}-12-31"),
            )
            high_crit_count = c.fetchone()[0]
            rate = min(100.0, (high_crit_count / zone_data[zid]["num_lights"]) * 100)
            failure_rates[zid] = rate

        # Normalize failure rates
        max_fr = max(failure_rates.values()) if max(failure_rates.values()) > 0 else 1
        failure_scores = {zid: (v / max_fr) * 100 for zid, v in failure_rates.items()}

        # 2. Complaint density per zone (unresolved)
        complaint_densities = {}
        for zid in zone_data:
            c.execute("SELECT COUNT(*) FROM citizen_complaints WHERE zone_id = ? AND resolved = 0", (zid,))
            unresolved = c.fetchone()[0]
            complaint_densities[zid] = unresolved / zone_data[zid]["area"]

        max_cd = max(complaint_densities.values()) if max(complaint_densities.values()) > 0 else 1
        complaint_scores = {zid: (v / max_cd) * 100 for zid, v in complaint_densities.items()}

        # 3. Accident risk score per zone
        acc_severity_scores = weights["accident_severity_scores"]
        lr_bonus = weights["lighting_related_bonus"]
        accident_totals = {}
        for zid in zone_data:
            c.execute(
                "SELECT severity, lighting_related FROM traffic_accidents WHERE zone_id = ? AND date >= ? AND date <= ?",
                (zid, f"{ref_start}-01-01", f"{ref_end}-12-31"),
            )
            rows = c.fetchall()
            total = 0
            for sev, lr in rows:
                if lr:
                    total += acc_severity_scores.get(sev, 0) + lr_bonus
            accident_totals[zid] = total

        max_at = max(accident_totals.values()) if max(accident_totals.values()) > 0 else 1
        accident_scores = {zid: (v / max_at) * 100 for zid, v in accident_totals.items()}

        # 4. Energy efficiency deviation
        # Most recent 12 months of data
        c.execute("SELECT MAX(year * 12 + month) FROM energy_consumption")
        max_ym = c.fetchone()[0]
        if max_ym is None:
            max_ym = 2025 * 12 + 12
        min_ym = max_ym - energy_lookback + 1

        energy_costs = {}
        for zid in zone_data:
            c.execute(
                "SELECT SUM(total_cost), COUNT(*) FROM energy_consumption WHERE zone_id = ? AND (year * 12 + month) >= ? AND (year * 12 + month) <= ?",
                (zid, min_ym, max_ym),
            )
            row = c.fetchone()
            total_cost = row[0] if row[0] else 0
            months = row[1] if row[1] else 1
            avg_monthly = total_cost / months if months > 0 else 0
            per_light = avg_monthly / zone_data[zid]["num_lights"] if zone_data[zid]["num_lights"] > 0 else 0
            energy_costs[zid] = per_light

        max_ec = max(energy_costs.values()) if max(energy_costs.values()) > 0 else 1
        energy_scores = {zid: (v / max_ec) * 100 for zid, v in energy_costs.items()}

        # 5. Infrastructure age
        age_ref_date = datetime.strptime(age_ref, "%Y-%m-%d")
        age_avgs = {}
        for zid in zone_data:
            c.execute("SELECT install_date FROM streetlights WHERE zone_id = ?", (zid,))
            dates = c.fetchall()
            ages = []
            for (d,) in dates:
                try:
                    install = datetime.strptime(d, "%Y-%m-%d")
                    age_years = (age_ref_date - install).days / 365.25
                    ages.append(age_years)
                except:
                    pass
            age_avgs[zid] = sum(ages) / len(ages) if ages else 0

        max_age = max(age_avgs.values()) if max(age_avgs.values()) > 0 else 1
        age_scores = {zid: (v / max_age) * 100 for zid, v in age_avgs.items()}

        # Composite scores
        w_fr = weights["failure_rate_weight"]
        w_cd = weights["complaint_density_weight"]
        w_ar = weights["accident_risk_weight"]
        w_ee = weights["energy_efficiency_weight"]
        w_ia = weights["infrastructure_age_weight"]

        composite_scores = {}
        for zid in zone_data:
            score = (
                w_fr * failure_scores[zid]
                + w_cd * complaint_scores[zid]
                + w_ar * accident_scores[zid]
                + w_ee * energy_scores[zid]
                + w_ia * age_scores[zid]
            )
            composite_scores[zid] = round(score, precision)

        # Rank zones by composite score descending
        ranked_zones = sorted(composite_scores.items(), key=lambda x: x[1], reverse=True)

        # Budget allocation
        total_budget = budget_rules["total_annual_budget"]
        emergency_pct = budget_rules["emergency_reserve_pct"]
        min_pct = budget_rules["minimum_zone_allocation_pct"]
        max_pct = budget_rules["maximum_zone_allocation_pct"]

        distributable = total_budget * (1 - emergency_pct / 100)
        total_risk = sum(composite_scores.values())

        allocations = {}
        if total_risk > 0:
            # Iterative capping
            remaining_budget = distributable
            capped = set()
            floored = set()
            zone_ids = list(zone_data.keys())

            for _ in range(10):  # iterate until stable
                uncapped_risk = sum(composite_scores[z] for z in zone_ids if z not in capped and z not in floored)
                changed = False
                for zid in zone_ids:
                    if zid in capped or zid in floored:
                        continue
                    prop_share = (composite_scores[zid] / total_risk) * 100 if total_risk > 0 else 100 / len(zone_ids)
                    if prop_share > max_pct:
                        allocations[zid] = distributable * max_pct / 100
                        capped.add(zid)
                        changed = True
                    elif prop_share < min_pct:
                        allocations[zid] = distributable * min_pct / 100
                        floored.add(zid)
                        changed = True
                if not changed:
                    break
                # Recalculate total_risk for uncapped
                total_risk = sum(composite_scores[z] for z in zone_ids if z not in capped and z not in floored)

            # Allocate remaining proportionally
            used = sum(allocations.get(z, 0) for z in capped | floored)
            remaining = distributable - used
            remaining_risk = sum(composite_scores[z] for z in zone_ids if z not in capped and z not in floored)
            for zid in zone_ids:
                if zid not in capped and zid not in floored:
                    if remaining_risk > 0:
                        allocations[zid] = round(remaining * composite_scores[zid] / remaining_risk, 2)
                    else:
                        allocations[zid] = round(remaining / (len(zone_ids) - len(capped) - len(floored)), 2)
                else:
                    allocations[zid] = round(allocations[zid], 2)

        # Tier assignment
        tier_defs = budget_rules["tier_definitions"]
        zone_tiers = {}
        for zid, score in composite_scores.items():
            if score >= tier_defs["critical"]["min_risk_score"]:
                zone_tiers[zid] = "critical"
            elif score >= tier_defs["high"]["min_risk_score"]:
                zone_tiers[zid] = "high"
            elif score >= tier_defs["medium"]["min_risk_score"]:
                zone_tiers[zid] = "medium"
            else:
                zone_tiers[zid] = "low"

        # Repair schedule: pending/in-progress orders ordered by zone risk then severity then date
        severity_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        c.execute(
            "SELECT order_id, light_id, zone_id, issue_type, severity, date_reported, repair_cost, status FROM work_orders WHERE status IN ('Pending', 'In Progress') ORDER BY date_reported"
        )
        pending_orders = c.fetchall()

        schedule = []
        for o in pending_orders:
            schedule.append({
                "order_id": o[0],
                "light_id": o[1],
                "zone_id": o[2],
                "zone_name": zone_data[o[2]]["name"],
                "issue_type": o[3],
                "severity": o[4],
                "date_reported": o[5],
                "repair_cost": o[6],
                "status": o[7],
                "zone_risk_score": composite_scores[o[2]],
                "tier": zone_tiers[o[2]],
                "response_days": tier_defs[zone_tiers[o[2]]]["response_days"],
            })

        schedule.sort(key=lambda x: (-x["zone_risk_score"], severity_order.get(x["severity"], 99), x["date_reported"]))

        conn.close()

        return {
            "zones": zone_data,
            "composite_scores": composite_scores,
            "ranked_zones": ranked_zones,
            "allocations": allocations,
            "zone_tiers": zone_tiers,
            "schedule": schedule,
            "total_budget": total_budget,
            "distributable": distributable,
            "emergency_reserve": total_budget * emergency_pct / 100,
        }

    def _eval_repair_schedule(self, gt) -> Dict:
        """Check repair_schedule.csv exists and has correct columns."""
        max_score = 15
        path = os.path.join(self.workspace, "repair_schedule.csv")
        if not os.path.exists(path):
            return {"passed": False, "score": 0, "max_score": max_score,
                    "reason": "repair_schedule.csv not found"}

        try:
            df = __import__("pandas").read_csv(path)
        except Exception as e:
            return {"passed": False, "score": 0, "max_score": max_score,
                    "reason": f"Cannot read repair_schedule.csv: {e}"}

        required_cols = {"order_id", "zone_name", "severity", "date_reported",
                         "repair_cost", "tier", "response_days"}
        actual_cols = set(df.columns)
        missing = required_cols - actual_cols
        if missing:
            return {"passed": False, "score": 5, "max_score": max_score,
                    "reason": f"Missing columns: {missing}"}

        expected_count = len(gt["schedule"])
        if len(df) != expected_count:
            return {"passed": False, "score": 8, "max_score": max_score,
                    "reason": f"Expected {expected_count} rows, got {len(df)}"}

        return {"passed": True, "score": max_score, "max_score": max_score}

    def _eval_schedule_ordering(self, gt) -> Dict:
        """Check repair schedule ordering is correct."""
        max_score = 20
        path = os.path.join(self.workspace, "repair_schedule.csv")
        if not os.path.exists(path):
            return {"passed": False, "score": 0, "max_score": max_score,
                    "reason": "repair_schedule.csv not found"}

        try:
            df = __import__("pandas").read_csv(path)
        except:
            return {"passed": False, "score": 0, "max_score": max_score,
                    "reason": "Cannot read file"}

        if "order_id" not in df.columns:
            return {"passed": False, "score": 0, "max_score": max_score,
                    "reason": "order_id column missing"}

        expected_order = [s["order_id"] for s in gt["schedule"]]
        actual_order = df["order_id"].tolist()

        if len(actual_order) == 0:
            return {"passed": False, "score": 0, "max_score": max_score,
                    "reason": "Empty schedule"}

        # Check how many are in correct position
        min_len = min(len(expected_order), len(actual_order))
        correct = sum(1 for i in range(min_len) if expected_order[i] == actual_order[i])
        ratio = correct / len(expected_order) if expected_order else 0

        if ratio >= 0.95:
            return {"passed": True, "score": max_score, "max_score": max_score}
        elif ratio >= 0.7:
            score = int(max_score * 0.6)
            return {"passed": False, "score": score, "max_score": max_score,
                    "reason": f"Ordering {ratio:.0%} correct"}
        elif ratio >= 0.4:
            score = int(max_score * 0.3)
            return {"passed": False, "score": score, "max_score": max_score,
                    "reason": f"Ordering {ratio:.0%} correct"}
        else:
            return {"passed": False, "score": 0, "max_score": max_score,
                    "reason": f"Ordering {ratio:.0%} correct"}

    def _eval_budget_proposal_structure(self, gt) -> Dict:
        """Check budget_proposal.csv structure."""
        max_score = 15
        path = os.path.join(self.workspace, "budget_proposal.csv")
        if not os.path.exists(path):
            return {"passed": False, "score": 0, "max_score": max_score,
                    "reason": "budget_proposal.csv not found"}

        try:
            df = __import__("pandas").read_csv(path)
        except Exception as e:
            return {"passed": False, "score": 0, "max_score": max_score,
                    "reason": f"Cannot read: {e}"}

        required_cols = {"zone_name", "composite_risk_score", "tier",
                         "allocated_budget", "allocation_pct"}
        actual_cols = set(df.columns)
        missing = required_cols - actual_cols
        if missing:
            return {"passed": False, "score": 5, "max_score": max_score,
                    "reason": f"Missing columns: {missing}"}

        if len(df) != len(gt["zones"]):
            return {"passed": False, "score": 8, "max_score": max_score,
                    "reason": f"Expected {len(gt['zones'])} zone rows, got {len(df)}"}

        return {"passed": True, "score": max_score, "max_score": max_score}

    def _eval_budget_allocations(self, gt) -> Dict:
        """Check budget allocation values."""
        max_score = 20
        path = os.path.join(self.workspace, "budget_proposal.csv")
        if not os.path.exists(path):
            return {"passed": False, "score": 0, "max_score": max_score,
                    "reason": "budget_proposal.csv not found"}

        try:
            df = __import__("pandas").read_csv(path)
        except:
            return {"passed": False, "score": 0, "max_score": max_score,
                    "reason": "Cannot read file"}

        if "zone_name" not in df.columns or "allocated_budget" not in df.columns:
            return {"passed": False, "score": 0, "max_score": max_score,
                    "reason": "Required columns missing"}

        # Map zone names to expected allocations
        name_to_id = {v["name"]: k for k, v in gt["zones"].items()}

        correct_alloc = 0
        correct_tier = 0
        total_zones = len(gt["zones"])

        for _, row in df.iterrows():
            zname = str(row.get("zone_name", ""))
            zid = name_to_id.get(zname)
            if zid is None:
                continue

            # Check allocation within 5% tolerance
            expected_alloc = gt["allocations"].get(zid, 0)
            actual_alloc = float(row.get("allocated_budget", 0))
            if expected_alloc > 0 and abs(actual_alloc - expected_alloc) / expected_alloc < 0.05:
                correct_alloc += 1
            elif expected_alloc == 0 and actual_alloc == 0:
                correct_alloc += 1

            # Check tier
            expected_tier = gt["zone_tiers"].get(zid, "")
            actual_tier = str(row.get("tier", "")).strip().lower()
            if actual_tier == expected_tier:
                correct_tier += 1

        alloc_ratio = correct_alloc / total_zones if total_zones > 0 else 0
        tier_ratio = correct_tier / total_zones if total_zones > 0 else 0

        score = 0
        # 12 pts for allocations, 8 pts for tiers
        score += int(12 * alloc_ratio)
        score += int(8 * tier_ratio)

        passed = score >= max_score * 0.9
        reason = None
        if not passed:
            reason = f"Allocation accuracy: {alloc_ratio:.0%}, tier accuracy: {tier_ratio:.0%}"

        return {"passed": passed, "score": score, "max_score": max_score, "reason": reason}

    def _eval_risk_rankings(self, gt, action: str) -> Dict:
        """Check that zone risk rankings are present in response."""
        max_score = 15
        ranked = gt["ranked_zones"]  # list of (zone_id, score) descending

        # Check if the response contains zone names in correct risk order
        zone_names_ranked = [gt["zones"][zid]["name"] for zid, _ in ranked]

        # Find positions of zone names in response
        positions = {}
        action_lower = action.lower()
        for name in zone_names_ranked:
            idx = action_lower.find(name.lower())
            if idx >= 0:
                positions[name] = idx

        if len(positions) < len(zone_names_ranked) // 2:
            return {"passed": False, "score": 0, "max_score": max_score,
                    "reason": "Too few zone names found in response"}

        # Check if the top 3 zones are correctly identified
        top3_expected = zone_names_ranked[:3]
        # Find the first occurrence of "rank" or "risk" context in response
        found_top3 = 0
        for name in top3_expected:
            if name.lower() in action_lower:
                found_top3 += 1

        if found_top3 == 3:
            score = max_score
        elif found_top3 == 2:
            score = int(max_score * 0.7)
        elif found_top3 == 1:
            score = int(max_score * 0.4)
        else:
            score = 0

        return {"passed": score >= max_score * 0.9, "score": score, "max_score": max_score,
                "reason": None if score >= max_score * 0.9 else f"Found {found_top3}/3 top zones"}

    def _eval_composite_scores(self, gt, action: str) -> Dict:
        """Check that composite risk scores are reported accurately."""
        max_score = 15
        ranked = gt["ranked_zones"]

        correct = 0
        found = 0
        for zid, expected_score in ranked:
            zname = gt["zones"][zid]["name"]
            # Look for the score near the zone name in the response
            import re
            # Search for patterns like "Zone-A: 65.32" or "Zone-A ... 65.32"
            pattern = re.escape(zname) + r'[^0-9]{0,50}?(\d+\.\d{1,2})'
            matches = re.findall(pattern, action, re.IGNORECASE)
            if matches:
                found += 1
                for m in matches:
                    try:
                        val = float(m)
                        if abs(val - expected_score) < 1.0:
                            correct += 1
                            break
                    except:
                        pass

        total_zones = len(ranked)
        if found == 0:
            return {"passed": False, "score": 0, "max_score": max_score,
                    "reason": "No composite scores found in response"}

        ratio = correct / total_zones
        score = int(max_score * ratio)
        passed = ratio >= 0.75

        return {"passed": passed, "score": score, "max_score": max_score,
                "reason": None if passed else f"Correct scores: {correct}/{total_zones}"}

    # ── verify: end-to-end solvability ───────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml as _yaml

        # Step 1: Read config files from workspace
        with open(os.path.join(self.workspace, "priority_weights.yaml")) as f:
            weights = _yaml.safe_load(f)
        with open(os.path.join(self.workspace, "budget_rules.json")) as f:
            budget_rules = json.load(f)
        with open(os.path.join(self.workspace, "scoring_config.json")) as f:
            scoring_config = json.load(f)
        with open(os.path.join(self.workspace, "maintenance_policy.md")) as f:
            policy = f.read()

        ref_start = scoring_config["reference_year_start"]
        ref_end = scoring_config["reference_year_end"]
        age_ref_str = scoring_config["age_reference_date"]
        energy_lookback = scoring_config["energy_lookback_months"]
        precision = scoring_config["composite_score_precision"]
        age_ref_date = datetime.strptime(age_ref_str, "%Y-%m-%d")

        # Step 2: Get zone list via tool
        zones_data = self.tools["list_zones"]()
        zone_ids = [z["zone_id"] for z in zones_data]
        zone_map = {z["zone_id"]: z for z in zones_data}

        # Step 3: Compute failure rate per zone using tools
        failure_rates = {}
        for zid in zone_ids:
            summary = self.tools["get_work_order_summary"](zone_id=zid, year_from=ref_start, year_to=ref_end)
            high_crit = summary["by_severity"].get("High", 0) + summary["by_severity"].get("Critical", 0)
            num_lights = zone_map[zid]["num_streetlights"]
            failure_rates[zid] = min(100.0, (high_crit / num_lights) * 100)

        max_fr = max(failure_rates.values()) if max(failure_rates.values()) > 0 else 1
        failure_scores = {zid: (v / max_fr) * 100 for zid, v in failure_rates.items()}

        # Step 4: Complaint density using tools
        complaint_densities = {}
        for zid in zone_ids:
            result = self.tools["get_complaints"](zone_id=zid, resolved_filter=0, page=1)
            total_unresolved = result["total_records"]
            area = zone_map[zid]["area_sqkm"]
            complaint_densities[zid] = total_unresolved / area

        max_cd = max(complaint_densities.values()) if max(complaint_densities.values()) > 0 else 1
        complaint_scores = {zid: (v / max_cd) * 100 for zid, v in complaint_densities.items()}

        # Step 5: Accident risk scores using tools
        acc_severity_scores = weights["accident_severity_scores"]
        lr_bonus = weights["lighting_related_bonus"]
        accident_totals = {}
        for zid in zone_ids:
            total = 0
            for year in range(ref_start, ref_end + 1):
                result = self.tools["get_accident_reports"](zone_id=zid, year=year, lighting_related_only=True)
                for acc in result["records"]:
                    total += acc_severity_scores.get(acc["severity"], 0) + lr_bonus
            accident_totals[zid] = total

        max_at = max(accident_totals.values()) if max(accident_totals.values()) > 0 else 1
        accident_scores = {zid: (v / max_at) * 100 for zid, v in accident_totals.items()}

        # Step 6: Energy efficiency using tools
        # Discover available years by probing, then use the most recent 12 months
        energy_costs = {}
        # First, find max year-month across all zones
        all_records_by_zone = {}
        for zid in zone_ids:
            all_records_by_zone[zid] = []
            for year in range(2020, 2030):
                result = self.tools["get_energy_data"](zone_id=zid, year=year)
                for rec in result["records"]:
                    all_records_by_zone[zid].append((year, rec["month"], rec["total_cost"]))

        # Find global max year-month
        all_ym = []
        for zid in zone_ids:
            for y, m, _ in all_records_by_zone[zid]:
                all_ym.append(y * 12 + m)
        max_ym = max(all_ym) if all_ym else 2025 * 12 + 12
        min_ym = max_ym - energy_lookback + 1

        for zid in zone_ids:
            total_cost = 0
            months_count = 0
            for y, m, cost in all_records_by_zone[zid]:
                ym = y * 12 + m
                if min_ym <= ym <= max_ym:
                    total_cost += cost
                    months_count += 1
            avg_monthly = total_cost / months_count if months_count > 0 else 0
            per_light = avg_monthly / zone_map[zid]["num_streetlights"] if zone_map[zid]["num_streetlights"] > 0 else 0
            energy_costs[zid] = per_light

        max_ec = max(energy_costs.values()) if max(energy_costs.values()) > 0 else 1
        energy_scores = {zid: (v / max_ec) * 100 for zid, v in energy_costs.items()}

        # Step 7: Infrastructure age using tools
        age_avgs = {}
        for zid in zone_ids:
            result = self.tools["get_zone_install_dates"](zone_id=zid)
            ages = []
            for light in result["lights"]:
                try:
                    install = datetime.strptime(light["install_date"], "%Y-%m-%d")
                    age_years = (age_ref_date - install).days / 365.25
                    ages.append(age_years)
                except:
                    pass
            age_avgs[zid] = sum(ages) / len(ages) if ages else 0

        max_age = max(age_avgs.values()) if max(age_avgs.values()) > 0 else 1
        age_scores = {zid: (v / max_age) * 100 for zid, v in age_avgs.items()}

        # Step 8: Compute composite scores
        w_fr = weights["failure_rate_weight"]
        w_cd = weights["complaint_density_weight"]
        w_ar = weights["accident_risk_weight"]
        w_ee = weights["energy_efficiency_weight"]
        w_ia = weights["infrastructure_age_weight"]

        composite_scores = {}
        for zid in zone_ids:
            score = (
                w_fr * failure_scores[zid]
                + w_cd * complaint_scores[zid]
                + w_ar * accident_scores[zid]
                + w_ee * energy_scores[zid]
                + w_ia * age_scores[zid]
            )
            composite_scores[zid] = round(score, precision)

        ranked = sorted(composite_scores.items(), key=lambda x: x[1], reverse=True)

        # Step 9: Budget allocation
        total_budget = budget_rules["total_annual_budget"]
        emergency_pct = budget_rules["emergency_reserve_pct"]
        min_pct = budget_rules["minimum_zone_allocation_pct"]
        max_pct = budget_rules["maximum_zone_allocation_pct"]
        distributable = total_budget * (1 - emergency_pct / 100)
        total_risk = sum(composite_scores.values())

        tier_defs = budget_rules["tier_definitions"]

        zone_tiers = {}
        for zid, score in composite_scores.items():
            if score >= tier_defs["critical"]["min_risk_score"]:
                zone_tiers[zid] = "critical"
            elif score >= tier_defs["high"]["min_risk_score"]:
                zone_tiers[zid] = "high"
            elif score >= tier_defs["medium"]["min_risk_score"]:
                zone_tiers[zid] = "medium"
            else:
                zone_tiers[zid] = "low"

        # Iterative capping
        allocations = {}
        capped = set()
        floored = set()
        for _ in range(10):
            changed = False
            for zid in zone_ids:
                if zid in capped or zid in floored:
                    continue
                prop_share = (composite_scores[zid] / total_risk) * 100 if total_risk > 0 else 100 / len(zone_ids)
                if prop_share > max_pct:
                    allocations[zid] = distributable * max_pct / 100
                    capped.add(zid)
                    changed = True
                elif prop_share < min_pct:
                    allocations[zid] = distributable * min_pct / 100
                    floored.add(zid)
                    changed = True
            if not changed:
                break
            total_risk = sum(composite_scores[z] for z in zone_ids if z not in capped and z not in floored)

        used = sum(allocations.get(z, 0) for z in capped | floored)
        remaining = distributable - used
        remaining_risk = sum(composite_scores[z] for z in zone_ids if z not in capped and z not in floored)
        for zid in zone_ids:
            if zid not in capped and zid not in floored:
                if remaining_risk > 0:
                    allocations[zid] = round(remaining * composite_scores[zid] / remaining_risk, 2)
                else:
                    allocations[zid] = round(remaining / (len(zone_ids) - len(capped) - len(floored)), 2)
            else:
                allocations[zid] = round(allocations[zid], 2)

        # Step 10: Build repair schedule
        severity_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        schedule = []
        for zid in zone_ids:
            page = 1
            while True:
                result = self.tools["get_work_orders"](zone_id=zid, page=page)
                for wo in result["records"]:
                    if wo["status"] in ("Pending", "In Progress"):
                        schedule.append({
                            "order_id": wo["order_id"],
                            "light_id": wo["light_id"],
                            "zone_id": zid,
                            "zone_name": zone_map[zid]["zone_name"],
                            "issue_type": wo["issue_type"],
                            "severity": wo["severity"],
                            "date_reported": wo["date_reported"],
                            "repair_cost": wo["repair_cost"],
                            "status": wo["status"],
                            "zone_risk_score": composite_scores[zid],
                            "tier": zone_tiers[zid],
                            "response_days": tier_defs[zone_tiers[zid]]["response_days"],
                        })
                if page >= result["total_pages"]:
                    break
                page += 1

        schedule.sort(key=lambda x: (-x["zone_risk_score"], severity_order.get(x["severity"], 99), x["date_reported"]))

        # Step 11: Write deliverables
        # repair_schedule.csv
        import pandas as pd
        sched_df = pd.DataFrame(schedule)
        sched_cols = ["order_id", "zone_name", "severity", "date_reported",
                      "repair_cost", "tier", "response_days", "zone_risk_score",
                      "light_id", "issue_type", "status"]
        for col in sched_cols:
            if col not in sched_df.columns:
                sched_df[col] = ""
        sched_df[sched_cols].to_csv(os.path.join(self.workspace, "repair_schedule.csv"), index=False)

        # budget_proposal.csv
        budget_rows = []
        for zid, score in ranked:
            zname = zone_map[zid]["zone_name"]
            alloc = allocations[zid]
            alloc_pct = round(alloc / distributable * 100, 2)
            budget_rows.append({
                "zone_name": zname,
                "composite_risk_score": score,
                "tier": zone_tiers[zid],
                "allocated_budget": round(alloc, 2),
                "allocation_pct": alloc_pct,
            })
        budget_df = pd.DataFrame(budget_rows)
        budget_df.to_csv(os.path.join(self.workspace, "budget_proposal.csv"), index=False)

        # Step 12: Construct final response
        response_lines = ["Streetlight Maintenance Budget Allocation Analysis", ""]
        response_lines.append("Zone Risk Rankings (highest to lowest):")
        for zid, score in ranked:
            zname = zone_map[zid]["zone_name"]
            tier = zone_tiers[zid]
            alloc = allocations[zid]
            response_lines.append(
                f"  {zname}: {score:.2f} (tier: {tier}, allocated: ${alloc:,.2f})"
            )

        response_lines.append("")
        response_lines.append(f"Total Budget: ${total_budget:,.2f}")
        response_lines.append(f"Emergency Reserve: ${total_budget * emergency_pct / 100:,.2f}")
        response_lines.append(f"Distributable Budget: ${distributable:,.2f}")
        response_lines.append("")
        response_lines.append(f"Total pending/in-progress work orders scheduled: {len(schedule)}")
        response_lines.append("Repair schedule saved to repair_schedule.csv")
        response_lines.append("Budget proposal saved to budget_proposal.csv")

        action = "\n".join(response_lines)
        return self.step(action)
