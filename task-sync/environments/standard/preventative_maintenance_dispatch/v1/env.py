"""
Fleet Preventative Maintenance Task - Environment
Defines tools, evaluation, and verification for maintenance dispatch scheduling.
"""
import csv
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

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

    # ── Tool Methods ────────────────────────────────────────────────────────

    @tool(
        description=(
            "List vehicles in the fleet with optional filtering by depot and/or "
            "category.  Returns a paginated list (20 vehicles per page)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "depot_id": {
                    "type": "string",
                    "description": "Filter by depot (e.g. 'North', 'Central', 'South'). Omit for all depots.",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by vehicle category (sedan, suv, truck, van, bus). Omit for all.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based, default 1).",
                },
            },
            "required": [],
        },
    )
    def list_vehicles(self, depot_id: str = None, category: str = None, page: int = 1):
        page_size = 20
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        q = "SELECT vehicle_id, make, model, year, category, depot_id FROM vehicles WHERE 1=1"
        params = []
        if depot_id:
            q += " AND depot_id = ?"
            params.append(depot_id)
        if category:
            q += " AND category = ?"
            params.append(category)
        q += " ORDER BY vehicle_id"
        rows = conn.execute(q, params).fetchall()
        conn.close()

        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start: start + page_size]
        return {
            "vehicles": [dict(r) for r in page_rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": start + page_size < total,
        }

    @tool(
        description="Get full details for a single vehicle by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "vehicle_id": {
                    "type": "string",
                    "description": "Vehicle identifier, e.g. 'V0001'.",
                },
            },
            "required": ["vehicle_id"],
        },
    )
    def get_vehicle_details(self, vehicle_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM vehicles WHERE vehicle_id = ?", (vehicle_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Vehicle {vehicle_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Retrieve all maintenance rules applicable to a given vehicle category. "
            "Each rule includes mileage and engine-hours intervals, priority base, "
            "required certification level, and estimated duration."
        ),
        parameters={
            "type": "object",
            "properties": {
                "vehicle_category": {
                    "type": "string",
                    "description": "Vehicle category (sedan, suv, truck, van, bus).",
                },
            },
            "required": ["vehicle_category"],
        },
    )
    def get_maintenance_rules(self, vehicle_category: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM maintenance_rules WHERE vehicle_category = ? ORDER BY rule_id",
            (vehicle_category,),
        ).fetchall()
        conn.close()
        return {"rules": [dict(r) for r in rows]}

    @tool(
        description=(
            "Get the service history for a specific vehicle.  Returns all past "
            "maintenance records including maintenance type, service date, mileage "
            "and engine hours at service, and the technician who performed it."
        ),
        parameters={
            "type": "object",
            "properties": {
                "vehicle_id": {
                    "type": "string",
                    "description": "Vehicle identifier, e.g. 'V0001'.",
                },
            },
            "required": ["vehicle_id"],
        },
    )
    def get_service_history(self, vehicle_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM service_history WHERE vehicle_id = ? ORDER BY service_date DESC",
            (vehicle_id,),
        ).fetchall()
        conn.close()
        return {"vehicle_id": vehicle_id, "records": [dict(r) for r in rows]}

    @tool(
        description=(
            "Check parts availability for a given maintenance type.  Returns the "
            "overall status ('ready', 'low_stock', or 'backordered') and details "
            "for each required part."
        ),
        parameters={
            "type": "object",
            "properties": {
                "maintenance_type": {
                    "type": "string",
                    "description": "Maintenance type name (e.g. 'oil_change').",
                },
            },
            "required": ["maintenance_type"],
        },
    )
    def check_parts_availability(self, maintenance_type: str):
        base_type = re.sub(r"_tier\d+$", "", maintenance_type)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT part_id, part_name, quantity_on_hand, reorder_point "
            "FROM parts_inventory WHERE compatible_types = ?",
            (base_type,),
        ).fetchall()
        conn.close()

        if not rows:
            return {"maintenance_type": maintenance_type, "status": "ready", "parts": []}

        any_backordered = False
        any_low = False
        parts_list = []
        for r in rows:
            r = dict(r)
            if r["quantity_on_hand"] == 0:
                any_backordered = True
                r["status"] = "backordered"
            elif r["quantity_on_hand"] <= r["reorder_point"]:
                any_low = True
                r["status"] = "low_stock"
            else:
                r["status"] = "available"
            parts_list.append(r)

        if any_backordered:
            overall = "backordered"
        elif any_low:
            overall = "low_stock"
        else:
            overall = "ready"

        return {"maintenance_type": maintenance_type, "status": overall, "parts": parts_list}

    @tool(
        description=(
            "List technicians with optional filtering by depot and/or minimum "
            "certification level.  Returns a paginated list (20 per page)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "depot_id": {
                    "type": "string",
                    "description": "Filter by depot. Omit for all.",
                },
                "min_cert_level": {
                    "type": "integer",
                    "description": "Minimum certification level (1-5). Omit for all.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based, default 1).",
                },
            },
            "required": [],
        },
    )
    def list_technicians(self, depot_id: str = None, min_cert_level: int = None, page: int = 1):
        page_size = 20
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        q = "SELECT * FROM technicians WHERE 1=1"
        params = []
        if depot_id:
            q += " AND depot_id = ?"
            params.append(depot_id)
        if min_cert_level is not None:
            q += " AND cert_level >= ?"
            params.append(min_cert_level)
        q += " ORDER BY tech_id"
        rows = conn.execute(q, params).fetchall()
        conn.close()

        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start: start + page_size]
        return {
            "technicians": [dict(r) for r in page_rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": start + page_size < total,
        }

    @tool(
        description="Get full details for a single technician by ID.",
        parameters={
            "type": "object",
            "properties": {
                "tech_id": {
                    "type": "string",
                    "description": "Technician identifier, e.g. 'T0001'.",
                },
            },
            "required": ["tech_id"],
        },
    )
    def get_technician_details(self, tech_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM technicians WHERE tech_id = ?", (tech_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Technician {tech_id} not found."}
        return dict(row)

    # ── Ground-truth computation (shared by step & verify) ──────────────────

    def _read_workspace_telemetry(self) -> Dict[str, Dict]:
        """Read all telemetry CSVs from workspace → {vehicle_id: {odometer_miles, engine_hours}}."""
        telemetry = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("telemetry_batch_") and fname.endswith(".csv"):
                path = os.path.join(self.workspace, fname)
                with open(path, newline="") as f:
                    for row in csv.DictReader(f):
                        telemetry[row["vehicle_id"]] = {
                            "odometer_miles": int(row["odometer_miles"]),
                            "engine_hours": int(row["engine_hours"]),
                        }
        return telemetry

    def _read_workspace_reservations(self) -> Dict[str, set]:
        """Read all reservation JSONs → {vehicle_id: set of ISO date strings within sched week}."""
        # Load scheduling week dates
        sc_path = os.path.join(self.workspace, "scheduling_constraints.json")
        with open(sc_path) as f:
            sc = json.load(f)
        week_dates_set = set(sc["available_days"])

        reservations: Dict[str, set] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("reservations_") and fname.endswith(".json"):
                path = os.path.join(self.workspace, fname)
                with open(path) as f:
                    entries = json.load(f)
                for entry in entries:
                    vid = entry["vehicle_id"]
                    start = datetime.strptime(entry["start_date"], "%Y-%m-%d")
                    end = datetime.strptime(entry["end_date"], "%Y-%m-%d")
                    d = start
                    while d <= end:
                        ds = d.strftime("%Y-%m-%d")
                        if ds in week_dates_set:
                            reservations.setdefault(vid, set()).add(ds)
                        d += timedelta(days=1)
        return reservations

    def _read_workspace_policy(self):
        with open(os.path.join(self.workspace, "maintenance_policy.yaml")) as f:
            return yaml.safe_load(f)

    def _read_workspace_schedule_config(self):
        with open(os.path.join(self.workspace, "scheduling_constraints.json")) as f:
            return json.load(f)

    def _compute_ground_truth(self):
        """Compute expected dispatch list using direct DB access + workspace files."""
        telemetry = self._read_workspace_telemetry()
        reservations = self._read_workspace_reservations()
        policy = self._read_workspace_policy()
        sched = self._read_workspace_schedule_config()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # All vehicles
        vehicles = [dict(r) for r in conn.execute("SELECT * FROM vehicles ORDER BY vehicle_id").fetchall()]
        # Rules by category
        rules_by_cat: Dict[str, list] = {}
        for r in conn.execute("SELECT * FROM maintenance_rules ORDER BY rule_id").fetchall():
            r = dict(r)
            rules_by_cat.setdefault(r["vehicle_category"], []).append(r)
        # Service history → most recent per (vehicle, mtype)
        last_service: Dict[str, Dict[str, dict]] = {}
        for r in conn.execute("SELECT * FROM service_history ORDER BY service_date DESC").fetchall():
            r = dict(r)
            vid, mt = r["vehicle_id"], r["maintenance_type"]
            last_service.setdefault(vid, {})
            if mt not in last_service[vid]:
                last_service[vid][mt] = r
        # Technicians
        all_techs = [dict(r) for r in conn.execute("SELECT * FROM technicians ORDER BY tech_id").fetchall()]
        conn.close()

        due_threshold = float(policy["due_threshold"])
        critical_threshold = float(policy["critical_threshold"])
        std_mult = float(policy["standard_multiplier"])
        crit_mult = float(policy["critical_multiplier"])
        no_hist_ratio = float(policy["no_history_overdue_ratio"])

        # Collect all due items
        due_items = []
        for v in vehicles:
            vid = v["vehicle_id"]
            if vid not in telemetry:
                continue
            cur = telemetry[vid]
            cat = v["category"]
            for rule in rules_by_cat.get(cat, []):
                mt = rule["maintenance_type"]
                svc = last_service.get(vid, {}).get(mt)
                if svc:
                    mi_ratio = (cur["odometer_miles"] - svc["mileage_at_service"]) / rule["mileage_interval"]
                    eh_ratio = (cur["engine_hours"] - svc["engine_hours_at_service"]) / rule["engine_hours_interval"]
                    overdue_ratio = max(mi_ratio, eh_ratio)
                else:
                    overdue_ratio = no_hist_ratio

                if overdue_ratio >= due_threshold:
                    mult = crit_mult if overdue_ratio >= critical_threshold else std_mult
                    urgency_score = round(overdue_ratio * rule["priority_base"] * mult, 2)
                    due_items.append({
                        "vehicle_id": vid,
                        "maintenance_type": mt,
                        "urgency_score": urgency_score,
                        "overdue_ratio": overdue_ratio,
                        "required_cert_level": rule["required_cert_level"],
                        "estimated_duration_hours": rule["estimated_duration_hours"],
                        "depot_id": v["depot_id"],
                    })

        # Sort: urgency DESC, vehicle_id ASC, maintenance_type ASC
        due_items.sort(key=lambda x: (-x["urgency_score"], x["vehicle_id"], x["maintenance_type"]))

        # Parts cache
        parts_cache = {}
        conn2 = sqlite3.connect(self.db_path)
        conn2.row_factory = sqlite3.Row
        for item in due_items:
            mt = item["maintenance_type"]
            if mt not in parts_cache:
                base_type = re.sub(r"_tier\d+$", "", mt)
                rows = conn2.execute(
                    "SELECT part_id, part_name, quantity_on_hand, reorder_point "
                    "FROM parts_inventory WHERE compatible_types = ?",
                    (base_type,),
                ).fetchall()
                any_bo = any(r["quantity_on_hand"] == 0 for r in rows)
                any_low = any(0 < r["quantity_on_hand"] <= r["reorder_point"] for r in rows)
                if any_bo:
                    parts_cache[mt] = "backordered"
                elif any_low:
                    parts_cache[mt] = "low_stock"
                else:
                    parts_cache[mt] = "ready"
        conn2.close()

        # Schedule
        week_dates = sched["available_days"]
        max_per_day = int(sched["max_dispatches_per_day"])
        max_tech_h_day = float(sched["max_hours_per_technician_per_day"])

        day_count = {d: 0 for d in week_dates}
        tech_day_h = {t["tech_id"]: {d: 0.0 for d in week_dates} for t in all_techs}
        tech_week_h = {t["tech_id"]: 0.0 for t in all_techs}

        dispatch = []
        rank = 1
        for item in due_items:
            v_res = reservations.get(item["vehicle_id"], set())
            scheduled = False
            for day in week_dates:
                if day in v_res:
                    continue
                if day_count[day] >= max_per_day:
                    continue
                eligible = []
                for t in all_techs:
                    if t["depot_id"] != item["depot_id"]:
                        continue
                    if t["cert_level"] < item["required_cert_level"]:
                        continue
                    if tech_day_h[t["tech_id"]][day] + item["estimated_duration_hours"] > max_tech_h_day:
                        continue
                    if tech_week_h[t["tech_id"]] + item["estimated_duration_hours"] > t["max_weekly_hours"]:
                        continue
                    eligible.append(t)
                if not eligible:
                    continue
                eligible.sort(key=lambda t: (t["hourly_rate"], t["tech_id"]))
                chosen = eligible[0]

                dispatch.append({
                    "priority_rank": rank,
                    "vehicle_id": item["vehicle_id"],
                    "maintenance_type": item["maintenance_type"],
                    "urgency_score": f"{item['urgency_score']:.2f}",
                    "assigned_tech_id": chosen["tech_id"],
                    "scheduled_day": day,
                    "estimated_duration_hours": f"{item['estimated_duration_hours']:.1f}",
                    "parts_status": parts_cache.get(item["maintenance_type"], "ready"),
                })
                day_count[day] += 1
                tech_day_h[chosen["tech_id"]][day] += item["estimated_duration_hours"]
                tech_week_h[chosen["tech_id"]] += item["estimated_duration_hours"]
                rank += 1
                scheduled = True
                break

        return dispatch, policy

    # ── Evaluation ──────────────────────────────────────────────────────────

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
        expected_dispatch, policy = self._compute_ground_truth()
        criteria = {}

        EXPECTED_COLS = [
            "priority_rank", "vehicle_id", "maintenance_type", "urgency_score",
            "assigned_tech_id", "scheduled_day", "estimated_duration_hours", "parts_status",
        ]

        # ── 1. File format (10 pts) ───────────────────────────────────────
        csv_path = os.path.join(self.workspace, "dispatch_list.csv")
        agent_rows = []
        fmt_ok = False
        if os.path.isfile(csv_path):
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames or []
                if cols == EXPECTED_COLS:
                    fmt_ok = True
                    for row in reader:
                        agent_rows.append(row)
        criteria["dispatch_file_format"] = {
            "passed": fmt_ok,
            "score": 10 if fmt_ok else 0,
            "max_score": 10,
            "reason": None if fmt_ok else "dispatch_list.csv missing or wrong columns",
        }

        if not fmt_ok:
            # Can't evaluate further
            total = sum(c["score"] for c in criteria.values())
            max_total = 100
            return total / max_total, {
                "eval_criteria": criteria,
                "total_score": total,
                "max_score": max_total,
            }

        # Build lookup for expected dispatch
        exp_lookup = {}  # (vehicle_id, mtype) -> expected row
        for er in expected_dispatch:
            exp_lookup[(er["vehicle_id"], er["maintenance_type"])] = er

        agent_lookup = {}
        for ar in agent_rows:
            agent_lookup[(ar["vehicle_id"], ar["maintenance_type"])] = ar

        # ── 2. Vehicle coverage (15 pts) ──────────────────────────────────
        exp_keys = set(exp_lookup.keys())
        agent_keys = set(agent_lookup.keys())
        if len(exp_keys) == 0:
            cov_frac = 1.0
        else:
            cov_frac = len(exp_keys & agent_keys) / len(exp_keys)
        cov_score = round(15 * cov_frac)
        criteria["vehicle_coverage"] = {
            "passed": cov_frac >= 0.95,
            "score": cov_score,
            "max_score": 15,
            "reason": None if cov_frac >= 0.95 else f"coverage {cov_frac:.2%}",
        }

        # ── 3. Urgency scores (15 pts) ────────────────────────────────────
        matched = exp_keys & agent_keys
        score_correct = 0
        for key in matched:
            exp_s = exp_lookup[key]["urgency_score"]
            try:
                agt_s = f"{float(agent_lookup[key]['urgency_score']):.2f}"
            except (ValueError, KeyError):
                agt_s = ""
            if agt_s == exp_s:
                score_correct += 1
        if len(matched) == 0:
            urg_frac = 0.0
        else:
            urg_frac = score_correct / len(matched)
        urg_pts = round(15 * urg_frac)
        criteria["urgency_scores"] = {
            "passed": urg_frac >= 0.95,
            "score": urg_pts,
            "max_score": 15,
            "reason": None if urg_frac >= 0.95 else f"accuracy {urg_frac:.2%}",
        }

        # ── 4. Priority ranking (15 pts) ──────────────────────────────────
        exp_order = [(r["vehicle_id"], r["maintenance_type"]) for r in expected_dispatch]
        agt_order = [(r["vehicle_id"], r["maintenance_type"]) for r in agent_rows]
        rank_ok = exp_order == agt_order
        criteria["priority_ranking"] = {
            "passed": rank_ok,
            "score": 15 if rank_ok else 0,
            "max_score": 15,
            "reason": None if rank_ok else "dispatch order does not match expected ranking",
        }

        # ── 5. Technician validity (15 pts) ───────────────────────────────
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        tech_map = {}
        for r in conn.execute("SELECT * FROM technicians").fetchall():
            tech_map[r["tech_id"]] = dict(r)
        vehicle_map = {}
        for r in conn.execute("SELECT * FROM vehicles").fetchall():
            vehicle_map[r["vehicle_id"]] = dict(r)
        rules_all = {}
        for r in conn.execute("SELECT * FROM maintenance_rules").fetchall():
            r = dict(r)
            rules_all.setdefault(r["vehicle_category"], {})[r["maintenance_type"]] = r
        conn.close()

        tech_valid_count = 0
        tech_total = len(agent_rows)
        for ar in agent_rows:
            vid = ar["vehicle_id"]
            mt = ar["maintenance_type"]
            tid = ar["assigned_tech_id"]
            v_info = vehicle_map.get(vid, {})
            t_info = tech_map.get(tid)
            rule_info = rules_all.get(v_info.get("category", ""), {}).get(mt)
            if t_info and rule_info and v_info:
                if (t_info["cert_level"] >= rule_info["required_cert_level"]
                        and t_info["depot_id"] == v_info["depot_id"]):
                    tech_valid_count += 1
        tech_frac = tech_valid_count / max(1, tech_total)
        tech_pts = round(15 * tech_frac)
        criteria["technician_validity"] = {
            "passed": tech_frac >= 0.95,
            "score": tech_pts,
            "max_score": 15,
            "reason": None if tech_frac >= 0.95 else f"valid {tech_frac:.2%}",
        }

        # ── 6. Parts status (10 pts) ──────────────────────────────────────
        parts_correct = 0
        for key in matched:
            if agent_lookup[key].get("parts_status") == exp_lookup[key]["parts_status"]:
                parts_correct += 1
        parts_frac = parts_correct / max(1, len(matched))
        parts_pts = round(10 * parts_frac)
        criteria["parts_status"] = {
            "passed": parts_frac >= 0.95,
            "score": parts_pts,
            "max_score": 10,
            "reason": None if parts_frac >= 0.95 else f"accuracy {parts_frac:.2%}",
        }

        # ── 7. Scheduling validity (10 pts) ───────────────────────────────
        reservations = self._read_workspace_reservations()
        sched = self._read_workspace_schedule_config()
        week_dates = set(sched["available_days"])
        max_per_day = int(sched["max_dispatches_per_day"])

        day_counts: Dict[str, int] = {}
        sched_violations = 0
        for ar in agent_rows:
            sd = ar["scheduled_day"]
            vid = ar["vehicle_id"]
            if sd not in week_dates:
                sched_violations += 1
                continue
            if sd in reservations.get(vid, set()):
                sched_violations += 1
            day_counts[sd] = day_counts.get(sd, 0) + 1

        for d, cnt in day_counts.items():
            if cnt > max_per_day:
                sched_violations += cnt - max_per_day

        sched_ok = sched_violations == 0
        criteria["scheduling_validity"] = {
            "passed": sched_ok,
            "score": 10 if sched_ok else max(0, 10 - sched_violations * 2),
            "max_score": 10,
            "reason": None if sched_ok else f"{sched_violations} scheduling violations",
        }

        # ── 8. Response summary (10 pts) ──────────────────────────────────
        tier_crit_thresh = float(policy["urgency_tiers"]["critical"]["min_score"])
        tier_high_thresh = float(policy["urgency_tiers"]["high"]["min_score"])

        exp_total_dispatches = len(expected_dispatch)
        exp_total_hours = sum(float(r["estimated_duration_hours"]) for r in expected_dispatch)
        exp_critical = sum(1 for r in expected_dispatch if float(r["urgency_score"]) >= tier_crit_thresh)
        exp_high = sum(
            1 for r in expected_dispatch
            if tier_high_thresh <= float(r["urgency_score"]) < tier_crit_thresh
        )
        exp_routine = exp_total_dispatches - exp_critical - exp_high

        summary_pts = 0
        # Check total dispatches
        if re.search(rf"Total dispatches:\s*{exp_total_dispatches}\b", action):
            summary_pts += 3
        # Check total hours
        exp_hours_str = f"{exp_total_hours:.1f}"
        if re.search(rf"Total estimated hours:\s*{re.escape(exp_hours_str)}\b", action):
            summary_pts += 3
        # Check tier breakdown
        tier_pat = rf"Critical:\s*{exp_critical}\b.*High:\s*{exp_high}\b.*Routine:\s*{exp_routine}\b"
        if re.search(tier_pat, action):
            summary_pts += 4

        criteria["response_summary"] = {
            "passed": summary_pts == 10,
            "score": summary_pts,
            "max_score": 10,
            "reason": None if summary_pts == 10 else "summary values do not match expected",
        }

        total = sum(c["score"] for c in criteria.values())
        max_total = sum(c["max_score"] for c in criteria.values())
        return total / max_total, {
            "eval_criteria": criteria,
            "total_score": total,
            "max_score": max_total,
        }

    # ── Verification ────────────────────────────────────────────────────────

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
        # ── 1. Read workspace files ─────────────────────────────────────
        telemetry = self._read_workspace_telemetry()
        reservations = self._read_workspace_reservations()
        policy = self._read_workspace_policy()
        sched = self._read_workspace_schedule_config()

        due_threshold = float(policy["due_threshold"])
        critical_threshold = float(policy["critical_threshold"])
        std_mult = float(policy["standard_multiplier"])
        crit_mult = float(policy["critical_multiplier"])
        no_hist_ratio = float(policy["no_history_overdue_ratio"])

        # ── 2. Gather all vehicles via tool (paginated) ─────────────────
        all_vehicles = []
        page = 1
        while True:
            result = self.tools["list_vehicles"](page=page)
            all_vehicles.extend(result["vehicles"])
            if not result["has_more"]:
                break
            page += 1

        # ── 3. Get maintenance rules per category ───────────────────────
        categories_seen = sorted(set(v["category"] for v in all_vehicles))
        rules_by_cat = {}
        for cat in categories_seen:
            res = self.tools["get_maintenance_rules"](vehicle_category=cat)
            rules_by_cat[cat] = res["rules"]

        # ── 4. For each vehicle, get service history & compute overdue ──
        due_items = []
        for v in all_vehicles:
            vid = v["vehicle_id"]
            if vid not in telemetry:
                continue
            cur = telemetry[vid]

            hist_res = self.tools["get_service_history"](vehicle_id=vid)
            last_svc = {}
            for rec in hist_res.get("records", []):
                mt = rec["maintenance_type"]
                if mt not in last_svc or rec["service_date"] > last_svc[mt]["service_date"]:
                    last_svc[mt] = rec

            for rule in rules_by_cat.get(v["category"], []):
                mt = rule["maintenance_type"]
                if mt in last_svc:
                    mi_ratio = (cur["odometer_miles"] - last_svc[mt]["mileage_at_service"]) / rule["mileage_interval"]
                    eh_ratio = (cur["engine_hours"] - last_svc[mt]["engine_hours_at_service"]) / rule["engine_hours_interval"]
                    overdue_ratio = max(mi_ratio, eh_ratio)
                else:
                    overdue_ratio = no_hist_ratio

                if overdue_ratio >= due_threshold:
                    mult = crit_mult if overdue_ratio >= critical_threshold else std_mult
                    urgency_score = round(overdue_ratio * rule["priority_base"] * mult, 2)
                    due_items.append({
                        "vehicle_id": vid,
                        "maintenance_type": mt,
                        "urgency_score": urgency_score,
                        "overdue_ratio": overdue_ratio,
                        "required_cert_level": rule["required_cert_level"],
                        "estimated_duration_hours": rule["estimated_duration_hours"],
                        "depot_id": v["depot_id"],
                    })

        # ── 5. Sort ─────────────────────────────────────────────────────
        due_items.sort(key=lambda x: (-x["urgency_score"], x["vehicle_id"], x["maintenance_type"]))

        # ── 6. Check parts availability for each unique mtype ───────────
        parts_cache = {}
        for item in due_items:
            mt = item["maintenance_type"]
            if mt not in parts_cache:
                res = self.tools["check_parts_availability"](maintenance_type=mt)
                parts_cache[mt] = res["status"]

        # ── 7. Get all technicians via tool (paginated) ─────────────────
        all_techs = []
        page = 1
        while True:
            result = self.tools["list_technicians"](page=page)
            all_techs.extend(result["technicians"])
            if not result["has_more"]:
                break
            page += 1

        # ── 8. Greedy scheduling ────────────────────────────────────────
        week_dates = sched["available_days"]
        max_per_day = int(sched["max_dispatches_per_day"])
        max_tech_h_day = float(sched["max_hours_per_technician_per_day"])

        day_count = {d: 0 for d in week_dates}
        tech_day_h = {t["tech_id"]: {d: 0.0 for d in week_dates} for t in all_techs}
        tech_week_h = {t["tech_id"]: 0.0 for t in all_techs}

        dispatch_list = []
        rank = 1
        for item in due_items:
            v_res = reservations.get(item["vehicle_id"], set())
            for day in week_dates:
                if day in v_res:
                    continue
                if day_count[day] >= max_per_day:
                    continue
                eligible = []
                for t in all_techs:
                    if t["depot_id"] != item["depot_id"]:
                        continue
                    if t["cert_level"] < item["required_cert_level"]:
                        continue
                    if tech_day_h[t["tech_id"]][day] + item["estimated_duration_hours"] > max_tech_h_day:
                        continue
                    if tech_week_h[t["tech_id"]] + item["estimated_duration_hours"] > t["max_weekly_hours"]:
                        continue
                    eligible.append(t)
                if not eligible:
                    continue
                eligible.sort(key=lambda t: (t["hourly_rate"], t["tech_id"]))
                chosen = eligible[0]

                dispatch_list.append({
                    "priority_rank": rank,
                    "vehicle_id": item["vehicle_id"],
                    "maintenance_type": item["maintenance_type"],
                    "urgency_score": f"{item['urgency_score']:.2f}",
                    "assigned_tech_id": chosen["tech_id"],
                    "scheduled_day": day,
                    "estimated_duration_hours": f"{item['estimated_duration_hours']:.1f}",
                    "parts_status": parts_cache.get(item["maintenance_type"], "ready"),
                })
                day_count[day] += 1
                tech_day_h[chosen["tech_id"]][day] += item["estimated_duration_hours"]
                tech_week_h[chosen["tech_id"]] += item["estimated_duration_hours"]
                rank += 1
                break

        # ── 9. Write dispatch_list.csv ──────────────────────────────────
        fieldnames = [
            "priority_rank", "vehicle_id", "maintenance_type", "urgency_score",
            "assigned_tech_id", "scheduled_day", "estimated_duration_hours", "parts_status",
        ]
        csv_path = os.path.join(self.workspace, "dispatch_list.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in dispatch_list:
                writer.writerow(row)

        # ── 10. Build summary ───────────────────────────────────────────
        tier_crit = float(policy["urgency_tiers"]["critical"]["min_score"])
        tier_high = float(policy["urgency_tiers"]["high"]["min_score"])

        total_dispatches = len(dispatch_list)
        total_hours = sum(float(r["estimated_duration_hours"]) for r in dispatch_list)
        n_critical = sum(1 for r in dispatch_list if float(r["urgency_score"]) >= tier_crit)
        n_high = sum(1 for r in dispatch_list if tier_high <= float(r["urgency_score"]) < tier_crit)
        n_routine = total_dispatches - n_critical - n_high

        action = (
            f"The weekly preventative maintenance dispatch list has been generated "
            f"and saved as dispatch_list.csv.\n"
            f"Total dispatches: {total_dispatches}\n"
            f"Total estimated hours: {total_hours:.1f}\n"
            f"Critical: {n_critical}, High: {n_high}, Routine: {n_routine}"
        )

        return self.step(action)
