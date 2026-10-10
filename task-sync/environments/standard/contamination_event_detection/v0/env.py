import sqlite3
import os
import json
import csv
import glob
from datetime import datetime
from typing import Tuple, Dict, List, Any


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
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

    # ── Tool Methods ──────────────────────────────────────────────────

    @tool(
        description="List all warehouse IDs and their basic information.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    def list_warehouses(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT warehouse_id, name, location, capacity_tons FROM warehouses")
        rows = c.fetchall()
        conn.close()
        return [{"warehouse_id": r[0], "name": r[1], "location": r[2], "capacity_tons": r[3]} for r in rows]

    @tool(
        description="List all zones in a given warehouse with their types and capacities.",
        parameters={
            "type": "object",
            "properties": {
                "warehouse_id": {
                    "type": "string",
                    "description": "The warehouse ID, e.g. 'WH-001'"
                }
            },
            "required": ["warehouse_id"]
        }
    )
    def get_warehouse_zones(self, warehouse_id: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT zone_id, zone_name, zone_type, capacity_tons FROM zones WHERE warehouse_id = ?",
                  (warehouse_id,))
        rows = c.fetchall()
        conn.close()
        return [{"zone_id": r[0], "zone_name": r[1], "zone_type": r[2], "capacity_tons": r[3]} for r in rows]

    @tool(
        description="List all lot IDs currently stored in a specific zone. Returns lot IDs, crop types, and statuses only.",
        parameters={
            "type": "object",
            "properties": {
                "warehouse_id": {
                    "type": "string",
                    "description": "The warehouse ID"
                },
                "zone_id": {
                    "type": "string",
                    "description": "The zone ID, e.g. 'WH-001-A'"
                }
            },
            "required": ["warehouse_id", "zone_id"]
        }
    )
    def get_lots_in_zone(self, warehouse_id: str, zone_id: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""SELECT lot_id, crop_type, status FROM seed_lots
                     WHERE current_warehouse_id = ? AND current_zone_id = ?""",
                  (warehouse_id, zone_id))
        rows = c.fetchall()
        conn.close()
        return [{"lot_id": r[0], "crop_type": r[1], "status": r[2]} for r in rows]

    @tool(
        description="Get the current location details for a specific seed lot.",
        parameters={
            "type": "object",
            "properties": {
                "lot_id": {
                    "type": "string",
                    "description": "The lot ID, e.g. 'LOT-0001'"
                }
            },
            "required": ["lot_id"]
        }
    )
    def get_lot_current_location(self, lot_id: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""SELECT lot_id, crop_type, variety, current_warehouse_id, current_zone_id,
                     status, arrival_date FROM seed_lots WHERE lot_id = ?""", (lot_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Lot {lot_id} not found"}
        return {
            "lot_id": row[0], "crop_type": row[1], "variety": row[2],
            "current_warehouse_id": row[3], "current_zone_id": row[4],
            "status": row[5], "arrival_date": row[6]
        }

    @tool(
        description="Get the movement history for a specific seed lot, ordered by move date.",
        parameters={
            "type": "object",
            "properties": {
                "lot_id": {
                    "type": "string",
                    "description": "The lot ID"
                }
            },
            "required": ["lot_id"]
        }
    )
    def get_lot_movement_history(self, lot_id: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""SELECT movement_id, from_warehouse_id, from_zone_id,
                     to_warehouse_id, to_zone_id, move_date, reason
                     FROM lot_movements WHERE lot_id = ? ORDER BY move_date""", (lot_id,))
        rows = c.fetchall()
        conn.close()
        return [{"movement_id": r[0], "from_warehouse_id": r[1], "from_zone_id": r[2],
                 "to_warehouse_id": r[3], "to_zone_id": r[4], "move_date": r[5],
                 "reason": r[6]} for r in rows]

    @tool(
        description="Get pest treatment records for a specific zone. Returns all treatment records ordered by date_applied.",
        parameters={
            "type": "object",
            "properties": {
                "warehouse_id": {
                    "type": "string",
                    "description": "The warehouse ID"
                },
                "zone_id": {
                    "type": "string",
                    "description": "The zone ID"
                }
            },
            "required": ["warehouse_id", "zone_id"]
        }
    )
    def get_pest_treatment_schedule(self, warehouse_id: str, zone_id: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""SELECT treatment_id, treatment_type, chemical_used,
                     date_applied, next_due_date, effectiveness_pct
                     FROM pest_treatments
                     WHERE warehouse_id = ? AND zone_id = ?
                     ORDER BY date_applied""",
                  (warehouse_id, zone_id))
        rows = c.fetchall()
        conn.close()
        return [{"treatment_id": r[0], "treatment_type": r[1], "chemical_used": r[2],
                 "date_applied": r[3], "next_due_date": r[4], "effectiveness_pct": r[5]} for r in rows]

    @tool(
        description="Get phytosanitary inspection results for a specific lot. Returns all inspections ordered by date.",
        parameters={
            "type": "object",
            "properties": {
                "lot_id": {
                    "type": "string",
                    "description": "The lot ID"
                }
            },
            "required": ["lot_id"]
        }
    )
    def get_phytosanitary_results(self, lot_id: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""SELECT inspection_id, inspection_date, inspector,
                     pest_detected, disease_detected, severity, result_status
                     FROM phytosanitary_inspections
                     WHERE lot_id = ? ORDER BY inspection_date""", (lot_id,))
        rows = c.fetchall()
        conn.close()
        return [{"inspection_id": r[0], "inspection_date": r[1], "inspector": r[2],
                 "pest_detected": r[3], "disease_detected": r[4], "severity": r[5],
                 "result_status": r[6]} for r in rows]

    @tool(
        description="Get sensor readings for a specific zone on a given date. Returns individual readings with timestamps.",
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "string",
                    "description": "The zone ID, e.g. 'WH-001-A'"
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format"
                }
            },
            "required": ["zone_id", "date"]
        }
    )
    def get_sensor_readings(self, zone_id: str, date: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""SELECT log_id, timestamp, temperature, humidity, co2_ppm
                     FROM sensor_logs
                     WHERE zone_id = ? AND DATE(timestamp) = ?
                     ORDER BY timestamp""", (zone_id, date))
        rows = c.fetchall()
        conn.close()
        return [{"log_id": r[0], "timestamp": r[1], "temperature": r[2],
                 "humidity": r[3], "co2_ppm": r[4]} for r in rows]

    @tool(
        description="List all lot IDs that have at least one phytosanitary inspection with the given result status (PASS, FAIL, or CONDITIONAL).",
        parameters={
            "type": "object",
            "properties": {
                "result_status": {
                    "type": "string",
                    "enum": ["PASS", "FAIL", "CONDITIONAL"],
                    "description": "Filter by inspection result"
                }
            },
            "required": ["result_status"]
        }
    )
    def list_lots_by_inspection_result(self, result_status: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""SELECT DISTINCT lot_id FROM phytosanitary_inspections
                     WHERE result_status = ? ORDER BY lot_id""", (result_status,))
        rows = c.fetchall()
        conn.close()
        return [r[0] for r in rows]

    # ── Evaluation ────────────────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute the full ground truth quarantine advisory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Load config files
        with open(os.path.join(self.workspace, "quarantine_rules.json")) as f:
            rules = json.load(f)
        with open(os.path.join(self.workspace, "contamination_thresholds.yaml")) as f:
            import yaml
            thresholds = yaml.safe_load(f)["crop_thresholds"]

        ref_date = datetime.strptime(rules["reference_date"], "%Y-%m-%d")
        grace_days = rules["overdue_grace_days"]
        weights = rules["risk_weights"]

        # Load zone adjacency
        adj_map = {}  # zone_id -> set of adjacent zone_ids
        with open(os.path.join(self.workspace, "zone_adjacency.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                adj_map.setdefault(row["zone_id"], set()).add(row["adjacent_zone_id"])

        # Get all lots
        c.execute("SELECT * FROM seed_lots")
        all_lots = [dict(r) for r in c.fetchall()]

        # Get all sensor logs
        c.execute("SELECT * FROM sensor_logs")
        all_sensors = [dict(r) for r in c.fetchall()]

        # Get all pest treatments
        c.execute("SELECT * FROM pest_treatments")
        all_treatments = [dict(r) for r in c.fetchall()]

        # Get all inspections
        c.execute("SELECT * FROM phytosanitary_inspections")
        all_inspections = [dict(r) for r in c.fetchall()]

        # Get all movements
        c.execute("SELECT * FROM lot_movements")
        all_movements = [dict(r) for r in c.fetchall()]

        conn.close()

        # ── 1. Identify zones with sensor exceedances per crop type ──
        # For each zone+date, find max temperature and humidity
        from collections import defaultdict
        zone_date_sensors = defaultdict(list)
        for s in all_sensors:
            dt = datetime.strptime(s["timestamp"], "%Y-%m-%d %H:%M:%S").date()
            zone_date_sensors[(s["zone_id"], str(dt))].append(s)

        # For each zone+date, compute max readings
        zone_date_maxes = {}
        for (zone_id, date_str), readings in zone_date_sensors.items():
            max_t = max(r["temperature"] for r in readings)
            max_h = max(r["humidity"] for r in readings)
            zone_date_maxes[(zone_id, date_str)] = {"max_temp": max_t, "max_humidity": max_h}

        # ── 2. Identify overdue treatment zones ──
        # For each zone, find latest treatment and check if overdue
        zone_latest_treatment = {}
        for t in all_treatments:
            zone_id = t["zone_id"]
            if zone_id not in zone_latest_treatment or t["date_applied"] > zone_latest_treatment[zone_id]["date_applied"]:
                zone_latest_treatment[zone_id] = t

        overdue_zones = set()
        from datetime import timedelta
        cutoff_date = ref_date - timedelta(days=grace_days)
        for zone_id, t in zone_latest_treatment.items():
            next_due = datetime.strptime(t["next_due_date"], "%Y-%m-%d")
            if next_due < cutoff_date:
                overdue_zones.add(zone_id)

        # ── 3. Identify lots with FAIL inspections ──
        failed_lots = set()
        for insp in all_inspections:
            if insp["result_status"] == "FAIL":
                failed_lots.add(insp["lot_id"])

        # Map failed lots to their current zones
        failed_lot_zones = set()
        for lot in all_lots:
            if lot["lot_id"] in failed_lots:
                failed_lot_zones.add(lot["current_zone_id"])

        # ── 4. Compute flags for each lot ──
        advisory = []
        for lot in all_lots:
            flags = set()
            lot_id = lot["lot_id"]
            crop = lot["crop_type"]
            current_zone = lot["current_zone_id"]
            current_wh = lot["current_warehouse_id"]
            arrival = lot["arrival_date"]

            crop_thresh = thresholds.get(crop, {})
            max_temp_thresh = crop_thresh.get("max_temperature", 999)
            max_hum_thresh = crop_thresh.get("max_humidity", 999)

            # FLAG 1: SENSOR_EXCEEDANCE - current zone had readings above
            # crop-specific thresholds during lot's stay
            for (zid, date_str), maxes in zone_date_maxes.items():
                if zid == current_zone and date_str >= arrival:
                    if maxes["max_temp"] > max_temp_thresh or maxes["max_humidity"] > max_hum_thresh:
                        flags.add("SENSOR_EXCEEDANCE")
                        break

            # FLAG 2: ADJACENT_CONTAMINATION - lot is in zone adjacent to
            # a zone containing a lot with FAIL inspection
            adjacent_zones = adj_map.get(current_zone, set())
            for adj_zone in adjacent_zones:
                if adj_zone in failed_lot_zones:
                    flags.add("ADJACENT_CONTAMINATION")
                    break

            # FLAG 3: OVERDUE_TREATMENT - current zone has overdue pest treatment
            if current_zone in overdue_zones:
                flags.add("OVERDUE_TREATMENT")

            # FLAG 4: MOVEMENT_EXPOSURE - lot was previously in a zone with
            # sensor exceedances during its stay
            lot_moves = [m for m in all_movements if m["lot_id"] == lot_id]
            lot_moves.sort(key=lambda m: m["move_date"])
            for move in lot_moves:
                from_zone = move["from_zone_id"]
                move_date = move["move_date"]
                # Check sensor data for from_zone on dates up to move_date and
                # after lot arrival
                for (zid, date_str), maxes in zone_date_maxes.items():
                    if zid == from_zone and date_str >= arrival and date_str <= move_date:
                        if maxes["max_temp"] > max_temp_thresh or maxes["max_humidity"] > max_hum_thresh:
                            flags.add("MOVEMENT_EXPOSURE")
                            break
                if "MOVEMENT_EXPOSURE" in flags:
                    break

            if flags:
                risk_score = sum(weights[f] for f in flags)
                # Determine action
                action = "STANDARD_REVIEW"
                for tier in rules["action_thresholds"]:
                    if risk_score >= tier["min_score"]:
                        action = tier["action"]
                        break

                advisory.append({
                    "lot_id": lot_id,
                    "crop_type": crop,
                    "variety": lot["variety"],
                    "current_warehouse": current_wh,
                    "current_zone": current_zone,
                    "risk_score": risk_score,
                    "contamination_flags": ", ".join(sorted(flags)),
                    "recommended_action": action,
                })

        # Sort by risk_score desc, then lot_id asc
        advisory.sort(key=lambda x: (-x["risk_score"], x["lot_id"]))
        return advisory

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        eval_criteria = {}
        ground_truth = self._compute_ground_truth()
        gt_lot_ids = set(r["lot_id"] for r in ground_truth)

        # ── Criterion 1: File exists with correct structure (10 pts) ──
        advisory_path = os.path.join(self.workspace, "quarantine_advisory.csv")
        c1_passed = False
        c1_score = 0
        submitted_rows = []
        expected_cols = {"lot_id", "crop_type", "variety", "current_warehouse",
                         "current_zone", "risk_score", "contamination_flags", "recommended_action"}
        if os.path.exists(advisory_path):
            try:
                with open(advisory_path, "r") as f:
                    reader = csv.DictReader(f)
                    cols = set(reader.fieldnames) if reader.fieldnames else set()
                    if expected_cols.issubset(cols):
                        submitted_rows = list(reader)
                        c1_passed = True
                        c1_score = 10
            except Exception:
                pass

        eval_criteria["file_structure"] = {
            "passed": c1_passed,
            "score": c1_score,
            "max_score": 10,
            "reason": "" if c1_passed else f"quarantine_advisory.csv missing or missing columns. Expected: {sorted(expected_cols)}"
        }

        # ── Criterion 2: Correct set of flagged lots (25 pts) ──
        c2_score = 0
        submitted_lot_ids = set(r["lot_id"] for r in submitted_rows) if submitted_rows else set()
        if gt_lot_ids and submitted_lot_ids:
            correct = submitted_lot_ids & gt_lot_ids
            precision = len(correct) / len(submitted_lot_ids) if submitted_lot_ids else 0
            recall = len(correct) / len(gt_lot_ids) if gt_lot_ids else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            c2_score = round(25 * f1)
        c2_passed = c2_score == 25

        eval_criteria["lot_identification"] = {
            "passed": c2_passed,
            "score": c2_score,
            "max_score": 25,
            "reason": "" if c2_passed else f"Expected {len(gt_lot_ids)} lots, got {len(submitted_lot_ids)}. Overlap: {len(submitted_lot_ids & gt_lot_ids)}"
        }

        # Build lookup for submitted rows
        submitted_map = {r["lot_id"]: r for r in submitted_rows}
        gt_map = {r["lot_id"]: r for r in ground_truth}

        # ── Criterion 3: Correct contamination flags (20 pts) ──
        c3_correct = 0
        c3_total = len(gt_lot_ids)
        for lot_id in gt_lot_ids:
            if lot_id in submitted_map:
                gt_flags = set(f.strip() for f in gt_map[lot_id]["contamination_flags"].split(","))
                sub_flags = set(f.strip() for f in submitted_map[lot_id].get("contamination_flags", "").split(","))
                if gt_flags == sub_flags:
                    c3_correct += 1
        c3_score = round(20 * c3_correct / c3_total) if c3_total > 0 else 0
        c3_passed = c3_score == 20

        eval_criteria["contamination_flags"] = {
            "passed": c3_passed,
            "score": c3_score,
            "max_score": 20,
            "reason": "" if c3_passed else f"Correct flags for {c3_correct}/{c3_total} lots"
        }

        # ── Criterion 4: Correct risk scores (15 pts) ──
        c4_correct = 0
        for lot_id in gt_lot_ids:
            if lot_id in submitted_map:
                try:
                    sub_score = int(submitted_map[lot_id].get("risk_score", -1))
                    gt_score = gt_map[lot_id]["risk_score"]
                    if sub_score == gt_score:
                        c4_correct += 1
                except (ValueError, TypeError):
                    pass
        c4_score = round(15 * c4_correct / c3_total) if c3_total > 0 else 0
        c4_passed = c4_score == 15

        eval_criteria["risk_scores"] = {
            "passed": c4_passed,
            "score": c4_score,
            "max_score": 15,
            "reason": "" if c4_passed else f"Correct scores for {c4_correct}/{c3_total} lots"
        }

        # ── Criterion 5: Correct recommended actions (15 pts) ──
        c5_correct = 0
        for lot_id in gt_lot_ids:
            if lot_id in submitted_map:
                if submitted_map[lot_id].get("recommended_action", "").strip() == gt_map[lot_id]["recommended_action"]:
                    c5_correct += 1
        c5_score = round(15 * c5_correct / c3_total) if c3_total > 0 else 0
        c5_passed = c5_score == 15

        eval_criteria["recommended_actions"] = {
            "passed": c5_passed,
            "score": c5_score,
            "max_score": 15,
            "reason": "" if c5_passed else f"Correct actions for {c5_correct}/{c3_total} lots"
        }

        # ── Criterion 6: Response summary (15 pts) ──
        c6_score = 0
        c6_checks = []
        if action:
            total_flagged = len(ground_truth)
            # Count by action
            action_counts = {}
            for r in ground_truth:
                action_counts[r["recommended_action"]] = action_counts.get(r["recommended_action"], 0) + 1

            # Highest risk lot
            highest_risk = ground_truth[0] if ground_truth else None

            if str(total_flagged) in action:
                c6_score += 5
                c6_checks.append("total_count")
            if highest_risk and highest_risk["lot_id"] in action:
                c6_score += 5
                c6_checks.append("highest_risk_lot")
            if highest_risk and str(highest_risk["risk_score"]) in action:
                c6_score += 5
                c6_checks.append("highest_risk_score")

        c6_passed = c6_score == 15
        eval_criteria["response_summary"] = {
            "passed": c6_passed,
            "score": c6_score,
            "max_score": 15,
            "reason": "" if c6_passed else f"Missing summary elements. Found: {c6_checks}"
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

        return total_score / max_score, info

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml

        # ── Step 1: Read config files from workspace ──
        with open(os.path.join(self.workspace, "quarantine_rules.json")) as f:
            rules = json.load(f)

        with open(os.path.join(self.workspace, "contamination_thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)["crop_thresholds"]

        ref_date_str = rules["reference_date"]
        ref_date = datetime.strptime(ref_date_str, "%Y-%m-%d")
        grace_days = rules["overdue_grace_days"]
        weights = rules["risk_weights"]
        action_thresholds = rules["action_thresholds"]

        # Read zone adjacency
        adj_map = {}
        with open(os.path.join(self.workspace, "zone_adjacency.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                adj_map.setdefault(row["zone_id"], set()).add(row["adjacent_zone_id"])

        # Read lot manifests from workspace (for crop_type lookup by lot_id)
        manifest_files = sorted(glob.glob(os.path.join(self.workspace, "lot_manifest_batch_*.json")))
        lot_crop_map = {}
        lot_info_map = {}
        for mf in manifest_files:
            with open(mf) as f:
                for lot in json.load(f):
                    lot_crop_map[lot["lot_id"]] = lot["crop_type"]
                    lot_info_map[lot["lot_id"]] = lot

        # Read sensor report files to find zones/dates with anomalies
        sensor_files = sorted(glob.glob(os.path.join(self.workspace, "sensor_report_*.csv")))
        sensor_daily = []
        for sf in sensor_files:
            with open(sf) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sensor_daily.append(row)

        # Read movement log files
        movement_files = sorted(glob.glob(os.path.join(self.workspace, "movement_log_*.csv")))
        file_movements = []
        for mf in movement_files:
            with open(mf) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    file_movements.append(row)

        # Read pest treatment protocols
        with open(os.path.join(self.workspace, "pest_treatment_protocols.md")) as f:
            _ = f.read()  # Read for reference

        # ── Step 2: Use tools to discover warehouses and zones ──
        tool_call_count = 0

        warehouses = self.tools["list_warehouses"]()
        tool_call_count += 1

        all_zones = []
        for wh in warehouses:
            zones = self.tools["get_warehouse_zones"](warehouse_id=wh["warehouse_id"])
            tool_call_count += 1
            for z in zones:
                z["warehouse_id"] = wh["warehouse_id"]
            all_zones.extend(zones)

        # ── Step 3: For each zone, get lots and check conditions ──

        # 3a: Check pest treatment status for each zone
        from datetime import timedelta
        overdue_zones = set()
        cutoff_date = ref_date - timedelta(days=grace_days)

        for zone in all_zones:
            treatments = self.tools["get_pest_treatment_schedule"](
                warehouse_id=zone["warehouse_id"], zone_id=zone["zone_id"])
            tool_call_count += 1
            if treatments:
                # Find latest treatment by date_applied
                latest = max(treatments, key=lambda t: t["date_applied"])
                next_due = datetime.strptime(latest["next_due_date"], "%Y-%m-%d")
                if next_due < cutoff_date:
                    overdue_zones.add(zone["zone_id"])

        # 3b: Find lots with FAIL inspections
        failed_lot_ids = self.tools["list_lots_by_inspection_result"](result_status="FAIL")
        tool_call_count += 1

        # Get current zones for failed lots
        failed_lot_zones = set()
        for lot_id in failed_lot_ids:
            loc = self.tools["get_lot_current_location"](lot_id=lot_id)
            tool_call_count += 1
            if "error" not in loc:
                failed_lot_zones.add(loc["current_zone_id"])

        # 3c: Get all lots in each zone and their info
        all_lot_locations = {}  # lot_id -> {warehouse, zone, crop_type, ...}
        for zone in all_zones:
            lots_in_zone = self.tools["get_lots_in_zone"](
                warehouse_id=zone["warehouse_id"], zone_id=zone["zone_id"])
            tool_call_count += 1
            for lot in lots_in_zone:
                all_lot_locations[lot["lot_id"]] = {
                    "warehouse_id": zone["warehouse_id"],
                    "zone_id": zone["zone_id"],
                    "crop_type": lot["crop_type"],
                    "status": lot["status"],
                }

        # 3d: For each lot, determine contamination flags
        # Build zone+date max sensor readings from workspace files
        from collections import defaultdict
        zone_date_maxes = defaultdict(lambda: {"max_temp": -999, "max_humidity": -999})
        for row in sensor_daily:
            key = (row["zone_id"], row["date"])
            max_t = float(row["max_temperature"])
            max_h = float(row["max_humidity"])
            if max_t > zone_date_maxes[key]["max_temp"]:
                zone_date_maxes[key]["max_temp"] = max_t
            if max_h > zone_date_maxes[key]["max_humidity"]:
                zone_date_maxes[key]["max_humidity"] = max_h

        # Also need to use tool to get sensor readings for zones/dates not in reports
        # or to get more granular data. We'll use workspace data as primary source
        # since it aggregates from the same sensor logs.

        # Build per-lot movement history from files
        lot_file_movements = defaultdict(list)
        for m in file_movements:
            lot_file_movements[m["lot_id"]].append(m)

        advisory = []
        for lot_id, loc_info in all_lot_locations.items():
            flags = set()
            crop = loc_info["crop_type"]
            current_zone = loc_info["zone_id"]
            current_wh = loc_info["warehouse_id"]

            # Get lot details via tool for arrival date
            lot_detail = self.tools["get_lot_current_location"](lot_id=lot_id)
            tool_call_count += 1
            arrival_date = lot_detail.get("arrival_date", "2000-01-01")
            variety = lot_detail.get("variety", "")

            crop_thresh = thresholds.get(crop, {})
            max_temp_thresh = crop_thresh.get("max_temperature", 999)
            max_hum_thresh = crop_thresh.get("max_humidity", 999)

            # FLAG 1: SENSOR_EXCEEDANCE
            for (zid, date_str), maxes in zone_date_maxes.items():
                if zid == current_zone and date_str >= arrival_date:
                    if maxes["max_temp"] > max_temp_thresh or maxes["max_humidity"] > max_hum_thresh:
                        flags.add("SENSOR_EXCEEDANCE")
                        break

            # FLAG 2: ADJACENT_CONTAMINATION
            adjacent_zones = adj_map.get(current_zone, set())
            for adj_zone in adjacent_zones:
                if adj_zone in failed_lot_zones:
                    flags.add("ADJACENT_CONTAMINATION")
                    break

            # FLAG 3: OVERDUE_TREATMENT
            if current_zone in overdue_zones:
                flags.add("OVERDUE_TREATMENT")

            # FLAG 4: MOVEMENT_EXPOSURE - check via tool
            movements = self.tools["get_lot_movement_history"](lot_id=lot_id)
            tool_call_count += 1
            for move in movements:
                from_zone = move["from_zone_id"]
                move_date = move["move_date"]
                for (zid, date_str), maxes in zone_date_maxes.items():
                    if zid == from_zone and date_str >= arrival_date and date_str <= move_date:
                        if maxes["max_temp"] > max_temp_thresh or maxes["max_humidity"] > max_hum_thresh:
                            flags.add("MOVEMENT_EXPOSURE")
                            break
                if "MOVEMENT_EXPOSURE" in flags:
                    break

            if flags:
                risk_score = sum(weights[f] for f in flags)
                rec_action = "STANDARD_REVIEW"
                for tier in action_thresholds:
                    if risk_score >= tier["min_score"]:
                        rec_action = tier["action"]
                        break

                advisory.append({
                    "lot_id": lot_id,
                    "crop_type": crop,
                    "variety": variety,
                    "current_warehouse": current_wh,
                    "current_zone": current_zone,
                    "risk_score": risk_score,
                    "contamination_flags": ", ".join(sorted(flags)),
                    "recommended_action": rec_action,
                })

        # Sort by risk_score desc, lot_id asc
        advisory.sort(key=lambda x: (-x["risk_score"], x["lot_id"]))

        # ── Step 4: Write quarantine_advisory.csv ──
        advisory_path = os.path.join(self.workspace, "quarantine_advisory.csv")
        fieldnames = ["lot_id", "crop_type", "variety", "current_warehouse",
                      "current_zone", "risk_score", "contamination_flags", "recommended_action"]
        with open(advisory_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(advisory)

        # ── Step 5: Build action string ──
        total_flagged = len(advisory)
        action_counts = {}
        for r in advisory:
            action_counts[r["recommended_action"]] = action_counts.get(r["recommended_action"], 0) + 1

        highest = advisory[0] if advisory else None

        action_str = f"Quarantine advisory analysis complete. Total lots flagged: {total_flagged}. "
        for act_name in ["IMMEDIATE_QUARANTINE", "ENHANCED_MONITORING", "STANDARD_REVIEW"]:
            if act_name in action_counts:
                action_str += f"{act_name}: {action_counts[act_name]}. "
        if highest:
            action_str += f"Highest risk lot: {highest['lot_id']} with risk score {highest['risk_score']}."

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need at least 15"

        return self.step(action_str)
