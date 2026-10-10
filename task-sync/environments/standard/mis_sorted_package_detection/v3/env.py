"""Environment for the mis-sorted package detection task."""

from typing import Tuple, Dict, List, Any
import csv
import glob as glob_mod
import json
import os
import re
import sqlite3

import yaml


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
    PAGE_SIZE = 25

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
        description=(
            "Lists packages with pagination. Returns package_id, tracking_number, "
            "destination_postal_code, assigned_lane, shipping_class, and station_id "
            "for each package. Pages are 1-indexed, 25 packages per page."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                }
            },
            "required": ["page"],
        },
    )
    def list_packages(self, page: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        offset = (page - 1) * self.PAGE_SIZE
        cur.execute(
            "SELECT p.package_id, p.tracking_number, p.destination_postal_code, "
            "sa.assigned_lane, p.shipping_class, p.station_id "
            "FROM packages p "
            "JOIN sort_assignments sa ON p.package_id = sa.package_id "
            "ORDER BY p.package_id "
            "LIMIT ? OFFSET ?",
            (self.PAGE_SIZE, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM packages")
        total = cur.fetchone()[0]
        conn.close()
        return {
            "page": page,
            "page_size": self.PAGE_SIZE,
            "total_packages": total,
            "total_pages": -(-total // self.PAGE_SIZE),  # ceil division
            "packages": rows,
        }

    @tool(
        description=(
            "Gets dimension scan results for a specific package. Returns declared "
            "and scanned length, width, and height."
        ),
        parameters={
            "type": "object",
            "properties": {
                "package_id": {
                    "type": "string",
                    "description": "The package identifier, e.g. PKG-000001.",
                }
            },
            "required": ["package_id"],
        },
    )
    def get_package_dimensions(self, package_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT p.declared_length, p.declared_width, p.declared_height, "
            "d.scanned_length, d.scanned_width, d.scanned_height "
            "FROM packages p "
            "JOIN dimension_scans d ON p.package_id = d.package_id "
            "WHERE p.package_id = ?",
            (package_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Package {package_id} not found"}
        return dict(row)

    @tool(
        description=(
            "Gets weight sensor reading for a specific package. Returns declared "
            "weight and measured weight."
        ),
        parameters={
            "type": "object",
            "properties": {
                "package_id": {
                    "type": "string",
                    "description": "The package identifier, e.g. PKG-000001.",
                }
            },
            "required": ["package_id"],
        },
    )
    def get_package_weight(self, package_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT p.declared_weight, w.measured_weight "
            "FROM packages p "
            "JOIN weight_readings w ON p.package_id = w.package_id "
            "WHERE p.package_id = ?",
            (package_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Package {package_id} not found"}
        return dict(row)

    @tool(
        description=(
            "Gets sort assignment details for a specific package including "
            "assigned lane, worker ID, station, and assignment time."
        ),
        parameters={
            "type": "object",
            "properties": {
                "package_id": {
                    "type": "string",
                    "description": "The package identifier, e.g. PKG-000001.",
                }
            },
            "required": ["package_id"],
        },
    )
    def get_sort_details(self, package_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT assigned_lane, worker_id, station_id, assignment_time "
            "FROM sort_assignments WHERE package_id = ?",
            (package_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Package {package_id} not found"}
        return dict(row)

    @tool(
        description=(
            "Gets information about a worker including name and assigned station."
        ),
        parameters={
            "type": "object",
            "properties": {
                "worker_id": {
                    "type": "string",
                    "description": "The worker identifier, e.g. WRK-0001.",
                }
            },
            "required": ["worker_id"],
        },
    )
    def get_worker_info(self, worker_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT worker_id, worker_name, station_id "
            "FROM workers WHERE worker_id = ?",
            (worker_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Worker {worker_id} not found"}
        return dict(row)

    # ================================================================
    # Ground-truth computation (used by step)
    # ================================================================

    def _compute_ground_truth(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute(
            "SELECT p.package_id, p.tracking_number, p.destination_postal_code, "
            "p.shipping_class, p.station_id, p.declared_weight, "
            "p.declared_length, p.declared_width, p.declared_height, "
            "sa.assigned_lane "
            "FROM packages p "
            "JOIN sort_assignments sa ON p.package_id = sa.package_id"
        )
        all_pkgs = [dict(r) for r in cur.fetchall()]

        cur.execute(
            "SELECT package_id, scanned_length, scanned_width, scanned_height "
            "FROM dimension_scans"
        )
        dim_map = {r["package_id"]: dict(r) for r in cur.fetchall()}

        cur.execute("SELECT package_id, measured_weight FROM weight_readings")
        wt_map = {r["package_id"]: dict(r) for r in cur.fetchall()}

        conn.close()

        # --- workspace look-ups ---
        with open(os.path.join(self.workspace, "zone_postal_mapping.json")) as fh:
            zone_map = json.load(fh)

        with open(os.path.join(self.workspace, "lane_zone_config.yaml")) as fh:
            zone_to_lane = yaml.safe_load(fh)["zone_to_lane"]

        cost_rates: Dict[tuple, float] = {}
        with open(os.path.join(self.workspace, "cost_avoidance_rates.csv")) as fh:
            for row in csv.DictReader(fh):
                cost_rates[(row["shipping_class"], row["zone"])] = float(row["base_cost"])

        customer_tiers: Dict[str, str] = {}
        for fp in sorted(glob_mod.glob(os.path.join(self.workspace, "shipment_batch_*.csv"))):
            with open(fp) as fh:
                for row in csv.DictReader(fh):
                    customer_tiers[row["package_id"]] = row["customer_tier"]

        tier_mult = {"enterprise": 2.5, "premium": 1.8, "standard": 1.0}

        # --- identify mis-sorted ---
        missorted = []
        for pkg in all_pkgs:
            prefix = pkg["destination_postal_code"][:5]
            zone = zone_map.get(prefix)
            if zone is None:
                continue
            correct_lane = zone_to_lane.get(zone)
            if correct_lane is None:
                continue
            if pkg["assigned_lane"] == correct_lane:
                continue

            wt = wt_map.get(pkg["package_id"], {})
            weight_disc = (
                abs(pkg["declared_weight"] - wt["measured_weight"]) > 0.5
                if "measured_weight" in wt
                else False
            )

            dim = dim_map.get(pkg["package_id"], {})
            dim_disc = False
            if "scanned_length" in dim:
                dim_disc = (
                    abs(pkg["declared_length"] - dim["scanned_length"]) > 2.0
                    or abs(pkg["declared_width"] - dim["scanned_width"]) > 2.0
                    or abs(pkg["declared_height"] - dim["scanned_height"]) > 2.0
                )

            tier = customer_tiers.get(pkg["package_id"], "standard")
            base_cost = cost_rates.get((pkg["shipping_class"], zone), 0.0)
            cost_avoidance = round(base_cost * tier_mult.get(tier, 1.0), 2)

            missorted.append(
                {
                    "package_id": pkg["package_id"],
                    "tracking_number": pkg["tracking_number"],
                    "station_id": pkg["station_id"],
                    "assigned_lane": pkg["assigned_lane"],
                    "correct_lane": correct_lane,
                    "destination_zone": zone,
                    "shipping_class": pkg["shipping_class"],
                    "customer_tier": tier,
                    "weight_discrepancy": weight_disc,
                    "dimension_discrepancy": dim_disc,
                    "cost_avoidance": cost_avoidance,
                }
            )

        missorted.sort(key=lambda x: (-x["cost_avoidance"], x["package_id"]))

        total_cost = round(sum(m["cost_avoidance"] for m in missorted), 2)

        station_counts: Dict[str, int] = {}
        for m in missorted:
            station_counts[m["station_id"]] = station_counts.get(m["station_id"], 0) + 1

        if station_counts:
            max_cnt = max(station_counts.values())
            top_station = sorted(s for s, c in station_counts.items() if c == max_cnt)[0]
        else:
            top_station = ""

        return {
            "missorted": missorted,
            "total_count": len(missorted),
            "total_cost": total_cost,
            "top_station": top_station,
        }

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
        gt = self._compute_ground_truth()
        criteria: Dict[str, dict] = {}

        # ---------- 1. File structure (15 pts) ----------
        csv_path = os.path.join(self.workspace, "re_sort_list.csv")
        expected_cols = [
            "package_id", "tracking_number", "station_id", "assigned_lane",
            "correct_lane", "destination_zone", "shipping_class", "customer_tier",
            "weight_discrepancy", "dimension_discrepancy", "cost_avoidance",
        ]
        file_ok = False
        agent_rows: list = []
        if os.path.exists(csv_path):
            with open(csv_path) as fh:
                reader = csv.DictReader(fh)
                if reader.fieldnames and set(expected_cols) <= set(reader.fieldnames):
                    file_ok = True
                    agent_rows = list(reader)
        criteria["file_structure"] = {
            "passed": file_ok,
            "score": 15 if file_ok else 0,
            "max_score": 15,
            "reason": "" if file_ok else "re_sort_list.csv missing or has wrong columns",
        }

        # ---------- 2. Package identification (25 pts) ----------
        gt_ids = {m["package_id"] for m in gt["missorted"]}
        agent_ids = {r.get("package_id", "") for r in agent_rows}
        if gt_ids:
            overlap = len(gt_ids & agent_ids)
            precision = overlap / len(agent_ids) if agent_ids else 0
            recall = overlap / len(gt_ids)
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            id_score = round(f1 * 25)
        else:
            id_score = 25 if not agent_ids else 0
        criteria["package_identification"] = {
            "passed": id_score == 25,
            "score": id_score,
            "max_score": 25,
            "reason": (
                ""
                if id_score == 25
                else f"Expected {len(gt_ids)}, got {len(agent_ids)}, overlap {len(gt_ids & agent_ids)}"
            ),
        }

        # ---------- 3. Correct lanes (10 pts) ----------
        gt_lanes = {m["package_id"]: m["correct_lane"] for m in gt["missorted"]}
        lane_ok = 0
        for r in agent_rows:
            pid = r.get("package_id", "")
            if pid in gt_lanes and r.get("correct_lane", "") == gt_lanes[pid]:
                lane_ok += 1
        n_gt = len(gt["missorted"]) or 1
        lane_score = round(lane_ok / n_gt * 10)
        criteria["correct_lanes"] = {
            "passed": lane_score == 10,
            "score": lane_score,
            "max_score": 10,
            "reason": "" if lane_score == 10 else f"{lane_ok}/{len(gt['missorted'])} correct",
        }

        # ---------- 4. Discrepancy flags (10 pts) ----------
        gt_flags = {
            m["package_id"]: (m["weight_discrepancy"], m["dimension_discrepancy"])
            for m in gt["missorted"]
        }
        flag_ok = 0
        for r in agent_rows:
            pid = r.get("package_id", "")
            if pid not in gt_flags:
                continue
            aw = r.get("weight_discrepancy", "").strip().lower() == "true"
            ad = r.get("dimension_discrepancy", "").strip().lower() == "true"
            if aw == gt_flags[pid][0] and ad == gt_flags[pid][1]:
                flag_ok += 1
        flag_score = round(flag_ok / n_gt * 10)
        criteria["discrepancy_flags"] = {
            "passed": flag_score == 10,
            "score": flag_score,
            "max_score": 10,
            "reason": "" if flag_score == 10 else f"{flag_ok}/{len(gt['missorted'])} correct",
        }

        # ---------- 5. Cost avoidance values (20 pts) ----------
        gt_costs = {m["package_id"]: m["cost_avoidance"] for m in gt["missorted"]}
        cost_ok = 0
        for r in agent_rows:
            pid = r.get("package_id", "")
            if pid not in gt_costs:
                continue
            try:
                val = round(float(r.get("cost_avoidance", 0)), 2)
                if abs(val - gt_costs[pid]) < 0.011:
                    cost_ok += 1
            except (ValueError, TypeError):
                pass
        cost_score = round(cost_ok / n_gt * 20)
        criteria["cost_avoidance_values"] = {
            "passed": cost_score == 20,
            "score": cost_score,
            "max_score": 20,
            "reason": "" if cost_score == 20 else f"{cost_ok}/{len(gt['missorted'])} correct",
        }

        # ---------- 6. Sort order (10 pts) ----------
        gt_order = [m["package_id"] for m in gt["missorted"]]
        agent_order = [r.get("package_id", "") for r in agent_rows]
        order_ok = gt_order == agent_order
        criteria["sort_order"] = {
            "passed": order_ok,
            "score": 10 if order_ok else 0,
            "max_score": 10,
            "reason": "" if order_ok else "Rows not sorted by cost_avoidance desc, package_id asc",
        }

        # ---------- 7. Total count in response (5 pts) ----------
        count_found = str(gt["total_count"]) in (action or "")
        criteria["total_count_response"] = {
            "passed": count_found,
            "score": 5 if count_found else 0,
            "max_score": 5,
            "reason": "" if count_found else f"Expected count {gt['total_count']} in response",
        }

        # ---------- 8. Total cost in response (10 pts) ----------
        cost_str = f"{gt['total_cost']:.2f}"
        cost_found = cost_str in (action or "")
        criteria["total_cost_response"] = {
            "passed": cost_found,
            "score": 10 if cost_found else 0,
            "max_score": 10,
            "reason": "" if cost_found else f"Expected cost {cost_str} in response",
        }

        # ---------- 9. Top station in response (10 pts) ----------
        station_found = gt["top_station"] in (action or "") if gt["top_station"] else True
        criteria["top_station_response"] = {
            "passed": station_found,
            "score": 10 if station_found else 0,
            "max_score": 10,
            "reason": "" if station_found else f"Expected station {gt['top_station']} in response",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
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
        tool_calls = 0

        # --- Read workspace config files ---
        with open(os.path.join(self.workspace, "zone_postal_mapping.json")) as fh:
            zone_map = json.load(fh)

        with open(os.path.join(self.workspace, "lane_zone_config.yaml")) as fh:
            zone_to_lane = yaml.safe_load(fh)["zone_to_lane"]

        cost_rates: Dict[tuple, float] = {}
        with open(os.path.join(self.workspace, "cost_avoidance_rates.csv")) as fh:
            for row in csv.DictReader(fh):
                cost_rates[(row["shipping_class"], row["zone"])] = float(row["base_cost"])

        # Parse tier multipliers from sorting policy
        with open(os.path.join(self.workspace, "sorting_policy.md")) as fh:
            policy = fh.read()
        tier_mult: Dict[str, float] = {}
        for m in re.finditer(r"-\s+(enterprise|premium|standard):\s+([\d.]+)", policy):
            tier_mult[m.group(1)] = float(m.group(2))

        # Parse thresholds
        wt_match = re.search(r"exceeds\s+([\d.]+)\s+kg", policy)
        weight_thresh = float(wt_match.group(1)) if wt_match else 0.5
        dim_match = re.search(r"greater than\s+([\d.]+)\s+cm", policy)
        dim_thresh = float(dim_match.group(1)) if dim_match else 2.0

        # Read customer tiers from batch manifests
        customer_tiers: Dict[str, str] = {}
        for fp in sorted(glob_mod.glob(os.path.join(self.workspace, "shipment_batch_*.csv"))):
            with open(fp) as fh:
                for row in csv.DictReader(fh):
                    customer_tiers[row["package_id"]] = row["customer_tier"]

        # --- Gather package data via tools ---
        all_packages = []
        page = 1
        while True:
            result = self.tools["list_packages"](page=page)
            tool_calls += 1
            all_packages.extend(result["packages"])
            if page >= result["total_pages"]:
                break
            page += 1

        # --- Identify mis-sorted packages ---
        missorted_ids = []
        pkg_info: Dict[str, dict] = {}
        for pkg in all_packages:
            prefix = pkg["destination_postal_code"][:5]
            zone = zone_map.get(prefix)
            if zone is None:
                continue
            correct_lane = zone_to_lane.get(zone)
            if correct_lane is None:
                continue
            if pkg["assigned_lane"] != correct_lane:
                missorted_ids.append(pkg["package_id"])
                pkg_info[pkg["package_id"]] = {
                    **pkg,
                    "destination_zone": zone,
                    "correct_lane": correct_lane,
                }

        # --- Get dimension and weight data for each mis-sorted package ---
        results = []
        for pid in missorted_ids:
            dims = self.tools["get_package_dimensions"](package_id=pid)
            tool_calls += 1
            wt = self.tools["get_package_weight"](package_id=pid)
            tool_calls += 1

            info = pkg_info[pid]

            weight_disc = abs(wt["declared_weight"] - wt["measured_weight"]) > weight_thresh
            dim_disc = (
                abs(dims["declared_length"] - dims["scanned_length"]) > dim_thresh
                or abs(dims["declared_width"] - dims["scanned_width"]) > dim_thresh
                or abs(dims["declared_height"] - dims["scanned_height"]) > dim_thresh
            )

            tier = customer_tiers.get(pid, "standard")
            base_cost = cost_rates.get((info["shipping_class"], info["destination_zone"]), 0.0)
            cost_avoidance = round(base_cost * tier_mult.get(tier, 1.0), 2)

            results.append(
                {
                    "package_id": pid,
                    "tracking_number": info["tracking_number"],
                    "station_id": info["station_id"],
                    "assigned_lane": info["assigned_lane"],
                    "correct_lane": info["correct_lane"],
                    "destination_zone": info["destination_zone"],
                    "shipping_class": info["shipping_class"],
                    "customer_tier": tier,
                    "weight_discrepancy": weight_disc,
                    "dimension_discrepancy": dim_disc,
                    "cost_avoidance": cost_avoidance,
                }
            )

        # --- Sort by cost_avoidance desc, package_id asc ---
        results.sort(key=lambda x: (-x["cost_avoidance"], x["package_id"]))

        # --- Write re_sort_list.csv ---
        fieldnames = [
            "package_id", "tracking_number", "station_id", "assigned_lane",
            "correct_lane", "destination_zone", "shipping_class", "customer_tier",
            "weight_discrepancy", "dimension_discrepancy", "cost_avoidance",
        ]
        csv_path = os.path.join(self.workspace, "re_sort_list.csv")
        with open(csv_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        total_cost = round(sum(r["cost_avoidance"] for r in results), 2)

        # Station with most mis-sorts (ties: alphabetical first)
        station_counts: Dict[str, int] = {}
        for r in results:
            station_counts[r["station_id"]] = station_counts.get(r["station_id"], 0) + 1
        if station_counts:
            max_cnt = max(station_counts.values())
            top_station = sorted(s for s, c in station_counts.items() if c == max_cnt)[0]
        else:
            top_station = "N/A"

        action = (
            f"Total mis-sorted packages: {len(results)}\n"
            f"Total cost avoidance: {total_cost:.2f}\n"
            f"Station with most mis-sorts: {top_station}\n"
        )

        assert tool_calls >= 15, f"Only {tool_calls} tool calls made (need >=15)"

        return self.step(action)
