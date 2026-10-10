"""
Preventative Maintenance Scheduling – Task Environment
"""

import os
import json
import csv
import sqlite3
from typing import Tuple, Dict, List, Any
from datetime import datetime


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

    # ──────────────────── tool methods ────────────────────

    @tool(
        description=(
            "Query buildings in the portfolio with optional zone filter. "
            "Returns a paginated list of buildings."
        ),
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "integer",
                    "description": "Optional zone ID to filter buildings by zone.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed. Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def query_buildings(self, zone_id=None, page=1, page_size=20):
        page = int(page)
        page_size = int(page_size)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        where = []
        params: list = []
        if zone_id is not None:
            where.append("zone_id = ?")
            params.append(int(zone_id))

        w = (" WHERE " + " AND ".join(where)) if where else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM buildings{w}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM buildings{w} ORDER BY building_id "
            f"LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
        conn.close()

        return {
            "buildings": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": page * page_size < total,
        }

    @tool(
        description=(
            "Query appliances with optional filters by building or category. "
            "Returns a paginated list of appliances with warranty and criticality info."
        ),
        parameters={
            "type": "object",
            "properties": {
                "building_id": {
                    "type": "integer",
                    "description": "Filter by building ID.",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by appliance category (e.g. HVAC, Plumbing).",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed. Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def query_appliances(self, building_id=None, category=None,
                         page=1, page_size=20):
        page = int(page)
        page_size = int(page_size)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        where = []
        params: list = []
        if building_id is not None:
            where.append("building_id = ?")
            params.append(int(building_id))
        if category is not None:
            where.append("category = ?")
            params.append(str(category))

        w = (" WHERE " + " AND ".join(where)) if where else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM appliances{w}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM appliances{w} ORDER BY appliance_id "
            f"LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
        conn.close()

        return {
            "appliances": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": page * page_size < total,
        }

    @tool(
        description=(
            "Query work orders with optional appliance filter. "
            "Returns a paginated list of historical work orders."
        ),
        parameters={
            "type": "object",
            "properties": {
                "appliance_id": {
                    "type": "integer",
                    "description": "Filter by appliance ID.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed. Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def query_work_orders(self, appliance_id=None, page=1, page_size=20):
        page = int(page)
        page_size = int(page_size)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        where = []
        params: list = []
        if appliance_id is not None:
            where.append("appliance_id = ?")
            params.append(int(appliance_id))

        w = (" WHERE " + " AND ".join(where)) if where else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM work_orders{w}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM work_orders{w} ORDER BY wo_id "
            f"LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
        conn.close()

        return {
            "work_orders": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": page * page_size < total,
        }

    @tool(
        description=(
            "Query tenant repair requests with optional building and category filters. "
            "Returns a paginated list of tenant requests."
        ),
        parameters={
            "type": "object",
            "properties": {
                "building_id": {
                    "type": "integer",
                    "description": "Filter by building ID.",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by appliance category.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed. Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def query_tenant_requests(self, building_id=None, category=None,
                              page=1, page_size=20):
        page = int(page)
        page_size = int(page_size)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        where = []
        params: list = []
        if building_id is not None:
            where.append("building_id = ?")
            params.append(int(building_id))
        if category is not None:
            where.append("category = ?")
            params.append(str(category))

        w = (" WHERE " + " AND ".join(where)) if where else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM tenant_requests{w}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM tenant_requests{w} ORDER BY request_id "
            f"LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
        conn.close()

        return {
            "requests": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": page * page_size < total,
        }

    @tool(
        description=(
            "Query vendors with optional specialty filter. "
            "Returns a paginated list of vendors with base rates and reliability info."
        ),
        parameters={
            "type": "object",
            "properties": {
                "specialty": {
                    "type": "string",
                    "description": "Filter by vendor specialty (appliance category).",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed. Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Defaults to 20.",
                },
            },
            "required": [],
        },
    )
    def query_vendors(self, specialty=None, page=1, page_size=20):
        page = int(page)
        page_size = int(page_size)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        where = []
        params: list = []
        if specialty is not None:
            where.append("specialty = ?")
            params.append(str(specialty))

        w = (" WHERE " + " AND ".join(where)) if where else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM vendors{w}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM vendors{w} ORDER BY vendor_id "
            f"LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
        conn.close()

        return {
            "vendors": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": page * page_size < total,
        }

    # ─────────────── ground-truth computation ─────────────────

    def _compute_expected_calendar(self):
        """
        Compute the ground-truth maintenance calendar using direct DB access
        and workspace files. Used by both step() and verify() for consistency.
        """
        import yaml

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # ── load workspace config ──
        with open(os.path.join(self.workspace, "priority_weights.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "budget_constraints.json")) as f:
            budget = json.load(f)
        with open(os.path.join(self.workspace, "category_service_hours.yaml")) as f:
            service_hours = yaml.safe_load(f)

        # seasonal vendor rates
        vendor_q3_mult = {}
        with open(os.path.join(self.workspace, "seasonal_vendor_rates.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                vendor_q3_mult[int(row["vendor_id"])] = float(row["q3_multiplier"])

        # zone inspection condition scores
        condition_scores = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("zone_") and fname.endswith("_inspections.csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        condition_scores[int(row["appliance_id"])] = float(
                            row["condition_score"]
                        )

        # ── load DB tables ──
        appliances = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM appliances ORDER BY appliance_id"
            ).fetchall()
        ]
        work_orders = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM work_orders ORDER BY wo_id"
            ).fetchall()
        ]
        tenant_reqs = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM tenant_requests ORDER BY request_id"
            ).fetchall()
        ]
        vendors_list = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM vendors ORDER BY vendor_id"
            ).fetchall()
        ]
        conn.close()

        # ── derived lookups ──
        weights = config["scoring"]["weights"]
        norm = config["scoring"]["normalization"]
        quarter_start = datetime.strptime(config["quarter_start"], "%Y-%m-%d")
        quarter_end = datetime.strptime(config["quarter_end"], "%Y-%m-%d")
        min_score = config["scheduling"]["min_priority_score"]
        months = config["quarter_months"]

        # last work order date per appliance
        last_wo = {}
        for wo in work_orders:
            aid = wo["appliance_id"]
            d = wo["service_date"]
            if aid not in last_wo or d > last_wo[aid]:
                last_wo[aid] = d

        # tenant request count per (building_id, category)
        req_count: Dict[tuple, int] = {}
        for r in tenant_reqs:
            key = (r["building_id"], r["category"])
            req_count[key] = req_count.get(key, 0) + 1

        # active vendors grouped by specialty
        vendors_by_spec: Dict[str, list] = {}
        for v in vendors_list:
            if v["active"]:
                vendors_by_spec.setdefault(v["specialty"], []).append(v)

        # ── compute priority scores ──
        candidates = []
        for app in appliances:
            aid = app["appliance_id"]
            bid = app["building_id"]
            cat = app["category"]
            crit = app["criticality"]
            wexp = datetime.strptime(app["warranty_expiry"], "%Y-%m-%d")

            # 1. warranty urgency
            if wexp <= quarter_end:
                days_left = max(0, (wexp - quarter_start).days)
                days_left = min(days_left, norm["warranty_warning_days"])
                w_urg = (1 - days_left / norm["warranty_warning_days"]) * 100
            else:
                w_urg = 0.0

            # 2. condition deficit
            cs = condition_scores.get(aid, norm["default_condition_score"])
            c_def = 100 - cs

            # 3. request frequency
            rc = req_count.get((bid, cat), 0)
            r_freq = min(rc / norm["max_request_count"], 1.0) * 100

            # 4. maintenance gap
            if aid in last_wo:
                last_date = datetime.strptime(last_wo[aid], "%Y-%m-%d")
                gap = max(0, (quarter_start - last_date).days)
                m_gap = min(gap / norm["max_maintenance_gap_days"], 1.0) * 100
            else:
                m_gap = 100.0

            # 5. criticality
            c_score = crit * 20

            priority = round(
                weights["warranty_urgency"] * w_urg
                + weights["condition_deficit"] * c_def
                + weights["request_frequency"] * r_freq
                + weights["maintenance_gap"] * m_gap
                + weights["criticality"] * c_score,
                2,
            )

            if priority < min_score:
                continue

            # vendor assignment
            eligible = vendors_by_spec.get(cat, [])
            if not eligible:
                continue

            sh = service_hours.get(cat, 4.0)
            best_vid = None
            best_cost = float("inf")
            best_rel = -1.0
            best_id = float("inf")

            for v in eligible:
                vid = v["vendor_id"]
                mult = vendor_q3_mult.get(vid, 1.0)
                est = round(v["base_hourly_rate"] * mult * sh, 2)
                if (est < best_cost
                        or (est == best_cost and v["reliability_score"] > best_rel)
                        or (est == best_cost
                            and v["reliability_score"] == best_rel
                            and vid < best_id)):
                    best_vid = vid
                    best_cost = est
                    best_rel = v["reliability_score"]
                    best_id = vid

            candidates.append({
                "appliance_id": aid,
                "building_id": bid,
                "category": cat,
                "priority_score": priority,
                "assigned_vendor_id": best_vid,
                "estimated_cost": best_cost,
            })

        # sort by priority desc, appliance_id asc for tie-break
        candidates.sort(key=lambda x: (-x["priority_score"], x["appliance_id"]))

        # ── apply budget constraints ──
        month_remaining = {m: budget["monthly_budget"][m] for m in months}
        month_count = {m: 0 for m in months}
        max_items = budget["max_items_per_month"]

        scheduled = []
        for cand in candidates:
            for m in months:
                if (month_remaining[m] >= cand["estimated_cost"]
                        and month_count[m] < max_items):
                    cand["month"] = m
                    month_remaining[m] -= cand["estimated_cost"]
                    month_count[m] += 1
                    scheduled.append(cand)
                    break

        # final sort: month asc, priority desc, appliance_id asc
        scheduled.sort(
            key=lambda x: (x["month"], -x["priority_score"], x["appliance_id"])
        )

        # summary stats
        total_items = len(scheduled)
        total_cost = round(sum(s["estimated_cost"] for s in scheduled), 2)
        if scheduled:
            best = max(scheduled, key=lambda x: (x["priority_score"],
                                                  -x["appliance_id"]))
            best_aid = best["appliance_id"]
            best_ps = best["priority_score"]
        else:
            best_aid = None
            best_ps = 0.0

        return scheduled, {
            "total_items": total_items,
            "total_cost": total_cost,
            "best_appliance_id": best_aid,
            "best_priority_score": best_ps,
        }

    # ─────────────────────── step ─────────────────────────────

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
        expected, summary = self._compute_expected_calendar()

        criteria: Dict[str, dict] = {}

        # ── 1. Calendar file structure (15 pts) ──
        cal_path = os.path.join(self.workspace, "maintenance_calendar.csv")
        expected_cols = [
            "month", "appliance_id", "building_id", "category",
            "priority_score", "assigned_vendor_id", "estimated_cost",
        ]
        if not os.path.isfile(cal_path):
            criteria["file_structure"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "maintenance_calendar.csv not found",
            }
            # can't evaluate further without the file
            for c_name, mx in [("scheduled_items", 25),
                                ("priority_scores", 20),
                                ("vendor_and_cost", 20),
                                ("sorting", 10),
                                ("summary_stats", 10)]:
                criteria[c_name] = {
                    "passed": False, "score": 0, "max_score": mx,
                    "reason": "calendar file missing",
                }
            total = 0
            mx_total = 100
            return total / mx_total, {
                "eval_criteria": criteria,
                "total_score": total,
                "max_score": mx_total,
            }

        # read agent's calendar
        agent_rows = []
        with open(cal_path, newline="") as f:
            reader = csv.DictReader(f)
            agent_cols = reader.fieldnames or []
            for row in reader:
                agent_rows.append(row)

        # check columns
        cols_match = [c.strip() for c in agent_cols] == expected_cols
        if cols_match:
            criteria["file_structure"] = {
                "passed": True, "score": 15, "max_score": 15,
            }
        else:
            criteria["file_structure"] = {
                "passed": False, "score": 5, "max_score": 15,
                "reason": (f"Expected columns {expected_cols}, "
                           f"got {[c.strip() for c in agent_cols]}"),
            }

        # build expected lookup: (appliance_id, month) -> record
        exp_key = {}
        for rec in expected:
            exp_key[(rec["appliance_id"], rec["month"])] = rec

        # parse agent rows
        agent_parsed = []
        for row in agent_rows:
            try:
                agent_parsed.append({
                    "month": row.get("month", "").strip(),
                    "appliance_id": int(row.get("appliance_id", -1)),
                    "building_id": int(row.get("building_id", -1)),
                    "category": row.get("category", "").strip(),
                    "priority_score": float(row.get("priority_score", 0)),
                    "assigned_vendor_id": int(row.get("assigned_vendor_id", -1)),
                    "estimated_cost": float(row.get("estimated_cost", 0)),
                })
            except (ValueError, TypeError):
                continue

        agent_key = {}
        for rec in agent_parsed:
            agent_key[(rec["appliance_id"], rec["month"])] = rec

        # ── 2. Scheduled items accuracy (25 pts) ──
        exp_set = set(exp_key.keys())
        agt_set = set(agent_key.keys())
        if len(exp_set) == 0:
            items_score = 25 if len(agt_set) == 0 else 0
        else:
            correct = len(exp_set & agt_set)
            total_union = len(exp_set | agt_set)
            items_score = round(25 * correct / total_union, 1)
        criteria["scheduled_items"] = {
            "passed": items_score >= 24.9,
            "score": items_score,
            "max_score": 25,
            "reason": (f"Expected {len(exp_set)} items, agent has {len(agt_set)}, "
                       f"overlap {len(exp_set & agt_set)}")
            if items_score < 24.9 else "",
        }

        # ── 3. Priority scores accuracy (20 pts) ──
        common = exp_set & agt_set
        if len(common) == 0:
            ps_score = 0.0
        else:
            match_count = 0
            for k in common:
                exp_ps = exp_key[k]["priority_score"]
                agt_ps = agent_key[k]["priority_score"]
                if abs(exp_ps - agt_ps) <= 0.02:
                    match_count += 1
            ps_score = round(20 * match_count / len(common), 1)
        criteria["priority_scores"] = {
            "passed": ps_score >= 19.9,
            "score": ps_score,
            "max_score": 20,
            "reason": (f"{match_count}/{len(common)} scores matched within tolerance")
            if ps_score < 19.9 and common else "",
        }

        # ── 4. Vendor and cost accuracy (20 pts) ──
        if len(common) == 0:
            vc_score = 0.0
        else:
            v_match = 0
            c_match = 0
            for k in common:
                if exp_key[k]["assigned_vendor_id"] == agent_key[k]["assigned_vendor_id"]:
                    v_match += 1
                if abs(exp_key[k]["estimated_cost"] - agent_key[k]["estimated_cost"]) <= 0.02:
                    c_match += 1
            # 10 pts for vendor, 10 pts for cost
            vc_score = round(10 * v_match / len(common)
                             + 10 * c_match / len(common), 1)
        criteria["vendor_and_cost"] = {
            "passed": vc_score >= 19.9,
            "score": vc_score,
            "max_score": 20,
        }

        # ── 5. Sorting (10 pts) ──
        if len(agent_parsed) < 2:
            sort_score = 10.0 if len(agent_parsed) == len(expected) else 0.0
        else:
            correctly_sorted = True
            for i in range(len(agent_parsed) - 1):
                a, b = agent_parsed[i], agent_parsed[i + 1]
                if a["month"] > b["month"]:
                    correctly_sorted = False
                    break
                if (a["month"] == b["month"]
                        and a["priority_score"] < b["priority_score"]):
                    correctly_sorted = False
                    break
            sort_score = 10.0 if correctly_sorted else 0.0
        criteria["sorting"] = {
            "passed": sort_score >= 9.9,
            "score": sort_score,
            "max_score": 10,
        }

        # ── 6. Summary statistics in action (10 pts) ──
        action_str = str(action)
        ss = 0.0
        # total items (exact)
        if str(summary["total_items"]) in action_str:
            ss += 3.0
        # total cost (within 1.0)
        try:
            import re
            cost_pats = re.findall(r"[\d,]+\.\d{2}", action_str)
            for cp in cost_pats:
                val = float(cp.replace(",", ""))
                if abs(val - summary["total_cost"]) <= 1.0:
                    ss += 4.0
                    break
        except Exception:
            pass
        # highest priority appliance id
        if summary["best_appliance_id"] is not None:
            if str(summary["best_appliance_id"]) in action_str:
                ss += 3.0
        else:
            ss += 3.0  # no items expected, no id needed
        criteria["summary_stats"] = {
            "passed": ss >= 9.9,
            "score": ss,
            "max_score": 10,
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0

        return reward, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ─────────────────────── verify ───────────────────────────

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
        import yaml

        # ── 1. Read workspace config files ──
        with open(os.path.join(self.workspace, "priority_weights.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "budget_constraints.json")) as f:
            budget = json.load(f)
        with open(os.path.join(self.workspace, "category_service_hours.yaml")) as f:
            service_hours = yaml.safe_load(f)

        # seasonal vendor rates
        vendor_q3_mult = {}
        with open(os.path.join(self.workspace, "seasonal_vendor_rates.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                vendor_q3_mult[int(row["vendor_id"])] = float(row["q3_multiplier"])

        # zone inspection condition scores
        condition_scores = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("zone_") and fname.endswith("_inspections.csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        condition_scores[int(row["appliance_id"])] = float(
                            row["condition_score"]
                        )

        # ── 2. Gather all data via tools (paginated) ──
        tool_call_count = 0

        # buildings
        all_buildings = []
        page = 1
        while True:
            result = self.tools["query_buildings"](page=page)
            tool_call_count += 1
            all_buildings.extend(result["buildings"])
            if not result["has_more"]:
                break
            page += 1

        # appliances
        all_appliances = []
        page = 1
        while True:
            result = self.tools["query_appliances"](page=page)
            tool_call_count += 1
            all_appliances.extend(result["appliances"])
            if not result["has_more"]:
                break
            page += 1

        # work orders
        all_work_orders = []
        page = 1
        while True:
            result = self.tools["query_work_orders"](page=page)
            tool_call_count += 1
            all_work_orders.extend(result["work_orders"])
            if not result["has_more"]:
                break
            page += 1

        # tenant requests
        all_requests = []
        page = 1
        while True:
            result = self.tools["query_tenant_requests"](page=page)
            tool_call_count += 1
            all_requests.extend(result["requests"])
            if not result["has_more"]:
                break
            page += 1

        # vendors
        all_vendors = []
        page = 1
        while True:
            result = self.tools["query_vendors"](page=page)
            tool_call_count += 1
            all_vendors.extend(result["vendors"])
            if not result["has_more"]:
                break
            page += 1

        assert tool_call_count >= 15, (
            f"Only {tool_call_count} tool calls; need ≥ 15"
        )

        # ── 3. Compute priority scores ──
        weights = config["scoring"]["weights"]
        norm = config["scoring"]["normalization"]
        quarter_start = datetime.strptime(config["quarter_start"], "%Y-%m-%d")
        quarter_end = datetime.strptime(config["quarter_end"], "%Y-%m-%d")
        min_score = config["scheduling"]["min_priority_score"]
        months = config["quarter_months"]

        # last work order date per appliance
        last_wo = {}
        for wo in all_work_orders:
            aid = wo["appliance_id"]
            d = wo["service_date"]
            if aid not in last_wo or d > last_wo[aid]:
                last_wo[aid] = d

        # tenant request count per (building_id, category)
        req_count: Dict[tuple, int] = {}
        for r in all_requests:
            key = (r["building_id"], r["category"])
            req_count[key] = req_count.get(key, 0) + 1

        # active vendors by specialty
        vendors_by_spec: Dict[str, list] = {}
        for v in all_vendors:
            if v["active"]:
                vendors_by_spec.setdefault(v["specialty"], []).append(v)

        candidates = []
        for app in all_appliances:
            aid = app["appliance_id"]
            bid = app["building_id"]
            cat = app["category"]
            crit = app["criticality"]
            wexp = datetime.strptime(app["warranty_expiry"], "%Y-%m-%d")

            # warranty urgency
            if wexp <= quarter_end:
                days_left = max(0, (wexp - quarter_start).days)
                days_left = min(days_left, norm["warranty_warning_days"])
                w_urg = (1 - days_left / norm["warranty_warning_days"]) * 100
            else:
                w_urg = 0.0

            # condition deficit
            cs = condition_scores.get(aid, norm["default_condition_score"])
            c_def = 100 - cs

            # request frequency
            rc = req_count.get((bid, cat), 0)
            r_freq = min(rc / norm["max_request_count"], 1.0) * 100

            # maintenance gap
            if aid in last_wo:
                last_date = datetime.strptime(last_wo[aid], "%Y-%m-%d")
                gap = max(0, (quarter_start - last_date).days)
                m_gap = min(gap / norm["max_maintenance_gap_days"], 1.0) * 100
            else:
                m_gap = 100.0

            # criticality
            c_score = crit * 20

            priority = round(
                weights["warranty_urgency"] * w_urg
                + weights["condition_deficit"] * c_def
                + weights["request_frequency"] * r_freq
                + weights["maintenance_gap"] * m_gap
                + weights["criticality"] * c_score,
                2,
            )

            if priority < min_score:
                continue

            # vendor assignment
            eligible = vendors_by_spec.get(cat, [])
            if not eligible:
                continue

            sh = service_hours.get(cat, 4.0)
            best_vid = None
            best_cost = float("inf")
            best_rel = -1.0
            best_id = float("inf")

            for v in eligible:
                vid = v["vendor_id"]
                mult = vendor_q3_mult.get(vid, 1.0)
                est = round(v["base_hourly_rate"] * mult * sh, 2)
                if (est < best_cost
                        or (est == best_cost
                            and v["reliability_score"] > best_rel)
                        or (est == best_cost
                            and v["reliability_score"] == best_rel
                            and vid < best_id)):
                    best_vid = vid
                    best_cost = est
                    best_rel = v["reliability_score"]
                    best_id = vid

            candidates.append({
                "appliance_id": aid,
                "building_id": bid,
                "category": cat,
                "priority_score": priority,
                "assigned_vendor_id": best_vid,
                "estimated_cost": best_cost,
            })

        # sort: priority desc, appliance_id asc
        candidates.sort(key=lambda x: (-x["priority_score"], x["appliance_id"]))

        # ── 4. Apply budget constraints ──
        month_remaining = {m: budget["monthly_budget"][m] for m in months}
        month_count = {m: 0 for m in months}
        max_items = budget["max_items_per_month"]

        scheduled = []
        for cand in candidates:
            for m in months:
                if (month_remaining[m] >= cand["estimated_cost"]
                        and month_count[m] < max_items):
                    cand["month"] = m
                    month_remaining[m] -= cand["estimated_cost"]
                    month_count[m] += 1
                    scheduled.append(cand)
                    break

        # final sort: month asc, priority desc, appliance_id asc
        scheduled.sort(
            key=lambda x: (x["month"], -x["priority_score"], x["appliance_id"])
        )

        # ── 5. Write calendar CSV ──
        cal_path = os.path.join(self.workspace, "maintenance_calendar.csv")
        with open(cal_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "month", "appliance_id", "building_id", "category",
                "priority_score", "assigned_vendor_id", "estimated_cost",
            ])
            for item in scheduled:
                writer.writerow([
                    item["month"],
                    item["appliance_id"],
                    item["building_id"],
                    item["category"],
                    f"{item['priority_score']:.2f}",
                    item["assigned_vendor_id"],
                    f"{item['estimated_cost']:.2f}",
                ])

        # ── 6. Summary ──
        total_items = len(scheduled)
        total_cost = round(sum(s["estimated_cost"] for s in scheduled), 2)
        if scheduled:
            best = max(
                scheduled,
                key=lambda x: (x["priority_score"], -x["appliance_id"]),
            )
            best_aid = best["appliance_id"]
            best_ps = best["priority_score"]
        else:
            best_aid = "N/A"
            best_ps = 0.0

        action = (
            f"Total scheduled maintenance tasks: {total_items}. "
            f"Total estimated quarterly cost: {total_cost:.2f}. "
            f"Highest priority appliance: ID {best_aid} "
            f"with score {best_ps:.2f}."
        )

        return self.step(action)
