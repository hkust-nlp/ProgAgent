import sqlite3
import os
import json
import csv
import math
from datetime import date, timedelta
from typing import Tuple, Dict, List, Any

import yaml

# ---------------------------------------------------------------------------
# Tool decorator
# ---------------------------------------------------------------------------

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
        }
        return func
    return decorator


# ---------------------------------------------------------------------------
# Task_Env
# ---------------------------------------------------------------------------

def _envelope(payload):
    """MCP-style tool result: payload JSON-encoded in a text content block."""
    return {"content": [{"type": "text",
                          "text": json.dumps(payload, ensure_ascii=False, default=str)}],
            "isError": False}


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
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description="List pens with basic info. Returns paginated results sorted by pen_id.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1."
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of pens per page."
                },
            },
            "required": [],
        },
    )
    def list_pens(self, page=1, page_size=20):
        conn = sqlite3.connect(self.db_path)
        total = conn.execute("SELECT COUNT(*) FROM pens").fetchone()[0]
        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT pen_id, breed, barn_id FROM pens ORDER BY pen_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return json.dumps({
            "pens": [{"pen_id": r[0], "breed": r[1], "barn_id": r[2]} for r in rows],
            "page": page,
            "total_pages": (total + page_size - 1) // page_size,
            "total_pens": total,
            "has_next": offset + page_size < total,
        }, ensure_ascii=False, default=str)

    @tool(
        description="Get detailed information for a specific pen including breed, animal count, average weight, age in weeks, and barn assignment.",
        parameters={
            "type": "object",
            "properties": {
                "pen_id": {
                    "type": "string",
                    "description": "The pen identifier, e.g. P0001."
                },
            },
            "required": ["pen_id"],
        },
    )
    def get_pen_details(self, pen_id):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT pen_id, breed, num_animals, avg_weight_kg, age_weeks, barn_id "
            "FROM pens WHERE pen_id = ?", (pen_id,),
        ).fetchone()
        conn.close()
        if not row:
            return _envelope({"error": f"Pen {pen_id} not found"})
        return _envelope({
            "pen_id": row[0], "breed": row[1], "num_animals": row[2],
            "avg_weight_kg": row[3], "age_weeks": row[4], "barn_id": row[5],
        })

    @tool(
        description="Retrieve recent automated feeder consumption logs for a specific pen. Returns commodity, date, quantity, and waste percentage for each entry within the lookback window.",
        parameters={
            "type": "object",
            "properties": {
                "pen_id": {
                    "type": "string",
                    "description": "The pen identifier."
                },
                "num_days": {
                    "type": "integer",
                    "description": "Number of most-recent days to include. Defaults to 7."
                },
            },
            "required": ["pen_id"],
        },
    )
    def get_feeder_logs(self, pen_id, num_days=7):
        conn = sqlite3.connect(self.db_path)
        max_date_row = conn.execute(
            "SELECT MAX(log_date) FROM feeder_logs WHERE pen_id = ?", (pen_id,),
        ).fetchone()
        if not max_date_row or max_date_row[0] is None:
            conn.close()
            return json.dumps({"logs": []}, ensure_ascii=False, default=str)
        max_dt = date.fromisoformat(max_date_row[0])
        start_dt = max_dt - timedelta(days=num_days - 1)
        rows = conn.execute(
            "SELECT commodity, log_date, quantity_kg, waste_pct "
            "FROM feeder_logs WHERE pen_id = ? AND log_date >= ? "
            "ORDER BY log_date, commodity",
            (pen_id, start_dt.isoformat()),
        ).fetchall()
        conn.close()
        return json.dumps({
            "logs": [
                {"commodity": r[0], "log_date": r[1],
                 "quantity_kg": r[2], "waste_pct": r[3]}
                for r in rows
            ]
        }, ensure_ascii=False, default=str)

    @tool(
        description="Look up breed-specific growth targets for a given age week. Returns target weight, average daily gain, expected dry-matter intake as percentage of body weight, and minimum protein and energy requirements.",
        parameters={
            "type": "object",
            "properties": {
                "breed": {
                    "type": "string",
                    "description": "Breed name, e.g. Angus."
                },
                "age_week": {
                    "type": "integer",
                    "description": "Age of the animals in weeks."
                },
            },
            "required": ["breed", "age_week"],
        },
    )
    def get_growth_target(self, breed, age_week):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT target_weight_kg, target_adg_kg, dmi_pct_bw, "
            "min_protein_pct, min_energy_mcal_kg "
            "FROM growth_targets WHERE breed = ? AND age_week = ?",
            (breed, age_week),
        ).fetchone()
        conn.close()
        if not row:
            return _envelope({"error": f"No growth target for {breed} at week {age_week}"})
        return _envelope({
            "target_weight_kg": row[0], "target_adg_kg": row[1],
            "dmi_pct_bw": row[2], "min_protein_pct": row[3],
            "min_energy_mcal_kg": row[4],
        })

    @tool(
        description="List all available feed commodities with their category, crude protein percentage, and metabolizable energy density.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_commodities(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT name, category, protein_pct, energy_mcal_kg "
            "FROM commodities ORDER BY name"
        ).fetchall()
        conn.close()
        return _envelope([
            {"name": r[0], "category": r[1],
             "protein_pct": r[2], "energy_mcal_kg": r[3]}
            for r in rows
        ])

    @tool(
        description="Get total available stock for a given commodity across all silos.",
        parameters={
            "type": "object",
            "properties": {
                "commodity": {
                    "type": "string",
                    "description": "Commodity name, e.g. Corn."
                },
            },
            "required": ["commodity"],
        },
    )
    def get_silo_stock(self, commodity):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT COALESCE(SUM(current_stock_kg), 0) FROM silo_inventory "
            "WHERE commodity = ?", (commodity,),
        ).fetchone()
        conn.close()
        return json.dumps({"commodity": commodity, "total_available_kg": row[0]}, ensure_ascii=False, default=str)

    @tool(
        description="Get the most recent market price for a commodity. Returns the lowest quoted price on the latest available date along with the supplier.",
        parameters={
            "type": "object",
            "properties": {
                "commodity": {
                    "type": "string",
                    "description": "Commodity name, e.g. Corn."
                },
            },
            "required": ["commodity"],
        },
    )
    def get_latest_price(self, commodity):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT price_per_ton, supplier, price_date FROM market_prices "
            "WHERE commodity = ? ORDER BY price_date DESC, price_per_ton ASC LIMIT 1",
            (commodity,),
        ).fetchone()
        conn.close()
        if not row:
            return json.dumps({"error": f"No price data for {commodity}"}, ensure_ascii=False, default=str)
        return json.dumps({
            "commodity": commodity,
            "price_per_ton": row[0],
            "supplier": row[1],
            "price_date": row[2],
        }, ensure_ascii=False, default=str)

    # ------------------------------------------------------------------
    # Shared ration computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_rations(pens, feeder_data, growth_targets, commodity_info,
                         latest_prices, health_data, rules, policy):
        """Pure computation: given all inputs, produce schedule and adjustments.

        Args:
            pens: list of dicts  {pen_id, breed, num_animals, avg_weight_kg, age_weeks}
            feeder_data: dict  pen_id -> list of {waste_pct}
            growth_targets: dict  (breed, age_week) -> {dmi_pct_bw, min_protein_pct, min_energy_mcal_kg}
            commodity_info: dict  name -> {category, protein_pct, energy_mcal_kg}
            latest_prices: dict  commodity_name -> price_per_ton
            health_data: dict  pen_id -> {health_flag}
            rules: parsed formulation_rules.yaml
            policy: parsed cost_policy.json

        Returns:
            (schedule_rows, adjustments, total_weekly_cost)
        """
        cat_map = rules["commodity_categories"]
        category_commodities = {}
        for cname, cat in cat_map.items():
            category_commodities.setdefault(cat, []).append(cname)
        # Within each category sort by latest price asc, then name asc
        for cat in category_commodities:
            category_commodities[cat].sort(
                key=lambda n: (latest_prices.get(n, 1e9), n))

        lookback = rules["waste_rules"]["lookback_days"]
        threshold = rules["waste_rules"]["threshold_pct"]
        reduction_factor = rules["waste_rules"]["reduction_factor"]

        schedule_rows = []
        adjustments = []

        for pen in pens:
            pid = pen["pen_id"]
            breed = pen["breed"]
            age_weeks = pen["age_weeks"]
            num_animals = pen["num_animals"]
            avg_weight = pen["avg_weight_kg"]

            gt = growth_targets.get((breed, age_weeks))
            if gt is None:
                continue

            dmi_per_head = avg_weight * gt["dmi_pct_bw"] / 100.0

            # Health multiplier
            hflag = health_data.get(pid, {}).get("health_flag", "green")
            health_mult = rules["health_adjustments"].get(hflag, 1.0)

            # Waste multiplier
            logs = feeder_data.get(pid, [])
            avg_waste = (sum(l["waste_pct"] for l in logs) / len(logs)) if logs else 0.0
            waste_mult = 1.0
            if avg_waste > threshold:
                waste_mult = 1.0 - (avg_waste - threshold) * reduction_factor / 100.0

            adjusted_dmi = dmi_per_head * health_mult * waste_mult
            total_dmi = adjusted_dmi * num_animals

            # Adjustment tracking
            is_health_adj = hflag != "green"
            is_waste_adj = avg_waste > threshold
            if is_health_adj and is_waste_adj:
                adj_type = "both"
            elif is_health_adj:
                adj_type = "health"
            elif is_waste_adj:
                adj_type = "waste"
            else:
                adj_type = None

            if adj_type:
                parts = []
                if is_health_adj:
                    parts.append(
                        f"health flag {hflag} (multiplier {health_mult:.2f})")
                if is_waste_adj:
                    parts.append(
                        f"avg waste {avg_waste:.1f}% exceeds {threshold}% "
                        f"threshold (multiplier {waste_mult:.4f})")
                adjustments.append({
                    "pen_id": pid,
                    "adjustment_type": adj_type,
                    "description": f"Pen {pid}: " + " and ".join(parts),
                })

            # Phase and base allocation
            phase = ("growing"
                     if age_weeks <= rules["feeding_phases"]["growing"]["max_age_weeks"]
                     else "finishing")
            allocation = dict(rules["feeding_phases"][phase]["category_allocation"])

            min_protein = gt["min_protein_pct"]
            min_energy = gt["min_energy_mcal_kg"]

            # Helper: blended nutrients given allocation
            def _blend(alloc):
                bp = 0.0
                be = 0.0
                for cat, pct in alloc.items():
                    if cat not in category_commodities:
                        continue
                    if cat == "supplement":
                        for sname, sfrac in rules["supplement_split"].items():
                            ci = commodity_info[sname]
                            bp += pct * sfrac * ci["protein_pct"]
                            be += pct * sfrac * ci["energy_mcal_kg"]
                    else:
                        chosen = category_commodities[cat][0]
                        ci = commodity_info[chosen]
                        bp += pct * ci["protein_pct"]
                        be += pct * ci["energy_mcal_kg"]
                return bp, be

            # Protein adjustment
            for _ in range(50):
                bp, _ = _blend(allocation)
                if bp >= min_protein:
                    break
                if allocation.get("protein", 0) >= 0.25:
                    break
                allocation["protein"] = round(allocation.get("protein", 0) + 0.02, 4)
                allocation["grain"] = round(allocation.get("grain", 0) - 0.02, 4)

            # Energy adjustment
            for _ in range(50):
                _, be = _blend(allocation)
                if be >= min_energy:
                    break
                if allocation.get("forage", 0) <= 0.15:
                    break
                allocation["grain"] = round(allocation.get("grain", 0) + 0.01, 4)
                allocation["forage"] = round(allocation.get("forage", 0) - 0.01, 4)

            # Build ration rows
            for cat in sorted(allocation.keys()):
                pct = allocation[cat]
                if cat not in category_commodities:
                    continue
                cat_qty = total_dmi * pct

                if cat == "supplement":
                    for sname in sorted(rules["supplement_split"].keys()):
                        sfrac = rules["supplement_split"][sname]
                        qty = cat_qty * sfrac
                        cost = qty * latest_prices.get(sname, 0) / 1000.0
                        schedule_rows.append({
                            "pen_id": pid,
                            "commodity": sname,
                            "daily_quantity_kg": round(qty, 2),
                            "weekly_total_kg": round(qty * 7, 2),
                            "daily_cost_usd": round(cost, 2),
                        })
                else:
                    chosen = category_commodities[cat][0]
                    qty = cat_qty
                    cost = qty * latest_prices.get(chosen, 0) / 1000.0
                    schedule_rows.append({
                        "pen_id": pid,
                        "commodity": chosen,
                        "daily_quantity_kg": round(qty, 2),
                        "weekly_total_kg": round(qty * 7, 2),
                        "daily_cost_usd": round(cost, 2),
                    })

        schedule_rows.sort(key=lambda r: (r["pen_id"], r["commodity"]))
        total_weekly_cost = round(sum(r["daily_cost_usd"] for r in schedule_rows) * 7, 2)

        return schedule_rows, adjustments, total_weekly_cost

    # ------------------------------------------------------------------
    # Ground-truth (reads DB + workspace directly)
    # ------------------------------------------------------------------

    def _compute_ground_truth(self):
        conn = sqlite3.connect(self.db_path)

        # Pens
        pens = []
        for r in conn.execute("SELECT pen_id, breed, num_animals, avg_weight_kg, age_weeks, barn_id FROM pens ORDER BY pen_id"):
            pens.append({
                "pen_id": r[0], "breed": r[1], "num_animals": r[2],
                "avg_weight_kg": r[3], "age_weeks": r[4], "barn_id": r[5],
            })

        # Commodity info
        commodity_info = {}
        for r in conn.execute("SELECT name, category, protein_pct, energy_mcal_kg FROM commodities"):
            commodity_info[r[0]] = {"category": r[1], "protein_pct": r[2], "energy_mcal_kg": r[3]}

        # Latest prices
        latest_prices = {}
        for cname in commodity_info:
            r = conn.execute(
                "SELECT price_per_ton FROM market_prices "
                "WHERE commodity = ? ORDER BY price_date DESC, price_per_ton ASC LIMIT 1",
                (cname,)).fetchone()
            if r:
                latest_prices[cname] = r[0]

        # Load rules & policy from workspace
        with open(os.path.join(self.workspace, "formulation_rules.yaml")) as f:
            rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "cost_policy.json")) as f:
            policy = json.load(f)

        lookback = rules["waste_rules"]["lookback_days"]

        # Feeder data (last lookback_days per pen)
        feeder_data = {}
        for pen in pens:
            pid = pen["pen_id"]
            md = conn.execute(
                "SELECT MAX(log_date) FROM feeder_logs WHERE pen_id = ?", (pid,)
            ).fetchone()[0]
            if md:
                max_dt = date.fromisoformat(md)
                start_dt = max_dt - timedelta(days=lookback - 1)
                rows = conn.execute(
                    "SELECT waste_pct FROM feeder_logs "
                    "WHERE pen_id = ? AND log_date >= ?",
                    (pid, start_dt.isoformat())
                ).fetchall()
                feeder_data[pid] = [{"waste_pct": r[0]} for r in rows]
            else:
                feeder_data[pid] = []

        # Growth targets
        growth_targets = {}
        for pen in pens:
            key = (pen["breed"], pen["age_weeks"])
            if key not in growth_targets:
                r = conn.execute(
                    "SELECT dmi_pct_bw, min_protein_pct, min_energy_mcal_kg "
                    "FROM growth_targets WHERE breed = ? AND age_week = ?",
                    key).fetchone()
                if r:
                    growth_targets[key] = {
                        "dmi_pct_bw": r[0], "min_protein_pct": r[1],
                        "min_energy_mcal_kg": r[2]}

        # Health data from workspace condition files
        health_data = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("condition_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        health_data[row["pen_id"]] = {
                            "health_flag": row["health_flag"]}

        conn.close()

        return self._compute_rations(
            pens, feeder_data, growth_targets, commodity_info,
            latest_prices, health_data, rules, policy)

    # ------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------

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
        expected_schedule, expected_adj, expected_cost = self._compute_ground_truth()

        criteria = {}
        total_score = 0
        max_score = 0

        # ---- 1. File structure (10 pts) ----
        max_score += 10
        sched_path = os.path.join(self.workspace, "weekly_ration_schedule.csv")
        expected_cols = ["pen_id", "commodity", "daily_quantity_kg",
                         "weekly_total_kg", "daily_cost_usd"]
        agent_schedule = []
        if os.path.exists(sched_path):
            with open(sched_path, newline="") as f:
                reader = csv.DictReader(f)
                if list(reader.fieldnames or []) == expected_cols:
                    agent_schedule = list(reader)
                    criteria["file_structure"] = {
                        "passed": True, "score": 10, "max_score": 10}
                    total_score += 10
                else:
                    criteria["file_structure"] = {
                        "passed": False, "score": 0, "max_score": 10,
                        "reason": f"Expected columns {expected_cols}, "
                                  f"got {reader.fieldnames}"}
        else:
            criteria["file_structure"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "weekly_ration_schedule.csv not found"}

        # ---- 2. Pen coverage (15 pts) ----
        max_score += 15
        conn = sqlite3.connect(self.db_path)
        all_pen_ids = {r[0] for r in conn.execute("SELECT pen_id FROM pens")}
        conn.close()
        agent_pens = {r["pen_id"] for r in agent_schedule}
        if all_pen_ids:
            coverage = len(agent_pens & all_pen_ids) / len(all_pen_ids)
        else:
            coverage = 0.0
        score_2 = round(15 * coverage)
        criteria["pen_coverage"] = {
            "passed": coverage == 1.0, "score": score_2, "max_score": 15}
        if coverage < 1.0:
            criteria["pen_coverage"]["reason"] = (
                f"Missing {len(all_pen_ids - agent_pens)} of {len(all_pen_ids)} pens")
        total_score += score_2

        # ---- 3. Nutritional adequacy (20 pts) ----
        max_score += 20
        # Build agent ration per pen
        agent_pen_rations = {}
        for row in agent_schedule:
            pid = row["pen_id"]
            agent_pen_rations.setdefault(pid, []).append(row)

        conn = sqlite3.connect(self.db_path)
        commodity_info = {}
        for r in conn.execute("SELECT name, protein_pct, energy_mcal_kg FROM commodities"):
            commodity_info[r[0]] = {"protein_pct": r[1], "energy_mcal_kg": r[2]}

        pens_checked = 0
        pens_passed = 0
        for pid in all_pen_ids:
            ration_rows = agent_pen_rations.get(pid, [])
            if not ration_rows:
                pens_checked += 1
                continue
            total_qty = 0.0
            weighted_protein = 0.0
            weighted_energy = 0.0
            for rr in ration_rows:
                try:
                    qty = float(rr["daily_quantity_kg"])
                except (ValueError, KeyError):
                    qty = 0.0
                ci = commodity_info.get(rr.get("commodity", ""), {})
                total_qty += qty
                weighted_protein += qty * ci.get("protein_pct", 0)
                weighted_energy += qty * ci.get("energy_mcal_kg", 0)
            if total_qty > 0:
                blend_protein = weighted_protein / total_qty
                blend_energy = weighted_energy / total_qty
            else:
                blend_protein = 0.0
                blend_energy = 0.0

            # Get growth target for this pen
            pen_row = conn.execute(
                "SELECT breed, age_weeks FROM pens WHERE pen_id = ?", (pid,)
            ).fetchone()
            if pen_row:
                gt = conn.execute(
                    "SELECT min_protein_pct, min_energy_mcal_kg FROM growth_targets "
                    "WHERE breed = ? AND age_week = ?",
                    (pen_row[0], pen_row[1])).fetchone()
                if gt:
                    pens_checked += 1
                    if blend_protein >= gt[0] - 0.5 and blend_energy >= gt[1] - 0.05:
                        pens_passed += 1

        conn.close()
        if pens_checked > 0:
            nut_ratio = pens_passed / pens_checked
        else:
            nut_ratio = 0.0
        score_3 = round(20 * nut_ratio)
        criteria["nutritional_adequacy"] = {
            "passed": nut_ratio >= 0.95, "score": score_3, "max_score": 20}
        if nut_ratio < 0.95:
            criteria["nutritional_adequacy"]["reason"] = (
                f"{pens_passed}/{pens_checked} pens meet nutritional targets")
        total_score += score_3

        # ---- 4. Schedule matches expected values (20 pts) ----
        max_score += 20
        # Compare agent schedule rows with expected
        expected_map = {}
        for er in expected_schedule:
            expected_map[(er["pen_id"], er["commodity"])] = er
        agent_map = {}
        for ar in agent_schedule:
            agent_map[(ar["pen_id"], ar.get("commodity", ""))] = ar

        matched = 0
        total_expected = len(expected_map)
        for key, exp in expected_map.items():
            ag = agent_map.get(key)
            if ag:
                try:
                    if (abs(float(ag["daily_quantity_kg"]) - exp["daily_quantity_kg"]) < 0.02
                            and abs(float(ag["weekly_total_kg"]) - exp["weekly_total_kg"]) < 0.15
                            and abs(float(ag["daily_cost_usd"]) - exp["daily_cost_usd"]) < 0.02):
                        matched += 1
                except (ValueError, KeyError):
                    pass
        if total_expected > 0:
            match_ratio = matched / total_expected
        else:
            match_ratio = 0.0
        score_4 = round(20 * match_ratio)
        criteria["schedule_accuracy"] = {
            "passed": match_ratio >= 0.95, "score": score_4, "max_score": 20}
        if match_ratio < 0.95:
            criteria["schedule_accuracy"]["reason"] = (
                f"{matched}/{total_expected} rows match expected values")
        total_score += score_4

        # ---- 5. Inventory feasibility (15 pts) ----
        max_score += 15
        conn = sqlite3.connect(self.db_path)
        with open(os.path.join(self.workspace, "cost_policy.json")) as f:
            policy = json.load(f)
        safety = policy.get("inventory_safety_margin_pct", 10) / 100.0

        commodity_usage = {}
        for row in agent_schedule:
            comm = row.get("commodity", "")
            try:
                wk = float(row["weekly_total_kg"])
            except (ValueError, KeyError):
                wk = 0.0
            commodity_usage[comm] = commodity_usage.get(comm, 0) + wk

        all_feasible = True
        infeasible_items = []
        for comm, usage in commodity_usage.items():
            stock_row = conn.execute(
                "SELECT COALESCE(SUM(current_stock_kg), 0) FROM silo_inventory "
                "WHERE commodity = ?", (comm,)).fetchone()
            avail = stock_row[0] * (1.0 - safety) if stock_row else 0
            if usage > avail and avail > 0:
                all_feasible = False
                infeasible_items.append(comm)
        conn.close()
        score_5 = 15 if all_feasible else 0
        criteria["inventory_feasibility"] = {
            "passed": all_feasible, "score": score_5, "max_score": 15}
        if not all_feasible:
            criteria["inventory_feasibility"]["reason"] = (
                f"Usage exceeds safe stock for: {', '.join(infeasible_items)}")
        total_score += score_5

        # ---- 6. Adjustment report (10 pts) ----
        max_score += 10
        report_path = os.path.join(self.workspace, "adjustment_report.json")
        score_6 = 0
        if os.path.exists(report_path):
            try:
                with open(report_path) as f:
                    report = json.load(f)
                has_keys = all(k in report for k in
                               ["total_weekly_cost", "num_pens_adjusted", "adjustments"])
                if has_keys:
                    # Check total_weekly_cost
                    cost_ok = abs(report["total_weekly_cost"] - expected_cost) < 1.0
                    # Check num_pens_adjusted
                    count_ok = report["num_pens_adjusted"] == len(expected_adj)
                    if cost_ok and count_ok:
                        score_6 = 10
                    elif cost_ok or count_ok:
                        score_6 = 5
                    else:
                        score_6 = 2  # at least has structure
                    criteria["adjustment_report"] = {
                        "passed": score_6 == 10, "score": score_6, "max_score": 10}
                    if score_6 < 10:
                        reasons = []
                        if not cost_ok:
                            reasons.append(
                                f"cost mismatch: got {report['total_weekly_cost']}, "
                                f"expected {expected_cost}")
                        if not count_ok:
                            reasons.append(
                                f"adjusted count: got {report['num_pens_adjusted']}, "
                                f"expected {len(expected_adj)}")
                        criteria["adjustment_report"]["reason"] = "; ".join(reasons)
                else:
                    criteria["adjustment_report"] = {
                        "passed": False, "score": 0, "max_score": 10,
                        "reason": "Missing required keys in adjustment_report.json"}
            except (json.JSONDecodeError, Exception) as e:
                criteria["adjustment_report"] = {
                    "passed": False, "score": 0, "max_score": 10,
                    "reason": f"Error reading adjustment_report.json: {e}"}
        else:
            criteria["adjustment_report"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "adjustment_report.json not found"}
        total_score += score_6

        # ---- 7. Action string (10 pts) ----
        max_score += 10
        score_7 = 0
        import re
        cost_match = re.search(
            r"Total Weekly Cost:\s*\$?([\d,]+\.?\d*)", action or "")
        count_match = re.search(
            r"Number of Adjusted Pens:\s*(\d+)", action or "")
        cost_ok = False
        count_ok = False
        if cost_match:
            try:
                parsed_cost = float(cost_match.group(1).replace(",", ""))
                cost_ok = abs(parsed_cost - expected_cost) < 1.0
            except ValueError:
                pass
        if count_match:
            try:
                parsed_count = int(count_match.group(1))
                count_ok = parsed_count == len(expected_adj)
            except ValueError:
                pass
        if cost_ok and count_ok:
            score_7 = 10
        elif cost_ok or count_ok:
            score_7 = 5
        criteria["action_string"] = {
            "passed": score_7 == 10, "score": score_7, "max_score": 10}
        if score_7 < 10:
            reasons = []
            if not cost_ok:
                reasons.append(f"Total Weekly Cost not found or mismatch (expected ~{expected_cost})")
            if not count_ok:
                reasons.append(f"Adjusted Pens count not found or mismatch (expected {len(expected_adj)})")
            criteria["action_string"]["reason"] = "; ".join(reasons)
        total_score += score_7

        # ---- Aggregate ----
        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ------------------------------------------------------------------
    # verify
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
        # 1. List all pens (paginated)
        all_pens_basic = []
        page = 1
        while True:
            result = json.loads(self.tools["list_pens"](page=page, page_size=20))
            all_pens_basic.extend(result["pens"])
            if not result["has_next"]:
                break
            page += 1

        # 2. Get details for each pen
        pen_details = {}
        for p in all_pens_basic:
            d = json.loads(self.tools["get_pen_details"](pen_id=p["pen_id"])["content"][0]["text"])
            pen_details[p["pen_id"]] = d

        # 3. Load rules and policy from workspace
        with open(os.path.join(self.workspace, "formulation_rules.yaml")) as f:
            rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "cost_policy.json")) as f:
            policy = json.load(f)

        lookback = rules["waste_rules"]["lookback_days"]

        # 4. Get feeder logs for each pen
        feeder_data = {}
        for pid in pen_details:
            result = json.loads(self.tools["get_feeder_logs"](pen_id=pid, num_days=lookback))
            feeder_data[pid] = result["logs"]

        # 5. Get growth targets for each unique (breed, age_week)
        growth_targets = {}
        for pid, d in pen_details.items():
            key = (d["breed"], d["age_weeks"])
            if key not in growth_targets:
                gt = json.loads(self.tools["get_growth_target"](breed=key[0], age_week=key[1])["content"][0]["text"])
                if "error" not in gt:
                    growth_targets[key] = {
                        "dmi_pct_bw": gt["dmi_pct_bw"],
                        "min_protein_pct": gt["min_protein_pct"],
                        "min_energy_mcal_kg": gt["min_energy_mcal_kg"],
                    }

        # 6. List commodities
        commodities_list = json.loads(self.tools["list_commodities"]()["content"][0]["text"])
        commodity_info = {c["name"]: c for c in commodities_list}

        # 7. Get latest prices
        latest_prices = {}
        for c in commodities_list:
            pr = json.loads(self.tools["get_latest_price"](commodity=c["name"]))
            if "error" not in pr:
                latest_prices[c["name"]] = pr["price_per_ton"]

        # 8. Get silo stocks (for info, not used in computation directly)
        silo_stocks = {}
        for c in commodities_list:
            sr = json.loads(self.tools["get_silo_stock"](commodity=c["name"]))
            silo_stocks[c["name"]] = sr["total_available_kg"]

        # 9. Read health data from condition files
        health_data = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("condition_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        health_data[row["pen_id"]] = {
                            "health_flag": row["health_flag"]}

        # 10. Build pens list in order
        pens_ordered = []
        for pid in sorted(pen_details.keys()):
            d = pen_details[pid]
            pens_ordered.append({
                "pen_id": pid,
                "breed": d["breed"],
                "num_animals": d["num_animals"],
                "avg_weight_kg": d["avg_weight_kg"],
                "age_weeks": d["age_weeks"],
            })

        # 11. Compute rations
        schedule, adjustments, total_weekly_cost = self._compute_rations(
            pens_ordered, feeder_data, growth_targets, commodity_info,
            latest_prices, health_data, rules, policy)

        # 12. Write weekly_ration_schedule.csv
        sched_path = os.path.join(self.workspace, "weekly_ration_schedule.csv")
        with open(sched_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "pen_id", "commodity", "daily_quantity_kg",
                "weekly_total_kg", "daily_cost_usd"])
            writer.writeheader()
            for row in schedule:
                writer.writerow(row)

        # 13. Write adjustment_report.json
        report = {
            "total_weekly_cost": total_weekly_cost,
            "num_pens_adjusted": len(adjustments),
            "adjustments": adjustments,
        }
        report_path = os.path.join(self.workspace, "adjustment_report.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        # 14. Build action string
        action = (
            f"Total Weekly Cost: ${total_weekly_cost:.2f}\n"
            f"Number of Adjusted Pens: {len(adjustments)}"
        )

        return self.step(action)
