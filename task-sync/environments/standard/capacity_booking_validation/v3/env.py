import sqlite3
import os
import json
import yaml
import csv
import glob
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

    # ----------------------------------------------------------------
    # Tool methods
    # ----------------------------------------------------------------

    @tool(
        description="Retrieve details for a specific pipeline segment by its identifier.",
        parameters={
            "type": "object",
            "properties": {
                "segment_id": {
                    "type": "string",
                    "description": "The segment identifier, e.g. SEG-0001",
                },
            },
            "required": ["segment_id"],
        },
    )
    def get_segment_info(self, segment_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT segment_id, name, max_capacity_mmbtu, region, diameter_inches, length_miles "
            "FROM segments WHERE segment_id = ?",
            (segment_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Segment {segment_id} not found"}
        return dict(row)

    @tool(
        description="Retrieve profile information for a specific shipper.",
        parameters={
            "type": "object",
            "properties": {
                "shipper_id": {
                    "type": "string",
                    "description": "The shipper identifier, e.g. SHP-0001",
                },
            },
            "required": ["shipper_id"],
        },
    )
    def get_shipper_profile(self, shipper_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT shipper_id, company_name, contract_tier, reliability_score "
            "FROM shippers WHERE shipper_id = ?",
            (shipper_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Shipper {shipper_id} not found"}
        return dict(row)

    @tool(
        description=(
            "Query scheduled maintenance events for a pipeline segment that are active "
            "on a given date. Returns a list of maintenance events whose date range "
            "covers the specified date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "segment_id": {
                    "type": "string",
                    "description": "The segment identifier, e.g. SEG-0001",
                },
                "date": {
                    "type": "string",
                    "description": "The date to check in YYYY-MM-DD format",
                },
            },
            "required": ["segment_id", "date"],
        },
    )
    def query_maintenance(self, segment_id: str, date: str) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT event_id, equipment_type, capacity_reduction_pct, description "
            "FROM maintenance_events "
            "WHERE segment_id = ? AND start_date <= ? AND end_date >= ?",
            (segment_id, date, date),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @tool(
        description=(
            "Get the flow volatility metrics for a pipeline segment based on "
            "the most recent analysis period."
        ),
        parameters={
            "type": "object",
            "properties": {
                "segment_id": {
                    "type": "string",
                    "description": "The segment identifier, e.g. SEG-0001",
                },
            },
            "required": ["segment_id"],
        },
    )
    def get_flow_volatility(self, segment_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT segment_id, volatility_index, mean_flow_mmbtu, std_flow_mmbtu, period "
            "FROM flow_volatility WHERE segment_id = ? ORDER BY period DESC LIMIT 1",
            (segment_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"No volatility data for segment {segment_id}"}
        return dict(row)

    @tool(
        description=(
            "Get the weather forecast for a specific region on a given date, "
            "including severity level."
        ),
        parameters={
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": "The region name, e.g. Northeast",
                },
                "date": {
                    "type": "string",
                    "description": "The date in YYYY-MM-DD format",
                },
            },
            "required": ["region", "date"],
        },
    )
    def get_weather_forecast(self, region: str, date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT forecast_id, region, forecast_date, weather_type, severity, "
            "wind_speed_mph, temperature_f, precipitation_inches "
            "FROM weather_forecasts WHERE region = ? AND forecast_date = ? LIMIT 1",
            (region, date),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"No forecast for region {region} on {date}"}
        return dict(row)

    # ----------------------------------------------------------------
    # Shared helpers (used by both step and verify)
    # ----------------------------------------------------------------

    def _load_policy(self) -> dict:
        path = os.path.join(self.workspace, "allocation_policy.yaml")
        with open(path) as f:
            return yaml.safe_load(f)

    def _load_pending_reservations(self) -> list:
        """Load all pending reservation nominations from workspace CSV files."""
        records = []
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "reservation_batch_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row["nominated_volume_mmbtu"] = float(row["nominated_volume_mmbtu"])
                    records.append(row)
        return records

    def _load_priority_flags(self) -> dict:
        """Load priority flags from workspace JSON files. Returns {reservation_id: flag}."""
        flags = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "priority_flags_*.json"))):
            with open(fpath) as f:
                flags.update(json.load(f))
        return flags

    def _load_equipment_factors(self) -> dict:
        """Load equipment age factors from workspace YAML files. Returns {segment_id: factor}."""
        factors = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "equipment_factors_*.yaml"))):
            with open(fpath) as f:
                data = yaml.safe_load(f)
                if data:
                    for sid, info in data.items():
                        factors[sid] = info["equipment_age_factor"]
        return factors

    def _load_regulatory_limits(self) -> dict:
        """Load regulatory capacity limits from workspace TXT files. Returns {segment_id: limit}."""
        limits = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "regulatory_limits_*.txt"))):
            with open(fpath) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("|")
                    if len(parts) == 2:
                        sid = parts[0].strip()
                        val = float(parts[1].strip())
                        limits[sid] = val
        return limits

    def _compute_ground_truth(self):
        """Compute the expected allocation using DB + workspace data."""
        policy = self._load_policy()
        pending = self._load_pending_reservations()
        pf_flags = self._load_priority_flags()
        eq_factors = self._load_equipment_factors()
        reg_limits = self._load_regulatory_limits()
        target_date = policy["target_date"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Gather unique segments and shippers
        unique_segments = set(r["segment_id"] for r in pending)
        unique_shippers = set(r["shipper_id"] for r in pending)

        # Segment info
        seg_info = {}
        for sid in unique_segments:
            row = conn.execute(
                "SELECT * FROM segments WHERE segment_id = ?", (sid,)
            ).fetchone()
            if row:
                seg_info[sid] = dict(row)

        # Shipper info
        shp_info = {}
        for shid in unique_shippers:
            row = conn.execute(
                "SELECT * FROM shippers WHERE shipper_id = ?", (shid,)
            ).fetchone()
            if row:
                shp_info[shid] = dict(row)

        # Weather by region
        regions_needed = set(seg_info[sid]["region"] for sid in unique_segments if sid in seg_info)
        weather_by_region = {}
        for region in regions_needed:
            row = conn.execute(
                "SELECT * FROM weather_forecasts WHERE region = ? AND forecast_date = ? LIMIT 1",
                (region, target_date),
            ).fetchone()
            if row:
                weather_by_region[region] = dict(row)

        # Volatility by segment
        vol_by_seg = {}
        for sid in unique_segments:
            row = conn.execute(
                "SELECT * FROM flow_volatility WHERE segment_id = ? ORDER BY period DESC LIMIT 1",
                (sid,),
            ).fetchone()
            if row:
                vol_by_seg[sid] = dict(row)

        # Maintenance by segment
        maint_by_seg = {}
        for sid in unique_segments:
            rows = conn.execute(
                "SELECT * FROM maintenance_events WHERE segment_id = ? AND start_date <= ? AND end_date >= ?",
                (sid, target_date, target_date),
            ).fetchall()
            maint_by_seg[sid] = [dict(r) for r in rows]

        conn.close()

        # Compute effective capacities
        sev_adj = {int(k): v for k, v in policy["weather_severity_adjustments"].items()}
        vol_thresholds = policy["volatility_thresholds"]
        vol_margins = policy["volatility_safety_margins"]
        maint_cap = policy["maintenance_reduction_cap"]
        rounding = policy["capacity_rounding_decimals"]
        pf_rank = policy["priority_flag_rank"]
        tier_rank = policy["tier_priority_rank"]

        effective_caps = {}
        segment_details = {}  # for report

        for sid in unique_segments:
            if sid not in seg_info:
                continue
            info = seg_info[sid]
            base_cap = info["max_capacity_mmbtu"]

            # Regulatory limit
            if sid in reg_limits:
                base_cap = min(base_cap, reg_limits[sid])

            # Maintenance reduction
            events = maint_by_seg.get(sid, [])
            age_factor = eq_factors.get(sid, 1.0)
            total_maint = 0.0
            for ev in events:
                total_maint += ev["capacity_reduction_pct"] / 100.0 * age_factor
            total_maint = min(total_maint, maint_cap)
            eff = base_cap * (1.0 - total_maint)

            # Weather adjustment
            region = info["region"]
            wx = weather_by_region.get(region, {})
            severity = wx.get("severity", 1)
            weather_adj = sev_adj.get(severity, 0.0)
            eff *= (1.0 - weather_adj)

            # Volatility margin
            vdata = vol_by_seg.get(sid, {})
            vol_idx = vdata.get("volatility_index", 0.0)
            if vol_idx < vol_thresholds["low_max"]:
                vol_margin = vol_margins["low"]
            elif vol_idx < vol_thresholds["moderate_max"]:
                vol_margin = vol_margins["moderate"]
            else:
                vol_margin = vol_margins["high"]
            eff *= (1.0 - vol_margin)

            eff = round(eff, rounding)
            effective_caps[sid] = eff
            segment_details[sid] = {
                "max_capacity": info["max_capacity_mmbtu"],
                "maintenance_reduction": round(total_maint * 100, 2),
                "weather_adjustment": round(weather_adj * 100, 2),
                "volatility_margin": round(vol_margin * 100, 2),
            }

        # Build allocation records sorted by segment, then priority
        all_records = []
        for r in pending:
            sid = r["segment_id"]
            shid = r["shipper_id"]
            rid = r["reservation_id"]
            if sid not in seg_info or shid not in shp_info:
                continue
            s = shp_info[shid]
            pf = pf_flags.get(rid, "normal")
            all_records.append({
                "segment_id": sid,
                "segment_name": seg_info[sid]["name"],
                "reservation_id": rid,
                "shipper_id": shid,
                "shipper_name": s["company_name"],
                "contract_tier": s["contract_tier"],
                "reliability_score": s["reliability_score"],
                "priority_flag": pf,
                "nominated_volume_mmbtu": r["nominated_volume_mmbtu"],
                "effective_segment_capacity_mmbtu": effective_caps.get(sid, 0.0),
            })

        # Sort: segment_id asc, then priority order
        def sort_key(rec):
            return (
                rec["segment_id"],
                pf_rank.get(rec["priority_flag"], 2),
                tier_rank.get(rec["contract_tier"], 3),
                0 if rec["priority_flag"] == "critical" else 1,
                -rec["reliability_score"],
                rec["reservation_id"],
            )

        all_records.sort(key=sort_key)

        # Greedy allocation per segment
        remaining = {}
        for rec in all_records:
            sid = rec["segment_id"]
            if sid not in remaining:
                remaining[sid] = effective_caps.get(sid, 0.0)
            alloc = min(rec["nominated_volume_mmbtu"], remaining[sid])
            alloc = round(alloc, rounding)
            remaining[sid] = round(remaining[sid] - alloc, rounding)
            rec["allocated_capacity_mmbtu"] = alloc
            if alloc >= rec["nominated_volume_mmbtu"]:
                rec["allocation_status"] = "confirmed"
            elif alloc > 0:
                rec["allocation_status"] = "curtailed"
            else:
                rec["allocation_status"] = "rejected"

        return all_records, effective_caps

    # ----------------------------------------------------------------
    # step
    # ----------------------------------------------------------------

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        expected_records, expected_eff_caps = self._compute_ground_truth()

        criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: Report file exists with correct columns (15 pts) ---
        c1_max = 15
        report_path = os.path.join(self.workspace, "capacity_allocation_report.csv")
        expected_cols = [
            "segment_id", "segment_name", "reservation_id", "shipper_id",
            "shipper_name", "contract_tier", "reliability_score", "priority_flag",
            "nominated_volume_mmbtu", "allocated_capacity_mmbtu",
            "allocation_status", "effective_segment_capacity_mmbtu",
        ]
        report_rows = []
        if os.path.exists(report_path):
            with open(report_path) as f:
                reader = csv.DictReader(f)
                actual_cols = reader.fieldnames or []
                report_rows = list(reader)
            if list(actual_cols) == expected_cols:
                c1_score = c1_max
                c1_pass = True
                c1_reason = ""
            else:
                c1_score = 5  # partial: file exists but wrong columns
                c1_pass = False
                c1_reason = f"Column mismatch. Expected {expected_cols}, got {list(actual_cols)}"
        else:
            c1_score = 0
            c1_pass = False
            c1_reason = "Report file not found"
        criteria["report_structure"] = {
            "passed": c1_pass, "score": c1_score, "max_score": c1_max,
            "reason": c1_reason if not c1_pass else "",
        }
        total_score += c1_score
        max_score += c1_max

        # --- Criterion 2: Correct row count (10 pts) ---
        c2_max = 10
        if len(report_rows) == len(expected_records):
            c2_score = c2_max
            c2_pass = True
            c2_reason = ""
        else:
            c2_score = 0
            c2_pass = False
            c2_reason = f"Expected {len(expected_records)} rows, got {len(report_rows)}"
        criteria["row_count"] = {
            "passed": c2_pass, "score": c2_score, "max_score": c2_max,
            "reason": c2_reason if not c2_pass else "",
        }
        total_score += c2_score
        max_score += c2_max

        # --- Criterion 3: Effective capacity accuracy (20 pts) ---
        c3_max = 20
        if report_rows and expected_records:
            # Build expected effective caps by segment
            expected_eff_by_seg = {}
            for rec in expected_records:
                expected_eff_by_seg[rec["segment_id"]] = rec["effective_segment_capacity_mmbtu"]
            # Build actual from report
            actual_eff_by_seg = {}
            for row in report_rows:
                sid = row.get("segment_id", "")
                try:
                    actual_eff_by_seg[sid] = float(row.get("effective_segment_capacity_mmbtu", 0))
                except (ValueError, TypeError):
                    pass
            correct = 0
            total_segs = len(expected_eff_by_seg)
            for sid, exp_val in expected_eff_by_seg.items():
                act_val = actual_eff_by_seg.get(sid)
                if act_val is not None and abs(act_val - exp_val) < 0.02:
                    correct += 1
            if total_segs > 0:
                c3_score = round(c3_max * correct / total_segs)
            else:
                c3_score = 0
            c3_pass = c3_score == c3_max
            c3_reason = "" if c3_pass else f"{correct}/{total_segs} segments correct"
        else:
            c3_score = 0
            c3_pass = False
            c3_reason = "No data to compare"
        criteria["effective_capacity"] = {
            "passed": c3_pass, "score": c3_score, "max_score": c3_max,
            "reason": c3_reason if not c3_pass else "",
        }
        total_score += c3_score
        max_score += c3_max

        # --- Criterion 4: Allocation amounts accuracy (25 pts) ---
        c4_max = 25
        if report_rows and expected_records and len(report_rows) == len(expected_records):
            # Match by reservation_id
            expected_by_rid = {r["reservation_id"]: r for r in expected_records}
            correct = 0
            total = len(expected_records)
            for row in report_rows:
                rid = row.get("reservation_id", "")
                if rid in expected_by_rid:
                    try:
                        actual_alloc = float(row.get("allocated_capacity_mmbtu", -1))
                        exp_alloc = expected_by_rid[rid]["allocated_capacity_mmbtu"]
                        if abs(actual_alloc - exp_alloc) < 0.02:
                            correct += 1
                    except (ValueError, TypeError):
                        pass
            c4_score = round(c4_max * correct / total) if total > 0 else 0
            c4_pass = c4_score == c4_max
            c4_reason = "" if c4_pass else f"{correct}/{total} allocations correct"
        else:
            c4_score = 0
            c4_pass = False
            c4_reason = "Row count mismatch or no data"
        criteria["allocation_amounts"] = {
            "passed": c4_pass, "score": c4_score, "max_score": c4_max,
            "reason": c4_reason if not c4_pass else "",
        }
        total_score += c4_score
        max_score += c4_max

        # --- Criterion 5: Allocation status accuracy (15 pts) ---
        c5_max = 15
        if report_rows and expected_records and len(report_rows) == len(expected_records):
            expected_by_rid = {r["reservation_id"]: r for r in expected_records}
            correct = 0
            total = len(expected_records)
            for row in report_rows:
                rid = row.get("reservation_id", "")
                if rid in expected_by_rid:
                    if row.get("allocation_status") == expected_by_rid[rid]["allocation_status"]:
                        correct += 1
            c5_score = round(c5_max * correct / total) if total > 0 else 0
            c5_pass = c5_score == c5_max
            c5_reason = "" if c5_pass else f"{correct}/{total} statuses correct"
        else:
            c5_score = 0
            c5_pass = False
            c5_reason = "Row count mismatch or no data"
        criteria["allocation_status"] = {
            "passed": c5_pass, "score": c5_score, "max_score": c5_max,
            "reason": c5_reason if not c5_pass else "",
        }
        total_score += c5_score
        max_score += c5_max

        # --- Criterion 6: Summary statistics in response (15 pts) ---
        c6_max = 15
        summary_checks = 0
        total_checks = 5

        # Expected summary stats
        n_segments = len(set(r["segment_id"] for r in expected_records))
        n_reservations = len(expected_records)
        n_confirmed = sum(1 for r in expected_records if r["allocation_status"] == "confirmed")
        n_curtailed = sum(1 for r in expected_records if r["allocation_status"] == "curtailed")
        n_rejected = sum(1 for r in expected_records if r["allocation_status"] == "rejected")
        total_nominated = round(sum(r["nominated_volume_mmbtu"] for r in expected_records), 2)
        total_allocated = round(sum(r["allocated_capacity_mmbtu"] for r in expected_records), 2)
        sum_eff = round(sum(expected_eff_caps[sid] for sid in set(r["segment_id"] for r in expected_records)), 2)
        utilization = round(total_allocated / sum_eff * 100, 2) if sum_eff > 0 else 0.0

        action_lower = action.lower() if action else ""

        if str(n_segments) in action:
            summary_checks += 1
        if str(n_confirmed) in action:
            summary_checks += 1
        if str(n_curtailed) in action:
            summary_checks += 1
        if str(n_rejected) in action:
            summary_checks += 1
        # Check utilization rate (allow some formatting variation)
        util_str = f"{utilization:.2f}"
        if util_str in action or f"{utilization:.1f}" in action or str(round(utilization)) in action:
            summary_checks += 1

        c6_score = round(c6_max * summary_checks / total_checks)
        c6_pass = summary_checks == total_checks
        c6_reason = "" if c6_pass else f"{summary_checks}/{total_checks} summary items found"
        criteria["summary_statistics"] = {
            "passed": c6_pass, "score": c6_score, "max_score": c6_max,
            "reason": c6_reason if not c6_pass else "",
        }
        total_score += c6_score
        max_score += c6_max

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ----------------------------------------------------------------
    # verify
    # ----------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import glob as _glob

        # 1. Load allocation policy
        policy_path = os.path.join(self.workspace, "allocation_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)

        target_date = policy["target_date"]
        tier_rank = policy["tier_priority_rank"]
        pf_rank = policy["priority_flag_rank"]
        sev_adj = {int(k): v for k, v in policy["weather_severity_adjustments"].items()}
        vol_thresholds = policy["volatility_thresholds"]
        vol_margins = policy["volatility_safety_margins"]
        maint_cap = policy["maintenance_reduction_cap"]
        rounding = policy["capacity_rounding_decimals"]

        # 2. Load pending reservations from workspace CSVs
        pending = []
        for fpath in sorted(_glob.glob(os.path.join(self.workspace, "reservation_batch_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row["nominated_volume_mmbtu"] = float(row["nominated_volume_mmbtu"])
                    pending.append(row)

        # 3. Load priority flags from workspace JSONs
        pf_flags = {}
        for fpath in sorted(_glob.glob(os.path.join(self.workspace, "priority_flags_*.json"))):
            with open(fpath) as f:
                pf_flags.update(json.load(f))

        # 4. Load equipment age factors from workspace YAMLs
        eq_factors = {}
        for fpath in sorted(_glob.glob(os.path.join(self.workspace, "equipment_factors_*.yaml"))):
            with open(fpath) as f:
                data = yaml.safe_load(f)
                if data:
                    for sid, info in data.items():
                        eq_factors[sid] = info["equipment_age_factor"]

        # 5. Load regulatory limits from workspace TXTs
        reg_limits = {}
        for fpath in sorted(_glob.glob(os.path.join(self.workspace, "regulatory_limits_*.txt"))):
            with open(fpath) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("|")
                    if len(parts) == 2:
                        sid = parts[0].strip()
                        val = float(parts[1].strip())
                        reg_limits[sid] = val

        # 6. Gather unique segment IDs and shipper IDs
        unique_segments = sorted(set(r["segment_id"] for r in pending))
        unique_shippers = sorted(set(r["shipper_id"] for r in pending))

        # 7. Call tools for segment info
        seg_info = {}
        for sid in unique_segments:
            seg_info[sid] = self.tools["get_segment_info"](segment_id=sid)

        # 8. Call tools for shipper info
        shp_info = {}
        for shid in unique_shippers:
            shp_info[shid] = self.tools["get_shipper_profile"](shipper_id=shid)

        # 9. Call tools for maintenance
        maint_by_seg = {}
        for sid in unique_segments:
            maint_by_seg[sid] = self.tools["query_maintenance"](segment_id=sid, date=target_date)

        # 10. Call tools for volatility
        vol_by_seg = {}
        for sid in unique_segments:
            vol_by_seg[sid] = self.tools["get_flow_volatility"](segment_id=sid)

        # 11. Call tools for weather (by unique regions)
        regions_needed = sorted(set(seg_info[sid]["region"] for sid in unique_segments if "region" in seg_info[sid]))
        weather_by_region = {}
        for region in regions_needed:
            weather_by_region[region] = self.tools["get_weather_forecast"](region=region, date=target_date)

        # 12. Compute effective capacities
        effective_caps = {}
        for sid in unique_segments:
            info = seg_info[sid]
            if "error" in info:
                continue
            base_cap = info["max_capacity_mmbtu"]
            if sid in reg_limits:
                base_cap = min(base_cap, reg_limits[sid])

            # Maintenance
            events = maint_by_seg.get(sid, [])
            age_factor = eq_factors.get(sid, 1.0)
            total_maint = 0.0
            for ev in events:
                total_maint += ev["capacity_reduction_pct"] / 100.0 * age_factor
            total_maint = min(total_maint, maint_cap)
            eff = base_cap * (1.0 - total_maint)

            # Weather
            region = info["region"]
            wx = weather_by_region.get(region, {})
            severity = wx.get("severity", 1)
            weather_adj = sev_adj.get(severity, 0.0)
            eff *= (1.0 - weather_adj)

            # Volatility
            vdata = vol_by_seg.get(sid, {})
            vol_idx = vdata.get("volatility_index", 0.0)
            if vol_idx < vol_thresholds["low_max"]:
                vol_margin = vol_margins["low"]
            elif vol_idx < vol_thresholds["moderate_max"]:
                vol_margin = vol_margins["moderate"]
            else:
                vol_margin = vol_margins["high"]
            eff *= (1.0 - vol_margin)

            eff = round(eff, rounding)
            effective_caps[sid] = eff

        # 13. Build allocation records
        all_records = []
        for r in pending:
            sid = r["segment_id"]
            shid = r["shipper_id"]
            rid = r["reservation_id"]
            if sid not in seg_info or "error" in seg_info[sid]:
                continue
            if shid not in shp_info or "error" in shp_info[shid]:
                continue
            s = shp_info[shid]
            pf = pf_flags.get(rid, "normal")
            all_records.append({
                "segment_id": sid,
                "segment_name": seg_info[sid]["name"],
                "reservation_id": rid,
                "shipper_id": shid,
                "shipper_name": s["company_name"],
                "contract_tier": s["contract_tier"],
                "reliability_score": s["reliability_score"],
                "priority_flag": pf,
                "nominated_volume_mmbtu": r["nominated_volume_mmbtu"],
                "effective_segment_capacity_mmbtu": effective_caps.get(sid, 0.0),
            })

        # 14. Sort by segment_id, then priority order
        def sort_key(rec):
            return (
                rec["segment_id"],
                pf_rank.get(rec["priority_flag"], 2),
                tier_rank.get(rec["contract_tier"], 3),
                0 if rec["priority_flag"] == "critical" else 1,
                -rec["reliability_score"],
                rec["reservation_id"],
            )
        all_records.sort(key=sort_key)

        # 15. Greedy allocation
        remaining = {}
        for rec in all_records:
            sid = rec["segment_id"]
            if sid not in remaining:
                remaining[sid] = effective_caps.get(sid, 0.0)
            alloc = min(rec["nominated_volume_mmbtu"], remaining[sid])
            alloc = round(alloc, rounding)
            remaining[sid] = round(remaining[sid] - alloc, rounding)
            rec["allocated_capacity_mmbtu"] = alloc
            if alloc >= rec["nominated_volume_mmbtu"]:
                rec["allocation_status"] = "confirmed"
            elif alloc > 0:
                rec["allocation_status"] = "curtailed"
            else:
                rec["allocation_status"] = "rejected"

        # 16. Write report CSV
        report_path = os.path.join(self.workspace, "capacity_allocation_report.csv")
        fieldnames = [
            "segment_id", "segment_name", "reservation_id", "shipper_id",
            "shipper_name", "contract_tier", "reliability_score", "priority_flag",
            "nominated_volume_mmbtu", "allocated_capacity_mmbtu",
            "allocation_status", "effective_segment_capacity_mmbtu",
        ]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rec in all_records:
                out = {k: rec[k] for k in fieldnames}
                out["reliability_score"] = f"{rec['reliability_score']:.1f}"
                out["nominated_volume_mmbtu"] = f"{rec['nominated_volume_mmbtu']:.2f}"
                out["allocated_capacity_mmbtu"] = f"{rec['allocated_capacity_mmbtu']:.2f}"
                out["effective_segment_capacity_mmbtu"] = f"{rec['effective_segment_capacity_mmbtu']:.2f}"
                writer.writerow(out)

        # 17. Build summary
        n_segments = len(set(r["segment_id"] for r in all_records))
        n_reservations = len(all_records)
        n_confirmed = sum(1 for r in all_records if r["allocation_status"] == "confirmed")
        n_curtailed = sum(1 for r in all_records if r["allocation_status"] == "curtailed")
        n_rejected = sum(1 for r in all_records if r["allocation_status"] == "rejected")
        total_nominated = round(sum(r["nominated_volume_mmbtu"] for r in all_records), 2)
        total_allocated = round(sum(r["allocated_capacity_mmbtu"] for r in all_records), 2)
        sum_eff = round(sum(effective_caps[sid] for sid in set(r["segment_id"] for r in all_records)), 2)
        utilization = round(total_allocated / sum_eff * 100, 2) if sum_eff > 0 else 0.0

        action = (
            f"Capacity Allocation Summary:\n"
            f"Total segments processed: {n_segments}\n"
            f"Total reservations: {n_reservations}\n"
            f"Confirmed: {n_confirmed}\n"
            f"Curtailed: {n_curtailed}\n"
            f"Rejected: {n_rejected}\n"
            f"Total nominated volume: {total_nominated:.2f} MMBtu\n"
            f"Total allocated capacity: {total_allocated:.2f} MMBtu\n"
            f"Overall utilization rate: {utilization:.2f}%\n"
        )

        return self.step(action)
