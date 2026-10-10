"""
Environment for industrial facility compliance risk assessment task.
"""

import csv
import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Tuple

import yaml


# ── Decorator ───────────────────────────────────────────────────────────────

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ── Task Environment ────────────────────────────────────────────────────────

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

    # ── Tool methods ────────────────────────────────────────────────────

    @tool(
        description=(
            "List all registered industrial facilities with pagination. "
            "Returns facility_id, name, sector, region, and operating_status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of facilities per page. Defaults to 10.",
                },
            },
            "required": [],
        },
    )
    def list_facilities(self, page: int = 1, page_size: int = 10) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM facilities")
        total = c.fetchone()[0]
        total_pages = max(1, (total + page_size - 1) // page_size)
        offset = (page - 1) * page_size
        c.execute(
            "SELECT facility_id, name, sector, region, operating_status "
            "FROM facilities ORDER BY facility_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return _envelope({
            "page": page,
            "page_size": page_size,
            "total_facilities": total,
            "total_pages": total_pages,
            "facilities": rows,
        })

    @tool(
        description=(
            "Get detailed information about a specific facility including "
            "coordinates, employee count, and established year."
        ),
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "The facility identifier, e.g. FAC-0001.",
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_facility_details(self, facility_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM facilities WHERE facility_id = ?",
                  (facility_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"Facility {facility_id} not found."}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description=(
            "Get the effluent sensor readings for a specific facility. "
            "Optionally filter by pollutant code. Returns all recorded "
            "readings ordered by timestamp descending (most recent first)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "The facility identifier.",
                },
                "pollutant_code": {
                    "type": "string",
                    "description": (
                        "Optional pollutant code to filter by, e.g. BOD, COD, "
                        "TSS, NH3, PH, TEMP, OG, TN, TP, HM_PB, HM_CD, HM_CR."
                    ),
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_sensor_readings(self, facility_id: str,
                            pollutant_code: str = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if pollutant_code:
            c.execute(
                "SELECT reading_id, pollutant_code, value, unit, timestamp, "
                "sensor_status FROM sensor_readings "
                "WHERE facility_id = ? AND pollutant_code = ? "
                "ORDER BY timestamp DESC",
                (facility_id, pollutant_code),
            )
        else:
            c.execute(
                "SELECT reading_id, pollutant_code, value, unit, timestamp, "
                "sensor_status FROM sensor_readings "
                "WHERE facility_id = ? ORDER BY timestamp DESC",
                (facility_id,),
            )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return _envelope({"facility_id": facility_id, "readings": rows})

    @tool(
        description=(
            "Get the discharge permit limits for a specific facility. "
            "Returns all active permits with daily maximum and monthly "
            "average maximum limits per pollutant."
        ),
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "The facility identifier.",
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_permit_limits(self, facility_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT permit_id, pollutant_code, daily_max, monthly_avg_max, "
            "unit, effective_date, expiry_date FROM discharge_permits "
            "WHERE facility_id = ? ORDER BY pollutant_code",
            (facility_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps({"facility_id": facility_id, "permits": rows}, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Get historical inspection violation records for a specific "
            "facility. Returns violation type, severity (1-5), inspection "
            "date, resolution status, and resolution date if applicable."
        ),
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "The facility identifier.",
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_violation_records(self, facility_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT violation_id, inspection_date, violation_type, severity, "
            "description, resolved, resolution_date FROM violations "
            "WHERE facility_id = ? ORDER BY inspection_date DESC",
            (facility_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return json.dumps({"facility_id": facility_id, "violations": rows}, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Get maintenance log entries for a specific facility. Returns "
            "equipment name, maintenance type, scheduled date, completion "
            "date, and current status (Completed / Scheduled / Overdue)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "facility_id": {
                    "type": "string",
                    "description": "The facility identifier.",
                },
            },
            "required": ["facility_id"],
        },
    )
    def get_maintenance_status(self, facility_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT log_id, equipment_name, maintenance_type, scheduled_date, "
            "completed_date, status FROM maintenance_logs "
            "WHERE facility_id = ? ORDER BY scheduled_date DESC",
            (facility_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return _envelope({"facility_id": facility_id, "maintenance_logs": rows})

    # ── Internal helpers (for step ground-truth computation) ────────────

    def _load_workspace_config(self):
        """Load the three fixed config files from workspace."""
        with open(os.path.join(self.workspace, "risk_scoring_config.yaml")) as f:
            risk_cfg = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "pollutant_hazard_tiers.csv")) as f:
            reader = csv.DictReader(f)
            hazard = {r["pollutant_code"]: float(r["tier_multiplier"])
                      for r in reader}
        with open(os.path.join(self.workspace, "dispatch_rules.json")) as f:
            dispatch = json.load(f)
        return risk_cfg, hazard, dispatch

    def _load_site_assessments(self):
        """Load sensitivity zone data from site_assessment*.json files."""
        zones = {}  # facility_id -> zone_multiplier
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("site_assessment") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                for rec in data:
                    zones[rec["facility_id"]] = rec["zone_multiplier"]
        return zones

    def _load_lab_analyses(self):
        """Load lab verification data from lab_analysis*.csv files.
        Returns {(facility_id, pollutant_code): lab_verified_value}."""
        lab = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("lab_analysis") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        key = (row["facility_id"], row["pollutant_code"])
                        lab[key] = float(row["lab_verified_value"])
        return lab

    def _load_corrective_actions(self):
        """Load corrective action statuses from corrective_actions* files.
        Returns {facility_id: count_of_overdue_actions}."""
        overdue = {}
        for fname in sorted(os.listdir(self.workspace)):
            if not fname.startswith("corrective_actions"):
                continue
            fpath = os.path.join(self.workspace, fname)

            if fname.endswith(".yaml"):
                with open(fpath) as f:
                    records = yaml.safe_load(f)
                if records:
                    for rec in records:
                        fid = rec["facility_id"]
                        if rec["corrective_action_status"] == "Overdue":
                            overdue[fid] = overdue.get(fid, 0) + 1

            elif fname.endswith(".md"):
                with open(fpath) as f:
                    text = f.read()
                # Parse markdown: look for Facility and Status lines
                current_fid = None
                for line in text.splitlines():
                    line = line.strip()
                    if line.startswith("- Facility:"):
                        current_fid = line.split(":", 1)[1].strip()
                    elif line.startswith("- Corrective Action Status:"):
                        status = line.split(":", 1)[1].strip()
                        if status == "Overdue" and current_fid:
                            overdue[current_fid] = overdue.get(current_fid, 0) + 1

            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    text = f.read()
                blocks = text.split("---")
                for block in blocks:
                    fid = None
                    status = None
                    for line in block.strip().splitlines():
                        line = line.strip()
                        if line.startswith("Facility:"):
                            fid = line.split(":", 1)[1].strip()
                        elif line.startswith("Corrective Action Status:"):
                            status = line.split(":", 1)[1].strip()
                    if fid and status == "Overdue":
                        overdue[fid] = overdue.get(fid, 0) + 1

        return overdue

    def _compute_ground_truth(self):
        """Compute the full ground-truth dispatch list."""
        risk_cfg, hazard_mult, dispatch_cfg = self._load_workspace_config()
        zone_mult = self._load_site_assessments()
        lab_data = self._load_lab_analyses()
        overdue_ca = self._load_corrective_actions()

        weights = risk_cfg["scoring_weights"]
        recency = risk_cfg["recency_weights"]
        unresolved_mult = risk_cfg["unresolved_multiplier"]
        ref_date = datetime.strptime(risk_cfg["reference_date"], "%Y-%m-%d")
        cat_thresholds = risk_cfg["risk_categories"]  # CRITICAL, HIGH, MODERATE
        disp_thresholds = risk_cfg["dispatch_thresholds"]  # IMMEDIATE, PRIORITY, ROUTINE

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Get active facilities
        c = conn.cursor()
        c.execute(
            "SELECT facility_id, name, region FROM facilities "
            "WHERE operating_status = 'Active' ORDER BY facility_id"
        )
        active_facs = [dict(r) for r in c.fetchall()]

        results = []
        for fac in active_facs:
            fid = fac["facility_id"]

            # 1. Exceedance score
            # Get latest sensor reading per pollutant
            c.execute(
                "SELECT pollutant_code, value, timestamp FROM sensor_readings "
                "WHERE facility_id = ? ORDER BY pollutant_code, timestamp DESC",
                (fid,),
            )
            sensor_latest = {}
            for row in c.fetchall():
                pc = row["pollutant_code"]
                if pc not in sensor_latest:
                    sensor_latest[pc] = row["value"]

            # Get permit limits (daily_max) per pollutant
            c.execute(
                "SELECT pollutant_code, daily_max FROM discharge_permits "
                "WHERE facility_id = ?",
                (fid,),
            )
            permits = {}
            for row in c.fetchall():
                pc = row["pollutant_code"]
                # If multiple permits for same pollutant, use the most
                # restrictive (lowest daily_max)
                if pc not in permits or row["daily_max"] < permits[pc]:
                    permits[pc] = row["daily_max"]

            exceedance_score = 0.0
            for pc in sensor_latest:
                if pc not in permits:
                    continue
                sensor_val = sensor_latest[pc]
                lab_val = lab_data.get((fid, pc))
                effective_val = sensor_val
                if lab_val is not None and lab_val > sensor_val:
                    effective_val = lab_val
                limit = permits[pc]
                if effective_val > limit:
                    excess = (effective_val - limit) / limit
                    tier_m = hazard_mult.get(pc, 1.0)
                    exceedance_score += excess * tier_m

            # 2. Violation history score
            c.execute(
                "SELECT severity, inspection_date, resolved FROM violations "
                "WHERE facility_id = ?",
                (fid,),
            )
            violation_score = 0.0
            for row in c.fetchall():
                sev = row["severity"]
                insp = datetime.strptime(row["inspection_date"], "%Y-%m-%d")
                days_ago = (ref_date - insp).days
                if days_ago <= 90:
                    rw = recency["last_90_days"]
                elif days_ago <= 180:
                    rw = recency["last_180_days"]
                elif days_ago <= 365:
                    rw = recency["last_365_days"]
                else:
                    rw = recency["older"]
                base = sev * rw
                if not row["resolved"]:
                    base *= unresolved_mult
                violation_score += base

            # 3. Maintenance risk score (count of overdue items)
            c.execute(
                "SELECT COUNT(*) FROM maintenance_logs "
                "WHERE facility_id = ? AND status = 'Overdue'",
                (fid,),
            )
            maintenance_score = float(c.fetchone()[0])

            # 4. Lab discrepancy score
            # Count pollutants where lab_verified > sensor by > 10%
            lab_disc_count = 0
            for pc, sv in sensor_latest.items():
                lv = lab_data.get((fid, pc))
                if lv is not None and sv > 0 and (lv - sv) / sv > 0.10:
                    lab_disc_count += 1
            lab_disc_score = float(lab_disc_count)

            # 5. Corrective action score (count of overdue actions)
            ca_score = float(overdue_ca.get(fid, 0))

            # Weighted raw score
            raw = (
                exceedance_score * weights["exceedance"]
                + violation_score * weights["violation_history"]
                + maintenance_score * weights["maintenance_risk"]
                + lab_disc_score * weights["lab_discrepancy"]
                + ca_score * weights["corrective_action"]
            )

            # Determine primary concern (highest weighted component)
            components = {
                "Exceedance": exceedance_score * weights["exceedance"],
                "Violations": violation_score * weights["violation_history"],
                "Maintenance": maintenance_score * weights["maintenance_risk"],
                "Lab Discrepancy": lab_disc_score * weights["lab_discrepancy"],
                "Corrective Actions": ca_score * weights["corrective_action"],
            }
            primary = max(components, key=components.get)

            # Apply zone multiplier
            zm = zone_mult.get(fid, 1.0)
            risk_score = round(raw * zm, 2)

            # Risk category
            if risk_score >= cat_thresholds["CRITICAL"]:
                risk_cat = "CRITICAL"
            elif risk_score >= cat_thresholds["HIGH"]:
                risk_cat = "HIGH"
            elif risk_score >= cat_thresholds["MODERATE"]:
                risk_cat = "MODERATE"
            else:
                risk_cat = "LOW"

            # Dispatch urgency
            if risk_score >= disp_thresholds["IMMEDIATE"]:
                urgency = "IMMEDIATE"
            elif risk_score >= disp_thresholds["PRIORITY"]:
                urgency = "PRIORITY"
            elif risk_score >= disp_thresholds["ROUTINE"]:
                urgency = "ROUTINE"
            else:
                urgency = "MONITOR"

            results.append({
                "facility_id": fid,
                "facility_name": fac["name"],
                "region": fac["region"],
                "risk_score": risk_score,
                "risk_category": risk_cat,
                "primary_concern": primary,
                "dispatch_urgency": urgency,
            })

        conn.close()

        # Sort: risk_score descending, facility_id ascending for ties
        results.sort(key=lambda r: (-r["risk_score"], r["facility_id"]))

        # Add rank
        for i, r in enumerate(results, 1):
            r["rank"] = i

        return results

    # ── Evaluation ──────────────────────────────────────────────────────

    def step(
        self, action: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's
        final response.

        Returns a reward based on evaluation results.

        Args:
            action: The agent's final response.

        Returns:
            reward: The reward based on task completion (between 0.0 and 1.0).
            info: Evaluation results.
        """
        ground_truth = self._compute_ground_truth()
        gt_map = {r["facility_id"]: r for r in ground_truth}

        criteria = {}

        # ── Criterion 1: dispatch_list.csv exists with correct columns (10 pts)
        csv_path = os.path.join(self.workspace, "dispatch_list.csv")
        expected_cols = [
            "rank", "facility_id", "facility_name", "region",
            "risk_score", "risk_category", "primary_concern",
            "dispatch_urgency",
        ]
        c1_pass = False
        agent_rows = []
        if os.path.isfile(csv_path):
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    if all(c in cols for c in expected_cols):
                        agent_rows = list(reader)
                        c1_pass = True
            except Exception:
                pass
        criteria["csv_structure"] = {
            "passed": c1_pass,
            "score": 10 if c1_pass else 0,
            "max_score": 10,
            "reason": "" if c1_pass else "dispatch_list.csv missing or wrong columns",
        }

        # ── Criterion 2: Correct set of facilities (15 pts)
        gt_ids = set(r["facility_id"] for r in ground_truth)
        agent_ids = set(r.get("facility_id", "") for r in agent_rows)
        c2_pass = gt_ids == agent_ids
        criteria["facility_set"] = {
            "passed": c2_pass,
            "score": 15 if c2_pass else 0,
            "max_score": 15,
            "reason": "" if c2_pass else (
                f"Expected {len(gt_ids)} facilities, got {len(agent_ids)}; "
                f"missing={gt_ids - agent_ids}, extra={agent_ids - gt_ids}"
            ),
        }

        # ── Criterion 3: Risk scores correct (25 pts) — partial credit
        c3_correct = 0
        c3_total = len(ground_truth)
        for row in agent_rows:
            fid = row.get("facility_id", "")
            try:
                agent_score = round(float(row.get("risk_score", -1)), 2)
            except (ValueError, TypeError):
                continue
            gt_rec = gt_map.get(fid)
            if gt_rec and abs(agent_score - gt_rec["risk_score"]) < 0.015:
                c3_correct += 1
        c3_ratio = c3_correct / c3_total if c3_total > 0 else 0
        c3_score = round(c3_ratio * 25, 2)
        criteria["risk_scores"] = {
            "passed": c3_ratio >= 0.99,
            "score": c3_score,
            "max_score": 25,
            "reason": "" if c3_ratio >= 0.99 else (
                f"{c3_correct}/{c3_total} risk scores correct"
            ),
        }

        # ── Criterion 4: Correct ranking / sort order (15 pts)
        c4_pass = False
        if len(agent_rows) == len(ground_truth):
            agent_order = [r.get("facility_id", "") for r in agent_rows]
            gt_order = [r["facility_id"] for r in ground_truth]
            c4_pass = agent_order == gt_order
            # Also check rank column
            if c4_pass:
                for i, row in enumerate(agent_rows):
                    try:
                        if int(row.get("rank", -1)) != i + 1:
                            c4_pass = False
                            break
                    except (ValueError, TypeError):
                        c4_pass = False
                        break
        criteria["ranking"] = {
            "passed": c4_pass,
            "score": 15 if c4_pass else 0,
            "max_score": 15,
            "reason": "" if c4_pass else "Incorrect sort order or rank values",
        }

        # ── Criterion 5: Risk categories correct (10 pts)
        c5_correct = 0
        for row in agent_rows:
            fid = row.get("facility_id", "")
            gt_rec = gt_map.get(fid)
            if gt_rec and row.get("risk_category") == gt_rec["risk_category"]:
                c5_correct += 1
        c5_ratio = c5_correct / c3_total if c3_total > 0 else 0
        c5_score = round(c5_ratio * 10, 2)
        criteria["risk_categories"] = {
            "passed": c5_ratio >= 0.99,
            "score": c5_score,
            "max_score": 10,
            "reason": "" if c5_ratio >= 0.99 else (
                f"{c5_correct}/{c3_total} categories correct"
            ),
        }

        # ── Criterion 6: Dispatch urgency correct (10 pts)
        c6_correct = 0
        for row in agent_rows:
            fid = row.get("facility_id", "")
            gt_rec = gt_map.get(fid)
            if gt_rec and row.get("dispatch_urgency") == gt_rec["dispatch_urgency"]:
                c6_correct += 1
        c6_ratio = c6_correct / c3_total if c3_total > 0 else 0
        c6_score = round(c6_ratio * 10, 2)
        criteria["dispatch_urgency"] = {
            "passed": c6_ratio >= 0.99,
            "score": c6_score,
            "max_score": 10,
            "reason": "" if c6_ratio >= 0.99 else (
                f"{c6_correct}/{c3_total} urgency values correct"
            ),
        }

        # ── Criterion 7: Primary concern correct (10 pts)
        c7_correct = 0
        for row in agent_rows:
            fid = row.get("facility_id", "")
            gt_rec = gt_map.get(fid)
            if gt_rec and row.get("primary_concern") == gt_rec["primary_concern"]:
                c7_correct += 1
        c7_ratio = c7_correct / c3_total if c3_total > 0 else 0
        c7_score = round(c7_ratio * 10, 2)
        criteria["primary_concern"] = {
            "passed": c7_ratio >= 0.99,
            "score": c7_score,
            "max_score": 10,
            "reason": "" if c7_ratio >= 0.99 else (
                f"{c7_correct}/{c3_total} primary concerns correct"
            ),
        }

        # ── Criterion 8: Response summary mentions top-5 (5 pts)
        top5 = ground_truth[:5]
        c8_count = 0
        action_upper = action.upper() if action else ""
        for rec in top5:
            if rec["facility_id"] in (action or ""):
                c8_count += 1
        c8_pass = c8_count >= 4  # at least 4 of 5
        criteria["response_summary"] = {
            "passed": c8_pass,
            "score": 5 if c8_pass else 0,
            "max_score": 5,
            "reason": "" if c8_pass else (
                f"Only {c8_count}/5 top facilities mentioned in response"
            ),
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ── Self-verification ───────────────────────────────────────────────

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
        # ── Step 1: Read workspace config files ─────────────────────────
        with open(os.path.join(self.workspace, "risk_scoring_config.yaml")) as f:
            risk_cfg = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "pollutant_hazard_tiers.csv")) as f:
            reader = csv.DictReader(f)
            hazard_mult = {r["pollutant_code"]: float(r["tier_multiplier"])
                           for r in reader}

        with open(os.path.join(self.workspace, "dispatch_rules.json")) as f:
            dispatch_cfg = json.load(f)

        # ── Step 2: Read site assessments (zone multipliers) ────────────
        zone_mult = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("site_assessment") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                for rec in data:
                    zone_mult[rec["facility_id"]] = rec["zone_multiplier"]

        # ── Step 3: Read lab analysis files ─────────────────────────────
        lab_data = {}  # (facility_id, pollutant_code) -> lab_verified_value
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("lab_analysis") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        key = (row["facility_id"], row["pollutant_code"])
                        lab_data[key] = float(row["lab_verified_value"])

        # ── Step 4: Read corrective action files ────────────────────────
        overdue_ca = {}  # facility_id -> count
        for fname in sorted(os.listdir(self.workspace)):
            if not fname.startswith("corrective_actions"):
                continue
            fpath = os.path.join(self.workspace, fname)

            if fname.endswith(".yaml"):
                with open(fpath) as f:
                    records = yaml.safe_load(f)
                if records:
                    for rec in records:
                        if rec["corrective_action_status"] == "Overdue":
                            fid = rec["facility_id"]
                            overdue_ca[fid] = overdue_ca.get(fid, 0) + 1

            elif fname.endswith(".md"):
                with open(fpath) as f:
                    text = f.read()
                current_fid = None
                for line in text.splitlines():
                    line = line.strip()
                    if line.startswith("- Facility:"):
                        current_fid = line.split(":", 1)[1].strip()
                    elif line.startswith("- Corrective Action Status:"):
                        status = line.split(":", 1)[1].strip()
                        if status == "Overdue" and current_fid:
                            overdue_ca[current_fid] = overdue_ca.get(
                                current_fid, 0) + 1

            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    text = f.read()
                blocks = text.split("---")
                for block in blocks:
                    fid = None
                    status = None
                    for line in block.strip().splitlines():
                        line = line.strip()
                        if line.startswith("Facility:"):
                            fid = line.split(":", 1)[1].strip()
                        elif line.startswith("Corrective Action Status:"):
                            status = line.split(":", 1)[1].strip()
                    if fid and status == "Overdue":
                        overdue_ca[fid] = overdue_ca.get(fid, 0) + 1

        # ── Step 5: Gather all facility data via tools ──────────────────
        weights = risk_cfg["scoring_weights"]
        recency_w = risk_cfg["recency_weights"]
        unresolved_mult_val = risk_cfg["unresolved_multiplier"]
        ref_date = datetime.strptime(risk_cfg["reference_date"], "%Y-%m-%d")
        cat_thresholds = risk_cfg["risk_categories"]
        disp_thresholds = risk_cfg["dispatch_thresholds"]

        # Get all facilities via pagination
        all_facilities = []
        page = 1
        while True:
            result = json.loads(self.tools["list_facilities"](page=page, page_size=10)["content"][0]["text"])
            all_facilities.extend(result["facilities"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Filter to Active only
        active_facs = [f for f in all_facilities
                       if f["operating_status"] == "Active"]

        results = []
        for fac in active_facs:
            fid = fac["facility_id"]

            # Get sensor readings
            sr = json.loads(self.tools["get_sensor_readings"](facility_id=fid)["content"][0]["text"])
            readings = sr["readings"]

            # Latest reading per pollutant
            sensor_latest = {}
            for r in readings:
                pc = r["pollutant_code"]
                if pc not in sensor_latest:
                    sensor_latest[pc] = r["value"]
                # readings are already sorted by timestamp DESC

            # Get permit limits
            pl = json.loads(self.tools["get_permit_limits"](facility_id=fid))
            permits = {}
            for p in pl["permits"]:
                pc = p["pollutant_code"]
                if pc not in permits or p["daily_max"] < permits[pc]:
                    permits[pc] = p["daily_max"]

            # 1. Exceedance score
            exceedance_score = 0.0
            for pc in sensor_latest:
                if pc not in permits:
                    continue
                sensor_val = sensor_latest[pc]
                lab_val = lab_data.get((fid, pc))
                effective_val = sensor_val
                if lab_val is not None and lab_val > sensor_val:
                    effective_val = lab_val
                limit = permits[pc]
                if effective_val > limit:
                    excess = (effective_val - limit) / limit
                    tier_m = hazard_mult.get(pc, 1.0)
                    exceedance_score += excess * tier_m

            # Get violations
            vr = json.loads(self.tools["get_violation_records"](facility_id=fid))

            # 2. Violation score
            violation_score = 0.0
            for v in vr["violations"]:
                sev = v["severity"]
                insp = datetime.strptime(v["inspection_date"], "%Y-%m-%d")
                days_ago = (ref_date - insp).days
                if days_ago <= 90:
                    rw = recency_w["last_90_days"]
                elif days_ago <= 180:
                    rw = recency_w["last_180_days"]
                elif days_ago <= 365:
                    rw = recency_w["last_365_days"]
                else:
                    rw = recency_w["older"]
                base = sev * rw
                if not v["resolved"]:
                    base *= unresolved_mult_val
                violation_score += base

            # Get maintenance
            ms = json.loads(self.tools["get_maintenance_status"](facility_id=fid)["content"][0]["text"])

            # 3. Maintenance risk score
            maintenance_score = float(
                sum(1 for m in ms["maintenance_logs"]
                    if m["status"] == "Overdue")
            )

            # 4. Lab discrepancy score
            lab_disc_count = 0
            for pc, sv in sensor_latest.items():
                lv = lab_data.get((fid, pc))
                if lv is not None and sv > 0 and (lv - sv) / sv > 0.10:
                    lab_disc_count += 1
            lab_disc_score = float(lab_disc_count)

            # 5. Corrective action score
            ca_score = float(overdue_ca.get(fid, 0))

            # Weighted raw score
            raw = (
                exceedance_score * weights["exceedance"]
                + violation_score * weights["violation_history"]
                + maintenance_score * weights["maintenance_risk"]
                + lab_disc_score * weights["lab_discrepancy"]
                + ca_score * weights["corrective_action"]
            )

            # Primary concern
            components = {
                "Exceedance": exceedance_score * weights["exceedance"],
                "Violations": violation_score * weights["violation_history"],
                "Maintenance": maintenance_score * weights["maintenance_risk"],
                "Lab Discrepancy": lab_disc_score * weights["lab_discrepancy"],
                "Corrective Actions": ca_score * weights["corrective_action"],
            }
            primary = max(components, key=components.get)

            # Zone multiplier
            zm = zone_mult.get(fid, 1.0)
            risk_score = round(raw * zm, 2)

            # Risk category
            if risk_score >= cat_thresholds["CRITICAL"]:
                risk_cat = "CRITICAL"
            elif risk_score >= cat_thresholds["HIGH"]:
                risk_cat = "HIGH"
            elif risk_score >= cat_thresholds["MODERATE"]:
                risk_cat = "MODERATE"
            else:
                risk_cat = "LOW"

            # Dispatch urgency
            if risk_score >= disp_thresholds["IMMEDIATE"]:
                urgency = "IMMEDIATE"
            elif risk_score >= disp_thresholds["PRIORITY"]:
                urgency = "PRIORITY"
            elif risk_score >= disp_thresholds["ROUTINE"]:
                urgency = "ROUTINE"
            else:
                urgency = "MONITOR"

            results.append({
                "facility_id": fid,
                "facility_name": fac["name"],
                "region": fac["region"],
                "risk_score": risk_score,
                "risk_category": risk_cat,
                "primary_concern": primary,
                "dispatch_urgency": urgency,
            })

        # Sort
        results.sort(key=lambda r: (-r["risk_score"], r["facility_id"]))
        for i, r in enumerate(results, 1):
            r["rank"] = i

        # ── Step 6: Write dispatch_list.csv ─────────────────────────────
        csv_path = os.path.join(self.workspace, "dispatch_list.csv")
        columns = dispatch_cfg["output_format"]["columns"]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for r in results:
                row = {c: r[c] for c in columns}
                writer.writerow(row)

        # ── Step 7: Build action string ─────────────────────────────────
        # Count by risk category
        cat_counts = {}
        for r in results:
            cat_counts[r["risk_category"]] = cat_counts.get(
                r["risk_category"], 0) + 1

        top5 = results[:5]
        top5_lines = []
        for r in top5:
            top5_lines.append(
                f"  {r['rank']}. {r['facility_id']} ({r['facility_name']})"
                f" - Risk Score: {r['risk_score']}"
            )

        action = (
            f"Compliance risk assessment complete. "
            f"Total facilities assessed: {len(results)}.\n\n"
            f"Risk category breakdown:\n"
        )
        for cat in ["CRITICAL", "HIGH", "MODERATE", "LOW"]:
            action += f"  {cat}: {cat_counts.get(cat, 0)}\n"
        action += f"\nTop 5 highest-risk facilities:\n"
        action += "\n".join(top5_lines)
        action += (
            f"\n\nThe full prioritized dispatch list has been saved to "
            f"dispatch_list.csv with {len(results)} entries."
        )

        return self.step(action)
