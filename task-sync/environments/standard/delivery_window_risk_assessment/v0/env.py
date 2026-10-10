import sqlite3
import os
import json
import csv
import glob
import math
from datetime import datetime, timedelta
from typing import Tuple, Dict, List, Any

import yaml


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
        }
        return func
    return decorator


REF_DATE = datetime(2026, 4, 25)


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

    @tool(
        description="Lists shipments filtered by status. Returns paginated results with basic shipment information. Use page and page_size to iterate through results.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["in_transit", "delivered", "pending", "cancelled"],
                    "description": "Shipment status to filter by"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20)"
                }
            },
            "required": ["status", "page", "page_size"]
        }
    )
    def list_shipments(self, status: str, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM shipments WHERE status = ?", (status,))
        total = c.fetchone()[0]
        c.execute(
            "SELECT shipment_id, vessel_id, shipper_id, origin_port, dest_port, "
            "commodity_code, incoterm, contract_delivery_date, status, quantity_tons "
            "FROM shipments WHERE status = ? ORDER BY shipment_id LIMIT ? OFFSET ?",
            (status, page_size, offset)
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {
            "shipments": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if page_size > 0 else 0
        }

    @tool(
        description="Gets the current AIS position and navigation data for a specific vessel. Returns coordinates, speed, heading, and estimated time of arrival at destination port.",
        parameters={
            "type": "object",
            "properties": {
                "vessel_id": {
                    "type": "string",
                    "description": "Vessel identifier (e.g. VSL-0001)"
                }
            },
            "required": ["vessel_id"]
        }
    )
    def get_vessel_position(self, vessel_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM vessels WHERE vessel_id = ?", (vessel_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Vessel {vessel_id} not found"}
        return dict(row)

    @tool(
        description="Gets the latest port congestion report for a specific port. Returns the most recent congestion level, average berth waiting time in days, and vessel queue count. Aggregates across all terminals at the port using the most recent report date.",
        parameters={
            "type": "object",
            "properties": {
                "port_code": {
                    "type": "string",
                    "description": "Port code (e.g. CNSHA, USLAX, NLRTM)"
                }
            },
            "required": ["port_code"]
        }
    )
    def get_port_congestion(self, port_code: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        # Get the most recent report date for this port
        c.execute(
            "SELECT MAX(report_date) as latest_date FROM port_congestion WHERE port_code = ?",
            (port_code,)
        )
        result = c.fetchone()
        if result is None or result["latest_date"] is None:
            conn.close()
            return {"error": f"No congestion data for port {port_code}"}

        latest_date = result["latest_date"]
        # Get all terminal reports for that date, aggregate
        c.execute(
            "SELECT port_code, congestion_level, avg_berth_wait_days, vessel_queue_count, "
            "terminal_name, report_date, notes "
            "FROM port_congestion WHERE port_code = ? AND report_date = ? "
            "ORDER BY avg_berth_wait_days DESC LIMIT 1",
            (port_code, latest_date)
        )
        row = c.fetchone()
        # Also compute port-level average wait across terminals on that date
        c.execute(
            "SELECT AVG(avg_berth_wait_days) as port_avg_wait_days, "
            "SUM(vessel_queue_count) as total_queue, "
            "MAX(congestion_level) as worst_congestion "
            "FROM port_congestion WHERE port_code = ? AND report_date = ?",
            (port_code, latest_date)
        )
        agg = c.fetchone()
        conn.close()
        return {
            "port_code": port_code,
            "report_date": latest_date,
            "avg_berth_wait_days": round(agg["port_avg_wait_days"], 1),
            "total_vessel_queue": agg["total_queue"],
            "worst_congestion_level": agg["worst_congestion"],
            "terminal_count": 1  # from the single latest-date query
        }

    @tool(
        description="Gets historical customs clearance statistics for a specific port and commodity combination. Returns the most recent period's average clearance time in hours, 95th percentile clearance time, and flagged inspection rate.",
        parameters={
            "type": "object",
            "properties": {
                "port_code": {
                    "type": "string",
                    "description": "Port code (e.g. CNSHA, USLAX)"
                },
                "commodity_code": {
                    "type": "string",
                    "description": "Commodity code (e.g. ELEC, TEXT, MACH, FOOD, CHEM, AUTO, PHAR, RAWM, FURN, TOYS)"
                }
            },
            "required": ["port_code", "commodity_code"]
        }
    )
    def get_customs_clearance_stats(self, port_code: str, commodity_code: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM customs_history WHERE port_code = ? AND commodity_code = ? "
            "ORDER BY period DESC LIMIT 1",
            (port_code, commodity_code)
        )
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"No customs data for {port_code}/{commodity_code}"}
        return dict(row)

    @tool(
        description="Gets shipper contract details including contract tier and daily penalty rate for late delivery.",
        parameters={
            "type": "object",
            "properties": {
                "shipper_id": {
                    "type": "string",
                    "description": "Shipper identifier (e.g. SHP-0001)"
                }
            },
            "required": ["shipper_id"]
        }
    )
    def get_shipper_info(self, shipper_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM shippers WHERE shipper_id = ?", (shipper_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Shipper {shipper_id} not found"}
        return dict(row)

    def _compute_ground_truth(self):
        """Compute the ground truth alert list from database and workspace files."""
        # Load workspace config files
        risk_thresholds_path = os.path.join(self.workspace, "risk_thresholds.json")
        with open(risk_thresholds_path, "r") as f:
            risk_config = json.load(f)

        incoterms_path = os.path.join(self.workspace, "incoterms_guide.yaml")
        with open(incoterms_path, "r") as f:
            incoterms_config = yaml.safe_load(f)

        playbook_path = os.path.join(self.workspace, "contingency_playbook.json")
        with open(playbook_path, "r") as f:
            playbook = json.load(f)

        # Load all route deviation data from workspace
        vessel_deviations = {}  # vessel_id -> total delay hours
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "route_updates_*.json"))):
            with open(fpath, "r") as f:
                data = json.load(f)
            for record in data.get("route_deviation_reports", []):
                vid = record["vessel_id"]
                vessel_deviations[vid] = vessel_deviations.get(vid, 0) + record["delay_hours"]

        # Load customs modifiers from workspace
        customs_modifiers = {}  # (port_code, commodity_code) -> multiplier
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "customs_modifiers_*.csv"))):
            with open(fpath, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (row["port_code"], row["commodity_code"])
                    customs_modifiers[key] = float(row["clearance_multiplier"])

        # Load contract amendments from workspace
        deadline_extensions = {}  # shipment_id -> extension_days
        priority_upgrades = {}   # shipment_id -> customs_time_reduction_pct
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "contract_amendments_*.yaml"))):
            with open(fpath, "r") as f:
                data = yaml.safe_load(f)
            for amend in data.get("contract_amendments", []):
                sid = amend["shipment_id"]
                if amend["amendment_type"] == "deadline_extension":
                    deadline_extensions[sid] = deadline_extensions.get(sid, 0) + amend["extension_days"]
                elif amend["amendment_type"] == "priority_upgrade":
                    priority_upgrades[sid] = amend["customs_time_reduction_pct"]

        # Load port advisories from workspace
        port_extra_wait = {}  # port_code -> extra_wait_days
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "port_advisories_*.md"))):
            with open(fpath, "r") as f:
                content = f.read()
            # Parse markdown advisories
            import re
            sections = re.split(r'## ', content)
            for section in sections:
                if not section.strip():
                    continue
                code_match = re.search(r'\(([A-Z]{5})\)', section)
                wait_match = re.search(r'\*\*Additional Wait Days:\*\*\s*([\d.]+)', section)
                if code_match and wait_match:
                    pc = code_match.group(1)
                    extra = float(wait_match.group(1))
                    # Take max if multiple advisories for same port
                    port_extra_wait[pc] = max(port_extra_wait.get(pc, 0), extra)

        # Get all in-transit shipments from DB
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT * FROM shipments WHERE status = 'in_transit' ORDER BY shipment_id")
        shipments = [dict(r) for r in c.fetchall()]

        alerts = []
        for ship in shipments:
            sid = ship["shipment_id"]
            vid = ship["vessel_id"]
            dest = ship["dest_port"]
            commodity = ship["commodity_code"]
            incoterm = ship["incoterm"]
            contract_date = datetime.strptime(ship["contract_delivery_date"], "%Y-%m-%d")

            # Get vessel ETA
            c.execute("SELECT * FROM vessels WHERE vessel_id = ?", (vid,))
            vessel = dict(c.fetchone())
            vessel_eta = datetime.strptime(vessel["eta_destination"], "%Y-%m-%d")

            # Get port congestion - average wait days for latest report date
            c.execute(
                "SELECT MAX(report_date) as latest FROM port_congestion WHERE port_code = ?",
                (dest,)
            )
            latest_res = c.fetchone()
            port_wait = 0.0
            if latest_res and latest_res["latest"]:
                c.execute(
                    "SELECT AVG(avg_berth_wait_days) as avg_wait "
                    "FROM port_congestion WHERE port_code = ? AND report_date = ?",
                    (dest, latest_res["latest"])
                )
                wait_res = c.fetchone()
                if wait_res and wait_res["avg_wait"] is not None:
                    port_wait = wait_res["avg_wait"]

            # Get customs clearance - most recent period
            c.execute(
                "SELECT avg_clearance_hours FROM customs_history "
                "WHERE port_code = ? AND commodity_code = ? ORDER BY period DESC LIMIT 1",
                (dest, commodity)
            )
            customs_res = c.fetchone()
            customs_hours = 0.0
            if customs_res:
                customs_hours = customs_res["avg_clearance_hours"]

            # Apply customs modifier from workspace
            mod_key = (dest, commodity)
            customs_multiplier = customs_modifiers.get(mod_key, 1.0)
            adjusted_customs_hours = customs_hours * customs_multiplier

            # Apply priority upgrade reduction from workspace
            if sid in priority_upgrades:
                reduction_pct = priority_upgrades[sid]
                adjusted_customs_hours *= (1 - reduction_pct / 100.0)

            customs_days = adjusted_customs_hours / 24.0

            # Route deviation delay from workspace
            deviation_hours = vessel_deviations.get(vid, 0)
            deviation_days = deviation_hours / 24.0

            # Port advisory extra wait from workspace
            extra_wait = port_extra_wait.get(dest, 0)

            # Total expected arrival
            total_additional_days = port_wait + customs_days + deviation_days + extra_wait
            expected_arrival = vessel_eta + timedelta(days=total_additional_days)

            # Apply deadline extension from workspace
            extension_days = deadline_extensions.get(sid, 0)
            effective_deadline = contract_date + timedelta(days=extension_days)

            # Calculate delay
            delay_days = (expected_arrival - effective_deadline).days

            if delay_days < 1:
                continue

            # Classify risk
            risk_level = "LOW"
            for level in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
                threshold = risk_config["risk_levels"][level]["min_delay_days"]
                if delay_days >= threshold:
                    risk_level = level
                    break

            # Determine risk bearer from incoterms
            risk_bearer = incoterms_config["incoterms"][incoterm]["risk_bearer"]

            # Get contingency actions
            actions = playbook["contingency_actions"].get(risk_level, {}).get(risk_bearer, [])
            recommended_action = actions[0] if actions else "No action defined"

            # Get shipper info for penalty
            c.execute("SELECT * FROM shippers WHERE shipper_id = ?", (ship["shipper_id"],))
            shipper = dict(c.fetchone())
            penalty_per_day = shipper["penalty_rate_usd_per_day"]
            estimated_penalty = round(penalty_per_day * delay_days, 2)

            alerts.append({
                "shipment_id": sid,
                "risk_level": risk_level,
                "delay_days": delay_days,
                "vessel_id": vid,
                "vessel_name": vessel["vessel_name"],
                "destination_port": dest,
                "contract_delivery_date": ship["contract_delivery_date"],
                "expected_arrival_date": expected_arrival.strftime("%Y-%m-%d"),
                "incoterm": incoterm,
                "risk_bearer": risk_bearer,
                "recommended_action": recommended_action,
                "estimated_penalty_usd": estimated_penalty,
                "shipper_id": ship["shipper_id"]
            })

        conn.close()

        # Sort: by risk level priority, then delay_days descending
        risk_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        alerts.sort(key=lambda x: (risk_order.get(x["risk_level"], 99), -x["delay_days"]))

        return alerts

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
        ground_truth = self._compute_ground_truth()
        gt_ids = set(a["shipment_id"] for a in ground_truth)
        gt_by_id = {a["shipment_id"]: a for a in ground_truth}

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: alerts.csv exists with correct columns (10 pts) ---
        c1_max = 10
        max_score += c1_max
        alerts_path = os.path.join(self.workspace, "alerts.csv")
        expected_cols = ["shipment_id", "risk_level", "delay_days", "vessel_id",
                         "vessel_name", "destination_port", "contract_delivery_date",
                         "expected_arrival_date", "incoterm", "risk_bearer",
                         "recommended_action", "estimated_penalty_usd"]
        if os.path.exists(alerts_path):
            try:
                with open(alerts_path, "r") as f:
                    reader = csv.DictReader(f)
                    actual_cols = reader.fieldnames or []
                    agent_alerts = list(reader)
                missing_cols = set(expected_cols) - set(actual_cols)
                if not missing_cols:
                    eval_criteria["alerts_file_structure"] = {
                        "passed": True, "score": c1_max, "max_score": c1_max
                    }
                    total_score += c1_max
                else:
                    eval_criteria["alerts_file_structure"] = {
                        "passed": False, "score": 5, "max_score": c1_max,
                        "reason": f"Missing columns: {missing_cols}"
                    }
                    total_score += 5
            except Exception as e:
                eval_criteria["alerts_file_structure"] = {
                    "passed": False, "score": 0, "max_score": c1_max,
                    "reason": f"Error reading alerts.csv: {str(e)}"
                }
                agent_alerts = []
        else:
            eval_criteria["alerts_file_structure"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "alerts.csv not found in workspace"
            }
            agent_alerts = []

        # --- Criterion 2: Correct identification of at-risk shipments (25 pts) ---
        c2_max = 25
        max_score += c2_max
        agent_ids = set()
        for row in agent_alerts:
            sid = row.get("shipment_id", "").strip()
            if sid:
                agent_ids.add(sid)

        if gt_ids:
            correct = agent_ids & gt_ids
            false_positives = agent_ids - gt_ids
            false_negatives = gt_ids - agent_ids
            precision = len(correct) / len(agent_ids) if agent_ids else 0
            recall = len(correct) / len(gt_ids)
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            c2_score = round(c2_max * f1)
            eval_criteria["at_risk_identification"] = {
                "passed": f1 >= 0.99,
                "score": c2_score,
                "max_score": c2_max,
                "reason": f"F1={f1:.3f}, correct={len(correct)}, FP={len(false_positives)}, FN={len(false_negatives)}"
            }
            total_score += c2_score
        else:
            eval_criteria["at_risk_identification"] = {
                "passed": len(agent_ids) == 0,
                "score": c2_max if len(agent_ids) == 0 else 0,
                "max_score": c2_max
            }
            total_score += c2_max if len(agent_ids) == 0 else 0

        # --- Criterion 3: Correct risk level classification (20 pts) ---
        c3_max = 20
        max_score += c3_max
        agent_by_id = {}
        for row in agent_alerts:
            sid = row.get("shipment_id", "").strip()
            if sid:
                agent_by_id[sid] = row

        correct_levels = 0
        total_comparable = 0
        for sid in gt_ids & agent_ids:
            total_comparable += 1
            gt_level = gt_by_id[sid]["risk_level"]
            agent_level = agent_by_id.get(sid, {}).get("risk_level", "").strip().upper()
            if gt_level == agent_level:
                correct_levels += 1

        if total_comparable > 0:
            level_acc = correct_levels / total_comparable
            c3_score = round(c3_max * level_acc)
        else:
            level_acc = 0
            c3_score = 0
        eval_criteria["risk_classification"] = {
            "passed": level_acc >= 0.99,
            "score": c3_score,
            "max_score": c3_max,
            "reason": f"Accuracy={level_acc:.3f}, correct={correct_levels}/{total_comparable}"
        }
        total_score += c3_score

        # --- Criterion 4: Correct delay calculation (15 pts) ---
        c4_max = 15
        max_score += c4_max
        correct_delays = 0
        for sid in gt_ids & agent_ids:
            gt_delay = gt_by_id[sid]["delay_days"]
            try:
                agent_delay = int(agent_by_id.get(sid, {}).get("delay_days", -999))
            except (ValueError, TypeError):
                try:
                    agent_delay = round(float(agent_by_id.get(sid, {}).get("delay_days", -999)))
                except (ValueError, TypeError):
                    agent_delay = -999
            if abs(gt_delay - agent_delay) <= 1:
                correct_delays += 1

        if total_comparable > 0:
            delay_acc = correct_delays / total_comparable
            c4_score = round(c4_max * delay_acc)
        else:
            delay_acc = 0
            c4_score = 0
        eval_criteria["delay_calculation"] = {
            "passed": delay_acc >= 0.99,
            "score": c4_score,
            "max_score": c4_max,
            "reason": f"Accuracy={delay_acc:.3f}, within_tolerance={correct_delays}/{total_comparable}"
        }
        total_score += c4_score

        # --- Criterion 5: Correct contingency actions (15 pts) ---
        c5_max = 15
        max_score += c5_max
        correct_actions = 0
        for sid in gt_ids & agent_ids:
            gt_action = gt_by_id[sid]["recommended_action"]
            agent_action = agent_by_id.get(sid, {}).get("recommended_action", "").strip()
            if gt_action.lower() == agent_action.lower():
                correct_actions += 1

        if total_comparable > 0:
            action_acc = correct_actions / total_comparable
            c5_score = round(c5_max * action_acc)
        else:
            action_acc = 0
            c5_score = 0
        eval_criteria["contingency_actions"] = {
            "passed": action_acc >= 0.99,
            "score": c5_score,
            "max_score": c5_max,
            "reason": f"Accuracy={action_acc:.3f}, correct={correct_actions}/{total_comparable}"
        }
        total_score += c5_score

        # --- Criterion 6: Correct sort order (15 pts) ---
        c6_max = 15
        max_score += c6_max
        if len(agent_alerts) >= 2:
            risk_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
            is_sorted = True
            for i in range(len(agent_alerts) - 1):
                cur_level = agent_alerts[i].get("risk_level", "").strip().upper()
                nxt_level = agent_alerts[i+1].get("risk_level", "").strip().upper()
                cur_ord = risk_order.get(cur_level, 99)
                nxt_ord = risk_order.get(nxt_level, 99)
                if cur_ord > nxt_ord:
                    is_sorted = False
                    break
                if cur_ord == nxt_ord:
                    try:
                        cur_delay = float(agent_alerts[i].get("delay_days", 0))
                        nxt_delay = float(agent_alerts[i+1].get("delay_days", 0))
                        if cur_delay < nxt_delay:
                            is_sorted = False
                            break
                    except (ValueError, TypeError):
                        pass
            c6_score = c6_max if is_sorted else 0
            eval_criteria["sort_order"] = {
                "passed": is_sorted,
                "score": c6_score,
                "max_score": c6_max,
                "reason": "Correctly sorted" if is_sorted else "Sort order incorrect: expected CRITICAL>HIGH>MEDIUM>LOW, then by delay_days descending"
            }
        elif len(agent_alerts) <= 1:
            c6_score = c6_max
            eval_criteria["sort_order"] = {
                "passed": True, "score": c6_max, "max_score": c6_max
            }
        else:
            c6_score = 0
            eval_criteria["sort_order"] = {
                "passed": False, "score": 0, "max_score": c6_max,
                "reason": "No alerts to check sort order"
            }
        total_score += c6_score

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

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
        import re

        # Step 1: Read workspace config files
        with open(os.path.join(self.workspace, "risk_thresholds.json"), "r") as f:
            risk_config = json.load(f)

        with open(os.path.join(self.workspace, "incoterms_guide.yaml"), "r") as f:
            incoterms_config = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "contingency_playbook.json"), "r") as f:
            playbook = json.load(f)

        # Step 2: Load route deviation data from workspace
        vessel_deviations = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "route_updates_*.json"))):
            with open(fpath, "r") as f:
                data = json.load(f)
            for record in data.get("route_deviation_reports", []):
                vid = record["vessel_id"]
                vessel_deviations[vid] = vessel_deviations.get(vid, 0) + record["delay_hours"]

        # Step 3: Load customs modifiers from workspace
        customs_modifiers = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "customs_modifiers_*.csv"))):
            with open(fpath, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (row["port_code"], row["commodity_code"])
                    customs_modifiers[key] = float(row["clearance_multiplier"])

        # Step 4: Load contract amendments from workspace
        deadline_extensions = {}
        priority_upgrades = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "contract_amendments_*.yaml"))):
            with open(fpath, "r") as f:
                data = yaml.safe_load(f)
            for amend in data.get("contract_amendments", []):
                sid = amend["shipment_id"]
                if amend["amendment_type"] == "deadline_extension":
                    deadline_extensions[sid] = deadline_extensions.get(sid, 0) + amend["extension_days"]
                elif amend["amendment_type"] == "priority_upgrade":
                    priority_upgrades[sid] = amend["customs_time_reduction_pct"]

        # Step 5: Load port advisories from workspace
        port_extra_wait = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "port_advisories_*.md"))):
            with open(fpath, "r") as f:
                content = f.read()
            sections = re.split(r'## ', content)
            for section in sections:
                if not section.strip():
                    continue
                code_match = re.search(r'\(([A-Z]{5})\)', section)
                wait_match = re.search(r'\*\*Additional Wait Days:\*\*\s*([\d.]+)', section)
                if code_match and wait_match:
                    pc = code_match.group(1)
                    extra = float(wait_match.group(1))
                    port_extra_wait[pc] = max(port_extra_wait.get(pc, 0), extra)

        # Step 6: List all in-transit shipments via tool calls
        all_shipments = []
        page = 1
        tool_call_count = 0
        while True:
            result = self.tools["list_shipments"](status="in_transit", page=page, page_size=20)
            tool_call_count += 1
            all_shipments.extend(result["shipments"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 7: For each shipment, gather vessel, port, customs, shipper data via tools
        vessel_cache = {}
        port_congestion_cache = {}
        customs_cache = {}
        shipper_cache = {}

        alerts = []
        for ship in all_shipments:
            sid = ship["shipment_id"]
            vid = ship["vessel_id"]
            dest = ship["dest_port"]
            commodity = ship["commodity_code"]
            incoterm = ship["incoterm"]
            contract_date = datetime.strptime(ship["contract_delivery_date"], "%Y-%m-%d")

            # Get vessel position (cached)
            if vid not in vessel_cache:
                vessel_cache[vid] = self.tools["get_vessel_position"](vessel_id=vid)
                tool_call_count += 1
            vessel = vessel_cache[vid]
            vessel_eta = datetime.strptime(vessel["eta_destination"], "%Y-%m-%d")

            # Get port congestion (cached)
            if dest not in port_congestion_cache:
                port_congestion_cache[dest] = self.tools["get_port_congestion"](port_code=dest)
                tool_call_count += 1
            congestion = port_congestion_cache[dest]
            port_wait = congestion.get("avg_berth_wait_days", 0)

            # Get customs stats (cached)
            customs_key = (dest, commodity)
            if customs_key not in customs_cache:
                customs_cache[customs_key] = self.tools["get_customs_clearance_stats"](
                    port_code=dest, commodity_code=commodity
                )
                tool_call_count += 1
            customs_data = customs_cache[customs_key]
            customs_hours = customs_data.get("avg_clearance_hours", 0)

            # Apply customs modifier from workspace
            customs_multiplier = customs_modifiers.get(customs_key, 1.0)
            adjusted_customs_hours = customs_hours * customs_multiplier

            # Apply priority upgrade from workspace
            if sid in priority_upgrades:
                reduction_pct = priority_upgrades[sid]
                adjusted_customs_hours *= (1 - reduction_pct / 100.0)

            customs_days = adjusted_customs_hours / 24.0

            # Route deviation delay from workspace
            deviation_hours = vessel_deviations.get(vid, 0)
            deviation_days = deviation_hours / 24.0

            # Port advisory extra wait from workspace
            extra_wait = port_extra_wait.get(dest, 0)

            # Expected arrival
            total_additional_days = port_wait + customs_days + deviation_days + extra_wait
            expected_arrival = vessel_eta + timedelta(days=total_additional_days)

            # Effective deadline with extensions
            extension_days = deadline_extensions.get(sid, 0)
            effective_deadline = contract_date + timedelta(days=extension_days)

            # Delay
            delay_days = (expected_arrival - effective_deadline).days

            if delay_days < 1:
                continue

            # Risk level
            risk_level = "LOW"
            for level in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
                threshold = risk_config["risk_levels"][level]["min_delay_days"]
                if delay_days >= threshold:
                    risk_level = level
                    break

            # Risk bearer
            risk_bearer = incoterms_config["incoterms"][incoterm]["risk_bearer"]

            # Contingency action
            actions = playbook["contingency_actions"].get(risk_level, {}).get(risk_bearer, [])
            recommended_action = actions[0] if actions else "No action defined"

            # Get shipper info (cached)
            shipper_id = ship["shipper_id"]
            if shipper_id not in shipper_cache:
                shipper_cache[shipper_id] = self.tools["get_shipper_info"](shipper_id=shipper_id)
                tool_call_count += 1
            shipper = shipper_cache[shipper_id]
            penalty_per_day = shipper["penalty_rate_usd_per_day"]
            estimated_penalty = round(penalty_per_day * delay_days, 2)

            alerts.append({
                "shipment_id": sid,
                "risk_level": risk_level,
                "delay_days": delay_days,
                "vessel_id": vid,
                "vessel_name": vessel["vessel_name"],
                "destination_port": dest,
                "contract_delivery_date": ship["contract_delivery_date"],
                "expected_arrival_date": expected_arrival.strftime("%Y-%m-%d"),
                "incoterm": incoterm,
                "risk_bearer": risk_bearer,
                "recommended_action": recommended_action,
                "estimated_penalty_usd": estimated_penalty,
                "shipper_id": shipper_id
            })

        # Sort alerts
        risk_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        alerts.sort(key=lambda x: (risk_order.get(x["risk_level"], 99), -x["delay_days"]))

        # Write alerts.csv
        alerts_path = os.path.join(self.workspace, "alerts.csv")
        fieldnames = ["shipment_id", "risk_level", "delay_days", "vessel_id",
                       "vessel_name", "destination_port", "contract_delivery_date",
                       "expected_arrival_date", "incoterm", "risk_bearer",
                       "recommended_action", "estimated_penalty_usd"]
        with open(alerts_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for alert in alerts:
                writer.writerow({k: alert[k] for k in fieldnames})

        # Build response summary
        risk_counts = {}
        for a in alerts:
            risk_counts[a["risk_level"]] = risk_counts.get(a["risk_level"], 0) + 1

        summary_lines = [
            f"Shipment Risk Assessment Complete.",
            f"Total in-transit shipments analyzed: {len(all_shipments)}",
            f"Total at-risk shipments identified: {len(alerts)}",
            f"Risk breakdown: " + ", ".join(f"{k}: {v}" for k, v in sorted(risk_counts.items(), key=lambda x: risk_order.get(x[0], 99))),
            "",
            "Top critical shipments:"
        ]
        for a in alerts[:3]:
            summary_lines.append(
                f"  - {a['shipment_id']}: {a['risk_level']} risk, {a['delay_days']} days delay, "
                f"vessel {a['vessel_name']} to {a['destination_port']}, "
                f"action: {a['recommended_action']}"
            )

        summary_lines.append(f"\nAlerts saved to alerts.csv with {len(alerts)} entries.")
        summary_lines.append(f"Tool calls made: {tool_call_count}")

        action = "\n".join(summary_lines)
        return self.step(action)
