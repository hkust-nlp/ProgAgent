"""
Environment for vessel catch-log / quota reconciliation task.
"""

import csv
import json
import os
import re
import sqlite3
import glob as globmod
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

    # ── Tool methods ────────────────────────────────────────────────

    @tool(
        description="List all registered vessels. Returns paginated results. Each page contains up to 10 vessels.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based)"
                }
            },
            "required": ["page"]
        }
    )
    def list_vessels(self, page: int) -> dict:
        page = int(page)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        page_size = 10
        offset = (page - 1) * page_size
        total = c.execute("SELECT COUNT(*) FROM vessels").fetchone()[0]
        rows = c.execute(
            "SELECT vessel_id, vessel_name, registration_number, flag_state, vessel_type, home_port "
            "FROM vessels ORDER BY vessel_id LIMIT ? OFFSET ?",
            (page_size, offset)
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "total_pages": (total + page_size - 1) // page_size,
            "total_vessels": total,
            "vessels": [
                {"vessel_id": r[0], "vessel_name": r[1], "registration_number": r[2],
                 "flag_state": r[3], "vessel_type": r[4], "home_port": r[5]}
                for r in rows
            ]
        }

    @tool(
        description="Get detailed information for a specific vessel by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "vessel_id": {
                    "type": "integer",
                    "description": "The unique vessel identifier"
                }
            },
            "required": ["vessel_id"]
        }
    )
    def get_vessel_details(self, vessel_id: int) -> dict:
        vessel_id = int(vessel_id)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        row = c.execute("SELECT * FROM vessels WHERE vessel_id = ?", (vessel_id,)).fetchone()
        conn.close()
        if not row:
            return {"error": f"Vessel {vessel_id} not found"}
        return {
            "vessel_id": row[0], "vessel_name": row[1], "registration_number": row[2],
            "flag_state": row[3], "vessel_type": row[4], "home_port": row[5],
            "length_m": row[6], "gross_tonnage": row[7]
        }

    @tool(
        description="Retrieve electronic catch reports for a vessel filtered by species. Returns paginated results (up to 20 per page).",
        parameters={
            "type": "object",
            "properties": {
                "vessel_id": {
                    "type": "integer",
                    "description": "Vessel identifier"
                },
                "species_code": {
                    "type": "string",
                    "description": "Species code (e.g. COD, HAD, TUN)"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based)"
                }
            },
            "required": ["vessel_id", "species_code", "page"]
        }
    )
    def get_catch_reports(self, vessel_id: int, species_code: str, page: int) -> dict:
        vessel_id = int(vessel_id)
        page = int(page)
        page_size = 20
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        total = c.execute(
            "SELECT COUNT(*) FROM catch_reports WHERE vessel_id = ? AND species_code = ?",
            (vessel_id, species_code)
        ).fetchone()[0]
        rows = c.execute(
            "SELECT report_id, report_date, reported_quantity_kg, catch_zone, submission_timestamp "
            "FROM catch_reports WHERE vessel_id = ? AND species_code = ? "
            "ORDER BY report_date LIMIT ? OFFSET ?",
            (vessel_id, species_code, page_size, offset)
        ).fetchall()
        conn.close()
        return {
            "vessel_id": vessel_id,
            "species_code": species_code,
            "page": page,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "total_records": total,
            "reports": [
                {"report_id": r[0], "report_date": r[1], "reported_quantity_kg": r[2],
                 "catch_zone": r[3], "submission_timestamp": r[4]}
                for r in rows
            ]
        }

    @tool(
        description="Get quota certificate for a specific vessel and species. Returns the allocated quota details for the given period.",
        parameters={
            "type": "object",
            "properties": {
                "vessel_id": {
                    "type": "integer",
                    "description": "Vessel identifier"
                },
                "species_code": {
                    "type": "string",
                    "description": "Species code"
                }
            },
            "required": ["vessel_id", "species_code"]
        }
    )
    def get_quota_certificate(self, vessel_id: int, species_code: str) -> dict:
        vessel_id = int(vessel_id)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        row = c.execute(
            "SELECT certificate_id, allocated_quota_kg, period_start, period_end, "
            "certificate_number, issuing_authority "
            "FROM quota_certificates WHERE vessel_id = ? AND species_code = ?",
            (vessel_id, species_code)
        ).fetchone()
        conn.close()
        if not row:
            return {"vessel_id": vessel_id, "species_code": species_code,
                    "quota": None, "message": "No quota certificate found"}
        return {
            "vessel_id": vessel_id,
            "species_code": species_code,
            "certificate_id": row[0],
            "allocated_quota_kg": row[1],
            "period_start": row[2],
            "period_end": row[3],
            "certificate_number": row[4],
            "issuing_authority": row[5]
        }

    @tool(
        description="Retrieve port inspection records for a vessel, optionally filtered by species. Returns paginated results (up to 20 per page).",
        parameters={
            "type": "object",
            "properties": {
                "vessel_id": {
                    "type": "integer",
                    "description": "Vessel identifier"
                },
                "species_code": {
                    "type": "string",
                    "description": "Species code filter (optional, omit for all species)"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based)"
                }
            },
            "required": ["vessel_id", "page"]
        }
    )
    def get_inspection_records(self, vessel_id: int, page: int, species_code: str = None) -> dict:
        vessel_id = int(vessel_id)
        page = int(page)
        page_size = 20
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        if species_code:
            total = c.execute(
                "SELECT COUNT(*) FROM port_inspections WHERE vessel_id = ? AND species_code = ?",
                (vessel_id, species_code)
            ).fetchone()[0]
            rows = c.execute(
                "SELECT inspection_id, inspection_date, port, inspector_name, species_code, "
                "measured_quantity_kg, compliance_flag, remarks "
                "FROM port_inspections WHERE vessel_id = ? AND species_code = ? "
                "ORDER BY inspection_date LIMIT ? OFFSET ?",
                (vessel_id, species_code, page_size, offset)
            ).fetchall()
        else:
            total = c.execute(
                "SELECT COUNT(*) FROM port_inspections WHERE vessel_id = ?",
                (vessel_id,)
            ).fetchone()[0]
            rows = c.execute(
                "SELECT inspection_id, inspection_date, port, inspector_name, species_code, "
                "measured_quantity_kg, compliance_flag, remarks "
                "FROM port_inspections WHERE vessel_id = ? "
                "ORDER BY inspection_date LIMIT ? OFFSET ?",
                (vessel_id, page_size, offset)
            ).fetchall()
        conn.close()
        return {
            "vessel_id": vessel_id,
            "page": page,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "total_records": total,
            "inspections": [
                {"inspection_id": r[0], "inspection_date": r[1], "port": r[2],
                 "inspector_name": r[3], "species_code": r[4],
                 "measured_quantity_kg": r[5], "compliance_flag": r[6], "remarks": r[7]}
                for r in rows
            ]
        }

    @tool(
        description="Get all species codes for which a vessel has filed catch reports.",
        parameters={
            "type": "object",
            "properties": {
                "vessel_id": {
                    "type": "integer",
                    "description": "Vessel identifier"
                }
            },
            "required": ["vessel_id"]
        }
    )
    def get_vessel_species(self, vessel_id: int) -> dict:
        vessel_id = int(vessel_id)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        rows = c.execute(
            "SELECT DISTINCT species_code FROM catch_reports WHERE vessel_id = ? ORDER BY species_code",
            (vessel_id,)
        ).fetchall()
        conn.close()
        return {
            "vessel_id": vessel_id,
            "species_codes": [r[0] for r in rows]
        }

    @tool(
        description="Retrieve AIS tracking positions for a vessel within a date range. Returns paginated results (up to 30 per page).",
        parameters={
            "type": "object",
            "properties": {
                "vessel_id": {
                    "type": "integer",
                    "description": "Vessel identifier"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based)"
                }
            },
            "required": ["vessel_id", "start_date", "end_date", "page"]
        }
    )
    def get_ais_positions(self, vessel_id: int, start_date: str, end_date: str, page: int) -> dict:
        vessel_id = int(vessel_id)
        page = int(page)
        page_size = 30
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        total = c.execute(
            "SELECT COUNT(*) FROM ais_tracking WHERE vessel_id = ? "
            "AND timestamp >= ? AND timestamp <= ?",
            (vessel_id, start_date, end_date + "T23:59:59")
        ).fetchone()[0]
        rows = c.execute(
            "SELECT ais_id, timestamp, latitude, longitude, speed_knots, heading, zone_code "
            "FROM ais_tracking WHERE vessel_id = ? "
            "AND timestamp >= ? AND timestamp <= ? "
            "ORDER BY timestamp LIMIT ? OFFSET ?",
            (vessel_id, start_date, end_date + "T23:59:59", page_size, offset)
        ).fetchall()
        conn.close()
        return {
            "vessel_id": vessel_id,
            "start_date": start_date,
            "end_date": end_date,
            "page": page,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "total_records": total,
            "positions": [
                {"ais_id": r[0], "timestamp": r[1], "latitude": r[2], "longitude": r[3],
                 "speed_knots": r[4], "heading": r[5], "zone_code": r[6]}
                for r in rows
            ]
        }

    @tool(
        description="Get a summary of total reported catch per species for a vessel (electronic reports only).",
        parameters={
            "type": "object",
            "properties": {
                "vessel_id": {
                    "type": "integer",
                    "description": "Vessel identifier"
                }
            },
            "required": ["vessel_id"]
        }
    )
    def get_catch_summary(self, vessel_id: int) -> dict:
        vessel_id = int(vessel_id)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        rows = c.execute(
            "SELECT species_code, SUM(reported_quantity_kg) as total_kg, COUNT(*) as num_reports "
            "FROM catch_reports WHERE vessel_id = ? GROUP BY species_code ORDER BY species_code",
            (vessel_id,)
        ).fetchall()
        conn.close()
        return {
            "vessel_id": vessel_id,
            "species_totals": [
                {"species_code": r[0], "total_reported_kg": round(r[1], 2), "num_reports": r[2]}
                for r in rows
            ]
        }

    @tool(
        description="List all distinct species codes that have quota certificates in the system.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    def list_quota_species(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        rows = c.execute(
            "SELECT DISTINCT species_code FROM quota_certificates ORDER BY species_code"
        ).fetchall()
        conn.close()
        return {"species_codes": [r[0] for r in rows]}

    # ── Step (evaluation) ───────────────────────────────────────────

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion.
        """
        # Compute ground truth
        gt = self._compute_ground_truth()

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: discrepancy_report.csv exists and has correct columns (15 pts) ──
        c1_max = 15
        max_score += c1_max
        report_path = os.path.join(self.workspace, "discrepancy_report.csv")
        report_rows = []
        c1_pass = False
        expected_cols = {"vessel_id", "vessel_name", "species_code", "allocated_quota_kg",
                         "total_catch_kg", "overage_kg", "overage_pct", "tier"}
        if os.path.exists(report_path):
            try:
                with open(report_path, "r") as f:
                    reader = csv.DictReader(f)
                    report_rows = list(reader)
                if expected_cols.issubset(set(reader.fieldnames)):
                    c1_pass = True
            except Exception:
                pass
        c1_score = c1_max if c1_pass else 0
        total_score += c1_score
        eval_criteria["report_file_format"] = {
            "passed": c1_pass, "score": c1_score, "max_score": c1_max,
            "reason": "" if c1_pass else f"discrepancy_report.csv missing or wrong columns. Expected: {expected_cols}"
        }

        # ── Criterion 2: correct vessel-species pairs flagged (25 pts) ──
        c2_max = 25
        max_score += c2_max
        gt_pairs = set()
        for row in gt["discrepancies"]:
            gt_pairs.add((str(row["vessel_id"]), row["species_code"]))
        found_pairs = set()
        for row in report_rows:
            try:
                found_pairs.add((str(row["vessel_id"]).strip(), row["species_code"].strip()))
            except (KeyError, AttributeError):
                pass
        if gt_pairs:
            correct = len(gt_pairs & found_pairs)
            extra = len(found_pairs - gt_pairs)
            # Penalize false positives
            c2_score = max(0, round(c2_max * (correct / len(gt_pairs)) - extra * 2, 1))
            c2_score = min(c2_max, c2_score)
        else:
            c2_score = c2_max if len(found_pairs) == 0 else 0
        c2_pass = c2_score >= c2_max * 0.9
        total_score += c2_score
        eval_criteria["correct_discrepancy_pairs"] = {
            "passed": c2_pass, "score": c2_score, "max_score": c2_max,
            "reason": "" if c2_pass else f"Expected {len(gt_pairs)} pairs, found {len(found_pairs)} (overlap={len(gt_pairs & found_pairs)})"
        }

        # ── Criterion 3: overage_kg and overage_pct accuracy (20 pts) ──
        c3_max = 20
        max_score += c3_max
        gt_lookup = {}
        for row in gt["discrepancies"]:
            key = (str(row["vessel_id"]), row["species_code"])
            gt_lookup[key] = row
        correct_values = 0
        total_checks = 0
        for row in report_rows:
            try:
                key = (str(row["vessel_id"]).strip(), row["species_code"].strip())
                if key in gt_lookup:
                    total_checks += 1
                    gt_row = gt_lookup[key]
                    try:
                        found_overage = float(row["overage_kg"])
                        found_pct = float(row["overage_pct"])
                        if (abs(found_overage - gt_row["overage_kg"]) < 1.0 and
                                abs(found_pct - gt_row["overage_pct"]) < 0.5):
                            correct_values += 1
                    except (ValueError, KeyError):
                        pass
            except (KeyError, AttributeError):
                pass
        if total_checks > 0:
            c3_score = round(c3_max * correct_values / total_checks, 1)
        else:
            c3_score = 0
        c3_pass = c3_score >= c3_max * 0.9
        total_score += c3_score
        eval_criteria["overage_accuracy"] = {
            "passed": c3_pass, "score": c3_score, "max_score": c3_max,
            "reason": "" if c3_pass else f"Correct values: {correct_values}/{total_checks}"
        }

        # ── Criterion 4: tier classification accuracy (15 pts) ──
        c4_max = 15
        max_score += c4_max
        correct_tiers = 0
        tier_checks = 0
        for row in report_rows:
            try:
                key = (str(row["vessel_id"]).strip(), row["species_code"].strip())
                if key in gt_lookup:
                    tier_checks += 1
                    if row.get("tier", "").strip().lower() == gt_lookup[key]["tier"].lower():
                        correct_tiers += 1
            except (KeyError, AttributeError):
                pass
        if tier_checks > 0:
            c4_score = round(c4_max * correct_tiers / tier_checks, 1)
        else:
            c4_score = 0
        c4_pass = c4_score >= c4_max * 0.9
        total_score += c4_score
        eval_criteria["tier_accuracy"] = {
            "passed": c4_pass, "score": c4_score, "max_score": c4_max,
            "reason": "" if c4_pass else f"Correct tiers: {correct_tiers}/{tier_checks}"
        }

        # ── Criterion 5: zone_violations.csv correct (15 pts) ──
        c5_max = 15
        max_score += c5_max
        zv_path = os.path.join(self.workspace, "zone_violations.csv")
        zv_rows = []
        c5_pass = False
        if os.path.exists(zv_path):
            try:
                with open(zv_path, "r") as f:
                    reader = csv.DictReader(f)
                    zv_rows = list(reader)
                gt_zv_pairs = set()
                for v in gt["zone_violations"]:
                    gt_zv_pairs.add((str(v["vessel_id"]), v["species_code"], v["zone_code"]))
                found_zv_pairs = set()
                for row in zv_rows:
                    try:
                        found_zv_pairs.add((
                            str(row["vessel_id"]).strip(),
                            row["species_code"].strip(),
                            row["zone_code"].strip()
                        ))
                    except (KeyError, AttributeError):
                        pass
                if gt_zv_pairs:
                    overlap = len(gt_zv_pairs & found_zv_pairs)
                    extra = len(found_zv_pairs - gt_zv_pairs)
                    c5_score_raw = max(0, c5_max * overlap / len(gt_zv_pairs) - extra * 1)
                    c5_score = min(c5_max, round(c5_score_raw, 1))
                else:
                    c5_score = c5_max if len(found_zv_pairs) == 0 else 0
                c5_pass = c5_score >= c5_max * 0.9
            except Exception:
                c5_score = 0
        else:
            c5_score = 0
        total_score += c5_score
        eval_criteria["zone_violations"] = {
            "passed": c5_pass, "score": c5_score, "max_score": c5_max,
            "reason": "" if c5_pass else "zone_violations.csv missing or inaccurate"
        }

        # ── Criterion 6: action summary in response (10 pts) ──
        c6_max = 10
        max_score += c6_max
        action_lower = action.lower() if action else ""
        # Check that response mentions total vessels flagged count
        n_flagged = len(gt["discrepancies"])
        n_zv = len(gt["zone_violations"])
        found_flagged = False
        found_zv = False
        # Look for counts in the response
        for num in [str(n_flagged)]:
            if num in action_lower:
                found_flagged = True
        for num in [str(n_zv)]:
            if num in action_lower:
                found_zv = True
        c6_score = 0
        if found_flagged:
            c6_score += 5
        if found_zv:
            c6_score += 5
        c6_pass = c6_score == c6_max
        total_score += c6_score
        eval_criteria["response_summary"] = {
            "passed": c6_pass, "score": c6_score, "max_score": c6_max,
            "reason": "" if c6_pass else f"Expected mention of {n_flagged} quota discrepancies and {n_zv} zone violations"
        }

        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    def _compute_ground_truth(self) -> dict:
        """Compute ground truth discrepancies and zone violations."""
        import yaml

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Load quota rules
        rules_path = os.path.join(self.workspace, "quota_rules.yaml")
        with open(rules_path, "r") as f:
            rules = yaml.safe_load(f)

        tolerance_pct = rules["tolerance_pct"]
        overage_tiers = rules["overage_tiers"]
        seasonal_adj = rules["seasonal_adjustments"]
        zone_restricted = rules["zone_restricted_species"]
        insp_disc_thresh = rules["inspection_discrepancy_threshold_pct"]

        # Get all vessels
        vessels = c.execute("SELECT vessel_id, vessel_name FROM vessels ORDER BY vessel_id").fetchall()

        # Load inspector amendments from workspace
        amendments = {}  # inspection_id -> corrected_kg
        for fpath in globmod.glob(os.path.join(self.workspace, "inspector_amendments_batch_*.txt")):
            with open(fpath, "r") as f:
                for line in f:
                    m = re.match(
                        r"Inspection #(\d+) \| Vessel (\d+) \| .+? \| .+? \| "
                        r"Original: [\d.]+ kg \| Corrected: ([\d.]+) kg",
                        line.strip()
                    )
                    if m:
                        amendments[int(m.group(1))] = float(m.group(3))

        # Load landing supplements from workspace CSVs
        landing_supplements = {}  # (vessel_id, species_code) -> total_manual_kg
        for fpath in globmod.glob(os.path.join(self.workspace, "landing_supplement_*.csv")):
            with open(fpath, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (int(row["vessel_id"]), row["species_code"])
                    landing_supplements[key] = landing_supplements.get(key, 0) + float(row["manual_landing_kg"])

        # Load AIS zone summaries
        ais_zone_summaries = {}  # vessel_id -> {zone: hours}
        for fpath in globmod.glob(os.path.join(self.workspace, "ais_zone_summary_vessel_*.json")):
            with open(fpath, "r") as f:
                data = json.load(f)
                ais_zone_summaries[data["vessel_id"]] = data.get("zone_hours", {})

        discrepancies = []
        zone_violations = []

        for vid, vname in vessels:
            # Get all species this vessel has catch reports for, OR landing supplements for.
            # The prompt requires combining electronic reports with manual landing supplements,
            # so a (vessel, species) pair appearing in supplements alone must still be considered.
            species_set = set()
            for (sp_code,) in c.execute(
                "SELECT DISTINCT species_code FROM catch_reports WHERE vessel_id = ?",
                (vid,)
            ).fetchall():
                species_set.add(sp_code)
            for (v_id, sp) in landing_supplements.keys():
                if v_id == vid:
                    species_set.add(sp)

            for sp_code in sorted(species_set):
                # Electronic catch total
                electronic_total = c.execute(
                    "SELECT SUM(reported_quantity_kg) FROM catch_reports "
                    "WHERE vessel_id = ? AND species_code = ?",
                    (vid, sp_code)
                ).fetchone()[0] or 0.0

                # Manual landing supplements
                manual_total = landing_supplements.get((vid, sp_code), 0.0)

                total_catch = electronic_total + manual_total

                # Get quota
                quota_row = c.execute(
                    "SELECT allocated_quota_kg, period_start, period_end FROM quota_certificates "
                    "WHERE vessel_id = ? AND species_code = ?",
                    (vid, sp_code)
                ).fetchone()

                if not quota_row:
                    # No quota means they shouldn't be catching this species at all
                    # If they have any catch, it's a violation
                    if total_catch > 0:
                        discrepancies.append({
                            "vessel_id": vid,
                            "vessel_name": vname,
                            "species_code": sp_code,
                            "allocated_quota_kg": 0.0,
                            "total_catch_kg": round(total_catch, 2),
                            "overage_kg": round(total_catch, 2),
                            "overage_pct": 100.0,
                            "tier": "critical",
                        })
                    continue

                allocated = quota_row[0]
                period_start = quota_row[1]
                period_end = quota_row[2]

                # Apply seasonal adjustment: find which months fall in the period
                # and use the LOWEST adjustment factor (most restrictive)
                from datetime import datetime as dt
                start_d = dt.strptime(period_start, "%Y-%m-%d")
                end_d = dt.strptime(period_end, "%Y-%m-%d")
                month_factors = []
                current = start_d
                while current <= end_d:
                    month_name = current.strftime("%B")
                    factor = seasonal_adj.get(month_name, 1.0)
                    month_factors.append(factor)
                    # Move to next month
                    if current.month == 12:
                        current = current.replace(year=current.year + 1, month=1)
                    else:
                        current = current.replace(month=current.month + 1)

                # Effective quota = allocated * min seasonal factor
                min_factor = min(month_factors) if month_factors else 1.0
                effective_quota = allocated * min_factor

                # Check if over tolerance
                if effective_quota > 0:
                    overage_pct = ((total_catch - effective_quota) / effective_quota) * 100.0
                else:
                    overage_pct = 100.0 if total_catch > 0 else 0.0

                if overage_pct > tolerance_pct:
                    overage_kg = total_catch - effective_quota
                    # Determine tier
                    tier = "minor"
                    for t in overage_tiers:
                        if t["min_pct"] <= overage_pct <= t["max_pct"]:
                            tier = t["tier"]
                            break

                    discrepancies.append({
                        "vessel_id": vid,
                        "vessel_name": vname,
                        "species_code": sp_code,
                        "allocated_quota_kg": round(effective_quota, 2),
                        "total_catch_kg": round(total_catch, 2),
                        "overage_kg": round(overage_kg, 2),
                        "overage_pct": round(overage_pct, 2),
                        "tier": tier,
                    })

            # Check zone violations using AIS zone summaries
            if vid in ais_zone_summaries:
                zone_hours = ais_zone_summaries[vid]
                for zone_code, hours in zone_hours.items():
                    if hours > 0 and zone_code in zone_restricted:
                        restricted_sp = zone_restricted[zone_code]
                        # Check if vessel caught any restricted species in this zone
                        for sp in restricted_sp:
                            catch_in_zone = c.execute(
                                "SELECT SUM(reported_quantity_kg) FROM catch_reports "
                                "WHERE vessel_id = ? AND species_code = ? AND catch_zone = ?",
                                (vid, sp, zone_code)
                            ).fetchone()[0]
                            if catch_in_zone and catch_in_zone > 0:
                                zone_violations.append({
                                    "vessel_id": vid,
                                    "vessel_name": vname,
                                    "species_code": sp,
                                    "zone_code": zone_code,
                                    "catch_kg_in_zone": round(catch_in_zone, 2),
                                    "hours_in_zone": hours,
                                })

        conn.close()

        # Sort discrepancies by overage_pct descending
        discrepancies.sort(key=lambda x: x["overage_pct"], reverse=True)
        zone_violations.sort(key=lambda x: (x["vessel_id"], x["zone_code"], x["species_code"]))

        return {"discrepancies": discrepancies, "zone_violations": zone_violations}

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # Step 1: Load config files from workspace
        with open(os.path.join(self.workspace, "quota_rules.yaml"), "r") as f:
            rules = yaml.safe_load(f)

        tolerance_pct = rules["tolerance_pct"]
        overage_tiers = rules["overage_tiers"]
        seasonal_adj = rules["seasonal_adjustments"]
        zone_restricted = rules["zone_restricted_species"]

        # Load species reference
        with open(os.path.join(self.workspace, "species_reference.json"), "r") as f:
            species_ref = json.load(f)

        # Load landing supplements from CSVs
        landing_supplements = {}
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "landing_supplement_*.csv"))):
            with open(fpath, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (int(row["vessel_id"]), row["species_code"])
                    landing_supplements[key] = landing_supplements.get(key, 0) + float(row["manual_landing_kg"])

        # Load AIS zone summaries
        ais_zone_summaries = {}
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "ais_zone_summary_vessel_*.json"))):
            with open(fpath, "r") as f:
                data = json.load(f)
                ais_zone_summaries[data["vessel_id"]] = data.get("zone_hours", {})

        # Load inspector amendments
        amendments = {}
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "inspector_amendments_batch_*.txt"))):
            with open(fpath, "r") as f:
                for line in f:
                    m = re.match(
                        r"Inspection #(\d+) \| Vessel (\d+) \| .+? \| .+? \| "
                        r"Original: [\d.]+ kg \| Corrected: ([\d.]+) kg",
                        line.strip()
                    )
                    if m:
                        amendments[int(m.group(1))] = float(m.group(3))

        # Step 2: List all vessels using paginated tool
        all_vessels = []
        page = 1
        while True:
            result = call_tool("list_vessels", page=page)
            all_vessels.extend(result["vessels"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 3: For each vessel, get species and compute totals
        discrepancies = []
        zone_violations = []

        for vessel in all_vessels:
            vid = vessel["vessel_id"]
            vname = vessel["vessel_name"]

            # Get species for this vessel
            sp_result = call_tool("get_vessel_species", vessel_id=vid)
            # Manual-only landings must also be reconciled, even without
            # an electronic report or quota certificate.
            vessel_species = sorted(
                set(sp_result["species_codes"])
                | {species for vessel_id, species in landing_supplements if vessel_id == vid}
            )

            for sp_code in vessel_species:
                # Get electronic catch summary
                catch_result = call_tool("get_catch_summary", vessel_id=vid)
                electronic_total = 0.0
                for st in catch_result["species_totals"]:
                    if st["species_code"] == sp_code:
                        electronic_total = st["total_reported_kg"]
                        break

                # Add manual landing supplements
                manual_total = landing_supplements.get((vid, sp_code), 0.0)
                total_catch = electronic_total + manual_total

                # Get quota certificate
                quota_result = call_tool("get_quota_certificate", vessel_id=vid, species_code=sp_code)
                if quota_result.get("quota") is None and "allocated_quota_kg" not in quota_result:
                    # No quota -- any catch is a violation
                    if total_catch > 0:
                        discrepancies.append({
                            "vessel_id": vid,
                            "vessel_name": vname,
                            "species_code": sp_code,
                            "allocated_quota_kg": 0.0,
                            "total_catch_kg": round(total_catch, 2),
                            "overage_kg": round(total_catch, 2),
                            "overage_pct": 100.0,
                            "tier": "critical",
                        })
                    continue

                allocated = quota_result["allocated_quota_kg"]
                period_start = quota_result["period_start"]
                period_end = quota_result["period_end"]

                # Seasonal adjustment
                from datetime import datetime as dt
                start_d = dt.strptime(period_start, "%Y-%m-%d")
                end_d = dt.strptime(period_end, "%Y-%m-%d")
                month_factors = []
                current = start_d
                while current <= end_d:
                    month_name = current.strftime("%B")
                    factor = seasonal_adj.get(month_name, 1.0)
                    month_factors.append(factor)
                    if current.month == 12:
                        current = current.replace(year=current.year + 1, month=1)
                    else:
                        current = current.replace(month=current.month + 1)

                min_factor = min(month_factors) if month_factors else 1.0
                effective_quota = allocated * min_factor

                if effective_quota > 0:
                    overage_pct = ((total_catch - effective_quota) / effective_quota) * 100.0
                else:
                    overage_pct = 100.0 if total_catch > 0 else 0.0

                if overage_pct > tolerance_pct:
                    overage_kg = total_catch - effective_quota
                    tier = "minor"
                    for t in overage_tiers:
                        if t["min_pct"] <= overage_pct <= t["max_pct"]:
                            tier = t["tier"]
                            break
                    discrepancies.append({
                        "vessel_id": vid,
                        "vessel_name": vname,
                        "species_code": sp_code,
                        "allocated_quota_kg": round(effective_quota, 2),
                        "total_catch_kg": round(total_catch, 2),
                        "overage_kg": round(overage_kg, 2),
                        "overage_pct": round(overage_pct, 2),
                        "tier": tier,
                    })

            # Zone violations: check AIS zone data
            if vid in ais_zone_summaries:
                zone_hours = ais_zone_summaries[vid]
                for zone_code, hours in zone_hours.items():
                    if hours > 0 and zone_code in zone_restricted:
                        restricted_sp = zone_restricted[zone_code]
                        for sp in restricted_sp:
                            # Need to check if vessel caught restricted species in this zone
                            # Use catch reports tool
                            cr_result = call_tool("get_catch_reports", vessel_id=vid, species_code=sp, page=1)
                            total_in_zone = 0.0
                            # Check all pages
                            all_reports = cr_result["reports"]
                            pg = 2
                            while pg <= cr_result["total_pages"]:
                                more = call_tool("get_catch_reports", vessel_id=vid, species_code=sp, page=pg)
                                all_reports.extend(more["reports"])
                                pg += 1
                            for r in all_reports:
                                if r["catch_zone"] == zone_code:
                                    total_in_zone += r["reported_quantity_kg"]
                            if total_in_zone > 0:
                                zone_violations.append({
                                    "vessel_id": vid,
                                    "vessel_name": vname,
                                    "species_code": sp,
                                    "zone_code": zone_code,
                                    "catch_kg_in_zone": round(total_in_zone, 2),
                                    "hours_in_zone": hours,
                                })

        # Sort outputs
        discrepancies.sort(key=lambda x: x["overage_pct"], reverse=True)
        zone_violations.sort(key=lambda x: (x["vessel_id"], x["zone_code"], x["species_code"]))

        # Write discrepancy_report.csv
        report_path = os.path.join(self.workspace, "discrepancy_report.csv")
        if discrepancies:
            with open(report_path, "w", newline="") as f:
                cols = ["vessel_id", "vessel_name", "species_code", "allocated_quota_kg",
                        "total_catch_kg", "overage_kg", "overage_pct", "tier"]
                writer = csv.DictWriter(f, fieldnames=cols)
                writer.writeheader()
                for row in discrepancies:
                    writer.writerow(row)
        else:
            with open(report_path, "w", newline="") as f:
                cols = ["vessel_id", "vessel_name", "species_code", "allocated_quota_kg",
                        "total_catch_kg", "overage_kg", "overage_pct", "tier"]
                writer = csv.DictWriter(f, fieldnames=cols)
                writer.writeheader()

        # Write zone_violations.csv
        zv_path = os.path.join(self.workspace, "zone_violations.csv")
        with open(zv_path, "w", newline="") as f:
            cols = ["vessel_id", "vessel_name", "species_code", "zone_code",
                    "catch_kg_in_zone", "hours_in_zone"]
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for row in zone_violations:
                writer.writerow(row)

        # Build action string
        action = (
            f"Reconciliation complete. Found {len(discrepancies)} quota discrepancies "
            f"across all vessels and species where total catch (electronic reports plus "
            f"manual landing supplements) exceeded the seasonally-adjusted allocated quota "
            f"beyond the {tolerance_pct}% tolerance threshold. "
            f"Additionally, identified {len(zone_violations)} zone restriction violations "
            f"where vessels caught restricted species in prohibited zones. "
            f"Results saved to discrepancy_report.csv and zone_violations.csv."
        )

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need >= 15"

        return self.step(action)
