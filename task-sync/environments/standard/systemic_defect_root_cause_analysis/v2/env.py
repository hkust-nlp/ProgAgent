"""
Manufacturing Defect Analysis Task - Environment

Provides tools for querying manufacturing data and evaluates the agent's
corrective action output against computed ground truth.
"""
import os
import sqlite3
import json
import csv
from typing import Tuple, Dict, List, Any
from collections import defaultdict

try:
    import yaml
except ImportError:
    raise ImportError("PyYAML is required. Install with: pip install pyyaml")


# --- Decorator for tool registration ---
def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


class Task_Env:
    PAGE_SIZE = 20

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

    # =====================================================================
    # Tool methods
    # =====================================================================

    @tool(
        description="List all assembly lines in the facility with their machine type, install date, and location.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_assembly_lines(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT line_id, line_name, machine_type, install_date, location "
            "FROM assembly_lines ORDER BY line_id"
        ).fetchall()
        conn.close()
        return {
            "data": [
                {
                    "line_id": r[0], "line_name": r[1], "machine_type": r[2],
                    "install_date": r[3], "location": r[4],
                }
                for r in rows
            ],
        }

    @tool(
        description="List all component suppliers with their country and certification.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_suppliers(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT supplier_id, supplier_name, country, certification, contact_email "
            "FROM suppliers ORDER BY supplier_id"
        ).fetchall()
        conn.close()
        return {
            "data": [
                {
                    "supplier_id": r[0], "supplier_name": r[1], "country": r[2],
                    "certification": r[3], "contact_email": r[4],
                }
                for r in rows
            ],
        }

    @tool(
        description="Get paginated sensor readings for a specific assembly line. Optionally filter by sensor type. Returns up to 20 results per page.",
        parameters={
            "type": "object",
            "properties": {
                "line_id": {
                    "type": "string",
                    "description": "Assembly line ID, e.g. LINE-001",
                },
                "sensor_type": {
                    "type": "string",
                    "description": "Optional sensor type filter: temperature, vibration, pressure, humidity, or speed",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number starting from 1 (default 1)",
                },
            },
            "required": ["line_id"],
        },
    )
    def get_sensor_readings(self, line_id: str, sensor_type: str = None, page: int = 1):
        conn = sqlite3.connect(self.db_path)
        query = "SELECT log_id, line_id, sensor_type, reading_value, reading_unit, timestamp FROM sensor_logs WHERE line_id = ?"
        params: list = [line_id]
        if sensor_type:
            query += " AND sensor_type = ?"
            params.append(sensor_type)
        query += " ORDER BY timestamp, log_id"

        rows = conn.execute(query, params).fetchall()
        conn.close()

        total = len(rows)
        start = (page - 1) * self.PAGE_SIZE
        end = start + self.PAGE_SIZE
        page_data = rows[start:end]

        return {
            "data": [
                {
                    "log_id": r[0], "line_id": r[1], "sensor_type": r[2],
                    "reading_value": r[3], "reading_unit": r[4], "timestamp": r[5],
                }
                for r in page_data
            ],
            "page": page,
            "page_size": self.PAGE_SIZE,
            "total_count": total,
            "has_more": end < total,
        }

    @tool(
        description="Get paginated component batch records for a specific supplier. Returns delivery quantities and incoming rejection counts. Up to 20 results per page.",
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "string",
                    "description": "Supplier ID, e.g. SUP-001",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number starting from 1 (default 1)",
                },
            },
            "required": ["supplier_id"],
        },
    )
    def get_supplier_batches(self, supplier_id: str, page: int = 1):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT batch_id, supplier_id, component_type, line_id, delivery_date, "
            "qty_delivered, qty_rejected_incoming "
            "FROM component_batches WHERE supplier_id = ? ORDER BY delivery_date, batch_id",
            (supplier_id,),
        ).fetchall()
        conn.close()

        total = len(rows)
        start = (page - 1) * self.PAGE_SIZE
        end = start + self.PAGE_SIZE
        page_data = rows[start:end]

        return {
            "data": [
                {
                    "batch_id": r[0], "supplier_id": r[1], "component_type": r[2],
                    "line_id": r[3], "delivery_date": r[4],
                    "qty_delivered": r[5], "qty_rejected_incoming": r[6],
                }
                for r in page_data
            ],
            "page": page,
            "page_size": self.PAGE_SIZE,
            "total_count": total,
            "has_more": end < total,
        }

    @tool(
        description="Get paginated inspection results that failed (result=FAIL). Optionally filter by assembly line. Returns up to 20 results per page.",
        parameters={
            "type": "object",
            "properties": {
                "line_id": {
                    "type": "string",
                    "description": "Optional assembly line ID to filter by",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number starting from 1 (default 1)",
                },
            },
            "required": [],
        },
    )
    def get_inspection_failures(self, line_id: str = None, page: int = 1):
        conn = sqlite3.connect(self.db_path)
        query = (
            "SELECT inspection_id, product_id, line_id, batch_id, inspection_date, "
            "result, defect_type FROM inspection_results WHERE result = 'FAIL'"
        )
        params: list = []
        if line_id:
            query += " AND line_id = ?"
            params.append(line_id)
        query += " ORDER BY inspection_date, inspection_id"

        rows = conn.execute(query, params).fetchall()
        conn.close()

        total = len(rows)
        start = (page - 1) * self.PAGE_SIZE
        end = start + self.PAGE_SIZE
        page_data = rows[start:end]

        return {
            "data": [
                {
                    "inspection_id": r[0], "product_id": r[1], "line_id": r[2],
                    "batch_id": r[3], "inspection_date": r[4],
                    "result": r[5], "defect_type": r[6],
                }
                for r in page_data
            ],
            "page": page,
            "page_size": self.PAGE_SIZE,
            "total_count": total,
            "has_more": end < total,
        }

    @tool(
        description="Get details for a single component batch by its batch ID.",
        parameters={
            "type": "object",
            "properties": {
                "batch_id": {
                    "type": "string",
                    "description": "Batch ID, e.g. BATCH-000001",
                },
            },
            "required": ["batch_id"],
        },
    )
    def get_batch_details(self, batch_id: str):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT batch_id, supplier_id, component_type, line_id, delivery_date, "
            "qty_delivered, qty_rejected_incoming "
            "FROM component_batches WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        conn.close()

        if row is None:
            return {"error": f"Batch {batch_id} not found"}

        return {
            "batch_id": row[0], "supplier_id": row[1], "component_type": row[2],
            "line_id": row[3], "delivery_date": row[4],
            "qty_delivered": row[5], "qty_rejected_incoming": row[6],
        }

    @tool(
        description="Get paginated operator shift schedule for a specific assembly line.",
        parameters={
            "type": "object",
            "properties": {
                "line_id": {
                    "type": "string",
                    "description": "Assembly line ID, e.g. LINE-001",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number starting from 1 (default 1)",
                },
            },
            "required": ["line_id"],
        },
    )
    def get_shift_schedule(self, line_id: str, page: int = 1):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT shift_id, operator_id, operator_name, line_id, shift_date, "
            "shift_type, hours_worked FROM operator_shifts WHERE line_id = ? "
            "ORDER BY shift_date, shift_type",
            (line_id,),
        ).fetchall()
        conn.close()

        total = len(rows)
        start = (page - 1) * self.PAGE_SIZE
        end = start + self.PAGE_SIZE
        page_data = rows[start:end]

        return {
            "data": [
                {
                    "shift_id": r[0], "operator_id": r[1], "operator_name": r[2],
                    "line_id": r[3], "shift_date": r[4],
                    "shift_type": r[5], "hours_worked": r[6],
                }
                for r in page_data
            ],
            "page": page,
            "page_size": self.PAGE_SIZE,
            "total_count": total,
            "has_more": end < total,
        }

    # =====================================================================
    # Ground truth computation (private helper, uses direct DB access)
    # =====================================================================

    def _compute_ground_truth(self):
        """Compute the expected corrective actions from DB + workspace files."""
        conn = sqlite3.connect(self.db_path)

        # --- Load workspace configs ---
        with open(os.path.join(self.workspace, "action_priority_config.json")) as f:
            config = json.load(f)
        with open(os.path.join(self.workspace, "defect_severity_rules.yaml")) as f:
            severity_rules = yaml.safe_load(f)

        # Calibration specs
        cal_specs = {}  # (machine_type, sensor_type) -> (min_val, max_val)
        with open(os.path.join(self.workspace, "calibration_specs.csv")) as f:
            for row in csv.DictReader(f):
                cal_specs[(row["machine_type"], row["sensor_type"])] = (
                    float(row["min_value"]), float(row["max_value"]),
                )

        # Photo analysis: inspection_id -> root_cause_indicator
        photo_data = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("photo_analysis_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for entry in json.load(f):
                        photo_data[entry["inspection_id"]] = entry["root_cause_indicator"]

        # Delivery reports: supplier_id -> [audit_scores]
        audit_scores = defaultdict(list)
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("delivery_report_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        audit_scores[row["supplier_id"]].append(float(row["audit_score"]))

        # Calibration checks: line_id -> sensor_type -> [drift_ratios]
        drift_data = defaultdict(lambda: defaultdict(list))
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("calibration_check_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                for m in data["measurements"]:
                    drift_data[m["line_id"]][m["sensor_type"]].append(m["drift_ratio"])

        # Root cause category sets
        supplier_indicators = set(severity_rules["root_cause_categories"]["supplier"]["indicators"])
        machine_indicators = set(severity_rules["root_cause_categories"]["machine"]["indicators"])

        weights = config["severity_weights"]
        precision = config["score_precision"]

        # --- Assembly lines ---
        lines = conn.execute(
            "SELECT line_id, machine_type FROM assembly_lines ORDER BY line_id"
        ).fetchall()

        # --- MACHINE RECALIBRATION ---
        machine_actions = []
        for line_id, machine_type in lines:
            sensor_readings = defaultdict(list)
            for row in conn.execute(
                "SELECT sensor_type, reading_value FROM sensor_logs WHERE line_id = ?",
                (line_id,),
            ):
                sensor_readings[row[0]].append(row[1])

            max_anomaly_rate = 0.0
            primary_sensor = None
            for st, readings in sensor_readings.items():
                spec_key = (machine_type, st)
                if spec_key not in cal_specs:
                    continue
                mn, mx = cal_specs[spec_key]
                n_anomalous = sum(1 for v in readings if v < mn or v > mx)
                rate = (n_anomalous / len(readings) * 100) if readings else 0
                if rate > max_anomaly_rate:
                    max_anomaly_rate = rate
                    primary_sensor = st

            threshold = config["machine_recalibration"]["anomaly_rate_threshold_pct"]
            if max_anomaly_rate > threshold and primary_sensor is not None:
                drifts = drift_data.get(line_id, {}).get(primary_sensor, [0])
                max_drift = max(drifts) if drifts else 0
                severity = round(
                    max_anomaly_rate * weights["anomaly_rate_weight"]
                    + max_drift * weights["drift_penalty_weight"],
                    precision,
                )
                machine_actions.append({
                    "action_type": "machine_recalibration",
                    "entity_id": line_id,
                    "severity_score": severity,
                    "anomaly_rate": max_anomaly_rate,
                    "primary_sensor": primary_sensor,
                    "max_drift": max_drift,
                })

        # --- SUPPLIER REWORK ---
        # Batch data per supplier
        supplier_batch_data = defaultdict(list)
        batch_to_supplier = {}
        for row in conn.execute(
            "SELECT batch_id, supplier_id, component_type, line_id, delivery_date, "
            "qty_delivered, qty_rejected_incoming FROM component_batches"
        ):
            rec = {
                "batch_id": row[0], "supplier_id": row[1], "component_type": row[2],
                "line_id": row[3], "delivery_date": row[4],
                "qty_delivered": row[5], "qty_rejected_incoming": row[6],
            }
            supplier_batch_data[row[1]].append(rec)
            batch_to_supplier[row[0]] = row[1]

        # Inspection failures
        failures = conn.execute(
            "SELECT inspection_id, line_id, batch_id FROM inspection_results WHERE result = 'FAIL'"
        ).fetchall()

        # Count failures by attribution
        supplier_failure_count = defaultdict(int)
        line_failure_count = defaultdict(int)
        for insp_id, fail_line_id, fail_batch_id in failures:
            indicator = photo_data.get(insp_id, "")
            sup_id = batch_to_supplier.get(fail_batch_id)
            if indicator in supplier_indicators and sup_id:
                supplier_failure_count[sup_id] += 1
            if indicator in machine_indicators:
                line_failure_count[fail_line_id] += 1

        supplier_ids = [r[0] for r in conn.execute(
            "SELECT supplier_id FROM suppliers ORDER BY supplier_id"
        ).fetchall()]

        supplier_actions = []
        for sid in supplier_ids:
            batches = supplier_batch_data.get(sid, [])
            if not batches:
                continue
            total_delivered = sum(b["qty_delivered"] for b in batches)
            total_rejected = sum(b["qty_rejected_incoming"] for b in batches)
            defect_rate = (total_rejected / total_delivered * 100) if total_delivered > 0 else 0

            threshold = config["supplier_rework"]["defect_rate_threshold_pct"]
            if defect_rate > threshold:
                scores = audit_scores.get(sid, [70.0])
                avg_audit = sum(scores) / len(scores)
                audit_thresh = config["audit_penalty_threshold"]
                audit_penalty = max(0, audit_thresh - avg_audit) * weights["audit_penalty_weight"]
                severity = round(
                    defect_rate * weights["defect_rate_weight"] + audit_penalty,
                    precision,
                )

                # Primary component: highest rejection-to-delivery ratio
                comp_rej = defaultdict(int)
                comp_del = defaultdict(int)
                for b in batches:
                    comp_rej[b["component_type"]] += b["qty_rejected_incoming"]
                    comp_del[b["component_type"]] += b["qty_delivered"]
                primary_comp = max(
                    comp_rej,
                    key=lambda c: comp_rej[c] / max(1, comp_del[c]),
                )

                supplier_actions.append({
                    "action_type": "supplier_rework",
                    "entity_id": sid,
                    "severity_score": severity,
                    "defect_rate": defect_rate,
                    "primary_component": primary_comp,
                    "avg_audit": avg_audit,
                })

        conn.close()

        # Combine, rank
        all_actions = machine_actions + supplier_actions
        all_actions.sort(key=lambda x: (-x["severity_score"], x["entity_id"]))

        # Build full output rows
        output_rows = []
        for rank, a in enumerate(all_actions, 1):
            if a["action_type"] == "supplier_rework":
                root_cause = (
                    f"Incoming defect rate: {a['defect_rate']:.1f}%; "
                    f"Primary component: {a['primary_component']}; "
                    f"Avg audit score: {a['avg_audit']:.1f}"
                )
                rec_action = (
                    f"Initiate rework program with {a['entity_id']} "
                    f"targeting {a['primary_component']} batches"
                )
                affected = supplier_failure_count.get(a["entity_id"], 0)
            else:
                root_cause = (
                    f"Sensor anomaly rate: {a['anomaly_rate']:.1f}%; "
                    f"Primary sensor: {a['primary_sensor']}; "
                    f"Max drift ratio: {a['max_drift']:.2f}"
                )
                rec_action = (
                    f"Schedule recalibration for {a['primary_sensor']} "
                    f"on {a['entity_id']}"
                )
                affected = line_failure_count.get(a["entity_id"], 0)

            output_rows.append({
                "rank": rank,
                "action_type": a["action_type"],
                "entity_id": a["entity_id"],
                "root_cause": root_cause,
                "severity_score": a["severity_score"],
                "affected_products": affected,
                "recommended_action": rec_action,
            })

        return output_rows

    # =====================================================================
    # Evaluation
    # =====================================================================

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
        expected = self._compute_ground_truth()
        criteria = {}
        total_score = 0
        max_score = 0

        # ---- 1. File exists and format (10 pts) ----
        csv_path = os.path.join(self.workspace, "corrective_actions.csv")
        file_ok = os.path.isfile(csv_path)
        expected_cols = [
            "rank", "action_type", "entity_id", "root_cause",
            "severity_score", "affected_products", "recommended_action",
        ]
        cols_ok = False
        actual_rows = []
        if file_ok:
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    actual_cols = [c.strip() for c in (reader.fieldnames or [])]
                    cols_ok = actual_cols == expected_cols
                    for row in reader:
                        actual_rows.append({k.strip(): v.strip() for k, v in row.items()})
            except Exception:
                pass

        fmt_score = (5 if file_ok else 0) + (5 if cols_ok else 0)
        criteria["file_format"] = {
            "passed": fmt_score == 10,
            "score": fmt_score,
            "max_score": 10,
            "reason": "" if fmt_score == 10 else (
                "File missing" if not file_ok else "Column mismatch"
            ),
        }
        total_score += fmt_score
        max_score += 10

        # ---- Build lookups from expected and actual ----
        expected_entities = {(r["entity_id"], r["action_type"]) for r in expected}
        actual_entities = set()
        actual_by_entity = {}
        for r in actual_rows:
            key = (r.get("entity_id", ""), r.get("action_type", ""))
            actual_entities.add(key)
            actual_by_entity[r.get("entity_id", "")] = r
        expected_by_entity = {r["entity_id"]: r for r in expected}

        # ---- 2. Entity identification (25 pts) ----
        if expected_entities:
            correct = len(expected_entities & actual_entities)
            union = len(expected_entities | actual_entities)
            ent_score = round(25 * correct / union) if union > 0 else 0
        else:
            ent_score = 25 if not actual_entities else 0

        criteria["entity_identification"] = {
            "passed": ent_score == 25,
            "score": ent_score,
            "max_score": 25,
            "reason": "" if ent_score == 25 else (
                f"Expected entities {sorted(expected_entities)}, got {sorted(actual_entities)}"
            ),
        }
        total_score += ent_score
        max_score += 25

        # ---- 3. Severity scores (25 pts) ----
        sev_points = 0
        n_expected = len(expected) or 1
        for exp in expected:
            eid = exp["entity_id"]
            act = actual_by_entity.get(eid)
            if act:
                try:
                    act_sev = float(act.get("severity_score", -9999))
                    if abs(act_sev - exp["severity_score"]) <= 1.0:
                        sev_points += 25 / n_expected
                except (ValueError, TypeError):
                    pass
        sev_score = round(sev_points)
        criteria["severity_scores"] = {
            "passed": sev_score == 25,
            "score": sev_score,
            "max_score": 25,
            "reason": "" if sev_score == 25 else "One or more severity scores outside tolerance (±1.0)",
        }
        total_score += sev_score
        max_score += 25

        # ---- 4. Ranking order (20 pts) ----
        expected_order = [r["entity_id"] for r in expected]
        actual_order = []
        try:
            sorted_actual = sorted(actual_rows, key=lambda r: int(r.get("rank", 9999)))
            actual_order = [r.get("entity_id", "") for r in sorted_actual]
        except (ValueError, TypeError):
            actual_order = [r.get("entity_id", "") for r in actual_rows]

        rank_ok = expected_order == actual_order
        rank_score = 20 if rank_ok else 0
        # Partial credit: fraction of pairwise orderings correct
        if not rank_ok and len(expected_order) > 1:
            correct_pairs = 0
            total_pairs = 0
            act_pos = {eid: i for i, eid in enumerate(actual_order)}
            for i in range(len(expected_order)):
                for j in range(i + 1, len(expected_order)):
                    ei, ej = expected_order[i], expected_order[j]
                    if ei in act_pos and ej in act_pos:
                        total_pairs += 1
                        if act_pos[ei] < act_pos[ej]:
                            correct_pairs += 1
            if total_pairs > 0:
                rank_score = round(20 * correct_pairs / total_pairs)

        criteria["ranking_order"] = {
            "passed": rank_ok,
            "score": rank_score,
            "max_score": 20,
            "reason": "" if rank_ok else f"Expected order {expected_order}, got {actual_order}",
        }
        total_score += rank_score
        max_score += 20

        # ---- 5. Affected products (10 pts) ----
        aff_points = 0
        for exp in expected:
            eid = exp["entity_id"]
            act = actual_by_entity.get(eid)
            if act:
                try:
                    act_aff = int(act.get("affected_products", -1))
                    if act_aff == exp["affected_products"]:
                        aff_points += 10 / n_expected
                except (ValueError, TypeError):
                    pass
        aff_score = round(aff_points)
        criteria["affected_products"] = {
            "passed": aff_score == 10,
            "score": aff_score,
            "max_score": 10,
            "reason": "" if aff_score == 10 else "One or more affected_products counts incorrect",
        }
        total_score += aff_score
        max_score += 10

        # ---- 6. Response summary (10 pts) ----
        resp_points = 0
        action_lower = (action or "").lower()
        for exp in expected:
            eid = exp["entity_id"]
            if eid.lower() in action_lower:
                resp_points += 10 / n_expected
        resp_score = round(resp_points)
        criteria["response_summary"] = {
            "passed": resp_score == 10,
            "score": resp_score,
            "max_score": 10,
            "reason": "" if resp_score == 10 else "Not all entity IDs mentioned in response",
        }
        total_score += resp_score
        max_score += 10

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, info

    # =====================================================================
    # Verification
    # =====================================================================

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
        import numpy as _np  # noqa: for potential use

        # ---- Read workspace config files ----
        with open(os.path.join(self.workspace, "action_priority_config.json")) as f:
            config = json.load(f)
        with open(os.path.join(self.workspace, "defect_severity_rules.yaml")) as f:
            severity_rules = yaml.safe_load(f)

        # Calibration specs
        cal_specs = {}
        with open(os.path.join(self.workspace, "calibration_specs.csv")) as f:
            for row in csv.DictReader(f):
                cal_specs[(row["machine_type"], row["sensor_type"])] = (
                    float(row["min_value"]), float(row["max_value"]),
                )

        # Photo analysis files
        photo_data = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("photo_analysis_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for entry in json.load(f):
                        photo_data[entry["inspection_id"]] = entry["root_cause_indicator"]

        # Delivery reports -> audit scores
        audit_scores = defaultdict(list)
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("delivery_report_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        audit_scores[row["supplier_id"]].append(float(row["audit_score"]))

        # Calibration checks -> drift ratios
        drift_data = defaultdict(lambda: defaultdict(list))
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("calibration_check_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                for m in data["measurements"]:
                    drift_data[m["line_id"]][m["sensor_type"]].append(m["drift_ratio"])

        # Root cause category sets
        supplier_indicators = set(
            severity_rules["root_cause_categories"]["supplier"]["indicators"]
        )
        machine_indicators = set(
            severity_rules["root_cause_categories"]["machine"]["indicators"]
        )

        weights = config["severity_weights"]
        precision = config["score_precision"]

        # ---- Get assembly lines via tool ----
        lines_result = self.tools["list_assembly_lines"]()
        lines = lines_result["data"]

        # ---- Get suppliers via tool ----
        suppliers_result = self.tools["list_suppliers"]()
        suppliers = suppliers_result["data"]

        # ---- MACHINE RECALIBRATION: get sensor readings per line ----
        machine_actions = []
        for line in lines:
            line_id = line["line_id"]
            machine_type = line["machine_type"]

            all_readings = []
            page = 1
            while True:
                result = self.tools["get_sensor_readings"](line_id=line_id, page=page)
                all_readings.extend(result["data"])
                if not result["has_more"]:
                    break
                page += 1

            sensor_readings = defaultdict(list)
            for r in all_readings:
                sensor_readings[r["sensor_type"]].append(r["reading_value"])

            max_anomaly_rate = 0.0
            primary_sensor = None
            for st, readings in sensor_readings.items():
                spec_key = (machine_type, st)
                if spec_key not in cal_specs:
                    continue
                mn, mx = cal_specs[spec_key]
                n_anom = sum(1 for v in readings if v < mn or v > mx)
                rate = (n_anom / len(readings) * 100) if readings else 0
                if rate > max_anomaly_rate:
                    max_anomaly_rate = rate
                    primary_sensor = st

            threshold = config["machine_recalibration"]["anomaly_rate_threshold_pct"]
            if max_anomaly_rate > threshold and primary_sensor is not None:
                drifts = drift_data.get(line_id, {}).get(primary_sensor, [0])
                max_drift = max(drifts) if drifts else 0
                severity = round(
                    max_anomaly_rate * weights["anomaly_rate_weight"]
                    + max_drift * weights["drift_penalty_weight"],
                    precision,
                )
                machine_actions.append({
                    "action_type": "machine_recalibration",
                    "entity_id": line_id,
                    "severity_score": severity,
                    "anomaly_rate": max_anomaly_rate,
                    "primary_sensor": primary_sensor,
                    "max_drift": max_drift,
                })

        # ---- SUPPLIER REWORK: get batches per supplier ----
        batch_to_supplier = {}
        supplier_batch_data = defaultdict(list)
        for sup in suppliers:
            sid = sup["supplier_id"]
            page = 1
            while True:
                result = self.tools["get_supplier_batches"](supplier_id=sid, page=page)
                for b in result["data"]:
                    batch_to_supplier[b["batch_id"]] = sid
                    supplier_batch_data[sid].append(b)
                if not result["has_more"]:
                    break
                page += 1

        # ---- Get all inspection failures ----
        all_failures = []
        page = 1
        while True:
            result = self.tools["get_inspection_failures"](page=page)
            all_failures.extend(result["data"])
            if not result["has_more"]:
                break
            page += 1

        # ---- Attribution counts ----
        supplier_failure_count = defaultdict(int)
        line_failure_count = defaultdict(int)
        for fail in all_failures:
            insp_id = fail["inspection_id"]
            batch_id = fail["batch_id"]
            indicator = photo_data.get(insp_id, "")
            sup_id = batch_to_supplier.get(batch_id)
            if indicator in supplier_indicators and sup_id:
                supplier_failure_count[sup_id] += 1
            if indicator in machine_indicators:
                line_failure_count[fail["line_id"]] += 1

        # ---- Compute supplier severity ----
        supplier_actions = []
        for sup in suppliers:
            sid = sup["supplier_id"]
            batches = supplier_batch_data.get(sid, [])
            if not batches:
                continue
            total_delivered = sum(b["qty_delivered"] for b in batches)
            total_rejected = sum(b["qty_rejected_incoming"] for b in batches)
            defect_rate = (total_rejected / total_delivered * 100) if total_delivered > 0 else 0

            sup_threshold = config["supplier_rework"]["defect_rate_threshold_pct"]
            if defect_rate > sup_threshold:
                scores = audit_scores.get(sid, [70.0])
                avg_audit = sum(scores) / len(scores)
                audit_thresh = config["audit_penalty_threshold"]
                audit_penalty = max(0, audit_thresh - avg_audit) * weights["audit_penalty_weight"]
                severity = round(
                    defect_rate * weights["defect_rate_weight"] + audit_penalty,
                    precision,
                )

                comp_rej = defaultdict(int)
                comp_del = defaultdict(int)
                for b in batches:
                    comp_rej[b["component_type"]] += b["qty_rejected_incoming"]
                    comp_del[b["component_type"]] += b["qty_delivered"]
                primary_comp = max(
                    comp_rej,
                    key=lambda c: comp_rej[c] / max(1, comp_del[c]),
                )

                supplier_actions.append({
                    "action_type": "supplier_rework",
                    "entity_id": sid,
                    "severity_score": severity,
                    "defect_rate": defect_rate,
                    "primary_component": primary_comp,
                    "avg_audit": avg_audit,
                })

        # ---- Combine and rank ----
        all_actions = machine_actions + supplier_actions
        all_actions.sort(key=lambda x: (-x["severity_score"], x["entity_id"]))

        # ---- Build output rows ----
        output_rows = []
        for rank, a in enumerate(all_actions, 1):
            if a["action_type"] == "supplier_rework":
                root_cause = (
                    f"Incoming defect rate: {a['defect_rate']:.1f}%; "
                    f"Primary component: {a['primary_component']}; "
                    f"Avg audit score: {a['avg_audit']:.1f}"
                )
                rec_action = (
                    f"Initiate rework program with {a['entity_id']} "
                    f"targeting {a['primary_component']} batches"
                )
                affected = supplier_failure_count.get(a["entity_id"], 0)
            else:
                root_cause = (
                    f"Sensor anomaly rate: {a['anomaly_rate']:.1f}%; "
                    f"Primary sensor: {a['primary_sensor']}; "
                    f"Max drift ratio: {a['max_drift']:.2f}"
                )
                rec_action = (
                    f"Schedule recalibration for {a['primary_sensor']} "
                    f"on {a['entity_id']}"
                )
                affected = line_failure_count.get(a["entity_id"], 0)

            output_rows.append({
                "rank": rank,
                "action_type": a["action_type"],
                "entity_id": a["entity_id"],
                "root_cause": root_cause,
                "severity_score": a["severity_score"],
                "affected_products": affected,
                "recommended_action": rec_action,
            })

        # ---- Write corrective_actions.csv ----
        csv_path = os.path.join(self.workspace, "corrective_actions.csv")
        fieldnames = [
            "rank", "action_type", "entity_id", "root_cause",
            "severity_score", "affected_products", "recommended_action",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(output_rows)

        # ---- Build action (response) string ----
        action_lines = ["Corrective Action Summary:"]
        for row in output_rows:
            action_lines.append(
                f"Rank {row['rank']}: [{row['action_type']}] {row['entity_id']} "
                f"- Severity: {row['severity_score']} - {row['root_cause']}"
            )
        action_str = "\n".join(action_lines)

        return self.step(action_str)
