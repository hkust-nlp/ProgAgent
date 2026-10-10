"""
Task environment for Controlled Substance Chain-of-Custody Reconciliation.
"""

import csv
import glob
import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Tuple

import yaml


# --- Decorator for tool registration ---
def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# Checkpoint definitions (must match data.py)
CHECKPOINT_MAP = {
    "SHORT":    ["ORIGIN", "DESTINATION"],
    "STANDARD": ["ORIGIN", "TRANSIT_A", "DESTINATION"],
    "EXTENDED": ["ORIGIN", "TRANSIT_A", "TRANSIT_B", "DESTINATION"],
}


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

    # ── Tool Methods ─────────────────────────────────────────────────────────

    @tool(
        description="Retrieve the DEA Form 222 record associated with a given shipment. Returns the form details including authorized quantity, schedule listed on the form, supplier and purchaser DEA numbers, issue date, and expiry date.",
        parameters={
            "type": "object",
            "properties": {
                "shipment_id": {
                    "type": "string",
                    "description": "The shipment identifier, e.g. 'SHP-00001'",
                },
            },
            "required": ["shipment_id"],
        },
    )
    def get_dea_form(self, shipment_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM dea_forms WHERE shipment_id = ?", (shipment_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return _envelope({"error": f"No DEA Form 222 found for shipment {shipment_id}"})
        return _envelope(dict(row))

    @tool(
        description="Verify a facility's license status, expiry date, and authorized DEA schedules. Returns license details for the given facility.",
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "The facility identifier, e.g. 'FAC-0001'",
                },
            },
            "required": ["facility_id"],
        },
    )
    def verify_facility_license(self, facility_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT facility_id, facility_name, license_number, "
            "license_expiry_date, license_status, schedules_authorized, dea_number "
            "FROM facilities WHERE facility_id = ?",
            (facility_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return _envelope({"error": f"No facility found with ID {facility_id}"})
        return _envelope(dict(row))

    @tool(
        description="Retrieve GPS tracking log entries for a specific shipment. Returns a list of GPS pings with timestamps, coordinates, zone name, and geofence status.",
        parameters={
            "type": "object",
            "properties": {
                "shipment_id": {
                    "type": "string",
                    "description": "The shipment identifier, e.g. 'SHP-00001'",
                },
            },
            "required": ["shipment_id"],
        },
    )
    def get_gps_log(self, shipment_id: str) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM gps_logs WHERE shipment_id = ? ORDER BY timestamp",
            (shipment_id,),
        ).fetchall()
        conn.close()
        if not rows:
            return json.dumps({"error": f"No GPS logs found for shipment {shipment_id}"}, ensure_ascii=False, default=str)
        return json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str)

    @tool(
        description="Retrieve carrier certification and compliance details. Returns hazmat endorsement status, controlled substance certification, DEA registration, certification expiry, and DOT number.",
        parameters={
            "type": "object",
            "properties": {
                "carrier_id": {
                    "type": "string",
                    "description": "The carrier identifier, e.g. 'CAR-0001'",
                },
            },
            "required": ["carrier_id"],
        },
    )
    def get_carrier_info(self, carrier_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM carriers WHERE carrier_id = ?", (carrier_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"No carrier found with ID {carrier_id}"}, ensure_ascii=False, default=str)
        result = dict(row)
        result["hazmat_certified"] = bool(result["hazmat_certified"])
        result["controlled_substance_certified"] = bool(
            result["controlled_substance_certified"]
        )
        result["dea_registered"] = bool(result["dea_registered"])
        return json.dumps(result, ensure_ascii=False, default=str)

    # ── Ground-truth computation (used by step and verify) ───────────────────

    def _compute_ground_truth(self):
        """Compute all discrepancies from DB + workspace config. Returns list of dicts."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        shipments = [dict(r) for r in conn.execute("SELECT * FROM shipments").fetchall()]
        dea_forms = {
            r["shipment_id"]: dict(r)
            for r in conn.execute("SELECT * FROM dea_forms").fetchall()
        }
        facilities = {
            r["facility_id"]: dict(r)
            for r in conn.execute("SELECT * FROM facilities").fetchall()
        }
        carriers_db = {
            r["carrier_id"]: dict(r)
            for r in conn.execute("SELECT * FROM carriers").fetchall()
        }
        gps_rows = conn.execute("SELECT * FROM gps_logs ORDER BY shipment_id, timestamp").fetchall()
        conn.close()

        gps_by_ship = {}
        for r in gps_rows:
            gps_by_ship.setdefault(r["shipment_id"], []).append(dict(r))

        # Load regulatory config
        cfg_path = os.path.join(self.workspace, "regulatory_config.yaml")
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        disc_cfg = cfg["discrepancy_types"]
        actions = cfg["recommended_actions"]
        carrier_rules = cfg["carrier_rules"]

        discrepancies = []

        for s in shipments:
            sid = s["shipment_id"]
            dep_date = s["departure_date"]  # YYYY-MM-DD
            schedule = s["dea_schedule"]

            # --- QUANTITY_MISMATCH ---
            dea = dea_forms.get(sid)
            if dea and dea["authorized_quantity"] != s["quantity_shipped"]:
                sev = disc_cfg["QUANTITY_MISMATCH"]["severity"]
                discrepancies.append({
                    "shipment_id": sid,
                    "manifest_number": s["manifest_number"],
                    "substance_name": s["substance_name"],
                    "dea_schedule": schedule,
                    "discrepancy_type": "QUANTITY_MISMATCH",
                    "severity": sev,
                    "recommended_action": actions[sev],
                    "detail": (f"Shipped {s['quantity_shipped']} {s['unit']}, "
                               f"DEA authorized {dea['authorized_quantity']} {s['unit']}"),
                })

            # --- SCHEDULE_MISMATCH ---
            if dea and dea["substance_schedule_on_form"] != schedule:
                sev = disc_cfg["SCHEDULE_MISMATCH"]["severity"]
                discrepancies.append({
                    "shipment_id": sid,
                    "manifest_number": s["manifest_number"],
                    "substance_name": s["substance_name"],
                    "dea_schedule": schedule,
                    "discrepancy_type": "SCHEDULE_MISMATCH",
                    "severity": sev,
                    "recommended_action": actions[sev],
                    "detail": (f"Manifest schedule {schedule}, "
                               f"DEA Form lists schedule {dea['substance_schedule_on_form']}"),
                })

            # --- DEA_FORM_EXPIRED ---
            if dea and dea["expiry_date"] < dep_date:
                sev = disc_cfg["DEA_FORM_EXPIRED"]["severity"]
                discrepancies.append({
                    "shipment_id": sid,
                    "manifest_number": s["manifest_number"],
                    "substance_name": s["substance_name"],
                    "dea_schedule": schedule,
                    "discrepancy_type": "DEA_FORM_EXPIRED",
                    "severity": sev,
                    "recommended_action": actions[sev],
                    "detail": (f"Form expired {dea['expiry_date']}, "
                               f"departure {dep_date}"),
                })

            # --- EXPIRED_FACILITY_LICENSE (origin + dest) ---
            for role, fid in [("origin", s["origin_facility_id"]),
                              ("destination", s["destination_facility_id"])]:
                fac = facilities.get(fid)
                if not fac:
                    continue
                if fac["license_status"] != "active" or fac["license_expiry_date"] < dep_date:
                    sev = disc_cfg["EXPIRED_FACILITY_LICENSE"]["severity"]
                    discrepancies.append({
                        "shipment_id": sid,
                        "manifest_number": s["manifest_number"],
                        "substance_name": s["substance_name"],
                        "dea_schedule": schedule,
                        "discrepancy_type": "EXPIRED_FACILITY_LICENSE",
                        "severity": sev,
                        "recommended_action": actions[sev],
                        "detail": (f"{role.capitalize()} facility {fid} "
                                   f"({fac['facility_name']}): license {fac['license_status']}, "
                                   f"expires {fac['license_expiry_date']}"),
                    })

            # --- UNAUTHORIZED_SCHEDULE (origin + dest) ---
            for role, fid in [("origin", s["origin_facility_id"]),
                              ("destination", s["destination_facility_id"])]:
                fac = facilities.get(fid)
                if not fac:
                    continue
                auth_schedules = [x.strip() for x in fac["schedules_authorized"].split(",")]
                if schedule not in auth_schedules:
                    sev = disc_cfg["UNAUTHORIZED_SCHEDULE"]["severity"]
                    discrepancies.append({
                        "shipment_id": sid,
                        "manifest_number": s["manifest_number"],
                        "substance_name": s["substance_name"],
                        "dea_schedule": schedule,
                        "discrepancy_type": "UNAUTHORIZED_SCHEDULE",
                        "severity": sev,
                        "recommended_action": actions[sev],
                        "detail": (f"{role.capitalize()} facility {fid} authorized for "
                                   f"[{fac['schedules_authorized']}], "
                                   f"shipment is Schedule {schedule}"),
                    })

            # --- CUSTODY_GAP ---
            ship_gps = gps_by_ship.get(sid, [])
            zones_seen = set(g["zone_name"] for g in ship_gps)
            required = CHECKPOINT_MAP.get(s["route_type"], [])
            missing = [cp for cp in required if cp not in zones_seen]
            if missing:
                sev = disc_cfg["CUSTODY_GAP"]["severity"]
                discrepancies.append({
                    "shipment_id": sid,
                    "manifest_number": s["manifest_number"],
                    "substance_name": s["substance_name"],
                    "dea_schedule": schedule,
                    "discrepancy_type": "CUSTODY_GAP",
                    "severity": sev,
                    "recommended_action": actions[sev],
                    "detail": f"Missing checkpoint(s): {', '.join(missing)}",
                })

            # --- GEOFENCE_VIOLATION ---
            outside_count = sum(1 for g in ship_gps if g["geofence_status"] == "outside")
            if outside_count > 0:
                sev = disc_cfg["GEOFENCE_VIOLATION"]["severity"]
                discrepancies.append({
                    "shipment_id": sid,
                    "manifest_number": s["manifest_number"],
                    "substance_name": s["substance_name"],
                    "dea_schedule": schedule,
                    "discrepancy_type": "GEOFENCE_VIOLATION",
                    "severity": sev,
                    "recommended_action": actions[sev],
                    "detail": f"{outside_count} GPS ping(s) outside authorized zone",
                })

            # --- CARRIER_NONCOMPLIANT ---
            car = carriers_db.get(s["carrier_id"])
            if car:
                issues = []
                if car["certification_expiry"] < dep_date:
                    issues.append("certification expired")
                hazmat_scheds = carrier_rules["hazmat_required_schedules"]
                if schedule in hazmat_scheds and not car["hazmat_certified"]:
                    issues.append("no hazmat endorsement for Schedule " + schedule)
                if carrier_rules["dea_registration_required"] and not car["dea_registered"]:
                    issues.append("not DEA-registered")
                if carrier_rules["controlled_substance_cert_required"] and not car["controlled_substance_certified"]:
                    issues.append("no controlled-substance certification")
                if issues:
                    sev = disc_cfg["CARRIER_NONCOMPLIANT"]["severity"]
                    discrepancies.append({
                        "shipment_id": sid,
                        "manifest_number": s["manifest_number"],
                        "substance_name": s["substance_name"],
                        "dea_schedule": schedule,
                        "discrepancy_type": "CARRIER_NONCOMPLIANT",
                        "severity": sev,
                        "recommended_action": actions[sev],
                        "detail": f"Carrier {s['carrier_id']}: {'; '.join(issues)}",
                    })

        # Deduplicate: same (shipment_id, discrepancy_type) keep first
        seen = set()
        unique = []
        for d in discrepancies:
            key = (d["shipment_id"], d["discrepancy_type"])
            if key not in seen:
                seen.add(key)
                unique.append(d)

        # Sort: severity order (critical > high > medium), then shipment_id, then type
        sev_order = {"critical": 0, "high": 1, "medium": 2}
        unique.sort(key=lambda x: (sev_order.get(x["severity"], 9), x["shipment_id"], x["discrepancy_type"]))
        return unique, len(shipments)

    # ── Evaluation ───────────────────────────────────────────────────────────

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
        ground_truth, total_shipments = self._compute_ground_truth()
        gt_keys = {(d["shipment_id"], d["discrepancy_type"]) for d in ground_truth}
        gt_map = {(d["shipment_id"], d["discrepancy_type"]): d for d in ground_truth}

        criteria = {}

        # ── C1: audit_roster.csv exists with correct columns (10 pts) ───────
        roster_path = os.path.join(self.workspace, "audit_roster.csv")
        expected_cols = ["shipment_id", "manifest_number", "substance_name",
                         "dea_schedule", "discrepancy_type", "severity",
                         "recommended_action", "detail"]
        c1_score = 0
        agent_rows = []
        if os.path.isfile(roster_path):
            with open(roster_path, newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and set(expected_cols).issubset(set(reader.fieldnames)):
                    c1_score = 10
                    for row in reader:
                        agent_rows.append(row)
                else:
                    c1_score = 3  # file exists but wrong columns
        criteria["file_and_columns"] = {
            "passed": c1_score == 10,
            "score": c1_score,
            "max_score": 10,
            "reason": "" if c1_score == 10 else "audit_roster.csv missing or wrong columns",
        }

        # ── C2: Flagged records accuracy — F1 (30 pts) ──────────────────────
        agent_keys = set()
        for r in agent_rows:
            agent_keys.add((r.get("shipment_id", ""), r.get("discrepancy_type", "")))

        tp = len(gt_keys & agent_keys)
        fp = len(agent_keys - gt_keys)
        fn = len(gt_keys - agent_keys)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        c2_score = round(f1 * 30, 2)
        criteria["flagged_records_f1"] = {
            "passed": c2_score >= 27,
            "score": c2_score,
            "max_score": 30,
            "reason": f"P={precision:.2f} R={recall:.2f} F1={f1:.2f} TP={tp} FP={fp} FN={fn}",
        }

        # ── C3: Severity accuracy (20 pts) ──────────────────────────────────
        correct_sev = 0
        matched = 0
        for r in agent_rows:
            key = (r.get("shipment_id", ""), r.get("discrepancy_type", ""))
            if key in gt_map:
                matched += 1
                if r.get("severity", "").strip().lower() == gt_map[key]["severity"]:
                    correct_sev += 1
        sev_ratio = correct_sev / matched if matched > 0 else 0
        c3_score = round(sev_ratio * 20, 2)
        criteria["severity_accuracy"] = {
            "passed": c3_score >= 18,
            "score": c3_score,
            "max_score": 20,
            "reason": f"{correct_sev}/{matched} correct severity",
        }

        # ── C4: Recommended action accuracy (15 pts) ────────────────────────
        correct_act = 0
        for r in agent_rows:
            key = (r.get("shipment_id", ""), r.get("discrepancy_type", ""))
            if key in gt_map:
                if r.get("recommended_action", "").strip() == gt_map[key]["recommended_action"]:
                    correct_act += 1
        act_ratio = correct_act / matched if matched > 0 else 0
        c4_score = round(act_ratio * 15, 2)
        criteria["action_accuracy"] = {
            "passed": c4_score >= 13,
            "score": c4_score,
            "max_score": 15,
            "reason": f"{correct_act}/{matched} correct action",
        }

        # ── C5: Sort order (10 pts) ─────────────────────────────────────────
        sev_order = {"critical": 0, "high": 1, "medium": 2}
        c5_score = 0
        if len(agent_rows) > 1:
            sorted_ok = True
            for idx in range(len(agent_rows) - 1):
                a = agent_rows[idx]
                b = agent_rows[idx + 1]
                ka = (sev_order.get(a.get("severity", "").strip().lower(), 9),
                      a.get("shipment_id", ""), a.get("discrepancy_type", ""))
                kb = (sev_order.get(b.get("severity", "").strip().lower(), 9),
                      b.get("shipment_id", ""), b.get("discrepancy_type", ""))
                if ka > kb:
                    sorted_ok = False
                    break
            c5_score = 10 if sorted_ok else 0
        elif len(agent_rows) == 1:
            c5_score = 10
        criteria["sort_order"] = {
            "passed": c5_score == 10,
            "score": c5_score,
            "max_score": 10,
            "reason": "" if c5_score == 10 else "Rows not sorted by severity > shipment_id > discrepancy_type",
        }

        # ── C6: Response summary (15 pts) ───────────────────────────────────
        action_lower = action.lower() if action else ""
        gt_unique_flagged = len({d["shipment_id"] for d in ground_truth})
        summary_checks = 0
        # Check total shipments reviewed
        if str(total_shipments) in action:
            summary_checks += 1
        # Check unique flagged count
        if str(gt_unique_flagged) in action:
            summary_checks += 1
        # Check that at least 3 discrepancy type names appear
        type_names = ["QUANTITY_MISMATCH", "EXPIRED_FACILITY_LICENSE", "SCHEDULE_MISMATCH",
                      "UNAUTHORIZED_SCHEDULE", "CUSTODY_GAP", "GEOFENCE_VIOLATION",
                      "CARRIER_NONCOMPLIANT", "DEA_FORM_EXPIRED"]
        types_mentioned = sum(1 for t in type_names if t.lower() in action_lower or t in action)
        if types_mentioned >= 3:
            summary_checks += 1
        c6_score = round(summary_checks / 3 * 15, 2)
        criteria["response_summary"] = {
            "passed": c6_score >= 13,
            "score": c6_score,
            "max_score": 15,
            "reason": f"Checks passed: {summary_checks}/3 (total, flagged, types)",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0

        return reward, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ── Verification ─────────────────────────────────────────────────────────

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
        import pandas as pd

        # 1. Read all manifest CSVs from workspace
        manifest_files = sorted(glob.glob(os.path.join(self.workspace, "manifest_batch_*.csv")))
        all_shipments = []
        for mf in manifest_files:
            with open(mf, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    all_shipments.append(row)

        # 2. Read route plans from workspace
        route_files = sorted(glob.glob(os.path.join(self.workspace, "route_plan_*.json")))
        route_map = {}
        for rf in route_files:
            with open(rf) as f:
                for entry in json.load(f):
                    route_map[entry["shipment_id"]] = entry

        # 3. Read regulatory config
        with open(os.path.join(self.workspace, "regulatory_config.yaml")) as f:
            cfg = yaml.safe_load(f)
        disc_cfg = cfg["discrepancy_types"]
        actions = cfg["recommended_actions"]
        carrier_rules = cfg["carrier_rules"]

        # 4. Read DEA schedule rules
        with open(os.path.join(self.workspace, "dea_schedule_rules.yaml")) as f:
            dea_rules = yaml.safe_load(f)

        # 5. Process each shipment — call tools, detect discrepancies
        facility_cache = {}
        carrier_cache = {}
        discrepancies = []
        tool_call_count = 0

        for s in all_shipments:
            sid = s["shipment_id"]
            dep_date = s["departure_date"]
            schedule = s["dea_schedule"]
            qty_shipped = int(s["quantity_shipped"])

            # --- Get DEA form ---
            dea = json.loads(self.tools["get_dea_form"](shipment_id=sid)["content"][0]["text"])
            tool_call_count += 1

            # --- Verify origin facility ---
            orig_fid = s["origin_facility_id"]
            if orig_fid not in facility_cache:
                facility_cache[orig_fid] = json.loads(self.tools["verify_facility_license"](facility_id=orig_fid)["content"][0]["text"])
                tool_call_count += 1
            orig_lic = facility_cache[orig_fid]

            # --- Verify destination facility ---
            dest_fid = s["destination_facility_id"]
            if dest_fid not in facility_cache:
                facility_cache[dest_fid] = json.loads(self.tools["verify_facility_license"](facility_id=dest_fid)["content"][0]["text"])
                tool_call_count += 1
            dest_lic = facility_cache[dest_fid]

            # --- Get GPS log ---
            gps = json.loads(self.tools["get_gps_log"](shipment_id=sid))
            tool_call_count += 1
            if isinstance(gps, dict) and "error" in gps:
                gps = []

            # --- Get carrier info ---
            cid = s["carrier_id"]
            if cid not in carrier_cache:
                carrier_cache[cid] = json.loads(self.tools["get_carrier_info"](carrier_id=cid))
                tool_call_count += 1
            carrier = carrier_cache[cid]

            base_info = {
                "shipment_id": sid,
                "manifest_number": s["manifest_number"],
                "substance_name": s["substance_name"],
                "dea_schedule": schedule,
            }

            # === Check QUANTITY_MISMATCH ===
            if "error" not in dea and dea["authorized_quantity"] != qty_shipped:
                sev = disc_cfg["QUANTITY_MISMATCH"]["severity"]
                discrepancies.append({
                    **base_info,
                    "discrepancy_type": "QUANTITY_MISMATCH",
                    "severity": sev,
                    "recommended_action": actions[sev],
                    "detail": (f"Shipped {qty_shipped} {s['unit']}, "
                               f"DEA authorized {dea['authorized_quantity']} {s['unit']}"),
                })

            # === Check SCHEDULE_MISMATCH ===
            if "error" not in dea and dea["substance_schedule_on_form"] != schedule:
                sev = disc_cfg["SCHEDULE_MISMATCH"]["severity"]
                discrepancies.append({
                    **base_info,
                    "discrepancy_type": "SCHEDULE_MISMATCH",
                    "severity": sev,
                    "recommended_action": actions[sev],
                    "detail": (f"Manifest schedule {schedule}, "
                               f"DEA Form lists schedule {dea['substance_schedule_on_form']}"),
                })

            # === Check DEA_FORM_EXPIRED ===
            if "error" not in dea and dea["expiry_date"] < dep_date:
                sev = disc_cfg["DEA_FORM_EXPIRED"]["severity"]
                discrepancies.append({
                    **base_info,
                    "discrepancy_type": "DEA_FORM_EXPIRED",
                    "severity": sev,
                    "recommended_action": actions[sev],
                    "detail": f"Form expired {dea['expiry_date']}, departure {dep_date}",
                })

            # === Check EXPIRED_FACILITY_LICENSE ===
            for role, lic_info in [("Origin", orig_lic), ("Destination", dest_lic)]:
                if "error" in lic_info:
                    continue
                if lic_info["license_status"] != "active" or lic_info["license_expiry_date"] < dep_date:
                    sev = disc_cfg["EXPIRED_FACILITY_LICENSE"]["severity"]
                    fid = lic_info["facility_id"]
                    # Only add if not already added for this (sid, type)
                    existing = [(d["shipment_id"], d["discrepancy_type"]) for d in discrepancies]
                    if (sid, "EXPIRED_FACILITY_LICENSE") not in existing:
                        discrepancies.append({
                            **base_info,
                            "discrepancy_type": "EXPIRED_FACILITY_LICENSE",
                            "severity": sev,
                            "recommended_action": actions[sev],
                            "detail": (f"{role} facility {fid} ({lic_info['facility_name']}): "
                                       f"license {lic_info['license_status']}, "
                                       f"expires {lic_info['license_expiry_date']}"),
                        })

            # === Check UNAUTHORIZED_SCHEDULE ===
            for role, lic_info in [("Origin", orig_lic), ("Destination", dest_lic)]:
                if "error" in lic_info:
                    continue
                auth_list = [x.strip() for x in lic_info["schedules_authorized"].split(",")]
                if schedule not in auth_list:
                    sev = disc_cfg["UNAUTHORIZED_SCHEDULE"]["severity"]
                    fid = lic_info["facility_id"]
                    existing = [(d["shipment_id"], d["discrepancy_type"]) for d in discrepancies]
                    if (sid, "UNAUTHORIZED_SCHEDULE") not in existing:
                        discrepancies.append({
                            **base_info,
                            "discrepancy_type": "UNAUTHORIZED_SCHEDULE",
                            "severity": sev,
                            "recommended_action": actions[sev],
                            "detail": (f"{role} facility {fid} authorized for "
                                       f"[{lic_info['schedules_authorized']}], "
                                       f"shipment is Schedule {schedule}"),
                        })

            # === Check CUSTODY_GAP ===
            route_info = route_map.get(sid)
            if route_info:
                required_cps = route_info["required_checkpoints"]
                zones_in_gps = set(g["zone_name"] for g in gps)
                missing_cps = [cp for cp in required_cps if cp not in zones_in_gps]
                if missing_cps:
                    sev = disc_cfg["CUSTODY_GAP"]["severity"]
                    discrepancies.append({
                        **base_info,
                        "discrepancy_type": "CUSTODY_GAP",
                        "severity": sev,
                        "recommended_action": actions[sev],
                        "detail": f"Missing checkpoint(s): {', '.join(missing_cps)}",
                    })

            # === Check GEOFENCE_VIOLATION ===
            outside = sum(1 for g in gps if g["geofence_status"] == "outside")
            if outside > 0:
                sev = disc_cfg["GEOFENCE_VIOLATION"]["severity"]
                discrepancies.append({
                    **base_info,
                    "discrepancy_type": "GEOFENCE_VIOLATION",
                    "severity": sev,
                    "recommended_action": actions[sev],
                    "detail": f"{outside} GPS ping(s) outside authorized zone",
                })

            # === Check CARRIER_NONCOMPLIANT ===
            if "error" not in carrier:
                issues = []
                if carrier["certification_expiry"] < dep_date:
                    issues.append("certification expired")
                hazmat_scheds = carrier_rules["hazmat_required_schedules"]
                if schedule in hazmat_scheds and not carrier["hazmat_certified"]:
                    issues.append("no hazmat endorsement for Schedule " + schedule)
                if carrier_rules["dea_registration_required"] and not carrier["dea_registered"]:
                    issues.append("not DEA-registered")
                if carrier_rules["controlled_substance_cert_required"] and not carrier["controlled_substance_certified"]:
                    issues.append("no controlled-substance certification")
                if issues:
                    sev = disc_cfg["CARRIER_NONCOMPLIANT"]["severity"]
                    discrepancies.append({
                        **base_info,
                        "discrepancy_type": "CARRIER_NONCOMPLIANT",
                        "severity": sev,
                        "recommended_action": actions[sev],
                        "detail": f"Carrier {cid}: {'; '.join(issues)}",
                    })

        # 6. Deduplicate (shipment_id, discrepancy_type) — keep first
        seen = set()
        unique_disc = []
        for d in discrepancies:
            key = (d["shipment_id"], d["discrepancy_type"])
            if key not in seen:
                seen.add(key)
                unique_disc.append(d)

        # 7. Sort by severity (critical > high > medium), then shipment_id, then type
        sev_order = {"critical": 0, "high": 1, "medium": 2}
        unique_disc.sort(key=lambda x: (sev_order.get(x["severity"], 9),
                                        x["shipment_id"],
                                        x["discrepancy_type"]))

        # 8. Write audit_roster.csv
        cols = ["shipment_id", "manifest_number", "substance_name",
                "dea_schedule", "discrepancy_type", "severity",
                "recommended_action", "detail"]
        roster_path = os.path.join(self.workspace, "audit_roster.csv")
        with open(roster_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for d in unique_disc:
                writer.writerow({c: d[c] for c in cols})

        # 9. Build response summary
        unique_flagged_ids = set(d["shipment_id"] for d in unique_disc)
        type_counts = {}
        for d in unique_disc:
            type_counts[d["discrepancy_type"]] = type_counts.get(d["discrepancy_type"], 0) + 1

        summary_lines = [
            f"Audit complete. Total shipments reviewed: {len(all_shipments)}.",
            f"Unique shipments flagged: {len(unique_flagged_ids)}.",
            f"Total discrepancy records: {len(unique_disc)}.",
            "Breakdown by discrepancy type:",
        ]
        for t in sorted(type_counts.keys()):
            summary_lines.append(f"  {t}: {type_counts[t]}")

        action_str = "\n".join(summary_lines)

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made"
        return self.step(action_str)
