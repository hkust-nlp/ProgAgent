#!/usr/bin/env python3
"""Environment for fuel theft / unauthorized vehicle usage detection task."""

import sqlite3
import os
import json
import csv
import math
import re
from typing import Tuple, Dict, List, Any
from datetime import datetime
from collections import defaultdict


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


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
    #  TOOLS
    # ================================================================

    @tool(
        description="List vehicles in the fleet. Optionally filter by depot. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "depot_id": {
                    "type": "integer",
                    "description": "Filter by depot ID (optional)"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1 (default 1)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 20, max 50)"
                },
            },
            "required": [],
        },
    )
    def list_vehicles(self, depot_id=None, page=1, page_size=20):
        page = max(1, int(page))
        page_size = max(1, min(50, int(page_size)))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if depot_id is not None:
            c.execute(
                "SELECT vehicle_id, plate_number, vehicle_type, depot_id "
                "FROM vehicles WHERE depot_id=? ORDER BY vehicle_id",
                (int(depot_id),),
            )
        else:
            c.execute(
                "SELECT vehicle_id, plate_number, vehicle_type, depot_id "
                "FROM vehicles ORDER BY vehicle_id"
            )
        rows = c.fetchall()
        conn.close()
        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = rows[start:end]
        return {
            "vehicles": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": end < total,
        }

    @tool(
        description="Get detailed information for a single vehicle by ID.",
        parameters={
            "type": "object",
            "properties": {
                "vehicle_id": {
                    "type": "integer",
                    "description": "The vehicle ID to look up"
                },
            },
            "required": ["vehicle_id"],
        },
    )
    def get_vehicle_details(self, vehicle_id):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM vehicles WHERE vehicle_id=?", (int(vehicle_id),))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Vehicle {vehicle_id} not found"}
        return dict(row)

    @tool(
        description="Query fuel card transactions with optional filters. Returns paginated results including transaction_id, vehicle_id, timestamp, latitude, longitude, liters, cost, and station_name.",
        parameters={
            "type": "object",
            "properties": {
                "vehicle_id": {
                    "type": "integer",
                    "description": "Filter by vehicle ID (optional)"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date filter YYYY-MM-DD (inclusive, optional)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date filter YYYY-MM-DD (inclusive, optional)"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1 (default 1)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 20, max 50)"
                },
            },
            "required": [],
        },
    )
    def query_fuel_transactions(self, vehicle_id=None, start_date=None,
                                 end_date=None, page=1, page_size=20):
        page = max(1, int(page))
        page_size = max(1, min(50, int(page_size)))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        clauses = []
        params = []
        if vehicle_id is not None:
            clauses.append("vehicle_id = ?")
            params.append(int(vehicle_id))
        if start_date:
            clauses.append("date(timestamp) >= ?")
            params.append(str(start_date))
        if end_date:
            clauses.append("date(timestamp) <= ?")
            params.append(str(end_date))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        c.execute(
            f"SELECT * FROM fuel_transactions{where} ORDER BY transaction_id",
            params,
        )
        rows = c.fetchall()
        conn.close()
        total = len(rows)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_rows = rows[start_idx:end_idx]
        return {
            "transactions": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": end_idx < total,
        }

    @tool(
        description="Query GPS tracking events with optional filters. Returns paginated results including event_id, vehicle_id, timestamp, latitude, longitude, speed_kmh, and ignition_on.",
        parameters={
            "type": "object",
            "properties": {
                "vehicle_id": {
                    "type": "integer",
                    "description": "Filter by vehicle ID (optional)"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date filter YYYY-MM-DD (inclusive, optional)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date filter YYYY-MM-DD (inclusive, optional)"
                },
                "min_speed": {
                    "type": "number",
                    "description": "Minimum speed in km/h (optional)"
                },
                "ignition_on": {
                    "type": "boolean",
                    "description": "Filter for ignition on (true) or off (false) (optional)"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1 (default 1)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 50, max 100)"
                },
            },
            "required": [],
        },
    )
    def query_gps_events(self, vehicle_id=None, start_date=None,
                          end_date=None, min_speed=None,
                          ignition_on=None, page=1, page_size=50):
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        clauses = []
        params = []
        if vehicle_id is not None:
            clauses.append("vehicle_id = ?")
            params.append(int(vehicle_id))
        if start_date:
            clauses.append("date(timestamp) >= ?")
            params.append(str(start_date))
        if end_date:
            clauses.append("date(timestamp) <= ?")
            params.append(str(end_date))
        if min_speed is not None:
            clauses.append("speed_kmh >= ?")
            params.append(float(min_speed))
        if ignition_on is not None:
            clauses.append("ignition_on = ?")
            params.append(1 if ignition_on else 0)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        c.execute(
            f"SELECT * FROM gps_events{where} ORDER BY event_id",
            params,
        )
        rows = c.fetchall()
        conn.close()
        total = len(rows)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_rows = rows[start_idx:end_idx]
        return {
            "events": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": end_idx < total,
        }

    @tool(
        description="Query driver shift schedules. Returns paginated results including shift_id, vehicle_id, driver_name, shift_date, start_hour, and end_hour.",
        parameters={
            "type": "object",
            "properties": {
                "vehicle_id": {
                    "type": "integer",
                    "description": "Filter by vehicle ID (optional)"
                },
                "date": {
                    "type": "string",
                    "description": "Filter by date YYYY-MM-DD (optional)"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1 (default 1)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 20, max 50)"
                },
            },
            "required": [],
        },
    )
    def query_driver_shifts(self, vehicle_id=None, date=None,
                             page=1, page_size=20):
        page = max(1, int(page))
        page_size = max(1, min(50, int(page_size)))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        clauses = []
        params = []
        if vehicle_id is not None:
            clauses.append("vehicle_id = ?")
            params.append(int(vehicle_id))
        if date:
            clauses.append("shift_date = ?")
            params.append(str(date))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        c.execute(
            f"SELECT * FROM driver_shifts{where} ORDER BY shift_id",
            params,
        )
        rows = c.fetchall()
        conn.close()
        total = len(rows)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_rows = rows[start_idx:end_idx]
        return {
            "shifts": [dict(r) for r in page_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": end_idx < total,
        }

    # ================================================================
    #  GROUND TRUTH COMPUTATION (used by step)
    # ================================================================

    def _compute_ground_truth(self):
        """Compute all anomalies from DB + workspace. Returns list of dicts."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # --- Read workspace config ---
        with open(os.path.join(self.workspace, "depot_geofences.json")) as f:
            depots = json.load(f)["depots"]
        with open(os.path.join(self.workspace, "anomaly_thresholds.json")) as f:
            thresholds = json.load(f)

        # Vehicle type specs
        type_specs = {}
        with open(os.path.join(self.workspace, "vehicle_type_specs.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                type_specs[row["vehicle_type"]] = {
                    "tank_capacity_liters": float(row["tank_capacity_liters"]),
                }

        # Maintenance schedules
        all_maintenance = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("maintenance_schedule_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        all_maintenance.append(row)

        # Overtime approvals
        overtime_set = set()  # (vehicle_id, date_str, hour)
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("fleet_daily_report_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    report = json.load(f)
                for daily in report.get("daily_records", []):
                    date_str = daily["date"]
                    for ot in daily.get("approved_overtime", []):
                        vid = ot["vehicle_id"]
                        for h in range(ot["start_hour"], ot["end_hour"]):
                            overtime_set.add((vid, date_str, h))

        # Prior incidents
        prior_incident_vehicles = set()
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("incident_history_") and fname.endswith(".md"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for line in f:
                        m = re.match(r"## Vehicle (\d+)", line)
                        if m:
                            prior_incident_vehicles.add(int(m.group(1)))

        # Fuel receipts
        receipt_amounts = {}  # transaction_id -> pump_amount
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("fuel_receipts_batch_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                for block in content.split("---"):
                    block = block.strip()
                    if not block:
                        continue
                    tid_match = re.search(r"FUEL RECEIPT #(\d+)", block)
                    pump_match = re.search(r"Pump Amount:\s*([\d.]+)\s*L", block)
                    if tid_match and pump_match:
                        receipt_amounts[int(tid_match.group(1))] = float(pump_match.group(1))

        # --- Load DB data ---
        c = conn.cursor()

        # Vehicles
        c.execute("SELECT * FROM vehicles")
        vehicles = {r["vehicle_id"]: dict(r) for r in c.fetchall()}

        # Fuel transactions
        c.execute("SELECT * FROM fuel_transactions ORDER BY transaction_id")
        fuel_txs = [dict(r) for r in c.fetchall()]

        # Shifts
        c.execute("SELECT * FROM driver_shifts")
        shift_lookup = {}
        for r in c.fetchall():
            shift_lookup[(r["vehicle_id"], r["shift_date"])] = (
                r["start_hour"], r["end_hour"]
            )

        # GPS events
        c.execute("SELECT * FROM gps_events ORDER BY event_id")
        gps_events = [dict(r) for r in c.fetchall()]

        conn.close()

        # --- Detect anomalies ---
        anomalies = []
        severity_upgrade = thresholds.get("prior_incident_severity_upgrade", False)

        def assign_severity(base_severity, vehicle_id):
            if severity_upgrade and vehicle_id in prior_incident_vehicles:
                return "HIGH"
            return base_severity

        # 1. Off-geofence fueling
        dist_thresh = thresholds["off_geofence_fueling"]["distance_threshold_km"]
        dist_high = thresholds["off_geofence_fueling"]["severity_high_distance_km"]
        for tx in fuel_txs:
            min_dist = min(
                _haversine_km(tx["latitude"], tx["longitude"],
                              d["latitude"], d["longitude"])
                for d in depots
            )
            if min_dist > dist_thresh:
                base_sev = "HIGH" if min_dist > dist_high else "MEDIUM"
                anomalies.append({
                    "vehicle_id": tx["vehicle_id"],
                    "plate_number": vehicles[tx["vehicle_id"]]["plate_number"],
                    "anomaly_type": "off_geofence_fueling",
                    "reference_id": tx["transaction_id"],
                    "timestamp": tx["timestamp"],
                    "severity": assign_severity(base_sev, tx["vehicle_id"]),
                    "details": f"Fuel transaction {min_dist:.1f}km from nearest depot",
                })

        # 2. Overcapacity fueling
        oc_pct = thresholds["overcapacity_fueling"]["threshold_pct"]
        oc_high_pct = thresholds["overcapacity_fueling"]["severity_high_pct"]
        for tx in fuel_txs:
            v = vehicles[tx["vehicle_id"]]
            vtype = v["vehicle_type"]
            if vtype not in type_specs:
                continue
            tank_cap = type_specs[vtype]["tank_capacity_liters"]
            pct = (tx["liters"] / tank_cap) * 100
            if pct > oc_pct:
                base_sev = "HIGH" if pct > oc_high_pct else "MEDIUM"
                anomalies.append({
                    "vehicle_id": tx["vehicle_id"],
                    "plate_number": v["plate_number"],
                    "anomaly_type": "overcapacity_fueling",
                    "reference_id": tx["transaction_id"],
                    "timestamp": tx["timestamp"],
                    "severity": assign_severity(base_sev, tx["vehicle_id"]),
                    "details": f"Fueled {tx['liters']}L, tank capacity {tank_cap}L ({pct:.0f}%)",
                })

        # 3. Maintenance movement
        speed_thresh = thresholds["maintenance_movement"]["speed_threshold_kmh"]
        speed_high = thresholds["maintenance_movement"]["severity_high_speed_kmh"]
        for maint in all_maintenance:
            m_vid = int(maint["vehicle_id"])
            m_start = maint["start_datetime"]
            m_end = maint["end_datetime"]
            for ev in gps_events:
                if ev["vehicle_id"] != m_vid:
                    continue
                if ev["speed_kmh"] < speed_thresh:
                    continue
                if m_start <= ev["timestamp"] <= m_end:
                    base_sev = "HIGH" if ev["speed_kmh"] > speed_high else "MEDIUM"
                    anomalies.append({
                        "vehicle_id": m_vid,
                        "plate_number": vehicles[m_vid]["plate_number"],
                        "anomaly_type": "maintenance_movement",
                        "reference_id": ev["event_id"],
                        "timestamp": ev["timestamp"],
                        "severity": assign_severity(base_sev, m_vid),
                        "details": f"Speed {ev['speed_kmh']}km/h during maintenance window {m_start} to {m_end}",
                    })

        # 4. After-hours ignition
        ah_high_start = thresholds["after_hours_ignition"]["severity_high_hour_start"]
        ah_high_end = thresholds["after_hours_ignition"]["severity_high_hour_end"]
        for ev in gps_events:
            if not ev["ignition_on"]:
                continue
            vid = ev["vehicle_id"]
            date_str = ev["timestamp"][:10]
            hour = int(ev["timestamp"][11:13])
            skey = (vid, date_str)
            if skey not in shift_lookup:
                continue
            sh, eh = shift_lookup[skey]
            if sh <= hour < eh:
                continue  # within shift
            if (vid, date_str, hour) in overtime_set:
                continue  # covered by overtime
            base_sev = "HIGH" if ah_high_start <= hour < ah_high_end else "MEDIUM"
            anomalies.append({
                "vehicle_id": vid,
                "plate_number": vehicles[vid]["plate_number"],
                "anomaly_type": "after_hours_ignition",
                "reference_id": ev["event_id"],
                "timestamp": ev["timestamp"],
                "severity": assign_severity(base_sev, vid),
                "details": f"Ignition on at hour {hour}, shift {sh}-{eh}",
            })

        # 5. Fuel receipt mismatch
        mismatch_thresh = thresholds["fuel_receipt_mismatch"]["threshold_liters"]
        mismatch_high = thresholds["fuel_receipt_mismatch"]["severity_high_liters"]
        tx_by_id = {tx["transaction_id"]: tx for tx in fuel_txs}
        for tid, pump_amt in receipt_amounts.items():
            if tid not in tx_by_id:
                continue
            tx = tx_by_id[tid]
            diff = abs(pump_amt - tx["liters"])
            if diff > mismatch_thresh:
                base_sev = "HIGH" if diff > mismatch_high else "MEDIUM"
                vid = tx["vehicle_id"]
                anomalies.append({
                    "vehicle_id": vid,
                    "plate_number": vehicles[vid]["plate_number"],
                    "anomaly_type": "fuel_receipt_mismatch",
                    "reference_id": tid,
                    "timestamp": tx["timestamp"],
                    "severity": assign_severity(base_sev, vid),
                    "details": f"Card: {tx['liters']}L, Pump: {pump_amt}L, diff: {diff:.1f}L",
                })

        # Sort: HIGH first, then timestamp ascending
        sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        anomalies.sort(key=lambda a: (sev_order.get(a["severity"], 9), a["timestamp"]))

        # Assign incident_id
        for i, a in enumerate(anomalies):
            a["incident_id"] = i + 1

        return anomalies

    # ================================================================
    #  STEP
    # ================================================================

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        ground_truth = self._compute_ground_truth()
        gt_by_type = defaultdict(list)
        for a in ground_truth:
            gt_by_type[a["anomaly_type"]].append(a)

        criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: Report file format (10 pts) ---
        max_c1 = 10
        max_score += max_c1
        report_path = os.path.join(self.workspace, "anomaly_report.csv")
        required_cols = ["incident_id", "vehicle_id", "plate_number",
                         "anomaly_type", "reference_id", "timestamp",
                         "severity", "details"]
        report_rows = []
        c1_score = 0
        c1_reason = ""
        if not os.path.exists(report_path):
            c1_reason = "anomaly_report.csv not found"
        else:
            try:
                with open(report_path, newline="") as f:
                    reader = csv.DictReader(f)
                    actual_cols = [c.strip() for c in (reader.fieldnames or [])]
                    missing = [c for c in required_cols if c not in actual_cols]
                    if missing:
                        c1_reason = f"Missing columns: {missing}"
                        c1_score = 3
                    else:
                        for row in reader:
                            report_rows.append(
                                {k.strip(): v.strip() for k, v in row.items()})
                        # Check sorting
                        sorted_ok = True
                        for i in range(1, len(report_rows)):
                            prev_sev = report_rows[i - 1].get("severity", "")
                            cur_sev = report_rows[i].get("severity", "")
                            sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
                            if sev_order.get(cur_sev, 9) < sev_order.get(prev_sev, 9):
                                sorted_ok = False
                                break
                            if (cur_sev == prev_sev and
                                    report_rows[i].get("timestamp", "") <
                                    report_rows[i - 1].get("timestamp", "")):
                                sorted_ok = False
                                break
                        if sorted_ok and len(report_rows) > 0:
                            c1_score = max_c1
                        elif len(report_rows) > 0:
                            c1_score = 6
                            c1_reason = "Sorting incorrect"
                        else:
                            c1_score = 3
                            c1_reason = "File empty"
            except Exception as e:
                c1_reason = f"Error reading report: {e}"
        total_score += c1_score
        criteria["report_format"] = {
            "passed": c1_score == max_c1,
            "score": c1_score,
            "max_score": max_c1,
            "reason": c1_reason if c1_score < max_c1 else "",
        }

        # --- Helper: compute F1 for an anomaly type ---
        def score_anomaly_type(atype, max_pts):
            nonlocal total_score, max_score
            max_score += max_pts
            gt_set = set()
            for a in gt_by_type.get(atype, []):
                gt_set.add((a["vehicle_id"], a["reference_id"]))

            detected_set = set()
            for row in report_rows:
                if row.get("anomaly_type", "") == atype:
                    try:
                        vid = int(row["vehicle_id"])
                        rid = int(row["reference_id"])
                        detected_set.add((vid, rid))
                    except (ValueError, KeyError):
                        pass

            if not gt_set and not detected_set:
                sc = max_pts
            elif not gt_set:
                sc = 0
            elif not detected_set:
                sc = 0
            else:
                tp = len(gt_set & detected_set)
                precision = tp / len(detected_set) if detected_set else 0
                recall = tp / len(gt_set) if gt_set else 0
                f1 = (2 * precision * recall / (precision + recall)
                      if (precision + recall) > 0 else 0)
                sc = round(f1 * max_pts)

            total_score += sc
            passed = sc == max_pts
            reason = ""
            if not passed:
                reason = (f"GT={len(gt_set)}, detected={len(detected_set)}, "
                          f"overlap={len(gt_set & detected_set)}")
            criteria[atype] = {
                "passed": passed,
                "score": sc,
                "max_score": max_pts,
                "reason": reason,
            }

        # --- Criteria 2-6: anomaly type detection ---
        score_anomaly_type("off_geofence_fueling", 20)
        score_anomaly_type("overcapacity_fueling", 15)
        score_anomaly_type("maintenance_movement", 20)
        score_anomaly_type("after_hours_ignition", 15)
        score_anomaly_type("fuel_receipt_mismatch", 10)

        # --- Criterion 7: Severity accuracy (10 pts) ---
        max_c7 = 10
        max_score += max_c7
        gt_severity = {}
        for a in ground_truth:
            gt_severity[(a["vehicle_id"], a["reference_id"], a["anomaly_type"])] = a["severity"]

        correct_sev = 0
        total_matched = 0
        for row in report_rows:
            try:
                vid = int(row["vehicle_id"])
                rid = int(row["reference_id"])
                atype = row.get("anomaly_type", "")
                sev = row.get("severity", "")
                key = (vid, rid, atype)
                if key in gt_severity:
                    total_matched += 1
                    if gt_severity[key] == sev:
                        correct_sev += 1
            except (ValueError, KeyError):
                pass
        if total_matched > 0:
            c7_score = round((correct_sev / total_matched) * max_c7)
        else:
            c7_score = 0
        total_score += c7_score
        criteria["severity_accuracy"] = {
            "passed": c7_score == max_c7,
            "score": c7_score,
            "max_score": max_c7,
            "reason": (f"{correct_sev}/{total_matched} correct"
                       if c7_score < max_c7 else ""),
        }

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ================================================================
    #  VERIFY
    # ================================================================

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as _csv

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # --- 1. Read workspace config files ---
        with open(os.path.join(self.workspace, "depot_geofences.json")) as f:
            depots = json.load(f)["depots"]
        with open(os.path.join(self.workspace, "anomaly_thresholds.json")) as f:
            thresholds = json.load(f)

        type_specs = {}
        with open(os.path.join(self.workspace, "vehicle_type_specs.csv")) as f:
            reader = _csv.DictReader(f)
            for row in reader:
                type_specs[row["vehicle_type"]] = {
                    "tank_capacity_liters": float(row["tank_capacity_liters"]),
                }

        # Read maintenance schedules
        all_maintenance = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("maintenance_schedule_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = _csv.DictReader(f)
                    for row in reader:
                        all_maintenance.append(row)

        # Read overtime approvals
        overtime_set = set()
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("fleet_daily_report_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    report = json.load(f)
                for daily in report.get("daily_records", []):
                    date_str = daily["date"]
                    for ot in daily.get("approved_overtime", []):
                        vid = ot["vehicle_id"]
                        for h in range(ot["start_hour"], ot["end_hour"]):
                            overtime_set.add((vid, date_str, h))

        # Read prior incidents
        prior_incident_vehicles = set()
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("incident_history_") and fname.endswith(".md"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for line in f:
                        m = re.match(r"## Vehicle (\d+)", line)
                        if m:
                            prior_incident_vehicles.add(int(m.group(1)))

        # Read fuel receipts
        receipt_amounts = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("fuel_receipts_batch_") and fname.endswith(".txt"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                for block in content.split("---"):
                    block = block.strip()
                    if not block:
                        continue
                    tid_match = re.search(r"FUEL RECEIPT #(\d+)", block)
                    pump_match = re.search(r"Pump Amount:\s*([\d.]+)\s*L", block)
                    if tid_match and pump_match:
                        receipt_amounts[int(tid_match.group(1))] = float(
                            pump_match.group(1))

        # --- 2. Fetch all vehicles via tool ---
        vehicle_lookup = {}
        page = 1
        while True:
            res = call_tool("list_vehicles", page=page, page_size=20)
            for v in res["vehicles"]:
                vehicle_lookup[v["vehicle_id"]] = v
            if not res["has_more"]:
                break
            page += 1

        # --- 3. Fetch all fuel transactions via tool ---
        all_fuel_txs = []
        page = 1
        while True:
            res = call_tool("query_fuel_transactions", page=page, page_size=20)
            all_fuel_txs.extend(res["transactions"])
            if not res["has_more"]:
                break
            page += 1

        # --- 4. Fetch all driver shifts via tool ---
        all_shifts = []
        page = 1
        while True:
            res = call_tool("query_driver_shifts", page=page, page_size=20)
            all_shifts.extend(res["shifts"])
            if not res["has_more"]:
                break
            page += 1
        shift_lookup = {
            (s["vehicle_id"], s["shift_date"]): (s["start_hour"], s["end_hour"])
            for s in all_shifts
        }

        # --- 5. Fetch all GPS events via tool ---
        all_gps = []
        page = 1
        while True:
            res = call_tool("query_gps_events", page=page, page_size=50)
            all_gps.extend(res["events"])
            if not res["has_more"]:
                break
            page += 1

        # --- 6. Detect anomalies ---
        anomalies = []
        severity_upgrade = thresholds.get("prior_incident_severity_upgrade", False)

        def assign_severity(base_sev, vid):
            if severity_upgrade and vid in prior_incident_vehicles:
                return "HIGH"
            return base_sev

        # 6a. Off-geofence fueling
        dist_thresh = thresholds["off_geofence_fueling"]["distance_threshold_km"]
        dist_high = thresholds["off_geofence_fueling"]["severity_high_distance_km"]
        for tx in all_fuel_txs:
            min_dist = min(
                _haversine_km(tx["latitude"], tx["longitude"],
                              d["latitude"], d["longitude"])
                for d in depots
            )
            if min_dist > dist_thresh:
                base_sev = "HIGH" if min_dist > dist_high else "MEDIUM"
                vid = tx["vehicle_id"]
                anomalies.append({
                    "vehicle_id": vid,
                    "plate_number": vehicle_lookup[vid]["plate_number"],
                    "anomaly_type": "off_geofence_fueling",
                    "reference_id": tx["transaction_id"],
                    "timestamp": tx["timestamp"],
                    "severity": assign_severity(base_sev, vid),
                    "details": f"Fuel transaction {min_dist:.1f}km from nearest depot",
                })

        # 6b. Overcapacity fueling
        oc_pct = thresholds["overcapacity_fueling"]["threshold_pct"]
        oc_high_pct = thresholds["overcapacity_fueling"]["severity_high_pct"]
        for tx in all_fuel_txs:
            vid = tx["vehicle_id"]
            vtype = vehicle_lookup[vid]["vehicle_type"]
            if vtype not in type_specs:
                continue
            tank_cap = type_specs[vtype]["tank_capacity_liters"]
            pct = (tx["liters"] / tank_cap) * 100
            if pct > oc_pct:
                base_sev = "HIGH" if pct > oc_high_pct else "MEDIUM"
                anomalies.append({
                    "vehicle_id": vid,
                    "plate_number": vehicle_lookup[vid]["plate_number"],
                    "anomaly_type": "overcapacity_fueling",
                    "reference_id": tx["transaction_id"],
                    "timestamp": tx["timestamp"],
                    "severity": assign_severity(base_sev, vid),
                    "details": f"Fueled {tx['liters']}L, tank capacity {tank_cap}L ({pct:.0f}%)",
                })

        # 6c. Maintenance movement
        speed_thresh = thresholds["maintenance_movement"]["speed_threshold_kmh"]
        speed_high = thresholds["maintenance_movement"]["severity_high_speed_kmh"]
        for maint in all_maintenance:
            m_vid = int(maint["vehicle_id"])
            m_start = maint["start_datetime"]
            m_end = maint["end_datetime"]
            for ev in all_gps:
                if ev["vehicle_id"] != m_vid:
                    continue
                if ev["speed_kmh"] < speed_thresh:
                    continue
                if m_start <= ev["timestamp"] <= m_end:
                    base_sev = "HIGH" if ev["speed_kmh"] > speed_high else "MEDIUM"
                    anomalies.append({
                        "vehicle_id": m_vid,
                        "plate_number": vehicle_lookup[m_vid]["plate_number"],
                        "anomaly_type": "maintenance_movement",
                        "reference_id": ev["event_id"],
                        "timestamp": ev["timestamp"],
                        "severity": assign_severity(base_sev, m_vid),
                        "details": f"Speed {ev['speed_kmh']}km/h during maintenance",
                    })

        # 6d. After-hours ignition
        ah_high_start = thresholds["after_hours_ignition"]["severity_high_hour_start"]
        ah_high_end = thresholds["after_hours_ignition"]["severity_high_hour_end"]
        for ev in all_gps:
            if not ev["ignition_on"]:
                continue
            vid = ev["vehicle_id"]
            date_str = ev["timestamp"][:10]
            hour = int(ev["timestamp"][11:13])
            skey = (vid, date_str)
            if skey not in shift_lookup:
                continue
            sh, eh = shift_lookup[skey]
            if sh <= hour < eh:
                continue
            if (vid, date_str, hour) in overtime_set:
                continue
            base_sev = "HIGH" if ah_high_start <= hour < ah_high_end else "MEDIUM"
            anomalies.append({
                "vehicle_id": vid,
                "plate_number": vehicle_lookup[vid]["plate_number"],
                "anomaly_type": "after_hours_ignition",
                "reference_id": ev["event_id"],
                "timestamp": ev["timestamp"],
                "severity": assign_severity(base_sev, vid),
                "details": f"Ignition on at hour {hour}, shift {sh}-{eh}",
            })

        # 6e. Fuel receipt mismatch
        mismatch_thresh = thresholds["fuel_receipt_mismatch"]["threshold_liters"]
        mismatch_high = thresholds["fuel_receipt_mismatch"]["severity_high_liters"]
        tx_by_id = {tx["transaction_id"]: tx for tx in all_fuel_txs}
        for tid, pump_amt in receipt_amounts.items():
            if tid not in tx_by_id:
                continue
            tx = tx_by_id[tid]
            diff = abs(pump_amt - tx["liters"])
            if diff > mismatch_thresh:
                vid = tx["vehicle_id"]
                base_sev = "HIGH" if diff > mismatch_high else "MEDIUM"
                anomalies.append({
                    "vehicle_id": vid,
                    "plate_number": vehicle_lookup[vid]["plate_number"],
                    "anomaly_type": "fuel_receipt_mismatch",
                    "reference_id": tid,
                    "timestamp": tx["timestamp"],
                    "severity": assign_severity(base_sev, vid),
                    "details": f"Card: {tx['liters']}L, Pump: {pump_amt}L, diff: {diff:.1f}L",
                })

        # --- 7. Sort and assign incident_id ---
        sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        anomalies.sort(key=lambda a: (sev_order.get(a["severity"], 9),
                                       a["timestamp"]))
        for i, a in enumerate(anomalies):
            a["incident_id"] = i + 1

        # --- 8. Write anomaly_report.csv ---
        report_path = os.path.join(self.workspace, "anomaly_report.csv")
        fieldnames = ["incident_id", "vehicle_id", "plate_number",
                      "anomaly_type", "reference_id", "timestamp",
                      "severity", "details"]
        with open(report_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for a in anomalies:
                writer.writerow({k: a[k] for k in fieldnames})

        # --- 9. Build summary ---
        type_counts = defaultdict(int)
        sev_counts = defaultdict(int)
        vehicle_counts = defaultdict(int)
        for a in anomalies:
            type_counts[a["anomaly_type"]] += 1
            sev_counts[a["severity"]] += 1
            vehicle_counts[a["vehicle_id"]] += 1

        repeat_offenders = sorted(
            [(vid, cnt) for vid, cnt in vehicle_counts.items() if cnt > 1],
            key=lambda x: -x[1]
        )

        summary_lines = [
            f"Total anomalies found: {len(anomalies)}",
            "",
            "Breakdown by type:",
        ]
        for atype in ["off_geofence_fueling", "overcapacity_fueling",
                       "maintenance_movement", "after_hours_ignition",
                       "fuel_receipt_mismatch"]:
            summary_lines.append(f"  {atype}: {type_counts.get(atype, 0)}")
        summary_lines.append("")
        summary_lines.append("Breakdown by severity:")
        for sev in ["HIGH", "MEDIUM"]:
            summary_lines.append(f"  {sev}: {sev_counts.get(sev, 0)}")
        if repeat_offenders:
            summary_lines.append("")
            summary_lines.append("Vehicles with multiple anomalies:")
            for vid, cnt in repeat_offenders[:10]:
                plate = vehicle_lookup[vid]["plate_number"]
                summary_lines.append(f"  Vehicle {vid} ({plate}): {cnt} anomalies")

        action = "\n".join(summary_lines)

        print(f"verify: {tool_call_count} tool calls made")
        return self.step(action)
