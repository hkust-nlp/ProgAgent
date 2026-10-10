import sqlite3
import os
import json
import csv
import math
from typing import Tuple, Dict, List, Any


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

    # ===================== TOOL METHODS =====================

    @tool(
        description="List all catalytic cracking units with basic information. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default is 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of units per page. Maximum 10. Default is 10.",
                },
            },
            "required": [],
        },
    )
    def list_units(self, page: int = 1, page_size: int = 10) -> dict:
        page_size = min(page_size, 10)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Get distinct units from latest inspection
        rows = conn.execute("""
            SELECT unit_id, unit_name, refinery, unit_type, capacity_bpd
            FROM unit_inspections
            WHERE inspection_id IN (
                SELECT MAX(inspection_id) FROM unit_inspections GROUP BY unit_id
            )
            ORDER BY unit_id
            LIMIT ? OFFSET ?
        """, (page_size, offset)).fetchall()
        total = conn.execute(
            "SELECT COUNT(DISTINCT unit_id) FROM unit_inspections"
        ).fetchone()[0]
        conn.close()
        return {
            "units": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total_units": total,
            "total_pages": math.ceil(total / page_size),
        }

    @tool(
        description="Get detailed inspection history for a specific unit.",
        parameters={
            "type": "object",
            "properties": {
                "unit_id": {
                    "type": "string",
                    "description": "The unit identifier, e.g. 'FCC-01'.",
                },
            },
            "required": ["unit_id"],
        },
    )
    def get_unit_details(self, unit_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM unit_inspections WHERE unit_id = ? ORDER BY inspection_date DESC",
            (unit_id,),
        ).fetchall()
        conn.close()
        if not rows:
            return {"error": f"No data found for unit {unit_id}"}
        return {
            "unit_id": unit_id,
            "inspections": [dict(r) for r in rows],
        }

    @tool(
        description="Get the active catalyst batch information for a specific unit, including catalyst type, supplier, load date, initial activity, and expected lifetime.",
        parameters={
            "type": "object",
            "properties": {
                "unit_id": {
                    "type": "string",
                    "description": "The unit identifier, e.g. 'FCC-01'.",
                },
            },
            "required": ["unit_id"],
        },
    )
    def get_catalyst_info(self, unit_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM catalyst_batches WHERE unit_id = ? AND status = 'active' ORDER BY load_date DESC LIMIT 1",
            (unit_id,),
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"No active catalyst batch found for unit {unit_id}"}
        return dict(row)

    @tool(
        description="Get activity measurement logs for a specific unit's active catalyst batch. Returns measurements sorted by date. Use limit and offset for pagination.",
        parameters={
            "type": "object",
            "properties": {
                "unit_id": {
                    "type": "string",
                    "description": "The unit identifier, e.g. 'FCC-01'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of records to return. Default 20, max 50.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip. Default 0.",
                },
            },
            "required": ["unit_id"],
        },
    )
    def get_activity_logs(self, unit_id: str, limit: int = 20, offset: int = 0) -> dict:
        limit = min(limit, 50)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Get active batch
        batch = conn.execute(
            "SELECT batch_id FROM catalyst_batches WHERE unit_id = ? AND status = 'active' LIMIT 1",
            (unit_id,),
        ).fetchone()
        if not batch:
            conn.close()
            return {"error": f"No active batch for unit {unit_id}", "measurements": []}
        batch_id = batch[0]
        total = conn.execute(
            "SELECT COUNT(*) FROM activity_measurements WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM activity_measurements WHERE batch_id = ? ORDER BY measurement_date LIMIT ? OFFSET ?",
            (batch_id, limit, offset),
        ).fetchall()
        conn.close()
        return {
            "unit_id": unit_id,
            "batch_id": batch_id,
            "measurements": [dict(r) for r in rows],
            "total_records": total,
            "limit": limit,
            "offset": offset,
        }

    @tool(
        description="Get throughput records for a specific unit. Returns records sorted by date. Use limit and offset for pagination.",
        parameters={
            "type": "object",
            "properties": {
                "unit_id": {
                    "type": "string",
                    "description": "The unit identifier, e.g. 'FCC-01'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of records to return. Default 20, max 50.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip. Default 0.",
                },
            },
            "required": ["unit_id"],
        },
    )
    def get_throughput_data(self, unit_id: str, limit: int = 20, offset: int = 0) -> dict:
        limit = min(limit, 50)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(
            "SELECT COUNT(*) FROM throughput_records WHERE unit_id = ?",
            (unit_id,),
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM throughput_records WHERE unit_id = ? ORDER BY record_date LIMIT ? OFFSET ?",
            (unit_id, limit, offset),
        ).fetchall()
        conn.close()
        return {
            "unit_id": unit_id,
            "records": [dict(r) for r in rows],
            "total_records": total,
            "limit": limit,
            "offset": offset,
        }

    @tool(
        description="Get energy consumption records for a specific unit. Returns records sorted by date. Use limit and offset for pagination.",
        parameters={
            "type": "object",
            "properties": {
                "unit_id": {
                    "type": "string",
                    "description": "The unit identifier, e.g. 'FCC-01'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of records to return. Default 20, max 50.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of records to skip. Default 0.",
                },
            },
            "required": ["unit_id"],
        },
    )
    def get_energy_data(self, unit_id: str, limit: int = 20, offset: int = 0) -> dict:
        limit = min(limit, 50)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(
            "SELECT COUNT(*) FROM energy_consumption WHERE unit_id = ?",
            (unit_id,),
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM energy_consumption WHERE unit_id = ? ORDER BY record_date LIMIT ? OFFSET ?",
            (unit_id, limit, offset),
        ).fetchall()
        conn.close()
        return {
            "unit_id": unit_id,
            "records": [dict(r) for r in rows],
            "total_records": total,
            "limit": limit,
            "offset": offset,
        }

    # ===================== STEP (EVALUATION) =====================

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        eval_criteria = {}
        total_score = 0
        max_score = 0

        # Compute ground truth
        gt = self._compute_ground_truth()

        # Criterion 1: maintenance_priority.csv exists and has correct columns (15 pts)
        c1_max = 15
        c1_score = 0
        c1_reason = ""
        csv_path = os.path.join(self.workspace, "maintenance_priority.csv")
        expected_cols = [
            "unit_id", "unit_name", "priority_rank", "priority_score",
            "activity_decline_rate", "energy_efficiency_ratio",
            "feedstock_severity_score", "conversion_loss_pct",
            "catalyst_age_days", "recommended_action", "estimated_downtime_days",
        ]
        csv_data = []
        if os.path.exists(csv_path):
            with open(csv_path, "r") as f:
                reader = csv.DictReader(f)
                actual_cols = reader.fieldnames or []
                csv_data = list(reader)
            if set(expected_cols).issubset(set(actual_cols)):
                c1_score = c1_max
            else:
                missing = set(expected_cols) - set(actual_cols)
                c1_score = 5
                c1_reason = f"Missing columns: {missing}"
        else:
            c1_reason = "maintenance_priority.csv not found"
        eval_criteria["csv_format"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": c1_reason,
        }

        # Criterion 2: All units present (15 pts)
        c2_max = 15
        c2_score = 0
        c2_reason = ""
        gt_unit_ids = set(gt.keys())
        csv_unit_ids = set(r.get("unit_id", "") for r in csv_data)
        if csv_data:
            present = gt_unit_ids & csv_unit_ids
            ratio = len(present) / len(gt_unit_ids) if gt_unit_ids else 0
            c2_score = round(c2_max * ratio)
            if ratio < 1.0:
                c2_reason = f"Missing units: {gt_unit_ids - csv_unit_ids}"
        else:
            c2_reason = "No CSV data"
        eval_criteria["all_units_present"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": c2_reason,
        }

        # Criterion 3: Priority scores correct within tolerance (20 pts)
        c3_max = 20
        c3_score = 0
        c3_reason = ""
        if csv_data:
            correct = 0
            total_units = len(gt_unit_ids)
            for row in csv_data:
                uid = row.get("unit_id", "")
                if uid in gt:
                    try:
                        agent_score = float(row.get("priority_score", -1))
                        gt_score = gt[uid]["priority_score"]
                        if abs(agent_score - gt_score) <= 2.0:
                            correct += 1
                    except (ValueError, TypeError):
                        pass
            ratio = correct / total_units if total_units else 0
            c3_score = round(c3_max * ratio)
            if ratio < 1.0:
                c3_reason = f"{correct}/{total_units} scores within tolerance"
        else:
            c3_reason = "No CSV data"
        eval_criteria["priority_scores"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": c3_reason,
        }

        # Criterion 4: Correct ranking order (15 pts)
        c4_max = 15
        c4_score = 0
        c4_reason = ""
        if csv_data:
            gt_ranking = sorted(gt.keys(), key=lambda u: (-gt[u]["priority_score"], u))
            csv_ranking = [r.get("unit_id", "") for r in csv_data]
            # Check if ordering by score descending is correct
            if csv_ranking == gt_ranking:
                c4_score = c4_max
            else:
                # Partial credit: check pairwise order
                n = min(len(csv_ranking), len(gt_ranking))
                matches = sum(1 for i in range(n) if csv_ranking[i] == gt_ranking[i])
                ratio = matches / len(gt_ranking) if gt_ranking else 0
                c4_score = round(c4_max * ratio)
                c4_reason = f"{matches}/{len(gt_ranking)} positions correct"
        else:
            c4_reason = "No CSV data"
        eval_criteria["ranking_order"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": c4_reason,
        }

        # Criterion 5: Correct recommended actions (15 pts)
        c5_max = 15
        c5_score = 0
        c5_reason = ""
        if csv_data:
            correct = 0
            total_units = len(gt_unit_ids)
            for row in csv_data:
                uid = row.get("unit_id", "")
                if uid in gt:
                    agent_action = row.get("recommended_action", "").strip()
                    gt_action = gt[uid]["recommended_action"]
                    if agent_action == gt_action:
                        correct += 1
            ratio = correct / total_units if total_units else 0
            c5_score = round(c5_max * ratio)
            if ratio < 1.0:
                c5_reason = f"{correct}/{total_units} actions correct"
        else:
            c5_reason = "No CSV data"
        eval_criteria["recommended_actions"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": c5_reason,
        }

        # Criterion 6: Correct estimated downtime (10 pts)
        c6_max = 10
        c6_score = 0
        c6_reason = ""
        if csv_data:
            correct = 0
            total_units = len(gt_unit_ids)
            for row in csv_data:
                uid = row.get("unit_id", "")
                if uid in gt:
                    try:
                        agent_dt = int(float(row.get("estimated_downtime_days", -1)))
                        gt_dt = gt[uid]["estimated_downtime_days"]
                        if agent_dt == gt_dt:
                            correct += 1
                    except (ValueError, TypeError):
                        pass
            ratio = correct / total_units if total_units else 0
            c6_score = round(c6_max * ratio)
            if ratio < 1.0:
                c6_reason = f"{correct}/{total_units} downtime values correct"
        else:
            c6_reason = "No CSV data"
        eval_criteria["downtime_values"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": c6_reason,
        }

        # Criterion 7: Response contains summary of critical/high priority units (10 pts)
        c7_max = 10
        c7_score = 0
        c7_reason = ""
        critical_high_units = [
            uid for uid, v in gt.items()
            if v["priority_score"] >= 50
        ]
        if action:
            found = sum(1 for uid in critical_high_units if uid in action)
            if critical_high_units:
                ratio = found / len(critical_high_units)
                c7_score = round(c7_max * ratio)
                if ratio < 1.0:
                    c7_reason = f"Only {found}/{len(critical_high_units)} critical/high units mentioned"
            else:
                c7_score = c7_max  # No critical units to mention
        else:
            c7_reason = "Empty response"
        eval_criteria["response_summary"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": c7_reason,
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score if max_score > 0 else 0.0, info

    def _compute_ground_truth(self) -> dict:
        """Compute ground truth priority list from DB and workspace files."""
        import yaml

        # Load scoring config
        with open(os.path.join(self.workspace, "scoring_config.yaml"), "r") as f:
            config = yaml.safe_load(f)

        # Load catalyst reference
        with open(os.path.join(self.workspace, "catalyst_reference.json"), "r") as f:
            cat_ref = json.load(f)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Get all units
        units_rows = conn.execute("""
            SELECT unit_id, unit_name, refinery, unit_type, capacity_bpd
            FROM unit_inspections
            WHERE inspection_id IN (
                SELECT MAX(inspection_id) FROM unit_inspections GROUP BY unit_id
            )
            ORDER BY unit_id
        """).fetchall()
        units = [dict(r) for r in units_rows]

        # Load feedstock data from workspace
        feedstock_data = self._load_feedstock_data()

        results = {}
        weights = config["weights"]
        norm = config["normalization"]
        energy_conv = config["energy_conversion"]
        fs_weights = config["feedstock_severity_weights"]
        tiers = config["tiers"]
        reference_date_str = "2025-12-31"
        from datetime import datetime
        reference_date = datetime.strptime(reference_date_str, "%Y-%m-%d")

        for u in units:
            uid = u["unit_id"]

            # Get active catalyst batch
            batch = conn.execute(
                "SELECT * FROM catalyst_batches WHERE unit_id = ? AND status = 'active' ORDER BY load_date DESC LIMIT 1",
                (uid,),
            ).fetchone()
            if not batch:
                continue
            batch = dict(batch)
            cat_type = batch["catalyst_type"]
            load_date = datetime.strptime(batch["load_date"], "%Y-%m-%d")
            catalyst_age_days = (reference_date - load_date).days
            expected_lifetime = batch["expected_lifetime_days"]

            # Activity decline
            activity_rows = conn.execute(
                "SELECT * FROM activity_measurements WHERE batch_id = ? ORDER BY measurement_date",
                (batch["batch_id"],),
            ).fetchall()
            activity_rows = [dict(r) for r in activity_rows]

            if len(activity_rows) >= 2:
                first_act = activity_rows[0]["activity_index"]
                last_act = activity_rows[-1]["activity_index"]
                first_date = datetime.strptime(activity_rows[0]["measurement_date"], "%Y-%m-%d")
                last_date = datetime.strptime(activity_rows[-1]["measurement_date"], "%Y-%m-%d")
                days_between = (last_date - first_date).days
                if days_between > 0 and first_act > 0:
                    activity_decline_rate = (first_act - last_act) / first_act * 100 / (days_between / 30)
                else:
                    activity_decline_rate = 0.0
            else:
                activity_decline_rate = 0.0

            # Throughput - conversion loss
            tp_rows = conn.execute(
                "SELECT * FROM throughput_records WHERE unit_id = ? ORDER BY record_date",
                (uid,),
            ).fetchall()
            tp_rows = [dict(r) for r in tp_rows]

            baseline_conversion = cat_ref[cat_type]["baseline_conversion"]
            if len(tp_rows) >= 2:
                current_conversion = sum(r["conversion_pct"] for r in tp_rows[-2:]) / 2
            elif len(tp_rows) == 1:
                current_conversion = tp_rows[0]["conversion_pct"]
            else:
                current_conversion = baseline_conversion
            conversion_loss = baseline_conversion - current_conversion

            # Energy efficiency ratio
            energy_rows = conn.execute(
                "SELECT * FROM energy_consumption WHERE unit_id = ? ORDER BY record_date",
                (uid,),
            ).fetchall()
            energy_rows = [dict(r) for r in energy_rows]

            if len(energy_rows) >= 2 and len(tp_rows) >= 2:
                # Match energy records with throughput records by date proximity
                energy_per_bbl = []
                for er in energy_rows:
                    total_energy = (
                        er["fuel_gas_mmbtu"]
                        + er["steam_klb"] * energy_conv["steam_to_mmbtu"]
                        + er["electricity_mwh"] * energy_conv["electricity_to_mmbtu"]
                    )
                    # Find closest throughput record
                    er_date = datetime.strptime(er["record_date"], "%Y-%m-%d")
                    closest_tp = min(
                        tp_rows,
                        key=lambda t: abs(
                            (datetime.strptime(t["record_date"], "%Y-%m-%d") - er_date).days
                        ),
                    )
                    feed_rate = closest_tp["feed_rate_bpd"]
                    if feed_rate > 0:
                        energy_per_bbl.append(total_energy / feed_rate)

                if len(energy_per_bbl) >= 2:
                    mid = len(energy_per_bbl) // 2
                    first_half = energy_per_bbl[:mid]
                    second_half = energy_per_bbl[mid:]
                    avg_first = sum(first_half) / len(first_half) if first_half else 1
                    avg_second = sum(second_half) / len(second_half) if second_half else 1
                    energy_efficiency_ratio = avg_second / avg_first if avg_first > 0 else 1.0
                else:
                    energy_efficiency_ratio = 1.0
            else:
                energy_efficiency_ratio = 1.0

            # Feedstock severity
            unit_feedstock = feedstock_data.get(uid, [])
            if unit_feedstock:
                severities = []
                for fs in unit_feedstock:
                    sev = (
                        fs["sulfur_pct"] * fs_weights["sulfur_pct"]
                        + fs["ccr_pct"] * fs_weights["ccr_pct"]
                        + (fs["nitrogen_ppm"] / 1000) * fs_weights["nitrogen_per_1000ppm"]
                        + (fs["nickel_ppm"] / 10) * fs_weights["nickel_per_10ppm"]
                        + (fs["vanadium_ppm"] / 10) * fs_weights["vanadium_per_10ppm"]
                    )
                    severities.append(sev)
                feedstock_severity = sum(severities) / len(severities)
            else:
                feedstock_severity = 0.0

            # Catalyst age factor
            catalyst_age_factor = catalyst_age_days / expected_lifetime if expected_lifetime > 0 else 0

            # Normalize factors
            def normalize(value, vmin, vmax):
                if vmax == vmin:
                    return 0.0
                return max(0.0, min(1.0, (value - vmin) / (vmax - vmin))) * 100

            norm_activity = normalize(
                activity_decline_rate, norm["activity_decline"]["min"], norm["activity_decline"]["max"]
            )
            norm_energy = normalize(
                energy_efficiency_ratio, norm["energy_efficiency"]["min"], norm["energy_efficiency"]["max"]
            )
            norm_feedstock = normalize(
                feedstock_severity, norm["feedstock_severity"]["min"], norm["feedstock_severity"]["max"]
            )
            norm_conversion = normalize(
                conversion_loss, norm["conversion_loss"]["min"], norm["conversion_loss"]["max"]
            )
            norm_age = normalize(
                catalyst_age_factor, norm["catalyst_age"]["min"], norm["catalyst_age"]["max"]
            )

            # Priority score
            priority_score = (
                weights["activity_decline"] * norm_activity
                + weights["energy_efficiency"] * norm_energy
                + weights["feedstock_severity"] * norm_feedstock
                + weights["conversion_loss"] * norm_conversion
                + weights["catalyst_age"] * norm_age
            )
            priority_score = round(priority_score, 2)

            # Tier and action
            if priority_score >= tiers["critical"]["min_score"]:
                tier = "critical"
            elif priority_score >= tiers["high"]["min_score"]:
                tier = "high"
            elif priority_score >= tiers["medium"]["min_score"]:
                tier = "medium"
            else:
                tier = "low"

            if tier == "critical" and catalyst_age_factor > 1.5:
                action = "immediate_replacement"
                downtime = 14
            elif tier == "critical":
                action = "emergency_regeneration"
                downtime = 10
            elif tier == "high":
                action = "scheduled_regeneration"
                downtime = 7
            elif tier == "medium":
                action = "enhanced_monitoring"
                downtime = 3
            else:
                action = "normal_operation"
                downtime = 0

            results[uid] = {
                "unit_id": uid,
                "unit_name": u["unit_name"],
                "priority_score": priority_score,
                "activity_decline_rate": round(activity_decline_rate, 2),
                "energy_efficiency_ratio": round(energy_efficiency_ratio, 2),
                "feedstock_severity_score": round(feedstock_severity, 2),
                "conversion_loss_pct": round(conversion_loss, 2),
                "catalyst_age_days": catalyst_age_days,
                "recommended_action": action,
                "estimated_downtime_days": downtime,
                "tier": tier,
                "catalyst_age_factor": round(catalyst_age_factor, 2),
            }

        conn.close()
        return results

    def _load_feedstock_data(self) -> dict:
        """Load feedstock data from all CSV files in workspace."""
        feedstock = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("feedstock_report_") and fname.endswith(".csv"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        uid = row["unit_id"]
                        if uid not in feedstock:
                            feedstock[uid] = []
                        feedstock[uid].append({
                            "sulfur_pct": float(row["sulfur_pct"]),
                            "ccr_pct": float(row["ccr_pct"]),
                            "nitrogen_ppm": float(row["nitrogen_ppm"]),
                            "nickel_ppm": float(row["nickel_ppm"]),
                            "vanadium_ppm": float(row["vanadium_ppm"]),
                        })
        return feedstock

    # ===================== VERIFY =====================

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml
        from datetime import datetime

        # Step 1: Load config files from workspace
        with open(os.path.join(self.workspace, "scoring_config.yaml"), "r") as f:
            config = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "catalyst_reference.json"), "r") as f:
            cat_ref = json.load(f)

        with open(os.path.join(self.workspace, "maintenance_guidelines.txt"), "r") as f:
            guidelines = f.read()

        weights = config["weights"]
        norm = config["normalization"]
        energy_conv = config["energy_conversion"]
        fs_weights = config["feedstock_severity_weights"]
        tiers_config = config["tiers"]

        # Step 2: Load feedstock data from workspace files
        feedstock_data = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("feedstock_report_") and fname.endswith(".csv"):
                fpath = os.path.join(self.workspace, fname)
                with open(fpath, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        uid = row["unit_id"]
                        if uid not in feedstock_data:
                            feedstock_data[uid] = []
                        feedstock_data[uid].append({
                            "sulfur_pct": float(row["sulfur_pct"]),
                            "ccr_pct": float(row["ccr_pct"]),
                            "nitrogen_ppm": float(row["nitrogen_ppm"]),
                            "nickel_ppm": float(row["nickel_ppm"]),
                            "vanadium_ppm": float(row["vanadium_ppm"]),
                        })

        # Step 3: Get all units via tool
        all_units = []
        page = 1
        while True:
            result = self.tools["list_units"](page=page, page_size=10)
            all_units.extend(result["units"])
            if page >= result["total_pages"]:
                break
            page += 1

        reference_date = datetime(2025, 12, 31)
        unit_results = []

        # Step 4: For each unit, gather data via tools and compute metrics
        for u in all_units:
            uid = u["unit_id"]

            # Get catalyst info
            cat_info = self.tools["get_catalyst_info"](unit_id=uid)
            if "error" in cat_info:
                continue
            cat_type = cat_info["catalyst_type"]
            load_date = datetime.strptime(cat_info["load_date"], "%Y-%m-%d")
            catalyst_age_days = (reference_date - load_date).days
            expected_lifetime = cat_info["expected_lifetime_days"]
            catalyst_age_factor = catalyst_age_days / expected_lifetime if expected_lifetime > 0 else 0

            # Get activity logs (all pages)
            all_activity = []
            offset = 0
            while True:
                act_result = self.tools["get_activity_logs"](unit_id=uid, limit=50, offset=offset)
                all_activity.extend(act_result["measurements"])
                if offset + len(act_result["measurements"]) >= act_result["total_records"]:
                    break
                offset += 50

            # Activity decline rate
            if len(all_activity) >= 2:
                first_act = all_activity[0]["activity_index"]
                last_act = all_activity[-1]["activity_index"]
                first_date = datetime.strptime(all_activity[0]["measurement_date"], "%Y-%m-%d")
                last_date = datetime.strptime(all_activity[-1]["measurement_date"], "%Y-%m-%d")
                days_between = (last_date - first_date).days
                if days_between > 0 and first_act > 0:
                    activity_decline_rate = (first_act - last_act) / first_act * 100 / (days_between / 30)
                else:
                    activity_decline_rate = 0.0
            else:
                activity_decline_rate = 0.0

            # Get throughput data (all pages)
            all_throughput = []
            offset = 0
            while True:
                tp_result = self.tools["get_throughput_data"](unit_id=uid, limit=50, offset=offset)
                all_throughput.extend(tp_result["records"])
                if offset + len(tp_result["records"]) >= tp_result["total_records"]:
                    break
                offset += 50

            # Conversion loss
            baseline_conversion = cat_ref[cat_type]["baseline_conversion"]
            if len(all_throughput) >= 2:
                current_conversion = sum(r["conversion_pct"] for r in all_throughput[-2:]) / 2
            elif len(all_throughput) == 1:
                current_conversion = all_throughput[0]["conversion_pct"]
            else:
                current_conversion = baseline_conversion
            conversion_loss = baseline_conversion - current_conversion

            # Get energy data (all pages)
            all_energy = []
            offset = 0
            while True:
                en_result = self.tools["get_energy_data"](unit_id=uid, limit=50, offset=offset)
                all_energy.extend(en_result["records"])
                if offset + len(en_result["records"]) >= en_result["total_records"]:
                    break
                offset += 50

            # Energy efficiency ratio
            if len(all_energy) >= 2 and len(all_throughput) >= 2:
                energy_per_bbl = []
                for er in all_energy:
                    total_energy = (
                        er["fuel_gas_mmbtu"]
                        + er["steam_klb"] * energy_conv["steam_to_mmbtu"]
                        + er["electricity_mwh"] * energy_conv["electricity_to_mmbtu"]
                    )
                    er_date = datetime.strptime(er["record_date"], "%Y-%m-%d")
                    closest_tp = min(
                        all_throughput,
                        key=lambda t: abs(
                            (datetime.strptime(t["record_date"], "%Y-%m-%d") - er_date).days
                        ),
                    )
                    feed_rate = closest_tp["feed_rate_bpd"]
                    if feed_rate > 0:
                        energy_per_bbl.append(total_energy / feed_rate)

                if len(energy_per_bbl) >= 2:
                    mid = len(energy_per_bbl) // 2
                    first_half = energy_per_bbl[:mid]
                    second_half = energy_per_bbl[mid:]
                    avg_first = sum(first_half) / len(first_half) if first_half else 1
                    avg_second = sum(second_half) / len(second_half) if second_half else 1
                    energy_efficiency_ratio = avg_second / avg_first if avg_first > 0 else 1.0
                else:
                    energy_efficiency_ratio = 1.0
            else:
                energy_efficiency_ratio = 1.0

            # Feedstock severity
            unit_feedstock = feedstock_data.get(uid, [])
            if unit_feedstock:
                severities = []
                for fs in unit_feedstock:
                    sev = (
                        fs["sulfur_pct"] * fs_weights["sulfur_pct"]
                        + fs["ccr_pct"] * fs_weights["ccr_pct"]
                        + (fs["nitrogen_ppm"] / 1000) * fs_weights["nitrogen_per_1000ppm"]
                        + (fs["nickel_ppm"] / 10) * fs_weights["nickel_per_10ppm"]
                        + (fs["vanadium_ppm"] / 10) * fs_weights["vanadium_per_10ppm"]
                    )
                    severities.append(sev)
                feedstock_severity = sum(severities) / len(severities)
            else:
                feedstock_severity = 0.0

            # Normalize
            def normalize(value, vmin, vmax):
                if vmax == vmin:
                    return 0.0
                return max(0.0, min(1.0, (value - vmin) / (vmax - vmin))) * 100

            norm_activity = normalize(
                activity_decline_rate, norm["activity_decline"]["min"], norm["activity_decline"]["max"]
            )
            norm_energy = normalize(
                energy_efficiency_ratio, norm["energy_efficiency"]["min"], norm["energy_efficiency"]["max"]
            )
            norm_feedstock = normalize(
                feedstock_severity, norm["feedstock_severity"]["min"], norm["feedstock_severity"]["max"]
            )
            norm_conversion = normalize(
                conversion_loss, norm["conversion_loss"]["min"], norm["conversion_loss"]["max"]
            )
            norm_age = normalize(
                catalyst_age_factor, norm["catalyst_age"]["min"], norm["catalyst_age"]["max"]
            )

            priority_score = (
                weights["activity_decline"] * norm_activity
                + weights["energy_efficiency"] * norm_energy
                + weights["feedstock_severity"] * norm_feedstock
                + weights["conversion_loss"] * norm_conversion
                + weights["catalyst_age"] * norm_age
            )
            priority_score = round(priority_score, 2)

            # Tier
            if priority_score >= tiers_config["critical"]["min_score"]:
                tier = "critical"
            elif priority_score >= tiers_config["high"]["min_score"]:
                tier = "high"
            elif priority_score >= tiers_config["medium"]["min_score"]:
                tier = "medium"
            else:
                tier = "low"

            # Action (from guidelines)
            if tier == "critical" and catalyst_age_factor > 1.5:
                action = "immediate_replacement"
                downtime = 14
            elif tier == "critical":
                action = "emergency_regeneration"
                downtime = 10
            elif tier == "high":
                action = "scheduled_regeneration"
                downtime = 7
            elif tier == "medium":
                action = "enhanced_monitoring"
                downtime = 3
            else:
                action = "normal_operation"
                downtime = 0

            unit_results.append({
                "unit_id": uid,
                "unit_name": u["unit_name"],
                "priority_score": priority_score,
                "activity_decline_rate": round(activity_decline_rate, 2),
                "energy_efficiency_ratio": round(energy_efficiency_ratio, 2),
                "feedstock_severity_score": round(feedstock_severity, 2),
                "conversion_loss_pct": round(conversion_loss, 2),
                "catalyst_age_days": catalyst_age_days,
                "recommended_action": action,
                "estimated_downtime_days": downtime,
            })

        # Step 5: Sort by priority score descending, then unit_id for tie-breaking
        unit_results.sort(key=lambda x: (-x["priority_score"], x["unit_id"]))

        # Assign ranks
        for i, r in enumerate(unit_results):
            r["priority_rank"] = i + 1

        # Step 6: Write maintenance_priority.csv
        csv_path = os.path.join(self.workspace, "maintenance_priority.csv")
        fieldnames = [
            "unit_id", "unit_name", "priority_rank", "priority_score",
            "activity_decline_rate", "energy_efficiency_ratio",
            "feedstock_severity_score", "conversion_loss_pct",
            "catalyst_age_days", "recommended_action", "estimated_downtime_days",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(unit_results)

        # Step 7: Build action string
        critical_high = [r for r in unit_results if r["priority_score"] >= 50]
        summary_lines = [
            f"Maintenance priority analysis completed for {len(unit_results)} catalytic cracking units.",
            "",
        ]
        if critical_high:
            summary_lines.append(
                f"{len(critical_high)} units require immediate attention (Critical or High priority):"
            )
            for r in critical_high:
                tier = "Critical" if r["priority_score"] >= 75 else "High"
                summary_lines.append(
                    f"  - {r['unit_id']} ({r['unit_name']}): {tier} priority, "
                    f"score={r['priority_score']}, action={r['recommended_action']}, "
                    f"downtime={r['estimated_downtime_days']} days"
                )
        else:
            summary_lines.append("No units currently in Critical or High priority status.")

        summary_lines.append("")
        summary_lines.append("Full priority list has been saved to maintenance_priority.csv.")

        action_str = "\n".join(summary_lines)

        return self.step(action_str)
