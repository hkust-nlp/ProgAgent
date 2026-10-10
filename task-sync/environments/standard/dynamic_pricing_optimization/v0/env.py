"""Environment for EV charger dynamic pricing and availability task."""

from typing import Tuple, Dict, List, Any
import sqlite3
import os
import json
import csv
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# YAML helper — avoids hard dependency on PyYAML at import time
# ---------------------------------------------------------------------------

def _load_yaml(path: str) -> dict:
    """Load a simple YAML file. Uses PyYAML if available, else a minimal parser."""
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f)
    except ImportError:
        pass
    # Minimal parser sufficient for pricing_policy.yaml
    data: dict = {}
    stack: list = [(data, -1)]
    with open(path) as f:
        for raw in f:
            stripped = raw.rstrip("\n")
            if not stripped or stripped.lstrip().startswith("#"):
                continue
            indent = len(stripped) - len(stripped.lstrip())
            line = stripped.strip()
            while len(stack) > 1 and indent <= stack[-1][1]:
                stack.pop()
            parent = stack[-1][0]
            if line.startswith("- "):
                val_str = line[2:].strip().strip('"')
                try:
                    val: Any = int(val_str)
                except ValueError:
                    try:
                        val = float(val_str)
                    except ValueError:
                        val = val_str
                if not isinstance(parent, list):
                    # should not happen in well-formed input
                    continue
                parent.append(val)
            elif ":" in line:
                key, _, rest = line.partition(":")
                key = key.strip()
                rest = rest.strip()
                if rest == "":
                    # Peek next non-empty line to decide list vs dict
                    # For simplicity, default to dict; convert later if needed.
                    child: Any = {}
                    parent[key] = child
                    stack.append((child, indent))
                elif rest.startswith("- "):
                    child = []
                    val_str = rest[2:].strip().strip('"')
                    try:
                        val = int(val_str)
                    except ValueError:
                        try:
                            val = float(val_str)
                        except ValueError:
                            val = val_str
                    child.append(val)
                    parent[key] = child
                    stack.append((child, indent))
                else:
                    rest = rest.strip('"')
                    try:
                        val = int(rest)
                    except ValueError:
                        try:
                            val = float(rest)
                        except ValueError:
                            val = rest
                    parent[key] = val
    # Convert dicts that should be lists (sequence of "- " items)
    # The parser above pushes dicts when it first sees "key:"; if the first
    # child is "- ", it replaces the dict with a list.  This simple approach
    # works for our specific YAML structure.
    return data


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

    # ================================================================
    # Internal DB helper
    # ================================================================

    def _query_db(self, query: str, params: tuple = ()) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    # ================================================================
    # Tools
    # ================================================================

    @tool(
        description=(
            "List chargers with pagination. Returns charger details including "
            "charger_id, station_id, zone_id, charger_type, power_kw, "
            "connector_type, and is_active status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 20, default 20).",
                },
            },
            "required": ["page"],
        },
    )
    def list_chargers(self, page: int, page_size: int = 20) -> dict:
        page_size = min(int(page_size), 20)
        page = int(page)
        offset = (page - 1) * page_size
        chargers = self._query_db(
            "SELECT * FROM chargers ORDER BY charger_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        total = self._query_db("SELECT COUNT(*) AS cnt FROM chargers")[0]["cnt"]
        return {
            "chargers": chargers,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description=(
            "Get the 24-hour schedule for a specific charger starting from the "
            "reference time. Returns currently active charging sessions, "
            "confirmed reservations, and scheduled or in-progress maintenance "
            "windows that overlap the next 24 hours."
        ),
        parameters={
            "type": "object",
            "properties": {
                "charger_id": {
                    "type": "string",
                    "description": "The charger ID, e.g. 'CHG-0001'.",
                },
            },
            "required": ["charger_id"],
        },
    )
    def get_charger_schedule(self, charger_id: str) -> dict:
        ref = "2026-04-22T08:00:00"
        end = "2026-04-23T08:00:00"

        active_sessions = self._query_db(
            "SELECT session_id, start_time, expected_end_time, energy_kwh "
            "FROM sessions "
            "WHERE charger_id = ? AND status = 'active' "
            "AND expected_end_time > ?",
            (charger_id, ref),
        )
        reservations = self._query_db(
            "SELECT reservation_id, reserved_start, reserved_end, user_id "
            "FROM reservations "
            "WHERE charger_id = ? AND status = 'confirmed' "
            "AND reserved_start < ? AND reserved_end > ?",
            (charger_id, end, ref),
        )
        maintenance = self._query_db(
            "SELECT maintenance_id, scheduled_start, scheduled_end, "
            "maintenance_type, priority "
            "FROM maintenance "
            "WHERE charger_id = ? "
            "AND status IN ('scheduled', 'in_progress') "
            "AND scheduled_start < ? AND scheduled_end > ?",
            (charger_id, end, ref),
        )
        return {
            "charger_id": charger_id,
            "active_sessions": active_sessions,
            "confirmed_reservations": reservations,
            "scheduled_maintenance": maintenance,
        }

    @tool(
        description=(
            "Get grid demand forecasts for a specific zone for the next 24 hours. "
            "Returns hourly predicted demand percentage, supply capacity, and "
            "renewable energy percentage."
        ),
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "string",
                    "description": "The zone ID, e.g. 'ZONE-A'.",
                },
            },
            "required": ["zone_id"],
        },
    )
    def get_grid_forecast(self, zone_id: str) -> dict:
        forecasts = self._query_db(
            "SELECT forecast_hour, predicted_demand_pct, "
            "supply_capacity_mw, renewable_pct "
            "FROM grid_forecasts WHERE zone_id = ? ORDER BY forecast_hour",
            (zone_id,),
        )
        return {"zone_id": zone_id, "forecasts": forecasts}

    @tool(
        description=(
            "Count the total number of active chargers (is_active = 1) in a "
            "specific zone."
        ),
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "string",
                    "description": "The zone ID, e.g. 'ZONE-A'.",
                },
            },
            "required": ["zone_id"],
        },
    )
    def count_zone_active_chargers(self, zone_id: str) -> dict:
        result = self._query_db(
            "SELECT COUNT(*) AS count FROM chargers "
            "WHERE zone_id = ? AND is_active = 1",
            (zone_id,),
        )
        return {"zone_id": zone_id, "active_charger_count": result[0]["count"]}

    # ================================================================
    # Ground-truth computation (shared by step and _compute_ground_truth)
    # ================================================================

    def _compute_ground_truth(self):
        """Compute ground-truth availability and pricing matrices.

        Returns (avail_matrix, price_matrix) where each is
        {charger_id: [val_for_hour_0 … val_for_hour_23]}.
        """
        ref = datetime(2026, 4, 22, 8, 0, 0)
        ref_str = ref.strftime("%Y-%m-%dT%H:%M:%S")
        end_str = (ref + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")

        chargers = self._query_db("SELECT * FROM chargers ORDER BY charger_id")

        # Workspace configs
        pricing = _load_yaml(os.path.join(self.workspace, "pricing_policy.yaml"))
        with open(os.path.join(self.workspace, "grid_tariff_tiers.json")) as f:
            tariff = json.load(f)
        with open(os.path.join(self.workspace, "maintenance_impact_rules.json")) as f:
            maint_rules = json.load(f)

        # Station usage files
        station_usage: Dict[str, Dict[int, float]] = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("station_STN-") and fname.endswith("_usage.csv"):
                stn_id = fname.replace("station_", "").replace("_usage.csv", "")
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    station_usage[stn_id] = {
                        int(row["clock_hour"]): float(row["avg_utilization_rate"])
                        for row in reader
                    }

        # Grid forecasts per zone  {zone: {hour_offset: {...}}}
        zones = sorted(set(c["zone_id"] for c in chargers))
        zone_forecasts: Dict[str, Dict[int, dict]] = {z: {} for z in zones}
        for zone in zones:
            rows = self._query_db(
                "SELECT forecast_hour, predicted_demand_pct, renewable_pct "
                "FROM grid_forecasts WHERE zone_id = ? ORDER BY forecast_hour",
                (zone,),
            )
            for row in rows:
                fh = datetime.strptime(row["forecast_hour"], "%Y-%m-%dT%H:%M:%S")
                offset = int((fh - ref).total_seconds() // 3600)
                if 0 <= offset < 24:
                    zone_forecasts[zone][offset] = {
                        "demand_pct": row["predicted_demand_pct"],
                        "renewable_pct": row["renewable_pct"],
                    }

        # Schedules per charger
        schedules: Dict[str, dict] = {}
        for c in chargers:
            cid = c["charger_id"]
            schedules[cid] = {
                "sessions": self._query_db(
                    "SELECT start_time, expected_end_time FROM sessions "
                    "WHERE charger_id = ? AND status = 'active' "
                    "AND expected_end_time > ?",
                    (cid, ref_str),
                ),
                "reservations": self._query_db(
                    "SELECT reserved_start, reserved_end FROM reservations "
                    "WHERE charger_id = ? AND status = 'confirmed' "
                    "AND reserved_start < ? AND reserved_end > ?",
                    (cid, end_str, ref_str),
                ),
                "maintenance": self._query_db(
                    "SELECT scheduled_start, scheduled_end FROM maintenance "
                    "WHERE charger_id = ? "
                    "AND status IN ('scheduled', 'in_progress') "
                    "AND scheduled_start < ? AND scheduled_end > ?",
                    (cid, end_str, ref_str),
                ),
            }

        # Zone active charger counts
        zone_active: Dict[str, int] = {}
        for zone in zones:
            r = self._query_db(
                "SELECT COUNT(*) AS cnt FROM chargers "
                "WHERE zone_id = ? AND is_active = 1",
                (zone,),
            )
            zone_active[zone] = r[0]["cnt"]

        # Maintenance count per zone per hour
        zone_maint: Dict[str, Dict[int, int]] = {
            z: {h: 0 for h in range(24)} for z in zones
        }
        for c in chargers:
            if not c["is_active"]:
                continue
            cid = c["charger_id"]
            zone = c["zone_id"]
            for m in schedules[cid]["maintenance"]:
                ms = datetime.strptime(m["scheduled_start"], "%Y-%m-%dT%H:%M:%S")
                me = datetime.strptime(m["scheduled_end"], "%Y-%m-%dT%H:%M:%S")
                for h in range(24):
                    hs = ref + timedelta(hours=h)
                    he = ref + timedelta(hours=h + 1)
                    if ms < he and me > hs:
                        zone_maint[zone][h] += 1

        # --- Helper closures ---
        def demand_multiplier(demand_pct: float) -> float:
            for tier in tariff["tiers"]:
                if tier["min_demand_pct"] <= demand_pct < tier["max_demand_pct"]:
                    return tier["multiplier"]
            return tariff["tiers"][-1]["multiplier"]

        def maint_surcharge(zone: str, hour: int) -> float:
            ta = zone_active.get(zone, 0)
            if ta == 0:
                return 0.0
            red_pct = (zone_maint.get(zone, {}).get(hour, 0) / ta) * 100
            for rule in maint_rules["zone_capacity_reduction_surcharge"]:
                if rule["min_reduction_pct"] <= red_pct < rule["max_reduction_pct"]:
                    return rule["surcharge"]
            return maint_rules["zone_capacity_reduction_surcharge"][-1]["surcharge"]

        def util_surcharge(station_id: str, clock_hour: int) -> float:
            util = station_usage.get(station_id, {}).get(clock_hour, 0.0)
            if util >= pricing["utilization_thresholds"]["high"]:
                return pricing["utilization_surcharges"]["high"]
            elif util >= pricing["utilization_thresholds"]["medium"]:
                return pricing["utilization_surcharges"]["medium"]
            return pricing["utilization_surcharges"]["low"]

        base_rates = pricing["base_rates"]
        peak_hours = set(int(h) for h in pricing["peak_hours"])
        peak_sur = float(pricing["peak_surcharge"])
        off_disc = float(pricing["off_peak_discount"])
        renew_thr = float(pricing["renewable_discount_threshold"])
        renew_disc = float(pricing["renewable_discount"])

        avail_matrix: Dict[str, List[str]] = {}
        price_matrix: Dict[str, List[str]] = {}

        for c in chargers:
            cid = c["charger_id"]
            avail_row: List[str] = []
            price_row: List[str] = []

            for h in range(24):
                hs = ref + timedelta(hours=h)
                he = ref + timedelta(hours=h + 1)
                clock_hour = hs.hour

                # --- Availability ---
                if not c["is_active"]:
                    avail_row.append("offline")
                    price_row.append("N/A")
                    continue

                in_maint = any(
                    datetime.strptime(m["scheduled_start"], "%Y-%m-%dT%H:%M:%S") < he
                    and datetime.strptime(m["scheduled_end"], "%Y-%m-%dT%H:%M:%S") > hs
                    for m in schedules[cid]["maintenance"]
                )
                if in_maint:
                    avail_row.append("maintenance")
                    price_row.append("N/A")
                    continue

                in_session = any(
                    datetime.strptime(s["start_time"], "%Y-%m-%dT%H:%M:%S") < he
                    and datetime.strptime(s["expected_end_time"], "%Y-%m-%dT%H:%M:%S") > hs
                    for s in schedules[cid]["sessions"]
                )
                if in_session:
                    status = "occupied"
                else:
                    in_res = any(
                        datetime.strptime(r["reserved_start"], "%Y-%m-%dT%H:%M:%S") < he
                        and datetime.strptime(r["reserved_end"], "%Y-%m-%dT%H:%M:%S") > hs
                        for r in schedules[cid]["reservations"]
                    )
                    status = "reserved" if in_res else "available"
                avail_row.append(status)

                # --- Price ---
                base = float(base_rates[c["charger_type"]])
                peak_adj = peak_sur if clock_hour in peak_hours else -off_disc
                zone = c["zone_id"]
                fc = zone_forecasts.get(zone, {}).get(
                    h, {"demand_pct": 50.0, "renewable_pct": 30.0}
                )
                dm = demand_multiplier(fc["demand_pct"])
                us = util_surcharge(c["station_id"], clock_hour)
                rd = renew_disc if fc["renewable_pct"] > renew_thr else 0.0
                ms_val = maint_surcharge(zone, h)
                price = round((base + peak_adj) * dm + us - rd + ms_val, 2)
                price_row.append(str(price))

            avail_matrix[cid] = avail_row
            price_matrix[cid] = price_row

        return avail_matrix, price_matrix

    # ================================================================
    # step
    # ================================================================

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
        eval_criteria: Dict[str, dict] = {}
        total_score = 0
        max_score = 0

        gt_avail, gt_price = self._compute_ground_truth()

        # ------ 1. availability_matrix.csv structure (10 pts) ------
        pts = 10
        max_score += pts
        avail_path = os.path.join(self.workspace, "availability_matrix.csv")
        avail_ok = False
        agent_avail: Dict[str, List[str]] = {}
        if os.path.exists(avail_path):
            try:
                with open(avail_path) as f:
                    reader = csv.DictReader(f)
                    expected = ["charger_id"] + [f"hour_{h}" for h in range(24)]
                    if list(reader.fieldnames or []) == expected:
                        for row in reader:
                            agent_avail[row["charger_id"]] = [
                                row[f"hour_{h}"] for h in range(24)
                            ]
                        if set(agent_avail.keys()) == set(gt_avail.keys()):
                            avail_ok = True
            except Exception:
                pass
        if avail_ok:
            eval_criteria["availability_structure"] = {
                "passed": True, "score": pts, "max_score": pts,
            }
            total_score += pts
        else:
            eval_criteria["availability_structure"] = {
                "passed": False, "score": 0, "max_score": pts,
                "reason": "File missing, wrong headers, or wrong charger IDs",
            }

        # ------ 2. availability correctness (25 pts) ------
        pts = 25
        max_score += pts
        if avail_ok:
            total_cells = correct = 0
            for cid in gt_avail:
                for h in range(24):
                    total_cells += 1
                    if agent_avail.get(cid, [""] * 24)[h] == gt_avail[cid][h]:
                        correct += 1
            pct = correct / total_cells if total_cells else 0
            earned = round(pct * pts)
            eval_criteria["availability_correctness"] = {
                "passed": pct >= 0.95,
                "score": earned,
                "max_score": pts,
                **({"reason": f"{correct}/{total_cells} correct ({pct:.1%})"} if pct < 0.95 else {}),
            }
            total_score += earned
        else:
            eval_criteria["availability_correctness"] = {
                "passed": False, "score": 0, "max_score": pts,
                "reason": "Structure check failed",
            }

        # ------ 3. pricing_matrix.csv structure (10 pts) ------
        pts = 10
        max_score += pts
        price_path = os.path.join(self.workspace, "pricing_matrix.csv")
        price_ok = False
        agent_price: Dict[str, List[str]] = {}
        if os.path.exists(price_path):
            try:
                with open(price_path) as f:
                    reader = csv.DictReader(f)
                    expected = ["charger_id"] + [f"hour_{h}" for h in range(24)]
                    if list(reader.fieldnames or []) == expected:
                        for row in reader:
                            agent_price[row["charger_id"]] = [
                                row[f"hour_{h}"] for h in range(24)
                            ]
                        if set(agent_price.keys()) == set(gt_price.keys()):
                            price_ok = True
            except Exception:
                pass
        if price_ok:
            eval_criteria["pricing_structure"] = {
                "passed": True, "score": pts, "max_score": pts,
            }
            total_score += pts
        else:
            eval_criteria["pricing_structure"] = {
                "passed": False, "score": 0, "max_score": pts,
                "reason": "File missing, wrong headers, or wrong charger IDs",
            }

        # ------ 4. pricing correctness (25 pts) ------
        pts = 25
        max_score += pts
        if price_ok:
            total_cells = correct = 0
            for cid in gt_price:
                for h in range(24):
                    total_cells += 1
                    gt_val = gt_price[cid][h]
                    ag_val = agent_price.get(cid, [""] * 24)[h]
                    if gt_val == "N/A":
                        if ag_val == "N/A":
                            correct += 1
                    else:
                        try:
                            if abs(float(ag_val) - float(gt_val)) < 0.005:
                                correct += 1
                        except (ValueError, TypeError):
                            pass
            pct = correct / total_cells if total_cells else 0
            earned = round(pct * pts)
            eval_criteria["pricing_correctness"] = {
                "passed": pct >= 0.95,
                "score": earned,
                "max_score": pts,
                **({"reason": f"{correct}/{total_cells} correct ({pct:.1%})"} if pct < 0.95 else {}),
            }
            total_score += earned
        else:
            eval_criteria["pricing_correctness"] = {
                "passed": False, "score": 0, "max_score": pts,
                "reason": "Structure check failed",
            }

        # ------ 5. total_available_slots (10 pts) ------
        pts = 10
        max_score += pts
        gt_avail_count = sum(
            1 for cid in gt_avail for s in gt_avail[cid] if s == "available"
        )
        if f"total_available_slots: {gt_avail_count}" in action:
            eval_criteria["total_available_slots"] = {
                "passed": True, "score": pts, "max_score": pts,
            }
            total_score += pts
        else:
            eval_criteria["total_available_slots"] = {
                "passed": False, "score": 0, "max_score": pts,
                "reason": f"Expected 'total_available_slots: {gt_avail_count}'",
            }

        # ------ 6. peak_pricing_hour (10 pts) ------
        pts = 10
        max_score += pts
        hour_avgs: Dict[int, float] = {}
        for h in range(24):
            vals = []
            for cid in gt_price:
                v = gt_price[cid][h]
                if v != "N/A":
                    vals.append(float(v))
            if vals:
                hour_avgs[h] = sum(vals) / len(vals)
        peak_hour = max(hour_avgs, key=hour_avgs.get) if hour_avgs else 0  # type: ignore[arg-type]
        if f"peak_pricing_hour: {peak_hour}" in action:
            eval_criteria["peak_pricing_hour"] = {
                "passed": True, "score": pts, "max_score": pts,
            }
            total_score += pts
        else:
            eval_criteria["peak_pricing_hour"] = {
                "passed": False, "score": 0, "max_score": pts,
                "reason": f"Expected 'peak_pricing_hour: {peak_hour}'",
            }

        # ------ 7. estimated_max_revenue (10 pts) ------
        pts = 10
        max_score += pts
        charger_map = {
            c["charger_id"]: c
            for c in self._query_db("SELECT * FROM chargers")
        }
        revenue = 0.0
        for cid in gt_price:
            for h in range(24):
                if gt_avail[cid][h] == "available" and gt_price[cid][h] != "N/A":
                    revenue += float(gt_price[cid][h]) * charger_map[cid]["power_kw"]
        revenue = round(revenue, 2)
        rev_str = f"{revenue:.2f}"
        if f"estimated_max_revenue: {rev_str}" in action:
            eval_criteria["estimated_max_revenue"] = {
                "passed": True, "score": pts, "max_score": pts,
            }
            total_score += pts
        else:
            eval_criteria["estimated_max_revenue"] = {
                "passed": False, "score": 0, "max_score": pts,
                "reason": f"Expected 'estimated_max_revenue: {rev_str}'",
            }

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ================================================================
    # verify
    # ================================================================

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
        # ---------- Read workspace configs ----------
        pricing = _load_yaml(os.path.join(self.workspace, "pricing_policy.yaml"))
        with open(os.path.join(self.workspace, "grid_tariff_tiers.json")) as f:
            tariff = json.load(f)
        with open(os.path.join(self.workspace, "maintenance_impact_rules.json")) as f:
            maint_rules = json.load(f)

        # Station usage
        station_usage: Dict[str, Dict[int, float]] = {}
        with open(os.path.join(self.workspace, "zone_station_map.csv")) as f:
            reader = csv.DictReader(f)
            station_rows = list(reader)
        for stn in station_rows:
            sid = stn["station_id"]
            path = os.path.join(self.workspace, f"station_{sid}_usage.csv")
            if os.path.exists(path):
                with open(path) as f:
                    rd = csv.DictReader(f)
                    station_usage[sid] = {
                        int(r["clock_hour"]): float(r["avg_utilization_rate"])
                        for r in rd
                    }

        ref_str = str(pricing["reference_time"])
        ref = datetime.strptime(ref_str, "%Y-%m-%dT%H:%M:%S")

        # ---------- Gather data via tools ----------
        all_chargers: List[dict] = []
        page = 1
        while True:
            result = self.tools["list_chargers"](page=page, page_size=20)
            all_chargers.extend(result["chargers"])
            if page >= result["total_pages"]:
                break
            page += 1

        schedules: Dict[str, dict] = {}
        for c in all_chargers:
            schedules[c["charger_id"]] = self.tools["get_charger_schedule"](
                charger_id=c["charger_id"]
            )

        zones = sorted(set(c["zone_id"] for c in all_chargers))

        zone_forecasts: Dict[str, Dict[int, dict]] = {z: {} for z in zones}
        for z in zones:
            fc_res = self.tools["get_grid_forecast"](zone_id=z)
            for fc in fc_res["forecasts"]:
                fh = datetime.strptime(fc["forecast_hour"], "%Y-%m-%dT%H:%M:%S")
                offset = int((fh - ref).total_seconds() // 3600)
                if 0 <= offset < 24:
                    zone_forecasts[z][offset] = {
                        "demand_pct": fc["predicted_demand_pct"],
                        "renewable_pct": fc["renewable_pct"],
                    }

        zone_active: Dict[str, int] = {}
        for z in zones:
            zone_active[z] = self.tools["count_zone_active_chargers"](zone_id=z)[
                "active_charger_count"
            ]

        # ---------- Compute maintenance per zone per hour ----------
        zone_maint: Dict[str, Dict[int, int]] = {
            z: {h: 0 for h in range(24)} for z in zones
        }
        for c in all_chargers:
            if not c["is_active"]:
                continue
            cid = c["charger_id"]
            zone = c["zone_id"]
            for m in schedules[cid]["scheduled_maintenance"]:
                ms = datetime.strptime(m["scheduled_start"], "%Y-%m-%dT%H:%M:%S")
                me = datetime.strptime(m["scheduled_end"], "%Y-%m-%dT%H:%M:%S")
                for h in range(24):
                    hs = ref + timedelta(hours=h)
                    he = ref + timedelta(hours=h + 1)
                    if ms < he and me > hs:
                        zone_maint[zone][h] += 1

        # ---------- Helpers ----------
        def demand_multiplier(demand_pct: float) -> float:
            for tier in tariff["tiers"]:
                if tier["min_demand_pct"] <= demand_pct < tier["max_demand_pct"]:
                    return tier["multiplier"]
            return tariff["tiers"][-1]["multiplier"]

        def get_maint_surcharge(zone: str, hour: int) -> float:
            ta = zone_active.get(zone, 0)
            if ta == 0:
                return 0.0
            red_pct = (zone_maint.get(zone, {}).get(hour, 0) / ta) * 100
            for rule in maint_rules["zone_capacity_reduction_surcharge"]:
                if rule["min_reduction_pct"] <= red_pct < rule["max_reduction_pct"]:
                    return rule["surcharge"]
            return maint_rules["zone_capacity_reduction_surcharge"][-1]["surcharge"]

        def get_util_surcharge(station_id: str, clock_hour: int) -> float:
            util = station_usage.get(station_id, {}).get(clock_hour, 0.0)
            if util >= pricing["utilization_thresholds"]["high"]:
                return pricing["utilization_surcharges"]["high"]
            elif util >= pricing["utilization_thresholds"]["medium"]:
                return pricing["utilization_surcharges"]["medium"]
            return pricing["utilization_surcharges"]["low"]

        base_rates = pricing["base_rates"]
        peak_hours = set(int(h) for h in pricing["peak_hours"])
        peak_sur = float(pricing["peak_surcharge"])
        off_disc = float(pricing["off_peak_discount"])
        renew_thr = float(pricing["renewable_discount_threshold"])
        renew_disc_val = float(pricing["renewable_discount"])

        # ---------- Build matrices ----------
        headers = ["charger_id"] + [f"hour_{h}" for h in range(24)]
        avail_rows: List[dict] = []
        price_rows: List[dict] = []
        charger_power: Dict[str, float] = {}

        for c in sorted(all_chargers, key=lambda x: x["charger_id"]):
            cid = c["charger_id"]
            charger_power[cid] = c["power_kw"]
            a_row: dict = {"charger_id": cid}
            p_row: dict = {"charger_id": cid}

            for h in range(24):
                hs = ref + timedelta(hours=h)
                he = ref + timedelta(hours=h + 1)
                clock_hour = hs.hour
                col = f"hour_{h}"

                if not c["is_active"]:
                    a_row[col] = "offline"
                    p_row[col] = "N/A"
                    continue

                in_maint = any(
                    datetime.strptime(m["scheduled_start"], "%Y-%m-%dT%H:%M:%S") < he
                    and datetime.strptime(m["scheduled_end"], "%Y-%m-%dT%H:%M:%S") > hs
                    for m in schedules[cid]["scheduled_maintenance"]
                )
                if in_maint:
                    a_row[col] = "maintenance"
                    p_row[col] = "N/A"
                    continue

                in_session = any(
                    datetime.strptime(s["start_time"], "%Y-%m-%dT%H:%M:%S") < he
                    and datetime.strptime(s["expected_end_time"], "%Y-%m-%dT%H:%M:%S") > hs
                    for s in schedules[cid]["active_sessions"]
                )
                if in_session:
                    status = "occupied"
                else:
                    in_res = any(
                        datetime.strptime(r["reserved_start"], "%Y-%m-%dT%H:%M:%S") < he
                        and datetime.strptime(r["reserved_end"], "%Y-%m-%dT%H:%M:%S") > hs
                        for r in schedules[cid]["confirmed_reservations"]
                    )
                    status = "reserved" if in_res else "available"
                a_row[col] = status

                base = float(base_rates[c["charger_type"]])
                peak_adj = peak_sur if clock_hour in peak_hours else -off_disc
                zone = c["zone_id"]
                fc = zone_forecasts.get(zone, {}).get(
                    h, {"demand_pct": 50.0, "renewable_pct": 30.0}
                )
                dm = demand_multiplier(fc["demand_pct"])
                us = get_util_surcharge(c["station_id"], clock_hour)
                rd = renew_disc_val if fc["renewable_pct"] > renew_thr else 0.0
                ms_val = get_maint_surcharge(zone, h)
                price = round((base + peak_adj) * dm + us - rd + ms_val, 2)
                p_row[col] = str(price)

            avail_rows.append(a_row)
            price_rows.append(p_row)

        # ---------- Write deliverables ----------
        with open(os.path.join(self.workspace, "availability_matrix.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(avail_rows)

        with open(os.path.join(self.workspace, "pricing_matrix.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(price_rows)

        # ---------- Summary metrics ----------
        total_available = sum(
            1 for r in avail_rows for h in range(24) if r[f"hour_{h}"] == "available"
        )

        hour_price_lists: Dict[int, List[float]] = {h: [] for h in range(24)}
        for r in price_rows:
            for h in range(24):
                v = r[f"hour_{h}"]
                if v != "N/A":
                    hour_price_lists[h].append(float(v))
        hour_avgs = {
            h: sum(vs) / len(vs) for h, vs in hour_price_lists.items() if vs
        }
        peak_hour = max(hour_avgs, key=hour_avgs.get) if hour_avgs else 0  # type: ignore[arg-type]

        revenue = 0.0
        for ar, pr in zip(avail_rows, price_rows):
            cid = ar["charger_id"]
            for h in range(24):
                if ar[f"hour_{h}"] == "available" and pr[f"hour_{h}"] != "N/A":
                    revenue += float(pr[f"hour_{h}"]) * charger_power[cid]
        revenue = round(revenue, 2)

        action = (
            f"total_available_slots: {total_available}\n"
            f"peak_pricing_hour: {peak_hour}\n"
            f"estimated_max_revenue: {revenue:.2f}"
        )

        return self.step(action)
