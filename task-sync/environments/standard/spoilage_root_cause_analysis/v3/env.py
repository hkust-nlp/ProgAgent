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

    # ────────────────────────────────────────────────────────────────────
    # TOOLS
    # ────────────────────────────────────────────────────────────────────

    @tool(
        description=(
            "List batch IDs with basic metadata. Returns a paginated list "
            "of batches. Each entry includes batch_id, crop_type, farm_origin, "
            "and harvest_datetime."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 25, default 20).",
                },
            },
            "required": ["page"],
        },
    )
    def list_batch_ids(self, page: int, page_size: int = 20) -> dict:
        import sqlite3

        page_size = min(page_size, 25)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT batch_id, crop_type, farm_origin, harvest_datetime "
            "FROM batches ORDER BY batch_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM batches")
        total = cur.fetchone()[0]
        conn.close()
        return {
            "batches": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }

    @tool(
        description=(
            "Get full details for a single batch, including quantity_kg and "
            "initial_temp_c."
        ),
        parameters={
            "type": "object",
            "properties": {
                "batch_id": {
                    "type": "string",
                    "description": "The batch identifier (e.g. B0001).",
                },
            },
            "required": ["batch_id"],
        },
    )
    def get_batch_details(self, batch_id: str) -> dict:
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM batches WHERE batch_id = ?", (batch_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Batch {batch_id} not found"}
        return dict(row)

    @tool(
        description=(
            "Get all transport legs for a given batch. Each leg includes "
            "leg_id, vehicle_id, departure_time, arrival_time, origin, "
            "and destination."
        ),
        parameters={
            "type": "object",
            "properties": {
                "batch_id": {
                    "type": "string",
                    "description": "The batch identifier.",
                },
            },
            "required": ["batch_id"],
        },
    )
    def get_transport_legs(self, batch_id: str) -> dict:
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM transport_legs WHERE batch_id = ? ORDER BY departure_time",
            (batch_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"batch_id": batch_id, "legs": rows}

    @tool(
        description=(
            "Get temperature readings for a specific transport leg. Returns "
            "timestamp, temperature_c, and sensor_position for each reading."
        ),
        parameters={
            "type": "object",
            "properties": {
                "leg_id": {
                    "type": "string",
                    "description": "The transport leg identifier (e.g. L0001).",
                },
            },
            "required": ["leg_id"],
        },
    )
    def get_temperature_readings(self, leg_id: str) -> dict:
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM temp_readings WHERE leg_id = ? ORDER BY timestamp",
            (leg_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"leg_id": leg_id, "readings": rows}

    @tool(
        description=(
            "Get warehouse environment records for a batch. Each record "
            "includes warehouse_id, zone, check_datetime, humidity_pct, "
            "and temperature_c."
        ),
        parameters={
            "type": "object",
            "properties": {
                "batch_id": {
                    "type": "string",
                    "description": "The batch identifier.",
                },
            },
            "required": ["batch_id"],
        },
    )
    def get_warehouse_records(self, batch_id: str) -> dict:
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM warehouse_records WHERE batch_id = ? "
            "ORDER BY check_datetime",
            (batch_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"batch_id": batch_id, "records": rows}

    @tool(
        description=(
            "Get the quality inspection result for a batch. Returns "
            "inspection_date, inspector_id, spoilage_pct, defect_types, "
            "overall_grade, and notes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "batch_id": {
                    "type": "string",
                    "description": "The batch identifier.",
                },
            },
            "required": ["batch_id"],
        },
    )
    def get_inspection(self, batch_id: str) -> dict:
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM inspections WHERE batch_id = ?", (batch_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"No inspection for batch {batch_id}"}
        return dict(row)

    @tool(
        description=(
            "Find inspections where the spoilage percentage meets or exceeds "
            "a given threshold. Returns paginated results sorted by "
            "spoilage_pct descending."
        ),
        parameters={
            "type": "object",
            "properties": {
                "min_spoilage_pct": {
                    "type": "number",
                    "description": "Minimum spoilage percentage threshold.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed, default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 25, default 20).",
                },
            },
            "required": ["min_spoilage_pct"],
        },
    )
    def find_flagged_inspections(
        self, min_spoilage_pct: float, page: int = 1, page_size: int = 20
    ) -> dict:
        import sqlite3

        page_size = min(page_size, 25)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM inspections WHERE spoilage_pct >= ? "
            "ORDER BY spoilage_pct DESC LIMIT ? OFFSET ?",
            (min_spoilage_pct, page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT COUNT(*) FROM inspections WHERE spoilage_pct >= ?",
            (min_spoilage_pct,),
        )
        total = cur.fetchone()[0]
        conn.close()
        return {
            "inspections": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }

    # ────────────────────────────────────────────────────────────────────
    # STEP  (evaluation)
    # ────────────────────────────────────────────────────────────────────

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
        import sqlite3, os, json, csv, yaml
        from datetime import datetime

        # ── load configs ───────────────────────────────────────────────
        with open(os.path.join(self.workspace, "cold_chain_thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)["crop_thresholds"]

        with open(os.path.join(self.workspace, "spoilage_classification.json")) as f:
            sp_cfg = json.load(f)

        flagged_thr = sp_cfg["flagged_threshold_pct"]
        classifications = sp_cfg["classifications"]

        # ── ground truth from DB ───────────────────────────────────────
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute(
            "SELECT i.batch_id, i.spoilage_pct, "
            "b.crop_type, b.farm_origin, b.quantity_kg, b.harvest_datetime "
            "FROM inspections i JOIN batches b ON i.batch_id = b.batch_id "
            "WHERE i.spoilage_pct >= ? ORDER BY i.spoilage_pct DESC",
            (flagged_thr,),
        )
        flagged_rows = [dict(r) for r in cur.fetchall()]

        gt_analysis = []
        gt_cause_summary: Dict[str, Dict] = {}

        for row in flagged_rows:
            bid = row["batch_id"]
            crop = row["crop_type"]
            sp = row["spoilage_pct"]
            qty = row["quantity_kg"]
            h_dt = row["harvest_datetime"]
            ct = thresholds[crop]

            # severity
            severity = "none"
            for cls in classifications:
                if cls["min_spoilage_pct"] <= sp < cls["max_spoilage_pct"]:
                    severity = cls["severity"]
                    break

            # root cause (ordered rules)
            root_cause = "unknown"

            # 1. transport temp
            cur.execute(
                "SELECT MAX(tr.temperature_c) AS mx FROM temp_readings tr "
                "JOIN transport_legs tl ON tr.leg_id = tl.leg_id "
                "WHERE tl.batch_id = ?",
                (bid,),
            )
            mx_temp = cur.fetchone()["mx"]
            if mx_temp is not None and mx_temp > ct["max_transport_temp_c"]:
                root_cause = "transport_temperature_excursion"
            else:
                # 2. warehouse humidity
                cur.execute(
                    "SELECT MAX(humidity_pct) AS mx FROM warehouse_records "
                    "WHERE batch_id = ?",
                    (bid,),
                )
                mx_hum = cur.fetchone()["mx"]
                if mx_hum is not None and mx_hum > ct["max_warehouse_humidity_pct"]:
                    root_cause = "warehouse_humidity_violation"
                else:
                    # 3. delayed precooling
                    cur.execute(
                        "SELECT MIN(check_datetime) AS mn FROM warehouse_records "
                        "WHERE batch_id = ?",
                        (bid,),
                    )
                    mn_wh = cur.fetchone()["mn"]
                    if mn_wh:
                        ht = datetime.strptime(h_dt, "%Y-%m-%d %H:%M:%S")
                        et = datetime.strptime(mn_wh, "%Y-%m-%d %H:%M:%S")
                        delay_h = (et - ht).total_seconds() / 3600
                        if delay_h > ct["max_precool_delay_hours"]:
                            root_cause = "delayed_precooling"
                        else:
                            # 4. adverse field conditions
                            cur.execute(
                                "SELECT field_temperature_c, rainfall_last_24h_mm "
                                "FROM field_conditions WHERE batch_id = ?",
                                (bid,),
                            )
                            fc = cur.fetchone()
                            if fc and (
                                fc["field_temperature_c"] > ct["max_field_temp_c"]
                                or fc["rainfall_last_24h_mm"] > ct["max_rainfall_mm"]
                            ):
                                root_cause = "adverse_field_conditions"

            gt_analysis.append({
                "batch_id": bid,
                "crop_type": crop,
                "farm_origin": row["farm_origin"],
                "spoilage_pct": sp,
                "severity": severity,
                "root_cause": root_cause,
            })

            gt_cause_summary.setdefault(
                root_cause, {"batch_count": 0, "total_qty": 0.0}
            )
            gt_cause_summary[root_cause]["batch_count"] += 1
            gt_cause_summary[root_cause]["total_qty"] = round(
                gt_cause_summary[root_cause]["total_qty"] + qty, 1
            )

        conn.close()

        # ── evaluate agent output ──────────────────────────────────────
        eval_criteria: Dict[str, Dict] = {}

        # Criterion 1: CSV format (10 pts)
        csv_path = os.path.join(self.workspace, "root_cause_analysis.csv")
        expected_cols = [
            "batch_id", "crop_type", "farm_origin",
            "spoilage_pct", "severity", "root_cause",
        ]
        agent_rows: list = []
        try:
            with open(csv_path, newline="") as fh:
                reader = csv.DictReader(fh)
                agent_rows = list(reader)
                cols_ok = list(reader.fieldnames) == expected_cols
            eval_criteria["csv_format"] = {
                "passed": cols_ok,
                "score": 10 if cols_ok else 0,
                "max_score": 10,
                "reason": (
                    ""
                    if cols_ok
                    else f"Expected columns {expected_cols}, got {list(reader.fieldnames)}"
                ),
            }
        except Exception as e:
            eval_criteria["csv_format"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": f"Cannot read root_cause_analysis.csv: {e}",
            }

        # Criterion 2: Correct flagged batch IDs (20 pts)
        gt_ids = set(r["batch_id"] for r in gt_analysis)
        ag_ids = set(r["batch_id"] for r in agent_rows)
        correct_ids = gt_ids & ag_ids
        extra_ids = ag_ids - gt_ids
        if gt_ids:
            id_score = max(
                0, round(len(correct_ids) / len(gt_ids) * 20) - len(extra_ids) * 2
            )
            id_score = min(id_score, 20)
        else:
            id_score = 20 if not ag_ids else 0
        eval_criteria["batch_identification"] = {
            "passed": id_score == 20,
            "score": id_score,
            "max_score": 20,
            "reason": (
                ""
                if id_score == 20
                else f"Expected {len(gt_ids)} batches, got {len(ag_ids)} "
                f"({len(correct_ids)} correct, {len(extra_ids)} extra)"
            ),
        }

        # Criterion 3: Root cause accuracy (25 pts)
        gt_cause_map = {r["batch_id"]: r["root_cause"] for r in gt_analysis}
        ag_cause_map = {r["batch_id"]: r.get("root_cause", "") for r in agent_rows}
        common = gt_ids & ag_ids
        matching_causes = (
            sum(1 for b in common if ag_cause_map.get(b) == gt_cause_map.get(b))
            if common
            else 0
        )
        cause_score = (
            round(matching_causes / len(gt_ids) * 25) if gt_ids else 0
        )
        eval_criteria["root_cause_accuracy"] = {
            "passed": cause_score == 25,
            "score": cause_score,
            "max_score": 25,
            "reason": (
                ""
                if cause_score == 25
                else f"{matching_causes}/{len(gt_ids)} correct root causes"
            ),
        }

        # Criterion 4: Severity accuracy (15 pts)
        gt_sev_map = {r["batch_id"]: r["severity"] for r in gt_analysis}
        ag_sev_map = {r["batch_id"]: r.get("severity", "") for r in agent_rows}
        matching_sev = (
            sum(1 for b in common if ag_sev_map.get(b) == gt_sev_map.get(b))
            if common
            else 0
        )
        sev_score = round(matching_sev / len(gt_ids) * 15) if gt_ids else 0
        eval_criteria["severity_accuracy"] = {
            "passed": sev_score == 15,
            "score": sev_score,
            "max_score": 15,
            "reason": (
                ""
                if sev_score == 15
                else f"{matching_sev}/{len(gt_ids)} correct severities"
            ),
        }

        # Criterion 5: Sort order — spoilage_pct descending (10 pts)
        try:
            sorted_ok = all(
                float(agent_rows[i]["spoilage_pct"])
                >= float(agent_rows[i + 1]["spoilage_pct"])
                for i in range(len(agent_rows) - 1)
            )
        except (KeyError, ValueError):
            sorted_ok = False
        sort_score = 10 if sorted_ok else 0
        eval_criteria["sort_order"] = {
            "passed": sorted_ok,
            "score": sort_score,
            "max_score": 10,
            "reason": "" if sorted_ok else "Rows not sorted by spoilage_pct descending",
        }

        # Criterion 6: corrective_actions.json (10 pts)
        ca_path = os.path.join(self.workspace, "corrective_actions.json")
        ca_score = 0
        ca_reason = ""
        try:
            with open(ca_path) as fh:
                agent_ca = json.load(fh)
            gt_cats = set(gt_cause_summary.keys()) - {"unknown"}
            ag_cats = set(agent_ca.keys())
            if gt_cats <= ag_cats:
                ca_score += 5
                counts_ok = True
                for cat in gt_cats:
                    if cat in agent_ca:
                        if agent_ca[cat].get("batch_count") != gt_cause_summary[cat]["batch_count"]:
                            counts_ok = False
                        agent_qty = agent_ca[cat].get("total_affected_quantity_kg", 0)
                        if abs(float(agent_qty) - gt_cause_summary[cat]["total_qty"]) > 1.0:
                            counts_ok = False
                if counts_ok:
                    ca_score += 5
                else:
                    ca_reason = "Category counts or quantities mismatch"
            else:
                ca_reason = f"Missing categories: {gt_cats - ag_cats}"
        except Exception as e:
            ca_reason = f"Cannot read corrective_actions.json: {e}"
        eval_criteria["corrective_actions"] = {
            "passed": ca_score == 10,
            "score": ca_score,
            "max_score": 10,
            "reason": ca_reason,
        }

        # Criterion 7: Action string summary (10 pts)
        act_score = 0
        act_reason = ""
        expected_total_str = f"Total flagged batches: {len(gt_analysis)}"
        if expected_total_str in action:
            act_score += 5
        else:
            act_reason += f"Missing '{expected_total_str}' in action. "

        if gt_cause_summary:
            highest = max(
                gt_cause_summary.items(), key=lambda x: x[1]["total_qty"]
            )
            if highest[0] in action:
                act_score += 5
            else:
                act_reason += f"Missing highest-impact cause '{highest[0]}' in action."
        else:
            act_score += 5

        eval_criteria["action_summary"] = {
            "passed": act_score == 10,
            "score": act_score,
            "max_score": 10,
            "reason": act_reason,
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ────────────────────────────────────────────────────────────────────
    # VERIFY
    # ────────────────────────────────────────────────────────────────────

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
        import os, json, csv, yaml, glob
        from datetime import datetime

        # ── Read workspace config files ────────────────────────────────
        with open(os.path.join(self.workspace, "cold_chain_thresholds.yaml")) as f:
            crop_thresh = yaml.safe_load(f)["crop_thresholds"]

        with open(os.path.join(self.workspace, "spoilage_classification.json")) as f:
            sp_cfg = json.load(f)
        flagged_thr = sp_cfg["flagged_threshold_pct"]
        classifications = sp_cfg["classifications"]

        with open(os.path.join(self.workspace, "corrective_action_guidelines.md")) as f:
            guidelines_text = f.read()

        # ── Read field-condition reports from workspace CSVs ───────────
        field_cond: Dict[str, dict] = {}
        for fp in sorted(
            glob.glob(
                os.path.join(self.workspace, "field_conditions_report_*.csv")
            )
        ):
            with open(fp, newline="") as fh:
                for row in csv.DictReader(fh):
                    field_cond[row["batch_id"]] = row

        # ── Find flagged batches via tool ──────────────────────────────
        flagged_inspections: list = []
        page = 1
        while True:
            result = self.tools["find_flagged_inspections"](
                min_spoilage_pct=flagged_thr, page=page, page_size=20
            )
            flagged_inspections.extend(result["inspections"])
            if not result["has_more"]:
                break
            page += 1

        # ── Analyse each flagged batch ─────────────────────────────────
        analysis_rows: list = []
        cause_summary: Dict[str, Dict] = {}

        for insp in flagged_inspections:
            bid = insp["batch_id"]
            sp = insp["spoilage_pct"]

            # batch details (tool call)
            batch = self.tools["get_batch_details"](batch_id=bid)
            crop = batch["crop_type"]
            farm = batch["farm_origin"]
            qty = batch["quantity_kg"]
            h_dt = batch["harvest_datetime"]
            ct = crop_thresh[crop]

            # severity
            severity = "none"
            for cls in classifications:
                if cls["min_spoilage_pct"] <= sp < cls["max_spoilage_pct"]:
                    severity = cls["severity"]
                    break

            # ── root cause classification (ordered rules) ──────────────
            root_cause = "unknown"

            # Rule 1: transport temperature excursion
            legs_result = self.tools["get_transport_legs"](batch_id=bid)
            max_temp = float("-inf")
            for leg in legs_result["legs"]:
                readings = self.tools["get_temperature_readings"](
                    leg_id=leg["leg_id"]
                )
                for rd in readings["readings"]:
                    if rd["temperature_c"] > max_temp:
                        max_temp = rd["temperature_c"]

            if max_temp > ct["max_transport_temp_c"]:
                root_cause = "transport_temperature_excursion"
            else:
                # Rule 2: warehouse humidity violation
                wh_result = self.tools["get_warehouse_records"](batch_id=bid)
                max_hum = max(
                    r["humidity_pct"] for r in wh_result["records"]
                )
                if max_hum > ct["max_warehouse_humidity_pct"]:
                    root_cause = "warehouse_humidity_violation"
                else:
                    # Rule 3: delayed precooling
                    harvest_time = datetime.strptime(h_dt, "%Y-%m-%d %H:%M:%S")
                    earliest_wh = min(
                        datetime.strptime(r["check_datetime"], "%Y-%m-%d %H:%M:%S")
                        for r in wh_result["records"]
                    )
                    delay_h = (earliest_wh - harvest_time).total_seconds() / 3600
                    if delay_h > ct["max_precool_delay_hours"]:
                        root_cause = "delayed_precooling"
                    else:
                        # Rule 4: adverse field conditions
                        fc = field_cond.get(bid)
                        if fc:
                            ft = float(fc["field_temperature_c"])
                            rf = float(fc["rainfall_last_24h_mm"])
                            if (
                                ft > ct["max_field_temp_c"]
                                or rf > ct["max_rainfall_mm"]
                            ):
                                root_cause = "adverse_field_conditions"

            analysis_rows.append({
                "batch_id": bid,
                "crop_type": crop,
                "farm_origin": farm,
                "spoilage_pct": sp,
                "severity": severity,
                "root_cause": root_cause,
            })

            cause_summary.setdefault(
                root_cause,
                {"batch_count": 0, "total_qty": 0.0, "batches": []},
            )
            cause_summary[root_cause]["batch_count"] += 1
            cause_summary[root_cause]["total_qty"] = round(
                cause_summary[root_cause]["total_qty"] + qty, 1
            )
            cause_summary[root_cause]["batches"].append(bid)

        # ── Sort by spoilage_pct descending ────────────────────────────
        analysis_rows.sort(key=lambda x: x["spoilage_pct"], reverse=True)

        # ── Write root_cause_analysis.csv ──────────────────────────────
        csv_path = os.path.join(self.workspace, "root_cause_analysis.csv")
        fieldnames = [
            "batch_id", "crop_type", "farm_origin",
            "spoilage_pct", "severity", "root_cause",
        ]
        with open(csv_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(analysis_rows)

        # ── Build corrective_actions.json ──────────────────────────────
        action_map = {
            "transport_temperature_excursion": {
                "recommended_actions": [
                    "Immediately inspect and recalibrate the vehicle refrigeration unit",
                    "Review and reduce maximum allowable transit duration for the affected route",
                    "Install redundant temperature monitoring sensors",
                    "Implement pre-departure cooling verification checklist",
                ],
                "priority": "HIGH",
            },
            "warehouse_humidity_violation": {
                "recommended_actions": [
                    "Inspect and service HVAC systems in the affected warehouse zone",
                    "Increase humidity monitoring frequency to every 30 minutes",
                    "Install additional dehumidification units in the affected zone",
                    "Review and update zone assignment criteria for moisture-sensitive crops",
                ],
                "priority": "HIGH",
            },
            "delayed_precooling": {
                "recommended_actions": [
                    "Implement forced-air precooling at the farm gate",
                    "Reduce field-to-cooler target time by deploying mobile cooling units",
                    "Adjust harvest scheduling to cooler hours of the day",
                    "Establish maximum field hold times with automatic alerts",
                ],
                "priority": "MEDIUM",
            },
            "adverse_field_conditions": {
                "recommended_actions": [
                    "Adjust harvest windows based on weather forecasts to avoid peak temperatures",
                    "Implement field-level quality gates with immediate rejection criteria",
                    "Deploy shade structures for staging areas",
                    "Increase post-harvest inspection frequency for weather-affected batches",
                ],
                "priority": "MEDIUM",
            },
        }

        corrective_actions = {}
        for cause, summary in cause_summary.items():
            if cause in action_map:
                corrective_actions[cause] = {
                    "batch_count": summary["batch_count"],
                    "total_affected_quantity_kg": summary["total_qty"],
                    "recommended_actions": action_map[cause]["recommended_actions"],
                    "priority": action_map[cause]["priority"],
                }

        ca_path = os.path.join(self.workspace, "corrective_actions.json")
        with open(ca_path, "w") as fh:
            json.dump(corrective_actions, fh, indent=2)

        # ── Build action string ────────────────────────────────────────
        total_flagged = len(analysis_rows)
        lines = [f"Total flagged batches: {total_flagged}"]
        for cause in sorted(cause_summary.keys()):
            s = cause_summary[cause]
            lines.append(
                f"{cause}: {s['batch_count']} batches, {s['total_qty']} kg"
            )
        if cause_summary:
            highest = max(
                cause_summary.items(), key=lambda x: x[1]["total_qty"]
            )
            lines.append(
                f"Highest impact root cause: {highest[0]} ({highest[1]['total_qty']} kg)"
            )
        action = "\n".join(lines)

        return self.step(action)
